#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pptx_to_html.py の往復検査。

    python3 SlideKit/pptx_to_html_check.py                       # slide-template.html で検査
    python3 SlideKit/pptx_to_html_check.py MyDeck/slides.html    # 任意のデッキで

手順:
    元HTML --html_to_pptx.py--> 中間.pptx --pptx_to_html.py--> 往復.html
    1) run_check.py 往復.html が「問題なし」で通る
    2) スライド枚数が元と一致
    3) 文字枠（.tb）の文字が元と一致
    4) 座標を持つ文字枠の位置（data-x/y/w/h）が元と ±2px 以内で一致

html_to_pptx は既定でタイトル枠化・テーマ色化（semantic）するので、純粋な往復を測るため
--no-semantic を付ける。画像が無くても落ちないよう --allow-missing-assets も付ける。
"""

import os
import re
import sys
import subprocess
import tempfile

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
H2P = os.path.join(HERE, 'html_to_pptx.py')
P2H = os.path.join(HERE, 'pptx_to_html.py')
RUN_CHECK = os.path.join(HERE, 'run_check.py')
TEMPLATE = os.path.join(HERE, 'slide-template.html')
TOL = 2  # px


def _norm(s):
    return re.sub(r'\s+', '', s or '')


def _tbs(html_text):
    """各スライドの文字枠を [(正規化テキスト, x, y, w, h), ...] のリストで返す（スライドごと）。
    座標が無い枠（.rect 内の文字など）は x..h を None にする。"""
    soup = BeautifulSoup(html_text, 'html.parser')
    per_slide = []
    for sl in soup.select('.slide'):
        items = []
        for tb in sl.select('.tb'):
            txt = _norm(tb.get_text(' ', strip=True))
            if not txt:
                continue

            def _i(name):
                v = tb.get(name)
                return int(v) if v not in (None, '') else None
            items.append((txt, _i('data-x'), _i('data-y'), _i('data-w'), _i('data-h')))
        per_slide.append(items)
    return per_slide


def run(deck_path):
    deck_path = os.path.abspath(deck_path)
    with open(deck_path, encoding='utf-8') as f:
        orig_html = f.read()

    tmp = tempfile.mkdtemp(prefix='sk_roundtrip_')
    pptx = os.path.join(tmp, 'mid.pptx')
    back = os.path.join(tmp, 'back.html')
    problems = []

    r1 = subprocess.run([sys.executable, H2P, deck_path, pptx, '--no-semantic',
                         '--allow-missing-assets'], capture_output=True, text=True)
    if r1.returncode != 0 or not os.path.exists(pptx):
        print('❌ html_to_pptx で失敗\n', r1.stdout, r1.stderr)
        return 1

    r2 = subprocess.run([sys.executable, P2H, pptx, back],
                        capture_output=True, text=True)
    if r2.returncode != 0 or not os.path.exists(back):
        print('❌ pptx_to_html で失敗\n', r2.stdout, r2.stderr)
        return 1

    # 1) run_check
    r3 = subprocess.run([sys.executable, RUN_CHECK, back], capture_output=True, text=True)
    if '問題なし' not in r3.stdout:
        problems.append(f'run_check が通らない: {r3.stdout.strip() or r3.stderr.strip()}')

    with open(back, encoding='utf-8') as f:
        back_html = f.read()
    a = _tbs(orig_html)
    b = _tbs(back_html)

    # 2) 枚数
    if len(a) != len(b):
        problems.append(f'スライド枚数が違う: 元{len(a)}枚 → 往復{len(b)}枚')

    # 3) 文字 + 4) 位置
    for i in range(min(len(a), len(b))):
        # html_to_pptx はスライドごとにページ番号の文字枠を足す（元HTMLには無い）。
        # 往復で増える純粋な番号は検査対象外にする。
        page_no = str(i + 1)
        a[i] = [t for t in a[i] if t[0] != page_no]
        b[i] = [t for t in b[i] if t[0] != page_no]
        ta = {t[0] for t in a[i]}
        tb = {t[0] for t in b[i]}
        miss = ta - tb
        extra = tb - ta
        if miss:
            problems.append(f'{i+1}枚目: 消えた文字 {sorted(miss)}')
        if extra:
            problems.append(f'{i+1}枚目: 増えた文字 {sorted(extra)}')
        # 位置: 両方に座標があるテキストだけ比べる
        pa = {t[0]: t[1:] for t in a[i] if t[1] is not None}
        pb = {t[0]: t[1:] for t in b[i] if t[1] is not None}
        for txt in pa.keys() & pb.keys():
            for dim, (va, vb) in zip('xywh', zip(pa[txt], pb[txt])):
                if va is None or vb is None:
                    continue
                if abs(va - vb) > TOL:
                    problems.append(f'{i+1}枚目「{txt}」 {dim} が {va}→{vb}（±{TOL}px超）')

    if problems:
        print(f'⚠️ 往復検査 NG（{len(problems)}件）:')
        for p in problems:
            print('  -', p)
        return 1
    print(f'✅ 往復検査 OK: {os.path.basename(deck_path)} / {len(a)}枚・文字と位置（±{TOL}px）一致・run_check 問題なし')
    return 0


def main():
    deck = sys.argv[1] if len(sys.argv) > 1 else TEMPLATE
    sys.exit(run(deck))


if __name__ == '__main__':
    main()
