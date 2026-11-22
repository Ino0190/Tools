# CalcKit ヘッドレス検証（CDP直叩き・BezierKit cdp-check.pyの接続機構を流用）
#   python3 CalcKit/check.py
import importlib.util, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CDP_PORT", "9247")
spec = importlib.util.spec_from_file_location("cdpkit", os.path.join(HERE, "..", "BezierKit", "cdp-check.py"))
cdpkit = importlib.util.module_from_spec(spec)
_argv = sys.argv; sys.argv = [_argv[0]]
spec.loader.exec_module(cdpkit)
sys.argv = _argv

PORT = int(os.environ["CDP_PORT"])
PAGE = "file://" + os.path.join(HERE, "index.html")
PROFILE = "/tmp/calckit-check-profile"

def main():
    subprocess.run(["pkill", "-f", "calckit-check-profile"], capture_output=True)
    time.sleep(0.4)
    subprocess.run(["rm", "-rf", PROFILE])  # localStorageを毎回まっさらに（前回実行の残骸対策）
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                               f"--user-data-dir={PROFILE}", "--no-first-run", "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect()
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        deadline = time.time() + 15
        while time.time() < deadline:
            if ev(sock, "!!window.CalcKit && document.querySelectorAll('#grid-t td').length > 100"):
                break
            time.sleep(0.3)

        # 初期描画: デモ（収支計算）が入りグリッドが出る
        st = ev(sock, "({tds:document.querySelectorAll('#grid-t td').length,"
                      "name:window.CalcKit.doc.name,"
                      "sales:window.CalcKit.display('B10'),"
                      "profit:window.CalcKit.val('N21'),"
                      "rate:window.CalcKit.val('N22'),"
                      "cum1:window.CalcKit.val('B26'),"
                      "cum12:window.CalcKit.val('M26')})")
        assert st["tds"] > 400 and "収支" in st["name"], f"初期描画: {st}"
        assert st["sales"].startswith("¥") and st["profit"] > 0, f"デモが赤字（数字の筋が悪い）: {st}"
        assert 0.1 < st["rate"] < 0.45, f"利益率の筋が悪い: {st}"
        assert st["cum1"] < 0 < st["cum12"], f"初期投資の回収の筋（初月マイナス→年度内回収）: {st}"
        print(f"OK 初期描画 {st['name']} 4月売上={st['sales']} 通年営業利益=+{st['profit']:,.0f}"
              f"（利益率{st['rate']*100:.0f}%・初期投資480万は年度内回収）")

        # 借入返済: 利息は残りに対してかかる（残高再帰=素の式で組めることの実証）
        ln = ev(sock, "({i1:window.CalcKit.val('B24'),"       # 初月利息 300万×2.5%/12
                      "bal2:window.CalcKit.val('C23'),"       # 翌月期首 = 300万+利息-5万
                      "balEnd:window.CalcKit.val('N23'),"     # 期末残高
                      "intSum:window.CalcKit.val('N24')})")
        assert ln["i1"] == 6250 and ln["bal2"] == 2956250, f"借入計算: {ln}"
        assert 2400000 < ln["balEnd"] < 2500000 and 60000 < ln["intSum"] < 80000, f"借入年間: {ln}"
        print(f"OK 借入返済 初月利息¥{ln['i1']:,.0f}→残高¥{ln['bal2']:,.0f}"
              f"（期末残高¥{ln['balEnd']:,.0f}・年間利息¥{ln['intSum']:,.0f}）")

        # 式エンジン: 四則・関数・IF・SUMIF・比較・文字列連結・%・エラー
        fx = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('R1','2');K.setCell('R2','3');K.setCell('R3','=R1*R2+1');"
                      "K.setCell('R4','=SUM(R1:R3)');K.setCell('R5','=IF(R1>1,\"big\",\"small\")');"
                      "K.setCell('R6','=ROUND(3.14159,2)');K.setCell('R7','=AVERAGE(R1:R2)');"
                      "K.setCell('R8','=1/0');K.setCell('R9','=R9+1');"
                      "K.setCell('S1','=\"合計:\"&SUM(R1:R2)');K.setCell('S2','=50%');"
                      "K.setCell('S3','=SUMIF(R1:R2,\">2\")');K.setCell('S4','=UNKNOWNFN(1)');"
                      "return {m:K.val('R3'),s:K.val('R4'),i:K.val('R5'),r:K.val('R6'),a:K.val('R7'),"
                      "d:K.display('R8'),cy:K.display('R9'),cc:K.val('S1'),pc:K.val('S2'),"
                      "sif:K.val('S3'),nm:K.display('S4')};})()")
        assert fx["m"] == 7 and fx["s"] == 12 and fx["i"] == "big" and fx["r"] == 3.14, f"式: {fx}"
        assert fx["a"] == 2.5 and fx["d"] == "#DIV/0!" and fx["cy"] == "#CYCLE!", f"式2: {fx}"
        assert fx["cc"] == "合計:5" and fx["pc"] == 0.5 and fx["sif"] == 3 and fx["nm"] == "#NAME?", f"式3: {fx}"
        print("OK 式エンジン 四則/SUM/IF/ROUND/AVERAGE/SUMIF/連結/%・#DIV/0!・#CYCLE!・#NAME?")

        # IME の確定 Enter で確定しない（2026-11-15）: isComposing の Enter はセル編集を閉じない。通常の Enter で閉じる
        im = ev(sock, "(function(){var K=window.CalcKit;K.select('P28');"
                      "var ed=document.getElementById('cell-ed');"
                      "document.dispatchEvent(new KeyboardEvent('keydown',{key:'F2',bubbles:true,cancelable:true}));"
                      "ed.value='売上'; var disp0=getComputedStyle(ed).display;"
                      "ed.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}));"
                      "var still=getComputedStyle(ed).display!=='none';"
                      "ed.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:false,bubbles:true,cancelable:true}));"
                      "var closed=getComputedStyle(ed).display==='none';"
                      "return {disp0:disp0,still:still,closed:closed,v:K.val('P28')};})()")
        assert im["disp0"] != "none" and im["still"] and im["closed"] and im["v"] == "売上", f"IME Enter: {im}"
        print("OK IME 変換確定の Enter（isComposing）では編集を閉じず、通常の Enter で確定（P28=売上）")

        # 関数の追加（2026-11-14）: 論理・条件集計・INDEX/MATCH・日付・数値・文字
        f2 = ev(sock, "(function(){var K=window.CalcKit;"
                      # 小さな表: U1:W4 = 部署/区分/金額
                      "K.select('U1');K.pasteText('営業\\tA\\t100\\n営業\\tB\\t200\\n開発\\tA\\t300\\n開発\\tB\\t400');"
                      "K.setCell('X1','=IFERROR(1/0,\\\"x\\\")');K.setCell('X2','=IFERROR(2*3,\\\"x\\\")');"
                      "K.setCell('X3','=AND(1,2>1,TRUE)');K.setCell('X4','=OR(0,FALSE,1=2)');K.setCell('X5','=NOT(0)');"
                      "K.setCell('X6','=IFS(1>2,\\\"a\\\",2>1,\\\"b\\\")');"
                      "K.setCell('X7','=SUMIFS(W1:W4,U1:U4,\\\"営業\\\",V1:V4,\\\"B\\\")');"
                      "K.setCell('X8','=COUNTIFS(U1:U4,\\\"開発\\\",W1:W4,\\\">300\\\")');"
                      "K.setCell('X9','=AVERAGEIF(U1:U4,\\\"開発\\\",W1:W4)');"
                      "K.setCell('X10','=INDEX(W1:W4,MATCH(\\\"開発\\\",U1:U4,0))');"
                      "K.setCell('X11','=INDEX(U1:W4,2,3)');K.setCell('X12','=MATCH(250,W1:W4,1)');"
                      "K.setCell('X13','=SUMPRODUCT(W1:W2,W3:W4)');K.setCell('X14','=RANK(300,W1:W4)');"
                      "K.setCell('Y1','=YEAR(DATE(2026,11,14))');K.setCell('Y2','=MONTH(\\\"2026-11-14\\\")');K.setCell('Y3','=DAY(DATE(2026,11,14))');"
                      "K.setCell('Y4','=EOMONTH(DATE(2026,1,31),1)-DATE(2026,2,28)');"
                      "K.setCell('Y5','=EDATE(DATE(2026,1,31),1)-DATE(2026,2,28)');"
                      "K.setCell('Y6','=NETWORKDAYS(DATE(2026,11,2),DATE(2026,11,6))');"
                      "K.setCell('Y7','=WEEKDAY(DATE(2026,11,14))');K.setCell('Y8','=DAYS(DATE(2026,12,1),DATE(2026,11,1))');"
                      "K.setCell('Y9','=MOD(-7,3)');K.setCell('Y10','=POWER(2,10)');K.setCell('Y11','=CEILING(123,10)');K.setCell('Y12','=FLOOR(127,10)');K.setCell('Y13','=PRODUCT(W1:W2)');"
                      "K.setCell('Z1','=LEN(\\\"あいうえお\\\")');K.setCell('Z2','=MID(\\\"あいうえお\\\",2,3)');K.setCell('Z3','=LEFT(\\\"abc\\\",2)&RIGHT(\\\"abc\\\",1)');"
                      "K.setCell('Z4','=TEXT(1234.5,\\\"#,##0\\\")');K.setCell('Z5','=TEXT(0.256,\\\"0.0%\\\")');K.setCell('Z6','=TEXT(DATE(2026,3,5),\\\"yyyy/m/d\\\")');"
                      "K.setCell('Z7','=UPPER(TRIM(\\\"  ab  c \\\"))');K.setCell('Z8','=CONCATENATE(\\\"a\\\",1,\\\"b\\\")');K.setCell('Z9','=VALUE(\\\"1,200\\\")');"
                      "K.setCell('Z10','=ISBLANK(Z20)+ISNUMBER(W1)*10+ISTEXT(U1)*100');"
                      "var o={};['X1','X2','X3','X4','X5','X6','X7','X8','X9','X10','X11','X12','X13','X14',"
                      "'Y1','Y2','Y3','Y4','Y5','Y6','Y7','Y8','Y9','Y10','Y11','Y12','Y13','Z1','Z2','Z3','Z4','Z5','Z6','Z7','Z8','Z9','Z10']"
                      ".forEach(function(a){o[a]=K.val(a);}); return o;})()")
        exp = {"X1": "x", "X2": 6, "X3": 1, "X4": 0, "X5": 1, "X6": "b", "X7": 200, "X8": 1, "X9": 350, "X10": 300, "X11": 200,
               "X12": 2, "X13": 100*300+200*400, "X14": 2,
               "Y1": 2026, "Y2": 11, "Y3": 14, "Y4": 0, "Y5": 0, "Y6": 5, "Y7": 7, "Y8": 30, "Y9": 2, "Y10": 1024, "Y11": 130, "Y12": 120, "Y13": 20000,
               "Z1": 5, "Z2": "いうえ", "Z3": "abc", "Z4": "1,235", "Z5": "25.6%", "Z6": "2026/3/5", "Z7": "AB C", "Z8": "a1b", "Z9": 1200, "Z10": 111}
        bad = {k: (f2.get(k), v) for k, v in exp.items() if f2.get(k) != v}
        assert not bad, f"追加関数（セル: (実際, 期待)）: {bad}"
        print(f"OK 追加関数 {len(exp)}式（IFERROR/AND/OR/NOT/IFS・SUMIFS/COUNTIFS/AVERAGEIF・INDEX/MATCH・SUMPRODUCT/RANK・"
              "YEAR/MONTH/DAY/EOMONTH/EDATE/NETWORKDAYS/WEEKDAY/DAYS・MOD/POWER/CEILING/FLOOR/PRODUCT・LEN/MID/LEFT/RIGHT/TEXT/UPPER/TRIM/CONCATENATE/VALUE/IS*）")

        # C2: 幅に入らない数は「###」（2026-11-15）。全体値は title（ホバー）と数式バー(getRaw)で読める。文字セルはスピルのまま
        c2 = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.addSheet();var ni=K.activeSheet;"            # 空の新シート（colW 既定104）
                      "K.setCell('A1','¥1000000000');"                # 10億円は既定幅104pxに入らない
                      "var disp=K.display('A1');"
                      "var td=document.getElementById('c-0-0');"
                      "var clipped=td.textContent,title=td.title,ovf=td.classList.contains('ovf'),raw=K.getRaw('A1');"
                      "K.doc.sheets[ni].colW[0]=360;K.switchSheet(0);K.switchSheet(ni);"   # 列を広げて再描画→元に戻る
                      "var td2=document.getElementById('c-0-0');"
                      "var wide=td2.textContent,wideOvf=td2.classList.contains('ovf'),wideTitle=td2.title;"
                      "K.setCell('A2','これはとても長い日本語の文字列でセル幅をはみ出します');"
                      "var txtTd=document.getElementById('c-1-0');"
                      "K.switchSheet(0);"                             # 後続テストのため元の収支シートへ戻す
                      "return {disp:disp,clipped:clipped,title:title,ovf:ovf,raw:raw,"
                      "wide:wide,wideOvf:wideOvf,wideTitle:wideTitle,"
                      "txt:txtTd.textContent,txtSpill:txtTd.classList.contains('spill')};})()")
        assert "1,000,000,000" in c2["disp"], f"10億の表示: {c2}"
        assert c2["clipped"] == "###" and c2["ovf"] and c2["title"] == c2["disp"], f"入らない数が###になっていない: {c2}"
        assert c2["raw"] == "¥1000000000", f"数式バー(getRaw)で全体値が読める: {c2}"
        assert c2["wide"] == c2["disp"] and not c2["wideOvf"] and c2["wideTitle"] == "", f"列を広げたら元の数に戻る: {c2}"
        assert c2["txt"].startswith("これは") and c2["txtSpill"], f"文字セルは###にせずスピルのまま: {c2}"
        print("OK C2 幅に入らない数は###（ホバーと数式バーで全体値・列を広げれば復帰・文字セルはスピル維持）")

        # コピペの相対参照シフト: R3(=R1*R2+1)をT3に貼る→=T1*T2+1
        cp = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('T1','10');K.setCell('T2','20');"
                      "K.select('R3');K.copySel();K.select('T3');"
                      "K.pasteText(K.display('R3'));"
                      "return {raw:K.getRaw('T3'),v:K.val('T3')};})()")
        assert cp["raw"] == "=T1*T2+1" and cp["v"] == 201, f"コピペシフト: {cp}"
        print(f"OK コピペで相対参照シフト =R1*R2+1 → {cp['raw']} = {cp['v']}")

        # 行挿入で参照が追従: R4(=SUM(R1:R3))の行より上に挿入→SUM(R2:R4)
        ins = ev(sock, "(function(){var K=window.CalcKit;"
                       "K.insertRow(0);"
                       "var raw=K.getRaw('R5'),v=K.val('R5');"
                       "K.undo();"
                       "return {raw:raw,v:v,back:K.getRaw('R4')};})()")
        assert ins["raw"] == "=SUM(R2:R4)" and ins["v"] == 12, f"行挿入: {ins}"
        assert ins["back"] == "=SUM(R1:R3)", f"Undo復元: {ins}"
        print(f"OK 行挿入で式が追従 =SUM(R1:R3)→{ins['raw']}（⌘Zで復元も確認）")

        # 列削除で参照切れ→#REF!
        ref = ev(sock, "(function(){var K=window.CalcKit;"
                       "K.setCell('U1','5');K.setCell('V1','=U1*2');"
                       "K.deleteCol(20);"  # U列(index20)を削除
                       "var d=K.display('U1');"  # 旧V1がU1に繰り上がる
                       "K.undo();"
                       "return {d:d,back:K.val('V1')};})()")
        assert ref["d"] == "#REF!" and ref["back"] == 10, f"参照切れ: {ref}"
        print("OK 列削除で参照切れ→#REF!（Undoで復元）")

        # TSVペースト（Excelからの貼り付け想定）
        tsv = ev(sock, "(function(){var K=window.CalcKit;K.select('W1');"
                       "K.pasteText('a\\t1\\t2\\nb\\t3\\t4');"
                       "return {a:K.display('W1'),n:K.val('Y2')};})()")
        assert tsv["a"] == "a" and tsv["n"] == 4, f"TSV: {tsv}"
        print("OK TSVペースト（Excel相互運用の入口）")

        # Excel表示値の貼り付け: ¥1,234 / 50% は数値になり見た目も引き継ぐ・負の円は-¥表記
        xp = ev(sock, "(function(){var K=window.CalcKit;K.select('X1');"
                      "K.pasteText('¥1,234\\t50%');"
                      "K.setCell('X2','-5000');"
                      "var cs=K.doc.sheets[K.activeSheet].cells;"
                      "(cs['X2']||(cs['X2']={})).fmt='yen';K.recalcAll();"
                      "return {y:K.val('X1'),p:K.val('Y1'),dy:K.display('X1'),dp:K.display('Y1'),"
                      "neg:K.display('X2')};})()")
        assert xp["y"] == 1234 and xp["p"] == 0.5, f"表示値貼付: {xp}"
        assert xp["dy"] == "¥1,234" and xp["dp"] == "50%" and xp["neg"] == "-¥5,000", f"表示: {xp}"
        print("OK Excel表示値の貼り付け ¥1,234/50%→数値＋書式引き継ぎ・負の円は-¥5,000")

        # 書式: 円・%・太字
        fmt = ev(sock, "(function(){var K=window.CalcKit;"
                       "K.setCell('Z1','1234567');K.select('Z1');"
                       "document.getElementById('fyen').click();"
                       "return K.display('Z1');})()")
        assert fmt == "¥1,234,567", f"書式: {fmt}"
        print(f"OK 書式 円 {fmt}")

        # 編集UI: セルをダブルクリック→入力→Enterで確定
        # ※表の隙間や隣接セルに書くと塊が橋渡しされ最大塊テストが変わるので、孤立したA28を使う
        ui = ev(sock, "(async()=>{var K=window.CalcKit;K.select('A28');"
                      "var td=document.getElementById('c-27-0');"
                      "td.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));"
                      "await new Promise(r=>setTimeout(r,100));"
                      "var e=document.getElementById('cell-ed');"
                      "var shown=e.style.display==='block';"
                      "e.value='=2^10';"
                      "e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
                      "await new Promise(r=>setTimeout(r,100));"
                      "return {shown:shown,v:K.val('A28')};})()", await_promise=True)
        assert ui["shown"] and ui["v"] == 1024, f"編集UI: {ui}"
        print("OK 編集UI ダブルクリック→=2^10→Enter確定")

        # CSV
        csv = ev(sock, "window.CalcKit.buildCSV().split('\\n').length")
        assert csv >= 15, f"CSV行数: {csv}"
        print(f"OK CSV書き出し {csv}行")

        # SlideKit書き出し: data属性表・タイトル・フォント下限（収支表を明示選択）
        sl = ev(sock, "(function(){window.CalcKit.select('A3','N26');"
                      "var h=window.CalcKit.buildSlideHtml();"
                      "return {n:h.length,tb:h.indexOf('data-x=\"64\"')>0,"
                      "tbl:h.indexOf('<table data-x')>0,edit:h.indexOf('slide-edit.js')>0,"
                      "small:/data-font-size=\"(1[0-4]|[0-9])\"/.test(h)};})()")
        assert sl["tb"] and sl["tbl"] and sl["edit"] and not sl["small"], f"スライド: {sl}"
        print(f"OK SlideKit書き出し {sl['n']}bytes（data属性表＋slide-edit.js・15px未満なし）")

        # GanttKit書き出し: タスク表→TL_ITEMS
        gk = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.pasteText('');"  # no-op guard
                      "K.select('AA1');"
                      "K.pasteText('項目\\t開始\\t終了\\tグループ\\n現場調査\\t2026-08\\t2026-10\\t探索\\n"
                      "PoC構築\\t2026-10-15\\t2027-01\\t実装\\nレポート\\t2027-01\\t2027-03\\t探索');"
                      "K.select('AA1','AD4');"
                      "var js=K.buildGanttData({name:0,start:1,end:2,group:3,label:-1,desc:-1});"
                      "return js;})()")
        assert gk and "TL_ITEMS" in gk and "現場調査" in gk and "2026-10-15" in gk, f"ガント: {str(gk)[:200]}"
        assert gk.count('"id":"cat') == 2, f"カテゴリ数: {gk}"
        assert '"start":"2026-08"' in gk and "TL_CONFIG" in gk, f"設定: {gk[:200]}"
        print("OK GanttKit書き出し 3項目・2グループ・日付単位もそのまま")

        # DashboardKitグラフデータ: 先頭行=系列・先頭列=ラベル
        ch = ev(sock, "(function(){var K=window.CalcKit;K.select('AA1','AC4');"
                      "var d=K.buildChartData();"
                      "return {dk:!!window.DK,labels:d.labels.length,series:d.series.length};})()")
        assert ch["dk"], "DashboardKitが読めていない"
        print(f"OK DK連携 グラフデータ生成 labels={ch['labels']} series={ch['series']}")

        # 収支デモをグラフ化（数値系列が拾える・100万超は万円スケール）
        ch2 = ev(sock, "(function(){var K=window.CalcKit;K.select('A3','M7');"
                       "var d=K.buildChartData();"
                       "return {s:d.series.length,l:d.labels.length,unit:d.unit,"
                       "mx:Math.max.apply(null,d.series.map(function(e){return Math.max.apply(null,e.values)}))};})()")
        assert ch2["s"] >= 3 and ch2["l"] == 12, f"グラフ: {ch2}"  # 横長→行=系列・月=ラベル
        assert ch2["unit"] == "万円" and ch2["mx"] < 1000, f"万円スケール: {ch2}"
        print(f"OK 収支デモのグラフ化 系列{ch2['s']}・ラベル{ch2['l']}・万円表示（最大{ch2['mx']}）")

        # 単一セル選択→カーソル周辺の塊（カレント領域）でグラフ化。タイトル行や別の塊を食わない
        ch3 = ev(sock, "(function(){var K=window.CalcKit;K.select('C5');"
                       "var d=K.buildChartData();"
                       "return {s:d.series.length,l:d.labels.length,"
                       "names:d.series.map(function(e){return e.name}).join('|')};})()")
        assert ch3["l"] == 12 and 2 <= ch3["s"] <= 8, f"カレント領域: {ch3}"  # 合計列は自動除外→月×12
        assert "FitBase" not in ch3["names"], f"タイトル行が混入: {ch3}"
        assert "会員数" not in ch3["names"], f"円でない系列（人数）が万円軸に混入: {ch3}"
        print(f"OK カレント領域 単一セル→周辺の塊のみ・合計列除外・円系列のみ（{ch3['names']}）")

        # 孤立セル（A1タイトル）にカーソル→一番大きい塊を使う。系列名が列名(B,C,D…)にならない
        ch4 = ev(sock, "(function(){var K=window.CalcKit;K.select('A1');"
                       "var d=K.buildChartData();"
                       "return {s:d.series.length,names:d.series.map(function(e){return e.name}).join('|'),"
                       "l0:d.labels[0]};})()")
        assert "月会費売上" in ch4["names"] and "利益率" not in ch4["names"], f"最大塊: {ch4}"
        assert not any(n in ("B", "C", "D") for n in ch4["names"].split("|")), f"列名系列が残存: {ch4}"
        print(f"OK 孤立セルから→最大の塊（先頭ラベル={ch4['l0']}・系列に実名）")

        # 円グラフ: ヘッダ無しの費用行（家賃〜広告費）を選択→系列合計の構成比
        pi = ev(sock, "(function(){var K=window.CalcKit;K.select('A13','M18');"
                      "var p=K.buildPieData();"
                      "return {n:p.slices.length,names:p.slices.map(function(s){return s.name}).join('|'),"
                      "ok:p.slices.every(function(s){return s.value>0})};})()")
        assert pi["n"] == 6 and pi["names"].startswith("家賃|トレーナー人件費") and pi["ok"], f"円グラフ: {pi}"
        assert "機材修理・追加" in pi["names"], f"空欄あり行が拾えていない: {pi}"
        print(f"OK 円グラフ 費用の内訳6系列（系列合計の構成比・ヘッダ行なし/空欄月ありでも自動判定）")

        # テンプレート切替: 工数計算→単価表VLOOKUP＋レベルはプルダウン
        tp = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('cost');"
                      "return {name:K.doc.name,f8:K.display('G8'),b11:K.val('B11'),"
                      "vl:K.getRaw('C4'),c4:K.val('C4'),"
                      "opts:(function(){var c=K.doc.sheets[K.activeSheet].cells['B4'];"
                      "return (c&&c.opts||[]).length;})()};})()")
        assert tp["name"] == "工数計算" and tp["f8"].startswith("¥"), f"テンプレ: {tp}"
        assert "VLOOKUP" in tp["vl"] and tp["c4"] == 41720 and tp["opts"] == 4, f"単価表引き: {tp}"
        assert isinstance(tp["b11"], (int, float)) and tp["b11"] > 0, f"人月換算: {tp}"
        print(f"OK テンプレート 工数計算 合計={tp['f8']} 人月={tp['b11']:.2f}")

        # フィルダウン: 式コピー・2セル連番・テキスト連番・日付+1日
        fl = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('AF1','1');K.setCell('AF2','2');"        # 2セル数値→連番
                      "K.setCell('AG1','項目1');"                          # テキスト連番
                      "K.setCell('AH1','2026-08-14');"                     # 日付+1日
                      "K.setCell('AI1','100');K.setCell('AJ1','=AI1*2');"  # 式コピー
                      "K.select('AF1','AF2');K.fill('down',2);"
                      "K.select('AG1');K.fill('down',2);"
                      "K.select('AH1');K.fill('down',2);"
                      "K.setCell('AI2','7');K.setCell('AI3','9');"
                      "K.select('AJ1');K.fill('down',2);"
                      "return {n3:K.val('AF3'),n4:K.val('AF4'),"
                      "t2:K.display('AG2'),t3:K.display('AG3'),"
                      "d2:K.display('AH2'),d3:K.display('AH3'),"
                      "f2:K.getRaw('AJ2'),f3:K.val('AJ3')};})()")
        assert fl["n3"] == 3 and fl["n4"] == 4, f"数値連番: {fl}"
        assert fl["t2"] == "項目2" and fl["t3"] == "項目3", f"テキスト連番: {fl}"
        assert fl["d2"] == "2026-08-15" and fl["d3"] == "2026-08-16", f"日付フィル: {fl}"
        assert fl["f2"] == "=AI2*2" and fl["f3"] == 18, f"式フィル: {fl}"
        print("OK フィル 2セル連番1,2→3,4・項目1→2,3・日付+1日・式の相対シフト")

        # 単一の数値フィル: 既定はコピー（1セルでは連番か分からない）・⌥ドラッグで+1連番
        f1 = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('AE1','1');K.select('AE1');K.fill('down',3);"
                      "K.setCell('AC1','5');K.select('AC1');K.fill('down',2,true);"  # ⌥=連番
                      "return {cp:[K.val('AE2'),K.val('AE3'),K.val('AE4')].join(','),"
                      "alt:[K.val('AC2'),K.val('AC3')].join(',')};})()")
        assert f1["cp"] == "1,1,1", f"単一数値はコピー: {f1}"
        assert f1["alt"] == "6,7", f"⌥で連番: {f1}"
        print("OK 単一数値フィル 既定=コピー（1,1,1）・⌥ドラッグ=+1連番（5→6,7）")

        # 日付演算: 引き算で日数・DATE/TODAY
        dt = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('AK1','2026-08-01');K.setCell('AK2','2026-09-12');"
                      "K.setCell('AK3','=AK2-AK1');K.setCell('AK4','=DATE(2026,8,1)');"
                      "K.setCell('AK5','=TODAY()');"
                      "return {days:K.val('AK3'),date:K.val('AK4')===K.val('AK1'),"
                      "today:typeof K.val('AK5')==='number'};})()")
        assert dt["days"] == 42 and dt["date"] and dt["today"], f"日付演算: {dt}"
        print("OK 日付型 引き算42日・DATE()一致・TODAY()")

        # 並べ替え: ヘッダ付き表を数値列で降順→ヘッダは動かない・行の式も追従
        so = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.select('AM1');"
                      "K.pasteText('名前\\t点\\nすいか\\t30\\nりんご\\t90\\nばなな\\t60');"
                      "K.setCell('AO2','=AN2*2');K.setCell('AO3','=AN3*2');K.setCell('AO4','=AN4*2');"
                      "K.select('AM1','AO4');"
                      "K.sort(39,false);"  # AN列(index39)で降順
                      "return {h:K.display('AM1'),r1:K.display('AM2'),v1:K.val('AN2'),"
                      "r3:K.display('AM4'),f1:K.val('AO2'),fr:K.getRaw('AO2')};})()")
        assert so["h"] == "名前" and so["r1"] == "りんご" and so["v1"] == 90, f"ソート: {so}"
        assert so["r3"] == "すいか" and so["f1"] == 180 and so["fr"] == "=AN2*2", f"ソート式: {so}"
        print("OK 並べ替え 降順90/60/30・ヘッダ固定・行内の式が追従（=AN2*2→180）")

        # フィルタ: 見出しの▽で絞り込み（行を隠すだけ・式の値は動かない）→並べ替え→解除
        fl = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.select('AQ1');"
                      "K.pasteText('担当\\t件数\\n井内\\t3\\n西田\\t1\\n井内\\t5\\n山本\\t2\\n西田\\t4');"
                      "K.setCell('AS2','=SUM(AR2:AR6)');"
                      "K.select('AQ1','AR6');K.addFilter();"
                      "var btn=function(c){return [...document.querySelectorAll('.fh-btn')]"
                      ".find(function(b){return b.dataset.fc===String(c);});};"
                      "btn(42).click();"                     # AQ列=index42
                      "var rows=[...document.querySelectorAll('#fp-list .fp-row')];"
                      "var names=rows.map(function(e){return e.textContent;});"
                      "rows.find(function(e){return e.textContent.indexOf('西田')===0;})"
                      ".querySelector('input').click();"
                      "var tb=document.querySelector('#grid-t tbody');"
                      "var vis=[...tb.rows].slice(0,6).map(function(tr){return tr.style.display!=='none';});"
                      "return {btns:document.querySelectorAll('.fh-btn').length,names:names,vis:vis,"
                      "sum:K.val('AS2'),left:K.visibleRows(),hid:document.getElementById('st-flt').textContent};})()")
        assert fl["btns"] == 2 and len(fl["names"]) == 4, f"フィルタの▽とパネル: {fl}"
        assert fl["vis"] == [True, True, False, True, True, False], f"隠れる行: {fl}"
        assert fl["sum"] == 15 and fl["left"] == [2, 4, 5], f"式は絞り込みで動かない: {fl}"
        assert "2行" in fl["hid"], f"絞り込みの件数表示: {fl}"
        fl2 = ev(sock, "(function(){var K=window.CalcKit;"
                       "var btn=[...document.querySelectorAll('.fh-btn')]"
                       ".find(function(b){return b.dataset.fc==='43';});btn.click();"
                       "document.getElementById('fp-desc').click();"
                       "var col=[];for(var r=2;r<=6;r++)col.push(K.val('AR'+r));"
                       "var head=K.display('AQ1');"
                       "K.clearFilter();"
                       "var tb=document.querySelector('#grid-t tbody');"
                       "return {head:head,col:col,btns:document.querySelectorAll('.fh-btn').length,"
                       "hidden:[...tb.rows].filter(function(tr){return tr.style.display==='none';}).length,"
                       "cap:document.getElementById('c-0-42').textContent,"
                       "st:document.getElementById('st-flt').textContent};})()")
        assert fl2["head"] == "担当" and fl2["col"] == [5, 4, 3, 2, 1], f"フィルタ列の並べ替え: {fl2}"
        assert fl2["btns"] == 0 and fl2["hidden"] == 0, f"フィルタ解除: {fl2}"
        assert fl2["cap"] == "担当" and fl2["st"] == "", f"解除後の後片付け: {fl2}"
        print("OK フィルタ 見出しの▽で2行を隠す（SUM=15は不変）・その列で降順・解除で全表示に戻る")

        # VLOOKUP: 完全一致・見つからない→#N/A・近似（既定・昇順前提）・HLOOKUP
        vk = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('BA1','L6');K.setCell('BB1','41720');"
                      "K.setCell('BA2','L5');K.setCell('BB2','32092');"
                      "K.setCell('BA3','L4');K.setCell('BB3','22465');"
                      "K.setCell('BD1','10');K.setCell('BE1','100');"
                      "K.setCell('BD2','20');K.setCell('BE2','200');"
                      "K.setCell('BD3','30');K.setCell('BE3','300');"
                      "K.setCell('BC1','=VLOOKUP(\"L5\",BA1:BB3,2,0)');"
                      "K.setCell('BC2','=VLOOKUP(\"LX\",BA1:BB3,2,0)');"
                      "K.setCell('BC3','=VLOOKUP(25,BD1:BE3,2)');"
                      "K.setCell('BC4','=HLOOKUP(\"L5\",BA1:BB3,2,0)');"
                      "return {ex:K.val('BC1'),na:K.display('BC2'),ap:K.val('BC3')};})()")
        assert vk["ex"] == 32092 and vk["na"] == "#N/A" and vk["ap"] == 200, f"VLOOKUP: {vk}"
        print(f"OK VLOOKUP 完全一致32092・#N/A・近似25→200（既定は近似=Excel互換）")

        # 揃え: 右揃え・上揃えボタン→クラス反映
        al = ev(sock, "(function(){var K=window.CalcKit;K.setCell('BG1','x');K.select('BG1');"
                      "document.getElementById('far').click();"
                      "document.getElementById('fvt').click();"
                      "var td=document.querySelector('#grid-t td.cur');"
                      "return td.className;})()")
        assert "ar" in al and "vt" in al, f"揃え: {al}"
        print("OK 揃え 右揃え＋上揃えボタン→セルに反映")

        # プルダウン: 選択肢を設定→▾が出る→メニューから選ぶと値が入る
        dd = ev(sock, "(async()=>{var K=window.CalcKit;K.setCell('BH1','');K.select('BH1');"
                      "K.setOpts(['松','竹','梅']);K.select('BH1');"
                      "var b=document.getElementById('dd-btn');"
                      "var shown=b.style.display!=='none';"
                      "b.click();await new Promise(r=>setTimeout(r,100));"
                      "var items=document.querySelectorAll('#ctx button');"
                      "if(items.length)items[1].click();"
                      "await new Promise(r=>setTimeout(r,100));"
                      "return {shown:shown,n:items.length,v:K.val('BH1')};})()", await_promise=True)
        assert dd["shown"] and dd["n"] == 3 and dd["v"] == "竹", f"プルダウン: {dd}"
        print("OK プルダウン 選択肢3件→▾クリック→「竹」を選んで入力")

        # 折り返し: 長文セルに折返→行の高さが中身に合わせて伸びる
        wr = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.setCell('BJ1','長い説明文がセル幅を超えても折り返して全部見えるようにする機能の確認テキスト');"
                      "K.select('BJ1');"
                      "var td=document.querySelector('#grid-t td.cur');var h0=td.offsetHeight;"
                      "document.getElementById('fwrap').click();"
                      "td=document.querySelector('#grid-t td.cur');"
                      "return {h0:h0,h1:td.offsetHeight,cls:td.className.indexOf('wrap')>=0};})()")
        assert wr["cls"] and wr["h1"] > wr["h0"], f"折り返し: {wr}"
        print(f"OK 折り返し 行高{wr['h0']}px→{wr['h1']}px（中身に合わせて伸びる）")

        # 選択枠線: 範囲選択でsel-boxが選択範囲を囲う
        sb = ev(sock, "(function(){var K=window.CalcKit;K.select('B2','D5');"
                      "var b=document.getElementById('sel-box');"
                      "var a=document.getElementById('c-1-1'),z=document.getElementById('c-4-3');"
                      "return {disp:b.style.display,"
                      "l:parseInt(b.style.left)===a.offsetLeft,"
                      "w:parseInt(b.style.width)===(z.offsetLeft+z.offsetWidth-a.offsetLeft),"
                      "handle:!!document.getElementById('fill-handle')};})()")
        assert sb["disp"] == "block" and sb["l"] and sb["w"] and sb["handle"], f"選択枠線: {sb}"
        print("OK 選択枠線 範囲外周に青枠＋右下フィルハンドル")

        # タブ: 追加→シート間参照（日本語シート名）→名前変更で式が追従→削除
        tb = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('pl');"
                      "var t0=document.querySelectorAll('#tabs .tab').length;"  # 1シート＋「＋」
                      "K.addSheet();"
                      "K.setCell('A1','=収支!N21');"
                      "K.setCell('A2','=SUM(収支!B4:M4)');"
                      "var v1=K.val('A1'),v2=K.val('A2'),n21=K.valOn('収支','N21');"
                      "K.renameSheet(0,'PL');"
                      "var raw=K.getRaw('A1'),v3=K.val('A1');"
                      "var names=K.sheetNames().join('|');"
                      "K.renameSheet(0,'収支');"
                      "K.switchSheet(0);K.deleteSheet(1);"
                      "return {t0:t0,v1:v1,v2:v2,n21:n21,raw:raw,v3:v3,names:names,"
                      "ns:K.sheetNames().length,tabs:document.querySelectorAll('#tabs .tab').length};})()")
        assert tb["t0"] == 2 and tb["v1"] == tb["n21"] and tb["v2"] == 711, f"タブ/シート間参照: {tb}"
        assert tb["raw"] == "=PL!N21" and tb["v3"] == tb["n21"], f"名前変更の式追従: {tb}"
        assert "PL|シート2" in tb["names"] and tb["ns"] == 1 and tb["tabs"] == 2, f"シート削除: {tb}"
        print(f"OK タブ 追加→=収支!N21={tb['v1']:,.0f}・SUM(収支!B4:M4)=711・改名でPL!に式追従・削除で1枚に復帰")

        # シート越し参照は行挿入・コピペでシフトしない（固定扱い）
        sf = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.addSheet();K.setCell('B2','=収支!N21+B1');"
                      "K.insertRow(0);"
                      "var raw=K.getRaw('B3');"
                      "K.undo();K.switchSheet(0);K.deleteSheet(1);"
                      "return raw;})()")
        assert sf == "=収支!N21+B2", f"シート越し参照の固定: {sf}"
        print("OK シート越し参照は行挿入でシフトしない（=収支!N21は固定・B1→B2は追従）")

        # シート削除で参照切れ→#REF!（評価時に検出）
        dl = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.addSheet();K.setCell('A1','7');"
                      "K.switchSheet(0);K.setCell('AS1','=シート2!A1*3');"
                      "var v0=K.val('AS1');"
                      "K.deleteSheet(1);"
                      "var d=K.display('AS1');"
                      "K.setCell('AS1','');"
                      "return {v0:v0,d:d};})()")
        assert dl["v0"] == 21 and dl["d"] == "#REF!", f"シート削除の参照: {dl}"
        print("OK シート間参照 =シート2!A1*3=21→シート削除で#REF!")

        # 保存往復: localStorage→リロードで復元
        ev(sock, "(function(){var K=window.CalcKit;K.setCell('A25','リロード確認');})()")
        time.sleep(1.0)  # autosave debounce
        call(sock, "Page.enable")
        call(sock, "Page.reload")
        time.sleep(2.5)
        rl = ev(sock, "window.CalcKit && window.CalcKit.display('A25')")
        assert rl == "リロード確認", f"保存往復: {rl}"
        print("OK 保存往復 localStorage→リロード復元")

        # 旧形式（単一シートJSON）の移行: 読めてタブが1枚できる
        ev(sock, "localStorage.setItem('calckit_v1',JSON.stringify("
                 "{name:'旧形式',rows:10,cols:5,cells:{A1:{v:'42'},A2:{v:'=A1*2'}}}))")
        call(sock, "Page.reload")
        time.sleep(2.5)
        mg = ev(sock, "({v:window.CalcKit.val('A2'),names:window.CalcKit.sheetNames().join('|'),"
                      "name:window.CalcKit.doc.name})")
        assert mg["v"] == 84 and mg["names"] == "シート1" and mg["name"] == "旧形式", f"旧形式移行: {mg}"
        print("OK 旧形式JSONの自動移行（単一シート→sheets形式）")

        print("CALCKIT_OK 全項目通過")
    finally:
        chrome.terminate()


