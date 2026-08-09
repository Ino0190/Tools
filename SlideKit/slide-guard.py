#!/usr/bin/env python3
# SlideKit slide-guard.py — 変換前の静的ガード（Chrome不要・一瞬で終わる）
#   python3 SlideKit/slide-guard.py [ファイル...]
#   引数なし→stdinからパス抽出→それも無ければ「最近5分に更新された.html」を検査
# SlideKit規約のデッキ（class="slide" と data-x を持つHTML）だけを対象に:
#   [fail=変換停止]
#     ①data-font-size 下限割れ（15px未満。図解スライド＝D系宣言ありのみ13px以上可・13px未満は常に不可）
#     ②許可外クラス（.tb/.rect/.flow/.li以外は html_to_pptx.py が読めず内容が静かに消える）
#     ③カタログ外hex（正解=pattern-catalog/diagram-catalog/slide-templateから自動抽出。
#       SVG内は警告に降格。<html data-palette="custom"> 宣言で全体を警告に降格）
#   [warn=警告のみ]
#     ④パターンID未宣言（<!-- SLIDE: 名前 [P09] --> / [D05] / [CUSTOM: 理由]）
#     ⑤キャンバス外座標（1280×720からのはみ出し）
# 深い検査（アス比・重なり）は run_check.py（Chrome headless）で別途やる
import os, re, select, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {'slide', 'tb', 'rect', 'flow', 'li', 'ins', 'inszone',
           # AWSテンプレ機構が実行時にスライドへ付けるシステムclass（変換側が正規に扱う）
           'aws-cover', 'aws-overlay', 'aws-cover-bg'}
EXCLUDE_DIRS = {'node_modules', '.git', '.versions', '_archive'}
# hex正解データの抽出元: カタログ2枚＋雛形＋defs＋AWSプラグイン（リマップ色・グラデ色。
# slidekit-aws.js はプラグイン化で defs から分離。無い環境では読み飛ばす＝許可色が減るだけ）
CATALOG_FILES = ('pattern-catalog.html', 'diagram-catalog.html', 'slide-template.html',
                 'slidekit-defs.js', 'slidekit-aws.js')
HEX_RE = re.compile(r'#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b')
PATTERN_ID_RE = re.compile(r'\[(?:P\d{2}|D\d{2}|CUSTOM:[^\]]+)\]|\b[PD]\d{2}\b')
_allowed_hex_cache = None


def _norm_hex(h):
    """#fff→#ffffff、#183251d9→#183251（アルファは基色で判定）に正規化"""
    h = h.lower()
    if len(h) == 4:
        h = '#' + ''.join(c * 2 for c in h[1:])
    return h[:7]


def allowed_hexes():
    """カタログ2枚＋雛形から使用hexを自動抽出（=正解データ。手書きリストは持たない）"""
    global _allowed_hex_cache
    if _allowed_hex_cache is None:
        s = set()
        for name in CATALOG_FILES:
            p = os.path.join(KIT, name)
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    s.update(_norm_hex(h) for h in HEX_RE.findall(f.read()))
            except OSError:
                pass
        _allowed_hex_cache = s
    return _allowed_hex_cache


def is_deck(text):
    return 'class="slide"' in text and 'data-x=' in text


