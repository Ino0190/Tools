#!/usr/bin/env python3
"""DashboardKitのダッシュボードにあるグラフを、SlideKitのスライド1枚にする。

    python3 SlideKit/dk_chart_to_slide.py <dashboard.html のURL> --index 2 \\
        -o out.html --title "月ごとの搬送量" --note "2026年1〜6月の実績"
    （--list でグラフの一覧だけ出す）

前提: ローカルサーバー起点はワークスペースルート。
    cd （ワークスペースルート） && python3 -m http.server 8000
    → URL は http://localhost:8000/DashboardKit/gym-demo.html

決定: CalcKit の buildChartSlideHtml と同じ方針を採る。
  ・テーマのCSS変数はスライド単体で解決できないので computed style を属性へ焼き込む
  ・DashboardKitの凡例はHTML側にあるのでSVGに入らない。**凡例とタイトルは .tb で置き直す**
    （PPTXで編集できる文字として残す）
  ・軸の目盛りはSVG内の <text> のまま。数値が変わったらグラフを作り直す前提
  根拠=.kiro/steering/projects/kiro-operations.md
"""
import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("cdpkit", os.path.join(ROOT, "BezierKit", "cdp-check.py"))
cdpkit = importlib.util.module_from_spec(_spec)
sys.modules["cdpkit"] = cdpkit
_spec.loader.exec_module(cdpkit)

# グラフのSVGを取り出し、CSS変数を解決して属性へ焼き込むJS（ブラウザ内で実行する）
EXTRACT_JS = r"""
(function(idx){
 var svgs=document.querySelectorAll('svg.dk-chart-svg');
 if(!svgs.length)return {err:'グラフ（svg.dk-chart-svg）が見つからない'};
 if(idx>=svgs.length)return {err:'index が範囲外（0〜'+(svgs.length-1)+'）'};
 var src=svgs[idx],svg=src.cloneNode(true);
 // computed style を属性へ焼き込む（var(--dk-*) はスライド単体で解決できない）
 var props=['fill','stroke','stroke-width','stroke-dasharray','font-family','font-size',
            'font-weight','opacity','fill-opacity','stroke-opacity','text-anchor'];
 var from=[src].concat([].slice.call(src.querySelectorAll('*')));
 var to=[svg].concat([].slice.call(svg.querySelectorAll('*')));
 for(var i=0;i<from.length;i++){
  var cs=getComputedStyle(from[i]);
  for(var p=0;p<props.length;p++){
   var v=cs.getPropertyValue(props[p]);
   if(v&&v!==''&&v!=='normal'&&v!=='auto'&&v!=='none')to[i].setAttribute(props[p],v);
  }
  to[i].removeAttribute('style');            // style内のvar()が残ると効かない
  to[i].removeAttribute('class');            // dk-* classはSlideKitの許可外（SVG内なので検査対象外だが落とす）
 }
 // 凡例はHTML側にあるので、同じカードの中から系列名と色を拾う
 var card=src.closest('.dk-card')||src.parentElement,legend=[];
 if(card)[].slice.call(card.querySelectorAll('[class*=legend] *,[class*=Legend] *')).forEach(function(el){
  var t=(el.textContent||'').trim();
  if(!t||t.length>24||el.children.length)return;
  var c=getComputedStyle(el).color,bg=getComputedStyle(el).backgroundColor;
  legend.push({name:t,color:(bg&&bg!=='rgba(0, 0, 0, 0)')?bg:c});
 });
 var title='';
 if(card){var h=card.querySelector('h1,h2,h3,h4,[class*=title]');if(h)title=(h.textContent||'').trim();}
 var vb=(svg.getAttribute('viewBox')||'').trim().split(/\s+/).map(Number);
 svg.removeAttribute('width');svg.removeAttribute('height');
 return {svg:new XMLSerializer().serializeToString(svg),
   vw:vb[2]||800,vh:vb[3]||400,title:title,legend:legend.slice(0,8),
   texts:svg.querySelectorAll('text').length,count:svgs.length};
})(%IDX%)
"""

LIST_JS = r"""
(function(){
 var out=[];
 document.querySelectorAll('svg.dk-chart-svg').forEach(function(s,i){
  var card=s.closest('.dk-card'),h=card&&card.querySelector('h1,h2,h3,h4,[class*=title]');
  var vb=(s.getAttribute('viewBox')||'').split(/\s+/);
  out.push({i:i,title:h?(h.textContent||'').trim().slice(0,40):'',
   size:(vb[2]||'?')+'×'+(vb[3]||'?'),texts:s.querySelectorAll('text').length});
 });
 return out;
})()
"""


