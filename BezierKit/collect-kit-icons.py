# 一時スクリプト: CadKit/BezierKitのツールバーSVGアイコンを96×96に変換してicons-data.jsへ追記
import re, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ARGC = {'M':2,'L':2,'T':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'A':7,'Z':0}
# 各コマンドの引数の軸種別: x=X座標, y=Y座標, r=長さ(スケールのみ), f=そのまま
AXES = {'M':'xy','L':'xy','T':'xy','H':'x','V':'y','C':'xyxyxy','S':'xyxy','Q':'xyxy','A':'rrfffxy','Z':''}

def fmt(v):
    r = round(v, 1)
    return str(int(r)) if r == int(r) else str(r)

def transform_d(d, k, tx=0, ty=0):
    tokens = re.findall(r'[A-Za-z]|-?\.?\d+(?:\.\d+)?(?:e-?\d+)?', d)
    out, i, cmd = [], 0, None
    while i < len(tokens):
        t = tokens[i]
        if re.match(r'[A-Za-z]', t):
            cmd = t; out.append(t); i += 1
            continue
        C = cmd.upper()
        rel = cmd.islower()
        n = ARGC[C]
        vals = tokens[i:i+n]; i += n
        for j, v in enumerate(vals):
            f = float(v)
            ax = AXES[C][j]
            if ax == 'f': out.append(fmt(f))
            elif ax == 'r': out.append(fmt(f*k))
            elif ax == 'x': out.append(fmt(f*k + (0 if rel else tx)))
            else: out.append(fmt(f*k + (0 if rel else ty)))
    return ' '.join(out)

def prim_to_path(tag, attrs, k, tx=0, ty=0):
    a = dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', attrs))
    if tag == 'path':
        return transform_d(a['d'], k, tx, ty), a
    if tag in ('circle', 'ellipse'):
        cx, cy = float(a['cx'])*k+tx, float(a['cy'])*k+ty
        rx = float(a.get('r', a.get('rx', 0)))*k
        ry = float(a.get('r', a.get('ry', 0)))*k
        d = f"M{fmt(cx-rx)} {fmt(cy)}a{fmt(rx)} {fmt(ry)} 0 1 0 {fmt(2*rx)} 0a{fmt(rx)} {fmt(ry)} 0 1 0 {fmt(-2*rx)} 0"
        return d, a
    if tag == 'rect':
        x, y = float(a['x'])*k+tx, float(a['y'])*k+ty
        w, h = float(a['width'])*k, float(a['height'])*k
        d = f"M{fmt(x)} {fmt(y)}H{fmt(x+w)}V{fmt(y+h)}H{fmt(x)}Z"
        return d, a
    return None, a

def parse_svg_inner(inner, root_attrs, k, tx=0, ty=0):
    root = dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', root_attrs))
    root_filled = root.get('fill', 'none') not in ('none', '')
    root_stroked = root.get('stroke', 'none') not in ('none', '')
    paths = []
    for m in re.finditer(r'<(path|circle|ellipse|rect)([^/>]*)/?>', inner):
        d, a = prim_to_path(m.group(1), m.group(2), k, tx, ty)
        if not d: continue
        fill = a.get('fill', 'currentColor' if root_filled else 'none')
        entry = {'d': d}
        if fill not in ('none', ''):
            entry['fill'] = 'currentColor'
            if root_stroked and a.get('stroke', 'inherit') != 'none':
                entry['stroke'] = 'currentColor'   # 塗り＋線の両方（例: CadKit面選択の淡い面）
        if a.get('opacity'):
            entry['opacity'] = a['opacity']
        paths.append(entry)
    return paths

def collect(file, kit_prefix, kit_tag):
    src = open(file).read()
    out = []
    # data-tool / id 付きボタン内のviewBox 0 0 20 20 svg
    for m in re.finditer(
        r'<button[^>]*?(?:data-tool="([^"]+)"|id="([^"]+)")[^>]*title="([^"]*)"[^>]*>\s*<svg viewBox="0 0 20 20"([^>]*)>(.*?)</svg>',
        src, re.S):
        tool, bid, title, root_attrs, inner = m.groups()
        key = tool or re.sub(r'^v', '', bid or '')
        key = re.sub(r'([A-Z])', lambda g: '-'+g.group(1).lower(), key).strip('-')
        name = re.sub(r'\s*[\(（].*$', '', title.split('・')[0].split(':')[-1].split('（')[0]).strip()
        tags = [kit_tag, 'ツール']
        out.append({'id': f'{kit_prefix}-{key}', 'name': name, 'tags': tags,
                    'paths': parse_svg_inner(inner, root_attrs, 4.8)})
    return out

