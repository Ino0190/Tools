// CalcKit エンジン — 表計算（式・書式・入出力・キット連携）
// evalは使わない（式は自前のトークナイザ＋Prattパーサで評価）
(function(){
'use strict';

const PARAMS=new URLSearchParams(location.search);
const READONLY=PARAMS.get('readonly')==='1';
const REVIEW=PARAMS.get('review')==='1';
const EMBED=PARAMS.get('embed')==='1';

// ==== アドレス変換 ====
function colName(i){ let s=''; i++; while(i>0){ i--; s=String.fromCharCode(65+i%26)+s; i=Math.floor(i/26);} return s; }
function colIndex(name){ let n=0; for(const ch of name) n=n*26+(ch.charCodeAt(0)-64); return n-1; }
function addrOf(r,c){ return colName(c)+(r+1); }
const REF_RE=/(\$?)([A-Z]+)(\$?)([0-9]+)/g;
function parseAddr(a){ const m=/^(\$?)([A-Z]+)(\$?)([0-9]+)$/.exec(a); if(!m) return null;
  return {c:colIndex(m[2]), r:parseInt(m[4],10)-1, absC:m[1]==='$', absR:m[3]==='$'}; }

// ==== ドキュメント（マルチシート） ====
const STORE_NS=PARAMS.get('ns')||'';   // 埋め込みごとに保存領域を分ける（1ページに複数のreview埋め込みを置くため）
const STORAGE_KEY=(REVIEW?'calckit_review_v12':'calckit_v1')+(STORE_NS?'_'+STORE_NS:'');
let restoredDocument=false;
let doc=null;           // {name, sheets:[{name,rows,cols,colW,rowH,cells:{addr:{v,fmt,..}}}], active}
let vals={};            // 計算結果 "シートindex!addr" -> number|string|{e:'#..'}
let cur={r:0,c:0};      // カーソル
let selA=null;          // 選択アンカー {r,c}（nullなら単一セル）
let undoStack=[], redoStack=[];
let dirty=false;
let lastImport=null;    // 直近の .xlsx 取り込みの要約 {sheets, formulas, valued}

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
function loadDocument(raw){
  if(!raw||typeof raw!=='object'||(!raw.sheets&&!raw.cells)) throw new Error('CalcKit文書ではありません');
  const cloned=JSON.parse(JSON.stringify(raw));
  doc=normalizeDoc(cloned);
  if(!doc.sheets.length) throw new Error('シートがありません');
  undoStack=[]; redoStack=[]; cur={r:0,c:0}; selA=null; dirty=false;
  astCache.clear(); recalc(); buildGrid(); setName(doc.name);
  if($('bsave')) $('bsave').classList.remove('dirty');
  setSaveStatus(READONLY?'読み取り専用':'外部文書');
  restoredDocument=true;
  if(REVIEW)autosave();
  return true;
}
function cell(a){ return sheet().cells[a]; }
function rawOf(a){ const c=sheet().cells[a]; return c? (c.v??'') : ''; }
function canonFormula(f){ // 引用符の外だけ大文字化（参照・関数名の正規化。文字列は保持）
  let out='',q=false;
  for(const ch of f){ if(ch==='"'){ q=!q; out+=ch; } else out+=q?ch:ch.toUpperCase(); }
  return out;
}
function cellEditable(a){
  if(READONLY)return false;
  if(!REVIEW)return true;
  const current=sheet().cells[a];
  return !(current&&current.locked);
}
function setRaw(a,v){
  if(!cellEditable(a)) return false;
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

// ==== 関数の追加（2026-11-14）: 論理・条件集計・INDEX/MATCH・日付・数値・文字 ====
// FUNCS には「引数を全部値にして渡せばよい」関数、SPECIAL_FUNCS には範囲そのものや遅延評価が要る関数。
function toDate(v){ // 日付引数: シリアル値の数か 'YYYY-MM-DD' の文字 → シリアル値
  if(isErr(v)) return v;
  if(typeof v==='number') return Math.floor(v);
  if(v==null||v==='') return {e:'#VALUE!'};
  const d=parseDateRaw(v); if(d!=null) return d;
  const n=parseFloat(String(v)); return isNaN(n)? {e:'#VALUE!'} : Math.floor(n);
}
function ymdOf(serial){ const dt=new Date(Math.round(serial-25569)*86400000); return {y:dt.getUTCFullYear(),m:dt.getUTCMonth()+1,d:dt.getUTCDate(),w:dt.getUTCDay()}; }
function monthEndSerial(y,m){ return dateToSerial(y,m+1,0); } // 翌月0日＝当月末（Date.UTC が繰り上げを吸収）
function addMonths(serial,n){ const t=ymdOf(serial); const tot=t.y*12+(t.m-1)+n; const y=Math.floor(tot/12), m=tot%12+1;
  const last=ymdOf(monthEndSerial(y,m)).d; return dateToSerial(y,m,Math.min(t.d,last)); }
function strOf(v){ return isErr(v)? v : (v==null? '' : String(v)); }
function numArg(a,i,def){ return toNum(a[i]==null||a[i]===''? (def??0) : a[i]); }
function textFmt(n,fmt){ // TEXT(値, 書式) の最低限: 0 / 0.00 / #,##0 / #,##0.00 / 0% / 0.0% / yyyy-mm-dd / yyyy/m/d / m/d / yyyy年m月d日
  const f=String(fmt);
  if(/[ymd]/i.test(f)){ const t=ymdOf(n); const p2=x=>String(x).padStart(2,'0');
    return f.replace(/yyyy/gi,t.y).replace(/mm/g,p2(t.m)).replace(/dd/g,p2(t.d)).replace(/m/g,t.m).replace(/d/g,t.d); }
  const pct=/%$/.test(f); let x=pct? n*100 : n;
  const dm=/\.(0+)/.exec(f); const dec=dm? dm[1].length : 0;
  let out=Math.abs(x).toFixed(dec);
  if(f.includes(',')) out=out.replace(/^(\d+)/,m=>m.replace(/\B(?=(\d{3})+(?!\d))/g,','));
  return (x<0?'-':'')+out+(pct?'%':'');
}
Object.assign(FUNCS,{
  // 論理
  NOT:a=>{ const n=toNum(a[0]); return isErr(n)?n:(n===0?1:0); },
  TRUE:()=>1, FALSE:()=>0,
  ISBLANK:a=>(a[0]==null||a[0]==='')?1:0,
  ISNUMBER:a=>(typeof a[0]==='number')?1:0,
  ISTEXT:a=>(typeof a[0]==='string'&&a[0]!=='')?1:0,
  ISERROR:a=>isErr(a[0])?1:0,
  // 日付
  YEAR:a=>{ const d=toDate(a[0]); return isErr(d)?d:ymdOf(d).y; },
  MONTH:a=>{ const d=toDate(a[0]); return isErr(d)?d:ymdOf(d).m; },
  DAY:a=>{ const d=toDate(a[0]); return isErr(d)?d:ymdOf(d).d; },
  EOMONTH:a=>{ const d=toDate(a[0]),n=numArg(a,1,0); if(isErr(d))return d; if(isErr(n))return n;
    const t=ymdOf(addMonths(d,Math.trunc(n))); return monthEndSerial(t.y,t.m); },
  EDATE:a=>{ const d=toDate(a[0]),n=numArg(a,1,0); if(isErr(d))return d; if(isErr(n))return n; return addMonths(d,Math.trunc(n)); },
  DAYS:a=>{ const e=toDate(a[0]),s=toDate(a[1]); if(isErr(e))return e; if(isErr(s))return s; return e-s; },
  WEEKDAY:a=>{ const d=toDate(a[0]),t=numArg(a,1,1); if(isErr(d))return d; if(isErr(t))return t;
    const w=ymdOf(d).w; return t===2? (w===0?7:w) : t===3? (w===0?6:w-1) : w+1; },
  NETWORKDAYS:a=>{ const s=toDate(a[0]),e=toDate(a[1]); if(isErr(s))return s; if(isErr(e))return e;
    const lo=Math.min(s,e),hi=Math.max(s,e); let n=0;
    for(let d=lo; d<=hi; d++){ const w=ymdOf(d).w; if(w!==0&&w!==6) n++; }
    return s<=e? n : -n; },
  // 数値
  MOD:a=>{ const x=toNum(a[0]),y=toNum(a[1]); if(isErr(x))return x; if(isErr(y))return y; if(y===0)return {e:'#DIV/0!'}; return x-y*Math.floor(x/y); },
  POWER:a=>{ const x=toNum(a[0]),y=toNum(a[1]); if(isErr(x))return x; if(isErr(y))return y; return Math.pow(x,y); },
  PRODUCT:a=>{ const n=numsOf(a); return isErr(n)?n:n.reduce((s,x)=>s*x,1); },
  CEILING:a=>{ const x=toNum(a[0]),g=numArg(a,1,1); if(isErr(x))return x; if(isErr(g))return g; if(g===0)return 0; return Math.ceil(x/g-1e-12)*g; },
  FLOOR:a=>{ const x=toNum(a[0]),g=numArg(a,1,1); if(isErr(x))return x; if(isErr(g))return g; if(g===0)return {e:'#DIV/0!'}; return Math.floor(x/g+1e-12)*g; },
  // 文字
  LEN:a=>{ const s=strOf(a[0]); return isErr(s)?s:[...s].length; },
  LEFT:a=>{ const s=strOf(a[0]),n=numArg(a,1,1); if(isErr(s))return s; if(isErr(n))return n; return [...s].slice(0,Math.max(0,n)).join(''); },
  RIGHT:a=>{ const s=strOf(a[0]),n=numArg(a,1,1); if(isErr(s))return s; if(isErr(n))return n; const c=[...s]; return n<=0? '' : c.slice(-n).join(''); },
  MID:a=>{ const s=strOf(a[0]),st=toNum(a[1]),n=toNum(a[2]); if(isErr(s))return s; if(isErr(st))return st; if(isErr(n))return n;
    if(st<1||n<0) return {e:'#VALUE!'}; return [...s].slice(st-1,st-1+n).join(''); },
  UPPER:a=>{ const s=strOf(a[0]); return isErr(s)?s:s.toUpperCase(); },
  LOWER:a=>{ const s=strOf(a[0]); return isErr(s)?s:s.toLowerCase(); },
  TRIM:a=>{ const s=strOf(a[0]); return isErr(s)?s:s.replace(/\s+/g,' ').trim(); },
  CONCATENATE:a=>{ let out=''; for(const v of a){ if(isErr(v))return v; out+=displayVal(v); } return out; },
  CONCAT:a=>{ let out=''; for(const v of a){ if(isErr(v))return v; out+=displayVal(v); } return out; },
  VALUE:a=>{ if(a[0]==null||a[0]==='') return 0; const d=parseDateRaw(a[0]); if(d!=null) return d; return toNum(a[0]); },
  TEXT:a=>{ const v=a[0]; if(isErr(v))return v; if(a[1]==null||a[1]==='') return displayVal(v);
    if(typeof v!=='number'){ const d=parseDateRaw(v); if(d==null) return displayVal(v); return textFmt(d,a[1]); }
    return textFmt(v,a[1]); },
});
// 範囲をそのまま受ける・引数を遅延評価する関数
function rangeArg(nd,si){ const v=evalNode(nd,si); if(!v||!v.rng) return {e:'#VALUE!'}; return v; }
function rangeGrid(nd){ // 範囲ノード → 行数・列数・左上（INDEX 用）
  if(!nd||nd.n!=='range') return null;
  const A=parseAddr(nd.a),B=parseAddr(nd.b);
  return {r1:Math.min(A.r,B.r),c1:Math.min(A.c,B.c),rows:Math.abs(A.r-B.r)+1,cols:Math.abs(A.c-B.c)+1};
}
function critsMatch(pairs,i){ // [{rng,si,crit}] の全部に i 番目が合うか
  for(const p of pairs){ const v=cellValue(p.rng[i],p.si); if(isErr(v)) return v; if(!matchCrit(v,p.crit)) return false; }
  return true;
}
function readCritPairs(nd,si,from){ // (範囲, 条件)* を読む
  const pairs=[];
  for(let k=from;k<nd.args.length;k+=2){
    const rv=rangeArg(nd.args[k],si); if(isErr(rv)) return rv;
    const crit=evalScalar(nd.args[k+1]??{n:'str',v:''},si); if(isErr(crit)) return crit;
    pairs.push({rng:rv.rng,si:rv.si,crit});
  }
  return pairs;
}
const SPECIAL_FUNCS={
  IFERROR:(nd,si)=>{ const v=evalScalar(nd.args[0]??{n:'num',v:0},si); return isErr(v)? evalScalar(nd.args[1]??{n:'str',v:''},si) : v; },
  IFS:(nd,si)=>{ for(let k=0;k+1<nd.args.length;k+=2){ const c=toNum(evalScalar(nd.args[k],si)); if(isErr(c))return c; if(c!==0) return evalScalar(nd.args[k+1],si); } return {e:'#N/A'}; },
  AND:(nd,si)=>{ let any=false; for(const a of nd.args){ for(const v of flatten(a,si)){ if(isErr(v))return v; if(v==null||v==='')continue; const n=toNum(v); if(isErr(n))continue; any=true; if(n===0) return 0; } } return any?1:{e:'#VALUE!'}; },
  OR:(nd,si)=>{ let any=false; for(const a of nd.args){ for(const v of flatten(a,si)){ if(isErr(v))return v; if(v==null||v==='')continue; const n=toNum(v); if(isErr(n))continue; any=true; if(n!==0) return 1; } } return any?0:{e:'#VALUE!'}; },
  SUMIFS:(nd,si)=>{ const sv=rangeArg(nd.args[0],si); if(isErr(sv))return sv; const pairs=readCritPairs(nd,si,1); if(isErr(pairs))return pairs;
    let acc=0; for(let i=0;i<sv.rng.length;i++){ const m=critsMatch(pairs,i); if(isErr(m))return m; if(m){ const x=cellValue(sv.rng[i],sv.si); if(typeof x==='number') acc+=x; } } return acc; },
  COUNTIFS:(nd,si)=>{ const pairs=readCritPairs(nd,si,0); if(isErr(pairs))return pairs; if(!pairs.length) return {e:'#VALUE!'};
    let n=0; for(let i=0;i<pairs[0].rng.length;i++){ const m=critsMatch(pairs,i); if(isErr(m))return m; if(m) n++; } return n; },
  AVERAGEIF:(nd,si)=>{ const rv=rangeArg(nd.args[0],si); if(isErr(rv))return rv; const crit=evalScalar(nd.args[1],si); if(isErr(crit))return crit;
    let av=rv; if(nd.args[2]){ av=rangeArg(nd.args[2],si); if(isErr(av))return av; }
    let acc=0,n=0; for(let i=0;i<rv.rng.length;i++){ const v=cellValue(rv.rng[i],rv.si); if(isErr(v))return v;
      if(matchCrit(v,crit)){ const x=cellValue(av.rng[i]??rv.rng[i],av.si); if(typeof x==='number'){ acc+=x; n++; } } }
    return n? acc/n : {e:'#DIV/0!'}; },
  INDEX:(nd,si)=>{ const rg=nd.args[0]; const g=rangeGrid(rg); if(!g) return {e:'#VALUE!'}; const rsi=resolveSheet(rg,si); if(rsi<0) return {e:'#REF!'};
    let r=toNum(evalScalar(nd.args[1]??{n:'num',v:1},si)); if(isErr(r))return r;
    let c=nd.args[2]!=null? toNum(evalScalar(nd.args[2],si)) : null; if(isErr(c))return c;
    if(c==null){ if(g.rows===1){ c=r; r=1; } else c=1; }        // 1行の範囲なら2番目の引数は列番号
    if(r<1||r>g.rows||c<1||c>g.cols) return {e:'#REF!'};
    return cellValue(addrOf(g.r1+r-1,g.c1+c-1),rsi); },
  MATCH:(nd,si)=>{ const key=evalScalar(nd.args[0],si); if(isErr(key))return key; const rv=rangeArg(nd.args[1],si); if(isErr(rv))return rv;
    const t=nd.args[2]!=null? toNum(evalScalar(nd.args[2],si)) : 1; if(isErr(t))return t;
    const ks=(typeof key==='string')? key.toLowerCase() : key; let best=-1;
    for(let i=0;i<rv.rng.length;i++){ const v=cellValue(rv.rng[i],rv.si); if(isErr(v)||v==null||v==='') continue;
      const vs=(typeof v==='string')? v.toLowerCase() : v;
      if(typeof vs!==typeof ks) continue;
      if(vs===ks) return i+1;
      if(t>0&&vs<ks) best=i; else if(t<0&&vs>ks) best=i; }
    return (t!==0&&best>=0)? best+1 : {e:'#N/A'}; },
  SUMPRODUCT:(nd,si)=>{ const rs=[]; for(const a of nd.args){ const v=rangeArg(a,si); if(isErr(v))return v; rs.push(v); }
    if(!rs.length) return 0; const n=rs[0].rng.length; if(rs.some(r=>r.rng.length!==n)) return {e:'#VALUE!'};
    let acc=0; for(let i=0;i<n;i++){ let p=1; for(const r of rs){ const x=cellValue(r.rng[i],r.si); if(isErr(x))return x; p*=(typeof x==='number')? x : 0; } acc+=p; } return acc; },
  RANK:(nd,si)=>{ const v=toNum(evalScalar(nd.args[0],si)); if(isErr(v))return v; const rv=rangeArg(nd.args[1],si); if(isErr(rv))return rv;
    const asc=nd.args[2]!=null? toNum(evalScalar(nd.args[2],si))!==0 : false;
    let n=0,found=false; for(const a of rv.rng){ const x=cellValue(a,rv.si); if(typeof x!=='number') continue; if(x===v) found=true; if(asc? x<v : x>v) n++; }
    return found? n+1 : {e:'#N/A'}; },
};

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
  const sp=SPECIAL_FUNCS[f];           // 範囲や遅延評価が要る関数（2026-11-14 追加分）
  if(sp) return sp(nd,si);
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
  const tableWidth=48+Array.from({length:sheet().cols},(_,c)=>colWidth(c)).reduce((a,b)=>a+b,0);
  t.style.width=tableWidth+'px'; t.style.minWidth=tableWidth+'px';
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
  refreshCells();
  if(sheet().filter) applyFilterView(); else { fltHidden=0; markFilterCols(); }
  paintSel(); renderTabs();
}
function refreshCells(){
  prepBars();                                  // 条件付き書式データバーの範囲内 最小/最大を先に求める
  numCells.length=0;                           // この描画で見つけた数のセル（C2: 幅に入らない数の ### 表示に使う）
  for(let r=0;r<sheet().rows;r++) for(let c=0;c<sheet().cols;c++){
    const a=addrOf(r,c), td=$('c-'+r+'-'+c); if(!td) continue;
    const v=V(a), shown=displayOf(a);
    const fhd=isFilterHeader(r,c);
    if(fhd) paintFilterHead(td,c,shown); else { td.textContent=shown; td.title=''; }  // 文字セル・空セルはホバーなし（### の名残を消す）
    const cl=sheet().cells[a];
    const al=cl&&cl.align? {l:'al',c:'ac',r:'ar'}[cl.align]||'' : '';
    const vl=cl&&cl.valign? {t:'vt',m:'vm',b:'vb'}[cl.valign]||'' : '';
    const spill=!fhd&&shown!==''&&typeof v!=='number'&&!isErr(v)&&!(cl&&cl.wrap)&&(!cl||!cl.align||cl.align==='l');
    const stop=shown!=='';
    td.className=(fhd?'fhd ':'')+(typeof v==='number'?'num ':'')+(isErr(v)?'err ':'')+(cl&&cl.bold?'bold ':'')
      +(al?al+' ':'')+(vl?vl+' ':'')+(cl&&cl.wrap?'wrap ':'')+(cl&&cl.fill?'fill-'+cl.fill+' ':'')+(cl&&cl.borderTop?'bt-'+cl.borderTop+' ':'')
      +(spill?'spill ':'')+(stop?'spill-stop ':'');
    // 数のセルだけ控える。文字セルは今までどおりスピル・折り返しのまま（### にはしない）。
    if(!fhd&&typeof v==='number'&&!isErr(v)) numCells.push({td,c,full:shown});
    applyCellStyle(td,a,r,c,v,cl,fhd);         // 静的なセル色（xlsx取り込み/Kiro生成）＋条件付き書式
  }
  applyNumClip();                              // C2: 列幅に入らない数は ### にして全体値を title へ（2026-11-15）
  paintSel();
}
// ==== C2: 幅に入らない数は「###」（2026-11-15）====
// 🚫 以前は #grid-t td{overflow:hidden} で、入らない数（¥1,000,000,000 など）が
//    知らせなしに途中で切れて ¥1,000,000 のように見えていた。Excel と同じく入らない数は
//    「###」を見せ、全体の値は title（ホバー）と数式バーで読めるようにする。
//    文字セルは対象外（今までどおりスピル・折り返し）。列幅変更・再計算のたびに付け外しする。
let numCells=[];   // refreshCells が毎回詰め直す {td,c,full}。snapshot には残さない。
function applyNumClip(onlyCol){
  const list = (onlyCol==null)? numCells : numCells.filter(n=>n.c===onlyCol);
  // ①まず全体値に戻す（戻してから測らないと、### の幅で測って誤判定する）
  for(const n of list){ n.td.textContent=n.full; n.td.title=''; n.td.classList.remove('ovf'); }
  // ②入りきらないセルを拾う（書き戻し後に一度だけ測る。右寄せでも scrollWidth は中身の幅）
  const over=[];
  for(const n of list){ if(n.td.scrollWidth > n.td.clientWidth+1) over.push(n); }
  // ③### を見せ、全体値はホバー（title）で読めるようにする。数式バーは rawOf 由来で元から全体値
  for(const n of over){ n.td.textContent='###'; n.td.title=n.full; n.td.classList.add('ovf'); }
}
// ==== 条件付き書式＋静的なセル色（塗り/文字色/太字/データバー）====
// 規則は sheet().condfmt に保存（.calc.json へ入るので Kiro 生成の表にも仕込める）。
// 規則の形: {kind:'cell', range:{r1,c1,r2,c2}, op:'>='|'<='|'between'|'contains'|'empty',
//            v1, v2, text, bg:'#rrggbb', color:'#rrggbb', bold:1}
//          {kind:'databar', range:{...}, barColor:'#rrggbb'}
const barBounds=new Map();   // databar規則→{lo,hi}（毎refreshで作り直す・snapshotには残さない）
function prepBars(){
  barBounds.clear();
  const rules=sheet().condfmt; if(!rules) return;
  for(const rule of rules){
    if(!rule||rule.kind!=='databar'||!rule.range) continue;
    const rg=rule.range; let mn=Infinity,mx=-Infinity;
    for(let r=rg.r1;r<=rg.r2;r++) for(let c=rg.c1;c<=rg.c2;c++){
      const x=V(addrOf(r,c)); if(typeof x==='number'){ if(x<mn)mn=x; if(x>mx)mx=x; }
    }
    if(mx!==-Infinity) barBounds.set(rule,{lo:Math.min(0,mn),hi:Math.max(0,mx)});
  }
}
function inCfRange(rg,r,c){ return rg&&r>=rg.r1&&r<=rg.r2&&c>=rg.c1&&c<=rg.c2; }
function cfMatch(rule,v,a){
  const op=rule.op;
  if(op==='empty') return v==null||v==='';
  if(op==='contains'){ const t=String(rule.text==null?'':rule.text); if(t==='')return false;
    return String(v==null?'':displayOf(a)).indexOf(t)>=0; }
  const n=(typeof v==='number')?v:parseFloat(v);
  if(!isFinite(n)) return false;
  if(op==='>=') return n>=(+rule.v1);
  if(op==='<=') return n<=(+rule.v1);
  if(op==='between'){ const a1=+rule.v1,a2=+rule.v2; return n>=Math.min(a1,a2)&&n<=Math.max(a1,a2); }
  return false;
}
function dataBarPct(rule,v){
  if(typeof v!=='number') return null;
  const b=barBounds.get(rule); if(!b) return null;
  if(b.hi===b.lo) return v>0?100:0;
  return Math.max(0,Math.min(100,(v-b.lo)/(b.hi-b.lo)*100));
}
function cfStyleAt(a,r,c,v){     // 当該セルに効く最終スタイル（なければnull）
  const cl=sheet().cells[a];
  let bg=(cl&&cl.bg)||'', color=(cl&&cl.color)||'', bold=false, bar=null, barColor='';
  const rules=sheet().condfmt;
  if(rules) for(const rule of rules){
    if(!rule||!inCfRange(rule.range,r,c)) continue;
    if(rule.kind==='databar'){ const w=dataBarPct(rule,v); if(w!=null){ bar=w; barColor=rule.barColor||'#9cc3ea'; } }
    else if(cfMatch(rule,v,a)){ if(rule.bg)bg=rule.bg; if(rule.color)color=rule.color; if(rule.bold)bold=true; }
  }
  if(!bg&&!color&&!bold&&bar==null) return null;
  return {bg,color,bold,bar:(bar==null?null:Math.round(bar)),barColor};
}
function applyCellStyle(td,a,r,c,v,cl,fhd){
  const st=fhd? null : cfStyleAt(a,r,c,v);     // 見出し行（フィルタ）は触らない
  if(!st){ td.style.background=''; td.style.color=''; td.style.fontWeight=''; return; }
  if(st.bar!=null){ td.style.background='linear-gradient(90deg,'+st.barColor+' '+st.bar+'%,transparent '+st.bar+'%)'; }
  else td.style.background=st.bg||'';
  td.style.color=st.color||'';
  td.style.fontWeight=st.bold?'700':'';
}
function normRange(rg){ return {r1:Math.min(rg.r1,rg.r2),c1:Math.min(rg.c1,rg.c2),
  r2:Math.max(rg.r1,rg.r2),c2:Math.max(rg.c1,rg.c2)}; }
function addCondRule(rule){
  if(READONLY)return false;
  if(!rule) return false;
  pushUndo();
  const rg=normRange(rule.range||selRange());
  const r={kind:rule.kind||'cell',range:rg};
  if(r.kind==='databar'){ r.barColor=rule.barColor||'#9cc3ea'; }
  else{ r.op=rule.op||'>='; if(rule.v1!=null)r.v1=+rule.v1; if(rule.v2!=null)r.v2=+rule.v2;
    if(rule.text!=null)r.text=String(rule.text);
    if(rule.bg)r.bg=rule.bg; if(rule.color)r.color=rule.color; if(rule.bold)r.bold=1; }
  (sheet().condfmt||(sheet().condfmt=[])).push(r);
  recalc(); refreshCells(); markDirty();
  return r;
}
function removeCondRule(i){ if(READONLY)return false; const rs=sheet().condfmt; if(!rs||!rs[i])return false;
  pushUndo(); rs.splice(i,1); if(!rs.length)delete sheet().condfmt; recalc(); refreshCells(); markDirty(); return true; }
function clearCondRules(){ if(READONLY)return false; if(!sheet().condfmt)return false;
  pushUndo(); delete sheet().condfmt; recalc(); refreshCells(); markDirty(); return true; }
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
  b.hidden=false;
  b.textContent='▼';
  b.style.left=(td.offsetLeft+td.offsetWidth-28)+'px';
  b.style.width='28px';
  b.style.zIndex='20';
  b.style.top=td.offsetTop+'px';
  b.style.height=td.offsetHeight+'px';
  b.style.display='block';
}
function positionBox(box,s){ // 範囲の外周にオーバーレイ枠を置く
  const a=$('c-'+s.r1+'-'+s.c1), b=$('c-'+s.r2+'-'+s.c2);
  if(!a||!b){ box.style.display='none'; return; }
  if(a.offsetParent===null||b.offsetParent===null){ box.style.display='none'; return; } // 絞り込みで隠れている行
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
  const fe=$('st-flt');
  if(fe){
    const f=sheet().filter;
    fe.textContent=(f&&fltHidden)? '絞り込み '+fltHidden+'行を非表示' : '';
  }
}

// ==== 変更・Undo ====
function snapshot(){ return JSON.stringify({name:doc.name,sheets:doc.sheets,active:doc.active}); }
function pushUndo(){ if(READONLY)return false; undoStack.push(snapshot()); if(undoStack.length>80)undoStack.shift(); redoStack=[]; }
function restore(s){ if(READONLY)return false; doc=JSON.parse(s); astCache.clear(); recalc(); buildGrid(); markDirty(); }
function undo(){ if(READONLY||!undoStack.length)return false; redoStack.push(snapshot()); restore(undoStack.pop()); }
function redo(){ if(READONLY||!redoStack.length)return false; undoStack.push(snapshot()); restore(redoStack.pop()); }
function markDirty(){ if(READONLY)return false; dirty=true; $('bsave').classList.add('dirty');
  clearTimeout(markDirty._t); markDirty._t=setTimeout(autosave,600); }
function autosave(){ if(READONLY)return false; try{ localStorage.setItem(STORAGE_KEY,snapshot()); }catch(e){} }
function commit(){ if(READONLY)return false; recalc(); refreshCells(); markDirty(); }
function ensureSize(r,c){ // 範囲外アクセス時にグリッドを自動拡張
  let grew=false;
  if(r>=sheet().rows){ sheet().rows=r+1; grew=true; }
  if(c>=sheet().cols){ sheet().cols=c+1; grew=true; }
  return grew;
}
function setCellAndRecalc(a,v){ if(!cellEditable(a))return false; pushUndo();
  const p=parseAddr(a); const grew=p? ensureSize(p.r,p.c) : false;
  setRaw(a,v);
  if(grew){ recalc(); buildGrid(); markDirty(); } else commit(); }

// ==== セル編集 ====
const ed=()=>$('cell-ed');
let editing=false;
function startEdit(initial){
  if(!cellEditable(addrOf(cur.r,cur.c)))return false;
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
  let nr=Math.max(0,Math.min(sheet().rows-1,cur.r+dr));
  const nc=Math.max(0,Math.min(sheet().cols-1,cur.c+dc));
  if(dr!==0&&sheet().filter) nr=nextVisibleRow(nr,dr>0?1:-1,cur.r); // 隠れている行は飛ばす
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
  if(READONLY||REVIEW)return false;
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
function insertRow(pos){ if(READONLY)return false; pushUndo(); remapCells('r',pos,1); sheet().rows++; astCache.clear(); recalc(); buildGrid(); markDirty(); }
function deleteRow(pos){ if(READONLY||sheet().rows<=1)return false; pushUndo(); remapCells('r',pos,-1); sheet().rows--; astCache.clear();
  if(cur.r>=sheet().rows)cur.r=sheet().rows-1; recalc(); buildGrid(); markDirty(); }
function insertCol(pos){ if(READONLY)return false; pushUndo(); remapCells('c',pos,1); sheet().cols++; astCache.clear(); recalc(); buildGrid(); markDirty(); }
function deleteCol(pos){ if(READONLY||sheet().cols<=1)return false; pushUndo(); remapCells('c',pos,-1); sheet().cols--; astCache.clear();
  if(cur.c>=sheet().cols)cur.c=sheet().cols-1; recalc(); buildGrid(); markDirty(); }

// ==== 書式 ====
function cleanCell(a){ const cl=sheet().cells[a];
  if(cl&&cl.v==null&&!cl.fmt&&!cl.bold&&!cl.align&&!cl.valign&&!cl.opts&&!cl.wrap) delete sheet().cells[a]; }
function applyFmt(fmt){
  if(READONLY||REVIEW)return false;
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
  if(READONLY||REVIEW)return false;
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
  if(READONLY||REVIEW)return false;
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
  if(READONLY||REVIEW)return false;
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
  if(READONLY||REVIEW)return false;
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
  if(READONLY)return false;
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
  if(READONLY)return false;
  if(typeof window.showOpenFilePicker==='function'){
    try{
      const handles=await window.showOpenFilePicker({
        id:'calckit-document',multiple:false,
        types:[{description:'CalcKit / Excel / CSV',accept:{'application/json':['.calc.json','.json'],
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':['.xlsx','.xlsm'],
          'text/plain':['.csv','.tsv','.txt']}}]
      });
      const handle=handles[0],file=await handle.getFile();
      if(/\.(xlsx|xlsm|xlsb)$/i.test(file.name)){ importXlsxArrayBuffer(file.name,await file.arrayBuffer()); return; }
      loadOpenedText(file.name,await file.text(),handle); return;
    }catch(e){ if(e&&e.name==='AbortError')return; alert('ファイルを開けません: '+(e.message||e)); return; }
  }
  const inp=document.createElement('input'); inp.type='file'; inp.accept='.json,.csv,.tsv,.txt,.xlsx,.xlsm';
  inp.onchange=()=>{ const file=inp.files[0]; if(!file)return;
    if(/\.(xlsx|xlsm|xlsb)$/i.test(file.name)){
      const rd=new FileReader(); rd.onload=()=>importXlsxArrayBuffer(file.name,rd.result); rd.readAsArrayBuffer(file); return; }
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
// ==== Excel 書き出し：全シートを色・罫線つきで（SpreadsheetML 2003・外部ライブラリなし）====
//   各タブを正式な <Worksheet> として定義するため、タブを押すと中身が出る（HTMLテーブル方式は
//   Excelが表を1枚目に積んでタブが空になるため不採用）。塗り(section/header)・階層罫線(major/middle)・
//   太字・揃え・折り返し・列幅を viewer の見た目のまま出す。
const XLS_FILL={section:'#DBE7F3',header:'#EEF3F8'};   // .fill-section / .fill-header と揃える
const XLS_H={l:'Left',c:'Center',r:'Right'};
const XLS_V={t:'Top',m:'Center',b:'Bottom'};
const XLS_NUMFMT={num:'#,##0',dec2:'#,##0.00'};        // 数として出す書式のみ（¥/%/日付は表示文字で出す）
function usedRangeOf(s){
  let r2=0,c2=0,found=false;
  for(const a in s.cells){ if(s.cells[a].v==null)continue;
    const p=parseAddr(a); if(!p)continue; r2=Math.max(r2,p.r); c2=Math.max(c2,p.c); found=true; }
  return {r1:0,c1:0,r2,c2,found};
}
function displayOfIn(si,a){ // displayOf のシート指定版（アクティブ以外も出せる）
  const s=doc.sheets[si], v=vals[si+'!'+a];
  if(v==null||v==='') return '';
  if(isErr(v)) return v.e;
  if(typeof v==='number'){ const c=s.cells[a];
    let fmt=c&&c.fmt;
    if(!fmt&&c&&c.v&&c.v[0]!=='='){
      if(DATE_RE.test(c.v)) fmt='date';
      else if(c.v.indexOf('¥')>=0) fmt='yen';
      else if(/%\s*$/.test(c.v)) fmt='pct';
    }
    return fmtNum(v,fmt); }
  return String(v);
}
function xlsSheetName(name){
  return (String(name||'シート').replace(/[\[\]:*?\/\\]/g,'_').slice(0,31))||'シート';
}
function xmlEsc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;').replace(/\r/g,'').replace(/\n/g,'&#10;'); }
function exportXls(){ // 全シートを色・罫線つきExcelへ（SpreadsheetML 2003）
  recalc();
  const styleXml=[], styleMap=new Map(); let styleN=0;
  function styleId(c,numFmt){
    const key=[c.fill||'',c.bold?1:0,c.align||'',c.valign||'',c.wrap?1:0,c.borderTop||'',numFmt||''].join('|');
    let id=styleMap.get(key); if(id) return id;
    id='s'+(styleN++); styleMap.set(key,id);
    const ver=XLS_V[c.valign]||'Center', hor=XLS_H[c.align];
    let s='<Style ss:ID="'+id+'"><Alignment ss:Vertical="'+ver+'"'
      +(hor?' ss:Horizontal="'+hor+'"':'')+(c.wrap?' ss:WrapText="1"':'')+'/><Borders>'
      +'<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="0.5" ss:Color="#E2E8F0"/>'
      +'<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="0.5" ss:Color="#E2E8F0"/>'
      +'<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="0.5" ss:Color="#E2E8F0"/>';
    if(c.borderTop==='major') s+='<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="2" ss:Color="#21537F"/>';
    else if(c.borderTop==='middle') s+='<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1.5" ss:Color="#718096"/>';
    else s+='<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="0.5" ss:Color="#E2E8F0"/>';
    s+='</Borders><Font ss:Color="#1E293B"'+((c.bold||c.fill)?' ss:Bold="1"':'')+'/>';
    const fill=c.fill&&XLS_FILL[c.fill];
    if(fill) s+='<Interior ss:Color="'+fill+'" ss:Pattern="Solid"/>';
    if(numFmt) s+='<NumberFormat ss:Format="'+numFmt+'"/>';
    s+='</Style>'; styleXml.push(s); return id;
  }
  const used=new Set(); let sheetsXml='';
  doc.sheets.forEach((sh,si)=>{
    let nm=xlsSheetName(sh.name), base=nm, i=2;
    while(used.has(nm)){ nm=base.slice(0,28)+'_'+i; i++; } used.add(nm);
    const u=usedRangeOf(sh);
    let cols='';
    for(let c=u.c1;c<=u.c2;c++){ const w=(sh.colW&&sh.colW[c])?Math.round(sh.colW[c]*0.75):68;
      cols+='<Column ss:Width="'+w+'"/>'; }
    let rowsXml='';
    for(let r=u.r1;r<=u.r2;r++){
      let cells='';
      for(let c=u.c1;c<=u.c2;c++){
        const a=addrOf(r,c), cell=sh.cells[a]||{}, v=vals[si+'!'+a];
        // 数として出せるのは fmt無し/num/dec2 の数値だけ。¥/%/日付・式は表示文字で出す（見た目一致）
        let numFmt=null, type='String', data='';
        const plainNum=(typeof v==='number')&&!(cell.v&&cell.v[0]==='=')
          &&(!cell.fmt||cell.fmt==='num'||cell.fmt==='dec2')
          &&!(cell.v&&(DATE_RE.test(cell.v)||cell.v.indexOf('¥')>=0||/%\s*$/.test(cell.v)));
        if(plainNum){ type='Number'; data=String(v); numFmt=XLS_NUMFMT[cell.fmt]||null; }
        else if(v!=null&&v!==''){ data=xmlEsc(displayOfIn(si,a)); }
        const id=styleId(cell,numFmt);
        cells+='<Cell ss:StyleID="'+id+'"><Data ss:Type="'+type+'">'+data+'</Data></Cell>';
      }
      rowsXml+='<Row>'+cells+'</Row>';
    }
    sheetsXml+='<Worksheet ss:Name="'+xmlEsc(nm)+'"><Table>'+cols+rowsXml+'</Table></Worksheet>';
  });
  const xml='<?xml version="1.0" encoding="UTF-8"?>\n<?mso-application progid="Excel.Sheet"?>\n'
    +'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"'
    +' xmlns:o="urn:schemas-microsoft-com:office:office"'
    +' xmlns:x="urn:schemas-microsoft-com:office:excel"'
    +' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"'
    +' xmlns:html="http://www.w3.org/TR/REC-html40"><Styles>'
    +'<Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Center"/>'
    +'<Font ss:Color="#1E293B"/></Style>'+styleXml.join('')+'</Styles>'
    +sheetsXml+'</Workbook>';
  download((doc.name||'CalcKit')+'.xls', xml, 'application/vnd.ms-excel');
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

// ==== .xlsx 読み込み（SheetJS・外部へ送らない・file://で動く）====
//   全シートをタブに取り込み、値・式（CalcKitが持つ関数のみ生きた式／無理な式は値）・
//   日付（Excelシリアル→YYYY-MM-DD）・列幅を入れる。正本は引き続き .calc.json。
const CK_FUNCS=new Set(['SUM','AVERAGE','MIN','MAX','COUNT','COUNTA','IF','SUMIF','COUNTIF',
  'ROUND','ROUNDUP','ROUNDDOWN','ABS','INT','SQRT','VLOOKUP','HLOOKUP','DATE','TODAY']);
function xlsxFormulaSupported(f){
  // 関数名（識別子の直後が「(」）を洗い出し、全部CalcKitが持つ関数か
  const names=f.toUpperCase().match(/[A-Z][A-Z0-9_.]*(?=\s*\()/g)||[];
  for(const n of names){ if(!CK_FUNCS.has(n)) return false; }
  if(/[\[\]{}]/.test(f)) return false;   // 構造化参照・配列数式は非対応→値に落とす
  return true;
}
function xlsxCellRaw(cell){ // 式でないセルの値→CalcKitの生入力文字列
  const t=cell.t;
  if(t==='n'){
    if(cell.z && window.XLSX && XLSX.SSF && XLSX.SSF.is_date(cell.z) && isFinite(cell.v))
      return serialToYMD(cell.v);        // 日付書式の数値→YYYY-MM-DD
    return String(cell.v);
  }
  if(t==='b') return cell.v? 'TRUE':'FALSE';
  if(t==='e') return cell.w||'#VALUE!';
  if(t==='d'){ const d=cell.v;           // cellDates:false では来ない想定の保険
    return (d instanceof Date)? d.getUTCFullYear()+'-'+String(d.getUTCMonth()+1).padStart(2,'0')
      +'-'+String(d.getUTCDate()).padStart(2,'0') : String(cell.w||cell.v||''); }
  return cell.w!=null? String(cell.w) : (cell.v!=null? String(cell.v):'');
}
function importXlsxArrayBuffer(name,buf,deferEnrich){
  if(READONLY)return false;
  if(typeof window.XLSX==='undefined'){ alert('xlsxライブラリ（xlsx.full.min.js）が読み込めていません'); return false; }
  let wb;
  try{ wb=XLSX.read(new Uint8Array(buf),{type:'array',cellFormula:true,cellNF:true,cellStyles:true,cellDates:false}); }
  catch(e){ alert('xlsxを読み込めません: '+(e&&e.message||e)); return false; }
  pushUndo();
  const base=String(name||'book').replace(/\.(xlsx|xlsm|xlsb)$/i,'');
  const nd={name:base||'読み込みシート',active:0,sheets:[]};
  let nf=0,nk=0,nfmt=0,nfill=0,nmerge=0;
  (wb.SheetNames||[]).forEach(sn=>{
    const ws=wb.Sheets[sn]; if(!ws)return;
    const sh=newSheet(sn); let maxR=0,maxC=0;
    const ref=ws['!ref'];
    if(ref){
      const rng=XLSX.utils.decode_range(ref);
      maxR=rng.e.r; maxC=rng.e.c;
      for(let R=rng.s.r;R<=rng.e.r;R++) for(let C=rng.s.c;C<=rng.e.c;C++){
        const cell=ws[XLSX.utils.encode_cell({r:R,c:C})]; if(!cell)continue;
        let raw;
        if(cell.f){
          const f=String(cell.f);
          if(xlsxFormulaSupported(f)){ raw='='+canonFormula(f); nf++; }
          else { raw=xlsxCellRaw(cell); nk++; }   // 無理な式は計算結果（値）に落とす
        }else raw=xlsxCellRaw(cell);
        if(raw==null||raw==='')continue;
        const co={v:raw};
        const fmt=xlsxFmtOf(cell); if(fmt){ co.fmt=fmt; nfmt++; }   // %・¥・桁区切り・小数・日付
        const bg=fillHexOf(cell); if(bg){ co.bg=bg; nfill++; }      // 塗り色（SheetJSが読める分）
        sh.cells[addrOf(R,C)]=co;
      }
    }
    sh.rows=Math.max(50,maxR+10); sh.cols=Math.max(26,maxC+4);
    const cols=ws['!cols'];
    if(Array.isArray(cols)) cols.forEach((w,ci)=>{ if(!w)return;
      let px=w.wpx!=null?w.wpx:(w.width!=null?Math.round(w.width*7):(w.wch!=null?Math.round(w.wch*7+5):null));
      if(px&&px>0) sh.colW[ci]=Math.round(px); });
    const mg=ws['!merges'];                      // CalcKitに結合はないので左上に値を置く（SheetJS既定）＋件数を注記
    if(Array.isArray(mg)) nmerge+=mg.length;
    nd.sheets.push(sh);
  });
  if(!nd.sheets.length) nd.sheets.push(newSheet('シート1'));
  doc=nd; astCache.clear(); recalc(); buildGrid(); setName(doc.name);
  clearSaveTarget();           // 正本は .calc.json。xlsxには書き戻さない（次の保存で保存先を選ぶ）
  markDirty();
  lastImport={sheets:nd.sheets.length,formulas:nf,valued:nk,fmts:nfmt,fills:nfill,merges:nmerge};
  const msg='xlsxから取り込んだ（シート'+nd.sheets.length+'・式'+nf+'・書式'+nfmt
    +(nmerge?'・結合'+nmerge+'は左上に値':'')+'）';
  setSaveStatus(msg); toast(msg);
  if(!deferEnrich) enrichXlsxStyles(buf);   // 太字・文字色・横位置を zip から後追いで補う（非同期）
  return true;
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
  if(READONLY||REVIEW)return false;
  pushUndo();
  doc.sheets.push(newSheet(uniqueSheetName('シート'+(doc.sheets.length+1))));
  doc.active=doc.sheets.length-1; cur={r:0,c:0}; selA=null;
  recalc(); buildGrid(); markDirty();
}
function renameSheet(i,name){
  if(READONLY)return false;
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
  if(READONLY)return false;
  if(doc.sheets.length<=1) return false;
  pushUndo();
  doc.sheets.splice(i,1);
  if(doc.active>=doc.sheets.length) doc.active=doc.sheets.length-1;
  cur={r:0,c:0}; selA=null;
  astCache.clear(); recalc(); buildGrid(); markDirty();  // 参照は評価時に#REF!
  return true;
}
function dupSheet(i){
  if(READONLY||REVIEW)return false;
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
    b.title=READONLY?'クリックで切替':'クリックで切替／ダブルクリックで名前変更／右クリックで複製・削除';
    b.onclick=()=>switchSheet(i);
    if(!(READONLY||REVIEW)){
      b.ondblclick=()=>{ const n=prompt('シート名',s.name); if(n!=null&&!renameSheet(i,n)&&n.trim()!==s.name)
        alert('その名前は使えません（重複か、!と\'は不可）'); };
      b.oncontextmenu=e=>{ e.preventDefault();
        showCtx(e.clientX,e.clientY,[
          {label:'名前を変更',fn:()=>b.ondblclick()},
          {label:'複製',fn:()=>dupSheet(i)},'-',
          {label:`「${s.name}」を削除`,fn:()=>{ if(doc.sheets.length<=1){alert('最後のシートは削除できません');return;}
            if(confirm(`シート「${s.name}」を削除しますか？（参照している式は#REF!になります）`)) deleteSheet(i); }}]); };
    }
    el.appendChild(b);
  });
  if(!(READONLY||REVIEW)){
    const add=document.createElement('button');
    add.className='tab tab-add'; add.textContent='＋'; add.title='シートを追加';
    add.onclick=addSheet;
    el.appendChild(add);
  }
}

// ==== テンプレート ====
function loadTemplate(id){
  if(READONLY||REVIEW)return false;
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
      // 決定: 罫線はSlideKitトークンの #d4dde7 を使う（#e2e8f0 等はslide-guardの許可色外でPPTX化が止まる）
      // 根拠=.kiro/steering/slide-contract-detail.md のカラートークン表
      else st=`padding:5px 10px;border-bottom:1px solid #d4dde7;color:#121212;text-align:${num?'right':'left'};`+
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
  return {config:p.config,categories:p.cats,items:p.items,baselines:p.baselines||[]};
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
    // 進捗%（0〜100 の数。「45%」の表示でも値は 0.45 なので 100 倍）・控え（GanttKit→表→ガントの往復で落とさない・2026-11-14）
    const gv=v=>{ const ci=map[v]; return (ci==null||ci<0)? null : V(addrOf(r,u.c1+ci)); };
    let prog=gv('progress');
    if(typeof prog==='string'){ const m=String(prog).trim().match(/^(-?\d+(?:\.\d+)?)\s*%?$/); prog=m? +m[1] : null; }
    else if(typeof prog==='number'){ const cl=sheet().cells[addrOf(r,u.c1+map.progress)]; if((cl&&cl.fmt==='pct')||(prog>0&&prog<=1)) prog=prog*100; }
    if(typeof prog!=='number'||!isFinite(prog)) prog=null; else prog=Math.max(0,Math.min(100,Math.round(prog)));
    const bs=normMonth(g('bstart')), be=normMonth(g('bend'));
        items.push({name,cat:grp,start:st,end:en,ver:g('label')||'',desc:g('desc')||'',assignee:g('assignee')||'',
          progress:prog, base:(bs&&be)?{start:bs,end:be}:null});
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
    items:items.map((it,i)=>{
      const v={ver:it.ver,start:it.start,end:it.end,desc:it.desc};
      if(it.progress!=null) v.progress=it.progress;
      return {id:'ck'+(i+1),cat:catId(it.cat),name:it.name,assignee:it.assignee||'',versions:[v]};
    }),
    // 控え: 1行でも控え開始・控え終了があれば1本の控えにまとめる（GanttKit の TL_BASELINES の形）
    baselines:(()=>{
      const bi={}; let any=false;
      items.forEach((it,i)=>{ if(it.base){ bi['ck'+(i+1)]=[{start:it.base.start,end:it.base.end}]; any=true; } });
      if(!any) return [];
      const d=new Date(), ds=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
      return [{date:ds,label:'控え（表から）',items:bi}];
    })()};
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
  if(p.baselines&&p.baselines.length) js.push('window.TL_BASELINES='+JSON.stringify(p.baselines)+';');
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
    const gi={name:guess(['項目','名前','タスク','作業']),start:guess(['開始','From','from']),desc:guess(['説明','備考','メモ']),
      end:guess(['終了','完了','To','to']),group:guess(['グループ','分類','カテゴリ','フェーズ']),
      assignee:guess(['担当','担当者','アサイン','owner','Owner']),
      progress:guess(['進捗','進捗%','進捗率','progress']),bstart:guess(['控え開始','計画開始','当初開始']),bend:guess(['控え終了','計画終了','当初終了'])};
  openModal(`<h3>GanttKitデータ書き出し</h3>
    <div class="note">先頭行をヘッダとして列を割り当てる。日付は YYYY-MM か YYYY-MM-DD（/区切りも可）</div>
    <label>項目名の列</label><select id="gk-name">${opts(gi.name<0?0:gi.name)}</select>
    <label>開始の列</label><select id="gk-start">${opts(gi.start<0?1:gi.start)}</select>
    <label>終了の列</label><select id="gk-end">${opts(gi.end<0?2:gi.end)}</select>
    <label>グループの列（任意）</label><select id="gk-group">${opts(gi.group,true)}</select>
    <label>担当の列（任意）</label><select id="gk-assignee">${opts(gi.assignee,true)}</select>
    <label>ラベルの列（任意・PoC/本番など）</label><select id="gk-label">${opts(-1,true)}</select>
    <label>説明の列（任意）</label><select id="gk-desc">${opts(gi.desc==null?-1:gi.desc,true)}</select>
    <label>進捗%の列（任意・0〜100）</label><select id="gk-progress">${opts(gi.progress,true)}</select>
    <label>控え開始・控え終了の列（任意・両方そろった行だけ控えになる）</label>
    <div style="display:flex;gap:6px"><select id="gk-bstart" style="flex:1">${opts(gi.bstart,true)}</select><select id="gk-bend" style="flex:1">${opts(gi.bend,true)}</select></div>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">キャンセル</button>
    <button id="m-go">データjsを保存</button>
    <button class="m-save" id="m-open">GanttKitで開く</button></div>`);
    const readMap=()=>({name:+$('gk-name').value,start:+$('gk-start').value,end:+$('gk-end').value,
      group:+$('gk-group').value,label:+$('gk-label').value,desc:+$('gk-desc').value,
      assignee:+$('gk-assignee').value,progress:+$('gk-progress').value,bstart:+$('gk-bstart').value,bend:+$('gk-bend').value});
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
  if(READONLY)return false;
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
function sortRange(byCol,asc,fixedRange,skipHeader){
  if(READONLY)return false;
  let s=fixedRange||selRange();
  if(!fixedRange&&s.r1===s.r2&&s.c1===s.c2) s=usedRange();
  if(byCol<s.c1||byCol>s.c2) return false;
  let start=s.r1;
  if(skipHeader) start=s.r1+1;
  else {
    const headV=V(addrOf(s.r1,byCol));
    let numBelow=0;
    for(let r=s.r1+1;r<=s.r2;r++) if(typeof V(addrOf(r,byCol))==='number') numBelow++;
    if(typeof headV!=='number'&&numBelow>0) start=s.r1+1;
  }
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
  if(sheet().filter) applyFilterView();
  return true;
}

// ==== フィルタ（見出し行ごとの絞り込み。行を隠すだけで値は触らない） ====
// sheet().filter = {r:見出し行, r2:最終行, c1,c2:列範囲, sel:{"列":[表示する値...]}}
let fltCol=null, fltHidden=0;
function filterOf(){ return sheet().filter||null; }
function isFilterHeader(r,c){ const f=filterOf(); return !!f&&r===f.r&&c>=f.c1&&c<=f.c2; }
function colSel(c){ const f=filterOf(); return (f&&f.sel&&f.sel[String(c)])||null; }
function filterActive(c){ return !!colSel(c); }
function keyOf(r,c){ return displayOf(addrOf(r,c)); }
function rowVisible(r){
  const f=filterOf(); if(!f||!f.sel) return true;
  if(r<=f.r||r>f.r2) return true;
  for(const k in f.sel){
    const allow=f.sel[k];
    if(allow&&allow.indexOf(keyOf(r,+k))<0) return false;
  }
  return true;
}
function nextVisibleRow(r,step,fallback){
  let n=r;
  while(n>=0&&n<sheet().rows&&!rowVisible(n)) n+=step;
  return (n<0||n>=sheet().rows)? fallback : n;
}
function applyFilterView(){
  const tb=tbody(); if(!tb) return;
  let hidden=0;
  for(let r=0;r<sheet().rows;r++){
    const tr=tb.rows[r]; if(!tr) continue;
    const vis=rowVisible(r);
    tr.style.display=vis? '' : 'none';
    if(!vis) hidden++;
  }
  fltHidden=hidden;
  markFilterCols(); updateStatus(); paintSel();
}
function markFilterCols(){
  const f=filterOf();
  if(!f&&!document.querySelector('#grid-t th.ch.fcol')) return;
  document.querySelectorAll('#grid-t th.ch').forEach(th=>{
    const c=+th.dataset.c;
    th.classList.toggle('fcol', !!f&&c>=f.c1&&c<=f.c2&&filterActive(c));
  });
}
function paintFilterHead(td,c,shown){
  td.textContent='';
  const cap=document.createElement('span'); cap.className='fh-cap'; cap.textContent=shown;
  const on=filterActive(c);
  const b=document.createElement('button');
  b.type='button'; b.className='fh-btn'+(on?' on':''); b.dataset.fc=String(c);
  b.textContent=on? '▼' : '▽';
  b.title=on? '絞り込み中（クリックで変更）' : '絞り込み・並べ替え';
  td.appendChild(cap); td.appendChild(b);
}
// ==== フィルタの付け外し ====
function filterTargetRange(){
  const s=selRange();
  if(s.r1===s.r2&&s.c1===s.c2) return currentRegion(cur.r,cur.c);
  return s;
}
function setFilterRange(range){
  const s=range||filterTargetRange();
  if(s.r2<=s.r1){ alert('見出し行とデータ行を含む範囲を選んでください'); return false; }
  sheet().filter={r:s.r1,r2:s.r2,c1:s.c1,c2:s.c2,sel:{}};
  afterFilterChange(true);
  return true;
}
function clearFilter(){
  hideFilterPanel();
  if(!filterOf()) return false;
  delete sheet().filter;
  afterFilterChange(true);
  return true;
}
function toggleFilter(){ return filterOf()? clearFilter() : setFilterRange(); }
function refreshFilterHeads(){ // 見出しの▽だけ描き直す（全セル再描画は重い）
  const f=filterOf(); if(!f) return;
  for(let c=f.c1;c<=f.c2;c++){
    const td=$('c-'+f.r+'-'+c);
    if(td) paintFilterHead(td,c,displayOf(addrOf(f.r,c)));
  }
}
function afterFilterChange(structural){
  if(structural) refreshCells(); else refreshFilterHeads();
  applyFilterView();   // 行の表示・非表示
  if(REVIEW) autosave(); else markDirty();
}
// ==== フィルタのパネル ====
function cmpFilterVals(a,b){
  if(a===''&&b!=='') return 1;
  if(b===''&&a!=='') return -1;
  const na=Number(String(a).replace(/[,¥%\s]/g,'')), nb=Number(String(b).replace(/[,¥%\s]/g,''));
  if(a!==''&&b!==''&&!isNaN(na)&&!isNaN(nb)) return na-nb;
  return String(a).localeCompare(String(b),'ja');
}
function colValues(c){
  const f=filterOf(); if(!f) return [];
  const m=new Map();
  for(let r=f.r+1;r<=f.r2;r++){ const k=keyOf(r,c); m.set(k,(m.get(k)||0)+1); }
  return [...m.entries()].map(([v,n])=>({v,n})).sort((x,y)=>cmpFilterVals(x.v,y.v));
}
function hideFilterPanel(){ const p=$('fltp'); if(p){ p.hidden=true; } fltCol=null; }
function openFilterPanel(c,anchor){
  const f=filterOf(); if(!f) return;
  fltCol=c;
  const p=$('fltp');
  $('fp-ttl').textContent=(keyOf(f.r,c)||colName(c)+'列')+'（'+colName(c)+'列）';
  $('fp-q').value='';
  $('fp-asc').disabled=READONLY; $('fp-desc').disabled=READONLY;
  renderFilterList();
  p.hidden=false;
  const rc=anchor.getBoundingClientRect(), ph=p.offsetHeight;
  p.style.left=Math.max(6,Math.min(rc.right-268,innerWidth-274))+'px';
  p.style.top=(rc.bottom+4+ph>innerHeight? Math.max(6,rc.top-4-ph) : rc.bottom+4)+'px';
  $('fp-q').focus();
}
function mkFilterRow(label,count,checked,onToggle){
  const row=document.createElement('label'); row.className='fp-row';
  const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=checked;
  const v=document.createElement('span'); v.className='fp-v'; v.textContent=label;
  row.appendChild(cb); row.appendChild(v);
  if(count!=null){ const n=document.createElement('span'); n.className='fp-n'; n.textContent=count; row.appendChild(n); }
  cb.addEventListener('change',()=>onToggle(cb.checked));
  return row;
}
function renderFilterList(){
  const list=$('fp-list'); if(fltCol==null) return;
  const q=$('fp-q').value.trim().toLowerCase();
  const all=colValues(fltCol);
  const shown=q? all.filter(o=>String(o.v).toLowerCase().indexOf(q)>=0) : all;
  const isOn=v=>{ const s=colSel(fltCol); return !s||s.indexOf(v)>=0; };
  list.textContent='';
  let allCb=null;
  const syncAll=()=>{ if(allCb) allCb.checked=shown.length>0&&shown.every(o=>isOn(o.v)); };
  const allRow=mkFilterRow(q?'（表示中をすべて）':'（すべて）',null,false,on=>{
    const keys=shown.map(o=>o.v);
    let next=colSel(fltCol)? colSel(fltCol).slice() : all.map(o=>o.v);
    if(on){ for(const k of keys) if(next.indexOf(k)<0) next.push(k); }
    else next=next.filter(k=>keys.indexOf(k)<0);
    setColSel(next,all);
    renderFilterList();   // 全行のチェックが変わるので作り直す
  });
  allCb=allRow.querySelector('input');
  list.appendChild(allRow);
  for(const o of shown.slice(0,400)){
    // 値の行は作り直さない（チェックのたびにDOMが入れ替わると連続で選べない）
    list.appendChild(mkFilterRow(o.v===''?'（空白）':o.v,o.n,isOn(o.v),on=>{
      let next=colSel(fltCol)? colSel(fltCol).slice() : all.map(x=>x.v);
      const i=next.indexOf(o.v);
      if(on){ if(i<0) next.push(o.v); } else if(i>=0) next.splice(i,1);
      setColSel(next,all); syncAll();
    }));
  }
  if(shown.length>400){
    const note=document.createElement('div'); note.className='fp-note';
    note.textContent='他 '+(shown.length-400)+' 件（検索でしぼってください）';
    list.appendChild(note);
  }
  if(!shown.length){
    const note=document.createElement('div'); note.className='fp-note'; note.textContent='該当なし';
    list.appendChild(note);
  }
  syncAll();
}
function setColSel(next,all){
  const f=filterOf(); if(!f) return;
  if(next.length>=all.length) delete f.sel[String(fltCol)];
  else f.sel[String(fltCol)]=next;
  afterFilterChange();
}
function clearColFilter(){
  const f=filterOf(); if(!f||fltCol==null) return;
  delete f.sel[String(fltCol)];
  afterFilterChange(); renderFilterList();
}
function sortByFilterCol(asc){
  const f=filterOf(); if(!f||fltCol==null||READONLY) return false;
  const c=fltCol;
  selA={r:f.r,c:f.c1}; cur={r:f.r2,c:f.c2};
  const ok=sortRange(c,asc,{r1:f.r,c1:f.c1,r2:f.r2,c2:f.c2},true);
  refreshCells(); applyFilterView(); hideFilterPanel();
  return ok;
}
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
function wireFilter(){ // 閲覧・編集の両モードで使う（絞り込みは見る操作）
  document.addEventListener('mousedown',e=>{
    if(e.target.closest('.fh-btn')){ e.stopPropagation(); return; } // セル選択を走らせない
    if(!e.target.closest('#fltp')) hideFilterPanel();
  },true);
  document.addEventListener('click',e=>{
    const b=e.target.closest('.fh-btn'); if(!b) return;
    e.preventDefault(); e.stopPropagation();
    const c=+b.dataset.fc;
    if(!$('fltp').hidden&&fltCol===c) hideFilterPanel(); else openFilterPanel(c,b);
  },true);
  $('fp-q').addEventListener('input',renderFilterList);
  $('fp-q').addEventListener('keydown',e=>{ if(e.key==='Escape'){ hideFilterPanel(); } e.stopPropagation(); });
  $('fp-asc').onclick=()=>sortByFilterCol(true);
  $('fp-desc').onclick=()=>sortByFilterCol(false);
  $('fp-clear').onclick=clearColFilter;
  $('fp-off').onclick=clearFilter;
  $('grid-wrap').addEventListener('scroll',()=>{ if(!$('fltp').hidden) hideFilterPanel(); });
  window.addEventListener('resize',()=>hideFilterPanel());
}
// 2026-09-25 セルを押したら表にフォーカスを移す。mousedownで既定動作を止めているので、
//   iframeに埋め込むと（viewer.html）枠の中にフォーカスが移らず、⌘C・矢印キーが外のページに行っていた
function focusGrid(){ const w=$('grid-wrap'); if(w&&document.activeElement!==w) w.focus({preventScroll:true}); }
function wireReadonlyEvents(){
  const wrap=$('grid-wrap');
  wrap.addEventListener('mousedown',e=>{
    const td=e.target.closest('td');
    if(td){ const p=tdPos(td); if(!p)return;
      if(e.shiftKey){ if(!selA)selA={...cur}; cur=p; } else { selA=null; cur=p; }
      paintSel(); e.preventDefault(); focusGrid(); return; }
    const rh=e.target.closest('th.rh');
    if(rh){ const r=+rh.dataset.r; selA={r,c:0}; cur={r,c:sheet().cols-1}; paintSel(); return; }
    const ch=e.target.closest('th.ch');
    if(ch){ const c=+ch.dataset.c; selA={r:0,c}; cur={r:sheet().rows-1,c}; paintSel(); }
  });
  document.addEventListener('keydown',e=>{
    if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;
    const mv={ArrowUp:[-1,0],ArrowDown:[1,0],ArrowLeft:[0,-1],ArrowRight:[0,1]}[e.key];
    if(mv){ e.preventDefault(); moveCur(mv[0],mv[1],e.shiftKey); return; }
    if(e.key==='Tab'){ e.preventDefault(); moveCur(0,e.shiftKey?-1:1); return; }
    if(e.key==='Escape'){ selA=null; paintSel(); }
  });
  document.addEventListener('copy',e=>{ if(document.activeElement.tagName==='INPUT')return; copySel(e); });
  window.addEventListener('resize',paintSel);
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
      dragSel=true; paintSel(); e.preventDefault(); focusGrid(); return; }
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
      applyNumClip(gripDrag.c);   // C2: 幅が変わったその列の数だけ ### を付け外し（2026-11-15）
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
        {label:filterOf()?'フィルタを外す':'フィルタを付ける（見出し行に▽）',fn:toggleFilter},'-',
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
    if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){ e.preventDefault(); endEdit(true,'down'); }
    else if(e.key==='Tab'){ e.preventDefault(); endEdit(true,'right'); }
    else if(e.key==='Escape'){ e.preventDefault(); endEdit(false); }
    e.stopPropagation();
  });
  ed().addEventListener('blur',()=>{ if(editing) endEdit(true); });
  ed().addEventListener('input',()=>{ $('fx').value=ed().value; });
  // 数式バー
  $('fx').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229)){ e.preventDefault(); setCellAndRecalc(addrOf(cur.r,cur.c),$('fx').value); moveCur(1,0); $('fx').blur(); }
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
  $('fflt').onclick=toggleFilter;
  $('fcond').onclick=showCondModal;
  $('fpivot').onclick=showPivotModal;
  $('frowa').onclick=()=>{ pushUndo(); sheet().rows+=10; buildGrid(); markDirty(); };
  $('fcola').onclick=()=>{ pushUndo(); sheet().cols+=4; buildGrid(); markDirty(); };
  // ヘッダー
  $('btmpl').onchange=e=>{ const v=e.target.value; e.target.value='';
    if(v&&confirm('現在のシートを置き換えます。よろしいですか？（⌘Zで戻せます）')){
      clearSaveTarget(); loadTemplate(v);
    } };
  $('bopen').onclick=openDocument;
  $('bcsv').onclick=()=>download(doc.name+'.csv','\ufeff'+buildCSV(),'text/csv');
  // ファイルのドロップで開く（.xlsx / .json / .csv / .tsv / .txt）
  const gwrap=$('grid-wrap');
  if(gwrap){
    ['dragover','dragenter'].forEach(evn=>gwrap.addEventListener(evn,e=>{
      if(READONLY||!e.dataTransfer||!Array.from(e.dataTransfer.types||[]).includes('Files'))return;
      e.preventDefault(); e.dataTransfer.dropEffect='copy'; }));
    gwrap.addEventListener('drop',e=>{
      if(READONLY)return;
      const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0]; if(!f)return;
      e.preventDefault();
      if(/\.(xlsx|xlsm|xlsb)$/i.test(f.name)){
        const rd=new FileReader(); rd.onload=()=>importXlsxArrayBuffer(f.name,rd.result); rd.readAsArrayBuffer(f);
      }else if(/\.(json|csv|tsv|txt)$/i.test(f.name)){
        const rd=new FileReader(); rd.onload=()=>loadOpenedText(f.name,String(rd.result),null); rd.readAsText(f);
      }
    });
  }
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
    inp.onkeydown=e=>{ if(e.key==='Enter'&&!(e.isComposing||e.keyCode===229))done(true); if(e.key==='Escape')done(false); e.stopPropagation(); };
    inp.onblur=()=>done(true);
  };
  window.addEventListener('resize',()=>{ if(editing)endEdit(true); });
}

