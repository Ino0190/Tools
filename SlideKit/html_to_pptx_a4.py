#!/usr/bin/env python3
"""SlideKit A4 縦 PPTX 出力 (既存 html_to_pptx.py を再利用)

元の 1280x720 HTML スライドを A4 縦 (210×297mm) PPTX に集約して出力する。
既存の html_to_pptx.py の座標変換だけ差し替え、他の描画ロジックはそのまま使う。

使い方:
    python3 html_to_pptx_a4.py <slides.html>                    # 既定 1up
    python3 html_to_pptx_a4.py <slides.html> out.pptx --layout=2up
    python3 html_to_pptx_a4.py <slides.html> --layout=2up

Layout:
    1up: 1 HTML スライド → 1 A4 PPTX ページ (上部に配置、下部は空白でメモ欄に)
    2up: 2 HTML スライド → 1 A4 PPTX ページ (配布資料相当)
"""
import sys
import os
import re
import copy

# 既存の html_to_pptx を再利用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import html_to_pptx as h2p
from pptx import Presentation
from pptx.util import Emu
from bs4 import BeautifulSoup

# A4 縦の EMU 寸法 (210 × 297 mm = 8.27 × 11.69 inches)
A4_W_EMU = 7563168
A4_H_EMU = 10689336

# 元スライドは 1280 × 720 px
SRC_W_PX = 1280
SRC_H_PX = 720

# 元スライドを A4 幅にフィットさせるスケール (1280 px → A4 幅)
# 1 px = 9525 EMU (96 DPI 換算) なので 1280 px = 12,192,000 EMU
# A4 幅 7,563,168 / 12,192,000 = 0.620
SCALE = A4_W_EMU / (SRC_W_PX * 9525)

# 元スライド 1 枚が A4 縦上で占める EMU 高さ
SLOT_H_EMU = int(SRC_H_PX * 9525 * SCALE)

# レイアウト定数 (EMU)
MARGIN_1UP_TOP = 800000     # 1up 時の上余白 (~0.87 inch)
MARGIN_2UP_TOP = 500000     # 2up 時のスライド1 上余白
MARGIN_2UP_GAP = 400000     # 2up スライド1と2の間

# 現在の Y オフセット (処理中のスロットに応じて変わる)
Y_OFFSET_EMU = 0

# 元の px_to_emu_x/y を保持 (何かの時のフォールバック用)
_orig_px_to_emu_x = h2p.px_to_emu_x
_orig_px_to_emu_y = h2p.px_to_emu_y


def px_to_emu_x_a4(px):
    return int(px * 9525 * SCALE)


def px_to_emu_y_a4(px):
    return int(px * 9525 * SCALE) + Y_OFFSET_EMU


def apply_y_offset_to_slide(slide_div, y_offset_px):
    """.slide の子孫要素の data-y / style top を全て +y_offset_px する。
    2up で下スライドを 720+gap px オフセットするために使う。"""
    for el in slide_div.find_all(True):
        # data-y 属性のオフセット
        dy = el.get('data-y')
        if dy:
            try:
                el['data-y'] = str(int(float(dy)) + y_offset_px)
            except (ValueError, TypeError):
                pass
        # inline style の top も同期
        style = el.get('style', '')
        if style:
            def _repl(m):
                try:
                    val = int(float(m.group(1))) + y_offset_px
                    return f'top:{val}px'
                except ValueError:
                    return m.group(0)
            new_style = re.sub(r'top\s*:\s*(\d+(?:\.\d+)?)px', _repl, style)
            if new_style != style:
                el['style'] = new_style


def merge_pairs_for_2up(slides_list, soup, gap_px=40):
    """2枚ずつペアにして 1 枚の "仮想スライド" に統合する。
    上スライドはそのまま、下スライドは Y を (720 + gap) px オフセット。
    背景は上スライドから採用 (下スライドの背景は無視)。"""
    merged = []
    src_h = SRC_H_PX

    for i in range(0, len(slides_list), 2):
        top = slides_list[i]
        # ペア用の新しい .slide を作る (上スライドをディープコピー)
        new_slide = copy.deepcopy(top)

        if i + 1 < len(slides_list):
            bottom = copy.deepcopy(slides_list[i + 1])
            # 下スライドの子要素を新スライドに追加 (Y を +720+gap オフセット)
            offset = src_h + gap_px
            apply_y_offset_to_slide(bottom, offset)
            # 下スライドの子要素だけを移す (bottom 自身の属性は使わない)
            for child in list(bottom.find_all(recursive=False)):
                new_slide.append(child)

        merged.append(new_slide)

    return merged


def parse_args():
    """簡易な CLI 引数パーサ (--layout=1up|2up 対応)"""
    args = sys.argv[1:]
    layout = '1up'
    filtered = []
    for a in args:
        if a == '--layout=2up':
            layout = '2up'
        elif a == '--layout=1up':
            layout = '1up'
        elif a.startswith('--layout='):
            print(f'不正なレイアウト指定: {a} (1up または 2up)')
            sys.exit(1)
        else:
            filtered.append(a)
    return filtered, layout


