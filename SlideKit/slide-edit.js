/* ============================================================
   SlideKit / slide-edit.js  ── PPTXスライド編集スニペット（標準・再利用版）
   ------------------------------------------------------------
   data属性ベースのスライドHTML（slide-html-to-pptx.md準拠）に1行で載せる編集機能。
   <body>末尾の </body> 直前に次の1行を置くだけ：
       <script src="../SlideKit/slide-edit.js"></script>
   （HTMLからの相対パスで指定。ワークスペース直下配信なら ../SlideKit/ 等）

   含まれる機能（閲覧が既定・右上「✏️編集」でON）：
   - ページ番号の自動採番（.slide を順に走査し右下に連番）
   - 要素の移動 / リサイズ / 矢印キー微調整 / 複数選択(Shift) / グループ移動・同倍率リサイズ
   - ⌘Z 取り消し / 画像・表の挿入(ボタン＋ドロップ) / Delete で挿入物削除
   - 🎯選択中パネル：文字色 / 背景色 / フォントサイズ / 太字 / 箇条書き(・①②③・ぶら下げ字下げ) / 整列
   - 🎨カラーパレット：バッジ/タイトル/サブ/本文/カード/赤 を全スライド一括置換
   - 📄ページ操作：ページ枠クリックで選択 → 複製 / 追加 / 並べ替え / 削除 / 背景色
   - 📤Kiroへ渡す：移動・編集・色・箇条書き・ページ操作を「Kiro貼付用パッチ」として出力（旧「📋変更をコピー」）
   - 📍場所をKiroへ：選択オブジェクトの位置ID＋outerHTMLをコピー（旧「📍参照」。"これを表にして"等の指示用）
   - 🎯選択中パネル先頭：⧉複製(⌘D) / 📋コピー(⌘C) / 🗑削除 ＝選択物そのものへの操作。貼付(⌘V)はツールバーの📋貼付
   - 💾保存：編集UIを除いたクリーンHTMLをダウンロード（ページ番号は除去＝再オープン時に再採番）

   localStorageに保存しない＝HTML本体が唯一の正本（Kiroの編集と衝突しない）。
   ============================================================ */
/* スライド編集スニペット（案B＋）：閲覧が既定、✏️で編集ON。
   移動/リサイズ/矢印キー/複数選択(Shift)/グループ移動・同倍率リサイズ/⌘Z取消/画像・表の挿入(ボタン＋ドロップ)/Deleteで挿入物削除。
   全てdata属性へ即書き戻し→「📋変更をコピー」でKiro貼付用パッチ(移動・編集・挿入)を出力。
   localStorageに保存しない＝HTML本体が唯一の正本（Kiro編集と衝突しない）。 */
(function(){
  // ============================================================
  // v2 起動シーケンス (Requirements 4.1, 4.2):
  //   1. loadSlideKitDeps() が slidekit-defs.js / slidekit-format.js を
  //      自分の src 基準で動的ロードする (既存デッキの1行導入は不変)
  //   2. ロード完了(または失敗)後に init() で従来どおり初期化する
  //      (v1 はパース時に即初期化。スクリプトは </body> 直前配置が前提で DOM は
  //       構築済みのため、念のため readyState を確認してから実行する = 挙動同等)
  //   3. ロード失敗時も編集機能は通常起動し、📐フォーマットのみ無効化して ⚠️ 表示
  // ============================================================

  // defs/format が使えるか (ローダ完了時に確定。失敗時は 📐フォーマットのみ無効化)
  let fmtReady=false;

  // 動的ローダ: 自分の src からディレクトリを推定して defs/format を <script> でロードする。
  // 既に window に載っていればスキップ。onerror でも必ず done() を1回呼ぶ (起動を止めない)。
  function loadSlideKitDeps(done){
    const me=document.querySelector('script[src*="slide-edit"]');
    const dir=me?(me.getAttribute('src')||'').replace(/slide-edit\.js.*$/,''):'';
    let remain=3;
    const fin=()=>{if(--remain===0)done();};
    // slidekit-aws.js は任意のプラグイン (外部配布には同梱されない)。404 は onerror → fin() で正常続行
    [['slidekit-defs.js',()=>window.SLIDEKIT_DEFS],['slidekit-format.js',()=>window.SlideKitFormat],['slidekit-aws.js',()=>window.SLIDEKIT_AWS]].forEach(([f,has])=>{
      if(has()){fin();return;}
      const s=document.createElement('script');
      s.className='seui'; // 保存時に外す（開くたびに読み込み直す。以前は保存のたびに head に溜まった・2026-09-27）
      s.src=dir+f;
      s.onload=fin;
      s.onerror=()=>{console.warn('SlideKit: '+f+' 読込失敗 ('+s.src+')');fin();};
      document.head.appendChild(s);
    });
    // プレゼン再生（slide-present.js）も自動で読み込む。デッキ側に読み込み行が無いと
    // 「📺 プレゼン再生」ボタンが出なかった（2026-09-27 実測で166デッキ中95件）。
    // 待ち合わせには含めない（無くても編集は動く）。二重読み込みは slide-present.js 側で止める
    if(!window.__skPresentLoaded){
          const p=document.createElement('script');
          p.className='seui';
          p.src=dir+'slide-present.js';
          p.onerror=()=>console.warn('SlideKit: slide-present.js 読込失敗 ('+p.src+')');
          document.head.appendChild(p);
        }
        // 発表者ビュー（slide-presenter.js）も自動で読み込む。本窓に「🧑‍🏫 発表者ビュー」ボタンが出る。
        // 二重読み込みは slide-presenter.js 側で止める（__skPresenterLoaded）。
        if(!window.__skPresenterLoaded){
          const pv=document.createElement('script');
          pv.className='seui';
          pv.src=dir+'slide-presenter.js';
          pv.onerror=()=>console.warn('SlideKit: slide-presenter.js 読込失敗 ('+pv.src+')');
          document.head.appendChild(pv);
        }
    // グラフ（data-chart）があるデッキだけ描画スクリプトを読む。PPTXではネイティブグラフになる（2026-10-14）
    if(!window.SlideKitChart&&document.querySelector('[data-chart]')){
      const c=document.createElement('script');
      c.className='seui';
      c.src=dir+'slidekit-chart.js';
      c.onerror=()=>console.warn('SlideKit: slidekit-chart.js 読込失敗 ('+c.src+')');
      document.head.appendChild(c);
    }
  }

  // ---- hideUI 判定 (Requirements 4.4) ----
  // 投影コンソール(teacher-console-v3.html)やプレゼン窓は iframe/window URL に `?hideUI=1` を付ける。
  // v1 はここで early-return して window.SlideKit も未定義のままだった。
  // v2 は「編集 UI (ツールバー/パネル/ハンドラ) の抑止」に限定し、
  // 公開 API (window.SlideKit) の定義とページ自動採番は hideUI でも実行する。
  let HIDE_UI=false,AUTO_EDIT=false;
  try{
    const _params=new URLSearchParams(location.search);
    HIDE_UI=(_params.get('hideUI')==='1'||_params.get('hideUI')==='true');
    // ?edit=1 …プレゼン窓を「編集できる状態」で開く（2026-09-16 利用者要望）。
    //   会議中に指摘されたその場で直せるようにする。hideUI とは併用しない
    AUTO_EDIT=(_params.get('edit')==='1'||_params.get('edit')==='true');
  }catch(_){}

  // 編集内部へのフック。init() 実行時に配線される (hideUI 時は空のまま = 各 API は安全に縮退)
  const _hooks={};

  // ページ番号の文字色。明るい地は #5e5e5e、暗い地（グラデ・暗い単色）は #d4dde7。
  //   旧 #718096 は #fafafa で 3.9:1、#183251 で 3.3:1 と WCAG AA(4.5:1) に届かなかった（2026-10-14 利用者了承）
  //   #a0aec0 はグラデの右下（#21537f）で 3.6:1 なので使わない。#d4dde7 は 5.9:1
  function pagenoColor(s){
    if(s&&s.getAttribute('data-bg-gradient'))return '#d4dde7';
    const m=/^#?([0-9a-f]{6})$/i.exec((s&&s.getAttribute('data-bg'))||'');if(!m)return '#5e5e5e';
    const v=[0,2,4].map(k=>{const c=parseInt(m[1].substr(k,2),16)/255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);});
    return (0.2126*v[0]+0.7152*v[1]+0.0722*v[2])<0.18?'#d4dde7':'#5e5e5e';
  }
  // hideUI 時のページ自動採番 (v1 の early-return 内処理をそのまま関数化。投影で番号が消えないように)
  function autoNumberPages(){
    const _slides=document.querySelectorAll('.slide');
    _slides.forEach((s,i)=>{
      const _pgs=[...s.querySelectorAll(':scope > .tb')].filter(t=>{
        const x=parseInt(t.getAttribute('data-x')||0,10);
        const y=parseInt(t.getAttribute('data-y')||0,10);
        return x>=1180 && y>=660 && /^\d+$/.test((t.textContent||'').trim());
      });
      if(_pgs.length){_pgs.forEach((p,k)=>{if(k===0)p.textContent=i+1;else p.remove();});}
      else{
        const n=document.createElement('div');n.className='tb';
        const pc=pagenoColor(s);
        [['data-x','1205'],['data-y','680'],['data-w','60'],['data-h','32'],['data-font-size','21'],['data-color',pc],['data-align','right']].forEach(kv=>n.setAttribute(kv[0],kv[1]));
        n.style.cssText='position:absolute;left:1205px;top:680px;width:60px;height:32px;font-size:21px;color:'+pc+';text-align:right';
        n.textContent=i+1;s.appendChild(n);
      }
    });
  }

  // ========================================================================
  // PowerPointネイティブ箇条書き（data-bullet="native-disc" / "native-decimal"）
  // ------------------------------------------------------------------------
  // 構造: <div class="tb" data-bullet="native-disc">
  //         <div class="li" data-lvl="0">親項目</div>
  //         <div class="li" data-lvl="1">子項目</div></div>
  // マーカーは本文に入れず CSS ::before で描く。PPTX側は buChar/buAutoNum が描くので
  // PowerPoint上で Enter（次項目も自動マーカー）・Tab/Shift+Tab（レベル送り）が効く。
  // 旧方式（data-bullet="disc"/"decimal"）はマーカーを本文文字として持つ別方式で、そのまま共存する。
  // レベル定義は slidekit-defs.js の list（PPTX側 html_to_pptx.py と同一の正本）。
  // ========================================================================
  const LIST_CSS_ID='skListCss';
  // defs 読込失敗時のフォールバック（defs.list と同値。ズレたら結合テストで落ちる）
  const LIST_FALLBACK={
    maxLevel:5,
    circledSymbols:'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳',
    kinds:{
      'native-disc':{stepEm:1.4,levels:[{char:'・'},{char:'–'},{char:'·'},{char:'–'},{char:'·'}]},
      'native-decimal':{stepEm:1.9,levels:[
        {autoNum:'circleNumDbPlain',cssStyle:'sk-circled',cssSuffix:' '},
        {autoNum:'arabicParenR',cssStyle:'decimal',cssSuffix:') '},
        {autoNum:'alphaLcParenR',cssStyle:'lower-alpha',cssSuffix:') '},
        {autoNum:'romanLcPeriod',cssStyle:'lower-roman',cssSuffix:'. '},
        {autoNum:'arabicPeriod',cssStyle:'decimal',cssSuffix:'. '}]}
    }
  };
  function listDefs(){
    const d=window.SLIDEKIT_DEFS&&window.SLIDEKIT_DEFS.list;
    return (d&&d.kinds)?d:LIST_FALLBACK;
  }
  function listMaxLevel(){return listDefs().maxLevel||LIST_FALLBACK.maxLevel;}
  function buildListCss(){
    const L=listDefs(),kinds=L.kinds,out=[];
    out.push('/* SlideKit: PowerPointネイティブ箇条書きの表示。PPTX側は buChar/buAutoNum が描く */');
    out.push('@counter-style sk-circled{system:fixed 1;symbols:'
      +String(L.circledSymbols||LIST_FALLBACK.circledSymbols).split('').map(c=>"'"+c+"'").join(' ')+';suffix:""}');
    out.push('.tb[data-bullet^="native-"]{padding-left:0;text-indent:0}');
    out.push('.tb[data-bullet^="native-"] .li{display:block}');
    Object.keys(kinds).forEach(kind=>{
      const k=kinds[kind],step=k.stepEm,levels=k.levels;
      if(levels.some(lv=>lv.autoNum))
        out.push('.tb[data-bullet="'+kind+'"]{counter-reset:'+levels.map((_,i)=>'sk'+i+' 0').join(' ')+'}');
      levels.forEach((lv,i)=>{
        const sel='.tb[data-bullet="'+kind+'"] .li[data-lvl="'+i+'"]';
        let rule=sel+'{padding-left:'+(step*(i+1))+'em;text-indent:-'+step+'em';
        if(lv.autoNum){
          rule+=';counter-increment:sk'+i;
          // 上位レベルが増えたら下位の採番を1に戻す（PowerPointの自動採番と同じ挙動）
          const rest=levels.slice(i+1).map((_,j)=>'sk'+(i+1+j)+' 0').join(' ');
          if(rest)rule+=';counter-reset:'+rest;
        }
        out.push(rule+'}');
        out.push(sel+'::before{content:'+(lv.autoNum
          ?'counter(sk'+i+','+(lv.cssStyle||'decimal')+') "'+(lv.cssSuffix||' ')+'"'
          :'"'+(lv.char||'・')+' "')+'}');
      });
    });
    return out.join('\n');
  }
  // <style> は head に置く＝💾保存したHTMLにも残る（.seui を付けないのでサニタイズで消えない）
  function ensureListCss(){
    if(document.getElementById(LIST_CSS_ID))return;
    const st=document.createElement('style');st.id=LIST_CSS_ID;
    st.textContent=buildListCss();
    (document.head||document.documentElement).appendChild(st);
  }
  function ensureListCssIfUsed(){
    if(document.querySelector('.tb[data-bullet^="native-"]'))ensureListCss();
  }

  // ========================================================================
  // 公開 API: 外部ツール (slide-present.js 等) から状態操作するための正規窓口
  // ========================================================================
  // Escape キー合成のような間接操作を減らすことで、edit.js の内部変更に対する
  // 脆さを取り除く。ここに列挙した関数だけを外部から呼ぶ約束にする。
  // v2: hideUI=1 でも定義される (Requirements 4.4)。編集内部状態 (選択・editing) への
  // 依存は _hooks 経由の遅延バインドにし、init() 未実行時は安全に縮退する。
  window.SlideKit = {
    // 全ての要素選択とページ選択を解除 (contenteditable も外す)
    clearSelection: function(){
      try { if(_hooks.clearSel) _hooks.clearSel(); } catch(_){}
      try { if(_hooks.clearPageSel) _hooks.clearPageSel(); } catch(_){}
      // フォーカス中の contenteditable も外す
      document.querySelectorAll('.slide [contenteditable="true"]').forEach(function(el){
        el.contentEditable = 'false';
        try { el.blur(); } catch(_){}
      });
    },
    // .slide 内の全要素・全スライドから outline を強制的に消す
    // (プレゼン側にリアルタイム同期する時、選択枠が漏れないようにするため)
    stripAllOutlines: function(root){
      var scope = root || document;
      scope.querySelectorAll('.slide, .slide [data-x], .slide img').forEach(function(el){
        if (el.style && el.style.outline) {
          el.style.outline = '';
          el.style.outlineOffset = '';
        }
      });
    },
    // 現在の編集モード状態を返す (プレゼン側が判定に使う)
    isEditing: function(){
      try { return !!(_hooks.isEditing && _hooks.isEditing()); } catch(_) { return false; }
    },
    // 統一サニタイズ (実体は下の _sanitizeSlide。init() 不要の純 DOM 処理)
    sanitizeSlide: function(el, mode){ return _sanitizeSlide(el, mode); },
    // v2 追加 (Requirements 4.5): 現在の data-template フォーマットを指定スライド群へ適用する窓口。
    // slides 省略時は document 内の全 .slide。AWS 以外のフォーマット (palette 系) は
    // 保存 HTML に色が焼き込まれているため、ここで再適用するものは無い。
    applyFormat: function(slides, opts){
      var list = slides ? Array.prototype.slice.call(slides) : Array.prototype.slice.call(document.querySelectorAll('.slide'));
      var html = document.documentElement;
      var isAws = html.getAttribute('data-template') === 'aws' || html.getAttribute('data-aws-decoration') === 'on';
      if (!isAws || !window.SlideKitFormat) return;
      var ui = (opts && opts.uiClass) || 'seui';
      list.forEach(function(s){ window.SlideKitFormat.applyAwsOverlay(s, { uiClass: ui }); });
    }
  };

  function init(){
  // 編集UIの初期化。hideUI=1 (投影コンソール/プレゼン窓) では init() 自体を呼ばず、
  // ページ自動採番 (autoNumberPages) と公開 API (window.SlideKit) だけが効く (Requirements 4.4)。
  const SEL='[data-x],.slide img';
  let editing=false,sels=[],act=null,sx=0,sy=0,bases=[],g0=null,placing=null,ghost=null,activeZone=null,pendingZone=null,rzMode=null,marqMoved=false;
  let cellSel=[],cellTable=null,cellAnchor=null;
  let dirty=false; // 保存していない編集があるか
  let colT=null,colIdx=-1,colBaseW=0,rowTr=null,rowBaseH=0,bdColor='#d7dde3'; // 表の列幅/行高ドラッグ・枠線色
  const orig=new Map(),txt0=new Map(),undo=[],redo=[],pageLog=[];
  let layerLog=[];
  const N=v=>parseFloat(v||'0'), A=(el,k)=>el.getAttribute(k);
  const allSlides=()=>Array.from(document.querySelectorAll('.slide'));
  // 図形・整列系の追加監視属性（「変更をコピー」の差分検出対象。帯矢印の尖り等もここで拾う）
  const EXATTRS=['data-cv','data-at','data-ah','data-radius','data-border','data-align','data-valign','data-rotate','data-flip','data-bx','data-link-sid'];
  function snapExtra(el){const o={};EXATTRS.forEach(k=>{o[k]=(el.getAttribute&&el.getAttribute(k))||'';});return o;}
  function baseSnap(el){if(!orig.has(el))orig.set(el,{x:N(A(el,'data-x')),y:N(A(el,'data-y')),w:N(A(el,'data-w')),h:N(A(el,'data-h')),fs:N(A(el,'data-font-size')),col:elTextHex(el),fill:elFillHex(el),bold:A(el,'data-bold')==='1'?1:0,bullet:A(el,'data-bullet')||'',lvls:liLvlsStr(el),extra:snapExtra(el)});if(!txt0.has(el))txt0.set(el,el.innerHTML.trim());}
  // ネイティブ箇条書きの階層列（"0,1,0"）。📋変更をコピーでレベル送りを報告するために持つ
  function liLvlsStr(el){if(!el.querySelectorAll)return '';const lis=Array.from(el.children||[]).filter(c=>c.classList&&c.classList.contains('li'));return lis.map(c=>c.getAttribute('data-lvl')||'0').join(',');}
  function setX(el,x){x=Math.round(x);el.setAttribute('data-x',x);el.style.left=x+'px';}
  function setY(el,y){y=Math.round(y);el.setAttribute('data-y',y);el.style.top=y+'px';}
  function setW(el,w){w=Math.round(w);el.setAttribute('data-w',w);el.style.width=w+'px';}
  function setH(el,h){h=Math.round(h);if(!el.hasAttribute('data-h')){el.setAttribute('data-h',h);}else{el.setAttribute('data-h',h);}el.style.height=h+'px';}
  function setFS(el,fs){if(!el.classList.contains('tb'))return;fs=Math.max(8,Math.round(fs*100)/100);el.setAttribute('data-font-size',fs);el.style.fontSize=fs+'px';if(typeof updateNoteFsBar==='function')updateNoteFsBar();}
  // 回転（data-rotate 度・時計回り・中心基準）と反転（data-flip h/v/hv）を transform に合成する。
  // CSSは右側から適用されるので rotate()→scale() の並び＝「反転してから回転」＝PPTXのxfrm(rot+flipH/V)と同じ
  function applyTransform(el){
    const r=N(A(el,'data-rotate'))||0;
    const f=A(el,'data-flip')||'';
    let t='';
    if(r)t+='rotate('+r+'deg)';
    if(f.indexOf('h')>=0)t+=' scaleX(-1)';
    if(f.indexOf('v')>=0)t+=' scaleY(-1)';
    el.style.transform=t.trim();
    // PowerPointは図形を反転しても文字を鏡文字にしないので、直下の.tbを逆反転して合わせる
    if(el.querySelectorAll&&el.classList&&!el.classList.contains('tb')){
      el.querySelectorAll(':scope > .tb').forEach(c=>{
        let ct='';
        if(f.indexOf('h')>=0)ct+='scaleX(-1)';
        if(f.indexOf('v')>=0)ct+=' scaleY(-1)';
        c.style.transform=ct.trim();
      });
    }
  }
  function setRot(el,deg){deg=Math.round(((deg%360)+360)%360);if(deg===0)el.removeAttribute('data-rotate');else el.setAttribute('data-rotate',deg);applyTransform(el);}
  function setFlip(el,axis){ // axis='h'|'v' をトグル
    let f=A(el,'data-flip')||'';
    f=f.indexOf(axis)>=0?f.replace(axis,''):f+axis;
    f=(f.indexOf('h')>=0?'h':'')+(f.indexOf('v')>=0?'v':'');
    if(f)el.setAttribute('data-flip',f);else el.removeAttribute('data-flip');
    applyTransform(el);
  }
  function setBold(el,on){if(!el.classList.contains('tb'))return;if(on){el.setAttribute('data-bold','1');el.style.fontWeight='700';}else{el.removeAttribute('data-bold');el.style.fontWeight='400';}}

  // ---- undo ----
  // Undo用スナップショット。data-*は丸ごと記録する（個別記録だと「元々無かった属性」を
  // Undoで消せず残留し、保存時の正規化で復活するバグの元）。data-skidは親子リンク参照のため対象外
  function rec(el){const dattrs={};for(const a of el.attributes){if(a.name.indexOf('data-')===0&&a.name!=='data-skid')dattrs[a.name]=a.value;}return {el,dattrs,html:el.innerHTML,style:el.getAttribute('style')};}
  // 新規操作を積む時は redo履歴をクリア（標準的な undo/redo 挙動）
  function pushAttr(list){list.forEach(el=>{try{baseSnap(el);}catch(_){}});undo.push({type:'attr',items:list.map(rec)});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}
  function pushAdd(el){undo.push({type:'add',el});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}
  function pushStyle(el){undo.push({type:'style',el,style:el.getAttribute('style')});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}
  function pushDel(el){undo.push({type:'del',el,parent:el.parentNode,next:el.nextSibling});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}
  // 逆操作を適用しつつ、反対側のスタックに逆情報を積む共通処理
  // fromStack から pop → 現状を snapshot → 元に戻す → toStack に snapshot を積む
  function _applyReverse(fromStack, toStack){
    const e=fromStack.pop();if(!e)return false;
    if(e.type==='attr'){
      // 現状を snapshot して積む
      const snap={type:'attr', items:e.items.map(it=>rec(it.el))};
      toStack.push(snap);
      e.items.forEach(it=>{
        // data-*を丸ごと復元（現在のdata-*を全部消してから記録時点のものを書き戻す。data-skidは温存）
        [...it.el.attributes].filter(a=>a.name.indexOf('data-')===0&&a.name!=='data-skid').forEach(a=>it.el.removeAttribute(a.name));
        Object.keys(it.dattrs).forEach(k=>it.el.setAttribute(k,it.dattrs[k]));
        it.el.innerHTML=it.html;
        if(it.style!=null)it.el.setAttribute('style',it.style);else it.el.removeAttribute('style');
      });
    }
    else if(e.type==='notes'){
      // 発表者ノート（data-notes）だけを戻す。ページ内の要素には触れない
      toStack.push({type:'notes',el:e.el,v:e.el.getAttribute('data-notes')||''});
      if(e.v)e.el.setAttribute('data-notes',e.v);else e.el.removeAttribute('data-notes');
      if(typeof updateNotesBox==='function')updateNotesBox();
      try{window.dispatchEvent(new CustomEvent('skit:notes',{detail:{slide:e.el}}));}catch(_){}
    }
    else if(e.type==='add'){
      // 追加を取り消す=削除。反対側では「del」として積む
      toStack.push({type:'del', el:e.el, parent:e.el.parentNode, next:e.el.nextSibling});
      e.el.remove();
    }
    else if(e.type==='del'){
      // 削除を取り消す=再挿入。反対側では「add」
      e.parent.insertBefore(e.el, e.next);
      toStack.push({type:'add', el:e.el});
    }
    else if(e.type==='style'){
      // 現在のstyleを snapshot
      const curStyle=e.el.getAttribute('style');
      toStack.push({type:'style', el:e.el, style:curStyle});
      if(e.style!=null)e.el.setAttribute('style', e.style);else e.el.removeAttribute('style');
    }
    else if(e.type==='color'){
      // color置換の逆: (old→new) を (new→old) で戻す。反対側には (old→new)
      applyColor(e.newHex, e.oldHex);
      toStack.push({type:'color', oldHex:e.newHex, newHex:e.oldHex});
    }
    else if(e.type==='slidebg'){
      // 現在の背景を snapshot
      const cur={type:'slidebg', el:e.el, bg:e.el.getAttribute('data-bg'), grad:e.el.getAttribute('data-bg-gradient'), style:e.el.getAttribute('style')};
      toStack.push(cur);
      if(e.bg!=null)e.el.setAttribute('data-bg',e.bg);else e.el.removeAttribute('data-bg');
      if(e.grad!=null)e.el.setAttribute('data-bg-gradient',e.grad);else e.el.removeAttribute('data-bg-gradient');
      if(e.style!=null)e.el.setAttribute('style',e.style);
    }
    else if(e.type==='order'){
      // 現在の順序を snapshot
      const curOrder=[...e.slide.children];
      toStack.push({type:'order', slide:e.slide, order:curOrder});
      e.order.forEach(el=>e.slide.appendChild(el));
    }
    if(toStack.length>60)toStack.shift();
    clearSel();
    dirty=true;
    return true;
  }
  function doUndo(){_applyReverse(undo, redo);}
  function doRedo(){_applyReverse(redo, undo);}

  // ---- selection ----
  function outline(el,on){const c=roleOf(el)?'#1f7a5a':'#e8821a';el.style.outline=on?('2px solid '+c):'';el.style.outlineOffset=on?'1px':'';}
  function clearSel(){if(typeof cellSelClear==='function')cellSelClear();sels.forEach(el=>outline(el,false));sels=[];box.style.display='none';if(typeof updateNoteFsBar==='function')updateNoteFsBar();if(typeof hideGapG==='function')hideGapG();if(typeof tbar!=='undefined'&&tbar)tbar.style.display='none';if(typeof rlabel!=='undefined'&&rlabel)rlabel.style.display='none';if(typeof idlabel!=='undefined'&&idlabel)idlabel.style.display='none';if(typeof updateSelPanel==='function')updateSelPanel();}
  function setSel(arr){sels.forEach(el=>outline(el,false));sels=arr.slice();sels.forEach(el=>{outline(el,true);baseSnap(el);});placeBox();if(typeof updateNoteFsBar==='function')updateNoteFsBar();}
  function toggleSel(el){if(sels.includes(el)){sels=sels.filter(s=>s!==el);outline(el,false);}else{sels.push(el);outline(el,true);baseSnap(el);}placeBox();if(typeof updateNoteFsBar==='function')updateNoteFsBar();}
  function unionRect(){let l=1e9,t=1e9,r=-1e9,b=-1e9;sels.forEach(el=>{const q=el.getBoundingClientRect();l=Math.min(l,q.left);t=Math.min(t,q.top);r=Math.max(r,q.right);b=Math.max(b,q.bottom);});return {l,t,r,b};}
  function placeBox(){if(!sels.length){box.style.display='none';if(typeof hideGapG==='function')hideGapG();if(typeof tbar!=='undefined'&&tbar)tbar.style.display='none';if(typeof rlabel!=='undefined'&&rlabel)rlabel.style.display='none';if(typeof updateSelPanel==='function')updateSelPanel();return;}const u=unionRect();box.style.display='block';box.style.left=(u.l+window.scrollX)+'px';box.style.top=(u.t+window.scrollY)+'px';box.style.width=(u.r-u.l)+'px';box.style.height=(u.b-u.t)+'px';if(typeof tbar!=='undefined'&&tbar){if(sels.length===1&&sels[0].tagName==='TABLE'){tbar.style.display='flex';tbar.style.left=(u.l+window.scrollX)+'px';tbar.style.top=(u.t+window.scrollY-36)+'px';}else tbar.style.display='none';}if(typeof rlabel!=='undefined'&&rlabel){const r=sels.length===1?roleOf(sels[0]):null;if(r){rlabel.textContent='🔗 共通：'+roleName(r)+'（全ページ連動 ／ Optionで単独）';rlabel.style.display='block';rlabel.style.left=(u.l+window.scrollX)+'px';rlabel.style.top=(u.t+window.scrollY-26)+'px';}else rlabel.style.display='none';}if(typeof idlabel!=='undefined'&&idlabel){if(sels.length===1){const el=sels[0];idlabel.textContent=eidStr(el)+' '+el.tagName.toLowerCase()+(el.className?'.'+el.className.split(' ')[0]:'');idlabel.style.display='block';idlabel.style.top=(u.t+window.scrollY-22)+'px';idlabel.style.left=(u.r+window.scrollX-idlabel.offsetWidth)+'px';}else idlabel.style.display='none';}if(typeof drawGapGuides==='function')drawGapGuides();if(typeof updateRotHandle==='function')updateRotHandle();if(typeof updateSelPanel==='function')updateSelPanel();}
  function groupData(){let x=1e9,y=1e9,r=-1e9,b=-1e9;sels.forEach(el=>{const ex=N(A(el,'data-x')),ey=N(A(el,'data-y')),ew=N(A(el,'data-w'))||el.getBoundingClientRect().width,eh=N(A(el,'data-h'))||el.getBoundingClientRect().height;x=Math.min(x,ex);y=Math.min(y,ey);r=Math.max(r,ex+ew);b=Math.max(b,ey+eh);});return {x,y,w:Math.max(1,r-x),h:Math.max(1,b-y)};}
  function targetSlide(){const cy=window.scrollY+window.innerHeight/2;let best=allSlides()[0],bd=1e9;allSlides().forEach(s=>{const r=s.getBoundingClientRect();const c=window.scrollY+r.top+r.height/2;if(Math.abs(c-cy)<bd){bd=Math.abs(c-cy);best=s;}});return best;}
  // 選択オブジェクトの位置ID（何枚目・スライド内何番目のdata-x要素か）
  function sidOf(el){const s=el.closest&&el.closest('.slide');return s?allSlides().indexOf(s)+1:0;}
  function eidxOf(el){const s=el.closest&&el.closest('.slide');return s?[...s.querySelectorAll('[data-x]')].indexOf(el)+1:0;}
  function eidStr(el){return 'S'+sidOf(el)+'#'+eidxOf(el);}

  // ---- 共通要素（バッジ/タイトル/サブタイトル/ページ番号）を自動判別→data-role付与 ----
  function classifyRoles(){
    allSlides().forEach(s=>{
      const rects=[...s.querySelectorAll(':scope > .rect[data-x]')];
      const badge=rects.find(r=>N(A(r,'data-y'))<80);if(badge&&!badge.getAttribute('data-role'))badge.setAttribute('data-role','badge');
      const tbs=[...s.querySelectorAll(':scope > .tb[data-x]')];
      let title=null,mx=0;tbs.forEach(t=>{const y=N(A(t,'data-y')),fs=N(A(t,'data-font-size'));if(y>=70&&y<=135&&fs>mx){mx=fs;title=t;}});
      if(title)title.setAttribute('data-role','title');
      const sub=tbs.find(t=>{const y=N(A(t,'data-y')),fs=N(A(t,'data-font-size'));return t!==title&&y>=130&&y<=182&&fs<=20&&(A(t,'data-color')||'').toLowerCase()==='#5e5e5e';});
      if(sub)sub.setAttribute('data-role','subtitle');
      const pg=tbs.find(t=>N(A(t,'data-x'))>=1180&&N(A(t,'data-y'))>=660&&/^\d+$/.test((t.textContent||'').trim()));
      if(pg)pg.setAttribute('data-role','pageno');
    });
  }
  const roleOf=el=>el.getAttribute&&el.getAttribute('data-role');
  const roleName=r=>({badge:'バッジ',title:'タイトル',subtitle:'サブタイトル',pageno:'ページ番号'}[r]||r);
  function expandLinked(list){const set=new Set();list.forEach(el=>{const r=roleOf(el);if(r)document.querySelectorAll('[data-role="'+r+'"]').forEach(x=>set.add(x));else set.add(el);});const arr=[...set];arr.forEach(baseSnap);return arr;}
  // 親子リンク（PPT風グループ）：親.rectに skid を付与、子.tbに data-linked-parent="skid" を持たせる
  function ensureSkid(el){if(el.dataset&&el.dataset.skid)return el.dataset.skid;const id='r'+Math.random().toString(36).slice(2,9);if(el.dataset)el.dataset.skid=id;return id;}
  // 親rectを動かす時、data-linked-parent で結びつく子.tbも一緒に動かす（個別選択は普通にできる）
  function addLinkedChildren(list){const set=new Set(list);list.forEach(el=>{const pid=el.dataset&&el.dataset.skid;if(!pid)return;document.querySelectorAll('[data-linked-parent="'+pid+'"]').forEach(c=>{set.add(c);baseSnap(c);});});return [...set];}
  // ファネル等の図(data-funnel-img)を動かす時、図の上に重なる.tbラベルも一緒に動かす
  function addCompanions(list){const set=new Set(list);list.forEach(el=>{if(el.hasAttribute&&el.hasAttribute('data-funnel-img')){const s=el.closest('.slide');if(!s)return;const fr=el.getBoundingClientRect();s.querySelectorAll('.tb[data-x]').forEach(t=>{const r=t.getBoundingClientRect();const cx=r.left+r.width/2,cy=r.top+r.height/2;if(cx>=fr.left&&cx<=fr.right&&cy>=fr.top&&cy<=fr.bottom){set.add(t);baseSnap(t);}});}});return [...set];}
  classifyRoles();
  renumberPages(); // 既存ページ番号があれば再利用・無ければ付与（二重採番防止）

  // ---- ページ（スライド）操作：複製/追加/移動/削除。対象＝画面中央のページ ----
  function isPageno(t){return N(A(t,'data-x'))>=1180&&N(A(t,'data-y'))>=660&&/^\d+$/.test((t.textContent||'').trim());}
  function pagenoNodes(s){return [...s.querySelectorAll(':scope > .tb')].filter(isPageno);}
  function makePageno(i,s){const pc=pagenoColor(s);const n=document.createElement('div');n.className='tb';[['data-x','1205'],['data-y','680'],['data-w','60'],['data-h','32'],['data-font-size','21'],['data-color',pc],['data-align','right']].forEach(kv=>n.setAttribute(kv[0],kv[1]));n.style.cssText='position:absolute;left:1205px;top:680px;width:60px;height:32px;font-size:21px;color:'+pc+';text-align:right';n.textContent=i;return n;}
  function renumberPages(){allSlides().forEach((s,i)=>{const pgs=pagenoNodes(s);pgs.forEach((p,k)=>{if(k===0)p.textContent=i+1;else p.remove();});if(!pgs.length)s.appendChild(makePageno(i+1,s));});}
  function slideTitleOf(s){let t=s.querySelector('[data-role="title"]');if(!t){const tbs=[...s.querySelectorAll(':scope > .tb[data-x]')];tbs.sort((a,b)=>N(A(b,'data-font-size'))-N(A(a,'data-font-size')));t=tbs[0];}return ((t&&t.textContent.trim())||'(無題)').replace(/\s+/g,' ').slice(0,28);}
  function cleanSlideClone(s){const c=s.cloneNode(true);window.SlideKit.sanitizeSlide(c,'copy');c.removeAttribute('data-sid');return c;} // 複製ページがリンク先を乗っ取らないようsidは外す
  function makeBlankSlide(){const d=document.createElement('div');d.className='slide';d.setAttribute('data-bg','#fafafa');d.style.cssText='background:#fafafa';const t=document.createElement('div');t.className='tb';[['data-x','64'],['data-y','81'],['data-w','1152'],['data-h','52'],['data-font-size','34'],['data-bold','1'],['data-color','#21537f']].forEach(kv=>t.setAttribute(kv[0],kv[1]));t.style.cssText='left:64px;top:81px;width:1152px;height:52px;font-size:34px;font-weight:700;color:#21537f';t.textContent='新しいスライド';d.appendChild(t);return d;}
  const bgOrig=new Map();
  function setSlideBg(s,hex){if(!bgOrig.has(s))bgOrig.set(s,{bg:A(s,'data-bg'),grad:A(s,'data-bg-gradient')});s.setAttribute('data-bg',hex);s.removeAttribute('data-bg-gradient');const st=(s.getAttribute('style')||'').replace(/background\s*:[^;]*;?/i,'');s.setAttribute('style',(st?st.replace(/;?\s*$/,';'):'')+'background:'+hex);}
  function pushSlideBg(s){undo.push({type:'slidebg',el:s,bg:A(s,'data-bg'),grad:A(s,'data-bg-gradient'),style:s.getAttribute('style')});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}
  function currentSlide(){const slides=allSlides();if(!slides.length)return null;const cy=window.innerHeight/2;let best=slides[0],bd=1e9;slides.forEach(s=>{const r=s.getBoundingClientRect();const d=Math.abs(r.top+r.height/2-cy);if(d<bd){bd=d;best=s;}});return best;}
  function afterStruct(target){renumberPages();classifyRoles();if(typeof updateSelPanel==='function')updateSelPanel();if(target&&target.isConnected){selectPage(target);target.scrollIntoView({behavior:'smooth',block:'center'});}else clearPageSel();if(typeof updatePageLabel==='function')updatePageLabel();}
  let pageSel=null;
  const pageBadge=document.createElement('div');pageBadge.className='seui';pageBadge.style.cssText='position:fixed;display:none;background:#e8821a;color:#fff;font:700 13px/1 sans-serif;padding:6px 11px;border-radius:8px;z-index:99997;box-shadow:0 2px 8px rgba(0,0,0,.25);pointer-events:none';pageBadge.textContent='📄 このページを選択中';document.body.appendChild(pageBadge);
  function positionPageBadge(){if(!pageSel||!pageSel.isConnected){pageBadge.style.display='none';return;}const r=pageSel.getBoundingClientRect();pageBadge.style.display='block';pageBadge.style.left=Math.max(6,r.left+10)+'px';pageBadge.style.top=Math.max(6,r.top+10)+'px';}
  function clearPageSel(){if(pageSel){pageSel.style.outline='';pageSel.style.outlineOffset='';}pageSel=null;pageBadge.style.display='none';if(typeof updatePageLabel==='function')updatePageLabel();}
  function selectPage(s){if(pageSel&&pageSel!==s){pageSel.style.outline='';pageSel.style.outlineOffset='';}pageSel=s;s.style.outline='4px solid #e8821a';s.style.outlineOffset='4px';positionPageBadge();if(typeof updatePageLabel==='function')updatePageLabel();}
  function pageTarget(){return (pageSel&&pageSel.isConnected)?pageSel:currentSlide();}
  function dupPage(){const s=pageTarget();if(!s)return;const c=cleanSlideClone(s);s.parentNode.insertBefore(c,s.nextSibling);pageLog.push('複製：「'+slideTitleOf(s)+'」を複製して直後に挿入');afterStruct(c);}
  function addPage(){const s=pageTarget();const d=makeBlankSlide();if(s)s.parentNode.insertBefore(d,s.nextSibling);else document.body.appendChild(d);pageLog.push('追加：'+(s?'「'+slideTitleOf(s)+'」の直後に':'末尾に')+'空白ページ');afterStruct(d);}

  // ---- スライドテンプレート: 表紙 / 中表紙 / Thank You ----
  function makeCoverSlide(){
    const d=document.createElement('div');d.className='slide';
    d.setAttribute('data-bg-gradient','135,#183251,#21537f');
    d.style.cssText='background:linear-gradient(135deg,#183251,#21537f)';
    // タイトル (大)
    const title=document.createElement('div');title.className='tb';
    [['data-x','140'],['data-y','240'],['data-w','1000'],['data-h','120'],['data-font-size','42'],['data-bold','1'],['data-color','#fafafa']].forEach(kv=>title.setAttribute(kv[0],kv[1]));
    title.style.cssText='left:140px;top:240px;width:1000px;height:120px;font-size:42px;font-weight:700;color:#fafafa';
    title.textContent='タイトル';
    d.appendChild(title);
    // サブタイトル
    const sub=document.createElement('div');sub.className='tb';
    [['data-x','140'],['data-y','380'],['data-w','1000'],['data-h','30'],['data-font-size','20'],['data-color','#9fc0dd']].forEach(kv=>sub.setAttribute(kv[0],kv[1]));
    sub.style.cssText='left:140px;top:380px;width:1000px;height:30px;font-size:20px;color:#9fc0dd';
    sub.textContent='サブタイトル';
    d.appendChild(sub);
    // 日付・著者
    const meta=document.createElement('div');meta.className='tb';
    [['data-x','140'],['data-y','520'],['data-w','1000'],['data-h','24'],['data-font-size','14'],['data-color','#c8dcef']].forEach(kv=>meta.setAttribute(kv[0],kv[1]));
    meta.style.cssText='left:140px;top:520px;width:1000px;height:24px;font-size:14px;color:#c8dcef';
    meta.textContent='2026年 | 発表者';
    d.appendChild(meta);
    return d;
  }
  function makeSectionSlide(){
    // 中表紙: 明色背景 + ロゴなし (data-aws-logo="off") + 大きめ見出し
    const d=document.createElement('div');d.className='slide';
    d.setAttribute('data-bg-gradient','135,#e8f1f7,#c8dcef');
    d.setAttribute('data-aws-logo','off');
    d.style.cssText='background:linear-gradient(135deg,#e8f1f7,#c8dcef)';
    const title=document.createElement('div');title.className='tb';
    [['data-x','80'],['data-y','280'],['data-w','1120'],['data-h','80'],['data-font-size','40'],['data-bold','1'],['data-color','#121212']].forEach(kv=>title.setAttribute(kv[0],kv[1]));
    title.style.cssText='left:80px;top:280px;width:1120px;height:80px;font-size:40px;font-weight:700;color:#121212';
    title.textContent='セクションタイトル';
    d.appendChild(title);
    const sub=document.createElement('div');sub.className='tb';
    [['data-x','80'],['data-y','380'],['data-w','1120'],['data-h','30'],['data-font-size','20'],['data-color','#3f5882']].forEach(kv=>sub.setAttribute(kv[0],kv[1]));
    sub.style.cssText='left:80px;top:380px;width:1120px;height:30px;font-size:20px;color:#3f5882';
    sub.textContent='セクションの狙い';
    d.appendChild(sub);
    return d;
  }
  function makeThanksSlide(){
    const d=document.createElement('div');d.className='slide';
    d.setAttribute('data-bg-gradient','135,#183251,#21537f');
    d.style.cssText='background:linear-gradient(135deg,#183251,#21537f)';
    const title=document.createElement('div');title.className='tb';
    [['data-x','140'],['data-y','280'],['data-w','1000'],['data-h','100'],['data-font-size','56'],['data-bold','1'],['data-color','#fafafa']].forEach(kv=>title.setAttribute(kv[0],kv[1]));
    title.style.cssText='left:140px;top:280px;width:1000px;height:100px;font-size:56px;font-weight:700;color:#fafafa';
    title.textContent='Thank you';
    d.appendChild(title);
    const sub=document.createElement('div');sub.className='tb';
    [['data-x','140'],['data-y','400'],['data-w','1000'],['data-h','30'],['data-font-size','20'],['data-color','#9fc0dd']].forEach(kv=>sub.setAttribute(kv[0],kv[1]));
    sub.style.cssText='left:140px;top:400px;width:1000px;height:30px;font-size:20px;color:#9fc0dd';
    sub.textContent='ご清聴ありがとうございました';
    d.appendChild(sub);
    return d;
  }
  function insertAfter(node,ref){if(ref)ref.parentNode.insertBefore(node,ref.nextSibling);else document.body.appendChild(node);}
  function addSlideOfType(type){
    const s=pageTarget();
    let d, label;
    if(type==='cover'){d=makeCoverSlide();label='表紙';}
    else if(type==='section'){d=makeSectionSlide();label='中表紙';}
    else if(type==='thanks'){d=makeThanksSlide();label='Thank you';}
    else {d=makeBlankSlide();label='空白';}
    insertAfter(d,s);
    pageLog.push('追加：'+(s?'「'+slideTitleOf(s)+'」の直後に':'末尾に')+label+'ページ');
    afterStruct(d);
  }
  function movePage(dir){const s=pageTarget();if(!s)return;const slides=allSlides(),i=slides.indexOf(s),j=i+dir;if(j<0||j>=slides.length)return;if(dir<0)s.parentNode.insertBefore(s,slides[j]);else s.parentNode.insertBefore(s,slides[j].nextSibling);pageLog.push('移動：「'+slideTitleOf(s)+'」を'+(dir<0?'前へ':'後ろへ'));afterStruct(s);}
  function delPage(){const s=pageTarget();if(!s)return;if(allSlides().length<=1){alert('最後の1ページは削除できません');return;}const t=slideTitleOf(s);if(!confirm('このページを削除しますか？\n「'+t+'」'))return;s.remove();pageLog.push('削除：「'+t+'」');afterStruct(null);}

  // ---- toolbar ----
  // 右パネルの幅（編集時の右カラム）。閲覧時ツールバー・スライド側の余白・診断パネルの位置はここから決める。
  // 2026-09-27 利用者「右側のツール類の幅は2/3くらいに」＝200px→136px
  const SK_PANEL_W=136,SK_PANEL_PAD=8,SK_BAR_W=SK_PANEL_W-SK_PANEL_PAD*2;
  const bar=document.createElement('div');bar.className='seui skit-live';bar.id='_sk_toolbar';
  // 閲覧時の座標は編集モードの右カラム(right:0/width:200/padding:10px 8px)とボタン位置が一致するよう
  // top:10/right:8/width:184に設定（編集ON/OFFでボタンがズレないように）
  // scrollbar-gutter:stable=内部スクロールバーの幅を常に確保（編集ONで中身が長くなり
  // スクロールバーが出た時にボタン幅が縮んで見えるのを防ぐ・両モードで同幅になる）
  bar.style.cssText='position:fixed;top:10px;right:'+SK_PANEL_PAD+'px;display:flex;flex-direction:column;align-items:stretch;gap:4px;z-index:99999;font-family:sans-serif;width:'+SK_BAR_W+'px;max-height:94vh;overflow:auto;box-sizing:border-box;scrollbar-gutter:stable;scrollbar-width:thin';
  bar.innerHTML='<button id="seEdit">✏️ 編集</button><div id="seUndoRow" style="display:flex;gap:4px"><button id="seUndo" title="直前の編集を取り消す (⌘Z)">↩︎ 戻す</button><button id="seRedo" title="戻しすぎた時に1つ先へ進める (⌘⇧Z)">↪︎ 進む</button></div><button id="seOpen">📂 開く</button><button id="seFmt">📐 フォーマット</button><button id="seDraft" title="ラフモード：手書きフォント＋ラフ印で「まだ叩き台」を見た目で伝える（表示のみ・データ不変）">✍️ ラフ</button><button id="seFont">🅰️ 書き出しFont</button><button id="seText">🅣 文字</button><button id="seShape">🔷 図形</button><button id="seImg">🖼 画像</button><button id="seTbl">▦ 表</button><button id="seDup" title="選択した図形を同じページに複製する（⌘D）。🎯選択中パネルにも同じボタンがある">⧉ 複製</button><button id="sePaste" title="「📋 コピー」した図形を、いま見ているページの同じ位置に貼る（⌘V）">📋 貼付（同じ位置）</button><button id="seRef" title="選択した図形の場所とHTMLを、Kiroに貼り付ける文章として書き出す（図形のコピーではない）">📍 場所をKiroへ</button><button id="seAi" aria-expanded="false">🧩 AI図解相談</button><button id="seCopy" title="このデッキに加えた編集の差分を、Kiroに貼り付ける文章として書き出す（図形のコピーではない）">📤 Kiroへ渡す</button><button id="seSave">💾 保存</button>';
  document.body.appendChild(bar);

  // ---- AI図解相談：選択中ページを外部送信せず、Kiro貼付用プロンプトだけコピー ----
  const aiPanel=document.createElement('div');aiPanel.className='seui';
  aiPanel.style.cssText='display:none;flex-direction:column;gap:6px;background:rgba(74,74,74,.95);padding:9px 10px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.2)';
  const aiTitle=document.createElement('div');aiTitle.textContent='🧩 AI図解相談';aiTitle.style.cssText='color:#fff;font:700 14px/1.2 sans-serif';aiPanel.appendChild(aiTitle);
  const aiNow=document.createElement('div');aiNow.style.cssText='color:#cdd9e5;font:600 14px/1.4 sans-serif';aiPanel.appendChild(aiNow);
  const aiNote=document.createElement('div');aiNote.textContent='外部送信なし。プロンプトをコピーします。';aiNote.style.cssText='color:#cdd9e5;font:400 14px/1.4 sans-serif';aiPanel.appendChild(aiNote);
  const aiIdeas=document.createElement('button');aiIdeas.type='button';aiIdeas.setAttribute('data-ai','ideas');aiIdeas.textContent='案だけコピー';aiPanel.appendChild(aiIdeas);
  const aiRewrite=document.createElement('button');aiRewrite.type='button';aiRewrite.setAttribute('data-ai','rewrite');aiRewrite.textContent='書き換え依頼をコピー';aiPanel.appendChild(aiRewrite);
  bar.insertBefore(aiPanel,bar.querySelector('#seCopy'));
  bar.querySelectorAll('button').forEach(b=>b.style.cssText='padding:5px 10px;border:none;border-radius:4px;background:rgba(74,74,74,.95);color:#fff;font-size:12px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2);text-align:center;white-space:nowrap');
  [bar.querySelector('#seAi'),aiIdeas,aiRewrite].forEach(b=>b.style.fontSize='14px');
  // 戻す／進むは2つ横並び。狭い右パネルでも1文字ずつ折り返さないよう余白を詰めて1行に保つ（2026-09-27）
  bar.querySelectorAll('#seUndoRow button').forEach(b=>{b.style.flex='1 1 0';b.style.padding='5px 2px';b.style.setProperty('white-space','nowrap','important');});

  function aiTargetSlide(){
    if(pageSel&&pageSel.isConnected)return pageSel;
    if(sels.length&&sels[0].closest){const s=sels[0].closest('.slide');if(s)return s;}
    return currentSlide();
  }
  function aiFileName(){try{return decodeURIComponent((location.pathname.split('/').pop()||'スライド.html'));}catch(_){return location.pathname.split('/').pop()||'スライド.html';}}
  function aiSlideContext(){
    const s=aiTargetSlide();if(!s)return null;
    const clean=cleanSlideClone(s),slides=allSlides();
    return {file:aiFileName(),number:slides.indexOf(s)+1,total:slides.length,title:slideTitleOf(s),text:(clean.textContent||'').replace(/\s+/g,' ').trim(),html:clean.outerHTML};
  }
  function updateAiLabel(){const c=aiSlideContext();aiNow.textContent=c?('対象: '+c.number+' / '+c.total+'ページ目「'+c.title+'」'):'対象ページがありません';}
  function aiIdeasPrompt(c){return [
    '=== SlideKit AI図解相談：図解案を考える ===','',
    '対象ファイル：'+c.file,'対象スライド：'+c.number+'ページ「'+c.title+'」','',
    'このスライドを、文章中心ではなく図または表で分かりやすくできないか検討してください。','内容の意味・事実・数値は変えないでください。まだHTMLは書き換えません。','',
    '現在の内容：',c.text,'','現在のHTML：','```html',c.html,'```','',
    '次の順で回答してください。','1. このスライドで理解させるべきことを1文で定義する','2. 比較、工程、時系列、循環、階層、依存関係、因果関係、数値のどれに該当するか判定する','3. 図解または表にする価値があるか判断する','4. 新規図解、表、スクリーンショット、過去PPTX移植を含め、適切な案を最大3案示す','5. 推奨案を1つ選び、理由を書く','',
    '既存の SlideKit/diagram-catalog.html と pattern-catalog.html に適合する型があれば優先してください。','無理に図解せず、文章の方が伝わる場合はその判断を明記してください。'
  ].join('\n');}
  function aiRewritePrompt(c){return [
    '=== SlideKit AI図解相談：推奨案で書き換える ===','',
    '対象ファイル：'+c.file,'対象スライド：'+c.number+'ページ「'+c.title+'」','',
    '次のスライドを分析し、内容に最も適した図解または表へ書き換えてください。','同じ会話に直前の推奨案があれば採用し、なければ最適案を選んでください。','',
    '現在の内容：',c.text,'','現在のHTML：','```html',c.html,'```','',
    '要件：','・内容の意味・事実・数値・固有名詞を変えない','・元の箇条書きをそのままカード化しない','・比較は表、工程はフロー、時系列はタイムライン、循環は円環、階層は階層図、依存関係は依存関係図を優先する','・図解が不適切なら文章レイアウトを改善する','・1280×720pxに収め、文字を縮小して詰め込まず、必要なら2枚に分ける','・SlideKitの slidekit-steering.md、diagram-catalog.html、pattern-catalog.html に従う','・使用classは .slide、.tb、.rect、.flow、.ins、.inszoneに限定する','・全要素のdata属性とinline styleを同値にする','・全ての文字はPowerPointで編集可能な.tbまたは表セルにする。SVG内のtext要素や画像への文字焼き込みは禁止','・複雑な図形はSVG（図形のみ）にし、文字は.tbとして同座標に重ねる','・対象スライドだけを書き換え、置換可能な完全なスライドブロックを返す','・書き換え後にレンダリング、run_check.py、PPTX変換を確認する'
  ].join('\n');}
  bar.querySelector('#seAi').onclick=function(){const open=aiPanel.style.display!=='none';aiPanel.style.display=open?'none':'flex';this.setAttribute('aria-expanded',open?'false':'true');if(!open)updateAiLabel();};

  // ---- ✍️ ラフモード：手書きフォント＋ラフ印のオーバーレイで「まだ叩き台」を見た目で伝える ----
  // 表示だけの上書き（.seuiスタイル1本）なのでデータは不変。<html data-draft="on"> だけ保存に残り、
  // 開き直すと自動でラフ表示が復元される。確定したらOFFにして保存すれば属性ごと消える。
  const DRAFT_STYLE_ID='seui-draft-style';
  const draftBtn=bar.querySelector('#seDraft');
  function draftApply(on){
    const old=document.getElementById(DRAFT_STYLE_ID);
    if(on&&!old){
      const st=document.createElement('style');st.id=DRAFT_STYLE_ID;st.className='seui';
      st.textContent=".slide,.slide .tb,.slide .rect,.slide .flow,.slide td,.slide th{font-family:'Klee','Klee One','Bradley Hand',cursive !important}"
        +".slide{filter:grayscale(1) contrast(.92)}" // 完全モノトーン＝色の議論を封じて構造だけ見せる
        +".slide::after{content:'ラフ';position:absolute;top:14px;right:18px;padding:2px 14px;border:2px solid #444;border-radius:4px;color:#444;font:700 20px/1.5 'Klee','Klee One',cursive;transform:rotate(6deg);opacity:.85;pointer-events:none;z-index:9000}";
      document.head.appendChild(st);
    }
    if(!on&&old)old.remove();
    if(on)document.documentElement.setAttribute('data-draft','on');
    else document.documentElement.removeAttribute('data-draft');
    draftBtn.style.background=on?'#8a5a1a':'rgba(74,74,74,.95)';
    draftBtn.textContent=on?'✍️ ラフ中':'✍️ ラフ';
  }
  draftBtn.onclick=function(){draftApply(!document.getElementById(DRAFT_STYLE_ID));};
  if(document.documentElement.getAttribute('data-draft')==='on')draftApply(true);
  aiPanel.addEventListener('click',function(e){const action=e.target.getAttribute&&e.target.getAttribute('data-ai');if(!action)return;const c=aiSlideContext();if(!c){alert('対象ページがありません');return;}updateAiLabel();const ideas=action==='ideas';copyText(ideas?aiIdeasPrompt(c):aiRewritePrompt(c),(ideas?'図解案相談':'書き換え依頼')+'のプロンプトをコピーしました。Kiroに貼り付けてください。');});
  // 戻す/進むは同じ行に左右2個で並べる（cssText で消えた flex を後付けで復元）
  ['seUndo','seRedo'].forEach(id=>{const b=bar.querySelector('#'+id);if(b)b.style.flex='1';});
  bar.querySelector('#seUndo').addEventListener('click',()=>doUndo());
  bar.querySelector('#seRedo').addEventListener('click',()=>doRedo());

  // ---- ページ操作パネル（編集ON時のみ表示・対象は画面中央のページ）----
  const pagebar=document.createElement('div');pagebar.className='seui';
  pagebar.style.cssText='display:none;flex-direction:column;gap:5px;background:rgba(74,74,74,.95);padding:9px 10px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.2)';
  bar.appendChild(pagebar);
  const pgTitle=document.createElement('div');pgTitle.textContent='📄 ページ操作';pgTitle.style.cssText='color:#fff;font:700 12px/1 sans-serif';pagebar.appendChild(pgTitle);
  const pgNow=document.createElement('div');pgNow.style.cssText='color:#cdd9e5;font:600 11px/1.3 sans-serif';pagebar.appendChild(pgNow);
  const pgBtns=document.createElement('div');pgBtns.style.cssText='display:flex;flex-wrap:wrap;gap:4px';
  pgBtns.innerHTML='<button data-pg="dup">⧉ 複製</button><button data-pg="add">＋ 追加</button><button data-pg="up">↑ 前へ</button><button data-pg="down">↓ 後ろへ</button><button data-pg="del">🗑 削除</button>'
    +'<div data-pg-add-menu style="display:flex;flex-wrap:wrap;gap:3px;width:100%;margin-top:3px">'
    +'<button data-pg="add-cover" title="表紙 (大きなタイトル+暗色グラデ背景)">＋表紙</button>'
    +'<button data-pg="add-section" title="中表紙 (セクション区切り。AWSロゴなし)">＋中表紙</button>'
    +'<button data-pg="add-thanks" title="Thank you (裏表紙)">＋Thanks</button>'
    +'<button data-pg="add-gantt" title="GanttKitでガントチャートを作成→「スライドへ追加」でこのデッキに1枚入る">＋ガント</button>'
    +'<button data-pg="add-calc" title="CalcKitで表を作成（既存シート・計算式もそのまま）→「この表をスライドへ追加」でこのデッキに1枚入る">＋表(CalcKit)</button>'
    +'<button data-pg="add-pattern" title="カタログの型から1枚入れる（図解D01〜D16・文字系P01〜P18）。座標はカタログのまま・型ID宣言つき">＋型から</button>'
    +'</div>';
  pagebar.appendChild(pgBtns);
  Array.from(pgBtns.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:4px 9px;border:none;border-radius:3px;background:#3a3a3a;color:#fff;font-size:12px;cursor:pointer');
  const pgBg=document.createElement('div');pgBg.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  pgBg.innerHTML='<span style="color:#cdd9e5;font:600 11px/1.3 sans-serif;width:100%;display:block">背景色</span><input id="pgBgTx" type="text" spellcheck="false" style="width:90px;font:400 13px Menlo,Consolas,monospace;letter-spacing:.4px;padding:3px 6px;border:none;border-radius:4px"><input id="pgBgSw" type="color" style="width:26px;height:20px;border:none;background:none;cursor:pointer;padding:0">';
  pagebar.appendChild(pgBg);
  // ☁️ AWSロゴ表示トグル (ページ単位。中表紙などロゴを外したいスライドで OFF)
  // フォーマットが AWS の時のみ効く
  const pgAws=document.createElement('div');pgAws.style.cssText='display:flex;align-items:center;gap:6px;margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,.15)';
  pgAws.innerHTML='<label style="color:#cdd9e5;font:600 11px/1.3 sans-serif;display:flex;align-items:center;gap:5px;cursor:pointer"><input id="pgAwsChk" type="checkbox" style="margin:0;cursor:pointer">☁️ このページはAWSロゴを付ける</label>';
  pagebar.appendChild(pgAws);
  const pgAwsChk=pgAws.querySelector('#pgAwsChk');
  pgAwsChk.addEventListener('change',function(){
    if(!pageSel||!pageSel.isConnected){alert('先にページ枠をクリックして選択してください');return;}
    pushSlideBg(pageSel); // ページ属性変更として undo に積む
    if(pgAwsChk.checked){
      pageSel.removeAttribute('data-aws-logo');
    }else{
      pageSel.setAttribute('data-aws-logo','off');
    }
    // オーバーレイを再描画
    if(curTemplate==='aws'){
      pageSel.querySelectorAll('.aws-overlay,.aws-cover-bg').forEach(e=>e.remove());
      pageSel.classList.remove('aws-cover');
      awsOverlayCreate(pageSel);
    }
    dirty=true;
  });
  // 🗒 発表者ノート（2026-10-14 利用者「発表者ノートつけましょうか」）
  //   対象ページの data-notes を読み書きする。PPTXではノート欄に入り、プレゼン中は手元のリモコン上に出る（投影には出ない）
  const pgNotes=document.createElement('div');pgNotes.style.cssText='display:flex;flex-direction:column;gap:3px;margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,.15)';
  const pgNotesLb=document.createElement('label');pgNotesLb.textContent='🗒 発表者ノート';pgNotesLb.title='PPTXのノート欄に入ります。プレゼン中は手元に出て、投影には出ません';pgNotesLb.style.cssText='color:#cdd9e5;font:600 11px/1.3 sans-serif';pgNotesLb.htmlFor='pgNotesTa';pgNotes.appendChild(pgNotesLb);
  const pgNotesTa=document.createElement('textarea');pgNotesTa.id='pgNotesTa';pgNotesTa.rows=5;pgNotesTa.spellcheck=false;pgNotesTa.placeholder='このページで話すこと（投影には出ません）';
  pgNotesTa.style.cssText='width:100%;box-sizing:border-box;resize:vertical;font:400 13px/1.5 sans-serif;padding:5px 7px;border:none;border-radius:4px;color:#121212;background:#fafafa';
  pgNotes.appendChild(pgNotesTa);pagebar.appendChild(pgNotes);
  let notesTgt=null,notesBefore='',notesPushed=false;
  function updateNotesBox(){if(document.activeElement===pgNotesTa)return;const s=pageTarget();notesTgt=s;pgNotesTa.value=s?(A(s,'data-notes')||''):'';pgNotesTa.disabled=!s;}
  pgNotesTa.addEventListener('focus',function(){notesTgt=pageTarget();notesBefore=notesTgt?(A(notesTgt,'data-notes')||''):'';notesPushed=false;});
  pgNotesTa.addEventListener('input',function(){
    const s=notesTgt;if(!s||!s.isConnected)return;
    if(!notesPushed){undo.push({type:'notes',el:s,v:notesBefore});if(undo.length>60)undo.shift();redo.length=0;notesPushed=true;}
    const v=pgNotesTa.value;if(v.trim())s.setAttribute('data-notes',v);else s.removeAttribute('data-notes');
    dirty=true;try{window.dispatchEvent(new CustomEvent('skit:notes',{detail:{slide:s}}));}catch(_){}
  });
  pgNotesTa.addEventListener('blur',function(){const s=notesTgt;if(s&&notesPushed&&(A(s,'data-notes')||'')!==notesBefore)pageLog.push('ノート：「'+slideTitleOf(s)+'」の発表者ノートを書き換え');notesPushed=false;});
  const pgBgTx=pgBg.querySelector('#pgBgTx'),pgBgSw=pgBg.querySelector('#pgBgSw');
  function applyPgBg(v){v=(v||'').trim();if(!pageSel||!pageSel.isConnected){alert('先にページ枠をクリックして選択してください');return;}if(!isHex(v))return;pushSlideBg(pageSel);setSlideBg(pageSel,v);pgBgTx.value=v;try{pgBgSw.value=v;}catch(_){}}
  pgBgTx.addEventListener('change',()=>applyPgBg(pgBgTx.value));
  pgBgSw.addEventListener('input',()=>applyPgBg(pgBgSw.value));
  pgBgSw.addEventListener('change',()=>applyPgBg(pgBgSw.value));
  function updatePageLabel(){const sel=(typeof pageSel!=='undefined'&&pageSel&&pageSel.isConnected);const s=sel?pageSel:currentSlide();const i=s?allSlides().indexOf(s)+1:0;pgNow.textContent=(sel?'選択中: ':'対象: ')+i+' / '+allSlides().length+'ページ目'+(sel?'（ページをクリックで選択）':'（ページ枠をクリックで選択）');if(sel){const bg=A(pageSel,'data-bg')||(A(pageSel,'data-bg-gradient')?'#183251':'#fafafa');const hx=isHex(bg)?bg:'#fafafa';pgBgTx.value=hx;try{pgBgSw.value=hx;}catch(_){}pgBg.style.opacity='1';
    // AWSロゴ表示チェック (AWSフォーマット中かつ slidekit-aws.js プラグインあり環境のみ)
    if(curTemplate==='aws'&&window.SLIDEKIT_DEFS&&window.SLIDEKIT_DEFS.formats&&window.SLIDEKIT_DEFS.formats.aws){pgAws.style.display='flex';pgAwsChk.checked=(A(pageSel,'data-aws-logo')!=='off');}else{pgAws.style.display='none';}
  }else{pgBgTx.value='';pgBg.style.opacity='.5';pgAws.style.display='none';}updateNotesBox();}
  pgBtns.addEventListener('click',function(e){
    const op=e.target.getAttribute&&e.target.getAttribute('data-pg');if(!op)return;
    if(op==='dup')dupPage();
    else if(op==='add')addPage();
    else if(op==='up')movePage(-1);
    else if(op==='down')movePage(1);
    else if(op==='del')delPage();
    else if(op==='add-cover')addSlideOfType('cover');
    else if(op==='add-section')addSlideOfType('section');
    else if(op==='add-thanks')addSlideOfType('thanks');
    else if(op==='add-gantt')openGanttKit();
    else if(op==='add-calc')openCalcKit();
    else if(op==='add-pattern')openPatternPicker();
  });

  // ---- キット連携: ＋ガント/＋表(CalcKit) → 別タブで作成 → localStorage(storageイベント)でスライド1枚受け取り ----
  // 受け渡しの流儀は BezierKit⇄アイコンカタログ と同じ（file://のタブ間で実証済み）
  // デッキの同一性はクエリとハッシュを落として比べる。
  // 決定: location.href の完全一致だと ?present=1 が付いた瞬間に受け取りが無言で失敗する（2026-08-21）
  // 根拠=.kiro/steering/projects/kiro-operations.md
  function deckKey(h){try{const u=new URL(h);return u.origin+decodeURIComponent(u.pathname);}catch(_){return String(h).split(/[?#]/)[0];}}
  window.SlideKit.deckKey=deckKey;
  function openKitTab(retKey,relPath){
    try{localStorage.setItem(retKey,JSON.stringify({deck:deckKey(location.href),ts:Date.now()}));}catch(_){}
    let src=null;
    document.querySelectorAll('script[src]').forEach(s=>{if(/slide-edit\.js/.test(s.src))src=s.src;});
    const url=src?new URL(relPath,src).href:relPath;
    window.open(url,'_blank');
  }
  function openGanttKit(){openKitTab('skGanttReturn','../GanttKit/index.html');}
  function openCalcKit(){openKitTab('skCalcReturn','../CalcKit/index.html');}

  // ---- カタログの型から1枚入れる（2026-08-21）----
  // 決定: 図解16型が使われない原因は「カタログから座標を手で写すしかない」こと。
  // カタログHTMLをfetchして型を選ぶだけで1枚入るようにする。焼き込まないので二重管理にならない。
  // 根拠=.kiro/steering/projects/kiro-operations.md
  function kitBase(){let s=null;document.querySelectorAll('script[src]').forEach(x=>{if(/slide-edit\.js/.test(x.src))s=x.src;});return s;}
  let patCache=null;
  async function loadPatterns(){
    if(patCache)return patCache;
    const base=kitBase();
    if(!base)throw new Error('slide-edit.js のURLが取れない');
    const out=[];
    for(const f of ['pattern-catalog.html','diagram-catalog.html']){
      const r=await fetch(new URL(f,base).href);
      if(!r.ok)throw new Error(f+'（HTTP '+r.status+'）');
      const t=await r.text();
      const re=/<!--\s*SLIDE:\s*([\s\S]*?)-->([\s\S]*?)<!--\s*\/SLIDE\s*-->/g;
      let m;
      while((m=re.exec(t))){
        const head=m[1].replace(/-+\s*$/,'').trim();
        const id=(head.match(/^([PD]\d{2})/)||[])[1];
        if(!id||!/class="slide"/.test(m[2]))continue;
        out.push({id,name:head.replace(/^[PD]\d{2}\s*/,'').trim()||id,html:m[2]});
      }
    }
    if(!out.length)throw new Error('カタログから型を取り出せなかった');
    patCache=out;
    return out;
  }
  function insertPattern(p){
    let doc;
    try{doc=new DOMParser().parseFromString('<body>'+p.html+'</body>','text/html');}catch(_){return false;}
    const sl=doc.querySelector('.slide');if(!sl)return false;
    const d=document.importNode(sl,true);
    window.SlideKit.sanitizeSlide(d,'copy');
    // 型ID宣言のコメントも一緒に入れる（構成ファイルとの突合と④の検査が効く）
    const cm=document.createComment(' SLIDE: '+p.name+' ['+p.id+'] ');
    const t=pageTarget();
    if(t&&t.parentNode){t.parentNode.insertBefore(cm,t.nextSibling);cm.parentNode.insertBefore(d,cm.nextSibling);}
    else{document.body.appendChild(cm);document.body.appendChild(d);}
    pageLog.push('追加：カタログの型 '+p.id+' '+p.name);
    afterStruct(d);
    return true;
  }
  window.SlideKit.insertPattern=async function(id){ // 検証・Kiro操作用
    const p=(await loadPatterns()).find(x=>x.id===id.toUpperCase());
    if(!p)throw new Error('型が見つからない: '+id);
    return insertPattern(p);
  };
  const patPanel=document.createElement('div');patPanel.className='seui skit-live';
  patPanel.style.cssText='display:none;flex-direction:column;gap:6px;background:rgba(22,42,66,.96);padding:10px 12px;border-radius:10px;max-height:60vh;overflow:auto;box-shadow:0 2px 8px rgba(0,0,0,.25)';
  bar.appendChild(patPanel);
  async function openPatternPicker(){
    if(patPanel.style.display==='flex'){patPanel.style.display='none';return;}
    patPanel.style.display='flex';
    patPanel.innerHTML='<div style="color:#fff;font:700 12px/1.4 sans-serif">カタログを読み込み中…</div>';
    let list;
    try{list=await loadPatterns();}
    catch(e){
      patPanel.innerHTML='<div style="color:#ffd7d7;font:600 12px/1.6 sans-serif;max-width:300px">'
        +'カタログを読めなかった（'+String(e.message).replace(/</g,'&lt;')+'）。<br>'
        +'ローカルサーバー経由で開き直す：<br>'
        +'<code style="color:#9fc0dd;font-size:11px">cd （ワークスペースルート） &amp;&amp; python3 -m http.server 8000</code><br>'
        +'file:// で開いているとカタログを取得できない。</div>';
      return;
    }
    const groups=[['図解（D01〜D16）',list.filter(p=>p.id[0]==='D')],
                  ['文字系（P01〜P18）',list.filter(p=>p.id[0]==='P')]];
    patPanel.innerHTML='<div style="color:#fff;font:700 12px/1.4 sans-serif">型を選ぶと現在ページの次に1枚入る</div>'
      +'<div style="color:#9fc0dd;font:400 10px/1.4 sans-serif;margin-bottom:2px">座標はカタログのまま。型ID宣言も一緒に入る</div>'
      +groups.map(([t,ps])=>'<div style="color:#9fc0dd;font:700 11px/1.4 sans-serif;margin-top:4px">'+t+'</div>'
        +'<div style="display:flex;flex-direction:column;gap:2px">'
        +ps.map(p=>'<button data-pid="'+p.id+'" style="text-align:left;padding:4px 8px;border:none;border-radius:3px;background:#3a3a3a;color:#fff;font-size:12px;cursor:pointer">'
          +'<b style="color:#9fc0dd">'+p.id+'</b> '+p.name.replace(/</g,'&lt;')+'</button>').join('')
        +'</div>').join('');
    patPanel.querySelectorAll('button[data-pid]').forEach(b=>{
      b.onclick=()=>{
        const p=list.find(x=>x.id===b.getAttribute('data-pid'));
        if(p&&insertPattern(p))flashPageBadge('📐 '+p.id+' を入れた（文字を書き換える）');
        patPanel.style.display='none';
      };
    });
  }
  function insertKitSlide(html,logLabel){
    let doc;
    try{doc=new DOMParser().parseFromString(html,'text/html');}catch(_){return false;}
    const sl=doc.querySelector('.slide');if(!sl)return false;
    const d=document.importNode(sl,true);
    window.SlideKit.sanitizeSlide(d,'copy'); // 編集UI・ページ番号などを剥がす（renumberで振り直す）
    const t=pageTarget();
    if(t)t.parentNode.insertBefore(d,t.nextSibling);else document.body.appendChild(d);
    pageLog.push('追加：'+logLabel);
    afterStruct(d);
    return true;
  }
  window.SlideKit.insertGanttSlide=html=>insertKitSlide(html,'GanttKitのガントスライドを挿入'); // 連携・検証用API
  window.SlideKit.insertCalcSlide=html=>insertKitSlide(html,'CalcKitの表スライドを挿入');
  const kitSlideKeys={skGanttSlide:['GanttKitのガントスライドを挿入','GanttKitからガントスライドを追加した','skGanttReturn'],
                      skCalcSlide:['CalcKitの表スライドを挿入','CalcKitから表スライドを追加した','skCalcReturn']};
  window.addEventListener('storage',function(ev){
    const kk=kitSlideKeys[ev.key];
    if(!kk||!ev.newValue)return;
    let d;try{d=JSON.parse(ev.newValue);}catch(_){return;}
    if(!d||!d.html)return;
    if(d.deck&&d.deck!==deckKey(location.href))return; // 別のデッキ宛は無視
    // 受け取ったスライドのキーは消す。戻り先は ts を更新して延命する＝このデッキが生きている印。
    // 決定: 戻り先の寿命を30分にし、受け取るたびに延命する。放置すれば消えるので相手Kitを
    // 単体で開いたときにボタンが出ない。延命するので2枚目・3枚目も入る（2026-08-21修正）
    try{
      localStorage.removeItem(ev.key);
      localStorage.setItem(kk[2],JSON.stringify({deck:deckKey(location.href),ts:Date.now()}));
    }catch(_){}
    if(insertKitSlide(d.html,kk[0])){
      const n=document.createElement('div');n.className='seui';
      n.textContent=kk[1]+'（📤Kiroへ渡す か 💾保存 で確定）';
      n.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:rgba(22,42,66,.95);color:#fff;padding:10px 22px;border-radius:8px;font:600 13px sans-serif;z-index:99999';
      document.body.appendChild(n);setTimeout(()=>n.remove(),3500);
    }
  });
  window.addEventListener('scroll',()=>{if(editing){updatePageLabel();positionPageBadge();}});
  window.addEventListener('resize',()=>{if(editing)positionPageBadge();});
  const fileInput=document.createElement('input');fileInput.className='seui';fileInput.type='file';fileInput.accept='image/*';fileInput.style.display='none';document.body.appendChild(fileInput);

  // ---- カラーパレット編集（デッキで使われている色を自動列挙→hex編集で全スライド一括置換）----
  const pal=document.createElement('div');pal.className='seui skit-live';
  pal.style.cssText='display:none;flex-direction:column;gap:5px;background:rgba(22,42,66,.94);padding:9px 10px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.2)';
  bar.appendChild(pal);
  const palHeader=document.createElement('div');palHeader.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:4px';
  const palTitle=document.createElement('div');palTitle.textContent='🎨 共通カラーパレット';palTitle.style.cssText='color:#fff;font:700 12px/1 sans-serif;flex:1';
  const palRefresh=document.createElement('button');palRefresh.textContent='🔄';palRefresh.title='パレットを再スキャン';
  palRefresh.style.cssText='padding:2px 6px;border:none;border-radius:3px;background:#0d3a5a;color:#fff;font-size:11px;cursor:pointer';
  palHeader.appendChild(palTitle);palHeader.appendChild(palRefresh);pal.appendChild(palHeader);
  const palHint=document.createElement('div');palHint.style.cssText='color:#8fa4b8;font:400 10px/1.3 sans-serif;margin-bottom:4px';
  palHint.innerHTML='hex/ピッカー入力で全スライドの同色を置換。⌀で透明。<br>Shift+クリックで選択中の要素にこの色を割り当て。';
  pal.appendChild(palHint);
  const palList=document.createElement('div');palList.style.cssText='display:flex;flex-direction:column;gap:4px';
  pal.appendChild(palList);

  function firstHex(sel,attr,def){const e=document.querySelector(sel);const v=e&&e.getAttribute(attr);return (v&&/^#[0-9a-fA-F]{3,8}$/.test(v))?v:def;}
  // 色として有効なのは 3・6・8桁だけ（以前は4・5・7桁も通り、入力途中の値が一瞬反映されていた）
  function isHex(v){return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v);}
  // 入力中（1文字ずつ）に即反映してよい完成形。3桁は「#162a42」を打つ途中にも現れるので Enter/確定の時だけ反映する
  function isHexTyped(v){return /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v);}
  function normHex(h){if(!h||h[0]!=='#')return null;h=h.toLowerCase();if(h.length===4)return '#'+h[1]+h[1]+h[2]+h[2]+h[3]+h[3];if(h.length===9)return h.slice(0,7);if(h.length===7)return h;return null;}
  function rgbToHex(rgbStr){const m=rgbStr.match(/rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/);if(!m)return null;const h=(x)=>('0'+parseInt(x,10).toString(16)).slice(-2);return '#'+h(m[1])+h(m[2])+h(m[3]);}
  function applyColor(oldHex,newHex){
    const oh=normHex(oldHex);const nh=normHex(newHex);
    if(!oh||!nh)return;
    // hex 表記 (oldHex) を newHex に置換
    const esc=oh.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    const rep=v=>v.replace(new RegExp(esc+'(?![0-9a-fA-F])','gi'),nh);
    // 対応する rgb() 表記も置換
    const r=parseInt(oh.slice(1,3),16),g=parseInt(oh.slice(3,5),16),b=parseInt(oh.slice(5,7),16);
    const nr=parseInt(nh.slice(1,3),16),ng=parseInt(nh.slice(3,5),16),nb=parseInt(nh.slice(5,7),16);
    const rgbEsc=`rgb\\(\\s*${r}\\s*,\\s*${g}\\s*,\\s*${b}\\s*\\)`;
    const rgbNew=`rgb(${nr}, ${ng}, ${nb})`;
    const repRgb=v=>v.replace(new RegExp(rgbEsc,'gi'),rgbNew);
    document.querySelectorAll('.slide, .slide *').forEach(el=>{
      ['data-color','data-fill','data-bg','data-bg-gradient'].forEach(a=>{
        const v=el.getAttribute(a);if(v){let nv=rep(v);nv=repRgb(nv);if(nv!==v)el.setAttribute(a,nv);}
      });
      const s=el.getAttribute('style');
      if(s){let ns=rep(s);ns=repRgb(ns);if(ns!==s)el.setAttribute('style',ns);}
    });
  }
  function replaceColor(oldHex,newHex){
    if(!isHex(newHex))return;
    const oh=normHex(oldHex),nh=normHex(newHex);
    if(!oh||!nh||oh===nh)return;
    // 変わる要素だけを記録してから置き換える（2026-09-27）。
    // 🚫 以前は「新色→旧色」の置換で戻していたため、元から新色だった無関係な要素まで旧色に変わった
    const r=parseInt(oh.slice(1,3),16),g=parseInt(oh.slice(3,5),16),b=parseInt(oh.slice(5,7),16);
    const rgbRe=new RegExp('rgb\\(\\s*'+r+'\\s*,\\s*'+g+'\\s*,\\s*'+b+'\\s*\\)','i');
    const hexRe=new RegExp(oh+'(?![0-9a-fA-F])','i');
    const hitAttr=v=>!!v&&(hexRe.test(v)||rgbRe.test(v));
    const affected=[...document.querySelectorAll('.slide, .slide *')].filter(el=>
      ['data-color','data-fill','data-bg','data-bg-gradient','style'].some(a=>hitAttr(el.getAttribute(a))));
    if(!affected.length)return;
    pushAttr(affected);
    applyColor(oh,nh);
  }
  // 特定 hex を使う要素の背景を透明化 (data-fill="none", background:transparent)
  function replaceColorTransparent(oldHex){
    const oh=normHex(oldHex);if(!oh)return;
    const affected=[];
    document.querySelectorAll('.slide, .slide *').forEach(el=>{
      const df=(el.getAttribute('data-fill')||'').toLowerCase();
      const st=(el.getAttribute('style')||'').toLowerCase();
      if(df===oh || st.indexOf('background:'+oh)>=0 || st.indexOf('background: '+oh)>=0){
        affected.push(el);
      }
    });
    if(!affected.length)return;
    pushAttr(affected);
    affected.forEach(el=>{
      if((el.getAttribute('data-fill')||'').toLowerCase()===oh){
        el.setAttribute('data-fill','none');
      }
      const s=el.getAttribute('style');
      if(s){
        const ns=s.replace(new RegExp('background(?:-color)?\\s*:\\s*'+oh.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\s*(?:;|$)','gi'),'background:transparent;');
        el.setAttribute('style',ns);
      }
    });
  }
  // デッキで使われている色をスキャン
  function scanDeckColors(){
    const map=new Map(); // hex → {count, kinds:Set('fg'|'bg')}
    function add(hex, kind){
      const h=normHex(hex);if(!h)return;
      let e=map.get(h);if(!e){e={count:0,kinds:new Set()};map.set(h,e);}
      e.count++;e.kinds.add(kind);
    }
    document.querySelectorAll('.slide, .slide *').forEach(el=>{
      const dc=el.getAttribute('data-color');if(dc)add(dc,'fg');
      const df=el.getAttribute('data-fill');if(df && df!=='none')add(df,'bg');
      const db=el.getAttribute('data-bg');if(db)add(db,'bg');
      const dg=el.getAttribute('data-bg-gradient');
      if(dg){const hexes=dg.match(/#[0-9a-fA-F]{3,8}/g);if(hexes)hexes.forEach(h=>add(h,'bg'));}
      const s=el.getAttribute('style');
      if(s){
        // color:xxx (背景系じゃない) は fg
        const cm=s.match(/(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))/gi);
        if(cm)cm.forEach(t=>{const m=t.match(/#[0-9a-fA-F]{3,8}/);if(m)add(m[0],'fg');else{const rm=t.match(/rgb\([^)]+\)/);if(rm){const h=rgbToHex(rm[0]);if(h)add(h,'fg');}}});
        const bm=s.match(/background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))/gi);
        if(bm)bm.forEach(t=>{const m=t.match(/#[0-9a-fA-F]{3,8}/);if(m)add(m[0],'bg');else{const rm=t.match(/rgb\([^)]+\)/);if(rm){const h=rgbToHex(rm[0]);if(h)add(h,'bg');}}});
        const bdm=s.match(/border(?:-\w+)?\s*:[^;]*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))/gi);
        if(bdm)bdm.forEach(t=>{const m=t.match(/#[0-9a-fA-F]{3,8}/);if(m)add(m[0],'bg');else{const rm=t.match(/rgb\([^)]+\)/);if(rm){const h=rgbToHex(rm[0]);if(h)add(h,'bg');}}});
      }
    });
    // 出現回数の多い順
    return [...map.entries()].sort((a,b)=>b[1].count-a[1].count);
  }
  // パレット行を再描画
  function rebuildPalette(){
    palList.innerHTML='';
    const entries=scanDeckColors();
    if(!entries.length){
      const empty=document.createElement('div');empty.textContent='(色が検出できませんでした)';empty.style.cssText='color:#8fa4b8;font:400 11px/1.4 sans-serif;padding:6px';
      palList.appendChild(empty);return;
    }
    entries.forEach(([hex,info])=>{
      // 右パネルが狭い時（2026-09-27 に2/3幅へ）は、使用数と⌀が次の段へ折り返す
      const row=document.createElement('div');row.style.cssText='display:flex;flex-wrap:wrap;align-items:center;gap:3px 5px;padding:2px;border-radius:4px';
      // 色見本 (= ネイティブカラーピッカーを大きめに表示。クリックで OS のカラーパネルが開く)
      // ラッパで角丸+枠を装飾しつつ、本体の <input type="color"> をそのまま置く
      const swWrap=document.createElement('div');
      swWrap.style.cssText='position:relative;width:26px;height:26px;flex-shrink:0';
      swWrap.title='クリック: カラーピッカーで色変更 / Shift+クリック: 選択中の要素に割り当て';
      const sw=document.createElement('input');sw.type='color';try{sw.value=hex;}catch(_){}
      sw.style.cssText='width:26px;height:26px;border:1px solid rgba(255,255,255,.25);border-radius:5px;background:none;cursor:pointer;padding:0;box-sizing:border-box';
      swWrap.appendChild(sw);
      // hex 入力
      const tx=document.createElement('input');tx.type='text';tx.value=hex;tx.spellcheck=false;
      tx.style.cssText="flex:1 1 48px;min-width:48px;font:400 10.5px 'SF Mono','Menlo','Consolas',monospace;padding:3px;border:1px solid transparent;border-radius:3px;background:#fff;color:#121212;box-sizing:border-box";
      // 使用数
      const cnt=document.createElement('span');cnt.textContent=info.count+'箇所';cnt.title='この色がデッキで使われている回数';
      cnt.style.cssText='color:#8fa4b8;font:400 10px/1 sans-serif;margin-left:auto;text-align:right;flex-shrink:0';
      // ⌀透明 (背景系の色のときだけ)
      let clearBtn=null;
      if(info.kinds.has('bg')){
        clearBtn=document.createElement('button');clearBtn.textContent='⌀';clearBtn.title='この色を使う要素の背景を透明にする';
        clearBtn.style.cssText='padding:2px 6px;border:none;border-radius:3px;background:#16314c;color:#fff;font:600 11px/1 sans-serif;cursor:pointer;flex-shrink:0';
      }
      let cur=hex;
      function commit(nv){
        nv=(nv||'').trim();
        const norm=normHex(nv);
        if(!norm||norm===cur){tx.value=cur;return;}
        replaceColor(cur,norm);
        cur=norm;tx.value=norm;try{sw.value=norm;}catch(_){}
        // 変更フィードバック: 一瞬緑枠
        tx.style.borderColor='#38a169';
        setTimeout(()=>{tx.style.borderColor='transparent';},600);
      }
      // 🚫 3桁で即反映すると「#162a42」を打つ途中の #162（=#116622）でデッキ全体の色が置き換わり、
      //    元から #116622 だった要素まで巻き込んでいた（2026-09-27）
      tx.addEventListener('input',()=>{const v=(tx.value||'').trim();if(isHexTyped(v))commit(v);});
      tx.addEventListener('change',()=>commit(tx.value));
      tx.addEventListener('blur',()=>commit(tx.value));
      tx.addEventListener('keydown',e=>{if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){e.preventDefault();commit(tx.value);tx.blur();}});
      tx.addEventListener('focus',()=>{setTimeout(()=>{try{tx.select();}catch(_){}},0);});
      sw.addEventListener('input',()=>commit(sw.value));
      sw.addEventListener('change',()=>commit(sw.value));
      if(clearBtn){
        clearBtn.addEventListener('click',()=>{
          replaceColorTransparent(cur);
          // 透明化後は行を薄くする
          row.style.opacity='0.5';
          setTimeout(()=>rebuildPalette(),300);
        });
      }
      // Shift+クリック: 選択中の要素にこの色を割り当てる (旧「ラベル/見本クリック」機能を継承)
      // カラーピッカーは通常クリックで開くので、Shift 修飾で「適用」動作を分岐
      sw.addEventListener('click',(ev)=>{
        if(ev.shiftKey){
          ev.preventDefault();
          if(!sels.length){alert('先に要素を選択してください');return;}
          if(!isHex(cur))return;
          pushAttr(sels.slice());
          sels.forEach(el=>{
            if(el.classList&&el.classList.contains('tb')){
              el.setAttribute('data-color',cur);setStyleProp(el,'color',cur);
            }else if(el.classList&&el.classList.contains('rect')){
              el.setAttribute('data-fill',cur);setStyleProp(el,'background',cur);
            }else if(el.tagName==='TABLE'){
              el.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'color',cur));
              el.setAttribute('data-color',cur);
            }
          });
          dirty=true;
          if(typeof updateSelPanel==='function')updateSelPanel();
        }
      });
      // ホバー: 該当色の要素をスライド上でハイライト
      function highlightTargets(){const h=(cur||'').toLowerCase();document.querySelectorAll('.slide [data-color],.slide [data-fill],.slide [data-bg],.slide [data-bg-gradient]').forEach(el=>{const dc=(el.getAttribute('data-color')||'').toLowerCase();const df=(el.getAttribute('data-fill')||'').toLowerCase();const db=(el.getAttribute('data-bg')||'').toLowerCase();const dg=(el.getAttribute('data-bg-gradient')||'').toLowerCase();if(dc===h||df===h||db===h||dg.indexOf(h)>=0)el.classList.add('skit-pal-hl');});}
      function unhighlightTargets(){document.querySelectorAll('.skit-pal-hl').forEach(el=>el.classList.remove('skit-pal-hl'));}
      row.addEventListener('mouseenter',highlightTargets);
      row.addEventListener('mouseleave',unhighlightTargets);
      row.appendChild(swWrap);row.appendChild(tx);
      if(clearBtn)row.appendChild(clearBtn);
      row.appendChild(cnt);
      palList.appendChild(row);
    });
  }
  palRefresh.addEventListener('click',rebuildPalette);
  // 編集モード切替時に再スキャン (palRows 互換のため配列を保持)
  const palRows=[rebuildPalette];
  // ツールバー/パレット上の操作は document の編集ハンドラに横取りさせない
  // ただし input/textarea/button/select/label への操作は preventDefault しない
  // （ネイティブの focus・テキスト選択・カーソル位置指定を邪魔しないため）
  bar.addEventListener('mousedown',e=>{
    e.stopPropagation();
    const t=e.target;
    // button は preventDefault する（フォーカスを奪うと編集中tbのcontenteditableが外れ、
    // 「テキストまたは表を選択してください」になってカード内の個別書式変更ができない）
    if(t&&t.matches&&t.matches('input,textarea,select,label,option')){
      return;
    }
    e.preventDefault();
  });

  // ---- 選択中オブジェクトの個別色編集＋整列（パレットにない色もここで）----
  function setStyleProp(el,prop,val){const s=el.getAttribute('style')||'';const re=new RegExp('(^|;)\\s*'+prop+'\\s*:[^;]*','i');let ns;if(re.test(s))ns=s.replace(re,(m,p)=>p+prop+':'+val);else ns=(s?s.replace(/;?\s*$/,';'):'')+prop+':'+val;el.setAttribute('style',ns);}
  function hexInStyle(el,prop){const m=(el.getAttribute('style')||'').match(new RegExp('(?:^|;)\\s*'+prop+'[^;]*:\\s*(#[0-9a-fA-F]{3,8})','i'));return m?m[1]:null;}
  function elTextHex(el){const v=A(el,'data-color');if(v&&isHex(v))return v;if(el.tagName==='TABLE'){const c=el.querySelector('td,th');const h=c&&hexInStyle(c,'color');if(h)return h;}return hexInStyle(el,'color')||'#121212';}
  function elFillHex(el){const v=A(el,'data-fill');if(v==='none')return 'none';if(v&&isHex(v))return v;if(el.tagName==='TABLE'){const th=el.querySelector('th');const h=th&&hexInStyle(th,'background');if(h)return h;}return hexInStyle(el,'background')||'#edf2f4';}
  function applyTextSel(hex){if(!sels.length||!isHex(hex))return;const tc=targetCells();if(tc){tc.forEach(c=>setStyleProp(c,'color',hex));return;}sels.forEach(el=>{if(el.tagName==='TABLE'){el.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'color',hex));el.setAttribute('data-color',hex);}else{el.setAttribute('data-color',hex);setStyleProp(el,'color',hex);}});}
  function applyFillSel(hex){if(!sels.length||!isHex(hex))return;const tc=targetCells();if(tc){tc.forEach(c=>setStyleProp(c,'background',hex));return;}sels.forEach(el=>{if(el.tagName==='TABLE'){el.querySelectorAll('th').forEach(c=>setStyleProp(c,'background',hex));el.setAttribute('data-fill',hex);}else{el.setAttribute('data-fill',hex);setStyleProp(el,'background',hex);if(typeof refreshShapeOutline==='function')refreshShapeOutline(el);}});}
  function applyFillTransparent(){if(!sels.length)return;const tc=targetCells();if(tc){tc.forEach(c=>setStyleProp(c,'background','transparent'));return;}pushAttr(sels.slice());sels.forEach(el=>{if(el.tagName==='TABLE'){el.querySelectorAll('th').forEach(c=>setStyleProp(c,'background','transparent'));el.setAttribute('data-fill','none');}else{el.setAttribute('data-fill','none');setStyleProp(el,'background','transparent');if(typeof refreshShapeOutline==='function')refreshShapeOutline(el);}});}

  const selbar=document.createElement('div');selbar.className='seui skit-live';
  // 選択中パネルはコンテキスト依存で編集を進める中心的なパネルなので、
  // 共通パレット(pal) より前(上)に表示する。パネル内部でスクロールしない
  // (縦に伸びても bar 自体が overflow:auto なのでツールバー全体をスクロール可)
  selbar.style.cssText='display:none;flex-direction:column;gap:5px;background:rgba(31,122,90,.95);padding:9px 10px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.2)';
  bar.insertBefore(selbar, pal);
  const selTitle=document.createElement('div');selTitle.textContent='🎯 選択中 (Selected)';selTitle.style.cssText='color:#fff;font:700 12px/1 sans-serif;margin-bottom:2px';selbar.appendChild(selTitle);
  function mkSelRow(label,apply){
    const row=document.createElement('div');row.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px';
    const lb=document.createElement('span');lb.textContent=label;lb.style.cssText='color:#eafff6;font:600 10px/1.2 sans-serif;width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    const inputRow=document.createElement('div');inputRow.style.cssText='display:flex;align-items:center;gap:4px';
    const tx=document.createElement('input');tx.type='text';tx.spellcheck=false;tx.style.cssText="flex:1;min-width:0;font:400 11px 'SF Mono','Menlo','Consolas',monospace;letter-spacing:.3px;padding:2px 5px;border:none;border-radius:3px";
    const sw=document.createElement('input');sw.type='color';sw.style.cssText='width:22px;height:18px;border:none;background:none;cursor:pointer;padding:0;flex-shrink:0';
    let snapped=false;
    function pre(){if(!snapped&&sels.length){pushAttr(sels.slice());snapped=true;}}
    function done(v){v=(v||'').trim();if(!isHex(v))return;pre();apply(v);tx.value=v;try{sw.value=v;}catch(_){}}
    sw.addEventListener('input',()=>done(sw.value));
    sw.addEventListener('change',()=>{done(sw.value);snapped=false;});
    // text入力: input(6桁hex揃った瞬間) / change(blur) / Enter で確実に反映
    tx.addEventListener('input',()=>{const v=(tx.value||'').trim();if(isHexTyped(v))done(v);});
    tx.addEventListener('change',()=>{done(tx.value);snapped=false;});
    tx.addEventListener('blur',()=>{done(tx.value);snapped=false;});
    tx.addEventListener('keydown',e=>{if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){e.preventDefault();done(tx.value);snapped=false;tx.blur();}});
    // focus時に自動全選択（click→⌘Cでhexコピーが即できる）
    tx.addEventListener('focus',()=>{setTimeout(()=>{try{tx.select();}catch(_){}},0);});
    tx.addEventListener('click',()=>{try{if(tx.selectionStart===tx.selectionEnd)tx.select();}catch(_){}});
    row.appendChild(lb);inputRow.appendChild(tx);inputRow.appendChild(sw);row.appendChild(inputRow);selbar.appendChild(row);
    return {tx,sw,resetSnap:()=>{snapped=false;}};
  }
  // 選択物そのものへの操作（複製・コピー・削除）。「どこを押せばコピーできるか」を選択パネルの先頭に集める。
  // 貼付は選択が無い状態でも押せる必要があるのでツールバー側（#sePaste）に置く
  const actRow=document.createElement('div');actRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-bottom:3px;padding-bottom:7px;border-bottom:1px solid rgba(255,255,255,.25)';
  actRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">この図形を</span>'
    +'<div style="display:flex;flex-wrap:wrap;gap:3px"><button data-act="dup" title="同じページに少しずらして複製する（⌘D）">⧉ 複製</button>'
    +'<button data-act="copy" title="コピーする。別のページへ移ってツールバーの「📋 貼付（同じ位置）」か⌘Vで、同じ座標に貼れる（⌘C）">📋 コピー</button></div>'
    +'<div style="display:flex;flex-wrap:wrap;gap:3px"><button data-act="del" title="削除する（Delete）">🗑 削除</button><span style="flex:1"></span></div>'
    // 依頼の枠（data-ask＝イラスト・グラフ・写真）を選んだ時だけ出る。枠の中の依頼文をそのままコピーする（2026-10-14）
    +'<button data-act="ask" title="この枠の依頼文（何を描いてもらうか・どんなグラフを探すか）をコピーする。画像生成やKiroに貼る" style="display:none">📋 依頼文をコピー</button>'
    // 絵（SVG）を選んだ時だけ出る。BezierKitで開き、「スライドへ戻す」で差し替わる（2026-10-14）
    +'<button data-act="bezier" title="この絵をBezierKitで開いて編集する。BezierKitの「スライドへ戻す」でこの絵が差し替わる（作業データも絵の中に残る）" style="display:none">✏ BezierKitで編集</button>';
  selbar.insertBefore(actRow,selTitle.nextSibling);
  Array.from(actRow.querySelectorAll('button')).forEach(b=>{
    const del=b.dataset.act==='del'; // 削除だけ幅いっぱいにしない（誤クリック防止）
    b.style.cssText='padding:5px 8px;border:none;border-radius:6px;background:'+(del?'#7a2d2d':'#0d5a40')+';color:#fff;font-size:12px;cursor:pointer;'+(del?'flex:0 0 auto':'flex:1;min-width:70px');
  });
  actRow.addEventListener('click',function(e){
    const b=e.target.closest&&e.target.closest('button[data-act]');
    if(!b||!sels.length)return;
    const a=b.dataset.act;
    if(a==='dup')dupSelected();
    else if(a==='copy'){if(!copyEls(false))copyText(refTextOf(sels),null);} // data-xを持たない要素は参照テキストで代替（⌘Cと同じ挙動）
    else if(a==='del')delSelected();
    else if(a==='ask'){const z=sels[0];copyText(askPromptOf(z),null);flashSaved('依頼文をコピーしました。画像を貼ると、この枠に入ります');}
    else if(a==='bezier')openBezierEdit(sels[0]);
  });
  // 依頼の枠の文を、外へ渡せる形にする（枠の種類＋見えている文。区切りは改行）
  function askPromptOf(z){const kind={illust:'イラストを描いてください',chart:'このグラフを作るか、探してください',photo:'この写真を探すか、撮ってください'}[z.getAttribute('data-ask')]||'';
    return (kind?kind+'\n':'')+(z.innerText||z.textContent||'').trim()+'\n（スライドの枠: 幅'+A(z,'data-w')+'×高さ'+A(z,'data-h')+'px。画像に文字は入れない＝文字はスライド側で書く）';}
  function updateAskBtn(){const b=actRow.querySelector('[data-act="ask"]');if(b)b.style.display=(sels.length===1&&sels[0].hasAttribute&&sels[0].hasAttribute('data-ask'))?'block':'none';
    const z=actRow.querySelector('[data-act="bezier"]');if(z)z.style.display=(sels.length===1&&bezierSvgOf(sels[0]))?'block':'none';}
  // 絵として編集できるSVG＝要素の直下にあるsvg（グラフ data-chart は数値から描くので対象外）
  function bezierSvgOf(el){if(!el||!el.querySelector||el.hasAttribute('data-chart'))return null;const s=el.querySelector(':scope > svg');return s||null;}
  function openBezierEdit(el){
    const svg=bezierSvgOf(el);if(!svg)return;
    if(svg.querySelector('text')&&!svg.querySelector('metadata#bezierkit')&&
       !confirm('この絵の中の文字はBezierKitに持ち込めず、戻すと消えます。\n文字はスライドの文字枠（.tb）で重ねて書くと、PPTXでも直せます。\nこのまま開きますか？'))return;
    if(!el.getAttribute('data-bk-id'))el.setAttribute('data-bk-id','bk'+Date.now().toString(36));
    const payload={deck:deckKey(location.href),id:el.getAttribute('data-bk-id'),svg:svg.outerHTML,w:N(A(el,'data-w')),h:N(A(el,'data-h'))};
    try{localStorage.setItem('bkSlideEdit',JSON.stringify(payload));}catch(_){}
    const base=kitBase();const url=(base?new URL('../BezierKit/index.html',base).href:'../BezierKit/index.html')
      +'#editslide='+btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
    window.open(url,'_blank');
    flashSaved('BezierKitで開きました。編集したら「スライドへ戻す」を押してください');
  }
  // BezierKitから戻ってきた絵で差し替える（同じデッキ・同じ data-bk-id の要素だけ）
  window.addEventListener('storage',function(ev){
    if(ev.key!=='skBezierSlide'||!ev.newValue)return;
    let d;try{d=JSON.parse(ev.newValue);}catch(_){return;}
    if(!d||!d.svg||(d.deck&&d.deck!==deckKey(location.href)))return;
    const el=document.querySelector('[data-bk-id="'+d.id+'"]');const old=el&&bezierSvgOf(el);if(!old)return;
    const doc=new DOMParser().parseFromString(d.svg,'image/svg+xml');
    if(doc.querySelector('parsererror'))return;
    const neo=document.importNode(doc.documentElement,true);
    neo.querySelectorAll('script,foreignObject').forEach(n=>n.remove()); // 受け取るのは図形だけ
    neo.setAttribute('width',old.getAttribute('width')||'100%');neo.setAttribute('height',old.getAttribute('height')||'100%');
    if(old.getAttribute('role'))neo.setAttribute('role',old.getAttribute('role'));
    if(old.getAttribute('aria-label'))neo.setAttribute('aria-label',old.getAttribute('aria-label'));
    if(typeof pushAttr==='function')pushAttr([el]);
    old.replaceWith(neo);
    try{localStorage.removeItem('skBezierSlide');}catch(_){}
    flashSaved('BezierKitで直した絵に差し替えました（💾保存で確定・⌘Zで戻せます）');
  });
  const selText=mkSelRow('文字色',applyTextSel);
  // 実効表示色の注記（AWSフォーマット等のCSS上書きでdata-colorと見た目が違う時だけ出る）
  const selTextNote=document.createElement('div');
  selTextNote.style.cssText='display:none;color:#ffe9a8;font:600 10px/1.4 sans-serif;padding:1px 2px';
  selText.tx.parentElement.parentElement.after(selTextNote);
  const selFill=mkSelRow('背景/塗り',applyFillSel);
  // 「⌀透明」ボタン（台座を塗りなしに）
  (function(){
    const btn=document.createElement('button');
    btn.textContent='⌀透明';
    btn.title='選択中の台座を塗りなし（透明）にする';
    // 狭い右パネルでは入力欄を潰さないよう、次の段に幅いっぱいで置く（2026-09-27）
    btn.style.cssText='flex:1 0 100%;padding:4px 9px;border:none;border-radius:5px;background:#16314c;color:#fff;font:600 11px/1 sans-serif;cursor:pointer;white-space:nowrap';
    selFill.tx.parentElement.style.flexWrap='wrap';
    btn.addEventListener('click',()=>{applyFillTransparent();selFill.tx.value='none';try{selFill.sw.value='#ffffff';}catch(_){}});
    selFill.tx.parentElement.appendChild(btn);
  })();
  // 親子リンク表示行（子＝data-linked-parent持ちが1個選択された時に出る）
  const linkRow=document.createElement('div');linkRow.id='seLinkRow';linkRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  linkRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">🔗 親と連動中</span>'
    +'<span style="color:#aedccb;font:500 10px/1.3 sans-serif;display:block">親カードを動かすと一緒に動く</span>'
    +'<button id="seUnlink" title="親子関係を解除（個別に動かせるようになる）" style="margin-top:4px;padding:5px 10px;border:none;border-radius:6px;background:#7a2d2d;color:#fff;font:600 12px sans-serif;cursor:pointer">🔗✕ リンク解除</button>';
  selbar.appendChild(linkRow);
  linkRow.querySelector('#seUnlink').addEventListener('click',function(){
    if(sels.length!==1)return;
    const c=sels[0];if(!c.hasAttribute('data-linked-parent'))return;
    pushAttr([c]);c.removeAttribute('data-linked-parent');
    updateSelPanel();
  });
  // フォントサイズ＋太字（data-font-size / data-bold＝PPTX対応。書体はYu Gothic固定なので変更不可）
  const fontRow=document.createElement('div');fontRow.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  fontRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">サイズ/太字</span>'
    +'<div style="display:flex;gap:4px;align-items:stretch">'
    +'<div style="display:flex;flex-direction:column;gap:3px;align-items:center"><span style="color:#9fe8cf;font:600 9px monospace">px</span>'
    +'<button data-fz="2" style="width:42px">＋</button>'
    +'<input id="seFz" type="text" inputmode="numeric" style="width:42px;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:4px">'
    +'<button data-fz="-2" style="width:42px">－</button></div>'
    +'<div style="display:flex;flex-direction:column;gap:3px;align-items:center"><span title="PPTX変換後のサイズ（1px=0.75pt）" style="color:#9fe8cf;font:600 9px monospace">pt</span>'
    +'<button data-fzpt="1" style="width:42px">＋</button>'
    +'<input id="seFzPtIn" type="text" inputmode="decimal" style="width:42px;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:4px;background:#e6fff5">'
    +'<button data-fzpt="-1" style="width:42px">－</button></div>'
    +'</div>'
    +'<button data-fz="bold" style="margin-top:6px;font-weight:700;width:88px">B</button>';
  selbar.appendChild(fontRow);
  Array.from(fontRow.querySelectorAll('button')).forEach(b=>b.style.cssText+=';padding:3px 9px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer');
  const fzInput=fontRow.querySelector('#seFz');
  const fzPtIn=fontRow.querySelector('#seFzPtIn');
  // PPTX変換後のpt値を併記（html_to_pptx.pyと同じ 1px=0.75pt 換算）
  const updFzPt=()=>{if(!fzPtIn)return;const v=parseFloat(fzInput&&fzInput.value);fzPtIn.value=(v>0)?String(Math.round(v*75)/100):'';};
  // 編集中(contenteditable)のtbを拾う。ボタン操作でフォーカスが外れても直前のtbを覚えておく。
  // カード(.rect/.flow)の中の見出しと説明を別々に編集するために必要。
  let lastEditTb=null;
  document.addEventListener('focusin',function(e){
    const t=e.target;if(!t||!t.closest)return;
    const tb=t.closest('.tb');
    if(tb&&tb.isContentEditable)lastEditTb=tb;
  },true);
  const editingTb=()=>{
    const ae=document.activeElement;
    if(ae&&ae.isContentEditable&&ae.closest){const tb=ae.closest('.tb');if(tb)return tb;}
    // isContentEditable が false になった(編集モードを抜けた)tbは対象にしない
    if(lastEditTb&&lastEditTb.isConnected&&lastEditTb.isContentEditable)return lastEditTb;
    return null;
  };
  const selTbs=()=>{const fromSels=sels.filter(el=>el.classList&&el.classList.contains('tb'));if(fromSels.length)return fromSels;const et=editingTb();if(et)return [et];return [];};
  // フォントサイズ/太字の対象: 選択中のtb＋選択中コンテナ(rect等)内の全tb。
  // 複数選択(マーキー)でカードごと選んだ時に中の文字をまとめて変えられる
  const fsTbs=()=>{const out=[],seen=new Set();const add=el=>{if(el&&!seen.has(el)){seen.add(el);out.push(el);}};
    // 文字編集中(contenteditable)のtbがあればそれだけを対象にする。
    // カード(.rect/.flow)の中の見出しと説明を別々のサイズにしたい時のため。
    // ダブルクリックで編集モードに入れば、カードが選択されたままでも1つだけ変わる（selTbsと同じ優先順）
    {const et=editingTb();if(et)return [et];}
    sels.forEach(el=>{if(el.classList&&el.classList.contains('tb'))add(el);
      else if(el.tagName!=='TABLE'&&el.tagName!=='IMG'&&el.querySelectorAll)el.querySelectorAll('.tb').forEach(add);});
    if(!out.length){const ae=document.activeElement;if(ae&&ae.isContentEditable){const tb=ae.closest&&ae.closest('.tb');if(tb)add(tb);}}
    return out;};
  fontRow.addEventListener('click',function(e){
    const v=e.target.getAttribute&&e.target.getAttribute('data-fz');
    const vp=e.target.getAttribute&&e.target.getAttribute('data-fzpt');
    if(!v&&!vp)return;
    const tbs=fsTbs(),tbls=selTables(),tc=targetCells();if(!tbs.length&&!tbls.length){alert('文字（テキスト）または表を選択してください');return;}
    pushAttr(sels.slice().concat(tbs.filter(t=>!sels.includes(t))));
    if(v==='bold'){const on=tbs.length?!(A(tbs[0],'data-bold')==='1'):true;tbs.forEach(el=>setBold(el,on));if(tc)tc.forEach(c=>setStyleProp(c,'font-weight',on?'700':'400'));else tbls.forEach(t=>tblBold(t,on));e.target.style.background=on?'#0a7d55':'#0d5a40';}
    else if(vp){const dp=parseInt(vp,10);const toPx=pt=>Math.round(pt*4/3*100)/100;const nextPx=cur=>toPx(Math.max(6,Math.round((cur||16)*0.75)+dp));
      tbs.forEach(el=>setFS(el,nextPx(N(A(el,'data-font-size')))));
      if(tc)tc.forEach(c=>setStyleProp(c,'font-size',nextPx(parseFloat(getComputedStyle(c).fontSize))+'px'));
      else tbls.forEach(t=>setTblFS(t,nextPx(tblFS(t))));}
    else{const d=parseInt(v,10);tbs.forEach(el=>setFS(el,N(A(el,'data-font-size'))+d));if(tc)tc.forEach(c=>{const cur=parseFloat(getComputedStyle(c).fontSize)||16;setStyleProp(c,'font-size',Math.max(8,Math.round(cur+d))+'px');});else tbls.forEach(t=>setTblFS(t,tblFS(t)+d));}
    if(fzInput){if(tbs[0])fzInput.value=N(A(tbs[0],'data-font-size'));else if(tc&&tc[0])fzInput.value=parseFloat(getComputedStyle(tc[0]).fontSize)||16;else if(tbls[0])fzInput.value=tblFS(tbls[0]);}updFzPt();placeBox();
  });
  // pt欄への直接入力: pt→px換算(1pt=4/3px)して適用
  fzPtIn&&fzPtIn.addEventListener('change',function(){const tbs=fsTbs(),tbls=selTables(),tc=targetCells();if(!tbs.length&&!tbls.length)return;const pv=parseFloat(fzPtIn.value);if(!pv)return;const fv=Math.round(pv*4/3*100)/100;pushAttr(sels.slice().concat(tbs.filter(t=>!sels.includes(t))));tbs.forEach(el=>setFS(el,fv));if(tc)tc.forEach(c=>setStyleProp(c,'font-size',Math.max(8,fv)+'px'));else tbls.forEach(t=>setTblFS(t,fv));if(fzInput)fzInput.value=tbs[0]?N(A(tbs[0],'data-font-size')):fv;updFzPt();placeBox();});
  fzInput&&fzInput.addEventListener('change',function(){const tbs=fsTbs(),tbls=selTables(),tc=targetCells();if(!tbs.length&&!tbls.length)return;const fv=parseInt(fzInput.value,10);if(!fv)return;pushAttr(sels.slice().concat(tbs.filter(t=>!sels.includes(t))));tbs.forEach(el=>setFS(el,fv));if(tc)tc.forEach(c=>setStyleProp(c,'font-size',Math.max(8,fv)+'px'));else tbls.forEach(t=>setTblFS(t,fv));fzInput.value=tbs[0]?N(A(tbs[0],'data-font-size')):fv;updFzPt();placeBox();});
  // 箇条書きマーカー（・/①）＋ぶら下げインデント（折り返しがマーカーの下に潜らず本文に揃う）。data-bulletに記録
  const bulletRow=document.createElement('div');bulletRow.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  bulletRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">箇条書き（1枠1項目）</span><button data-bl="disc">・</button><button data-bl="decimal">①②③</button><button data-bl="none">なし</button>'
    +'<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block;margin-top:5px">PowerPoint形式（Tabで階層）</span>'
    +'<div style="display:flex;gap:3px"><button data-bl="native-disc" style="flex:1">・</button><button data-bl="native-decimal" style="flex:1">①②③</button></div>'
    +'<span style="color:#aedccb;font:500 10px/1.3 sans-serif;width:100%;display:block">Enterで項目追加／Tab・Shift+Tabで階層</span>';
  selbar.appendChild(bulletRow);
  Array.from(bulletRow.querySelectorAll('button')).forEach(b=>b.style.cssText=(b.style.cssText||'')+';padding:3px 10px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer');
  // 2つ横並びの「①②③」が狭い右パネルで2段に割れないよう、この行だけ文字を小さくする（2026-09-27）
  const nbDec=bulletRow.querySelector('[data-bl="native-decimal"]');if(nbDec)nbDec.style.fontSize='11px';
  function circledNum(i){return (i>=1&&i<=20)?String.fromCharCode(0x245F+i):(i+'.');}
  function stripMarker(html){return html.replace(/^\s*(?:[・･‣•]\s*|[\u2460-\u2473]\s*|\(?\d+[.)、]\s*)/,'');}
  // ---- ネイティブ箇条書き（.li[data-lvl]）の操作 ----
  const isNativeBullet=el=>((el&&el.getAttribute&&el.getAttribute('data-bullet'))||'').indexOf('native-')===0;
  const liItems=el=>Array.from(el.children).filter(c=>c.classList&&c.classList.contains('li'));
  function clampLvl(v){const n=parseInt(v,10);return Math.max(0,Math.min(isNaN(n)?0:n,listMaxLevel()-1));}
  // 既存の中身を「行」に分解する（.li構造 → そのまま／<br>区切り → 1行1項目）
  function splitLines(el){
    const lis=liItems(el);
    if(lis.length)return lis.map(c=>({html:c.innerHTML,lvl:clampLvl(c.getAttribute('data-lvl'))}));
    return el.innerHTML.split(/<br\s*\/?>/i)
      .map(h=>({html:stripMarker(h).trim(),lvl:0}))
      .filter(x=>x.html!==''&&x.html!=='<br>');
  }
  // .li構造 → <br>区切りのテキストに戻す（旧方式へ切り替える時・解除する時）
  function flattenLi(el){
    const lis=liItems(el);
    if(!lis.length)return el.innerHTML;
    return lis.map(c=>c.innerHTML.trim()).join('<br>');
  }
  function toNativeList(el,kind){
    const lines=splitLines(el);
    el.setAttribute('data-bullet',kind);
    el.innerHTML=lines.map(l=>'<div class="li" data-lvl="'+l.lvl+'">'+(l.html||'<br>')+'</div>').join('');
    // 字下げはCSS（.li側）が持つので、旧方式のtb直指定は外す
    rmStyleProp(el,'padding-left');rmStyleProp(el,'text-indent');
  }
  function applyBullet(kind){
    const tbs=selTbs();if(!tbs.length){alert('テキスト（テキストボックス）を選択してください');return;}
    pushAttr(sels.slice());
    if(kind==='native-disc'||kind==='native-decimal'){ensureListCss();tbs.forEach(el=>toNativeList(el,kind));placeBox();return;}
    let n=1;
    tbs.forEach(el=>{
      const html=stripMarker(flattenLi(el));
      if(kind==='disc'){el.setAttribute('data-bullet','disc');el.innerHTML='・'+html;setStyleProp(el,'padding-left','1.4em');setStyleProp(el,'text-indent','-1.4em');}
      else if(kind==='decimal'){el.setAttribute('data-bullet','decimal');el.innerHTML=circledNum(n)+' '+html;n++;setStyleProp(el,'padding-left','1.9em');setStyleProp(el,'text-indent','-1.9em');}
      else{el.removeAttribute('data-bullet');el.innerHTML=html;setStyleProp(el,'padding-left','0');setStyleProp(el,'text-indent','0');}
    });
    placeBox();
  }
  bulletRow.addEventListener('click',function(e){const k=e.target.getAttribute&&e.target.getAttribute('data-bl');if(k)applyBullet(k);});
  // 編集中のカーソル位置から .li を得る
  function liOf(node){let n=node;while(n&&n!==document.body){if(n.classList&&n.classList.contains('li'))return n;n=n.parentNode;}return null;}
  function caretLi(){const s=window.getSelection();if(!s||!s.rangeCount)return null;return liOf(s.getRangeAt(0).startContainer);}
  function shiftLvl(li,d){li.setAttribute('data-lvl',clampLvl(parseInt(li.getAttribute('data-lvl')||'0',10)+d));}
  // Enter: カーソル位置で項目を分割して同レベルの新項目を作る（ブラウザ既定のdiv生成に任せない）
  function splitLiAtCaret(li){
    const s=window.getSelection();if(!s||!s.rangeCount)return;
    const r=s.getRangeAt(0);
    r.deleteContents();
    const tail=document.createRange();
    tail.setStart(r.endContainer,r.endOffset);
    tail.setEnd(li,li.childNodes.length);
    const nl=document.createElement('div');
    nl.className='li';nl.setAttribute('data-lvl',clampLvl(li.getAttribute('data-lvl')));
    nl.appendChild(tail.extractContents());
    if(!nl.textContent.length)nl.appendChild(document.createElement('br'));
    if(!li.textContent.length&&!li.querySelector('br'))li.appendChild(document.createElement('br'));
    li.parentNode.insertBefore(nl,li.nextSibling);
    const c=document.createRange();c.setStart(nl,0);c.collapse(true);
    s.removeAllRanges();s.addRange(c);
  }
  // 直接子が .li 以外になった時（ペースト等）の後始末。カーソルに影響しない blur 時だけ呼ぶ
  function normalizeList(tb){
    let lvl=0;
    Array.from(tb.childNodes).forEach(n=>{
      if(n.nodeType===3){
        if(!n.textContent.trim()){tb.removeChild(n);return;}
        const d=document.createElement('div');d.className='li';d.setAttribute('data-lvl',lvl);
        tb.insertBefore(d,n);d.appendChild(n);return;
      }
      if(n.nodeType!==1)return;
      if(n.tagName==='BR'){tb.removeChild(n);return;}
      if(!n.classList.contains('li')){
        if(n.tagName==='DIV'||n.tagName==='P'){n.classList.add('li');n.setAttribute('data-lvl',lvl);}
        else{const d=document.createElement('div');d.className='li';d.setAttribute('data-lvl',lvl);tb.insertBefore(d,n);d.appendChild(n);n=d;}
      }
      n.setAttribute('data-lvl',clampLvl(n.getAttribute('data-lvl')));
      lvl=clampLvl(n.getAttribute('data-lvl'));
    });
  }
  document.addEventListener('keydown',function(e){
    if(!editing)return;
    // 文字編集中の判定はカーソル位置（.li）から取る。activeElement 依存にすると
    // 親tbにフォーカスが乗る/乗らないの差で拾えないことがある
    const li=caretLi();
    const tbEdit=(li&&li.closest)?li.closest('.tb'):null;
    const typing=tbEdit&&(tbEdit.getAttribute('contenteditable')==='true'||tbEdit.isContentEditable);
    if(typing&&isNativeBullet(tbEdit)){
      if(e.key==='Tab'&&!e.metaKey&&!e.ctrlKey&&!e.altKey){e.preventDefault();pushAttr([tbEdit]);shiftLvl(li,e.shiftKey?-1:1);return;}
      if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)&&!e.shiftKey&&!e.metaKey&&!e.ctrlKey){e.preventDefault();pushAttr([tbEdit]);splitLiAtCaret(li);return;}
      return;
    }
    // 編集中でない時のTab＝選択中tbの全項目をまとめて1段送り／戻し
    if(e.key!=='Tab'||e.metaKey||e.ctrlKey||e.altKey)return;
    if(isInputFocused())return;
    const tbs=selTbs().filter(isNativeBullet);
    if(!tbs.length)return;
    e.preventDefault();pushAttr(sels.slice());
    tbs.forEach(el=>liItems(el).forEach(li=>shiftLvl(li,e.shiftKey?-1:1)));
  },true);
  document.addEventListener('focusout',function(e){
    const tb=e.target&&e.target.closest&&e.target.closest('.tb');
    if(tb&&isNativeBullet(tb))normalizeList(tb);
  },true);
  // 文字ぞろえ（左/中央/右）＝data-align＋text-align。縦位置（上/中/下）＝data-valign＋flex
  function rmStyleProp(el,prop){const s=el.getAttribute('style')||'';const parts=s.split(';').map(x=>x.trim()).filter(Boolean).filter(p=>p.split(':')[0].trim().toLowerCase()!==prop.toLowerCase());el.setAttribute('style',parts.join(';')+(parts.length?';':''));}
  function alignItemsFor(a){return a==='center'?'center':(a==='right'?'flex-end':'flex-start');}
  // テーブル用ヘルパー（選択＝表のとき、中身全セルにまとめて適用）
  function selTables(){return sels.filter(el=>el.tagName==='TABLE');}
  function tblFS(t){const c=t.querySelector('td,th');if(c){const m=(c.getAttribute('style')||'').match(/font-size:\s*(\d+)/);if(m)return parseInt(m[1],10);const cs=parseFloat(getComputedStyle(c).fontSize);if(cs)return Math.round(cs);}const m2=(t.getAttribute('style')||'').match(/font-size:\s*(\d+)/);return m2?parseInt(m2[1],10):16;}
  function setTblFS(t,fs){fs=Math.max(8,Math.round(fs*100)/100);setStyleProp(t,'font-size',fs+'px');t.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'font-size',fs+'px'));}
  function tblBold(t,on){t.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'font-weight',on?'700':'400'));}
  function tblTextAlign(t,val){t.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'text-align',val));}
  function tblValign(t,val){t.querySelectorAll('td,th').forEach(c=>setStyleProp(c,'vertical-align',val==='middle'?'middle':(val==='bottom'?'bottom':'top')));}
  // ---- 表のセル範囲選択（表を選択中にセルをドラッグ＝Excel風の矩形選択）----
  function cellPos(t,cell){for(let r=0;r<t.rows.length;r++){const cs=t.rows[r].cells;for(let c=0;c<cs.length;c++)if(cs[c]===cell)return {r,c};}return null;}
  function cellsInRange(t,a,b){const r1=Math.min(a.r,b.r),r2=Math.max(a.r,b.r),c1=Math.min(a.c,b.c),c2=Math.max(a.c,b.c),out=[];for(let r=r1;r<=r2&&r<t.rows.length;r++){const cs=t.rows[r].cells;for(let c=c1;c<=c2&&c<cs.length;c++)out.push(cs[c]);}return out;}
  function cellSelClear(){cellSel.forEach(c=>{c.style.outline='';c.style.outlineOffset='';});cellSel=[];cellTable=null;cellAnchor=null;}
  function cellSelSet(arr){cellSel.forEach(c=>{c.style.outline='';c.style.outlineOffset='';});cellSel=arr.slice();cellSel.forEach(c=>{c.style.outline='2px solid #1f7a5a';c.style.outlineOffset='-2px';});}
  // 対象セル（範囲選択があればそれ、無ければnull＝表全体）
  function targetCells(){return cellSel.length?cellSel.slice():null;}
  // 枠線の色・太さ（選択セル or 表全体の全セル）
  function applyCellBorder(t,w,color){const cells=(targetCells()&&targetCells().every(c=>c.closest('table')===t))?targetCells():[...t.querySelectorAll('td,th')];cells.forEach(c=>setStyleProp(c,'border',(w<=0?'none':(w+'px solid '+color))));}
  // 列幅：その列の全セルにwidthを設定。行高：その行の全セルにheightを設定
  function setColWidth(t,idx,w){w=Math.max(24,Math.round(w));for(let r=0;r<t.rows.length;r++){const c=t.rows[r].cells[idx];if(c)setStyleProp(c,'width',w+'px');}}
  function setRowHeight(tr,h){h=Math.max(16,Math.round(h));[...tr.cells].forEach(c=>setStyleProp(c,'height',h+'px'));}
  function applyTextAlign(val){const tbs=selTbs(),tbls=selTables(),tc=targetCells();if(!tbs.length&&!tbls.length){alert('テキストまたは表を選択してください');return;}pushAttr(sels.slice());tbs.forEach(el=>{el.setAttribute('data-align',val);setStyleProp(el,'text-align',val);if((A(el,'data-valign')||'')!=='')setStyleProp(el,'align-items',alignItemsFor(val));});if(tc)tc.forEach(c=>setStyleProp(c,'text-align',val));else tbls.forEach(t=>tblTextAlign(t,val));placeBox();}
  function applyValign(val){const tbs=selTbs(),tbls=selTables(),tc=targetCells();if(!tbs.length&&!tbls.length){alert('テキストまたは表を選択してください');return;}pushAttr(sels.slice());tbs.forEach(el=>{if(val==='top'){el.removeAttribute('data-valign');rmStyleProp(el,'display');rmStyleProp(el,'flex-direction');rmStyleProp(el,'justify-content');rmStyleProp(el,'align-items');}else{el.setAttribute('data-valign',val);setStyleProp(el,'display','flex');setStyleProp(el,'flex-direction','column');setStyleProp(el,'justify-content',val==='middle'?'center':'flex-end');setStyleProp(el,'align-items',alignItemsFor(A(el,'data-align')||'left'));}});if(tc)tc.forEach(c=>setStyleProp(c,'vertical-align',val==='middle'?'middle':(val==='bottom'?'bottom':'top')));else tbls.forEach(t=>tblValign(t,val));placeBox();}
  // 文字ぞろえ: 横並び (左/中央/右 は水平位置の意味なので横並びが自然)
  const taRow=document.createElement('div');taRow.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  taRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">文字ぞろえ</span>'
    +'<div style="display:flex;gap:3px"><button data-ta="left" title="左ぞろえ">左</button><button data-ta="center" title="中央ぞろえ">中</button><button data-ta="right" title="右ぞろえ">右</button></div>';
  selbar.appendChild(taRow);
  Array.from(taRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:3px 8px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer');
  taRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-ta');if(v)applyTextAlign(v);});
  const vaRow=document.createElement('div');vaRow.style.cssText='display:flex;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  vaRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">縦位置</span><button data-va="top">上</button><button data-va="middle">中</button><button data-va="bottom">下</button>';
  selbar.appendChild(vaRow);
  Array.from(vaRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:3px 10px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer');
  vaRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-va');if(v)applyValign(v);});

  // 枠線(border)行：rect/tb選択時に表示。位置・太さ・色・線スタイル
  const borderRow=document.createElement('div');borderRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  borderRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">枠線</span>'
    +'<div style="display:flex;gap:4px;margin-top:2px"><button data-bd="none" title="なし" class="bd-big">⊘ なし</button><button data-bd="all" title="全周" class="bd-big bd-mini bd-all"></button></div>'
    +'<div data-grp="pos" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px;margin-top:3px">'
    +'<span></span><button data-bd="top" title="上のみ" class="bd-mini bd-top"></button><span></span>'
    +'<button data-bd="left" title="左のみ" class="bd-mini bd-left"></button><span style="display:flex;align-items:center;justify-content:center;color:#aedccb;font:600 10px/1 sans-serif;height:32px">位置</span><button data-bd="right" title="右のみ" class="bd-mini bd-right"></button>'
    +'<span></span><button data-bd="bottom" title="下のみ" class="bd-mini bd-bottom"></button><span></span>'
    +'</div>'
    +'<div style="display:flex;align-items:center;gap:4px;margin-top:2px">'
    +'<button data-bdw="-1">−</button>'
    +'<input id="seBdW" type="text" inputmode="numeric" value="3" style="flex:1;min-width:0;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:3px">'
    +'<button data-bdw="1">＋</button>'
    +'</div>'
    +'<div style="display:flex;align-items:center;gap:4px;margin-top:2px">'
    +'<input id="seBdC" type="text" spellcheck="false" value="#162a42" style="flex:1;min-width:0;font:400 11px monospace;padding:2px 5px;border:none;border-radius:3px">'
    +'<input id="seBdSw" type="color" value="#162a42" style="width:22px;height:18px;border:none;background:none;cursor:pointer;padding:0;flex-shrink:0">'
    +'</div>'
    +'<div data-grp="style" style="display:flex;flex-wrap:wrap;gap:2px;margin-top:2px"><button data-bds="solid" title="実線">━</button><button data-bds="dashed" title="破線">╌</button><button data-bds="dotted" title="点線">⋯</button><button data-bds="double" title="二重">═</button><button data-bds="wavy" title="波線">〰</button></div>';
  selbar.appendChild(borderRow);
  Array.from(borderRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:3px 8px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer;flex:1;min-width:30px');
  // 太さの−／＋は固定幅にして、間の数値欄を潰さない（2026-09-27 右パネルを2/3幅にした時）
  Array.from(borderRow.querySelectorAll('button[data-bdw]')).forEach(b=>{b.style.flex='0 0 28px';b.style.minWidth='0';b.style.padding='3px 0';});
  const bdwInput=borderRow.querySelector('#seBdW');
  const bdcInput=borderRow.querySelector('#seBdC');
  const bdcSw=borderRow.querySelector('#seBdSw');
  function parseBorder(v){if(!v)return null;const m=v.match(/^(\d+)\s*,\s*(#[0-9a-fA-F]{3,8})(?:\s*,\s*(\w+))?$/);if(!m)return null;return{w:parseInt(m[1],10),c:m[2],s:m[3]||'solid'};}
  function canBorder(el){return el&&el.classList&&(el.classList.contains('rect')||el.classList.contains('tb')||el.classList.contains('ins'));}
  function getBorderState(el){
    if(!canBorder(el)){return{pos:'none',w:3,c:'#162a42',s:'solid'};}
    for(const k of ['','top','right','bottom','left']){
      const attr=k?('data-border-'+k):'data-border';
      const v=el.getAttribute(attr);if(!v)continue;
      const p=parseBorder(v);if(p)return{pos:k||'all',w:p.w,c:p.c,s:p.s};
    }
    return{pos:'none',w:3,c:'#162a42',s:'solid'};
  }
  function applyBorder(pos,w,c,style){
    if(!sels.length)return;
    pushAttr(sels.slice());
    // CSSにない波線はdashedで代用（PPTXのSQUARE_DOT/WAVY等にマップする想定）
    const cssStyle=(style==='wavy')?'dashed':style;
    sels.forEach(el=>{
      // clip-path系図形（矢印/帯矢印/三角）はCSS borderだと四角い箱に線が付くので、
      // データは同じdata-borderに持ちつつ、描画はSVG輪郭stroke（refreshShapeOutline）で行う
      const isPoly=(typeof shapeOutlinePts==='function')&&!!shapeOutlinePts(el);
      // 枠線変更前の各辺の太さ（中身エリアを維持するため）
      const old={t:0,r:0,b:0,l:0};
      const hadCssBorder=/(^|;)\s*border(-top|-right|-bottom|-left)?\s*:\s*\d/.test(el.getAttribute('style')||'');
      const oa=A(el,'data-border');
      if(oa){const p=parseBorder(oa);if(p){old.t=old.r=old.b=old.l=p.w;}}
      ['top','right','bottom','left'].forEach(k=>{const v=A(el,'data-border-'+k);if(v){const p=parseBorder(v);if(p)old[k[0]]=p.w;}});
      if(isPoly&&!hadCssBorder){old.t=old.r=old.b=old.l=0;} // SVG輪郭描画は箱サイズに影響しないため補正不要
      const nw={t:0,r:0,b:0,l:0};
      if(!(pos==='none'||w<=0)&&!isPoly){
        if(pos==='all'){nw.t=nw.r=nw.b=nw.l=w;}else{nw[pos[0]]=w;}
      }
      ['data-border','data-border-top','data-border-right','data-border-bottom','data-border-left','data-border-style'].forEach(a=>el.removeAttribute(a));
      ['border','border-top','border-right','border-bottom','border-left'].forEach(p=>setStyleProp(el,p,''));
      if(!(pos==='none'||w<=0)){
        const val=w+','+c+(style!=='solid'?(','+style):'');
        if(isPoly){el.setAttribute('data-border',val);} // 図形は全周のみ（PPTXのshape.line輪郭に対応）
        else if(pos==='all'){el.setAttribute('data-border',val);setStyleProp(el,'border',w+'px '+cssStyle+' '+c);}
        else{el.setAttribute('data-border-'+pos,val);setStyleProp(el,'border-'+pos,w+'px '+cssStyle+' '+c);}
        if(style==='wavy')el.setAttribute('data-border-style','wavy');
      }
      if(isPoly)refreshShapeOutline(el);
      // box-sizing:border-boxの中身エリアを維持＝枠線増分だけ data-w/h を膨らませ、data-x/y を左/上枠分縮める
      const dl=nw.l-old.l, dt=nw.t-old.t, dr=nw.r-old.r, db=nw.b-old.b;
      const dW=dl+dr, dH=dt+db;
      if(el.hasAttribute('data-x')&&dl!==0){setX(el,(N(A(el,'data-x'))||0)-dl);}
      if(el.hasAttribute('data-y')&&dt!==0){setY(el,(N(A(el,'data-y'))||0)-dt);}
      if(el.hasAttribute('data-w')&&dW!==0){setW(el,Math.max(8,(N(A(el,'data-w'))||0)+dW));}
      if(el.hasAttribute('data-h')&&dH!==0){setH(el,Math.max(8,(N(A(el,'data-h'))||0)+dH));}
    });
    placeBox();
  }
  borderRow.addEventListener('click',function(e){
    const pos=e.target.getAttribute&&e.target.getAttribute('data-bd');
    const dw=e.target.getAttribute&&e.target.getAttribute('data-bdw');
    const sty=e.target.getAttribute&&e.target.getAttribute('data-bds');
    const cur=getBorderState(sels[0]);
    const w=Math.max(0,parseInt(bdwInput.value,10)||3);
    const c=(bdcInput.value||'#162a42').trim();
    if(pos){applyBorder(pos,w,c,cur.s||'solid');}
    else if(dw){const nw=Math.max(0,(parseInt(bdwInput.value,10)||0)+parseInt(dw,10));bdwInput.value=nw;if(cur.pos!=='none')applyBorder(cur.pos,nw,c,cur.s||'solid');}
    else if(sty){if(cur.pos!=='none')applyBorder(cur.pos,w,c,sty);}
    if(sels[0]){const st=getBorderState(sels[0]);bdwInput.value=st.w;bdcInput.value=st.c;try{bdcSw.value=st.c;}catch(_){}}
  });
  bdcInput.addEventListener('change',function(){const c=(bdcInput.value||'').trim();if(!isHex(c))return;try{bdcSw.value=c;}catch(_){}const st=getBorderState(sels[0]);if(st.pos!=='none')applyBorder(st.pos,st.w,c,st.s||'solid');});
  bdcSw.addEventListener('input',function(){bdcInput.value=bdcSw.value;const st=getBorderState(sels[0]);if(st.pos!=='none')applyBorder(st.pos,st.w,bdcSw.value,st.s||'solid');});

  // ---- カードスタイル: rect 選択時に表示。プリセット3種で見た目を一発切替 ----
  // ・ベタ塗り (solid) = 塗り色維持 / 枠線なし
  // ・白に薄い枠 (outlined) = data-fill=#ffffff / 1px solid #d6dde3 / border-radius:8px
  // ・透明 (transparent) = data-fill=none / 枠線なし
  const cardStyleRow=document.createElement('div');
  cardStyleRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  cardStyleRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">カードスタイル</span>'
    +'<div style="display:flex;gap:3px"><button data-cs="solid" title="ベタ塗り (塗り色+枠なし)">塗り</button>'
    +'<button data-cs="outlined" title="白に薄い枠線">枠線</button>'
    +'<button data-cs="transparent" title="透明 (塗り/枠なし)">透明</button></div>'
    +'<button data-cs="shadow" title="薄い影 ON/OFF (現状のスタイルに加算)" style="margin-top:2px">🌫 薄い影</button>';
  selbar.appendChild(cardStyleRow);
  Array.from(cardStyleRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:4px 6px;border:none;border-radius:5px;background:#0d5a40;color:#fff;font-size:11px;cursor:pointer;white-space:nowrap');
  function isCardRect(el){
    if(!el||!el.classList||!el.classList.contains('rect'))return false;
    // 図形系 (circle/triangle/line/arrow/chevron) は除外
    const ds=A(el,'data-shape');
    return ['circle','triangle','line','arrow','chevron'].indexOf(ds)<0;
  }
  // 薄い影 CSS。PPTX変換では data-shadow="soft" を見て outerShdw 効果を付ける
  const SOFT_SHADOW_CSS='0 2px 8px rgba(0,0,0,.08)';
  function applyCardStyle(kind){
    const rects=sels.filter(isCardRect);
    if(!rects.length)return;
    pushAttr(rects.slice());
    if(kind==='shadow'){
      // トグル: 全rectについて、現状の data-shadow に基づいて on/off 切替
      // 選択の先頭が off なら全部 ON、on なら全部 OFF
      const willOn=!(A(rects[0],'data-shadow')==='soft');
      rects.forEach(el=>{
        if(willOn){
          el.setAttribute('data-shadow','soft');
          setStyleProp(el,'box-shadow',SOFT_SHADOW_CSS);
        }else{
          el.removeAttribute('data-shadow');
          rmStyleProp(el,'box-shadow');
        }
      });
      dirty=true;
      if(typeof updateSelPanel==='function')updateSelPanel();
      return;
    }
    rects.forEach(el=>{
      // 既存枠線関連 data 属性/スタイルをリセット (影は保持)
      ['data-border','data-border-top','data-border-right','data-border-bottom','data-border-left','data-border-style'].forEach(a=>el.removeAttribute(a));
      ['border','border-top','border-right','border-bottom','border-left'].forEach(p=>rmStyleProp(el,p));
      if(kind==='solid'){
        // 現在の data-fill を維持 (無ければ薄灰)
        let fill=A(el,'data-fill');
        if(!fill||fill==='none'||fill==='transparent')fill='#edf2f4';
        el.setAttribute('data-fill',fill);
        setStyleProp(el,'background',fill);
        // 角丸は現状維持
      }else if(kind==='outlined'){
        el.setAttribute('data-fill','#ffffff');
        setStyleProp(el,'background','#ffffff');
        el.setAttribute('data-border','1,#d6dde3');
        setStyleProp(el,'border','1px solid #d6dde3');
        // 角丸8px を推奨 (既に radius があればそのまま、無ければ 8px)
        if(!A(el,'data-radius')){
          el.setAttribute('data-radius','8');
          setStyleProp(el,'border-radius','8px');
        }
      }else if(kind==='transparent'){
        el.setAttribute('data-fill','none');
        setStyleProp(el,'background','transparent');
      }
    });
    dirty=true;
    if(typeof updateSelPanel==='function')updateSelPanel();
  }
  cardStyleRow.addEventListener('click',function(e){
    const k=e.target.getAttribute&&e.target.getAttribute('data-cs');
    if(k)applyCardStyle(k);
  });
  function refreshCardStyleRow(){
    const rects=sels.filter(isCardRect);
    cardStyleRow.style.display=rects.length?'flex':'none';
    if(rects.length){
      const shBtn=cardStyleRow.querySelector('[data-cs="shadow"]');
      const on=A(rects[0],'data-shadow')==='soft';
      if(shBtn){
        shBtn.style.background=on?'#0a7d55':'#0d5a40';
        shBtn.textContent=on?'🌫 薄い影 ON':'🌫 薄い影';
      }
    }
  }

  // ---- 表(table) の色パレット行: 表選択時のみ表示 ----
  // ヘッダー背景 / ヘッダー文字 / 本文セル背景 / 本文セル文字 / セル枠線
  const tblColorRow=document.createElement('div');tblColorRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  tblColorRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">表の色</span>';
  selbar.appendChild(tblColorRow);
  function readTblColor(t,which){
    // which: 'headBg' | 'headFg' | 'bodyBg' | 'bodyFg' | 'border'
    const th=t.querySelector('th');
    const td=t.querySelector('td');
    function pick(el, prop){
      if(!el)return null;
      const inl=(el.getAttribute('style')||'').match(new RegExp('(?:^|;)\\s*'+prop+'\\s*:\\s*([^;]+)','i'));
      if(inl){const v=inl[1].trim();const m=v.match(/#[0-9a-fA-F]{3,8}/);if(m)return m[0];const rm=v.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);if(rm){const h=(x)=>('0'+parseInt(x,10).toString(16)).slice(-2);return '#'+h(rm[1])+h(rm[2])+h(rm[3]);}}
      // computed から取る
      try{
        const cs=getComputedStyle(el)[prop==='background'?'backgroundColor':prop];
        const rm=cs&&cs.match(/rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if(rm){const h=(x)=>('0'+parseInt(x,10).toString(16)).slice(-2);return '#'+h(rm[1])+h(rm[2])+h(rm[3]);}
      }catch(_){}
      return null;
    }
    if(which==='headBg')return pick(th,'background')||'#162a42';
    if(which==='headFg')return pick(th,'color')||'#fafafa';
    if(which==='bodyBg')return pick(td,'background')||'#ffffff';
    if(which==='bodyFg')return pick(td,'color')||'#121212';
    if(which==='border'){
      const bc=pick(td,'border-bottom-color')||pick(td,'border-color')||pick(th,'border-bottom-color')||pick(th,'border-color');
      return bc||'#d7dde3';
    }
    return '#000000';
  }
  function applyTblColor(t,which,hex){
    if(!t||!isHex(hex))return;
    const cells=t.querySelectorAll('th,td');
    if(which==='headBg'){t.querySelectorAll('th').forEach(c=>setStyleProp(c,'background',hex));}
    else if(which==='headFg'){t.querySelectorAll('th').forEach(c=>setStyleProp(c,'color',hex));}
    else if(which==='bodyBg'){t.querySelectorAll('td').forEach(c=>setStyleProp(c,'background',hex));}
    else if(which==='bodyFg'){t.querySelectorAll('td').forEach(c=>setStyleProp(c,'color',hex));}
    else if(which==='border'){
      cells.forEach(c=>{
        const s=c.getAttribute('style')||'';
        // 既存の border-bottom / border 色部分を差し替える
        let ns=s;
        if(/border-bottom\s*:/.test(ns)){
          ns=ns.replace(/border-bottom\s*:[^;]*/,'border-bottom: 1px solid '+hex);
        }else{
          ns=(ns?ns.replace(/;?\s*$/,';'):'')+'border-bottom:1px solid '+hex;
        }
        c.setAttribute('style',ns);
      });
    }
  }
  function applyTblColorTransparent(t,which){
    if(!t)return;
    if(which==='headBg'){t.querySelectorAll('th').forEach(c=>setStyleProp(c,'background','transparent'));}
    else if(which==='bodyBg'){t.querySelectorAll('td').forEach(c=>setStyleProp(c,'background','transparent'));}
    else if(which==='border'){t.querySelectorAll('th,td').forEach(c=>{setStyleProp(c,'border-bottom','none');});}
    else return; // 文字色は透明にしない
  }
  function mkTblRow(label, which, allowTransparent){
    const row=document.createElement('div');row.style.cssText='display:flex;flex-direction:column;gap:2px;padding:1px 2px';
    const lb=document.createElement('span');lb.textContent=label;lb.style.cssText='color:#cdd9e5;font:600 10px/1.2 sans-serif';
    const inputRow=document.createElement('div');inputRow.style.cssText='display:flex;align-items:center;gap:4px';
    const tx=document.createElement('input');tx.type='text';tx.spellcheck=false;tx.style.cssText="flex:1;min-width:0;font:400 11px 'SF Mono','Menlo','Consolas',monospace;padding:2px 5px;border:none;border-radius:3px";
    const sw=document.createElement('input');sw.type='color';sw.style.cssText='width:22px;height:18px;border:none;background:none;cursor:pointer;padding:0;flex-shrink:0';
    let clearBtn=null;
    if(allowTransparent){
      clearBtn=document.createElement('button');clearBtn.textContent='⌀';clearBtn.title='透明';
      clearBtn.style.cssText='padding:2px 6px;border:none;border-radius:3px;background:#16314c;color:#fff;font:600 11px/1 sans-serif;cursor:pointer;flex-shrink:0';
    }
    function commit(v){
      v=(v||'').trim();if(!isHex(v))return;
      const tables=selTables();if(!tables.length)return;
      pushAttr(tables.slice());
      tables.forEach(t=>applyTblColor(t,which,v));
      tx.value=v;try{sw.value=v;}catch(_){}
      dirty=true;
    }
    tx.addEventListener('input',()=>{const v=(tx.value||'').trim();if(isHexTyped(v))commit(v);});
    tx.addEventListener('change',()=>commit(tx.value));
    tx.addEventListener('keydown',e=>{if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){e.preventDefault();commit(tx.value);tx.blur();}});
    sw.addEventListener('input',()=>commit(sw.value));
    sw.addEventListener('change',()=>commit(sw.value));
    if(clearBtn){
      clearBtn.addEventListener('click',()=>{
        const tables=selTables();if(!tables.length)return;
        pushAttr(tables.slice());
        tables.forEach(t=>applyTblColorTransparent(t,which));
        dirty=true;
      });
    }
    row.appendChild(lb);inputRow.appendChild(tx);inputRow.appendChild(sw);
    if(clearBtn)inputRow.appendChild(clearBtn);
    row.appendChild(inputRow);tblColorRow.appendChild(row);
    return {tx,sw,which};
  }
  const tblRows=[
    mkTblRow('ヘッダー背景','headBg',true),
    mkTblRow('ヘッダー文字','headFg',false),
    mkTblRow('本文セル背景','bodyBg',true),
    mkTblRow('本文セル文字','bodyFg',false),
    mkTblRow('セル枠線','border',true),
  ];
  function refreshTblColorRow(){
    const tables=selTables();
    if(!tables.length){tblColorRow.style.display='none';return;}
    tblColorRow.style.display='flex';
    const t=tables[0];
    tblRows.forEach(r=>{
      const v=readTblColor(t,r.which);
      r.tx.value=v;try{r.sw.value=v;}catch(_){}
    });
  }

  // サイズ行（W/H）：選択中要素の幅・高さを数値で直接編集
  const sizeRow=document.createElement('div');sizeRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  sizeRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">サイズ W × H (px)</span>'
    +'<div style="display:flex;align-items:center;gap:4px">'
    +'<input id="seW" type="text" inputmode="numeric" style="flex:1;min-width:0;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:3px">'
    +'<span style="color:#eafff6;font-size:12px">×</span>'
    +'<input id="seH" type="text" inputmode="numeric" style="flex:1;min-width:0;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:3px">'
    +'</div>';
  selbar.appendChild(sizeRow);
  const wInput=sizeRow.querySelector('#seW');
  const hInput=sizeRow.querySelector('#seH');
  wInput.addEventListener('change',function(){const v=parseInt(wInput.value,10);if(isNaN(v)||!sels.length)return;pushAttr(sels.slice());sels.forEach(el=>setW(el,Math.max(8,v)));placeBox();wInput.value=N(A(sels[0],'data-w'))||v;});
  hInput.addEventListener('change',function(){const v=parseInt(hInput.value,10);if(isNaN(v)||!sels.length)return;pushAttr(sels.slice());sels.forEach(el=>{if(!el.hasAttribute('data-h')){const ch=el.getBoundingClientRect().height||40;el.setAttribute('data-h',Math.round(ch));}setH(el,Math.max(8,v));});placeBox();hInput.value=N(A(sels[0],'data-h'))||v;});

  // 角R（border-radius）行：rectで data-shape != circle/triangle のときに表示
  const radiusRow=document.createElement('div');radiusRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  radiusRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">角R (px)</span>'
    +'<div style="display:flex;align-items:center;gap:4px">'
    +'<button data-rd="-2">−</button>'
    +'<input id="seRd" type="text" inputmode="numeric" style="flex:1;min-width:0;text-align:center;font:600 12px monospace;padding:2px 4px;border:none;border-radius:3px">'
    +'<button data-rd="2">＋</button>'
    +'</div>';
  selbar.appendChild(radiusRow);
  Array.from(radiusRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:3px 9px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer;flex-shrink:0');
  const rdInput=radiusRow.querySelector('#seRd');
  function getRectTargets(){return sels.filter(el=>el.classList&&el.classList.contains('rect')&&['circle','triangle','line','arrow','chevron'].indexOf(A(el,'data-shape'))<0);}
  function applyRadius(val){const tgts=getRectTargets();if(!tgts.length)return;val=Math.max(0,Math.round(val));pushAttr(tgts.slice());tgts.forEach(el=>{if(val===0){el.removeAttribute('data-radius');el.style.borderRadius='0';}else{el.setAttribute('data-radius',val);el.style.borderRadius=val+'px';}});}
  radiusRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-rd');if(!v)return;const tgts=getRectTargets();if(!tgts.length)return;const cur=N(A(tgts[0],'data-radius'))||0;applyRadius(cur+parseInt(v,10));rdInput.value=N(A(tgts[0],'data-radius'))||0;});
  rdInput.addEventListener('change',function(){const v=parseInt(rdInput.value,10);if(isNaN(v))return;applyRadius(v);rdInput.value=N(A(getRectTargets()[0]||{},'data-radius'))||0;});

  // 線/矢印パラメータ：太さ（line=data-h／arrow=data-at＝軸の太さ）・矢羽（arrow=data-ah＝矢じりの長さ）。長さ・位置は通常リサイズで
  // 図形パラメータの clamp/default は slidekit-defs.js (shapes) が正本 (v2 / Requirements 4.6)。
  // defs 未読込時は v1 実装と同値のインラインフォールバック。
  function _shapeParam(shape,param,fb){
    try{
      const p=window.SLIDEKIT_DEFS.shapes[shape].params[param];
      if(typeof p.min==='number'&&typeof p.max==='number'&&typeof p['default']==='number')return {min:p.min,max:p.max,def:p['default']};
    }catch(_){}
    return fb;
  }
  const SHP_AT=_shapeParam('arrow','at',{min:.05,max:.95,def:.45});   // 矢印の軸の太さ
  const SHP_AH=_shapeParam('arrow','ah',{min:.05,max:.9,def:.32});    // 矢印の矢じり長
  const SHP_CV=_shapeParam('chevron','cv',{min:.02,max:.6,def:.14});  // 帯矢印の尖り
  const SHP_BX=_shapeParam('callout','bx',{min:.08,max:.92,def:.3}); // 吹き出しのしっぽ先端x位置
  function arrowClip(hf,tf){const x=((1-hf)*100).toFixed(1),t=(50-tf*50).toFixed(1),b=(50+tf*50).toFixed(1);return 'polygon(0 '+t+'%,'+x+'% '+t+'%,'+x+'% 0,100% 50%,'+x+'% 100%,'+x+'% '+b+'%,0 '+b+'%)';}
  // clip-pathで切り抜く図形（矢印・帯矢印・三角）の輪郭点（0〜100空間）。
  // CSS borderは四角い箱に付いてしまうため、枠線はこの輪郭のSVG strokeとして描く
  function shapeOutlinePts(el){
    const ds=A(el,'data-shape');
    if(ds==='triangle')return [[50,0],[0,100],[100,100]];
    if(ds==='chevron'){const cf=Math.max(SHP_CV.min,Math.min(SHP_CV.max,N(A(el,'data-cv'))||SHP_CV.def));const x=(1-cf)*100;return [[0,0],[x,0],[100,50],[x,100],[0,100]];}
    if(ds==='arrow'){const hf=Math.max(SHP_AH.min,Math.min(SHP_AH.max,N(A(el,'data-ah'))||SHP_AH.def)),tf=Math.max(SHP_AT.min,Math.min(SHP_AT.max,N(A(el,'data-at'))||SHP_AT.def));const x=(1-hf)*100,t=50-tf*50,b=50+tf*50;return [[0,t],[x,t],[x,0],[100,50],[x,100],[x,b],[0,b]];}
    if(ds==='callout'){const bx=Math.max(SHP_BX.min,Math.min(SHP_BX.max,N(A(el,'data-bx'))||SHP_BX.def));return calloutPts(bx);}
    return null;
  }
  // 吹き出し：本体=上80%、しっぽ=下20%（先端x=bx）。PPTX側はWEDGE_RECT_CALLOUTのadjで同じ形にする
  function calloutPts(bx){
    const tipX=Math.max(4,Math.min(96,bx*100));
    const b1=Math.max(2,tipX-8),b2=Math.min(98,tipX+8);
    return [[0,0],[100,0],[100,80],[b2,80],[tipX,100],[b1,80],[0,80]];
  }
  function calloutClip(bx){return 'polygon('+calloutPts(bx).map(p=>p[0].toFixed(1)+'% '+p[1]+'%').join(',')+')';}
  function applyCalloutShape(el){const bx=Math.max(SHP_BX.min,Math.min(SHP_BX.max,N(A(el,'data-bx'))||SHP_BX.def));const cp=calloutClip(bx);el.style.clipPath=cp;el.style.webkitClipPath=cp;refreshShapeOutline(el);}
  // data-border を図形輪郭のSVG背景として描画する（clip-pathが外側半分を落とすので
  // stroke-widthは2倍＝内側w px。PPTX側は add_rect_shape が shape.line に変換済み）。
  // background:#hex のショートハンドに負けないよう、毎回消してから末尾に追記する
  function refreshShapeOutline(el){
    const pts=shapeOutlinePts(el);if(!pts)return false;
    const bd=parseBorder(A(el,'data-border'));
    const st0=el.getAttribute('style')||'';
    if(!bd&&st0.indexOf('data:image/svg+xml')<0&&st0.indexOf('background-image')<0)return true; // 書き換え不要（読み込み時の差分ノイズ防止）
    ['background-image','background-repeat','background-size'].forEach(p=>rmStyleProp(el,p));
    // el.style を直接触るとブラウザが background ショートハンドに合成することがある
    // → url入りショートハンドが残っていたら、塗りを正本(data-fill)から張り直して輪郭を消す
    if((el.getAttribute('style')||'').indexOf('data:image/svg+xml')>=0){
      const f=A(el,'data-fill');
      rmStyleProp(el,'background');
      setStyleProp(el,'background',(f&&f!=='none'&&f!=='transparent')?f:'transparent');
    }
    if(bd&&bd.w>0){
      const dash=(bd.s==='dashed'||bd.s==='wavy')?' stroke-dasharray="6 4"':(bd.s==='dotted'?' stroke-dasharray="2 3"':'');
      const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none"><polygon points="'
        +pts.map(p=>p[0].toFixed(2)+','+p[1].toFixed(2)).join(' ')
        +'" fill="none" stroke="'+bd.c+'" stroke-width="'+(bd.w*2)+'" vector-effect="non-scaling-stroke"'+dash+'/></svg>';
      setStyleProp(el,'background-image','url("data:image/svg+xml,'+encodeURIComponent(svg)+'")');
      setStyleProp(el,'background-repeat','no-repeat');
      setStyleProp(el,'background-size','100% 100%');
    }
    return true;
  }
  function applyArrowShape(el){const hf=Math.max(SHP_AH.min,Math.min(SHP_AH.max,N(A(el,'data-ah'))||SHP_AH.def)),tf=Math.max(SHP_AT.min,Math.min(SHP_AT.max,N(A(el,'data-at'))||SHP_AT.def));const cp=arrowClip(hf,tf);el.style.clipPath=cp;el.style.webkitClipPath=cp;refreshShapeOutline(el);}
  function arrowTarget(){return sels.find(el=>el.classList&&el.classList.contains('rect')&&['line','arrow'].indexOf(A(el,'data-shape'))>=0);}
  const arrowRow=document.createElement('div');arrowRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  arrowRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">線/矢印</span>'
    +'<div style="display:flex;align-items:center;gap:4px"><span style="color:#aedccb;font-size:11px;width:30px;flex-shrink:0">太さ</span><button data-aw="t-">−</button><button data-aw="t+">＋</button></div>'
    +'<div data-headrow="1" style="display:flex;align-items:center;gap:4px"><span style="color:#aedccb;font-size:11px;width:30px;flex-shrink:0">矢羽</span><button data-aw="h-">−</button><button data-aw="h+">＋</button></div>';
  selbar.appendChild(arrowRow);
  Array.from(arrowRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:3px 9px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:13px;cursor:pointer');
  arrowRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-aw');if(!v)return;const tgt=arrowTarget();if(!tgt)return;pushAttr([tgt]);const sh=A(tgt,'data-shape');
    // ＋/− の可動域 (.08-.9 / .08-.85) は v1 の UI ステップ上限をそのまま維持 (挙動保存)。既定値のみ defs 参照
    if(v==='t-'||v==='t+'){const s=v==='t+'?1:-1;if(sh==='line'){if(!tgt.hasAttribute('data-h'))tgt.setAttribute('data-h',Math.round(tgt.getBoundingClientRect().height)||4);setH(tgt,Math.max(1,(N(A(tgt,'data-h'))||4)+s*2));}else{const nt=Math.max(.08,Math.min(.9,(N(A(tgt,'data-at'))||SHP_AT.def)+s*.06));tgt.setAttribute('data-at',nt.toFixed(3));applyArrowShape(tgt);}}
    else if(v==='h-'||v==='h+'){const s=v==='h+'?1:-1;const nh=Math.max(.08,Math.min(.85,(N(A(tgt,'data-ah'))||SHP_AH.def)+s*.05));tgt.setAttribute('data-ah',nh.toFixed(3));applyArrowShape(tgt);}
    placeBox();});
  // 帯矢印（chevron）の尖り具合：data-cv＝先端が占める幅の割合。複数を同じ尖りに揃えるボタン付き
  function chevronClip(cf){const x=((1-cf)*100).toFixed(1);return 'polygon(0 0,'+x+'% 0,100% 50%,'+x+'% 100%,0 100%)';}
  function applyChevronShape(el){const cf=Math.max(SHP_CV.min,Math.min(SHP_CV.max,N(A(el,'data-cv'))||SHP_CV.def));const cp=chevronClip(cf);el.style.clipPath=cp;el.style.webkitClipPath=cp;refreshShapeOutline(el);}
  function chevronTarget(){return sels.find(el=>el.classList&&el.classList.contains('rect')&&A(el,'data-shape')==='chevron');}
  const chevRow=document.createElement('div');chevRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  chevRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">帯矢印の尖り</span>'
    +'<div style="display:flex;gap:4px"><button data-cv="-">緩く</button><button data-cv="+">尖らす</button></div>'
    +'<button data-cv="sync" style="margin-top:2px">全部の帯矢印を同じ尖りに</button>';
  selbar.appendChild(chevRow);
  Array.from(chevRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:3px 9px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer');
  Array.from(chevRow.querySelectorAll('div button')).forEach(b=>b.style.flex='1');
  chevRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-cv');if(!v)return;const tgt=chevronTarget();if(!tgt)return;
    if(v==='sync'){const cf=Math.max(SHP_CV.min,Math.min(SHP_CV.max,N(A(tgt,'data-cv'))||SHP_CV.def));const all=Array.from(document.querySelectorAll('.rect[data-shape="chevron"]'));pushAttr(all);all.forEach(el=>{el.setAttribute('data-cv',cf.toFixed(3));applyChevronShape(el);});}
    else{const s=v==='+'?1:-1;pushAttr([tgt]);const nc=Math.max(SHP_CV.min,Math.min(SHP_CV.max,(N(A(tgt,'data-cv'))||SHP_CV.def)+s*0.03));tgt.setAttribute('data-cv',nc.toFixed(3));applyChevronShape(tgt);}
    placeBox();});
  // 吹き出しのしっぽ位置（data-bx）
  function calloutTarget(){return sels.find(el=>el.classList&&el.classList.contains('rect')&&A(el,'data-shape')==='callout');}
  const calloutRow=document.createElement('div');calloutRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:3px;margin-top:2px';
  calloutRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">吹き出しのしっぽ</span>'
    +'<div style="display:flex;gap:4px"><button data-bxm="-">← 左へ</button><button data-bxm="+">右へ →</button></div>';
  selbar.appendChild(calloutRow);
  Array.from(calloutRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:3px 9px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer');
  calloutRow.addEventListener('click',function(e){const v=e.target.getAttribute&&e.target.getAttribute('data-bxm');if(!v)return;const tgt=calloutTarget();if(!tgt)return;pushAttr([tgt]);
    const nb=Math.max(SHP_BX.min,Math.min(SHP_BX.max,(N(A(tgt,'data-bx'))||SHP_BX.def)+(v==='+'?1:-1)*0.06));
    tgt.setAttribute('data-bx',nb.toFixed(3));applyCalloutShape(tgt);placeBox();});
  // 反転（左右/上下）：図形と画像のみ。PPTXのflipH/flipVに変換される
  function canFlip(el){return !!(el&&el.classList&&!el.classList.contains('tb')&&el.tagName!=='TABLE'&&(el.classList.contains('rect')||el.tagName==='IMG'||(el.querySelector&&el.querySelector('img'))));}
  const flipRow=document.createElement('div');flipRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:2px';
  flipRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">反転</span>'
    +'<div style="display:flex;gap:3px"><button data-fl="h" title="左右反転（もう一度で戻る）">⇋ 左右</button><button data-fl="v" title="上下反転（もう一度で戻る）">⇅ 上下</button></div>';
  selbar.appendChild(flipRow);
  Array.from(flipRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:4px 8px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer');
  flipRow.addEventListener('click',function(e){const ax=e.target.getAttribute&&e.target.getAttribute('data-fl');if(!ax||sels.length!==1)return;pushAttr([sels[0]]);setFlip(sels[0],ax);placeBox();});
  // 塗りの不透明度：data-fill を #RRGGBBAA にする（PPTX変換は8桁hex対応済み）
  const opRow=document.createElement('div');opRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:2px';
  opRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">塗りの不透明度 <span data-opval style="color:#aedccb;font-weight:400"></span></span>'
    +'<div style="display:flex;gap:3px"><button data-op="100">100</button><button data-op="75">75</button><button data-op="50">50</button><button data-op="25">25</button></div>';
  selbar.appendChild(opRow);
  Array.from(opRow.querySelectorAll('button')).forEach(b=>b.style.cssText='flex:1;padding:4px 4px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer');
  function fillOpacityOf(el){const f=A(el,'data-fill')||'';const m=f.match(/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})$/);return m?Math.round(parseInt(m[1],16)/255*100):100;}
  opRow.addEventListener('click',function(e){
    const p=e.target.getAttribute&&e.target.getAttribute('data-op');if(!p)return;
    const pct=parseInt(p,10);
    const tgts=sels.filter(el=>el.classList&&el.classList.contains('rect')&&/^#[0-9a-fA-F]{6}/.test(A(el,'data-fill')||''));
    if(!tgts.length)return;
    pushAttr(tgts);
    tgts.forEach(el=>{
      const base=(A(el,'data-fill')||'').slice(0,7);
      const v=pct>=100?base:base+('0'+Math.round(255*pct/100).toString(16)).slice(-2);
      el.setAttribute('data-fill',v);setStyleProp(el,'background',v);
      if(typeof refreshShapeOutline==='function')refreshShapeOutline(el);
    });
    placeBox();
  });
  // ---- ページジャンプリンク（クリックで指定スライドへ）----
  // データ: 要素に data-link-sid / 行き先スライドに data-sid（固定ID・ページ入替でも切れない）
  // 動き: 閲覧モード＆プレゼンでクリックジャンプ。PPTXでは click_action.target_slide に変換
  function ensureSid(s){let v=s.getAttribute('data-sid');if(v)return v;do{v='s'+Math.random().toString(36).slice(2,7);}while(document.querySelector('.slide[data-sid="'+v+'"]'));s.setAttribute('data-sid',v);return v;}
  const navRow=document.createElement('div');navRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:2px';
  navRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block" title="閲覧モード・プレゼン・PPTXでクリックするとそのページへ飛ぶ">🔗 クリックでページへ</span>'
    +'<select data-navsel style="padding:4px;border:none;border-radius:5px;font-size:12px;max-width:160px"></select>';
  selbar.appendChild(navRow);
  const navSel=navRow.querySelector('[data-navsel]');
  function refreshNavSel(el){
    const cur=A(el,'data-link-sid')||'';
    let found=(cur==='');
    let html='<option value="">リンクなし</option>';
    allSlides().forEach((s,i)=>{
      const sid=s.getAttribute('data-sid');
      const isCur=!!(cur&&sid&&sid===cur);
      if(isCur)found=true;
      html+='<option value="'+i+'"'+(isCur?' selected':'')+'>P'+(i+1)+' '+esc(slideTitleOf(s))+'</option>';
    });
    if(!found)html='<option value="" selected>⚠ リンク切れ（'+esc(cur)+'）</option>'+html;
    navSel.innerHTML=html;
  }
  navSel.addEventListener('change',function(){
    if(sels.length!==1)return;
    const el=sels[0];
    if(navSel.value===''){pushAttr([el]);el.removeAttribute('data-link-sid');placeBox();return;}
    const tgt=allSlides()[parseInt(navSel.value,10)];if(!tgt)return;
    pushAttr([el,tgt]); // 行き先スライドのsid付与もUndo対象に含める
    el.setAttribute('data-link-sid',ensureSid(tgt));
    placeBox();
  });
  // 閲覧モード（✏️OFF）: リンク要素クリックでそのページへスクロール
  (function(){const st=document.createElement('style');st.className='seui';st.textContent='.slide [data-link-sid]{cursor:pointer}';document.head.appendChild(st);})();
  document.addEventListener('click',function(e){
    if(editing)return; // 編集中は選択操作を優先
    const ln=e.target&&e.target.closest&&e.target.closest('.slide [data-link-sid]');
    if(!ln)return;
    let tgt=null;
    try{tgt=document.querySelector('.slide[data-sid="'+CSS.escape(ln.getAttribute('data-link-sid'))+'"]');}catch(_){}
    if(tgt){e.preventDefault();tgt.scrollIntoView({behavior:'smooth',block:'center'});}
  });
  const alignRow=document.createElement('div');alignRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  alignRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">整列（揃え・等間隔は2つ以上選択）</span>'
    +'<span style="color:#aedccb;font:500 10px/1 sans-serif;margin-top:2px">横方向</span>'
    +'<div data-grp="h" style="display:flex;flex-wrap:wrap;gap:3px"><button data-al="l">左</button><button data-al="cx">中央</button><button data-al="r">右</button></div>'
    +'<span style="color:#aedccb;font:500 10px/1 sans-serif;margin-top:4px">縦方向</span>'
    +'<div data-grp="v" style="display:flex;flex-wrap:wrap;gap:3px"><button data-al="t">上</button><button data-al="cy">中央</button><button data-al="b">下</button></div>'
    +'<span style="color:#aedccb;font:500 10px/1 sans-serif;margin-top:4px">サイズ統一</span>'
    +'<div data-grp="s" style="display:flex;flex-wrap:wrap;gap:3px"><button data-al="w">幅</button><button data-al="h">高さ</button></div>'
    +'<span style="color:#aedccb;font:500 10px/1 sans-serif;margin-top:4px">等間隔（3つ以上）</span>'
    +'<div data-grp="d" style="display:flex;flex-wrap:wrap;gap:3px"><button data-al="dh">横</button><button data-al="dv">縦</button></div>'
    +'<span style="color:#aedccb;font:500 10px/1 sans-serif;margin-top:4px">スライド基準（1つでも可）</span>'
    +'<div data-grp="sl" style="display:flex;flex-wrap:wrap;gap:3px"><button data-al="slcx" title="選択全体をスライドの横中央に">横中央</button><button data-al="slcy" title="選択全体をスライドの縦中央に">縦中央</button></div>';
  selbar.appendChild(alignRow);
  Array.from(alignRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:4px 12px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer;flex:1;min-width:40px');

  // ---- 書式コピー（ハケ）: 選択1つの書式を次にクリックした要素へ転写 ----
  let painterSrc=null;
  const painterRow=document.createElement('div');painterRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  painterRow.innerHTML='<button id="sePainter" title="この要素の書式（塗り/枠線/角丸/文字色/サイズ/太字/揃え）を、次にクリックした要素にコピー。Shiftクリックで連続適用、Escで解除">🖌 書式コピー</button>';
  selbar.appendChild(painterRow);
  const painterBtn=painterRow.querySelector('#sePainter');
  painterBtn.style.cssText='padding:5px 10px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font:600 12px sans-serif;cursor:pointer';
  function painterExit(){painterSrc=null;document.body.style.cursor='';painterBtn.style.background='#0d5a40';painterBtn.textContent='🖌 書式コピー';}
  function painterApply(src,dst){
    pushAttr([dst]);
    // 台座系: 塗り・枠線・角丸
    copyFill(src,dst);copyBorder(src,dst);
    const rv=A(src,'data-radius');
    if(rv){dst.setAttribute('data-radius',rv);dst.style.borderRadius=rv+'px';}
    else if(dst.classList&&dst.classList.contains('rect')){dst.removeAttribute('data-radius');dst.style.borderRadius='0';}
    // 文字系: 色・サイズ・太字・揃え（src/dstどちらが.tbでもrect内tbでも動く）
    copyColor(src,dst);
    const sTb=(src.classList&&src.classList.contains('tb'))?src:(src.querySelector&&src.querySelector('.tb'));
    const dTbs=(dst.classList&&dst.classList.contains('tb'))?[dst]:(dst.querySelectorAll?[...dst.querySelectorAll('.tb')]:[]);
    if(sTb&&dTbs.length){
      const fs=N(A(sTb,'data-font-size')),bold=A(sTb,'data-bold')==='1',al=A(sTb,'data-align');
      dTbs.forEach(t=>{if(fs)setFS(t,fs);setBold(t,bold);if(al){t.setAttribute('data-align',al);setStyleProp(t,'text-align',al);}});
    }
    placeBox();
  }
  painterBtn.addEventListener('click',function(){
    if(painterSrc){painterExit();return;}
    if(sels.length!==1)return;
    painterSrc=sels[0];document.body.style.cursor='copy';
    painterBtn.style.background='#e8821a';painterBtn.textContent='🖌 転写先をクリック（Escで解除）';
  });
  // 転写先クリックはmousedownのcapture段階で先取り（通常の選択処理に渡さない）
  document.addEventListener('mousedown',function(e){
    if(!painterSrc||!editing)return;
    if(e.target.closest&&e.target.closest('.seui'))return; // パネル操作は素通し
    const dst=e.target.closest&&e.target.closest(SEL);
    if(!dst||dst===painterSrc){return;}
    e.preventDefault();e.stopPropagation();
    painterApply(painterSrc,dst);
    if(!e.shiftKey)painterExit();
  },true);
  // 共通化（1つ選択時・全ページに伝播）：塗り/枠線/文字色/サイズ ×（なし/同じ色/全カード）
  const commonizeRow=document.createElement('div');commonizeRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  function ckRow(attr,label){return '<div data-ck="'+attr+'" style="display:flex;flex-wrap:wrap;align-items:center;gap:3px;font-size:10px;color:#cfe9dd">'
    +'<span style="width:38px;font-weight:600;font-size:11px">'+label+'</span>'
    +'<label title="変更しない" style="display:flex;align-items:center;gap:1px;cursor:pointer"><input type="radio" name="ck_'+attr+'" value="none" checked style="margin:0;transform:scale(.85)">無</label>'
    +'<label title="今同じ値のカードだけに" style="display:flex;align-items:center;gap:1px;cursor:pointer"><input type="radio" name="ck_'+attr+'" value="same" style="margin:0;transform:scale(.85)">同</label>'
    +'<label title="全カードに" style="display:flex;align-items:center;gap:1px;cursor:pointer"><input type="radio" name="ck_'+attr+'" value="all" style="margin:0;transform:scale(.85)">全</label>'
    +'</div>';}
  commonizeRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">共通化（全ページ）</span>'
    +'<span style="color:#aedccb;font:500 9px/1.3 sans-serif;display:block;margin-bottom:2px">無=しない／同=今同じ／全=全カード</span>'
    +ckRow('fill','塗り')+ckRow('border','枠線')+ckRow('color','文字色')+ckRow('size','サイズ')
    +'<button id="seCmnApply" style="margin-top:5px;padding:5px 10px;border:none;border-radius:6px;background:#1f7a5a;color:#fff;font:600 12px sans-serif;cursor:pointer">適用</button>';
  selbar.appendChild(commonizeRow);
  function isCardEl(el){if(!el.classList||!el.classList.contains('rect'))return false;const y=N(A(el,'data-y'))||0,h=N(A(el,'data-h'))||0;if(y<80&&h<=44)return false;return true;}
  function getFillKey(el){return A(el,'data-fill')||'';}
  function getBorderKey(el){const b=getBorderState(el);return b.pos+'|'+b.w+'|'+b.c+'|'+b.s;}
  function getColorKey(el){const tb=el.classList.contains('tb')?el:el.querySelector('.tb');return tb?(A(tb,'data-color')||''):'';}
  function getSizeKey(el){return (N(A(el,'data-w'))||0)+'x'+(N(A(el,'data-h'))||0);}
  function copyFill(src,dst){const fv=A(src,'data-fill');if(fv){dst.setAttribute('data-fill',fv);setStyleProp(dst,'background',fv);}else{dst.removeAttribute('data-fill');rmStyleProp(dst,'background');}}
  function copyBorder(src,dst){const bs=getBorderState(src);['data-border','data-border-top','data-border-right','data-border-bottom','data-border-left','data-border-style'].forEach(a=>dst.removeAttribute(a));['border','border-top','border-right','border-bottom','border-left'].forEach(p=>rmStyleProp(dst,p));if(bs.pos==='none'||bs.w<=0)return;const cssStyle=(bs.s==='wavy')?'dashed':bs.s;const val=bs.w+','+bs.c+(bs.s!=='solid'?(','+bs.s):'');if(bs.pos==='all'){dst.setAttribute('data-border',val);setStyleProp(dst,'border',bs.w+'px '+cssStyle+' '+bs.c);}else{dst.setAttribute('data-border-'+bs.pos,val);setStyleProp(dst,'border-'+bs.pos,bs.w+'px '+cssStyle+' '+bs.c);}if(bs.s==='wavy')dst.setAttribute('data-border-style','wavy');}
  function copyColor(src,dst){const srcTb=src.classList.contains('tb')?src:src.querySelector('.tb');if(!srcTb)return;const cv=A(srcTb,'data-color');if(!cv)return;const tbs=dst.classList.contains('tb')?[dst]:dst.querySelectorAll('.tb');tbs.forEach(tb=>{tb.setAttribute('data-color',cv);setStyleProp(tb,'color',cv);});}
  function copySize(src,dst){const w=N(A(src,'data-w'))||0,h=N(A(src,'data-h'))||0;if(w>0)setW(dst,w);if(h>0)setH(dst,h);}
  function applyCommonize(){
    if(sels.length!==1)return;
    const src=sels[0];if(!isCardEl(src)){alert('カード（rect）を1つ選んでね');return;}
    const modes={};['fill','border','color','size'].forEach(k=>{const r=commonizeRow.querySelector('input[name="ck_'+k+'"]:checked');modes[k]=r?r.value:'none';});
    const active=Object.keys(modes).filter(k=>modes[k]!=='none');
    if(!active.length){alert('適用する項目を選んでね');return;}
    const allCards=Array.from(document.querySelectorAll('.slide .rect')).filter(isCardEl);
    const targets=new Set();
    active.forEach(k=>{
      if(modes[k]==='all'){allCards.forEach(c=>targets.add(c));return;}
      let key='';if(k==='fill')key=getFillKey(src);else if(k==='border')key=getBorderKey(src);else if(k==='color')key=getColorKey(src);else if(k==='size')key=getSizeKey(src);
      allCards.forEach(c=>{let ck='';if(k==='fill')ck=getFillKey(c);else if(k==='border')ck=getBorderKey(c);else if(k==='color')ck=getColorKey(c);else if(k==='size')ck=getSizeKey(c);if(ck===key)targets.add(c);});
    });
    targets.delete(src);
    if(!targets.size){alert('対象が見つからない');return;}
    const list=Array.from(targets);
    if(!confirm(list.length+'件のカードに「'+active.join('・')+'」を適用する？'))return;
    pushAttr(list);
    list.forEach(t=>{if(modes.fill!=='none')copyFill(src,t);if(modes.border!=='none')copyBorder(src,t);if(modes.color!=='none')copyColor(src,t);if(modes.size!=='none')copySize(src,t);});
    placeBox();
    // ラジオをリセット
    commonizeRow.querySelectorAll('input[type="radio"][value="none"]').forEach(r=>{r.checked=true;});
    alert(list.length+'件のカードに適用した');
  }
  commonizeRow.querySelector('#seCmnApply').addEventListener('click',applyCommonize);
  // バッジ形（なし/矩形/長円）：data-role=badge のrect が1個選択された時のみ表示
  const badgeShapeRow=document.createElement('div');badgeShapeRow.id='seBadgeShape';badgeShapeRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  badgeShapeRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">バッジ形</span>'
    +'<div style="display:flex;gap:3px"><button data-bs="none" title="装飾なし（背景透明・枠線なし）">⊘ なし</button><button data-bs="rect" title="矩形（角丸なし）">▭ 矩形</button><button data-bs="pill" title="長円（端が半円）">⬭ 長円</button></div>';
  selbar.appendChild(badgeShapeRow);
  Array.from(badgeShapeRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:4px 8px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer;flex:1');
  function applyBadgeShape(kind){
    if(sels.length!==1)return;
    const el=sels[0];if(!el.classList||!el.classList.contains('rect'))return;
    // バッジ等の共通要素は全ページに展開して一括適用
    const tgts=expandLinked([el]);
    pushAttr(tgts);
    tgts.forEach(t=>{
      if(kind==='none'){
        t.setAttribute('data-fill','none');setStyleProp(t,'background','transparent');
        t.removeAttribute('data-radius');t.style.borderRadius='0';
        ['data-border','data-border-top','data-border-right','data-border-bottom','data-border-left','data-border-style'].forEach(a=>t.removeAttribute(a));
        ['border','border-top','border-right','border-bottom','border-left'].forEach(p=>rmStyleProp(t,p));
        t.setAttribute('data-shape','none');
      }else if(kind==='rect'){
        t.removeAttribute('data-radius');t.style.borderRadius='0';
        t.removeAttribute('data-shape');
      }else if(kind==='pill'){
        const h=N(A(t,'data-h'))||t.getBoundingClientRect().height||30;
        const r=Math.round(h/2);
        t.setAttribute('data-radius',r);t.style.borderRadius=r+'px';
        t.setAttribute('data-shape','pill');
      }
    });
    placeBox();
  }
  badgeShapeRow.addEventListener('click',e=>{const k=e.target.getAttribute&&e.target.getAttribute('data-bs');if(k)applyBadgeShape(k);});
  // ---- 画像トリミング（clip-path: inset で見た目→data-crop-*に保存→PPTX変換も対応）----
  const cropRow=document.createElement('div');cropRow.style.cssText='display:none;flex-direction:column;align-items:stretch;gap:4px;margin-top:2px;padding-top:6px;border-top:1px solid rgba(255,255,255,.18)';
  cropRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;width:100%;display:block">✂️ トリミング</span>'
    +'<div style="display:flex;gap:4px;flex-wrap:wrap"><button data-cp="on" style="flex:1;padding:5px 8px;border:none;border-radius:5px;background:#0d5a40;color:#fff;font:600 12px sans-serif;cursor:pointer">開始/終了</button><button data-cp="reset" style="flex:1;padding:5px 8px;border:none;border-radius:5px;background:#7a2d2d;color:#fff;font:600 12px sans-serif;cursor:pointer">解除</button></div>'
    +'<span style="color:#aedccb;font:400 10px/1.4 sans-serif;display:block">画像ダブルクリックで開始 → ドラッグ＝表示位置、ホイール＝拡大縮小。Esc/枠外クリックで終了。</span>';
  selbar.appendChild(cropRow);
  // クロップの意味論：切り抜いた領域が「枠（表示エリア）いっぱいに拡大表示」される。
  // PPTXのsrcRect（pic.crop_*）と同じモデル。表示は object-view-box（Chrome系）で行う。
  // 旧clip-path方式（枠の内側を切り落とすだけ）は読み込み時にこの方式へ移行する。
  let cropMode=null,cropState=null; // cropState={nw,nh,fw,fh,s0,z,ox,oy}
  const cropOverlay=document.createElement('div');cropOverlay.className='seui';
  cropOverlay.style.cssText='position:absolute;display:none;z-index:99997;pointer-events:auto;cursor:grab;outline:2px dashed #ff9900';
  const cropGhost=document.createElement('img'); // 枠外に元画像全体を薄く表示（どこを切り出しているかの手がかり）
  cropGhost.style.cssText='position:absolute;opacity:.3;pointer-events:none;max-width:none';
  const cropHint=document.createElement('div');
  cropHint.textContent='ドラッグ＝位置 / ホイール＝拡大縮小 / Esc＝終了';
  cropHint.style.cssText='position:absolute;left:50%;top:-32px;transform:translateX(-50%);background:rgba(22,42,66,.95);color:#fafafa;font:600 11px/1 sans-serif;padding:6px 10px;border-radius:6px;white-space:nowrap;pointer-events:none';
  const cropZoom=document.createElement('div');
  cropZoom.style.cssText='position:absolute;right:-2px;bottom:-28px;background:rgba(22,42,66,.95);color:#fafafa;font:600 11px/1 sans-serif;padding:4px 8px;border-radius:6px;pointer-events:none';
  cropOverlay.appendChild(cropGhost);cropOverlay.appendChild(cropHint);cropOverlay.appendChild(cropZoom);
  document.body.appendChild(cropOverlay);
  function _cf(v){const f=parseFloat(v||0);return isFinite(f)?Math.max(0,Math.min(0.9,f)):0;}
  function readCrop(img){return {t:_cf(img.dataset.cropT),r:_cf(img.dataset.cropR),b:_cf(img.dataset.cropB),l:_cf(img.dataset.cropL)};}
  function applyCropStyle(img){
    const c=readCrop(img);
    if(c.t||c.r||c.b||c.l){
      img.dataset.cropT=c.t;img.dataset.cropR=c.r;img.dataset.cropB=c.b;img.dataset.cropL=c.l;
      if(img.dataset.cropOf===undefined)img.dataset.cropOf=img.style.objectFit||''; // 解除時に戻せるよう元のobject-fitを控える
      img.style.clipPath='';
      img.style.setProperty('object-view-box','inset('+(c.t*100)+'% '+(c.r*100)+'% '+(c.b*100)+'% '+(c.l*100)+'%)');
      img.style.objectFit='fill'; // 切り出し領域は枠と同アス比で作るので歪まない
    }else{
      img.style.clipPath='';img.style.removeProperty('object-view-box');
      if(img.dataset.cropOf!==undefined){if(img.dataset.cropOf)img.style.objectFit=img.dataset.cropOf;else img.style.removeProperty('object-fit');delete img.dataset.cropOf;}
      delete img.dataset.cropT;delete img.dataset.cropR;delete img.dataset.cropB;delete img.dataset.cropL;
    }
  }
  // 旧clip-path方式で保存された既存クロップを新方式の表示へ移行
  document.querySelectorAll('.slide img').forEach(function(im){const c=readCrop(im);if(c.t||c.r||c.b||c.l)applyCropStyle(im);});
  function positionCropOverlay(){
    if(!cropMode||!cropMode.isConnected){cropOverlay.style.display='none';return;}
    const r=cropMode.getBoundingClientRect();
    cropOverlay.style.display='block';
    cropOverlay.style.left=(r.left+window.scrollX)+'px';
    cropOverlay.style.top=(r.top+window.scrollY)+'px';
    cropOverlay.style.width=r.width+'px';
    cropOverlay.style.height=r.height+'px';
  }
  function _r4(v){return Math.round(v*10000)/10000;}
  function cropCalc(){ // cropState（倍率・位置）→ data-crop-* に書き戻して表示更新
    const st=cropState,img=cropMode;if(!st||!img)return;
    const s=st.s0*st.z,Dw=st.nw*s,Dh=st.nh*s;
    st.ox=Math.min(0,Math.max(st.fw-Dw,st.ox)); // 枠に隙間が出ないよう位置をクランプ
    st.oy=Math.min(0,Math.max(st.fh-Dh,st.oy));
    img.dataset.cropL=_r4(-st.ox/Dw);
    img.dataset.cropR=_r4((Dw-st.fw+st.ox)/Dw);
    img.dataset.cropT=_r4(-st.oy/Dh);
    img.dataset.cropB=_r4((Dh-st.fh+st.oy)/Dh);
    applyCropStyle(img);
    cropGhost.style.left=st.ox+'px';cropGhost.style.top=st.oy+'px';
    cropGhost.style.width=Dw+'px';cropGhost.style.height=Dh+'px';
    cropZoom.textContent='×'+(Math.round(st.z*100)/100);
    dirty=true;
  }
  function enterCropMode(img){
    if(!img.naturalWidth||!img.naturalHeight){alert('画像の読み込みが終わっていません');return;}
    pushAttr([img]); // 1セッション1Undo単位（⌘Zで開始前に戻る）
    cropMode=img;
    const r=img.getBoundingClientRect();
    const st={nw:img.naturalWidth,nh:img.naturalHeight,fw:r.width,fh:r.height};
    st.s0=Math.max(st.fw/st.nw,st.fh/st.nh); // z=1 ＝枠を過不足なく覆う倍率（cover相当）
    const c=readCrop(img);
    if(c.l||c.r||c.t||c.b){ // 既存クロップから倍率・位置を復元
      const Dw=st.fw/Math.max(0.05,1-c.l-c.r),Dh=st.fh/Math.max(0.05,1-c.t-c.b);
      const s=Math.max(Dw/st.nw,Dh/st.nh,st.s0);
      st.z=s/st.s0;st.ox=-c.l*st.nw*s;st.oy=-c.t*st.nh*s;
    }else{ // 初回＝中央で枠いっぱいに広げる
      st.z=1;st.ox=(st.fw-st.nw*st.s0)/2;st.oy=(st.fh-st.nh*st.s0)/2;
    }
    cropState=st;
    cropGhost.src=img.currentSrc||img.src;
    positionCropOverlay();cropCalc();
  }
  function exitCropMode(){cropMode=null;cropState=null;cropOverlay.style.display='none';}
  // 枠内ドラッグ＝表示位置の移動
  let cropPan=null;
  cropOverlay.addEventListener('mousedown',function(e){
    if(!cropMode||!cropState)return;
    e.preventDefault();e.stopPropagation();
    cropPan={x:e.clientX,y:e.clientY,ox:cropState.ox,oy:cropState.oy};
    cropOverlay.style.cursor='grabbing';
    window.addEventListener('mousemove',cropPanMove);
    window.addEventListener('mouseup',cropPanEnd);
  });
  function cropPanMove(e){if(!cropPan||!cropState)return;cropState.ox=cropPan.ox+(e.clientX-cropPan.x);cropState.oy=cropPan.oy+(e.clientY-cropPan.y);cropCalc();}
  function cropPanEnd(){cropPan=null;cropOverlay.style.cursor='grab';window.removeEventListener('mousemove',cropPanMove);window.removeEventListener('mouseup',cropPanEnd);}
  // 枠内ホイール＝カーソル位置を中心に拡大縮小（×1〜×8）
  cropOverlay.addEventListener('wheel',function(e){
    if(!cropMode||!cropState)return;
    e.preventDefault();e.stopPropagation();
    const st=cropState;
    const nz=Math.max(1,Math.min(8,st.z*Math.exp(-e.deltaY*0.0025)));
    if(nz===st.z)return;
    const or_=cropOverlay.getBoundingClientRect();
    const cx=e.clientX-or_.left,cy=e.clientY-or_.top;
    const k=nz/st.z; // カーソル直下の画像点を固定
    st.ox=cx-(cx-st.ox)*k;
    st.oy=cy-(cy-st.oy)*k;
    st.z=nz;
    cropCalc();
  },{passive:false});
  // 選択中の画像（img直接 or 画像を1枚だけ含む枠）を返す
  function selCropImg(){
    if(sels.length!==1)return null;
    const el=sels[0];
    if(el.tagName==='IMG')return el;
    if(el.querySelectorAll){const ims=el.querySelectorAll('img');if(ims.length===1)return ims[0];}
    return null;
  }
  cropRow.addEventListener('click',function(e){
    const b=e.target.closest('button[data-cp]');if(!b)return;
    const img=selCropImg();
    if(!img){alert('画像を選択してください');return;}
    if(b.dataset.cp==='on'){if(cropMode===img)exitCropMode();else enterCropMode(img);}
    else if(b.dataset.cp==='reset'){pushAttr([img]);delete img.dataset.cropT;delete img.dataset.cropR;delete img.dataset.cropB;delete img.dataset.cropL;applyCropStyle(img);exitCropMode();dirty=true;placeBox();}
  });
  window.addEventListener('scroll',()=>{if(cropMode)positionCropOverlay();});
  window.addEventListener('resize',()=>{if(cropMode)positionCropOverlay();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&cropMode){exitCropMode();}});

  // レイヤー順操作ボタン群
  const layerRow=document.createElement('div');layerRow.style.cssText='display:none;flex-direction:column;gap:3px;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.2)';
  layerRow.innerHTML='<span style="color:#eafff6;font:600 11px/1.3 sans-serif;display:block">レイヤー</span>'
    +'<div style="display:flex;flex-wrap:wrap;gap:3px"><button data-lo="fwd">▲前面</button><button data-lo="bwd">▼背面</button></div>'
    +'<div style="display:flex;flex-wrap:wrap;gap:3px"><button data-lo="front">⬆最前面</button><button data-lo="back">⬇最背面</button></div>';
  selbar.appendChild(layerRow);
  Array.from(layerRow.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:4px 8px;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer;flex:1;min-width:60px');
  layerRow.addEventListener('click',function(e){
    const op=e.target.getAttribute&&e.target.getAttribute('data-lo');if(!op||!sels.length)return;
    const slide=sels[0].closest('.slide');if(!slide)return;
    pushOrder(slide);
    let changed=false;
    if(op==='fwd')changed=bringForward(sels);
    else if(op==='bwd')changed=sendBackward(sels);
    else if(op==='front')changed=bringToFront(sels);
    else if(op==='back')changed=sendToBack(sels);
    if(!changed){undo.pop();}else{
      const opNames={fwd:'前面に1つ',bwd:'背面に1つ',front:'最前面',back:'最背面'};
      const slideNum=allSlides().indexOf(slide)+1;
      const targets=layerTargets(slide);
      sels.forEach(el=>{const idx=targets.indexOf(el);if(idx>=0)layerLog.push({slide:slideNum,eidx:idx+1,op:opNames[op]});});
      placeBox();
    }
  });
  alignRow.addEventListener('click',function(e){const al=e.target.getAttribute&&e.target.getAttribute('data-al');if(!al||!sels.length)return;
    // スライド基準は1つから、それ以外（選択同士の整列）は2つ以上必要
    if(al.indexOf('sl')!==0&&sels.length<2)return;pushAttr(sels.slice());
    if(al==='slcx'){const g=groupData();const off=Math.round((1280-g.w)/2-g.x);sels.forEach(el=>setX(el,N(A(el,'data-x'))+off));placeBox();return;}
    if(al==='slcy'){const g=groupData();const off=Math.round((720-g.h)/2-g.y);sels.forEach(el=>setY(el,N(A(el,'data-y'))+off));placeBox();return;}
    if(al==='w'){const mw=Math.max.apply(null,sels.map(el=>N(A(el,'data-w'))||el.getBoundingClientRect().width));sels.forEach(el=>setW(el,mw));}
    else if(al==='h'){const hs=sels.filter(el=>el.hasAttribute('data-h'));if(hs.length){const mh=Math.max.apply(null,hs.map(el=>N(A(el,'data-h'))));hs.forEach(el=>setH(el,mh));}}
    else if(al==='l'){const mx=Math.min.apply(null,sels.map(el=>N(A(el,'data-x'))));sels.forEach(el=>setX(el,mx));}
    else if(al==='t'){const my=Math.min.apply(null,sels.map(el=>N(A(el,'data-y'))));sels.forEach(el=>setY(el,my));}
    else if(al==='r'){const mr=Math.max.apply(null,sels.map(el=>N(A(el,'data-x'))+(N(A(el,'data-w'))||el.getBoundingClientRect().width)));sels.forEach(el=>setX(el,mr-(N(A(el,'data-w'))||el.getBoundingClientRect().width)));}
    else if(al==='b'){const mb=Math.max.apply(null,sels.map(el=>N(A(el,'data-y'))+(N(A(el,'data-h'))||el.getBoundingClientRect().height)));sels.forEach(el=>setY(el,mb-(N(A(el,'data-h'))||el.getBoundingClientRect().height)));}
    else if(al==='cx'){const centers=sels.map(el=>N(A(el,'data-x'))+(N(A(el,'data-w'))||el.getBoundingClientRect().width)/2);const avg=centers.reduce((a,b)=>a+b,0)/centers.length;sels.forEach(el=>setX(el,Math.round(avg-(N(A(el,'data-w'))||el.getBoundingClientRect().width)/2)));}
    else if(al==='cy'){const centers=sels.map(el=>N(A(el,'data-y'))+(N(A(el,'data-h'))||el.getBoundingClientRect().height)/2);const avg=centers.reduce((a,b)=>a+b,0)/centers.length;sels.forEach(el=>setY(el,Math.round(avg-(N(A(el,'data-h'))||el.getBoundingClientRect().height)/2)));}
    else if(al==='dh'){if(sels.length<3)return;const sorted=sels.slice().sort((a,b)=>N(A(a,'data-x'))-N(A(b,'data-x')));const first=N(A(sorted[0],'data-x')),lastEl=sorted[sorted.length-1],lastEnd=N(A(lastEl,'data-x'))+(N(A(lastEl,'data-w'))||lastEl.getBoundingClientRect().width);const totalW=sorted.reduce((s,el)=>s+(N(A(el,'data-w'))||el.getBoundingClientRect().width),0);const gap=(lastEnd-first-totalW)/(sorted.length-1);let cur=first;sorted.forEach(el=>{setX(el,Math.round(cur));cur+=(N(A(el,'data-w'))||el.getBoundingClientRect().width)+gap;});}
    else if(al==='dv'){if(sels.length<3)return;const sorted=sels.slice().sort((a,b)=>N(A(a,'data-y'))-N(A(b,'data-y')));const first=N(A(sorted[0],'data-y')),lastEl=sorted[sorted.length-1],lastEnd=N(A(lastEl,'data-y'))+(N(A(lastEl,'data-h'))||lastEl.getBoundingClientRect().height);const totalH=sorted.reduce((s,el)=>s+(N(A(el,'data-h'))||el.getBoundingClientRect().height),0);const gap=(lastEnd-first-totalH)/(sorted.length-1);let cur=first;sorted.forEach(el=>{setY(el,Math.round(cur));cur+=(N(A(el,'data-h'))||el.getBoundingClientRect().height)+gap;});}
    placeBox();});
  function updateSelPanel(){if(!selbar)return;
    // テキスト編集中（contentEditable）も選択パネルを出す
    const editingTb=document.activeElement&&document.activeElement.isContentEditable&&document.activeElement.closest&&document.activeElement.closest('.tb');
    if(editing&&(sels.length>=1||editingTb)){selbar.style.display='flex';const el=editingTb||sels[0];const tc=elTextHex(el),fc=elFillHex(el);selText.tx.value=tc;try{selText.sw.value=tc;}catch(_){}selText.resetSnap();(function(){const tEl=(el.classList&&el.classList.contains('tb'))?el:((el.querySelector&&el.querySelector('.tb'))||el);let eff=null;try{eff=rgbToHex(getComputedStyle(tEl).color);}catch(_){}if(eff&&normHex(eff)&&normHex(tc)&&normHex(eff)!==normHex(tc)){selTextNote.textContent='⚠ 画面表示は '+eff+'（フォーマットが色を自動変換中。元の値のままでOK）';selTextNote.style.display='block';}else selTextNote.style.display='none';})();selFill.tx.value=fc;try{selFill.sw.value=fc;}catch(_){}selFill.resetSnap();const tbs0=editingTb?[editingTb]:fsTbs();const hasTbl=sels.some(x=>x.tagName==='TABLE');if(tbs0.length||hasTbl){fontRow.style.display='flex';taRow.style.display='flex';vaRow.style.display='flex';bulletRow.style.display=tbs0.length?'flex':'none';if(fzInput)fzInput.value=tbs0.length?N(A(tbs0[0],'data-font-size')):tblFS(selTables()[0]||document.createElement('table'));if(typeof updFzPt==='function')updFzPt();const bb=fontRow.querySelector('[data-fz="bold"]');if(bb)bb.style.background=(tbs0.length&&A(tbs0[0],'data-bold')==='1')?'#0a7d55':'#0d5a40';}else{fontRow.style.display='none';bulletRow.style.display='none';taRow.style.display='none';vaRow.style.display='none';}actRow.style.display=sels.length>=1?'flex':'none';updateAskBtn();alignRow.style.display=sels.length>=1?'flex':'none';commonizeRow.style.display=(sels.length===1&&isCardEl(sels[0]))?'flex':'none';linkRow.style.display=(sels.length===1&&sels[0].hasAttribute&&sels[0].hasAttribute('data-linked-parent'))?'flex':'none';badgeShapeRow.style.display=(sels.length===1&&sels[0].classList&&sels[0].classList.contains('rect')&&roleOf(sels[0])==='badge')?'flex':'none';const rectTgts=sels.filter(x=>x.classList&&x.classList.contains('rect')&&['circle','triangle','line','arrow','chevron','callout'].indexOf(A(x,'data-shape'))<0);if(rectTgts.length){radiusRow.style.display='flex';rdInput.value=N(A(rectTgts[0],'data-radius'))||0;}else radiusRow.style.display='none';const arTgt=(sels.length===1&&sels[0].classList&&['line','arrow'].indexOf(A(sels[0],'data-shape'))>=0)?sels[0]:null;if(arTgt){arrowRow.style.display='flex';const hr=arrowRow.querySelector('[data-headrow]');if(hr)hr.style.display=(A(arTgt,'data-shape')==='arrow')?'flex':'none';}else arrowRow.style.display='none';const cvT=(sels.length===1&&sels[0].classList&&A(sels[0],'data-shape')==='chevron')?sels[0]:null;chevRow.style.display=cvT?'flex':'none';if(sels.length===1){sizeRow.style.display='flex';const el=sels[0];wInput.value=N(A(el,'data-w'))||Math.round(el.getBoundingClientRect().width);hInput.value=N(A(el,'data-h'))||Math.round(el.getBoundingClientRect().height);}else sizeRow.style.display='none';const borderTgts=sels.filter(canBorder);if(borderTgts.length){borderRow.style.display='flex';const st=getBorderState(borderTgts[0]);bdwInput.value=st.w;bdcInput.value=st.c;try{bdcSw.value=st.c;}catch(_){}}else borderRow.style.display='none';refreshCardStyleRow();refreshTblColorRow();layerRow.style.display=(sels.length>=1)?'flex':'none';painterRow.style.display=(sels.length===1)?'flex':'none';if(painterSrc&&sels.length!==1&&!sels.includes(painterSrc))painterExit();const cimg=(typeof selCropImg==='function')?selCropImg():null;if(typeof cropRow!=='undefined'&&cropRow)cropRow.style.display=cimg?'flex':'none';if(typeof cropMode!=='undefined'&&cropMode&&cimg!==cropMode&&typeof exitCropMode==='function')exitCropMode();if(typeof cropMode!=='undefined'&&cropMode&&typeof positionCropOverlay==='function')positionCropOverlay();}else{if(typeof cropRow!=='undefined'&&cropRow)cropRow.style.display='none';if(typeof cropMode!=='undefined'&&cropMode&&typeof exitCropMode==='function')exitCropMode();selbar.style.display='none';}}
  const box=document.createElement('div');box.className='seui skit-live';
  box.style.cssText='position:absolute;border:2px solid #e8821a;pointer-events:none;display:none;z-index:99998';
  // リサイズハンドル：四隅＋四辺の8個（上・左からも掴める）。角=塗り(両軸)・辺=白(片軸)
  let rzSide='br';
  [['br','nwse-resize','right:-7px;bottom:-7px',1],
   ['tl','nwse-resize','left:-7px;top:-7px',1],
   ['tr','nesw-resize','right:-7px;top:-7px',1],
   ['bl','nesw-resize','left:-7px;bottom:-7px',1],
   ['r','ew-resize','right:-7px;top:calc(50% - 7px)',0],
   ['l','ew-resize','left:-7px;top:calc(50% - 7px)',0],
   ['b','ns-resize','bottom:-7px;left:calc(50% - 7px)',0],
   ['t','ns-resize','top:-7px;left:calc(50% - 7px)',0]
  ].forEach(function(d){
    const h=document.createElement('div');h.dataset.rz=d[0];
    h.style.cssText='position:absolute;width:14px;height:14px;border-radius:50%;pointer-events:auto;'+d[2]+';cursor:'+d[1]+';'+(d[3]?'background:#e8821a;border:2px solid #fff':'background:#fff;border:2px solid #e8821a');
    box.appendChild(h);
  });
  // 回転ハンドル：枠上中央の少し上。ドラッグで回転（90°近傍に吸着・Shiftで15°刻み）、ダブルクリックで0°
  // ハンドル上・回転ドラッグ中はカーソル自体を↻にする（SVGカーソル・中心=ホットスポット）
  const ROT_CUR='url("data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><text x="12" y="18" font-size="17" text-anchor="middle" font-family="sans-serif" font-weight="700" fill="#e8821a" stroke="#fafafa" stroke-width="0.9" paint-order="stroke">\u21bb</text></svg>')+'") 12 12, grab';
  const rotHandle=document.createElement('div');rotHandle.dataset.rot='1';
  rotHandle.title='ドラッグで回転（Shiftで15°刻み）／ダブルクリックで0°に戻す';
  rotHandle.textContent='↻';
  rotHandle.style.cssText='position:absolute;left:calc(50% - 9px);top:-34px;width:18px;height:18px;background:#fff;border:2px solid #e8821a;border-radius:50%;pointer-events:auto;display:flex;align-items:center;justify-content:center;font:700 12px/1 sans-serif;color:#e8821a;box-sizing:border-box';
  rotHandle.style.cursor=ROT_CUR;
  const rotLabel=document.createElement('div');
  rotLabel.style.cssText='position:absolute;left:calc(50% + 16px);top:-36px;display:none;background:rgba(22,42,66,.95);color:#fafafa;font:600 11px/1 sans-serif;padding:4px 7px;border-radius:5px;pointer-events:none;white-space:nowrap';
  box.appendChild(rotHandle);box.appendChild(rotLabel);
  let rotCx=0,rotCy=0,rotBase=0,rotStart=0;
  function updateRotHandle(){
    // 単一選択のみ・表は回転不可（PPTXのtableが回転を持てない）
    const ok=sels.length===1&&sels[0].tagName!=='TABLE';
    rotHandle.style.display=ok?'flex':'none';
    if(ok&&act==='rotate'){rotLabel.style.display='block';rotLabel.textContent=(N(A(sels[0],'data-rotate'))||0)+'°';}
    else rotLabel.style.display='none';
    // 反転・不透明度・吹き出しの行（🎯パネル）の表示もここで揃える
    if(typeof flipRow!=='undefined'&&flipRow)flipRow.style.display=(sels.length===1&&canFlip(sels[0]))?'flex':'none';
    if(typeof calloutRow!=='undefined'&&calloutRow)calloutRow.style.display=(sels.length===1&&A(sels[0],'data-shape')==='callout')?'flex':'none';
    if(typeof opRow!=='undefined'&&opRow){
      const opT=sels.length>=1&&sels.some(el=>el.classList&&el.classList.contains('rect')&&/^#[0-9a-fA-F]{6}/.test(A(el,'data-fill')||''));
      opRow.style.display=opT?'flex':'none';
      if(opT){const v=opRow.querySelector('[data-opval]');if(v)v.textContent=fillOpacityOf(sels[0])+'%';}
    }
    if(typeof navRow!=='undefined'&&navRow){
      const nvOk=sels.length===1&&sels[0].matches&&sels[0].matches(SEL)&&sels[0].tagName!=='TABLE';
      navRow.style.display=nvOk?'flex':'none';
      if(nvOk&&!act)refreshNavSel(sels[0]); // ドラッグ中は選択肢を作り直さない
    }
  }
  rotHandle.addEventListener('dblclick',function(e){
    if(sels.length!==1)return;
    e.preventDefault();e.stopPropagation();
    pushAttr([sels[0]]);setRot(sels[0],0);placeBox();
  });

  // ポストイット選択中だけ、選択枠の右上に文字サイズ操作を出す。
  // 選択枠の子にすることで、メモを移動・リサイズしても操作が自動追従する。
  var noteFsBar=document.createElement('div');noteFsBar.className='seui';
  noteFsBar.style.cssText='position:absolute;right:-2px;top:-42px;display:none;align-items:center;gap:4px;padding:4px 6px;background:rgba(22,42,66,.96);color:#fafafa;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.25);pointer-events:auto;white-space:nowrap';
  const noteFsMinus=document.createElement('button');noteFsMinus.type='button';noteFsMinus.setAttribute('data-note-fs','-2');noteFsMinus.textContent='−';noteFsMinus.title='メモの文字を2px小さくする';
  const noteFsValue=document.createElement('span');noteFsValue.style.cssText='min-width:48px;text-align:center;font:700 14px/1.2 sans-serif';noteFsValue.textContent='20px';
  const noteFsPlus=document.createElement('button');noteFsPlus.type='button';noteFsPlus.setAttribute('data-note-fs','2');noteFsPlus.textContent='＋';noteFsPlus.title='メモの文字を2px大きくする';
  [noteFsMinus,noteFsPlus].forEach(b=>{b.style.cssText='width:32px;height:30px;padding:0;border:none;border-radius:4px;background:#fafafa;color:#121212;font:700 18px/1 sans-serif;cursor:pointer';});
  noteFsBar.appendChild(noteFsMinus);noteFsBar.appendChild(noteFsValue);noteFsBar.appendChild(noteFsPlus);box.appendChild(noteFsBar);document.body.appendChild(box);
  // ボタン押下でcontenteditableからフォーカスが外れないようにする。
  noteFsBar.addEventListener('mousedown',e=>{e.preventDefault();e.stopPropagation();});
  noteFsBar.addEventListener('click',e=>{const b=e.target.closest('[data-note-fs]');if(!b)return;const note=sels.length===1&&A(sels[0],'data-note')==='1'?sels[0]:null;const tb=note&&note.querySelector(':scope > .tb');if(!tb)return;const cur=N(A(tb,'data-font-size'))||20;const next=Math.max(15,Math.min(48,cur+parseInt(b.getAttribute('data-note-fs'),10)));if(next===cur)return;pushAttr([note,tb]);setFS(tb,next);updateNoteFsBar();placeBox();});
  function updateNoteFsBar(){if(!noteFsBar)return;const note=editing&&sels.length===1&&A(sels[0],'data-note')==='1'?sels[0]:null;const tb=note&&note.querySelector(':scope > .tb');if(!tb){noteFsBar.style.display='none';return;}noteFsValue.textContent=(N(A(tb,'data-font-size'))||20)+'px';noteFsBar.style.display='flex';}

  // ---- すき間ガイド（A：選択した箱と隣／スライド端までの距離を px で表示）----
  // SlideKitは絶対座標なので margin/padding は無い。選んだ箱の上下左右について、
  // 同じスライド内で最も近い隣の箱（無ければスライド端）までの距離を線＋数値で示す。
  // 隣までの距離＝マゼンタ／スライド端までの距離＝グレーで色分け。単一選択時のみ。
  const gapG=document.createElement('div');gapG.className='seui skit-live';
  gapG.style.cssText='position:absolute;left:0;top:0;display:none;pointer-events:none;z-index:99996';
  document.body.appendChild(gapG);
  const gapUnits={};let gapInfo={};
  ['left','right','top','bottom'].forEach(side=>{
    const line=document.createElement('div');line.style.cssText='position:absolute;display:none';
    const inp=document.createElement('input');inp.type='text';inp.inputMode='numeric';inp.title='この隙間をpxで指定（Enterで反映）';
    inp.style.cssText='position:absolute;display:none;width:46px;text-align:center;font:600 12px/1 sans-serif;color:#121212;background:rgba(250,250,250,.96);border:1px solid rgba(216,22,150,.5);padding:2px 3px;border-radius:4px;transform:translate(-50%,-50%);box-shadow:0 1px 3px rgba(0,0,0,.2);pointer-events:auto;cursor:text';
    inp.addEventListener('mousedown',e=>e.stopPropagation());
    inp.addEventListener('focus',()=>{inp.select();inp._el=sels[0];inp._info=gapInfo[side];});
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){e.preventDefault();inp.blur();}else if(e.key==='Escape'){e.preventDefault();inp._el=null;inp.blur();if(typeof drawGapGuides==='function')drawGapGuides();}});
    inp.addEventListener('blur',()=>{if(typeof applyGapEdit==='function')applyGapEdit(side,inp.value,inp._el,inp._info);});
    gapG.appendChild(line);gapG.appendChild(inp);gapUnits[side]={line,chip:inp};
  });
  function hideGapG(){gapG.style.display='none';}
  function vOverlap(a,b){return Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);}
  function hOverlap(a,b){return Math.min(a.right,b.right)-Math.max(a.left,b.left);}
  // カーソルが要素の枠の「端」(12px以内)にあるか。文字枠の端つかみ＝移動モード判定に使う。
  function nearEdge(el,e){
    try{const r=el.getBoundingClientRect();const m=12;
      if(e.clientX<r.left-2||e.clientX>r.right+2||e.clientY<r.top-2||e.clientY>r.bottom+2)return false;
      return (e.clientX-r.left<=m)||(r.right-e.clientX<=m)||(e.clientY-r.top<=m)||(r.bottom-e.clientY<=m);
    }catch(_){return false;}
  }
  // ノード(.rect[data-x])の中に流し込まれた、自前data-xを持たないテキスト(.tb)なら、その親ノードを返す。
  // こういうテキストは絶対座標でなく親のpadding＋自分のmarginで位置が決まる＝余白はノード端から測る。
  function inNodeText(el){
    if(!el||!el.classList||!el.classList.contains('tb'))return null;
    if(el.matches&&el.matches(SEL))return null; // data-x を持つ＝スライド直下の独立要素
    const n=el.closest&&el.closest('.rect[data-x]');
    if(n&&n!==el&&n.contains(el))return n;
    return null;
  }
  // ノード(.rect)内に流し込まれた data-x 無しの文字を、見た目そのままにスライド直下の
  // 絶対配置へ切り出す（独立して動かせるようにする）。親子リンク(data-linked-parent)は維持。
  // 既に data-x を持つ要素はそのまま返す。
  function detachInnerTb(tb){
    if(!tb||tb.hasAttribute('data-x'))return tb;
    const slide=tb.closest&&tb.closest('.slide');if(!slide)return tb;
    const host=tb.parentElement;
    pushAttr([tb]);
    const sr=slide.getBoundingClientRect();const r=tb.getBoundingClientRect();
    const sc=(sr.width/1280)||1,scy=(sr.height/720)||1;
    const ix=Math.round((r.left-sr.left)/sc),iy=Math.round((r.top-sr.top)/scy),iw=Math.round(r.width/sc),ih=Math.round(r.height/scy);
    tb.setAttribute('data-x',ix);tb.setAttribute('data-y',iy);tb.setAttribute('data-w',iw);tb.setAttribute('data-h',ih);
    setStyleProp(tb,'position','absolute');setStyleProp(tb,'left',ix+'px');setStyleProp(tb,'top',iy+'px');setStyleProp(tb,'width',iw+'px');setStyleProp(tb,'height',ih+'px');
    if(host&&host.classList&&host.classList.contains('rect')){const pid=ensureSkid(host);tb.setAttribute('data-linked-parent',pid);}
    slide.appendChild(tb);
    return tb;
  }
  // すき間の数値を編集→選択した箱を、その隙間がg pxになる位置へ動かす（隣は動かさない）。
  // el/info はフォーカス時のスナップショット（入力中に選択が変わっても取り違えない）。
  function applyGapEdit(side,raw,el,info){
    el=el||sels[0];if(!el||!el.isConnected)return;
    const slide=el.closest&&el.closest('.slide');if(!slide)return;
    let g=parseInt(raw,10);if(!isFinite(g))return;if(g<0)g=0;
    info=info||gapInfo[side]||{};
    // ノード内テキスト：余白＝ノード端からの距離。テキストの margin を増減して inset を g にする。
    if(info.mode==='inset'&&info.node&&info.node.isConnected){
      const node=info.node;const S=el.getBoundingClientRect(),NR=node.getBoundingClientRect();
      const cur={left:S.left-NR.left,right:NR.right-S.right,top:S.top-NR.top,bottom:NR.bottom-S.bottom}[side];
      const mProp={left:'marginLeft',right:'marginRight',top:'marginTop',bottom:'marginBottom'}[side];
      let csm=0;try{csm=parseFloat(getComputedStyle(el)[mProp])||0;}catch(_){csm=0;}
      const newM=Math.max(0,Math.round(csm+(g-cur)));
      pushStyle(el);
      el.style[mProp]=newM+'px';
      placeBox();
      return;
    }
    const nb=info.nbEl&&info.nbEl.isConnected?info.nbEl:null;
    const SLr=slide.getBoundingClientRect();const sc=(SLr.width/1280)||1,scy=(SLr.height/720)||1;
    const ew=N(A(el,'data-w'))||Math.round(el.getBoundingClientRect().width/sc);
    const eh=N(A(el,'data-h'))||Math.round(el.getBoundingClientRect().height/scy);
    const nbX=nb?N(A(nb,'data-x')):0,nbY=nb?N(A(nb,'data-y')):0;
    const nbW=nb?(N(A(nb,'data-w'))||Math.round(nb.getBoundingClientRect().width/sc)):0;
    const nbH=nb?(N(A(nb,'data-h'))||Math.round(nb.getBoundingClientRect().height/scy)):0;
    pushAttr([el]);
    if(side==='left')setX(el,(nb?nbX+nbW:0)+g);
    else if(side==='right')setX(el,(nb?nbX:1280)-g-ew);
    else if(side==='top')setY(el,(nb?nbY+nbH:0)+g);
    else setY(el,(nb?nbY:720)-g-eh);
    baseSnap(el);placeBox();
  }
  function drawGapGuides(){
    if(!editing||sels.length!==1){hideGapG();return;}
    const el=sels[0];const slide=el.closest&&el.closest('.slide');
    if(!slide){hideGapG();return;}
    const S=el.getBoundingClientRect();const SL=slide.getBoundingClientRect();
    const scale=(SL.width/1280)||1;
    gapG.style.display='block';
    const ox=window.scrollX,oy=window.scrollY,cx=S.left+S.width/2,cy=S.top+S.height/2;
    const NB='rgba(216,22,150,.6)',ED='rgba(94,94,94,.5)',INS='rgba(33,150,136,.7)';
    const put=(side,gap,color)=>{
      const u=gapUnits[side];
      if(gap===null||gap<0.5){u.line.style.display='none';u.chip.style.display='none';return;}
      u.line.style.display='block';u.chip.style.display='block';
      u.line.style.background=color;u.chip.value=Math.round(gap/scale);
      if(side==='left'){u.line.style.left=(S.left-gap+ox)+'px';u.line.style.top=(cy+oy-1)+'px';u.line.style.width=gap+'px';u.line.style.height='2px';u.chip.style.left=(S.left-gap/2+ox)+'px';u.chip.style.top=(cy+oy)+'px';}
      else if(side==='right'){u.line.style.left=(S.right+ox)+'px';u.line.style.top=(cy+oy-1)+'px';u.line.style.width=gap+'px';u.line.style.height='2px';u.chip.style.left=(S.right+gap/2+ox)+'px';u.chip.style.top=(cy+oy)+'px';}
      else if(side==='top'){u.line.style.left=(cx+ox-1)+'px';u.line.style.top=(S.top-gap+oy)+'px';u.line.style.width='2px';u.line.style.height=gap+'px';u.chip.style.left=(cx+ox)+'px';u.chip.style.top=(S.top-gap/2+oy)+'px';}
      else{u.line.style.left=(cx+ox-1)+'px';u.line.style.top=(S.bottom+oy)+'px';u.line.style.width='2px';u.line.style.height=gap+'px';u.chip.style.left=(cx+ox)+'px';u.chip.style.top=(S.bottom+gap/2+oy)+'px';}
    };
    // ノード内テキスト：余白は親ノードの内側端からの距離(inset)で出す（隣やスライド端でなく）。
    const node=inNodeText(el);
    if(node){
      const NR=node.getBoundingClientRect();
      const ins={left:S.left-NR.left,right:NR.right-S.right,top:S.top-NR.top,bottom:NR.bottom-S.bottom};
      gapInfo={};
      ['left','right','top','bottom'].forEach(side=>{gapInfo[side]={mode:'inset',node:node};put(side,ins[side],INS);});
      return;
    }
    const cands=[];
    slide.querySelectorAll('[data-x]').forEach(n=>{
      if(n===el||n.classList.contains('seui'))return;
      if(n.contains(el)||el.contains(n))return;
      if(typeof isPageno==='function'&&isPageno(n))return;
      const q=n.getBoundingClientRect();if(q.width<=0||q.height<=0)return;
      cands.push({q,el:n});
    });
    const sides={left:{edge:S.left-SL.left,nb:null,nbEl:null},right:{edge:SL.right-S.right,nb:null,nbEl:null},top:{edge:S.top-SL.top,nb:null,nbEl:null},bottom:{edge:SL.bottom-S.bottom,nb:null,nbEl:null}};
    cands.forEach(c=>{const q=c.q;
      if(q.right<=S.left+1&&vOverlap(S,q)>1){const g=S.left-q.right;if(g>=-1&&(sides.left.nb===null||g<sides.left.nb)){sides.left.nb=g;sides.left.nbEl=c.el;}}
      if(q.left>=S.right-1&&vOverlap(S,q)>1){const g=q.left-S.right;if(g>=-1&&(sides.right.nb===null||g<sides.right.nb)){sides.right.nb=g;sides.right.nbEl=c.el;}}
      if(q.bottom<=S.top+1&&hOverlap(S,q)>1){const g=S.top-q.bottom;if(g>=-1&&(sides.top.nb===null||g<sides.top.nb)){sides.top.nb=g;sides.top.nbEl=c.el;}}
      if(q.top>=S.bottom-1&&hOverlap(S,q)>1){const g=q.top-S.bottom;if(g>=-1&&(sides.bottom.nb===null||g<sides.bottom.nb)){sides.bottom.nb=g;sides.bottom.nbEl=c.el;}}
    });
    ['left','right','top','bottom'].forEach(side=>{const s=sides[side];const useNb=s.nb!==null;gapInfo[side]={toNb:useNb,nbEl:useNb?s.nbEl:null};put(side,useNb?s.nb:s.edge,useNb?NB:ED);});
  }
  // ラバーバンド（空白ドラッグで矩形選択）
  const marq=document.createElement('div');marq.className='seui skit-live';marq.style.cssText='position:fixed;border:1.5px solid #e8821a;background:rgba(232,130,26,.12);display:none;z-index:99998;pointer-events:none';document.body.appendChild(marq);
  function marqRect(e){const x1=Math.min(sx,e.clientX),y1=Math.min(sy,e.clientY),x2=Math.max(sx,e.clientX),y2=Math.max(sy,e.clientY);return {l:x1,t:y1,r:x2,b:y2};}
  function selectInMarquee(r){const hit=[];document.querySelectorAll('.slide [data-x]').forEach(el=>{if(el.classList.contains('seui'))return;const q=el.getBoundingClientRect();const inter=!(q.right<r.l||q.left>r.r||q.bottom<r.t||q.top>r.b);if(inter)hit.push(el);});
    // 親(.rect等)と中身の重複を避ける：選ばれた要素の祖先が同じく選ばれていれば子は除外
    const set=hit.filter(el=>!hit.some(o=>o!==el&&o.contains(el)));if(set.length)setSel(set);else clearSel();}

  const tbar=document.createElement('div');tbar.className='seui';
  tbar.style.cssText='position:absolute;display:none;align-items:center;gap:4px;z-index:99998;font-family:sans-serif';
  tbar.innerHTML='<button data-op="rp" title="行を末尾に追加">行＋</button><button data-op="rm" title="選択行を削除（範囲なしは末尾行）">行✕</button><button data-op="cp" title="列を末尾に追加">列＋</button><button data-op="cm" title="選択列を削除（範囲なしは末尾列）">列✕</button><button data-op="hp" title="選択行の高さを増やす（範囲なしは全行）">高さ＋</button><button data-op="hm" title="選択行の高さを減らす（範囲なしは全行）">高さ－</button>'
    +'<span style="color:#fff;font:600 12px/1 sans-serif;margin:0 2px 0 8px">枠</span><input id="seBdC" type="color" value="#d7dde3" style="width:24px;height:20px;border:none;background:none;cursor:pointer;padding:0">'
    +'<button data-bd="0">なし</button><button data-bd="1">細</button><button data-bd="2">中</button><button data-bd="3">太</button>'
    +'<button data-op="grp" title="選択したセル範囲を同色+外周線だけにして1つの大きなセルに見せる（結合しない）。セル範囲はドラッグ or クリック→Shift+クリック">大項目</button>'
    +'<button data-op="ungrp" title="選択したセル範囲の塗りと枠線を解除">解除</button>';
  document.body.appendChild(tbar);
  Array.from(tbar.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:4px 10px;border:none;border-radius:7px;background:#e8821a;color:#fff;font-size:13px;cursor:pointer;margin-right:4px');
  tbar.addEventListener('mousedown',e=>e.stopPropagation());
  const bdInput=tbar.querySelector('#seBdC');
  bdInput.addEventListener('mousedown',e=>e.stopPropagation());
  bdInput.addEventListener('input',()=>{bdColor=bdInput.value;});
  tbar.addEventListener('click',function(e){
    const bd=e.target.getAttribute&&e.target.getAttribute('data-bd');
    if(bd!=null){const t=sels[0];if(!t||t.tagName!=='TABLE')return;pushAttr([t]);applyCellBorder(t,parseInt(bd,10),bdColor);return;}
    const op=e.target.getAttribute&&e.target.getAttribute('data-op');if(!op)return;const t=sels[0];if(!t||t.tagName!=='TABLE')return;if(op==='rp')tblAddRow(t);else if(op==='rm')tblDelRow(t);else if(op==='cp')tblAddCol(t);else if(op==='cm')tblDelCol(t);else if(op==='hp')tblRowH(t,3);else if(op==='hm')tblRowH(t,-3);else if(op==='grp')applyCellGroup(t);else if(op==='ungrp')clearCellGroup(t);placeBox();});

  // ---- 大項目（疑似結合）: 選択セル範囲を同色で塗り、外周辺だけ線を引く（セル結合しない）----
  // PPTX変換はセル辺のCSS borderをそのまま a:lnL/lnR/lnT/lnB にするので、変換後も同じ見た目になる。
  // 内側の辺は 'none' を明示（行区切り線が透けて「複数セル感」が出るのを防ぐ）
  function cellRangeBox(t,tc){
    const ps=tc.map(c=>cellPos(t,c)).filter(Boolean);
    if(!ps.length)return null;
    return {r1:Math.min(...ps.map(p=>p.r)),r2:Math.max(...ps.map(p=>p.r)),
            c1:Math.min(...ps.map(p=>p.c)),c2:Math.max(...ps.map(p=>p.c))};
  }
  function applyCellGroup(t){
    const tc=targetCells();
    if(!tc||tc.length<2||tc.some(c=>c.closest('table')!==t)){
      alert('先にセルを範囲選択してください。\n表をクリックで選択 → セルの上をドラッグ（またはセルをクリック → 端のセルをShift+クリック）');
      return;
    }
    pushAttr([t]);
    const b=cellRangeBox(t,tc);if(!b)return;
    // 線色: 枠色input が既定(#d7dde3)のままなら見出し青、変更済みならその色
    const line='2px solid '+(bdColor.toLowerCase()==='#d7dde3'?'#21537f':bdColor);
    // 塗り: 左上セルに既存の背景があれば引き継ぐ（黄系グループの再適用等）、無ければ青灰。
    // 🚨style属性の正規表現では拾わない: 選択outline等でstyleを触るとブラウザが
    // 'background:#f4f4ef' を 'background: rgb(244,244,239)' に正規化するため、hex直読みは失敗する
    const first=t.rows[b.r1].cells[b.c1];
    let fill='#eef3f8';
    const bgv=(first.style&&first.style.backgroundColor)||'';
    let m=bgv.match(/^#[0-9a-fA-F]{3,8}$/);
    if(m)fill=bgv;
    else{m=bgv.match(/^rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/);
      if(m)fill='#'+[m[1],m[2],m[3]].map(v=>(+v).toString(16).padStart(2,'0')).join('');}
    tc.forEach(c=>{
      const p=cellPos(t,c);if(!p)return;
      setStyleProp(c,'background',fill);
      setStyleProp(c,'border-top',p.r===b.r1?line:'none');
      setStyleProp(c,'border-bottom',p.r===b.r2?line:'none');
      setStyleProp(c,'border-left',p.c===b.c1?line:'none');
      setStyleProp(c,'border-right',p.c===b.c2?line:'none');
    });
    setStyleProp(first,'vertical-align','top'); // 見出しテキストは左上セルに書く想定
  }
  function clearCellGroup(t){
    const tc=targetCells();
    if(!tc||tc.some(c=>c.closest('table')!==t)){alert('解除するセルを範囲選択してください');return;}
    pushAttr([t]);
    tc.forEach(c=>['background','border-top','border-bottom','border-left','border-right','vertical-align'].forEach(pr=>rmStyleProp(c,pr)));
  }

  const rlabel=document.createElement('div');rlabel.className='seui skit-live';
  rlabel.style.cssText='position:absolute;display:none;z-index:99998;background:#1f7a5a;color:#fff;font:600 12px/1.4 sans-serif;padding:3px 9px;border-radius:6px;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.25)';
  document.body.appendChild(rlabel);
  const idlabel=document.createElement('div');idlabel.className='seui skit-live';
  idlabel.style.cssText='position:absolute;display:none;z-index:99998;background:#162a42;color:#fff;font:600 11px/1.4 sans-serif;padding:2px 7px;border-radius:5px;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.25)';
  document.body.appendChild(idlabel);

  // 3カラムレイアウト用CSS注入（編集モードON時のみ有効）
  const skitStyle=document.createElement('style');skitStyle.className='seui';skitStyle.textContent=
    // スクロールバーを常時表示（編集ON/OFFでスクロールバーが出たり消えたりすると
    // fixedのツールバーがバー幅ぶん左右にズレるため、最初から幅を確保しておく）
    'html{overflow-y:scroll}'
    // キット共通ブランド（丸に井桁＋SlideKit・.kiro/steering/kit-common-header.md）
    // 閲覧時=左上に浮かせるだけ／編集時=全幅48pxバーになり、ページはその下から
    +'.skit-brand{position:fixed;left:0;top:0;height:48px;display:flex;align-items:center;gap:8px;padding:0 14px;z-index:99996;color:#e2e8f0;font:700 17px/1 "Yu Gothic","游ゴシック",Meiryo,sans-serif;pointer-events:none;box-sizing:border-box}'
    +'.skit-brand svg{width:22px;height:22px;display:block;flex:none}'
    // サムネイル一覧を出している時は、ロゴの下に不透明の帯を必ず敷く（透けると1枚目と重なって見える）
    +'body[data-skit-edit="on"] .skit-brand{width:100%;background:#1f2933;box-shadow:0 2px 8px rgba(0,0,0,.2)}'
    +'.skit-brand::before{content:"";position:absolute;left:0;top:0;width:128px;height:48px;background:#1f2933;z-index:-1}'
    +'body._sp_active .skit-brand{display:none}'
    +'@media print{.skit-brand{display:none}}'
    +'body[data-skit-edit="on"]{display:block!important;padding:48px 0 0!important;margin-left:140px;margin-right:'+(SK_PANEL_W+16)+'px;background:#3a4756!important}'
    +'body[data-skit-edit="on"] .slide{margin:14px auto!important}'
    // top=52px はロゴ（.skit-brand は高さ48px）の下から始める値。48pxだと1枚目がロゴに食い込む（2026-09-16）
    +'.skit-thumbs{position:fixed;left:0;top:52px;bottom:0;width:128px;background:#1f2933;overflow-y:auto;z-index:99995;padding:8px 6px;box-shadow:2px 0 8px rgba(0,0,0,.2);box-sizing:border-box;font-family:Meiryo,sans-serif}'
    +'.skit-thumb{display:block;width:100%;margin-bottom:6px;padding:6px 8px;background:#162a42;color:#cdd9e5;border:none;border-radius:5px;cursor:pointer;font-size:11px;line-height:1.35;text-align:left;border-left:3px solid transparent;transition:all .15s}'
    +'.skit-thumb:hover{background:#234060;color:#fff}'
    +'.skit-thumb.cur{border-left-color:#fafafa;background:#21537f;color:#fff}'
    +'.skit-thumb .pn{display:block;font-size:9px;color:#7a92ad;margin-bottom:2px;font-weight:700}'
    +'body[data-skit-edit="on"] .skit-edit-col{position:fixed!important;top:48px!important;right:0!important;bottom:0!important;left:auto!important;width:'+SK_PANEL_W+'px!important;max-width:none!important;max-height:none!important;background:#1f2933!important;padding:10px '+SK_PANEL_PAD+'px!important;border-radius:0!important;box-shadow:-2px 0 8px rgba(0,0,0,.2);overflow-y:auto;box-sizing:border-box}'
    // 狭い列でも文字が列の外へ出ないよう、ボタンは折り返す（2026-09-27 幅を2/3にした時に追加）
    //   左右の余白は詰め、日本語は語の途中（「中央」「なし」等）で割らない
    +'#_sk_toolbar button{white-space:normal!important;word-break:keep-all;overflow-wrap:anywhere;line-height:1.25;padding-left:4px!important;padding-right:4px!important}'
    +'#_sk_toolbar .bd-mini{min-width:0!important}'
    +'.skit-pal-hl{outline:4px solid #ffd60a!important;outline-offset:2px!important;box-shadow:0 0 0 8px rgba(255,214,10,.35),0 0 20px rgba(255,214,10,.8)!important;transition:outline .1s,box-shadow .1s;animation:skit-pal-pulse .8s ease-in-out infinite alternate}'
    +'@keyframes skit-pal-pulse{from{box-shadow:0 0 0 4px rgba(255,214,10,.4),0 0 12px rgba(255,214,10,.6)!important}to{box-shadow:0 0 0 10px rgba(255,214,10,.2),0 0 24px rgba(255,214,10,.9)!important}}'
    +'.skit-pal-row-hover{background:rgba(255,214,10,.15)!important;border-radius:4px}'
    +'.bd-big{padding:6px 10px!important;border:none;border-radius:6px;background:#0d5a40;color:#fff;font-size:12px;cursor:pointer;flex:1}'
    +'.bd-mini{position:relative;height:32px;background:#0d5a40;border:none;border-radius:6px;cursor:pointer}'
    +'.bd-mini::before{content:"";position:absolute;top:50%;left:50%;width:26px;height:18px;margin:-9px 0 0 -13px;border:1px solid rgba(255,255,255,0.35);box-sizing:border-box;pointer-events:none}'
    +'.bd-mini::after{content:"";position:absolute;background:#fff;pointer-events:none}'
    +'.bd-mini.bd-all::after{top:50%;left:50%;width:26px;height:18px;margin:-9px 0 0 -13px;border:2px solid #fff;background:transparent;box-sizing:border-box}'
    +'.bd-mini.bd-top::after{top:50%;left:50%;width:26px;height:3px;margin:-9px 0 0 -13px}'
    +'.bd-mini.bd-bottom::after{top:50%;left:50%;width:26px;height:3px;margin:6px 0 0 -13px}'
    +'.bd-mini.bd-left::after{top:50%;left:50%;width:3px;height:18px;margin:-9px 0 0 -13px}'
    +'.bd-mini.bd-right::after{top:50%;left:50%;width:3px;height:18px;margin:-9px 0 0 10px}'
    +'.bd-mini:hover{background:#0f6b4a}';
  document.head.appendChild(skitStyle);

  // キット共通ブランド（左上・kit-common-header.md準拠。保存時はseuiとして剥がれる）
  const brandBar=document.createElement('div');brandBar.className='seui skit-brand';
  brandBar.innerHTML='<svg viewBox="414 291 285 285" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M557.82 294.27C633.96 294.27 695.68 355.99 695.68 432.13C695.68 508.27 633.96 569.99 557.82 569.99C481.68 569.99 419.96 508.27 419.96 432.13C419.96 355.99 481.68 294.27 557.82 294.27ZM447.11 432.13C447.11 493.27 496.68 542.84 557.82 542.84C618.96 542.84 668.52 493.27 668.52 432.13C668.52 370.99 618.96 321.43 557.82 321.43C496.68 321.43 447.11 370.99 447.11 432.13Z"/><path fill="currentColor" d="M586.49 351.44h29.07v224.03h-29.07ZM497.43 291.45h29.07v224.03h-29.07ZM414.48 489.87V460.8h224.03v29.07ZM474.47 403.46V374.4h224.04v29.06Z"/></svg>SlideKit';
  document.body.appendChild(brandBar);

  // 左ペイン（ページサムネ）
  const thumbsPane=document.createElement('div');thumbsPane.className='seui skit-thumbs';thumbsPane.style.display='none';document.body.appendChild(thumbsPane);
  function rebuildThumbs(){thumbsPane.innerHTML='';allSlides().forEach((s,i)=>{const b=document.createElement('button');b.className='skit-thumb';b.dataset.idx=i;const ttl=slideTitleOf(s);b.innerHTML='<span class="pn">P'+(i+1)+'</span>'+(ttl||'(無題)');b.onclick=()=>{s.scrollIntoView({behavior:'smooth',block:'center'});thumbsPane.querySelectorAll('.skit-thumb').forEach(x=>x.classList.remove('cur'));b.classList.add('cur');clearSel();selectPage(s);b.focus();};thumbsPane.appendChild(b);});}
  // 左サムネペイン内クリックは選択解除（テキストやオブジェクトの選択を外す）
  thumbsPane.addEventListener('mousedown',e=>{if(sels.length)clearSel();e.stopPropagation();});
  function highlightCurrentThumb(){const cs=currentSlide();if(!cs)return;const idx=allSlides().indexOf(cs);thumbsPane.querySelectorAll('.skit-thumb').forEach((b,i)=>b.classList.toggle('cur',i===idx));}
  window.addEventListener('scroll',()=>{if(editing)highlightCurrentThumb();},{passive:true});

  // Escape キーで選択解除
  document.addEventListener('keydown',function(e){
    if(!editing)return;
    if(e.key==='Escape'){
      if(isInputFocused()){const ae=document.activeElement;if(ae&&ae.blur)ae.blur();}
      if(sels.length){clearSel();e.preventDefault();}
      else if(pageSel&&pageSel.isConnected){clearPageSel();e.preventDefault();}
    }
  });

  // ページ単位のコピー＆ペースト（編集モード中・サムネペインにフォーカスがある時を優先）
  function isInputFocused(){const ae=document.activeElement;if(!ae)return false;const t=ae.tagName;if(t==='INPUT'||t==='TEXTAREA')return true;if(ae.isContentEditable)return true;return false;}
  // 文字選択のハイライトを消す。スライド内の選択だけ対象（パネルのinput内の選択は触らない）
  // 文字編集を抜けても青いハイライトが残る問題の対処（2026-09-08）
  function clearTextSel(){
    try{
      const s=window.getSelection();if(!s||!s.rangeCount)return;
      const n=s.anchorNode;const host=n?(n.nodeType===1?n:n.parentElement):null;
      if(host&&host.closest&&host.closest('.slide'))s.removeAllRanges();
    }catch(_){}
  }
  // 文字編集を終了する（Escape・スライド外クリック・他要素クリックで共用）
  function exitTextEdit(){
    let any=false;
    document.querySelectorAll('.slide [contenteditable="true"]').forEach(function(el){
      el.contentEditable='false';try{el.blur();}catch(_){}any=true;});
    clearTextSel();
    return any;
  }
  // パネルの入力欄にフォーカスが残っているとDeleteキーが効かないため、
  // スライド側を操作し始めた時点でフォーカスを外す（2026-09-08）
  function blurPanelInput(){
    const ae=document.activeElement;
    if(ae&&ae.closest&&ae.closest('.seui')&&(ae.tagName==='INPUT'||ae.tagName==='TEXTAREA')){try{ae.blur();}catch(_){}}
  }
  function isOnThumbPane(){const ae=document.activeElement;return ae&&ae.classList&&ae.classList.contains('skit-thumb');}
  document.addEventListener('keydown',function(e){
    if(!editing)return;
    const onThumb=isOnThumbPane();
    // サムネフォーカス時は常にページ操作を優先。サムネ外＋テキスト編集中はスキップ
    if(!onThumb&&isInputFocused())return;
    const isCopy=(e.key==='c'||e.key==='C')&&(e.metaKey||e.ctrlKey)&&!e.shiftKey&&!e.altKey;
    const isCut=(e.key==='x'||e.key==='X')&&(e.metaKey||e.ctrlKey)&&!e.shiftKey&&!e.altKey;
    const isPaste=(e.key==='v'||e.key==='V')&&(e.metaKey||e.ctrlKey)&&!e.shiftKey&&!e.altKey;
    // サムネフォーカスなしの時は、ページ選択中（pageSel）のみ動作（オブジェクト選択中などは通常コピペ動作にする）
    if(!onThumb){
      // 要素コピー/カット：選択要素を内部クリップボードへ（別ページの同じ位置に貼れる）。
      // 第2のkeydownの参照コピーに上書きされないよう stopImmediatePropagation する。
      if((isCopy||isCut)&&sels.length>0){if(copyEls(isCut)){e.preventDefault();e.stopImmediatePropagation();return;}}
      // ペースト：keydownでは何もせず、pasteイベントに委ねる（keydownでpreventDefaultするとpasteが発火せず画像が貼れないため）
      if(isPaste)return;
      if(!(pageSel&&pageSel.isConnected))return;
      // オブジェクト選択中（sels.length>0）は通常コピペを邪魔しない
      if(sels.length>0)return;
    }
    if(isCopy||isCut){
      const target=pageSel&&pageSel.isConnected?pageSel:null;
      if(!target)return;
      e.preventDefault();
      const html='<!--SKIT-PAGE-->'+target.outerHTML;
      lastCopyPayload=html;
      try{
        navigator.clipboard.writeText(html).then(()=>{
          if(typeof pageBadge!=='undefined'){pageBadge.style.background='#1a5a32';pageBadge.textContent=isCut?'✂️ ページを切り取りました':'📋 ページをコピーしました';setTimeout(()=>{pageBadge.style.background='#e8821a';pageBadge.textContent='📄 このページを選択中';},1600);}
          if(isCut){pushRemove(target);target.remove();clearPageSel();afterStruct();rebuildThumbs();}
        });
      }catch(_){}
    }
    // ページ選択中のペーストも pasteイベント側で処理する
  });

  bar.querySelector('#seEdit').onclick=function(){editing=!editing;this.style.background=editing?'#e8821a':'rgba(74,74,74,.95)';this.textContent=editing?'✏️ 編集中':'✏️ 編集';if(typeof pal!=='undefined'&&pal)pal.style.display=editing?'flex':'none';if(editing&&typeof palRows!=='undefined')palRows.forEach(fn=>fn());if(pagebar)pagebar.style.display=editing?'flex':'none';if(editing)updatePageLabel();if(!editing){clearSel();clearPageSel();}if(editing){document.body.setAttribute('data-skit-edit','on');rebuildThumbs();thumbsPane.style.display='block';bar.classList.add('skit-edit-col');setTimeout(highlightCurrentThumb,100);}else{document.body.removeAttribute('data-skit-edit');thumbsPane.style.display='none';bar.classList.remove('skit-edit-col');}};
  // ?edit=1 で開いた時（プレゼン窓を編集できる状態で開いた時）は、最初から編集モードにする。
  //   再生中はサムネイル一覧を出さない（投影の邪魔になる）ので、開いた直後に閉じる
  if(AUTO_EDIT){
    setTimeout(()=>{
      const eb=bar.querySelector('#seEdit');
      if(eb&&!editing){
        eb.click();
        if(document.body.classList.contains('_sp_active')&&thumbsPane){
          thumbsPane.style.display='none';
          bar.classList.remove('skit-edit-col');
        }
      }
    },300);
  }

  // ---- S2: 文字が枠に入りきらない印（画面だけ・2026-11-15） ----
  // ブラウザは .tb{overflow:hidden} で文字を切って隠すが、PPTX は切らずに下へあふれる（html_to_pptx の実測警告と対）。
  // 編集中だけ、はみ出す .tb に赤い点線の枠（.sk-ovmark）を重ね、数をバッジで出す。
  //   枠もバッジも seui なので💾保存時に _sanitizeSlide が剥がす＝HTML には残らない。
  //   判定: scrollHeight−clientHeight が max(4, 字の大きさ×0.4)px を超える時。
  //   🚫 以前は印が無く、1行ぶんあふれても画面では切れて気づけなかった。
  //   1行だけ4〜6px高い（行の高さの丸め・ディセンダ）のは字の大きさ比の下限で見逃す＝型の一覧の誤検出を避ける。
  const ovBadge=document.createElement('div');ovBadge.className='seui';
  ovBadge.style.cssText='position:fixed;left:10px;bottom:10px;display:none;max-width:280px;background:#c62828;color:#fff;font:700 12px/1.35 sans-serif;padding:7px 11px;border-radius:8px;z-index:99996;box-shadow:0 2px 8px rgba(0,0,0,.25);pointer-events:none';
  document.body.appendChild(ovBadge);
  function ovThresh(fs){return Math.max(4,(fs||16)*0.4);}
  function markOverflow(){
    document.querySelectorAll('.sk-ovmark').forEach(x=>x.remove());
    let n=0;
    document.querySelectorAll('.slide .tb').forEach(tb=>{
      const cs=getComputedStyle(tb);
      if(cs.display==='none'||cs.visibility==='hidden')return;
      if(cs.overflowY==='visible')return; // .rect>.tb / .flow>.tb は切らない＝対象外
      const ov=tb.scrollHeight-tb.clientHeight;
      if(ov<=ovThresh(parseFloat(cs.fontSize)))return;
      const slide=tb.closest('.slide');if(!slide)return;
      const sr=slide.getBoundingClientRect(),br=tb.getBoundingClientRect();
      const mk=document.createElement('div');mk.className='seui sk-ovmark';
      mk.style.cssText='position:absolute;left:'+(br.left-sr.left)+'px;top:'+(br.top-sr.top)+'px;width:'+br.width+'px;height:'+br.height+'px;border:2px dotted #c62828;box-sizing:border-box;pointer-events:none;z-index:40;border-radius:2px';
      slide.appendChild(mk);n++;
    });
    if(n){ovBadge.textContent='⚠ 文字が枠に入りきらない枠が'+n+'か所（赤い点線）。PPTXでは下へあふれます';ovBadge.style.display='block';}
    else ovBadge.style.display='none';
  }
  let _ovObs=null,_ovTimer=null;
  function _ovSchedule(){clearTimeout(_ovTimer);_ovTimer=setTimeout(_ovRun,300);}
  function _ovRun(){
    if(!editing){stopOv();return;}
    if(_ovObs)_ovObs.disconnect();              // 自分の印の付け外し（childList変化）で呼び戻らないよう一旦外す
    try{markOverflow();}catch(_){}
    if(_ovObs&&editing)_ovObs.observe(document.body,{childList:true,subtree:true,characterData:true});
  }
  function startOv(){
    if(!_ovObs)_ovObs=new MutationObserver(_ovSchedule);
    if(document.fonts&&document.fonts.ready)document.fonts.ready.then(_ovRun);else _ovRun();
  }
  function stopOv(){
    if(_ovObs)_ovObs.disconnect();clearTimeout(_ovTimer);
    document.querySelectorAll('.sk-ovmark').forEach(x=>x.remove());ovBadge.style.display='none';
  }
  bar.querySelector('#seEdit').addEventListener('click',function(){if(editing)startOv();else stopOv();});
  window.addEventListener('resize',()=>{if(editing)_ovSchedule();});

  // ---- insert（配置モード：種類選択→波線プレビュー追従→クリック確定→ペースト/ドロップ/ダブルクリックで中身）----
  function mkImg(src){const img=document.createElement('img');img.src=src;img.style.cssText='width:100%;height:100%;object-fit:contain';return img;}
  function insertImage(src,slide,x,y,w,h){w=w||320;h=h||200;const d=document.createElement('div');d.className='ins';d.setAttribute('data-x',x);d.setAttribute('data-y',y);d.setAttribute('data-w',w);d.setAttribute('data-h',h);d.setAttribute('data-inserted','1');d.setAttribute('data-border','1,#d4dde7');d.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px;overflow:hidden;border:1px solid #d4dde7;box-sizing:border-box';d.appendChild(mkImg(src));slide.appendChild(d);pushAdd(d);setSel([d]);return d;}
  // SVG（CadKitの線画・BezierKit・Illustratorの書き出しなど）は img にせず、そのまま絵として入れる（2026-10-14）。
  // img だとPPTXで図形にならず、BezierKitでも開けない。実行・外部参照につながるものは外してから入れる
  function sanitizeSvgText(text){
    let doc;try{doc=new DOMParser().parseFromString(String(text||''),'image/svg+xml');}catch(_){return null;}
    const sv=doc.documentElement;if(!sv||sv.tagName.toLowerCase()!=='svg'||doc.querySelector('parsererror'))return null;
    sv.querySelectorAll('script,foreignObject,iframe,object,embed,audio,video').forEach(n=>n.remove());
    sv.querySelectorAll('style').forEach(s=>{if(/@import|url\s*\(\s*["']?(?!#)/i.test(s.textContent||''))s.remove();});
    [sv,...sv.querySelectorAll('*')].forEach(n=>[...n.attributes].forEach(a=>{const v=a.value||'';
      if(/^on/i.test(a.name))n.removeAttribute(a.name);
      else if(/^(?:href|xlink:href)$/i.test(a.name)&&!/^#/.test(v)&&!/^data:image\/(png|jpe?g|gif|webp);/i.test(v))n.removeAttribute(a.name);
      else if(/url\s*\(\s*["']?(?!#)/i.test(v))n.removeAttribute(a.name);}));
    return sv;}
  function insertSvgText(text,slide,x,y){
    const sv=sanitizeSvgText(text);if(!sv){flashSaved('SVGとして読めなかった');return null;}
    const vb=sv.viewBox&&sv.viewBox.baseVal;let w=vb&&vb.width||parseFloat(sv.getAttribute('width'))||640,h=vb&&vb.height||parseFloat(sv.getAttribute('height'))||420;
    if(!(vb&&vb.width))sv.setAttribute('viewBox','0 0 '+w+' '+h);
    const sc=Math.min(640/w,420/h,1);w=Math.max(60,Math.round(w*sc));h=Math.max(40,Math.round(h*sc));
    const nx=Math.max(0,Math.min(x,1280-w)),ny=Math.max(0,Math.min(y,720-h));
    ['width','height','style','class'].forEach(k=>sv.removeAttribute(k));
    sv.setAttribute('width','100%');sv.setAttribute('height','100%');sv.setAttribute('style','display:block');
    const d=document.createElement('div');
    d.setAttribute('data-x',nx);d.setAttribute('data-y',ny);d.setAttribute('data-w',w);d.setAttribute('data-h',h);d.setAttribute('data-inserted','1');
    d.style.cssText='position:absolute;left:'+nx+'px;top:'+ny+'px;width:'+w+'px;height:'+h+'px';
    d.appendChild(document.importNode(sv,true));slide.appendChild(d);pushAdd(d);setSel([d]);
    flashSaved('SVGを絵として入れました（PPTXで図形になる・「BezierKitで編集」で直せる）');return d;}
  const isSvgFile=f=>!!f&&(f.type==='image/svg+xml'||/\.svg$/i.test(f.name||''));
  // 画像の実寸を読んでコンテナをアス比に合わせて挿入（枠と画像のアス比が違うとPPTX変換で歪むため）
  function insertImageFit(src,slide,x,y){
    const im=new Image();
    im.onload=function(){
      const MAXW=640,MAXH=420;
      let w=im.naturalWidth||MAXW,h=im.naturalHeight||MAXH;
      const sc=Math.min(MAXW/w,MAXH/h,1);
      w=Math.max(60,Math.round(w*sc));h=Math.max(40,Math.round(h*sc));
      // 挿入位置がスライドからはみ出すなら内側に寄せる
      const nx=Math.max(0,Math.min(x,1280-w)),ny=Math.max(0,Math.min(y,720-h));
      insertImage(src,slide,nx,ny,w,h);
    };
    im.onerror=function(){insertImage(src,slide,x,y);};
    im.src=src;
  }
  function insertTable(slide,x,y){x=x||160;y=y||220;const w=520;const t=document.createElement('table');t.className='ins';t.setAttribute('data-x',x);t.setAttribute('data-y',y);t.setAttribute('data-w',w);t.setAttribute('data-inserted','1');t.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;border-collapse:collapse;font-size:18px';t.innerHTML='<tr><th style="background:#162a42;color:#fafafa;padding:9px 14px;text-align:left;border:1px solid #162a42">見出し1</th><th style="background:#162a42;color:#fafafa;padding:9px 14px;text-align:left;border:1px solid #162a42">見出し2</th></tr><tr><td style="padding:9px 14px;border:1px solid #d7dde3;color:#121212">項目</td><td style="padding:9px 14px;border:1px solid #d7dde3;color:#121212">値</td></tr>';slide.appendChild(t);pushAdd(t);setSel([t]);return t;}
  // 新規テキストボックス（配置→即編集）
  function insertTextBox(slide,x,y){const w=360,h=48,fs=24;const d=document.createElement('div');d.className='tb';[['data-x',x],['data-y',y],['data-w',w],['data-h',h],['data-font-size',fs],['data-color','#121212']].forEach(kv=>d.setAttribute(kv[0],kv[1]));d.setAttribute('data-inserted','1');d.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px;font-size:'+fs+'px;color:#121212;line-height:1.5';d.textContent='テキスト';slide.appendChild(d);pushAdd(d);setSel([d]);return d;}
  function startEditTb(el){el.contentEditable='true';el.focus();try{const r=document.createRange();r.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(r);}catch(_){}el.addEventListener('blur',()=>{el.contentEditable='false';},{once:true});}

  // プレゼン中メモ。rect内のtbにすることで、HTML保存後もPPTX上で編集可能な図形として残す。
  // 5枚ずつ少しずらして重ね、次の束は左へ送る。追加された最新メモが常に最前面になる。
  function insertStickyNote(slide,opts){
    opts=opts||{};
    if(!slide||!slide.classList||!slide.classList.contains('slide'))slide=targetSlide();
    if(!slide)return null;
    if(!editing){const eb=bar.querySelector('#seEdit');if(eb)eb.click();}
    const count=slide.querySelectorAll(':scope > [data-note="1"]').length;
    const stack=count%5,batch=Math.floor(count/5)%3,w=300,h=150;
    const defaultX=900-(batch*320)+(stack*18),defaultY=460+(stack*18);
    const nx=Number(opts.x),ny=Number(opts.y);
    const x=Math.max(0,Math.min(1280-w,Number.isFinite(nx)?nx:defaultX));
    const y=Math.max(0,Math.min(720-h,Number.isFinite(ny)?ny:defaultY));
    const note=document.createElement('div');
    note.className='rect';
    [['data-x',x],['data-y',y],['data-w',w],['data-h',h],['data-fill','#f4f4ef'],['data-note','1']].forEach(kv=>note.setAttribute(kv[0],kv[1]));
    note.setAttribute('data-inserted','1');
    note.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px;background:#f4f4ef;display:flex;flex-direction:column;justify-content:flex-start;overflow:hidden;box-sizing:border-box';
    const text=document.createElement('div');
    text.className='tb';
    [['data-font-size','20'],['data-color','#121212'],['data-align','left']].forEach(kv=>text.setAttribute(kv[0],kv[1]));
    text.style.cssText='position:static;left:auto;top:auto;width:auto;height:auto;padding:14px 16px;overflow:visible;font-size:20px;font-weight:400;color:#121212;text-align:left;line-height:1.45;white-space:pre-wrap';
    text.textContent=typeof opts.text==='string'?opts.text:'メモを入力';
    note.appendChild(text);slide.appendChild(note);pushAdd(note);setSel([note]);startEditTb(text);return note;
  }
  // slide-present.js など外部ツールから呼ぶ正規窓口。
  window.SlideKit.addStickyNote=function(slide,opts){try{return insertStickyNote(slide,opts);}catch(e){console.warn('SlideKit: メモ追加失敗',e);return null;}};
  // 選択中オブジェクトを複製（少しずらして配置）
  function dupSelected(){if(!sels.length){alert('複製するオブジェクトを選択してください');return;}const clones=[];sels.forEach(el=>{const c=el.cloneNode(true);if(c.style){c.style.outline='';c.style.outlineOffset='';}if(c.removeAttribute){c.removeAttribute('contenteditable');c.removeAttribute('data-role');}if(c.querySelectorAll)c.querySelectorAll('[contenteditable]').forEach(x=>x.removeAttribute('contenteditable'));const nx=N(A(el,'data-x'))+20,ny=N(A(el,'data-y'))+20;c.setAttribute('data-x',nx);c.setAttribute('data-y',ny);if(c.style){c.style.left=nx+'px';c.style.top=ny+'px';}c.setAttribute('data-inserted','1');el.parentNode.appendChild(c);pushAdd(c);clones.push(c);});setSel(clones);}

  // ---- 要素（オブジェクト）コピー＆ペースト：選んだ要素を別ページの「同じ位置」に貼る ----
  function flashPageBadge(msg){if(typeof pageBadge==='undefined')return;pageBadge.style.display='block';pageBadge.style.background='#1a5a32';pageBadge.textContent=msg;setTimeout(()=>{pageBadge.style.background='#e8821a';pageBadge.textContent='📄 このページを選択中';if(!(pageSel&&pageSel.isConnected))pageBadge.style.display='none';},1600);}
  // 「📋 貼付」ボタン用の控え。file:// では clipboard.readText() が使えないので内部にも持つ
  let lastCopyPayload='';
  // 選択要素をクリップボードへ（data-x/y入りのouterHTMLをマーカー付きで保存）。cut時は元を削除。
  function copyEls(cut){
    const movable=sels.filter(el=>el.matches&&el.matches(SEL)); // data-xを持つ要素のみ（同位置で貼れる）
    if(!movable.length)return false;
    const payload=movable.map(el=>{const c=el.cloneNode(true);if(c.style){c.style.outline='';c.style.outlineOffset='';}if(c.removeAttribute){c.removeAttribute('contenteditable');c.removeAttribute('data-role');}if(c.querySelectorAll)c.querySelectorAll('[contenteditable]').forEach(x=>x.removeAttribute('contenteditable'));return c.outerHTML;}).join('\n<!--EL-->\n');
    lastCopyPayload='<!--SKIT-ELS-->\n'+payload;
    copyText(lastCopyPayload,null);
    flashPageBadge(cut?'✂️ 図形を切り取り（「📋 貼付」か⌘Vで同じ位置に）':'📋 図形をコピー（「📋 貼付」か⌘Vで同じ位置に）');
    if(cut){sels.slice().forEach(el=>{pushDel(el);el.remove();});clearSel();}
    return true;
  }
  // クリップボード文字列の種別（要素/ページ）で振り分けてペースト。
  function pasteFromText(text){
    if(!text)return;
    if(text.indexOf('<!--SKIT-ELS-->')===0){
      const parts=text.slice('<!--SKIT-ELS-->'.length).split('<!--EL-->');
      const slide=pageTarget();if(!slide)return;
      const added=[];
      parts.forEach(h=>{h=h.trim();if(!h)return;const tmp=document.createElement('div');tmp.innerHTML=h;const el=tmp.firstElementChild;if(!el)return;if(el.style){el.style.outline='';el.style.outlineOffset='';}el.setAttribute('data-inserted','1');slide.appendChild(el);pushAdd(el);added.push(el);});
      if(added.length){setSel(added);flashPageBadge('📋 同じ位置にペーストしました（'+added.length+'件）');}
      return;
    }
    if(text.indexOf('<!--SKIT-PAGE-->')===0){
      const html=text.slice('<!--SKIT-PAGE-->'.length).trim();
      const tmp=document.createElement('div');tmp.innerHTML=html;const newSlide=tmp.querySelector('.slide');if(!newSlide)return;
      newSlide.style.outline='';newSlide.style.outlineOffset='';
      const after=pageSel&&pageSel.isConnected?pageSel:currentSlide();
      if(after&&after.parentNode)after.parentNode.insertBefore(newSlide,after.nextSibling);else document.body.appendChild(newSlide);
      pushAdd(newSlide);afterStruct(newSlide);rebuildThumbs();selectPage(newSlide);
      flashPageBadge('📋 ページをペーストしました');
      return;
    }
  }
  // ---- グラフの貼り付け（DashboardKit「Excelからグラフ」の「SlideKitのグラフをコピー」・2026-10-14）----
  //   利用者「DashboardKitのグラフをコピペでSlideKitに持ってこれたりするのかな」
  //   貼れるのは data-chart（SPEC 5.7）の JSON。HTMLは DOMParser で読むだけ（実行しない）、
  //   要素はこちらで作り直して JSON の中身も型を確かめる＝クリップボードの属性やスクリプトを持ち込まない
  const CHART_TYPES={column:1,bar:1,stacked:1,line:1,pie:1,table:1,sankey:1};
  // グラフの見せ方ボタン（slidekit-chart.js）を編集中に押したとき: undo に積んでから type を書き換える
  const CHART_TYPE_NAME={column:'縦棒',bar:'横棒',stacked:'積み上げ',line:'折れ線',pie:'円',table:'表',sankey:'サンキー',
    'map-circle':'地図（円）','map-bar':'地図（棒）','map-fill':'地図（塗り分け）',
    'area-circle':'地図（半径の円）','area-voronoi':'地図（最寄りの範囲）','area-none':'地図（点）'};
  window.addEventListener('skit:chart-type',function(e){
    const d=e.detail||{},el=d.el;if(!editing||!el||!el.isConnected||!CHART_TYPE_NAME[d.type])return;
    let c;try{c=JSON.parse(el.getAttribute('data-chart'));}catch(_){return;}
    // 地図の見せ方は type:map ＋ mark（県の値）／ type:map ＋ areas（拠点の範囲）
    const isMap=d.type.indexOf('map-')===0,isArea=d.type.indexOf('area-')===0;
    const ptsOnly=Array.isArray(c.points)&&!c.values&&!Array.isArray(c.series);
    const cur=c.type!=='map'?c.type:ptsOnly?'area-'+(c.areas||'circle'):'map-'+(c.mark||'circle');
    if(cur===d.type){e.preventDefault();return;}
    e.preventDefault();
    pushAttr([el]);
    if(isMap){c.type='map';c.mark=d.type.slice(4);}else if(isArea){c.type='map';c.areas=d.type.slice(5);}else c.type=d.type;
    el.setAttribute('data-chart',JSON.stringify(c));
    const s=el.closest('.slide');
    pageLog.push('グラフ：「'+(s?slideTitleOf(s):'')+'」のグラフを'+CHART_TYPE_NAME[d.type]+'にした');
    flashPageBadge('📊 '+CHART_TYPE_NAME[d.type]+'にしました（保存するとPPTXもこの形・⌘Zで戻せます）');
  });
  function chartSpecFromText(txt){
    const t=(txt||'').trim().replace(/^<!--SKIT-CHART-->\s*/,'');
    let spec=null,box=null;
    if(/^</.test(t)&&/data-chart\s*=/.test(t)){
      const d=new DOMParser().parseFromString(t,'text/html').querySelector('[data-chart]');
      if(!d)return null;
      try{spec=JSON.parse(d.getAttribute('data-chart'));}catch(_){return null;}
      box=['data-x','data-y','data-w','data-h','data-font-size'].map(k=>N(d.getAttribute(k)));
    }else if(/^\{[\s\S]*"(categories|links|map|points)"[\s\S]*\}$/.test(t)){
      try{spec=JSON.parse(t);}catch(_){return null;}
    }
    // 地図: 地図の名前・印・値（県名→数）だけを、型を確かめて作り直す
    if(spec&&(spec.type==='map'||spec.map||Array.isArray(spec.points))&&(spec.values||Array.isArray(spec.series)||Array.isArray(spec.points))){
      const fin=v=>typeof v==='number'&&isFinite(v);
      const vals=o=>{const r={};Object.keys(o||{}).slice(0,200).forEach(k=>{if(fin(o[k]))r[String(k).slice(0,20)]=o[k];});return r;};
      const pts=Array.isArray(spec.points)?spec.points.slice(0,300).filter(p=>p&&fin(p.lat)&&fin(p.lon)&&Math.abs(p.lat)<=90&&Math.abs(p.lon)<=180):[];
      const clean={type:spec.type==='table'?'table':'map'};
      if(/^[a-z0-9-]+$/.test(spec.map||''))clean.map=spec.map;else if(!pts.length)clean.map='japan-pref';
      if(spec.values||Array.isArray(spec.series)||!pts.length)clean.mark=['circle','bar','fill'].indexOf(spec.mark)>=0?spec.mark:'circle';
      if(typeof spec.title==='string'&&spec.title)clean.title=spec.title.slice(0,120);
      if(typeof spec.unit==='string'&&spec.unit)clean.unit=spec.unit.slice(0,12);
      if(Array.isArray(spec.series))clean.series=spec.series.slice(0,6).map(s=>({name:String((s&&s.name)||'').slice(0,40),values:vals(s&&s.values)}));
      else if(spec.values||!pts.length)clean.values=vals(spec.values);
      // 拠点（店など）と、その範囲（商圏）: 緯度経度・半径km・寄せる範囲（2026-10-15）
      if(pts.length){
        clean.points=pts.map(p=>{const r={name:String(p.name==null?'':p.name).slice(0,40),lat:p.lat,lon:p.lon};if(fin(p.value))r.value=p.value;return r;});
        if(['circle','voronoi','none'].indexOf(spec.areas)>=0)clean.areas=spec.areas;
        if(Array.isArray(spec.radius_km)){const rk=spec.radius_km.filter(v=>fin(v)&&v>0&&v<=300).slice(0,3);if(rk.length)clean.radius_km=rk;}
        if(Array.isArray(spec.bbox)&&spec.bbox.length===4&&spec.bbox.every(fin))clean.bbox=spec.bbox.slice();
        if(typeof spec.pointLabel==='string'&&spec.pointLabel)clean.pointLabel=spec.pointLabel.slice(0,20);
        if(typeof spec.pointUnit==='string'&&spec.pointUnit)clean.pointUnit=spec.pointUnit.slice(0,12);
      }
      return {spec:clean,box:box};
    }
    // サンキー（流れ）: nodes と links だけを、型を確かめて作り直す
    if(spec&&Array.isArray(spec.nodes)&&Array.isArray(spec.links)){
      const fin=v=>typeof v==='number'&&isFinite(v);
      const nodes=spec.nodes.slice(0,60).filter(n=>n&&n.id!=null).map(n=>({id:String(n.id).slice(0,40),label:String(n.label==null?n.id:n.label).slice(0,40)}));
      const ids=new Set(nodes.map(n=>n.id));
      const links=spec.links.slice(0,200).filter(l=>l&&ids.has(String(l.from))&&ids.has(String(l.to))&&fin(l.value)&&l.value>0)
        .map(l=>({from:String(l.from),to:String(l.to),value:l.value}));
      if(!nodes.length||!links.length)return null;
      const clean={type:spec.type==='table'?'table':'sankey',nodes,links};
      if(typeof spec.title==='string'&&spec.title)clean.title=spec.title.slice(0,120);
      if(typeof spec.unit==='string'&&spec.unit)clean.unit=spec.unit.slice(0,12);
      if(Array.isArray(spec.colors)){const cs=spec.colors.filter(isHex).slice(0,12);if(cs.length)clean.colors=cs;}
      return {spec:clean,box:box};
    }
    if(!spec||!CHART_TYPES[spec.type]||!Array.isArray(spec.categories)||!Array.isArray(spec.series)||!spec.series.length)return null;
    const clean={type:spec.type};
    if(typeof spec.title==='string'&&spec.title)clean.title=spec.title.slice(0,120);
    if(typeof spec.unit==='string'&&spec.unit)clean.unit=spec.unit.slice(0,12);
    if(spec.labels===false)clean.labels=false;
    if(spec.legend===false)clean.legend=false;
    if(Array.isArray(spec.colors)){const cs=spec.colors.filter(isHex).slice(0,12);if(cs.length)clean.colors=cs;}
    clean.categories=spec.categories.slice(0,400).map(c=>String(c==null?'':c).slice(0,60));
    const fin=v=>typeof v==='number'&&isFinite(v);
    clean.series=spec.series.slice(0,12).map(s=>{const r={name:String((s&&s.name)||'').slice(0,60),
      values:clean.categories.map((_,i)=>{const v=s&&Array.isArray(s.values)?s.values[i]:null;return fin(v)?v:null;})};if(s&&s.dash===true)r.dash=true;return r;});
    // 軸をデータに合わせる・上限・目標線（DashboardKit の fitY / max / target・2026-10-14）
    if(spec.fitY===true)clean.fitY=true;
    if(spec.timeAxis===true)clean.timeAxis=true;
    if(spec.smooth===true)clean.smooth=true;
    if(spec.area===true)clean.area=true;
    clean.series.forEach((r,j)=>{const s=spec.series[j];if(s&&s.area===false)r.area=false;});
    if(Array.isArray(spec.bands)){const BT={danger:1,accent:1,warn:1,ok:1,sub:1};const bs=spec.bands.slice(0,20).filter(b=>b&&b.from!=null).map(b=>{
      const r={from:String(b.from).slice(0,40),to:String(b.to==null?b.from:b.to).slice(0,40)};
      if(typeof b.label==='string'&&b.label)r.label=b.label.slice(0,30);
      if(typeof b.color==='string'&&(BT[b.color]||/^#[0-9a-fA-F]{6}$/.test(b.color)))r.color=b.color;
      if(fin(b.opacity)&&b.opacity>0&&b.opacity<=1)r.opacity=b.opacity;return r;});if(bs.length)clean.bands=bs;}
    if(spec.weekendBand===true)clean.weekendBand=true;
    if(fin(spec.max))clean.max=spec.max;
    if(spec.target&&fin(spec.target.value)){clean.target={value:spec.target.value};if(typeof spec.target.label==='string'&&spec.target.label)clean.target.label=spec.target.label.slice(0,40);}
    return {spec:clean,box:box};
  }
  function ensureChartLib(el){
    if(window.SlideKitChart){window.SlideKitChart.render(el);return;}
    if(document.querySelector('script[src*="slidekit-chart"]'))return; // 読み込み中＝読み終わりに全部描く
    const me=document.querySelector('script[src*="slide-edit"]');
    const c=document.createElement('script');c.className='seui';
    c.src=(me?(me.getAttribute('src')||'').replace(/slide-edit\.js.*$/,''):'')+'slidekit-chart.js';
    document.head.appendChild(c);
  }
  // 置き場所: 選んでいるグラフ依頼の枠（data-ask="chart"）→ 選んでいる枠 → 画面中央のページの本文域
  function pasteChart(found){
    const z=(sels.length===1&&sels[0].classList.contains('inszone'))?sels[0]:((activeZone&&activeZone.isConnected)?activeZone:null);
    let s,x,y,w,h;
    const b=found.box||[];
    if(z){s=z.closest('.slide');x=N(A(z,'data-x'));y=N(A(z,'data-y'));w=N(A(z,'data-w'));h=N(A(z,'data-h'));}
    else{s=targetSlide();x=b[0]||64;y=b[1]||170;w=b[2]||1152;h=b[3]||440;}
    if(!s)return;
    const sw=s.offsetWidth||1280,sh=s.offsetHeight||720;
    w=Math.max(160,Math.min(w,sw));h=Math.max(120,Math.min(h,sh));x=Math.max(0,Math.min(x,sw-w));y=Math.max(0,Math.min(y,sh-h));
    const fs=Math.max(15,Math.min(b[4]||16,24));
    const el=document.createElement('div');
    [['data-x',x],['data-y',y],['data-w',w],['data-h',h],['data-font-size',fs]].forEach(kv=>el.setAttribute(kv[0],String(Math.round(kv[1]))));
    el.setAttribute('data-chart',JSON.stringify(found.spec));
    el.style.cssText='position:absolute;left:'+Math.round(x)+'px;top:'+Math.round(y)+'px;width:'+Math.round(w)+'px;height:'+Math.round(h)+'px';
    if(z){pushDel(z);z.remove();if(activeZone===z)activeZone=null;}
    el.setAttribute('data-inserted','1');
    s.appendChild(el);pushAdd(el);setSel([el]);
    ensureChartLib(el);
    pageLog.push('グラフ：「'+slideTitleOf(s)+'」に'+(found.spec.title?'「'+found.spec.title+'」の':'')+'グラフを貼り付け'+(z?'（依頼の枠と置き換え）':''));
    flashPageBadge(z?'📊 依頼の枠をグラフに置き換えました（⌘Zを2回で枠に戻せます）':'📊 グラフを貼り付けました（PPTXでもPowerPointのグラフになります）');
  }
  // 「📋 貼付」ボタン: 直前に copyEls / ページコピーで控えたものを貼る。
  // 無ければクリップボードを読む（http(s)のみ・file://は失敗するので案内を出す）
  function pasteEls(){
    if(lastCopyPayload){pasteFromText(lastCopyPayload);return;}
    const guide='貼り付けるものがありません。図形を選んで「📋 コピー」（または⌘C）してから押してください。';
    if(navigator.clipboard&&navigator.clipboard.readText){
      navigator.clipboard.readText().then(t=>{
        if(t&&(t.indexOf('<!--SKIT-ELS-->')===0||t.indexOf('<!--SKIT-PAGE-->')===0))pasteFromText(t);
        else if(chartSpecFromText(t))pasteChart(chartSpecFromText(t));
        else alert(guide);
      },()=>alert(guide+'\n（クリップボードを読めない環境では⌘Vで貼り付けてください）'));
      return;
    }
    alert(guide);
  }
  // 選択物の削除（Deleteキーと🎯パネルの「🗑 削除」で共用）。表のセル範囲選択時は中身だけ消す
  function delSelected(){
    if(!sels.length)return false;
    if(cellSel.length){pushAttr(sels.slice());cellSel.forEach(c=>{c.textContent='';});return true;}
    let any=false;
    sels.slice().forEach(el=>{pushDel(el);el.remove();any=true;});
    if(any){sels=sels.filter(el=>el.isConnected);clearSel();}
    return any;
  }
  const TH='background:#162a42;color:#fafafa;padding:9px 14px;text-align:left;border:1px solid #162a42';
  const TD='padding:9px 14px;border:1px solid #d7dde3;color:#121212';
  function tblAddRow(t){
    pushAttr([t]);
    const cols=t.rows[0]?t.rows[0].cells.length:2;
    // 模範行: 最後のtd行（ヘッダ以外）。無ければ最終行そのもの
    let model=null;
    for(let i=t.rows.length-1;i>=0;i--){if(t.rows[i].cells[0]&&t.rows[i].cells[0].tagName==='TD'){model=t.rows[i];break;}}
    if(!model&&t.rows.length)model=t.rows[t.rows.length-1];
    const tr=t.insertRow(-1);
    for(let i=0;i<cols;i++){
      const td=tr.insertCell(-1);
      const src=model&&model.cells[i];
      td.style.cssText=src?src.style.cssText:TD;
      td.textContent='';
    }
  }
  function tblDelRow(t){
    // セル範囲選択がある場合はその行（複数可）を削除、無ければ最後の行
    if(cellSel.length&&cellTable===t){
      const rowIdx=new Set();cellSel.forEach(c=>{const p=cellPos(t,c);if(p)rowIdx.add(p.r);});
      const sorted=Array.from(rowIdx).sort((a,b)=>b-a);
      if(t.rows.length-sorted.length<1){alert('全行は削除できない');return;}
      pushAttr([t]);sorted.forEach(i=>t.deleteRow(i));cellSelClear();
    }else if(t.rows.length>1){pushAttr([t]);t.deleteRow(-1);}
  }
  function tblAddCol(t){
    pushAttr([t]);
    for(let i=0;i<t.rows.length;i++){
      const r=t.rows[i];
      const isH=r.cells[0]&&r.cells[0].tagName==='TH';
      // 同じ行の最後のセルを模範にしてスタイル継承（無ければ最初のセル or 既定TH/TD）
      const model=r.cells[r.cells.length-1]||r.cells[0];
      const c=document.createElement(isH?'th':'td');
      c.style.cssText=model?model.style.cssText:(isH?TH:TD);
      c.textContent='';
      r.appendChild(c);
    }
  }
  function tblDelCol(t){
    // セル範囲選択がある場合はその列（複数可）を削除、無ければ最後の列
    if(cellSel.length&&cellTable===t){
      const colIdx=new Set();cellSel.forEach(c=>{const p=cellPos(t,c);if(p)colIdx.add(p.c);});
      const sorted=Array.from(colIdx).sort((a,b)=>b-a);
      const cols=t.rows[0]?t.rows[0].cells.length:0;
      if(cols-sorted.length<1){alert('全列は削除できない');return;}
      pushAttr([t]);for(let i=0;i<t.rows.length;i++){sorted.forEach(c=>{if(t.rows[i].cells[c])t.rows[i].deleteCell(c);});}cellSelClear();
    }else{const c0=t.rows[0]?t.rows[0].cells.length:0;if(c0>1){pushAttr([t]);for(let i=0;i<t.rows.length;i++){if(t.rows[i].cells.length)t.rows[i].deleteCell(-1);}}}
  }
  function tblRowH(t,delta){
    pushAttr([t]);
    let cells;
    if(cellSel.length&&cellTable===t){
      // 選択セルが含まれる行の全セルを対象
      const rowIdx=new Set();cellSel.forEach(c=>{const p=cellPos(t,c);if(p)rowIdx.add(p.r);});
      cells=[];rowIdx.forEach(r=>{Array.from(t.rows[r].cells).forEach(c=>cells.push(c));});
    }else{
      cells=Array.from(t.querySelectorAll('td,th'));
    }
    cells.forEach(c=>{
      const cur=parseFloat(getComputedStyle(c).paddingTop)||9;
      const nv=Math.max(2,cur+delta);
      c.style.paddingTop=nv+'px';
      c.style.paddingBottom=nv+'px';
    });
  }
  function esc(v){return (v==null?'':String(v)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function buildGrid(grid,slide,x,y){const cols=Math.max.apply(null,grid.map(r=>r.length));const w=Math.min(1152,Math.max(240,cols*170));const t=document.createElement('table');t.className='ins';t.setAttribute('data-x',x);t.setAttribute('data-y',y);t.setAttribute('data-w',w);t.setAttribute('data-inserted','1');t.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;border-collapse:collapse;font-size:18px';let html='';grid.forEach((row,ri)=>{html+='<tr>';for(let ci=0;ci<cols;ci++){html+=ri===0?('<th style="'+TH+'">'+esc(row[ci])+'</th>'):('<td style="'+TD+'">'+esc(row[ci])+'</td>');}html+='</tr>';});t.innerHTML=html;slide.appendChild(t);pushAdd(t);setSel([t]);return t;}
  function createZone(slide,x,y,w,h){const d=document.createElement('div');d.className='ins inszone';d.setAttribute('data-x',x);d.setAttribute('data-y',y);d.setAttribute('data-w',w);d.setAttribute('data-h',h);d.setAttribute('data-inserted','1');d.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px;border:2px dashed #e8821a;background:rgba(232,130,26,.06);display:flex;align-items:center;justify-content:center;color:#e8821a;font-size:15px;text-align:center;overflow:hidden;padding:8px';d.textContent='📎 ⌘Vで貼り付け / 画像をドロップ / ダブルクリックで選択';slide.appendChild(d);pushAdd(d);setSel([d]);return d;}
  // 画像が入った枠は依頼の枠ではなくなる。依頼文の1行目（伝えたいこと）は画像の代替テキストに残す
  function fillZone(zone,src){if(zone.hasAttribute('data-ask')){const t=(zone.innerText||zone.textContent||'').split('\n').map(s=>s.trim()).find(s=>/^伝えたいこと/.test(s));if(t)zone.setAttribute('data-alt',t.replace(/^伝えたいこと[:：]\s*/,''));zone.removeAttribute('data-ask');}zone.classList.remove('inszone');zone.style.background='';zone.style.display='';zone.style.color='';zone.style.padding='';zone.style.overflow='hidden';zone.style.border='1px solid #d4dde7';zone.style.boxSizing='border-box';zone.setAttribute('data-border','1,#d4dde7');zone.textContent='';zone.appendChild(mkImg(src));}
  function ptToSlide(e){const t=document.elementFromPoint(e.clientX,e.clientY);let s=t?t.closest('.slide'):null;if(!s)s=targetSlide();const r=s.getBoundingClientRect();return {slide:s,x:Math.max(0,Math.round(e.clientX-r.left)),y:Math.max(0,Math.round(e.clientY-r.top))};}
  function startPlacing(type){if(!editing){alert('「✏️ 編集」をONにしてください');return;}placing=type;document.body.style.cursor='crosshair';if(!ghost){ghost=document.createElement('div');ghost.className='seui';ghost.style.cssText='position:fixed;border:2px dashed #e8821a;background:rgba(232,130,26,.08);pointer-events:none;z-index:99999;display:none';document.body.appendChild(ghost);}ghost.style.width=(type==='table'?520:320)+'px';ghost.style.height=(type==='table'?120:200)+'px';ghost.style.display='block';}
  function moveGhost(e){if(ghost){ghost.style.left=e.clientX+'px';ghost.style.top=e.clientY+'px';}}
  function endPlacing(){placing=null;document.body.style.cursor='';if(ghost)ghost.style.display='none';}
  bar.querySelector('#seImg').onclick=()=>startPlacing('image');
  bar.querySelector('#seTbl').onclick=()=>startPlacing('table');
  bar.querySelector('#seText').onclick=()=>startPlacing('text');
  bar.querySelector('#seDup').onclick=dupSelected;
  bar.querySelector('#sePaste').onclick=pasteEls;

  // 図形サブメニュー（折りたたみ）
  const shapeMenu=document.createElement('div');shapeMenu.className='seui';
  shapeMenu.style.cssText='display:none;flex-direction:column;gap:3px;background:transparent;padding:3px 0 3px 12px;border-radius:0;box-shadow:none';
  shapeMenu.innerHTML='<button data-sk="rect">□ 四角</button><button data-sk="rrect">▢ 角丸四角</button><button data-sk="circle">● 丸</button><button data-sk="triangle">▲ 三角</button><button data-sk="line">─ 線</button><button data-sk="arrow">→ 矢印</button><button data-sk="chevron">▷ 帯矢印（期間）</button><button data-sk="callout">💬 吹き出し</button>';
  Array.from(shapeMenu.querySelectorAll('button')).forEach(b=>b.style.cssText='padding:5px 10px;border:none;border-radius:3px;background:#3a3a3a;color:#fff;font-size:12px;cursor:pointer;text-align:left');
  bar.querySelector('#seShape').insertAdjacentElement('afterend',shapeMenu);
  function setShapeOpen(open){shapeMenu.style.display=open?'flex':'none';const b=bar.querySelector('#seShape');if(b)b.style.background=open?'#2a2a2a':'rgba(74,74,74,.95)';}
  bar.querySelector('#seShape').onclick=function(e){e.stopPropagation();setShapeOpen(shapeMenu.style.display!=='flex');};
  shapeMenu.addEventListener('click',e=>{const b=e.target.closest('button[data-sk]');if(!b)return;startPlacing('shape:'+b.dataset.sk);setShapeOpen(false);});
  document.addEventListener('mousedown',e=>{if(shapeMenu.style.display==='flex'&&!shapeMenu.contains(e.target)&&e.target!==bar.querySelector('#seShape'))setShapeOpen(false);});

  function insertShape(kind,slide,x,y){
    let w=220,h=140,fill='#edf2f4',extra='',shape='';
    if(kind==='rrect'){extra='border-radius:12px;';}
    else if(kind==='circle'){shape='circle';extra='border-radius:50%;';}
    else if(kind==='triangle'){shape='triangle';extra='clip-path:polygon(50% 0,0 100%,100% 100%);';}
    else if(kind==='line'){shape='line';fill='#5e5e5e';w=240;h=4;}
    else if(kind==='arrow'){shape='arrow';fill='#5e5e5e';w=240;h=44;}
    else if(kind==='chevron'){shape='chevron';w=200;h=56;}
    else if(kind==='callout'){shape='callout';w=260;h=120;fill='#fafafa';}
    // 四角(rect)はそのまま角丸なし
    const d=document.createElement('div');d.className='rect ins';
    d.setAttribute('data-x',x);d.setAttribute('data-y',y);d.setAttribute('data-w',w);d.setAttribute('data-h',h);d.setAttribute('data-fill',fill);d.setAttribute('data-inserted','1');
    if(kind==='rrect')d.setAttribute('data-radius','12');
    if(shape)d.setAttribute('data-shape',shape);
    d.style.cssText='position:absolute;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px;background:'+fill+';justify-content:center;align-items:center;'+extra;
    if(kind==='arrow'){d.setAttribute('data-ah',String(SHP_AH.def));d.setAttribute('data-at',String(SHP_AT.def));applyArrowShape(d);}
    if(kind==='chevron'){d.setAttribute('data-cv',String(SHP_CV.def));applyChevronShape(d);}
    if(kind==='callout'){d.setAttribute('data-bx',String(SHP_BX.def));d.setAttribute('data-border','1,#718096');applyCalloutShape(d);}
    slide.appendChild(d);pushAdd(d);setSel([d]);return d;
  }
  fileInput.onchange=function(){const f=this.files[0];this.value='';if(!f)return;const rd=new FileReader();rd.onload=()=>{if(pendingZone&&pendingZone.isConnected){fillZone(pendingZone,rd.result);pendingZone=null;}else insertImage(rd.result,targetSlide(),400,250);};rd.readAsDataURL(f);};

  // ---- mouse ----
  document.addEventListener('mousedown',function(e){
    if(!editing)return;
    if(placing){const p=ptToSlide(e);if(placing==='table')insertTable(p.slide,p.x,p.y);else if(placing==='text'){const d=insertTextBox(p.slide,p.x,p.y);endPlacing();startEditTb(d);e.preventDefault();e.stopPropagation();return;}else if(placing.startsWith('shape:'))insertShape(placing.slice(6),p.slide,p.x,p.y);else activeZone=createZone(p.slide,p.x,p.y,320,200);endPlacing();e.preventDefault();e.stopPropagation();return;}
    // スライド上を触り始めたら、パネルの入力欄のフォーカスを外す（Deleteが効かない原因を潰す）
    // 編集中の枠の外をクリックしたときは、文字編集も終了して選択のハイライトを消す
    if(e.target&&e.target.closest&&e.target.closest('.slide')){
      blurPanelInput();
      if(!e.target.closest('[contenteditable="true"]'))exitTextEdit();
    }
    // 早期解除: スライドの外(かつSlideKit UI以外)をクリックしたら即座に選択解除
    // (marquee 経由の mouseup を待たず・contenteditable の tb がフォーカス残ってても確実に解除)
    if(e.target && e.target.closest && !e.target.closest('.slide') && !e.target.closest('.seui')){
      if(sels.length)clearSel();
      if(pageSel && pageSel.isConnected)clearPageSel();
      // contenteditable の tb をフォーカス外す＋文字選択のハイライトも消す
      exitTextEdit();
    }
    // 文字枠の「端」(12px以内)をつかんだら移動モード（中央はダブルクリックで文字編集）。
    // ノード内(rect の子) data-x 無しの子tbは選択対象外にする（SlideKit標準仕様）
    // → 子tbを切り出そうとすると親rectの flex 配置で他の子が動いて崩れる（クチャッと重なる）
    // Shift押下時は複数選択トグルを優先させるため、この分岐に入らない。
    {let tbEdge=e.target.closest&&e.target.closest('.tb');
     if(tbEdge&&nearEdge(tbEdge,e)&&!e.shiftKey){
       if(tbEdge.isContentEditable){tbEdge.contentEditable='false';try{window.getSelection().removeAllRanges();}catch(_){}}
       // data-x を持たない子tb は無視（親rectを丸ごと選ぶ運用に）
       if(!tbEdge.hasAttribute('data-x'))tbEdge=null;
       if(tbEdge&&tbEdge.matches&&tbEdge.matches(SEL)){
         clearPageSel();
         if(!sels.includes(tbEdge))setSel([tbEdge]);else placeBox();
         act='move';sx=e.clientX;sy=e.clientY;const grp=addCompanions(addLinkedChildren(e.altKey?sels.slice():expandLinked(sels)));pushAttr(grp);bases=grp.map(s=>({el:s,x:N(A(s,'data-x')),y:N(A(s,'data-y'))}));e.preventDefault();return;
       }
     }}
    // テキスト編集中（contentEditable）はブラウザのネイティブ選択に任せる（ドラッグで文字選択・削除できるように）
    if(e.target.closest&&e.target.closest('[contenteditable="true"]'))return;
    if(e.target===rotHandle&&sels.length===1){
      act='rotate';const el0=sels[0];pushAttr([el0]);
      const rr=el0.getBoundingClientRect();rotCx=rr.left+rr.width/2;rotCy=rr.top+rr.height/2; // 要素中心を軸に
      rotBase=N(A(el0,'data-rotate'))||0;
      rotStart=Math.atan2(e.clientY-rotCy,e.clientX-rotCx)*180/Math.PI;
      document.body.style.cursor=ROT_CUR; // ハンドルから外れても↻カーソルを維持
      e.preventDefault();return;}
    if(e.target.dataset&&e.target.dataset.rz&&sels.length){act='resize';rzSide=e.target.dataset.rz;sx=e.clientX;sy=e.clientY;const role=sels.length===1?roleOf(sels[0]):null;const grp=(role&&!e.altKey)?expandLinked(sels):sels.slice();rzMode=(sels.length>1)?'group':'delta';
      // data-hが無い要素に現在の高さを付与（リサイズ可能にする）
      grp.forEach(el=>{if(!el.hasAttribute('data-h')){const ch=el.getBoundingClientRect().height||40;el.setAttribute('data-h',Math.round(ch));el.style.height=Math.round(ch)+'px';}});
      pushAttr(grp);bases=grp.map(el=>({el,x:N(A(el,'data-x')),y:N(A(el,'data-y')),w:N(A(el,'data-w'))||el.getBoundingClientRect().width,h:N(A(el,'data-h')),fs:N(A(el,'data-font-size'))}));if(rzMode==='group')g0=groupData();e.preventDefault();return;}
    // 表が選択済みのとき：セル境界付近=列幅/行高ドラッグ、内側=セル範囲選択
    {const cell=e.target.closest&&e.target.closest('td,th');if(cell){const t=cell.closest('table');if(t&&sels.includes(t)){
      const q=cell.getBoundingClientRect();
      if(Math.abs(e.clientX-q.right)<=5){act='colresize';colT=t;colIdx=cell.cellIndex;colBaseW=q.width;sx=e.clientX;pushAttr([t]);e.preventDefault();return;}
      if(Math.abs(e.clientY-q.bottom)<=5){act='rowresize';rowTr=cell.parentNode;rowBaseH=rowTr.getBoundingClientRect().height;sy=e.clientY;pushAttr([t]);e.preventDefault();return;}
      // Shift+クリック＝既存アンカーから矩形範囲を拡張（ドラッグと同じ結果をクリック2回で作れる）
      if(e.shiftKey&&cellAnchor&&cellTable===t){const p=cellPos(t,cell);if(p){cellSelSet(cellsInRange(t,cellAnchor,p));e.preventDefault();return;}}
      act='cellsel';cellTable=t;cellAnchor=cellPos(t,cell);if(cellAnchor)cellSelSet(cellsInRange(t,cellAnchor,cellAnchor));e.preventDefault();return;
    }}}
    // ノード内テキスト（自前data-x無し・.rectノードの中）をクリック＝そのテキストを選択（ノードは動かさない）。
    // 余白はノード端からの距離(inset)で表示・編集する。Alt+クリックは従来の分離に回す。
    // Shift押下時は複数選択トグルを優先させるため、この分岐に入らない。
    {const tbN=e.target.closest&&e.target.closest('.tb');const nodeN=tbN?inNodeText(tbN):null;
     if(tbN&&nodeN&&!e.altKey&&!e.shiftKey){
       if(tbN.isContentEditable){return;} // 編集中はネイティブ操作に任せる
       clearPageSel();
       // rect 内子tb をクリック → 親rect を選択して動かす（台座ごと移動）
       // テキストだけ動かしたい時は Alt(Option)+クリックで分離（既存の Alt 分岐に流す）
       const host = tbN.closest('.rect[data-x]') || tbN;
       if(!sels.includes(host))setSel([host]);
       act='move';sx=e.clientX;sy=e.clientY;
       const grp=addCompanions(addLinkedChildren(expandLinked([host])));
       pushAttr(grp);bases=grp.map(s=>({el:s,x:N(A(s,'data-x')),y:N(A(s,'data-y'))}));
       e.preventDefault();return;
     }}
    let el=e.target.closest(SEL);
    // Alt+クリック：親rect内のdata-x無し.tbをスライド直下に分離して独立選択可能化（親子リンクは維持）
    if(el&&e.altKey&&el.classList&&el.classList.contains('rect')){
      const inner=e.target.closest&&e.target.closest('.tb');
      if(inner&&inner!==el&&!inner.hasAttribute('data-x')&&el.contains(inner)){
        const slide=el.closest('.slide');
        if(slide){
          pushAttr([inner]);
          const sr=slide.getBoundingClientRect();
          const r=inner.getBoundingClientRect();
          const ix=Math.round(r.left-sr.left),iy=Math.round(r.top-sr.top),iw=Math.round(r.width),ih=Math.round(r.height);
          inner.setAttribute('data-x',ix);inner.setAttribute('data-y',iy);
          inner.setAttribute('data-w',iw);inner.setAttribute('data-h',ih);
          setStyleProp(inner,'position','absolute');setStyleProp(inner,'left',ix+'px');setStyleProp(inner,'top',iy+'px');setStyleProp(inner,'width',iw+'px');setStyleProp(inner,'height',ih+'px');
          // 親子リンク維持：親に内部ID付与・子にdata-linked-parentを記録
          const pid=ensureSkid(el);
          inner.setAttribute('data-linked-parent',pid);
          slide.appendChild(inner);
          el=inner;
        }
      }
    }
    if(el){
      // imgが直接選ばれた場合、親divが絶対配置なら親divを選択対象にする(画像エリア全体を動かす)
      if(el.tagName==='IMG'){
        const parent=el.parentElement;
        if(parent && parent.tagName==='DIV' && getComputedStyle(parent).position==='absolute'){
          if(!parent.hasAttribute('data-x')){
            const slide=parent.closest('.slide');
            if(slide){
              const sr=slide.getBoundingClientRect();
              const er=parent.getBoundingClientRect();
              parent.setAttribute('data-x',Math.round(er.left-sr.left));
              parent.setAttribute('data-y',Math.round(er.top-sr.top));
              if(!parent.hasAttribute('data-w'))parent.setAttribute('data-w',Math.round(er.width));
              if(!parent.hasAttribute('data-h'))parent.setAttribute('data-h',Math.round(er.height));
            }
          }
          el=parent;
        } else {
          // 親が絶対配置でない場合(レアケース)はimg自身のリサイズに留める
          const r=el.getBoundingClientRect();
          if(!el.hasAttribute('data-w'))el.setAttribute('data-w',Math.round(r.width));
          if(!el.hasAttribute('data-h'))el.setAttribute('data-h',Math.round(r.height));
        }
      }
      clearPageSel();
      // テキスト編集モード中：要素の枠(端12px以内)をつかむと移動、中身をつかむとテキスト範囲選択
      // → PowerPoint と同じ感覚。要素「自身」が contenteditable=true のときのみ発動
      //   (親からの継承 isContentEditable は含めない=通常のクリック/Shift+クリック/ドラッグを邪魔しない)
      if(el.getAttribute&&el.getAttribute('contenteditable')==='true'){
        if(!nearEdge(el,e))return; // 中身 → ブラウザの範囲選択に任せる
        // 枠 → 編集モードを一旦解除して通常の移動処理へ落とす
        try{el.blur();el.contentEditable='false';}catch(_){}
      }
      if(e.shiftKey){toggleSel(el);e.preventDefault();return;}
      if(!sels.includes(el))setSel([el]);
      act='move';sx=e.clientX;sy=e.clientY;const grp=addCompanions(addLinkedChildren(e.altKey?sels.slice():expandLinked(sels)));pushAttr(grp);bases=grp.map(s=>({el:s,x:N(A(s,'data-x')),y:N(A(s,'data-y'))}));e.preventDefault();
    } else if(!bar.contains(e.target)&&!(e.target.dataset&&e.target.dataset.rz)){
      // 空白部分：ドラッグでラバーバンド選択を開始（小さな動きならクリック＝ページ選択）
      act='marquee';sx=e.clientX;sy=e.clientY;marqMoved=false;
      marq.style.display='block';marq.style.left=sx+'px';marq.style.top=sy+'px';marq.style.width='0px';marq.style.height='0px';
      e.preventDefault();
    }
  });
  // ---- スマートガイド（ドラッグ中、他要素の端/中央・スライド中央に吸着＋マゼンタ線）----
  const snapV=document.createElement('div');snapV.className='seui skit-live';snapV.style.cssText='position:absolute;width:0;border-left:1px dashed #d81690;display:none;z-index:99997;pointer-events:none';
  const snapH=document.createElement('div');snapH.className='seui skit-live';snapH.style.cssText='position:absolute;height:0;border-top:1px dashed #d81690;display:none;z-index:99997;pointer-events:none';
  document.body.appendChild(snapV);document.body.appendChild(snapH);
  function hideSnapG(){snapV.style.display='none';snapH.style.display='none';}
  const SNAP_TH=5; // 吸着距離(px)
  function snapMove(dx,dy){
    const out={dx,dy,vx:null,hy:null,slide:null};
    if(!bases.length)return out;
    const slide=bases[0].el.closest('.slide');if(!slide)return out;
    out.slide=slide;
    // 移動中グループのbbox（スライド座標・移動量込み）
    let l=1e9,t=1e9,r=-1e9,b=-1e9;
    bases.forEach(bb=>{const w=bb.w||bb.el.getBoundingClientRect().width,h=bb.h||bb.el.getBoundingClientRect().height;
      l=Math.min(l,bb.x+dx);t=Math.min(t,bb.y+dy);r=Math.max(r,bb.x+dx+w);b=Math.max(b,bb.y+dy+h);});
    // 吸着候補: スライドの端/中央 ＋ 同スライド内の他要素の端/中央
    const selSet=new Set(bases.map(bb=>bb.el));
    const xs=[0,640,1280],ys=[0,360,720];
    slide.querySelectorAll('[data-x]').forEach(el=>{
      if(selSet.has(el)||(el.classList&&el.classList.contains('seui')))return;
      const x=N(A(el,'data-x')),y=N(A(el,'data-y')),w=N(A(el,'data-w'))||el.getBoundingClientRect().width,h=N(A(el,'data-h'))||el.getBoundingClientRect().height;
      xs.push(x,x+w/2,x+w);ys.push(y,y+h/2,y+h);});
    // グループの左/中央/右・上/中央/下と候補の最短差分を探す
    let bxd=SNAP_TH+1,bestX=null;[l,(l+r)/2,r].forEach(g=>xs.forEach(c=>{const d=c-g;if(Math.abs(d)<Math.abs(bxd)){bxd=d;bestX=c;}}));
    let byd=SNAP_TH+1,bestY=null;[t,(t+b)/2,b].forEach(g=>ys.forEach(c=>{const d=c-g;if(Math.abs(d)<Math.abs(byd)){byd=d;bestY=c;}}));
    if(bestX!=null&&Math.abs(bxd)<=SNAP_TH){out.dx=dx+bxd;out.vx=bestX;}
    if(bestY!=null&&Math.abs(byd)<=SNAP_TH){out.dy=dy+byd;out.hy=bestY;}
    return out;
  }
  function showSnapG(sn){
    if(!sn.slide){hideSnapG();return;}
    const sr=sn.slide.getBoundingClientRect();
    if(sn.vx!=null){snapV.style.display='block';snapV.style.left=(sr.left+window.scrollX+sn.vx)+'px';snapV.style.top=(sr.top+window.scrollY)+'px';snapV.style.height=sr.height+'px';}
    else snapV.style.display='none';
    if(sn.hy!=null){snapH.style.display='block';snapH.style.top=(sr.top+window.scrollY+sn.hy)+'px';snapH.style.left=(sr.left+window.scrollX)+'px';snapH.style.width=sr.width+'px';}
    else snapH.style.display='none';
  }

  document.addEventListener('mousemove',function(e){
    if(placing){moveGhost(e);return;}
    if(!act){ // ホバー時：選択中の表のセル境界でカーソルを列/行リサイズに
      const cell=e.target&&e.target.closest&&e.target.closest('td,th');
      if(cell&&editing){const t=cell.closest('table');if(t&&sels.includes(t)){const q=cell.getBoundingClientRect();if(Math.abs(e.clientX-q.right)<=5)document.body.style.cursor='col-resize';else if(Math.abs(e.clientY-q.bottom)<=5)document.body.style.cursor='row-resize';else document.body.style.cursor='';return;}}
      if(document.body.style.cursor==='col-resize'||document.body.style.cursor==='row-resize')document.body.style.cursor='';
      // 文字枠の端にホバー中は「移動」カーソル（端つかみ＝移動の合図・ノード内文字でも）。
      {const hoverTb=e.target&&e.target.closest&&e.target.closest('.tb');
       if(editing&&hoverTb&&nearEdge(hoverTb,e)){document.body.style.cursor='move';}
       else if(document.body.style.cursor==='move')document.body.style.cursor='';}
      return;
    }
    if(act==='colresize'){let w=colBaseW+(e.clientX-sx);if(!e.altKey)w=Math.round(w/8)*8;setColWidth(colT,colIdx,w);placeBox();return;}
    if(act==='rowresize'){let h=rowBaseH+(e.clientY-sy);if(!e.altKey)h=Math.round(h/4)*4;setRowHeight(rowTr,h);placeBox();return;}
    if(act==='marquee'){const r=marqRect(e);marq.style.left=r.l+'px';marq.style.top=r.t+'px';marq.style.width=(r.r-r.l)+'px';marq.style.height=(r.b-r.t)+'px';if(Math.abs(e.clientX-sx)>4||Math.abs(e.clientY-sy)>4)marqMoved=true;return;}
    if(act==='cellsel'){const el2=document.elementFromPoint(e.clientX,e.clientY);const cell=el2&&el2.closest&&el2.closest('td,th');if(cell&&cell.closest('table')===cellTable&&cellAnchor){const p=cellPos(cellTable,cell);if(p)cellSelSet(cellsInRange(cellTable,cellAnchor,p));}return;}
    if(!act||!sels.length)return;
    if(act==='rotate'){
      const ang=Math.atan2(e.clientY-rotCy,e.clientX-rotCx)*180/Math.PI;
      let nd=rotBase+(ang-rotStart);
      if(e.shiftKey)nd=Math.round(nd/15)*15; // Shift＝15°刻み
      else{const q=Math.round(nd/90)*90;if(Math.abs(nd-q)<=3)nd=q;} // 0/90/180/270近傍は吸着
      setRot(sels[0],nd);placeBox();return;
    }
    let dx=e.clientX-sx,dy=e.clientY-sy;
    // Shift+ドラッグで水平/垂直ロック（移動の時だけ・変位の大きい方を採用）
    if(act==='move'&&e.shiftKey){
      if(Math.abs(dx)>=Math.abs(dy))dy=0;else dx=0;
    }
    if(act==='move'){
      // Alt押下でスナップ無効（微調整用）。Shiftロック中は動かない軸への吸着をしない
      let sn={dx,dy,vx:null,hy:null,slide:null};
      if(!e.altKey){
        sn=snapMove(dx,dy);
        if(e.shiftKey){if(dy===0){sn.dy=0;sn.hy=null;}if(dx===0){sn.dx=0;sn.vx=null;}}
      }
      bases.forEach(b=>{setX(b.el,b.x+sn.dx);setY(b.el,b.y+sn.dy);});
      showSnapG(sn);
    }
    else{ // resize
      const L=rzSide.indexOf('l')>=0,R=rzSide.indexOf('r')>=0,T=rzSide.indexOf('t')>=0,B=rzSide.indexOf('b')>=0;
      const corner=(L||R)&&(T||B);
      if(rzMode==='group'){
        const fx=Math.max(0.2,(g0.w+(L?-dx:dx))/g0.w);
        const fy=Math.max(0.2,(g0.h+(T?-dy:dy))/g0.h);
        const ax=L?g0.x+g0.w:g0.x,ay=T?g0.y+g0.h:g0.y; // 掴んだ側の反対の辺を固定
        if(corner){const f=fx;bases.forEach(b=>{setX(b.el,ax+(b.x-ax)*f);setY(b.el,ay+(b.y-ay)*f);setW(b.el,b.w*f);if(b.h)setH(b.el,b.h*f);if(b.fs)setFS(b.el,b.fs*f);});}
        else if(L||R){bases.forEach(b=>{setX(b.el,ax+(b.x-ax)*fx);setW(b.el,b.w*fx);});}
        else{bases.forEach(b=>{setY(b.el,ay+(b.y-ay)*fy);if(b.h)setH(b.el,b.h*fy);});}
      }
      else{bases.forEach(b=>{
        const isCircle=A(b.el,'data-shape')==='circle';
        const h0=b.h||40;
        // Shift+角＝ドラッグ開始時の縦横比を維持（画像が歪まない・SPEC 7.2）。円は常に正円
        const keepAspect=corner&&(e.shiftKey||isCircle);
        let nw=b.w,nh=h0;
        if(keepAspect){
          const ddx=L?-dx:dx,ddy=T?-dy:dy; // 外向きに広げる方向を正に揃える
          if(isCircle){const nv=Math.max(20,Math.max(b.w,h0)+(Math.abs(dx)>=Math.abs(dy)?ddx:ddy));nw=nv;nh=nv;}
          else{
            const ratio=b.w/Math.max(1,h0); // 変位の大きい軸を基準に他方を追従
            if(Math.abs(dx)>=Math.abs(dy)){nw=Math.max(20,b.w+ddx);nh=Math.max(16,nw/ratio);}
            else{nh=Math.max(16,h0+ddy);nw=Math.max(20,nh*ratio);}
          }
          setW(b.el,nw);setH(b.el,nh);
        }else{
          if(R)nw=Math.max(20,b.w+dx);
          if(L)nw=Math.max(20,b.w-dx);
          if(B)nh=Math.max(16,h0+dy);
          if(T)nh=Math.max(16,h0-dy);
          if(L||R)setW(b.el,nw);
          if(T||B)setH(b.el,nh);
        }
        // 上・左から掴んだ時は反対側の辺を固定（位置も動かす）
        if(L)setX(b.el,b.x+(b.w-nw));
        if(T)setY(b.el,b.y+(h0-nh));
      });}
    }
    placeBox();
  });
  document.addEventListener('mouseup',function(e){
    if(act==='cellsel'){act=null;return;}
    if(act==='colresize'||act==='rowresize'){act=null;document.body.style.cursor='';placeBox();return;}
    if(act==='marquee'){marq.style.display='none';if(marqMoved){selectInMarquee(marqRect(e));}else{clearSel();const sl=e.target.closest&&e.target.closest('.slide');if(sl)selectPage(sl);else clearPageSel();}act=null;return;}
    if(act==='rotate')document.body.style.cursor='';
    act=null;placeBox();hideSnapG();
  });

  // ---- text edit (.tb / 表セル) ----
  document.addEventListener('dblclick',function(e){
    if(!editing)return;
    const zone=e.target.closest('.inszone');if(zone){pendingZone=zone;fileInput.click();return;}
    // 画像をダブルクリック＝トリミング（クロップ）モード開始（✂️ボタンと同じ）
    {const im=e.target.closest&&e.target.closest('.slide img');
     if(im){const p=im.parentElement;const host=(p&&p.tagName==='DIV'&&getComputedStyle(p).position==='absolute')?p:im;setSel([host]);enterCropMode(im);e.preventDefault();return;}}
    const el=e.target.closest('.tb,td,th');if(!el)return;
    const owner=el.closest(SEL)||el;pushAttr([owner.classList&&owner.matches&&owner.matches(SEL)?owner:el]);
    el.contentEditable='true';el.focus();
    // カーソルをクリック位置に置く（先頭固定を防ぐ）
    try{
      const range=document.caretRangeFromPoint(e.clientX,e.clientY);
      if(range){const sel2=window.getSelection();sel2.removeAllRanges();sel2.addRange(range);}
    }catch(_){}
    el.addEventListener('blur',()=>{el.contentEditable='false';clearTextSel();},{once:true});
  });

  // ---- keyboard ----
  document.addEventListener('keydown',function(e){
    // ⌘Z: Undo / ⌘Shift+Z, ⌘Y: Redo
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!e.shiftKey){e.preventDefault();doUndo();return;}
    if((e.metaKey||e.ctrlKey)&&((e.key.toLowerCase()==='z'&&e.shiftKey)||e.key.toLowerCase()==='y')){e.preventDefault();doRedo();return;}
    if(e.key==='Escape'&&placing){endPlacing();return;}
    if(e.key==='Escape'&&painterSrc){painterExit();return;}
    // Escape: 文字編集を抜ける（選択のハイライトも消す）。何も編集していなければ選択解除
    if(e.key==='Escape'&&editing){
      if(exitTextEdit()){e.preventDefault();return;}
      if(sels.length){clearSel();e.preventDefault();return;}
    }
    // 要素を選んでいない時は、上下左右キーでページを送る（2026-09-16 利用者要望）
    //   要素選択中は従来どおり「選んだ図形を動かす」。両方を同じキーに割り当てても衝突しない
    //   プレゼン再生中は scrollIntoView が効かない（1枚だけ表示している）ので
    //   window.SlidePresent.show() で表示を切り替える
    if(editing&&!sels.length&&!isInputFocused()&&!e.metaKey&&!e.ctrlKey&&!e.altKey&&
       ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(e.key)){
      const slides=allSlides();if(!slides.length)return;
      const live=window.SlidePresent&&document.body.classList.contains('_sp_active')?window.SlidePresent:null;
      let idx=live?live.index()
              :slides.indexOf(pageSel&&slides.indexOf(pageSel)>=0?pageSel:currentSlide());
      if(e.key==='Home')idx=0;
      else if(e.key==='End')idx=slides.length-1;
      else if(e.key==='ArrowRight'||e.key==='ArrowDown'||e.key==='PageDown')idx=Math.min(idx+1,slides.length-1);
      else idx=Math.max(idx-1,0);
      const t=slides[idx];
      clearSel();
      if(live){live.show(idx);}                       // 再生中＝表示を切り替える
      else{t.scrollIntoView({behavior:'smooth',block:'center'});}
      selectPage(t);
      if(thumbsPane&&thumbsPane.style.display!=='none'){
        const btns=thumbsPane.querySelectorAll('.skit-thumb');
        btns.forEach((b,i)=>b.classList.toggle('cur',i===idx));
        if(btns[idx])btns[idx].scrollIntoView({block:'nearest'});
      }
      e.preventDefault();return;
    }
    if(!editing||!sels.length)return;
    // 入力欄にフォーカスが残っていてDeleteが効かない時は、黙って無反応にせず理由を出す（2026-09-08）
    if((e.key==='Delete'||e.key==='Backspace')&&isInputFocused()){
      const ae=document.activeElement;
      if(ae&&ae.closest&&ae.closest('.seui')&&typeof flashSaved==='function')
        flashSaved('入力欄にカーソルがあります。図形をクリックし直してDelete、または「🗑 削除」で消せます');
    }
    // input/textarea/contentEditable にフォーカス中はショートカットで要素を消さない
    if(isInputFocused())return;
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='c'){copyText(refTextOf(sels),null);e.preventDefault();return;} // 選択オブジェクトの内容＋IDをコピー
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='d'){e.preventDefault();dupSelected();return;} // ⌘D=複製（イラレ/PowerPointと同じ）
    if(e.key==='Delete'||e.key==='Backspace'){if(delSelected())e.preventDefault();return;}
    // レイヤー順ショートカット: Cmd+]/[ = 1つ前面/背面, Cmd+Shift+]/[ = 最前面/最背面
    if((e.metaKey||e.ctrlKey)&&(e.key===']'||e.key==='[')){
      const slide=sels[0].closest('.slide');if(!slide){e.preventDefault();return;}
      pushOrder(slide);
      let changed=false;
      if(e.key===']')changed=e.shiftKey?bringToFront(sels):bringForward(sels);
      else changed=e.shiftKey?sendToBack(sels):sendBackward(sels);
      if(!changed){undo.pop();}else{
        const opName=e.key===']'?(e.shiftKey?'最前面':'前面に1つ'):(e.shiftKey?'最背面':'背面に1つ');
        const slideNum=allSlides().indexOf(slide)+1;
        const targets=layerTargets(slide);
        sels.forEach(el=>{const idx=targets.indexOf(el);if(idx>=0)layerLog.push({slide:slideNum,eidx:idx+1,op:opName});});
        placeBox();
      }
      e.preventDefault();return;
    }
    if(e.key===']'||e.key==='['){const step=(e.key===']'?1:-1)*(e.shiftKey?4:1);const grp=e.altKey?sels.slice():expandLinked(sels);const tbs=grp.filter(el=>el.classList&&el.classList.contains('tb'));if(tbs.length){if(undo.length===0||undo[undo.length-1].type!=='attr')pushAttr(grp);tbs.forEach(el=>setFS(el,N(A(el,'data-font-size'))+step));placeBox();}e.preventDefault();return;}
    const d=e.shiftKey?10:1;let h=true;const grp=addCompanions(e.altKey?sels.slice():expandLinked(sels));
    if(e.key==='ArrowLeft')grp.forEach(el=>setX(el,N(A(el,'data-x'))-d));
    else if(e.key==='ArrowRight')grp.forEach(el=>setX(el,N(A(el,'data-x'))+d));
    else if(e.key==='ArrowUp')grp.forEach(el=>setY(el,N(A(el,'data-y'))-d));
    else if(e.key==='ArrowDown')grp.forEach(el=>setY(el,N(A(el,'data-y'))+d));
    else h=false;
    if(h){if(undo.length===0||undo[undo.length-1].type!=='attr')pushAttr(grp);e.preventDefault();placeBox();}
  });
  window.addEventListener('scroll',placeBox);window.addEventListener('resize',placeBox);

  // ---- image drop / paste ----
  document.addEventListener('dragover',e=>{if(editing&&e.dataTransfer&&e.dataTransfer.types.includes('Files'))e.preventDefault();});
  document.addEventListener('drop',function(e){
    if(!editing)return;const f=e.dataTransfer&&e.dataTransfer.files[0];if(!f||!(f.type.startsWith('image/')||isSvgFile(f)))return;e.preventDefault();
    const zone=e.target.closest&&e.target.closest('.inszone');
    if(isSvgFile(f)){const rd=new FileReader();rd.onload=()=>{const p=zone?{slide:zone.closest('.slide'),x:N(A(zone,'data-x')),y:N(A(zone,'data-y'))}:ptToSlide(e);
      const d=insertSvgText(rd.result,p.slide,zone?p.x:Math.max(0,p.x-160),zone?p.y:Math.max(0,p.y-100));if(d&&zone){zone.remove();if(zone===activeZone)activeZone=null;}};rd.readAsText(f);return;}
    const rd=new FileReader();rd.onload=()=>{if(zone){fillZone(zone,rd.result);if(zone===activeZone)activeZone=null;}else{const p=ptToSlide(e);insertImageFit(rd.result,p.slide,Math.max(0,p.x-160),Math.max(0,p.y-100));}};rd.readAsDataURL(f);
  });
  document.addEventListener('paste',function(e){
    if(!editing)return;
    // テキスト入力中（contentEditable/INPUT/TEXTAREA）は通常ペーストに任せる
    // e.target と activeElement の両方で判定（focus 遷移中の瞬間でも取りこぼさない）
    const tgt=e.target;
    if(tgt&&tgt.matches&&tgt.matches('input,textarea')){return;}
    const ceHost=tgt&&tgt.closest&&tgt.closest('[contenteditable="true"]');
    if(ceHost){
      // Word・Webからの書式付き貼り付けは文字だけにする（2026-09-27）。
      // そのまま入ると class="MsoNormal"・font・span style が残り、変換前ガードが「許可外クラス」で止まる
      const cd=e.clipboardData;
      if(cd&&ceHost.closest('.slide')&&(cd.types||[]).indexOf('text/html')>=0){
        e.preventDefault();
        document.execCommand('insertText',false,(cd.getData('text/plain')||'').replace(/\r/g,''));
      }
      return;
    }
    const ae=document.activeElement;
    if(ae&&(ae.isContentEditable||ae.tagName==='INPUT'||ae.tagName==='TEXTAREA'))return;
    const items=(e.clipboardData&&e.clipboardData.items)||[];let f=null;for(let i=0;i<items.length;i++){if(items[i].type&&items[i].type.indexOf('image/')===0){f=items[i].getAsFile();break;}}
    // SVGの文字（CadKit・BezierKitの「CadKit用コピー」など）やSVGファイルの貼り付け＝絵として入れる
    const svgTxt0=(e.clipboardData&&e.clipboardData.getData('text/plain'))||'';
    if((f&&isSvgFile(f))||/^\s*(?:<\?xml[^>]*>\s*)?(?:<!--[\s\S]*?-->\s*)*<svg[\s>]/i.test(svgTxt0)){
      e.preventDefault();const zone=(activeZone&&activeZone.isConnected)?activeZone:((sels[0]&&sels[0].classList.contains('inszone'))?sels[0]:null);
      const put=t=>{const s=zone?zone.closest('.slide'):targetSlide();const d=insertSvgText(t,s,zone?N(A(zone,'data-x')):320,zone?N(A(zone,'data-y')):160);if(d&&zone){zone.remove();activeZone=null;}};
      if(f&&isSvgFile(f)){const rd=new FileReader();rd.onload=()=>put(rd.result);rd.readAsText(f);}else put(svgTxt0);return;}
    if(f){e.preventDefault();const zone=(activeZone&&activeZone.isConnected)?activeZone:((sels[0]&&sels[0].classList.contains('inszone'))?sels[0]:null);const rd=new FileReader();rd.onload=()=>{if(zone){fillZone(zone,rd.result);activeZone=null;}else insertImageFit(rd.result,targetSlide(),320,160);};rd.readAsDataURL(f);return;}
    const txt=(e.clipboardData&&e.clipboardData.getData('text/plain'))||'';
    // SlideKit内部形式（要素/ページのコピー）は pasteFromText に振り分け
    if(txt.indexOf('<!--SKIT-ELS-->')===0||txt.indexOf('<!--SKIT-PAGE-->')===0){e.preventDefault();pasteFromText(txt);return;}
    // グラフ（data-chart）: DashboardKit「Excelからグラフ」でコピーしたもの・Kiroが書いた data-chart の div
    const chartFound=chartSpecFromText(txt);
    if(chartFound){e.preventDefault();pasteChart(chartFound);return;}
    const rows=txt.replace(/\r/g,'').replace(/\n$/,'').split('\n');
    if(txt&&(rows.length>1||txt.indexOf('\t')>=0)){
      e.preventDefault();const grid=rows.map(r=>r.split('\t'));
      const z=(activeZone&&activeZone.isConnected)?activeZone:null;let s,x,y;
      if(z){s=z.closest('.slide');x=N(A(z,'data-x'));y=N(A(z,'data-y'));z.remove();activeZone=null;}else{s=targetSlide();x=120;y=200;}
      buildGrid(grid,s,x,y);
    }
  });

  // ---- copy patch ----
  bar.querySelector('#seCopy').onclick=function(){
    const sl=allSlides(),lines=[],roleAgg={},RN={badge:'バッジ',title:'タイトル',subtitle:'サブタイトル',pageno:'ページ番号'};
    function sgn(v){return (v>=0?'+':'')+v;}
    const stripTags=h=>String(h||'').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim();
    function bulletLabel(v){
      if(v==='disc')return '・(ぶら下げ字下げ padding-left/text-indent)';
      if(v==='decimal')return '①(ぶら下げ字下げ)';
      if(v==='native-disc')return '・(PowerPoint形式 buChar＋.li[data-lvl])';
      if(v==='native-decimal')return '①(PowerPoint形式 buAutoNum＋.li[data-lvl])';
      return 'なし(字下げ解除)';
    }
    function deltaStr(o,n){const p=[];if(n.x!==o.x)p.push('data-x Δ'+sgn(n.x-o.x));if(n.y!==o.y)p.push('data-y Δ'+sgn(n.y-o.y));if(n.w!==o.w)p.push('data-w Δ'+sgn(n.w-o.w));if(n.h!==o.h)p.push('data-h Δ'+sgn(n.h-o.h));if(n.fs!==o.fs)p.push('font-size Δ'+sgn(n.fs-o.fs));if((n.bold||0)!==(o.bold||0))p.push('data-bold '+(n.bold?'→太字(700)':'→標準(400)'));if((n.bullet||'')!==(o.bullet||''))p.push('data-bullet →'+bulletLabel(n.bullet));if((n.lvls||'')!==(o.lvls||''))p.push('箇条書きレベル '+(o.lvls||'(なし)')+'→'+(n.lvls||'(なし)')+' (.li の data-lvl)');if(n.col&&o.col&&n.col!==o.col)p.push('data-color '+o.col+'→'+n.col);if(n.fill&&o.fill&&n.fill!==o.fill)p.push('data-fill '+o.fill+'→'+n.fill);EXATTRS.forEach(k=>{const ov=(o.extra||{})[k]||'',nv=(n.extra||{})[k]||'';if(ov!==nv)p.push(k+' '+(ov||'(なし)')+'→'+(nv||'(削除)'));});return p.join(' / ');}
    orig.forEach((o,el)=>{
      if(!el.isConnected||el.getAttribute('data-inserted')==='1')return;
      const n={x:N(A(el,'data-x')),y:N(A(el,'data-y')),w:N(A(el,'data-w')),h:N(A(el,'data-h')),fs:N(A(el,'data-font-size')),col:elTextHex(el),fill:elFillHex(el),bold:A(el,'data-bold')==='1'?1:0,bullet:A(el,'data-bullet')||'',lvls:liLvlsStr(el),extra:snapExtra(el)},t=el.innerHTML.trim();
      const O={x:o.x,y:o.y,w:o.w,h:o.h,fs:o.fs||0,col:o.col,fill:o.fill,bold:o.bold||0,bullet:o.bullet||'',lvls:o.lvls||'',extra:o.extra||{}};
      const extraChanged=EXATTRS.some(k=>(n.extra[k]||'')!==(O.extra[k]||''));
      const changed=(n.x!==O.x||n.y!==O.y||n.w!==O.w||n.h!==O.h||n.fs!==O.fs||n.col!==O.col||n.fill!==O.fill||n.bold!==O.bold||n.bullet!==O.bullet||n.lvls!==O.lvls||extraChanged),edited=(t!==txt0.get(el));
      if(!changed&&!edited)return;
      const role=roleOf(el);
      if(role&&changed&&!edited){const d={dx:n.x-O.x,dy:n.y-O.y,dw:n.w-O.w,dh:n.h-O.h,dfs:n.fs-O.fs,col:n.col,fill:n.fill,bold:n.bold,bullet:n.bullet};const a=roleAgg[role]||(roleAgg[role]={d,n:0,uniform:true,o:O,nv:n});if(a.d.dx!==d.dx||a.d.dy!==d.dy||a.d.dw!==d.dw||a.d.dh!==d.dh||a.d.dfs!==d.dfs||a.d.col!==d.col||a.d.fill!==d.fill||a.d.bold!==d.bold||a.d.bullet!==d.bullet)a.uniform=false;a.n++;a.o=O;a.nv=n;return;}
      const si=sl.indexOf(el.closest('.slide'))+1;
      const curText=stripTags((el.querySelector('.tb')||el).textContent)||'(無題)';
      const oldTextFull=stripTags(txt0.get(el));
      // 編集（テキスト変更）時は「旧テキスト」を見出しにする＝ファイル内のどこを書き換えたか特定できる。
      const idText=(edited?(oldTextFull||curText):curText).slice(0,24);
      const roleTag=role?('['+(RN[role]||role)+'] '):'';
      let s='[移動/編集] S'+si+' '+roleTag+el.className.split(' ')[0]+' 「'+idText+'」';
      if(changed)s+='\n  '+deltaStr(O,n);
      if(edited)s+='\n  旧text:「'+oldTextFull.slice(0,120)+'」\n  新text:「'+t+'」';
      lines.push(s);
    });
    Object.keys(roleAgg).forEach(k=>{const a=roleAgg[k],nm=RN[k]||k;if(a.uniform)lines.unshift('[共通] 全ページの'+nm+'（'+a.n+'枚）を一括変更：'+deltaStr(a.o,a.nv)+'（全スライドの'+nm+'に同じ変更）');else lines.unshift('[共通] '+nm+'（'+a.n+'枚）に不均一な変更あり（要確認）');});
    document.querySelectorAll('[data-inserted="1"]:not(.inszone)').forEach(el=>{
      const si=sl.indexOf(el.closest('.slide'))+1;
      const c=el.cloneNode(true);c.style.outline='';c.removeAttribute('data-inserted');c.removeAttribute('contenteditable');
      lines.push('[挿入] S'+si+' に追加：\n'+c.outerHTML);
    });
    // 削除：undoスタックのdelエントリで、いま文書につながっていない（＝削除されたまま）要素を報告する。
    // これで「枠ごと消した」がパッチに出る（元ファイルから該当ブロックを消すための情報）。
    const delSeen=new Set();
    undo.forEach(u=>{
      if(!u||u.type!=='del'||!u.el)return;
      const el=u.el;if(delSeen.has(el))return;delSeen.add(el);
      if(el.isConnected)return; // 復活済み（取り消された）はスキップ
      if(el.getAttribute&&el.getAttribute('data-inserted')==='1')return; // 挿入物の削除は元から無いので無視
      if(el.classList&&el.classList.contains('seui'))return;
      if(typeof isPageno==='function'&&isPageno(el))return;
      const par=u.parent;
      const sld=par?(par.matches&&par.matches('.slide')?par:(par.closest?par.closest('.slide'):null)):null;
      const si=(sld&&sld.isConnected)?allSlides().indexOf(sld)+1:'?';
      const txt=stripTags((el.querySelector&&el.querySelector('.tb')||el).textContent).slice(0,40)||'(無題)';
      const tag=el.className?el.className.split(' ')[0]:((el.tagName||'').toLowerCase());
      const pos=(A(el,'data-x')!=null)?(' (data-x='+A(el,'data-x')+',y='+A(el,'data-y')+')'):'';
      lines.push('[削除] S'+si+' '+tag+' 「'+txt+'」'+pos+' を枠ごと削除');
    });
    // 🎨パレットの色一括置換は orig に登録されない要素も書き換えるため、undoスタックを正本に集約（連鎖は最終色へ畳む）
    const cOrder=[],cNet={};
    undo.forEach(u=>{if(!u||u.type!=='color')return;const o=u.oldHex.toLowerCase(),n=u.newHex;let key=null;for(const k of cOrder){if((cNet[k]||'').toLowerCase()===o){key=k;break;}}if(key)cNet[key]=n;else{cOrder.push(o);cNet[o]=n;}});
    cOrder.forEach(k=>{if((cNet[k]||'').toLowerCase()!==k)lines.unshift('[色置換] 全スライドの '+k+' → '+cNet[k]+'（data-color / data-fill / style を一括置換）');});
    if(pageLog.length){const order=allSlides().map((s,i)=>(i+1)+'.'+slideTitleOf(s)).join(' / ');lines.unshift('[ページ構成変更] '+pageLog.length+'件：\n  '+pageLog.join('\n  ')+'\n  最終ページ順：'+order+'\n  ※ページの複製・追加・並べ替えは「💾保存」でHTMLを書き出すのが確実（パッチは微調整向け）');}
    if(layerLog.length){layerLog.forEach(function(entry){lines.unshift('[レイヤー順] S'+entry.slide+'#'+entry.eidx+' → '+entry.op);});}
    bgOrig.forEach((o,s)=>{if(!s.isConnected)return;const nb=A(s,'data-bg'),ng=A(s,'data-bg-gradient');if((nb||'')!==(o.bg||'')||(ng||'')!==(o.grad||'')){const si=allSlides().indexOf(s)+1;lines.unshift('[ページ背景] S'+si+' 「'+slideTitleOf(s)+'」→ data-bg '+(nb||'(なし)')+(o.grad&&!ng?'（グラデーション解除・単色化）':''));}});
    // 書き出しFontの切替もパッチに載せる（bodyは差分監視対象外のため個別報告）
    try{if(typeof curFont!=='undefined'&&typeof fontOrig!=='undefined'&&curFont!==fontOrig){lines.unshift('[書き出しFont] '+(FONTS[fontOrig]?FONTS[fontOrig].label:fontOrig)+' → '+(FONTS[curFont]?FONTS[curFont].label:curFont)+'（<body> style の font-family 先頭と <html data-font> を変更）');}}catch(_){}
    const out=lines.length?'=== スライド編集パッチ（Kiroに貼り付け）===\n'+lines.join('\n\n'):'変更はありません';
    function done(){alert('編集内容をKiroへ渡す文章をコピーしました（'+lines.length+'件）。Kiroに貼り付けてください。');}
    if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(out).then(done,fallback);else fallback();
    function fallback(){const ta=document.createElement('textarea');ta.value=out;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(_){}ta.remove();done();}
  };

  // ---- 保存（編集UIを除いたクリーンHTMLをダウンロード。画像入りや丸ごと差し替え向け）----
  function refTextOf(list){
    const out=['=== 選択オブジェクトの参照（Kiroに貼り付けて「これを表にして」等を指示）==='];
    list.forEach(el=>{
      const c=el.cloneNode(true);if(c.style){c.style.outline='';c.style.outlineOffset='';}c.removeAttribute&&c.removeAttribute('contenteditable');if(c.querySelectorAll)c.querySelectorAll('[contenteditable]').forEach(x=>x.removeAttribute('contenteditable'));
      const txt=el.textContent.trim().replace(/\s+/g,' ').slice(0,80);
      out.push('\n【'+eidStr(el)+'】 '+el.tagName.toLowerCase()+(el.className?'.'+el.className.split(' ')[0]:'')+'  （'+sidOf(el)+'枚目 / スライド内'+eidxOf(el)+'番目のdata-x要素）');
      out.push('data-x='+(A(el,'data-x')||'')+' data-y='+(A(el,'data-y')||'')+' data-w='+(A(el,'data-w')||'')+' data-h='+(A(el,'data-h')||''));
      if(txt)out.push('内容:「'+txt+'」');
      out.push('outerHTML:\n'+c.outerHTML);
    });
    return out.join('\n');
  }
  function copyText(text,msg){function done(){if(msg)alert(msg);}if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done,fb);else fb();function fb(){const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(_){}ta.remove();done();}}
  bar.querySelector('#seRef').onclick=function(){
    if(!sels.length){alert('オブジェクトを選択してください');return;}
    copyText(refTextOf(sels),'場所と内容をコピーしました（'+sels.length+'件）。Kiroに貼り付けて指示してください。');
  };

  // ---- IndexedDB でファイルハンドル永続化（File System Access API） ----
  // 一度「ワークスペースに直接保存」を選んだら、以降はブラウザを閉じても同じHTMLを開けば同じ保存先へ書き戻せる
  function idbOpen(){return new Promise((res,rej)=>{const req=indexedDB.open('slidekit-fs',1);req.onupgradeneeded=e=>e.target.result.createObjectStore('handles');req.onsuccess=e=>res(e.target.result);req.onerror=e=>rej(e);});}
  async function idbSet(k,v){const db=await idbOpen();return new Promise((res,rej)=>{const tx=db.transaction('handles','readwrite');tx.objectStore('handles').put(v,k);tx.oncomplete=()=>res();tx.onerror=e=>rej(e);});}
  async function idbGet(k){const db=await idbOpen();return new Promise((res,rej)=>{const tx=db.transaction('handles','readonly');const rq=tx.objectStore('handles').get(k);rq.onsuccess=()=>res(rq.result);rq.onerror=e=>rej(e);});}
  async function idbDel(k){const db=await idbOpen();return new Promise((res,rej)=>{const tx=db.transaction('handles','readwrite');tx.objectStore('handles').delete(k);tx.oncomplete=()=>res();tx.onerror=e=>rej(e);});}

  let saveHandle=null;
  const saveKey='handle:'+location.pathname;
  const canDirectSave='showSaveFilePicker' in window && location.protocol!=='file:';
  // 保存対応サーバー（SlideKit/serve.py）で開かれているかを OPTIONS で判定
  let hasPutServer=false;
  async function probePutServer(){
    try{
      const r=await fetch(location.pathname,{method:'OPTIONS'});
      const allow=(r.headers.get('Allow')||'')+' '+(r.headers.get('Access-Control-Allow-Methods')||'');
      hasPutServer=/PUT/i.test(allow) || r.headers.get('X-SlideKit-Server')==='1';
    }catch(_){hasPutServer=false;}
    updateSaveBtn();
  }
  if(location.protocol!=='file:')probePutServer();
  // 開いた時点のファイル更新時刻。保存前に比べ、開いた後に Kiro や別タブが書き換えていたら確認する（2026-09-27）
  // 🚫 以前は古い画面のまま保存すると、その間の変更を黙って上書きしていた（PJメモ 7/21 の巻き戻り）
  let knownMtime=null;
  async function fetchMtime(){
    try{const r=await fetch(location.pathname,{method:'HEAD',cache:'no-store'});return r.ok?r.headers.get('Last-Modified'):null;}catch(_){return null;}
  }
  if(location.protocol!=='file:')fetchMtime().then(m=>{knownMtime=m;});
  function confirmOverwrite(){
    return confirm('このファイルは開いた後に、別の場所（Kiro・別のタブなど）で書き換えられています。\n\n上書きすると、その変更は消えます。上書きしますか？\n（キャンセルして開き直すと最新の内容を読み込めます）');
  }
  // 起動時に保存済みハンドルを復元（permission確認はしない＝実際に保存する時までダイアログを出さない）
  if(canDirectSave){idbGet(saveKey).then(h=>{if(h)saveHandle=h;updateSaveBtn();}).catch(()=>{});}
  function updateSaveBtn(){
    const btn=bar.querySelector('#seSave');if(!btn)return;
    if(hasPutServer){btn.textContent='💾 保存';btn.title='ワークスペースの同じフォルダに直接書き戻します（SlideKit保存対応サーバー）';btn.style.background='#3a7a5a';}
    else if(saveHandle){btn.textContent='💾 上書き保存';btn.title='ワークスペースの元HTMLに直接上書き（'+(saveHandle.name||'')+'）';btn.style.background='#3a7a5a';}
    else{btn.textContent='💾 保存';btn.title=canDirectSave?'初回はワークスペースの元HTMLを選択（次回以降は直接上書き）':'ダウンロードで保存（お使いのブラウザは直接保存に非対応）';btn.style.background='rgba(74,74,74,.95)';}
  }

  async function saveViaPut(html){
    try{
      const url=location.pathname;
      const res=await fetch(url,{method:'PUT',headers:{'Content-Type':'text/html; charset=utf-8'},body:html});
      if(!res.ok)return false;
      return true;
    }catch(e){console.warn('PUT保存失敗:',e);return false;}
  }

  function buildCleanHTML(){
    const doc=document.documentElement.cloneNode(true);
    // 統一サニタイズ (mode:'save') — 剥がすリストは SlideKit.sanitizeSlide に集約
    // ページ番号は保持する = 保存された HTML を PPTX 変換した時に番号が入る
    window.SlideKit.sanitizeSlide(doc, 'save');
    // 編集モード中に保存しても編集状態がHTMLに焼き込まれないように剥がす
    const b=doc.querySelector('body');
    if(b){b.removeAttribute('data-skit-edit');b.style.cursor='';if(!b.getAttribute('style'))b.removeAttribute('style');}
    // 過去の保存で溜まった重複（同じ src の script・同じ中身の style）を1つにする（2026-09-27）
    const seenSrc=new Set(),seenCss=new Set();
    doc.querySelectorAll('script[src]').forEach(s=>{const k=s.getAttribute('src');if(seenSrc.has(k))s.remove();else seenSrc.add(k);});
    doc.querySelectorAll('style').forEach(s=>{const k=s.textContent;if(seenCss.has(k))s.remove();else seenCss.add(k);});
    // 正規化: data-* → style を再生成 (Kiro や手編集で片方だけ変わってもここで揃う)
    normalizeDataStyleSync(doc);
    return '<!DOCTYPE html>\n'+doc.outerHTML;
  }

  // data-* が正本。inline style の対応プロパティを data-* から書き直す。
  // 修正件数を返す (data-* と style の不一致を何個直したか)。
  function normalizeDataStyleSync(root){
    let fixed = 0;
    root.querySelectorAll('.slide').forEach(function(slide){
      // スライド背景
      const bg = slide.getAttribute('data-bg');
      const bgGrad = slide.getAttribute('data-bg-gradient');
      if (bgGrad) {
        const parts = bgGrad.split(',').map(s=>s.trim());
        if (parts.length >= 3) {
          fixed += setStyleValue(slide, 'background', 'linear-gradient('+parts[0]+'deg,'+parts.slice(1).join(',')+')');
        }
      } else if (bg) {
        fixed += setStyleValue(slide, 'background', bg);
      }
    });
    root.querySelectorAll('.slide [data-x]').forEach(function(el){
      const dx = el.getAttribute('data-x');
      const dy = el.getAttribute('data-y');
      const dw = el.getAttribute('data-w');
      const dh = el.getAttribute('data-h');
      if (dx !== null) fixed += setStyleValue(el, 'left', dx+'px');
      if (dy !== null) fixed += setStyleValue(el, 'top', dy+'px');
      if (dw !== null) fixed += setStyleValue(el, 'width', dw+'px');
      if (dh !== null) fixed += setStyleValue(el, 'height', dh+'px');
      // .tb: フォント関連の同期
      if (el.classList && el.classList.contains('tb')) {
        const fs = el.getAttribute('data-font-size');
        const bold = el.getAttribute('data-bold');
        const color = el.getAttribute('data-color');
        const align = el.getAttribute('data-align');
        if (fs !== null) fixed += setStyleValue(el, 'font-size', fs+'px');
        if (bold === '1') fixed += setStyleValue(el, 'font-weight', '700');
        if (color !== null) fixed += setStyleValue(el, 'color', color);
        if (align !== null) fixed += setStyleValue(el, 'text-align', align);
      }
      // .rect: 塗り
      if (el.classList && el.classList.contains('rect')) {
        const fill = el.getAttribute('data-fill');
        if (fill !== null) {
          if (fill === 'none' || fill === 'transparent') {
            fixed += setStyleValue(el, 'background', 'transparent');
          } else {
            fixed += setStyleValue(el, 'background', fill);
          }
        }
      }
    });
    if (fixed > 0) {
      console.log('[SlideKit] 正規化: data-* と style の不一致を ' + fixed + ' 件修正しました');
    }
    return fixed;
  }

  // inline style の 1 プロパティだけを書き換える。
  // 既存値と異なれば 1、同じなら 0 を返す (修正件数カウント用)。
  function setStyleValue(el, prop, value){
    if (!el || !el.style) return 0;
    try {
      const current = el.style.getPropertyValue(prop);
      // 値の正規化なしで文字列比較 (ブラウザが返す形式に依存するので厳密な等価は難しい)
      // "linear-gradient" や CSS unit を含む値は同一とみなす場合もあるが、
      // 悪影響はないので "違う" と判定されたら書き直す
      if (current === value) return 0;
      el.style.setProperty(prop, value);
      return 1;
    } catch(_) {
      return 0;
    }
  }

  async function saveDirect(html){
    if(!canDirectSave)return false;
    try{
      if(!saveHandle){
        const suggested=location.pathname.split('/').pop()||'slides.html';
        saveHandle=await window.showSaveFilePicker({
          suggestedName:suggested,
          types:[{description:'HTML',accept:{'text/html':['.html','.htm']}}]
        });
        try{await idbSet(saveKey,saveHandle);}catch(_){}
      }else{
        const perm=await saveHandle.queryPermission({mode:'readwrite'});
        if(perm!=='granted'){
          const req=await saveHandle.requestPermission({mode:'readwrite'});
          if(req!=='granted'){saveHandle=null;await idbDel(saveKey).catch(()=>{});updateSaveBtn();return false;}
        }
      }
      // 開いた後に書き換えられていないか（秒単位の誤差を見込んで2秒の余裕）
      if(knownMtime){
        const f=await saveHandle.getFile();const base=Date.parse(knownMtime);
        if(base&&f.lastModified-base>2000&&!confirmOverwrite())return 'aborted';
      }
      const w=await saveHandle.createWritable();
      await w.write(html);
      await w.close();
      try{knownMtime=new Date((await saveHandle.getFile()).lastModified).toUTCString();}catch(_){}
      return true;
    }catch(e){
      // ユーザーがキャンセル or 拒否 → 通常DLフォールバックに落とす
      if(e&&(e.name==='AbortError'||e.name==='NotAllowedError')){return 'aborted';}
      console.warn('direct save失敗:',e);
      return false;
    }
  }
  function saveDownload(html){
    const blob=new Blob([html],{type:'text/html'});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);
    a.download=location.pathname.split('/').pop()||'slides.html';a.click();
  }

  function flashSaved(msg){
    const n=document.createElement('div');n.className='seui';
    n.style.cssText='position:fixed;bottom:16px;right:16px;background:#3a7a5a;color:#fff;padding:10px 14px;border-radius:6px;font:600 13px/1.4 sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.3);z-index:100001';
    n.textContent=msg;document.body.appendChild(n);setTimeout(()=>n.remove(),2200);
  }
  bar.querySelector('#seSave').onclick=async function(){
    const html=buildCleanHTML();
    // 1) SlideKit保存対応サーバーが立っていれば PUT で同一パスに書き戻す（最短経路）
    if(hasPutServer){
      const cur=await fetchMtime();
      if(knownMtime&&cur&&cur!==knownMtime&&!confirmOverwrite())return;
      const ok=await saveViaPut(html);
      if(ok){dirty=false;knownMtime=await fetchMtime();flashSaved('✅ ワークスペースに保存: '+(location.pathname.split('/').pop()||''));return;}
      // 失敗した = サーバーが落ちた可能性 → 判定を戻して次へ
      hasPutServer=false;updateSaveBtn();
    }
    // 2) File System Access API（Chrome/Edge）
    if(canDirectSave){
      const r=await saveDirect(html);
      if(r===true){dirty=false;updateSaveBtn();
        flashSaved('✅ ワークスペースに保存: '+(saveHandle.name||''));
        return;
      }
      if(r==='aborted'){return;} // ユーザーがダイアログをキャンセル→何もしない
    }
    // 3) 通常DLフォールバック。元のファイルは書き換わっていないので「未保存」のまま扱い、そう伝える（2026-09-27）
    saveDownload(html);
    flashSaved('⬇️ ダウンロードしました。元のファイルは書き換わっていません（ダウンロードしたファイルで置き換えてください）');
  };
  // 「別名で保存」= 保存先を作り直したい時（Optionクリック or 右クリック）
  bar.querySelector('#seSave').addEventListener('contextmenu',async function(e){
    e.preventDefault();
    if(!canDirectSave){alert('お使いのブラウザは「別名保存」に対応していません（Chrome/Edgeで動作）');return;}
    if(saveHandle){if(!confirm('保存先を作り直します。よろしいですか？\n（今の保存先: '+(saveHandle.name||'')+'）'))return;}
    saveHandle=null;await idbDel(saveKey).catch(()=>{});updateSaveBtn();
    bar.querySelector('#seSave').click();
  });
  updateSaveBtn();

  // ---- 📂 HTMLを開く（保存済みデッキの .slide を読み込んで編集。閲覧/編集どちらでも可）----
  const htmlInput=document.createElement('input');htmlInput.className='seui';htmlInput.type='file';htmlInput.accept='.html,.htm,text/html';htmlInput.style.display='none';document.body.appendChild(htmlInput);
  bar.querySelector('#seOpen').onclick=function(){
    if(dirty){
      if(!confirm('保存していない編集があります。\n別ファイルを開くと、保存していない編集は失われます。続けますか？'))return;
      if(confirm('先に今の内容を保存しますか？\n　OK＝保存してから開く\n　キャンセル＝保存せず開く'))bar.querySelector('#seSave').click();
    }
    htmlInput.value='';htmlInput.click();
  };
  // テキスト入力（contenteditable）も未保存扱いにする
  document.addEventListener('input',function(){if(editing)dirty=true;});

  // 未保存編集があるとリロード/閉じる時に警告（事故防止）
  window.addEventListener('beforeunload',function(e){
    if(editing&&dirty){
      e.preventDefault();
      e.returnValue='保存していない編集があります。リロードすると消えます。「📤Kiroへ渡す」または「💾保存」してから移動してください。';
      return e.returnValue;
    }
  });

  // ---- 📐 フォーマット選択（なし / AWS / 青系モノトーン / ...拡張可） ----
  // v2: フォーマット定義 (label / overlay / palette) は slidekit-defs.js
  // (window.SLIDEKIT_DEFS.formats) が唯一の正本。ここは表示用に参照するだけ (Requirements 4.3)。
  // フォーマット追加 = defs の formats に1エントリ追加するだけでドロップダウンに並ぶ。
  // aws: AWS ロゴと Cover-Gradient オーバーレイを重ねる (PPTX変換にも反映)
  // palette: 色マップ (旧hex→新hex)。選択時に一括で data-color / data-fill / style を書き換える
  const TEMPLATES=(function(){
    const d=window.SLIDEKIT_DEFS;
    if(fmtReady && d && d.formats){
      const t={};
      Object.keys(d.formats).forEach(k=>{
        const f=d.formats[k]||{};
        t[k]={label:f.label||k,overlay:f.overlay||null};
        if(f.palette)t[k].palette=f.palette;
        // 見出し変換（aws2）。以前はここで落ちていて、線見出しへの変換が一度も走らなかった（2026-09-27）
        if(f.header)t[k].header=f.header;
      });
      return t;
    }
    // defs 読込失敗時は「なし」のみ (📐ボタン自体も無効化される / Requirements 4.2)
    return {none:{label:'なし',overlay:null}};
  })();
  let curTemplate=document.documentElement.getAttribute('data-template')||'none';
  if(!fmtReady)curTemplate='none'; // defs/format 読込失敗時は「なし」固定 (html の data-template 属性自体は保持 / Requirements 4.2)

  // --- オーバーレイ描画 (v2: 実体は slidekit-format.js に一本化 / Requirements 4.3) ---
  // 暗色スライド判定 (isDarkSlide)・光彩背景・リマップCSS・コピーライト・ロゴ解決は
  // SlideKitFormat 側に移設済み。ここに実体は持たない。
  function templateOverlayCreate(s,key){
    // TEMPLATES.overlay に値があれば描画。現状は AWS の overlay は独立トグル化したため
    // TEMPLATES 側で overlay を要求するテンプレは無い（将来の拡張用にヨロシク）
  }
  // ---- ☁️ AWSオーバーレイ (v2: SlideKitFormat.applyAwsOverlay へ委譲 / Requirements 4.3) ----
  // 光彩背景・左端バンド・ロゴ・コピーライト・表紙リマップCSSの描画実体は slidekit-format.js。
  // リマップ CSS は defs.coverRemap (9色) から機械生成されるため、v1 で漏れていた3色
  // (#a0aec0/#e8f1f7/#f0f5fa) もブラウザ側でカバーされる (Requirements 7.1 の意図的修正)。
  // uiClass 'seui' 指定でリマップ style の id も v1 と同一 ('seui-aws-cover-style') になる。
  function awsOverlayCreate(s){
    if(window.SlideKitFormat)window.SlideKitFormat.applyAwsOverlay(s,{uiClass:'seui'});
  }
  function awsOverlayRemove(){
    if(window.SlideKitFormat){window.SlideKitFormat.removeAwsOverlay(document);return;}
    // format 未読込時の最小フォールバック (オーバーレイは作られないので通常は到達しない)
    document.querySelectorAll('.aws-overlay').forEach(e=>e.remove());
    document.querySelectorAll('.slide.aws-cover').forEach(s=>s.classList.remove('aws-cover'));
  }
  // 初期値: <html data-aws-decoration="on"> か 旧仕様の <html data-template="aws"> があれば ON
  // (defs/format 読込失敗時は OFF 固定 + 属性マイグレーションもしない = 保存 HTML を汚さない)
  let awsOn=fmtReady && document.documentElement.getAttribute('data-aws-decoration')==='on';
  if(fmtReady && !awsOn && document.documentElement.getAttribute('data-template')==='aws'){
    awsOn=true;
    // 旧仕様マイグレーション: data-template="aws" → data-aws-decoration="on" + data-template="none"
    document.documentElement.setAttribute('data-aws-decoration','on');
    document.documentElement.removeAttribute('data-template');
  }
  // (旧) 独立トグル用の awsApply / updateAwsBtn は削除。
  // 現在は 📐フォーマット の "AWS" 選択で templateApply 内から on/off される。
  // パレット適用時の「変換前スナップショット」(なし に戻す時に復元する)
  // { records: [{el, color, fill, style}] }
  let paletteSnapshot=null;

  function templateApply(key){
    const prev=curTemplate;
    const prevTpl=TEMPLATES[prev];
    const tpl=TEMPLATES[key];
    // 現在パレット適用中で、別のフォーマット(なし含む)に切り替える場合は先に色を戻す
    if(prevTpl && prevTpl.palette && paletteSnapshot && prev!==key){
      revertPaletteSwap();
    }
    templateRemove(); // 既存オーバーレイをクリア
    // AWS オーバーレイは 'aws' 選択時のみ表示 (他フォーマットに切替時は解除)
    awsOverlayRemove();
    // 新しいテンプレートにパレットがあれば適用
    if(tpl && tpl.palette && prev!==key){
      const ok=confirm('「'+tpl.label+'」に変換します。全スライドの色を一括で置き換えます。\n\n「なし」を選ぶと元の色に戻ります。\n実行しますか?');
      if(!ok){updateFmtBtn();return;}
      applyPaletteSwap(tpl.palette);
    }
    curTemplate=key;
    if(key&&key!=='none'){
      document.documentElement.setAttribute('data-template',key);
      allSlides().forEach((s,i)=>templateOverlayCreate(s,key));
    }else{
      document.documentElement.removeAttribute('data-template');
    }
    // 見出しスタイルの変換（header を持つフォーマット = AWSフォーマット2）。
    // 内容を書き換えるのでundoスナップショットを取り、件数をトーストで返す（2026-09-08）
    // prev!==key＝利用者がフォーマットを切り替えた時だけ。開いた瞬間の自動適用では確認を出さない
    if(tpl&&tpl.header&&prev!==key&&window.SlideKitFormat&&window.SlideKitFormat.applyHeaderStyle){
      const targets=allSlides().filter(s=>!s.getAttribute('data-bg-gradient')&&!s.querySelector('[data-sk-headline]'));
      if(targets.length){
        const ok=confirm('「'+tpl.label+'」の見出しに変換します。\n\nバッジを消し、タイトルの下に線を引きます（'+targets.length+'ページ）。\n⌘Zで戻せます。実行しますか?');
        if(ok){
          pushAttr(targets); // ページ内容ごと戻せるように（rec()はinnerHTMLも記録する）
          let n=0;targets.forEach(s=>{n+=window.SlideKitFormat.applyHeaderStyle(s,tpl.header);});
          if(typeof flashSaved==='function')flashSaved('見出しを変換しました（'+n+'ページ）');
          dirty=true;
        }
      }
    }
    // AWS オーバーレイを適用 (aws 系選択時。aws2 は aws の派生なので同じ装飾を出す)
    if(key==='aws'||key==='aws2'){
      awsOn=true;
      document.documentElement.setAttribute('data-aws-decoration','on');
      allSlides().forEach(s=>awsOverlayCreate(s));
    }else{
      awsOn=false;
      document.documentElement.removeAttribute('data-aws-decoration');
    }
    updateFmtBtn();
  }
  // パレット一括置換 (v2: 置換実体は SlideKitFormat.applyPalette へ委譲 / Requirements 4.3)
  // undo 統合・dirty フラグ・「置換対象なし」の alert は従来どおりこちらの責務。
  // applyPalette は変換後に「変換前の値」のスナップショットを返す (対象なしは null)。
  function applyPaletteSwap(map){
    if(!window.SlideKitFormat){alert('フォーマット機能が利用できません (slidekit-format.js 未読込)');return;}
    const snap=window.SlideKitFormat.applyPalette(map);
    if(!snap){alert('置換対象なし');return;}
    // undo スナップショット (⌘Z 一発で戻せる):
    // v1 は「変換前に pushAttr」だった。v2 は変換後に rec() を取り、palette が触る
    // 3属性 (data-color / data-fill / style) だけ snap の変換前値へ差し戻して積む = 復元結果は同一
    const items=snap.records.map(r=>{
      const it=rec(r.el);
      if(r.color!=null)it.dattrs['data-color']=r.color;else delete it.dattrs['data-color'];
      if(r.fill!=null)it.dattrs['data-fill']=r.fill;else delete it.dattrs['data-fill'];
      it.style=r.style;
      return it;
    });
    undo.push({type:'attr',items});if(undo.length>60)undo.shift();redo.length=0;
    // 「なし」に戻した時の復元用スナップショット
    paletteSnapshot=snap;
    dirty=true;
  }
  // パレット変換を巻き戻す(「なし」に戻す時)。復元実体は SlideKitFormat.revertPalette
  function revertPaletteSwap(){
    if(!paletteSnapshot)return;
    const els=paletteSnapshot.records.map(r=>r.el).filter(el=>el&&el.isConnected);
    if(els.length)pushAttr(els);  // ⌘Zで再適用できる状態にする
    if(window.SlideKitFormat)window.SlideKitFormat.revertPalette(paletteSnapshot);
    paletteSnapshot=null;
    dirty=true;
  }
  function templateRemove(){
    document.querySelectorAll('.tpl-overlay').forEach(e=>e.remove());
  }
  function updateFmtBtn(){
    const fmtBtn=bar.querySelector('#seFmt');
    if(!fmtReady){
      // defs/format 読込失敗 (Requirements 4.2): ⚠️ を表示して無効化 (「なし」固定)
      fmtBtn.textContent='📐 フォーマット ⚠️';
      fmtBtn.disabled=true;
      fmtBtn.style.opacity='.55';fmtBtn.style.cursor='not-allowed';
      fmtBtn.title='slidekit-defs.js / slidekit-format.js が読み込めないためフォーマット機能は使えません (編集機能は通常どおり使えます)';
      return;
    }
    const t=TEMPLATES[curTemplate];
    if(curTemplate==='none'){fmtBtn.style.background='rgba(74,74,74,.95)';fmtBtn.textContent='📐 フォーマット';}
    else{fmtBtn.style.background='#ff9900';fmtBtn.textContent='📐 '+(t?t.label:curTemplate);}
  }

  // --- フォーマット選択パネル ---
  const fmtPanel=document.createElement('div');fmtPanel.className='seui';
  fmtPanel.style.cssText='display:none;position:fixed;top:50px;right:12px;z-index:100000;background:rgba(74,74,74,.96);padding:10px 12px;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.35);min-width:160px';
  const fmtTitle=document.createElement('div');fmtTitle.textContent='📐 フォーマット選択';fmtTitle.style.cssText='color:#fff;font:700 12px/1 sans-serif;margin-bottom:8px';
  fmtPanel.appendChild(fmtTitle);
  Object.keys(TEMPLATES).forEach(key=>{
    const btn=document.createElement('button');
    btn.textContent=(key===curTemplate?'● ':'○ ')+TEMPLATES[key].label;
    btn.setAttribute('data-tpl',key);
    btn.style.cssText='display:block;width:100%;text-align:left;padding:6px 10px;border:none;border-radius:3px;background:'+(key===curTemplate?'#ff9900':'#3a3a3a')+';color:#fff;font-size:13px;cursor:pointer;margin-bottom:4px';
    fmtPanel.appendChild(btn);
  });
  document.body.appendChild(fmtPanel);
  fmtPanel.addEventListener('mousedown',e=>{e.stopPropagation();e.preventDefault();});
  fmtPanel.addEventListener('click',function(e){
    const key=e.target.getAttribute&&e.target.getAttribute('data-tpl');
    if(!key)return;
    templateApply(key);
    fmtPanel.style.display='none';
    dirty=true;
    // ボタン表示更新
    fmtPanel.querySelectorAll('button[data-tpl]').forEach(b=>{
      const k=b.getAttribute('data-tpl');
      b.textContent=(k===curTemplate?'● ':'○ ')+TEMPLATES[k].label;
      b.style.background=(k===curTemplate?'#ff9900':'#3a3a3a');
    });
  });
  bar.querySelector('#seFmt').onclick=function(){
    if(!fmtReady)return; // defs/format 読込失敗時は無効 (Requirements 4.2)
    // パネル表示トグル
    if(fmtPanel.style.display==='none'||!fmtPanel.style.display){
      fmtPanel.style.display='block';
      // 現在の選択状態を反映
      fmtPanel.querySelectorAll('button[data-tpl]').forEach(b=>{
        const k=b.getAttribute('data-tpl');
        b.textContent=(k===curTemplate?'● ':'○ ')+TEMPLATES[k].label;
        b.style.background=(k===curTemplate?'#ff9900':'#3a3a3a');
      });
    }else{fmtPanel.style.display='none';}
  };
  // パネル外クリックで閉じる
  document.addEventListener('mousedown',function(e){if(fmtPanel.style.display==='block'&&!fmtPanel.contains(e.target)&&e.target!==bar.querySelector('#seFmt'))fmtPanel.style.display='none';});

  // ページ追加・複製後に新ページにもオーバーレイを付ける
  const _origAfterStruct=afterStruct;
  afterStruct=function(target){
    _origAfterStruct(target);
    if(curTemplate&&curTemplate!=='none'){
      allSlides().forEach(s=>{if(!s.querySelector('.tpl-overlay'))templateOverlayCreate(s,curTemplate);});
    }
    // AWSロゴ独立トグルが ON なら新ページにも追加
    if(awsOn){allSlides().forEach(s=>{if(!s.querySelector('.aws-overlay'))awsOverlayCreate(s);});}
  };
  // 初期表示時：data-templateが既にあれば適用
  if(curTemplate&&curTemplate!=='none')templateApply(curTemplate);
  updateFmtBtn();
  // AWS ロゴは 📐フォーマット の "AWS" 選択で on/off する。
  // 旧仕様の data-aws-decoration="on" が残っていたら data-template="aws" に格上げしておく。
  // aws2 は aws の派生なので格上げしない（以前は開くたびに aws2 → aws へ書き換わっていた・2026-09-27）
  if(awsOn && curTemplate!=='aws' && curTemplate!=='aws2'){
    curTemplate='aws';
    document.documentElement.setAttribute('data-template','aws');
    document.documentElement.removeAttribute('data-aws-decoration');
    allSlides().forEach(s=>awsOverlayCreate(s));
    updateFmtBtn();
  }

  // ---- 🅰️ 書き出しFont（body font-familyの先頭を切替→PPTX書き出しに確実に反映）
  //     ブラウザ表示は実際に入っているフォントに依存するため必ず切り替わるわけではないが、
  //     保存後のHTMLから html_to_pptx.py が先頭のフォント名を拾って PPTX に書き出す
  // primary=そのフォントが無い環境ではfallbackで表示されるが、PPTXにはprimary名で書き出されるので配布先(Windows)ではそのフォントで開かれる
  const FONTS={
    meiryo_ui:{label:'Meiryo UI',   primary:'Meiryo UI',            stack:"'Meiryo UI','Yu Gothic','游ゴシック','Hiragino Sans','Noto Sans JP',sans-serif"},
    yu_gothic:{label:'Yu Gothic',   primary:'Yu Gothic',            stack:"'Yu Gothic','游ゴシック','Meiryo UI','Hiragino Sans','Noto Sans JP',sans-serif"},
    meiryo:   {label:'メイリオ',      primary:'Meiryo',               stack:"'Meiryo','Meiryo UI','Yu Gothic','游ゴシック','Hiragino Sans','Noto Sans JP',sans-serif"},
    hiragino: {label:'ヒラギノ角ゴ (mac)', primary:'Hiragino Sans',    stack:"'Hiragino Sans','ヒラギノ角ゴ ProN','Yu Gothic','Meiryo UI',sans-serif"},
    noto_sans_jp:{label:'Noto Sans JP', primary:'Noto Sans JP',      stack:"'Noto Sans JP','Yu Gothic','Meiryo UI','Hiragino Sans',sans-serif"},
    yu_mincho:{label:'Yu Mincho (明朝)',  primary:'Yu Mincho',        stack:"'Yu Mincho','游明朝','Hiragino Mincho ProN','MS Mincho',serif"},
    hira_mincho:{label:'ヒラギノ明朝 (mac)', primary:'Hiragino Mincho ProN', stack:"'Hiragino Mincho ProN','ヒラギノ明朝 ProN W3','Yu Mincho','MS Mincho',serif"}
  };
  function isFontInstalled(name){try{return document.fonts.check('16px "'+name+'"');}catch(_){return false;}}
  // 現在のbody font-familyから初期選択キーを推定
  // 🚨宣言の「先頭フォント」だけで判定する。文字列全体を検索すると、
  // スタック後方のfallback（例: Meiryo UIスタック内の'Hiragino Sans'）に
  // 誤マッチして、リロード時に別フォントが選択される（2026-07-18実地で発生）
  function detectCurFont(){
    const dk=document.documentElement.getAttribute('data-font');
    if(dk&&FONTS[dk])return dk;
    const st=document.body.getAttribute('style')||'';
    const m=st.match(/font-family\s*:\s*([^;]+)/i);
    const fam=m?m[1]:(getComputedStyle(document.body).fontFamily||'');
    const first=(fam.split(',')[0]||'').trim().replace(/^['"]|['"]$/g,'').toLowerCase();
    for(const k in FONTS){if(FONTS[k].primary.toLowerCase()===first)return k;}
    const alias={'游ゴシック':'yu_gothic','游明朝':'yu_mincho','ヒラギノ角ゴ pron':'hiragino','ヒラギノ明朝 pron w3':'hira_mincho','メイリオ':'meiryo'};
    if(alias[first])return alias[first];
    return 'meiryo_ui';
  }
  // ブラウザで実際に描画されているフォント名を推定（キーの primary が使えるか順に判定）
  function effectiveRenderName(key){
    const f=FONTS[key];if(!f)return '';
    // stack を左から順にチェックして最初に使えるフォント名を返す
    const parts=f.stack.split(',').map(s=>s.trim().replace(/^['"]|['"]$/g,''));
    for(const p of parts){if(p==='sans-serif'||p==='serif')return p;if(isFontInstalled(p))return p;}
    return parts[0]||'';
  }
  let curFont=detectCurFont();
  const fontOrig=curFont;  // 「変更をコピー」でフォント切替を差分報告するための初期値
  function applyFont(key){
    const f=FONTS[key];if(!f)return;
    curFont=key;
    // body の inline style の font-family だけ差し替え（他のstyleは温存）
    const st=(document.body.getAttribute('style')||'');
    const re=/font-family\s*:[^;]*;?/i;
    const nst=re.test(st)?st.replace(re,'font-family:'+f.stack+';'):(st?st.replace(/;?\s*$/,';'):'')+'font-family:'+f.stack+';';
    document.body.setAttribute('style',nst);
    document.body.style.fontFamily=f.stack;
    document.documentElement.setAttribute('data-font',key);
    updateFontBtn();
    dirty=true;
  }
  function updateFontBtn(){
    const f=FONTS[curFont];
    const btn=bar.querySelector('#seFont');
    if(!btn)return;
    if(curFont==='meiryo_ui'){btn.style.background='rgba(74,74,74,.95)';btn.textContent='🅰️ 書き出しFont';}
    else{btn.style.background='#3a7a5a';btn.textContent='🅰️ '+(f?f.label:'書き出しFont');}
  }
  const fontPanel=document.createElement('div');fontPanel.className='seui';
  fontPanel.style.cssText='display:none;position:fixed;top:50px;right:12px;z-index:100000;background:rgba(74,74,74,.96);padding:10px 12px;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.35);min-width:280px';
  const fontTitle=document.createElement('div');fontTitle.textContent='🅰️ 書き出しFont（PPTX出力時のフォント）';fontTitle.style.cssText='color:#fff;font:700 12px/1.3 sans-serif;margin-bottom:8px';
  fontPanel.appendChild(fontTitle);
  function fontBtnLabel(key){
    const f=FONTS[key],ok=isFontInstalled(f.primary);
    const dot=(key===curFont?'●':'○');
    const badge=ok?'<span style="color:#8ce8b3;font-size:10px;margin-left:6px">✓ 利用可</span>':'<span style="color:#ffb090;font-size:10px;margin-left:6px">× 未検出→PPTXのみ有効</span>';
    return dot+' <span style="font-size:13px">'+f.label+'</span>'+badge;
  }
  Object.keys(FONTS).forEach(key=>{
    const btn=document.createElement('button');
    btn.setAttribute('data-fnt',key);
    btn.innerHTML=fontBtnLabel(key);
    btn.style.cssText='display:block;width:100%;text-align:left;padding:6px 10px;border:none;border-radius:3px;background:'+(key===curFont?'#3a7a5a':'#3a3a3a')+';color:#fff;cursor:pointer;margin-bottom:4px;font-family:'+FONTS[key].stack;
    fontPanel.appendChild(btn);
  });
  const fontNote=document.createElement('div');fontNote.style.cssText='color:#cdd9e5;font:400 10px/1.5 sans-serif;margin-top:4px;padding-top:6px;border-top:1px solid rgba(255,255,255,.15)';
  fontNote.innerHTML='<b>PPTX保存時はこのフォント名で書き出し</b>。ブラウザ表示は<br>そのフォントが無い環境ではfallback表示されます。';
  fontPanel.appendChild(fontNote);
  const fontEff=document.createElement('div');fontEff.style.cssText='color:#9fc0dd;font:600 11px/1.4 sans-serif;margin-top:6px';
  fontPanel.appendChild(fontEff);
  function refreshFontEff(){fontEff.textContent='いまブラウザで実効: '+effectiveRenderName(curFont);}
  refreshFontEff();
  document.body.appendChild(fontPanel);
  fontPanel.addEventListener('mousedown',e=>{e.stopPropagation();e.preventDefault();});
  function refreshFontButtons(){
    fontPanel.querySelectorAll('button[data-fnt]').forEach(b=>{
      const k=b.getAttribute('data-fnt');
      b.innerHTML=fontBtnLabel(k);
      b.style.background=(k===curFont?'#3a7a5a':'#3a3a3a');
    });
    refreshFontEff();
  }
  fontPanel.addEventListener('click',function(e){
    const btn=e.target.closest&&e.target.closest('button[data-fnt]');
    if(!btn)return;
    const key=btn.getAttribute('data-fnt');
    applyFont(key);
    refreshFontButtons();
    // 選択後もパネルを閉じない（連続比較したいことがあるので）
    // 閉じたい時はパネル外クリック
  });
  bar.querySelector('#seFont').onclick=function(){
    if(fontPanel.style.display==='none'||!fontPanel.style.display){
      fontPanel.style.display='block';
      curFont=detectCurFont();
      refreshFontButtons();
    }else{fontPanel.style.display='none';}
  };
  document.addEventListener('mousedown',function(e){if(fontPanel.style.display==='block'&&!fontPanel.contains(e.target)&&e.target!==bar.querySelector('#seFont'))fontPanel.style.display='none';});
  updateFontBtn();

  htmlInput.addEventListener('change',function(){const f=htmlInput.files&&htmlInput.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>importDeck(rd.result,f.name);rd.readAsText(f);});
  function importDeck(htmlStr,name){
    let imported=[];try{imported=[...new DOMParser().parseFromString(htmlStr,'text/html').querySelectorAll('.slide')];}catch(_){}
    if(!imported.length){alert('スライド（.slide）が見つかりませんでした：'+(name||''));return;}
    if(!confirm('「'+(name||'ファイル')+'」の '+imported.length+' 枚を読み込みます。\n今表示中の編集内容は破棄されます。よろしいですか？'))return;
    allSlides().forEach(s=>s.remove());
    const frag=document.createDocumentFragment();
    imported.forEach(s=>{
      s.querySelectorAll('.seui').forEach(e=>e.remove());
      s.querySelectorAll('[data-role]').forEach(e=>e.removeAttribute('data-role'));
      s.querySelectorAll('[contenteditable]').forEach(e=>e.removeAttribute('contenteditable'));
      s.querySelectorAll('[data-inserted]').forEach(e=>e.removeAttribute('data-inserted'));
      s.querySelectorAll('*').forEach(e=>{if(e.style&&e.style.outline){e.style.outline='';e.style.outlineOffset='';}});
      [...s.querySelectorAll(':scope > .tb')].forEach(t=>{const x=parseFloat(t.getAttribute('data-x')||0),y=parseFloat(t.getAttribute('data-y')||0);if(x>=1180&&y>=660&&/^\d+$/.test((t.textContent||'').trim()))t.remove();});
      frag.appendChild(document.importNode(s,true));
    });
    document.body.insertBefore(frag,document.body.firstChild);
    orig.clear();txt0.clear();undo.length=0;sels=[];if(typeof pageSel!=='undefined')pageSel=null;if(typeof bgOrig!=='undefined')bgOrig.clear();if(typeof pageLog!=='undefined')pageLog.length=0;layerLog.length=0;dirty=false;
    clearSel();if(typeof clearPageSel==='function')clearPageSel();
    classifyRoles();renumberPages();window.scrollTo(0,0);
  }

  // ---- レイヤー順（重ね順）操作 ----
  // 対象要素：.slide直下のdata-x属性を持つ要素のみ
  function layerTargets(slide){
    return [...slide.querySelectorAll(':scope > [data-x]')];
  }

  // Undo用：操作前の全要素順序を記録
  function pushOrder(slide){undo.push({type:'order',slide,order:layerTargets(slide)});if(undo.length>60)undo.shift();redo.length=0;dirty=true;}

  // 前面に1つ移動（DOM上で後方に1つ）
  // 後方（前面側）の選択要素から処理。既に最後 or 直後も選択中なら不動
  function bringForward(elements){
    if(!elements||!elements.length)return false;
    const slide=elements[0].closest('.slide');
    if(!slide)return false;
    const targets=layerTargets(slide);
    const selected=new Set(elements);
    let changed=false;
    // 後方（インデックス大=前面側）から処理
    for(let i=targets.length-1;i>=0;i--){
      const el=targets[i];
      if(!selected.has(el))continue;
      // 既に最後なら不動
      if(i===targets.length-1)continue;
      // 直後も選択中なら不動
      if(selected.has(targets[i+1]))continue;
      // 1つ後方に移動: insertBefore(el, el.nextElementSibling.nextElementSibling)
      const next=targets[i+1];
      slide.insertBefore(el,next.nextElementSibling);
      changed=true;
      // targets配列を更新（swap）
      targets[i]=next;
      targets[i+1]=el;
    }
    return changed;
  }

  // 背面に1つ移動（DOM上で前方に1つ）
  // 前方（インデックス小=背面側）の選択要素から処理
  function sendBackward(elements){
    if(!elements||!elements.length)return false;
    const slide=elements[0].closest('.slide');
    if(!slide)return false;
    const targets=layerTargets(slide);
    const selected=new Set(elements);
    let changed=false;
    // 前方（インデックス小=背面側）から処理
    for(let i=0;i<targets.length;i++){
      const el=targets[i];
      if(!selected.has(el))continue;
      // 既に先頭なら不動
      if(i===0)continue;
      // 直前も選択中なら不動
      if(selected.has(targets[i-1]))continue;
      // 1つ前方に移動: insertBefore(el, el.previousElementSibling)
      const prev=targets[i-1];
      slide.insertBefore(el,prev);
      changed=true;
      // targets配列を更新（swap）
      targets[i]=prev;
      targets[i-1]=el;
    }
    return changed;
  }

  // 最前面に移動（選択要素を相対順序維持で最後尾に）
  function bringToFront(elements){
    if(!elements||!elements.length)return false;
    const slide=elements[0].closest('.slide');
    if(!slide)return false;
    const targets=layerTargets(slide);
    const selected=new Set(elements);
    // 既に全選択要素が最後尾に連続しているか確認
    const selectedInOrder=targets.filter(el=>selected.has(el));
    const lastN=targets.slice(targets.length-selectedInOrder.length);
    const alreadyAtFront=selectedInOrder.length===lastN.length&&selectedInOrder.every((el,i)=>el===lastN[i]);
    if(alreadyAtFront)return false;
    // 相対順序維持で最後尾に移動
    selectedInOrder.forEach(el=>slide.appendChild(el));
    return true;
  }

  // 最背面に移動（選択要素を相対順序維持で先頭に）
  function sendToBack(elements){
    if(!elements||!elements.length)return false;
    const slide=elements[0].closest('.slide');
    if(!slide)return false;
    const targets=layerTargets(slide);
    const selected=new Set(elements);
    // 既に全選択要素が先頭に連続しているか確認
    const selectedInOrder=targets.filter(el=>selected.has(el));
    const firstN=targets.slice(0,selectedInOrder.length);
    const alreadyAtBack=selectedInOrder.length===firstN.length&&selectedInOrder.every((el,i)=>el===firstN[i]);
    if(alreadyAtBack)return false;
    // 相対順序維持で先頭に移動
    // 最初の非選択要素の前に選択要素を順に挿入
    const firstNonSelected=targets.find(el=>!selected.has(el));
    if(!firstNonSelected)return false; // 全部選択なら移動不要
    selectedInOrder.forEach(el=>slide.insertBefore(el,firstNonSelected));
    return true;
  }

  // テスト用エクスポート
  window._layerOrder={layerTargets,bringForward,sendBackward,bringToFront,sendToBack,pushOrder,doUndo,undo,layerLog};

  // 公開 API (window.SlideKit) はファイル冒頭で定義済み (v2 / Requirements 4.4)。
  // ここでは編集内部状態へのフックだけを配線する (init() 実行後に API が編集状態へ届く = v1 と同じ)。
  _hooks.clearSel=function(){ if(typeof clearSel==='function') clearSel(); };
  _hooks.clearPageSel=function(){ if(typeof clearPageSel==='function' && pageSel) clearPageSel(); };
  _hooks.isEditing=function(){ return !!editing; };
  } // ← init() 終わり

  // ========================================================================
  // 統一サニタイズ: あらゆる「編集 UI を剥がして正本 HTML に戻す」処理を集約
  // ========================================================================
  // 従来は 3 箇所 (cleanSlideClone / buildCleanHTML / sendSlideUpdate / sendDeckSync)
  // で個別に「剥がすリスト」を書いていた。ここに集約することで、
  // 新しい UI クラスが増えた時に片方だけ反映漏れて事故る問題を根絶する。
  // v2: init() 非依存の純 DOM 処理のため IIFE 直下に置き、hideUI=1 でも
  // window.SlideKit.sanitizeSlide として使える (Requirements 4.4)。
  //
  // 使い方: 事前に cloneNode(true) してから渡す (in-place で子孫まで書き換える)。
  //
  // mode:
  //   'save'  … 💾 保存用 (PPTX 変換にもかける HTML)
  //             編集UI・.inszone・data-role・data-inserted・contenteditable・outline を全部除去
  //             さらに data-* → style の正規化まで行う
  //   'copy'  … ページ複製・ペースト用 (内部で HTML をコピーして貼る時)
  //             編集UI・data-role・contenteditable・outline を除去 + ページ番号除去
  //   'sync'  … プレゼン別窓へのリアルタイム同期用
  //             編集UI・contenteditable・outline・.aws-overlay を除去 + shadow 復元
  function _sanitizeSlide(el, mode){
      mode = mode || 'sync';
      if (!el) return el;

      // ---- 共通: 編集 UI (.seui) を除去 ----
      el.querySelectorAll('.seui').forEach(function(x){ x.remove(); });

      // ---- 共通: 全 outline を再帰的に剥がす (自分自身も含む) ----
      if (el.style) {
        el.style.outline = '';
        el.style.outlineOffset = '';
      }
      el.querySelectorAll('*').forEach(function(x){
        if (x.style && x.style.outline) {
          x.style.outline = '';
          x.style.outlineOffset = '';
        }
      });

      // ---- 共通: contenteditable 除去 (編集中フォーカスの持ち出しを防ぐ) ----
      el.querySelectorAll('[contenteditable]').forEach(function(x){
        x.removeAttribute('contenteditable');
      });

      // ---- save/copy 共通: 内部マーカー属性を除去 ----
      if (mode === 'save' || mode === 'copy') {
        el.querySelectorAll('[data-role]').forEach(function(x){
          x.removeAttribute('data-role');
        });
        el.querySelectorAll('[data-inserted]').forEach(function(x){
          x.removeAttribute('data-inserted');
        });
        // プレゼン連携の選択発光(box-shadow)が焼き込まれないよう元に戻す
        var shadowed = el.hasAttribute && el.hasAttribute('data-orig-shadow') ? [el] : [];
        el.querySelectorAll('[data-orig-shadow]').forEach(function(x){ shadowed.push(x); });
        shadowed.forEach(function(x){
          if (x.style) x.style.boxShadow = x.getAttribute('data-orig-shadow') || '';
          x.removeAttribute('data-orig-shadow');
        });
      }

      // ---- save 専用: 中身未確定の波線プレースホルダーを除去 ----
      if (mode === 'save') {
        // 依頼の枠（data-ask＝何を描くか・どんなグラフかを書いた枠）は、画像が入るまで残す（2026-10-14）
        el.querySelectorAll('.inszone:not([data-ask])').forEach(function(x){ x.remove(); });
      }

      // ---- copy 専用: ページ番号を除去 (renumberPages で振り直す前提) ----
      if (mode === 'copy') {
        // pagenoNodes(el) 相当の inline 判定
        Array.prototype.forEach.call(el.querySelectorAll(':scope > .tb, .tb'), function(t){
          var x = parseInt(t.getAttribute('data-x') || 0, 10);
          var y = parseInt(t.getAttribute('data-y') || 0, 10);
          if (x >= 1180 && y >= 660 && /^\d+$/.test((t.textContent || '').trim())) {
            t.remove();
          }
        });
      }

      // ---- sync 専用: AWS 装飾を剥がし、元の box-shadow を復元 ----
      if (mode === 'sync') {
        el.querySelectorAll('.aws-overlay').forEach(function(x){ x.remove(); });
        if (el.classList) el.classList.remove('aws-cover');
        // present 側で復元用に保存した元の box-shadow を戻す
        var origShadow = el.getAttribute('data-orig-shadow');
        if (origShadow !== null && el.style) el.style.boxShadow = origShadow;
      }

      return el;
  } // ← _sanitizeSlide 終わり

  // ---- 起動: defs/format をロードしてから初期化する (Requirements 4.1, 4.4) ----
  // hideUI=1 の時は編集 UI (init) を起動せず、ページ自動採番だけ実行する。
  // window.SlideKit 公開 API は上で定義済み (パース時に同期定義 = v1 の非 hideUI 時と同じ)。
  loadSlideKitDeps(function(){
    // ロード順不定対策: プラグイン (slidekit-aws.js) が defs より先に評価されても
    // ここで共通マージする (プラグイン自身の register() と二重でも同値上書きで冪等)
    if(window.SlideKitFormat && window.SlideKitFormat.registerFormatPlugins)window.SlideKitFormat.registerFormatPlugins();
    fmtReady=!!(window.SLIDEKIT_DEFS && window.SLIDEKIT_DEFS.formats && window.SlideKitFormat);
    if(!fmtReady)console.warn('SlideKit: slidekit-defs.js / slidekit-format.js が読み込めないため 📐フォーマット機能を無効化します (編集機能は通常どおり使えます)');
    const run=HIDE_UI?autoNumberPages:init;
    // ネイティブ箇条書きを含むデッキは表示用CSSを確保する（Kiroが手書きしたHTMLでもマーカーが出る）
    const start=function(){ensureListCssIfUsed();run();};
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
    else start();
  });
})();

// ---- 絵文字→SVGアイコン置換（隣に sk-icons.js があれば編集UIに適用・無ければ絵文字のまま） ----
// 正本: BezierKit/icons-data.js → SlideKit/gen-sk-icons.py で生成。スライド本文（.seui以外）は触らない
(function(){
 try{
  var me=document.currentScript&&document.currentScript.src;
  if(!me){var ss=document.querySelectorAll('script[src]');
   for(var i=0;i<ss.length;i++){if(/slide-edit\.js/.test(ss[i].src)){me=ss[i].src;break;}}}
  if(!me)return;
  var sc=document.createElement('script');
  sc.className='seui';
  sc.src=me.replace(/slide-edit\.js.*$/,'sk-icons.js');
  sc.onload=function(){
   if(!window.SKIcons)return;
   var css=document.createElement('style');
   css.className='seui';
   css.textContent='.seui svg.sk-ic{width:1em;height:1em;vertical-align:-0.12em;display:inline-block}';
   document.head.appendChild(css);
   var apply=function(){var f=window.SKIcons.replaceUI||window.SKIcons.replaceEmoji;
    document.querySelectorAll('.seui').forEach(function(el){f(el);});};
   var mo=new MutationObserver(function(ms){
    var hit=ms.some(function(m){var el=m.target.nodeType===1?m.target:m.target.parentNode;
     return el&&el.closest&&el.closest('.seui');});
    if(hit){mo.disconnect();apply();observe();} // 置換中の変異で無限ループしないよう外して掛け直す
   });
   var observe=function(){mo.observe(document.body,{childList:true,subtree:true,characterData:true});};
   apply();observe();
  };
  sc.onerror=function(){}; // sk-icons.jsが無い環境では絵文字のまま
  document.head.appendChild(sc);
 }catch(_){}
})();
