# BezierKit ヘッドレス検証（CDP直叩き・CadKitのcdp-run.pyと同流儀）
#   python3 cdp-check.py                          … 自己テスト（合成画像トレース・曲線フィット・レイヤー統合）
#   python3 cdp-check.py trace 画像 出力.svg      … 画像をトレースしてSVG保存（環境変数 COLORS/TOL/MINPX/RES/FIT）
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request
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

def boot(page=PAGE, ready="typeof runTrace==='function' && typeof fitLoopNodes==='function'"):
    # 前回異常終了の残骸が同じポートを握っていると古いページに繋がってしまう→先に掃除
    subprocess.run(["pkill", "-f", "bk-check-profile"], capture_output=True)
    time.sleep(0.5)
    chrome = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
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

def do_trace(sock, colors, tol, minpx, res, fit):
    return ev(sock, f"""(()=>{{
      document.getElementById('traceColors').value='{colors}';
      document.getElementById('traceTol').value='{tol}';
      document.getElementById('traceMin').value='{minpx}';
      document.getElementById('traceRes').value='{res}';
      document.getElementById('traceFit').checked={'true' if fit else 'false'};
      runTrace();
      return document.getElementById('traceInfo').textContent;
    }})()""", timeout=600)

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

    chrome.terminate()
    print(("BEZIERKIT_FAIL\n" + "\n".join(fails)) if fails else
          "BEZIERKIT_OK (trace-fit / trace-res / layer-merge / openDocument / generic-import / "
          "select-same / pen-insert / simplify / smooth / clip-mask / lock / outline / width-tool / shape-builder / align-anchor / cap-fx / appearance / cad-copy)")
    return 1 if fails else 0

def trace_file(img_path, out_svg):
    chrome, sock = boot()
    try:
        load_image(sock, "file://" + os.path.abspath(img_path))
        info = do_trace(sock, os.environ.get("COLORS", "8"), os.environ.get("TOL", "1.2"),
                        os.environ.get("MINPX", "3"), os.environ.get("RES", "360"),
                        os.environ.get("FIT", "1") != "0")
        print("TRACE:", info)
        print("STATS:", ev(sock, STATS_JS))
        svg_text = ev(sock, "buildExportSvg(true)", timeout=600)
        with open(out_svg, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + svg_text)
        print("SVG:", out_svg, f"{len(svg_text):,} bytes")
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

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "trace":
        sys.exit(trace_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 2 and sys.argv[1] == "icons":
        sys.exit(icons_check())
    rc = selftest()
    sys.exit(rc or icons_check())