# --- SlideKit往復: skCalcReturnがあると青ボタンが出て、押すとskCalcSlideに1枚分書く ---
def slidekit_roundtrip():
    subprocess.run(["pkill", "-f", "calckit-sk-profile"], capture_output=True)
    time.sleep(0.4)
    subprocess.run(["rm", "-rf", "/tmp/calckit-sk-profile"])
    port2 = PORT + 24   # 他キットの残留ヘッドレスChromeとポードが被らない位置に
    old = cdpkit.PORT; cdpkit.PORT = port2
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port2}",
                               "--user-data-dir=/tmp/calckit-sk-profile", "--no-first-run",
                               "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        time.sleep(3)
        url = ev(sock, "location.href")
        assert url and "CalcKit" in url, f"接続先が違う（残留Chromeのポート衝突）: {url}"
        # SlideKitから開かれた状況を作る→リロード→青ボタン→クリック→ペイロード検証
        ev(sock, "localStorage.setItem('skCalcReturn',JSON.stringify({deck:'file:///tmp/fake-deck.html',ts:Date.now()}))")
        call(sock, "Page.enable"); call(sock, "Page.reload")
        time.sleep(2.5)
        rt = ev(sock, "(function(){var b=document.getElementById('bslidekit');"
                      "if(!b)return {btn:false};"
                      "window.CalcKit.select('A3','N10');b.click();"
                      "document.getElementById('sk-kind').value='table';"
                      "document.getElementById('m-go').click();"
                      "var p=JSON.parse(localStorage.getItem('skCalcSlide')||'null');"
                      "return {btn:true,deck:p&&p.deck,ok:p&&p.html.indexOf('<table')>=0&&p.html.indexOf('data-x')>=0,"
                      "slide:p&&p.html.indexOf('class=\"slide\"')>=0};})()")
        assert rt["btn"] and rt["deck"] == "file:///tmp/fake-deck.html" and rt["ok"] and rt["slide"], f"往復: {rt}"
        print("OK SlideKit往復（CalcKit側）青ボタン→形式=表→skCalcSlideに表スライド1枚分")

        # グラフ形式: SVGが焼き込まれ・CSS変数が残らない・凡例テキストつき
        rg = ev(sock, "(function(){var K=window.CalcKit;K.select('A3','M7');"
                      "localStorage.removeItem('skCalcSlide');"
                      "document.getElementById('bslidekit').click();"
                      "document.getElementById('sk-kind').value='bar';"
                      "document.getElementById('m-go').click();"
                      "var p=JSON.parse(localStorage.getItem('skCalcSlide')||'null');"
                      "return {svg:p&&p.html.indexOf('<svg')>=0,"
                      "novar:p&&p.html.indexOf('var(--dk')<0,"
                      "legend:p&&p.html.indexOf('月会費売上')>=0,"
                      "wrap:p&&p.html.indexOf('data-w')>=0};})()")
        assert rg["svg"] and rg["novar"] and rg["legend"] and rg["wrap"], f"グラフ往復: {rg}"
        print("OK SlideKit往復（CalcKit側）形式=グラフ→SVG焼き込み・テーマ色解決済み・凡例つき")
    finally:
        chrome.terminate()

    # SlideKit側: insertCalcSlideでデッキに1枚増える
    subprocess.run(["pkill", "-f", "calckit-sk2-profile"], capture_output=True)
    time.sleep(0.4)
    port3 = PORT + 25
    deck = "file://" + os.path.normpath(os.path.join(HERE, "..", "SlideKit", "slide-template.html"))
    old = cdpkit.PORT; cdpkit.PORT = port3
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port3}",
                               "--user-data-dir=/tmp/calckit-sk2-profile", "--no-first-run",
                               "--window-size=1600,900", deck],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        deadline = time.time() + 12
        while time.time() < deadline:
            if ev(sock, "!!(window.SlideKit && window.SlideKit.insertCalcSlide)"):
                break
            time.sleep(0.4)
        url = ev(sock, "location.href")
        assert url and "slide-template" in url, f"接続先が違う（残留Chromeのポート衝突）: {url}"
        r = ev(sock, "(function(){if(!window.SlideKit||!window.SlideKit.insertCalcSlide)return {api:false};"
                     "var n0=document.querySelectorAll('.slide').length;"
                     "var ok=window.SlideKit.insertCalcSlide('<html><body><div class=\"slide\" data-bg=\"#fafafa\">"
                     "<table data-x=\"64\" data-y=\"120\" data-w=\"1152\"><tr><td>往復テスト</td></tr></table></div></body></html>');"
                     "return {api:true,ok:ok,n0:n0,n1:document.querySelectorAll('.slide').length};})()")
        assert r["api"] and r["ok"] and r["n1"] == r["n0"] + 1, f"SlideKit側: {r}"
        print(f"OK SlideKit往復（デッキ側）insertCalcSlideで{r['n0']}→{r['n1']}枚")
    finally:
        chrome.terminate()


