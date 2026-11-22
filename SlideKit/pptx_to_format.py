#!/usr/bin/env python3
"""もらったPPTXから「書式だけ」を抜き出して、SlideKitの型に当てられる形にする。

    python3 SlideKit/pptx_to_format.py もらった.pptx            # → もらった.format.json
    python3 SlideKit/pptx_to_format.py もらった.pptx -o out.json

中身を持ってきたいときは pptx_to_slidekit.py（内容も書式も変換）。
こちらは**内容を捨てて色とフォントと余白だけ**を取り、自分の資料に着せるために使う。

出すもの（<name>.format.json）
    theme  テーマ色（accent1..6 / dk1 / lt1 など）
    used   実際に使われている色と面積（px²）の上位。面積で重みを付けるので地色が上に来る
    fonts  latin / ea の書体名（最頻）
    sizes  タイトル・本文・最小の文字サイズ（px換算）
    layout 左右の余白・タイトルの上端・本文の上端（最頻値）
    map    **SlideKitトークン → 相手の色 の対応表**（これを使って色を置換する）

決定: SlideKitのトークン規則（カタログ外hexはfail）と衝突するので、相手の色で作るデッキは
`<html data-palette="custom">` を宣言する。根拠=.kiro/steering/slide-contract-detail.md
"""
import argparse
import colorsys
import json
import os
import re
import sys
from collections import Counter, defaultdict

from pptx import Presentation
from pptx.util import Emu

EMU_PER_PX = 914400 / 96
SLIDE_W, SLIDE_H = 1280, 720
# SlideKitの主要トークン（slide-contract-detail.md の推奨セット）。役割ごとに相手の色を割り当てる
TOKENS = {
    'ink': '#121212', 'title': '#21537f', 'navy': '#162a42', 'paper': '#fafafa',
    'sub': '#9fc0dd', 'muted': '#718096', 'card': '#eef3f8', 'line': '#d4dde7',
    'accent': '#c62828',
}


