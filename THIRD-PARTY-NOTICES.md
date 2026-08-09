# Third-Party Notices

このリポジトリ自体のライセンスは MIT（`LICENSE`）。以下の同梱物は各自のライセンスに従う。

## OCCT (Open CASCADE Technology) — LGPL-2.1

- 同梱物: `CadKit/occt/opencascade.full.js` / `CadKit/occt/opencascade.full.wasm`
  （[opencascade.js](https://github.com/donalffons/opencascade.js) 2.0.0-beta による
  OCCT の WebAssembly ビルド。改変せずそのまま同梱）
- ライセンス: GNU Lesser General Public License v2.1
  （<https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>）。
  OCCT 本体は LGPL-2.1 に Open CASCADE 例外を付して配布されている
  （<https://dev.opencascade.org/about/licence>）
- LGPLへの対応: 上記2ファイルは独立したファイルとして同梱しており、
  同等の別ビルドに差し替えて利用できる（CadKit は `CadKit/occt/` のパスを読むだけ）。
  ソースコードは上記の各配布元から入手できる

## その他の外部ライブラリ（同梱なし）

Three.js 0.160.0、Manifold 3.5.1、paper.js 0.12.18、paperjs-offset 1.0.8、
opentype.js 1.3.4、aws-icons 3.2.0、Noto Fonts、Google FontsはCDNから
実行時に読み込むだけで、このリポジトリには同梱していない。
各ライブラリとフォントのライセンスは各配布元を参照する。
