# SlideKit — PPTXスライド編集キット

HTMLで書いたスライドを、**ブラウザ上で直接編集**して、**PPTXに変換**できるキット。
スライドは1280×720px固定で、全要素が絶対座標のdata属性（`data-x/y/w/h`等）を持つ方式。
AI（Kiro等）にHTMLを生成させ、人がブラウザで微調整し、確定したらPPTXにする流れを想定している。

```
AIがHTML生成 → ブラウザで編集（✏️） → PPTX変換（html_to_pptx.py）
```


## 一番かんたんな使い方（推奨）

このフォルダごと自分のワークスペースに置いて、AIエージェント（Kiro / Amazon Quick）に
**「SlideKitでスライドを作って」＋内容**を伝えるだけ。1行読み込みもPPTX変換もAIがやる。
（Kiro・Amazon Quickの両方で動作確認済み）

以下は、人が手で書く場合と仕組みを知りたい人向けの説明。

## 使い方（新しいスライドを作るとき）

前提: スライドHTMLは `SlideKit/` と同じ親フォルダ配下のプロジェクトフォルダに置く想定
（例: `ワークスペース/MyDeck/slides.html` と `ワークスペース/SlideKit/`）。
以下の `../SlideKit/` はこの配置での相対パス。

1. `slide-template.html` をコピーして中身（スライド）を書く／Kiroに書いてもらう
2. `<body>` 末尾に次の1行があること（HTMLからの相対パスで指定）:

   ```html
   <script src="../SlideKit/slide-edit.js"></script>
   ```

3. ローカルサーバーで開く（推奨）:

   ```
   # SlideKit 保存対応サーバー (💾保存でワークスペースに直接書き戻せる)
   python3 SlideKit/serve.py 8130
   # または http.server (保存はダウンロードのみ)
   python3 -m http.server 8130
   ```
   → `http://localhost:8130/フォルダ/ファイル.html`

   ※編集・閲覧だけなら `file://` 直開きでも動く（script読み込みのみ・fetch不使用のため）。
   💾保存のワークスペース直接書き戻しは serve.py 経由の時だけ。それ以外はダウンロード保存になる。
   ※サーバーは**ワークスペースルート**（SlideKitフォルダの親）で起動する。深い階層で起動するとSlideKit本体が404になる。

4. 既定は閲覧モード。右上の「✏️ 編集」を押すと編集できる。

## できること

| パネル | 機能 |
|---|---|
| ✏️ 編集 | 移動 / リサイズ / 矢印キー微調整 / Shift複数選択 / グループ移動・同倍率リサイズ / ⌘Z |
| 📂 開く | 保存済みのスライドHTMLを選んで読み込み、その場で編集（slide-template.html を汎用エディタとして使える） |
| 🎯 選択中 | 文字色・背景色 / フォントサイズ・太字 / 箇条書き(・①②③・ぶら下げ字下げ) / 整列 |
| 🎨 カラーパレット | バッジ/タイトル/サブ/本文/カード/赤 を全スライド一括置換 |
| 📄 ページ操作 | ページ枠クリックで選択 → 複製 / 追加 / 並べ替え / 削除 / 背景色 |
| 🖼 画像 / ▦ 表 | クリック配置・ドロップ・⌘V貼り付け |
| 🧩 AI図解相談 | 対象ページから「案だけ」「書き換え依頼」のプロンプトを生成してコピー |
| ✍️ ラフ | 叩き台の間は手書きフォント＋「ラフ」印で表示（見た目だけ・データ不変）。確定したらOFF |
| 📺 プレゼン再生 | 別ウィンドウ投影 / ページ送り / レーザー / ペン / 🗒メモ（現在ページへ追加・即入力・選択枠の−/＋で文字サイズ変更・投影同期） |
| 📋 変更をコピー | 編集内容を「Kiro貼付用パッチ」で出力 → Kiroに貼ると本体ファイルに反映 |
| 📍 参照 | 選択オブジェクトの位置ID＋outerHTMLをコピー（変換指示用） |
| 💾 保存 | 編集UIを除いたクリーンHTMLを保存（serve.py 使用時はワークスペースに直接書き戻し・data-\*/style 正規化＋不一致件数のログ出力あり） |

