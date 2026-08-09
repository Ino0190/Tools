// CalcKit エンジン — 表計算（式・書式・入出力・キット連携）
// evalは使わない（式は自前のトークナイザ＋Prattパーサで評価）
(function(){
'use strict';

// ==== アドレス変換 ====
function colName(i){ let s=''; i++; while(i>0){ i--; s=String.fromCharCode(65+i%26)+s; i=Math.floor(i/26);} return s; }
function colIndex(name){ let n=0; for(const ch of name) n=n*26+(ch.charCodeAt(0)-64); return n-1; }
function addrOf(r,c){ return colName(c)+(r+1); }
const REF_RE=/(\$?)([A-Z]+)(\$?)([0-9]+)/g;
function parseAddr(a){ const m=/^(\$?)([A-Z]+)(\$?)([0-9]+)$/.exec(a); if(!m) return null;
  return {c:colIndex(m[2]), r:parseInt(m[4],10)-1, absC:m[1]==='$', absR:m[3]==='$'}; }

// ==== ドキュメント（マルチシート） ====
const STORAGE_KEY='calckit_v1';
let doc=null;           // {name, sheets:[{name,rows,cols,colW,rowH,cells:{addr:{v,fmt,..}}}], active}
let vals={};            // 計算結果 "シートindex!addr" -> number|string|{e:'#..'}
let cur={r:0,c:0};      // カーソル
let selA=null;          // 選択アンカー {r,c}（nullなら単一セル）
let undoStack=[], redoStack=[];
let dirty=false;

function newSheet(name,rows,cols){ return {name:name||'シート1',rows:rows||50,cols:cols||26,colW:{},rowH:{},cells:{}}; }
function newDoc(name,rows,cols){ return {name:name||'新しいシート',sheets:[newSheet('シート1',rows,cols)],active:0}; }
function sheet(){ return doc.sheets[doc.active]; }
function sheetIdx(name){ // シート名→index（大文字小文字を区別しない）。無ければ-1
  const t=String(name).toLowerCase();
  return doc.sheets.findIndex(s=>s.name.toLowerCase()===t);
}
const V=a=>vals[doc.active+'!'+a];    // 表示側: アクティブシートの計算結果
function normalizeDoc(d){ // 旧形式（単一シート）→ sheets形式へ移行
  if(d.sheets){ d.active=Math.min(d.active||0,d.sheets.length-1);
    d.sheets.forEach(s=>{ s.colW=s.colW||{}; s.rowH=s.rowH||{}; s.cells=s.cells||{}; }); return d; }
  return {name:d.name||'シート',active:0,
    sheets:[{name:'シート1',rows:d.rows||50,cols:d.cols||26,colW:d.colW||{},rowH:d.rowH||{},cells:d.cells||{}}]};
}
function cell(a){ return sheet().cells[a]; }
function rawOf(a){ const c=sheet().cells[a]; return c? (c.v??'') : ''; }
function canonFormula(f){ // 引用符の外だけ大文字化（参照・関数名の正規化。文字列は保持）
  let out='',q=false;
  for(const ch of f){ if(ch==='"'){ q=!q; out+=ch; } else out+=q?ch:ch.toUpperCase(); }
  return out;
}
function setRaw(a,v){
  const cs=sheet().cells;
  if(v===''||v==null){ const c=cs[a]; if(c){ delete c.v; cleanCell(a); } return; }
  let s=String(v);
  if(s[0]==='=') s='='+canonFormula(s.slice(1));
  (cs[a]||(cs[a]={})).v=s;
}

// ==== 式トークナイザ ====
function tokenize(src){
  const toks=[]; let i=0;
  while(i<src.length){
    const ch=src[i];
    if(ch===' '){ i++; continue; }
    if(/[0-9.]/.test(ch)){ let j=i; while(j<src.length&&/[0-9.]/.test(src[j]))j++;
      toks.push({t:'num',v:parseFloat(src.slice(i,j))}); i=j; continue; }
    if(ch==='"'){ let j=i+1,s=''; while(j<src.length&&src[j]!=='"'){ s+=src[j]; j++; }
      toks.push({t:'str',v:s}); i=j+1; continue; }
    if(src.slice(i,i+5)==='#REF!'){ toks.push({t:'err',v:'#REF!'}); i+=5; continue; }
    if(ch==="'"){ // 'シート名'!A1（スペース等を含むシート名）
      let j=i+1,nm=''; while(j<src.length&&src[j]!=="'"){ nm+=src[j]; j++; }
      if(src[j]!=="'"||src[j+1]!=='!') throw {e:'#NAME?'};
      j+=2;
      const m=/^(\$?[A-Z]+\$?[0-9]+)/.exec(src.slice(j));
      if(!m) throw {e:'#NAME?'};
      toks.push({t:'ref',v:m[1],sheet:nm}); i=j+m[1].length; continue; }
    if(/[A-Za-z$_\u00C0-\uFFFF]/.test(ch)){ // 識別子（日本語シート名も可）
      let j=i; while(j<src.length&&/[A-Za-z0-9_.$\u00C0-\uFFFF]/.test(src[j]))j++;
      const w=src.slice(i,j);
      if(src[j]==='!'){ // シート名!A1
        const m=/^(\$?[A-Z]+\$?[0-9]+)/.exec(src.slice(j+1));
        if(!m) throw {e:'#NAME?'};
        toks.push({t:'ref',v:m[1],sheet:w}); i=j+1+m[1].length; continue; }
      const W=w.toUpperCase();
      if(parseAddr(W)) toks.push({t:'ref',v:W});
      else toks.push({t:'name',v:W});
      i=j; continue; }
    if(ch==='<'&&src[i+1]==='>'){ toks.push({t:'op',v:'<>'}); i+=2; continue; }
    if((ch==='<'||ch==='>')&&src[i+1]==='='){ toks.push({t:'op',v:ch+'='}); i+=2; continue; }
    if('+-*/^&%(),:=<>'.includes(ch)){ toks.push({t:'op',v:ch}); i++; continue; }
    throw {e:'#NAME?'};
  }
  return toks;
}

// ==== Prattパーサ ====
// 優先順位: 比較1 < &2 < +-3 < */4 < ^5(右結合) < 単項-6 < 後置%7
function parseFormula(src){
  const toks=tokenize(src); let p=0;
  function peek(){ return toks[p]; }
  function next(){ return toks[p++]; }
  function parseExpr(minBp){
    let lhs=parsePrimary();
    for(;;){
      const t=peek(); if(!t||t.t!=='op') break;
      const v=t.v;
      if(v==='%'){ next(); lhs={n:'pct',a:lhs}; continue; }
      const bp={'=':1,'<>':1,'<':1,'>':1,'<=':1,'>=':1,'&':2,'+':3,'-':3,'*':4,'/':4,'^':5}[v];
      if(bp===undefined||bp<minBp) break;
      next();
      const rhs=parseExpr(v==='^'?bp:bp+1);
      lhs={n:'bin',op:v,a:lhs,b:rhs};
    }
    return lhs;
  }
  function parsePrimary(){
    const t=next(); if(!t) throw {e:'#NAME?'};
    if(t.t==='num') return {n:'num',v:t.v};
    if(t.t==='str') return {n:'str',v:t.v};
    if(t.t==='err') throw {e:t.v};
    if(t.t==='ref'){
      if(peek()&&peek().t==='op'&&peek().v===':'){ next(); const t2=next();
        if(!t2||t2.t!=='ref') throw {e:'#NAME?'};
        return {n:'range',a:t.v,b:t2.v,s:t.sheet||null}; }
      return {n:'ref',v:t.v,s:t.sheet||null};
    }
    if(t.t==='name'){
      if(t.v==='TRUE') return {n:'num',v:1};
      if(t.v==='FALSE') return {n:'num',v:0};
      if(peek()&&peek().t==='op'&&peek().v==='('){ next();
        const args=[];
        if(peek()&&!(peek().t==='op'&&peek().v===')')){
          args.push(parseExpr(0));
          while(peek()&&peek().t==='op'&&peek().v===','){ next(); args.push(parseExpr(0)); }
        }
        const cl=next(); if(!cl||cl.v!==')') throw {e:'#NAME?'};
        return {n:'call',f:t.v,args:args};
      }
      throw {e:'#NAME?'};
    }
    if(t.t==='op'&&t.v==='('){ const e=parseExpr(0); const cl=next();
      if(!cl||cl.v!==')') throw {e:'#NAME?'}; return e; }
    if(t.t==='op'&&t.v==='-') return {n:'neg',a:parseExpr(6)};
    if(t.t==='op'&&t.v==='+') return parseExpr(6);
    throw {e:'#NAME?'};
  }
  const ast=parseExpr(0);
  if(p<toks.length) throw {e:'#NAME?'};
  return ast;
}
const astCache=new Map();

// ==== 評価 ====
function isErr(v){ return v&&typeof v==='object'&&v.e; }
function toNum(v){
  if(isErr(v)) return v;
  if(typeof v==='number') return v;
  if(v==null||v==='') return 0;
  const n=parseFloat(String(v).replace(/[,¥\s]/g,''));
  return isNaN(n)? {e:'#VALUE!'} : n;
}
function rangeAddrs(a,b){
  const A=parseAddr(a),B=parseAddr(b); const out=[];
  for(let r=Math.min(A.r,B.r);r<=Math.max(A.r,B.r);r++)
    for(let c=Math.min(A.c,B.c);c<=Math.max(A.c,B.c);c++) out.push(addrOf(r,c));
  return out;
}
function numsOf(list){ // 範囲/引数リスト→数値のみ（Excel流: 文字列・空は無視）
  const out=[];
  for(const v of list){ if(isErr(v)) return v;
    if(typeof v==='number') out.push(v); }
  return out;
}
function matchCrit(v,crit){ // SUMIF/COUNTIF条件: ">=5" "<>x" "5" "文字列"
  const s=String(crit); const m=/^(<>|<=|>=|<|>|=)(.*)$/.exec(s);
  const op=m?m[1]:'='; const rhs=m?m[2]:s;
  const rn=parseFloat(rhs); const vn=(typeof v==='number')?v:parseFloat(v);
  if(!isNaN(rn)&&!isNaN(vn)){
    if(op==='=')return vn===rn; if(op==='<>')return vn!==rn;
    if(op==='<')return vn<rn; if(op==='>')return vn>rn;
    if(op==='<=')return vn<=rn; return vn>=rn;
  }
  const vs=String(v??''); if(op==='<>')return vs!==rhs; return vs===rhs;
}
const FUNCS={
  SUM:a=>{ const n=numsOf(a); return isErr(n)?n:n.reduce((s,x)=>s+x,0); },
  AVERAGE:a=>{ const n=numsOf(a); if(isErr(n))return n; return n.length? n.reduce((s,x)=>s+x,0)/n.length : {e:'#DIV/0!'}; },
  MIN:a=>{ const n=numsOf(a); return isErr(n)?n:(n.length?Math.min(...n):0); },
  MAX:a=>{ const n=numsOf(a); return isErr(n)?n:(n.length?Math.max(...n):0); },
  COUNT:a=>{ const n=numsOf(a); return isErr(n)?n:n.length; },
  COUNTA:a=>a.filter(v=>v!==''&&v!=null).length,
  ABS:a=>{ const n=toNum(a[0]); return isErr(n)?n:Math.abs(n); },
  INT:a=>{ const n=toNum(a[0]); return isErr(n)?n:Math.floor(n); },
  SQRT:a=>{ const n=toNum(a[0]); return isErr(n)?n:(n<0?{e:'#VALUE!'}:Math.sqrt(n)); },
  ROUND:a=>{ const n=toNum(a[0]),d=toNum(a[1]??0); if(isErr(n))return n; if(isErr(d))return d;
    const k=Math.pow(10,d); return Math.round(n*k)/k; },
  ROUNDUP:a=>{ const n=toNum(a[0]),d=toNum(a[1]??0); if(isErr(n))return n; if(isErr(d))return d;
    const k=Math.pow(10,d); return Math.sign(n)*Math.ceil(Math.abs(n)*k)/k; },
  ROUNDDOWN:a=>{ const n=toNum(a[0]),d=toNum(a[1]??0); if(isErr(n))return n; if(isErr(d))return d;
    const k=Math.pow(10,d); return Math.sign(n)*Math.floor(Math.abs(n)*k)/k; },
  TODAY:()=>{ const d=new Date(); return dateToSerial(d.getFullYear(),d.getMonth()+1,d.getDate()); },
  DATE:a=>{ const y=toNum(a[0]),m=toNum(a[1]),d=toNum(a[2]);
    if(isErr(y))return y; if(isErr(m))return m; if(isErr(d))return d;
    return dateToSerial(y,m,d); },
  IF:null, SUMIF:null, COUNTIF:null // 特殊処理（下のevalNode内）
};

// ==== 日付（Excel互換シリアル値: 1899-12-30起点の日数） ====
const DATE_RE=/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})$/;
function dateToSerial(y,m,d){ return Math.round(Date.UTC(y,m-1,d)/86400000)+25569; }
function parseDateRaw(s){
  const m=DATE_RE.exec(String(s).trim()); if(!m) return null;
  const y=+m[1],mo=+m[2],d=+m[3];
  if(mo<1||mo>12||d<1||d>31) return null;
  const dt=new Date(Date.UTC(y,mo-1,d));
  if(dt.getUTCFullYear()!==y||dt.getUTCMonth()!==mo-1||dt.getUTCDate()!==d) return null;
  return dateToSerial(y,mo,d);
}
function serialToYMD(s){
  const dt=new Date(Math.round(s-25569)*86400000);
  return dt.getUTCFullYear()+'-'+String(dt.getUTCMonth()+1).padStart(2,'0')+'-'+String(dt.getUTCDate()).padStart(2,'0');
}

