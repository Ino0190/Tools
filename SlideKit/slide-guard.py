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
#     ⑥構成ファイル（<deck>.structure.md）が無い／HTMLと枚数・型IDがずれる／主張が空
#       構成ファイル内の4問のうち「誰に」「理解してほしいこと」の空欄はfail（宛先の無い資料を作らない）
#       「相談したいこと」「一番伝えたいこと」の空欄はwarn
#       3枚未満のデッキは対象外。<html data-structure="off"> で無効化
#     ⑦図解スライドが0枚（6枚以上のデッキでD系宣言なし＝文字ばかりの疑い）
#     ⑧1枚の文字が多い（.tbの文字数が900字超。表セルは除く）
#     ⑥〜⑧は <html data-structure="off"> でまとめて外れる
# 角丸は禁止しない。PPTXで指定サイズが守られるかは tests/test_radius.py が見る
# メッセージ先頭の [B1] [R2] [M5] 等は SlideKit/defect-taxonomy.md の分類ID。
# 機械で見られない欠陥（M4 M6 M7 A1〜A4）はその表を見ながら人とAIが点検する
# 深い検査（アス比・重なり）は run_check.py（Chrome headless）で別途やる
import html, math, os, re, select, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {'slide', 'tb', 'rect', 'flow', 'li', 'ins', 'inszone',
           # AWSテンプレ機構が実行時にスライドへ付けるシステムclass（変換側が正規に扱う）
           'aws-cover', 'aws-overlay', 'aws-cover-bg'}
EXCLUDE_DIRS = {'node_modules', '.git', '.versions', '_archive', '.slidekit-v0'}
# hex正解データの抽出元: カタログ2枚＋雛形＋defs＋AWSプラグイン（リマップ色・グラデ色。
# slidekit-aws.js はプラグイン化で defs から分離。無い環境では読み飛ばす＝許可色が減るだけ）
CATALOG_FILES = ('pattern-catalog.html', 'diagram-catalog.html', 'slide-template.html',
                 'slidekit-defs.js', 'slidekit-aws.js')
HEX_RE = re.compile(r'#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b')
PATTERN_ID_RE = re.compile(r'\[(?:P\d{2}|D\d{2}|CUSTOM:[^\]]+)\]|\b[PD]\d{2}\b')
# 構成ファイル（<deck>.structure.md）の必須メタと、節見出し末尾の型ID宣言
# 構成ファイルの4問（2026-08-21 利用者）。空欄の重さで fail / warn を分ける
STRUCT_META_REQUIRED = ('誰に', '理解してほしいこと')      # 空ならfail＝この2つが無い資料は作らない
STRUCT_META_WANTED = ('相談したいこと', '一番伝えたいこと')  # 空ならwarn
STRUCT_META = STRUCT_META_REQUIRED + STRUCT_META_WANTED
# PJメモから仮説で埋めた値の印。空欄で止めるのではなく仮で埋めて確認する運用（2026-08-21）
TENTATIVE_MARK = '[仮]'
_H = r'[ \t\u3000]*'  # 行内の空白のみ（\s だと改行を食って次行を値と誤認する）
_STRUCT_ID_RE = re.compile(r'\[(?:P\d{2}|D\d{2}|CUSTOM:[^\]]+)\]\s*$')
STRUCT_MIN_SLIDES = 3   # これ未満の短いデッキは構成ファイルを求めない
DIAGRAM_MIN_SLIDES = 6  # これ以上の枚数でD系が0枚なら「文字ばかり」を疑う
# 1枚の文字数の目安。既存2,483枚の実測 p50=279 / p75=422 / p90=561 / p95=656 / p99=962（2026-08-21）
TEXT_MAX_CHARS = 900
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


def norm_pattern_id(s):
    """[P09]→P09、[CUSTOM: 理由]→CUSTOM、裸のd05→D05。未宣言はNone"""
    if not s:
        return None
    t = s.strip().strip('[]').strip()
    return 'CUSTOM' if t.upper().startswith('CUSTOM') else t.upper()


def slide_pattern_ids(comments):
    """SLIDEコメント本文の列から型IDを出現順に取り出す（未宣言はNone）"""
    out = []
    for c in comments:
        m = PATTERN_ID_RE.search(c)
        out.append(norm_pattern_id(m.group(0)) if m else None)
    return out