def check(path):
    """検査本体。デッキ以外は None。デッキは [('fail'|'warn', メッセージ), ...] を返す"""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return None
    if not is_deck(text):
        return None  # SlideKitデッキ以外は対象外
    probs = []
    body = re.sub(r'<script[\s\S]*?</script>', '', text)
    body = re.sub(r'<style[\s\S]*?</style>', '', body)

    # ①フォント下限（PPTX pt換算。絶対下限15px=11.25pt。
    #   図解スライド＝SLIDEコメントにD系宣言があるスライドのみ13px以上可＝2026-08-05利用者判断）
    #   13px未満はどこでもfail。13〜14pxはD宣言スライド内なら許容、それ以外はfail
    hard, soft = set(), set()
    for chunk in re.split(r'(?=<!--\s*SLIDE:)', text):
        m = re.match(r'<!--\s*SLIDE:([\s\S]*?)-->', chunk)
        is_diagram = bool(m and re.search(r'\bD\d{2}\b', m.group(1)))
        for s in re.findall(r'data-font-size="(\d+)"', chunk):
            s = int(s)
            if s < 13:
                hard.add(s)
            elif s < 15 and not is_diagram:
                soft.add(s)
    if hard:
        probs.append(('fail', f'フォント13px未満: {sorted(hard)}（図解でも13pxが下限）'))
    if soft:
        probs.append(('fail', f'フォント15px未満: {sorted(soft)}（13〜14pxは図解スライド＝D系宣言ありのみ可。本文は19px以上）'))

    # ②許可外クラス → fail
    bad = sorted({c for m in re.findall(r'class="([^"]+)"', body)
                  for c in m.split() if c not in ALLOWED})
    if bad:
        probs.append(('fail', f'許可外クラス: {bad}（.tb/.rect/.flow/.li以外はPPTXで内容が消える）'))

    # ③カタログ外hex → fail（SVG内はwarn・data-palette="custom"宣言で全体warn）
    custom_palette = bool(re.search(r'<html[^>]*data-palette="custom"', text))
    svg_blocks = re.findall(r'<svg[\s\S]*?</svg>', body)
    non_svg = re.sub(r'<svg[\s\S]*?</svg>', '', body)
    allowed = allowed_hexes()
    if allowed:  # カタログが読めない環境（配布版等）ではhex検査をスキップ
        out_main = sorted({_norm_hex(h) for h in HEX_RE.findall(non_svg)} - allowed)
        out_svg = sorted({_norm_hex(h) for h in HEX_RE.findall(''.join(svg_blocks))} - allowed)
        if out_main:
            lv = 'warn' if custom_palette else 'fail'
            note = '（data-palette="custom"宣言あり）' if custom_palette else \
                '（カタログ・トークンに無い色。顧客ブランド色なら <html data-palette="custom"> を宣言）'
            probs.append((lv, f'カタログ外hex: {out_main}{note}'))
        if out_svg:
            probs.append(('warn', f'SVG内のカタログ外hex: {out_svg}（グラデ中間色なら可）'))

    # ④パターンID宣言 → warn
    comments = re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->', text)
    n_slides = len(re.findall(r'class="slide"', text))
    if not comments and n_slides:
        probs.append(('warn', f'SLIDEコメントなし（全{n_slides}枚）。各スライドを <!-- SLIDE: 名前 [P09] --> で囲む'))
    else:
        no_id = [c.strip()[:20] for c in comments if not PATTERN_ID_RE.search(c)]
        if no_id:
            probs.append(('warn', f'パターンID未宣言: {no_id}（[P09]/[D05]/[CUSTOM: 理由] を付ける）'))

    # ⑤キャンバス外座標（1280×720はみ出し） → warn
    off = []
    for m in re.finditer(r'data-x="(-?\d+)"\s+data-y="(-?\d+)"\s+data-w="(\d+)"\s+data-h="(\d+)"', text):
        x, y, w, h = map(int, m.groups())
        if x < 0 or y < 0 or x + w > 1280 or y + h > 720:
            off.append(f'x{x},y{y},w{w},h{h}')
    if off:
        probs.append(('warn', f'キャンバス外座標: {off[:5]}（1280×720からはみ出し）'))

    return probs


def targets_from_stdin():
    if sys.stdin.isatty():
        return []
    ready, _, _ = select.select([sys.stdin], [], [], 1.0)
    if not ready:
        return []
    text = sys.stdin.read()
    hits = re.findall(r'[\w./ヲ-ヺぁ-ゖ一-鿿ー-]+\.html?', text)
    return [h for h in hits if os.path.exists(os.path.join(ROOT, h)) or os.path.exists(h)]


def recent_html(minutes=5):
    now = time.time()
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and '_dist_' not in d]
        for n in filenames:
            if n.endswith(('.html', '.htm')):
                p = os.path.join(dirpath, n)
                try:
                    if now - os.path.getmtime(p) < minutes * 60:
                        out.append(p)
                except OSError:
                    pass
    return out


def main():
    explicit = sys.argv[1:]
    paths = explicit or targets_from_stdin() or recent_html()
    fails = warns = checked = 0
    for p in paths:
        # 絶対パス→CWD相対→ワークスペースROOT相対 の順に解決
        cands = [p] if os.path.isabs(p) else [os.path.abspath(p), os.path.join(ROOT, p)]
        full = next((c for c in cands if os.path.exists(c)), None)
        if full is None:
            if explicit:
                print(f'⚠️  slide-guard: ファイルが見つからない: {p}')
            continue
        probs = check(full)
        if probs is None:
            continue  # SlideKitデッキ以外は黙ってスキップ
        rel = os.path.relpath(full, ROOT)
        checked += 1
        for lv, msg in probs:
            print(f'{"🚨" if lv == "fail" else "⚠️ "} {rel}: {msg}')
            if lv == 'fail':
                fails += 1
            else:
                warns += 1
    if checked and not fails:
        print(f'slide-guard OK（デッキ{checked}件・停止級の違反なし・警告{warns}件）')
    elif explicit and not checked:
        print('slide-guard: 検査対象なし（指定パスが見つからないかSlideKitデッキではない）')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
