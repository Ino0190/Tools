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

## 作る流れ

コマンドはすべて**ワークスペースルート**（SlideKitフォルダの親）で実行する。例のデッキは `MyDeck/slides.html`。

1. **構成ファイルを書く**：`SlideKit/structure-template.md` をコピーして `MyDeck/slides.structure.md`（HTMLと同じフォルダ・同じ名前）にする。誰に・理解してほしいこと・相談したいこと・一番伝えたいこと・渡し方を埋め、1枚ずつ型IDを決める
2. **型を選ぶ**：`SlideKit/pattern-select.md` で6分類→型の順に絞る。実物は `pattern-catalog.html`（P01〜P18）と `diagram-catalog.html`（D01〜D16）の2本
3. **雛形をコピーする**：`SlideKit/slide-template.html` を `MyDeck/slides.html` にコピーして中身を書く（Kiroに書いてもらってよい）
4. **検査する**：`python3 SlideKit/slidecheck.py MyDeck/slides.html`（`--shot all` を付けると全ページのスクショも出る）
5. **PPTXにする**：`python3 SlideKit/slidecheck.py MyDeck/slides.html --pptx`

### 置き場所の罠

デッキは**ワークスペース直下の1階層下のフォルダ**に置く（例: `ワークスペース/MyDeck/slides.html`）。
雛形の `<script src="../SlideKit/slide-edit.js"></script>` はこの配置が前提。

- 2階層下（例: `ワークスペース/案件/slides/x.html`）に置くなら、src を `../../SlideKit/slide-edit.js` に直す
- パスが切れると、スライドは表示されるのに**編集ツールバーだけ出ない**。エラーも出ない
- `slidecheck.py` がパス切れを警告する

### 開き方

- HTMLをダブルクリック（`file://`）で開けば、閲覧も編集もできる
- 💾保存でファイルを直接上書きしたい時だけ、`python3 SlideKit/serve.py 8130` を起動して `http://localhost:8130/MyDeck/slides.html` を開く。サーバーなしの💾保存はダウンロードになる
- サーバーは必ずワークスペースルートで起動する。深い階層で起動すると SlideKit 本体が404になる

既定は閲覧モード。右上の「✏️ 編集」を押すと編集できる。

## できること

| パネル | 機能 |
|---|---|
| ✏️ 編集 | 移動 / リサイズ / 矢印キー微調整 / Shift複数選択 / グループ移動・同倍率リサイズ |
| ↩︎ 戻す / ↪︎ 進む | 直前の編集を取り消す（⌘Z）／戻しすぎたら1つ先へ進める（⌘⇧Z） |
| 📂 開く | 保存済みのスライドHTMLを選んで読み込み、その場で編集（slide-template.html を汎用エディタとして使える） |
| 📐 フォーマット | デッキの書式（なし／AWS提案用など）を切り替える |
| 🅰️ 書き出しFont | PPTXに書き出すフォントを切り替える（既定はMeiryo UI） |
| 🅣 文字 | クリックした場所に文字ボックスを置く |
| 🔷 図形 | 四角・角丸四角・丸・三角・線・矢印・帯矢印・吹き出しを置く |
| 🎯 選択中 | 文字色・背景色 / フォントサイズ・太字 / 箇条書き(・①②③・ぶら下げ字下げ) / 整列 |
| 🎨 カラーパレット | バッジ/タイトル/サブ/本文/カード/赤 を全スライド一括置換 |
| 📄 ページ操作 | ページ枠クリックで選択 → 複製 / 追加 / 並べ替え / 削除 / 背景色 |
| 🖼 画像 / ▦ 表 | クリック配置・ドロップ・⌘V貼り付け |
| ⧉ 複製 | 選択中の図形をその場に複製する（⌘D） |
| 🧩 AI図解相談 | 対象ページから「案だけ」「書き換え依頼」のプロンプトを生成してコピー |
| ✍️ ラフ | 叩き台の間は手書きフォント＋「ラフ」印で表示（見た目だけ・データ不変）。確定したらOFF |
| 📺 プレゼン再生 | 別ウィンドウ投影 / ページ送り / レーザー / ペン / 🗒メモ（現在ページへ追加・即入力・選択枠の−/＋で文字サイズ変更・投影同期）/ 📝ノート（発表者ノートを手元にだけ出す） |
| 📋 貼付（同じ位置） | 「📋 コピー」した図形を、いま見ているページの同じ座標に貼る（⌘V） |
| 📤 Kiroへ渡す | 編集内容を「Kiro貼付用パッチ」で出力 → Kiroに貼ると本体ファイルに反映（旧「📋 変更をコピー」） |
| 📍 場所をKiroへ | 選択オブジェクトの位置ID＋outerHTMLをコピー（変換指示用。旧「📍 参照」） |
| 💾 保存 | 編集UIを除いたクリーンHTMLを保存（serve.py 使用時はワークスペースに直接書き戻し・data-\*/style 正規化＋不一致件数のログ出力あり） |