# --- 実運用シナリオ（2026-07-31の探索テストを常設化） ---
def scenarios():
    subprocess.run(["pkill", "-f", "calckit-scn-profile"], capture_output=True)
    time.sleep(0.4)
    subprocess.run(["rm", "-rf", "/tmp/calckit-scn-profile"])
    port4 = PORT + 26
    old = cdpkit.PORT; cdpkit.PORT = port4
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port4}",
                               "--user-data-dir=/tmp/calckit-scn-profile", "--no-first-run",
                               "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    slide_tmp = "/tmp/calckit-scn-slide.html"
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        time.sleep(3)
        url = ev(sock, "location.href")
        assert url and "CalcKit" in url, f"接続先が違う: {url}"

        # 単価表の改定が全行に効く（工数テンプレの本来の使い方）
        r = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('cost');"
                     "var g0=K.val('G8');K.setCell('J4','50000');"
                     "return {g0:g0,g1:K.val('G8'),c4:K.val('C4')};})()")
        assert r["c4"] == 50000 and r["g1"] > r["g0"], f"単価改定: {r}"
        print(f"OK 単価表の改定→VLOOKUP経由で全行に反映 合計{r['g0']:,}→{r['g1']:,}")

        # 日付エッジ: 月末+1日=翌月1日・うるう年・12月→1月循環
        r = ev(sock, "(function(){var K=window.CalcKit;"
                     "K.setCell('CA1','2026-01-31');K.select('CA1');K.fill('down',1);"
                     "K.setCell('CB1','2028-02-28');K.select('CB1');K.fill('down',1);"
                     "K.setCell('CC1','12月');K.select('CC1');K.fill('down',2);"
                     "return {m:K.display('CA2'),leap:K.display('CB2'),"
                     "dec:K.display('CC2')+'/'+K.display('CC3')};})()")
        assert r["m"] == "2026-02-01" and r["leap"] == "2028-02-29" and r["dec"] == "1月/2月", f"日付エッジ: {r}"
        print("OK 日付エッジ 月末+1=翌月1日・うるう年2/29・12月→1月循環")

        # 逆方向フィル（上=線形の逆外挿・左右の式シフト）
        r = ev(sock, "(function(){var K=window.CalcKit;"
                     "K.setCell('CE5','10');K.setCell('CE6','20');K.select('CE5','CE6');K.fill('up',2);"
                     "K.setCell('CG1','=CE5*2');K.select('CG1');K.fill('right',2);"
                     "return {up:K.val('CE3')+'/'+K.val('CE4'),right:K.getRaw('CH1')};})()")
        assert r["up"] == "-10/0" and r["right"] == "=CF5*2", f"逆方向フィル: {r}"
        print("OK 逆方向フィル 上=逆外挿0,-10・右=式シフト")

        # 返済額の感度: 5万→10万で期末残高が減る（残高再帰の生きた検証）
        r = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('pl');"
                     "var b0=K.val('N23');"
                     "for(var i=1;i<12;i++){var L=String.fromCharCode(66+i);"
                     "K.setCell(L+'23','='+String.fromCharCode(65+i)+'23+'+String.fromCharCode(65+i)+'24-100000');}"
                     "K.setCell('N23','=M23+M24-100000');"
                     "return {b0:b0,b1:K.val('N23')};})()")
        assert r["b1"] < r["b0"] - 500000, f"返済額感度: {r}"
        print(f"OK 返済額の感度 5万→10万で期末残高 {r['b0']:,}→{r['b1']:,}")

        # 性能: 200行×3列の式ペーストが3秒以内・値が正しい
        r = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('blank');"
                     "var t0=performance.now();"
                     "var rows=[];for(var i=1;i<=200;i++)rows.push(i+'\\t=A'+i+'*2\\t=SUM(B1:B'+i+')');"
                     "K.pasteText(rows.join('\\n'));"
                     "return {ms:Math.round(performance.now()-t0),last:K.val('C200')};})()")
        assert r["ms"] < 3000 and r["last"] == 40200, f"性能: {r}"
        print(f"OK 性能 200行×3列の式ペースト {r['ms']}ms・C200={r['last']:,}")

        # スライド書き出し→run_check→PPTX変換→python-pptx再保存（パイプライン全通し）
        h = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('pl');"
                     "K.select('A3','N10');return K.buildSlideHtml();})()")
        with open(slide_tmp, "w") as f:
            f.write(h)
        rc = subprocess.run(["python3", os.path.join(HERE, "..", "SlideKit", "run_check.py"), slide_tmp],
                            capture_output=True, text=True)
        assert "問題なし" in rc.stdout, f"run_check: {rc.stdout[-200:]}"
        cv = subprocess.run(["python3", os.path.join(HERE, "..", "SlideKit", "html_to_pptx.py"), slide_tmp],
                            capture_output=True, text=True)
        assert "Saved:" in cv.stdout, f"変換: {cv.stdout[-200:]} {cv.stderr[-200:]}"
        pptx = slide_tmp.replace(".html", ".pptx")
        rs = subprocess.run(["python3", "-c",
                             f"from pptx import Presentation; p=Presentation('{pptx}'); p.save('{pptx}'); print('resave-ok')"],
                            capture_output=True, text=True)
        assert "resave-ok" in rs.stdout, f"再保存: {rs.stderr[-200:]}"
        print("OK PPTXパイプライン run_check問題なし→変換→再保存")

        # グラフスライドもPPTX変換を全通し（SVG→PNG化・MISSINGが出ないこと）
        h2 = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('pl');"
                      "K.select('A3','M7');return K.buildChartSlideHtml('bar');})()")
        with open(slide_tmp, "w") as f:
            f.write(h2)
        cv2 = subprocess.run(["python3", os.path.join(HERE, "..", "SlideKit", "html_to_pptx.py"), slide_tmp],
                             capture_output=True, text=True)
        assert "Saved:" in cv2.stdout and "MISSING" not in cv2.stdout, f"グラフ変換: {cv2.stdout[-300:]}"
        print("OK グラフスライドのPPTX変換（SVG→PNG配置・欠落なし）")
        print("SCENARIOS_OK 実運用シナリオ通過")
    finally:
        chrome.terminate()
        for p in (slide_tmp, slide_tmp.replace(".html", ".pptx")):
            if os.path.exists(p):
                os.remove(p)
        subprocess.run(["rm", "-rf", slide_tmp.replace(".html", "_svg")])  # 変換器の単体SVG書き出し


