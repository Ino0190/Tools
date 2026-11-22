# SlideKit 仕様書

最終更新: 2026-09-27（2章ファイル一覧・AWSプラグインの正本・プレゼン再生の自動読込を実装に合わせた）

## 1. 概要

SlideKit は、Kiro が生成した HTML スライドを **ブラウザ上で直接編集**でき、確定後に **PPTX に変換**できる単一 JS + Python 変換ツールのセット。KiroとPPTXの往復コストを下げ、非エンジニアでもスライド微調整ができることを目指す。

### 特徴

- **単一ファイル導入**: HTML の `</body>` 直前に 1 行 `<script src=".../SlideKit/slide-edit.js"></script>` を入れるだけで有効化
- **正本は HTML 本体**: localStorage は使わず、HTML ファイル自体を編集/上書き
- **絶対座標方式**: 全要素に `data-x/y/w/h` を持たせる (1280×720px 固定キャンバス)
- **PPTX 変換再現性**: HTML の見た目とほぼ同じ結果を PPTX で出す
- **Kiro併用**: 「📤Kiroへ渡す」でブラウザ側の編集を Kiro に貼付して再生成できる

## 2. ファイル構成

```
SlideKit/
├── slidekit-defs.js       ★共有定義 (JSON in JS)。色マップ/図形/属性スキーマ/定数の唯一の正本。JS/Python 両方が読む
├── slidekit-format.js     ★フォーマット描画エンジン。AWSオーバーレイ/パレット置換/暗色判定を一本化 (edit/present 共用)
├── slide-edit.js          ブラウザ側の編集機能 (メイン)。起動時に defs/format を自 src 基準で動的ロード
├── slide-present.js       別ウィンドウでプレゼン再生 (Zoom画面共有向け)。slide-edit.js が自動で読み込む (デッキ側の行は任意・二重読込は無害)。AWS描画は format に委譲
├── slide-a4export.js      A4縦PDF出力 (印刷CSS方式・独立)。キャンバス定数は defs 参照
├── slide-template.html    新規スライド作成の雛形
├── pattern-catalog.html   AI向けパターンカタログ (文字系 P01〜P18 の見本帳)
├── diagram-catalog.html   AI向け図解パターンカタログ (D01〜D16・PPTXネイティブ図形のみ)
├── pattern-select.md      型の選び方 (34型を6分類で絞る・図解ゲート)
├── structure-template.md  構成ファイル (<deck>.structure.md) の雛形。HTMLの前に作る
├── structure-preview.py   構成ファイルを確認用HTMLにする
├── defect-taxonomy.md     作った後の欠陥分類表 (検査出力の [R1] [B2] 等と対応)
├── slidekit-steering.md   AI向けステアリング文書 (Kiro等の生成ルール)
├── slidecheck.py          検査の入口 (ガード→診断→スクショ→PPTX を1コマンドで)
├── slide-guard.py         変換前の静的ガード (フォント下限・許可外class・カタログ外色・構成ファイル突合)
├── ui-check.py            編集UIの実ブラウザ検査 (プレゼン再生ボタン・右パネルのはみ出し)。BezierKit/cdp-check.py を使う
├── html_to_pptx.py        HTML→PPTX変換スクリプト。リマップ表/図形clamp/テンプレ検索/定数を defs から読む
├── pptx_semantic.py       PPTXの意味付け: タイトル枠・テーマ色・代替テキスト・直せる文字。html_to_pptx が読む (必須・既定ON)
├── slidekit-chart.js      data-chart のグラフをブラウザで描く (slide-edit.js が data-chart のあるデッキだけ自動で読む)
├── measure_layout.py      (試作) ブラウザの描画結果を測る。data属性・変換側との食い違い・行数のずれを出す
├── html_to_pptx_a4.py     A4縦PPTX変換 (1up/2up・独立。html_to_pptx を import して自動追従)
├── pptx_to_slidekit.py    PPTX→SlideKit HTML 逆変換。図形逆マッピングは defs.shapes から導出
├── pptx_to_a4.py          既存PPTXをA4に組み直す補助 (独立)
├── serve.py               保存用ローカルHTTPサーバー (PUT対応・アトミック保存)
├── check-layout.js        レイアウト崩れ診断 (任意)。属性/定数は defs 参照
├── run_check.py           レイアウト診断 CLI (Chrome headless)
├── pptx_to_format.py      もらったPPTXから書式 (色・フォント・余白) だけ抜き出して .format.json にする。内容は捨てる
├── pptx-compare.py        ブラウザ表示とPPTX描画 (LibreOffice) を左右に並べた比較画像を作る (目視用)
├── html_to_standalone.py  スライドHTMLを1ファイルで送れる形にする (画像・動画をbase64埋め込み・編集UIを外す)
├── flow_to_movie.py       CadKitのコマ送りSVGを mp4 にする＋プレビュー (poster) 選択画面を出す
├── dk_chart_to_slide.py   DashboardKitのグラフをスライド1枚にする
├── slide-livenotes.js     Live Notes (補助)。録音とスライド切替を記録し、発言を表示中のスライドに紐づける
├── livenotes_transcribe.py Live Notes の録音を手元の whisper で文字起こしし、スライドごとの議事メモにする (音声は外に出さない)
├── livenotes_check.py     Live Notes の回帰テスト (ロジック＋ブラウザ)
├── html-edit.js           一般HTML (スライド以外) 用の編集スニペット。1行注入で右パネルからサイズ等を直せる
├── sk-icons.js            UIの絵文字をSVGアイコンに置き換える (生成物・直接編集しない)
├── gen-sk-icons.py        sk-icons.js を BezierKit/icons-data.js から生成する
├── make_dist.sh           配布スナップショットを作る (steering 3本を .kiro/steering/ に同梱・個人名を除去)
├── TESTS.md               手で確かめる動作テストのチェックリスト

├── SPEC.md                本ドキュメント
└── README.md              導入ガイド
```

> **v2 の設計方針**: 横断的な「値」(色マップ・図形パラメータ・属性スキーマ・定数) は
> `slidekit-defs.js` に集約し、フォーマット描画は `slidekit-format.js` に一本化した。
> デッキ側の導入は従来どおり `slide-edit.js` の 1 行のみ (defs/format は自動ロード)。
> defs/format が読めない環境でも、各ファイルは v1 と同値の組み込みフォールバックで動作する。

## 3. 起動と基本操作

### 起動

1. ワークスペースルートで `python3 -m http.server` (もしくは `python3 SlideKit/serve.py`)
2. 対象HTMLをブラウザで開く
3. 右上のツールバーが表示される。「✏️編集」を押して編集モードに入る

### 保存

- **💾保存**: 3モード自動判定
  - `serve.py` 経由なら PUT で直接HTMLに書き戻し
  - File System Access API 対応ブラウザなら OS のファイル選択で上書き
  - どちらも不可なら DL フォールバック (ダウンロードして手動で上書き)
- **📤Kiroへ渡す**: 前回状態からの差分をパッチ形式でクリップボードへ (Kiroに貼付して反映。旧「📋変更をコピー」)

## 4. HTML 規約

### 4.1 スライドサイズ

- **1280 × 720 px 固定** (PPTX 16:9 の 13.333 × 7.5 inch と 1:1 対応)
- 全要素は絶対座標 (data-x, data-y) で配置

### 4.2 基本構造

```html
<!DOCTYPE html>
<head>
  <meta charset="utf-8">
  <style>
    body{font-family:'Yu Gothic','Meiryo UI','Noto Sans JP',sans-serif}
    .slide{width:1280px;height:720px;position:relative;overflow:hidden;margin:12px auto}
    .tb{position:absolute;overflow:hidden;line-height:1.5}
    .rect{position:absolute;display:flex;flex-direction:column;justify-content:center}
  </style>
</head>
<body>
  <!-- SLIDE: 表紙 -->
  <div class="slide" data-bg-gradient="135,#183251,#21537f">
    <div class="tb" data-x="140" data-y="240" data-w="1000" data-h="120"
         data-font-size="42" data-bold="1" data-color="#fafafa"
         style="left:140px;top:240px;width:1000px;height:120px;font-size:42px;font-weight:700;color:#fafafa">
      タイトル
    </div>
  </div>
  <!-- /SLIDE -->
  <script src="../SlideKit/slide-edit.js"></script>
</body>
</html>
```

### 4.3 要素タイプ

| クラス | 意味 | PPTX変換先 |
|---|---|---|
| `.tb` | テキストボックス | `<a:sp>` (Text Frame) |
| `.li` | 箇条書きの項目 (`.tb[data-bullet^="native-"]` の子) | `<a:p>` (1段落) |
| `.rect` | 矩形カード / バッジ / 図形の台座 | `<a:sp>` (Shape) |
| `.flow` | 角丸矩形 (フロー図ノード) | `<a:sp>` (ROUNDED_RECTANGLE) |
| `<table>` | 表 | PPTX table |
| `<img>` (親div内) | 画像 | `<p:pic>` |
| `<svg>` (親div内) | SVG図 | PNG化して `<p:pic>` |
| `<video>` (親div内) | 動く図 (mp4) | 動画を埋め込み (`add_movie`)。プレビューは `poster` のPNG |

#### 動く図（アニメーション）の出し方

🚫 **SVGのSMILアニメはPPTXで動かない。** `<svg>` は `rasterize_svg` で1コマのPNGになる。
ブラウザでは動いていたものが、PPTXでは静止画になる（2026-08-21に空港BHSで確認）。
動かしたい図は **mp4を埋める**。

```
CadKit/cdp-run.py <model> --export-flow <dir> --flow-frames 16 --flow-step 1.1 \
    --line-angle 18,30 --line-outer 2.0 --line-inner 0.6 --line-size 1800,760
SlideKit/flow_to_movie.py <dir> -o <deck>/xxx.mp4 --fps 8 --scale 2
```

スライドには枠のdivをそのまま使い、中身を `<video>` にする（座標はPPTXでも一致する）。

```html
<div data-x="0" data-y="79" data-w="1280" data-h="601" style="...">
  <video src="xxx.mp4" poster="xxx_frames/frame08.png" autoplay loop muted playsinline
         style="width:100%;height:100%;object-fit:contain;display:block"></video>
</div>
```

- `poster` = **再生前にPowerPointが出す1枚**。`flow_to_movie.py` が出す
  `xxx_frames/index.html` を開き、動画を見ながら「今の場面をプレビューに」で選ぶ。
  選び直しは `poster=` の書き換えだけで済む（動画の作り直しは不要）
- `autoplay` `loop` があると変換側が `p:timing` を書き換えてPowerPointでも自動再生・ループを狙う。
  ⚠️ 実機のPowerPointで自動再生が効くかは環境差がある。効かなくてもクリックで再生できる
