"""
HTML Slide → PPTX Converter (SlideKit canonical)
Reads data-* attributes for positioning. No CSS parsing needed.
Usage: python3 html_to_pptx.py <slides.html> [output.pptx]

SlideKit編集機能(slide-edit.js)で付くdata属性に対応：
  data-x/y/w/h, data-font-size, data-bold, data-color, data-fill,
  data-bg, data-bg-gradient, data-align,
  data-bullet(disc|decimal|native-disc|native-decimal)
- data-bg-gradient が無く data-bg がある＝単色背景（背景色変更/グラデ解除に対応）
- data-bullet=disc|decimal ＝段落にぶら下げ字下げ(marL/indent)（マーカーは本文の文字）
- data-bullet=native-* ＝PowerPointネイティブ箇条書き。子要素 .li[data-lvl] を段落にし、
  buChar/buAutoNum + lvl + lstStyle を書く（PowerPoint側のEnter継続・Tabレベル送りが効く）
"""
from pptx import Presentation
from pptx.util import Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.oxml.ns import qn, nsdecls
from pptx.oxml import parse_xml
from bs4 import BeautifulSoup, Comment, NavigableString
import os, re, sys, subprocess, tempfile, shutil, base64, copy
from urllib.parse import unquote
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pptx_semantic as _SEM  # タイトル・テーマ色・代替テキスト（PPTXの「意味」）

# Pillow はオプション扱い（画像サイズ取得・webp変換用）。無くてもクラッシュせず graceful に degrade
try:
    from PIL import Image as _PILImage
    HAS_PIL = True
except Exception:
    _PILImage = None
    HAS_PIL = False


def _get_image_size(img_path):
    """画像の実ピクセルサイズ(iw, ih)を返す。取得失敗時 None。
    Pillow を最優先、無ければ sips (macOS) にフォールバック。"""
    if HAS_PIL:
        try:
            with _PILImage.open(img_path) as im:
                return im.size
        except Exception as e:
            print(f'  WARN: Pillowでサイズ取得失敗({e})、sipsにフォールバック')
    try:
        r = subprocess.run(
            ['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', img_path],
            capture_output=True, text=True, timeout=10
        )
        iw_m = re.search(r'pixelWidth:\s*(\d+)', r.stdout)
        ih_m = re.search(r'pixelHeight:\s*(\d+)', r.stdout)
        if iw_m and ih_m:
            return int(iw_m.group(1)), int(ih_m.group(1))
    except Exception:
        pass
    return None

# --- SVG→PNG ラスタライズ（Chrome headless：ブラウザと同じ見た目で描画）---
SVG_SCALE = 2  # 解像度倍率（PPTXでの精細さ）
def _find_chrome():
    cands = [
        os.environ.get('CHROME_PATH', ''),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        shutil.which('google-chrome') or '', shutil.which('chromium') or '',
        shutil.which('chromium-browser') or '',
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None
CHROME = _find_chrome()

# SVG単体ファイル書き出し（PowerPointへ手動でドラッグ＆ペースト＝ベクターで鮮明）
# 「順番一致」に依存しない設計: BeautifulSoupの html.parser(タグ名の大小保持)で生HTMLから
# 各wrapperに対応する生SVG文字列を直接抽出する。lxmlパーサが viewBox/linearGradient を
# 小文字化して壊すので、SVG抽出専用に html.parser 側のsoupを用意する。
RAW_SVG_SOUP = None  # html.parser で作った soup（属性の大小保持）
PAGENO_OFF = False   # <html data-pageno="off"> で自動ページ番号を抑止
CUR_SLIDE = 0   # 現在のスライド番号（1始まり）
SVG_OUT_DIR = None
EXPORTED_SVG = []
MISSING_ASSETS = []  # (slide, kind, x, y, w, h, reason) — Chrome 欠落等で SVG が変換できなかった記録
ALLOW_MISSING = False  # --allow-missing-assets が指定されているか (欠落を許すか)
# AWSテンプレート使用時のフラグ。表紙(暗色)スライドで文字/ロゴを黒に切替える判定に使う
USE_AWS_TEMPLATE = False
AWS_DECK = False     # <html data-template="aws|aws2"> 等でAWSを宣言したデッキか（ロゴの可否）
# --measured（試作・2026-10-14）: ブラウザの実測値（measure_layout.py）。None なら従来どおり data 属性だけで変換
MEASURED = None
MEASURE_FULL = False  # --measured 指定時だけ位置・文字書式も実測で上書きする（SVG内の文字の実測は常に使う）
# 意味付け（2026-10-14 既定ON）: タイトルをプレースホルダーに・トークン色をテーマ色にする（pptx_semantic.py）。--no-semantic で外す
SEMANTIC = True
ALT_MISSING = []     # 代替テキストの無い図 (slide, 種類, src)


def _overflow_warnings(measured, floor=4.0):
    """[F2] 文字が枠に入らない枠を、ブラウザの実測（measure_layout）から拾う（S2・2026-11-15）。
    ブラウザは .tb{overflow:hidden} で切って隠すが、PPTX は切らずに下へあふれるので、変換の前に警告する。
    判定: scrollHeight−clientHeight（＝ov）が max(4, 字の大きさ×0.4)px を超える見えている .tb。
      🚫 以前は無警告で、1行ぶんあふれても黙って PPTX に出していた（編集画面の赤い点線の印と対）。
      1行だけ4〜6px高い（行の高さの丸め・ディセンダ）ものは字の大きさ比の下限で見逃す＝型の一覧の誤検出を避ける。
    返り: 『N枚目「先頭…」約Mpxあふれる』の文字列を枚数順にした配列。"""
    rows = []
    for r in (measured or {}).get('els', {}).values():
        if not r.get('runs') or not r.get('vis'):
            continue  # runs を持つのが .tb。見えていない枠は出さない
        ov = r.get('ov', 0) or 0
        fs = r.get('fs') or 16.0
        if ov > max(floor, fs * 0.4):
            first = ''.join((run[0] if run else '') for run in r['runs']).strip()[:12]
            rows.append((r.get('s', 0), f'{r.get("s", 0)}枚目「{first}…」約{round(ov)}pxあふれる'))
    return [m for _, m in sorted(rows, key=lambda t: t[0])]

def standalone_svg(raw, w, h):
    """生SVG文字列を、xmlnsとpx寸法を付けた単体SVGファイル内容にする。"""
    m = re.match(r'<svg\b([^>]*)>', raw, re.IGNORECASE)
    if not m:
        return None
    attrs = m.group(1)
    attrs = re.sub(r'\s(width|height)="[^"]*"', '', attrs)
    if 'xmlns' not in attrs:
        attrs += ' xmlns="http://www.w3.org/2000/svg"'
    attrs += ' width="%d" height="%d"' % (w, h)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<svg' + attrs + '>' + raw[m.end():]


def rasterize_svg(svg_el, w_px, h_px):
    """インラインSVGを w_px×h_px（×SVG_SCALE）の透過PNGに。失敗時 None。"""
    if not CHROME:
        return None
    W, H = int(w_px * SVG_SCALE), int(h_px * SVG_SCALE)
    svg_el['width'] = str(W)
    svg_el['height'] = str(H)
    html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>html,body{margin:0;padding:0;background:transparent}svg{display:block}</style>'
            '</head><body>' + str(svg_el) + '</body></html>')
    tmpd = tempfile.mkdtemp(prefix='slidekit_svg_')
    hp, pp = os.path.join(tmpd, 's.html'), os.path.join(tmpd, 's.png')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    try:
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                        '--default-background-color=00000000', '--force-device-scale-factor=1',
                        '--window-size=%d,%d' % (W, H), '--screenshot=' + pp, 'file://' + hp],
                       timeout=60, capture_output=True)
    except Exception:
        pass
    if not os.path.exists(pp):  # 旧Chrome向けフォールバック（--headless）
        try:
            subprocess.run([CHROME, '--headless', '--disable-gpu', '--hide-scrollbars',
                            '--default-background-color=00000000', '--force-device-scale-factor=1',
                            '--window-size=%d,%d' % (W, H), '--screenshot=' + pp, 'file://' + hp],
                           timeout=60, capture_output=True)
        except Exception:
            pass
    return pp if os.path.exists(pp) else None

def _find_matching_raw_svg(wrapper):
    """処理中の wrapper に対応する生SVG文字列を html.parser soup から取得する。
    lxml側の wrapper と data-x/y/w/h と親要素の位置で照合。"""
    if RAW_SVG_SOUP is None:
        return None
    try:
        dx = wrapper.get('data-x'); dy = wrapper.get('data-y')
        dw = wrapper.get('data-w'); dh = wrapper.get('data-h')
        # data-x/y/w/h の完全一致で raw 側 wrapper を特定
        for cand in RAW_SVG_SOUP.find_all(['div'], attrs={'data-x': dx, 'data-y': dy, 'data-w': dw, 'data-h': dh}):
            svg = cand.find('svg')
            if svg is not None:
                return str(svg)
    except Exception:
        pass
    return None


def _sanitize_svg_text(svg):
    """取り込むSVGから実行・外部参照につながるものを外す（script・foreignObject・on属性・外のURL）。
    画像の埋め込み（data:image/png 等）と、同じファイルの中の参照（#id）は残す"""
    svg = re.sub(r'<\?xml[^>]*\?>|<!DOCTYPE[^>]*>|<!--[\s\S]*?-->', '', svg)
    svg = re.sub(r'<(script|foreignObject|iframe|object|embed)\b[\s\S]*?</\1\s*>|<(script|foreignObject|iframe|object|embed)\b[^>]*/>', '', svg, flags=re.I)
    svg = re.sub(r'\son[a-zA-Z]+\s*=\s*("[^"]*"|\'[^\']*\')', '', svg)
    def _href(m):
        v = m.group(2)[1:-1].strip()
        return m.group(0) if v.startswith('#') or re.match(r'data:image/(png|jpe?g|gif|webp);', v, re.I) else ''
    svg = re.sub(r'\s((?:xlink:)?href)\s*=\s*("[^"]*"|\'[^\']*\')', _href, svg)
    svg = re.sub(r'url\(\s*["\']?(?!#)[^)]*\)', 'none', svg)  # 外のファイルを読む url(...)
    return svg.strip()


def _inline_svg_images(raw_html):
    """<img> で入ったSVG（SlideKitへ.svgファイルをドロップしたもの・data URL・同じフォルダの.svg）を、
    インラインの <svg> に置き換える。インラインならPowerPointの図形になる（2026-10-14。それまでは黙ってPPTXから消えていた）。
    object-fit を preserveAspectRatio に移す。手動トリミング（data-crop-*）のある画像は対象外（画像のまま）"""
    def _rep(m):
        tag = m.group(0)
        if re.search(r'\sdata-crop-[lrtb]\s*=', tag):
            return tag
        sm = re.search(r'\ssrc\s*=\s*"([^"]*)"', tag) or re.search(r"\ssrc\s*=\s*'([^']*)'", tag)
        if not sm:
            return tag
        src = sm.group(1).replace('&amp;', '&')
        text = None
        dm = re.match(r'data:image/svg\+xml(;base64)?,(.*)$', src, re.S | re.I)
        try:
            if dm:
                text = base64.b64decode(dm.group(2)).decode('utf-8', 'replace') if dm.group(1) else unquote(dm.group(2))
            elif re.search(r'\.svg(\?|#|$)', src, re.I) and not re.match(r'^[a-z]+:', src, re.I):
                p = os.path.normpath(os.path.join(BASE_DIR, unquote(src.split('#', 1)[0].split('?', 1)[0])))
                if os.path.isfile(p) and os.path.getsize(p) < 20 * 1024 * 1024:
                    text = open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            text = None
        if not text or len(text) > 20 * 1024 * 1024 or '<svg' not in text:
            return tag
        svg = _sanitize_svg_text(text)
        om = re.search(r'object-fit\s*:\s*(\w+)', tag)
        par = {'contain': 'xMidYMid meet', 'cover': 'xMidYMid slice'}.get(om.group(1) if om else '', 'none')
        am = re.search(r'\salt\s*=\s*"([^"]*)"', tag)
        head = re.match(r'<svg\b[^>]*>', svg)
        if not head:
            return tag
        h = head.group(0)
        if not re.search(r'\sviewBox\s*=', h, re.I):  # 大きさだけのSVGは viewBox を足す（100%に広げても絵が伸び縮みするように）
            wv = re.search(r'\swidth\s*=\s*"([\d.]+)', h); hv = re.search(r'\sheight\s*=\s*"([\d.]+)', h)
            if wv and hv:
                h = h[:-1] + ' viewBox="0 0 %s %s">' % (wv.group(1), hv.group(1))
        h = re.sub(r'\s(width|height|preserveAspectRatio|style|class)\s*=\s*("[^"]*"|\'[^\']*\')', '', h)
        extra = ' width="100%" height="100%" preserveAspectRatio="' + par + '" style="display:block"'
        if am and am.group(1) and 'aria-label' not in h:
            extra += ' role="img" aria-label="' + am.group(1).replace('"', '&quot;') + '"'
        inline = h[:-1] + extra + '>' + svg[head.end():]
        # img 自身が座標を持つ（スライド直下の img）ときは、同じ座標の div で包む（SVGは div で包まないとPPTXに出ない）
        if re.search(r'\sdata-x\s*=', tag):
            keep = ''.join(' ' + a.group(0).strip() for a in re.finditer(r'\s(data-(?:x|y|w|h|rotate|flip|link)|style)\s*=\s*("[^"]*"|\'[^\']*\')', tag))
            return '<div' + keep + '>' + inline + '</div>'
        return inline
    return re.sub(r'<img\b[^>]*>', _rep, raw_html, flags=re.I)


def add_svg(slide, wrapper):
    """SVGを含むラッパーdiv（data-x/y/w/h）をPNG化してラッパーと同座標・同サイズで配置。
    あわせて単体.svgファイルを書き出す（PowerPointへ手動でベクター貼り付け用）。"""
    x = int(float(wrapper.get('data-x', 0))); y = int(float(wrapper.get('data-y', 0)))
    w = int(float(wrapper.get('data-w', 400))); h = int(float(wrapper.get('data-h', 200)))
    svg = wrapper.find('svg')
    # SVGの中の文字は画像に焼き込まない（PPTXで編集できなくなる）。ブラウザで測った位置に文字枠として置き、
    # 画像は文字を抜いたSVGから作る（2026-10-14 利用者「PPTXで編集できない文字を使わない」）
    texts = None
    has_text = svg is not None and svg.find('text') is not None
    _r = MEASURED['els'].get(wrapper.get('data-mid') or '') if MEASURED else None
    # 図形にできるSVGは、PowerPointの図形のグループにする（色を変える・消す・動かすができる・2026-10-14）。
    # ぼかし・マスク等があるSVGと data-svg="image" 指定は従来どおり画像
    vec = (_r or {}).get('svgShapes')
    if vec is not None and wrapper.get('data-svg') != 'image':
        import pptx_vector as _PV
        _tboxes = []
        for _it in (_r or {}).get('svgText') or []:
            _add_svg_text(slide, _it)
            _tboxes.append(slide.shapes[-1]._element)
        _alt = _SEM.alt_of_svg(wrapper) or ' '.join(t['t'] for t in ((_r or {}).get('svgText') or []))[:200]
        # 図形にできない要素（図形そのもののぼかし・形の複雑な切り抜きなど）は、その要素だけを画像にして同じ順番で入れる（2026-10-14）
        def _raster_piece(svg_text, pw, ph):
            _el = BeautifulSoup(svg_text, 'html.parser').find('svg')
            return rasterize_svg(_el, pw, ph) if _el is not None else None
        _g = _PV.add_vector_group(slide, vec, name='Illust S%d' % CUR_SLIDE, alt=_alt, extra_elements=_tboxes, rasterize=_raster_piece)
        if _g is None:  # 一部を画像にできず、絵全体を画像に戻す＝先に置いた文字枠は外す（下の従来の流れで置き直す）
            for _tb in _tboxes:
                if _tb.getparent() is not None:
                    _tb.getparent().remove(_tb)
        if _g is not None and (_r or {}).get('svgPartial'):
            print(f'  INFO: S{CUR_SLIDE} SVGの一部だけを画像にした（図形にできない: {_r["svgPartial"]}）: x={x} y={y}')
        if _g is not None:
            if not _alt:
                ALT_MISSING.append((CUR_SLIDE, 'SVG図', 'x%d,y%d' % (x, y)))
            _export_raw_svg(wrapper, x, y, w, h)
            return True
    if (_r or {}).get('svgWhy'):
        print(f'  INFO: S{CUR_SLIDE} SVGを画像にした（図形にできない: {_r["svgWhy"]}）: x={x} y={y}')
    if has_text:
        texts = (_r or {}).get('svgText')
        if texts:
            svg = copy.copy(svg)
            for _t in svg.find_all('text'):
                _t.decompose()
        else:
            MISSING_ASSETS.append((CUR_SLIDE, 'svg-text', x, y, w, h,
                                   'SVG内の文字を測れず、画像に焼き込んだ（PPTXで編集できない）。Chromeを確認する'))
            print(f'  🚨 S{CUR_SLIDE} SVG内の文字を文字枠にできなかった（画像に焼き込み）: x={x} y={y}')
    png = rasterize_svg(svg, w, h) if svg is not None else None
    placed = False
    if png:
        _pic = slide.shapes.add_picture(png, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h))
        if not _SEM.set_alt_text(_pic, _SEM.alt_of_svg(wrapper) or ' '.join(t['t'] for t in (texts or []))[:200]):
            ALT_MISSING.append((CUR_SLIDE, 'SVG図', 'x%d,y%d' % (x, y)))
            # python-pptx は一時ファイル名（tmpXXXX.png）を代替テキストに入れる。意味が無いので空にする
            _c = _pic._element.find('.//' + qn('p:cNvPr'))
            if _c is not None:
                _c.set('descr', '')
        for _it in texts or []:
            _add_svg_text(slide, _it)
        try:
            os.remove(png); os.rmdir(os.path.dirname(png))
        except Exception:
            pass
        placed = True
    else:
        # PNG 化失敗 (Chrome 見つからず) を欠落として記録
        try:
            reason = 'Chrome not found (set CHROME_PATH env var)' if not CHROME else 'SVG rasterization failed'
            MISSING_ASSETS.append((CUR_SLIDE, 'svg', x, y, w, h, reason))
            print(f'  🚨 MISSING: S{CUR_SLIDE} SVG at ({x},{y}) {w}x{h} — {reason}')
        except Exception:
            pass
    _export_raw_svg(wrapper, x, y, w, h)
    return placed


def _export_raw_svg(wrapper, x, y, w, h):
    """単体SVGファイルを書き出し（このwrapper自身から html.parser 経由で取り出す→対応保証）"""
    raw = _find_matching_raw_svg(wrapper)
    if raw and SVG_OUT_DIR:
        content = standalone_svg(raw, w, h)
        if content:
            os.makedirs(SVG_OUT_DIR, exist_ok=True)
            name = 'S%d_x%d_y%d_%dx%d.svg' % (CUR_SLIDE, x, y, w, h)
            with open(os.path.join(SVG_OUT_DIR, name), 'w', encoding='utf-8') as f:
                f.write(content)
            EXPORTED_SVG.append((CUR_SLIDE, x, y, w, h, name))


ASK_LEFT = []  # 画像が入っていない依頼の枠 (slide, 種類)


