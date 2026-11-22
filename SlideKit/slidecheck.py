#!/usr/bin/env python3
"""スライドHTMLの検証・変換・目視確認を1コマンドで実行する。

使い方:
  python3 SlideKit/slidecheck.py 対象.html                    # ガード + レイアウト診断
  python3 SlideKit/slidecheck.py 対象.html --pptx             # ＋PPTX変換
  python3 SlideKit/slidecheck.py 対象.html --shot 3           # ＋3枚目のスクショ
  python3 SlideKit/slidecheck.py 対象.html --shot 3,5,12      # ＋複数ページ
  python3 SlideKit/slidecheck.py 対象.html --shot all         # ＋全ページ
  python3 SlideKit/slidecheck.py 対象.html --pptx --shot 2,4
  python3 SlideKit/slidecheck.py 対象.html --bak --shot all --pptx   # 編集前後の定番

文字列の差し替えも同じコマンドでできる（置換 → 検証 → スクショ → 変換が1回で済む）:
  python3 SlideKit/slidecheck.py 対象.html --sub "旧=>新" --shot 10
  python3 SlideKit/slidecheck.py 対象.html --sub "A=>B" --sub "C=>D" --shot all --pptx

--sub は "旧=>新" の形。複数回渡せる。置換件数を出力し、0件の指定には ! が付く。
--sub を使うときはバックアップを自動で取る。座標や属性を変える編集には向かないので、
文言の差し替えに使い、構造を変える編集は str_replace で行う。

スクショは /tmp/slidecheck/<htmlのstem>_pNN.png に保存し、パスを出力する。
2枚以上撮ると <stem>_sheet.png（2列グリッドの一覧）も作る。一覧1枚で全体を確認し、
崩れが疑わしいページだけ個別PNGを開けばよい。

--bak は 対象.bak-MMDD-HHMM.html を同じディレクトリに作る。

読む人の目での点検（構成ファイルの「誰に」・全枚の文字・欠陥分類表M/A・一覧画像を1つのプロンプトに）:
  python3 SlideKit/slidecheck.py 対象.html --review          # /tmp/slidecheck/<stem>_review.md
  python3 SlideKit/slidecheck.py 対象.html --review --copy   # ＋クリップボードへ（外部には送らない）
  python3 SlideKit/slidecheck.py 対象.html --review --as "PwCのパートナー"   # 読ませる立場を変える
新しいチャットに貼って読ませ、返ってきた指摘は採否表にする（defect-taxonomy.md）。

[CUSTOM: 理由] を宣言した枚は、--shot が無くても自動で撮る（型に無い配置は目で確かめる）。

deck-lint（deck_lint.py）がタイトル一覧と、表記ゆれ・数値の食い違い・タイトルの数・禁止語を出す。
用語表は案件フォルダの terms.md、禁止語は forbidden-terms.txt（どちらも対象HTMLから上へたどって読む）。

最初に通した版は .slidekit-v0/ に1回だけ残る（構成ファイルも一緒に）。仕上がったら差を見る:
  python3 SlideKit/slidecheck.py 対象.html --v0diff      # 最初の版 → 今 の文字の差を枚ごとに
  python3 SlideKit/slidecheck.py 対象.html --v0-reset    # 同じ名前で別のデッキを作り直すとき

コマンドはワークスペースルート（SlideKit の親フォルダ）で実行する。
"""
# 開発メモ: 複合コマンド（&&）を使わずに済むよう1本にまとめてある
# （Kiro の trustedCommands は単体コマンド形しか照合しないため）
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = '/tmp/slidecheck'
SLIDE_H = 720          # スライド高さ
SLIDE_GAP = 12         # .slide の margin 上下
BODY_TOP = 20          # body の padding-top