let busy=null; // 循環参照検出
function cellValue(a,si){
  const ad=a.replace(/\$/g,'');
  const key=si+'!'+ad;
  if(key in vals) return vals[key];
  if(busy.has(key)){ vals[key]={e:'#CYCLE!'}; return vals[key]; }
  busy.add(key);
  let v='';
  const cl=doc.sheets[si].cells[ad];
  const raw=cl? (cl.v??'') : '';
  if(raw!==''){
    if(raw[0]==='='){
      try{
        let ast=astCache.get(raw);
        if(!ast){ ast=parseFormula(raw.slice(1)); astCache.set(raw,ast); }
        v=evalNode(ast,si);
      }catch(ex){ v=ex&&ex.e? {e:ex.e} : {e:'#NAME?'}; }
    }else{
      const ds=parseDateRaw(raw);
      if(ds!=null) v=ds;
      else{
        const t=raw.trim();
        if(/^-?¥[\d,]+(\.\d+)?$/.test(t)||/^¥-?[\d,]+(\.\d+)?$/.test(t)){
          v=parseFloat(t.replace(/[¥,]/g,''));           // Excel表示値の「¥1,234」貼り付け
        }else if(/^-?[\d,]+(\.\d+)?%$/.test(t)){
          v=parseFloat(t.replace(/[,%]/g,''))/100;       // 「50%」→0.5
        }else{
          const n=parseFloat(raw.replace(/,/g,''));
          v=(String(n)===raw.replace(/,/g,'')||/^-?[0-9,]*\.?[0-9]+$/.test(raw))&&!isNaN(n)? n : raw;
        }
      }
    }
  }
  busy.delete(key);
  vals[key]=v; return v;
}
function resolveSheet(nd,si){ // 参照ノードのシート決定（プレフィックス無し=自シート）
  if(!nd.s) return si;
  const k=sheetIdx(nd.s);
  return k;
}
function evalNode(nd,si){
  switch(nd.n){
    case 'num': return nd.v;
    case 'str': return nd.v;
    case 'ref': { const k=resolveSheet(nd,si); return k<0? {e:'#REF!'} : cellValue(nd.v,k); }
    case 'range': { const k=resolveSheet(nd,si); return k<0? {e:'#REF!'} : {rng:rangeAddrs(nd.a,nd.b),si:k}; }
    case 'neg': { const v=toNum(evalScalar(nd.a,si)); return isErr(v)?v:-v; }
    case 'pct': { const v=toNum(evalScalar(nd.a,si)); return isErr(v)?v:v/100; }
    case 'bin': return evalBin(nd,si);
    case 'call': return evalCall(nd,si);
  }
  return {e:'#NAME?'};
}
function evalScalar(nd,si){ const v=evalNode(nd,si); return (v&&v.rng)? {e:'#VALUE!'} : v; }
function flatten(nd,si){ // 引数→値の配列（範囲は展開）
  const v=evalNode(nd,si);
  if(v&&v.rng) return v.rng.map(x=>cellValue(x,v.si));
  return [v];
}
function evalBin(nd,si){
  const op=nd.op;
  const a=evalScalar(nd.a,si), b=evalScalar(nd.b,si);
  if(op==='&'){ if(isErr(a))return a; if(isErr(b))return b;
    return displayVal(a)+displayVal(b); }
  if(['=','<>','<','>','<=','>='].includes(op)){
    if(isErr(a))return a; if(isErr(b))return b;
    let r;
    if(typeof a==='number'&&typeof b==='number'){ r={'=':a===b,'<>':a!==b,'<':a<b,'>':a>b,'<=':a<=b,'>=':a>=b}[op]; }
    else { const as=String(a??''),bs=String(b??''); r={'=':as===bs,'<>':as!==bs,'<':as<bs,'>':as>bs,'<=':as<=bs,'>=':as>=bs}[op]; }
    return r?1:0;
  }
  const x=toNum(a),y=toNum(b);
  if(isErr(x))return x; if(isErr(y))return y;
  if(op==='+')return x+y; if(op==='-')return x-y; if(op==='*')return x*y;
  if(op==='/')return y===0? {e:'#DIV/0!'} : x/y;
  if(op==='^')return Math.pow(x,y);
  return {e:'#NAME?'};
}

function evalCall(nd,si){
  const f=nd.f;
  if(f==='VLOOKUP'||f==='HLOOKUP'){
    // VLOOKUP(キー, 範囲, 何列目, [近似]) 近似省略時=TRUE（Excel互換・昇順前提）。0/FALSEで完全一致
    const key=evalScalar(nd.args[0],si); if(isErr(key))return key;
    const rg=nd.args[1]; if(!rg||rg.n!=='range') return {e:'#VALUE!'};
    const rsi=resolveSheet(rg,si); if(rsi<0) return {e:'#REF!'};
    const A=parseAddr(rg.a),B=parseAddr(rg.b);
    const r1=Math.min(A.r,B.r),r2=Math.max(A.r,B.r),c1=Math.min(A.c,B.c),c2=Math.max(A.c,B.c);
    const idx=toNum(evalScalar(nd.args[2]??{n:'num',v:1},si)); if(isErr(idx))return idx;
    let approx=true;
    if(nd.args[3]!=null){ const t=evalScalar(nd.args[3],si); if(isErr(t))return t; approx=toNum(t)!==0; }
    const vert=(f==='VLOOKUP');
    if(idx<1||idx>(vert? c2-c1+1 : r2-r1+1)) return {e:'#VALUE!'};
    const n=vert? r2-r1 : c2-c1;
    const keyAt=i=>cellValue(addrOf(vert? r1+i : r1, vert? c1 : c1+i),rsi);
    const valAt=i=>cellValue(addrOf(vert? r1+i : r1+idx-1, vert? c1+idx-1 : c1+i),rsi);
    const ks=(typeof key==='string')? key.toLowerCase() : key;
    let best=-1;
    for(let i=0;i<=n;i++){
      const kv=keyAt(i); if(isErr(kv)) continue;
      if(typeof kv==='string'&&typeof key==='string'){
        if(kv.toLowerCase()===ks) return valAt(i);
        if(approx&&kv.toLowerCase()<=ks) best=i;
      }else if(typeof kv==='number'&&typeof key==='number'){
        if(kv===key) return valAt(i);
        if(approx&&kv<=key) best=i;
      }
    }
    return (approx&&best>=0)? valAt(best) : {e:'#N/A'};
  }
  if(f==='IF'){
    const c=toNum(evalScalar(nd.args[0],si)); if(isErr(c))return c;
    return c!==0? evalScalar(nd.args[1]??{n:'num',v:0},si) : evalScalar(nd.args[2]??{n:'num',v:0},si);
  }
  if(f==='SUMIF'||f==='COUNTIF'){
    const rv=evalNode(nd.args[0],si); if(!rv||!rv.rng) return {e:'#VALUE!'};
    const crit=evalScalar(nd.args[1],si); if(isErr(crit))return crit;
    let sumRng=rv.rng, sumSi=rv.si;
    if(f==='SUMIF'&&nd.args[2]){ const sv=evalNode(nd.args[2],si); if(!sv||!sv.rng)return {e:'#VALUE!'};
      sumRng=sv.rng; sumSi=sv.si; }
    let acc=0,cnt=0;
    for(let i=0;i<rv.rng.length;i++){
      const v=cellValue(rv.rng[i],rv.si);
      if(isErr(v))return v;
      if(matchCrit(v,crit)){ cnt++;
        if(f==='SUMIF'){ const s=cellValue(sumRng[i]??rv.rng[i],sumSi); if(typeof s==='number') acc+=s; } }
    }
    return f==='SUMIF'? acc : cnt;
  }
  const fn=FUNCS[f];
  if(!fn) return {e:'#NAME?'};
  const args=[];
  for(const a of nd.args) args.push(...flatten(a,si));
  return fn(args);
}
function recalc(){ vals={}; busy=new Set();
  for(let si=0;si<doc.sheets.length;si++){
    const cs=doc.sheets[si].cells;
    for(const a in cs) if(cs[a].v!=null) cellValue(a,si);
  }
}

// ==== 表示 ====
function displayVal(v){
  if(v==null||v==='') return '';
  if(isErr(v)) return v.e;
  return String(v);
}
function fmtNum(n,fmt){
  const sep=x=>{ const p=x.toFixed(Math.abs(x)>=1||x===0? (Number.isInteger(x)?0:2) :4).split('.');
    p[0]=p[0].replace(/\B(?=(\d{3})+(?!\d))/g,','); return p.join('.'); };
  if(fmt==='yen') return (n<0?'-¥':'¥')+Math.abs(n).toLocaleString('ja-JP',{maximumFractionDigits:0});
  if(fmt==='pct') return (n*100).toLocaleString('ja-JP',{maximumFractionDigits:1})+'%';
  if(fmt==='dec2') return n.toLocaleString('ja-JP',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(fmt==='num') return n.toLocaleString('ja-JP',{maximumFractionDigits:2});
  if(fmt==='date') return serialToYMD(n);
  return sep(n);
}
function displayOf(a){
  const v=V(a);
  if(v==null||v==='') return '';
  if(isErr(v)) return v.e;
  if(typeof v==='number'){ const c=sheet().cells[a];
    let fmt=c&&c.fmt;
    if(!fmt&&c&&c.v&&c.v[0]!=='='){          // 書式未指定でも入力の見た目を引き継ぐ
      if(DATE_RE.test(c.v)) fmt='date';
      else if(c.v.indexOf('¥')>=0) fmt='yen';
      else if(/%\s*$/.test(c.v)) fmt='pct';
    }
    return fmtNum(v,fmt); }
  return String(v);
}

// ==== グリッド描画 ====
const $=id=>document.getElementById(id);
const thead=()=>$('grid-t').tHead, tbody=()=>$('grid-t').tBodies[0];
const DEFAULT_W=104;
function colWidth(c){ return sheet().colW[c]||DEFAULT_W; }
function buildGrid(){
  const t=$('grid-t');
  let h='<tr><th class="corner"></th>';
  for(let c=0;c<sheet().cols;c++)
    h+=`<th class="ch" data-c="${c}" style="width:${colWidth(c)}px;min-width:${colWidth(c)}px">${colName(c)}<span class="colgrip" data-c="${c}"></span></th>`;
  t.tHead.innerHTML=h+'</tr>';
  let b='';
  for(let r=0;r<sheet().rows;r++){
    const rh=(sheet().rowH&&sheet().rowH[r])? ` style="height:${sheet().rowH[r]}px"` : '';
    b+=`<tr${rh}><th class="rh" data-r="${r}" style="position:relative">${r+1}<span class="rowgrip" data-r="${r}"></span></th>`;
    for(let c=0;c<sheet().cols;c++) b+=`<td id="c-${r}-${c}"></td>`;
    b+='</tr>';
  }
  t.tBodies[0].innerHTML=b;
  refreshCells(); paintSel(); renderTabs();
}
function refreshCells(){
  for(let r=0;r<sheet().rows;r++) for(let c=0;c<sheet().cols;c++){
    const a=addrOf(r,c), td=$('c-'+r+'-'+c); if(!td) continue;
    const v=V(a);
    td.textContent=displayOf(a);
    const cl=sheet().cells[a];
    const al=cl&&cl.align? {l:'al',c:'ac',r:'ar'}[cl.align]||'' : '';
    const vl=cl&&cl.valign? {t:'vt',m:'vm',b:'vb'}[cl.valign]||'' : '';
    td.className=(typeof v==='number'?'num ':'')+(isErr(v)?'err ':'')+(cl&&cl.bold?'bold ':'')
      +(al?al+' ':'')+(vl?vl+' ':'')+(cl&&cl.wrap?'wrap ':'');
  }
  paintSel();
}
// ==== 選択 ====
function selRange(){
  const a=selA||cur;
  return {r1:Math.min(a.r,cur.r),c1:Math.min(a.c,cur.c),r2:Math.max(a.r,cur.r),c2:Math.max(a.c,cur.c)};
}
let painted=[];
function paintSel(){
  for(const el of painted) el.classList.remove('sel','cur');
  document.querySelectorAll('#grid-t th.hl').forEach(e=>e.classList.remove('hl'));
  painted=[];
  const s=selRange();
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const td=$('c-'+r+'-'+c); if(td){ td.classList.add('sel'); painted.push(td); } }
  const cu=$('c-'+cur.r+'-'+cur.c); if(cu){ cu.classList.add('cur'); painted.push(cu); }
  document.querySelectorAll(`#grid-t th.ch`).forEach(th=>{ const c=+th.dataset.c; if(c>=s.c1&&c<=s.c2) th.classList.add('hl'); });
  document.querySelectorAll(`#grid-t th.rh`).forEach(th=>{ const r=+th.dataset.r; if(r>=s.r1&&r<=s.r2) th.classList.add('hl'); });
  positionBox($('sel-box'),s);
  positionDdBtn();
  updateFxBar(); updateStatus();
}
function positionDdBtn(){ // 単一セル選択かつ選択肢つきセルなら右端に▾
  const b=$('dd-btn'); if(!b) return;
  const s=selRange();
  const cl=sheet().cells[addrOf(cur.r,cur.c)];
  const single=(s.r1===s.r2&&s.c1===s.c2);
  const td=$('c-'+cur.r+'-'+cur.c);
  if(!single||!cl||!cl.opts||!td){ b.style.display='none'; return; }
  b.style.left=(td.offsetLeft+td.offsetWidth)+'px';
  b.style.top=td.offsetTop+'px';
  b.style.height=td.offsetHeight+'px';
  b.style.display='block';
}
function positionBox(box,s){ // 範囲の外周にオーバーレイ枠を置く
  const a=$('c-'+s.r1+'-'+s.c1), b=$('c-'+s.r2+'-'+s.c2);
  if(!a||!b){ box.style.display='none'; return; }
  box.style.left=a.offsetLeft+'px'; box.style.top=a.offsetTop+'px';
  box.style.width=(b.offsetLeft+b.offsetWidth-a.offsetLeft)+'px';
  box.style.height=(b.offsetTop+b.offsetHeight-a.offsetTop)+'px';
  box.style.display='block';
}

