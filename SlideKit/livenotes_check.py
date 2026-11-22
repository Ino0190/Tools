#!/usr/bin/env python3
"""Live Notes の回帰テスト。

    python3 SlideKit/livenotes_check.py              # ロジック + ブラウザ
    python3 SlideKit/livenotes_check.py --logic      # ロジックだけ（1秒）

検証の要点:
  ・発言が「そのとき表示していたスライド」に付く。あとで進めても過去は変わらない
  ・プレゼン本体に干渉しない（キー漏れなし・マイクが無くてもスライドは動く）
  ・ユーザー操作なしに録音を始めない。停止でマイクを確実に離す
  ・reload しても記録が残る

マイクは Chrome の擬似デバイスで代用する（実マイクは不要）。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 9411
PROFILE = "/tmp/sk-ln-check"
ng = []


def chk(label, got, want):
    ok = got == want
    print(f"  {'OK' if ok else 'NG'} {label}: {got}" + ("" if ok else f" （期待 {want}）"))
    if not ok:
        ng.append(label)
    return got


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ============================================================
# 1. スライド割り当てロジック（Python側）
# ============================================================
def check_logic():
    print("■ スライド割り当て")
    lt = load(os.path.join(HERE, "livenotes_transcribe.py"), "lt")
    session = {
        "sessionId": "test", "title": "テスト", "deck": "t.html",
        "startedAt": "2026-09-12T14:03:00+09:00",
        "recordStartedAt": "2026-09-12T14:03:00+09:00",
        "entries": [
            {"id": "n1", "type": "slide", "atMs": 0,      "slideIndex": 4, "slideId": "slide-5", "clock": "14:03:00"},
            {"id": "n2", "type": "slide", "atMs": 120000, "slideIndex": 5, "slideId": "slide-6", "clock": "14:05:00"},
            {"id": "n3", "type": "slide", "atMs": 300000, "slideIndex": 6, "slideId": "slide-7", "clock": "14:08:00"},
            {"id": "n4", "type": "memo",  "atMs": 180000, "slideIndex": 5, "slideId": "slide-6",
             "clock": "14:06:00", "text": "海外拠点を含めた数字も見たい"},
        ],
    }
    segments = [
        {"start": 60.0,  "end": 64.0,  "text": " この数字は去年との比較ですか？"},
        {"start": 180.0, "end": 184.0, "text": " 海外拠点を含めた場合の数字も見たい。"},
        {"start": 360.0, "end": 364.0, "text": " このコストには海外拠点も入っていますか？"},
        {"start": 0.5,   "end": 2.0,   "text": "   "},
    ]
    marks = lt.slide_timeline(session)
    chk("14:04の発言 → Slide5", lt.slide_at(marks, 60000)[0], 4)
    chk("14:06の発言 → Slide6", lt.slide_at(marks, 180000)[0], 5)
    chk("14:09の発言 → Slide7", lt.slide_at(marks, 360000)[0], 6)
    chk("切替の瞬間は新しい方", lt.slide_at(marks, 120000)[0], 5)
    chk("切替の1ms前は前のまま", lt.slide_at(marks, 119999)[0], 4)

    entries = lt.build_entries(session, segments)
    tr = [e for e in entries if e["type"] == "transcript"]
    chk("空セグメントを捨てる", len(tr), 3)
    chk("時刻が実時刻になる", tr[0]["clock"], "14:04:00")
    chk("メモも混ざる", sum(1 for e in entries if e["type"] == "memo"), 1)
    chk("時系列に並ぶ", [e["atMs"] for e in entries], sorted(e["atMs"] for e in entries))

    before = [e["slideIndex"] for e in tr]
    s2 = dict(session)
    s2["entries"] = session["entries"] + [
        {"id": "n9", "type": "slide", "atMs": 600000, "slideIndex": 9, "slideId": "slide-10", "clock": "14:13:00"}]
    after = [e["slideIndex"] for e in lt.build_entries(s2, segments) if e["type"] == "transcript"]
    chk("あとで進めても過去は不変", after, before)

    md = lt.to_markdown(session, entries)
    chk("Markdownにスライド見出し", ("## Slide 5" in md) and ("## Slide 7" in md), True)

    # 別アプリ（ボイスメモ）の音声を使う場合。2分早く回し始めた音声なら offset=120
    shifted = [{"start": s["start"] + 120, "end": s["end"] + 120, "text": s["text"]} for s in segments]
    e2 = [e for e in lt.build_entries(session, shifted, 120.0) if e["type"] == "transcript"]
    chk("offsetを引くと元と同じ割り当てになる",
        [e["slideIndex"] for e in e2], [e["slideIndex"] for e in tr])
    chk("offset適用後も時刻が合う", e2[0]["clock"], tr[0]["clock"])
    # 録音開始より前の発言（プレゼン前の雑談）は最初のスライドに寄せる
    pre = lt.build_entries(session, [{"start": 10.0, "end": 12.0, "text": "始める前の雑談"}], 120.0)
    chk("開始前の発言は最初のスライドへ", pre[0]["slideIndex"], 4)

    # AI に仕分けを頼む形
    ai = lt.to_ai_markdown(session, entries)
    chk("お願いが先頭に入る", ai.startswith("# 議事メモの作成をお願いします"), True)
    chk("5分類を指示している",
        all(k in ai for k in ["質問", "懸念", "決定事項", "宿題", "修正要求"]), True)
    chk("スライド番号を残す指示がある", "スライド番号を必ず残す" in ai, True)
    chk("記録の本文が入る", "海外拠点を含めた場合の数字も見たい" in ai, True)
    chk("メモと発言の区別を説明している", "発表者がその場で打ったメモ" in ai, True)
    chk("スライド見出しが並ぶ", ai.count("## Slide "), 3)


# ============================================================
# 2. ブラウザ側（パネル・録音・紐づけ・非干渉）
# ============================================================
DECK_HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>Live Notes check</title>
<style>body{margin:0;background:#3a4756;padding:20px 0 60px}
.slide{width:1280px;height:720px;margin:12px auto;background:#fafafa;font:40px sans-serif;
display:flex;align-items:center;justify-content:center}</style></head><body>
<div class="slide" id="slide-a">1枚目</div>
<div class="slide" id="slide-b">2枚目</div>
<div class="slide" id="slide-c">3枚目</div>
<script src="slide-present.js"></script>
<script src="slide-livenotes.js"></script>
</body></html>
"""