def add_ask_zone(slide, el):
    """依頼の枠を、破線の枠＋中の文（編集できる文字）にする"""
    from pptx.enum.dml import MSO_LINE
    x, y = float(el.get('data-x', 0)), float(el.get('data-y', 0))
    w, h = float(el.get('data-w', 320)), float(el.get('data-h', 200))
    sh = slide.shapes.add_shape(1, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = hex_to_rgb('#f4f4ef')  # カタログの薄黄カード（ブラウザは橙6%の透け）
    sh.line.color.rgb = hex_to_rgb('#e8821a')
    sh.line.width = Emu(int(2 * 9525))
    sh.line.dash_style = MSO_LINE.DASH
    remove_shadow(sh)
    sh.name = 'Ask ' + (el.get('data-ask') or '')
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(9)
    tf.margin_top = tf.margin_bottom = Pt(9)
    tf.vertical_anchor = MSO_ANCHOR.TOP  # ブラウザと同じく上から
    fs = float(el.get('data-font-size', 15))
    for i, (runs, _al, _lvl) in enumerate(rich_lines(el, fs, False, '7a471a')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        for (t, rfs, rb, rc) in runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(px_to_pt(rfs))
            r.font.bold = rb
            set_font_name(r.font, FONT_NAME)
            r.font.color.rgb = hex_to_rgb(rc if _is_valid_hex(rc) else '#7a471a')


def _add_svg_text(slide, it):
    """SVGの文字1つを、ブラウザで見えている位置・大きさ・色・太さの文字枠にする（折り返さない）"""
    fs = max(1.0, float(it.get('fs') or 15))
    ang = float(it.get('ang') or 0)
    if abs(ang) > 0.5:
        # 回転した文字: 外接枠の中心に、文字の長さ×1行分の枠を置いて回す
        cw, ch = max(it.get('len') or it['w'], 1) + 4, fs * 1.3
        cx, cy = it['x'] + it['w'] / 2, it['y'] + it['h'] / 2
        bx, by, bw, bh = cx - cw / 2, cy - ch / 2, cw, ch
    else:
        bx, by, bw, bh = it['x'] - 2, it['y'], it['w'] + 4, max(it['h'], fs * 1.2)
        # 2026-11-19: ブラウザで測った幅は PPTX のフォント（Meiryo UI）より狭いことがある。
        #   「4月」の枠が字より狭く、LibreOffice 等で「4／月」の2行に割れていた。字の数から見積もった幅まで広げる
        _t = it.get('t') or ''
        _est = sum(fs if ord(ch) > 0x2E80 else fs * 0.62 for ch in _t) * 1.1 + fs * 0.4
        if _est > bw:
            _pad = _est - bw
            _anc = it.get('anchor')
            bx -= _pad / 2 if _anc == 'middle' else (_pad if _anc == 'end' else 0)
            bw = _est
    tb = slide.shapes.add_textbox(px_to_emu_x(bx), px_to_emu_y(by), px_to_emu_x(bw), px_to_emu_y(bh))
    if abs(ang) > 0.5:
        tb.rotation = ang % 360
    tf = tb.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = {'middle': PP_ALIGN.CENTER, 'end': PP_ALIGN.RIGHT}.get(it.get('anchor'), PP_ALIGN.LEFT)
    r = p.add_run()
    r.text = it['t']
    r.font.size = Pt(px_to_pt(fs))
    r.font.bold = bool(it.get('b'))
    set_font_name(r.font, FONT_NAME)
    if _is_valid_hex(it.get('c')):
        r.font.color.rgb = hex_to_rgb(it['c'])


def add_native_chart(slide, el):
    """<div data-chart='{...}'> を PowerPoint のネイティブグラフにする（2026-10-14）。
    数値は埋め込みのブックに入るので、PowerPoint の「データを編集」で直せる。
    ブラウザ側の見た目は slidekit-chart.js が同じ JSON から描く（色・凡例・数値ラベルを合わせてある）"""
    import json
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    try:
        c = json.loads(el.get('data-chart') or '')
        if isinstance(c.get('links'), list) and isinstance(c.get('nodes'), list):
            c = sankey_as_table(c)   # サンキーを「表」にしたもの（ブラウザの sankeyAsTable と同じ）
        elif c.get('map') or isinstance(c.get('points'), list):
            c = map_as_table(c)      # 地図を「表」にしたもの（ブラウザの mapAsTable と同じ）
        cats = [str(x) for x in c.get('categories') or []]
        series = [s for s in (c.get('series') or []) if isinstance(s, dict)]
        if not cats or not series:
            raise ValueError('categories と series が要る')
    except Exception as e:
        print(f'  🚨 S{CUR_SLIDE} data-chart を読めない（グラフを出していない）: {e}')
        MISSING_ASSETS.append((CUR_SLIDE, 'chart', el.get('data-x'), el.get('data-y'),
                               el.get('data-w'), el.get('data-h'), f'data-chart のJSON: {e}'))
        return
    x, y = int(float(el.get('data-x', 0))), int(float(el.get('data-y', 0)))
    w, h = int(float(el.get('data-w', 600))), int(float(el.get('data-h', 360)))
    fs = float(el.get('data-font-size', 15))
    kind = c.get('type', 'column')
    if kind == 'table':
        # 表（2026-10-14）: グラフの代わりに PowerPoint の表にする。数値も文字も表のセルで直せる
        add_table(slide, chart_table_html(c, x, y, w, fs))
        return
    xl = {'column': XL_CHART_TYPE.COLUMN_CLUSTERED, 'bar': XL_CHART_TYPE.BAR_CLUSTERED,
          'stacked': XL_CHART_TYPE.COLUMN_STACKED, 'line': XL_CHART_TYPE.LINE_MARKERS,
          'pie': XL_CHART_TYPE.PIE}.get(kind)
    if xl is None:
        print(f'  WARN: S{CUR_SLIDE} グラフの種類 "{kind}" は未対応 → 縦棒で出す（column/bar/stacked/line/pie/table）')
        kind, xl = 'column', XL_CHART_TYPE.COLUMN_CLUSTERED
    if kind == 'pie':
        series = series[:1]
    # timeAxis（実際の日付の間隔）・weekendBand（土日）・bands（期間・その日の帯）・area（線の下の塗り）・smooth（2026-10-14）
    #   timeAxis は PowerPoint の日付の軸。土日と帯は「上限まで届く棒」を線の後ろに置く（_background_series_to_bar）
    #   日付の軸で土日か帯があるときは、間の日付も項目に入れる（値は空・線はつなぐ）＝データの無い日も塗れる
    #   塗りは同じ値の面グラフを線の後ろに置く（_area_series_to_area）
    import datetime as _dt
    days = _chart_days(cats) if kind == 'line' else None
    use_time = bool(days) and c.get('timeAxis') is True
    use_we = bool(days) and c.get('weekendBand') is True
    bands = [b for b in (c.get('bands') or []) if isinstance(b, dict)]
    if bands and kind != 'line':
        print(f'  WARN: S{CUR_SLIDE} 帯（bands）は折れ線だけPPTXに出す（{kind} ではブラウザだけ）')
        bands = []
    cc, filled = c, False
    if use_time and (use_we or bands):
        pos = {d: i for i, d in enumerate(days)}
        allds = list(range(min(days), max(days) + 1))
        cc = dict(c, categories=[_dt.date.fromordinal(d).isoformat() for d in allds],
                  series=[dict(s, values=[(s.get('values') or [])[pos[d]] if d in pos and pos[d] < len(s.get('values') or []) else None
                                          for d in allds]) for s in series])
        series, cats, days, filled = cc['series'], cc['categories'], allds, True
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    cd = CategoryChartData()
    cd.categories = [_dt.date.fromordinal(d) for d in days] if use_time else cats
    for s in series:
        vals = list(s.get('values') or [])[:len(cats)]
        cd.add_series(str(s.get('name') or ''), [num(v) for v in vals])
    # 目標線（target）: 同じ値が並ぶ系列としてブックに入れる＝PowerPointの「データを編集」で目標値も直せる。
    #   棒グラフでは、この系列を折れ線に移す（棒と線の組み合わせ・_target_series_to_line）。横棒・円は出さない
    tg = c.get('target') if isinstance(c.get('target'), dict) else None
    tval = tg.get('value') if tg else None
    has_target = isinstance(tval, (int, float)) and not isinstance(tval, bool) and kind in ('column', 'stacked', 'line')
    if tg and not has_target:
        print(f'  WARN: S{CUR_SLIDE} 目標線は{"横棒" if kind == "bar" else "この種類"}ではPPTXに出していない（縦棒・積み上げ・折れ線で出る）')
    if has_target:
        tname = f'{tg.get("label") or "目標"} {_chart_num(tval)}{c.get("unit") or ""}'
        cd.add_series(tname, [float(tval)] * len(cats))
    # 塗り（area）: 破線でなく area:false でない系列ごとに、同じ値の面
    cols = [h for h in (c.get('colors') or CHART_PAL) if _is_valid_hex(h)] or CHART_PAL
    areas = []
    if kind == 'line' and c.get('area') is True:
        for j, s in enumerate(series):
            if s.get('area') is not False and not s.get('dash'):
                cd.add_series(f'{s.get("name") or ""}（塗り）', [num(v) for v in list(s.get('values') or [])[:len(cats)]])
                areas.append(cols[j % len(cols)])
    # 後ろの帯: 期間・その日の帯（bands）→ 土日。上限まで届く棒
    lo_, hi_, _st = _chart_ticks(cc, kind)
    bg = []
    for b in bands:
        r = _chart_band_range(b, cats)
        if not r:
            continue
        cd.add_series(str(b.get('label') or '期間'), [float(hi_) if r[0] <= i <= r[1] else None for i in range(len(cats))])
        bg.append((_band_color(b), _band_opacity(b), r[0] if b.get('label') else None))
    if use_we:
        cd.add_series('土日', [float(hi_) if _dt.date.fromordinal(d).weekday() >= 5 else None for d in days])
        bg.append(('#eef3f8', 1.0, None))
    gf = slide.shapes.add_chart(xl, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h), cd)
    _SEM.set_alt_text(gf, c.get('title') or ' / '.join(str(s.get('name') or '') for s in series))
    if has_target and kind != 'line':
        _target_series_to_line(gf.chart)
    _style_native_chart(gf.chart, cc, kind, fs, w, h)
    if bg:
        _background_series_to_bar(gf.chart, bg, fs)
    if areas:
        _area_series_to_area(gf.chart, areas)
    if has_target:
        _style_target_series(gf.chart, len(cats), fs)
    if use_time:
        ca = gf.chart.category_axis
        ca.tick_labels.number_format, ca.tick_labels.number_format_is_linked = 'm/d', False
    if filled:
        # 間に入れた日付（値は空）で線を切らない
        db = gf.chart._chartSpace.find('.//' + qn('c:dispBlanksAs'))
        if db is not None:
            db.set('val', 'span')


BAND_COL = {'danger': '#c62828', 'accent': '#c62828', 'warn': '#7a471a', 'ok': '#21537f', 'sub': '#9fc0dd'}


def _band_color(b):
    """帯の色（slidekit-chart.js の bandColor と同じ）。意味の名前か #hex"""
    v = b.get('color')
    return BAND_COL.get(v) or (v if isinstance(v, str) and re.match(r'^#[0-9a-fA-F]{6}$', v) else BAND_COL['sub'])


def _band_opacity(b):
    v = b.get('opacity')
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 1 else 0.12


def _chart_band_range(b, cats):
    """帯が掛かる項目の番号 [始め, 終わり]（slidekit-chart.js の bandRange と同じ）。日付の項目なら日付で比べる"""
    iso = bool(cats) and all(re.match(r'^\d{4}-\d{2}-\d{2}$', str(x)) for x in cats)
    f = str(b.get('from') if b.get('from') is not None else '')
    t = str(b.get('to') if b.get('to') is not None else f)
    i0 = i1 = -1
    for i, s in enumerate(map(str, cats)):
        if iso:
            if f <= s <= t:
                i0 = i if i0 < 0 else i0
                i1 = i
        else:
            if s == f:
                i0 = i
            if s == t:
                i1 = i
    return [i0, i1] if i0 >= 0 and i1 >= i0 else None


def sankey_as_table(c):
    """サンキーの流れを表にする: 1行＝1本の帯（出どころ → 行き先・量）。slidekit-chart.js の sankeyAsTable と同じ"""
    import math
    nodes = {str(n['id']): str(n.get('label') if n.get('label') is not None else n['id'])
             for n in c.get('nodes') or [] if isinstance(n, dict) and n.get('id') is not None}
    rows = [(nodes[str(l['from'])] + ' → ' + nodes[str(l['to'])], l['value'])
            for l in c.get('links') or [] if isinstance(l, dict) and str(l.get('from')) in nodes and str(l.get('to')) in nodes
            and isinstance(l.get('value'), (int, float)) and not isinstance(l.get('value'), bool)
            and math.isfinite(l['value']) and l['value'] > 0 and str(l['from']) != str(l['to'])]
    return {'type': 'table', 'unit': c.get('unit'), 'categoryLabel': '流れ', 'title': c.get('title'),
            'categories': [r[0] for r in rows], 'series': [{'name': '量', 'values': [r[1] for r in rows]}]}


def _is_sankey(el):
    """data-chart が、ブラウザで描いた図を図形にする種類（サンキー・地図）か。表にしたものは含まない"""
    try:
        return json.loads(el.get('data-chart') or '{}').get('type') in ('sankey', 'map')
    except Exception:
        return False


def map_as_table(c):
    """地図を表にする: 1行＝1つの地域（書いてある順）・列＝系列。slidekit-chart.js の mapAsTable と同じ"""
    import math
    ser = c.get('series')
    if not (isinstance(ser, list) and ser and isinstance(ser[0], dict) and not isinstance(ser[0].get('values'), list)):
        ser = [{'name': c.get('title') or '', 'values': c.get('values') or {}}]
    keys = list((ser[0].get('values') or {}).keys())
    ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    pts = [p for p in (c.get('points') or []) if isinstance(p, dict) and ok(p.get('lat')) and ok(p.get('lon'))]
    if pts and not keys:
        # 拠点だけの地図: 1行＝1つの拠点・列＝値（あれば）・緯度・経度
        col = lambda name, k: {'name': name, 'values': [p.get(k) if ok(p.get(k)) else None for p in pts]}
        cols = [col('値' + ('（%s）' % c['pointUnit'] if c.get('pointUnit') else ''), 'value')] if any(ok(p.get('value')) for p in pts) else []
        return {'type': 'table', 'categoryLabel': c.get('pointLabel') or '拠点', 'title': c.get('title'),
                'categories': ['' if p.get('name') is None else str(p.get('name')) for p in pts],
                'series': cols + [col('緯度', 'lat'), col('経度', 'lon')]}
    return {'type': 'table', 'unit': c.get('unit'), 'categoryLabel': '地域', 'title': c.get('title'), 'categories': keys,
            'series': [{'name': s.get('name') or '値', 'values': [(s.get('values') or {}).get(k) if ok((s.get('values') or {}).get(k)) else None
                                                                 for k in keys]} for s in ser]}


def _chart_tw(s, fs):
    """文字幅の見積もり（slidekit-chart.js の tw と同じ: 全角=1em・半角=0.6em）"""
    return sum(1 if ord(ch) > 255 else 0.6 for ch in str(s)) * fs


def _chart_label_below(c, ser):
    """折れ線が2本以上のとき、数値を線の下に置く系列（平均がいちばん低い系列）。無ければ -1（slidekit-chart.js の labelBelow と同じ）"""
    import math
    if c.get('type') != 'line' or len(ser) < 2:
        return -1
    best, bm = -1, math.inf
    for j, s in enumerate(ser):
        v = [x for x in (s.get('values') or []) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)]
        m = sum(v) / len(v) if v else math.inf
        if m < bm:
            best, bm = j, m
    return best


def _chart_label_box(c, ser, j, i, g):
    """数値の枠 [左, 右, 下, 上]（slidekit-chart.js の labelBox と同じ）"""
    lf = g['fs'] * 0.85
    unit = c.get('unit') or ''
    v = ser[j]['values'][i]
    w = _chart_tw(_chart_num(v) + unit, lf) + lf * 0.3
    k = max(1, len(ser))
    gw = g['band'] * 0.7
    bw = gw / k
    vp = (v - g['lo']) / ((g['hi'] - g['lo']) or 1) * g['ph']
    if g['mode'] == 'line':
        y = vp + (-lf * 1.1 if j == _chart_label_below(c, ser) else lf * 1.1)
        x = g['xs'][i] if g.get('xs') else g['band'] * (i + 0.5)
        return [x - w / 2, x + w / 2, y - lf * 0.6, y + lf * 0.6]
    x2 = g['band'] * i + (g['band'] - gw) / 2 + bw * j + bw * 0.46
    if g['mode'] == 'hbar':
        return [vp + 6, vp + 6 + w, x2 - lf * 0.62, x2 + lf * 0.62]
    return [x2 - w / 2, x2 + w / 2, vp + lf * 0.1, vp + lf * 1.3]


def _chart_geo(c, kind, w, h, fs):
    """軸のあるグラフの広さ（slidekit-chart.js の axisGeo と同じ式）"""
    lo, hi, step = _chart_ticks(c, kind)
    unit = c.get('unit') or ''
    cats = c.get('categories') or []
    ser = [s for s in (c.get('series') or []) if isinstance(s, dict)]
    ticks, k = [], 0
    while lo + step * k <= hi + step / 2:
        ticks.append(round(lo + step * k, 10))
        k += 1
    vw = max([_chart_tw(_chart_num(t) + unit, fs * 0.85) for t in ticks] + [0])
    iso = bool(cats) and all(re.match(r'^\d{4}-\d{2}-\d{2}$', str(x)) for x in cats)
    cw = max([_chart_tw(f'{int(x[5:7])}/{int(x[8:10])}' if iso else x, fs) for x in cats] + [0])
    horiz, line = kind == 'bar', kind == 'line'
    top = fs * 2.2 if (c.get('legend', True) is not False and len(ser) > 1) else fs * 1.6
    L = cw + 10 if horiz else vw + 10
    R = vw / 2 + 4 if horiz else fs * 0.8
    pw, ph = w - L - R, h - top - (fs * 1.8 if horiz else fs * 1.9)
    band = (ph if horiz else pw) / max(1, len(cats))
    # timeAxis: 1日を1枠とし、点は枠の中央（slidekit-chart.js と PowerPoint の日付の軸と同じ置き方）
    xs = None
    days = _chart_days(cats)
    if line and c.get('timeAxis') is True and days:
        d0, span = min(days), max(days) - min(days)
        xs = [pw * (d - d0 + 0.5) / (span + 1) for d in days]
    return {'mode': 'line' if line else 'hbar' if horiz else 'cluster', 'band': band, 'fs': fs,
            'lo': lo, 'hi': hi, 'ph': pw if horiz else ph, 'xs': xs}


def _chart_days(cats):
    """項目がすべて 'YYYY-MM-DD' なら日の番号（連続した整数）の列、そうでなければ None"""
    import datetime
    if not cats or not all(re.match(r'^\d{4}-\d{2}-\d{2}$', str(x)) for x in cats):
        return None
    try:
        return [datetime.date(int(x[:4]), int(x[5:7]), int(x[8:10])).toordinal() for x in cats]
    except ValueError:
        return None


def chart_label_plan(c, kind, w, h, fs):
    """数値ラベルをどの点に出すか [[bool]*項目]*系列（slidekit-chart.js の labelPlan と同じ手順・2026-10-14）。
    利用者「点の数ではなく、数値を間引く仕組みを」。点の数で全部出す／全部消すを決めていた（24点）のをやめた。
    数値1つずつの置き場所（枠）を見積もり、すでに置いた数値と重ならないものだけ出す。
    置く順: ①系列ごとの最大・最小・最後 ②左から順に。重ならなければ全部出る。
    labels:false＝出さない／labels:"all"＝全部出す"""
    import math
    cats = c.get('categories') or []
    ser = [s for s in (c.get('series') or []) if isinstance(s, dict)]
    n = len(cats)
    ser = [dict(s, values=[(s.get('values') or [])[i] if i < len(s.get('values') or []) else None for i in range(n)]) for s in ser]
    def has(s, i):
        v = s['values'][i]
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    show = [[False] * n for _ in ser]
    if c.get('labels') is False or kind == 'stacked':   # 積み上げは数値を出さない（ブラウザと同じ）
        return show
    if c.get('labels') == 'all':
        return [[has(s, i) for i in range(n)] for s in ser]
    g = _chart_geo(c, kind, w, h, fs)
    order, seen = [], set()
    def push(j, i):
        if i >= 0 and (j, i) not in seen:
            seen.add((j, i))
            order.append((j, i))
    for j, s in enumerate(ser):
        idx = [i for i in range(n) if has(s, i)]
        if not idx:
            continue
        mx = mn = idx[0]
        for i in idx:   # 同じ値なら最初の点（JS の > / < と同じ）
            if s['values'][i] > s['values'][mx]:
                mx = i
            if s['values'][i] < s['values'][mn]:
                mn = i
        push(j, mx); push(j, mn); push(j, idx[-1])
    for i in range(n):
        for j, s in enumerate(ser):
            if has(s, i):
                push(j, i)
    placed = []
    for j, i in order:
        b = _chart_label_box(c, ser, j, i, g)
        if any(b[0] < p[1] and p[0] < b[1] and b[2] < p[3] and p[2] < b[3] for p in placed):
            continue
        placed.append(b)
        show[j][i] = True
    return show


def _chart_num(v):
    """slidekit-chart.js の fmt と同じ: 小数2桁で丸め、3桁区切り、末尾の0は出さない"""
    r = round(float(v) * 100) / 100
    s = f'{r:,.2f}'.rstrip('0').rstrip('.')
    return s if s != '-0' else '0'


def chart_table_html(c, x, y, w, fs):
    """data-chart（type:table）を、add_table が読める <table> にする（ブラウザの tableChart と同じ見た目）。
    行＝項目・列＝系列。見出しは card 地＋title 色の下線、行の区切りは line 色。文字は 8pt 以上"""
    from html import escape as _e
    fs = max(10.67, float(fs))
    cats = [str(v) for v in c.get('categories') or []]
    ser = [s for s in (c.get('series') or []) if isinstance(s, dict)]
    unit = c.get('unit') or ''
    pad = f'padding:{round(fs * 0.4)}px {round(fs * 0.7)}px'
    th = f'background:#eef3f8;color:#121212;font-weight:700;{pad};border-bottom:2px solid #21537f'
    td = f'color:#121212;{pad};border-bottom:1px solid #d4dde7'
    head = [c.get('categoryLabel') or '項目'] + [str(s.get('name') or '') + (f'（{unit}）' if unit else '') for s in ser]
    rows = ['<tr>' + ''.join(f'<th style="{th};text-align:{"left" if j == 0 else "right"}">{_e(h)}</th>'
                             for j, h in enumerate(head)) + '</tr>']
    for i, cat in enumerate(cats):
        cells = [f'<td style="{td};text-align:left">{_e(cat)}</td>']
        for s in ser:
            vals = s.get('values') or []
            v = vals[i] if i < len(vals) else None
            cells.append(f'<td style="{td};text-align:right">{"" if v in (None, "") else _e(_chart_num(v))}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    html = (f'<table data-x="{x}" data-y="{y}" data-w="{w}" style="position:absolute;left:{x}px;top:{y}px;'
            f'width:{w}px;border-collapse:collapse;font-size:{fs:g}px">' + ''.join(rows) + '</table>')
    return BeautifulSoup(html, 'html.parser').find('table')


# 系列の既定色＝slidekit-chart.js の PAL と同じ（スライド契約のトークン）
CHART_PAL = ['#21537f', '#9fc0dd', '#718096', '#162a42', '#d4dde7', '#c62828']


def _style_native_chart(chart, c, kind, fs, w=600, h=360):
    """色・文字・凡例・数値ラベル・目盛り線をブラウザ表示（slidekit-chart.js）に合わせる"""
    from pptx.enum.chart import XL_LEGEND_POSITION, XL_LABEL_POSITION
    from pptx.enum.chart import XL_MARKER_STYLE
    from lxml import etree
    cols = [h for h in (c.get('colors') or CHART_PAL) if _is_valid_hex(h)] or CHART_PAL
    unit = str(c.get('unit') or '').replace('"', '')
    # General＝整数は「120」、小数は「10.5」（'#,##0.##' だと PowerPoint で「120.」になる）
    numfmt = 'General' + ('"%s"' % unit if unit else '')
    chart.font.size = Pt(px_to_pt(fs))
    set_font_name(chart.font, FONT_NAME)
    chart.font.color.rgb = hex_to_rgb('#121212')
    chart.has_title = False
    plot = chart.plots[0]
    real = [s for s in (c.get('series') or []) if isinstance(s, dict)]
    n_ser = len(real)   # 目標線の系列は数えない（凡例を出すかの判断）
    chart.has_legend = (kind == 'pie') or (c.get('legend', True) is not False and n_ser > 1)
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.RIGHT if kind == 'pie' else XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(px_to_pt(fs))
    if kind == 'pie':
        for i, pt in enumerate(plot.series[0].points):
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = hex_to_rgb(cols[i % len(cols)])
            pt.format.line.color.rgb = hex_to_rgb('#fafafa')
        if c.get('labels', True) is not False:
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.show_percentage, dl.show_value, dl.show_category_name = True, False, False
            dl.font.size = Pt(px_to_pt(fs * 0.85))
        return
    if kind != 'line':
        plot.gap_width = 43   # 帯の70%を棒にする＝ブラウザと同じ
        plot.overlap = 100 if kind == 'stacked' else -8
    for j, s in enumerate(plot.series):
        if j >= n_ser:
            continue   # 目標線（_style_target_series で整える）
        col = hex_to_rgb(cols[j % len(cols)])
        if kind == 'line':
            s.format.line.color.rgb = col
            s.format.line.width = Pt(2.25)
            s.smooth = c.get('smooth') is True   # なめらかな線（PowerPoint の平滑線。ブラウザの単調3次補間とは少し違う）
            s.marker.style = XL_MARKER_STYLE.CIRCLE
            s.marker.size = 7
            s.marker.format.fill.solid()
            # dash:true（予測・理論値）は破線＋白抜きの点（ブラウザと同じ・2026-10-14）
            dashed = bool(real[j].get('dash'))
            s.marker.format.fill.fore_color.rgb = hex_to_rgb('#fafafa') if dashed else col
            s.marker.format.line.color.rgb = col
            if dashed:
                s.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        else:
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = col
    # 数値ラベル: ブラウザと同じ点に出す（chart_label_plan）。系列ごとに出し、出さない点は c:dLbl の delete で消す
    if kind != 'stacked' and c.get('labels') is not False:
        plan = chart_label_plan(c, kind, w, h, fs)
        below = _chart_label_below(c, [s for s in (c.get('series') or []) if isinstance(s, dict)])
        for j, s in enumerate(plot.series):
            if j >= len(plan) or not any(plan[j]):   # 目標線の系列は数値を出さない
                continue
            dl = s.data_labels
            dl.show_value = True
            dl.number_format, dl.number_format_is_linked = numfmt, False
            dl.font.size = Pt(px_to_pt(fs * 0.85))
            dl.position = (XL_LABEL_POSITION.OUTSIDE_END if kind != 'line' else
                           XL_LABEL_POSITION.BELOW if j == below else XL_LABEL_POSITION.ABOVE)
            dls = s._element.find(qn('c:dLbls'))
            for i in reversed([i for i, on in enumerate(plan[j]) if not on]):
                d = etree.Element(qn('c:dLbl'))
                etree.SubElement(d, qn('c:idx')).set('val', str(i))
                etree.SubElement(d, qn('c:delete')).set('val', '1')
                dls.insert(0, d)   # CT_DLbls は dLbl が先頭（逆順に先頭へ入れて idx の昇順にする）
    va, ca = chart.value_axis, chart.category_axis
    # 目盛りはブラウザ（slidekit-chart.js の nice()）と同じ刻みにする。PowerPoint の自動だと上限が変わる
    lo, hi, step = _chart_ticks(c, kind)
    va.minimum_scale, va.maximum_scale, va.major_unit = lo, hi, step
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = hex_to_rgb('#d4dde7')
    va.format.line.fill.background()
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = numfmt, False
    va.tick_labels.font.size = Pt(px_to_pt(fs * 0.85))
    va.tick_labels.font.color.rgb = hex_to_rgb('#5e5e5e')
    ca.tick_labels.font.size = Pt(px_to_pt(fs))
    ca.format.line.color.rgb = hex_to_rgb('#5e5e5e')
    if kind == 'bar':
        ca.reverse_order = True   # PowerPointの横棒は下から並ぶ。ブラウザ（上から）に合わせる
        # 反転すると目盛りが上に行くので、値の軸を「最後の項目の側」で交差させて下に戻す。
        # python-pptx の crosses は ValueAxis にしか無く意味も逆なので、valAx の c:crosses を直接書く
        cr = va._element.find(qn('c:crosses'))
        if cr is not None:
            cr.set('val', 'max')


def _target_series_to_line(chart):
    """棒グラフの最後の系列（目標線）を、同じ軸の折れ線に移す（棒と線の組み合わせ）。
    c:barChart の c:ser を c:lineChart へ移し、棒にしかない要素を外して、線の要素を足す"""
    from lxml import etree
    pa = chart._chartSpace.find('.//' + qn('c:plotArea'))
    bar = pa.find(qn('c:barChart'))
    sers = bar.findall(qn('c:ser'))
    ser = sers[-1]
    bar.remove(ser)
    for tag in ('c:invertIfNegative', 'c:pictureOptions', 'c:shape'):
        for e in ser.findall(qn(tag)):
            ser.remove(e)
    mk = etree.Element(qn('c:marker'))
    etree.SubElement(mk, qn('c:symbol')).set('val', 'none')
    tx = ser.find(qn('c:tx'))
    sp = ser.find(qn('c:spPr'))
    (sp if sp is not None else tx).addnext(mk)   # 順: idx, order, tx, spPr, marker, …, cat, val, smooth
    etree.SubElement(ser, qn('c:smooth')).set('val', '0')
    line = etree.Element(qn('c:lineChart'))
    etree.SubElement(line, qn('c:grouping')).set('val', 'standard')
    etree.SubElement(line, qn('c:varyColors')).set('val', '0')
    line.append(ser)
    etree.SubElement(line, qn('c:marker')).set('val', '1')
    for ax in bar.findall(qn('c:axId')):
        etree.SubElement(line, qn('c:axId')).set('val', ax.get('val'))
    bar.addnext(line)


def _hide_legend_entry(chart, ser):
    """凡例からこの系列を外す（c:legendEntry delete）。順: legendPos, legendEntry*, layout…"""
    from lxml import etree
    if not chart.has_legend:
        return
    leg = chart._chartSpace.find('.//' + qn('c:legend'))
    le = etree.Element(qn('c:legendEntry'))
    etree.SubElement(le, qn('c:idx')).set('val', ser.find(qn('c:idx')).get('val'))
    etree.SubElement(le, qn('c:delete')).set('val', '1')
    leg.find(qn('c:legendPos')).addnext(le)


def _fill_xml(hexcol, alpha=1.0, grad=False):
    """c:spPr（塗り・線なし）。grad=True は上から下へ薄くなる塗り（線の下の塗り）"""
    from lxml import etree
    sp = etree.Element(qn('c:spPr'))
    h = hexcol.lstrip('#').upper()
    if grad:
        gf = etree.SubElement(sp, qn('a:gradFill'))
        gl = etree.SubElement(gf, qn('a:gsLst'))
        for pos, a in ((0, 0.14), (100000, 0.01)):
            gs = etree.SubElement(gl, qn('a:gs'))
            gs.set('pos', str(pos))
            clr = etree.SubElement(gs, qn('a:srgbClr'))
            clr.set('val', h)
            etree.SubElement(clr, qn('a:alpha')).set('val', str(int(a * 100000)))
        etree.SubElement(gf, qn('a:lin')).set('ang', '5400000')
    else:
        sf = etree.SubElement(sp, qn('a:solidFill'))
        clr = etree.SubElement(sf, qn('a:srgbClr'))
        clr.set('val', h)
        if alpha < 1:
            etree.SubElement(clr, qn('a:alpha')).set('val', str(int(alpha * 100000)))
    etree.SubElement(etree.SubElement(sp, qn('a:ln')), qn('a:noFill'))
    return sp


def _take_line_series(chart, n):
    """折れ線グループの最後の n 系列を取り出す（線にしかない要素・数値ラベルは外す）"""
    pa = chart._chartSpace.find('.//' + qn('c:plotArea'))
    line = pa.find(qn('c:lineChart'))
    sers = line.findall(qn('c:ser'))[-n:]
    for ser in sers:
        line.remove(ser)
        for tag in ('c:marker', 'c:smooth', 'c:dLbls', 'c:spPr'):
            for e in ser.findall(qn(tag)):
                ser.remove(e)
    return line, sers


