#!/usr/bin/env python3
"""ブラウザの描画結果を測る（試作・2026-10-14）。
  python3 SlideKit/measure_layout.py 対象.html [--json 出力.json]

Chrome headless でデッキを開き、見えている通りの値を1要素ずつ取る。
・位置・大きさ（data-x/y/w/h と食い違えば報告＝規則6の破れ）
・.tb の文字を1文字ずつ（太字・大きさ・色）→ 変換側の読み取り（rich_lines）と食い違えば報告
・行数、中身のあふれ（.flow も含む）、PPTXに出ない文字（.rect 直下の .tb 以外に書いた文字など）

html_to_pptx.py --measured はここの tag_html / measure_tagged / remap_runs を使い、
位置と文字の書式を実測で上書きして変換する。
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _chrome():
    from run_check import _find_chrome
    return _find_chrome()


def tag_html(raw_html):
    """.slide 内の要素に通し番号 data-mid を振った HTML を返す（SVG の中は振らない）。
    ブラウザで測った値と、変換側が読む要素を同じ番号で突き合わせるため"""
    soup = BeautifulSoup(raw_html, 'html.parser')  # 属性の大文字小文字を保つ（SVG の viewBox 等）
    n = 0
    for s in soup.find_all('div', class_='slide'):
        for el in s.find_all(True):
            if el.name == 'svg' or el.find_parent('svg') is not None:
                continue
            el['data-mid'] = str(n)
            n += 1
    return str(soup), n


# ブラウザ側で測る処理。結果は base64(JSON) にして document.title に入れ、--dump-dom で回収する
_MEASURE_JS = r'''
<script>
(function(){
function hex(c){var m=/rgba?\(([^)]+)\)/.exec(c||'');if(!m)return null;
  var p=m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
  return p.slice(0,3).map(function(v){return ('0'+Math.round(v).toString(16)).slice(-2);}).join('');}
function pos(el,slide){var x=0,y=0,e=el;
  while(e&&e!==slide){x+=e.offsetLeft;y+=e.offsetTop;var op=e.offsetParent;
    if(op&&op!==slide){x+=op.clientLeft;y+=op.clientTop;}e=op;}
  if(e!==slide){var a=el.getBoundingClientRect(),b=slide.getBoundingClientRect();return [a.left-b.left,a.top-b.top];}
  return [x,y];}
function visible(n){var e=n.nodeType===3?n.parentElement:n;
  while(e){var cs=getComputedStyle(e);if(cs.display==='none'||cs.visibility==='hidden')return false;
    if(e.classList&&e.classList.contains('slide'))return true;e=e.parentElement;}return true;}
function charsOf(el){var out=[],tops=[],tw=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),n;
  while((n=tw.nextNode())){var t=n.data.replace(/\s+/g,'');if(!t)continue;
    var pe=n.parentElement;if(pe.closest('.seui')||!visible(n))continue;
    var cs=getComputedStyle(pe);
    out.push([t,parseFloat(cs.fontSize),parseInt(cs.fontWeight,10)>=600?1:0,hex(cs.color)]);
    var r=document.createRange();r.selectNodeContents(n);var rs=r.getClientRects();
    for(var i=0;i<rs.length;i++){if(rs[i].width>0.5)tops.push([rs[i].top,rs[i].height]);}}
  tops.sort(function(a,b){return a[0]-b[0];});var lines=0,last=-1e9;
  tops.forEach(function(t){if(t[0]-last>t[1]*0.5){lines++;last=t[0];}});
  return {runs:out,lines:lines};}
function lostText(el){var lost='',tw=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),n;
  while((n=tw.nextNode())){var t=n.data.replace(/\s+/g,'');if(!t||!visible(n))continue;
    var tb=n.parentElement.closest('.tb');if(!tb||tb.parentElement!==el)lost+=t;}
  return lost;}
function rgba(c){var m=/rgba?\(([^)]+)\)/.exec(c||'');if(!m)return 0;
  var p=m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);return p.length>3?p[3]:1;}
// SlideKitの型に乗っていない自由配置のdiv（flexの行など）。見えている箱と文字を1つずつ拾う
function freeItems(root,s){var out=[],sr=s.getBoundingClientRect();
  [root].concat([].slice.call(root.querySelectorAll('*'))).forEach(function(e){
    if(!visible(e))return;var cs=getComputedStyle(e),b=e.getBoundingClientRect();
    var bx=b.left-sr.left,by=b.top-sr.top;
    if(rgba(cs.backgroundColor)>0.02&&b.width>0&&b.height>0)
      out.push({k:'box',x:bx,y:by,w:b.width,h:b.height,fill:hex(cs.backgroundColor)});
    // 枠線は辺ごとに細い箱にする（区切り線の行など）
    [['Top',0],['Bottom',1],['Left',2],['Right',3]].forEach(function(sd){
      var bw=parseFloat(cs['border'+sd[0]+'Width'])||0,bc=cs['border'+sd[0]+'Color'];
      if(bw<=0||cs['border'+sd[0]+'Style']==='none'||rgba(bc)<=0.02)return;
      var q=sd[1]===0?[bx,by,b.width,bw]:sd[1]===1?[bx,by+b.height-bw,b.width,bw]
            :sd[1]===2?[bx,by,bw,b.height]:[bx+b.width-bw,by,bw,b.height];
      out.push({k:'box',x:q[0],y:q[1],w:q[2],h:q[3],fill:hex(bc)});});
    var t='',rg=null;for(var i=0;i<e.childNodes.length;i++){var n=e.childNodes[i];
      if(n.nodeType!==3||!n.data.trim())continue;t+=n.data;
      var r=document.createRange();r.selectNodeContents(n);var q=r.getBoundingClientRect();
      rg=rg?{l:Math.min(rg.l,q.left),t:Math.min(rg.t,q.top),r:Math.max(rg.r,q.right),b:Math.max(rg.b,q.bottom)}
        :{l:q.left,t:q.top,r:q.right,b:q.bottom};}
    t=t.replace(/[ \t\r\n]+/g,' ').trim();
    if(t&&rg)out.push({k:'text',x:rg.l-sr.left,y:rg.t-sr.top,w:rg.r-rg.l,h:rg.b-rg.t,t:t,
      fs:parseFloat(cs.fontSize),b:parseInt(cs.fontWeight,10)>=600?1:0,c:hex(cs.color),ta:cs.textAlign});});
  return out;}
// SVGの中の文字（PPTXでは画像に焼き込まれてしまう）を1つずつ測る。変換側がPPTXの文字枠に置き直す
function svgTexts(el,s){var out=[],sr=s.getBoundingClientRect();
  el.querySelectorAll('svg text').forEach(function(t){
    if(t.closest('defs,clipPath,mask,pattern,symbol,marker')||!visible(t))return;
    var parts=[].slice.call(t.querySelectorAll('tspan')).filter(function(sp){
      return sp.hasAttribute('y')||sp.hasAttribute('dy')||sp.hasAttribute('x');});
    (parts.length>1?parts:[t]).forEach(function(n){
      var txt=(n.textContent||'').replace(/\s+/g,' ').trim();if(!txt)return;
      var cs=getComputedStyle(n),m=n.getScreenCTM(),sc=m?Math.sqrt(m.a*m.a+m.b*m.b):1;
      var ang=m?Math.atan2(m.b,m.a)*180/Math.PI:0,b=n.getBoundingClientRect(),len=0;
      try{len=n.getComputedTextLength()*sc;}catch(e){len=b.width;}
      var fill=cs.fill&&cs.fill.indexOf('url')<0&&cs.fill!=='none'?hex(cs.fill):null;
      out.push({t:txt,x:b.left-sr.left,y:b.top-sr.top,w:b.width,h:b.height,len:len,ang:ang,
        fs:parseFloat(cs.fontSize)*sc,b:parseInt(cs.fontWeight,10)>=600?1:0,c:fill||'121212',
        anchor:cs.textAnchor||'start'});});});
  return out;}
// 文字と、その真下に見えている地の色のコントラスト（WCAG）。地は重なった要素を上から順に見て決める
function lum(h){var c=[0,2,4].map(function(i){var v=parseInt(h.substr(i,2),16)/255;
  return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];}
function ratio(a,b){var x=lum(a),y=lum(b);return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);}
function bgUnder(el){
  var own=/rgba?\(([^)]+)\)/.exec(getComputedStyle(el).backgroundColor||'');
  if(own){var ov=own[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);if((ov.length>3?ov[3]:1)>=0.5)return [hex(getComputedStyle(el).backgroundColor)];}
  el.scrollIntoView({block:'center'});var b=el.getBoundingClientRect();
  var st=document.elementsFromPoint(b.left+b.width/2,b.top+Math.min(b.height/2,14));
  for(var i=0;i<st.length;i++){var e=st[i];
    // 編集UIは飛ばす。ただしAWS表紙の光彩背景（.seui.aws-overlay）はスライドの地なので見る
    if(e===el||el.contains(e)||(e.closest&&e.closest('.seui')&&!e.classList.contains('aws-overlay')))continue;
    if(/^(IMG|VIDEO|CANVAS|svg)$/.test(e.tagName)||(e.closest&&e.closest('svg')))return null; // 画像の上は測れない
    var cs=getComputedStyle(e),bi=cs.backgroundImage;
    if(bi&&bi!=='none'){var cols=(bi.match(/rgba?\([^)]+\)/g)||[]).map(hex).filter(Boolean);if(cols.length)return cols;if(/url\(/.test(bi))return null;}
    var p=/rgba?\(([^)]+)\)/.exec(cs.backgroundColor||'');
    if(p){var v=p[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);if((v.length>3?v[3]:1)>=0.5)return [hex(cs.backgroundColor)];}
    if(e.classList&&e.classList.contains('slide'))return ['ffffff'];}
  return ['ffffff'];}
function contrastOf(el,runs){
  // 矢印・▼などの記号だけの文字は飾り（読ませる文字ではない）ので見ない
  if(!/[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]/.test(el.textContent||''))return null;
  var bg=bgUnder(el);if(!bg)return null;var worst=null;
  runs.forEach(function(r){if(!r[3])return;var big=r[1]>=24||(r[2]&&r[1]>=18.66),need=big?3:4.5;
    bg.forEach(function(g){var q=ratio(r[3],g);if(q<need&&(!worst||q<worst[0]))worst=[+q.toFixed(2),r[3],g,need];});});
  return worst;}
function run(){var res={slides:[],els:{},cover:[]};
  // 地の色を重なり順で拾うため、スライドの中は全部クリックの当たりに含める
  // （pointer-events:none の要素＝AWS表紙の光彩背景などは elementsFromPoint に出てこない）
  var pe=document.createElement('style');pe.textContent='.slide, .slide *{pointer-events:auto !important}';document.head.appendChild(pe);
  document.querySelectorAll('.slide').forEach(function(s,si){
    res.slides.push([s.offsetWidth,s.offsetHeight]);
    if(s.classList.contains('aws-cover'))res.cover.push(si+1);
    s.querySelectorAll('[data-mid]').forEach(function(el){
      var cl=el.classList,isTb=cl.contains('tb'),isBox=cl.contains('rect')||cl.contains('flow');
      var top=el.parentElement===s;if(!(top||isTb))return;
      var p=pos(el,s),r={s:si+1,x:p[0],y:p[1],w:el.offsetWidth,h:el.offsetHeight,top:top?1:0,
        vis:visible(el)?1:0};
      if(isTb){var c=charsOf(el);r.runs=c.runs;r.lines=c.lines;r.ov=el.scrollHeight-el.clientHeight;
        if(c.runs.length&&visible(el)){var ct=contrastOf(el,c.runs);if(ct)r.contrast=ct;}
        r.fs=parseFloat(getComputedStyle(el).fontSize);}
      // グラフ（data-chart）は数値から作り直すので測らない。サンキーだけは図形と文字枠にする（PowerPointに同じグラフが無い）
      var drawn=!el.hasAttribute('data-chart')||!!el.querySelector('svg[data-sk-chart="sankey"],svg[data-sk-chart="map"]');
      if(top&&drawn&&el.querySelector('svg text')){r.svgText=svgTexts(el,s);}
      if(top&&drawn&&el.querySelector('svg')&&window.__skSvgShapes){
        var sv=window.__skSvgShapes(el,s);r.svgShapes=sv.shapes;if(sv.why)r.svgWhy=sv.why;if(sv.partial)r.svgPartial=sv.partial;}
      if(isBox){r.ov=el.scrollHeight-el.clientHeight;var lt=lostText(el);if(lt)r.lost=lt.slice(0,40);}
      else if(top&&!isTb&&el.tagName==='DIV'&&!cl.contains('ins')&&!el.querySelector('svg,img,video,table')){
        var t2=(el.textContent||'').replace(/\s+/g,'');if(t2&&r.vis){r.lost=t2.slice(0,40);r.free=freeItems(el,s);}}
      res.els[el.getAttribute('data-mid')]=r;});});
  var js=JSON.stringify(res);
  document.title='__SKM__'+btoa(unescape(encodeURIComponent(js)));}
window.addEventListener('load',function(){
  var go=function(){setTimeout(function(){try{run();}catch(e){document.title='__SKMERR__'+e.message;}},400);};
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(go);else go();});
})();
</script>
'''


def _vector_js():
    """SVGの図形をPowerPointの図形にするための測定（svg_shapes.js）。無ければ空＝従来どおり画像にする"""
    p = os.path.join(HERE, 'svg_shapes.js')
    if not os.path.exists(p):
        return ''
    return '<script>\n' + open(p, encoding='utf-8').read() + '\n</script>\n'


def measure_tagged(html_path, tagged_html, timeout=90):
    """data-mid 付きの HTML を元HTMLと同じフォルダで開いて測る（画像・スクリプトの相対パスを保つ）。
    返り値: {'slides': [[w,h],...], 'els': {mid: {...}}}。測れなければ RuntimeError"""
    chrome = _chrome()
    if not chrome:
        raise RuntimeError('Chrome/Chromium/Edge が見つからない（CHROME_PATH で指定できる）')
    idx = tagged_html.rfind('</body>')
    js = _vector_js() + _MEASURE_JS
    src = (tagged_html[:idx] + js + tagged_html[idx:]) if idx >= 0 else tagged_html + js
    fd, tmp = tempfile.mkstemp(prefix='.skmeasure-', suffix='.html', dir=os.path.dirname(html_path))
    # 🚫 以前は capture_output=True（stdout をパイプ）で --dump-dom を受けていたが、Chrome 157 では
    #   DOM を吐いた後も後始末（crashpad・GPU・network の子）がそのパイプの書き端を握ったまま 30 秒ほど
    #   居座り、EOF が来ず subprocess.run が timeout まで必ず待ってしまう（最小のデッキでも 90 秒で
    #   TimeoutExpired）。stdout を実ファイルに落とすと本体の終了で run が返り、同じ測定が約 15 秒で済む。
    #   （2026-11-15）
    outf = tmp + '.dom'
    profile = tempfile.mkdtemp(prefix='.skmprof-')  # 既定プロファイルと競合させない専用の一時プロファイル（2026-11-15）
    timed_out = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(src)
        with open(outf, 'w', encoding='utf-8') as fo:
            try:
                subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                                '--mute-audio', '--user-data-dir=' + profile,  # 🚫 --mute-audio なし・既定プロファイルは禁止（キット群の決まり／競合よけ）（2026-11-15）
                                '--virtual-time-budget=6000', '--window-size=1600,1000',
                                '--dump-dom', 'file://' + tmp], stdout=fo, stderr=subprocess.DEVNULL, timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True  # 時間切れでも落とさず『実測できなかった』に倒す（html_to_pptx は data 属性だけの経路へ戻る）（2026-11-15）
        dom = open(outf, encoding='utf-8').read() if os.path.exists(outf) else ''
    finally:
        for p in (tmp, outf):
            if os.path.exists(p):
                os.unlink(p)
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
    m = re.search(r'<title>__SKM(ERR)?__(.*?)</title>', dom, re.DOTALL)
    if not m:
        raise RuntimeError('測定結果を回収できなかった（時間切れ）' if timed_out
                           else '測定結果を回収できなかった')
    if m.group(1):
        raise RuntimeError('測定中のエラー: ' + m.group(2))
    return json.loads(base64.b64decode(m.group(2)).decode('utf-8'))


def _expand(runs):
    """[(text, fs, bold, color)] を空白を除いた1文字ずつの (ch, fs, bold, color) にする"""
    return [(ch, float(fs), bool(b), (c or '').lower()) for (t, fs, b, c) in runs for ch in t if not ch.isspace()]


def remap_runs(lines, mruns, keep_color=False):
    """変換側の行・段落構成（rich_lines の返り値）はそのままに、各文字の太字・大きさ・色を実測値に置き換える。
    空白を除いた文字の並びが実測と一致しない時は置き換えない（返り値の2番目が False）。
    keep_color=True は色だけ変換側のまま（AWS表紙はブラウザがCSSで色を置き換えて見せているため）"""
    mchars = _expand(mruns)
    if keep_color:
        conv_c = [c for runs, _, _ in lines for (t, _, _, c) in runs for ch in t if not ch.isspace()]
        if len(conv_c) == len(mchars):
            mchars = [m[:3] + (cc,) for m, cc in zip(mchars, conv_c)]
    conv = ''.join(ch for runs, _, _ in lines for (t, _, _, _) in runs for ch in t if not ch.isspace())
    if conv != ''.join(c[0] for c in mchars):
        return lines, False
    k, out = 0, []
    for runs, al, lvl in lines:
        nr = []
        for (t, fs, b, c) in runs:
            cur, buf = None, ''
            for ch in t:
                if ch.isspace():
                    st = cur if cur is not None else (
                        mchars[k][1:] if k < len(mchars) else (fs, b, c))
                else:
                    st = mchars[k][1:]
                    k += 1
                if cur is not None and st != cur:
                    nr.append((buf,) + tuple(cur))
                    buf = ''
                cur, buf = st, buf + ch
            if buf:
                nr.append((buf,) + tuple(cur))
        out.append((nr, al, lvl))
    return out, True


def apply_geometry(soup, M, slide_w, slide_h):
    """スライド直下の要素の data-x/y/w/h を実測値にする（ブラウザで見えている位置が正）。
    返り値: (見た目に合わせた数, 無かった属性を補った数)。スライドの実寸がキャンバスと違う時は何もしない"""
    if any(abs(w - slide_w) > 1 or abs(h - slide_h) > 1 for w, h in M.get('slides', [])):
        return 0, 0
    n = filled = 0
    for el in soup.find_all(attrs={'data-mid': True}):
        r = M['els'].get(el.get('data-mid'))
        if not r or not r.get('top') or not r.get('vis') or el.get('data-x') is None:
            continue
        if r['w'] <= 0 and r['h'] <= 0:
            continue
        for key, v in (('data-x', r['x']), ('data-y', r['y']), ('data-w', r['w']), ('data-h', r['h'])):
            new = str(int(round(v)))
            if el.get(key) is not None and el.get(key) != new:
                try:
                    if abs(float(el.get(key)) - v) <= 1.5:
                        continue  # 1.5px 以内は丸めの差。data の値（21.334 等の小数も）を残す
                except ValueError:
                    pass
            if el.get(key) is None:
                filled += 1
            elif el.get(key) != new:
                n += 1
            el[key] = new
    return n, filled


def compare(html_path, M, tagged_html):
    """実測と、data属性・変換側の読み取りとの食い違いを数える。返り値: (件数dict, 明細list)"""
    import html_to_pptx as H
    soup = BeautifulSoup(tagged_html, 'lxml')
    cnt = {'geom': 0, 'text': 0, 'bold': 0, 'size': 0, 'color': 0, 'overflow': 0, 'lost': 0, 'tb': 0, 'contrast': 0}
    rows = []
    pairs = {}  # コントラスト不足は色の組み合わせごとにまとめる（同じ補足色が何十か所も並ぶため）

    def label(el):
        return re.sub(r'\s+', ' ', el.get_text() or '').strip()[:24]

    for el in soup.find_all(attrs={'data-mid': True}):
        r = M['els'].get(el.get('data-mid'))
        if not r:
            continue
        s = r['s']
        if r.get('top') and r.get('vis') and el.get('data-x') is not None:
            d = []
            for key, v in (('data-x', r['x']), ('data-y', r['y']), ('data-w', r['w']), ('data-h', r['h'])):
                try:
                    if el.get(key) is not None and abs(float(el.get(key)) - v) > 1.5:
                        d.append('%s=%s→見た目%d' % (key[5:], el.get(key), round(v)))
                except ValueError:
                    pass
            if d:
                cnt['geom'] += 1
                rows.append((s, 'geom', label(el), ' '.join(d)))
        if r.get('lost'):
            cnt['lost'] += 1
            rows.append((s, 'lost', r['lost'], 'ブラウザに見えるがPPTXに出ない文字（.tb に入れる）'))
        fs_now = r.get('fs') or 16
        if r.get('ov', 0) > max(4, fs_now * 0.4) and r.get('vis'):
            cnt['overflow'] += 1
            rows.append((s, 'overflow', label(el), '中身が枠から%dpxあふれている' % r['ov']))
        if r.get('contrast'):
            q, fg, bg, need = r['contrast']
            cnt['contrast'] += 1
            pairs.setdefault((fg, bg, need), [q, []])[1].append('%d枚目「%s」' % (s, label(el)[:12]))
        if 'tb' not in (el.get('class') or []) or not r.get('runs'):
            continue
        cnt['tb'] += 1
        in_box = any(c in (el.parent.get('class') or []) for c in ('rect', 'flow'))
        fs = float(el.get('data-font-size', 15 if in_box else 17))
        lines = H.rich_lines(el, fs, el.get('data-bold') == '1', H._effective_color(el))
        conv = [(ch, f, bool(b), (H.css_color_hex6(c) or '')) for runs, _, _ in lines
                for (t, f, b, c) in runs for ch in t if not ch.isspace()]
        meas = _expand(r['runs'])
        if ''.join(c[0] for c in conv) != ''.join(c[0] for c in meas):
            cnt['text'] += 1
            rows.append((s, 'text', label(el), '変換側とブラウザで文字の並びが違う'))
            continue
        nb = sum(1 for a, b in zip(conv, meas) if a[2] != b[2])
        nz = sum(1 for a, b in zip(conv, meas) if abs(a[1] - b[1]) > 0.6)
        # AWS表紙はブラウザがCSSで色を置き換えて見せている（変換側も同じ表で置き換える）ので色は比べない
        nc = 0 if s in M.get('cover', []) else sum(
            1 for a, b in zip(conv, meas) if a[3] and b[3] and a[3] != b[3])
        for k, v, msg in (('bold', nb, '太字'), ('size', nz, '大きさ'), ('color', nc, '色')):
            if v:
                cnt[k] += 1
                rows.append((s, k, label(el), '%sが%d文字ちがう（変換側の読み取り≠見た目）' % (msg, v)))
    for (fg, bg, need), (q, where) in sorted(pairs.items(), key=lambda kv: kv[1][0]):
        more = '　ほか%dか所' % (len(where) - 3) if len(where) > 3 else ''
        rows.append((0, 'contrast', '文字#%s・地#%s' % (fg, bg),
                     'コントラスト%.1f:1（%s:1以上にする）%dか所: %s%s' % (q, need, len(where), '、'.join(where[:3]), more)))
    return cnt, rows


def pptx_line_check(html_path, M, tagged_html, extra=()):
    """PPTXの行数をブラウザの行数と比べる。PPTXは LibreOffice で描く（PowerPointとは字の詰め方が少し違う）。
    比べるのはスライド直下の .tb で、他の文字枠と重ならないものだけ。返り値: [(枚, 文字, ブラウザ行, PPTX行)]"""
    import shutil
    import xml.etree.ElementTree as ET
    soffice = next((p for p in ('/opt/homebrew/bin/soffice', '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                                shutil.which('soffice') or '') if p and os.path.exists(p)), None)
    if not soffice or not shutil.which('pdftotext'):
        raise RuntimeError('LibreOffice（soffice）と pdftotext（brew install poppler）が要る')
    work = tempfile.mkdtemp(prefix='skml-')
    try:
        pptx = os.path.join(work, 'deck.pptx')
        subprocess.run([sys.executable, os.path.join(HERE, 'html_to_pptx.py'), html_path, pptx,
                        '--allow-missing-assets'] + list(extra), capture_output=True, text=True, check=True)
        subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', work, pptx],
                       capture_output=True, check=True)
        bbox = os.path.join(work, 'deck.html')
        subprocess.run(['pdftotext', '-bbox-layout', os.path.join(work, 'deck.pdf'), bbox], check=True)
        root = ET.parse(bbox).getroot()
        ns = '{http://www.w3.org/1999/xhtml}'
        pages = []  # ページごとの行の中心（スライドのpx座標）
        for pg in root.iter(ns + 'page'):
            k = 1280.0 / float(pg.get('width'))
            pages.append([((float(l.get('xMin')) + float(l.get('xMax'))) / 2 * k,
                           (float(l.get('yMin')) + float(l.get('yMax'))) / 2 * k)
                          for l in pg.iter(ns + 'line')])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    tbs = [(mid, r) for mid, r in M['els'].items() if r.get('top') and r.get('runs') and r.get('vis')]
    soup = BeautifulSoup(tagged_html, 'html.parser')
    # AWSテンプレートはフッター帯（y676〜）にロゴと著作権の文字を持つ。デッキの文字と混ぜない
    h = soup.find('html')
    if h is not None and (h.get('data-template') in ('aws', 'aws2') or h.get('data-aws-decoration') == 'on'):
        pages = [[(cx, cy) for cx, cy in pg if cy < 676] for pg in pages]
    out = []
    for mid, r in tbs:
        box = (r['x'], r['y'], r['x'] + r['w'], r['y'] + max(r['h'], r['lines'] * r['fs'] * 1.2))
        if any(o is not r and o['s'] == r['s'] and o['x'] < box[2] and o['x'] + o['w'] > box[0]
               and o['y'] < box[3] and o['y'] + o['h'] > box[1] for _, o in tbs):
            continue  # 文字枠が重なっていると行の持ち主を決められない
        if r['s'] > len(pages):
            continue
        # pdftotext は1行の中の広い空き（「▼　▼　▼」等）で行を分けるので、高さの近い行は1行に数える
        ys = sorted(cy for cx, cy in pages[r['s'] - 1] if box[0] <= cx <= box[2] and box[1] <= cy <= box[3])
        n, last = 0, -1e9
        for cy in ys:
            if cy - last > r['fs'] * 0.6:
                n += 1
                last = cy
        if n and n != r['lines']:
            el = soup.find(attrs={'data-mid': mid})
            lab = re.sub(r'\s+', ' ', el.get_text() if el else '').strip()[:24]
            out.append((r['s'], lab, r['lines'], n))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description='ブラウザの描画結果を測り、data属性・変換側との食い違いを出す')
    ap.add_argument('html')
    ap.add_argument('--json', help='実測値をJSONで保存する')
    ap.add_argument('--max', type=int, default=40, help='明細を何行まで出すか')
    ap.add_argument('--lines', action='store_true',
                    help='PPTXにしてLibreOfficeで描き、行数がブラウザと同じか比べる（改行位置のずれ）')
    a = ap.parse_args()
    path = os.path.abspath(a.html)
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    tagged, n = tag_html(raw)
    try:
        M = measure_tagged(path, tagged)
    except RuntimeError as e:
        print('実測できなかった（検査を飛ばす）: %s' % e)
        return 0
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(M, f, ensure_ascii=False)
    cnt, rows = compare(path, M, tagged)
    lines = sum(r.get('lines', 0) for r in M['els'].values())
    print('%s: %d枚・要素%d・文字枠%d・行%d' % (os.path.basename(path), len(M['slides']), n, cnt['tb'], lines))
    print('  位置ずれ=%(geom)d  文字の並び違い=%(text)d  太字=%(bold)d  大きさ=%(size)d  色=%(color)d  '
          'あふれ=%(overflow)d  PPTXに出ない文字=%(lost)d  コントラスト不足=%(contrast)d' % cnt)
    for s, kind, lab, msg in rows[:a.max]:
        if s:
            print('  %d枚目 [%s] 「%s」 %s' % (s, kind, lab, msg))
        else:
            print('  [%s] %s %s' % (kind, lab, msg))
    if len(rows) > a.max:
        print('  …ほか%d件（--max で増やせる）' % (len(rows) - a.max))
    if a.lines:
        diff = pptx_line_check(path, M, tagged)
        checked = sum(1 for r in M['els'].values() if r.get('top') and r.get('runs'))
        print('  行数（ブラウザ→PPTX）が違う文字枠=%d（スライド直下の文字枠%d個のうち重ならないもの）' % (len(diff), checked))
        for s, lab, b, p in diff[:a.max]:
            print('  %d枚目 [lines] 「%s」 ブラウザ%d行→PPTX%d行' % (s, lab, b, p))
    return 0


if __name__ == '__main__':
    sys.exit(main())
