# Third-Party Notices

このリポジトリ自体のライセンスは MIT（`LICENSE`）。以下の外部依存は各自のライセンスに従う。

## OCCT (Open CASCADE Technology) — LGPL-2.1

- CadKitはopencascade.js 2.0.0-betaのJavaScript／WebAssemblyをjsDelivrから実行時に読み込む
- OCCTファイルは25MBの公開上限を超えるため、このリポジトリには同梱しない
- ライセンス: GNU Lesser General Public License v2.1
  （<https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>）
- OCCT本体はLGPL-2.1にOpen CASCADE例外を付して配布されている
  （<https://dev.opencascade.org/about/licence>）
- opencascade.jsのソースコードは各配布元から入手できる

## BezierKit に同梱したもの

- paper.js 0.12.18（MIT）・paperjs-offset 1.0.8（MIT）・opentype.js 1.3.4（MIT）・pdf.js（Apache-2.0）
- 日本語フォント12本（SIL Open Font License 1.1。Noto Sans/Serif CJK JP は日本語の範囲に絞ったもの）
- 各ライセンス文は `BezierKit/vendor/NOTICES.md` と `BezierKit/vendor/fonts/OFL-*.txt`

## ClassroomKit・CalcKit に同梱したもの

- qrcode-generator（MIT）・SheetJS xlsx（Apache-2.0）

## その他の外部ライブラリ（同梱なし）

Three.js 0.160.0、Manifold 3.5.1、aws-icons 3.2.0、Google FontsはCDNから
実行時に読み込むだけで、このリポジトリには同梱していない。
PictureKitのrawpy 0.27.0、NumPy 2.5.2、Pillow 12.1.1、lensfunpy 1.18.0も
利用者がrequirementsから導入する依存であり、リポジトリには同梱していない。
各ライブラリとフォントのライセンスは各配布元を参照する。
