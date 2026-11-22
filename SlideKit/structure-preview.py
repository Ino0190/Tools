#!/usr/bin/env python3
"""構成ファイル（<deck>.structure.md）を1枚のHTMLにして目で見られるようにする。

    python3 SlideKit/structure-preview.py 対象.structure.md [-o 出力.html]
    （-o 省略時は <deck>.structure.html を同じ場所に作る）

決定: 構成の正本は .structure.md のまま。テキストだと全体像がつかめないので、
見るための入れ物だけを生成する（二重管理しない＝HTMLは毎回作り直す使い捨て）。
根拠=.kiro/steering/projects/kiro-operations.md

出すもの:
  ・読み手／相手が下す判断／渡し方（空なら赤で出す）
  ・スライドのサムネイル格子（型IDから骨組みの形を描く・主張と根拠つき）
  ・見出しだけを縦に並べたリスト（上から読んで話が通るかを見る）
  ・警告帯（型ID未宣言・主張が空・図解0枚）
  ・骨格（役割ごとの枚・論点ごとの枚数・欠けた役割。「- 役割:」を書いた構成ファイルに限る・2026-10-31）
"""
import os
import re
import sys

# 型ID → (分類, 骨組みの形)。形は draw() が解釈する
KIND = {
    'P01': ('A 導入', 'cover'), 'P03': ('A 導入', 'cover'), 'P12': ('A 導入', 'cover'),
    'P14': ('A 導入', 'cover'), 'P02': ('A 導入', 'list'), 'P13': ('A 導入', 'list'),
    'P04': ('B 文字', 'body'), 'P17': ('B 文字', 'indent'),
    'P05': ('C 数と比較', 'col3'), 'P06': ('C 数と比較', 'col2'),
    'P07': ('C 数と比較', 'table'), 'P18': ('C 数と比較', 'table'),
    'P09': ('C 数と比較', 'kpi'), 'D09': ('C 数と比較', 'bars'),
    'D12': ('C 数と比較', 'table'),
    'P08': ('D 構造', 'flow'), 'D13': ('D 構造', 'flow'), 'D15': ('D 構造', 'flow'),
    'D01': ('D 構造', 'branch'), 'D02': ('D 構造', 'stack'), 'D03': ('D 構造', 'cycle'),
    'D04': ('D 構造', 'quad'), 'D07': ('D 構造', 'hub'), 'D08': ('D 構造', 'steps3'),
    'D10': ('D 構造', 'venn'), 'D11': ('D 構造', 'todo'), 'D14': ('D 構造', 'cycle'),
    'P10': ('E 時間', 'time'), 'D05': ('E 時間', 'time'), 'D06': ('E 時間', 'gantt'),
    'D16': ('E 時間', 'time'),
    'P11': ('F 画像', 'img-side'), 'P15': ('F 画像', 'img-full'), 'P16': ('F 画像', 'img-around'),
}
# 画像型の枠実寸（pattern-catalog.html の値）。素材を頼む前にこの比率を伝えるため
IMG_FRAME = {'P11': (560, 400, ''), 'P15': (1280, 720, '・全面／coverでトリミング'),
             'P16': (600, 380, ''), 'D11': (0, 0, '図は未確定')}
# 2026-10-31 に足した欄。行が無い古い構成ファイルでは出さない
NEW_META = ('目的', '知ってほしいこと', '骨格')
# 骨格の4つの役割（2026-10-31 利用者「この項目がカバーできているかを検討するのが良さそう」）。
# 役割の書き出しで寄せる＝「説明・報告（計測体験）」は説明・報告、「論点のサマリ」は振り返りと論点
ROLES = (('アジェンダ', ('アジェンダ',)), ('振り返りと論点', ('振り返り', '論点')),
         ('説明・報告', ('説明', '報告')), ('次回に向けた確認', ('次回',)))