function applyReadonlyUi(){
  if(!READONLY)return;
  document.body.classList.add('ck-readonly');
  document.querySelectorAll('header .hbtn').forEach(el=>{ el.hidden=true;el.style.display='none'; });
  const fxbar=document.querySelector('.fxbar'); if(fxbar){fxbar.hidden=true;fxbar.style.display='none';}
  const grid=$('grid-wrap'); if(grid){grid.style.top='48px';grid.style.bottom='50px';}
  const fx=$('fx'); if(fx){fx.readOnly=true;fx.tabIndex=-1;}
  const ed0=ed(); if(ed0)ed0.disabled=true;
  const fill=$('fill-handle'); if(fill)fill.hidden=true;
  const dd=$('dd-btn'); if(dd)dd.hidden=true;
  const hs=$('hsub'); if(hs){hs.title='読み取り専用';hs.style.cursor='default';}
  const hint=document.querySelector('.status .hint');
  document.querySelectorAll('.status>span').forEach(el=>{el.style.display='none';});
  const fe=$('st-flt'); if(fe)fe.style.display='inline';   // 絞り込み中の件数だけは残す
  if(hint)hint.textContent='読み取り専用　タブで最新表を切り替え／見出しの▽で絞り込み／セルを選択してコピー可能';
  if(EMBED)document.body.classList.add('ck-embed');
}
function applyReviewUi(){
  if(!REVIEW)return;
  document.body.classList.add('ck-review');
  document.querySelectorAll('header .hbtn').forEach(el=>{el.style.display='none';});
  ['bsave','bxls'].forEach(id=>{const el=$(id);if(el){el.hidden=false;el.style.display='inline-block';}});
  if($('bsave'))$('bsave').textContent='保存 (.calc)';
  if($('bxls'))$('bxls').textContent='Excel';
  const fxbar=document.querySelector('.fxbar');if(fxbar)fxbar.style.display='none';
  const grid=$('grid-wrap');if(grid){grid.style.top='48px';grid.style.bottom='42px';}
  const fill=$('fill-handle');if(fill){fill.hidden=true;fill.style.display='none';}
  const dd=$('dd-btn');if(dd){dd.hidden=false;dd.style.display='none';}
  document.querySelectorAll('.status>span').forEach(el=>{el.style.display='none';});
  const fe=$('st-flt'); if(fe)fe.style.display='inline';   // 絞り込み中の件数だけは残す
  if(EMBED)document.body.classList.add('ck-embed');
}
function initExternalBridge(){
  if(!EMBED)return;
  window.addEventListener('message',e=>{
    if(e.source!==parent||!e.data||e.data.type!=='calckit:load')return;
    try{
      loadDocument(e.data.doc);
      parent.postMessage({type:'calckit:loaded',name:doc.name,sheets:doc.sheets.map(s=>s.name)},'*');
    }catch(err){
      parent.postMessage({type:'calckit:error',message:String(err&&err.message||err)},'*');
    }
  });
  parent.postMessage({type:'calckit:ready',hasDocument:REVIEW&&restoredDocument},'*');
}

