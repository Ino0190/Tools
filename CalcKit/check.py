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
        print("GANTT_ROUNDTRIP_OK 表⇄ガントの往復通過")
    finally:
        chrome.terminate()

if __name__ == "__main__":
    main()
    slidekit_roundtrip()
    scenarios()
    gantt_roundtrip()
