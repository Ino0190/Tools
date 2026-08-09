#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PPTX を A4 縦にリフロー変換するツール（編集可能なまま）。

用途:
    貰い物の PPTX（PowerPoint 等で作られた 16:9 / 4:3 スライド）を、
    A4 縦の配布資料スタイル（1up）に再配置する。
    出力の PPTX は PowerPoint で通常どおり編集できる。

方式:
    - 元 PPTX を開いて slide_width/height を A4 縦に変更
    - 全 slide / master / layout の直下 shape の xfrm (位置・サイズ) と
      全 rPr のフォントサイズ を同一倍率でスケール
    - group shape は外側の xfrm だけスケール（内側は相対座標なので自動追従）
    - relationship や shape XML はそのまま維持 → 書式・色・画像・表・ハイパーリンクを保持

使い方:
    python3 SlideKit/pptx_to_a4.py source.pptx                      # → source_a4.pptx
    python3 SlideKit/pptx_to_a4.py source.pptx out.pptx
    python3 SlideKit/pptx_to_a4.py source.pptx out.pptx --margin=8

制約:
    - アニメーションは静止化（配布資料の性質上問題なし）
    - SmartArt / グラフ / 動画 は shape のスケールだけ動作。内部レンダリングは PowerPoint 側が処理
    - マスターに配置されたロゴ・フッターも同じ倍率でスケールされる（相対位置は保たれる）