function updateFxBar(){
  const a=addrOf(cur.r,cur.c);
  $('fx-addr').value=a;
  if(document.activeElement!==$('fx')) $('fx').value=rawOf(a);
}
function updateStatus(){
  const s=selRange();
  const single=(s.r1===s.r2&&s.c1===s.c2);
  $('st-sel').textContent=single? addrOf(cur.r,cur.c) : addrOf(s.r1,s.c1)+':'+addrOf(s.r2,s.c2);
  const nums=[];
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const v=V(addrOf(r,c)); if(typeof v==='number') nums.push(v); }
  $('st-sum').textContent=nums.length? fmtNum(nums.reduce((a,b)=>a+b,0),'num') : '-';
  $('st-avg').textContent=nums.length? fmtNum(nums.reduce((a,b)=>a+b,0)/nums.length,'num') : '-';
  $('st-cnt').textContent=nums.length||'-';
}

// ==== 変更・Undo ====
function snapshot(){ return JSON.stringify({name:doc.name,sheets:doc.sheets,active:doc.active}); }
function pushUndo(){ undoStack.push(snapshot()); if(undoStack.length>80)undoStack.shift(); redoStack=[]; }
function restore(s){ doc=JSON.parse(s); astCache.clear(); recalc(); buildGrid(); markDirty(); }
function undo(){ if(!undoStack.length)return; redoStack.push(snapshot()); restore(undoStack.pop()); }
function redo(){ if(!redoStack.length)return; undoStack.push(snapshot()); restore(redoStack.pop()); }
function markDirty(){ dirty=true; $('bsave').classList.add('dirty');
  clearTimeout(markDirty._t); markDirty._t=setTimeout(autosave,600); }
function autosave(){ try{ localStorage.setItem(STORAGE_KEY,snapshot()); }catch(e){} }
function commit(){ recalc(); refreshCells(); markDirty(); }
function ensureSize(r,c){ // 範囲外アクセス時にグリッドを自動拡張
  let grew=false;
  if(r>=sheet().rows){ sheet().rows=r+1; grew=true; }
  if(c>=sheet().cols){ sheet().cols=c+1; grew=true; }
  return grew;
}
function setCellAndRecalc(a,v){ pushUndo();
  const p=parseAddr(a); const grew=p? ensureSize(p.r,p.c) : false;
  setRaw(a,v);
  if(grew){ recalc(); buildGrid(); markDirty(); } else commit(); }

// ==== セル編集 ====
const ed=()=>$('cell-ed');
let editing=false;
function startEdit(initial){
  const td=$('c-'+cur.r+'-'+cur.c); if(!td) return;
  const gw=$('grid-inner').getBoundingClientRect(), tr=td.getBoundingClientRect();
  const e=ed();
  e.style.left=(tr.left-gw.left)+'px'; e.style.top=(tr.top-gw.top)+'px';
  e.style.width=Math.max(tr.width,120)+'px'; e.style.height=tr.height+'px';
  e.style.display='block';
  e.value=(initial!=null)? initial : rawOf(addrOf(cur.r,cur.c));
  e.focus(); if(initial==null) e.select();
  editing=true;
}
function endEdit(save,move){
  if(!editing) return;
  const v=ed().value; ed().style.display='none'; editing=false;
  if(save) setCellAndRecalc(addrOf(cur.r,cur.c),v);
  $('grid-wrap').focus();
  if(move==='down') moveCur(1,0); else if(move==='right') moveCur(0,1);
}

function moveCur(dr,dc,extend){
  const nr=Math.max(0,Math.min(sheet().rows-1,cur.r+dr));
  const nc=Math.max(0,Math.min(sheet().cols-1,cur.c+dc));
  if(extend){ if(!selA) selA={...cur}; } else selA=null;
  cur={r:nr,c:nc}; paintSel(); scrollToCur();
}
function scrollToCur(){
  const td=$('c-'+cur.r+'-'+cur.c); if(!td)return;
  const w=$('grid-wrap'), tr=td.getBoundingClientRect(), wr=w.getBoundingClientRect();
  if(tr.left<wr.left+52) w.scrollLeft-=wr.left+52-tr.left;
  if(tr.right>wr.right) w.scrollLeft+=tr.right-wr.right+4;
  if(tr.top<wr.top+32) w.scrollTop-=wr.top+32-tr.top;
  if(tr.bottom>wr.bottom) w.scrollTop+=tr.bottom-wr.bottom+4;
}

// ==== クリップボード（Excel相互TSV＋内部の式シフト） ====
let clipInternal=null; // {sig, rows:[[raw..]], r, c}
function buildTSV(s){
  const lines=[];
  for(let r=s.r1;r<=s.r2;r++){ const row=[];
    for(let c=s.c1;c<=s.c2;c++) row.push(displayOf(addrOf(r,c)));
    lines.push(row.join('\t')); }
  return lines.join('\n');
}
function copySel(e,cut){
  const s=selRange(); const tsv=buildTSV(s);
  const rows=[];
  for(let r=s.r1;r<=s.r2;r++){ const row=[];
    for(let c=s.c1;c<=s.c2;c++){ const cl=sheet().cells[addrOf(r,c)]||{};
      row.push({v:cl.v??'',fmt:cl.fmt,bold:cl.bold,align:cl.align,valign:cl.valign,wrap:cl.wrap,
        opts:cl.opts?[...cl.opts]:undefined}); }
    rows.push(row); }
  clipInternal={sig:tsv,rows:rows,r:s.r1,c:s.c1};
  if(e&&e.clipboardData){ e.clipboardData.setData('text/plain',tsv); e.preventDefault(); }
  if(cut){ pushUndo();
    for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++) setRaw(addrOf(r,c),'');
    commit(); }
}
function mapOutsideQuotes(f,fn){ // 文字列リテラルを守って置換
  return f.split('"').map((seg,i)=> i%2? seg : fn(seg)).join('"');
}
const SHEETREF_RE=/('[^']*'|[A-Za-z0-9_.\u00C0-\uFFFF]+)!\$?[A-Z]+\$?[0-9]+/g;
function maskSheetRefs(f,fn){ // シート越し参照（収支!N21等）はシフトさせない（固定扱い）
  const bag=[];
  const masked=f.replace(SHEETREF_RE,m=>{ bag.push(m); return '\u0001'+(bag.length-1)+'\u0001'; });
  return fn(masked).replace(/\u0001(\d+)\u0001/g,(_,i)=>bag[+i]);
}
function shiftRelative(f,dr,dc){ // コピペ時の相対参照シフト
  return mapOutsideQuotes(f,seg=>maskSheetRefs(seg,s=>s.replace(REF_RE,(m,d1,col,d2,row)=>{
    let c=colIndex(col), r=parseInt(row,10)-1;
    if(!d1) c+=dc; if(!d2) r+=dr;
    if(c<0||r<0) return '#REF!';
    return d1+colName(c)+d2+(r+1);
  })));
}
function pasteAt(text){
  pushUndo();
  const useInternal=clipInternal&&clipInternal.sig===text.replace(/\r/g,'').replace(/\n$/,'');
  const rows=useInternal? clipInternal.rows
    : text.replace(/\r/g,'').replace(/\n$/,'').split('\n').map(l=>l.split('\t'));
  const maxW=Math.max(0,...rows.map(r=>r.length));
  const grew=ensureSize(cur.r+rows.length-1,cur.c+maxW-1);
  for(let i=0;i<rows.length;i++) for(let j=0;j<rows[i].length;j++){
    const r=cur.r+i, c=cur.c+j, a=addrOf(r,c);
    if(useInternal){ // 内部コピペは書式・選択肢ごと（式は相対シフト）
      const m=rows[i][j]; let v=m.v;
      if(v&&v[0]==='=') v='='+shiftRelative(v.slice(1),cur.r-clipInternal.r,cur.c-clipInternal.c);
      delete sheet().cells[a];
      setRaw(a,v);
      if(m.fmt||m.bold||m.align||m.valign||m.opts||m.wrap){
        const d2=sheet().cells[a]||(sheet().cells[a]={});
        if(m.fmt)d2.fmt=m.fmt; if(m.bold)d2.bold=1;
        if(m.align)d2.align=m.align; if(m.valign)d2.valign=m.valign;
        if(m.opts)d2.opts=[...m.opts]; if(m.wrap)d2.wrap=1;
      }
    }else setRaw(a,rows[i][j]);
  }
  if(grew){ recalc(); buildGrid(); markDirty(); } else commit();
}

// ==== 行・列の挿入/削除（式の参照を書き換え） ====
function shiftRefs(f,axis,pos,delta){ // axis:'r'|'c'
  return mapOutsideQuotes(f,seg=>maskSheetRefs(seg,s=>s.replace(REF_RE,(m,d1,col,d2,row)=>{
    let c=colIndex(col), r=parseInt(row,10)-1;
    const t=(axis==='r')? r : c;
    if(delta<0&&t===pos) return '#REF!';
    if(t>=pos+(delta<0?1:0)&&t>=pos){ if(axis==='r') r+=delta; else c+=delta; }
    if(r<0||c<0) return '#REF!';
    return d1+colName(c)+d2+(r+1);
  })));
}
function remapCells(axis,pos,delta){
  const nc={};
  for(const a in sheet().cells){
    const p=parseAddr(a); let {r,c}=p;
    const t=(axis==='r')? r : c;
    if(delta<0&&t===pos) continue;            // 削除された行/列のセルは捨てる
    if(t>=pos+(delta<0?1:0)&&t>=pos){ if(axis==='r') r+=delta; else c+=delta; }
    const cell={...sheet().cells[a]};
    if(cell.v&&cell.v[0]==='=') cell.v='='+shiftRefs(cell.v.slice(1),axis,pos,delta);
    nc[addrOf(r,c)]=cell;
  }
  sheet().cells=nc;
  if(axis==='c'){ const nw={};
    for(const k in sheet().colW){ let c=+k;
      if(delta<0&&c===pos) continue;
      if(c>=pos+(delta<0?1:0)&&c>=pos) c+=delta;
      nw[c]=sheet().colW[k]; }
    sheet().colW=nw; }
}
function insertRow(pos){ pushUndo(); remapCells('r',pos,1); sheet().rows++; astCache.clear(); recalc(); buildGrid(); markDirty(); }
function deleteRow(pos){ if(sheet().rows<=1)return; pushUndo(); remapCells('r',pos,-1); sheet().rows--; astCache.clear();
  if(cur.r>=sheet().rows)cur.r=sheet().rows-1; recalc(); buildGrid(); markDirty(); }
function insertCol(pos){ pushUndo(); remapCells('c',pos,1); sheet().cols++; astCache.clear(); recalc(); buildGrid(); markDirty(); }
function deleteCol(pos){ if(sheet().cols<=1)return; pushUndo(); remapCells('c',pos,-1); sheet().cols--; astCache.clear();
  if(cur.c>=sheet().cols)cur.c=sheet().cols-1; recalc(); buildGrid(); markDirty(); }

// ==== 書式 ====
function cleanCell(a){ const cl=sheet().cells[a];
  if(cl&&cl.v==null&&!cl.fmt&&!cl.bold&&!cl.align&&!cl.valign&&!cl.opts&&!cl.wrap) delete sheet().cells[a]; }
