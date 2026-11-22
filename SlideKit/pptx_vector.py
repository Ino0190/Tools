#!/usr/bin/env python3
"""SVGの図形をPowerPointの図形（自由な形＝custGeom）にする（2026-10-14）。html_to_pptx.py から呼ぶ。
入力はブラウザで測った図形（svg_shapes.js）＝スライド上のpx座標の M/L/C/Z と、塗り・線。
1つのSVGは1つのグループにまとめる。PowerPointでグループの中の図形を選べば、色を変える・消す・動かすができる。
2026-10-14 追加: 影・光彩・ぼかし輪郭（effectLst）・矢じり（headEnd/tailEnd）・放射グラデ（path circle）
"""
from lxml import etree

NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
EMU = 9525  # 1px（1280px = 12192000 EMU）
CAP = {'butt': 'flat', 'round': 'rnd', 'square': 'sq'}


def _a(t):
    return '{%s}%s' % (NS_A, t)


def _p(t):
    return '{%s}%s' % (NS_P, t)


def _color(parent, hexv, alpha):
    c = etree.SubElement(parent, _a('srgbClr'), val=(hexv or '000000').upper()[:6])
    if alpha is not None and alpha < 0.999:
        etree.SubElement(c, _a('alpha'), val=str(int(max(0, min(1, alpha)) * 100000)))


def _bbox(d):
    xs, ys = [], []
    for s in d:
        xs += s[1::2]
        ys += s[2::2]
    return min(xs), min(ys), max(xs), max(ys)


def _fill_xml(spPr, fill):
    if not fill:
        etree.SubElement(spPr, _a('noFill'))
        return
    if fill['t'] == 's':
        _color(etree.SubElement(spPr, _a('solidFill')), fill['c'], fill['a'])
        return
    g = etree.SubElement(spPr, _a('gradFill'), rotWithShape='1')
    lst = etree.SubElement(g, _a('gsLst'))
    for off, c, a in fill['stops']:
        _color(etree.SubElement(lst, _a('gs'), pos=str(int(off * 100000))), c, a)
    if fill.get('radial'):  # 中心からの円のグラデ（pos 0 が中心）
        p = etree.SubElement(g, _a('path'), path='circle')
        etree.SubElement(p, _a('fillToRect'), l='50000', t='50000', r='50000', b='50000')
    else:
        etree.SubElement(g, _a('lin'), ang=str(int(fill['ang'] * 60000) % 21600000), scaled='0')


def _fx_xml(spPr, fx):
    """影・光彩・ぼかし輪郭（svg_shapes.js が filter から読んだもの）。並びはスキーマどおり glow → outerShdw → softEdge"""
    if not fx:
        return
    lst = etree.SubElement(spPr, _a('effectLst'))
    e = lambda v: str(max(0, int(round(v * EMU))))
    if fx.get('glow'):
        gl = fx['glow']
        _color(etree.SubElement(lst, _a('glow'), rad=e(gl['r'])), gl.get('c'), gl.get('a', 1))
    if fx.get('shadow'):
        sh = fx['shadow']
        el = etree.SubElement(lst, _a('outerShdw'), blurRad=e(sh['blur']), dist=e(sh['dist']),
                              dir=str(int(round(sh['dir'] * 60000)) % 21600000), algn='ctr', rotWithShape='0')
        _color(el, sh.get('c'), sh.get('a', 1))
    if fx.get('soft'):
        etree.SubElement(lst, _a('softEdge'), rad=e(fx['soft']['r']))


