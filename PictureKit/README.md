# PictureKit

Adobe Lightroom／Photoshopから日常の写真作業を移すためのRAW現像・画像編集Kit。
RAW現像を非破壊recipeとして保持し、JPEG／PNG／8bit・16bit TIFFへ書き出す。

## 現在の現像機能

- RGBヒストグラム、自動補正、Before／After、90°回転
- 1:1／3:2／4:3／16:9クロップと位置調整
- 輝度・RGBトーンカーブ、現像preset、recipe JSON保存／再読込
- 色温度、Tint（±100でR/Bが2段動く。スポイトで青い影のグレーも取れる）、露出、ハイライト、シャドウ、白・黒レベル
- テクスチャ、明瞭度、かすみ除去、輝度・カラーノイズ低減
- HSLミキサー、白黒ミキサー、カラーグレーディング、3D LUT
- 写真を閉じる（ライブラリの×。現像cacheを消す。recipeは保存済みなので開き直せば戻る）
- ベジェ・色域・ブラシマスクによる部分補正、スポット修復・clone（コピー元は周囲に合う場所を自動で探す。ドラッグで動かせる）
- 画像レイヤーの追加、空レイヤー、複製、範囲コピー／貼り付け、表示順、移動、サイズ、回転、不透明度
- レイヤー本体への非破壊ペイント／消しゴム（移動・拡縮・回転へ追従）
- Normal／Multiply／Screen／Overlay／Darken／Lighten／Difference
- レイヤー追従ブラシマスク（加筆・消去・硬さ・不透明度・反転）
- **レイヤーをベジェで切り抜き**（囲みのぼかし付き。ブラシと併用して境界を詰められる）
- **選択範囲の内側だけに描く**（ブラシ・消しゴム・Clone・ぼかしを範囲内に閉じ込める。使う範囲はプルダウンで選び、塗っている間は赤く表示）
- 非破壊ピクセル編集（ペイント・消しゴム・連続Clone・ぼかし）
- 非破壊Content-Aware Fill（範囲描画・コピー元自動探索・Undo）
- 非破壊Liquify（押す・膨らませる・つまむ、サイズ・強さ・Undo）
- DCPカメラプロファイル（RAWのみ。Adobe Camera Rawが無いMacでも同梱の「PictureKit Standard」＝ACR標準カーブが既定）、lensfun／Adobe LCPレンズ補正
- フリンジ軽減（紫・緑）: 白飛びした空と枝の境目などに出る色収差の縁を、強い輝度差のそばだけ無彩色に寄せる。紫や緑の被写体そのものは変えない。preview・100%・書き出しで同じ式
- JPEG／PNG／8bit TIFF／16bit TIFF書き出し（全形式に撮影情報EXIFとsRGB ICCを引き継ぐ）
- **PSDのレイヤー読み込み**（レイヤー・座標・不透明度・7種のブレンド・マスク込みの見た目）
- **ライブラリの絞り込み**（星0〜5・キーワード・撮影日の範囲・カメラ機種。星はキーボード1〜5、0で消す。星とキーワードはrecipeに非破壊で同居させ、無ければ0／空）
- **書き出しプリセットと一括書き出し**（形式・長辺px・品質・ファイル名の付け方をpresetとして`images/export-presets.json`に保存。絞り込んだ写真を1つのpresetでまとめて書き出し、進み具合を出し途中で止められる。sRGB ICCは常に付く）

## 右パネル

右パネル上部の「RAW現像／画像編集」で作業を切り替える。切替は表示順だけを変え、recipeと編集内容は保持する。

- RAW現像: プロファイル、WB、ライト、トーン、カラー、質感、レンズ、切り抜き、部分補正
- 画像編集: 画像レイヤー、レタッチ、Content-Aware Fill、ピクセル編集、Liquify（PSD読み込みは「画像レイヤー」の「＋PSDのレイヤーを読み込む」）
- 設定と書き出しは両モード共通
- リセットは現在のモードだけに作用。RAW現像リセットは画像編集を残し、画像編集リセットはRAW現像と部分補正を残す
- JPEG品質などの書き出し設定は、どちらのリセットでも保持

## 対象カメラ

