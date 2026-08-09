#!/usr/bin/env python3
"""CaptureKit 検証
使い方: python3 CaptureKit/check.py
1) edit.html / index.html の静的チェック（フォント下限・必須要素）
2) インラインJSの構文チェック（node --check）
3) Chrome headlessで edit.html#selftest を実行しピクセル処理の自動テスト
"""
import os, re, sys, subprocess, tempfile, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
results = []

def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))

def read(name):
    with open(os.path.join(BASE, name), encoding='utf-8') as f:
        return f.read()

# ---- 1. 静的チェック ----
edit = read('edit.html')
index = read('index.html')

# フォント下限（14px未満禁止・design-system準拠）
small = [m for m in re.findall(r'font-size:\s*(\d+)px', edit) if int(m) < 14]
check('edit.html フォント14px未満なし', not small, 'NG: ' + ','.join(small) if small else '')

for fid in ['cv', 'drop', 'tools', 'cropOk', 'cropNo', 'copyBtn', 'saveBtn', 'textin', 'toast']:
    check(f'edit.html #{fid} あり', f'id="{fid}"' in edit)

check('edit.html 井桁favicon', 'data:image/svg+xml' in edit)
check('edit.html ブランドヘッダー48px', 'height:48px' in edit and 'kit-mark' in edit)
check('edit.html 危険API不使用', '.innerHTML' not in edit and 'document.write' not in edit and 'eval(' not in edit)
check('index.html からエディタ導線', 'edit.html' in index)

# ツール一式が定義されているか
for t in ['crop', 'cropc', 'cropr', 'arrow', 'frame', 'ellipse', 'text', 'mosaic']:
    check(f'ツール {t} 定義', f'data-tool="{t}"' in edit)

# ---- 2. JS構文チェック ----
scripts = re.findall(r'<script>(.*?)</script>', edit, re.S)
check('インラインscript抽出', len(scripts) == 1)
with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as tf:
    tf.write(scripts[0] if scripts else '')
    js_path = tf.name
r = subprocess.run(['node', '--check', js_path], capture_output=True, text=True)
check('JS構文（node --check）', r.returncode == 0, r.stderr.strip()[:300])
os.unlink(js_path)

# ---- 3. Chrome headlessでselftest ----
def find_chrome():
    cands = [
        os.environ.get('CHROME_PATH', ''),
        shutil.which('google-chrome') or '',
        shutil.which('chromium') or '',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None

chrome = find_chrome()
if chrome:
    url = 'file://' + os.path.join(BASE, 'edit.html') + '#selftest'
    r = subprocess.run(
        [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
         '--virtual-time-budget=3000', '--dump-dom', url],
        capture_output=True, text=True, timeout=60)
    dom = r.stdout
    m = re.search(r'SELFTEST (PASS \d+/\d+|FAIL[^<]*)', dom)
    if m and m.group(1).startswith('PASS'):
        check('selftest（ピクセル処理）', True, m.group(1))
    else:
        check('selftest（ピクセル処理）', False, (m.group(1)[:200] if m else 'selftest結果がDOMにない'))
else:
    check('selftest（ピクセル処理）', False, 'Chromeが見つからない（CHROME_PATHで指定可）')

# ---- 結果 ----
ng = [x for x in results if not x[1]]
for name, ok, detail in results:
    mark = '✅' if ok else '❌'
    print(f'{mark} {name}' + (f'  {detail}' if detail else ''))
print()
print(f'{len(results) - len(ng)}/{len(results)} 通過')
sys.exit(1 if ng else 0)
