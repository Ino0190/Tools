# vendor/fonts/

BezierKit の「文字」機能が相対パスで読み込む日本語フォント。すべて単一の OTF/TTF で、
opentype.js 1.3.4 がそのままパースできる（woff2・分割版は使わない）。

## Noto Sans/Serif CJK JP（日本語サブセット）

- `NotoSansCJKjp-Regular.subset.otf` / `-Bold.subset.otf`
- `NotoSerifCJKjp-Regular.subset.otf` / `-Bold.subset.otf`
- 元は [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) の静的 OTF（Sans 16–17MB・Serif 24–25MB）を
  `fonttools`（pyftsubset）で日本語の実用範囲にサブセット化したもの。各 4.8–6.7MB。
- ライセンス: SIL Open Font License 1.1（`OFL-NotoCJK.txt`）。
- 再生成: `sh make_noto_subset.sh`（下記 `.venv-fonttools` と `/tmp/noto/` の元 OTF が要る）。

## 再生成用（配布には含めない）

- `.venv-fonttools/` — fonttools + brotli を入れた隔離 venv（約23MB）。システムの python には入れていない。
  作り直す場合: `python3 -m venv .venv-fonttools && .venv-fonttools/bin/pip install fonttools brotli`
- `/tmp/noto/` の元 OTF（未同梱・サイズのため）も再生成時のみ。
- これらは BezierKit の配布物には含めない。
