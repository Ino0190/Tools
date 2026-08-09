#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PPTX を SlideKit 形式の HTML に変換する。

出力:
    - 単一 HTML ファイル（1280×720px の .slide が並ぶ）
    - 画像は隣に `<出力名>_media/` フォルダを作って書き出し
    - SlideKit の slide-edit.js を読み込むので、ブラウザで開けば即編集できる

対応要素:
    - PLACEHOLDER / TEXT_BOX → .tb (文字色/フォントサイズ/太字/文字揃え/塗り)
    - AUTO_SHAPE (rectangle / oval / triangle / rounded rect 等) → .rect
    - PICTURE → <img> + ラッパー div
    - LINE / CONNECTOR → .rect data-shape=line
    - TABLE → <table> (colspan/rowspan/セル色/文字揃え)
    - GROUP → 展開して絶対座標化
    - FREEFORM / 未対応 shape → 灰色のプレースホルダー .rect + 注記

使い方:
    python3 SlideKit/pptx_to_slidekit.py source.pptx                     # → source.html
    python3 SlideKit/pptx_to_slidekit.py source.pptx out.html
    python3 SlideKit/pptx_to_slidekit.py source.pptx --slides=1,5-8      # 指定スライドだけ
"""

import os
import sys
import re
import argparse
import shutil
import colorsys
import html as html_lib
from lxml import etree
from pptx import Presentation
from pptx.util import Emu
from pptx.enum.shapes import MSO_SHAPE_TYPE, MSO_SHAPE

# 図形逆マッピングの正本は slidekit-defs.js (shapes)。html_to_pptx.load_defs を再利用して
# defs を1箇所で読む (v2 の二重管理解消)。読めない場合は下の互換フォールバックで v1 同値になる。
try:
    from html_to_pptx import load_defs as _load_defs
except Exception:
    def _load_defs():
        return None

# --- namespaces ---
NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
def qn(pl):
    p, l = pl.split(':')
    return '{%s}%s' % (NS[p], l)

# SlideKit 標準サイズ
SK_W = 1280
SK_H = 720


def _build_reverse_shape_map():
    """OOXML preset geometry (prst) → SlideKit data-shape の逆マップを返す。

    canonical 分は slidekit-defs.js (shapes.*.mso) の MSO 名を python-pptx の
    prst 文字列 (xml_value) に変換して導出する = 図形を1種 defs に足せばここも自動追従する。
    v1 が持っていた互換 (円は data-shape='oval' 表記 / OOXML 別名 rtTriangle・chevron・pentagon /
    defs mso 名が現行 python-pptx に無い綴りのケース) は setdefault で上乗せして挙動保存する。
    defs が読めない場合も、この上乗せ分だけで v1 と同一の逆マップになる (defs 欠落耐性)。"""
    label = {'circle': 'oval'}  # v1 は楕円を data-shape='oval' で出力
    m = {}
    try:
        defs = _load_defs()
    except Exception:
        defs = None
    shapes = defs.get('shapes', {}) if isinstance(defs, dict) else {}
    for key, sd in shapes.items():
        mso = sd.get('mso') if isinstance(sd, dict) else None
        if not mso:
            continue  # line 等 (mso=null) は逆引き対象外 (v1 も line は別処理)
        try:
            prst = getattr(MSO_SHAPE, mso).xml_value
        except Exception:
            continue  # 現行 python-pptx に無い mso 名 (例: ISOCELES 綴り) は下の互換で補う
        m[prst] = label.get(key, key)
    # v1 互換の上乗せ (= v1 の if/elif と同一。defs 由来キーは上書きしない)
    for prst, ds in (('ellipse', 'oval'), ('triangle', 'triangle'), ('rtTriangle', 'triangle'),
                     ('rightArrow', 'arrow'), ('homePlate', 'chevron'),
                     ('chevron', 'chevron'), ('pentagon', 'chevron')):
        m.setdefault(prst, ds)
    return m


_REVERSE_SHAPE_MAP = _build_reverse_shape_map()

# EMU 変換
def emu_to_px_x(emu, orig_w_emu):
    return int(round(emu * SK_W / orig_w_emu))
def emu_to_px_y(emu, orig_h_emu):
    return int(round(emu * SK_H / orig_h_emu))
def emu_pt_to_px(sz_100, orig_w_emu):
    """rPr sz は 1/100 pt。1pt = 96/72 px。フォントは横スケール倍率を使う（縦横比は元PPTXに依存）。"""
    pt = sz_100 / 100.0
    # SlideKit は 96dpi 相当なので pt を px にすると 1.333 倍
    return round(pt * 96 / 72, 1)


# ---- カラー解決 ----

class ThemeResolver:
    """theme.xml から色マップを作る。schemeClr の val を hex に変換する。"""
    def __init__(self, prs):
        self.color_map = {}   # {'accent1': '#hex', ...}
        try:
            master = prs.slide_masters[0]
            theme_el = master.element.getparent()
            # PPTX 内の theme.xml を探す
            for master in prs.slide_masters:
                # python-pptx はマスターのテーマパートを直接 expose しない → part 経由で読む
                for rel in master.part.rels.values():
                    if 'theme' in rel.reltype:
                        theme_xml = rel.target_part.blob
                        self._parse_theme(theme_xml)
                        break
        except Exception:
            pass

    def _parse_theme(self, theme_xml_bytes):
        try:
            root = etree.fromstring(theme_xml_bytes)
        except Exception:
            return
        # clrScheme の子を舐める
        for clrScheme in root.iter(qn('a:clrScheme')):
            for child in clrScheme:
                # 子: dk1, lt1, dk2, lt2, accent1-6, hlink, folHlink
                # {a}dk1 → 'dk1'
                tag_local = etree.QName(child).localname
                # 子の中: srgbClr / sysClr
                srgb = child.find(qn('a:srgbClr'))
                sys = child.find(qn('a:sysClr'))
                hex_val = None
                if srgb is not None:
                    hex_val = '#' + srgb.get('val').lower()
                elif sys is not None:
                    last = sys.get('lastClr')
                    if last:
                        hex_val = '#' + last.lower()
                if hex_val:
                    self.color_map[tag_local] = hex_val
                    # PPTX の schemeClr val は 'tx1' / 'bg1' / 'accent1' などにマッピングされる
                    # tx1 = dk1, bg1 = lt1, tx2 = dk2, bg2 = lt2
        # マッピング補正
        aliases = {'tx1':'dk1', 'bg1':'lt1', 'tx2':'dk2', 'bg2':'lt2'}
        for k, v in aliases.items():
            if v in self.color_map and k not in self.color_map:
                self.color_map[k] = self.color_map[v]

    def resolve(self, elem, default='#333333'):
        """<a:solidFill> / <a:srgbClr> / <a:schemeClr> を含む elem を解決して hex を返す。
        srgbClr / schemeClr の子として lumMod / lumOff / shade / tint / alpha があれば
        HSL 変換で色に反映する（PPTXの色パレット合成に必須）。
        """
        if elem is None:
            return default
        # 最も内側の色要素を探す
        srgb = elem.find('.//' + qn('a:srgbClr'))
        sch = elem.find('.//' + qn('a:schemeClr'))
        color_elem = None
        base_hex = None
        if srgb is not None:
            base_hex = '#' + srgb.get('val', '').lower()
            color_elem = srgb
        elif sch is not None:
            key = sch.get('val')
            if key and key in self.color_map:
                base_hex = self.color_map[key]
                color_elem = sch
        if base_hex is None:
            return default
        # 修飾子を子要素から取得
        return apply_color_mods(base_hex, color_elem)


def apply_color_mods(base_hex, color_elem):
    """color_elem の子 <a:lumMod>/<a:lumOff>/<a:shade>/<a:tint>/<a:satMod> を適用して hex を返す。
    ECMA-376 の準拠は完全ではないが、実用上ほぼ一致する近似を使う。
    """
    if not base_hex.startswith('#') or len(base_hex) < 7:
        return base_hex
    r = int(base_hex[1:3], 16) / 255.0
    g = int(base_hex[3:5], 16) / 255.0
    b = int(base_hex[5:7], 16) / 255.0

    # 修飾値を収集
    def _val(child, tag):
        e = child.find(qn(tag))
        if e is not None:
            v = e.get('val')
            if v:
                try: return int(v) / 100000.0
                except: return None
        return None

    lum_mod = _val(color_elem, 'a:lumMod')
    lum_off = _val(color_elem, 'a:lumOff')
    shade   = _val(color_elem, 'a:shade')
    tint    = _val(color_elem, 'a:tint')
    sat_mod = _val(color_elem, 'a:satMod')

    # HSL でルミナンス操作
    if lum_mod is not None or lum_off is not None or sat_mod is not None:
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        if lum_mod is not None:
            l = l * lum_mod
        if lum_off is not None:
            l = min(1.0, l + lum_off)
        if sat_mod is not None:
            s = min(1.0, s * sat_mod)
        r, g, b = colorsys.hls_to_rgb(h, l, s)

    # shade: RGB * val (黒に近づける)
    if shade is not None:
        r *= shade; g *= shade; b *= shade

    # tint: RGB + (1 - RGB) * (1 - val)  (白に近づける)
    if tint is not None:
        r = r + (1 - r) * (1 - tint)
        g = g + (1 - g) * (1 - tint)
        b = b + (1 - b) * (1 - tint)

    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    return '#{:02x}{:02x}{:02x}'.format(int(round(r*255)), int(round(g*255)), int(round(b*255)))


def _html_escape(s):
    return html_lib.escape(s or '', quote=True)


# ---- 座標抽出（groupの累積変換対応） ----

def get_xfrm(sp_el):
    """shape 要素の xfrm から (x, y, cx, cy, rot) を取り出す（EMU）。取れなければ None。"""
    # p:sp/p:spPr/a:xfrm, p:pic/p:spPr/a:xfrm, p:grpSp/p:grpSpPr/a:xfrm
    for spPr_tag in ('p:spPr', 'p:grpSpPr'):
        spPr = sp_el.find(qn(spPr_tag))
        if spPr is not None:
            xfrm = spPr.find(qn('a:xfrm'))
            if xfrm is not None:
                off = xfrm.find(qn('a:off'))
                ext = xfrm.find(qn('a:ext'))
                if off is not None and ext is not None:
                    x = int(off.get('x', 0)); y = int(off.get('y', 0))
                    cx = int(ext.get('cx', 0)); cy = int(ext.get('cy', 0))
                    rot = int(xfrm.get('rot', 0)) / 60000  # 度
                    # group の場合、chOff/chExt もある
                    chOff = xfrm.find(qn('a:chOff'))
                    chExt = xfrm.find(qn('a:chExt'))
                    ch_x = int(chOff.get('x', 0)) if chOff is not None else 0
                    ch_y = int(chOff.get('y', 0)) if chOff is not None else 0
                    ch_cx = int(chExt.get('cx', cx)) if chExt is not None else cx
                    ch_cy = int(chExt.get('cy', cy)) if chExt is not None else cy
                    return {
                        'x':x,'y':y,'cx':cx,'cy':cy,'rot':rot,
                        'ch_x':ch_x,'ch_y':ch_y,'ch_cx':ch_cx,'ch_cy':ch_cy,
                    }
    # graphicFrame (表) の xfrm は p:xfrm 直下
    xfrm = sp_el.find(qn('p:xfrm'))
    if xfrm is not None:
        off = xfrm.find(qn('a:off'))
        ext = xfrm.find(qn('a:ext'))
        if off is not None and ext is not None:
            return {
                'x': int(off.get('x', 0)), 'y': int(off.get('y', 0)),
                'cx': int(ext.get('cx', 0)), 'cy': int(ext.get('cy', 0)),
                'rot': 0, 'ch_x':0, 'ch_y':0, 'ch_cx':int(ext.get('cx',0)), 'ch_cy':int(ext.get('cy',0)),
            }
    return None


def transform_by_group(x, y, cx, cy, grp_xfrm):
    """group の xfrm を子座標に適用する。
    子座標(x,y) は group の ch座標系 (chOff, chExt)。
    実座標 = grp.off + (子座標 - grp.chOff) * (grp.ext / grp.chExt)
    """
    if grp_xfrm['ch_cx'] == 0 or grp_xfrm['ch_cy'] == 0:
        # スケーリング無し・オフセットだけ
        return x + grp_xfrm['x'], y + grp_xfrm['y'], cx, cy
    sx = grp_xfrm['cx'] / grp_xfrm['ch_cx']
    sy = grp_xfrm['cy'] / grp_xfrm['ch_cy']
    new_x = grp_xfrm['x'] + int((x - grp_xfrm['ch_x']) * sx)
    new_y = grp_xfrm['y'] + int((y - grp_xfrm['ch_y']) * sy)
    new_cx = int(cx * sx)
    new_cy = int(cy * sy)
    return new_x, new_y, new_cx, new_cy


# ---- shape ごとの HTML 生成 ----

def sp_get_fill_hex(sp_el, theme):
    """shape の solidFill を hex で返す。なければ None (透明扱い)。"""
    spPr = sp_el.find(qn('p:spPr'))
    if spPr is None:
        return None
    # noFill 明示
    if spPr.find(qn('a:noFill')) is not None:
        return None
    solid = spPr.find(qn('a:solidFill'))
    if solid is not None:
        return theme.resolve(solid, default=None)
    # gradFill / blipFill などは未対応（今は無視）
    return None


def sp_get_line(sp_el, theme):
    """shape の a:ln から (width_px, color_hex) を返す。線なしなら None。"""
    spPr = sp_el.find(qn('p:spPr'))
    if spPr is None:
        return None
    ln = spPr.find(qn('a:ln'))
    if ln is None:
        return None
    # 明示的な noFill
    if ln.find(qn('a:noFill')) is not None:
        return None
    solid = ln.find(qn('a:solidFill'))
    if solid is None:
        return None
    color = theme.resolve(solid, default=None)
    if color is None:
        return None
    # 幅（EMU）→ px。1pt = 12700 EMU, 1pt ≒ 1.33px
    w_emu = ln.get('w')
    try:
        w_px = max(1, round(int(w_emu) / 12700 * 96 / 72)) if w_emu else 1
    except ValueError:
        w_px = 1
    return (w_px, color)


def sp_get_prst_shape(sp_el):
    """AUTO_SHAPE の prstGeom prst 名を返す（rect / roundRect / ellipse など）。"""
    spPr = sp_el.find(qn('p:spPr'))
    if spPr is None:
        return None
    prst = spPr.find(qn('a:prstGeom'))
    if prst is not None:
        return prst.get('prst')
    return None


def build_paragraphs_html(txBody_el, theme, default_color='#333333', default_size_px=18):
    """<a:txBody> から HTML の innerHTML を作る。
    段落ごとに buChar / buAutoNum を検出して先頭にマーカーを追加。
    rPr の u="sng" は下線に変換。
    """
    if txBody_el is None:
        return '', {'size_px': default_size_px, 'align': 'left', 'bold': False,
                     'color': default_color, 'has_bullet': False}
    parts = []
    first_para_meta = None
    saw_bullet = False
    numbered_counter = 0
    for p in txBody_el.findall(qn('a:p')):
        pPr = p.find(qn('a:pPr'))
        align = 'left'
        bullet_char = None
        marL = 0
        indent = 0
        is_numbered = False
        if pPr is not None:
            algn = pPr.get('algn')
            if algn == 'ctr': align = 'center'
            elif algn == 'r': align = 'right'
            elif algn == 'just': align = 'justify'
            try: marL = int(pPr.get('marL', '0'))
            except: pass
            try: indent = int(pPr.get('indent', '0'))
            except: pass
            # bullet 検出
            buChar = pPr.find(qn('a:buChar'))
            buAutoNum = pPr.find(qn('a:buAutoNum'))
            buNone = pPr.find(qn('a:buNone'))
            buFont = pPr.find(qn('a:buFont'))
            if buNone is not None:
                bullet_char = None
            elif buChar is not None:
                raw = buChar.get('char') or '•'
                # Wingdings / Symbol / Webdings 系フォントは記号を Unicode に翻訳
                font_name = (buFont.get('typeface') if buFont is not None else '') or ''
                fn_lower = font_name.lower()
                if any(x in fn_lower for x in ('wingdings', 'webdings', 'symbol')):
                    # Wingdings コード → Unicode 概略対応
                    _wingdings_map = {
                        'l': '●', 'n': '■', 'u': '◆', 'p': '❖', 'v': '❖',
                        '\uf0a7': '■', '\uf0b7': '●', '\uf0d8': '➢',
                        '¡': '●',  # Symbol
                    }
                    bullet_char = _wingdings_map.get(raw, '•')
                else:
                    bullet_char = raw
                saw_bullet = True
            elif buAutoNum is not None:
                is_numbered = True
                saw_bullet = True
                numbered_counter += 1
                # 番号スタイル（簡易）
                num_type = buAutoNum.get('type', 'arabicPeriod')
                if 'Period' in num_type:
                    bullet_char = f'{numbered_counter}.'
                else:
                    bullet_char = f'{numbered_counter})'
        para_texts = []
        para_size_px = default_size_px
        para_bold = False
        para_color = default_color
        for r in p.findall(qn('a:r')):
            rPr = r.find(qn('a:rPr'))
            t = r.find(qn('a:t'))
            text = t.text if (t is not None and t.text) else ''
            if not text:
                continue
            # 属性抽出
            b = False; sz_px = default_size_px; col = default_color; underline = False; italic = False
            if rPr is not None:
                if rPr.get('b') == '1': b = True
                if rPr.get('i') == '1': italic = True
                if rPr.get('u') and rPr.get('u') not in ('none',): underline = True
                sz = rPr.get('sz')
                if sz:
                    try: sz_px = emu_pt_to_px(int(sz), 1)
                    except ValueError: pass
                # 色 (a:solidFill 直下)
                sf = rPr.find(qn('a:solidFill'))
                if sf is not None:
                    col = theme.resolve(sf, default=default_color) or default_color
            # 段落の代表値（最初の run から）
            if not para_texts:
                para_size_px = sz_px
                para_bold = b
                para_color = col
            # HTML span
            span_style = []
            if b: span_style.append('font-weight:700')
            if italic: span_style.append('font-style:italic')
            if underline: span_style.append('text-decoration:underline')
            if sz_px != default_size_px: span_style.append(f'font-size:{sz_px}px')
            if col and col != default_color: span_style.append(f'color:{col}')
            span_style_str = ';'.join(span_style)
            escaped = _html_escape(text).replace('\n', '<br>')
            if span_style_str:
                para_texts.append(f'<span style="{span_style_str}">{escaped}</span>')
            else:
                para_texts.append(escaped)
        # a:fld や defRPr フォールバック
        if not para_texts:
            for fld in p.findall(qn('a:fld')):
                t = fld.find(qn('a:t'))
                if t is not None and t.text:
                    para_texts.append(_html_escape(t.text))
        # 段落ラップ（bullet 付き＋インデント）
        if para_texts or bullet_char:
            content = "".join(para_texts)
            if bullet_char:
                # 「•本文」形式で組む。左マージン = marL / 12700 pt ≒ px、字下げは text-indent で
                # 実際は「マーカー＋半角空白＋本文」の hanging indent
                marL_px = round(marL / 12700 * 96 / 72) if marL else 0
                marker = _html_escape(bullet_char)
                content = f'<span style="display:inline-block;width:{max(12, marL_px)}px">{marker}</span>{content}'
            style_parts = []
            if align != 'left': style_parts.append(f'text-align:{align}')
            if bullet_char and marL:
                style_parts.append(f'padding-left:{round(marL / 12700 * 96 / 72)}px')
                style_parts.append(f'text-indent:-{round(marL / 12700 * 96 / 72)}px')
            style_str = ';'.join(style_parts)
            if style_str:
                parts.append(f'<div style="{style_str}">{content}</div>')
            else:
                parts.append(f'<div>{content}</div>')
            if first_para_meta is None:
                first_para_meta = {'size_px': para_size_px, 'align': align,
                                    'bold': para_bold, 'color': para_color,
                                    'has_bullet': bullet_char is not None}
    inner = ''.join(parts) if parts else ''
    meta = first_para_meta or {'size_px': default_size_px, 'align':'left',
                                 'bold': False, 'color': default_color,
                                 'has_bullet': False}
    meta['saw_bullet'] = saw_bullet
    return inner, meta


# ---- shape 変換ロジック ----

def shape_to_html(sp_el, orig_w_emu, orig_h_emu, theme, media_dir, media_map,
                  slide_part, group_xfrms=None):
    """shape 要素を SlideKit HTML 断片(list of str) にする。
    group_xfrms は親 group の xfrm 配列（内側から外側の順）。
    return: list of HTML string
    """
    group_xfrms = group_xfrms or []
    tag = sp_el.tag
    out = []
    if tag == qn('p:grpSp'):
        # group: 子を展開して累積変換
        grp_xfrm = get_xfrm(sp_el)
        if grp_xfrm is None:
            # xfrm 無い group はそのまま子だけ回す
            for child in sp_el:
                if child.tag in (qn('p:sp'), qn('p:pic'), qn('p:grpSp'),
                                 qn('p:graphicFrame'), qn('p:cxnSp')):
                    out.extend(shape_to_html(child, orig_w_emu, orig_h_emu, theme,
                                              media_dir, media_map, slide_part, group_xfrms))
            return out
        for child in sp_el:
            if child.tag in (qn('p:sp'), qn('p:pic'), qn('p:grpSp'),
                             qn('p:graphicFrame'), qn('p:cxnSp')):
                out.extend(shape_to_html(child, orig_w_emu, orig_h_emu, theme,
                                          media_dir, media_map, slide_part,
                                          group_xfrms + [grp_xfrm]))
        return out

    xfrm = get_xfrm(sp_el)
    if xfrm is None:
        return []
    x, y, cx, cy = xfrm['x'], xfrm['y'], xfrm['cx'], xfrm['cy']
    rot = xfrm.get('rot', 0)
    # group 逆順に適用（内側→外側）
    for grp in group_xfrms:
        x, y, cx, cy = transform_by_group(x, y, cx, cy, grp)
    # EMU → px (SlideKit 座標系)
    px = emu_to_px_x(x, orig_w_emu)
    py = emu_to_px_y(y, orig_h_emu)
    pw = emu_to_px_x(cx, orig_w_emu)
    ph = emu_to_px_y(cy, orig_h_emu)

    # 種別ごとに処理
    if tag == qn('p:sp'):
        return _sp_to_html(sp_el, px, py, pw, ph, rot, theme)
    if tag == qn('p:pic'):
        return _pic_to_html(sp_el, px, py, pw, ph, rot, media_dir, media_map, slide_part)
    if tag == qn('p:cxnSp'):
        return _cxn_to_html(sp_el, px, py, pw, ph, theme)
    if tag == qn('p:graphicFrame'):
        return _graphic_to_html(sp_el, px, py, pw, ph, theme)
    return []


def _sp_to_html(sp_el, px, py, pw, ph, rot, theme):
    """p:sp = 通常の shape（AUTO_SHAPE / TEXT_BOX / PLACEHOLDER 兼用）"""
    # 塗り / 枠線
    fill = sp_get_fill_hex(sp_el, theme)
    line = sp_get_line(sp_el, theme)  # (w_px, color) or None
    prst = sp_get_prst_shape(sp_el)
    # テキスト
    txBody = sp_el.find(qn('p:txBody'))
    txt_html, meta = build_paragraphs_html(txBody, theme)

    # PLACEHOLDER / TEXT_BOX の判定
    nvSpPr = sp_el.find(qn('p:nvSpPr'))
    is_txbox = False
    if nvSpPr is not None:
        cNvSpPr = nvSpPr.find(qn('p:cNvSpPr'))
        if cNvSpPr is not None and cNvSpPr.get('txBox') == '1':
            is_txbox = True
        nvPr = nvSpPr.find(qn('p:nvPr'))
        is_ph = (nvPr is not None and nvPr.find(qn('p:ph')) is not None)
    else:
        is_ph = False

    # テキストのみ shape の判定：塗りも枠線も無く shape 種類が rect / なし
    is_text_only = (fill is None and line is None and (prst in (None, 'rect')) and is_txbox)

    if is_text_only or (fill is None and line is None and txt_html):
        # .tb として出す
        size = meta['size_px']
        align = meta['align']
        bold = meta['bold']
        color = meta['color'] or '#333333'
        s = [
            f'    <div class="tb" data-x="{px}" data-y="{py}" data-w="{pw}" data-h="{ph}"',
            f'         data-font-size="{int(size)}" data-color="{color}"',
        ]
        if bold: s.append('         data-bold="1"')
        if align != 'left': s.append(f'         data-align="{align}"')
        if meta.get('saw_bullet'): s.append('         data-bullet="disc"')
        style_parts = [f'left:{px}px', f'top:{py}px', f'width:{pw}px', f'height:{ph}px',
                       f'font-size:{int(size)}px', f'color:{color}']
        if bold: style_parts.append('font-weight:700')
        if align != 'left': style_parts.append(f'text-align:{align}')
        s.append(f'         style="{";".join(style_parts)}">')
        s.append(f'      {txt_html}')
        s.append('    </div>')
        return s

    # .rect として出す（AUTO_SHAPE / 塗りあり or 枠線あり）
    # prst → data-shape は slidekit-defs.js (shapes) 由来の逆マップ (_REVERSE_SHAPE_MAP)。
    data_shape = _REVERSE_SHAPE_MAP.get(prst)

    fill_str = fill if fill else 'none'
    bg_style = f'background:{fill}' if fill else 'background:transparent'
    s = [
        f'    <div class="rect" data-x="{px}" data-y="{py}" data-w="{pw}" data-h="{ph}"',
        f'         data-fill="{fill_str}"',
    ]
    style_parts = [f'left:{px}px', f'top:{py}px', f'width:{pw}px', f'height:{ph}px', bg_style]
    if line:
        w_px, col = line
        s.append(f'         data-border="{w_px},{col}"')
        style_parts.append(f'border:{w_px}px solid {col}')
    if prst == 'roundRect':
        s.append('         data-radius="8"')
        style_parts.append('border-radius:8px')
    if data_shape:
        s.append(f'         data-shape="{data_shape}"')
    s.append(f'         style="{";".join(style_parts)}">')
    if txt_html:
        size = meta['size_px']
        align = meta['align']
        bold = meta['bold']
        color = meta['color'] or '#333333'
        inner_style_parts = [f'font-size:{int(size)}px', f'color:{color}',
                             f'text-align:{align}', 'padding:4px 12px']
        if bold: inner_style_parts.append('font-weight:700')
        s.append(f'      <div class="tb" data-font-size="{int(size)}" data-color="{color}"'
                 + (' data-bold="1"' if bold else '')
                 + (f' data-align="{align}"' if align != 'left' else '')
                 + (' data-bullet="disc"' if meta.get('saw_bullet') else '')
                 + f' style="{";".join(inner_style_parts)}">')
        s.append(f'        {txt_html}')
        s.append('      </div>')
    s.append('    </div>')
    return s


def _pic_to_html(sp_el, px, py, pw, ph, rot, media_dir, media_map, slide_part):
    """p:pic = 画像。media を書き出して <img> にする。"""
    # blipFill/blip の r:embed → part の blob を書き出し
    blip = sp_el.find('.//' + qn('a:blip'))
    if blip is None:
        return []
    rId = blip.get(qn('r:embed'))
    if not rId:
        return []
    # slide の rels から part を取得
    try:
        image_part = slide_part.rels[rId].target_part
    except Exception:
        return []
    # 拡張子とファイル名
    partname = image_part.partname  # /ppt/media/image1.png
    fname = os.path.basename(str(partname))
    if fname in media_map:
        outname = media_map[fname]
    else:
        outname = fname
        media_map[fname] = outname
        # 書き出し
        os.makedirs(media_dir, exist_ok=True)
        with open(os.path.join(media_dir, outname), 'wb') as f:
            f.write(image_part.blob)
    rel_path = f'{os.path.basename(media_dir)}/{outname}'
    style = f'position:absolute;left:{px}px;top:{py}px;width:{pw}px;height:{ph}px;overflow:hidden'
    return [
        f'    <div data-x="{px}" data-y="{py}" data-w="{pw}" data-h="{ph}"',
        f'         style="{style}">',
        f'      <img src="{rel_path}" style="width:100%;height:100%;object-fit:cover;display:block" alt="">',
        '    </div>',
    ]


def _cxn_to_html(sp_el, px, py, pw, ph, theme):
    """p:cxnSp = 線・矢印コネクタ。"""
    # 線色
    line_el = sp_el.find(qn('p:spPr'))
    color = '#5e5e5e'
    if line_el is not None:
        ln = line_el.find(qn('a:ln'))
        if ln is not None:
            sf = ln.find(qn('a:solidFill'))
            if sf is not None:
                col = theme.resolve(sf, default=None)
                if col: color = col
    # 高さが小さいなら横線、幅が小さいなら縦線
    if ph <= 2 and pw > 2:
        # 横線
        line_h = 2
        style = f'left:{px}px;top:{py}px;width:{pw}px;height:{line_h}px;background:{color}'
    elif pw <= 2 and ph > 2:
        line_w = 2
        style = f'left:{px}px;top:{py}px;width:{line_w}px;height:{ph}px;background:{color}'
    else:
        # 斜め線などは矩形で表現
        style = f'left:{px}px;top:{py}px;width:{pw}px;height:{ph}px;background:{color}'
    return [
        f'    <div class="rect" data-x="{px}" data-y="{py}" data-w="{pw}" data-h="{ph}"',
        f'         data-fill="{color}" data-shape="line"',
        f'         style="{style}"></div>',
    ]


def _graphic_to_html(sp_el, px, py, pw, ph, theme):
    """p:graphicFrame = 表（table）。"""
    tbl = sp_el.find('.//' + qn('a:tbl'))
    if tbl is None:
        # SmartArt / Chart 等は今回未対応
        return _placeholder_html(px, py, pw, ph, '（未対応: SmartArt/Chartなど）')
    # 列幅
    tblGrid = tbl.find(qn('a:tblGrid'))
    col_widths = []
    if tblGrid is not None:
        for c in tblGrid.findall(qn('a:gridCol')):
            w = int(c.get('w', 0))
            col_widths.append(w)
    # 行を舐める
    rows = tbl.findall(qn('a:tr'))
    html_rows = []
    for tr in rows:
        h = int(tr.get('h', 0))
        cells_html = []
        for tc in tr.findall(qn('a:tc')):
            gs = tc.get('gridSpan')
            rs = tc.get('rowSpan')
            attrs = ''
            if gs and int(gs) > 1: attrs += f' colspan="{gs}"'
            if rs and int(rs) > 1: attrs += f' rowspan="{rs}"'
            # merged cell 側は空
            if tc.get('hMerge') == '1' or tc.get('vMerge') == '1':
                continue
            # 塗り
            tcPr = tc.find(qn('a:tcPr'))
            fill_hex = None
            if tcPr is not None:
                sf = tcPr.find(qn('a:solidFill'))
                if sf is not None:
                    fill_hex = theme.resolve(sf, default=None)
            # 縦揃え
            valign = 'middle'
            if tcPr is not None:
                anch = tcPr.get('anchor')
                if anch == 't': valign = 'top'
                elif anch == 'b': valign = 'bottom'
            # テキスト
            txBody = tc.find(qn('a:txBody'))
            inner, meta = build_paragraphs_html(txBody, theme, default_size_px=15)
            style_bits = ['padding:6px 10px', 'border:1px solid #d0d7de']
            if fill_hex: style_bits.append(f'background:{fill_hex}')
            style_bits.append(f'vertical-align:{valign}')
            style_bits.append(f'text-align:{meta["align"]}')
            style_bits.append(f'color:{meta["color"]}')
            style_bits.append(f'font-size:{int(meta["size_px"])}px')
            if meta['bold']: style_bits.append('font-weight:700')
            cells_html.append(f'<td{attrs} style="{";".join(style_bits)}">{inner}</td>')
        row_style = f'height:{emu_to_px_y(h, orig_h_emu=6858000) if h else 30}px' if h else ''
        html_rows.append(f'<tr style="{row_style}">' + ''.join(cells_html) + '</tr>')
    tbl_html = f'<table data-x="{px}" data-y="{py}" data-w="{pw}" style="position:absolute;left:{px}px;top:{py}px;width:{pw}px;border-collapse:collapse;font-family:inherit">'
    tbl_html += ''.join(html_rows)
    tbl_html += '</table>'
    return ['    ' + tbl_html]


def _placeholder_html(px, py, pw, ph, note='未対応 shape'):
    return [
        f'    <div class="rect" data-x="{px}" data-y="{py}" data-w="{pw}" data-h="{ph}"',
        f'         data-fill="#f0f0f0"',
        f'         style="left:{px}px;top:{py}px;width:{pw}px;height:{ph}px;background:#f0f0f0;border:1px dashed #999">',
        f'      <div class="tb" data-font-size="12" data-color="#666" style="font-size:12px;color:#666;padding:4px">{note}</div>',
        '    </div>',
    ]


# ---- スライド単位の HTML 生成 ----

def _extract_bg_hex(root_el, theme):
    """cSld/bg から背景色を取る（solidFill のみ対応）。"""
    cSld = root_el.find(qn('p:cSld'))
    if cSld is None: return None
    bg = cSld.find(qn('p:bg'))
    if bg is None: return None
    bgPr = bg.find(qn('p:bgPr'))
    if bgPr is not None:
        sf = bgPr.find(qn('a:solidFill'))
        if sf is not None:
            return theme.resolve(sf, default=None)
    # bgRef はテーマから解決（スキップ）
    return None


def _shapes_from_tree(root_el, orig_w_emu, orig_h_emu, theme, media_dir, media_map,
                      part, skip_placeholders=False):
    """cSld/spTree の shape を HTML 行列に変換して返す。
    skip_placeholders=True でマスター/レイアウトの placeholder は無視
    （それらはスライド側で個別に上書きされるため）。
    """
    lines = []
    spTree = root_el.find(qn('p:cSld'))
    if spTree is not None:
        spTree = spTree.find(qn('p:spTree'))
    if spTree is None:
        return lines
    for child in spTree:
        if child.tag not in (qn('p:sp'), qn('p:pic'), qn('p:grpSp'),
                             qn('p:graphicFrame'), qn('p:cxnSp')):
            continue
        if skip_placeholders and child.tag == qn('p:sp'):
            nvSpPr = child.find(qn('p:nvSpPr'))
            if nvSpPr is not None:
                nvPr = nvSpPr.find(qn('p:nvPr'))
                if nvPr is not None and nvPr.find(qn('p:ph')) is not None:
                    continue
        try:
            lines.extend(shape_to_html(child, orig_w_emu, orig_h_emu, theme,
                                        media_dir, media_map, part))
        except Exception as e:
            lines.append(f'    <!-- 変換エラー: {e} -->')
    return lines


def slide_to_html(slide, slide_idx, orig_w_emu, orig_h_emu, theme, media_dir, media_map):
    """1 スライドの HTML を生成する。マスター → レイアウト → スライド の順に描画（背面→前面）。"""
    # 背景色: スライド → レイアウト → マスターの順に検索
    layout = slide.slide_layout
    master = layout.slide_master
    bg_hex = (_extract_bg_hex(slide.element, theme)
              or _extract_bg_hex(layout.element, theme)
              or _extract_bg_hex(master.element, theme))
    slide_style = f'background:{bg_hex}' if bg_hex else 'background:#fff'
    lines = [
        f'  <!-- SLIDE {slide_idx} -->',
        f'  <div class="slide"' + (f' data-bg="{bg_hex}"' if bg_hex else '') + f' style="{slide_style}">',
    ]
    # マスター（背面）
    lines.append(f'    <!-- master shapes -->')
    lines.extend(_shapes_from_tree(master.element, orig_w_emu, orig_h_emu, theme,
                                    media_dir, media_map, master.part,
                                    skip_placeholders=True))
    # レイアウト
    lines.append(f'    <!-- layout shapes -->')
    lines.extend(_shapes_from_tree(layout.element, orig_w_emu, orig_h_emu, theme,
                                    media_dir, media_map, layout.part,
                                    skip_placeholders=True))
    # スライド本体（前面）
    lines.append(f'    <!-- slide shapes -->')
    lines.extend(_shapes_from_tree(slide.element, orig_w_emu, orig_h_emu, theme,
                                    media_dir, media_map, slide.part,
                                    skip_placeholders=False))
    lines.append('  </div>')
    return '\n'.join(lines)


def convert(src_path, out_path, slides_filter=None):
    prs = Presentation(src_path)
    orig_w = prs.slide_width
    orig_h = prs.slide_height
    theme = ThemeResolver(prs)

    # media 出力先
    base, ext = os.path.splitext(out_path)
    media_dir = base + '_media'
    if os.path.exists(media_dir):
        shutil.rmtree(media_dir)
    media_map = {}

    slides_all = list(prs.slides)
    total = len(slides_all)
    if slides_filter:
        indices = _parse_slides_filter(slides_filter, total)
    else:
        indices = list(range(1, total+1))

    print(f'元スライド: {total}枚 / {orig_w/914400:.2f}" × {orig_h/914400:.2f}"')
    print(f'変換対象: {len(indices)}枚 ({indices[:5]}{"..." if len(indices)>5 else ""})')
    print(f'メディア出力先: {media_dir}')

    slide_htmls = []
    for i in indices:
        s = slides_all[i-1]
        slide_html = slide_to_html(s, i, orig_w, orig_h, theme, media_dir, media_map)
        slide_htmls.append(slide_html)
        print(f'  ✓ S{i:02d}')

    # SlideKit 相対パス
    # 出力HTMLからSlideKitへの相対パス（SlideKit フォルダは KiroProjects 直下）
    out_dir = os.path.dirname(os.path.abspath(out_path))
    sk_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        sk_rel = os.path.relpath(sk_dir, out_dir)
    except ValueError:
        sk_rel = '../SlideKit'

    # 全体 HTML
    full = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{os.path.basename(src_path)} (SlideKit変換)</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Yu Gothic','Meiryo UI','Noto Sans JP',sans-serif;background:#2d3748;display:flex;flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}}
.slide{{width:{SK_W}px;height:{SK_H}px;position:relative;overflow:hidden;margin:12px 0;box-shadow:0 4px 24px rgba(0,0,0,.2)}}
.tb{{position:absolute;overflow:hidden;line-height:1.5}}
.rect{{position:absolute;display:flex;flex-direction:column;justify-content:center}}
.rect>.tb{{position:static;left:auto;top:auto;width:auto;height:auto;padding:4px 12px;overflow:visible;text-align:center}}
</style>
</head>
<body>
{chr(10).join(slide_htmls)}
<script>
document.querySelectorAll('.slide').forEach((s,i)=>{{
  const n=document.createElement('div');
  n.className='tb';
  n.setAttribute('data-x','1200');n.setAttribute('data-y','688');
  n.setAttribute('data-w','60');n.setAttribute('data-h','24');
  n.setAttribute('data-font-size','21');n.setAttribute('data-color','#718096');
  n.setAttribute('data-align','right');
  n.style.cssText='position:absolute;left:1200px;top:688px;width:60px;height:24px;font-size:21px;color:#718096;text-align:right';
  n.textContent=i+1;
  s.appendChild(n);
}});
</script>
<script src="{sk_rel}/slide-edit.js"></script>
</body>
</html>
'''

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full)
    print(f'\n✅ 出力: {out_path}')
    print(f'   ブラウザで開いて確認 (ワークスペースルートで python3 -m http.server 8138 → http://localhost:8138/{os.path.relpath(out_path, os.getcwd())})')


def _parse_slides_filter(spec, total):
    """"1,3,5-8" → [1,3,5,6,7,8]"""
    out = []
    for tok in spec.split(','):
        tok = tok.strip()
        if not tok: continue
        if '-' in tok:
            a, b = tok.split('-')
            out.extend(range(int(a), int(b)+1))
        else:
            out.append(int(tok))
    return [i for i in out if 1 <= i <= total]


def main():
    ap = argparse.ArgumentParser(description='PPTX を SlideKit HTML に変換')
    ap.add_argument('source', help='元 PPTX')
    ap.add_argument('output', nargs='?', help='出力 HTML (省略時 source.html)')
    ap.add_argument('--slides', help='対象スライド指定 例 "1,3,5-8"')
    args = ap.parse_args()

    src = args.source
    if args.output:
        out = args.output
    else:
        base, ext = os.path.splitext(src)
        out = f'{base}.html'

    try:
        convert(src, out, slides_filter=args.slides)
    except Exception as e:
        print(f'❌ エラー: {e}', file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
