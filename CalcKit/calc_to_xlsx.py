# CalcKit .calc.json → .xlsx（式・書式ごとExcel化。顧客納品用の出口）
# 使い方: python3 CalcKit/calc_to_xlsx.py 対象.calc.json [出力.xlsx] [--strict]
#         python3 CalcKit/calc_to_xlsx.py --check 対象.calc.json   … 形状検査のみ（違反で非ゼロ終了）
#         python3 CalcKit/calc_to_xlsx.py --selftest
# 検査: 変換前に validate() が形状違反（不正セルキー・未知fmt・VLOOKUP第4引数欠落等）を
#       警告リストで出力する。既定は警告のみで変換続行、--strict なら非ゼロ終了で停止
# 方針:
#   ・式（=SUM/IF/VLOOKUP・$絶対参照・シート間参照=収支!N21）はCalcKitがExcel互換文法なので
#     そのままExcelの式として書き込む＝Excel側で生きた式になり再計算される
#   ・fmt: num/yen/pct/dec2/date → Excelの表示形式。bold/揃え/折り返し/プルダウン/列幅/行高も反映
#   ・値のみ欲しい時は従来のCSV/.xls書き出し（アプリ内）を使う
import json, re, sys, datetime, os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FMT = {'num': '#,##0', 'yen': '"¥"#,##0;-"¥"#,##0', 'pct': '0.0%',
       'dec2': '#,##0.00', 'date': 'yyyy-mm-dd'}
