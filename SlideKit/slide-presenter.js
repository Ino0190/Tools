/**
 * SlideKit 発表者ビュー（独立ファイル）
 *
 * 目的:
 *  - 手元ウィンドウ（本窓）は編集・閲覧のまま、別ウィンドウに「発表者ビュー」を開く。
 *    発表者ビューには 現在のスライド（縮小）・次のスライド（縮小）・現在のノート・
 *    開始からの経過時間と現在時刻・スライド番号/総数 を出す。
 *  - 本窓でページを進めると別窓も追従する（プレゼン再生 slide-present.js とは別物。
 *    あちらは「投影画面」、こちらは発表者の手元コンソール）。
 *
 * 使い方:
 *  <script src="../SlideKit/slide-edit.js"></script>        ← 自動で読み込まれる
 *  <script src="../SlideKit/slide-presenter.js"></script>   ← 明示してもよい（二重読込は防止）
 *  → 本窓の左上（ツールバー内）に「🧑‍🏫 発表者ビュー」ボタンが出る。
 *  → クリックで別ウィンドウが発表者ビューで開く（同じ file:// ・?presenter=1&hideUI=1）。
 *  → 本窓で ← / → / Space / PageUp / PageDown でページを送ると、別窓が追従する。
 *
 * 追従の仕組み（file:// で動く方）:
 *  - 既定は BroadcastChannel('slidekit_presenter_' + location.pathname)。
 *    file:// のページはどれも origin が "file://" なので、同じHTMLを開いた2窓は同じ
 *    チャンネルを共有できる（slide-present.js のプレゼン同期と同じ原理）。
 *  - 保険として localStorage の storage イベントにも同じ番号を書く（BroadcastChannel が
 *    効かない環境でも追従できるように。二重配達は番号が同じなので無害）。
 *
 * PPTX 変換・保存への影響:
 *  - 本窓で足す要素（ボタン等）は class="seui" を付ける（💾保存・PPTX変換の対象外）。
 *  - 発表者ビューの中身は別ウィンドウ上に実行時に作るだけで、HTMLファイルには一切書かない。
 *    よって html_to_pptx.py / run_check.py の変換対象には入らない。
 */
