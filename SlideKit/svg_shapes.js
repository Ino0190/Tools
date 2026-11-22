/* SVGの図形を、PowerPointの図形にするために測る（2026-10-14）。measure_layout.py がブラウザに差し込む。
 * 各図形を「スライド上の座標の直線・3次ベジェ」に直して返す（変形・viewBox・CSSの効いた後の値）。
 * html_to_pptx.py はこれを custGeom（PowerPointの自由な形）にし、グループにまとめる。
 * 図形にできない効果（図形全体のぼかし・複雑なマスクと切り抜き・模様・画像・use）を含むSVGは why を返し、従来どおり画像にする。
 * 2026-10-14 利用者「できるものは対応してほしい」: PowerPointにあるものは置き換える
 *   影・光彩・ぼかし輪郭（filter）→ effectLst／矢印の印（marker）→ 線の矢じり／放射グラデ → 円のグラデ／
 *   図形を包む長方形の切り抜き → 外す・外れた図形 → 出さない／単色や直線グラデのマスク → 不透明度・透明度つきグラデ
 */
(function () {
  // パスの d を絶対座標の M/L/C/Z だけにする（H/V/S/Q/T/A も変換）
  function parseD(d) {
    var toks = [], re = /([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)/g, m;
    while ((m = re.exec(d))) toks.push(m[1] || parseFloat(m[2]));
    var out = [], i = 0, cmd = null, x = 0, y = 0, sx = 0, sy = 0, px = null, py = null, qx = null, qy = null;
    function n() { return toks[i++]; }
    while (i < toks.length) {
      if (typeof toks[i] === 'string') cmd = toks[i++];
      if (!cmd) break;
      var rel = cmd === cmd.toLowerCase(), C = cmd.toUpperCase(), ox = rel ? x : 0, oy = rel ? y : 0;
      if (C === 'Z') { out.push(['Z']); x = sx; y = sy; px = qx = null; if (typeof toks[i] !== 'string') cmd = null; continue; }
      if (C === 'M') { x = ox + n(); y = oy + n(); sx = x; sy = y; out.push(['M', x, y]); cmd = rel ? 'l' : 'L'; px = qx = null; continue; }
      if (C === 'L') { x = ox + n(); y = oy + n(); out.push(['L', x, y]); px = qx = null; continue; }
      if (C === 'H') { x = ox + n(); out.push(['L', x, y]); px = qx = null; continue; }
      if (C === 'V') { y = (rel ? y : 0) + n(); out.push(['L', x, y]); px = qx = null; continue; }
      if (C === 'C' || C === 'S') {
        var x1, y1;
        if (C === 'C') { x1 = ox + n(); y1 = oy + n(); }
        else { x1 = px === null ? x : 2 * x - px; y1 = py === null ? y : 2 * y - py; }
        var x2 = ox + n(), y2 = oy + n(), ex = ox + n(), ey = oy + n();
        out.push(['C', x1, y1, x2, y2, ex, ey]); px = x2; py = y2; qx = null; x = ex; y = ey; continue;
      }
      if (C === 'Q' || C === 'T') {
        var cx, cy;
        if (C === 'Q') { cx = ox + n(); cy = oy + n(); }
        else { cx = qx === null ? x : 2 * x - qx; cy = qy === null ? y : 2 * y - qy; }
        var qex = ox + n(), qey = oy + n();
        out.push(['C', x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), qex + 2 / 3 * (cx - qex), qey + 2 / 3 * (cy - qey), qex, qey]);
        qx = cx; qy = cy; px = null; x = qex; y = qey; continue;
      }
      if (C === 'A') {
        var rx = n(), ry = n(), rot = n(), la = n(), sw = n(), ax = ox + n(), ay = oy + n();
        arcToC(x, y, rx, ry, rot, la, sw, ax, ay).forEach(function (c) { out.push(c); });
        x = ax; y = ay; px = qx = null; continue;
      }
      break; // 知らないコマンドは打ち切る
    }
    return out;
  }
  // 楕円弧を3次ベジェに（SVG仕様 F.6 の中心形式へ直して、90°ずつに割る）
  function arcToC(x1, y1, rx, ry, phi, fa, fs, x2, y2) {
    if (!rx || !ry) return [['L', x2, y2]];
    rx = Math.abs(rx); ry = Math.abs(ry);
    var p = phi * Math.PI / 180, cp = Math.cos(p), sp = Math.sin(p);
    var dx = (x1 - x2) / 2, dy = (y1 - y2) / 2, x1p = cp * dx + sp * dy, y1p = -sp * dx + cp * dy;
    var lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry);
    if (lam > 1) { rx *= Math.sqrt(lam); ry *= Math.sqrt(lam); }
    var num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p, den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
    var k = (fa === fs ? -1 : 1) * Math.sqrt(Math.max(0, num / den));
    var cxp = k * rx * y1p / ry, cyp = -k * ry * x1p / rx;
    var cx = cp * cxp - sp * cyp + (x1 + x2) / 2, cy = sp * cxp + cp * cyp + (y1 + y2) / 2;
    function ang(ux, uy, vx, vy) { var a = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy); return a; }
    var t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    var dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if (!fs && dt > 0) dt -= 2 * Math.PI; else if (fs && dt < 0) dt += 2 * Math.PI;
    var segs = Math.max(1, Math.ceil(Math.abs(dt) / (Math.PI / 2))), d = dt / segs, out = [];
    var kk = 4 / 3 * Math.tan(d / 4);
    function pt(t) { var c = Math.cos(t), s = Math.sin(t); return [cx + rx * c * cp - ry * s * sp, cy + rx * c * sp + ry * s * cp]; }
    function dv(t) { var c = Math.cos(t), s = Math.sin(t); return [-rx * s * cp - ry * c * sp, -rx * s * sp + ry * c * cp]; }
    for (var i = 0; i < segs; i++) {
      var a = t1 + d * i, b = a + d, A = pt(a), B = pt(b), dA = dv(a), dB = dv(b);
      out.push(['C', A[0] + kk * dA[0], A[1] + kk * dA[1], B[0] - kk * dB[0], B[1] - kk * dB[1], B[0], B[1]]);
    }
    return out;
  }
  function f(el, a) { return parseFloat(el.getAttribute(a)) || 0; }
  // 基本図形を d と同じ形の区間列にする
  function segsOf(el) {
    var t = el.tagName.toLowerCase();
    if (t === 'path') return parseD(el.getAttribute('d') || '');
    if (t === 'line') return [['M', f(el, 'x1'), f(el, 'y1')], ['L', f(el, 'x2'), f(el, 'y2')]];
    if (t === 'polyline' || t === 'polygon') {
      var v = (el.getAttribute('points') || '').match(/-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/gi) || [], out = [];
      for (var i = 0; i + 1 < v.length; i += 2) out.push([i ? 'L' : 'M', +v[i], +v[i + 1]]);
      if (t === 'polygon' && out.length) out.push(['Z']);
      return out;
    }
    var x, y, w, h, rx, ry;
    if (t === 'rect') {
      x = f(el, 'x'); y = f(el, 'y'); w = f(el, 'width'); h = f(el, 'height');
      rx = el.hasAttribute('rx') ? f(el, 'rx') : f(el, 'ry'); ry = el.hasAttribute('ry') ? f(el, 'ry') : rx;
      rx = Math.min(rx, w / 2); ry = Math.min(ry, h / 2);
      if (!rx || !ry) return [['M', x, y], ['L', x + w, y], ['L', x + w, y + h], ['L', x, y + h], ['Z']];
      return parseD('M' + (x + rx) + ' ' + y + 'H' + (x + w - rx) + 'A' + rx + ' ' + ry + ' 0 0 1 ' + (x + w) + ' ' + (y + ry) +
        'V' + (y + h - ry) + 'A' + rx + ' ' + ry + ' 0 0 1 ' + (x + w - rx) + ' ' + (y + h) + 'H' + (x + rx) +
        'A' + rx + ' ' + ry + ' 0 0 1 ' + x + ' ' + (y + h - ry) + 'V' + (y + ry) + 'A' + rx + ' ' + ry + ' 0 0 1 ' + (x + rx) + ' ' + y + 'Z');
    }
    if (t === 'circle' || t === 'ellipse') {
      var cx = f(el, 'cx'), cy = f(el, 'cy');
      rx = t === 'circle' ? f(el, 'r') : f(el, 'rx'); ry = t === 'circle' ? rx : f(el, 'ry');
      return parseD('M' + (cx + rx) + ' ' + cy + 'A' + rx + ' ' + ry + ' 0 0 1 ' + cx + ' ' + (cy + ry) + 'A' + rx + ' ' + ry + ' 0 0 1 ' +
        (cx - rx) + ' ' + cy + 'A' + rx + ' ' + ry + ' 0 0 1 ' + cx + ' ' + (cy - ry) + 'A' + rx + ' ' + ry + ' 0 0 1 ' + (cx + rx) + ' ' + cy + 'Z');
    }
    return null;
  }
  // url(#id) の参照先
  function refOf(val, svg) { var u = /url\(["']?#([^"')]+)["']?\)/.exec(val || ''); return u ? svg.ownerDocument.getElementById(u[1]) : null; }
  // ---- filter → PowerPointの効果。読めない組み合わせ（図形全体のぼかし・色の変換など）は null ----
  // BezierKit の出力（影＝SourceAlphaをぼかしてずらして塗る／光彩＝膨らませてぼかして塗る／ぼかし輪郭＝削ってぼかして切り抜く）と feDropShadow を読む
  function filterFx(f, k) {
    var fx = {}, cur = null, lastBlur = null, kids = [].slice.call(f.children);
    for (var i = 0; i < kids.length; i++) {
      var c = kids[i], t = c.tagName, inp = c.getAttribute('in'), cs = getComputedStyle(c);
      var flood = function () { var r = rgb(cs.floodColor) || { c: '000000', a: 1 }; return { c: r.c, a: r.a * (parseFloat(cs.floodOpacity) || (cs.floodOpacity === '0' ? 0 : 1)) }; };
      if (t === 'feGaussianBlur') {
        var std = parseFloat(c.getAttribute('stdDeviation')) || 0;
        if (inp === 'SourceGraphic' || (!inp && i === 0)) return null; // 図形そのものをぼかす＝PowerPointの図形には無い
        if (cur && cur.kind === 'glow' && cur.blur == null) cur.blur = std; else lastBlur = std;
      } else if (t === 'feOffset') {
        var dx = (parseFloat(c.getAttribute('dx')) || 0) * k, dy = (parseFloat(c.getAttribute('dy')) || 0) * k;
        cur = fx.shadow = { kind: 'shadow', dist: Math.hypot(dx, dy), dir: (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360, blur: (lastBlur || 0) * 2 * k, c: '000000', a: .4 };
        lastBlur = null;
      } else if (t === 'feDropShadow') {
        var fl = flood(), ddx = (parseFloat(c.getAttribute('dx')) || 0) * k, ddy = (parseFloat(c.getAttribute('dy')) || 0) * k;
        fx.shadow = { kind: 'shadow', dist: Math.hypot(ddx, ddy), dir: (Math.atan2(ddy, ddx) * 180 / Math.PI + 360) % 360, blur: (parseFloat(c.getAttribute('stdDeviation')) || 0) * 2 * k, c: fl.c, a: fl.a };
      } else if (t === 'feMorphology') {
        var rad = parseFloat(c.getAttribute('radius')) || 0;
        if (c.getAttribute('operator') === 'dilate') cur = fx.glow = { kind: 'glow', r: rad * 2 * k, c: 'FFD54F', a: .6 };
        else cur = fx.soft = { kind: 'soft', r: rad / .8 * k };
      } else if (t === 'feFlood') {
        if (cur && cur.kind !== 'soft') { var f2 = flood(); cur.c = f2.c; cur.a = f2.a; }
      } else if (t === 'feComposite' || t === 'feMerge' || t === 'feComponentTransfer') {
        // 重ね方・切り抜き。上の組み合わせの一部
      } else return null;
    }
    return fx.shadow || fx.glow || fx.soft ? fx : null;
  }
  // CSS の filter: drop-shadow(色 x y ぼかし) だけ読む
  function cssFx(v, k) {
    var m = /^drop-shadow\((rgba?\([^)]*\))\s+(-?[\d.]+)px\s+(-?[\d.]+)px\s+([\d.]+)px\)$/.exec((v || '').trim());
    if (!m) return null; var c = rgb(m[1]), dx = +m[2] * k, dy = +m[3] * k;
    return { shadow: { dist: Math.hypot(dx, dy), dir: (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360, blur: +m[4] * k, c: c.c, a: c.a } };
  }
  // 要素からsvgまでの filter・clip-path・mask をまとめて見る。戻り値 {fx, skip, alpha, why}
  function effectsOf(el, svg, sr, bb) {
    var out = { fx: null, skip: false, alpha: 1, grad: null }, why = [];
    for (var e = el; e && e !== svg.parentNode; e = e.parentNode) {
      if (e.nodeType !== 1) continue;
      var cs = getComputedStyle(e), m = e.getScreenCTM ? e.getScreenCTM() : null, k = m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1 : 1;
      var n0 = why.length;
      if (cs.filter && cs.filter !== 'none') {
        var f = refOf(cs.filter, svg), fx = f && f.tagName.toLowerCase() === 'filter' ? filterFx(f, k) : cssFx(cs.filter, k);
        if (!fx || out.fx) why.push('ぼかし（図形全体のぼかし・色の変換など）'); else out.fx = fx;
      }
      if (cs.clipPath && cs.clipPath !== 'none') {
        var r = clipRect(refOf(cs.clipPath, svg), e, sr);
        if (!r) why.push('切り抜き（長方形以外）');
        else if (bb[2] < r[0] || bb[0] > r[2] || bb[3] < r[1] || bb[1] > r[3]) out.skip = true;     // 切り抜きの外＝見えない
        else if (!(bb[0] >= r[0] - .5 && bb[1] >= r[1] - .5 && bb[2] <= r[2] + .5 && bb[3] <= r[3] + .5)) why.push('切り抜き（図形の途中で切れる）');
      }
      if (cs.mask && cs.mask !== 'none' && !/^none/.test(cs.mask)) {
        var mk = maskOf(refOf(cs.mask, svg), e, sr, bb);
        if (!mk) why.push('マスク（複雑な形）'); else if (mk.skip) out.skip = true; else { out.alpha *= mk.alpha; if (mk.grad) out.grad = mk.grad; }
      }
      if (why.length > n0) out.host = e; // 図形にできない効果の付いた要素（上へたどるので、最後に残るのは一番外側）
    }
    out.why = why;
    return out;
  }
  // 図形の点（スライド座標）
  function slideSegs(sh, host, sr) {
    var segs = segsOf(sh); if (!segs) return null;
    var m = host.getScreenCTM(); if (!m) return null;
    var t = sh.transform && sh.transform.baseVal && sh.transform.baseVal.consolidate();
    if (t) m = m.multiply(t.matrix);
    return segs.map(function (s) { if (s[0] === 'Z') return s; var r = [s[0]]; for (var i = 1; i < s.length; i += 2) r.push(m.a * s[i] + m.c * s[i + 1] + m.e - sr.left, m.b * s[i] + m.d * s[i + 1] + m.f - sr.top); return r; });
  }
  function segsBBox(segs) { var xs = [], ys = []; segs.forEach(function (s) { for (var i = 1; i < s.length; i += 2) { xs.push(s[i]); ys.push(s[i + 1]); } }); return xs.length ? [Math.min.apply(null, xs), Math.min.apply(null, ys), Math.max.apply(null, xs), Math.max.apply(null, ys)] : null; }
  // 長方形1つの切り抜きなら [l,t,r,b]（スライド座標）。それ以外は null
  function clipRect(cp, host, sr) {
    if (!cp || cp.tagName.toLowerCase() !== 'clippath' || cp.getAttribute('clipPathUnits') === 'objectBoundingBox') return null;
    var kids = [].slice.call(cp.children).filter(function (c) { return c.matches(SHAPES); });
    if (kids.length !== 1) return null;
    var segs = slideSegs(kids[0], host, sr); if (!segs) return null;
    var pts = segs.filter(function (s) { return s[0] !== 'Z'; });
    if (pts.some(function (s) { return s[0] === 'C'; }) || pts.length < 4 || pts.length > 5) return null;
    var bb = segsBBox(segs), onEdge = pts.every(function (s) { return (Math.abs(s[1] - bb[0]) < .5 || Math.abs(s[1] - bb[2]) < .5) && (Math.abs(s[2] - bb[1]) < .5 || Math.abs(s[2] - bb[3]) < .5); });
    return onEdge ? bb : null;
  }
  function lum(c) { var v = [0, 2, 4].map(function (i) { return parseInt(c.c.substr(i, 2), 16) / 255; }); return (.2126 * v[0] + .7152 * v[1] + .0722 * v[2]) * c.a; }
  // マスク: 中身が長方形1つで、単色（＝不透明度）か直線グラデ（＝透明度つきグラデ）のときだけ。グラデは長方形が図形とほぼ同じ大きさのとき
  function maskOf(mk, host, sr, bb) {
    if (!mk || mk.tagName.toLowerCase() !== 'mask' || mk.getAttribute('maskContentUnits') === 'objectBoundingBox') return null;
    var kids = [].slice.call(mk.children).filter(function (c) { return c.matches(SHAPES); });
    if (kids.length !== 1) return null;
    var r = clipRect({ tagName: 'clippath', getAttribute: function () { return null; }, children: kids }, host, sr);
    if (!r) return null;
    if (bb[2] < r[0] || bb[0] > r[2] || bb[3] < r[1] || bb[1] > r[3]) return { skip: true };
    var inside = bb[0] >= r[0] - .5 && bb[1] >= r[1] - .5 && bb[2] <= r[2] + .5 && bb[3] <= r[3] + .5;
    var cs = getComputedStyle(kids[0]), op = (parseFloat(cs.opacity) || 1) * (cs.fillOpacity === '0' ? 0 : (parseFloat(cs.fillOpacity) || 1));
    var solid = rgb(cs.fill);
    if (solid) return inside ? { alpha: lum(solid) * op } : null;
    var g = refOf(cs.fill, kids[0].ownerSVGElement || kids[0]);
    if (!g || g.tagName.toLowerCase() !== 'lineargradient' || g.getAttribute('gradientTransform') || g.getAttribute('gradientUnits') === 'userSpaceOnUse') return null;
    if (Math.abs(bb[0] - r[0]) > 2 || Math.abs(bb[1] - r[1]) > 2 || Math.abs(bb[2] - r[2]) > 2 || Math.abs(bb[3] - r[3]) > 2) return null;
    var p = paint(cs.fill, kids[0], kids[0].ownerSVGElement, []);
    if (!p || p.t !== 'g') return null;
    return { alpha: 1, grad: { ang: p.ang, a: p.stops.map(function (s) { return [s[0], lum({ c: s[1], a: s[2] }) * op]; }) } };
  }
  // 矢印の印 → PowerPointの矢じり。形は BezierKit の印の形から、大きさは markerWidth（線の太さの何倍か）から
  var ARROW_D = { 'M0 0 L10 5 L0 10 Z': 'triangle', 'M0 0 L10 5 L0 10 L3 5 Z': 'stealth', 'M1 1 L9 5 L1 9': 'arrow', 'M0 5 L5 0 L10 5 L5 10 Z': 'diamond' };
  function markerEnd(mk) {
    if (!mk || mk.tagName.toLowerCase() !== 'marker') return null;
    var p = mk.querySelector('path,circle,ellipse,polygon'), type = 'triangle';
    if (p && p.tagName === 'path') { var d = (p.getAttribute('d') || '').replace(/\s+/g, ' ').trim(); type = ARROW_D[d] || (/^M0 5 A/.test(d) ? 'oval' : 'triangle'); }
    else if (p && (p.tagName === 'circle' || p.tagName === 'ellipse')) type = 'oval';
    var w = parseFloat(mk.getAttribute('markerWidth')) || 3;
    if (mk.getAttribute('markerUnits') === 'userSpaceOnUse') w = 3;
    return { type: type, size: w <= 2.5 ? 'sm' : w <= 4 ? 'med' : 'lg' };
  }
  function rgb(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return null;
    var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
    return { c: p.slice(0, 3).map(function (v) { return ('0' + Math.round(v).toString(16)).slice(-2); }).join(''), a: p.length > 3 ? p[3] : 1 };
  }
  // 要素から svg までの opacity を掛け合わせる（getComputedStyle の opacity は継承しない）
  function opac(el, svg) { var o = 1; for (var e = el; e && e !== svg.parentNode; e = e.parentNode) { var v = parseFloat(getComputedStyle(e).opacity); if (!isNaN(v)) o *= v; } return o; }
  // url(#id) の塗り。直線グラデーション（図形の外接枠基準・変形なし）だけ図形にできる
  function paint(val, el, svg, why) {
    if (!val || val === 'none') return null;
    var u = /url\(["']?#([^"')]+)["']?\)/.exec(val);
    if (!u) { var c = rgb(val); return c ? { t: 's', c: c.c, a: c.a } : null; }
    var g = svg.ownerDocument.getElementById(u[1]), tag = g ? g.tagName.toLowerCase() : '';
    // 放射は中心が図形の中心で、焦点もそこのものだけ（PowerPointの「パス（円）」グラデ）
    var radialOk = tag === 'radialgradient' && ['cx', 'cy', 'fx', 'fy'].every(function (a) { var v = g.getAttribute(a); return v === null || Math.abs((v.indexOf('%') > 0 ? parseFloat(v) / 100 : parseFloat(v)) - .5) < .01; });
    if (!g || (tag !== 'lineargradient' && !radialOk) || g.getAttribute('gradientTransform') ||
        (g.getAttribute('gradientUnits') || '') === 'userSpaceOnUse') { why.push('グラデーション（中心のずれた放射・変形つき）'); return null; }
    var stops = [].slice.call(g.querySelectorAll('stop')).map(function (s) {
      var cs = getComputedStyle(s), c = rgb(cs.stopColor) || { c: '000000', a: 1 };
      var off = s.getAttribute('offset') || '0'; off = off.indexOf('%') > 0 ? parseFloat(off) / 100 : parseFloat(off);
      return [Math.max(0, Math.min(1, off || 0)), c.c, c.a * (parseFloat(cs.stopOpacity) || 1)];
    });
    if (!stops.length) return null;
    if (radialOk) return { t: 'g', radial: true, ang: 0, stops: stops };
    var p = function (a, d) { var v = g.getAttribute(a); return v === null ? d : (v.indexOf('%') > 0 ? parseFloat(v) / 100 : parseFloat(v)); };
    var ang = Math.atan2(p('y2', 0) - p('y1', 0), p('x2', 1) - p('x1', 0)) * 180 / Math.PI;
    return { t: 'g', ang: (ang + 360) % 360, stops: stops };
  }
  // 図形にできない要素だけを画像にするためのSVG（2026-10-14）。元のSVGを丸ごと写し、その要素と祖先・defs 類だけ残す。
  // 範囲は要素の外接枠（ぼかし・影のはみ出しぶん広げる）。文字は SlideKit が文字枠にするので消す
  var KEEP_DEFS = 'defs,clipPath,mask,marker,pattern,symbol,filter,linearGradient,radialGradient,style';
  function rasterPiece(host, svg, sr) {
    var rb = host.getBoundingClientRect(), vb = svg.getBoundingClientRect();
    if (!rb.width && !rb.height) return null;
    var pad = Math.max(24, .2 * Math.max(rb.width, rb.height));
    var l = Math.max(vb.left, rb.left - pad), t = Math.max(vb.top, rb.top - pad), r = Math.min(vb.right, rb.right + pad), b = Math.min(vb.bottom, rb.bottom + pad);
    if (r <= l || b <= t) return null;
    var inv = svg.getScreenCTM() && svg.getScreenCTM().inverse(); if (!inv) return null;
    var P = function (x, y) { return [inv.a * x + inv.c * y + inv.e, inv.b * x + inv.d * y + inv.f]; }, p0 = P(l, t), p1 = P(r, b);
    host.setAttribute('data-sk-r', '1');
    for (var a = host.parentNode; a && a !== svg; a = a.parentNode) if (a.setAttribute) a.setAttribute('data-sk-a', '1');
    var c = svg.cloneNode(true);
    host.removeAttribute('data-sk-r');
    for (var a2 = host.parentNode; a2 && a2 !== svg; a2 = a2.parentNode) if (a2.removeAttribute) a2.removeAttribute('data-sk-a');
    [].slice.call(c.querySelectorAll('*')).forEach(function (e) {
      if (!e.isConnected && !c.contains(e)) return;
      if (e.closest('[data-sk-r]') || e.hasAttribute('data-sk-a') || e.closest(KEEP_DEFS)) return;
      e.remove();
    });
    [].slice.call(c.querySelectorAll('text')).forEach(function (e) { e.remove(); });
    // 画像の参照は絶対のURLにする（画像にするときは別の一時ファイルから開くので、相対パスのままだと見つからない）
    [].slice.call(c.querySelectorAll('image')).forEach(function (e) {
      var h = e.getAttribute('href') || e.getAttribute('xlink:href') || '';
      if (h && !/^data:/.test(h)) { try { var abs = new URL(h, svg.ownerDocument.baseURI).href; e.setAttribute('href', abs); e.removeAttribute('xlink:href'); } catch (_) {} }
    });
    [].slice.call(c.querySelectorAll('[data-sk-r],[data-sk-a]')).forEach(function (e) { e.removeAttribute('data-sk-r'); e.removeAttribute('data-sk-a'); });
    c.setAttribute('viewBox', [p0[0], p0[1], p1[0] - p0[0], p1[1] - p0[1]].map(function (v) { return +v.toFixed(3); }).join(' '));
    c.setAttribute('preserveAspectRatio', 'none');
    c.removeAttribute('style'); c.removeAttribute('class');
    c.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    return { svg: new XMLSerializer().serializeToString(c), box: [l - sr.left, t - sr.top, r - l, b - t].map(function (v) { return +v.toFixed(2); }) };
  }
  // <use> を参照先の写しに置き換える（PowerPointには使い回しが無いので展開する）。測るための一時ページの中だけで行う。
  // symbol は viewBox つきの入れ子の svg にする（大きさの合わせ方が use と同じになる）。use の中の use も5段まで展開する
  function expandUses(svg, why) {
    var SVGNS = 'http://www.w3.org/2000/svg';
    for (var pass = 0; pass < 5; pass++) {
      var uses = [].slice.call(svg.querySelectorAll('use')).filter(function (u) { return !u.closest('defs,clipPath,mask,marker,pattern,symbol'); });
      if (!uses.length) return;
      uses.forEach(function (u) {
        var href = u.getAttribute('href') || u.getAttribute('xlink:href') || '', ref = /^#/.test(href) ? svg.ownerDocument.getElementById(href.slice(1)) : null;
        if (!ref || ref.contains(u)) { why.push('use（参照先が無い・外のファイル）'); u.remove(); return; }
        var g = svg.ownerDocument.createElementNS(SVGNS, 'g'), x = parseFloat(u.getAttribute('x')) || 0, y = parseFloat(u.getAttribute('y')) || 0;
        [].slice.call(u.attributes).forEach(function (a) { if (!/^(x|y|width|height|href|xlink:href|transform)$/.test(a.name)) g.setAttribute(a.name, a.value); });
        g.setAttribute('transform', (u.getAttribute('transform') || '') + ' translate(' + x + ' ' + y + ')');
        var body;
        if (ref.tagName.toLowerCase() === 'symbol') {
          body = svg.ownerDocument.createElementNS(SVGNS, 'svg');
          ['viewBox', 'preserveAspectRatio'].forEach(function (k) { if (ref.getAttribute(k)) body.setAttribute(k, ref.getAttribute(k)); });
          body.setAttribute('width', u.getAttribute('width') || ref.getAttribute('width') || '100%');
          body.setAttribute('height', u.getAttribute('height') || ref.getAttribute('height') || '100%');
          body.setAttribute('overflow', 'visible');
          [].slice.call(ref.childNodes).forEach(function (n) { body.appendChild(n.cloneNode(true)); });
        } else { body = ref.cloneNode(true); }
        body.removeAttribute('id'); [].slice.call(body.querySelectorAll('[id]')).forEach(function (n) { n.removeAttribute('id'); });
        g.appendChild(body); u.parentNode.replaceChild(g, u);
      });
    }
    if (svg.querySelector('use')) why.push('use（入れ子が深すぎる）');
  }
  var RASTER_MAX = 12; // 画像にする要素がこれより多ければ、従来どおり絵全体を1枚の画像にする
  var SKIP = 'defs,clipPath,mask,marker,symbol,pattern,title,desc,metadata';
  var SHAPES = 'path,rect,circle,ellipse,line,polyline,polygon';
  window.__skSvgShapes = function (wrap, slide) {
    var sr = slide.getBoundingClientRect(), out = [], why = [], partial = [];
    wrap.querySelectorAll('svg').forEach(function (svg) {
      if (svg.parentElement && svg.parentElement.closest('svg')) return; // 入れ子のsvgは外側で拾う
      expandUses(svg, why);
      svg.querySelectorAll('foreignObject').forEach(function () { why.push('foreignObject'); });
      var hosts = new Set();
      svg.querySelectorAll('*').forEach(function (el) {
        if (el.closest(SKIP)) return;
        var cs = getComputedStyle(el);
        // SVGの中の画像（写真など）＝その部分だけ画像にする（切り抜き・変形も効いたまま）
        if (el.tagName.toLowerCase() === 'image' && cs.display !== 'none' && cs.visibility !== 'hidden') {
          for (var hi of hosts) if (hi.contains(el)) return;
          var ef0 = effectsOf(el, svg, sr, (function () { var b = el.getBoundingClientRect(); return [b.left - sr.left, b.top - sr.top, b.right - sr.left, b.bottom - sr.top]; })());
          if (ef0.skip) return;
          var h0 = ef0.host && ef0.host !== svg ? ef0.host : el, pc0 = ef0.host === svg ? null : rasterPiece(h0, svg, sr);
          if (!pc0) { why.push('画像（image）'); return; }
          hosts.add(h0); out.push({ raster: pc0 }); partial.push('画像（image）'); return;
        }
        if (!el.matches(SHAPES) || cs.display === 'none' || cs.visibility === 'hidden') return;
        // この図形だけの「図形にできない理由」。あれば、その要素（効果が祖先なら祖先）だけを画像にする
        var lw = [], host = null;
        for (var hh of hosts) if (hh.contains(el)) { host = hh; break; }
        if (host) return; // すでに画像にした要素の中
        if (cs.markerMid && cs.markerMid !== 'none') lw.push('途中の印（marker-mid）');
        var segs = segsOf(el), m = el.getScreenCTM();
        if (!segs || !segs.length || !m) return;
        var T = function (x, y) { return [m.a * x + m.c * y + m.e - sr.left, m.b * x + m.d * y + m.f - sr.top]; };
        var d = segs.map(function (s) {
          if (s[0] === 'Z') return ['Z'];
          var r = [s[0]];
          for (var i = 1; i < s.length; i += 2) { var q = T(s[i], s[i + 1]); r.push(+q[0].toFixed(2), +q[1].toFixed(2)); }
          return r;
        });
        var o = opac(el, svg), sc = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1;
        var fill = el.tagName.toLowerCase() === 'line' || el.tagName.toLowerCase() === 'polyline' && cs.fill === 'none' ? null : paint(cs.fill, el, svg, lw);
        if (fill) { var fo = (parseFloat(cs.fillOpacity) || (cs.fillOpacity === '0' ? 0 : 1)) * o; if (fill.t === 's') fill.a *= fo; else fill.stops.forEach(function (st) { st[2] *= fo; }); }
        var st = null;
        if (cs.stroke && cs.stroke !== 'none') {
          if (/url\(/.test(cs.stroke)) lw.push('線のグラデーション');
          var sc2 = rgb(cs.stroke), w = parseFloat(cs.strokeWidth) || 0;
          if (cs.vectorEffect !== 'non-scaling-stroke') w *= sc;
          var dash = (cs.strokeDasharray && cs.strokeDasharray !== 'none') ? cs.strokeDasharray.split(/[\s,]+/).map(function (v) { return parseFloat(v) * sc; }).filter(function (v) { return v >= 0; }) : null;
          if (sc2 && w > 0) st = { c: sc2.c, a: sc2.a * (parseFloat(cs.strokeOpacity) || (cs.strokeOpacity === '0' ? 0 : 1)) * o, w: w,
            cap: cs.strokeLinecap, join: cs.strokeLinejoin, dash: dash };
        }
        // 矢印の印 → 線の矢じり
        if (st) [['head', cs.markerStart], ['tail', cs.markerEnd]].forEach(function (pr) {
          if (!pr[1] || pr[1] === 'none') return; var me = markerEnd(refOf(pr[1], svg)); if (me) st[pr[0]] = me; else lw.push('矢印などの印（marker）'); });
        // 影・光彩・ぼかし輪郭／切り抜き／マスク（線の太さぶん外側まで含めた外接枠で判定）
        var bb = segsBBox(d), half = st ? st.w / 2 : 0, ef = effectsOf(el, svg, sr, [bb[0] - half, bb[1] - half, bb[2] + half, bb[3] + half]);
        ef.why.forEach(function (w) { lw.push(w); });
        if (ef.skip && !lw.length) return;
        if (ef.alpha < .999) { if (fill) { if (fill.t === 's') fill.a *= ef.alpha; else fill.stops.forEach(function (s2) { s2[2] *= ef.alpha; }); } if (st) st.a *= ef.alpha; }
        if (ef.grad && fill) { // マスクの直線グラデ＝透明度つきグラデ（塗りが単色のとき）
          if (fill.t !== 's') lw.push('マスク（グラデの塗りにグラデのマスク）');
          else fill = { t: 'g', ang: ef.grad.ang, stops: ef.grad.a.map(function (s3) { return [s3[0], fill.c, fill.a * s3[1]]; }) };
        }
        if (lw.length) {
          var h2 = ef.host && ef.host !== svg ? ef.host : el;
          if (ef.host === svg) { lw.forEach(function (w) { why.push(w); }); return; } // ルートに付いた効果＝絵全体
          var pc = rasterPiece(h2, svg, sr);
          if (!pc) { lw.forEach(function (w) { why.push(w); }); return; }
          hosts.add(h2); out.push({ raster: pc }); lw.forEach(function (w) { partial.push(w); });
          return;
        }
        if (fill || st) out.push({ d: d, fill: fill, st: st, rule: cs.fillRule, fx: ef.fx });
      });
    });
    if (out.length > 1500) why.push('図形が多すぎる（' + out.length + '個）');
    var rasters = out.filter(function (o) { return o.raster; }).length;
    if (rasters && (rasters === out.length || rasters > RASTER_MAX)) partial.forEach(function (w) { why.push(w); }); // 全部か多すぎる＝絵全体を1枚の画像に
    return { shapes: why.length ? null : out, why: why.length ? Array.from(new Set(why)).join('・') : '',
      partial: !why.length && partial.length ? Array.from(new Set(partial)).join('・') : '' };
  };
})();
