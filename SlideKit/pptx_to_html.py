#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""他人の PPTX を SlideKit 形式の HTML（雛形の作法）に逆取り込みする。

    python3 SlideKit/pptx_to_html.py 入力.pptx 出力.html
    python3 SlideKit/pptx_to_html.py 入力.pptx                 # → 入力.html
    python3 SlideKit/pptx_to_html.py 入力.pptx 出力.html --slides=1,5-8

出力は slide-template.html と同じ作法：
    - 1280×720px の .slide div が縦に並ぶ
    - 位置・大きさ・色などは data-* 属性の絶対座標（PPTX 互換の範囲の CSS だけ）
    - 画像は出力 HTML の隣に images/ を作って書き出し、<img> で参照
    - 発表者ノートは .slide の data-notes 属性に入れる（html_to_pptx がそのまま PPTX ノートへ戻せる）
    - slide-edit.js / slide-present.js / slide-presenter.js を読み込むので開けば即編集・再生できる

変換する要素：スライドサイズ・背景色・文字枠（位置/大きさ/文字/サイズ/太字/色/箇条書き）・
画像・表（行列と文字・セル色）・基本図形（矩形/楕円/三角/角丸/線/矢印の形と色）。
グループは展開して絶対座標化。SmartArt・グラフなど画像化できないものは枠だけ置き、
ページ下部の目立たない注記に「変換できなかった要素」として件数を出す。

