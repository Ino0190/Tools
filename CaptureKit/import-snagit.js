#!/usr/bin/env node
// Snagit資産の取り込み
// ・画像(.snagx): 中のPNGを shots/日付/ に抽出＋OCR/ウインドウ名をカタログへ
// ・動画(.mp4/.mov): コピーせず元の場所を絶対パス参照（13GBを複製しない）
// 何度実行しても二重取り込みしない（カタログ登録済みはスキップ）
// 使い方: node import-snagit.js [--limit N] [--src DIR]
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const BASE = __dirname;
const OUT = path.join(BASE, 'catalog-data.js');
const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };
const SRC = opt('--src', path.join(os.homedir(), 'Pictures', 'Snagit'));
const LIMIT = +opt('--limit', 0);

let catalog = { updated: '', items: [] };
try {
  const t = fs.readFileSync(OUT, 'utf8');
  catalog = JSON.parse(t.replace(/^window\.CATALOG\s*=\s*/, '').replace(/;?\s*$/, ''));
} catch (e) { /* 初回 */ }
const known = new Set(catalog.items.map(i => i.file));
// 抽出済みPNGの元snagx名も記録して二重抽出を防ぐ（noteでなくsrcフィールドで持つ）
const knownSrc = new Set(catalog.items.map(i => i.src).filter(Boolean));

function dims(p) {
  try {
    const o = execFileSync('sips', ['-g', 'pixelWidth', '-g', 'pixelHeight', p], { encoding: 'utf8' });
    return { w: +(o.match(/pixelWidth: (\d+)/) || [])[1] || 0, h: +(o.match(/pixelHeight: (\d+)/) || [])[1] || 0 };
  } catch (e) { return { w: 0, h: 0 }; }
}
function zipList(f) {
  return execFileSync('unzip', ['-Z1', f], { encoding: 'utf8' }).split('\n').filter(Boolean);
}
function zipRead(f, entry) {
  return execFileSync('unzip', ['-p', f, entry], { maxBuffer: 512 * 1024 * 1024 });
}

const NAME_RE = /^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})/;
const files = fs.readdirSync(SRC).filter(f => NAME_RE.test(f)).sort();
let done = 0, skipped = 0, errors = 0;

for (const f of files) {
  if (LIMIT && done >= LIMIT) break;
  const m = f.match(NAME_RE);
  const [, date, hh, mm, ss] = m;
  const time = `${hh}:${mm}:${ss}`;
  const abs = path.join(SRC, f);
  const ext = path.extname(f).toLowerCase();

  try {
    if (ext === '.mp4' || ext === '.mov') {
      if (known.has(abs)) { skipped++; continue; }
      const st = fs.statSync(abs);
      catalog.items.push({
        file: abs, date, time, kind: 'video', size: st.size,
        mtime: Math.round(st.mtimeMs), w: 0, h: 0,
        tags: ['snagit'], group: '', note: '', ocr: ''
      });
      known.add(abs); done++;
    } else if (ext === '.snagx') {
      if (knownSrc.has(f)) { skipped++; continue; }
      // メタデータ（OCR・アプリ名・ウインドウ名）
      let meta = {};
      try { meta = JSON.parse(zipRead(abs, 'metadata.json').toString('utf8')); } catch (e) {}
      // 本体PNG（thumbnail以外。無ければthumbnail）
      const entries = zipList(abs);
      let pngs = entries.filter(e => /\.png$/i.test(e) && e !== 'thumbnail.png');
      if (!pngs.length) pngs = entries.filter(e => e === 'thumbnail.png');
      if (!pngs.length) { errors++; continue; }
      const dayDir = path.join(BASE, 'shots', date);
      fs.mkdirSync(dayDir, { recursive: true });
      pngs.forEach((entry, idx) => {
        const suffix = idx ? `_${idx + 1}` : '';
        const outName = `snagit_${hh}${mm}${ss}${suffix}.png`;
        const outPath = path.join(dayDir, outName);
        fs.writeFileSync(outPath, zipRead(abs, entry));
        const st = fs.statSync(outPath);
        const note = [meta.WindowName, meta.AppName && `（${meta.AppName}）`].filter(Boolean).join('');
        catalog.items.push({
          file: `shots/${date}/${outName}`, date, time, kind: 'image', size: st.size,
          mtime: Math.round(st.mtimeMs), ...dims(outPath),
          tags: ['snagit'], group: '', note, ocr: meta.OcrText || '', src: f
        });
      });
      knownSrc.add(f); done++;
    }
  } catch (e) { errors++; console.error(`NG: ${f}: ${e.message.split('\n')[0]}`); }
  if (done && done % 200 === 0) console.log(`…${done}件`);
}

catalog.items.sort((a, b) => (b.date + b.time).localeCompare(a.date + a.time));
catalog.updated = new Date().toISOString().slice(0, 19).replace('T', ' ');
fs.writeFileSync(OUT, 'window.CATALOG=' + JSON.stringify(catalog, null, 1) + ';\n');
console.log(`取り込み: ${done}件 / スキップ(取り込み済み): ${skipped}件 / エラー: ${errors}件 / カタログ計: ${catalog.items.length}件`);