def check_structure(spath, comments, n_slides):
    """構成ファイル（<deck>.structure.md）を読み、HTML側と突合する。

    決定: 構成ファイルの存在自体は任意（無ければwarn）だが、作った以上は
    「誰に」「理解してほしいこと」の空欄はfailにする。宛先の無い資料を作らないための工程。
    根拠=.kiro/steering/projects/kiro-operations.md
    """
    try:
        with open(spath, encoding='utf-8', errors='replace') as f:
            st = f.read()
    except OSError as e:
        return [('warn', f'構成ファイルが読めない: {e}')]
    name = os.path.basename(spath)
    out = []
    tentative = []
    for key in STRUCT_META:
        lv = 'fail' if key in STRUCT_META_REQUIRED else 'warn'
        tail = '。ここが決まらない資料は作らない' if lv == 'fail' else ''
        # 🚫 ここで \s* を使うと改行を食って次の行を値として拾い、空欄を検出できない
        m = re.search(rf'^[-*・]{_H}{key}{_H}[:：]{_H}(.*)$', st, re.M)
        if m is None:
            out.append((lv, f'[M1/M2] 構成ファイルに「{key}」の行が無い（{name}）'))
            continue
        v = m.group(1).strip()
        if v in ('', '（未定）', '未定', 'TBD', '-'):
            out.append((lv, f'[M1/M2] 構成ファイルの「{key}」が空（{name}）{tail}'))
        elif v.startswith(TENTATIVE_MARK):
            # 仮で埋めた値。作業は進めるが、確定したら印を外す（外し忘れの検出）
            tentative.append(key)
    if tentative:
        out.append(('warn', f'[M1/M2] 仮のままの項目: {"・".join(tentative)}'
                            f'（資料を頼んだ人に確認して、確定したら {TENTATIVE_MARK} を外す）'))

    st_ids, no_claim = [], []
    for b in re.split(r'^##\s+', st, flags=re.M)[1:]:
        head = b.splitlines()[0].strip()
        m = _STRUCT_ID_RE.search(head)
        st_ids.append(norm_pattern_id(m.group(0)) if m else None)
        cm = re.search(rf'^[-*・]{_H}主張{_H}[:：]{_H}(.*)$', b, re.M)
        if cm is None or not cm.group(1).strip():
            no_claim.append(head[:20])
    if not st_ids:
        return out + [('warn', f'構成ファイルにスライドの節（## 見出し）が無い（{name}）')]
    if no_claim:
        out.append(('warn', f'[M3] 構成ファイルで主張が空: {no_claim[:5]}（1スライド1メッセージ）'))
    undecl = [h for h, i in zip([b.splitlines()[0].strip()[:20]
                                 for b in re.split(r'^##\s+', st, flags=re.M)[1:]], st_ids) if i is None]
    if undecl:
        out.append(('warn', f'[M7] 構成ファイルで型ID未宣言: {undecl[:5]}（見出し末尾に [P09]/[D05]/[CUSTOM: 理由]）'))
    if len(st_ids) != n_slides:
        out.append(('warn', f'[M3] 枚数が構成と不一致: 構成{len(st_ids)}枚・HTML{n_slides}枚（{name}）'))
    html_ids = slide_pattern_ids(comments)
    diff = [f'{i + 1}枚目 構成{a or "未宣言"}→HTML{b or "未宣言"}'
            for i, (a, b) in enumerate(zip(st_ids, html_ids)) if a != b]
    if diff:
        out.append(('warn', f'[M7] 型IDが構成と不一致: {diff[:5]}（どちらかを直す）'))
    return out + check_density(st, name)


DENSE, LIGHT = '濃い', '薄め'


def check_density(st, name):
    """[M9] キースライドと濃淡（山と谷）。全部の枚が同じ濃さだと、どこが要か分からない資料になる。
    決定: キースライドは1枚の番号。濃い枚はキースライドを含む連続した1か所（山は1つ）。
    🚫 韓国L7資料（2026-09-28）は全枚が同じ濃さで、最後に「全部は説明できないからサマリーを」となった。
    出典＝太田賢一「AIスライド生成を進化させるMDファイル全文公開」（2026-03）のルール3"""
    st = re.sub(r'<!--[\s\S]*?-->', '', st)
    blocks = re.split(r'^##\s+', st, flags=re.M)[1:]
    n = len(blocks)
    out = []
    m = re.search(rf'^[-*・]{_H}キースライド{_H}[:：]{_H}(.*)$', st, re.M)
    key = None
    # 行が無い＝この項目ができる前の構成ファイル。黙って通す（既存デッキで警告を増やさない）
    if m is None:
        return []
    v = m.group(1).strip()
    # 「なし」＝分科会・定例・報告など、論点を順に並べて一緒に検討する資料。山と谷が要らない
    # 決定: キースライドは説得・印象づけの資料（提案・紹介・登壇）の考え方（2026-09-28 利用者
    #       「PoC分科会の資料なんかではキースライドがあるわけではないよね」）
    if v.startswith('なし'):
        return []
    if not v or v.startswith(('（', '(')):
        out.append(('warn', f'[M9] キースライドが未定（{name}）。1枚だけ見せるならどの枚か番号で書く。'
                            '分科会・定例・報告のように並べて検討する資料なら「なし」'))
    else:
        km = re.search(r'\d+', v)
        key = int(km.group(0)) if km else None
        if key is None or not 1 <= key <= n:
            out.append(('warn', f'[M9] キースライドの番号が枚数（1〜{n}）に無い: 「{v[:20]}」'))
            key = None
    dens = []
    for b in blocks:
        dm = re.search(rf'^[-*・]{_H}濃淡{_H}[:：]{_H}(.*)$', b, re.M)
        v = dm.group(1).strip() if dm else ''
        dens.append(DENSE if v.startswith(DENSE) else (LIGHT if v.startswith(LIGHT) else None))
    if not any(dens):
        out.append(('warn', f'[M9] 濃淡が未記入（{name}）。キースライドとその前後を「濃い」、他を「薄め」にする'))
        return out
    dense_at = [i + 1 for i, d in enumerate(dens) if d == DENSE]
    if key and dens[key - 1] != DENSE:
        out.append(('warn', f'[M9] キースライド（{key}枚目）が「濃い」になっていない'))
    runs = sum(1 for i, no in enumerate(dense_at) if i == 0 or no != dense_at[i - 1] + 1)
    if runs > 1:
        out.append(('warn', f'[M9] 「濃い」が{runs}か所に分かれている: {dense_at}枚目（山は1か所。他は薄めにする）'))
    if dense_at and len(dense_at) * 2 > n:
        out.append(('warn', f'[M9] 「濃い」が全{n}枚中{len(dense_at)}枚（半分を超えると山にならない）'))
    return out