def hls(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, l, s


def theme_colors(prs):
    """theme.xml の色スキームを拾う（pptx_to_slidekit.py の ThemeResolver と同じ出所）"""
    out = {}
    try:
        from lxml import etree
        for master in prs.slide_masters:
            for rel in master.part.rels.values():
                if 'theme' not in rel.reltype:
                    continue
                root = etree.fromstring(rel.target_part.blob)
                ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                scheme = root.find('.//a:clrScheme', ns)
                if scheme is None:
                    continue
                for child in scheme:
                    name = etree.QName(child).localname
                    srgb = child.find('a:srgbClr', ns)
                    sysc = child.find('a:sysClr', ns)
                    if srgb is not None:
                        out[name] = '#' + srgb.get('val', '').lower()
                    elif sysc is not None and sysc.get('lastClr'):
                        out[name] = '#' + sysc.get('lastClr').lower()
                if out:
                    return out
    except Exception as e:
        print(f'  WARN: テーマ色を読めなかった（{e}）', file=sys.stderr)
    return out


def collect(prs):
    """全スライドを走って色（面積重み）・フォント・サイズ・座標を集める"""
    area = Counter()          # hex -> px²（塗りは面積、文字は概算面積）
    fonts = Counter()
    sizes = Counter()
    xs, title_tops, body_tops = Counter(), Counter(), Counter()

    def walk(shapes, depth=0):
        for sp in shapes:
            if sp.shape_type is not None and str(sp.shape_type).startswith('GROUP'):
                try:
                    walk(sp.shapes, depth + 1)
                    continue
                except Exception:
                    pass
            try:
                w = max(0, round((sp.width or 0) / EMU_PER_PX))
                h = max(0, round((sp.height or 0) / EMU_PER_PX))
                x = round((sp.left or 0) / EMU_PER_PX)
                y = round((sp.top or 0) / EMU_PER_PX)
            except Exception:
                continue
            # 左余白は「最頻値」ではなく各スライドの最小xを集める（最頻値だと
            # 右側に並ぶオブジェクトが勝って957pxのような無意味な値になる）
            if w > 40 and 0 <= x < SLIDE_W // 2:
                xs[x] += 1
            # 塗り色を面積で重み付け
            try:
                f = sp.fill
                if f.type is not None and str(f.type).startswith('SOLID'):
                    rgb = f.fore_color.rgb
                    if rgb is not None:
                        area['#' + str(rgb).lower()] += w * h
            except Exception:
                pass
            if not sp.has_text_frame:
                continue
            biggest = 0
            for p in sp.text_frame.paragraphs:
                for r in p.runs:
                    if not (r.text or '').strip():
                        continue
                    pt = None
                    try:
                        if r.font.size is not None:
                            pt = r.font.size.pt
                    except Exception:
                        pass
                    if pt:
                        px = round(pt / 0.75)
                        sizes[px] += len(r.text)
                        biggest = max(biggest, px)
                    try:
                        if r.font.color and r.font.color.type is not None and r.font.color.rgb is not None:
                            # 文字は「字数×サイズ²」を面積の代わりにする
                            area['#' + str(r.font.color.rgb).lower()] += len(r.text) * max(8, px or 16) ** 2 // 4
                    except Exception:
                        pass
                    try:
                        if r.font.name:
                            fonts[r.font.name] += len(r.text)
                    except Exception:
                        pass
            if biggest >= 28:
                title_tops[y] += 1
            elif biggest:
                body_tops[y] += 1

    for sl in prs.slides:
        walk(sl.shapes)
    return area, fonts, sizes, xs, title_tops, body_tops


def build_map(area, theme):
    """SlideKitトークン → 相手の色 の対応表を作る。

    明度と彩度で役割を当てる。人が見て直せるよう、必ず全トークンを埋める（欠けるとデッキが崩れる）。
    """
    used = [h for h, _ in area.most_common(40) if re.fullmatch(r'#[0-9a-f]{6}', h)]
    # 決定: テーマ色を優先して役割へ当てる。PPTXは dk1/dk2/lt1/lt2/accent1..6 で
    # 役割を定義しているので、実使用色から推測するより確か（実使用色は塗りが画像や
    # グラデだと拾えず、数色しか取れないことがある。ある提案書で4色しか取れなかった）
    pool, seen = [], set()
    for h in used + [theme[k] for k in ('dk1', 'dk2', 'lt1', 'lt2', 'accent1', 'accent2',
                                        'accent3', 'accent4', 'accent5', 'accent6') if theme.get(k)]:
        if re.fullmatch(r'#[0-9a-f]{6}', h or '') and h not in seen:
            seen.add(h)
            pool.append(h)
    if not pool:
        return {}
    info = {h: hls(h) for h in pool}
    by_light = sorted(pool, key=lambda h: info[h][1])
    darkest, lightest = by_light[0], by_light[-1]
    accents = [theme[k] for k in ('accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6')
               if theme.get(k) and re.fullmatch(r'#[0-9a-f]{6}', theme[k])]
    chromatic = sorted([h for h in pool if info[h][2] > .18], key=lambda h: -info[h][2])
    pale = [h for h in by_light[::-1] if info[h][2] <= .25 and info[h][1] > .82]
    greys = [h for h in pool if info[h][2] <= .25 and .3 <= info[h][1] <= .68]

    ink = theme.get('dk1') or darkest
    paper = theme.get('lt1') or lightest
    navy = theme.get('dk2') or (by_light[1] if len(by_light) > 1 else darkest)
    card = theme.get('lt2') or (pale[0] if pale else paper)
    # 見出しは暗くて彩度のあるもの。accent1が明るい（L>0.55）ときは見出しに使わず dk2 を使う
    a1 = accents[0] if accents else None
    title = a1 if (a1 and info[a1][1] < .55) else navy
    # accentは実際に使われているaccent色を優先。無ければ accent1
    accent = next((h for h in accents if h in used), None) or a1 or (chromatic[0] if chromatic else darkest)
    sub = next((h for h in accents if info[h][1] > .55 and h != accent), None) or (pale[0] if pale else paper)
    out = {
        TOKENS['title']: title, TOKENS['navy']: navy,
        TOKENS['accent']: accent, TOKENS['card']: card, TOKENS['sub']: sub,
        TOKENS['muted']: (greys[0] if greys else navy),
        # 罫線がカード地と同色だと見えないので、違う色を必ず選ぶ
        TOKENS['line']: next((h for h in (pale[1:] + greys[-1:]) if h != card), card),
    }
    # 決定: 本文色と紙面色は相手に合わせない。
    #   #121212 は純黒(#000000)が読みにくいので意図的に選んだ色、#fafafa も純白を避けた紙面色。
    #   相手のテーマが #000000/#ffffff でも可読性を優先して保つ（文字サイズを合わせないのと同じ理由）。
    #   2026-08-21 利用者「121212はまさにそのために設定した」
    #   根拠=.kiro/steering/slide-contract-detail.md のカラートークン表
    keep = {
        TOKENS['ink']: {'theirs': ink, 'why': '純黒は読みにくい。本文色は #121212 を保つ'},
        TOKENS['paper']: {'theirs': paper, 'why': '純白は目が疲れる。紙面は #fafafa を保つ'},
    }
    return out, keep


def apply_format(html_path, data, out_path=None):
    """デッキのHTMLへ book の対応表を当てる（トークン色 → 相手の色）。

    data属性とinline styleの両方に同じ置換をかける（片方だけ変えるとPPTXでずれる）。
    相手の色はカタログ外なので <html data-palette="custom"> を宣言する。
    """
    with open(html_path, encoding='utf-8') as f:
        text = f.read()
    mp = data.get('map') or {}
    if not mp:
        return None, 0
    n = 0
    for tok, col in mp.items():
        if not col or tok.lower() == col.lower():
            continue
        pat = re.compile(re.escape(tok) + r'(?![0-9a-fA-F])', re.I)
        text, k = pat.subn(col, text)
        n += k
    if 'data-palette=' not in text:
        text = re.sub(r'<html(\s|>)', r'<html data-palette="custom"\1', text, count=1)
    fonts = [f for f in (data.get('fonts') or []) if not f.startswith('+')]
    if fonts:
        text = re.sub(r"(body\s*\{[^}]*font-family\s*:\s*)([^;}]+)",
                      lambda m: m.group(1) + f"'{fonts[0]}'," + m.group(2), text, count=1)
    out = out_path or re.sub(r'\.html?$', '', html_path) + '.formatted.html'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pptx')
    ap.add_argument('-o', '--out')
    ap.add_argument('--apply', metavar='DECK.html',
                    help='抽出した書式を既存デッキへ当てて <deck>.formatted.html を書く')
    args = ap.parse_args()
    src = os.path.abspath(args.pptx)
    if not os.path.exists(src):
        print(f'見つからない: {src}')
        return 1
    prs = Presentation(src)
    theme = theme_colors(prs)
    area, fonts, sizes, xs, title_tops, body_tops = collect(prs)
    size_list = sorted(sizes)
    body = max(sizes, key=lambda k: sizes[k]) if sizes else None  # 字数が最も多いサイズ＝本文
    data = {
        'label': os.path.splitext(os.path.basename(src))[0],
        'source': os.path.relpath(src, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'slides': len(prs.slides._sldIdLst),
        'theme': theme,
        'used': [[h, n] for h, n in area.most_common(12)],
        'fonts': [f for f, _ in fonts.most_common(3)],
        'sizes': {'title': (size_list[-1] if size_list else None), 'body': body,
                  'min': (size_list[0] if size_list else None), 'all': size_list[:14]},
        'layout': {'marginLeft': (min(xs) if xs else None),
                   'titleTop': (title_tops.most_common(1)[0][0] if title_tops else None),
                   'bodyTop': (body_tops.most_common(1)[0][0] if body_tops else None)},
    }
    data['map'], data['keep'] = build_map(area, theme)
    out = os.path.abspath(args.out) if args.out else re.sub(r'\.pptx$', '.format.json', src, flags=re.I)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'書式を抽出: {out}（{data["slides"]}枚）')
    print(f'  フォント: {data["fonts"] or "指定なし（テーマ既定）"}')
    s = data['sizes']
    print(f'  文字サイズ: 本文{s["body"]}px / 見出し{s["title"]}px / 最小{s["min"]}px'
          + ('  🔴 15px未満がある＝そのまま真似るとPPTXで読めない' if s['min'] and s['min'] < 15 else ''))
    print(f'  余白: 左{data["layout"]["marginLeft"]}px / タイトル上端{data["layout"]["titleTop"]}px'
          f' / 本文上端{data["layout"]["bodyTop"]}px')
    print('  トークンの当てはめ（左=SlideKit／右=相手の色。おかしければjsonを手で直す）:')
    inv = {v: k for k, v in TOKENS.items()}
    for tk, col in data['map'].items():
        print(f'    {inv.get(tk, tk):<7} {tk} → {col}')
    print('  合わせないもの（可読性のために選んだ値なので相手に寄せない）:')
    for tk, d in (data.get('keep') or {}).items():
        print(f'    {inv.get(tk, tk):<7} {tk} ← 相手は {d["theirs"]}　{d["why"]}')
    if s['min'] and s['min'] < 15:
        print(f'    文字    下限15px（本文19px）← 相手は {s["min"]}px　小さすぎて読めなくなる')
    if args.apply:
        deck = os.path.abspath(args.apply)
        if not os.path.exists(deck):
            print(f'  デッキが見つからない: {deck}')
            return 1
        made, n = apply_format(deck, data)
        print(f'  書式を当てた: {made}（色を{n}箇所置換）')
        print('  そのまま python3 SlideKit/slidecheck.py で検査できる')
    else:
        print('  使い方: 型は pattern-select.md から選んでデッキを作り、'
              f'\n    python3 SlideKit/pptx_to_format.py {os.path.basename(src)} --apply <deck>.html'
              '\n  で色を当てる。相手の色はカタログ外なので data-palette="custom" が自動で付く')
    return 0


if __name__ == '__main__':
    sys.exit(main())