def _line_xml(spPr, st):
    if not st:
        etree.SubElement(etree.SubElement(spPr, _a('ln')), _a('noFill'))
        return
    w = max(1, int(st['w'] * EMU))
    ln = etree.SubElement(spPr, _a('ln'), w=str(w), cap=CAP.get(st.get('cap'), 'flat'))
    _color(etree.SubElement(ln, _a('solidFill')), st['c'], st['a'])
    dash = [v for v in (st.get('dash') or []) if v is not None]
    if dash and any(dash):
        if len(dash) % 2:
            dash = dash * 2
        cd = etree.SubElement(ln, _a('custDash'))
        for i in range(0, len(dash), 2):  # 長さは線幅に対する比（1000分の1%）
            etree.SubElement(cd, _a('ds'), d=str(int(dash[i] / st['w'] * 100000)),
                             sp=str(int(dash[i + 1] / st['w'] * 100000)))
    j = st.get('join')
    if j == 'round':
        etree.SubElement(ln, _a('round'))
    elif j == 'bevel':
        etree.SubElement(ln, _a('bevel'))
    else:
        etree.SubElement(ln, _a('miter'), lim='800000')
    for key, tag in (('head', 'headEnd'), ('tail', 'tailEnd')):  # 矢印の印（marker）→ 矢じり
        if st.get(key):
            sz = st[key].get('size', 'med')
            etree.SubElement(ln, _a(tag), type=st[key].get('type', 'triangle'), w=sz, len=sz)


def shape_xml(sid, name, shp):
    """図形1つの <p:sp>。座標は外接枠の左上を原点にしたEMU"""
    d = shp['d']
    x0, y0, x1, y1 = _bbox(d)
    w, h = max(x1 - x0, 0.5), max(y1 - y0, 0.5)
    sp = etree.Element(_p('sp'), nsmap={'a': NS_A, 'p': NS_P})
    nv = etree.SubElement(sp, _p('nvSpPr'))
    etree.SubElement(nv, _p('cNvPr'), id=str(sid), name=name)
    etree.SubElement(nv, _p('cNvSpPr'))
    etree.SubElement(nv, _p('nvPr'))
    spPr = etree.SubElement(sp, _p('spPr'))
    xf = etree.SubElement(spPr, _a('xfrm'))
    etree.SubElement(xf, _a('off'), x=str(int(x0 * EMU)), y=str(int(y0 * EMU)))
    etree.SubElement(xf, _a('ext'), cx=str(int(w * EMU)), cy=str(int(h * EMU)))
    geo = etree.SubElement(spPr, _a('custGeom'))
    for t in ('avLst', 'gdLst', 'ahLst', 'cxnLst'):
        etree.SubElement(geo, _a(t))
    etree.SubElement(geo, _a('rect'), l='0', t='0', r='r', b='b')
    pl = etree.SubElement(geo, _a('pathLst'))
    attrs = {'w': str(int(w * EMU)), 'h': str(int(h * EMU))}
    if not shp.get('fill'):
        attrs['fill'] = 'none'
    if not shp.get('st'):
        attrs['stroke'] = '0'
    path = etree.SubElement(pl, _a('path'), **attrs)

    def pt(parent, x, y):
        etree.SubElement(parent, _a('pt'), x=str(int((x - x0) * EMU)), y=str(int((y - y0) * EMU)))
    for s in d:
        k = s[0]
        if k == 'M':
            pt(etree.SubElement(path, _a('moveTo')), s[1], s[2])
        elif k == 'L':
            pt(etree.SubElement(path, _a('lnTo')), s[1], s[2])
        elif k == 'C':
            c = etree.SubElement(path, _a('cubicBezTo'))
            for i in (1, 3, 5):
                pt(c, s[i], s[i + 1])
        elif k == 'Z':
            etree.SubElement(path, _a('close'))
    _fill_xml(spPr, shp.get('fill'))
    _line_xml(spPr, shp.get('st'))
    _fx_xml(spPr, shp.get('fx'))
    return sp, (x0, y0, x0 + w, y0 + h)


def _next_id(spTree):
    ids = [int(e.get('id')) for e in spTree.iter(_p('cNvPr')) if (e.get('id') or '').isdigit()]
    return max(ids + [1]) + 1


