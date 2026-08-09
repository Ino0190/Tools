#!/usr/bin/env python3
# kit-overview.html に貼るキット画面のスクショ。1280×800（16:10）のウィンドウをそのまま撮る。
#   python3 kits-img/deck-shot.py          # 全部
#   python3 kits-img/deck-shot.py cadkit   # 1つだけ
# 出力: kits-img/deck/<name>.png（2560×1600・Retina2倍）
# 切り出しはしない（枠側を16:10に合わせる）。デッキ内の画像枠は全部このアス比。
# 準備JS付きで撮れるのが kits-img/shoot.py との違い（SlideKitの編集モードON等）。
import base64, importlib.util, io, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "deck")
spec = importlib.util.spec_from_file_location("cdp", os.path.join(ROOT, "BezierKit", "cdp-check.py"))
cdp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cdp)

W, H = 1280, 800

# name: (ページ, 描画待ち秒, 準備JS)
SHOTS = {
    'slidekit':     ('SlideKit/pattern-catalog.html', 4,
                     "document.getElementById('seEdit').click()"),
    'dashboardkit': ('DashboardKit/gym-demo.html',    6, None),
    'archkit':      ('ArchKit/gym-demo.html',         6, None),
    'ganttkit':     ('GanttKit/index.html',           5, None),
    'bezierkit':    ('BezierKit/index.html',          5, None),
    'cadkit':       ('CadKit/index.html#tinrobot',   42, None),
    'capturekit':   ('CaptureKit/index.html',         5, None),
}

def shoot(name):
    page, wait, prep = SHOTS[name]
    url = "file://" + os.path.join(ROOT, page)
    chrome, sock = cdp.boot(page=url, ready="document.readyState==='complete'")
    try:
        cdp.call(sock, "Emulation.setDeviceMetricsOverride",
                 {"width": W, "height": H, "deviceScaleFactor": 2, "mobile": False})
        time.sleep(wait)
        if prep:
            cdp.ev(sock, prep); time.sleep(2)
        shot = cdp.call(sock, "Page.captureScreenshot", {"format": "png",
                        "clip": {"x": 0, "y": 0, "width": W, "height": H, "scale": 1}})
        png = base64.b64decode(shot["data"])
    finally:
        chrome.kill()
        subprocess.run(["pkill", "-f", "bk-check-profile"], capture_output=True)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".png")
    open(path, "wb").write(png)
    from PIL import Image
    w, h = Image.open(path).size
    print(f"{name}: {w}x{h}px（{w/h:.3f}） {len(png):,}B  {page}")

for n in (sys.argv[1:] or list(SHOTS)):
    if n not in SHOTS:
        print(f"{n}: 不明（候補: {' '.join(SHOTS)}）"); continue
    shoot(n)
