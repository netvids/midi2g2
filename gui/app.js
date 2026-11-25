(function(){
'use strict';
const T = JSON.parse(document.getElementById('tpl').textContent);
const $ = id => document.getElementById(id);
const SLOT = ['A','B','C','D'], SLOTVAR = ['--red','--yellow','--blue','--green'];
let A = null, fileBytes = null, fileName = '', chainMode = false, parts = 3, assign = new Map(), soundByLine = new Map(), last = null, downloads;
let playing = null;                                   // 'file' | 'sel' | 'slots' | 'row:<id>'
let range = null, playBeat = null;                    // section [from, to) in beats (null = whole song); playhead position in beats
const ICON_PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>';
const ICON_STOP = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3.5" width="9" height="9" rx="1" fill="currentColor"/></svg>';
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
function tempo() { return parseFloat($('bpm').value) || A.bpm; }
function setBtn(b, on, label) { (b.querySelector('.pi') || b).innerHTML = on ? ICON_STOP : ICON_PLAY; b.setAttribute('aria-pressed', on); b.setAttribute('aria-label', (on ? 'Stop ' : 'Play ') + label); b.title = (on ? 'Stop ' : 'Play ') + label; }
function refreshButtons() {
  document.querySelectorAll('[data-play]').forEach(b => setBtn(b, b.dataset.play === playing, b.dataset.label));
  document.querySelectorAll('.line').forEach(r => r.classList.toggle('playing', 'row:' + r.dataset.id === playing));
}
function startPlay(key, events, fromBeat = 0) {
  if (playing === key) { M2GPlayer.stop(false); return; }
  if (!events.length) return;
  M2GPlayer.stop(false);                              // ends the previous preview (its end callback clears the state)
  playing = key; refreshButtons(); const bps = tempo() / 60;
  M2GPlayer.play(events, {
    tick: (pos, len) => { $('ptime').textContent = `${fmt(pos)} / ${fmt(len)}`; playBeat = fromBeat + pos * bps; drawOverview(); },
    end: () => { playing = null; playBeat = null; $('ptime').textContent = ''; refreshButtons(); drawOverview(); },
  });
}
const secStart = () => range ? range[0] : 0;
const inSection = l => range ? M2G.clip(l, range[0], range[1]) : l;
function playFile() { startPlay('file', A.lines.filter(l => l.kind === 'line').flatMap(l => M2GPlayer.fromNotes(l, tempo()))); }
function playSelected() { startPlay('sel', chosenIds().flatMap(id => M2GPlayer.fromNotes(inSection(A.lines[id]), tempo())), secStart()); }
function playSlots() { if (last) startPlay('slots', M2GPlayer.fromPreview(last.preview), secStart()); }
function playRow(l) { startPlay('row:' + l.id, M2GPlayer.fromNotes(l, tempo())); }

// ---- section: which bars of the song to convert
const bpb = () => A.beatsPerBar || 4;
const totalBars = () => Math.max(1, Math.ceil(A.endBeat / bpb() - 1e-9));
function setSection(fromBar, toBar, redraw = true) {          // bars are 1-based, toBar inclusive
  const n = totalBars(); fromBar = Math.min(n, Math.max(1, Math.round(fromBar) || 1)); toBar = Math.min(n, Math.max(fromBar, Math.round(toBar) || n));
  range = (fromBar === 1 && toBar === n) ? null : [(fromBar - 1) * bpb(), toBar * bpb()];
  $('barFrom').value = fromBar; $('barTo').value = toBar; $('barFrom').max = n; $('barTo').max = n;
  const secs = b => fmt(b * 60 / tempo());
  $('secText').textContent = range ? `Bars ${fromBar} to ${toBar} of ${n} (${secs(range[0])} to ${secs(Math.min(range[1], n * bpb()))})` : `Whole song: ${n} bars (${secs(A.endBeat)})`;
  $('secReset').classList.toggle('hidden', !range);
  drawOverview();
  if (redraw) { if (playing === 'sel') M2GPlayer.stop(false); render(); }
}
function sectionBars() { return range ? [range[0] / bpb() + 1, range[1] / bpb()] : [1, totalBars()]; }
function drawOverview() {
  const cv = $('overview'); if (!A || !cv) return;
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1; if (!r.width) return;
  cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
  const g = cv.getContext('2d'), W = cv.width, H = cv.height, css = getComputedStyle(document.documentElement), col = v => css.getPropertyValue(v).trim();
  const len = totalBars() * bpb(); let lo = 127, hi = 0;
  for (const l of A.lines) if (l.kind === 'line') for (const nt of l.notes) { lo = Math.min(lo, nt[2]); hi = Math.max(hi, nt[2]); }
  const span = Math.max(12, hi - lo), top = 14 * dpr, nh = Math.max(1.5 * dpr, (H - top) / (span + 1));
  const slotOf = new Map(); for (const [id, s] of assign) { const it = A.lines[id]; if (!it) continue; if (it.kind === 'line') slotOf.set(id, s); else for (const x of A.lines) if (x.kind === 'line' && x.tid === it.tid) slotOf.set(x.id, s); }
  for (const pass of [0, 1]) for (const l of A.lines) {
    if (l.kind !== 'line' || slotOf.has(l.id) !== !!pass) continue;
    g.fillStyle = pass ? col(SLOTVAR[slotOf.get(l.id)]) : col('--muted'); g.globalAlpha = pass ? 1 : 0.45;
    for (const [s, e, n] of l.notes) g.fillRect(s / len * W, top + (H - top) - (n - lo + 1) / (span + 1) * (H - top), Math.max(dpr, (e - s) / len * W - dpr * 0.3), nh);
  }
  g.globalAlpha = 1;
  // bar ruler
  const n = totalBars(), every = [1, 2, 4, 8, 16, 32, 64].find(k => n / k <= 14) || 128;
  g.fillStyle = col('--muted'); g.font = `${11 * dpr}px Barlow, sans-serif`; g.textBaseline = 'top';
  for (let b = 0; b < n; b += every) { const x = b / n * W; g.globalAlpha = 0.35; g.fillRect(x, 0, dpr, H); g.globalAlpha = 1; g.fillText(String(b + 1), x + 3 * dpr, 1 * dpr); }
  // section shading and handles
  const [f, t] = sectionBars(), x0 = (f - 1) / n * W, x1 = t / n * W;
  g.fillStyle = col('--bg'); g.globalAlpha = 0.72; g.fillRect(0, 0, x0, H); g.fillRect(x1, 0, W - x1, H); g.globalAlpha = 1;
  g.fillStyle = col('--ink');
  for (const x of [x0, x1]) { g.fillRect(Math.min(W - 3 * dpr, Math.max(0, x - 1.5 * dpr)), 0, 3 * dpr, H); g.fillRect(Math.min(W - 9 * dpr, Math.max(0, x - 4.5 * dpr)), H / 2 - 9 * dpr, 9 * dpr, 18 * dpr); }
  if (playBeat !== null) { g.fillStyle = col('--red'); g.fillRect(playBeat / len * W, 0, 2 * dpr, H); }
}
(function wireOverview() {
  const cv = $('overview'); let drag = null;
  const barAt = e => { const r = cv.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * totalBars(); };
  const move = e => {
    const b = barAt(e); let [f, t] = sectionBars();
    if (drag === 'from') f = Math.min(t, Math.floor(b + 0.5) + 1); else t = Math.max(f, Math.max(1, Math.round(b)));
    setSection(f, t, false);
  };
  cv.addEventListener('pointerdown', e => {
    if (!A) return; const b = barAt(e), [f, t] = sectionBars();
    drag = Math.abs(b - (f - 1)) <= Math.abs(b - t) ? 'from' : 'to'; cv.setPointerCapture(e.pointerId); move(e);
  });
  cv.addEventListener('pointermove', e => { if (drag) move(e); });
  const done = () => { if (drag) { drag = null; if (playing === 'sel' || playing === 'slots') M2GPlayer.stop(false); render(); } };
  cv.addEventListener('pointerup', done); cv.addEventListener('pointercancel', done);
  $('barFrom').addEventListener('change', () => setSection(+$('barFrom').value, Math.max(+$('barFrom').value, +$('barTo').value)));
  $('barTo').addEventListener('change', () => setSection(Math.min(+$('barFrom').value, +$('barTo').value), +$('barTo').value));
  $('secReset').addEventListener('click', () => setSection(1, totalBars()));
  window.addEventListener('resize', drawOverview);
})();

downloads = null;                                     // the Save button hands the zip to the browser as a normal download

const drop = $('drop'), pick = $('pick');
drop.addEventListener('click', () => pick.click());
drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick.click(); } });
['dragenter','dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave','drop'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) load(f); });
pick.addEventListener('change', () => { if (pick.files[0]) load(pick.files[0]); pick.value = ''; });
$('another').addEventListener('click', () => pick.click());
document.querySelectorAll('#mode button').forEach(b => b.addEventListener('click', () => {
  chainMode = b.dataset.parts === 'chain'; parts = chainMode ? 1 : +b.dataset.parts;
  document.querySelectorAll('#mode button').forEach(x => x.setAttribute('aria-pressed', x === b));
  $('modeHelp').textContent = chainMode ? 'One track plays through slot A, then B, C and D: up to 4 × 29 bars in one performance. Plays once; no transpose or reverb (the buses carry the hand-over).'
    : parts === 3 ? 'Slot D plays nothing itself: it transposes everything from the keyboard and adds reverb.'
    : 'All four slots play a part. No keyboard transpose and no reverb.';
  if (chainMode) {                                          // keep one single-note line: the chosen one, else the busiest
    const cur = chosenIds().map(i => A && A.lines[i]).find(l => l && l.kind === 'line');
    const best = cur || (A && A.lines.filter(l => l.kind === 'line').sort((x, y) => y.notes.length - x.notes.length)[0]);
    assign = new Map(best ? [[best.id, 0]] : []);
  } else for (const [id, s] of [...assign]) if (s >= parts) assign.delete(id);
  if (A) { compact(); render(); }
}));
$('grid').addEventListener('change', update);
$('bends').addEventListener('change', async () => {      // re-read the file; keep slot and sound choices by line name
  if (!fileBytes) return;
  const keepSlot = new Map([...assign].map(([id, s]) => [A.lines[id].name, s]));
  const keepSnd = new Map([...soundByLine].map(([id, s]) => [A.lines[id].name, s]));
  M2GPlayer.stop(false);
  try { A = await M2G.analyse(fileBytes, fileName, $('bends').value, A.nsf ? A.nsf.song : null); }
  catch (err) { A = null; showError(err.message || String(err)); return; }
  assign = new Map(); soundByLine = new Map();
  for (const l of A.lines) { if (keepSlot.has(l.name)) assign.set(l.id, keepSlot.get(l.name)); if (keepSnd.has(l.name)) soundByLine.set(l.id, keepSnd.get(l.name)); }
  compact(); render();
});
$('bpm').addEventListener('input', () => { update(); if (A) { const [f, t] = sectionBars(); setSection(f, t, false); } });

