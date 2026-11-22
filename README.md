# なになにKit

ブラウザとlocalhostで使える12のローカルツールです。
入口は **`kits.html`**。まずこのファイルをダブルクリックしてください。

| キット | 用途 |
|---|---|
| SlideKit | HTMLスライドの作成・編集・発表・PPTX変換（PPTXの取り込みも） |
| CalcKit | 式・複数シート・Excel相互コピペ・xlsxの読み書きに対応した表計算 |
| BezierKit | 画像トレース・可変線幅に対応したベジェ描画・資料用アイコン178個 |
| CadKit | スケッチ拘束・押し出し・回転・STEP入出力・三面図に対応したブラウザ3D CAD |
| PictureKit | RAW現像・非破壊補正・JPEG書き出し |
| DocKit | 手元のMarkdown文書の索引・検索・参照切れ・決定と宿題の台帳 |


## 使い方

各キットの詳しい入口と検証コマンドは `kits.html` にあります。
PPTX・Excel変換の一部機能では `python-pptx` と `openpyxl` を使用します。

DocKit と ResearchKit は、手元の文書や案件を `scan.js`（`node scan.js`）で読んで索引を作ります。
索引（`catalog-data.js` など）と案件の中身は配布物に含みません。

CaptureKit の常駐取り込みを使う場合は、`capturekit-app.applescript` と `*.plist` 内の
`/PATH/TO/...` を自分の環境のパスへ変更してください。
PictureKit は `python3 -m venv PictureKit/.venv` で環境を作り、requirementsを導入して
`PictureKit/PictureKit.command` から起動します。RAWと書き出し画像は配布物に含みません。

## 外部通信

CadKitはThree.js等をunpkg/jsDelivrから実行時に読み込みます。
BezierKitは描画ライブラリとフォントを `BezierKit/vendor/` に同梱しており、CDNなしで動きます。
PictureKitは画像を外部送信せず、localhost内で処理します。
CDNを制限する環境ではCadKitの一部機能を利用できません。

## ライセンス

MIT（`LICENSE`）。CadKitがCDNから読み込むOCCT WebAssemblyはLGPL-2.1です。
BezierKitに同梱したフォントはSIL Open Font Licenseです（`BezierKit/vendor/fonts/`）。
詳細は `THIRD-PARTY-NOTICES.md` を参照してください。