- mp4以外（webm等）は埋め込まずMISSING扱い。H.264/yuv420pのmp4にする

#### 3Dモデル（回せる図）は自動変換に乗らない

PowerPointは3Dモデル（**GLB推奨**・OBJ/3MF/STLも可。FBXはOfficeで無効化済み）を挿入でき、
スライド上で回転・傾きができる。GLBにアニメーションが入っていれば荷の流れも再生される。

🚫 **python-pptxに3Dモデルを埋めるAPIが無いため、`html_to_pptx.py` では出せない。**
PowerPointで「挿入 > 3Dモデル > このデバイス」で手作業で入れる。
デッキを再生成すると消えるので、**配布物はmp4を本線にする**。

アニメ入りGLBの作り方（BHSの例・`CadKit/bhs-export.py`）:

```
python3 CadKit/bhs-export.py bhstwin ../project/bhs-dashboard/scene --frames 24 --step 0.5
```

同じGLBは `project/bhs-dashboard/bhs-viewer.html` でも自動再生される（「⏸ 荷を止める」で停止）。
打合せの場で回して見せるなら、PowerPointに入れるよりビューアを開く方が速い。

### 4.4 スライド管理

- `<!-- SLIDE: 名前 -->` ... `<!-- /SLIDE -->` でスライドを囲むと並び替え/削除が容易
- ページ番号は自動採番 (`renumberPages`) されるので手書き不要。**`<html data-pageno="off">` でPPTX変換時の自動ページ番号を抑止できる**（テンプレ側フッタが番号を持つ場合など・2026-08-31追加）

## 5. data 属性一覧

### 5.1 共通 (全要素)

| 属性 | 型 | 説明 |
|---|---|---|
| `data-x` | int | X座標 px (スライド左上原点) |
| `data-y` | int | Y座標 px |
| `data-w` | int | 幅 px |
| `data-h` | int | 高さ px |
| `data-rotate` | int (0〜359) | 回転角・度・時計回り・中心基準。style `transform:rotate(Ndeg)` と同値必須。PPTX shape.rotation に変換 (tb/rect/img。table不可) |
| `data-flip` | `h`/`v`/`hv` | 左右/上下反転 (rect図形・img)。style `transform` の `scaleX(-1)`/`scaleY(-1)` と同値必須 (rotateの後に書く)。PPTX xfrm flipH/flipV に変換。直下の.tbは逆反転して文字を読める向きに保つ |
| `data-link-sid` | sid文字列 | ページジャンプリンク。クリックで `.slide[data-sid]` の一致ページへ (閲覧モード=スクロール / プレゼン=切替 / PPTX=click_action.target_slide)。table不可 |
| `data-color` | hex | 文字色 (.tb) / 表全体の文字色 (table) |
| `data-fill` | hex/`none` | 塗り色 (.rect) / 塗りなし |
| `data-shadow` | `soft` | 薄い影を付ける (rect のみ) |
| `data-radius` | int | 角丸 px (.rect / .flow)。**`0`=角なし（PPTXはRECTANGLE）。.flowで未指定なら既定8px を明示適用**（PowerPoint既定の大きい丸みは出さない・2026-08-31ルール化） |
| `data-border` | `w,#hex` | 全周ボーダー (.rect)。矢印/帯矢印/三角では図形輪郭の線（表示=SVG stroke背景・PPTX=shape.line）。CSS borderは書かない |
| `data-border-top` / `-right` / `-bottom` / `-left` | `w,#hex` | 片側ボーダー (.rect) |
| `data-border-style` | `wavy` 等 | PPTX変換時に線種を wavy 相当にする |
| `data-linked-parent` | skid | 親rectと連動する子.tb |

### 5.2 .tb 固有

| 属性 | 説明 |
|---|---|
| `data-font-size` | フォントサイズ px |
| `data-bold` | `1` で太字 |
| `data-align` | `left` / `center` / `right` |
| `data-valign` | `top` / `middle` / `bottom` |
| `data-bullet` | `disc` (・) / `decimal` (①②③) / `native-disc` / `native-decimal` |
| `data-role` | `badge` / `title` / `subtitle` / `pageno` (自動分類) |

### 5.2.1 箇条書きの2方式

| 方式 | data-bullet | 構造 | マーカー | 向き |
|---|---|---|---|---|
| 文字マーカー | `disc` / `decimal` | 1つの `.tb` = 1項目 | 本文の先頭文字 | 項目ごとに位置を変えたいカード列 |
| PowerPointネイティブ | `native-disc` / `native-decimal` | 1つの `.tb` に `.li` を並べる | ブラウザ=CSS `::before` / PPTX=`buChar`・`buAutoNum` | 階層のある箇条書き・PowerPointで続けて編集する資料 |

ネイティブ方式の構造:

```html
<div class="tb" data-x="64" data-y="180" data-w="1120" data-h="200"
     data-font-size="20" data-color="#121212" data-bullet="native-disc"
     style="left:64px;top:180px;width:1120px;height:200px;font-size:20px;color:#121212">
  <div class="li" data-lvl="0">親項目</div>
  <div class="li" data-lvl="1">子項目</div>
  <div class="li" data-lvl="0">親項目2</div>
</div>
```

- `.li` 1個 = PPTX の1段落。`data-lvl` (0〜4) が `<a:pPr lvl>` になる
- マーカーは本文に入れない（入れると PPTX で二重になる）
- 表示CSSは `slide-edit.js` が `<style id="skListCss">` を head に注入する（保存HTMLにも残る）
- レベル定義（字下げ幅・マーカー・採番の型）は `slidekit-defs.js` の `list` が正本。
  ブラウザ用CSSと PPTX の `buChar`/`buAutoNum` を同じ定義から作る
- PPTX側は `<a:lstStyle>` に lvl1〜lvl5 を書くので、PowerPoint で Tab / Shift+Tab しても同じ字下げになる
- 採番 (`native-decimal`) は同じテキストフレーム内の連続段落で数える。項目を別の `.tb` に分けると各々①から始まる
- 逆変換 (`pptx_to_slidekit.py`) は `buChar` / `buAutoNum` を文字マーカー方式（`data-bullet="disc"` + 先頭に記号）へ落とす。ネイティブ構造には戻らない（階層は marL の字下げとして残る）

### 5.3 .rect 固有

| 属性 | 説明 |
|---|---|
| `data-shape` | `circle` / `triangle` / `line` / `arrow` / `chevron` / `callout` |
| `data-cv` | chevron の先端幅割合 (0.02〜0.6) |
| `data-at` | arrow の軸太さ割合 (0.05〜0.95) |
| `data-ah` | arrow の矢羽長割合 (0.05〜0.9) |
| `data-bx` | callout のしっぽ先端x位置 (0.08〜0.92)。本体=上80%・しっぽ=下20%。PPTXは RECTANGULAR_CALLOUT の adj に変換 |
| `data-fill` 8桁hex | `#RRGGBBAA` で半透明塗り (UIの「塗りの不透明度」)。PPTX は alpha 変換済み |
| `data-funnel-img` | ファネル図の目印 (画像内のラベルを一緒に動かす) |

### 5.4 スライド (.slide) 固有

| 属性 | 説明 |
|---|---|
| `data-bg` | 単色背景 hex |
| `data-bg-gradient` | `角度,#hex1,#hex2` (例: `135,#183251,#21537f`) |
| `data-sid` | ページ固定ID (英数)。`data-link-sid` の行き先。編集UIがリンク設定時に自動採番。ページ複製時は複製側から自動除去 |
| `data-notes` | 発表者ノート（改行可・旧来の `\n` 表記も可）。編集パネル「🗒 発表者ノート」で書く（undo可）。PPTXではノート欄、📺プレゼン再生中は手元のリモコン上に出る（投影には出ない・📝 ノートで隠せる）。2026-10-14 |

### 5.5 html (最上位) 固有

| 属性 | 説明 |
|---|---|
| `data-template` | `aws` / `blue` / なし。フォーマット指定 |

### 5.6 画像 (`<img>` 親div) 固有

| 属性 | 説明 |
|---|---|
| `data-border` | `w,#hex` (画像枠) |
| `data-clip` | `circle` (円クリップ) |
| `data-crop-l/r/t/b` | 0.0〜0.9 (手動トリミング比率。切り出し領域が枠いっぱいに表示＝PPTX srcRect と同義) |
| style `object-fit` | `cover`/`contain` (PPTX変換で crop_* に変換) |
| style `object-position` | `left/center/right top/center/bottom` |

### 5.7 グラフ (`data-chart`・2026-10-14)

数値のグラフはスライド直下の div に JSON で書く。ブラウザは `slidekit-chart.js`（slide-edit.js が自動で読む）が SVG で描き、
PPTX は `html_to_pptx.py` がネイティブグラフにする（数値は埋め込みブック＝PowerPointの「データを編集」で直せる）。

```html
<div data-x="64" data-y="170" data-w="560" data-h="440" data-font-size="16"
     data-chart='{"type":"column","title":"問い合わせ件数","unit":"件","categories":["Q1","Q2","Q3","Q4"],
                  "series":[{"name":"2025年","values":[120,150,135,180]},{"name":"2026年","values":[140,170,190,210]}]}'
     style="position:absolute;left:64px;top:170px;width:560px;height:440px"></div>
```

