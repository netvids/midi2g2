#!/usr/bin/env python3
"""midi2g2 - convert a MIDI file into a Nord Modular G2 performance (.prf2) that plays the whole piece.

    python midi2g2.py song.mid                      # writes ./song G2/ next to the MIDI file
    python midi2g2.py song.mid --list               # show the mono lines found, then stop
    python midi2g2.py song.mid --pick 0,2,3 --out "My Song G2"
    python midi2g2.py song.mid --parts 4            # 4 parts, no control/reverb slot
    python midi2g2.py song.mid --grid 4 --sound 5   # force 16ths, warm-saw sound on every slot

How it works: every track is split into monophonic lines; the busiest lines become slots A-C (or A-D).
Each slot stores its line in chained 16-step SeqNotes (one per 16 steps): up to 36 in the voice area,
the rest in the FX area next to the synth voice. Rest steps hold a "no note" value, so note lengths,
legato and rests are kept. Slot D (default) = keyboard transpose + reverb. Pieces longer than one
performance are split into several numbered performances.
Capacity: about 36 chained SeqNotes fit in one area of a G2 patch."""
import sys, os, argparse, math, re
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
try:
    import mido
except ImportError:
    raise SystemExit('mido is missing: run  pip install mido')
from g2lib import *
import chords as C
from gm import GM_NAMES, default_sound
def chord_step_label(k, spb):
    b = k / spb
    return f'{b:g} beat' + ('' if b == 1 else 's')

def clip(item, a, b):
    """The part of an item inside the section [a, b) beats, moved to start at 0. Notes that start before `a` are left
    out; notes that run past `b` are cut there."""
    notes = [(s - a, min(e, b) - a, n, v, tuple((t - a, n2) for t, n2 in ch if t < b)) for s, e, n, v, ch in item['notes'] if a - 1e-9 <= s < b - 1e-9]
    return dict(item, notes=notes)

def is_bass(l): return l['kind'] == 'line' and (l['avg'] < 50 or (l.get('program') is not None and 32 <= l['program'] <= 39))
def default_pick(lines, parts):
    """Busiest items first; a chordal track counts as one chord item (its split lines are skipped).
    With 2+ slots a bass line is always kept: it replaces the least busy pick if it didn't make the cut."""
    cand = []
    for l in lines:
        if l['in_chords']: continue
        if l['kind'] == 'chords':                      # chords that change faster than every half beat play better as a line
            spb0 = choose_grid([l])
            if C.choose_chord_step(l, spb0) / spb0 < 0.5:
                sub = [x for x in lines if x['kind'] == 'line' and x['tid'] == l['tid']]
                cand.append(max(sub, key=lambda x: len(x['notes']))); continue
        cand.append(l)
    cand.sort(key=lambda l: -len(l['notes']))
    top = cand[:parts]
    if parts >= 2 and len(cand) > parts and not any(is_bass(l) for l in top):
        bass = next((l for l in cand[parts:] if is_bass(l)), None)
        if bass: top[-1] = bass
    return sorted(top, key=lambda l: -l['avg'])

# ---------------------------------------------------------------- capacity (measured budgets, module outputs per area)
VOICE_BUDGET, FX_BUDGET = 115, 112          # module outputs per area that load reliably
REST = 0                                    # raw step value 0 = "no note" (-64 units); real notes must be >= MIDI 5
G2_BPM = (30, 240)

SOUNDS = [  # one per variation: (name, osc1 wave, osc1 shape, osc2 wave, osc2 semis, osc2 fine, lev1, lev2, cutoff Hz, res, env amt, amp ADSR ms/level, filter ADSR)
    ('Soft Keys',   1, 0,   0, 12, 64, 118, 52, 3000, 8,  18, (2, 900, 40, 600),   (0, 450, 0, 500)),
    ('Organ',       0, 0,   0, 12, 64, 112, 92, 7000, 0,  0,  (6, 120, 127, 300),  (0, 100, 127, 300)),
    ('Chip Square', 3, 0,   3, 0, 64,  118, 0,  12000, 0, 0,  (1, 60, 110, 150),   (0, 100, 127, 150)),
    ('Chip Pulse',  3, 90,  1, -12, 64, 112, 40, 12000, 0, 0, (1, 60, 110, 150),   (0, 100, 127, 150)),
    ('Warm Saw',    2, 0,   2, -12, 64, 110, 90, 1600, 28, 26, (6, 400, 100, 600),  (2, 600, 30, 600)),
    ('Pluck',       2, 0,   3, 0, 64,  112, 70, 700, 22, 46, (1, 800, 0, 600),     (0, 280, 0, 400)),
    ('Strings',     2, 0,   2, 12, 64, 112, 64, 2600, 6,  10, (350, 600, 108, 1400), (300, 900, 90, 1400)),
    ('Bass',        2, 0,   3, -12, 64, 112, 96, 650, 38, 34, (1, 450, 88, 300),   (0, 300, 20, 300)),
]

# ---------------------------------------------------------------- MIDI reading
def _round(x): return int(round(x))           # Python round(): halves to even (the web page copies this)

