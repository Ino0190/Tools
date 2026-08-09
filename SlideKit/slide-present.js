/**
 * SlideKit プレゼン再生モジュール (独立ファイル)
 *
 * 目的:
 *  - 手元ウィンドウは SlideKit 編集モードのまま、別ウィンドウでフルスクリーン
 *    のスライドショーを開いて Zoom 等の画面共有で見せる用途に使う。
 *  - Zoom 画面共有時、そのプレゼンウィンドウだけを共有すれば、ブラウザの
 *    アドレスバー・SlideKit ツールバー・他のアプリは相手に見えない。
 *
 * 使い方:
 *  <script src="../SlideKit/slide-edit.js"></script>
 *  <script src="../SlideKit/slide-present.js"></script>
 *  → 手元ウィンドウの左上に「📺 プレゼン再生」ボタンが出る。
 *  → クリックで別ウィンドウがプレゼンモードで開く (`?present=1&hideUI=1`)。
 *  → 手元 ↔ プレゼン間で BroadcastChannel でスライド送り同期。
 *
 * URL パラメータ:
 *  ?present=1        → このウィンドウがプレゼン (受信) モード
 *  ?hideUI=1         → SlideKit の編集UIを抑止 (slide-edit.js が early-return)
 *  ?idx=N            → プレゼン起動時の初期スライド番号 (0 起点)
 *
 * ナビゲーション (プレゼン側):
 *  → / Space / PageDown / N   次
 *  ← / PageUp / Backspace / P 前
 *  Home / End                 最初 / 最後
 *  F                          フルスクリーン切替
 *  Esc                        フルスクリーン解除 or ウィンドウ閉じ
 *  マウスホイール             前/次 (300ms cooldown)
 */