def _background_series_to_bar(chart, styles, fs):
    """折れ線の最後の系列たち（帯・土日）を、線の後ろの棒（すき間なし・重ねる）にする。
    styles: [(色, 不透明度, 名前を出す項目の番号 or None)]。凡例には出さない"""
    from lxml import etree
    from pptx.enum.chart import XL_LABEL_POSITION  # noqa: F401
    line, sers = _take_line_series(chart, len(styles))
    bar = etree.Element(qn('c:barChart'))
    etree.SubElement(bar, qn('c:barDir')).set('val', 'col')
    etree.SubElement(bar, qn('c:grouping')).set('val', 'clustered')
    etree.SubElement(bar, qn('c:varyColors')).set('val', '0')
    for ser, (col, alpha, lab_at) in zip(sers, styles):
        sp = _fill_xml(col, alpha)
        ser.find(qn('c:tx')).addnext(sp)   # 順: idx, order, tx, spPr, invertIfNegative, dPt, dLbls, cat, val
        inv = etree.Element(qn('c:invertIfNegative'))
        inv.set('val', '0')
        sp.addnext(inv)
        if lab_at is not None:
            # 帯の名前: 帯の始めの棒の内側の上に（ほかの点は出さない）
            d = etree.Element(qn('c:dLbls'))
            one = etree.SubElement(d, qn('c:dLbl'))
            etree.SubElement(one, qn('c:idx')).set('val', str(lab_at))
            tx = etree.SubElement(one, qn('c:txPr'))
            etree.SubElement(tx, qn('a:bodyPr'))
            etree.SubElement(tx, qn('a:lstStyle'))
            p = etree.SubElement(tx, qn('a:p'))
            rp = etree.SubElement(etree.SubElement(p, qn('a:pPr')), qn('a:defRPr'))
            rp.set('sz', str(int(round(px_to_pt(fs * 0.85) * 100))))
            etree.SubElement(etree.SubElement(rp, qn('a:solidFill')), qn('a:srgbClr')).set('val', '5E5E5E')
            etree.SubElement(one, qn('c:dLblPos')).set('val', 'inEnd')
            for k, v in (('showLegendKey', '0'), ('showVal', '0'), ('showCatName', '0'), ('showSerName', '1'),
                         ('showPercent', '0'), ('showBubbleSize', '0')):
                etree.SubElement(one, qn('c:' + k)).set('val', v)
            for k in ('showLegendKey', 'showVal', 'showCatName', 'showSerName', 'showPercent', 'showBubbleSize'):
                etree.SubElement(d, qn('c:' + k)).set('val', '0')
            inv.addnext(d)
        bar.append(ser)
    etree.SubElement(bar, qn('c:gapWidth')).set('val', '0')
    etree.SubElement(bar, qn('c:overlap')).set('val', '100')
    for ax in line.findall(qn('c:axId')):
        etree.SubElement(bar, qn('c:axId')).set('val', ax.get('val'))
    line.addprevious(bar)   # 先に描く＝線の後ろ
    for ser in sers:
        _hide_legend_entry(chart, ser)


def _area_series_to_area(chart, colors):
    """折れ線の最後の系列たち（線の下の塗り）を、線の後ろの面グラフにする（上から下へ薄くなる塗り）"""
    from lxml import etree
    line, sers = _take_line_series(chart, len(colors))
    area = etree.Element(qn('c:areaChart'))
    etree.SubElement(area, qn('c:grouping')).set('val', 'standard')
    etree.SubElement(area, qn('c:varyColors')).set('val', '0')
    for ser, col in zip(sers, colors):
        ser.find(qn('c:tx')).addnext(_fill_xml(col, grad=True))   # 順: idx, order, tx, spPr, …, cat, val
        area.append(ser)
    for ax in line.findall(qn('c:axId')):
        etree.SubElement(area, qn('c:axId')).set('val', ax.get('val'))
    line.addprevious(area)
    for ser in sers:
        _hide_legend_entry(chart, ser)


def _style_target_series(chart, n, fs):
    """目標線の系列: 赤の破線・点なし・凡例から外す・最後の点に系列名（「目標 100kg」）を出す"""
    from lxml import etree
    from pptx.enum.chart import XL_LABEL_POSITION, XL_MARKER_STYLE
    s = list(chart.series)[-1]
    s.format.line.color.rgb = hex_to_rgb('#c62828')
    s.format.line.width = Pt(1.5)
    s.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    s.smooth = False
    s.marker.style = XL_MARKER_STYLE.NONE
    dl = s.data_labels
    dl.show_value, dl.show_series_name = False, True
    dl.font.size = Pt(px_to_pt(fs * 0.85))
    dl.font.bold = True
    dl.font.color.rgb = hex_to_rgb('#c62828')
    dl.position = XL_LABEL_POSITION.ABOVE
    dls = s._element.find(qn('c:dLbls'))
    for i in reversed(range(n - 1)):   # 最後の点だけ名前を出す
        d = etree.Element(qn('c:dLbl'))
        etree.SubElement(d, qn('c:idx')).set('val', str(i))
        etree.SubElement(d, qn('c:delete')).set('val', '1')
        dls.insert(0, d)
    if chart.has_legend:
        leg = chart._chartSpace.find('.//' + qn('c:legend'))
        idx = s._element.find(qn('c:idx')).get('val')
        le = etree.Element(qn('c:legendEntry'))
        etree.SubElement(le, qn('c:idx')).set('val', idx)
        etree.SubElement(le, qn('c:delete')).set('val', '1')
        leg.find(qn('c:legendPos')).addnext(le)   # 順: legendPos, legendEntry*, layout, overlay…


def _chart_ticks(c, kind):
    """slidekit-chart.js の axisScale と同じ値の軸（下限・上限・刻み）。
    既定は0を含む4刻み前後のきりのいい値／fitY（折れ線・max なし）はデータの範囲に合わせる／
    max は上限の固定（データの最大より小さければ使わない）／target の値も範囲に入れる（2026-10-14）"""
    import math
    def nice(v):
        if v <= 0:
            return 1
        p = 10 ** math.floor(math.log10(v))
        m = v / p
        return (1 if m <= 1 else 2 if m <= 2 else 2.5 if m <= 2.5 else 5 if m <= 5 else 10) * p
    def isnum(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    cats, ser = c.get('categories') or [], [s for s in (c.get('series') or []) if isinstance(s, dict)]
    mx = mn = 0.0
    dlo, dhi = math.inf, -math.inf
    for i in range(len(cats)):
        vals = []
        for s in ser:
            v = (s.get('values') or [])[i] if i < len(s.get('values') or []) else None
            if isnum(v):
                dlo, dhi = min(dlo, v), max(dhi, v)
            else:
                v = 0.0
            vals.append(float(v))
        mx, mn = max([mx] + vals), min([mn] + vals)
        if kind == 'stacked':
            mx = max(mx, sum(vals))
    t = (c.get('target') or {}).get('value') if isinstance(c.get('target'), dict) else None
    if isnum(t):
        mx, mn, dlo, dhi = max(mx, t), min(mn, t), min(dlo, t), max(dhi, t)
    cmax = c.get('max')
    if kind == 'line' and c.get('fitY') is True and not isnum(cmax) and dlo <= dhi:
        span = dhi - dlo
        if span <= 0:
            span = abs(dhi) * 0.1 or 1
        st = nice(span / 4)
        flo, fhi = math.floor(dlo / st) * st, math.ceil(dhi / st) * st
        if abs(dlo - flo) < st * 0.1:
            flo -= st
        if abs(fhi - dhi) < st * 0.1:
            fhi += st
        if dlo >= 0 and flo < 0:
            flo = 0
        return round(flo, 10), round(fhi, 10), st
    step = nice((mx - mn) / 4 or 1)
    lo, hi = math.floor(mn / step) * step, math.ceil(mx / step) * step
    if isnum(cmax) and cmax >= mx:
        hi = cmax
        step = (hi - lo) / 4 or 1
    return lo, hi, step

#    動く図を渡すには動画を埋める。CadKit --export-flow → SlideKit/flow_to_movie.py で
#    mp4とコマPNGを作り、スライドには <video src poster> を置く（2026-08-21）
MOVIE_MIME = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime'}


def add_movie_shape(slide, wrapper):
    """<video>を含むラッパーdiv（data-x/y/w/h）→ 動画を同座標・同サイズで埋め込む。
    再生前に見えるプレビューは video の poster 画像（動画のどのコマでも選べる）。"""
    video = wrapper.find('video')
    if video is None:
        return False
    x = int(wrapper.get('data-x', 0)); y = int(wrapper.get('data-y', 0))
    w = int(wrapper.get('data-w', 400)); h = int(wrapper.get('data-h', 200))
    src = (video.get('src') or '').strip()
    ext = os.path.splitext(src)[1].lower()
    movie_path = os.path.join(BASE_DIR, src) if src else ''
    if not src or not os.path.exists(movie_path):
        MISSING_ASSETS.append((CUR_SLIDE, 'video', x, y, w, h,
                               f'動画が見つからない: {src or "(src無し)"}'))
        print(f'  🚨 MISSING: S{CUR_SLIDE} VIDEO at ({x},{y}) — {src or "(src無し)"}')
        return False
    if ext not in MOVIE_MIME:
        MISSING_ASSETS.append((CUR_SLIDE, 'video', x, y, w, h,
                               f'PPTX非対応の動画形式: {ext}（mp4にする）'))
        print(f'  🚨 MISSING: S{CUR_SLIDE} VIDEO {ext} は非対応 — mp4に変換する')
        return False
    poster = (video.get('poster') or '').strip()
    poster_path = os.path.join(BASE_DIR, poster) if poster else None
    if poster_path and not os.path.exists(poster_path):
        print(f'  WARN: S{CUR_SLIDE} poster が見つからない: {poster}（既定の枠になる）')
        poster_path = None
    if not poster_path:
        print(f'  WARN: S{CUR_SLIDE} poster 未指定。再生前が黒枠になる'
              f'（flow_to_movie.py のコマ一覧から選ぶ）')
    try:
        pic = slide.shapes.add_movie(
            movie_path, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h),
            poster_frame_image=poster_path, mime_type=MOVIE_MIME[ext])
    except Exception as e:
        MISSING_ASSETS.append((CUR_SLIDE, 'video', x, y, w, h, f'埋め込み失敗: {e}'))
        print(f'  🚨 MISSING: S{CUR_SLIDE} VIDEO 埋め込み失敗 — {e}')
        return False
    _movie_autoplay_loop(slide, pic, video.has_attr('autoplay'), video.has_attr('loop'))
    print(f'  動画: S{CUR_SLIDE} {os.path.basename(movie_path)} at ({x},{y}) {w}x{h}'
          f' poster={os.path.basename(poster_path) if poster_path else "なし"}')
    return True


def _movie_autoplay_loop(slide, pic, autoplay, loop):
    """スライド表示と同時の自動再生・ループをtiming XMLで設定する。
    python-pptx の add_movie は「クリックで再生」しか作らないので、
    生成済みの <p:video> の条件とメディアノードを書き換える。"""
    if not (autoplay or loop):
        return
    try:
        timing = slide._element.find(qn('p:timing'))
        if timing is None:
            return
        for vid in timing.iter(qn('p:video')):
            media = vid.find(qn('p:cMediaNode'))
            if media is None:
                continue
            ctn = media.find(qn('p:cTn'))
            tgt = media.find(qn('p:tgtEl'))
            spid = tgt.find(qn('p:spTgt')) if tgt is not None else None
            if spid is None or spid.get('spid') != str(pic.shape_id):
                continue   # 別の動画のノード
            if loop:
                media.set('repeat', '1')
                if ctn is not None:
                    ctn.set('repeatCount', 'indefinite')
            if autoplay and ctn is not None:
                # クリック待ちを外し、スライド表示と同時に始める
                for cond in ctn.iter(qn('p:cond')):
                    if cond.get('evt') == 'onClick':
                        del cond.attrib['evt']
                    if cond.get('delay') in (None, 'indefinite'):
                        cond.set('delay', '0')
    except Exception as e:
        print(f'  WARN: 動画の自動再生/ループ設定をスキップ: {e}')



# --- SlideKit v2 共有定義ローダ (slidekit-defs.js) --------------------------
# slidekit-defs.js のマーカー間 JSON を読み、色リマップ・図形clamp・テンプレ検索順・
# キャンバス定数を JS 側と共有する。defs が欠落・破損していても例外を外に漏らさず、
# 現行値(v1)と同一のフォールバック定数で変換を続行する。
import json

_DEFS_CACHE = None
_DEFS_BEGIN = '/* SLIDEKIT_DEFS_JSON_BEGIN */'
_DEFS_END = '/* SLIDEKIT_DEFS_JSON_END */'
_DEFS_EXPECTED_VERSION = 2
_AWS_PLUGIN_BEGIN = '/* SLIDEKIT_AWS_JSON_BEGIN */'
_AWS_PLUGIN_END = '/* SLIDEKIT_AWS_JSON_END */'


def _merge_aws_plugin(defs):
    """同ディレクトリの slidekit-aws.js（AWSテンプレ・プラグイン）が存在すれば
    マーカー間 JSON を読んで defs['formats'] へマージする。
    プラグイン破損時は WARN を出して aws 無し扱い（例外は外に漏らさない）。
    version 不一致（!=2）も WARN で続行。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slidekit-aws.js')
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
        raw = text.split(_AWS_PLUGIN_BEGIN, 1)[1].split(_AWS_PLUGIN_END, 1)[0]
        plugin = json.loads(raw)
        if plugin.get('version') != _DEFS_EXPECTED_VERSION:
            print(f"WARN: slidekit-aws.js の version {plugin.get('version')} != {_DEFS_EXPECTED_VERSION}（続行）")
        defs.setdefault('formats', {}).update(plugin.get('formats') or {})
    except Exception as e:
        print(f'WARN: slidekit-aws.js 読込失敗 ({e})。AWSテンプレなしで続行')


def load_defs():
    """slidekit-defs.js からマーカー間の JSON を抽出して dict を返す。
    同ディレクトリに slidekit-aws.js（AWSテンプレ・プラグイン）があれば formats へマージする。
    失敗時は None（呼び出し側が現行値と同一の既定値へフォールバック）。例外は外に漏らさない。"""
    global _DEFS_CACHE
    if _DEFS_CACHE is not None:
        return _DEFS_CACHE
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slidekit-defs.js')
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
        raw = text.split(_DEFS_BEGIN, 1)[1].split(_DEFS_END, 1)[0]
        defs = json.loads(raw)
        if defs.get('version') != _DEFS_EXPECTED_VERSION:
            print(f"WARN: slidekit-defs.js の version {defs.get('version')} != {_DEFS_EXPECTED_VERSION}（続行）")
        _merge_aws_plugin(defs)
        _DEFS_CACHE = defs
        return defs
    except Exception as e:
        print(f'WARN: slidekit-defs.js 読込失敗 ({e})。組み込み既定値で続行')
        return None


# (shape_key, param) → (min, max, default)。add_rect_shape の現行 clamp 値と同一
_SHAPE_CLAMP_FALLBACK = {
    ('arrow', 'at'):   (0.05, 0.95, 0.45),  # 軸の太さ
    ('arrow', 'ah'):   (0.05, 0.90, 0.32),  # 矢じりの長さ
    ('chevron', 'cv'): (0.02, 0.60, 0.14),  # 先端が占める幅の割合
    ('callout', 'bx'): (0.08, 0.92, 0.30),  # 吹き出しのしっぽ先端x位置
}

# キャンバス定数（16:9 スライドの px / EMU）
_CANVAS_FALLBACK = {'wPx': 1280, 'hPx': 720, 'wEmu': 12192000, 'hEmu': 6858000}

# PowerPointネイティブ箇条書き（data-bullet="native-disc" / "native-decimal"）のレベル定義。
# defs.list と同値。ブラウザ側は同じ定義から CSS(::before) を作るので見た目が一致する。
_LIST_FALLBACK = {
    'maxLevel': 5,
    'circledSymbols': '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳',
    'kinds': {
        'native-disc': {
            'stepEm': 1.4,
            'levels': [{'char': '・'}, {'char': '–'}, {'char': '·'},
                       {'char': '–'}, {'char': '·'}],
        },
        'native-decimal': {
            'stepEm': 1.9,
            'levels': [{'autoNum': 'circleNumDbPlain'}, {'autoNum': 'arabicParenR'},
                       {'autoNum': 'alphaLcParenR'}, {'autoNum': 'romanLcPeriod'},
                       {'autoNum': 'arabicPeriod'}],
        },
    },
}


def get_list_def(bullet):
    """ネイティブ箇条書きの定義（stepEm / levels）を返す。
    data-bullet が旧方式（disc / decimal）や未指定なら None（＝呼び出し側は従来のぶら下げ処理）。"""
    if not bullet or not str(bullet).startswith('native-'):
        return None
    defs = load_defs()
    src = None
    if defs:
        try:
            src = defs['list']['kinds'][bullet]
        except (KeyError, TypeError):
            src = None
    if src is None:
        src = _LIST_FALLBACK['kinds'].get(bullet)
    if not src or not src.get('levels'):
        print(f'WARN: data-bullet="{bullet}" の定義が無い。箇条書きなしで続行')
        return None
    return src


def get_aws_format():
    """マージ後 defs の formats.aws を返す。未登録（プラグイン無し等）は None。
    AWS固有データの正本は slidekit-aws.js プラグインのみ（コアにフォールバック値を持たない）。"""
    defs = load_defs()
    fmts = defs.get('formats') if isinstance(defs, dict) else None
    return fmts.get('aws') if isinstance(fmts, dict) else None


def get_aws_cover_remap():
    """AWS表紙の色リマップ表を返す（キー・値とも小文字正規化）。
    aws 未登録（プラグイン無し）・defs 異常時は {}（リマップなし）。"""
    fmt = get_aws_format()
    if not fmt:
        return {}
    try:
        return {k.lower(): v.lower() for k, v in fmt['coverRemap'].items()}
    except (KeyError, AttributeError, TypeError) as e:
        print(f'WARN: formats.aws.coverRemap 不正 ({e})。リマップなしで続行')
        return {}


def get_shape_clamp(shape_key, param):
    """図形パラメータの (min, max, default) を返す。例: get_shape_clamp('arrow', 'at')"""
    defs = load_defs()
    if defs:
        try:
            p = defs['shapes'][shape_key]['params'][param]
            return (p['min'], p['max'], p['default'])
        except (KeyError, TypeError):
            pass
    return _SHAPE_CLAMP_FALLBACK[(shape_key, param)]


def get_pptx_template_search():
    """AWSテンプレートPPTX検索定義を (envVar, candidates) で返す。candidates はスクリプト基準の相対パス。
    aws 未登録（プラグイン無し）時は (None, [])（テンプレなし）。"""
    fmt = get_aws_format()
    if not fmt:
        return (None, [])
    try:
        t = fmt['pptxTemplate']
        return (t['envVar'], list(t['candidates']))
    except (KeyError, TypeError) as e:
        print(f'WARN: formats.aws.pptxTemplate 不正 ({e})。テンプレなしで続行')
        return (None, [])


def get_canvas_defaults():
    """16:9 キャンバスの (wPx, hPx, wEmu, hEmu) を返す。defs 異常時はフォールバック。"""
    defs = load_defs()
    if defs:
        try:
            c = defs['canvas']
            return (int(c['wPx']), int(c['hPx']), int(c['wEmu']), int(c['hEmu']))
        except (KeyError, TypeError, ValueError) as e:
            print(f'WARN: defs.canvas 不正 ({e})。組み込み既定値を使用')
    c = _CANVAS_FALLBACK
    return (c['wPx'], c['hPx'], c['wEmu'], c['hEmu'])


def _mso_shape_enum(shape_key, fallback):
    """defs.shapes[shape_key].mso を getattr(MSO_SHAPE, 名前) で解決する。
    defs 異常・mso が null・名前解決失敗時は fallback（v1 と同じ MSO_SHAPE 値）を返す。"""
    defs = load_defs()
    if defs:
        try:
            name = defs['shapes'][shape_key]['mso']
            if name:
                return getattr(MSO_SHAPE, name)
        except (KeyError, TypeError, AttributeError):
            pass
    return fallback
# ---------------------------------------------------------------------------


# キャンバス定数は slidekit-defs.js (canvas) が正本。defs 異常時は get_canvas_defaults が
# 組み込み既定値 (_CANVAS_FALLBACK = v1 と同値) を返すため、defs 有無で出力は不変。
SLIDE_W_PX, SLIDE_H_PX, SLIDE_W_EMU, SLIDE_H_EMU = get_canvas_defaults()
FONT_NAME = 'Yu Gothic'  # 既定。main()でHTMLのbody font-familyから自動上書き

# ページサイズプリセット（<html data-page-size="..."> で選択）
# EMU: 1 inch = 914400 EMU, A4 = 210×297mm = 8.2677×11.6929 inch
PAGE_SIZE_PRESETS = {
    '16-9': (1280, 720, 12192000, 6858000),         # デフォルト（16:9スライド）
    '4-3':  (1024, 768, 9144000, 6858000),           # 4:3 スライド
    'a4-portrait':  (794, 1123, 7560000, 10692000),  # A4タテ（210×297mm）
    'a4-landscape': (1123, 794, 10692000, 7560000),  # A4ヨコ（297×210mm）
}

def configure_page_size(html_el):
    """<html data-page-size="a4-portrait"> 等から SLIDE_W/H を切替。
    既定は 16-9 で従来のスライド互換を維持。"""
    global SLIDE_W_PX, SLIDE_H_PX, SLIDE_W_EMU, SLIDE_H_EMU
    ps = ''
    if html_el is not None:
        ps = (html_el.get('data-page-size') or '').strip().lower()
    if ps and ps in PAGE_SIZE_PRESETS:
        SLIDE_W_PX, SLIDE_H_PX, SLIDE_W_EMU, SLIDE_H_EMU = PAGE_SIZE_PRESETS[ps]
        print(f"ページサイズ: {ps} ({SLIDE_W_PX}×{SLIDE_H_PX}px / {SLIDE_W_EMU/914400*25.4:.1f}×{SLIDE_H_EMU/914400*25.4:.1f}mm)")
    # 未指定 or 未知の値は 16-9 のまま

# CSS px → PowerPoint pt 換算（ブラウザは 96dpi、PowerPoint は 72dpi）
# 1px = 0.75pt。この換算をしないとPPTX側でフォントが約33%大きくなり改行位置が変わる
def px_to_pt(px):
    return px * 72 / 96
EMU_PER_PT = 12700
BASE_DIR = '.'  # 画像はHTMLファイルからの相対で解決（main()で設定）

def set_font_name(font, name):
    """font.name は <a:latin> しか設定しないので、日本語グリフ用の <a:ea> も同じtypefaceで書く。
    OOXML内 <a:rPr> の子要素順は latin → ea → cs。順序違反は修復対象になる。"""
    font.name = name  # <a:latin typeface="...">
    try:
        rPr = font._rPr
        if rPr is None:
            return
        ea = rPr.find(qn('a:ea'))
        if ea is None:
            from lxml import etree
            ea = etree.SubElement(rPr, qn('a:ea'))
            latin = rPr.find(qn('a:latin'))
            if latin is not None:
                # latin の直後に移動
                rPr.remove(ea)
                latin.addnext(ea)
        ea.set('typeface', name)
    except Exception:
        pass


def apply_hanging(p, bullet, font_size):
    """data-bullet があれば段落にぶら下げ字下げを設定（marL=字下げ, indent=初行の戻し）。font_sizeはpx値。"""
    if not bullet:
        return
    em = 1.9 if bullet == 'decimal' else 1.4
    # font_size は px なので pt に換算してから EMU に
    marL = int(em * float(px_to_pt(font_size)) * EMU_PER_PT)
    pPr = p._p.get_or_add_pPr()
    pPr.set('marL', str(marL))
    pPr.set('indent', str(-marL))


# ---- PowerPointネイティブ箇条書き（buChar / buAutoNum / lvl）----
# 旧方式（data-bullet="disc"/"decimal"）はマーカーを本文文字として持つのでそのまま。
# ネイティブ方式（"native-disc"/"native-decimal"）はマーカーを持たず、PowerPointが描く。
# これで PowerPoint 上の Enter（次項目にもマーカー）・Tab/Shift+Tab（レベル送り）が効く。

def _xml_attr(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _bullet_inner_xml(level_def, font_name):
    """1レベル分のマーカー定義を <a:buFont>+<a:buChar|a:buAutoNum> の文字列で返す。"""
    xml = '<a:buFont typeface="%s"/>' % _xml_attr(font_name)
    if level_def.get('autoNum'):
        return xml + '<a:buAutoNum type="%s"/>' % _xml_attr(level_def['autoNum'])
    return xml + '<a:buChar char="%s"/>' % _xml_attr(level_def.get('char', '・'))


def _level_indent_emu(list_def, lvl, font_size):
    """レベル lvl の (marL, indent) を EMU で返す。字下げは1段ごとに stepEm 分だけ深くする。"""
    step = float(list_def.get('stepEm', 1.4)) * float(px_to_pt(font_size)) * EMU_PER_PT
    return int(step * (lvl + 1)), int(-step)


def apply_list_style(tf, bullet, font_size):
    """txBody に <a:lstStyle> を入れて、PowerPoint側で Tab / Shift+Tab したときの
    字下げ・マーカーが SlideKit の見た目と一致するようにする（レベル1〜5を定義）。
    すでに lstStyle があれば何もしない（1つの図形に複数tbが入る .rect でも安全）。"""
    list_def = get_list_def(bullet)
    if list_def is None:
        return
    txBody = tf._txBody
    exist = txBody.find(qn('a:lstStyle'))
    # python-pptx が add_textbox 時に空の <a:lstStyle/> を作るので「有る」だけでは判定できない。
    # 中身が入っていれば設定済み（.rect 内に複数tbがある場合の二重適用を防ぐ）
    if exist is not None and len(exist):
        return
    parts = []
    for i, lv in enumerate(list_def['levels']):
        marL, indent = _level_indent_emu(list_def, i, font_size)
        parts.append('<a:lvl%dpPr marL="%d" indent="%d">%s</a:lvl%dpPr>'
                     % (i + 1, marL, indent, _bullet_inner_xml(lv, FONT_NAME), i + 1))
    try:
        lst = parse_xml('<a:lstStyle %s>%s</a:lstStyle>' % (nsdecls('a'), ''.join(parts)))
    except Exception as e:
        print(f'WARN: lstStyle生成失敗 ({e})。段落側の指定のみで続行')
        return
    if exist is not None:
        for child in list(lst):
            exist.append(child)
        return
    bodyPr = txBody.find(qn('a:bodyPr'))
    if bodyPr is not None:
        bodyPr.addnext(lst)
    else:
        txBody.insert(0, lst)


def apply_bullet(p, bullet, font_size, lvl=0):
    """段落に箇条書きを設定する。
    旧方式（disc / decimal）＝ぶら下げ字下げのみ（マーカーは本文文字）。
    ネイティブ方式（native-*）＝lvl + buChar/buAutoNum をPowerPointの箇条書きとして書く。"""
    if not bullet:
        return
    list_def = get_list_def(bullet)
    if list_def is None:
        apply_hanging(p, bullet, font_size)
        return
    levels = list_def['levels']
    k = max(0, min(int(lvl or 0), len(levels) - 1))
    p.level = k
    marL, indent = _level_indent_emu(list_def, k, font_size)
    pPr = p._p.get_or_add_pPr()
    pPr.set('marL', str(marL))
    pPr.set('indent', str(indent))
    # a:pPr の子要素順は buFont → buChar/buAutoNum → defRPr。defRPr の前に差す
    try:
        frag = parse_xml('<a:wrap %s>%s</a:wrap>'
                         % (nsdecls('a'), _bullet_inner_xml(levels[k], FONT_NAME)))
    except Exception as e:
        print(f'WARN: 箇条書きマーカー生成失敗 ({e})。字下げのみ設定')
        return
    ref = pPr.find(qn('a:defRPr'))
    for child in list(frag):
        if ref is not None:
            ref.addprevious(child)
        else:
            pPr.append(child)


def px_to_emu_x(px):
    return int(px * SLIDE_W_EMU / SLIDE_W_PX)

def px_to_emu_y(px):
    return int(px * SLIDE_H_EMU / SLIDE_H_PX)

_NAMED_COLORS = {'white': 'ffffff', 'black': '000000', 'red': 'ff0000', 'gray': '808080', 'grey': '808080'}
_WARNED_COLORS = set()


def css_color_hex6(v):
    """CSSの色（#rgb/#rrggbb/#rrggbbaa・rgb()/rgba()・一部の色名）を 'rrggbb' にする。解釈できなければ None。
    2026-09-27: 以前は hex 以外を黙って濃灰 #333333 にしていた（rgba() の台座が不透明な濃灰になる）"""
    if not v:
        return None
    s = str(v).strip().lower()
    m = re.match(r'^#?([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$', s)
    if m:
        h = m.group(1)
        return (''.join(c * 2 for c in h) if len(h) == 3 else h[:6])
    m = re.match(r'^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', s)
    if m:
        return ''.join('%02x' % min(255, int(x)) for x in m.groups())
    return _NAMED_COLORS.get(s)


