# 平安京アセットのリリース一括処理: 検証→JSON書き出しを1コマンドで。
# 使い方:
#   python3 heian-release.py                → heiantest＋#shinden検証→全アセット書き出し
#   python3 heian-release.py buraku daidairi → 検証→指定アセットだけ書き出し
#   python3 heian-release.py --skip-test daidairi → 検証を飛ばして書き出しのみ
# && で繋ぐ必要がないので、コマンド承認は1回で済む。
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "平安京", "models")
ASSETS = {
    "shinden1": "寝殿造1_一町_区画全部.json",
    "shinden2": "寝殿造2_半町_2分割.json",
    "shinden3": "寝殿造3_四分町_4分割.json",
    "shinden4": "寝殿造4_六分町_6分割.json",
    "shinden5": "寝殿造5_八分町_8分割.json",
    "machiya": "町家.json",
    "hottate": "掘立小屋.json",
    "rajomon": "羅城門.json",
    "chodoin": "朝堂院.json",
    "buraku": "豊楽院.json",
    "dairi": "内裏.json",
    "daidairi": "大内裏.json",
    "toji": "東寺.json",
    "saiji": "西寺.json",
    "korokan-east": "東鴻臚館.json",
    "korokan-west": "西鴻臚館.json",
}

def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    r = subprocess.run(cmd)
    return r.returncode == 0

args = [a for a in sys.argv[1:]]
skip_test = "--skip-test" in args
targets = [a for a in args if not a.startswith("--")] or list(ASSETS)
bad = [t for t in targets if t not in ASSETS]
if bad:
    print("HEIAN_RELEASE_FAIL 不明なアセット: " + " ".join(bad))
    sys.exit(1)

if not skip_test:
    print("== 検証: heiantest ==", flush=True)
    if not run("cdp-run.py", "heiantest"):
        print("HEIAN_RELEASE_FAIL heiantestが失敗（書き出し中止）")
        sys.exit(1)
    print("== 検証: heianterrain ==", flush=True)
    if not run("cdp-run.py", "heianterrain"):
        print("HEIAN_RELEASE_FAIL heianterrainが失敗（書き出し中止）")
        sys.exit(1)
    print("== 検証: heiangame ==", flush=True)
    if not run("cdp-run.py", "heiangame"):
        print("HEIAN_RELEASE_FAIL heiangameが失敗（書き出し中止）")
        sys.exit(1)
    for detail_target in ["buraku", "toji", "saiji", "korokan-east", "korokan-west"]:
        if detail_target in targets:
            print(f"== 検証: {detail_target} ==", flush=True)
            if not run("cdp-run.py", detail_target):
                print(f"HEIAN_RELEASE_FAIL {detail_target}が失敗（書き出し中止）")
                sys.exit(1)
    if any(t.startswith("shinden") for t in targets):
        print("== 検証: shinden ==", flush=True)
        if not run("cdp-run.py", "shinden"):
            print("HEIAN_RELEASE_FAIL shindenが失敗（書き出し中止）")
            sys.exit(1)

import time

fails = []
for t in targets:
    print(f"== 書き出し: {t} ==", flush=True)
    exported = run("export-model.py", t, os.path.join(OUT, ASSETS[t]))
    # export-modelの終了番犬が専用Chromeを停止してから次の書き出しを始める。
    time.sleep(2)
    if not exported:
        fails.append(t)

if fails:
    print("HEIAN_RELEASE_FAIL 書き出し失敗: " + " ".join(fails))
    sys.exit(1)
print(f"HEIAN_RELEASE_OK {len(targets)}アセット書き出し完了 → 平安京/models/")