| キー | 値 |
|---|---|
| `type` | `column`（縦棒）/ `bar`（横棒）/ `stacked`（積み上げ縦棒）/ `line`（折れ線）/ `pie`（円・系列は1つ目だけ）/ `table`（表＝行が項目・列が系列。PPTXでは PowerPoint の表・文字は8pt以上） |
| `categoryLabel` | 表の1列目の見出し（既定「項目」） |
| `type:"map"` | 地図（2026-10-14）。`{"type":"map","map":"japan-pref","mark":"circle｜bar｜fill","unit":"万人","values":{"東京都":1404,…}}`。系列が2つ以上なら `"series":[{"name":"2024年","values":{…}},…]`（棒は並べる・円と塗り分けは1つ目）。県は「東京都」「東京」「13」「JP-13」のどれでも。**円**は面積が値に比例（凡例は切りのいい値の円2つ）、**棒**は県の位置に立てる、**塗り分け**は値の並びの20・40・60・80%で5段（スライドの色の濃淡・データの無い県は白）。名前と数値は、ほかの名前・円・棒・凡例に重ならないものだけ（大きい方から5県は円に重なってもよい）。見せ方の切り替えは「円／棒／塗り分け／表」（表は1行＝1つの地域）。地図データは `maps/japan-pref.js`（`map_build.py` が Natural Earth（public domain）から作る。沖縄県は左上の枠に移す・小笠原・南鳥島・大東・尖閣は地図を小さくしないため外す）。**PPTX はサンキーと同じく、県・円・棒を図形、名前と数値を文字枠にする**（県ごとに色を直せる） |
| `points`（地図） | 拠点と範囲＝商圏（2026-10-15）。`{"type":"map","pointLabel":"店","pointUnit":"千人","points":[{"name":"浦和店","lat":35.858,"lon":139.657,"value":12}],"areas":"circle｜voronoi｜none","radius_km":[3,5],"bbox":[西経度,南緯度,東経度,北緯度]}`。拠点は緯度経度で置く（`value` があれば点の面積が値に比例）。**circle**＝半径 `radius_km` の円（既定 3km・5km、外側は破線）、**voronoi**＝いちばん近い拠点で陸地を分ける（距離はkm・海は塗らない・`radius_km` を書くといちばん大きい半径の内側に限る）、**none**＝点だけ。`bbox` が無ければ拠点と円が収まる範囲に寄せる（最小10km四方）。寄せた地図は細かい県境 `maps/japan-pref-detail.js`、県名は見えている部分の真ん中、凡例の下に縮尺。画面の外・海に出る部分は図形を切って出す（PPTXでも枠からはみ出さない）。県の `values` と一緒に書くと、県の塗り分けの上に拠点を置く。見せ方の切り替えは「半径の円／最寄りの範囲／点／表」（表は1行＝1つの拠点・列＝値・緯度・経度）。県境は Natural Earth 1:10m（約1km単位）なので市区町村の境は無い。店の位置は自分で用意する（他社サイトから集めない） |
| `type:"sankey"` | 流れ（2026-10-14）。`{"type":"sankey","unit":"ケース","nodes":[{"id","label"}],"links":[{"from","to","value"}]}`（DashboardKit と同じ形）。列＝起点からの段数、列の中は量の多い順、帯の太さは量・色は出どころの箱。名前と量は箱の右。見せ方の切り替えは「サンキー／表」（表は1行＝1本の帯）。**PPTX は PowerPoint に同じグラフが無いので、ブラウザで描いた帯・箱を図形のグループ、名前と量を文字枠にする**（数値をあとで直すときはSlideKitで直してPPTXを作り直す）。表にしたものは PowerPoint の表 |
| `fitY` | `true` で値の軸をデータの範囲に合わせる（折れ線だけ・`max` があれば使わない）。体重47〜49kgのような小さな変化が平らにならない（DashboardKit の fitY と同じ考え方） |
| `max` | 値の軸の上限（データの最大より小さいときは使わない）。率は `100` |
| `target` | `{"value":100,"label":"目標"}` 目標線。赤の破線と「目標 100kg」。範囲に入れて軸を作る。PPTXは同じ値の系列（ブックで直せる・凡例には出さない）、棒グラフでは棒＋線の組み合わせ。横棒には出さない |
| `series[].dash` | `true` で破線＋白抜きの点（予測・理論値）。折れ線だけ。`null` の値は線を切る（0に落とさない） |
| `timeAxis` | `true` で点を実際の日付の間隔に置く（折れ線・項目がすべて `YYYY-MM-DD`）。1日を1枠・点は枠の中央。項目名は重ならないものだけ。PPTXは日付の軸（m/d） |
| `bands` | `[{"from","to","label","color","opacity"}]` 期間・その日の帯（線・棒の後ろ）。from/to は項目の値（日付の項目なら日付で比べ、間の日も含む）。color は `danger/accent/warn/ok/sub` か #hex（既定 sub・濃さ0.12）。名前は帯の左上（48px以上）。PPTXは折れ線だけ＝線の後ろの棒（名前は帯の始めに）。縦棒の帯はブラウザだけ（WARN） |
| `area` | `true` で線の下を上から下へ薄く塗る（系列で `area:false`・破線の系列は塗らない）。PPTXは線の後ろの面グラフ（グラデーション） |
| `smooth` | `true` でなめらかな線（ブラウザは単調3次補間＝山や谷を越えて膨らまない。PPTXは PowerPoint の平滑線で、少し違う） |
| `weekendBand` | `true` で土日を薄く塗る（折れ線・項目がすべて日付）。timeAxis なら範囲の中の土日すべて。PPTXは線の後ろの「土日」の棒（すき間なし・凡例に出さない）。timeAxis と両方のときは間の日付も項目に入れ、線はつなぐ |
| `categories` / `series` | 項目名の配列 / `[{"name","values"}]` |
| `unit` | 数値ラベルと目盛りに付ける単位（任意） |
| `labels` / `legend` | `false` で数値ラベル / 凡例を消す（凡例は系列2つ以上か円のときだけ出る）。`labels` を書かなければ数値を**間引いて**出す＝数値1つずつの置き場所を見積もり、置いた数値と重ならないものだけ出す（置く順は系列ごとの最大・最小・最後→左から）。`"all"` で全部出す。折れ線が2本以上なら平均の低い系列の数値は線の下。ブラウザ（slidekit-chart.js labelPlan）とPPTX（html_to_pptx.chart_label_plan・出さない点は c:dLbl delete）で同じ点を選ぶ（tests/test_chart_wording.py） |
| `colors` | 系列色（既定＝トークン `#21537f #9fc0dd #718096 #162a42 #d4dde7 #c62828`） |
| `title` | 図の代替テキスト（グラフの上に見出しは出さない。見出しは `.tb` で書く） |

- 目盛りの刻みはブラウザとPPTXで同じ計算（4刻み前後のきりのいい値）。文字の大きさは `data-font-size`（既定15px）
- 中に描かれた SVG は保存HTMLに残る（JS 無しでも見える）。変換時は SVG を画像にせず、JSON から作り直す
- 回帰の見本 = `tests/fixtures/chart_native.html`（5種類）
- **見せ方の切り替え**（2026-10-14）: グラフにマウスを乗せると、上に「縦棒・横棒・積み上げ・折れ線・円・表」のボタンが出る
  （`.seui`＝保存・同期・コピーでは外れる）。見ているとき・📺プレゼン中は**その場の見せ方だけ**変わり、ファイルとPPTXは変わらない
  （「↺ 元の形」で戻る）。✏️編集中に押すと `type` を書き換える＝保存され、PPTXもその形（グラフか表）になる。⌘Zで戻る
- **貼り付けで入れる**（2026-10-14）: DashboardKit のどの画面でも、グラフをクリックして ⌘C
  （`excel-chart.html` でExcelから作ったグラフも、ダッシュボードのグラフも同じ。画面にボタンは出さない）→ 編集画面（✏️編集）で ⌘V（または「📋 貼付」）。
  点が多いグラフは数値ラベルを重ならない分だけ間引き（上の `labels`）、項目名も間引く。日付は 4/1 の形で出す（項目名はPPTXでは PowerPoint が間引く）。グラフの依頼の枠（`data-ask="chart"`）を
  選んでから貼ると、枠の位置と大きさで置き換わる（⌘Z 2回で枠に戻る）。選んでいなければ画面中央のページの本文域。
  貼れるのは data-chart の div か JSON だけ。HTMLは DOMParser で読むだけで、要素はこちらで作り直す
  （クリップボードの他の属性・スクリプトは持ち込まない。type・項目・系列・数値は型を確かめ、数でない値は空にする）

## 6. ツールバー・パネル

### 6.1 ツールバー (右上・縦列)

| ボタン | 機能 |
|---|---|
| ✏️編集 | 閲覧/編集モード切替。編集ONで下記パネル自動展開 |
| 📂開く | 別HTMLファイルを開く |
| 📐フォーマット | ドロップダウン: なし / 青系モノトーン (パレット一括置換) |
| ✍️ラフ | ラフモード。手書きフォント(Klee)＋各ページに「ラフ」印の表示上書き。`<html data-draft="on">`が保存に残り再オープンで復元。データ不変・PPTX変換時は警告 |
| 🅰️書き出しFont | 6種切替 (Meiryo UI / Yu Gothic / メイリオ / Noto Sans JP / ヒラギノ / 明朝) |
| 🅣文字 | テキストボックス配置モード |
| 🔷図形 | 図形メニュー (四角/角丸/丸/三角/線/矢印/帯矢印) |
| 🖼画像 | 画像挿入 (ファイル選択 or ⌘V or ドロップ) |
| ▦表 | 表挿入 |
| ⧉複製 | 選択要素を複製 |
| 📋貼付（同じ位置） | 「📋コピー」した図形を、いま見ているページの同じ座標に貼る (⌘V) |
| 📍場所をKiroへ | 選択要素の outerHTML を Kiro貼付形式で出力 (旧「📍参照」) |
| 🧩AI図解相談 | 対象ページから図解検討・書き換え用プロンプトを生成 |
| 📤Kiroへ渡す | 前回からの差分パッチをクリップボードへ (旧「📋変更をコピー」) |
| 💾保存 | 3モード自動判定 (PUT/FS Access API/DL) |

### 6.1.1 🧩 AI図解相談

- 対象ページは「明示的に選択したページ → 選択中オブジェクトがあるページ → 画面中央」の順で決定する
- 「案だけコピー」は、理解目標、情報構造、図表化の妥当性、最大3案、推奨案の提示をAIへ依頼する
- 「書き換え依頼をコピー」は、推奨案またはAIが選んだ最適案で対象スライドだけを書き換えるよう依頼する
- プロンプトにはファイル名、ページ番号、タイトル、本文、サニタイズ済みの対象スライドHTMLを含める
- HTMLから編集UI、選択outline、contenteditable、内部属性、ページ番号を除去する。元のDOMは変更しない
- 外部APIへ自動送信しない。生成したプロンプトをクリップボードへコピーするだけとする
- 相談操作は編集履歴、dirty状態、保存内容へ影響しない

### 6.2 🎨 共通カラーパレット

- デッキで使われている色を自動スキャン (data-color/data-fill/data-bg/style)
- 出現回数順に列挙
- 各行: 色見本 (=カラーピッカー) / hex入力 / ⌀透明 (bg系のみ) / N箇所
- **hex/ピッカー編集** → 全スライドの同色を即置換 (rgb() 表記も同時)
- **Shift+クリック** → 選択中の要素にその色を割り当て
- **⌀ボタン** → その色を使う要素の背景を透明化
- **ホバー** → 該当色の要素をスライド上でハイライト
- **🔄** で手動再スキャン

### 6.3 🎯 選択中パネル (Selected)

選択した要素の種類に応じて表示行が動的に変わる。