BODY_MIN_PX = 22      # 本文の下限（slide-contract-detail.md 規則8。2026-11-18 投影で小さいとの指摘を受け19→22＝16.5pt）
BODY_MIN_CHARS = 40   # これ以上の長さの文字を「本文」とみなす（注記・ラベル・出典は短い）
# 2026-10-14 利用者「最近文字がまた小さくなり始めてる」→実測で10月前半は19px以上の文字が42%（9月後半61%）。
# 2026-11-18 既定を底上げ: 本文22px以上・カードの中18px以上（15〜17pxは注記・ラベルだけ）、表の中は小さくてよいが8pt（=10.667px）以上
CARD_MIN_PX = 18
CARD_MIN_CHARS = 12   # これ以上の長さをカードの本文とみなす（バッジ・見出しラベルは短い）
TABLE_MIN_PX = 8 / 0.75
SMALL_SHARE_MAX = 0.6  # 表の外の文字のうち19px未満がこれを超えたら、デッキ全体が小さい


def _strip_code(s):
    return re.sub(r'<(script|style)[\s\S]*?</\1>', '', s)


def _slides_with_comment(text):
    """[(枚目, そのスライドのHTML, 図解か, SLIDEコメントがあるか)]。
    SLIDEコメントは <div class="slide"> の直前にあるので、1つ前の区間の末尾を見る"""
    parts = re.split(r'(?=<div class="slide"[\s>])', text)
    out = []
    for i in range(1, len(parts)):
        prev = parts[i - 1]
        # 直前の区間で最後に出てくる SLIDE コメントのうち、/SLIDE より後ろのもの
        tail = prev[prev.rfind('<!-- /SLIDE') + 1:] if '<!-- /SLIDE' in prev else prev
        cm = list(re.finditer(r'<!--\s*SLIDE:([\s\S]*?)-->', tail))
        has = bool(cm)
        is_diagram = bool(cm and re.search(r'\bD\d{2}\b', cm[-1].group(1)))
        out.append((i, parts[i], is_diagram, has))
    return out


def slide_chunks(text):
    """[(枚目, スライドHTML, 図解か)]"""
    return [(no, ch, d) for no, ch, d, _h in _slides_with_comment(text)]


def _elem_text(chunk, pos):
    """pos を含むタグの中身の文字（その要素が閉じるか、次の要素が始まるまで）"""
    gt = chunk.find('>', pos)
    if gt < 0:
        return ''
    rest = chunk[gt + 1:gt + 4000]
    end = re.search(r'</div>|<div class="(?!li\b)|<table', rest)
    seg = rest[:end.start()] if end else rest
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', seg)).strip()


CAPTION_COLORS = {'#718096', '#5e5e5e', '#a0aec0', '#9fc0dd'}  # 色表の muted/補足/暗背景の細字/sub
FOOTER_Y = 640  # これより下は注記・出典・機密表示の帯


def _is_caption(chunk, pos):
    """補足色か、画面下端の帯にある文字＝注記。本文の大きさの検査から外す"""
    tag = chunk[chunk.rfind('<', 0, pos):chunk.find('>', pos) + 1]
    c = re.search(r'data-color="(#[0-9a-fA-F]{6})"', tag)
    if c and c.group(1).lower() in CAPTION_COLORS:
        return True
    y = re.search(r'data-y="(\d+(?:\.\d+)?)"', tag)
    return bool(y and float(y.group(1)) >= FOOTER_Y)


MAIN_MIN_W = 500  # これより狭い文字ボックスは画像横の注記とみなす


def _in_card(chunk, pos):
    """pos の要素がカード（.rect/.flow）の中か。画像・依頼の枠（.ins）の中は除く"""
    start = chunk.rfind('<div', 0, pos)
    before = chunk[:start]
    opens = [m for m in re.finditer(r'<div\b[^>]*>|</div>', before)]
    stack = []
    for m in opens:
        if m.group(0) == '</div>':
            if stack:
                stack.pop()
        elif not m.group(0).endswith('/>'):
            stack.append(m.group(0))
    return any(re.search(r'class="[^"]*\b(?:rect|flow)\b', t) for t in stack[1:]) and \
        not any(re.search(r'class="[^"]*\bins\b', t) for t in stack[1:])


def _is_main_text(chunk, pos):
    """スライドの主文か。19pxの下限はここだけに掛ける（2026-09-27 利用者判断）。
    外すもの＝カード（.rect/.flow）の中・幅500px未満の注記・補足色・下端の帯。
    表のセルとグラフ（SVG）はそもそも data-font-size を持たないので数えていない。
    🚫 カードの中まで数えた頃は実デッキ165件中105件・約1600箇所で出て、警告が読まれなくなった"""
    if _is_caption(chunk, pos):
        return False
    start = chunk.rfind('<div', 0, pos)
    before = chunk[:start]
    # chunk は <div class="slide"> から始まる。開いたままの div が slide 以外にあればカードの中
    depth = len(re.findall(r'<div\b', before)) - len(re.findall(r'</div>', before))
    if depth >= 2:
        return False
    tag = chunk[start:chunk.find('>', pos) + 1]
    if re.search(r'class="[^"]*\bins\b', tag):
        return False  # 画像・依頼の枠の中の文字は作る人向けのメモ（読む人の主文ではない）
    w = re.search(r'data-w="(\d+(?:\.\d+)?)"', tag)
    return not (w and float(w.group(1)) < MAIN_MIN_W)


