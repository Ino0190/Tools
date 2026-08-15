# 使い方: python3 cdp-run.py <ハッシュ名 or URL> [-v] [-o ログファイル]
#   例: python3 cdp-run.py shinden          （index.html#shinden を実行）
#       python3 cdp-run.py testrobot -v     （全consoleログ表示）
#       python3 cdp-run.py tinrobot --export-line shots/tinrobot-line.svg
#       python3 cdp-run.py tinrobot --export-animation shots/tinrobot-jump-animated.svg
#           --animation-fps 12 --animation-pose 片足ジャンプ
#       python3 cdp-run.py tinrobot --export-animation shots/tinrobot-waddle-animated.svg
#           --animation-fps 12 --animation-pose 'ヨチヨチ（左右ループ）' --animation-tracking subject
#       python3 cdp-run.py forkliftoperator --export-line shots/carry-opposite.svg
#           --export-pose 後傾 --camera-yaw 180
#       python3 cdp-run.py forkliftoperator --export-animation shots/forklift-v4.svg
#           --animation-pose '全ポーズ（順番）' --camera-yaw 180
#       python3 cdp-run.py daidairi -v -o /tmp/x.log  （ログをファイルへも逐次書き出し。
#         シェルの > リダイレクト不要＝コマンド承認なしで流せる。tail -f で監視できる）
# ヘッドレスChromeは無ければ自動起動する（ポート9251専用・使い回し）。
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

PORT = int(os.environ.get("CDP_PORT", "9251"))
PROFILE_TAG = "v2"
PROFILE_DIR = f"/tmp/cadkit-cdp-{PORT}-{PROFILE_TAG}"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
raw = sys.argv[1:]
LOGFILE = None
if "-o" in raw:
    i = raw.index("-o")
    LOGFILE = raw[i + 1] if i + 1 < len(raw) else None
    raw = raw[:i] + raw[i + 2:]

def take_option(name, default=None):
    global raw
    if name not in raw:
        return default
    i = raw.index(name)
    if i + 1 >= len(raw):
        raise SystemExit(f"{name} requires a value")
    value = raw[i + 1]
    raw = raw[:i] + raw[i + 2:]
    return value

EXPORT_PROJECT = take_option("--export-project")
EXPORT_PACKAGE = take_option("--export-package")
EXPORT_LINE = take_option("--export-line")
EXPORT_ANIMATION = take_option("--export-animation")
EXPORT_POSE = take_option("--export-pose")
CAMERA_YAW = max(-360.0, min(360.0, float(take_option("--camera-yaw", "0"))))
ANIMATION_FRAMES_RAW = take_option("--animation-frames")
ANIMATION_FRAMES = max(2, min(60, int(ANIMATION_FRAMES_RAW))) if ANIMATION_FRAMES_RAW is not None else None
ANIMATION_FPS = max(4, min(30, int(take_option("--animation-fps", "12"))))
ANIMATION_POSE = take_option("--animation-pose", "片足ジャンプ")
ANIMATION_TRACKING = take_option("--animation-tracking", "world")
if ANIMATION_TRACKING not in {"world", "subject"}: raise SystemExit("--animation-tracking must be world or subject")
EXPORT_COMPONENT = take_option("--export-component", "robot-root")
args = [a for a in raw if a != "-v"]
VERBOSE = os.environ.get("VERBOSE") or "-v" in sys.argv

def out(line):
    print(line, flush=True)
    if LOGFILE:
        with open(LOGFILE, "a") as f:
            f.write(line + "\n")

TARGET = args[0] if args else "test"
if not TARGET.startswith(("file://", "http://", "https://")):
    here = os.path.dirname(os.path.abspath(__file__))
    TARGET = "file://" + os.path.join(here, "index.html") + "?allowFileOCCT=1#" + TARGET.lstrip("#")
HASH = urlparse(TARGET).fragment

