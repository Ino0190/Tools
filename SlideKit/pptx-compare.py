#!/usr/bin/env python3
"""ブラウザ表示とPPTXの描画を1枚ずつ左右に並べた比較画像を作る（作成者の目視用）。
  python3 SlideKit/pptx-compare.py 対象.html [--pages 1,3,5] [--out /tmp/skcmp]
手順: slidecheck.py でブラウザのスクショ → html_to_pptx.py でPPTX → LibreOffice でPNG化 → 左右に並べる。
出力: <out>/<stem>_cmp_pNN.png（左=ブラウザ／右=PPTX）と <stem>_cmp_sheet.png（一覧）。
注意: 右はLibreOfficeの描画。フォントと行送りはPowerPointと少し違う。形・色・欠落の比較に使う。
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOFFICE_CANDS = ['/opt/homebrew/bin/soffice', '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                 shutil.which('soffice') or '', shutil.which('libreoffice') or '']


def find_soffice():
    return next((p for p in SOFFICE_CANDS if p and os.path.exists(p)), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html')
    ap.add_argument('--pages', default='all')
    ap.add_argument('--out', default='/tmp/skcmp')
    a = ap.parse_args()
    html = os.path.abspath(a.html)
    stem = os.path.splitext(os.path.basename(html))[0]
    soffice = find_soffice()
    if not soffice:
        print('LibreOffice（soffice）が見つからない'); return 2
    if not shutil.which('pdftoppm'):
        print('pdftoppm が見つからない（brew install poppler）'); return 2
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix='skcmp-')
    try:
        # 1) ブラウザのスクショ（slidecheck の --shot）
        subprocess.run([sys.executable, os.path.join(HERE, 'slidecheck.py'), html, '--shot', a.pages],
                       check=True, stdout=subprocess.DEVNULL)
        # 2) PPTX（元HTMLの隣を汚さないよう作業ディレクトリへ出す）
        pptx = os.path.join(work, stem + '.pptx')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'html_to_pptx.py'), html, pptx,
                            '--allow-missing-assets'], capture_output=True, text=True)
        warns = [ln for ln in r.stdout.splitlines() if 'WARN' in ln or '⚠️' in ln or '🚨' in ln]
        if not os.path.exists(pptx):
            print(r.stdout[-2000:]); return 1
        # 3) PPTX → PDF → PNG
        subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', work, pptx],
                       check=True, capture_output=True)
        subprocess.run(['pdftoppm', '-png', '-r', '96', os.path.join(work, stem + '.pdf'),
                        os.path.join(work, 'pp')], check=True)
        pages = None if a.pages == 'all' else {int(p) for p in a.pages.split(',') if p.strip().isdigit()}
        return compose(stem, work, a.out, warns, pages)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compose(stem, work, out, warns, pages=None):
    from PIL import Image, ImageDraw
    pp = sorted(glob.glob(os.path.join(work, 'pp-*.png')))
    for old in glob.glob(os.path.join(out, stem + '_cmp_*.png')):
        os.remove(old)  # 前回の比較画像を混ぜない
    made = []
    for path in pp:
        n = int(os.path.splitext(path)[0].rsplit('-', 1)[1])
        if pages is not None and n not in pages:
            continue
        shot = os.path.join('/tmp/slidecheck', '%s_p%02d.png' % (stem, n))
        if not os.path.exists(shot):
            continue
        left = Image.open(shot).convert('RGB').crop((10, 0, 1290, 720)).resize((640, 360), Image.LANCZOS)
        right = Image.open(path).convert('RGB').resize((640, 360), Image.LANCZOS)
        im = Image.new('RGB', (1290, 384), '#2a2f36')
        im.paste(left, (0, 24)); im.paste(right, (650, 24))
        d = ImageDraw.Draw(im)
        d.text((6, 5), 'p%02d  browser' % n, fill='#ffffff'); d.text((656, 5), 'PPTX', fill='#ffffff')
        dst = os.path.join(out, '%s_cmp_p%02d.png' % (stem, n))
        im.save(dst); made.append(dst)
    if not made:
        print('比較画像を作れなかった'); return 1
    rows = [Image.open(p) for p in made]
    sheet = Image.new('RGB', (1290, 384 * len(rows)), '#2a2f36')
    for i, r_ in enumerate(rows):
        sheet.paste(r_, (0, 384 * i))
    sp = os.path.join(out, stem + '_cmp_sheet.png')
    sheet.save(sp)
    print('比較 %d枚  一覧: %s' % (len(made), sp))
    for w in warns[:30]:
        print('  ' + w.strip())
    return 0


if __name__ == '__main__':
    sys.exit(main())