def _text_after(chunk, pos, n=16):
    """人が要素を探すための手がかり（中身の先頭 n 文字）"""
    t = _elem_text(chunk, pos)
    return t[:n] + ('…' if len(t) > n else '')


def _few(items, k=5):
    return '、'.join(items[:k]) + (f' ほか{len(items) - k}件' if len(items) > k else '')


def _where_slides(slides, pred):
    nos = [str(no) for no, ch, _d in slides if pred(ch)]
    return (f'{"・".join(nos[:8])}枚目' + (' ほか' if len(nos) > 8 else '')) if nos else 'スライドの外'


_GEO_ATTR_RE = re.compile(r'\bdata-([xywh])="(-?\d+(?:\.\d+)?)"')
_GEO_TAG_RE = re.compile(r'<(div|table|img)\b[^>]*\bdata-x="[^>]*>', re.I)


def _est_text_width(t, fs):
    """文字列の幅の見積もり（px）。全角=0.88字（Meiryo UI は仮名・約物が狭い。Chrome の実測に合わせた）、半角=0.55字"""
    return sum(fs * 0.88 if ord(c) > 0x2e7f else fs * 0.55 for c in t)


def _inner_of(chunk, start):
    """start の開きタグに対応する閉じタグまでの中身（div の入れ子を数える）"""
    m = re.match(r'<(\w+)', chunk[start:])
    tag = m.group(1).lower() if m else 'div'
    i = chunk.find('>', start) + 1
    depth, pos = 1, i
    for t in re.finditer(r'<(/?)%s\b[^>]*>' % tag, chunk[i:], re.I):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return chunk[i:i + t.start()]
    return chunk[i:]


