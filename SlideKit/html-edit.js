/* ============================================================
  SlideKit / html-edit.js  ── 一般HTML編集スニペット（1行注入）
  ------------------------------------------------------------
  対象HTMLの </body> 直前に次の1行を置くだけ:
    <script src="../SlideKit/html-edit.js"></script>

  起動時に body 全体を 2カラム化（左=本体・右=パネル）にし、
  右パネルで選択要素の
    - サイズ (width/height)
    - 余白 (margin/padding 上下左右)
    - 色   (背景/文字/境界)
    - 文字 (font-size / weight / align)
    - 表示 (display block/flex/grid/inline-block/none)
    - flex (direction/gap/justify/align)  ※display:flex時のみ
  を編集できる。localStorage不使用＝HTML本体が唯一の正本。
  「📋 パッチをコピー」で変更点を Kiro 貼付用テキストとして出力。
============================================================ */
(function(){
  if(window.__heInited)return;window.__heInited=true;
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',boot,{once:true});return}
  boot();

function boot(){
  const state={
    editing:false,
    sel:null,          // 選択中要素
    marker:null,       // ハイライト枠 element
    tab:'edit',        // 'edit' | 'theme'
    multiApply:true,   // 同種要素にまとめて適用
    peerMarkers:[],    // 同種要素のハイライト枠
    changes:new Map(), // el -> {selector, before:{...}, after:{...}}
    origStyle:new Map()// el -> 元 style.cssText
  };
  const $=t=>document.createElement(t);

  // ===== 1) 既存bodyをラップして 2カラム化 =====
  const bodyComp=getComputedStyle(document.body);
  const content=$('div');
  content.id='he-content';
  // content は透明にして body の背景/テーマCSSが透けるようにする
  content.style.cssText='position:relative;overflow:auto;height:100vh;background:transparent';
  // body直下要素を content に移動（script/styleは除外して元の位置に残す）
  Array.from(document.body.childNodes).forEach(n=>{
    if(n.nodeType===1&&(n.tagName==='SCRIPT'||n.tagName==='STYLE'))return;
    content.appendChild(n);
  });
  const panel=makePanel();
  // bodyを 2カラム grid に（背景は body 側のTailwind class/テーマCSSに任せる）
  document.body.style.margin='0';
  document.body.style.padding='0';
  document.body.style.display='grid';
  document.body.style.gridTemplateColumns='1fr 380px';
  document.body.style.height='100vh';
  document.body.style.overflow='hidden';
  document.body.style.fontFamily=bodyComp.fontFamily;
  document.body.appendChild(content);
  document.body.appendChild(panel);

  // ハイライト枠（body直下・fixed）
  const marker=$('div');
  marker.id='he-marker';
  marker.style.cssText='position:fixed;pointer-events:none;box-shadow:0 0 0 2px #2563eb, 0 0 0 4px rgba(37,99,235,0.25);border-radius:2px;z-index:2147483645;display:none;transition:all 0.06s ease-out';
  document.body.appendChild(marker);
  state.marker=marker;

  // ===== 2) パネル UI =====
  function makePanel(){
    const p=$('aside');
    p.id='he-panel';
    p.style.cssText=`
      display:flex;flex-direction:column;height:100vh;
      background:#f8fafc;border-left:1px solid #cbd5e1;
      font-family:system-ui,-apple-system,'Yu Gothic',sans-serif;color:#1e293b;
      font-size:13px;overflow:hidden;
    `;
    p.innerHTML=`
      <div id="he-head" style="display:flex;flex-direction:column;gap:6px;padding:10px 14px;border-bottom:1px solid #cbd5e1;background:#fff">
        <div style="display:flex;align-items:center;gap:8px">
          <strong style="font-size:13px;letter-spacing:0.02em;color:#0f172a">🎨 HTML Edit</strong>
          <span style="flex:1"></span>
          <button id="he-toggle" title="編集ON/OFF" style="padding:4px 10px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;font-size:12px;font-family:inherit">✏️ 編集</button>
        </div>
        <div id="he-tabs" style="display:flex;gap:2px;margin-top:4px">
          <button data-tab="edit" class="he-tab" style="flex:1;padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px 6px 0 0;background:#fff;cursor:pointer;font-size:12px;font-family:inherit;font-weight:600;color:#0f172a;border-bottom-color:#fff">選択</button>
          <button data-tab="theme" class="he-tab" style="flex:1;padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px 6px 0 0;background:#f1f5f9;cursor:pointer;font-size:12px;font-family:inherit;color:#64748b">テーマ</button>
        </div>
      </div>
      <div id="he-body" style="flex:1;overflow-y:auto;padding:12px 14px"></div>
      <div id="he-foot" style="display:flex;gap:6px;padding:10px 14px;border-top:1px solid #cbd5e1;background:#fff">
        <button id="he-copy" style="flex:1;padding:8px;border:none;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;font-family:inherit;font-size:12px;font-weight:600">📋 パッチをコピー</button>
        <button id="he-reset" title="全変更を元に戻す" style="padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;font-family:inherit;font-size:12px">↺</button>
      </div>
    `;
    setTimeout(()=>{
      p.querySelector('#he-toggle').addEventListener('click',()=>setEditing(!state.editing));
      p.querySelector('#he-copy').addEventListener('click',copyPatch);
      p.querySelector('#he-reset').addEventListener('click',resetAll);
      p.querySelectorAll('.he-tab').forEach(btn=>{
        btn.addEventListener('click',()=>{
          state.tab=btn.dataset.tab;
          syncTabUi();
          renderBody();
        });
      });
    },0);
    return p;
  }

  function syncTabUi(){
    panel.querySelectorAll('.he-tab').forEach(btn=>{
      const on=btn.dataset.tab===state.tab;
      btn.style.background=on?'#fff':'#f1f5f9';
      btn.style.color=on?'#0f172a':'#64748b';
      btn.style.fontWeight=on?'600':'400';
      btn.style.borderBottomColor=on?'#fff':'#cbd5e1';
    });
  }
  function renderBody(){
    const body=panel.querySelector('#he-body');
    if(!body)return;
    if(state.tab==='theme'){renderThemeTab(body);return}
    // Editタブ
    if(!state.editing){
      body.innerHTML=`<div style="color:#64748b;padding:16px 4px;line-height:1.6">
        右上「✏️ 編集」で編集モード開始。<br>要素をクリックすると編集項目が出ます。
      </div>`;return;
    }
    // 選択情報+peer情報 を Edit タブ内に表示
    let header=`<div style="font-family:ui-monospace,'SF Mono',monospace;font-size:11px;color:#64748b;padding:5px 8px;background:#f1f5f9;border-radius:4px;word-break:break-all;margin-bottom:8px">${state.sel?describeText(state.sel):'選択なし（左のHTMLで要素をクリック）'}</div>`
      +`<label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#475569;cursor:pointer;user-select:none;margin-bottom:12px;padding:6px 8px;background:#fff;border:1px solid #e2e8f0;border-radius:6px">
          <input type="checkbox" id="he-multi-cb" ${state.multiApply?'checked':''} style="cursor:pointer">
          <span>同じ種類の要素にまとめて適用</span>
          <span id="he-peer-count" style="margin-left:auto;font-family:ui-monospace,monospace;font-size:11px;color:#94a3b8"></span>
        </label>`;
    if(!state.sel){body.innerHTML=header;bindMultiCb();return}
    try{
      const el=state.sel;
      const cs=getComputedStyle(el);
      body.innerHTML=header+sectionsHtml(el,cs);
      bindMultiCb();
      body.querySelectorAll('[data-prop]').forEach(inp=>{
        inp.addEventListener('input',()=>applyInput(inp));
        inp.addEventListener('change',()=>applyInput(inp));
      });
      updatePeerCount(state.multiApply?getPeers(el).length:1);
    }catch(err){
      console.error('[HTMLEdit] renderBody error:',err);
      body.innerHTML=header+`<div style="color:#dc2626;padding:12px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;font-size:12px">パネル描画エラー: ${err.message}</div>`;
    }
  }
  function bindMultiCb(){
    const cb=panel.querySelector('#he-multi-cb');
    if(cb)cb.addEventListener('change',()=>{state.multiApply=cb.checked;updateMarker();if(state.sel)renderBody()});
  }
  function describeText(el){
    const tag=el.tagName.toLowerCase();
    const id=el.id?'#'+el.id:'';
    const cls=el.className&&typeof el.className==='string'?
      '.'+el.className.trim().split(/\s+/).slice(0,3).join('.'):'';
    const r=el.getBoundingClientRect();
    return `${tag}${id}${cls}  ${Math.round(r.width)}×${Math.round(r.height)}`;
  }

  const SVG_TAGS=new Set(['svg','path','line','rect','circle','ellipse','polyline','polygon','text','tspan','g','use']);
  function isSvg(el){return el&&el.namespaceURI==='http://www.w3.org/2000/svg'||(el&&SVG_TAGS.has(el.tagName.toLowerCase()))}

  function sectionsHtml(el,cs){
    if(isSvg(el)) return sectionsSvg(el);
    return [
      section('サイズ',[
        row('幅',    input('width',   cs.width,   'text','例: 320px / 100% / auto')),
        row('高さ',  input('height',  cs.height,  'text','例: 200px / auto')),
      ]),
      section('外側の余白 (margin)',[
        row('上',  input('marginTop',   cs.marginTop,   'text')),
        row('右',  input('marginRight', cs.marginRight, 'text')),
        row('下',  input('marginBottom',cs.marginBottom,'text')),
        row('左',  input('marginLeft',  cs.marginLeft,  'text')),
      ]),
      section('内側の余白 (padding)',[
        row('上',  input('paddingTop',   cs.paddingTop,   'text')),
        row('右',  input('paddingRight', cs.paddingRight, 'text')),
        row('下',  input('paddingBottom',cs.paddingBottom,'text')),
        row('左',  input('paddingLeft',  cs.paddingLeft,  'text')),
      ]),
      section('色',[
        row('文字色',   colorRow('color',           toHex(cs.color))),
        row('背景色',   colorRow('backgroundColor', toHex(cs.backgroundColor))),
        row('境界色',   colorRow('borderColor',     toHex(cs.borderColor||cs.borderTopColor))),
        row('境界幅',   input('borderWidth', cs.borderWidth,'text','例: 1px')),
      ]),
      section('文字',[
        row('サイズ',   input('fontSize',   cs.fontSize,   'text','例: 16px')),
        row('太さ',     selectField('fontWeight',cs.fontWeight, ['400','500','600','700','800'])),
        row('揃え',     selectField('textAlign', cs.textAlign,  ['left','center','right','justify'])),
        row('行の高さ', input('lineHeight', cs.lineHeight, 'text','例: 1.5')),
      ]),
      section('表示 (display / flex)',[
        row('display', selectField('display',cs.display,['block','inline-block','flex','grid','inline','none'])),
        row('flex方向', selectField('flexDirection',cs.flexDirection,['row','column','row-reverse','column-reverse'])),
        row('flex詰め', selectField('justifyContent',cs.justifyContent,['flex-start','center','flex-end','space-between','space-around'])),
        row('flex揃え', selectField('alignItems',cs.alignItems,['stretch','flex-start','center','flex-end','baseline'])),
        row('gap',      input('gap',cs.gap,'text','例: 12px')),
      ]),
    ].join('');
  }

  // ===== テーマタブ：画面全体で使われている色一覧 =====
  const IGNORE_HEX=new Set(['','#000000','#ffffff','#00000000']);
  function collectColorUsage(){
    // hex → { count, elements:[{el, prop}] }
    const map=new Map();
    const all=content.querySelectorAll('*');
    all.forEach(el=>{
      if(panel.contains(el))return;
      const cs=getComputedStyle(el);
      const specs=[
        {prop:'backgroundColor',rgb:cs.backgroundColor},
        {prop:'color',rgb:cs.color},
        {prop:'borderTopColor',rgb:cs.borderTopColor},
        {prop:'borderLeftColor',rgb:cs.borderLeftColor},
      ];
      // border は width が 0 の時は使ってないので除外
      if(parseFloat(cs.borderTopWidth||'0')<0.5){specs[2].rgb=null}
      if(parseFloat(cs.borderLeftWidth||'0')<0.5){specs[3].rgb=null}
      specs.forEach(s=>{
        if(!s.rgb)return;
        // 透明度0は無視
        const alphaMatch=s.rgb.match(/rgba?\([^)]*,\s*0(\.0+)?\s*\)/);
        if(alphaMatch)return;
        const hex=toHex(s.rgb);
        if(!hex||IGNORE_HEX.has(hex.toLowerCase()))return;
        if(!map.has(hex))map.set(hex,{count:0,elements:[]});
        const rec=map.get(hex);
        rec.count++;
        if(rec.elements.length<50)rec.elements.push({el,prop:s.prop});
      });
    });
    return map;
  }
  // SVGのfill/strokeも拾う
  function collectSvgColorUsage(map){
    content.querySelectorAll('svg *').forEach(el=>{
      if(panel.contains(el))return;
      ['fill','stroke'].forEach(prop=>{
        const v=el.getAttribute(prop)||getComputedStyle(el)[prop];
        if(!v||v==='none')return;
        const hex=toHex(v);
        if(!hex||IGNORE_HEX.has(hex.toLowerCase()))return;
        if(!map.has(hex))map.set(hex,{count:0,elements:[]});
        const rec=map.get(hex);
        rec.count++;
        if(rec.elements.length<50)rec.elements.push({el,prop});
      });
    });
    return map;
  }
  // 対象HTMLのテーマ切替UI（<select data-role="theme">）を優先。
  //   → 表示名(A案｜...)と値(themeA等)がそのまま拾える。切替もReactに任せる
  //   フォールバック: CSSの body.XXX セレクタから自動検出
  const THEME_IGNORE=/^(font-|panning|panning-active|open|hidden|active|visible|disabled)/;
  function findThemeSelect(){
    return document.querySelector('select[data-role="theme"]')
        || document.querySelector('select[data-theme]');
  }
  function detectThemes(){
    // 優先: 対象HTMLの既存selectを使う
    const sel=findThemeSelect();
    if(sel){
      return Array.from(sel.options).map(o=>({id:o.value,name:(o.textContent||o.value).trim()}));
    }
    // フォールバック: CSSから拾う
    const themes=[];
    const seen=new Set();
    for(const sheet of document.styleSheets){
      let rules;
      try{rules=sheet.cssRules}catch(e){continue}
      if(!rules)continue;
      for(const r of rules){
        const s=r.selectorText;if(!s)continue;
        const m=s.match(/^body\.([\w-]+)/);
        if(!m)continue;
        const cls=m[1];
        if(THEME_IGNORE.test(cls))continue;
        if(seen.has(cls))continue;
        seen.add(cls);
        themes.push({id:cls,name:cls});
      }
    }
    return themes;
  }
  function currentTheme(){
    const sel=findThemeSelect();
    if(sel)return sel.value||'';
    const themes=detectThemes();
    for(const t of themes){
      if(t.id&&document.body.classList.contains(t.id))return t.id;
    }
    return '';
  }
  function applyTheme(themeCls){
    const sel=findThemeSelect();
    if(sel){
      // 既存selectのvalue更新 → React onChangeが動いて class切替＋localStorage同期
      sel.value=themeCls;
      sel.dispatchEvent(new Event('change',{bubbles:true}));
    }else{
      // フォールバック: 直接class操作
      detectThemes().forEach(t=>t.id&&document.body.classList.remove(t.id));
      if(themeCls)document.body.classList.add(themeCls);
      try{window.dispatchEvent(new Event('themechange'))}catch(e){}
    }
    // React再render完了を少し待ってパレット再描画
    setTimeout(()=>{
      const b=panel.querySelector('#he-body');
      if(b&&state.tab==='theme')renderThemeTab(b);
    },250);
  }

  function renderThemeTab(body){
    const themes=detectThemes();
    const cur=currentTheme();
    const useHtmlSelect=!!findThemeSelect();
    const themeHtml=themes.length
      ? `<div style="margin-bottom:12px;padding:10px;background:#eef5fc;border:1px solid #bfd5ec;border-radius:6px">
          <div style="font-size:11px;font-weight:700;color:#00479D;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px">テーマ切替</div>
          <select id="he-theme-select" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:5px;font-size:12px;font-family:inherit;background:#fff">
            ${useHtmlSelect?'':'<option value="">（デフォルト）</option>'}
            ${themes.map(t=>`<option value="${t.id}" ${t.id===cur?'selected':''}>${t.name}</option>`).join('')}
          </select>
          <div style="font-size:11px;color:#64748b;margin-top:6px">テーマを切替えると下のパレットも自動で更新されます</div>
        </div>`
      : '';
    body.innerHTML=themeHtml+`<div style="color:#64748b;padding:8px 4px 4px;line-height:1.5;font-size:12px">
      画面全体で使われている色の一覧です。<br>
      色を変えると使用箇所がまとめて置換されます。件数クリックで対象要素をハイライト。
    </div>
    <div id="he-theme-list" style="display:flex;flex-direction:column;gap:6px"></div>`;
    const sel=body.querySelector('#he-theme-select');
    if(sel)sel.addEventListener('change',()=>applyTheme(sel.value));
    const list=body.querySelector('#he-theme-list');
    if(!list)return;
    let map=collectColorUsage();
    map=collectSvgColorUsage(map);
    const entries=Array.from(map.entries()).sort((a,b)=>b[1].count-a[1].count).slice(0,30);
    if(!entries.length){list.innerHTML='<div style="color:#94a3b8;padding:8px">色が見つかりませんでした</div>';return}
    entries.forEach(([hex,rec])=>{
      const row=document.createElement('div');
      row.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 8px;background:#fff;border:1px solid #e2e8f0;border-radius:6px';
      row.innerHTML=`
        <input type="color" value="${hex}" style="width:32px;height:26px;padding:0;border:1px solid #cbd5e1;border-radius:5px;cursor:pointer;background:#fff">
        <input type="text" value="${hex}" style="flex:1;padding:4px 6px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;font-family:ui-monospace,monospace">
        <button title="使用箇所をハイライト" style="padding:3px 8px;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc;color:#475569;font-size:11px;cursor:pointer;font-family:inherit;font-variant-numeric:tabular-nums;min-width:44px">${rec.count}件</button>
      `;
      const picker=row.querySelector('input[type=color]');
      const text=row.querySelector('input[type=text]');
      const highlightBtn=row.querySelector('button');
      const apply=newColor=>{
        if(!/^#[0-9a-f]{3,8}$/i.test(newColor))return;
        picker.value=newColor.slice(0,7);
        text.value=newColor;
        rec.elements.forEach(({el,prop})=>{
          try{
            if(prop==='fill'||prop==='stroke'){
              el.setAttribute(prop,newColor);
              trackChange(el,prop,newColor);
            }else{
              el.style[prop]=newColor;
              trackChange(el,prop,newColor);
            }
          }catch(err){}
        });
      };
      picker.addEventListener('input',()=>apply(picker.value));
      text.addEventListener('change',()=>apply(text.value.trim()));
      highlightBtn.addEventListener('click',()=>highlightColorUsage(rec.elements));
      list.appendChild(row);
    });
  }
  // 一時的なピカピカハイライト（3秒で消える）
  function highlightColorUsage(elements){
    // 既存の一時ハイライトを消去
    document.querySelectorAll('.he-color-flash').forEach(m=>m.remove());
    elements.forEach(({el})=>{
      const r=el.getBoundingClientRect();
      if(r.width<=0||r.height<=0)return;
      const m=document.createElement('div');
      m.className='he-color-flash';
      m.style.cssText=`position:fixed;pointer-events:none;box-shadow:0 0 0 2px #ec4899,0 0 12px rgba(236,72,153,0.5);border-radius:2px;z-index:2147483643;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;animation:hePulse 0.6s ease-in-out 3;`;
      document.body.appendChild(m);
      setTimeout(()=>m.remove(),2500);
    });
  }
  // アニメーション CSS を1度だけ挿入
  if(!document.getElementById('he-anim-style')){
    const st=document.createElement('style');
    st.id='he-anim-style';
    st.textContent='@keyframes hePulse{0%,100%{opacity:1}50%{opacity:0.4}}';
    document.head.appendChild(st);
  }

  // SVG専用の編集項目
  function sectionsSvg(el){
    const attr=(k,fallback)=>el.getAttribute(k)||el.style[k]||fallback||'';
    const cs=getComputedStyle(el);
    const fillCur=toHex(attr('fill','')||cs.fill);
    const strokeCur=toHex(attr('stroke','')||cs.stroke);
    return [
      `<div style="background:#fef3c7;color:#78350f;padding:6px 10px;border-radius:6px;margin-bottom:10px;font-size:11px">SVG要素: <b>${el.tagName.toLowerCase()}</b> — style ではなく属性で編集します</div>`,
      section('色（塗り/線）',[
        row('塗り fill',   colorRow('fill', fillCur||'#000000')),
        row('線 stroke',   colorRow('stroke', strokeCur||'#000000')),
        row('線の幅',      input('stroke-width', attr('stroke-width',cs.strokeWidth||'1'), 'text','例: 2')),
        row('不透明度',    input('opacity', attr('opacity',cs.opacity||'1'), 'text','0〜1')),
      ]),
      section('文字（textの場合）',[
        row('font-size',   input('font-size', attr('font-size',cs.fontSize), 'text','例: 12px')),
        row('font-weight', selectField('font-weight', attr('font-weight',cs.fontWeight), ['normal','bold','400','500','600','700','800'])),
        row('揃え',        selectField('text-anchor', attr('text-anchor','start'), ['start','middle','end'])),
      ]),
      section('サイズ・位置（rect/circle等）',[
        row('width',  input('width',  attr('width',''),  'text')),
        row('height', input('height', attr('height',''), 'text')),
        row('x',      input('x',      attr('x',''),      'text')),
        row('y',      input('y',      attr('y',''),      'text')),
        row('r',      input('r',      attr('r',''),      'text','円のみ')),
      ]),
    ].join('');
  }
  function section(title,rows){
    return `<div style="margin-bottom:14px">
      <div style="font-size:11px;font-weight:700;color:#64748b;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px">${title}</div>
      ${rows.join('')}
    </div>`;
  }
  function row(label,control){
    return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
      <label style="width:88px;color:#475569;font-size:12px">${label}</label>
      <div style="flex:1">${control}</div>
    </div>`;
  }
  function input(prop,value,type,placeholder){
    return `<input type="${type||'text'}" data-prop="${prop}" value="${escapeAttr(String(value||''))}" placeholder="${placeholder||''}" style="width:100%;padding:5px 8px;border:1px solid #cbd5e1;border-radius:5px;font-size:12px;font-family:inherit;background:#fff">`;
  }
  function selectField(prop,value,options){
    const opts=options.map(o=>`<option value="${o}" ${value===o?'selected':''}>${o}</option>`).join('');
    return `<select data-prop="${prop}" style="width:100%;padding:5px 8px;border:1px solid #cbd5e1;border-radius:5px;font-size:12px;font-family:inherit;background:#fff">${opts}</select>`;
  }
  function colorRow(prop,hex){
    const safe=hex||'#000000';
    return `<div style="display:flex;gap:6px">
      <input type="color" data-prop="${prop}" data-color-picker="1" value="${safe}" style="width:36px;height:26px;padding:0;border:1px solid #cbd5e1;border-radius:5px;cursor:pointer;background:#fff">
      <input type="text" data-prop="${prop}" value="${safe}" style="flex:1;padding:5px 8px;border:1px solid #cbd5e1;border-radius:5px;font-size:12px;font-family:ui-monospace,monospace">
    </div>`;
  }

  // ===== 3) 選択・ハイライト =====
  function setEditing(on){
    state.editing=on;
    const btn=panel.querySelector('#he-toggle');
    if(on){
      btn.textContent='✏️ 編集中';
      btn.style.background='#2563eb';btn.style.color='#fff';btn.style.borderColor='#2563eb';
      document.body.style.cursor='pointer';
    }else{
      btn.textContent='✏️ 編集';
      btn.style.background='#fff';btn.style.color='#1e293b';btn.style.borderColor='#cbd5e1';
      document.body.style.cursor='';
      clearSelection();
    }
    renderBody();
  }

  // documentレベルで capture フェーズで受ける（本体HTML内の他のリスナより先に処理）
  document.addEventListener('click',e=>{
    if(!state.editing)return;
    let t=e.target;
    // パネル/マーカーは無視
    if(panel.contains(t)||t===marker)return;
    // contentの外は無視
    if(!content.contains(t))return;
    // linkの遷移などを止める
    e.preventDefault();e.stopPropagation();
    if(t===content)return;
    select(t);
    console.log('[HTMLEdit] selected:',t.tagName,t.className);
  },true);

  function select(el){
    // テキストノード等はElement親に上げる
    while(el&&el.nodeType!==1)el=el.parentNode;
    if(!el||typeof el.getBoundingClientRect!=='function')return;
    state.sel=el;
    updateMarker();
    renderBody();
  }
  function clearSelection(){
    state.sel=null;
    if(marker)marker.style.display='none';
  }
  function updateMarker(){
    const el=state.sel;
    // 既存 peer markers を除去
    state.peerMarkers.forEach(m=>m.remove());
    state.peerMarkers=[];
    if(!el||!marker){if(marker)marker.style.display='none';updatePeerCount(0);return}
    const r=el.getBoundingClientRect();
    marker.style.left=r.left+'px';marker.style.top=r.top+'px';
    marker.style.width=r.width+'px';marker.style.height=r.height+'px';
    marker.style.display='block';
    // peer marker
    const peers=state.multiApply?getPeers(el).filter(x=>x!==el):[];
    peers.forEach(p=>{
      const pr=p.getBoundingClientRect();
      if(pr.width<=0||pr.height<=0)return;
      const m=document.createElement('div');
      m.style.cssText=`position:fixed;pointer-events:none;outline:1.5px dashed #f59e0b;outline-offset:-1.5px;border-radius:2px;z-index:2147483644;left:${pr.left}px;top:${pr.top}px;width:${pr.width}px;height:${pr.height}px`;
      document.body.appendChild(m);
      state.peerMarkers.push(m);
    });
    updatePeerCount(peers.length+1);
  }
  function updatePeerCount(n){
    const el=panel.querySelector('#he-peer-count');
    if(!el)return;
    el.textContent=(state.sel&&state.multiApply&&n>1)?`${n}個`:'';
  }
  // 見た目シグネチャ（背景・文字・境界の色）
  function visualSignature(el){
    if(!el)return '';
    const cs=getComputedStyle(el);
    return [
      cs.backgroundColor,
      cs.color,
      cs.borderTopColor,cs.borderLeftColor,
      cs.borderTopWidth,cs.borderLeftWidth,
      cs.backgroundImage,
    ].join('|');
  }
  // 同種要素判定:
  //   兄弟優先（同じ親・同tag）＋ 見た目シグネチャ一致 で絞る
  //   → セグメントタブなら「同状態の兄弟のみ」が仲間になる（例: アクティブは単独、非アクティブ3個で1グループ）
  //   兄弟にヒットが少ない or 単独なら、className完全一致にフォールバック
  function getPeers(el){
    if(!el||!el.tagName)return [el];
    const baseSig=visualSignature(el);
    // 兄弟優先（同一見た目のみ）
    if(el.parentElement&&!panel.contains(el.parentElement)){
      const siblings=Array.from(el.parentElement.children)
        .filter(x=>x.tagName===el.tagName)
        .filter(x=>!panel.contains(x)&&x!==marker)
        .filter(x=>visualSignature(x)===baseSig);
      if(siblings.length>=2&&siblings.length<=30)return siblings;
      if(siblings.length===1)return siblings; // 自分だけ
    }
    // フォールバック: className完全一致
    const tag=el.tagName.toLowerCase();
    const cls=(el.className&&typeof el.className==='string')?el.className.trim():'';
    let list;
    if(!cls){
      list=Array.from(document.querySelectorAll(tag));
    }else{
      const clsEsc=cls.split(/\s+/).map(c=>'.'+CSS.escape(c)).join('');
      list=Array.from(document.querySelectorAll(tag+clsEsc));
      list=list.filter(x=>{
        const c=(x.className&&typeof x.className==='string')?x.className.trim():'';
        return c===cls;
      });
    }
    list=list.filter(x=>!panel.contains(x)&&x!==marker);
    list=list.filter(x=>visualSignature(x)===baseSig);
    return list;
  }
  content.addEventListener('scroll',updateMarker,true);
  window.addEventListener('resize',updateMarker);
  window.addEventListener('scroll',updateMarker,true);

  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){if(state.sel){clearSelection();renderBody()}}
    if((e.metaKey||e.ctrlKey)&&e.key==='z'){e.preventDefault();undoLast()}
  });

  // ===== 4) 値変更 =====
  function applyInput(inp){
    if(!state.sel)return;
    const prop=inp.dataset.prop;
    let val=inp.value;
    if(!val)return;
    // color picker & hex text の連動
    if(inp.dataset.colorPicker){
      const twin=inp.parentElement.querySelector('input[type=text][data-prop="'+prop+'"]');
      if(twin)twin.value=val;
    }else if(inp.type==='text'&&/^#[0-9a-f]{3,8}$/i.test(val)){
      const twin=inp.parentElement.querySelector('input[type=color][data-prop="'+prop+'"]');
      if(twin)twin.value=val.length===7?val:val.slice(0,7);
    }
    const targets=state.multiApply?getPeers(state.sel):[state.sel];
    targets.forEach(t=>{
      trackChange(t,prop,val);
      try{
        if(isSvg(t)){
          t.setAttribute(prop,val);
        }else{
          t.style[prop]=val;
        }
      }catch(err){}
    });
    updateMarker();
  }
  function trackChange(el,prop,val){
    if(!state.origStyle.has(el))state.origStyle.set(el,el.getAttribute('style')||'');
    if(!state.changes.has(el)){
      state.changes.set(el,{selector:cssPath(el),before:{},after:{}});
    }
    const c=state.changes.get(el);
    if(!(prop in c.before)){
      const cs=getComputedStyle(el);
      c.before[prop]=cs[prop]||'';
    }
    c.after[prop]=val;
  }

  // ===== 5) パッチ生成 =====
  function copyPatch(){
    if(!state.changes.size){alert('変更がありません');return}
    const lines=['# SlideKit HTML Edit パッチ',''];
    state.changes.forEach((c,el)=>{
      lines.push(`## ${c.selector}`);
      Object.keys(c.after).forEach(prop=>{
        if(c.before[prop]===c.after[prop])return;
        lines.push(`  ${cssProp(prop)}: ${c.before[prop]} → ${c.after[prop]}`);
      });
      lines.push('');
    });
    const text=lines.join('\n');
    navigator.clipboard.writeText(text).then(()=>{
      alert('パッチをコピーしました\n\nKiroに貼り付けて反映を依頼してください。');
    }).catch(()=>{
      prompt('パッチ（Cmd+Cでコピー）:',text);
    });
  }
  function resetAll(){
    if(!state.changes.size){alert('変更がありません');return}
    if(!confirm('全ての変更を元に戻しますか?'))return;
    state.changes.forEach((c,el)=>{
      const s=state.origStyle.get(el)||'';
      el.setAttribute('style',s);
    });
    state.changes.clear();
    state.origStyle.clear();
    updateMarker();renderBody();
  }
  function undoLast(){
    // MVPでは last change 1つだけ戻す（全反転はresetAllで）
    if(!state.changes.size)return;
    let lastEl=null;let lastKey=null;
    state.changes.forEach((c,el)=>{
      const keys=Object.keys(c.after);
      if(keys.length){lastEl=el;lastKey=keys[keys.length-1]}
    });
    if(!lastEl)return;
    const c=state.changes.get(lastEl);
    lastEl.style[lastKey]=c.before[lastKey]||'';
    delete c.after[lastKey];
    if(!Object.keys(c.after).length)state.changes.delete(lastEl);
    if(state.sel===lastEl)renderBody();
    updateMarker();
  }

  // ===== 6) セレクタ生成 =====
  function cssPath(el){
    if(el.id)return `#${el.id}`;
    const parts=[];
    let cur=el;
    for(let i=0;i<6&&cur&&cur!==content&&cur!==document.body;i++){
      let s=cur.tagName.toLowerCase();
      if(cur.className&&typeof cur.className==='string'){
        const cls=cur.className.trim().split(/\s+/).filter(c=>!c.startsWith('he-')&&c).slice(0,2);
        if(cls.length)s+='.'+cls.join('.');
      }
      const siblings=Array.from(cur.parentNode.children).filter(x=>x.tagName===cur.tagName);
      if(siblings.length>1){
        const idx=siblings.indexOf(cur)+1;
        s+=`:nth-of-type(${idx})`;
      }
      parts.unshift(s);
      cur=cur.parentNode;
    }
    return parts.join(' > ');
  }
  function describe(el){
    const tag=el.tagName.toLowerCase();
    const id=el.id?'#'+el.id:'';
    const cls=el.className&&typeof el.className==='string'?
      '.'+el.className.trim().split(/\s+/).slice(0,3).join('.'):'';
    const r=el.getBoundingClientRect();
    return `${tag}${id}${cls}  <span style="color:#64748b">${Math.round(r.width)}×${Math.round(r.height)}</span>`;
  }
  function cssProp(camel){return camel.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}
  function escapeAttr(s){return s.replace(/"/g,'&quot;')}
  function toHex(rgb){
    if(!rgb)return '';
    if(rgb.startsWith('#'))return rgb.length===7?rgb:rgb.slice(0,7);
    const m=rgb.match(/rgba?\(([^)]+)\)/);
    if(!m)return '';
    const parts=m[1].split(',').map(x=>parseFloat(x.trim()));
    if(parts.length<3)return '';
    return '#'+parts.slice(0,3).map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');
  }

  // 初回描画
  renderBody();
}
})();