def ensure_chrome():
    try:
        json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
        return  # 既に起動済み（使い回し）
    except Exception:
        pass
    subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
         "--allow-file-access-from-files", "--window-size=1500,1000",
         f"--user-data-dir={PROFILE_DIR}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def kill_chrome():
    # 専用Chrome（このポートのuser-data-dirを持つプロセス）だけを落とす
    subprocess.run(["pkill", "-f", PROFILE_DIR], check=False)
    time.sleep(1.2)
BASE = {"heiangame": "CADKIT_GAME", "testloft": "CADKIT_LOFT", "testsweep": "CADKIT_SWEEP", "testbool": "CADKIT_BOOL",
        "testxform": "CADKIT_XFORM",
        "test": "CADKIT_TEST", "testbear": "CADKIT_BEAR", "testrobot": "CADKIT_ROBOT",
        "testaxis": "CADKIT_AXIS", "testedges": "CADKIT_EDGES", "testauto": "CADKIT_AUTO",
        "testunify": "CADKIT_UNIFY", "testshot": "CADKIT_SHOT", "testcad3": "CADKIT_CAD3",
        "testcad4": "CADKIT_CAD4", "testorganic": "CADKIT_ORGANIC",
        "testhist": "CADKIT_HIST", "forklift": "CADKIT_FORKLIFT",
        "forkliftdriver": "CADKIT_DRIVER", "forkliftoperator": "CADKIT_OPERATOR",
        }.get(HASH, "CADKIT")

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
def open_session(fresh=False):
    # 戻り値: 健全なsock。前の実行が無限ループ等でレンダラーを塞いでいると
    # about:blankへのnavigateが応答しないので、それを健全性チェックに使う
    if fresh:
        kill_chrome()
    ensure_chrome()
    sock = connect()
    for idx, method in enumerate(("Runtime.enable", "Page.enable"), 1):
        send_frame(sock, {"id": idx, "method": method})
    # 同じURL（ハッシュ違いだけ）だと再読み込みされないので、一度about:blankを経由する
    send_frame(sock, {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}})
    # 健全性チェック: レンダラーが前の実行のJSで塞がっているとevaluateが返らない
    send_frame(sock, {"id": 5, "method": "Runtime.evaluate", "params": {"expression": "1+1"}})
    sock.settimeout(5)
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            opcode, raw = recv_frame(sock)
        except socket.timeout:
            break
        if opcode != 1:
            continue
        if json.loads(raw).get("id") == 5:
            sock.settimeout(600)
            return sock
    try:
        sock.close()
    except Exception:
        pass
    return None

sock = open_session(fresh=bool(EXPORT_ANIMATION))
if sock is None:
    out("CHROME_STUCK: 前の実行が固まっているため専用Chromeを再起動")
    sock = open_session(fresh=True)
    if sock is None:
        out("CADKIT_CDP_TIMEOUT chrome restart failed")
        sys.exit(2)
time.sleep(0.3)
send_frame(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
deadline = time.time() + 600
result = None
navigated = False
while time.time() < deadline:
    opcode, raw = recv_frame(sock)
    if opcode != 1:
        continue
    msg = json.loads(raw)
    method = msg.get("method")
    if msg.get("id") == 3:
        navigated = True
    elif method == "Runtime.consoleAPICalled" and navigated:
        text = " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"])
        if VERBOSE:
            out("LOG: " + text[:400])
        if BASE + "_OK" in text or BASE + "_FAIL" in text:
            out(text)
            result = text
            break
    elif method == "Runtime.exceptionThrown" and navigated:
        d = msg["params"]["exceptionDetails"]
        out("EXCEPTION " + str(d.get("text")) + " " + str(d.get("exception", {}).get("description", "")))
if not result:
    out("CADKIT_CDP_TIMEOUT")
    sys.exit(2)

def evaluate_value(expression, ident, timeout=180):
    sock.settimeout(timeout)
    send_frame(sock, {"id": ident, "method": "Runtime.evaluate", "params": {
        "expression": expression, "returnByValue": True, "awaitPromise": True}})
    end = time.time() + timeout
    while time.time() < end:
        opcode, raw_result = recv_frame(sock)
        if opcode != 1:
            continue
        message = json.loads(raw_result)
        if message.get("id") != ident:
            continue
        if message.get("error"):
            raise RuntimeError(str(message["error"]))
        remote = message.get("result", {}).get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError(remote.get("description", "Runtime.evaluate failed"))
        return remote.get("value")
    raise TimeoutError("Runtime.evaluate export timeout")