def hex_to_rgb(h):
    # #fff → #ffffff、8桁は先頭6桁を採用（αは無視）。rgb()/rgba()/色名も受ける。解釈できなければ既定色＋WARN
    if not h:
        return RGBColor(0x33, 0x33, 0x33)
    x = css_color_hex6(h)
    if x:
        return RGBColor(int(x[0:2], 16), int(x[2:4], 16), int(x[4:6], 16))
    if h not in _WARNED_COLORS:
        _WARNED_COLORS.add(h)
        print(f'  WARN: 色を解釈できない ({h!r}) → #333333 で出力。#rrggbb で書く')
    return RGBColor(0x33, 0x33, 0x33)


def _is_valid_hex(v):
    """3/6/8桁hex、または rgb()/rgba()・色名で色として解釈できるなら True"""
    if not v:
        return False
    return css_color_hex6(v) is not None

def parse_gradient(val):
    # "135" / "135deg" / " 135 , #xxx , #yyy " 全部対応。失敗時は 135°/黒/白 でフォールバック
    try:
        parts = [p.strip() for p in (val or '').split(',')]
        if len(parts) < 3:
            raise ValueError(f'gradient tokens < 3: {val!r}')
        angle_str = re.sub(r'deg\s*$', '', parts[0], flags=re.IGNORECASE).strip()
        angle = float(angle_str)
        c1 = parts[1]
        c2 = parts[2]
        if not (_is_valid_hex(c1) and _is_valid_hex(c2)):
            raise ValueError(f'invalid hex: c1={c1} c2={c2}')
        return angle, c1, c2
    except Exception as e:
        print(f'  WARN: parse_gradient失敗({e}) → 既定値(135°,#183251,#21537f)にフォールバック')
        return 135.0, '#183251', '#21537f'

def set_gradient(slide, angle, c1, c2):
    bg = slide.background
    fill = bg.fill
    fill.gradient()
    # python-pptx の gradient_angle は「度」を渡すAPI（内部で60000倍される）
    # CSS の角度(真上=0°、時計回り) → OOXML の角度(右=0°、時計回り)に変換
    # 範囲を [0, 360) に正規化しないと ang=21600000 に張り付いてPowerPoint修復対象になる
    fill.gradient_angle = (360 - ((angle - 90) % 360)) % 360
    stops = fill.gradient_stops
    stops[0].color.rgb = hex_to_rgb(c1)
    stops[0].position = 0.0
    stops[1].color.rgb = hex_to_rgb(c2)
    stops[1].position = 1.0

def remove_shadow(shape, shadow=None):
    """影を制御する。
    shadow=None または 'none': 影なし（既定/PPTXのデフォルト影を明示的に削除）
    shadow='soft': 薄い外側シャドウを付与（box-shadow: 0 2px 8px rgba(0,0,0,.08) 相当）
    """
    spPr = shape._element.spPr
    for ef in spPr.findall(qn('a:effectLst')):
        spPr.remove(ef)
    if shadow == 'soft':
        # outerShdw: 半径63500EMU=5pt, 距離25400EMU=2pt, 方向5400000=下向き, 黒20%透過
        xml = (
            '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:outerShdw blurRad="63500" dist="25400" dir="5400000" algn="t" rotWithShape="0">'
            '<a:srgbClr val="000000"><a:alpha val="20000"/></a:srgbClr>'
            '</a:outerShdw>'
            '</a:effectLst>'
        )
        spPr.append(parse_xml(xml))
    else:
        spPr.append(parse_xml('<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'))

def get_align(val):
    if val == 'center': return PP_ALIGN.CENTER
    if val == 'right': return PP_ALIGN.RIGHT
    return PP_ALIGN.LEFT

def get_text(el):
    # インライン要素間の空白を潰さない: 個別 strip をやめ、結合後に連続空白を1個に正規化
    texts = []
    for child in el.children:
        if isinstance(child, str):
            texts.append(str(child))
        elif child.name == 'br':
            texts.append('\n')
        elif 'li' in (child.get('class') or []):
            # ネイティブ箇条書きの項目（.li）は1行として扱う
            texts.append(child.get_text() + '\n')
        else:
            texts.append(child.get_text())
    s = ''.join(texts)
    # 改行は保持、行内のtab/連続半角空白のみ1個に(全角空白はそのまま)
    lines = [re.sub(r'[ \t]+', ' ', ln).strip() for ln in s.split('\n')]
    return '\n'.join(lines).strip('\n').strip()

_BLOCK_TAGS = {'div', 'p', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'section'}


def _collapse_ws(s):
    """ブラウザと同じ空白の畳み方: 半角空白・タブ・改行だけを1個に畳む。
    全角スペース(U+3000)は畳まない。&nbsp; は畳まずに半角スペースへ。
    2026-09-27: 以前は Python の \\s で全角スペースと &nbsp; まで潰し、字下げや区切りが消えていた"""
    return re.sub(r'[ \t\r\n\f\v]+', ' ', s).replace('\xa0', ' ')


def _is_trailing(node):
    """node の後ろに空白以外の兄弟が無いか"""
    for sib in node.next_siblings:
        if isinstance(sib, str):
            if sib.strip(' \t\r\n'):
                return False
            continue
        return False
    return True


def rich_lines(el, fs, bold, color):
    """tb内を再帰走査し、span単位の書式を保った行リストを返す。
    返り値: [(runs, line_align, lvl)] / runs = [(text, fs_px, bold, color_hex)]
    spanの font-weight / font-size / color / text-align を反映する。
    lvl = ネイティブ箇条書きの階層（.li の data-lvl。無ければ 0）。
    🚨tbのdata属性だけで塗りつぶすと「見出しのみ太字・本文はspanで400」の
    カードが全文太字のPPTXになる（2026-07-18実地で発生）。"""
    lines = [{'runs': [], 'align': None, 'lvl': 0}]

    def newline():
        # 階層は直前の行から引き継ぐ（.li の中に<br>があっても同じレベルの続きになる）
        lines.append({'runs': [], 'align': None, 'lvl': lines[-1]['lvl']})

    def walk(node, fs, bold, color, align, in_block=False):
        for child in node.children:
            if isinstance(child, str):
                # HTMLと同じく半角空白・改行・タブだけを1個に潰す（&nbsp; は畳まず半角スペースへ）。
                # 🚫 \s は全角空白(U+3000)も含むため、位置合わせの「▼　　▼」が「▼ ▼」に潰れていた（2026-09-27）
                t = _collapse_ws(str(child))
                if t.strip(' ') or (t == ' ' and lines[-1]['runs']):
                    lines[-1]['runs'].append((t, fs, bold, color))
                    if align and lines[-1]['align'] is None:
                        lines[-1]['align'] = align
                continue
            if child.name == 'br':
                # ブロック要素の末尾の <br> はブラウザでは行を増やさない（Enterで入る <div>…<br></div>）
                if in_block and _is_trailing(child):
                    continue
                newline()
                continue
            st = child.get('style', '') or ''
            nfs, nb, nc, nal = fs, bold, color, align
            # <b>/<strong> はブラウザでは太字。styleが無くても太字にする
            # 🚫 以前は style の font-weight しか見ず、本文中の強調がPPTXで全部消えていた（2026-09-27・韓国L7で発見）
            if child.name in ('b', 'strong'):
                nb = True
            m = re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*px', st)
            if m: nfs = float(m.group(1))
            m = re.search(r'font-weight\s*:\s*(\d+|bold|normal)', st)
            if m:
                v = m.group(1)
                nb = (v == 'bold') or (v.isdigit() and int(v) >= 600)
            # hex に加えて rgb()/rgba() も拾う（ブラウザで貼った文字や手書きHTMLに多い・2026-09-27）
            m = re.search(r'(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))', st)
            if m and css_color_hex6(m.group(1)): nc = css_color_hex6(m.group(1))
            m = re.search(r'text-align\s*:\s*(left|center|right)', st)
            if m: nal = m.group(1)
            # ネイティブ箇条書きの項目（.li）＝1行1段落。data-lvl をその行の階層にする
            if 'li' in (child.get('class') or []):
                if lines[-1]['runs']:
                    newline()
                try:
                    lines[-1]['lvl'] = max(0, int(child.get('data-lvl') or 0))
                except (TypeError, ValueError):
                    lines[-1]['lvl'] = 0
                walk(child, nfs, nb, nc, nal, True)
                newline()
                continue
            # div/p 等はブラウザの既定で改行される（2026-09-27: 以前は display:block を書いた時だけ改行した）
            disp = re.search(r'display\s*:\s*([\w-]+)', st)
            if disp:
                is_block = not disp.group(1).startswith('inline')
            else:
                is_block = child.name in _BLOCK_TAGS
            if is_block and lines[-1]['runs']:
                newline()
            walk(child, nfs, nb, nc, nal, is_block)
            if is_block:
                newline()
        return

    walk(el, fs, bold, color, None)
    # 行頭・行末の空白を除去し、空行（連続brの間以外の末尾）を整理
    out = []
    for ln in lines:
        runs = ln['runs']
        if runs:
            # 半角スペースだけ落とす。全角スペース（字下げ）はブラウザでも残るので残す
            t0, f0, b0, c0 = runs[0]
            runs[0] = (t0.lstrip(' '), f0, b0, c0)
            t1, f1, b1, c1 = runs[-1]
            runs[-1] = (t1.rstrip(' '), f1, b1, c1)
            runs = [r for r in runs if r[0]]
        out.append((runs, ln['align'], ln['lvl']))
    # 末尾の空行を落とす
    while out and not out[-1][0]:
        out.pop()
    # 先頭の空行も落とす
    while out and not out[0][0]:
        out.pop(0)
    return out

def _effective_color(el):
    """tbの実効文字色を返す。テキスト全体が単一<span style="color:...">で
    包まれている場合はspanの色が勝つ（ブラウザ表示と同じ）。
    data-colorだけ読むと紺地に紺文字など読めない出力になる（2026-07-18実地で発生）。"""
    color = (el.get('data-color') or '#333333').lstrip('#')
    kids = [c for c in el.children if getattr(c, 'name', None)]
    if len(kids) == 1 and kids[0].name == 'span':
        if kids[0].get_text(strip=True) == el.get_text(strip=True):
            m = re.search(r'color\s*:\s*(#[0-9a-fA-F]{3,8})', kids[0].get('style', '') or '')
            if m:
                color = m.group(1).lstrip('#')
    return color

def _line_spacing_of(el, font_size_px):
    """CSSの line-height をPPTXの行間に変換する。
    インラインstyleに明示指定がある時だけ返す（Noneなら書き出さない＝PowerPoint既定）。
    既定を書き出さない理由: フォント固有の行送り（Meiryo UIは約1.75em）が使われ、
    行間未指定で組まれた合流先デッキと行送りが揃うため。
    換算: CSSのunitless(1.4等)は「フォントサイズ×倍率」なのでポイント実寸に直して返す
    （PPTXのmultipleは「フォント固有行送り×倍率」で意味が違い、そのまま渡すと開きすぎる）。
    px指定はそのまま Pt に換算。"""
    m = re.search(r'line-height\s*:\s*([\d.]+)(px|%|em)?', el.get('style', '') or '')
    if not m:
        return None
    try:
        v = float(m.group(1))
        if m.group(2) == 'px':
            return Pt(px_to_pt(v))
        if m.group(2) == '%':  # 150% は 1.5 倍（以前は 150 倍の巨大な行間になっていた）
            v = v / 100.0
        return Pt(px_to_pt(v * font_size_px))
    except Exception:
        return None

def _apply_rotation(shape, *els):
    """data-rotate（度・時計回り・中心基準）を shape.rotation に反映。
    CSS transform:rotate() と PPTX の rot は同じ向き・同じ中心なのでそのまま渡す。
    els は候補要素（最初に data-rotate を持つものを採用。画像はラッパーdiv側が持つ）。"""
    for el in els:
        if el is None:
            continue
        v = el.get('data-rotate') if hasattr(el, 'get') else None
        if v is None:
            continue
        try:
            rot = float(v) % 360
            if rot:
                shape.rotation = rot
        except (TypeError, ValueError) as e:
            print(f'  WARN: data-rotate 反映失敗: {v} ({e})')
        return

# ページジャンプリンク（data-link-sid → .slide[data-sid]）。
# 前方参照（後のスライドへのリンク）があるため、生成中は溜めて全スライド生成後に解決する
_SID_TO_SLIDE = {}
_PENDING_SLIDE_LINKS = []  # (shape, sid) のリスト


def _register_link(shape, *els):
    """要素の data-link-sid を控える（解決は _resolve_slide_links）。画像はラッパーdiv側が持つ"""
    for el in els:
        if el is None:
            continue
        sid = el.get('data-link-sid') if hasattr(el, 'get') else None
        if sid:
            _PENDING_SLIDE_LINKS.append((shape, sid))
            return


def _resolve_slide_links():
    """全スライド生成後に click_action.target_slide を張る（PowerPointのスライドジャンプ）"""
    for shape, sid in _PENDING_SLIDE_LINKS:
        target = _SID_TO_SLIDE.get(sid)
        if target is None:
            print(f'  WARN: data-link-sid="{sid}" の行き先スライド（data-sid）が無い → リンクを張らずに続行')
            continue
        try:
            shape.click_action.target_slide = target
        except Exception as e:
            print(f'  WARN: スライドリンク設定失敗 ({sid}): {e}')


def _apply_flip(shape, *els):
    """data-flip="h"/"v"/"hv" を a:xfrm の flipH/flipV に反映。
    表示側CSSは rotate()→scaleX/Y(-1) の順（=反転してから回転）で、DrawingMLと同じ合成順。"""
    for el in els:
        if el is None:
            continue
        v = el.get('data-flip') if hasattr(el, 'get') else None
        if v is None:
            continue
        try:
            xfrm = shape._element.spPr.xfrm
            if xfrm is not None:
                if 'h' in v:
                    xfrm.set('flipH', '1')
                if 'v' in v:
                    xfrm.set('flipV', '1')
        except Exception as e:
            print(f'  WARN: data-flip 反映失敗: {e}')
        return


def _measured_lines(el, lines):
    """--measured: 文字ごとの太字・大きさ・色をブラウザの実測値にする（段落・改行の組み方は変換側のまま）。
    文字の並びが合わない時は従来の読み取りのまま続ける"""
    if not (MEASURED and MEASURE_FULL):
        return lines
    r = MEASURED['els'].get(el.get('data-mid') or '')
    if not r or not r.get('runs'):
        return lines
    import measure_layout as _ML
    out, ok = _ML.remap_runs(lines, r['runs'], keep_color=(CUR_SLIDE in MEASURED.get('cover', [])))
    if not ok:
        _lab = re.sub(r'\s+', ' ', el.get_text() or '').strip()[:20]
        print(f'  INFO: S{CUR_SLIDE} 実測と文字の並びが合わないため従来の読み取りで変換: 「{_lab}」')
    return out


def _add_free_layout(slide, items):
    """--measured: SlideKit の型に乗っていない自由配置の div を、見えている箱と文字のまま置く。
    従来はこの div ごと PPTX から消えていた（data-x の無い flex の行など）"""
    for it in items:
        x, y, w, h = it['x'], it['y'], max(1, it['w']), max(1, it['h'])
        if it['k'] == 'box' and it.get('fill'):
            sh = slide.shapes.add_shape(1, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h))
            sh.fill.solid()
            sh.fill.fore_color.rgb = hex_to_rgb(it['fill'])
            sh.line.fill.background()
            remove_shadow(sh)
            continue
        if it['k'] != 'text':
            continue
        one_line = h <= it['fs'] * 1.8
        # 1行の文字は少し幅に余裕を持たせて折り返さない（PowerPointの字幅の差で2行にならないように）
        tb = slide.shapes.add_textbox(px_to_emu_x(x), px_to_emu_y(y),
                                      px_to_emu_x(w + (6 if one_line else 2)), px_to_emu_y(h))
        tf = tb.text_frame
        tf.word_wrap = not one_line
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = get_align(it.get('ta'))
        r = p.add_run()
        r.text = it['t']
        r.font.size = Pt(px_to_pt(it['fs']))
        r.font.bold = bool(it.get('b'))
        set_font_name(r.font, FONT_NAME)
        if _is_valid_hex(it.get('c')):
            r.font.color.rgb = hex_to_rgb(it['c'])


def add_textbox(slide, el):
    x = int(el.get('data-x', 0))
    y = int(el.get('data-y', 0))
    w = int(el.get('data-w', 400))
    h = int(el.get('data-h', 30))
    text = get_text(el)
    if not text:
        return
    
    txBox = slide.shapes.add_textbox(
        px_to_emu_x(x), px_to_emu_y(y),
        px_to_emu_x(w), px_to_emu_y(h)
    )
    _apply_rotation(txBox, el)
    _register_link(txBox, el)
    tf = txBox.text_frame
    tf.word_wrap = True
    # 内側margin(padding)をゼロ化＝ブラウザの.tbと同じ実効幅にして改行位置を揃える
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    
    font_size = float(el.get('data-font-size', 17))
    bold = el.get('data-bold') == '1'
    color = _effective_color(el)
    align = get_align(el.get('data-align', 'left'))
    bullet = el.get('data-bullet')

    # data-valign（SlideKit編集UIの上下揃え）をテキストフレームのアンカーに反映
    valign = el.get('data-valign')
    if valign == 'middle':
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    elif valign == 'bottom':
        tf.vertical_anchor = MSO_ANCHOR.BOTTOM

    # span単位の書式（太字/サイズ/色/揃え）を保ってrunに変換する
    _ls = _line_spacing_of(el, font_size)
    apply_list_style(tf, bullet, font_size)  # ネイティブ箇条書きのみ効く（Tabレベル送り用）
    for i, (runs, lal, lvl) in enumerate(_measured_lines(el, rich_lines(el, font_size, bold, color))):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.alignment = get_align(lal) if lal else align
        if _ls is not None:
            p.line_spacing = _ls  # インラインline-height指定時のみ反映
        # 段落既定はtbのベース書式（PowerPointでの追記時に引き継がれる）
        p.font.size = Pt(px_to_pt(font_size))
        p.font.bold = bold
        set_font_name(p.font, FONT_NAME)
        if _is_valid_hex(color):
            p.font.color.rgb = hex_to_rgb(color)
        for (t, rfs, rb, rc) in runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(px_to_pt(rfs))
            r.font.bold = rb
            set_font_name(r.font, FONT_NAME)
            if _is_valid_hex(rc):
                r.font.color.rgb = hex_to_rgb(rc)
        apply_bullet(p, bullet, font_size, lvl)

def _cell_rich_paragraphs(cell):
    """<td>/<th>内を <br> 区切りの段落と run (text, bold, color_hex, font_px) に分解する。
    b/strong は太字、span等の style から font-weight・color・font-size を拾う。
    従来は get_text() で平文化していたため、セル内の部分太字が PPTX で落ちていた
    （2026-08-28 実地: 完了条件表の <b> が全て解除された）。"""
    paras = [[]]
    def walk(node, b, c, fs):
        for ch in node.children:
            if isinstance(ch, str):
                t = _collapse_ws(str(ch))
                if t.strip(' ') or (t == ' ' and paras[-1]):
                    paras[-1].append((t, b, c, fs))
                continue
            if ch.name == 'br':
                paras.append([])
                continue
            nb, nc, nfs = b, c, fs
            if ch.name in ('b', 'strong'):
                nb = True
            st = ch.get('style', '') or ''
            m = re.search(r'font-weight\s*:\s*(\d+|bold|normal)', st)
            if m:
                v = m.group(1)
                nb = (v == 'bold') or (v.isdigit() and int(v) >= 600)
            m = re.search(r'(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{3,8})', st)
            if m: nc = m.group(1).lstrip('#')
            m = re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*px', st)
            if m: nfs = float(m.group(1))
            walk(ch, nb, nc, nfs)
    walk(cell, None, None, None)
    out = []
    for runs_ in paras:
        if runs_:
            t0 = runs_[0]; runs_[0] = (t0[0].lstrip(' '),) + t0[1:]
            t1 = runs_[-1]; runs_[-1] = (t1[0].rstrip(' '),) + t1[1:]
            runs_ = [r for r in runs_ if r[0]]
        out.append(runs_)
    while len(out) > 1 and not out[-1]:
        out.pop()
    return out

_ANCHOR_OF = {
    'flex-start': MSO_ANCHOR.TOP, 'start': MSO_ANCHOR.TOP, 'top': MSO_ANCHOR.TOP,
    'center': MSO_ANCHOR.MIDDLE, 'middle': MSO_ANCHOR.MIDDLE,
    'flex-end': MSO_ANCHOR.BOTTOM, 'end': MSO_ANCHOR.BOTTOM, 'bottom': MSO_ANCHOR.BOTTOM,
}
# デッキの<style>にある .rect / .flow の縦揃え（main()で読む）。雛形の既定は rect=中央・flow=上
CLASS_VALIGN = {'rect': 'center', 'flow': 'flex-start'}


def read_class_valign(raw_html):
    """デッキ<style>の `.rect{...}` `.flow{...}` から縦方向の揃え(justify-content)を拾う。
    横並び(flex-direction:row)なら縦は align-items。見つからなければ雛形の既定のまま。"""
    out = {'rect': 'center', 'flow': 'flex-start'}
    for cls in out:
        m = re.search(r'(?<![\w>.-])\.' + cls + r'\s*\{([^}]*)\}', raw_html)
        if not m:
            continue
        body = m.group(1)
        key = 'align-items' if re.search(r'flex-direction\s*:\s*row', body) else 'justify-content'
        v = re.search(key + r'\s*:\s*([\w-]+)', body)
        if v and v.group(1) in _ANCHOR_OF:
            out[cls] = v.group(1)
    return out


def _box_anchor(el, classes):
    """rect/flow 内テキストの縦位置。data-valign > インラインstyle > デッキCSSのクラス既定。"""
    dv = el.get('data-valign')
    if dv in _ANCHOR_OF:
        return _ANCHOR_OF[dv]
    st = el.get('style', '') or ''
    key = 'align-items' if re.search(r'flex-direction\s*:\s*row', st) else 'justify-content'
    m = re.search(key + r'\s*:\s*([\w-]+)', st)
    if m and m.group(1) in _ANCHOR_OF:
        return _ANCHOR_OF[m.group(1)]
    base = CLASS_VALIGN['flow'] if 'flow' in classes else CLASS_VALIGN['rect']
    return _ANCHOR_OF.get(base, MSO_ANCHOR.MIDDLE)


