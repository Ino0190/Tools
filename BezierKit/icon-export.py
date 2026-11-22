# アイコンの実用サイズ書き出し（icons-data.jsのアイコンをPNG / favicon.ico / .icnsへ）
#   python3 icon-export.py <id>                     … 例: python3 icon-export.py gear
#   python3 icon-export.py <id> --color '#21537f'   … 描画色を指定（既定 #121212）
#   python3 icon-export.py <id> --out <dir>         … 出力先（既定 export/<id>/）
# やること:
#   1. ヘッドレスChromeでアイコンを各サイズへラスター化（16〜1024px・サイズごとに再ベクター描画）
#   2. PNG一式（16/32/48/64/128/256/512）+ favicon.ico（16/32/48内蔵）+ <id>.icns（iconutil）を出力
#   3. 16pxのASCIIアートを標準出力（小サイズで潰れていないかのKiro目視用）
import argparse, base64, importlib.util, io, json, os, re, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cdp", os.path.join(HERE, "cdp-check.py"))
cdp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cdp)

ap = argparse.ArgumentParser()
ap.add_argument("id", nargs="?", default="", help="アイコンid（省略時は最後に追加されたアイコン）")
ap.add_argument("--color", default="#121212", help="描画色hex（currentColor部分に適用）")
ap.add_argument("--out", default="", help="出力先ディレクトリ")
args = ap.parse_args()
if args.id and not re.fullmatch(r"[a-z0-9-]+", args.id):
    print(f"NG idは英小文字・数字・ハイフンのみ: {args.id}"); sys.exit(1)
if not re.fullmatch(r"#[0-9a-fA-F]{6}", args.color):
    print(f"NG 色は #rrggbb 形式: {args.color}"); sys.exit(1)

PNG_SIZES = [16, 32, 48, 64, 128, 256, 512]
ALL_SIZES = PNG_SIZES + [1024]          # 1024は.icnsの512@2x用
ICO_SIZES = [16, 32, 48]
ICONSET = {16: ["icon_16x16.png"], 32: ["icon_16x16@2x.png", "icon_32x32.png"],
           64: ["icon_32x32@2x.png"], 128: ["icon_128x128.png"],
           256: ["icon_128x128@2x.png", "icon_256x256.png"],
           512: ["icon_256x256@2x.png", "icon_512x512.png"], 1024: ["icon_512x512@2x.png"]}

RENDER_JS = """(async()=>{
  const id=%s, color=%s, sizes=%s;
  const ic=id?window.ICONS.find(i=>i.id===id):window.ICONS[window.ICONS.length-1];
  if(!ic)return JSON.stringify({err:'アイコンが見つからない: '+id});
  const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
  const body=ic.paths.map(p=>{
    const fill=p.fill?String(p.fill).replace('currentColor',color):'none';
    const stroke=p.fill?(p.stroke?String(p.stroke).replace('currentColor',color):'none'):color;
    let a='d="'+esc(p.d)+'" fill="'+fill+'" stroke="'+stroke+'" stroke-width="'+(p.width||8)
      +'" stroke-linecap="round" stroke-linejoin="round"';
    if(p.fr)a+=' fill-rule="'+p.fr+'"';
    if(p.opacity)a+=' opacity="'+p.opacity+'"';
    return '<path '+a+'/>';
  }).join('');
  const out={id:ic.id,name:ic.name,png:{}};
  for(const sz of sizes){
    // サイズごとにwidth/height入りSVGを作り直す＝Chromeがそのサイズでベクター再描画する（拡縮ボケ防止）
    const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="'+sz
      +'" height="'+sz+'">'+body+'</svg>';
    const img=new Image();
    img.src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(svg)));
    await img.decode();
    const cv=document.createElement('canvas');cv.width=cv.height=sz;
    cv.getContext('2d').drawImage(img,0,0,sz,sz);
    out.png[sz]=cv.toDataURL('image/png').split(',')[1];
  }
  return JSON.stringify(out);
})()"""

def write_ico(path, pngs):
    """PNG内蔵ICO（サイズ昇順の[(size, bytes)]）。Vista以降・全ブラウザが読める形式。"""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, png in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png; offset += len(png)
    open(path, "wb").write(head + entries + blobs)

page = "file://" + os.path.join(HERE, "icon-preview.html") + (f"#id={args.id}" if args.id else "")
chrome, sock = cdp.boot(page=page, ready="!!window.ICONS")
try:
    res = json.loads(cdp.ev(sock, RENDER_JS % (json.dumps(args.id), json.dumps(args.color),
                                               json.dumps(ALL_SIZES)), await_promise=True))
finally:
    chrome.kill()
    subprocess.run(["pkill", "-f", "bk-check-profile"], capture_output=True)
if res.get("err"):
    print("NG " + res["err"]); sys.exit(1)

icon_id = res["id"]
out_dir = args.out or os.path.join(HERE, "export", icon_id)
os.makedirs(out_dir, exist_ok=True)
png = {int(k): base64.b64decode(v) for k, v in res["png"].items()}

# 1) PNG一式
for sz in PNG_SIZES:
    open(os.path.join(out_dir, f"{icon_id}-{sz}.png"), "wb").write(png[sz])

# 2) favicon.ico（16/32/48内蔵）
write_ico(os.path.join(out_dir, "favicon.ico"), [(sz, png[sz]) for sz in ICO_SIZES])

# 3) .icns（macOS標準のiconutilで生成。失敗しても他の出力は残す）
icns_note = ""
iconset = os.path.join(out_dir, f"{icon_id}.iconset")
os.makedirs(iconset, exist_ok=True)
for sz, names in ICONSET.items():
    for name in names:
        open(os.path.join(iconset, name), "wb").write(png[sz])
r = subprocess.run(["iconutil", "-c", "icns", "-o", os.path.join(out_dir, f"{icon_id}.icns"), iconset],
                   capture_output=True, text=True)
shutil.rmtree(iconset)
if r.returncode != 0:
    icns_note = f"（icnsはNG: {r.stderr.strip()[:120]}）"

# 4) 16px ASCIIプレビュー（潰れチェック用・アンチエイリアスは+で表現）
from PIL import Image
im = Image.open(io.BytesIO(png[16])).convert("LA")
w, h = im.size; px = im.load()
lines = ["+" + "-" * w + "+"]
for y in range(h):
    row = ""
    for x in range(w):
        lum, a = px[x, y]
        v = 255 - (255 - lum) * a // 255   # 透明地は白扱い
        row += "#" if v < 110 else ("+" if v < 200 else " ")
    lines.append("|" + row + "|")
lines.append("+" + "-" * w + "+")
ink = sum(1 for y in range(h) for x in range(w) if px[x, y][1] > 60 and px[x, y][0] < 200)
print(f"アイコン: {icon_id}（{res['name']}） 色: {args.color}")
print("\n".join(lines))
print(f"16px被覆率 {100.0*ink/(w*h):.0f}%" + ("（薄い＝16pxで消えかけの可能性）" if ink < 20 else ""))
files = sorted(os.listdir(out_dir))
print(f"出力: {out_dir}/ … {', '.join(files)} {icns_note}")