def _check_geometry(non_svg):
    """[F1] 枠がキャンバス（1280×720）の外へ出る・[F2] 文字が枠の高さに入らない見込み（2026-11-15）。
    返り: (off, overflow) どちらも『N枚目 …』の文字列の配列"""
    off, overflow = [], []
    for si, chunk in enumerate(re.split(r'(?=<div class="slide")', non_svg)[1:], 1):
        for m in _GEO_TAG_RE.finditer(chunk):
            tag = m.group(0)
            g = {k: float(v) for k, v in _GEO_ATTR_RE.findall(tag)}
            if 'x' not in g or 'y' not in g or 'w' not in g:
                continue
            x, y, w = g['x'], g['y'], g['w']
            h = g.get('h')
            kind = m.group(1).lower()
            if h is None and kind == 'table':
                # data-h の無い表: 行数 × 見積もりの行の高さ（html_to_pptx の既定 32px と、字の大きさ×1.5＋上下の余白の大きい方）
                inner = _inner_of(chunk, m.start())
                rows = len(re.findall(r'<tr\b', inner, re.I))
                fsm = re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', tag)
                fs = float(fsm.group(1)) if fsm else 17.0
                h = rows * max(32.0, fs * 1.5 + 12)
            if h is None:
                continue
            if x < 0 or y < 0 or x + w > 1280.5 or y + h > 720.5:
                off.append(f'{si}枚目 x{x:g},y{y:g},w{w:g},h{h:g}' + ('（表の行数から）' if kind == 'table' and 'h' not in g else ''))
            # [F2] 文字の枠（.tb）: 段落ごとに折り返しの行数を見積もり、高さ×1.25 を超えたら
            #   white-space:nowrap の枠は折り返さない（GanttKit の行の名前など。はみ出しは横で、作る側が「…」で詰める）
            if kind == 'div' and re.search(r'class="tb\b', tag) and 'h' in g and w > 0 \
                    and not re.search(r'white-space\s*:\s*nowrap', tag):
                fsm = re.search(r'data-font-size="(\d+(?:\.\d+)?)"', tag) or \
                    re.search(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', tag)
                fs = float(fsm.group(1)) if fsm else 18.0
                # 行の高さ: style の line-height（倍率か px）、無ければ .tb の既定 1.5
                lhm = re.search(r'line-height\s*:\s*(\d+(?:\.\d+)?)(px)?', tag)
                lh = (float(lhm.group(1)) if lhm.group(2) else fs * float(lhm.group(1))) if lhm else fs * 1.5
                inner = _inner_of(chunk, m.start())
                paras = re.split(r'<br\s*/?>|</div>|</p>|</li>', inner, flags=re.I)
                lines = 0
                for para in paras:
                    t = html.unescape(re.sub(r'<[^>]+>', '', para)).strip()
                    if t:
                        # 1字より細かくは折り返せない（幅12px の「›」を3行と数えない）
                        lines += max(1, min(len(t), math.ceil(_est_text_width(t, fs) / max(1.0, w))))
                need = lines * lh
                if lines >= 2 and need > g['h'] * 1.25:
                    first = html.unescape(re.sub(r'<[^>]+>', '', inner)).strip()[:12]
                    overflow.append(f'{si}枚目「{first}…」約{lines}行={need:.0f}px>枠{g["h"]:g}px')
    return off, overflow


SLIDE_COLOR_MAX = 4  # 1枚で使う「はっきりした色」の数の目安（ベース・メイン・アクセント＋1まで）


def _iter_charts(chunk):
    """スライド内の data-chart を dict にして返す（壊れていれば None を混ぜる）。2026-11-18"""
    import json
    out = []
    for m in re.finditer(r'data-chart=(["\'])([\s\S]*?)\1', chunk):
        try:
            out.append(json.loads(m.group(2).replace('&quot;', '"')))
        except Exception:
            out.append(None)
    return out


def _hex_is_vivid(h):
    """#rrggbb が『はっきりした色』か。無彩色（白・黒・灰）と極端に明るい/暗い色は除く。2026-11-18"""
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return False
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    mx, mn = max(r, g, b), min(r, g, b)
    light = (mx + mn) / 510.0      # 明るさ 0..1
    chroma = (mx - mn) / 255.0     # 鮮やかさ 0..1
    return chroma >= 0.18 and 0.12 <= light <= 0.92


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
    # 見つけた違反は「何枚目の・どの文字か」で出す（どこを直すか分かるように・2026-09-27）
    slides = slide_chunks(text)
    hard, soft, small_body, small_card, tiny_table, share = [], [], [], [], [], [0, 0]
    for no, chunk, is_diagram in slides:
        # 小数（13.334px=10pt 等）も拾う。整数だけ見ていた頃は小数指定が検査を素通りしていた（2026-09-27）
        for m in re.finditer(r'data-font-size="(\d+(?:\.\d+)?)"', chunk):
            s = float(m.group(1))
            s = int(s) if s.is_integer() else s
            where = f'{no}枚目 {s}px「{_text_after(chunk, m.end())}」'
            if s < 13:
                hard.append(where)
            elif s < 15 and not is_diagram:
                soft.append(where)
            elif (s < BODY_MIN_PX and not is_diagram and _is_main_text(chunk, m.start())
                  and len(_elem_text(chunk, m.end())) >= BODY_MIN_CHARS):
                # 長い文＝本文。15〜18pxは注記なら可だが、本文なら小さい（規則は本文19px以上）
                small_body.append(where)
            elif (s < CARD_MIN_PX and not is_diagram and _in_card(chunk, m.start())
                  and not _is_caption(chunk, m.start()) and len(_elem_text(chunk, m.end())) >= CARD_MIN_CHARS):
                small_card.append(where)
        # 表の中（小さくてよいが 8pt 以上）
        for tm in re.finditer(r'<table\b[\s\S]*?</table>', _strip_code(chunk)):
            for fm in re.finditer(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', tm.group(0)):
                if float(fm.group(1)) < TABLE_MIN_PX - 0.01:
                    tiny_table.append(f'{no}枚目 {fm.group(1)}px')
        # デッキ全体の傾き（表の外の文字の量で見る）
        no_table = re.sub(r'<table\b[\s\S]*?</table>', '', chunk)
        for m in re.finditer(r'data-font-size="(\d+(?:\.\d+)?)"', no_table):
            share[0 if float(m.group(1)) < BODY_MIN_PX else 1] += len(_elem_text(no_table, m.end()))
    if hard:
        probs.append(('fail', f'[R1] 文字が13px未満: {_few(hard)}（図解でも13pxが下限。data-font-size と style の font-size を両方上げる）'))
    if soft:
        probs.append(('fail', f'[R1] 文字が15px未満: {_few(soft)}（13〜14pxは図解スライド＝D系宣言ありのみ可）'))
    if small_body:
        probs.append(('warn', f'[R1] 主文が{BODY_MIN_PX}px未満: {_few(small_body)}'
                              f'（スライドの主文は{BODY_MIN_PX}px以上。カードの中は{CARD_MIN_PX}px以上・注記とグラフは15pxまで可）'))
    if small_card:
        probs.append(('warn', f'[R1] カードの中の文が{CARD_MIN_PX}px未満: {_few(small_card)}'
                              f'（カードの中は{CARD_MIN_PX}px以上。15〜16pxは注記・ラベル・出典だけ。文を削って大きくする）'))
    if tiny_table:
        probs.append(('fail', f'[R1] 表の文字が8pt（10.67px）未満: {_few(tiny_table)}（表の中は小さくてよいが8pt以上）'))
    tot = share[0] + share[1]
    if tot >= 300 and share[0] / tot > SMALL_SHARE_MAX:
        probs.append(('warn', f'[R1] デッキ全体で文字が小さい: 表の外の文字の{share[0] * 100 // tot}%が{BODY_MIN_PX}px未満'
                              f'（目安{int(SMALL_SHARE_MAX * 100)}%まで。カードや注記に寄せず、文を減らして大きくする）'))

    # ⑤情報デザイン（広島大「情報デザインを意識したスライド作成入門」より・2026-11-18）
    #   G1 3Dグラフ禁止 / G2 棒グラフは0始まり / C1 1枚の色数 / A1 本文は左揃え
    three_d, bar_floor, many_color, centered = [], [], [], []
    for no, chunk, is_diagram in slides:
        for c in _iter_charts(chunk):
            if not isinstance(c, dict):
                continue
            t = str(c.get('type', '')).lower()
            if '3d' in t or c.get('threeD') or c.get('3d'):
                three_d.append(f'{no}枚目 type={c.get("type")}')
            if t in ('column', 'bar', 'stacked'):
                mn = c.get('min')
                if c.get('fitY') is True or (isinstance(mn, (int, float)) and mn != 0):
                    bar_floor.append(f'{no}枚目「{c.get("title") or t}」')
        # 1枚で使うはっきりした色の数（data-color/data-fill。グラフの系列色はデータなので数えない）
        cols = {_norm_hex(h) for a in ('data-color', 'data-fill')
                for h in re.findall(a + r'="(#[0-9a-fA-F]{3,6})"', chunk) if _hex_is_vivid(h)}
        if len(cols) > SLIDE_COLOR_MAX:
            many_color.append(f'{no}枚目 {len(cols)}色')
        # 本文（長い主文）のセンタリング
        for m in re.finditer(r'data-align="center"', chunk):
            if _is_main_text(chunk, m.start()) and len(_elem_text(chunk, m.end())) >= BODY_MIN_CHARS:
                centered.append(f'{no}枚目「{_text_after(chunk, m.end())}」')
    if three_d:
        probs.append(('fail', f'[G1] 3Dグラフは量を誤って見せる: {_few(three_d)}（2Dにする）'))
    if bar_floor:
        probs.append(('warn', f'[G2] 棒グラフの縦軸が0始まりでない: {_few(bar_floor)}'
                              '（棒の長さで量を比べるので0から。min/fitYを外す）'))
    if many_color:
        probs.append(('warn', f'[C1] 1枚に色が多い: {_few(many_color)}'
                              f'（はっきりした色は{SLIDE_COLOR_MAX}色まで＝ベース・メイン・アクセントに絞る）'))
    if centered:
        probs.append(('warn', f'[A1] 本文がセンタリング: {_few(centered)}'
                              '（長い文は左揃え。センタリングは行頭が揃わず読みにくい）'))

    # SVGブロックは分離して扱う。SVGはPPTXで画像になるので、中のclassや色は内容を壊さない
    svg_blocks = re.findall(r'<svg[\s\S]*?</svg>', body)
    non_svg = re.sub(r'<svg[\s\S]*?</svg>', '', body)

    # ②許可外クラス → fail（SVG内は対象外。
    #   決定: グラフ等のSVGはPNG化されるので dk-chart-svg のような外部由来classがあっても
    #   内容は消えない。body全体で見ていたため CalcKitのグラフ経路を過剰に止めていた 2026-08-21）
    bad = sorted({c for m in re.findall(r'class="([^"]+)"', non_svg)
                  for c in m.split() if c not in ALLOWED})
    if bad:
        at = _where_slides(slides, lambda ch: any(c in bad for m in re.findall(r'class="([^"]+)"', _strip_code(ch))
                                                 for c in m.split()))
        probs.append(('fail', f'[B1] 使えないclass: {bad}（{at}）'
                              '。使えるのは slide / tb / rect / flow / li / ins / inszone だけ。'
                              '他のclassはPPTXで見た目が消える＝inline style に書き直す'))

    # ③カタログ外hex → fail（SVG内はwarn・data-palette="custom"宣言で全体warn）
    custom_palette = bool(re.search(r'<html[^>]*data-palette="custom"', text))
    allowed = allowed_hexes()
    if allowed:  # カタログが読めない環境（配布版等）ではhex検査をスキップ
        out_main = sorted({_norm_hex(h) for h in HEX_RE.findall(non_svg)} - allowed)
        out_svg = sorted({_norm_hex(h) for h in HEX_RE.findall(''.join(svg_blocks))} - allowed)
        if out_main:
            lv = 'warn' if custom_palette else 'fail'
            note = '（data-palette="custom"宣言あり）' if custom_palette else \
                '（カタログ・トークンに無い色。近い色を slide-contract-detail.md の色表から選ぶ。' \
                '顧客ブランド色なら <html data-palette="custom"> を宣言）'
            at = _where_slides(slides, lambda ch: any(
                _norm_hex(h) in out_main for h in HEX_RE.findall(re.sub(r'<svg[\s\S]*?</svg>', '', _strip_code(ch)))))
            probs.append((lv, f'[B2] カタログに無い色: {out_main}（{at}）{note}'))
        if out_svg:
            probs.append(('warn', f'[B2] SVG内のカタログ外hex: {out_svg}（グラデ中間色なら可）'))

    # ④パターンID宣言 → warn
    comments = re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->', text)
    n_slides = len(re.findall(r'class="slide"', text))
    if not comments and n_slides:
        probs.append(('warn', f'[M5] SLIDEコメントなし（全{n_slides}枚）。各スライドを <!-- SLIDE: 名前 [P09] --> で囲む'))
    else:
        no_id = [c.strip()[:20] for c in comments if not PATTERN_ID_RE.search(c)]
        if no_id:
            probs.append(('warn', f'[M5] パターンID未宣言: {no_id}（[P09]/[D05]/[CUSTOM: 理由] を付ける）'))
        # 決定: 枚数とコメント数の一致も見る。片方だけ欠けると「型が1つ使えない」状態に気づけない
        #   （diagram-catalog.html の D11 が SLIDEコメント欠落で選択肢から消えていた 2026-08-21）
        if len(comments) != n_slides:
            missing = [str(no) for no, _c, _d, has in _slides_with_comment(text) if not has]
            where = f'。コメントが無いのは {"・".join(missing[:8])}枚目' if missing else ''
            probs.append(('warn', f'[M5] SLIDEコメントが{len(comments)}件・スライドが{n_slides}枚で不一致{where}'
                                  '（コメントが無いスライドは型が宣言されない）'))

    # ⑥構成ファイル（<deck>.structure.md）との突合
    #   HTMLを書く前に「読み手・相手が下す判断・1スライド1メッセージ・型ID」を確定させる工程。
    #   型カタログがあるのに文字ばかりになる原因は、型を選ぶ工程が無いこと（2026-08-21）
    #   <html data-structure="off"> は「これは人に渡す資料ではない」宣言。⑥⑦の両方を外す
    #   （型の見本帳＝pattern-catalog/diagram-catalog、感想シートの一覧など）
    structure_off = bool(re.search(r'<html[^>]*data-structure="off"', text))
    spath = os.path.splitext(path)[0] + '.structure.md'
    if os.path.exists(spath):
        probs += check_structure(spath, comments, n_slides)
    elif n_slides >= STRUCT_MIN_SLIDES and not structure_off:
        probs.append(('warn', f'[M1/M2] 構成ファイルが無い: {os.path.basename(spath)}'
                              '（誰に・理解してほしいこと・相談したいこと・一番伝えたいことを先に決める。'
                              '雛形=SlideKit/structure-template.md・不要なら <html data-structure="off">）'))

    # ⑦図解が1枚も無いデッキ → warn（図解の型は16種あるのに文字だけで並ぶのを防ぐ）
    #   型IDが1つも宣言されていないデッキは④が先に指摘するので、ここでは重ねて言わない
    if n_slides >= DIAGRAM_MIN_SLIDES and comments and not structure_off:
        ids = slide_pattern_ids(comments)
        if any(ids) and not any(i and i.startswith('D') for i in ids):
            probs.append(('warn', f'[M5] 図解スライドが0枚（全{n_slides}枚でD系宣言なし）。'
                                  'diagram-catalog.html のD01〜D16に置き換える余地がないか見る'))

    # ⑧1枚に文字を詰め込みすぎ → warn（表セルは除く。実測 p50=279/p95=656/p99=962 で閾値900）
    if not structure_off:
        heavy = []
        for i, chunk in enumerate(re.split(r'(?=<div class="slide")', non_svg)[1:], 1):
            txt = ''.join(re.sub(r'<[^>]+>', '', m)
                          for m in re.findall(r'<div class="tb"[^>]*>([\s\S]*?)</div>', chunk, re.I))
            n = len(re.sub(r'\s+', '', txt))
            if n > TEXT_MAX_CHARS:
                heavy.append(f'{i}枚目{n}字')
        if heavy:
            probs.append(('warn', f'[R2] 1枚の文字が多い: {heavy[:5]}'
                                  f'（目安{TEXT_MAX_CHARS}字。スライドを割るか図解にする）'))

    # ⑤キャンバス外座標（1280×720はみ出し） → warn
    #   2026-11-15: 属性の順番・小数を問わない（編集画面の実測は小数を書く）。data-h の無い表は行数から高さを見積もる。
    #   🚫 以前は data-x data-y data-w data-h がこの順・整数の時しか見ず、30行の表が下へ切れても素通りだった
    off, overflow = _check_geometry(non_svg)
    if off:
        probs.append(('warn', f'[F1] キャンバス外座標: {off[:5]}（1280×720からはみ出し）'
                              + (f' ほか{len(off) - 5}件' if len(off) > 5 else '')))
    if overflow:
        probs.append(('warn', f'[F2] 文字が枠に入らない見込み: {overflow[:5]}'
                              + (f' ほか{len(overflow) - 5}件' if len(overflow) > 5 else '')
                              + '（ブラウザでは切れて見えず、PPTX では下へあふれる。文を減らすか枠を広げる）'))

    # ⑨AWSフォーマットのフッター帯（下44px＝y676〜）に中身がかかる → warn
    #   PPTXではAWSテンプレートのロゴ・著作権表示と重なる。ページ番号（右下の数字）は除く（2026-09-27）
    if re.search(r'<html[^>]*data-template="aws2?"', text):
        hit = []
        for i, chunk in enumerate(re.split(r'(?=<!--\s*SLIDE:)', text)[1:], start=1):
            if re.search(r'data-bg-gradient=', chunk.split('>', 2)[1] if '>' in chunk else ''):
                continue  # 表紙・扉はフッターが無い
            for m in re.finditer(r'<div class="(?:tb|rect|flow)[^"]*"[^>]*?data-x="(\d+)"[^>]*?data-y="(\d+)"'
                                 r'[^>]*?data-w="(\d+)"[^>]*?data-h="(\d+)"[^>]*>([^<]*)', chunk):
                x, y, w, h = map(int, m.groups()[:4])
                if y + h > 676 and not (x >= 1180 and m.group(5).strip().isdigit()):
                    hit.append(f'{i}枚目 y{y}+h{h}')
        if hit:
            probs.append(('warn', f'[F1] AWSフッター帯（y676以下）に中身がかかる: {hit[:5]}'
                                  '（PPTXでロゴ・著作権表示と重なる。y+h を676以内に収める）'))

    # ⑫スライド直下にむき出しのSVG → fail（位置を持たないので、PPTXでは絵ごと消える・2026-10-14 第22回の4コマ）
    bare = []
    for no, chunk, _d in slides:
        depth = 0
        for m in re.finditer(r'<(/?)(div|svg)\b[^>]*>', _strip_code(chunk)):
            if m.group(2) == 'div':
                depth += -1 if m.group(1) else (0 if m.group(0).endswith('/>') else 1)
            elif not m.group(1) and depth == 1:
                bare.append(f'{no}枚目')
    if bare:
        probs.append(('fail', f'[B6] SVGが div で包まれていない: {_few(bare, 8)}'
                              '（PPTXで絵が消える。<div data-x data-y data-w data-h style="position:absolute;…"> の中に入れる）'))

    # ⑪依頼の枠（data-ask＝イラスト・グラフ・写真の用意を頼む枠）が残っている → warn（作りかけの印・2026-10-14）
    asks = [f'{no}枚目 ' + {'illust': 'イラスト', 'chart': 'グラフ', 'photo': '写真'}.get(k, k)
            for no, chunk, _d in slides for k in re.findall(r'data-ask="(\w+)"', chunk)]
    if asks:
        probs.append(('warn', f'[F7] 依頼の枠が残っている: {_few(asks, 8)}'
                              '（枠を選んで「📋 依頼文をコピー」→用意した画像を枠に貼る。グラフは data-chart に置き換える）'))

    # ⑩読む人に向けた言葉（slide-contract-detail.md の「機械で拾う」項目・2026-10-14）
    #   見本帳など人に渡さない資料（data-structure="off"）は対象外
    if not structure_off:
        probs += check_wording(slides)

    return probs


# 言葉の検査: (ID, 正規表現, 何が悪いか, 直し方)
WORDING_RULES = [
    ('A5', re.compile(r'(?<!いた)だけ'), '「〜だけ」で話す範囲を狭めている',
     '「〜だけ」を外す。限る理由があるなら「〜に限る」「〜専用」'),
    ('A5', re.compile(r'次のページ|次ページ|この(?:あと|後)[^。]{0,10}(?:お見せ|ご説明|説明し)'),
     '次のページの予告をしている', 'そのページで話す。予告の文は消す'),
    ('A7', re.compile(r'世界初|国内外に(?:事例が)?(?:無|な)い|公開事例は(?:無|な)い|国際的な空白|文献は皆無|世界で\d+件'),
     '「無いこと」を書いている（確かめられない）', '見つかった事実を肯定形で書く（対象・規模・出典）'),
    # 以下は利用者の文体（.kiro/steering/inouchi-voice.md・2026-10-14「決めつけ、対語などをやめることもルール化したい」）
    ('A8', re.compile(r'(?:本質|核心|正体)(?:です|だ|である|なのは|と言える)|(?<![そど])こそ'),
     '決めつけ（「これが〜の本質です」「〜こそ」）', '事実を書いて止める。自分の考えなら「〜と思っています」'),
    ('A8', re.compile(r'結論から言うと|最も重要なのは|圧倒的|劇的|格段に'),
     '盛り語・前置き', '前置きを消して本題から書く。盛り語は数字か事実に置き換える'),
    ('A9', re.compile(r'ておこう|ておきましょう'),
     '「〜しておこう」「〜しておきましょう」', '「〜する」「〜してください」にする'),
]
# 対比（「AではなくB」「AよりBが大事」）は1文書に1回まで。2回目から知らせる
CONTRAST_RE = re.compile(r'ではなく|じゃなく|より(?:も)?[^。、]{0,12}(?:大事|重要|大切)')
UNDECIDED_RE = re.compile(r'要確認|TBD|調整中|未定')


def _visible_text(chunk):
    """スライドHTMLのうち、読む人に見える文字（script/style/SVG/コメントを除く）"""
    s = re.sub(r'<!--[\s\S]*?-->', '', _strip_code(chunk))
    s = re.sub(r'<svg[\s\S]*?</svg>', '', s)
    import html as _html
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', s)))


def check_wording(slides):
    found = {}
    contrast = []
    for no, chunk, _d in slides:
        t = _visible_text(chunk)
        contrast += [f'{no}枚目「{t[max(0, m.start() - 10):m.end() + 6].strip()}」' for m in CONTRAST_RE.finditer(t)]
        for rid, rx, what, fix in WORDING_RULES:
            for m in rx.finditer(t):
                ctx = t[max(0, m.start() - 10):m.end() + 6].strip()
                found.setdefault((rid, what, fix), []).append(f'{no}枚目「{ctx}」')
        # 未決は「仮＝…」「…までに」「無かったら」のどれかが同じ枚にあれば書けている
        if UNDECIDED_RE.search(t) and not re.search(r'仮|までに|無かった|なかった|取れなければ', t):
            m = UNDECIDED_RE.search(t)
            found.setdefault(('A6', '未決を「要確認」等だけで置いている',
                              '「仮＝○○で進めている／いつ誰から確定をもらう／無かったときの扱い」の3点で書く'),
                             []).append(f'{no}枚目「{t[max(0, m.start() - 10):m.end() + 4].strip()}」')
    if len(contrast) > 1:
        found[('A10', f'対比が{len(contrast)}回（1文書に1回まで）',
               '言い切る形に直す。対立そのものが中身のときだけ1回残す')] = contrast
    return [('warn', f'[{rid}] {what}: {_few(w)}（{fix}）') for (rid, what, fix), w in found.items()]


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
        # ワークスペースの外（/tmp 等）は ../../../ だらけになるのでファイル名だけ出す
        rel = os.path.relpath(full, ROOT)
        if rel.startswith('..'):
            rel = os.path.basename(full)
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
