#!/usr/bin/env python3
"""資料用アイコンの一括検査（2026-11-19）。icons-data.js に入れる前の下書きファイルを見る。

    python3 icon-batch-check.py _icons_new/common.js

下書きファイルは  window.NEW_ICONS = [ {id, name, tags, paths:[{d}...]}, ... ];  の形（icons-data.js と同じ書き方・num は不要）。
やること:
  1. 全部を 1 枚の HTML に並べ、ヘッドレス Chrome の --screenshot で撮る（CDP を使わない＝何本同時に回してもぶつからない）
  2. アイコンごとに 192px の枠を切り出し、bbox・余白・被覆率・ASCII(32×32) を出す
  3. 一覧画像 <file>.sheet.png（192px と 32px を並べた見比べ用）を書く
形の決まりは icons-data.js 先頭のコメント（96×96・線幅8・丸い端・余白8以上・平行線の間は16以上）。
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def load(path):
    src = open(path, encoding="utf-8").read()
    js = ("global.window=global;" + src +
          ";process.stdout.write(JSON.stringify(window.NEW_ICONS||[]))")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if r.returncode != 0:
        print("NG 下書きが読めない:", r.stderr[-400:]); sys.exit(1)
    return json.loads(r.stdout)


def svg_of(ic, size, color="#121212"):
    parts = []
    for p in ic.get("paths", []):
        fill = "currentColor" if p.get("fill") else "none"
        stroke = (p.get("stroke") or "none") if p.get("fill") else "currentColor"
        op = f' opacity="{p["opacity"]}"' if p.get("opacity") is not None else ""
        parts.append(f'<path d="{p["d"]}" fill="{fill}" stroke="{stroke}" stroke-width="{p.get("width", 8)}" '
                     f'stroke-linecap="round" stroke-linejoin="round"{op}/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="{size}" height="{size}" '
            f'style="color:{color};display:block">{"".join(parts)}</svg>')


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(2)
    path = os.path.abspath(args[0])
    icons = load(path)
    if not icons:
        print("NG NEW_ICONS が空"); sys.exit(1)
    ids = [i.get("id") for i in icons]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    known = set(re.findall(r"id:'([^']+)'", open(os.path.join(HERE, "icons-data.js"), encoding="utf-8").read()))
    clash = [x for x in ids if x in known]
    CELL, COLS = 240, 6
    rows = (len(icons) + COLS - 1) // COLS
    cells = []
    for i, ic in enumerate(icons):
        cells.append(f'<div class="c"><div class="big">{svg_of(ic, 192)}</div>'
                     f'<div class="sm">{svg_of(ic, 32)}{svg_of(ic, 16)}</div>'
                     f'<div class="t">{ic.get("name")}<br><small>{ic.get("id")}</small></div></div>')
    html = ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#fff;font:13px 'Hiragino Sans',sans-serif}"
            f".g{{display:grid;grid-template-columns:repeat({COLS},{CELL}px)}}"
            f".c{{width:{CELL}px;height:{CELL+60}px;box-sizing:border-box;border:1px solid #eee;position:relative}}"
            ".big{position:absolute;left:24px;top:8px}.sm{position:absolute;left:8px;top:206px;display:flex;gap:8px;align-items:center}"
            ".t{position:absolute;left:70px;top:206px;line-height:1.3}small{color:#888}</style>"
            f"<div class=g>{''.join(cells)}</div>")
    tmpd = tempfile.mkdtemp(prefix="bk_iconbatch_")
    hp = os.path.join(tmpd, "sheet.html")
    open(hp, "w", encoding="utf-8").write(html)
    shot = path.rsplit(".", 1)[0] + ".sheet.png"
    W, H = COLS * CELL, rows * (CELL + 60)
    if os.path.exists(shot):
        os.remove(shot)
    # --screenshot は撮ったあと Chrome が居座ることがあるので、ファイルができたら止める
    proc = subprocess.Popen([CHROME, "--headless=new", "--mute-audio", "--hide-scrollbars", "--disable-gpu",
                             f"--user-data-dir={tmpd}/prof", f"--window-size={W},{H}",
                             f"--screenshot={shot}", "file://" + hp],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time
    t0 = time.time()
    while time.time() - t0 < 90:
        if os.path.exists(shot) and os.path.getsize(shot) > 0:
            time.sleep(0.5); break
        if proc.poll() is not None: break
        time.sleep(0.2)
    proc.kill()
    if not os.path.exists(shot):
        print("NG 撮れなかった（Chrome）"); sys.exit(1)
    from PIL import Image
    im = Image.open(shot).convert("L")
    px = im.load()
    bad = 0
    for i, ic in enumerate(icons):
        ox, oy = (i % COLS) * CELL + 24, (i // COLS) * (CELL + 60) + 8
        xs, ys, ink = [], [], 0
        for y in range(192):
            for x in range(192):
                if px[ox + x, oy + y] < 200:
                    xs.append(x); ys.append(y); ink += 1
        warn = []
        if not xs:
            print(f"■ {ic['id']}（{ic.get('name')}）: NG 何も描かれていない"); bad += 1; continue
        sc = 96 / 192
        bx0, bx1, by0, by1 = min(xs) * sc, max(xs) * sc, min(ys) * sc, max(ys) * sc
        if bx0 < 3.5 or by0 < 3.5 or bx1 > 92.5 or by1 > 92.5: warn.append("はみ出し")
        if bx1 - bx0 < 55 and by1 - by0 < 55: warn.append("小さすぎ")
        cov = 100 * ink / (192 * 192)
        if cov > 45: warn.append("塗りが重い（被覆率%.0f%%）" % cov)
        if not ic.get("tags"): warn.append("tags が空")
        if ic.get("id") in clash: warn.append("id が icons-data.js と重複")
        if ic.get("id") in dup: warn.append("id が下書き内で重複")
        if warn: bad += 1
        G = 32
        art = []
        for gy in range(G):
            row = ""
            for gx in range(G):
                vals = [px[ox + x, oy + y] for y in range(gy * 6, gy * 6 + 6) for x in range(gx * 6, gx * 6 + 6)]
                m = sum(vals) / len(vals)
                row += "#" if m < 110 else ("+" if m < 200 else " ")
            art.append("|" + row + "|")
        print(f"■ {ic['id']}（{ic.get('name')}）bbox x{bx0:.0f}〜{bx1:.0f} y{by0:.0f}〜{by1:.0f} 被覆{cov:.1f}%  "
              + ("警告: " + "・".join(warn) if warn else "OK"))
        print("\n".join(art))
    print(f"\n一覧画像: {shot}")
    print(f"{'ICONBATCH_OK' if bad == 0 else 'ICONBATCH_WARN'} {len(icons)}個・警告{bad}個")


if __name__ == "__main__":
    main()
