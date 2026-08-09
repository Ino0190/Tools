// SlideKit Layout Diagnostic Tool
// 検出: ①.rect同士の重なり ②.rect/.tb/imgの中身あふれ ③.slide境界はみ出し
//       ④画像アス比ずれ ⑤絶対配置子divのはみ出し ⑥data-*↔styleの不整合（PPTX変換ズレの元）
// 使い方: HTMLの</body>直前で <script src="SlideKit/check-layout.js"></script> を読み込む
// → 画面右上に「⚠️診断」ボタンが出る。クリックで全スライドを検査。
// Chrome headlessから呼ぶ場合: window.__slideKitCheck() で結果のJSONが返る

(function(){
  'use strict';
  // キャンバス定数は slidekit-defs.js (canvas) が正本 (v2 / Requirements 1.2, 2.5)。
  // 診断はボタンクリック時に走る = slide-edit.js が defs を読み終えた後なので、
  // checkAll 実行時に window.SLIDEKIT_DEFS から取り込む。未ロード時は v1 と同値にフォールバック。
  let SLIDE_W = 1280, SLIDE_H = 720;
  function _syncCanvasFromDefs(){
    const c = window.SLIDEKIT_DEFS && window.SLIDEKIT_DEFS.canvas;
    if (c && c.wPx && c.hPx){ SLIDE_W = c.wPx; SLIDE_H = c.hPx; }
  }
  const N = v => parseFloat(v||'0');
  const A = (el,k) => el.getAttribute(k);

  // 矩形重なり判定（スライド内座標で）
  function rectsOverlap(a, b){
    return !(a.x+a.w <= b.x || b.x+b.w <= a.x || a.y+a.h <= b.y || b.y+b.h <= a.y);
  }

  // 各.slideについて要素を集めてチェック
  function checkAll(){
    _syncCanvasFromDefs(); // 実行時に defs のキャンバス定数を取り込む (未ロード時は v1 同値)
    const slides = Array.from(document.querySelectorAll('.slide'));
    const issues = []; // {slideIdx, kind, el, msg, rect}
    slides.forEach((slide, sIdx) => {
      const slideRect = slide.getBoundingClientRect();
      // この .slide の直接の子要素のうち、座標を持つもの
      const rects = Array.from(slide.querySelectorAll(':scope > .rect[data-x]')).map(el => ({
        el, x:N(A(el,'data-x')), y:N(A(el,'data-y')),
        w:N(A(el,'data-w')), h:N(A(el,'data-h'))
      }));

      // ① .rect 同士の重なり（同じスライド内、各ペア）
      for(let i=0;i<rects.length;i++){
        for(let j=i+1;j<rects.length;j++){
          if(rectsOverlap(rects[i], rects[j])){
            issues.push({
              slideIdx: sIdx+1, kind:'overlap',
              elA: rects[i].el, elB: rects[j].el,
              msg: `rect(${rects[i].x},${rects[i].y} ${rects[i].w}×${rects[i].h}) と rect(${rects[j].x},${rects[j].y} ${rects[j].w}×${rects[j].h}) が重なっている`
            });
          }
        }
      }

      // ② 中身あふれ＋③境界はみ出し
      const allBoxes = Array.from(slide.querySelectorAll('[data-x]'));
      allBoxes.forEach(el => {
        const x = N(A(el,'data-x')), y = N(A(el,'data-y'));
        const w = N(A(el,'data-w')), h = N(A(el,'data-h'));
        // ③ .slide 境界はみ出し（data属性ベース）
        if(w > 0){
          if(x < 0 || x+w > SLIDE_W){
            issues.push({
              slideIdx: sIdx+1, kind:'overflow-slide-x', el,
              msg: `要素が横方向にスライド境界(0..${SLIDE_W})を超える x=${x} w=${w}`
            });
          }
        }
        if(h > 0){
          if(y < 0 || y+h > SLIDE_H){
            issues.push({
              slideIdx: sIdx+1, kind:'overflow-slide-y', el,
              msg: `要素が縦方向にスライド境界(0..${SLIDE_H})を超える y=${y} h=${h}`
            });
          }
        }
        // ② 中身あふれ（実描画ベース・scrollHeight/scrollWidth）
        // .tb で h 指定があるもの、.rect で h 指定があるもの、img の親
        const isTb = el.classList && el.classList.contains('tb');
        const isRect = el.classList && el.classList.contains('rect');
        if((isTb || isRect) && h > 0){
          // 実際の中身が枠より大きいか
          const sh = el.scrollHeight, ch = el.clientHeight;
          if(sh > ch + 1){
            issues.push({
              slideIdx: sIdx+1, kind:'text-overflow', el,
              msg: `中身が枠の高さを超える (scrollHeight ${sh}px > clientHeight ${ch}px) ${el.tagName.toLowerCase()}.${el.className.split(' ')[0]||''} 推奨h≧${sh}`
            });
          }
        }
        if((isTb || isRect) && w > 0){
          const sw = el.scrollWidth, cw = el.clientWidth;
          if(sw > cw + 1){
            issues.push({
              slideIdx: sIdx+1, kind:'text-overflow-x', el,
              msg: `中身が枠の幅を超える (scrollWidth ${sw}px > clientWidth ${cw}px)`
            });
          }
        }
      });

      // ④ 画像アス比チェック（PPTX変換時の歪み防止）
      const imgs = Array.from(slide.querySelectorAll('img'));
      imgs.forEach(img => {
        if(!img.naturalWidth || !img.naturalHeight) return; // 未読み込み or データURL
        const parent = img.parentElement;
        if(!parent || parent === slide) return;
        const cw = parent.clientWidth, ch = parent.clientHeight;
        if(cw < 1 || ch < 1) return;
        const imgAspect = img.naturalWidth / img.naturalHeight;
        const containerAspect = cw / ch;
        const diff = Math.abs(imgAspect - containerAspect) / imgAspect;
        if(diff > 0.05){ // 5%超ずれ
          // object-fit:cover/contain ならトリミング/アス比保持想定OK＝警告でなく情報のみ
          const imgStyle = (img.getAttribute('style')||'').replace(/\s/g,'');
          const isCover = imgStyle.indexOf('object-fit:cover') >= 0;
          const isContain = imgStyle.indexOf('object-fit:contain') >= 0;
          if(isCover || isContain) return; // トリミング/内側余白で対応するので無視
          // 推奨：幅維持で高さ調整／高さ維持で幅調整
          const recH = Math.round(cw / imgAspect);
          const recW = Math.round(ch * imgAspect);
          const fname = (img.src||'').split('/').pop().split('?')[0];
          issues.push({
            slideIdx: sIdx+1, kind:'image-aspect', el: parent,
            msg: `画像アス比ずれ ${fname}: 実画像 ${img.naturalWidth}×${img.naturalHeight} (${imgAspect.toFixed(2)}:1) vs コンテナ ${cw}×${ch} (${containerAspect.toFixed(2)}:1)・ずれ ${(diff*100).toFixed(0)}% ／ 推奨コンテナ：${cw}×${recH} または ${recW}×${ch} ／ または img に object-fit:cover を付けてトリミング表示`
          });
        }
      });

      // ⑥ data-*↔style 同期チェック（PPTX変換では data-* が正本・styleは表示用）
      //    両者がズレていると「ブラウザでは正しいのにPPTXでズレる」が起きる。
      // data属性→style プロパティの対応は slidekit-defs.js (styleSyncProps) が正本。
      // 正規表現は v1 と同一形 (プロパティ名だけ defs から差し込む)。未ロード時は v1 同値にフォールバック。
      const _ssp = (window.SLIDEKIT_DEFS && window.SLIDEKIT_DEFS.styleSyncProps)
        || { 'data-x': 'left', 'data-y': 'top', 'data-w': 'width', 'data-h': 'height' };
      const SYNC_MAP = Object.keys(_ssp).map(function(dAttr){
        return [dAttr, new RegExp('(?:^|;)\\s*' + _ssp[dAttr] + '\\s*:\\s*(-?\\d+(?:\\.\\d+)?)\\s*px')];
      });
      const syncTargets = Array.from(slide.querySelectorAll('[data-x]'));
      syncTargets.forEach((el, eIdx) => {
        const style = (el.getAttribute('style') || '');
        SYNC_MAP.forEach(([dAttr, sRe]) => {
          if(!el.hasAttribute(dAttr)) return;
          const dVal = N(A(el, dAttr));
          const m = style.match(sRe);
          if(!m){
            // style側にプロパティが無い＝表示は効かないがPPTX変換は data-* で動く。
            // ただし width/height は要素種によっては未指定でも成立するので、
            // left/top は data-*/style両方揃っている前提で厳しく、w/h は緩めに扱う。
            if(dAttr === 'data-x' || dAttr === 'data-y'){
              const propName = {'data-x':'left','data-y':'top'}[dAttr];
              issues.push({
                slideIdx: sIdx+1, kind:'data-style-mismatch', el,
                msg: `${dAttr}=${dVal} だが style.${propName} が未指定（ブラウザ表示位置とPPTX位置がズレる）`
              });
            }
            return;
          }
          const sVal = parseFloat(m[1]);
          if(Math.abs(dVal - sVal) > 0.5){
            const propName = {'data-x':'left','data-y':'top','data-w':'width','data-h':'height'}[dAttr];
            const short = (el.tagName.toLowerCase()) + '.' + ((el.className||'').split(' ')[0] || '');
            const preview = (el.textContent || '').trim().slice(0, 20);
            issues.push({
              slideIdx: sIdx+1, kind:'data-style-mismatch', el,
              msg: `${short}#${eIdx} ${dAttr}=${dVal} vs style.${propName}=${sVal}${preview ? '（"'+preview+'"）' : ''}`
            });
          }
        });
      });

      // ⑤ data-x のない絶対配置子div(画像コンテナ等)もスライド境界チェック
      const directChildren = Array.from(slide.children);
      directChildren.forEach(el => {
        if(el.classList && (el.classList.contains('tb') || el.classList.contains('rect'))) return;
        if(el.hasAttribute && el.hasAttribute('data-x')) return; // 既に上でチェック済み
        const style = el.getAttribute && el.getAttribute('style') || '';
        const lm = style.match(/left\s*:\s*(\d+)px/);
        const tm = style.match(/top\s*:\s*(\d+)px/);
        const wm = style.match(/width\s*:\s*(\d+)px/);
        const hm = style.match(/height\s*:\s*(\d+)px/);
        if(lm && tm && wm && hm){
          const x = parseInt(lm[1]), y = parseInt(tm[1]);
          const w = parseInt(wm[1]), h = parseInt(hm[1]);
          if(x < 0 || x+w > SLIDE_W){
            issues.push({ slideIdx: sIdx+1, kind:'overflow-slide-x', el,
              msg: `画像/divが横方向にスライド境界(0..${SLIDE_W})を超える x=${x} w=${w}` });
          }
          if(y < 0 || y+h > SLIDE_H){
            issues.push({ slideIdx: sIdx+1, kind:'overflow-slide-y', el,
              msg: `画像/divが縦方向にスライド境界(0..${SLIDE_H})を超える y=${y} h=${h}（スライド外にはみ出る）` });
          }
        }
      });
    });
    return issues;
  }

  // 問題箇所のハイライト
  let highlighted = [];
  function clearHighlights(){
    highlighted.forEach(el => {
      if(el && el.style){
        el.style.outline = '';
        el.style.outlineOffset = '';
      }
    });
    highlighted = [];
    const labels = document.querySelectorAll('.__sk_check_label');
    labels.forEach(l => l.remove());
  }
  function highlight(el, color, label){
    if(!el || !el.style) return;
    el.style.outline = '3px dashed ' + color;
    el.style.outlineOffset = '-3px';
    highlighted.push(el);
    if(label){
      const tag = document.createElement('div');
      tag.className = '__sk_check_label';
      tag.textContent = label;
      tag.style.cssText = 'position:absolute;background:'+color+';color:#fff;font-size:12px;font-weight:700;padding:2px 6px;z-index:99998;pointer-events:none;font-family:sans-serif';
      const r = el.getBoundingClientRect();
      tag.style.left = (window.scrollX + r.left) + 'px';
      tag.style.top = (window.scrollY + r.top - 18) + 'px';
      document.body.appendChild(tag);
    }
  }

  // 結果パネル
  let panel = null;
  function showPanel(issues){
    if(panel) panel.remove();
    panel = document.createElement('div');
    panel.className = 'seui'; // 💾保存時にHTMLへ焼き込まれないようマーク
    panel.style.cssText = 'position:fixed;top:54px;right:220px;width:380px;max-height:calc(100vh - 80px);overflow-y:auto;background:#fff;border:2px solid #d81616;border-radius:8px;padding:14px;box-shadow:0 6px 24px rgba(0,0,0,.2);z-index:100001;font-family:Meiryo,sans-serif;font-size:13px;line-height:1.5';
    let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><b style="font-size:15px;color:#d81616">⚠️ 診断結果：' + issues.length + '件</b><button id="__sk_check_close" style="background:none;border:none;font-size:18px;cursor:pointer;color:#666">✕</button></div>';
    if(issues.length === 0){
      html += '<div style="color:#1a5a32;font-weight:700">問題なし。すべてOK。</div>';
    } else {
      const byKind = {};
      issues.forEach(i => { byKind[i.kind] = (byKind[i.kind]||0)+1; });
      html += '<div style="margin-bottom:10px;color:#5e5e5e">';
      Object.keys(byKind).forEach(k => {
        const label = {
          'overlap':'rect重なり',
          'overflow-slide-x':'横はみ出し',
          'overflow-slide-y':'縦はみ出し',
          'text-overflow':'中身あふれ',
          'text-overflow-x':'横にあふれ',
          'image-aspect':'画像アス比ずれ',
          'data-style-mismatch':'data-*/style不整合'
        }[k] || k;
        html += label + ': ' + byKind[k] + '件　';
      });
      html += '</div>';
      html += '<div style="border-top:1px solid #e2e8f0;padding-top:10px">';
      issues.forEach((iss, idx) => {
        html += '<div style="margin-bottom:10px;padding:8px;background:#fff5f5;border-left:3px solid #d81616;cursor:pointer" data-idx="'+idx+'">';
        html += '<b>S'+iss.slideIdx+' / '+iss.kind+'</b><br>';
        html += '<span style="color:#333">'+iss.msg+'</span>';
        html += '</div>';
      });
      html += '</div>';
    }
    panel.innerHTML = html;
    document.body.appendChild(panel);
    document.getElementById('__sk_check_close').onclick = () => {
      panel.remove(); panel = null;
      clearHighlights();
    };
    // クリックで該当スライドへスクロール
    panel.querySelectorAll('[data-idx]').forEach(div => {
      div.onclick = () => {
        const idx = parseInt(div.dataset.idx, 10);
        const iss = issues[idx];
        const slides = document.querySelectorAll('.slide');
        const s = slides[iss.slideIdx-1];
        if(s) s.scrollIntoView({behavior:'smooth', block:'center'});
      };
    });
  }

  // 診断実行（ボタンクリック or プログラム呼び出し）
  function runCheck(){
    clearHighlights();
    const issues = checkAll();
    issues.forEach(iss => {
      if(iss.kind === 'overlap'){
        highlight(iss.elA, '#d81616', '⚠️重なり S'+iss.slideIdx);
        highlight(iss.elB, '#d81616', '⚠️重なり S'+iss.slideIdx);
      } else if(iss.kind === 'text-overflow' || iss.kind === 'text-overflow-x'){
        highlight(iss.el, '#e8821a', '⚠️あふれ S'+iss.slideIdx);
      } else if(iss.kind === 'image-aspect'){
        highlight(iss.el, '#0066cc', '⚠️画像アス比 S'+iss.slideIdx);
      } else if(iss.kind === 'data-style-mismatch'){
        highlight(iss.el, '#7a3fa0', '⚠️data/style不一致 S'+iss.slideIdx);
      } else {
        highlight(iss.el, '#b01212', '⚠️はみ出し S'+iss.slideIdx);
      }
    });
    showPanel(issues);
    return issues;
  }

  // ボタン作成
  // SlideKit本体ツールバー(#_sk_toolbar)があればその中に追加、無ければ左下にfixed配置
  // ツールバーがまだ無い場合は少し待ってリトライ（読み込み順対策）
  function createButton(retry){
    if(document.getElementById('__sk_check_btn')) return;
    const _skBar = document.getElementById('_sk_toolbar');
    if (!_skBar && (retry === undefined ? (retry = 3) : retry) > 0) {
      setTimeout(function(){ createButton(retry - 1); }, 200);
      return;
    }
    const btn = document.createElement('button');
    btn.id = '__sk_check_btn';
    btn.textContent = '⚠️ 診断';
    btn.title = 'レイアウト崩れ診断（重なり・はみ出し・文字あふれ・画像歪み等、PPTX変換で崩れる箇所を検出）';
    if (_skBar) {
      // ツールバー内: 他のボタンと同じ見た目（グレー地・白文字）で下部に追加
      btn.className = 'seui';
      btn.style.cssText = 'padding:5px 10px;border:none;border-radius:4px;background:rgba(74,74,74,.95);color:#fff;font-size:12px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2);text-align:center;white-space:nowrap';
      _skBar.appendChild(btn);
    } else {
      // fallback: 左下fixed（SlideKit本体が無いHTML用・右下は編集パネルと被るので左下に変更）
      btn.className = 'seui'; // 💾保存時にHTMLへ焼き込まれないようマーク
      btn.style.cssText = 'position:fixed;bottom:16px;left:16px;z-index:100000;padding:6px 12px;background:#fff;border:2px solid #d81616;color:#d81616;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.1);font-family:Meiryo,sans-serif';
      document.body.appendChild(btn);
    }
    btn.onclick = runCheck;
  }

  // 公開API（headlessから呼ぶ用）
  window.__slideKitCheck = function(){
    return checkAll().map(iss => ({
      slideIdx: iss.slideIdx,
      kind: iss.kind,
      msg: iss.msg
    }));
  };

  if(document.readyState === 'loading'){
    // createButtonを直接渡すとEventオブジェクトがretry引数に入りリトライが効かなくなるためラップ
    document.addEventListener('DOMContentLoaded', function(){ createButton(); });
  } else {
    createButton();
  }
})();
