# BezierKit 仕様と追加計画（2026-10-14）

`index.html` 1ファイル・ビルド不要・file://で起動。機能の履歴は `.kiro/steering/projects/bezierkit.md`。
このファイルは「これから足すもの」と「PowerPointに渡すときの約束」を書く。

## 1. 使う場面

・スライド（SlideKit／PowerPoint）に載せるイラスト・図解・アイコンを描いて、PowerPointでも図形のまま直せる形で渡す
・CadKit・PictureKit・SlideKitとの往復（線画の受け取り、トレース、アイコンカタログ）
・Kiroが書いたSVGを開いて人が手で直す。人が直したものをKiroが読む

## 2. 競合との比較

調べた範囲は Illustrator 2026（v30）、Figma Draw、Affinity（2025年10月からCanvaが無料で提供）、Inkscape 1.4、PowerPoint の図形機能。

| 機能 | Illustrator | Figma Draw | Affinity | Inkscape | PowerPoint | BezierKit 現状 | 判断 |
|---|---|---|---|---|---|---|---|
| ペン・アンカー編集・パス演算 | ○ | ○ | ○ | ○ | △ 頂点編集・図形の結合 | ○ | 済 |
| 幅ツール・線端効果・うねり | ○ | ○ 可変線幅 | ○ | ○ パスエフェクト | × | ○（塗りに展開して書き出し） | 済 |
| シェイプビルダー | ○ | ○ | ○ | ○ | △ 図形の結合＞分割 | ○ | 済 |
| 画像トレース | ○ | × | × | ○ | × | ○ 曲線フィット付き | 済 |
| 影・光彩・ぼかし輪郭 | ○ 効果 | ○ | ○ | ○ フィルター | ○ 図形の効果 | × | A：PPTXの効果に直結する |
| 放射グラデ・多色グラデ | ○ | ○ | ○ | ○ | ○ | × 2色の直線のみ | A |
| 矢印の種類 | ○ | ○ | ○ | ○ マーカー | ○ 9種×大きさ | △ 1種 | A：PPTXの矢印に直結する |
| PPTXで図形のまま渡す | △ 画像かEMF | × | × | × | — | △ SlideKit経由 | A：直接書き出しを作る |
| 複数アートボード | ○ | ○ フレーム | ○ | ○ ページ | ○ スライド | × | B：1アートボード＝1スライド |
| シンボル（同じ絵の使い回し） | ○ | ○ コンポーネント | ○ | ○ クローン | × | × | B |
| グローバルカラー（色名で一括変更） | ○ | ○ 変数 | ○ | △ | ○ テーマの色 | △ 再配色 | B：PPTXのテーマの色に出す |
| 繰り返し（放射・グリッド・ミラーのライブ版） | ○ | × | × | ○ | × | △ 確定版のみ | B |
| ナイフ・消しゴム・ブロブブラシ | ○ | △ | ○ | ○ | × | △ ハサミ | C |
| 文字からベクター生成（生成AI） | ○ Firefly | ○ | ○ 有料 | × | ○ Designer | × | C：Kiroが描く経路を整える（5章） |
| 透視グリッド・3D | ○ | × | × | ○ | ○ 3D回転 | × | 見送り |

### Illustratorのファイルを扱える道具（2026-10-14 追加）

| 道具 | 動く場所 | AIを開く | 書き出し | BezierKitに足すもの |
|---|---|---|---|---|
| Vectorpea | ブラウザ（登録なし） | ○ AI・EPS・PDF | SVG・PDF・PNG ほか | AI／PDFを開く（BK-P14） |
| Photopea | ブラウザ | ○ グループ・切り抜き・不透明度・描画モード・文字が残る | PSD・SVG・PDF | 切り抜きをマスクに、文字を文字に（BK-P14） |
| Vectorholic | ブラウザ（開発中） | △ 形・塗り・線（文字・グラデ・効果は落ちる） | SVG・PNG（PDFは有料） | シンボル（BK-P10） |
| Affinity | Mac・Windows（無料） | ○ PDF互換のAI | PDF・SVG・EPS ほか | PDF書き出し（BK-P15） |
| Graphite | ブラウザ（オープンソース・alpha） | × | SVG・PNG | 非破壊の効果（BezierKitの幅・うねり・線端と同じ方向） |

