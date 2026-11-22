# CadKitアセットの自動目視: ヘッドレスで生成→3方向撮影→ASCIIアート＋PNG保存
# 使い方: python3 shot-check.py <ハッシュ名> [-w 幅] [-v ビュー名,...]
#          python3 shot-check.py --launch  # ゲームのツアー地点8画角を平安京/launch-*.jpgへ保存
#   例: python3 shot-check.py dairi
#       python3 shot-check.py chodoin -v plan,south -w 90
#       python3 shot-check.py bhs --eye 6000,3000,6000 --at 2400,800,0 --name merge
#         ↑ 一部分を寄って見る（合流点・分岐点など）。ビュー名は --name（既定 zoom）
#       python3 shot-check.py bhs -v iso --advance 20
#         ↑ 撮る前に搬送ランタイムを20秒進める（荷が流れた先の姿を見る）
#       python3 shot-check.py tinrobot4-a --eval-file CadKit/tinrobot4-wrist-check.js --shots 画角.json
#         ↑ --eval-file＝撮る前にページで JS を1つ評価（Promise は待つ・返り値を EVAL の行に出す。window.__cad で関節を触れる）
#           --shots＝[[名前, 目x,目y,目z, 先x,先y,先z, (その1枚の前に評価する JS)], …] を1回の起動で撮る（2026-10-31）
# 出力: CadKit/shots/<ハッシュ>-<ビュー>.txt（ASCII目視用）と同名.png（人間確認用）
# ビュー: plan=真上 / bird=南東鳥瞰 / south=南から低め。カメラはシーンbboxから自動決定。
# 仕組み: index.htmlの window.__shotFrom（カメラ配置＋透過PNG撮影）をCDPから呼ぶ。
# BezierKitのicon-check.py（ASCII自動目視）のCadKit版。
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

