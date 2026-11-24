"""Chord slots for midi2g2.

A chord slot plays a polyphonic track as up to 4 chord voices (lowest note .. top note). Each voice is its own chain
of 16-step SeqNotes driving its own oscillator; all oscillators share one filter and envelope (paraphonic).
Chord changes are quantized to a coarser "chord step" (1/16, 1 beat, 2 beats or 1 bar of the G2 clock), so a chord
slot covers much more time per sequencer than a melody.
Pitch path: sequencer -> oscillator Pitch input directly (no mixer, no track & hold). Keyboard transpose enters the
oscillator's PitchVar input, so it can't touch the notes while untransposed.
Gate: voice 1's second row = "chord sounding" (gate mode), voice 2's second row = "new chord" (trigger) for retriggering."""
import math
from g2lib import *

CHORD_STEPS = tuple(range(16, 0, -1))       # chord step length in grid steps: any 1..16 (the step-clock sequencer's length)
CHORD_SOUNDS = [  # name, waveform, shape, cutoff Hz, res, filter env amount, amp ADSR (ms, ms, level, ms), filter ADSR
    ('Warm Pad',      2, 0,  1800, 10, 12, (300, 900, 100, 1200), (400, 1500, 60, 1200)),
    ('Organ',         3, 0,  4500, 0,  0,  (5, 100, 127, 200),    (0, 100, 127, 200)),
    ('Strings',       2, 0,  3200, 4,  6,  (250, 600, 110, 900),  (200, 800, 90, 900)),
    ('E-Piano',       1, 0,  5000, 0,  10, (1, 1500, 30, 600),    (0, 600, 40, 600)),
    ('Brass',         2, 0,  900,  12, 40, (40, 300, 110, 300),   (60, 500, 60, 300)),
    ('Square Chords', 3, 0,  6000, 0,  0,  (1, 200, 100, 200),    (0, 100, 127, 200)),
    ('Pluck Chords',  2, 0,  700,  20, 50, (1, 900, 0, 500),      (0, 250, 0, 400)),
    ('Soft Sine',     0, 0,  8000, 0,  0,  (20, 400, 110, 700),   (0, 100, 127, 700)),
]

def is_chordal(track):
    """A track counts as chords when at least 30% of its notes start together with another note."""
    st = sorted(round(s * 32) for s, *_ in track['notes'])
    together = sum(1 for i, x in enumerate(st) if (i > 0 and st[i - 1] == x) or (i + 1 < len(st) and st[i + 1] == x))
    return len(st) >= 4 and together >= 0.3 * len(st)

def quantized(item, spb):
    out = []
    for s, e, n, *_ in item['notes']:
        a = int(round(s * spb)); out.append((a, max(a + 1, int(round(e * spb))), n))
    return out

def choose_chord_step(item, spb):
    """Largest chord step (in grid steps) that keeps >= 97% of chord starts and ends on a step."""
    q = quantized(item, spb); edges = [a for a, _, _ in q] + [b for _, b, _ in q]
    for k in CHORD_STEPS:
        if sum(x % k == 0 for x in edges) >= 0.97 * len(edges): return k
    return 1

def chord_steps(item, spb, k, total):
    """-> (voices K, list of K step lists [(note, row2)...] of length total//k, dropped notes).
    row2: voice 1 = sounding (gate), voice 2 = new chord (trigger); others 0."""
    n_steps = total // k
    q = [(int(round(a / k)), max(int(round(a / k)) + 1, int(round(b / k))), n) for a, b, n in quantized(item, spb)]
    sounding = [[] for _ in range(n_steps)]; onset = [0] * n_steps
    for A, B, n in q:
        if A >= n_steps: continue
        onset[A] = 1
        for s in range(A, min(B, n_steps)): sounding[s].append(n)
    most = max((len(set(x)) for x in sounding), default=1)
    K = min(4, max(2, most)); dropped = 0
    rows = [[] for _ in range(K)]
    prev = None
    for s in range(n_steps):
        ns = sorted(set(sounding[s]))
        if len(ns) > K: dropped += len(ns) - K; ns = ns[:1] + ns[-(K - 1):]       # keep the bass note and the top notes
        if ns:
            ns = [max(5, min(127, x)) for x in ns]
            v = [ns[i] if i < len(ns) else ns[-1] for i in range(K)]
            prev = v
        else:
            v = prev
        if v is None:                                                              # silence before the first chord
            first = next((sorted(set(x)) for x in sounding if x), [60])
            v = [first[i] if i < len(first) else first[-1] for i in range(K)]; v = [max(5, min(127, x)) for x in v][:K]
            v += [v[-1]] * (K - len(v))
        for i in range(K):
            r2 = (1 if ns else 0) if i == 0 else (onset[s] if (i == 1 and ns) else 0)
            rows[i].append((v[i], r2))
    return K, rows, dropped

