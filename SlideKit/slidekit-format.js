// slidekit-format.js — SlideKit v2 フォーマット描画エンジン
// AWSオーバーレイ・パレット置換・暗色判定を一本化し、slide-edit.js と slide-present.js の
// 両方から window.SlideKitFormat として使う。定義値は slidekit-defs.js (window.SLIDEKIT_DEFS) を参照。
// ビルドなし・file:// でも動く素のスクリプト。defs 未ロードでも読み込み自体は失敗しない。
(function(){
  'use strict';

  // ---- スクリプト自身のディレクトリをロード時に確定 ----
  // 動的 <script> 挿入後は document.currentScript が null になるため、ここ（評価時）で捕捉する。
  // v1 の AWS_LOGO_SRC（slide-edit.js）と同じ手法: 自分の src から slidekit-format.js 部分を除いた残りがディレクトリ。
  var SCRIPT_DIR = (function(){
    var s = document.currentScript || document.querySelector('script[src*="slidekit-format"]');
    if (s) {
      var src = s.getAttribute('src');
      if (src) return src.replace(/slidekit-format\.js.*$/, '');
    }
    return ''; // 特定不可 → カレント相対
  })();

  // ---- defs 参照ヘルパ ----
  function defs(){ return window.SLIDEKIT_DEFS || null; }

  // ---- フォーマットプラグインの共通マージ ----
  // slidekit-aws.js 等のプラグインは自己登録 (window.SLIDEKIT_DEFS.formats へ) を試みるが、
  // <script> のロード順は保証されない (プラグインが defs より先に評価されるケース)。
  // そのためローダの完了コールバックからこれを1回呼び、window.SLIDEKIT_AWS が居れば
  // defs.formats へマージする。プラグイン自身の register() と二重に走っても同値上書きで冪等。
  // 事後条件: 戻り値はマージを実行したか (defs 未読込・プラグイン不在は false)。
  function registerFormatPlugins(){
    var d = defs();
    if (!d || !d.formats) return false;
    var p = window.SLIDEKIT_AWS;
    if (!p || !p.formats || !p.formats.aws) return false;
    if (p.version !== d.version) console.warn('SlideKitFormat: slidekit-aws.js の version (' + p.version + ') が defs (' + d.version + ') と不一致 (続行)');
    d.formats.aws = p.formats.aws; // 冪等 (同値上書き)
    return true;
  }

  // 輝度しきい値: defs.darkThreshold を参照（defs 欠落時は v1 と同じ 0.5 にフォールバック）
  function darkThreshold(){
    var d = defs();
    return (d && typeof d.darkThreshold === 'number') ? d.darkThreshold : 0.5;
  }

  // ---- 暗色スライド判定 ----
  // v1 slide-present.js 版（最も広い実装: rgb()/rgba() ・computedStyle フォールバック対応）を採用し、
  // slide-edit.js 版が持っていた 3/8桁 hex の展開もマージ（設計書 関数1 の契約どおり）。
  // 事後条件: data-bg-gradient あり → true / 背景色の輝度 < darkThreshold → true / それ以外 false。
  // slideEl への副作用なし。
  function isDarkSlide(slideEl){
    if (!slideEl || !slideEl.getAttribute) return false;
    if (slideEl.getAttribute('data-bg-gradient')) return true;
    var bg = slideEl.getAttribute('data-bg');
    if (!bg && typeof getComputedStyle === 'function') {
      try { bg = getComputedStyle(slideEl).backgroundColor; } catch(_){ bg = null; }
    }
    if (!bg) return false;
    var lum = null;
    // (1) data-bg 形式の hex（3/6/8桁のみ厳密照合。4/5/7桁等の不正値は不一致 → false 側へ）。
    //     3桁は #abc → #aabbcc に展開、8桁は先頭6桁（RGB）を使う
    var mExact = bg.match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/);
    if (mExact) {
      var hx = mExact[1];
      var h = (hx.length === 3) ? (hx[0]+hx[0]+hx[1]+hx[1]+hx[2]+hx[2]) : hx.slice(0, 6);
      var r = parseInt(h.slice(0,2),16), g = parseInt(h.slice(2,4),16), b = parseInt(h.slice(4,6),16);
      lum = (0.299*r + 0.587*g + 0.114*b) / 255;
    }
    // (2) 6桁 hex を含む文字列（v1 slide-present.js と同じ緩い照合。computedStyle 経由等）
    if (lum === null) {
      var m6 = bg.match(/#([0-9a-fA-F]{6})/);
      if (m6) {
        var r6 = parseInt(m6[1].slice(0,2),16), g6 = parseInt(m6[1].slice(2,4),16), b6 = parseInt(m6[1].slice(4,6),16);
        lum = (0.299*r6 + 0.587*g6 + 0.114*b6) / 255;
      }
    }
    // (3) rgb() / rgba() 表記（computedStyle の返り値はこの形式）
    if (lum === null) {
      var mRgb = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (mRgb) {
        lum = (0.299*(+mRgb[1]) + 0.587*(+mRgb[2]) + 0.114*(+mRgb[3])) / 255;
      }
    }
    if (lum === null) return false; // パース不能 → 明色扱い（v1 と同じ）
    return lum < darkThreshold();
  }

  // ---- アセットURL解決 ----
  // slidekit-format.js 自身の src 基準でファイル名を解決する（v1 AWS_LOGO_SRC と同じ手法）。
  // 事後条件: SCRIPT_DIR + filename（ディレクトリ不明時は filename そのまま = カレント相対）。
  function resolveAssetUrl(filename){
    return SCRIPT_DIR + filename;
  }

  // ---- HTML エスケープ (innerHTML に埋めるテキスト用) ----
  function escHtml(s){
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ---- AWS Cover 文字色リマップ <style> の注入 ----
  // defs.formats.aws.coverRemap（唯一の正本）から CSS を機械生成して <head> に1回だけ注入する。
  // v1 では slide-edit.js / slide-present.js がそれぞれ手書き CSS を持っていた（6色のみ・二重管理）。
  // v2 はリマップ表から生成するため、defs に色を足すだけで hex/rgb/data-color の全パターンが揃う。
  // v1 に無かった3色 (#a0aec0/#e8f1f7/#f0f5fa) もカバーされる = プレビューが PPTX 出力に揃う意図的修正。

  // hex 検証: ^#[0-9a-f]{3,6}$（小文字正規化後）。defs 手編集ミスによる CSS インジェクションを遮断する。
  var HEX_RE = /^#[0-9a-f]{3,6}$/;

  // hex → [r,g,b]。3桁は #abc → #aabbcc に展開、6桁はそのまま。
  // 4/5桁は検証は通るが RGB に展開できないため null を返す（rgb() セレクタのみ省略）。
  function hexToRgb(hex){
    var h = hex.slice(1);
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    if (h.length !== 6) return null;
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
  }

  // 事前条件: SLIDEKIT_DEFS.formats.aws.coverRemap が読めること（欠落時は WARN のみで注入しない）。
  // 事後条件: document.getElementById(styleId) が存在（冪等: 既存なら何もしない）。
  //   生成 CSS は各エントリ (old → new) につき次の3セレクタを含む（v1 の手書きルールと同形式）:
  //     .aws-cover .tb[data-color="{old}"]            … data-color 属性
  //     .aws-cover .tb[style*="color:{old}"]          … インライン style の hex（"color:" 直後スペースなし = v1 準拠）
  //     .aws-cover .tb[style*="rgb({r}, {g}, {b})"]   … ブラウザ正規化後の rgb() 表記（カンマ後スペースあり = v1 準拠)
  //   いずれも {color:{new} !important}。style 要素の class に uiClass が付く（保存時サニタイズで除去される）。
  // ループ不変条件: 生成途中の rules は常に「処理済みエントリの全ルール」を含む。

  // 注入済みリマップ style の id を追跡する (removeAwsOverlay が除去するため)。
  // v1 では style は保存時サニタイズ任せだったが、v2 は removeAwsOverlay でも掃除できるようにする。
  var _remapStyleIds = {};

  function ensureCoverRemapStyle(styleId, uiClass){
    _remapStyleIds[styleId] = true; // 既存でも追跡 (再適用後の除去に備える)
    if (document.getElementById(styleId)) return; // 冪等: 注入済みなら何もしない
    var d = defs();
    var remap = d && d.formats && d.formats.aws && d.formats.aws.coverRemap;
    if (!remap) {
      console.warn('SlideKitFormat: defs.formats.aws.coverRemap が読めないためリマップ style を注入しない');
      return;
    }
    var rules = [];
    for (var oldRaw in remap) {
      if (!Object.prototype.hasOwnProperty.call(remap, oldRaw)) continue;
      // 小文字正規化してから検証（不正値は WARN + スキップ = CSS に埋め込まない）
      var oldHex = String(oldRaw).toLowerCase();
      var newHex = String(remap[oldRaw]).toLowerCase();
      if (!HEX_RE.test(oldHex) || !HEX_RE.test(newHex)) {
        console.warn('SlideKitFormat: coverRemap の不正な hex をスキップ: ' + oldRaw + ' → ' + remap[oldRaw]);
        continue;
      }
      var decl = '{color:' + newHex + ' !important}';
      rules.push('.aws-cover .tb[data-color="' + oldHex + '"]' + decl);
      rules.push('.aws-cover .tb[style*="color:' + oldHex + '"]' + decl);
      var rgb = hexToRgb(oldHex);
      if (rgb) rules.push('.aws-cover .tb[style*="rgb(' + rgb[0] + ', ' + rgb[1] + ', ' + rgb[2] + ')"]' + decl);
    }
    var st = document.createElement('style');
    st.id = styleId;
    st.className = uiClass || ''; // 保存時サニタイズが uiClass を目印に除去する
    st.textContent = rules.join('\n');
    document.head.appendChild(st);
  }

  // ---- AWS オーバーレイ描画 ----
  // v1 slide-edit.js の awsOverlayCreate を移設。coverBg(光彩5層)/bandGradient/copyright は
  // defs.formats.aws を参照し、uiClass はハードコード('seui')をやめ opts.uiClass で受ける
  // (編集側='seui' / プレゼン側='_sp_ui')。DOM 構造・inline style は v1 と同一 = 見た目等価。
  // 保存時契約: 追加ノードは全て uiClass を持つ → sanitizeSlide('save') の .seui 一括除去で消える。
  //   スライドに付ける .aws-cover クラスは uiClass 系ではないため、v1 同様
  //   awsOverlayRemove(=removeAwsOverlay)/sanitizeSlide('sync') が明示的に外す。

  // 事前条件: slideEl は .slide 要素。defs (formats.aws) ロード済み。
  // 事後条件:
  //   - 冪等: .aws-overlay が既にあれば何もしない
  //   - data-aws-logo="off" なら何もしない
  //   - 暗色(表紙): coverBg 背景層 + .aws-cover クラス + リマップ style 注入 + 大ロゴ + コピーライト
  //   - 明色: 左端バンド + フッター(小ロゴ + コピーライト)
  //   - 追加 DOM は全て opts.uiClass のクラスを持つ / data-* 属性・本文 DOM は不変更
  function applyAwsOverlay(slideEl, opts){
    if (!slideEl || !slideEl.querySelector) return;
    opts = opts || {};
    var ui = opts.uiClass || 'seui';
    if (slideEl.querySelector('.aws-overlay')) return; // 冪等: すでにある
    // 個別スライドで AWS ロゴを外したい場合 (中表紙など): data-aws-logo="off" で無効化
    if (slideEl.getAttribute && slideEl.getAttribute('data-aws-logo') === 'off') return;
    var d = defs();
    var aws = d && d.formats && d.formats.aws;
    if (!aws) {
      console.warn('SlideKitFormat: defs.formats.aws が読めないため AWS オーバーレイを適用しない');
      return;
    }
    // ロゴ解決の優先順: opts.logoUrl → プラグイン内包の logoSvg (data URI 化) → 同ディレクトリの svg ファイル
    // (v2 プラグイン分離後の正本は formats.aws.logoSvg。ファイル解決は旧配布との互換フォールバック)
    var logoUrl = opts.logoUrl
      || (aws.logoSvg ? 'data:image/svg+xml;utf8,' + encodeURIComponent(aws.logoSvg) : resolveAssetUrl('aws-ps-logo.svg'));
    // ロゴ脇キャプション: formats.aws.logoCaption ("\n" 区切り) から生成 (データ駆動が正本・ハードコードしない)。
    // innerHTML に埋めるため各行を HTML エスケープする (defs/プラグイン手編集ミスによる注入を遮断)
    var caption = String(aws.logoCaption || '').split('\n').map(escHtml).join('<br class="' + ui + '">');
    var dark = isDarkSlide(slideEl);
    // v1 準拠の固定色 (ライト/ダークで同値なのも v1 のまま)
    var textColor = '#252f3e';
    var crColor = '#64748b';
    if (dark) {
      // 表紙: 明るい背景 + パステルの光彩を配置 (AWSテンプレそのまま)
      var bg = document.createElement('div');
      bg.className = ui + ' aws-overlay aws-cover-bg';
      bg.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:0;background:'
        + (aws.coverBg || []).join(',');
      if (slideEl.firstChild) slideEl.insertBefore(bg, slideEl.firstChild); else slideEl.appendChild(bg);
      // 明るい背景では HTML の白文字が見えなくなるので、暗色にリマップする CSS を注入
      // (PPTX 側の _AWS_COVER_COLOR_REMAP と同じ defs.coverRemap を CSS 経由で適用)
      slideEl.classList.add('aws-cover');
      ensureCoverRemapStyle(ui + '-aws-cover-style', ui); // ui='seui' なら v1 と同一 id
    }
    var ov = document.createElement('div');
    ov.className = ui + ' aws-overlay';
    ov.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:2';
    // 左端グラデーション帯 (コンテンツスライド用) ※dark 時は cover-bg で塗るので不要
    if (!dark) {
      var band = document.createElement('div');
      band.className = ui;
      band.style.cssText = 'position:absolute;left:0;top:0;width:6px;height:100%;background:' + (aws.bandGradient || '');
      ov.appendChild(band);
    }
    if (dark) {
      // AWS 表紙: 左上にロゴ+キャプション (黒テキスト)、下部中央にコピーライト
      var bigLogo = document.createElement('div');
      bigLogo.className = ui;
      bigLogo.style.cssText = 'position:absolute;left:44px;top:44px;display:flex;align-items:center;gap:16px';
      // professional/services はロゴから少し右に離し(gap:16px)、テキストを 5px 上げて
      // aws ワードマーク(スウォッシュを除いた実体)の上下中央付近に寄せる(position:relative;top:-5px)
      bigLogo.innerHTML = '<img class="' + ui + '" src="' + logoUrl + '" style="height:44px;width:auto;display:block">'
        + '<span class="' + ui + '" style="font-size:14px;color:#252f3e;line-height:1.15;font-family:sans-serif;font-weight:400;position:relative;top:-5px">' + caption + '</span>';
      ov.appendChild(bigLogo);
      var cr = document.createElement('div');
      cr.className = ui;
      cr.textContent = aws.copyright || '';
      cr.style.cssText = 'position:absolute;bottom:12px;left:0;right:0;text-align:center;font-size:10px;color:' + crColor + ';font-family:sans-serif';
      ov.appendChild(cr);
    } else {
      // コンテンツ: 下部フッター (小ロゴ + "professional/services" + コピーライト)
      var foot = document.createElement('div');
      foot.className = ui;
      foot.style.cssText = 'position:absolute;bottom:0;left:0;right:0;height:44px;display:flex;align-items:center;padding:0 60px 0 36px';
      var logo = document.createElement('div');
      logo.className = ui;
      // 表紙の大ロゴと同じバランス。ロゴが小さい(28px/11px)ぶん縮尺: 右の間隔 margin-left:11px、
      // テキストを 3px 上げて aws ワードマークの上下中央付近に寄せる。
      logo.innerHTML = '<img class="' + ui + '" src="' + logoUrl + '" style="height:28px;width:auto;display:block"><span class="' + ui + '" style="font-size:11px;color:' + textColor + ';margin-left:11px;line-height:1.3;font-family:sans-serif;position:relative;top:-3px">' + caption + '</span>';
      logo.style.cssText = 'display:flex;align-items:center';
      foot.appendChild(logo);
      var crL = document.createElement('div');
      crL.className = ui;
      crL.textContent = aws.copyright || '';
      crL.style.cssText = 'flex:1;text-align:center;font-size:10px;color:' + crColor + ';font-family:sans-serif';
      foot.appendChild(crL);
      ov.appendChild(foot);
    }
    slideEl.appendChild(ov);
    // v1 準拠: .slide が static なら relative に (通常はテンプレ CSS で relative 済みのため発火しない)
    if (typeof getComputedStyle === 'function' && getComputedStyle(slideEl).position === 'static') {
      slideEl.style.position = 'relative';
    }
  }

  // ---- AWS オーバーレイ除去 ----
  // v1 slide-edit.js の awsOverlayRemove を移設し、対象を rootEl (document または任意のコンテナ) に
  // 一般化。オーバーレイノード(.aws-overlay)と .aws-cover クラスを除去する。
  // リマップ <style> は「document 上に .aws-cover が1枚も残っていない時」だけ除去する
  // (スライド単位の部分除去で他の表紙の文字色が崩れないようにするため)。
  // 事後条件: rootEl 配下に .aws-overlay ノードなし / .aws-cover クラスなし。
  function removeAwsOverlay(rootEl){
    var root = rootEl || document;
    if (root.querySelectorAll) {
      root.querySelectorAll('.aws-overlay').forEach(function(e){ e.remove(); });
      // .aws-cover クラスは表紙リマップ用に付けたので削除
      root.querySelectorAll('.aws-cover').forEach(function(s){ s.classList.remove('aws-cover'); });
    }
    // rootEl 自身が .slide.aws-cover の場合 (querySelectorAll は自分自身を含まない)
    if (root.classList && root.classList.contains('aws-cover')) root.classList.remove('aws-cover');
    // 注入済みリマップ style の掃除 (document 全体から .aws-cover が消えた時だけ)
    if (!document.querySelector('.aws-cover')) {
      for (var id in _remapStyleIds) {
        var st = document.getElementById(id);
        if (st) st.remove();
        delete _remapStyleIds[id];
      }
    }
  }

  // ---- パレット一括置換 ----
  // v1 slide-edit.js の applyPaletteSwap / revertPaletteSwap を移設 (Task 3.4)。
  // 置換ロジック (data-color / data-fill / style 内 hex・rgb() / 表セル th,td) は v1 と同一。
  // v1 との責務分担の違い (設計書どおり):
  //   - undo 統合 (pushAttr) と dirty フラグは呼び出し側 (slide-edit.js) の責務のまま
  //     → 呼び出し側は戻り値 snapshot.records の el を使って pushAttr できる
  //   - 「置換対象なし」の通知 (v1 は alert) も呼び出し側の責務 → 対象なしは null を返す

  // hex → 'rgb(r, g, b)' 文字列 (v1 hexToRgbStr と同一。#abc は #aabbcc に展開)。
  // パース不能 (# 無し・16進でない) は null。
  function hexToRgbStr(hex){
    if (!hex || hex[0] !== '#') return null;
    var h = hex.length === 4 ? (hex[1]+hex[1]+hex[2]+hex[2]+hex[3]+hex[3]) : hex.slice(1, 7);
    var r = parseInt(h.slice(0,2),16), g = parseInt(h.slice(2,4),16), b = parseInt(h.slice(4,6),16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return null;
    return 'rgb(' + r + ', ' + g + ', ' + b + ')';
  }

  // 正規表現メタ文字のエスケープ (v1 のインライン式を関数化。挙動同一)
  function escRe(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // 事前条件: map は { 旧hex: 新hex } (大文字小文字は吸収)。
  // 事後条件: document 内の該当要素の data-color / data-fill / style (hex・rgb() 両表記) を書換。
  //   戻り値は復元用スナップショット { records: [{el, color, fill, style}] }。対象なしは null。
  function applyPalette(map){
    // 色マップは大文字/小文字を吸収
    var norm = {};
    for (var k in map) { norm[k.toLowerCase()] = String(map[k]).toLowerCase(); }
    // 影響を受けるすべての要素を収集 (data-color / data-fill / style を持つもの)
    var affected = new Set();
    document.querySelectorAll('[data-color],[data-fill],[style]').forEach(function(el){
      var dc = (el.getAttribute('data-color') || '').toLowerCase();
      var df = (el.getAttribute('data-fill') || '').toLowerCase();
      var st = (el.getAttribute('style') || '').toLowerCase();
      if (dc in norm) affected.add(el);
      if (df in norm) affected.add(el);
      for (var key in norm) {
        if (st.indexOf(key) >= 0) { affected.add(el); break; }
        // rgb 表記もチェック
        var rgb = hexToRgbStr(key);
        if (rgb && st.indexOf(rgb) >= 0) { affected.add(el); break; }
      }
    });
    // 表セル(th/td)も個別対象 (親tableは対象、子セルは style で書き換えが必要)
    document.querySelectorAll('table th,table td').forEach(function(c){
      var st = (c.getAttribute('style') || '').toLowerCase();
      for (var key in norm) {
        if (st.indexOf(key) >= 0) { affected.add(c); break; }
        var rgb = hexToRgbStr(key);
        if (rgb && st.indexOf(rgb) >= 0) { affected.add(c); break; }
      }
    });
    if (!affected.size) return null; // v1 は alert('置換対象なし')。通知は呼び出し側の責務
    var affArr = Array.from(affected);
    // 「なし」に戻した時の復元用に、変換前の色属性を保存 (v1 paletteSnapshot と同形式)
    var snapshot = { records: affArr.map(function(el){ return {
      el: el,
      color: el.getAttribute('data-color'),
      fill: el.getAttribute('data-fill'),
      style: el.getAttribute('style')
    }; }) };
    // 書き換え (v1 と同一ロジック)
    affected.forEach(function(el){
      // data-color
      var dc = (el.getAttribute('data-color') || '').toLowerCase();
      if (dc in norm) el.setAttribute('data-color', norm[dc]);
      // data-fill
      var df = (el.getAttribute('data-fill') || '').toLowerCase();
      if (df in norm) el.setAttribute('data-fill', norm[df]);
      // style
      var st = el.getAttribute('style');
      if (st) {
        for (var key in norm) {
          var v = norm[key];
          // hex 表記
          st = st.replace(new RegExp(escRe(key), 'gi'), v);
          // rgb() 表記 (v1 準拠: エスケープ後に空白を \s* 化してスペース揺れを吸収)
          var rgbOld = hexToRgbStr(key), rgbNew = hexToRgbStr(v);
          if (rgbOld && rgbNew) {
            st = st.replace(new RegExp(escRe(rgbOld).replace(/\s/g, '\\s*'), 'gi'), rgbNew);
          }
        }
        el.setAttribute('style', st);
      }
    });
    return snapshot;
  }

  // パレット変換を巻き戻す (「なし」に戻す時)。
  // 事前条件: snapshot は applyPalette の戻り値。
  // 事後条件: 各 record の el が接続中なら変換前の属性値に復元 (null は removeAttribute)。
  //   undo 統合 (v1 は復元前に pushAttr(els)) は呼び出し側の責務。
  function revertPalette(snapshot){
    if (!snapshot || !snapshot.records) return;
    snapshot.records.forEach(function(r){
      if (!r.el || !r.el.isConnected) return;
      // 変換前の値に戻す (null は removeAttribute)
      if (r.color != null) r.el.setAttribute('data-color', r.color); else r.el.removeAttribute('data-color');
      if (r.fill != null) r.el.setAttribute('data-fill', r.fill); else r.el.removeAttribute('data-fill');
      if (r.style != null) r.el.setAttribute('style', r.style); else r.el.removeAttribute('style');
    });
  }

  // ---- 公開 API ----
  window.SlideKitFormat = {
    registerFormatPlugins: registerFormatPlugins,
    isDarkSlide: isDarkSlide,
    resolveAssetUrl: resolveAssetUrl,
    ensureCoverRemapStyle: ensureCoverRemapStyle,
    applyAwsOverlay: applyAwsOverlay,
    removeAwsOverlay: removeAwsOverlay,
    applyPalette: applyPalette,
    revertPalette: revertPalette
  };
})();
