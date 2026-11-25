// midi2g2 page <-> python/gui.py. Reading and converting happen in Python (midi2g2.py); this file only asks for them.
(function (root) {
'use strict';
const T = JSON.parse(document.getElementById('tpl').textContent);
const GRID_NAMES = { 2: '8ths', 3: '8th triplets', 4: '16ths', 6: '16th triplets', 8: '32nds', 12: '32nd triplets' };

async function call(path, body, query) {
  const r = await fetch(path + (query ? '?' + new URLSearchParams(query) : ''), {
    method: 'POST', body, headers: { 'Content-Type': query ? 'application/octet-stream' : 'application/json' } });
  if (!r.ok) {
    let msg = `The midi2g2 program answered ${r.status}.`;
    try { msg = (await r.json()).error || msg; } catch (e) { /* not JSON */ }
    const err = new Error(msg); err.status = r.status; throw err;
  }
  return r;
}
const SRC = new WeakMap();         // A -> the file it was read from, to send again if Python dropped it (410)
async function withSong(A, path, opts) {
  const body = () => JSON.stringify({ token: A.token, opts });
  try { return await call(path, body()); }
  catch (err) {
    if (err.status !== 410 || !SRC.has(A)) return failed(err);
    const s = SRC.get(A), again = await analyse(s.bytes, s.fileName, s.bends, s.song);
    A.token = again.token;           // same file, same reading: only the token is new
    return call(path, body()).catch(failed);
  }
}
function failed(err) {             // the Python program was stopped: say how to start it again
  if (err instanceof TypeError) throw new Error('Lost contact with midi2g2: start it again with  python python/gui.py  and reload this page.');
  throw err;
}

// file bytes -> lines found (and, for NSF / NSFe / SID, the song info)
async function analyse(bytes, fileName, bendsMode = 'main', song = null) {
  const q = { name: fileName, bends: bendsMode }; if (song !== null && song !== undefined) q.song = song;
  return (await call('/api/analyse', bytes, q).catch(failed)).json();
}
let lastA = null;
// the page asks for these right after analyse(): Python worked them out with the lines
function defaultPick(lines, parts) { return ((lastA && lastA.picks && lastA.picks[parts]) || []).map(id => lines[id]); }
function defaultSound(line, i, n) { return line.snd ? line.snd[n - 1][i] : 0; }
// the part of an item inside the section [a, b) beats, moved to start at 0 (for the preview player)
function clip(item, a, b) {
  const notes = item.notes.filter(([s]) => a - 1e-9 <= s && s < b - 1e-9)
    .map(([s, e, n, v, ch]) => [s - a, Math.min(e, b) - a, n, v, (ch || []).filter(([t]) => t < b).map(([t, n2]) => [t - a, n2])]);
  return Object.assign({}, item, { notes });
}
// slot choices -> length, grid, clock, report and the preview of what the G2 will play (no files yet: fast)
async function convert(T_, A, opts) {
  const r = await (await withSong(A, '/api/convert', opts)).json();
  r.opts = opts; return r;
}
// builds the files in Python and returns the zip
async function save(A, opts) {
  return new Uint8Array(await (await withSong(A, '/api/save', opts)).arrayBuffer());
}

root.M2G = {
  analyse: (bytes, fileName, bends = 'main', song = null) => analyse(bytes, fileName, bends, song).then(A => {
    SRC.set(A, { bytes, fileName, bends, song }); return (lastA = A);
  }),
  defaultPick, defaultSound, clip, convert, save, GRID_NAMES, GM_NAMES: T.gm,
};
})(window);