# --- GanttKit往復: 表→ガント（#fromCalc）→表（#fromGantt） ---
def gantt_roundtrip():
    port5 = PORT + 27
    prof = "/tmp/calckit-gk-profile"
    subprocess.run(["pkill", "-f", "calckit-gk-profile"], capture_output=True)
    time.sleep(0.4)
    subprocess.run(["rm", "-rf", prof])
    gantt = "file://" + os.path.normpath(os.path.join(HERE, "..", "GanttKit", "index.html"))
    old = cdpkit.PORT; cdpkit.PORT = port5
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port5}",
                               f"--user-data-dir={prof}", "--no-first-run",
                               "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        time.sleep(3)
        assert "CalcKit" in ev(sock, "location.href")

        # CalcKitでタスク表を作り、ガント用ペイロードをlocalStorageへ（「GanttKitで開く」相当）
        pl = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('blank');K.select('A1');"
                      "K.pasteText('項目\\t開始\\t終了\\tグループ\\n現場調査\\t2026-08-01\\t2026-10-31\\t探索\\n"
                      "PoC構築\\t2026-10-15\\t2027-01-31\\t実装');"
                      "K.select('A1','D3');"
                      "var d=K.buildGanttPayload({name:0,start:1,end:2,group:3,label:-1,desc:-1});"
                      "localStorage.setItem('ckGanttData',JSON.stringify({data:d,ts:Date.now()}));"
                      "return {items:d.items.length,cats:d.categories.length,start:d.config.start};})()")
        assert pl["items"] == 2 and pl["cats"] == 2 and pl["start"] == "2026-08", f"ペイロード: {pl}"
        print(f"OK GanttKit往復（CalcKit側）表2行→ガントデータ（グループ{pl['cats']}・開始{pl['start']}）")

        # 同プロファイルでGanttKitを#fromCalcで開く→取り込まれる
        call(sock, "Page.enable")
        call(sock, "Page.navigate", {"url": gantt + "#fromCalc"})
        time.sleep(4)
        gk = ev(sock, "({items:window.TL_ITEMS.length,names:window.TL_ITEMS.map(function(i){return i.name}).join('|'),"
                      "cats:window.TL_CATEGORIES.map(function(c){return c.name}).join('|'),"
                      "ms:window.TL_MILESTONES.length,left:localStorage.getItem('ckGanttData')})")
        assert gk["items"] == 2 and "現場調査" in gk["names"], f"ガント取り込み: {gk}"
        assert "探索" in gk["cats"] and gk["ms"] == 0 and gk["left"] is None, f"取り込み内容: {gk}"
        print(f"OK GanttKit往復（Gantt側）#fromCalcで取り込み（{gk['names']}／グループ {gk['cats']}）")

        # ガント側で「表(CalcKit)で開く」→ CalcKitのシート形式ペイロードを作る
        bk = ev(sock, "(function(){var d=window.GanttKit.buildCalcSheet();"
                      "localStorage.setItem('gkCalcSheet',JSON.stringify({doc:d,ts:Date.now()}));"
                      "var cs=d.sheets[0].cells;"
                      "return {sheets:d.sheets.length,name:d.name,hdr:cs['A3'].v+cs['B3'].v,"
                      "b4:cs['B4'].v,d4:cs['D4'].v,f4:cs['F4'].v};})()")
        assert bk["sheets"] >= 1 and bk["hdr"] == "グループ項目", f"表化: {bk}"
        assert bk["d4"] == "2026-08-01" and bk["f4"] == "=E4-D4+1", f"表化の内容: {bk}"
        print(f"OK GanttKit往復（Gantt側）buildCalcSheet 日数=式・日付展開（{bk['b4']} {bk['d4']}）")

        # CalcKitを#fromGanttで開く→表として読み込まれ、日数の式が計算される
        call(sock, "Page.navigate", {"url": PAGE + "#fromGantt"})
        time.sleep(3.5)
        ck = ev(sock, "({name:window.CalcKit.doc.name,sheets:window.CalcKit.sheetNames().join('|'),"
                      "b4:window.CalcKit.display('B4'),days:window.CalcKit.val('F4'),"
                      "left:localStorage.getItem('gkCalcSheet'),hash:location.hash})")
        assert ck["b4"] == "現場調査" and ck["days"] == 92, f"表として開く: {ck}"   # 8/1〜10/31=92日
        assert ck["left"] is None and ck["hash"] == "", f"二重取り込み対策: {ck}"
        print(f"OK GanttKit往復（CalcKit側）#fromGanttで表化（{ck['b4']}・日数{ck['days']}日・シート {ck['sheets']}）")

        # 進捗%・控え開始/終了も往復で落とさない（2026-11-14）: 表に I〜L 相当の列 → ペイロードに progress・baselines
        pl2 = ev(sock, "(function(){var K=window.CalcKit;K.loadTemplate('blank');K.select('A1');"
                       "K.pasteText('項目\\t開始\\t終了\\tグループ\\t進捗%\\t控え開始\\t控え終了\\n"
                       "現場調査\\t2026-08-01\\t2026-11-15\\t探索\\t60\\t2026-08-01\\t2026-10-31\\n"
                       "PoC構築\\t2026-10-15\\t2027-01-31\\t実装\\t\\t\\t');"
                       "K.select('A1','G3');"
                       "var d=K.buildGanttPayload({name:0,start:1,end:2,group:3,label:-1,desc:-1,assignee:-1,progress:4,bstart:5,bend:6});"
                       "localStorage.setItem('ckGanttData',JSON.stringify({data:d,ts:Date.now()}));"
                       "var js=K.buildGanttData({name:0,start:1,end:2,group:3,label:-1,desc:-1,assignee:-1,progress:4,bstart:5,bend:6});"
                       "return {p0:d.items[0].versions[0].progress,p1:(d.items[1].versions[0].progress===undefined?null:d.items[1].versions[0].progress),"
                       "bl:d.baselines.length,b0:d.baselines[0]&&d.baselines[0].items.ck1[0].end,"
                       "b1:!!(d.baselines[0]&&d.baselines[0].items.ck2),js:js.indexOf('TL_BASELINES')>0};})()")
        assert pl2["p0"] == 60 and pl2["p1"] is None, f"進捗の読み: {pl2}"
        assert pl2["bl"] == 1 and pl2["b0"] == "2026-10-31" and pl2["b1"] is False and pl2["js"], f"控えの読み: {pl2}"
        print(f"OK GanttKit往復（CalcKit側）進捗%→progress・控え開始/終了→baselines（控え終了 {pl2['b0']}・データjsにも TL_BASELINES）")
        call(sock, "Page.navigate", {"url": gantt + "#fromCalc"})
        time.sleep(4)
        gk2 = ev(sock, "(function(){var cs=window.GanttKit.buildCalcSheet().sheets[0].cells;"
                       "return {bl:window.TL_BASELINES.length,prog:window.TL_ITEMS[0].versions[0].progress,"
                       "hdrK:cs['K3'].v,k4:cs['K4'].v,l4:cs['L4'].v,i4:cs['I4'].v};})()")
        assert gk2["bl"] == 1 and gk2["prog"] == 60, f"ガント側の控え・進捗: {gk2}"
        assert gk2["hdrK"] == "遅れ日数" and gk2["k4"] == "15" and gk2["l4"] == "60" and gk2["i4"] == "2026-08-01", f"表に戻した控え列: {gk2}"
        print(f"OK GanttKit往復（Gantt側）控え1本・進捗60 → 表に戻すと 遅れ日数 +{gk2['k4']}・進捗% {gk2['l4']}")
        print("GANTT_ROUNDTRIP_OK 表⇄ガントの往復通過")
    finally:
        chrome.terminate()


