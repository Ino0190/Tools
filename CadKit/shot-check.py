# CadKitアセットの自動目視: ヘッドレスで生成→3方向撮影→ASCIIアート＋PNG保存
# 使い方: python3 shot-check.py <ハッシュ名> [-w 幅] [-v ビュー名,...]
#   例: python3 shot-check.py dairi
#       python3 shot-check.py chodoin -v plan,south -w 90
# 出力: CadKit/shots/<ハッシュ>-<ビュー>.txt（ASCII目視用）と同名.png（人間確認用）
# ビュー: plan=真上 / bird=南東鳥瞰 / south=南から低め。カメラはシーンbboxから自動決定。
# 仕組み: index.htmlの window.__shotFrom（カメラ配置＋透過PNG撮影）をCDPから呼ぶ。
# BezierKitのicon-check.py（ASCII自動目視）のCadKit版。
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

PORT = int(os.environ.get("CDP_PORT", "9251"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
raw = sys.argv[1:]
WIDTH = 112
VIEWS = ["plan", "bird", "south"]
SCALE = 1   # -s 4 で4倍解像度のPNG（overlay-check.py の突き合わせに使う）
if "-w" in raw:
    i = raw.index("-w"); WIDTH = int(raw[i + 1]); raw = raw[:i] + raw[i + 2:]
if "-v" in raw:
    i = raw.index("-v"); VIEWS = raw[i + 1].split(","); raw = raw[:i] + raw[i + 2:]
if "-s" in raw:
    i = raw.index("-s"); SCALE = int(raw[i + 1]); raw = raw[:i] + raw[i + 2:]
HASH = raw[0].lstrip("#")
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "shots")
TARGET = "file://" + os.path.join(HERE, "index.html") + "#" + HASH

def ensure_chrome():
    try:
        json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
        return
    except Exception:
        pass
    subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
         "--allow-file-access-from-files", "--window-size=1500,1000",
         f"--user-data-dir=/tmp/cadkit-cdp-{PORT}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def exact(sock, size):
    data = b""
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError("closed")
        data += part
    return data

def send_frame(sock, obj):
    data = json.dumps(obj).encode()
    mask = os.urandom(4)
    size = len(data)
    if size < 126:
        head = bytes([0x81, 0x80 | size])
    elif size < 65536:
        head = bytes([0x81, 0xFE]) + struct.pack("!H", size)
    else:
        head = bytes([0x81, 0xFF]) + struct.pack("!Q", size)
    sock.sendall(head + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))

def recv_frame(sock):
    first, second = exact(sock, 2)
    opcode, size = first & 0x0F, second & 0x7F
    if size == 126:
        size = struct.unpack("!H", exact(sock, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", exact(sock, 8))[0]
    if second & 0x80:
        mask = exact(sock, 4)
        return opcode, bytes(v ^ mask[i % 4] for i, v in enumerate(exact(sock, size)))
    return opcode, exact(sock, size)

def connect():
    deadline = time.time() + 15
    while True:
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            ws = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
            break
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(0.2)
    p = urlparse(ws)
    sock = socket.create_connection((p.hostname, p.port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET {p.path} HTTP/1.1\r\nHost: {p.netloc}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                  f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(4096)
    if b" 101 " not in resp.split(b"\r\n", 1)[0]:
        raise RuntimeError(resp.decode(errors="ignore"))
    return sock

ensure_chrome()
sock = connect()
sock.settimeout(600)
send_frame(sock, {"id": 1, "method": "Runtime.enable"})
send_frame(sock, {"id": 2, "method": "Page.enable"})
send_frame(sock, {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}})
time.sleep(0.5)
send_frame(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
deadline = time.time() + 600
generated = False
while time.time() < deadline and not generated:
    opcode, rawf = recv_frame(sock)
    if opcode != 1:
        continue
    msg = json.loads(rawf)
    if msg.get("method") == "Runtime.consoleAPICalled":
        text = " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"])
        if "CADKIT_FAIL" in text:
            print("SHOT_FAIL 生成が失敗: " + text)
            sys.exit(1)
        if "CADKIT" in text and "_OK" in text:
            generated = True
if not generated:
    print("SHOT_FAIL タイムアウト（CADKIT_OKが出なかった）")
    sys.exit(2)

mid = [10]
def evaluate(expr, timeout=180):
    mid[0] += 1
    i = mid[0]
    send_frame(sock, {"id": i, "method": "Runtime.evaluate",
                      "params": {"expression": expr, "returnByValue": True}})
    end = time.time() + timeout
    while time.time() < end:
        opcode, rawf = recv_frame(sock)
        if opcode != 1:
            continue
        msg = json.loads(rawf)
        if msg.get("id") == i:
            return msg.get("result", {}).get("result", {}).get("value")
    raise TimeoutError(expr[:60])

# シーンbboxからビューごとのカメラ位置を決め、撮影してASCII＋PNGを返す
JS = """
(view=>{try{
 const c=window.__shotView(view,%S%);
 if(!c)return 'ERR unknown view '+view;
 const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
 const W=%W%,H=Math.max(24,Math.round(W*c.height/c.width*0.5)),ramp=' .:-=+*#%@';
 let s='';
 for(let y=0;y<H;y++){let row='';
  for(let x=0;x<W;x++){
   let a=0,l=0,n=0;
   for(let dy=0;dy<2;dy++)for(let dx=0;dx<2;dx++){
    const px=Math.min(c.width-1,Math.floor((x+dx/2)/W*c.width)),
     py=Math.min(c.height-1,Math.floor((y+dy/2)/H*c.height)),i=(py*c.width+px)*4;
    a+=d[i+3];l+=(d[i]*.3+d[i+1]*.59+d[i+2]*.11)/255;n++;}
   a/=n;l/=n;
   row+=a<40?' ':ramp[Math.min(9,Math.round((1-l)*9))];}
  s+=row.replace(/ +$/,'')+'\\n';}
 return s+'|PNG|'+c.toDataURL('image/png');
}catch(e){return 'ERR '+e.message+' '+(e.stack||'').split('\\n')[1];}
})('%V%')
""".replace("%W%", str(WIDTH)).replace("%S%", str(SCALE))

os.makedirs(OUTDIR, exist_ok=True)
fail = False
for view in VIEWS:
    r = evaluate(JS.replace("%V%", view))
    if not r or r.startswith("ERR"):
        print(f"SHOT_FAIL {view}: {r}")
        fail = True
        continue
    ascii_art, png = r.split("|PNG|")
    base = os.path.join(OUTDIR, f"{HASH}-{view}")
    with open(base + ".png", "wb") as f:
        f.write(base64.b64decode(png.split(",")[1]))
    with open(base + ".txt", "w") as f:
        f.write(ascii_art)
    print(f"SHOT_OK {view} -> shots/{HASH}-{view}.txt .png")
sys.exit(1 if fail else 0)
