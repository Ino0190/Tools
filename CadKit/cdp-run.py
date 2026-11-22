# 使い方: python3 cdp-run.py <ハッシュ名 or URL> [-v] [-o ログファイル]
#   例: python3 cdp-run.py shinden          （index.html#shinden を実行）
#       python3 cdp-run.py testrobot -v     （全consoleログ表示）
#       python3 cdp-run.py tinrobot --export-line shots/tinrobot-line.svg
#           --line-opts '{"smoothSilhouette":false,"fitTol":0}'  （線画の options を混ぜる。検証用: 曲面の輪郭を切る／折れ線のまま）
#       python3 cdp-run.py tinrobot --export-drawing shots/tinrobot-drawing.svg
#           （三面図＝第三角法・正面/上面/右側面・外形の寸法線・図枠つきの線画SVG。選択bodyが無ければ表示中の全部）
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
_chrome_watchdog = None
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
EXPORT_DRAWING = take_option("--export-drawing")  # 三面図（第三角法・正面/上面/右側面・寸法線・図枠）の線画SVG
DRAW_PAPER = take_option("--draw-paper", "A3")    # A3 / A4（横）
DRAW_TIERS = take_option("--draw-tiers")          # 寸法の段の上限（各面各辺）。既定6
LINE_OPTS = take_option("--line-opts")  # JSON。buildVisibleLineSVG の options に混ぜる（検証用）
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
# --camera-view iso: 平行投影に切り替えてアイソメ（方位45°・俯角35.264°）へ置いてから書き出す。
# 提案書の図に使う線画は寸法が素直に読める平行投影が要る（2026-08-21）。
# mPersp/setPerspective はwindowへ公開されていないのでボタンのclickが唯一の口。
CAMERA_VIEW = take_option("--camera-view")
# --line-angle yaw,pitch[,dist]: 角度を指定して線画を撮る（横長のシーンを横長の絵にする）
LINE_ANGLE = take_option("--line-angle")
# --anchors 名前1,名前2: 設備の投影位置をviewBox相対で書き出す（引き出し線の指し先に使う）
LINE_ANCHORS = take_option("--anchors")
LINE_INFO = take_option("--line-info")   # __lineArtViewInfo をJSONで保存するパス
LINE_OUTER = take_option("--line-outer")   # 外形線の太さ（既定3.0）
LINE_INNER = take_option("--line-inner")   # 内部線の太さ（既定0.8）
LINE_SIZE = take_option("--line-size")     # 投影の画素サイズ W,H（既定1600,900）
# --export-flow <dir>: 荷が流れる様子をコマ送りの線画で連番書き出す（frame00.svg…）。
# --export-animation はポーズ補間（人物）専用で、BHSの搬送ランタイムには効かない。
# こちらは window.__bhsAdvance(秒) でランタイムを進めながら、同じカメラで撮り続ける。
# 出来たコマ列は SlideKit/flow_to_movie.py が mp4 とポスター候補に変える（2026-08-21）
EXPORT_FLOW = take_option("--export-flow")
FLOW_FRAMES = max(2, min(120, int(take_option("--flow-frames", "12"))))
FLOW_STEP = max(0.02, min(10.0, float(take_option("--flow-step", "0.35"))))  # 1コマあたり進める秒数
# 自己検査がFAILでも成果物を出す。検査と書き出しは別の関心（BHSのtags期待値のように
# 検査側が陳腐化していても図は要ることがある）。既定では出さない
EXPORT_ON_FAIL = "--export-on-fail" in raw
if EXPORT_ON_FAIL:
    raw.remove("--export-on-fail")
DIM_EDIT_CHECK = "--dim-edit-check" in raw  # 図面→3D の寸法編集の自己検査（window.__dimEditSelfCheck）
if DIM_EDIT_CHECK:
    raw.remove("--dim-edit-check")
HOLE_CL_CHECK = "--hole-cl-check" in raw  # 穴の中心線の検査。板＋円カットのテストモデルで十字＋1本が出るか（window.__cadMakeSample）
if HOLE_CL_CHECK:
    raw.remove("--hole-cl-check")
BOM_CHECK = "--bom-check" in raw  # 部品表（BOM）の自己検査（window.__bomCheck）
if BOM_CHECK:
    raw.remove("--bom-check")