「🧩 AI図解相談」は、ページ選択、選択中オブジェクトのページ、画面中央の順で対象を決める。ページ内容を外部へ自動送信せず、サニタイズしたHTMLを含むプロンプトだけをクリップボードへコピーする。Kiroへ貼り付けると、図解案の検討または対象ページの書き換えを依頼できる。

## 2通りの保存・反映

- **💾保存**：DOM全体をクリーンHTMLで書き出す。**迷ったらこちらでいい**
- **📋パッチ → Kiroに貼る**（Kiro併用時のみ）：位置・色・サイズ等の微調整差分をKiroが本体HTMLに反映。AIとの往復で編集履歴を残したい時に使う

localStorageには保存しない＝**HTML本体が唯一の正本**（Kiroの編集と衝突しない）。
💾保存はページ番号を一旦外して書き出す → 再オープン時に自動採番が振り直す（複製・追加ページも正しい連番に）。

## 既存デッキを開いて編集する（📂 開く）

`slide-template.html` を開く → 右上「📂 開く」→ 保存済みのスライドHTMLを選ぶ → その中の `.slide` を読み込んで編集できる。`slide-template.html` が「どのデッキでも開ける汎用エディタ」になる。
- 読み込むのは `.slide` 要素だけ（標準CSSはテンプレート側のものを使う）。**独自の `<style>` を持つ凝ったデッキは見た目が変わることがある** → そのデッキは自分のHTMLを直接開いて編集する方が確実。
- `file://` で開いても動く（fetchを使っていないため）。

## 📺 プレゼン再生（別ウィンドウ・Zoom画面共有向け）

`slide-present.js`（別ファイル・独立）を追加読み込みすると、**別ウィンドウでフルスクリーンのスライドショー**を開ける。Zoom や Meet で「そのプレゼンウィンドウだけ」を画面共有すれば、ブラウザのアドレスバーや SlideKit ツールバー・他のアプリが相手に写り込まない。

### 読み込み

`slide-edit.js` の次の行に 1 行追加：

```html
<script src="../SlideKit/slide-edit.js"></script>
<script src="../SlideKit/slide-present.js"></script>
```

編集モードの左上に **「📺 プレゼン再生」** ボタンが出る。

### 使い方

1. 手元ブラウザでスライドを開いて編集（いつも通り）
2. 左上「📺 プレゼン再生」をクリック → 別ウィンドウがプレゼンモードで開く
3. そのウィンドウを外部モニターにドラッグ or F キーでフルスクリーン化
4. Zoom で画面共有 → **「Chrome ウィンドウ」→ プレゼンウィンドウだけ**を選ぶ
5. 手元は SlideKit 編集モードのまま。左下のリモコン（◀ ▶ ・ 3/24 ・ ✕）で操作
6. プレゼン側でも矢印キー・スペース・ホイールで送り

### ナビゲーション

**プレゼン側キー操作**

| キー | 動作 |
|---|---|
| → / Space / PageDown / N | 次のスライド |
| ← / PageUp / Backspace / P | 前のスライド |
| Home / End | 最初 / 最後 |
| F | フルスクリーン切替 |
| Esc | フルスクリーン解除、または ウィンドウを閉じる |
| マウスホイール | 前/次 (300ms cooldown) |

**手元側のリモコン**

- ◀ / ▶ ボタンでスライド送り
- ⏮ / ⏭ で最初/最後
- 🔍 手前へ ボタンでプレゼンウィンドウを前面化
- ✕ 閉じる でプレゼン終了
- 手元での矢印キー (←/→/PageUp/PageDown) も動く
- 🔴 レーザー：手元のマウス位置に赤い点を表示（両側同期）
- ✏️ ペン：ドラッグで赤い線を描画、スライドを跨いで保存（両側同期）
- 🗑 消す：ペン線を全消し
- 🗒 メモ：現在のスライドにポストイット（薄黄・300×150px）を追加して即入力。相手の発言をその場で書き留める用。移動・リサイズ・選択枠右上の−/＋で文字サイズ変更ができ、💾保存でHTMLに残りPPTXでも編集可能。ペンと違い記録として残る
- 📄 ページジャンプ：全ページのタイトル一覧から直接飛べる
- ライブ編集同期：手元で編集した内容が 300ms 後にプレゼン側に反映（構造変更＝ページ追加/削除/並べ替えも同期）

