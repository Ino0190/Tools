/**
 * SlideKit A4 縦エクスポート (独立ファイル・オプトイン)
 *
 * 既存の 1280×720 スライドを、A4 縦の PDF として出力する。
 * 印刷 CSS で `@page A4 portrait` に切り替え、各 .slide を縮小配置して
 * ブラウザの PDF 保存機能で書き出す。既存の HTML/PPTX 変換フローは無影響。
 *
 * 使い方:
 *   <script src="../SlideKit/slide-edit.js"></script>
 *   <script src="../SlideKit/slide-a4export.js"></script>
 *   → SlideKit ツールバーの下に「📄 A4 PDF」ボタンが 2 つ出る
 *
 * 対応モード:
 *   1up (1 スライド / A4 1 ページ) : 詳細資料・メモ欄付き印刷向け
 *   2up (2 スライド / A4 1 ページ) : PowerPoint 配布資料相当
 */
(function(){
  'use strict';

  // A4 縦の物理寸法
  // A4: 210mm × 297mm = 8.27" × 11.69" @ 96dpi ≈ 794 × 1123 px
  // スライド幅は slidekit-defs.js (canvas.wPx) が正本 (v2)。未ロード時は v1 と同値 (1280) にフォールバック。
  // 縮小率: 794 / スライド幅 (1280 なら 0.6203)。
  function _canvasWidth(){
    var c = window.SLIDEKIT_DEFS && window.SLIDEKIT_DEFS.canvas;
    return (c && c.wPx) || 1280;
  }

  // 印刷用 CSS を <head> に注入 (一度だけ)
  function injectPrintCss(){
    if (document.getElementById('_a4_export_style')) return;
    var SCALE = 794 / _canvasWidth(); // エクスポート実行時に defs から幅を取り込む
    var st = document.createElement('style');
    st.id = '_a4_export_style';
    st.className = 'seui'; // 💾保存時にHTMLへ焼き込まれないようマーク
    st.textContent = [
      '@media print {',
      '  @page { size: A4 portrait; margin: 0; }',
      '  html, body { margin: 0 !important; padding: 0 !important; background: #fff !important; }',
      '  /* SlideKit / present の UI は印刷に出さない */',
      '  .seui, ._sp_ui, #_sp_overlay, #_sp_counter { display: none !important; }',
      '  body[data-a4-export] .slide {',
      '    zoom: ' + SCALE + ';',
      '    display: block !important;',
      '    box-shadow: none !important;',
      '    page-break-inside: avoid;',
      '    -webkit-print-color-adjust: exact;',
      '    print-color-adjust: exact;',
      '    margin: 24px auto !important;',
      '  }',
      '  /* 1up: 1 スライド = 1 ページ */',
      '  body[data-a4-export="1up"] .slide { page-break-after: always; }',
      '  body[data-a4-export="1up"] .slide:last-of-type { page-break-after: auto; }',
      '  /* 2up: 2 スライド = 1 ページ */',
      '  body[data-a4-export="2up"] .slide { margin: 16px auto !important; }',
      '  body[data-a4-export="2up"] .slide:nth-of-type(2n) { page-break-after: always; }',
      '}'
    ].join('\n');
    document.head.appendChild(st);
  }

  function exportA4(mode){
    injectPrintCss();
    var body = document.body;
    // data-a4-export="1up" or "2up" を付けて印刷 CSS を発動
    body.setAttribute('data-a4-export', mode);
    // 少し遅延させてブラウザに CSS を適用させてから print()
    setTimeout(function(){
      try { window.print(); } catch(e) { alert('印刷ダイアログを開けませんでした: ' + e); }
      // 印刷後は属性を外す (次に通常表示できるように)
      setTimeout(function(){ body.removeAttribute('data-a4-export'); }, 500);
    }, 150);
  }

  // ツールバーへのボタン追加 (SlideKit の #seSave の下に置く)
  function setupButtons(){
    // ?hideUI=1 の場合は追加しない (投影/プレゼン中は不要)
    var params = new URLSearchParams(location.search);
    if (params.get('hideUI') === '1' || params.get('present') === '1') return;

    // 対象スライドが 1 枚も無ければスキップ
    if (!document.querySelector('.slide')) return;

    // SlideKit のツールバー (#seSave を含む .seui bar) を探して、その下にボタンを足す
    var seSave = document.getElementById('seSave');
    var bar = seSave ? seSave.parentElement : null;
    if (!bar) return;

    // A4 エクスポート専用のミニパネル (SlideKit の bar 内に追加)
    var a4Group = document.createElement('div');
    a4Group.className = 'seui _a4_group';
    a4Group.style.cssText = 'display:flex;flex-direction:column;gap:3px;margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,.12)';

    var label = document.createElement('div');
    label.textContent = '📄 A4縦PDF出力';
    label.style.cssText = 'color:#cdd9e5;font:600 10px/1.2 sans-serif;letter-spacing:.5px;padding:2px 0 4px 0';
    a4Group.appendChild(label);

    var btn1up = document.createElement('button');
    btn1up.textContent = '1スライド/1ページ';
    btn1up.title = 'スライド1枚をA4縦1ページの上部に配置 (下部空白でメモ欄に)';
    btn1up.style.cssText = 'padding:5px 8px;border:none;border-radius:4px;background:#4a6fa5;color:#fff;font-size:11px;cursor:pointer;text-align:center;white-space:nowrap';
    btn1up.addEventListener('click', function(){ exportA4('1up'); });
    a4Group.appendChild(btn1up);

    var btn2up = document.createElement('button');
    btn2up.textContent = '2スライド/1ページ';
    btn2up.title = '配布資料向け (PowerPoint 配布資料 2 スライド相当)';
    btn2up.style.cssText = 'padding:5px 8px;border:none;border-radius:4px;background:#4a6fa5;color:#fff;font-size:11px;cursor:pointer;text-align:center;white-space:nowrap';
    btn2up.addEventListener('click', function(){ exportA4('2up'); });
    a4Group.appendChild(btn2up);

    bar.appendChild(a4Group);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupButtons);
  } else {
    // slide-edit.js の後に読み込まれることが多いので即実行 (setTimeout 少し遅延)
    setTimeout(setupButtons, 50);
  }
})();
