#!/usr/bin/env python3
"""地図データを作る（SlideKit の data-chart type:"map" 用・2026-10-14 利用者「地図の上に棒グラフとか人口を示す円」）。

    python3 SlideKit/map_build.py <ne_10m_admin_1_states_provinces.zip>  → SlideKit/maps/japan-pref.json（全国用・粗い）
                                                                          ＋ japan-pref-detail.json（寄せた地図用・細かい）

元データ: Natural Earth 1:10m Admin 1 – States, Provinces（著作権なし・public domain）
    https://www.naturalearthdata.com/  （ダウンロードは naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip）
外部ライブラリなし（shapefile と dbf を自分で読む）。日本の47都道府県を取り出し、
  ・投影: 正距円筒（中心緯度36°で横を cos で縮める）
  ・沖縄県は左上の枠に移す（日本地図のふつうの置き方）。遠い島（東京都の小笠原・南鳥島、沖縄県の大東諸島・尖閣諸島）は
    スライドの地図を小さくしないために外す（地図の上の値は県全体のまま）
  ・形をスライド向けに粗くする（Douglas-Peucker）。小さな島は、その県のいちばん大きな島を残して外す
"""
import io
import json
import math
import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'maps', 'japan-pref.json')
W = 1000                      # 地図の幅（座標の単位）
LAT0 = 36.0                   # 投影の中心緯度
OKI_SHIFT = (6.3, 14.6)       # 沖縄県を動かす量（経度・緯度）＝日本海の左上の枠へ
TOL = 0.9                     # 粗くする度合い（地図の座標で）。小さいほど細かい
MIN_AREA = 6.0                # これより小さい島は外す（地図の座標で・面積）

# Natural Earth の県名（英語）→ 都道府県コード・名前
PREFS = ['北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県', '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県',
         '東京都', '神奈川県', '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県', '静岡県', '愛知県', '三重県',
         '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県', '鳥取県', '島根県', '岡山県', '広島県', '山口県', '徳島県',
         '香川県', '愛媛県', '高知県', '福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県']


def read_dbf(b):
    n, hlen, rlen = struct.unpack('<xxxxIHH', b[:12])
    fields, off = [], 32
    while b[off] != 0x0D:
        name = b[off:off + 11].split(b'\0')[0].decode('latin1')
        flen = b[off + 16]
        fields.append((name, flen))
        off += 32
    rows = []
    for i in range(n):
        r = b[hlen + i * rlen: hlen + (i + 1) * rlen]
        p, row = 1, {}
        for name, flen in fields:
            row[name] = r[p:p + flen].decode('utf-8', 'replace').strip(' \x00\ufffd')
            p += flen
        rows.append(row)
    return rows


def read_shp(b):
    """多角形（type 5）だけ。レコードごとに [輪（[(lon,lat)...])...]"""
    out, off = [], 100
    while off < len(b):
        _, clen = struct.unpack('>ii', b[off:off + 8])
        rec = b[off + 8: off + 8 + clen * 2]
        off += 8 + clen * 2
        st = struct.unpack('<i', rec[:4])[0]
        if st != 5:
            out.append([])
            continue
        nparts, npts = struct.unpack('<ii', rec[36:44])
        parts = list(struct.unpack('<%di' % nparts, rec[44:44 + 4 * nparts])) + [npts]
        pts = struct.unpack('<%dd' % (2 * npts), rec[44 + 4 * nparts: 44 + 4 * nparts + 16 * npts])
        rings = []
        for k in range(nparts):
            rings.append([(pts[2 * i], pts[2 * i + 1]) for i in range(parts[k], parts[k + 1])])
        out.append(rings)
    return out


def area(r):
    return 0.5 * sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(-1, len(r) - 1))