ROLE_FREE = ('P01', 'P03', 'P14')  # 表紙・扉・終わりの枚は役割を書かなくてよい
SAME_TOPIC_WARN = 3  # 同じ論点の枚がこの数以上なら「まとめられないか」を出す
GROUP_COLOR = {'A 導入': '#162a42', 'B 文字': '#21537f', 'C 数と比較': '#1a5a32',
               'D 構造': '#7a471a', 'E 時間': '#5e5e5e', 'F 画像': '#742323',
               'CUSTOM': '#c62828', '未宣言': '#c62828'}
_H = r'[ \t\u3000]*'


def draw(shape, color):
    """骨組みを320×180のSVGで描く。中身は描かず「どういう形の面か」だけを示す"""
    r = f'<rect x="0" y="0" width="320" height="180" fill="#ffffff" stroke="#d4dde7"/>'
    c, g = color, '#d4dde7'
    bar = f'<rect x="18" y="16" width="140" height="12" fill="{c}"/>'
    parts = {
        'cover': f'<rect x="0" y="0" width="320" height="180" fill="{c}"/>'
                 f'<rect x="60" y="74" width="200" height="16" fill="#fafafa"/>'
                 f'<rect x="100" y="100" width="120" height="8" fill="#9fc0dd"/>',
        'list': bar + ''.join(f'<rect x="24" y="{50 + i * 24}" width="{200 - i * 10}" height="10" fill="{g}"/>'
                              f'<circle cx="18" cy="{55 + i * 24}" r="4" fill="{c}"/>' for i in range(4)),
        'body': bar + f'<rect x="18" y="40" width="284" height="10" fill="{g}"/>' +
                ''.join(f'<rect x="28" y="{64 + i * 22}" width="{250 - i * 20}" height="9" fill="{g}"/>' for i in range(4)),
        'indent': bar + ''.join(f'<rect x="{24 + (i % 2) * 20}" y="{46 + i * 22}" width="{220 - (i % 2) * 40}" '
                                f'height="9" fill="{g}"/>' for i in range(5)),
        'col3': bar + ''.join(f'<rect x="{18 + i * 98}" y="46" width="88" height="112" fill="none" stroke="{c}" '
                              f'stroke-width="2"/><rect x="28" y="60" width="0" height="0"/>' for i in range(3)),
        'col2': bar + ''.join(f'<rect x="{18 + i * 152}" y="46" width="142" height="112" fill="none" stroke="{c}" '
                              f'stroke-width="2"/>' for i in range(2)) +
                f'<text x="160" y="108" font-size="20" fill="{c}" text-anchor="middle">→</text>',
        'table': bar + ''.join(f'<line x1="18" y1="{46 + i * 22}" x2="302" y2="{46 + i * 22}" stroke="{g}"/>'
                              for i in range(6)) +
                 ''.join(f'<line x1="{18 + i * 71}" y1="46" x2="{18 + i * 71}" y2="156" stroke="{g}"/>' for i in range(5)) +
                 f'<rect x="18" y="46" width="284" height="22" fill="{c}" opacity=".25"/>',
        'kpi': bar + ''.join(f'<rect x="{18 + i * 98}" y="56" width="88" height="80" fill="{c}" opacity=".12"/>'
                             f'<rect x="{34 + i * 98}" y="80" width="56" height="24" fill="{c}"/>' for i in range(3)),
        'bars': bar + ''.join(f'<rect x="{34 + i * 60}" y="{150 - h}" width="34" height="{h}" fill="{c}"/>'
                              for i, h in enumerate((40, 70, 55, 95))) +
                f'<line x1="18" y1="152" x2="302" y2="152" stroke="{g}"/>',
        'flow': bar + ''.join(f'<rect x="{16 + i * 76}" y="76" width="60" height="44" fill="none" stroke="{c}" '
                              f'stroke-width="2"/>' + (f'<text x="{80 + i * 76}" y="103" font-size="14" fill="{c}">→</text>'
                                                       if i < 3 else '') for i in range(4)),
        'branch': bar + f'<rect x="130" y="46" width="60" height="30" fill="none" stroke="{c}" stroke-width="2"/>'
                        f'<line x1="160" y1="76" x2="80" y2="110" stroke="{c}"/><line x1="160" y1="76" x2="240" y2="110" stroke="{c}"/>'
                        f'<rect x="40" y="110" width="80" height="34" fill="none" stroke="{g}" stroke-width="2"/>'
                        f'<rect x="200" y="110" width="80" height="34" fill="none" stroke="{g}" stroke-width="2"/>',
        'stack': bar + ''.join(f'<rect x="40" y="{50 + i * 36}" width="240" height="28" fill="{c}" '
                               f'opacity="{0.5 - i * 0.12:.2f}"/>' for i in range(3)),
        'cycle': bar + f'<circle cx="160" cy="105" r="46" fill="none" stroke="{c}" stroke-width="2"/>' +
                 ''.join(f'<circle cx="{160 + int(46 * x)}" cy="{105 + int(46 * y)}" r="9" fill="{c}"/>'
                         for x, y in ((0, -1), (1, 0), (0, 1), (-1, 0))),
        'quad': bar + f'<rect x="60" y="46" width="200" height="110" fill="none" stroke="{g}"/>'
                      f'<line x1="160" y1="46" x2="160" y2="156" stroke="{c}"/>'
                      f'<line x1="60" y1="101" x2="260" y2="101" stroke="{c}"/>',
        'hub': bar + f'<circle cx="160" cy="105" r="22" fill="{c}"/>' +
               ''.join(f'<circle cx="{160 + dx}" cy="{105 + dy}" r="13" fill="none" stroke="{c}" stroke-width="2"/>'
                       f'<line x1="160" y1="105" x2="{160 + dx}" y2="{105 + dy}" stroke="{g}"/>'
                       for dx, dy in ((-80, -30), (80, -30), (-80, 30), (80, 30))),
        'steps3': bar + ''.join(f'<rect x="18" y="{48 + i * 36}" width="284" height="28" fill="{c}" opacity=".15"/>'
                                f'<rect x="18" y="{48 + i * 36}" width="70" height="28" fill="{c}"/>' for i in range(3)),
        'venn': bar + f'<circle cx="130" cy="105" r="46" fill="{c}" opacity=".25"/>'
                      f'<circle cx="190" cy="105" r="46" fill="{c}" opacity=".25"/>',
        'todo': bar + f'<rect x="40" y="50" width="240" height="106" fill="none" stroke="{c}" '
                      f'stroke-width="2" stroke-dasharray="8 6"/>'
                      f'<text x="160" y="110" font-size="13" fill="{c}" text-anchor="middle">図は未確定</text>',
        'time': bar + f'<line x1="24" y1="105" x2="296" y2="105" stroke="{c}" stroke-width="2"/>' +
                ''.join(f'<circle cx="{40 + i * 60}" cy="105" r="7" fill="{c}"/>'
                        f'<rect x="{26 + i * 60}" y="120" width="44" height="8" fill="{g}"/>' for i in range(5)),
        'gantt': bar + ''.join(f'<rect x="{30 + i * 22}" y="{50 + i * 26}" width="{120 - i * 10}" height="16" '
                               f'fill="{c}" opacity=".6"/>' for i in range(4)),
        'img-full': f'<rect x="0" y="0" width="320" height="180" fill="{g}"/>'
                    f'<line x1="0" y1="0" x2="320" y2="180" stroke="#ffffff"/>'
                    f'<line x1="320" y1="0" x2="0" y2="180" stroke="#ffffff"/>'
                    f'<rect x="0" y="126" width="320" height="34" fill="{c}" opacity=".8"/>',
        'img-side': bar + f'<rect x="18" y="46" width="150" height="112" fill="{g}"/>'
                          f'<line x1="18" y1="46" x2="168" y2="158" stroke="#ffffff"/>' +
                    ''.join(f'<rect x="184" y="{56 + i * 24}" width="118" height="9" fill="{g}"/>' for i in range(4)),
        'img-around': f'<rect x="90" y="40" width="140" height="100" fill="{g}"/>'
                      f'<line x1="90" y1="40" x2="230" y2="140" stroke="#ffffff"/>' +
                      ''.join(f'<rect x="{x}" y="{y}" width="70" height="9" fill="{g}"/>'
                              for x, y in ((10, 60), (240, 60), (10, 100), (240, 100), (120, 156))),
    }
    return f'<svg viewBox="0 0 320 180" width="100%">{r}{parts.get(shape, bar)}</svg>'


