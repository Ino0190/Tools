# なになにKit

ビルドやサーバーなしで、ブラウザから直接使える5つのローカルツールです。
入口は **`kits.html`**。まずこのファイルをダブルクリックしてください。

| キット | 用途 |
|---|---|
| SlideKit | HTMLスライドの作成・編集・PPTX変換 |
| CadKit | スケッチ拘束・押し出し・回転・STEP入出力に対応したブラウザ3D CAD |
| BezierKit | 画像トレース・可変線幅に対応したベジェ描画 |
| CaptureKit | スクリーンショットの保存・検索・画像編集 |
| CalcKit | 式・複数シート・Excel相互コピペに対応した表計算 |

## 使い方

各キットの詳しい入口と検証コマンドは `kits.html` にあります。
PPTX・Excel変換の一部機能では `python-pptx` と `openpyxl` を使用します。

CaptureKit の常駐取り込みを使う場合は、`capturekit-app.applescript` と `*.plist` 内の
`/PATH/TO/...` を自分の環境のパスへ変更してください。

## 外部通信

CadKitはThree.js等をunpkg/jsDelivr、BezierKitは描画ライブラリとフォントを
jsDelivr等のCDNから実行時に読み込みます。CDNを制限する環境では一部機能を利用できません。

## ライセンス

MIT（`LICENSE`）。CadKit同梱のOCCT WebAssemblyはLGPL-2.1です。
詳細は `THIRD-PARTY-NOTICES.md` を参照してください。