def read_midi(path, bends_mode='main'):
    """Notes per track and channel as (start beat, end beat, note, velocity, pitch changes).
    MIDI 1.0 rules followed: Note On velocity 0 = Note Off; repeated Note Ons of one key are paired first-in first-out
    with their Note Offs; All Notes Off / All Sound Off (CC 123 / 120) end held notes; Pitch Bend (14 bit, centre 8192)
    uses the range set by RPN 00 00 (default +/-2 semitones) and is reset by Reset All Controllers (CC 121).
    Bends are rounded to whole semitones (the G2 sequencers store semitones). bends_mode:
      'main'   (default) each note gets the semitone offset it holds longest - steady pitch, no stepped glides;
      'follow' the bend at the note's start shifts it and later bends become semitone steps without a new attack;
      'off'    pitch bend is ignored."""
    f = mido.MidiFile(path); tpb = f.ticks_per_beat
    tempos, raw, bends, ranges = [], [], defaultdict(list), defaultdict(list)
    for ti, tr in enumerate(f.tracks):
        t, on, notes, name = 0, defaultdict(list), defaultdict(list), tr.name.strip()
        rpn, semis, cents, prog, inst = {}, {}, {}, {}, ''
        for msg in tr:
            t += msg.time
            if msg.type == 'set_tempo': tempos.append((t, msg.tempo))
            elif msg.type == 'instrument_name': inst = inst or msg.name.strip()
            elif msg.type == 'program_change': prog.setdefault(msg.channel, msg.program)
            elif msg.type == 'note_on' and msg.velocity > 0: on[(msg.channel, msg.note)].append((t, msg.velocity))
            elif msg.type in ('note_off', 'note_on'):
                q = on.get((msg.channel, msg.note))
                if q: s, v = q.pop(0); notes[msg.channel].append((s, max(t, s + 1), msg.note, v))
            elif msg.type == 'pitchwheel': bends[msg.channel].append((t, msg.pitch))
            elif msg.type == 'control_change':
                ch, c, v = msg.channel, msg.control, msg.value
                if c in (120, 123):
                    for key in sorted(k for k in on if k[0] == ch):
                        while on[key]: s, vel = on[key].pop(0); notes[ch].append((s, max(t, s + 1), key[1], vel))
                elif c == 121: bends[ch].append((t, 0))
                elif c == 101: rpn[ch] = (v, rpn.get(ch, (127, 127))[1])
                elif c == 100: rpn[ch] = (rpn.get(ch, (127, 127))[0], v)
                elif c in (6, 38) and rpn.get(ch) == (0, 0):
                    if c == 6: semis[ch] = v
                    else: cents[ch] = v
                    ranges[ch].append((t, semis.get(ch, 2) + cents.get(ch, 0) / 100))
        raw.append((name, inst, prog, ti, notes))
    for ch in bends: bends[ch].sort(key=lambda x: x[0])
    for ch in ranges: ranges[ch].sort(key=lambda x: x[0])
    def semitones(ch, t, value):
        r = 2.0
        for rt, rv in ranges.get(ch, ()):
            if rt <= t: r = rv
            else: break
        return value / 8192 * r
    tracks = []
    for name, inst, prog, ti, notes in raw:
        for ch, ns in notes.items():
            if ch == 9: continue                                   # GM drums: not pitched
            out = []
            for s, e, key, v in ns:
                cur, changes = 0, []
                if bends_mode != 'off':
                    for bt, bv in bends.get(ch, ()):
                        if bt <= s: cur = _round(semitones(ch, bt, bv))
                        elif bt < e:
                            off = _round(semitones(ch, bt, bv))
                            if off != (changes[-1][1] - key if changes else cur): changes.append((bt, key + off))
                        else: break
                if bends_mode == 'main' and changes:
                    # one pitch per note: the semitone offset the note holds longest (scoops, falls and vibrato ignored)
                    segs, t0, o0 = {}, s, cur
                    for bt, n2 in changes: segs[o0] = segs.get(o0, 0) + bt - t0; t0, o0 = bt, n2 - key
                    segs[o0] = segs.get(o0, 0) + e - t0
                    best = max(segs.values()); cur = next(o for o in segs if segs[o] == best); changes = []
                out.append((s / tpb, e / tpb, key + cur, v, tuple((bt / tpb, n2) for bt, n2 in changes)))
            p = prog.get(ch)                                         # first Program Change on this channel in this track
            shown = name or inst or (GM_NAMES[p] if p is not None else f'Track {ti}')
            tracks.append(dict(name=f'{shown} ch{ch + 1}', notes=sorted(out), program=p))
    tempos.sort(); bpm = 60_000_000 / tempos[0][1] if tempos else 120.0
    if len({tp for _, tp in tempos}) > 1: print('! tempo changes in the file: using the first tempo only')
    return tracks, bpm

LEGATO = 0.25                                  # beats: a note may overlap the next one by this much (and by at most half
                                               # its own length) and still count as the same melodic line
def split_lines(track):
    """Split a (possibly polyphonic) track into monophonic lines: each note goes to a free line with the nearest pitch.
    A line is free when its last note has ended, or only overlaps this one a little (legato playing)."""
    lines = []                                                     # each: dict(notes=[...], end=beat, last=pitch, ls=start)
    for nt in sorted(track['notes'], key=lambda x: (x[0], -x[2])):
        s, e, n = nt[0], nt[1], nt[2]
        free = [l for l in lines if l['end'] - s <= 1e-6 or (l['end'] - s <= LEGATO and l['end'] - s <= 0.5 * (l['end'] - l['ls']))]
        if free: l = min(free, key=lambda l: abs(l['last'] - n))
        else: l = dict(notes=[], end=0, last=n, ls=s); lines.append(l)
        l['notes'].append(nt); l['end'], l['last'], l['ls'] = e, n, s
    return [dict(name=f"{track['name']} line {i + 1}" if len(lines) > 1 else track['name'], notes=l['notes'], program=track.get('program'), sound=track.get('sound')) for i, l in enumerate(lines)]