### 仕組み

- URL パラメータ `?present=1&hideUI=1&session=<UUID>` を付けて `window.open` で別ウィンドウ起動
- 手元 ↔ プレゼン間の同期は `BroadcastChannel('slidekit_present_' + pathname + '_' + sessionId)`
  - セッション ID (UUID) は起動時に生成、URL にも埋め込む。同じデッキを複数タブで開いても混線しない
- プレゼン側にはリアルタイム編集同期 (`slide:update`) + 構造変更同期 (`deck:sync`) を実装
- 観客側のページ番号は `<html data-present-counter="off">` または `?counter=0` で非表示にできる
- プレゼン側は body に `_sp_active` クラスを付けて、`.slide` 以外の要素（ツールバー含む）を CSS で全部隠す
- スライドは `position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(fitScale)` で全画面センタリング＋アスペクト維持で拡縮
- letterbox（余白部分）は黒

## 動作要件

- **編集・閲覧**: ブラウザだけ（Chrome推奨・macOS Chrome/Safariで確認済み。Windowsは未検証）

### Macの人だけ: Meiryo UIのセットアップ（1回だけ・推奨）

PPTXの書き出しフォントは既定でMeiryo UI。MacにはMeiryo UIが無いため、ブラウザのプレビューは
ヒラギノ（約18%幅広）で代替表示され、**プレビューとPPTXで改行位置・中央揃えがズレる**。
PowerPoint for Macに同梱のメイリオを自分のフォントフォルダへコピーすると一致する:

```bash
cp "/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts/meiryo.ttc" \
   "/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts/meiryob.ttc" \
   ~/Library/Fonts/
```

- AI（Kiro / Amazon Quick）に「SlideKitのREADMEにあるMeiryo UIセットアップをして」と頼めば実行してくれる
- やらなくても動く（プレビューの改行位置がPPTXと少しズレるだけ）
- フォントはOfficeのライセンス物。リポジトリへの同梱・再配布はしない（各自のOfficeからコピー）
- Windowsは標準搭載のため作業不要
- **PPTX変換**: Python 3.10以上 + `pip install -r SlideKit/requirements.txt`（python-pptx / beautifulsoup4 / lxml / Pillow）
- **SVG図の変換・レイアウト診断(run_check.py)**: Chrome/Chromium/Edge が必要（`CHROME_PATH` 環境変数でパス指定可）

- ⚠️ 「📂開く」で読み込むHTMLは**信頼できるもの（自分やKiroが作ったデッキ）だけ**にする

## PPTX変換

キット同梱の `html_to_pptx.py` で変換（依存は上の「動作要件」参照）。

```
python3 ../SlideKit/html_to_pptx.py 自分のスライド.html        # → 同名 .pptx を出力
python3 ../SlideKit/html_to_pptx.py 自分のスライド.html 出力.pptx
```

