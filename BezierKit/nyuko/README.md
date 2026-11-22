# BezierKit 入稿（カットライン・入稿用 .ai）

ステッカーなどの版下を、BezierKit から「レイヤー3枚（デザイン／カットライン／トンボ）の .ai」で出すための一式。
2026-11-13 に、ロボ3体ステッカー（グラフィック・台紙付きハーフカット）の入稿を一発にするために作った。

## 流れ

1. **アートボードを塗り足し込みの大きさにする**（例: 仕上がり148×100mm・塗り足し3mm → 154×106mm）。単位を mm にすると入れやすい。
2. デザインを置く。背景は塗り足しの端まで届かせる。
3. 画像か図形を選んで **「カットライン作成…」**。白フチ（既定2mm）・角の丸め（1.5mm）・点を減らす許容（0.1mm）を決めて「作成」。
   - 画像は、端が透明なら「不透明な所＝絵」、そうでなければ端の色を紙として輪郭を取る。
   - 複数を選ぶとまとめて処理する（離れていれば別々の線になる）。穴（ドーナツ形）は外す。
   - 「カットライン」レイヤーに、M100相当（#EC008C）・0.25pt・塗りなしの閉じたパスとして入る。
   - 画像に白フチが焼き込み済みなら、白フチは 0 にする。
4. **「入稿用 .ai 書き出し…」**。印刷所の決まり・アートボード・塗り足し・カットラインのレイヤーを確かめ、検査（✓／△／✗）を見て「書き出し」。
   - ✗ があると出せない（切り線がない・デザインがない・仕上がりが0以下）。△ は出せるが知らせる。
   - 出るのは PDF互換の `.ai`。レイヤー＝デザイン／カットライン／トンボ、切り線は M100・0.25pt・閉じる、トンボはレジストレーション、TrimBox＝仕上がり。デザインの色は RGB のまま。
5. 出た .ai を **`nyuko/Illustratorで保存.app`** に落とす。Illustrator 2026 が開いてレイヤーを整え、色モード（CMYK か RGB）を合わせ、**本物の Illustrator 形式**で `<名前>（Illustrator）.ai` に保存する。元のファイルは変えない。結果は `<名前>（Illustrator）.log.txt` にも残る。
   - 初回は macOS が「"Illustratorで保存" が "Adobe Illustrator" を制御しようとしています」と聞くので OK を押す。
   - 色モードの小窓は 15 秒で CMYK に進む。

## なぜ Illustrator を通すのか

.ai は PDF に Adobe 専用データを抱き合わせた形式で、他のソフトはどれも専用データを書けない。BezierKit の .ai だけでも Illustrator では開ける（警告が1回出る）が、印刷所の自動チェックが弾くことがあるので、最後に Illustrator に保存させて本物にする。CMYK 変換も Illustrator に任せる（ブラウザでは精度が出ない）。

## 印刷所の決まり（プリセット）

`index.html` の `NYUKO_PRESETS` に書く。今あるのは:

| 名前 | 切り線レイヤー | 切り線 | 塗り足し | 切り線どうし | 仕上がり端から |
|---|---|---|---|---|---|
| グラフィック（台紙付きステッカー） | カットライン | M100・0.25pt | 3mm | 2mm以上 | 3mm以上 |
| 汎用 | カットパス | M100・0.25pt | 3mm | 2mm以上 | 3mm以上 |

## 検証

```
python3 cdp-check.py nyuko     # 画像→カットライン→.ai→PyMuPDFで読み戻し。NYUKO_OK で合格
```
Illustrator まで通す確認（小窓なし）:
```
osascript -e 'set s to load script (POSIX file "/PATH/TO/KitsRepo/BezierKit/nyuko/droplet.scpt")' \
          -e "set s's quiet to true" \
          -e 'tell s to open {POSIX file "/PATH/TO/KitsRepo/BezierKit/_check/nyuko/test_154x106.ai"}'
```

## ファイル

- `nyuko_save.jsx` — Illustrator 側の台本（色で3層に振り分け・色モード・保存）
- `droplet.applescript` — ドロップレットの元。`build_app.sh` で `.app` と検証用 `droplet.scpt` を作り直す
- `Illustratorで保存.app` — 出来上がり（jsx を中に含む）