def choose_grid(lines, forced=None):
    """Steps per beat: the coarsest grid that keeps (almost) every note start on a step."""
    if forced: return forced
    starts = [s for l in lines for s, *_ in l['notes']]
    for spb in (2, 3, 4, 6, 8, 12):
        err = [abs(x * spb - round(x * spb)) for x in starts]
        if sum(e <= 0.12 for e in err) >= 0.97 * len(err): return spb
    return 4

def to_steps(line, spb, total):
    """-> list of (raw note, trig) per step. Rest = REST. Overlaps become legato; collisions keep the higher note.
    Pitch changes inside a note (from pitch bend) change the step value without a new trigger."""
    note, trig, dropped = [REST] * total, [0] * total, 0
    ev = sorted(((_round(s * spb), max(_round(s * spb) + 1, _round(e * spb)), n, ch) for s, e, n, _, ch in line['notes']))
    for i, (a, b, n, ch) in enumerate(ev):
        if a >= total: continue
        if i + 1 < len(ev) and ev[i + 1][0] < b: b = max(a + 1, ev[i + 1][0])        # next note starts: cut (legato)
        if trig[a]:
            dropped += 1
            if n <= note[a]: continue
        n = min(127, max(5, n))
        for k in range(a, min(b, total)): note[k] = n
        for t, n2 in ch:
            n2 = min(127, max(5, n2))
            for k in range(max(a, _round(t * spb)), min(b, total)): note[k] = n2
        trig[a] = 1
    return list(zip(note, trig)), dropped

