#!/usr/bin/env python3
"""PPTXに「意味」を持たせる（2026-10-14・同日PowerPoint実機で確認して既定ON）。html_to_pptx.py から呼ぶ。

・タイトル: 各スライドの見出し .tb をタイトルのプレースホルダーにする（既定ON・--no-semantic で外す）
  → PowerPointのアウトライン表示・アクセシビリティチェック・Copilot等がスライド名を読める
・テーマ色: トークン色をテーマの配色に登録し、本文中の同じ色をテーマ色で参照する（既定ON）
  → PowerPointの「デザイン > バリエーション > 配色」で全体の色を一度に変えられる
・代替テキスト: img の alt／SVG の <title>・aria-label を図の説明に入れる（常時）

見た目は変えない。タイトルは書式をすべて明示し、マスターのタイトル書式（中央揃え・90%行間・
縦中央）を継承しないようにしている。AWSテンプレート使用時はテーマ色を触らない（テンプレ側の配色）。
"""
import copy
import re
import zipfile

from lxml import etree
from pptx.oxml.ns import qn

# テーマの配色スロット ← スライド契約のカラートークン
# 試作のためここに置く。採用するなら slidekit-defs.js へ移す（正本は1か所）
THEME_SLOTS = [
    ('dk1', '121212', 'tx1'),      # ink 本文
    ('lt1', 'FFFFFF', 'bg1'),      # 白（スライド地の既定）
    ('dk2', '162A42', 'tx2'),      # navy バッジ・濃色図形
    ('lt2', 'EEF3F8', 'bg2'),      # card カード地
    ('accent1', '21537F', 'accent1'),  # title 見出し
    ('accent2', 'C62828', 'accent2'),  # accent 警告
    ('accent3', '718096', 'accent3'),  # muted図形（文字の muted は #5e5e5e＝スロット外・2026-10-14）
    ('accent4', '9FC0DD', 'accent4'),  # sub 暗背景のサブ
    ('accent5', 'D4DDE7', 'accent5'),  # line 罫線
    ('accent6', '183251', 'accent6'),  # darkbg グラデの始点
]
HEX_TO_SCHEME = {hx: ref for _, hx, ref in THEME_SLOTS}


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def pick_title_tb(slide_div, is_dark):
    """スライド直下の .tb から見出しを1つ選ぶ。無ければ None。
    本文スライド: y=20〜140 にある 22px 以上で一番大きい文字（slide-edit.js の役割判定＋aws2 の y38）
    表紙・扉（暗色）: 28px 以上で一番大きい文字。同じ大きさなら上にある方"""
    best, key = None, None
    for tb in slide_div.find_all('div', class_='tb', recursive=False):
        text = tb.get_text(strip=True)
        if not text or tb.get('data-bullet'):
            continue
        if sum(c.isdigit() for c in text) * 2 >= len(text):
            continue  # 「90分」「3/24」のような数字の強調は見出しにしない
        fs = _num(tb.get('data-font-size'))
        y = _num(tb.get('data-y'), 9999)
        if is_dark:
            if fs < 28:
                continue
        elif not (20 <= y <= 140) or fs < 22:
            continue
        k = (fs, -y)
        if key is None or k > key:
            best, key = tb, k
    return best


def _ensure_ppr_child(p, tag, make, order):
    """a:pPr に tag が無ければ make() で作り、スキーマ順（order の並び）を守って差し込む"""
    pPr = p.find(qn('a:pPr'))
    if pPr is None:
        pPr = etree.Element(qn('a:pPr'))
        p.insert(0, pPr)
    if pPr.find(qn(tag)) is not None:
        return
    el = make()
    later = order[order.index(tag) + 1:]
    for i, c in enumerate(pPr):
        if c.tag in [qn(t) for t in later]:
            pPr.insert(i, el)
            return
    pPr.append(el)


