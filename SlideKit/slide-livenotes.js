/**
 * SlideKit Live Notes (独立ファイル・補助機能)
 *
 * 目的:
 *  プレゼン中の会話を、そのとき表示していたスライドと紐づけて残す。
 *  録音とスライド切替ログだけを取り、文字起こしは終了後にローカルで行う。
 *
 * なぜリアルタイム認識にしないか:
 *  ブラウザの Web Speech API (webkitSpeechRecognition) は音声を Google の
 *  サーバーへ送るため顧客先で使えない。かつ file:// では動かず、入力デバイスも
 *  選べない。録音してあとで手元の whisper に通せば、音声は一切外に出ず、
 *  マイク選択も効き、精度も上げられる。プレゼン中の処理も録音だけで済む。
 *
 * 使い方:
 *  <script src="../SlideKit/slide-present.js"></script>
 *  <script src="../SlideKit/slide-livenotes.js"></script>
 *  → 手元ウィンドウの右下に「🎙 Live Notes」パネルが出る (投影側には出ない)。
 *  → 録音を開始 → プレゼン → 停止 → 「音声とログを保存」
 *  → python3 SlideKit/livenotes_transcribe.py <保存したjson>
 *
 * 設計の約束:
 *  - プレゼン機能から独立。例外は必ずこのパネル内で止め、スライド送りを妨げない
 *  - document にキーボードイベントを足さない (矢印キーのスライド送りを壊さない)
 *  - スライドの DOM を書き換えない。読むだけ
 *  - 文字起こし・AI分析はこのファイルの外 (保存した JSON を入力にする)
 */