def add_rect_shape(slide, el, rounded=False):
    x = int(el.get('data-x', 0))
    y = int(el.get('data-y', 0))
    w = int(el.get('data-w', 400))
    h = int(el.get('data-h', 100))
    fill_color = el.get('data-fill')
    if fill_color is None:
        # data-fill が無ければ style の背景を使う（2026-09-27: 以前は常に薄灰 #f7fafc になり、
        # 紺の台座に白文字のカードが「薄灰に白文字」で読めなくなっていた）
        _bg = re.search(r'background(?:-color)?\s*:\s*([^;]+)', el.get('style', '') or '')
        _bgv = _bg.group(1).strip() if _bg else ''
        if re.match(r'^(none|transparent)\b', _bgv):
            fill_color = 'none'
        elif css_color_hex6(_bgv):
            fill_color = '#' + css_color_hex6(_bgv)
        elif 'gradient' in _bgv:
            _first = re.search(r'#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)', _bgv)
            fill_color = ('#' + css_color_hex6(_first.group(0))) if _first and css_color_hex6(_first.group(0)) else '#fafafa'
            print(f'  WARN: S{CUR_SLIDE} 枠のグラデーション背景はPPTXでは単色（{fill_color}）になる')
        else:
            fill_color = '#fafafa'

    classes = el.get('class', [])
    ds = el.get('data-shape')
    is_chev = ('chev' in classes) or (ds == 'chevron')
    # style / data-radius から角丸 px を拾う（バッジ pill shape 等をPPTXでも再現）
    _style = el.get('style', '') or ''
    _br_m = re.search(r'border-radius\s*:\s*(\d+(?:\.\d+)?)px', _style)
    radius_px = None
    _dr = el.get('data-radius')
    if _dr:
        # "12px" のような単位付きも受ける（以前は例外で握りつぶされ、角が四角になっていた・2026-09-27）
        _drm = re.match(r'\s*(\d+(?:\.\d+)?)', _dr)
        if _drm:
            radius_px = round(float(_drm.group(1)))
    elif _br_m:
        radius_px = round(float(_br_m.group(1)))
    if rounded:
        # PPTX変換ルール: flowの丸みは radius_px に従う。
        #   radius_px == 0 (data-radius="0"/border-radius:0) → 角なし(RECTANGLE)
        #   未指定 → HTML側 .flow の既定(8px)を明示適用（PowerPoint既定の大きい丸みを出さない）
        if radius_px is None:
            radius_px = 8
        shape_enum = MSO_SHAPE.ROUNDED_RECTANGLE if radius_px > 0 else MSO_SHAPE.RECTANGLE
    elif is_chev:
        shape_enum = _mso_shape_enum('chevron', MSO_SHAPE.PENTAGON)  # 右が尖ったホームベース型（矢印）
    elif ds == 'circle':
        shape_enum = _mso_shape_enum('circle', MSO_SHAPE.OVAL)
    elif ds == 'triangle':
        shape_enum = _mso_shape_enum('triangle', MSO_SHAPE.ISOSCELES_TRIANGLE)
    elif ds == 'arrow':
        shape_enum = _mso_shape_enum('arrow', MSO_SHAPE.RIGHT_ARROW)
    elif ds == 'callout':
        shape_enum = _mso_shape_enum('callout', MSO_SHAPE.RECTANGULAR_CALLOUT)
    elif radius_px and radius_px > 0:
        # 通常rectでも border-radius があれば ROUNDED_RECTANGLE で
        shape_enum = MSO_SHAPE.ROUNDED_RECTANGLE
    else:
        shape_enum = 1  # line は塗りつぶしの細い四角としてそのまま出力
    # 吹き出し：HTML箱=本体(上80%)+しっぽ(下20%)。PPTXは本体矩形をshapeにして、
    # しっぽはWEDGE系のadj（中心からの割合）で同じ先端位置を指す
    callout_tail = None
    if ds == 'callout':
        body_h = max(1, round(h * 0.8))
        try:
            bx = float(el.get('data-bx') or 0.3)
        except (TypeError, ValueError):
            bx = 0.3
        _bxmn, _bxmx, _ = get_shape_clamp('callout', 'bx')
        bx = max(_bxmn, min(_bxmx, bx))
        callout_tail = (bx - 0.5, (h - body_h / 2) / body_h)  # adj1=先端x, adj2=先端y（本体中心基準の割合）
        h = body_h
    shape = slide.shapes.add_shape(
        shape_enum,
        px_to_emu_x(x), px_to_emu_y(y),
        px_to_emu_x(w), px_to_emu_y(h)
    )
    _apply_rotation(shape, el)
    _apply_flip(shape, el)
    _register_link(shape, el)
    if callout_tail is not None:
        try:
            shape.adjustments[0] = callout_tail[0]
            shape.adjustments[1] = callout_tail[1]
        except Exception as e:
            print(f'  WARN: callout adj 反映失敗: {e}')
    if is_chev:
        try:
            cv = el.get('data-cv')
            if cv is not None:
                _cvmn, _cvmx, _ = get_shape_clamp('chevron', 'cv')
                adj = max(_cvmn, min(_cvmx, float(cv)))  # 先端が占める幅の割合（data-cvと一致）
            else:
                adj = max(0.05, min(0.40, 14.0 / max(h, 1)))
            shape.adjustments[0] = adj
        except Exception:
            pass
    # ROUNDED_RECTANGLE の丸み度合いを radius_px から反映（0〜0.5、短辺の半分でpill）
    if shape_enum == MSO_SHAPE.ROUNDED_RECTANGLE and radius_px:
        try:
            short = min(w, h) if min(w, h) > 0 else 1
            shape.adjustments[0] = max(0.0, min(0.5, radius_px / short))
        except Exception:
            pass
    if ds == 'arrow':
        try:
            _atmn, _atmx, _atdf = get_shape_clamp('arrow', 'at')
            _ahmn, _ahmx, _ahdf = get_shape_clamp('arrow', 'ah')
            at = float(el.get('data-at', _atdf)); ah = float(el.get('data-ah', _ahdf))
            shape.adjustments[0] = max(_atmn, min(_atmx, at))  # 軸の太さ
            shape.adjustments[1] = max(_ahmn, min(_ahmx, ah))  # 矢じりの長さ
        except Exception:
            pass
    # data-fill="none" or "transparent" は塗りなし(線なし)で出力
    if fill_color in ('none', 'transparent'):
        shape.fill.background()
        shape.line.fill.background()
    else:
        shape.fill.solid()
        # 8桁hex(#RRGGBBAA)は下位2桁をアルファとして半透明塗りに変換（全面画像上の帯テキスト台座用）
        _fc = fill_color.lstrip('#')
        if len(_fc) == 8:
            shape.fill.fore_color.rgb = hex_to_rgb('#' + _fc[:6])
            try:
                _alpha_pct = int(int(_fc[6:8], 16) / 255 * 100000)  # 0-100000 (DrawingML)
                _sf = shape.fill.fore_color._xFill.find(
                    '{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr')
                if _sf is not None:
                    from lxml import etree as _et
                    _a = _et.SubElement(
                        _sf, '{http://schemas.openxmlformats.org/drawingml/2006/main}alpha')
                    _a.set('val', str(_alpha_pct))
            except Exception as e:
                print(f'  WARN: 半透明塗り(8桁hex)の反映失敗: {e}')
        else:
            shape.fill.fore_color.rgb = hex_to_rgb(fill_color)
        shape.line.fill.background()
    remove_shadow(shape, el.get('data-shadow'))

    # 全周ボーダー: data-border="w,#hex" もしくは style="border:1px solid #hex" を shape.line に反映
    # (data-border-left/top はこれとは別のサイド帯として下で別途処理)
    _border_spec = el.get('data-border')
    if not _border_spec:
        _bm = re.search(r'(?<!-)border\s*:\s*(\d+)px\s+\w+\s+(#[0-9a-fA-F]{3,8})', (el.get('style') or ''))
        if _bm:
            _border_spec = _bm.group(1) + ',' + _bm.group(2)
    if _border_spec:
        try:
            _parts = _border_spec.split(',')
            _bw_str, _bc = _parts[0], _parts[1]
            _dash = _parts[2].strip().lower() if len(_parts) > 2 else None  # 'dash'|'dot'（省略=solid）
            _bw_px = max(0.5, float(_bw_str.strip()))
            _bc = _bc.strip()
            if _is_valid_hex(_bc):
                shape.line.color.rgb = hex_to_rgb(_bc)
                shape.line.width = Emu(int(_bw_px * 9525))  # 1px = 9525 EMU
                if _dash in ('dash', 'dashed', 'dot', 'dotted'):
                    from pptx.enum.dml import MSO_LINE  # python-pptx 1.x
                    shape.line.dash_style = MSO_LINE.ROUND_DOT if _dash.startswith('dot') else MSO_LINE.DASH
        except Exception as e:
            print(f'  WARN: data-border 反映失敗: {e}')

    # Border-left
    border_left = el.get('data-border-left')
    if border_left:
        parts = border_left.split(',')
        bw = int(parts[0])
        bc = parts[1].strip()
        # Add thin rect on left side
        border_shape = slide.shapes.add_shape(
            1, px_to_emu_x(x), px_to_emu_y(y),
            px_to_emu_x(bw), px_to_emu_y(h)
        )
        border_shape.fill.solid()
        border_shape.fill.fore_color.rgb = hex_to_rgb(bc)
        border_shape.line.fill.background()
        remove_shadow(border_shape)
    
    # Border-top
    border_top = el.get('data-border-top')
    if border_top:
        parts = border_top.split(',')
        bw = int(parts[0])
        bc = parts[1].strip()
        border_shape = slide.shapes.add_shape(
            1, px_to_emu_x(x), px_to_emu_y(y),
            px_to_emu_x(w), px_to_emu_y(bw)
        )
        border_shape.fill.solid()
        border_shape.fill.fore_color.rgb = hex_to_rgb(bc)
        border_shape.line.fill.background()
        remove_shadow(border_shape)
    
    # Add child text boxes inside the rect
    child_tbs = el.find_all('div', class_='tb', recursive=False)
    if child_tbs:
        # Create a text frame inside the rect shape
        tf = shape.text_frame
        tf.word_wrap = True
        
        # Small rects (badges) need tighter margins
        if h <= 40:
            tf.margin_left = Pt(6)
            tf.margin_top = Pt(0)
            tf.margin_bottom = Pt(0)
            tf.margin_right = Pt(6)
            tf.word_wrap = False
        else:
            tf.margin_left = Pt(12)
            tf.margin_top = Pt(8)
            tf.margin_right = Pt(12)
        # 縦位置はブラウザの見た目に合わせる（バッジ等の小さい図形は常に中央）
        # 🚫 以前は常に中央。.flow は HTML で上揃え(flex-start)なので、カードの中身が下がり
        #    D04 ではバッジと本文が重なっていた（2026-09-27）
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE if h <= 40 else _box_anchor(el, classes)
        
        for i, tb in enumerate(child_tbs):
            text = get_text(tb)
            if not text:
                continue
            font_size = float(tb.get('data-font-size', 15))
            bold = tb.get('data-bold') == '1'
            color = _effective_color(tb)
            align = get_align(tb.get('data-align', 'left'))
            bullet = tb.get('data-bullet')
            
            _ls = _line_spacing_of(tb, font_size)
            apply_list_style(tf, bullet, font_size)  # 最初のネイティブ箇条書きtbで1回だけ入る
            for j, (runs, lal, lvl) in enumerate(_measured_lines(tb, rich_lines(tb, font_size, bold, color))):
                if i == 0 and j == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.alignment = get_align(lal) if lal else align
                if _ls is not None:
                    p.line_spacing = _ls  # インラインline-height指定時のみ反映
                # 段落既定はtbのベース書式
                p.font.size = Pt(px_to_pt(font_size))
                p.font.bold = bold
                set_font_name(p.font, FONT_NAME)
                if _is_valid_hex(color):
                    p.font.color.rgb = hex_to_rgb(color)
                for (t, rfs, rb, rc) in runs:
                    r = p.add_run()
                    r.text = t
                    r.font.size = Pt(px_to_pt(rfs))
                    r.font.bold = rb
                    set_font_name(r.font, FONT_NAME)
                    if _is_valid_hex(rc):
                        r.font.color.rgb = hex_to_rgb(rc)
                apply_bullet(p, bullet, font_size, lvl)

def _parse_len_px(style, attr_val, total_px, prop='width'):
    """style="width: 38%" / "width:200px" / 属性 width=200 / height=同 を px に解決。
    総幅(total_px) が渡っていれば % → px を計算。見つからなければ None。"""
    if style:
        m = re.search(rf'\b{prop}\s*:\s*(-?\d+(?:\.\d+)?)\s*(px|%)?', style)
        if m:
            val = float(m.group(1)); unit = m.group(2) or 'px'
            if unit == '%' and total_px:
                return int(val * total_px / 100)
            if unit == 'px':
                return int(val)
    if attr_val:
        try:
            v = str(attr_val).strip()
            if v.endswith('%') and total_px:
                return int(float(v[:-1]) * total_px / 100)
            return int(float(v.replace('px','')))
        except Exception:
            pass
    return None

def _parse_col_widths(table_el, n_cols, total_w_px):
    """列幅を px リストで返す。取得できなければ None。
    優先順: <colgroup><col> → 最初の行の <th>/<td> (colspan 考慮)。"""
    cols = table_el.find_all('col')
    colgroup_widths = None
    if len(cols) == n_cols:
        colgroup_widths = [_parse_len_px(c.get('style',''), c.get('width'), total_w_px, 'width') for c in cols]
        if all(w is not None and w > 0 for w in colgroup_widths):
            return colgroup_widths
        # PPTX変換ルール: colgroupの部分指定（<col>に幅なし＝残り幅）を尊重する。
        # 全滅させて等分に落とすと「1列だけ自動幅」の表で列幅が崩れる（2026-08-31 v0.9-sk S7/S10/S13で発生）
    # 🚨全行を走査し、rowspan/colspanの占有を考慮して論理列ごとの幅指定を拾う。
    # 先頭行だけ見る方式だと「1行目がcolspanの大見出しth」の表で列幅が全滅し、
    # 等分配分→本文が折り返して表が縦に膨らむ（2026-07-18 S8選定基準表で発生）
    widths = list(colgroup_widths) if colgroup_widths else [None] * n_cols
    occupied = {}
    for r_idx, row in enumerate(table_el.find_all('tr')):
        c_idx = 0
        for cell in row.find_all(['th', 'td']):
            while (r_idx, c_idx) in occupied:
                c_idx += 1
            if c_idx >= n_cols:
                break
            try:
                cs = max(1, int(cell.get('colspan', 1)))
                rs = max(1, int(cell.get('rowspan', 1)))
            except Exception:
                cs = rs = 1
            for dr in range(rs):
                for dc in range(cs):
                    occupied[(r_idx + dr, c_idx + dc)] = True
            w = _parse_len_px(cell.get('style',''), cell.get('width'), total_w_px, 'width')
            if w:
                each = int(w / cs)
                for i in range(cs):
                    if c_idx + i < n_cols and widths[c_idx + i] is None:
                        widths[c_idx + i] = each
            c_idx += cs
    # 指定されなかった列がある場合、残り幅を等分
    if any(w is None for w in widths):
        specified = sum(w for w in widths if w)
        unspec = [i for i,w in enumerate(widths) if w is None]
        if unspec:
            remain = max(0, total_w_px - specified)
            avg = remain // len(unspec) if len(unspec) else 0
            for i in unspec: widths[i] = max(24, avg)
    return widths if any(widths) else None

_FLD_SEQ = {}  # スライドごとのページ番号フィールドの通し番号


def make_slidenum_field(paragraph):
    """段落の中身をPowerPointの「スライド番号」フィールドに差し替える。
    PowerPointが描画時に採番するので、スライドを挿入・並べ替え・削除しても番号が自動で直る
    （2026-09-08追加。以前は数字を文字として焼き込んでいたため、PowerPoint側で1枚挿すと
    以降の番号が全部ずれ、手で振り直す必要があった）。
    事後条件: 段落内の run は fld 1個に置き換わる。書式（rPr）は元の run から引き継ぐ。"""
    import uuid
    from pptx.oxml.ns import qn
    p = paragraph._p
    runs = p.findall(qn('a:r'))
    if not runs:
        return False
    first = runs[0]
    rPr = first.find(qn('a:rPr'))
    txt = first.find(qn('a:t'))
    shown = txt.text if txt is not None else '1'
    # id はスライド番号と通し番号から決める（同じHTMLからは同じPPTXが出る。uuid4 だと変換のたびに変わり、
    # 出力の一致を見る回帰テストが全部落ちていた・2026-10-14）
    _FLD_SEQ[CUR_SLIDE] = _FLD_SEQ.get(CUR_SLIDE, 0) + 1
    fid = uuid.uuid5(uuid.NAMESPACE_URL, 'slidekit/slidenum/%d/%d' % (CUR_SLIDE, _FLD_SEQ[CUR_SLIDE]))
    fld = p.makeelement(qn('a:fld'), {'id': '{%s}' % str(fid).upper(), 'type': 'slidenum'})
    if rPr is not None:
        fld.append(copy.deepcopy(rPr))       # 色・サイズ・フォントを保つ
    t = p.makeelement(qn('a:t'), {})
    t.text = shown                            # 表示用の初期値（PowerPointが開いた時に採番し直す）
    fld.append(t)
    first.addprevious(fld)
    for r in runs:                            # 元の run は全部消す（fldだけ残す）
        p.remove(r)
    return True
def _parse_padding_px(style):
    """CSSの padding を (上下, 左右) の px で返す。指定が無ければ (None, None)。
    対応: padding:A / padding:A B / padding:A B C / padding:A B C D（CSSの並び順は上右下左）。
    PPTXのセル余白（margin_top等）に写すために使う。"""
    m = re.search(r'(?<![\w-])padding\s*:\s*([^;"\']+)', style or '')
    if not m:
        return (None, None)
    vals = []
    for tok in m.group(1).split():
        mm = re.match(r'(\d+(?:\.\d+)?)\s*px$', tok)
        if mm is None:
            return (None, None)          # px以外（%やauto）は扱わない
        vals.append(float(mm.group(1)))
    if not vals:
        return (None, None)
    if len(vals) == 1:
        return (vals[0], vals[0])
    if len(vals) == 2:
        return (vals[0], vals[1])
    return (vals[0], vals[1])            # 3〜4指定は上・右を代表値にする
def _parse_row_heights(table_el, rows_html):
    """行高を px リストで返す。見つからない要素は None。
    優先: <tr style="height:Npx"> → <tr height=N> → 最初のセルのstyle height。"""
    heights = []
    for tr in rows_html:
        h = _parse_len_px(tr.get('style',''), tr.get('height'), None, 'height')
        if h is None:
            c = tr.find(['th','td'])
            if c is not None:
                h = _parse_len_px(c.get('style',''), c.get('height'), None, 'height')
        heights.append(h)
    return heights