def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def parse(path):
    """構成ファイルを読んで (デッキ名, メタ, スライドの列) にする"""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    text = re.sub(r'<!--[\s\S]*?-->', '', text)  # 雛形の注記は読み飛ばす
    m = re.search(r'^#\s+(.+)$', text, re.M)
    title = m.group(1).strip() if m else os.path.basename(path)
    meta = {}
    for key in ('目的', '誰に', '理解してほしいこと', '知ってほしいこと', '相談したいこと', '一番伝えたいこと',
                'キースライド', '渡し方', '骨格'):
        mm = re.search(rf'^[-*・]{_H}{key}{_H}[:：]{_H}(.*)$', text, re.M)
        if mm is None and key in NEW_META:
            continue  # 2026-10-31 より前の構成ファイルには無い欄。行が無ければ出さない（古いファイルで「空」を増やさない）
        meta[key] = (mm.group(1).strip() if mm else '')
    slides = []
    for b in re.split(r'^##\s+', text, flags=re.M)[1:]:
        head = b.splitlines()[0].strip()
        idm = re.search(r'\[(P\d{2}|D\d{2}|CUSTOM:[^\]]+)\]\s*$', head)
        pid = idm.group(1) if idm else None
        pid = 'CUSTOM' if pid and pid.startswith('CUSTOM') else pid
        name = re.sub(r'\s*\[[^\]]*\]\s*$', '', head)
        name = re.sub(r'^\d+\.\s*', '', name)
        get = lambda k: (re.search(rf'^[-*・]{_H}{k}{_H}[:：]{_H}(.*)$', b, re.M) or [None, ''])[1].strip() \
            if re.search(rf'^[-*・]{_H}{k}{_H}[:：]', b, re.M) else ''
        slides.append({'name': name, 'id': pid, 'claim': get('主張'),
                       'basis': get('根拠'), 'asset': get('素材'), 'dens': get('濃淡'), 'role': get('役割')})
    return title, meta, slides