function applyFmt(fmt){
  pushUndo(); const s=selRange();
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const a=addrOf(r,c);
    if(fmt===null){ const cl=sheet().cells[a];
      if(cl){ delete cl.fmt; delete cl.bold; delete cl.align; delete cl.valign; delete cl.wrap; cleanCell(a); } }
    else (sheet().cells[a]||(sheet().cells[a]={})).fmt=fmt;
  }
  commit();
}
function applyAlign(prop,val){ // prop:'align'(l/c/r)|'valign'(t/m/b)。同じ値をもう一度で解除
  pushUndo(); const s=selRange();
  const a0=sheet().cells[addrOf(s.r1,s.c1)];
  const off=a0&&a0[prop]===val;
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const a=addrOf(r,c);
    if(off){ const cl=sheet().cells[a]; if(cl){ delete cl[prop]; cleanCell(a); } }
    else (sheet().cells[a]||(sheet().cells[a]={}))[prop]=val;
  }
  commit();
}
function toggleWrap(){ // 折り返して全体を表示（行の高さは中身に合わせて伸びる）
  pushUndo(); const s=selRange();
  const a0=sheet().cells[addrOf(s.r1,s.c1)]; const on=!(a0&&a0.wrap);
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const a=addrOf(r,c);
    if(on) (sheet().cells[a]||(sheet().cells[a]={})).wrap=1;
    else { const cl=sheet().cells[a]; if(cl){ delete cl.wrap; cleanCell(a); } }
  }
  commit();
}
function setOpts(list){ // 選択範囲にプルダウン選択肢を設定（nullで解除）
  pushUndo(); const s=selRange();
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const a=addrOf(r,c);
    if(!list||!list.length){ const cl=sheet().cells[a]; if(cl){ delete cl.opts; cleanCell(a); } }
    else (sheet().cells[a]||(sheet().cells[a]={})).opts=[...list];
  }
  commit();
}
function showOptsModal(){
  const cl=sheet().cells[addrOf(cur.r,cur.c)];
  const cur0=(cl&&cl.opts)? cl.opts.join('\n') : '';
  openModal(`<h3>プルダウンの選択肢</h3>
    <label>選択肢（1行に1つ。空にすると解除）</label>
    <textarea id="dd-list" rows="6">${escHtml(cur0)}</textarea>
    <div class="note">選択範囲のセルに適用。セルを選ぶと右に▾が出て、クリックで選べる（手入力も可）</div>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">キャンセル</button>
    <button class="m-save" id="m-go">適用</button></div>`);
  $('m-go').onclick=()=>{
    const list=$('dd-list').value.split('\n').map(s=>s.trim()).filter(Boolean);
    setOpts(list); closeModal();
  };
}
function toggleBold(){
  pushUndo(); const s=selRange();
  const a0=addrOf(s.r1,s.c1); const on=!(sheet().cells[a0]&&sheet().cells[a0].bold);
  for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++){
    const a=addrOf(r,c);
    if(on) (sheet().cells[a]||(sheet().cells[a]={})).bold=1;
    else { const cl=sheet().cells[a]; if(cl){ delete cl.bold; if(cl.v==null&&!cl.fmt) delete sheet().cells[a]; } }
  }
  commit();
}

