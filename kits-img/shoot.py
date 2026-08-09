#!/usr/bin/env python3
# kits.html用のキットスクショ撮影。ワークスペース直下で:
#   python3 kits-img/shoot.py            # 全部撮る
#   python3 kits-img/shoot.py cadkit     # 1つだけ撮る（名前はSHOTSのキー）
# 1280×800・Retina2倍。待ち時間はページ別（OCCT等の重いビルドは長め）
import subprocess, os, sys
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHOTS = {  # name: (page, 仮想時間ms)
    'slidekit':     ('SlideKit/pattern-catalog.html',          9000),
    'dashboardkit': ('DashboardKit/gym-demo.html',             9000),
    'archkit':      ('ArchKit/gym-demo.html',                  9000),
    'cadkit':       ('CadKit/index.html#tinrobot',            40000),  # ブリキロボ（ゼンマイ・色付き）
    'bezierkit':    ('BezierKit/index.html',                   9000),
    'ganttkit':     ('GanttKit/index.html',                    9000),
    'calckit':      ('CalcKit/index.html',                     9000),
    'capturekit':   ('CaptureKit/index.html',                  9000),
    'dockit':       ('DocKit/index.html',                      9000),
    'classroomkit': ('ClassroomKit/teacher-console.html',      9000),
}
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
targets = sys.argv[1:] or list(SHOTS)
for name in targets:
    if name not in SHOTS:
        print(f'{name}: 不明（候補: {" ".join(SHOTS)}）'); continue
    page, budget = SHOTS[name]
    out = f'kits-img/{name}.png'
    subprocess.run([CHROME, '--headless=new', '--hide-scrollbars', '--window-size=1280,800',
                    '--force-device-scale-factor=2', f'--virtual-time-budget={budget}',
                    f'--screenshot={out}', 'file://' + os.path.abspath(page)],
                   capture_output=True, timeout=180)
    print(f'{name}: {os.path.getsize(out):,} bytes' if os.path.exists(out) else f'{name}: 失敗')