def role_of(s):
    """枚の役割を4つのどれかに寄せる。書いていなければ ''、4つに当たらなければ 'その他'"""
    for name, heads in ROLES:
        if s['role'].startswith(heads):
            return name
    return 'その他' if s['role'] else ''


def skeleton(meta, slides):
    """骨格＝4つの役割がそろっているか・同じ論点の枚が重なっていないかを見る。
    決定: 「- 役割:」を1枚も書いていない構成ファイル（2026-10-31より前）は見ない＝既存デッキで警告を増やさない。
    返り値は (警告の列, 役割ごとの枚を並べたHTML)"""
    if not any(s['role'] for s in slides):
        return [], ''
    have, topics = {}, {}
    for i, s in enumerate(slides, 1):
        r = role_of(s)
        have.setdefault(r, []).append(i)
        if r == '説明・報告':
            tm = re.search(r'[（(]([^）)]+)[）)]', s['role'])
            topics.setdefault(tm.group(1).strip() if tm else '', []).append(i)
    warn = []
    missing = [n for n, _h in ROLES if n not in have and n not in meta.get('骨格', '')]
    if missing:
        warn.append(f'骨格の欠け: {"・".join(missing)}（足すか、最初の欄に「- 骨格: 〇〇は無し（理由）」と書く）')
    bare = [i for i in have.get('', []) if (slides[i - 1]['id'] or '') not in ROLE_FREE]
    if bare:
        warn.append('役割が無い枚: ' + '・'.join(f'{i}枚目' for i in bare[:8]))
    if topics.get(''):
        warn.append('説明・報告で論点が無い枚: ' + '・'.join(f'{i}枚目' for i in topics[''][:8])
                    + '（（ ）に論点の名前を書く）')
    for t, nos in topics.items():
        if t and len(nos) >= SAME_TOPIC_WARN:
            warn.append(f'同じ論点の枚が{len(nos)}枚: {t}（{"・".join(map(str, nos))}枚目）。1枚にまとめられないか')
    rows = []
    for n, _h in ROLES:
        rows.append(f'<div class="m"><dt>{n}</dt>' + (f'<dd>{"・".join(map(str, have[n]))}枚目</dd>' if n in have
                    else '<dd class="empty">無し</dd>') + '</div>')
    if 'その他' in have:
        rows.append(f'<div class="m"><dt>その他</dt><dd>{"・".join(map(str, have["その他"]))}枚目</dd></div>')
    rows += [f'<div class="m"><dt>論点：{esc(t)}</dt><dd>{len(nos)}枚（{"・".join(map(str, nos))}枚目）</dd></div>'
             for t, nos in topics.items() if t]
    return warn, '<h2>骨格（役割ごとの枚）</h2><dl>' + ''.join(rows) + '</dl>'