(function(){
  'use strict';
  if (window.__skPresenterLoaded) return;
  window.__skPresenterLoaded = true;

  var params = new URLSearchParams(location.search);
  var isPresenter = params.get('presenter') === '1';

  // 本窓・別窓で同じチャンネル名（location.pathname が同一＝同じHTML）
  var CH = 'slidekit_presenter_' + location.pathname;
  var LS = 'slidekit_pv_' + location.pathname;
  var bus = null;
  try { bus = new BroadcastChannel(CH); } catch (_) { bus = null; }

  function post(msg){
    try { if (bus) bus.postMessage(msg); } catch (_){}
    // localStorage フォールバック（値を必ず変えるため t を入れる＝同じ番号でも storage が飛ぶ）
    try { localStorage.setItem(LS, JSON.stringify({ msg: msg, t: Date.now() })); } catch (_){}
  }
  function onBus(handler){
    if (bus) bus.onmessage = function(e){ handler(e.data); };
    window.addEventListener('storage', function(e){
      if (e.key !== LS || !e.newValue) return;
      try { var d = JSON.parse(e.newValue); if (d && d.msg) handler(d.msg); } catch (_){}
    });
  }

  if (isPresenter) initConsole(); else initRemote();

  // ============================================================
  // 発表者ビュー（別ウィンドウ側）
  // ============================================================
  function initConsole(){
    if (document.readyState === 'loading')
      document.addEventListener('DOMContentLoaded', buildConsole);
    else buildConsole();
  }

  function buildConsole(){
    var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
    if (!slides.length) return;

    injectDesignKit();
    injectConsoleStyle();
    document.body.classList.add('_pv_active');

    var idx = parseInt(params.get('idx') || '0', 10);
    if (isNaN(idx) || idx < 0) idx = 0;
    if (idx >= slides.length) idx = slides.length - 1;

    var root = document.createElement('div');
    root.id = '_pv_root'; root.className = 'seui';
    root.innerHTML =
      '<div id="_pv_head">' +
        '<div id="_pv_counter" class="_pv_badge">- / -</div>' +
        '<div id="_pv_timer" class="_pv_time" title="開始からの経過">00:00:00</div>' +
        '<div id="_pv_pace" class="_pv_time" title="ここまでの目安（文字数から。緑=余裕・赤=遅れ）">目安 --:--</div>' +
        '<div id="_pv_clock" class="_pv_time" title="現在時刻">--:--</div>' +
      '</div>' +
      '<div id="_pv_body">' +
        '<div id="_pv_curwrap" class="_pv_col">' +
          '<div class="_pv_label">現在</div>' +
          '<div id="_pv_cur" class="_pv_stage"></div>' +
        '</div>' +
        '<div id="_pv_side" class="_pv_col">' +
          '<div class="_pv_label">次</div>' +
          '<div id="_pv_next" class="_pv_stage _pv_small"></div>' +
          '<div class="_pv_label">ノート</div>' +
          '<div id="_pv_notes"></div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(root);

    var elCur = root.querySelector('#_pv_cur');
    var elNext = root.querySelector('#_pv_next');
    var elNotes = root.querySelector('#_pv_notes');
    var elCounter = root.querySelector('#_pv_counter');

    function placeScaled(stage, slideIndex){
      stage.innerHTML = '';
      var s = slides[slideIndex];
      if (!s) { stage.removeAttribute('data-index'); return; }
      var box = stage.getBoundingClientRect();
      var scale = Math.min(box.width / 1280, box.height / 720);
      if (!isFinite(scale) || scale <= 0) scale = box.width / 1280 || 0.25;
      var clone = s.cloneNode(true);
      // 実行時UIの混入を防ぐ（スライド本体は持たないが念のため）
      clone.querySelectorAll && clone.querySelectorAll('.seui,.aws-overlay').forEach(function(x){ x.remove(); });
      clone.style.position = 'absolute';
      clone.style.left = '0'; clone.style.top = '0'; clone.style.margin = '0';
      clone.style.transform = 'scale(' + scale + ')';
      clone.style.transformOrigin = 'top left';
      clone.style.boxShadow = 'none';
      stage.appendChild(clone);
      stage.setAttribute('data-index', slideIndex);
    }

    // 発表時間の目安（SlideKit/deck_timing.py と同じ決まり: ノート＝全部話す／本文＝6割／300字/分／下限8秒／図だけ20秒）
    var CPM = 300, BODY_RATIO = 0.6, MIN_SEC = 8, FIG_SEC = 20, FIG_CHARS = 20;
    function countChars(t){
      t = (t || '').replace(/\s+/g, ' ').trim();
      var words = (t.match(/[A-Za-z0-9][A-Za-z0-9\-\.%]*/g) || []).length;
      var rest = t.replace(/[A-Za-z0-9][A-Za-z0-9\-\.%]*/g, '').replace(/[\s\u0000-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007f\u3000-\u303f\uff00-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65]/g, '');
      return rest.length + 2 * words;
    }
    function estimateSec(s){
      if (!s) return 0;
      var notes = (s.getAttribute('data-notes') || '').replace(/\\n/g, '\n').trim();
      var sec;
      if (notes) sec = countChars(notes) / CPM * 60;
      else {
        var body = '';
        s.querySelectorAll('.tb, td, th').forEach(function(el){ body += ' ' + (el.textContent || ''); });
        var bc = countChars(body);
        sec = bc < FIG_CHARS ? FIG_SEC : bc * BODY_RATIO / CPM * 60;
      }
      return Math.max(MIN_SEC, Math.round(sec));
    }
    var estSec = slides.map(estimateSec);
    var cumSec = []; estSec.reduce(function(a, b, k){ cumSec[k] = a + b; return a + b; }, 0);
    var totalSec = cumSec.length ? cumSec[cumSec.length - 1] : 0;
    function mmss(s){ s = Math.max(0, Math.round(s)); return pad(Math.floor(s / 60)) + ':' + pad(s % 60); }

    function notesOf(i){
      var s = slides[i];
      var v = s ? (s.getAttribute('data-notes') || '').replace(/\\n/g, '\n').trim() : '';
      return v;
    }

    function show(i, notify){
      if (i < 0) i = 0;
      if (i >= slides.length) i = slides.length - 1;
      idx = i;
      placeScaled(elCur, i);
      placeScaled(elNext, i + 1 < slides.length ? i + 1 : -1);
      var nx = notesOf(i);
      elNotes.textContent = nx || '（このページのノートはありません）';
      elNotes.classList.toggle('_pv_empty', !nx);
      elCounter.textContent = (i + 1) + ' / ' + slides.length;
      elCounter.title = 'このページの目安 ' + estSec[i] + '秒 ／ 全体 ' + mmss(totalSec);
      updatePace();
      elCur.setAttribute('data-cur-index', i);
      if (notify !== false) post({ type: 'pv:slide', index: i, total: slides.length, from: 'presenter' });
    }

    // 時計と経過時間
    var startedAt = Date.now();
    function pad(n){ return (n < 10 ? '0' : '') + n; }
    // 目安: 「いまのページを終えた時点までの累計目安」と経過を比べる。経過が目安を 10% 超えたら赤、まだ目安の半分以下なら緑
    function updatePace(){
      var el = root.querySelector('#_pv_pace'); if (!el) return;
      var target = cumSec[idx] || 0, s = (Date.now() - startedAt) / 1000;
      el.textContent = '目安 ' + mmss(target) + ' / ' + mmss(totalSec) + '（この頁 ' + (estSec[idx] || 0) + '秒）';
      el.classList.toggle('_pv_late', s > target * 1.1 + 15);
      el.classList.toggle('_pv_ahead', s < target * 0.5);
    }
    function tick(){
      var now = new Date();
      root.querySelector('#_pv_clock').textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
      var s = Math.floor((Date.now() - startedAt) / 1000);
      root.querySelector('#_pv_timer').textContent =
        pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60);
      updatePace();
    }
    tick(); setInterval(tick, 1000);

    window.__pvTiming = function(){ return { est: estSec.slice(), cum: cumSec.slice(), total: totalSec, idx: idx }; }; // 検査用（presenter-check / kits-mcp）
    // 本窓からの追従
    onBus(function(d){
      if (!d || d.from === 'presenter') return;
      if (d.type === 'pv:slide') show(d.index, false);
      if (d.type === 'pv:hello') post({ type: 'pv:slide', index: idx, total: slides.length, from: 'presenter' });
      if (d.type === 'pv:close') { try { window.close(); } catch (_){} }
    });

    // 別窓側でもページ送りできる（本窓も追従する）
    document.addEventListener('keydown', function(e){
      switch (e.key) {
        case 'ArrowRight': case ' ': case 'PageDown': case 'n': case 'N':
          e.preventDefault(); show(idx + 1); break;
        case 'ArrowLeft': case 'PageUp': case 'Backspace': case 'p': case 'P':
          e.preventDefault(); show(idx - 1); break;
        case 'Home': e.preventDefault(); show(0); break;
        case 'End': e.preventDefault(); show(slides.length - 1); break;
        case 'Escape': try { window.close(); } catch (_){} break;
      }
    });
    window.addEventListener('resize', function(){ placeScaled(elCur, idx); placeScaled(elNext, idx + 1 < slides.length ? idx + 1 : -1); });

    // テスト・外部用フック
    window.__pvIndex = function(){ return idx; };
    window.__pvGoto = function(i){ show(i); };
    window.__pvNext = function(){ show(idx + 1); };

    // 初期表示（少し遅らせてレイアウト確定後にスケール）し、本窓に現在位置を尋ねる
    show(idx, false);
    setTimeout(function(){ placeScaled(elCur, idx); placeScaled(elNext, idx + 1 < slides.length ? idx + 1 : -1); }, 60);
    setTimeout(function(){ post({ type: 'pv:hello', from: 'presenter' }); }, 120);

    window.addEventListener('beforeunload', function(){ post({ type: 'pv:close', from: 'presenter' }); });
  }

  function injectDesignKit(){
    // 既に読み込み済みなら何もしない
    if (document.querySelector('link[href*="design-kit.css"]')) return;
    var me = document.querySelector('script[src*="slide-presenter"]');
    var dir = me ? (me.getAttribute('src') || '').replace(/slide-presenter\.js.*$/, '') : '';
    var link = document.createElement('link');
    link.rel = 'stylesheet'; link.className = 'seui';
    link.href = dir + '../DesignKit/design-kit.css';
    link.onerror = function(){ /* 無くても var(...) のフォールバック値で見える */ };
    document.head.appendChild(link);
  }

  function injectConsoleStyle(){
    var s = document.createElement('style');
    s.id = '_pv_style'; s.className = 'seui';
    s.textContent = [
      'html,body._pv_active{margin:0!important;padding:0!important;height:100%!important;overflow:hidden!important;background:var(--kit-bg,#fafafa)!important}',
      // スライドの縦並び・ツールバー等、root 以外の body 直下は全部隠す
      'body._pv_active>*:not(#_pv_root):not(script):not(style):not(link){display:none!important}',
      '#_pv_root{position:fixed;inset:0;display:flex;flex-direction:column;z-index:9000;',
      '  font-family:var(--kit-font,"Yu Gothic UI",sans-serif);color:var(--kit-fg,#121212);background:var(--kit-bg,#fafafa)}',
      '#_pv_head{height:56px;flex:none;display:flex;align-items:center;justify-content:space-between;',
      '  padding:0 18px;border-bottom:1px solid var(--kit-line,#d9dee3);background:var(--kit-card,#fff)}',
      '._pv_badge{font-size:var(--kit-fs-h3,18px);font-weight:700;color:var(--kit-accent-fg,#fff);',
      '  background:var(--kit-accent,#21537f);padding:4px 14px;border-radius:var(--kit-radius,0)}',
      '._pv_time{font-variant-numeric:tabular-nums;font-size:22px;font-weight:700;color:var(--kit-fg,#121212)}',
      '#_pv_clock{color:var(--kit-sub,#5e5e5e);font-size:18px;font-weight:400}',
      '#_pv_pace{color:var(--kit-sub,#5e5e5e);font-size:16px;font-weight:400}',
      '#_pv_pace._pv_late{color:#b02a37;font-weight:700}',
      '#_pv_pace._pv_ahead{color:#2e7d32}',
      '#_pv_body{flex:1;display:flex;gap:16px;padding:16px;min-height:0}',
      '._pv_col{display:flex;flex-direction:column;min-width:0;min-height:0}',
      '#_pv_curwrap{flex:1.7}#_pv_side{flex:1}',
      '._pv_label{font-size:var(--kit-fs-label,14px);color:var(--kit-sub,#5e5e5e);font-weight:700;margin:2px 0 6px}',
      '._pv_stage{position:relative;flex:1;min-height:0;overflow:hidden;background:#000;',
      '  border:1px solid var(--kit-line,#d9dee3);border-radius:var(--kit-radius,0)}',
      '._pv_small{flex:0 0 auto;height:40%}',
      '#_pv_notes{flex:1;min-height:0;margin-top:2px;overflow-y:auto;white-space:pre-wrap;',
      '  background:var(--kit-card,#fff);border:1px solid var(--kit-line,#d9dee3);border-radius:var(--kit-radius,0);',
      '  padding:12px 14px;font-size:20px;line-height:1.7;color:var(--kit-fg,#121212)}',
      '#_pv_notes._pv_empty{color:var(--kit-sub,#5e5e5e);font-style:italic;font-size:16px}'
    ].join('\n');
    document.head.appendChild(s);
  }

  // ============================================================
  // 本窓（手元の編集/閲覧ウィンドウ）側
  // ============================================================
  function initRemote(){
    // プレゼン窓・発表者窓など hideUI の中では本窓ボタンを出さない
    if (params.get('hideUI') === '1' || params.get('hideUI') === 'true') return;
    if (document.readyState === 'loading')
      document.addEventListener('DOMContentLoaded', setupRemote);
    else setupRemote();
  }

  function setupRemote(){
    if (!document.querySelector('.slide')) return;

    var pvWin = null;
    var curIdx = nearestSlide();

    function nearestSlide(){
      var slides = document.querySelectorAll('.slide');
      var vc = window.innerHeight / 2 + window.scrollY, best = Infinity, idx = 0;
      slides.forEach(function(s, i){
        var r = s.getBoundingClientRect();
        var c = r.top + window.scrollY + r.height / 2;
        var d = Math.abs(c - vc);
        if (d < best) { best = d; idx = i; }
      });
      return idx;
    }

    // 「🧑‍🏫 発表者ビュー」ボタン（ツールバーがあれば中へ、無ければ右上 fixed）
    var btn = document.createElement('button');
    btn.id = '_pv_openbtn'; btn.className = 'seui';
    btn.textContent = '🧑‍🏫 発表者ビュー';
    btn.title = '別ウィンドウに発表者ビュー（現在・次・ノート・時計）を開く。\n本窓で ←/→/Space でページを送ると追従します。';
    function intoBar(bar){
      btn.style.cssText = 'position:sticky;top:0;z-index:2;padding:6px 10px;border:none;border-radius:4px;background:#0f766e;color:#fff;font:700 12px/1.2 -apple-system,sans-serif;cursor:pointer;text-align:center;white-space:normal;overflow-wrap:anywhere;box-shadow:0 2px 8px rgba(0,0,0,.2)';
      bar.insertBefore(btn, bar.firstChild);
    }
    var hasEditor = !!(window.SlideKit || document.querySelector('script[src*="slide-edit"]'));
    (function place(tries){
      var bar = document.getElementById('_sk_toolbar');
      if (bar) { intoBar(bar); return; }
      if (hasEditor && tries > 0) { setTimeout(function(){ place(tries - 1); }, 100); return; }
      btn.style.cssText = 'position:fixed;top:12px;right:150px;z-index:100002;padding:8px 14px;border:none;border-radius:6px;background:#0f766e;color:#fff;font:700 13px/1.2 -apple-system,sans-serif;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);white-space:nowrap';
      document.body.appendChild(btn);
      if (hasEditor && window.MutationObserver) {
        var mo = new MutationObserver(function(){
          var b = document.getElementById('_sk_toolbar');
          if (b) { mo.disconnect(); intoBar(b); }
        });
        mo.observe(document.body, { childList: true });
      }
    })(100);

    function openPresenter(){
      if (pvWin && !pvWin.closed) { try { pvWin.focus(); } catch (_){} return pvWin; }
      curIdx = nearestSlide();
      var sep = location.search ? '&' : '?';
      var url = location.pathname + location.search + sep + 'presenter=1&hideUI=1&idx=' + curIdx;
      pvWin = window.open(url, 'slideKitPresenter_' + location.pathname.replace(/\W/g, ''),
                          'width=1100,height=700,left=80,top=80');
      window.__skPresenterWin = pvWin;
      if (!pvWin) alert('発表者ビューを開けませんでした。ブラウザのポップアップブロックを解除してください。');
      else { try { pvWin.focus(); } catch (_){} }
      return pvWin;
    }
    btn.addEventListener('click', openPresenter);

    function goto(i){
      var n = document.querySelectorAll('.slide').length;
      if (i < 0) i = 0; if (i >= n) i = n - 1;
      curIdx = i;
      highlight(i);
      post({ type: 'pv:slide', index: i, total: n, from: 'remote' });
    }

    function highlight(i){
      var slides = document.querySelectorAll('.slide');
      slides.forEach(function(s){
        s.style.outline = ''; s.style.outlineOffset = '';
      });
      var s = slides[i];
      if (!s) return;
      s.style.outline = '4px solid #0f766e';
      s.style.outlineOffset = '2px';
      try { s.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_){}
    }

    onBus(function(d){
      if (!d || d.from === 'remote') return;
      if (d.type === 'pv:hello') { post({ type: 'pv:slide', index: curIdx, total: document.querySelectorAll('.slide').length, from: 'remote' }); }
      if (d.type === 'pv:slide') { curIdx = d.index; highlight(curIdx); }
      if (d.type === 'pv:close') { pvWin = null; window.__skPresenterWin = null; document.querySelectorAll('.slide').forEach(function(s){ s.style.outline=''; s.style.outlineOffset=''; }); }
    });

    // 本窓のキーでページ送り（発表者ビューが開いている時だけ）
    document.addEventListener('keydown', function(e){
      if (!pvWin || pvWin.closed) return;
      if (e.target && e.target.matches && e.target.matches('input,textarea,[contenteditable]')) return;
      if (e.key === 'PageDown') { e.preventDefault(); goto(curIdx + 1); }
      else if (e.key === 'PageUp') { e.preventDefault(); goto(curIdx - 1); }
      else if (e.key === ' ') { e.preventDefault(); goto(e.shiftKey ? curIdx - 1 : curIdx + 1); }
      else if (e.key === 'ArrowRight') { if (e.defaultPrevented) return; e.preventDefault(); goto(curIdx + 1); }
      else if (e.key === 'ArrowLeft') { if (e.defaultPrevented) return; e.preventDefault(); goto(curIdx - 1); }
    });

    // 本窓を閉じたら別窓にも通知
    window.addEventListener('beforeunload', function(){ post({ type: 'pv:close', from: 'remote' }); });

    // テスト・外部用フック
    window.__skPresenterOpen = openPresenter;
    window.__skPresenterGoto = goto;
    window.__skPresenterNext = function(){ goto(curIdx + 1); };
    window.__skPresenterPrev = function(){ goto(curIdx - 1); };
    window.__skPresenterCur = function(){ return curIdx; };
  }
})();