# --- .xlsx 読み込み: SheetJSで書いて読む往復（複数シート・式・日付・列幅） ---
def xlsx_import():
    subprocess.run(["pkill", "-f", "calckit-xlsx-profile"], capture_output=True)
    time.sleep(0.4)
    prof = "/tmp/calckit-xlsx-profile"
    subprocess.run(["rm", "-rf", prof])
    port6 = PORT + 28
    old = cdpkit.PORT; cdpkit.PORT = port6
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port6}",
                               f"--user-data-dir={prof}", "--no-first-run", "--mute-audio",
                               "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        deadline = time.time() + 15
        while time.time() < deadline:
            if ev(sock, "!!(window.CalcKit && window.XLSX && window.XLSX.utils)"):
                break
            time.sleep(0.3)
        assert ev(sock, "!!window.XLSX"), "SheetJS(xlsx.full.min.js)が読み込めていない"

        # SheetJSで複数シート・式（対応/非対応）・日付・列幅を持つxlsxを書き、importXlsxで取り込む
        r = ev(sock, "(function(){var X=window.XLSX,K=window.CalcKit;"
                     "var ws1=X.utils.aoa_to_sheet([['月','額'],['4月',100],['5月',200]]);"
                     "ws1['B4']={t:'n',f:'SUM(B2:B3)'};"                           # 対応関数→生きた式
                     "var ser=Math.round(Date.UTC(2026,7,14)/86400000)+25569;"     # 2026-08-14のExcelシリアル
                     "ws1['A5']={t:'n',v:ser,z:'yyyy-mm-dd'};"                     # 日付書式→日付型へ
                     "ws1['B5']={t:'s',f:'CONCATENATE(\"x\",B4)',v:'x300',w:'x300'};"  # 非対応関数→値に落ちる
                     "ws1['!ref']='A1:B5';ws1['!cols']=[{wpx:123},{wpx:77}];"
                     "var ws2=X.utils.aoa_to_sheet([[10]]);"
                     "ws2['A2']={t:'n',f:'A1*2'};ws2['!ref']='A1:A2';"             # 対応（四則）→生きた式
                     "var wb=X.utils.book_new();"
                     "X.utils.book_append_sheet(wb,ws1,'売上');"
                     "X.utils.book_append_sheet(wb,ws2,'原価');"
                     "var out=X.write(wb,{type:'array',bookType:'xlsx'});"
                     "var ok=K.importXlsx(out,'テスト.xlsx');"
                     "return {ok:ok,names:K.sheetNames().join('|'),name:K.doc.name,"
                     "imp:K.lastImport,"
                     "sum:K.val('B4'),sumRaw:K.getRaw('B4'),"
                     "dateDisp:K.display('A5'),dateRaw:K.getRaw('A5'),dateNum:typeof K.val('A5'),"
                     "b5Raw:K.getRaw('B5'),b5Val:K.val('B5'),"
                     "cw0:K.doc.sheets[0].colW[0],cw1:K.doc.sheets[0].colW[1],"
                     "status:document.getElementById('save-status').textContent};})()")
        assert r["ok"] and r["names"] == "売上|原価" and r["name"] == "テスト", f"取り込み基本: {r}"
        assert r["imp"]["sheets"]==2 and r["imp"]["formulas"]==2 and r["imp"]["valued"]==1, f"要約: {r['imp']}"
        assert r["sumRaw"] == "=SUM(B2:B3)" and r["sum"] == 300, f"対応関数は生きた式: {r}"
        assert r["dateRaw"] == "2026-08-14" and r["dateDisp"] == "2026-08-14" and r["dateNum"] == "number", f"日付型: {r}"
        assert r["b5Raw"] == "x300" and "=" not in r["b5Raw"] and r["b5Val"] == "x300", f"非対応式→値: {r}"
        assert r["cw0"] == 123 and r["cw1"] == 77, f"列幅: {r}"
        assert "xlsxから取り込んだ" in r["status"], f"状態欄: {r['status']}"
        print(f"OK xlsx読み込み 2シート・式{r['imp']['formulas']}（SUM=300生きた式）・"
              f"値に落ちた式{r['imp']['valued']}・日付2026-08-14・列幅{r['cw0']}/{r['cw1']}px・状態欄表示")

        # 2枚目のシートに切替→四則の式も生きている
        r2 = ev(sock, "(function(){var K=window.CalcKit;K.switchSheet(1);"
                      "return {raw:K.getRaw('A2'),v:K.val('A2')};})()")
        assert r2["raw"] == "=A1*2" and r2["v"] == 20, f"2枚目の式: {r2}"
        print(f"OK xlsx読み込み 2枚目 =A1*2=20（シート越しに式が生きる）")

        # --- 書式つき（%・¥・小数・桁区切り＋太字/塗り/文字色/横位置＋結合）を openpyxl で作って取り込む ---
        #   SheetJS write は塗り/太字を書けないので、実物の様式は openpyxl で作りbase64で流し込む。
        #   太字・文字色・横位置は importXlsxAsync が zip の styles.xml を自前で読んで補う。
        import base64, io, openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        wbk=openpyxl.Workbook(); wsx=wbk.active; wsx.title="様式"
        wsx["A1"]="見出し"; wsx["A1"].font=Font(bold=True,color="FF0000")
        wsx["A1"].fill=PatternFill("solid",fgColor="FFFF00"); wsx["A1"].alignment=Alignment(horizontal="right")
        wsx["B2"]=0.5;      wsx["B2"].number_format="0%"
        wsx["C2"]=1234;     wsx["C2"].number_format='"¥"#,##0'
        wsx["D2"]=1234.5;   wsx["D2"].number_format="#,##0.00"
        wsx["E2"]=1000000;  wsx["E2"].number_format="#,##0"
        wsx["A4"]="結合セル"; wsx.merge_cells("A4:C4")
        bio=io.BytesIO(); wbk.save(bio)
        b64=base64.b64encode(bio.getvalue()).decode()
        js=("(async()=>{var b=atob('"+b64+"');var u=new Uint8Array(b.length);"
            "for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);"
            "var imp=await window.CalcKit.importXlsxAsync(u.buffer,'様式.xlsx');"
            "var K=window.CalcKit,cs=K.doc.sheets[0].cells;"
            "return {imp:imp,name:K.doc.name,"
            "pb2:K.display('B2'),pc2:K.display('C2'),pd2:K.display('D2'),pe2:K.display('E2'),"
            "fb2:cs['B2'].fmt,fc2:cs['C2'].fmt,fd2:cs['D2'].fmt,fe2:cs['E2'].fmt,"
            "bold:!!cs['A1'].bold,bg:cs['A1'].bg,color:cs['A1'].color,align:cs['A1'].align,"
            "a4:K.display('A4')};})()")
        st=ev(sock,js,await_promise=True)
        assert st["name"]=="様式", f"様式ファイル名: {st}"
        assert st["fb2"]=="pct" and st["pb2"]=="50%", f"%書式: {st}"
        assert st["fc2"]=="yen" and st["pc2"]=="¥1,234", f"¥書式: {st}"
        assert st["fd2"]=="dec2" and st["pd2"]=="1,234.50", f"小数書式: {st}"
        assert st["fe2"]=="num" and st["pe2"]=="1,000,000", f"桁区切り書式: {st}"
        assert st["bold"] and st["bg"]=="#FFFF00" and st["color"]=="#FF0000" and st["align"]=="r", f"太字/塗り/文字色/横位置: {st}"
        assert st["imp"]["merges"]==1 and st["a4"]=="結合セル", f"結合セルの注記: {st}"
        assert st["imp"].get("styled",0)>=3, f"様式の取り込み件数: {st}"
        print(f"OK xlsx書式 %={st['pb2']}・¥={st['pc2']}・小数={st['pd2']}・桁区切り={st['pe2']}"
              f"＋太字/黄塗り/赤字/右寄せ＋結合1件（見た目補完{st['imp']['styled']}件）")
        print("XLSX_IMPORT_OK .xlsx取り込み通過")
    finally:
        chrome.terminate()