def frame_note(s):
    """画像型なら枠の実寸と比を出す。素材が書かれていなければ赤で促す。

    決定: 素材を頼む前に枠の比率を先に出す。これが無いと横長の枠に縦長の写真を
    当てる指定になる（2026-08-21 利用者指摘）。
    """
    fr = IMG_FRAME.get(s['id'] or '')
    out = ''
    if fr and fr[0]:
        w, h, note = fr
        out += (f'<div class="frame">枠 {w}×{h}px（{w / h:.2f}:1 の横長{note}）'
                f'<br>この比率で用意する。縦長の写真は入らない</div>')
    if s['asset']:
        out += f'<div class="asset">素材: {esc(s["asset"])}</div>'
    elif fr:
        out += '<div class="asset missing">素材が未定（何の絵かを書く）</div>'
    return out


def build(title, meta, slides, src_name):
    warn = []
    tentative = [k for k, v in meta.items() if v.startswith('[仮]')]
    if tentative:
        warn.append(f'黄色の{len(tentative)}件はPJメモからの仮です（{"・".join(tentative)}）。'
                    '違うところを直してください。合っていれば [仮] を外します')
    for k in ('誰に', '理解してほしいこと'):
        if not meta[k]:
            warn.append(f'{k}が空（このままだと変換が止まる）')
    for k in ('相談したいこと', '一番伝えたいこと'):
        if not meta[k]:
            warn.append(f'{k}が空')
    if '目的' in meta and not meta['目的']:
        warn.append('目的が空（この資料で何をする場か）')
    no_id = [s['name'] for s in slides if not s['id']]
    if no_id:
        warn.append(f'型ID未宣言 {len(no_id)}枚: ' + '／'.join(no_id[:4]))
    no_claim = [s['name'] for s in slides if not s['claim']]
    if no_claim:
        warn.append(f'主張が空 {len(no_claim)}枚: ' + '／'.join(no_claim[:4]))
    # 濃淡（山と谷）。検査の正本は slide-guard.py の check_density。ここは見る人向けの言い直し
    kv = meta.get('キースライド', '')
    km = re.search(r'\d+', kv)
    key = int(km.group(0)) if km else None
    no_key = kv.startswith('なし') or not kv   # 「なし」＝分科会・報告など／空＝この項目ができる前の構成ファイル
    if not no_key and not key:
        warn.append('キースライドが未定（1枚だけ見せるならどの枚か。分科会・報告なら「なし」）')
    dense = [i for i, s in enumerate(slides, 1) if s['dens'].startswith('濃い')]
    if no_key:
        pass
    elif not any(s['dens'] for s in slides):
        warn.append('濃淡が未記入（キースライドの前後を「濃い」、他を「薄め」）')
    else:
        if key and key not in dense:
            warn.append(f'キースライド（{key}枚目）が「濃い」になっていない')
        if sum(1 for j, n in enumerate(dense) if j == 0 or n != dense[j - 1] + 1) > 1:
            warn.append(f'「濃い」が分かれている（{dense}枚目）。山は1か所')
        if len(dense) * 2 > len(slides):
            warn.append(f'「濃い」が{len(dense)}/{len(slides)}枚。半分を超えると山にならない')
    if len(slides) >= 6 and not any((s['id'] or '').startswith('D') for s in slides):
        warn.append(f'図解が0枚（全{len(slides)}枚）。文字ばかりになっていないか')
    sk_warn, sk_html = skeleton(meta, slides)
    warn += sk_warn

    cards = []
    for i, s in enumerate(slides, 1):
        grp, shape = KIND.get(s['id'] or '', ('未宣言' if not s['id'] else 'CUSTOM', 'body'))
        col = GROUP_COLOR.get(grp, '#21537f')
        is_key = (i == key)
        dcls = ' dense' if s['dens'].startswith('濃い') else (' light' if s['dens'].startswith('薄め') else '')
        cards.append(
            f'<div class="card{" tent" if s["claim"].startswith("[仮]") else ""}{dcls}{" key" if is_key else ""}">'
            f'<div class="thumb">{draw(shape, col)}'
            f'<span class="no">{i}</span>'
            + ('<span class="keytag">キースライド</span>' if is_key else '')
            + (f'<span class="dtag">{esc(s["dens"][:2])}</span>' if s['dens'] else '')
            + '</div>'
            f'<div class="meta"><span class="pid" style="background:{col}">'
            f'{esc(s["id"] or "型ID未宣言")}</span><span class="grp">{esc(grp)}</span></div>'
            + (f'<div class="role">{esc(s["role"])}</div>' if s['role'] else '')
            + f'<div class="name">{esc(s["name"])}</div>'
            f'<div class="claim{"" if s["claim"] else " empty"}">'
            f'{esc(s["claim"] or "主張が空")}</div>'
            + (f'<div class="basis">根拠: {esc(s["basis"])}</div>' if s['basis'] else '')
            + frame_note(s) + '</div>')

    heads = ''.join(f'<li>{esc(s["claim"] or s["name"])}</li>' for s in slides)
    metarow = ''.join(
        f'<div class="m"><dt>{k}</dt><dd class="'
        f'{"empty" if not v else ("tent" if v.startswith("[仮]") else "")}">'
        f'{esc(v or "空")}</dd></div>'
        for k, v in meta.items())
    warns = ('<ul class="warn">' + ''.join(f'<li>{esc(w)}</li>' for w in warn) + '</ul>') if warn \
        else '<p class="ok">この構成で作れる（最初の欄・型ID・主張・濃淡がそろっている）</p>'
    return TEMPLATE.format(title=esc(title), src=esc(src_name), n=len(slides),
                           meta=metarow, warns=warns, skeleton=sk_html, cards=''.join(cards), heads=heads)