def add_table(slide, table_el):
    x = int(table_el.get('data-x', 64))
    y = int(table_el.get('data-y', 130))
    tbl_style = table_el.get('style') or ''
    _fs_m = re.search(r'font-size\s*:\s*(\d+)px', tbl_style)
    table_font_px = int(_fs_m.group(1)) if _fs_m else 17
    # 本文セルの既定の文字色（2026-11-15）: ブラウザと同じく table → 親（.slide まで）の style の color を受け継ぐ。
    #   🚫 以前は table の color:#121212（カタログの表の書き方）を見ずに固定の #333333 で書き、HTML と PPTX で色がずれていた
    table_color = None
    for _anc in [table_el] + list(getattr(table_el, 'parents', [])):
        _st = _anc.get('style') if hasattr(_anc, 'get') else None
        _cm = re.search(r'(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b', _st or '')
        if _cm:
            table_color = _cm.group(1)
            break
        if 'slide' in ((_anc.get('class') or []) if hasattr(_anc, 'get') else []):
            break
    w = int(table_el.get('data-w', 1152))
    # data-h があればそれを使い、無ければ従来値(行数×32)
    dh = table_el.get('data-h')
    if dh:
        try:
            table_h = int(dh)
        except Exception:
            table_h = None
    else:
        table_h = None

    rows_html = table_el.find_all('tr')
    # colspan/rowspan を解釈しつつグリッド上に配置：占有マップ方式で列ズレを防ぐ
    # まず論理列数(n_cols)を実際の占有幅から算出
    occupied = {}   # (r,c) → 占有元セルの (r0,c0)
    grid = []       # rows[r] = [(cell, colspan, rowspan) or None]
    for r_idx, row in enumerate(rows_html):
        while len(grid) <= r_idx:
            grid.append([])
        row_arr = grid[r_idx]
        c_idx = 0
        for cell in row.find_all(['th', 'td']):
            # 既に上のrowspanで埋まっているカラムを飛ばす
            while (r_idx, c_idx) in occupied:
                c_idx += 1
            try:
                cs = max(1, int(cell.get('colspan', 1)))
                rs = max(1, int(cell.get('rowspan', 1)))
            except Exception:
                cs = rs = 1
            # 拡張
            while len(row_arr) <= c_idx:
                row_arr.append(None)
            row_arr[c_idx] = (cell, cs, rs)
            for dr in range(rs):
                for dc in range(cs):
                    occupied[(r_idx+dr, c_idx+dc)] = (r_idx, c_idx)
            c_idx += cs
    n_rows = len(rows_html)
    n_cols = 0
    for (r, c) in occupied:
        if c + 1 > n_cols:
            n_cols = c + 1
    n_cols = max(n_cols, 1)

    tbl_shape = slide.shapes.add_table(
        n_rows, n_cols,
        px_to_emu_x(x), px_to_emu_y(y),
        px_to_emu_x(w),
        px_to_emu_y(table_h if table_h else n_rows * 32)
    )
    tbl = tbl_shape.table
    # 🚨 python-pptx が付ける tblPr の firstRow="1" / bandRow="1" と tableStyleId
    # (Medium Style 2 - Accent 1) は PowerPoint 側で列幅を再配分することがある。
    # HTML の width 指定を厳密に守るため、これらを無効化する。
    try:
        from lxml import etree
        tbl_el = tbl_shape._element.graphic.graphicData.tbl
        tblPr = tbl_el.find(qn('a:tblPr'))
        if tblPr is not None:
            # firstRow / bandRow を無効化 (特殊行のスタイル継承を抑制 → 列幅を素直に効かせる)
            for attr in ('firstRow','bandRow','firstCol','bandCol','lastRow','lastCol'):
                if attr in tblPr.attrib:
                    tblPr.attrib.pop(attr)
            # スタイル (Medium Style 2 - Accent 1) を "No Style, No Grid" に差し替え
            style_el = tblPr.find(qn('a:tableStyleId'))
            if style_el is not None:
                style_el.text = '{2D5ABB26-0587-4C30-8999-92F81FD0307C}'
    except Exception as e:
        print(f'  WARN: tblPr sanitize failed: {e}')
    # 列幅 (HTML の width:Npx / width:N% を反映)。指定なしなら等分
    col_widths_px = _parse_col_widths(table_el, n_cols, w)
    if col_widths_px:
        for i, cw in enumerate(col_widths_px):
            try:
                if i < len(tbl.columns) and cw and cw > 0:
                    tbl.columns[i].width = px_to_emu_x(cw)
            except Exception as e:
                print(f'  WARN: col{i} width set failed: {e}')
    # 行高 (HTML の <tr height> / style height を反映)。
    # 🚨未指定行にも「1行分の最小高さ」を明示する。add_table はテーブル全体高を
    # 全行に均等配分するため、未指定のままだと本文の長い表ほどヘッダー行が
    # 不自然に高くなる（2026-07-18実地で発生）。PowerPointの行高は最小値扱いで、
    # 中身が多い行は描画時に自動で伸びるので、小さめに入れておけば揃う。
    row_heights_px = _parse_row_heights(table_el, rows_html)
    # 行高の下限は「フォント1行＋セルの上下padding」で見積もる。padding を実際のHTMLから読むので、
    # padding:1px 2px のような詰めた表は詰めたまま変換できる（2026-09-08。以前は+10px固定で、
    # 25行の週割り表がPPTXで下にはみ出した）
    _first_td = table_el.find('td')
    _pad_v0 = _parse_padding_px((_first_td.get('style') or '') if _first_td is not None else '')[0]
    _min_row_px = int(table_font_px * 1.4) + (_pad_v0 * 2 if _pad_v0 is not None else 10) + 2
    for i, rh in enumerate(row_heights_px):
        try:
            if i < len(tbl.rows):
                tbl.rows[i].height = px_to_emu_y(rh if rh else _min_row_px)
        except Exception as e:
            print(f'  WARN: row{i} height set failed: {e}')

    def _pick_color_from_style(style):
        m = re.search(r'(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{3,8})', style or '')
        return m.group(1) if m else None

    # ---- セル枠線（style の border / border-top|right|bottom|left → a:lnL/lnR/lnT/lnB）----
    # テーブルスタイルは "No Style, No Grid" なので、CSSで線を書いたセル辺だけPPTXに線が出る
    # ＝ブラウザと同じ見た目。行区切りの border-bottom も、複数セルを同色で塗って外周だけ
    # 線を引く「疑似結合（大項目）」も、この仕組みで再現される。
    def _parse_css_border_value(v):
        """'1px solid #hex' → (幅px, '#hex') / 'none'・'0' → (0, None) / 解釈不能 → None"""
        v = (v or '').strip()
        if re.match(r'^(none|0)(\s|$)', v):
            return (0.0, None)
        m = re.match(r'^(\d+(?:\.\d+)?)px\s+\w+\s+(#[0-9a-fA-F]{3,8})', v)
        if m and _is_valid_hex(m.group(2)):
            return (float(m.group(1)), m.group(2))
        return None

    def _cell_borders_from_style(style):
        """セル style から {side: (幅px, 色)} を返す。shorthand の border を
        side別指定（border-top等）が上書きする（CSSと同じ優先順）。"""
        out = {}
        m = re.search(r'(?<![\w-])border\s*:\s*([^;]+)', style or '')
        if m:
            b = _parse_css_border_value(m.group(1))
            if b:
                out = {s: b for s in ('top', 'right', 'bottom', 'left')}
        for side in ('top', 'right', 'bottom', 'left'):
            m = re.search(r'border-' + side + r'\s*:\s*([^;]+)', style or '')
            if m:
                b = _parse_css_border_value(m.group(1))
                if b:
                    out[side] = b
        return out

    _LN_TAGS = {'left': 'a:lnL', 'right': 'a:lnR', 'top': 'a:lnT', 'bottom': 'a:lnB'}
    _LN_ORDER = ['a:lnL', 'a:lnR', 'a:lnT', 'a:lnB']  # CT_TableCellProperties のスキーマ順

    def _set_cell_border(tbl_cell, side, width_px, color):
        """1辺の線を tcPr に書く。color=None は noFill（線なしを明示）。
        🚨 tcPr の子要素順は lnL→lnR→lnT→lnB→…→fill。順序が崩れると修復ダイアログが出る。"""
        tag = _LN_TAGS[side]
        if color:
            w_emu = max(1, int(px_to_pt(width_px) * EMU_PER_PT))
            xml = ('<%s %s w="%d" cap="flat" cmpd="sng" algn="ctr">'
                   '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
                   '<a:prstDash val="solid"/></%s>'
                   % (tag, nsdecls('a'), w_emu, str(hex_to_rgb(color)), tag))
        else:
            xml = '<%s %s><a:noFill/></%s>' % (tag, nsdecls('a'), tag)
        try:
            ln = parse_xml(xml)
            tcPr = tbl_cell._tc.get_or_add_tcPr()
            old = tcPr.find(qn(tag))
            if old is not None:
                tcPr.remove(old)
            # スキーマ順で自分より前にある ln の直後、無ければ先頭（fillより前）に入れる
            pos = 0
            for t in _LN_ORDER:
                if t == tag:
                    break
                if tcPr.find(qn(t)) is not None:
                    pos = list(tcPr).index(tcPr.find(qn(t))) + 1
            tcPr.insert(pos, ln)
        except Exception as e:
            print(f'  WARN: セル枠線({side})設定失敗: {e}')

    def _pick_bg_from_style(style):
        m = re.search(r'background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8})', style or '')
        return m.group(1) if m else None
    def _is_bold_style(style):
        return bool(re.search(r'font-weight\s*:\s*(700|bold)', style or ''))
    def _pick_font_size_from_style(style):
        m = re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*px', style or '')
        return float(m.group(1)) if m else None
    def _pick_text_align_from_style(style):
        m = re.search(r'text-align\s*:\s*(left|center|right)', style or '')
        return m.group(1) if m else None
    def _pick_valign_from_style(style):
        m = re.search(r'vertical-align\s*:\s*(top|middle|bottom)', style or '')
        return m.group(1) if m else None

    for r_idx, row in enumerate(rows_html):
        for c_idx in range(n_cols):
            if (r_idx, c_idx) not in occupied:
                continue
            origin = occupied[(r_idx, c_idx)]
            if origin != (r_idx, c_idx):
                continue  # 拡張先セルはスキップ（後で merge 済み）
            cell, cs, rs = grid[r_idx][c_idx]
            # 行(<tr>)の style をセルのフォールバックにする（背景・文字色・太字・サイズ・揃え）。
            # ヘッダを <tr style="background:...;color:..."> で書くデッキが多く、セルstyleだけ
            # 読むとPPTXでヘッダの塗り・白文字が落ちてブラウザと見た目が揃わない（2026-07-26実地）
            rstyle = ''
            try:
                tr_parent = cell.find_parent('tr')
                rstyle = (tr_parent.get('style') or '') if tr_parent is not None else ''
            except Exception:
                pass
            tbl_cell = tbl.cell(r_idx, c_idx)
            # colspan/rowspan があれば結合
            if cs > 1 or rs > 1:
                try:
                    other = tbl.cell(r_idx + rs - 1, c_idx + cs - 1)
                    tbl_cell.merge(other)
                except Exception:
                    pass
            # セル内を run 単位で構築（<b>/<span>/<br> の書式を保つ）
            tbl_cell.text = ''
            _tf_cell = tbl_cell.text_frame
            _run_ovs = []   # (run, bold_ov, color_ov, fs_ov)
            _paras = []
            for _pi, _runs in enumerate(_cell_rich_paragraphs(cell)):
                _p = _tf_cell.paragraphs[0] if _pi == 0 else _tf_cell.add_paragraph()
                _paras.append(_p)
                for (_t, _b_ov, _c_ov, _fs_ov) in _runs:
                    _r = _p.add_run()
                    _r.text = _t
                    _run_ovs.append((_r, _b_ov, _c_ov, _fs_ov))
            p = _paras[0]
            cstyle = cell.get('style') or ''
            # 書式は段落(defRPr)とrunの両方に設定する。
            # PowerPointは既存runに段落既定色を適用しないため、p.fontだけだと
            # thの白文字がテーマ黒で描画され読めなくなる（2026-07-18実地で確認）
            _fonts = [f for _pp in _paras for f in ([_pp.font] + [r.font for r in _pp.runs])]
            def _set_all(attr_fn):
                for f in _fonts:
                    attr_fn(f)
            # フォントサイズ: セル style > 行(tr) style > テーブル既定
            cell_fs = _pick_font_size_from_style(cstyle) or _pick_font_size_from_style(rstyle) or table_font_px
            _set_all(lambda f: setattr(f, 'size', Pt(px_to_pt(cell_fs))))
            for f in _fonts:
                set_font_name(f, FONT_NAME)
            # text-align (セル > 行 > テーブル既定)
            ta = _pick_text_align_from_style(cstyle) or _pick_text_align_from_style(rstyle)
            if ta:
                for _pp in _paras:
                    _pp.alignment = get_align(ta)
            # vertical-align (top/middle/bottom → MSO_ANCHOR)
            va = _pick_valign_from_style(cstyle) or _pick_valign_from_style(rstyle)
            if va:
                try:
                    tbl_cell.vertical_anchor = {
                        'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM
                    }.get(va, MSO_ANCHOR.MIDDLE)
                except Exception: pass
            if cell.name == 'th':
                _set_all(lambda f: setattr(f, 'bold', True))
                # ヘッダは既定で白文字、style で color 指定があれば優先
                fg = _pick_color_from_style(cstyle) or _pick_color_from_style(rstyle)
                _th_rgb = hex_to_rgb(fg) if (fg and _is_valid_hex(fg)) else RGBColor(0xFF, 0xFF, 0xFF)
                for f in _fonts:
                    f.color.rgb = _th_rgb
                bg = _pick_bg_from_style(cstyle) or _pick_bg_from_style(rstyle) or '#1a365d'
                tbl_cell.fill.solid()
                tbl_cell.fill.fore_color.rgb = hex_to_rgb(bg)
            else:
                fg = _pick_color_from_style(cstyle) or _pick_color_from_style(rstyle) or table_color
                _td_rgb = hex_to_rgb(fg) if (fg and _is_valid_hex(fg)) else RGBColor(0x33, 0x33, 0x33)
                for f in _fonts:
                    f.color.rgb = _td_rgb
                if _is_bold_style(cstyle) or _is_bold_style(rstyle):
                    _set_all(lambda f: setattr(f, 'bold', True))
                # 明示的な背景色があれば優先、無ければ従来の縞模様
                bg = _pick_bg_from_style(cstyle) or _pick_bg_from_style(rstyle)
                if bg and _is_valid_hex(bg):
                    tbl_cell.fill.solid()
                    tbl_cell.fill.fore_color.rgb = hex_to_rgb(bg)
                elif r_idx % 2 == 0 and r_idx > 0:
                    # 縞の薄灰はカタログ色 #fafafa（2026-11-15）。🚫 #f7fafc はカタログ外で、往復で B2 に掛かっていた
                    tbl_cell.fill.solid()
                    tbl_cell.fill.fore_color.rgb = hex_to_rgb('#fafafa')
            # run単位の書式上書き（<b>/<span>由来）は既定を全て当てた後に適用する
            for (_r, _b_ov, _c_ov, _fs_ov) in _run_ovs:
                if _b_ov is not None:
                    _r.font.bold = _b_ov
                if _fs_ov:
                    _r.font.size = Pt(px_to_pt(_fs_ov))
                if _c_ov and _is_valid_hex(_c_ov):
                    _r.font.color.rgb = hex_to_rgb(_c_ov)
            # セルの余白: HTMLの padding をPPTXのセル余白に写す（未指定はPowerPoint既定のまま）。
            # これが無いと既定余白（上下0.05in）で行が膨らみ、詰めた表が下にはみ出す（2026-09-08）
            _pad_v, _pad_h = _parse_padding_px(cstyle)
            if _pad_v is None and _pad_h is None:
                _pad_v, _pad_h = _parse_padding_px(rstyle)
            try:
                if _pad_v is not None:
                    tbl_cell.margin_top = Pt(px_to_pt(_pad_v))
                    tbl_cell.margin_bottom = Pt(px_to_pt(_pad_v))
                if _pad_h is not None:
                    tbl_cell.margin_left = Pt(px_to_pt(_pad_h))
                    tbl_cell.margin_right = Pt(px_to_pt(_pad_h))
            except Exception as e:
                print(f'  WARN: cell margin set failed: {e}')
            # セル枠線（fill設定の後に呼ぶが、挿入位置はスキーマ順を守る）
            for side, (bw, bc) in _cell_borders_from_style(cstyle).items():
                _set_cell_border(tbl_cell, side, bw, bc)

def _object_position(style):
    """object-position を (横 'left|center|right', 縦 'top|center|bottom') にする。
    キーワードは順不同（'top' 1語＝縦だけ）。% は 0%=左/上・100%=右/下・それ以外=中央。"""
    op_h, op_v = 'center', 'center'
    m = re.search(r'object-position\s*:\s*([^;"]+)', style or '')
    if not m:
        return op_h, op_v
    toks = m.group(1).strip().lower().split()
    pct = []
    for t in toks:
        if t in ('left', 'right'):
            op_h = t
        elif t in ('top', 'bottom'):
            op_v = t
        elif t.endswith('%'):
            pct.append(t)
    for i, t in enumerate(pct[:2]):
        try:
            v = float(t[:-1])
        except ValueError:
            continue
        side = ('left', 'right') if i == 0 else ('top', 'bottom')
        val = side[0] if v <= 0 else (side[1] if v >= 100 else 'center')
        if i == 0:
            op_h = val
        else:
            op_v = val
    return op_h, op_v


def add_image(slide, img_el, parent_style):
    # data属性優先→無ければ style から拾う（ブラウザ再保存で "left: 74px" のようにスペースが入るためregexは \s* を許容）
    def _p(attr, prop):
        v = img_el.parent.get(attr) if img_el.parent else None
        if v is not None:
            try: return int(float(v))
            except: pass
        m = re.search(prop + r'\s*:\s*(\d+)px', parent_style, re.IGNORECASE)
        return int(m.group(1)) if m else None
    x = _p('data-x', 'left')
    y = _p('data-y', 'top')
    w = _p('data-w', 'width')
    h = _p('data-h', 'height')
    left_match = top_match = width_match = height_match = True  # 後段の分岐互換
    if x is None or y is None or w is None or h is None:
        return
    
    src = img_el.get('src', '')
    # data URL(base64画像・ブラウザで⌘Vペースト/ドロップ時)を一時ファイルに書き出す
    _tmp_img_path = None
    if src.startswith('data:'):
        m = re.match(r'data:image/([a-zA-Z0-9+.\-]+);base64,(.+)$', src, re.DOTALL)
        if not m:
            print(f'  WARN: 不正な data URL をスキップ: {src[:40]}...')
            return
        ext = m.group(1).lower()
        if ext == 'jpeg': ext = 'jpg'
        if ext == 'svg+xml': ext = 'svg'
        if ext not in ('png', 'jpg', 'gif', 'bmp', 'tiff', 'tif'):
            print(f'  WARN: PPTX非対応の画像形式(data URL: {ext})をスキップ')
            return
        try:
            fd, _tmp_img_path = tempfile.mkstemp(suffix='.' + ext)
            with os.fdopen(fd, 'wb') as f:
                f.write(base64.b64decode(m.group(2)))
            img_path = _tmp_img_path
        except Exception as e:
            print(f'  WARN: data URL のデコードに失敗: {e}')
            return
    else:
        # %20 等のURLエンコードと ?v=2 / #frag を外して実ファイルを探す（ブラウザは同じファイルを表示している）
        img_path = os.path.join(BASE_DIR, unquote(src.split('#', 1)[0].split('?', 1)[0]))
        _miss = None
        if re.match(r'^https?://', src):
            _miss = 'ネット上の画像は埋め込めない（ダウンロードして相対パスにする）'
        elif img_path.lower().endswith(('.svg', '.heic', '.heif', '.avif')):
            _miss = 'PPTXが扱えない画像形式（PNG/JPGに変換する）'
        elif not img_path.lower().endswith('.webp') and not os.path.exists(img_path):
            _miss = '画像ファイルが見つからない'
        if _miss:
            # 2026-09-27: 以前は黙って消え、PPTXが「完成品」の名前で出ていた。SVG・動画と同じく欠落として扱う
            MISSING_ASSETS.append((CUR_SLIDE, 'image', x, y, w, h, f'{_miss}: {src}'))
            print(f'  🚨 MISSING: S{CUR_SLIDE} IMAGE at ({x},{y}) — {_miss}: {src}')
            return
    
    # webp → jpg 変換（python-pptx は webp 非対応）
    # 1) 事前変換済み jpg があればそれを使う 2) Pillow あればその場でPNGに変換 3) 無ければWARNしてスキップ
    _tmp_webp_conv = None
    if img_path.lower().endswith('.webp'):
        base, _ = os.path.splitext(img_path)
        jpg_path = base + '.jpg'
        if os.path.exists(jpg_path):
            img_path = jpg_path
        elif HAS_PIL:
            try:
                fd, _tmp_webp_conv = tempfile.mkstemp(suffix='.png')
                os.close(fd)
                with _PILImage.open(img_path) as im:
                    im.save(_tmp_webp_conv, 'PNG')
                img_path = _tmp_webp_conv
                print(f'  INFO: webpを一時PNGに変換: {src}')
            except Exception as e:
                print(f'  WARN: webp→PNG変換失敗({e})、スキップ: {src}')
                if _tmp_webp_conv and os.path.exists(_tmp_webp_conv):
                    try: os.remove(_tmp_webp_conv)
                    except: pass
                return
        else:
            print(f'  WARN: webp画像({src})の事前変換jpg無し・Pillow未導入 → スキップ')
            return
    
    if os.path.exists(img_path):
        # object-fit を取得
        img_style = (img_el.get('style') or '').replace(' ', '')
        is_cover = 'object-fit:cover' in img_style
        is_contain = 'object-fit:contain' in img_style

        # SlideKit UIの手動クロップ(data-crop-*)がある場合は「切り出し領域が枠いっぱいに表示」の
        # 意味論なので、contain の内側配置調整はせず枠そのものを表示エリアにする
        has_manual_crop = any(img_el.get('data-crop-' + k) for k in ('l', 'r', 't', 'b'))

        # contain の場合はコンテナ内にアス比保持で内側配置するよう x,y,w,h を差し替え
        # (return せず共通の add_picture ブロックに合流 → border など後続処理も走る)
        if is_contain and not has_manual_crop:
            size = _get_image_size(img_path)
            if size:
                iw, ih = size
                img_aspect = iw / ih
                container_aspect = w / h
                if img_aspect > container_aspect:
                    new_w = w; new_h = round(w / img_aspect)
                    new_x = x; new_y = y + (h - new_h) // 2
                else:
                    new_h = h; new_w = round(h * img_aspect)
                    new_y = y; new_x = x + (w - new_w) // 2
                x, y, w, h = new_x, new_y, new_w, new_h

        # width:100%;height:auto（幅に合わせて縦は成り行き）＝ブラウザは上から描き、枠を超えた下は切れる。
        # 2026-09-27: 以前は枠いっぱいに引き伸ばしていた（縦横比が崩れる）
        _wfit_crop_b = None
        if (not is_cover and not is_contain and not has_manual_crop
                and 'width:100%' in img_style and 'height:auto' in img_style):
            size = _get_image_size(img_path)
            if size and size[0]:
                nat_h = w * size[1] / size[0]
                if nat_h <= h:
                    h = max(1, round(nat_h))
                else:
                    _wfit_crop_b = 1 - h / nat_h

        try:
            pic = slide.shapes.add_picture(
                img_path,
                px_to_emu_x(x), px_to_emu_y(y),
                px_to_emu_x(w), px_to_emu_y(h)
            )
        except Exception as e:
            MISSING_ASSETS.append((CUR_SLIDE, 'image', x, y, w, h, f'画像を埋め込めない({e}): {src}'))
            print(f'  🚨 MISSING: S{CUR_SLIDE} IMAGE 埋め込み失敗 — {src}: {e}')
            return
        if _wfit_crop_b:
            pic.crop_bottom = _wfit_crop_b
        _apply_rotation(pic, img_el.parent, img_el)  # 回転・反転・リンクはラッパーdiv側が持つ（無ければimg自身）
        _apply_flip(pic, img_el.parent, img_el)
        _register_link(pic, img_el.parent, img_el)
        # 代替テキスト（img の alt 等）。読み上げ・アクセシビリティチェック用（2026-10-14）
        if not _SEM.set_alt_text(pic, _SEM.alt_of_image(img_el)):
            ALT_MISSING.append((CUR_SLIDE, '画像', src[:60]))
        # (1) data-crop-* があれば手動クロップとして最優先で反映（SlideKitのUIトリミング）
        def _pf(v):
            try:
                f = float(v or 0)
                return max(0.0, min(0.9, f))
            except Exception:
                return 0.0
        cl = _pf(img_el.get('data-crop-l'))
        cr = _pf(img_el.get('data-crop-r'))
        ct = _pf(img_el.get('data-crop-t'))
        cb = _pf(img_el.get('data-crop-b'))
        manual_crop = cl or cr or ct or cb
        if manual_crop:
            try:
                if cl: pic.crop_left = cl
                if cr: pic.crop_right = cr
                if ct: pic.crop_top = ct
                if cb: pic.crop_bottom = cb
            except Exception as e:
                print(f'  WARN: manual crop failed for {src}: {e}')
        # (2) object-fit:cover の場合、画像をコンテナ枠でトリミング（中央寄せ）
        # → ブラウザの object-fit:cover と同じ振る舞いを PPTX の crop で再現
        elif is_cover:
            try:
                size = _get_image_size(img_path)
                if size:
                    iw, ih = size
                    img_aspect = iw / ih
                    container_aspect = w / h
                    # object-position も読み取り（デフォルト center center）
                    op_h = 'center'
                    op_v = 'center'
                    # 空白を詰める前の style から読む（詰めると "left top" が "lefttop" になり効かなかった・2026-09-27）
                    op_h, op_v = _object_position(img_el.get('style') or '')
                    # 画像がコンテナより横長 → 左右トリミング
                    if img_aspect > container_aspect:
                        visible_ratio = container_aspect / img_aspect
                        total_crop = 1 - visible_ratio
                        if op_h == 'left':
                            cl, cr = 0, total_crop
                        elif op_h == 'right':
                            cl, cr = total_crop, 0
                        else:
                            cl = cr = total_crop / 2
                        # python-pptx の crop_* は -1.0〜1.0 の小数
                        pic.crop_left = cl
                        pic.crop_right = cr
                    elif img_aspect < container_aspect:
                        # 画像がコンテナより縦長 → 上下トリミング
                        visible_ratio = img_aspect / container_aspect
                        total_crop = 1 - visible_ratio
                        if op_v == 'top':
                            ct, cb = 0, total_crop
                        elif op_v == 'bottom':
                            ct, cb = total_crop, 0
                        else:
                            ct = cb = total_crop / 2
                        pic.crop_top = ct
                        pic.crop_bottom = cb
            except Exception as e:
                print(f'  WARN: crop calc failed for {src}: {e}')

    # 親div の data-border="w,#hex" を pic の枠線に反映（薄い灰の細線など）
    # picture shape の枠線は python-pptx の高レベルAPIでは信頼できず、XMLを直接書く方が確実
    parent = img_el.parent
    bd = parent.get('data-border') if parent else None
    if not bd and parent:
        m_bd = re.search(r'border\s*:\s*(\d+)px\s+solid\s+(#[0-9a-fA-F]{3,8})', parent.get('style', '') or '')
        if m_bd:
            bd = f"{m_bd.group(1)},{m_bd.group(2)}"
    if bd:
        try:
            from lxml import etree
            bw_str, bc = bd.split(',', 1)
            bw_px = float(bw_str.strip())
            bc = bc.strip().lstrip('#').upper()
            emu = int(bw_px * 9525)  # 1px = 9525 EMU（PPTX標準）
            sp_pr = pic._element.spPr
            # 既存の ln 要素を削除
            for old in sp_pr.findall(qn('a:ln')):
                sp_pr.remove(old)
            # ln 要素を子供付きで作る
            ln = etree.Element(qn('a:ln'))
            ln.set('w', str(emu))
            ln.set('cap', 'flat')
            ln.set('cmpd', 'sng')
            ln.set('algn', 'ctr')
            solid = etree.SubElement(ln, qn('a:solidFill'))
            srgb = etree.SubElement(solid, qn('a:srgbClr'))
            srgb.set('val', bc)
            # OOXML仕様: a:spPr の子要素順は xfrm→prstGeom→(fill)→ln→effectLst...
            # ln を fill の直後に挿入する（順序違反はPowerPoint修復対象になる）
            fill_tags = {qn('a:noFill'), qn('a:solidFill'), qn('a:gradFill'),
                         qn('a:blipFill'), qn('a:pattFill'), qn('a:grpFill')}
            inserted = False
            for i, child in enumerate(list(sp_pr)):
                if child.tag in fill_tags:
                    sp_pr.insert(i + 1, ln)
                    inserted = True
                    break
            if not inserted:
                # fillが無い場合は prstGeom / custGeom の直後
                for i, child in enumerate(list(sp_pr)):
                    if child.tag in (qn('a:prstGeom'), qn('a:custGeom')):
                        sp_pr.insert(i + 1, ln)
                        inserted = True
                        break
            if not inserted:
                sp_pr.append(ln)  # fallback
        except Exception as e:
            print(f'  WARN: image border XML write failed: {e}')

    # data URL / webp変換 で作った一時ファイルを削除
    for _p in (_tmp_img_path, _tmp_webp_conv):
        if _p and os.path.exists(_p):
            try:
                os.remove(_p)
            except Exception:
                pass


# AWSテンプレート表紙用の色リマップ表: 暗色前提の明るい文字 → AWS光彩背景で読める暗い色
# 正本は slidekit-aws.js プラグイン (formats.aws.coverRemap / 9色)。
# プラグイン無しなら get_aws_cover_remap() が {} を返す＝リマップなし。
def _remap_cover_colors_for_aws(slide_div):
    """AWSテンプレート表紙で、暗色前提の明るい色を暗い色にリマップする（PPTX側のみ）。"""
    import re as _re
    _remap = get_aws_cover_remap()  # キー・値とも小文字正規化済み
    def _rgb_from_hex(h):
        h = h.lstrip('#')
        if len(h) == 3: h = ''.join(c*2 for c in h)
        try:
            return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        except Exception:
            return None
    # data-color を書き換え + style="color:..." も同期
    for el in slide_div.find_all(True):
        dc = el.get('data-color')
        if dc:
            key = dc.lower()
            new = _remap.get(key)
            if new:
                el['data-color'] = new
                st = el.get('style') or ''
                # hex 表記
                st = _re.sub(_re.escape(dc)+r'(?![0-9a-fA-F])', new, st, flags=_re.IGNORECASE)
                # rgb() 表記
                rgb_old = _rgb_from_hex(key)
                rgb_new = _rgb_from_hex(new)
                if rgb_old and rgb_new:
                    r,g,b = rgb_old; nr,ng,nb = rgb_new
                    st = _re.sub(rf'rgb\(\s*{r}\s*,\s*{g}\s*,\s*{b}\s*\)', f'rgb({nr}, {ng}, {nb})', st, flags=_re.IGNORECASE)
                el['style'] = st

def _rect_inner_images(slide, rect_el):
    """.rect/.flow の中の画像と、PPTXに出ない中身を扱う。
    直下の <img> は枠と同じ位置に画像として置く（2026-09-27: 以前は黙って消えていた。C-14ヒアリング資料等9件）。
    それより深い img・表・入れ子の枠・孫の文字枠はPPTXに出ないので、黙らずWARNを出す。"""
    for img in rect_el.find_all('img', recursive=False):
        add_image(slide, img, rect_el.get('style', ''))
    lost = []
    if any(im.parent is not rect_el for im in rect_el.find_all('img')):
        lost.append('入れ子の画像')
    if rect_el.find('table'):
        lost.append('表')
    if rect_el.find('div', class_='rect'):
        lost.append('入れ子の枠(.rect)')
    if any(tb.parent is not rect_el for tb in rect_el.find_all('div', class_='tb')):
        lost.append('孫の文字枠(.tb)')
    if lost:
        print(f'  WARN: S{CUR_SLIDE} 枠({rect_el.get("data-x")},{rect_el.get("data-y")})の中の'
              f'{"・".join(lost)}はPPTXに出ない。枠の外に同じ座標で置く')