| 行 | 表示条件 | 内容 |
|---|---|---|
| この図形を | 1つ以上選択時 | ⧉複製 (⌘D) / 📋コピー (⌘C) / 🗑削除 (Delete)。貼付はツールバーの📋貼付 (⌘V) |
| 文字色 / 背景・塗り | 常時 | hex入力 + ピッカー + ⌀透明ボタン |
| サイズ/太字 | .tb 選択時 | +/− ボタン、hex数値入力、B (太字) |
| 文字ぞろえ | .tb/table 選択時 | 左 / 中央 / 右 (横並び) |
| 縦位置 | .tb/table 選択時 | 上 / 中 / 下 (縦並び) |
| 箇条書き | .tb 選択時 | ・(disc) / ①(decimal) / なし |
| 枠線 | rect/tb 選択時 | 位置(全周/上下左右) × 太さ × 色 × 線スタイル |
| カードスタイル | rect 選択時 (図形除く) | 塗り / 枠線 / 透明 + 🌫薄い影 |
| バッジ形状 | badgeロール選択時 | pill / 角丸 / 四角 / 帯矢印 |
| 表の色 | table 選択時 | ヘッダー背景/文字, 本文セル背景/文字, セル枠線 (⌀透明あり) |
| 線/矢印 | line/arrow shape選択時 | 太さ / 矢羽長 |
| 帯矢印の尖り | chevron shape選択時 | 緩く/尖らす + 全一括統一 |
| 角R | rect 選択時 (図形除く) | data-radius 数値入力 |
| サイズ W×H | 単一選択時 | 数値入力 |
| 整列 | 2つ以上選択時 | 横方向 / 縦方向 / サイズ統一 / 等間隔 |
| 共通化 | 1カード選択時 | 塗り/枠線/文字色/サイズを他ページに伝播 (無/同/全) |
| リンク解除 | 子.tb選択時 | 親rectとの連動を解除 |
| トリミング | 画像(または画像1枚の枠)選択時 | クロップモード（ドラッグ=位置/ホイール=拡縮） |
| 並び順 | 常時 | 最前面/前へ/後ろへ/最背面 |

### 6.4 📄 ページ操作パネル

- 現在ページ表示 (「N/M ページ 「タイトル」」)
- ⧉ 複製 / ＋ 追加 / ↑ 前へ / ↓ 後ろへ / 🗑 削除
- 背景色 (hex入力 + カラーピッカー)
- ページ枠の余白クリックで選択 (オレンジ枠+バッジ表示)

## 7. 操作

### 7.1 キーボードショートカット

| キー | 動作 |
|---|---|
| ⌘Z / ⌘Y (⌘Shift+Z) | Undo / Redo (60操作前まで) |
| 矢印キー | 1px移動 |
| Shift+矢印 | 10px移動 |
| Shift+ドラッグ | 水平/垂直ロック移動 |
| Option(⌥)+ドラッグ | 連動を外して単独移動 |
| Shift+クリック | 追加選択 |
| ⌘V | 画像ペースト (クリップボードから) |
| ドラッグ&ドロップ | スライド上に画像ファイルをドロップ |
| Delete | 挿入要素削除 |
| Escape | 選択解除 |
| ⌘S | 保存 (💾と同等) |
| ⌘Shift+R | ハードリロード (ブラウザキャッシュ回避) |

### 7.2 選択・移動・リサイズ

- **選択**: クリック / Shift+クリックで複数 / ドラッグで矩形選択
- **移動**: 選択要素をドラッグ / 矢印キー / 選択枠の十字アイコンをドラッグ
- **リサイズ**: 選択枠の8ハンドル (四隅=両軸/辺=片軸)。上・左から掴むと反対側の辺を固定して位置も追従
- **同倍率リサイズ**: 複数選択 → 角ハンドル (どの角でも可・掴んだ角の対角を固定)
- **アスペクト比固定リサイズ**: Shift+角ハンドル (ドラッグ開始時の縦横比を維持。画像が歪まない)
- **回転**: 選択枠上中央の↻ハンドルをドラッグ (0/90/180/270°近傍に吸着・Shiftで15°刻み)。
  ハンドル上・ドラッグ中はマウスカーソルも↻になる (SVGカーソル)。
  ダブルクリックで0°に戻す。`data-rotate`(度・時計回り・中心基準)に保存され、
  PPTX の shape.rotation にそのまま変換 (図形は内部テキストごと回転)。表(table)は回転不可
- **画像トリミング**: 画像をダブルクリック（または🎯パネルの✂️ボタン）で開始。枠＝表示エリアは固定のまま、
  枠内ドラッグで画像の表示位置を移動、マウスホイールで拡大縮小（×1〜×8・カーソル位置中心）。
  Esc/枠外クリックで終了、✂️「解除」で元に戻す。表示は `object-view-box`（Chrome系ブラウザ）、
  データは `data-crop-l/r/t/b` に保存され PPTX の crop_*（srcRect）へそのまま変換される

### 7.3 特殊選択機構

- **親子リンク**: 親.rect に skid 付与、子.tb に `data-linked-parent="skid"`。親を動かすと子も追従
- **ロール連動**: badge/title/subtitle/pageno を1つ動かすと全ページの同ロールが連動 (Option⌥ で解除)
- **ファネル図の同行者**: `data-funnel-img` の上に重なる.tbラベルを動かした時に一緒に動かす

## 8. PPTX 変換 (`html_to_pptx.py`)

### 8.1 使い方

```bash
python3 SlideKit/html_to_pptx.py 対象.html [出力.pptx]
python3 SlideKit/html_to_pptx.py 対象.html --measured               # 試作（2026-10-14）
python3 SlideKit/html_to_pptx.py 対象.html --no-semantic            # タイトル枠・テーマ色をやめる（既定はON）
python3 SlideKit/measure_layout.py 対象.html [--lines]              # 実測との食い違いだけ見る
```

- 常時: `img` の `alt`（無ければ `title`・ラッパーの `aria-label`/`data-alt`）、SVG図の `aria-label`/`<title>` を図の代替テキストに入れる。無い図は件数を出す
- 意味付け（**2026-10-14 既定ON**。利用者がPowerPoint実機で、見出しの位置・大きさが従来と同じ／アウトライン表示にタイトルが並ぶ／ネイティブグラフの「データの編集」で数値を変えると図が変わる、を確認。`--no-semantic` で外す・`--semantic` は旧指定として受ける）: 見出しの `.tb` をタイトルのプレースホルダーにする（本文=y20〜140で22px以上の最大字／暗色=28px以上の最大字。数字の強調は除く）。書式は明示して見た目を変えない。トークン10色をテーマの配色に登録し、同じ色を schemeClr で参照する（AWSテンプレ使用時は配色を触らない）。読み上げ順: スライド直下の文字の無い図形・線（代替テキストなし）に「装飾」の印（adec:decorative）を付け、読み上げで飛ばす。重なり順は変えない（並べ替えると見出しが背景の下に隠れるため）
- `--measured`（試作）: Chrome で開いて測り、位置・大きさと文字ごとの太字・大きさ・色を見えている値にする（段落の組み方は従来どおり）。型に乗らない自由配置の div（従来は消えていた）を箱と文字のまま置く。Chrome が無ければ従来の変換に戻る
- `measure_layout.py --lines`: PPTX を LibreOffice で描き、スライド直下の文字枠の行数をブラウザと比べる（PowerPoint の字詰めとは少し違う）

### 8.2 レイアウト再現

| HTML要素 | PPTX要素 |
|---|---|
| `.tb` | Text Frame + Latin/EastAsian両方のフォント指定 |
| `.rect` | Shape (fill/border/shadow/radius/shape対応) |
| `.rect[data-shape]` | 対応する MSO_SHAPE (OVAL/TRIANGLE/RIGHT_ARROW/PENTAGON) |
| `<table>` | PPTX table (colspan/rowspan/列幅/行高) |
| `<img>` | Picture Shape (object-fit:cover→crop_*) |
| `<svg>` | Chrome headless で PNG化して Picture Shape |

### 8.3 座標・単位変換

- **px → EMU**: 1280px = 12192000 EMU, 720px = 6858000 EMU
- **px → pt (フォント)**: ×0.75 (96dpi→72dpi)
- **px → EMU (線幅)**: 1px = 9525 EMU

### 8.5 修復ダイアログ対策

- `[Content_Types].xml`: Default 群 → Override 群の順序を保証 (ECMA-376 準拠)
- SVG は個別 Override で書き出し (Default不可)
- グラデ角度は 0〜360 に正規化 (`<a:lin ang>` の 21600000 範囲外を防ぐ)
- `<p:grpSpPr>` の xfrm を chOff/chExt 完備で補正
- `docProps/app.xml` をスライド実数に書き直し (Slide枚数/タイトル整合)
- 全 rect の shadow を明示指定 (`<a:effectLst/>` = 影なし)

### 8.6 サポートするフォント

- **body font-family 自動検出**: HTML の body スタイルから先頭フォント名を抽出して PPTX に反映
- **Latin + EastAsian 両方指定**: `<a:latin>` に加えて `<a:ea>` にも同じ typeface を書く (日本語グリフのフォント揃え)
- サポート例: Yu Gothic, Meiryo UI, メイリオ, Noto Sans JP, ヒラギノ角ゴ ProN, Yu Mincho

### 8.6.1 SVG をPowerPointの図形にする（2026-10-14）

SVGのあるデッキは変換時に必ずブラウザで測り（`measure_layout.py` ＋ `svg_shapes.js`）、SVGを**PowerPointの図形（自由な形）のグループ**にする（`pptx_vector.py`）。

- 線・曲線・四角（角丸）・円・楕円・多角形・弧 → 1つずつ custGeom（直線と3次ベジェ）。変形・viewBox・CSSは効いた後の値
- 塗り（不透明度つき）・直線グラデーション・線の色/太さ/端の形/角の形/破線 → そのまま
- SVGの中の文字 → 同じ位置・大きさ・太さ・色・角度の文字枠（グループの中に入る）
- 1つのSVG＝1つのグループ（名前 `Illust S枚目`・代替テキスト＝aria-label か中の文字）。PowerPointでグループの中の図形を選べば、色を変える・消す・動かすができる
- **PowerPointにあるものへ置き換えるもの**（2026-10-14 追加・利用者「できるものは対応してほしい」）
  - 影・光彩・ぼかし輪郭（BezierKit の filter・`feDropShadow`・CSS の `drop-shadow()`）→ 図形の効果（`outerShdw`・`glow`・`softEdge`）
  - 矢印の印（marker の始点・終点）→ 線の矢じり。形は BezierKit の5種（三角・鋭角・開いた矢・丸・菱形）、大きさは markerWidth（2.5以下＝小・4以下＝中・それより大）
  - 中心の放射グラデ → 「パス（円）」のグラデ
  - 図形を包む長方形の切り抜き → 外す（Illustrator・Figmaの書き出しに多い）。切り抜きの外の図形 → 出さない
  - 長方形1つのマスク: 単色 → 不透明度、直線グラデ（図形と同じ大きさ）→ 透明度つきのグラデ（端に向かって消える）
  - 塗りの規則 nonzero で穴の無い重なり → 輪郭ごとの図形に分ける（1つにすると重なりが白く抜けた）