def check_browser():
    cdp = load(os.path.join(ROOT, "BezierKit", "cdp-check.py"), "cdp")
    cdp.PORT = PORT
    deck_path = os.path.join(HERE, ".livenotes_check_deck.html")
    with open(deck_path, "w", encoding="utf-8") as f:
        f.write(DECK_HTML)
    deck = "file://" + urllib.parse.quote(deck_path)

    def boot(url):
        subprocess.run(["pkill", "-f", "sk-ln-check"], capture_output=True)
        time.sleep(0.5)
        p = subprocess.Popen([
            cdp.CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
            f"--user-data-dir={PROFILE}", "--allow-file-access-from-files",
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
            "--window-size=1400,900", "--hide-scrollbars", url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s = cdp.connect()
        s.settimeout(300)
        cdp.call(s, "Runtime.enable")
        cdp.call(s, "Page.enable")
        for _ in range(100):
            if cdp.ev(s, "document.readyState==='complete'"):
                break
            time.sleep(0.2)
        time.sleep(1.0)
        return p, s

    def sess(s):
        return json.loads(cdp.ev(s, "localStorage.getItem('slidekit_livenotes_session')||'null'") or "null")

    def memo(s, text):
        cdp.ev(s, f"""(()=>{{const m=document.querySelector('#sk-ln .memo');
          m.value={json.dumps(text)};
          m.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}));return true;}})()""")
        time.sleep(0.25)

    def wait(s, expr, n=40):
        for _ in range(n):
            if cdp.ev(s, expr):
                return True
            time.sleep(0.2)
        return False

    try:
        print("■ パネルと録音")
        chrome, sock = boot(deck)
        try:
            # 前回のテストで残った記録を消してから始める（テストどうしを独立させる）
            cdp.ev(sock, "localStorage.clear()")
            cdp.call(sock, "Page.reload", {})
            time.sleep(1.5)
            wait(sock, "!!document.getElementById('sk-ln')")
            chk("パネルが出る", cdp.ev(sock, "!!document.getElementById('sk-ln')"), True)
            chk("勝手に録音していない", cdp.ev(sock, "document.querySelector('#sk-ln .dot').className.indexOf('rec')<0"), True)
            cdp.ev(sock, "document.querySelector('#sk-ln .hd').click()")
            # 権限前でもマイク欄が空にならない（何が使われるか分かる）
            chk("Start前もマイク欄に説明がある",
                cdp.ev(sock, "document.querySelectorAll('#sk-ln select option').length>=1"), True)
            cdp.ev(sock, "document.querySelector('#sk-ln .go').click()")
            wait(sock, "document.querySelector('#sk-ln .dot').classList.contains('rec')")
            chk("録音中の表示になる", cdp.ev(sock, "document.querySelector('#sk-ln .dot').classList.contains('rec')"), True)
            # 権限が通った後はデバイス名が読めるので選択肢を埋め直す（初回だけ選べない不具合の回帰）
            wait(sock, "[...document.querySelectorAll('#sk-ln select option')].some(o=>o.value)")
            chk("録音開始後はマイクを選べる",
                cdp.ev(sock, "[...document.querySelectorAll('#sk-ln select option')].some(o=>o.value)"), True)
            chk("マイク名が表示される",
                cdp.ev(sock, "document.querySelector('#sk-ln .st').textContent.length>10"), True)
            # 選んだマイクを覚える
            cdp.ev(sock, """(()=>{const s=document.querySelector('#sk-ln select');
              s.selectedIndex=0;s.dispatchEvent(new Event('change'));return true;})()""")
            chk("選んだマイクをlocalStorageに覚える",
                cdp.ev(sock, "localStorage.getItem('slidekit_livenotes_device')!==null"), True)

            print("■ スライドとの紐づけ")
            memo(sock, "1枚目についての質問")
            s = sess(sock)
            m0 = [e for e in s["entries"] if e["type"] == "memo"]
            chk("メモが今のスライドに付く", m0[0]["slideIndex"], 0)
            cdp.ev(sock, """(()=>{const b=new BroadcastChannel(window.__skPresentChannel);
              b.postMessage({type:'slide:change',index:2,total:3,from:'present'});return true;})()""")
            time.sleep(0.6)
            chk("既存の通知で現在スライドを拾う",
                cdp.ev(sock, "/Slide 3/.test(document.querySelector('#sk-ln .st').textContent)"), True)
            memo(sock, "3枚目への指摘")
            s = sess(sock)
            m1 = [e for e in s["entries"] if e["type"] == "memo"]
            chk("2件目は新しいスライドに付く", m1[1]["slideIndex"], 2)
            chk("1件目のスライドは変わらない", m1[0]["slideIndex"], 0)
            memo(sock, "!これは宿題")
            chk("!で重要マークになる", [e["text"] for e in sess(sock)["entries"] if e["type"] == "mark"], ["これは宿題"])

            print("■ プレゼンへの非干渉")
            cdp.ev(sock, "window.__leak=0;document.addEventListener('keydown',()=>{window.__leak++})")
            cdp.ev(sock, """(()=>{const m=document.querySelector('#sk-ln .memo');
              ['ArrowRight','ArrowLeft',' ','PageDown'].forEach(k=>
                m.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true})));return true;})()""")
            chk("メモ欄のキーがスライド送りへ漏れない", cdp.ev(sock, "window.__leak"), 0)

            print("■ 停止と保存")
            cdp.ev(sock, "document.querySelector('#sk-ln .stop').click()")
            wait(sock, "/停止/.test(document.querySelector('#sk-ln .st').textContent)")
            chk("録音インジケータが消える",
                cdp.ev(sock, "document.querySelector('#sk-ln .dot').classList.contains('rec')"), False)
            chk("マイクのトラックが残っていない",
                cdp.ev(sock, "(()=>{const a=document.querySelectorAll('audio,video');return a.length;})()"), 0)
            s = sess(sock)
            chk("停止時刻と音声名が入る", bool(s.get("recordStoppedAt")) and bool(s.get("audioFile")), True)
            need = ["id", "timestamp", "clock", "atMs", "slideIndex", "slideId", "text", "speaker", "type"]
            chk("entryの項目が揃う", [k for k in need if k not in s["entries"][0]], [])
            before = len(s["entries"])
            cdp.call(sock, "Page.reload", {})
            time.sleep(2.0)
            wait(sock, "!!document.getElementById('sk-ln')")
            chk("reload後もエントリが残る", len(sess(sock)["entries"]), before)
            chk("reloadで勝手に録音しない",
                cdp.ev(sock, "document.querySelector('#sk-ln .dot').classList.contains('rec')"), False)

            # 次のプレゼンを始めたとき、前回の記録に追記しない（別セッションになる）
            print("■ 2回目のプレゼン")
            old_id = sess(sock)["sessionId"]
            cdp.ev(sock, "document.querySelector('#sk-ln .hd').click()")
            cdp.ev(sock, "document.querySelector('#sk-ln .go').click()")
            wait(sock, "document.querySelector('#sk-ln .dot').classList.contains('rec')")
            s2 = sess(sock)
            chk("別のセッションになる", s2["sessionId"] != old_id, True)
            chk("前回のメモを引き継がない", len([e for e in s2["entries"] if e["type"] == "memo"]), 0)
            chk("前回分は退避される",
                cdp.ev(sock, "!!localStorage.getItem('slidekit_livenotes_session_prev')"), True)
            cdp.ev(sock, "document.querySelector('#sk-ln .stop').click()")
            wait(sock, "/停止/.test(document.querySelector('#sk-ln .st').textContent)")
        finally:
            chrome.terminate()

        print("■ 投影側とエラー時")
        chrome, sock = boot(deck + "?present=1&idx=0")
        try:
            chk("投影側にパネルを出さない", cdp.ev(sock, "!!document.getElementById('sk-ln')"), False)
            chk("投影側のスライドは生きている", cdp.ev(sock, "document.querySelectorAll('.slide').length"), 3)
        finally:
            chrome.terminate()

        chrome, sock = boot(deck)
        try:
            cdp.ev(sock, """(()=>{navigator.mediaDevices.getUserMedia=function(){
              return Promise.reject(Object.assign(new Error('no mic'),{name:'NotFoundError'}));};return true;})()""")
            cdp.ev(sock, "document.querySelector('#sk-ln .hd').click()")
            cdp.ev(sock, "document.querySelector('#sk-ln .go').click()")
            time.sleep(1.2)
            chk("マイクなしはパネル内に表示",
                cdp.ev(sock, "/見つかりません|許可されていません|エラー/.test(document.querySelector('#sk-ln .st').textContent)"), True)
            chk("マイクなしでもキー操作は生きている",
                cdp.ev(sock, "(()=>{let n=0;document.addEventListener('keydown',()=>n++);"
                             "document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight'}));return n;})()"), 1)
            cdp.ev(sock, "window.MediaRecorder=undefined")
            cdp.ev(sock, "document.querySelector('#sk-ln .go').click()")
            time.sleep(0.6)
            chk("録音非対応でもスライドは無事", cdp.ev(sock, "document.querySelectorAll('.slide').length"), 3)
        finally:
            chrome.terminate()
    finally:
        try:
            os.remove(deck_path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logic", action="store_true", help="ブラウザ検証を省く")
    a = ap.parse_args()
    check_logic()
    if not a.logic:
        check_browser()
    print("結果:", "全OK" if not ng else f"NG {ng}")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
