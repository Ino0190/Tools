// nyuko_save.jsx — BezierKit が出した入稿用 .ai（PDF互換・Adobe専用データなし）を Illustrator で開き、
// レイヤーを「デザイン／カットライン／トンボ」に整え、色モードを合わせ、Illustrator形式で保存し直す。
// 呼び出し側（ドロップレット）が先頭に var NYUKO={src,dst,mode,cut,cutw} を付けてから実行する。
// Illustrator は PDF の光学レイヤーを「Layer 1」1枚に畳んで開くので、色で振り分け直す（pageItems は手前から順なので「末尾へ置く」で前後を保つ）:
//   M100 の線 → カットライン / それ以外の塗りなしの線 → トンボ / 残り → デザイン
(function(){
  app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
  var src = new File(NYUKO.src), dst = new File(NYUKO.dst), want = NYUKO.mode || 'cmyk';
  var cutName = NYUKO.cut || 'カットライン', cutW = NYUKO.cutw || 0.25;
  var doc = app.open(src);
  if (want === 'cmyk' && doc.documentColorSpace != DocumentColorSpace.CMYK) app.executeMenuCommand('doc-color-cmyk');
  if (want === 'rgb'  && doc.documentColorSpace != DocumentColorSpace.RGB)  app.executeMenuCommand('doc-color-rgb');
  var isCMYK = (doc.documentColorSpace == DocumentColorSpace.CMYK);
  function isMagenta(c){
    if (!c) return false;
    if (c.typename == 'CMYKColor') return c.magenta > 85 && c.cyan < 15 && c.yellow < 15 && c.black < 15;
    if (c.typename == 'RGBColor')  return c.red > 190 && c.green < 60 && c.blue > 90 && c.blue < 200;
    if (c.typename == 'SpotColor') return isMagenta(c.spot.color);
    return false;
  }
  var cutColor;
  if (isCMYK) { cutColor = new CMYKColor(); cutColor.cyan = 0; cutColor.magenta = 100; cutColor.yellow = 0; cutColor.black = 0; }
  else { cutColor = new RGBColor(); cutColor.red = 236; cutColor.green = 0; cutColor.blue = 140; }
  var regColor = null, regNames = ['[Registration]', '[レジストレーション]'];
  for (var r = 0; r < regNames.length && !regColor; r++) { try { regColor = doc.swatches.getByName(regNames[r]).color; } catch (e) {} }
  if (!regColor) { for (var s = 0; s < doc.swatches.length; s++) { var sc = doc.swatches[s].color; if (sc.typename == 'SpotColor' && sc.spot.colorType == ColorModel.REGISTRATION) { regColor = sc; break; } } }

  var names = {}, i; for (i = 0; i < doc.layers.length; i++) names[doc.layers[i].name] = true;
  var already = names['デザイン'] && names[cutName] && names['トンボ'] && doc.layers.length == 3;
  var nCut = 0, nMark = 0, nDesign = 0, nDel = 0;
  if (!already) {
    var old = []; for (i = 0; i < doc.layers.length; i++) old.push(doc.layers[i]);
    var Ldesign = doc.layers.add(); Ldesign.name = 'デザイン';
    var Lcut = doc.layers.add();    Lcut.name = cutName;
    var Lmark = doc.layers.add();   Lmark.name = 'トンボ';
    for (var L = 0; L < old.length; L++) {
      var items = []; for (i = 0; i < old[L].pageItems.length; i++) items.push(old[L].pageItems[i]);
      for (i = 0; i < items.length; i++) {
        var it = items[i], probe = it;
        if (it.typename == 'CompoundPathItem' && it.pathItems.length) probe = it.pathItems[0];
        if (probe.typename == 'PathItem') {
          var subs = (it.typename == 'CompoundPathItem') ? it.pathItems : [it];
          if (probe.stroked && isMagenta(probe.strokeColor)) {
            for (var k = 0; k < subs.length; k++) { subs[k].strokeColor = cutColor; subs[k].strokeWidth = cutW; subs[k].filled = false; subs[k].closed = true; }
            it.move(Lcut, ElementPlacement.PLACEATEND); nCut += subs.length; }
          else if (probe.stroked && !probe.filled) {
            for (var k2 = 0; k2 < subs.length; k2++) { if (regColor) subs[k2].strokeColor = regColor; }
            it.move(Lmark, ElementPlacement.PLACEATEND); nMark += subs.length; }
          else if (!probe.filled && !probe.stroked && !probe.clipping) { it.remove(); nDel++; }
          else { it.move(Ldesign, ElementPlacement.PLACEATEND); nDesign++; }
        } else { it.move(Ldesign, ElementPlacement.PLACEATEND); nDesign++; }
      }
      if (old[L].pageItems.length == 0) old[L].remove();
    }
  } else {
    // 既に3層あるときは、切り線の色と幅だけそろえる
    var Lc = doc.layers.getByName(cutName);
    for (i = 0; i < Lc.pathItems.length; i++) { Lc.pathItems[i].strokeColor = cutColor; Lc.pathItems[i].strokeWidth = cutW; Lc.pathItems[i].filled = false; nCut++; }
  }
  var o = new IllustratorSaveOptions();
  o.compatibility = Compatibility.ILLUSTRATOR17; o.pdfCompatible = true; o.embedICCProfile = true;
  o.compressed = true; o.embedLinkedFiles = true;
  doc.saveAs(dst, o);
  var out = []; for (i = 0; i < doc.layers.length; i++) out.push(doc.layers[i].name + '(' + doc.layers[i].pageItems.length + ')');
  var ab = doc.artboards[0].artboardRect;
  var info = 'layers=' + out.join('/') + ';cut=' + nCut + ';marks=' + nMark + ';design=' + nDesign + ';removed=' + nDel +
             ';registration=' + (regColor ? 'yes' : 'no') + ';colorSpace=' + (isCMYK ? 'CMYK' : 'RGB') +
             ';artboard_mm=' + Math.round((ab[2]-ab[0])/72*25.4*10)/10 + 'x' + Math.round((ab[1]-ab[3])/72*25.4*10)/10;
  doc.close(SaveOptions.DONOTSAVECHANGES);
  return info;
})();