図形そのものへの操作（⧉複製 ⌘D／📋コピー ⌘C／🗑削除）は、選択すると出る **🎯選択中パネルの先頭**にもまとまっている。
「Kiroへ渡す」「場所をKiroへ」はKiroに文章を渡すためのボタンで、図形のコピーではない。

「🧩 AI図解相談」は、ページ選択、選択中オブジェクトのページ、画面中央の順で対象を決める。ページ内容を外部へ自動送信せず、サニタイズしたHTMLを含むプロンプトだけをクリップボードへコピーする。Kiroへ貼り付けると、図解案の検討または対象ページの書き換えを依頼できる。

## 2通りの保存・反映

- **💾保存**：DOM全体をクリーンHTMLで書き出す。**迷ったらこちらでいい**
- **📤 Kiroへ渡す → Kiroに貼る**（Kiro併用時のみ）：位置・色・サイズ等の微調整差分をKiroが本体HTMLに反映。AIとの往復で編集履歴を残したい時に使う

localStorageには保存しない＝**HTML本体が唯一の正本**（Kiroの編集と衝突しない）。
💾保存はページ番号を一旦外して書き出す → 再オープン時に自動採番が振り直す（複製・追加ページも正しい連番に）。

## 既存デッキを開いて編集する（📂 開く）

`slide-template.html` を開く → 右上「📂 開く」→ 保存済みのスライドHTMLを選ぶ → その中の `.slide` を読み込んで編集できる。`slide-template.html` が「どのデッキでも開ける汎用エディタ」になる。
- 読み込むのは `.slide` 要素だけ（標準CSSはテンプレート側のものを使う）。**独自の `<style>` を持つ凝ったデッキは見た目が変わることがある** → そのデッキは自分のHTMLを直接開いて編集する方が確実。
- `file://` で開いても動く（fetchを使っていないため）。

## ⏱ 発表時間の見積もり

```
python3 SlideKit/deck_timing.py 対象.html --limit 20     # 持ち時間20分と比べる
```

発表者ノート（`data-notes`）があればその字数、無いページは本文の6割を **300字/分** で割る（1枚の下限8秒・図だけの頁は20秒）。
持ち時間を超えていれば、長いページから「何枚削れば収まるか」を出す。ノートが入っているほど確度が上がる（高/中/低を表示）。
発表者ビューのヘッダにも「目安 mm:ss / 全体 mm:ss（この頁 ○秒）」が出て、経過が目安を1割超えると赤、半分以下なら緑になる。
`slidecheck.py` でも `deck-timing` として自動で出る。kits-mcp からは `slidekit_timing` / `slidekit_lint`。

## 📺 プレゼン再生（別ウィンドウ・Zoom画面共有向け）

**別ウィンドウでフルスクリーンのスライドショー**を開ける。Zoom や Meet で「そのプレゼンウィンドウだけ」を画面共有すれば、ブラウザのアドレスバーや SlideKit ツールバー・他のアプリが相手に写り込まない。

### 読み込み

何も足さなくていい。`slide-edit.js` が `slide-present.js` を自動で読み込む。
雛形のように `slide-present.js` の行も書いてあるデッキはそのままでよい（二重には読まれない・無害）。

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
- 📝 ノート：発表者ノート（編集パネル「🗒 発表者ノート」で書いた `data-notes`）を手元のリモコンの上に出す。投影には出ない。押すと隠れる。PPTXではノート欄に入る
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

普段は `python3 SlideKit/slidecheck.py MyDeck/slides.html --pptx`（検査と変換を一度に通す）。
変換だけしたい時はキット同梱の `html_to_pptx.py` を直接使う（依存は上の「動作要件」参照）。
どちらも**ワークスペースルートで実行**する。

