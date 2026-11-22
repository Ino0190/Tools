#!/usr/bin/env python3
"""SlideKit 編集UIの実ブラウザ検査（Chrome headless / CDP）
  python3 SlideKit/ui-check.py 対象.html [--width 1512 --height 900] [--shot /tmp/skui]
見るもの:
  ① 「📺 プレゼン再生」ボタンが存在し、画面内で他の要素に隠れていない（閲覧時・編集時）
  ② 右パネル内の要素が列からはみ出していない／入力欄が潰れていない（編集ON・要素選択時）
  ③ スライドが右パネルの下に潜っていない
終了コード: 0=問題なし / 1=問題あり / 2=実行失敗
"""
import argparse, base64, importlib.util, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("cdpkit", os.path.join(ROOT, "BezierKit", "cdp-check.py"))
cdp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdp)
PROFILE = "/tmp/slidekit-ui-check-profile"

# ブラウザ内で実行する検査。結果はJSONで返す
PROBE_JS = r"""(function(){
  const out={present:null,overflow:[],squashed:[],slideUnder:false};
  const btn=document.getElementById('_sp_openbtn');
  if(!btn){out.present='missing';}
  else{
    const r=btn.getBoundingClientRect();
    const inView=r.width>0&&r.height>0&&r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth;
    const hit=inView?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
    const covered=hit&&!(hit===btn||btn.contains(hit));
    out.present=!inView?'offscreen':(covered?'covered':'ok');
    out.presentParent=btn.parentElement&&btn.parentElement.id||btn.parentElement&&btn.parentElement.tagName;
  }
  const bar=document.getElementById('_sk_toolbar');
  if(bar){
    const br=bar.getBoundingClientRect();out.barWidth=Math.round(br.width);
    bar.querySelectorAll('button,input,select,span,div').forEach(el=>{
      const cs=getComputedStyle(el);if(cs.display==='none'||cs.visibility==='hidden')return;
      const r=el.getBoundingClientRect();if(!r.width||!r.height)return;
      let p=el.parentElement,hidden=false;
      while(p&&p!==bar){if(getComputedStyle(p).display==='none'){hidden=true;break;}p=p.parentElement;}
      if(hidden)return;
      const name=(el.id?'#'+el.id:el.tagName.toLowerCase())+' '+((el.textContent||el.value||'').trim().slice(0,14));
      if(r.right>br.right+1||r.left<br.left-1)out.overflow.push(name+' ('+Math.round(r.left-br.left)+'..'+Math.round(r.right-br.left)+')');
      // 数値欄（太さ・サイズ）は2〜3桁が入れば足りる。色コード等の文字欄は #rrggbb が読める幅が要る
      const numeric=/numeric|decimal/.test(el.getAttribute('inputmode')||'');
      if(el.tagName==='INPUT'&&el.type==='text'&&r.width<(numeric?22:36))out.squashed.push(name+' w='+Math.round(r.width));
    });
    const s=document.querySelector('.slide');
    if(s&&document.body.getAttribute('data-skit-edit')==='on'){
      out.slideUnder=s.getBoundingClientRect().right>br.left+1;
    }
  }
  return out;
})()"""


def shot(sock, path):
    data = cdp.call(sock, "Page.captureScreenshot", {"format": "png"}).get("data")
    if data:
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))


def wait_ready(sock, timeout=8.0):
    """ツールバーの生成を待つ。出来なければFalse（本体なしHTML）"""
    end = time.time() + timeout
    while time.time() < end:
        if cdp.ev(sock, "!!document.getElementById('_sk_toolbar')"):
            return True
        time.sleep(0.2)
    return False


