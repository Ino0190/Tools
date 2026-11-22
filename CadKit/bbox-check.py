# 平安京アセットのグループごとの実寸（bbox）を出す。2Dの実測値との突き合わせに使う。
# 使い方: python3 bbox-check.py daidairi
#         python3 bbox-check.py daidairi --expect ../平安京/refs/daidairi-layout.js
# 仕組み: index.html の window.__groupBBoxes（CDP経由）。cdp-run.py と同じ専用Chromeを使う。
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib.util
spec = importlib.util.spec_from_file_location("cdplib", os.path.join(HERE, "cdp-run.py"))

# cdp-run.py は import で実行まで走ってしまうので、必要な関数だけ写して使う
import base64, socket, struct, subprocess, time, urllib.request
from urllib.parse import urlparse
PORT = int(os.environ.get("CDP_PORT", "9251"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HASH = (sys.argv[1] if len(sys.argv) > 1 else "daidairi").lstrip("#")
EXPECT = None
if "--expect" in sys.argv:
    EXPECT = sys.argv[sys.argv.index("--expect") + 1]
TARGET = "file://" + os.path.join(HERE, "index.html") + "#" + HASH

def exact(s, n):
    d = b""
    while len(d) < n:
        p = s.recv(n - len(d))
        if not p: raise EOFError
        d += p
    return d
def send(s, o):
    data = json.dumps(o).encode(); m = os.urandom(4); n = len(data)
    if n < 126: h = bytes([0x81, 0x80 | n])
    elif n < 65536: h = bytes([0x81, 0xFE]) + struct.pack("!H", n)
    else: h = bytes([0x81, 0xFF]) + struct.pack("!Q", n)
    s.sendall(h + m + bytes(v ^ m[i % 4] for i, v in enumerate(data)))
def recv(s):
    a, b = exact(s, 2); op, n = a & 0x0F, b & 0x7F
    if n == 126: n = struct.unpack("!H", exact(s, 2))[0]
    elif n == 127: n = struct.unpack("!Q", exact(s, 8))[0]
    if b & 0x80:
        m = exact(s, 4)
        return op, bytes(v ^ m[i % 4] for i, v in enumerate(exact(s, n)))
    return op, exact(s, n)
def ensure():
    try:
        json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1)); return
    except Exception: pass
    subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                      "--allow-file-access-from-files", "--window-size=1500,1000",
                      f"--user-data-dir=/tmp/cadkit-cdp-{PORT}",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    # 番犬: 起動元のPythonが死んだら（強制終了含む）Chromeを道連れにする（2026-08-19残骸5GBの再発防止）。
    # パイプ切断検知（catのEOF）＝ゾンビ誤認なし。Popenの参照をglobalに保持してパイプを開いたままにする
    global _chrome_watchdog
    _chrome_watchdog = subprocess.Popen(["/bin/sh", "-c",
        f"cat >/dev/null; sleep 1; pkill -f /tmp/cadkit-cdp-{PORT}"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
def connect():
    end = time.time() + 15
    while True:
        try:
            t = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            ws = next(x["webSocketDebuggerUrl"] for x in t if x["type"] == "page"); break
        except Exception:
            if time.time() > end: raise
            time.sleep(0.2)
    p = urlparse(ws)
    s = socket.create_connection((p.hostname, p.port), timeout=5)
    k = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {p.path} HTTP/1.1\r\nHost: {p.netloc}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {k}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    r = b""
    while b"\r\n\r\n" not in r: r += s.recv(4096)
    return s

ensure()
sock = connect(); sock.settimeout(600)
send(sock, {"id": 1, "method": "Runtime.enable"})
send(sock, {"id": 2, "method": "Page.enable"})
send(sock, {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}})
time.sleep(0.5)
send(sock, {"id": 3, "method": "Page.navigate", "params": {"url": TARGET}})
ok = False
end = time.time() + 900
while time.time() < end and not ok:
    op, raw = recv(sock)
    if op != 1: continue
    m = json.loads(raw)
    if m.get("method") == "Runtime.consoleAPICalled":
        t = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"])
        if "CADKIT_FAIL" in t:
            print("BBOX_FAIL 生成失敗: " + t); sys.exit(1)
        if "CADKIT" in t and "_OK" in t: ok = True
if not ok:
    print("BBOX_FAIL タイムアウト"); sys.exit(2)

if "--body" in sys.argv:   # 単体ボディのbboxを見る: --body 紫宸殿屋根
    pfx = sys.argv[sys.argv.index("--body") + 1]
    send(sock, {"id": 98, "method": "Runtime.evaluate",
                "params": {"expression": f"JSON.stringify(window.__bodyBBox({json.dumps(pfx)}))",
                           "returnByValue": True}})
    end = time.time() + 120
    while time.time() < end:
        op, raw = recv(sock)
        if op != 1: continue
        m = json.loads(raw)
        if m.get("id") == 98:
            print(f"{pfx}: " + str(m.get("result", {}).get("result", {}).get("value")))
            sys.exit(0)
    print("BBOX_FAIL 応答なし"); sys.exit(3)

send(sock, {"id": 99, "method": "Runtime.evaluate",
            "params": {"expression": "JSON.stringify(window.__groupBBoxes())", "returnByValue": True}})
res = None
end = time.time() + 180
while time.time() < end:
    op, raw = recv(sock)
    if op != 1: continue
    m = json.loads(raw)
    if m.get("id") == 99:
        r = m.get("result", {})
        res = r.get("result", {}).get("value")
        if not res:
            print("BBOX_FAIL evaluate: " + json.dumps(r, ensure_ascii=False)[:600])
            sys.exit(3)
        break
if not res:
    print("BBOX_FAIL bboxが取れません（応答なし）"); sys.exit(3)
gs = json.loads(res)
lines = [f"{HASH} のグループ実寸（ワールド座標・単位=mm/1:100）"]
for g in gs:
    if not g.get("n"): continue
    lines.append(f"  {g['name']:<14} n={g['n']:>4} cx={g['cx']:>6} cz={g['cz']:>6} "
                 f"w={g['w']:>6} d={g['d']:>6} h={g['h']:>4}")
if EXPECT:
    txt = open(EXPECT).read()
    txt = txt[txt.index("{"):txt.rindex("}") + 1]
    exp = json.loads(txt)
    lines.append("")
    lines.append("2Dの実測値との差（大物3院）:")
    by = {g["name"]: g for g in gs}
    for b in exp["bigzones"]:
        g = by.get(b["name"])
        if not g:
            lines.append(f"  {b['name']}: 3Dにグループが無い"); continue
        lines.append(f"  {b['name']:<8} 中心差 dx={g['cx']-b['cx']:>5} dz={g['cz']-b['cz']:>5} / "
                     f"寸法差 dw={g['w']-b['w']:>5} dd={g['d']-b['d']:>5}")
out = os.path.join(HERE, "shots", f"{HASH}-bbox.txt")
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w").write("\n".join(lines) + "\n")
# 機械が読む用（overlay-check.py が真上図のpx→モデル座標の対応に使う）
json.dump(gs, open(os.path.join(HERE, "shots", f"{HASH}-bbox.json"), "w"), ensure_ascii=False)

# 全ボディの真上占有矩形（通りの通行チェック用）
send(sock, {"id": 97, "method": "Runtime.evaluate",
            "params": {"expression": "JSON.stringify(window.__bodiesXZ())", "returnByValue": True}})
end = time.time() + 180
while time.time() < end:
    op, raw = recv(sock)
    if op != 1: continue
    m = json.loads(raw)
    if m.get("id") == 97:
        v = m.get("result", {}).get("result", {}).get("value")
        if v:
            open(os.path.join(HERE, "shots", f"{HASH}-bodies.json"), "w").write(v)
        break
print("BBOX_OK -> shots/%s-bbox.txt .json / %s-bodies.json" % (HASH, HASH))