def chord_synth(V, K, div=6, k=1):
    """Clock: ClkGen 1/96 -> ClkDiv (one pulse per grid step, like every other slot) -> a looping 'Chord Step'
    sequencer of length k with a trigger on its first step. Its trigger output is the chord clock: one pulse every
    k grid steps, starting exactly on the first grid step (it behaves like the melody sequencers)."""
    s = Stack(V, 0); s.label('CHORD CLOCK')
    clk = s.add('ClkGen', 'Master Clock', color=MC.yellow1); setp(clk.params.Source, 1); setp(clk.params.Active, 1)
    pu = s.add('Pulse', 'Start Pulse', color=MC.yellow1); setp(pu.params.Time, 10); setp(pu.params.Range, 0)
    dv = s.add('ClkDiv', 'Step Clock', color=MC.yellow1); setp(dv.params.Divider, div - 1); dv.modes[0].value = 0
    con(V, out(clk, 'ClkActive'), pu.inputs.In, YEL)
    con(V, out(clk, '1/96'), dv.inputs.Clk, YEL); con(V, pu.outputs.Out, dv.inputs.Rst, YEL)
    cs = s.add('SeqNote', 'Chord Step', color=MC.yellow1)
    for i in range(16): setp(getattr(cs.params, f'Seq1Step{i + 1}'), 64); setp(getattr(cs.params, f'Seq2Step{i + 1}'), 1 if i == 0 else 0)
    setp(cs.params.Loop, 1); setp(cs.params.Length, k - 1); setp(cs.params.TG, 0)
    con(V, dv.outputs.Out, cs.inputs.Clk, YEL); con(V, pu.outputs.Out, cs.inputs.Rst, YEL)
    g1 = s.add('Gate', 'Gate Logic A', color=MC.yellow1); g1.modes[0].value = 0; g1.modes[1].value = 3      # AND / NOR
    g2 = s.add('Gate', 'Gate Logic B', color=MC.yellow1); g2.modes[0].value = 0; g2.modes[1].value = 0
    tin = s.add('2-In', 'Transpose Bus1'); setp(tin.params.Source, 2); setp(tin.params.Active, 1); setp(tin.params.Pad, 2)
    con(V, out(clk, 'ClkActive'), g1.inputs.In1_2, YEL)
    con(V, g1.outputs.Out1, g2.inputs.In1_1, YEL); con(V, g1.outputs.Out2, g2.inputs.In1_2, YEL)
    y = Stack(V, 1); y.label('CHORD SYNTH')
    oscs = []
    for i in range(K):
        o = y.add('OscB', f'Chord Osc {i + 1}', color=MC.blue1); oscs.append(o)
        setp(o.params.Waveform, [x[1] for x in CHORD_SOUNDS]); setp(o.params.Shape, [x[2] for x in CHORD_SOUNDS])
        for p, v in (('FreqCoarse', 64), ('FreqFine', 64), ('FreqMode', 0), ('Kbt', 0), ('PitchMod', 127), ('Active', 1)):
            setp(getattr(o.params, p), v)
        con(V, tin.outputs.OutL, o.inputs.PitchVar, BLUE)
    mx = y.add('Mix4-1B', 'Chord Mix', color=MC.blue1)
    for i in range(4): setp(getattr(mx.params, f'Lev{i + 1}'), 100 if i < K else 0)
    setp(mx.params.ExpLin, 2)
    for i, o in enumerate(oscs): con(V, o.outputs.Out, getattr(mx.inputs, f'In{i + 1}'), RED)
    z = Stack(V, 2); z.label('FILTER AMP')
    fe = z.add('ModADSR', 'Filter Env', color=MC.green1); flt = z.add('FltClassic', 'Filter', color=MC.red1)
    amp = z.add('EnvADSR', 'Amp Env', color=MC.green1)
    o = z.add('2-Out', 'Main Out'); setp(o.params.Destination, 0); setp(o.params.Active, 1); setp(o.params.Pad, 0)
    snd = z.add('2-Out', 'Reverb Send B3'); setp(snd.params.Destination, 5); setp(snd.params.Active, 1); setp(snd.params.Pad, 0)
    setp(flt.params.Freq, [filter_freq(x[3]) for x in CHORD_SOUNDS]); setp(flt.params.Res, [x[4] for x in CHORD_SOUNDS])
    setp(flt.params.PitchMod, [x[5] for x in CHORD_SOUNDS]); setp(flt.params.Kbt, 0); setp(flt.params.Slope, 1); setp(flt.params.Active, 1)
    for env, idx in ((amp, 6), (fe, 7)):
        a, d, sl, r = zip(*[x[idx] for x in CHORD_SOUNDS])
        setp(env.params.Attack, [env_time(x) for x in a]); setp(env.params.Decay, [env_time(x) for x in d])
        setp(env.params.Sustain, list(sl)); setp(env.params.Release, [env_time(x) for x in r]); setp(env.params.OutputType, 0)
    setp(amp.params.Shape, 0)
    con(V, mx.outputs.Out, flt.inputs.In, RED); con(V, fe.outputs.Env, flt.inputs.PitchVar, BLUE)
    con(V, flt.outputs.Out, amp.inputs.In, RED)
    con(V, g2.outputs.Out1, amp.inputs.Gate, YEL); con(V, g2.outputs.Out1, fe.inputs.Gate, YEL)
    con(V, amp.outputs.Out, o.inputs.InL, RED); con(V, amp.outputs.Out, o.inputs.InR, RED); con(V, amp.outputs.Out, snd.inputs.InL, RED)
    return dict(clk=clk, pu=pu, step=cs, g1=g1, oscs=oscs, flt=flt, amp=amp, fe=fe, mx=mx)

