# Kits — file://で動く自作ツールキット群

ブラウザだけで動く（ビルドなし・サーバ不要・`file://`ダブルクリック起動）ツールキット集。
入口は **`kits.html`**。各キットの関係はキット間のコピペ（SVG・JSON・HTML片）で緩く繋がる。

| キット | 何をするか |
|---|---|
| SlideKit | スライドをHTMLで作りPPTXへ変換。ブラウザ上で直接編集 |
| DashboardKit | ダッシュボード部品（KPI・グラフ・テーブル・テーマ6種） |
| ArchKit | ホバー詳細＋フローアニメ付きAWS構成図。データ差し替えで量産 |
| CadKit | ブラウザ3D CAD（スケッチ拘束→押し出し・回転・STEP入出力） |
| BezierKit | イラレ風ベジェ描画。画像トレース・筆線・可変線幅 |
| CaptureKit | スクリーンショットのカタログ＋画像エディタ |
| DocKit | .md群のカタログビューア＋決定・宿題台帳＋Word書き出し |
| GanttKit | 触れるガントチャート（タイムカーソル） |
| CalcKit | 表計算（自前式エンジン・Excel相互コピペ・.xlsx書き出し） |
| DesignKit | キット共通デザインシステム（ここを変えると全体が変わる） |

## クローン後の初期化

生成物はリポジトリに含めていない。使う機能に応じて:

```bash
node DocKit/scan.js            # DocKitの文書カタログ生成
node DocKit/ledger-scan.js     # 決定・宿題台帳
node DocKit/skills-scan.js     # スキル・ステアリング一覧（Kiro併用時）
```

PPTX変換等のPython系は `python-pptx` `openpyxl` `python-docx` を使う。

CaptureKit の常駐取り込み（`capturekit-app.applescript` / `*.plist`）内の
`/PATH/TO/...` は自分の環境のパスに書き換えてから使う（テンプレート化してある）。

## 外部通信

ArchKitはAWSアイコンをjsDelivr、CadKitはThree.js等をunpkg/jsDelivr、
BezierKitは描画ライブラリと選択フォントをjsDelivrまたはraw.githubusercontent.comから取得する。
オフライン環境や外部CDNを制限するネットワークでは、一部機能を利用できない。

## 検証

多くのキットに自動テストがある（`check.py` / `cdp-check.py` / `npm test`）。
ヘッドレス検証はmacOS＋Google Chromeを前提にしている。

## ライセンス

MIT（`LICENSE`）。ただし CadKit が同梱する OCCT の wasm ビルドは LGPL-2.1 —
詳細は `THIRD-PARTY-NOTICES.md`。