- PENTAX K-1 Mark II（PEF / DNG）
- PENTAX K-3（PEF / DNG）
- RICOH GR III（DNG）
- SIGMA fp（DNG）

## 起動

Finderで **`PictureKit.command` をダブルクリック**する。ローカルサーバーが起動し、ブラウザが自動で開く。
初回にmacOSの確認が出た場合は、右クリック→「開く」を選ぶ。

Terminalから起動・検証する場合:

```bash
PictureKit/.venv/bin/python PictureKit/picturekit.py
PictureKit/.venv/bin/python PictureKit/check.py
PictureKit/.venv/bin/python PictureKit/check.py --full
```

依存環境を作り直す場合:

```bash
python3 -m venv PictureKit/.venv
PictureKit/.venv/bin/pip install -r PictureKit/requirements.txt
```

RAWは外部へ送信せず、`http://127.0.0.1:8765`（使用中は8766以降）のMac内だけで処理する。認証はなく、localhost以外には公開しない。
見出しのスタイルは隣の `DesignKit/design-kit.css` を使い、無い環境では同梱の `design-kit.css` に切り替わる。前回異常終了で残った現像cache（`picturekit-*`）は起動時に消す。

## 現像pipeline

- LibRaw/rawpyでcamera WB・highlight recoveryを適用し、16bit linear sRGBへ一度だけ展開
- full RAWと1400px previewを16bit `.npy`へsession cache
- tone／colorはfloat32チャンク、保持バッファはencoded sRGB uint16
- DCP（HSVテーブル＋カーブ）は65³の3D LUTに1回だけ焼き込んで掛ける（スライダー1回の反応 2秒→1秒。Kit Vividだけは値の飛びが大きいので全画素計算）
- 100%表示のレンズ補正はタイルの領域だけ計算する（LazyLens。全面24MPの補正cacheを待たない。100%の初回 4秒→1秒）。フルサイズ書き出しは全面を補正してcache
- 画面表示用PNGは compress_level=1（localhostなので圧縮率より速さ）
- 色温度・Tintの係数はwbModel 2（±100で各チャンネル±1段）。古いrecipe（wbModel無し）は読み込み時に値を換算する
- detailは8bit Pillow処理の補正差分だけをuint16へ戻し、細階調を保持
- mask／retouch／grainまでuint16で処理し、8bit化はJPEG／PNG／8bit TIFFの直前だけ
- ブラシマスクは加筆・消去・サイズ・硬さ・不透明度を非破壊strokeとしてrecipeへ保存
- 画像レイヤー素材はcontent-addressed保存し、100%表示・書き出しでlinear alphaのuint16合成
- レイヤー描画はlocal strokeとして保存し、asset→paint／erase→mask→rotation→blendの順で再現
- 空レイヤーと範囲コピーはcanonical PNG asset、複製は不変assetを共有してstroke／maskだけdeep copy
- Blend Modeはlinear RGBで演算。レイヤーマスクはlocal strokeをalphaへ乗算して画像と一緒に変形
- ピクセル編集はmask／retouch／Content-Aware Fill／Liquify後、grain／画像レイヤー前にuint16でstrokeを再実行
- Content-Aware Fillは720px解析で外周が合うコピー元を決め、source座標をrecipeへ固定してfull／tileでsoft合成
- Liquifyは逆写像とbilinear補間でuint16変形し、100% tileはstrokeの最大変位分だけ依存領域を拡張
- 16bit TIFFはDeflate圧縮、sRGB ICC付きの現像マスター

## 検証

複数の確認は1コマンドへ集約している。`--full`だけフルサイズJPEGも生成して確認する。

## 現在の制限

