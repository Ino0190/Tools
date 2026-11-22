# CadKitのサンプルをプロジェクトJSONとして書き出す
# 使い方: python3 export-model.py <ハッシュ名> <出力.json>
#   例: python3 export-model.py shinden1 ../平安京/models/寝殿造1_一町_区画全部.json
# ヘッドレスChromeで生成→location.hashとprojectDataの存在をポーリング→保存。
# consoleログ待ちはしない（Runtime.enableが古いログを再配信して誤認するため・2026-08-01修正）。
# 書き出したJSONはCadKitの ファイル>開く で復元できる。
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

PORT = int(os.environ.get("CDP_PORT", "9251"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HASH = sys.argv[1].lstrip("#")
OUT = sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = "file://" + os.path.join(HERE, "index.html") + "#" + HASH

def ensure_chrome():
    try:
        json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
        return
    except Exception:
        pass
    subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
         "--allow-file-access-from-files", f"--user-data-dir=/tmp/cadkit-cdp-{PORT}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    # 番犬: 起動元のPythonが死んだら（強制終了含む）Chromeを道連れにする（2026-08-19残骸5GBの再発防止）。
    # パイプ切断検知（catのEOF）＝ゾンビ誤認なし。Popenの参照をglobalに保持してパイプを開いたままにする
    global _chrome_watchdog
    _chrome_watchdog = subprocess.Popen(["/bin/sh", "-c",
        f"cat >/dev/null; sleep 1; pkill -f /tmp/cadkit-cdp-{PORT}"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def kill_chrome():
    subprocess.run(["pkill", "-f", f"cadkit-cdp-{PORT}"], check=False)
    time.sleep(1.2)

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

def wait_for(sock, msg_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            opcode, raw = recv_frame(sock)
        except socket.timeout:
            return None
        if opcode != 1:
            continue
        msg = json.loads(raw)
        if msg.get("id") == msg_id:
            return msg
    return None

def open_session(fresh=False):
    if fresh:
        kill_chrome()
    ensure_chrome()
    sock = connect()
    send_frame(sock, {"id": 1, "method": "Page.enable"})
    send_frame(sock, {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}})
    send_frame(sock, {"id": 5, "method": "Runtime.evaluate", "params": {"expression": "1+1"}})
    sock.settimeout(5)
    if wait_for(sock, 5, 6) is None:
        try:
            sock.close()
        except Exception:
            pass
        return None
    sock.settimeout(600)
    return sock

sock = open_session()
if sock is None:
    print("EXPORT_FAIL 前の実行が固まっている→専用Chromeを再起動")
    sock = open_session(fresh=True)
    if sock is None:
        print("EXPORT_FAIL chrome restart failed")
        sys.exit(2)
time.sleep(0.3)
send_frame(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
if wait_for(sock, 3, 30) is None:
    print("EXPORT_FAIL navigateが応答しない")
    sys.exit(2)
# 生成完了をポーリング（生成中はレンダラーが塞がるので応答自体が待ちになる）
ready_expr = (f"location.hash==='#{HASH}'&&typeof window.projectData==='function'"
              "&&window.projectData().ops.length>0")
deadline = time.time() + 600
ready = False
poll_id = 100
while time.time() < deadline:
    poll_id += 1
    send_frame(sock, {"id": poll_id, "method": "Runtime.evaluate",
                      "params": {"expression": ready_expr, "returnByValue": True}})
    msg = wait_for(sock, poll_id, 590)
    if msg and msg.get("result", {}).get("result", {}).get("value") is True:
        ready = True
        break
    time.sleep(1)
if not ready:
    print("EXPORT_FAIL 生成完了を確認できない（hash不一致かタイムアウト）")
    sys.exit(2)
send_frame(sock, {"id": 10, "method": "Runtime.evaluate",
                  "params": {"expression": "JSON.stringify(projectData())", "returnByValue": True}})
msg = wait_for(sock, 10, 120)
val = msg and msg["result"]["result"].get("value")
if not val:
    print("EXPORT_FAIL projectData()を取得できない: " + json.dumps(msg)[:300])
    sys.exit(1)
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with open(OUT, "w") as f:
    f.write(val)
data = json.loads(val)
print(f"EXPORT_OK {OUT} ops={len(data.get('ops', []))} bytes={len(val)}")
sys.exit(0)