data属性（data-x/y/w/h, data-font-size, data-bold, data-color, data-fill, data-bg, data-bg-gradient, data-align, **data-bullet**）を読む。
- ✅ ページ背景色：`data-bg-gradient` が無く `data-bg` があれば単色背景（背景色変更・グラデ解除に対応）
- ✅ 箇条書き（文字マーカー方式）：`data-bullet`（disc/decimal）で段落にぶら下げ字下げ（marL/indent）を設定＝折り返しがマーカー下に潜らない
- ✅ 箇条書き（PowerPointネイティブ方式）：`data-bullet`（native-disc/native-decimal）＋子要素 `.li[data-lvl]`。マーカーは PowerPoint が描く（`buChar` / `buAutoNum`）ので、変換後も Enter で次項目にマーカーが付き、Tab / Shift+Tab で階層が変わる（`lstStyle` に5レベル分の字下げを書き出す）。詳細は SPEC.md 5.2.1
- 画像は HTML ファイルからの相対パスで解決（WebPは事前にJPG変換）
- ✅ `.flow`（フロー図ノード）：角丸矩形（roundRect）として変換
- ✅ SVG図（ファネル等）：Chrome headless で PNG にラスタライズし、ラッパーの data-x/y/w/h と同じ位置・サイズで配置（2倍解像度・透過背景・見た目はブラウザと一致）。**Chrome が必要**（`CHROME_PATH` 環境変数でパス指定可）。Chrome が無い場合は **exit code 2 で失敗** + 出力ファイル名を `xxx.incomplete.pptx` に変えて完成品と区別する。`--allow-missing-assets` フラグで警告付き続行も可能（通常名で保存）
- ✅ SVG単体ファイルも書き出し：`<出力名>_svg/S{枚}_x{X}_y{Y}_{W}x{H}.svg`。**PowerPointへ手動でドラッグ＆ペースト**するとベクターで鮮明＆編集可能（元HTMLから生SVGを抽出するので viewBox/linearGradient の大小文字が壊れない）。PNGは位置の目印として残るので、上から差し替える運用
- 🟡 注意：SVG上に重ねる透明ラベル（`.tb`）は別テキストボックスとして出力される。HTML上で SVGラッパーより後ろに置くと PPTX で前面に来る（番号が図の裏に隠れる場合は順序を確認）

AWS提案用テンプレ（ロゴ・フッター継承）は `<html data-template="aws">` を付ければ `html_to_pptx.py` が対応する（テンプレPPTXの検索順は SPEC.md 8.4 参照）。

## 📄 A4 縦への変換出力（PDF / PPTX）

1280×720 で作った既存のスライドを、そのまま A4 縦の配布資料に変換して出力する。既存デッキは 1 文字も変更されない（オプトイン機能）。

### PDF 出力（ワンクリック）

`slide-a4export.js` を読み込むと、SlideKit ツールバー下部に「📄 A4縦PDF出力」パネルが出る。

```html
<script src="../SlideKit/slide-a4export.js"></script>
```

- **1スライド/1ページ**：1 枚を A4 上部にセンタリング（下は空白でメモ欄に）
- **2スライド/1ページ**：PowerPoint「配布資料 2 スライド」相当

ボタン押下 → 印刷ダイアログ → PDF として保存。

### PPTX 出力（CLI）

```bash
python3 ../SlideKit/html_to_pptx_a4.py slides.html                    # 既定 1up
python3 ../SlideKit/html_to_pptx_a4.py slides.html out.pptx --layout=2up
```

A4 縦 (210×297mm) の PPTX が出力される。既存の `html_to_pptx.py` の描画ロジックを再利用しつつ、座標変換だけ A4 用にスケール。

## AI にスライドを生成させる時（Kiro 等）

`pattern-catalog.html` と `slidekit-steering.md` を用意している。

- **`pattern-catalog.html`**：14 種類の標準パターン（P01 表紙〜P14 Thanks）の見本帳。Kiro に「この中から選んで内容を差し替えて」と指示すれば、毎回同じ座標系・同じ配色でスライドが生成される
- **`diagram-catalog.html`**：図解パターンの見本帳（D01 判定フロー〜D10 境界図＋D11 図解プレースホルダー）。全部PPTXネイティブ図形＝座標計算済みで、文字と表に寄りがちなAI生成スライドに図解の選択肢を与える
- **`slidekit-steering.md`**：AI に対する「絶対規則」「カラートークン」「幾何定数」「パターン選択ガイド」を集約した文書。Kiro の steering として読み込ませる（`.kiro/steering/` に入れる）

AI を使わない場合も、`pattern-catalog.html` はデザイン参照＋座標コピー元として有用。

## 由来

スライド編集で繰り返し使う操作を抽出して汎用化したもの。
以降の新規スライドはこのキットを標準として使う。