// ==== 条件付き書式の小窓（規則の管理）====
function parseRangeStr(s){
  if(!s) return null;
  const m=/^\s*([A-Za-z]+[0-9]+)\s*(?::\s*([A-Za-z]+[0-9]+))?\s*$/.exec(s);
  if(!m) return null;
  const a=parseAddr(m[1].toUpperCase()); if(!a) return null;
  const b=m[2]? parseAddr(m[2].toUpperCase()) : a; if(!b) return null;
  return normRange({r1:a.r,c1:a.c,r2:b.r,c2:b.c});
}
function rangeToStr(rg){ return addrOf(rg.r1,rg.c1)+(rg.r1===rg.r2&&rg.c1===rg.c2?'':':'+addrOf(rg.r2,rg.c2)); }
function showCondModal(){
  if(READONLY||REVIEW)return false;
  const rules=sheet().condfmt||[];
  const selStr=rangeToStr(selRange());
  const opL={'>=':'以上','<=':'以下','between':'範囲','contains':'文字を含む','empty':'空'};
  const sw=c=>c?`<span style="display:inline-block;width:12px;height:12px;border:1px solid #cbd5e1;background:${escHtml(c)};vertical-align:middle;margin:0 2px"></span>`:'';
  const listHtml=rules.length? rules.map((r,i)=>{
    let desc,style;
    if(r.kind==='databar'){ desc='データバー'; style=sw(r.barColor); }
    else{ const val=r.op==='contains'?('「'+(r.text||'')+'」'):r.op==='between'?((r.v1)+'〜'+(r.v2)):r.op==='empty'?'':(r.v1);
      desc=(opL[r.op]||r.op)+(val!==''&&val!=null?' '+val:'');
      style=sw(r.bg)+(r.color?`<span style="color:${escHtml(r.color)};font-weight:700">A</span>`:'')+(r.bold?'<b>太</b>':''); }
    return `<div style="display:flex;align-items:center;gap:8px;padding:5px 2px;border-bottom:1px solid var(--border)">
      <span style="flex:1;font-size:13px">${escHtml(rangeToStr(r.range))}：${escHtml(desc)} ${style}</span>
      <button class="fbtn" data-del="${i}">削除</button></div>`;
  }).join('') : '<div class="note">まだ規則はありません</div>';
  openModal(`<h3>条件付き書式</h3>
    <div style="max-height:150px;overflow:auto;margin-bottom:10px">${listHtml}</div>
    <div style="border-top:2px solid var(--border);padding-top:8px">
    <label>範囲</label><input id="cf-range" value="${escHtml(selStr)}">
    <label>種類</label><select id="cf-kind">
      <option value="cell">セルの値で色を付ける</option>
      <option value="databar">データバー（セル内の横棒）</option></select>
    <div id="cf-cell">
      <label>条件</label><select id="cf-op">
        <option value=">=">値が ○ 以上</option><option value="<=">値が ○ 以下</option>
        <option value="between">範囲 ○〜○</option><option value="contains">文字を含む</option>
        <option value="empty">空セル</option></select>
      <div style="display:flex;gap:8px;margin-top:4px">
        <input id="cf-v1" placeholder="値" style="flex:1">
        <input id="cf-v2" placeholder="上限" style="flex:1;display:none">
        <input id="cf-text" placeholder="文字" style="flex:1;display:none"></div>
      <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:10px">
        <label style="margin:0;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="cf-bgon" checked>塗り <input type="color" id="cf-bg" value="#fde68a" style="width:40px;padding:0"></label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="cf-fgon">文字色 <input type="color" id="cf-fg" value="#b91c1c" style="width:40px;padding:0"></label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="cf-bold">太字</label>
      </div>
    </div>
    <div id="cf-bar" style="display:none">
      <label>バーの色</label><input type="color" id="cf-barcolor" value="#9cc3ea" style="width:40px;padding:0"></div>
    </div>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">閉じる</button>
    <button class="m-save" id="m-go">規則を追加</button></div>`);
  const kind=$('cf-kind'),op=$('cf-op');
  const syncKind=()=>{ const b=kind.value==='databar';
    $('cf-bar').style.display=b?'block':'none'; $('cf-cell').style.display=b?'none':'block'; };
  const syncOp=()=>{ const o=op.value;
    $('cf-v1').style.display=(o==='contains'||o==='empty')?'none':'block';
    $('cf-v2').style.display=o==='between'?'block':'none';
    $('cf-text').style.display=o==='contains'?'block':'none'; };
  kind.onchange=syncKind; op.onchange=syncOp; syncKind(); syncOp();
  document.querySelectorAll('#modal [data-del]').forEach(b=>b.onclick=()=>{ removeCondRule(+b.dataset.del); showCondModal(); });
  $('m-go').onclick=()=>{
    const rg=parseRangeStr($('cf-range').value); if(!rg){ alert('範囲の形が正しくありません（例 A1:B5）'); return; }
    if(kind.value==='databar'){ addCondRule({kind:'databar',range:rg,barColor:$('cf-barcolor').value}); }
    else{
      const r={kind:'cell',range:rg,op:op.value};
      if(op.value==='between'){ r.v1=$('cf-v1').value; r.v2=$('cf-v2').value; }
      else if(op.value==='contains'){ r.text=$('cf-text').value; }
      else if(op.value!=='empty'){ r.v1=$('cf-v1').value; }
      if($('cf-bgon').checked) r.bg=$('cf-bg').value;
      if($('cf-fgon').checked) r.color=$('cf-fg').value;
      if($('cf-bold').checked) r.bold=1;
      if(!r.bg&&!r.color&&!r.bold){ alert('塗り・文字色・太字のどれかを選んでください'); return; }
      addCondRule(r);
    }
    showCondModal();   // 一覧を更新して開いたまま
  };
}

