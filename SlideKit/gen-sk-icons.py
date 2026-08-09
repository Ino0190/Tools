# sk-icons.js を BezierKit/icons-data.js（正本）から生成する
#   python3 SlideKit/gen-sk-icons.py
# SlideKitのUI絵文字→カタログアイコンの対応表もここが正本。カタログを変えたら再実行。
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(os.path.dirname(HERE), "BezierKit", "icons-data.js")

# 絵文字 → カタログid（SlideKit UIで置き換える分だけ）
EMOJI_MAP = {
    "💾": "save", "📋": "copy", "✏️": "pen", "🗑": "trash", "📄": "doc",
    "📂": "open", "🎨": "palette", "🖌": "brush", "📐": "format", "🅰️": "font",
    "📝": "sticky", "▶": "play", "🖼": "image", "📊": "table", "⚠️": "warn",
    "✂️": "scissor", "🔗": "link", "📍": "pin", "🎯": "target", "🧩": "puzzle",
    "📖": "book", "☁️": "cloud", "🔄": "refresh", "📺": "screen", "🌫": "shadow",
    "✍️": "pen", "💧": "drop", "🔒": "lock", "👁": "eye", "✅": "check",
}

# UI記号 → カタログid（ボタンラベルの先頭記号だけ置換。本文に出る→や─を誤爆しないため）
UI_MAP = {
    "□": "square", "▢": "rrect", "●": "circle", "▲": "triangle",
    "─": "bz-line", "→": "arrow-right", "▷": "chevron",
}

text = open(CATALOG).read()
# エントリをJSっぽく雑にパースせず、ブラウザ不要の簡易評価: {num:..} 行を正規表現で
entries = {}
for m in re.finditer(r"\{num:(\d+), id:'([^']+)', name:'([^']*)', tags:\[[^\]]*\], paths:\[(.*?)\]\}", text, re.S):
    num, iid, name, body = m.groups()
    paths = []
    for pm in re.finditer(r"\{d:(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")([^}]*)\}", body):
        d = pm.group(1) or pm.group(2)
        d = d.replace("\\'", "'").replace('\\\\', '\\')
        rest = pm.group(3)
        p = {"d": d}
        if "fill:'currentColor'" in rest: p["fill"] = 1
        if "stroke:'currentColor'" in rest: p["stroke"] = 1
        wm = re.search(r"width:([\d.]+)", rest)
        if wm: p["w"] = float(wm.group(1))
        om = re.search(r"opacity:(\.?[\d.]+)", rest)
        if om: p["o"] = float(om.group(1))
        paths.append(p)
    entries[iid] = {"name": name, "paths": paths}

need = sorted(set(EMOJI_MAP.values()) | set(UI_MAP.values()))
missing = [i for i in need if i not in entries]
assert not missing, f"カタログに無いid: {missing}"

icons_js = {}
for iid in need:
    parts = []
    for p in entries[iid]["paths"]:
        fill = "currentColor" if p.get("fill") else "none"
        stroke = "currentColor" if (p.get("stroke") or not p.get("fill")) else "none"
        sw = p.get("w", 8)
        attrs = f'd="{p["d"]}" fill="{fill}" stroke="{stroke}"'
        if stroke != "none":
            attrs += f' stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
        if p.get("o"): attrs += f' opacity="{p["o"]}"'
        parts.append(f"<path {attrs}/>")
    icons_js[iid] = "".join(parts)

out = ["// sk-icons.js — SlideKit UIの絵文字をSVGアイコンに置き換える（生成物・直接編集しない）",
       "// 正本: BezierKit/icons-data.js ＋ SlideKit/gen-sk-icons.py のEMOJI_MAP。更新は gen-sk-icons.py を再実行",
       "(function(){",
       "var SK_ICONS=" + json.dumps(icons_js, ensure_ascii=False) + ";",
       "var SK_EMOJI=" + json.dumps(EMOJI_MAP, ensure_ascii=False) + ";",
"var SK_UI=" + json.dumps(UI_MAP, ensure_ascii=False) + ";",
       """function svgFor(id,cls){var b=SK_ICONS[id];if(!b)return null;
 var s=document.createElementNS('http://www.w3.org/2000/svg','svg');
 s.setAttribute('viewBox','0 0 96 96');s.setAttribute('class',cls||'sk-ic');s.setAttribute('aria-hidden','true');
 s.innerHTML=b;return s;}
// テキストノード内の対応絵文字をSVGに置き換える（root以下・scriptとstyleは除外）
function replaceEmoji(root){
 var keys=Object.keys(SK_EMOJI).sort(function(a,b){return b.length-a.length;});
 var re=new RegExp('('+keys.map(function(k){return k.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');}).join('|')+')\\ufe0f?','g');
 var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,null);
 var targets=[];
 while(walker.nextNode()){var n=walker.currentNode;
  var tag=n.parentNode&&n.parentNode.tagName;
  if(tag==='SCRIPT'||tag==='STYLE'||tag==='TEXTAREA')continue;
  if(re.test(n.nodeValue)){targets.push(n);}re.lastIndex=0;}
 targets.forEach(function(n){
  var frag=document.createDocumentFragment(),last=0,m;
  while((m=re.exec(n.nodeValue))){
   if(m.index>last)frag.appendChild(document.createTextNode(n.nodeValue.slice(last,m.index)));
   var id=SK_EMOJI[m[1]]||SK_EMOJI[m[1].replace('\\ufe0f','')];
   var sv=svgFor(id);
   frag.appendChild(sv||document.createTextNode(m[0]));
   last=m.index+m[0].length;
  }
  re.lastIndex=0;
  if(last<n.nodeValue.length)frag.appendChild(document.createTextNode(n.nodeValue.slice(last)));
  n.parentNode.replaceChild(frag,n);
 });
}
// UI要素向け: 絵文字置換＋「ボタンラベル先頭のUI記号」（□▢●▲─→▷）をSVG化
function replaceUI(root){
 replaceEmoji(root);
 var btns=root.querySelectorAll?root.querySelectorAll('button'):[];
 for(var i=0;i<btns.length;i++){
  var b=btns[i],n=b.firstChild;
  if(!n||n.nodeType!==3)continue;
  var m=n.nodeValue.match(/^\\s*([□▢●▲─→▷])\\s*/);
  if(!m||!SK_UI[m[1]])continue;
  var sv=svgFor(SK_UI[m[1]]);
  if(!sv)continue;
  n.nodeValue=n.nodeValue.slice(m[0].length);
  b.insertBefore(document.createTextNode(' '),n);
  b.insertBefore(sv,b.firstChild);
 }
}
window.SKIcons={svg:svgFor,replaceEmoji:replaceEmoji,replaceUI:replaceUI,map:SK_EMOJI,uiMap:SK_UI};
})();""" ]
target = os.path.join(HERE, "sk-icons.js")
open(target, "w").write("\n".join(out) + "\n")
print(f"生成: sk-icons.js（{len(icons_js)}アイコン・{len(EMOJI_MAP)}絵文字対応）")