// ==== 入出力 ====
function download(name,content,mime){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([content],{type:mime||'text/plain'}));
  a.download=name; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),3000);
}
let saveFileHandle=null;
function setSaveStatus(text){ const el=$('save-status'); if(el){el.textContent=text;el.title=text;} }
function clearSaveTarget(){ saveFileHandle=null; setSaveStatus('復旧: ブラウザ内'); }
function savedTo(name,downloaded){
  dirty=false; $('bsave').classList.remove('dirty');
  setSaveStatus((downloaded?'DL: ':'保存先: ')+name);
}
async function saveDocument(saveAs){
  autosave();
  const name=(doc.name||'sheet').replace(/[\\/:*?"<>|]/g,'_')+'.calc.json';
  const content=snapshot();
  if(typeof window.showSaveFilePicker!=='function'){
    download(name,content,'application/json'); savedTo(name,true); return;
  }
  try{
    if(saveAs)saveFileHandle=null;
    if(!saveFileHandle)saveFileHandle=await window.showSaveFilePicker({
      id:'calckit-document',suggestedName:name,
      types:[{description:'CalcKit JSON',accept:{'application/json':['.calc.json','.json']}}]
    });
    const writable=await saveFileHandle.createWritable();
    await writable.write(content); await writable.close();
    savedTo(saveFileHandle.name,false); toast('保存しました: '+saveFileHandle.name);
  }catch(e){
    if(e&&e.name==='AbortError')return;
    alert('保存に失敗しました: '+(e.message||e));
  }
}
function loadOpenedText(name,text,handle){
  if(name.toLowerCase().endsWith('.json')){
    try{
      const d=JSON.parse(text); if(!d.cells&&!d.sheets)throw 0;
      pushUndo(); doc=normalizeDoc(d); astCache.clear(); recalc(); buildGrid(); setName(doc.name);
      saveFileHandle=handle||null; autosave(); dirty=false; $('bsave').classList.remove('dirty');
      setSaveStatus(saveFileHandle?'保存先: '+saveFileHandle.name:'復旧: ブラウザ内');
    }catch(_){ alert('CalcKitのJSONではありません'); }
  }else{
    clearSaveTarget(); importCSVText(text,name.replace(/\.(csv|tsv|txt)$/i,''));
  }
}
async function openDocument(){
  if(typeof window.showOpenFilePicker==='function'){
    try{
      const handles=await window.showOpenFilePicker({
        id:'calckit-document',multiple:false,
        types:[{description:'CalcKit / CSV',accept:{'application/json':['.calc.json','.json'],'text/plain':['.csv','.tsv','.txt']}}]
      });
      const handle=handles[0],file=await handle.getFile();
      loadOpenedText(file.name,await file.text(),handle); return;
    }catch(e){ if(e&&e.name==='AbortError')return; alert('ファイルを開けません: '+(e.message||e)); return; }
  }
  const inp=document.createElement('input'); inp.type='file'; inp.accept='.json,.csv,.tsv,.txt';
  inp.onchange=()=>{ const file=inp.files[0]; if(!file)return;
    const rd=new FileReader(); rd.onload=()=>loadOpenedText(file.name,String(rd.result),null); rd.readAsText(file); };
  inp.click();
}
function usedRange(){
  let r2=0,c2=0,found=false;
  for(const a in sheet().cells){ if(sheet().cells[a].v==null)continue;
    const p=parseAddr(a); r2=Math.max(r2,p.r); c2=Math.max(c2,p.c); found=true; }
  return found? {r1:0,c1:0,r2,c2} : {r1:0,c1:0,r2:0,c2:0};
}
function currentRegion(r0,c0){ // 指定セル周辺の連続データ塊（Excelのカレント領域）
  let r1=r0,r2=r0,c1=c0,c2=c0;
  const has=(r,c)=>{ const cl=sheet().cells[addrOf(r,c)]; return cl&&cl.v!=null&&cl.v!==''; };
  let changed=true;
  while(changed){ changed=false;
    if(r1>0) for(let c=c1;c<=c2;c++) if(has(r1-1,c)){ r1--; changed=true; break; }
    if(r2<sheet().rows-1) for(let c=c1;c<=c2;c++) if(has(r2+1,c)){ r2++; changed=true; break; }
    if(c1>0) for(let r=r1;r<=r2;r++) if(has(r,c1-1)){ c1--; changed=true; break; }
    if(c2<sheet().cols-1) for(let r=r1;r<=r2;r++) if(has(r,c2+1)){ c2++; changed=true; break; }
  }
  return {r1,c1,r2,c2};
}
function largestRegion(){ // シート内で一番セル数の多いデータ塊
  const seen={}; let best=null;
  for(const a in sheet().cells){
    const cl=sheet().cells[a]; if(cl.v==null||cl.v===''||seen[a]) continue;
    const p=parseAddr(a);
    const rg=currentRegion(p.r,p.c);
    let cnt=0;
    for(let r=rg.r1;r<=rg.r2;r++) for(let c=rg.c1;c<=rg.c2;c++){
      const k=addrOf(r,c); seen[k]=1;
      const kc=sheet().cells[k]; if(kc&&kc.v!=null&&kc.v!=='') cnt++;
    }
    if(!best||cnt>best.cnt) best={rg,cnt};
  }
  return best? best.rg : usedRange();
}
function exportRange(){
  // 選択が複数セルならそれ／単一ならカーソル周辺の塊／孤立セル上なら一番大きい塊
  const s=selRange();
  if(!(s.r1===s.r2&&s.c1===s.c2)) return s;
  const rg=currentRegion(cur.r,cur.c);
  return (rg.r1===rg.r2&&rg.c1===rg.c2)? largestRegion() : rg;
}
function csvEsc(v){ return /[",\n]/.test(v)? '"'+v.replace(/"/g,'""')+'"' : v; }
function buildCSV(){
  const u=usedRange(); const lines=[];
  for(let r=u.r1;r<=u.r2;r++){ const row=[];
    for(let c=u.c1;c<=u.c2;c++) row.push(csvEsc(displayOf(addrOf(r,c))));
    lines.push(row.join(',')); }
  return lines.join('\n');
}
function exportXls(){ // HTMLテーブル方式（Excelが開ける）
  const u=usedRange(); let rows='';
  for(let r=u.r1;r<=u.r2;r++){ rows+='<tr>';
    for(let c=u.c1;c<=u.c2;c++){ const a=addrOf(r,c); const v=V(a);
      const cl=sheet().cells[a];
      const st=(cl&&cl.bold?'font-weight:bold;':'')+(typeof v==='number'?'mso-number-format:\\#\\,\\#\\#0;':'');
      rows+=`<td style="${st}">${escHtml(displayOf(a))}</td>`; }
    rows+='</tr>'; }
  const html=`<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="UTF-8"></head><body><table>${rows}</table></body></html>`;
  download(doc.name+'.xls',html,'application/vnd.ms-excel');
}
function escHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function importCSVText(text,name){
  pushUndo();
  doc=newDoc(name||'読み込みシート');
  const lines=text.replace(/\r/g,'').split('\n');
  const rows=lines.map(parseCSVLine);
  sheet().rows=Math.max(50,rows.length+10); sheet().cols=Math.max(26,(rows[0]||[]).length+4);
  for(let r=0;r<rows.length;r++) for(let c=0;c<rows[r].length;c++)
    if(rows[r][c]!=='') setRaw(addrOf(r,c),rows[r][c]);
  astCache.clear(); recalc(); buildGrid(); setName(doc.name); markDirty();
}
function parseCSVLine(line){
  const out=[]; let i=0,cur='',q=false;
  while(i<line.length){ const ch=line[i];
    if(q){ if(ch==='"'){ if(line[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=ch; }
    else if(ch==='"') q=true;
    else if(ch===','){ out.push(cur); cur=''; }
    else cur+=ch;
    i++; }
  out.push(cur); return out;
}

// ==== シート（タブ）操作 ====
function uniqueSheetName(base){
  let n=base,k=2;
  while(sheetIdx(n)>=0){ n=base+'('+k+')'; k++; }
  return n;
}
function switchSheet(i){
  if(i<0||i>=doc.sheets.length||i===doc.active) return;
  if(editing) endEdit(true);
  doc.active=i; cur={r:0,c:0}; selA=null;
  buildGrid(); markDirty();
}
function addSheet(){
  pushUndo();
  doc.sheets.push(newSheet(uniqueSheetName('シート'+(doc.sheets.length+1))));
  doc.active=doc.sheets.length-1; cur={r:0,c:0}; selA=null;
  recalc(); buildGrid(); markDirty();
}
function renameSheet(i,name){
  name=String(name||'').trim();
  if(!name||name.includes('!')||name.includes("'")) return false;
  if(sheetIdx(name)>=0&&sheetIdx(name)!==i) return false;
  pushUndo();
  const old=doc.sheets[i].name;
  doc.sheets[i].name=name;
  // 全シートの式のシート参照を書き換え（旧名!A1 / '旧名'!A1 の両形）
  const needQuote=/[^A-Za-z0-9_.\u00C0-\uFFFF]/.test(name);
  const nn=needQuote? "'"+name+"'" : name;
  for(const s of doc.sheets) for(const a in s.cells){
    const c=s.cells[a];
    if(c.v&&c.v[0]==='='){
      c.v=c.v.split("'"+old+"'!").join(nn+'!').split(old+'!').join(nn+'!');
    }
  }
  astCache.clear(); recalc(); buildGrid(); markDirty();
  return true;
}
function deleteSheet(i){
  if(doc.sheets.length<=1) return false;
  pushUndo();
  doc.sheets.splice(i,1);
  if(doc.active>=doc.sheets.length) doc.active=doc.sheets.length-1;
  cur={r:0,c:0}; selA=null;
  astCache.clear(); recalc(); buildGrid(); markDirty();  // 参照は評価時に#REF!
  return true;
}
function dupSheet(i){
  pushUndo();
  const src=doc.sheets[i];
  const cp=JSON.parse(JSON.stringify(src));
  cp.name=uniqueSheetName(src.name+'のコピー');
  doc.sheets.splice(i+1,0,cp);
  doc.active=i+1; cur={r:0,c:0}; selA=null;
  recalc(); buildGrid(); markDirty();
}
function renderTabs(){
  const el=$('tabs'); if(!el) return;
  el.innerHTML='';
  doc.sheets.forEach((s,i)=>{
    const b=document.createElement('button');
    b.className='tab'+(i===doc.active?' on':'');
    b.textContent=s.name;
    b.title='クリックで切替／ダブルクリックで名前変更／右クリックで複製・削除';
    b.onclick=()=>switchSheet(i);
    b.ondblclick=()=>{ const n=prompt('シート名',s.name); if(n!=null&&!renameSheet(i,n)&&n.trim()!==s.name)
      alert('その名前は使えません（重複か、!と\'は不可）'); };
    b.oncontextmenu=e=>{ e.preventDefault();
      showCtx(e.clientX,e.clientY,[
        {label:'名前を変更',fn:()=>b.ondblclick()},
        {label:'複製',fn:()=>dupSheet(i)},'-',
        {label:`「${s.name}」を削除`,fn:()=>{ if(doc.sheets.length<=1){alert('最後のシートは削除できません');return;}
          if(confirm(`シート「${s.name}」を削除しますか？（参照している式は#REF!になります）`)) deleteSheet(i); }}]); };
    el.appendChild(b);
  });
  const add=document.createElement('button');
  add.className='tab tab-add'; add.textContent='＋'; add.title='シートを追加';
  add.onclick=addSheet;
  el.appendChild(add);
}

// ==== テンプレート ====
function loadTemplate(id){
  pushUndo();
  if(id==='blank'){ doc=newDoc('新しいシート'); }
  else if(id==='cost') doc=tmplCost();
  else doc=tmplPL();
  astCache.clear(); recalc(); buildGrid(); setName(doc.name);
  cur={r:0,c:0}; selA=null; paintSel(); markDirty();
}
function tset(d,a,v,o){ d.cells[a]={v:String(v),...(o||{})}; }
function wrapDoc(name,sheets){ return {name,sheets,active:0}; }
function tmplCost(){ // 工数計算: レベルはプルダウン→単価は単価表からVLOOKUP
  const d=newSheet('工数',30,12);
  d.colW={0:140,1:70,2:110,3:80,4:80,5:60,6:130,7:30,8:70,9:110};
  tset(d,'A1','工数・費用計算（金額 = 時給単価 × 40h × 稼働週 × 稼働率 × 人数）',{bold:1});
  ['役割','レベル','時給単価','稼働率','稼働週','人数','金額'].forEach((h,i)=>tset(d,addrOf(2,i),h,{bold:1}));
  // 単価表（I3:J7）。改定はここを1か所直すだけ
  tset(d,'I3','レベル',{bold:1}); tset(d,'J3','時給単価',{bold:1});
  [['L6',41720],['L5',32092],['L4',22465],['PT',5000]].forEach((rw,i)=>{
    tset(d,'I'+(4+i),rw[0]); tset(d,'J'+(4+i),rw[1],{fmt:'yen'});
  });
  const LEVELS=['L6','L5','L4','PT'];
  const rows=[['リード','L6',0.5,12,1],['メンバー','L5',1,12,2],['メンバー','L4',1,12,1]];
  rows.forEach((rw,i)=>{ const r=4+i;   // 表示行番号
    tset(d,'A'+r,rw[0]);
    tset(d,'B'+r,rw[1],{opts:LEVELS,align:'c'});
    tset(d,'C'+r,`=VLOOKUP(B${r},$I$4:$J$7,2,0)`,{fmt:'yen'});
    tset(d,'D'+r,rw[2],{fmt:'pct'});
    tset(d,'E'+r,rw[3]);
    tset(d,'F'+r,rw[4]);
    tset(d,'G'+r,`=C${r}*40*E${r}*D${r}*F${r}`,{fmt:'yen'});
  });
  tset(d,'A8','合計',{bold:1});
  tset(d,'G8','=SUM(G4:G6)',{bold:1,fmt:'yen'});
  tset(d,'A10','合計工数（人週）'); tset(d,'B10','=E4*D4*F4+E5*D5*F5+E6*D6*F6',{fmt:'dec2'});
  tset(d,'A11','人月換算（4.33週/月）'); tset(d,'B11','=B10/4.33',{fmt:'dec2'});
  return wrapDoc('工数計算',[d]);
}
function tmplPL(){ // 収支計算（FitBase月次PL・デモ既定）
  // 筋（2026-07-31利用者ヒアリング反映）:
  //  収入=月会費＋パーソナル＋物販（プロテイン等）＋空き時間の時間貸し（個人トレーナーへ）
  //  費用=初期費用（敷金礼金90万・内装150万・機材200万・備品40万=480万を4月に一括）＋
  //       家賃30万＋非常駐トレーナー人件費（1日5h前後・規模連動）＋水道光熱・通信・設備
  //       （ウォーターサーバー/監視カメラ/スマートロック込み8万）＋物販原価50%＋
  //       突発の機材修理・追加（数万円を不定期）＋広告費
  //  → 単月は4か月目に黒字化・初期投資は10か月目に累計回収・通年+322万（利益率16%）
  const d=newSheet('収支',30,16);
  d.colW={0:230}; for(let c=1;c<=13;c++)d.colW[c]=92;
  const mons=['4月','5月','6月','7月','8月','9月','10月','11月','12月','1月','2月','3月'];
  tset(d,'A1','FitBase 月次収支計画 FY2026',{bold:1});
  tset(d,'A3','項目',{bold:1});
  mons.forEach((m,i)=>tset(d,addrOf(2,1+i),m,{bold:1}));
  tset(d,addrOf(2,13),'合計',{bold:1});
  const members=[20,26,33,41,50,58,65,71,78,84,90,95];
  const rentH  =[10,12,15,18,20,22,25,25,28,28,30,30];
  const repair =[0,0,50000,0,30000,0,80000,0,0,60000,0,40000];
  tset(d,'A4','会員数（人）');
  tset(d,'A5','月会費売上（¥12,000）');
  tset(d,'A6','パーソナル売上（月2回×¥7,000）');
  tset(d,'A7','物販売上（プロテイン等 ¥1,200/人）');
  tset(d,'A8','ジム貸出時間（h・空き時間）');
  tset(d,'A9','レンタル売上（¥2,500/h）');
  tset(d,'A10','売上合計',{bold:1});
  tset(d,'A12','初期費用（敷金礼金・内装・機材・備品）');
  tset(d,'A13','家賃');
  tset(d,'A14','トレーナー人件費（非常駐・1日5h前後）');
  tset(d,'A15','水道光熱・通信・設備（カメラ/鍵/水込み）');
  tset(d,'A16','物販原価（50%）');
  tset(d,'A17','機材修理・追加');
  tset(d,'A18','広告費');
  tset(d,'A19','費用合計',{bold:1});
  tset(d,'A21','営業利益',{bold:1});
  tset(d,'A22','利益率');
  tset(d,'A23','借入残高（期首・借入300万/年2.5%/毎月¥50,000元利返済）');
  tset(d,'A24','支払利息（期首残高×2.5%÷12）');
  tset(d,'A25','経常利益（営業利益−支払利息）');
  tset(d,'A26','累計経常利益（初期投資の回収）');
  for(let i=0;i<12;i++){ const L=colName(1+i);
    tset(d,L+'4',members[i]);
    tset(d,L+'5',`=${L}4*12000`,{fmt:'yen'});
    tset(d,L+'6',`=${L}4*2*7000`,{fmt:'yen'});
    tset(d,L+'7',`=${L}4*1200`,{fmt:'yen'});
    tset(d,L+'8',rentH[i]);
    tset(d,L+'9',`=${L}8*2500`,{fmt:'yen'});
    tset(d,L+'10',`=${L}5+${L}6+${L}7+${L}9`,{fmt:'yen',bold:1});
    if(i===0) tset(d,L+'12',4800000,{fmt:'yen'});           // 初期費用は4月のみ
    tset(d,L+'13',300000,{fmt:'yen'});
    tset(d,L+'14',i<4?325000:(i<8?400000:500000),{fmt:'yen'});
    tset(d,L+'15',80000,{fmt:'yen'});
    tset(d,L+'16',`=${L}7*0.5`,{fmt:'yen'});
    if(repair[i]>0) tset(d,L+'17',repair[i],{fmt:'yen'});   // 突発なので無い月は空欄
    tset(d,L+'18',i<3?250000:120000,{fmt:'yen'});
    tset(d,L+'19',`=SUM(${L}12:${L}18)`,{fmt:'yen',bold:1});
    tset(d,L+'21',`=${L}10-${L}19`,{fmt:'yen',bold:1});
    tset(d,L+'22',`=IF(${L}10=0,0,${L}21/${L}10)`,{fmt:'pct'});
    // 借入: 期首残高→利息は残りに対してかかる→翌月期首=期首+利息−返済¥50,000
    const P=colName(i);   // 前月の列
    tset(d,L+'23',i===0? 3000000 : `=${P}23+${P}24-50000`,{fmt:'yen'});
    tset(d,L+'24',`=ROUND(${L}23*0.025/12,0)`,{fmt:'yen'});
    tset(d,L+'25',`=${L}21-${L}24`,{fmt:'yen',bold:1});
    tset(d,L+'26',i===0? '=B25' : `=${P}26+${L}25`,{fmt:'yen'});
  }
  for(const r of [5,6,7,8,9,10,12,13,14,15,16,17,18,19,21,24,25])
    tset(d,'N'+r,`=SUM(B${r}:M${r})`,{fmt:r===8?'num':'yen',bold:[10,19,21,25].includes(r)?1:undefined});
  tset(d,'N22','=IF(N10=0,0,N21/N10)',{fmt:'pct'});
  tset(d,'N23','=M23+M24-50000',{fmt:'yen'});   // 期末残高
  tset(d,'N26','=M26',{fmt:'yen'});
  return wrapDoc('FitBase収支計画（デモ）',[d]);
}

// ==== SlideKit書き出し（data属性表・PPTX変換可能） ====
function buildSlideHtml(){
  const u=exportRange();
  const nR=u.r2-u.r1+1, nC=u.c2-u.c1+1;
  // 列幅を1152pxに比例配分
  let tw=0; const ws=[];
  for(let c=u.c1;c<=u.c2;c++){ ws.push(colWidth(c)); tw+=colWidth(c); }
  const W=1152; const colPx=ws.map(w=>Math.round(w/tw*W));
  const fs=nR>16?15:16;                       // PPTX 0.75換算で11.25pt/12pt（下限順守）
  let rows='';
  for(let r=u.r1;r<=u.r2;r++){
    rows+='<tr>';
    const isHead=(r===u.r1);
    for(let c=u.c1;c<=u.c2;c++){
      const a=addrOf(r,c), v=V(a), cl=sheet().cells[a];
      const num=(typeof v==='number');
      const tag=isHead?'th':'td';
      let st;
      if(isHead) st=`background:#21537f;color:#fafafa;padding:7px 10px;text-align:${num?'right':'left'};font-weight:700;font-size:${fs}px`;
      else st=`padding:5px 10px;border-bottom:1px solid #e2e8f0;color:#121212;text-align:${num?'right':'left'};`+
        `${cl&&cl.bold?'font-weight:700;':''}font-size:${fs}px`;
      rows+=`<${tag} style="${st}">${escHtml(displayOf(a))}</${tag}>`;
    }
    rows+='</tr>';
  }
  const editJs=new URL('../SlideKit/slide-edit.js',location.href).href;
  return `<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>${escHtml(doc.name)}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Yu Gothic','游ゴシック','Noto Sans JP',sans-serif;background:#2d3748;display:flex;flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;background:#fafafa}
.tb{position:absolute;overflow:hidden;line-height:1.5}
</style></head>
<body>
<!-- SLIDE: ${escHtml(doc.name)} -->
<div class="slide" data-bg="#fafafa" style="background:#fafafa">
  <div class="tb" data-x="64" data-y="48" data-w="1152" data-h="44" data-font-size="28" data-bold="1" data-color="#183251"
       style="left:64px;top:48px;width:1152px;height:44px;font-size:28px;font-weight:700;color:#183251">${escHtml(doc.name)}</div>
  <table data-x="64" data-y="120" data-w="1152"
         style="position:absolute;left:64px;top:120px;width:1152px;border-collapse:collapse;font-size:${fs}px;table-layout:fixed">
    <colgroup>${colPx.map(w=>`<col style="width:${w}px">`).join('')}</colgroup>
    ${rows}
  </table>
</div>
<!-- /SLIDE -->
<script src="${editJs}"><\/script>
</body>
</html>`;
}

// ==== GanttKitデータ書き出し ====
function normMonth(s){ // 'YYYY-MM'|'YYYY-MM-DD'|'YYYY/M/D' → 'YYYY-MM' / 日付付きはそのまま正規化
  const t=String(s).trim().replace(/\//g,'-');
  let m=/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$/.exec(t);
  if(!m) return null;
  const ym=m[1]+'-'+String(+m[2]).padStart(2,'0');
  return m[3]? ym+'-'+String(+m[3]).padStart(2,'0') : ym;
}
function monthOf(d){ return d.slice(0,7); }
function buildGanttPayload(map){ // GanttKitに渡す素データ（localStorage受け渡し用）
  const p=ganttRows(map); if(!p) return null;
  return {config:p.config,categories:p.cats,items:p.items};
}
function ganttRows(map){ // 表→ガント用の中間形（列マッピングを適用）
  const u=exportRange();
  const items=[]; const catNames=[];
  let minM=null,maxM=null;
  for(let r=u.r1+1;r<=u.r2;r++){ // 先頭行はヘッダ
    const g=v=>{ const ci=map[v]; return (ci==null||ci<0)? '' : displayOf(addrOf(r,u.c1+ci)); };
    const name=g('name'); if(!name) continue;
    const st=normMonth(g('start')), en=normMonth(g('end'));
    if(!st||!en) continue;
    const grp=g('group')||'項目';
    if(!catNames.includes(grp)) catNames.push(grp);
    items.push({name,cat:grp,start:st,end:en,ver:g('label')||'',desc:g('desc')||''});
    const a=monthOf(st),b=monthOf(en);
    if(!minM||a<minM)minM=a; if(!maxM||b>maxM)maxM=b;
  }
  if(!items.length) return null;
  const PALETTE=['#3498DB','#E74C3C','#27AE60','#9B59B6','#E67E22','#2C3E50','#16A085','#7F8C8D'];
  const cats=catNames.map((n,i)=>({id:'cat'+(i+1),name:n,color:PALETTE[i%PALETTE.length]}));
  const catId=n=>cats[catNames.indexOf(n)].id;
  return {cats,
    config:{start:minM,end:maxM,today:minM,storageKey:'ganttkit_calc_'+Date.now(),
      exportName:doc.name,exportTitle:doc.name},
    items:items.map((it,i)=>({id:'ck'+(i+1),cat:catId(it.cat),name:it.name,
      versions:[{ver:it.ver,start:it.start,end:it.end,desc:it.desc}]}))};
}
function buildGanttData(map){ // GanttKitデータjs（ファイル保存用）
  const p=ganttRows(map); if(!p) return null;
  const js=[];
  js.push('// CalcKit書き出し — GanttKitデータ（'+doc.name+'）');
  js.push('(function(){','\'use strict\';');
  js.push('window.TL_CONFIG='+JSON.stringify(p.config)+';');
  js.push('window.TL_MILESTONES=[];');
  js.push('window.TL_ANNUAL_FOCUS=[];');
  js.push('window.TL_PLANS=[];');
  js.push('window.TL_CATEGORIES='+JSON.stringify(p.cats)+';');
  js.push('window.TL_ITEMS=['+p.items.map(it=>JSON.stringify(it)).join(',\n')+'];');
  js.push('})();');
  return js.join('\n');
}

// ==== DashboardKitグラフ（範囲→ {labels, series} ） ====
function buildChartData(){
  // ヘッダ行/列は「文字が多数派か」で自動判定し、短い方の次元を系列にする（Excelの流儀）
  const u=exportRange();
  const val=(r,c)=>V(addrOf(r,c));
  const disp=(r,c)=>displayOf(addrOf(r,c));
  const isTextish=v=>v!=null&&v!==''&&typeof v!=='number';
  let tx=0,nm=0;
  for(let c=u.c1+1;c<=u.c2;c++){ const v=val(u.r1,c); if(isTextish(v))tx++; else if(typeof v==='number')nm++; }
  const hR=tx>nm;                                    // 先頭行がヘッダか
  tx=0; nm=0;
  for(let r=u.r1+1;r<=u.r2;r++){ const v=val(r,u.c1); if(isTextish(v))tx++; else if(typeof v==='number')nm++; }
  const hC=tx>nm;                                    // 先頭列がラベル列か
  const r0=u.r1+(hR?1:0), c0=u.c1+(hC?1:0);
  const nR=u.r2-r0+1, nC=u.c2-c0+1;                  // データ行数・列数
  const byRows=nC>nR;                                // 横長なら 行=系列・列=ラベル
  const labels=[], series=[];
  const yenish=(r,c)=>{ const cl=sheet().cells[addrOf(r,c)]; return cl&&cl.fmt==='yen'; };
  if(byRows){
    for(let c=c0;c<=u.c2;c++) labels.push(hR? (disp(u.r1,c)||colName(c)) : colName(c));
    for(let r=r0;r<=u.r2;r++){
      let hasNum=false,yen=0,n=0;
      for(let c=c0;c<=u.c2;c++){ if(typeof val(r,c)==='number'){ hasNum=true; n++; if(yenish(r,c))yen++; } }
      if(!hasNum) continue;
      series.push({name:hC? (disp(r,u.c1)||String(r-r0+1)) : '行'+(r+1), yen:yen>n/2,
        values:labels.map((_,i)=>{ const v=val(r,c0+i); return typeof v==='number'? v:0; })});
    }
  }else{
    for(let r=r0;r<=u.r2;r++) labels.push(hC? (disp(r,u.c1)||String(r-r0+1)) : String(r+1));
    for(let c=c0;c<=u.c2;c++){
      let hasNum=false,yen=0,n=0;
      for(let r=r0;r<=u.r2;r++){ if(typeof val(r,c)==='number'){ hasNum=true; n++; if(yenish(r,c))yen++; } }
      if(!hasNum) continue;
      series.push({name:hR? (disp(u.r1,c)||colName(c)) : colName(c), yen:yen>n/2,
        values:labels.map((_,i)=>{ const v=val(r0+i,c); return typeof v==='number'? v:0; })});
    }
  }
  // 「合計」のラベルは除外（月次と同じ軸に載るとスケールが潰れる・円では二重カウント）
  for(let i=labels.length-1;i>=0;i--){
    const t=String(labels[i]).trim();
    if(t==='合計'||t==='計'||/^total$/i.test(t)){
      labels.splice(i,1); for(const s of series) s.values.splice(i,1);
    }
  }
  // 桁あふれ対策: 最大値が100万以上なら万円スケール。その際、円書式でない系列
  // （人数・時間など単位の違うもの）は軸が無意味になるので外す
  let maxAbs=0;
  for(const s of series) for(const v of s.values) maxAbs=Math.max(maxAbs,Math.abs(v));
  let unit='', out=series;
  if(maxAbs>=1e6){ unit='万円';
    const yen=series.filter(s=>s.yen);
    out=yen.length? yen : series;
    for(const s of out) s.values=s.values.map(v=>Math.round(v/1000)/10);
  }
  return {labels,series:out,unit};
}
function buildPieData(){ // 円/ドーナツ用: 各系列の合計の構成比（負・ゼロは除外）
  const d=buildChartData();
  return {unit:d.unit,
    slices:d.series.map(s=>({name:s.name,value:s.values.reduce((a,b)=>a+b,0)}))
      .filter(s=>s.value>0)};
}
function showChartModal(){
  if(!window.DK){ alert('DashboardKit（../DashboardKit/dashboard-kit.js）が見つからないためグラフは使えません'); return; }
  const d=buildChartData();
  if(!d.series.length){ alert('グラフにする範囲を選択してください（系列名の行＋ラベル列＋数値）'); return; }
  openModal(`<h3>グラフ（DashboardKit）</h3>
    <label>種類</label>
    <select id="ck-ctype"><option value="bar">棒</option><option value="line">折れ線</option>
    <option value="smooth">折れ線（曲線）</option><option value="pie">円</option><option value="donut">ドーナツ</option></select>
    <div id="chart-host"></div>
    <div class="note">選択範囲をグラフ化（単一セルならカーソル周辺のデータ塊）。ヘッダ行/列は自動判定、
    短い方の次元を系列として描画。「合計」の列は自動で外す。最大値が100万以上のときは万円表示にし、
    円書式でない系列（人数・時間など）も外す。円/ドーナツは<b>各系列の合計の構成比</b>
    （例: 家賃〜広告費の行を選択すると費用の内訳）。
    スライドに入れる時はスクリーンショットで（グラフのPPTXネイティブ化は未対応）</div>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">閉じる</button></div>`,true);
  const host=$('chart-host'); let inst=null;
  function draw(){
    const type=$('ck-ctype').value;
    host.innerHTML='';
    let opts;
    if(type==='pie'||type==='donut'){
      const p=buildPieData();
      opts={type,series:p.slices};
      if(type==='donut') opts.centerLabel=fmtNum(p.slices.reduce((a,b)=>a+b.value,0),'num')+(p.unit||'');
    }else{
      opts={type,labels:d.labels,series:d.series,height:380};
      if(d.unit) opts.unit=d.unit;
    }
    inst=DK.chart(host,opts);
  }
  $('ck-ctype').onchange=draw; draw();
}

// ==== モーダル ====
function openModal(html,wide){
  const m=$('modal'); m.className='modal'+(wide?' wide':''); m.innerHTML=html;
  $('modal-bg').classList.add('show');
  const c=$('m-cancel'); if(c) c.onclick=closeModal;
}
function closeModal(){ $('modal-bg').classList.remove('show'); $('modal').innerHTML=''; }

function showGanttModal(){
  const u=exportRange();
  const heads=[]; for(let c=u.c1;c<=u.c2;c++) heads.push(displayOf(addrOf(u.r1,c))||colName(c));
  const opts=(sel,none)=> (none?'<option value="-1">（なし）</option>':'')+
    heads.map((h,i)=>`<option value="${i}"${i===sel?' selected':''}>${escHtml(h)}</option>`).join('');
  const guess=(words)=>heads.findIndex(h=>words.some(w=>String(h).includes(w)));
  const gi={name:guess(['項目','名前','タスク','作業']),start:guess(['開始','From','from']),
    end:guess(['終了','完了','To','to']),group:guess(['グループ','分類','カテゴリ','フェーズ'])};
  openModal(`<h3>GanttKitデータ書き出し</h3>
    <div class="note">先頭行をヘッダとして列を割り当てる。日付は YYYY-MM か YYYY-MM-DD（/区切りも可）</div>
    <label>項目名の列</label><select id="gk-name">${opts(gi.name<0?0:gi.name)}</select>
    <label>開始の列</label><select id="gk-start">${opts(gi.start<0?1:gi.start)}</select>
    <label>終了の列</label><select id="gk-end">${opts(gi.end<0?2:gi.end)}</select>
    <label>グループの列（任意）</label><select id="gk-group">${opts(gi.group,true)}</select>
    <label>ラベルの列（任意・PoC/本番など）</label><select id="gk-label">${opts(-1,true)}</select>
    <label>説明の列（任意）</label><select id="gk-desc">${opts(-1,true)}</select>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">キャンセル</button>
    <button id="m-go">データjsを保存</button>
    <button class="m-save" id="m-open">GanttKitで開く</button></div>`);
  const readMap=()=>({name:+$('gk-name').value,start:+$('gk-start').value,end:+$('gk-end').value,
    group:+$('gk-group').value,label:+$('gk-label').value,desc:+$('gk-desc').value});
  $('m-open').onclick=()=>{
    const d=buildGanttPayload(readMap());
    if(!d){ alert('書き出せる行がありません（項目名と開始・終了の日付を確認）'); return; }
    try{
      localStorage.setItem('ckGanttData',JSON.stringify({data:d,ts:Date.now()}));
      window.open(new URL('../GanttKit/index.html',location.href).href+'#fromCalc','_blank');
      toast('GanttKitのタブでガントとして開いた');
    }catch(e){ alert('受け渡し失敗: '+e.message); }
    closeModal();
  };
  $('m-go').onclick=()=>{
    const js=buildGanttData(readMap());
    if(!js){ alert('書き出せる行がありません（項目名と開始・終了の日付を確認）'); return; }
    download(doc.name+'-gantt-data.js',js,'text/javascript');
    closeModal();
  };
}

// ==== コンテキストメニュー（行/列操作） ====
function showCtx(x,y,items){
  const el=$('ctx');
  el.innerHTML=items.map((it,i)=>it==='-'?'<div class="cx-sep"></div>':`<button data-i="${i}">${it.label}</button>`).join('');
  el.style.left=Math.min(x,innerWidth-200)+'px'; el.style.top=Math.min(y,innerHeight-items.length*32)+'px';
  el.style.display='block';
  el.onclick=e=>{ const b=e.target.closest('button'); if(!b)return;
    hideCtx(); items[+b.dataset.i].fn(); };
}
function hideCtx(){ $('ctx').style.display='none'; }

// ==== フィル（式コピー・連番・日付シリーズ） ====
function performFill(base,dir,count,alt){
  if(count<=0) return false;
  pushUndo();
  const vert=(dir==='down'||dir==='up');
  const sign=(dir==='down'||dir==='right')?1:-1;
  const L=vert? base.r2-base.r1+1 : base.c2-base.c1+1;
  const lanes=[]; if(vert){ for(let c=base.c1;c<=base.c2;c++)lanes.push(c); }
  else { for(let r=base.r1;r<=base.r2;r++)lanes.push(r); }
  let grew=false;
  for(const lane of lanes){
    const pat=[];
    for(let i=0;i<L;i++){
      const r=vert? base.r1+i : lane, c=vert? lane : base.c1+i;
      pat.push({r,c,a:addrOf(r,c)});
    }
    const vs=pat.map(p=>V(p.a)), raws=pat.map(p=>rawOf(p.a));
    const isDate=i=>{ const cl=sheet().cells[pat[i].a];
      return typeof vs[i]==='number'&&((cl&&cl.fmt==='date')||DATE_RE.test(raws[i])); };
    const allDate=pat.every((_,i)=>isDate(i)&&raws[i]!=='');
    const numSeries=L>1&&raws.every((rw,i)=>rw!==''&&rw[0]!=='='&&typeof vs[i]==='number');
    const delta=(L>1&&(numSeries||allDate))? (vs[L-1]-vs[0])/(L-1) : 0;
    for(let k=0;k<count;k++){
      const off=sign>0? L+k : -(k+1);
      const tr=vert? base.r1+off : lane, tc=vert? lane : base.c1+off;
      if(tr<0||tc<0) continue;
      grew=ensureSize(tr,tc)||grew;
      const pi=sign>0? k%L : (L-1)-(k%L);
      const src=pat[pi], raw=raws[pi], srcCell=sheet().cells[src.a];
      let out;
      if(L>1&&(numSeries||allDate)){
        const v=sign>0? vs[L-1]+delta*(k+1) : vs[0]-delta*(k+1);
        out=allDate? serialToYMD(v) : String(+v.toFixed(10));
      }else if(raw&&raw[0]==='='){
        out='='+shiftRelative(raw.slice(1),tr-src.r,tc-src.c);
      }else if(L===1&&allDate){
        out=serialToYMD(vs[0]+sign*(k+1));
      }else if(L===1&&typeof vs[0]==='number'&&raw!==''){
        // 単一の数値はコピー（1セルでは連番かコピーか分からない・Excelと同じ）。
        // 連番にしたい時は1,2の2セルで傾きを作るか、⌥(Option)ドラッグで+1連番
        out=alt? String(vs[0]+sign*(k+1)) : raw;
      }else{
        const mMon=/^(\d{1,2})月$/.exec(raw||'');
        const mNum=/^(.*?)(\d+)$/.exec(raw||'');
        if(mMon) out=(((+mMon[1]-1+sign*(k+1))%12)+12)%12+1+'月';
        else if(mNum&&typeof vs[pi]!=='number') out=mNum[1]+(parseInt(mNum[2],10)+sign*(k+1));
        else out=raw;                       // その他はコピー
      }
      setRaw(addrOf(tr,tc),out);
      if(srcCell&&(srcCell.fmt||srcCell.bold||srcCell.align||srcCell.valign||srcCell.opts||srcCell.wrap)){
        const d2=sheet().cells[addrOf(tr,tc)]||(sheet().cells[addrOf(tr,tc)]={});
        if(srcCell.fmt)d2.fmt=srcCell.fmt; if(srcCell.bold)d2.bold=1;
        if(srcCell.wrap)d2.wrap=1;
        if(srcCell.align)d2.align=srcCell.align; if(srcCell.valign)d2.valign=srcCell.valign;
        if(srcCell.opts)d2.opts=[...srcCell.opts];
      }
    }
  }
  // 選択をフィル結果全体に広げる
  if(vert){ selA={r:base.r1,c:base.c1}; cur={r:base.r2,c:base.c2};
    if(sign>0)cur.r=base.r2+count; else selA.r=base.r1-count; }
  else { selA={r:base.r1,c:base.c1}; cur={r:base.r2,c:base.c2};
    if(sign>0)cur.c=base.c2+count; else selA.c=base.c1-count; }
  astCache.clear(); recalc();
  if(grew) buildGrid(); else refreshCells();
  markDirty();
  return true;
}

// ==== 並べ替え（選択範囲を指定列でソート・先頭行はヘッダなら除外） ====
function sortRange(byCol,asc){
  let s=selRange();
  if(s.r1===s.r2&&s.c1===s.c2) s=usedRange();
  if(byCol<s.c1||byCol>s.c2) return false;
  let start=s.r1;
  const headV=V(addrOf(s.r1,byCol));
  let numBelow=0;
  for(let r=s.r1+1;r<=s.r2;r++) if(typeof V(addrOf(r,byCol))==='number') numBelow++;
  if(typeof headV!=='number'&&numBelow>0) start=s.r1+1;
  const idx=[]; for(let r=start;r<=s.r2;r++) idx.push(r);
  idx.sort((a,b)=>{
    const va=V(addrOf(a,byCol)), vb=V(addrOf(b,byCol));
    const ea=(va==null||va===''), eb=(vb==null||vb==='');
    if(ea&&eb)return 0; if(ea)return 1; if(eb)return -1;   // 空セルは常に最後
    let cmp;
    if(typeof va==='number'&&typeof vb==='number') cmp=va-vb;
    else if(typeof va==='number') cmp=-1;
    else if(typeof vb==='number') cmp=1;
    else cmp=String(va).localeCompare(String(vb),'ja');
    return asc? cmp : -cmp;
  });
  pushUndo();
  const buf={};
  for(let i=0;i<idx.length;i++){
    const srcR=idx[i], dstR=start+i;
    for(let c=s.c1;c<=s.c2;c++){
      const cell=sheet().cells[addrOf(srcR,c)];
      if(cell){ const nc={...cell};
        if(nc.v&&nc.v[0]==='=') nc.v='='+shiftRelative(nc.v.slice(1),dstR-srcR,0);
        buf[addrOf(dstR,c)]=nc;
      } else buf[addrOf(dstR,c)]=null;
    }
  }
  for(const a in buf){ if(buf[a]) sheet().cells[a]=buf[a]; else delete sheet().cells[a]; }
  commit();
  return true;
}

// ==== イベント ====
function setName(n){ doc.name=n; $('hsub').textContent=n; document.title='CalcKit — '+n; }
function tdPos(td){ const m=/^c-(\d+)-(\d+)$/.exec(td.id); return m? {r:+m[1],c:+m[2]} : null; }
let dragSel=false, gripDrag=null, fillDrag=null, rowGripDrag=null;
function fillTarget(e){ // ドラッグ先→方向と数
  const td=document.elementFromPoint(e.clientX,e.clientY)?.closest?.('td');
  if(!td||!td.id.startsWith('c-')) return null;
  const p=tdPos(td), b=fillDrag.base;
  const dDown=p.r-b.r2, dUp=b.r1-p.r, dRight=p.c-b.c2, dLeft=b.c1-p.c;
  const best=Math.max(dDown,dUp,dRight,dLeft);
  if(best<=0) return {dir:'down',count:0};
  if(best===dDown) return {dir:'down',count:dDown};
  if(best===dUp) return {dir:'up',count:dUp};
  if(best===dRight) return {dir:'right',count:dRight};
  return {dir:'left',count:dLeft};
}
function fillGhost(t){
  const b=fillDrag.base, g=$('fill-box');
  if(!t||t.count<=0){ g.style.display='none'; return; }
  const s={r1:b.r1,c1:b.c1,r2:b.r2,c2:b.c2};
  if(t.dir==='down')s.r2=Math.min(sheet().rows-1,b.r2+t.count);
  if(t.dir==='up')s.r1=Math.max(0,b.r1-t.count);
  if(t.dir==='right')s.c2=Math.min(sheet().cols-1,b.c2+t.count);
  if(t.dir==='left')s.c1=Math.max(0,b.c1-t.count);
  positionBox(g,s);
}
function wireEvents(){
  const wrap=$('grid-wrap');
  // フィルハンドル
  $('fill-handle').addEventListener('mousedown',e=>{
    e.preventDefault(); e.stopPropagation();
    if(editing) endEdit(true);
    fillDrag={base:selRange()};
  });
  wrap.addEventListener('mousedown',e=>{
    hideCtx();
    const grip=e.target.closest('.colgrip');
    if(grip){ gripDrag={c:+grip.dataset.c,x:e.clientX,w:colWidth(+grip.dataset.c)}; e.preventDefault(); return; }
    const rgrip=e.target.closest('.rowgrip');
    if(rgrip){ const r=+rgrip.dataset.r;
      rowGripDrag={r,y:e.clientY,h:(sheet().rowH&&sheet().rowH[r])||30};
      e.preventDefault(); e.stopPropagation(); return; }
    const td=e.target.closest('td');
    if(td){ const p=tdPos(td); if(!p)return;
      if(editing) endEdit(true);
      if(e.shiftKey){ if(!selA)selA={...cur}; cur=p; } else { selA=null; cur=p; }
      dragSel=true; paintSel(); e.preventDefault(); return; }
    const rh=e.target.closest('th.rh');
    if(rh){ if(editing)endEdit(true); const r=+rh.dataset.r;
      selA={r,c:0}; cur={r,c:sheet().cols-1}; paintSel(); return; }
    const ch=e.target.closest('th.ch');
    if(ch){ if(editing)endEdit(true); const c=+ch.dataset.c;
      selA={r:0,c}; cur={r:sheet().rows-1,c}; paintSel(); return; }
  });
  window.addEventListener('mousemove',e=>{
    if(fillDrag){ fillGhost(fillTarget(e)); return; }
    if(rowGripDrag){ const h=Math.max(24,rowGripDrag.h+e.clientY-rowGripDrag.y);
      (sheet().rowH||(sheet().rowH={}))[rowGripDrag.r]=h;
      const tr=$('c-'+rowGripDrag.r+'-0'); if(tr) tr.parentElement.style.height=h+'px';
      return; }
    if(gripDrag){ const w=Math.max(40,gripDrag.w+e.clientX-gripDrag.x);
      sheet().colW[gripDrag.c]=w;
      document.querySelectorAll(`#grid-t th.ch[data-c="${gripDrag.c}"]`)
        .forEach(th=>{ th.style.width=w+'px'; th.style.minWidth=w+'px'; });
      return; }
    if(!dragSel) return;
    const td=document.elementFromPoint(e.clientX,e.clientY)?.closest?.('td');
    if(td&&td.id.startsWith('c-')){ const p=tdPos(td);
      if(p&&(p.r!==cur.r||p.c!==cur.c)){ if(!selA)selA={...cur}; cur=p; paintSel(); } }
  });
  window.addEventListener('mouseup',e=>{
    if(fillDrag){ const t=fillTarget(e); $('fill-box').style.display='none';
      if(t&&t.count>0) performFill(fillDrag.base,t.dir,t.count,e.altKey);
      fillDrag=null; return; }
    if(rowGripDrag){ rowGripDrag=null; markDirty(); paintSel(); }
    if(gripDrag){ gripDrag=null; markDirty(); } dragSel=false; });
  wrap.addEventListener('dblclick',e=>{ const td=e.target.closest('td');
    if(td&&tdPos(td)){ startEdit(); } });
  wrap.addEventListener('contextmenu',e=>{
    const rh=e.target.closest('th.rh'), ch=e.target.closest('th.ch');
    if(!rh&&!ch) return;
    e.preventDefault();
    if(rh){ const r=+rh.dataset.r;
      showCtx(e.clientX,e.clientY,[
        {label:'上に行を挿入',fn:()=>insertRow(r)},
        {label:'下に行を挿入',fn:()=>insertRow(r+1)},'-',
        {label:`行${r+1}を削除`,fn:()=>deleteRow(r)}]); }
    else { const c=+ch.dataset.c;
      showCtx(e.clientX,e.clientY,[
        {label:'左に列を挿入',fn:()=>insertCol(c)},
        {label:'右に列を挿入',fn:()=>insertCol(c+1)},'-',
        {label:`${colName(c)}列で昇順に並べ替え`,fn:()=>sortRange(c,true)},
        {label:`${colName(c)}列で降順に並べ替え`,fn:()=>sortRange(c,false)},'-',
        {label:`${colName(c)}列を削除`,fn:()=>deleteCol(c)}]); }
  });
  document.addEventListener('mousedown',e=>{ if(!e.target.closest('#ctx')) hideCtx(); });

  // キーボード
  document.addEventListener('keydown',e=>{
    const inInput=e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT';
    if(editing||inInput) return;
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){ e.preventDefault(); e.shiftKey?redo():undo(); return; }
    if(e.metaKey||e.ctrlKey) return; // ⌘C/V/Xはcopy/pasteイベント側
    const mv={ArrowUp:[-1,0],ArrowDown:[1,0],ArrowLeft:[0,-1],ArrowRight:[0,1]}[e.key];
    if(mv){ e.preventDefault(); moveCur(mv[0],mv[1],e.shiftKey); return; }
    if(e.key==='Enter'){ e.preventDefault(); startEdit(); return; }
    if(e.key==='F2'){ e.preventDefault(); startEdit(); return; }
    if(e.key==='Tab'){ e.preventDefault(); moveCur(0,e.shiftKey?-1:1); return; }
    if(e.key==='Delete'||e.key==='Backspace'){ e.preventDefault();
      pushUndo(); const s=selRange();
      for(let r=s.r1;r<=s.r2;r++) for(let c=s.c1;c<=s.c2;c++) setRaw(addrOf(r,c),'');
      commit(); return; }
    if(e.key==='Escape'){ selA=null; paintSel(); return; }
    if(e.key.length===1&&!e.altKey){ startEdit(e.key); }
  });
  // セル編集
  ed().addEventListener('keydown',e=>{
    if(e.key==='Enter'){ e.preventDefault(); endEdit(true,'down'); }
    else if(e.key==='Tab'){ e.preventDefault(); endEdit(true,'right'); }
    else if(e.key==='Escape'){ e.preventDefault(); endEdit(false); }
    e.stopPropagation();
  });
  ed().addEventListener('blur',()=>{ if(editing) endEdit(true); });
  ed().addEventListener('input',()=>{ $('fx').value=ed().value; });
  // 数式バー
  $('fx').addEventListener('keydown',e=>{
    if(e.key==='Enter'){ e.preventDefault(); setCellAndRecalc(addrOf(cur.r,cur.c),$('fx').value); moveCur(1,0); $('fx').blur(); }
    else if(e.key==='Escape'){ e.preventDefault(); updateFxBar(); $('fx').blur(); }
  });
  // クリップボード
  document.addEventListener('copy',e=>{ if(editing||document.activeElement.tagName==='INPUT')return; copySel(e); });
  document.addEventListener('cut',e=>{ if(editing||document.activeElement.tagName==='INPUT')return; copySel(e,true); });
  document.addEventListener('paste',e=>{
    if(editing||document.activeElement.tagName==='INPUT')return;
    const t=e.clipboardData&&e.clipboardData.getData('text/plain');
    if(t){ e.preventDefault(); pasteAt(t); }
  });

  // プルダウン▾: クリックで選択肢メニュー
  $('dd-btn').addEventListener('mousedown',e=>{ e.preventDefault(); e.stopPropagation(); });
  $('dd-btn').addEventListener('click',e=>{
    e.stopPropagation();
    const cl=sheet().cells[addrOf(cur.r,cur.c)];
    if(!cl||!cl.opts) return;
    const rc=$('dd-btn').getBoundingClientRect();
    showCtx(rc.left,rc.bottom+2,cl.opts.map(o=>({label:escHtml(o),fn:()=>setCellAndRecalc(addrOf(cur.r,cur.c),o)})));
  });
  // 書式ボタン
  $('fbold').onclick=toggleBold;
  $('fnum').onclick=()=>applyFmt('num');
  $('fyen').onclick=()=>applyFmt('yen');
  $('fpct').onclick=()=>applyFmt('pct');
  $('fdec').onclick=()=>applyFmt('dec2');
  $('fdate').onclick=()=>applyFmt('date');
  $('fclr').onclick=()=>applyFmt(null);
  $('fal').onclick=()=>applyAlign('align','l');
  $('fac').onclick=()=>applyAlign('align','c');
  $('far').onclick=()=>applyAlign('align','r');
  $('fvt').onclick=()=>applyAlign('valign','t');
  $('fvm').onclick=()=>applyAlign('valign','m');
  $('fvb').onclick=()=>applyAlign('valign','b');
  $('fwrap').onclick=toggleWrap;
  $('fdd').onclick=showOptsModal;
  $('frowa').onclick=()=>{ pushUndo(); sheet().rows+=10; buildGrid(); markDirty(); };
  $('fcola').onclick=()=>{ pushUndo(); sheet().cols+=4; buildGrid(); markDirty(); };
  // ヘッダー
  $('btmpl').onchange=e=>{ const v=e.target.value; e.target.value='';
    if(v&&confirm('現在のシートを置き換えます。よろしいですか？（⌘Zで戻せます）')){
      clearSaveTarget(); loadTemplate(v);
    } };
  $('bopen').onclick=openDocument;
  $('bcsv').onclick=()=>download(doc.name+'.csv','\ufeff'+buildCSV(),'text/csv');
  $('bxls').onclick=exportXls;
  $('bchart').onclick=showChartModal;
  $('bslide').onclick=()=>download(doc.name+'-slide.html',buildSlideHtml(),'text/html');
  $('bgantt').onclick=showGanttModal;
  $('bsave').onclick=e=>saveDocument(e.shiftKey);
  $('breset').onclick=()=>{ if(!confirm('保存内容を消してデモシートに戻します。よろしいですか？'))return;
    localStorage.removeItem(STORAGE_KEY); clearSaveTarget(); loadTemplate('pl'); };
  // シート名
  $('hsub').onclick=()=>{
    const cu=$('hsub'); if(cu.querySelector('input'))return;
    const inp=document.createElement('input'); inp.value=doc.name;
    cu.textContent=''; cu.appendChild(inp); inp.focus(); inp.select();
    const done=ok=>{ const v=ok? inp.value.trim():doc.name; setName(v||doc.name); markDirty(); };
    inp.onkeydown=e=>{ if(e.key==='Enter')done(true); if(e.key==='Escape')done(false); e.stopPropagation(); };
    inp.onblur=()=>done(true);
  };
  window.addEventListener('resize',()=>{ if(editing)endEdit(true); });
}

// ==== 公開API（検証・Kiro操作用） ====
window.CalcKit={
  get doc(){ return doc; },
  setCell(a,v){ setCellAndRecalc(a.toUpperCase(),v); },
  getRaw(a){ return rawOf(a.toUpperCase()); },
  val(a){ return V(a.toUpperCase()); },
  valOn(sheetName,a){ const i=sheetIdx(sheetName); return i<0? undefined : vals[i+'!'+a.toUpperCase()]; },
  addSheet,switchSheet,renameSheet,deleteSheet,dupSheet,
  sheetNames(){ return doc.sheets.map(s=>s.name); },
  get activeSheet(){ return doc.active; },
  display(a){ return displayOf(a.toUpperCase()); },
  select(a1,a2){ const p=parseAddr(a1.toUpperCase()); cur={r:p.r,c:p.c};
    selA=a2? (()=>{ const q=parseAddr(a2.toUpperCase()); const t={...cur}; cur={r:q.r,c:q.c}; return t; })() : null;
    paintSel(); },
  getSel(){ return selRange(); },
  insertRow,deleteRow,insertCol,deleteCol,undo,redo,
  fill(dir,count,alt){ return performFill(selRange(),dir,count,alt); },
  sort(byCol,asc){ return sortRange(byCol,asc); },
  align(prop,val){ applyAlign(prop,val); },
  setOpts(list){ setOpts(list); },
  copySel(){ copySel(null); }, pasteText(t){ pasteAt(t); },
  buildCSV,buildSlideHtml,buildChartSlideHtml,buildGanttData,buildGanttPayload,buildChartData,buildPieData,
  loadTemplate,usedRange,
  setName(n){ setName(n); markDirty(); },
  recalcAll(){ astCache.clear(); recalc(); refreshCells(); }
};

// ==== グラフのスライド化（DKのSVGを焼き込んで1枚に） ====
function buildChartSlideHtml(type){
  if(!window.DK) throw new Error('DashboardKitが見つからない');
  const d=buildChartData();
  if(!d.series.length) throw new Error('グラフにできる数値範囲がない');
  const host=document.createElement('div');
  host.style.cssText='position:fixed;left:-3000px;top:0;width:1152px;background:#fafafa';
  document.body.appendChild(host);
  try{
    let opts;
    if(type==='pie'||type==='donut'){
      const p=buildPieData();
      if(!p.slices.length) throw new Error('構成比にできる系列がない');
      opts={type,series:p.slices};
      if(type==='donut') opts.centerLabel=fmtNum(p.slices.reduce((a,b)=>a+b.value,0),'num')+(p.unit||'');
    }else{
      opts={type,labels:d.labels,series:d.series,height:500};
    }
    if(d.unit) opts.unit=d.unit;
    DK.chart(host,opts);
    const svg=host.querySelector('svg');
    if(!svg) throw new Error('グラフSVGが取れない');
    // テーマのCSS変数はスライド単体で解決できないため、computed styleを属性に焼き込む
    const els=[svg,...svg.querySelectorAll('*')];
    for(const el of els){
      const cs=getComputedStyle(el);
      for(const p of ['fill','stroke','stroke-width','stroke-dasharray','font-family',
                      'font-size','font-weight','opacity','fill-opacity','stroke-opacity','text-anchor']){
        const v=cs.getPropertyValue(p);
        if(v&&v!==''&&v!=='normal'&&v!=='auto') el.setAttribute(p,v);
      }
    }
    // 実寸を測ってアス比を保ったままスライド領域（1152×500）に収める
    const bw=svg.clientWidth||1152, bh=svg.clientHeight||500;
    if(!svg.getAttribute('viewBox')) svg.setAttribute('viewBox','0 0 '+bw+' '+bh);
    const H=500, W=Math.min(1152,Math.round(bw*H/bh)||1152);
    const X=64+Math.round((1152-W)/2);
    svg.setAttribute('width',W); svg.setAttribute('height',H);
    const svgStr=new XMLSerializer().serializeToString(svg);
    // 凡例（DKの凡例はHTML側なので自前で置く。円/ドーナツはSVG内にラベルがあるので不要）
    const theme=DK.getTheme&&DK.getTheme();
    const colors=(theme&&theme.chart&&theme.chart.colors)||['#21537f','#c53030','#38a169','#d69e2e','#5e5e5e','#183251'];
    let legend='';
    if(type!=='pie'&&type!=='donut'){
      let lx=64;
      d.series.forEach((s,i)=>{
        const wpx=Math.min(300,s.name.length*17+40);
        const col=colors[i%colors.length];
        legend+=`<div class="tb" data-x="${lx}" data-y="112" data-w="${wpx}" data-h="26" data-font-size="16" data-bold="1" data-color="${col}" style="left:${lx}px;top:112px;width:${wpx}px;height:26px;font-size:16px;font-weight:700;color:${col}">● ${escHtml(s.name)}</div>`;
        lx+=wpx+10;
      });
    }
    const editJs=new URL('../SlideKit/slide-edit.js',location.href).href;
    return `<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>${escHtml(doc.name)}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Yu Gothic','游ゴシック','Noto Sans JP',sans-serif;background:#2d3748;display:flex;flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;background:#fafafa}
.tb{position:absolute;overflow:hidden;line-height:1.5}
</style></head>
<body>
<!-- SLIDE: ${escHtml(doc.name)}（グラフ） -->
<div class="slide" data-bg="#fafafa" style="background:#fafafa">
  <div class="tb" data-x="64" data-y="48" data-w="1152" data-h="44" data-font-size="28" data-bold="1" data-color="#183251"
       style="left:64px;top:48px;width:1152px;height:44px;font-size:28px;font-weight:700;color:#183251">${escHtml(doc.name)}</div>
  ${legend}
  <div data-x="${X}" data-y="150" data-w="${W}" data-h="${H}"
       style="position:absolute;left:${X}px;top:150px;width:${W}px;height:${H}px">${svgStr}</div>
</div>
<!-- /SLIDE -->
<script src="${editJs}"><\/script>
</body>
</html>`;
  }finally{ host.remove(); }
}

// ==== SlideKit往復（「＋表(CalcKit)」から開かれた時だけ青ボタンを出す） ====
function toast(msg){
  const n=document.createElement('div');
  n.textContent=msg;
  n.style.cssText='position:fixed;bottom:48px;left:50%;transform:translateX(-50%);background:rgba(22,42,66,.95);color:#fff;padding:10px 22px;border-radius:8px;font-size:14px;z-index:9999';
  document.body.appendChild(n); setTimeout(()=>n.remove(),3500);
}
function initSlideKitReturn(){
  let ret=null;
  try{
    const r=JSON.parse(localStorage.getItem('skCalcReturn')||'null');
    if(r&&r.deck&&Date.now()-r.ts<6*3600*1000) ret=r;
  }catch(e){}
  if(!ret) return;
  const hdr=document.querySelector('header'); if(!hdr) return;
  const btn=document.createElement('button');
  btn.className='hbtn'; btn.id='bslidekit';
  btn.textContent='スライドへ追加';
  btn.title='選択範囲（単一セルならカーソル周辺の塊）を表かグラフのスライド1枚にしてデッキへ挿入';
  btn.style.cssText='background:#2b6cb0;color:#fff;border-color:#2b6cb0';
  hdr.appendChild(btn);
  function send(html){
    const doc2=new DOMParser().parseFromString(html,'text/html');
    const sl=doc2.querySelector('.slide');
    if(!sl) throw new Error('slide生成失敗');
    localStorage.setItem('skCalcSlide',JSON.stringify({deck:ret.deck,html:sl.outerHTML,ts:Date.now()}));
    toast('デッキに追加した。SlideKitのタブへ戻って確認');
  }
  btn.addEventListener('click',()=>{
    const dk=!!window.DK;
    openModal(`<h3>スライドへ追加</h3>
      <label>形式</label>
      <select id="sk-kind">
        <option value="table">表（PPTXでも編集できるネイティブの表）</option>
        ${dk?`<option value="bar">グラフ: 棒</option>
        <option value="line">グラフ: 折れ線</option>
        <option value="smooth">グラフ: 折れ線（曲線）</option>
        <option value="pie">グラフ: 円（系列合計の構成比）</option>
        <option value="donut">グラフ: ドーナツ</option>`:''}
      </select>
      <div class="note">対象は選択範囲（単一セルならカーソル周辺のデータ塊）。
      グラフは画像として入る（PPTX変換時にPNG化・タイトルと凡例の文字は編集可能）</div>
      <div class="modal-btns"><button class="m-cancel" id="m-cancel">キャンセル</button>
      <button class="m-save" id="m-go">追加</button></div>`);
    $('m-go').onclick=()=>{
      try{
        const k=$('sk-kind').value;
        send(k==='table'? buildSlideHtml() : buildChartSlideHtml(k));
        closeModal();
      }catch(e){ toast('受け渡し失敗: '+e.message); }
    };
  });
}

// ==== GanttKitから受け取る（「表(CalcKit)で開く」で開かれた時） ====
function initGanttImport(){
  if(location.hash!=='#fromGantt') return false;
  let p=null;
  try{ p=JSON.parse(localStorage.getItem('gkCalcSheet')||'null'); }catch(_){}
  if(!p||!p.doc||!p.doc.sheets||Date.now()-p.ts>6*3600*1000) return false;
  try{ localStorage.removeItem('gkCalcSheet'); }catch(_){}
  doc=normalizeDoc(p.doc);
  history.replaceState(null,'',location.pathname);   // 再読込で二重取り込みしない
  return true;
}

// ==== 起動 ====
function init(){
  const fromGantt=initGanttImport();
  if(!fromGantt){
    const saved=localStorage.getItem(STORAGE_KEY);
    if(saved){ try{ const d=JSON.parse(saved); if(d&&(d.cells||d.sheets)) doc=normalizeDoc(d); }catch(_){ doc=null; } }
  }
  if(!doc) doc=tmplPL();
  recalc(); buildGrid(); setName(doc.name);
  wireEvents(); paintSel(); initSlideKitReturn();
  if(fromGantt){ markDirty(); toast('GanttKitの計画を表として開いた（日数はF列の式。ガントに戻すには「ガント書き出し」）'); }
}
init();
})();
