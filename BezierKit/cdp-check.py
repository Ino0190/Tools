# BezierKit ヘッドレス検証（CDP直叩き・CadKitのcdp-run.pyと同流儀）
#   python3 cdp-check.py                          … 自己テスト（合成画像トレース・曲線フィット・レイヤー統合）
#   python3 cdp-check.py trace 画像 出力.svg      … 画像をトレースしてSVG保存（環境変数 COLORS/TOL/MINPX/RES/FIT）
#   python3 cdp-check.py halftone 画像 出力.svg   … 画像を網点化してSVG＋目視用PNG保存（環境変数 PITCH/ANGLE/SHAPE/MODE/INK/SCALE/GAIN/INVERT/PAPER）
#   python3 cdp-check.py verify 入力.ai|.pdf|.svg|fixture [--ppt] [--crop=x,y,w;x,y,w] … 通し確認を1コマンドで
#       （読み込み→PPTX→見比べ画像 BezierKit/_check/<名前>/compare.png→--pptでPowerPoint実機）。
#       確認はこれで回す（シェルで && やパイプ・heredoc・環境変数の前置きを組むと承認ボタンが出る）
#   python3 cdp-check.py illust 入力.svg … Kiroが描いたPPTX向けイラストの検査（使わない要素・色・BezierKitで開いて落ちる図形・PPTXの「出ないもの」）＋見比べ画像。ILLUST_OK／NG
#   python3 cdp-check.py shot <名前> … 画面のスクリーンショット（SHOT_SETUPS）。_check/shot-<名前>.png
#   python3 cdp-check.py pdf 入力.ai|入力.pdf|fixture 出力.png … AI／PDF読み込み＋見比べ用PNG（.bk.png=BezierKit／.ref.png=pdf.js描画。正解に近いのは sips -s format png で出すmacOSの描画）
#   python3 cdp-check.py pptx 入力.svg|fixture 出力.pptx … PPTX書き出し＋見比べ用PNG（.bk.png=BezierKit描画／.lo.png=LibreOfficeでPPTX描画。環境変数 TEXTBOX=false で文字を形に）
import base64, json, os, re, socket, struct, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

PORT = int(os.environ.get("CDP_PORT", "9235"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = "file://" + os.path.join(HERE, "index.html")

def exact(sock, size):
    data = b""
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part: raise EOFError("closed")
        data += part
    return data

def send_frame(sock, obj):
    data = json.dumps(obj).encode()
    mask = os.urandom(4); size = len(data)
    if size < 126: head = bytes([0x81, 0x80 | size])
    elif size < 65536: head = bytes([0x81, 0xFE]) + struct.pack("!H", size)
    else: head = bytes([0x81, 0xFF]) + struct.pack("!Q", size)
    sock.sendall(head + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))

def recv_frame(sock):
    first, second = exact(sock, 2)
    opcode, size = first & 0x0F, second & 0x7F
    if size == 126: size = struct.unpack("!H", exact(sock, 2))[0]
    elif size == 127: size = struct.unpack("!Q", exact(sock, 8))[0]
    if second & 0x80:
        mask = exact(sock, 4)
        return opcode, bytes(v ^ mask[i % 4] for i, v in enumerate(exact(sock, size)))
    return opcode, exact(sock, size)

def connect():
    deadline = time.time() + 20
    while True:
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            ws = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
            break
        except Exception:
            if time.time() > deadline: raise
            time.sleep(0.3)
    p = urlparse(ws)
    sock = socket.create_connection((p.hostname, p.port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET {p.path} HTTP/1.1\r\nHost: {p.netloc}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                  f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp: resp += sock.recv(4096)
    if b" 101 " not in resp.split(b"\r\n", 1)[0]: raise RuntimeError(resp.decode(errors="ignore"))
    return sock

msg_id = 0
def call(sock, method, params=None, timeout=180):
    global msg_id
    msg_id += 1; mid = msg_id
    send_frame(sock, {"id": mid, "method": method, "params": params or {}})
    deadline = time.time() + timeout
    while time.time() < deadline:
        opcode, raw = recv_frame(sock)
        if opcode != 1: continue
        m = json.loads(raw)
        if m.get("id") == mid: return m.get("result", {})
    raise TimeoutError(method)

def ev(sock, expr, await_promise=False, timeout=180):
    r = call(sock, "Runtime.evaluate",
             {"expression": expr, "returnByValue": True, "awaitPromise": await_promise}, timeout)
    res = r.get("result", {})
    if "exceptionDetails" in r:
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
    return res.get("value")

def boot(page=PAGE, ready="typeof runTrace==='function' && typeof fitLoopNodes==='function' && typeof halftoneRun==='function'"):
    # 前回異常終了の残骸が同じポートを握っていると古いページに繋がってしまう→先に掃除
    subprocess.run(["pkill", "-f", "bk-check-profile"], capture_output=True)
    time.sleep(0.5)
    chrome = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--mute-audio",
        "--user-data-dir=/tmp/bk-check-profile", "--allow-file-access-from-files",
        "--window-size=1500,1000", "--hide-scrollbars", page,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = connect(); sock.settimeout(300)
    call(sock, "Runtime.enable"); call(sock, "Page.enable")
    for _ in range(100):
        if ev(sock, ready): break
        time.sleep(0.2)
    return chrome, sock

def load_image(sock, url):
    ev(sock, f"""(async()=>{{
      const r=await fetch('{url}');
      const b=await r.blob();
      loadTraceImage(new File([b],'input.img',{{type:b.type||'image/png'}}));
      return true;
    }})()""", await_promise=True)
    for _ in range(150):
        if ev(sock, "!document.getElementById('traceRun').disabled"): return
        time.sleep(0.2)
    raise RuntimeError("画像読み込みが完了しない: " + str(ev(sock, "document.getElementById('traceInfo').textContent")))

def do_trace(sock, colors, tol, minpx, res, fit, mode="regions", thresh=50, corner="normal"):
    return ev(sock, f"""(()=>{{
      document.getElementById('traceColors').value='{colors}';
      document.getElementById('traceTol').value='{tol}';
      document.getElementById('traceMin').value='{minpx}';
      document.getElementById('traceRes').value='{res}';
      document.getElementById('traceFit').checked={'true' if fit else 'false'};
      document.getElementById('traceMode').value='{mode}';
      document.getElementById('traceThresh').value='{thresh}';
      document.getElementById('traceCorner').value='{corner}';
      runTrace();
      return document.getElementById('traceInfo').textContent;
    }})()""", timeout=600)

def do_halftone(sock, pitch=10, angle=45, shape="circle", mode="am", ink="mono",
                scale=100, gain=100, invert=False, keep=False, paper=True):
    return ev(sock, f"""(()=>{{
      const g=id=>document.getElementById(id);
      g('htPitch').value='{pitch}';g('htAngle').value='{angle}';g('htShape').value='{shape}';
      g('htMode').value='{mode}';g('htInk').value='{ink}';g('htScale').value='{scale}';
      g('htGain').value='{gain}';g('htInvert').checked={'true' if invert else 'false'};
      g('htPaper').checked={'true' if paper else 'false'};
      g('htKeep').checked={'true' if keep else 'false'};
      halftoneRun();
      return g('htInfo').textContent;
    }})()""", timeout=600)

# 網点の測定: 最後に生成されたパスのドット（subpaths）を中心x順に並べ、濃い側／薄い側の平均半径を出す
HT_DOTS_JS = """JSON.stringify((()=>{
  const p=state.paths[state.paths.length-1],parts=p.subpaths||[p];
  const dots=parts.map(s=>{const xs=s.nodes.map(n=>n.x),ys=s.nodes.map(n=>n.y);
    return{x:(Math.min(...xs)+Math.max(...xs))/2,r:(Math.max(...xs)-Math.min(...xs))/2,
      h:(Math.max(...ys)-Math.min(...ys))/2};});
  dots.sort((a,b)=>a.x-b.x);
  const q=Math.max(1,Math.floor(dots.length/4)),avg=a=>a.reduce((s,d)=>s+d.r,0)/a.length;
  const rs=dots.map(d=>d.r);
  return{paths:state.paths.length,dots:dots.length,fillRule:p.fillRule,fill:p.fill,stroke:p.stroke,
    layers:state.layers.filter(L=>L.name.startsWith('網点')).length,
    darkR:avg(dots.slice(0,q)),lightR:avg(dots.slice(-q)),
    rMin:Math.min(...rs),rMax:Math.max(...rs)};
})())"""

STATS_JS = """JSON.stringify((()=>{
  let nodes=0,smooth=0;
  for(const p of state.paths){
    for(const part of (p.subpaths||[p])){
      if(!part.nodes)continue;
      for(const n of part.nodes){
        nodes++;
        if(n.inX!==n.x||n.inY!==n.y||n.outX!==n.x||n.outY!==n.y)smooth++;
      }
    }
  }
  return {paths:state.paths.length,layers:state.layers.length,nodes,smooth};
})())"""

# PPTX書き出しの見本: 単色＋破線＋不透明度／直線グラデ／穴あき(evenodd)／重なる点(nonzero)／矢印付きの曲線／
# 幅ツール／うねり／マスク／グループ／文字（2行）／非表示レイヤー。SPEC.md 4章の表を一通り通す
PPTX_FIXTURE_JS = r"""(()=>{
  state.paths=[];state.dims=[];state.animation=null;state.artboards=null;state.swatches=null;
  state.layers=[{id:1,name:'背景',visible:true},{id:2,name:'前景',visible:true},{id:3,name:'下書き',visible:false}];state.activeLayer=1;
  applyArtboard(1280,720);
  const R=(x,y,w,h)=>[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)];
  const C=(cx,cy,r)=>{const k=.5523*r;return[{x:cx+r,y:cy,inX:cx+r,inY:cy-k,outX:cx+r,outY:cy+k},{x:cx,y:cy+r,inX:cx+k,inY:cy+r,outX:cx-k,outY:cy+r},
    {x:cx-r,y:cy,inX:cx-r,inY:cy+k,outX:cx-r,outY:cy-k},{x:cx,y:cy-r,inX:cx-k,inY:cy-r,outX:cx+k,outY:cy-r}];};
  const add=o=>{o.id=nextId++;o.layerId=o.layerId||1;state.paths.push(o);return o;};
  add({nodes:R(40,40,1200,640),closed:true,fill:'#eef3f8',stroke:'#21537f',width:4,dash:'12 6',opacity:.9});
  add({nodes:C(240,220,120),closed:true,fill:'#21537f',stroke:'none',width:1,gradient:{c1:'#21537f',c2:'#9fc0dd',angle:90},shadow:{dist:12,dir:45,blur:16,color:'#121212',alpha:.4}});
  add({nodes:C(760,610,60),closed:true,fill:'#c62828',stroke:'none',width:1,gradient:{type:'radial',c1:'#c62828',mid:'#ffffff',c2:'#21537f',angle:0}});
  add({subpaths:[{closed:true,nodes:C(560,220,120)},{closed:true,nodes:C(560,220,60)}],fill:'#c62828',stroke:'#121212',width:3,fillSw:1});
  state.swatches=[{id:1,name:'赤',color:'#c62828'}];
  add({subpaths:[{closed:true,nodes:C(840,200,50)},{closed:true,nodes:C(900,200,50)},{closed:true,nodes:C(870,250,50)}],fill:'#162a42',stroke:'none',width:1,fillRule:'nonzero'});
  add({nodes:[node(120,480),{x:320,y:380,inX:260,inY:380,outX:380,outY:380},node(520,480)],closed:false,fill:'none',stroke:'#121212',width:6,arrow:'both',arrowType:'stealth',arrowSize:'med'});
  add({nodes:[node(620,420),node(1000,420)],closed:false,fill:'none',stroke:'#21537f',width:10,widthPts:[{part:0,u:.5,w:40}]});
  add({nodes:[node(620,520),node(1000,520)],closed:false,fill:'none',stroke:'#c62828',width:4,zig:{kind:'smooth',amp:12,len:30}});
  const tgt=add({nodes:R(1040,380,200,200),closed:true,fill:'#10b981',stroke:'#121212',width:8,layerId:2});
  const m=add({nodes:C(1140,480,115),closed:true,fill:'none',stroke:'none',width:1,clipMask:true,layerId:2});tgt.clipBy=m.id;
  add({nodes:R(1040,100,80,80),closed:true,fill:'#9fc0dd',stroke:'none',width:1,layerId:2,groupId:'g1',glow:{r:10,color:'#ffd54f',alpha:.8}});
  add({nodes:R(1140,100,80,80),closed:true,fill:'#718096',stroke:'none',width:1,layerId:2,groupId:'g1',softEdge:12});
  add({type:'text',text:'見出しの文字\n二行目',x:120,y:620,size:40,lineHeight:1.3,fontKey:'noto-sans-b',fill:'#121212',stroke:'none',width:1,layerId:2,
    cmds:[{type:'M',x:120,y:590},{type:'L',x:360,y:590},{type:'L',x:360,y:672},{type:'L',x:120,y:672},{type:'Z'}]});
  add({nodes:R(300,300,50,50),closed:true,fill:'#000000',stroke:'none',width:1,layerId:3});
  state.selectedPaths=[];state.selectedPath=null;render();return state.paths.length;
})()"""

PPTX_BLOB_JS = r"""(async()=>{const r=buildPptxBlob({textBox:%s,selectionOnly:false});
  const buf=new Uint8Array(await r.blob.arrayBuffer());let s='';for(let i=0;i<buf.length;i+=32768)s+=String.fromCharCode.apply(null,buf.subarray(i,i+32768));
  return JSON.stringify({b64:btoa(s),slides:r.slides,stats:{shape:r.stats.shape.length,baked:r.stats.baked.length,text:r.stats.text.length,lost:r.stats.lost.length}});})()"""

def make_test_pdf():
    """AI／PDF読み込みの見本（手書きのPDF・600×400pt）: レイヤー2つ（OCG）・穴あき(f*)・破線の曲線・
    四角で切り抜いた直線グラデ(sh)・円で切り抜いた塗り（マスクになる）・不透明度50%・文字1行"""
    content = b"""/OC /oc1 BDC
q 0.776 0.157 0.157 rg 300 50 m 500 50 l 500 250 l 300 250 l h 350 100 m 450 100 l 450 200 l 350 200 l h f* Q
q 0 0 0 RG 4 w [10 5] 0 d 1 J 1 j 40 380 m 100 300 180 300 240 380 c S Q
q 20 230 200 150 re W n /Sh1 sh Q
EMC
/OC /oc2 BDC
q 560 330 m 560 352 542 370 520 370 c 498 370 480 352 480 330 c 480 308 498 290 520 290 c 542 290 560 308 560 330 c h W n
0.063 0.725 0.506 rg 470 280 70 100 re f Q
q /GS1 gs 0.129 0.325 0.498 rg 100 150 m 100 177.6 77.6 200 50 200 c 22.4 200 0 177.6 0 150 c 0 122.4 22.4 100 50 100 c 77.6 100 100 122.4 100 150 c f Q
BT /F1 40 Tf 1 0 0 1 300 300 Tm 0.07 0.07 0.07 rg (Hello World) Tj ET
EMC
"""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [7 0 R 8 0 R] /D << /Order [7 0 R 8 0 R] >> >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> "
        b"/Shading << /Sh1 6 0 R >> /ExtGState << /GS1 << /ca 0.5 >> >> /Properties << /oc1 7 0 R /oc2 8 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 380 0 230] /Extend [true true] "
        b"/Function << /FunctionType 2 /Domain [0 1] /C0 [0.129 0.325 0.498] /C1 [0.624 0.753 0.867] /N 1 >> >>",
        b"<< /Type /OCG /Name (Back) >>",
        b"<< /Type /OCG /Name (Front) >>",
    ]
    out = bytearray(b"%PDF-1.6\n"); offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % v for v in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)

PDF_IMPORT_JS = r"""(async()=>{const bin=Uint8Array.from(atob(%s),c=>c.charCodeAt(0));
  const r=await importPdfVector(new File([bin],%s,{type:'application/pdf'}),1);
  return JSON.stringify({r,status:document.getElementById('status').textContent});})()"""

def pptx_shapes(path):
    """python-pptxで開いて、図形を入れ子まで数える（開けなければ例外）"""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation(path)
    out = {"w": prs.slide_width, "h": prs.slide_height, "slides": len(prs.slides), "groups": [], "free": 0, "text": [], "names": []}
    def walk(shapes):
        for sh in shapes:
            out["names"].append(sh.name)
            if sh.shape_type == 6:  # GROUP
                out["groups"].append(sh.name); walk(sh.shapes)
            elif sh.has_text_frame and sh.text_frame.text.strip():
                out["text"].append(sh.text_frame.text)
            else:
                out["free"] += 1
    for sl in prs.slides:
        walk(sl.shapes)
    return out

def grad_pdf(out_pdf):
    # 40%の分岐点がある放射グラデ1枚を PDF 書き出し（目視用）
    chrome, sock = boot()
    try:
        txt = ev(sock, r"""(()=>{state.paths=[];const L=state.layers[0].id;
          const p={id:nextId++,layerId:L,closed:true,fill:'#ffd54f',stroke:'none',width:1,
            nodes:[node(160,160),node(640,160),node(640,600),node(160,600)],
            gradient:{type:'radial',c1:'#ffd54f',c2:'#1e40af',angle:0,cx:.5,cy:.5,spread:100,
              stops:[[0,'#ffd54f',1],[.5,'#00c853',.4],[1,'#1e40af',1]]}};
          state.paths.push(p);render();return buildPdf(pptxOptions()).text;})()""")
    finally:
        chrome.terminate()
    with open(out_pdf, "wb") as f:
        f.write(bytes(ord(c) & 255 for c in txt))
    print("GRAD_PDF_OK", out_pdf)
    return 0


def run_only(name):
    # 波の新テストだけを回す（起動・片付けは selftest と同じ。全回帰は Kiro が別で流す）
    fails = []
    chrome, sock = boot()
    ev(sock, "state.paths=[];state.selectedPath=null;state.selectedPaths=[];render();true")
    fn = {"wave11": wave11_checks, "wave12": wave12_checks, "wave13": wave13_checks, "wave14": wave14_checks, "wave15": wave15_checks, "wave16": wave16_checks, "wave17": wave17_checks}.get(name)
    if not fn:
        chrome.terminate()
        print(f"BEZIERKIT_FAIL\nunknown only target: {name}")
        return 1
    try:
        fn(sock, fails)
    finally:
        chrome.terminate()
    print(("BEZIERKIT_FAIL\n" + "\n".join(fails)) if fails else f"BEZIERKIT_OK ({name})")
    return 1 if fails else 0


def wave11_checks(sock, fails):
    # 波11 #1 グラデの多色（色ごとに位置と不透明度）
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={};
      const sq=(id,grad)=>({id,nodes:[node(100,100),node(300,100),node(300,300),node(100,300)],closed:true,layerId:state.activeLayer,fill:grad.c1,gradient:JSON.parse(JSON.stringify(grad))});
      // A) データと描画 + 帯を押して50%に分岐点
      let p=sq(1,{c1:'#ff0000',c2:'#0000ff',angle:0});state.paths=[p];state.selectedPaths=[1];state.selectedPath=1;drawGradStops=null;_gradBarPathId=null;
      let st=gradEditStops(p.gradient);R.startLen=st.length;
      const mid=gradColorAt(st,.5);st.push([.5,mid[0],mid[1]]);writeGradStops(p.gradient,st);
      R.afterAddLen=p.gradient.stops.length;R.midColor=p.gradient.stops[1][1];R.midPos=p.gradient.stops[1][0];
      // その色を #00ff00・不透明40 → SVG stop-opacity .4
      st=gradEditStops(p.gradient);st[1][1]='#00ff00';st[1][2]=.4;writeGradStops(p.gradient,st);render();
      let svg=buildPathsSvg(state.paths).text;R.stopCount=(svg.match(/<stop/g)||[]).length;R.hasOp4=/stop-opacity="0?\.4"/.test(svg);
      // B) ドラッグで70%
      st=gradEditStops(p.gradient);st[1][0]=.7;writeGradStops(p.gradient,st);R.posMoved=gradEditStops(p.gradient).find(s=>Math.abs(s[0]-.7)<1e-6)?.7:null;
      // C) 下へ引き離す→消える（3→2）。2からは消えない
      st=gradEditStops(p.gradient);st.splice(1,1);writeGradStops(p.gradient,st);R.afterDel=p.gradient.stops.length;
      st=gradEditStops(p.gradient);st.splice(0,1);writeGradStops(p.gradient,st);R.minTwo=p.gradient.stops.length;
      // D) 反転
      p.gradient={c1:'#ff0000',c2:'#0000ff',angle:0};st=gradEditStops(p.gradient);const rev=st.map(s=>[+(1-s[0]).toFixed(6),s[1],s[2]]);writeGradStops(p.gradient,rev);
      R.revFirst=p.gradient.stops[0][1];R.revLast=p.gradient.stops[p.gradient.stops.length-1][1];
      // E) 4色・1つ不透明50 ×図形不透明80 → PPTX gs 4つ・alpha .4
      let p2=sq(2,{c1:'#111111',c2:'#444444',angle:0});p2.opacity=.8;p2.gradient.stops=[[0,'#111111',1],[.33,'#222222',.5],[.66,'#333333',1],[1,'#444444',1]];p2.gradient.c2='#444444';
      state.paths=[p2];state.selectedPaths=[2];state.selectedPath=2;
      const pp=pptxPaint(p2);R.pptxLen=pp.stops.length;const g2=pp.stops.find(s=>Math.abs(s[0]-.33)<1e-6);R.pptxAlpha=g2?+g2[2].toFixed(3):null;
      // F) 保存→開き直しで stops が残る
      const snap=snapshot();state.paths=[];render();restore(snap);const q=pathById(2);R.loadLen=q&&q.gradient.stops?q.gradient.stops.length:0;R.loadAlpha=q&&q.gradient.stops?q.gradient.stops[1][2]:null;
      // G) 古いデータ c1/mid/c2 が3色で開く
      let p3=sq(3,{c1:'#ff0000',mid:'#00ff00',c2:'#0000ff',angle:0});state.paths=[p3];R.oldStops=gradStops(p3.gradient).length;svg=buildPathsSvg(state.paths).text;R.oldSvgStops=(svg.match(/<stop/g)||[]).length;
      // H) 何も選ばず4色→次に描く図形
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;$('fillType').value='grad';
      drawGradStops=[[0,'#111111',1],[.33,'#222222',1],[.66,'#333333',1],[1,'#444444',1]];
      const ds=currentDrawStyle(true);R.drawLen=ds.gradient&&ds.gradient.stops?ds.gradient.stops.length:0;
      // I) 再配色に4色が並ぶ
      let p4=sq(4,{c1:'#ff0000',c2:'#0000ff',angle:0});p4.stroke='#000000';p4.gradient.stops=[[0,'#aa0000',1],[.33,'#bb0000',1],[.66,'#cc0000',1],[1,'#dd0000',1]];p4.gradient.c1='#aa0000';p4.gradient.c2='#dd0000';
      state.paths=[p4];state.selectedPaths=[];state.selectedPath=null;recolorScope=null;buildRecolorRows();
      const rows=[...document.getElementById('recolorList').querySelectorAll('.rrow .cnt')].map(e=>e.textContent);
      R.recolorHas=rows.some(t=>t.includes('#aa0000'))&&rows.some(t=>t.includes('#dd0000'))&&rows.some(t=>t.includes('#bb0000'));
      // J) Undo（欄は change で1段）
      let p5=sq(5,{c1:'#ff0000',c2:'#0000ff',angle:0});state.paths=[p5];state.selectedPaths=[5];state.selectedPath=5;_gradBarPathId=null;
      pushUndo();st=gradEditStops(p5.gradient);st.push([.5,'#00ff00',1]);writeGradStops(p5.gradient,st);R.beforeUndo=p5.gradient.stops.length;
      undo();const u=pathById(5);R.afterUndo=u.gradient.stops?u.gradient.stops.length:2;
      // 市松（透明）プレビュー要素がある
      R.hasBar=!!document.getElementById('gradBar')&&!!document.getElementById('gradStopTrack');
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;drawGradStops=null;render();
      return R;
    })())"""))
    def bad(k, cond, msg):
        if not cond:
            fails.append(f"WAVE11-{k}: {msg}: {r.get(k)}")
    bad("A-data", r["startLen"] == 2 and r["afterAddLen"] == 3 and r["midColor"].lower() == "#800080" and abs(r["midPos"] - .5) < 1e-6,
        "直線グラデに50%の分岐点→3つ・間の色#800080のはず")
    bad("A-svg", r["stopCount"] == 3 and r["hasOp4"], "SVGにstopが3つ・#00ff00の分岐点にstop-opacity .4のはず")
    bad("B-pos", r["posMoved"] == .7, "位置を70%にしたら0.7のはず")
    bad("C-del", r["afterDel"] == 2 and r["minTwo"] == 2, "3→2に消え、2からは消えない（最少2）はず")
    bad("D-rev", r["revFirst"].lower() == "#0000ff" and r["revLast"].lower() == "#ff0000", "反転で端の色が入れ替わるはず")
    bad("E-pptx", r["pptxLen"] == 4 and r["pptxAlpha"] == .4, "PPTXのgsが4つ・不透明50%×図形80%=alpha .4のはず")
    bad("F-load", r["loadLen"] == 4 and r["loadAlpha"] == .5, "保存→開き直しでstops(4つ・不透明.5)が残るはず")
    bad("G-old", r["oldStops"] == 3 and r["oldSvgStops"] == 3, "古いc1/mid/c2が3色で開くはず")
    bad("H-draw", r["drawLen"] == 4, "何も選ばず4色にして描く図形が4色stopsのはず")
    bad("I-recolor", r["recolorHas"], "再配色に全分岐点の色が並ぶはず")
    bad("J-undo", r["beforeUndo"] == 3 and r["afterUndo"] == 2, "分岐点追加→Undoで元の2つに戻るはず")
    bad("UI", r["hasBar"], "帯のDOM(#gradBar/#gradStopTrack)があるはず")

    # 波11 続き: PDF ソフトマスク・16進欄の幅
    r2 = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={};const L=state.layers[0].id;
      const mk=(stops)=>({id:nextId++,layerId:L,closed:true,fill:stops[0][1],stroke:'none',width:1,
        nodes:[node(200,200),node(600,200),node(600,560),node(200,560)],
        gradient:{c1:stops[0][1],c2:stops[stops.length-1][1],angle:0,stops:stops.map(s=>[s[0],s[1],s[2]])}});
      // 40%の分岐点がある図形 → /SMask が入る
      state.paths=[mk([[0,'#ffd54f',1],[.5,'#00c853',.4],[1,'#1e40af',1]])];state.selectedPaths=[];state.selectedPath=null;render();
      let t=buildPdf(pptxOptions()).text;R.smaskYes=t.includes('/SMask')&&t.includes('/Luminosity');
      // 全部不透明の図形 → /SMask は入らない
      state.paths=[mk([[0,'#ffd54f',1],[.5,'#00c853',1],[1,'#1e40af',1]])];render();
      t=buildPdf(pptxOptions()).text;R.smaskNo=!t.includes('/SMask');
      // 16進の欄の幅: #00ff00（7文字）が切れない
      const p=mk([[0,'#ff0000',1],[1,'#00ff00',1]]);p.gradient.type='radial';state.paths=[p];state.selectedPaths=[p.id];state.selectedPath=p.id;_gradBarPathId=null;
      $('fillType').value='radial';if(typeof revealPanel==='function')revealPanel(document.getElementById('gradBar'));updateGradRow();renderGradBar();gradStopSel=1;renderGradBar();
      const h=document.getElementById('gradStopHex');R.hexVal=h.value;R.hexFit=h.scrollWidth<=h.clientWidth+1;R.posFit=(()=>{const e=document.getElementById('gradStopPos');return e.scrollWidth<=e.clientWidth+1;})();
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();return R;
    })())"""))
    if not r2["smaskYes"]:
        fails.append(f"WAVE11-PDF-smask: 40%の分岐点がある図形のPDFに/SMask /Luminosityが入るはず: {r2}")
    if not r2["smaskNo"]:
        fails.append(f"WAVE11-PDF-nosmask: 全部不透明の図形には/SMaskが入らないはず: {r2}")
    if not (r2["hexVal"].lower() == "#00ff00" and r2["hexFit"] and r2["posFit"]):
        fails.append(f"WAVE11-HEXWIDTH: 16進の欄で#00ff00（7文字）が切れないはず（scrollWidth<=clientWidth）: {r2}")


def wave12_checks(sock, fails):
    # 波12 #2 連結(J1)
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={},L=state.layers[0].id;
      const line=(id,pts,extra={})=>({id,nodes:pts.map(p=>node(p[0],p[1])),closed:false,layerId:L,fill:'none',stroke:'#000000',width:1,...extra});
      // a) 端が2px以内の2本→1本・溶接で点数=5
      state.paths=[line(1,[[100,100],[200,100],[300,101]]),line(2,[[301,100],[400,100],[500,100]])];
      state.selectedPaths=[1,2];state.selectedPath=1;state.selectedPart=0;joinOpenPaths();
      R.weldLen=state.paths.length;R.weldNodes=state.paths[0]&&!state.paths[0].closed?state.paths[0].nodes.length:-1;
      // b) 離れた2本(各3点)→点数=和(6)・溶接なし
      state.paths=[line(1,[[100,100],[150,100],[200,100]]),line(2,[[400,100],[500,100],[600,100]])];
      state.selectedPaths=[1,2];state.selectedPath=1;joinOpenPaths();
      R.apartLen=state.paths.length;R.apartNodes=state.paths[0]?state.paths[0].nodes.length:-1;R.apartClosed=!!state.paths[0].closed;
      // c) 1本→閉じる
      state.paths=[line(1,[[100,100],[300,100],[300,300]])];state.selectedPaths=[1];state.selectedPath=1;joinOpenPaths();
      R.closed=!!state.paths[0].closed;
      // d) 見た目=最前面(idx大=stroke赤・太さ5)を継承
      state.paths=[line(1,[[100,100],[200,100]],{stroke:'#000000',width:1}),line(2,[[201,100],[300,100]],{stroke:'#ff0000',width:5})];
      state.selectedPaths=[1,2];state.selectedPath=1;joinOpenPaths();
      R.inheritStroke=(state.paths[0].stroke||'').toLowerCase();R.inheritWidth=state.paths[0].width;
      // e) 形の元(shape)が外れる
      state.paths=[line(1,[[100,100],[200,100]],{shape:{type:'polygon',sides:3,cx:1,cy:1,r:1,rot:0}}),line(2,[[201,100],[300,100]])];
      state.selectedPaths=[1,2];state.selectedPath=1;joinOpenPaths();
      R.shapeGone=state.paths[0].shape===undefined;
      // f) 閉じた図形を含む選択→変化なし・ステータス
      state.paths=[line(1,[[100,100],[200,100]]),{id:2,nodes:[node(300,300),node(400,300),node(400,400)],closed:true,layerId:L,fill:'#0000ff'}];
      state.selectedPaths=[1,2];state.selectedPath=1;$('status').textContent='';joinOpenPaths();
      R.rejectLen=state.paths.length;R.rejectMsg=$('status').textContent.includes('閉じた図形');
      // g) Undo1回
      state.paths=[line(1,[[100,100],[200,100]]),line(2,[[400,100],[500,100]])];render();
      state.selectedPaths=[1,2];state.selectedPath=1;joinOpenPaths();R.beforeUndo=state.paths.length;
      undo();R.afterUndo=state.paths.length;
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return R;
    })())"""))
    def badJ(cond, msg):
        if not cond:
            fails.append(f"WAVE12-J1 {msg}: {r}")
    badJ(r["weldLen"] == 1 and r["weldNodes"] == 5, "端が2px以内の2本→1本・溶接で点5")
    badJ(r["apartLen"] == 1 and r["apartNodes"] == 6 and not r["apartClosed"], "離れた2本→直線連結で点=和6・閉じない")
    badJ(r["closed"] is True, "1本選んで連結→閉じる")
    badJ(r["inheritStroke"] == "#ff0000" and r["inheritWidth"] == 5, "見た目=最前面の線を継承")
    badJ(r["shapeGone"] is True, "連結で形の元(shape)が外れる")
    badJ(r["rejectLen"] == 2 and r["rejectMsg"], "閉じた図形を含む選択は変化なし＋ステータス")
    badJ(r["beforeUndo"] == 1 and r["afterUndo"] == 2, "連結はUndo1回で元の2本")

    # 波12 #3 文字の揃え(X1)
    rx = json.loads(ev(sock, r"""(async()=>{
      const R={},L=state.layers[0].id,font=await ensureFont();
      const mk=(text,align,vertical,x,y)=>{const t={id:nextId++,type:'text',text,x,y,size:80,letterSpacing:0,lineHeight:1.3,vertical:!!vertical,align,fontKey:currentFontKey,fill:'#000000',stroke:'none',width:1,layerId:L};t.cmds=textCmds(font,t);return t;};
      // 横: 中央/右のオフセットが行幅から正しく出る（side bearing非依存で検証）
      const s=mk('abcd','start',false,500,300),c=mk('abcd','center',false,500,300),e=mk('abcd','end',false,500,300);
      const lineW=[...'abcd'].reduce((w,ch)=>w+font.getAdvanceWidth(ch,80),0);
      R.centerOff=(bboxOfPath(s).l-bboxOfPath(c).l)-lineW/2;
      R.endOff=(bboxOfPath(s).l-bboxOfPath(e).l)-lineW;
      // 多行: 2行(長さ違い)中央→各行の左端が行幅の半分だけ戻る＝中心がそろう
      const m1=mk('ab','center',false,500,300),m2=mk('abcd','center',false,500,300);
      const w1=[...'ab'].reduce((w,ch)=>w+font.getAdvanceWidth(ch,80),0),w2=lineW;
      R.rowCenter=Math.abs(((bboxOfPath(m1).l+w1/2)-(bboxOfPath(m2).l+w2/2)));
      // 縦: 中央=上から colLen/2、下=colLen だけ上に寄る（colLen=3*80=240）
      const v0=mk('あいう','start',true,500,200),vc=mk('あいう','center',true,500,200),ve=mk('あいう','end',true,500,200);
      R.vCenterOff=(bboxOfPath(v0).t-bboxOfPath(vc).t)-120;
      R.vEndOff=(bboxOfPath(v0).t-bboxOfPath(ve).t)-240;
      // PPTX: 横 pPr algn ctr/r、縦 bodyPr anchor ctr
      state.paths=[mk('abc','center',false,500,300)];state.selectedPaths=[];state.selectedPath=null;
      const sl=a=>Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'];
      R.pptxCtr=sl().includes('algn="ctr"');
      state.paths=[mk('abc','end',false,500,300)];R.pptxR=sl().includes('algn="r"');
      state.paths=[mk('あいう','center',true,500,200)];R.pptxAnchor=sl().includes('anchor="ctr"');
      // 保存open で align が残る / sanitizeText: 不正な値は外れる(start扱い)
      const keep=mk('abc','center',false,500,300);state.paths=[keep];const snap=snapshot();state.paths=[];restore(snap);R.loadAlign=(pathById(keep.id)||{}).align;
      const bad=mk('abc','center',false,500,300);bad.align='bogus';state.paths=[bad];const snap2=snapshot();state.paths=[];restore(snap2);R.sanit=(pathById(bad.id)||{}).align||'start';
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return JSON.stringify(R);
    })()""", await_promise=True))
    def badX(cond, msg):
        if not cond:
            fails.append(f"WAVE12-X1 {msg}: {rx}")
    badX(abs(rx["centerOff"]) < 0.01, "横中央のオフセット=行幅/2")
    badX(abs(rx["endOff"]) < 0.01, "横右のオフセット=行幅")
    badX(abs(rx["rowCenter"]) < 0.01, "多行中央で各行の中心がそろう")
    badX(abs(rx["vCenterOff"]) < 0.01, "縦中央のオフセット=列長/2(120)")
    badX(abs(rx["vEndOff"]) < 0.01, "縦下のオフセット=列長(240)")
    badX(rx["pptxCtr"], "PPTXの横中央で pPr algn=ctr")
    badX(rx["pptxR"], "PPTXの横右で pPr algn=r")
    badX(rx["pptxAnchor"], "PPTXの縦中央で bodyPr anchor=ctr")
    badX(rx["loadAlign"] == "center", "保存→開き直しで align が残る")
    badX(rx["sanit"] == "start", "不正な align は開くとき外れて start 扱い")

    # 波12 2回目 #3 エリア内文字(X2)
    ry = json.loads(ev(sock, r"""(async()=>{
      const R={},L=state.layers[0].id,font=await ensureFont();
      const mkA=(text,boxW,boxH,align,vertical)=>{const t={id:nextId++,type:'text',text,x:200,y:200,size:40,letterSpacing:0,lineHeight:1.3,vertical:!!vertical,align,area:true,boxW,boxH,fontKey:currentFontKey,fill:'#000000',stroke:'none',width:1,layerId:L};t.cmds=textCmds(font,t);return t;};
      const aw=ch=>font.getAdvanceWidth(ch,40),jp='あいうえおかきくけこさしすせそたちつてと';
      R.wrapLines=wrapLines(font,mkA(jp,aw('あ')*5+5,400,'start',false)).length;                       // 枠幅で行が増える
      const wl=wrapLines(font,mkA('あ、いう。え',aw('あ')+3,400,'start',false));R.headOk=wl.every((l,i)=>i===0||!l||'、。'.indexOf(l[0])===-1); // 行頭に、。が来ない
      const we=wrapLines(font,mkA('aaaa bbbb cccc',[...'aaaa '].reduce((s,c)=>s+aw(c),0)+2,400,'start',false));
      R.enWhole=we.length===3&&we.every(l=>['aaaa','bbbb','cccc'].includes(l.trim()));                 // 英語は単語で折り返す
      const tr=mkA(jp,aw('あ')*10,400,'start',false),n1=wrapLines(font,tr).length,sz1=tr.size;tr.boxW=aw('あ')*4;tr.cmds=textCmds(font,tr);
      R.reflow=wrapLines(font,tr).length>n1&&tr.size===sz1;                                             // 枠を狭める→折り返し直し・大きさ不変
      R.overflow=areaOverflow(mkA(jp,aw('あ')*5,40,'start',false));                                      // 入りきらない→overflow
      const bw=300,lineW=[...'abc'].reduce((s,c)=>s+aw(c),0);
      R.centerBox=(bboxOfPath(mkA('abc',bw,200,'center',false)).l-bboxOfPath(mkA('abc',bw,200,'start',false)).l)-((bw-lineW)/2); // 中央=枠の中心
      R.vCols=wrapLines(font,mkA('あいうえおかきく',120,40*2+10,'start',true)).length;                    // 縦書きの折り返し
      state.paths=[mkA('ab\ncd',300,200,'start',false)];state.selectedPaths=[];state.selectedPath=null;
      const sl=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'];
      R.pptxWrap=sl.includes('wrap="square"');R.pptxParas=(sl.match(/<a:p>/g)||[]).length;              // wrap=square・段落はユーザー改行だけ
      const keep=mkA('あいう',150,120,'start',false);state.paths=[keep];const snap=snapshot();state.paths=[];restore(snap);const q=pathById(keep.id)||{};R.loadArea=!!q.area&&q.boxW===150&&q.boxH===120;
      const bad=mkA('x',150,120,'start',false);bad.boxW=-5;state.paths=[bad];const s2=snapshot();state.paths=[];restore(s2);R.sanit=!!(pathById(bad.id)||{}).area;
      const pt={id:nextId++,type:'text',text:'ab',x:100,y:100,size:40,lineHeight:1.3,fontKey:currentFontKey,fill:'#000000',stroke:'none',width:1,layerId:L};pt.cmds=textCmds(font,pt);R.pointNoArea=!pt.area;
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return JSON.stringify(R);
    })()""", await_promise=True))
    def badA(cond, msg):
        if not cond:
            fails.append(f"WAVE12-X2 {msg}: {ry}")
    badA(ry["wrapLines"] > 1, "枠幅で行が増える")
    badA(ry["headOk"], "行頭に「、」「。」が来ない（簡易禁則）")
    badA(ry["enWhole"], "英語は単語の切れ目で折り返す")
    badA(ry["reflow"], "枠を狭めると折り返し直し・文字サイズ不変")
    badA(ry["overflow"], "入りきらないとき overflow フラグ")
    badA(abs(ry["centerBox"]) < 0.01, "中央で各行の中心が枠の中心")
    badA(ry["vCols"] > 1, "縦書きで枠の高さで折り返す")
    badA(ry["pptxWrap"] and ry["pptxParas"] == 2, "PPTX wrap=square・段落はユーザー改行だけ(2)")
    badA(ry["loadArea"], "保存→開き直しで area/boxW/boxH が残る")
    badA(not ry["sanit"], "不正な boxW は開くとき area が外れる")
    badA(ry["pointNoArea"], "点文字は area 無しのまま")


def wave13_checks(sock, fails):
    # 波13 #4 画像を置いて切り抜く（1回目: 配置・表示・選択・移動・変形・複製・Undoの軽さ）
    ev(sock, """(()=>{state.paths=[];state.selectedPath=null;state.selectedPaths=[];render();
      const mk=(type,w,h)=>{const cv=document.createElement('canvas');cv.width=w;cv.height=h;const c=cv.getContext('2d');
        c.fillStyle='#ffffff';c.fillRect(0,0,w,h);c.fillStyle='#d2691e';c.fillRect(w*0.1,h*0.15,w*0.8,h*0.7);
        c.fillStyle='#1e40af';c.beginPath();c.arc(w/2,h/2,Math.min(w,h)*0.25,0,7);c.fill();return cv.toDataURL(type);};
      window.__w13png=mk('image/png',1600,960);window.__w13jpg=mk('image/jpeg',200,120);
      window.__w13snapEmpty=snapshot().length;return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__w13png);const b=await r.blob();
      placeImageFile(new File([b],'w13.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "state.paths.some(p=>p.type==='image')"):
            break
        time.sleep(0.1)
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={};
      // A) state.paths に type:'image' 1つ・imageStore に画素1つ・Undoで消える
      let img=state.paths.find(p=>p.type==='image');
      R.placed=!!img;R.type=img&&img.type;R.pathCount=state.paths.length;R.storeSize=imageStore.size;R.hasImgId=!!img&&img.imgId!=null;
      // 配置サイズ: 長辺がABの60%・中央
      const bb0=bboxOfPath(img);R.longEdge=+Math.max(bb0.r-bb0.l,bb0.b-bb0.t).toFixed(1);R.target=+(Math.max(ART.w,ART.h)*0.6).toFixed(1);
      R.centered=Math.abs((bb0.l+bb0.r)/2-ART.w/2)<1&&Math.abs((bb0.t+bb0.b)/2-ART.h/2)<1;
      // J) Undo の記録に画素が入らない（snapshot に dataURL が無い・置く前後で画素分増えない）
      R.snapNoPixels=snapshot().indexOf('data:image')===-1;
      R.snapLen=snapshot().length;R.snapEmpty=window.__w13snapEmpty;R.dataUrlLen=(window.__w13png||'').length;
      // Undo/redo
      undo();R.afterUndo=state.paths.length;redo();R.afterRedo=state.paths.length;
      img=state.paths.find(p=>p.type==='image');
      // B) 移動・比率固定拡縮・回転90・左右反転。mat/bbox が期待どおり・画素は保持
      const imgId0=img.imgId,w0=img.w0,h0=img.h0;
      state.selectedPaths=[img.id];state.selectedPath=img.id;
      const m0=img.mat.slice();transformSelection(mat(1,0,0,1,50,30));
      R.moved=Math.abs(img.mat[4]-(m0[4]+50))<1e-6&&Math.abs(img.mat[5]-(m0[5]+30))<1e-6;
      const bbA=bboxOfPath(img);scaleSelection(200);const bbB=bboxOfPath(img);
      R.scaled=Math.abs((bbB.r-bbB.l)-2*(bbA.r-bbA.l))<0.5&&Math.abs((bbB.b-bbB.t)-2*(bbA.b-bbA.t))<0.5;
      const wB=bbB.r-bbB.l,hB=bbB.b-bbB.t;rotateSelection(90);const bbR=bboxOfPath(img);
      R.rotated=Math.abs((bbR.r-bbR.l)-hB)<0.5&&Math.abs((bbR.b-bbR.t)-wB)<0.5;
      flip(true);
      R.pixelsKept=img.imgId===imgId0&&img.w0===w0&&img.h0===h0&&imageStore.size===1;
      // C) 複製→imgId 共有（imageStore 1件）・別id
      state.selectedPaths=[img.id];state.selectedPath=img.id;duplicateSelection(0,0);
      const imgs=state.paths.filter(p=>p.type==='image');
      R.dupCount=imgs.length;R.sameImgId=imgs.length===2&&imgs[0].imgId===imgs[1].imgId;R.diffId=imgs.length===2&&imgs[0].id!==imgs[1].id;R.storeAfterDup=imageStore.size;
      // 当たり判定: 置いた画像の DOM 要素が .drawn[data-id] で引ける
      render();R.domHit=!!art.querySelector('.drawn[data-id="'+imgs[0].id+'"]');
      return R;})())"""))

    def bad(k, cond, msg):
        if not cond:
            fails.append(f"WAVE13-{k}: {msg}: {r.get(k)}")
    bad("A-place", r["placed"] and r["type"] == "image" and r["pathCount"] == 1 and r["storeSize"] == 1 and r["hasImgId"],
        "配置→state.pathsにtype:'image'1つ・imageStoreに画素1つ")
    bad("A-size", abs(r["longEdge"] - r["target"]) < 2 and r["centered"], "長辺がABの60%・中央のはず")
    bad("A-undo", r["afterUndo"] == 0 and r["afterRedo"] == 1, "Undoで消え・Redoで戻るはず")
    bad("J-pixels", r["snapNoPixels"] and r["snapLen"] < r["dataUrlLen"],
        "Undoの記録(snapshot)に画素dataURLが入らず・画素分増えないはず")
    bad("B-move", r["moved"], "移動でmatのe/fが+50/+30のはず")
    bad("B-scale", r["scaled"], "比率固定2倍でbboxが2倍のはず")
    bad("B-rot", r["rotated"], "回転90でbboxの幅高が入れ替わるはず")
    bad("B-pixels", r["pixelsKept"], "変形しても画素(imgId/w0/h0)は保持・imageStore1件のはず")
    bad("C-dup", r["dupCount"] == 2 and r["sameImgId"] and r["diffId"] and r["storeAfterDup"] == 1,
        "複製でimgId共有・別id・imageStore1件のまま")
    bad("hit", r["domHit"], "置いた画像がDOMで .drawn[data-id] として引けるはず")

    # JPEG も置ける（selftest 冒頭と同じく canvas の JPEG）
    ev(sock, "state.paths=[];state.selectedPath=null;state.selectedPaths=[];render();true")
    ev(sock, """(async()=>{const r=await fetch(window.__w13jpg);const b=await r.blob();
      placeImageFile(new File([b],'w13.jpg',{type:'image/jpeg'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "state.paths.some(p=>p.type==='image')"):
            break
        time.sleep(0.1)
    rj = json.loads(ev(sock, """JSON.stringify((()=>{const img=state.paths.find(p=>p.type==='image');
      const bb=img?bboxOfPath(img):null;
      return {jpg:!!img&&imageDataURL(img).indexOf('data:image/jpeg')===0,
        noUpscale:!!img&&img.w0===200&&bb&&Math.abs((bb.r-bb.l)-200)<1&&Math.abs((bb.b-bb.t)-120)<1};})())"""))
    if not rj["jpg"]:
        fails.append(f"WAVE13-JPEG: JPEGを配置すると data:image/jpeg で入るはず: {rj}")
    if not rj["noUpscale"]:
        fails.append(f"WAVE13-NOUPSCALE: 小さい画像(200px)は60%まで拡大しない（原寸で置く）はず: {rj}")

    # 手順4 切り抜き・手順5 SVG保存→開き直し（同じ画像は1回だけ埋める）
    r3 = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={};
      const cv=document.createElement('canvas');cv.width=100;cv.height=60;const c=cv.getContext('2d');
      c.fillStyle='#e23b3b';c.fillRect(0,0,100,60);const url=cv.toDataURL('image/png');
      imageStore.clear();nextImgId=1;const iid=nextImgId++;imageStore.set(iid,{dataURL:url,px:100,py:60});
      const L=state.layers[0].id;
      const img={id:nextId++,type:'image',imgId:iid,w0:100,h0:60,mat:[2,0,0,2,100,100],opacity:1,layerId:L};
      state.paths=[img];state.selectedPath=img.id;state.selectedPaths=[img.id];render();
      // 画像の上に長方形→両方選んで⌘7（切り抜き）
      const ell={id:nextId++,closed:true,fill:'#000000',stroke:'none',width:1,layerId:L,nodes:[node(150,130),node(250,130),node(250,200),node(150,200)]};
      state.paths.push(ell);state.selectedPaths=[img.id,ell.id];state.selectedPath=ell.id;makeClipMask();
      R.clipBy=pathById(img.id).clipBy===ell.id;
      const exp=buildExportSvg(false);R.svgImage=exp.indexOf('<image')>=0;R.svgClip=exp.indexOf('clip-path')>=0;
      // 画像だけ動かす→クリップ(形)は残る
      const bb0=bboxOfPath(pathById(img.id));state.selectedPaths=[img.id];state.selectedPath=img.id;transformSelection(mat(1,0,0,1,30,0));
      R.imgMoved=Math.abs(bboxOfPath(pathById(img.id)).l-(bb0.l+30))<1&&pathById(img.id).clipBy===ell.id;
      R.maskStill=Math.abs(bboxOfPath(pathById(ell.id)).l-150)<1;
      undo();R.afterUndo=pathById(img.id).clipBy===ell.id&&Math.abs(bboxOfPath(pathById(img.id)).l-bb0.l)<1;
      // 同じ画像を共有する2つめ（不透明0.5）→ images メタは1件
      const img2={id:nextId++,type:'image',imgId:iid,w0:100,h0:60,mat:[1,0,0,1,400,400],opacity:0.5,layerId:L};
      state.paths.push(img2);render();
      const svg=buildExportSvg(true);const doc=new DOMParser().parseFromString(svg,'image/svg+xml');
      const imeta=doc.getElementById('bezierkit-images');const obj=imeta?JSON.parse(imeta.textContent):{};
      R.embedOnce=Object.keys(obj).length===1;
      // 開き直し: imageStore を消して meta から作り直す
      imageStore.clear();nextImgId=1;restoreImageStoreFromMeta(imeta.textContent);restore(doc.getElementById('bezierkit').textContent);
      const imgs=state.paths.filter(p=>p.type==='image');
      R.reopenCount=imgs.length;R.reopenStore=imageStore.size;
      const im0=imgs.find(p=>p.mat[0]===2);R.reopenMat=!!im0&&im0.mat[4]===100;R.reopenClip=!!im0&&im0.clipBy!=null;
      R.reopenOpacity=imgs.some(p=>p.opacity===0.5);R.reopenHref=imageDataURL(imgs[0]).indexOf('data:image/png')===0;
      R.nextIdBumped=nextImgId>iid;
      return R;})())"""))
    def bad3(k, cond, msg):
        if not cond:
            fails.append(f"WAVE13-{k}: {msg}: {r3.get(k)}")
    bad3("clip", r3["clipBy"] and r3["svgImage"] and r3["svgClip"], "⌘7で画像に clipBy・SVGに <image> と clip-path")
    bad3("clip-move", r3["imgMoved"] and r3["maskStill"] and r3["afterUndo"], "画像だけ動く・形は残る・Undoで戻る")
    bad3("embed-once", r3["embedOnce"], "同じ画像を共有する2つでも images メタは1件")
    bad3("reopen", r3["reopenCount"] == 2 and r3["reopenStore"] == 1 and r3["reopenMat"] and r3["reopenClip"] and r3["reopenOpacity"] and r3["reopenHref"] and r3["nextIdBumped"],
         "開き直しで画像2つ・store1件・mat/切り抜き/不透明度/dataURLが戻り nextImgId が進む")

    # PNG に画像の色が出る（ラスタライズして画素を読む）
    rp = json.loads(ev(sock, r"""(async()=>{
      state.paths=state.paths.filter(p=>p.type==='image');state.paths.forEach(p=>{delete p.clipBy;});render();
      const svg=buildExportSvg(false);const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
      const img=new Image();await new Promise((res,rej)=>{img.onload=res;img.onerror=rej;img.src=url;});
      const cv=document.createElement('canvas');cv.width=ART.w;cv.height=ART.h;const c=cv.getContext('2d');c.drawImage(img,0,0);URL.revokeObjectURL(url);
      const px=c.getImageData(150,130,1,1).data;return JSON.stringify({r:px[0],g:px[1],b:px[2],a:px[3]});})()""", await_promise=True))
    if not (rp["a"] > 0 and rp["r"] > 150 and rp["g"] < 120):
        fails.append(f"WAVE13-PNG: PNGに画像の赤が出るはず（中心画素が赤・不透明）: {rp}")

    # 切り抜いた画像がラスタで正しい位置に出る（transform+clipのずれがない）
    rcr = json.loads(ev(sock, r"""(async()=>{
      const L=state.layers[0].id;const cv=document.createElement('canvas');cv.width=100;cv.height=100;const c=cv.getContext('2d');
      c.fillStyle='#e23b3b';c.fillRect(0,0,100,100);const url=cv.toDataURL('image/png');
      imageStore.clear();nextImgId=1;imageStore.set(1,{dataURL:url,px:100,py:100});
      const img={id:nextId++,type:'image',imgId:1,w0:100,h0:100,mat:[3,0,0,3,100,100],layerId:L};
      const box={id:nextId++,closed:true,fill:'#000',stroke:'none',width:1,layerId:L,nodes:[node(180,180),node(260,180),node(260,260),node(180,260)]};
      state.paths=[img,box];state.selectedPaths=[img.id,box.id];state.selectedPath=box.id;makeClipMask();render();
      const svg=buildExportSvg(false);const u=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
      const im=new Image();await new Promise((res,rej)=>{im.onload=res;im.onerror=rej;im.src=u;});
      const cc=document.createElement('canvas');cc.width=ART.w;cc.height=ART.h;const g=cc.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,ART.w,ART.h);g.drawImage(im,0,0);URL.revokeObjectURL(u);
      const ins=g.getImageData(220,220,1,1).data,out=g.getImageData(130,130,1,1).data;
      return JSON.stringify({inR:ins[0],inG:ins[1],outR:out[0],outG:out[1],outB:out[2]});})()""", await_promise=True))
    if not (rcr["inR"] > 150 and rcr["inG"] < 120 and rcr["outR"] > 240 and rcr["outG"] > 240 and rcr["outB"] > 240):
        fails.append(f"WAVE13-CLIP-RASTER: 切り抜いた画像はクリップの中だけ赤・外は白のはず（transform+clipのずれ無し）: {rcr}")

    # おかしな imgId・mat・w0 は捨てる／data URL は png・jpeg・webp・gif だけ受ける
    rb = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const L=state.layers[0].id;
      const snap=JSON.stringify({paths:[
        {id:1,type:'image',imgId:1,w0:10,h0:10,mat:[1,0,0,1,0,0],layerId:L},
        {id:2,type:'image',w0:10,h0:10,mat:[1,0,0,1,0,0],layerId:L},
        {id:3,type:'image',imgId:2,w0:10,h0:10,mat:[1,0,'x',1,0,0],layerId:L},
        {id:4,type:'image',imgId:3,w0:0,h0:10,mat:[1,0,0,1,0,0],layerId:L}],
        layers:state.layers,activeLayer:L,art:{w:ART.w,h:ART.h}});
      imageStore.clear();nextImgId=1;imageStore.set(1,{dataURL:'data:image/png;base64,AAAA'});restore(snap);
      const imgs=state.paths.filter(p=>p.type==='image');
      const R={kept:imgs.length,keptId:imgs.length===1&&imgs[0].imgId===1};
      imageStore.clear();nextImgId=1;
      restoreImageStoreFromMeta(JSON.stringify({1:'data:image/png;base64,AAAA',2:'data:text/html;base64,AAAA',3:'data:image/svg+xml;base64,AAAA',4:'data:image/webp;base64,AAAA',5:'data:image/gif;base64,AAAA'}));
      R.storeKeys=[...imageStore.keys()].sort((a,b)=>a-b);return R;})())"""))
    if not (rb["kept"] == 1 and rb["keptId"]):
        fails.append(f"WAVE13-SANITIZE: imgId無し・mat非数・w0非正の画像は捨てるはず: {rb}")
    if rb["storeKeys"] != [1, 4, 5]:
        fails.append(f"WAVE13-DATAURL: data URL は png/jpeg/webp/gif だけ受ける（text/html・svg は捨てる）はず: {rb}")

    # 画像を選ぶと塗り・線・太さの欄が押せない（不透明度は効く）。図形に切り替えると戻る
    rpanel = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const L=state.layers[0].id;imageStore.clear();nextImgId=1;imageStore.set(1,{dataURL:'data:image/png;base64,AAAA'});
      const img={id:nextId++,type:'image',imgId:1,w0:10,h0:10,mat:[1,0,0,1,0,0],opacity:1,layerId:L};
      state.paths=[img];state.selectedPaths=[img.id];state.selectedPath=img.id;updateControls();
      const R={fillDis:$('fillHex').disabled,strokeDis:$('strokeHex').disabled,widthDis:$('width').disabled,opacityOn:!$('opacity').disabled};
      const sq={id:nextId++,closed:true,fill:'#123456',stroke:'#000000',width:3,layerId:L,nodes:[node(0,0),node(10,0),node(10,10),node(0,10)]};
      state.paths=[sq];state.selectedPaths=[sq.id];state.selectedPath=sq.id;updateControls();
      R.fillBack=!$('fillHex').disabled;R.fillVal=$('fillHex').value.toLowerCase();return R;})())"""))
    if not (rpanel["fillDis"] and rpanel["strokeDis"] and rpanel["widthDis"] and rpanel["opacityOn"]):
        fails.append(f"WAVE13-PANEL: 画像選択で塗り・線・太さの欄が押せず・不透明度は効くはず: {rpanel}")
    if not (rpanel["fillBack"] and rpanel["fillVal"] == "#123456"):
        fails.append(f"WAVE13-PANEL2: 図形に切り替えると塗りの欄が戻るはず: {rpanel}")

    # 画像を含む選択でパス演算→画像は残り、ステータス
    rbool = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const L=state.layers[0].id;imageStore.clear();nextImgId=1;imageStore.set(1,{dataURL:'data:image/png;base64,AAAA'});
      const img={id:nextId++,type:'image',imgId:1,w0:10,h0:10,mat:[1,0,0,1,0,0],layerId:L};
      const a={id:nextId++,closed:true,fill:'#f00',stroke:'none',width:1,layerId:L,nodes:[node(0,0),node(50,0),node(50,50),node(0,50)]};
      const b={id:nextId++,closed:true,fill:'#00f',stroke:'none',width:1,layerId:L,nodes:[node(25,25),node(75,25),node(75,75),node(25,75)]};
      state.paths=[img,a,b];state.selectedPaths=[img.id,a.id,b.id];state.selectedPath=b.id;updateControls();
      const R={unionDisabled:$('union').disabled};
      booleanOp('union');R.imgKept=!!pathById(img.id)&&pathById(img.id).type==='image';R.status=$('status').textContent;
      return R;})())"""))
    if not (rbool["unionDisabled"] and rbool["imgKept"] and len(rbool["status"]) > 0):
        fails.append(f"WAVE13-BOOL: 画像を含む選択はパス演算せず画像が残り・ボタンは押せずステータスが出るはず: {rbool}")

    # 手順8 PPTX: p:pic・media1件（共有）・rels・Content_Types・rot/flipV・custGeom・alphaModFix・PPTX確認の画像数
    rpptx = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const L=state.layers[0].id;imageStore.clear();nextImgId=1;
      const pcv=document.createElement('canvas');pcv.width=40;pcv.height=40;pcv.getContext('2d').fillStyle='#e23b3b';pcv.getContext('2d').fillRect(0,0,40,40);
      imageStore.set(1,{dataURL:pcv.toDataURL('image/png')});
      const jcv=document.createElement('canvas');jcv.width=40;jcv.height=40;jcv.getContext('2d').fillStyle='#2244cc';jcv.getContext('2d').fillRect(0,0,40,40);
      imageStore.set(2,{dataURL:jcv.toDataURL('image/jpeg')});nextImgId=3;
      const img=(id,imgId,mat,extra)=>Object.assign({id,type:'image',imgId,w0:40,h0:40,mat,layerId:L},extra||{});
      const c=Math.cos(Math.PI/6),sn=Math.sin(Math.PI/6);
      const box={id:50,closed:true,clipMask:true,fill:'none',stroke:'none',width:1,layerId:L,nodes:[node(700,100),node(760,100),node(760,160),node(700,160)]};
      state.paths=[img(10,1,[2,0,0,2,100,100]),img(11,1,[c,sn,-sn,c,300,100]),img(12,2,[1,0,0,1,500,100],{opacity:0.5}),img(13,1,[1,0,0,-1,300,400]),img(14,1,[1,0,0,1,700,100],{clipBy:50}),box];
      state.selectedPaths=[];state.selectedPath=null;
      const r=buildPptxFiles({textBox:true,selectionOnly:false});const f=Object.fromEntries(r.files);
      const sl=f['ppt/slides/slide1.xml'],rels=f['ppt/slides/_rels/slide1.xml.rels'],ct=f['[Content_Types].xml'];
      const R={};
      R.picCount=(sl.match(/<p:pic>/g)||[]).length;
      R.mediaFiles=r.files.filter(x=>x[0].startsWith('ppt/media/')).length;
      R.ctImage=/Extension="png"/.test(ct)&&/Extension="jpeg"/.test(ct)&&ct.includes('image/png')&&ct.includes('image/jpeg');
      R.relImage=(rels.match(/relationships\/image/g)||[]).length;
      R.hasRot=/rot="1800000"/.test(sl);R.hasFlipV=/flipV="1"/.test(sl);
      R.hasCustGeom=/<a:custGeom>/.test(sl);R.hasAlpha=/<a:blip r:embed=\"[^\"]+\"><a:alphaModFix amt="50000"\/>/.test(sl);
      R.statImage=r.stats.image.length;R.check=pptxCheck().image;
      return R;})())"""))
    def badp(k, cond, msg):
        if not cond:
            fails.append(f"WAVE13-PPTX-{k}: {msg}: {rpptx.get(k)}")
    badp("pic", rpptx["picCount"] == 5, "画像5つが p:pic 5つになるはず")
    badp("media", rpptx["mediaFiles"] == 2, "媒体は共有込みで2件（imgId 1と2）のはず")
    badp("ct", rpptx["ctImage"], "[Content_Types] に png/jpeg の Default のはず")
    badp("rels", rpptx["relImage"] >= 2, "slide の rels に image 関係があるはず")
    badp("rot", rpptx["hasRot"], "30°回転が rot 属性に出るはず")
    badp("flipV", rpptx["hasFlipV"], "上下反転が flipV 属性に出るはず")
    badp("custGeom", rpptx["hasCustGeom"], "切り抜きは custGeom 付きの p:pic のはず")
    badp("alpha", rpptx["hasAlpha"], "不透明度は alphaModFix に出るはず")
    badp("stat", rpptx["statImage"] == 5 and rpptx["check"] == 5, "PPTX確認の画像数が5のはず")

    # 手順7 PDF: /XObject /Image・JPEG は DCTDecode・透明PNGは SMask・切り抜きは W n クリップ
    rpdf = json.loads(ev(sock, r"""(async()=>{
      const L=state.layers[0].id;imageStore.clear();nextImgId=1;
      const pcv=document.createElement('canvas');pcv.width=40;pcv.height=40;const pc=pcv.getContext('2d');pc.clearRect(0,0,40,40);pc.fillStyle='#e23b3b';pc.fillRect(0,0,30,30);
      imageStore.set(1,{dataURL:pcv.toDataURL('image/png')});
      const jcv=document.createElement('canvas');jcv.width=40;jcv.height=40;jcv.getContext('2d').fillStyle='#2244cc';jcv.getContext('2d').fillRect(0,0,40,40);
      imageStore.set(2,{dataURL:jcv.toDataURL('image/jpeg')});nextImgId=3;
      const box={id:50,closed:true,clipMask:true,fill:'none',stroke:'none',width:1,layerId:L,nodes:[node(700,100),node(760,100),node(760,160),node(700,160)]};
      state.paths=[{id:10,type:'image',imgId:1,w0:40,h0:40,mat:[2,0,0,2,100,100],layerId:L},
        {id:11,type:'image',imgId:2,w0:40,h0:40,mat:[1,0,0,1,500,100],layerId:L},
        {id:12,type:'image',imgId:1,w0:40,h0:40,mat:[1,0,0,1,700,100],layerId:L,clipBy:50},box];
      state.selectedPaths=[];state.selectedPath=null;
      await preparePdfImages([1,2]);
      const t=buildPdf({textBox:false,selectionOnly:false,keepClip:true}).text;
      const R={xobj:(t.match(/\/Subtype \/Image/g)||[]).length,dct:t.includes('/DCTDecode'),smask:t.includes('/SMask'),
        clip:/W\*? n\n[^Q]*\/Im\d+ Do/.test(t),doOps:(t.match(/\/Im\d+ Do/g)||[]).length};
      return JSON.stringify(R);})()""", await_promise=True))
    if not (rpdf["xobj"] >= 2 and rpdf["dct"] and rpdf["smask"] and rpdf["doOps"] == 3):
        fails.append(f"WAVE13-PDF-XOBJ: PDFに /Subtype /Image・JPEGはDCTDecode・透明PNGはSMask・3つ描画のはず: {rpdf}")
    if not rpdf["clip"]:
        fails.append(f"WAVE13-PDF-CLIP: 切り抜きは画像の前に W n クリップが出るはず: {rpdf}")

    # 外から開く SVG の data URL 画像だけ取り込む（http などは取り込まない）
    rsvg = json.loads(ev(sock, r"""JSON.stringify((()=>{
      state.paths=[];imageStore.clear();nextImgId=1;
      const cv=document.createElement('canvas');cv.width=20;cv.height=20;cv.getContext('2d').fillStyle='#39a';cv.getContext('2d').fillRect(0,0,20,20);const url=cv.toDataURL('image/png');
      const svg='<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 400 300" width="400" height="300">'+
        '<rect x="10" y="10" width="50" height="50" fill="#f00"/>'+
        '<image x="100" y="80" width="120" height="90" href="'+url+'"/>'+
        '<image x="0" y="0" width="40" height="40" href="https://example.com/x.png"/>'+
        '<image x="0" y="0" width="40" height="40" href="data:image/svg+xml;base64,PHN2Zy8+"/>'+
        '</svg>';
      importGenericSvg(svg,'imgimport.svg');
      const imgs=state.paths.filter(p=>p.type==='image');const shapes=state.paths.filter(p=>p.type!=='image');
      const R={imgCount:imgs.length,shapeCount:shapes.length,store:imageStore.size};
      if(imgs.length===1){const bb=bboxOfPath(imgs[0]);R.w0=imgs[0].w0;R.h0=imgs[0].h0;R.near=Math.abs((bb.r-bb.l)-120)<1&&Math.abs((bb.b-bb.t)-90)<1;R.href=imageDataURL(imgs[0]).indexOf('data:image/png')===0;}
      state.paths=[];imageStore.clear();render();return R;})())"""))
    if not (rsvg["imgCount"] == 1 and rsvg["shapeCount"] >= 1 and rsvg["store"] == 1 and rsvg.get("near") and rsvg.get("href") and rsvg.get("w0") == 120 and rsvg.get("h0") == 90):
        fails.append(f"WAVE13-SVG-IMPORT: data URL 画像1つだけ取り込み（http・svg は無視）・大きさ120x90のはず: {rsvg}")

    ev(sock, "state.paths=[];state.selectedPath=null;state.selectedPaths=[];imageStore.clear();pdfImgCache.clear();render();true")


def wave14_checks(sock, fails):
    # 波14 #5 複合シェイプ（compound）: 作成・焼き直し・拡張・解除・保存open・sanitize・undo
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={},L=state.layers[0].id;
      const sq=(id,x,fill)=>({id,nodes:[node(x,100),node(x+200,100),node(x+200,300),node(x,300)],closed:true,layerId:L,fill,stroke:'none',width:1});
      const reset=()=>{state.paths=[];state.selectedPaths=[];state.selectedPath=null;};
      // 1) comp-make: Option+合体で2つ→1つ・compound(op/kids2)・見た目=前面
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      R.makeLen=state.paths.length;const m=state.paths[0];R.hasComp=!!m.compound;R.op=m.compound&&m.compound.op;R.kids=m.compound&&m.compound.kids.length;R.frontFill=m.fill;
      // ふつうのパス演算（live=false）は compound を付けない
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',false);
      R.plainNoComp=!state.paths[0].compound;
      // 2) comp-sub-back: 型抜き→見た目=最背面
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('subtract',true);
      R.subFill=state.paths[0].fill;R.subOp=state.paths[0].compound&&state.paths[0].compound.op;
      // 3つ以上(comp-3plus)
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,160,'#00ff00'),sq(3,220,'#0000ff')];state.selectedPaths=[1,2,3];state.selectedPath=1;booleanOp('union',true);
      R.plusKids=state.paths[0].compound&&state.paths[0].compound.kids.length;
      // 3) comp-rebuild: kid の点を動かす→結果の bbox が変わる（sig 変化で焼き直し）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      let cp=state.paths[0];const bb0=bboxOfPath(cp);const sig0=cp.compound.sig;
      cp.compound.kids[1].nodes.forEach(n=>{n.x+=150;});render();const bb1=bboxOfPath(cp);
      R.rebuilt=Math.abs(bb1.r-bb0.r)>50&&cp.compound.sig!==sig0;
      // 5) comp-expand: 拡張→compound なし・形と見た目同じ
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      const pid=state.paths[0].id,beforeFill=state.paths[0].fill;
      const beforeForm=JSON.stringify(partsOf(state.paths[0]).map(pt=>pt.nodes.map(n=>[Math.round(n.x),Math.round(n.y)])));
      state.selectedPaths=[pid];state.selectedPath=pid;expandCompound();
      R.expNoComp=!state.paths[0].compound;R.expFill=state.paths[0].fill===beforeFill;
      R.expSameForm=JSON.stringify(partsOf(state.paths[0]).map(pt=>pt.nodes.map(n=>[Math.round(n.x),Math.round(n.y)])))===beforeForm;
      // 6) comp-release: 解除→元の2図形（kids数・見た目=結果の見た目）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      const rid=state.paths[0].id,rfill=state.paths[0].fill;
      state.selectedPaths=[rid];state.selectedPath=rid;releaseCompound();
      R.relLen=state.paths.length;R.relAllResult=state.paths.every(p=>p.fill===rfill);R.relNoComp=state.paths.every(p=>!p.compound);
      // 7) comp-save-open: 保存→開き直しで compound 残り→まだ直せる
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      const snap=snapshot();state.paths=[];render();restore(snap);
      const q=state.paths.find(p=>p.compound);R.openHasComp=!!q;R.openKids=q&&q.compound.kids.length;
      if(q){const a=bboxOfPath(q);q.compound.kids[0].nodes.forEach(n=>{n.x-=150;});render();const b=bboxOfPath(q);R.openEditable=Math.abs(b.l-a.l)>20||Math.abs(b.r-a.r)>20;}
      // 9) comp-sanitize: 壊れた compound データ→外れて普通のパス
      reset();const bad={id:nextId++,nodes:[node(100,100),node(300,100),node(300,300),node(100,300)],closed:true,layerId:L,fill:'#123456',compound:{op:'bogus',kids:[]}};
      sanitizeCompound(bad);R.saniNoComp=!bad.compound;R.saniKeptPath=Array.isArray(bad.nodes)&&bad.nodes.length===4;
      // 10) comp-undo: 作成1回 Undo で元の2つに戻る
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('exclude',true);
      R.undoBefore=state.paths.length;undo();R.undoAfter=state.paths.length;R.undoNoComp=state.paths.every(p=>!p.compound);
      // ボタンの有効・無効（複合シェイプを選んでいない時は押せない）
      reset();render();R.btnDisabled=$('compoundExpand').disabled&&$('compoundRelease').disabled;
      state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      state.selectedPaths=[state.paths[0].id];state.selectedPath=state.paths[0].id;render();
      R.btnEnabled=!$('compoundExpand').disabled&&!$('compoundRelease').disabled;
      // --- 2回目（手順4・5）---
      // 手順4: 中に入る→kidをまるごと動かす（ドラッグ中は作り直さない・離すと作り直す・Escで抜ける）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      const eid=state.paths[0].id;enterCompound(eid);R.entered=!!compEdit&&compEdit.id===eid;
      let ep=pathById(eid);const ebb0=bboxOfPath(ep);
      compDragging=true;ep.compound.kids[1].nodes.forEach(n=>{n.x+=120;n.inX+=120;n.outX+=120;});render();
      R.dragFrozen=Math.abs(bboxOfPath(ep).r-ebb0.r)<1;
      endCompDrag();R.relRebuilt=Math.abs(bboxOfPath(ep).r-ebb0.r)>50;R.stillComp=!!ep.compound;
      exitCompound();R.exited=!compEdit;
      // 手順5: ダイレクト選択で kid の点を動かす→結果が変わり compound は残る（手崩れで外れない）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      let dp=state.paths[0];state.tool='direct';state.selectedPaths=[dp.id];state.selectedPath=dp.id;render();
      const dbb0=bboxOfPath(dp);compDragging=true;dp.compound.kids[0].nodes[1].x+=160;dp.compound.kids[0].nodes[1].inX+=160;dp.compound.kids[0].nodes[1].outX+=160;render();endCompDrag();
      const dbb1=bboxOfPath(dp);R.directChanged=Math.abs(dbb1.r-dbb0.r)>30||Math.abs(dbb1.l-dbb0.l)>30;R.directComp=!!dp.compound;state.tool='select';
      // Undo: kid 移動1回が ⌘Z 1回で戻る
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      let up2=state.paths[0];const ubb0=bboxOfPath(up2);
      pushUndo();compDragging=true;up2.compound.kids[1].nodes.forEach(n=>{n.x+=130;n.inX+=130;n.outX+=130;});endCompDrag();
      R.undoMoved=Math.abs(bboxOfPath(up2).r-ubb0.r)>50;undo();const uback=pathById(up2.id);render();
      R.undoBack=!!(uback&&uback.compound&&Math.abs(bboxOfPath(uback).r-ubb0.r)<1);
      // 複合シェイプでないダブルクリックは中に入らない（同色選択のまま）
      reset();state.paths=[sq(1,100,'#ff0000')];enterCompound(state.paths[0].id);R.plainNoEnter=!compEdit;exitCompound();
      // 重い形（点>2000）: ドラッグ中は作り直さない
      reset();const bigKid=(cx)=>({closed:true,nodes:Array.from({length:1200},(_,i)=>{const t=i/1200*2*Math.PI,x=cx+260*Math.cos(t),y=400+260*Math.sin(t);return{x,y,inX:x,inY:y,outX:x,outY:y};})});
      let hp={id:nextId++,layerId:L,fill:'#888888',stroke:'none',width:1,closed:true,nodes:[node(100,100)],compound:{op:'union',kids:[bigKid(380),bigKid(620)],sig:''}};
      state.paths=[hp];state.selectedPaths=[hp.id];state.selectedPath=hp.id;render();
      R.heavyPts=hp.compound.kids.reduce((s,k)=>s+k.nodes.length,0);
      const beforeNodes=JSON.stringify(partsOf(hp).map(pt=>pt.nodes.length));
      compDragging=true;for(let i=0;i<3;i++){hp.compound.kids[0].nodes.forEach(n=>{n.x+=2;});render();}
      R.heavyFrozen=JSON.stringify(partsOf(hp).map(pt=>pt.nodes.length))===beforeNodes;
      endCompDrag();compDragging=false;
      // --- 3回目（自前ダブルクリック判定・手順6）---
      const pdAt=(x,y)=>{const el=document.elementFromPoint(x,y)||document.querySelector('.drawn');if(el)el.dispatchEvent(new PointerEvent('pointerdown',{clientX:x,clientY:y,bubbles:true,cancelable:true,button:0,pointerId:1}));svg.dispatchEvent(new PointerEvent('pointerup',{clientX:x,clientY:y,bubbles:true,cancelable:true,button:0,pointerId:1}));};
      // 2回の pointerdown（同じ場所・短時間）で複合シェイプに入る
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);state.tool='select';state.selectedPaths=[state.paths[0].id];state.selectedPath=state.paths[0].id;render();
      compEdit=null;lastDownInfo=null;{const r=document.querySelector('.drawn').getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;pdAt(cx,cy);pdAt(cx,cy);}
      R.dblEnter=!!compEdit;exitCompound();
      // 離れた2回はふつうの2クリック（中に入らない）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);state.tool='select';render();
      compEdit=null;lastDownInfo=null;{const r=document.querySelector('.drawn').getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;pdAt(cx-80,cy-60);pdAt(cx+80,cy+60);}
      R.farNoEnter=!compEdit;
      // ふつうの図形の2回押し＝同じ色を選ぶ（前からの動き）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,120,'#ff0000'),sq(3,520,'#0000ff')];state.selectedPaths=[];state.selectedPath=null;state.tool='select';render();
      compEdit=null;lastDownInfo=null;{const r=document.querySelector('.drawn').getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;pdAt(cx,cy);pdAt(cx,cy);}
      R.sameColorSel=state.selectedPaths.length;
      // 手順6: 複製は複合シェイプを保ち、元の形も一緒に動く
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      let cpd=state.paths[0];const cbb=bboxOfPath(cpd);const dup=transformedPath(cpd,mat(1,0,0,1,200,0));dup.id=nextId++;state.paths.push(dup);render();
      R.dupComp=!!dup.compound;R.dupShift=Math.abs((bboxOfPath(dup).l-cbb.l)-200)<2;
      // 手順6: シンボルにすると焼いた形（compound は外れる）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);state.symbols=null;
      let spp=state.paths[0];state.selectedPaths=[spp.id];state.selectedPath=spp.id;makeSymbol();
      R.symBaked=!spp.compound&&!!(state.symbols&&state.symbols.length);
      // 手順6: 繰り返しの元は compound を保ち、コピーは普通のパス
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);state.repeats=null;
      let rpp=state.paths[0];state.selectedPaths=[rpp.id];state.selectedPath=rpp.id;$('rptKind').value='grid';$('rptCols').value=2;$('rptRows').value=1;$('rptGap').value=20;makeRepeat();render();
      R.rptSrcComp=!!rpp.compound;R.rptCopyPlain=state.paths.filter(p=>p.rptOf!=null).length>0&&state.paths.filter(p=>p.rptOf!=null).every(p=>!p.compound);
      // 手順6: 書き出しは結果の形（SVGにcompoundは出ない・PPTX slideが作れる）
      reset();state.paths=[sq(1,100,'#ff0000'),sq(2,200,'#0000ff')];state.selectedPaths=[1,2];state.selectedPath=1;booleanOp('union',true);
      const svg2=buildPathsSvg(state.paths).text;R.svgPath=(svg2.match(/<path/g)||[]).length>=1;R.svgNoComp=!/compound/.test(svg2);
      R.pptxOk=!!Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'];
      reset();render();return R;
    })())"""))
    def bad(k, cond, msg):
        if not cond:
            fails.append(f"WAVE14-{k}: {msg}: {r.get(k)}")
    bad("make", r["makeLen"] == 1 and r["hasComp"] and r["op"] == "union" and r["kids"] == 2 and r["frontFill"].lower() == "#0000ff" and r["plainNoComp"],
        "Option+合体で1つ・compound(op=union,kids2)・見た目=前面#0000ff、live=falseはcompoundなしのはず")
    bad("sub-back", r["subFill"].lower() == "#ff0000" and r["subOp"] == "subtract", "型抜きは最背面#ff0000の見た目のはず")
    bad("3plus", r["plusKids"] == 3, "3つ以上でも複合シェイプ（kids3）のはず")
    bad("rebuild", r["rebuilt"], "kidの点を動かすと結果が焼き直される（bboxが変わる・sig更新）はず")
    bad("expand", r["expNoComp"] and r["expFill"] and r["expSameForm"], "拡張でcompoundが外れ、形と見た目は同じはず")
    bad("release", r["relLen"] == 2 and r["relAllResult"] and r["relNoComp"], "解除で元の2図形・どちらも結果の見た目のはず")
    bad("save-open", r["openHasComp"] and r["openKids"] == 2 and r.get("openEditable"), "保存→開き直しでcompoundが残り、まだ焼き直せるはず")
    bad("sanitize", r["saniNoComp"] and r["saniKeptPath"], "壊れたcompoundは外れ、焼いた結果は普通のパスで残るはず")
    bad("undo", r["undoBefore"] == 1 and r["undoAfter"] == 2 and r["undoNoComp"], "作成1回Undoで元の2つに戻るはず")
    bad("buttons", r["btnDisabled"] and r["btnEnabled"], "拡張・解除は複合シェイプ選択時だけ押せるはず")
    bad("enter-move", r["entered"] and r["dragFrozen"] and r["relRebuilt"] and r["stillComp"] and r["exited"],
        "中に入る→kid移動はドラッグ中据え置き・離すと作り直し・compound残る・Escで抜けるはず")
    bad("direct-point", r["directChanged"] and r["directComp"], "ダイレクト選択でkidの点を動かすと結果が変わりcompoundは残るはず")
    bad("edit-undo", r["undoMoved"] and r["undoBack"], "kid移動1回がUndo1回で元に戻るはず")
    bad("other-dblclick", r["plainNoEnter"], "複合シェイプでないダブルクリックは中に入らない（同色選択のまま）はず")
    bad("heavy", r["heavyPts"] > 2000 and r["heavyFrozen"], "2000点超の複合シェイプはドラッグ中に作り直さないはず")
    bad("dbl-enter", r["dblEnter"], "同じ場所の2回のpointerdownで複合シェイプに入るはず（自前ダブルクリック判定）")
    bad("far-no-enter", r["farNoEnter"], "離れた2回のpointerdownはダブルクリック扱いしない（中に入らない）はず")
    bad("same-color", r["sameColorSel"] == 2, "ふつうの図形の2回押しは同じ色を選ぶ（前からの動き・赤2個）はず")
    bad("dup", r["dupComp"] and r["dupShift"], "複製は複合シェイプを保ち、元の形も+200ずれて結果が追従するはず")
    bad("sym-bake", r["symBaked"], "シンボルにすると焼いた形になり compound は外れるはず")
    bad("rpt", r["rptSrcComp"] and r["rptCopyPlain"], "繰り返しの元は compound を保ち、コピーは普通のパスのはず")
    bad("export", r["svgPath"] and r["svgNoComp"] and r["pptxOk"], "書き出しは結果の形で出る（SVGにcompoundは出ず・PPTX slideが作れる）はず")


def wave15_checks(sock, fails):
    # 波15 #6 ワープ（15種の式・向き・かけ直し・平らに戻す・保存open・Undo・sanitize）
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={},L=state.layers[0].id;
      const reset=()=>{state.paths=[];state.selectedPaths=[];state.selectedPath=null;};
      const rect=(id,l,t,r,b)=>({id,nodes:[node(l,t),node(r,t),node(r,b),node(l,b)],closed:true,layerId:L,fill:'#cc3333',stroke:'#000000',width:4});
      const setW=(style,axis,bend,dh,dv)=>{$('warpStyle').value=style;$('warpAxis').value=axis||'h';$('warpBend').value=bend;$('warpDh').value=dh||0;$('warpDv').value=dv||0;};
      const poly=p=>sampleNodesToPoly(partsOf(p)[0]);
      const cur=()=>pathById(state.selectedPaths[0]);
      // A) アーチ・カーブ60: 上縁の中央が端より上（符号）・点が増える・全点有限
      reset();state.paths=[rect(1,100,100,300,300)];state.selectedPaths=[1];state.selectedPath=1;setW('arch','h',60,0,0);doWarp(true);
      {const res=cur(),pl=poly(res);R.archNodes=partsOf(res)[0].nodes.length;R.archFinite=pl.every(q=>isFinite(q[0])&&isFinite(q[1]));
       let l=1e9,rr=-1e9;pl.forEach(q=>{l=Math.min(l,q[0]);rr=Math.max(rr,q[0]);});const w=rr-l,cx=(l+rr)/2;
       const cTop=Math.min(...pl.filter(q=>Math.abs(q[0]-cx)<w*0.12).map(q=>q[1]));
       const eTop=Math.min(...pl.filter(q=>q[0]<l+w*0.12||q[0]>rr-w*0.12).map(q=>q[1]));
       R.archCenterUp=cTop<eTop-2;}
      // B) 円弧: 虹の形（真ん中が上）・全点有限・縦に伸びる（枠外へ出ず中心は合う）
      reset();state.paths=[rect(2,100,100,300,300)];state.selectedPaths=[2];state.selectedPath=2;setW('arc','h',60,0,0);doWarp(true);
      {const pl=poly(cur());R.arcFinite=pl.every(q=>isFinite(q[0])&&isFinite(q[1]));
       let l=1e9,rr=-1e9,t=1e9,b=-1e9;pl.forEach(q=>{l=Math.min(l,q[0]);rr=Math.max(rr,q[0]);t=Math.min(t,q[1]);b=Math.max(b,q[1]);});const w=rr-l,cx=(l+rr)/2;
       const cTop=Math.min(...pl.filter(q=>Math.abs(q[0]-cx)<w*0.12).map(q=>q[1]));
       const eTop=Math.min(...pl.filter(q=>q[0]<l+w*0.12||q[0]>rr-w*0.12).map(q=>q[1]));
       R.arcRainbow=cTop<eTop-2;R.arcCentered=Math.abs((l+rr)/2-200)<3;}
      // C) 膨張: 中央の縦の幅が端より広い
      reset();state.paths=[rect(3,100,100,300,300)];state.selectedPaths=[3];state.selectedPath=3;setW('bulge','h',80,0,0);doWarp(true);
      {const pl=poly(cur());let l=1e9,rr=-1e9;pl.forEach(q=>{l=Math.min(l,q[0]);rr=Math.max(rr,q[0]);});const w=rr-l,cx=(l+rr)/2;
       const band=f=>{const ys=pl.filter(f).map(q=>q[1]);return ys.length?Math.max(...ys)-Math.min(...ys):0;};
       R.bulgeCenterWider=band(q=>Math.abs(q[0]-cx)<w*0.1)>band(q=>q[0]<l+w*0.1)+5;}
      // C2) 絞り込み: 縦の中央の横幅が端（上下）より狭い
      reset();state.paths=[rect(4,100,100,300,300)];state.selectedPaths=[4];state.selectedPath=4;setW('squeeze','h',80,0,0);doWarp(true);
      {const pl=poly(cur());let t=1e9,b=-1e9;pl.forEach(q=>{t=Math.min(t,q[1]);b=Math.max(b,q[1]);});const h=b-t,cy=(t+b)/2;
       const band=f=>{const xs=pl.filter(f).map(q=>q[0]);return xs.length?Math.max(...xs)-Math.min(...xs):0;};
       R.squeezeCenterNarrower=band(q=>Math.abs(q[1]-cy)<h*0.1)<band(q=>q[1]<t+h*0.1)-5;}
      // D) 旋回・魚眼: 四隅がほぼ元位置／旋回は上辺の中央が動く
      const cornerFixed=(style)=>{reset();state.paths=[rect(5,100,100,300,300)];state.selectedPaths=[5];state.selectedPath=5;setW(style,'h',100,0,0);doWarp(true);
       const pl=poly(cur());return [[100,100],[300,100],[300,300],[100,300]].every(c=>pl.some(q=>Math.hypot(q[0]-c[0],q[1]-c[1])<8));};
      R.twistCorners=cornerFixed('twist');R.fisheyeCorners=cornerFixed('fisheye');
      reset();state.paths=[rect(6,100,100,300,300)];state.selectedPaths=[6];state.selectedPath=6;setW('twist','h',100,0,0);doWarp(true);
      {const P={style:'twist',axis:'h',bend:1,dh:0,dv:0},bb={l:100,t:100,w:200,h:200,cx:200,cy:200},m=warpPointMap(200,100,bb,P);R.twistMoved=Math.hypot(m.x-200,m.y-100)>20;} // 上辺の中央の点そのものの行き先で見る（ねじれた辺は元の中央の近くを通るので「近くに点がない」では測れない）
      // E) 文字「A」をワープ→図形になる→平らに戻すで text に戻る
      reset();const t={id:nextId++,type:'text',text:'A',x:200,y:300,size:80,letterSpacing:0,lineHeight:1.3,vertical:false,fontKey:'x',fill:'#000000',stroke:'none',width:1,layerId:L,
        cmds:[{type:'M',x:150,y:220},{type:'L',x:250,y:220},{type:'L',x:250,y:320},{type:'L',x:150,y:320},{type:'Z'}]};
      state.paths=[t];state.selectedPaths=[t.id];state.selectedPath=t.id;setW('arch','h',60,0,0);doWarp(true);
      {const w=cur();R.textBecameShape=!isText(w)&&!!(partsOf(w)[0]&&partsOf(w)[0].nodes);}
      warpUnwrap();{const back=cur();R.textBack=isText(back)&&back.text==='A';}
      // F) かけ直し: 60→80 が「元から一度だけ80」と図形数・bbox一致（2回がけにならない）
      reset();state.paths=[rect(7,100,100,300,300)];state.selectedPaths=[7];state.selectedPath=7;setW('arch','h',60,0,0);doWarp(true);
      setW('arch','h',80,0,0);doWarp(true);
      {const reb=cur();const rebBB=bboxOfPath(reb);const rebCount=state.paths.filter(p=>p.groupId===reb.groupId).length;
       reset();state.paths=[rect(8,100,100,300,300)];state.selectedPaths=[8];state.selectedPath=8;setW('arch','h',80,0,0);doWarp(true);
       const onceBB=bboxOfPath(cur());R.rebuildOneShape=rebCount===1;
       R.rebuildSame=Math.abs(rebBB.l-onceBB.l)<1&&Math.abs(rebBB.t-onceBB.t)<1&&Math.abs(rebBB.r-onceBB.r)<1&&Math.abs(rebBB.b-onceBB.b)<1;}
      // G) 向き=垂直でアーチ→左右の縁が反る（水平と転置）
      reset();state.paths=[rect(9,100,100,300,300)];state.selectedPaths=[9];state.selectedPath=9;setW('arch','v',60,0,0);doWarp(true);
      {const pl=poly(cur());let t=1e9,b=-1e9;pl.forEach(q=>{t=Math.min(t,q[1]);b=Math.max(b,q[1]);});const h=b-t,cy=(t+b)/2;
       const cLeft=Math.min(...pl.filter(q=>Math.abs(q[1]-cy)<h*0.12).map(q=>q[0]));
       const eLeft=Math.min(...pl.filter(q=>q[1]<t+h*0.12||q[1]>b-h*0.12).map(q=>q[0]));
       R.vArchBow=Math.abs(cLeft-eLeft)>5;}
      // H) 保存→開き直し→warpSrc 残りかけ直せる
      reset();state.paths=[rect(10,100,100,300,300)];state.selectedPaths=[10];state.selectedPath=10;setW('arch','h',60,0,0);doWarp(true);
      {const snap=snapshot();state.paths=[];render();restore(snap);
       const carrier=state.paths.find(p=>p.warpSrc);R.openHasWarp=!!carrier;R.openSrcLen=carrier&&carrier.warpSrc.src?carrier.warpSrc.src.length:0;
       if(carrier){const ids=state.paths.filter(p=>p.groupId===carrier.groupId).map(p=>p.id);setSelection(ids);const bb0=bboxOfPath(carrier);setW('arch','h',95,0,0);doWarp(true);const bb1=bboxOfPath(cur());R.openRewarp=Math.abs(bb1.t-bb0.t)>2||Math.abs(bb1.b-bb0.b)>2;}}
      // I) Undo 1回でワープが戻る（元の矩形1つ）
      reset();state.paths=[rect(11,100,100,300,300)];state.selectedPaths=[11];state.selectedPath=11;render();setW('arch','h',60,0,0);
      doWarp(true);R.warpCarrier=state.paths.filter(p=>p.warpSrc).length;
      undo();R.undoLen=state.paths.length;R.undoNoWarp=state.paths.every(p=>!p.warpSrc);R.undoIsRect=state.paths.length===1&&!!state.paths[0].nodes&&state.paths[0].nodes.length===4;
      // J) ボタンの文字（結果を選ぶと「かけ直す」＋平らに戻す／なしは「ワープ」）
      reset();state.paths=[rect(12,100,100,300,300)];state.selectedPaths=[12];state.selectedPath=12;setW('arch','h',60,0,0);doWarp(true);syncWarpControls();
      R.btnRewarp=$('warpRun').textContent==='かけ直す'&&$('warpFlat').style.display!=='none';
      reset();render();syncWarpControls();R.btnWarp=$('warpRun').textContent==='ワープ'&&$('warpFlat').style.display==='none';
      // K) sanitizeWarp: 壊れた warpSrc は外れ、正しいものは残る
      {const bad={id:nextId++,nodes:[node(0,0),node(1,0),node(1,1)],closed:true,layerId:L,fill:'#111111',warpSrc:{ui:{style:'bogus',axis:'h',bend:50,dh:0,dv:0},src:[{}]}};
       sanitizeWarp(bad);R.saniNoWarp=!bad.warpSrc;
       const good={id:nextId++,nodes:[node(0,0)],layerId:L,warpSrc:{ui:{style:'arc',axis:'h',bend:50,dh:0,dv:0},src:[{type:'text',text:'A'}]}};
       sanitizeWarp(good);R.saniKeepGood=!!good.warpSrc;}
      reset();render();return R;
    })())"""))
    def bad(k, cond, msg):
        if not cond:
            fails.append(f"WAVE15-{k}: {msg}: {r.get(k)}")
    bad("arch", r["archFinite"] and r["archCenterUp"] and r["archNodes"] >= 4, "アーチ+で上縁の中央が端より上・点が有限のはず")
    bad("arc", r["arcFinite"] and r["arcRainbow"] and r["arcCentered"], "円弧+は虹の形（真ん中が上）で中心が元の枠に合うはず")
    bad("bulge", r["bulgeCenterWider"], "膨張は中央の縦幅が端より広いはず")
    bad("squeeze", r["squeezeCenterNarrower"], "絞り込みは縦の中央の横幅が端より狭いはず")
    bad("twist-corners", r["twistCorners"] and r["twistMoved"], "旋回は四隅がほぼ元位置で上辺の中央が動くはず")
    bad("fisheye-corners", r["fisheyeCorners"], "魚眼は四隅が固定のはず")
    bad("text", r["textBecameShape"] and r["textBack"], "文字をワープ→図形になり、平らに戻すと text「A」に戻るはず")
    bad("rebuild", r["rebuildOneShape"] and r["rebuildSame"], "かけ直し(60→80)が元から一度だけ80と図形数・bbox一致のはず（2回がけにならない）")
    bad("v-arch", r["vArchBow"], "向き垂直のアーチは左右の縁が反る（水平と転置）はず")
    bad("save-open", r["openHasWarp"] and r["openSrcLen"] >= 1 and r.get("openRewarp"), "保存→開き直しでwarpSrcが残り、かけ直せるはず")
    bad("undo", r["warpCarrier"] == 1 and r["undoLen"] == 1 and r["undoNoWarp"] and r["undoIsRect"], "ワープ1回がUndo1回で元の矩形に戻るはず")
    bad("buttons", r["btnRewarp"] and r["btnWarp"], "結果選択で「かけ直す」＋平らに戻す表示、選択なしは「ワープ」のはず")
    bad("sanitize", r["saniNoWarp"] and r["saniKeepGood"], "壊れたwarpSrcは外れ、正しいものは残るはず")


def wave16_checks(sock, fails):
    # 波16 F1 外接枠を曲線のふくらみまで入れる / F2 PPTX放射グラデの広がり100%超 / F3 数値欄の矢印はUndo1回
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={},L=state.layers[0].id,K=0.5522847498;
      const ell=(cx,cy,a,b)=>({closed:true,nodes:[
        {x:cx+a,y:cy,inX:cx+a,inY:cy-b*K,outX:cx+a,outY:cy+b*K},
        {x:cx,y:cy+b,inX:cx+a*K,inY:cy+b,outX:cx-a*K,outY:cy+b},
        {x:cx-a,y:cy,inX:cx-a,inY:cy+b*K,outX:cx-a,outY:cy-b*K},
        {x:cx,y:cy-b,inX:cx-a*K,inY:cy-b,outX:cx+a*K,outY:cy-b}]});
      const rotNd=(nd,cx,cy,ang)=>{const c=Math.cos(ang),s=Math.sin(ang),tf=(x,y)=>[cx+(x-cx)*c-(y-cy)*s,cy+(x-cx)*s+(y-cy)*c];
        return {closed:true,nodes:nd.nodes.map(n=>{const[x,y]=tf(n.x,n.y),[ix,iy]=tf(n.inX,n.inY),[ox,oy]=tf(n.outX,n.outY);return{x,y,inX:ix,inY:iy,outX:ox,outY:oy};})};};
      const anchorW=p=>{let l=1e9,r=-1e9;partsOf(p)[0].nodes.forEach(n=>{l=Math.min(l,n.x);r=Math.max(r,n.x);});return r-l;};
      // F1-a) 45°回した楕円 a=100 b=60 → W=H=2√((a²+b²)/2)、アンカーだけの枠(141.4)より明らかに大きい
      {const a=100,b=60,th=Math.PI/4;const p={id:nextId++,...rotNd(ell(400,400,a,b),400,400,th),layerId:L,fill:'#cc3333',width:4};
       const bb=bboxOfPath(p),W=bb.r-bb.l,H=bb.b-bb.t,exp=2*Math.sqrt(a*a*Math.cos(th)**2+b*b*Math.sin(th)**2);
       R.rotW=W;R.rotH=H;R.rotExp=exp;R.rotAnchorW=anchorW(p);}
      // F1-b) 軸に沿った楕円は W=2a, H=2b（今までと同じ＝アンカーが極値）
      {const a=100,b=60;const p={id:nextId++,...ell(400,400,a,b),layerId:L,fill:'#cc3333'};const bb=bboxOfPath(p);R.axW=bb.r-bb.l;R.axH=bb.b-bb.t;}
      // F1-c) アーチをかけた四角 → 枠の上辺が曲線の一番上と合い、アンカーの一番上より上
      {state.paths=[{id:nextId++,nodes:[node(100,100),node(300,100),node(300,300),node(100,300)],closed:true,layerId:L,fill:'#cc3333',stroke:'#000000',width:4}];
       state.selectedPaths=[state.paths[0].id];state.selectedPath=state.paths[0].id;
       $('warpStyle').value='arch';$('warpAxis').value='h';$('warpBend').value=60;$('warpDh').value=0;$('warpDv').value=0;doWarp(true);
       const res=pathById(state.selectedPaths[0]),bb=bboxOfPath(res),pl=sampleNodesToPoly(partsOf(res)[0]);
       const curveTop=Math.min(...pl.map(q=>q[1])),anchorTop=Math.min(...partsOf(res)[0].nodes.map(n=>n.y));
       R.archTopMatch=Math.abs(bb.t-curveTop)<1.5;R.archTopAboveAnchor=bb.t<anchorTop-2;}
      // F1-d) 軸に沿った四角は四隅ぴったり（今までと同じ）
      {const p={id:nextId++,nodes:[node(100,100),node(300,100),node(300,250),node(100,250)],closed:true,layerId:L,fill:'#cc3333'};const bb=bboxOfPath(p);
       R.rectExact=Math.abs(bb.l-100)<.001&&Math.abs(bb.t-100)<.001&&Math.abs(bb.r-300)<.001&&Math.abs(bb.b-250)<.001;}
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      // F2) 放射グラデ 広がり135% のPPTX fill XML（最後のgsがpos=100000で色が1/1.35の補間色）／広がり60%は今まで通りpos縮む
      {const f={radial:true,spread:135,cx:.5,cy:.5,stops:[[0,'FF0000',1],[.5,'00FF00',1],[1,'0000FF',1]]};
       const xml=pptxFillXml(f),gs=[...xml.matchAll(/<a:gs pos="(\d+)"><a:srgbClr val="([0-9A-F]{6})"/g)].map(m=>[+m[1],m[2]]);
       R.gsCount=gs.length;R.lastPos=gs[gs.length-1][0];R.lastCol=gs[gs.length-1][1];R.lastIsOrig=gs[gs.length-1][1]==='0000FF';
       const f2={radial:true,spread:60,cx:.5,cy:.5,stops:[[0,'FF0000',1],[.5,'00FF00',1],[1,'0000FF',1]]};
       const gs2=[...pptxFillXml(f2).matchAll(/<a:gs pos="(\d+)"/g)].map(m=>+m[1]);R.small60Last=gs2[gs2.length-1];}
      // F3) 数値欄の矢印を続けて3回→Undo1回。setup＝多角形6角形
      const sh={type:'polygon',cx:200,cy:200,r:100,rot:0,sides:6};
      const p={id:nextId++,closed:true,nodes:shapeToNodes(sh).map(n=>({x:n.x,y:n.y,inX:n.x,inY:n.y,outX:n.x,outY:n.y})),shape:{...sh},layerId:L,fill:'#cc3333'};
      state.paths=[p];state.selectedPaths=[p.id];state.selectedPath=p.id;render();$('polySides').value=6;
      undoStack.length=0;const base=undoStack.length; // 50段の上限に当たると length の差がずれるので一旦空に
      [5,4,3].forEach(v=>{$('polySides').value=v;$('polySides').dispatchEvent(new Event('change',{bubbles:true}));});
      R.after3=undoStack.length-base;R.sides3=pathById(p.id).shape.sides;
      undo();R.sidesUndo=pathById(p.id)&&pathById(p.id).shape?pathById(p.id).shape.sides:null;
      window.__f3id=p.id;window.__f3base=undoStack.length;
      return R;
    })())"""))
    def bad(k, cond, msg):
        if not cond:
            fails.append(f"WAVE16-{k}: {msg}: {r.get(k)}")
    bad("f1-rot", abs(r["rotW"] - r["rotExp"]) < 1.5 and abs(r["rotH"] - r["rotExp"]) < 1.5 and r["rotW"] > r["rotAnchorW"] + 10,
        f"45°回した楕円のW/Hが真の大きさ{r['rotExp']:.2f}でアンカー枠{r['rotAnchorW']:.1f}より大きいはず")
    bad("f1-axis", abs(r["axW"] - 200) < 0.6 and abs(r["axH"] - 120) < 0.6, "軸に沿った楕円は W=2a・H=2b のはず")
    bad("f1-arch", r["archTopMatch"] and r["archTopAboveAnchor"], "アーチの枠の上辺が曲線の一番上と合い、アンカーの一番上より上のはず")
    bad("f1-rect", r["rectExact"], "軸に沿った四角は四隅ぴったりのはず")
    bad("f2-last", r["lastPos"] == 100000 and not r["lastIsOrig"] and r["lastCol"] == "00847B",
        "広がり135%のPPTXは最後のgsがpos=100000で色が1/1.35の補間色(00847B)のはず")
    bad("f2-count", r["gsCount"] == 3, "広がり135%は分岐点3つ（pos×1.35≤100%の2つ＋100%の境界1つ）のはず")
    bad("f2-small", r["small60Last"] == 60000, "広がり60%は最後のgsが pos=60000（今まで通り）のはず")
    bad("f3-rapid", r["after3"] == 1 and r["sides3"] == 3 and r["sidesUndo"] == 6,
        "角数の矢印を続けて3回→Undoの記録は1つ・⌘Z1回で6角形に戻るはず")
    # F3 gap: 1秒超あけた2回の変更は Undo 2回（別々）。undo() が選択を解いたので選び直す。
    # 直前の rapid 連打と1秒以内だと1回目もまとまってしまうので、1回目の前も1.2秒あける
    ev(sock, r"""(()=>{state.selectedPaths=[window.__f3id];state.selectedPath=window.__f3id;render();undoStack.length=0;window.__f3base=undoStack.length;return true;})()""")
    time.sleep(1.2)
    ev(sock, r"""(()=>{$('polySides').value=5;$('polySides').dispatchEvent(new Event('change',{bubbles:true}));return true;})()""")
    time.sleep(1.2)
    gap = json.loads(ev(sock, r"""JSON.stringify((()=>{$('polySides').value=4;$('polySides').dispatchEvent(new Event('change',{bubbles:true}));
      return {delta:undoStack.length-window.__f3base,sides:pathById(window.__f3id).shape.sides};})())"""))
    bad("f3-gap", gap["delta"] == 2, f"1秒超あけて押した2回はUndo2回（別々）のはず: {gap}")

    # 波16 F4: 下絵の移動/拡縮のUndo・文字を外接枠で掴む・エリア文字あふれのPPTX・グラデ分岐点トラック追加
    f = json.loads(ev(sock, r"""(async()=>{
      const R={},L=state.layers[0].id,font=await ensureFont();
      // F4-1) 下絵の位置・大きさが snapshot に入り、⌘Z で戻る（画素は入れない）
      underlayBounds={x:100,y:50,w:200,h:200};
      const s1=JSON.parse(snapshot());R.ulInSnap=!!(s1.underlay&&s1.underlay.x===100&&s1.underlay.w===200)&&s1.underlayImg===undefined;
      undoStack.length=0;pushUndo();underlayBounds={x:300,y:150,w:200,h:200};undo();R.ulUndoX=underlayBounds?underlayBounds.x:null;
      underlayBounds=null;R.ulNullSafe=(JSON.parse(snapshot()).underlay===undefined);
      // F4-2) 文字の外接枠の中（画線でない隙間）でも掴める・上の文字が先
      state.paths=[];
      const mkT=(id,x,y)=>{const t={id,type:'text',text:'口',x,y,size:120,letterSpacing:0,lineHeight:1.3,vertical:false,fill:'#000000',stroke:'none',width:1,layerId:L};t.cmds=textCmds(font,t);return t;};
      const t1=mkT(nextId++,100,300);state.paths=[t1];const b=bboxOfPath(t1),cx=(b.l+b.r)/2,cy=(b.t+b.b)/2;
      R.gapHit=((textHitForEdit({x:cx,y:cy})||{}).id===t1.id);
      const t2=mkT(nextId++,110,310);state.paths=[t1,t2];R.topFirst=((textHitForEdit({x:cx,y:cy})||{}).id===t2.id);
      // F4-3) エリア内文字のあふれ→PPTX は見えている行だけ・注記の文言
      state.paths=[];const jp='あいうえおかきくけこさしすせそたちつてと';const aw=c=>font.getAdvanceWidth(c,40);
      const ta={id:nextId++,type:'text',text:jp,x:100,y:100,size:40,letterSpacing:0,lineHeight:1.3,vertical:false,area:true,boxW:aw('あ')*3,boxH:40*1.3*2+2,fontKey:currentFontKey,fill:'#000000',stroke:'none',width:1,layerId:L};ta.cmds=textCmds(font,ta);
      R.taOverflow=areaOverflow(ta);const wl=wrapLines(font,ta),maxN=Math.max(1,Math.floor((ta.boxH+1e-6)/(1.3*40)));
      const xml=pptxTextXml(nextId++,ta,1).xml;R.taParas=(xml.match(/<a:p>/g)||[]).length;R.taMaxN=maxN;R.taWl=wl.length;
      const bodyT=[...xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map(m=>m[1]).join('');const lastChar=(wl[wl.length-1]||'').slice(-1);R.taLastHidden=!!lastChar&&bodyT.indexOf(lastChar)===-1;
      R.taNote=((resolvePrimitives(ta).notes||[]).join('｜')).indexOf('見えている行だけ')>=0;
      // F4-4) グラデ分岐点トラックの空き追加（丸でない所を押す＝帯と同じ）
      try{setPanelTab('draw');}catch(_){}
      const gp={id:nextId++,nodes:[node(100,100),node(300,100),node(300,300),node(100,300)],closed:true,layerId:L,fill:'#ff0000',gradient:{c1:'#ff0000',c2:'#0000ff',angle:0}};
      state.paths=[gp];state.selectedPaths=[gp.id];state.selectedPath=gp.id;$('fillType').value='grad';applyAppearance('fillType');try{renderGradBar();}catch(_){}
      const track=$('gradStopTrack'),tr=track.getBoundingClientRect();R.trackW=tr.width;
      const before=gradBarTarget()?gradBarTarget().get().length:0;
      if(tr.width>2)track.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:tr.left+tr.width*0.5,clientY:tr.top+7}));
      R.trackBefore=before;R.trackAfter=gradBarTarget()?gradBarTarget().get().length:0;
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;underlayBounds=null;render();return JSON.stringify(R);
    })()""", await_promise=True))
    bad("f4-underlay-undo", f["ulInSnap"] and f["ulUndoX"] == 100 and f["ulNullSafe"],
        "下絵の位置・大きさが snapshot に入り（画素は入れない）⌘Zで戻る・下絵なしでも安全なはず")
    bad("f4-text-bbox", f["gapHit"] and f["topFirst"], "文字の外接枠の隙間でも掴め、重なりは上の文字が先のはず")
    bad("f4-area-pptx", f["taOverflow"] and f["taParas"] == f["taMaxN"] and f["taMaxN"] < f["taWl"] and f["taLastHidden"] and f["taNote"],
        f"エリア文字あふれ→PPTXは見えている行だけ・注記は『見えている行だけ』のはず: {f}")
    bad("f4-grad-track", (f["trackW"] <= 2) or (f["trackAfter"] == f["trackBefore"] + 1),
        f"グラデ分岐点トラックの空きを押すと分岐点が増えるはず: {f}")


def wave17_checks(sock, fails):
    # 波17: 整える（ラフ整形）＋ 配色の差し替え（2026-11-13b）
    r = json.loads(ev(sock, r"""JSON.stringify((()=>{
      const R={},L=state.activeLayer;
      const mk=(id,pts,extra)=>Object.assign({id,nodes:pts.map(p=>node(p[0],p[1])),closed:true,layerId:L,fill:'#888888',stroke:'none'},extra||{});
      // (1a) 手描き風の歪んだ四角 → 水平・垂直吸着で各辺が水平/垂直になる
      let sq=mk(1,[[10,12],[210,6],[206,208],[4,204]]);
      state.paths=[sq];state.selectedPaths=[1];state.selectedPath=1;
      tidyApplyToPath(sq,{snapHV:true,strength:100});
      {const ns=sq.nodes,ec=ns.length;let ok=true;
       for(let i=0;i<ec;i++){const a=ns[i],b=ns[(i+1)%ec];if(!(Math.abs(b.x-a.x)<0.5||Math.abs(b.y-a.y)<0.5))ok=false;}
       R.snapAxis=ok;}
      // (1b) 左右対称化 → 左右の点が鏡像になる
      let q=mk(2,[[10,10],[200,20],[190,200],[20,190]]);
      state.paths=[q];tidyApplyToPath(q,{sym:true,strength:100});
      {const qs=q.nodes,xs=qs.map(n=>n.x),ax=(Math.min(...xs)+Math.max(...xs))/2;let ok=true;
       qs.forEach(n=>{const mx=2*ax-n.x;let best=Infinity;qs.forEach(m=>{best=Math.min(best,Math.hypot(m.x-mx,m.y-n.y));});if(best>0.5)ok=false;});
       R.sym=ok;}
      // (1c) 小窓のプレビュー→適用→Undo（本物のUI経路）
      let sq2=mk(3,[[10,12],[210,6],[206,208],[4,204]]);
      state.paths=[sq2];state.selectedPaths=[3];state.selectedPath=3;undoStack.length=0;
      const g=id=>document.getElementById(id);
      ['tidyEqual','tidySym','tidyCorner','tidySmooth','tidySimplify','tidyKeep'].forEach(i=>g(i).checked=false);
      g('tidyHV').checked=true;g('tidyStrength').value=100;
      tidyOpen();const prevX=pathById(3).nodes[1].x;
      tidyApplyCommit();const afterX=pathById(3).nodes[1].x;
      R.applied=Math.abs(afterX-prevX)<0.5&&g('tidyPanel').style.display==='none';
      undo();const un=pathById(3).nodes[1];
      R.undoBack=Math.abs(un.x-210)<0.5&&Math.abs(un.y-6)<0.5;
      // (2) 3色の図形群（1つはグラデ）→ パレット適用で色が置き換わり・グラデも変わる
      let a=mk(10,[[0,0],[80,0],[80,80],[0,80]],{fill:'#ff0000'});
      let b=mk(11,[[100,0],[180,0],[180,80],[100,80]],{fill:'#00cc00'});
      let gr=mk(12,[[200,0],[280,0],[280,80],[200,80]],{fill:'#0000ff',gradient:{c1:'#0000ff',c2:'#ffff00',angle:0}});
      state.paths=[a,b,gr];state.selectedPaths=[];state.selectedPath=null;recolorScope=null;
      g('recolorList').replaceChildren();g('recolorActs').style.display='none';
      const before={f10:pathById(10).fill,f11:pathById(11).fill,g1:pathById(12).gradient.c1,g2:pathById(12).gradient.c2};
      const palColors=RECOLOR_PALSETS.find(p=>p.id==='dk-seiryoku').colors,palSet=palColors.map(c=>c.toLowerCase());
      g('recolorPalSel').value='dk-seiryoku';
      R.previewRows=applyPaletteToRecolor(palColors);
      applyRecolor();
      const after={f10:pathById(10).fill,f11:pathById(11).fill,g1:pathById(12).gradient.c1,g2:pathById(12).gradient.c2};
      R.fillChanged=after.f10!==before.f10&&after.f11!==before.f11;
      R.fillInPal=palSet.includes((after.f10||'').toLowerCase())&&palSet.includes((after.f11||'').toLowerCase());
      R.gradChanged=after.g1!==before.g1||after.g2!==before.g2;
      R.gradInPal=palSet.includes((after.g1||'').toLowerCase())&&palSet.includes((after.g2||'').toLowerCase());
      R.corpColors=RECOLOR_PALSETS.find(p=>p.id==='dk-corporate').colors.every(c=>/^#[0-9a-f]{6}$/i.test(c));
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;recolorScope=null;
      g('recolorList').replaceChildren();g('recolorActs').style.display='none';render();
      return R;
    })())"""))
    checks = {
      "snapAxis": "W17-snapHV: 歪んだ四角が吸着後に各辺水平/垂直になるはず",
      "sym": "W17-sym: 対称化後に左右の点が鏡像になるはず",
      "applied": "W17-tidy-apply: 小窓のプレビュー→適用で形が確定し小窓が閉じるはず",
      "undoBack": "W17-tidy-undo: Undoで元の歪んだ四角に戻るはず",
      "fillChanged": "W17-recolor-fill: パレット適用で塗り色が置き換わるはず",
      "fillInPal": "W17-recolor-inpal: 置換後の塗りがパレットの色のはず",
      "gradChanged": "W17-recolor-grad: グラデの分岐点も置き換わるはず",
      "gradInPal": "W17-recolor-gradpal: 置換後のグラデ色がパレットの色のはず",
      "corpColors": "W17-corp-derive: corporateテーマ色がaccentから導出され有効なhexのはず",
    }
    for k, msg in checks.items():
        if not r.get(k):
            fails.append(f"{msg}: {r.get(k)} / {r}")
    if r.get("previewRows") != 4:
        fails.append(f"W17-recolor-rows: 3色(＋グラデ終)で4行集まるはず: {r.get('previewRows')}")


def selftest():
    fails = []
    chrome, sock = boot()
    # 起動時のプリセット図形（コッホ雪片）を消してから測る
    ev(sock, "state.paths=[];render();true")
    # 合成画像: 白地に赤の円と青の正方形（1000x750=精細さ360/720で処理画素が変わる大きさ）
    ev(sock, """(()=>{
      const cv=document.createElement('canvas');cv.width=1000;cv.height=750;
      const ctx=cv.getContext('2d');
      ctx.fillStyle='#ffffff';ctx.fillRect(0,0,1000,750);
      ctx.fillStyle='#cc2222';ctx.beginPath();ctx.arc(300,375,200,0,7);ctx.fill();
      ctx.fillStyle='#2244cc';ctx.fillRect(600,175,300,300);
      window.__testUrl=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{
      const r=await fetch(window.__testUrl);const b=await r.blob();
      loadTraceImage(new File([b],'synthetic.png',{type:'image/png'}));return true;})()""",
       await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)

    # 0) 外周線だけ: 背景色を辺から自動判定し、画像を残したまま線だけを1レイヤーへ生成
    ev(sock, "window.__underlayBefore=document.getElementById('underlayImg').getAttribute('href');true")
    do_trace(sock, 3, 1.2, 3, 360, True, "outline")
    outline = json.loads(ev(sock, """JSON.stringify((()=>{
      const parts=p=>p.subpaths||[p],built=buildPathsSvg(state.paths);
      return {paths:state.paths.length,layers:state.layers.filter(L=>L.name==='アウトライン').length,
        lines:state.paths.every(p=>p.fill==='none'&&p.stroke==='#121212'&&p.width===2),
        closed:state.paths.every(p=>parts(p).every(q=>q.closed)),
        selected:state.selectedPaths.length===state.paths.length&&!underlaySel,
        underlay:!!document.getElementById('underlayImg')&&document.getElementById('underlayImg').getAttribute('href')===window.__underlayBefore,
        cadSvg:!!built&&built.text.includes('<path')&&!built.text.includes('<image')};
    })())"""))
    if outline["paths"] != 2 or outline["layers"] != 1:
        fails.append(f"OUTLINE-TRACE: 円と四角が1レイヤー・2パスになるはず: {outline}")
    for key in ("lines", "closed", "selected", "underlay", "cadSvg"):
        if not outline[key]: fails.append(f"OUTLINE-TRACE: {key} が成立しない: {outline}")
    ev(sock, "undo()")

    # 1) 曲線フィットON: 円が少ないアンカーの滑らかなパスになるか
    do_trace(sock, 3, 1.2, 3, 360, True)
    st = json.loads(ev(sock, STATS_JS))
    if not (st["paths"] >= 2): fails.append(f"FIT: パスが2以上のはず: {st}")
    if not (st["nodes"] <= 80): fails.append(f"FIT: 円+四角で総アンカー80以下のはず: {st}")
    if not (st["smooth"] > 0): fails.append(f"FIT: ハンドル付きノードがあるはず: {st}")
    # 円の真円度: 赤いパスの「曲線上サンプル点」がbbox中心から半径ほぼ一定
    rr = json.loads(ev(sock, """JSON.stringify((()=>{
      const p=state.paths.find(q=>{const c=q.fill||'';
        return c!=='none'&&parseInt(c.slice(1,3),16)>150&&parseInt(c.slice(5,7),16)<110;});
      if(!p)return null;
      const ns=(p.subpaths?p.subpaths[0]:p).nodes;
      const xs=ns.map(n=>n.x),ys=ns.map(n=>n.y);
      const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
      const bez=(a,b,t)=>{const u=1-t;return[
        u*u*u*a.x+3*t*u*u*a.outX+3*t*t*u*b.inX+t*t*t*b.x,
        u*u*u*a.y+3*t*u*u*a.outY+3*t*t*u*b.inY+t*t*t*b.y];};
      const rs=[];
      for(let i=0;i<ns.length;i++){const a=ns[i],b=ns[(i+1)%ns.length];
        for(let t=0;t<1;t+=.125){const q2=bez(a,b,t);rs.push(Math.hypot(q2[0]-cx,q2[1]-cy));}}
      return {min:Math.min(...rs),max:Math.max(...rs),n:ns.length};
    })())"""))
    if not rr: fails.append("FIT: 赤い円のパスが見つからない")
    elif (rr["max"] - rr["min"]) / rr["max"] > 0.10:
        fails.append(f"FIT: 円の半径ぶれが10%超: {rr}")
    ev(sock, "undo()")

    # 2) 折れ線モード(フィットOFF)が従来通り動くか
    do_trace(sock, 3, 1.2, 3, 360, False)
    st2 = json.loads(ev(sock, STATS_JS))
    if not (st2["nodes"] > st["nodes"]): fails.append(f"OFF: 折れ線はフィットよりアンカー多いはず: {st2} vs {st}")
    if st2["smooth"] != 0: fails.append(f"OFF: 折れ線モードにハンドルは無いはず: {st2}")
    ev(sock, "undo()")

    # 3) 精細さ720で処理解像度が上がるか（単純化0なら境界点数はほぼ解像度比例）
    do_trace(sock, 3, 0, 3, 360, False)
    lo = json.loads(ev(sock, STATS_JS))
    ev(sock, "undo()")
    do_trace(sock, 3, 0, 3, 720, False)
    hi = json.loads(ev(sock, STATS_JS))
    if not (hi["nodes"] > lo["nodes"] * 1.5): fails.append(f"RES: 精細さ720は360より境界点が増えるはず: {hi} vs {lo}")
    ev(sock, "undo()")

    # 4) レイヤー統合: トレース→2色レイヤーを統合して色が揃いレイヤーが減る
    do_trace(sock, 3, 1.2, 3, 360, True)
    merged = json.loads(ev(sock, """JSON.stringify((()=>{
      const traceLayers=state.layers.filter(L=>L.name.startsWith('トレース'));
      if(traceLayers.length<2)return{err:'トレースレイヤー2枚未満'};
      const src=traceLayers[0].id,dst=traceLayers[1].id;
      state.activeLayer=src;
      const before=state.layers.length;
      mergeLayerInto(src,dst);
      const dstPaths=state.paths.filter(p=>p.layerId===dst);
      const fills=[...new Set(dstPaths.map(p=>p.fill))];
      return {before,after:state.layers.length,fills:fills.length,srcRemains:state.layers.some(L=>L.id===src)};
    })())"""))
    if merged.get("err"): fails.append(f"MERGE: {merged}")
    else:
        if merged["after"] != merged["before"] - 1: fails.append(f"MERGE: レイヤーが1減るはず: {merged}")
        if merged["fills"] != 1: fails.append(f"MERGE: 統合先の塗りは1色のはず: {merged}")
        if merged["srcRemains"]: fails.append(f"MERGE: 統合元レイヤーが残っている: {merged}")
    undone = json.loads(ev(sock, """JSON.stringify((()=>{
      undo();return {layers:state.layers.length};})())"""))
    if merged.get("before") and undone["layers"] != merged["before"]:
        fails.append(f"MERGE: undoで統合前に戻るはず: {undone} vs before={merged['before']}")

    # 5) 線端効果: 抜き=端の幅が絞られる／掠れ=毛束パーツが増える／丸=キャップ弧がある
    cap = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const mk=()=>({id:nextId++,closed:false,fill:'none',stroke:'#121212',width:24,layerId:state.activeLayer,
        nodes:[node(100,400),node(400,300),node(700,400)].map((n,i)=>n)});
      const plain=mk(),tap=mk(),kas=mk();
      tap.capFx={start:'taper',end:'taper',len:60};
      kas.capFx={start:'none',end:'kasure',len:60};
      state.paths.push(plain,tap,kas);render();
      const outline=p=>widthOutlineParts(p);
      const oPlain=outline(plain),oTap=outline(tap),oKas=outline(kas);
      // 先端アンカー(100,400)から輪郭までの最短距離: 丸キャップ≈半幅12 / 抜き≈0
      const minDist=o=>{let m=1e9;o.forEach(part=>part.nodes.forEach(n=>{m=Math.min(m,Math.hypot(n.x-100,n.y-400));}));return m;};
      return {plainParts:oPlain.length,tapParts:oTap.length,kasParts:oKas.length,
        plainTip:Math.round(minDist(oPlain)*10)/10,tapTip:Math.round(minDist(oTap)*10)/10,
        hasCapPlain:hasCapFx(plain),hasCapTap:hasCapFx(tap)};
    })())"""))
    if cap["kasParts"] < cap["plainParts"] + 3: fails.append(f"CAP: 掠れは毛束パーツが増えるはず: {cap}")
    if not (cap["plainTip"] > 8 and cap["tapTip"] < 2): fails.append(f"CAP: 抜きの先端はアンカーに収束するはず: {cap}")
    if cap["hasCapPlain"] or not cap["hasCapTap"]: fails.append(f"CAP: hasCapFx判定が変: {cap}")
    # 筆（起筆）: 水平線の始端で「基準幅より膨らむ」＋「中心が法線方向にずれて非対称」
    fude = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const p={id:nextId++,closed:false,fill:'none',stroke:'#121212',width:24,layerId:state.activeLayer,
        nodes:[node(100,400),node(700,400)],capFx:{start:'fude',end:'none',len:60}};
      state.paths.push(p);render();
      const o=widthOutlineParts(p);
      let above=0,below=0;      // 始端付近(x<180)の中心線からの張り出し
      let mid=0;                // 効果範囲外(x 300-500)の半幅
      o[0].nodes.forEach(n=>{
        if(n.x<180){above=Math.max(above,400-n.y);below=Math.max(below,n.y-400);}
        if(n.x>300&&n.x<500)mid=Math.max(mid,Math.abs(n.y-400));
      });
      return {above:Math.round(above*10)/10,below:Math.round(below*10)/10,mid:Math.round(mid*10)/10};
    })())"""))
    if not (max(fude["above"], fude["below"]) > fude["mid"] * 1.15):
        fails.append(f"FUDE: 打ち込みは基準幅より膨らむはず: {fude}")
    if abs(fude["above"] - fude["below"]) < 3:
        fails.append(f"FUDE: 打ち込みは中心がずれて非対称のはず: {fude}")
    if not (11 < fude["mid"] < 13.5):
        fails.append(f"FUDE: 効果範囲外の幅は基準(半幅12)のまま: {fude}")
    ev(sock, "state.paths=[];render();true")

    # 6) openDocumentがPromiseを返す
    is_promise = ev(sock, "openDocument(new File(['<svg></svg>'],'t.svg',{type:'image/svg+xml'})) instanceof Promise")
    if not is_promise: fails.append("OPEN: openDocumentがPromiseを返さない")

    # 6) 汎用SVG読み込み: 穴（複数サブパス）・開いた線・円・曲線・継承した色/線幅が図形として入る
    ev(sock, "state.paths=[];render();true")
    g = json.loads(ev(sock, """(async()=>{
      const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
       +'<g stroke="none"><path fill="#aabbcc" d="M10 10L90 10L90 90L10 90Z"/>'
       +'<path fill="#8899aa" d="M20 20L40 20L40 40L20 40ZM25 25L35 25L35 35L25 35Z"/></g>'
       +'<g fill="none" stroke="#0d1117" stroke-width="1.2"><path d="M10 10L90 10L90 30"/></g>'
       +'<circle cx="50" cy="50" r="10" fill="#ff0000"/>'
       +'<path d="M0 0C10 0 20 10 20 20" fill="none" stroke="#000000"/>'
       +'<path d="M0 40A10 10 0 0 1 20 40" fill="none" stroke="#000000"/></svg>';
      await openDocument(new File([svg],'generic.svg',{type:'image/svg+xml'}));
      const flat=p=>(p.subpaths?p.subpaths.flatMap(q=>q.nodes):p.nodes)||[];
      return JSON.stringify({
        n:state.paths.length,
        holes:state.paths.some(p=>p.subpaths&&p.subpaths.length===2),
        open:state.paths.some(p=>!p.closed&&!p.subpaths),
        red:state.paths.some(p=>p.fill==='#ff0000'),
        edgeStroke:state.paths.some(p=>p.stroke==='#0d1117'&&Math.abs(p.width-1.2)<.01),
        curved:state.paths.some(p=>flat(p).some(nd=>nd.outX!==nd.x||nd.outY!==nd.y))});
    })()""", await_promise=True))
    if g["n"] != 6: fails.append(f"IMPORT: パス6個のはず: {g}")
    for k in ("holes", "open", "red", "edgeStroke", "curved"):
        if not g.get(k): fails.append(f"IMPORT: {k} が成立しない: {g}")
    # 6a) PictureKitの「輪郭をSVGでコピー」→⌘Vで線だけの編集可能パスになる
    pasted = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const text='<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
       +'<path d="M 8 8 C 30 8 66 8 88 8 C 88 30 88 66 88 88 C 66 88 30 88 8 88 C 8 66 8 30 8 8 Z" '
       +'fill="none" stroke="#121212" stroke-width="2"/></svg>';
      const dt=new DataTransfer();dt.setData('text/plain',text);
      document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
      const p=state.paths[0],nodes=p?(p.subpaths?p.subpaths[0].nodes:p.nodes):[];
      return {n:state.paths.length,closed:p&&p.closed,fill:p&&p.fill,
        stroke:p&&p.stroke,width:p&&p.width,
        curved:nodes.some(n=>n.inX!==n.x||n.outX!==n.x),
        status:document.getElementById('status').textContent};
    })())"""))
    if not (pasted["n"] == 1 and pasted["closed"] and pasted["fill"] == "none"
            and pasted["stroke"] == "#121212" and pasted["width"] == 2
            and pasted["curved"] and "クリップボード.svg" in pasted["status"]):
        fails.append(f"PASTE-SVG: PictureKit輪郭SVGを編集可能な線で受け取れない: {pasted}")
    # 6b) CadKit撮影SVGの実物が開ける（面=塗り・線=ストロークが大量に入る）
    real = json.loads(ev(sock, """(async()=>{
      state.paths=[];
      const r=await fetch('cadkit-shot.svg');const t=await r.text();
      await openDocument(new File([t],'cadkit-shot.svg',{type:'image/svg+xml'}));
      return JSON.stringify({n:state.paths.length,
        filled:state.paths.filter(p=>p.fill&&p.fill!=='none').length,
        stroked:state.paths.filter(p=>p.stroke&&p.stroke!=='none').length});
    })()""", await_promise=True, timeout=300))
    if real["n"] < 300 or real["filled"] < 100 or real["stroked"] < 100:
        fails.append(f"IMPORT: cadkit-shot.svgの取り込みが少なすぎ: {real}")
    ev(sock, "state.paths=[];render();true")

    # 7) 同じ属性で選択: 塗り/線色/太さ/見た目・非表示レイヤー除外・同レイヤー限定
    same = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.dims=[];
      state.layers=[{id:1,name:'L1',visible:true},{id:2,name:'L2',visible:true},{id:3,name:'L3',visible:false}];
      state.activeLayer=1;
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const mk=(fill,stroke,width,layerId)=>{const p={id:nextId++,nodes:[nd(0,0),nd(10,0),nd(10,10)],closed:true,fill,stroke,width,layerId};state.paths.push(p);return p;};
      const A=mk('#ff0000','#000000',1,1);
      mk('#ff0000','#000000',3,2);      // B: 同塗り・別レイヤー・太さ違い
      mk('#00ff00','#000000',1,1);      // C: 別塗り・同太さ
      mk('#ff0000','#000000',1,3);      // D: 同塗りだが非表示レイヤー
      state.selectedPaths=[A.id];state.selectedPath=A.id;
      setTool('pen'); // 選択ツールに自動で切り替わるかも見る
      document.getElementById('sameScope').checked=false;
      selectSame('fill');   const fillN=state.selectedPaths.length,tool=state.tool;
      document.getElementById('sameScope').checked=true;
      selectSame('fill');   const fillLayerN=state.selectedPaths.length;
      document.getElementById('sameScope').checked=false;
      selectSame('width');  const widthN=state.selectedPaths.length;
      selectSame('stroke'); const strokeN=state.selectedPaths.length;
      selectSame('appearance'); const appN=state.selectedPaths.length;
      return {fillN,fillLayerN,widthN,strokeN,appN,tool};
    })())"""))
    expect = {"fillN": 2, "fillLayerN": 1, "widthN": 2, "strokeN": 3, "appN": 1, "tool": "select"}
    for k, v in expect.items():
        if same.get(k) != v: fails.append(f"SAME: {k} は {v} のはず: {same}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;render();true")

    # 8) ペンで選択中の線をクリック=アンカー追加＋そのままドラッグで移動（隣の点は動かない）
    pen = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.dims=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const tri={id:nextId++,nodes:[nd(100,100),nd(300,100),nd(200,250)],closed:true,fill:'#edf2f4',stroke:'#183251',width:1,layerId:1};
      state.paths.push(tri);state.selectedPaths=[tri.id];state.selectedPath=tri.id;
      setTool('pen');render();
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      const elp=art.querySelector('.drawn[data-id="'+tri.id+'"]');
      elp.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:7,isPrimary:true,button:0,...cl(200,100)}));
      const afterDown={n:tri.nodes.length,dragType:state.drag&&state.drag.type};
      svg.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:7,isPrimary:true,...cl(200,60)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:7,isPrimary:true,...cl(200,60)}));
      const nn=tri.nodes[1];
      const out={afterDown,moved:[Math.round(nn.x),Math.round(nn.y)],
        neighbors:[tri.nodes[0],tri.nodes[2]].map(q=>Math.round(q.x)+','+Math.round(q.y)),
        closed:tri.closed,total:tri.nodes.length,draft:!!state.draft};
      undo();
      out.undoN=pathById(tri.id)?pathById(tri.id).nodes.length:-1;
      state.paths=[];render();
      return out;
    })())"""))
    if pen["afterDown"] != {"n": 4, "dragType": "node"}: fails.append(f"PEN: 線クリックでアンカーが増えてnodeドラッグになるはず: {pen}")
    if pen["moved"] != [200, 60]: fails.append(f"PEN: 追加点がドラッグ先(200,60)にあるはず: {pen}")
    if pen["neighbors"] != ["100,100", "300,100"]: fails.append(f"PEN: 隣の点は動かないはず: {pen}")
    if not pen["closed"] or pen["total"] != 4 or pen["draft"]: fails.append(f"PEN: 閉じたまま4点・新規描画は始まらないはず: {pen}")
    if pen["undoN"] != 3: fails.append(f"PEN: undoで3点に戻るはず: {pen}")

    # 9) 単純化: 高密度ポリライン円→アンカー激減・真円度維持、開いたサイン波→端点固定で削減
    simp = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.dims=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;
      const circ={id:nextId++,nodes:Array.from({length:72},(_,i)=>{const th=i/72*2*Math.PI;
        return{x:400+150*Math.cos(th),y:300+150*Math.sin(th),inX:400+150*Math.cos(th),inY:300+150*Math.sin(th),outX:400+150*Math.cos(th),outY:300+150*Math.sin(th)};}),
        closed:true,fill:'#edf2f4',stroke:'#183251',width:1,layerId:1};
      const sine={id:nextId++,nodes:Array.from({length:101},(_,i)=>{const x=100+i*4,y=300+40*Math.sin((x-100)/40);
        return{x,y,inX:x,inY:y,outX:x,outY:y};}),closed:false,fill:'none',stroke:'#183251',width:1,layerId:1};
      state.paths.push(circ,sine);
      state.selectedPaths=[circ.id,sine.id];state.selectedPath=sine.id;
      document.getElementById('simplifyTol').value='1';
      simplifySelection();
      const bez=(a,b,t)=>{const u=1-t;return[u*u*u*a.x+3*t*u*u*a.outX+3*t*t*u*b.inX+t*t*t*b.x,
        u*u*u*a.y+3*t*u*u*a.outY+3*t*t*u*b.inY+t*t*t*b.y];};
      const rs=[];const cn=circ.nodes;
      for(let i=0;i<cn.length;i++){const a=cn[i],b=cn[(i+1)%cn.length];
        for(let t=0;t<1;t+=.125){const q=bez(a,b,t);rs.push(Math.hypot(q[0]-400,q[1]-300));}}
      const sn=sine.nodes;
      return {circN:cn.length,rSpread:Math.max(...rs)-Math.min(...rs),
        sineN:sn.length,endsKept:sn[0].x===100&&sn[sn.length-1].x===500};
    })())"""))
    if simp["circN"] >= 20: fails.append(f"SIMP: 円72点が20未満になるはず: {simp}")
    if simp["rSpread"] > 4: fails.append(f"SIMP: 単純化後も真円度を保つはず(半径ぶれ4px以下): {simp}")
    if simp["sineN"] >= 30 or not simp["endsKept"]: fails.append(f"SIMP: サイン波101点が30未満・端点固定のはず: {simp}")

    # 10) スムーズツール: ジグザグをなぞると振幅が減る・端点固定・undoで戻る
    smo = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      const zig={id:nextId++,nodes:Array.from({length:21},(_,i)=>{const x=100+i*10,y=200+(i%2?12:-12);
        return{x,y,inX:x,inY:y,outX:x,outY:y};}),closed:false,fill:'none',stroke:'#183251',width:2,layerId:1};
      state.paths.push(zig);state.selectedPaths=[zig.id];state.selectedPath=zig.id;
      setTool('smooth');render();
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      for(let pass=0;pass<3;pass++){
        svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:9,isPrimary:true,button:0,...cl(105,200)}));
        for(let x=110;x<=290;x+=5)svg.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:9,isPrimary:true,...cl(x,200)}));
        svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:9,isPrimary:true,...cl(290,200)}));
      }
      const dev=zig.nodes.slice(1,-1).map(n=>Math.abs(n.y-200));
      const out={maxDev:Math.max(...dev),ends:zig.nodes[0].y===188&&zig.nodes[20].y===188,
        smoothHandles:zig.nodes.slice(1,-1).some(n=>n.outX!==n.x)};
      undo();undo();undo();
      const z2=pathById(zig.id);
      out.undoDev=Math.max(...z2.nodes.slice(1,-1).map(n=>Math.abs(n.y-200)));
      return out;
    })())"""))
    if smo["maxDev"] > 6: fails.append(f"SMOOTH: 3回なぞって振幅12→6未満のはず: {smo}")
    if not smo["ends"] or not smo["smoothHandles"]: fails.append(f"SMOOTH: 端点固定＋ハンドル付与のはず: {smo}")
    if smo["undoDev"] != 12: fails.append(f"SMOOTH: undoで元のジグザグに戻るはず: {smo}")

    # 11) クリッピングマスク: 最前面がマスクになり、DOMにclipPath・書き出しにも入る。解除で外れる
    clip = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const photo={id:nextId++,nodes:[nd(100,100),nd(300,100),nd(300,200),nd(100,200)],closed:true,fill:'#d81616',stroke:'none',width:1,layerId:1};
      const frame={id:nextId++,nodes:[nd(150,120),nd(250,120),nd(250,180),nd(150,180)],closed:true,fill:'#21537f',stroke:'none',width:1,layerId:1};
      state.paths.push(photo,frame);
      state.selectedPaths=[photo.id,frame.id];state.selectedPath=frame.id;
      makeClipMask();
      const memberEl=art.querySelector('.drawn[data-id="'+photo.id+'"]');
      const out={maskFlag:!!frame.clipMask,maskFill:frame.fill,clipBy:photo.clipBy,
        grouped:!!photo.groupId&&photo.groupId===frame.groupId,
        domClip:memberEl?memberEl.getAttribute('clip-path'):null,
        defHasClip:!!svg.querySelector('defs clipPath'),
        exportHasClip:String(buildExportSvg(false)).includes('<clipPath')};
      releaseClipMask();
      out.released=!photo.clipBy&&!frame.clipMask;
      return out;
    })())"""))
    if not clip["maskFlag"] or clip["maskFill"] != "none": fails.append(f"CLIP: 最前面がマスク（塗りなし）になるはず: {clip}")
    if not clip["grouped"] or not clip["domClip"] or not clip["defHasClip"]: fails.append(f"CLIP: グループ化＋clip-path属性＋defsが付くはず: {clip}")
    if not clip["exportHasClip"]: fails.append(f"CLIP: SVG書き出しにclipPathが入るはず: {clip}")
    if not clip["released"]: fails.append(f"CLIP: 解除でclipBy/clipMaskが消えるはず: {clip}")

    # 12) ロック: クリックしても選択されない（pointer-events:none）・全選択から除外・全解除で戻る
    lock = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const A={id:nextId++,nodes:[nd(100,100),nd(200,100),nd(200,160),nd(100,160)],closed:true,fill:'#d81616',stroke:'none',width:1,layerId:1};
      const B={id:nextId++,nodes:[nd(300,100),nd(400,100),nd(400,160),nd(300,160)],closed:true,fill:'#21537f',stroke:'none',width:1,layerId:1};
      state.paths.push(A,B);
      state.selectedPaths=[A.id];state.selectedPath=A.id;
      lockSelection();
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      const hitEl=document.elementFromPoint(cl(150,130).clientX,cl(150,130).clientY);
      const out={locked:!!A.locked,selCleared:state.selectedPaths.length===0,
        pe:getComputedStyle(art.querySelector('.drawn[data-id="'+A.id+'"]')).pointerEvents,
        clickThrough:!(hitEl&&hitEl.dataset&&+hitEl.dataset.id===A.id)};
      state.selectedPaths=[B.id];state.selectedPath=B.id;
      document.getElementById('sameScope').checked=false;
      selectSame('width'); // A,Bとも太さ1だがAはロック中
      out.sameN=state.selectedPaths.length;
      unlockAll();
      out.unlocked=!A.locked;
      return out;
    })())"""))
    if not lock["locked"] or not lock["selCleared"]: fails.append(f"LOCK: ロック＋選択解除のはず: {lock}")
    if lock["pe"] != "none" or not lock["clickThrough"]: fails.append(f"LOCK: ロック中はクリックが素通りするはず: {lock}")
    if lock["sameN"] != 1: fails.append(f"LOCK: 同属性選択からロック中は除外のはず: {lock}")
    if not lock["unlocked"]: fails.append(f"LOCK: 全解除で戻るはず: {lock}")

    # 13) アウトライン表示: 画面は骨格描画・書き出しは通常のまま
    outl = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      state.paths.push({id:nextId++,nodes:[nd(100,100),nd(200,100),nd(200,160)],closed:true,fill:'#d81616',stroke:'none',width:1,layerId:1});
      toggleOutline();
      const p=art.querySelector('.drawn');
      const out={fill:p.getAttribute('fill'),stroke:p.getAttribute('stroke'),
        exportKeeps:String(buildExportSvg(false)).includes('#d81616')};
      out.segOn=document.getElementById('viewOutline').classList.contains('on');
      out.underlayDim=document.getElementById('underlay').style.opacity;
      toggleOutline();
      out.back=art.querySelector('.drawn').getAttribute('fill');
      out.segBack=document.getElementById('viewPreview').classList.contains('on');
      // ヘッダーのトグルボタンで切替（クリック操作）
      document.getElementById('viewOutline').click();
      out.byClick=art.querySelector('.drawn').getAttribute('fill')==='none';
      // ⌘Y（イラレ流）で戻る・⇧⌘Zはredoのまま。keydownはdocumentに付いているのでdocumentへ投げる
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'y',metaKey:true,bubbles:true}));
      out.byCmdY=art.querySelector('.drawn').getAttribute('fill')==='#d81616';
      setOutlineView(false); // 後続テストへ表示モードを持ち越さない
      state.paths=[];render();
      return out;
    })())"""))
    if outl["fill"] != "none" or outl["stroke"] != "#5e5e5e": fails.append(f"OUTLINE: 骨格表示になるはず: {outl}")
    if not outl["exportKeeps"] or outl["back"] != "#d81616": fails.append(f"OUTLINE: 書き出しは通常・トグルで戻るはず: {outl}")
    if not outl["segOn"] or not outl["segBack"]: fails.append(f"OUTLINE: ヘッダーのプレビュー/アウトライン表示が連動しないはず: {outl}")
    if outl["underlayDim"] not in ("0.25", ".25"): fails.append(f"OUTLINE: 下絵は薄く残すはず: {outl}")
    if not outl["byClick"] or not outl["byCmdY"]: fails.append(f"OUTLINE: ボタンクリック・⌘Yで切替できるはず: {outl}")

    # 14) 幅ツール: 線上ドラッグで幅ポイント追加→太さ60px・DOMは塗りアウトライン・Option+クリックで削除
    wid = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const line={id:nextId++,nodes:[nd(100,300),nd(500,300)],closed:false,fill:'none',stroke:'#183251',width:2,layerId:1};
      state.paths.push(line);state.selectedPaths=[line.id];state.selectedPath=line.id;
      setTool('width');render();
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:11,isPrimary:true,button:0,...cl(300,300)}));
      svg.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:11,isPrimary:true,...cl(300,270)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:11,isPrimary:true,...cl(300,270)}));
      const wp=line.widthPts&&line.widthPts[0];
      const strokeEl=art.querySelector('g.drawn path');
      const bb=strokeEl?strokeEl.getBBox():{height:0};
      const out={n:line.widthPts?line.widthPts.length:0,w:wp?wp.w:0,u:wp?Math.round(wp.u*100)/100:-1,
        outlineH:Math.round(bb.height),grouped:!!art.querySelector('g.drawn[data-id="'+line.id+'"]'),
        exportFilled:String(buildExportSvg(false)).includes('fill="#183251"')};
      // Option+クリックでハンドル(300,270)を削除
      svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:12,isPrimary:true,button:0,altKey:true,...cl(300,270)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:12,isPrimary:true,altKey:true,...cl(300,270)}));
      out.deleted=!line.widthPts;
      return out;
    })())"""))
    if wid["n"] != 1 or not (58 <= wid["w"] <= 62) or wid["u"] != 0.5: fails.append(f"WIDTH: ドラッグで幅60のポイントがu=0.5に付くはず: {wid}")
    if not (58 <= wid["outlineH"] <= 62) or not wid["grouped"]: fails.append(f"WIDTH: 塗りアウトライン描画（高さ60・gグループ）のはず: {wid}")
    if not wid["exportFilled"]: fails.append(f"WIDTH: 書き出しに線色の塗りパスが入るはず: {wid}")
    if not wid["deleted"]: fails.append(f"WIDTH: Option+クリックで幅ポイント削除のはず: {wid}")

    # 15) シェイプビルダー: 2矩形→3領域に分割→なぞって2領域合体→Option+クリックで削除
    bld = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const A={id:nextId++,nodes:[nd(100,100),nd(300,100),nd(300,200),nd(100,200)],closed:true,fill:'#d81616',stroke:'none',width:1,layerId:1};
      const B={id:nextId++,nodes:[nd(200,150),nd(400,150),nd(400,250),nd(200,250)],closed:true,fill:'#21537f',stroke:'none',width:1,layerId:1};
      state.paths.push(A,B);
      state.selectedPaths=[A.id,B.id];state.selectedPath=B.id;
      setTool('builder'); // ここで自動分割
      const out={regions:state.paths.length,
        reds:state.paths.filter(p=>p.fill==='#d81616').length,
        blues:state.paths.filter(p=>p.fill==='#21537f').length};
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      // A−B(赤)から∩(青)へなぞって合体
      svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:13,isPrimary:true,button:0,...cl(150,120)}));
      for(const [x,y] of [[200,140],[250,175]])svg.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:13,isPrimary:true,...cl(x,y)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:13,isPrimary:true,...cl(250,175)}));
      out.afterMerge=state.paths.length;
      const merged=pathById(state.selectedPath);
      const bb=merged?bboxOfPath(merged):null;
      out.mergedFill=merged?merged.fill:null;
      out.mergedBox=bb?[Math.round(bb.l),Math.round(bb.t),Math.round(bb.r),Math.round(bb.b)]:null;
      // 残ったB−AをOption+クリックで削除
      svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:14,isPrimary:true,button:0,altKey:true,...cl(350,225)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:14,isPrimary:true,altKey:true,...cl(350,225)}));
      out.afterDelete=state.paths.length;
      undo();undo();undo(); // 削除→合体→分割を全部戻す
      out.undoN=state.paths.length;
      state.paths=[];setTool('select');render();
      return out;
    })())"""))
    if bld["regions"] != 3 or bld["reds"] != 1 or bld["blues"] != 2: fails.append(f"BUILDER: 3領域（赤1・青2）に分割のはず: {bld}")
    if bld["afterMerge"] != 2 or bld["mergedFill"] != "#d81616": fails.append(f"BUILDER: 合体で2個・なぞり始めの色を継承のはず: {bld}")
    if bld["mergedBox"] != [100, 100, 300, 200]: fails.append(f"BUILDER: 合体形=元の矩形Aと同じ範囲のはず: {bld}")
    if bld["afterDelete"] != 1: fails.append(f"BUILDER: Option+クリックで領域削除のはず: {bld}")
    if bld["undoN"] != 2: fails.append(f"BUILDER: undo3回で元の2図形に戻るはず: {bld}")

    # 16) ロック図形を整列の基準に（FreeHand流）: Option+クリックで基準指定→整列で基準側だけに揃う
    anc = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const nd=(x,y)=>({x,y,inX:x,inY:y,outX:x,outY:y});
      const K={id:nextId++,nodes:[nd(400,300),nd(600,300),nd(600,400),nd(400,400)],closed:true,fill:'#edf2f4',stroke:'none',width:1,layerId:1,locked:true};
      const A={id:nextId++,nodes:[nd(100,100),nd(150,100),nd(150,130),nd(100,130)],closed:true,fill:'#d81616',stroke:'none',width:1,layerId:1};
      const B={id:nextId++,nodes:[nd(200,500),nd(280,500),nd(280,560),nd(200,560)],closed:true,fill:'#21537f',stroke:'none',width:1,layerId:1};
      state.paths.push(K,A,B);render();
      const m=svg.getScreenCTM();
      const cl=(x,y)=>({clientX:m.a*x+m.c*y+m.e,clientY:m.b*x+m.d*y+m.f});
      // ロックの上をOption+クリック→基準
      svg.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:15,isPrimary:true,button:0,altKey:true,...cl(500,350)}));
      svg.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:15,isPrimary:true,altKey:true,...cl(500,350)}));
      const out={anchorSet:alignAnchorId===K.id};
      state.selectedPaths=[A.id,B.id];state.selectedPath=B.id;
      alignSelection('l');alignSelection('cv');
      const ba=bboxOfPath(pathById(A.id)),bbx=bboxOfPath(pathById(B.id)),bk=bboxOfPath(pathById(K.id));
      out.aPos=[ba.l,Math.round((ba.t+ba.b)/2)];out.bPos=[bbx.l,Math.round((bbx.t+bbx.b)/2)];
      out.anchorStay=bk.l===400&&bk.t===300;
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
      out.escCleared=alignAnchorId===null;
      state.paths=[];render();
      return out;
    })())"""))
    if not anc["anchorSet"]: fails.append(f"ANCHOR: Option+クリックでロック図形が基準になるはず: {anc}")
    if anc["aPos"] != [400, 350] or anc["bPos"] != [400, 350]: fails.append(f"ANCHOR: 左揃え+上下中央で基準(400,300-600,400)に揃うはず: {anc}")
    if not anc["anchorStay"]: fails.append(f"ANCHOR: 基準は動かないはず: {anc}")
    if not anc["escCleared"]: fails.append(f"ANCHOR: Escで基準解除のはず: {anc}")

    # パレットポップオーバー: 塗りスウォッチクリック→現在のパレット36色が出る→色クリックで適用されて閉じる
    pal = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const p={id:nextId++,closed:true,fill:'#ffffff',stroke:'#121212',width:1,layerId:state.activeLayer,
        nodes:[node(100,100),node(200,100),node(200,200),node(100,200)]};
      state.paths.push(p);state.selectedPath=p.id;state.selectedPaths=[p.id];render();
      const inp=document.getElementById('fill');
      inp.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
      const pop=document.getElementById('palPop');
      const shown=pop.style.display!=='none';
      const swatches=pop.querySelectorAll('.pp').length;
      const first=pop.querySelector('.pp');
      const want=first?first.title:null;
      if(first)first.click();
      return {shown,swatches,applied:p.fill===want,closed:pop.style.display==='none',
        hasOs:!!pop.querySelector||true};
    })())"""))
    if not (pal["shown"] and pal["swatches"] == 36 and pal["applied"] and pal["closed"]):
        fails.append(f"PAL: ポップオーバー連携が壊れている: {pal}")
    ev(sock, "state.paths=[];render();true")

    # 17) 線のアピアランス: 線端(butt)・角(miter)・うねり（波線/ギザギザ・非破壊・書き出し反映）
    ap = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const p={id:nextId++,closed:false,fill:'none',stroke:'#121212',width:2,layerId:state.activeLayer,
        nodes:[node(100,400),node(500,400)]};
      state.paths.push(p);state.selectedPath=p.id;state.selectedPaths=[p.id];render();
      const out={};
      $('capStyle').value='butt';applyAppearance('capStyle');
      $('joinStyle').value='miter';applyAppearance('joinStyle');
      let elp=document.querySelector(`[data-id="${p.id}"]`);
      out.cap=elp.getAttribute('stroke-linecap');out.join=elp.getAttribute('stroke-linejoin');
      // 波線: 400px線に波長40・大きさ10 → 半波20個・C曲線20本・上下±10にふくらむ
      $('zigKind').value='smooth';$('zigAmp').value=10;$('zigLen').value=40;applyAppearance('zig');
      elp=document.querySelector(`[data-id="${p.id}"]`);
      const d=elp.getAttribute('d'),bb=elp.getBBox();
      out.curves=(d.match(/C/g)||[]).length;out.waveH=Math.round(bb.height);
      out.nodesKept=p.nodes.length===2&&p.nodes[0].y===400; // 骨格は非破壊
      // ギザギザ: 直線L だけになる
      $('zigKind').value='corner';applyAppearance('zig');
      const d2=document.querySelector(`[data-id="${p.id}"]`).getAttribute('d');
      out.zigL=(d2.match(/L/g)||[]).length;out.zigC=(d2.match(/C/g)||[]).length;
      // 書き出しにも線端と波が乗る
      $('zigKind').value='smooth';applyAppearance('zig');
      const ex=buildExportSvg(false);
      out.exportOk=ex.includes('stroke-linecap="butt"')&&(ex.match(/ C /g)||[]).length>10;
      $('zigKind').value='none';applyAppearance('zig');out.cleared=!p.zig;
      state.paths=[];render();
      return out;
    })())"""))
    if ap["cap"] != "butt" or ap["join"] != "miter": fails.append(f"APPEAR: 線端butt・角miterが属性に出るはず: {ap}")
    if not (15 <= ap["curves"] <= 25) or not (16 <= ap["waveH"] <= 24): fails.append(f"APPEAR: 波線=C曲線約20本・高さ約20pxのはず: {ap}")
    if not ap["nodesKept"]: fails.append(f"APPEAR: うねりは非破壊（元アンカー不変）のはず: {ap}")
    if ap["zigC"] != 0 or not (15 <= ap["zigL"] <= 25): fails.append(f"APPEAR: ギザギザ=L線分のみ約20本のはず: {ap}")
    if not ap["exportOk"]: fails.append(f"APPEAR: SVG書き出しに線端と波が乗るはず: {ap}")
    if not ap["cleared"]: fails.append(f"APPEAR: なしでzigが消えるはず: {ap}")

    # 18) CadKit用コピー: 選択なし=全図形、選択あり=選択のみのSVGテキストが組めること
    #     （クリップボード自体はヘッドレスで書けないので、コピー内容を組むbuildPathsSvgを直接検証）
    cad = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const a={id:nextId++,closed:true,fill:'#88aa66',stroke:'#333333',width:2,layerId:state.activeLayer,
        nodes:[node(100,100),node(300,100),node(300,250),node(100,250)]};
      const b={id:nextId++,closed:true,fill:'#4466aa',stroke:'none',width:1,layerId:state.activeLayer,
        nodes:[node(400,100),node(520,100),new (function(){const n=node(460,220);n.inX=520;n.inY=200;return n;})()]};
      state.paths.push(a,b);render();
      const all=buildPathsSvg(visiblePathsInOrder());
      state.selectedPaths=[a.id];state.selectedPath=a.id;
      const sel=buildSelectionSvg();
      const m=('x'+all.text).match(/<svg[\\s\\S]*?<\\/svg>/i); // CadKit側の抽出regexと同じ
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return {allPaths:(all.text.match(/<path/g)||[]).length,
        selPaths:(sel.text.match(/<path/g)||[]).length,
        hasCurve:all.text.includes(' C '),extractOk:!!m&&m[0].startsWith('<svg')&&m[0].endsWith('</svg>'),
        viewBoxOk:all.text.includes('viewBox=')};
    })())"""))
    if cad["allPaths"] != 2 or cad["selPaths"] != 1:
        fails.append(f"CADCOPY: 全図形=2パス・選択=1パスのはず: {cad}")
    if not (cad["hasCurve"] and cad["extractOk"] and cad["viewBoxOk"]):
        fails.append(f"CADCOPY: 曲線C・viewBox・CadKit側regex抽出が通るはず: {cad}")

    # 19) 再配色: 使用色を集める（グラデは開始/終了で別行）→入れ替えで赤い花が青に・葉は不変・undoで戻る
    rec = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;setTool('select');
      const mk=(fill,stroke,extra)=>{const p={id:nextId++,closed:true,fill,stroke,width:2,layerId:state.activeLayer,
        nodes:[node(100,100),node(200,100),node(200,200),node(100,200)],...extra};state.paths.push(p);return p;};
      const petal1=mk('#d81616','#7f1d1d');
      const petal2=mk('#d81616','#7f1d1d',{gradient:{c1:'#d81616',c2:'#F5A3A3',angle:0}}); // c2は大文字hex=正規化も見る
      const leaf=mk('#276749','none');
      render();
      document.getElementById('recolorCollect').click();
      const rows=[...document.querySelectorAll('#recolorList .rrow')];
      const labels=rows.map(r=>r.querySelector('.cnt').textContent);
      // 左スウォッチクリック=その色の図形を選択（葉は入らない）
      rows.find(r=>r.querySelector('input').dataset.old==='#d81616').querySelector('.old').click();
      const selRed=[...state.selectedPaths].sort();
      // 赤→青・淡赤→淡青に指定して入れ替え（葉の緑は据え置き）
      const setNew=(from,to)=>{const i=rows.find(r=>r.querySelector('input').dataset.old===from).querySelector('input');i.value=to;};
      setNew('#d81616','#2b6cb0');setNew('#f5a3a3','#90cdf4');
      document.getElementById('recolorApply').click();
      const after={p1:petal1.fill,g1:petal2.gradient.c1,g2:petal2.gradient.c2,gfill:petal2.fill,
        leaf:leaf.fill,stroke:petal1.stroke,
        rows2:[...document.querySelectorAll('#recolorList .rrow input')].map(i=>i.dataset.old)};
      undo();
      const back={p1:pathById(petal1.id).fill,g2:pathById(petal2.id).gradient.c2};
      // スコープ: 葉だけ選択して集める→行は葉の色だけ
      state.selectedPaths=[leaf.id];state.selectedPath=leaf.id;
      document.getElementById('recolorCollect').click();
      const scopedRows=[...document.querySelectorAll('#recolorList .rrow input')].map(i=>i.dataset.old);
      document.getElementById('recolorClose').click();
      const closed=document.querySelectorAll('#recolorList .rrow').length===0;
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return {nRows:rows.length,labels,selRed,after,back,scopedRows,closed};
    })())"""))
    if rec["nRows"] != 4: fails.append(f"RECOLOR: 使用色4行（赤/濃赤/淡赤/緑）のはず: {rec['labels']}")
    if not any("グラデ始" in s for s in rec["labels"]) or not any("グラデ終" in s for s in rec["labels"]):
        fails.append(f"RECOLOR: グラデが開始/終了の行に出るはず: {rec['labels']}")
    if len(rec["selRed"]) != 2: fails.append(f"RECOLOR: 赤スウォッチクリックで花びら2個選択のはず: {rec['selRed']}")
    a = rec["after"]
    if not (a["p1"] == "#2b6cb0" and a["g1"] == "#2b6cb0" and a["g2"] == "#90cdf4" and a["gfill"] == "#2b6cb0"):
        fails.append(f"RECOLOR: 赤い花が青くなるはず（fill/グラデc1c2/gradient.c1とfillの同期）: {a}")
    if a["leaf"] != "#276749" or a["stroke"] != "#7f1d1d": fails.append(f"RECOLOR: 指定しない色は不変のはず: {a}")
    if "#2b6cb0" not in a["rows2"] or "#d81616" in a["rows2"]:
        fails.append(f"RECOLOR: 入れ替え後は行が新色で再構築されるはず: {a['rows2']}")
    if rec["back"] != {"p1": "#d81616", "g2": "#F5A3A3"}:  # 大文字hexはsnapshotどおり戻る
        fails.append(f"RECOLOR: undoで元に戻るはず: {rec['back']}")
    if rec["scopedRows"] != ["#276749"]: fails.append(f"RECOLOR: 選択して集めると対象は選択のみのはず: {rec['scopedRows']}")
    if not rec["closed"]: fails.append(f"RECOLOR: 閉じるで行が消えるはず")

    # 19b) パレットCSV往復: 書き出し=ヘッダー+全色+用途／読み込み=BOM・ヘッダー・未知色を読み飛ばして新色を反映
    csv = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;
      const mk=(fill,stroke)=>{state.paths.push({id:nextId++,closed:true,fill,stroke,width:2,layerId:state.activeLayer,
        nodes:[node(100,100),node(200,100),node(200,200),node(100,200)]});};
      mk('#d81616','#7f1d1d');mk('#276749','none');
      render();
      document.getElementById('recolorCollect').click();
      const text=buildRecolorCsv();
      // 未編集で読み込むと集めていない場合も行が立つ（collectIfEmpty）: いったん閉じて素の状態から
      document.getElementById('recolorClose').click();
      collectIfEmpty();
      const r=applyRecolorCsv('\\ufeff元色,新色,用途\\n#D81616,#2b6cb0,塗り1\\n#00ff00,#0000ff,\\nメモ行,,\\n');
      const val=[...document.querySelectorAll('#recolorList input')].find(i=>i.dataset.old==='#d81616').value;
      document.getElementById('recolorApply').click();
      const applied=state.paths[0].fill,leaf=state.paths[1].fill;
      undo();document.getElementById('recolorClose').click();
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();
      return {header:text.startsWith('元色,新色,用途'),lines:text.trim().split('\\n').length,
        hasUsage:text.includes('塗り1')&&text.includes('線1'),hit:r.hit,miss:r.miss,val,applied,leaf};
    })())"""))
    if not csv["header"] or csv["lines"] != 4 or not csv["hasUsage"]:
        fails.append(f"RECOLOR-CSV: ヘッダー+3色+用途列のはず: {csv}")
    if csv["hit"] != 1 or csv["miss"] != 1:
        fails.append(f"RECOLOR-CSV: 一致1（大文字hexも正規化）・未知1のはず: {csv}")
    if csv["val"] != "#2b6cb0" or csv["applied"] != "#2b6cb0" or csv["leaf"] != "#276749":
        fails.append(f"RECOLOR-CSV: 読み込み→入れ替えで赤だけ青になるはず: {csv}")

    # 20) パスのオフセット: 閉パスが外へ膨らむ／角の形が選べる／undoで戻る
    ev(sock, """(()=>{state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];
      state.activeLayer=1;state.selectedPaths=[];state.selectedPath=null;render();
      window.__mkRect=()=>{const r={id:nextId++,closed:true,fill:'#dddddd',stroke:'#121212',width:2,layerId:1,
        nodes:[node(200,200),node(400,200),node(400,340),node(200,340)]};state.paths.push(r);setSelection([r.id]);return r;};
      window.__bb=p=>{const parts=p.subpaths||[p];let l=1e9,t=1e9,r=-1e9,b=-1e9;
        for(const q of parts)for(const n of q.nodes){l=Math.min(l,n.x);t=Math.min(t,n.y);r=Math.max(r,n.x);b=Math.max(b,n.y);}
        return{l,t,r,b,w:r-l,h:b-t};};return true;})()""")
    off = json.loads(ev(sock, """JSON.stringify((()=>{
      document.getElementById('offsetJoin').value='round';
      document.getElementById('offsetCopy').checked=false;
      document.getElementById('offsetBoth').checked=false;
      const rect=window.__mkRect(),before=window.__bb(rect);
      offsetSelection(20);
      const grown=window.__bb(state.paths[0]);
      const undoneW=(()=>{undo();return window.__bb(state.paths[0]).w;})();
      return{paths:state.paths.length,dw:grown.w-before.w,dh:grown.h-before.h,undoneW,beforeW:before.w};
    })())"""))
    if off["paths"] != 1: fails.append(f"OFFSET: 破壊モードではパスは増えないはず: {off}")
    if not (35 <= off["dw"] <= 45 and 35 <= off["dh"] <= 45):
        fails.append(f"OFFSET: 20px外側で幅・高さが約40px増えるはず: {off}")
    if abs(off["undoneW"] - off["beforeW"]) > 0.5:
        fails.append(f"OFFSET: undoで元の形に戻るはず: {off}")

    # 21) 「元を残す」: 元パスが残り、内側オフセットが別パスとして増え、選択は新しい方
    offcopy = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      document.getElementById('offsetCopy').checked=true;
      const rect=window.__mkRect();
      offsetSelection(-15);
      const src=state.paths.find(p=>p.id===rect.id),made=state.paths.filter(p=>p.id!==rect.id);
      const res={paths:state.paths.length,srcKept:!!src,srcW:src?window.__bb(src).w:0,
        madeW:made.length?window.__bb(made[0]).w:0,
        selectedIsNew:state.selectedPaths.length===1&&state.selectedPaths[0]!==rect.id};
      document.getElementById('offsetCopy').checked=false;undo();
      res.afterUndo=state.paths.length;return res;})())"""))
    if not offcopy["srcKept"] or offcopy["paths"] != 2:
        fails.append(f"OFFSET-COPY: 元を残して2パスになるはず: {offcopy}")
    if not (abs(offcopy["srcW"] - 200) < 0.5 and 155 <= offcopy["madeW"] <= 185):
        fails.append(f"OFFSET-COPY: 元200px・内側15pxで約170pxのはず: {offcopy}")
    if not offcopy["selectedIsNew"]: fails.append(f"OFFSET-COPY: 新しい方が選択されるはず: {offcopy}")
    if offcopy["afterUndo"] != 1: fails.append(f"OFFSET-COPY: undoで1パスに戻るはず: {offcopy}")

    # 22) 文字は自動アウトライン化してからオフセット（従来は無視されていた）
    offtext = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const t={id:nextId++,type:'text',text:'▲',fill:'#121212',stroke:'none',width:1,layerId:1,
        x:200,y:380,size:100,fontKey:'noto-sans-r',
        cmds:[{type:'M',x:300,y:200},{type:'L',x:400,y:380},{type:'L',x:200,y:380},{type:'Z'}]};
      state.paths.push(t);setSelection([t.id]);
      offsetSelection(8);
      const p=state.paths[0],parts=p.subpaths||[p];
      return{paths:state.paths.length,stillText:p.type==='text',hasNodes:!!(parts[0]&&parts[0].nodes),
        closed:parts.every(s=>s.closed),h:window.__bb(p).h,status:document.getElementById('status').textContent};
    })())"""))
    if offtext["stillText"] or not offtext["hasNodes"]:
        fails.append(f"OFFSET-TEXT: 文字はパス化されるはず: {offtext}")
    if not offtext["closed"] or not (offtext["h"] > 180):
        fails.append(f"OFFSET-TEXT: 三角形(高さ180)が外へ膨らんだ閉パスになるはず: {offtext}")
    if "アウトライン化" not in offtext["status"]:
        fails.append(f"OFFSET-TEXT: 文字をパス化したことを知らせるはず: {offtext}")
    ev(sock, "undo()")

    # 23) 開いた線の「両側」: 片側ずれではなく線を囲む閉パスになる
    offboth = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];render();
      const line={id:nextId++,closed:false,fill:'none',stroke:'#121212',width:2,layerId:1,
        nodes:[node(200,500),node(500,500)]};
      state.paths.push(line);setSelection([line.id]);
      document.getElementById('offsetBoth').checked=false;
      offsetSelection(12);
      const one=(()=>{const p=state.paths[0],parts=p.subpaths||[p];
        return{closed:parts.every(s=>s.closed),h:window.__bb(p).h};})();
      undo();
      document.getElementById('offsetBoth').checked=true;
      setSelection([line.id]);offsetSelection(12);
      const both=(()=>{const p=state.paths[0],parts=p.subpaths||[p];
        return{closed:parts.every(s=>s.closed),h:window.__bb(p).h};})();
      document.getElementById('offsetBoth').checked=false;undo();
      return{one,both,status:document.getElementById('status').textContent};})())"""))
    if offboth["one"]["closed"]: fails.append(f"OFFSET-OPEN: 既定は開いた線のままのはず: {offboth}")
    if not offboth["both"]["closed"] or not (20 <= offboth["both"]["h"] <= 30):
        fails.append(f"OFFSET-OPEN: 両側ONで高さ約24pxの閉パスになるはず: {offboth}")

    # 24) 網点: 黒→赤→シアン→白のグラデ画像を読み込み、濃い側のドットが大きいこと
    ev(sock, """(()=>{
      state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;render();
      const cv=document.createElement('canvas');cv.width=800;cv.height=600;
      const ctx=cv.getContext('2d'),g=ctx.createLinearGradient(0,0,800,0);
      g.addColorStop(0,'#000000');g.addColorStop(.45,'#cc2222');g.addColorStop(.75,'#1199cc');g.addColorStop(1,'#ffffff');
      ctx.fillStyle=g;ctx.fillRect(0,0,800,600);
      window.__gradUrl=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{
      const r=await fetch(window.__gradUrl);const b=await r.blob();
      loadTraceImage(new File([b],'gradient.png',{type:'image/png'}));return true;})()""",
       await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('htRun').disabled"): break
        time.sleep(0.2)
    else:
        fails.append("HALFTONE: 画像読み込みで「網点にする」が有効にならない")
    ev(sock, "document.getElementById('htColor').value='#121212';true")
    do_halftone(sock, pitch=12, shape="circle", mode="am", ink="mono")
    ht = json.loads(ev(sock, HT_DOTS_JS))
    if ht["paths"] != 1 or ht["layers"] != 1:
        fails.append(f"HALFTONE: 網点レイヤー1枚・1パスにまとめるはず: {ht}")
    if ht["fillRule"] != "nonzero" or ht["stroke"] != "none" or ht["fill"] != "#121212":
        fails.append(f"HALFTONE: 塗り色の単色・線なし・nonzeroのはず: {ht}")
    if not (200 < ht["dots"] < 6000): fails.append(f"HALFTONE: ドット数が想定外: {ht}")
    if not (ht["darkR"] > ht["lightR"] * 1.3):
        fails.append(f"HALFTONE: 濃い側のドットが大きいはず: {ht}")
    svg_nonzero = ev(sock, "buildExportSvg(false).includes('fill-rule=\\\"nonzero\\\"')")
    if not svg_nonzero: fails.append("HALFTONE: 書き出しSVGにfill-rule=nonzeroが入るはず")
    ev(sock, "undo()")

    # 25) 網間隔を広げるとドットが減る／トーンモードはドットの大きさが一定
    do_halftone(sock, pitch=24, shape="circle", mode="am", ink="mono")
    coarse = json.loads(ev(sock, HT_DOTS_JS))
    ev(sock, "undo()")
    if not (coarse["dots"] < ht["dots"] / 2):
        fails.append(f"HALFTONE-PITCH: 網間隔24は12よりドットが大きく減るはず: {coarse} vs {ht}")
    do_halftone(sock, pitch=12, shape="circle", mode="tone", ink="mono")
    tone = json.loads(ev(sock, HT_DOTS_JS))
    ev(sock, "undo()")
    if tone["rMax"] - tone["rMin"] > 0.05:
        fails.append(f"HALFTONE-TONE: トーンはドットの大きさが一定のはず: {tone}")
    if not (100 < tone["dots"] < ht["dots"]):
        fails.append(f"HALFTONE-TONE: 濃いところだけ密に置くのでドット数は網点以下のはず: {tone} vs {ht}")

    # 26) CMYK4色版: C/M/Y/Kの4レイヤーに分かれ、それぞれ定番角度の網になる
    do_halftone(sock, pitch=16, shape="circle", mode="am", ink="cmyk")
    cmyk = json.loads(ev(sock, """JSON.stringify((()=>{
      const names=state.layers.filter(L=>L.name.startsWith('網点 ')).map(L=>L.name);
      const inks=state.paths.filter(p=>p.fillRule==='nonzero');
      return{layers:names,paths:inks.length,fills:inks.map(p=>p.fill),
        opacity:inks.every(p=>p.opacity>=.6&&p.opacity<=.9),
        dots:inks.map(p=>(p.subpaths||[p]).length)};})())"""))
    if sorted(cmyk["layers"]) != ["網点 C", "網点 K", "網点 M", "網点 Y"]:
        fails.append(f"HALFTONE-CMYK: C/M/Y/Kの4レイヤーになるはず: {cmyk}")
    if cmyk["paths"] != 4 or not cmyk["opacity"]:
        fails.append(f"HALFTONE-CMYK: 4版が半透明（0.6〜0.9）で重なるはず: {cmyk}")
    if any(d < 20 for d in cmyk["dots"]):
        fails.append(f"HALFTONE-CMYK: どの版にもドットが乗るはず: {cmyk}")
    ev(sock, "undo()")
    left = json.loads(ev(sock, """JSON.stringify((()=>({paths:state.paths.length}))())"""))
    if left["paths"] != 0: fails.append(f"HALFTONE-CMYK: undoで生成前に戻るはず: {left}")

    # 27) 紙色を抜く: 黄ばんだ地色の画像はONで地のドットが消え、絵柄だけ網点になる
    ev(sock, """(()=>{
      state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;render();
      const cv=document.createElement('canvas');cv.width=600;cv.height=400;
      const ctx=cv.getContext('2d');
      ctx.fillStyle='#efe3c0';ctx.fillRect(0,0,600,400);
      ctx.fillStyle='#101010';ctx.beginPath();ctx.arc(300,200,110,0,7);ctx.fill();
      window.__yellowUrl=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{
      const r=await fetch(window.__yellowUrl);const b=await r.blob();
      loadTraceImage(new File([b],'yellowed.png',{type:'image/png'}));return true;})()""",
       await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('htRun').disabled"): break
        time.sleep(0.2)
    do_halftone(sock, pitch=10, ink="mono", paper=False)
    raw = json.loads(ev(sock, HT_DOTS_JS)); ev(sock, "undo()")
    do_halftone(sock, pitch=10, ink="mono", paper=True)
    cleaned = json.loads(ev(sock, HT_DOTS_JS)); ev(sock, "undo()")
    if not (cleaned["dots"] < raw["dots"] * 0.6):
        fails.append(f"HALFTONE-PAPER: 紙色を抜くと地のドットが消えるはず: {cleaned} vs {raw}")

    # 28) PPTX: 確認の数・XMLの中身・python-pptxで開けて入れ子のグループと文字枠が数どおり
    ev(sock, PPTX_FIXTURE_JS)
    chk = json.loads(ev(sock, "JSON.stringify(pptxCheck())"))
    if (chk["shape"], chk["baked"], chk["text"], chk["lost"]) != (8, 3, 1, 0):
        fails.append(f"PPTX-CHECK: 図形のまま8・焼き3・文字枠1・出ない0のはず: {chk}")
    if not any("非表示" in x for x in chk["extra"]) or set(chk["notes"]) != {"幅ツール", "うねり", "マスク"}:
        fails.append(f"PPTX-CHECK: 非表示レイヤーと焼いた理由3種を出すはず: {chk}")
    xml = json.loads(ev(sock, """JSON.stringify((()=>{const r=buildPptxFiles({textBox:true,selectionOnly:false});
      const f=Object.fromEntries(r.files);const s=f['ppt/slides/slide1.xml'];
      const donut=resolvePrimitives(state.paths[3]).prims[0],o=orientParts(donut.parts,'evenodd');
      const d3=orientParts(resolvePrimitives(state.paths[4]).prims[0].parts,'nonzero');
      const rg=(s.match(/<a:gradFill[^>]*><a:gsLst>((?:(?!<\\/a:gsLst>).)*)<\\/a:gsLst><a:path path="circle">/)||[])[1]||'';
      const C=(cx,cy,r)=>{const k=.5523*r;return{closed:true,nodes:[{x:cx+r,y:cy,inX:cx+r,inY:cy-k,outX:cx+r,outY:cy+k},{x:cx,y:cy+r,inX:cx+k,inY:cy+r,outX:cx-k,outY:cy+r},{x:cx-r,y:cy,inX:cx-r,inY:cy+k,outX:cx-r,outY:cy-k},{x:cx,y:cy-r,inX:cx-k,inY:cy-r,outX:cx+k,outY:cy-r}]};};
      const many=orientParts(Array.from({length:450},(_,i)=>C(i*6,0,5)),'nonzero'),apart=orientParts([C(0,0,5),C(50,0,5)],'nonzero');
      const dots={multi:d3.parts.length===1&&!d3.multi&&many.multi&&!apart.multi};
      return{names:Object.keys(f).length,sz:f['ppt/presentation.xml'].match(/sldSz cx="(\\d+)" cy="(\\d+)"/).slice(1).map(Number),
        custGeom:(s.match(/<a:custGeom>/g)||[]).length,grad:/<a:gradFill[^>]*>.*<a:lin ang="5400000"/.test(s),dash:/<a:custDash><a:ds d="300000" sp="150000"\\/>/.test(s),
        alpha:/<a:alpha val="90000"\\/>/.test(s),tail:/<a:headEnd type="stealth" w="med" len="med"\\/><a:tailEnd type="stealth" w="med" len="med"\\/>/.test(s),
        radial:(rg.match(/<a:gs /g)||[]).length===3&&/^<a:gs pos="0"><a:srgbClr val="C62828"/.test(rg),
        fx:/<a:effectLst><a:outerShdw blurRad="152400" dist="114300" dir="2700000" algn="ctr" rotWithShape="0"><a:srgbClr val="121212"><a:alpha val="40000"\\/>/.test(s)
          &&/<a:glow rad="95250"><a:srgbClr val="FFD54F">/.test(s)&&/<a:softEdge rad="114300"\\/>/.test(s),
        svgFx:(()=>{render();const f=document.querySelector('#canvas filter[id^="fx-"]');const m=document.querySelector('#canvas marker path');
          return !!f&&!!document.querySelector('#canvas radialGradient stop:nth-child(3)')&&!!m&&m.getAttribute('d')===ARROW_SHAPE.stealth
            &&!!document.querySelector('#art [filter^="url(#fx-"]');})(),text:/<a:t>見出しの文字<\\/a:t>/.test(s)&&/b="1"/.test(s)&&/typeface="Noto Sans JP"/.test(s),
        layer:/name="前景"/.test(s)&&/name="背景"/.test(s)&&!/name="下書き"/.test(s),
        donutOpposite:Math.sign(polyArea(sampleNodesToPoly(o.parts[0])))!==Math.sign(polyArea(sampleNodesToPoly(o.parts[1]))),dotsMulti:dots.multi};})())"""))
    if xml["sz"] != [1280 * 9525, 720 * 9525]:
        fails.append(f"PPTX-XML: スライドは1280×720px＝12192000×6858000EMUのはず: {xml}")
    if not all(xml[k] for k in ("grad", "dash", "alpha", "tail", "radial", "fx", "svgFx", "text", "layer", "donutOpposite", "dotsMulti")) or xml["custGeom"] != 12:
        fails.append(f"PPTX-XML: グラデ（直線・放射3色）・破線・不透明度・矢印（鋭角・中）・影・光彩・ぼかし輪郭・画面のfilter・文字枠・レイヤー名・穴の巻き方向・重なる点・custGeom 12個のはず: {xml}")
    got = json.loads(ev(sock, PPTX_BLOB_JS % "true", await_promise=True))
    tmp = "/tmp/bk-pptx-check.pptx"
    with open(tmp, "wb") as f: f.write(base64.b64decode(got["b64"]))
    try:
        sh = pptx_shapes(tmp)
        if sh["free"] != 12 or len(sh["groups"]) != 4 or sh["text"] != ["見出しの文字\n二行目"] or "前景" not in sh["groups"]:
            fails.append(f"PPTX-OPEN: フリーフォーム12・グループ4（背景/前景/図形/グループ）・文字枠1のはず: {sh}")
    except Exception as err:
        fails.append(f"PPTX-OPEN: python-pptxで開けるはず: {err}")
    off = json.loads(ev(sock, PPTX_BLOB_JS % "false", await_promise=True))
    if off["stats"]["text"] != 0 or off["stats"]["baked"] != 4:
        fails.append(f"PPTX-TEXTOFF: 文字枠オフなら文字は形に焼くはず: {off['stats']}")

    # 29) AI／PDF読み込み: 手書きPDF（make_test_pdf）からレイヤー・穴あき・破線・グラデ・切り抜き・不透明度・文字が入る
    got = json.loads(ev(sock, PDF_IMPORT_JS % (json.dumps(base64.b64encode(make_test_pdf()).decode()), '"fixture.pdf"'), await_promise=True, timeout=300))
    pdf = json.loads(ev(sock, """JSON.stringify((()=>{const ps=state.paths,L=id=>(state.layers.find(l=>l.id===id)||{}).name;
      const donut=ps.find(p=>p.subpaths&&p.subpaths.length===2),grad=ps.find(p=>p.gradient),dash=ps.find(p=>p.dash),half=ps.find(p=>p.opacity===.5);
      const clipped=ps.find(p=>p.clipBy),mask=clipped&&pathById(clipped.clipBy),text=ps.find(isText);
      return{art:[ART.w,ART.h],layers:state.layers.map(l=>l.name),donut:donut&&[donut.fill,donut.fillRule,L(donut.layerId)],
        grad:grad&&[grad.gradient.c1,grad.gradient.c2,grad.gradient.angle],dash:dash&&[dash.dash,dash.width,dash.cap],half:half&&half.fill,
        mask:!!(mask&&mask.clipMask),text:text&&[text.text,L(text.layerId),text.size,text.cmds.length>0]};})())"""))
    exp_ok = (got["r"] and got["r"]["shapes"] == 5 and pdf["art"] == [600, 400] and pdf["layers"] == ["Back", "Front"]
              and pdf["donut"] == ["#c62828", "evenodd", "Back"] and pdf["grad"] == ["#21537f", "#9fc0dd", 90]
              and pdf["dash"] == ["10 5", 4, "round"] and pdf["half"] == "#21537f" and pdf["mask"]
              and pdf["text"] and pdf["text"][0] == "Hello World" and pdf["text"][1] == "Front" and pdf["text"][3])
    if not exp_ok:
        fails.append(f"PDF-IMPORT: レイヤー2・穴あき・グラデ・破線・不透明度・マスク・文字が入るはず: {got} {pdf}")
    # 30) PDF書き出し→自分で読み戻す: レイヤー名・直線と放射のグラデ・破線・不透明度・切り抜き・矢じり（形）・文字（形）が残る
    ev(sock, PPTX_FIXTURE_JS)
    out = json.loads(ev(sock, """(async()=>{const r=buildPdf({textBox:false,selectionOnly:false});
      const head=r.text.slice(0,8),bin=pdfBytes(r.text),before=state.paths.filter(p=>!p.clipMask&&state.layers.find(l=>l.id===p.layerId).visible).length;
      const back=await importPdfVector(new File([bin],'roundtrip.pdf',{type:'application/pdf'}),1);
      const ps=state.paths,g=ps.filter(p=>p.gradient);
      return JSON.stringify({head,pages:r.pages,before,back,layers:state.layers.map(l=>l.name),
        lin:g.some(p=>p.gradient.type!=='radial'&&p.gradient.angle===90),radial:g.some(p=>p.gradient.type==='radial'),
        dash:ps.some(p=>p.dash==='12 6'&&p.width===4),alpha:ps.some(p=>p.opacity===.9),mask:ps.some(p=>p.clipBy),
        stealth:ps.some(p=>p.fill==='#121212'&&p.stroke==='none'&&p.subpaths&&p.subpaths.length===2&&p.subpaths.every(s=>s.closed&&s.nodes.length===4))});})()""", await_promise=True, timeout=300))
    if not (out["head"] == "%PDF-1.6" and out["layers"] == ["背景", "前景"] and all(out[k] for k in ("lin", "radial", "dash", "alpha", "mask", "stealth"))
            and out["back"] and out["back"]["shapes"] >= out["before"]):
        fails.append(f"PDF-EXPORT: 書き出したPDFを読み戻してレイヤー名・グラデ2種・破線・不透明度・切り抜き・矢じりが残るはず: {out}")

    # 31) 複数アートボード: 3枚（3枚目だけ960×720）→PPTX3枚・PDF3ページ（各ページの大きさ）・外の図形は出ない・PDFを全ページで開き直すと3枚に戻る・undoで戻る
    ab = json.loads(ev(sock, """(async()=>{
      state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;state.artboards=null;state.activeArtboard=0;applyArtboard(1280,720);
      addArtboard();state.activeArtboard=1;addArtboard();setActiveArtboardSize(960,720);
      const list=artboardList().map(a=>({...a}));
      const R=(x,y,w,h,fill)=>{const o={id:nextId++,layerId:1,closed:true,fill,stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]};state.paths.push(o);return o;};
      R(100,100,200,100,'#21537f');R(list[1].x+100,100,200,100,'#c62828');R(list[2].x+100,100,200,100,'#10b981');R(-900,-900,50,50,'#000000');render();
      const chk=pptxCheck(),px=buildPptxFiles({textBox:true,selectionOnly:false}),f=Object.fromEntries(px.files);
      const off=s=>(s.match(/<p:sp>.*?<a:off x="(\\d+)" y="(\\d+)"/)||[]).slice(1).map(Number);
      const pdf=buildPdf({textBox:false,selectionOnly:false}),boxes=[...pdf.text.matchAll(/MediaBox \\[0 0 (\\S+) (\\S+)\\]/g)].map(m=>[+m[1],+m[2]]);
      undo();const afterUndo=artboardList().length;
      const back=await importPdfVector(new File([pdfBytes(pdf.text)],'ab.pdf',{type:'application/pdf'}),0);
      return JSON.stringify({list:list.map(a=>[a.x,a.w,a.h]),slides:px.slides,shrunk:px.shrunk,s2:off(f['ppt/slides/slide2.xml']),s3:off(f['ppt/slides/slide3.xml']),
        lost:chk.lost,outside:chk.notes['アートボードの外'],boxes,afterUndo,back:back&&back.artboards,shapes:back&&back.shapes,names:artboardList().map(a=>a.name)});})()""", await_promise=True, timeout=300))
    k3 = 720 / 720  # 960×720 は高さが同じなので縮めない（幅は1280以内）
    if not (ab["list"][1][0] == 1360 and ab["slides"] == 3 and ab["s2"] == [100 * 9525, 100 * 9525] and ab["s3"] == [round(100 * k3) * 9525, 100 * 9525]
            and ab["lost"] == 1 and ab["outside"] == 1 and ab["boxes"] == [[1280, 720], [1280, 720], [960, 720]]
            and ab["afterUndo"] == 2 and ab["back"] == 3 and ab["shapes"] == 3 and ab["names"] == ["1ページ", "2ページ", "3ページ"]):
        fails.append(f"ARTBOARDS: 3枚→PPTX3枚（原点合わせ）・PDF3ページ（大きさ別）・外の1個は出ない・undoで3枚目の追加が戻る・PDF全ページで3枚に戻るはず: {ab}")

    # 32) グローバルカラー: 塗りから作る→色を変えるとつないだ図形が全部変わる→手で色を変えた図形はつながりが外れる→PPTXはテーマの色＋schemeClr→undo
    sw = json.loads(ev(sock, """(()=>{
      state.paths=[];state.swatches=null;state.artboards=null;state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;applyArtboard(1280,720);
      const R=(x,fill,stroke)=>{const o={id:nextId++,layerId:1,closed:true,fill,stroke,width:4,nodes:[node(x,100),node(x+100,100),node(x+100,200),node(x,200)]};state.paths.push(o);return o;};
      const a=R(100,'#21537f','#121212'),b=R(300,'#21537f','#121212'),c=R(500,'#c62828','#121212');render();
      setSelection([a.id,b.id,c.id]);createSwatch('fill');const id=state.swatches[0].id,linked=swatchUsers(id).length;
      setSelection([c.id]);createSwatch('stroke');const sid=state.swatches[1].id;
      swEditAt=0;setSwatchColor(id,'#10b981');const changed=[a.fill,b.fill,c.fill];
      setSelection([b.id]);fillInput.value='#ffd54f';applyAppearance('fill');render();const afterHand=swatchUsers(id).length;
      const f=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files),th=f['ppt/theme/theme1.xml'],sl=f['ppt/slides/slide1.xml'];
      const n=state.swatches.length;undo();undo();const undone=[state.paths[0].fill,state.swatches[0].color];
      return JSON.stringify({linked,changed,afterHand,n,theme:/<a:accent1><a:srgbClr val="10B981"\\/>/.test(th)&&/<a:accent2><a:srgbClr val="121212"\\/>/.test(th),
        acc1:(sl.match(/<a:schemeClr val="accent1"/g)||[]).length,acc2:(sl.match(/<a:schemeClr val="accent2"/g)||[]).length,undone,panel:document.querySelectorAll('#swList .sw-row').length});})()"""))
    if not (sw["linked"] == 2 and sw["changed"] == ["#10b981", "#10b981", "#c62828"] and sw["afterHand"] == 1 and sw["n"] == 2 and sw["theme"]
            and sw["acc1"] == 1 and sw["acc2"] == 1 and sw["undone"] == ["#21537f", "#21537f"] and sw["panel"] == 2):
        fails.append(f"SWATCHES: 同じ塗り2個をつなぐ→色替えで2個とも変わる→手で変えた1個は外れる→テーマのアクセント1・2とschemeClr→undoで戻るはず: {sw}")

    # 33) シンボル: 2図形をシンボルに→2つ置く→1つを回転・1つを反転・拡大→1つ目で編集（色と頂点）→終えると他の2つも同じ変形のまま更新
    #     →複製は新しいインスタンスに分かれる→手で崩した絵はリンクが外れる→PPTXのグループ名＝シンボル名→undo
    sy = json.loads(ev(sock, """(()=>{
      state.paths=[];state.symbols=null;state.swatches=null;state.artboards=null;state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;applyArtboard(1280,720);
      const R=(x,y,w,h,fill)=>{const o={id:nextId++,layerId:1,closed:true,fill,stroke:'#121212',width:4,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]};state.paths.push(o);return o;};
      const a=R(100,100,100,60,'#21537f'),b=R(120,120,30,20,'#c62828');render();setSelection([a.id,b.id]);makeSymbol();const sid=state.symbols[0].id;
      placeSymbol(sid);const i2=state.selectedPaths.slice();rotateSelection(90);
      placeSymbol(sid);const i3=state.selectedPaths.slice();flip(true);scaleSelection(200);
      const inst=[...new Set(state.paths.map(p=>p.symInst))],m3=instanceMatrix(state.symbols[0],pathById(state.selectedPaths[0]).symInst);
      setSelection([a.id]);toggleSymbolEdit();const editing=!!symEdit;
      const a2=pathById(a.id);a2.fill='#10b981';a2.nodes[2].x+=40;a2.nodes[2].outX+=40;a2.nodes[2].inX+=40;render();
      toggleSymbolEdit();
      const ps=state.paths,big=ps.filter(p=>p.symIdx===0);
      const fills=big.map(p=>p.fill),w3=ps.filter(p=>p.symIdx===0).map(p=>p.width);
      const mats=[...new Set(ps.map(p=>p.symInst))].map(i=>instanceMatrix(state.symbols[0],i));
      const det=mats.map(m=>m&&Math.round((m.a*m.d-m.b*m.c)*100)/100);
      setSelection(ps.filter(p=>p.symInst===mats.length&&true).map(p=>p.id));
      setSelection(ps.filter(p=>p.symInst===inst[1]).map(p=>p.id));duplicateSelection(30,30);render();const afterDup=instancesOf(sid).length;
      const broken=ps.find(p=>p.symInst===inst[2]&&p.symIdx===1);broken.nodes.pop();render();
      setSelection(ps.filter(p=>p.symInst===inst[0]).map(p=>p.id));toggleSymbolEdit();toggleSymbolEdit();const stillLinked=instancesOf(sid).length;
      const sl=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'];
      const grp=(sl.match(/name="シンボル 1"/g)||[]).length;
      return JSON.stringify({inst:inst.length,m3:!!m3,editing,fills,w3,det,afterDup,stillLinked,grp,panel:document.querySelectorAll('#symList .sw-row').length});})()"""))
    if not (sy["inst"] == 3 and sy["m3"] and sy["editing"] and sy["fills"] == ["#10b981"] * 3 and sy["det"] == [1, 1, -4]
            and sorted(sy["w3"]) == [4, 4, 8] and sy["afterDup"] == 4 and sy["stillLinked"] == 3 and sy["grp"] == 3 and sy["panel"] == 1):
        fails.append(f"SYMBOLS: 3つ置いて回転・反転拡大→編集が他の2つに同じ変形で反映（線の太さも拡大率）→複製は4つ目→崩した1つは外れる→PPTXのグループ名のはず: {sy}")

    # 34) 繰り返し（ライブ）: 放射8→元の色を変えるとコピー7個も変わる→元を動かすとついてくる→個数を変えると数が変わる→Undoで戻る
    #     →グリッド3×2＝5コピー→ミラー1コピー（左右反転）→確定で普通の図形→外すで元だけ→複製した元は繰り返しに入らない→PPTXに全部入る
    rp = json.loads(ev(sock, """(()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;state.repeats=null;state.symbols=null;state.swatches=null;state.artboards=null;state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;applyArtboard(1280,720);
      const R=(x,y,w,h,fill)=>{const o={id:nextId++,layerId:1,closed:true,fill,stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]};state.paths.push(o);return o;};
      const a=R(600,100,40,80,'#21537f');render();setSelection([a.id]);$('rptKind').value='radial';$('rptN').value=8;$('rptR').value=150;makeRepeat();
      const cp=()=>state.paths.filter(p=>p.rptOf!=null);const n1=cp().length;
      pathById(a.id).fill='#c62828';render();const fills=[...new Set(cp().map(p=>p.fill))];
      setSelection([a.id]);nudgeSelection(100,0);render();const moved=Math.round(Math.min(...cp().map(p=>bboxOfPath(p).l))-Math.min(...[600-150-40]));
      $('rptN').value=12;rptEditAt=0;updateRepeatFromPanel();const n2=cp().length;undo();const n3=cp().length;
      const bake0=cp().every(p=>p.locked);
      setSelection([a.id]);removeRepeat();const afterRemove=state.paths.length;
      setSelection([a.id]);$('rptKind').value='grid';$('rptCols').value=3;$('rptRows').value=2;$('rptGap').value=10;makeRepeat();const g=cp().length;
      const gx=[...new Set(cp().map(p=>Math.round(bboxOfPath(p).l)))].sort((x,y)=>x-y);
      duplicateSelection(0,300);const dupJoined=state.paths.filter(p=>p.rptSrc!=null).length;
      const px=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'];const geoms=(px.match(/<a:custGeom>/g)||[]).length;
      setSelection([a.id]);bakeRepeat();const baked=state.paths.filter(p=>p.locked||p.rptOf!=null).length;
      const b=R(100,400,60,40,'#10b981');b.nodes[1].x=200;render();setSelection([b.id]);$('rptKind').value='mirror';$('rptAxis').value='v';$('rptMGap').value=20;makeRepeat();
      const mc=cp(),mbb=mc.length&&bboxOfPath(mc[0]);
      return JSON.stringify({n1,fills,moved,n2,n3,bake0,afterRemove,g,gx,dupJoined,geoms,baked,mirror:mc.length,mbb:mbb&&[Math.round(mbb.l),Math.round(mbb.r)]});})()"""))
    if not (rp["n1"] == 7 and rp["fills"] == ["#c62828"] and rp["n2"] == 11 and rp["n3"] == 7 and rp["bake0"] and rp["afterRemove"] == 1
            and rp["g"] == 5 and rp["gx"][:3] == [700, 750, 800] and rp["dupJoined"] == 1 and rp["geoms"] == 7 and rp["baked"] == 0
            and rp["mirror"] == 1 and rp["mbb"] == [220, 320]):
        fails.append(f"REPEATS: 放射8＝コピー7→色・位置が追従→12個→Undoで7→外す→グリッド5（50pxおき）→複製は入らない→PPTX→確定→ミラー（右にすき間20で反転）のはず: {rp}")

    # 35) ナイフ: 円を縦に横切ると左右2つ（面積の和は元のまま・色も同じ）／ドーナツを横切ると穴の両側で2つ（各々穴なし）／横切らない線では切れない
    #     消しゴム: 正方形の真ん中を縦になぞると2つに分かれ、消した幅ぶん面積が減る／端をかすると1つのまま欠ける／Undoで戻る
    kn = json.loads(ev(sock, """(()=>{
      state.paths=[];state.selectedPaths=[];state.selectedPath=null;state.repeats=null;state.symbols=null;state.artboards=null;state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;applyArtboard(1280,720);
      const C=(cx,cy,r)=>{const k=.5523*r;return{closed:true,nodes:[{x:cx+r,y:cy,inX:cx+r,inY:cy-k,outX:cx+r,outY:cy+k},{x:cx,y:cy+r,inX:cx+k,inY:cy+r,outX:cx-k,outY:cy+r},{x:cx-r,y:cy,inX:cx-r,inY:cy+k,outX:cx-r,outY:cy-k},{x:cx,y:cy-r,inX:cx-k,inY:cy-r,outX:cx+k,outY:cy-r}]};};
      const add=o=>{o.id=nextId++;o.layerId=1;state.paths.push(o);return o;};
      const circ=add({...C(200,200,100),fill:'#21537f',stroke:'#121212',width:2});render();const a0=polyAreaOfParts(partsOf(circ));
      const run=(tool,pts)=>{setSelection([]);finishCutStroke({type:'cut',tool,pts:pts.map(([x,y])=>({x,y}))});};
      run('knife',[[200,60],[205,200],[200,340]]);const kc=state.paths.length,ka=state.paths.reduce((s,p)=>s+polyAreaOfParts(partsOf(p)),0),kf=[...new Set(state.paths.map(p=>p.fill))];
      run('knife',[[400,60],[400,340]]);const miss=state.paths.length;
      state.paths=[];const dn=add({subpaths:[C(600,200,100),C(600,200,40)],fill:'#c62828',stroke:'none',width:1});render();
      run('knife',[[450,200],[750,200]]);const dc=state.paths.length,dholes=state.paths.map(p=>(p.subpaths||[p]).length);
      state.paths=[];const sq=add({closed:true,nodes:[node(100,400),node(300,400),node(300,600),node(100,600)],fill:'#10b981',stroke:'none',width:1});render();
      $('eraserW').value=20;run('eraser',[[200,380],[200,620]]);const ec=state.paths.length,ea=Math.round(state.paths.reduce((s,p)=>s+polyAreaOfParts(partsOf(p)),0));
      undo();const eu=state.paths.length;
      run('eraser',[[290,380],[310,620]]);const ec2=state.paths.length,ea2=Math.round(polyAreaOfParts(partsOf(state.paths[0])));
      return JSON.stringify({a0:Math.round(a0),kc,ka:Math.round(ka),kf,miss,dc,dholes,ec,ea,eu,ec2,ea2});})()"""))
    if not (kn["kc"] == 2 and abs(kn["ka"] - kn["a0"]) < kn["a0"] * .01 and kn["kf"] == ["#21537f"] and kn["miss"] == 2 and kn["dc"] == 2
            and kn["dholes"] == [1, 1] and kn["ec"] == 2 and abs(kn["ea"] - (40000 - 20 * 200)) < 200 and kn["eu"] == 1 and kn["ec2"] == 1 and 30000 < kn["ea2"] < 40000):
        fails.append(f"KNIFE/ERASER: 円→2つ（面積そのまま）・外れた線は切らない・ドーナツ→穴なし2つ・消しゴムで正方形が2つ（幅20ぶん減る）・Undo・端をかすると1つのまま欠けるはず: {kn}")

    # 36) Kiroのイラスト（examples/warehouse.svg）: viewBoxがそのままアートボード・data-layer がレイヤー名・グラデが入る・空の「レイヤー 1」が残らない・PPTXで出ないもの0
    ws = open(os.path.join(HERE, "examples", "warehouse.svg"), encoding="utf-8").read()
    il = json.loads(ev(sock, """(async()=>{state.paths=[];state.selectedPaths=[];state.selectedPath=null;state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;state.artboards=null;render();
      await openDocument(new File([%s],'warehouse.svg',{type:'image/svg+xml'}));const c=pptxCheck();
      return JSON.stringify({art:[ART.w,ART.h],layers:state.layers.map(l=>l.name),n:state.paths.length,grad:state.paths.filter(p=>p.gradient).length,lost:c.lost,baked:c.baked,
        shadow:state.paths.filter(p=>p.opacity&&Math.abs(p.opacity-.12)<1e-6).length});})()""" % json.dumps(ws), await_promise=True))
    if not (il["art"] == [800, 450] and il["layers"] == ["背景", "倉庫", "荷物", "トラック", "矢印"] and il["n"] == 25 and il["grad"] == 2
            and il["lost"] == 0 and il["baked"] == 0 and il["shadow"] == 2):
        fails.append(f"ILLUST: 見本の絵が 800×450・レイヤー5つ・25図形・グラデ2・影2・出ないもの0 で開くはず: {il}")

    # 37) 外から持ち込むSVGの切り抜き・マスク（examples/clip-mask-test.svg）: 円・図形の大きさ基準の三角・白いマスク・灰色のマスク・入れ子（帯×星）が
    #     クリッピングマスクになる（円は2図形で共有）・灰色は半透明・グラデのマスクは平均の半透明・「スライドへ戻す」には clipPath が残らない
    cm = open(os.path.join(HERE, "examples", "clip-mask-test.svg"), encoding="utf-8").read()
    ci = json.loads(ev(sock, """(()=>{state.paths=[];state.selectedPaths=[];state.selectedPath=null;state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;render();
      importGenericSvg(%s,'clip-mask-test.svg');const ps=state.paths,masks=ps.filter(p=>p.clipMask),clipped=ps.filter(p=>p.clipBy);
      const share=Math.max(...masks.map(m=>clipped.filter(p=>p.clipBy===m.id).length));
      const star=masks.map(m=>bboxOfPath(m)).find(b=>b.l>570&&b.t>280);const op=ps.map(p=>p.opacity).filter(v=>v!=null&&v<.99).map(v=>Math.round(v*100)).sort();
      const status=document.getElementById('status').textContent,sl=buildSlideSvg(),c=pptxCheck();
      return JSON.stringify({status,n:ps.length,masks:masks.length,clipped:clipped.length,share,star:star&&[Math.round(star.t),Math.round(star.b)],op,slideClip:/<clipPath/.test(sl.replace(/<metadata[\\s\\S]*?<\\/metadata>/,'')),lost:c.lost});})()""" % json.dumps(cm)))
    if not (ci["n"] == 13 and ci["masks"] == 5 and ci["clipped"] == 6 and ci["share"] == 2 and ci["star"] == [300, 370]
            and ci["op"] == [50, 50] and not ci["slideClip"] and ci["lost"] == 0 and "グラデのマスク" in ci["status"]):
        fails.append(f"CLIP-IMPORT: 8図形＋マスク5（円は2図形で共有・帯×星は帯の高さに切れる）・灰色とグラデのマスクは半透明・スライドへ戻すと切り抜いた形のはず: {ci}")

    eps = ev(sock, """(async()=>{await openDocument(new File([new Uint8Array([0xC5,0xD0,0xD3,0xC6,0,0,0,0])],'old.ai'));return document.getElementById('status').textContent;})()""", await_promise=True)
    if "PDF互換" not in (eps or ""):
        fails.append(f"PDF-EPS: 古いAI／EPSは保存し直しを案内するはず: {eps}")

    # 38) パス演算の見た目の受け継ぎ（#1）: 型抜き=最背面の見た目／合体=最前面の見た目（グラデ・不透明度・影・破線）／Undoで2つに戻る
    ba = json.loads(ev(sock, """JSON.stringify((()=>{
      const mk=(x,y,w,h,ex)=>({id:nextId++,closed:true,fill:'#cccccc',stroke:'#000000',width:1,layerId:state.activeLayer,
        nodes:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(c=>node(c[0],c[1])),...(ex||{})});
      state.paths=[];const back=mk(100,100,200,200,{fill:'#cc2222'}),front=mk(150,150,200,200,{fill:'#000000'});
      state.paths=[back,front];render();setSelection([back.id,front.id]);booleanOp('subtract');
      const sub={n:state.paths.length,fill:state.paths[0].fill};undo();const afterUndo=state.paths.length;
      state.paths=[];const b2=mk(100,100,200,200,{fill:'#cc2222'}),f2=mk(150,150,200,200,{fill:'#000000',opacity:0.5,dash:'8 4',shadow:{dx:3,dy:3,blur:5,color:'#000000',alpha:0.4},gradient:{type:'radial',c1:'#ffd700',c2:'#b8860b',angle:0}});
      state.paths=[b2,f2];render();setSelection([b2.id,f2.id]);booleanOp('union');const u=state.paths[0];
      return {sub,afterUndo,uni:{n:state.paths.length,fill:u.fill,op:u.opacity,dash:u.dash,shadow:!!u.shadow,grad:u.gradient&&u.gradient.type}};
    })())"""))
    if not (ba["sub"]["n"]==1 and ba["sub"]["fill"]=='#cc2222' and ba["afterUndo"]==2 and
            ba["uni"]["n"]==1 and ba["uni"]["fill"]=='#000000' and abs(ba["uni"]["op"]-0.5)<1e-9 and
            ba["uni"]["dash"]=='8 4' and ba["uni"]["shadow"] and ba["uni"]["grad"]=='radial'):
        fails.append(f"BOOLEAN-APPEARANCE: 型抜きは最背面の見た目・合体は最前面の見た目（グラデ/不透明度/影/破線）を受け継ぎUndoで2つに戻るはず: {ba}")

    # 39) パス演算を3つ以上でも（#2）: 3つの合体→1つ・ボタン有効／背面から型抜き→1つ／Undoで3つ
    bm = json.loads(ev(sock, """JSON.stringify((()=>{
      const mk=(x,y,w,h)=>({id:nextId++,closed:true,fill:'#3366cc',stroke:'#000000',width:1,layerId:state.activeLayer,
        nodes:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(c=>node(c[0],c[1]))});
      state.paths=[];const a=mk(100,100,150,150),b=mk(200,100,150,150),c=mk(300,100,150,150);
      state.paths=[a,b,c];render();setSelection([a.id,b.id,c.id]);
      const canU=!document.getElementById('union').disabled;
      booleanOp('union');const unionN=state.paths.length;undo();const back=state.paths.length;
      setSelection([a.id,b.id,c.id]);booleanOp('subtract');const subN=state.paths.length;undo();
      return {canU,unionN,back,subN};
    })())"""))
    if not (bm["canU"] and bm["unionN"]==1 and bm["back"]==3 and bm["subN"]==1):
        fails.append(f"BOOLEAN-MULTI: 2つ以上でボタン有効・3つの合体→1つ・型抜き→1つ・Undoで3つのはず: {bm}")

    # 40) 文字ツールで既存の文字を押したら打ち直し（#6）: 外接枠の中=その文字を返す／外=新規／ロック・非表示は対象外／ヒント更新
    te = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];const t={id:nextId++,type:'text',text:'あ',x:200,y:300,size:80,letterSpacing:0,lineHeight:1.3,vertical:false,fontKey:'x',fill:'#000000',stroke:'none',width:1,layerId:state.activeLayer,
        cmds:[{type:'M',x:180,y:260},{type:'L',x:260,y:260},{type:'L',x:260,y:340},{type:'L',x:180,y:340},{type:'Z'}]};
      state.paths=[t];render();
      const inside=textHitForEdit({x:220,y:300}),outside=textHitForEdit({x:500,y:500});
      t.locked=true;const locked=textHitForEdit({x:220,y:300});t.locked=false;
      setTool('text');const hint=document.getElementById('hint').textContent;
      return {inside:inside&&inside.id===t.id,outside:outside===null,locked:locked===null,hintOk:hint.indexOf('文字の上をクリック')>=0};
    })())"""))
    if not (te["inside"] and te["outside"] and te["locked"] and te["hintOk"]):
        fails.append(f"TEXT-CLICK-EDIT: 文字ツールのクリックが文字の外接枠内なら打ち直し・外は新規・ロックは対象外・ヒント更新のはず: {te}")

    # 41) 下絵を今のアートボードに合わせて置く（#7前半）: 800x800の92%に収めて中央・拡大しない
    ul = json.loads(ev(sock, """JSON.stringify((()=>{
      state.artboards=null;applyArtboard(800,800);state.activeArtboard=0;
      const fr=underlayFrame({naturalWidth:1600,naturalHeight:900});
      const wide=underlayFrame({naturalWidth:900,naturalHeight:1600});
      const small=underlayFrame({naturalWidth:100,naturalHeight:100});
      applyArtboard(1200,800);state.artboards=null;
      return {w:fr.w,cx:fr.x+fr.w/2,cy:fr.y+fr.h/2,inside:fr.x>=0&&fr.y>=0&&fr.x+fr.w<=800&&fr.y+fr.h<=800,
        maxFit:fr.w<=800*0.92+0.5,wideCx:wide.x+wide.w/2,wideCy:wide.y+wide.h/2,noUp:small.w===100};
    })())"""))
    if not (abs(ul["cx"]-400)<1 and abs(ul["cy"]-400)<1 and ul["inside"] and ul["maxFit"] and
            abs(ul["wideCx"]-400)<1 and abs(ul["wideCy"]-400)<1 and ul["noUp"]):
        fails.append(f"UNDERLAY-ARTBOARD: 下絵が800x800の92%に収まり中央・16:9も中央・拡大しないはず: {ul}")

    # 42) 入力欄でEnterしたら絵の操作に戻る（#13）: #fillHexで値が入り欄からフォーカスが外れる／Shift+Enterは残る／寸法欄は外れない
    ie = json.loads(ev(sock, """JSON.stringify((()=>{
      const mk=(x,y,w,h)=>({id:nextId++,closed:true,fill:'#cccccc',stroke:'#000000',width:1,layerId:state.activeLayer,
        nodes:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(c=>node(c[0],c[1]))});
      state.paths=[];const r=mk(100,100,100,100);state.paths=[r];render();setSelection([r.id]);
      const fh=document.getElementById('fillHex');revealPanel(fh);fh.focus();fh.value='#123456';
      fh.dispatchEvent(new Event('change',{bubbles:true}));const applied=pathById(r.id).fill;
      fh.focus();fh.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));const blurred=document.activeElement!==fh;
      fh.focus();fh.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey:true,bubbles:true}));const kept=document.activeElement===fh;fh.blur();
      const dl=document.getElementById('dimLen');dl.disabled=false;revealPanel(dl);dl.focus();dl.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));const dimKept=document.activeElement===dl;dl.blur();
      return {applied,blurred,kept,dimKept};
    })())"""))
    if not (ie["applied"]=='#123456' and ie["blurred"] and ie["kept"] and ie["dimKept"]):
        fails.append(f"INPUT-ENTER-BLUR: #fillHexでEnter→値が入り欄から外れる・Shift+Enterは残る・寸法欄は外れないはず: {ie}")

    # 43) 回転コピーの数のラベル（#15）: ラベル「複製」・ステータスに元と合わせた総数
    rl = json.loads(ev(sock, """JSON.stringify((()=>{
      const lbl=document.getElementById('rcCount').closest('label').textContent.trim();
      const mk=(x,y,w,h)=>({id:nextId++,closed:true,fill:'#cccccc',stroke:'#000000',width:1,layerId:state.activeLayer,
        nodes:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(c=>node(c[0],c[1]))});
      state.paths=[];const r=mk(300,300,40,40);state.paths=[r];render();setSelection([r.id]);
      const lp=document.getElementById('livePrev');if(lp)lp.checked=false;
      document.getElementById('rcCount').value=5;document.getElementById('rcAngle').value=30;document.getElementById('rcScale').value=100;
      rotateCopyAt({x:400,y:400});const status=document.getElementById('status').textContent;
      return {labelOk:lbl.indexOf('複製')===0,status,statusOk:status.indexOf('5個複製した（元と合わせて6個')===0};
    })())"""))
    if not (rl["labelOk"] and rl["statusOk"]):
        fails.append(f"ROTATE-COPY-LABEL: ラベルが「複製」・ステータスが「5個複製した（元と合わせて6個…」のはず: {rl}")

    # 44) 何も選ばずに決めた見た目を次に描く図形に付ける（#4）: 放射グラデ・突出・尖り・破線・不透明50・矢印終点→矩形と直線に付く（矢印は開いた線だけ）／効果は付かない／塗りなしは塗りなし／効果欄は選択なしで無効
    ds = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPath=null;state.selectedPaths=[];updateControls();
      const effOff=document.getElementById('shadowOn').disabled&&document.getElementById('zigKind').disabled&&document.getElementById('glowOn').disabled&&document.getElementById('softEdge').disabled;
      document.getElementById('fillNone').checked=false;document.getElementById('strokeNone').checked=false;
      document.getElementById('fillType').value='radial';document.getElementById('capStyle').value='square';document.getElementById('joinStyle').value='miter';
      document.getElementById('dash').value='6 4';document.getElementById('opacity').value='50';document.getElementById('arrowSel').value='end';
      const rect=newPath([[100,100],[180,100],[180,180],[100,180]].map(c=>node(c[0],c[1])),true);
      const line=newPath([node(300,300),node(400,300)],false);
      document.getElementById('fillNone').checked=true;
      const none=newPath([[500,500],[560,500],[560,560]].map(c=>node(c[0],c[1])),true);
      document.getElementById('fillNone').checked=false;document.getElementById('fillType').value='solid';document.getElementById('capStyle').value='round';document.getElementById('joinStyle').value='round';document.getElementById('dash').value='';document.getElementById('opacity').value='100';document.getElementById('arrowSel').value='none';
      return {effOff,grad:rect.gradient&&rect.gradient.type,cap:rect.cap,join:rect.join,dash:rect.dash,op:rect.opacity,rectArrow:rect.arrow||null,lineArrow:line.arrow,shadow:!!rect.shadow,zig:!!rect.zig,noneFill:none.fill};
    })())"""))
    if not (ds["effOff"] and ds["grad"]=='radial' and ds["cap"]=='square' and ds["join"]=='miter' and ds["dash"]=='6 4' and
            abs(ds["op"]-0.5)<1e-9 and ds["rectArrow"] is None and ds["lineArrow"]=='end' and not ds["shadow"] and not ds["zig"] and ds["noneFill"]=='none'):
        fails.append(f"DRAW-STYLE: 何も選ばずに決めた見た目が新しい図形に付き・矢印は開いた線だけ・効果は付かず・塗りなしは塗りなし・選択なしで効果欄が無効のはず: {ds}")

    # 45) 効果の色の16進欄（#12）: #glowHex/#shadowHex/#gradMidHexがある／光彩の図形で#glowHexに#ff5252→glow.colorが変わる／不正値は入らず欄が戻る
    eh = json.loads(ev(sock, """JSON.stringify((()=>{
      const exists=!!document.getElementById('glowHex')&&!!document.getElementById('shadowHex')&&!!document.getElementById('gradMidHex');
      const r={id:nextId++,closed:true,fill:'#cccccc',stroke:'#000000',width:1,layerId:state.activeLayer,glow:{r:8,color:'#ffd54f',alpha:0.6},
        nodes:[[100,100],[200,100],[200,200],[100,200]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);
      const gh=document.getElementById('glowHex');gh.value='#ff5252';gh.dispatchEvent(new Event('change',{bubbles:true}));
      const after=pathById(r.id).glow.color;
      gh.value='#zzzz';gh.dispatchEvent(new Event('change',{bubbles:true}));
      return {exists,after,stillValid:pathById(r.id).glow.color,fieldReset:gh.value};
    })())"""))
    if not (eh["exists"] and eh["after"]=='#ff5252' and eh["stillValid"]=='#ff5252' and eh["fieldReset"]=='#ff5252'):
        fails.append(f"EFFECT-HEX: #glowHexで色が変わり不正値は入らず欄が戻るはず: {eh}")

    # 46) うねり「不規則」（#9）: zigKindにrough／適用でzig.seedが残る（保存open用）／展開後の点が4より多い／seed固定で2回同じ
    rg = json.loads(ev(sock, """JSON.stringify((()=>{
      const hasOpt=!!document.querySelector('#zigKind option[value="rough"]');
      const r={id:7777,closed:true,fill:'#cccccc',stroke:'#000000',width:2,layerId:state.activeLayer,
        nodes:[[100,100],[300,100],[300,300],[100,300]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);
      document.getElementById('zigKind').value='rough';document.getElementById('zigAmp').value='10';document.getElementById('zigLen').value='24';
      document.getElementById('zigKind').dispatchEvent(new Event('change',{bubbles:true}));
      const seedSet=pathById(r.id).zig.seed!=null;
      const dump=()=>zigParts(pathById(r.id)).map(pt=>pt.nodes.map(n=>[Math.round(n.x*100),Math.round(n.y*100)]));
      const a=dump(),b=dump();
      const nPts=a.reduce((s,pt)=>s+pt.length,0);
      return {hasOpt,seedSet,nPts,same:JSON.stringify(a)===JSON.stringify(b)};
    })())"""))
    if not (rg["hasOpt"] and rg["seedSet"] and rg["nPts"]>4 and rg["same"]):
        fails.append(f"ZIG-ROUGH: 不規則がzigKindにあり・seedが残り・点が増え・seed固定で2回同じのはず: {rg}")

    # 47) 不透明度0%が0のまま（100に化けない）: 適用後0・SVGにopacity="0"・PPTXにalpha0・PDFに/ca 0・保存openで0
    oz = json.loads(ev(sock, """JSON.stringify((()=>{
      const r={id:nextId++,closed:true,fill:'#cc0000',stroke:'none',width:1,layerId:state.activeLayer,nodes:[[100,100],[200,100],[200,200],[100,200]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);
      const o=document.getElementById('opacity');o.value='0';o.dispatchEvent(new Event('change',{bubbles:true}));
      const op0=pathById(r.id).opacity;
      const svgHas=buildExportSvg(false).includes('opacity="0"');
      const pptxHas=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'].includes('<a:alpha val="0"/>');
      const pdfHas=buildPdf({textBox:false,selectionOnly:false}).text.includes('/ca 0 ');
      const j=snapshot();state.paths=[];restore(j);const reop=state.paths[0].opacity;
      return {op0,svgHas,pptxHas,pdfHas,reop};
    })())"""))
    if not (oz["op0"]==0 and oz["svgHas"] and oz["pptxHas"] and oz["pdfHas"] and oz["reop"]==0):
        fails.append(f"OPACITY-ZERO: 不透明度0が0のまま（SVG opacity0・PPTX alpha0・PDF ca0・保存open）保たれるはず: {oz}")

    # 48) 矢印の設定が閉じた図形を描くと消えない（#4の続き）: 何も選ばず矢印終点→矩形を描く→欄は無効だが値は保持→直線を描くと矢印が付く
    ac = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];state.selectedPath=null;state.selectedPaths=[];updateControls();
      const as=document.getElementById('arrowSel');as.value='end';
      const rect=newPath([[100,100],[180,100],[180,180],[100,180]].map(c=>node(c[0],c[1])),true);
      state.paths=[rect];setSelection([rect.id]);updateControls();
      const disabledOnClosed=as.disabled,keptVal=as.value;
      const line=newPath([node(300,300),node(400,300)],false);
      state.paths.push(line);setSelection([line.id]);updateControls();
      const enabledOnLine=!as.disabled,lineShows=as.value;as.value='none';
      return {disabledOnClosed,keptVal,lineArrow:line.arrow||null,enabledOnLine,lineShows};
    })())"""))
    if not (ac["disabledOnClosed"] and ac["keptVal"]=='end' and ac["lineArrow"]=='end' and ac["enabledOnLine"] and ac["lineShows"]=='end'):
        fails.append(f"ARROW-CLOSED: 閉じた図形選択で矢印欄が無効・値は保持・次の線に矢印が付くはず: {ac}")

    # 49) 放射グラデの中心・広がり（#3）: cx/cy25%・広がり60%がパネル・SVG・PPTX(fillToRect)・PDF(ShadingType3)・保存openに出る／中心の印をドラッグ→cx変化→Undoで戻る
    rc3 = json.loads(ev(sock, """JSON.stringify((()=>{
      const r={id:nextId++,closed:true,fill:'#ff0000',stroke:'none',width:1,layerId:state.activeLayer,gradient:{c1:'#ff0000',c2:'#0000ff',angle:0,type:'radial',cx:0.25,cy:0.25,spread:60},nodes:[[100,100],[300,100],[300,300],[100,300]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);updateControls();
      const panel={cx:document.getElementById('gradCx').value,sp:document.getElementById('gradSpread').value,rowShown:document.getElementById('gradRadialRow').style.display!=='none'};
      const svgHas=buildExportSvg(false).includes('cx="0.25"');
      const pptxHas=Object.fromEntries(buildPptxFiles({textBox:true,selectionOnly:false}).files)['ppt/slides/slide1.xml'].includes('<a:fillToRect l="25000" t="25000" r="75000" b="75000"/>');
      const pdfHas=buildPdf({textBox:false,selectionOnly:false}).text.includes('/ShadingType 3');
      const j=snapshot();state.paths=[];restore(j);const g=state.paths[0].gradient;
      return {panel,svgHas,pptxHas,pdfHas,recx:g.cx,respread:g.spread};
    })())"""))
    if not (rc3["panel"]["rowShown"] and rc3["panel"]["cx"]=='25' and rc3["panel"]["sp"]=='60' and rc3["svgHas"] and rc3["pptxHas"] and rc3["pdfHas"] and abs(rc3["recx"]-0.25)<1e-9 and rc3["respread"]==60):
        fails.append(f"RADIAL-CENTER: 放射グラデの中心25%・広がり60%がパネル/SVG/PPTX/PDF/保存openに出るはず: {rc3}")
    dm = json.loads(ev(sock, """JSON.stringify((()=>{
      const r={id:nextId++,closed:true,fill:'#ff0000',stroke:'none',width:1,layerId:state.activeLayer,gradient:{c1:'#ff0000',c2:'#0000ff',angle:0,type:'radial',cx:0.5,cy:0.5,spread:100},nodes:[[100,100],[300,100],[300,300],[100,300]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);updateControls();
      setTool('select');render();
      const marker=!!document.querySelector('[data-gradc]');
      const m=svg.getScreenCTM();const q=svg.createSVGPoint();q.x=150;q.y=150;const scr=q.matrixTransform(m);
      beginGradCenter({target:{dataset:{gradc:'1'}},clientX:scr.x,clientY:scr.y,preventDefault(){}});
      moveGradCenter({clientX:scr.x,clientY:scr.y});
      const cxDrag=pathById(r.id).gradient.cx;
      undo();const cxUndo=pathById(r.id).gradient.cx;
      return {marker,cxDrag:Math.round(cxDrag*100)/100,cxUndo};
    })())"""))
    if not (dm["marker"] and abs(dm["cxDrag"]-0.25)<0.02 and abs(dm["cxUndo"]-0.5)<1e-9):
        fails.append(f"RADIAL-CENTER-DRAG: 中心の印があり・ドラッグでcx変化・Undoで戻るはず: {dm}")

    # 50) 位置・サイズの単位（#14）: 600px→mmで211.67／W=23mm→65.2px／pxに戻すと65.2
    un = json.loads(ev(sock, """JSON.stringify((()=>{
      const r={id:nextId++,closed:true,fill:'#cccccc',stroke:'none',width:1,layerId:state.activeLayer,nodes:[[0,0],[600,0],[600,600],[0,600]].map(c=>node(c[0],c[1]))};
      state.paths=[r];render();setSelection([r.id]);updateControls();
      const u=document.getElementById('geomUnit');u.value='mm';u.dispatchEvent(new Event('change',{bubbles:true}));
      const wmm=document.getElementById('geomW').value;
      const gw=document.getElementById('geomW');gw.value='23';gw.dispatchEvent(new Event('change',{bubbles:true}));
      const bb=selectionTotalBBox();const pxw=Math.round((bb.r-bb.l)*100)/100;
      u.value='px';u.dispatchEvent(new Event('change',{bubbles:true}));
      const backpx=document.getElementById('geomW').value;
      return {wmm,pxw,backpx};
    })())"""))
    if not (abs(float(un["wmm"])-211.67)<0.1 and abs(un["pxw"]-65.2)<0.05 and abs(float(un["backpx"])-65.2)<0.1):
        fails.append(f"UNITS: 600px→mm211.67／23mm→65.2px／pxに戻すと65.2のはず: {un}")

    # 51) 下絵を動かす・大きさを変える（#7後半）: (100,50)動かす→位置が変わる／50%→中心を保って半分
    um = json.loads(ev(sock, """JSON.stringify((()=>{
      state.artboards=null;applyArtboard(800,800);state.activeArtboard=0;
      traceImage={img:{naturalWidth:400,naturalHeight:400},name:'t'};
      underlayBounds={...underlayFrame(traceImage.img)};underlaySel=true;const base={...underlayBounds};
      const m=svg.getScreenCTM();const sp=(x,y)=>{const p=svg.createSVGPoint();p.x=x;p.y=y;return p.matrixTransform(m);};
      state.drag={type:'underlay',start:{x:0,y:0},orig:{...base}};
      const s1=sp(100,50);moveUnderlay({clientX:s1.x,clientY:s1.y});state.drag=null;
      const dx=Math.round(underlayBounds.x-base.x),dy=Math.round(underlayBounds.y-base.y);
      const cx0=underlayBounds.x+underlayBounds.w/2,cy0=underlayBounds.y+underlayBounds.h/2;
      setUnderlayScale(50);
      const half=Math.abs(underlayBounds.w-base.w*0.5)<0.5&&Math.abs(underlayBounds.h-base.h*0.5)<0.5;
      const centerKept=Math.abs((underlayBounds.x+underlayBounds.w/2)-cx0)<0.5&&Math.abs((underlayBounds.y+underlayBounds.h/2)-cy0)<0.5;
      clearUnderlay();traceImage=null;applyArtboard(1200,800);state.artboards=null;
      return {dx,dy,half,centerKept};
    })())"""))
    if not (um["dx"]==100 and um["dy"]==50 and um["half"] and um["centerKept"]):
        fails.append(f"UNDERLAY-MOVE: 下絵を(100,50)動かし・50%で中心を保って半分になるはず: {um}")

    # T1) 色数1（インクと紙）: 赤地に白い字→インクの層1つ・桃色の輪なし・穴あり／しきい値で字の太さが変わる
    ev(sock, """(()=>{
      const cv=document.createElement('canvas');cv.width=400;cv.height=400;const c=cv.getContext('2d');
      c.fillStyle='#ffffff';c.fillRect(0,0,400,400);
      c.fillStyle='#d23b2b';c.fillRect(80,80,240,240);
      c.fillStyle='#ffffff';c.fillRect(170,140,60,160);
      window.__t1=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__t1);const b=await r.blob();
      loadTraceImage(new File([b],'t1.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)
    do_trace(sock, 1, 1.2, 3, 360, True, thresh=50)
    t1 = json.loads(ev(sock, """JSON.stringify((()=>{
      const tl=state.layers.filter(L=>L.name.startsWith('トレース'));
      const hasHole=state.paths.some(p=>p.subpaths&&p.subpaths.length>=2);
      return {layers:tl.length,hasHole};})())"""))
    if t1["layers"] != 1: fails.append(f"TRACE-INK: インクの層は1つのはず: {t1}")
    if not t1["hasHole"]: fails.append(f"TRACE-INK: 白い字の穴があるはず: {t1}")
    ev(sock, "undo()")
    NET_AREA_JS = """(()=>{let a=0;for(const p of state.paths){const parts=(p.subpaths||[p]).map(q=>{const n=q.nodes;let s=0;for(let i=0;i<n.length;i++){const u=n[i],v=n[(i+1)%n.length];s+=u.x*v.y-v.x*u.y;}return Math.abs(s)/2;});parts.sort((x,y)=>y-x);a+=parts[0]-parts.slice(1).reduce((s,v)=>s+v,0);}return a;})()"""
    # 紙色に近い側→濃い側のグラデの四角（ハードエッジだとしきい値が効かないのでグラデにする）
    ev(sock, """(()=>{const cv=document.createElement('canvas');cv.width=400;cv.height=400;const c=cv.getContext('2d');
      c.fillStyle='#ffffff';c.fillRect(0,0,400,400);
      const g=c.createLinearGradient(80,0,320,0);g.addColorStop(0,'#f0cfc4');g.addColorStop(1,'#c01810');
      c.fillStyle=g;c.fillRect(80,80,240,240);window.__t1b=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__t1b);const b=await r.blob();
      loadTraceImage(new File([b],'t1b.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)
    do_trace(sock, 1, 1.2, 3, 360, True, thresh=20); lowA = float(ev(sock, NET_AREA_JS)); ev(sock, "undo()")
    do_trace(sock, 1, 1.2, 3, 360, True, thresh=80); hiA = float(ev(sock, NET_AREA_JS)); ev(sock, "undo()")
    if not (lowA > hiA * 1.05): fails.append(f"TRACE-INK: しきい値が低いほどインク面積が広いはず: thr20={lowA} thr80={hiA}")

    # T2) 小さい画像（335px）も精細さまで拡大して処理する（360と720で境界点が変わる／大きい画像はRESテストで不変を担保）
    ev(sock, """(()=>{const cv=document.createElement('canvas');cv.width=335;cv.height=335;const c=cv.getContext('2d');
      c.fillStyle='#ffffff';c.fillRect(0,0,335,335);c.fillStyle='#cc2222';c.beginPath();c.arc(167,167,130,0,7);c.fill();
      window.__t2=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__t2);const b=await r.blob();
      loadTraceImage(new File([b],'t2.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)
    do_trace(sock, 2, 0, 3, 360, False); t2lo = json.loads(ev(sock, STATS_JS)); ev(sock, "undo()")
    do_trace(sock, 2, 0, 3, 720, False); t2hi = json.loads(ev(sock, STATS_JS)); ev(sock, "undo()")
    if not (t2hi["nodes"] > t2lo["nodes"] * 1.5):
        fails.append(f"TRACE-UPSCALE: 335px画像は精細さ720で境界点が増えるはず: hi={t2hi} lo={t2lo}")

    # T3) 「アートボードに合わせる」で小さい画像も拡大（読み込み直後は最大1倍のまま）
    ab = json.loads(ev(sock, """JSON.stringify((()=>{
      state.artboards=null;applyArtboard(800,800);state.activeArtboard=0;
      const img={naturalWidth:335,naturalHeight:325};
      const init=underlayFrame(img),fit=artboardFitFrame(img);
      applyArtboard(1200,800);state.artboards=null;
      return {initW:init.w,fitW:fit.w,fitH:fit.h};})())"""))
    if not (abs(ab["initW"]-335) < 1 and abs(ab["fitW"]-736) < 2):
        fails.append(f"TRACE-FIT-AB: 読み込み直後は335・ボタンで736(800*.92)に広がるはず: {ab}")

    # T4) トレースの角の出し方: 5稜星（鋭い角）で「角を残す」は内側の角まで立ち「丸める」は角が減る
    ev(sock, """(()=>{const cv=document.createElement('canvas');cv.width=400;cv.height=400;const c=cv.getContext('2d');
      c.fillStyle='#ffffff';c.fillRect(0,0,400,400);c.fillStyle='#cc2222';c.beginPath();
      for(let i=0;i<10;i++){const r=i%2?60:150,a=Math.PI/180*(36*i-90),x=200+r*Math.cos(a),y=200+r*Math.sin(a);i?c.lineTo(x,y):c.moveTo(x,y);}
      c.closePath();c.fill();window.__t4=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__t4);const b=await r.blob();
      loadTraceImage(new File([b],'t4.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)
    SHARP_JS = """JSON.stringify((()=>{
      const p=state.paths.find(q=>{const c=(q.fill||'');return c.length===7&&parseInt(c.slice(1,3),16)>150&&parseInt(c.slice(3,5),16)<110&&parseInt(c.slice(5,7),16)<110;});
      if(!p)return null;const q=(p.subpaths?p.subpaths.slice().sort((a,b)=>b.nodes.length-a.nodes.length)[0]:p);
      const ns=q.nodes;let corners=0;
      for(const n of ns){const iv=[n.x-n.inX,n.y-n.inY],ov=[n.outX-n.x,n.outY-n.y];
        const li=Math.hypot(iv[0],iv[1]),lo=Math.hypot(ov[0],ov[1]);
        if(li<1e-6||lo<1e-6){corners++;continue;}
        const d=(iv[0]*ov[0]+iv[1]*ov[1])/(li*lo),ang=Math.acos(Math.max(-1,Math.min(1,d)))*180/Math.PI;
        if(ang>30)corners++;}
      return {anchors:ns.length,corners};})())"""
    do_trace(sock, 2, 1.2, 3, 720, True, corner="sharp"); t4sharp = json.loads(ev(sock, SHARP_JS)); ev(sock, "undo()")
    do_trace(sock, 2, 1.2, 3, 720, True, corner="round"); t4round = json.loads(ev(sock, SHARP_JS)); ev(sock, "undo()")
    if not t4sharp or not t4round:
        fails.append(f"TRACE-CORNER: 星のパスが見つからない: sharp={t4sharp} round={t4round}")
    else:
        if not (t4sharp["corners"] >= 5): fails.append(f"TRACE-CORNER: 角を残すと星の角が立つはず: {t4sharp}")
        if not (t4sharp["corners"] > t4round["corners"]): fails.append(f"TRACE-CORNER: 角を残す>丸めるのはず: sharp={t4sharp} round={t4round}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;traceImage=null;clearUnderlay();render();true")

    # S1) 球に貼る: 太さ・間がちがう横帯＋円→球面に沿った形になる
    ev(sock, """(()=>{
      state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      const rect=(x,y,w,h)=>({id:nextId++,closed:true,layerId:1,fill:'#cc3333',stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      state.paths=[rect(150,310,500,20),rect(150,380,500,40),rect(150,470,500,15),circ(400,400,250)];
      setSelection(state.paths.map(p=>p.id));
      $('livePrev').checked=false;$('sphTilt').value=0;$('sphSpin').value=0;$('sphAxis').value=0;$('sphBack').value='hide';$('sphBackOp').value=25;
      return true;})()""")
    sigjs = "g=>g.slice(1).reduce((s,p)=>s+(p.subpaths||[p]).reduce((a,q)=>a+q.nodes.reduce((b,n)=>b+n.x+n.y,0),0),0)"
    sw = json.loads(ev(sock, """JSON.stringify((()=>{
      const sig=%s;
      const ok=doSphereWrap(true);
      const group=state.selectedPaths.map(pathById);
      const c=group[0],bb=bboxOfPath(c),cx=(bb.l+bb.r)/2,cy=(bb.t+bb.b)/2,R=((bb.r-bb.l)+(bb.b-bb.t))/4;
      let maxOver=0;group.slice(1).forEach(p=>(p.subpaths||[p]).forEach(q=>q.nodes.forEach(n=>{maxOver=Math.max(maxOver,Math.hypot(n.x-cx,n.y-cy)/R);})));
      const grouped=group.every(p=>p.groupId===group[0].groupId);
      return{ok,groupN:group.length,maxOver,grouped,sig1:Math.round(sig(group))};})())""" % sigjs))
    if not sw["ok"]: fails.append(f"SPHERE: doSphereWrap が失敗: {sw}")
    if not (sw["groupN"] >= 4): fails.append(f"SPHERE: 円＋3帯で4図形以上のはず: {sw}")
    if not (sw["maxOver"] <= 1.03): fails.append(f"SPHERE: ①全点が球の半径内のはず（maxOver<=1.03）: {sw}")
    if not sw["grouped"]: fails.append(f"SPHERE: 結果が1グループのはず: {sw}")
    # ⑤ Undo 1回で元の帯と円へ
    un = json.loads(ev(sock, "JSON.stringify((()=>{undo();return{n:state.paths.length,circ:state.paths.filter(p=>p.nodes&&p.nodes.length===48).length};})())"))
    if not (un["n"] == 4 and un["circ"] == 1): fails.append(f"SPHERE: ⑤Undoで元の4図形に戻るはず: {un}")
    # ⑥ 同じ設定で2回やると同じ形
    sw2 = json.loads(ev(sock, "JSON.stringify((()=>{const sig=%s;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);return Math.round(sig(state.selectedPaths.map(pathById)));})())" % sigjs))
    if abs(sw2 - sw["sig1"]) > 2: fails.append(f"SPHERE: ⑥同設定2回で同じ形のはず: {sw['sig1']} vs {sw2}")
    ev(sock, "undo();true")
    # ④ 裏側＝薄く出す→図形が増え、裏の不透明度が薄さ(25%)
    sw4 = json.loads(ev(sock, """JSON.stringify((()=>{
      $('sphBack').value='faint';$('sphBackOp').value=25;
      setSelection(state.paths.map(p=>p.id));
      doSphereWrap(true);
      const group=state.selectedPaths.map(pathById);
      const faint=group.filter(p=>p.opacity!=null&&Math.abs(p.opacity-0.25)<0.001).length;
      return{groupN:group.length,faint};})())"""))
    if not (sw4["faint"] >= 1): fails.append(f"SPHERE: ④裏側に不透明度25%の図形があるはず: {sw4}")
    if not (sw4["groupN"] >= 5): fails.append(f"SPHERE: ④裏側ありは表のみより図形が増えるはず: {sw4}")
    ev(sock, "undo();true")
    # ②③ 北・赤道・南の3帯→赤道の帯(group[2])で、傾き0は水平／傾き20は中央が下へふくらむ
    TOPMEAS = """JSON.stringify((()=>{
      const band=pathById(state.selectedPaths[2]);
      const part=band.subpaths?band.subpaths.slice().sort((a,b)=>b.nodes.length-a.nodes.length)[0]:band;
      const pts=sampleNodesToPoly(part);
      const xs=pts.map(p=>p[0]),xl=Math.min(...xs),xr=Math.max(...xs),w=xr-xl;
      const third=(f,t)=>{const a=pts.filter(p=>p[0]>=xl+w*f&&p[0]<=xl+w*t).map(p=>p[1]);return a.length?Math.min(...a):null;};
      return{midTop:third(0.4,0.6),sideTop:Math.min(third(0,0.2),third(0.8,1))};})())"""
    ev(sock, """(()=>{
      state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      const rect=(x,y,w,h)=>({id:nextId++,closed:true,layerId:1,fill:'#cc3333',stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      state.paths=[rect(170,312,460,18),rect(170,391,460,18),rect(170,470,460,18),circ(400,400,250)];
      $('sphBack').value='hide';$('sphSpin').value=0;$('sphAxis').value=0;return true;})()""")
    ev(sock, "$('sphTilt').value=0;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);true")
    flat = json.loads(ev(sock, TOPMEAS)); ev(sock, "undo();true")
    ev(sock, "$('sphTilt').value=20;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);true")
    bulge = json.loads(ev(sock, TOPMEAS)); ev(sock, "undo();true")
    if not (flat["midTop"] is not None and flat["sideTop"] is not None and abs(flat["midTop"] - flat["sideTop"]) < 8):
        fails.append(f"SPHERE: ②傾き0は水平の帯（中央と両端の上端がほぼ同じ）のはず: {flat}")
    if not (bulge["midTop"] is not None and bulge["sideTop"] is not None and bulge["midTop"] > bulge["sideTop"] + 5):
        fails.append(f"SPHERE: ③傾き20で中央の上端が両端より下（ふくらむ）のはず: {bulge}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;$('livePrev').checked=true;render();true")

    # ---- 波6（R1/R2/R3/R4）----
    MK = """state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      (()=>{const rect=(x,y,w,h)=>({id:nextId++,closed:true,layerId:1,fill:'#cc3333',stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      state.paths=[rect(170,330,460,20),rect(170,395,460,30),rect(170,460,460,18),circ(400,400,250)];})();
      $('livePrev').checked=false;$('sphSpin').value=0;$('sphAxis').value=0;$('sphBack').value='hide';$('sphBackOp').value=25;render();"""
    sigj = "g=>g.filter(p=>!p.sphSrc).reduce((s,p)=>s+(p.subpaths||[p]).reduce((a,q)=>a+q.nodes.reduce((b,n)=>b+n.x+n.y,0),0),0)"
    # R1) 貼り直し: 貼った結果を選んで傾きを変える→元から1回だけ貼った結果と同じ（2回貼りにならない）＋ボタン/欄
    rw = json.loads(ev(sock, """JSON.stringify((()=>{
      %s $('sphTilt').value=0;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);
      const grp1=selectedSphereGroup();
      $('sphTilt').value=25;doSphereWrap(true);
      const sig=%s,group=state.selectedPaths.map(pathById);
      updateControls();
      return{hasSrc:!!grp1,rewrapSig:Math.round(sig(group)),rewrapN:group.length,btn:$('sphereWrap').textContent,un:$('sphereUnwrap').style.display};})())""" % (MK, sigj)))
    fw = json.loads(ev(sock, """JSON.stringify((()=>{
      %s $('sphTilt').value=25;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);
      const sig=%s,group=state.selectedPaths.map(pathById);
      return{freshSig:Math.round(sig(group)),freshN:group.length};})())""" % (MK, sigj)))
    if not rw["hasSrc"]: fails.append(f"SPHERE-REWRAP: 貼った結果にsphSrcが無い: {rw}")
    if rw["rewrapN"] != fw["freshN"]: fails.append(f"SPHERE-REWRAP: 貼り直しの図形数が1回貼りと違う(2回貼り?): rw={rw} fw={fw}")
    if abs(rw["rewrapSig"] - fw["freshSig"]) > 3: fails.append(f"SPHERE-REWRAP: 貼り直しの形が1回貼りと違う: rw={rw} fw={fw}")
    if rw["btn"] != "貼り直す": fails.append(f"SPHERE-REWRAP: ボタンが『貼り直す』になっていない: {rw}")
    if rw["un"] == "none": fails.append(f"SPHERE-REWRAP: 『元に戻す』が出ていない: {rw}")
    # R1) 元に戻す→平らな4図形（帯3＋円）／保存→開き直し→貼り直せる
    uw = json.loads(ev(sock, """JSON.stringify((()=>{
      %s $('sphTilt').value=20;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);sphereUnwrap();
      const ps=state.paths;
      return{n:ps.length,anySrc:ps.some(p=>p.sphSrc),anyGid:ps.some(p=>p.groupId),circ:ps.filter(p=>p.nodes&&p.nodes.length===48).length};})())""" % MK))
    if not (uw["n"] == 4 and not uw["anySrc"] and not uw["anyGid"] and uw["circ"] == 1):
        fails.append(f"SPHERE-REWRAP: 元に戻すで平らな4図形に戻るはず: {uw}")
    ro = json.loads(ev(sock, """(async()=>{
      %s $('sphTilt').value=20;setSelection(state.paths.map(p=>p.id));doSphereWrap(true);
      const svg=buildExportSvg(true);
      await openDocument(new File([svg],'t.svg',{type:'image/svg+xml'}));
      setSelection(state.paths.map(p=>p.id));const grp=selectedSphereGroup();
      $('sphTilt').value=35;const ok=doSphereWrap(true);
      return JSON.stringify({restored:!!grp,reok:ok});})()""" % MK, await_promise=True))
    if not (ro["restored"] and ro["reok"]): fails.append(f"SPHERE-REWRAP: 保存→開き直し後に貼り直せるはず: {ro}")

    # R3) 枠: 塗りも線もない四角を枠にすると、中央にだけ置いた縞が極に届かない（枠なしは極に届く）
    frt = json.loads(ev(sock, """JSON.stringify((()=>{
      const rect=(x,y,w,h,f,s)=>({id:nextId++,closed:true,layerId:1,fill:f,stroke:s,width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      const mk=()=>({fr:rect(150,150,500,500,'none','none'),b1:rect(170,382,460,12,'#cc3333','none'),b2:rect(170,408,460,12,'#cc3333','none'),c:circ(400,400,250)});
      $('livePrev').checked=false;$('sphTilt').value=0;$('sphSpin').value=0;$('sphAxis').value=0;$('sphBack').value='hide';
      let S=mk();state.paths=[S.fr,S.b1,S.b2,S.c];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      setSelection(state.paths.map(p=>p.id));doSphereWrap(true);
      let g=state.selectedPaths.map(pathById),c=g.find(p=>p.sphSrc),bb=bboxOfPath(c),cy=(bb.t+bb.b)/2,R=(bb.b-bb.t)/2;
      let near=0,maxLat=0;g.filter(p=>!p.sphSrc).forEach(p=>(p.subpaths||[p]).forEach(q=>q.nodes.forEach(n=>{const d=Math.min(Math.abs(n.y-(cy-R)),Math.abs(n.y-(cy+R)));if(d<R*0.2)near++;maxLat=Math.max(maxLat,Math.abs(n.y-cy)/R);})));
      S=mk();state.paths=[S.b1,S.b2,S.c];setSelection(state.paths.map(p=>p.id));doSphereWrap(true);
      let g2=state.selectedPaths.map(pathById);let maxLat2=0;g2.filter(p=>!p.sphSrc).forEach(p=>(p.subpaths||[p]).forEach(q=>q.nodes.forEach(n=>{maxLat2=Math.max(maxLat2,Math.abs(n.y-cy)/R);})));
      return{nearPole:near,maxLat:+maxLat.toFixed(2),maxLatNoFrame:+maxLat2.toFixed(2)};})())"""))
    if frt["nearPole"] != 0: fails.append(f"SPHERE-FRAME: 枠ありで極付近に点があってはいけない: {frt}")
    if not (frt["maxLat"] < 0.6): fails.append(f"SPHERE-FRAME: 枠ありは中央の緯度に収まるはず: {frt}")
    if not (frt["maxLatNoFrame"] > 0.8): fails.append(f"SPHERE-FRAME: 枠なしは極近くまで届くはず（枠が効いている証拠）: {frt}")

    # R2) 極の継ぎ目: 外接枠の上端に触れる全幅の帯→極のまわりで継ぎ目の点の重なりが無い・全点が半径内
    pole = json.loads(ev(sock, """JSON.stringify((()=>{
      const rect=(x,y,w,h)=>({id:nextId++,closed:true,layerId:1,fill:'#cc3333',stroke:'none',width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      state.paths=[rect(150,150,500,40),circ(400,400,250)];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      $('livePrev').checked=false;$('sphTilt').value=25;$('sphSpin').value=0;$('sphAxis').value=0;$('sphBack').value='hide';
      setSelection(state.paths.map(p=>p.id));const ok=doSphereWrap(true);
      const g=state.selectedPaths.map(pathById),c=g.find(p=>p.sphSrc),bb=bboxOfPath(c),cx=(bb.l+bb.r)/2,cy=(bb.t+bb.b)/2,R=(bb.b-bb.t)/2;
      let maxOver=0,seam=0;
      g.filter(p=>!p.sphSrc).forEach(p=>(p.subpaths||[p]).forEach(q=>{const ns=q.nodes;
        ns.forEach(n=>{maxOver=Math.max(maxOver,Math.hypot(n.x-cx,n.y-cy)/R);});
        for(let i=0;i<ns.length;i++)for(let j=i+2;j<ns.length;j++){if(i===0&&j===ns.length-1)continue;if(Math.hypot(ns[i].x-ns[j].x,ns[i].y-ns[j].y)<0.5)seam++;}}));
      return{ok,maxOver:+maxOver.toFixed(3),seam};})())"""))
    if not pole["ok"]: fails.append(f"SPHERE-POLE: wrap失敗: {pole}")
    if not (pole["maxOver"] <= 1.03): fails.append(f"SPHERE-POLE: 全点が半径内のはず: {pole}")
    if pole["seam"] != 0: fails.append(f"SPHERE-POLE: 極のつなぎ目の点の重なりがある（継ぎ目）: {pole}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;$('livePrev').checked=true;render();true")

    # R2b) 継ぎ目(経度±180°): 枠つき横いっぱいの帯＋円を裏側=薄く出すで貼る→帯1本あたり表1・裏1（左右の端で切れない）。回転180でも表が1つ
    SEAMJS = """JSON.stringify((()=>{
      const rect=(x,y,w,h,f,s)=>({id:nextId++,closed:true,layerId:1,fill:f,stroke:s,width:1,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]});
      const circ=(cx,cy,r)=>{const ns=[];for(let i=0;i<48;i++){const a=i/48*2*Math.PI;ns.push(node(cx+r*Math.cos(a),cy+r*Math.sin(a)));}return{id:nextId++,closed:true,layerId:1,fill:'#882222',stroke:'none',width:1,nodes:ns};};
      state.paths=[rect(150,150,500,500,'none','none'),rect(150,390,500,20,'#cc3333','none'),circ(400,400,250)];
      state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;
      $('livePrev').checked=false;$('sphTilt').value=25;$('sphSpin').value=%d;$('sphAxis').value=0;$('sphBack').value='faint';$('sphBackOp').value=25;
      setSelection(state.paths.map(p=>p.id));const ok=doSphereWrap(true);
      const g=state.selectedPaths.map(pathById),c=g.find(p=>p.sphSrc),bb=bboxOfPath(c),cx=(bb.l+bb.r)/2,cy=(bb.t+bb.b)/2,R=(bb.b-bb.t)/2;
      const isBack=p=>p.opacity!=null&&Math.abs(p.opacity-0.25)<0.01,nc=g.filter(p=>!p.sphSrc);
      let maxOver=0;nc.forEach(p=>(p.subpaths||[p]).forEach(q=>q.nodes.forEach(n=>{maxOver=Math.max(maxOver,Math.hypot(n.x-cx,n.y-cy)/R);})));
      return{ok,front:nc.filter(p=>!isBack(p)).length,back:nc.filter(isBack).length,maxOver:+maxOver.toFixed(3)};})())"""
    s0 = json.loads(ev(sock, SEAMJS % 0)); ev(sock, "undo();true")
    s180 = json.loads(ev(sock, SEAMJS % 180)); ev(sock, "undo();true")
    if not s0["ok"]: fails.append(f"SPHERE-SEAM: wrap失敗: {s0}")
    if s0["front"] != 1: fails.append(f"SPHERE-SEAM: 回転0で表が1図形のはず（±180°で切れない）: {s0}")
    if s0["back"] != 1: fails.append(f"SPHERE-SEAM: 回転0で裏が1図形のはず（±180°で切れない）: {s0}")
    if s180["front"] != 1: fails.append(f"SPHERE-SEAM: 回転180でも表が1図形のはず: {s180}")
    if s180["back"] != 1: fails.append(f"SPHERE-SEAM: 回転180で裏が1図形のはず: {s180}")
    if not (s0["maxOver"] <= 1.03 and s180["maxOver"] <= 1.03): fails.append(f"SPHERE-SEAM: 全点が半径内のはず: {s0} {s180}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;$('livePrev').checked=true;render();true")

    # R4) トレース後も下絵を消さず隠す／開き直さず2回目／Undoで下絵が戻る／チェックで表示切替
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;traceImage=null;clearUnderlay();render();true")
    ev(sock, """(()=>{const cv=document.createElement('canvas');cv.width=300;cv.height=300;const c=cv.getContext('2d');
      c.fillStyle='#ffffff';c.fillRect(0,0,300,300);c.fillStyle='#2244cc';c.fillRect(60,60,180,180);
      window.__tr=cv.toDataURL('image/png');return true;})()""")
    ev(sock, """(async()=>{const r=await fetch(window.__tr);const b=await r.blob();
      loadTraceImage(new File([b],'tr.png',{type:'image/png'}));return true;})()""", await_promise=True)
    for _ in range(100):
        if ev(sock, "!document.getElementById('traceRun').disabled"): break
        time.sleep(0.2)
    pos = json.loads(ev(sock, "JSON.stringify({x:underlayBounds.x,y:underlayBounds.y})"))
    do_trace(sock, 2, 1.2, 3, 360, True)
    aft = json.loads(ev(sock, """JSON.stringify((()=>({hasBounds:!!underlayBounds,hasImg:!!traceImage,
      disp:document.getElementById('underlay').style.display,checked:document.getElementById('underlayShow').checked,
      samePos:(Math.abs(underlayBounds.x-(%s))<0.5&&Math.abs(underlayBounds.y-(%s))<0.5)}))())""" % (pos["x"], pos["y"])))
    if not aft["hasBounds"]: fails.append(f"TRACE-REDO: トレース後も下絵(underlayBounds)が残るはず: {aft}")
    if not aft["hasImg"]: fails.append(f"TRACE-REDO: トレース後も画像(traceImage)が残るはず: {aft}")
    if aft["disp"] != "none": fails.append(f"TRACE-REDO: トレース後は下絵が隠れるはず: {aft}")
    if aft["checked"]: fails.append(f"TRACE-REDO: トレース後は『下絵を表示』がオフのはず: {aft}")
    if not aft["samePos"]: fails.append(f"TRACE-REDO: トレース後も下絵の位置が変わらないはず: {aft}")
    info2 = do_trace(sock, 3, 1.2, 3, 360, True)
    if "レイヤー化した" not in info2: fails.append(f"TRACE-REDO: 開き直さずに2回目のトレースができるはず: {info2}")
    ev(sock, "undo();undo();true")
    back = json.loads(ev(sock, """JSON.stringify((()=>({hasBounds:!!underlayBounds,disp:document.getElementById('underlay').style.display,checked:document.getElementById('underlayShow').checked}))())"""))
    if not (back["hasBounds"] and back["disp"] != "none" and back["checked"]):
        fails.append(f"TRACE-REDO: Undoで下絵が表示に戻るはず: {back}")
    tog = json.loads(ev(sock, """JSON.stringify((()=>{const c=document.getElementById('underlayShow');
      c.checked=false;c.dispatchEvent(new Event('change'));const h=document.getElementById('underlay').style.display;
      c.checked=true;c.dispatchEvent(new Event('change'));const s=document.getElementById('underlay').style.display;
      return{hidden:h,shown:s};})())"""))
    if not (tog["hidden"] == "none" and tog["shown"] != "none"):
        fails.append(f"TRACE-REDO: 『下絵を表示』で表示/非表示が切り替わるはず: {tog}")
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'L',visible:true}];state.activeLayer=1;traceImage=null;clearUnderlay();render();true")

    # 61) P1（波7）: PDFに入らない効果を書き出す前に知らせる（光彩の図形→「入りません（1個の図形）」／効果なし→出ない）
    p1 = json.loads(ev(sock, """JSON.stringify((()=>{
      const orig=window.prompt;let cap='';window.prompt=(m)=>{cap=m;return null;};
      const r={id:nextId++,closed:true,fill:'#cccccc',stroke:'none',width:1,layerId:state.activeLayer,glow:{r:8,color:'#ffd54f',alpha:0.6},nodes:[[100,100],[200,100],[200,200],[100,200]].map(c=>node(c[0],c[1]))};
      state.paths=[r];state.selectedPath=null;state.selectedPaths=[];render();
      exportPdf(false);const withFx=cap;
      delete r.glow;cap='';exportPdf(false);const noFx=cap;
      window.prompt=orig;
      return {withFx,noFx};
    })())"""))
    if not ('PDFには影・光彩・ぼかし輪郭が入りません（1個の図形）' in p1['withFx'] and '入りません' not in p1['noFx']):
        fails.append(f"PDF-FX-NOTE: 効果のある図形でPDF書き出しの文に「入りません（1個の図形）」が出て・効果なしでは出ないはず: {p1}")

    # 62) L1（波7）: 多角形・星をあとから直せる（6→3／星5→8・鋭さ50→30／回転30+2倍の後も／手で動かすと外れてステータス／Undo／保存open）
    sh = json.loads(ev(sock, """JSON.stringify((()=>{
      const cp=document.getElementById('copyTransform');if(cp)cp.checked=false;
      const mkPoly=(cx,cy,r,sides)=>{state.tool='polygon';document.getElementById('polySides').value=sides;
        state.draft=newPath(regularNodes('polygon',{x:cx,y:cy},{x:cx,y:cy-r},false),true);
        state.drag={type:'shape',start:{x:cx,y:cy}};endShape();state.drag=null;return pathById(state.selectedPath);};
      const cen=p=>{const n=p.nodes;return[n.reduce((s,q)=>s+q.x,0)/n.length,n.reduce((s,q)=>s+q.y,0)/n.length];};
      const rad=p=>{const[cx,cy]=cen(p);return Math.hypot(p.nodes[0].x-cx,p.nodes[0].y-cy);};
      const setF=(id,v)=>{const e=document.getElementById(id);e.value=String(v);e.dispatchEvent(new Event('change',{bubbles:true}));};
      // 6角形→3角形
      state.paths=[];let hex=mkPoly(400,400,60,6);const id0=hex.id;const fillBefore=hex.fill;
      const hasShape=!!hex.shape&&hex.shape.type==='polygon'&&hex.shape.sides===6;
      setF('polySides',3);hex=pathById(id0);
      const to3={n:hex.nodes.length,cx:Math.round(cen(hex)[0]),cy:Math.round(cen(hex)[1]),r:Math.round(rad(hex)),fill:hex.fill,sides:hex.shape&&hex.shape.sides};
      setSelection([id0]);updateControls();const panelSides=document.getElementById('polySides').value;
      undo();const undoN=pathById(id0).nodes.length;
      // 星5→8・鋭さ50→30
      state.paths=[];state.tool='star';document.getElementById('starPoints').value=5;document.getElementById('starRatio').value=50;
      state.draft=newPath(regularNodes('star',{x:400,y:400},{x:400,y:340},false),true);state.drag={type:'shape',start:{x:400,y:400}};endShape();state.drag=null;
      let st=pathById(state.selectedPath);const sid=st.id;const starHas=!!st.shape&&st.shape.points===5;
      setF('starPoints',8);setF('starRatio',30);st=pathById(sid);
      const starAfter={n:st.nodes.length,points:st.shape&&st.shape.points,ratio:st.shape&&Math.round(st.shape.ratio*100)};
      // 回転30+2倍の後に角数変更→中心と2倍の大きさが残る
      state.paths=[];let h2=mkPoly(400,400,60,6);const h2id=h2.id;setSelection([h2id]);
      rotateSelection(30);scaleSelection(200);
      setF('polySides',3);h2=pathById(h2id);
      const xf={n:h2.nodes.length,cx:Math.round(cen(h2)[0]),cy:Math.round(cen(h2)[1]),r:Math.round(rad(h2))};
      // 手で点を動かすと形の元が外れ、欄を変えても変わらずステータス
      state.paths=[];let h3=mkPoly(400,400,60,6);const h3id=h3.id;setSelection([h3id]);
      h3.nodes[0].x+=25;h3.nodes[0].y-=25;render();
      setF('polySides',4);h3=pathById(h3id);
      const manual={n:h3.nodes.length,shapeGone:!h3.shape,status:document.getElementById('status').textContent};
      // 保存→開き直しで形の元が残り直せる
      state.paths=[];mkPoly(300,300,50,5);
      const j=snapshot();state.paths=[];restore(j);const reopen=state.paths[0];
      const reHas=!!reopen.shape&&reopen.shape.sides===5;
      setSelection([reopen.id]);setF('polySides',7);const reEdit=state.paths[0].nodes.length;
      return {hasShape,fillBefore,to3,panelSides,undoN,starHas,starAfter,xf,manual,reHas,reEdit};
    })())"""))
    if not (sh['hasShape'] and sh['to3']['n']==3 and abs(sh['to3']['cx']-400)<=2 and abs(sh['to3']['cy']-400)<=2
            and abs(sh['to3']['r']-60)<=2 and sh['to3']['fill']==sh['fillBefore'] and sh['to3']['sides']==3
            and sh['panelSides']=='3' and sh['undoN']==6
            and sh['starHas'] and sh['starAfter']['n']==16 and sh['starAfter']['points']==8 and sh['starAfter']['ratio']==30
            and sh['xf']['n']==3 and abs(sh['xf']['cx']-400)<=3 and abs(sh['xf']['cy']-400)<=3 and abs(sh['xf']['r']-120)<=3
            and sh['manual']['n']==6 and sh['manual']['shapeGone'] and '手で直した' in sh['manual']['status']
            and sh['reHas'] and sh['reEdit']==7):
        fails.append(f"SHAPE-EDIT: 多角形・星を後から直せ・移動回転拡縮後も保て・手で崩すと外れ・保存openで残るはず: {sh}")
    ev(sock, "state.paths=[];state.selectedPath=null;state.selectedPaths=[];state.tool='select';render();true")

    # 63) L2（波7後半）: 角丸の四角を、大きさを変えても同じ半径に保つ
    rr = json.loads(ev(sock, """JSON.stringify((()=>{
      const cp=document.getElementById('copyTransform');if(cp)cp.checked=false;
      const mkRect=(w,h)=>{state.tool='rect';const l=400-w/2,t=400-h/2;
        state.draft=newPath(shapeNodes('rect',{x:l,y:t},{x:l+w,y:t+h},false),true);
        state.drag={type:'shape',start:{x:l,y:t}};endShape();state.drag=null;return pathById(state.selectedPath);};
      const radii=p=>{const n=p.nodes;if(n.length!==8)return[];const out=[];for(let i=0;i<4;i++){const a=n[2*i],b=n[2*i+1];out.push(Math.hypot(a.x-b.x,a.y-b.y)/Math.SQRT2);}return out;};
      const close4=(arr,t)=>arr.length===4&&arr.every(r=>Math.abs(r-t)<=0.5);
      const setCorner=(v)=>{document.getElementById('livePrev').checked=true;const e=document.getElementById('cornerR');e.value=String(v);e.dispatchEvent(new Event('input',{bubbles:true}));};
      const setGeom=(id,v)=>{document.getElementById('geomLock').checked=false;const e=document.getElementById(id);e.value=String(v);e.dispatchEvent(new Event('change',{bubbles:true}));};
      // 欄に28が出る
      state.paths=[];let r1=mkRect(160,100);setSelection([r1.id]);setCorner(28);
      setSelection([r1.id]);updateControls();const panel28=document.getElementById('cornerR').value;
      // W520 比率固定（一様拡大 3.25倍）
      scaleSelection(325);r1=pathById(r1.id);const rad1=radii(r1);
      const key1={w:Math.round(r1.shape.w),h:Math.round(r1.shape.h),cr:Math.round(r1.shape.cornerR)};
      // W520 比率なし（幅だけ）
      state.paths=[];let r2=mkRect(160,100);setSelection([r2.id]);setCorner(28);setGeom('geomW',520);
      r2=pathById(r2.id);const rad2=radii(r2);const key2={w:Math.round(r2.shape.w),h:Math.round(r2.shape.h)};
      // H300
      state.paths=[];let r3=mkRect(160,100);setSelection([r3.id]);setCorner(28);setGeom('geomH',300);
      r3=pathById(r3.id);const rad3=radii(r3);const key3={w:Math.round(r3.shape.w),h:Math.round(r3.shape.h)};
      // 30°回してから一様拡大2倍
      state.paths=[];let r4=mkRect(160,100);setSelection([r4.id]);setCorner(28);rotateSelection(30);scaleSelection(200);
      r4=pathById(r4.id);const rad4=radii(r4);const has4=!!(r4.shape&&r4.shape.type==='rect');
      // 欄 28→40
      state.paths=[];let r5=mkRect(160,100);setSelection([r5.id]);setCorner(28);setCorner(40);
      r5=pathById(r5.id);const rad5=radii(r5);
      // 手で点を動かすと形の元が外れる（ふつうのパスに戻る）
      state.paths=[];let r6=mkRect(160,100);setSelection([r6.id]);setCorner(28);
      r6.nodes[0].x+=20;r6.nodes[0].y-=20;render();const gone=!r6.shape;
      // 保存→開き直しで形の元が残り、欄で変えられる
      state.paths=[];let r7=mkRect(160,100);setSelection([r7.id]);setCorner(28);
      const j=snapshot();state.paths=[];restore(j);const ro=state.paths[0];
      const reHas=!!(ro.shape&&ro.shape.type==='rect'&&Math.round(ro.shape.cornerR)===28);const radRe=radii(ro);
      setSelection([ro.id]);setCorner(40);const radRe40=radii(state.paths[0]);
      return {panel28,rad1,key1,rad2,key2,rad3,key3,rad4,has4,rad5,gone,reHas,radRe,radRe40};
    })())"""))
    def close4(arr,t):
        return len(arr)==4 and all(abs(r-t)<=0.5 for r in arr)
    if not (rr['panel28']=='28'
            and close4(rr['rad1'],28) and rr['key1']['w']==520 and rr['key1']['h']==325 and rr['key1']['cr']==28
            and close4(rr['rad2'],28) and rr['key2']['w']==520 and rr['key2']['h']==100
            and close4(rr['rad3'],28) and rr['key3']['w']==160 and rr['key3']['h']==300
            and close4(rr['rad4'],28) and rr['has4']
            and close4(rr['rad5'],40)
            and rr['gone']
            and rr['reHas'] and close4(rr['radRe'],28) and close4(rr['radRe40'],40)):
        fails.append(f"RECT-SHAPE: 角丸四角が拡縮しても角Rを保ち・欄で変えられ・手崩れで外れ・保存openで残るはず: {rr}")
    ev(sock, "state.paths=[];state.selectedPath=null;state.selectedPaths=[];state.tool='select';render();true")

    # 64) 波8 案B改（#11）: 固定の枠（レイヤー・いつも出ている・タブ）＋4タブ。id は238個のまま・revealPanelで隠れたタブが開く・localStorageに覚える
    pt = json.loads(ev(sock, """JSON.stringify((()=>{
      const tabs=[...document.querySelectorAll('#panel .ptab')].map(t=>t.dataset.ptab);
      const panes=[...document.querySelectorAll('#panel .ppane')].map(p=>p.dataset.ppane);
      // いつも出ている枠にある欄は、どのタブでも見えている（.ppaneの外）
      const fixedIds=['geomX','geomY','geomW','geomH','geomUnit','geomLock','fill','fillHex','stroke','strokeHex','width','opacity'];
      const fixedOk=fixedIds.every(id=>{const e=document.getElementById(id);return e&&!e.closest('.ppane');});
      // 描くに切替→配置タブの要素(group)は display:none、描くタブの要素(polySides)は見える
      setPanelTab('draw');
      const drawOn=document.querySelector('.ptab[data-ptab="draw"]').classList.contains('on')&&document.querySelector('.ppane[data-ppane="draw"]').classList.contains('on');
      const arrangeHidden=getComputedStyle(document.querySelector('.ppane[data-ppane="arrange"]')).display==='none';
      // revealPanel: 配置タブの要素(#group)を見せる→配置タブが開く
      revealPanel(document.getElementById('group'));
      const switched=document.querySelector('.ppane[data-ppane="arrange"]').classList.contains('on')&&localStorage.getItem('bkPanelTab')==='arrange';
      // 不明なタブ名は draw に落ちる
      setPanelTab('nope');const fallback=document.querySelector('.ptab[data-ptab="draw"]').classList.contains('on');
      // #panel 直下の id の個数（固定枠＋ppane内の全部）
      const panelIds=[...document.querySelectorAll('#panel [id]')].length;
      return {tabs,panes,fixedOk,drawOn,arrangeHidden,switched,fallback,panelIds};
    })())"""))
    if not (pt["tabs"]==['draw','arrange','color','file'] and pt["panes"]==['draw','arrange','color','file']
            and pt["fixedOk"] and pt["drawOn"] and pt["arrangeHidden"] and pt["switched"] and pt["fallback"]):
        fails.append(f"PANEL-TABS: 案B改＝固定枠＋4タブ・revealPanelで隠れタブが開く・localStorageに覚える・不明名はdrawのはず: {pt}")
    ev(sock, "setPanelTab('draw');try{localStorage.removeItem('bkPanelTab');}catch(e){}true")

    # 65) 波9（#11の続き・2026-11-02）: 塗りと線の見分け（線の見本は枠だけ・なしは赤い斜線と「なし」）・同じ属性で選択は色タブの2番目・PowerPointの欄に SPEC.md のメモが無い
    fsl = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];const L=state.layers[0].id;
      const p={id:nextId++,layerId:L,closed:true,fill:'#c62828',stroke:'#183251',width:2,nodes:[node(100,100),node(300,100),node(300,250),node(100,250)]};
      state.paths.push(p);render();setSelection([p.id]);render();
      const sw=getComputedStyle(document.getElementById('stroke')).getPropertyValue('--sw').trim();
      const fn=document.getElementById('fillNone');fn.checked=true;fn.dispatchEvent(new Event('change'));
      const noneOn={cls:document.getElementById('fill').classList.contains('sw-none'),hex:document.getElementById('fillHex').value,grey:document.getElementById('fillHex').classList.contains('hex-none'),fill:pathById(p.id).fill};
      fn.checked=false;fn.dispatchEvent(new Event('change'));
      const noneOff=!document.getElementById('fill').classList.contains('sw-none')&&!document.getElementById('fillHex').classList.contains('hex-none');
      const order=[...document.querySelectorAll('.ppane[data-ppane="color"] h2')].map(h=>h.textContent.trim());
      const hint=[...document.querySelectorAll('.ppane[data-ppane="file"] .hint')].map(h=>h.textContent).join(' ');
      state.paths=[];state.selectedPath=null;state.selectedPaths=[];render();
      return {sw,noneOn,noneOff,order,specNote:hint.includes('SPEC.md')};
    })())"""))
    if not (fsl["sw"] == "#183251" and fsl["noneOn"]["cls"] and fsl["noneOn"]["hex"] == "なし" and fsl["noneOn"]["grey"] and fsl["noneOn"]["fill"] == "none"
            and fsl["noneOff"] and fsl["order"][:2] == ["パレット", "同じ属性で選択"] and not fsl["specNote"]):
        fails.append(f"FILL-STROKE-LOOK: 線の見本の枠の色・なしの斜線と「なし」・同じ属性で選択が色タブの2番目・SPEC.mdのメモ無し のはず: {fsl}")

    # 66) 波10（2026-11-02）: 塗りなし・線なしを外したら前の色に戻る（グラデも）。選び直しても・保存の型の確かめ（sanitizePrevColors）も
    nr = json.loads(ev(sock, """JSON.stringify((()=>{
      state.paths=[];const L=state.layers[0].id;const sq=(x)=>[node(x,100),node(x+200,100),node(x+200,250),node(x,250)];
      const a={id:nextId++,layerId:L,closed:true,fill:'#c62828',stroke:'#183251',width:2,nodes:sq(100)};
      const b={id:nextId++,layerId:L,closed:true,fill:'#21537f',gradient:{c1:'#21537f',c2:'#ffd54f',angle:0,type:'radial'},stroke:'#121212',width:2,nodes:sq(500)};
      state.paths.push(a,b);render();
      const tog=(id,on)=>{const e=document.getElementById(id);e.checked=on;e.dispatchEvent(new Event('change'));};
      const sel=id=>{setSelection([id]);render();};
      sel(a.id);tog('fillNone',true);const aNone=pathById(a.id).fill;sel(b.id);sel(a.id);const swatchKept=document.getElementById('fill').value;tog('fillNone',false);const aBack=pathById(a.id).fill;
      sel(b.id);tog('fillNone',true);tog('fillNone',false);const g=pathById(b.id).gradient;
      sel(a.id);tog('strokeNone',true);sel(b.id);sel(a.id);tog('strokeNone',false);const sBack=pathById(a.id).stroke;
      const bad={prevFill:'javascript:x',prevStroke:'#12345g',prevGradient:{c1:'#fff'}};sanitizePrevColors(bad);
      const good={prevFill:'#c62828',prevStroke:'#183251',prevGradient:{c1:'#21537f',c2:'#ffd54f'}};sanitizePrevColors(good);
      state.paths=[];state.selectedPath=null;state.selectedPaths=[];render();
      return {aNone,swatchKept,aBack,grad:g?{type:g.type,c2:g.c2}:null,sBack,badLeft:Object.keys(bad),goodLeft:Object.keys(good)};
    })())"""))
    if not (nr["aNone"] == "none" and nr["swatchKept"] == "#c62828" and nr["aBack"] == "#c62828" and nr["grad"] == {"type": "radial", "c2": "#ffd54f"}
            and nr["sBack"] == "#183251" and nr["badLeft"] == [] and sorted(nr["goodLeft"]) == ["prevFill", "prevGradient", "prevStroke"]):
        fails.append(f"NONE-RESTORE: 塗りなし・線なしを外すと前の色（グラデも）に戻り、選び直しても欄が黒にならず、型の確かめで変な値は外れるはず: {nr}")

    # 67) 波10後半の続き（2026-11-02・Kiro）: ①小さい輪（2点で閉じる）も継ぎ目なしの輪になる ②左右の端の両方に触れる1枚（表裏にまたがる北極寄りの帯）は、端の辺を抜いて外周＋内周の輪になる＝回転180で表に縦の切れ目が出ない
    rs = json.loads(ev(sock, """JSON.stringify((()=>{
      const sph={cx:400,cy:400,R:250,bb:{l:150,t:150,w:500,h:500}};
      const sq=(t,b)=>({nodes:[node(150,t),node(650,t),node(650,b),node(150,b)],closed:true});
      $('sphAxis').value=0;$('sphTilt').value=60;$('sphSpin').value=0;const P60=sphereParams();
      const small=sphereRingNodes(sq(170,182),sph,P60);
      $('sphTilt').value=25;$('sphSpin').value=180;const P25=sphereParams();
      booleanScope.activate();booleanScope.project.clear();
      const regions=sphereFrontRegions(sph,P25);
      const fr=new booleanScope.CompoundPath({insert:false,children:regions.map(poly=>new booleanScope.Path({insert:false,closed:true,segments:poly.map(pt=>new booleanScope.Point(pt[0],pt[1]))}))});
      const front=fromPaperPath(sphereSealSeam(partToPaper(sq(202,230)).intersect(fr,{insert:false,trace:true}),sph.bb)).filter(q=>q.nodes&&q.nodes.length>=3);
      const ring=front.length===1?sphereSeamRing(front[0],sph,P25):null;
      $('sphTilt').value=20;$('sphSpin').value=0;
      return {small:!!small&&small.parts.length===2,frontPieces:front.length,ringLoops:ring?ring.length:0};
    })())"""))
    if not (rs["small"] and rs["frontPieces"] == 1 and rs["ringLoops"] == 2):
        fails.append(f"SPHERE-RING-SEAM: 小さい輪も輪になり、左右の端の両方に触れる1枚は外周＋内周の輪（2本）になるはず: {rs}")

    wave11_checks(sock, fails)
    wave12_checks(sock, fails)
    wave13_checks(sock, fails)
    wave14_checks(sock, fails)
    wave15_checks(sock, fails)
    wave16_checks(sock, fails)
    wave17_checks(sock, fails)

    chrome.terminate()
    print(("BEZIERKIT_FAIL\n" + "\n".join(fails)) if fails else
          "BEZIERKIT_OK (outline-trace / trace-fit / trace-res / layer-merge / openDocument / generic-import / "
          "select-same / pen-insert / simplify / smooth / clip-mask / lock / outline / width-tool / shape-builder / align-anchor / cap-fx / appearance / cad-copy / recolor / "
          "offset / offset-copy / offset-text / offset-open / halftone / halftone-tone / halftone-cmyk / halftone-paper / "
          "pptx-check / pptx-xml / pptx-open / pptx-textoff / pdf-import / pdf-export / artboards / swatches / symbols / repeats / knife / eraser / illust / clip-import / pdf-eps / boolean-appearance / boolean-multi / text-click-edit / underlay-artboard / input-enter-blur / rotate-copy-label / draw-style / effect-hex / zig-rough / opacity-zero / arrow-closed / radial-center / units / underlay-move / trace-ink / trace-upscale / trace-fit-ab / trace-corner / sphere-wrap / sphere-rewrap / sphere-frame / sphere-pole / sphere-seam / trace-redo / pdf-fx-note / shape-edit / rect-shape / panel-tabs / fill-stroke-look / none-restore / sphere-ring-seam / join-paths / text-align / place-image / compound / warp / f1-curve-bbox / f2-radial-spread / f3-spinner-undo / f4-underlay-undo / f4-text-bbox / f4-area-pptx / f4-grad-track / tidy-snaphv / tidy-sym / tidy-apply-undo / recolor-palette / recolor-palette-grad / corp-derive)")
    return 1 if fails else 0

def trace_file(img_path, out_svg):
    chrome, sock = boot()
    try:
        load_image(sock, "file://" + os.path.abspath(img_path))
        info = do_trace(sock, os.environ.get("COLORS", "8"), os.environ.get("TOL", "1.2"),
                        os.environ.get("MINPX", "3"), os.environ.get("RES", "360"),
                        os.environ.get("FIT", "1") != "0",
                        mode=os.environ.get("MODE", "regions"),
                        thresh=os.environ.get("THRESH", "50"), corner=os.environ.get("CORNER", "normal"))
        print("TRACE:", info)
        print("STATS:", ev(sock, STATS_JS))
        svg_text = ev(sock, "buildExportSvg(true)", timeout=600)
        with open(out_svg, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + svg_text)
        print("SVG:", out_svg, f"{len(svg_text):,} bytes")
    finally:
        chrome.terminate()
    return 0

def halftone_file(img_path, out_svg):
    """実画像を網点化してSVG保存＋キャンバスのスクショを撮る（目視用）。
    環境変数 PITCH/ANGLE/SHAPE/MODE/INK/SCALE/GAIN/INVERT で設定を変えられる"""
    chrome, sock = boot()
    try:
        load_image(sock, "file://" + os.path.abspath(img_path))
        ev(sock, "state.paths=[];render();true")
        info = do_halftone(sock, pitch=os.environ.get("PITCH", "10"), angle=os.environ.get("ANGLE", "45"),
                           shape=os.environ.get("SHAPE", "circle"), mode=os.environ.get("MODE", "am"),
                           ink=os.environ.get("INK", "mono"), scale=os.environ.get("SCALE", "100"),
                           gain=os.environ.get("GAIN", "100"), invert=os.environ.get("INVERT", "0") != "0",
                           paper=os.environ.get("PAPER", "1") != "0")
        print("HALFTONE:", info)
        print("STATS:", ev(sock, STATS_JS))
        svg_text = ev(sock, "buildExportSvg(true)", timeout=600)
        with open(out_svg, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + svg_text)
        print("SVG:", out_svg, f"{len(svg_text):,} bytes")
        # 目視用: アートボード全体が入るようにビューを合わせてキャンバスだけ撮る（UIは写さない）
        rect = ev(sock, """(()=>{const c=document.getElementById('canvas');
          setSelection([]); // 選択オーバーレイが網点を覆ってしまうので外す
          setView({x:0,y:0,w:ART.w,h:ART.w*c.clientHeight/c.clientWidth});
          const b=c.getBoundingClientRect();
          return{x:b.x,y:b.y,w:b.width,h:b.height*ART.h/(ART.w*c.clientHeight/c.clientWidth)};})()""")
        shot = call(sock, "Page.captureScreenshot", {"format": "png", "clip": {
            "x": rect["x"], "y": rect["y"], "width": rect["w"], "height": rect["h"], "scale": 1}})
        png = os.path.splitext(out_svg)[0] + ".png"
        with open(png, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print("PNG:", png)
    finally:
        chrome.terminate()
    return 0

def icons_check():
    fails = []
    chrome, sock = boot("file://" + os.path.join(HERE, "icons.html"),
                        "typeof ICONS!=='undefined' && document.querySelectorAll('.card').length>0")
    try:
        data = json.loads(ev(sock, """JSON.stringify((()=>{
          const ids=ICONS.map(i=>i.id);
          return {n:ICONS.length,cards:document.querySelectorAll('.card').length,
            dup:ids.length!==new Set(ids).size,
            numBad:ICONS.filter(i=>!(i.num>0)).map(i=>i.id),
            numDup:ICONS.length!==new Set(ICONS.map(i=>i.num)).size,
            badPath:ICONS.filter(i=>!i.paths||!i.paths.length||i.paths.some(p=>!/^\\s*[Mm]/.test(p.d))).map(i=>i.id),
            emptySvg:[...document.querySelectorAll('.card .icon svg')].filter(s=>!s.querySelector('path')).length};
        })())"""))
        if not data["n"] or data["cards"] != data["n"]: fails.append(f"ICONS: カード数がデータと不一致: {data}")
        if data["dup"]: fails.append("ICONS: idが重複している")
        if data["numBad"]: fails.append(f"ICONS: numが無い: {data['numBad']}")
        if data["numDup"]: fails.append("ICONS: numが重複している")
        if data["badPath"]: fails.append(f"ICONS: 不正なpath d: {data['badPath']}")
        if data["emptySvg"]: fails.append(f"ICONS: 空のSVGが{data['emptySvg']}個")
        filt = ev(sock, """(()=>{const s=document.getElementById('q');s.value='検索';
          s.dispatchEvent(new Event('input'));
          return document.querySelectorAll('.card:not(.hide)').length;})()""")
        if not (0 < filt < data["n"]): fails.append(f"ICONS: 検索で絞り込めるはず: {filt}/{data['n']}")
        svg = ev(sock, "svgText(ICONS[0])")
        if "currentColor" not in svg or "viewBox=\"0 0 96 96\"" not in svg:
            fails.append(f"ICONS: svgTextの出力が規約と違う: {svg[:120]}")
        # 編集セッションの往復(1/3): ✏️相当＝URLハッシュのpayloadを作る（localStorage非依存の輸送を検証）
        orig_d = ev(sock, "ICONS[0].paths[0].d")
        payload = ev(sock, """(()=>{
          localStorage.removeItem('bkIconOverrides');localStorage.removeItem('bkIconEdit');
          return '#editicon='+btoa(unescape(encodeURIComponent(JSON.stringify(
            {id:ICONS[0].id,name:ICONS[0].name,tags:ICONS[0].tags||[],paths:ICONS[0].paths}))));
        })()""")
    finally:
        chrome.terminate()

    # 往復(2/3): 全アイコンをBezierKitに読ませる網羅チェック→ICONS[0]を+1px動かして「アイコンへ反映」
    chrome, sock = boot(PAGE + payload, "typeof applyIconEdit==='function'&&!!iconEditSession")
    try:
        edit = json.loads(ev(sock, """(async()=>{
          const text=await fetch('icons-data.js').then(r=>r.text());
          (new Function(text))();
          const mk=ic=>'#editicon='+btoa(unescape(encodeURIComponent(JSON.stringify(
            {id:ic.id,name:ic.name,tags:ic.tags||[],paths:ic.paths}))));
          const loadFail=[];
          for(const ic of window.ICONS){
            try{
              location.hash=mk(ic);startIconEdit();
              if(!state.paths.filter(p=>!p.iconFrame).length)loadFail.push(ic.id);
            }catch(e){loadFail.push(ic.id+':'+e.message);}
          }
          location.hash=mk(window.ICONS[0]);startIconEdit();
          const body=state.paths.filter(p=>!p.iconFrame);
          body.forEach(p=>(p.subpaths||[p]).forEach(part=>part.nodes.forEach(n=>{
            n.x+=5;n.inX+=5;n.outX+=5;})));  // キャンバス5px=アイコン1px右へ
          render();applyIconEdit();
          const ov=JSON.parse(localStorage.getItem('bkIconOverrides')||'{}');
          return JSON.stringify({loadFail,frame:state.paths.some(p=>p.iconFrame),body:body.length,
            saved:Object.keys(ov),applyBtn:document.getElementById('iconApply').style.display!=='none'});
        })()""", await_promise=True))
        if edit["loadFail"]: fails.append(f"ICONS: BezierKitに読めないアイコン: {edit['loadFail']}")
        if not (edit["frame"] and edit["body"] > 0 and edit["saved"] and edit["applyBtn"]):
            fails.append(f"ICONS: 編集セッションが変: {edit}")
        # 往復(3/3): 同じタブでカタログへ遷移する。🚨file://のlocalStorageはChromeを再起動すると
        # 消える（プロファイルに残らない）ので、ここでChromeを落としてはいけない
        ev(sock, "location.href='icons.html'")
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            try:
                if ev(sock, "typeof ICONS!=='undefined' && document.querySelectorAll('.card').length>0"):
                    ready = True; break
            except Exception:
                pass
            time.sleep(0.3)
        if not ready: fails.append("ICONS: カタログへの遷移が完了しない")
        back = json.loads(ev(sock, """JSON.stringify((()=>{
          const edited=document.querySelectorAll('.card .edited').length;
          const copyBtn=document.getElementById('ovCopy').style.display!=='none';
          const ic=mergedIcons()[0];
          const entry=jsEntry(ic);
          const r={edited,copyBtn,changed:ic._edited===true,entryOk:entry.includes(ic.id)&&entry.includes('paths:')};
          localStorage.removeItem('bkIconOverrides');localStorage.removeItem('bkIconEdit');build();
          r.cleared=document.querySelectorAll('.card .edited').length===0;
          return r;
        })())"""))
        new_d = ev(sock, "ICONS[0].paths[0].d")
        if not (back["edited"] == 1 and back["copyBtn"] and back["changed"] and back["entryOk"] and back["cleared"]):
            fails.append(f"ICONS: 編集の反映/破棄が変: {back}")
        if new_d != orig_d: fails.append("ICONS: icons-data.js本体が書き換わっている（上書きはlocalStorageのみのはず）")
    finally:
        chrome.terminate()
    print(("ICONS_FAIL\n" + "\n".join(fails)) if fails else
          f"ICONS_OK ({data['n']}個 / 検索 / 96viewBox / currentColor / 編集往復)")
    return 1 if fails else 0

def pptx_file(src, out_pptx, pdf_out=None):
    """src=BezierKitで開けるSVG か 'fixture'。PPTXと、見比べ用のPNG2枚（BezierKitの描画／LibreOfficeでPPTXを描画）を出す"""
    chrome, sock = boot()
    try:
        if src == "fixture":
            ev(sock, PPTX_FIXTURE_JS)
        elif src.lower().endswith((".ai", ".pdf")):  # AI／PDF → PPTX の通し
            ev(sock, PDF_IMPORT_JS % (json.dumps(base64.b64encode(open(src, "rb").read()).decode()), json.dumps(os.path.basename(src))), await_promise=True, timeout=300)
        else:
            text = open(src, encoding="utf-8").read()
            # 起動時の見本（コッホ雪片）を消してから開く。残すと背景の後ろに隠れたまま書き出しに入る
            ev(sock, "state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();true")
            ev(sock, "(async()=>{await openDocument(new File([%s],%s,{type:'image/svg+xml'}));return true;})()"
               % (json.dumps(text), json.dumps(os.path.basename(src))), await_promise=True)
        print(json.dumps(json.loads(ev(sock, "JSON.stringify(pptxCheck())")), ensure_ascii=False))
        got = json.loads(ev(sock, PPTX_BLOB_JS % os.environ.get("TEXTBOX", "true"), await_promise=True))
        os.makedirs(os.path.dirname(os.path.abspath(out_pptx)), exist_ok=True)
        with open(out_pptx, "wb") as f: f.write(base64.b64decode(got["b64"]))
        png = ev(sock, """(async()=>{const img=new Image();const url=URL.createObjectURL(new Blob([buildExportSvg(false)],{type:'image/svg+xml'}));
          await new Promise((ok,ng)=>{img.onload=ok;img.onerror=ng;img.src=url;});const c=document.createElement('canvas');c.width=ART.w;c.height=ART.h;
          c.getContext('2d').drawImage(img,0,0);return c.toDataURL('image/png').split(',')[1];})()""", await_promise=True)
        base = os.path.splitext(out_pptx)[0]
        with open(base + ".bk.png", "wb") as f: f.write(base64.b64decode(png))
        if src.lower().endswith(".svg"):  # 元のSVGをChromeでそのまま描いたもの（見比べの正解）
            src_png = ev(sock, """(async()=>{const t=%s;const img=new Image();const url=URL.createObjectURL(new Blob([t],{type:'image/svg+xml'}));
              await new Promise((ok,ng)=>{img.onload=ok;img.onerror=ng;img.src=url;});const w=img.naturalWidth||ART.w,h=img.naturalHeight||ART.h;
              const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,w,h);x.drawImage(img,0,0,w,h);
              return c.toDataURL('image/png').split(',')[1];})()""" % json.dumps(open(src, encoding="utf-8").read()), await_promise=True)
            with open(base + ".src.png", "wb") as f: f.write(base64.b64decode(src_png))
        if pdf_out:  # 同じ絵をPDFでも書き出す（verify で macOS の描画と並べる）
            with open(pdf_out, "wb") as f: f.write(ev(sock, "buildPdf({textBox:false,selectionOnly:false}).text").encode("latin-1"))
    finally:
        chrome.terminate()
    print(json.dumps(pptx_shapes(out_pptx) | {"names": None}, ensure_ascii=False, default=str))
    outdir = os.path.dirname(os.path.abspath(out_pptx))
    subprocess.run(["soffice", "--headless", "--convert-to", "png", "--outdir", outdir, out_pptx], capture_output=True, timeout=180)
    lo = base + ".png"
    if os.path.exists(lo):
        os.replace(lo, base + ".lo.png")
    print("PPTX_OK", out_pptx, base + ".bk.png", base + ".lo.png")
    return 0

# ---- 見比べ・実機確認の道具（2026-10-14 利用者「ボタン押させずに進められないかな」）----
# 確認作業を全部このスクリプトの単体コマンド（python3 cdp-check.py …＝承認済み）に入れる。
# シェルで && ・パイプ・heredoc・cp・osascript を組むと毎回承認が出るため。一時ファイルは WORK の下に作り、次の実行の最初に消す
# /tmp や隠しフォルダに置くと PowerPoint（サンドボックス）が開けずに止まった→ワークスペース内の _check に置く
# （公開コピーは kits-repo-export.py の KIT_INCLUDE_ONLY で入らない）
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_check")

def fresh_dir(name):
    import shutil
    path = os.path.join(WORK, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path

def mac_render(src, out_png, width=1600):
    """macOSのPDF描画（sips）でAI／PDFを画像にする。正解に一番近い見本として使う"""
    import shutil
    tmp = os.path.splitext(out_png)[0] + ".src.pdf"
    shutil.copyfile(src, tmp)
    subprocess.run(["sips", "-s", "format", "png", "-Z", str(width), tmp, "--out", out_png], capture_output=True, timeout=180)
    os.remove(tmp)
    return out_png if os.path.exists(out_png) else None

def compare_png(pairs, out_png, crop=""):
    """[(ラベル, PNG)] を縦に並べた見比べ画像。crop="x,y,w;x,y,w"（幅1600に揃えた座標）で拡大する所を選べる"""
    from PIL import Image, ImageDraw
    crops = [tuple(map(int, c.split(","))) for c in crop.split(";") if c.strip()]
    rows = []
    for label, path in pairs:
        if not path or not os.path.exists(path):
            continue
        im = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", im.size, "white"); bg.alpha_composite(im); im = bg.convert("RGB")
        im = im.resize((1600, round(im.height * 1600 / im.width)))
        tiles = [im.crop((x, y, x + w, y + w)).resize((300, 300)) for x, y, w in crops] if crops else [im.resize((900, round(im.height * 900 / 1600)))]
        rows.append((label, tiles))
    if not rows:
        return None
    tw, th = sum(t.width for t in rows[0][1]), max(t.height for t in rows[0][1])
    W = Image.new("RGB", (tw, (th + 28) * len(rows)), "white"); d = ImageDraw.Draw(W)
    for r, (label, tiles) in enumerate(rows):
        y = r * (th + 28); d.text((6, y + 6), label, fill="#c62828")
        x = 0
        for t in tiles:
            W.paste(t, (x, y + 28)); x += t.width
    W.save(out_png)
    return out_png

def ppt_open(pptx):
    """PowerPoint実機で開いて、最上位の図形数と1つ目の名前を読み、保存せずに閉じる。修復ダイアログが出ると時間切れになる"""
    # 開いたファイルだけを full name で探して触る。active presentation を使うと、利用者が開いている別のデッキを閉じかねない
    script = '''on run argv
  set target to item 1 of argv
  tell application "Microsoft PowerPoint"
    with timeout of 120 seconds
      set p to missing value
      repeat 40 times
        repeat with i from 1 to count of presentations
          if (full name of presentation i) is target then set p to presentation i
        end repeat
        if p is not missing value then exit repeat
        delay 1
      end repeat
      if p is missing value then error "40秒待っても開かなかった（修復かアクセス許可のダイアログが出ていないか見る）: " & target
      set n to count of shapes of slide 1 of p
      set g to name of shape 1 of slide 1 of p
      set s to count of slides of p
      close p saving no
    end timeout
  end tell
  return "slides=" & s & " topShapes=" & n & " shape1=" & g
end run'''
    # AppleScript の open は -9074（サンドボックスの拒否）で開けなくなった（2026-10-14）。
    # Finderで開くのと同じ open -a で渡すと、PowerPointにファイルの許可が付く。あとはAppleScriptで探して数えて閉じる
    import shutil
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ppt-check.pptx")
    shutil.copyfile(pptx, here)
    try:
        subprocess.run(["open", "-a", "Microsoft PowerPoint", here], capture_output=True, timeout=60)
        r = subprocess.run(["osascript", "-", here], input=script, capture_output=True, text=True, timeout=180)
    finally:
        os.remove(here)
    out = (r.stdout or r.stderr).strip()
    print(("PPT_OPEN_OK " if r.returncode == 0 else "PPT_OPEN_FAIL ") + out)
    return r.returncode

RENDER_PNG_JS = r"""(async()=>{const img=new Image();const url=URL.createObjectURL(new Blob([buildExportSvg(false)],{type:'image/svg+xml'}));
  await new Promise((ok,ng)=>{img.onload=ok;img.onerror=ng;img.src=url;});const k=Math.min(1,1600/ART.w);const c=document.createElement('canvas');c.width=ART.w*k;c.height=ART.h*k;
  c.getContext('2d').drawImage(img,0,0,c.width,c.height);return c.toDataURL('image/png').split(',')[1];})()"""

def pdf_file(src, out_png):
    """src=AI(PDF互換)/PDF か 'fixture'。読み込んだ結果を表示し、見比べ用PNG（.bk.png=BezierKit／.ref.png=pdf.jsの描画）を出す"""
    data = make_test_pdf() if src == "fixture" else open(src, "rb").read()
    chrome, sock = boot()
    try:
        got = json.loads(ev(sock, PDF_IMPORT_JS % (json.dumps(base64.b64encode(data).decode()), json.dumps(os.path.basename(src) if src != "fixture" else "fixture.pdf")), await_promise=True, timeout=300))
        print(json.dumps(got, ensure_ascii=False))
        base = os.path.splitext(out_png)[0]
        os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
        with open(base + ".bk.png", "wb") as f: f.write(base64.b64decode(ev(sock, RENDER_PNG_JS, await_promise=True)))
        ref = ev(sock, r"""(async()=>{const lib=await loadPdfJs();const bin=Uint8Array.from(atob(%s),c=>c.charCodeAt(0));
          const pdf=await lib.getDocument({data:bin,isEvalSupported:false}).promise;const page=await pdf.getPage(1);
          const v0=page.getViewport({scale:1}),vp=page.getViewport({scale:Math.min(1,1600/v0.width)});const c=document.createElement('canvas');c.width=vp.width;c.height=vp.height;
          await page.render({canvasContext:c.getContext('2d'),viewport:vp}).promise;return c.toDataURL('image/png').split(',')[1];})()"""
                 % json.dumps(base64.b64encode(data).decode()), await_promise=True, timeout=300)
        with open(base + ".ref.png", "wb") as f: f.write(base64.b64decode(ref))
    finally:
        chrome.terminate()
    print("PDF_OK", base + ".bk.png", base + ".ref.png")
    return 0

SHOT_SETUPS = {
    # 波11: 4色・不透明度ありの放射グラデの図形を選び、帯を出した塗り・線・効果の欄
    "wave11": r"""(()=>{state.paths=[];const L=state.layers[0].id;
      const p={id:nextId++,layerId:L,closed:true,fill:'#ff5252',stroke:'#121212',width:4,
        nodes:[node(260,180),node(620,180),node(620,540),node(260,540)],
        gradient:{type:'radial',c1:'#ff5252',c2:'#1e40af',angle:0,cx:.3,cy:.3,spread:90,
          stops:[[0,'#ffd54f',1],[.35,'#ff5252',.8],[.7,'#8e24aa',.6],[1,'#1e40af',1]]}};
      state.paths.push(p);render();setSelection([p.id]);
      document.getElementById('fillType').value='radial';updateGradRow();
      if(typeof revealPanel==='function')revealPanel(document.getElementById('gradBar'));
      renderGradBar();return true;})()""",
    # 3枚のアートボードに1つずつ図形を置いた画面
    # グローバルカラー2色（塗り・線）をつないだ図形と、パネルの一覧
    "swatches": r"""(()=>{state.paths=[];state.swatches=null;const L=state.layers[0].id;
      [100,300,500].forEach((x,i)=>state.paths.push({id:nextId++,layerId:L,closed:true,fill:i<2?'#21537f':'#c62828',stroke:'#121212',width:6,nodes:[node(x,200),node(x+150,200),node(x+150,350),node(x,350)]}));
      render();setSelection(state.paths.map(p=>p.id));createSwatch('fill');createSwatch('stroke');state.swatches[0].name='青';swEditAt=0;setSwatchColor(state.swatches[0].id,'#10b981');
      setSelection([]);render();revealPanel(document.getElementById('abList'));return true;})()""",
    # シンボル3つ（そのまま・90°回転・左右反転＋2倍）を、1つ目の編集で全部更新した後
    "symbols": r"""(()=>{state.paths=[];state.symbols=null;const L=state.layers[0].id;applyArtboard(1280,720);
      const R=(x,y,w,h,fill)=>{const o={id:nextId++,layerId:L,closed:true,fill,stroke:'#121212',width:4,nodes:[node(x,y),node(x+w,y),node(x+w,y+h),node(x,y+h)]};state.paths.push(o);return o;};
      const a=R(100,150,160,90,'#21537f'),b=R(120,170,50,30,'#ffd54f');render();setSelection([a.id,b.id]);makeSymbol();const sid=state.symbols[0].id;
      placeSymbol(sid);transformSelection({a:1,b:0,c:0,d:1,e:0,f:0});const s2=state.selectedPaths.slice();
      const bb=selectionBBox();transformSelection({a:1,b:0,c:0,d:1,e:420-bb.cx,f:200-bb.cy});rotateSelection(90);
      placeSymbol(sid);const b3=selectionBBox();transformSelection({a:1,b:0,c:0,d:1,e:800-b3.cx,f:300-b3.cy});flip(true);scaleSelection(200);
      setSelection([a.id]);toggleSymbolEdit();const p=pathById(a.id);p.fill='#10b981';p.nodes[2].x+=60;p.nodes[2].inX+=60;p.nodes[2].outX+=60;render();toggleSymbolEdit();
      setSelection([]);fitArtboards();render();revealPanel(document.getElementById('symList'));return true;})()""",
    # 繰り返し3種: 花びら（放射12）・タイル（グリッド4×2）・横顔の半分（ミラー）。花びらは作った後に色と形を直す
    "repeats": r"""(()=>{state.paths=[];state.selectedPaths=[];state.repeats=null;const L=state.layers[0].id;applyArtboard(1280,720);
      const add=o=>{o.id=nextId++;o.layerId=L;state.paths.push(o);return o;};
      const petal=add({closed:true,fill:'#9fc0dd',stroke:'#21537f',width:2,nodes:[{x:250,y:120,inX:250,inY:120,outX:280,outY:160},{x:250,y:230,inX:280,inY:200,outX:220,outY:200}]});
      petal.nodes[0].inX=220;petal.nodes[0].inY=160;
      render();setSelection([petal.id]);$('rptKind').value='radial';$('rptN').value=12;$('rptR').value=110;makeRepeat();
      petal.fill='#f5a3a3';petal.stroke='#b01212';petal.nodes[1].y=250;render();
      const tile=add({closed:true,fill:'#21537f',stroke:'none',width:1,nodes:[node(520,120),node(600,120),node(560,190)]});
      render();setSelection([tile.id]);$('rptKind').value='grid';$('rptCols').value=4;$('rptRows').value=3;$('rptGap').value=8;makeRepeat();
      const half=add({closed:true,fill:'#ffd54f',stroke:'#121212',width:3,nodes:[node(1000,140),{x:1060,y:200,inX:1060,inY:160,outX:1060,outY:240},node(1000,300),node(1000,140)]});half.nodes.pop();
      render();setSelection([half.id]);$('rptKind').value='mirror';$('rptAxis').value='v';$('rptMGap').value=0;makeRepeat();
      setSelection([petal.id]);render();revealPanel(document.getElementById('rptKind'));return true;})()""",
    # ナイフで円を波線に切って片方をずらす／ドーナツを斜めに切る／消しゴムで四角に溝を2本
    "knife": r"""(()=>{state.paths=[];state.selectedPaths=[];state.selectedPath=null;const L=state.layers[0].id;applyArtboard(1280,720);
      const C=(cx,cy,r)=>{const k=.5523*r;return{closed:true,nodes:[{x:cx+r,y:cy,inX:cx+r,inY:cy-k,outX:cx+r,outY:cy+k},{x:cx,y:cy+r,inX:cx+k,inY:cy+r,outX:cx-k,outY:cy+r},{x:cx-r,y:cy,inX:cx-r,inY:cy+k,outX:cx-r,outY:cy-k},{x:cx,y:cy-r,inX:cx-k,inY:cy-r,outX:cx+k,outY:cy-r}]};};
      const add=o=>{o.id=nextId++;o.layerId=L;state.paths.push(o);return o;};
      add({...C(250,300,150),fill:'#21537f',stroke:'#121212',width:3});add({subpaths:[C(650,300,140),C(650,300,60)],fill:'#c62828',stroke:'#121212',width:3,fillRule:'evenodd'});
      add({closed:true,nodes:[node(880,170),node(1140,170),node(1140,430),node(880,430)],fill:'#10b981',stroke:'#121212',width:3});render();
      const run=(tool,pts)=>{setSelection([]);finishCutStroke({type:'cut',tool,pts:pts.map(([x,y])=>({x,y}))});};
      const wave=[];for(let i=0;i<=40;i++)wave.push([80+i*8.5,300+Math.sin(i/3)*30]);run('knife',wave);
      const top=state.paths.filter(p=>p.fill==='#21537f').sort((a,b)=>bboxOfPath(a).t-bboxOfPath(b).t)[0];setSelection([top.id]);nudgeSelection(0,-40);
      run('knife',[[480,470],[820,130]]);const rr=state.paths.filter(p=>p.fill==='#c62828');setSelection([rr[1].id]);nudgeSelection(25,25);
      $('eraserW').value=24;run('eraser',[[960,150],[960,450]]);run('eraser',[[860,330],[1160,260]]);
      setSelection([]);render();return true;})()""",
    # アートボード2枚のパネル（選んでいる行の文字が読めるか）
    "abpanel": r"""(()=>{state.artboards=null;state.activeArtboard=0;applyArtboard(1280,720);addArtboard();render();
      revealPanel(document.getElementById('abList'));return true;})()""",
    "artboards": r"""(()=>{state.paths=[];state.artboards=null;state.activeArtboard=0;applyArtboard(1280,720);addArtboard();state.activeArtboard=1;addArtboard();setActiveArtboardSize(960,720);
      const L=artboardList();L.forEach((a,i)=>{state.paths.push({id:nextId++,layerId:state.layers[0].id,closed:true,fill:['#21537f','#c62828','#10b981'][i],stroke:'none',width:1,
        nodes:[node(a.x+100,a.y+100),node(a.x+500,a.y+100),node(a.x+500,a.y+400),node(a.x+100,a.y+400)]});});fitArtboards();render();return true;})()""",
}

def shot(name):
    """画面のスクリーンショット（SHOT_SETUPS の準備をしてから撮る）。出力 _check/shot-<名前>.png"""
    chrome, sock = boot()
    try:
        ev(sock, SHOT_SETUPS[name]); time.sleep(0.5)
        png = call(sock, "Page.captureScreenshot", {"format": "png"})["data"]
    finally:
        chrome.terminate()
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, f"shot-{name}.png")
    with open(out, "wb") as f: f.write(base64.b64decode(png))
    print("SHOT_OK", out)
    return 0

# Kiroが描くPPTX向けイラストの約束（SPEC.md 5章・Skill pptx-illust）。使わない要素と色の推奨セット
ILLUST_FORBIDDEN = ["filter", "mask", "clipPath", "pattern", "image", "use", "foreignObject", "text", "script", "symbol", "marker"]
ILLUST_COLORS = {"#121212", "#21537f", "#162a42", "#fafafa", "#9fc0dd", "#718096", "#eef3f8", "#d4dde7", "#c62828", "#183251",
                 "#b01212", "#edf2f4", "#f4f4ef", "#f7f2f2", "#7a471a", "#5e5e5e", "#a0aec0", "#ffffff",
                 "#1e40af", "#06b6d4", "#10b981", "#2563eb", "#14b8a6", "#94a3b8"}

def illust_check(src):
    """KiroのSVGを検査: ①使わない要素 ②色（推奨セット外は注意）③BezierKitで開いたときに落ちる図形 ④PPTX確認の「出ないもの」
    ⑤verify と同じ見比べ画像。①③④が0件なら ILLUST_OK"""
    text = open(src, encoding="utf-8").read()
    ng, warn = [], []
    for tag in ILLUST_FORBIDDEN:
        n = len(re.findall(r"<%s[\s>/]" % tag, text))
        if n: ng.append(f"<{tag}> が {n}個（{'文字はSlideKitの .tb で重ねる' if tag == 'text' else 'PPTXで図形にならない'}）")
    if re.search(r"url\(\s*['\"]?(?!#)", text): ng.append("外部の url(...) を参照している")
    if 'data-bezierkit-artboard="1"' not in text: warn.append('ルートに data-bezierkit-artboard="1" が無い（BezierKitで開くと大きさが変わる）')
    if not re.search(r"viewBox=", text): ng.append("viewBox が無い")
    cols = {c.lower() for c in re.findall(r"(?:fill|stroke|stop-color)\s*[=:]\s*['\"]?(#[0-9a-fA-F]{6})", text)}
    off = sorted(cols - ILLUST_COLORS)
    if off: warn.append("色トークンの推奨セット外: " + " ".join(off) + "（グラデの中間色なら可）")
    shapes = len(re.findall(r"<(?:path|rect|circle|ellipse|line|polyline|polygon)[\s>/]", text))
    chrome, sock = boot()
    try:
        ev(sock, "state.paths=[];state.selectedPaths=[];state.selectedPath=null;render();true")
        ev(sock, "(async()=>{await openDocument(new File([%s],%s,{type:'image/svg+xml'}));return true;})()" % (json.dumps(text), json.dumps(os.path.basename(src))), await_promise=True)
        got = json.loads(ev(sock, "JSON.stringify({paths:state.paths.length,layers:state.layers.map(l=>l.name),art:[ART.w,ART.h],chk:pptxCheck()})"))
    finally:
        chrome.terminate()
    if got["paths"] < shapes: ng.append(f"BezierKitで開くと図形が {shapes}→{got['paths']} に減る（塗りも線も無い図形か、defs の中）")
    chk = got["chk"]
    if chk["lost"]: ng.append(f"PPTX確認で「出ないもの」{chk['lost']}個 {chk['notes']}")
    if chk["baked"]: warn.append(f"形に焼いて図形 {chk['baked']}個 {chk['notes']}（PowerPointでは形として直す）")
    print(json.dumps({"shapes": shapes, "imported": got["paths"], "layers": got["layers"], "artboard": got["art"], "pptx": chk}, ensure_ascii=False))
    for w in warn: print("注意:", w)
    for n in ng: print("NG:", n)
    verify_file(src)
    print("ILLUST_NG" if ng else "ILLUST_OK")
    return 1 if ng else 0

def slide_fixture(out_html):
    """見本の絵（PPTX_FIXTURE_JS）を「スライドへ戻す」と同じSVGにして、SlideKitのスライド1枚に入れたHTMLを書く。
    SlideKit 側の変換（影・光彩・ぼかし輪郭・矢じり・放射グラデ・切り抜きが図形のまま渡るか）の検査に使う"""
    chrome, sock = boot()
    try:
        ev(sock, PPTX_FIXTURE_JS)
        ev(sock, "state.paths=state.paths.filter(p=>!isText(p));render();true")  # 文字は SlideKit 側の .tb の役目
        svg_text = ev(sock, "buildSlideSvg()")
    finally:
        chrome.terminate()
    svg_text = re.sub(r"<metadata[\s\S]*?</metadata>", "", svg_text)  # 作業データは検査に要らない
    html = ('<!DOCTYPE html>\n<html lang="ja" data-structure="off"><head><meta charset="utf-8"><title>BezierKitの効果をPPTXへ</title><style>\n'
            "body{font-family:'Meiryo UI','Yu Gothic',sans-serif;margin:0;padding-top:20px;background:#e9edf1}\n"
            '.slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;background:#fafafa}\n'
            '.tb{position:absolute;overflow:hidden;line-height:1.5}\n</style></head><body>\n'
            '<!-- SLIDE: BezierKitの効果 [CUSTOM: 変換の検査] -->\n<div class="slide" data-bg="#fafafa">\n'
            '<div data-x="0" data-y="0" data-w="1280" data-h="720" style="position:absolute;left:0;top:0;width:1280px;height:720px">\n'
            + svg_text.replace("<svg ", '<svg role="img" aria-label="BezierKitの見本の絵（影・光彩・ぼかし輪郭・矢じり・放射グラデ・切り抜き）" ', 1)
            + '\n</div>\n</div>\n<!-- /SLIDE -->\n<script src="../../slide-edit.js"></script>\n</body></html>\n')
    with open(out_html, "w", encoding="utf-8") as f: f.write(html)
    print("SLIDE_FIXTURE_OK", out_html, len(svg_text))
    return 0

def verify_file(src, ppt=False, crop=""):
    """1コマンドの通し確認: 読み込み → PPTX → 見比べ画像（BezierKit／元のAI・PDFのmacOS描画／PPTXのLibreOffice描画）→ 任意でPowerPoint実機。
    出力は BezierKit/_check/<名前>/ に置き、前回の分は最初に消す"""
    name = "fixture" if src == "fixture" else os.path.splitext(os.path.basename(src))[0]
    d = fresh_dir(re.sub(r"[^\w.-]+", "_", name))
    pptx = os.path.join(d, "out.pptx")
    pptx_file(src, pptx, pdf_out=os.path.join(d, "out.pdf"))
    mac = mac_render(src, os.path.join(d, "mac.png")) if src.lower().endswith((".ai", ".pdf")) else None
    pdfmac = mac_render(os.path.join(d, "out.pdf"), os.path.join(d, "out.pdf.png"))
    src_png = os.path.join(d, "out.src.png")
    cmp = compare_png([("original SVG (Chrome)", src_png if os.path.exists(src_png) else None), ("BezierKit", os.path.join(d, "out.bk.png")), ("macOS: original AI/PDF", mac),
                       ("PPTX -> LibreOffice", os.path.join(d, "out.lo.png")), ("PDF export -> macOS", pdfmac)], os.path.join(d, "compare.png"), crop)
    print("VERIFY_OK", cmp)
    return ppt_open(pptx) if ppt else 0


def nyuko_check():
    """入稿: 画像からカットライン作成→入稿用 .ai 書き出し→PyMuPDFで読み戻して確認。python3 cdp-check.py nyuko"""
    fails = []
    chrome, sock = boot()
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;nextLayerId=2;render();true")
    # アートボード＝塗り足し込み 154x106mm。デザイン＝全面の水色の矩形。画像＝透明地に白フチ付きの赤い丸（60mm幅で (20,20)mm に置く）
    ok = ev(sock, """(()=>{
      const MM=72/25.4; applyArtboard(154*MM,106*MM);
      const bg={id:nextId++,nodes:[[0,0],[154,0],[154,106],[0,106]].map(([x,y])=>({x:x*MM,y:y*MM,inX:x*MM,inY:y*MM,outX:x*MM,outY:y*MM})),closed:true,fill:'#cfe8ff',stroke:'none',width:1,layerId:1};
      state.paths.push(bg);
      const cv=document.createElement('canvas');cv.width=600;cv.height=400;const ctx=cv.getContext('2d');
      ctx.fillStyle='#ffffff';ctx.beginPath();ctx.arc(300,200,150,0,7);ctx.fill();     // 白フチ（画像の中・r=150px=15mm）
      ctx.fillStyle='#cc2222';ctx.beginPath();ctx.arc(300,200,120,0,7);ctx.fill();     // 絵
      const imgId=nextImgId++;imageStore.set(imgId,{dataURL:cv.toDataURL('image/png'),px:600,py:400});
      const s=60*MM/600;const im={id:nextId++,type:'image',imgId,w0:600,h0:400,mat:[s,0,0,s,20*MM,20*MM],opacity:1,layerId:1};
      state.paths.push(im);setSelection([im.id]);render();
      document.getElementById('cutMargin').value='2';document.getElementById('cutRound').value='1.5';document.getElementById('cutTol').value='0.1';
      return state.paths.length===2;})()""")
    if not ok: fails.append("NYUKO-SETUP: 図形2つを置けない")
    r = ev(sock, "window.__bkNyuko.makeCutline().then(r=>JSON.stringify(r))", await_promise=True)
    r = json.loads(r) if r else None
    if not r or len(r["ids"]) != 1 or r["layer"] != "カットライン":
        fails.append(f"CUTLINE: 1本が「カットライン」に出来るはず: {r}")
    else:
        bb = json.loads(ev(sock, f"""JSON.stringify((()=>{{const MM=72/25.4,p=pathById({r['ids'][0]}),b=bboxOfPath(p);
          return {{l:b.l/MM,t:b.t/MM,r:b.r/MM,b:b.b/MM,closed:!!p.closed,stroke:p.stroke,width:p.width,fill:p.fill,n:p.nodes.length}};}})())"""))
        # 期待: 丸の中心(50,40)mm・半径15mm＋白フチ2mm＝17mm → 33..67 / 23..57
        for k, want in (("l", 33), ("t", 23), ("r", 67), ("b", 57)):
            if abs(bb[k] - want) > 0.35: fails.append(f"CUTLINE: {k}={bb[k]:.2f}mm（期待 {want}±0.35）")
        if not bb["closed"] or bb["stroke"].lower() != "#ec008c" or bb["fill"] != "none" or abs(bb["width"] - 0.25) > 1e-6:
            fails.append(f"CUTLINE: 閉じたM100相当の0.25pt線になっていない: {bb}")
        if bb["n"] > 80: fails.append(f"CUTLINE: アンカーが多すぎる {bb['n']}（丸なら80以下）")
        print("cutline bbox(mm)", {k: round(v, 2) for k, v in bb.items() if isinstance(v, float)}, "anchors", bb["n"], "holes", r["holes"])
    # 入稿用 .ai
    chk = json.loads(ev(sock, "(()=>{window.__bkNyuko.fillDlg();return JSON.stringify(window.__bkNyuko.checks(window.__bkNyuko.params()));})()"))
    print("checks:", [c["lv"][0] + " " + c["text"] for c in chk])
    if any(c["lv"] == "ng" for c in chk): fails.append(f"NYUKO-CHECK: ng がある: {chk}")
    if not any("届いている" in c["text"] for c in chk): fails.append("NYUKO-CHECK: デザインが塗り足しまで届いている判定が出ない")
    txt = ev(sock, "window.__bkNyuko.build(window.__bkNyuko.params()).then(r=>{window.__nyukoR={cut:r.cut,layers:r.layers};return r.text;})", await_promise=True)
    meta = json.loads(ev(sock, "JSON.stringify(window.__nyukoR)"))
    out_dir = os.path.join(HERE, "_check", "nyuko"); os.makedirs(out_dir, exist_ok=True)
    ai = os.path.join(out_dir, "test_154x106.ai")
    with open(ai, "wb") as f: f.write(bytes(ord(c) & 255 for c in txt))
    for key in ("/Separation /All", "0 1 0 0 K", "/TrimBox", "/OCProperties", "/CSReg CS 1 SCN"):
        if key not in txt: fails.append(f"NYUKO-PDF: {key} が無い")
    if meta["cut"] != 1 or meta["layers"] != 3: fails.append(f"NYUKO-PDF: 切り線1・レイヤー3のはず: {meta}")
    try:
        import fitz
        d = fitz.open(ai); pg = d[0]
        layers = [v.get("name") for v in d.get_ocgs().values()]
        tb = [round(v / (72 / 25.4), 2) for v in pg.trimbox]
        strokes = {}
        for dr in pg.get_drawings():
            if dr.get("fill") is None and dr.get("color") is not None:
                k = (tuple(round(v, 2) for v in dr["color"]), round(dr["width"], 2)); strokes[k] = strokes.get(k, 0) + 1
        print("fitz:", "layers", layers, "trimbox(mm)", tb, "images", len(pg.get_images()), "strokes", strokes, "page(mm)", round(pg.rect.width/(72/25.4),1), round(pg.rect.height/(72/25.4),1))
        if layers != ["デザイン", "カットライン", "トンボ"]: fails.append(f"NYUKO-PDF: レイヤー名の順: {layers}")
        if tb != [3.0, 3.0, 151.0, 103.0]: fails.append(f"NYUKO-PDF: TrimBox: {tb}")
        if len(pg.get_images()) != 1: fails.append("NYUKO-PDF: 画像が1つ入るはず")
        if sum(n for (c, w), n in strokes.items() if abs(c[0]-0.93)<0.05 and c[1]<0.05) != 1: fails.append(f"NYUKO-PDF: M100の線が1本のはず: {strokes}")
        if sum(n for (c, w), n in strokes.items() if c == (0.0, 0.0, 0.0)) != 8: fails.append(f"NYUKO-PDF: トンボ8本のはず: {strokes}")
        pg.get_pixmap(dpi=72).save(os.path.join(out_dir, "test_154x106.png"))
    except ImportError:
        print("PyMuPDF が無いので読み戻しは省いた")
    chrome.terminate()
    for f in fails: print("FAIL", f)
    print("NYUKO_OK" if not fails else f"NYUKO_NG {len(fails)}")
    return 1 if fails else 0

def fixes2_check():
    """2026-11-15 の4件(B1 文字の知らせ／B2 背景 白・透明／B3 白地の読み飛ばし／B4 谷を鋭くしない)。python3 cdp-check.py fix2"""
    fails = []
    out_dir = os.path.join(HERE, "_check", "fix2"); os.makedirs(out_dir, exist_ok=True)
    chrome, sock = boot()

    # ---- B1: <text> 入りSVGを開くと「文字 N か所」の知らせが出る ----
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;nextLayerId=2;render();true")
    mix = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect x='10' y='10' width='30' height='30' fill='#39c'/><text x='10' y='80' font-size='20'>あ</text><text x='60' y='80'>い</text></svg>"
    st = ev(sock, f"(()=>{{importGenericSvg({json.dumps(mix)},'mix.svg');return document.getElementById('status').textContent;}})()")
    n = ev(sock, "state.paths.length")
    if "文字 2か所" not in st: fails.append(f"B1: 文字の知らせが出ない: {st}")
    if int(n) != 1: fails.append(f"B1: 図形は1個だけ取り込むはず（文字は取り込まない）: {n}")
    only = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text x='10' y='50'>文字だけ</text></svg>"
    ev(sock, "state.paths=[];render();true")
    st2 = ev(sock, f"(()=>{{importGenericSvg({json.dumps(only)},'only.svg');return document.getElementById('status').textContent;}})()")
    if "文字 1か所" not in st2: fails.append(f"B1: 文字だけのSVGで知らせが出ない: {st2}")
    print("B1 status:", st, "||", st2)

    # ---- B2: 背景 白／透明で buildExportSvg の白地が出たり消えたりする ----
    ev(sock, "state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;render();applyArtboard(400,300);true")
    ev(sock, "state.paths.push({id:nextId++,nodes:[[50,50],[150,50],[150,150],[50,150]].map(([x,y])=>({x,y,inX:x,inY:y,outX:x,outY:y})),closed:true,fill:'#39c',stroke:'none',width:1,layerId:1});render();true")
    white = ev(sock, "(()=>{document.getElementById('exportBg').value='white';const s=buildExportSvg(false);return (s.match(/data-bk-bg/g)||[]).length;})()")
    trans = ev(sock, "(()=>{document.getElementById('exportBg').value='transparent';const s=buildExportSvg(false);return (s.match(/data-bk-bg/g)||[]).length+'|'+(/fill=\"#ffffff\"/.test(s)?'has':'none');})()")
    ev(sock, "document.getElementById('exportBg').value='white';true")
    if int(white) < 1: fails.append(f"B2: 既定(白)で白地のrectが無い: {white}")
    if not str(trans).startswith("0|none"): fails.append(f"B2: 透明で白地が残っている: {trans}")

    # ---- B3: 書き出した白地つきSVGを開き直すと、白地は図形に増えない ----
    ev(sock, "document.getElementById('exportBg').value='white';true")
    svg_white = ev(sock, "buildExportSvg(false)")
    ev(sock, "state.paths=[];render();true")
    n3 = ev(sock, f"(()=>{{importGenericSvg({json.dumps(svg_white)},'roundtrip.svg');return state.paths.length;}})()")
    if int(n3) != 1: fails.append(f"B3: 白地つきSVGの開き直しで図形が増えた（期待1・実際{n3}）")
    print("B2 white rects:", white, "transparent:", trans, "B3 reimport paths:", n3)

    # ---- B4(見送り): 既定の設定では今の2段オフセットが谷を丸められていることを確かめる回帰ガード ----
    # 細い首(0.75mm)で1つにつながった亜鈴の切り線が、当てはめ後も鋭いくさびにならない（最も鋭い曲がり<90°）。
    ev(sock, "state.paths=[];render();true")
    ev(sock, r"""(()=>{const P=booleanScope;P.activate();P.project.clear();const MM=72/25.4;const r=9*MM,d=11*MM,nk=0.75*MM;
      let u=new P.Path.Circle(new P.Point(-d,0),r).unite(new P.Path.Circle(new P.Point(d,0),r),{insert:false});
      u=u.unite(new P.Path.Rectangle(new P.Rectangle(-d,-nk/2,2*d,nk)),{insert:false});
      const parts=parsePathD(u.pathData),cx=170,cy=100;parts.forEach(p=>p.nodes.forEach(n=>{n.x+=cx;n.y+=cy;n.inX+=cx;n.inY+=cy;n.outX+=cx;n.outY+=cy;}));
      state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;nextLayerId=2;applyArtboard(340,200);
      const obj={id:nextId++,fill:'#dfe6ee',stroke:'none',width:1,layerId:1};if(parts.length===1)Object.assign(obj,parts[0]);else obj.subpaths=parts;
      state.paths.push(obj);setSelection([obj.id]);
      document.getElementById('cutMargin').value='2';document.getElementById('cutRound').value='1.5';document.getElementById('cutTol').value='0.1';return true;})()""")
    ev(sock, "window.__bkNyuko.makeCutline().then(r=>JSON.stringify(r))", await_promise=True)
    b4 = json.loads(ev(sock, r"""(()=>{const cut=state.paths.filter(p=>p.layerId===state.layers.find(L=>L.name==='カットライン').id&&p.nodes);
      const S=[];for(const p of cut){const ns=p.nodes,n=ns.length;for(let i=0;i<n;i++){const a=ns[i],b=ns[(i+1)%n];for(let t=0;t<1;t+=1/16){const mt=1-t;S.push([mt*mt*mt*a.x+3*mt*mt*t*a.outX+3*mt*t*t*b.inX+t*t*t*b.x,mt*mt*mt*a.y+3*mt*mt*t*a.outY+3*mt*t*t*b.inY+t*t*t*b.y,p.id]);}}}
      let w=0;const n=S.length;for(let i=0;i<n;i++){const a=S[(i-1+n)%n],b=S[i],c=S[(i+1)%n];if(a[2]!==b[2]||b[2]!==c[2])continue;const v1x=b[0]-a[0],v1y=b[1]-a[1],v2x=c[0]-b[0],v2y=c[1]-b[1];const l1=Math.hypot(v1x,v1y),l2=Math.hypot(v2x,v2y);if(l1<1e-4||l2<1e-4)continue;let d=(v1x*v2x+v1y*v2y)/(l1*l2);d=Math.max(-1,Math.min(1,d));const t=Math.acos(d)*180/Math.PI;if(t>w)w=t;}
      return JSON.stringify({sharp:+w.toFixed(1)});})()"""))
    print("B4 亜鈴(首0.75mm)の切り線 最も鋭い曲がり:", b4["sharp"], "°")
    if b4["sharp"] >= 90: fails.append(f"B4: 細い首の切り線が鋭い（{b4['sharp']}°・<90°のはず）")

    # ---- B4b(2026-11-15): 離れた2円(すき間1.5mm)の白フチがまたぐ所の谷。
    # 既存B4は「つながった亜鈴」で鋭い曲がりを見るが、谷は当てはめ後G1でなめらかになり曲がりでは出ない。
    # 本当の不具合は、離れた図形のすき間を白フチがまたいでできる『深く細い谷』。小窓(0.53mm)での
    # 谷の内角で測る（円の縁は約178°・谷が鋭いほど小さい）。膨らませて縮める直しで谷が開く。
    ev(sock, r"""(()=>{const P=booleanScope;P.activate();P.project.clear();const MM=72/25.4;const r=18*MM;const cy=200,cx1=150,cx2=cx1+2*r+1.5*MM;
      const c1=new P.Path.Circle({center:[cx1,cy],radius:r,insert:false}),c2=new P.Path.Circle({center:[cx2,cy],radius:r,insert:false});
      const a={id:nextId,fill:'#622',stroke:'none',width:1,layerId:1,closed:true},b={id:nextId+1,fill:'#622',stroke:'none',width:1,layerId:1,closed:true};
      a.nodes=fromPaperPath(c1)[0].nodes;b.nodes=fromPaperPath(c2)[0].nodes;nextId+=2;
      state.paths=[];state.layers=[{id:1,name:'レイヤー 1',visible:true}];state.activeLayer=1;nextLayerId=2;applyArtboard(400,400);
      state.paths.push(a);state.paths.push(b);setSelection([a.id,b.id]);
      document.getElementById('cutMargin').value='2';document.getElementById('cutRound').value='1.5';document.getElementById('cutTol').value='0.1';document.getElementById('cutThresh').value='50';return true;})()""")
    ev(sock, "window.__bkNyuko.makeCutline().then(r=>JSON.stringify(r))", await_promise=True)
    b4b = json.loads(ev(sock, r"""(()=>{const cut=state.paths.filter(p=>p.fill==='none'&&p.nodes);
      let best=200,bx=0,by=0;const W=1.5;
      for(const p of cut){const ns=p.nodes,m=ns.length;let poly=[];for(let i=0;i<m;i++){const a=ns[i],b=ns[(i+1)%m];for(let t=0;t<1;t+=1/24){const u=1-t;poly.push([u*u*u*a.x+3*u*u*t*a.outX+3*u*t*t*b.inX+t*t*t*b.x,u*u*u*a.y+3*u*u*t*a.outY+3*u*t*t*b.inY+t*t*t*b.y]);}}
        const n=poly.length;const at=(i,d)=>{let j=i,acc=0;while(acc<W){const k=(j+d+n)%n;acc+=Math.hypot(poly[k][0]-poly[j][0],poly[k][1]-poly[j][1]);j=k;}return poly[j];};
        for(let i=0;i<n;i++){const cu=poly[i],pa=at(i,-1),pb=at(i,1);const ax=pa[0]-cu[0],ay=pa[1]-cu[1],bx2=pb[0]-cu[0],by2=pb[1]-cu[1];const la=Math.hypot(ax,ay),lb=Math.hypot(bx2,by2);if(la<1e-4||lb<1e-4)continue;let d=(ax*bx2+ay*by2)/(la*lb);d=Math.max(-1,Math.min(1,d));const ang=Math.acos(d)*180/Math.PI;if(ang<best){best=ang;bx=cu[0];by=cu[1];}}}
      return JSON.stringify({ang:+best.toFixed(1),x:Math.round(bx),y:Math.round(by),loops:cut.length});})()"""))
    print("B4b 離れた2円(すき間1.5mm)の谷の内角:", b4b["ang"], "° @", b4b["x"], b4b["y"], "loops", b4b["loops"])
    if b4b["ang"] < 155: fails.append(f"B4b: すき間をまたぐ谷が鋭いくさび（{b4b['ang']}°・155°以上のはず）")

    chrome.terminate()
    for f in fails: print("FAIL", f)
    print("FIX2_OK" if not fails else f"FIX2_NG {len(fails)}")
    return 1 if fails else 0

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "fix2":
        sys.exit(fixes2_check())
    if len(sys.argv) >= 2 and sys.argv[1] == "nyuko":
        sys.exit(nyuko_check())
    if len(sys.argv) >= 3 and sys.argv[1] == "slidefx":
        sys.exit(slide_fixture(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "illust":
        sys.exit(illust_check(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "shot":
        sys.exit(shot(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "verify":
        crop = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--crop=")), "")
        sys.exit(verify_file(sys.argv[2], ppt="--ppt" in sys.argv, crop=crop))
    if len(sys.argv) >= 4 and sys.argv[1] == "pdf":
        sys.exit(pdf_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 4 and sys.argv[1] == "pptx":
        sys.exit(pptx_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 4 and sys.argv[1] == "trace":
        sys.exit(trace_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 4 and sys.argv[1] == "halftone":
        sys.exit(halftone_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 3 and sys.argv[1] == "grad":
        sys.exit(grad_pdf(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "only":
        sys.exit(run_only(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == "icons":
        sys.exit(icons_check())
    rc = selftest()
    sys.exit(rc or icons_check())