def report(label, r, problems):
    print(f"[{label}] 発表ボタン={r['present']}（親={r.get('presentParent')}） パネル幅={r.get('barWidth')}px")
    if r["present"] != "ok":
        problems.append(f"{label}: 発表ボタンが{r['present']}")
    for k, msg in (("overflow", "はみ出し"), ("squashed", "入力欄が潰れている")):
        if r[k]:
            problems.append(f"{label}: {msg} {len(r[k])}件")
            for x in r[k][:8]:
                print(f"    {msg}: {x}")
    if r.get("slideUnder"):
        # 画面幅の問題（スライドは1280px固定・編集中は縮小しない）。不具合ではないので警告に留める
        print(f"    ⚠️ 画面幅不足: スライド右端が右パネルの下に入る（編集には {140 + 1280 + (r.get('barWidth') or 0) + 16}px 以上の幅が要る）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--width", type=int, default=1512)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--port", type=int, default=9241)
    ap.add_argument("--shot", default="", help="スクショの出力先プレフィックス（例 /tmp/skui）")
    a = ap.parse_args()
    path = os.path.abspath(a.html)
    if not os.path.exists(path):
        print(f"not found: {path}"); return 2
    subprocess.run(["pkill", "-f", PROFILE], capture_output=True)
    time.sleep(0.3)
    # 前回のキャッシュで古い slide-edit.js を読まないよう、毎回まっさらなプロファイルで起動する
    shutil.rmtree(PROFILE, ignore_errors=True)
    cdp.PORT = a.port
    chrome = subprocess.Popen([cdp.CHROME, "--headless=new", f"--remote-debugging-port={a.port}",
                               f"--user-data-dir={PROFILE}", "--no-first-run", "--allow-file-access-from-files",
                               f"--window-size={a.width},{a.height}", "file://" + path],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = []
    try:
        sock = cdp.connect(); sock.settimeout(60)
        cdp.call(sock, "Runtime.enable"); cdp.call(sock, "Page.enable")
        cdp.call(sock, "Emulation.setDeviceMetricsOverride",
                 {"width": a.width, "height": a.height, "deviceScaleFactor": 1, "mobile": False})
        if not wait_ready(sock):
            print("🔴 ツールバーが生成されない（slide-edit.js が読めていない可能性）"); return 1
        time.sleep(0.8)
        r = cdp.ev(sock, PROBE_JS); report("閲覧", r, problems)
        if a.shot: shot(sock, a.shot + "-view.png")
        cdp.ev(sock, "document.getElementById('seEdit').click()"); time.sleep(0.6)
        r = cdp.ev(sock, PROBE_JS); report("編集", r, problems)
        if a.shot: shot(sock, a.shot + "-edit.png")
        # 1枚目の最初の文字枠を選択して、選択パネルまで開いた状態を見る
        cdp.ev(sock, """(function(){const t=document.querySelector('.slide .tb');if(!t)return;
          t.scrollIntoView({block:'center'});const r=t.getBoundingClientRect();
          ['mousedown','mouseup','click'].forEach(k=>t.dispatchEvent(new MouseEvent(k,{bubbles:true,clientX:r.left+5,clientY:r.top+5})));})()""")
        time.sleep(0.6)
        r = cdp.ev(sock, PROBE_JS); report("選択", r, problems)
        if a.shot:
            shot(sock, a.shot + "-select.png")
            # 選択パネル（文字色・サイズ・枠線など）が見える位置までツールバーをスクロールして撮る
            cdp.ev(sock, """(function(){const b=document.getElementById('_sk_toolbar');if(!b)return;
              const l=[...b.querySelectorAll('span')].find(s=>s.textContent.trim()==='文字色');
              if(l)b.scrollTop+=l.getBoundingClientRect().top-b.getBoundingClientRect().top-60;})()""")
            time.sleep(0.3)
            shot(sock, a.shot + "-selbar.png")
        cdp.ev(sock, "const _c=document.getElementById('_sk_toolbar');_c&&(_c.scrollTop=_c.scrollHeight)")
        time.sleep(0.3)
        r = cdp.ev(sock, PROBE_JS); report("スクロール後", r, problems)
        if a.shot: shot(sock, a.shot + "-scrolled.png")
    finally:
        chrome.terminate()
    if problems:
        print("🔴 問題あり: " + " / ".join(problems)); return 1
    print("✅ UI検査 問題なし"); return 0


if __name__ == "__main__":
    sys.exit(main())
