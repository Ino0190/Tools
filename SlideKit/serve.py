#!/usr/bin/env python3
"""SlideKit 保存対応サーバー

python3 -m http.server の代替。ブラウザからの PUT でカレントディレクトリ配下の
HTMLを上書き保存できる。SlideKit の「💾保存」ボタンを押すと、ダウンロードでなく
そのままワークスペースの元HTMLに書き戻される。

使い方:
    python3 SlideKit/serve.py            # ポート8130で起動（既定）
    python3 SlideKit/serve.py 8200       # ポート指定

セキュリティ:
- ローカル専用: 127.0.0.1 にのみバインド（LAN側からは繋げない）
- PUT の書き込み先はカレントディレクトリ配下の *.html のみ（新規作成は不可）
- Origin ヘッダ検証: localhost / 127.0.0.1 の同一ポートのみ許可、それ以外は 403
- パス検証: realpath + commonpath で symlink 攻撃・親ディレクトリ脱出を防止
- サイズ上限: 20MB (これを超える PUT は 413)
- 書き込みはアトミック (tempfile + fsync + os.replace) で書き途中クラッシュから守る
- バックアップ: 保存前の内容を .bak として残す (直前1世代のみ)
"""
import sys
import os
import stat
import tempfile
import shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote, urlparse

PORT = 8130
MAX_PUT_SIZE = 20 * 1024 * 1024  # 20 MB


def _is_allowed_origin(origin, port):
    """Origin ヘッダが同一ホスト(localhost/127.0.0.1)+同一ポートなら許可。
    Origin ヘッダ無し(同一オリジンfetch)も許可。"""
    if not origin:
        return True
    try:
        u = urlparse(origin)
    except Exception:
        return False
    if u.scheme not in ('http', 'https'):
        return False
    if u.hostname not in ('localhost', '127.0.0.1'):
        return False
    if u.port != port:
        return False
    return True


def _safe_resolve(rel_path, cwd_real):
    """相対パスをカレントディレクトリ配下の実パスに解決する。
    symlink や '..' で親ディレクトリを脱出しようとしたら None を返す。"""
    abs_path = os.path.abspath(rel_path)
    real_path = os.path.realpath(abs_path)
    try:
        common = os.path.commonpath([real_path, cwd_real])
    except ValueError:
        return None
    if common != cwd_real:
        return None
    return real_path


class Handler(SimpleHTTPRequestHandler):
    def _check_origin(self):
        origin = self.headers.get('Origin')
        if not _is_allowed_origin(origin, PORT):
            self.send_error(403, f'Forbidden origin: {origin}')
            return False
        return True

    def do_PUT(self):
        if not self._check_origin():
            return
        cwd_real = os.path.realpath('.')
        path = unquote(self.path.lstrip('/').split('?', 1)[0])
        abs_path = _safe_resolve(path, cwd_real)
        if abs_path is None:
            self.send_error(403, 'Forbidden (outside workspace or symlink escape)')
            return
        if not abs_path.lower().endswith(('.html', '.htm')):
            self.send_error(403, 'Only .html files can be saved')
            return
        if not os.path.isfile(abs_path):
            self.send_error(404, 'File not found (create the file first)')
            return
        # Content-Length 検査 (上限 + 必須)
        clen_hdr = self.headers.get('Content-Length')
        if clen_hdr is None:
            self.send_error(411, 'Content-Length required')
            return
        try:
            length = int(clen_hdr)
        except ValueError:
            self.send_error(400, 'Invalid Content-Length')
            return
        if length < 0 or length > MAX_PUT_SIZE:
            self.send_error(413, f'Payload too large (limit {MAX_PUT_SIZE} bytes)')
            return
        try:
            data = self.rfile.read(length)
            if len(data) != length:
                self.send_error(400, 'Incomplete body')
                return
            # バックアップ (直前 1 世代)
            bak_path = abs_path + '.bak'
            try:
                shutil.copyfile(abs_path, bak_path)
            except Exception:
                pass  # バックアップ失敗は書き込みを止める理由にはしない
            # 元ファイルの権限を保存 (tempfile.mkstemp は 0600 で作るため、そのまま
            # os.replace すると元ファイルの権限が失われる)
            try:
                original_mode = stat.S_IMODE(os.stat(abs_path).st_mode)
            except Exception:
                original_mode = 0o644
            # アトミック書き込み: 一時ファイル → fsync → 権限復元 → os.replace
            dir_ = os.path.dirname(abs_path) or '.'
            fd, tmp_path = tempfile.mkstemp(
                prefix='.slidekit_', suffix='.tmp', dir=dir_)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.chmod(tmp_path, original_mode)
                except Exception:
                    pass  # 権限設定失敗しても書き込みは続行
                os.replace(tmp_path, abs_path)
            except Exception:
                if os.path.exists(tmp_path):
                    try: os.remove(tmp_path)
                    except: pass
                raise
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            rel = os.path.relpath(abs_path, cwd_real)
            self.wfile.write(f'OK: saved {rel} ({len(data)} bytes)'.encode('utf-8'))
            print(f'  ✅ PUT {rel} ({len(data)} bytes)')
        except Exception as e:
            self.send_error(500, f'Write failed: {e}')

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        if not _is_allowed_origin(origin, PORT):
            self.send_error(403, f'Forbidden origin: {origin}')
            return
        self.send_response(204)
        self.send_header('Allow', 'GET, HEAD, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('X-SlideKit-Server', '1')
        self.end_headers()

    def end_headers(self):
        self.send_header('X-SlideKit-Server', '1')
        super().end_headers()


def main():
    global PORT
    if len(sys.argv) > 1:
        try:
            PORT = int(sys.argv[1])
        except ValueError:
            print(f'不正なポート番号: {sys.argv[1]}')
            sys.exit(1)
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'SlideKit 保存対応サーバー起動')
    print(f'  URL:  http://127.0.0.1:{PORT}/')
    print(f'  ROOT: {os.getcwd()}')
    print(f'  💾保存でPUT書き戻し・GETは通常のhttp.serverと同じ')
    print(f'  上限: {MAX_PUT_SIZE // (1024*1024)} MB / .bak バックアップあり')
    print(f'  停止: Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n停止')


if __name__ == '__main__':
    main()