# CT_TextParagraphProperties の子要素順（先頭の3つだけ使う。後ろは「この位置より前に入れる」目印）
_PPR_ORDER = ['a:lnSpc', 'a:spcBef', 'a:spcAft', 'a:buClrTx', 'a:buClr', 'a:buSzTx', 'a:buSzPct',
              'a:buSzPts', 'a:buFontTx', 'a:buFont', 'a:buNone', 'a:buAutoNum', 'a:buChar',
              'a:buBlip', 'a:tabLst', 'a:defRPr', 'a:extLst']


def _spc(tag, kind, val):
    def make():
        el = etree.Element(qn(tag))
        etree.SubElement(el, qn(kind)).set('val', str(val))
        return el
    return make


def make_title_placeholder(shape):
    """テキストボックスをタイトルのプレースホルダーに変える（見た目は変えない）。
    マスターのタイトル書式から継承しうる値（縦位置・行間・段落前後の空き・自動調整）を明示で上書きする"""
    sp = shape._element
    nv = sp.find(qn('p:nvSpPr'))
    if nv is None:
        return False
    cNvSpPr = nv.find(qn('p:cNvSpPr'))
    if cNvSpPr is not None:
        cNvSpPr.attrib.pop('txBox', None)  # プレースホルダーはテキストボックス扱いにしない
        if cNvSpPr.find(qn('a:spLocks')) is None:
            etree.SubElement(cNvSpPr, qn('a:spLocks')).set('noGrp', '1')
    nvPr = nv.find(qn('p:nvPr'))
    if nvPr is None or nvPr.find(qn('p:ph')) is not None:
        return False
    ph = etree.Element(qn('p:ph'))
    ph.set('type', 'title')
    nvPr.insert(0, ph)
    bodyPr = sp.find('.//' + qn('a:bodyPr'))
    if bodyPr is not None:
        if bodyPr.get('anchor') is None:
            bodyPr.set('anchor', 't')  # テキストボックスの既定＝上。マスターのタイトルは縦中央
        fits = [qn('a:noAutofit'), qn('a:normAutofit'), qn('a:spAutoFit')]
        if not any(c.tag in fits for c in bodyPr):
            bodyPr.append(etree.Element(qn('a:noAutofit')))  # マスターの「はみ出したら縮小」を継承しない
    for p in sp.iter(qn('a:p')):
        _ensure_ppr_child(p, 'a:lnSpc', _spc('a:lnSpc', 'a:spcPct', 100000), _PPR_ORDER)
        _ensure_ppr_child(p, 'a:spcBef', _spc('a:spcBef', 'a:spcPts', 0), _PPR_ORDER)
        _ensure_ppr_child(p, 'a:spcAft', _spc('a:spcAft', 'a:spcPts', 0), _PPR_ORDER)
        pPr = p.find(qn('a:pPr'))
        if pPr.get('algn') is None:
            pPr.set('algn', 'l')  # マスターのタイトルが中央揃えでも左のまま
    shape.name = 'Title ' + str(shape.shape_id)
    return True


def set_alt_text(shape, text):
    """図の代替テキスト（cNvPr@descr）を入れる。空なら何もしない"""
    t = re.sub(r'\s+', ' ', text or '').strip()
    if not t:
        return False
    cNvPr = shape._element.find('.//' + qn('p:cNvPr'))
    if cNvPr is None:
        return False
    cNvPr.set('descr', t[:1000])
    return True


def alt_of_image(img_el):
    """img の代替テキスト: alt → title → ラッパーの aria-label / data-alt"""
    par = img_el.parent if img_el is not None else None
    for v in (img_el.get('alt'), img_el.get('title'),
              par.get('aria-label') if par is not None else None,
              par.get('data-alt') if par is not None else None):
        if v and v.strip():
            return v
    return ''


def alt_of_svg(wrapper):
    """SVG図の代替テキスト: ラッパーの aria-label / data-alt → svg の aria-label → <title>"""
    svg = wrapper.find('svg')
    cands = [wrapper.get('aria-label'), wrapper.get('data-alt')]
    if svg is not None:
        cands.append(svg.get('aria-label'))
        t = svg.find('title')
        cands.append(t.get_text() if t is not None else None)
    for v in cands:
        if v and v.strip():
            return v
    return ''


_NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_NS_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def _master_theme_parts(files):
    """スライドマスターが使うテーマのパート名（ppt/theme/themeN.xml）"""
    out = set()
    for name in files:
        m = re.match(r'^ppt/slideMasters/_rels/(slideMaster\d+\.xml)\.rels$', name)
        if not m:
            continue
        rels = etree.fromstring(files[name])
        for r in rels.findall('{%s}Relationship' % _NS_REL):
            if r.get('Type', '').endswith('/theme'):
                out.add('ppt/theme/' + r.get('Target', '').split('/')[-1])
    return out


def apply_theme_colors(pptx_path):
    """テーマの配色をトークン色にし、スライド内の同じ srgbClr を schemeClr に置き換える。
    返り値: (置き換えた色の数, 書き換えたテーマの数)"""
    with zipfile.ZipFile(pptx_path) as z:
        names = z.namelist()
        files = {n: z.read(n) for n in names}
    themes = _master_theme_parts(files)
    for tn in themes:
        root = etree.fromstring(files[tn])
        cs = root.find('.//' + qn('a:clrScheme'))
        if cs is None:
            continue
        cs.set('name', 'SlideKit')
        for slot, hx, _ in THEME_SLOTS:
            el = cs.find(qn('a:' + slot))
            if el is None:
                continue
            for c in list(el):
                el.remove(c)
            etree.SubElement(el, qn('a:srgbClr')).set('val', hx)
        files[tn] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    n_sub = 0
    for name in names:
        if not re.match(r'^ppt/slides/slide\d+\.xml$', name):
            continue
        root = etree.fromstring(files[name])
        hit = False
        for el in root.iter(qn('a:srgbClr')):
            ref = HEX_TO_SCHEME.get((el.get('val') or '').upper())
            if ref:
                el.tag = qn('a:schemeClr')  # 子要素（alpha 等）はそのまま使える
                el.set('val', ref)
                n_sub += 1
                hit = True
        if hit:
            files[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, files[n])
    return n_sub, len(themes)


# 読み上げ順（2026-10-14）: 文字の無い図形（カード地・帯・線・矢印）を「装飾」にして、読み上げで飛ばす。
#   PowerPointの読み上げ順は重なり順と同じなので、並べ替えると見出しが背景の下に隠れる。順は触らず、
#   中身の無い図形を外すことで、見出し→本文→図の順に読まれるようにする（PowerPointの「装飾用にする」と同じ印）
DECOR_URI = '{C183D7F6-B498-43B3-948B-1728B52AA6E4}'
DECOR_NS = 'http://schemas.microsoft.com/office/drawing/2017/decorative'


def _has_text(el):
    return any((t.text or '').strip() for t in el.iter(qn('a:t')))


def mark_decorative(pptx_path):
    """スライド直下の文字の無い図形・線に装飾の印を付ける。代替テキストのある図形・画像・グループ・グラフは触らない。
    返り値: 印を付けた数"""
    with zipfile.ZipFile(pptx_path) as z:
        names = z.namelist()
        files = {n: z.read(n) for n in names}
    n_dec = 0
    for name in names:
        if not re.match(r'^ppt/slides/slide\d+\.xml$', name):
            continue
        root = etree.fromstring(files[name])
        tree = root.find('.//' + qn('p:spTree'))
        if tree is None:
            continue
        hit = False
        for el in tree:
            if el.tag not in (qn('p:sp'), qn('p:cxnSp')) or _has_text(el):
                continue
            if el.find('.//' + qn('p:ph')) is not None:
                continue
            c = el.find('.//' + qn('p:cNvPr'))
            if c is None or (c.get('descr') or '').strip():
                continue
            if any(x.get('uri') == DECOR_URI for x in c.iter(qn('a:ext'))):
                continue
            ext_lst = c.find(qn('a:extLst'))
            if ext_lst is None:
                ext_lst = etree.SubElement(c, qn('a:extLst'))
            ext = etree.SubElement(ext_lst, qn('a:ext'))
            ext.set('uri', DECOR_URI)
            etree.SubElement(ext, '{%s}decorative' % DECOR_NS, nsmap={'adec': DECOR_NS}).set('val', '1')
            n_dec += 1
            hit = True
        if hit:
            files[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, files[n])
    return n_dec