function load(file) {
  file.arrayBuffer().then(buf => { fileBytes = new Uint8Array(buf); fileName = file.name; openSong(null); });
}
// read the loaded file (for an NSF: the given song, null = its starting song) and start with a fresh selection
async function openSong(song) {
  M2GPlayer.stop(false);                                // stop any preview of the previous file BEFORE its data is replaced
  assign = new Map(); soundByLine = new Map(); range = null; last = null;
  try { A = await M2G.analyse(fileBytes, fileName, $('bends').value, song); }
  catch (err) { A = null; showError(err.message || String(err)); return; }
  if (!A.lines.length && !A.nsf) { A = null; showError('No pitched notes found in this file (drum tracks on channel 10 are skipped).'); return; }
  if (chainMode) { const best = A.lines.filter(l => l.kind === 'line').sort((x, y) => y.notes.length - x.notes.length)[0]; if (best) assign.set(best.id, 0); }
  else M2G.defaultPick(A.lines, parts).forEach((l, i) => assign.set(l.id, i));
  $('bpm').value = Math.round(A.bpm * 10) / 10;
  const n = A.nsf;
  $('fname').textContent = A.fileName + (n && n.title ? ` (${n.title})` : '');
  $('songField').classList.toggle('hidden', !n); $('bendField').classList.toggle('hidden', !!n);
  if (n) {
    const sel = $('song');
    if (song === null || sel.options.length !== n.songs) {       // a new file: rebuild the list (NSFe files can name their songs)
      sel.textContent = '';
      for (let k = 1; k <= n.songs; k++) { const o = document.createElement('option'); o.value = k; o.textContent = n.labels && n.labels[k - 1] ? `${k}. ${n.labels[k - 1]}` : `Song ${k}`; sel.appendChild(o); }
    }
    sel.value = n.song;
    $('songHelp').textContent = `${n.songs} song${n.songs > 1 ? 's' : ''} in this file` + (n.artist ? `, by ${n.artist}` : '') + '. ' +
      (!A.lines.length ? 'This one has no pitched notes (a sound effect, a drum-only cue, or a tune this reader can’t run).'
        : n.loopEnd ? 'The song loops: one full pass was read.' : (n.times && n.times[n.song - 1] > 0) ? 'The song was read to the length stored in the file. Use the section to pick a part.' : 'No loop was found, so the first 4 minutes were read. Use the section to pick a part.') +
      (n.chip !== 'sid' && (n.chips & 3) ? ` Extra sound chip channels are read too (${['VRC6', 'VRC7'].filter((_, k) => n.chips & (1 << k)).join(', ')}).` : '') +
      (n.chip !== 'sid' && (n.chips & ~3) ? ` This file also uses ${['', '', 'FDS', 'MMC5', 'Namco 163', 'Sunsoft 5B'].filter((x, k) => x && n.chips & (1 << k)).join(', ') || 'another sound chip'}, whose channels are not read, so parts may be missing.` : '') +
      (n.chip === 'sid' ? ' The tempo is estimated from the notes; noise drums are skipped and fast arpeggios become single notes.'
                        : ' The tempo is estimated from the notes; noise and sample drums are skipped.');
  }
  drop.classList.add('hidden'); $('work').classList.remove('hidden'); $('bar').classList.remove('hidden');
  setSection(1, totalBars(), false);
  render();
}
$('song').addEventListener('change', () => { if (fileBytes) openSong(+$('song').value); });
function showError(msg) {
  drop.classList.remove('hidden'); $('work').classList.add('hidden'); $('bar').classList.add('hidden');
  drop.querySelector('span').textContent = msg + ' Choose another file.';
}
function compact() {
  const order = [...assign].sort((a, b) => a[1] - b[1]); assign = new Map(order.map(([id], i) => [id, i]));
}
function chosenIds() { return [...assign].sort((a, b) => a[1] - b[1]).map(([id]) => id); }
function defaultSound(id) {
  const ids = chosenIds(), i = ids.indexOf(id), l = A.lines[id];
  if (chainMode) return l.program == null ? (l.avg < 55 ? 7 : 0) : M2G.defaultSound(l, 0, 1);
  return M2G.defaultSound(l, i, ids.length);
}
function soundOf(id) { return soundByLine.has(id) ? soundByLine.get(id) : defaultSound(id); }