Vectorpea は [XDA の紹介](https://www.xda-developers.com/inkscape-good-adobe-illustrator-alternative-but-free-app-even-better/)、Photopea は [Photopea 5.0 の告知](https://blog.photopea.com/photopea-5-0-open-illustrator-files.html)、Vectorholic は [公式](https://vectorholic.com/)、Graphite は [公式](https://www.graphite.rs/) を参照した。

Illustratorの新機能は [Adobe のリリースノート](https://helpx.adobe.com/ee/illustrator/desktop/new-features/release-notes.html)、Figmaは [Figma Draw の紹介](https://www.figma.com/blog/introducing-figma-draw/)、Affinityは [Canva の発表](https://www.canva.com/newsroom/news/all-new-affinity/) を参照した。

## 3. 追加する機能要件

A＝PowerPointに渡す力に直結するもの。B＝描く力。C＝余力があれば。

| ID | 優先 | 要件 | 受け入れの目安 |
|---|---|---|---|
| BK-P1 | A | PPTXで書き出す（全体・選択） | PowerPointで開くと修復なしで開き、グループ解除で1図形ずつ色・線・頂点を直せる |
| BK-P2 | A | PPTX確認（書き出す前に、どの図形がどう変わるかを数で出す） | 「図形のまま／形に焼いて図形／文字枠／出ないもの」の4つに分け、行クリックで該当図形を選ぶ |
| BK-P3 | A | 文字はPowerPointで直せる文字枠で出す（切り替えで形のまま） | フォント名・大きさ・色・太字がPowerPointで変えられる |
| BK-P4 | A | スライドの大きさのアートボード（16:9＝1280×720、4:3＝960×720） | 1px＝9525EMU、SlideKitと同じ座標 |
| BK-P5 | A | 影・光彩・ぼかし輪郭（外観） | 画面はSVGのfilter、PPTXは outerShdw／glow／softEdge |
| BK-P6 | A | 放射グラデ・3色以上のグラデ | PPTXは gradFill（lin／path="circle"）の gsLst |
| BK-P7 | A | 矢印の形と大きさ（三角・鋭角・丸・菱形・矢じり、小中大） | PPTXは headEnd／tailEnd |
| BK-P8 | B | 複数アートボード（1枚＝1スライド） | PPTXでスライドが並ぶ |
| BK-P9 | B | グローバルカラー（色に名前を付けて一括で変える） | PPTXはテーマの色（accent1〜6）に出す |
| BK-P10 | B | シンボル（同じ絵を複数置いて元を直すと全部変わる） | PPTXでは展開して図形にする |
| BK-P11 | B | ライブ繰り返し（放射・グリッド・ミラー） | 元を直すと並びが追従する。PPTXでは展開 |
| BK-P12 | C | ナイフ・消しゴム | 閉じた図形を線で2つに切る |
| BK-P13 | C | Kiroの描画手順（5章）をSkillにする | Kiroが書いたSVGがPPTX確認で「出ないもの」0件 |
| BK-P14 | A | AI（PDF互換）・PDFを開く | 実物のAIを開いて、macOSのPDF描画と見た目がそろう。AIのレイヤー・切り抜き・文字が入る |
| BK-P15 | B | PDFで書き出す | Illustrator・Affinityで開ける |
| BK-P16 | C | 描画モード（乗算など） | PPTXには無いので「出ないもの」に数える |

## 4. PPTXに渡すときの約束

1つの図形は custGeom（PowerPointのフリーフォーム）1つにする。レイヤーはグループにして、名前をレイヤー名にする。

| BezierKitの持ち物 | PPTXでの形 | 種類 |
|---|---|---|
| 塗り（単色）・不透明度 | solidFill＋alpha | 図形のまま |
| 塗り（直線グラデ） | gradFill lin | 図形のまま |
| 線の色・太さ・線端・角・破線 | ln（cap・round/bevel/miter・custDash） | 図形のまま |
| 矢印（5種・小中大） | ln の tailEnd／headEnd（triangle・stealth・arrow・oval・diamond × sm・med・lg） | 図形のまま |
| 放射グラデ・中間色 | gradFill path="circle"（pos 0＝中心）・gs 3つ | 図形のまま |
| 放射グラデの中心・広がり（v2） | fillToRect l=cx・t=cy・r=1−cx・b=1−cy（1/1000%）で中心、gs の pos を広がり%で縮め伸びして近づける | 図形のまま |
| 影・光彩・ぼかし輪郭 | effectLst の outerShdw・glow・softEdge | 図形のまま |
| 穴あき（evenodd） | 1つの path に全サブパス。巻き方向を外形と穴で逆に揃える＝塗りの規則に依らず同じ見た目 | 図形のまま |
| 重なるサブパス（nonzero） | 400個までは重なりを合体して1つの形に。それより多い網点はサブパスごとの図形をグループにする（1つのcustGeomに並べるとLibreOfficeで重なりが白く抜けた） | 図形のまま |
| 幅ツール・線端効果 | 線を塗りの形に展開した図形 | 形に焼いて図形 |
| うねり（波線・ギザギザ） | 展開したアンカーで図形 | 形に焼いて図形 |
| クリッピングマスク | 塗りはマスクと交差、線は線の形に展開してから交差 | 形に焼いて図形 |
| 文字（横・縦） | 文字枠（フォント名・pt・色・太字・字間・行間） | 文字枠 |
| パス上文字 | 文字の形 | 形に焼いて図形 |
| 画像（配置した） | p:pic（blipFill＋ppt/mediaに埋め込み）。切り抜きは図形の形の custGeom・回転rot・反転flipV・不透明度alphaModFix | 画像 |
| 寸法注釈・下絵画像・非表示レイヤー | 出さない | 出ないもの |
| アニメのコマ | 1コマ＝1スライド | 図形のまま |

・大きさ: 1px＝9525EMU。PowerPointのスライドの上限（56インチ）を超えるアートボードは全体を縮める
・文字の位置: ベースラインからフォントのアセンダ分を上げた所を文字枠の上端にする。見本では数pxずれた
・矢じり: 画面の大きさをPowerPointの小中大（線の太さの2・3・5倍）に合わせた。以前の絵の矢じりは一回り小さく見える
・影・光彩・ぼかし輪郭・矢じり・放射グラデ・クリッピングマスクは、SlideKitの「スライドへ戻す」経由でも図形のまま入る（2026-10-14。SlideKit SPEC.md 8.6.1。マスクは「スライドへ戻す」のときに切り抜いた形にする）
・テーマの色: スライドの色トークン（ink・title・navy・card・accent など）を入れてある

## 5. KiroがPPTX向けのイラストを描くときの約束

Kiroが書くSVGは、BezierKitで開いて人が直せて、PPTX確認で「出ないもの」0件になる形で書く。

・使う要素: path・rect・circle・ellipse・line・polyline・polygon・g（transform可）
・塗り: 単色か linearGradient（objectBoundingBox）。不透明度は fill-opacity／opacity
・線: stroke・stroke-width・stroke-linecap・stroke-linejoin・stroke-dasharray
・使わない要素: filter・mask・clipPath・pattern・image・use・foreignObject・text（文字はSlideKitの `.tb` で重ねる）
・色はスライドの色トークン（`.kiro/steering/slide-contract-detail.md`）から選ぶ
・描いたら BezierKit で開いて「PPTX確認」を通し、書き出したPPTXを LibreOffice で画像にして目で見る
・2026-10-14 BK-P13 で手順を Skill `.kiro/skills/pptx-illust/SKILL.md` にした。検査は `python3 cdp-check.py illust <絵>.svg`（`ILLUST_OK` まで直す）。見本は `examples/warehouse.svg`
・ルートに `data-bezierkit-artboard="1"` を付けると viewBox がそのままアートボードになる。`<g data-layer="名前">` がレイヤー名になる。グラデ（直線・放射・中間色）と fill-opacity も読む

## 6. コード整理の方針

`index.html` は約4,000行・330KB。1ファイルのまま、次の順で整える。

1. 重複と不具合を消す: 同じ名前の関数が2つあった（`reverseBlend`）。幅ツールを使った線の塗り側に不透明度が付いていなかった
2. 共通の道具を1か所に置く: 状態表示（`setStatus`）、ファイル保存（`downloadBlob`）。新しく書くコードから使い、古い箇所は触るついでに置き換える
3. 「見た目を図形に確定する」処理を1か所にする（`resolvePrimitives`）。PPTX書き出しとPPTX確認が使う。画面の描画（`drawPath`）も順次ここへ寄せる
4. 新しい機能は `// ==== 名前 ====` の区切りの中に置く。区切りの中の関数は先頭に用途を1行書く

## 7. 検証

・`python3 cdp-check.py` が全項目緑（PPTXの項目を追加）
・書き出したPPTXを python-pptx で読み、図形数・グループ・文字枠を数える
・LibreOffice で PPTX を PNG にし、BezierKit の PNG 書き出しと見比べる
・PowerPoint 実機で開き、修復のダイアログが出ないことを見る

## 8. 進み具合（2026-10-14）

| ID | 状態 | メモ |
|---|---|---|
| BK-P1 PPTX書き出し | 済 | ファイルメニュー「PPTX書き出し」「選択をPPTX書き出し」、パネル「PowerPoint」。ブラウザの中でZIPまで組む |
| BK-P2 PPTX確認 | 済 | パネル「PPTX確認」。4種の数と焼いた理由（幅ツール・うねり・マスクなど）を出し、行クリックで選ぶ |
| BK-P3 文字枠 | 済 | 「文字は文字枠で出す」で切り替え |
| BK-P4 スライドの大きさ | 済 | ファイルメニュー「スライドの大きさ 16:9／4:3」 |
| BK-P14 AI／PDFを開く | 済 | 9章。ファイル＞開く・ドロップ |
| BK-P5 影・光彩・ぼかし輪郭 | 済 | アピアランス欄。PPTXは outerShdw／glow／softEdge（PowerPointの「図形の効果」で直せる） |
| BK-P6 放射・3色グラデ | 済 | 塗り「放射グラデ」と「中間色」。AI／PDFの多色グラデは8色まで読む |
| BK-P7 矢印の形と大きさ | 済 | 三角・鋭角・開いた矢・丸・菱形 × 小中大（線の太さの2・3・5倍＝PowerPointと同じ） |
| BK-P15 PDF書き出し | 済 | 10章。ファイルメニュー「PDF書き出し」「選択をPDF書き出し」 |
| BK-P8 複数アートボード | 済 | パネル「アートボード」（追加・名前・削除・全体）。1枚＝PPTXの1スライド・PDFの1ページ。複数ページのAI／PDFは「0」で全ページを並べて開く |
| BK-P9 グローバルカラー | 済 | 12章。パネル「グローバルカラー」 |
| BK-P10 シンボル | 済 | 13章。パネル「シンボル」 |
| BK-P11 ライブ繰り返し | 済 | 14章。パネル「繰り返し（ライブ）」 |
| BK-P12 ナイフ・消しゴム | 済 | 15章。ツール K・X |
| BK-P13 Kiroの描画手順 | 済 | Skill `pptx-illust`・`cdp-check.py illust`・見本 `examples/warehouse.svg`（5章） |
| BK-P16 描画モード | 未 | PPTXに無いので優先は低い。必要になったら |

確かめたこと:
・見本（SPEC 4章の表を一通り含む13図形）と、トレースした神奈川沖浪裏（1,346図形）をPPTXにし、LibreOfficeの描画とBezierKitの描画を並べて見た。見た目は一致
・PowerPoint（Mac）で2本とも開き、AppleScriptで図形の名前（レイヤー名のグループ）まで読めた。修復のダイアログで止まらなかった
・`python3 cdp-check.py` に pptx-check／pptx-xml／pptx-open／pptx-textoff を追加し、全項目緑
・見比べは `python3 cdp-check.py pptx 入力.svg 出力.pptx`（`.bk.png` と `.lo.png` が並んで出る）

## 9. AI／PDFを開くときの約束（BK-P14・2026-10-14 済）

ファイルの先頭で振り分ける: `%PDF`＝PDF互換のAIとPDF、`%!PS` と DOS EPS の印＝古いAI・EPS（保存し直しを案内する）、それ以外＝SVG。

| PDFの中身 | BezierKitでの形 |
|---|---|
| パス（m・l・c・v・y・re・h） | アンカーとハンドル。座標はページの左上原点・1pt＝1px |
| 塗り・線・線幅・線端・角・破線・不透明度（ca／CA・透明グループ） | 同じ名前の属性 |
| f*（evenodd）と f（nonzero） | fillRule |
| 開いた線を塗って線も引くもの | 塗りの図形と線の図形に分ける（PDFは塗りだけ閉じる） |
| 切り抜き（W n） | クリッピングマスク。図形を包む長方形の切り抜きは外す |
| 直線グラデ（sh・パターン塗り） | 2色の直線グラデ。放射は直線で近似 |
| AIのレイヤー（OCG） | レイヤー（名前もそのまま） |
| 文字 | 1行ずつ BezierKit の文字（Noto Sans・太字は B）。位置と大きさは元のまま |
| 画像・パターン・描画モード・ソフトマスク | 入れない。件数をステータスに出す |

pdf.js（4.10.38）を jsDelivr から読み、`isEvalSupported:false` で開く。100MBまで。
確かめたこと: 手書きのPDF見本（レイヤー2・穴あき・破線・グラデ・切り抜き・不透明度・文字）、Adobe StockのAI（1,076図形・切り抜き72）、別の手元のAI（1,188図形）。AI→BezierKit→PPTX→LibreOfficeの描画が、macOSで元のAIを描いたものとそろった。

確認の入口: `python3 cdp-check.py verify <AI・PDF・SVG・fixture> [--ppt] [--crop=x,y,w;…]`。見比べ画像は `BezierKit/_check/<名前>/compare.png`。

## 10. PDFで書き出すときの約束（BK-P15・2026-10-14 済）

ライブラリを使わずにブラウザの中でPDF 1.6を組む。1pt＝1px（AI／PDFを開くときと同じ）。

| BezierKitの持ち物 | PDFでの形 |
|---|---|
| パス・塗り・線・線端・角・破線 | m・l・c・h と f／f*／S／B／B*・J・j・d |
| 不透明度 | ExtGState の ca・CA |
| 直線グラデ・放射グラデ・中間色 | シェーディングのパターン（ShadingType 2・3、3色は FunctionType 3）。外接枠を単位正方形にする行列で画面と同じ向き・広がり |
| 放射グラデの中心・広がり（v2） | ShadingType 3 の Coords [cx cy 0 cx cy r]（r＝0.7071×広がり%） |
| クリッピングマスク | クリップ（W n／W* n）。形には焼かない |
| レイヤー | PDFのレイヤー（OCG・名前はUTF-16） |
| 矢印 | 矢じりを形にして描く（PDFに線の端の印が無いため） |
| 幅ツール・線端効果・うねり・長さ0の線 | PPTXと同じく形に展開 |
| 文字 | 形（フォントは埋め込まない） |
| 影・光彩・ぼかし輪郭 | 入れない（件数をステータスに出す） |
| アニメのコマ | 1コマ＝1ページ |

確かめたこと: 見本を書き出し、macOSの描画で画面とそろうのを見た（効果のある3図形は効果なし）。書き出したPDFをBezierKitで開き直し、レイヤー名・直線と放射のグラデ・破線・不透明度・切り抜き・矢じりが戻ることを `cdp-check.py`（pdf-export）で見ている。
Illustrator 2026で開いた（2026-10-14 利用者確認）: 見本の絵・物流アイコン（AI→BezierKit→PDF）とも、エラーなく開いて見た目が画面とそろった。色のくすみはIllustratorでは出なかった（macOSのプレビュー側の描き方）。
未確認: Affinityで開くこと。Illustratorのレイヤーパネルの名前。

## 11. 複数アートボードの約束（BK-P8・2026-10-14 済）

・同じ作業面に長方形を並べる（Illustratorと同じ）。1枚目は常に左上 (0,0) で、ファイル＞アートボードの大きさは選んでいる1枚に効く
・図形は外接枠の中心が入っている1枚に属する。どれにも入らなければ重なりが一番大きい1枚。どこにも重ならない図形は書き出さず、PPTX確認の「出ないもの（アートボードの外）」に数える
・PPTX: スライドの大きさは1つなので1枚目に合わせる。大きさの違う枚は縮めて左上に置く
・PDF: ページごとにアートボードの大きさ
・SVG保存: 全部のアートボードを包む範囲（白地は各アートボード）
・AI／PDFを開く: 複数ページなら番号を聞く。「0」で全ページを横に並べたアートボードにする（ページ名は「1ページ」…）
・アニメのコマがあるときは、従来どおり1コマ＝1枚（アートボードは使わない）

## 12. グローバルカラーの約束（BK-P9・2026-10-14 済）

・色に名前を付けて持つ（`state.swatches`）。図形は塗り・線ごとに `fillSw`／`strokeSw` でつながる
・図形の塗り・線には実際の色もそのまま持つ。描画・PDF・SVGは今までどおり実際の色を使う
・つながりは「図形の色とグローバルカラーの色が同じ間だけ」。手で色を変える・再配色・スポイト・グラデにする、のどれでも外れる（render のたびに確かめる）
・作る: 選択した図形の塗り（線）の色で作り、同じ色の選択図形をつなぐ。付ける: 行の「塗り」「線」で選択図形をその色にしてつなぐ
・色を変える: つないだ図形が全部変わる。続いた変更はUndo 1回
・消す: つながりだけ外れ、図形の色はそのまま
・PPTX: 先頭6色がテーマのアクセント1〜6になり、つないだ図形は `schemeClr`（テーマの色）で書く。PowerPointの配色を変えると一緒に変わる。7色目からは普通の色で書く
確かめたこと: 回帰 swatches（2個つなぐ→色替えで2個とも変わる→手で変えた1個は外れる→テーマ・schemeClr→Undo）。見本の赤い輪をテーマの色にしてもLibreOfficeで赤のまま描かれた

## 13. シンボルの約束（BK-P10・2026-10-14 済）

・選んだ図形を「シンボルにする」と、元の絵（`state.symbols[].paths`・左上が原点）ができ、選んだ図形が1つ目の絵になる。「置く」で同じ絵を増やす
・置いた絵は普通の図形（1つのグループ）として持ち、図形に `symId`／`symInst`／`symIdx` を付ける。描画・PPTX・PDF・SVGは今までどおり
・置いた絵は動かす・回す・拡縮・反転してよい。どこにどう置かれているかは、元の絵と点を突き合わせて最小二乗で求める（ずれ0.5px以内）
・形や色を直すとき: 絵を1つ選んで「編集」→直す→「編集を終える」。ほかの絵は、それぞれの置き方のまま新しい形になる。線の太さは拡大率に合わせる
・手で形を崩した絵（点の数が変わったなど）は、「編集を終える」ときにリンクを外して普通の図形に戻す
・複製・コピー＆ペーストした絵は、新しい置いた絵として数える
・「リンク解除」＝選んだ絵を普通の図形に。「×」＝シンボルを消す（置いた絵は残る）
・PPTX: 置いた絵ごとのグループで、グループ名がシンボル名になる
確かめたこと: 回帰 symbols（3つ置いて回転・反転＋2倍→1つ目の編集が残り2つに同じ置き方で反映・線の太さ2倍→複製で4つ目→崩した1つは外れる→PPTXのグループ名）。画面は `python3 cdp-check.py shot symbols`

## 14. 繰り返し（ライブ）の約束（BK-P11・2026-10-14 済）

・選んだ図形を元にして並べる。種類＝放射（個数・半径。回す中心は元の中心から半径ぶん下）／グリッド（横・縦の数・すき間）／ミラー（縦軸か横軸・すき間。軸は元の右端か下端）
・元には `rptSrc`、コピーには `rptOf` を付ける。元の中身と数値の署名（`state.repeats[].sig`）が変わったときだけ、描画の前にコピーを作り直す＝元を動かす・色を変える・頂点を直す、のどれでも追従する
・コピーはロックしておく（触れない・全選択に入らない）。PPTX・PDF・SVGには普通の図形として入る
・元を選ぶと、パネルにその繰り返しの数値が出て、数値を変えると並びが変わる（続いた変更はUndo 1回）
・「確定」＝コピーを普通の図形にする（もう追従しない）。「外す」＝コピーを消して元だけにする
・元を複製・ペーストした図形は繰り返しに入らない
確かめたこと: 回帰 repeats（放射8→色と位置の追従→12個→Undo→外す→グリッド→複製は入らない→PPTX→確定→ミラー）。画面は `python3 cdp-check.py shot repeats`（花びら12枚・タイル4×3・ミラー）

## 15. ナイフ・消しゴムの約束（BK-P12・2026-10-14 済）

・ナイフ (K): 閉じた図形の上をなぞって横切ると、その線で切り分ける。Altを押しながら＝直線。なぞった線を両端の向きへ延ばし、片側を大きく囲んだ領域との intersect／subtract で分ける＝隙間なく2つになる
・消しゴム (X): なぞった所を、パネル「パス」の消しゴム幅で閉じた図形から消す
・対象: 選択があれば選択のうち、無ければ表示中・ロックなし・今のコマの閉じた図形。線（開いたパス）と文字は対象外（文字は先にアウトライン化）
・結果は島（外形＋その穴）ごとに別の図形にし、塗り・線・効果は元のまま。端まで横切っていない線では切らない。全部消えた図形は消す
・切った図形はシンボル・繰り返しの元ではなくなる
確かめたこと: 回帰 knife／eraser（円→2つ・面積そのまま／外れた線は切らない／ドーナツ→穴なし2つ／正方形に幅20の溝→2つで面積が幅ぶん減る／Undo／端をかすると1つのまま欠ける）。画面は `python3 cdp-check.py shot knife`

## 16. 外から持ち込むSVGの切り抜き・マスク（2026-10-14 済）

BezierKitで開くと、切り抜きとマスクをクリッピングマスクとして受け取る。「スライドへ戻す」とPPTX書き出しでは切り抜いた形になるので、Illustratorなどの書き出しも PowerPoint で図形のまま直せる。

| SVGの中身 | BezierKitでの形 |
|---|---|
| clip-path（形は何でもよい・`clipPathUnits` は両方） | クリッピングマスク。同じ切り抜きを使う図形は1つのマスクを共有し、1つのグループになる |
| 入れ子の切り抜き（グループと図形の両方） | 重なった所（交わり）を1つのマスクにする |
| 白一色の形のマスク | その形で切り抜くクリッピングマスク |
| 灰色一色の形のマスク | 切り抜き＋その濃さの不透明度 |
| グラデのマスク（だんだん消える） | 持てない。マスクの平均の濃さの半透明にして、ステータスに出す |

確かめたこと: 見本 `examples/clip-mask-test.svg`（円・三角・楕円・灰色・帯×星・グラデ）を `python3 cdp-check.py verify` で、元のSVG（Chrome）・BezierKit・PPTX・PDFの4段を並べて見た。グラデのマスク以外はそろった。回帰 clip-import

## 17. 実操作レビュー（2026-11-02）からの改善（v2）

2026-11-02 の実操作レビュー（`bezierkit-review-20261102/`）で出た改善点を波ごとに直す。波1＝期待する動きがはっきりしている5件＋ラベル。

| 項目 | 何が変わったか | 回帰テスト名 |
|---|---|---|
| #1 パス演算の結果の見た目 | 型抜き＝最背面、合体・交差・中マド＝最前面の見た目をまるごと受け継ぐ（塗り・線・太さ・不透明度・グラデ（深いコピー）・破線・線端・角・うねり・影・光彩・ぼかし輪郭・グローバルカラー）。形に結びつく値・印・矢印は受け継がない。`inheritAppearance` 新設 | boolean-appearance |
| #2 パス演算を3つ以上でも | 2つ以上で動く（合体＝全部／型抜き＝最背面から全部引く／交差＝全部重なる所／中マド＝順にexclude）。`booleanOp` と `canBoolean`（count>=2）を書き換え。ボタンの title も更新。終わったらステータスに個数 | boolean-multi |
| #6 文字ツールで既存の文字を押したら打ち直し | 文字ツールで表示中・ロックなし・今のコマの文字の外接枠を押すと打ち直し（選択ツールのダブルクリックと同じ `openTextInput`）。空いた所は新規。`textHitForEdit` 新設。ヒント文更新 | text-click-edit |
| #7（前半）下絵を今のアートボードに合わせて置く | `underlayFrame` を固定1100×700／1200×800中心から、今のアートボードの92%・その中心へ（拡大しない）。トレース・網点も同じ位置で読む | underlay-artboard |
| #13 入力欄で Enter したら絵の操作に戻る | パネル等の数値・文字欄で Enter（Shiftなし）を押したら値の確定はそのままにフォーカスを外す。Esc も外す。除外＝文字textarea・寸法欄（#dimLen・#dimAng・#dimValueInput）。ライブ欄は確定＋blur | input-enter-blur |
| #15 回転コピーの数のラベル | ラベル「個数」→「複製」、title を「元の図形を含まない複製の数（12本にするなら11）」。ステータスに「5個複製した（元と合わせて6個…）」 | rotate-copy-label |
| #4 何も選ばずに決めた見た目を次に描く図形に付ける | `newPath` が `currentDrawStyle`（塗り・線・太さ・不透明度・線端・角・破線・矢印=開いた線だけ。効果は付けない）を付ける。何も選んでいないときは効果の欄（うねり・始端/終端・影・光彩・ぼかし輪郭とその16進欄）を無効にし title で説明。見た目の欄を変えるとステータスに「次に描く図形の見た目にした」。トレース・網点・パス演算・貼り付け・複製・ブレンド・繰り返し・シンボルは `newPath` を通らないので今のまま | draw-style |
| #12 効果の色に16進の欄 | 中間色・影・光彩の色に `#fillHex` と同じ形の16進欄（#gradMidHex・#shadowHex・#glowHex）を並べ双方向に同期。change（Enter/欄を離れる）で適用、不正値は入らない。右端は線の16進欄とそろう | effect-hex |
| #9 うねりに「不規則」 | `#zigKind` に「不規則」（value=rough）。`zigParts` にラフの枝＝波長を平均にばらつかせて点を置き法線方向に大きさを上限でばらばらにずらし直線でつなぐ。乱数は図形ごとに固定（`zig.seed`、無ければ id から `zigSeedFor`）＝描き直し・保存open・書き出しで同じ形。開いた線の両端は元の位置。展開は既存の `zigParts`/`fxParts` の流れ（幅ツール・破線・アウトライン化・PPTX/PDF 展開がそのまま効く） | zig-rough |
| 不透明度0%が0のまま（v1からある） | 欄の読みを `opacityInputVal`（空欄だけ100%・0は0%）に統一（`+value||100` が 0 を 100 にしていた）。描画・SVG・PPTX(alpha)・PDF(ca/CA)・保存open・アイコン往復も `!=null` で判定 | opacity-zero |
| #4の続き 矢印が閉じた図形で消える | `syncArrowControls`：選択が閉じた図形・文字のときは矢印3欄（#arrowSel・#arrowType・#arrowSize）を書き換えず押せない見た目にし title を「開いた線だけに付く」。開いた線なら今まで通りその値。何も選んでいない間は有効のまま（次に描く線の設定を保持） | arrow-closed |
| #3 放射グラデの中心・広がり | グラデに `cx`・`cy`（0〜1・既定0.5）と `spread`（%・既定100＝r0.7071）。パネルの放射の行に中X・中Y・広の欄（`gradRadialRow`・`gradRadialPanelVals`）。1つ選ぶとキャンバスに中心の印（`drawGradCenter`）→ドラッグで動く（`beginGradCenter`/`moveGradCenter`・Undo1回）。SVGは cx/cy/r/fx/fy、PPTXは fillToRect＋pos、PDFは Coords、汎用SVG読み込みは cx/cy/r（fx/fyが中心）。既定0.5/100%は書き出しが今までと同じ | radial-center / radial-center-drag |
| #14 位置・サイズの単位 | px／pt／mm／cm（`geomUnit`・既定px・localStorage記憶）。X/Y/W/Hをその単位で表示・入力（`geomToUnit`/`geomFromUnit`・1px＝1pt・mm＝px×25.4÷72・px/ptは小数1桁 mm/cmは2桁） | units |
| #7（後半）下絵を動かす・大きさを変える | 選択ツールで下絵をドラッグ移動（`moveUnderlay`）、トレース欄に「下絵の大きさ」%（`setUnderlayScale`・中心を保って拡縮）と「アートボードに合わせる」。トレースの出力マッピングを固定1200×800から `underlayBounds` に変更＝動かした後の位置・大きさで読み結果が下絵に重なる | underlay-move |
| T1 色数「1（インクと紙）」 | `#traceColors` に「1（インクと紙）」＋色数1のときだけ出る「しきい値」欄（0〜100・既定50）。`inkPaperSplit` が画素を紙（縁の色＝透明があれば透明、無ければ四辺の平均）とインクに分け、紙からの色の距離としきい値で分け目を決める。インクの層1つ（色＝インク画素の平均）・外形と穴（evenodd）。白い字のまわりの桃色のにじみの層が出ない。外周線でも同じ分け方 | trace-ink |
| T2 小さい画像も細かく処理 | 処理サイズを `Math.min(1,精細さ/長辺)`→`Math.min(4,精細さ/長辺)`に。画像が精細さより小さいときは精細さまで拡大（最大4倍・拡大のときだけ imageSmoothingQuality='high'）。335px画像を精細さ720でふちがなめらかに。大きい画像（縮小側）は既定のままで従来と同じ結果 | trace-upscale |
| T3 「アートボードに合わせる」で小さい画像も拡大 | `artboardFitFrame` 新設（`underlayFrame` と違い最大1倍の頭打ちなし）。ボタンで拡大・縮小どちらでもアートボードの92%に収める。読み込み直後の置き方（`underlayFrame`）は今まで通り最大1倍 | trace-fit-ab |
| T4 トレースの角の出し方 | トレース欄に「角」（丸める／標準／角を残す・既定＝標準＝従来）。`fitLoopNodes` に opts（smooth・ang）を足す。丸める＝smooth3・角82°、標準＝smooth2・角62°（従来と同一）、角を残す＝smooth1・角45°（篆刻の画の直線・直角を立てる）。既定は opts 無し＝従来どおり（単純化・icon-from-image.py も不変） | trace-corner |
| S1 球に貼る（波5） | 平らな絵＋円を選んで「変形」の「球に貼る」。最前面の円が球（クリップと同じ決まり）、残りが貼る絵でその外接枠が経度−180〜180・緯度北極〜南極。経度緯度→球面→回転（傾き・回転・地軸）→正射影。表側に見える範囲の多角形と paper.js で交差して表/裏に分け、ふちを点にして球へ移し曲線フィットで図形に。閉じた図形と開いた線の両方。欄＝傾き/回転/地軸/裏側（隠す・薄く出す）/薄さ、数値ライブプレビュー（Enter確定・Esc取消・Undo1回）。円は球の地として残す。`doSphereWrap`・`sphereProject`・`sphereFrontRegions`・`sphereMapClosed`・`sphereMapOpen` 新設 | sphere-wrap |
| R1 球に貼るを貼り直せる（波6） | 貼った結果の円に元の平らな絵・円・設定を持たせる（`sphSrc`・作業データに入る）。貼った結果を選んで欄を変える／「貼り直す」で、いつも元の平らな絵から作り直す＝2回貼りにならない。欄に貼ったときの設定が出る（`syncSphereControls`）。「平らな絵に戻す」（`sphereUnwrap`・Undo 1回）。最前面が円でなければ貼らない（`isCircleish`） | sphere-rewrap |
| R2 北極・南極の継ぎ目 | 極を囲む帯は継ぎ目なしの1枚で貼る（`sphereCapNodes`） | sphere-pole |
| R2b/R2c 継ぎ目と北極の欠け（波10後半） | 裏（と回転180の表）の帯が経度±180°＝平らな絵の左右の端で2つに切れ、半透明の接する縁が縦線に見えていた→左の端に触れる部分を枠の幅ぶんずらして右の部分に面で重ね paper.js で合体し1枚に（`sphereSealSeam`。経度は周期なので−180°より外の値もそのまま正しく写る）。全幅で丸ごと表 or 裏の帯は切れ目のないリング（外周＋内周の穴・evenodd）にする（`sphereRingNodes`）。北極の欠けは `sphereCapNodes`（と新 `sphereRingNodes`）が未定義の `sph.bb.r`／`sph.bb.b` を見ていて一度も発火していなかったのが原因で、`sph.bb.l+w`／`sph.bb.t+h` に直してキャップ／リングが効くようにした | sphere-seam |
| 球の継ぎ目の残り（波10後半の続き・Kiro） | ①左右の端の両方に触れる1枚（表と裏にまたがる北極寄りの帯の表の部分）は、端の縦の辺が球の上で同じ経線に重なり幅0の切れ目になっていた（回転180で表の真ん中に縦線）→ `sphereSeamRing` で端の辺を抜き、上の縁と下の縁の2本をそれぞれ閉じた輪にして穴のある形に（極の縁に沿う線は除く）。②小さい輪は `fitLoopNodes` が2点で閉じるため、`sphereRingNodes`・`sphereCapNodes` が「3点未満は不可」で外れていた（傾き60で一番上の帯に切れ目）→ 2点も受け入れる | sphere-ring-seam |
| R3 貼る範囲の枠 | 塗りも線もない長方形を一緒に選ぶと、その外接枠が経度−180〜180・緯度90〜−90の地図の枠になる（`isSphereFrame`・枠そのものは貼らない） | sphere-frame |
| R4 トレースし直せる | 色ごとの面のトレースのあとも下絵を消さずに隠す（「下絵を表示」`#underlayShow`・`setUnderlayVisible`）。トレースを Undo すると下絵の表示・位置・大きさも戻る（snapshot/restore に下絵の状態） | trace-redo |
| P1 PDFに入らない効果を書き出す前に知らせる（波7） | `exportPdf` でファイル名を聞く前に、書き出す図形（`pptxTargets`）のうち `hasFx`（影・光彩・ぼかし輪郭）を数え、1つ以上なら `askFilename` の第3引数 note でプロンプトの文に「PDFには影・光彩・ぼかし輪郭が入りません（n個の図形）。入れたいときはPNGかPPTXで書き出してください」を前置き。0なら今まで通り。`askFilename(defaultName,ext,note)` に note を追加（既存呼び出しは不変） | pdf-fx-note |
| L1 多角形・星をあとから直せる（波7） | 多角形・星に形の元 `shape`（type・中心cx/cy・外接半径r・回しrot＋多角形sides／星points・ratio0.05〜0.95）を持たせる（`shapeFromNodes`／作り直しは `shapeToNodes`・endShape で付与）。1つ選ぶと `updateControls` が角数/頂点/鋭さの欄に値を出す。欄を変えると `editSelectedShape` が、今の点と shape から作った点を `fitAffine` で合わせた置き方 m を求め、新しい shape から作った点に m をかけて作り直す（中心・大きさ・回し・見た目・id・レイヤー・グループを保つ）。移動・回転・拡縮・反転はアフィンなので m に吸収＝直せるまま。手で点を動かす・点を足す・パス演算などでアフィンに合わなくなったら（m=null）形の元を外し「形を手で直したので、角数はもう変えられない」。保存→開き直しは `sanitizeShape`（型と範囲を確認・角数3〜24・頂点3〜24・鋭さ5〜95）を restore で通す。type で分けてあり L2 で rect を足せる | shape-edit |
| L2 角R（角丸の四角）を大きさを変えても保つ（波7） | 矩形ツールで描いた四角に形の元 `shape`（type`rect`・中心cx/cy・幅w・高さh・角RcornerR・回しrot）を持たせる（`shapeFromNodes('rect')`＝n0〜n2から中心・w・h・rot、`endShape` で4点のとき付与／点は `rectShapeNodes`＝角丸四角を作る、角R>0なら `roundNodesFrom` で8点）。`#cornerR` の欄は、形の元を持つ四角を1つ選んでいるとき（`rectShapeSel`）はその四角の角Rを `updateControls` が表示し `editRectCornerR` で変更（半径は短い辺の半分までにクランプ、`cornerApply`・ライブ input 両方が分岐）。ほかの図形は今までどおりの `setCornerR`（cornerSrc）。拡縮への追従は render の頭 `syncShapeRects`（`syncRepeats` と同じ所・四角が無ければ即return）で、形の元から作った点と今の点を `fitAffine` で合わせ、拡縮があれば w×sx・h×|sy|・同じ角R（クランプ）で作り直し shape を更新、移動・回転だけなら何もしない。シアー（`|a·c+b·d|/sx²>0.01`）や点のアフィン不一致（m=null）・点数ちがいは形の元を外す（手崩れ）。保存→開き直しは `sanitizeShape`（rect＝w・h正の有限・cornerR 0以上で短辺の半分まで）を restore で通す | rect-shape |
| #11 右パネルを案B改に（固定枠＋4タブ） | `#panel` を「上に固定（コマ・レイヤー・『いつも出ている』枠＝X/Y/W/H/単位/比率固定・塗り/線の16進・太さ/不透明）＋タブ」に組み直す。タブ＝`.ptab[data-ptab="draw|arrange|color|file"]`、中身＝`.ppane[data-ppane=...]`、選択は class `on`・隠れは display:none。描く＝塗り・線・効果/パス/図形/文字/寸法入力、配置＝整列/オブジェクト/変形/繰り返し/シンボル、色＝パレット/グローバルカラー/再配色/同じ属性で選択、ファイル＝アートボード/PowerPoint/画像トレース/網点。`setPanelTab`（localStorage `bkPanelTab`・既定draw・不明名はdraw）と `revealPanel(el)`（el の入るタブへ切替＋scrollIntoView）を新設。下絵を置いたら（`loadTraceImage`）ファイルタブへ。`#panel` は flex 縦並びで本体はスクロールせず `.ppanes` だけ `overflow-y:auto`（固定枠 flex:none）。固定枠の線 #9fc0dd・右上に「いつも出ている」(var(--blue))。id は1つも変えない・消さない（238個のまま／新しい container は class だけ）。組み直しは `v2/wave8/rebuild_panel.py`（section を h2 で並べ直し CSS/JS も注入） | panel-tabs |
| #11の続き 塗りと線の見分け・色タブの並び（波9） | 線の見本は太い枠だけの四角（中は白・外と内に細い灰色の縁＝白い線でも見える）、塗りの見本は今どおり塗りつぶし（Illustratorのプロパティパネルと同じ）。塗りなし・線なしのときは見本を白に赤い斜線にし、16進の欄に灰色で「なし」（`syncSwatchLook`・`syncHexInputs` から呼ぶ）。初見レビューで「同じ属性で選択」がスクロールしないと見えなかったので、色タブの2番目（パレットの下）へ。PowerPointの欄のメモから「仕様は SPEC.md 4章」を外した | fill-stroke-look |
| 塗りなし・線なしを外したら前の色（波10） | なしにする前の色を図形に覚えさせ（`prevFill`・`prevGradient`・`prevStroke`）、外したらそれに戻す（グラデも）。なしの図形を選んでも欄の色を黒にしない。新しい色を選んだら覚えていた色は捨てる。読み込むときは `sanitizePrevColors` で型を確かめる（v1から、外すと #000000 の塗りになっていた） | none-restore |

波3（放射グラデの中心・単位・下絵を動かす）を 不透明度0%→#4続き→#3→#14→#7後半 の順に実装し、各項目で構文確認（node --check）。変更前に全回帰（`v2/wave3/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave3/regress-after.log`）が新テスト5件（opacity-zero / arrow-closed / radial-center(+drag) / units / underlay-move）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。放射グラデの中心25%・広がり60%を書き出し、LibreOfficeでPPTXを画像にして光だまりが左上に寄るのを目視（`v2/wave3/radial-offset.lo.png`）、PDFは sips でPNGにして同じく左上を目視（`v2/wave3/radial-offset.pdf.png`）。既定0.5/100%は fillToRect 50000・pos等倍で今までと同じ。パネルは 中X/中Y/広の行・単位の選択・下絵の大きさの行・閉じた図形で無効の矢印欄をスクリーンショットで確認＝他の行と右端・ラベルがそろう（`v2/wave3/{panel-radial-arrow-unit.png,panel-unit.png,panel-underlay-size.png}`）。中心の印はドラッグで動き Undo で戻る。パッチ: `bezierkit-review-20261102/v2/wave3/{index.patch,cdp-check.patch}`

確かめたこと: 変更前に全回帰（`regress-before.log`）が全緑であることを記録→波1の6項目を1つずつ実装・構文確認→全回帰（`regress-after.log`）が新テスト6件を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。パネルの「複製」行の並びをスクリーンショットで確認（他の行とそろう）。パッチ: `bezierkit-review-20261102/v2/wave1/{index.patch,cdp-check.patch}`

波2（新しい図形の見た目・効果の色の16進欄・不規則なうねり）を #4→#12→#9 の順に実装し、各項目で構文確認（node --check）。変更前に全回帰（`v2/wave2/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave2/regress-after.log`）が新テスト3件（draw-style / effect-hex / zig-rough）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。パネルをスクリーンショットで確認＝16進欄3つの右端が線の16進欄とそろう（右端1421px・幅63px）・何も選んでいないとき効果の欄が無効（`v2/wave2/{01-panel-effects-disabled.png,02-panel-effect-hex.png}`）。パッチ: `bezierkit-review-20261102/v2/wave2/{index.patch,cdp-check.patch}`

波4（実物の印影をトレースできるように）を T3→T1→T2→T4 の順に実装し、各項目で構文確認（node --check）。変更前に全回帰（`v2/wave4/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave4/regress-after.log`）が新テスト4件（trace-ink / trace-upscale / trace-fit-ab / trace-corner）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。既定（色数8・角＝標準・精細さ標準）のトレース結果は変えていない（trace-fit・trace-res・outline-trace・layer-merge が不変で緑）。参考画像 `King_of_Na_gold_seal_imprint_intaglio.png`（335×325）を 色数1（インクと紙）・しきい値50・精細さ720・角＝角を残す・アートボードに合わせる（800の92%＝736px）でトレースし、白文（赤の層1つ・白い字は穴）になることを確認（桃色のにじみの層は出ない）。成果物 `v2/seal-trace/seal-traced.{svg,png,pptx,pdf}`、見比べ `v2/wave4/{compare-full.png,compare-zoom-wang-guo.png}`（元画像と王・國の画）、PPTX/PDF を画像にして崩れないのを目視（`v2/wave4/{seal-traced-pptx.png,seal-traced-pdf.png}`）。パネルは色数1で「しきい値」行が出て、精細さ/角の行の右端がそろうのをスクリーンショットで確認（`v2/wave4/panel-trace.png`）。パッチ: `bezierkit-review-20261102/v2/wave4/{index.patch,cdp-check.patch}`

波5（球に貼る）を実装し、構文確認（node --check）。変更前に全回帰（`v2/wave5/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave5/regress-after.log`）が新テスト1件（sphere-wrap＝①全点が球の半径内②傾き0は水平の帯③傾き20で中央が下へふくらむ④裏側を薄く出すと図形が増え不透明度25%⑤Undo1回で元へ⑥同設定2回で同じ形）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。球面の計算（経度・緯度→Ry(回転)·Rx(傾き)·Rz(地軸)→正射影、表裏の境は g=sinφ·sint+cosφ·cost·cos(λ+s)>0 の1°刻み）を傾き0・20・60／回転0・90で数値確認（全点が半径内・傾き0は経度の帯）。成果物＝太さと間がばらばらの横縞10本＋円を「球に貼る」で作ったBBC風の1枚（背景＝中心をずらした赤の放射グラデ、球の地＝円に放射グラデ＋光彩のハロー、縞＝明るい赤〜白、裏側＝薄さ22%で透け、光の輪＝細い楕円2本＋光彩、中央に光の玉）。`v2/sphere/bbc-globe.{svg,png}`、PPTXにも書き出してLibreOfficeで画像に（`bbc-globe.pptx`＝図形30・欠落0、`bbc-globe.lo.png`）＝縞が球の丸みに沿って曲がりふちで切れ裏側が薄く透けるのを目視。パッチ: `bezierkit-review-20261102/v2/wave5/{index.patch,cdp-check.patch}`

波6（波4・波5の確認で見つけた点）を R2→R1→R3→R4 の順に実装し、構文確認（node --check）。変更前に全回帰（`v2/wave6/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave6/regress-after.log`）が新テスト4件（sphere-rewrap / sphere-frame / sphere-pole / trace-redo）を含めて全緑。Kiro が本物のマウス・キー操作で確かめた: 枠＋太さと間がばらばらの横縞10本＋円→球に貼る→傾き15・25・35と貼り直しても絵は壊れない（図形31→28→27）／保存→開き直し→「平らな絵に戻す」で13図形・Undoで28図形／印影を色数1でトレース→Undo→しきい値を変えて、下絵を開き直さずに2回目ができる。成果物 `v2/sphere/bbc-globe-v2.svg`・`.png`・`.pptx`（PPTX は図形28・画像0、LibreOffice の描画 `v2/sphere/lo/bbc-globe-v2.png`）。残り: 「裏側＝薄く出す」の裏の帯に、経度の端の細い縦線が薄く見える（368%で目に見える。1倍ではほぼ見えない）

波7前半（#10 PDFの効果の知らせ・#5 描いた後で直せる範囲）を P1→L1 の順に実装し、各項目で構文確認（node --check）。変更前に全回帰（`v2/wave7/regress-before.log`）が全緑であることを記録→実装→全回帰（`v2/wave7/regress-after-a.log`）が新テスト2件（pdf-fx-note / shape-edit）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。shape は原寸のひな形で、移動・回転・拡縮しても shape は変えず、作り直すときだけ fitAffine で今の点から置き方を復元する（シンボルの `instanceMatrix`／`fitAffine` と同じ考え）。L2（角R＝rect の shape）は次の担当。shape は type で分けてあるので rect を足せる。パッチ: `bezierkit-review-20261102/v2/wave7/{index-a.patch,cdp-check-a.patch}`

波7後半（L2 角R＝角丸の四角を大きさを変えても同じ半径に保つ）を実装し、構文確認（node --check）。「変える前」の全回帰は前半の `v2/wave7/regress-after-a.log`（全緑）をそのまま使い流し直していない→実装→全回帰（`v2/wave7/regress-after-b.log`）が新テスト1件（rect-shape＝欄に28が出る／W520比率固定・W520比率なし・H300・30°回転後の一様拡大のどれでも4角の半径28±0.5／欄28→40／手で点を動かすと形の元が外れる／保存→開き直しで残り直せる）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。L1 と同じ fitAffine ガードに乗せ、個々の編集操作へのフックは足さない（拡縮の追従だけ render 頭の `syncShapeRects` で判定）。角Rは `#cornerR` の欄を、形の元を持つ四角のときだけ `editRectCornerR` に分岐（ほかは従来の cornerSrc 処理）。パッチ: `bezierkit-review-20261102/v2/wave7/{index-b.patch,cdp-check-b.patch}`

波8（右パネル 案B改＝#11）を実装し、構文確認（node --check）。「変える前」の全回帰は波7後半の `v2/wave7/regress-after-b.log`（全緑）をそのまま使い流し直していない→実装→全回帰（`v2/wave8/regress-after.log`）が新テスト1件（panel-tabs＝4タブ `.ptab`/`.ppane` が draw/arrange/color/file・「いつも出ている」枠の欄は `.ppane` の外でどのタブでも見える・描くに切替で配置paneが display:none・`revealPanel(#group)` で配置タブが開き localStorage に残る・不明名は draw に落ちる）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。id は組み直しの前後で 238個のまま同じ集合（`v2/wave8/{panel-ids-before,panel-ids-after}.txt`・missing/added ともなし）。SHOT_SETUPS（swatches/symbols/repeats/abpanel の abList・symList・rptKind）と test42 の #dimLen は、隠れたタブの要素なので `scrollIntoView`/`focus` の前に `revealPanel` を通すよう直した（テストの意図は不変）。bkdrive.py（ポート18474）で4タブ×（四角1つ選択・無選択）と、ファイルタブを一番下までスクロールしても固定枠（レイヤー・いつも出ている・タブ）が動かないこと（タブの y=351 のまま pane が584pxスクロール）を 1440×900 と 1440×760 でスクリーンショット確認（`v2/wave8/{01..11}-*.png`）＝モックの案B改と並び・右端・ラベルがそろう。残り（軽微）＝「いつも出ている」枠の線の16進欄が狭く `#183251` が `#18325` と少し切れて見える（値は保持・表示だけ）。組み直し: `v2/wave8/rebuild_panel.py`。パッチ: `bezierkit-review-20261102/v2/wave8/{index.patch,cdp-check.patch}`

波9（2026-11-02）: 利用者「塗りの色、線の色がどっちかわかんないね」→案を3つ描いて案1（線の見本を枠だけに）に決定。あわせて初見レビュー（画像だけを見る別の担当）で見つかった「同じ属性で選択が見えない」「SPEC.md のメモ」を直した。初見レビューの残り（合体・型抜きを配置の整列の下へ移す案と、タブの名前）は今回は見送り、今のまま。全回帰は fill-stroke-look を含めて全緑（`v2/wave9/regress-after.log`）

波10後半（2026-11-02）: 「球に貼る」で「裏側＝薄く出す」の裏の帯の真ん中（回転0なら球の裏の経度±180°）に細い縦線、北極のふちに小さな欠けが見えていたのを直した。原因は2つ: ①横いっぱいの帯を `pp.subtract(frontRegion)`／`intersect` で表裏に分けると、横いっぱいの帯が平らな絵の左右の端（経度±180°）で2つの図形に切れ、半透明の2つが接する縁がにじんで縦線に見えていた（回転180では表に出る）。→`sphereSealSeam` で、左の端に触れる部分を枠の幅ぶんずらして右の部分に面で重ね（標本化の刻み約2pxより広い重なり）paper.js で合体し、帯1本＝1図形にした。全幅で丸ごと表 or 裏の帯は `sphereRingNodes` で外周＋内周の穴（evenodd）のリングにして、そもそも左右の端の半径状の切れ目を作らない。②北極の欠けは、極を囲む帯を1枚にする `sphereCapNodes` が未定義の `sph.bb.r`／`sph.bb.b`（`sph.bb` は `{l,t,w,h}` しか持たない）を見ていて一度も発火していなかったのが根本原因。`sph.bb.l+w`／`sph.bb.t+h` に直し、キャップとリングが効くようにした。構文確認（node --check）。「変える前」の全回帰は波10前半の `v2/wave10/regress-after-a.log`（全緑）をそのまま使い流し直していない→実装→全回帰（`v2/wave10/regress-after-b.log`）が新テスト1件（sphere-seam＝裏側＝薄く出す・傾き25で横いっぱいの帯を貼ると回転0でも180でも表1図形・裏1図形＝左右の端で切れない／全点が半径内）を含めて全緑（BEZIERKIT_OK＋ICONS_OK）。bkdrive.py（ポート18474）で横縞＋円＋枠を傾き25/60・回転0/180で貼り、1帯あたりの図形数を数え（回転0は before 表1裏2→after 表1裏1、回転180は before 表2裏1→after 表1裏1）北極を拡大して目視（`wave10/*pole*`）＝北極の欠けは消え、縦線は内側のリングでは消えた。残り（軽微）＝表裏にまたがる1本の帯で、回転180の真正面（経度0）に短い縦線がまだ薄く残る。パッチ: `bezierkit-review-20261102/v2/wave10/{index-b.patch,cdp-check-b.patch}`

波11（#1 グラデの多色・2026-11-02）: 直線/放射グラデに「色ごとの位置と不透明度」を持たせた。データは `gradient.stops=[[位置0〜1,色,不透明度0〜1],…]`（位置順・2〜10個）に揃え、`c1`=先頭色・`c2`=末尾色を同期、`mid` は書かない。古い `c1/mid/c2` は今まで通りの見た目で開く（`gradStops` が三つ組に正規化し、`gradEditStops`/`writeGradStops` で読み書き。開くとき `sanitizeGradient` で型と範囲を確かめる）。UI は Illustrator のグラデーションパネルと同じ「帯」＝「描く」タブの塗り・線・効果に `#gradBar`（市松の上に今のグラデを見せる）＋分岐点ボタン `.gstop`（`#gradStopTrack` 内・選択に `on`）。分岐点を押す＝選ぶ、帯の空いた所を押す＝その位置の今の色でその場に足す（上限10）、左右ドラッグ＝位置、下へ24px引き離す＝消す（3つ以上のとき）、`#gradStopDel`・`#gradReverse`（⇄）。下の欄に色（`#gradStopColor`＋`#gradStopHex`）・位置（`#gradStopPos`%）・不透明（`#gradStopAlpha`%）。「いつも出ている」塗りの見本と16進はグラデのとき選んでいる分岐点の色を出し、変えるとその分岐点が変わる（図形を選び直すと先頭に戻る）。何も選ばず帯を直すと `drawGradStops` に入り `currentDrawStyle` が次に描く図形へ（#4 と同じ）。不透明度は図形の不透明度と掛け合わせる（SVG=`stop-opacity`／PPTX=`a:gs` の alpha＝分岐点×図形／PDF は色だけ・分岐点ごとの不透明度のソフトマスクは未実装）。再配色（`buildRecolorRows`/`selectByColor`/`applyRecolor`＋kmeans減色）は全分岐点の色を拾って並べ替えられる。2色目・中間色の行は帯に置き換えて隠す（`#fill2`・`#gradMid` 等の id は DOM に残す＝既存コードが参照しても落ちない）。構文確認（node --check）。新テストは `wave11_checks` にまとめ `python3 cdp-check.py only wave11` で全緑（WAVE11 A〜J＋UI：50%分岐点→3つ間の色#800080・#00ff00不透明40でSVG stop-opacity .4・位置70%→.7・3→2で消え2からは消えない・反転・4色+不透明50×図形80→PPTX gs4つ alpha .4・保存open・古いc1/mid/c2が3色・何も選ばず4色で次に描く・再配色に全色・追加Undoで2つ）。全回帰は Kiro が後で流す。撮影＝4色・不透明度ありの放射グラデの図形と帯（`v2/wave11/panel-gradbar.png`）。パッチ: `v2/wave11/{index.patch,cdp-check.patch}`

波11の仕上げ（2026-11-02）: PDF にグラデの分岐点ごとの不透明度を /SMask /Luminosity（同じ形の DeviceGray シェーディングを塗る透明グループ・flipの逆でパターンと同位置に合わせ図形の不透明度とも掛ける）で入れた＝不透明度が全部1の図形は SMask を付けない。分岐点の行は 色（見本＋16進）を左半分・位/透を右半分にして7文字が切れないように、直線グラデの角度ラベルを先頭の子に戻して他の行と左端をそろえた。回帰 WAVE11-PDF-smask/nosmask・HEXWIDTH を追加、`only wave11`＋全回帰とも緑。sips で PDF を画像にして40
波12（#2 連結・#3 文字の揃え）の1回目として J1 連結 と X1 文字の揃え を実装し、構文確認（node --check）。X2 エリア内文字は次の回（今回は触っていない）。J1=開いた線を2本以上選んで「連結」（パス欄の `#joinPaths`・右クリックの `#contextJoin`・⌘J）＝残りのチェーンから一番近い端どうしを貪欲につなぐ（端が2px以内なら1点に溶接 `joinNodes`、離れていれば直線で `[...a,...b]`）、1本だけなら閉じる、つないだ両端が2px以内なら閉じる、見た目は最前面の線を `inheritAppearance` で継承、形の元 `shape`・寸法注釈 `dims`・シンボル/繰り返しの印は外す、Undo1回。閉じた図形・文字・異なるコマを含む選択は何もせずステータスで知らせる。X1=文字に `t.align`（start/center/end・未定義は start で今の見た目を変えない）を持たせ、`textCmds` で行（縦書きは列）ごとにオフセット（横書き=左/中央/右、縦書き=上/中央/下、点文字は打った点 `t.x`/`t.y` が基準）。欄は「描く」タブの文字の `#textAlign`（`syncTextAlignLabels` が縦書きのときラベルを上/下に替える）。パス上文字の `pathAlign` とは別物。書き出しは SVG/PNG/PDF は揃えた `cmds` がそのまま出る、PPTX は横書き=`a:pPr` の `algn`（l 省略/ctr/r）・縦書き=`a:bodyPr` の `anchor`（t/ctr/b）で、揃えぶん box を広げる。開くとき `sanitizeText` で型（start/center/end 以外は外して start 扱い）を確かめる。新テストは `wave12_checks` にまとめ `python3 cdp-check.py only wave12` で全緑（WAVE12-J1 7件＝溶接5点・直線連結6点・1本閉じ・最前面継承・shape外れ・閉じた図形拒否・Undo1回／WAVE12-X1 10件＝横中央/右のオフセット=行幅・多行で中心そろう・縦中央/下=列長・PPTX algn ctr/r・anchor ctr・保存open で残る・不正 align は外れる）。selftest 末尾からも `wave12_checks` を呼ぶ。本物のマウス・キー操作（bkdrive.py・ポート18474）で、線2本を描いて選択ツールで囲み⌘J→1本（4点・Undoで2本）、3行の文字を選択ツールで「揃え＝中央」→3行の中心がそろう、を確認（`v2/wave12/{w12-01-j1-joined,w12-02-x1-left,w12-03-x1-center,w12-04-x1-align-row}.png`）。全回帰は Kiro が後で流す。パッチ: `v2/wave12/{index.patch,cdp-check.patch}`

波12（2回目）の X2 エリア内文字を実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テストを含め全緑（BEZIERKIT_OK＋ICONS_OK）。文字ツールで4px以上ドラッグ→枠（`t.area`・`boxW`・`boxH`、`t.x`/`t.y`＝枠の左上）を作って打つ（4px未満は従来の点文字＝#6 の打ち直しを壊さない。down では判定を保留し up で分岐）。`wrapLines(fontObj,t)` が横書きは枠幅で、縦書きは枠高で折り返す（日本語＝1文字ごと＋簡易禁則: 行頭に `、。，．・：；！？）」』】〕ー)]}` を置かず前行へ追い込む／行末に `（「『【〔([{` を残さず次行へ送る、英語＝空白の切れ目・枠より長い語だけ途中で切る、ユーザー改行はそのまま、縦書きは列右→左）。`textCmds` の area 分岐が折り返した行のうち枠に入る分だけを置く（入らない行は非表示＝画面・SVG・PNG・PDF・アウトライン化すべて見えている分）。揃え（`t.align`）は枠の中で効く（左＝枠左・中央＝枠中心・右＝枠右、縦は上/中央/下）。選択ツールの枠のつまみ（`beginBB`→`areabox`／`moveAreaBox`）は文字サイズを変えず `boxW`/`boxH` だけ変えて折り返し直す（Undoはつまみのドラッグ1回で1段。点文字は従来どおり拡縮）。選択中はバウンディングボックスを枠（`t.x,t.y,boxW,boxH`）に合わせて細線表示し、入りきらないとき枠の右下に赤い小さな「＋」（`areaOverflow`・画面だけ・書き出さない）。PPTX は `bodyPr wrap="square"`・`off`/`ext` を枠に、段落はユーザー改行だけ（折り返し改行を入れない＝PowerPoint で折り返し直せる。縦書きは `vert="eaVert"`）、入りきらない文字がある時は PPTX確認の注記に「枠に入りきらない文字（PowerPointでは枠の下にはみ出す）」。保存・開き直しで `area`/`boxW`/`boxH` が残り、`sanitizeText` で型と範囲を確かめる（boxW/boxH が正の有限でなければ area を外す）。新テストを `wave12_checks` に11件追加（枠幅で行が増える・行頭に、。が来ない・英語は単語で折り返す・つまみで狭めると折り返し直し＋サイズ不変・入りきらないとoverflow・中央で各行の中心が枠の中心・縦書きの折り返し・PPTX wrap=square＋段落はユーザー改行だけ・保存open・不正boxWでarea外れ・点文字はareaなし）。本物のマウス・キー操作（bkdrive.py・ポート18474）で、文字ツールで枠をドラッグ→長い日本語を打って折り返し→選択ツールでつまみを左へ動かして狭める→折り返し直し（枠300×230=行14→148幅=行42・文字サイズ80不変）→枠を低くして overflow の赤「＋」を確認（`v2/wave12/{w12b-01-x2-wrapped,w12b-02-x2-narrowed,w12b-03-x2-overflow}.png`）。パッチ: `v2/wave12/{index.patch,cdp-check.patch}`（before-wave12 との差で作り直し）

波13（#4 画像を置いて切り抜く）の1回目として 手順1（データの種類と表示・imageStore・placeImageFile・drawPath の画像・メニュー）と 手順2（外接枠・選択・移動・当たり判定）＋手順3の一部（transformSelection/transformedPath の mat 合成・複製/コピペ・ノード前提機能のガード）を実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テスト place-image を含め全緑（BEZIERKIT_OK＋ICONS_OK）。画像は nodes を持たない別種 `{type:'image',imgId,mat:[a,b,c,d,e,f],w0,h0,opacity,layerId,…}`（text と同じ扱い）で、置き方は配置行列 mat（単位矩形 0..w0×0..h0→画面）に移動・拡縮・回転・反転をすべて左合成（`composeMat`）で吸収する。画素は state.paths に入れず常駐 `imageStore`（imgId→{dataURL,px,py}）に置くので snapshot/Undo の各段に画素が入らない（実測 空=170字・画像1枚=273字＝画像オブジェクトの数十字だけ増え、dataURL は入らない）。入口はファイルメニュー「画像を配置…」（`#placeImage`／`#placeImageFile`→`placeImageFile`）で、長辺4096px超は読み込み時に縮め、長辺がアートボードの60%（小さい画像は拡大しない）で中央に置いて選択する。ドロップ/ペーストは今まで通り下絵（`loadTraceImage`）のままで、ステータスに「絵の一部として置くには『ファイル>画像を配置…』」を案内。表示は `drawPath` の画像分岐で `<image class="drawn" data-id href=dataURL width=w0 height=h0 transform=matrix(mat)>`（+opacity・clip-path・locked の pointer-events。アウトライン表示は4隅の多角形）。外接枠・選択・ヒット判定・移動は `bboxOfPath`/`selectionBBox`/`pathData`（4隅）・`shiftedPath`（mat の e/f を足す）・DOM の `.drawn[data-id]` で効く。回転・反転・拡縮・整列・位置サイズ欄・バウンディングボックスのつまみは `transformSelection`/`transformedPath` の mat 合成を通る。複製・コピー＆ペーストは clone が imgId を参照コピーするので imageStore は1件のまま共有。画像はクリップの中身にはなれるがマスクにはなれない（`makeClipMask` の最前面が画像ならステータスで断る）。パス演算は `canBoolean` が閉じた図形だけなので画像は自動で外れる。restore に `sanitizeImage`（mat が配列6・w0/h0 正の有限・opacity 0〜1 を確認）を追加。SVG/PNG/PDF/PPTX の書き出しと保存→開き直し（imageStore 再構築）は次の回（手順5以降）。新テストは `wave13_checks`、`python3 cdp-check.py only wave13` で単体実行（配置→type:'image'1つ・imageStore1件・Undoで消える／長辺60%・中央／移動 mat+50/+30・比率固定2倍・回転90でbbox入替・反転しても画素保持／複製で imgId 共有・別id・store1件／当たり判定 .drawn[data-id]／JPEG・小画像の非拡大・snapshot に画素が入らない）。本物のマウス・キー操作（bkdrive.py・ポート18474）で漢委奴国王の印影PNGを配置→選択ツールで掴んでドラッグ移動（mat 432.5/237.5→582.5/317.5）→⌘Zで戻るのを確認（`v2/wave13/{01-placed,02-moved,03-undo}.png`）。残り（次の回）＝手順4 ⌘7 切り抜きの画像対応確認・手順5 SVG保存とmetadata#bezierkit-images・手順6 開き直し・手順7 PDF XObject・手順8 PPTX p:pic。気になった点＝画像を選ぶと「塗り・線」の16進欄が前の図形の値のまま残る（画像は塗り/線を持たないので updateControls が触らない。実害なし・表示だけ）。パッチ: `bezierkit-review-20261102/v2/wave13/{index.patch,cdp-check.patch}`

波13（#4 画像を置いて切り抜く）の2回目として 手順4（切り抜き）・手順5（SVG保存と開き直し）・手順6（開き直しの検査）＋画像選択時のパネル・ノード前提機能のガードの漏れ埋めを実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テストを含め全緑（BEZIERKIT_OK＋ICONS_OK）。切り抜き＝画像の上に図形を重ねて⌘7（`makeClipMask`）で画像に `clipBy`。クリップは画像の配置行列 mat より外（アートボード座標）で効かせる必要があるため、クリップありの画像は `<g clip-path>` ＋ 中に transform 付き `<image>` の形で描く（`<image>` 自身に clip-path を付けると mat で clip 図形まで動いて全部切り落とされる＝画面が真っ白になるのを解消）。画像だけ・形だけ動かせて⌘Zで戻る。SVG保存＝画像は `<image href="data:…" transform>` で描き、作業データ metadata#bezierkit には imgId 参照だけ、画素は metadata#bezierkit-images に {imgId:dataURL} で1回だけ埋める（`usedImageStoreJson`・同じ画像を共有する複数オブジェクトでも1件）。開き直し＝`restoreImageStoreFromMeta` が許可形式（png/jpeg/webp/gif の data URL）だけ imageStore に戻し nextImgId を最大 imgId の次へ進めてから restore＝位置・mat・切り抜き・不透明度・レイヤーが戻る。PNG書き出しは buildExportSvg をラスタ化する既存経路でそのまま画像が出る。汎用SVG（外部）の `<image>` は従来どおり取り込まない（importGenericSvg 未変更）。開き直しの検査＝restore で `imageValid`（imgId が数・mat が数6・w0/h0 が正）に外れた画像オブジェクトを捨て、`sanitizeImage` が opacity を正規化、`restoreImageStoreFromMeta` が許可外 mime（text/html・svg 等）の data URL を捨てる。画像選択時のパネル＝`setPaintEnabled(false)` で塗り・線・太さ・塗り/線なし・塗りの種類の欄を押せない見た目にして前の図形の値を出さない（不透明度は効く・効果欄も無効）。画像に効かない機能のガード（漏れ埋め）＝パス演算（`booleanOp` は閉じ図形条件で画像が混じると実行せず画像は残りステータス・`canBoolean` でボタンも無効）、オフセット（`offsetSelection` が画像を外して残りに効かせ、全部画像なら「画像にはオフセットを使えない」）、単純化・アウトライン化（`!isImage` 除外）、スムーズ・幅ツール（対象ピッカーに `!isImage`）、球に貼る（貼る絵・球どちらも画像を除外しステータス）、連結（`joinOpenPaths` が画像を拒否）、うねり/効果（`applyAppearance` が opacity 以外は画像をスキップ）、シェイプビルダー（閉じ図形条件で自動除外）。新テストを `wave13_checks` に追加（clip＝clipBy・SVGに image/clip-path・画像だけ動く・形は残る・Undo／clip-raster＝クリップの中だけ画像色・外は白＝transform と clip のずれ無し／SVG保存→開き直し＝画像2つ・store1件・mat/切り抜き/不透明度/dataURL が戻る・同じ画像は1回だけ埋まる・nextImgId が進む／PNGに画像の色／おかしな imgId・mat・w0 は捨てる・data URL は png/jpeg/webp/gif だけ／画像選択で塗りの欄が押せず図形で戻る／画像を含む選択でパス演算は画像を残しステータス）。`only wave13`＋全回帰とも緑。本物のマウス・キー操作（bkdrive.py・ポート18474・`v2/wave13/check_wave13b_input.py`）で、印影PNGを配置→楕円→⌘A→⌘7で丸く切り抜き（seal が円の中だけに出る）→ドラッグ移動→SVG保存→開き直しで切り抜き・位置が復元するのを確認（`v2/wave13/{04-clipped,05-reopened}.png`）。残り＝手順7 PDF の XObject・手順8 PPTX の p:pic（media/rels/Content_Types/custGeom）は次の回。パッチ: `bezierkit-review-20261102/v2/wave13/{index.patch,cdp-check.patch}`

波13（#4 画像を置いて切り抜く）の3回目として 手順7（PDF の画像）・手順8（PPTX の画像）＋外部SVGの data URL 画像の取り込みを実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テストを含め全緑（BEZIERKIT_OK＋ICONS_OK）。PDF＝画像を XObject で入れる（`resolvePrimitives` に kind 'image'、`transformPrims` が mat を枚ごとに変換、`buildPdf` の `pdfImageOps` が `q [cm] cm /Im Do Q`）。JPEG はバイトをそのまま `/DCTDecode`、PNG など（と透明）は `preparePdfImages`（exportPdf が名前を聞いたあとに await・画像が無ければ待たない＝テストの prompt 差し替えと衝突しない）で画素に展開して無圧縮の DeviceRGB＋透明は DeviceGray の `/SMask`。cm は world（左上原点）座標で `[a·w0, b·w0, −c·h0, −d·h0, c·h0+e, d·h0+f]`（画像の上下と y 下向きページの合わせ）。切り抜きは図形の形の `W n`/`W* n` クリップ（buildPdf が clipBy から作る既存経路）、不透明度は ExtGState `/ca`。PPTX＝画像は `p:pic`（`pptxPicXml`）。`blipFill` の `a:blip r:embed` と `a:stretch`、`spPr` の xfrm に off/ext・回転 rot・反転 flipV（mat から sx・rot・sy で分解、det<0 は flipV）、不透明度 `a:alphaModFix`、切り抜き（上向きのとき）は図形の形の custGeom。媒体は `ppt/media/imageN.ext` に1回だけ（`buildPptxFiles` の media レジストリで imgId→file を共有、`mctx.ref` が slide ごとの rId を発番）、`[Content_Types].xml` に png/jpeg/webp/gif の Default、slide の rels に image 関係を足す（`pptxPackage` 拡張）。PPTX確認（`pptxStats`/`pptxCheck`）に「画像」の行を追加（4章の表にも）。SVG取り込み＝`importGenericSvg` が `<image>` のうち data URL（png/jpeg/webp/gif のみ）を画像オブジェクトにする（http・data:image/svg+xml は従来どおり落とす・サニタイザで href を image のときだけ残す）、CTM と x/y/width/height から mat を作り、画像だけの SVG でも外接枠に入れて取り込む。新テストを `wave13_checks` に追加（PPTX＝p:pic 数・媒体は共有込みで2件・Content_Types・rels・rot/flipV・custGeom・alphaModFix・PPTX確認の画像数／PDF＝/Subtype /Image・JPEGは DCTDecode・透明PNGは SMask・切り抜きの W n／SVG取り込み＝data URL 1件だけ・http/svg は無視・大きさ）。`only wave13`＋全回帰とも緑。本物のマウス・キー操作（bkdrive.py・18474・`v2/wave13/check_wave13d_input.py`）で画像2つ（1つ円で切り抜き・1つ30°回転＋左右反転＋不透明50%）を PDF と PPTX に書き出し、sips と LibreOffice（timeout 120）で画像にして BezierKit の画面と3枚並べ（`v2/wave13/10-compare.png`）＝切り抜きの形・回り・反転・薄さが一致、PPTX は p:pic 2・媒体 image1/image2 の2件、python-pptx で pic 2（グループ内も再帰で数える）を確認。気になった点＝PDF のページは白地を敷かない（既存仕様）ので sips でラスタ化すると背景が黒く見える（中身の描画・切り抜き・向きは正しい）。残り＝なし（波13は完了）。パッチ: `bezierkit-review-20261102/v2/wave13/{index.patch,cdp-check.patch}`

波14（#5 複合シェイプ）の1回目として 手順1（データ＋sanitizeCompound＋syncCompounds の骨組み＋`booleanOp(mode,live)` で作成）・手順2（「あとで直せる」チェック・拡張・解除）・手順3（保存open＋Undo＋ボタンの有効/無効）を実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テスト compound を含め全緑（BEZIERKIT_OK＋ICONS_OK）。複合シェイプ＝パス演算（合体・型抜き・交差・中マド）を **Option（⌥）を押しながら**、または パス欄の **「あとで直せる」（`#compoundLive`）** にチェックして押すと、元の形を残したまま結果だけを見せる（Optionなし・チェックなしは今までどおりふつうのパス）。結果の図形1つに `compound={op,kids,sig}` を持たせる＝`op`（union/subtract/intersect/exclude）、`kids`（元の各図形の形だけ `{nodes,closed}` か `{subpaths}`・並び順＝重ね順で `kids[0]`＝最背面・見た目とidは持たせない＝結果側が持つ）、`sig`（`compoundSig`＝op と kids の JSON 署名）。見た目は全体に1つ（#1 と同じ `inheritAppearance`＝型抜きは最背面 `paths[0]`・ほかは最前面 `paths[last]`）。作り直しは render の頭 `syncRepeats()→syncShapeRects()→syncCompounds()` の順で、`syncCompounds()` が compound を持つ図形の sig が変わったときだけ paper.js でブール結果を焼き直して nodes/subpaths を差し替える（見た目は触らない）＝**sig 不変なら即 return**（点が数千の重い形でも毎 render は焼き直さない）。「拡張」（`#compoundExpand`・`expandCompound`）＝`delete p.compound` でふつうのパスにする（焼いた結果が残る）。「解除」（`#compoundRelease`・`releaseCompound`）＝結果を消し kids を別々のパスに戻す（戻した形には結果の見た目を `inheritAppearance` で付ける）。拡張・解除は複合シェイプを1つだけ選んでいるときだけ押せる（`updateControls` の `compSel`）。保存→開き直しは compound が path に乗って snapshot に入るので残り、restore で `sanitizeCompound`（op が4種・kids が2個以上で各 kid が3点以上の閉じた形かを確認、だめなら外して焼いた結果を普通のパスに）を通し、**sig を空にして kids から焼き直す（kids が真・結果は導出）**。手で結果の点を動かしたら（`beginNodeDrag`）compound を外す＝手崩れ（中に入って kid を直す＝ダブルクリック／ダイレクト選択は次の回）。書き出し（SVG/PNG/PDF/PPTX）は結果の nodes を使う＝「形に焼いて図形」（`resolvePrimitives` 変更なし・compound は無視される）。新テストは `wave14_checks`、`python3 cdp-check.py only wave14` で単体実行（make＝Option+合体で1つ・op/kids2・前面の見た目／live=false は compound なし／sub-back＝型抜きは最背面の見た目／3plus＝3つ以上で kids3／rebuild＝kid の点を動かすと焼き直し（bbox 変化・sig 更新）／expand＝拡張で compound 外れ形と見た目は同じ／release＝解除で元の2つ・どちらも結果の見た目／save-open＝保存open で compound 残り焼き直せる／sanitize＝壊れた compound は外れ普通のパス／undo＝作成1回 Undo で2つに戻る／buttons＝拡張・解除は複合シェイプ選択時だけ押せる）。`only wave14`＋全回帰とも緑。本物のマウス・キー操作（bkdrive.py・ポート18474・`v2/wave14/check_wave14_input.py`）で、円を2つ描いて両方選び Option を押しながら「合体」→複合シェイプ（op=union・kids2・前面の青を継承）→「拡張」でふつうのパス、もう一度「あとで直せる」で作って「解除」で元の2つ（どちらも結果の青）を確認（`v2/wave14/_w14input/{01-w14-01-compound,02-w14-02-expand,03-w14-03-release}.png`）。増えた id 3個（`#compoundLive`/`#compoundExpand`/`#compoundRelease`・`v2/wave14/panel-ids.txt`）。残り（次の回）＝手順4 編集セッション（ダブルクリックで中に入る）・手順5 ダイレクト選択で kid の点を動かす＋重い形の間引き・手順6 他機能の関わり（球化/シンボル化でステータス）。パッチ: `bezierkit-review-20261102/v2/wave14/{index.patch,cdp-check.patch}`

波14（#5 複合シェイプ）の2回目として 手順4（中に入って直す）・手順5（ダイレクト選択で中の点）＋重い形の間引き・Undo を実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テストを含め全緑（BEZIERKIT_OK＋ICONS_OK）。手順4＝選択ツールで複合シェイプを**ダブルクリックすると中に入る**（`compEdit={id,kidIdx}`・symEdit が手本）。中では元の形（kids）を細い線で描き（`drawCompoundKids`）、kid を押して選び、ドラッグでまるごと動かせる（`beginCompMove`/`moveCompMove`）。Esc か外の空白のダブルクリックで抜ける（`exitCompound`）。中にいる間はステータスに「複合シェイプの中（元の形を押して動かせる・Escで抜ける）」、バウンディングボックスのつまみは出さない。複合シェイプでないダブルクリックは今までどおり「同じ色を選ぶ」。手順5＝ダイレクト選択（A）で複合シェイプの点を押すと、中に入っていなくても kid の点を直す（`beginCompNode`/`moveCompNode`。`beginNodeDrag` が `data-kid` を持つ comp-anchor を `beginCompNode` へ回す）＝このとき「手崩れで compound を外す」は起こさない（compound は残る）。重い形の間引き＝`compDragging` フラグ。ドラッグ中は `syncCompounds` を止めて kids（元の形）だけ動かして見せ、結果（焼いた形）は前のまま。指を離した時（`endCompDrag`）に sig が変わって1回だけ焼き直す。点2400の複合シェイプで、ドラッグ中の render は 0.4〜6.4ms、離して作り直す render は 29.8〜34.6ms（約5〜75倍差＝ドラッグ中は重くならない）。Undo＝`beginCompNode`/`beginCompMove` の先頭で pushUndo＝1回のドラッグが ⌘Z 1回で戻る（中にいる間でも抜けた後でも）。新テストを `wave14_checks` に追加（enter-move＝中に入る→kid移動はドラッグ中据え置き・離すと作り直し・compound残る・Escで抜ける／direct-point＝ダイレクト選択で kid の点を動かすと結果が変わり compound は残る／edit-undo＝kid移動1回が Undo1回で戻る／other-dblclick＝複合シェイプでないダブルクリックは中に入らない／heavy＝点>2000 の複合シェイプはドラッグ中に作り直さない）。`only wave14`＋全回帰とも緑。本物のマウス・キー操作（bkdrive.py・ポート18474・`v2/wave14/check_wave14b_input.py`）で、2つの四角を Option+合体→複合シェイプ→ダイレクト選択で右辺の kid の点を+90px→外周 bbox r 640→745・compound 残る→Undo で640に戻る、を確認（`v2/wave14/_w14b/{01-w14b-01-compound,02-w14b-02-direct-kid-moved}.png`）。🚫 合成入力ドライバ（CDP Input.dispatchMouseEvent）は clickCount=2 でも DOM の dblclick を発火しないため、「ダブルクリックで中に入る」操作は実操作ドライバでは駆動できない＝自動テスト（enter-move）で enterCompound/kid移動/作り直し/compound残り/Esc抜けを検証した。残り（次の回）＝手順6 他機能の関わり（球化・シンボル化で焼いた結果を使う＝中は直せなくなるのをステータスで知らせる・パス演算/オフセット/単純化/ナイフ/手で点追加は compound を外してから）。パッチ: `bezierkit-review-20261102/v2/wave14/{index.patch,cdp-check.patch}`

波14（#5 複合シェイプ）の3回目として キャンバスの自前ダブルクリック判定と 手順6（ほかの機能との関わり）を実装し、構文確認（node --check）＋全回帰（`python3 cdp-check.py`）が新テストを含め全緑（BEZIERKIT_OK＋ICONS_OK）。**ダブルクリックの見分けを自前にした理由**＝キャンバスの図形は、1回目の押下で選択が起き render が path 要素を作り直すので、2回目の押下が別の要素に当たり、ブラウザの `dblclick` が一度も出ない（本物のマウスでも同じ）。そのため「中に入る」も前からの「同じ色を選ぶ」も効いていなかった。対策＝svg の pointerdown で、直前が **tap（ほぼ動かない押下→離し。pointerup で記録）** のとき、前の tap から 400ms 以内・5px 以内の2回目の押下をダブルクリックとみなし、`handleCanvasDblclick(e)`（旧 dblclick リスナーの中身を関数化）を呼び、2回目のふつうの処理（ドラッグ開始など）はしない。本物の `dblclick`（画面の普通の要素では出る）が来ても `lastSyntheticDbl` ガードで二重に動かさない。**選択・ダイレクト選択ツールのときだけ**判定し、tap のときだけ arm する（smooth・ナイフ・幅など、同じ場所を続けて押す/なぞる操作を誤ってダブルクリック扱いしない）。手順6＝複合シェイプと他機能の関わりを決めた: ①複製・変形（`transformedPath`）は compound の kids も同じ行列で動かして複合シェイプを保つ（コピー・⌘F・反転・回転・拡縮・整列で中の形も付いてくる・sig を空にして焼き直す） ②シンボルにすると焼いた形にして compound を外す（中は直せない＝仕様通り・ステータスで知らせる・テンプレートからも外す） ③繰り返しは元が compound を保ち、コピーは普通のパス（`RPT_SKIP` に `compound` を追加） ④クリップ（clipBy）・ほかのパス演算は結果の形で動く（入れ子の compound は作らない） ⑤書き出し（SVG/PNG/PDF/PPTX）は結果の形で出る（`resolvePrimitives` は compound を無視・SVG に compound は出ない）。新テストを `wave14_checks` に追加（dbl-enter＝同じ場所の2回の tap で中に入る／far-no-enter＝離れた2回は中に入らない／same-color＝ふつうの図形の2回押しは同じ色を選ぶ／dup＝複製は複合シェイプを保ち元の形も+200ずれて結果が追従／sym-bake＝シンボルは焼いた形で compound 外れる／rpt＝元は compound を保ちコピーは普通のパス／export＝SVG に compound は出ず・PPTX slide が作れる）。`only wave14`＋全回帰とも緑。本物のマウス・キー操作（bkdrive.py・ポート18474・`v2/wave14/check_wave14c_input.py`・`bk.click(sx,sy,count=2)`）で ①複合シェイプをダブルクリック→中に入る→kidドラッグ→Esc ②ふつうの四角のダブルクリック→同じ色を選ぶ ③文字をダブルクリック→打ち直し ④離れた2つを素早く押す→ふつうに選び替わる（中に入らない）、を確認（`v2/wave14/_w14c/*.png`）。残り＝手順4（金印トレースの1画を型抜きで複合シェイプ化して直す確認）は時間切れで次回。パッチ: `bezierkit-review-20261102/v2/wave14/{index.patch,cdp-check.patch}`


波15（#6 ワープ・2026-11-03）: 「配置」タブの変形の中、球に貼るの下に欄（スタイル `#warpStyle` 15種＝Illustrator 日本語版の名前・向き `#warpAxis`・カーブ `#warpBend`・変形 水平/垂直 `#warpDh`/`#warpDv`・「ワープ／かけ直す」`#warpRun`・「平らに戻す」`#warpFlat`）。式は xsvg の envelope-presets（Illustrator の「ワープで作成」の再現）で、カーブ＋は上（水平）／右（垂直）へ反る。球に貼ると同じく、結果の先頭の図形に元の平らな絵と設定（`warpSrc`）を持たせ、かけ直しはいつも元から作る。文字は形にしてゆがめ、平らに戻すと打ち直せる文字に戻る。開くときに `sanitizeWarp`。書き出しはゆがめた形（形に焼いて図形）。回帰 warp（`wave15_checks`）。あわせて直したこと（Kiro）: 選択物だけの書き出し（`buildPathsSvg`）の枠を、曲線のふくらみまで入れた外接枠（`curveBBoxOfPath`＝ベジェの極値を解く）で決めるようにした。前は点だけを見る `bboxOfPath` で、点と点の間でふくらむ曲線（ワープ・回した楕円など）が切れていた。画面の選択枠と W・H の欄は今のまま点で決まる。

波16 直し（2026-11-03）: F1 外接枠を曲線のふくらみまで入れる＝`bboxOfPath` の中身を曲線（ベジェ）の極値まで入れた本当の形の枠にした（`curveBBoxOfPath` は `bboxOfPath` を呼ぶだけに一本化）。文字・画像は今までどおりアンカーで測る。これで選択枠・つまみ・W/H/X/Y の欄・整列・等間隔・拡縮と回転の基準・スナップ・PPTX/PDF の枠がみな同じ曲線の枠を使う（回した楕円・アーチをかけた四角・ペンのS字がはみ出さない）。速くするために、先に点だけで枠を作り、ハンドルがその枠の外に出ている区間だけ極値を解く（ハンドルが枠の中なら曲線は制御点の凸包の中＝枠の中なので正確）。覚え（キャッシュ）は持たない（Kiro・2026-11-03: 担当が入れた描画ごとのキャッシュは、点をその場で動かしてから render までの間に古い枠を返したので外した）。性能（1万ノード）＝render 7.33→9.60ms(x1.31)・ドラッグ 12.78→14.20ms(x1.11)。F2 PPTX の放射グラデの広がり100%超＝`pptxFillXml` で、pos×広がり≤100% の分岐点はそのまま・ちょうど100%の所に「元の位置 1/広がり での補間色・不透明度」を1つ置き・それより外は出さない（100%以下は今まで通り pos を縮める）＝PowerPoint で端が早く暗くならない。F3 数値欄の矢印はUndo1回＝`pushUndo` を、キャプチャ段の change（数値欄 type=number）で控えた欄の番号と1秒の窓でまとめ、同じ欄を続けて矢印で変えた間は新しいスナップショットを積まない（ほかの操作をはさむと切れる・ライブプレビューの欄は今まで通り）。回帰は `wave16_checks`（`only wave16`）＝f1-curve-bbox（45°回した楕円のW/Hが真の大きさ・アーチの枠の上辺が曲線の一番上に合う・軸に沿った四角と楕円は今までと同じ数字）／f2-radial-spread（広がり135%の最後のgsがpos=100000で色が1/1.35の補間色00847B・広がり60%は今まで通りpos=60000）／f3-spinner-undo（矢印3回→Undo1回・1秒超あけた2回→Undo2回）。`only wave16`＋全回帰＋icons 緑。本物のマウス・キー操作（bkdrive.py・ポート18474・`v2/wave16/check_wave16_input.py`）で、楕円を描いて45°回す→選択枠が楕円にぴったり（`_w16input/01-w16-ellipse-rot45.png`）／四角にアーチ→枠の上辺が曲線の一番上に合う（`02-w16-rect-arch.png`）／多角形の角数の矢印を3回→⌘Z1回で戻る（`03-/04-`）を確認。F4（確認担当の報告の不具合）は別件で次回。パッチ: `bezierkit-review-20261102/v2/wave16/{index.patch,cdp-check.patch}`

波16 F4（確認担当の報告の不具合4件・2026-11-03）: ①下絵の移動・大きさ変更が⌘Zで戻らない＝`moveUnderlay`（ドラッグの最初の1回）と`setUnderlayScale`で`pushUndo`、`snapshot`に`underlay{x,y,w,h}`を入れ`restore`で#underlayImgごと戻す（画素は入れない＝作業データ/保存SVGには出ない・下絵なしでも安全）。②選択ツールで文字の隙間（外接枠の中・画線でない所）を押しても掴めない＝選択ツールで.drawnに当たらなかった時`textHitForEdit`で一番上の文字を選ぶ（ほかの図形が物理的に当たっていればそちらが先）。③エリア内文字が枠からあふれた分、画面・PDFは隠れるのにPPTXは全部見えて出る＝`pptxTextXml`で`areaOverflow`のとき`wrapLines`の入る行数だけを段落にする（PowerPointの文字枠が伸びて全部見せるのを防ぐ）、PPTX確認の注記も「PowerPointでは見えている行だけになる」に。④グラデの分岐点トラック（`#gradStopTrack`）の丸でない所を押しても足せない＝帯と同じく分岐点を足す（丸を押すのは今どおり選ぶ・ドラッグ）。回帰を`wave16_checks`に追加（f4-underlay-undo／f4-text-bbox／f4-area-pptx／f4-grad-track）。本物のマウス・キー（bkdrive・18474・`v2/wave16/check_wave16_f4_input.py`）で、下絵の移動→⌘Z→戻る・50%→⌘Z→戻る、文字の隙間クリックで選択、トラックの空き押しで分岐点2→3、エリア文字のあふれを確認（`v2/wave16/_w16f4/*.png`）。F2のLibreOffice確認＝広がり135%の放射グラデを画像にして端（角）の色が BezierKit(0,145,109) と LibreOffice(0,144,111) で一致（Δ2・純青との差205＝端が早く暗くならない）。パッチ更新: `v2/wave16/{index.patch,cdp-check.patch}`