// ==== 簡易ピボット（選んだ範囲→新しいシートに集計表）====
function pivotNum(x){ return (typeof x==='number'&&!Number.isInteger(x))? +x.toFixed(4) : x; }
function pivotAgg(agg,list){
  if(agg==='count'){ let n=0; for(const x of list) if(x!=null&&x!=='') n++; return n; }
  let sum=0,cnt=0; for(const x of list){ const n=(typeof x==='number')?x:parseFloat(x); if(isFinite(n)){ sum+=n; cnt++; } }
  if(agg==='avg') return cnt? sum/cnt : 0;
  return sum;
}
function computePivot(meta){
  const si=sheetIdx(meta.srcSheetName); if(si<0) return null;
  const rowAbs=meta.c1+meta.rowField;
  const colAbs=meta.colField>=0? meta.c1+meta.colField : -1;
  const valAbs=meta.c1+meta.valField;
  const dsp=(r,c)=> displayOfIn(si,addrOf(r,c));
  const rawV=(r,c)=> vals[si+'!'+addrOf(r,c)];
  const rowKeys=[],colKeys=[],seenR={},seenC={},recs=[];
  for(let r=meta.r1+1;r<=meta.r2;r++){
    const rk=dsp(r,rowAbs);
    const ck=colAbs>=0? dsp(r,colAbs) : '値';
    const vv=rawV(r,valAbs);
    if(rk===''&&(vv==null||vv==='')) continue;   // 完全に空の行は飛ばす
    if(!(rk in seenR)){ seenR[rk]=1; rowKeys.push(rk); }
    if(!(ck in seenC)){ seenC[ck]=1; colKeys.push(ck); }
    recs.push({rk,ck,v:vv});
  }
  const agg=(rk,ck)=> pivotAgg(meta.agg, recs.filter(x=>(rk==null||x.rk===rk)&&(ck==null||x.ck===ck)).map(x=>x.v));
  const grid={},rowTot={},colTot={};
  for(const rk of rowKeys){ grid[rk]={}; for(const ck of colKeys) grid[rk][ck]=agg(rk,ck); rowTot[rk]=agg(rk,null); }
  for(const ck of colKeys) colTot[ck]=agg(null,ck);
  return {rowName:dsp(meta.r1,rowAbs)||'行', hasCol:colAbs>=0, colName:colAbs>=0?(dsp(meta.r1,colAbs)||'列'):null,
    valHeader:dsp(meta.r1,valAbs)||'値', rowKeys,colKeys,grid,rowTot,colTot,grand:agg(null,null),agg:meta.agg};
}
function writePivot(sh,meta){
  sh.cells={};
  const P=computePivot(meta);
  sh.colW={0:160};
  if(!P){ sh.cells['A1']={v:'（元の範囲が見つかりません）'}; sh.rows=20; sh.cols=10; sh.pivot=meta; return; }
  const aggL={sum:'合計',count:'件数',avg:'平均'}[meta.agg]||'';
  sh.cells['A1']={v:P.rowName,bold:1,bg:'#EEF3F8'};
  let lastCol;
  if(P.hasCol){
    for(let j=0;j<P.colKeys.length;j++) sh.cells[addrOf(0,1+j)]={v:String(P.colKeys[j]),bold:1,bg:'#EEF3F8',align:'r'};
    const totCol=1+P.colKeys.length; lastCol=totCol;
    sh.cells[addrOf(0,totCol)]={v:'総計',bold:1,bg:'#EEF3F8',align:'r'};
    for(let i=0;i<P.rowKeys.length;i++){ const rk=P.rowKeys[i], r=1+i;
      sh.cells[addrOf(r,0)]={v:String(rk)};
      for(let j=0;j<P.colKeys.length;j++) sh.cells[addrOf(r,1+j)]={v:String(pivotNum(P.grid[rk][P.colKeys[j]]))};
      sh.cells[addrOf(r,totCol)]={v:String(pivotNum(P.rowTot[rk])),bold:1};
    }
    const tr=1+P.rowKeys.length;
    sh.cells[addrOf(tr,0)]={v:'総計',bold:1};
    for(let j=0;j<P.colKeys.length;j++) sh.cells[addrOf(tr,1+j)]={v:String(pivotNum(P.colTot[P.colKeys[j]])),bold:1};
    sh.cells[addrOf(tr,totCol)]={v:String(pivotNum(P.grand)),bold:1};
    sh.rows=Math.max(30,tr+8);
  }else{
    sh.cells['B1']={v:aggL+'：'+P.valHeader,bold:1,bg:'#EEF3F8',align:'r'}; lastCol=1;
    for(let i=0;i<P.rowKeys.length;i++){ const rk=P.rowKeys[i], r=1+i;
      sh.cells[addrOf(r,0)]={v:String(rk)};
      sh.cells[addrOf(r,1)]={v:String(pivotNum(P.rowTot[rk]))};
    }
    const tr=1+P.rowKeys.length;
    sh.cells[addrOf(tr,0)]={v:'総計',bold:1};
    sh.cells[addrOf(tr,1)]={v:String(pivotNum(P.grand)),bold:1};
    sh.rows=Math.max(30,tr+8);
  }
  sh.cols=Math.max(12,lastCol+4);
  sh.pivot=meta;
}
function createPivot(meta){
  if(READONLY)return 'READONLY';
  if(meta.rowField==null||meta.rowField<0) return '行の軸を選んでください';
  if(meta.valField==null||meta.valField<0) return '値の列を選んでください';
  pushUndo();
  const sh=newSheet(uniqueSheetName('ピボット'));
  writePivot(sh,meta);
  doc.sheets.push(sh); doc.active=doc.sheets.length-1; cur={r:0,c:0}; selA=null;
  recalc(); buildGrid(); markDirty();
  return null;
}
function refreshPivot(i){
  if(READONLY)return false;
  const sh=doc.sheets[i]; if(!sh||!sh.pivot) return false;
  pushUndo(); writePivot(sh,sh.pivot);
  if(i===doc.active){ recalc(); buildGrid(); } else recalc();
  markDirty(); return true;
}
function pivotFields(rg){ const h=[]; for(let c=rg.c1;c<=rg.c2;c++) h.push(displayOf(addrOf(rg.r1,c))||colName(c)); return h; }
function showPivotModal(){
  if(READONLY||REVIEW)return false;
  if(sheet().pivot){
    const m=sheet().pivot;
    openModal(`<h3>ピボット</h3>
      <div class="note">このシートは「${escHtml(m.srcSheetName)}」の ${escHtml(rangeToStr(m))} から作った集計表です。<br>
      もとの範囲を直したら「更新」で作り直せます。</div>
      <div class="modal-btns"><button class="m-cancel" id="m-cancel">閉じる</button>
      <button class="m-save" id="m-go">更新</button></div>`);
    $('m-go').onclick=()=>{ refreshPivot(doc.active); closeModal(); toast('ピボットを更新した'); };
    return;
  }
  const rg=normRange(selRange());
  if(rg.r1===rg.r2){ alert('ピボットのもとにする範囲（先頭行が見出し）を選んでください'); return; }
  const h=pivotFields(rg);
  const opt=(sel,none)=> (none?'<option value="-1">（なし）</option>':'')
    +h.map((x,i)=>`<option value="${i}"${i===sel?' selected':''}>${escHtml(x)}</option>`).join('');
  openModal(`<h3>ピボット集計表を作る</h3>
    <div class="note">選んだ範囲 ${escHtml(rangeToStr(rg))}（先頭行が見出し）から、行の軸・列の軸・値を選んで新しいシートに集計します。</div>
    <label>行の軸</label><select id="pv-row">${opt(0)}</select>
    <label>列の軸（任意）</label><select id="pv-col">${opt(-1,true)}</select>
    <label>値</label><select id="pv-val">${opt(h.length>1?1:0)}</select>
    <label>集計</label><select id="pv-agg">
      <option value="sum">合計</option><option value="count">件数</option><option value="avg">平均</option></select>
    <div class="modal-btns"><button class="m-cancel" id="m-cancel">キャンセル</button>
    <button class="m-save" id="m-go">作成</button></div>`);
  $('m-go').onclick=()=>{
    const meta={srcSheetName:sheet().name,r1:rg.r1,c1:rg.c1,r2:rg.r2,c2:rg.c2,
      rowField:+$('pv-row').value,colField:+$('pv-col').value,valField:+$('pv-val').value,agg:$('pv-agg').value};
    const err=createPivot(meta); if(err){ alert(err); return; }
    closeModal(); toast('ピボット集計表を作った');
  };
}