DATE_RE = re.compile(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$')
NUM_RE = re.compile(r'^-?[\d,]+(\.\d+)?$')
ALIGN_H = {'l': 'left', 'c': 'center', 'r': 'right'}
ALIGN_V = {'t': 'top', 'm': 'center', 'b': 'bottom'}
ADDR_RE = re.compile(r'^([A-Z]+)(\d+)$')

# CalcKit の式エンジンが持つ関数名（calc.js の FUNCS＋SPECIAL_FUNCS＋特殊処理 IF/SUMIF/COUNTIF/VLOOKUP/HLOOKUP と対応・2026-11-15）
# 🚫 以前はここに照らさず、=UNKNOWNFN(1) のような未知関数もそのまま生きた式で xlsx に書いていた。
CK_FUNCS = {
    'SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT', 'COUNTA', 'ABS', 'INT', 'SQRT',
    'ROUND', 'ROUNDUP', 'ROUNDDOWN', 'TODAY', 'DATE', 'IF', 'SUMIF', 'COUNTIF',
    'VLOOKUP', 'HLOOKUP', 'NOT', 'TRUE', 'FALSE', 'ISBLANK', 'ISNUMBER', 'ISTEXT',
    'ISERROR', 'YEAR', 'MONTH', 'DAY', 'EOMONTH', 'EDATE', 'DAYS', 'WEEKDAY',
    'NETWORKDAYS', 'MOD', 'POWER', 'PRODUCT', 'CEILING', 'FLOOR', 'LEN', 'LEFT',
    'RIGHT', 'MID', 'UPPER', 'LOWER', 'TRIM', 'CONCATENATE', 'CONCAT', 'VALUE',
    'TEXT', 'IFERROR', 'IFS', 'AND', 'OR', 'SUMIFS', 'COUNTIFS', 'AVERAGEIF',
    'INDEX', 'MATCH', 'SUMPRODUCT', 'RANK',
}
FUNC_RE = re.compile(r'[A-Za-z][A-Za-z0-9_.]*(?=\s*\()')

def formula_issue(formula):
    """壊れた式なら理由（日本語）、正しければ None を返す（2026-11-15）。
    括弧の対応・文字列の閉じ・末尾の演算子・CalcKit が知らない関数名を見る。
    CalcKit が評価できない式を xlsx に生きた式のまま書かないための番人。"""
    body = formula[1:] if formula.startswith('=') else formula
    depth, in_str, i, n = 0, False, 0, len(body)
    while i < n:
        ch = body[i]
        if in_str:
            if ch == '"':
                if i + 1 < n and body[i + 1] == '"':  # "" はエスケープされた "
                    i += 2; continue
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return '括弧が閉じすぎ（) が多い）'
        i += 1
    if in_str:
        return '文字列の " が閉じていない'
    if depth > 0:
        return '括弧が閉じていない（( が多い）'
    stripped = body.rstrip()
    if stripped and not stripped.endswith('"') and stripped[-1] in '+-*/^&,<>=(':
        return f'式が演算子・記号で終わっている（…{stripped[-1]}）'
    for name in FUNC_RE.findall(body):
        if name.upper() not in CK_FUNCS:
            return f'CalcKit が知らない関数 {name}()'
    return None

def sheet_title(name, used):
    t = re.sub(r'[\[\]:*?/\\]', '_', name or 'シート')[:31] or 'シート'
    base, i = t, 2
    while t in used:
        t = f'{base[:28]}_{i}'; i += 1
    used.add(t)
    return t

def parse_value(v, fmt):
    """セルの生文字列 → (Excelに書く値, 推定fmt)。式はそのまま文字列で返す"""
    if v.startswith('='):
        return v, fmt
    m = DATE_RE.match(v)
    if m:
        y, mo, d = map(int, m.groups())
        return datetime.date(y, mo, d), (fmt or 'date')
    s = v.replace('¥', '').replace(',', '').strip()
    if s.endswith('%') and NUM_RE.match(s[:-1].strip() or 'x') and s[:-1].strip():
        try: return float(s[:-1]) / 100, (fmt or 'pct')
        except ValueError: pass
    if s and NUM_RE.match(s):
        f = float(s)
        return (int(f) if f.is_integer() else f), (fmt or ('yen' if '¥' in v else None))
    return v, fmt

def vlookup_arg_counts(formula):
    """式文字列中の各VLOOKUP呼び出しのトップレベル引数数を返す（ネスト対応）"""
    counts = []
    for m in re.finditer(r'VLOOKUP\s*\(', formula, re.I):
        depth, args, i = 1, 1, m.end()
        while i < len(formula) and depth > 0:
            ch = formula[i]
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            elif ch == ',' and depth == 1: args += 1
            i += 1
        counts.append(args)
    return counts

def validate(doc):
    """`.calc.json` の形状検査（変換で黙って捨てられる・誤るものを列挙）。違反文字列のリストを返す"""
    issues = []
    if not isinstance(doc, dict):
        return ['トップレベルがオブジェクトでない']
    sheets = doc.get('sheets')
    if not isinstance(sheets, list) or not sheets:
        return ["'sheets' が無いか空（旧単一シート形式はトップレベル 'cells' が必要）"]
    for si, s in enumerate(sheets):
        if not isinstance(s, dict):
            issues.append(f'sheets[{si}]: オブジェクトでない'); continue
        label = s.get('name') or f'sheets[{si}]'
        cells = s.get('cells') or {}
        if not isinstance(cells, dict):
            issues.append(f"{label}: 'cells' が辞書でない"); continue
        for addr, c in cells.items():
            where = f'{label}!{addr}'
            if not ADDR_RE.match(str(addr)):
                issues.append(f'{where}: セルキーが A1形式（^[A-Z]+数字$）でない → 変換で黙って捨てられる')
                continue
            if not isinstance(c, dict):
                issues.append(f'{where}: セルがオブジェクトでない'); continue
            fmt = c.get('fmt')
            if fmt is not None and fmt not in FMT:
                issues.append(f"{where}: 未知のfmt '{fmt}'（許可: {'/'.join(FMT)}）→ 表示形式が付かない")
            v = str(c.get('v', ''))
            if v.startswith('='):
                bad = formula_issue(v)
                if bad:
                    issues.append(f'{where}: 壊れた式（{bad}）→ 文字として書き出す（Excel で評価させない）')
                    continue
                for n in vlookup_arg_counts(v):
                    if n < 4:
                        issues.append(f'{where}: VLOOKUPに第4引数がない（完全一致は `,0` 必須。省略は近似一致で誤値）')
    return issues

def pct_format(value):
    """pctは整数％なら0%、小数が出るなら0.0%（50.0%の見た目のうるささを避ける）"""
    if isinstance(value, (int, float)) and abs(value * 100 - round(value * 100)) < 1e-9:
        return '0%'
    return '0.0%'

def convert(doc, out_path):
    wb = Workbook(); wb.remove(wb.active)
    used = set()
    broken = []   # (シート名!セル, 理由, 元の式) 変換で文字に落とした壊れた式
    for s in doc['sheets']:
        ws = wb.create_sheet(sheet_title(s.get('name'), used))
        label = s.get('name') or ws.title
        for k, w in (s.get('colW') or {}).items():
            ws.column_dimensions[get_column_letter(int(k) + 1)].width = round(int(w) / 7.0, 1)
        for k, h in (s.get('rowH') or {}).items():
            ws.row_dimensions[int(k) + 1].height = round(int(h) * 0.75, 1)
        dvs = {}  # プルダウン候補 → DataValidation（同じ候補は1つにまとめる）
        for addr, c in (s.get('cells') or {}).items():
            if not ADDR_RE.match(addr):
                continue
            raw = str(c.get('v', ''))
            value, fmt = parse_value(raw, c.get('fmt'))
            cell = ws[addr]
            # 壊れた式は生きた式にせず、先頭に ' を付けた文字として書く（Excel で評価させない・2026-11-15）
            bad = formula_issue(raw) if raw.startswith('=') else None
            if bad:
                cell.value = "'" + raw
                broken.append((f'{label}!{addr}', bad, raw))
            else:
                cell.value = value
                if fmt == 'pct' and not raw.startswith('='):
                    cell.number_format = pct_format(value)
                elif fmt in FMT:
                    cell.number_format = FMT[fmt]
            if c.get('bold'):
                cell.font = Font(bold=True)
            if c.get('align') or c.get('valign') or c.get('wrap'):
                cell.alignment = Alignment(
                    horizontal=ALIGN_H.get(c.get('align')),
                    vertical=ALIGN_V.get(c.get('valign')),
                    wrap_text=bool(c.get('wrap')) or None)
            if c.get('fill'):
                color = 'DBE7F3' if c.get('fill') == 'section' else 'EEF3F8'
                cell.fill = PatternFill(fill_type='solid', fgColor=color)
            if c.get('borderTop'):
                major = c.get('borderTop') == 'major'
                cell.border = Border(top=Side(style='medium' if major else 'thin',
                                              color='21537F' if major else '718096'))
            opts = c.get('opts')
            if opts:
                key = '\x00'.join(opts)
                if key not in dvs:
                    dv = DataValidation(type='list', formula1='"' + ','.join(opts) + '"',
                                        allow_blank=True, showDropDown=False)
                    ws.add_data_validation(dv)
                    dvs[key] = dv
                dvs[key].add(cell)
        f = s.get('filter')  # 見出し行のフィルタ → Excelのオートフィルタ（絞り込み状態は持ち越さない）
        if isinstance(f, dict) and all(isinstance(f.get(k), int) for k in ('r', 'r2', 'c1', 'c2')):
            ws.auto_filter.ref = '%s%d:%s%d' % (get_column_letter(f['c1'] + 1), f['r'] + 1,
                                                get_column_letter(f['c2'] + 1), f['r2'] + 1)
    wb.save(out_path)
    for where, reason, raw in broken:
        print(f'文字にした式: {where}（{reason}）: {raw}', file=sys.stderr)
    return out_path

def selftest():
    doc = {'name': 'テスト', 'active': 0, 'sheets': [
        {'name': '工数', 'rows': 10, 'cols': 8, 'colW': {'0': 140}, 'rowH': {'0': 40}, 'cells': {
            'A1': {'v': '工数計算', 'bold': 1},
            'A2': {'v': '役割', 'bold': 1}, 'B2': {'v': 'レベル', 'bold': 1},
            'A3': {'v': 'PM'}, 'B3': {'v': 'L6', 'opts': ['L6', 'L5', 'L4'], 'align': 'c'},
            'C3': {'v': '41720', 'fmt': 'yen'}, 'D3': {'v': '50%'},
            'E3': {'v': '=C3*40*D3', 'fmt': 'yen'},
            'F3': {'v': '2026-08-14'}, 'G3': {'v': '=F3+7', 'fmt': 'date'},
            'A5': {'v': '合計', 'bold': 1}, 'E5': {'v': '=SUM(E3:E4)', 'fmt': 'yen', 'bold': 1},
            'A6': {'v': '=集計!B1', 'fmt': 'dec2'},
            'A7': {'v': '長い説明文を折り返す', 'wrap': 1, 'valign': 't'},
        }},
        {'name': '集計', 'rows': 5, 'cols': 3, 'colW': {}, 'rowH': {}, 'cells': {
            'A1': {'v': '人月'}, 'B1': {'v': '=工数!E5/1600000', 'fmt': 'dec2'},
        }},
    ]}
    out = convert(doc, '/tmp/calckit-selftest.xlsx')
    wb = load_workbook(out)  # 式保持のまま読み戻して検証
    ws, ws2 = wb['工数'], wb['集計']
    assert ws['E3'].value == '=C3*40*D3' and ws['E3'].number_format.startswith('"¥"'), ws['E3'].value
    assert ws['A6'].value == '=集計!B1' and ws2['B1'].value == '=工数!E5/1600000', 'シート間参照'
    assert ws['C3'].value == 41720 and ws['D3'].value == 0.5, '数値化（¥・%の生入力）'
    assert ws['D3'].number_format == '0%', 'pctの表示形式'
    assert isinstance(ws['F3'].value, datetime.datetime) or isinstance(ws['F3'].value, datetime.date), '日付'
    assert ws['A1'].font.bold and ws['B3'].alignment.horizontal == 'center', '書式'
    assert ws['A7'].alignment.wrap_text and ws['A7'].alignment.vertical == 'top', '折り返し'
    assert abs(ws.column_dimensions['A'].width - 20.0) < 0.1, '列幅'
    assert len(ws.data_validations.dataValidation) == 1, 'プルダウン'
    os.remove(out)
    assert validate(doc) == [], '正常docは違反ゼロのはず'
    bad = {'sheets': [{'name': 'S', 'cells': {
        'a1': {'v': 'x'},                          # 小文字キー
        'B2': {'v': '1', 'fmt': 'money'},           # 未知fmt
        'C3': {'v': '=VLOOKUP(A1,D:E,2)'},          # 第4引数なし
        'D4': {'v': '=IF(VLOOKUP(A1,D:E,2,0)>1,SUM(A1:A2),0)'},  # ネスト4引数はOK
    }}]}
    msgs = validate(bad)
    assert len(msgs) == 3 and 'a1' in msgs[0] and 'money' in msgs[1] and 'VLOOKUP' in msgs[2], msgs
    assert validate({'foo': 1}) == ["'sheets' が無いか空（旧単一シート形式はトップレベル 'cells' が必要）"]
    assert vlookup_arg_counts('=VLOOKUP(A1,B:C,2,0)') == [4]

    # 壊れた式は文字に落とす（2026-11-15・C3）: =SUM( ・=1+ ・未知関数は ' 付きの文字、正しい式は生きたまま
    assert formula_issue('=SUM(') and formula_issue('=1+') and formula_issue('=UNKNOWNFN(1)')
    assert formula_issue('=SUM(A1:A2)') is None and formula_issue('=IF(A1>1,"(x)",SUM(A1:A2))') is None
    assert formula_issue('=工数!E5/1600000') is None and formula_issue('=50%') is None
    bdoc = {'name': '壊れ式', 'active': 0, 'sheets': [{'name': 'S', 'rows': 5, 'cols': 5, 'cells': {
        'A1': {'v': '=SUM('},                 # 括弧が閉じない
        'A2': {'v': '=1+'},                    # 末尾が演算子
        'A3': {'v': '=UNKNOWNFN(1)'},          # 未知関数
        'B1': {'v': '=SUM(A1:A2)'},            # 正しい → 生きた式のまま
        'B2': {'v': '=工数!E5/2'},             # シート間参照 → 生きたまま
    }}]}
    msgs = validate(bdoc)
    assert len(msgs) == 3 and all('壊れた式' in m for m in msgs), msgs
    bout = convert(bdoc, '/tmp/calckit-selftest-broken.xlsx')   # 壊れ式は stderr に『文字にした式』も出る
    wb2 = load_workbook(bout)
    ws3 = wb2['S']
    assert ws3['A1'].value == "'=SUM(" and ws3['A1'].data_type == 's', ('壊れ式を文字に', ws3['A1'].value, ws3['A1'].data_type)
    assert ws3['A2'].value == "'=1+" and ws3['A3'].value == "'=UNKNOWNFN(1)", (ws3['A2'].value, ws3['A3'].value)
    assert ws3['B1'].value == '=SUM(A1:A2)' and ws3['B2'].value == '=工数!E5/2', ('正しい式は生きたまま', ws3['B1'].value, ws3['B2'].value)
    os.remove(bout)
    print('CALC2XLSX_OK（式・シート間参照・¥/%数値化・日付・書式・プルダウン・列幅・validate検査・壊れ式を文字に落とす）')

if __name__ == '__main__':
    strict = '--strict' in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != '--strict']
    if args and args[0] == '--selftest':
        selftest(); sys.exit(0)
    check_only = bool(args) and args[0] == '--check'
    if check_only:
        args = args[1:]
    if not args:
        print('python3 calc_to_xlsx.py 対象.calc.json [出力.xlsx] [--strict] | --check 対象.calc.json | --selftest')
        sys.exit(1)
    src = args[0]
    with open(src, encoding='utf-8') as f:
        d = json.load(f)
    if isinstance(d, dict) and 'sheets' not in d and 'cells' in d:  # 旧単一シート形式
        d = {'name': d.get('name', 'シート'), 'active': 0,
             'sheets': [{'name': 'シート1', 'colW': d.get('colW', {}), 'rowH': d.get('rowH', {}),
                         'cells': d.get('cells', {})}]}
    issues = validate(d)
    for msg in issues:
        print(f'警告: {msg}', file=sys.stderr)
    if check_only:
        print(f'{src}: 違反 {len(issues)} 件' if issues else f'{src}: OK')
        sys.exit(1 if issues else 0)
    if issues and strict:
        print(f'--strict: 違反 {len(issues)} 件のため変換を中止', file=sys.stderr)
        sys.exit(1)
    dst = args[1] if len(args) > 1 else re.sub(r'(\.calc)?\.json$', '', src) + '.xlsx'
    print('saved:', convert(d, dst))
