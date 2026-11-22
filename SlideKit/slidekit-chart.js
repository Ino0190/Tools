/* SlideKit グラフ（2026-10-14）。<div data-chart='{...}'> を SVG で描く。
 * PPTX 変換（html_to_pptx.py）は data-chart の数値から PowerPoint のネイティブグラフを作る
 * ＝PowerPoint の「データを編集」で数値を直せる。ここで描く SVG はブラウザ表示用。
 * slide-edit.js が自動で読み込む。保存した HTML にも SVG が残るので、JS 無しでも見える。
 * 書式: {"type":"column|bar|stacked|line|pie|table","categories":[...],"series":[{"name":"","values":[...]}],
 *        "unit":"件","labels":true,"legend":true,"colors":["#21537f",...]}  文字の大きさは data-font-size
 */
(function () {
  if (window.SlideKitChart) return;
  // 系列の既定色＝スライド契約のトークン（title / sub / muted / navy / line / accent）
  var PAL = ['#21537f', '#9fc0dd', '#718096', '#162a42', '#d4dde7', '#c62828'];
  var INK = '#121212', AXIS = '#5e5e5e', GRID = '#d4dde7', WEEKEND = '#eef3f8', areaSeq = 0;
  // サンキーの箱の色: 罫線色（薄すぎる）と警告の赤（意味が付く）を外した4色
  var SANKEY_PAL = ['#21537f', '#718096', '#9fc0dd', '#162a42'];
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function nice(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  function fmt(v, unit) {
    var r = Math.round(v * 100) / 100;
    return r.toLocaleString('ja-JP') + (unit || '');
  }
  function tw(s, fs) { // 文字幅の見積もり（全角=1em・半角=0.6em）
    var w = 0; String(s).split('').forEach(function (c) { w += c.charCodeAt(0) > 255 ? 1 : 0.6; });
    return w * fs;
  }
  function txt(x, y, s, fs, o) {
    o = o || {};
    return '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" font-size="' + fs + '" fill="' +
      (o.fill || INK) + '" text-anchor="' + (o.anchor || 'middle') + '"' + (o.bold ? ' font-weight="700"' : '') +
      ' dominant-baseline="' + (o.base || 'middle') + '">' + esc(s) + '</text>';
  }
  function rect(x, y, w, h, c) {
    return '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + Math.max(0, w).toFixed(1) +
      '" height="' + Math.max(0, h).toFixed(1) + '" fill="' + c + '"/>';
  }
  function legend(names, cols, W, fs) {
    var parts = [], x = 0, sw = fs * 0.8;
    names.forEach(function (n, i) {
      parts.push({ x: x, n: n, c: cols[i % cols.length] });
      x += sw + 6 + tw(n, fs) + fs * 1.2;
    });
    var off = Math.max(0, (W - x + fs * 1.2) / 2), out = '';
    parts.forEach(function (p) {
      out += rect(off + p.x, fs * 0.4, sw, sw, p.c) +
        txt(off + p.x + sw + 6, fs * 0.8, p.n, fs, { anchor: 'start', fill: AXIS });
    });
    return out;
  }
  // ---- 数値ラベルの間引き（2026-10-14 利用者「点の数ではなく、数値を間引く仕組みを」）----
  //   html_to_pptx.chart_label_plan と同じ手順。PPTXでも同じ点に数値が出る
  //   数値1つずつの置き場所（枠）を見積もり、すでに置いた数値と重ならないものだけ出す
  //   置く順: ①系列ごとの最大・最小・最後 ②左から順に。重ならなければ全部出る
  //   折れ線が2本以上のときは、平均がいちばん低い系列の数値を線の下に置く（labelBelow）
  //   labels:false＝出さない／labels:"all"＝全部出す
  function labelBelow(c, ser) {
    if (c.type !== 'line' || ser.length < 2) return -1;
    var best = -1, bm = Infinity;
    ser.forEach(function (s, j) {
      var v = (s.values || []).filter(function (x) { return typeof x === 'number' && isFinite(x); });
      var m = v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : Infinity;
      if (m < bm) { bm = m; best = j; }
    });
    return best;
  }
  // 数値の枠 [左, 右, 下, 上]（値の軸＝上向き・項目の軸＝右向きの座標。横棒は軸を入れ替えた座標）
  function labelBox(c, ser, j, i, g) {
    var lf = g.fs * 0.85, v = ser[j].values[i], w = tw(fmt(v, c.unit), lf) + lf * 0.3;
    var k = Math.max(1, ser.length), gw = g.band * 0.7, bw = gw / k, vp = (v - g.lo) / ((g.hi - g.lo) || 1) * g.ph;
    if (g.mode === 'line') {
      var y = vp + (j === labelBelow(c, ser) ? -lf * 1.1 : lf * 1.1), x = g.xs ? g.xs[i] : g.band * (i + 0.5);
      return [x - w / 2, x + w / 2, y - lf * 0.6, y + lf * 0.6];
    }
    var x2 = g.band * i + (g.band - gw) / 2 + bw * j + bw * 0.46;
    if (g.mode === 'hbar') return [vp + 6, vp + 6 + w, x2 - lf * 0.62, x2 + lf * 0.62];
    return [x2 - w / 2, x2 + w / 2, vp + lf * 0.1, vp + lf * 1.3];
  }
  function labelPlan(c, ser, n, g) {
    // g: {mode:'line'|'cluster'|'hbar', band, fs, lo, hi, ph}
    var show = ser.map(function () { return []; });
    function has(s, i) { var v = s.values[i]; return typeof v === 'number' && isFinite(v); }
    if (c.labels === false) return show;
    if (c.labels === 'all') { ser.forEach(function (s, j) { for (var i = 0; i < n; i++) show[j][i] = has(s, i); }); return show; }
    var order = [], seen = {};
    function push(j, i) { var key = j + ':' + i; if (i >= 0 && !seen[key]) { seen[key] = 1; order.push([j, i]); } }
    ser.forEach(function (s, j) {
      var mx = -1, mn = -1, last = -1;
      for (var i = 0; i < n; i++) if (has(s, i)) {
        if (mx < 0 || s.values[i] > s.values[mx]) mx = i;
        if (mn < 0 || s.values[i] < s.values[mn]) mn = i;
        last = i;
      }
      push(j, mx); push(j, mn); push(j, last);
    });
    for (var i = 0; i < n; i++) ser.forEach(function (s, j) { if (has(s, i)) push(j, i); });
    var placed = [];
    order.forEach(function (o) {
      var b = labelBox(c, ser, o[0], o[1], g);
      if (placed.some(function (p) { return b[0] < p[1] && p[0] < b[1] && b[2] < p[3] && p[2] < b[3]; })) return;
      placed.push(b);
      show[o[0]][o[1]] = true;
    });
    return show;
  }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  // 帯の色: 意味の名前（DashboardKit と同じ）か #hex。スライド契約の色に読み替える
  var BAND_COL = { danger: '#c62828', accent: '#c62828', warn: '#7a471a', ok: '#21537f', sub: '#9fc0dd' };
  function bandColor(b) {
    var c = b && b.color;
    return BAND_COL[c] || (/^#[0-9a-fA-F]{6}$/.test(c || '') ? c : BAND_COL.sub);
  }
  function bandOpacity(b) { var o = b && b.opacity; return isNum(o) && o > 0 && o <= 1 ? o : 0.12; }
  // 帯（bands: [{from, to, label, color, opacity}]）が掛かる項目の番号 [始め, 終わり]。
  //   from/to は項目の値。日付の項目なら日付で比べる（間の日付も含む）。掛からなければ null
  function bandRange(b, rawCats) {
    var iso = rawCats.length && rawCats.every(function (s) { return /^\d{4}-\d{2}-\d{2}$/.test(s); });
    var f = String(b.from == null ? '' : b.from), t = String(b.to == null ? f : b.to), i0 = -1, i1 = -1;
    rawCats.forEach(function (s, i) {
      var inside = iso ? s >= f && s <= t : false;
      if (!iso && (s === f)) i0 = i;
      if (!iso && (s === t)) i1 = i;
      if (inside) { if (i0 < 0) i0 = i; i1 = i; }
    });
    return i0 >= 0 && i1 >= i0 ? [i0, i1] : null;
  }
  // なめらかな線（smooth:true）: 単調3次補間（DashboardKit の monotonePath と同じ。山や谷を越えて膨らまない）
  function smoothPath(pts) {
    var n = pts.length;
    if (n < 3) return 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' L');
    var m = [], t = [], i;
    for (i = 0; i < n - 1; i++) m.push((pts[i + 1][1] - pts[i][1]) / ((pts[i + 1][0] - pts[i][0]) || 1));
    t.push(m[0]);
    for (i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
    t.push(m[n - 2]);
    for (i = 0; i < n - 1; i++) {
      if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
      var a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
      if (s > 9) { var k = 3 / Math.sqrt(s); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
    }
    var d = 'M' + pts[0][0].toFixed(1) + ',' + pts[0][1].toFixed(1);
    for (i = 0; i < n - 1; i++) {
      var h = (pts[i + 1][0] - pts[i][0]) / 3;
      d += ' C' + (pts[i][0] + h).toFixed(1) + ',' + (pts[i][1] + t[i] * h).toFixed(1) + ' ' +
        (pts[i + 1][0] - h).toFixed(1) + ',' + (pts[i + 1][1] - t[i + 1] * h).toFixed(1) + ' ' +
        pts[i + 1][0].toFixed(1) + ',' + pts[i + 1][1].toFixed(1);
    }
    return d;
  }
  function targetOf(c) { return c.target && isNum(c.target.value) ? c.target.value : null; }
  // 値の軸（下限・上限・刻み）。html_to_pptx._chart_ticks と同じ手順（DashboardKit の computeYScale / computeFitScale と同じ考え方）
  //   ・既定: 0 を含む範囲を 4刻み前後のきりのいい値で
  //   ・fitY（折れ線だけ・max が無いとき）: データの範囲に合わせる。端に張り付けば1刻み足す。全部0以上なら0で止める
  //   ・max: 上限をこの値にする（データの最大より小さいときは使わない）。刻みは4等分
  //   ・target（目標線）の値も範囲に入れる（線が外にはみ出さない）
  function axisScale(c, ser, n) {
    var stacked = c.type === 'stacked', tg = targetOf(c), max = 0, min = 0, dlo = Infinity, dhi = -Infinity;
    for (var i = 0; i < n; i++) {
      var sum = 0;
      ser.forEach(function (s) {
        var v = s.values[i];
        if (isNum(v)) { dlo = Math.min(dlo, v); dhi = Math.max(dhi, v); } else v = 0;
        sum += v; max = Math.max(max, v); min = Math.min(min, v);
      });
      if (stacked) max = Math.max(max, sum);
    }
    if (tg !== null) { max = Math.max(max, tg); min = Math.min(min, tg); dlo = Math.min(dlo, tg); dhi = Math.max(dhi, tg); }
    var hasMax = isNum(c.max) && c.max >= max;
    if (c.type === 'line' && c.fitY === true && !isNum(c.max) && dlo <= dhi) {
      var span = dhi - dlo; if (span <= 0) span = Math.abs(dhi) * 0.1 || 1;
      var fst = nice(span / 4), flo = Math.floor(dlo / fst) * fst, fhi = Math.ceil(dhi / fst) * fst;
      if (Math.abs(dlo - flo) < fst * 0.1) flo -= fst;
      if (Math.abs(fhi - dhi) < fst * 0.1) fhi += fst;
      if (dlo >= 0 && flo < 0) flo = 0;
      return { lo: +flo.toFixed(10), hi: +fhi.toFixed(10), step: fst };
    }
    var step = nice((max - min) / 4 || 1), lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    if (hasMax) { hi = c.max; step = (hi - lo) / 4 || 1; }
    return { lo: lo, hi: hi, step: step };
  }
  // 軸のあるグラフの広さ（html_to_pptx.chart_label_plan も同じ式で見積もる）
  function axisGeo(c, W, H, fs) {
    // 日付（2026-04-01）は 4/1 と短く出す（DashboardKit と同じ。データはそのまま）
    var iso = (c.categories || []).length > 0 && (c.categories || []).every(function (s) { return /^\d{4}-\d{2}-\d{2}$/.test(s); });
    var cats = (c.categories || []).map(function (s) { return iso ? +s.slice(5, 7) + '/' + +s.slice(8, 10) : s; });
    var ser = c.series || [], n = cats.length;
    var horiz = c.type === 'bar', stacked = c.type === 'stacked', line = c.type === 'line';
    // 上は凡例か、いちばん上の数値（上限ちょうどの棒の「100%」）が入る分を空ける
    var showLeg = c.legend !== false && ser.length > 1, top = showLeg ? fs * 2.2 : fs * 1.6;
    var sc = axisScale(c, ser, n), lo = sc.lo, hi = sc.hi, step = sc.step;
    var ticks = []; for (var t = 0; lo + step * t <= hi + step / 2; t++) ticks.push(+(lo + step * t).toFixed(10));
    var vw = Math.max.apply(null, ticks.map(function (t) { return tw(fmt(t, c.unit), fs * 0.85); }));
    var cw = Math.max.apply(null, cats.map(function (s) { return tw(s, fs); }).concat([0]));
    // 横棒は右端の目盛り文字が半分はみ出すので、その分を右に空ける
    var L = horiz ? cw + 10 : vw + 10, B = horiz ? fs * 1.8 : fs * 1.9, R = horiz ? vw / 2 + 4 : fs * 0.8;
    var pw = W - L - R, ph = H - top - B, band = (horiz ? ph : pw) / Math.max(1, n);
    // timeAxis（折れ線・項目がすべて日付）: 点を実際の日付の間隔に置く。1日を1枠とし、点は枠の中央
    //   （PowerPoint の日付の軸と同じ置き方。毎日そろったデータなら等間隔と同じになる）
    var days = iso ? (c.categories || []).map(function (s) { return Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / 864e5; }) : null;
    var xs = null, d0 = 0, span = 0;
    if (line && c.timeAxis === true && iso && n) {
      d0 = Math.min.apply(null, days); span = Math.max.apply(null, days) - d0;
      xs = days.map(function (d) { return pw * (d - d0 + 0.5) / (span + 1); });
    }
    return { cats: cats, ser: ser, n: n, horiz: horiz, stacked: stacked, line: line, showLeg: showLeg, top: top,
      lo: lo, hi: hi, ticks: ticks, cw: cw, L: L, pw: pw, ph: ph, band: band, iso: iso, days: days, xs: xs, d0: d0, span: span,
      plan: { mode: line ? 'line' : horiz ? 'hbar' : 'cluster', band: band, fs: fs, lo: lo, hi: hi, ph: horiz ? pw : ph, xs: xs } };
  }
  // テスト用（tests/chart_label_plan.js）: どの点に数値を出すか
  function planFor(c, W, H, fs) {
    var g = axisGeo(c, W, H, fs);
    return g.stacked ? g.ser.map(function () { return []; }) : labelPlan(c, g.ser, g.n, g.plan);
  }
  // 縦棒・積み上げ・横棒・折れ線（軸のあるグラフ）
  function axisChart(c, W, H, fs) {
    var g = axisGeo(c, W, H, fs), cats = g.cats, ser = g.ser, n = g.n, cols = c.colors || PAL;
    var horiz = g.horiz, stacked = g.stacked, line = g.line, showLeg = g.showLeg, top = g.top;
    var lo = g.lo, hi = g.hi, ticks = g.ticks, cw = g.cw, L = g.L, pw = g.pw, ph = g.ph;
    var out = showLeg ? legend(ser.map(function (s) { return s.name; }), cols, W, fs) : '';
    function vpos(v) { return horiz ? L + (v - lo) / (hi - lo) * pw : top + ph - (v - lo) / (hi - lo) * ph; }
    // 項目の位置（中心）。timeAxis なら日付の間隔
    function xat(i) { return L + (g.xs ? g.xs[i] : g.band * (i + 0.5)); }
    // weekendBand（折れ線・項目がすべて日付）: 土日を薄く塗る。timeAxis なら範囲の中の土日すべて、そうでなければ土日の項目
    if (line && c.weekendBand === true && g.iso) {
      var isWe = function (d) { var w = new Date(d * 864e5).getUTCDay(); return w === 0 || w === 6; };
      if (g.xs) { for (var d = g.d0; d <= g.d0 + g.span; d++) if (isWe(d)) out += rect(L + pw * (d - g.d0) / (g.span + 1), top, pw / (g.span + 1), ph, WEEKEND); }
      else g.days.forEach(function (d, i) { if (isWe(d)) out += rect(L + g.band * i, top, g.band, ph, WEEKEND); });
    }
    // 帯（bands）: 線・棒の後ろに薄く敷く。名前は帯の左上（帯が48px以上のとき）
    var bandLabs = '';
    if (!horiz && Array.isArray(c.bands)) c.bands.forEach(function (b) {
      var r = bandRange(b, c.categories || []);
      if (!r) return;
      var x0, x1;
      if (g.xs) {
        // 日付の軸: 帯の日付そのもの（両端の日を含む）を、表示の範囲で切って塗る
        var dd = function (s, def) { return /^\d{4}-\d{2}-\d{2}$/.test(s || '') ? Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / 864e5 : def; };
        var f = Math.max(g.d0, dd(b.from, g.days[r[0]])), t2 = Math.min(g.d0 + g.span, dd(b.to, g.days[r[1]]));
        x0 = L + pw * (f - g.d0) / (g.span + 1); x1 = L + pw * (t2 - g.d0 + 1) / (g.span + 1);
      } else { x0 = L + g.band * r[0]; x1 = L + g.band * (r[1] + 1); }
      out += '<rect x="' + x0.toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + (x1 - x0).toFixed(1) + '" height="' + ph.toFixed(1) +
        '" fill="' + bandColor(b) + '" fill-opacity="' + bandOpacity(b) + '"/>';
      if (b.label && x1 - x0 >= 48) bandLabs += txt(x0 + 4, top + fs * 0.6, String(b.label), fs * 0.85, { anchor: 'start', fill: AXIS });
    });
    out += bandLabs;
    ticks.forEach(function (t) {
      var p = vpos(t);
      out += horiz ? rect(p - 0.5, top, 1, ph, GRID) + txt(p, top + ph + fs * 0.9, fmt(t, c.unit), fs * 0.85, { fill: AXIS })
        : rect(L, p - 0.5, pw, 1, GRID) + txt(L - 6, p, fmt(t, c.unit), fs * 0.85, { anchor: 'end', fill: AXIS });
    });
    var band = g.band, z = vpos(Math.max(lo, 0));
    // 項目名が重なるときは間引く（先頭は必ず出す）
    var every = Math.max(1, Math.ceil((horiz ? fs * 1.3 : cw + fs) / Math.max(1, band)));
    var lab = stacked ? ser.map(function () { return []; }) : labelPlan(c, ser, n, g.plan);
    var labs = '', below = labelBelow(c, ser);   // 数値は棒・線の後に描く（となりの棒に隠れない）
    var lastX = -Infinity;   // timeAxis の項目名は、前の名前と重ならないものだけ出す
    cats.forEach(function (cat, i) {
      var b0 = (horiz ? top : L) + band * i;
      if (g.xs) { if (xat(i) - lastX >= cw + fs) { out += txt(xat(i), top + ph + fs * 0.95, cat, fs); lastX = xat(i); } }
      else if (i % every === 0) out += horiz ? txt(L - 8, b0 + band / 2, cat, fs, { anchor: 'end' }) : txt(b0 + band / 2, top + ph + fs * 0.95, cat, fs);
      if (line) return;
      var k = stacked ? 1 : ser.length, gw = band * 0.7, bw = gw / k, acc = 0;
      ser.forEach(function (s, j) {
        var v = +s.values[i] || 0, a = stacked ? vpos(acc) : z, e = stacked ? vpos(acc + v) : vpos(v);
        var off = b0 + (band - gw) / 2 + (stacked ? 0 : bw * j), col = cols[j % cols.length];
        out += horiz ? rect(Math.min(a, e), off, Math.abs(e - a), bw * 0.92, col)
          : rect(off, Math.min(a, e), bw * 0.92, Math.abs(e - a), col);
        if (lab[j][i]) labs += horiz ? txt(e + 6, off + bw * 0.46, fmt(v, c.unit), fs * 0.85, { anchor: 'start' })
          : txt(off + bw * 0.46, e - fs * 0.6, fmt(v, c.unit), fs * 0.85);
        acc += v;
      });
    });
    // 折れ線: 空の値（null）で線を切る（0に落とさない・DashboardKit と同じ）。dash:true の系列は破線（予測・理論値）
    var areas = '', lineStart = out.length;   // 塗りは全部の線の後ろに入れる
    if (line) ser.forEach(function (s, j) {
      var col = cols[j % cols.length], segs = [[]], dash = s.dash ? ' stroke-dasharray="9 6"' : '';
      cats.forEach(function (_, i) {
        var v = s.values[i];
        if (!isNum(v)) { if (segs[segs.length - 1].length) segs.push([]); return; }
        segs[segs.length - 1].push([xat(i), vpos(v), i]);
      });
      segs.forEach(function (pts) {
        var d = c.smooth === true ? smoothPath(pts) : 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' L');
        // 線の下の塗り（area:true・系列で area:false なら塗らない）。破線（予測）は塗らない
        if (c.area === true && s.area !== false && !s.dash && pts.length > 1) {
          var base = vpos(Math.max(lo, Math.min(0, hi)));
          // 上から下へ薄くなる塗り（DashboardKit と同じ考え方）。全面を同じ濃さで塗ると帯や目盛りが沈む
          var gid = 'skArea' + (++areaSeq);
          areas += '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + col +
            '" stop-opacity="0.14"/><stop offset="1" stop-color="' + col + '" stop-opacity="0.01"/></linearGradient></defs>' +
            '<path d="' + d + ' L' + pts[pts.length - 1][0].toFixed(1) + ',' + base.toFixed(1) + ' L' + pts[0][0].toFixed(1) + ',' + base.toFixed(1) +
            ' Z" fill="url(#' + gid + ')"/>';
        }
        if (pts.length > 1) out += '<path fill="none" stroke="' + col + '" stroke-width="3" stroke-linejoin="round"' + dash + ' d="' + d + '"/>';
        pts.forEach(function (p) {
          if (n <= 40 || pts.length === 1) out += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4.5" fill="' + (s.dash ? '#fafafa" stroke="' + col + '" stroke-width="2' : col) + '"/>';
          if (lab[j][p[2]]) labs += txt(p[0], p[1] + (j === below ? fs * 0.95 : -fs * 0.9), fmt(s.values[p[2]], c.unit), fs * 0.85);
        });
      });
    });
    if (areas) out = out.slice(0, lineStart) + areas + out.slice(lineStart);
    // 目標線（target: {value, label}）: 値の位置に破線と名前。PPTXでは破線の系列になる（凡例には出さない）
    var tg = targetOf(c);
    if (tg !== null) {
      var tp = vpos(tg), tl = (c.target.label || '目標') + ' ' + fmt(tg, c.unit), tcol = '#c62828';
      out += horiz ? '<line x1="' + tp.toFixed(1) + '" y1="' + top + '" x2="' + tp.toFixed(1) + '" y2="' + (top + ph) + '" stroke="' + tcol + '" stroke-width="2" stroke-dasharray="7 5"/>' +
        txt(tp + 4, top + fs * 0.5, tl, fs * 0.85, { anchor: 'start', fill: tcol, bold: true })
        : '<line x1="' + L + '" y1="' + tp.toFixed(1) + '" x2="' + (L + pw) + '" y2="' + tp.toFixed(1) + '" stroke="' + tcol + '" stroke-width="2" stroke-dasharray="7 5"/>' +
        txt(L + pw - 2, tp - fs * 0.7, tl, fs * 0.85, { anchor: 'end', fill: tcol, bold: true });
    }
    return out + labs + rect(horiz ? L : L, horiz ? top : top + ph, horiz ? 1 : pw, horiz ? ph : 1, AXIS);
  }
  // 円グラフ（系列は1つ目だけ使う）。凡例は右に「項目 値（割合）」
  function pieChart(c, W, H, fs) {
    var cats = c.categories || [], s = (c.series || [])[0] || { values: [] }, cols = c.colors || PAL;
    var vals = cats.map(function (_, i) { return Math.max(0, +s.values[i] || 0); });
    var tot = vals.reduce(function (a, b) { return a + b; }, 0) || 1;
    var labs = cats.map(function (cat, i) { return cat + '  ' + fmt(vals[i], c.unit) + '（' + Math.round(vals[i] / tot * 100) + '%）'; });
    var lw = Math.max.apply(null, labs.map(function (s) { return tw(s, fs); }).concat([0])) + fs * 2.9;
    // 凡例が入りきる幅を先に取り、残りで円の大きさを決める
    var r = Math.max(fs * 2, Math.min(H / 2 - fs * 0.5, (W - lw) / 2 - fs * 0.5)), cx = r + fs * 0.5, cy = H / 2, a0 = -Math.PI / 2, out = '';
    vals.forEach(function (v, i) {
      var a1 = a0 + v / tot * Math.PI * 2, col = cols[i % cols.length];
      if (v >= tot) out += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + col + '"/>';
      else if (v > 0) out += '<path fill="' + col + '" stroke="#fafafa" stroke-width="2" d="M' + cx + ',' + cy +
        ' L' + (cx + r * Math.cos(a0)).toFixed(1) + ',' + (cy + r * Math.sin(a0)).toFixed(1) +
        ' A' + r + ',' + r + ' 0 ' + (a1 - a0 > Math.PI ? 1 : 0) + ' 1 ' +
        (cx + r * Math.cos(a1)).toFixed(1) + ',' + (cy + r * Math.sin(a1)).toFixed(1) + ' Z"/>';
      a0 = a1;
    });
    var lx = cx + r + fs * 1.6, lh = Math.min(fs * 1.9, H / Math.max(1, cats.length)), ly = cy - lh * cats.length / 2 + lh / 2;
    cats.forEach(function (cat, i) {
      var y = ly + lh * i;
      out += rect(lx, y - fs * 0.4, fs * 0.8, fs * 0.8, cols[i % cols.length]) +
        txt(lx + fs * 1.3, y, labs[i], fs, { anchor: 'start' });
    });
    return out;
  }
  // サンキー（type:"sankey"・2026-10-14 利用者「サンキーいいね」）
  //   {"nodes":[{"id","label"}], "links":[{"from","to","value"}], "unit"}。DashboardKit と同じデータの形
  //   列＝起点からの段数（いちばん長い道）、列の中は量の多い順に上から。帯の太さは量に比例・色は出どころの箱の色
  //   名前と量は箱の右（いちばん右の列の分は右を空ける）。PPTX は、この絵を PowerPoint の図形（帯・箱）と文字枠にする
  function sankeyData(c) {
    var nodes = (c.nodes || []).filter(function (n) { return n && n.id != null; }).map(function (n) { return { id: String(n.id), label: String(n.label == null ? n.id : n.label) }; });
    var byId = {}; nodes.forEach(function (n) { byId[n.id] = n; n.ins = []; n.outs = []; });
    var links = (c.links || []).filter(function (l) { return l && byId[String(l.from)] && byId[String(l.to)] && isNum(l.value) && l.value > 0 && String(l.from) !== String(l.to); })
      .map(function (l) { return { s: byId[String(l.from)], t: byId[String(l.to)], v: l.value }; });
    links.forEach(function (l) { l.s.outs.push(l); l.t.ins.push(l); });
    nodes.forEach(function (n) {
      n.v = Math.max(n.ins.reduce(function (a, l) { return a + l.v; }, 0), n.outs.reduce(function (a, l) { return a + l.v; }, 0));
    });
    // 段数: 入りの無い箱を0列目に。いちばん長い道で決める（輪になっていても止まる）
    nodes.forEach(function (n) { n.col = 0; });
    for (var it = 0; it < nodes.length; it++) {
      var moved = false;
      links.forEach(function (l) { if (l.t.col < l.s.col + 1 && l.s.col + 1 < nodes.length) { l.t.col = l.s.col + 1; moved = true; } });
      if (!moved) break;
    }
    return { nodes: nodes.filter(function (n) { return n.v > 0; }), links: links };
  }
  function sankeyChart(c, W, H, fs) {
    var d = sankeyData(c), nodes = d.nodes, cols = c.colors || PAL, out = '';
    if (!nodes.length) return txt(W / 2, H / 2, 'データがありません', fs, { fill: AXIS });
    var ncol = Math.max.apply(null, nodes.map(function (n) { return n.col; })) + 1;
    var lab = function (n) { return n.label + '  ' + fmt(n.v, c.unit); };
    var nw = Math.max(10, fs * 0.9);
    // いちばん右の列の名前は箱の右の外に出す（帯に重ねない）。その分を右に空ける
    var lastW = Math.max.apply(null, nodes.filter(function (n) { return n.col === ncol - 1; }).map(function (n) { return tw(lab(n), fs); }).concat([0]));
    var colX = function (k) { return ncol > 1 ? (W - nw - lastW - fs * 0.6) * k / (ncol - 1) : 0; };
    cols = c.colors || SANKEY_PAL;
    var gap = fs * 0.9, top = fs * 0.4, bottom = fs * 0.4, k = Infinity, i;
    var byCol = [];
    for (i = 0; i < ncol; i++) byCol.push(nodes.filter(function (n) { return n.col === i; }).sort(function (a, b) { return b.v - a.v; }));
    byCol.forEach(function (list) {
      var sum = list.reduce(function (a, n) { return a + n.v; }, 0);
      if (sum > 0) k = Math.min(k, (H - top - bottom - gap * (list.length - 1)) / sum);
    });
    if (!isFinite(k) || k <= 0) k = 1;
    var ci = 0;
    byCol.forEach(function (list, cidx) {
      var used = list.reduce(function (a, n) { return a + n.v * k; }, 0) + gap * (list.length - 1), y = top + (H - top - bottom - used) / 2;
      list.forEach(function (n) { n.x = colX(cidx); n.y = y; n.h = Math.max(1, n.v * k); n.c = cols[ci++ % cols.length]; y += n.h + gap; n.so = 0; n.to = 0; });
    });
    // 帯: 出どころ・行き先それぞれで、相手の上下の順に積む（帯が交差しにくい）
    nodes.forEach(function (n) {
      n.outs.sort(function (a, b) { return a.t.y - b.t.y; });
      n.ins.sort(function (a, b) { return a.s.y - b.s.y; });
    });
    nodes.forEach(function (n) { n.outs.forEach(function (l) { l.sy = n.y + n.so; n.so += l.v * k; }); n.ins.forEach(function (l) { l.ty = n.y + n.to; n.to += l.v * k; }); });
    d.links.forEach(function (l) {
      if (l.s.x === undefined || l.t.x === undefined) return;
      var x0 = l.s.x + nw, x1 = l.t.x, th = l.v * k, mx = (x0 + x1) / 2;
      out += '<path d="M' + x0.toFixed(1) + ',' + l.sy.toFixed(1) + ' C' + mx.toFixed(1) + ',' + l.sy.toFixed(1) + ' ' + mx.toFixed(1) + ',' + l.ty.toFixed(1) + ' ' + x1.toFixed(1) + ',' + l.ty.toFixed(1) +
        ' L' + x1.toFixed(1) + ',' + (l.ty + th).toFixed(1) + ' C' + mx.toFixed(1) + ',' + (l.ty + th).toFixed(1) + ' ' + mx.toFixed(1) + ',' + (l.sy + th).toFixed(1) + ' ' + x0.toFixed(1) + ',' + (l.sy + th).toFixed(1) +
        ' Z" fill="' + l.s.c + '" fill-opacity="0.35"/>';
    });
    nodes.forEach(function (n) {
      out += rect(n.x, n.y, nw, n.h, n.c);
      out += txt(n.x + nw + fs * 0.4, n.y + n.h / 2, lab(n), fs, { anchor: 'start' });
    });
    return out;
  }
  // ---- 地図（type:"map"・2026-10-14 利用者「地図の上に、棒グラフとか、人口を示す円」）----
  //   {"type":"map","map":"japan-pref","mark":"circle|bar|fill","unit":"万人","values":{"東京都":1404,...}}
  //   系列が2つ以上なら "series":[{"name":"2020年","values":{...}}, ...]（棒は並べる・円と塗り分けは1つ目）
  //   県は 名前（東京都）・短い名前（東京）・コード（13 / "JP-13"）のどれで書いてもよい
  //   円は面積が値に比例（半径は平方根）。塗り分けは5段（スライドの色の濃淡）。地図データは maps/<名前>.js（map_build.py が作る）
  //   PPTX はサンキーと同じく、描いた県・円・棒を PowerPoint の図形、名前と数値を文字枠にする（県ごとに色を直せる）
  var MAP_STEPS = ['#eef3f8', '#d4dde7', '#9fc0dd', '#21537f', '#162a42'];
  function mapSeries(c) {
    if (Array.isArray(c.series) && c.series.length && c.series[0] && !Array.isArray(c.series[0].values))
      return c.series.map(function (s) { return { name: String(s.name == null ? '' : s.name), values: s.values || {} }; });
    return [{ name: c.title || '', values: c.values || {} }];
  }
  function mapIndex(m) {
    var ix = {};
    m.regions.forEach(function (r) { [r.name, r.short, r.code, String(+r.code), 'JP-' + r.code].forEach(function (k) { ix[k] = r; }); });
    return ix;
  }
  var mapLoading = {};
  function mapData(name) {
    var all = window.SLIDEKIT_MAPS || {};
    if (all[name]) return all[name];
    if (!mapLoading[name] && /^[a-z0-9-]+$/.test(name)) {
      // slidekit-chart.js と同じ場所の maps/ から読む（file:// でも読める script の形）
      mapLoading[name] = true;
      var me = document.querySelector('script[src*="slidekit-chart"]'), sc = document.createElement('script');
      sc.className = 'seui';
      sc.src = (me ? me.getAttribute('src').replace(/slidekit-chart\.js.*$/, '') : '') + 'maps/' + name + '.js';
      sc.onerror = function () { console.warn('SlideKit: 地図データを読めない（' + sc.src + '）'); };
      document.head.appendChild(sc);
    }
    return null;
  }
  // ---- 拠点と、その範囲（商圏）・2026-10-15 利用者「イオンの店舗とその商圏を描くとか」----
  //   "points":[{"name":"A店","lat":35.68,"lon":139.76,"value":120}]  緯度経度で置く（value があれば点の大きさ）
  //   "areas":"circle"（半径 radius_km の円・既定）|"voronoi"（いちばん近い拠点で陸地を分ける）|"none"
  //   "radius_km":[3,5]（既定）。voronoi で radius_km を書くと、いちばん大きい半径の内側に限る
  //   "bbox":[西の経度,南の緯度,東の経度,北の緯度]（無ければ拠点と円が収まる範囲に寄せる）
  //   寄せた地図は細かい県境（maps/japan-pref-detail.js）。画面の外・海に出る部分は図形を切って出す＝PPTXでもはみ出さない
  //   区画の色: グラフの系列色（DashboardKit 既定テーマの6色・slidekit-defs.js の chartPalette）を薄く。隣どうしは別の色
  var AREA_PAL = [['#2563eb', 0.2], ['#10b981', 0.24], ['#94a3b8', 0.38], ['#06b6d4', 0.22], ['#1e40af', 0.16], ['#14b8a6', 0.3]];
  function mapPoints(c) {
    return (Array.isArray(c.points) ? c.points : []).filter(function (p) { return p && isNum(p.lat) && isNum(p.lon); });
  }
  function mapAreas(c, zoom) { return ['circle', 'voronoi', 'none'].indexOf(c.areas) >= 0 ? c.areas : zoom ? 'circle' : 'none'; }
  function mapRadii(c) {
    var r = (Array.isArray(c.radius_km) ? c.radius_km : []).filter(function (v) { return isNum(v) && v > 0; });
    return r.length ? r.slice(0, 3).sort(function (a, b) { return a - b; }) : [3, 5];
  }
  // 緯度経度 → 地図の座標（map_build.py の proj。沖縄は左上の枠へ動かしたのと同じだけ動かす）
  function mapProj(m, lon, lat) {
    var p = m.proj, o = p.oki || [0, 0, -99, -999];
    if (lat < o[2] && lon < o[3]) { lon += o[0]; lat += o[1]; }
    return [(lon * p.k - p.x0) * p.s, (-lat - p.y0) * p.s];
  }
  function ringsOf(r) {
    if (!r._rings) r._rings = r.d.split('Z').filter(function (t) { return /\d/.test(t); }).map(function (t) {
      return t.replace(/[ML]/g, ' ').trim().split(/\s+/).map(function (xy) { var a = xy.split(','); return [+a[0], +a[1]]; });
    });
    return r._rings;
  }
  function polyD(q) { return 'M' + q.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' L') + 'Z'; }
  function ellPoly(cx, cy, rx, ry, n) {
    var o = [];
    for (var i = 0; i < n; i++) { var a = i / n * Math.PI * 2; o.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)]); }
    return o;
  }
  // 多角形を半平面 a·x + b·y <= cc で切る（Sutherland–Hodgman の1辺分）
  function clipHalf(poly, a, b, cc) {
    var out = [], n = poly.length;
    for (var i = 0; i < n; i++) {
      var P = poly[i], Q = poly[(i + 1) % n], dp = a * P[0] + b * P[1] - cc, dq = a * Q[0] + b * Q[1] - cc;
      if (dp <= 0) out.push(P);
      if ((dp <= 0) !== (dq <= 0)) { var t = dp / (dp - dq); out.push([P[0] + (Q[0] - P[0]) * t, P[1] + (Q[1] - P[1]) * t]); }
    }
    return out;
  }
  function clipRect(poly, b) {
    poly = clipHalf(poly, -1, 0, -b[0]);
    if (poly.length) poly = clipHalf(poly, 1, 0, b[2]);
    if (poly.length) poly = clipHalf(poly, 0, -1, -b[1]);
    if (poly.length) poly = clipHalf(poly, 0, 1, b[3]);
    return poly;
  }
  // 凸の多角形 cell で切る（向きは問わない）。県の形（凹んでいてよい）を、商圏の区画で切るのに使う
  function clipConvex(poly, cell) {
    var n = cell.length, a2 = 0;
    for (var i = 0; i < n; i++) a2 += cell[i][0] * cell[(i + 1) % n][1] - cell[(i + 1) % n][0] * cell[i][1];
    var sg = a2 > 0 ? 1 : -1;
    for (var j = 0; j < n && poly.length; j++) {
      var A = cell[j], B = cell[(j + 1) % n], ex = B[0] - A[0], ey = B[1] - A[1];
      poly = clipHalf(poly, sg * ey, -sg * ex, sg * (ey * A[0] - ex * A[1]));
    }
    return poly;
  }
  function polyBox(q) {
    var b = [Infinity, Infinity, -Infinity, -Infinity];
    q.forEach(function (p) { b[0] = Math.min(b[0], p[0]); b[1] = Math.min(b[1], p[1]); b[2] = Math.max(b[2], p[0]); b[3] = Math.max(b[3], p[1]); });
    return b;
  }
  // 寄せる範囲（地図の座標）: bbox か、拠点と円が収まる範囲。最小10km四方。縦横比は地図を描く枠に合わせて広げる
  function mapView(m, c, pts, aspect, zoom) {
    var p = m.proj, kmY = p.s / 111.32, v, lat;
    if (Array.isArray(c.bbox) && c.bbox.length === 4 && c.bbox.every(isNum)) {
      var a = mapProj(m, c.bbox[0], c.bbox[3]), b = mapProj(m, c.bbox[2], c.bbox[1]);
      v = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
      lat = (c.bbox[1] + c.bbox[3]) / 2;
    } else {
      var xy = pts.map(function (q) { return mapProj(m, q.lon, q.lat); });
      lat = pts.reduce(function (t, q) { return t + q.lat; }, 0) / pts.length;
      v = polyBox(xy);
      var ar = mapAreas(c, zoom), rk = ar === 'circle' || (ar === 'voronoi' && Array.isArray(c.radius_km)) ? Math.max.apply(null, mapRadii(c)) : 0;
      var py = Math.max(rk * 1.12 * kmY, 0.12 * Math.max(v[2] - v[0], v[3] - v[1])), px = rk ? rk * 1.12 * kmY * p.k / Math.cos(lat * Math.PI / 180) : py;
      v = [v[0] - px, v[1] - py, v[2] + px, v[3] + py];
    }
    var cx = (v[0] + v[2]) / 2, cy = (v[1] + v[3]) / 2, w = Math.max(v[2] - v[0], 10 * kmY), h = Math.max(v[3] - v[1], 10 * kmY);
    if (w / h < aspect) w = h * aspect; else h = w / aspect;
    return { box: [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], lat: lat };
  }
  // いちばん近い拠点で陸地を分ける（ボロノイ）。距離は km で測る（横の px を f 倍すると縦の px と同じ長さ）
  //   区画は凸なので、県の形（画面で切ったもの）を区画で切れば「陸の上の区画」になる。色は隣どうしが違うように選ぶ
  function mapVoronoi(pts, pxy, regPx, box, radii, kmX, kmY, lat0) {
    var f = kmY / kmX(lat0), f2 = f * f, n = pts.length, cells = [], col = [], out = '', i, j;
    for (i = 0; i < n; i++) {
      var cell = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], pi = pxy[i];
      for (j = 0; j < n && cell.length; j++) {
        var pj = pxy[j];
        if (j === i || (pj[0] === pi[0] && pj[1] === pi[1])) continue;
        cell = clipHalf(cell, 2 * f2 * (pj[0] - pi[0]), 2 * (pj[1] - pi[1]), f2 * (pj[0] * pj[0] - pi[0] * pi[0]) + (pj[1] * pj[1] - pi[1] * pi[1]));
      }
      cells.push(cell);
    }
    var dist = function (v, p) { var dx = (v[0] - p[0]) * f, dy = v[1] - p[1]; return Math.sqrt(dx * dx + dy * dy); };
    for (i = 0; i < n; i++) {
      var used = {};
      for (j = 0; j < i; j++) {
        if (cells[i].some(function (v) { return Math.abs(dist(v, pxy[i]) - dist(v, pxy[j])) < 0.5; })) used[col[j]] = 1;
      }
      var k = 0;
      while (used[k] && k < AREA_PAL.length - 1) k++;
      col.push(k);
    }
    cells.forEach(function (cell, i2) {
      if (radii) { var rk = radii[radii.length - 1]; cell = clipConvex(cell, ellPoly(pxy[i2][0], pxy[i2][1], rk * kmX(pts[i2].lat), rk * kmY, 72)); }
      if (cell.length < 3) return;
      var cb = polyBox(cell), d = '';
      regPx.forEach(function (g) {
        if (g.b[0] > cb[2] || g.b[2] < cb[0] || g.b[1] > cb[3] || g.b[3] < cb[1]) return;
        var q = clipConvex(g.q, cell);
        if (q.length >= 3) d += polyD(q);
      });
      if (d) out += '<path d="' + d + '" fill="' + AREA_PAL[col[i2]][0] + '" fill-opacity="' + AREA_PAL[col[i2]][1] + '" stroke="#fafafa" stroke-width="1.5" stroke-linejoin="round"/>';
    });
    return out;
  }
  function mapChart(c, W, H, fs) {
    var pts = mapPoints(c), zoom = c.zoom !== false && (pts.length > 0 || Array.isArray(c.bbox));
    var m = mapData(c.map || (zoom ? 'japan-pref-detail' : 'japan-pref'));
    if (!m) return txt(W / 2, H / 2, '地図を読み込み中', fs, { fill: AXIS });
    if (!m.proj && (zoom || pts.length)) { console.warn('SlideKit: この地図データは緯度経度を持たない（map_build.py で作り直す）'); zoom = false; pts = []; }
    var ix = mapIndex(m), ser = mapSeries(c), mark = c.mark || 'circle', lf = fs * 0.85, out = '';
    var vals = ser.map(function (s) {
      var o = {};
      Object.keys(s.values).forEach(function (k) { var r = ix[String(k)], v = s.values[k]; if (r && isNum(v)) o[r.code] = v; });
      return o;
    });
    var v0 = vals[0], codes = Object.keys(v0), max = 0, min = Infinity;
    (mark === 'bar' ? vals : [v0]).forEach(function (o) { Object.keys(o).forEach(function (k) { max = Math.max(max, o[k]); min = Math.min(min, o[k]); }); });
    if (!isFinite(min)) min = 0;
    // 凡例の幅を右に取り、残りに地図を入れる（縦横比はそのまま）
    var legW = fs * 10, mv = zoom ? mapView(m, c, pts, (W - legW) / H, zoom) : { box: [0, 0, m.w, m.h], lat: 36 }, vb = mv.box;
    var vw = vb[2] - vb[0], vh = vb[3] - vb[1], s = Math.min((W - legW) / vw, H / vh), mw = vw * s, mh = vh * s, oy = (H - mh) / 2;
    var P = function (x, y) { return [(x - vb[0]) * s, oy + (y - vb[1]) * s]; };
    var inView = function (q) { return q[0] >= 0 && q[0] <= mw && q[1] >= oy && q[1] <= oy + mh; };
    // 塗り分け: 5段。区切りは値の並びの 20・40・60・80% の位置を、上2桁に丸めた値（人口のように偏った値でも5段に散る）
    var sorted = Object.keys(v0).map(function (k2) { return v0[k2]; }).sort(function (a, b) { return a - b; });
    var round2 = function (v) { if (!v) return 0; var p = Math.pow(10, Math.floor(Math.log10(Math.abs(v))) - 1); return Math.round(v / p) * p; };
    var brk = [0.2, 0.4, 0.6, 0.8].map(function (q) { return round2(sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))] || 0); })
      .filter(function (b, i, a) { return i === 0 || b > a[i - 1]; });
    while (brk.length < 4) brk.push((brk[brk.length - 1] || 0) + 1e-9);   // 値の種類が少ないとき（段が詰まる）
    var cls = function (v) { var i = 0; while (i < 4 && v >= brk[i]) i++; return i; };
    var missing = false, hasVals = Object.keys(v0).length > 0, regPx = [], outlines = '', labAt = {};
    var paint = function (r) {
      var has = isNum(v0[r.code]), fill = '#eef3f8', stroke = '#9fc0dd';
      if (mark === 'fill' && hasVals) { if (has) { fill = MAP_STEPS[cls(v0[r.code])]; stroke = '#fafafa'; } else { fill = '#fafafa'; stroke = '#d4dde7'; missing = true; } }
      return [fill, stroke];
    };
    if (!zoom) {
      out += '<g transform="translate(0,' + oy.toFixed(1) + ') scale(' + s.toFixed(5) + ')">';
      m.regions.forEach(function (r) {
        var fs2 = paint(r);
        out += '<path d="' + r.d + '" fill="' + fs2[0] + '" stroke="' + fs2[1] + '" stroke-width="' + (1 / s).toFixed(2) + '" stroke-linejoin="round"/>';
      });
      (m.frames || []).forEach(function (f) {
        out += '<rect x="' + f[0] + '" y="' + f[1] + '" width="' + f[2] + '" height="' + f[3] + '" fill="none" stroke="#d4dde7" stroke-width="' + (1 / s).toFixed(2) + '"/>';
      });
      out += '</g>';
    } else {
      // 寄せた地図: 画面の外を切った県の形を、画面の座標で描く（拡大しても線の太さは1px）
      m.regions.forEach(function (r) {
        var d = '', big = 0;
        ringsOf(r).forEach(function (g) {
          var q = clipRect(g, vb);
          if (q.length < 3) return;
          q = q.map(function (p) { return P(p[0], p[1]); });
          regPx.push({ q: q, b: polyBox(q) });
          d += polyD(q);
          // 県の名前は、画面に見えている部分（いちばん大きい切れ端）の重心に置く
          var a = 0, gx = 0, gy = 0;
          for (var i = 0; i < q.length; i++) {
            var p0 = q[i], p1 = q[(i + 1) % q.length], cr = p0[0] * p1[1] - p1[0] * p0[1];
            a += cr; gx += (p0[0] + p1[0]) * cr; gy += (p0[1] + p1[1]) * cr;
          }
          if (Math.abs(a) > big) { big = Math.abs(a); labAt[r.code] = [gx / (3 * a), gy / (3 * a)]; }
        });
        if (!d) return;
        var fs2 = paint(r);
        out += '<path d="' + d + '" fill="' + fs2[0] + '" stroke="' + fs2[1] + '" stroke-width="1" stroke-linejoin="round"/>';
        outlines += '<path d="' + d + '" fill="none" stroke="' + (mark === 'fill' && hasVals ? '#fafafa' : '#9fc0dd') + '" stroke-width="1" stroke-linejoin="round"/>';
      });
    }
    // 拠点（画面の座標）と範囲。範囲は県の形の上・県の値の印の下に描く
    var areas = mapAreas(c, zoom), radii = mapRadii(c), kmY = m.proj ? m.proj.s / 111.32 * s : 0, pmax = 0;
    var kmX = function (lat) { return kmY * m.proj.k / Math.cos(lat * Math.PI / 180); };
    var pxy = pts.map(function (q) { if (isNum(q.value)) pmax = Math.max(pmax, q.value); var a = mapProj(m, q.lon, q.lat); return P(a[0], a[1]); });
    var mapBox = [0, oy, mw, oy + mh];
    if (pts.length && areas === 'circle') {
      pts.forEach(function (q, i) {
        radii.slice().reverse().forEach(function (rk, j) {
          var poly = clipRect(ellPoly(pxy[i][0], pxy[i][1], rk * kmX(q.lat), rk * kmY, 72), mapBox);
          if (poly.length < 3) return;
          // 県の塗り分けの上では、濃い県でも見えるように白の縁を下に敷く
          if (mark === 'fill' && hasVals) out += '<path d="' + polyD(poly) + '" fill="none" stroke="#fafafa" stroke-width="3.5"/>';
          out += '<path d="' + polyD(poly) + '" fill="#21537f" fill-opacity="0.08" stroke="#21537f" stroke-opacity="0.65" stroke-width="1.2"' +
            (j === 0 && radii.length > 1 ? ' stroke-dasharray="5 4"' : '') + '/>';
        });
      });
    }
    if (pts.length > 1 && areas === 'voronoi') out += mapVoronoi(pts, pxy, regPx, mapBox, Array.isArray(c.radius_km) ? radii : null, kmX, kmY, mv.lat) + outlines;
    if (zoom) out += '<rect x="0.5" y="' + (oy + 0.5).toFixed(1) + '" width="' + (mw - 1).toFixed(1) + '" height="' + (mh - 1).toFixed(1) + '" fill="none" stroke="#d4dde7" stroke-width="1"/>';
    // 印と、名前・数値（重ならないものだけ。値の大きい県から置く）
    var rmax = Math.min(mw, mh) * 0.06, hmax = mh * 0.2, bw = Math.max(4, fs * 0.45), k = ser.length, placed = [], labs = '';
    // 寄せた地図では、県の印は画面に見えている部分の真ん中に置く（見えていない県は出さない）
    var at = function (code) { return zoom ? labAt[code] : P(ix[code].cx, ix[code].cy); };
    var order = codes.filter(function (code) { return !!at(code); }).sort(function (a, b) { return v0[b] - v0[a]; });
    // 名前と数値は、ほかの名前・ほかの県の円・凡例に重ならないものだけ出す（全部の値は「表」で見られる）
    var rOf = function (v) { return Math.sqrt(Math.max(0, v) / (max || 1)) * rmax; };
    var obst = [[mw + fs * 0.5, 0, W, H]];
    // 拠点の点（値があれば面積が値に比例）。名前はほかの点に重ねない
    var prOf = function (q) { return pmax > 0 && isNum(q.value) ? Math.max(3, Math.sqrt(Math.max(0, q.value) / pmax) * fs * 0.9) : fs * 0.32; };
    pts.forEach(function (q, i) { var p = pxy[i], rr = prOf(q) + 1.5; obst.push([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr, 'pt' + i]); });
    if (mark === 'circle') order.forEach(function (code) { var p = at(code), rr = rOf(v0[code]); obst.push([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr, code]); });
    if (mark === 'bar') order.forEach(function (code) {
      var p = at(code), tl = Math.max.apply(null, vals.map(function (o) { return isNum(o[code]) && o[code] > 0 ? o[code] / (max || 1) * hmax : 0; }));
      obst.push([p[0] - k * bw / 2, p[1] - tl, p[0] + k * bw / 2, p[1], code]);
    });
    var hit = function (b, a) { return b[0] < a[2] && a[0] < b[2] && b[1] < a[3] && a[1] < b[3]; };
    var inside = function (b) { return b[0] >= 0 && b[1] >= 0 && b[2] <= W && b[3] <= H; };
    var free = function (b, code) { return inside(b) && !placed.some(function (p) { return hit(b, p); }) && !obst.some(function (o) { return o[4] !== code && hit(b, o); }); };
    order.forEach(function (code) {
      var r = ix[code], pt = at(code), v = v0[code], t = r.short + ' ' + fmt(v, c.unit), w = tw(t, lf), box;
      if (mark === 'circle') {
        var rr = rOf(v);
        out += '<circle cx="' + pt[0].toFixed(1) + '" cy="' + pt[1].toFixed(1) + '" r="' + Math.max(1.5, rr).toFixed(1) + '" fill="#21537f" fill-opacity="0.55" stroke="#fafafa" stroke-width="1"/>';
        // 置き場所は 右→左→上→下 の順に試す。大きい方から5県は、ほかの円には重なってもよい（名前が無いと読めないため）
        var hh = lf * 0.62, cand = [[pt[0] + rr + 3, pt[1] - hh], [pt[0] - rr - 3 - w, pt[1] - hh], [pt[0] - w / 2, pt[1] - rr - 2 - hh * 2], [pt[0] - w / 2, pt[1] + rr + 2]];
        var top5 = order.indexOf(code) < 5, pick = null;
        cand.some(function (q) { var b = [q[0], q[1], q[0] + w, q[1] + hh * 2]; if (free(b, code)) { pick = b; return true; } return false; });
        if (!pick && top5) cand.some(function (q) {
          var b = [q[0], q[1], q[0] + w, q[1] + hh * 2];
          if (inside(b) && !placed.some(function (p) { return hit(b, p); }) && !hit(b, obst[0])) { pick = b; return true; } return false;
        });
        if (pick) { placed.push(pick); labs += txt(pick[0], pick[1] + hh, t, lf, { anchor: 'start' }); }
      } else if (mark === 'bar') {
        var tall = 0;
        ser.forEach(function (_, j) {
          var vj = vals[j][code]; if (!isNum(vj) || vj <= 0) return;
          var h = vj / (max || 1) * hmax, x = pt[0] + (j - k / 2) * bw;
          tall = Math.max(tall, h);
          out += rect(x, pt[1] - h, bw * 0.9, h, PAL[j % PAL.length]);
        });
        // 名前と各系列の値（「東京 12／15拠点」）。置き場所は 上→右→左
        if (k > 1) { t = r.short + ' ' + vals.map(function (o) { return isNum(o[code]) ? fmt(o[code], '') : '—'; }).join('／') + (c.unit || ''); w = tw(t, lf); }
        var bh = lf * 1.24, bcand = [[pt[0] - w / 2, pt[1] - tall - lf * 1.5], [pt[0] + k * bw / 2 + 3, pt[1] - tall / 2 - bh / 2], [pt[0] - k * bw / 2 - 3 - w, pt[1] - tall / 2 - bh / 2]];
        bcand.some(function (q) {
          var b = [q[0], q[1], q[0] + w, q[1] + bh];
          if (!free(b, code)) return false;
          placed.push(b); labs += txt(b[0], b[1] + bh / 2, t, lf, { anchor: 'start' }); return true;
        });
      } else {
        box = [pt[0] - w / 2, pt[1] - lf * 0.62, pt[0] + w / 2, pt[1] + lf * 0.62];
        // 文字は県の外にもはみ出すので、白の札の上に黒で書く（濃い県でも薄い県でも読める・PPTXでは札は図形・文字は文字枠）
        if (free(box, code)) {
          placed.push(box);
          labs += '<rect x="' + (box[0] - 3).toFixed(1) + '" y="' + (box[1] - 1).toFixed(1) + '" width="' + (w + 6).toFixed(1) + '" height="' + (box[3] - box[1] + 2).toFixed(1) +
            '" rx="3" fill="#fafafa" fill-opacity="0.88"/>' + txt(pt[0], pt[1], t, lf);
        }
      }
    });
    // 拠点の印と名前（値の大きい拠点から名前を置く。重なる名前は出さない＝全部の拠点は「表」で見られる）
    var inMap = function (b) { return b[0] >= 0 && b[2] <= mw && b[1] >= oy && b[3] <= oy + mh; };
    var tag = function (b) {
      return '<rect x="' + b[0].toFixed(1) + '" y="' + b[1].toFixed(1) + '" width="' + (b[2] - b[0]).toFixed(1) + '" height="' + (b[3] - b[1]).toFixed(1) + '" rx="3" fill="#fafafa" fill-opacity="0.88"/>';
    };
    pts.forEach(function (q, i) {
      if (!inView(pxy[i])) return;
      out += '<circle cx="' + pxy[i][0].toFixed(1) + '" cy="' + pxy[i][1].toFixed(1) + '" r="' + prOf(q).toFixed(1) + '" fill="#162a42" stroke="#fafafa" stroke-width="1.5"/>';
    });
    pts.map(function (_, i) { return i; }).sort(function (a, b) { return (pts[b].value || 0) - (pts[a].value || 0) || a - b; }).forEach(function (i) {
      var q = pts[i], pt = pxy[i];
      if (!inView(pt) || !q.name) return;
      var t = q.name + (isNum(q.value) ? ' ' + fmt(q.value, c.pointUnit || '') : ''), w = tw(t, lf), hh = lf * 0.62, rr = prOf(q);
      var cand = [[pt[0] + rr + 6, pt[1] - hh], [pt[0] - rr - 6 - w, pt[1] - hh], [pt[0] - w / 2, pt[1] - rr - 5 - hh * 2], [pt[0] - w / 2, pt[1] + rr + 5]];
      cand.some(function (cq) {
        var b = [cq[0] - 3, cq[1] - 1, cq[0] + w + 3, cq[1] + hh * 2 + 1];
        if (!inMap(b) || !free(b, 'pt' + i)) return false;
        placed.push(b);
        labs += tag(b) + txt(cq[0], cq[1] + hh, t, lf, { anchor: 'start' });
        return true;
      });
    });
    // 寄せた地図で県の値が無いとき: どこの地図か分かるように県の名前を薄く出す（拠点の名前を優先）
    if (zoom && !hasVals) m.regions.forEach(function (r) {
      var pt = labAt[r.code];
      if (!pt) return;
      var w = tw(r.name, lf), b = [pt[0] - w / 2, pt[1] - lf * 0.62, pt[0] + w / 2, pt[1] + lf * 0.62];
      if (inMap(b) && free(b, '')) { placed.push(b); labs += txt(pt[0], pt[1], r.name, lf, { fill: AXIS }); }
    });
    out += labs;
    // 凡例（地図の右）
    var lx = mw + fs, ly = Math.max(fs, oy + fs), unit = c.unit ? '（' + c.unit + '）' : '';
    // 拠点の凡例は県の値の凡例の下（県の値が無ければいちばん上）
    var ly2 = !hasVals ? ly : mark === 'fill' ? ly + fs * (missing ? 10.6 : 9.2) : mark === 'circle' ? ly + fs * 2.6 + rmax * 4 : ly + ser.length * fs * 1.5 + fs * 0.5;
    if (!hasVals) {
      // 県の値なし
    } else if (mark === 'circle') {
      out += txt(lx, ly, (ser[0].name || '大きさ') + unit, fs * 0.85, { anchor: 'start', fill: AXIS });
      // 見本の円は切りのいい値（最大以下でいちばん大きい 1・2・5×10ⁿ と、その 1/5）
      var p10 = Math.pow(10, Math.floor(Math.log10(max || 1))), ref = [5, 2, 1].map(function (m) { return m * p10; }).filter(function (v) { return v <= max; })[0] || max;
      [ref, ref / 5].forEach(function (v, i) {
        var rr = rOf(v), cy = ly + fs + rmax + i * (rmax * 2 + fs * 0.6);
        out += '<circle cx="' + (lx + rmax).toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + rr.toFixed(1) + '" fill="#21537f" fill-opacity="0.55"/>' +
          txt(lx + rmax * 2 + fs * 0.5, cy, fmt(v, c.unit), fs * 0.85, { anchor: 'start' });
      });
    } else if (mark === 'bar') {
      ser.forEach(function (sj, j) {
        out += rect(lx, ly + j * fs * 1.5 - fs * 0.4, fs * 0.8, fs * 0.8, PAL[j % PAL.length]) + txt(lx + fs * 1.2, ly + j * fs * 1.5, sj.name || '系列' + (j + 1), fs * 0.85, { anchor: 'start' });
      });
    } else {
      out += txt(lx, ly, (ser[0].name || '値') + unit, fs * 0.85, { anchor: 'start', fill: AXIS });
      MAP_STEPS.forEach(function (col, i) {
        var y = ly + fs * 1.4 + i * fs * 1.4;
        var lab2 = i === 0 ? fmt(brk[0], '') + '未満' : i === 4 ? fmt(brk[3], '') + '以上' : fmt(brk[i - 1], '') + '〜' + fmt(brk[i], '');
        out += rect(lx, y - fs * 0.5, fs * 1.4, fs, col) + txt(lx + fs * 1.9, y, lab2, fs * 0.85, { anchor: 'start' });
      });
      if (missing) out += '<rect x="' + lx + '" y="' + (ly + fs * 8.4 - fs * 0.5).toFixed(1) + '" width="' + fs * 1.4 + '" height="' + fs + '" fill="#fafafa" stroke="#d4dde7"/>' +
        txt(lx + fs * 1.9, ly + fs * 8.4, 'データなし', fs * 0.85, { anchor: 'start', fill: AXIS });
    }
    if (pts.length) out += mapPointLegend(c, lx, ly2, fs, areas, radii, pmax);
    // 縮尺（寄せた地図。凡例の列のいちばん下）。長さは 1・2・5×10ⁿ km
    if (zoom) {
      var pk = kmX(mv.lat), t0 = fs * 7 / pk, p10 = Math.pow(10, Math.floor(Math.log10(t0)));
      var L = [5, 2, 1].map(function (x) { return x * p10; }).filter(function (v) { return v <= t0; })[0] || p10, bl = L * pk, by = oy + mh - fs * 0.5;
      out += '<path d="M' + lx.toFixed(1) + ',' + (by - 5).toFixed(1) + ' L' + lx.toFixed(1) + ',' + by.toFixed(1) + ' L' + (lx + bl).toFixed(1) + ',' + by.toFixed(1) +
        ' L' + (lx + bl).toFixed(1) + ',' + (by - 5).toFixed(1) + '" fill="none" stroke="#5e5e5e" stroke-width="1.2"/>' +
        txt(lx, by - fs * 0.85, fmt(L, '') + 'km', fs * 0.85, { anchor: 'start', fill: AXIS });
    }
    return out;
  }
  function mapPointLegend(c, lx, y, fs, areas, radii, pmax) {
    var pl = c.pointLabel || '拠点', lf = fs * 0.85, out = '', cx = lx + fs * 0.5, tx = lx + fs * 1.3, room = fs * 8.6;
    out += '<circle cx="' + cx.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + (fs * 0.32).toFixed(1) + '" fill="#162a42" stroke="#fafafa" stroke-width="1.5"/>' +
      txt(tx, y, pl + (pmax > 0 && c.pointUnit ? '（' + c.pointUnit + '）' : ''), lf, { anchor: 'start' });
    y += fs * 1.6;
    if (areas === 'circle') radii.forEach(function (rk, j) {
      var dash = j === radii.length - 1 && radii.length > 1 ? ' stroke-dasharray="5 4"' : '';
      out += '<circle cx="' + cx.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + (fs * 0.5).toFixed(1) + '" fill="#21537f" fill-opacity="0.08" stroke="#21537f" stroke-opacity="0.65" stroke-width="1.2"' + dash + '/>' +
        txt(tx, y, '半径' + fmt(rk, '') + 'km', lf, { anchor: 'start' });
      y += fs * 1.5;
    });
    if (areas === 'voronoi') {
      var t = '最寄りの' + pl;
      if (tw(t, lf) > room) t = '最寄りの範囲';
      out += '<rect x="' + lx.toFixed(1) + '" y="' + (y - fs * 0.5).toFixed(1) + '" width="' + fs.toFixed(1) + '" height="' + fs.toFixed(1) + '" fill="' + AREA_PAL[0][0] + '" fill-opacity="' + AREA_PAL[0][1] + '"/>' +
        txt(tx, y, t, lf, { anchor: 'start' });
      if (Array.isArray(c.radius_km)) out += txt(tx, y + fs * 1.3, '（半径' + fmt(radii[radii.length - 1], '') + 'km以内）', lf, { anchor: 'start', fill: AXIS });
    }
    return out;
  }
  // 地図を表にするとき: 1行＝1つの県（書いてある順）・列＝系列
  //   県の値が無く拠点だけのとき: 1行＝1つの拠点・列＝値（あれば）・緯度・経度
  function mapAsTable(c) {
    var ser = mapSeries(c), keys = Object.keys(ser[0].values), pts = mapPoints(c);
    if (pts.length && !keys.length) {
      var col = function (name, f) { return { name: name, values: pts.map(function (p) { var v = f(p); return isNum(v) ? v : null; }) }; };
      var cols = pts.some(function (p) { return isNum(p.value); }) ? [col('値' + (c.pointUnit ? '（' + c.pointUnit + '）' : ''), function (p) { return p.value; })] : [];
      return { type: 'table', categoryLabel: c.pointLabel || '拠点', categories: pts.map(function (p) { return String(p.name == null ? '' : p.name); }),
        series: cols.concat([col('緯度', function (p) { return p.lat; }), col('経度', function (p) { return p.lon; })]) };
    }
    return { type: 'table', unit: c.unit, categoryLabel: '地域', categories: keys,
      series: ser.map(function (s) { return { name: s.name || '値', values: keys.map(function (k) { var v = s.values[k]; return isNum(v) ? v : null; }) }; }) };
  }
  // サンキーを表にするとき: 1行＝1本の帯（出どころ → 行き先・量）
  function sankeyAsTable(c) {
    var d = sankeyData(c);
    return { type: 'table', unit: c.unit, categoryLabel: '流れ', categories: d.links.map(function (l) { return l.s.label + ' → ' + l.t.label; }),
      series: [{ name: '量', values: d.links.map(function (l) { return l.v; }) }] };
  }
  // 表（type:"table"・2026-10-14）。行＝項目・列＝系列。PPTXでは編集できる表になる（html_to_pptx.chart_table_html と同じ形）
  //   文字は 8pt（10.67px）より小さくしない。入りきらない行は「ほか N 行」にまとめる
  var MIN_TABLE_PX = 10.67;
  function tableChart(c, W, H, fs) {
    var cats = c.categories || [], ser = c.series || [], n = cats.length;
    var head = [c.categoryLabel || '項目'].concat(ser.map(function (s) { return s.name + (c.unit ? '（' + c.unit + '）' : ''); }));
    var rowsAll = cats.map(function (cat, i) {
      return [cat].concat(ser.map(function (s) { var v = s.values[i]; return v === null || v === undefined || v === '' ? '' : fmt(+v); }));
    });
    var f = fs, rh = f * 2;
    while ((n + 1) * rh > H && f > MIN_TABLE_PX) { f = Math.max(MIN_TABLE_PX, f - 1); rh = f * 2; }
    var fit = Math.max(1, Math.floor(H / rh) - 1), rows = rowsAll;
    if (n > fit) { rows = rowsAll.slice(0, Math.max(1, fit - 1)); rows.push(['ほか ' + (n - rows.length) + ' 行'].concat(ser.map(function () { return ''; }))); }
    // 列幅: 中身の幅に比例させて全幅に広げる（1列目は項目名なので左寄せ、数値は右寄せ）
    var need = head.map(function (h, j) {
      return Math.max(tw(h, f), Math.max.apply(null, rows.map(function (r) { return tw(r[j], f); }).concat([0]))) + f * 1.4;
    });
    var sum = need.reduce(function (a, b) { return a + b; }, 0), k = W / Math.max(1, sum), xs = [0];
    need.forEach(function (w) { xs.push(xs[xs.length - 1] + w * k); });
    var out = rect(0, 0, W, rh, '#eef3f8');
    head.forEach(function (h, j) {
      out += j === 0 ? txt(xs[j] + f * 0.7, rh / 2, h, f, { anchor: 'start', bold: true })
        : txt(xs[j + 1] - f * 0.7, rh / 2, h, f, { anchor: 'end', bold: true });
    });
    out += rect(0, rh - 2, W, 2, '#21537f');
    rows.forEach(function (r, i) {
      var y = rh * (i + 1);
      r.forEach(function (v, j) {
        out += j === 0 ? txt(xs[j] + f * 0.7, y + rh / 2, v, f, { anchor: 'start', fill: /^ほか \d+ 行$/.test(v) ? AXIS : INK })
          : txt(xs[j + 1] - f * 0.7, y + rh / 2, v, f, { anchor: 'end' });
      });
      out += rect(0, y + rh - 1, W, 1, GRID);
    });
    return out;
  }

  // ---- 見せ方の切り替え（DashboardKit と同じく、表・棒・折れ線などを選べる・2026-10-14）----
  //   利用者「DashboardKitだと、表、棒グラフ、折れ線とかを切り替えられるけどSlideKitでも同様に」
  //   ・見ているとき／プレゼン中: その場の見せ方だけ変わる（ファイルとPPTXは変わらない）
  //   ・編集中（✏️編集）: data-chart の type を書き換える＝保存され、PPTXもこの形になる（⌘Zで戻る）
  //   ボタンは .seui（保存・同期・コピーで外れる）。普段は隠し、グラフにマウスを乗せたときだけ出す
  var VIEWS = [['column', '縦棒'], ['bar', '横棒'], ['stacked', '積み上げ'], ['line', '折れ線'], ['pie', '円'], ['table', '表']];
  var FLOW_VIEWS = [['sankey', 'サンキー'], ['table', '表']];
  var MAP_VIEWS = [['map-circle', '円'], ['map-bar', '棒'], ['map-fill', '塗り分け'], ['table', '表']];
  var AREA_VIEWS = [['area-circle', '半径の円'], ['area-voronoi', '最寄りの範囲'], ['area-none', '点'], ['table', '表']];
  // 見せ方を data-chart に書く（地図の map-○○ は type:map ＋ mark・area-○○ は type:map ＋ areas）
  function applyView(c, type) {
    if (type.indexOf('map-') === 0) { c.type = 'map'; c.mark = type.slice(4); }
    else if (type.indexOf('area-') === 0) { c.type = 'map'; c.areas = type.slice(5); } else c.type = type;
    return c;
  }
  function isEditing() { return document.body && document.body.getAttribute('data-skit-edit') === 'on'; }
  function setView(el, type) {
    if (isEditing()) {
      // slide-edit.js が undo に積んでから data-chart を書き換える。受け手がいなければ直接書く
      var ev = new CustomEvent('skit:chart-type', { detail: { el: el, type: type }, cancelable: true });
      if (window.dispatchEvent(ev)) {
        try { var c = applyView(JSON.parse(el.getAttribute('data-chart')), type); el.setAttribute('data-chart', JSON.stringify(c)); } catch (e) { return; }
      }
      el._skView = null;
    } else {
      el._skView = type;
    }
    render(el);
  }
  function switcher(el, saved, view, views) {
    // ⌘Z（中身ごと戻す）や同期で、動かないボタンの写しが入ることがある。自分で作ったもの以外は外す
    el.querySelectorAll(':scope > .sk-chart-sw').forEach(function (x) { if (x !== el._skSw) x.remove(); });
    var sw = el._skSw;
    if (sw && !sw.isConnected) el.appendChild(sw);
    if (!sw) {
      sw = document.createElement('div');
      sw.className = 'seui sk-chart-sw';
      sw.setAttribute('role', 'group');
      sw.setAttribute('aria-label', 'グラフの見せ方');
      // グラフの上の外側・左寄せに出す（表の見出しや凡例を隠さない／編集中の右上の番号札とも重ならない）
      sw.style.cssText = 'position:absolute;bottom:100%;left:0;z-index:5;display:none;gap:2px;padding:3px;background:#fafafa;' +
        'border:1px solid #d4dde7;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.12);font:600 14px/1 sans-serif';
      // 編集画面の選択・ドラッグに渡さない（ボタンを押しただけでグラフが動かないように）
      sw.addEventListener('mousedown', function (e) { e.stopPropagation(); });
      sw.addEventListener('click', function (e) {
        e.stopPropagation();
        var b = e.target.closest && e.target.closest('button[data-view]');
        if (!b) return;
        var t = b.getAttribute('data-view');
        if (t === 'reset') { el._skView = null; render(el); } else setView(el, t);
      });
      el._skSw = sw;
      el.appendChild(sw);
      el.addEventListener('mouseenter', function () { sw.style.display = 'flex'; });
      el.addEventListener('mouseleave', function () { sw.style.display = 'none'; });
    }
    while (sw.firstChild) sw.removeChild(sw.firstChild);
    var editing = isEditing();
    (views || VIEWS).forEach(function (v) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-view', v[0]);
      b.textContent = v[1];
      var on = v[0] === view;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = editing ? 'この形にする（保存され、PPTXもこの形になる）' : 'この場の見せ方だけ変える（ファイルとPPTXは変わらない）';
      b.style.cssText = 'border:none;border-radius:4px;padding:5px 8px;cursor:pointer;font:inherit;' +
        (on ? 'background:#21537f;color:#fafafa' : 'background:transparent;color:#121212');
      sw.appendChild(b);
    });
    if (!editing && view !== saved) {
      var r = document.createElement('button');
      r.type = 'button';
      r.setAttribute('data-view', 'reset');
      r.textContent = '↺ 元の形';
      r.title = 'ファイルに書いてある形に戻す';
      r.style.cssText = 'border:none;border-left:1px solid #d4dde7;border-radius:0 4px 4px 0;padding:5px 8px;cursor:pointer;font:inherit;background:transparent;color:#5e5e5e';
      sw.appendChild(r);
    }
  }

  function render(el) {
    var c;
    try { c = JSON.parse(el.getAttribute('data-chart')); } catch (e) { el.setAttribute('title', 'data-chart のJSONが読めない: ' + e.message); return; }
    var W = el.offsetWidth || +el.getAttribute('data-w') || 600, H = el.offsetHeight || +el.getAttribute('data-h') || 360;
    var fs = +el.getAttribute('data-font-size') || 15;
    // 編集中はファイルに書いてある形で描く（見るときに一時的に変えた形のまま保存しない）
    if (isEditing()) el._skView = null;
    // 地図は「円・棒・塗り分け・表」（見せ方の名前は map-circle など）
    var geo = c.type === 'map' || (c.type === 'table' && (!!c.map || Array.isArray(c.points)));
    // 拠点だけの地図（県の値なし）は「半径の円・最寄りの範囲・表」（見せ方の名前は area-circle など）
    var ptsOnly = geo && Array.isArray(c.points) && !c.values && !Array.isArray(c.series);
    var saved = c.type !== 'map' ? (c.type || 'column') : ptsOnly ? 'area-' + mapAreas(c, true) : 'map-' + (c.mark || 'circle'), view = el._skView || saved;
    // 流れのデータ（nodes・links）はサンキーか表にだけ切り替える
    var flow = Array.isArray(c.links) && Array.isArray(c.nodes);
    if (flow && view !== 'sankey' && view !== 'table') view = 'sankey';
    if (geo && view !== 'table' && view.indexOf(ptsOnly ? 'area-' : 'map-') !== 0) view = ptsOnly ? 'area-circle' : 'map-circle';
    if (view.indexOf('map-') === 0) { c.type = 'map'; c.mark = view.slice(4); }
    else if (view.indexOf('area-') === 0) { c.type = 'map'; c.areas = view.slice(5); } else c.type = view;
    var body = c.type === 'map' ? mapChart(c, W, H, fs) : view === 'sankey' ? sankeyChart(c, W, H, fs) : view === 'pie' ? pieChart(c, W, H, fs)
      : view === 'table' ? tableChart(flow ? sankeyAsTable(c) : geo ? mapAsTable(c) : c, W, H, fs) : axisChart(c, W, H, fs);
    switcher(el, saved, view, flow ? FLOW_VIEWS : ptsOnly ? AREA_VIEWS : geo ? MAP_VIEWS : VIEWS);
    var old = el.querySelector('svg[data-sk-chart]');
    if (old) old.remove();
    // サンキーは PPTX で図形と文字枠にする（measure_layout が data-sk-chart="sankey" を測る）
    el.insertAdjacentHTML('afterbegin', '<svg data-sk-chart="' + (view === 'sankey' ? 'sankey' : c.type === 'map' ? 'map' : '1') + '" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H +
      '" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="' + esc(c.title || '') + '" style="display:block;font-family:inherit">' + body + '</svg>');
  }
  function renderAll(root) {
    (root || document).querySelectorAll('[data-chart]').forEach(render);
  }
  window.SlideKitChart = { render: render, renderAll: renderAll, palette: PAL, labelPlan: labelPlan, planFor: planFor,
    scaleFor: function (c) { var s = axisScale(c, c.series || [], (c.categories || []).length); return [s.lo, s.hi, s.step]; } };
  function start() {
    renderAll();
    // 編集で大きさ・数値・文字サイズを変えたら描き直す（描画は子要素だけ触るので属性の監視とは干渉しない）
    // 後から入ったグラフ（貼り付け・プレゼン窓への同期）も描く。描画で増える svg・ボタンは data-chart を持たないので再帰しない
    try {
      new MutationObserver(function (ms) {
        var seen = [];
        function add(el) { if (el && seen.indexOf(el) < 0) { seen.push(el); render(el); } }
        ms.forEach(function (m) {
          if (m.type === 'childList') {
            m.addedNodes.forEach(function (nd) {
              if (nd.nodeType !== 1) return;
              if (nd.hasAttribute('data-chart')) add(nd);
              nd.querySelectorAll && nd.querySelectorAll('[data-chart]').forEach(add);
            });
            return;
          }
          // 編集の入り・出: ボタンの意味（その場だけ／保存する）が変わるので全部描き直す
          if (m.attributeName === 'data-skit-edit') { document.querySelectorAll('[data-chart]').forEach(add); return; }
          if (m.target.closest && m.target.closest('.sk-chart-sw')) return;
          add(m.target.closest && m.target.closest('[data-chart]'));
        });
      }).observe(document.body, { subtree: true, attributes: true, childList: true,
        attributeFilter: ['data-chart', 'data-w', 'data-h', 'data-font-size', 'style', 'data-skit-edit'] });
    } catch (e) { /* 古いブラウザは描き直さないだけ */ }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
