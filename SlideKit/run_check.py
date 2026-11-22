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
    # 診断本体（check-layout.js）はデッキが読んでいなくても必ず差し込む。
    # 🚫 雛形もslide-edit.jsも読み込まないため、以前は全デッキで診断が空振りし
    #    「✅問題なし」を返していた（2026-09-27・韓国L7で読ませると22件）
    loader = ''
    if 'check-layout.js' not in src:
        cl = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'check-layout.js')
        loader = '<script src="file://%s"></script>\n' % cl
    inject = loader + '''
<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    try {
      if (!window.__slideKitCheck) throw new Error('check-layout.js が読み込めませんでした（診断していません）');
      var r = window.__slideKitCheck();
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
        # 🚫 以前は capture_output=True（stdout をパイプ）で受けていたが、Chrome 157 では DOM を吐いた後も
        #   後始末の子プロセスがパイプの書き端を握ったまま居座り、EOF が来ず subprocess.run が timeout まで
        #   必ず待ってしまう（診断が空の DOM で返る）。stdout を実ファイルに落とすと本体の終了で返る。（2026-11-15）
        prof = tempfile.mkdtemp(prefix='.skrcprof-')  # 既定プロファイルと競合させない専用の一時プロファイル（2026-11-15）
        dom_path = tmp_path + '.dom'
        try:
            with open(dom_path, 'w', encoding='utf-8') as fo:
                subprocess.run([
                    CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
                    '--mute-audio', '--user-data-dir=' + prof,  # 🚫 --mute-audio なし・既定プロファイルは禁止（キット群の決まり／競合よけ）（2026-11-15）
                    '--virtual-time-budget=3000', '--window-size=1280,720',
                    '--dump-dom', f'file://{tmp_path}'
                ], stdout=fo, stderr=subprocess.DEVNULL, timeout=60)
            dom = open(dom_path, encoding='utf-8').read() if os.path.exists(dom_path) else ''
        except subprocess.TimeoutExpired:
            dom = ''  # 時間切れでも落とさず「取得できなかった」として扱う（2026-11-15）
        finally:
            if os.path.exists(dom_path):
                os.unlink(dom_path)
            shutil.rmtree(prof, ignore_errors=True)
        m = re.search(r'<title>__SLIDEKIT_(RESULT|ERROR)__(.*?)</title>', dom, re.DOTALL)
        if not m:
            print('診断結果が取得できませんでした。check-layout.jsが読み込まれているか確認してください。')
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
            'image-aspect':'画像アス比ずれ','broken-link':'ページリンク切れ'
        }
        print('  内訳:', '  '.join(f'{labels.get(k,k)}={v}' for k,v in kinds.items()))
        print()
        for iss in issues:
            where = f'「{iss["text"]}」 ' if iss.get('text') else ''
            print(f'  {iss["slideIdx"]}枚目 [{iss["kind"]}] {where}{iss["msg"]}')
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

if __name__ == '__main__':
    main()
