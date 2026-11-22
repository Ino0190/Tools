-- Illustratorで保存.app — BezierKit の「入稿用 .ai 書き出し」で出た .ai（PDF互換）を落とすと、
-- Illustrator 2026 で開いてレイヤー（デザイン／カットライン／トンボ）を整え、色モードを合わせ、
-- 本物の Illustrator 形式で「<名前>（Illustrator）.ai」に保存する。元のファイルは変えない。
-- 結果は同じフォルダの「<名前>（Illustrator）.log.txt」にも残す。作り直し: nyuko/build_app.sh
-- 検証用: quiet を true にすると小窓を出さず CMYK で進む（cdp-check.py droplet が使う）

property quiet : false
property colorMode : "cmyk"
property jsxFallback : "__JSX_FALLBACK__"

on run
	if quiet then return
	display dialog "BezierKit で書き出した入稿用 .ai（または PDF）を、このアイコンに落としてください。" & return & return & "Illustrator 2026 で開いて、レイヤーを整え、本物の .ai で保存し直します。" buttons {"OK"} default button "OK" with title "Illustratorで保存"
end run

on jsxPath()
	set cands to {}
	try
		set end of cands to (POSIX path of (path to me)) & "Contents/Resources/nyuko_save.jsx"
	end try
	try
		set end of cands to (POSIX path of ((path to me) as alias)) & "/../nyuko_save.jsx"
	end try
	set end of cands to jsxFallback
	repeat with c in cands
		try
			do shell script "test -f " & quoted form of c
			return c as text
		end try
	end repeat
	error "nyuko_save.jsx が見つからない（" & jsxFallback & "）"
end jsxPath

on open theFiles
	set jsxBody to read (POSIX file (my jsxPath())) as «class utf8»
	if not quiet then
		-- 色モード。15秒で返事がなければ CMYK
		set modeAnswer to display dialog "色モードは？" & return & "CMYK＝ふつうの印刷（デザインの画像も Illustrator が変換）" & return & "RGB＝RGBデータ入稿オプションを使う時" buttons {"RGBのまま", "CMYK"} default button "CMYK" giving up after 15 with title "Illustratorで保存"
		set colorMode to "cmyk"
		if (gave up of modeAnswer) is false and (button returned of modeAnswer) is "RGBのまま" then set colorMode to "rgb"
	end if
	set results to {}
	repeat with f in theFiles
		set srcPath to POSIX path of f
		set lower to do shell script "printf %s " & quoted form of srcPath & " | tr 'A-Z' 'a-z'"
		if lower ends with ".ai" or lower ends with ".pdf" then
			set dstPath to my outName(srcPath)
			set prelude to "var NYUKO={src:" & my jsStr(srcPath) & ",dst:" & my jsStr(dstPath) & ",mode:" & my jsStr(colorMode) & ",cut:\"カットライン\",cutw:0.25};" & return
			set resLine to ""
			try
				with timeout of 600 seconds
					tell application id "com.adobe.illustrator"
						activate
						set r to do javascript (prelude & jsxBody)
					end tell
				end timeout
				set resLine to (my baseName(dstPath)) & "  ←  " & r
			on error errMsg
				set resLine to (my baseName(srcPath)) & "  ✗ " & errMsg
			end try
			set end of results to resLine
			try
				do shell script "printf '%s\\n' " & quoted form of resLine & " > " & quoted form of (my logName(dstPath))
			end try
		else
			set end of results to (my baseName(srcPath)) & "  ✗ .ai か .pdf だけ"
		end if
	end repeat
	if quiet then return
	set AppleScript's text item delimiters to return
	display dialog "保存しました（" & colorMode & "）:" & return & return & (results as text) buttons {"OK"} default button "OK" with title "Illustratorで保存"
	set AppleScript's text item delimiters to ""
end open

on stem(p)
	set dotPos to 0
	repeat with i from (count of p) to 1 by -1
		if character i of p is "." then
			set dotPos to i
			exit repeat
		end if
		if character i of p is "/" then exit repeat
	end repeat
	if dotPos is 0 then return p
	return text 1 thru (dotPos - 1) of p
end stem

on outName(p)
	return (my stem(p)) & "（Illustrator）.ai"
end outName

on logName(p)
	return (my stem(p)) & ".log.txt"
end logName

on baseName(p)
	set AppleScript's text item delimiters to "/"
	set n to last text item of p
	set AppleScript's text item delimiters to ""
	return n
end baseName

on jsStr(s)
	set AppleScript's text item delimiters to "\\"
	set parts to text items of s
	set AppleScript's text item delimiters to "\\\\"
	set s2 to parts as text
	set AppleScript's text item delimiters to "\""
	set parts to text items of s2
	set AppleScript's text item delimiters to "\\\""
	set s3 to parts as text
	set AppleScript's text item delimiters to ""
	return "\"" & s3 & "\""
end jsStr