def main():
    global Y_OFFSET_EMU

    args, layout = parse_args()
    if len(args) < 1:
        print("Usage: python3 html_to_pptx_a4.py <slides.html> [output.pptx] [--layout=1up|2up]")
        print("  --layout=1up : 1 HTML スライド → 1 A4 縦ページ (既定)")
        print("  --layout=2up : 2 HTML スライド → 1 A4 縦ページ (配布資料相当)")
        sys.exit(1)

    html_path = os.path.abspath(args[0])
    if len(args) > 1:
        output_path = os.path.abspath(args[1])
    else:
        base, _ = os.path.splitext(html_path)
        output_path = f'{base}_a4_{layout}.pptx'

    # HTML 読み込み
    with open(html_path, 'r', encoding='utf-8') as f:
        raw_html = f.read()
    soup = BeautifulSoup(raw_html, 'lxml')

    # h2p グローバルを設定 (既存 main() が普段やっている前処理を代替する)
    h2p.BASE_DIR = os.path.dirname(html_path)
    h2p.MISSING_ASSETS = []
    h2p.ALLOW_MISSING = True  # A4 出力では欠落を alert のみで続行 (エラー終了しない)
    h2p.SVG_OUT_DIR = None    # A4 では単体 SVG 書き出しは無効

    # フォント自動検出 (既存 main() と同じロジック)
    first = None
    m_inline = re.search(r'<body\b[^>]*\bstyle\s*=\s*["\'][^"\']*font-family\s*:\s*([^;"\']+)', raw_html, re.IGNORECASE)
    if m_inline:
        first = m_inline.group(1).split(',')[0].strip().strip('\'"')
    if not first:
        m = re.search(r'body\s*\{[^}]*font-family\s*:\s*([^;}]+)', raw_html, re.IGNORECASE)
        if m:
            first = m.group(1).split(',')[0].strip().strip('\'"')
    if first:
        h2p.FONT_NAME = first
        print(f"フォント: {h2p.FONT_NAME}")

    # SVG 抽出用 soup
    try:
        h2p.RAW_SVG_SOUP = BeautifulSoup(raw_html, 'html.parser')
    except Exception as e:
        print(f'  WARN: SVG 抽出用 soup 作成失敗 ({e})')
        h2p.RAW_SVG_SOUP = None

    # h2p の座標変換関数を A4 用に差し替え
    h2p.px_to_emu_x = px_to_emu_x_a4
    h2p.px_to_emu_y = px_to_emu_y_a4

    # A4 縦の Presentation を作成
    prs = Presentation()
    prs.slide_width = Emu(A4_W_EMU)
    prs.slide_height = Emu(A4_H_EMU)

    slides = soup.find_all('div', class_='slide')
    slide_titles = h2p.extract_slide_titles(soup, raw_html)

    if layout == '2up':
        # 2 スライドを 1 枚に統合してから処理 (SRC_H_PX を延長する必要はない.
        # 下スライドは Y +760 px にオフセット済みなので、Y_OFFSET_EMU の設定で調整)
        merged_slides = merge_pairs_for_2up(slides, soup, gap_px=40)
        # 2up 時は元スライド 720px 2 枚 + 40px gap = 1480px を A4 縦 (1123 px 相当) に収める必要がある
        # SCALE を再計算: A4 高さ - 上下マージン (計 300px 相当) = 1123 - 300 = 823 → 1480 に対し 0.556
        # ただし A4 幅にもフィットさせないといけない。上下と左右で厳しい方に合わせる
        # 幅方向: 1280 → 794 = 0.620
        # 高さ方向 (2枚+gap): 1480 → 823 = 0.556
        # 厳しい方 = 0.556 を採用
        global SCALE, SLOT_H_EMU
        SCALE_2UP = min(A4_W_EMU / (SRC_W_PX * 9525),
                        (A4_H_EMU - 2 * MARGIN_2UP_TOP) / ((2 * SRC_H_PX + 40) * 9525))
        # 上マージン + 中央寄せ
        SCALE = SCALE_2UP
        Y_OFFSET_EMU = MARGIN_2UP_TOP
        for i, mg in enumerate(merged_slides, 1):
            h2p.process_slide(prs, mg, i)
    else:  # 1up
        Y_OFFSET_EMU = MARGIN_1UP_TOP
        for i, slide_div in enumerate(slides, 1):
            h2p.process_slide(prs, slide_div, i)

    prs.save(output_path)
    # 後処理 (Content Types 修復のみ・app.xml は A4 で不要)
    h2p._fix_content_types(output_path)
    # PowerPointで直せる形に（段落既定の太字を外す・手書きのページ番号を自動番号に）
    h2p._SEM.fix_editable(output_path)
    # macOSの検疫属性を外す（保護ビュー=読み取り専用で開くのを防ぐ。html_to_pptx.py と同じ）
    if sys.platform == 'darwin':
        try:
            import subprocess
            subprocess.run(['xattr', '-d', 'com.apple.quarantine', output_path],
                           capture_output=True, timeout=10)
        except Exception:
            pass

    print(f"Saved: {output_path} (layout={layout}, {len(slides)} 元スライド)")
    if h2p.MISSING_ASSETS:
        print(f"⚠️  {len(h2p.MISSING_ASSETS)} 個のアセット欠落あり (Chrome 無し等)")


if __name__ == '__main__':
    main()
