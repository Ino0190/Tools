# CaptureKit

Snagit代替。撮影はmacOS標準の`screencapture`に任せ、保存形式は常にPNG/MOV。
日付フォルダで管理し、カタログHTMLで一覧、Kiroで整理する。

## 構成

| ファイル | 役割 |
|---|---|
| `capture.sh` | 撮影→`shots/YYYY-MM-DD/cap_HHMMSS.png`保存＋クリップボードコピー |
| `scan.js` | shotsを走査して`catalog-data.js`を生成（tags/group/noteは保持） |
| `index.html` | カタログ。file://ダブルクリックで開く。検索・グループ絞り込み・ライトボックス |
| `edit.html` | 画像エディタ。クロップ（矩形/丸抜き/角丸）・矢印・枠・テキスト・モザイク |
| `catalog-data.js` | カタログデータ正本。Kiroが直接編集する対象 |
| `check.py` | 検証。静的チェック＋JS構文＋Chrome headlessでピクセル処理の自己テスト |

## 撮影（ターミナル不要）

`CaptureKit.app` をダブルクリック → モード選択が出る。

| ボタン | 動作 |
|---|---|
| 撮影（Enterでもこれ） | 範囲選択スクショ。ドラッグ中スペースキーでウインドウ認識に切替 |
| クロップ | 撮影→プレビュー.appが開く→⌘Kクロップ→⌘S |
| 録画 | 画面録画（MOV）。メニューバーの■で停止 |

FinderからDockにドラッグしておけば、クリック→Enterで撮れる。
初回起動時に「画面収録」の許可を求められたら許可→もう一度実行。
アプリの中身は `capturekit-app.applescript`（変更したら `./build-app.sh` で再ビルド。
osacompile単体だとバンドルIDが付かず権限リストに出ないので必ずこのスクリプトを使う）。

### 権限ダイアログで「拒否」を押してしまったら

システム設定 → プライバシーとセキュリティ → 画面収録 で CaptureKit をオンにする。
一覧に出てこない場合は `./build-app.sh` で作り直すと新しいアプリ扱いになり、次回起動時にダイアログが出直す。

### コマンドで使う場合

```bash
CaptureKit/capture.sh          # 範囲選択スクショ（デフォルト）
CaptureKit/capture.sh edit     # 撮影→プレビュー.appで開く（クロップ用）
CaptureKit/capture.sh window   # ウインドウ選択
CaptureKit/capture.sh full     # 全画面
CaptureKit/capture.sh video    # 画面録画（MOV）。メニューバーの■で停止
```

- **範囲選択中にスペースキーでウインドウ認識モードに切替**（Snagitと同じ。1つのホットキーで枠指定もウインドウ撮影もできる）
- 画像はクリップボードにも入る→SlideKitのプレースホルダーに⌘Vでそのまま差せる
- 録画は初回に「画面収録」の許可が必要（システム設定→プライバシーとセキュリティ）

## エディタ（edit.html・2026-08-02追加）

カタログ右上の「✎ エディタ」か `edit.html` を直接開く。Photoshopミニ版というより
「Snagitの編集画面」相当。スライド貼り付け前の加工はここで完結する。

- **入力**: 画像をドラッグ＆ドロップ／⌘V（capture.shで撮った直後はクリップボードに
  入っているのでそのまま貼れる）／「開く」ボタン。
  ※shots内の画像を直接読まないのはfile://のCanvas汚染（保存不能になる）を避けるため
- **クロップ3種**: 矩形／**丸抜き**／角丸。丸と角丸は**透過PNG**になるので
  スライドに置くと背景が抜ける。ドラッグ→Enterで確定・Escで取消
- **注釈**: 矢印・枠・丸枠・テキスト（白文字は自動で縁取り）・モザイク（個人情報隠し）。
  焼き込みは書き出し時なので、選択ツールで移動・削除・色変えがいつでもできる
- **出力**: 「📋 コピー」→スライドやKeynoteに⌘Vで直貼り／「⬇ PNG保存」→ダウンロード
- **ショートカット**: V選択 C矩形 O丸 R角丸 A矢印 F枠 E丸枠 Tテキスト Mモザイク・
  ⌘Z戻す・⌘Cコピー・⌘S保存
