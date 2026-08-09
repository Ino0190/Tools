# アイコンの自動目視チェック（icons-data.jsに追加したアイコンの形をKiroが自分で確認する）
#   python3 icon-check.py <id>     … 例: python3 icon-check.py kiro
# やること:
#   1. ヘッドレスChromeで icon-preview.html#id=<id> を開く（512/96/32pxの3サイズ描画）
#   2. 512px描画をスクショ → icon-shot-<id>.png に保存（人の目視用）
#   3. ASCIIアート（40×40）とメトリクス（bbox・余白・被覆率）を標準出力（Kiroの目視用）
import base64, importlib.util, io, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cdp", os.path.join(HERE, "cdp-check.py"))
cdp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cdp)

icon_id = sys.argv[1] if len(sys.argv) > 1 else ""
page = "file://" + os.path.join(HERE, "icon-preview.html") + (f"#id={icon_id}" if icon_id else "")
chrome, sock = cdp.boot(page=page, ready="!!document.getElementById('main')||!!document.getElementById('err')")
try:
    if cdp.ev(sock, "!!document.getElementById('err')"):
        print(f"NG アイコンが見つからない: {icon_id}"); sys.exit(1)
    r = cdp.ev(sock, "(function(){var b=document.getElementById('main').getBoundingClientRect();"
                     "return{x:b.x,y:b.y,w:b.width,h:b.height};})()")
    shot = cdp.call(sock, "Page.captureScreenshot", {"format": "png", "clip": {
        "x": r["x"], "y": r["y"], "width": r["w"], "height": r["h"], "scale": 1}})
    png = base64.b64decode(shot["data"])
    out = os.path.join(HERE, f"icon-shot-{icon_id or 'last'}.png")
    open(out, "wb").write(png)
finally:
    chrome.kill()
    subprocess.run(["pkill", "-f", "bk-check-profile"], capture_output=True)

from PIL import Image
im = Image.open(io.BytesIO(png)).convert("L")
W, H = im.size; px = im.load()
xs = [x for y in range(H) for x in range(W) if px[x, y] < 200]
ys = [y for y in range(H) for x in range(W) if px[x, y] < 200]
if not xs:
    print("NG 何も描画されていない"); sys.exit(1)
sc = 96.0 / W  # px → viewBox座標
bx0, bx1, by0, by1 = min(xs)*sc, max(xs)*sc, min(ys)*sc, max(ys)*sc
ink = sum(1 for y in range(H) for x in range(W) if px[x, y] < 200)
print(f"bbox(viewBox96): x {bx0:.0f}〜{bx1:.0f} / y {by0:.0f}〜{by1:.0f}  被覆率 {100.0*ink/(W*H):.1f}%")
warn = []
if bx0 < 3.5 or by0 < 3.5 or bx1 > 92.5 or by1 > 92.5: warn.append("はみ出し（線幅込みで0〜96を超えそう）")
if bx1 - bx0 < 55 and by1 - by0 < 55: warn.append("小さすぎ（有効領域8〜88に対して）")
print("警告: " + "・".join(warn) if warn else "余白OK（8〜88目安）")
G = 40
lines = ["+" + "-" * G + "+"]
for gy in range(G):
    row = ""
    for gx in range(G):
        x0, x1 = gx*W//G, max(gx*W//G+1, (gx+1)*W//G)
        y0, y1 = gy*H//G, max(gy*H//G+1, (gy+1)*H//G)
        vals = [px[x, y] for y in range(y0, y1) for x in range(x0, x1)]
        mean = sum(vals) / len(vals)
        row += "#" if mean < 110 else ("+" if mean < 200 else " ")
    lines.append("|" + row + "|")
lines.append("+" + "-" * G + "+")
txt = os.path.join(HERE, f"icon-shot-{icon_id or 'last'}.txt")
open(txt, "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print(f"スクショ: {out} / ASCII: {txt}")