# ---------------------------------------------------------------- patch building
def chain(A, col0, steps_bars, clk_out, start_out, first_rst, first_index):
    seqs = []
    for k, bar in enumerate(steps_bars):
        if k % 12 == 0: col = Stack(A, col0 + k // 12)
        s = col.add('SeqNote', f'Bar {first_index + k + 1}', color=MC.red1 if first_index + k == 0 else MC.yellow1)
        for i, (n, t) in enumerate(bar):
            setp(getattr(s.params, f'Seq1Step{i + 1}'), n); setp(getattr(s.params, f'Seq2Step{i + 1}'), t)
        setp(s.params.Loop, 0); setp(s.params.Length, 15); setp(s.params.TG, 0)
        con(A, clk_out, s.inputs.Clk, YEL)
        if k == 0: con(A, first_rst, s.inputs.Rst, YEL)
        else:
            p = seqs[-1]; con(A, p.outputs.Link, s.inputs.Rst, YEL)
            con(A, p.outputs.Note, s.inputs.Note, BLUE); con(A, p.outputs.Trig, s.inputs.Trig, YEL)
        if first_index + k > 0: con(A, start_out, s.inputs.Park, YEL)
        seqs.append(s)
    return seqs

def clock(st, A, name, div=6):
    """Master clock -> step clock. The ClkGen 1/96 output (24 pulses per beat) is divided by `div`, so one pulse =
    one grid step at the REAL tempo (16ths: /6, 16th triplets: /4, 8ths: /12 ...). The divider restarts with the clock.
    Returns (ClkGen, start Pulse, step clock output)."""
    clk = st.add('ClkGen', name, color=MC.yellow1); setp(clk.params.Source, 1); setp(clk.params.Active, 1)
    pu = st.add('Pulse', name[:9] + ' Start', color=MC.yellow1); setp(pu.params.Time, 10); setp(pu.params.Range, 0)
    dv = st.add('ClkDiv', 'Step Clock', color=MC.yellow1); setp(dv.params.Divider, div - 1); dv.modes[0].value = 0
    con(A, out(clk, 'ClkActive'), pu.inputs.In, YEL)
    con(A, out(clk, '1/96'), dv.inputs.Clk, YEL); con(A, pu.outputs.Out, dv.inputs.Rst, YEL)
    return clk, pu, dv.outputs.Out

def clock_plan(bpm, spb):
    """-> (G2 master tempo, ClkDiv value, note). Normally the G2 runs at the file's tempo and the divider is 24 / spb.
    Outside 30-240 BPM the G2 runs at a simple fraction or multiple of the tempo and the divider makes up for it."""
    for m in (1, 2, 3, 4, 6, 8):                       # G2 at bpm / m
        if (24 % (spb * m) == 0) and G2_BPM[0] <= bpm / m <= G2_BPM[1]:
            return int(round(bpm / m)), 24 // (spb * m), ('' if m == 1 else f'The G2 clock runs at 1/{m} of the tempo ({bpm / m:.0f} BPM); the step clock makes up for it.')
    for m in (2, 3, 4):                                # G2 at bpm * m
        if (24 * m) % spb == 0 and 24 * m // spb <= 128 and G2_BPM[0] <= bpm * m <= G2_BPM[1]:
            return int(round(bpm * m)), 24 * m // spb, f'The G2 clock runs at {m}x the tempo ({bpm * m:.0f} BPM); the step clock makes up for it.'
    g = int(round(min(G2_BPM[1], max(G2_BPM[0], bpm))))
    return g, 24 // spb, f'Tempo {bpm:.0f} BPM cannot be matched: the G2 clock is set to {g} BPM, so the piece plays at a different speed.'

_CAP = None
def capacity():
    """(SeqNotes per melody slot, 0): (measured voice-area output budget - clock and synth outputs) / 3 per SeqNote."""
    global _CAP
    if _CAP is None:
        _, P = new_patch(voices=1, mode='mono')
        clock(Stack(P.voice, 0), P.voice, 'C'); synth(P.voice, 0)
        fixed = sum(len(m.outputs) for m in P.voice.modules)
        _CAP = ((VOICE_BUDGET - fixed) // 3, 0)
    return _CAP

def synth(FX, sound, split=False, buses=True):
    """The melody voice, built in the SAME area as its sequencers (the voice area). The note value never leaves the
    area: held pitch values are not sent through FX sends or buses.
    The last sequencer's Note goes to 'note_in' (CompLev + T&H), its Trig to 'trig_in' (NOR -> retrigger)."""
    f = Stack(FX, 1); f.label('NOTE LOGIC')
    tin = None
    if buses: tin = f.add('2-In', 'Transpose Bus1'); setp(tin.params.Source, 2); setp(tin.params.Active, 1); setp(tin.params.Pad, 2)
    cmp_ = f.add('CompLev', 'Note On', color=MC.yellow1); setp(cmp_.params.C, 64 - 60)      # above -60 units = a note
    g1 = f.add('Gate', 'Gate Logic A', color=MC.yellow1); g1.modes[0].value = 0; g1.modes[1].value = 3   # AND / NOR
    g2 = f.add('Gate', 'Gate Logic B', color=MC.yellow1); g2.modes[0].value = 0; g2.modes[1].value = 0
    th = f.add('T&H', 'Hold Pitch', color=MC.blue1)
    con(FX, cmp_.outputs.Out, g1.inputs.In1_1, YEL)                 # sounding AND clock running
    con(FX, g1.outputs.Out1, g2.inputs.In1_1, YEL); con(FX, g1.outputs.Out2, g2.inputs.In1_2, YEL)
    con(FX, g1.outputs.Out1, th.inputs.Ctrl, YEL)

    s = Stack(FX, 2); s.label('SYNTH')
    o1 = s.add('OscB', 'Osc 1', color=MC.blue1); o2 = s.add('OscB', 'Osc 2', color=MC.blue1)
    mx = s.add('Mix2-1B', 'Osc Mix', color=MC.blue1); fe = s.add('ModADSR', 'Filter Env', color=MC.green1)
    flt = s.add('FltClassic', 'Filter', color=MC.red1); amp = s.add('EnvADSR', 'Amp Env', color=MC.green1)
    o = s.add('2-Out', 'Main Out'); setp(o.params.Destination, 0); setp(o.params.Active, 1); setp(o.params.Pad, 0)
    snd = None
    if buses: snd = s.add('2-Out', 'Rev Send Loop'); setp(snd.params.Destination, 5); setp(snd.params.Active, 1); setp(snd.params.Pad, 0)
    V = SOUNDS                                                       # variation k = sound k; the slot starts on `sound`
    col = lambda i: [v[i] for v in V]
    setp(o1.params.Waveform, col(1)); setp(o1.params.Shape, col(2)); setp(o1.params.FreqCoarse, 64); setp(o1.params.FreqFine, 64); setp(o1.params.FreqMode, 0); setp(o1.params.Kbt, 0); setp(o1.params.PitchMod, 127); setp(o1.params.Active, 1)
    setp(o2.params.Waveform, col(3)); setp(o2.params.FreqCoarse, [64 + x for x in col(4)]); setp(o2.params.FreqFine, col(5))
    setp(o2.params.FreqMode, 0); setp(o2.params.Kbt, 0); setp(o2.params.PitchMod, 127); setp(o2.params.Active, 1)
    setp(mx.params.Lev1, col(6)); setp(mx.params.Lev2, col(7)); setp(mx.params.ExpLin, 2)
    setp(flt.params.Freq, [filter_freq(x) for x in col(8)]); setp(flt.params.Res, col(9)); setp(flt.params.PitchMod, col(10))
    setp(flt.params.Slope, 1); setp(flt.params.Kbt, 0); setp(flt.params.Active, 1)
    for env, idx in ((amp, 11), (fe, 12)):
        a, d, sl, r = zip(*col(idx))
        setp(env.params.Attack, [env_time(x) for x in a]); setp(env.params.Decay, [env_time(x) for x in d])
        setp(env.params.Sustain, list(sl)); setp(env.params.Release, [env_time(x) for x in r]); setp(env.params.OutputType, 0)
    setp(amp.params.Shape, 0)
    for oo in (o1, o2):
        con(FX, th.outputs.Out, oo.inputs.Pitch, BLUE)
        if tin: con(FX, tin.outputs.OutL, oo.inputs.PitchVar, BLUE)
    con(FX, th.outputs.Out, flt.inputs.Pitch, BLUE)                 # transpose enters the oscillators' PitchVar only
    con(FX, o1.outputs.Out, mx.inputs.In1, RED); con(FX, o2.outputs.Out, mx.inputs.In2, RED)
    con(FX, mx.outputs.Out, flt.inputs.In, RED); con(FX, fe.outputs.Env, flt.inputs.PitchVar, BLUE)
    con(FX, flt.outputs.Out, amp.inputs.In, RED)
    if buses: con(FX, g2.outputs.Out1, amp.inputs.Gate, YEL); con(FX, g2.outputs.Out1, fe.inputs.Gate, YEL)
    con(FX, amp.outputs.Out, o.inputs.InL, RED); con(FX, amp.outputs.Out, o.inputs.InR, RED)
    if snd: con(FX, amp.outputs.Out, snd.inputs.InL, RED)
    return dict(o=o, cmp=cmp_, th=th, g1=g1, g2=g2, snd=snd, flt=flt, amp=amp, fe=fe, mx=mx)

def part_patch(title, bars, sound, path, loop=True, div=6):
    """Melody slot: clock, synth and up to capacity() chained SeqNotes, all in the voice area (FX area empty)."""
    pch2, P = new_patch(voices=1, mode='mono'); V = P.voice
    c = Stack(V, 0); c.label('CLOCK')
    clk, st, step = clock(c, V, 'Clock', div)
    sy = synth(V, sound)
    con(V, out(clk, 'ClkActive'), sy['g1'].inputs.In1_2, YEL)
    vs = chain(V, 3, bars, step, st.outputs.Out, st.outputs.Out, 0)
    con(V, vs[-1].outputs.Note, sy['cmp'].inputs.In, BLUE); con(V, vs[-1].outputs.Note, sy['th'].inputs.In, BLUE)
    con(V, vs[-1].outputs.Trig, sy['g1'].inputs.In2_1, YEL)
    if loop: con(V, vs[-1].outputs.Link, vs[0].inputs.Loop, YEL)
    vb, fb = bars, []
    P.description.variation = sound
    knobs(P, 'A1', [sy['flt'].params.Freq, sy['flt'].params.Res, sy['flt'].params.PitchMod, sy['amp'].params.Attack,
                    sy['amp'].params.Decay, sy['amp'].params.Sustain, sy['amp'].params.Release, P.settings.patchvol])
    knobs(P, 'A2', [sy['fe'].params.Attack, sy['fe'].params.Decay, sy['fe'].params.Sustain, sy['fe'].params.Release,
                    sy['mx'].params.Lev1, sy['mx'].params.Lev2, None, None])
    cc(P, 74, sy['flt'].params.Freq); cc(P, 71, sy['flt'].params.Res); cc(P, 73, sy['amp'].params.Attack); cc(P, 72, sy['amp'].params.Release)
    setp(P.settings.patchvol, 96)
    set_text(P, f'midi2g2 melody slot: {len(vb)} x 16 steps, sequencers and synth in the voice area, '
                'follows the master clock (1/96 divided to one pulse per step), restarts on start. Variations = sounds: ' + ', '.join(f'{i + 1} {SOUNDS[i][0]}' for i in range(8)) +
                '. A1: cutoff, res, filter env, amp A D S R, volume. A2: filter env ADSR, osc 1/2 levels.')
    return save(pch2, path), sy

def control_patch(path):
    pch2, P = new_patch(voices=1, mode='mono'); V, FX = P.voice, P.fx
    c = Stack(V, 0); c.label('TRANSPOSE')
    kb = c.add('Keyboard', 'Keys')
    la = c.add('LevAdd', 'C3 Is Zero', color=MC.blue1); setp(la.params.Level, 64 + 16); setp(la.params.BipUni, 0)
    th = c.add('T&H', 'Hold Transpose', color=MC.blue1)
    to = c.add('2-Out', 'Transpose Bus1'); setp(to.params.Destination, 4); setp(to.params.Active, 1); setp(to.params.Pad, 0)
    con(V, kb.outputs.Note, la.inputs.In, BLUE); con(V, la.outputs.Out, th.inputs.In, BLUE); con(V, kb.outputs.Gate, th.inputs.Ctrl, YEL)
    con(V, th.outputs.Out, to.inputs.InL, BLUE)
    f = Stack(FX, 0); f.label('REVERB')
    ri = f.add('2-In', 'Send Bus3'); setp(ri.params.Source, 3); setp(ri.params.Active, 1); setp(ri.params.Pad, 2)
    rv = f.add('Reverb', 'Room'); rv.modes[0].value = 2
    for k, v in (('Time', 60), ('Brightness', 64), ('DryWet', 127), ('Active', 1)): setp(getattr(rv.params, k), v)
    rl = f.add('Mix2-1B', 'Return L', color=MC.blue1); rr = f.add('Mix2-1B', 'Return R', color=MC.blue1)
    for mx in (rl, rr): setp(mx.params.Lev1, 84); setp(mx.params.ExpLin, 2)
    ro = f.add('2-Out', 'Reverb Out'); setp(ro.params.Destination, 0); setp(ro.params.Active, 1); setp(ro.params.Pad, 0)
    con(FX, ri.outputs.OutL, rv.inputs.InL, RED); con(FX, ri.outputs.OutL, rv.inputs.InR, RED)
    con(FX, rv.outputs.OutL, rl.inputs.In1, RED); con(FX, rv.outputs.OutR, rr.inputs.In1, RED)
    con(FX, rl.outputs.Out, ro.inputs.InL, RED); con(FX, rr.outputs.Out, ro.inputs.InR, RED)
    knobs(P, 'A1', [rv.params.Time, rv.params.Brightness, rl.params.Lev1, rr.params.Lev1, None, None, None, P.settings.patchvol])
    cc(P, 91, rl.params.Lev1); cc(P, 93, rv.params.Time); setp(P.settings.patchvol, 100)
    set_text(P, 'Control slot: play a key to transpose all parts (C3 = original key, holds until the next key). '
                'FX area: room reverb fed by Bus 3 from the part slots. A1: reverb time, brightness, return L/R, volume.')
    return save(pch2, path)


# ---------------------------------------------------------------- performance file size (the G2 editor can't load a .prf2 over 64 KB)
PRF2_LIMIT = 65000                           # bytes, a little under 65,535
_TPL = None
def _blob_len(b64):
    pad = b64[-2:].count('=') if b64 else 0
    return len(b64) * 3 // 4 - pad
def _tpl():
    global _TPL
    if _TPL is None:
        import json; _TPL = json.load(open(os.path.join(HERE, 'templates.json')))
    return _TPL
def perf_size(parts, b0, b1, short, control):
    """Exact .prf2 size for bars b0..b1, from the patch sizes in templates.json (same numbers the web page uses)."""
    T = _tpl(); blobs, names = [], []
    for si, (kind, k, st) in enumerate(parts):
        if kind == 'chords':
            nseq = math.ceil((b1 - b0) * 16 // k / 16)
            blobs.append(_blob_len(T['chord'][str(len(st))][str(nseq)]['blob']))
        else:
            blobs.append(_blob_len(T['templates'][str(b1 - b0)]['blob']))
        names.append(f'{short} {"ABCD"[si]}')
    nknobs = 3 * len(parts)
    if control: blobs.append(_blob_len(T['control'])); names.append(f'{short[:9]} Ctrl'); nknobs += 3
    while len(names) < 4: blobs.append(_blob_len(T['free'])); names.append('Free')
    desc = 8 + sum(min(16, len(n) + 1) + 10 for n in names)
    knob = (16 + 120 + 23 * nknobs + 7) // 8
    hdr = len('Version=Nord Modular G2 File Format 1\r\nType=Performance\r\nVersion=23\r\nInfo=BUILD 320\r\n\0')
    return hdr + 2 + 3 + desc + sum(blobs) + 3 + knob + 2
def perf_ranges(parts, nbars, per_perf, short, control, align=1):
    """Bar ranges per performance: at most per_perf bars, file under the size limit, and every boundary on a multiple
    of `align` bars so chord slots start on a whole chord step."""
    out, b0 = [], 0; step = max(align, per_perf // align * align)
    while b0 < nbars:
        b1 = min(nbars, b0 + step)
        while b1 - align > b0 and perf_size(parts, b0, b1, short, control) > PRF2_LIMIT: b1 = (b1 - 1) // align * align if b1 % align else b1 - align
        out.append((b0, b1)); b0 = b1
    return out


GRID_NAMES = {2: '8ths', 3: '8th triplets', 4: '16ths', 6: '16th triplets', 8: '32nds', 12: '32nd triplets'}
def write_chain(a, name, short, line, lines, bpm, section=None):
    """One track over up to 4 slots per performance (see chainslots.py)."""
    import chainslots as CS
    src = line
    if section: line = clip(line, *section)
    spb = choose_grid([line], a.grid)
    g2bpm, div, note = clock_plan(bpm, spb)
    if note: print('! ' + note)
    end = (section[1] - section[0]) if section else max(x[1] for x in line['notes']); total = int(math.ceil(end * spb / 16)) * 16
    st, dr = to_steps(line, spb, total); nbars = total // 16; cap = CS.chain_capacity(); per_perf = 4 * cap
    nperf = math.ceil(nbars / per_perf)
    outdir = a.out or os.path.join(os.path.dirname(os.path.abspath(a.midi)), f'{name} G2'); os.makedirs(outdir, exist_ok=True)
    sound = a.sound - 1 if a.sound else ((7 if line['avg'] < 55 else 0) if (line.get('program') is None and line.get('sound') is None) else default_sound(line, 0, 1))
    rest = [(REST, 0)] * 16
    files, used = [], []
    for pi in range(nperf):
        b0, b1 = pi * per_perf, min(nbars, (pi + 1) * per_perf)
        tag = f' {pi + 1}of{nperf}' if nperf > 1 else ''
        nslots = math.ceil((b1 - b0) / cap); used.append(nslots)
        slots, gk = [], []
        for si in range(nslots):
            c0 = b0 + si * cap; c1 = min(b1, c0 + cap)
            bars = [st[16 * b:16 * b + 16] for b in range(c0, c1)] + [rest] * (cap - (c1 - c0))
            pf, sy = CS.chain_slot(CS.ROLES[si], bars, sound, f'{outdir}/{name}{tag} {CS.ROLES[si]}.pch2', div)
            slots.append(dict(name=f'{short} {CS.ROLES[si]}', patch=pf, enabled=1, keyboard=0))
            fl, am = find(pf, 'Filter'), find(pf, 'Amp Env')
            gk += [(si, si, fl.params.Freq), (4 + si, si, am.params.Release), (8 + si, si, am.params.Attack)]
        while len(slots) < 4: slots.append(dict(name='Free', patch=free_patch(f'{outdir}/Free.pch2'), enabled=0, keyboard=0))
        pp = f'{outdir}/{name}{tag}.prf2'; write_prf2(pp, slots, bpm=g2bpm, global_knobs=gk); files.append(pp)
    secs = total / spb * 60 / bpm
    summary = [f'Source: {os.path.basename(a.midi)}', f'Tempo {bpm:.1f} BPM, grid {GRID_NAMES[spb]} -> G2 master clock {g2bpm} BPM (step clock = 1/96 divided by {div})',
               f'Length {nbars} x 16 steps, {int(secs // 60)}:{int(secs % 60):02d}; {nperf} performance(s), one track chained over '
               + ', '.join(str(u) for u in used) + f' slot(s), up to {cap} x 16 steps per slot',
               f"Track: {line['name']}: {len(line['notes'])} notes" + (f', {dr} merged by quantizing' if dr else '') + f' (starts on variation {sound + 1} {SOUNDS[sound][0]})']
    if section: summary.insert(1, f'Section: beats {section[0]:g} to {section[1]:g}')
    others = [l for l in lines if l is not src and l['kind'] == 'line']
    if others: summary.append('Not included: ' + ', '.join(f"{l['name']} ({len(l['notes'])} notes)" for l in others))
    open(f'{outdir}/CONVERSION.txt', 'w', encoding='utf-8', newline='\n').write('\n'.join(summary) + '\n')
    print('\n'.join(summary)); print('wrote', *files, sep='\n  ')

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('midi'); ap.add_argument('--out'); ap.add_argument('--list', action='store_true')
    ap.add_argument('--pick', help='comma-separated line numbers from --list, in slot order')
    ap.add_argument('--parts', type=int, default=3, choices=(1, 2, 3, 4), help='part slots (4 = no control/reverb slot)')
    ap.add_argument('--grid', type=int, choices=(2, 3, 4, 6, 8, 12), help='steps per beat (4 = 16ths). Default: auto')
    ap.add_argument('--sound', type=int, choices=range(1, 9), help='starting variation/sound 1-8 for every slot (default: 1 Soft Keys, 8 Bass for a low bottom line)')
    ap.add_argument('--bends', choices=('main', 'follow', 'off'), default='main', help='pitch bend: main pitch per note (default), follow in semitone steps, or ignore')
    ap.add_argument('--chain', action='store_true', help='play ONE track across slots A -> B -> C -> D (longer pieces; no control slot)')
    ap.add_argument('--song', type=int, help='NSF / NSFe / SID files: which song of the file (default: its starting song)')
    ap.add_argument('--start', type=float, help='convert only a section: first beat (quarter notes from the start of the file)')
    ap.add_argument('--end', type=float, help='section end in beats (default: end of the file)')
    ap.add_argument('--no-loop', action='store_true'); ap.add_argument('--bpm', type=float, help='override the file tempo')
    a = ap.parse_args()
    name = re.sub(r' +', ' ', re.sub(r'[^A-Za-z0-9 \-]', ' ', os.path.splitext(os.path.basename(a.midi))[0])).strip()[:40] or 'Song'
    short = name[:10].strip()
    magic = open(a.midi, 'rb').read(4)
    if magic in (b'NESM', b'NSFE', b'PSID', b'RSID'):            # chip music: run the tune's own player (see nsf.py / sid.py)
        if magic in (b'PSID', b'RSID'): import sid; tracks, bpm, info = sid.read_sid(open(a.midi, 'rb').read(), a.song); kind = 'SID'
        else: import nsf; tracks, bpm, info = nsf.read_nsf(open(a.midi, 'rb').read(), a.song); kind = 'NSF'
        name = f"{name[:34].strip()} s{info['song']}"; short = name[:10].strip()
        print(f"{kind}: {info['title'] or 'untitled'}, song {info['song']} of {info['songs']}" + (f", loop found after {info['loop_end']} frames" if info['loop_end'] else ', no loop found (4 minutes read)'))
    else: tracks, bpm = read_midi(a.midi, a.bends)
    bpm = a.bpm or bpm
    lines = []
    for tid, t in enumerate(tracks):
        ls = split_lines(t); chordal = len(ls) > 1 and C.is_chordal(t)
        for l in ls: l['kind'] = 'line'; l['in_chords'] = chordal; l['tid'] = tid; lines.append(l)
        if chordal: lines.append(dict(kind='chords', name=f"{t['name']} chords", notes=t['notes'], in_chords=False, program=t.get('program'), tid=tid))
    for i, l in enumerate(lines):
        ps = [x[2] for x in l['notes']]; l['id'] = i; l['avg'] = sum(ps) / len(ps)
    if a.list or not lines:
        for l in lines: print(f"{l['id']:3d}  {len(l['notes']):5d} notes  avg {l['avg']:5.1f}  {l['name']}" + ('  [chords]' if l['kind'] == 'chords' else '') + (f"  (GM {l['program'] + 1} {GM_NAMES[l['program']]})" if l.get('program') is not None else ''))
        return
    section = None
    if a.start is not None or a.end is not None:
        file_end = max(x[1] for l in lines for x in l['notes'])
        section = (max(0.0, a.start or 0.0), min(file_end, a.end) if a.end is not None else file_end)
        if section[0] >= section[1]: raise SystemExit('--start must be before --end')
    if a.chain:
        cand = [lines[int(x)] for x in a.pick.split(',')][:1] if a.pick else sorted([l for l in lines if l['kind'] == 'line'], key=lambda l: -len(l['notes']))[:1]
        if not cand or cand[0]['kind'] != 'line': raise SystemExit('--chain needs a single-note line (not a chord item)')
        return write_chain(a, name, short, cand[0], lines, bpm, section)
    if a.pick: chosen = [lines[int(x)] for x in a.pick.split(',')]
    else: chosen = default_pick(lines, a.parts)
    dropped_lines = [l for l in lines if l['id'] not in {c['id'] for c in chosen} and not (l['in_chords'] and any(c['kind'] == 'chords' for c in chosen))]
    spb = choose_grid(chosen, a.grid)
    g2bpm, div, note = clock_plan(bpm, spb)
    if note: print('! ' + note)
    ids = {l['id'] for l in chosen}
    if section: chosen = [clip(l, *section) for l in chosen]
    end = (section[1] - section[0]) if section else max(x[1] for l in chosen for x in l['notes'])
    nv, nf = capacity(); per_perf = nv + nf
    cinfo = {}
    for l in chosen:
        if l['kind'] == 'chords':
            k = C.choose_chord_step(l, spb); cinfo[l['id']] = k
    total = int(math.ceil(end * spb / 16)) * 16
    parts, report, align = [], [], 1                # align: performances must start on a whole chord step
    for l in chosen:
        if l['kind'] == 'chords':
            k = cinfo[l['id']]; K, rows, dr = C.chord_steps(l, spb, k, int(math.ceil(total / k)) * k)
            per_perf = min(per_perf, C.chord_capacity(K) * k); align = align * (k // math.gcd(16, k)) // math.gcd(align, k // math.gcd(16, k))
            parts.append(('chords', k, rows))
            report.append(f"{l['name']}: {len(l['notes'])} notes as {K}-note chords, one step = {chord_step_label(k, spb)}" + (f', {dr} notes above {K} per chord left out' if dr else ''))
        else:
            st, dr = to_steps(l, spb, total); parts.append(('line', 1, st))
            report.append(f"{l['name']}: {len(l['notes'])} notes" + (f', {dr} merged by quantizing' if dr else ''))
    nbars = total // 16
    ranges = perf_ranges(parts, nbars, per_perf, short, a.parts < 4 and len(parts) < 4, align)
    nperf = len(ranges)
    outdir = a.out or os.path.join(os.path.dirname(os.path.abspath(a.midi)), f'{name} G2'); os.makedirs(outdir, exist_ok=True)
    roles = []
    for i, l in enumerate(chosen):
        if a.sound: roles.append(a.sound - 1)
        else: roles.append(default_sound(l, i, len(chosen)))
    secs = total / spb * 60 / bpm
    files = []
    for pi, (b0, b1) in enumerate(ranges):
        tag = f' {pi + 1}of{nperf}' if nperf > 1 else ''
        slots, gk = [], []
        for si, (kind, k, st) in enumerate(parts):
            ppath = f'{outdir}/{name}{tag} {"ABCD"[si]}.pch2'
            if kind == 'chords':
                c0, c1 = b0 * 16 // k, b1 * 16 // k                  # chord steps of this performance
                nseq = math.ceil((c1 - c0) / 16); last = (c1 - c0) - 16 * (nseq - 1)
                rb = [[row[c0 + 16 * q: min(c1, c0 + 16 * q + 16)] for q in range(nseq)] for row in st]
                rb = [[bar + [(bar[-1][0], 0)] * (16 - len(bar)) for bar in rows] for rows in rb]   # pad the last sequencer
                pf, sy = C.chord_patch(rb, k, roles[si], ppath, last_len=last, loop=not a.no_loop, div=div)
            else:
                bars = [st[16 * b:16 * b + 16] for b in range(b0, b1)]
                pf, sy = part_patch('', bars, roles[si], ppath, loop=not a.no_loop, div=div)
            slots.append(dict(name=f'{short} {"ABCD"[si]}', patch=pf, enabled=1, keyboard=0))
            fl = find(pf, 'Filter'); am = find(pf, 'Amp Env')
            gk += [(si, si, fl.params.Freq), (4 + si, si, am.params.Release), (8 + si, si, am.params.Attack)]
        if a.parts < 4 and len(parts) < 4:
            D = control_patch(f'{outdir}/{name}{tag} Control.pch2')
            slots.append(dict(name=f'{short[:9]} Ctrl', patch=D, enabled=1, keyboard=1))
            cs = len(slots) - 1                                     # the control slot follows the parts
            gk += [(3, cs, find(D, 'Room').params.Time), (7, cs, find(D, 'Return L').params.Lev1), (11, cs, find(D, 'Return R').params.Lev1)]
        while len(slots) < 4:
            slots.append(dict(name='Free', patch=free_patch(f'{outdir}/Free.pch2'), enabled=0, keyboard=0))
        pp = f'{outdir}/{name}{tag}.prf2'
        write_prf2(pp, slots, bpm=g2bpm, global_knobs=gk); files.append(pp)
    grid_name = {2: '8ths', 3: '8th triplets', 4: '16ths', 6: '16th triplets', 8: '32nds', 12: '32nd triplets'}[spb]
    summary = [f'Source: {os.path.basename(a.midi)}', f'Tempo {bpm:.1f} BPM, grid {grid_name} -> G2 master clock {g2bpm} BPM (step clock = 1/96 divided by {div})',
               f'Length {nbars} x 16 steps, {int(secs // 60)}:{int(secs % 60):02d}; {nperf} performance(s) (' + ', '.join(str(b1 - b0) for b0, b1 in ranges) + ' x 16 steps; each file under 64 KB)',
               'Slots: ' + '; '.join(f'{"ABCD"[i]} = {r} (starts on variation {roles[i] + 1} {(C.CHORD_SOUNDS if chosen[i]["kind"] == "chords" else SOUNDS)[roles[i]][0]})' for i, r in enumerate(report))]
    if section: summary.insert(1, f'Section: beats {section[0]:g} to {section[1]:g}')
    if dropped_lines: summary.append('Not included: ' + ', '.join(f"{l['name']} ({len(l['notes'])} notes)" for l in dropped_lines))
    open(f'{outdir}/CONVERSION.txt', 'w', encoding='utf-8', newline='\n').write('\n'.join(summary) + '\n')
    print('\n'.join(summary)); print('wrote', *files, sep='\n  ')


if __name__ == '__main__':
    main()