"""

import os
import sys
import argparse
from lxml import etree
from pptx import Presentation

# --- namespaces ---
NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
def qn(prefix_local):
    prefix, local = prefix_local.split(':')
    return '{%s}%s' % (NS[prefix], local)

# A4 縦 (mm → EMU): 1mm = 36000 EMU (1 inch = 914400 EMU, 1 inch = 25.4 mm)
EMU_PER_MM = 36000
A4_W_EMU = int(210 * EMU_PER_MM)   # 7560000  ≒ 8.27"
A4_H_EMU = int(297 * EMU_PER_MM)   # 10692000 ≒ 11.69"


# ---- shape スケール ----

def _scale_xfrm_at(elem, scale, off_x, off_y):
    """elem 直下の <a:xfrm> の off/ext だけをスケール。
    子 shape の相対座標は触らない（group の外側 xfrm を変えれば追従する）。"""
    for xfrm in elem.findall('.//' + qn('a:xfrm')):
        # ただし、これは shape 直下限定にしたい。ここでは spPr 直下 or grpSpPr 直下の xfrm のみ対象。
        parent = xfrm.getparent()
        if parent is None: continue
        if parent.tag not in (qn('p:spPr'), qn('p:grpSpPr'), qn('a:graphicFrame')):
            # a:graphicFrame は tbl 用 (実際は p:graphicFrame だが古い名前空間もあり)
            pass
        # off / ext
        off = xfrm.find(qn('a:off'))
        ext = xfrm.find(qn('a:ext'))
        if off is not None:
            x = int(off.get('x', 0))
            y = int(off.get('y', 0))
            off.set('x', str(int(x * scale + off_x)))
            off.set('y', str(int(y * scale + off_y)))
        if ext is not None:
            cx = int(ext.get('cx', 0))
            cy = int(ext.get('cy', 0))
            ext.set('cx', str(max(1, int(cx * scale))))
            ext.set('cy', str(max(1, int(cy * scale))))


def _scale_top_xfrm(shape_el, scale, off_x, off_y):
    """shape の直下 xfrm だけをスケール（group 内の子 xfrm は相対座標なので触らない）。"""
    # shape 直下の spPr / grpSpPr / graphicFrame を探す
    for spPr in shape_el.findall(qn('p:spPr')):
        xfrm = spPr.find(qn('a:xfrm'))
        if xfrm is not None:
            _do_scale_xfrm(xfrm, scale, off_x, off_y)
    for grpSpPr in shape_el.findall(qn('p:grpSpPr')):
        xfrm = grpSpPr.find(qn('a:xfrm'))
        if xfrm is not None:
            # group は off/ext だけでなく chOff/chExt も持つ。
            # chOff/chExt は「子のローカル座標系宣言」なので、外側 off/ext と同じ倍率で拡縮すべき
            _do_scale_xfrm(xfrm, scale, off_x, off_y)
            # chOff/chExt はオフセットは掛けず、スケールだけ
            chOff = xfrm.find(qn('a:chOff'))
            chExt = xfrm.find(qn('a:chExt'))
            # 既存の chOff/chExt はグループ子の相対座標をどう配置するかの宣言。
            # 外側 off/ext とセットで動くもの＝子座標をそのまま使うため、chOff/chExt は元のまま
            # （外側 off/ext の scale が反映されれば、子は自動的に同倍率で表示される）
    # 表 (graphicFrame) の xfrm
    for gf in shape_el.iter(qn('p:graphicFrame')):
        for xfrm in gf.findall(qn('p:xfrm')):
            _do_scale_xfrm(xfrm, scale, off_x, off_y)


def _do_scale_xfrm(xfrm, scale, off_x, off_y):
    off = xfrm.find(qn('a:off'))
    ext = xfrm.find(qn('a:ext'))
    if off is not None:
        x = int(off.get('x', 0))
        y = int(off.get('y', 0))
        off.set('x', str(int(x * scale + off_x)))
        off.set('y', str(int(y * scale + off_y)))
    if ext is not None:
        cx = int(ext.get('cx', 0))
        cy = int(ext.get('cy', 0))
        ext.set('cx', str(max(1, int(cx * scale))))
        ext.set('cy', str(max(1, int(cy * scale))))


def _scale_fonts(shape_el, scale):
    """shape 内の全 rPr / endParaRPr / defRPr のフォントサイズをスケール。"""
    for tag in ('a:rPr', 'a:endParaRPr', 'a:defRPr'):
        for rpr in shape_el.iter(qn(tag)):
            sz = rpr.get('sz')
            if sz:
                try:
                    new_sz = int(int(sz) * scale)
                    # PPTX は 100 = 1pt、下限は 400 (4pt) にしておく
                    if new_sz < 400: new_sz = 400
                    rpr.set('sz', str(new_sz))
                except ValueError:
                    pass


def _scale_line_widths(shape_el, scale):
    """線の太さ (<a:ln w="..."/>) もスケール。"""
    for ln in shape_el.iter(qn('a:ln')):
        w = ln.get('w')
        if w:
            try:
                new_w = int(int(w) * scale)
                if new_w < 1: new_w = 1
                ln.set('w', str(new_w))
            except ValueError:
                pass


def _scale_table_dimensions(shape_el, scale):
    """<a:tbl> 内の列幅 (a:gridCol w) と行高 (a:tr h) をスケール。"""
    for gridCol in shape_el.iter(qn('a:gridCol')):
        w = gridCol.get('w')
        if w:
            try:
                new_w = int(int(w) * scale)
                gridCol.set('w', str(max(1, new_w)))
            except ValueError:
                pass
    for tr in shape_el.iter(qn('a:tr')):
        h = tr.get('h')
        if h:
            try:
                new_h = int(int(h) * scale)
                tr.set('h', str(max(1, new_h)))
            except ValueError:
                pass


def scale_shape_tree(spTree, scale, off_x, off_y):
    """spTree の直接の子 shape (p:sp / p:pic / p:grpSp / p:graphicFrame / p:cxnSp) を対象に、
    xfrm と font と line と table をスケール。"""
    # 直接の子だけ (再帰しない)
    for child in list(spTree):
        tag = child.tag
        if tag in (qn('p:sp'), qn('p:pic'), qn('p:grpSp'),
                   qn('p:graphicFrame'), qn('p:cxnSp')):
            _scale_top_xfrm(child, scale, off_x, off_y)
            _scale_fonts(child, scale)
            _scale_line_widths(child, scale)
            _scale_table_dimensions(child, scale)


# ---- メイン変換処理 ----

def convert_pptx_to_a4(src_path, out_path, margin_mm=10, scale_masters=True):
    """PPTX を A4 縦にリフローして保存する。"""
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    prs = Presentation(src_path)
    orig_w = prs.slide_width
    orig_h = prs.slide_height

    # A4 縦のスロット計算
    margin_emu = int(margin_mm * EMU_PER_MM)
    slot_w = A4_W_EMU - 2 * margin_emu
    slot_h = A4_H_EMU - 2 * margin_emu  # 縦は上端 margin から使えるだけ使う
    # ただし、資料として下部にメモ欄を残すため、縦は「1up」らしく上半分に配置する。
    # → アス比を保ったまま「max width」で fit させ、下は空ける
    scale_x = slot_w / orig_w
    scale_y = slot_h / orig_h
    scale = min(scale_x, scale_y)

    # A4 縦に配置後のスライド実寸
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    off_x = (A4_W_EMU - new_w) // 2
    off_y = margin_emu  # 上端揃え (下がメモ欄になる)

    print(f'元スライドサイズ: {orig_w/914400:.2f}" × {orig_h/914400:.2f}"')
    print(f'A4縦: 8.27" × 11.69" / 余白 {margin_mm}mm')
    print(f'倍率: {scale:.3f}倍 / 配置: x={off_x/914400:.2f}" y={off_y/914400:.2f}" w={new_w/914400:.2f}" h={new_h/914400:.2f}"')
    print(f'スライド数: {len(prs.slides)}')
    print()

    # スライドサイズを A4 縦に変更
    prs.slide_width = A4_W_EMU
    prs.slide_height = A4_H_EMU

    # マスター・レイアウト・スライドの shape をスケール
    if scale_masters:
        # マスター
        for master in prs.slide_masters:
            spTree = master.element.find(qn('p:cSld')).find(qn('p:spTree'))
            if spTree is not None:
                scale_shape_tree(spTree, scale, off_x, off_y)
            # 各レイアウト
            for layout in master.slide_layouts:
                spTree = layout.element.find(qn('p:cSld')).find(qn('p:spTree'))
                if spTree is not None:
                    scale_shape_tree(spTree, scale, off_x, off_y)

    # 各スライドの shape をスケール
    for i, slide in enumerate(prs.slides, 1):
        spTree = slide.element.find(qn('p:cSld')).find(qn('p:spTree'))
        if spTree is not None:
            scale_shape_tree(spTree, scale, off_x, off_y)

    # 保存
    prs.save(out_path)
    print(f'✅ 出力: {out_path}')


def main():
    ap = argparse.ArgumentParser(description='PPTX を A4 縦にリフロー変換 (編集可能なまま)')
    ap.add_argument('source', help='元 PPTX ファイル')
    ap.add_argument('output', nargs='?', help='出力 PPTX (省略時は source_a4.pptx)')
    ap.add_argument('--margin', type=int, default=10, help='A4 の余白 mm (既定: 10)')
    ap.add_argument('--no-scale-masters', action='store_true',
                    help='マスター/レイアウトの shape をスケールしない (背景画像の位置が動く場合の対策)')
    args = ap.parse_args()

    src = args.source
    if args.output:
        out = args.output
    else:
        base, ext = os.path.splitext(src)
        out = f'{base}_a4.pptx'

    try:
        convert_pptx_to_a4(src, out, margin_mm=args.margin,
                           scale_masters=not args.no_scale_masters)
    except Exception as e:
        print(f'❌ エラー: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
