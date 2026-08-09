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
from pptx.oxml.ns import qn, nsdecls
from pptx.oxml import parse_xml
from bs4 import BeautifulSoup, Comment, NavigableString
import os, re, sys, subprocess, tempfile, shutil, base64

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
CUR_SLIDE = 0   # 現在のスライド番号（1始まり）
SVG_OUT_DIR = None
EXPORTED_SVG = []
MISSING_ASSETS = []  # (slide, kind, x, y, w, h, reason) — Chrome 欠落等で SVG が変換できなかった記録
ALLOW_MISSING = False  # --allow-missing-assets が指定されているか (欠落を許すか)
# AWSテンプレート使用時のフラグ。表紙(暗色)スライドで文字/ロゴを黒に切替える判定に使う
USE_AWS_TEMPLATE = False

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


def add_svg(slide, wrapper):
    """SVGを含むラッパーdiv（data-x/y/w/h）をPNG化してラッパーと同座標・同サイズで配置。
    あわせて単体.svgファイルを書き出す（PowerPointへ手動でベクター貼り付け用）。"""
    x = int(wrapper.get('data-x', 0)); y = int(wrapper.get('data-y', 0))
    w = int(wrapper.get('data-w', 400)); h = int(wrapper.get('data-h', 200))
    svg = wrapper.find('svg')
    png = rasterize_svg(svg, w, h) if svg is not None else None
    placed = False
    if png:
        slide.shapes.add_picture(png, px_to_emu_x(x), px_to_emu_y(y), px_to_emu_x(w), px_to_emu_y(h))
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
    # 単体SVGファイルを書き出し（このwrapper自身から html.parser 経由で取り出す→対応保証）
    raw = _find_matching_raw_svg(wrapper)
    if raw and SVG_OUT_DIR:
        content = standalone_svg(raw, w, h)
        if content:
            os.makedirs(SVG_OUT_DIR, exist_ok=True)
            name = 'S%d_x%d_y%d_%dx%d.svg' % (CUR_SLIDE, x, y, w, h)
            with open(os.path.join(SVG_OUT_DIR, name), 'w', encoding='utf-8') as f:
                f.write(content)
            EXPORTED_SVG.append((CUR_SLIDE, x, y, w, h, name))
    return placed



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

def hex_to_rgb(h):
    # #fff → #ffffff、8桁は先頭6桁を採用（αは無視）。それ以外は既定色
    if not h:
        return RGBColor(0x33, 0x33, 0x33)
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c*2 for c in h)
    if len(h) == 8:
        h = h[:6]
    if len(h) == 6:
        try:
            return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
        except Exception:
            pass
    return RGBColor(0x33, 0x33, 0x33)


def _is_valid_hex(v):
    """3/6/8桁hexなら True"""
    if not v:
        return False
    v = v.lstrip('#')
    return len(v) in (3, 6, 8) and all(c in '0123456789abcdefABCDEF' for c in v)

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

    def walk(node, fs, bold, color, align):
        for child in node.children:
            if isinstance(child, str):
                t = re.sub(r'\s+', ' ', str(child))
                if t.strip() or (t == ' ' and lines[-1]['runs']):
                    lines[-1]['runs'].append((t, fs, bold, color))
                    if align and lines[-1]['align'] is None:
                        lines[-1]['align'] = align
                continue
            if child.name == 'br':
                newline()
                continue
            st = child.get('style', '') or ''
            nfs, nb, nc, nal = fs, bold, color, align
            m = re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*px', st)
            if m: nfs = float(m.group(1))
            m = re.search(r'font-weight\s*:\s*(\d+|bold|normal)', st)
            if m:
                v = m.group(1)
                nb = (v == 'bold') or (v.isdigit() and int(v) >= 600)
            m = re.search(r'(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{3,8})', st)
            if m: nc = m.group(1).lstrip('#')
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
                walk(child, nfs, nb, nc, nal)
                newline()
                continue
            is_block = bool(re.search(r'display\s*:\s*block', st))
            if is_block and lines[-1]['runs']:
                newline()
            walk(child, nfs, nb, nc, nal)
            if is_block:
                newline()
        return

    walk(el, fs, bold, color, None)
    # 行頭・行末の空白を除去し、空行（連続brの間以外の末尾）を整理
    out = []
    for ln in lines:
        runs = ln['runs']
        if runs:
            t0, f0, b0, c0 = runs[0]
            runs[0] = (t0.lstrip(), f0, b0, c0)
            t1, f1, b1, c1 = runs[-1]
            runs[-1] = (t1.rstrip(), f1, b1, c1)
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
    m = re.search(r'line-height\s*:\s*([\d.]+)(px)?', el.get('style', '') or '')
    if not m:
        return None
    try:
        v = float(m.group(1))
        return Pt(px_to_pt(v)) if m.group(2) else Pt(px_to_pt(v * font_size_px))
    except Exception:
        return None

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
    for i, (runs, lal, lvl) in enumerate(rich_lines(el, font_size, bold, color)):
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