- **`<img>` で入ったSVG**（2026-10-14）: data URL・同じフォルダの .svg を、変換の中でインラインの `<svg>` に置き換えてから図形にする（元のHTMLは変えない）。それまでは「PPTX非対応の画像形式」で黙ってPPTXから消えていた。手動トリミング（data-crop-*）のある画像は画像のまま
- **SVGの貼り付け・ドロップ**（編集画面・2026-10-14）: .svg ファイルのドロップ・貼り付け、SVGの文字（CadKit・BezierKitの「CadKit用コピー」など）の貼り付けは、img にせず座標つき div の中のインラインSVGとして入れる。PPTXで図形になり、「BezierKitで編集」でも開ける。script・foreignObject・on属性・外のURLは外してから入れる
- **`<use>`（使い回し）**: 参照先を展開して普通の図形にする（symbol の viewBox・use の x/y/width/height/transform が効く。入れ子は5段まで）。測る一時ページの中だけで展開し、元のHTMLは変えない
- **その要素だけ画像にするもの**（2026-10-14 追加）: SVGの中の `<image>`（写真など。切り抜き・変形も効いたまま）・図形そのもののぼかし・色の変換などの filter・長方形以外の切り抜きと途中で切れる切り抜き・複雑なマスク・模様・途中の印（marker-mid）・中心のずれた放射グラデ・線のグラデ。その要素（効果がグループに付いていればそのグループ）の周りだけを画像にし、同じグループの同じ順番に入れる。ほかの図形は図形のまま。理由は `INFO: … SVGの一部だけを画像にした（図形にできない: …）` で出る
- **絵全体を画像にするもの**: `<foreignObject>`・参照先の無い `<use>`・ルートの svg に付いた効果・画像にする要素が全部か12個超・図形1500個超・一部の画像を作れなかったとき。理由は `INFO: … SVGを画像にした（図形にできない: …）` で出る
- BezierKit の「スライドへ戻す」は、クリッピングマスクを切り抜いた形にして渡す（作業データはマスクのまま）
- 強制的に画像にしたい時は、SVGを包む div に `data-svg="image"`
- 見本＝`tests/fixtures/illust_vector.html`（29図形）。PowerPoint実機で開き、グループを解除すると29個の「フリーフォーム」になることを確認済み
- 効果の見本＝`tests/fixtures/bezier_effects.html`（BezierKit の見本の絵を「スライドへ戻す」と同じ形で入れたもの。作り直しは `python3 BezierKit/cdp-check.py slidefx SlideKit/tests/fixtures/bezier_effects.html`）。回帰は `tests/test_editable_text.py` の `test_bezierkit_effects_stay_shapes`・`test_generic_svg_effects`・`test_only_unshapeable_parts_become_pictures`・`test_use_and_image`

### 8.6.2 BezierKit で絵を直す（2026-10-14）

- SlideKitで絵（SVGを包む要素）を選ぶ →「✏ BezierKitで編集」→ BezierKitが開く（`#editslide=`）
- BezierKitの「スライドへ戻す」→ スライドの絵が差し替わる（⌘Zで戻せる・💾保存で確定）
- 戻した絵には BezierKit の作業データ（`<metadata id="bezierkit">`）が入る＝次に開いてもレイヤーのまま編集できる。HTML本体が正本のまま
- 作業データの無いSVG（Kiroが描いた絵など）は、普通のSVGとして図形に読み込む。SVGの中の文字は持ち込めない（開く前に確認が出る）。ラベルは `.tb` で重ねて書く

### 8.7 SVG 画像化（図形にできないSVG）

- SVG 単体ファイル書き出し: PPTX と同じフォルダに `対象.pptx_svg/` を作って個別SVGを保存 (PowerPointに手動ドラッグでベクター貼付可能)
- ラッパー `.rect` の内側に SVG がある場合: rect の枠 + SVG (PNG化) の両方を描画

### 8.8 表の詳細

- **列幅**: `<colgroup><col style="width:200px">` / `<th style="width:38%">` / 属性 `width=200` から取得
- **行高**: `<tr style="height:32px">` / `<tr height="32">` / 最初のセルの style height
- **セル色**: style `color:#hex` / `background:#hex` を汎用的にパース
- **フォント**: table の style `font-size` から検出、太字は `font-weight:700` から
- **colspan/rowspan**: 占有マップ方式で正しく配置 + `cell.merge()` で結合

## 9. 保存サーバー (`serve.py`)

### 使い方

```bash
python3 SlideKit/serve.py [port]        # 既定 8130
```

### セキュリティ

- **127.0.0.1 バインド**: LAN 公開しない
- **Origin ヘッダ検証**: 同一オリジンのみ受付、それ以外は 403
- **アトミック書き込み**: 同ディレクトリに一時ファイル→`os.replace()` で差し替え (書き込み途中のクラッシュで元HTMLを壊さない)
- PUT のみ対応、他は静的HTTP応答

## 10. 診断機能

### `check-layout.js` (ブラウザ)

- デッキに書く必要はない。検査のときは `run_check.py`（`slidecheck.py` 経由）が自動で差し込む
- ブラウザで診断したい時だけ、`</body>` 直前に `<script src="../SlideKit/check-layout.js"></script>`（HTMLからの相対パス）を書く
- 書くと右上に「⚠️診断」ボタンが出る → クリックで検出結果一覧
- 検出項目:
  - rect 同士の重なり (意図しない overlap)
  - .tb の中身あふれ (data-h 不足)
  - スライド境界からのはみ出し
  - 画像アスペクト比のずれ (5%超で警告 + 推奨サイズ提示)
  - **data-\* と style の不整合** (PPTX変換ズレの元。`data-x=100` と `style.left=150` のような食い違いを検出)

### `run_check.py` (CLI)

```bash
python3 SlideKit/run_check.py 対象.html
```

同じ検出をCLIで実行。CI組み込みや事前チェック用。デッキが check-layout.js を読んでいなくても、run_check.py が差し込んで診断する。

## 11. 制約・非対応

- **アニメーション**: SlideKit は静的スライド。PPTXアニメは対象外
- **SmartArt / ネイティブグラフ**: PPTX→HTML変換時は画像化フォールバックが現実的
- **3D 効果**: 平面化される
- **WordArt / 縁取り**: 一部落ちる
- **PowerPoint 変換で崩れやすい要素**:
  - 角丸 + 濃い border-left の交差部分 (禁止パターン)
  - box-shadow を明示指定 (data-shadow=soft のみサポート)

## 12. 拡張ポイント

> **v2**: 横断的な定義は `slidekit-defs.js` が唯一の正本。多くの拡張は defs に 1 エントリ足すだけで、
> エディタのドロップダウン・パレット置換・(該当すれば) PPTX 変換まで揃う。
> `slide-edit.js` の `TEMPLATES` は defs.formats から動的生成されるため手を入れない。

### フォーマット追加 = defs に 1 エントリ

`slidekit-defs.js` の `formats` に新しいキーを追加するだけ。パレット一括置換なら `palette` に色マップを指定する。
エディタのフォーマット選択ドロップダウンは defs.formats から自動生成される。

```js
// slidekit-defs.js の formats に追記
"green": {
  "label": "緑系モノトーン",
  "palette": { "#b01212": "#2f6c3a", "#c53030": "#2f6c3a" }
}
```

AWS のようなオーバーレイ付きフォーマットは `overlay: "aws"` と `coverBg`/`coverRemap`/`copyright`/
読み込み時に defs.formats へ自己登録される。描画は `slidekit-format.js` が行う。
見出しの体裁を変えるフォーマット（`aws2`）は `header` を持ち、利用者がそのフォーマットへ**切り替えた時だけ**
確認のうえ変換する（開いた時の自動適用では変換しない）。

### 図形追加 = defs.shapes に 1 エントリ + clip-path

`slidekit-defs.js` の `shapes` にキー (mso 名・clamp) を追加。PPTX 変換 (`add_rect_shape` の MSO 解決・
`pptx_to_slidekit.py` の逆マッピング) と図形 clamp は defs.shapes から導出されるため自動追従する。
ブラウザの見た目 (clip-path 数式) だけ `slide-edit.js` の `applyArrowShape` 等に相当関数を足す。

### PPTX変換のカスタム

`html_to_pptx.py` の `process_slide` 内、各要素ハンドラ (add_textbox / add_rect_shape / add_table / add_image / add_svg) に処理を追加。data-shadow のようにHTML側とPPTX側で対の実装を入れる。

## 13. データフロー

```
Kiro (骨組み生成)
  ↓  HTML (data属性付きスライド)
ブラウザで SlideKit ロード
  ↓  ✏️編集で微調整 / 📤Kiroへ渡す
Kiro に貼付 or 💾保存
  ↓
確定 HTML → html_to_pptx.py
  ↓
PPTX 出力 → PowerPoint 確認
```

## 14. 生成時の手順書（画像・SVG・プレースホルダー）

> 2026-08-05 に `slidekit-steering.md` から移設。判断基準は steering 側、手順の正本はここ。

### 14.1 画像

- **コンテナdivのサイズは画像のアスペクト比に合わせる**（`sips -g pixelWidth -g pixelHeight 画像` で実寸確認）。
  PPTX変換は `add_picture(x,y,w,h)` でコンテナに引き延ばすため、比率が違うと歪む
- 黒/白の土台＋`object-fit:contain` で中央寄せする方式は禁止。`<img style="width:100%;height:100%;display:block">` だけにする
- レイアウト優先で領域を固定したい時だけ `object-fit:cover`＋親`overflow:hidden`
  （変換側が crop_* に翻訳するのでPPTXでも同じトリミングになる。`object-position` 対応）
- WebP・HEICはPPTX非対応 → 事前に `sips -s format jpeg` でJPG化。`file` コマンドで実フォーマット確認
- 診断: `python3 SlideKit/run_check.py 対象.html`（アス比ずれ5%超で警告＋推奨サイズ。cover指定は対象外）

### 14.2 SVG作り込み図（透明テキスト方式）

PPTXがネイティブで描けない曲線・ファネル・テーパー・グラデ帯は:

1. **図形だけ**をインラインSVGで描く（文字は入れない・スライド契約の規則5）
2. 変換時はそのSVG領域がPNG化されて同座標に貼られる（`html_to_pptx.py` 対応済み。
   単体SVGも `対象.pptx_svg/` に書き出されPowerPointへベクター貼付可）
3. ラベル・説明文は**透明背景の `.tb`（data属性付き）を図の上に重ねる** → 文字はPPTXで編集可能なまま

- 文字色は背景帯の濃淡に合わせる（淡い帯=濃紺、濃い帯=白）
- 体制図・スイムレーン・ノード20超の大規模図はネイティブで無理に組まずD11で相談

### 14.3 図解プレースホルダー（D11・図が要るが型が決まらない時）