```
python3 SlideKit/html_to_pptx.py MyDeck/slides.html              # → 同名 .pptx を出力
python3 SlideKit/html_to_pptx.py MyDeck/slides.html 出力.pptx
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

## 📥 PPTX から取り込む（逆変換）

他人の PPTX を SlideKit 形式の HTML（雛形の作法）に取り込んで、ブラウザで編集・再生できる形にする。

```
python3 SlideKit/pptx_to_html.py 入力.pptx 出力.html
python3 SlideKit/pptx_to_html.py 入力.pptx                 # → 入力.html
python3 SlideKit/pptx_to_html.py 入力.pptx 出力.html --slides=1,5-8
```

- スライドサイズ・背景色・文字枠（位置・大きさ・文字・サイズ・太字・色・箇条書き）・表（行列・文字・セル色）・基本図形（矩形/楕円/三角/角丸/線/矢印の形と色）を変換
- 画像は出力 HTML の隣に `images/` を作って書き出し、`<img src="images/...">` で参照
- 発表者ノートは `.slide` の `data-notes` に入る（`html_to_pptx.py` でそのまま PPTX ノートへ戻せる）
- グループは展開して絶対座標化
- SmartArt・グラフなど画像化できないものは枠だけ置き、ページ下部の目立たない注記に「変換できなかった要素」として件数を出す
- 逆変換の中身（色解決・座標・図形逆マップ・段落組み立て）は `pptx_to_slidekit.py` を共有（二重管理しない）
- 旧 `pptx_to_slidekit.py` も入口として残っているが、いまは `pptx_to_html.py` を呼ぶだけの後方互換の薄い包み。両方とも同じ HTML を出す（新規の取り込みは `pptx_to_html.py` を使う）

### 往復検査

```
python3 SlideKit/pptx_to_html_check.py                       # 雛形で検査
python3 SlideKit/pptx_to_html_check.py MyDeck/slides.html    # 任意のデッキで
```

元HTML → `html_to_pptx.py` → PPTX → `pptx_to_html.py` → 往復HTML と通して、①`run_check.py` が問題なし ②枚数一致 ③文字枠の文字一致 ④座標の位置が ±2px 以内で一致、を確かめる。

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
python3 SlideKit/html_to_pptx_a4.py MyDeck/slides.html                    # 既定 1up（ワークスペースルートで実行）
python3 SlideKit/html_to_pptx_a4.py MyDeck/slides.html out.pptx --layout=2up
```

A4 縦 (210×297mm) の PPTX が出力される。既存の `html_to_pptx.py` の描画ロジックを再利用しつつ、座標変換だけ A4 用にスケール。

## AI にスライドを生成させる時（Kiro 等）

型は全部で34（文字系18＋図解16）。見本帳2本と選び方1本、規則の steering を用意している。

- **`pattern-catalog.html`**：文字系の型 P01〜P18（表紙・アジェンダ・3カラムカード・比較表・KPI・画像・階層箇条書き・大項目つき表など）の見本帳。Kiro に「この中から選んで内容を差し替えて」と指示すれば、毎回同じ座標系・同じ配色でスライドが生成される
- **`diagram-catalog.html`**：図解の型 D01〜D16（判定フロー・層スタック・循環・4象限・ロードマップ・ガント・境界図・評価ポイント対応表・多層防御・複数レーンのタイムラインなど。D11は図解プレースホルダー）。全部PPTXネイティブ図形＝座標計算済み
- **`pattern-select.md`**：34型を6分類→型の2段で絞る手順
- **MUST規則とカラートークン**：正本は `.kiro/steering/slide-contract-detail.md`（入口は `slide-contract.md`）。配布版（`make_dist.sh`）では `slide-contract.md`・`slide-contract-detail.md`・`slide-html-to-pptx.md` を `.kiro/steering/` に同梱する。ワークスペース直下に `.kiro/` ごと置けば Kiro が自動で読む
- **`slidekit-steering.md`**：生成規約の詳細（幾何定数・余白・画像・SVG図・プレースホルダー）

AI を使わない場合も、`pattern-catalog.html` はデザイン参照＋座標コピー元として有用。

## 由来

スライド編集で繰り返し使う操作を抽出して汎用化したもの。
以降の新規スライドはこのキットを標準として使う。
