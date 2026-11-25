// midi2g2 preview player: Web Audio, equal temperament (A4 = 440 Hz, like the G2).
(function (root) {
'use strict';
let ctx = null, master = null, timer = null, events = [], ptr = 0, t0 = 0, length = 0, onTick = null, onEnd = null, live = [];
const hz = n => 440 * Math.pow(2, (n - 69) / 12);
function ensure() {
  if (ctx) return ctx;
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -14; comp.ratio.value = 4;
  master = ctx.createGain(); master.gain.value = 0.7; master.connect(comp); comp.connect(ctx.destination);
  return ctx;
}
// voice styles: lead, bass, chords
const STYLE = {
  lead:   { wave: 'triangle', cut: 5000, gain: 0.22, rel: 0.06 },
  bass:   { wave: 'sawtooth', cut: 900,  gain: 0.20, rel: 0.06 },
  chords: { wave: 'sawtooth', cut: 1600, gain: 0.08, rel: 0.25 },
};
function voice(ev) {
  const st = STYLE[ev.style] || STYLE.lead, start = t0 + ev.t, end = t0 + ev.t + Math.max(0.03, ev.d), rel = ev.rel !== undefined ? ev.rel : st.rel;
  const o = ctx.createOscillator(), f = ctx.createBiquadFilter(), g = ctx.createGain();
  o.type = st.wave; o.frequency.setValueAtTime(hz(ev.n), start); f.type = 'lowpass'; f.frequency.value = st.cut;
  for (const [dt, n2] of ev.ch || []) o.frequency.setValueAtTime(hz(n2), start + dt);   // pitch changes (pitch bend), no new attack
  g.gain.setValueAtTime(0, start); g.gain.linearRampToValueAtTime(st.gain, start + 0.006);
  g.gain.setValueAtTime(st.gain, end); g.gain.linearRampToValueAtTime(0, end + rel);
  o.connect(f); f.connect(g); g.connect(master); o.start(start); o.stop(end + rel + 0.02);
  live.push(o); o.onended = () => { const i = live.indexOf(o); if (i >= 0) live.splice(i, 1); };
}
function tick() {
  const now = ctx.currentTime;
  while (ptr < events.length && t0 + events[ptr].t < now + 0.2) voice(events[ptr++]);
  const pos = now - t0; if (onTick) onTick(Math.min(pos, length), length);
  if (pos > length + 0.4) stop(true);
}
function play(evs, cb) {
  stop(false); ensure(); if (ctx.state === 'suspended') ctx.resume();
  events = evs.slice().sort((a, b) => a.t - b.t); ptr = 0;
  length = events.reduce((m, e) => Math.max(m, e.t + e.d), 0);
  t0 = ctx.currentTime + 0.08; onTick = cb.tick; onEnd = cb.end;
  timer = setInterval(tick, 25); tick();
}
function stop(ended) {
  if (timer) { clearInterval(timer); timer = null; }
  if (ctx) for (const o of live.slice()) { try { o.stop(); } catch (e) {} }
  live = []; events = [];
  const cb = onEnd; onEnd = null; onTick = null; if (cb) cb(ended);
}
// ---- event builders
// one line = one monophonic voice: a note's release never rings into the next note of the same line
function mono(evs) {
  const s = evs.slice().sort((a, b) => a.t - b.t);
  for (let i = 0; i + 1 < s.length; i++) {
    const nx = s[i + 1].t, st = STYLE[s[i].style] || STYLE.lead;
    if (nx < s[i].t + s[i].d) s[i].d = Math.max(0.02, nx - s[i].t);
    s[i].rel = Math.max(0.008, Math.min(st.rel, nx - (s[i].t + s[i].d)));
  }
  return s;
}
const styleOf = item => item.kind === 'chords' ? 'chords' : (item.avg < 55 ? 'bass' : 'lead');
function fromNotes(item, bpm) {           // original MIDI notes (beats -> seconds)
  const spb = 60 / bpm, style = styleOf(item);
  const evs = item.notes.map(([s, e, n, , ch]) => ({ t: s * spb, d: (e - s) * spb, n, style, ch: (ch || []).map(([t, n2]) => [(t - s) * spb, n2]) }));
  return item.kind === 'chords' ? evs : mono(evs);
}
function fromLineSteps(steps, sec, style) { // converted melody: note starts on trig, ends at next trig or rest
  const out = [];
  for (let i = 0; i < steps.length; i++) {
    if (!steps[i][1]) continue;
    let j = i + 1; const ch = [];
    while (j < steps.length && !steps[j][1] && steps[j][0] !== 0) { if (steps[j][0] !== steps[j - 1][0]) ch.push([(j - i) * sec, steps[j][0]]); j++; }
    out.push({ t: i * sec, d: (j - i) * sec, n: steps[i][0], style, ch });
  }
  return mono(out);
}
function fromChordRows(rows, sec) {        // converted chords: voice 1 row 2 = sounding, voice 2 row 2 = new chord
  const out = [], n = rows[0].length; let prevGate = 0;
  for (let s = 0; s < n; s++) {
    const gate = rows[0][s][1], onset = rows[1][s][1];
    if (gate && (onset || !prevGate)) {
      let j = s + 1; while (j < n && rows[0][j][1] && !rows[1][j][1]) j++;
      const notes = [...new Set(rows.map(r => r[s][0]))];
      for (const nt of notes) out.push({ t: s * sec, d: (j - s) * sec, n: nt, style: 'chords' });
    }
    prevGate = gate;
  }
  return out;
}
function fromPreview(pv) {
  const grid = 60 / pv.bpm / pv.spb, out = [];
  for (const p of pv.parts) {
    if (p.kind === 'chords') out.push(...fromChordRows(p.rows, grid * p.k));
    else out.push(...fromLineSteps(p.steps, grid, p.avg < 55 ? 'bass' : 'lead'));
  }
  return out;
}
root.M2GPlayer = { play, stop, fromNotes, fromPreview };
})(window);