DIM_EDIT_SHOTS = take_option("--dim-edit-shots")  # 胴の幅を +8mm した前後の 3D(iso) PNG と作り直した図面SVG を出す先ディレクトリ
LINE_PARALLEL = "--parallel" in raw        # 平行投影で線画を出す（寸法が素直に読める）
if LINE_PARALLEL:
    raw.remove("--parallel")
args = [a for a in raw if a not in ("-v", "--as-user")]
VERBOSE = os.environ.get("VERBOSE") or "-v" in sys.argv
ROBOT_FALLBACK_TEST = os.environ.get("HEIAN_ROBOT_FALLBACK_TEST") == "1"
AS_USER = "--as-user" in sys.argv  # 一般利用者の起動を再現（navigator.webdriver=false）

def out(line):
    # 🚫 標準出力が閉じている（呼び出し元の中断・パイプ切断）とprintがBrokenPipeErrorで落ち、
    #    -o のログにも何も残らないまま実行が消える（2026-08-24に13分の実測を1件失った）。
    #    ログファイルへの記録を優先し、標準出力の失敗では止めない。
    if LOGFILE:
        with open(LOGFILE, "a") as f:
            f.write(line + "\n")
    try:
        print(line, flush=True)
    except (BrokenPipeError, ValueError, OSError):
        pass

TARGET = args[0] if args else "test"
if not TARGET.startswith(("file://", "http://", "https://")):
    here = os.path.dirname(os.path.abspath(__file__))
    TARGET = "file://" + os.path.join(here, "index.html") + "?allowFileOCCT=1&music=0#" + TARGET.lstrip("#")
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
         "--mute-audio",  # 2026-10-15 --headless=new は音をスピーカーへ出す。検査中に BGM・効果音が鳴らないよう出力だけ消す（AudioContext は動く）
         f"--user-data-dir={PROFILE_DIR}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    # 番犬: 起動元のPythonが死んだら（kill -9・タイムアウト強制終了含む）Chromeを道連れにする。
    # atexitは強制終了では走らず、残骸29プロセス約5GBが積もった（2026-08-19利用者報告の真因）。
    # 🚫PID監視(kill -0)はゾンビを生存と誤認する＝パイプ切断検知（catのEOF）で見張る
    global _chrome_watchdog
    if not os.environ.get("KEEP_CHROME"):
        _chrome_watchdog = subprocess.Popen(["/bin/sh", "-c",
            f"cat >/dev/null; sleep 1; pkill -f {PROFILE_DIR}"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def kill_chrome():
    # 専用Chrome（このポートのuser-data-dirを持つプロセス）だけを落とす
    subprocess.run(["pkill", "-f", PROFILE_DIR], check=False)
    time.sleep(1.2)

# 終了時に自分のChromeを片付ける。使い回したい時だけ KEEP_CHROME=1（連続実行の高速化用）。
# 🚫使い回し前提で残すと、並行セッションがポートを変えるたびに1ポート=1Chrome（平安京シーン込みで
# 約1.5GB）が積もり、実測87プロセス14.5GBでMac全体が遅くなった（2026-08-18利用者報告の真因）
import atexit, signal
if not os.environ.get("KEEP_CHROME"):
    atexit.register(kill_chrome)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))  # SIGTERMでもatexitを走らせる
