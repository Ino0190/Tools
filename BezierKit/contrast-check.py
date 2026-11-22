# WCAGコントラスト比の検査（UI・アイコンの配色決めの機械チェック・依存なし）
#   python3 contrast-check.py '#121212' '#fafafa'          … 前景/背景の1ペアを判定
#   python3 contrast-check.py --matrix '#121212' '#21537f' '#eef3f8' …  … 全組み合わせの総当たり表
#   python3 contrast-check.py --file DesignKit/design-kit.css           … ファイル内のhex色を抽出して総当たり
# 判定基準（WCAG 2.x）:
#   通常文字 AA=4.5 AAA=7 ／ 大きい文字(24px+ or 19px太字+) AA=3 ／ UI部品・図形の境界 3
import argparse, re, sys

def parse_hex(s):
    m = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", s.strip())
    if not m: return None
    h = m.group(1)
    if len(h) == 3: h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # alphaは無視（合成後の色で測る前提）

def luminance(rgb):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(c1, c2):
    l1, l2 = sorted((luminance(c1), luminance(c2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)

def grade(r):
    if r >= 7:   return "AAA"
    if r >= 4.5: return "AA"
    if r >= 3:   return "大文字/UIのみ"
    return "不可"

def fmt(rgb): return "#{:02x}{:02x}{:02x}".format(*rgb)

ap = argparse.ArgumentParser()
ap.add_argument("colors", nargs="*", help="hex色（2個=ペア判定、--matrixで総当たり）")
ap.add_argument("--matrix", action="store_true", help="全組み合わせを表にする")
ap.add_argument("--file", default="", help="CSS/HTML等からhex色を抽出して総当たり")
args = ap.parse_args()

colors = []
if args.file:
    text = open(args.file, encoding="utf-8", errors="replace").read()
    seen = {}
    for h in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", text):
        rgb = parse_hex(h)
        if rgb and rgb not in seen: seen[rgb] = True
    colors = list(seen)
    print(f"{args.file}: {len(colors)}色を抽出")
else:
    for s in args.colors:
        rgb = parse_hex(s)
        if not rgb:
            print(f"NG hex色として読めない: {s}"); sys.exit(1)
        colors.append(rgb)

if not args.file and not args.matrix and len(colors) == 2:
    # 1ペア判定
    r = ratio(colors[0], colors[1])
    print(f"{fmt(colors[0])} × {fmt(colors[1])}  コントラスト比 {r:.2f}:1")
    print(f"  通常文字(〜23px):        AA(4.5) {'OK' if r >= 4.5 else 'NG'} / AAA(7) {'OK' if r >= 7 else 'NG'}")
    print(f"  大きい文字(24px+/19px太): AA(3)   {'OK' if r >= 3 else 'NG'}")
    print(f"  UI部品・アイコン・図形:    3:1    {'OK' if r >= 3 else 'NG'}")
    sys.exit(0 if r >= 3 else 1)

if len(colors) < 2:
    print("NG 色を2つ以上指定する（--file か --matrix か ペア指定）"); sys.exit(1)
if len(colors) > 24:
    print(f"NG 色が多すぎる（{len(colors)}色）。--matrixは24色まで"); sys.exit(1)

# 総当たり表（比が3以上のセルにだけ等級を出す＝使えるペアが一目で分かる）
names = [fmt(c) for c in colors]
wid = 9
print(" " * wid + "".join(n.rjust(wid) for n in names))
ok_pairs = []
for i, ci in enumerate(colors):
    row = names[i].ljust(wid)
    for j, cj in enumerate(colors):
        if i == j:
            row += "-".rjust(wid); continue
        r = ratio(ci, cj)
        row += (f"{r:.1f}" if r >= 3 else "·").rjust(wid)
        if i < j and r >= 4.5: ok_pairs.append((r, names[i], names[j]))
    print(row)
print("\n本文に使えるペア（AA 4.5以上・比の高い順）:")
for r, a, b in sorted(ok_pairs, reverse=True):
    print(f"  {a} × {b}  {r:.2f}:1  {grade(r)}")
if not ok_pairs:
    print("  なし（この色セットに本文用の組み合わせが無い）")