if "FAIL" not in result and (EXPORT_PROJECT or EXPORT_PACKAGE or EXPORT_LINE or EXPORT_ANIMATION):
    if EXPORT_POSE or CAMERA_YAW:
        pose_name = json.dumps(EXPORT_POSE, ensure_ascii=False) if EXPORT_POSE else "null"
        changed = evaluate_value(f"window.__prepareLineExport({pose_name},{CAMERA_YAW})", 90)
        if not changed:
            raise RuntimeError(f"pose not found: {EXPORT_POSE}")
    if EXPORT_PROJECT:
        expression = "JSON.stringify(window.__projectDataZeroPose())"
        project = json.loads(evaluate_value(expression, 91))
        parent = os.path.dirname(os.path.abspath(EXPORT_PROJECT))
        os.makedirs(parent, exist_ok=True)
        with open(EXPORT_PROJECT, "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, separators=(",", ":"))
        out(f"EXPORTED_PROJECT {EXPORT_PROJECT} ops={len(project.get('ops', []))}")
    if EXPORT_PACKAGE:
        component = json.dumps(EXPORT_COMPONENT)
        package_text = evaluate_value(f"JSON.stringify(window.__assemblySvgPackageData({component})||window.__buildAssemblySvgPackage({component}))", 92)
        package = json.loads(package_text)
        if not package:
            raise RuntimeError(f"component not found: {EXPORT_COMPONENT}")
        os.makedirs(EXPORT_PACKAGE, exist_ok=True)
        for name, text in package["files"].items():
            with open(os.path.join(EXPORT_PACKAGE, name), "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(EXPORT_PACKAGE, "assembly.json"), "w", encoding="utf-8") as f:
            json.dump(package["manifest"], f, ensure_ascii=False, indent=2)
        out(f"EXPORTED_PACKAGE {EXPORT_PACKAGE} files={len(package['files']) + 1} component={EXPORT_COMPONENT}")
    if EXPORT_LINE:
        line_svg = evaluate_value("window.__buildVisibleLineSVG()", 93)
        if not line_svg:
            raise RuntimeError("visible line SVG is empty")
        parent = os.path.dirname(os.path.abspath(EXPORT_LINE))
        os.makedirs(parent, exist_ok=True)
        with open(EXPORT_LINE, "w", encoding="utf-8") as f:
            f.write(line_svg)
        out(f"EXPORTED_LINE {EXPORT_LINE} chars={len(line_svg)}")
    if EXPORT_ANIMATION:
        pose_name = json.dumps(ANIMATION_POSE, ensure_ascii=False)
        frame_arg = f",frames:{ANIMATION_FRAMES}" if ANIMATION_FRAMES is not None else ""
        tracking = json.dumps(ANIMATION_TRACKING)
        expression = f"(()=>{{const o=[...document.getElementById('cameraAnimPose').options].find(o=>o.textContent==={pose_name});return window.__buildAnimatedLineSVG({{poseKey:o?.value||'0',fps:{ANIMATION_FPS}{frame_arg},cameraMode:'current',tracking:{tracking}}})}})()"
        animation_svg = evaluate_value(expression, 94, 1800)
        if not animation_svg:
            raise RuntimeError(f"animated line SVG is empty: {ANIMATION_POSE}")
        parent = os.path.dirname(os.path.abspath(EXPORT_ANIMATION))
        os.makedirs(parent, exist_ok=True)
        with open(EXPORT_ANIMATION, "w", encoding="utf-8") as f:
            f.write(animation_svg)
        frame_label = str(ANIMATION_FRAMES) if ANIMATION_FRAMES is not None else "auto"
        out(f"EXPORTED_ANIMATION {EXPORT_ANIMATION} chars={len(animation_svg)} frames={frame_label} fps={ANIMATION_FPS} pose={ANIMATION_POSE}")
sys.exit(1 if "FAIL" in result else 0)
