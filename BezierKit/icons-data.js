// BezierKit アイコンカタログのデータ（正本）
//
// ■ Kiroへの追加指示の受け方（このコメントが運用ルール）
// ・「○○のアイコンを追加して」と言われたら、このファイルの ICONS 配列に追記する
// ・追加・修正したら python3 icon-check.py <id> で形を自動確認する
//   （ヘッドレスChromeで描画→ASCIIアートとbbox/余白をKiroが読んで目視・スクショPNGも保存）
// ・ロゴ等「実物の画像」からアイコンを起こす時は手描きせず python3 icon-from-image.py を使う
//   （画像→マスク→トレース→96×96正規化→エントリ反映→自動目視→中間ファイル削除まで1コマンド。
//    例: python3 icon-from-image.py kiro-ghost/kiro-icon-512.png kiro Kiro 'ゴースト,AI' --shape=light --write）
// ・viewBox は 0 0 96 96 固定。描画は余白8px以上（有効領域 8〜88）
// ・線は stroke: currentColor・線幅8・丸端（レンダラーの既定値。pathには d だけ書けばよい）
//   ※丸に井桁マーク実測9.5（塗りなので不変）に一度合わせたが、細部が重く8に調整（2026-07-29 利用者判断）
// ・塗りアイコンは {d, fill:'currentColor'}（strokeは自動でnoneになる）
// ・線幅を変えたい時だけ {d, width:5} のように指定。ただし統一感が崩れるので原則使わない
// ・線幅9.5で潰れないよう、平行線の間隔は16px以上あける
// ・id は英小文字ケバブケース・重複禁止。name は日本語。tags は検索用の別名
// ・スタイル統一: 幾何学的・角は丸く・ディテールは最小限（16px表示でも読める形）
// ・🚨同形を「塗り」と「輪郭」で対比させる時（ミラー・複製元と複製先等）は、塗り側にも
//   stroke:'currentColor' を付けて外形サイズを揃える。輪郭側は線の分だけ大きく見えるため
//   （2026-07-29 利用者指摘: 左右反転で塗り三角が輪郭三角より小さく見えた）
window.ICONS = [
 {num:1, id:'search', name:'検索', tags:['虫眼鏡','さがす','ルーペ'], paths:[
  {d:'M42 18a24 24 0 1 0 0 48 24 24 0 1 0 0-48'},
  {d:'M60 60 L82 82'}]},
 {num:2, id:'home', name:'ホーム', tags:['家','トップ'], paths:[
  {d:'M14 46 L48 16 L82 46'},
  {d:'M24 42 V82 H72 V42'},
  {d:'M42 82 V60 H54 V82'}]},
 {num:3, id:'gear', name:'設定', tags:['歯車','ギア'], paths:[
  {d:'M48 34a14 14 0 1 0 0 28 14 14 0 1 0 0-28'},
  {d:'M70 48 H80 M48 70 V80 M26 48 H16 M48 26 V16 M63 63 L71 71 M33 63 L25 71 M33 33 L25 25 M63 33 L71 25'}]},
 {num:4, id:'user', name:'ユーザー', tags:['人','プロフィール'], paths:[
  {d:'M48 18a14 14 0 1 0 0 28 14 14 0 1 0 0-28'},
  {d:'M18 82 C18 58 78 58 78 82'}]},
 {num:5, id:'doc', name:'書類', tags:['ドキュメント','ファイル'], paths:[
  {d:'M26 10 H60 L74 24 V86 H26 Z'},
  {d:'M60 10 V24 H74'},
  {d:'M36 48 H64 M36 64 H56'}]},
 {num:6, id:'trash', name:'ゴミ箱', tags:['削除','捨てる'], paths:[
  {d:'M18 26 H78'},
  {d:'M38 26 V16 H58 V26'},
  {d:'M26 26 L30 84 H66 L70 26'},
  {d:'M40 40 V70 M56 40 V70'}]},
 {num:7, id:'check', name:'チェック', tags:['完了','OK'], paths:[
  {d:'M18 52 L40 74 L78 26'}]},
 {num:8, id:'close', name:'閉じる', tags:['バツ','キャンセル'], paths:[
  {d:'M26 26 L70 70 M70 26 L26 70'}]},
 {num:9, id:'plus', name:'追加', tags:['プラス','新規'], paths:[
  {d:'M48 20 V76 M20 48 H76'}]},
 {num:10, id:'arrow-right', name:'右矢印', tags:['次へ','進む'], paths:[
  {d:'M14 48 H74'},
  {d:'M54 26 L76 48 L54 70'}]},
 {num:11, id:'warn', name:'警告', tags:['注意','エラー','！'], paths:[
  {d:'M48 12 L88 80 H8 Z'},
  {d:'M48 36 V54 M48 67 L48 68'}]},
 {num:12, id:'download', name:'ダウンロード', tags:['保存','DL'], paths:[
  {d:'M48 12 V58'},
  {d:'M28 40 L48 60 L68 40'},
  {d:'M16 78 H80'}]},
 {num:13, id:'pen', name:'ペン', tags:['編集','書く'], paths:[
  {d:'M64 16 L80 32 L34 78 L16 80 L18 62 Z'},
  {d:'M58 22 L74 38'}]},
 {num:14, id:'curve', name:'曲線', tags:['ベジェ','パス'], paths:[
  {d:'M14 78 C34 18 62 18 82 78'}]},
 {num:15, id:'save', name:'保存', tags:['フロッピー','セーブ'], paths:[
  {d:'M14 14 H66 L82 30 V82 H14 Z'},
  {d:'M30 14 V34 H60 V14'},
  {d:'M48 53a9 9 0 1 0 0 18 9 9 0 1 0 0-18'}]},
 {num:16, id:'copy', name:'コピー', tags:['複写'], paths:[
  {d:'M34 30 H82 V82 H34 Z'},
  {d:'M66 16 H22 V68'}]},
 {num:17, id:'paste', name:'ペースト', tags:['貼り付け','クリップボード'], paths:[
  {d:'M24 22 H72 V84 H24 Z'},
  {d:'M38 22 V14 H58 V22'},
  {d:'M36 46 H60 M36 64 H60'}]},
 {num:18, id:'duplicate', name:'複製', tags:['増やす'], paths:[
  {d:'M34 30 H82 V82 H34 Z'},
  {d:'M66 16 H22 V68'},
  {d:'M58 44 V68 M46 56 H70'}]},
 {num:19, id:'undo', name:'戻す', tags:['戻る','アンドゥ'], paths:[
  {d:'M80 62A34 34 0 0 0 22 42'},
  {d:'M40 28 L22 42 L42 54'}]},
 {num:20, id:'redo', name:'やり直す', tags:['進む','リドゥ'], paths:[
  {d:'M16 62A34 34 0 0 1 74 42'},
  {d:'M56 28 L74 42 L54 54'}]},
 {num:21, id:'open', name:'開く', tags:['読み込み','フォルダ'], paths:[
  {d:'M12 26 H38 L46 34 H84 V78 H12 Z'}]},
 {num:22, id:'export', name:'書き出し', tags:['エクスポート','アップロード'], paths:[
  {d:'M48 60 V16'},
  {d:'M30 34 L48 16 L66 34'},
  {d:'M16 78 H80'}]},
 {num:23, id:'drop', name:'スポイト', tags:['色を拾う','ドロッパー'], paths:[
  {d:'M54 26 L70 42 L38 74 L22 74 L22 58 Z'},
  {d:'M62 18 L78 34'},
  {d:'M72 14 L80 22', width:16}]},
 {num:24, id:'zoom-in', name:'ズームイン', tags:['拡大'], paths:[
  {d:'M42 18a24 24 0 1 0 0 48 24 24 0 1 0 0-48'},
  {d:'M42 30 V54 M30 42 H54'},
  {d:'M60 60 L82 82'}]},
 {num:25, id:'zoom-out', name:'ズームアウト', tags:['縮小'], paths:[
  {d:'M42 18a24 24 0 1 0 0 48 24 24 0 1 0 0-48'},
  {d:'M30 42 H54'},
  {d:'M60 60 L82 82'}]},
 {num:26, id:'layers', name:'レイヤー', tags:['重ね'], paths:[
  {d:'M48 12 L84 32 L48 52 L12 32 Z'},
  {d:'M12 48 L48 68 L84 48'},
  {d:'M12 62 L48 82 L84 62'}]},
 {num:27, id:'eye', name:'表示', tags:['目','見える'], paths:[
  {d:'M8 48 C24 24 72 24 88 48 C72 72 24 72 8 48 Z'},
  {d:'M48 38a10 10 0 1 0 0 20 10 10 0 1 0 0-20'}]},
 {num:28, id:'eye-off', name:'非表示', tags:['目','隠す'], paths:[
  {d:'M8 48 C24 24 72 24 88 48 C72 72 24 72 8 48 Z'},
  {d:'M48 38a10 10 0 1 0 0 20 10 10 0 1 0 0-20'},
  {d:'M22 80 L74 16'}]},
 {num:29, id:'lock', name:'ロック', tags:['鍵','固定'], paths:[
  {d:'M24 46 H72 V84 H24 Z'},
  {d:'M34 46 V32a14 14 0 0 1 28 0 V46'},
  {d:'M48 60 V70'}]},
 {num:30, id:'play', name:'再生', tags:['プレゼン','スタート'], paths:[
  {d:'M32 20 L76 48 L32 76 Z'}]},
 {num:31, id:'image', name:'画像', tags:['写真','絵'], paths:[
  {d:'M14 20 H82 V76 H14 Z'},
  {d:'M20 68 L40 46 L54 60 L64 50 L78 68'},
  {d:'M32 32 L32 33'}]},
 {num:32, id:'table', name:'表', tags:['テーブル','グリッド'], paths:[
  {d:'M14 22 H82 V78 H14 Z'},
  {d:'M14 40 H82'},
  {d:'M40 40 V78 M62 40 V78'}]},
 {num:33, id:'union', name:'合体', tags:['パス演算','ブーリアン'], paths:[
  {d:'M48 30.8A21 21 0 1 0 48 65.2A21 21 0 1 0 48 30.8Z', fill:'currentColor'}]},
 {num:34, id:'subtract', name:'型抜き', tags:['パス演算','ブーリアン'], paths:[
  {d:'M48 30.8A21 21 0 1 0 48 65.2A21 21 0 0 1 48 30.8Z', fill:'currentColor'},
  {d:'M39 48a21 21 0 1 0 42 0 21 21 0 1 0-42 0', width:5, opacity:.45}]},
 {num:35, id:'intersect', name:'交差', tags:['パス演算','ブーリアン'], paths:[
  {d:'M48 30.8A21 21 0 0 1 48 65.2A21 21 0 0 1 48 30.8Z', fill:'currentColor'},
  {d:'M15 48a21 21 0 1 0 42 0 21 21 0 1 0-42 0', width:5, opacity:.45},
  {d:'M39 48a21 21 0 1 0 42 0 21 21 0 1 0-42 0', width:5, opacity:.45}]},
 {num:78, id:'group', name:'グループ化', tags:['まとめる','オブジェクト'], paths:[
  {d:'M14 26 V14 H26 M70 14 H82 V26 M82 70 V82 H70 M26 82 H14 V70'},
  {d:'M26 40 H48 V62 H26 Z'},
  {d:'M52 52a11 11 0 1 0 22 0a11 11 0 1 0-22 0'}]},
 {num:79, id:'flip-h', name:'左右反転', tags:['ミラー','変形'], paths:[
  {d:'M48 12 V84'},
  {d:'M38 28 V68 L14 68 Z', fill:'currentColor', stroke:'currentColor'},
  {d:'M58 28 V68 L82 68 Z'}]},
 {num:80, id:'flip-v', name:'上下反転', tags:['ミラー','変形'], paths:[
  {d:'M12 48 H84'},
  {d:'M28 38 H68 L68 14 Z', fill:'currentColor', stroke:'currentColor'},
  {d:'M28 58 H68 L68 82 Z'}]},
 {num:81, id:'rotate-copy', name:'回転コピー', tags:['配列','変形'], paths:[
  {d:'M48 48 L48 49'},
  {d:'M40 12h16v16h-16Z', fill:'currentColor', stroke:'currentColor'},
  {d:'M12 56h16v16h-16Z M68 56h16v16h-16Z'}]},
 {num:82, id:'grid-dup', name:'グリッド複製', tags:['配列','タイル'], paths:[
  {d:'M16 16h24v24h-24Z', fill:'currentColor', stroke:'currentColor'},
  {d:'M56 16h24v24h-24Z M16 56h24v24h-24Z M56 56h24v24h-24Z'}]},
 {num:83, id:'scissor', name:'ハサミ', tags:['カット','切る'], paths:[
  {d:'M9 28a9 9 0 1 0 18 0a9 9 0 1 0-18 0'},
  {d:'M9 68a9 9 0 1 0 18 0a9 9 0 1 0-18 0'},
  {d:'M26 34 L84 68 M26 62 L84 28'}]},
 {num:84, id:'blend', name:'ブレンド', tags:['モーフ','中間形状'], paths:[
  {d:'M12 56h18v18h-18Z', fill:'currentColor', stroke:'currentColor'},
  {d:'M38 46h22v22h-22Z'},
  {d:'M60 38a12 12 0 1 0 24 0a12 12 0 1 0-24 0'}]},
 {num:85, id:'simplify', name:'単純化', tags:['アンカー削減','なめらか'], paths:[
  {d:'M12 62 L22 46 L32 60 L42 44 C58 30 72 42 84 60'}]},
 {num:86, id:'mask', name:'マスク', tags:['クリップ','切り抜き'], paths:[
  {d:'M18 18 H78 V78 H18 Z M36 48a14 14 0 1 0 28 0a14 14 0 1 0-28 0', fill:'currentColor'}]},
 {num:87, id:'dimension', name:'寸法線', tags:['測る','図面'], paths:[
  {d:'M14 52 V84 M82 52 V84'},
  {d:'M14 68 H82'},
  {d:'M26 60 L14 68 L26 76 M70 60 L82 68 L70 76'}]},
 {num:88, id:'angle', name:'角度', tags:['図面','∠'], paths:[
  {d:'M18 78 H80 M18 78 L66 26'},
  {d:'M46 78A28 28 0 0 0 37 58'}]},
 {num:89, id:'dist-h', name:'横等間隔', tags:['整列','分布'], paths:[
  {d:'M20 28 V68 M48 28 V68 M76 28 V68'}]},
 {num:90, id:'dist-v', name:'縦等間隔', tags:['整列','分布'], paths:[
  {d:'M28 20 H68 M28 48 H68 M28 76 H68'}]},
 {num:91, id:'offset', name:'オフセット', tags:['拡縮','輪郭'], paths:[
  {d:'M30 30 H66 V66 H30 Z'},
  {d:'M14 14 H82 V82 H14 Z'}]},
 {num:92, id:'text-outline', name:'文字アウトライン化', tags:['文字','パス化'], paths:[
  {d:'M26 22 H70 M48 22 V74'},
  {d:'M20 14h12v12h-12Z M64 14h12v12h-12Z M42 66h12v12h-12Z', fill:'currentColor'}]},
 {num:93, id:'cube', name:'立方体', tags:['3D','CadKit','STL'], paths:[
  {d:'M48 12 L84 32 V64 L48 84 L12 64 V32 Z'},
  {d:'M12 32 L48 52 L84 32 M48 52 V84'}]},
 {num:94, id:'camera', name:'カメラ', tags:['撮影','スクショ'], paths:[
  {d:'M12 30 H32 L38 20 H58 L64 30 H84 V78 H12 Z'},
  {d:'M34 52a14 14 0 1 0 28 0a14 14 0 1 0-28 0'}]},
 {num:95, id:'bone', name:'骨格', tags:['リグ','関節','CadKit'], paths:[
  {d:'M14 74a8 8 0 1 0 16 0a8 8 0 1 0-16 0'},
  {d:'M40 48a8 8 0 1 0 16 0a8 8 0 1 0-16 0'},
  {d:'M66 22a8 8 0 1 0 16 0a8 8 0 1 0-16 0'},
  {d:'M28 68 L42 54 M54 42 L68 28'}]},
 {num:96, id:'theme', name:'ライト／ダーク', tags:['テーマ','切替'], paths:[
  {d:'M18 48a30 30 0 1 0 60 0a30 30 0 1 0-60 0'},
  {d:'M48 18a30 30 0 0 1 0 60Z', fill:'currentColor'}]},
 {num:97, id:'con-h', name:'水平拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M16 48 H80'},
  {d:'M16 48 L16 49 M80 48 L80 49', width:14}]},
 {num:98, id:'con-v', name:'垂直拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M48 16 V80'},
  {d:'M48 16 L48 17 M48 80 L48 81', width:14}]},
 {num:99, id:'con-para', name:'平行拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M26 76 L54 20 M42 76 L70 20'}]},
 {num:100, id:'con-perp', name:'直角拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M20 20 V76 H76'},
  {d:'M20 48 H48 V76'}]},
 {num:101, id:'con-eq', name:'等長拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M20 34 H76 M20 62 H76'},
  {d:'M45 24 L51 44 M45 52 L51 72'}]},
 {num:102, id:'con-coin', name:'一致拘束', tags:['スケッチ','CadKit'], paths:[
  {d:'M34 48a14 14 0 1 0 28 0a14 14 0 1 0-28 0'},
  {d:'M48 48 L48 49', width:14}]},
 {num:103, id:'brush', name:'書式コピー', tags:['筆','SlideKit','転写'], paths:[
  {d:'M84 12 L52 44'},
  {d:'M52 44 L28 52 L44 68 Z', fill:'currentColor', stroke:'currentColor'}]},
 {num:104, id:'palette', name:'パレット', tags:['色','SlideKit'], paths:[
  {d:'M16 50a32 32 0 1 0 64 0a32 32 0 1 0-64 0'},
  {d:'M34 38 L34 39 M52 32 L52 33 M64 46 L64 47', width:12},
  {d:'M52 64 L58 64', width:14}]},
 {num:105, id:'sticky', name:'付箋', tags:['メモ','ポストイット','SlideKit'], paths:[
  {d:'M18 16 H78 V58 L58 78 H18 Z'},
  {d:'M78 58 H58 V78'}]},
 {num:106, id:'screen', name:'プレゼン画面', tags:['投影','スクリーン','SlideKit'], paths:[
  {d:'M12 20 H84'},
  {d:'M20 20 V60 H76 V20'},
  {d:'M48 60 V72 M36 80 H60'}]},
 {num:107, id:'font', name:'フォント', tags:['文字','A','SlideKit'], paths:[
  {d:'M24 78 L48 18 L72 78'},
  {d:'M32 58 H64'}]},
 {num:108, id:'shadow', name:'影', tags:['ドロップシャドウ','SlideKit'], paths:[
  {d:'M30 30 H82 V82 H30 Z', fill:'currentColor', opacity:.45},
  {d:'M14 14 H66 V66 H14 Z'}]},
 {num:36, id:'exclude', name:'中マド', tags:['パス演算','ブーリアン'], paths:[
  {d:'M15 48a21 21 0 1 0 42 0a21 21 0 1 0-42 0M39 48a21 21 0 1 1 42 0a21 21 0 1 1-42 0', fill:'currentColor'}]},
 {num:109, id:'format', name:'フォーマット', tags:['三角定規','📐','SlideKit'], paths:[
  {d:'M18 78 L78 78 L18 18 Z'},
  {d:'M34 64 L48 64 L34 50 Z'}]},
 {num:110, id:'link', name:'リンク', tags:['鎖','🔗','共通'], paths:[
  {d:'M40 52a20 20 0 0 0 30.2 2.2l12-12a20 20 0 0 0-28.3-28.3l-6.9 6.8'},
  {d:'M56 44a20 20 0 0 0-30.2-2.2l-12 12a20 20 0 0 0 28.3 28.3l6.9-6.8'}]},
 {num:111, id:'pin', name:'ピン', tags:['場所','📍','マーカー'], paths:[
  {d:'M48 12a24 24 0 0 1 24 24c0 18-24 48-24 48S24 54 24 36a24 24 0 0 1 24-24Z'},
  {d:'M40 36a8 8 0 1 0 16 0a8 8 0 1 0-16 0'}]},
 {num:112, id:'target', name:'的', tags:['ターゲット','🎯','選択中'], paths:[
  {d:'M18 48a30 30 0 1 0 60 0a30 30 0 1 0-60 0'},
  {d:'M34 48a14 14 0 1 0 28 0a14 14 0 1 0-28 0'},
  {d:'M48 48 L48 49', width:12}]},
 {num:113, id:'puzzle', name:'パズル', tags:['ピース','🧩','図解'], paths:[
  {d:'M20 40 H38a10 10 0 1 1 20 0 H76 V56a10 10 0 1 0 0 20 V78 H20 Z'}]},
 {num:114, id:'book', name:'本', tags:['ドキュメント','📖','使い方'], paths:[
  {d:'M48 26 C38 18 26 18 16 22 V72 C26 68 38 68 48 76 C58 68 70 68 80 72 V22 C70 18 58 18 48 26 Z'},
  {d:'M48 26 V76'}]},
 {num:115, id:'cloud', name:'クラウド', tags:['雲','☁️','AWS'], paths:[
  {d:'M70 76 H36a28 28 0 1 1 26.8-36A18 18 0 1 1 70 76 Z'}]},
 {num:116, id:'refresh', name:'更新', tags:['再読み込み','🔄','リフレッシュ'], paths:[
  {d:'M84 48a36 36 0 1 1-10.6-25.4'},
  {d:'M84 12 V36 H60'}]},
 {num:117, id:'square', name:'四角', tags:['図形','□','SlideKit'], paths:[
  {d:'M20 20 H76 V76 H20 Z'}]},
 {num:118, id:'rrect', name:'角丸四角', tags:['図形','▢','SlideKit'], paths:[
  {d:'M34 20 H62 A14 14 0 0 1 76 34 V62 A14 14 0 0 1 62 76 H34 A14 14 0 0 1 20 62 V34 A14 14 0 0 1 34 20 Z'}]},
 {num:119, id:'circle', name:'丸', tags:['図形','●','SlideKit'], paths:[
  {d:'M18 48a30 30 0 1 0 60 0a30 30 0 1 0-60 0'}]},
 {num:120, id:'triangle', name:'三角', tags:['図形','▲','SlideKit'], paths:[
  {d:'M48 18 L82 76 H14 Z'}]},
 {num:121, id:'chevron', name:'帯矢印', tags:['図形','期間','ホームベース','SlideKit'], paths:[
  {d:'M14 30 H62 L82 48 L62 66 H14 Z'}]},

 // ---- 各キットのUIで使っているアイコン（_collect_iconsで20×20→96×96変換） ----
 {num:37, id:'bz-select', name:'選択', tags:['BezierKit','ツール'], paths:[
  {d:"M 24 12 74.4 47 l -22.1 3.8 12.5 24 -9.6 4.8 -12.5 -24 -16.3 15.4 z", fill:'currentColor', stroke:'currentColor'}]},
 {num:38, id:'bz-direct', name:'ダイレクト選択', tags:['BezierKit','ツール'], paths:[
  {d:"M 24 12 74.4 47 l -22.1 3.8 12.5 24 -9.6 4.8 -12.5 -24 -16.3 15.4 z"}]},
 {num:40, id:'bz-pencil', name:'鉛筆', tags:['BezierKit','ツール'], paths:[
  {d:"M 62.4 16.8 79.2 33.6 33.6 79.2 14.4 81.6 l 2.4 -19.2 z"},
  {d:"M 16.8 79.2 c 9.6 -19.2 24 -24 38.4 -43.2"}]},
 {num:41, id:'bz-smooth', name:'スムーズ', tags:['BezierKit','ツール'], paths:[
  {d:"M 14.4 62.4 c 14.4 -31.2 28.8 21.6 43.2 -9.6 7.2 -15.4 14.4 -17.3 24 -17.3"},
  {d:"M7.7 62.4a6.7 6.7 0 1 0 13.4 0a6.7 6.7 0 1 0 -13.4 0", fill:'currentColor'},
  {d:"M74.9 35.5a6.7 6.7 0 1 0 13.4 0a6.7 6.7 0 1 0 -13.4 0", fill:'currentColor'}]},
 {num:42, id:'bz-width', name:'線幅', tags:['BezierKit','ツール'], paths:[
  {d:"M 12 48 C 33.6 28.8 62.4 28.8 84 48 C 62.4 67.2 33.6 67.2 12 48 Z"},
  {d:"M 12 48 H 84"}]},
 {num:43, id:'bz-builder', name:'シェイプビルダー', tags:['BezierKit','ツール'], paths:[
  {d:"M9.6 48a26.4 26.4 0 1 0 52.8 0a26.4 26.4 0 1 0 -52.8 0"},
  {d:"M33.6 48a26.4 26.4 0 1 0 52.8 0a26.4 26.4 0 1 0 -52.8 0"},
  {d:"M 48 38.4 v 19.2 M 38.4 48 h 19.2"}]},
 {num:44, id:'bz-rect', name:'矩形', tags:['BezierKit','ツール'], paths:[
  {d:"M14.4 24H81.6V72H14.4Z"}]},
 {num:45, id:'bz-ellipse', name:'楕円', tags:['BezierKit','ツール'], paths:[
  {d:"M14.4 48a33.6 24 0 1 0 67.2 0a33.6 24 0 1 0 -67.2 0"}]},
 {num:46, id:'bz-line', name:'直線', tags:['BezierKit','ツール'], paths:[
  {d:"M 19.2 76.8 76.8 19.2"}]},
 {num:47, id:'bz-polygon', name:'多角形', tags:['BezierKit','ツール'], paths:[
  {d:"M 48 20.2 l 29.3 21.1 -11 34.6 H 29.8 L 18.7 41.3 z"}]},
 {num:48, id:'bz-star', name:'星', tags:['BezierKit','ツール'], paths:[
  {d:"M 48 12 l 10.6 22.1 24 3.4 -17.3 16.8 4.3 24 -21.6 -11.5 -21.6 11.5 4.3 -24 L 13.4 37.4 l 24 -3.4 z"}]},
 {num:49, id:'bz-text', name:'文字', tags:['BezierKit','ツール'], paths:[
  {d:"M 19.2 26.4 V 19.2 h 57.6 v 7.2 M 48 19.2 v 57.6 M 38.4 76.8 h 19.2"}]},
 {num:50, id:'cad-sel-auto', name:'自動', tags:['CadKit','ツール'], paths:[
  {d:"M 26.4 14.4 l 45.6 31.2 -19.2 4.3 10.6 23 -10.1 4.8 -10.6 -23.5 -14.4 13 z"}]},
 {num:51, id:'cad-sel-body', name:'ボディ', tags:['CadKit','ツール'], paths:[
  {d:"M 48 12 81.6 28.8 v 38.4 l -33.6 16.8 L 14.4 67.2 V 28.8 z"},
  {d:"M 14.4 28.8 l 33.6 16.8 L 81.6 28.8 M 48 45.6 v 38.4"}]},
 {num:52, id:'cad-sel-face', name:'面', tags:['CadKit','ツール'], paths:[
  {d:"M 48 12 81.6 28.8 v 38.4 l -33.6 16.8 L 14.4 67.2 V 28.8 z"},
  {d:"M 14.4 28.8 l 33.6 16.8 L 81.6 28.8 M 48 45.6 v 38.4"},
  {d:"M 48 12 81.6 28.8 l -33.6 16.8 L 14.4 28.8 z", fill:'currentColor', opacity:.55}]},
 {num:53, id:'cad-sel-edge', name:'エッジ', tags:['CadKit','ツール'], paths:[
  {d:"M 48 12 81.6 28.8 v 38.4 l -33.6 16.8 L 14.4 67.2 V 28.8 z"},
  {d:"M 14.4 28.8 l 33.6 16.8 L 81.6 28.8"},
  {d:"M 48 45.6 v 38.4"}]},
 {num:54, id:'cad-gz-move', name:'移動ギズモ', tags:['CadKit','ツール'], paths:[
  {d:"M 48 12 v 72 M 12 48 h 72"},
  {d:"M 48 12 38.4 24 m 9.6 -12 L 57.6 24 M 48 84 38.4 72 m 9.6 12 L 57.6 72 M 12 48 24 38.4 m -12 9.6 L 24 57.6 M 84 48 72 38.4 m 12 9.6 L 72 57.6"}]},
 {num:55, id:'cad-gz-rot', name:'回転ギズモ', tags:['CadKit','ツール'], paths:[
  {d:"M 79.2 48 a 31.2 31.2 0 1 1 -15.4 -26.9"},
  {d:"M 80.6 12.5 v 20.2 h -20.2"}]},
 {num:56, id:'cad-gz-scale', name:'尺度ギズモ', tags:['CadKit','ツール'], paths:[
  {d:"M14.4 14.4H48V48H14.4Z"},
  {d:"M 57.6 81.6 h 24 v -24"},
  {d:"M 81.6 81.6 48 48"}]},
 {num:57, id:'cad-fit', name:'フィット', tags:['CadKit','ツール'], paths:[
  {d:"M 14.4 28.8 V 14.4 h 14.4 M 67.2 14.4 h 14.4 v 14.4 M 81.6 67.2 v 14.4 h -14.4 M 28.8 81.6 H 14.4 v -14.4"},
  {d:"M39.8 48a8.2 8.2 0 1 0 16.3 0a8.2 8.2 0 1 0 -16.3 0", fill:'currentColor'}]},
 {num:58, id:'cad-persp', name:'パース／平行投影の切替', tags:['CadKit','ツール'], paths:[
  {d:"M 33.6 24 h 28.8 l 19.2 52.8 H 14.4 z"},
  {d:"M 28.8 59.5 h 39.4"}]},
 {num:59, id:'cad-drc', name:'干渉チェック', tags:['CadKit','ツール'], paths:[
  {d:"M14.4 14.4H57.6V57.6H14.4Z"},
  {d:"M38.4 38.4H81.6V81.6H38.4Z"},
  {d:"M38.4 38.4H57.6V57.6H38.4Z", fill:'currentColor', opacity:.65}]},
 {num:60, id:'cad-sk-edit', name:'選択', tags:['CadKit','スケッチ'], paths:[
  {d:"M 19.2 14.4 72 48 l -24 7.2 L 38.4 81.6 Z"}]},
 {num:61, id:'cad-sk-profile', name:'面選択', tags:['CadKit','スケッチ'], paths:[
  {d:"M 14.4 48 c 14.4 -24 52.8 -24 67.2 0 -14.4 24 -52.8 24 -67.2 0 Z", fill:'currentColor', stroke:'currentColor', opacity:.25},
  {d:"M31.2 48a16.8 16.8 0 1 0 33.6 0a16.8 16.8 0 1 0 -33.6 0"}]},
 {num:62, id:'cad-sk-rect', name:'長方形', tags:['CadKit','スケッチ'], paths:[
  {d:"M14.4 24H81.6V72H14.4Z"}]},
 {num:63, id:'cad-sk-circle', name:'円', tags:['CadKit','スケッチ'], paths:[
  {d:"M16.8 48a31.2 31.2 0 1 0 62.4 0a31.2 31.2 0 1 0 -62.4 0"}]},
 {num:64, id:'cad-sk-ellipse', name:'楕円', tags:['CadKit','スケッチ'], paths:[
  {d:"M14.4 48a33.6 21.6 0 1 0 67.2 0a33.6 21.6 0 1 0 -67.2 0"}]},
 {num:65, id:'cad-sk-poly', name:'折れ線', tags:['CadKit','スケッチ'], paths:[
  {d:"M 14.4 72 33.6 28.8 l 19.2 28.8 28.8 -43.2"}]},
 {num:66, id:'cad-sk-arc', name:'円弧', tags:['CadKit','スケッチ'], paths:[
  {d:"M 14.4 76.8 A 62.4 62.4 0 0 1 76.8 14.4"},
  {d:"M71.5 76.8a5.3 5.3 0 1 0 10.6 0a5.3 5.3 0 1 0 -10.6 0", fill:'currentColor'}]},
 {num:67, id:'cad-sk-spline', name:'スプライン', tags:['CadKit','スケッチ'], paths:[
  {d:"M 14.4 67.2 c 19.2 -43.2 43.2 43.2 67.2 -19.2"}]},
 {num:68, id:'cad-ft-extrude', name:'押し出し', tags:['CadKit','フィーチャー'], paths:[
  {d:"M19.2 52.8H76.8V81.6H19.2Z"},
  {d:"M 48 43.2 V 14.4 M 36 26.4 48 14.4 l 12 12"}]},
 {num:69, id:'cad-ft-revolve', name:'回転体', tags:['CadKit','フィーチャー'], paths:[
  {d:"M 48 12 v 72"},
  {d:"M 62.4 24 c 13.4 7.2 15.4 38.4 0 50.4"},
  {d:"M24 74.4a24 8.6 0 1 0 48 0a24 8.6 0 1 0 -48 0"}]},
 {num:70, id:'cad-ft-loft', name:'ロフト', tags:['CadKit','フィーチャー'], paths:[
  {d:"M28.8 21.6a19.2 7.7 0 1 0 38.4 0a19.2 7.7 0 1 0 -38.4 0"},
  {d:"M14.4 74.4a33.6 10.1 0 1 0 67.2 0a33.6 10.1 0 1 0 -67.2 0"},
  {d:"M 28.8 25 14.4 69.6 M 67.2 25 l 14.4 44.6"}]},
 {num:71, id:'cad-ft-sweep', name:'スイープ', tags:['CadKit','フィーチャー'], paths:[
  {d:"M 16.8 79.2 C 16.8 48 33.6 36 60 33.6"},
  {d:"M57.1 31.2a12.5 12.5 0 1 0 25 0a12.5 12.5 0 1 0 -25 0"}]},
 {num:72, id:'cad-ft-mirror', name:'ミラー', tags:['CadKit','フィーチャー'], paths:[
  {d:"M 48 12 v 72"},
  {d:"M 36 28.8 14.4 67.2 h 21.6 z", fill:'currentColor', stroke:'currentColor', opacity:.55},
  {d:"M 60 28.8 81.6 67.2 h -21.6 z"}]},
 {num:73, id:'cad-ft-boolean', name:'ボディのブーリアン', tags:['CadKit','フィーチャー'], paths:[
  {d:"M12 48a24 24 0 1 0 48 0a24 24 0 1 0 -48 0"},
  {d:"M36 48a24 24 0 1 0 48 0a24 24 0 1 0 -48 0"}]},
 {num:74, id:'cad-ft-facepull', name:'面の押し引き', tags:['CadKit','フィーチャー'], paths:[
  {d:"M19.2 52.8H76.8V81.6H19.2Z", fill:'currentColor', opacity:.4},
  {d:"M19.2 52.8H76.8V81.6H19.2Z"},
  {d:"M 48 40.8 v -24 M 36 28.8 48 16.8 60 28.8 M 48 40.8"}]},
 {num:75, id:'cad-ft-fillet', name:'フィレット', tags:['CadKit','フィーチャー'], paths:[
  {d:"M 14.4 81.6 V 43.2 a 28.8 28.8 0 0 1 28.8 -28.8 h 38.4"},
  {d:"M 14.4 43.2 h 9.6 M 43.2 14.4 v 9.6", opacity:.5}]},
 {num:76, id:'cad-ft-chamfer', name:'面取り', tags:['CadKit','フィーチャー'], paths:[
  {d:"M 14.4 81.6 V 43.2 l 28.8 -28.8 h 38.4"},
  {d:"M 14.4 43.2 43.2 14.4", opacity:.5}]},
 {num:77, id:'kit-mark', name:'丸に井桁', tags:['キット共通','ロゴ'], paths:[
  {d:"M 48.4 1.1 C 74.1 1.1 94.9 21.9 94.9 47.5 C 94.9 73.2 74.1 94 48.4 94 C 22.8 94 2 73.2 2 47.5 C 2 21.9 22.8 1.1 48.4 1.1 Z M 11.2 47.5 C 11.2 68.1 27.9 84.8 48.4 84.8 C 69 84.8 85.7 68.1 85.7 47.5 C 85.7 26.9 69 10.3 48.4 10.3 C 27.9 10.3 11.2 26.9 11.2 47.5 Z", fill:'currentColor'},
  {d:"M 58.1 20.4 h 9.8 v 75.5 h -9.8 Z M 28.1 0.2 h 9.8 v 75.5 h -9.8 Z M 0.2 67 V 57.2 h 75.5 v 9.8 Z M 20.4 37.9 V 28.1 h 75.5 v 9.8 Z", fill:'currentColor'}]},
 {num:122, id:'kiro', name:'Kiro', tags:['ゴースト','おばけ','エージェント','AI'], paths:[
  {d:'M 48.9 78.9 C 48.6 78.8 41.6 82.6 40 83 C 33.7 84.4 26.8 81.2 27.9 73.9 C 28.2 72 29.3 69.7 29.5 68.1 C 29.3 67.9 27.9 68.7 27.5 68.8 C 24.7 69.4 20 70.2 19 66.4 C 18.1 62.8 20.4 59.6 22 56.7 C 23 54.9 23.4 52.4 23.9 50.4 C 24.6 47.8 24.3 43.7 24.7 41 C 25.1 37.4 26 33.3 27.3 29.9 C 33.6 12.9 54.3 10 67.1 21.5 C 77.9 31.2 76.7 56.4 71.2 68.5 C 68.5 74.5 60.5 86 52.5 82.9 C 50.5 82.2 50.3 80 48.9 78.9 Z M 49.3 33.8 C 45.2 35.8 46.3 47.1 51.9 44.2 C 55.4 42.4 53.9 31.5 49.3 33.8 Z M 61 33.8 C 56.7 35.4 58 47.2 63.6 44.2 C 66.8 42.5 65.8 31.9 61 33.8 Z', fill:'currentColor', fr:'evenodd'}]},
];