図解が適所なのに34型（P01〜P18・D01〜D16）のどれにも当てはまらない／自信がない時は、文字で埋めず**図解プレースホルダーを置いて提案する**。書式は `diagram-catalog.html` の D11。必須要素:

1. 枠内に**「伝えたいこと」を1文**（これが図の設計仕様になる）
2. 横に**作り方の選択肢**（□新規作図／□過去PPTXの図を移植＝候補ファイル名+ページ／□スクショを貼る／□表で十分）＋Kiroの推しに印
3. 過去の図の在処の当たりを付ける: 過去案件の報告書・分科会資料のPPTXフォルダ（論理アーキ・課題構造・修正フロー・体制図などの実績図がある）

### 14.5 依頼の枠（イラスト・グラフ・写真をどう用意するかを書いておく・2026-10-14）

イラストやグラフがあると伝わりやすいと考えた場所に、**何を描いてもらうか／どんなグラフを作るか・探すか**を書いた枠を置く。
`.ins .inszone` に `data-ask="illust|chart|photo"` を付ける。見本＝`tests/fixtures/ask_zone.html`。

| data-ask | 枠に書くこと（1行ずつ・「見出し：中身」） |
|---|---|
| `illust` | 伝えたいこと／描くもの（誰が・どこで・何をしている）／構図（枠の比率と大きさ・主役の位置）／画風（線画・色はトークンの1〜2色）／入れないもの（文字・数字・ロゴ） |
| `chart` | 伝えたいこと／作るなら（data-chart の種類・項目・値・元のデータ）／探すなら（何の調査か・検索語2つ）／出典の条件 |
| `photo` | 伝えたいこと／写すもの／撮り方（向き・距離・比率）／探すなら（検索語・使ってよい出典）／写さないもの（顔・社名） |

- 1行目の「伝えたいこと」は、画像を貼ったときに代替テキスト（`data-alt`）として残る
- 編集画面で枠を選ぶと「📋 依頼文をコピー」が出る（枠の種類＋中の文＋枠の大きさ＋「画像に文字は入れない」）。画像生成やKiroに貼る
- 画像を貼る（選んで⌘V・ダブルクリック・ドロップ）と、枠は画像に置き換わる。グラフは data-chart（5.7）に書き換える
- 💾保存しても消えない（普通のスクショ枠は保存で消える）。PPTXでは破線の枠と編集できる依頼文のまま出る
- 残っている枠は slide-guard [F7] と変換時に枚数つきで出る＝作りかけのまま渡さない

### 14.4 画像プレースホルダー（スクショ差し込み枠）

UI・画面・実物・操作手順の説明スライドに置く波線枠。編集モードでプレースホルダー選択→⌘Vでスクショを差し込める（アス比は自動フィット）。

```html
<div class="ins inszone" data-x="64" data-y="220" data-w="640" data-h="400"
     style="position:absolute;left:64px;top:220px;width:640px;height:400px;border:2px dashed #e8821a;background:rgba(232,130,26,.06);display:flex;align-items:center;justify-content:center;color:#e8821a;font-size:16px;text-align:center;overflow:hidden;padding:8px">
  📎 ここに「選択中パネル」のスクショ（右カラム全体）
</div>
```

- 指示文には**何をどの範囲で撮るか**を具体的に書く（「編集パネル」でなく「要素を選択した状態の右カラム全体」）
- プレースホルダーの縦横比は貼る予定のスクショに合わせて見積もる（縦長UI=縦長枠）
- 説明文（.tb）はプレースホルダーの横か下に置き、スクショの補足に徹する
- 未使用のプレースホルダーは💾保存時に自動で除去される（貼り忘れが焼き込まれない）

## 付録 A: 動作確認済みブラウザ

- macOS Chrome (Chromium系)
- macOS Safari (File System Access API は非対応→DLフォールバック)
- Windows Chrome (未検証だが動作するはず)

## 付録 B: 参考 steering

- `.kiro/steering/slide-contract.md`: MUST規則とカラートークンの正本（常時読込・2026-08-05新設）
- `SlideKit/slidekit-steering.md`: 判断ガイド（情報構造→表現・余白/脱AI数値・図解と画像の使い分け）
- `.kiro/steering/slide-html-to-pptx.md`: SlideKit作業時の所在案内＋コマンド（fileMatch読込）
- 配布時は slide-contract.md と slidekit-steering.md を同梱推奨

---

## 付録 C: PPTX 互換性の落とし穴と回避コード

PPTX 出力で PowerPoint が「修復ダイアログ」を出す原因は複数あり、どれも数バイトの XML ミスで発生する。ここでは実装で踏んだ地雷と回避法を全部残す。**この章の内容を守れば修復ダイアログは出ない**。

### C.1 座標変換の関数実装

```python
SLIDE_W_PX = 1280
SLIDE_H_PX = 720
SLIDE_W_EMU = 12192000   # 13.333 inch × 914400 EMU/inch
SLIDE_H_EMU = 6858000    # 7.5 inch × 914400 EMU/inch

def px_to_emu_x(px): return int(px * SLIDE_W_EMU / SLIDE_W_PX)
def px_to_emu_y(px): return int(px * SLIDE_H_EMU / SLIDE_H_PX)
def px_to_pt(px): return px * 72 / 96   # CSS 96dpi → PPT 72dpi
```

線幅: `1px = 9525 EMU` (`Emu(int(px * 9525))`)

### C.2 グラデ角度バグ (最重要・修復ダイアログの真犯人)

**問題**: python-pptx の `fill.gradient_angle` は「度」を受け取る API だが、内部で `60000` 倍して OOXML の `<a:lin ang="…">` を生成する。誤って `angle * 60000` を渡すと `ang="21600000"` に張り付く。**OOXML の `ang` は `ST_PositiveFixedAngle` 型で `[0, 21600000)` **EXCLUSIVE**。21600000 ちょうどは範囲外**で PowerPoint が修復対象にする。

**修正**:

```python
def set_gradient(slide, angle, c1, c2):
    fill = slide.background.fill
    fill.gradient()
    # CSS 角度 (真上=0°, 時計回り) → OOXML 角度 (右=0°, 時計回り) に変換 + 正規化
    fill.gradient_angle = (360 - ((angle - 90) % 360)) % 360
    stops = fill.gradient_stops
    stops[0].color.rgb = hex_to_rgb(c1)
    stops[1].color.rgb = hex_to_rgb(c2)
```

**再発防止**: どんな入力 (0/90/135/360/-45/"135deg") でも最終 `ang` が範囲内に収まる。

### C.3 Content_Types.xml のスキーマ順序

**問題**: ECMA-376 は `[Content_Types].xml` に対し `<Default>` 要素を先、`<Override>` 要素を後に置くことを要求する。`Default` を後に追加すると PowerPoint が修復対象にする。SVG を `Default Extension="svg"` として登録するのも避けたほうがよい (PowerPoint が拒否)。

**修正の要点**:

1. `<Default>` を後から追加する時は Override 群の**前**に挿入する
2. SVG は `Default Extension="svg"` にせず、`ppt/media/image*.svg` を個別 `<Override>` で書く (python-pptx の再保存挙動と一致)

```python
# Default 群の最後の位置を探して、その直後に挿入
last_default_idx = -1
for i, c in enumerate(root):
    if c.tag == f'{{{NS_CT}}}Default':
        last_default_idx = i
insert_pos = last_default_idx + 1  # Override 群の先頭
# SVG は Override として個別追加
for name in media_files:
    if name.endswith('.svg'):
        ov = etree.SubElement(root, f'{{{NS_CT}}}Override')
        ov.set('PartName', '/' + name)
        ov.set('ContentType', 'image/svg+xml')
```

### C.4 フォント: 日本語グリフの ea 指定

**問題**: python-pptx の `font.name = 'Meiryo UI'` は `<a:latin typeface="...">` しか設定しない。日本語グリフは OOXML で `<a:ea>` を参照するため、latin だけ指定すると日本語がテーマ既定フォントに落ちて改行位置がHTMLとズレる。

**OOXML の子要素順**: `<a:latin> → <a:ea> → <a:cs>`。順序違反は修復対象。

**修正**:

```python
def set_font_name(font, name):
    font.name = name  # <a:latin typeface=".."/>
    rPr = font._rPr
    if rPr is None: return
    ea = rPr.find(qn('a:ea'))
    if ea is None:
        from lxml import etree
        ea = etree.SubElement(rPr, qn('a:ea'))
        latin = rPr.find(qn('a:latin'))
        if latin is not None:
            # スキーマ順 (latin → ea → cs) を維持
            rPr.remove(ea)
            latin.addnext(ea)
    ea.set('typeface', name)
```

### C.5 `<p:grpSpPr>` の xfrm 補正

**問題**: python-pptx で新規スライドを追加すると、スライド直下の `<p:grpSpPr>` に空の `<a:xfrm>` が付く (cx=0/cy=0)。これも PowerPoint に修復対象にされる。

**修正**: xfrm を完全な形で作り直す。

```python
sld_el = slide._element
grpSpPr = sld_el.find('.//' + qn('p:grpSpPr'))
if grpSpPr is not None:
    for old in grpSpPr.findall(qn('a:xfrm')):
        grpSpPr.remove(old)
    xfrm = etree.SubElement(grpSpPr, qn('a:xfrm'))
    off = etree.SubElement(xfrm, qn('a:off'))
    off.set('x', '0'); off.set('y', '0')
    ext = etree.SubElement(xfrm, qn('a:ext'))
    ext.set('cx', str(SLIDE_W_EMU)); ext.set('cy', str(SLIDE_H_EMU))
    chOff = etree.SubElement(xfrm, qn('a:chOff'))
    chOff.set('x', '0'); chOff.set('y', '0')
    chExt = etree.SubElement(xfrm, qn('a:chExt'))
    chExt.set('cx', str(SLIDE_W_EMU)); chExt.set('cy', str(SLIDE_H_EMU))
```

### C.6 影 (outerShdw) の具体XML

`data-shadow="soft"` の rect には python-pptx の effectLst API がないため、直接 XML を挿入する。値は「薄い/自然な影」の実測値。

```python
xml = (
  '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:outerShdw blurRad="63500" dist="25400" dir="5400000" algn="t" rotWithShape="0">'
      '<a:srgbClr val="000000"><a:alpha val="20000"/></a:srgbClr>'
    '</a:outerShdw>'
  '</a:effectLst>'
)
```

- `blurRad="63500"` = 5pt (半径)
- `dist="25400"` = 2pt (距離)
- `dir="5400000"` = 5400000 / 60000 = 90° = 下方向
- `alpha="20000"` = 20% (100000で100%)

**影なし**: `<a:effectLst/>` (空要素で明示的に "no effect" を宣言)。PPTX のデフォルト影を消すため必要。