- 検証: `python3 CaptureKit/check.py`（Chrome headlessで切り抜き・モザイクの
  ピクセル単位テスト18件を含む）

## クロップ（プレビュー.app経由・従来の方法）

- `capture.sh edit` で撮ると直後にプレビュー.appが開く。範囲選択→⌘Kでクロップ→⌘Sで**shots内のファイルがそのまま更新される**
- editモードはクリップボードに入れない（クロップ前の画像で紛らわしいため）。クロップ後にプレビューで⌘A→⌘C
- 撮影済みの画像を後から切るときは、shots内のファイルをプレビューで開いて同じ手順。次の`node scan.js`でカタログの縦横も自動で取り直される
- Kiroに「この画像の右半分だけにして」等と頼んでもいい（sipsで切る）

## ホットキー割当（⇧⌘C推奨・設定は1回だけ）

Dockクリックより速くしたい場合。ショートカット.app → 新規ショートカット →
アクション「シェルスクリプトを実行」→ `/PATH/TO/KitsRepo/CaptureKit/capture.sh` →
詳細（ⓘ）でキーボードショートカット⇧⌘Cを割当。
クロップをよく使うなら`capture.sh edit`を⌥⇧⌘C等で2つめに登録。
アプリ内ショートカットと被る場合（TextEditのスタイルコピー等）は⌃⌘Cに変える。

## Kiroで整理する

カタログを見せて「今日の分をグループ化して」「タグ付けて」と言えば、
Kiroが画像の中身を確認して`catalog-data.js`の`tags`/`group`/`note`を書き込む。
ブラウザをリロードすれば反映される。`node scan.js`を再実行しても編集は消えない。

## 手持ち画像の取り込み

`shots/YYYY-MM-DD/`にPNG/JPG/MOV等を置いて`node scan.js`。

## Snagit資産の移行（2026-08-01 全量取り込み済み・自動同期あり）

```bash
node import-snagit.js --limit 100   # お試し（件数指定）
node import-snagit.js               # 全量（画像4442枚≒3.8GB抽出・10〜20分）
```

- 画像(.snagx)は中のPNGを`shots/`へ抽出。SnagitのOCRテキスト・ウインドウ名・アプリ名も
  カタログに入り、検索窓で「画面の中の文字」からヒットする
- 動画(.mp4/.mov 158本≒13GB)はコピーせず`~/Pictures/Snagit/`を絶対パス参照（消すとカタログからも消える）
- 何度実行しても二重取り込みしない。取り込み済み分は`tags: ["snagit"]`が付く
- 注意: Documentsを iCloud 同期している場合は抽出3.8GB分のアップロードが走る

### 自動同期（launchd・2026-08-01設置）

Snagitで新しくキャプチャすると、自動で`import-snagit.js`が走ってギャラリーに載る。
手で取り込む必要はない（リロードするだけ）。

- 正本: `CaptureKit/local.capturekit.capturekit-snagit.plist`（`~/Library/LaunchAgents/`にコピーして使用）
- 仕組み: launchdの`WatchPaths`で`~/Pictures/Snagit/`を監視。変化から最短120秒間隔で実行
- ログ: `CaptureKit/import-snagit.log`
- **状態確認: `python3 CaptureKit/sync-status.py`**（エージェント生存・最終実行・未取込の有無・カタログ件数を一発で出す）
- 止めたいとき: `launchctl bootout gui/$(id -u)/local.capturekit.capturekit-snagit`
- 再開: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.capturekit.capturekit-snagit.plist`
- 即時実行: `launchctl kickstart gui/$(id -u)/local.capturekit.capturekit-snagit`

## やらないこと

- ~~注釈・矢印・モザイク~~（2026-08-02 edit.htmlで実装済み）
- レイヤー合成・ブレンドモード・自動選択・コンテンツ認識塗りつぶし（そこまで行くと本家Photoshopの領分）
- 動画のサムネイル生成（`<video preload="metadata">`の先頭フレームで代用）
