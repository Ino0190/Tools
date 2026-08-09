#!/usr/bin/env python3
"""Snagit自動同期の状態確認
使い方: python3 CaptureKit/sync-status.py
launchdエージェントの生存・最終実行・取り込み結果・未取込の有無をまとめて出す。
"""
import os, re, subprocess, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LABEL = 'local.capturekit.capturekit-snagit'
LOG = os.path.join(BASE, 'import-snagit.log')
SNAGIT = os.path.expanduser('~/Pictures/Snagit')
ng = 0

def line(mark, msg):
    print(f'{mark} {msg}')

def fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

# 1. launchdエージェント
r = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
row = next((l for l in r.stdout.splitlines() if LABEL in l), None)
if row:
    code = row.split()[1]
    if code == '0':
        line('✅', f'launchdエージェント動作中（{LABEL}・最終終了コード0）')
    else:
        line('❌', f'launchdエージェントの最終実行がエラー終了（コード{code}）。ログを見る')
        ng += 1
else:
    line('❌', f'launchdエージェント未ロード。再開: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{LABEL}.plist')
    ng += 1

# 2. 最終実行と結果（ログのmtime＋末尾のサマリ行）
if os.path.exists(LOG):
    mt = os.path.getmtime(LOG)
    with open(LOG, encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()
    summary = next((l for l in reversed(lines) if l.startswith('取り込み:')), '')
    line('✅', f'最終実行 {fmt(mt)}　{summary or "サマリ行なし"}')
    m = re.search(r'エラー: (\d+)件', summary)
    if m and int(m.group(1)) > 0:
        errs = [l for l in lines if l.startswith('NG:')]
        line('⚠️ ', f'エラー{m.group(1)}件（既知: 破損snagx。直近: {errs[-1][:80] if errs else "?"}）')
else:
    line('❌', 'import-snagit.log がない（まだ一度も実行されていない）')
    ng += 1

# 3. Snagit側に最終実行より新しいファイルがないか（＝未取込の検知）
if os.path.isdir(SNAGIT) and os.path.exists(LOG):
    log_mt = os.path.getmtime(LOG)
    newer = []
    for f in os.listdir(SNAGIT):
        if not f.lower().endswith(('.snagx', '.mp4', '.mov')):
            continue
        p = os.path.join(SNAGIT, f)
        if os.path.getmtime(p) > log_mt:
            newer.append(f)
    if newer:
        line('⚠️ ', f'最終実行より新しいSnagitファイルが{len(newer)}件（launchdが最短120秒間隔なので待てば入る。急ぐなら: launchctl kickstart gui/$(id -u)/{LABEL}）')
    else:
        line('✅', 'Snagit側に未取込なし')
elif not os.path.isdir(SNAGIT):
    line('⚠️ ', f'{SNAGIT} がない（Snagit未使用ならこの警告は無視してよい）')

# 4. カタログの更新時刻
cat = os.path.join(BASE, 'catalog-data.js')
if os.path.exists(cat):
    with open(cat, encoding='utf-8') as f:
        head = f.read(200)
    m = re.search(r'"updated":\s*"([^"]+)"', head)
    n = 0
    with open(cat, encoding='utf-8') as f:
        n = f.read().count('"file":')
    line('✅', f'カタログ {n}件（更新 {m.group(1) if m else "?"}）')
else:
    line('❌', 'catalog-data.js がない。node CaptureKit/scan.js を実行')
    ng += 1

print()
print('問題なし。SnagitとCaptureKitのギャラリーは共有されている' if ng == 0 else f'{ng}件の問題あり')
sys.exit(1 if ng else 0)