### C.7 全周ボーダー (data-border) → shape.line

```python
# data-border="1,#d6dde3" or style="border:1px solid #d6dde3"
# 第3引数で線種指定可（2026-07-31追加・GanttKit書き出しで使用）:
#   data-border="1,#94a3b8,dash" → MSO_LINE.DASH / "…,dot" → ROUND_DOT（省略=solid）
if _is_valid_hex(bc):
    shape.line.color.rgb = hex_to_rgb(bc)
    shape.line.width = Emu(int(bw_px * 9525))
```

python-pptx が自動で `<a:ln w="9525"><a:solidFill><a:srgbClr val="D6DDE3"/></a:solidFill></a:ln>` を生成する。

### C.8 画像 object-fit:cover → crop_*

**問題**: HTML の `object-fit:cover` は画像をコンテナ枠でトリミングして中央寄せするが、PPTX の `add_picture` はコンテナサイズに引き延ばすだけ (アスペクト比が違うと歪む)。

**修正**: python-pptx の `pic.crop_left / crop_right / crop_top / crop_bottom` (-1.0〜1.0 の小数) を計算する。

```python
iw, ih = Pillow で取得
img_aspect = iw / ih
container_aspect = w / h

if img_aspect > container_aspect:
    # 画像が横長 → 左右トリミング
    total_crop = 1 - (container_aspect / img_aspect)
    pic.crop_left = pic.crop_right = total_crop / 2   # 中央寄せ
elif img_aspect < container_aspect:
    # 画像が縦長 → 上下トリミング
    total_crop = 1 - (img_aspect / container_aspect)
    pic.crop_top = pic.crop_bottom = total_crop / 2
```

`object-position:left/right/top/bottom` の場合は片側 0、他方 total_crop に配分。

### C.9 SVG レンダリング (Chrome headless)

```python
subprocess.run([
    CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--default-background-color=00000000',    # 透過背景
    '--force-device-scale-factor=1',
    '--window-size=%d,%d' % (W, H),
    '--screenshot=' + png_path,
    'file://' + tmp_html_path
], timeout=60, capture_output=True)
```

- 旧Chrome向けフォールバック: `--headless` (`=new` が失敗した時)
- 解像度倍率: SVG_SCALE=2 で PPTX 上での精細さを確保
- `.rect` の内側に SVG がある場合: rect の枠 + SVG (PNG化) の両方を描画

### C.10 webp → JPG/PNG フォールバック

python-pptx は webp 非対応。事前 JPG があればそれを使い、なければ Pillow で PNG に変換。

```python
if img_path.lower().endswith('.webp'):
    jpg_path = os.path.splitext(img_path)[0] + '.jpg'
    if os.path.exists(jpg_path):
        img_path = jpg_path
    elif HAS_PIL:
        # 一時PNGに変換
        with _PILImage.open(img_path) as im:
            im.save(tmp_png, 'PNG')
        img_path = tmp_png
    else:
        return  # WARN してスキップ
```

### C.11 表 (table): 列幅と行高

**列幅の優先順**: `<colgroup><col style="width:200px">` → 最初の行の `<th>/<td> style="width:38%">` (colspan考慮)。
**colgroupの部分指定を尊重する**: `<col>`（幅なし）が混在しても指定済みの列幅は使い、幅なし列だけ残り幅を等分（全滅させて等分に落とさない・2026-08-31ルール化）。

```python
def _parse_len_px(style, attr_val, total_px, prop='width'):
    if style:
        m = re.search(rf'\b{prop}\s*:\s*(-?\d+(?:\.\d+)?)\s*(px|%)?', style)
        if m:
            val = float(m.group(1)); unit = m.group(2) or 'px'
            if unit == '%' and total_px:
                return int(val * total_px / 100)
            return int(val)
    # attribute width="200" も対応
```

反映:

```python
tbl.columns[i].width = px_to_emu_x(cw)
tbl.rows[i].height = px_to_emu_y(rh)
```

### C.14 Blue-monotone パレット (フォーマット選択の中身)

> **v2**: 青系モノトーンのパレットの正本は **`slidekit-defs.js` の `formats.blue.palette`**。
> `slide-edit.js` の `TEMPLATES` は defs.formats から動的生成されるため、ここにもコードにも値を複写しない。

置換は `slidekit-format.js` の `applyPalette()` が担い、`data-color` / `data-fill` / `style` (hex・rgb 両表記) と
表セル (th/td) を一括で書き換える。undo 統合・「置換対象なし」通知は呼び出し側 (`slide-edit.js`) の責務。

### C.15 検証フロー

生成した PPTX が修復ダイアログを出さないかを機械的に確認する方法:

```bash
python3 -c "
from pptx import Presentation
p = Presentation('output.pptx')
p.save('/tmp/resaved.pptx')
"
# 元 PPTX と再保存 PPTX を diff -rq で比較
# 差分ゼロなら OK (PowerPoint が修復不要と判断する状態)
```

python-pptx の再保存は「PowerPoint が自動修復した後の理想的な形」に近い。差分ゼロなら修復ダイアログは出ない。差分があれば、その差分の内容が修復対象。

### C.16 チェックリスト

新しい PPTX 生成機能を追加する時、以下を全部通過するかを確認する:

- [ ] `<a:lin ang>` が全スライドで `[0, 21600000)` 内
- [ ] `[Content_Types].xml` の Default → Override 順序
- [ ] SVG は個別 Override で登録 (Default不可)
- [ ] `<a:latin>` の直後に `<a:ea>` (順序遵守)
- [ ] `<p:grpSpPr>` の xfrm が完全形 (cx/cy > 0)
- [ ] `<a:effectLst/>` が影ありと影なしの両方で明示指定
- [ ] `<a:gs pos>` が `[0, 100000]`
- [ ] `<a:srgbClr val>` が 6桁hex
- [ ] `<p:cNvPr id>` が重複していない
- [ ] `<a:ext cx cy>` が正の値
- [ ] python-pptx 再保存との diff がゼロ (最終確認)


---

## 付録 D: Capability Matrix (対応状況一覧)

エディタ (`slide-edit.js`) と PPTX コンバータ (`html_to_pptx.py`) の対応状況を機能単位で整理する。
未対応機能を silent skip しないための機械可読な参照。

**凡例**
- 🟢 対応 (両方で完全動作)
- 🟡 部分 (片方のみ、または限定条件で動作)
- 🔴 未対応 (無視される)
- ⚠️ 未対応だが警告を出す (現状は sink するのが理想)

### スライド (.slide 直下 data-\*)

| data-\* | 値の例 | HTML表示 | PPTX変換 | 備考 |
|---|---|---|---|---|
| data-bg | `#fafafa` | 🟢 | 🟢 | 単色背景 |
| data-bg-gradient | `135,#183251,#21537f` | 🟢 | 🟢 | 2色線形グラデ |
| data-aws-logo | `off` | 🟢 | 🟢 | AWS フォーマット時にロゴを外す (中表紙用) |
| data-notes | `話すこと` | 🟢（手元のみ） | 🟢 | 発表者ノート。PPTXのノート欄へ・投影には出ない |
| data-aws-decoration | `on` | 🟢 | 🟢 | 旧仕様 (自動で data-template=aws に格上げ) |

### テキストボックス (.tb)

| data-\* | 値の例 | HTML表示 | PPTX変換 | 備考 |
|---|---|---|---|---|
| data-x, y, w, h | `64, 76, 1152, 40` | 🟢 | 🟢 | 絶対座標 (px) |
| data-font-size | `28` | 🟢 | 🟢 | px |
| data-bold | `1` | 🟢 | 🟢 | 太字 |
| data-color | `#1a365d` | 🟢 | 🟢 | 文字色 |
| data-fill | `#f7fafc` / `none` | 🟢 | 🔴 | **PPTXでは塗られない**。背景が要る文字は .rect の上に .tb を重ねる |
| data-align | `left/center/right` | 🟢 | 🟢 | 水平揃え |
| 中の `<b>` `<strong>` / `<div>` `<p>` | | 🟢 | 🟢 | 太字の run／1行ずつの段落になる（2026-09-27〜）。`<i>` `<u>` は未対応 |
| 全角スペース・`&nbsp;` | | 🟢 | 🟢 | 潰さずに残る（2026-09-27〜） |
| 中の `<a href>` | | 🟢 | 🔴 | リンクにならず文字だけ出る。ページ間リンクは data-link-sid |
| data-bullet | `disc/decimal` | 🟢 | 🟢 | ぶら下げ字下げ (marL/indent)。マーカーは本文文字 |
| data-bullet | `native-disc/native-decimal` | 🟢 | 🟢 | PowerPointネイティブ箇条書き (buChar/buAutoNum + lvl + lstStyle) |
| data-lvl (`.li`) | `0`〜`4` | 🟢 | 🟢 | ネイティブ箇条書きの階層。`<a:pPr lvl>` になる |
| data-valign | `top/middle/bottom` | 🟢 | 🟢 | 単独の .tb はテキストフレームのアンカーに変換 |
| data-role | `title` | 🟢 | 🔴 | 編集時のタイトル判定用のみ (PPTX には影響なし) |
| data-linked-parent | (skid) | 🟢 | 🔴 | Alt+クリック分離した子tb の親リンク (エディタのみ) |

### 矩形・シェイプ (.rect)

| data-\* | 値の例 | HTML表示 | PPTX変換 | 備考 |
|---|---|---|---|---|
| data-x, y, w, h | `64, 40, 200, 34` | 🟢 | 🟢 | 絶対座標 |
| data-fill | `#162a42` / `none` | 🟢 | 🟢 | 塗り色 |
| data-radius | `12` | 🟢 | 🟢 | 角丸 px |
| data-shape | `arrow` | 🟢 | 🟢 | 右向き矢印 (adjustments で幅調整) |
| data-shape | `chevron` | 🟢 | 🟢 | 五角形 (ホームベース型) |
| data-shape | `circle` | 🟢 | 🟢 | 楕円（※`oval`は不可・defsの正キーは`circle`） |
| data-shape | `triangle` | 🟢 | 🟢 | 三角形 |
| data-shape | `line` | 🟢 | 🟢 | 細い塗り四角 |
| data-at, data-ah | `0.45, 0.32` | 🟢 | 🟢 | data-shape=arrow の軸の太さ/矢じり長さ |
| data-cv | `0.14` | 🟢 | 🟢 | data-shape=chevron の尖り具合 |
| data-border | `1,#e2e8f0` | 🟢 | 🟢 | 全周ボーダー (幅,色) |
| data-border-left | `4,#c53030` | 🟢 | 🟢 | 左サイド帯 |
| data-border-top | `4,#38a169` | 🟢 | 🟢 | 上サイド帯 |
| data-border-right | `4,#...` | 🟢 | 🔴 | **未対応** (エディタのみ style 反映) |
| data-border-bottom | `4,#...` | 🟢 | 🔴 | **未対応** (エディタのみ style 反映) |
| data-border-style | `wavy` | 🔴 | 🔴 | **未対応** (実線のみ) |
| data-shadow | なし/`none` (無効化) | 🟢 | 🟢 | シェイプの影を明示的に外す（既定） |
| data-shadow | `soft` (薄い影) | 🟢 | 🟢 | 薄い影を付ける (a:outerShdw) |