function setSlot(id, s) {
  const cur = assign.get(id);
  if (cur === s) { assign.delete(id); compact(); render(); return; }
  for (const [other, os] of assign) if (os === s && other !== id) { if (cur === undefined) assign.delete(other); else assign.set(other, cur); }
  assign.set(id, s); compact(); render();
}

function render() {
  const box = $('lines'); box.textContent = '';
  let tEnd = 0, pLo = 127, pHi = 0;
  for (const l of A.lines) for (const [s, e, n] of l.notes) { tEnd = Math.max(tEnd, e); pLo = Math.min(pLo, n); pHi = Math.max(pHi, n); }
  const nChords = A.lines.filter(l => l.kind === 'chords').length;
  $('linesHelp').textContent = `${A.lines.length - nChords} mono line${A.lines.length - nChords === 1 ? '' : 's'}` + (nChords ? ` and ${nChords} chord track${nChords > 1 ? 's' : ''}` : '') + ` found. ` + (chainMode ? 'Pick the one line to play across slots A to D.' : `Give up to ${parts} of them a slot.`) + (nChords ? ' A chord track plays its chords in one slot; its split lines are there too if you’d rather use single notes.' : '');
  const mk = list => list.map((s, i) => `<option value="${i}">${i + 1} ${s}</option>`).join('');
  const opts = mk(T.sounds), chordOpts = mk(T.chord_sounds);
  for (const l of A.lines) {
    const s = assign.get(l.id), on = s !== undefined;
    const row = document.createElement('div'); row.className = 'line' + (on ? ' on' : '');
    if (on) { row.style.setProperty('--c', `var(${SLOTVAR[s]})`); row.style.setProperty('--mc', `var(--mod${SLOT[s]})`); }
    const sp = document.createElement('div'); sp.className = 'slotpick'; sp.setAttribute('role', 'group'); sp.setAttribute('aria-label', 'Slot for ' + l.name);
    if (chainMode) {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = 'A→D'; b.className = 'wide';
      b.style.setProperty('--c', 'var(--red)'); b.setAttribute('aria-pressed', s === 0); b.disabled = l.kind !== 'line';
      b.title = l.kind !== 'line' ? 'Chord items can’t be chained' : s === 0 ? 'Remove' : 'Play this line across slots A to D';
      b.addEventListener('click', () => { assign = new Map(s === 0 ? [] : [[l.id, 0]]); render(); }); sp.appendChild(b);
    }
    for (let k = 0; k < (chainMode ? 0 : parts); k++) {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = SLOT[k];
      b.style.setProperty('--c', `var(${SLOTVAR[k]})`); if (k === 1) b.style.setProperty('--fg', '#1B1E21'); b.setAttribute('aria-pressed', s === k);
      b.title = s === k ? `Remove from slot ${SLOT[k]}` : `Play in slot ${SLOT[k]}`;
      b.addEventListener('click', () => setSlot(l.id, k)); sp.appendChild(b);
    }
    const meta = document.createElement('div'); meta.className = 'meta';
    const head = document.createElement('div'); head.className = 'nmrow';
    const pb = document.createElement('button'); pb.type = 'button'; pb.className = 'pbtn'; pb.dataset.play = 'row:' + l.id; pb.dataset.label = l.name;
    pb.addEventListener('click', () => playRow(l));
    const nm = document.createElement('div'); nm.className = 'nm'; nm.textContent = l.name; head.append(pb, nm);
    const sub = document.createElement('div'); sub.className = 'sub';
    sub.textContent = (l.program != null ? M2G.GM_NAMES[l.program] + ' · ' : '') + (l.kind === 'chords' ? 'Chords: ' : '') + `${l.notes.length} notes, ${noteName(Math.min(...l.notes.map(x => x[2])))} to ${noteName(Math.max(...l.notes.map(x => x[2])))}`;
    const cv = document.createElement('canvas'); cv.className = 'roll';
    meta.append(head, sub, cv); row.dataset.id = l.id;
    const sd = document.createElement('div'); sd.className = 'snd';
    const sel = document.createElement('select'); sel.innerHTML = l.kind === 'chords' ? chordOpts : opts; sel.disabled = !on; sel.value = soundOf(l.id);
    sel.setAttribute('aria-label', 'Starting sound for ' + l.name);
    sel.addEventListener('change', () => { soundByLine.set(l.id, +sel.value); update(); });
    sd.appendChild(sel);
    row.append(sp, meta, sd); box.appendChild(row);
    const lo = Math.min(...l.notes.map(x => x[2])), hi = Math.max(...l.notes.map(x => x[2])), mid = (lo + hi) / 2, half = Math.max(6, (hi - lo) / 2);
    requestAnimationFrame(() => drawRoll(cv, l, tEnd, Math.floor(mid - half), Math.ceil(mid + half), on ? SLOTVAR[s] : '--muted'));
  }
  update(); refreshButtons(); requestAnimationFrame(drawOverview);
  $('playSel').disabled = !chosenIds().length;
}
function noteName(n) { return ['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B'][n % 12] + (Math.floor(n / 12) - 1); }
function drawRoll(cv, l, tEnd, lo, hi, colVar) {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = Math.max(1, Math.round(r.width * dpr)); cv.height = Math.round(r.height * dpr);
  const g = cv.getContext('2d'), W = cv.width, H = cv.height, span = Math.max(1, hi - lo);
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(colVar).trim() || '#888';
  const nh = Math.max(2 * dpr, H / (span + 1));
  for (const [s, e, n] of l.notes) {
    const x = s / tEnd * W, w = Math.max(dpr, (e - s) / tEnd * W - dpr * .5), y = H - (n - lo + 1) / (span + 1) * H;
    g.globalAlpha = (range && (s < range[0] - 1e-9 || s >= range[1] - 1e-9)) ? 0.25 : 1;      // outside the section: dimmed
    g.fillRect(x, y, w, nh);
  }
}