def process_slide(prs, slide_div, slide_no=0):
    global CUR_SLIDE
    CUR_SLIDE = slide_no
    # スライドの背景暗さでレイアウトを選ぶ
    # - 暗い背景(グラデ or 輝度<0.5) = 表紙/セクション表紙 → Cover-Gradient系(白ロゴが載る)
    # - それ以外 = コンテンツ → Blank(暗ロゴ)
    grad = slide_div.get('data-bg-gradient')
    bg_solid = slide_div.get('data-bg')
    def _bg_is_dark(hx):
        if not hx or not re.match(r'^#[0-9a-fA-F]{3,8}$', hx):
            return False
        h = hx.lstrip('#')
        if len(h) == 3: h = ''.join(c*2 for c in h)
        try:
            r = int(h[0:2],16); g = int(h[2:4],16); b = int(h[4:6],16)
        except Exception:
            return False
        return (0.299*r + 0.587*g + 0.114*b) / 255 < 0.5
    is_dark = bool(grad) or _bg_is_dark(bg_solid)
    chosen_layout = None
    # 個別スライドの意向: data-aws-logo="off" ならセクション表紙相当 (AWSロゴを持たないレイアウト) にする
    logo_off = (slide_div.get('data-aws-logo') == 'off')
    if is_dark:
        if logo_off:
            # 中表紙: Section-Divider (光彩背景あり・大きな AWS ロゴなし)
            for l in prs.slide_layouts:
                if 'section-divider' in l.name.lower() or 'divider' in l.name.lower():
                    chosen_layout = l
                    break
        if chosen_layout is None:
            # 表紙: Cover-Gradient
            for l in prs.slide_layouts:
                if 'cover' in l.name.lower():
                    chosen_layout = l
                    break
        if chosen_layout is None:
            for l in prs.slide_layouts:
                if 'section-divider' in l.name.lower() or 'divider' in l.name.lower():
                    chosen_layout = l
                    break
    if chosen_layout is None:
        for l in prs.slide_layouts:
            if l.name.lower().strip() in ('blank', '白紙'):
                chosen_layout = l
                break
    if chosen_layout is None:
        chosen_layout = min(prs.slide_layouts, key=lambda l: len(l.placeholders))
    slide = prs.slides.add_slide(chosen_layout)
    # 固定ID（data-sid）→ 生成スライドの対応を控える（ページジャンプリンクの解決用）
    _sid = slide_div.get('data-sid')
    if _sid:
        if _sid in _SID_TO_SLIDE:
            print(f'  WARN: data-sid="{_sid}" が重複（slide{slide_no}）→ 先勝ちでリンク解決')
        else:
            _SID_TO_SLIDE[_sid] = slide
    # レイアウトから継承された placeholder(タイトル/コンテンツ枠等)を削除
    # → HTMLで作った要素だけがPPTXに残る
    for ph in list(slide.placeholders):
        try:
            sp = ph._element
            sp.getparent().remove(sp)
        except Exception:
            pass
    # spTree の grpSpPr の xfrm を完全な形に補正
    # → python-pptx は cx=0/cy=0 の空 xfrm を作るので上書きが必要
    # → 抜けていたり 0 のままだと PowerPoint が「修復済み」ダイアログを出す
    try:
        from lxml import etree
        sld_el = slide._element
        grpSpPr = sld_el.find('.//' + qn('p:grpSpPr'))
        if grpSpPr is not None:
            # 既存の xfrm を全部削除して作り直す
            for old in grpSpPr.findall(qn('a:xfrm')):
                grpSpPr.remove(old)
            xfrm = etree.SubElement(grpSpPr, qn('a:xfrm'))
            off = etree.SubElement(xfrm, qn('a:off'))
            off.set('x', '0'); off.set('y', '0')
            ext = etree.SubElement(xfrm, qn('a:ext'))
            ext.set('cx', str(SLIDE_W_EMU)); ext.set('cy', str(SLIDE_H_EMU))
            chOff = etree.SubElement(xfrm, qn('a:chOff'))
            chOff.set('x', '0'); chOff.set('y', '0')
            chExt = etree.SubElement(xfrm, qn('a:chExt'))
            chExt.set('cx', str(SLIDE_W_EMU)); chExt.set('cy', str(SLIDE_H_EMU))
        # 暗色スライド(表紙・セクション表紙)はスライドマスターの下部暗ロゴを非表示に
        # 既存の showMasterSp 属性は一旦削除してから is_dark 判定で正しくセット
        if 'showMasterSp' in sld_el.attrib:
            del sld_el.attrib['showMasterSp']
        if is_dark:
            if USE_AWS_TEMPLATE:
                # AWSテンプレートの Cover-Gradient レイアウトは薄い光彩背景＋AWSロゴを既に持つ。
                # マスター表示は残し (showMasterSp なし=デフォルトで表示)、
                # 白ロゴの追加もしない。明色前提の文字色を暗色にリマップして薄い背景でも読めるようにする。
                _remap_cover_colors_for_aws(slide_div)
            else:
                sld_el.set('showMasterSp', '0')
                # 暗色スライドには白ロゴを直接配置（テンプレ Cover-Gradient の Graphic 3 が空blip）
                # 🚫 以前は宣言を見ずに置いていたため、授業デッキの表紙にもAWSロゴが入っていた（2026-09-27）
                if AWS_DECK:
                    _add_white_aws_logo_to_slide(slide)
    except Exception as e:
        print(f'  WARN: grpSpPr xfrm補正失敗: {e}')

    # Background
    bg_gradient = slide_div.get('data-bg-gradient')
    bg_solid = slide_div.get('data-bg')
    
    if bg_gradient:
        # AWSテンプレート表紙ではレイアウトの光彩背景を優先する（暗色グラデを重ねると
        # AWSロゴが埋もれる）。ブラウザは HTML の暗色グラデを表示するが、PPTX は AWS 表紙
        # デザインに従う。文字は下記でコントラスト調整される。
        if not (USE_AWS_TEMPLATE and is_dark):
            # 1枚のグラデ指定ミスで変換全体を止めない（WARN出して背景無しで続行）
            try:
                angle, c1, c2 = parse_gradient(bg_gradient)
                set_gradient(slide, angle, c1, c2)
            except Exception as e:
                print(f'  WARN: slide{slide_no} グラデ設定失敗({e}) → 背景なしで続行')
    elif bg_solid and bg_solid != '#ffffff' and not (USE_AWS_TEMPLATE and is_dark):
        # 暗い単色の扉（P03 など）も、AWSテンプレートではグラデと同じくレイアウトの光彩背景に従う。
        # 🚫 以前は単色だけ塗っていたため、文字は暗色にリマップされるのに背景は紺のままで
        #    「紺地に紺の文字」になった（2026-10-06 分科会4の中表紙）。ブラウザ側は光彩背景＋暗色文字
        try:
            bg = slide.background
            fill = bg.fill
            fill.solid()
            fill.fore_color.rgb = hex_to_rgb(bg_solid)
        except Exception as e:
            print(f'  WARN: slide{slide_no} 単色背景設定失敗({e}) → 背景なしで続行')
    
    # Process direct children
    has_pageno = False
    # --semantic: 見出しの .tb をタイトルのプレースホルダーにする（アウトライン・読み上げ・AIがスライド名を読める）
    title_el = _SEM.pick_title_tb(slide_div, is_dark) if SEMANTIC else None
    for child in slide_div.children:
        if not hasattr(child, 'get'):
            continue
        
        classes = child.get('class', [])

        # スライド直下にむき出しで置いたSVGは位置を持たないのでPPTXに出ない。黙って消さずに知らせる
        # 🚫 第22回の4コマ漫画が、4コマとも絵ごと消えていた（台詞の文字だけ残った・2026-10-14）
        if child.name == 'svg':
            MISSING_ASSETS.append((CUR_SLIDE, 'svg', '?', '?', '?', '?',
                                   'SVGが div（data-x/y/w/h）で包まれていない。包めば図形として出る'))
            print(f'  🚨 S{slide_no} SVGが div で包まれていないので、PPTXに出ない（data-x/y/w/h の div に入れる）')
            continue

        # グラフ（data-chart）はネイティブグラフにする。中のSVGはブラウザ表示用なので画像にしない
        #   サンキーは PowerPoint に同じグラフが無いので、ブラウザで描いた図を図形（帯・箱）と文字枠にする（下の SVG の経路）
        if child.get('data-chart') is not None and not _is_sankey(child):
            add_native_chart(slide, child)
            continue
        if child.get('data-chart') is not None and not (MEASURED and (MEASURED['els'].get(child.get('data-mid') or '') or {}).get('svgShapes')):
            print(f'  🚨 S{slide_no} サンキー・地図を図形にできなかった（ブラウザで測れない）。Chrome と maps/ の地図データがあるか確かめる')
            MISSING_ASSETS.append((slide_no, 'chart', child.get('data-x'), child.get('data-y'),
                                   child.get('data-w'), child.get('data-h'), 'サンキー・地図を測れない'))
            continue

        # --measured: 型に乗っていない自由配置の div（従来は丸ごと消えていた）を見えている通りに置く
        _mr = MEASURED['els'].get(child.get('data-mid') or '') if (MEASURED and MEASURE_FULL) else None
        if _mr and _mr.get('free'):
            _add_free_layout(slide, _mr['free'])
            print(f'  INFO: S{slide_no} 型に乗っていない配置を実測で置いた: 「{_mr.get("lost", "")[:24]}」')
            continue

        # 2026-11-19: SVG を包んだ div に data-x/y/w/h が無いと、どの経路にも乗らず黙って消えていた
        #   （むき出しの <svg> は上で知らせるが、「包んであるのに位置が無い」は素通りだった。
        #    図解・アイコン・グラフの3つとも PPTX から消え、エラーも出なかった）
        if (child.name == 'div' and child.get('data-x') is None and child.get('data-chart') is None
                and not ({'tb', 'rect', 'flow'} & set(classes)) and child.find('svg') is not None):
            _lab = (child.find('svg').get('aria-label') or '')[:24]
            _st = child.get('style') or ''
            _pos = {k: re.search(r'(?:^|;)\s*' + k + r'\s*:\s*(-?[\d.]+)px', _st) for k in ('left', 'top', 'width', 'height')}
            if all(_pos.values()):
                # style に px の位置があれば、それを data-x/y/w/h として読む（見えている位置のまま図形にする）
                for _k, _a in (('left', 'data-x'), ('top', 'data-y'), ('width', 'data-w'), ('height', 'data-h')):
                    child[_a] = _pos[_k].group(1)
                print(f'  INFO: S{slide_no} SVGを包む div に data-x/y/w/h が無いので、style の位置で置いた「{_lab}」')
            else:
                MISSING_ASSETS.append((CUR_SLIDE, 'svg', '?', '?', '?', '?',
                                       'SVGを包む div に位置（data-x/y/w/h か style の left/top/width/height px）が無い'))
                print(f'  🚨 S{slide_no} SVGを包む div に位置が無いので、PPTXに出ない「{_lab}」'
                      f'（data-x/y/w/h を書く）')
                continue
        
        # ラッパー div が SVG を内包しているかを事前判定
        # (rect/flow 内に SVG が入っている場合、枠 + SVG の両方を描画する)
        has_svg = (hasattr(child, 'find') and child.get('data-x') is not None
                   and (child.find('svg') is not None or child.get('data-chart') is not None))   # サンキーは測った図形がある
        # 動画（動く図解）。SVGのSMILはPPTXで静止するので、動かしたい図はmp4で渡す
        has_video = (hasattr(child, 'find') and child.find('video') is not None
                     and child.get('data-x') is not None)

        # 画像を入れていない画像枠（.ins）はPPTXに何も出ない。黙って消さず知らせる
        # 🚫 以前は警告なしで消え、「📎ここに画像」の場所が空白のまま顧客に出ていた（2026-09-27）
        # 依頼の枠（data-ask＝イラスト・グラフ・写真をどう用意するかを書いた枠）は、
        # PPTXでも破線の枠と編集できる文字のまま残す（PowerPointで受け取った人も何が入るか分かる・2026-10-14）
        if 'ins' in classes and child.get('data-ask') and not child.find(['img', 'svg', 'video']):
            add_ask_zone(slide, child)
            ASK_LEFT.append((slide_no, child.get('data-ask')))
            continue
        if 'ins' in classes and not (hasattr(child, 'find') and child.find(['img', 'svg', 'video'])):
            _label = re.sub(r'\s+', ' ', child.get_text() or '').strip()[:30]
            print(f'  ⚠️ S{slide_no} 画像枠が空のまま（PPTXでは空白になる）: 「{_label}」 '
                  f'x={child.get("data-x")} y={child.get("data-y")}。画像を入れるか枠を消す')

        if 'tb' in classes:
            _is_pageno = False
            # スライド番号の判定：右下（スライドサイズ相対）にあって数字だけの.tb
            # 固定値(1180/660)だとA4縦(794×1123)で判定できないため相対化
            # 2026-10-14: 判定を広げた（下端の帯の右側・data-role="pageno"・「3 / 24」形式）。
            #   右下から少しでも外れた手書きの番号が、文字のままPPTXに残っていた（利用者「いつの間にか手書きに戻っている」）
            try:
                _tx = float(child.get('data-x', 0) or 0)
                _ty = float(child.get('data-y', 0) or 0)
                _text = re.sub(r'\s+', '', child.get_text() or '')
                _num = re.fullmatch(r'(?:p\.?|P\.?)?(\d{1,3})(?:/\d{1,3})?', _text)
                if _num and (child.get('data-role') == 'pageno' or
                             (_tx >= SLIDE_W_PX * 0.75 and _ty >= SLIDE_H_PX - 80)):
                    has_pageno = True
                    _is_pageno = True
                    if _text != _num.group(1):
                        print(f'  INFO: S{slide_no} ページ番号「{_text}」を自動番号にした（総枚数の表示は外す）')
            except Exception:
                pass
            _n_before = len(slide.shapes)
            add_textbox(slide, child)
            if child is title_el and len(slide.shapes) > _n_before:
                try:
                    _SEM.make_title_placeholder(slide.shapes[-1])
                except Exception as e:
                    print(f'  WARN: S{slide_no} タイトルにできなかった: {e}')
            # ページ番号はPowerPointの自動フィールド（スライド番号）にする。
            # 数字を文字で焼き込むと、他デッキと結合・並べ替えをしたときに番号がずれる（2026-10-14 利用者）
            if _is_pageno:
                try:
                    for _para in slide.shapes[-1].text_frame.paragraphs:
                        make_slidenum_field(_para)
                except Exception as e:
                    print(f'  WARN: S{CUR_SLIDE} ページ番号を自動フィールドにできなかった: {e}')
        elif 'rect' in classes:
            add_rect_shape(slide, child)
            # rect が SVG を内包していれば SVG を上に重ねて配置 (紙芝居の粗い絵など)
            if has_svg:
                add_svg(slide, child)
            elif has_video:
                add_movie_shape(slide, child)
            else:
                _rect_inner_images(slide, child)
        elif 'flow' in classes:
            add_rect_shape(slide, child, rounded=True)
            if has_svg:
                add_svg(slide, child)
            elif has_video:
                add_movie_shape(slide, child)
            else:
                _rect_inner_images(slide, child)
        elif child.name == 'table':
            add_table(slide, child)
        elif child.name == 'div':
            # SVG（ファネル等）はラッパーのdata-x/y/w/hでPNG配置→位置・サイズが画面と一致
            if has_svg:
                add_svg(slide, child)
            elif has_video:
                add_movie_shape(slide, child)
            else:
                img = child.find('img')
                if img:
                    add_image(slide, img, child.get('style', ''))

    # ページ番号が入っていなければ自動で右下に追加（SlideKitのrenumberPages相当）
    # PPTX変換ルール: <html data-pageno="off"> で自動ページ番号を抑止できる
    # （テンプレート側フッタが番号を持つ場合や、番号なし運用のデッキ用・2026-08-31追加）
    # スピーカーノート: <div class="slide" data-notes="..."> をPPTXのノートへ入れる。
    # 発表者ツールで読む前提なので改行はそのまま渡す（\n 区切り）
    notes = slide_div.get('data-notes') if hasattr(slide_div, 'get') else None
    if notes:
        try:
            slide.notes_slide.notes_text_frame.text = notes.replace('\\n', '\n')
        except Exception as e:
            print(f'  WARN: S{CUR_SLIDE} ノートを入れられなかった: {e}')

    if PAGENO_OFF:
        has_pageno = True
    if not has_pageno:
        try:
            # 位置はスライドサイズ相対（16:9=1205,680 / A4縦=719,1083 相当）
            txBox = slide.shapes.add_textbox(
                px_to_emu_x(SLIDE_W_PX - 75), px_to_emu_y(SLIDE_H_PX - 40),
                px_to_emu_x(60), px_to_emu_y(32)
            )
            tf = txBox.text_frame
            tf.word_wrap = False
            tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
            p = tf.paragraphs[0]
            p.text = str(slide_no)
            p.alignment = PP_ALIGN.RIGHT
            # 書式は段落とrunの両方に（run未設定だとテーマ既定の黒/別フォントで出る）
            _pn_px = 21.334 if SLIDE_W_PX >= 1280 else 14  # 16:9投影=21.334px(=16.0pt) / A4文書=14px
            for f in [p.font] + [r.font for r in p.runs]:
                f.size = Pt(px_to_pt(_pn_px))
                set_font_name(f, FONT_NAME)
                f.color.rgb = hex_to_rgb(_pageno_color(slide_div))
            make_slidenum_field(p)  # 文字でなく自動フィールドに（並べ替え・結合しても番号が直る）
        except Exception as e:
            print(f'  WARN: auto page number failed: {e}')

def _pageno_color(slide_div):
    """自動ページ番号の文字色。明るい地は #5e5e5e、暗い地（グラデ・暗い単色）は #d4dde7（#21537f で5.9:1）。
    旧 #718096 は #fafafa で 3.9:1・#183251 で 3.3:1 と WCAG AA(4.5:1) 不足だった（2026-10-14 利用者了承）。
    slide-edit.js の pagenoColor と同じ判定"""
    get = slide_div.get if hasattr(slide_div, 'get') else (lambda k, d=None: d)
    if get('data-bg-gradient'):
        return '#d4dde7'
    m = re.match(r'^#?([0-9a-fA-F]{6})$', (get('data-bg') or '').strip())
    if not m:
        return '#5e5e5e'
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(m.group(1)[k:k + 2], 16)) for k in (0, 2, 4))
    return '#d4dde7' if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.18 else '#5e5e5e'