# ---------------------------------------------------------------------------
# PowerPointで直せる文字にする（2026-10-14 利用者「BOLDを解除できない…そういう変換をしない」）
# ---------------------------------------------------------------------------
_NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
_NS_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_PAGENO_RE = re.compile(r'(?:[pP]\.?)?(\d{1,3})(?:/\d{1,3})?')


def _a(tag):
    return '{%s}%s' % (_NS_A, tag)


def unlock_bold(root):
    """段落既定（a:pPr/a:defRPr）の b を外し、b を持たない run に移す。
    段落既定に b="1" があると、PowerPointで文字を選んで太字を外しても太字のまま残る
    （AppleScriptで bold=false にしても true のまま＝2026-10-14 実測。b だけ外すと外れる）。返り値: 直した段落数"""
    n = 0
    for p in root.iter(_a('p')):
        pPr = p.find(_a('pPr'))
        d = pPr.find(_a('defRPr')) if pPr is not None else None
        if d is None or d.get('b') is None:
            continue
        b = d.attrib.pop('b')
        for r in list(p.findall(_a('r'))) + list(p.findall(_a('fld'))):
            rPr = r.find(_a('rPr'))
            if rPr is None:
                rPr = etree.Element(_a('rPr'))
                r.insert(0, rPr)
            if rPr.get('b') is None:
                rPr.set('b', b)
        e = p.find(_a('endParaRPr'))
        if e is not None and e.get('b') is None:
            e.set('b', b)
        n += 1
    return n


_RPR_FILL = ('ln', 'noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill', 'grpFill')


def unlock_para_defaults(root):
    """段落既定（a:pPr/a:defRPr）を run に移してから消し、pt固定の行間を倍率にする。
    段落既定に大きさや色が残っていると、PowerPointで文字を選んで大きさを変えても効かないことがある。
    固定の行間（a:lnSpc/a:spcPts）だと、文字を大きくしても行の高さが変わらず上下が切れる
    （2026-10-22 TxAneo_ビジネス検討支援.pptx で利用者が確認。この2つを外した写しで直った）。
    返り値: 直した段落数"""
    n = 0
    for p in root.iter(_a('p')):
        pPr = p.find(_a('pPr'))
        if pPr is None:
            continue
        changed = False
        d = pPr.find(_a('defRPr'))
        runs = list(p.findall(_a('r'))) + list(p.findall(_a('fld')))
        if d is not None:
            for r in runs:
                rPr = r.find(_a('rPr'))
                if rPr is None:
                    rPr = etree.Element(_a('rPr'))
                    r.insert(0, rPr)
                for k, v in d.attrib.items():
                    if rPr.get(k) is None:
                        rPr.set(k, v)
                have = {etree.QName(c).localname for c in rPr}
                for c in d:
                    ln = etree.QName(c).localname
                    if ln in have or (ln in _RPR_FILL and have & set(_RPR_FILL[1:])):
                        continue
                    cp = copy.deepcopy(c)
                    if ln in _RPR_FILL:   # 塗りは latin/ea より前
                        rPr.insert(0, cp)
                    else:
                        rPr.append(cp)
            pPr.remove(d)
            changed = True
        ls = pPr.find(_a('lnSpc'))
        pts = ls.find(_a('spcPts')) if ls is not None else None
        if pts is not None:
            szs = [int(r.find(_a('rPr')).get('sz')) for r in runs
                   if r.find(_a('rPr')) is not None and r.find(_a('rPr')).get('sz')]
            pct = 100000
            if szs:   # PowerPointの1行＝文字の大きさの約1.2倍。見た目の行の高さを保つ
                pct = max(60000, min(250000, round(int(pts.get('val')) / (max(szs) * 1.2) * 100000)))
            ls.remove(pts)
            etree.SubElement(ls, _a('spcPct')).set('val', str(pct))
            changed = True
        n += changed
    return n


