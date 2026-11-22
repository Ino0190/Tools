#!/usr/bin/env python3
"""Live Notes の録音を手元で文字起こしして、スライドごとの議事メモにする。

音声は外に出さない。手元の whisper（~/.local/bin/whisper）だけを使う。

    python3 SlideKit/livenotes_transcribe.py livenotes_20260911_1430.json
    python3 SlideKit/livenotes_transcribe.py livenotes_*.json --prompt "固有名詞 製品名 部署名"

    # 議事メモに仕上げる（仕分けのお願い付きMarkdownをクリップボードへ→Kiroに貼る）
    python3 SlideKit/livenotes_transcribe.py livenotes_*.json --for-ai --copy

    # ボイスメモの音声で救済する（Live Notes より2分早く回し始めた場合）
    python3 SlideKit/livenotes_transcribe.py livenotes_*.json --audio ~/rec.m4a --offset 120

モデルは turbo（large-v3-turbo・1.6GB）が既定。M3 Pro で音声の 0.66 倍の時間で終わり、
small では取り違える固有名詞（競技名→似た音の語、コーチ→工事）も正しく拾える。

やること:
  1. json と同じ場所の音声（webm/m4a）を ffmpeg で 16kHz mono wav に変換
  2. whisper にかけてセグメント（開始秒・終了秒・本文）を得る
  3. json のスライド切替ログと突き合わせ、各セグメントを当時のスライドへ割り当てる
  4. 手打ちメモと混ぜて時系列に並べ、Markdown と JSON を書き出す
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

WHISPER = os.path.expanduser("~/.local/bin/whisper")
AUDIO_EXT = (".webm", ".m4a", ".mp4", ".wav", ".mp3")


def find_audio(js_path, session, override=None):
    """json に書かれた音声名 → 同名の音声 → 同フォルダの近い名前、の順で探す。

    override を渡すとそれを使う（ボイスメモなど別アプリで録った音声で差し替える用）。
    """
    if override:
        if not os.path.exists(override):
            return None
        return os.path.abspath(override)
    d = os.path.dirname(os.path.abspath(js_path))
    named = session.get("audioFile")
    if named:
        p = os.path.join(d, named)
        if os.path.exists(p):
            return p
    base = os.path.splitext(os.path.basename(js_path))[0]
    for ext in AUDIO_EXT:
        p = os.path.join(d, base + ext)
        if os.path.exists(p):
            return p
    # ブラウザが (1) を付けて保存した場合などの救済
    for f in sorted(os.listdir(d)):
        if f.startswith(base) and f.lower().endswith(AUDIO_EXT):
            return os.path.join(d, f)
    return None


def to_wav(src, out):
    """whisper が扱いやすい 16kHz mono wav にする"""
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg が見つかりません（brew install ffmpeg）")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
           "-ac", "1", "-ar", "16000", "-vn", out]
    subprocess.run(cmd, check=True)
    return out


def run_whisper(wav, model, lang, workdir, prompt=None):
    """whisper を回して segments を返す。既に結果があれば作り直さない。

    注意: whisper の出力名は入力の拡張子を除いた名前で決まる。入力セッション
    json と同名になると自分の入力を認識結果として読んでしまうため、wav 名には
    _audio を付けてある（process 側）。念のため segments の有無も確かめる。
    """
    stem = os.path.splitext(os.path.basename(wav))[0]
    out_json = os.path.join(workdir, stem + ".json")
    cached = None
    if os.path.exists(out_json):
        try:
            with open(out_json, encoding="utf-8") as f:
                o = json.load(f)
            if isinstance(o, dict) and "segments" in o:
                cached = o["segments"]
        except (OSError, ValueError):
            cached = None
    if cached is not None:
        print(f"  既存の認識結果を使います: {os.path.basename(out_json)}")
        return cached
    if not os.path.exists(WHISPER):
        sys.exit(f"whisper が見つかりません: {WHISPER}")
    print(f"  文字起こし中（model={model}・長さによっては数分〜数十分）…")
    cmd = [WHISPER, wav, "--model", model, "--language", lang,
           "--output_format", "json", "--output_dir", workdir,
           "--verbose", "False"]
    # 固有名詞を先に教えると誤変換が減る（競技名→似た音の語、コーチ→工事 のような取り違え）
    if prompt:
        cmd += ["--initial_prompt", prompt]
    subprocess.run(cmd, check=True)
    with open(out_json, encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def slide_timeline(session):
    """録音開始からの経過msで「この区間はスライドN」の並びを作る"""
    marks = []
    for e in session.get("entries", []):
        if e.get("type") != "slide":
            continue
        at = e.get("atMs")
        if at is None:
            continue
        marks.append((max(0, at), e.get("slideIndex", 0), e.get("slideId") or ""))
    marks.sort(key=lambda m: m[0])
    if not marks or marks[0][0] > 0:
        # 録音開始直後の区間が無い場合は最初のスライドで埋める
        first = marks[0][1:] if marks else (0, "slide-1")
        marks.insert(0, (0,) + tuple(first))
    return marks


def slide_at(marks, at_ms):
    """その時刻に表示していたスライドを返す（切替後の発言は新しい方に付く）"""
    cur = marks[0]
    for m in marks:
        if m[0] <= at_ms:
            cur = m
        else:
            break
    return cur[1], cur[2]


def clock_of(session, at_ms):
    """録音開始時刻 + 経過ms → 14:03:21 形式"""
    from datetime import datetime, timedelta
    base = session.get("recordStartedAt") or session.get("startedAt")
    if not base:
        s = int(at_ms // 1000)
        return f"{s//3600:02d}:{(s//60)%60:02d}:{s%60:02d}"
    try:
        t = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(milliseconds=at_ms)
        return t.strftime("%H:%M:%S")
    except Exception:
        return ""


def build_entries(session, segments, offset_sec=0.0):
    """whisper のセグメントを transcript エントリにして、手打ちメモと合わせて時系列に並べる。

    offset_sec: 音声の先頭が Live Notes の録音開始より前に始まっている場合の差（秒）。
      別アプリ（ボイスメモ等）で録った音声を使うときに指定する。
    """
    marks = slide_timeline(session)
    out = []
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        at = int((float(seg.get("start", 0)) - offset_sec) * 1000)
        idx, sid = slide_at(marks, at)
        out.append({
            "id": f"tr-{i:04d}",
            "atMs": at,
            "clock": clock_of(session, at),
            "slideIndex": idx,
            "slideId": sid or f"slide-{idx+1}",
            "text": text,
            "speaker": None,
            "type": "transcript",
        })
    # 手打ちメモ・重要マークを混ぜる（録音中でなかったものは末尾扱い）
    for e in session.get("entries", []):
        if e.get("type") in ("memo", "mark"):
            out.append({
                "id": e.get("id"),
                "atMs": e.get("atMs") if e.get("atMs") is not None else 10 ** 12,
                "clock": e.get("clock") or "",
                "slideIndex": e.get("slideIndex", 0),
                "slideId": e.get("slideId") or "",
                "text": e.get("text", ""),
                "speaker": e.get("speaker"),
                "type": e.get("type"),
            })
    out.sort(key=lambda x: (x["atMs"], x["id"]))
    return out


def to_markdown(session, entries):
    from datetime import datetime
    started = session.get("startedAt", "")
    try:
        date = datetime.fromisoformat(started.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        date = started
    L = [f"# {session.get('title') or 'Presentation Notes'}", "",
         f"Date: {date}", f"Deck: {session.get('deck','')}", ""]
    memo_n = sum(1 for e in entries if e["type"] in ("memo", "mark"))
    tr_n = sum(1 for e in entries if e["type"] == "transcript")
    L += [f"文字起こし {tr_n} 件 / メモ {memo_n} 件", "", "---", ""]
    groups = {}
    for e in entries:
        groups.setdefault(e["slideIndex"], []).append(e)
    for idx in sorted(groups):
        items = groups[idx]
        sid = items[0].get("slideId") or f"slide-{idx+1}"
        L += [f"## Slide {idx+1}  `{sid}`", ""]
        for e in items:
            mark = {"mark": "★ ", "memo": "✎ "}.get(e["type"], "")
            L.append(e["clock"])
            L.append(mark + (f"{e['speaker']}：" if e.get("speaker") else "") + e["text"])
            L.append("")
    return "\n".join(L)


def to_ai_markdown(session, entries):
    """AI に仕分けを頼むための形。生の文字起こしのままでは議事録にならないので、
    お願いと出力の型を先頭に付けて、そのまま貼れる状態にする。"""
    from datetime import datetime
    try:
        date = datetime.fromisoformat(session.get("startedAt", "").replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        date = session.get("startedAt", "")
    L = [
        "# 議事メモの作成をお願いします", "",
        "プレゼン中の会話を、その時表示していたスライドごとに記録したものです。",
        "音声認識なので固有名詞や数字が崩れています。前後から推測して直してください。", "",
        "## お願い", "",
        "1. 発言を5つに仕分ける（**質問** / **懸念** / **決定事項** / **宿題・ToDo** / **修正要求・アイデア**）",
        "2. スライドごとに「この資料をどう直すべきか」の候補を挙げる",
        "3. 冗長な言い回しは削る。ただし発言の意味は変えない",
        "4. 聞き取りが怪しくて意味を確定できない箇所は `[要確認]` を付ける",
        "5. 誰の発言かは記録に無い。推測が付く場合だけ添え、分からなければ書かない", "",
        "## 出力してほしい形", "",
        "・箇条書きは「・」で始める。常体・体言止めで短く",
        "・決定事項と宿題は、期限や担当が読み取れる場合だけ添える",
        "・**スライド番号を必ず残す**（あとで資料を直すときの手がかりにする）",
        "・空疎な前置きと総括は書かない", "",
        "---", "",
        "## この記録について", "",
        f"・日時: {date}",
        f"・資料: {session.get('deck','')}"
        + (f"（{session.get('title')}）" if session.get("title") else ""),
        f"・記録: 文字起こし {sum(1 for e in entries if e['type']=='transcript')} 件"
        f" / 発表者メモ {sum(1 for e in entries if e['type'] in ('memo','mark'))} 件",
        "・`✎` と `★` は発表者がその場で打ったメモ（発言ではなく本人の書き込み）。`★` は本人が重要と判断したもの",
        "", "---", "",
    ]
    groups = {}
    for e in entries:
        groups.setdefault(e["slideIndex"], []).append(e)
    for idx in sorted(groups):
        items = groups[idx]
        L += [f"## Slide {idx+1}", ""]
        for e in items:
            mark = {"mark": "★ ", "memo": "✎ "}.get(e["type"], "")
            L.append(f"{e['clock']} {mark}{e['text']}")
        L.append("")
    return "\n".join(L)


def process(js_path, model, lang, keep_wav, prompt=None, audio_override=None, offset=0.0,
            for_ai=False, copy=False):
    print(f"■ {os.path.basename(js_path)}")
    with open(js_path, encoding="utf-8") as f:
        session = json.load(f)
    audio = find_audio(js_path, session, audio_override)
    if not audio:
        print("  音声が見つかりません。json と同じフォルダに .webm を置くか --audio で指定してください")
        return False
    print(f"  音声: {os.path.basename(audio)}" + (f"（--offset {offset:g}秒）" if offset else ""))
    if audio_override and not offset:
        print(f"  ヒント: この記録の録音開始は {session.get('recordStartedAt','?')} です。"
              "別アプリの音声なら、その録音開始からの差を --offset 秒 で渡してください")
    d = os.path.dirname(os.path.abspath(js_path))
    base = os.path.splitext(os.path.basename(js_path))[0]
    # _audio を付けるのは、whisper の出力 json が入力セッション json と同名に
    # なるのを避けるため（同名だと自分の入力を認識結果として読んでしまう）
    wav = os.path.join(d, base + "_audio.wav")
    made_wav = False
    if not audio.lower().endswith(".wav"):
        to_wav(audio, wav)
        made_wav = True
    else:
        wav = audio
    try:
        segments = run_whisper(wav, model, lang, d, prompt)
    finally:
        if made_wav and not keep_wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass
    entries = build_entries(session, segments, offset)
    md_path = os.path.join(d, base + "_notes.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(session, entries))
    session["entries"] = [e for e in session.get("entries", []) if e.get("type") == "slide"] + entries
    full = os.path.join(d, base + "_full.json")
    with open(full, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    if for_ai:
        ai_path = os.path.join(d, base + "_ai.md")
        ai_body = to_ai_markdown(session, entries)
        with open(ai_path, "w", encoding="utf-8") as f:
            f.write(ai_body)
        print(f"  → {os.path.basename(ai_path)}（AIに貼る用）")
        if copy:
            try:
                subprocess.run(["pbcopy"], input=ai_body, text=True, check=True)
                print("     クリップボードにコピーしました。そのまま貼れます")
            except (OSError, subprocess.CalledProcessError):
                print("     クリップボードへのコピーはできませんでした")
    slides = sorted(set(e["slideIndex"] for e in entries))
    print(f"  → {os.path.basename(md_path)} / {os.path.basename(full)}")
    print(f"  {len(entries)} 件・スライド {len(slides)} 枚分（{', '.join('S'+str(i+1) for i in slides[:12])}"
          + (" …" if len(slides) > 12 else "") + "）")
    return True


def main():
    ap = argparse.ArgumentParser(description="Live Notes の録音をローカルで文字起こしする")
    ap.add_argument("json", nargs="+", help="Live Notes が保存した .json")
    ap.add_argument("--model", default="turbo",
                    help="whisper モデル（既定 turbo=large-v3-turbo。速度はsmall並みで精度が高い）")
    ap.add_argument("--lang", default="ja", help="言語（既定 ja）")
    ap.add_argument("--keep-wav", action="store_true", help="変換した wav を残す")
    ap.add_argument("--prompt", default=None,
                    help="出てくる固有名詞を渡すと誤変換が減る（例: \"製品名 部署名 権限設計\"）")
    ap.add_argument("--audio", default=None,
                    help="別アプリで録った音声を使う（ボイスメモの m4a など）")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="--audio の音声が Live Notes の録音開始より何秒早く始まっているか")
    ap.add_argument("--for-ai", action="store_true",
                    help="質問・懸念・決定事項・宿題への仕分けを頼む形で _ai.md も出す")
    ap.add_argument("--copy", action="store_true", help="--for-ai の内容をクリップボードへ")
    a = ap.parse_args()
    ok = 0
    for p in a.json:
        if p.endswith("_full.json"):
            continue
        try:
            if process(p, a.model, a.lang, a.keep_wav, a.prompt, a.audio, a.offset,
                       a.for_ai, a.copy):
                ok += 1
        except subprocess.CalledProcessError as e:
            print(f"  失敗: {e}")
    print(f"完了: {ok}/{len(a.json)} 件")


if __name__ == "__main__":
    main()