_chrome_watchdog = None
PORT = int(os.environ.get("CDP_PORT", "9251"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
raw = sys.argv[1:]
LAUNCH = "--launch" in raw
if LAUNCH:
    raw.remove("--launch")
WIDTH = 112
VIEWS = ["plan", "bird", "south"]
SCALE = 1   # -s 4 で4倍解像度のPNG（overlay-check.py の突き合わせに使う）
if "-w" in raw:
    i = raw.index("-w"); WIDTH = int(raw[i + 1]); raw = raw[:i] + raw[i + 2:]
if "-v" in raw:
    i = raw.index("-v"); VIEWS = raw[i + 1].split(","); raw = raw[:i] + raw[i + 2:]
if "-s" in raw:
    i = raw.index("-s"); SCALE = int(raw[i + 1]); raw = raw[:i] + raw[i + 2:]
# 任意のカメラ位置・注視点で寄って撮る（合流点・分岐点のような局所の目視に使う）
EYE = AT = None
ZOOM_NAME = "zoom"
for opt in ("--eye", "--at", "--name"):
    if opt in raw:
        i = raw.index(opt); val = raw[i + 1]; raw = raw[:i] + raw[i + 2:]
        if opt == "--name":
            ZOOM_NAME = val
        else:
            nums = [float(v) for v in val.split(",")]
            if len(nums) != 3:
                sys.exit(f"{opt} は x,y,z の3つで指定する")
            if opt == "--eye":
                EYE = nums
            else:
                AT = nums
ADVANCE = 0.0   # 撮る前に搬送ランタイムを進める秒数（動きの確認用）
if "--advance" in raw:
    i = raw.index("--advance"); ADVANCE = float(raw[i + 1]); raw = raw[:i] + raw[i + 2:]
# シーンに登場する便・荷物・ULDのリストをJSONで書き出す（window.__bhsManifest）
MANIFEST = None
if "--manifest" in raw:
    i = raw.index("--manifest"); MANIFEST = raw[i + 1]; raw = raw[:i] + raw[i + 2:]
# 撮る前にページで JS を1つ評価する（返り値を EVAL の行に出す・Promise は待つ）。
# 関節を当てて姿勢を作ってから撮る（2026-10-31 まるロボの合掌・window.__cad を使う）
EVAL_FILE = None
if "--eval-file" in raw:
    i = raw.index("--eval-file"); EVAL_FILE = raw[i + 1]; raw = raw[:i] + raw[i + 2:]
# 寄った画角を何枚も1回で撮る: JSON の [[名前, 目x,目y,目z, 先x,先y,先z], …]（--eye の複数版）
SHOTS = None
if "--shots" in raw:
    i = raw.index("--shots")
    with open(raw[i + 1], encoding="utf-8") as f:
        SHOTS = json.load(f)
    raw = raw[:i] + raw[i + 2:]
if EYE and not AT:
    AT = [0.0, 0.0, 0.0]
if AT and not EYE:
    sys.exit("--at を使うときは --eye も指定する")
if LAUNCH:
    HASH = "heiangame"
    VIEWS = ["launch-bg", "launch-01", "launch-02", "launch-03", "launch-04", "launch-05", "launch-06", "launch-07"]
elif raw:
    HASH = raw[0].lstrip("#")
else:
    sys.exit("使い方: python3 shot-check.py <ハッシュ名> または --launch")
EXPECT = {"heiangame": "CADKIT_GAME", "forklift": "CADKIT_FORKLIFT", "forkliftdriver": "CADKIT_DRIVER", "forkliftoperator": "CADKIT_OPERATOR"}.get(HASH, "CADKIT")
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(os.path.dirname(HERE), "平安京") if LAUNCH else os.path.join(HERE, "shots")
MIME = "image/jpeg" if LAUNCH else "image/png"
EXT = ".jpg" if LAUNCH else ".png"
# 2026-10-20: OCCT で組む物（#tinrobot 等）は allowFileOCCT が無いと組めず CADKIT_OK が出ないまま止まった
# music=0: 2026-10-18 ?shot= だけだと音楽が既定で入り、heiangame の音楽・ヘッダー検査が落ちた
# 🚫 2026-10-20 上の注釈を行末に書き足したとき `+ "#" + HASH` が注釈に入り、ハッシュの無いURLを開いて全アセットで止まっていた
TARGET = "file://" + os.path.join(HERE, "index.html") + (f"?shot={int(time.time() * 1000)}&music=0" if LAUNCH else "?allowFileOCCT=1") + "#" + HASH

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
    # 番犬: 起動元のPythonが死んだら（強制終了含む）Chromeを道連れにする（2026-08-19残骸5GBの再発防止）。
    # パイプ切断検知（catのEOF）＝ゾンビ誤認なし。Popenの参照をglobalに保持してパイプを開いたままにする
    global _chrome_watchdog
    _chrome_watchdog = subprocess.Popen(["/bin/sh", "-c",
        f"cat >/dev/null; sleep 1; pkill -f /tmp/cadkit-cdp-{PORT}"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

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
# heiangameは焼き込み36MBの読み込み＋街の生成で600秒を超えることがある（2026-08-27）。cdp-run.pyのCDP_DEADLINEに倣って伸ばせるようにする
SHOT_DEADLINE = int(os.environ.get("SHOT_DEADLINE", 600))
sock = connect()
sock.settimeout(SHOT_DEADLINE)
send_frame(sock, {"id": 1, "method": "Runtime.enable"})
send_frame(sock, {"id": 2, "method": "Page.enable"})
send_frame(sock, {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}})
time.sleep(0.5)
send_frame(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
deadline = time.time() + SHOT_DEADLINE
generated = False
while time.time() < deadline and not generated:
    opcode, rawf = recv_frame(sock)
    if opcode != 1:
        continue
    msg = json.loads(rawf)
    if msg.get("method") == "Runtime.consoleAPICalled":
        text = " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"])
        if EXPECT + "_FAIL" in text:
            print("SHOT_FAIL 生成が失敗: " + text)
            sys.exit(1)
        if EXPECT + "_OK" in text:
            generated = True
if not generated:
    print("SHOT_FAIL タイムアウト（CADKIT_OKが出なかった）")
    sys.exit(2)

mid = [10]
def evaluate(expr, timeout=180):
    mid[0] += 1
    i = mid[0]
    send_frame(sock, {"id": i, "method": "Runtime.evaluate",
                      "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}})
    end = time.time() + timeout
    while time.time() < end:
        opcode, rawf = recv_frame(sock)
        if opcode != 1:
            continue
        msg = json.loads(rawf)
        if msg.get("id") == i:
            return msg.get("result", {}).get("result", {}).get("value")
    raise TimeoutError(expr[:60])

if LAUNCH:
    evaluate("window.__heianFinishEdges&&window.__heianFinishEdges()")  # 後回しの外形線を出し切ってから撮る（2026-09-13）
    prep = evaluate("JSON.stringify(window.__heianPrepareLaunchShot?.())")
    probe = evaluate("JSON.stringify({shrine:window.__heianFunaokaShrine?.(),tour:window.__heianFunaokaTourView?.(),sky:window.__heianSkyInfo?.()})")
    print("LAUNCH_PREP " + str(prep))
    print("LAUNCH_PROBE " + str(probe))

# シーンbboxからビューごとのカメラ位置を決め、撮影してASCII＋PNGを返す
JS = """
(view=>{try{
 if(%ADV%>0)window.__bhsAdvance?.(%ADV%);   // 荷を流してから撮る
 const eye=%EYE%;
 const c=eye?window.__shotFrom(eye[0],eye[1],eye[2],eye[3],eye[4],eye[5],%S%)
             :window.__shotView(view,%S%);
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
 return s+'|PNG|'+c.toDataURL('%MIME%',.9);
}catch(e){return 'ERR '+e.message+' '+(e.stack||'').split('\\n')[1];}
})('%V%')
""".replace("%W%", str(WIDTH)).replace("%S%", str(SCALE)).replace("%MIME%", MIME) \
   .replace("%ADV%", repr(ADVANCE))

if MANIFEST:
    raw_manifest = evaluate("JSON.stringify(window.__bhsManifest?.()||null)")
    data = json.loads(raw_manifest or "null")
    if not data:
        sys.exit("MANIFEST_FAIL window.__bhsManifest がありません")
    parent = os.path.dirname(os.path.abspath(MANIFEST))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("MANIFEST_OK %s flights=%d bags=%d uld=%d" % (
        MANIFEST, len(data.get("flights", [])), len(data.get("bags", [])), len(data.get("uld", []))))

if EVAL_FILE:
    with open(EVAL_FILE, encoding="utf-8") as f:
        print("EVAL " + str(evaluate(f.read(), timeout=600)))

if EYE:
    VIEWS = [ZOOM_NAME]
if SHOTS:
    VIEWS = [s[0] for s in SHOTS]
os.makedirs(OUTDIR, exist_ok=True)
# 起動画像12枚の退避・比較ページ・追加4枚は heian-launch.py が受け持つ（ここは8枚を撮るだけ）
fail = False
for view in VIEWS:
    eye = next((s[1:7] for s in (SHOTS or []) if s[0] == view), (EYE + AT) if EYE else None)
    pre = next((s[7] for s in (SHOTS or []) if s[0] == view and len(s) > 7), None)
    if pre:  # 8つ目＝その1枚の前に評価する JS（姿勢を替えて撮る）
        print(f"PRE {view} " + str(evaluate(pre)))
    r = evaluate(JS.replace("%V%", view).replace("%EYE%", json.dumps(eye) if eye else "null"))
    if not r or r.startswith("ERR"):
        print(f"SHOT_FAIL {view}: {r}")
        fail = True
        continue
    ascii_art, png = r.split("|PNG|")
    base = os.path.join(OUTDIR, view if LAUNCH else f"{HASH}-{view}")
    with open(base + EXT, "wb") as f:
        f.write(base64.b64decode(png.split(",")[1]))
    if not LAUNCH:
        with open(base + ".txt", "w") as f:
            f.write(ascii_art)
        print(f"SHOT_OK {view} -> shots/{HASH}-{view}.txt .png")
    else:
        print(f"SHOT_OK {view} -> ../平安京/{view}.jpg")
if LAUNCH and not fail:
    info_raw = evaluate("JSON.stringify(window.__heianLaunchShotInfo||null)")
    try:
        info = json.loads(info_raw or "null")
    except json.JSONDecodeError:
        info = None
    if not info or info.get("view") != "launch-07" or info.get("mobFormations", 0) < 1 or info.get("crowdVisiblePoints", 0) < 1 or info.get("crowdPeople") != 420:
        print("SHOT_FAIL launch-07に牛車・群衆が写っていません: " + str(info_raw))
        fail = True
    else:
        print("LAUNCH_CAST_OK " + str(info_raw))
sys.exit(1 if fail else 0)
