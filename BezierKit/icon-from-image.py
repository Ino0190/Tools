# 画像→アイコン自動生成パイプライン（ロゴ等の実物からアイコンを起こす）
#   python3 icon-from-image.py <画像> <id> <名前> [タグ,カンマ区切り] [--shape=light|dark|alpha] [--write]
# やること:
#   1. 画像から形のマスクを作る（--shape: light=明るい部分/dark=暗い部分/alpha=不透明部分。既定=auto）
#   2. BezierKitのトレース（cdp-check.py trace・COLORS=2・FIT=1）でベジェパス化
#   3. 最大の暗色パス＋その内側のパス（目などの穴）だけ残して viewBox 96 に正規化
#   4. icons-data.js のエントリを生成（--write で追記/同idは置換）→ icon-check.py で自動目視
#   5. 成功したら中間ファイル（マスク・トレースSVG）を削除（--keep で残す）
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a.split("=")[0][2:]: (a.split("=")[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
if len(args) < 3:
    print(__doc__ or "usage: icon-from-image.py <画像> <id> <名前> [タグ] [--shape=..] [--write]"); sys.exit(1)
img_path, icon_id, icon_name = args[0], args[1], args[2]
tags = args[3].split(",") if len(args) > 3 else []

# --- 1. マスク生成 ---
from PIL import Image
im = Image.open(img_path).convert("RGBA")
W, H = im.size; px = im.load()
shape = opts.get("shape", "auto")
if shape == "auto":
    has_alpha = any(px[x, y][3] < 128 for y in range(0, H, 7) for x in range(0, W, 7))
    shape = "alpha" if has_alpha else "dark"
def is_shape(p):
    r, g, b, a = p
    if a < 128: return False
    if shape == "light": return r + g + b > 550
    if shape == "dark": return r + g + b < 380
    return True  # alpha: 不透明なら形
mask = Image.new("RGB", (W, H), (255, 255, 255)); mp = mask.load()
n_ink = 0
for y in range(H):
    for x in range(W):
        if is_shape(px[x, y]): mp[x, y] = (0, 0, 0); n_ink += 1
stem = os.path.splitext(img_path)[0]
mask_path = stem + "-mask.png"; mask.save(mask_path)
print(f"1. マスク {mask_path}（shape={shape}・墨 {100.0*n_ink/(W*H):.0f}%）")

# --- 2. トレース ---
trace_path = stem + "-trace.svg"
env = dict(os.environ, COLORS="2", FIT="1")
r = subprocess.run([sys.executable, os.path.join(HERE, "cdp-check.py"), "trace", mask_path, trace_path],
                   env=env, capture_output=True, text=True, timeout=300)
if not os.path.exists(trace_path):
    print("NG トレース失敗:\n" + (r.stdout + r.stderr)[-800:]); sys.exit(1)
print(f"2. トレース {trace_path}")

# --- 3. 暗色パスの選別と正規化 ---
svg = open(trace_path).read()
paths = []  # (fill, d)
for m in re.finditer(r'<path\b([^>]*)>', svg):
    attrs = m.group(1)
    dm = re.search(r'd="([^"]+)"', attrs)
    fm = re.search(r'fill="(#[0-9a-fA-F]{3,6})"', attrs)
    if not dm or not fm: continue
    hexc = fm.group(1).lstrip("#")
    if len(hexc) == 3: hexc = "".join(c * 2 for c in hexc)
    lum = int(hexc[0:2], 16) * .3 + int(hexc[2:4], 16) * .6 + int(hexc[4:6], 16) * .1
    if lum < 128: paths.append(dm.group(1))
if not paths:
    print("NG 暗色パスが見つからない"); sys.exit(1)

TOK = re.compile(r'([MLCQZmlcqz])|(-?\d+\.?\d*(?:e-?\d+)?)')
def parse(d):
    out = []; nums = []; cmd = None
    for m in TOK.finditer(d):
        if m.group(1):
            if cmd: out.append((cmd, nums)); nums = []
            cmd = m.group(1)
        else: nums.append(float(m.group(2)))
    if cmd: out.append((cmd, nums))
    return out
def bbox(cmds):
    xs = []; ys = []
    for c, ns in cmds:
        for i in range(0, len(ns) - 1, 2): xs.append(ns[i]); ys.append(ns[i + 1])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None
parsed = [(d, parse(d)) for d in paths]
parsed = [(d, c, bbox(c)) for d, c in parsed if bbox(c)]
# 最大面積のパス=本体。本体bboxに収まるパス=穴（目など）も残す。プリセット等の外れは捨てる
parsed.sort(key=lambda t: (t[2][2] - t[2][0]) * (t[2][3] - t[2][1]), reverse=True)
bx0, by0, bx1, by1 = parsed[0][2]
keep = [parsed[0]] + [t for t in parsed[1:]
                      if t[2][0] >= bx0 - 2 and t[2][1] >= by0 - 2 and t[2][2] <= bx1 + 2 and t[2][3] <= by1 + 2]
print(f"3. パス {len(paths)}本 → 本体+内側 {len(keep)}本を採用")

# 96×96・余白10に正規化（縦横比維持・中央寄せ）
s = 76.0 / max(bx1 - bx0, by1 - by0)
ox = 10 + (76 - (bx1 - bx0) * s) / 2
oy = 10 + (76 - (by1 - by0) * s) / 2
def fmt(v): return f"{v:.1f}".rstrip("0").rstrip(".")
d_out = []
for _, cmds, _ in keep:
    parts = []
    for c, ns in cmds:
        t = []
        for i in range(0, len(ns) - 1, 2):
            t.append(fmt((ns[i] - bx0) * s + ox)); t.append(fmt((ns[i + 1] - by0) * s + oy))
        parts.append(c.upper() + " " + " ".join(t) if t else c.upper())
    d_out.append(" ".join(parts))
d_all = " ".join(d_out)

# --- 4. icons-data.js エントリ生成（fr:'evenodd'=穴を抜く） ---
data_path = os.path.join(HERE, "icons-data.js")
src = open(data_path).read()
nums = [int(n) for n in re.findall(r'num:(\d+)', src)]
old = re.search(r' \{num:(\d+), id:\'' + re.escape(icon_id) + r'\'.*?\]\},\n', src, re.S)
num = int(old.group(1)) if old else (max(nums) + 1 if nums else 1)
tag_js = ",".join(f"'{t}'" for t in tags)
entry = (f" {{num:{num}, id:'{icon_id}', name:'{icon_name}', tags:[{tag_js}], paths:[\n"
         f"  {{d:'{d_all}', fill:'currentColor', fr:'evenodd'}}]}},\n")
print("4. エントリ:\n" + entry[:200] + ("…" if len(entry) > 200 else ""))
if opts.get("write"):
    if old:
        src = src.replace(old.group(0), entry)
        print(f"   → icons-data.js の #{num} {icon_id} を置換")
    else:
        i = src.rfind("];")
        src = src[:i] + entry + src[i:]
        print(f"   → icons-data.js に #{num} {icon_id} を追加")
    open(data_path, "w").write(src)
    subprocess.run(["node", "--check", data_path], check=True)
    # --- 5. 自動目視 ---
    subprocess.run([sys.executable, os.path.join(HERE, "icon-check.py"), icon_id])
else:
    print("   （--write を付けると icons-data.js に反映して icon-check まで実行）")

# --- 6. 後片付け（中間ファイルは既定で消す・--keep で残す） ---
if not opts.get("keep"):
    for f in (mask_path, trace_path):
        try: os.remove(f)
        except OSError: pass
    print("5. 中間ファイル削除（マスク・トレースSVG。残すなら --keep）")