def condfmt_pivot():
    """条件付き書式（規則→色の付くセルの数・データバー）とピボット（3×2の集計値・更新）の検査"""
    subprocess.run(["pkill", "-f", "calckit-cfpv-profile"], capture_output=True)
    time.sleep(0.4)
    prof = "/tmp/calckit-cfpv-profile"
    subprocess.run(["rm", "-rf", prof])
    port7 = PORT + 29
    old = cdpkit.PORT; cdpkit.PORT = port7
    chrome = subprocess.Popen([cdpkit.CHROME, "--headless=new", f"--remote-debugging-port={port7}",
                               f"--user-data-dir={prof}", "--no-first-run", "--mute-audio",
                               "--window-size=1600,900", PAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = cdpkit.connect(); cdpkit.PORT = old
        call, ev = cdpkit.call, cdpkit.ev
        call(sock, "Runtime.enable")
        deadline = time.time() + 15
        while time.time() < deadline:
            if ev(sock, "!!(window.CalcKit && window.CalcKit.addCondRule && window.CalcKit.createPivot)"):
                break
            time.sleep(0.3)
        # 新しいシートに 6行の表を置く: 地域/品/額
        ev(sock, "(function(){var K=window.CalcKit;K.addSheet();"
                 "var rows=[['地域','品','額'],['東','りんご',100],['東','みかん',50],['西','りんご',70],['西','みかん',20],['西','りんご',30]];"
                 "rows.forEach(function(r,i){r.forEach(function(v,j){K.setCell(String.fromCharCode(65+j)+(i+1),String(v));});});return true;})()")
        # 条件付き書式: 額>=50 を黄塗り・太字、品に「りんご」を含む→赤字、額にデータバー
        st = ev(sock, "(function(){var K=window.CalcKit;"
                      "K.addCondRule({range:{r1:1,c1:2,r2:5,c2:2},op:'>=',v1:50,bg:'#FFF59D',bold:1});"
                      "K.addCondRule({range:{r1:1,c1:1,r2:5,c2:1},op:'contains',text:'りんご',color:'#C62828'});"
                      "K.addCondRule({range:{r1:1,c1:2,r2:5,c2:2},kind:'databar',barColor:'#9cc3ea'});"
                      "var yellow=0,bold=0,red=0,bars=[];"
                      "for(var r=2;r<=6;r++){var s=K.condStyle('C'+r);if(s&&s.bg==='#FFF59D')yellow++;if(s&&s.bold)bold++;if(s&&s.bar!=null)bars.push(s.bar);"
                      " var t=K.condStyle('B'+r);if(t&&t.color==='#C62828')red++;}"
                      "return {rules:K.condRules.length,yellow:yellow,bold:bold,red:red,bars:bars,"
                      "td:(function(){var td=document.querySelector('td[data-a=\"C2\"],td[data-addr=\"C2\"]');return td?td.style.background:null;})()};})()")
        assert st["rules"] == 3, f"規則の数: {st}"
        assert st["yellow"] == 3 and st["bold"] == 3, f"額>=50 は 100/50/70 の3セルのはず: {st}"
        assert st["red"] == 3, f"りんご は3セルのはず: {st}"
        assert st["bars"] == [100, 50, 70, 20, 30], f"データバー（最大=100%・0から）: {st}"
        print(f"OK 条件付き書式 規則3→黄塗り太字{st['yellow']}セル・赤字{st['red']}セル・データバー{st['bars']}")
        # 規則を1つ外す→色が減る
        st2 = ev(sock, "(function(){var K=window.CalcKit;K.removeCondRule(0);var y=0;for(var r=2;r<=6;r++){var s=K.condStyle('C'+r);if(s&&s.bg==='#FFF59D')y++;}return {rules:K.condRules.length,yellow:y};})()")
        assert st2["rules"] == 2 and st2["yellow"] == 0, f"規則を外した後: {st2}"
        print("OK 条件付き書式 規則を外すと色が消える")
        # ピボット: 行=地域・列=品・値=合計(額) → 2×2
        pv = ev(sock, "(function(){var K=window.CalcKit;var src=K.sheetNames()[K.sheetNames().length-1];"
                      "var err=K.createPivot({srcSheetName:src,r1:0,c1:0,r2:5,c2:2,rowField:0,colField:1,valField:2,agg:'sum'});"
                      "if(err)return {err:err};var names=K.sheetNames();var g={};"
                      "for(var r=1;r<=6;r++)for(var c=0;c<5;c++){var a=String.fromCharCode(65+c)+r;var d=K.display(a);if(d!=='')g[a]=d;}"
                      "return {sheet:names[names.length-1],g:g};})()")
        assert "err" not in pv, f"ピボット作成: {pv}"
        g = pv["g"]; vals = list(g.values())
        # 東×りんご=100, 東×みかん=50, 西×りんご=100, 西×みかん=20, 行計 150/120, 列計 200/70, 総計 270
        for want in ("100", "50", "20", "150", "120", "200", "70", "270"):
            assert want in vals, f"ピボットに {want} がない: {g}"
        assert "東" in vals and "西" in vals and "りんご" in vals and "みかん" in vals, f"軸の見出し: {g}"
        print(f"OK ピボット 行=地域×列=品×合計(額)→ 東りんご100・西りんご100・総計270（{pv['sheet']}）")
        # 元を変えて更新 → 総計が変わる
        up = ev(sock, "(function(){var K=window.CalcKit;var names=K.sheetNames();var pi=names.length-1,si=pi-1;"
                      "K.switchSheet(si);K.setCell('C2','200');K.refreshPivot(pi);K.switchSheet(pi);"
                      "var found=null;for(var r=1;r<=6;r++)for(var c=0;c<5;c++){var d=K.display(String.fromCharCode(65+c)+r);if(d==='370')found=String.fromCharCode(65+c)+r;}return {found:found};})()")
        assert up["found"], f"更新後の総計370が無い: {up}"
        print("OK ピボット 元の表を変えて「更新」→総計 270→370")
        print("CONDFMT_PIVOT_OK 条件付き書式・ピボット通過")
    finally:
        chrome.terminate()

if __name__ == "__main__":
    main()
    slidekit_roundtrip()
    scenarios()
    gantt_roundtrip()
    xlsx_import()
    condfmt_pivot()
