-- CaptureKit.app 本体（osacompileでビルド）
-- 開くとモード選択ダイアログ。Enter＝範囲撮影（スペースキーでウインドウ認識切替）
set base to "/PATH/TO/KitsRepo/CaptureKit/capture.sh"
activate
set d to display dialog "CaptureKit — 撮影モードを選ぶ（Enterで範囲撮影）" buttons {"録画", "クロップ", "撮影"} default button "撮影" with title "CaptureKit" giving up after 60
set b to button returned of d
if b is "撮影" then
	do shell script quoted form of base
else if b is "クロップ" then
	do shell script quoted form of base & " edit"
else if b is "録画" then
	do shell script quoted form of base & " video"
end if
