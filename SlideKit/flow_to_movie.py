#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コマ送りの線画SVG（CadKit cdp-run.py --export-flow の出力）を mp4 にする。
スライドのプレビュー（ポスターフレーム）は動画のコマから選ぶ。

  python3 SlideKit/flow_to_movie.py /tmp/bhs-flow -o out/bhs-flow.mp4
  python3 SlideKit/flow_to_movie.py /tmp/bhs-flow -o out.mp4 --fps 8 --poster 7

出力:
  out.mp4                  PPTXへ埋め込む動画（H.264/yuv420p＝PowerPointが再生できる形）
  out_frames/frameNN.png   コマのPNG。スライドの poster= とPPTXのプレビュー画像に使う
  out_frames/index.html    コマ一覧。どの場面をプレビューにするか見て選ぶ
  out.flow.json            コマ数・fps・選んだポスター番号（スライド生成側が読む）

🚫 mp4 は PowerPoint が再生できる組み合わせに固定する（H.264 + yuv420p + 偶数解像度）。
   webm や yuv444p は Windows の PowerPoint で黒画面になる。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

KIT = os.path.dirname(os.path.abspath(__file__))


def find_chrome():
    cands = [
        os.environ.get('CHROME_PATH'),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        shutil.which('google-chrome'), shutil.which('chromium'),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def svg_size(text):
    """SVGの width/height（無ければ viewBox）から画素サイズを読む。"""
    m = re.search(r'\bwidth="([\d.]+)"', text)
    n = re.search(r'\bheight="([\d.]+)"', text)
    if m and n:
        return int(float(m.group(1))), int(float(n.group(1)))
    vb = re.search(r'viewBox="([-\d.\s]+)"', text)
    if vb:
        p = vb.group(1).split()
        if len(p) == 4:
            return int(float(p[2])), int(float(p[3]))
    return 1280, 720


def rasterize(chrome, svg_path, png_path, w, h, scale=1):
    """SVGを白背景のPNGにする。Chromeで撮るのでブラウザと同じ見た目になる。"""
    W, H = int(w * scale), int(h * scale)
    # 🚫 SVGを直接 --screenshot に渡すとウィンドウサイズに引き伸ばされて縦横比が崩れる。
    #    HTMLで包んで width/height を明示し、body余白を殺してから撮る。
    with open(svg_path, encoding='utf-8') as f:
        svg = f.read()
    svg = re.sub(r'<svg\b([^>]*?)\s(width|height)="[^"]*"', r'<svg\1', svg, count=2)
    svg = re.sub(r'<svg\b', '<svg width="%d" height="%d"' % (W, H), svg, count=1)
    tmpd = tempfile.mkdtemp(prefix='slidekit_flow_')
    try:
        hp = os.path.join(tmpd, 'f.html')
        with open(hp, 'w', encoding='utf-8') as f:
            f.write('<!DOCTYPE html><meta charset="utf-8">'
                    '<style>html,body{margin:0;padding:0;background:#fff}'
                    'svg{display:block}</style>' + svg)
        subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                        '--default-background-color=FFFFFFFF',
                        '--screenshot=' + png_path, '--window-size=%d,%d' % (W, H),
                        'file://' + hp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return os.path.exists(png_path)


def encode(frames_dir, out_mp4, fps, loops):
    """PNG連番 → mp4。PowerPointが再生できる H.264/yuv420p 固定。"""
    pattern = os.path.join(frames_dir, 'frame%02d.png')
    cmd = ['ffmpeg', '-y', '-loglevel', 'error']
    if loops > 1:
        cmd += ['-stream_loop', str(loops - 1)]
    cmd += ['-framerate', str(fps), '-i', pattern,
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.0',
            # 偶数解像度でないとlibx264が拒否する
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-r', '30', '-movflags', '+faststart',
            out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('ffmpeg 失敗: ' + (r.stderr or '').strip()[:400])
    return out_mp4


PICKER_CSS = """
body{margin:0;background:#fafafa;color:#121212;
 font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
header{padding:18px 24px;background:#183251;color:#fafafa}
h1{margin:0;font-size:17px}
p.lead{margin:6px 0 0;font-size:13px;color:#9fc0dd}
main{padding:20px 24px 40px}
video{max-width:900px;width:100%;background:#fff;border:1px solid #d4dde7;display:block}
.row{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
.panel{flex:1;min-width:320px}
.note{font-size:13px;color:#718096;margin-top:14px;line-height:1.7}
button{font:inherit;padding:8px 14px;border:1px solid #21537f;background:#fff;
 color:#21537f;border-radius:6px;cursor:pointer}
button.main{background:#21537f;color:#fff}
/* 🚫 150px幅だとコマ間で荷がどこまで進んだか見えず、選ぶ判断ができない（2026-08-21実測） */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:20px}
figure{margin:0;cursor:pointer;border:2px solid #d4dde7;border-radius:6px;overflow:hidden;background:#fff}
figure.on{border-color:#c62828;box-shadow:0 0 0 3px rgba(198,40,40,.18)}
figure img{width:100%;display:block}
figcaption{font-size:12px;padding:4px 6px;color:#718096}
code{display:block;white-space:pre-wrap;word-break:break-all;background:#eef3f8;
 border:1px solid #d4dde7;border-radius:6px;padding:10px;font-size:12px;margin-top:10px}
.pick{font-size:14px;margin-top:12px}
.pick b{color:#c62828}
"""

PICKER_JS = """
var FR=window.__FLOW__;var sel=FR.poster;
function paint(){
 document.querySelectorAll('figure').forEach(function(f){
  f.classList.toggle('on', Number(f.dataset.i)===sel);});
 document.getElementById('no').textContent='frame'+String(sel).padStart(2,'0')+'.png';
 document.getElementById('snip').textContent=
  '<video src="'+FR.mp4+'" poster="'+FR.dir+'/frame'+String(sel).padStart(2,'0')+'.png"'
  +' autoplay loop muted playsinline style="width:100%;height:100%;object-fit:contain">'
  +'</video>';
}
document.querySelectorAll('figure').forEach(function(f){
 f.addEventListener('click',function(){sel=Number(f.dataset.i);paint();});});
document.getElementById('now').addEventListener('click',function(){
 var v=document.getElementById('mv');
 // 再生位置 → コマ番号。ループ再生でも今見えているコマに合わせる
 var t=v.currentTime%(FR.frames/FR.fps);
 sel=Math.min(FR.frames-1,Math.max(0,Math.floor(t*FR.fps)));
 paint();});
document.getElementById('copy').addEventListener('click',function(){
 navigator.clipboard.writeText(document.getElementById('snip').textContent);
 this.textContent='コピーした';});
paint();
"""


def write_picker(frames_dir, names, meta, mp4_rel):
    """コマ一覧＝プレビュー（ポスターフレーム）を選ぶ画面。
    動画を見ながら止めて「今の場面をプレビューに」でも選べる。"""
    fig = []
    for i, n in enumerate(names):
        fig.append('<figure data-i="%d"><img src="%s" alt="コマ%d"><figcaption>frame%02d'
                   '</figcaption></figure>' % (i, n, i, i))
    state = json.dumps({'frames': meta['frames'], 'fps': meta['fps'],
                        'poster': meta['poster'], 'mp4': mp4_rel,
                        'dir': meta['frames_dir']}, ensure_ascii=False)
    html = ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            '<title>プレビューにする場面を選ぶ</title><style>%s</style></head><body>'
            '<header><h1>どの場面をプレビューにするか選ぶ</h1>'
            '<p class="lead">PowerPointは再生前にこの1枚を出す。荷が要所に乗っている場面を選ぶ。</p>'
            '</header><main><div class="row">'
            '<div class="panel"><video id="mv" src="%s" controls autoplay loop muted '
            'playsinline></video>'
            '<p class="pick">プレビュー: <b id="no"></b></p>'
            '<p><button id="now" class="main">今の場面をプレビューに</button> '
            '<button id="copy">スライドに貼る行をコピー</button></p>'
            '<code id="snip"></code>'
            '<p class="note">決めたら、スライドHTMLの <b>poster=</b> をそのコマに書き換える'
            '（Kiroに「frame07にして」と言うだけでもよい）。動画の作り直しは要らない。</p>'
            '</div></div>'
            '<div class="grid">%s</div></main>'
            '<script>window.__FLOW__=%s;</script><script>%s</script></body></html>'
            % (PICKER_CSS, mp4_rel, ''.join(fig), state, PICKER_JS))
    path = os.path.join(frames_dir, 'index.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    src = os.path.abspath(argv[0])
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    out_mp4 = os.path.abspath(opt('-o') or opt('--out')
                              or os.path.join(src, 'flow.mp4'))
    fps = max(1, min(30, int(opt('--fps', '8'))))
    loops = max(1, min(20, int(opt('--loops', '1'))))
    scale = max(1, min(3, int(opt('--scale', '1'))))
    poster = opt('--poster')

    svgs = sorted(f for f in os.listdir(src) if re.fullmatch(r'frame\d+\.svg', f))
    if not svgs:
        print('ERROR: %s に frameNN.svg が無い（先に cdp-run.py --export-flow で焼く）' % src)
        return 1
    chrome = find_chrome()
    if not chrome:
        print('ERROR: Chrome が見つからない（CHROME_PATH を設定する）')
        return 1
    if not shutil.which('ffmpeg'):
        print('ERROR: ffmpeg が無い（brew install ffmpeg）')
        return 1

    frames_dir = os.path.splitext(out_mp4)[0] + '_frames'
    os.makedirs(frames_dir, exist_ok=True)
    with open(os.path.join(src, svgs[0]), encoding='utf-8') as f:
        w, h = svg_size(f.read())
    names = []
    for i, name in enumerate(svgs):
        png = os.path.join(frames_dir, 'frame%02d.png' % i)
        if not rasterize(chrome, os.path.join(src, name), png, w, h, scale):
            print('ERROR: %s のPNG化に失敗' % name)
            return 1
        names.append(os.path.basename(png))
        print('  frame%02d ← %s (%d bytes)' % (i, name, os.path.getsize(png)))
    n = len(names)
    # 既定は真ん中のコマ。荷が経路の途中まで進んでいて、動きが想像しやすい
    idx = int(poster) if poster is not None else n // 2
    idx = max(0, min(n - 1, idx))

    encode(frames_dir, out_mp4, fps, loops)
    meta = {'frames': n, 'fps': fps, 'loops': loops, 'poster': idx,
            'mp4': os.path.basename(out_mp4),
            'frames_dir': os.path.basename(frames_dir),
            'size': [w * scale, h * scale],
            'duration': round(n * loops / fps, 2)}
    with open(os.path.splitext(out_mp4)[0] + '.flow.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    picker = write_picker(frames_dir, names,  meta,
                          os.path.relpath(out_mp4, frames_dir))
    print('MOVIE_OK %s %dx%d %d frames %.1fs fps=%d' %
          (out_mp4, meta['size'][0], meta['size'][1], n, meta['duration'], fps))
    print('POSTER   frame%02d.png（既定=中央のコマ）' % idx)
    print('PICKER   %s ← 開いて場面を選ぶ' % picker)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