def chord_patch(rows_bars, k, sound, path, last_len=16, loop=True, div=6, _hl=None):
    """rows_bars: K lists (one per voice) of n bars of 16 (note, row2) steps. k: chord step in grid steps."""
    K, n = len(rows_bars), len(rows_bars[0])
    pch2, P = new_patch(voices=1, mode='mono'); V = P.voice
    sy = chord_synth(V, K, div, k)
    if _hl is not None: setp(sy['step'].params.Length, _hl)       # template generator only: marks the Length field
    clk_out = sy['step'].outputs.Trig
    col = 3
    for vi, bars in enumerate(rows_bars):
        seqs = []
        for b, steps in enumerate(bars):
            if b % 12 == 0: st = Stack(V, col); col += 1
            s = st.add('SeqNote', f'V{vi + 1} Bar {b + 1}', color=MC.red1 if b == 0 else MC.yellow1)
            for i, (nt, r2) in enumerate(steps):
                setp(getattr(s.params, f'Seq1Step{i + 1}'), nt); setp(getattr(s.params, f'Seq2Step{i + 1}'), r2)
            setp(s.params.Loop, 0); setp(s.params.Length, (last_len if b == n - 1 else 16) - 1)
            setp(s.params.TG, 1 if vi == 0 else 0)
            con(V, clk_out, s.inputs.Clk, YEL)
            if b == 0: con(V, sy['pu'].outputs.Out, s.inputs.Rst, YEL)
            else:
                p = seqs[-1]; con(V, sy['pu'].outputs.Out, s.inputs.Park, YEL)
                con(V, p.outputs.Link, s.inputs.Rst, YEL); con(V, p.outputs.Note, s.inputs.Note, BLUE); con(V, p.outputs.Trig, s.inputs.Trig, YEL)
            seqs.append(s)
        if loop: con(V, seqs[-1].outputs.Link, seqs[0].inputs.Loop, YEL)
        con(V, seqs[-1].outputs.Note, sy['oscs'][vi].inputs.Pitch, BLUE)
        if vi == 0: con(V, seqs[-1].outputs.Trig, sy['g1'].inputs.In1_1, YEL)
        if vi == 1: con(V, seqs[-1].outputs.Trig, sy['g1'].inputs.In2_1, YEL)
    P.description.variation = sound
    knobs(P, 'A1', [sy['flt'].params.Freq, sy['flt'].params.Res, sy['flt'].params.PitchMod, sy['amp'].params.Attack,
                    sy['amp'].params.Decay, sy['amp'].params.Sustain, sy['amp'].params.Release, P.settings.patchvol])
    knobs(P, 'A2', [sy['fe'].params.Attack, sy['fe'].params.Decay, sy['fe'].params.Sustain, sy['fe'].params.Release,
                    None, None, None, None])
    cc(P, 74, sy['flt'].params.Freq); cc(P, 71, sy['flt'].params.Res); cc(P, 73, sy['amp'].params.Attack); cc(P, 72, sy['amp'].params.Release)
    setp(P.settings.patchvol, 90)
    set_text(P, f'midi2g2 chord slot: {K} chord voices, {n} sequencers per voice. The Chord Step sequencer sets how many '
                'grid steps one chord step lasts (its length). '
                'Each voice: sequencers -> its own oscillator (no mixer in the pitch path); shared filter and envelope. '
                'Variations = sounds: ' + ', '.join(f'{i + 1} {x[0]}' for i, x in enumerate(CHORD_SOUNDS)) +
                '. A1: cutoff, res, filter env, amp A D S R, volume. A2: filter env ADSR.')
    return save(pch2, path), sy

_CAP = {}
def chord_capacity(K, budget=115):
    """SeqNotes per chord voice in the voice area."""
    if K not in _CAP:
        _, P = new_patch(voices=1, mode='mono'); chord_synth(P.voice, K)
        fixed = sum(len(m.outputs) for m in P.voice.modules)
        _CAP[K] = (budget - fixed) // 3 // K
    return _CAP[K]
