#!/bin/sh
# 「Illustratorで保存.app」を作り直す（droplet.applescript → .app、nyuko_save.jsx を中に入れる）
set -e
cd "$(dirname "$0")"
APP="Illustratorで保存.app"
rm -rf _build && mkdir -p _build
# jsx の置き場（アプリの外にある時の最後の手）を書き込んでから組む
sed "s|__JSX_FALLBACK__|$(pwd)/nyuko_save.jsx|" droplet.applescript > _build/droplet.applescript
osacompile -o "_build/$APP" _build/droplet.applescript
osacompile -o "droplet.scpt" _build/droplet.applescript   # 検証用（osascript から load script で呼ぶ）
PL="_build/$APP/Contents/Info.plist"
cp nyuko_save.jsx "_build/$APP/Contents/Resources/nyuko_save.jsx"
# .ai と .pdf を受け取れるように書類の型を登録
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes array" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0 dict" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions array" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 string ai" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:1 string pdf" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" "$PL" 2>/dev/null || true
rm -rf "$APP"
mv "_build/$APP" "$APP"
rm -rf _build
echo "BUILT: $(pwd)/$APP"