def collect_tico(file, kit_prefix, kit_tag):
    src = open(file).read()
    out, seen = [], set()
    # <button id="toolXxx"><svg class="tico" ...>inner</svg>ラベル</button>
    for m in re.finditer(
        r'<button[^>]*id="([^"]+)"[^>]*>\s*<svg class="tico"([^>]*)>(.*?)</svg>\s*([^<]*)</button>',
        src, re.S):
        bid, root_attrs, inner, label = m.groups()
        key = re.sub(r'^tool', '', bid)
        key = re.sub(r'([A-Z])', lambda g: '-'+g.group(1).lower(), key).strip('-')
        name = label.strip() or key
        if key in seen: continue
        seen.add(key)
        out.append({'id': f'{kit_prefix}-{key}', 'name': name, 'tags': [kit_tag, 'スケッチ'],
                    'paths': parse_svg_inner(inner, root_attrs, 4.8)})
    return out

def collect_h3(file, kit_prefix, kit_tag):
    src = open(file).read()
    out, n = [], 0
    en = {'押し出し':'extrude','回転体':'revolve','ロフト':'loft','スイープ':'sweep','ミラー':'mirror',
          '分割':'split','面プル':'facepull','面の押し引き':'facepull','フィレット':'fillet',
          '面取り':'chamfer','シェル':'shell','パターン':'pattern','ボディのブーリアン':'boolean'}
    for m in re.finditer(r'<h3>\s*<svg class="tico"([^>]*)>(.*?)</svg>(.*?)</h3>', src, re.S):
        root_attrs, inner, label = m.groups()
        label = re.sub(r'<[^>]*>', ' ', label)  # <span>などを除去してテキストだけ
        name = re.sub(r'[（(].*$', '', label.strip().split()[0] if label.strip() else '')
        key = en.get(name) or f'f{n}'
        n += 1
        out.append({'id': f'{kit_prefix}-{key}', 'name': name, 'tags': [kit_tag, 'フィーチャー'],
                    'paths': parse_svg_inner(inner, root_attrs, 4.8)})
    return out

# 手描きアイコンと重複するものは収録しない（正本は手描き側）
EXCLUDE = {
    'bz-pen',  # 手描き'pen'と重複（2026-07-29 利用者判断）
    # CadKit拘束ボタンのticoは手描き con-h〜con-coin（#97-102）の20×20版なので二重収録しない
    'cad-sk-con-h', 'cad-sk-con-v', 'cad-sk-con-para',
    'cad-sk-con-perp', 'cad-sk-con-eq', 'cad-sk-con-coin',
}

icons = []
icons += collect(os.path.join(HERE, 'index.html'), 'bz', 'BezierKit')
icons += collect(os.path.join(ROOT, 'CadKit', 'index.html'), 'cad', 'CadKit')
icons += collect_tico(os.path.join(ROOT, 'CadKit', 'index.html'), 'cad-sk', 'CadKit')
icons += collect_h3(os.path.join(ROOT, 'CadKit', 'index.html'), 'cad-ft', 'CadKit')

# キット共通マーク（丸に井桁）: viewBox 414 291 285 285 → 96×96
mark_src = open(os.path.join(HERE, 'index.html')).read()
mm = re.search(r'<svg class="kit-mark" viewBox="414 291 285 285"[^>]*>(.*?)</svg>', mark_src, re.S)
k = 96/285.0
mark_paths = parse_svg_inner(mm.group(1), 'fill="currentColor"', k, -414*k, -291*k)
icons.append({'id': 'kit-mark', 'name': '丸に井桁', 'tags': ['キット共通', 'ロゴ'], 'paths': mark_paths})

# JSフラグメント生成
def js_entry(ic):
    ps = ',\n  '.join(
        '{d:' + json.dumps(p['d'], ensure_ascii=False)
        + (", fill:'currentColor'" if p.get('fill') else '')
        + (", stroke:'currentColor'" if p.get('stroke') else '')
        + (f", opacity:{p['opacity']}" if p.get('opacity') else '') + '}'
        for p in ic['paths'])
    tags = ','.join("'"+t+"'" for t in ic['tags'])
    return (f" {{num:{ic['num']}, id:'{ic['id']}', name:'{ic['name']}', tags:[{tags}], paths:[\n  {ps}]}},")

MARK = ' // ---- 各キットのUIで使っているアイコン（_collect_iconsで20×20→96×96変換） ----'
target = os.path.join(HERE, 'icons-data.js')
text = open(target).read()
# 既存の num を保持し、新規idには最大+1から振る（numは通し番号・欠番あり・再利用しない）
num_map = {m.group(2): int(m.group(1)) for m in re.finditer(r"\{num:(\d+), id:'([^']+)'", text)}
next_num = max(num_map.values(), default=0) + 1
icons = [ic for ic in icons if ic['id'] not in EXCLUDE]
for ic in icons:
    if ic['id'] in num_map:
        ic['num'] = num_map[ic['id']]
    else:
        ic['num'] = next_num; next_num += 1
frag = '\n'.join(js_entry(ic) for ic in icons)
if MARK in text:  # 再実行時は前回の生成分を差し替え
    text = text[:text.index(MARK)].rstrip() + '\n];\n'
assert text.rstrip().endswith('];')
text = text.rstrip()[:-2].rstrip() + '\n\n' + MARK + '\n' + frag + '\n];\n'
open(target, 'w').write(text)
print(f"収録 {len(icons)}個:", ', '.join(ic['id'] for ic in icons))
