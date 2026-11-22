# Third-Party Notices — BezierKit/vendor/

BezierKit はこのフォルダのライブラリを相対パスで読み込み、CDN には接続しない
（file:// で動く・外部へ何も送らない方針）。各ライブラリは元の配布物をそのまま同梱し、
各自のライセンスに従う。BezierKit 自体のライセンスはリポジトリの `LICENSE`（MIT）。

## paper.js 0.12.18 — MIT

- ファイル: `paper-full.min.js`
- 取得元: <https://cdn.jsdelivr.net/npm/paper@0.12.18/dist/paper-full.min.js>
- Copyright (c) 2011–2020 Jürg Lehni & Jonathan Puckey
- ライセンス: MIT（<https://github.com/paperjs/paper.js/blob/develop/LICENSE.txt>）
- 配布物に Straps.js（MIT）・Acorn.js（MIT）を含む

## paperjs-offset 1.0.8 — MIT

- ファイル: `paperjs-offset.min.js`
- 取得元: <https://cdn.jsdelivr.net/npm/paperjs-offset@1.0.8/dist/paperjs-offset.min.js>
- ライセンス: MIT（<https://github.com/glenzli/paperjs-offset/blob/master/LICENSE>）

## opentype.js 1.3.4 — MIT

- ファイル: `opentype.min.js`
- 取得元: <https://cdn.jsdelivr.net/npm/opentype.js@1.3.4/dist/opentype.min.js>
- ライセンス: MIT（<https://github.com/opentypejs/opentype.js/blob/master/LICENSE>）

## pdf.js (pdfjs-dist) 4.10.38 — Apache-2.0

- ファイル: `pdf.min.mjs`・`pdf.worker.min.mjs`
- 取得元: <https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/>
- Copyright Mozilla Foundation
- ライセンス: Apache License 2.0
  （<https://www.apache.org/licenses/LICENSE-2.0>）
- ワーカーも同梱し、`pdfjsLib.GlobalWorkerOptions.workerSrc` に相対パスで渡す

## 日本語フォント（`vendor/fonts/` に同梱・SIL Open Font License 1.1）

「文字」機能で使う日本語フォントのうち、下記は `vendor/fonts/` に元の配布物
（Google Fonts の OFL 版 TTF）をそのまま同梱し、`index.html` から相対パスで読み込む。
各フォントの OFL 全文は同フォルダの `OFL-<name>.txt`。

| キー | ファイル | フォント | 著作権 |
|---|---|---|---|
| noto-sans-r/b | `NotoSansCJKjp-Regular.subset.otf`・`-Bold.subset.otf` | Noto Sans CJK JP（日本語サブセット） | © The Noto Project Authors |
| noto-serif-r/b | `NotoSerifCJKjp-Regular.subset.otf`・`-Bold.subset.otf` | Noto Serif CJK JP（日本語サブセット） | © The Noto Project Authors |
| zen-maru-r/b | `ZenMaruGothic-Regular.ttf`・`-Bold.ttf` | Zen Maru Gothic | © 2021 The Zen Maru Gothic Project Authors |
| shippori | `ShipporiMincho-Regular.ttf` | しっぽり明朝 | © 2021 The Shippori Mincho Project Authors |
| klee | `KleeOne-Regular.ttf` | Klee One | © 2020 The Klee Project Authors |
| yusei | `YuseiMagic-Regular.ttf` | Yusei Magic | © 2020 The Yusei Magic Project Authors |
| mochiy | `MochiyPopOne-Regular.ttf` | Mochiy Pop One | © 2020 The Mochiypop Project Authors |
| rocknroll | `RocknRollOne-Regular.ttf` | RocknRoll One | © 2020 The RocknRoll Project Authors |
| dot16 | `DotGothic16-Regular.ttf` | DotGothic16 | © 2020 The DotGothic16 Project Authors |

- 取得元: Google Fonts（`ofl/<name>/`）<https://github.com/google/fonts> ／ Noto は <https://github.com/notofonts/noto-cjk>
- ライセンス: SIL Open Font License 1.1（Google Fonts 版は各 `OFL-<name>.txt`、Noto は `OFL-NotoCJK.txt`）
- `opentype.js` が OTF/TTF をそのまま読める（woff2 ではない）。

### Noto の日本語サブセット化

Noto Sans/Serif CJK JP（`noto-sans-r/b`・`noto-serif-r/b`）は、元の静的 OTF が
大きすぎる（Sans 約33MB・Serif 約49MB／R+B 合計）ため、`fonttools`（pyftsubset）で
日本語の実用範囲にサブセット化して同梱した。元は notofonts/noto-cjk。

- 範囲 `--unicodes`:
  `U+0020-00FF`（基本ラテン・ラテン1）, `U+2000-27BF`（一般句読点・矢印・数学記号・罫線・丸数字 等）,
  `U+3000-303F`（CJK記号・句読点）, `U+3040-30FF`（ひらがな・カタカナ）,
  `U+4E00-9FFF`（CJK統合漢字ブロック全部＝JIS第1・第2水準を含む）, `U+FF00-FFEF`（全角英数記号・半角カナ）
- `--layout-features=''`（GSUB/GPOS を全部落とす）。BezierKit は opentype.js の `getPath`
  （cmap 直引き・GSUB 非適用）で 1 文字ずつアウトライン化するため、縦書き `vert` 等の
  異体字グリフは使われない。残すとグリフ数が 22,000→40,000 に倍増しサイズも倍増するだけ
  （落としても `getPath` の出力は 1 コマンドも変わらないことを確認済み）。
- CFF の subr（圧縮）は残す。opentype.js 1.3.4 で読めることを確認済み（`--desubroutinize` はむしろ肥大）。
- サイズ: Sans R/B 各 4.8MB・Serif R/B 各 6.6–6.7MB、合計 約22.9MB。
- 再生成: `vendor/fonts/make_noto_subset.sh`（隔離 venv `.venv-fonttools` と `/tmp/noto/` の元 OTF が要る。
  この venv と元 OTF は再生成用で、配布には含めない。詳細は `vendor/fonts/README.md`）。
