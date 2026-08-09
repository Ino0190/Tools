#!/bin/zsh
# CaptureKit.app 再ビルド（AppleScript変更後はこれを実行）
# バンドルID付与＋署名までやる。osacompile単体だとIDが無くて権限リストに出ない（2026-07-30の教訓）
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE"
osacompile -o CaptureKit.app capturekit-app.applescript
plutil -insert CFBundleIdentifier -string "local.capturekit.capturekit" CaptureKit.app/Contents/Info.plist
codesign --force --deep -s - CaptureKit.app
echo "OK: CaptureKit.app（local.capturekit.capturekit）"