def _run_slide_guard(html_path):
    """変換前に静的ガードを通す。fail級（フォント下限・許可外クラス・カタログ外hex）は
    変換を停止し、warn級（パターンID未宣言・キャンバス外座標等）は表示だけして続行する。
    検査本体は slide-guard.py が正本（check() は [('fail'|'warn', msg), ...] を返す）"""
    import importlib.util
    gpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slide-guard.py')
    try:
        spec = importlib.util.spec_from_file_location('slide_guard', gpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        probs = mod.check(html_path)
    except Exception as e:
        print(f'  WARN: slide-guard実行失敗({e})、静的ガードはスキップされます')
        return
    fails = 0
    for item in probs or []:
        lv, msg = item if isinstance(item, tuple) else ('fail', item)  # 旧API（文字列）はfail扱い
        print(f'{"🚨" if lv == "fail" else "⚠️ "} slide-guard: {msg}')
        if lv == 'fail':
            fails += 1
    if fails:
        print(f'🚨 slide-guard: 停止級の違反{fails}件のため変換を中止。修正して再実行してください')
        sys.exit(1)


def main():
    # 引数解析 (--allow-missing-assets フラグ対応)
    raw = sys.argv[1:]
    allow_missing = '--allow-missing-assets' in raw
    # 出力先は位置引数のほか -o / --out でも受ける
    # 🚫 以前は -o を出力ファイル名と解釈し、「-o」という名前のPPTXを作っていた（2026-09-27）
    args, out_opt, k = [], None, 0
    while k < len(raw):
        a = raw[k]
        if a in ('-o', '--out'):
            if k + 1 >= len(raw):
                print('ERROR: -o の後に出力ファイル名を書いてください'); sys.exit(1)
            out_opt = raw[k + 1]; k += 2; continue
        if a in ('--allow-missing-assets', '--measured', '--semantic', '--no-semantic'):
            k += 1; continue
        if a.startswith('-'):
            print(f'ERROR: 知らないオプションです: {a}（使えるのは -o / --allow-missing-assets / '
                  f'--measured / --no-semantic）'); sys.exit(1)
        args.append(a); k += 1
    if out_opt:
        args = args[:1] + [out_opt]
    if len(args) < 1:
        print("Usage: python3 html_to_pptx.py <slides.html> [output.pptx | -o output.pptx] [--allow-missing-assets]")
        print("  --allow-missing-assets  SVG欠落 (Chrome無し等) があっても通常の出力名で続行")
        print("                          (指定なしの場合は .incomplete.pptx にリネームして exit 2)")
        print("  --measured  （試作）ブラウザで測った位置・文字書式で変換し、型に乗らない配置も拾う")
        print("  --no-semantic  見出しのタイトル枠・テーマ色をやめる（既定はON・2026-10-14）")
        sys.exit(1)
    html_path = os.path.abspath(args[0])
    output_path = os.path.abspath(args[1]) if len(args) > 1 else os.path.splitext(html_path)[0] + '.pptx'
    global BASE_DIR, RAW_SVG_SOUP, SVG_OUT_DIR, FONT_NAME, MISSING_ASSETS, ALLOW_MISSING
    BASE_DIR = os.path.dirname(html_path)
    MISSING_ASSETS = []  # (slide_index, kind, x, y, w, h, reason) の列
    ALLOW_MISSING = allow_missing

    _run_slide_guard(html_path)

    with open(html_path, 'r', encoding='utf-8') as f:
        raw_html = f.read()
    raw_html = _inline_svg_images(raw_html)
    global MEASURED, SEMANTIC, MEASURE_FULL
    # 既定ON（2026-10-14 利用者がPowerPoint実機で確認＝見出しの位置・大きさは同じ／アウトラインにタイトルが並ぶ）。
    #   --semantic は旧指定として受けるだけ。やめるときは --no-semantic
    SEMANTIC = '--no-semantic' not in raw
    MEASURE_FULL = '--measured' in raw
    # SVGがあるデッキは必ず測る（文字を画像に焼き込まず文字枠に・図形をPowerPointの図形にするため）
    _svg_text = any('data-sk-chart="1"' not in s
                    for s in re.findall(r'<svg[\s\S]*?</svg>', raw_html.split('<body', 1)[-1], re.I))
    # サンキー（data-chart type:sankey）はブラウザで描いた図を図形と文字枠にするので、必ず測る
    _svg_text = _svg_text or bool(re.search(r'type(?:"|&quot;)\s*:\s*(?:"|&quot;)(?:sankey|map)\b', raw_html))
    if MEASURE_FULL or _svg_text:
        # ブラウザで実測する。要素の突き合わせ用に data-mid を振った HTML を以降の正として読む
        import measure_layout as _ML
        try:
            _tagged, _n = _ML.tag_html(raw_html)
            MEASURED = _ML.measure_tagged(html_path, _tagged)
            raw_html = _tagged
            _why = '--measured' if MEASURE_FULL else 'SVGを図形と文字枠にするため'
            print(f'実測: {len(MEASURED["slides"])}枚・{len(MEASURED["els"])}要素（{_why}）')
            _ovw = _overflow_warnings(MEASURED)
            if _ovw:
                print('  ⚠️ [F2] 文字が枠に入らない（実測）: ' + '、'.join(_ovw[:5])
                      + (f' ほか{len(_ovw) - 5}件' if len(_ovw) > 5 else '')
                      + '（ブラウザでは切れて見えず、PPTX では下へあふれる。枠を広げるか文を減らす。文字は縮めない）')
        except Exception as e:
            MEASURED = None
            print(f'⚠️ 実測できなかったため data 属性だけで変換します: {e}')
    soup = BeautifulSoup(raw_html, 'lxml')
    global CLASS_VALIGN
    CLASS_VALIGN = read_class_valign(raw_html)
    # bodyのfont-familyから先頭フォント名を拾い、編集可能テキストのフォントに使う
    # 優先順: (1) <body style="font-family:...">（SlideKitで切替した結果） (2) <style> body{font-family:...}
    first = None
    body_el = soup.find('body')
    if body_el and body_el.get('style'):
        # soupで属性を直接読む（regexだと 'Meiryo UI' のようなクォート付きフォント名で失敗する）
        m_inline = re.search(r'font-family\s*:\s*([^;]+)', body_el.get('style'), re.IGNORECASE)
        if m_inline:
            first = m_inline.group(1).split(',')[0].strip().strip('\'"')
    if not first:
        m = re.search(r'body\s*\{[^}]*font-family\s*:\s*([^;}]+)', raw_html, re.IGNORECASE)
        if m:
            first = m.group(1).split(',')[0].strip().strip('\'"')
    if first:
        FONT_NAME = first
        print(f"フォント: {FONT_NAME}（HTMLのbody font-familyから自動検出）")
    # SVG抽出用の soup（html.parserは属性の大文字小文字を保持=viewBox/linearGradient等が壊れない）
    # 対応関係を data-x/y/w/h の完全一致で照合するので、処理経路に依存せずズレが出ない
    try:
        RAW_SVG_SOUP = BeautifulSoup(raw_html, 'html.parser')
    except Exception as e:
        print(f'  WARN: SVG抽出用soup作成失敗({e})、単体SVG書き出しはスキップされます')
        RAW_SVG_SOUP = None
    SVG_OUT_DIR = os.path.splitext(output_path)[0] + '_svg'

    prs = Presentation()
    # AWSテンプレート対応: <html data-template="aws"> または <html data-aws-decoration="on"> があればテンプレートPPTXを使用
    # 検索順: (1)環境変数 SLIDEKIT_AWS_TEMPLATE → (2)スクリプトと同じディレクトリ → (3)従来の ../TS/
    html_el = soup.find('html')

    # ラフモード警告: <html data-draft="on"> は「まだ叩き台」の印。
    # ブラウザ表示だけの上書きなのでPPTXは通常フォントで出るが、確定前の変換は意図か確認を促す
    if html_el and html_el.get('data-draft') == 'on':
        print('⚠️ このデッキはラフモード（data-draft="on"）です。PPTXは通常フォントで出力されます。'
              '確定済みならSlideKitで「✍️ ラフ中」をOFFにして保存してから変換してください。')
    # ページサイズをHTMLから検出（<html data-page-size="a4-portrait"> 等）。既定は 16-9
    configure_page_size(html_el)
    if MEASURED and MEASURE_FULL:
        # 位置・大きさは見えている値が正（data 属性と style が食い違っていても画面どおりに出す）
        _n_geo, _n_fill = _ML.apply_geometry(soup, MEASURED, SLIDE_W_PX, SLIDE_H_PX)
        if RAW_SVG_SOUP is not None:
            _ML.apply_geometry(RAW_SVG_SOUP, MEASURED, SLIDE_W_PX, SLIDE_H_PX)  # SVG の突き合わせも同じ値で
        if _n_geo or _n_fill:
            print(f'実測: data 属性と見た目のずれ {_n_geo} か所を見た目に合わせ、書いていなかった大きさ {_n_fill} か所を補った')
    # 自動ページ番号の抑止（<html data-pageno="off">）
    global PAGENO_OFF
    PAGENO_OFF = bool(html_el is not None and html_el.get('data-pageno') == 'off')
    if PAGENO_OFF:
        print('ページ番号: 自動挿入を抑止（data-pageno="off"）')
    # A4系ページサイズ選択時はAWSテンプレート（16:9前提）と非互換なので自動スキップ
    _is_a4 = SLIDE_W_PX in (794, 1123) and SLIDE_H_PX in (794, 1123)
    # aws2（AWSフォーマット2＝バッジ無し・線見出し）も同じAWSテンプレートPPTXを使う
    use_aws_template = (not _is_a4) and html_el and (
        html_el.get('data-template') in ('aws', 'aws2') or
        html_el.get('data-aws-decoration') == 'on'
    )
    # AWSプラグイン（slidekit-aws.js）不在なら通常モードへ縮退（属性は保持・データ破壊しない）
    if use_aws_template and not get_aws_format():
        print('WARN: slidekit-aws.js が無いためAWSテンプレなしで変換します')
        use_aws_template = False
    # AWSロゴを置いてよいのは AWS を宣言したデッキだけ
    # （A4はテンプレを使わないが、宣言があれば暗色スライドの白ロゴは従来どおり置く）
    global AWS_DECK
    AWS_DECK = bool(html_el is not None and (
        html_el.get('data-template') in ('aws', 'aws2') or
        html_el.get('data-aws-decoration') == 'on') and get_aws_format())
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # テンプレPPTX検索定義は slidekit-aws.js (formats.aws.pptxTemplate) が正本。
    # envVar → スクリプト基準の相対候補の順。aws 未登録時は (None, []) = テンプレなし。
    _tpl_env, _tpl_cands = get_pptx_template_search()
    candidates = ([os.environ.get(_tpl_env, '')] if _tpl_env else []) + [
        os.path.join(script_dir, c) for c in _tpl_cands
    ]
    aws_tpl_path = None
    for c in candidates:
        if c and os.path.exists(c):
            aws_tpl_path = c
            break
    if use_aws_template and aws_tpl_path:
        prs = Presentation(aws_tpl_path)
        # テンプレートの既存スライドを削除（マスター/レイアウトは残る）
        xml_slides = prs.slides._sldIdLst
        for _ in range(len(xml_slides)):
            rId = xml_slides[0].rId
            prs.part.drop_rel(rId)
            del xml_slides[0]
        # process_slide 内で AWS 表紙処理を分岐するためグローバルフラグを立てる
        global USE_AWS_TEMPLATE
        USE_AWS_TEMPLATE = True
        print(f"AWSテンプレート使用: {aws_tpl_path}")
    else:
        prs = Presentation()
        if use_aws_template:
            print("⚠️ AWSテンプレート指定あり、ファイル未発見（通常モードで生成）")
            print("   環境変数 SLIDEKIT_AWS_TEMPLATE でパス指定可能")
    prs.slide_width = Emu(SLIDE_W_EMU)
    prs.slide_height = Emu(SLIDE_H_EMU)

    slides = soup.find_all('div', class_='slide')
    # docProps/app.xml 書き換え用にスライドタイトルを抽出（<!-- SLIDE: 名前 -->→最大.tb→デフォルト の順）
    slide_titles = extract_slide_titles(soup, raw_html)
    assert len(slide_titles) == len(slides), \
        f"slide_titles({len(slide_titles)}) != slides({len(slides)})"
    for i, slide_div in enumerate(slides, 1):
        process_slide(prs, slide_div, i)

    # ページジャンプリンク（data-link-sid）を全スライド生成後に解決（前方参照対応）
    _resolve_slide_links()

    # 欠落アセットがあり、--allow-missing-assets 指定なしの場合は
    # 完成品の名前に紛れないよう .incomplete.pptx に書き出す。
    write_path = output_path
    if MISSING_ASSETS and not allow_missing:
        base, ext = os.path.splitext(output_path)
        write_path = base + '.incomplete' + ext
    prs.save(write_path)
    # post-process: [Content_Types].xml の欠落を補完する（PowerPoint修復ダイアログ対策）
    _fix_content_types(write_path)
    # post-process: docProps/app.xml を実スライド構成に合わせて書き換える（PowerPoint修復ダイアログ対策）
    if os.environ.get('SLIDEKIT_SKIP_APP_XML_FIX') != '1':
        _fix_app_xml(write_path, slide_titles)
    # PowerPointで直せる形にそろえる（毎回・オプションなし）: 段落既定の太字を run へ移す／
    # 右下に残った手書きのページ番号を自動番号にする。どの経路で作った要素でもここを通る
    _nb, _npg = _SEM.fix_editable(write_path)
    if _npg:
        print(f'ページ番号: 文字のまま残っていた {_npg} か所を自動番号にした')
    # --semantic: トークン色をテーマの配色に登録し、同じ色をテーマ色で参照する（AWSテンプレはテンプレ側の配色を使う）
    if SEMANTIC:
        if USE_AWS_TEMPLATE:
            print('テーマ色: AWSテンプレートの配色を使うため置き換えない')
        else:
            _n_sc, _n_th = _SEM.apply_theme_colors(write_path)
            print(f'テーマ色: {_n_sc} か所をテーマ色で参照（PowerPointの「配色」で一度に変えられる）')
        # 読み上げ順: 文字の無い図形を装飾にして、見出し→本文→図の順に読まれるようにする（重なり順は変えない）
        _SEM.mark_decorative(write_path)
    if ASK_LEFT:
        _kinds = {'illust': 'イラスト', 'chart': 'グラフ', 'photo': '写真'}
        print(f'⚠️ 依頼の枠が {len(ASK_LEFT)} 個残っている（PPTXでは破線の枠と依頼文のまま）: '
              + '、'.join(f'{s}枚目 {_kinds.get(k, k)}' for s, k in ASK_LEFT[:8]))
    if ALT_MISSING:
        print(f'代替テキストの無い図 {len(ALT_MISSING)} 個（img に alt="…" を書くと読み上げ・アクセシビリティチェックに出る）')
        for _s, _k, _src in ALT_MISSING[:5]:
            print(f'  - {_s}枚目 {_k}: {_src}')
    # post-process: macOSの検疫属性(com.apple.quarantine)を外す（必ず最後＝zip書き換え後に実行）。
    # 付いたままだとPowerPointが保護ビュー（読み取り専用）で開き、
    # 「文字が編集できない」ように見える（2026-07-26実地で発生）
    if sys.platform == 'darwin':
        try:
            subprocess.run(['xattr', '-d', 'com.apple.quarantine', write_path],
                           capture_output=True, timeout=10)
        except Exception:
            pass

    # 欠落アセットチェック → error 終了 or 警告続行
    if MISSING_ASSETS:
        print()
        print(f"⚠️  {len(MISSING_ASSETS)} 個のアセット (SVG等) が変換できませんでした:")
        for slide_i, kind, x, y, w, h, reason in MISSING_ASSETS:
            print(f"   ERROR: Slide {slide_i} / {kind} at ({x},{y}) {w}x{h}")
            print(f"          {reason}")
        if not allow_missing:
            print()
            print(f"⚠️  不完全な PPTX を {write_path} に書き出しました。")
            print(f"    (完成した扱いにしないため、通常名 {output_path} には保存していません)")
            print("解決策:")
            print("  1) Chrome をインストール (または CHROME_PATH 環境変数でパス指定)")
            print("  2) 欠落を承知の上で通常名に保存する場合: --allow-missing-assets フラグを付ける")
            sys.exit(2)
        else:
            print()
            print(f"Saved: {write_path} ({len(slides)} slides) — SVG欠落あり (--allow-missing-assets)")
    else:
        print(f"Saved: {write_path} ({len(slides)} slides)")


def _add_white_aws_logo_to_slide(slide):
    """暗色スライドの左上にAWSロゴを白色化したPNGで直接配置する。
    ロゴSVGはマージ後 defs の formats.aws.logoSvg（slidekit-aws.js プラグイン内包）から読む。
    logoSvg 無し（プラグイン無し）なら黙って return。
    テンプレ Cover-Gradient レイアウトの Graphic 3 は blip embed が空で表示されないため。
    """
    fmt = get_aws_format()
    svg_text = fmt.get('logoSvg') if isinstance(fmt, dict) else None
    if not svg_text or not CHROME:
        return
    # 出力PNGサイズ(2倍解像度でPPTXの79x47pt相当)
    RENDER_W, RENDER_H = 316, 188
    try:
        # 全ての fill / stroke を #FFFFFF に置換(属性・style両方)
        svg_white = re.sub(r'fill\s*=\s*"[^"]*"', 'fill="#FFFFFF"', svg_text)
        svg_white = re.sub(r'stroke\s*=\s*"[^"]*"', 'stroke="#FFFFFF"', svg_white)
        svg_white = re.sub(r'fill\s*:\s*[^;"\s]+', 'fill:#FFFFFF', svg_white)
        svg_white = re.sub(r'stroke\s*:\s*[^;"\s]+', 'stroke:#FFFFFF', svg_white)
        # <svg> タグに width/height を明示注入（Chromeが正しいサイズでレンダリングするため）
        svg_white = re.sub(
            r'<svg\b([^>]*)>',
            lambda m: f'<svg width="{RENDER_W}" height="{RENDER_H}"' + m.group(1) + '>',
            svg_white, count=1
        )
        # HTMLでラップして余白ゼロで確実にサイズ固定
        html = f'<!DOCTYPE html><html><head><style>html,body{{margin:0;padding:0;background:transparent}}svg{{display:block}}</style></head><body>{svg_white}</body></html>'
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as sf:
            sf.write(html)
            svg_tmp = sf.name
        png_tmp = svg_tmp.replace('.html', '.png')
        # Chrome headless で PNG化(透過背景)。サイズは 316x188 (2倍解像度で 79x47pt 相当)
        try:
            subprocess.run(
                [CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                 '--default-background-color=00000000', '--force-device-scale-factor=1',
                 '--window-size=316,188', '--screenshot=' + png_tmp, 'file://' + svg_tmp],
                timeout=30, capture_output=True
            )
        except Exception:
            pass
        if not os.path.exists(png_tmp):
            # 旧Chromeフォールバック
            try:
                subprocess.run(
                    [CHROME, '--headless', '--disable-gpu', '--hide-scrollbars',
                     '--default-background-color=00000000', '--force-device-scale-factor=1',
                     '--window-size=316,188', '--screenshot=' + png_tmp, 'file://' + svg_tmp],
                    timeout=30, capture_output=True
                )
            except Exception:
                pass
        if os.path.isfile(png_tmp):
            # テンプレ Cover-Gradient-2 の Graphic 3 と同じ位置・サイズ (pt単位)
            slide.shapes.add_picture(png_tmp, Pt(33), Pt(39), Pt(79), Pt(47))
        # 一時ファイル削除
        for p in (svg_tmp, png_tmp):
            if os.path.isfile(p):
                try: os.remove(p)
                except: pass
    except Exception as e:
        print(f'  WARN: 白ロゴ配置失敗: {e}')


def _fix_content_types(pptx_path):
    """[Content_Types].xml の欠落を全面補完（PowerPoint修復ダイアログ対策）
    - SVG含む media 拡張子の Default 宣言
    - slide/slideMaster/slideLayout/theme 等各パートの Override 宣言
    - 個別 media Override は Default で網羅されるなら削除
    """
    import zipfile
    from lxml import etree
    NS_CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
    CT_MAP_EXT = {
        'svg': 'image/svg+xml',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'gif': 'image/gif',
        'bmp': 'image/bmp', 'tif': 'image/tiff', 'tiff': 'image/tiff',
        'webp': 'image/webp',
    }
    # part 名パターン → Content-Type のマッピング（PPTX仕様）
    CT_MAP_PART = [
        ('/ppt/presentation.xml', 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'),
        ('/ppt/presProps.xml', 'application/vnd.openxmlformats-officedocument.presentationml.presProps+xml'),
        ('/ppt/viewProps.xml', 'application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml'),
        ('/ppt/tableStyles.xml', 'application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml'),
        ('/ppt/authors.xml', 'application/vnd.ms-powerpoint.authors+xml'),
        ('/docProps/core.xml', 'application/vnd.openxmlformats-package.core-properties+xml'),
        ('/docProps/app.xml', 'application/vnd.openxmlformats-officedocument.extended-properties+xml'),
        ('/docProps/custom.xml', 'application/vnd.openxmlformats-officedocument.custom-properties+xml'),
    ]
    def _content_type_for(part_name):
        # 完全一致
        for pn, ct in CT_MAP_PART:
            if part_name == pn:
                return ct
        # プレフィックス
        if part_name.startswith('/ppt/slides/slide') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'
        if part_name.startswith('/ppt/slideMasters/slideMaster') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml'
        if part_name.startswith('/ppt/slideLayouts/slideLayout') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml'
        if part_name.startswith('/ppt/notesMasters/notesMaster') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml'
        if part_name.startswith('/ppt/notesSlides/notesSlide') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml'
        if part_name.startswith('/ppt/handoutMasters/handoutMaster') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.presentationml.handoutMaster+xml'
        if part_name.startswith('/ppt/theme/theme') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.theme+xml'
        if part_name.startswith('/customXml/itemProps') and part_name.endswith('.xml'):
            return 'application/vnd.openxmlformats-officedocument.customXmlProperties+xml'
        return None

    with zipfile.ZipFile(pptx_path) as z:
        namelist = z.namelist()
        files = {n: z.read(n) for n in namelist}
    ct_data = files.get('[Content_Types].xml')
    if not ct_data:
        return
    root = etree.fromstring(ct_data)
    existing_defaults = {c.get('Extension', '').lower() for c in root
                         if c.tag == f'{{{NS_CT}}}Default'}
    existing_overrides = {c.get('PartName') for c in root
                          if c.tag == f'{{{NS_CT}}}Override'}
    changed = False
    # (1) media 拡張子の Content-Type 補完
    # 🚨 SVGは Default ではなく Override で個別指定する（PowerPointの厳格な検証がDefault svgを拒否＝修復ダイアログの原因）
    # jpeg/png は Default で網羅（PPTX標準）、svgは個別 Override（python-pptxの再保存挙動と一致）
    # ECMA-376 スキーマ順序: Default 群 → Override 群
    OVERRIDE_ONLY_EXTS = {'svg'}  # Default にすると PowerPoint が修復対象にする拡張子
    used_exts = set()
    used_media_files = []
    for name in namelist:
        if name.startswith('ppt/media/'):
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext in CT_MAP_EXT:
                used_exts.add(ext)
                used_media_files.append((name, ext))
    # (1a) Override 個別対応の拡張子は個別 Override で補完
    for name, ext in used_media_files:
        if ext in OVERRIDE_ONLY_EXTS:
            part_name = '/' + name
            if part_name not in existing_overrides:
                o = etree.SubElement(root, f'{{{NS_CT}}}Override')
                o.set('PartName', part_name); o.set('ContentType', CT_MAP_EXT[ext])
                existing_overrides.add(part_name)
                changed = True
    # (1b) Default 対応の拡張子は Default で補完（Default 群の直後に挿入）
    last_default_idx = -1
    for i, c in enumerate(root):
        if c.tag == f'{{{NS_CT}}}Default':
            last_default_idx = i
    insert_pos = last_default_idx + 1
    for ext in sorted(used_exts - OVERRIDE_ONLY_EXTS):
        if ext not in existing_defaults:
            d = etree.Element(f'{{{NS_CT}}}Default')
            d.set('Extension', ext); d.set('ContentType', CT_MAP_EXT[ext])
            root.insert(insert_pos, d)
            insert_pos += 1
            changed = True
            existing_defaults.add(ext)
    # (2) 個別 media Override は Default で網羅されるなら削除（Override専用拡張子は残す）
    for c in list(root):
        if c.tag == f'{{{NS_CT}}}Override':
            pn = c.get('PartName', '')
            if pn.startswith('/ppt/media/'):
                ext = pn.rsplit('.', 1)[-1].lower() if '.' in pn else ''
                if ext in existing_defaults and ext not in OVERRIDE_ONLY_EXTS:
                    root.remove(c)
                    existing_overrides.discard(pn)
                    changed = True
    # (3) zip内に実在する xml パートに Override が抜けていたら追加
    for name in namelist:
        if not name.endswith('.xml'):
            continue
        if name == '[Content_Types].xml':
            continue
        part_name = '/' + name
        if part_name in existing_overrides:
            continue
        ct = _content_type_for(part_name)
        if ct is None:
            continue
        o = etree.SubElement(root, f'{{{NS_CT}}}Override')
        o.set('PartName', part_name); o.set('ContentType', ct)
        existing_overrides.add(part_name)
        changed = True
    if not changed:
        return
    files['[Content_Types].xml'] = etree.tostring(
        root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    if EXPORTED_SVG:
        print(f"SVG単体ファイル {len(EXPORTED_SVG)}件 → {SVG_OUT_DIR}/ （PowerPointへ手動でドラッグ＆ペーストするとベクターで鮮明）")
        for sn, x, y, w, h, name in EXPORTED_SVG:
            print(f"  - {name}（{sn}枚目 / 位置 x{x},y{y} / {w}×{h}px）")


def _fix_app_xml(pptx_path, slide_titles):
    """docProps/app.xml を実スライド構成に合わせて書き換える（PowerPoint修復ダイアログ対策）。

    書き換える要素:
      - <Slides>            テキスト → str(N)（N = len(slide_titles) = 実スライド枚数）
      - <Words>             テキスト → '0'（無ければ SubElement で追加）
      - <Paragraphs>        テキスト → '0'（無ければ SubElement で追加）
      - <HeadingPairs>/vt:vector の中で <vt:lpstr>スライド タイトル</vt:lpstr>
        の次の兄弟 variant 内の <vt:i4> → str(N)
        （ペアが見つからなければ先頭に <vt:variant><vt:lpstr>スライド タイトル
        </vt:lpstr></vt:variant><vt:variant><vt:i4>N</vt:i4></vt:variant> を
        prepend し vector の size を +2。他ペア「使用したフォント」等はそのまま残す）
      - <TitlesOfParts>/vt:vector の size 属性 → str(N)、baseType 属性 → 'lpstr'
      - <TitlesOfParts>/vt:vector の子要素を全削除 → slide_titles の各文字列を
        <vt:lpstr> として追加（`SubElement().text = title` で lxml が自動 escape）

    触らない要素:
      - <Application> / <AppVersion> / <Company> / <Manager> / <TotalTime> /
        <ScaleCrop> / <LinksUpToDate> / <SharedDoc> / <HyperlinksChanged>
      - <HeadingPairs> の他ペア（「使用したフォント」「テーマ」等）

    防御ケース（早期 return して pptx を無変更で残す）:
      - N == 0（slide_titles が空）
      - docProps/app.xml が ZIP に存在しない（通常モードで python-pptx が自動生成
        しなかったケース向け）

    要件 3.6 に従い print は追加しない。
    """
    import zipfile
    from lxml import etree

    NS_EXT = 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'
    NS_VT = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'

    N = len(slide_titles)
    if N == 0:
        return

    with zipfile.ZipFile(pptx_path) as z:
        namelist = z.namelist()
        files = {n: z.read(n) for n in namelist}

    if 'docProps/app.xml' not in files:
        return

    root = etree.fromstring(files['docProps/app.xml'])

    # (1) <Slides> → str(N)
    slides_el = root.find(f'{{{NS_EXT}}}Slides')
    if slides_el is None:
        slides_el = etree.SubElement(root, f'{{{NS_EXT}}}Slides')
    slides_el.text = str(N)

    # (2) <Words> / <Paragraphs> → '0'
    for tag in ('Words', 'Paragraphs'):
        el = root.find(f'{{{NS_EXT}}}{tag}')
        if el is None:
            el = etree.SubElement(root, f'{{{NS_EXT}}}{tag}')
        el.text = '0'

    # (3) <HeadingPairs> の「スライド タイトル」ペアの <vt:i4> を書き換え
    hp = root.find(f'{{{NS_EXT}}}HeadingPairs')
    if hp is None:
        hp = etree.SubElement(root, f'{{{NS_EXT}}}HeadingPairs')
    hp_vec = hp.find(f'{{{NS_VT}}}vector')
    if hp_vec is None:
        hp_vec = etree.SubElement(hp, f'{{{NS_VT}}}vector')
        hp_vec.set('size', '0')
        hp_vec.set('baseType', 'variant')

    variants = hp_vec.findall(f'{{{NS_VT}}}variant')
    found_slide_title_pair = False
    # ペアは (label, count) の 2 個 1 組で並ぶ
    for i in range(0, len(variants) - 1, 2):
        label_el = variants[i].find(f'{{{NS_VT}}}lpstr')
        if label_el is not None and label_el.text == 'スライド タイトル':
            count_variant = variants[i + 1]
            i4_el = count_variant.find(f'{{{NS_VT}}}i4')
            if i4_el is None:
                i4_el = etree.SubElement(count_variant, f'{{{NS_VT}}}i4')
            i4_el.text = str(N)
            found_slide_title_pair = True
            break

    if not found_slide_title_pair:
        # 先頭に「スライド タイトル」ペアを prepend し vector の size を +2
        label_variant = etree.Element(f'{{{NS_VT}}}variant')
        lpstr_el = etree.SubElement(label_variant, f'{{{NS_VT}}}lpstr')
        lpstr_el.text = 'スライド タイトル'
        count_variant = etree.Element(f'{{{NS_VT}}}variant')
        i4_el = etree.SubElement(count_variant, f'{{{NS_VT}}}i4')
        i4_el.text = str(N)
        # insert 順は逆から入れる（先に count、次に label を index 0 に入れる
        # ことで最終的に [label, count, ...既存...] の並びになる）
        hp_vec.insert(0, count_variant)
        hp_vec.insert(0, label_variant)
        try:
            cur_size = int(hp_vec.get('size') or 0)
        except (TypeError, ValueError):
            cur_size = 0
        hp_vec.set('size', str(cur_size + 2))

    # (4) <TitlesOfParts>
    top = root.find(f'{{{NS_EXT}}}TitlesOfParts')
    if top is None:
        top = etree.SubElement(root, f'{{{NS_EXT}}}TitlesOfParts')
    top_vec = top.find(f'{{{NS_VT}}}vector')
    if top_vec is None:
        top_vec = etree.SubElement(top, f'{{{NS_VT}}}vector')
    # 子要素を全削除
    for child in list(top_vec):
        top_vec.remove(child)
    # size 属性 & baseType 属性
    top_vec.set('size', str(N))
    top_vec.set('baseType', 'lpstr')
    # 実スライド分の <vt:lpstr>title</vt:lpstr>（lxml が自動 escape）
    for title in slide_titles:
        lpstr_el = etree.SubElement(top_vec, f'{{{NS_VT}}}lpstr')
        lpstr_el.text = title

    # ZIP 書き戻し（既存 _fix_content_types と同じスタイル）
    files['docProps/app.xml'] = etree.tostring(
        root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


# 制御文字（U+0000-U+001F のうち tab/LF/CR 以外）を落とすための正規表現
_CTRL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
# <!-- SLIDE: 名前 --> のコメントから名前部分を拾う（先頭末尾の空白は落とす）
_SLIDE_COMMENT_RE = re.compile(r'^\s*SLIDE:\s*(.*?)\s*$', re.DOTALL)


def extract_slide_titles(soup, raw_html):
    """.slide 要素から docProps/app.xml 用のスライドタイトルを抽出する。

    抽出優先順位:
      1. .slide 直前の HTML コメント <!-- SLIDE: 名前 --> から拾う
      2. コメントが無ければ .slide 内の .tb のうち data-font-size 最大
         (同値なら data-y 最小) の要素の text
         （ページ番号らしき数字だけの text は候補から除外）
      3. それも無ければ固定文字列 'PowerPoint プレゼンテーション'

    XML escape は行わない。lxml の `SubElement().text = value` に渡す前提で
    生の文字列を返し、`<`, `>`, `&`, `"`, `'` などのエスケープは呼び出し側
    (lxml) が自動で行う。手書きで `&amp;` を書かない。

    制御文字 (U+0000-U+001F のうち tab/LF/CR 以外) は削除する
    （XML 1.0 で不正なため）。

    Args:
        soup: BeautifulSoup でパース済みの HTML（lxml パーサ推奨）
        raw_html: 元 HTML 文字列。現状ロジックでは soup だけで完結するが、
                  将来 BeautifulSoup がコメント順序を落とすケースに備えて
                  API に残してある

    Returns:
        list[str]: `.slide` 要素と同じ長さのタイトル文字列リスト
    """
    slides = soup.find_all('div', class_='slide')
    titles = []
    for slide_div in slides:
        title = None

        # 1. 直前の Comment ノード <!-- SLIDE: 名前 -->
        prev = slide_div.previous_sibling
        while prev is not None and not isinstance(prev, Comment):
            # 空白だけのテキストノードならスキップして遡る
            if isinstance(prev, NavigableString) and str(prev).strip() == '':
                prev = prev.previous_sibling
                continue
            # 非空白テキスト or 別要素に当たった時点で終了（コメントは見つからず）
            prev = None
            break
        if isinstance(prev, Comment):
            m = _SLIDE_COMMENT_RE.match(str(prev))
            if m:
                captured = m.group(1)
                # 末尾のパターンID宣言（[P09]/[D05]/[CUSTOM: 理由]）はタイトルに含めない
                captured = re.sub(r'\s*\[(?:[PD]\d{2}|CUSTOM:[^\]]*)\]\s*$', '', captured)
                if captured:
                    title = captured

        # 2. スライド内の .tb で data-font-size 最大 (同値なら data-y 最小)
        if title is None:
            candidates = []
            for tb in slide_div.find_all('div', class_='tb'):
                text = tb.get_text(strip=True)
                # 空 or 数字だけ (ページ番号) はフォールバック候補から除外
                if not text or text.isdigit():
                    continue
                try:
                    fs = float(tb.get('data-font-size', 0) or 0)
                except (TypeError, ValueError):
                    fs = 0
                try:
                    y = int(tb.get('data-y', 9999) or 9999)
                except (TypeError, ValueError):
                    y = 9999
                # sort キー: (font-size 大, y 小) が先に来る
                candidates.append((fs, -y, text))
            if candidates:
                candidates.sort(reverse=True)
                title = candidates[0][2]

        # 3. フォールバック
        if not title:
            title = 'PowerPoint プレゼンテーション'

        # 制御文字を削除（tab/LF/CR は許容）
        title = _CTRL_CHAR_RE.sub('', title)
        titles.append(title)

    # 防御的 assert: 戻り値の長さは必ず .slide 要素数と一致する
    assert len(titles) == len(slides), (
        f"extract_slide_titles: titles count {len(titles)} != slides count {len(slides)}"
    )
    return titles


if __name__ == '__main__':
    main()