(function(){
  'use strict';

  var params = new URLSearchParams(location.search);
  // 投影側と UI 抑止時は何もしない (要件: Presenter View 側にだけ置く)
  if (params.get('present') === '1') return;
  if (params.get('hideUI') === '1') return;

  // ===== 定数 =====
  var LANG = 'ja-JP';                                  // 将来の言語切替用
  var LS_DEVICE  = 'slidekit_livenotes_device';        // 選んだマイクを覚える
  var LS_SESSION = 'slidekit_livenotes_session';        // 記録本体 (reload復元用)
  var MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
  var STATE = {
    IDLE:      { key:'idle',      label:'待機中',              cls:'' },
    ASKING:    { key:'asking',    label:'マイクの許可を確認中', cls:'warn' },
    READY:     { key:'ready',     label:'準備完了',            cls:'ok' },
    RECORDING: { key:'recording', label:'録音中',              cls:'rec' },
    STOPPED:   { key:'stopped',   label:'停止 (保存できます)',  cls:'ok' },
    NOMIC:     { key:'nomic',     label:'マイクが見つかりません', cls:'err' },
    LOST:      { key:'lost',      label:'マイクが切断されました', cls:'err' },
    DENIED:    { key:'denied',    label:'マイクが許可されていません', cls:'err' },
    ERROR:     { key:'error',     label:'エラー',              cls:'err' }
  };

  // ===== SlideWatcher: 現在スライドを知る (自前で管理せず既存の通知に乗る) =====
  // slide-present.js が BroadcastChannel で流している slide:change を購読する。
  // 投影ウィンドウを開いていない時は、手元の画面中央にあるスライドで代用する。
  var SlideWatcher = (function(){
    var idx = 0, bus = null, listeners = [];

    function slides(){
      try { return document.querySelectorAll('.slide'); } catch(_) { return []; }
    }
    function idOf(i){
      var ss = slides(), el = ss[i];
      var raw = el && el.getAttribute ? (el.getAttribute('id') || el.getAttribute('data-slide-id')) : null;
      return raw || ('slide-' + (i + 1));
    }
    function set(i){
      if (typeof i !== 'number' || i < 0 || i === idx) return;
      idx = i;
      listeners.forEach(function(fn){ try { fn(idx, idOf(idx)); } catch(_){} });
    }
    // 手元ウィンドウで画面中央に最も近いスライド (slide-edit.js の currentSlide と同じ考え方)
    function fromScroll(){
      var ss = slides();
      if (!ss.length) return null;
      var cy = window.innerHeight / 2, best = 0, bd = 1e9;
      for (var i = 0; i < ss.length; i++) {
        try {
          var r = ss[i].getBoundingClientRect();
          var d = Math.abs(r.top + r.height / 2 - cy);
          if (d < bd) { bd = d; best = i; }
        } catch(_){}
      }
      return best;
    }
    function start(){
      // 既存チャンネルに相乗り (slide-present.js が公開したチャンネル名を使う)
      try {
        var name = window.__skPresentChannel;
        if (name && window.BroadcastChannel) {
          bus = new BroadcastChannel(name);
          bus.addEventListener('message', function(ev){
            try {
              var d = ev.data;
              if (d && d.type === 'slide:change' && typeof d.index === 'number') set(d.index);
            } catch(_){}
          });
        }
      } catch(_){}
      // 投影を開いていない時の保険。スクロールが止まってから判定する
      var t = null;
      try {
        window.addEventListener('scroll', function(){
          if (t) clearTimeout(t);
          t = setTimeout(function(){ var i = fromScroll(); if (i !== null) set(i); }, 200);
        }, { passive:true });
      } catch(_){}
      var i0 = fromScroll();
      if (i0 !== null) idx = i0;
    }
    return {
      start: start,
      index: function(){ return idx; },
      id: function(){ return idOf(idx); },
      total: function(){ return slides().length; },
      onChange: function(fn){ listeners.push(fn); }
    };
  })();

  // ===== NoteStore: 記録の保持と書き出し (音声認識・UIから独立) =====
  // entry.type = 'slide'(切替ログ) / 'memo'(手打ちメモ) / 'mark'(重要マーク) / 'transcript'(後処理で追加)
  // atMs = 録音開始からの経過ミリ秒。あとで whisper のセグメント時刻と突き合わせる鍵になる。
  var NoteStore = (function(){
    var s = null, seq = 0;

    function nowIso(){ return new Date().toISOString(); }
    function stamp(d){
      d = d || new Date();
      function p(n){ return (n < 10 ? '0' : '') + n; }
      return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }
    function fileStamp(iso){
      var d = iso ? new Date(iso) : new Date();
      function p(n){ return (n < 10 ? '0' : '') + n; }
      return d.getFullYear() + p(d.getMonth()+1) + p(d.getDate()) + '_' + p(d.getHours()) + p(d.getMinutes());
    }
    function create(){
      s = {
        sessionId: 'presentation-' + fileStamp() + '-' + Math.random().toString(36).slice(2, 6),
        deck: (location.pathname.split('/').pop() || 'deck'),
        title: (document.title || '').trim(),
        lang: LANG,
        startedAt: nowIso(),
        recordStartedAt: null,
        recordStoppedAt: null,
        audioFile: null,
        entries: []
      };
      seq = 0;
      save();
      return s;
    }
    function save(){
      try { localStorage.setItem(LS_SESSION, JSON.stringify(s)); } catch(_){}
    }
    function load(){
      try {
        var raw = localStorage.getItem(LS_SESSION);
        if (!raw) return null;
        var o = JSON.parse(raw);
        if (!o || !o.sessionId || !Array.isArray(o.entries)) return null;
        s = o;
        seq = o.entries.length;
        return s;
      } catch(_) { return null; }
    }
    function add(type, text, extra){
      if (!s) create();
      seq++;
      var d = new Date();
      var e = {
        id: 'note-' + String(seq).padStart(3, '0'),
        timestamp: d.toISOString(),
        clock: stamp(d),
        atMs: s.recordStartedAt ? (d.getTime() - new Date(s.recordStartedAt).getTime()) : null,
        slideIndex: SlideWatcher.index(),
        slideId: SlideWatcher.id(),
        text: text || '',
        speaker: null,
        type: type
      };
      if (extra) for (var k in extra) if (Object.prototype.hasOwnProperty.call(extra, k)) e[k] = extra[k];
      s.entries.push(e);
      save();
      return e;
    }
    return {
      create: create, load: load, save: save, add: add,
      session: function(){ return s; },
      fileStamp: fileStamp,
      // 前のプレゼンの記録に追記してしまわないよう、録音を始める時は新しい入れ物にする。
      // 保存し忘れても消えないように、前回分は _prev に退避しておく。
      startNew: function(){
        if (s && s.entries && s.entries.length) {
          try { localStorage.setItem(LS_SESSION + '_prev', JSON.stringify(s)); } catch(_){}
        }
        return create();
      },
      markRecordStart: function(){ if (!s) create(); s.recordStartedAt = nowIso(); save(); },
      markRecordStop:  function(){ if (s) { s.recordStoppedAt = nowIso(); save(); } },
      setAudioFile:    function(n){ if (s) { s.audioFile = n; save(); } },
      clear: function(){ s = null; seq = 0; try { localStorage.removeItem(LS_SESSION); } catch(_){} }
    };
  })();

  // ===== Exporter: 記録を JSON / Markdown にする (保存形式を Store から分離) =====
  var Exporter = (function(){
    var MARK = { slide:'▶', memo:'✎', mark:'★', transcript:'' };

    function toJSON(s){ return JSON.stringify(s, null, 2); }

    function toMarkdown(s){
      if (!s) return '';
      var d = new Date(s.startedAt);
      var out = ['# ' + (s.title || 'Presentation Notes'), '', 'Date: ' + d.toLocaleString('ja-JP'),
                 'Deck: ' + s.deck, ''];
      // スライド順にまとめる。切替ログだけのスライドは出さない
      var groups = {}, order = [];
      s.entries.forEach(function(e){
        if (e.type === 'slide') return;
        var k = String(e.slideIndex);
        if (!groups[k]) { groups[k] = { index:e.slideIndex, id:e.slideId, items:[] }; order.push(k); }
        groups[k].items.push(e);
      });
      order.sort(function(a, b){ return groups[a].index - groups[b].index; });
      if (!order.length) return out.concat(['(記録なし)', '']).join('\n');
      order.forEach(function(k){
        var g = groups[k];
        out.push('## Slide ' + (g.index + 1) + '  `' + g.id + '`', '');
        g.items.forEach(function(e){
          var m = MARK[e.type] || '';
          out.push(e.clock + (m ? '  ' + m : ''));
          out.push((e.speaker ? e.speaker + '：' : '') + e.text, '');
        });
      });
      return out.join('\n');
    }

    function download(blob, name){
      try {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.click();
        setTimeout(function(){ try { URL.revokeObjectURL(a.href); } catch(_){} }, 5000);
        return true;
      } catch(_) { return false; }
    }
    function copy(text){
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
      } catch(_){}
      try {
        var ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove();
      } catch(_){}
      return Promise.resolve();
    }
    return { toJSON: toJSON, toMarkdown: toMarkdown, download: download, copy: copy };
  })();

  // ===== MicManager: デバイス列挙・取得・入力レベル・切断検知 =====
  // 権限を取る前はデバイス名が空になるブラウザがあるので、
  // 「一度 getUserMedia して許可を得る → enumerateDevices」の順で列挙する。
  var MicManager = (function(){
    var stream = null, ac = null, analyser = null, buf = null, devices = [];
    var onLost = null, onDevices = null;

    function supported(){
      return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    }
    function list(){
      if (!supported()) return Promise.resolve([]);
      return navigator.mediaDevices.enumerateDevices().then(function(ds){
        devices = ds.filter(function(d){ return d.kind === 'audioinput'; });
        if (onDevices) try { onDevices(devices); } catch(_){}
        return devices;
      }).catch(function(){ return []; });
    }
    // 許可だけ取って即閉じる。これでデバイス名が読めるようになる
    function requestPermission(){
      if (!supported()) return Promise.reject(new Error('unsupported'));
      return navigator.mediaDevices.getUserMedia({ audio:true }).then(function(st){
        st.getTracks().forEach(function(t){ try { t.stop(); } catch(_){} });
        return list();
      });
    }
    function open(deviceId){
      if (!supported()) return Promise.reject(new Error('unsupported'));
      var audio = { echoCancellation:false, noiseSuppression:false, autoGainControl:true };
      if (deviceId) audio.deviceId = { exact: deviceId };
      return navigator.mediaDevices.getUserMedia({ audio: audio })
        .catch(function(err){
          // 指定デバイスが無い/抜けた場合は既定マイクへ落とす
          if (deviceId) return navigator.mediaDevices.getUserMedia({ audio:true });
          throw err;
        })
        .then(function(st){
          stream = st;
          try {
            var AC = window.AudioContext || window.webkitAudioContext;
            ac = new AC();
            var src = ac.createMediaStreamSource(st);
            analyser = ac.createAnalyser();
            analyser.fftSize = 512;
            buf = new Uint8Array(analyser.fftSize);
            src.connect(analyser);           // 出力には繋がない (ハウリング防止)
          } catch(_) { analyser = null; }
          // トラックが死んだ = マイクが抜けた / Bluetooth 切断
          st.getAudioTracks().forEach(function(t){
            t.addEventListener('ended', function(){ if (onLost) try { onLost(); } catch(_){} });
          });
          return st;
        });
    }
    // 0〜1 の入力レベル (RMS)。メーター表示用
    function level(){
      if (!analyser || !buf) return 0;
      try {
        analyser.getByteTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
        return Math.min(1, Math.sqrt(sum / buf.length) * 4);
      } catch(_) { return 0; }
    }
    function close(){
      try { if (stream) stream.getTracks().forEach(function(t){ t.stop(); }); } catch(_){}
      try { if (ac && ac.close) ac.close(); } catch(_){}
      stream = null; ac = null; analyser = null; buf = null;
    }
    function watchDevices(){
      try {
        navigator.mediaDevices.addEventListener('devicechange', function(){ list(); });
      } catch(_){}
    }
    function nameOf(id){
      for (var i = 0; i < devices.length; i++) if (devices[i].deviceId === id) return devices[i].label || 'マイク';
      return null;
    }
    return {
      supported: supported, list: list, requestPermission: requestPermission,
      open: open, close: close, level: level, watchDevices: watchDevices,
      devices: function(){ return devices; }, nameOf: nameOf,
      activeLabel: function(){
        try { return stream ? (stream.getAudioTracks()[0].label || 'マイク') : null; } catch(_) { return null; }
      },
      set onLost(fn){ onLost = fn; },
      set onDevices(fn){ onDevices = fn; }
    };
  })();

  // ===== Recorder: 音声を溜めるだけ。認識はしない (あとで手元の whisper に渡す) =====
  var Recorder = (function(){
    var mr = null, chunks = [], mime = '';

    function pickMime(){
      if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
      for (var i = 0; i < MIME_CANDIDATES.length; i++) {
        if (MediaRecorder.isTypeSupported(MIME_CANDIDATES[i])) return MIME_CANDIDATES[i];
      }
      return '';
    }
    function supported(){ return !!window.MediaRecorder; }
    function start(stream, onError){
      chunks = [];
      mime = pickMime();
      mr = mime ? new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64000 })
                : new MediaRecorder(stream);
      mr.addEventListener('dataavailable', function(ev){
        if (ev.data && ev.data.size) chunks.push(ev.data);
      });
      mr.addEventListener('error', function(ev){ if (onError) try { onError(ev); } catch(_){} });
      // 5秒ごとに区切って溜める。長時間でも1つの巨大バッファにしない
      mr.start(5000);
      return mime || 'audio/webm';
    }
    function stop(){
      return new Promise(function(res){
        if (!mr || mr.state === 'inactive') return res(null);
        mr.addEventListener('stop', function(){
          res(chunks.length ? new Blob(chunks, { type: mime || 'audio/webm' }) : null);
        }, { once:true });
        try { mr.stop(); } catch(_) { res(null); }
      });
    }
    return {
      supported: supported, start: start, stop: stop,
      ext: function(){ return (mime.indexOf('mp4') >= 0) ? 'm4a' : 'webm'; },
      bytes: function(){ return chunks.reduce(function(a, c){ return a + (c.size || 0); }, 0); },
      state: function(){ return mr ? mr.state : 'inactive'; }
    };
  })();

  // ===== Panel: UI。ここで起きた例外はここで止め、プレゼン側へ伝えない =====
  var CSS = ''
  + '#sk-ln{position:fixed;right:14px;bottom:14px;z-index:99998;width:330px;'
  + 'font:14px/1.6 -apple-system,"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;'
  + 'background:#16181d;color:#e8edf5;border:1px solid #2e3a52;border-radius:12px;'
  + 'box-shadow:0 6px 24px rgba(0,0,0,.35);overflow:hidden}'
  + '#sk-ln.min{width:186px}'
  + '#sk-ln .hd{display:flex;align-items:center;gap:8px;padding:9px 11px;background:#1c2130;'
  + 'border-bottom:1px solid #2e3a52;cursor:pointer;user-select:none}'
  + '#sk-ln .hd b{font-size:14px;font-weight:700;flex:1}'
  + '#sk-ln .dot{width:9px;height:9px;border-radius:50%;background:#5c6b82;flex:none}'
  + '#sk-ln .dot.rec{background:#e74c3c;animation:sk-ln-p 1s infinite}'
  + '#sk-ln .dot.ok{background:#2ecc71}'
  + '#sk-ln .dot.err{background:#e74c3c}'
  + '#sk-ln .dot.warn{background:#f1c40f}'
  + '@keyframes sk-ln-p{0%,100%{opacity:1}50%{opacity:.25}}'
  + '#sk-ln .bd{padding:11px}'
  + '#sk-ln.min .bd{display:none}'
  + '#sk-ln .row{display:flex;gap:7px;align-items:center;margin-bottom:9px}'
  + '#sk-ln label{font-size:12px;color:#9fb0c8;flex:none}'
  + '#sk-ln select{flex:1;min-width:0;font:inherit;font-size:12px;padding:5px 6px;'
  + 'background:#0f1420;color:#e8edf5;border:1px solid #2e3a52;border-radius:6px}'
  + '#sk-ln .st{font-size:12px;color:#9fb0c8;margin-bottom:9px}'
  + '#sk-ln .st b{color:#e8edf5}'
  + '#sk-ln .meter{height:5px;background:#0f1420;border-radius:3px;overflow:hidden;margin-bottom:9px}'
  + '#sk-ln .meter i{display:block;height:100%;width:0;background:#2ecc71;transition:width .1s}'
  + '#sk-ln .btns{display:flex;gap:7px;margin-bottom:9px}'
  + '#sk-ln button{flex:1;font:inherit;font-size:13px;font-weight:700;padding:8px 6px;cursor:pointer;'
  + 'background:#222d44;color:#e8edf5;border:1px solid #2e3a52;border-radius:7px}'
  + '#sk-ln button:hover:not(:disabled){border-color:#5aa7ff}'
  + '#sk-ln button:disabled{opacity:.4;cursor:default}'
  + '#sk-ln button.go{background:#c0392b;border-color:#c0392b}'
  + '#sk-ln button.sub{font-size:12px;font-weight:400;padding:6px}'
  + '#sk-ln input.memo{width:100%;font:inherit;font-size:13px;padding:7px 8px;margin-bottom:9px;'
  + 'background:#0f1420;color:#e8edf5;border:1px solid #2e3a52;border-radius:7px}'
  + '#sk-ln .log{max-height:168px;overflow-y:auto;font-size:12px;line-height:1.65;'
  + 'border-top:1px solid #2e3a52;padding-top:8px}'
  + '#sk-ln .log .e{margin-bottom:5px;color:#c9d4e4}'
  + '#sk-ln .log .e i{color:#5aa7ff;font-style:normal}'
  + '#sk-ln .log .e.sl{color:#6b7a90}'
  + '#sk-ln .note{font-size:11px;color:#6b7a90;margin-top:7px;line-height:1.5}';

  var Panel = (function(){
    var el = {}, state = STATE.IDLE, audioBlob = null, levelTimer = null, tickTimer = null;

    function esc(s){
      return String(s == null ? '' : s)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    // 一言だけ知らせる（説明行を一時的に差し替える。別要素を増やさない）
    function toast(msg){
      try {
        var n = el.root.querySelector('.note');
        if (!n) return;
        if (!n.dataset.orig) n.dataset.orig = n.textContent;
        n.textContent = msg;
        n.style.color = 'var(--accent, #f1c40f)';
        setTimeout(function(){
          n.textContent = n.dataset.orig || '';
          n.style.color = '';
        }, 3500);
      } catch(_){}
    }
    function build(){
      var st = document.createElement('style');
      st.textContent = CSS;
      document.head.appendChild(st);
      var d = document.createElement('div');
      d.id = 'sk-ln';
      d.className = 'min';
      d.innerHTML =
        '<div class="hd"><span class="dot"></span><b>🎙 Live Notes</b><span class="tg">▲</span></div>'
      + '<div class="bd">'
      + '<div class="row"><label>マイク</label><select></select></div>'
      + '<div class="meter"><i></i></div>'
      + '<div class="st"></div>'
      + '<div class="btns"><button class="go">● 録音開始</button>'
      + '<button class="stop" disabled>■ 停止</button></div>'
      + '<input class="memo" placeholder="メモ → Enter で今のスライドに残す">'
      + '<div class="btns"><button class="sub save" disabled>⇩ 音声とログ</button>'
      + '<button class="sub md">📋 Markdown</button></div>'
      + '<div class="log"></div>'
      + '<div class="note">録音だけ行い、文字起こしは手元で後から実行します（音声は外部に送りません）。</div>'
      + '</div>';
      document.body.appendChild(d);
      el.root = d;
      el.hd   = d.querySelector('.hd');
      el.tg   = d.querySelector('.tg');
      el.dot  = d.querySelector('.dot');
      el.sel  = d.querySelector('select');
      el.meter= d.querySelector('.meter i');
      el.st   = d.querySelector('.st');
      el.go   = d.querySelector('.go');
      el.stop = d.querySelector('.stop');
      el.memo = d.querySelector('.memo');
      el.save = d.querySelector('.save');
      el.md   = d.querySelector('.md');
      el.log  = d.querySelector('.log');
    }
    function setState(s){
      state = s;
      el.dot.className = 'dot ' + (s.cls || '');
      render();
    }
    function elapsed(){
      var ss = NoteStore.session();
      if (!ss || !ss.recordStartedAt) return '';
      var ms = Date.now() - new Date(ss.recordStartedAt).getTime();
      if (ss.recordStoppedAt) ms = new Date(ss.recordStoppedAt).getTime() - new Date(ss.recordStartedAt).getTime();
      var s = Math.floor(ms / 1000);
      return ' / ' + Math.floor(s / 60) + '分' + ('0' + (s % 60)).slice(-2) + '秒';
    }
    function render(){
      var mic = MicManager.activeLabel() || (el.sel.selectedOptions[0] && el.sel.selectedOptions[0].textContent) || '未選択';
      el.st.innerHTML = '<b>' + esc(state.label) + '</b>' + esc(elapsed())
        + '<br>Slide ' + (SlideWatcher.index() + 1) + ' / ' + SlideWatcher.total()
        + '　<span style="color:#6b7a90">' + esc(mic) + '</span>';
      var rec = (state === STATE.RECORDING);
      el.go.disabled   = rec;
      el.stop.disabled = !rec;
      el.save.disabled = !audioBlob;
    }
    function renderLog(){
      var ss = NoteStore.session();
      if (!ss) { el.log.innerHTML = ''; return; }
      var items = ss.entries.slice(-40).map(function(e){
        if (e.type === 'slide') return '<div class="e sl">' + esc(e.clock) + ' ▶ ' + esc(e.text) + '</div>';
        var m = (e.type === 'mark') ? '★ ' : '✎ ';
        return '<div class="e"><i>' + esc(e.clock) + '</i> ' + m + esc(e.text)
             + ' <span style="color:#6b7a90">[S' + (e.slideIndex + 1) + ']</span></div>';
      });
      el.log.innerHTML = items.join('');
      el.log.scrollTop = el.log.scrollHeight;
    }

    function fillDevices(ds){
      var saved = null;
      try { saved = localStorage.getItem(LS_DEVICE); } catch(_){}
      if (!ds.length) {
        el.sel.innerHTML = '<option value="">マイクなし</option>';
        return;
      }
      el.sel.innerHTML = ds.map(function(d, i){
        var label = d.label || ('マイク ' + (i + 1));
        return '<option value="' + esc(d.deviceId) + '">' + esc(label) + '</option>';
      }).join('');
      // 前回選んだマイクを優先。無ければ既定 (先頭) に落とす
      if (saved) {
        for (var i = 0; i < ds.length; i++) if (ds[i].deviceId === saved) { el.sel.value = saved; break; }
      }
      render();
    }
    function startLevel(){
      stopLevel();
      levelTimer = setInterval(function(){
        try { el.meter.style.width = Math.round(MicManager.level() * 100) + '%'; } catch(_){}
      }, 100);
      tickTimer = setInterval(render, 1000);
    }
    function stopLevel(){
      if (levelTimer) { clearInterval(levelTimer); levelTimer = null; }
      if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
      try { el.meter.style.width = '0%'; } catch(_){}
    }
    // マイクは Start を押した時だけ開く (勝手に録音を始めない)
    function start(){
      if (!MicManager.supported()) { setState(STATE.NOMIC); return; }
      if (!Recorder.supported())   { setState(STATE.ERROR); return; }
      setState(STATE.ASKING);
      var id = el.sel.value || null;
      MicManager.open(id).then(function(stream){
        // 権限が通った直後はデバイス名が読めるようになる。ここで選択肢を埋め直さないと
        // 初回起動時だけマイクを選べないまま録音が進んでしまう
        MicManager.list();
        // 前回の記録が残っていて既に停止済みなら、別のプレゼンとして新しく始める
        var prev = NoteStore.session();
        if (!prev || prev.recordStoppedAt) {
          var had = prev && prev.entries.length;
          NoteStore.startNew();
          if (had) toast('前回の記録は退避しました（新しい記録を開始）');
        }
        NoteStore.markRecordStart();
        Recorder.start(stream, function(){ setState(STATE.ERROR); });
        audioBlob = null;
        NoteStore.add('slide', 'Slide ' + (SlideWatcher.index() + 1) + ' から開始');
        setState(STATE.RECORDING);
        startLevel();
        renderLog();
      }).catch(function(err){
        var n = (err && err.name) || '';
        if (n === 'NotAllowedError' || n === 'SecurityError') setState(STATE.DENIED);
        else if (n === 'NotFoundError' || n === 'OverconstrainedError') setState(STATE.NOMIC);
        else setState(STATE.ERROR);
      });
    }
    function stop(){
      stopLevel();
      Recorder.stop().then(function(blob){
        audioBlob = blob;
        NoteStore.markRecordStop();
        MicManager.close();                       // トラックを確実に止める
        var ss = NoteStore.session();
        if (blob && ss) NoteStore.setAudioFile('livenotes_' + NoteStore.fileStamp(ss.startedAt) + '.' + Recorder.ext());
        setState(STATE.STOPPED);
        renderLog();
      }).catch(function(){
        MicManager.close();
        setState(STATE.ERROR);
      });
    }
    function saveFiles(){
      var ss = NoteStore.session();
      if (!ss) return;
      var base = 'livenotes_' + NoteStore.fileStamp(ss.startedAt);
      if (audioBlob) Exporter.download(audioBlob, base + '.' + Recorder.ext());
      Exporter.download(new Blob([Exporter.toJSON(ss)], { type:'application/json' }), base + '.json');
    }

    function wire(){
      el.hd.addEventListener('click', function(){
        el.root.classList.toggle('min');
        el.tg.textContent = el.root.classList.contains('min') ? '▲' : '▼';
      });
      el.go.addEventListener('click', function(e){ e.stopPropagation(); try { start(); } catch(_) { setState(STATE.ERROR); } });
      el.stop.addEventListener('click', function(e){ e.stopPropagation(); try { stop(); } catch(_) { setState(STATE.ERROR); } });
      el.save.addEventListener('click', function(e){ e.stopPropagation(); try { saveFiles(); } catch(_){} });
      el.md.addEventListener('click', function(e){
        e.stopPropagation();
        try {
          var ss = NoteStore.session();
          if (ss) Exporter.copy(Exporter.toMarkdown(ss));
          el.md.textContent = '📋 コピーした';
          setTimeout(function(){ el.md.textContent = '📋 Markdown'; }, 1400);
        } catch(_){}
      });
      el.sel.addEventListener('change', function(){
        try { localStorage.setItem(LS_DEVICE, el.sel.value); } catch(_){}
        render();
      });
      // メモ欄のキー入力はスライド送りに渡さない (矢印キーでページが飛ぶのを防ぐ)
      el.memo.addEventListener('keydown', function(ev){
        ev.stopPropagation();
        if (ev.key !== 'Enter') return;
        var t = el.memo.value.trim();
        if (!t) return;
        // 先頭に ! を付けると重要マーク
        var type = 'memo';
        if (t.charAt(0) === '!') { type = 'mark'; t = t.slice(1).trim(); }
        try { NoteStore.add(type, t); renderLog(); } catch(_){}
        el.memo.value = '';
      });
      el.memo.addEventListener('keypress', function(ev){ ev.stopPropagation(); });
      el.memo.addEventListener('keyup', function(ev){ ev.stopPropagation(); });
      MicManager.onLost = function(){
        if (state === STATE.RECORDING) { try { stop(); } catch(_){} }
        setState(STATE.LOST);
        MicManager.list();
      };
      MicManager.onDevices = fillDevices;
      SlideWatcher.onChange(function(i){
        if (state === STATE.RECORDING) {
          try { NoteStore.add('slide', 'Slide ' + (i + 1)); renderLog(); } catch(_){}
        }
        render();
      });
    }
    function init(){
      build();
      wire();
      // 前回のセッションが残っていれば復元 (reload しても記録は消えない)
      var restored = NoteStore.load();
      if (restored && restored.entries.length) {
        setState(STATE.STOPPED);
        renderLog();
      } else {
        setState(MicManager.supported() ? STATE.IDLE : STATE.NOMIC);
      }
      MicManager.watchDevices();
      // 権限がまだ無いブラウザではデバイス名が空になる。その場合は名前を出せないので
      // 「録音を始めると選べる」と伝えるだけにして、Start 後に list を呼び直す
      MicManager.list().then(function(ds){
        if (ds.length && !ds[0].label) {
          el.sel.innerHTML = '<option value="">既定のマイク（録音開始後に選べます）</option>';
          return;
        }
        fillDevices(ds);
      });
      render();
    }
    return { init: init };
  })();

  function boot(){
    try {
      SlideWatcher.start();
      Panel.init();
    } catch(err) {
      // Live Notes が死んでもプレゼン機能は動き続けさせる
      try { console.warn('[SlideKit LiveNotes] 起動できませんでした:', err); } catch(_){}
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
