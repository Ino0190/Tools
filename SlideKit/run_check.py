#!/usr/bin/env python3
"""SlideKit Layout Diagnostic CLI
使い方: python3 SlideKit/run_check.py MyDeck/slides.html
Chrome headlessでHTMLを開き、window.__slideKitCheck()の結果をJSONで返す。

Chrome の場所は次の順で検索:
  1) 環境変数 CHROME_PATH
  2) PATH 上の google-chrome / chromium / chromium-browser (Linux)
  3) Mac の Application 配下
  4) Windows の Program Files 配下
"""
import sys, os, json, subprocess, tempfile, time, re, shutil


def _find_chrome():
    """Chrome/Chromium/Edge の実行ファイルを見つける (未発見なら None)"""
    cands = [
        os.environ.get('CHROME_PATH', ''),
        # Linux
        shutil.which('google-chrome') or '',
        shutil.which('google-chrome-stable') or '',
        shutil.which('chromium') or '',
        shutil.which('chromium-browser') or '',
        # macOS
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        # Windows
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


CHROME = _find_chrome()

def main():
    if len(sys.argv) < 2:
        print('usage: run_check.py <html_path>')
        sys.exit(1)
    if not CHROME:
        print('ERROR: Chrome/Chromium/Edge が見つかりません。')
        print('  以下のいずれかで対処してください:')
        print('  1) Chrome/Chromium/Edge をインストール')
        print('  2) 環境変数 CHROME_PATH で実行ファイルのパスを指定')
        sys.exit(2)
    html_path = os.path.abspath(sys.argv[1])
    if not os.path.exists(html_path):
        print(f'not found: {html_path}'); sys.exit(1)

    # 一時HTMLを作って、診断スクリプトを実行→結果をtitleに書き出す
    with open(html_path, encoding='utf-8') as f:
        src = f.read()
    inject = '''
<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    try {
      var r = window.__slideKitCheck ? window.__slideKitCheck() : [];
      document.title = '__SLIDEKIT_RESULT__' + JSON.stringify(r);
    } catch(e) {
      document.title = '__SLIDEKIT_ERROR__' + e.message;
    }
  }, 800);
});
</script>
</body>
'''
    new_src = src.replace('</body>', inject)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8',
                                       dir=os.path.dirname(html_path)) as tf:
        tf.write(new_src)
        tmp_path = tf.name
    try:
        # Chrome headlessでDOM dump
        result = subprocess.run([
            CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
            '--virtual-time-budget=3000', '--window-size=1280,720',
            '--dump-dom', f'file://{tmp_path}'
        ], capture_output=True, text=True, timeout=60)
        dom = result.stdout
        m = re.search(r'<title>__SLIDEKIT_(RESULT|ERROR)__(.*?)</title>', dom, re.DOTALL)
        if not m:
            print('診断結果が取得できませんでした。check-layout.jsが読み込まれているか確認してください。')
            print('STDERR:', result.stderr[:500] if result.stderr else '')
            sys.exit(2)
        kind, payload = m.group(1), m.group(2)
        if kind == 'ERROR':
            print('診断エラー:', payload)
            sys.exit(3)
        issues = json.loads(payload)
        if not issues:
            print(f'✅ {os.path.basename(html_path)}: 問題なし')
            return
        print(f'⚠️ {os.path.basename(html_path)}: {len(issues)}件の問題')
        # 種別別カウント
        kinds = {}
        for iss in issues:
            kinds[iss['kind']] = kinds.get(iss['kind'], 0) + 1
        labels = {
            'overlap':'rect重なり','overflow-slide-x':'横はみ出し','overflow-slide-y':'縦はみ出し',
            'text-overflow':'中身あふれ','text-overflow-x':'横あふれ',
            'image-aspect':'画像アス比ずれ'
        }
        print('  内訳:', '  '.join(f'{labels.get(k,k)}={v}' for k,v in kinds.items()))
        print()
        for iss in issues:
            print(f'  S{iss["slideIdx"]} [{iss["kind"]}] {iss["msg"]}')
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

if __name__ == '__main__':
    main()