逆取り込みの中身（色解決・座標・図形逆マップ・段落組み立て）は pptx_to_slidekit.py を
そのまま使う（二重管理しない）。この薄い層が images/ フォルダ・ノート・注記を足している。
"""

import os
import sys
import shutil
import argparse
import html as html_lib
from collections import Counter

from pptx import Presentation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pptx_to_slidekit as p2s
from pptx_to_slidekit import (
    ThemeResolver, qn, SK_W, SK_H,
    _shapes_from_tree, _extract_bg_hex,
)


# ---- 発表者ノート ----

def _get_notes(slide):
    """スライドのノート本文を返す（無ければ None）。"""
    try:
        if slide.has_notes_slide:
            txt = slide.notes_slide.notes_text_frame.text
            return txt.strip() or None
    except Exception:
        return None
    return None


def _attr(s):
    """data 属性値用にエスケープ。改行はリテラル \\n にして属性を1行に収める
    （html_to_pptx は data-notes の \\n を実改行に戻すので PPTX ノートへ往復できる）。"""
    return html_lib.escape(s, quote=True).replace('\r', '').replace('\n', '\\n')


# ---- 変換できなかった要素（SmartArt・グラフ・OLE など）----

def _collect_unconverted(root_el):
    """スライドの shape ツリーを歩いて、表でない graphicFrame を数える。
    SmartArt / グラフ / OLE は pptx_to_slidekit が灰色の枠だけで描くので、
    ここで種類を拾ってページ下部の注記に出す。"""
    labels = []
    cSld = root_el.find(qn('p:cSld'))
    spTree = cSld.find(qn('p:spTree')) if cSld is not None else None
    if spTree is None:
        return labels

    def walk(el):
        for ch in el:
            if ch.tag == qn('p:grpSp'):
                walk(ch)
            elif ch.tag == qn('p:graphicFrame'):
                gd = ch.find('.//' + qn('a:graphicData'))
                uri = (gd.get('uri') if gd is not None else '') or ''
                if 'table' in uri:
                    continue  # 表は変換済み
                if 'chart' in uri:
                    labels.append('グラフ')
                elif 'diagram' in uri:
                    labels.append('SmartArt')
                elif 'ole' in uri:
                    labels.append('OLE オブジェクト')
                else:
                    labels.append('図')

    walk(spTree)
    return labels


def _footnote_html(labels):
    c = Counter(labels)
    body = '、'.join(f'{k}{v}件' for k, v in c.items())
    txt = f'変換できなかった要素: {body}（枠だけ置いています）'
    esc = html_lib.escape(txt)
    return [
        f'    <div class="tb" data-x="64" data-y="692" data-w="1152" data-h="22"',
        f'         data-font-size="11" data-color="#9aa3ad"',
        f'         style="left:64px;top:692px;width:1152px;height:22px;font-size:11px;color:#9aa3ad">{esc}</div>',
    ]


# ---- スライド1枚 ----

def slide_to_html(slide, slide_idx, orig_w_emu, orig_h_emu, theme, media_dir, media_map):
    layout = slide.slide_layout
    master = layout.slide_master
    bg_hex = (_extract_bg_hex(slide.element, theme)
              or _extract_bg_hex(layout.element, theme)
              or _extract_bg_hex(master.element, theme))
    notes = _get_notes(slide)

    attrs = ''
    if bg_hex:
        attrs += f' data-bg="{bg_hex}"'
    if notes:
        attrs += f' data-notes="{_attr(notes)}"'
    slide_style = f'background:{bg_hex}' if bg_hex else 'background:#fff'

    lines = [
        f'  <!-- SLIDE {slide_idx} -->',
        f'  <div class="slide"{attrs} style="{slide_style}">',
    ]
    # マスター（背面）→ レイアウト → スライド本体（前面）
    lines.extend(_shapes_from_tree(master.element, orig_w_emu, orig_h_emu, theme,
                                   media_dir, media_map, master.part, skip_placeholders=True))
    lines.extend(_shapes_from_tree(layout.element, orig_w_emu, orig_h_emu, theme,
                                   media_dir, media_map, layout.part, skip_placeholders=True))
    lines.extend(_shapes_from_tree(slide.element, orig_w_emu, orig_h_emu, theme,
                                   media_dir, media_map, slide.part, skip_placeholders=False))

    unconv = _collect_unconverted(slide.element)
    if unconv:
        lines.extend(_footnote_html(unconv))

    lines.append('  </div>')
    return '\n'.join(lines)


# ---- 全体 ----

_STYLE = """*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Meiryo UI','Yu Gothic','游ゴシック','Noto Sans JP',sans-serif;background:#3a4756;display:flex;flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;box-shadow:0 4px 24px rgba(0,0,0,.2)}
.tb{position:absolute;overflow:hidden;line-height:1.5}
.rect{position:absolute;display:flex;flex-direction:column;justify-content:center;align-items:center}
.rect>.tb{position:static;left:auto;top:auto;width:auto;height:auto;padding:3px;overflow:visible}
.rect>.tb:not([data-align]){text-align:center}
.rect>.tb[data-align="left"],.rect>.tb[data-align="right"]{align-self:stretch}
.flow{position:absolute;display:flex;flex-direction:column;justify-content:flex-start;border-radius:8px}
.flow>.tb{position:static;left:auto;top:auto;width:auto;height:auto;padding:3px;overflow:visible}"""


def convert(src_path, out_path, slides_filter=None):
    prs = Presentation(src_path)
    orig_w, orig_h = prs.slide_width, prs.slide_height
    theme = ThemeResolver(prs)

    out_path = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_path)
    media_dir = os.path.join(out_dir, 'images')
    if os.path.exists(media_dir):
        shutil.rmtree(media_dir)
    media_map = {}

    slides_all = list(prs.slides)
    total = len(slides_all)
    indices = (p2s._parse_slides_filter(slides_filter, total) if slides_filter
               else list(range(1, total + 1)))

    print(f'元スライド: {total}枚 / {orig_w/914400:.2f}" × {orig_h/914400:.2f}"')
    print(f'変換対象: {len(indices)}枚')

    slide_htmls = []
    for i in indices:
        slide_htmls.append(slide_to_html(slides_all[i-1], i, orig_w, orig_h,
                                         theme, media_dir, media_map))
        print(f'  ✓ S{i:02d}')

    sk_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        sk_rel = os.path.relpath(sk_dir, out_dir)
    except ValueError:
        sk_rel = '../SlideKit'

    # data-palette="custom"（2026-11-15）: 取り込んだ PPTX の色はカタログ外が当たり前（顧客色・PowerPoint の既定の灰）。
    #   宣言が無いと、この HTML を html_to_pptx.py に戻した時に slide-guard の B2 が停止級で止め、往復できなかった。
    #   宣言しても色の違反は警告として一覧に残る（見落とさない）。
    full = f'''<!DOCTYPE html>
<html lang="ja" data-palette="custom">
<head>
<meta charset="utf-8">
<title>{html_lib.escape(os.path.basename(src_path))}（SlideKit 取り込み）</title>
<style>
{_STYLE}
</style>
</head>
<body>

{chr(10).join(slide_htmls)}

<script src="{sk_rel}/slide-edit.js"></script>
<script src="{sk_rel}/slide-present.js"></script>
<script src="{sk_rel}/slide-presenter.js"></script>
</body>
</html>
'''
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full)

    n_img = len(media_map)
    print(f'\n✅ 出力: {out_path}')
    if n_img:
        print(f'   画像 {n_img}枚 → {media_dir}')
    print(f'   ブラウザで開けば編集・再生できます（右上 ✏️）')
    return out_path


def main():
    ap = argparse.ArgumentParser(description='PPTX を SlideKit 形式の HTML に逆取り込みする')
    ap.add_argument('source', help='元 PPTX')
    ap.add_argument('output', nargs='?', help='出力 HTML（省略時 source.html）')
    ap.add_argument('--slides', help='対象スライド指定 例 "1,3,5-8"')
    args = ap.parse_args()

    out = args.output or (os.path.splitext(args.source)[0] + '.html')
    try:
        convert(args.source, out, slides_filter=args.slides)
    except Exception as e:
        print(f'❌ エラー: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