def find_chrome():
    cands = [
        os.environ.get('CHROME_PATH', ''),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def run(label, args, limit=40):
    """サブプロセスを実行し、出力を表示。戻り値は returncode。
    🚫 以前は末尾6行だけ出していたため、警告が多いと先頭に出る🚨（止まった理由）が消えていた（2026-09-27）。
    今は limit 行まで出し、超えたら🚨の行を優先して残す。"""
    print('--- %s' % label)
    r = subprocess.run(args, capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    lines = [x for x in out.strip().split('\n') if x.strip()]
    if len(lines) > limit:
        stops = [x for x in lines if '🚨' in x]
        rest = [x for x in lines if '🚨' not in x]
        keep = stops + rest[:max(0, limit - len(stops))]
        lines = keep + ['…ほか%d行（全文は python3 %s で見られる）'
                        % (len(stops) + len(rest) - len(keep), ' '.join(os.path.basename(a) if a.endswith('.py') else a for a in args[1:]))]
    for line in lines:
        print('   ' + line)
    return r.returncode


def check_script_path(html_path):
    """デッキが読む slide-edit.js が実在するか。切れていると編集UIだけ黙って出ない。"""
    src = open(html_path, encoding='utf-8').read()
    m = re.search(r'<script src="([^"]*slide-edit\.js)"></script>', src)
    if not m:
        return
    ref = m.group(1)
    if re.match(r'^(https?:|file:|/)', ref):
        return
    here = os.path.dirname(html_path)
    if os.path.exists(os.path.normpath(os.path.join(here, ref))):
        return
    right = os.path.relpath(os.path.join(HERE, 'slide-edit.js'), here)
    print('--- script path')
    print('   ⚠️ slide-edit.js が見つかりません: src="%s"' % ref)
    print('      このままだとブラウザで開いても編集ツールバーが出ません（PPTX変換は動きます）')
    print('      直し方: src="%s" にする' % right)


def shoot(html_path, pages):
    """SlideKitのスクリプトを除いた一時HTMLを作り、指定ページを切り出す。"""
    try:
        from PIL import Image
    except ImportError:
        print('   WARN: Pillow が無いためスクショをスキップします')
        return

    chrome = find_chrome()
    if not chrome:
        print('   WARN: Chrome が見つかりません（CHROME_PATH で指定可）')
        return

    src = open(html_path, encoding='utf-8').read()
    total = src.count('<!-- SLIDE:')
    if total == 0:
        print('   WARN: <!-- SLIDE: --> が見つかりません')
        return

    targets = list(range(1, total + 1)) if pages == 'all' else [p for p in pages if 1 <= p <= total]
    if not targets:
        print('   WARN: 対象ページがありません（全%d枚）' % total)
        return

    # 編集UI（.seui）だけ隠した一時HTML（元ファイルは触らない）
    # 🚫 以前は slide-edit.js ごと外していたため、箇条書きの点（skListCss）や AWS 表示が映らず、
    #    ブラウザともPPTXとも違う画像で確認していた（2026-09-27）
    tmp = os.path.join(os.path.dirname(html_path), '.slidecheck-tmp.html')
    hide = '<style>.seui,.seui *{display:none!important}</style>'
    open(tmp, 'w', encoding='utf-8').write(
        src.replace('</head>', hide + '</head>', 1) if '</head>' in src else hide + src)

    os.makedirs(SHOT_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(html_path))[0]
    full = os.path.join(SHOT_DIR, stem + '_full.png')
    height = BODY_TOP + (SLIDE_H + SLIDE_GAP * 2) * total + 80

    try:
        # slide-edit.js は defs/format を後から読むので、描画を待ってから撮る
        # --disk-cache-size=1: 直したJS（slidekit-chart.js など）を古い写しで撮らない（2026-10-15 同じ絵が2回出た）
        subprocess.run([chrome, '--headless', '--disable-gpu', '--disk-cache-size=1',
                        '--virtual-time-budget=4000',
                        '--screenshot=' + full,
                        '--window-size=1300,%d' % height,
                        '--hide-scrollbars', 'file://' + tmp],
                       capture_output=True, timeout=180)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    if not os.path.exists(full):
        print('   WARN: スクショの生成に失敗しました')
        return

    im = Image.open(full)
    for n in targets:
        y = BODY_TOP + (SLIDE_H + SLIDE_GAP * 2) * (n - 1) + SLIDE_GAP
        out = os.path.join(SHOT_DIR, '%s_p%02d.png' % (stem, n))
        im.crop((0, y, 1300, y + SLIDE_H)).save(out)
        print('   ' + out)
    os.remove(full)
    if len(targets) > 1:
        contact_sheet(stem, targets)


def contact_sheet(stem, targets):
    """個別PNGを縮小し2列グリッドに並べた一覧画像を作る。

    枚数が多いデッキでも一覧1枚を見れば全体の流れと崩れを把握できる。
    細部は個別の _pNN.png を見る。"""
    from PIL import Image, ImageDraw
    cols, cw = 2, 640
    ch = int(SLIDE_H * cw / 1300)
    pad, label = 6, 18
    rows = (len(targets) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (cw + pad) + pad,
                              rows * (ch + label + pad) + pad), '#3a4756')
    draw = ImageDraw.Draw(sheet)
    for i, n in enumerate(targets):
        src = os.path.join(SHOT_DIR, '%s_p%02d.png' % (stem, n))
        if not os.path.exists(src):
            continue
        x = pad + (i % cols) * (cw + pad)
        y = pad + (i // cols) * (ch + label + pad)
        draw.text((x + 2, y + 3), 'p%02d' % n, fill='#ffffff')
        sheet.paste(Image.open(src).resize((cw, ch), Image.LANCZOS), (x, y + label))
    out = os.path.join(SHOT_DIR, stem + '_sheet.png')
    sheet.save(out)
    print('   ' + out + '   ← 一覧%d枚' % len(targets))


V0_DIR = '.slidekit-v0'   # 最初の版の置き場（デッキと同じフォルダの下）


def v0_path(html):
    return os.path.join(os.path.dirname(html), V0_DIR, os.path.basename(html))


def save_v0(html, reset=False):
    """最初にslidecheckを通した版を1回だけ残す（2回目以降は上書きしない）。
    決定: AIが作った直後の版と、人が直した後の版の差に、次の規範の手がかりがある。
    🚫 韓国L7資料（2026-09-28）は中身を4回外したが、場当たりの .bak では最初と最後を比べられなかった。
    出典＝太田賢一「Opus5.5の性能を活かす、スライド自動生成の仕組み」（2026-10）"""
    import shutil
    dst = v0_path(html)
    if os.path.exists(dst) and not reset:
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(html, dst)
    st = os.path.splitext(html)[0] + '.structure.md'
    if os.path.exists(st):
        shutil.copy2(st, os.path.splitext(dst)[0] + '.structure.md')
    print('--- v0')
    print('   最初の版を残しました: ' + os.path.relpath(dst))
    print('   仕上がったら --v0diff で差を見る')


def slide_texts(path):
    """[(スライド名, [見えている文字の行], ノート)]。表のセル・.tb・ノートを拾う"""
    from bs4 import BeautifulSoup
    raw = open(path, encoding='utf-8').read()
    names = [re.sub(r'\s*\[[^\]]*\]\s*$', '', c).strip()
             for c in re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->', raw)]
    soup = BeautifulSoup(raw, 'html.parser')
    out = []
    for i, sl in enumerate(soup.select('div.slide')):
        rows = []
        for el in sl.find_all(['div', 'td', 'th']):
            if el.name == 'div' and 'tb' not in (el.get('class') or []):
                continue
            if el.find(['div', 'td', 'th'], class_='tb') or (el.name != 'div' and el.find('div', class_='tb')):
                continue
            t = re.sub(r'\s+', ' ', el.get_text(' ')).strip()
            if t and t not in rows:
                rows.append(t)
        name = names[i] if i < len(names) else f'{i + 1}枚目'
        out.append((name, rows, (sl.get('data-notes') or '').strip()))
    return out


def v0diff(html):
    """最初の版 → 今 の差を、枚ごとに文字だけで出す（座標・色の差は出さない）"""
    import difflib
    from datetime import datetime
    src = v0_path(html)
    if not os.path.exists(src):
        print('最初の版がありません（slidecheck を一度通すと残ります）: ' + os.path.relpath(src))
        return 1
    old, new = slide_texts(src), slide_texts(html)
    when = datetime.fromtimestamp(os.path.getmtime(src)).strftime('%m/%d %H:%M')
    print(f'--- v0diff（最初の版 {when} → 今）')
    old_by = {n: (r, no) for n, r, no in old}
    new_names = [n for n, _r, _no in new]
    changed = 0
    for i, (name, rows, notes) in enumerate(new, 1):
        if name not in old_by:
            print(f'\n {i}枚目「{name}」 追加')
            changed += 1
            continue
        orow, onotes = old_by[name]
        lines = [l for l in difflib.unified_diff(orow, rows, lineterm='', n=0)
                 if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        note_changed = onotes != notes
        if not lines and not note_changed:
            continue
        changed += 1
        print(f'\n {i}枚目「{name}」')
        for l in lines:
            print('   ' + l[0] + ' ' + l[1:][:160])
        if note_changed:
            print('   ＊ノートも変わった')
    for name, _r, _no in old:
        if name not in new_names:
            print(f'\n 「{name}」 削除')
            changed += 1
    print(f'\n変わった枚 {changed} / 今 {len(new)}枚（最初 {len(old)}枚）')
    print('次: 直した理由のうち、次のデッキでも起きそうなものを projects/*.md か lessons に1行で書く')
    return 0


# 自由記述を先に書く・破綻の確認・直す順の上位5件は、jinba-consulting-pptx-skill の
# references/content-review-prompt.md（MIT License）を参考にした（2026-10-18）
REVIEW_ASK = '''## 読み方
{persona}
この資料がどう作られたかは知らされません。推測しなくて大丈夫です。
規約やスキルのファイルは読まず、下の文字と一覧画像で判断してください。

## 1. 最初に自由に書く（3〜10件）
読む人として一番困ること・納得できないこと・自分が決める立場なら突き返す理由を、思いつく順に書いてください。
下の表に無い観点を拾うための欄です。

## 2. 1枚ずつ見上げる
問いは3つです。
・次に何をすればいいか分かるか（指示は、その人が実際にする動作＝話す・書く・見る、になっているか）
・知らない言葉・数えていない番号がないか（作る側の進行語・「第17回」「前々回」など）
・嫌な印象を作っていないか（自分の言葉が晒される・叱られている・配っていないものを「配った」）
見分け方: 文の主語が「講師／提案者／私たち」なら台本。主語が読む人で、動詞が読む人の動作なら通る。

次の欠陥分類表（M・A）と照合してください。自由に眺めず、表のどれに当たるかで見ます。
{taxonomy}

## 3. 破綻を探す（枚番号つき）
・タイトルと、図や最後の囲みの結論が食い違う（タイトルで限っていることを、図で言い切っている）
・裏付けのない評価語（「十分」「問題ない」「最小限」「限定的」）が、その枚に根拠なく置かれている
・後ろの枚が前の枚の繰り返しで、新しい論点が無い
・アジェンダや目次で予告した内容・枚番号と、本編が合わない
・数字を載せた枚に出所が無い。例や試算の断りが要る所に無い
・同じ結論や定義が、枚によって違う言い回しで書かれ、別の主張に読める
・業界・制度の用語が、その分野の定義と違う意味で使われている（正しい用語と根拠を添える）
（表記ゆれ・同じ指標の値の食い違い・タイトルの数と連番は、機械の検査で見ています）

## 出してほしい形
・1の自由な指摘（枚番号・引用・何が困るか）
・2で引っかかった枚ごとに「N枚目　分類ID　元の文 → その人がその場で言いそうな言葉」。無くても成立する文は「消す」
・3の破綻は「N枚目　引用　何が食い違うか」。当たらない項目は書かない
・主張だけを上から読んで話が通るか（M4）を1〜3行
・最後に、直す順に5件。各1〜2文で、どう直すかまで
・欠点を最低3つ挙げる。前置きと総括は書かない
'''

PERSONA_DEFAULT = '下の「読む人」になって読んでください。'
PERSONA_AS = ('あなたは{who}です。この資料を受け取った立場で読んでください。'
              '自分が決める立場なら、何を理由に突き返すかを考えてください。下の「読む人」は、資料を作った側が想定した相手です。')


def _review_texts(path):
    """slide_texts と同じだが、表は1行＝1項目（セルを「｜」でつなぐ）にして読みやすくする"""
    from bs4 import BeautifulSoup
    raw = open(path, encoding='utf-8').read()
    names = [re.sub(r'\s*\[[^\]]*\]\s*$', '', c).strip()
             for c in re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->', raw)]
    out = []
    for i, sl in enumerate(BeautifulSoup(raw, 'html.parser').select('div.slide')):
        rows = []
        for el in sl.find_all(['div', 'tr']):
            if el.name == 'tr':
                t = ' ｜ '.join(re.sub(r'\s+', ' ', c.get_text(' ')).strip() for c in el.find_all(['td', 'th']))
            elif 'tb' in (el.get('class') or []) and not el.find_parent('table') \
                    and not el.find('div', class_='tb'):
                t = re.sub(r'\s+', ' ', el.get_text(' ')).strip()
            else:
                continue
            if t.strip(' ｜') and t not in rows:
                rows.append(t)
        out.append((names[i] if i < len(names) else f'{i + 1}枚目', rows, (sl.get('data-notes') or '').strip()))
    return out


def review_prompt(html, who=None):
    """読む人の目で点検するためのプロンプトを作る（外部に送らない。ファイルとクリップボードに出すだけ）
    who: 読ませる立場（--as "PwCのパートナー"）。無ければ構成ファイルの「誰に」の人として読む"""
    stem = os.path.splitext(os.path.basename(html))[0]
    st = os.path.splitext(html)[0] + '.structure.md'
    if os.path.exists(st):
        # 冒頭（誰に・理解してほしいこと…）だけ渡す。枚ごとの設計はスライドの文字と重なる
        reader = re.split(r'(?m)^## \d', open(st, encoding='utf-8').read(), maxsplit=1)[0]
        # 構成ファイルのコメント（根拠・作り方のメモ）は渡さない。作った経緯を知らない目で読ませるため
        reader = re.sub(r'<!--[\s\S]*?-->\s*', '', reader).strip()
    else:
        reader = '（構成ファイルが無い。読む人を先に決める＝SlideKit/structure-template.md）'
    tax = os.path.join(HERE, 'defect-taxonomy.md')
    # \d+ ＝ M10 以降の2桁のIDも拾う（2026-10-31・M14を足したとき、1桁のIDしか拾っていなかった）
    rows = [l for l in open(tax, encoding='utf-8').read().splitlines() if re.match(r'^\| [MA]\d+ ', l)] \
        if os.path.exists(tax) else []
    raw = open(html, encoding='utf-8').read()
    ids = [re.search(r'\[([^\]]*)\]\s*$', c.strip()) for c in re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->', raw)]
    out = [f'# 読む人の目での点検: {os.path.basename(html)}', '',
           '## 読む人（構成ファイル）', reader, '',
           REVIEW_ASK.format(taxonomy='\n'.join(rows),
                             persona=PERSONA_AS.format(who=who) if who else PERSONA_DEFAULT),
           '## スライドの文字']
    for i, (name, lines, notes) in enumerate(_review_texts(html)):
        tag = f' [{ids[i].group(1)}]' if i < len(ids) and ids[i] else ''
        out.append(f'\n### {i + 1}枚目「{name}」{tag}')
        out += ['・' + l for l in lines]
        if notes:
            out.append('（ノート）' + notes)
    sheet = os.path.join(SHOT_DIR, stem + '_sheet.png')
    out += ['', '## 一覧画像', f'{sheet}（この画像も一緒に見る。崩れより、読む人がどう受け取るかを見る）']
    return '\n'.join(out) + '\n'


def backup(html):
    """タイムスタンプ付きバックアップを同じディレクトリに作る。"""
    import shutil
    from datetime import datetime
    stem, ext = os.path.splitext(html)
    dst = '%s.bak-%s%s' % (stem, datetime.now().strftime('%m%d-%H%M'), ext)
    shutil.copy2(html, dst)
    print('--- backup')
    print('   ' + dst)


def parse_subs(argv):
    """--sub "旧=>新" を全部集める。同じ指定を複数回渡せる。"""
    subs = []
    for i, a in enumerate(argv):
        if a == '--sub' and i + 1 < len(argv):
            v = argv[i + 1]
            if '=>' in v:
                old, new = v.split('=>', 1)
                subs.append((old, new))
            else:
                print('   WARN: --sub は "旧=>新" の形で渡してください: ' + v)
    return subs


def apply_subs(html, subs):
    """置換を適用して件数を報告する。0件の指定は ! を付けて目立たせる。"""
    print('--- substitute')
    s = open(html, encoding='utf-8').read()
    total = 0
    for old, new in subs:
        n = s.count(old)
        total += n
        s = s.replace(old, new)
        print('%s %d件  %s  ->  %s' % ('   ' if n else '  !', n, old[:38], new[:38]))
    if total:
        open(html, 'w', encoding='utf-8').write(s)
    else:
        print('   どれも当たらずファイルは変更していません')
    return total


def parse_files(argv):
    """オプションとその値を除いた位置引数（対象HTML）を返す。"""
    takes_value = {'--shot', '--sub', '--as'}
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a.startswith('--'):
            skip = a in takes_value
            continue
        out.append(a)
    return out


def parse_shot(argv):
    """--shot の値を返す。'all' か ページ番号のリスト。指定なしは None。"""
    if '--shot' not in argv:
        return None
    i = argv.index('--shot')
    if i + 1 >= len(argv):
        return 'all'
    v = argv[i + 1].strip()
    if v == 'all':
        return 'all'
    pages = []
    for part in v.replace(' ', '').split(','):
        if part.isdigit():
            pages.append(int(part))
    return pages or 'all'


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        print(__doc__)
        return 0
    files = parse_files(argv)
    if not files:
        print(__doc__)
        return 1

    html = files[0]
    if not os.path.isabs(html):
        html = os.path.abspath(html)
    if not os.path.exists(html):
        print('ファイルが見つかりません: ' + html)
        return 1

    print('対象: ' + html)
    if '--v0diff' in argv:
        return v0diff(html)
    # 最初の版を残す（置換より前＝手を入れる前の版）
    save_v0(html, reset='--v0-reset' in argv)
    check_script_path(html)

    # 0) 置換。--sub を使うときは必ずバックアップを取る
    subs = parse_subs(argv)
    if '--bak' in argv or subs:
        backup(html)
    if subs:
        apply_subs(html, subs)

    # 1) 静的ガード（フォント下限・許可外クラス・色トークン）
    if run('slide-guard', ['python3', os.path.join(HERE, 'slide-guard.py'), html]) != 0:
        print('!! ガードで停止級の違反あり。修正してから再実行してください')
        return 1

    # 2) レイアウト診断（Chrome headless。はみ出し・重なり）
    run('run_check', ['python3', os.path.join(HERE, 'run_check.py'), html])

    # 2b) 実測（ブラウザの見た目とPPTXの読み取りの食い違い・PPTXに出ない文字・カードのあふれ）
    #     型に無い配置（[CUSTOM]）を許す代わりに、ここで受ける（2026-10-14）
    run('measure', ['python3', os.path.join(HERE, 'measure_layout.py'), html, '--max', '12'], limit=16)

    # 2c) デッキ全体の文字を横に見る（タイトル一覧・表記ゆれ・数値の食い違い・タイトルの数・禁止語）
    #     2026-10-18 jinba-consulting-pptx-skill の check_deck.py を参考に追加。止めずに出すだけ
    run('deck-lint', ['python3', os.path.join(HERE, 'deck_lint.py'), html], limit=60)
    # 2d) 発表時間の見積もり（ノート or 本文の文字数 ÷ 300字/分）。止めずに出すだけ（2026-11-14）
    run('deck-timing', ['python3', os.path.join(HERE, 'deck_timing.py'), html], limit=30)

    # 3) スクショ（表は自動高さのため診断で検出できない。目視が必要）
    #    [CUSTOM] の枚は型の座標の裏付けが無いので、指定が無くても撮る
    pages = parse_shot(argv)
    if '--review' in argv:
        pages = 'all'
    custom = [i for i, c in enumerate(re.findall(r'<!--\s*SLIDE:\s*([\s\S]*?)-->',
                                                 open(html, encoding='utf-8').read()), 1) if '[CUSTOM' in c]
    if pages is None and custom:
        pages = custom
        print('--- [CUSTOM] の枚を撮る: ' + ','.join(map(str, custom)) + '枚目（型に無い配置なので目で確かめる）')
    if pages is not None:
        print('--- screenshot')
        shoot(html, pages)

    # 3b) 読む人の目での点検プロンプト（外部に送らない。ファイルに書き、--copy でクリップボードへ）
    if '--review' in argv:
        stem = os.path.splitext(os.path.basename(html))[0]
        dst = os.path.join(SHOT_DIR, stem + '_review.md')
        who = argv[argv.index('--as') + 1] if '--as' in argv and argv.index('--as') + 1 < len(argv) else None
        with open(dst, 'w', encoding='utf-8') as f:
            f.write(review_prompt(html, who))
        print('--- review')
        print('   ' + dst)
        print('   ← 新しいチャットに貼って読ませる（作った経緯を知らない目で読むため。一覧画像も添付）')
        print('   返ってきた指摘は採否表にする（defect-taxonomy.md「レビューの指摘の受け方」）')
        if '--copy' in argv and sys.platform == 'darwin':
            subprocess.run(['pbcopy'], input=open(dst, encoding='utf-8').read(), text=True)
            print('   クリップボードにコピーしました')

    # 4) PPTX変換
    if '--pptx' in argv:
        run('html_to_pptx', ['python3', os.path.join(HERE, 'html_to_pptx.py'), html])

    print('--- done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
