// slidekit-defs.js — SlideKit v2 共有定義（横断的な「値」の唯一の正本）
// マーカー間は厳密な JSON。ブラウザは <script> で window.SLIDEKIT_DEFS として読み、
// Python は load_defs()（html_to_pptx.py）がマーカー間を json.loads して読む。
// 値の出所（v1・2026-07-12 時点の実コードからコピー。移設元は後続タスクで置換するまで残る）:
//   - html_to_pptx.py: _AWS_COVER_COLOR_REMAP（9色）/ テンプレPPTX検索順 / EMU定数
//   - slide-edit.js: TEMPLATES.blue.palette / AWS_COPYRIGHT / coverBg（光彩5層）/ bandGradient / 図形clamp
window.SLIDEKIT_DEFS = /* SLIDEKIT_DEFS_JSON_BEGIN */ {
  "version": 2,
  "canvas": { "wPx": 1280, "hPx": 720, "wEmu": 12192000, "hEmu": 6858000 },
  "darkThreshold": 0.5,
  "formats": {
    "none": { "label": "なし" },
    "blue": {
      "label": "青系モノトーン",
      "palette": {
        "#000000": "#183251",
        "#121212": "#183251",
        "#161616": "#183251",
        "#252525": "#183251",
        "#333333": "#183251",
        "#1a1a1a": "#183251",
        "#212529": "#183251",
        "#5e5e5e": "#3f5882",
        "#718096": "#3f5882",
        "#a0aec0": "#3f5882",
        "#4a5568": "#3f5882",
        "#64748b": "#3f5882",
        "#7a471a": "#21537f",
        "#5c3512": "#21537f",
        "#ba8425": "#21537f",
        "#d69e2e": "#21537f",
        "#b01212": "#21537f",
        "#c53030": "#21537f",
        "#e82a2a": "#21537f",
        "#d81616": "#3f5882",
        "#fff5f5": "#f1f7f9",
        "#f7f2f2": "#f1f7f9",
        "#fffff0": "#f1f7f9",
        "#f4f4ef": "#f1f7f9",
        "#742a2a": "#162a42",
        "#e8f1f7": "#f1f7f9",
        "#8b4513": "#21537f",
        "#6b4423": "#21537f"
      }
    }
  },
  "chartPalette": {
    "_note": "DashboardKit既定テーマ(seiryoku)の系列色。CalcKit/DashboardKit経由のグラフスライドで使う。2026-08-21追加＝利用者判断。他テーマ(pastel等)を使うデッキは <html data-palette=\"custom\"> を宣言する。出所=DashboardKit/dashboard-kit.js の BUILTIN_THEMES seiryoku",
    "seiryoku": ["#1e40af", "#06b6d4", "#10b981", "#2563eb", "#14b8a6", "#94a3b8"]
  },
  "shapes": {
    "arrow": {
      "params": {
        "at": { "min": 0.05, "max": 0.95, "default": 0.45 },
        "ah": { "min": 0.05, "max": 0.90, "default": 0.32 }
      },
      "mso": "RIGHT_ARROW"
    },
    "chevron": {
      "params": {
        "cv": { "min": 0.02, "max": 0.60, "default": 0.14 }
      },
      "mso": "PENTAGON"
    },
    "callout": {
      "params": {
        "bx": { "min": 0.08, "max": 0.92, "default": 0.3 }
      },
      "mso": "RECTANGULAR_CALLOUT"
    },
    "circle": { "mso": "OVAL" },
    "triangle": { "mso": "ISOCELES_TRIANGLE" },
    "line": { "mso": null }
  },
  "list": {
    "maxLevel": 5,
    "circledSymbols": "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳",
    "kinds": {
      "native-disc": {
        "stepEm": 1.4,
        "levels": [
          { "char": "・" },
          { "char": "–" },
          { "char": "·" },
          { "char": "–" },
          { "char": "·" }
        ]
      },
      "native-decimal": {
        "stepEm": 1.9,
        "levels": [
          { "autoNum": "circleNumDbPlain", "cssStyle": "sk-circled", "cssSuffix": " " },
          { "autoNum": "arabicParenR", "cssStyle": "decimal", "cssSuffix": ") " },
          { "autoNum": "alphaLcParenR", "cssStyle": "lower-alpha", "cssSuffix": ") " },
          { "autoNum": "romanLcPeriod", "cssStyle": "lower-roman", "cssSuffix": ". " },
          { "autoNum": "arabicPeriod", "cssStyle": "decimal", "cssSuffix": ". " }
        ]
      }
    }
  },
  "attrSchema": {
    "common": ["data-x", "data-y", "data-w", "data-h", "data-rotate", "data-flip", "data-link-sid"],
    "tb": ["data-font-size", "data-bold", "data-color", "data-fill", "data-align",
           "data-valign", "data-bullet", "data-role", "data-linked-parent"],
    "li": ["data-lvl"],
    "rect": ["data-fill", "data-radius", "data-shape", "data-at", "data-ah", "data-cv", "data-bx",
             "data-border", "data-border-top", "data-border-right", "data-border-bottom",
             "data-border-left", "data-border-style", "data-shadow"],
    "slide": ["data-bg", "data-bg-gradient", "data-aws-logo", "data-sid"],
    "html": ["data-template", "data-aws-decoration", "data-page-size"],
    "img": ["data-border", "data-clip", "data-crop-l", "data-crop-r", "data-crop-t", "data-crop-b"]
  },
  "styleSyncProps": { "data-x": "left", "data-y": "top", "data-w": "width", "data-h": "height" }
} /* SLIDEKIT_DEFS_JSON_END */;