// ==== .xlsx の見た目（太字・文字色・横位置）を zip から補う ====
//   SheetJS無料版は塗り色と書式(z)は読めるが、太字・文字色・横位置は落とす。そこで xlsx(=zip)の
//   styles.xml とシートXMLを自前で読み、値のあるセルに足す。DecompressionStreamで file:// でも動く。
function rgbHex(rgb){ if(!rgb||typeof rgb!=='string')return null; let h=rgb.replace('#','').trim();
  if(h.length===8)h=h.slice(2); if(!/^[0-9a-fA-F]{6}$/.test(h))return null; return '#'+h.toUpperCase(); }
function fillHexOf(cell){ const s=cell.s; if(!s||s.patternType!=='solid')return null;
  return rgbHex(s.fgColor&&s.fgColor.rgb); }
function xlsxFmtOf(cell){
  if(cell.t!=='n') return null;
  const z=cell.z; if(!z||typeof z!=='string'||z==='General') return null;
  try{ if(window.XLSX&&XLSX.SSF&&XLSX.SSF.is_date&&XLSX.SSF.is_date(z)) return 'date'; }catch(_){}
  if(z.indexOf('%')>=0) return 'pct';
  if(/[¥￥$€£]/.test(z)) return 'yen';
  if(/0\.0/.test(z)) return 'dec2';
  if(z.indexOf('#,##0')>=0) return 'num';
  return null;
}
async function inflateRaw(bytes){
  const ds=new DecompressionStream('deflate-raw');
  const ab=await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer();
  return new Uint8Array(ab);
}
async function unzipEntries(buf,want){
  const u=new Uint8Array(buf);
  const dv=new DataView(u.buffer,u.byteOffset,u.byteLength);
  let eo=-1;
  for(let i=u.length-22;i>=0&&i>u.length-22-65536;i--){ if(dv.getUint32(i,true)===0x06054b50){ eo=i; break; } }
  if(eo<0) return {};
  const cnt=dv.getUint16(eo+10,true); let off=dv.getUint32(eo+16,true);
  const out={},pend=[];
  for(let k=0;k<cnt;k++){
    if(off+46>u.length||dv.getUint32(off,true)!==0x02014b50) break;
    const method=dv.getUint16(off+10,true);
    const csize=dv.getUint32(off+20,true);
    const fnl=dv.getUint16(off+28,true), efl=dv.getUint16(off+30,true), cml=dv.getUint16(off+32,true);
    const lho=dv.getUint32(off+42,true);
    const name=new TextDecoder().decode(u.subarray(off+46,off+46+fnl));
    off+=46+fnl+efl+cml;
    if(!want(name)) continue;
    const lfnl=dv.getUint16(lho+26,true), lefl=dv.getUint16(lho+28,true);
    const ds=lho+30+lfnl+lefl, data=u.subarray(ds,ds+csize);
    if(method===0) out[name]=data.slice();
    else if(method===8) pend.push(inflateRaw(data).then(r=>{ out[name]=r; }));
  }
  await Promise.all(pend);
  return out;
}
function colorAttrHex(el){ return el&&el.getAttribute? rgbHex(el.getAttribute('rgb')) : null; }
function parseStylesXml(xml){
  const d=new DOMParser().parseFromString(xml,'application/xml');
  const first=t=>d.getElementsByTagName(t)[0];
  const numFmts={}; const nfp=first('numFmts');
  if(nfp) for(const n of nfp.getElementsByTagName('numFmt')) numFmts[n.getAttribute('numFmtId')]=n.getAttribute('formatCode');
  const fonts=[]; const fp=first('fonts');
  if(fp) for(const f of fp.getElementsByTagName('font')){
    const b=f.getElementsByTagName('b')[0];
    const bold=!!b&&b.getAttribute('val')!=='0'&&b.getAttribute('val')!=='false';
    fonts.push({bold,color:colorAttrHex(f.getElementsByTagName('color')[0])});
  }
  const fills=[]; const fl=first('fills');
  if(fl) for(const f of fl.getElementsByTagName('fill')){
    const pf=f.getElementsByTagName('patternFill')[0];
    const solid=pf&&pf.getAttribute('patternType')==='solid';
    fills.push({color: solid? colorAttrHex(pf.getElementsByTagName('fgColor')[0]) : null});
  }
  const xfs=[]; const cx=first('cellXfs');
  if(cx) for(const x of cx.getElementsByTagName('xf')){
    const al=x.getElementsByTagName('alignment')[0];
    xfs.push({numFmtId:x.getAttribute('numFmtId'),fontId:+x.getAttribute('fontId')||0,
      fillId:+x.getAttribute('fillId')||0,align:al?al.getAttribute('horizontal'):null});
  }
  return {numFmts,fonts,fills,xfs};
}
function sheetFileOrder(wbXml,relsXml,files){
  const order=[];
  if(wbXml&&relsXml){
    const rd=new DOMParser().parseFromString(relsXml,'application/xml');
    const rel={}; for(const r of rd.getElementsByTagName('Relationship')) rel[r.getAttribute('Id')]=r.getAttribute('Target');
    const wd=new DOMParser().parseFromString(wbXml,'application/xml');
    for(const s of wd.getElementsByTagName('sheet')){
      const rid=s.getAttribute('r:id')||s.getAttribute('id'); let tgt=rel[rid]; if(!tgt)continue;
      if(tgt[0]==='/') tgt=tgt.slice(1); else tgt='xl/'+tgt.replace(/^\.\//,'');
      tgt=tgt.replace(/^xl\/xl\//,'xl/');
      order.push(tgt);
    }
  }
  if(!order.length) return Object.keys(files).filter(k=>/^xl\/worksheets\/sheet\d+\.xml$/.test(k))
    .sort((a,b)=>(+a.match(/\d+/)[0])-(+b.match(/\d+/)[0]));
  return order;
}
function applyStylesToSheet(sh,xml,styles){
  const d=new DOMParser().parseFromString(xml,'application/xml');
  const cells=d.getElementsByTagName('c'); let n=0;
  for(const c of cells){
    const ref=c.getAttribute('r'); if(!ref) continue;
    const sIdx=c.getAttribute('s'); if(sIdx==null) continue;
    const xf=styles.xfs[+sIdx]; if(!xf) continue;
    const cl=sh.cells[ref]; if(!cl) continue;        // 値のあるセルだけに足す
    const font=styles.fonts[xf.fontId];
    if(font){ if(font.bold&&!cl.bold){ cl.bold=1; n++; } if(font.color&&!cl.color){ cl.color=font.color; n++; } }
    const fill=styles.fills[xf.fillId];
    if(fill&&fill.color&&!cl.bg){ cl.bg=fill.color; n++; }
    if(xf.align){ const m={left:'l',center:'c',right:'r'}[xf.align]; if(m&&!cl.align){ cl.align=m; n++; } }
  }
  return n;
}
async function enrichXlsxStyles(buf){
  try{
    if(typeof DecompressionStream==='undefined') return;
    const files=await unzipEntries(buf,n=>n==='xl/styles.xml'||n==='xl/workbook.xml'
      ||n==='xl/_rels/workbook.xml.rels'||/^xl\/worksheets\/sheet\d+\.xml$/.test(n));
    if(!files['xl/styles.xml']) return;
    const dec=new TextDecoder('utf-8');
    const styles=parseStylesXml(dec.decode(files['xl/styles.xml']));
    const order=sheetFileOrder(files['xl/workbook.xml']&&dec.decode(files['xl/workbook.xml']),
      files['xl/_rels/workbook.xml.rels']&&dec.decode(files['xl/_rels/workbook.xml.rels']),files);
    let changed=0;
    for(let si=0;si<doc.sheets.length&&si<order.length;si++){
      const x=files[order[si]]; if(!x) continue;
      changed+=applyStylesToSheet(doc.sheets[si],dec.decode(x),styles);
    }
    if(lastImport) lastImport.styled=changed;
    if(changed){ recalc(); refreshCells(); }
  }catch(e){ /* 見た目は任意。失敗しても値は入っている */ }
}

// ==== 公開API（検証・Kiro操作用） ====
window.CalcKit={
  get doc(){ return READONLY?JSON.parse(JSON.stringify(doc)):doc; },
  get readonly(){ return READONLY; },
  loadDocument,
  importXlsx(buf,name){ return importXlsxArrayBuffer(name||'book.xlsx',buf); },
  get lastImport(){ return lastImport; },
  setCell(a,v){ return setCellAndRecalc(a.toUpperCase(),v); },
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
  addFilter(range){ return setFilterRange(range); },
  clearFilter,
  get filter(){ return sheet().filter||null; },
  filterCol(col,values){ // values=表示する値の配列（displayOf基準）／null・undefinedで解除
    const f=sheet().filter; if(!f) return false;
    const c=typeof col==='string'? colIndex(col.toUpperCase()) : col;
    if(values==null) delete f.sel[String(c)]; else f.sel[String(c)]=values.map(String);
    refreshCells(); applyFilterView();
    return true;
  },
  filterValues(col){ const c=typeof col==='string'? colIndex(col.toUpperCase()) : col; return colValues(c); },
  visibleRows(){ const f=sheet().filter; if(!f) return null;
    const out=[]; for(let r=f.r+1;r<=f.r2;r++) if(rowVisible(r)) out.push(r+1); return out; },
  align(prop,val){ applyAlign(prop,val); },
  setOpts(list){ setOpts(list); },
  copySel(){ copySel(null); }, pasteText(t){ pasteAt(t); },
  buildCSV,buildSlideHtml,buildChartSlideHtml,buildGanttData,buildGanttPayload,buildChartData,buildPieData,
  loadTemplate,usedRange,
  addCondRule,removeCondRule,clearCondRules,
  get condRules(){ return sheet().condfmt||[]; },
  condStyle(a){ const u=a.toUpperCase(); const p=parseAddr(u); return p? cfStyleAt(u,p.r,p.c,V(u)) : null; },
  createPivot,refreshPivot,
  get pivotMeta(){ return sheet().pivot||null; },
  importXlsxAsync(buf,name){ const ok=importXlsxArrayBuffer(name||'book.xlsx',buf,true);
    return ok? enrichXlsxStyles(buf).then(()=>lastImport) : Promise.resolve(false); },
  setName(n){ if(READONLY)return false; setName(n); markDirty(); },
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
    // 決定: data-palette="custom" を宣言する。凡例の●はDashboardKitの系列色と揃える必要がある。
    // 既定テーマ(seiryoku)の6色は slidekit-defs.js の chartPalette に登録したので宣言なしでも
    // 通るが、**テーマを切り替えると別の6色になる**ので宣言は残す（pastel等はカタログ外）。
    // 凡例は .tb のままにしてPPTXで編集できる形を保つ（SVGに焼き込まない）。2026-08-21
    // 根拠=.kiro/steering/slide-contract-detail.md のカラートークン表
    return `<!DOCTYPE html>
<html lang="ja" data-palette="custom">
<head><meta charset="utf-8"><title>${escHtml(doc.name)}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Yu Gothic','游ゴシック','Noto Sans JP',sans-serif;background:#2d3748;display:flex;flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;background:#fafafa}
.tb{position:absolute;overflow:hidden;line-height:1.5}
</style></head>
<body>
<!-- SLIDE: ${escHtml(doc.name)}（グラフ） [D09] -->
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
    // 30分。デッキ側がスライドを受け取るたびに ts を更新して延命する（放置すれば消えて
    // ボタンが出なくなる＝古いデッキ宛に飛ぶ事故を防ぐ。2026-08-21修正）
    if(r&&r.deck&&Date.now()-r.ts<30*60*1000) ret=r;
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
  const fromGantt=READONLY?false:initGanttImport();
  if(!fromGantt&&!READONLY){
    const saved=localStorage.getItem(STORAGE_KEY);
    if(saved){ try{ const d=JSON.parse(saved); if(d&&(d.cells||d.sheets)){doc=normalizeDoc(d);restoredDocument=true;} }catch(_){ doc=null; } }
  }
  if(!doc) doc=READONLY?newDoc('読み込み待ち',20,10):tmplPL();
  recalc(); buildGrid(); setName(doc.name);
  READONLY?wireReadonlyEvents():wireEvents();
  wireFilter();
  paintSel(); applyReadonlyUi(); applyReviewUi(); initSlideKitReturn(); initExternalBridge();
  if(fromGantt){ markDirty(); toast('GanttKitの計画を表として開いた（日数はF列の式。ガントに戻すには「ガント書き出し」）'); }
}
init();
})();
