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
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FMT = {'num': '#,##0', 'yen': '"¥"#,##0;-"¥"#,##0', 'pct': '0.0%',
       'dec2': '#,##0.00', 'date': 'yyyy-mm-dd'}
DATE_RE = re.compile(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$')
NUM_RE = re.compile(r'^-?[\d,]+(\.\d+)?$')
ALIGN_H = {'l': 'left', 'c': 'center', 'r': 'right'}
ALIGN_V = {'t': 'top', 'm': 'center', 'b': 'bottom'}
ADDR_RE = re.compile(r'^([A-Z]+)(\d+)$')

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
    for s in doc['sheets']:
        ws = wb.create_sheet(sheet_title(s.get('name'), used))
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
            opts = c.get('opts')
            if opts:
                key = '\x00'.join(opts)
                if key not in dvs:
                    dv = DataValidation(type='list', formula1='"' + ','.join(opts) + '"',
                                        allow_blank=True, showDropDown=False)
                    ws.add_data_validation(dv)
                    dvs[key] = dv
                dvs[key].add(cell)
    wb.save(out_path)
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
    print('CALC2XLSX_OK（式・シート間参照・¥/%数値化・日付・書式・プルダウン・列幅・validate検査）')

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