def _split_nonzero(shp):
    """塗りの規則が nonzero で、輪郭が全部同じ向き（＝穴の無い重なり）の図形は、輪郭ごとの図形に分ける。
    PowerPoint・LibreOffice は1つの図形の中の重なりを白く抜くことがある（2026-10-14 BezierKitの重なる丸で実測）"""
    if (shp.get('rule') or 'nonzero') != 'nonzero' or not shp.get('fill'):
        return [shp]
    subs, cur = [], None
    for s in shp['d']:
        if s[0] == 'M':
            cur = [s]; subs.append(cur)
        elif cur is not None:
            cur.append(s)
    if len(subs) < 2:
        return [shp]

    def area(sub):
        pts = [(s[i], s[i + 1]) for s in sub if s[0] != 'Z' for i in range(1, len(s), 2)]
        return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
    signs = {a > 0 for a in map(area, subs) if abs(a) > 1e-6}
    if len(signs) != 1:
        return [shp]  # 向きの違う輪郭がある＝穴として描いている
    return [dict(shp, d=sub) for sub in subs]


def _picture_xml(slide, png, box, sid, name):
    """{raster} の1枚を <p:pic> にする（いったんスライドに置いてから取り外す）。box はスライドのpx [x,y,w,h]"""
    from pptx.util import Emu
    x, y, w, h = box
    pic = slide.shapes.add_picture(png, Emu(int(x * EMU)), Emu(int(y * EMU)), Emu(int(max(w, .5) * EMU)), Emu(int(max(h, .5) * EMU)))
    el = pic._element
    el.getparent().remove(el)
    c = el.find('.//' + _p('cNvPr'))
    c.set('id', str(sid)); c.set('name', name)
    return el, (x, y, x + w, y + h)


def add_vector_group(slide, shapes, name='Illust', alt='', extra_elements=(), rasterize=None):
    """図形の列を1つのグループにしてスライドに置く。extra_elements（文字枠など）も同じグループに入れる。
    {raster: {svg, box}} の項目は、その要素だけを画像（rasterize(svg文字列, w, h) → PNGのパス）にして同じ順番で入れる。
    返り値: グループの要素。図形が空か、画像にできなかったら None（呼び出し側が絵全体を画像にする）"""
    spTree = slide.shapes._spTree
    if any(s.get('raster') for s in shapes) and rasterize is None:
        return None
    sid = _next_id(spTree)
    grp = etree.Element(_p('grpSp'), nsmap={'a': NS_A, 'p': NS_P})
    nv = etree.SubElement(grp, _p('nvGrpSpPr'))
    c = etree.SubElement(nv, _p('cNvPr'), id=str(sid), name=name)
    if alt:
        c.set('descr', alt[:1000])
    etree.SubElement(nv, _p('cNvGrpSpPr'))
    etree.SubElement(nv, _p('nvPr'))
    gpr = etree.SubElement(grp, _p('grpSpPr'))
    boxes = []
    shapes = [part for shp in shapes for part in (_split_nonzero(shp) if not shp.get('raster') else [shp])]
    for i, shp in enumerate(shapes):
        if shp.get('raster'):
            rs = shp['raster']
            png = rasterize(rs['svg'], rs['box'][2], rs['box'][3])
            if not png:
                return None
            sp, bb = _picture_xml(slide, png, rs['box'], sid + 1 + i, '%s %d（画像）' % (name, i + 1))
        else:
            sp, bb = shape_xml(sid + 1 + i, '%s %d' % (name, i + 1), shp)
        grp.append(sp)
        boxes.append(bb)
    for el in extra_elements:  # 既にスライドに置いた文字枠をグループへ移す
        off, ext = el.find('.//' + _a('off')), el.find('.//' + _a('ext'))
        if off is not None and ext is not None:
            x, y = int(off.get('x')) / EMU, int(off.get('y')) / EMU
            boxes.append((x, y, x + int(ext.get('cx')) / EMU, y + int(ext.get('cy')) / EMU))
        el.getparent().remove(el)
        grp.append(el)
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    xf = etree.SubElement(gpr, _a('xfrm'))
    for tag, a, b in (('off', 'x', 'y'), ('ext', 'cx', 'cy'), ('chOff', 'x', 'y'), ('chExt', 'cx', 'cy')):
        v = (x0, y0) if tag in ('off', 'chOff') else (x1 - x0, y1 - y0)
        etree.SubElement(xf, _a(tag), **{a: str(int(v[0] * EMU)), b: str(int(v[1] * EMU))})
    ext = spTree.find(_p('extLst'))
    if ext is not None:
        ext.addprevious(grp)
    else:
        spTree.append(grp)
    return grp
