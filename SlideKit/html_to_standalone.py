#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スライドHTMLを「1ファイルだけ送れば開ける」形にする。

  python3 SlideKit/html_to_standalone.py <deck>.html [-o out.html]

やること
  1. <img src> <video src> <video poster> の外部ファイルを base64 で埋め込む
  2. slide-edit.js の読み込みを外す（渡す相手には編集UIが要らない・404になるだけ）
  3. 相対パスの参照が残っていないか検査して報告する

🚫 これは**渡す用のコピー**。正本は元のHTML。standalone を編集しないこと
   （base64が混ざって str_replace も slide-edit.js も使えなくなる）
"""
import base64
import mimetypes
import os
import re
import sys

MIME = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime',
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml'}


def data_uri(path):
    ext = os.path.splitext(path)[1].lower()
    mime = MIME.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
    with open(path, 'rb') as f:
        return 'data:%s;base64,%s' % (mime, base64.b64encode(f.read()).decode('ascii'))


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    src = os.path.abspath(argv[0])
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv \
        else os.path.splitext(src)[0] + '.standalone.html'
    base = os.path.dirname(src)
    with open(src, encoding='utf-8') as f:
        t = f.read()

    # 🚫 先に slide-edit.js を外す。あとにすると src="" が base64 に置換されてしまい、
    #    除去の正規表現が一致せず**編集UIごと310KB埋め込まれる**（2026-08-21に踏んだ）
    removed = len(re.findall(r'<script[^>]*slide-edit\.js[^>]*>\s*</script>\s*', t))
    t = re.sub(r'<script[^>]*slide-edit\.js[^>]*>\s*</script>\s*', '', t)

    embedded, missing, total = [], [], [0]

    def repl(m):
        attr, path = m.group(1), m.group(2)
        if path.startswith(('data:', 'http://', 'https://', '#')):
            return m.group(0)
        full = os.path.join(base, path)
        if not os.path.exists(full):
            missing.append(path)
            return m.group(0)
        uri = data_uri(full)
        total[0] += len(uri)
        embedded.append((path, os.path.getsize(full)))
        return '%s="%s"' % (attr, uri)

    t = re.sub(r'\b(src|poster)="([^"]+)"', repl, t)
    return finish(t, out, embedded, missing, src, removed)


def finish(t, out, embedded, missing, src, removed):
    # 渡す相手のブラウザで確実に自動再生されるよう muted を保証する
    # 🚫 muted が無いと Chrome/Safari は autoplay をブロックする
    fixed = 0
    for m in list(re.finditer(r'<video\b[^>]*>', t)):
        tag = m.group(0)
        if 'autoplay' in tag and 'muted' not in tag:
            t = t.replace(tag, tag.replace('<video', '<video muted', 1)); fixed += 1

    with open(out, 'w', encoding='utf-8') as f:
        f.write(t)

    print('STANDALONE %s' % out)
    print('  元: %s' % src)
    print('  埋め込み %d件' % len(embedded))
    for p, n in embedded:
        print('    %-46s %8.1f KB' % (p, n / 1024))
    print('  slide-edit.js の読み込みを除去: %d件' % removed)
    if fixed:
        print('  autoplay に muted を補った: %d件' % fixed)
    print('  出力サイズ: %.1f MB' % (os.path.getsize(out) / 1024 / 1024))

    # 相対パス参照が残っていないか（残っていると相手の環境で欠ける）
    rest = [p for p in re.findall(r'\b(?:src|poster|href)="([^"]+)"', t)
            if not p.startswith(('data:', 'http://', 'https://', '#'))]
    if missing:
        print('  🚨 見つからなかった参照 %d件: %s' % (len(missing), ', '.join(missing[:5])))
    if rest:
        print('  🚨 相対パスが残っている %d件: %s' % (len(rest), ', '.join(rest[:5])))
        print('     → このファイルだけ送ると欠ける。元HTMLの参照を確認する')
        return 2
    if missing:
        return 2
    print('  ✅ 外部参照なし。このファイル1つで開ける')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