BASE = {"heiangame": "CADKIT_GAME", "heiancontent": "HEIAN_CONTENT", "testloft": "CADKIT_LOFT", "testsweep": "CADKIT_SWEEP", "testbool": "CADKIT_BOOL",
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
            # timeoutなしだとdevtoolsが固まったChromeで永久に待つ（2026-08-17に発生）
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=3))
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
    try:
        sock = connect()
    except Exception:
        return None  # 接続不能=Chrome自体が固まっている。呼び出し側がfresh=Trueで再起動する
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
if ROBOT_FALLBACK_TEST:
    source = "(()=>{const original=JSON.parse.bind(JSON);JSON.parse=(text,reviver)=>{const value=original(text,reviver);if(value&&value.schemaVersion===1&&value.bodyCount===100&&value.robotBodyCount===85)value.schemaVersion=0;return value;};})();"
    send_frame(sock, {"id": 6, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": source}})
# 2026-10-17 一般利用者の起動を再現する（--as-user）。navigator.webdriver を false に見せる＝自己検査の分岐・チュートリアルが実ブラウザと同じ道を通る。
#   🚫 ヘッドレスは webdriver=true なので、実ブラウザだけで落ちる起動（散策の準備中92%で止まる）を検査が見逃した
if AS_USER:
    send_frame(sock, {"id": 7, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": "Object.defineProperty(Navigator.prototype,'webdriver',{get:()=>false,configurable:true});"}})
send_frame(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
# 焼き込みがstaleでブラウザ内生成へ落ちると大内裏だけで約820秒使う（実測774+47秒）。
# 全landmark＋寝殿造まで通すには1200秒では足りず、CADKIT_CDP_TIMEOUTで打ち切られていた（2026-08-24）
# heianterrainは他のChromeと同時に走ると3600秒でも足りないので、CDP_DEADLINEで延ばせるようにした（2026-08-24）
DEADLINE_SEC = int(os.environ.get("CDP_DEADLINE", "3600"))
sock.settimeout(DEADLINE_SEC)  # 大内裏の同期生成中はCDPイベントが十数分途切れる
deadline = time.time() + DEADLINE_SEC
result = None
navigated = False
content_retry = False
runtime_exceptions = []
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
        elif "HEIAN_GAME_BAD" in text:  # 自己検査の外れた条件名（2026-10-23: FAIL だけでは何が外れたか分からなかった）
            out(text[:400])
        if BASE == "HEIAN_CONTENT" and "HEIAN_CONTENT_RETRY" in text:
            content_retry = True
            if not VERBOSE: out(text[:400])
        # heianterrainは途中の部品検査（CADKIT_OK rajomon-detail 等）も同じ接頭辞で出すので、本体の行まで待つ（2026-10-03）
        ok_hit = BASE + "_OK" in text and (HASH != "heianterrain" or "CADKIT_OK heianterrain" in text)
        if ok_hit or BASE + "_FAIL" in text or (HASH in {"heiangame", "heianterrain"} and "CADKIT_FAIL heianterrain" in text):
            out(text)
            result = text
            break
    elif method == "Runtime.exceptionThrown" and navigated:
        d = msg["params"]["exceptionDetails"]
        detail = str(d.get("text")) + " " + str(d.get("exception", {}).get("description", ""))
        runtime_exceptions.append(detail)
        out("EXCEPTION " + detail)
if not result:
    out("CADKIT_CDP_TIMEOUT")
    sys.exit(2)
if BASE == "HEIAN_CONTENT" and "HEIAN_CONTENT_OK" in result and (content_retry or runtime_exceptions or "retries=0" not in result):
    out("HEIAN_CONTENT_COLD_FAIL retry=%s exceptions=%d result=%s" % (content_retry, len(runtime_exceptions), result))
    sys.exit(1)
if ROBOT_FALLBACK_TEST:
    expected = ('CADKIT_GAME_OK heiangame', 'actorSource=occt', 'occtRequested=true', 'actorBodies=85', 'gaitSteps=10', 'skipSteps=9')
    if all(token in result for token in expected):
        out("CADKIT_GAME_FALLBACK_OK robot invalid -> OCCT runtime")
        sys.exit(0)
    out("CADKIT_GAME_FALLBACK_FAIL " + result[:500])
    sys.exit(1)

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

if ("FAIL" not in result or EXPORT_ON_FAIL) and (EXPORT_PROJECT or EXPORT_PACKAGE or EXPORT_LINE
                                                or EXPORT_ANIMATION or EXPORT_FLOW or EXPORT_DRAWING):
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
    def line_art_expression():
        """線画SVGを作るJS式。--export-line と --export-flow で同じカメラ指定を使う。"""
        size = (LINE_SIZE or "1600,900").split(",")
        w, h = int(size[0]), int(size[1] if len(size) > 1 else size[0])
        opts = {}
        if LINE_OPTS:
            opts.update(json.loads(LINE_OPTS))
        if LINE_OUTER:
            opts["outerWidth"] = float(LINE_OUTER)
        if LINE_INNER:
            opts["innerWidth"] = float(LINE_INNER)
        if LINE_ANCHORS:
            opts["anchors"] = [a for a in LINE_ANCHORS.split(",") if a]
        if LINE_ANGLE:
            a = [float(v) for v in LINE_ANGLE.split(",")]
            yaw, pitch = a[0], a[1] if len(a) > 1 else 32.0
            dist = a[2] if len(a) > 2 else 1.35
            return f"window.__lineArtAngle({yaw},{pitch},{dist},{w},{h},{json.dumps(opts)})"
        if CAMERA_VIEW:
            # 名前付きビュー。ヘッドレスでも投影が合うカメラを内部で作る（--parallel で平行投影）
            return (f"window.__lineArtView({json.dumps(CAMERA_VIEW)},{w},{h},"
                    f"{json.dumps(opts)},{'true' if LINE_PARALLEL else 'false'})")
        opts.update({"width": w, "height": h})
        return f"window.__buildVisibleLineSVG({json.dumps(opts)})"

    if EXPORT_LINE:
        expr = line_art_expression()
        line_svg = evaluate_value(expr, 93)
        if not line_svg:
            raise RuntimeError("visible line SVG is empty")
        parent = os.path.dirname(os.path.abspath(EXPORT_LINE))
        os.makedirs(parent, exist_ok=True)
        with open(EXPORT_LINE, "w", encoding="utf-8") as f:
            f.write(line_svg)
        out(f"EXPORTED_LINE {EXPORT_LINE} chars={len(line_svg)}")
        if LINE_INFO:
            info = json.loads(evaluate_value("JSON.stringify(window.__lineArtViewInfo||null)", 96) or "null")
            with open(LINE_INFO, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            got = list((info or {}).get("anchors") or {})
            out(f"EXPORTED_LINE_INFO {LINE_INFO} anchors={len(got)} {'/'.join(got)}")
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
    if EXPORT_FLOW:
        # 荷が流れる様子をコマ送りで撮る。カメラは毎コマ同じ指定で作り直す（視点固定）。
        # 🚫 ランタイムを進めずに撮ると全コマ同じ絵になる。__bhsAdvance が無いモデルは即エラーにする
        #    （黙って12枚の同じ絵が出ると、mp4にした後まで気づけない）
        expr = line_art_expression()
        os.makedirs(EXPORT_FLOW, exist_ok=True)
        if not evaluate_value(f"!!window.__bhsAdvance", 97):
            raise RuntimeError("window.__bhsAdvance が無い。--export-flow は荷を流すモデル（bhs等）専用")
        written, sizes = [], []
        for i in range(FLOW_FRAMES):
            if i and not evaluate_value(f"window.__bhsAdvance({FLOW_STEP})", 98):
                raise RuntimeError("__bhsAdvance が false を返した（搬送ランタイムが動いていない）")
            svg = evaluate_value(expr, 99 + i, 300)
            if not svg:
                raise RuntimeError(f"frame{i:02d} の線画SVGが空")
            path = os.path.join(EXPORT_FLOW, f"frame{i:02d}.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            written.append(path)
            sizes.append(len(svg))
        # 全コマ同じ長さなら荷が動いていない疑い。警告として出す（長さは荷の位置で変わる）
        same = len(set(sizes)) == 1
        meta = {"frames": len(written), "step": FLOW_STEP, "expression": expr,
                "chars": sizes, "target": TARGET}
        # アンカー（設備の投影位置）は引き出し線の指し先に使う。コマ間でカメラは同じなので1回で足りる
        if LINE_ANCHORS:
            info = json.loads(evaluate_value("JSON.stringify(window.__lineArtViewInfo||null)", 1000) or "null")
            meta["anchors"] = (info or {}).get("anchors") or {}
            meta["viewBox"] = (info or {}).get("viewBox")
        with open(os.path.join(EXPORT_FLOW, "flow.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        out(f"EXPORTED_FLOW {EXPORT_FLOW} frames={len(written)} step={FLOW_STEP}s"
            f" chars={min(sizes)}..{max(sizes)}" + (" ⚠️SAME_SIZE(荷が動いていないかも)" if same else ""))
    if EXPORT_DRAWING:
        import re as _re, xml.dom.minidom as _mdom
        name = json.dumps(HASH, ensure_ascii=False)
        draw_opts = {"name": HASH, "paper": DRAW_PAPER}
        if DRAW_TIERS:
            draw_opts["maxDimTiers"] = int(DRAW_TIERS)
        draw_text = evaluate_value(f"JSON.stringify(window.__threeViewDrawing({json.dumps(draw_opts, ensure_ascii=False)}))", 95)
        draw = json.loads(draw_text) if draw_text else None
        if not draw:
            raise RuntimeError("three-view drawing is empty")
        svg, meta = draw["svg"], draw["meta"]
        parent = os.path.dirname(os.path.abspath(EXPORT_DRAWING))
        os.makedirs(parent, exist_ok=True)
        with open(EXPORT_DRAWING, "w", encoding="utf-8") as f:
            f.write(svg)
        # 検査1: SVG が well-formed（壊れていたら parseString が投げる）
        _mdom.parseString(svg)
        # 検査2: 3面（正面・上面・右側面）が揃っている
        found = set(_re.findall(r'data-cadkit-view="(front|top|right)"', svg))
        if found != {"front", "top", "right"}:
            raise RuntimeError(f"DRAWING_FAIL 3面が揃っていない views={sorted(found)}")
        # 検査3: 外形の全体寸法 W/H/D が外接箱から計算した値と一致する
        sz = meta["bbox"]["size"]  # [W,H,D]（model単位=mm）
        want = {"W": sz[0], "H": sz[1], "D": sz[2]}
        hits = dict(_re.findall(r'data-cadkit-dim="([WHD])" data-cadkit-dim-value="([0-9.]+)"', svg))
        if set(hits) != {"W", "H", "D"}:
            raise RuntimeError(f"DRAWING_FAIL 寸法が揃っていない dims={sorted(hits)}")
        for k in ("W", "H", "D"):
            got, exp = float(hits[k]), round(want[k], 1)
            if abs(got - exp) > 0.15:
                raise RuntimeError(f"DRAWING_FAIL 寸法 {k} が外接箱と不一致 got={got} want={exp}")
        # 検査4: 三面図の外接が描画領域の 60% 以上。ただし極端な縦横比で既に最大の規格尺度なら許容（尺度が最大に選べていればOK）
        vbb, vreg = meta["viewsBBox"], meta["viewRegion"]
        fill = max(vbb[0] / vreg[0], vbb[1] / vreg[1])
        if fill < 0.60 and meta.get("nextScaleFits"):
            raise RuntimeError(f"DRAWING_FAIL 三面図が小さい（より大きい尺度が入るのに選べていない）fill={fill:.2f} scale={meta['scale']}")
        # 検査5: 寸法線（寸法値の文字）の数が外形3より多い＝部品ごとの寸法が入っている
        dimtexts = _re.findall(r'data-cadkit-dimbox="([-0-9.,]+)"', svg)
        if len(dimtexts) <= 3:
            raise RuntimeError(f"DRAWING_FAIL 寸法が外形3本しかない n={len(dimtexts)}")
        # 検査6: 部品ごとの寸法値が、その body の投影外接箱（AABB成分）から計算した値と一致（±0.5mm）
        psz = meta["partSizes"]
        axis_i = {"W": 0, "H": 1, "D": 2}
        pdims = _re.findall(r'data-cadkit-pidx="(\d+)" data-cadkit-paxis="([WHD])" data-cadkit-pval="([0-9.]+)"', svg)
        if not pdims:
            raise RuntimeError("DRAWING_FAIL 部品ごとの寸法が1つも無い")
        for pidx, ax, pval in pdims:
            exp = round(psz[int(pidx)][axis_i[ax]], 1)
            if abs(float(pval) - exp) > 0.5:
                raise RuntimeError(f"DRAWING_FAIL 部品寸法 idx={pidx} {ax} got={pval} want={exp}")
        # 検査7: 寸法の数字の文字枠どうしが重ならない
        boxes = [tuple(float(v) for v in b.split(",")) for b in dimtexts]
        for i in range(len(boxes)):
            ax0, ay0, aw, ah = boxes[i]
            for j in range(i + 1, len(boxes)):
                bx0, by0, bw, bh = boxes[j]
                ox = min(ax0 + aw, bx0 + bw) - max(ax0, bx0)
                oy = min(ay0 + ah, by0 + bh) - max(ay0, by0)
                if ox > 0.3 and oy > 0.3:
                    raise RuntimeError(f"DRAWING_FAIL 寸法の数字が重なる box{i}={boxes[i]} box{j}={boxes[j]}")
        # 検査8: 段の数が各面各辺で maxDimTiers 以下
        mt = meta["maxDimTiers"]
        for side, n in meta["dimTiers"].items():
            if n > mt:
                raise RuntimeError(f"DRAWING_FAIL 段が多すぎる {side}={n}>{mt}")
        # 検査9: 部品表の行数が（表示する）body 数と合う
        rows = [r for r in _re.findall(r'data-cadkit-part-row="([^"]+)"', svg) if r != "more"]
        if len(rows) != meta["partsShown"]:
            raise RuntimeError(f"DRAWING_FAIL 部品表の行数 {len(rows)} != 表示部品 {meta['partsShown']}")
        exp_shown = min(meta["partsTotal"], 20)
        if meta["partsShown"] != exp_shown:
            raise RuntimeError(f"DRAWING_FAIL 表示部品数 {meta['partsShown']} != min(total,20)={exp_shown}")
        # 検査10: 引き出し円どうしが重ならない
        circ = [tuple(float(v) for v in c.split(",")) for c in _re.findall(r'data-cadkit-callout="([-0-9.,]+)"', svg)]
        for i in range(len(circ)):
            ax, ay, ar = circ[i]
            for j in range(i + 1, len(circ)):
                bx, by, br = circ[j]
                if (ax - bx) ** 2 + (ay - by) ** 2 < (ar + br - 0.2) ** 2:
                    raise RuntimeError(f"DRAWING_FAIL 引き出し円が重なる {circ[i]} {circ[j]}")
        # 検査11: 引き出し線どうしが交差しない（端点の共有は除く）
        leads = [tuple(float(v) for v in c.split(",")) for c in _re.findall(r'data-cadkit-leader="([-0-9.,]+)"', svg)]

        def _ccw(ax, ay, bx, by, cx, cy):
            return (cy - ay) * (bx - ax) - (by - ay) * (cx - ax)

        def _cross(p, q):
            x1, y1, x2, y2 = p
            x3, y3, x4, y4 = q
            d1 = _ccw(x3, y3, x4, y4, x1, y1)
            d2 = _ccw(x3, y3, x4, y4, x2, y2)
            d3 = _ccw(x1, y1, x2, y2, x3, y3)
            d4 = _ccw(x1, y1, x2, y2, x4, y4)
            return (d1 * d2 < -1e-6) and (d3 * d4 < -1e-6)

        for i in range(len(leads)):
            for j in range(i + 1, len(leads)):
                if _cross(leads[i], leads[j]):
                    raise RuntimeError(f"DRAWING_FAIL 引き出し線が交差 {i} {j} {leads[i]} {leads[j]}")
        # 検査12: shinden は尺度 1:5 以上（紙を十分に使えている）
        if HASH == "shinden" and float(meta.get("scaleFactor", 0)) + 1e-9 < 0.2:
            raise RuntimeError(f"DRAWING_FAIL shinden 尺度が 1:5 未満 scale={meta['scale']}")
        # 検査13: 部品ごとの位置寸法（data-cadkit-pos）の数を数える。段数は検査8で maxDimTiers 以下が担保される
        posdims = len(_re.findall(r'data-cadkit-pos="1"', svg))
        # 検査14（t82o）: 位置寸法の文字箱と引き出し円が重ならない
        pos_boxes = [tuple(float(v) for v in b.split(","))
                     for b in _re.findall(r'data-cadkit-pos="1"[^>]*?data-cadkit-dimbox="([-0-9.,]+)"', svg)]
        for (bx0, by0, bw, bh) in pos_boxes:
            for (cx, cy, cr) in circ:
                nx = max(bx0, min(cx, bx0 + bw))
                ny = max(by0, min(cy, by0 + bh))
                if (cx - nx) ** 2 + (cy - ny) ** 2 < (cr - 0.2) ** 2:
                    raise RuntimeError(f"DRAWING_FAIL 位置寸法が引き出し円に重なる box=({bx0:.1f},{by0:.1f},{bw:.1f},{bh:.1f}) circ=({cx:.1f},{cy:.1f},{cr})")
        # 検査15（t82o・K6で紙ごとのしきい値に 2026-11-15）: tinrobot は位置寸法が規定本数以上（段を増やせている）。
        # 🚫 以前は A3 前提の 12 本固定で、A4 だと正しい出力（紙が狭く入る本数が減る）でも落ちていた。
        _pos_min = {"A3": 12, "A4": 6}.get(meta.get("paper", DRAW_PAPER), 12)
        if HASH == "tinrobot" and posdims < _pos_min:
            raise RuntimeError(f"DRAWING_FAIL tinrobot 位置寸法が少ない pos={posdims}<{_pos_min} (paper={meta.get('paper')})")
        # 検査16（t82o・K6で紙を限定 2026-11-15）: 3モデルの尺度が不変（tinrobot 1:1 / shinden 1:5）。
        # この想定値は既定の A3 で測ったもの。A4 など小さい紙では収まる最大尺度が変わる（tinrobot は 1:2 が正しい）ので A3 のときだけ照合する。
        _exp_scale = {"tinrobot": 1.0, "shinden": 0.2}
        if meta.get("paper", DRAW_PAPER) == "A3" and HASH in _exp_scale and abs(float(meta.get("scaleFactor", 0)) - _exp_scale[HASH]) > 1e-6:
            raise RuntimeError(f"DRAWING_FAIL {HASH} 尺度が変わった scale={meta['scale']} (想定 1:{1/_exp_scale[HASH]:.0f})")
        # 検査17（K1・2026-11-15）: 紙幅に入らず落とした位置寸法の本数を凡例に出す（黙って減らさない）。
        # posOmitted が meta に無い＝数えていない＝黙って捨てている（直す前の形だと落ちる）。
        pos_omit = meta.get("posOmitted")
        if pos_omit is None:
            raise RuntimeError("DRAWING_FAIL meta.posOmitted が無い（落とした位置寸法の本数を数えていない）")
        pos_omit = int(pos_omit)
        if pos_omit > 0 and f"位置寸法 {pos_omit} 本省略" not in svg:
            raise RuntimeError(f"DRAWING_FAIL 位置寸法 {pos_omit} 本を落としたのに凡例に『位置寸法 {pos_omit} 本省略』が無い")
        out(f"EXPORTED_DRAWING {EXPORT_DRAWING} chars={len(svg)} views=3 paper={meta['paper']} scale={meta['scale']}"
            f" W={want['W']:.1f} H={want['H']:.1f} D={want['D']:.1f} fill={fill:.2f} dims={len(dimtexts)}"
            f" pos={posdims} posOmit={pos_omit} front={meta.get('front')} circ={len(circ)} parts={meta['partsShown']}/{meta['partsTotal']} CHECK_OK")
if DIM_EDIT_CHECK:
    dim = evaluate_value("JSON.stringify(window.__dimEditSelfCheck())", 200, 300)
    r = json.loads(dim) if dim else None
    if not r:
        out("DIMEDIT_FAIL self-check returned nothing")
        sys.exit(1)
    if not r.get("ok"):
        out("DIMEDIT_FAIL " + json.dumps(r, ensure_ascii=False))
        sys.exit(1)
    out("DIMEDIT_OK %s partDims=%s bound=%s ratio=%.2f 胴幅 %.1f->%.1f(got %.1f) redraw=%s restored=%.1f posPair=%s CHECK_OK" % (
        TARGET.split("#")[-1], r["partDims"], r["boundPartDims"], r["ratio"],
        r["before"], r["target"], r["after"], r["redrawn"], r["restored"], r.get("posPair")))

if DIM_EDIT_SHOTS:
    js = r"""(()=>{
 const T=window.__THREE,dbg=window.__laDebug(),ops=dbg.ops,bodies=dbg.bodies;
 const torso=ops.find(o=>o.type==='extrude'&&o.label==='\u80f4');
 if(!torso)return JSON.stringify({err:'no torso op'});
 const body=bodies.find(b=>(b.sourceOps||[]).includes(torso)&&!/\u30df\u30e9\u30fc/.test(b.name))||bodies.find(b=>(b.sourceOps||[]).includes(torso));
 if(!body)return JSON.stringify({err:'no torso body'});
 const r=window.__threeViewDrawing({});
 const re=/data-cadkit-bind='([^']*)'/g;let m,bind=null;
 while((m=re.exec(r.svg))){try{const b=JSON.parse(m[1].replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&amp;/g,'&'));if(b.op===torso.featureId&&b.axis==='W'){bind=b;break;}}catch(e){}}
 if(!bind)return JSON.stringify({err:'no torso W bind'});
 const sz=()=>{const s=new T.Box3().setFromObject(body.mesh).getSize(new T.Vector3());return s.x;};
 const shot=()=>{window.__shotView('iso',1.2);const c=window.__shotNow(1.2);return c?c.toDataURL('image/png'):null;};
 const w0=+sz().toFixed(1),target=+(w0+8).toFixed(1);
 const before=shot();
 const ok=window.__drawingDimEdit(bind,target);
 const after=shot(),afterW=+sz().toFixed(1);
 const r2=window.__threeViewDrawing({});
 window.__drawingDimEdit(bind,w0);
 return JSON.stringify({ok,w0,target,afterW,before,after,drawing:r2.svg});
})()"""
    raw_json = evaluate_value(js, 201, 300)
    r = json.loads(raw_json) if raw_json else None
    if not r or r.get("err"):
        out("DIMEDIT_SHOTS_FAIL " + json.dumps(r, ensure_ascii=False))
        sys.exit(1)
    os.makedirs(DIM_EDIT_SHOTS, exist_ok=True)

    def _save_png(data_url, path):
        b64 = data_url.split(",", 1)[1]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))

    _save_png(r["before"], os.path.join(DIM_EDIT_SHOTS, "torso-before.png"))
    _save_png(r["after"], os.path.join(DIM_EDIT_SHOTS, "torso-after.png"))
    with open(os.path.join(DIM_EDIT_SHOTS, "edited-drawing.svg"), "w", encoding="utf-8") as f:
        f.write(r["drawing"])
    out("DIMEDIT_SHOTS_OK %s 胴幅 %.1f->%.1f(3D got %.1f) dir=%s" % (
        TARGET.split("#")[-1], r["w0"], r["target"], r["afterW"], DIM_EDIT_SHOTS))

if HOLE_CL_CHECK:
    # 板＋ボス＋貫通穴（円カット）のテストモデルを組み、穴の中心線が出るか確かめる。
    # 軸が紙に向く図＝十字（h+v）・沿う図＝1本。viewごとに segの本数で大まかに判定する。
    import re as _re2
    js = (
        "(()=>{if(!window.__cadMakeSample())return JSON.stringify({err:'sample build failed'});"
        "const r=window.__threeViewDrawing({});if(!r)return JSON.stringify({err:'no drawing'});"
        "const g=(r.svg.match(/<g id=\"centerlines\"[\\s\\S]*?<\\/g>/)||[''])[0];"
        "const holes=(g.match(/data-cadkit-cl=\"hole\"/g)||[]).length;"
        "return JSON.stringify({holes,svg:r.svg});})()"
    )
    raw_json = evaluate_value(js, 202, 120)
    r = json.loads(raw_json) if raw_json else None
    if not r or r.get("err"):
        out("HOLE_CL_FAIL " + json.dumps(r, ensure_ascii=False))
        sys.exit(1)
    svg = r["svg"]
    holeseg = _re2.findall(r'<path d="(M[-0-9.]+ [-0-9.]+L[-0-9.]+ [-0-9.]+)" data-cadkit-cl="hole"', svg)
    # 十字＝同じ点を通る h と v が1組以上（端点の集合から交差を大まかに判定）: h seg と v seg が両方あること
    horiz = [s for s in holeseg if abs(float(s.split("L")[0][1:].split(" ")[1]) - float(s.split("L")[1].split(" ")[1])) < 0.01]
    vert = [s for s in holeseg if abs(float(s.split("L")[0][1:].split(" ")[0]) - float(s.split("L")[1].split(" ")[0])) < 0.01]
    if r["holes"] < 3 or not horiz or not vert:
        out(f"HOLE_CL_FAIL 穴の中心線が足りない holes={r['holes']} h={len(horiz)} v={len(vert)}")
        sys.exit(1)
    out(f"HOLE_CL_OK sample holes={r['holes']} h={len(horiz)} v={len(vert)}(十字1組+沿う図1本以上) CHECK_OK")
if BOM_CHECK:
    rawb = evaluate_value("JSON.stringify(window.__bomCheck())", 210, 300)
    r = json.loads(rawb) if rawb else None
    if not r:
        out("BOM_FAIL self-check returned nothing")
        sys.exit(1)
    checks = {
        "qty=visible": r["totalQty"] == r["visible"],
        "grouped>=5": r["grouped"] >= 5,
        "csvLines=rows+1": r["csvLines"] == r["rows"] + 1,
        "calc sheets/cells": r["sheetsOK"],
        "=SUM>=1": r["sumCount"] >= 1,
    }
    if not all(checks.values()):
        bad = [k for k, v in checks.items() if not v]
        out("BOM_FAIL " + json.dumps({"failed": bad, **r}, ensure_ascii=False))
        sys.exit(1)
    top = " / ".join("%s x%d(%gx%gx%g)" % (t["name"], t["qty"], t["w"], t["h"], t["d"]) for t in r.get("top", [])[:10])
    out("BOM_OK %s rows=%d qty=%d(=visible %d) grouped=%d csvLines=%d sum=%d  top: %s  CHECK_OK" % (
        TARGET.split("#")[-1], r["rows"], r["totalQty"], r["visible"], r["grouped"], r["csvLines"], r["sumCount"], top))

sys.exit(1 if "FAIL" in result else 0)