def add_rect_shape(slide, el, rounded=False):
    x = int(el.get('data-x', 0))
    y = int(el.get('data-y', 0))
    w = int(el.get('data-w', 400))
    h = int(el.get('data-h', 100))
    fill_color = el.get('data-fill', '#f7fafc')

    classes = el.get('class', [])
    ds = el.get('data-shape')
    is_chev = ('chev' in classes) or (ds == 'chevron')
    # style / data-radius から角丸 px を拾う（バッジ pill shape 等をPPTXでも再現）
    _style = el.get('style', '') or ''
    _br_m = re.search(r'border-radius\s*:\s*(\d+)px', _style)
    radius_px = None
    _dr = el.get('data-radius')
    if _dr:
        try: radius_px = int(_dr)
        except: pass
    elif _br_m:
        radius_px = int(_br_m.group(1))
    if rounded:
        shape_enum = MSO_SHAPE.ROUNDED_RECTANGLE
    elif is_chev:
        shape_enum = _mso_shape_enum('chevron', MSO_SHAPE.PENTAGON)  # 右が尖ったホームベース型（矢印）
    elif ds == 'circle':
        shape_enum = _mso_shape_enum('circle', MSO_SHAPE.OVAL)
    elif ds == 'triangle':
        shape_enum = _mso_shape_enum('triangle', MSO_SHAPE.ISOSCELES_TRIANGLE)
    elif ds == 'arrow':
        shape_enum = _mso_shape_enum('arrow', MSO_SHAPE.RIGHT_ARROW)
    elif radius_px and radius_px > 0:
        # 通常rectでも border-radius があれば ROUNDED_RECTANGLE で
        shape_enum = MSO_SHAPE.ROUNDED_RECTANGLE
    else:
        shape_enum = 1  # line は塗りつぶしの細い四角としてそのまま出力
    shape = slide.shapes.add_shape(
        shape_enum,
        px_to_emu_x(x), px_to_emu_y(y),
        px_to_emu_x(w), px_to_emu_y(h)
    )
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
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        
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
            for j, (runs, lal, lvl) in enumerate(rich_lines(tb, font_size, bold, color)):
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
    if len(cols) == n_cols:
        widths = [_parse_len_px(c.get('style',''), c.get('width'), total_w_px, 'width') for c in cols]
        if all(w is not None and w > 0 for w in widths):
            return widths
    # 🚨全行を走査し、rowspan/colspanの占有を考慮して論理列ごとの幅指定を拾う。
    # 先頭行だけ見る方式だと「1行目がcolspanの大見出しth」の表で列幅が全滅し、
    # 等分配分→本文が折り返して表が縦に膨らむ（2026-07-18 S8選定基準表で発生）
    widths = [None] * n_cols
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
    _min_row_px = int(table_font_px * 1.4) + 10  # フォント1行分＋上下padding相当
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
            tbl_cell.text = cell.get_text(strip=True)
            p = tbl_cell.text_frame.paragraphs[0]
            cstyle = cell.get('style') or ''
            # 書式は段落(defRPr)とrunの両方に設定する。
            # PowerPointは既存runに段落既定色を適用しないため、p.fontだけだと
            # thの白文字がテーマ黒で描画され読めなくなる（2026-07-18実地で確認）
            _fonts = [p.font] + [r.font for r in p.runs]
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
                p.alignment = get_align(ta)
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
                fg = _pick_color_from_style(cstyle) or _pick_color_from_style(rstyle)
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
                    tbl_cell.fill.solid()
                    tbl_cell.fill.fore_color.rgb = hex_to_rgb('#f7fafc')
            # セル枠線（fill設定の後に呼ぶが、挿入位置はスキーマ順を守る）
            for side, (bw, bc) in _cell_borders_from_style(cstyle).items():
                _set_cell_border(tbl_cell, side, bw, bc)

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
        img_path = os.path.join(BASE_DIR, src)
    
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

        # contain の場合はコンテナ内にアス比保持で内側配置するよう x,y,w,h を差し替え
        # (return せず共通の add_picture ブロックに合流 → border など後続処理も走る)
        if is_contain:
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

        pic = slide.shapes.add_picture(
            img_path,
            px_to_emu_x(x), px_to_emu_y(y),
            px_to_emu_x(w), px_to_emu_y(h)
        )
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
                    op_match = re.search(r'object-position:([^;]+)', img_style)
                    if op_match:
                        parts = op_match.group(1).strip().split()
                        if parts:
                            if parts[0] in ('left','center','right'):
                                op_h = parts[0]
                            if len(parts) > 1 and parts[1] in ('top','center','bottom'):
                                op_v = parts[1]
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
    elif bg_solid and bg_solid != '#ffffff':
        try:
            bg = slide.background
            fill = bg.fill
            fill.solid()
            fill.fore_color.rgb = hex_to_rgb(bg_solid)
        except Exception as e:
            print(f'  WARN: slide{slide_no} 単色背景設定失敗({e}) → 背景なしで続行')
    
    # Process direct children
    has_pageno = False
    for child in slide_div.children:
        if not hasattr(child, 'get'):
            continue
        
        classes = child.get('class', [])
        
        # ラッパー div が SVG を内包しているかを事前判定
        # (rect/flow 内に SVG が入っている場合、枠 + SVG の両方を描画する)
        has_svg = (hasattr(child, 'find') and child.find('svg') is not None
                   and child.get('data-x') is not None)

        if 'tb' in classes:
            # スライド番号の判定：右下（スライドサイズ相対）にあって数字だけの.tb
            # 固定値(1180/660)だとA4縦(794×1123)で判定できないため相対化
            try:
                _tx = int(float(child.get('data-x', 0) or 0))
                _ty = int(float(child.get('data-y', 0) or 0))
                _text = (child.get_text() or '').strip()
                if _tx >= SLIDE_W_PX - 100 and _ty >= SLIDE_H_PX - 60 and _text.isdigit():
                    has_pageno = True
            except Exception:
                pass
            add_textbox(slide, child)
        elif 'rect' in classes:
            add_rect_shape(slide, child)
            # rect が SVG を内包していれば SVG を上に重ねて配置 (紙芝居の粗い絵など)
            if has_svg:
                add_svg(slide, child)
        elif 'flow' in classes:
            add_rect_shape(slide, child, rounded=True)
            if has_svg:
                add_svg(slide, child)
        elif child.name == 'table':
            add_table(slide, child)
        elif child.name == 'div':
            # SVG（ファネル等）はラッパーのdata-x/y/w/hでPNG配置→位置・サイズが画面と一致
            if has_svg:
                add_svg(slide, child)
            else:
                img = child.find('img')
                if img:
                    add_image(slide, img, child.get('style', ''))

    # ページ番号が入っていなければ自動で右下に追加（SlideKitのrenumberPages相当）
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
            _pn_px = 21 if SLIDE_W_PX >= 1280 else 14  # 16:9投影=21px / A4文書=14px
            for f in [p.font] + [r.font for r in p.runs]:
                f.size = Pt(px_to_pt(_pn_px))
                set_font_name(f, FONT_NAME)
                f.color.rgb = hex_to_rgb('#718096')
        except Exception as e:
            print(f'  WARN: auto page number failed: {e}')

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
    args = [a for a in sys.argv[1:] if a != '--allow-missing-assets']
    allow_missing = '--allow-missing-assets' in sys.argv
    if len(args) < 1:
        print("Usage: python3 html_to_pptx.py <slides.html> [output.pptx] [--allow-missing-assets]")
        print("  --allow-missing-assets  SVG欠落 (Chrome無し等) があっても通常の出力名で続行")
        print("                          (指定なしの場合は .incomplete.pptx にリネームして exit 2)")
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
    soup = BeautifulSoup(raw_html, 'lxml')
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
    # A4系ページサイズ選択時はAWSテンプレート（16:9前提）と非互換なので自動スキップ
    _is_a4 = SLIDE_W_PX in (794, 1123) and SLIDE_H_PX in (794, 1123)
    use_aws_template = (not _is_a4) and html_el and (
        html_el.get('data-template') == 'aws' or
        html_el.get('data-aws-decoration') == 'on'
    )
    # AWSプラグイン（slidekit-aws.js）不在なら通常モードへ縮退（属性は保持・データ破壊しない）
    if use_aws_template and not get_aws_format():
        print('WARN: slidekit-aws.js が無いためAWSテンプレなしで変換します')
        use_aws_template = False
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
