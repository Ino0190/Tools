#!/usr/bin/env python3
"""SlideKit 発表者ビューの追従テスト（Chrome headless・2窓・CDP）
  python3 SlideKit/presenter-check.py [対象.html]

本窓（手元）で slide-presenter.js を読み、別窓（発表者ビュー）を window.open で開いて、
  ① 発表者ビューが現在/次のスライド・ノート・時計・番号を出す
  ② 本窓でページを送ると別窓が追従する（BroadcastChannel / localStorage・file:// で動く方）
  ③ 別窓でページを送ると本窓も追従する（双方向）
  ④ 本窓には発表者ビューの要素（#_pv_root）が無い＝PPTX変換・保存に混ざらない
を確かめる。別窓は本窓から window.opener 経由（同一 file:// オリジン）で中身を読む。

終了コード: 0=問題なし / 1=問題あり / 2=実行失敗
"""
import importlib.util, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("cdpkit", os.path.join(ROOT, "BezierKit", "cdp-check.py"))
cdp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdp)
PROFILE = "/tmp/slidekit-presenter-check-profile"


def wait(sock, expr, timeout=10.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = cdp.ev(sock, expr)
            if last:
                return last
        except Exception as e:
            last = str(e)
        time.sleep(0.2)
    return last


# 本窓から別窓(window.opener先)の中身を読む小道具。見つからなければ None。
PV = r"""(function(){try{
  var w=window.__skPresenterWin; if(!w||w.closed||!w.document) return null;
  var d=w.document, root=d.getElementById('_pv_root'); if(!root) return null;
  var cur=d.getElementById('_pv_cur'), nx=d.getElementById('_pv_next');
  return {counter:(d.getElementById('_pv_counter')||{}).textContent,
          cur:cur?cur.getAttribute('data-cur-index'):null,
          next:nx?nx.getAttribute('data-index'):null,
          notes:(d.getElementById('_pv_notes')||{}).textContent||'',
          timer:(d.getElementById('_pv_timer')||{}).textContent,
          clock:(d.getElementById('_pv_clock')||{}).textContent,
          curHasSlide:!!(cur&&cur.querySelector('.slide'))};
}catch(e){return {err:String(e)};}})()"""


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "slide-template.html")
    path = os.path.abspath(target)
    if not os.path.exists(path):
        print(f"not found: {path}"); return 2
    subprocess.run(["pkill", "-f", PROFILE], capture_output=True)
    time.sleep(0.3)
    shutil.rmtree(PROFILE, ignore_errors=True)
    cdp.PORT = 9247
    chrome = subprocess.Popen([
        cdp.CHROME, "--headless=new", f"--remote-debugging-port={cdp.PORT}",
        f"--user-data-dir={PROFILE}", "--no-first-run", "--mute-audio",
        "--allow-file-access-from-files", "--disable-popup-blocking",
        "--window-size=1400,900", "file://" + path,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = []
    try:
        sock = cdp.connect(); sock.settimeout(60)
        cdp.call(sock, "Runtime.enable"); cdp.call(sock, "Page.enable")

        n = cdp.ev(sock, "document.querySelectorAll('.slide').length")
        if not n or n < 2:
            print(f"🔴 スライドが2枚以上ないと追従を試せません: {n}"); return 2

        # 本窓に発表者ビューのフックが配線されるのを待つ（slide-edit.js→自動読込）
        if not wait(sock, "typeof window.__skPresenterOpen==='function'", 12):
            print("🔴 本窓に __skPresenterOpen が出ない（slide-presenter.js が読めていない）"); return 1

        # 本窓には発表者ビューの要素が無い（PPTX/保存に混ざらない）＋ボタンは seui
        if cdp.ev(sock, "!!document.getElementById('_pv_root')"):
            problems.append("本窓に #_pv_root がある（変換に混ざる恐れ）")
        # ボタンはツールバー生成後に差し込まれる（非同期）ので、出るのを待ってから確かめる
        if not wait(sock, "!!document.getElementById('_pv_openbtn')", 10):
            problems.append("発表者ビューのボタンが本窓に出ない")
        elif not cdp.ev(sock, "(document.getElementById('_pv_openbtn')||{}).className==='seui'"):
            problems.append("発表者ビューのボタンに class='seui' が付いていない（保存/変換に残る）")

        # 別窓を開く
        cdp.ev(sock, "window.__skPresenterOpen(); true")
        pv = wait(sock, PV, 12)
        if not isinstance(pv, dict) or pv.get("err") or not pv.get("counter"):
            print(f"🔴 発表者ビューが開かない/中身が読めない: {pv}"); return 1

        # 初期（idx 0）: 1枚目・次は2枚目・時計の書式
        if pv["counter"] != f"1 / {n}":
            problems.append(f"初期の番号が 1 / {n} でない: {pv['counter']}")
        if pv["cur"] != "0" or pv["next"] != "1":
            problems.append(f"初期の現在/次が 0/1 でない: cur={pv['cur']} next={pv['next']}")
        if not pv["curHasSlide"]:
            problems.append("現在のスライドが縮小表示されていない（.slide のクローンが無い）")
        import re
        if not re.match(r"^\d\d:\d\d:\d\d$", pv["timer"] or ""):
            problems.append(f"経過時間の書式が HH:MM:SS でない: {pv['timer']}")
        if not re.match(r"^\d\d:\d\d$", pv["clock"] or ""):
            problems.append(f"時計の書式が HH:MM でない: {pv['clock']}")
        print(f"[開く] {pv['counter']}  現在={pv['cur']} 次={pv['next']} 時計={pv['clock']} 経過={pv['timer']}")

        # ② 本窓で最後のページへ送る → 別窓が追従
        cdp.ev(sock, f"window.__skPresenterGoto({n-1}); true")
        pv2 = wait(sock, f"(function(){{var p={PV};return (p&&p.counter==='{n} / {n}')?p:null;}})()", 8)
        if not isinstance(pv2, dict):
            cur = cdp.ev(sock, PV)
            problems.append(f"本窓→別窓の追従が効かない（最後へ送っても別窓が変わらない）: {cur}")
        else:
            if pv2["cur"] != str(n - 1):
                problems.append(f"追従後の現在ページが {n-1} でない: {pv2['cur']}")
            if pv2["next"] not in (None, "null"):
                problems.append(f"最後のページで『次』が空でない: {pv2['next']}")
            # 2枚目にはテンプレの data-notes があるのでノートが出る
            notes_ok = ("ノート" in pv2["notes"]) or (len(pv2["notes"]) > 0 and "ありません" not in pv2["notes"])
            if not notes_ok:
                problems.append(f"最後のページのノートが出ていない: {pv2['notes'][:40]}")
            print(f"[本窓→別窓] {pv2['counter']}  現在={pv2['cur']} 次={pv2['next']} ノート={pv2['notes'][:24]!r}")

        # ②b 発表時間の目安（2026-11-14）: 別窓に __pvTiming があり、枚数ぶんの秒があって合計が正、ヘッダに「目安」が出る
        tm = cdp.ev(sock, "(function(){var w=window.__skPresenterWin;if(!w||!w.__pvTiming)return null;var t=w.__pvTiming();"
                          "var el=w.document.getElementById('_pv_pace');return {n:t.est.length,total:t.total,min:Math.min.apply(null,t.est),pace:el?el.textContent:''};})()")
        if not tm or tm["n"] != cdp.ev(sock, "document.querySelectorAll('.slide').length") or tm["total"] <= 0 or tm["min"] < 8 or "目安" not in tm["pace"]:
            problems.append(f"発表時間の目安が出ていない: {tm}")
        else:
            print(f"[目安] {tm['n']}枚・合計 {tm['total']}秒・ヘッダ『{tm['pace']}』")

        # ③ 別窓でページを戻す → 本窓が追従
        cdp.ev(sock, "window.__skPresenterWin.__pvGoto(0); true")
        back = wait(sock, "(function(){return window.__skPresenterCur()===0;})()", 8)
        if not back:
            problems.append(f"別窓→本窓の追従が効かない（本窓の現在ページが戻らない）: cur={cdp.ev(sock,'window.__skPresenterCur()')}")
        else:
            print("[別窓→本窓] 本窓の現在ページ=0 に追従 OK")
    finally:
        chrome.terminate()

    if problems:
        print("🔴 問題あり: " + " / ".join(problems)); return 1
    print("✅ 発表者ビュー 追従テスト 問題なし"); return 0


if __name__ == "__main__":
    sys.exit(main())
