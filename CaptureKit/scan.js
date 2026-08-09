#!/usr/bin/env node
// CaptureKit カタログ生成
// shots/YYYY-MM-DD/ を走査して catalog-data.js を作る。
// tags / group / note は既存カタログから引き継ぐ（Kiroや手編集が消えない）。
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BASE = __dirname;
const SHOTS = path.join(BASE, 'shots');
const OUT = path.join(BASE, 'catalog-data.js');
const IMG = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp']);
const VID = new Set(['.mov', '.mp4', '.webm', '.m4v']);

// 既存カタログ読み込み（tags/group/note保持のため）
let old = { items: [] };
try {
  const t = fs.readFileSync(OUT, 'utf8');
  old = JSON.parse(t.replace(/^window\.CATALOG\s*=\s*/, '').replace(/;?\s*$/, ''));
} catch (e) { /* 初回は無くてよい */ }
const keep = new Map((old.items || []).map(i => [i.file, i]));

function dims(p) {
  try {
    const o = execFileSync('sips', ['-g', 'pixelWidth', '-g', 'pixelHeight', p], { encoding: 'utf8' });
    const w = +(o.match(/pixelWidth: (\d+)/) || [])[1] || 0;
    const h = +(o.match(/pixelHeight: (\d+)/) || [])[1] || 0;
    return { w, h };
  } catch (e) { return { w: 0, h: 0 }; }
}

const items = [];
if (fs.existsSync(SHOTS)) {
  for (const day of fs.readdirSync(SHOTS)) {
    const dayDir = path.join(SHOTS, day);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
    if (!fs.statSync(dayDir).isDirectory()) continue;
    for (const f of fs.readdirSync(dayDir)) {
      const ext = path.extname(f).toLowerCase();
      const kind = IMG.has(ext) ? 'image' : VID.has(ext) ? 'video' : null;
      if (!kind) continue;
      const rel = `shots/${day}/${f}`;
      const st = fs.statSync(path.join(dayDir, f));
      const prev = keep.get(rel) || {};
      const mtime = Math.round(st.mtimeMs);
      const changed = prev.mtime !== mtime; // クロップ等で更新されたら寸法を取り直す
      const it = {
        file: rel,
        date: day,
        time: prev.time || new Date(st.mtimeMs).toTimeString().slice(0, 8),
        kind,
        size: st.size,
        mtime,
        w: prev.w || 0,
        h: prev.h || 0,
        tags: prev.tags || [],
        group: prev.group || '',
        note: prev.note || '',
        ocr: prev.ocr || ''
      };
      if (prev.src) it.src = prev.src; // Snagit取り込み元（二重取り込み防止）
      if (kind === 'image' && (changed || !(it.w && it.h))) Object.assign(it, dims(path.join(dayDir, f)));
      items.push(it);
    }
  }
}

// 外部参照エントリ（絶対パス＝Snagit動画等）は実在すれば残す
for (const it of old.items || []) {
  if (it.file.startsWith('/') && fs.existsSync(it.file)) items.push(it);
}

// 新しい順（日付＋時刻の降順）
items.sort((a, b) => (b.date + b.time).localeCompare(a.date + a.time));

const data = { updated: new Date().toISOString().slice(0, 19).replace('T', ' '), items };
fs.writeFileSync(OUT, 'window.CATALOG=' + JSON.stringify(data, null, 1) + ';\n');
console.log(`カタログ更新: ${items.length}件`);