function options() {
  const ids = chosenIds();
  return { parts, chain: chainMode, pick: ids, grid: +$('grid').value || null, sound: ids.map(soundOf), bpm: parseFloat($('bpm').value) || null, range };
}
let convSeq = 0;                                      // only the answer to the latest change is shown
function update() {
  if (playing === 'slots') M2GPlayer.stop(false);
  const ids = chosenIds(), facts = $('facts'), sum = $('summary'), seq = ++convSeq, forA = A;
  if (!ids.length) { last = null; facts.innerHTML = '<div><b>No slots</b><span>Give a line a slot to convert it</span></div>'; sum.textContent = ''; refreshSave(); return; }
  last = null; refreshSave();
  M2G.convert(T, A, options()).then(r => { if (seq === convSeq && forA === A) { last = r; showResult(r, ids); } },
    err => { if (seq !== convSeq || forA !== A) return; last = null; sum.innerHTML = ''; facts.innerHTML = `<div><b>Can’t convert</b><span>${esc(err.message)}</span></div>`; refreshSave(); });
}
function showResult(r, ids) {
  const facts = $('facts'), sum = $('summary'), mm = `${Math.floor(r.secs / 60)}:${String(Math.floor(r.secs % 60)).padStart(2, '0')}`;
  facts.innerHTML = [[mm, 'length'], [M2G.GRID_NAMES[r.spb], 'grid'], [r.g2bpm, 'G2 clock BPM'], [r.nperf, r.nperf > 1 ? 'performances' : 'performance']]
    .map(([b, s]) => `<div><b>${esc(String(b))}</b><span>${esc(s)}</span></div>`).join('');
  const hasC = ids.some(i => A.lines[i].kind === 'chords');
  const left = A.lines.filter(l => !ids.includes(l.id) && !(l.in_chords && hasC)).length;
  $('bpmHelp').textContent = `The G2 master clock is set to ${r.g2bpm} BPM. Sync Ableton at ${r.g2bpm}.`;
  sum.innerHTML = (r.chain
      ? `<p>${r.nbars} bars of 16 steps, played through ${r.used.map(n => 'ABCD'.slice(0, n).split('').join('→')).join(', then ')}${r.nperf > 1 ? ` (${r.nperf} performances)` : ''}, up to ${T.chain_capacity} bars per slot.</p>`
      : `<p>${r.nbars} bars of 16 steps${r.nperf > 1 ? `, split into ${r.nperf} performances of up to ${r.perPerf} bars` : ''}.</p>`) +
    r.report.filter(x => x.includes(' chords, one step')).map(x => `<p>${esc(x.replace(/ \(starts.*$/, ''))}.</p>`).join('') +
    (left ? `<p>${left} item${left > 1 ? 's' : ''} without a slot won’t be played.</p>` : '') +
    r.report.filter(x => x.includes('merged')).map(x => `<p class="warn">${esc(x)}: notes closer than one grid step. A finer grid keeps them.</p>`).join('') +
    r.warnings.map(w => `<p class="warn">${esc(w)}</p>`).join('');
  refreshSave();
}
function esc(s) { return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

function refreshSave() {
  const b = $('save'), st = $('saveStatus');
  b.disabled = !last || downloads === undefined; if (!st.dataset.keep) st.textContent = '';
}
$('save').addEventListener('click', async () => {
  if (!last || downloads === undefined) return;
  const st = $('saveStatus'), folder = `${A.name} G2`, b = $('save');
  let data;
  b.disabled = true; st.textContent = 'Building the G2 files…';
  try { data = await M2G.save(A, last.opts); }
  catch (err) { st.textContent = err.message || String(err); return; }
  finally { b.disabled = false; }
  if (!downloads) {                                     // browser download
    try {
      const url = URL.createObjectURL(new Blob([data], { type: 'application/zip' })), a = document.createElement('a');
      a.href = url; a.download = `${folder}.zip`; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000); st.textContent = 'Download started.';
    } catch (e) { st.textContent = 'Saving didn’t work in this view. Open the midi2g2 page from its link instead.'; }
    return;
  }
  try { await downloads.save({ filename: `${folder}.zip`, data: new Blob([data]) }); st.textContent = 'Saved.'; }
  catch (e) { st.textContent = e && e.code === 'declined' ? 'Not saved.' : e && e.code === 'rate_limited' ? 'A save is already waiting: answer it first.' : 'Saving didn’t work here.'; }
});
$('playFile').addEventListener('click', playFile);
$('playSel').addEventListener('click', playSelected);
$('playSlots').addEventListener('click', playSlots);
})();