### 表 (table)

| 属性 | 値の例 | HTML表示 | PPTX変換 | 備考 |
|---|---|---|---|---|
| data-x, y, w, h | `64, 130, 1152` | 🟢 | 🟢 | 絶対座標 (h は省略可・行数から自動計算) |
| colspan, rowspan | `2` | 🟢 | 🟢 | セル結合 |
| style: width | `120px` | 🟢 | 🟢 | 列幅 (colgroup から拾う) |
| style: height | `48px` | 🟢 | 🟢 | 行高 |
| style: font-size | `15px` | 🟢 | 🟢 | セル別フォント (無指定は表全体の font-size) |
| style: text-align | `left/center/right` | 🟢 | 🟢 | セル内水平揃え |
| style: vertical-align | `top/middle/bottom` | 🟢 | 🟢 | セル内垂直揃え |
| style: background | `#1a365d` | 🟢 | 🟢 | セル塗り |
| style: color | `#fff` | 🟢 | 🟢 | セル文字色 |
| style: border | `1,#e2e8f0` 形式でなく CSS (`1px solid #e2e8f0` / `none`) | 🟢 | 🟢 | セル全周の線 (a:lnL/lnR/lnT/lnB) |
| style: border-top/right/bottom/left | `2px solid #21537f` / `none` | 🟢 | 🟢 | セル1辺の線。`none` は noFill で「線なし」を明示 |
| `<tr>` の style | `background/color/font-weight/font-size/text-align/vertical-align` | 🟢 | 🟢 | セルに指定が無い時のフォールバックとして継承（ヘッダ行を tr にまとめて書ける） |

表スタイルは "No Style, No Grid" 固定なので、**CSSで線を書いたセル辺だけPPTXに線が出る**（＝ブラウザと同じ見た目）。

**疑似結合（セル結合を使わない大項目のグルーピング）**: 縦に並ぶ複数セルを同じ背景色で塗り、
グループの外周辺だけ線を引く（先頭セル=top+left+right、中間セル=left+right、末尾セル=left+right+bottom）。
中身のテキストは先頭セルにだけ書き、残りは空にする。rowspan と違って行の追加・削除・並べ替えで
構造が壊れず、SlideKit編集UIのセル単位操作もそのまま効く。見本は `pattern-catalog.html` P18。

編集UIからは表ミニツールバーの「大項目」ボタンで一発適用できる:
表をクリックで選択 → セルの上をドラッグ（またはセルをクリック → 端のセルを Shift+クリック）で
範囲選択 → 「大項目」。塗りは青灰 `#eef3f8`（左上セルに既存の背景があればその色を引き継ぐ）、
線は枠色入力が既定のままなら `#21537f`。「解除」で塗り・枠線を外す。

### 画像・SVG

| 種類 | 属性 | HTML表示 | PPTX変換 | 備考 |
|---|---|---|---|---|
| `<img>` 親div | data-x/y/w/h | 🟢 | 🟢 | ラッパー div のサイズで PPTX 配置 |
| `<img>` | src (相対パス) | 🟢 | 🟢 | HTMLファイルからの相対解決 |
| `<img>` | style: object-fit:cover | 🟢 | 🟢 | crop_left/right/top/bottom に変換 |
| `<img>` | style: object-position | 🟢 | 🟢 | キーワード2語（順不同）・0%/100% を crop に反映 |
| `<img>` | style: width:100%;height:auto | 🟢 | 🟢 | 幅に合わせ、枠を超えた下を切る（引き伸ばさない） |
| `.rect`/`.flow` 直下の `<img>` | | 🟢 | 🟢 | 枠と同じ位置に画像（2026-09-27〜）。それより深い img・表・入れ子の枠・孫の .tb は出ないので WARN |
| 画像が見つからない／svg・heic・avif／http(s) | | 🟢 | ⚠️ | 欠落として記録し `.incomplete.pptx`＋exit 2（SVG・動画と同じ扱い） |
| WebP 画像 | | 🟢 | 🟢 | 同名 .jpg があれば使用、無ければ Pillow で一時 PNG に変換 |
| 親div | data-border | 🟢 | 🟢 | 画像の枠線 |
| 親div | data-clip="circle" | 🟢 | 🔴 | **未対応** (エディタは border-radius:50% で丸表示、PPTXは矩形のまま) |
| `<svg>` ラッパーdiv | data-x/y/w/h | 🟢 | 🟢 | Chrome headless で PNG ラスタライズ (Chrome 必須) |
| Chrome 見つからない | | 🟢 | � | **error 化済み**: 既定で exit code 2 + `.incomplete.pptx` に別出力。`--allow-missing-assets` で警告続行 (通常名で保存) |
| SVG 単体書出し | | - | 🟢 | `<出力名>_svg/SN_xX_yY_WxH.svg` に別出力 |

### 修復ダイアログ対策 (OOXML レベル)

以下は付録 C にも記載。修復ダイアログを出さないための処理はすべて実装済み。

| 対策 | 状況 |
|---|---|
| [Content_Types].xml Default → Override 順序保証 | 🟢 |
| SVG 個別 Override (Default 不可) | 🟢 |
| グラデ角度変換 `(360 - ((a - 90) % 360)) % 360` | 🟢 |
| 影の明示削除 (`effectLst` 空要素) | 🟢 |
| Group 空 `grpSpPr` 削除 | 🟢 |
| app.xml AppVersion 数値化 | 🟢 |

### 未対応で 🔴 の項目 (優先順)

1. **data-border-right / data-border-bottom** → 右・下サイド帯を PPTX で描画
2. **data-clip="circle"** → PPTX 側で楕円クリップ
3. **data-valign (.tb)** → テキストボックス垂直揃え
4. **data-border-style="wavy"** → 波線 (PPTX の a:prstDash="sysDash" 等で近似)

### 完了項目

- ~~Chrome 見つからない時の silent skip~~ → 2026-07-11 error 化完了 (exit code 2 + `.incomplete.pptx`)

---

**このマトリクスの使い方**

- 新機能を SlideKit に追加する時は、この表に行を追加してから実装
- エディタで操作可能な機能が PPTX で 🔴 になっている場合は、エディタで「(PPTX非対応)」の警告を出す
- Kiro でスライド HTML を書く時、この表の 🟢 だけを使うのが安全


---

## 付録 E: 公開 API (window.SlideKit)

外部ツール (slide-present.js 等) から SlideKit を操作するための正規窓口。
内部関数を直接呼んだり、Escape キー合成のような間接操作をする代わりに、ここに列挙した関数だけを使う。

### `SlideKit.clearSelection()`
要素選択・ページ選択・contenteditable フォーカスを全部解除。

### `SlideKit.stripAllOutlines(root)`
`root` (省略時は document) 配下の `.slide` および子要素から outline スタイルを強制的にクリア。プレゼン同期時に選択枠が漏れるのを防ぐ用途。

### `SlideKit.isEditing()`
編集モード ON/OFF を bool で返す。

### `SlideKit.addStickyNote(slide, opts)`

編集ウィンドウの指定スライドへ、PPTXでも編集可能なポストイット型メモを追加する。
`slide`省略時は現在ページ、`opts`では`text`、`x`、`y`を指定できる。追加直後に本文を全選択して入力状態に入り、Undo・保存・プレゼン別窓への300ms同期は既存の編集経路を使う。

- 既定サイズ: 300×150px、本文20px
- メモの選択枠右上に `− 20px ＋` を表示し、2px刻み（15〜48px）で変更できる。入力中に押してもフォーカスを維持する
- 既定色: 薄黄 `#f4f4ef`
- 同じページへ続けて追加すると5枚単位で少しずつ重なり、次の束は左へ移る
- `data-note="1"`は保存後も残る。`data-inserted`と`contenteditable`だけをサニタイズで除去する

### `SlideKit.sanitizeSlide(el, mode)`

「編集 UI を剥がして正本 HTML に戻す」処理を一本化した API。事前に `cloneNode(true)` してから渡す（in-place で子孫まで書き換える）。

**mode 一覧**

| mode | 用途 | 除去/処理 |
|---|---|---|
| `'save'` | 💾 保存用（PPTX 変換にもかける HTML） | `.seui` / `.inszone` / `contenteditable` / `outline` / `data-role` / `data-inserted` |
| `'copy'` | ページ複製・ペースト用 | `.seui` / `contenteditable` / `outline` / `data-role` / `data-inserted` + ページ番号 |
| `'sync'` | プレゼン別窓へのリアルタイム同期用 | `.seui` / `contenteditable` / `outline` / `.aws-overlay` + `.aws-cover` class / `box-shadow` 元値復元 |

**設計方針**

- 従来は 3 箇所 (`cleanSlideClone` / `buildCleanHTML` / `sendSlideUpdate` / `sendDeckSync`) で個別に「剥がすリスト」を書いていた
- 新しい UI クラスが増えた時に片方だけ反映漏れて事故る問題 (実例: 選択枠がプレゼン側に漏れる) を根絶
- 剥がすリストは 1 箇所 (`SlideKit.sanitizeSlide`) だけで管理
### `SlideKit.applyFormat(slides, opts)`

(v2 追加) 現在の `data-template` / `data-aws-decoration` フォーマットを指定スライド群へ適用する窓口。
`slides` 省略時は document 内の全 `.slide`。AWS フォーマット時のみ `slidekit-format.js` の
`applyAwsOverlay()` を各スライドに適用する (パレット系は保存 HTML に色が焼き込まれているため再適用対象なし)。

- `opts.uiClass`: 追加ノードに付けるマーカークラス (既定 `'seui'`)。保存時サニタイズの除去対象。
- `window.SlideKitFormat` 未ロード時・AWS 以外のフォーマット時は何もしない (安全に縮退)。
- `hideUI=1` (投影コンソール / プレゼン窓) でも `window.SlideKit` は定義されるため、この API は常時呼べる。

**設計方針 (v2)**: フォーマット描画の実体は `slidekit-format.js` に一本化され、`slide-edit.js`
(編集画面) と `slide-present.js` (プレゼン窓) が同じ関数を呼ぶ。v1 で slide-present.js にあった
約 100 行の複製 (isDarkSlide / 光彩背景 / リマップ CSS / コピーライト / ロゴ解決) は削除済み。