- 写真カタログ（複数フォルダの常設管理）は未実装。開いた写真のライブラリは星・キーワード・撮影日・機種で絞り込める
- ブラシマスクは長辺1400pxでラスタライズ。1マスク128stroke・合計12000点まで
- JPEG／PNG／TIFFを開いたときカメラプロファイルは出ない（現像済みの画像に重ねない）
- 100%表示とフルサイズ書き出しの待ち時間は残り時間の表示が無い（status文言のみ）
- ピクセル編集は最大128stroke・合計12000点・サイズ最大10%。消しゴムは編集前の現像結果へ復元
- 画像レイヤーは64枚まで（超えると状態欄に知らせる）
- Content-Aware Fillは最大32操作・1操作512点・合計6000点・サイズ最大12%。初版は1つの平行移動パッチなので、大きな人物や複雑な規則模様には弱い
- Liquifyは最大128stroke・1 stroke 1024点・合計12000点・サイズ最大5%。書き出しは逆写像を1回のcopyで行う（24MPで+1〜2秒）
- Clone元と消しゴムの復元元はpixelEdits開始前のclean画像。先行paint結果はClone元に含めない
- 画像レイヤーは最大64枚。レイヤー描画とレイヤーマスクは全レイヤー合計12000点まで
- 範囲コピーはPictureKit内の一時クリップボード。別アプリのクリップボードやPSDファイルとの直接交換には未対応
- fit表示のレイヤー描画／Blend／maskは最大1024pxの操作用近似（BlendはCSSのmix-blend-mode＝sRGB合成）。100%表示と書き出しのlinear合成を正とする
- レイヤー素材はローカル`images/assets/`に保存され、recipe JSON単体では別Macへ移らない
- 読み込んだレイヤー素材は初版ではcanonical 8bit sRGB PNGへ変換
- 内部・16bit TIFFはencoded sRGBで、広色域・CMYKには未対応
- DCP／LCPはMac上のAdobe Camera Raw資産の有無で利用可能範囲が変わる
- 対象4機種の実機RAWを各1枚ずつ追加検証する必要がある

## PSDの読み込み
Photoshopで作った既存データを取り込む。`psd-tools` が必要（`.venv/bin/pip install psd-tools`）。
右パネル「画像編集」→「画像レイヤー」→「＋PSDのレイヤーを読み込む」。

取り込めるもの
- レイヤーの画像・位置・サイズ・不透明度
- ブレンドモードは7種（normal／multiply／screen／overlay／darken／lighten／difference）
- レイヤーマスクとレイヤースタイルは**見た目に焼き込んだ状態**で入る

取り込めないもの（画面に理由が出る。黙って変換しない）
- 調整レイヤー → 取り込まない。PictureKitの現像側で作り直す
- 文字・スマートオブジェクト → 編集できない画像になる
- 上記7種以外のブレンド（Soft Light等20種）→ normal に落として警告
- 非表示レイヤー → 取り込まない
- クリッピングマスクを含むグループ・3階層以上の入れ子 → 1枚に統合

🚫 **PSDの書き出しは持たない。** 往復すると調整レイヤーとスマートオブジェクトが壊れるため、
読み込み専用にしている。Photoshopへ渡すなら書き出し（TIFF/PNG）を使う。

## 切り抜きと範囲指定（BezierKitの能力をそのまま使う）
パス編集はBezierKitと同じ操作系。クリックで直線、ドラッグで曲線、Option＋線クリックでアンカー追加、
アンカーをダブルクリックで角⇄滑らか、Deleteで削除（3点未満にはしない）。

### レイヤーを切り抜く
「画像レイヤー」→「レイヤーマスクを追加」→「**ベジェで囲む**」。
レイヤーの上をクリック／ドラッグで囲み、先頭クリックかダブルクリックで確定（Escで取消）。
- 「囲みのぼかし」で境界をなじませる
- **はみ出しは「マスクを塗る」の消しゴムで詰める**（パスが土台、ブラシがその上に重なる）
- 「囲みを消去」でパスだけ外せる（ブラシの描画は残る）

### 選択範囲を作る3つの方法（部分補正）
| 方法 | ボタン | Photoshopでいうと |
|---|---|---|
| ベジェで囲む | 範囲を追加 | パス→選択範囲 |
| 同じ色を選ぶ | 色で追加 | 色域指定／自動選択（`contiguous`で隣接のみに切替） |
| ブラシで塗る | ブラシで追加 | クイックマスク（消しゴムで削れる） |

### 選択範囲の内側だけ塗る
「ピクセル編集」で「**選択範囲の内側だけに描く**」にチェックを入れると、
そのとき選んでいる範囲の外にはみ出さなくなる。Photoshopの「選択範囲内を塗りつぶす」に相当。
