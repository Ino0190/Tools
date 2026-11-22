#!/usr/bin/env python3
"""デッキの発表時間を見積もる（2026-11-14 利用者「発表時間の見積もり」）。

  python3 SlideKit/deck_timing.py 対象.html [--limit 分] [--cpm 300] [--json]

考え方
  話す量 ＝ 発表者ノート（data-notes）があればノートの文字数。無いページは本文の文字数×0.6
            （画面の文字は全部は読まない。見出し・箇条書きを言い換えて話す分の目安）。
  速さ   ＝ 日本語 1分 300字（NHK のアナウンスは 1分 300字前後。プレゼンは少しゆっくりで 250〜300）。
            英数字は 1語 ≒ 2字で数える。
  下限   ＝ 1枚 8秒（表紙・章扉でも、めくって一呼吸）。
  図・表だけのページ ＝ 本文が 20字未満なら「指して説明する」分として 20秒を置く。

出すもの
  枚ごとの秒数・文字数・根拠（ノート／本文）、合計（分:秒）、--limit があれば超過と「削る目安の枚数」。
  --json で機械向け。slidecheck / kits-mcp（slidekit_timing）から使う。
戻り値: --limit を超えたら 1、それ以外 0。
"""
import json
import re
import sys

CPM_DEFAULT = 300          # 字/分
BODY_RATIO = 0.6           # ノートが無いページ: 本文の何割を話すか
MIN_SEC = 8                # 1枚の下限
FIGURE_ONLY_SEC = 20       # 本文がほぼ無い（図・表だけ）ページ
FIGURE_ONLY_CHARS = 20


def count_chars(text):
    """話す量としての文字数。全角は1、英数の語は2字相当、空白・記号は数えない。"""
    t = re.sub(r'\s+', ' ', text or '').strip()
    words = re.findall(r'[A-Za-z0-9][A-Za-z0-9\-\.%]*', t)
    rest = re.sub(r'[A-Za-z0-9][A-Za-z0-9\-\.%]*', '', t)
    rest = re.sub(r'[\s\W_]', '', rest, flags=re.UNICODE)  # 句読点・記号は除く
    return len(rest) + 2 * len(words)


def deck_slides(path):
    """[(枚番号, タイトル, 本文, ノート)]。deck_lint と同じ切り方＋data-notes。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(open(path, encoding='utf-8').read(), 'html.parser')
    out = []
    for i, sl in enumerate(soup.select('div.slide'), 1):
        notes = (sl.get('data-notes') or '').replace('\\n', '\n').strip()
        best, parts = (0, ''), []
        for el in sl.find_all(['div', 'tr']):
            if el.name == 'tr':
                t = ' '.join(re.sub(r'\s+', ' ', c.get_text(' ')).strip() for c in el.find_all(['td', 'th']))
            elif 'tb' in (el.get('class') or []) and not el.find_parent('table') \
                    and not el.find('div', class_='tb'):
                t = re.sub(r'\s+', ' ', el.get_text(' ')).strip()
                try:
                    fs = float(el.get('data-font-size') or 0)
                except ValueError:
                    fs = 0
                if fs > best[0] and len(re.sub(r'[\d\s]', '', t)) >= 2:
                    best = (fs, t)
            else:
                continue
            if t and t not in parts:
                parts.append(t)
        title = best[1]
        body = ' '.join(p for p in parts if p != title)
        out.append((i, title, body, notes))
    return out


def estimate(path, cpm=CPM_DEFAULT):
    rows = []
    for i, title, body, notes in deck_slides(path):
        if notes:
            chars, basis = count_chars(notes), 'ノート'
            sec = chars / cpm * 60
        else:
            bc = count_chars(body)
            if bc < FIGURE_ONLY_CHARS:
                chars, basis, sec = bc, '図・表', FIGURE_ONLY_SEC
            else:
                chars, basis = bc, '本文'
                sec = bc * BODY_RATIO / cpm * 60
        sec = max(MIN_SEC, round(sec))
        rows.append({'index': i, 'title': title, 'chars': chars, 'basis': basis, 'sec': int(sec)})
    total = sum(r['sec'] for r in rows)
    with_notes = sum(1 for r in rows if r['basis'] == 'ノート')
    return {
        'path': path, 'slides': len(rows), 'cpm': cpm,
        'total_sec': total, 'total_text': f'{total // 60}分{total % 60:02d}秒',
        'avg_sec': round(total / len(rows)) if rows else 0,
        'notes_pages': with_notes,
        'confidence': '高（ノートあり）' if rows and with_notes == len(rows)
                      else '中（一部ノート）' if with_notes else '低（本文からの推定）',
        'rows': rows,
    }


def with_limit(est, limit_min):
    """持ち時間との差。超えていれば、長いページから削って収まる枚数の目安を足す。"""
    if not limit_min:
        return est
    limit = int(limit_min * 60)
    over = est['total_sec'] - limit
    est['limit_sec'] = limit
    est['over_sec'] = over
    if over > 0:
        cut, acc = [], 0
        for r in sorted(est['rows'], key=lambda r: -r['sec']):
            if acc >= over:
                break
            cut.append(r['index']); acc += r['sec']
        est['suggest_cut'] = sorted(cut)
        est['verdict'] = f'{over // 60}分{over % 60:02d}秒 超過。長い順に {len(cut)}枚（{", ".join(map(str, sorted(cut)))}）を削るか短くすると収まる'
    else:
        est['verdict'] = f'{(-over) // 60}分{(-over) % 60:02d}秒 の余り'
    return est


def main(argv):
    files = [a for k, a in enumerate(argv) if not a.startswith('--') and (k == 0 or argv[k - 1] not in ('--limit', '--cpm'))]
    if not files:
        print(__doc__); return 2
    limit = next((float(argv[k + 1]) for k, a in enumerate(argv) if a == '--limit' and k + 1 < len(argv)), 0)
    cpm = next((int(argv[k + 1]) for k, a in enumerate(argv) if a == '--cpm' and k + 1 < len(argv)), CPM_DEFAULT)
    est = with_limit(estimate(files[0], cpm), limit)
    if '--json' in argv:
        print(json.dumps(est, ensure_ascii=False, indent=1)); return 1 if est.get('over_sec', 0) > 0 else 0
    print(f'発表時間の見積もり（{cpm}字/分・{est["confidence"]}）')
    for r in est['rows']:
        print(f'{r["index"]:>3}  {r["sec"]:>4}秒  {r["chars"]:>4}字 {r["basis"]:<4} {r["title"] or "（タイトルなし）"}')
    print(f'合計 {est["total_text"]}（{est["slides"]}枚・1枚平均 {est["avg_sec"]}秒）')
    if est.get('verdict'):
        print(('🚨 ' if est.get('over_sec', 0) > 0 else '✓ ') + f'持ち時間 {int(limit)}分: ' + est['verdict'])
    return 1 if est.get('over_sec', 0) > 0 else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
