#!/bin/zsh
# CaptureKit 撮影スクリプト
# 使い方: capture.sh          … 範囲選択スクショ（デフォルト。ドラッグ中にスペースでウインドウ認識に切替）
#         capture.sh edit     … 撮影→プレビュー.appで開く（クロップ⌘K→⌘Sでshots内が更新される）
#         capture.sh window   … ウインドウ選択スクショ
#         capture.sh full     … 全画面スクショ
#         capture.sh video    … 画面録画（範囲選択→メニューバーの■で停止）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"  # アプリ経由（do shell script）でもnodeが見えるように
BASE="$(cd "$(dirname "$0")" && pwd)"
DIR="$BASE/shots/$(date +%Y-%m-%d)"
mkdir -p "$DIR"
TS=$(date +%H%M%S)

case "$1" in
  edit)
    FILE="$DIR/cap_${TS}.png"
    screencapture -i -P "$FILE"
    ;;
  video)
    FILE="$DIR/cap_${TS}.mov"
    screencapture -v "$FILE"
    ;;
  window)
    FILE="$DIR/cap_${TS}.png"
    screencapture -i -W "$FILE"
    ;;
  full)
    FILE="$DIR/cap_${TS}.png"
    screencapture "$FILE"
    ;;
  *)
    FILE="$DIR/cap_${TS}.png"
    screencapture -i "$FILE"
    ;;
esac

# キャンセル時（ファイルが無い）は何もしない
[ -f "$FILE" ] || exit 0

# 画像はクリップボードにもコピー（スライドの⌘V差し込み用）
# editモードはクロップ前の画像が入って紛らわしいのでコピーしない（クロップ後にプレビューで⌘A→⌘C）
if [[ "$FILE" == *.png && "$1" != "edit" ]]; then
  osascript -e "set the clipboard to (read (POSIX file \"$FILE\") as «class PNGf»)" 2>/dev/null
fi

# カタログ更新
if command -v node >/dev/null 2>&1; then
  node "$BASE/scan.js" >/dev/null 2>&1
fi

echo "$FILE"