TEMPLATE = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>構成 — {title}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Meiryo UI','Yu Gothic','Noto Sans JP',sans-serif;background:#eef3f8;color:#121212;
padding:28px 32px 64px;line-height:1.6}}
h1{{font-size:26px;color:#21537f}} .src{{font-size:13px;color:#718096;margin:4px 0 24px}}
dl{{display:flex;flex-wrap:wrap;gap:0;background:#fff;border:1px solid #d4dde7;margin-bottom:20px}}
.m{{display:flex;width:100%;border-bottom:1px solid #eef3f8}} .m:last-child{{border-bottom:0}}
dt{{width:190px;flex:none;background:#162a42;color:#fafafa;font-size:14px;padding:10px 14px;font-weight:700}}
dd{{padding:10px 14px;font-size:16px}} dd.empty,.claim.empty{{color:#c62828;font-weight:700}}
dd.tent{{background:#f4f4ef;border-left:4px solid #7a471a}}
.card.tent .claim{{background:#f4f4ef;border-left:4px solid #7a471a;padding-left:8px}}
ul.warn{{background:#f7f2f2;border-left:5px solid #c62828;padding:12px 16px 12px 34px;margin-bottom:20px;font-size:15px}}
p.ok{{background:#edf2f4;border-left:5px solid #1a5a32;padding:12px 16px;margin-bottom:20px;font-size:15px}}
h2{{font-size:18px;color:#21537f;margin:26px 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid #d4dde7;padding:10px 12px 12px}}
.thumb{{position:relative;margin:-10px -12px 8px}} .no{{position:absolute;left:0;top:0;background:#162a42;
color:#fafafa;font-size:13px;padding:2px 8px}}
.meta{{display:flex;gap:8px;align-items:center;margin-bottom:6px}}
.pid{{color:#fafafa;font-size:12px;font-weight:700;padding:2px 8px}} .grp{{font-size:12px;color:#718096}}
.name{{font-size:15px;font-weight:700;margin-bottom:4px}}
.role{{font-size:12px;color:#21537f;font-weight:700;margin-bottom:2px}}
.claim{{font-size:14px}} .basis{{font-size:12px;color:#718096;margin-top:6px}}
.asset{{font-size:12px;color:#7a471a;background:#f4f4ef;padding:4px 8px;margin-top:6px}}
.asset.missing{{color:#c62828;background:#f7f2f2;font-weight:700}}
.card.key{{outline:3px solid #c62828;outline-offset:-1px}} .card.light{{opacity:.82}}
.keytag{{position:absolute;right:0;top:0;background:#c62828;color:#fafafa;font-size:12px;font-weight:700;padding:2px 8px}}
.dtag{{position:absolute;left:0;bottom:0;background:#fafafa;color:#162a42;font-size:12px;font-weight:700;padding:1px 8px;border:1px solid #d4dde7}}
.card.dense .dtag{{background:#162a42;color:#fafafa}}
.frame{{font-size:12px;color:#fafafa;background:#5e5e5e;padding:4px 8px;margin-top:6px}}
ol.heads{{background:#fff;border:1px solid #d4dde7;padding:14px 18px 14px 44px;font-size:15px}}
ol.heads li{{margin-bottom:6px}}
</style></head><body>
<h1>{title}</h1>
<p class="src">構成ファイル: {src} ／ 全{n}枚 ／ これは見るための生成物。直すのは .structure.md の方</p>
<dl>{meta}</dl>
{warns}
{skeleton}
<h2>主張だけを上から読む（これで話が通らなければ順序か主張が悪い）</h2>
<ol class="heads">{heads}</ol>
<h2>スライドの並び（枠は型の形。中身は入っていない）</h2>
<div class="grid">{cards}</div>
</body></html>
'''


def main():
    args = [a for a in sys.argv[1:] if a != '-o']
    if not args:
        print(__doc__)
        return 1
    src = os.path.abspath(args[0])
    if not os.path.exists(src):
        print(f'構成ファイルが見つからない: {src}')
        return 1
    out = os.path.abspath(sys.argv[sys.argv.index('-o') + 1]) if '-o' in sys.argv \
        else re.sub(r'\.md$', '.html', src)
    title, meta, slides = parse(src)
    if not slides:
        print('スライドの節（## 見出し）が1つも無い')
        return 1
    with open(out, 'w', encoding='utf-8') as f:
        f.write(build(title, meta, slides, os.path.basename(src)))
    empty = [k for k in ('誰に', '理解してほしいこと') if not meta[k]]
    print(f'構成プレビュー: {out}（{len(slides)}枚）')
    if empty:
        print(f'🚨 {"・".join(empty)} が空。ここが決まらないうちはHTMLを作らない')
    for w in skeleton(meta, slides)[0]:
        print('骨格: ' + w)
    return 0


if __name__ == '__main__':
    sys.exit(main())