def autonumber_pages(root, slide_no, slide_w, slide_h):
    """右下の帯にある「数字だけ」の文字枠を、PowerPointのスライド番号フィールドにする。
    変換のどの経路で作られた番号でも、最後にここを通せば手書きの番号は残らない。返り値: 直した数"""
    import uuid
    n = 0
    for sp in root.iter('{%s}sp' % _NS_P):
        # 2026-11-20: グループの中（SVGから作ったグラフ・図）は見ない。グラフの右軸の「0」がページ番号「1」に置き換わっていた
        if sp.getparent() is not None and sp.getparent().tag == '{%s}grpSp' % _NS_P:
            continue
        off = sp.find('.//' + _a('off'))
        tx = sp.find('{%s}txBody' % _NS_P)
        if off is None or tx is None or tx.find('.//' + _a('fld')) is not None:
            continue
        if int(off.get('x', 0)) < slide_w * 0.75 or int(off.get('y', 0)) < slide_h * 0.85:
            continue
        paras = tx.findall(_a('p'))
        text = re.sub(r'\s+', '', ''.join(''.join(p.itertext()) for p in paras))
        if not _PAGENO_RE.fullmatch(text):
            continue
        for p in paras:
            runs = p.findall(_a('r'))
            if not runs:
                continue
            rPr = runs[0].find(_a('rPr'))
            fid = uuid.uuid5(uuid.NAMESPACE_URL, 'slidekit/slidenum-fix/%d/%d' % (slide_no, n))
            fld = etree.Element(_a('fld'), {'id': '{%s}' % str(fid).upper(), 'type': 'slidenum'})
            if rPr is not None:
                fld.append(copy.deepcopy(rPr))
            etree.SubElement(fld, _a('t')).text = str(slide_no)
            runs[0].addprevious(fld)
            for r in runs:
                p.remove(r)
            n += 1
            break
    return n


def fix_editable(pptx_path):
    """PPTX全体を「PowerPointで直せる形」にそろえる（太字の段落既定・手書きのページ番号）。
    html_to_pptx.py が毎回最後に呼ぶ。他のスクリプトで作ったPPTXにも使える（下の CLI）。
    返り値: (太字を直した段落数, 自動番号にした数)"""
    with zipfile.ZipFile(pptx_path) as z:
        names = z.namelist()
        files = {n: z.read(n) for n in names}
    pres = etree.fromstring(files['ppt/presentation.xml'])
    sz = pres.find('{%s}sldSz' % _NS_P)
    sw, sh = int(sz.get('cx')), int(sz.get('cy'))
    # スライドの並び（presentation.xml の sldIdLst の順＝表示順）
    rels = etree.fromstring(files['ppt/_rels/presentation.xml.rels'])
    target = {r.get('Id'): 'ppt/' + r.get('Target').lstrip('/').replace('ppt/', '', 1)
              for r in rels.findall('{%s}Relationship' % _NS_REL)}
    lst = pres.find('{%s}sldIdLst' % _NS_P)
    if lst is None:
        return 0, 0  # スライドが1枚も無い（.slide の無いHTMLを変換した）
    order = [target[s.get('{%s}id' % _NS_R)] for s in lst]
    nb = npg = 0
    for i, name in enumerate(order, 1):
        root = etree.fromstring(files[name])
        b = unlock_bold(root)
        b += unlock_para_defaults(root)
        pg = autonumber_pages(root, i, sw, sh)
        if b or pg:
            files[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
        nb, npg = nb + b, npg + pg
    if nb or npg:
        with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for n in names:
                z.writestr(n, files[n])
    return nb, npg


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3 or sys.argv[1] != 'fix':
        print('使い方: python3 SlideKit/pptx_semantic.py fix <PPTX> [<PPTX> ...]\n'
              '  太字の段落既定を外し（PowerPointで太字を外せるように）、右下の手書きのページ番号を自動番号にする')
        sys.exit(1)
    for path in sys.argv[2:]:
        b, pg = fix_editable(path)
        print(f'{path}: 太字を直した段落 {b} / 自動番号にしたページ番号 {pg}')
