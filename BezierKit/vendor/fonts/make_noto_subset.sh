#!/bin/sh
# Noto Sans/Serif CJK JP を日本語の実用範囲に絞って静的 OTF（CFF）を作り直す。
# 配布には .venv-fonttools と /tmp/noto の元 OTF は含めない（再生成用）。
#
# 使い方:
#   cd vendor/fonts
#   sh make_noto_subset.sh
#
# 前提:
#   - .venv-fonttools（隔離 venv・fonttools+brotli 入り）がこのフォルダにある
#     python3 -m venv .venv-fonttools && .venv-fonttools/bin/pip install fonttools brotli
#   - 元の 4 本 OTF を /tmp/noto/ に curl -L で置く:
#       Sans  R/B : cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/OTF/Japanese/NotoSansCJKjp-{Regular,Bold}.otf
#       Serif R/B : raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/Japanese/NotoSerifCJKjp-{Regular,Bold}.otf
set -e

PYFT=".venv-fonttools/bin/pyftsubset"
SRC="/tmp/noto"

# 日本語の実用範囲:
#   U+0020-00FF  基本ラテン・ラテン1
#   U+2000-27BF  一般句読点・矢印・数学記号・罫線・丸数字 等
#   U+3000-303F  CJK記号・句読点
#   U+3040-30FF  ひらがな・カタカナ
#   U+4E00-9FFF  CJK統合漢字（JIS第1・第2水準を含む）
#   U+FF00-FFEF  全角英数記号・半角カナ
UNI="U+0020-00FF,U+2000-27BF,U+3000-303F,U+3040-30FF,U+4E00-9FFF,U+FF00-FFEF"

# --layout-features='' : GSUB/GPOS を全部落とす。
#   BezierKit は opentype.js の getPath（cmap 直引き・GSUB 非適用）で 1 文字ずつ
#   アウトライン化するため、縦書き vert などの異体字グリフは一切使われない。
#   '*' で残すとグリフ数が 22,000→40,000 に倍増しサイズも倍増するだけなので落とす。
#   （落としても getPath の出力は 1 コマンドも変わらないことを確認済み）
# CFF の subr（サブルーチン＝圧縮）は残す。opentype.js 1.3.4 で読めることを確認済みで、
#   --desubroutinize するとかえって大きくなる。
subset () {
  in="$1"; out="$2"
  "$PYFT" "$SRC/$in" \
    --unicodes="$UNI" \
    --layout-features='' \
    --no-hinting \
    --output-file="$out"
  echo "  $out  $(ls -l "$out" | awk '{print $5}') bytes"
}

echo "subsetting (unicodes=$UNI)"
subset NotoSansCJKjp-Regular.otf  NotoSansCJKjp-Regular.subset.otf
subset NotoSansCJKjp-Bold.otf     NotoSansCJKjp-Bold.subset.otf
subset NotoSerifCJKjp-Regular.otf NotoSerifCJKjp-Regular.subset.otf
subset NotoSerifCJKjp-Bold.otf    NotoSerifCJKjp-Bold.subset.otf
echo "done"