SLIDE = """<!DOCTYPE html>
<html lang="ja" data-palette="custom">
<head><meta charset="utf-8"><title>{title}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Meiryo UI','Yu Gothic','Noto Sans JP',sans-serif;background:#3a4756;display:flex;
flex-direction:column;align-items:center;padding:20px 0 60px;font-weight:400}}
.slide{{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px 0;box-shadow:0 4px 24px rgba(0,0,0,.2)}}
.tb{{position:absolute;overflow:hidden;line-height:1.5}}
.rect{{position:absolute;display:flex;flex-direction:column;justify-content:center;align-items:center}}
</style></head>
<body>
<!-- SLIDE: {title} [D09] -->
<div class="slide" data-bg="#fafafa" style="background:#fafafa">
{body}</div>
<!-- /SLIDE -->
<script src="../SlideKit/slide-edit.js"><\\/script>
</body>
</html>
"""


def tb(x, y, w, h, fs, text, color="#121212", bold=0):
    st = (f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;font-size:{fs}px;"
          f"{'font-weight:700;' if bold else ''}color:{color}")
    return (f'  <div class="tb" data-x="{x}" data-y="{y}" data-w="{w}" data-h="{h}" '
            f'data-font-size="{fs}" {"data-bold=\"1\" " if bold else ""}data-color="{color}" '
            f'style="{st}">{text}</div>\n')


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slide(data, title, note):
    """グラフSVGをスライド1枚にする。タイトルと凡例は .tb（PPTXで編集できる文字）"""
    vw, vh = data["vw"], data["vh"]
    FW, FH = 1152, 420
    sc = min(FW / vw, FH / vh)
    w, h = round(vw * sc), round(vh * sc)
    x, y = 64 + (FW - w) // 2, 200
    svg = data["svg"].replace("<svg ", '<svg width="100%" height="100%" ', 1)
    s = tb(64, 48, 1152, 44, 28, esc(title or data["title"] or "グラフ"), "#183251", 1)
    if note:
        s += tb(64, 100, 1152, 30, 19, esc(note), "#21537f")
    # 凡例は .tb で置き直す（DashboardKitの凡例はHTML側なのでSVGに入らない）
    lx = 64
    for item in data["legend"]:
        wpx = min(300, len(item["name"]) * 17 + 40)
        s += tb(lx, 150, wpx, 26, 16, "● " + esc(item["name"]), item["color"], 1)
        lx += wpx + 10
    s += (f'  <div data-x="{x}" data-y="{y}" data-w="{w}" data-h="{h}" '
          f'style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px">{svg}</div>\n')
    s += tb(64, 660, 1152, 24, 15, "※ グラフはDashboardKitの実データ。軸の目盛りは画像側・タイトルと凡例は文字として編集できる", "#718096")
    return SLIDE.format(title=esc(title or data["title"] or "グラフ"), body=s), (w, h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="ダッシュボードHTMLのURL（http://localhost:8000/... 形式）")
    ap.add_argument("--index", type=int, default=0, help="何番目のグラフか（--list で確認）")
    ap.add_argument("--list", action="store_true", help="グラフの一覧だけ出す")
    ap.add_argument("-o", "--out")
    ap.add_argument("--title")
    ap.add_argument("--note")
    ap.add_argument("--port", type=int, default=9342)
    ap.add_argument("--wait", type=float, default=4.0, help="描画待ち秒数")
    a = ap.parse_args()
    if not a.url.startswith("http"):
        print("🔴 file:// では相対パスのJSが読めない。ワークスペースルートで http.server を立てて "
              "http://localhost:8000/... を渡す")
        return 1
    prof = f"/tmp/dkslide-{a.port}"
    subprocess.run(["pkill", "-f", os.path.basename(prof)], capture_output=True)
    time.sleep(0.3)
    subprocess.run(["rm", "-rf", prof])
    cdpkit.PORT = a.port
    ch = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={a.port}",
                           f"--user-data-dir={prof}", "--no-first-run",
                           "--window-size=1600,1000", a.url],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect()
        cdpkit.call(sock, "Runtime.enable")
        time.sleep(a.wait)
        if a.list:
            for g in cdpkit.ev(sock, LIST_JS) or []:
                print(f"  [{g['i']}] {g['size']:>10}  text{g['texts']:>3}  {g['title']}")
            return 0
        data = cdpkit.ev(sock, EXTRACT_JS.replace("%IDX%", str(a.index)))
        if not data or data.get("err"):
            print(f"🔴 {(data or {}).get('err', '取得に失敗')}")
            return 1
        html, (w, h) = build_slide(data, a.title, a.note)
        out = os.path.abspath(a.out or "dk-chart-slide.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"スライドを作った: {out}")
        print(f"  グラフ {data['vw']}×{data['vh']} → 枠 {w}×{h}／SVG内の目盛り {data['texts']}個／"
              f"凡例 {len(data['legend'])}件を文字で再配置")
        print(f"  検査: python3 SlideKit/slidecheck.py {os.path.relpath(out, ROOT)}")
        return 0
    finally:
        ch.terminate()


if __name__ == "__main__":
    sys.exit(main())