def dp(pts, tol):
    """Douglas-Peucker（閉じた輪は2つに分けて掛ける）"""
    if len(pts) < 4:
        return pts
    def rec(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1, -1
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            return rec(a, bi)[:-1] + rec(bi, b)
        return [pts[a], pts[b]]
    mid = len(pts) // 2
    return rec(0, mid)[:-1] + rec(mid, len(pts) - 1)


def main(zpath, name_out='japan-pref'):
    z = zipfile.ZipFile(zpath)
    base = next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
    rows = read_dbf(z.read(base + '.dbf'))
    shapes = read_shp(z.read(base + '.shp'))
    jp = [(r, s) for r, s in zip(rows, shapes) if r.get('adm0_a3') == 'JPN']
    print('日本の行', len(jp), '列の例', [k for k in rows[0].keys()][:12])
    k = math.cos(math.radians(LAT0))
    raw = []
    for r, rings in jp:
        code = r.get('iso_3166_2', '')            # JP-13
        try:
            no = int(code.split('-')[1])
        except (IndexError, ValueError):
            print('  ? コード不明', r.get('name'), code)
            continue
        oki = no == 47
        keep = []
        for ring in rings:
            if no == 13 and min(p[1] for p in ring) < 32:
                continue                                 # 小笠原・南鳥島など
            if oki and (min(p[0] for p in ring) > 130.5 or (max(p[0] for p in ring) < 124.6 and min(p[1] for p in ring) > 25.4)):
                continue                                 # 大東諸島・尖閣諸島（枠が大きくなり本島が小さくなるため）
            if oki:
                ring = [(x + OKI_SHIFT[0], y + OKI_SHIFT[1]) for x, y in ring]
            keep.append([(x * k, -y) for x, y in ring])
        raw.append((no, keep, r))
    xs = [p[0] for _, rs, _ in raw for ring in rs for p in ring]
    ys = [p[1] for _, rs, _ in raw for ring in rs for p in ring]
    x0, y0 = min(xs), min(ys)
    s = W / (max(xs) - x0)
    H = round((max(ys) - y0) * s)
    prefs, npts = [], 0
    for no, rs, r in sorted(raw):
        rings = [[((x - x0) * s, (y - y0) * s) for x, y in ring] for ring in rs]
        rings.sort(key=lambda g: -abs(area(g)))
        rings = [g for i, g in enumerate(rings) if i == 0 or abs(area(g)) >= MIN_AREA]
        d, big = '', rings[0]
        for g in rings:
            g2 = dp(g, TOL)
            if len(g2) < 3:
                continue
            npts += len(g2)
            d += 'M' + ' L'.join('%.1f,%.1f' % p for p in g2) + 'Z'
        # 名前・印を置く点＝いちばん大きな島の重心
        a = area(big) or 1e-9
        cx = sum((big[i][0] + big[i + 1][0]) * (big[i][0] * big[i + 1][1] - big[i + 1][0] * big[i][1]) for i in range(-1, len(big) - 1)) / (6 * a)
        cy = sum((big[i][1] + big[i + 1][1]) * (big[i][0] * big[i + 1][1] - big[i + 1][0] * big[i][1]) for i in range(-1, len(big) - 1)) / (6 * a)
        name = PREFS[no - 1]
        prefs.append({'code': '%02d' % no, 'name': name, 'short': name if name == '北海道' else name[:-1],
                      'cx': round(cx, 1), 'cy': round(cy, 1), 'd': d})
    # 沖縄の枠（移したことが分かる線）
    ok = next(p for p in raw if p[0] == 47)[1]
    oxs = [(x - x0) * s for ring in ok for x, _ in ring]
    oys = [(y - y0) * s for ring in ok for _, y in ring]
    pad = 10
    frame = [round(min(oxs) - pad, 1), round(min(oys) - pad, 1), round(max(oxs) - min(oxs) + 2 * pad, 1), round(max(oys) - min(oys) + 2 * pad, 1)]
    # 緯度経度 → 地図の座標（店の位置を置くため・2026-10-15 商圏）。
    #   x = (lon×k − x0)×s、y = (−lat − y0)×s。沖縄（緯度 oki[2] 未満・経度 oki[3] 未満）は先に oki[0..1] だけ動かす
    #   1km = s / 111.32（縦）。横は k / cos(緯度) 倍になる（正距円筒の横の伸び）
    proj = {'k': round(k, 8), 'x0': round(x0, 6), 'y0': round(y0, 6), 's': round(s, 6),
            'oki': [OKI_SHIFT[0], OKI_SHIFT[1], 27.0, 131.5]}
    data = {'name': name_out, 'source': 'Natural Earth 1:10m Admin 1（public domain）を SlideKit/map_build.py で粗くした',
            'w': W, 'h': H, 'proj': proj, 'frames': [frame], 'regions': prefs}
    out = os.path.join(HERE, 'maps', name_out + '.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    # ブラウザ用（file:// でも読めるように script で読む形）。slidekit-chart.js が地図のあるデッキだけ読む
    with open(out[:-5] + '.js', 'w', encoding='utf-8') as f:
        f.write('/* 生成物（SlideKit/map_build.py）。直接編集しない。元データ: Natural Earth（public domain） */\n'
                '(window.SLIDEKIT_MAPS = window.SLIDEKIT_MAPS || {})["' + name_out + '"] = ')
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\nif (window.SlideKitChart) window.SlideKitChart.renderAll();\n')
    print(f'{len(prefs)}都道府県・点 {npts}・{os.path.getsize(out) // 1024}KB・{W}x{H} → {out}')


if __name__ == '__main__':
    main(sys.argv[1])
    # 寄せた地図（商圏など・県の一部を大きく見せる）用に、細かい版も作る。全国の地図には粗い版を使う
    TOL, MIN_AREA = 0.15, 0.3
    main(sys.argv[1], 'japan-pref-detail')