(function(){
  'use strict';

  var params = new URLSearchParams(location.search);
  var isPresent = params.get('present') === '1';
  // セッションID: 同じデッキを複数開いた時のチャンネル混線を防ぐ (Review 2-3)
  // - present 側: URL の session パラメータを使う
  // - remote 側: 未生成 (openPresentation 時に生成し URL に付ける)
  //              ページ内で複数回プレゼン開くケースは常に同じチャンネル (単一 remote)
  var SESSION_ID = params.get('session') ||
    (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : String(Date.now())+'-'+Math.random().toString(36).slice(2));
  var CHANNEL_NAME = 'slidekit_present_' + location.pathname + '_' + SESSION_ID;
  var bus;
  try { bus = new BroadcastChannel(CHANNEL_NAME); } catch(_) { return; }
  // 観客側ページ番号の表示切替 (Review 2-4)
  // <html data-present-counter="off"> または ?counter=0 で非表示
  var SHOW_COUNTER = !(
    document.documentElement.getAttribute('data-present-counter') === 'off' ||
    params.get('counter') === '0'
  );

  if (isPresent) {
    initPresentMode();
  } else {
    initRemoteMode();
  }

  // ============================================================
  // プレゼンモード (別ウィンドウ側)
  // ============================================================
  function initPresentMode(){
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', setupPresent);
    } else {
      setupPresent();
    }
  }

  function setupPresent(){
    var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
    if (!slides.length) return;

    // 初期スライド番号 (URL の idx を優先)
    var idx = parseInt(params.get('idx') || '0', 10);
    if (isNaN(idx) || idx < 0) idx = 0;
    if (idx >= slides.length) idx = slides.length - 1;

    injectPresentStyles();

    // 全面黒背景オーバーレイ
    var ov = document.createElement('div');
    ov.id = '_sp_overlay';
    ov.className = '_sp_overlay _sp_ui';
    document.body.insertBefore(ov, document.body.firstChild);

    // ページ番号 (右下・薄グレー) — SHOW_COUNTER=false なら非表示
    var counter = document.createElement('div');
    counter.id = '_sp_counter';
    counter.className = '_sp_ui';
    counter.style.cssText = 'position:fixed;bottom:14px;right:18px;color:rgba(255,255,255,.5);font:600 13px/1 -apple-system,sans-serif;z-index:8100;user-select:none;pointer-events:none;letter-spacing:1px' + (SHOW_COUNTER ? '' : ';display:none');
    document.body.appendChild(counter);

    // レーザードット
    var laserDot = document.createElement('div');
    laserDot.id = '_sp_laser';
    laserDot.className = '_sp_ui';
    laserDot.style.cssText = 'position:fixed;width:20px;height:20px;border-radius:50%;background:rgba(255,40,40,.9);box-shadow:0 0 20px 8px rgba(255,40,40,.6);z-index:9999;pointer-events:none;display:none;transform:translate(-50%,-50%)';
    document.body.appendChild(laserDot);

    // プレゼン側キャプチャレイヤー: laser/pen 有効時にマウス操作を先取り
    var pCapture = document.createElement('div');
    pCapture.id = '_sp_pcapture';
    pCapture.className = '_sp_ui';
    pCapture.style.cssText = 'position:fixed;inset:0;z-index:9500;display:none;cursor:crosshair;background:transparent';
    document.body.appendChild(pCapture);

    // プレゼン側の tool state (remote から broadcast されて更新される)
    var pLaser = false, pPen = false, pPenDrawing = false;

    function updatePCapture(){
      pCapture.style.display = (pLaser || pPen) ? 'block' : 'none';
    }

    // プレゼン側で mouse 座標 → 現在スライドに対する xPct/yPct を計算
    function presentCoordFromEvent(e){
      var r = currentSlideRect();
      if (!r || !r.width || !r.height) return null;
      var xPct = (e.clientX - r.left) / r.width;
      var yPct = (e.clientY - r.top) / r.height;
      // 範囲外(スライド外)でも送るとリモート側が困るのでクランプ or 拒否
      if (xPct < 0 || xPct > 1 || yPct < 0 || yPct > 1) return null;
      return { xPct: xPct, yPct: yPct, slideIndex: idx };
    }

    pCapture.addEventListener('mousemove', function(e){
      var pt = presentCoordFromEvent(e);
      if (!pt) {
        if (pLaser) {
          laserDot.style.display = 'none';
          try { bus.postMessage({type:'laser:move', visible:false, from:'present'}); } catch(_){}
        }
        return;
      }
      if (pLaser) {
        // 自分側の laserDot も同じ場所に
        var p = pctToScreen(pt.xPct, pt.yPct);
        if (p) {
          laserDot.style.left = p.x + 'px';
          laserDot.style.top = p.y + 'px';
          laserDot.style.display = 'block';
        }
        try { bus.postMessage({type:'laser:move', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, visible:true, from:'present'}); } catch(_){}
      }
      if (pPenDrawing) {
        // 自分側にストローク追加
        if (penCurrent) {
          penCurrent.points.push({xPct:pt.xPct, yPct:pt.yPct});
          redrawPen();
        }
        try { bus.postMessage({type:'pen:point', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, from:'present'}); } catch(_){}
      }
    });

    pCapture.addEventListener('mousedown', function(e){
      if (!pPen) return;
      var pt = presentCoordFromEvent(e);
      if (!pt) return;
      e.preventDefault();
      pPenDrawing = true;
      penCurrent = { color:'#ef4444', width:3, slideIndex:pt.slideIndex, points:[{xPct:pt.xPct, yPct:pt.yPct}] };
      penStrokes.push(penCurrent);
      redrawPen();
      try { bus.postMessage({type:'pen:start', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, color:'#ef4444', width:3, from:'present'}); } catch(_){}
    });
    pCapture.addEventListener('mouseup', function(){
      if (!pPenDrawing) return;
      pPenDrawing = false;
      try { bus.postMessage({type:'pen:end', from:'present'}); } catch(_){}
    });
    pCapture.addEventListener('mouseleave', function(){
      if (!pPenDrawing) return;
      pPenDrawing = false;
      try { bus.postMessage({type:'pen:end', from:'present'}); } catch(_){}
    });

    // ペン描画用 canvas
    var penCanvas = document.createElement('canvas');
    penCanvas.id = '_sp_pencanvas';
    penCanvas.className = '_sp_ui';
    penCanvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:8150;pointer-events:none';
    document.body.appendChild(penCanvas);

    // ペン線データ (スライド相対座標で保存 → スライド切替時に再描画)
    var penStrokes = []; // { color, width, slideIndex, points: [{xPct, yPct}] }
    var penCurrent = null;

    function resizeCanvas(){
      penCanvas.width = window.innerWidth;
      penCanvas.height = window.innerHeight;
      redrawPen();
    }
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    function currentSlideRect(){
      var s = slides[idx];
      if (!s) return null;
      return s.getBoundingClientRect();
    }

    function pctToScreen(xPct, yPct){
      var r = currentSlideRect();
      if (!r || !r.width || !r.height) return null;
      return { x: r.left + xPct * r.width, y: r.top + yPct * r.height };
    }

    function redrawPen(){
      var ctx = penCanvas.getContext('2d');
      ctx.clearRect(0, 0, penCanvas.width, penCanvas.height);
      penStrokes.forEach(function(s){
        if (s.slideIndex !== idx) return;
        if (!s.points || s.points.length < 2) return;
        ctx.strokeStyle = s.color || '#ef4444';
        ctx.lineWidth = s.width || 3;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        var first = pctToScreen(s.points[0].xPct, s.points[0].yPct);
        if (!first) return;
        ctx.moveTo(first.x, first.y);
        for (var i = 1; i < s.points.length; i++) {
          var p = pctToScreen(s.points[i].xPct, s.points[i].yPct);
          if (p) ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
      });
    }

    // <html data-template="aws"> or data-aws-decoration="on" の時はプレゼン側でも
    // AWSフォーマット(光彩背景・ロゴ・フッター・色リマップ)を適用する
    applyAwsFormatIfNeeded(slides);

    document.body.classList.add('_sp_active');

    function showSlide(i, notify){
      if (i < 0) i = 0;
      if (i >= slides.length) i = slides.length - 1;
      idx = i;
      slides.forEach(function(s, j){ s.classList.toggle('_sp_show', j === i); });
      scaleSlide(slides[i]);
      counter.textContent = (i + 1) + ' / ' + slides.length;
      // スライド切替時はレーザーを一旦消して、そのスライドのペン線だけ再描画
      laserDot.style.display = 'none';
      redrawPen();
      if (notify !== false) {
        try { bus.postMessage({type:'slide:change', index:i, total:slides.length, from:'present'}); } catch(_){}
      }
    }

    function scaleSlide(slide){
      if (!slide) return;
      var ww = window.innerWidth;
      var wh = window.innerHeight;
      if (!ww || !wh) return;
      // スライドは常に 1280x720 (SlideKit 標準)。装飾要素の影響を受けないよう固定値を使う
      var sw = 1280;
      var sh = 720;
      var scale = Math.min(ww / sw, wh / sh);
      slide.style.transform = 'translate(-50%,-50%) scale(' + scale + ')';
    }

    // 初期表示
    showSlide(idx, false);

    // キーボード操作
    document.addEventListener('keydown', function(e){
      if (e.target && e.target.matches && e.target.matches('input,textarea,[contenteditable]')) return;
      switch (e.key) {
        case 'ArrowRight': case ' ': case 'PageDown':
        case 'n': case 'N':
          e.preventDefault(); showSlide(idx + 1); break;
        case 'ArrowLeft': case 'PageUp': case 'Backspace':
        case 'p': case 'P':
          e.preventDefault(); showSlide(idx - 1); break;
        case 'Home':
          e.preventDefault(); showSlide(0); break;
        case 'End':
          e.preventDefault(); showSlide(slides.length - 1); break;
        case 'f': case 'F':
          e.preventDefault();
          if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen && document.documentElement.requestFullscreen();
          } else {
            document.exitFullscreen && document.exitFullscreen();
          }
          break;
        case 'Escape':
          if (document.fullscreenElement) {
            document.exitFullscreen && document.exitFullscreen();
          } else {
            try { bus.postMessage({type:'present:close', from:'present'}); } catch(_){}
            window.close();
          }
          break;
      }
    });

    // マウスホイール (300ms cooldown・トラックパッド対策)
    var wheelCd = 0;
    document.addEventListener('wheel', function(e){
      var now = Date.now();
      if (now - wheelCd < 300) return;
      if (Math.abs(e.deltaY) < 10) return;
      wheelCd = now;
      showSlide(idx + (e.deltaY > 0 ? 1 : -1));
    }, { passive: true });

    // リサイズ / フルスクリーン切替で再スケール
    function rescale(){ scaleSlide(slides[idx]); resizeCanvas(); }
    window.addEventListener('resize', rescale);
    document.addEventListener('fullscreenchange', function(){
      setTimeout(rescale, 50);
      setTimeout(rescale, 300);
    });
    // 初期化直後の遅延再計算 (viewport サイズ確定待ち)
    setTimeout(rescale, 100);
    setTimeout(rescale, 500);

    // BroadcastChannel 受信 (手元ウィンドウからの制御)
    bus.onmessage = function(e){
      var d = e.data;
      if (!d || d.from === 'present') return;
      if (d.type === 'slide:change') showSlide(d.index, false);
      if (d.type === 'slide:query') {
        try { bus.postMessage({type:'slide:reply', index:idx, total:slides.length, from:'present'}); } catch(_){}
      }
      if (d.type === 'present:close') window.close();

      // ==== remote からの tool state ====
      if (d.type === 'tool:state') {
        pLaser = !!d.laser;
        pPen = !!d.pen;
        updatePCapture();
        if (!pLaser) laserDot.style.display = 'none';
        if (!pPen) pPenDrawing = false;
      }

      // ==== remote 側の編集をリアルタイム反映 (単一スライド) ====
      if (d.type === 'slide:update' && d.html) {
        var oldSlide = slides[d.index];
        if (!oldSlide) return;
        // 表示中のスライドかどうか、その _sp_show 状態を保持
        var wasShown = oldSlide.classList.contains('_sp_show');
        // 新しいスライド element を作る
        var tmp = document.createElement('div');
        tmp.innerHTML = d.html;
        var newSlide = tmp.firstElementChild;
        if (!newSlide) return;
        // slide クラスを維持 (もし失われていれば戻す)
        if (!newSlide.classList.contains('slide')) newSlide.classList.add('slide');
        // 元 slide の親に差し替え
        oldSlide.parentNode.replaceChild(newSlide, oldSlide);
        // slides 配列も更新
        slides[d.index] = newSlide;
        // AWS フォーマットを再適用 (差し替えで overlay が消えたため)
        applyAwsFormatIfNeeded([newSlide]);
        // 表示中スライドなら _sp_show を復元 + スケールを再計算
        if (wasShown) {
          newSlide.classList.add('_sp_show');
          scaleSlide(newSlide);
        }
        // ペン線・レーザーも念のため再描画
        redrawPen();
      }

      // ==== 構造変更 (追加/削除/並べ替え) 時のフル再同期 (Review 1-3, 2-2) ====
      if (d.type === 'deck:sync' && Array.isArray(d.htmls)) {
        // 既存のスライドを全部消して、送られてきた HTML から作り直す
        var oldSlides = document.querySelectorAll('.slide');
        oldSlides.forEach(function(s){ s.remove(); });
        // 新しいスライドを body に追加
        var overlay = document.getElementById('_sp_overlay');
        d.htmls.forEach(function(html){
          var tmp = document.createElement('div');
          tmp.innerHTML = html;
          var newSlide = tmp.firstElementChild;
          if (newSlide) {
            if (!newSlide.classList.contains('slide')) newSlide.classList.add('slide');
            // オーバーレイの直後に挿入 (z-index の描画順を維持)
            if (overlay && overlay.parentNode === document.body) {
              document.body.appendChild(newSlide);
            } else {
              document.body.appendChild(newSlide);
            }
          }
        });
        // slides 配列を再構築
        slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
        // AWS フォーマット再適用
        applyAwsFormatIfNeeded(slides);
        // 現在の idx が範囲外なら調整
        if (typeof d.curIdx === 'number') idx = d.curIdx;
        if (idx >= slides.length) idx = slides.length - 1;
        if (idx < 0) idx = 0;
        // 表示中スライドを更新
        showSlide(idx, false);
        // ペン線もクリア (スライド構造変わったので slideIndex が意味を失う)
        penStrokes = [];
        redrawPen();
        // 手元側にも最新の総ページ数と現在位置を返す (レビュー指摘: slide:reply 相当)
        try {
          bus.postMessage({type:'slide:reply', index:idx, total:slides.length, from:'present'});
        } catch(_){}
        console.log('[SlideKit] deck:sync 受信: ' + slides.length + ' 枚に再構築');
      }

      // ==== レーザー ====
      if (d.type === 'laser:move') {
        if (!d.visible) {
          laserDot.style.display = 'none';
          return;
        }
        // slideIndex が違っても現在スライドの座標系で表示 (自動ナビ待ちのラグ吸収)
        var p = pctToScreen(d.xPct, d.yPct);
        if (!p) return;
        laserDot.style.left = p.x + 'px';
        laserDot.style.top = p.y + 'px';
        laserDot.style.display = 'block';
      }

      // ==== ペン ====
      if (d.type === 'pen:start') {
        penCurrent = { color: d.color || '#ef4444', width: d.width || 3, slideIndex: d.slideIndex, points: [{xPct:d.xPct, yPct:d.yPct}] };
        penStrokes.push(penCurrent);
        redrawPen();
      }
      if (d.type === 'pen:point') {
        if (!penCurrent) return;
        // slideIndex が変わったら別スライドの線として扱う
        if (d.slideIndex !== undefined && d.slideIndex !== penCurrent.slideIndex) {
          penCurrent = { color: penCurrent.color, width: penCurrent.width, slideIndex: d.slideIndex, points: [] };
          penStrokes.push(penCurrent);
        }
        penCurrent.points.push({xPct:d.xPct, yPct:d.yPct});
        redrawPen();
      }
      if (d.type === 'pen:end') {
        penCurrent = null;
      }
      if (d.type === 'pen:clear') {
        penStrokes = [];
        penCurrent = null;
        redrawPen();
      }
    };

    // 起動通知 (手元にプレゼン開始を知らせる)
    setTimeout(function(){
      try { bus.postMessage({type:'slide:change', index:idx, total:slides.length, from:'present'}); } catch(_){}
    }, 150);

    // ウィンドウ閉じ通知
    window.addEventListener('beforeunload', function(){
      try { bus.postMessage({type:'present:close', from:'present'}); } catch(_){}
    });
  }

  // AWS フォーマット適用 (v2: 描画実体は slidekit-format.js の applyAwsOverlay に一本化 / Requirements 5.1)
  // v1 はここに slide-edit.js awsOverlayCreate の複製 (約100行: isDarkSlide コピー・光彩背景・
  // リマップ CSS・コピーライト・ロゴ解決) を持っていた。v2 では削除して委譲する。
  // v2 の slide-edit.js は hideUI=1 でも defs/format をロードするため通常 SlideKitFormat は存在する。
  // 旧 slide-edit.js との混在 (Requirements 5.2) に備え、
  //   (1) 未定義なら自分の src 基準で slidekit-defs.js / slidekit-format.js を動的ロード
  //   (2) それでも未定義なら AWS 装飾なしで表示を続行 (WARN のみ。プレゼン自体は止めない)
  // リマップは defs.coverRemap (9色) から機械生成 = プレゼン表示も PPTX と同じ9色 (Requirements 7.3)。
  function applyAwsFormatIfNeeded(slides){
    var html = document.documentElement;
    var isAws = html.getAttribute('data-template') === 'aws' || html.getAttribute('data-aws-decoration') === 'on';
    if (!isAws) return;
    function applyAll(){
      // ロード順不定対策: slidekit-aws.js プラグインが defs より先に評価されていても
      // オーバーレイ適用前にここで defs.formats へマージする (二重実行でも同値上書きで冪等)
      if (window.SlideKitFormat.registerFormatPlugins) window.SlideKitFormat.registerFormatPlugins();
      slides.forEach(function(s){
        // 冪等 (.aws-overlay 既存ならスキップ) / data-aws-logo="off" 尊重は applyAwsOverlay 側の契約
        window.SlideKitFormat.applyAwsOverlay(s, { uiClass: '_sp_ui' });
      });
    }
    if (window.SlideKitFormat && window.SLIDEKIT_DEFS) { applyAll(); return; }
    loadFormatDeps(function(){
      if (window.SlideKitFormat && window.SLIDEKIT_DEFS) applyAll();
      else console.warn('SlideKit: slidekit-format.js が読めないため AWS フォーマットなしで表示します (旧 slide-edit.js との混在?)');
    });
  }

  // defs/format の動的ロード (slide-edit.js の loadSlideKitDeps と同じ src 推定手法 / Requirements 5.2)
  // slide-edit.js (v2) が既に <script> を挿入済みならそれの load を待ち、二重挿入しない。
  // 壊れた defs 等で load が既に終わっているケースに備えて 3 秒の保険タイマー付き。
  var _depsWaiters = null;
  function loadFormatDeps(done){
    if (window.SlideKitFormat && window.SLIDEKIT_DEFS) { done(); return; }
    if (_depsWaiters) { _depsWaiters.push(done); return; }
    _depsWaiters = [done];
    var finish = function(){
      var cbs = _depsWaiters || [];
      _depsWaiters = null;
      cbs.forEach(function(cb){ try { cb(); } catch(_){} });
    };
    var me = document.querySelector('script[src*="slide-present"]');
    var dir = me ? (me.getAttribute('src') || '').replace(/slide-present\.js.*$/, '') : '';
    var remain = 3;
    var fin = function(){ if (--remain === 0) finish(); };
    // slidekit-aws.js は任意のプラグイン。無ければ error → fin で正常続行 (AWS 装飾なし表示)
    [['slidekit-defs.js', function(){ return window.SLIDEKIT_DEFS; }],
     ['slidekit-format.js', function(){ return window.SlideKitFormat; }],
     ['slidekit-aws.js', function(){ return window.SLIDEKIT_AWS; }]].forEach(function(pair){
      if (pair[1]()) { fin(); return; }
      var s = document.querySelector('script[src*="' + pair[0].replace('.js', '') + '"]');
      if (!s) { s = document.createElement('script'); s.src = dir + pair[0]; document.head.appendChild(s); }
      s.addEventListener('load', fin);
      s.addEventListener('error', fin);
    });
    setTimeout(finish, 3000); // 保険 (finish は1回しか効かない)
  }

  function injectPresentStyles(){
    var s = document.createElement('style');
    s.id = '_sp_style';
    s.className = 'seui'; // 💾保存時にHTMLへ焼き込まれないようマーク
    s.textContent = [
      // プレゼン中はビューポート全体を黒にして余計な余白を絶対に出さない
      'html { margin:0!important; padding:0!important; height:100%!important; overflow:hidden!important; background:#000!important; }',
      'body._sp_active { margin:0!important; padding:0!important; height:100%!important; background:#000!important; overflow:hidden!important; box-sizing:border-box!important; }',
      // body 直下: .slide と ._sp_ui クラスを持つ要素だけ表示。他は全部隠す
      // (SlideKit のツールバー、サムネイル、パネル類を排除する)
      'body._sp_active > *:not(.slide):not(._sp_ui):not(script):not(style):not(link) { display:none!important; }',
      // SlideKit UI (万一 hideUI が効かない場合の保険)
      'body._sp_active .seui:not(._sp_ui) { display:none!important; }',
      // スライド本体は position:fixed で中央固定
      'body._sp_active .slide {',
      '  display:none!important; margin:0; box-shadow:none;',
      '  position:fixed; top:50%; left:50%;',
      '  transform:translate(-50%,-50%);',
      '  transform-origin:center center;',
      '  z-index:8001;',
      '}',
      'body._sp_active .slide._sp_show { display:flex!important; flex-direction:column; }',
      '._sp_overlay { position:fixed; inset:0; background:#000; z-index:8000; }'
    ].join('\n');
    document.head.appendChild(s);
  }

  // ============================================================
  // リモート (手元編集ウィンドウ) 側
  // ============================================================
  function initRemoteMode(){
    // hideUI=1 の時は SlideKit 用の iframe 呼び出しなのでプレゼン開くボタンは出さない
    if (params.get('hideUI') === '1' || params.get('hideUI') === 'true') return;

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', setupRemote);
    } else {
      setupRemote();
    }
  }

  function setupRemote(){
    if (!document.querySelector('.slide')) return;

    // 「📺 プレゼン再生」ボタン
    // SlideKit本体ツールバー(#_sk_toolbar)があればその中に追加、無ければ左上にfixed配置
    var btn = document.createElement('button');
    btn.id = '_sp_openbtn';
    btn.className = 'seui'; // SlideKit の hideUI モードでは非表示になる
    btn.textContent = '📺 プレゼン再生';
    btn.title = '別ウィンドウでフルスクリーン プレゼンを開く (Zoom 画面共有向け)';
    btn.addEventListener('mouseenter', function(){ btn.style.background = '#3b82f6'; });
    btn.addEventListener('mouseleave', function(){ btn.style.background = '#2563eb'; });
    // ツールバー(#_sk_toolbar)は slide-edit.js が生成する。両スクリプトとも DOMContentLoaded 起動で
    // 生成順に依存するため、ツールバーが未生成のうちに setupRemote が走ると以前は左上フォールバックに
    // 落ちて「右上に置いたはずが左上に戻る」不具合が出ていた。→ 少し待って確実にツールバー内に入れる。
    // フォールバック(本体なしHTML)も左上ではなく右上に統一する。
    function placeBtn(tries){
      var _skBar = document.getElementById('_sk_toolbar');
      if (_skBar) {
        // ツールバー内: 「✏️ 編集」の上（先頭）に配置
        btn.style.cssText = 'padding:6px 10px;border:none;border-radius:4px;background:#2563eb;color:#fff;font:700 12px/1.2 -apple-system,sans-serif;cursor:pointer;text-align:center;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.2)';
        _skBar.insertBefore(btn, _skBar.firstChild);
      } else if (tries > 0) {
        setTimeout(function(){ placeBtn(tries - 1); }, 100); // 最大 ~2秒 ツールバー生成を待つ
      } else {
        // fallback: 右上fixed（SlideKit本体が無いHTML用。左上ではなくツールバー位置に合わせる）
        btn.style.cssText = 'position:fixed;top:12px;right:8px;z-index:99998;padding:8px 14px;border:none;border-radius:6px;background:#2563eb;color:#fff;font:700 13px/1.2 -apple-system,sans-serif;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);white-space:nowrap';
        document.body.appendChild(btn);
      }
    }
    placeBtn(20);

    var presentWin = null;
    var curIdx = 0, total = 0;

    // リモコンパネル (プレゼン起動時のみ表示)
    var ctrl = document.createElement('div');
    ctrl.id = '_sp_remote';
    ctrl.className = 'seui';
    // 左端のページ一覧カラム(128px)の右隣に配置（編集モードと同じ位置・ページ表示と被らない）
    ctrl.style.cssText = 'display:none;position:fixed;bottom:14px;left:140px;z-index:99998;background:rgba(30,41,59,.94);padding:8px 10px;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.4);color:#fff;font:600 13px/1 -apple-system,sans-serif;align-items:center;gap:6px;backdrop-filter:blur(4px)';
    var btnStyle = 'padding:6px 10px;border:none;border-radius:4px;background:#4a6fa5;color:#fff;cursor:pointer;font-size:13px';
    ctrl.innerHTML =
      '<button data-sp="first" title="最初へ" style="' + btnStyle + ';padding:6px 8px;font-size:12px">⏮</button>' +
      '<button data-sp="prev"  title="前へ (←)" style="' + btnStyle + ';font-size:14px">◀</button>' +
      '<span id="_sp_pos" style="min-width:64px;text-align:center;color:#e0e7ff;font-weight:700">- / -</span>' +
      '<button data-sp="next"  title="次へ (→)" style="' + btnStyle + ';font-size:14px">▶</button>' +
      '<button data-sp="last"  title="最後へ" style="' + btnStyle + ';padding:6px 8px;font-size:12px">⏭</button>' +
      '<span style="width:1px;height:22px;background:rgba(255,255,255,.2);margin:0 4px"></span>' +
      '<button data-sp="laser" title="レーザーポインター (手元でマウス移動→プレゼンに赤い点)" style="' + btnStyle + ';font-size:12px">🔴 レーザー</button>' +
      '<button data-sp="pen"   title="ペン (手元でドラッグ→プレゼンに線を描く)" style="' + btnStyle + ';font-size:12px">✏️ ペン</button>' +
      '<button data-sp="clear" title="書き込み消去" style="' + btnStyle + ';font-size:12px;background:#64748b;display:none">🗑 消す</button>' +
      '<span style="width:1px;height:22px;background:rgba(255,255,255,.2);margin:0 4px"></span>' +
      '<button data-sp="focus" title="プレゼンウィンドウを前面に" style="' + btnStyle + ';background:#059669;font-size:12px">🔍 手前へ</button>' +
      '<button data-sp="close" title="プレゼンを閉じる" style="' + btnStyle + ';background:#c62828;font-size:12px">✕ 閉じる</button>';
    document.body.appendChild(ctrl);

    function openPresentation(){
      var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
      // 手元で今スクロール中に近いスライドを初期表示
      var idx = 0;
      var vc = window.innerHeight / 2 + window.scrollY;
      var best = Infinity;
      slides.forEach(function(s, i){
        var rect = s.getBoundingClientRect();
        var c = rect.top + window.scrollY + rect.height / 2;
        var d = Math.abs(c - vc);
        if (d < best) { best = d; idx = i; }
      });

      var sep = location.search ? '&' : '?';
      var url = location.pathname + location.search + sep + 'present=1&hideUI=1&idx=' + idx + '&session=' + encodeURIComponent(SESSION_ID);
      // カウンター非表示指定を present 側にも渡す
      if (!SHOW_COUNTER) url += '&counter=0';
      if (presentWin && !presentWin.closed) {
        // 既に開いてる → フォーカスだけ
        try { presentWin.focus(); } catch(_){}
        return;
      }
      // ウィンドウ名にもセッションIDを付ける (別デッキとウィンドウ衝突を防ぐ)
      var winName = 'slideKitPresent_' + SESSION_ID.slice(0, 8);
      presentWin = window.open(url, winName, 'width=1280,height=720,left=100,top=100');
      if (presentWin) {
        try { presentWin.focus(); } catch(_){}
        // 編集内容の同期を開始 (少し待って observer 起動)
        setTimeout(function(){ if (presentWin && !presentWin.closed) startEditSync(); }, 500);
      } else {
        alert('プレゼンウィンドウを開けませんでした。\nブラウザのポップアップブロックを解除してください。');
      }
    }

    btn.addEventListener('click', openPresentation);

    // ============================================================
    // SlideKit の要素選択解除ワークアラウンド
    // ============================================================
    // 「スライドの外をクリックしても .tb 選択の outline が残る」問題を
    // 強制解決する。slide-edit.js は無変更で、こちらで補う。
    //
    // 発動条件: スライドの外 (かつ SlideKit UI の外) を mousedown した時、
    // .slide 内の全 [data-x] 要素の outline を消す。
    document.addEventListener('mousedown', function(e){
      var t = e.target;
      if (!t) return;
      // スライドの中は対象外
      if (t.closest && t.closest('.slide')) return;
      // SlideKit / present の UI (.seui) の中も対象外
      if (t.closest && t.closest('.seui')) return;
      // body の空白部分をクリックした時に全 outline をリセット
      document.querySelectorAll('.slide [data-x], .slide img').forEach(function(el){
        if (el.style && el.style.outline) {
          el.style.outline = '';
          el.style.outlineOffset = '';
        }
        // contenteditable も解除
        if (el.getAttribute && el.getAttribute('contenteditable') === 'true') {
          el.contentEditable = 'false';
          try { el.blur(); } catch(_){}
        }
      });
      // SlideKit の公開 API を通じて内部状態 (sels[]/pageSel) も解除。
      // Escape 合成キー方式は edit.js の Escape ハンドラ変更で壊れるので廃止。
      if (window.SlideKit && typeof window.SlideKit.clearSelection === 'function') {
        try { window.SlideKit.clearSelection(); } catch(_){}
      } else {
        // 公開 API が無い旧版 slide-edit.js フォールバック: 従来の Escape 2 連発
        try {
          var escEvt = new KeyboardEvent('keydown', {key:'Escape', code:'Escape', keyCode:27, which:27, bubbles:true, cancelable:true});
          document.dispatchEvent(escEvt);
          setTimeout(function(){
            var e2 = new KeyboardEvent('keydown', {key:'Escape', code:'Escape', keyCode:27, which:27, bubbles:true, cancelable:true});
            document.dispatchEvent(e2);
          }, 10);
        } catch(_){}
      }
    }, true); // capture phase で先取り

    // ページジャンプパネル (左サイド・SlideKit の skit-thumbs と同じ縦リスト)
    // 顧客が「P10 を見せて」と言った時に一発でジャンプ、タイトルで内容も分かる。
    var jump = document.createElement('div');
    jump.id = '_sp_jump';
    jump.className = 'seui';
    // 編集モードの左サムネイル列(.skit-thumbs: left0/top0/bottom0/width128)と同じ座標に統一
    jump.style.cssText = 'display:none;position:fixed;top:0;left:0;bottom:0;width:128px;z-index:99995;background:#1f2933;padding:8px 6px;box-shadow:2px 0 8px rgba(0,0,0,.2);overflow-y:auto;box-sizing:border-box;font-family:Meiryo,sans-serif';
    document.body.appendChild(jump);

    // スライドのタイトル取得 (data-role="title" があればそれ、無ければ一番大きいフォントの tb)
    function slideTitleOf(s){
      var t = s.querySelector('[data-role="title"]');
      if (!t) {
        var tbs = [].slice.call(s.querySelectorAll(':scope > .tb[data-x]'));
        tbs.sort(function(a, b){
          return (parseFloat(b.getAttribute('data-font-size')||0) - parseFloat(a.getAttribute('data-font-size')||0));
        });
        t = tbs[0];
      }
      var txt = (t && t.textContent && t.textContent.trim()) || '(無題)';
      return txt.replace(/\s+/g, ' ').slice(0, 28);
    }

    function renderJumpGrid(){
      jump.innerHTML = '';
      var slides = document.querySelectorAll('.slide');
      for (var i = 0; i < slides.length; i++) {
        var b = document.createElement('button');
        b.setAttribute('data-jump', i);
        var isCur = (i === curIdx);
        b.style.cssText = 'display:block;width:100%;margin-bottom:6px;padding:6px 8px;background:' + (isCur ? '#21537f' : '#162a42') + ';color:' + (isCur ? '#fff' : '#cdd9e5') + ';border:none;border-left:3px solid ' + (isCur ? '#fafafa' : 'transparent') + ';border-radius:5px;cursor:pointer;font:400 11px/1.35 Meiryo,sans-serif;text-align:left;transition:all .15s';
        var ttl = slideTitleOf(slides[i]);
        b.innerHTML = '<span style="display:block;font-size:9px;color:' + (isCur ? '#c8dcef' : '#7a92ad') + ';margin-bottom:2px;font-weight:700">P' + (i + 1) + '</span>' + ttl;
        b.title = 'P' + (i + 1) + ' ' + ttl;
        jump.appendChild(b);
      }
    }

    jump.addEventListener('click', function(e){
      var t = e.target.closest('[data-jump]');
      if (!t) return;
      var idx = parseInt(t.getAttribute('data-jump'), 10);
      if (isNaN(idx)) return;
      navLocalAndSend(idx);
    });

    jump.addEventListener('mouseover', function(e){
      var t = e.target.closest('[data-jump]');
      if (!t) return;
      var idx = parseInt(t.getAttribute('data-jump'), 10);
      if (idx !== curIdx) t.style.background = '#234060';
    });
    jump.addEventListener('mouseout', function(e){
      var t = e.target.closest('[data-jump]');
      if (!t) return;
      var idx = parseInt(t.getAttribute('data-jump'), 10);
      if (idx !== curIdx) t.style.background = '#162a42';
    });

    // ---- 編集モードとの共存（ページ一覧の二重表示を防ぐ）----
    // 編集ON中はSlideKitの左サムネイル(.skit-thumbs)に一本化し、ジャンプパネルは隠す。
    // （リモコンバーは常時left:140px＝サムネイル/ジャンプ列の右隣なので調整不要）
    var coexistStyle = document.createElement('style');
    coexistStyle.className = 'seui'; // 💾保存時にHTMLへ焼き込まれないようマーク
    coexistStyle.textContent =
      'body[data-skit-edit="on"] #_sp_jump{display:none!important}';
    document.head.appendChild(coexistStyle);

    // 編集サムネイルのクリックでもプレゼン画面を追従させる（ジャンプパネルの代役）
    document.addEventListener('click', function(e){
      if (!presentWin || presentWin.closed) return;
      var t = e.target.closest('.skit-thumb');
      if (!t) return;
      var thumbs = [].slice.call(document.querySelectorAll('.skit-thumb'));
      var idx = thumbs.indexOf(t);
      if (idx >= 0) navLocalAndSend(idx);
    });

    var laserOn = false, penOn = false;

    // レーザー/ペン時に SlideKit の編集操作(選択・ドラッグ)を無効化するための
    // 全画面キャプチャレイヤー。ここが mouse イベントを先取りする。
    var captureLayer = document.createElement('div');
    captureLayer.id = '_sp_capture';
    captureLayer.className = 'seui';
    captureLayer.style.cssText = 'position:fixed;inset:0;z-index:99000;display:none;cursor:crosshair;background:transparent';
    document.body.appendChild(captureLayer);

    // 手元 (SlideKit) 側にもレーザードットとペン canvas を出す (プレゼンと同じ内容を確認できる)
    var localLaser = document.createElement('div');
    localLaser.className = 'seui';
    localLaser.style.cssText = 'position:fixed;width:18px;height:18px;border-radius:50%;background:rgba(255,40,40,.85);box-shadow:0 0 16px 6px rgba(255,40,40,.55);z-index:99500;pointer-events:none;display:none;transform:translate(-50%,-50%)';
    document.body.appendChild(localLaser);

    var localPenCanvas = document.createElement('canvas');
    localPenCanvas.className = 'seui';
    localPenCanvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:99400;pointer-events:none';
    document.body.appendChild(localPenCanvas);

    // 手元側のペン線保持 (プレゼンと同じデータをローカルにも溜める)
    var localStrokes = []; // {color, width, slideIndex, points:[{xPct,yPct}]}
    var localCurrent = null;

    function resizeLocalCanvas(){
      localPenCanvas.width = window.innerWidth;
      localPenCanvas.height = window.innerHeight;
      redrawLocalPen();
    }
    resizeLocalCanvas();
    window.addEventListener('resize', resizeLocalCanvas);
    window.addEventListener('scroll', redrawLocalPen, {passive:true});

    function localSlideRect(slideIndex){
      var s = document.querySelectorAll('.slide')[slideIndex];
      return s ? s.getBoundingClientRect() : null;
    }

    function redrawLocalPen(){
      var ctx = localPenCanvas.getContext('2d');
      ctx.clearRect(0, 0, localPenCanvas.width, localPenCanvas.height);
      localStrokes.forEach(function(stroke){
        var r = localSlideRect(stroke.slideIndex);
        if (!r || !r.width) return;
        if (stroke.points.length < 2) return;
        ctx.strokeStyle = stroke.color || '#ef4444';
        ctx.lineWidth = stroke.width || 3;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(r.left + stroke.points[0].xPct * r.width, r.top + stroke.points[0].yPct * r.height);
        for (var i = 1; i < stroke.points.length; i++) {
          ctx.lineTo(r.left + stroke.points[i].xPct * r.width, r.top + stroke.points[i].yPct * r.height);
        }
        ctx.stroke();
      });
    }

    function updateLocalLaser(xPct, yPct, slideIndex, visible){
      if (!visible) { localLaser.style.display = 'none'; return; }
      var r = localSlideRect(slideIndex);
      if (!r || !r.width) { localLaser.style.display = 'none'; return; }
      localLaser.style.left = (r.left + xPct * r.width) + 'px';
      localLaser.style.top = (r.top + yPct * r.height) + 'px';
      localLaser.style.display = 'block';
    }

    function updateCaptureLayer(){
      captureLayer.style.display = (laserOn || penOn) ? 'block' : 'none';
    }

    // デバッグは撤去 (問題切り分けが済んだのでシンプルにする)
    function updateDbg(){}
    function sendMsg(msg){
      try { bus.postMessage(msg); } catch(e) { console.warn('bus send failed:', e); }
    }

    function setToggle(btn, on){
      btn.style.background = on ? '#ef4444' : '#4a6fa5';
      btn.style.fontWeight = on ? '700' : '600';
    }

    function updateClearBtn(){
      var btn = ctrl.querySelector('[data-sp="clear"]');
      if (btn) btn.style.display = (penOn || penHasStrokes) ? 'inline-block' : 'none';
    }

    // ローカル(手元) 側も同じスライドに合わせる (present の echo を待たずに即応)
    function navLocalAndSend(newIdx){
      if (newIdx < 0) newIdx = 0;
      var slideCount = total || document.querySelectorAll('.slide').length;
      if (newIdx >= slideCount) newIdx = slideCount - 1;
      curIdx = newIdx;
      var pos = ctrl.querySelector('#_sp_pos');
      if (pos) pos.textContent = (curIdx + 1) + ' / ' + slideCount;
      scrollToSlideInEditor(curIdx);
      renderJumpGrid();
      sendMsg({type:'slide:change', index:curIdx, from:'remote'});
    }

    // プレゼン中メモ。静的なinnerHTMLへ文字列を差し込まず、DOM APIでボタンを追加する。
    var noteBtn = document.createElement('button');
    noteBtn.setAttribute('data-sp', 'note');
    noteBtn.title = '現在のスライドにポストイットを追加';
    noteBtn.textContent = '🗒 メモ';
    noteBtn.style.cssText = btnStyle + ';font-size:14px;background:#f4f4ef;color:#121212;font-weight:700';
    ctrl.insertBefore(noteBtn, ctrl.querySelector('[data-sp="laser"]'));

    function addStickyNoteForCurrent(){
      var slides = document.querySelectorAll('.slide');
      var slide = slides[curIdx];
      if (!slide) return;
      if (!window.SlideKit || typeof window.SlideKit.addStickyNote !== 'function') {
        alert('メモ機能を使うには最新の slide-edit.js が必要です。');
        return;
      }
      // 入力時はキャプチャレイヤーを外し、ポストイットを直接編集できる状態にする。
      if (laserOn || penOn) {
        laserOn = false; penOn = false; penDrawing = false;
        setToggle(ctrl.querySelector('[data-sp="laser"]'), false);
        setToggle(ctrl.querySelector('[data-sp="pen"]'), false);
        updateCaptureLayer();
        if (localLaser) localLaser.style.display = 'none';
        sendMsg({type:'tool:state', laser:false, pen:false, from:'remote'});
      }
      scrollToSlideInEditor(curIdx);
      window.SlideKit.addStickyNote(slide);
    }

    ctrl.addEventListener('click', function(e){
      var t = e.target.closest('[data-sp]');
      if (!t) return;
      var act = t.getAttribute('data-sp');
      if (act === 'prev')  navLocalAndSend(curIdx - 1);
      if (act === 'next')  navLocalAndSend(curIdx + 1);
      if (act === 'first') navLocalAndSend(0);
      if (act === 'last')  navLocalAndSend((total || document.querySelectorAll('.slide').length) - 1);
      if (act === 'note')  addStickyNoteForCurrent();
      if (act === 'focus') { if (presentWin && !presentWin.closed) { try { presentWin.focus(); } catch(_){} } }
      if (act === 'laser') {
        laserOn = !laserOn;
        setToggle(t, laserOn);
        // ペンと排他
        if (laserOn && penOn) { penOn = false; setToggle(ctrl.querySelector('[data-sp="pen"]'), false); }
        updateCaptureLayer();
        if (!laserOn) bus.postMessage({type:'laser:move', visible:false, from:'remote'});
        bus.postMessage({type:'tool:state', laser:laserOn, pen:penOn, from:'remote'});
      }
      if (act === 'pen') {
        penOn = !penOn;
        setToggle(t, penOn);
        if (penOn && laserOn) {
          laserOn = false;
          setToggle(ctrl.querySelector('[data-sp="laser"]'), false);
          bus.postMessage({type:'laser:move', visible:false, from:'remote'});
        }
        updateCaptureLayer();
        updateClearBtn();
        bus.postMessage({type:'tool:state', laser:laserOn, pen:penOn, from:'remote'});
      }
      if (act === 'clear') {
        bus.postMessage({type:'pen:clear', from:'remote'});
        penHasStrokes = false;
        updateClearBtn();
        // 手元のストロークもクリア
        localStrokes = [];
        localCurrent = null;
        redrawLocalPen();
      }
      if (act === 'close') {
        if (presentWin && !presentWin.closed) { try { presentWin.close(); } catch(_){} }
        cleanupPresentation();
      }
    });

    // ================================================================
    // クリーンアップ処理を一本化 (Review 2-1)
    // ================================================================
    // 呼び出し元: ①リモコン閉じる ②present:close 受信 ③presentWin.closed 検知 ④beforeunload
    // どこから呼ばれても同じ後片付けをする。これがないと laser/pen ON のまま
    // ウィンドウが閉じられると captureLayer が透明で残って手元がクリック不能になる。
    var cleanedUp = false;
    function cleanupPresentation(){
      if (cleanedUp) return;
      cleanedUp = true;
      presentWin = null;
      // UI 隠す
      if (ctrl) ctrl.style.display = 'none';
      if (jump) jump.style.display = 'none';
      // レーザー/ペンモード解除 + captureLayer 撤去
      laserOn = false;
      penOn = false;
      penDrawing = false;
      updateCaptureLayer();
      // MutationObserver 停止 (これがないと再度開いた時に二重発火する)
      try { stopEditSync(); } catch(_){}
      // 相手側にも解除通知 (念のため・既に閉じてる場合は無害)
      try { bus.postMessage({type:'tool:state', laser:false, pen:false, from:'remote'}); } catch(_){}
      // スライドの青ハイライトを外す
      document.querySelectorAll('.slide').forEach(function(x){
        x.style.outline = '';
        x.style.outlineOffset = '';
        x.style.boxShadow = x.getAttribute('data-orig-shadow') || '';
        x.removeAttribute('data-orig-shadow');
      });
      // 手元のレーザードット / ペンストローク消去
      if (localLaser) localLaser.style.display = 'none';
      localStrokes = [];
      localCurrent = null;
      try { redrawLocalPen(); } catch(_){}
      // 次回のプレゼン開始のためフラグ戻す
      setTimeout(function(){ cleanedUp = false; }, 500);
    }

    // ==== 手元マウス → スライド相対座標 ====
    var penHasStrokes = false;
    var penDrawing = false;

    function slideCoordFromEvent(e){
      // e.target 直下からスライドを遡って探す
      var slides = document.querySelectorAll('.slide');
      // クリック位置に含まれるスライドを検索
      for (var i = 0; i < slides.length; i++) {
        var r = slides[i].getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX <= r.right &&
            e.clientY >= r.top && e.clientY <= r.bottom) {
          return {
            xPct: (e.clientX - r.left) / r.width,
            yPct: (e.clientY - r.top) / r.height,
            slideIndex: i
          };
        }
      }
      return null;
    }

    // マウス移動 → レーザー / ペン描画中の点送信
    // captureLayer の上でイベントを受けるので SlideKit の編集ハンドラに邪魔されない
    captureLayer.addEventListener('mousemove', function(e){
      if (!presentWin || presentWin.closed) return;
      var pt = slideCoordFromEvent(e);
      if (!pt) {
        if (laserOn) {
          sendMsg({type:'laser:move', visible:false, from:'remote'});
          updateLocalLaser(0, 0, 0, false);
        }
        return;
      }
      if (laserOn) {
        sendMsg({type:'laser:move', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, visible:true, from:'remote'});
        // 手元にも同じ位置に赤い点
        updateLocalLaser(pt.xPct, pt.yPct, pt.slideIndex, true);
      }
      if (penDrawing) {
        sendMsg({type:'pen:point', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, from:'remote'});
        // 手元側の現在ストロークにも追加
        if (localCurrent) {
          // slideIndex が変わったら別ストローク
          if (pt.slideIndex !== localCurrent.slideIndex) {
            localCurrent = { color:localCurrent.color, width:localCurrent.width, slideIndex:pt.slideIndex, points:[] };
            localStrokes.push(localCurrent);
          }
          localCurrent.points.push({xPct:pt.xPct, yPct:pt.yPct});
          redrawLocalPen();
        }
      }
    });

    // ペン: マウス押下・離しでストローク管理
    captureLayer.addEventListener('mousedown', function(e){
      if (!penOn || !presentWin || presentWin.closed) return;
      var pt = slideCoordFromEvent(e);
      if (!pt) return;
      e.preventDefault();
      penDrawing = true;
      penHasStrokes = true;
      updateClearBtn();
      sendMsg({type:'pen:start', xPct:pt.xPct, yPct:pt.yPct, slideIndex:pt.slideIndex, color:'#ef4444', width:3, from:'remote'});
      // 手元にも新規ストローク開始
      localCurrent = { color:'#ef4444', width:3, slideIndex:pt.slideIndex, points:[{xPct:pt.xPct, yPct:pt.yPct}] };
      localStrokes.push(localCurrent);
    });
    captureLayer.addEventListener('mouseup', function(){
      if (!penDrawing) return;
      penDrawing = false;
      sendMsg({type:'pen:end', from:'remote'});
    });
    captureLayer.addEventListener('mouseleave', function(){
      if (!penDrawing) return;
      penDrawing = false;
      sendMsg({type:'pen:end', from:'remote'});
    });
    // スクロールしてもレーザー座標が正しく計算されるように
    // (captureLayer は position:fixed なので mousewheel も自分の上で発火)
    captureLayer.addEventListener('wheel', function(e){
      // wheel は下の要素(スライド一覧)に通したい
      // captureLayer の下のスクロール可能な要素にスクロールを転送
      window.scrollBy(0, e.deltaY);
      e.preventDefault();
    }, {passive:false});

    function scrollToSlideInEditor(index){
      var slides = document.querySelectorAll('.slide');
      var s = slides[index];
      if (!s) return;
      // 全スライドから "投影中" ハイライトを外す → 現在のに付ける
      slides.forEach(function(x){
        x.style.outline = '';
        x.style.outlineOffset = '';
        x.style.boxShadow = x.getAttribute('data-orig-shadow') || '';
      });
      // 現スライドの元 box-shadow を保存しておいて置き換える
      if (!s.hasAttribute('data-orig-shadow')) {
        s.setAttribute('data-orig-shadow', s.style.boxShadow || '');
      }
      s.style.outline = '4px solid #2563eb';
      s.style.outlineOffset = '2px';
      s.style.boxShadow = '0 0 0 8px rgba(37,99,235,0.25), 0 8px 24px rgba(37,99,235,0.35)';
      // スライドを画面中央に (scrollIntoView は browser 実装で自動計算)
      try { s.scrollIntoView({behavior:'smooth', block:'center'}); }
      catch(_) {
        var rect = s.getBoundingClientRect();
        window.scrollTo(0, Math.max(0, rect.top + window.scrollY - 100));
      }
      // スクロール後にペン線を再描画 (位置ズレ防止)
      setTimeout(redrawLocalPen, 400);
    }

    bus.onmessage = function(e){
      var d = e.data;
      if (!d || d.from === 'remote') return;
      if (d.type === 'slide:change' || d.type === 'slide:reply') {
        curIdx = d.index;
        total = d.total;
        ctrl.style.display = 'flex';
        jump.style.display = 'block';
        var pos = ctrl.querySelector('#_sp_pos');
        if (pos) pos.textContent = (curIdx + 1) + ' / ' + total;
        renderJumpGrid();
        // 手元 SlideKit 側でも同じスライドまでスクロール
        if (d.type === 'slide:change') scrollToSlideInEditor(curIdx);
      }
      if (d.type === 'present:close') {
        cleanupPresentation();
      }

      // ==== present 側から laser/pen が来た時 (プレゼン画面上でマウス操作した時) ====
      // SlideKit(手元) 側でも同じ位置に赤い点/線を出す
      if (d.type === 'laser:move') {
        if (!d.visible) { localLaser.style.display = 'none'; return; }
        updateLocalLaser(d.xPct, d.yPct, d.slideIndex, true);
      }
      if (d.type === 'pen:start') {
        localCurrent = { color:d.color||'#ef4444', width:d.width||3, slideIndex:d.slideIndex, points:[{xPct:d.xPct, yPct:d.yPct}] };
        localStrokes.push(localCurrent);
        penHasStrokes = true;
        updateClearBtn();
        redrawLocalPen();
      }
      if (d.type === 'pen:point') {
        if (!localCurrent) return;
        if (d.slideIndex !== undefined && d.slideIndex !== localCurrent.slideIndex) {
          localCurrent = { color:localCurrent.color, width:localCurrent.width, slideIndex:d.slideIndex, points:[] };
          localStrokes.push(localCurrent);
        }
        localCurrent.points.push({xPct:d.xPct, yPct:d.yPct});
        redrawLocalPen();
      }
      if (d.type === 'pen:end') {
        localCurrent = null;
      }
    };

    // プレゼンウィンドウが手動で閉じられた時の検出
    setInterval(function(){
      if (presentWin && presentWin.closed) {
        cleanupPresentation();
      }
    }, 1500);

    // 手元ページ離脱時にも cleanup + プレゼン側にも close 通知
    window.addEventListener('beforeunload', function(){
      try { bus.postMessage({type:'present:close', from:'remote'}); } catch(_){}
      cleanupPresentation();
    });

    // ============================================================
    // SlideKit で編集した内容をプレゼン側にリアルタイム反映
    // ============================================================
    // 手元で編集(テキスト・色・位置・追加削除)した瞬間、
    // MutationObserver で検知して該当スライドの outerHTML を送信。
    // プレゼン側はそのスライドを置き換える。
    var pendingUpdate = {}; // slideIndex → timeout id
    var UPDATE_DEBOUNCE = 300;

    function sendSlideUpdate(slideIdx){
      var slides = document.querySelectorAll('.slide');
      var s = slides[slideIdx];
      if (!s) return;
      // clone してから統一サニタイズ (SlideKit.sanitizeSlide に集約)
      // 剥がすリストは slide-edit.js 側で一元管理される
      var clone = s.cloneNode(true);
      if (window.SlideKit && typeof window.SlideKit.sanitizeSlide === 'function') {
        window.SlideKit.sanitizeSlide(clone, 'sync');
      } else {
        // 旧版 slide-edit.js フォールバック (最低限のクリーンアップ)
        clone.querySelectorAll('.seui, .aws-overlay').forEach(function(e){ e.remove(); });
        clone.classList.remove('aws-cover');
        clone.style.outline = '';
      }
      var html = clone.outerHTML;
      try {
        bus.postMessage({type:'slide:update', index:slideIdx, html:html, from:'remote'});
      } catch(e) { console.warn('slide:update send failed', e); }
    }

    function scheduleSlideUpdate(slideIdx){
      if (!presentWin || presentWin.closed) return;
      if (pendingUpdate[slideIdx]) clearTimeout(pendingUpdate[slideIdx]);
      pendingUpdate[slideIdx] = setTimeout(function(){
        pendingUpdate[slideIdx] = null;
        sendSlideUpdate(slideIdx);
      }, UPDATE_DEBOUNCE);
    }

    // スライド構造 (追加/削除/並べ替え) を監視する別 observer
    // body 直下の .slide の変化を検知したらフル同期
    var deckStructureObserver = new MutationObserver(function(mutations){
      var hasStructureChange = mutations.some(function(m){
        if (m.type !== 'childList') return false;
        // 追加/削除されたノードに .slide があるか
        var added = Array.prototype.some.call(m.addedNodes, function(n){
          return n.nodeType === 1 && n.classList && n.classList.contains('slide');
        });
        var removed = Array.prototype.some.call(m.removedNodes, function(n){
          return n.nodeType === 1 && n.classList && n.classList.contains('slide');
        });
        return added || removed;
      });
      if (hasStructureChange) {
        // 新規追加スライドにも Observer を張り直す (レビュー指摘: 追加後の編集が同期されない)
        refreshSlideObservers();
        scheduleDeckSync();
      }
    });

    var pendingDeckSync = null;
    function scheduleDeckSync(){
      if (!presentWin || presentWin.closed) return;
      if (pendingDeckSync) clearTimeout(pendingDeckSync);
      pendingDeckSync = setTimeout(function(){
        pendingDeckSync = null;
        sendDeckSync();
      }, UPDATE_DEBOUNCE);
    }

    // 全スライドを送り直し (プレゼン側で slides[] 配列を再構築させる)
    // 手元側の total / UI (位置カウンタ / ジャンプグリッド) も同時更新する
    function sendDeckSync(){
      var slides = document.querySelectorAll('.slide');
      var htmls = [];
      slides.forEach(function(s){
        var clone = s.cloneNode(true);
        if (window.SlideKit && typeof window.SlideKit.sanitizeSlide === 'function') {
          window.SlideKit.sanitizeSlide(clone, 'sync');
        }
        htmls.push(clone.outerHTML);
      });
      // 手元側の状態を更新 (レビュー指摘: total が古いまま + ジャンプグリッド未再描画)
      total = htmls.length;
      if (total === 0) {
        curIdx = 0;
      } else {
        if (curIdx >= total) curIdx = total - 1;
        if (curIdx < 0) curIdx = 0;
      }
      var pos = ctrl.querySelector('#_sp_pos');
      if (pos) pos.textContent = total ? (curIdx + 1) + ' / ' + total : '0 / 0';
      renderJumpGrid();
      try {
        bus.postMessage({type:'deck:sync', htmls:htmls, total:total, curIdx:curIdx, from:'remote'});
      } catch(e) { console.warn('deck:sync send failed', e); }
    }

    var slideObserver = new MutationObserver(function(mutations){
      var slides = document.querySelectorAll('.slide');
      var changed = new Set();
      mutations.forEach(function(m){
        // 変更ノードから親スライドを遡って探す
        var node = m.target;
        while (node && node !== document.body) {
          if (node.classList && node.classList.contains('slide')) {
            var idx = Array.prototype.indexOf.call(slides, node);
            if (idx >= 0) changed.add(idx);
            break;
          }
          node = node.parentNode;
        }
      });
      changed.forEach(scheduleSlideUpdate);
    });

    // 現存する全 .slide に slideObserver を張り直す
    // (構造変更で新規追加されたスライドにも監視を及ぼすため)
    function refreshSlideObservers(){
      slideObserver.disconnect();
      document.querySelectorAll('.slide').forEach(function(s){
        slideObserver.observe(s, {
          childList: true,
          subtree: true,
          attributes: true,
          characterData: true,
          attributeOldValue: false,
          characterDataOldValue: false
        });
      });
    }

    // observer は present window が開いた時に起動、閉じたら止める
    function startEditSync(){
      refreshSlideObservers();
      // body 直下の構造変化 (スライドの追加/削除/並べ替え) を監視
      deckStructureObserver.observe(document.body, {childList: true});
    }
    function stopEditSync(){
      slideObserver.disconnect();
      deckStructureObserver.disconnect();
    }

    // キーボードショートカット: 手元でスライド送り (プレゼン起動時のみ)
    // - PageDown / PageUp / Space : 常にページ送り (SlideKit と競合しない)
    // - 矢印キー : SlideKit が要素移動に使用済(defaultPrevented=true)なら譲る
    document.addEventListener('keydown', function(e){
      if (!presentWin || presentWin.closed) return;
      if (e.target && e.target.matches && e.target.matches('input,textarea,[contenteditable]')) return;
      if (e.key === 'PageDown') {
        e.preventDefault();
        navLocalAndSend(curIdx + 1);
      } else if (e.key === 'PageUp') {
        e.preventDefault();
        navLocalAndSend(curIdx - 1);
      } else if (e.key === ' ') {
        e.preventDefault();
        navLocalAndSend(e.shiftKey ? curIdx - 1 : curIdx + 1);
      } else if (e.key === 'ArrowRight') {
        // SlideKit が既に要素移動で消費していれば譲る
        if (e.defaultPrevented) return;
        e.preventDefault();
        navLocalAndSend(curIdx + 1);
      } else if (e.key === 'ArrowLeft') {
        if (e.defaultPrevented) return;
        e.preventDefault();
        navLocalAndSend(curIdx - 1);
      }
    });
  }
})();
