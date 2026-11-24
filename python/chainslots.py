"""One long track played across slots A -> B -> C -> D.

Every slot holds CHAIN_BARS bars of the same track (sequencers + synth in the voice area, as in a melody slot).
When a slot's last sequencer finishes, its Link pulse goes out on a bus and starts the next slot:
    A -> B on Bus 1/2 L,   B -> C on Bus 1/2 R,   C -> D on Bus 3/4 L.
Only a pulse crosses slots, never a pitch. The Link of the last sequencer goes through a Pulse module first,
so the bus and the flip-flop reset only ever see a short pulse at the real end (a Link that is already high when the
clock starts would otherwise hold the flip-flop in reset and the slot would stay silent). Each slot's clock is delayed a little more than the previous one
(B 2.5 ms, C 5 ms, D 7.5 ms) so the start pulse always arrives before that slot's next clock step.
An SR flip-flop marks the slot that is playing; the others stay silent. Unused bars at the end are rests.
No loop: the piece plays once. The buses are taken, so there is no control/reverb slot in this mode."""
from g2lib import *
import midi2g2 as M

ROLES = 'ABCD'
DELAY = {'A': 0, 'B': 45, 'C': 54, 'D': 60}            # Delay module Time (Sub range): ~0.1 ms, 2.5 ms, 5 ms, 7.5 ms
LINK_IN = {'B': (2, 'OutL'), 'C': (2, 'OutR'), 'D': (3, 'OutL')}        # 2-In Source (2 = Bus 1/2, 3 = Bus 3/4), side
LINK_OUT = {'A': (4, 'InL'), 'B': (4, 'InR'), 'C': (5, 'InL'), 'D': (5, 'InR')}  # 2-Out Destination (4 = Bus 1/2, 5 = Bus 3/4)

def chain_slot(role, bars, sound, path, div=6):
    pch2, P = new_patch(voices=1, mode='mono'); V = P.voice
    c = Stack(V, 0); c.label(f'CHAIN {role}')
    clk, st, step = M.clock(c, V, 'Clock', div)
    dly = c.add('Delay', 'Clock Offset', color=MC.yellow1)
    setp(dly.params.Time, DELAY[role]); setp(dly.params.Range, 0); dly.modes[0].value = 2
    lin = c.add('2-In', 'Start From Prev'); setp(lin.params.Source, LINK_IN.get(role, (2, 'OutL'))[0]); setp(lin.params.Active, 1); setp(lin.params.Pad, 2)
    lout = c.add('2-Out', 'Start Next Slot'); setp(lout.params.Destination, LINK_OUT[role][0]); setp(lout.params.Active, 1); setp(lout.params.Pad, 0)
    ff = c.add('FlipFlop', 'Playing', color=MC.yellow1); ff.modes[0].value = 1                       # SR type
    g3 = c.add('Gate', 'Gate Logic C', color=MC.yellow1); g3.modes[0].value = 0; g3.modes[1].value = 2   # AND / OR
    ep = c.add('Pulse', 'End Pulse', color=MC.yellow1); setp(ep.params.Time, 10); setp(ep.params.Range, 0)
    sy = M.synth(V, sound, buses=False)
    con(V, step, dly.inputs.In, YEL)
    con(V, out(clk, 'ClkActive'), sy['g1'].inputs.In1_2, YEL)
    start_me = st.outputs.Out if role == 'A' else getattr(lin.outputs, LINK_IN[role][1])
    seqs, col = [], 3
    for k, bar in enumerate(bars):
        if k % 12 == 0: sc = Stack(V, col); col += 1
        s = sc.add('SeqNote', f'Bar {k + 1}', color=MC.red1 if k == 0 else MC.yellow1)
        for i, (n, t) in enumerate(bar):
            setp(getattr(s.params, f'Seq1Step{i + 1}'), n); setp(getattr(s.params, f'Seq2Step{i + 1}'), t)
        setp(s.params.Loop, 0); setp(s.params.Length, 15); setp(s.params.TG, 0)
        con(V, dly.outputs.Out, s.inputs.Clk, YEL)
        if k == 0: con(V, start_me, s.inputs.Rst, YEL)
        else:
            p = seqs[-1]; con(V, p.outputs.Link, s.inputs.Rst, YEL)
            con(V, p.outputs.Note, s.inputs.Note, BLUE); con(V, p.outputs.Trig, s.inputs.Trig, YEL)
        if not (role == 'A' and k == 0): con(V, st.outputs.Out, s.inputs.Park, YEL)
        seqs.append(s)
    con(V, seqs[-1].outputs.Link, ep.inputs.In, YEL)
    end = ep.outputs.Out          # a short pulse on the rising edge of the last Link: never a held level
    con(V, seqs[-1].outputs.Note, sy['cmp'].inputs.In, BLUE); con(V, seqs[-1].outputs.Note, sy['th'].inputs.In, BLUE)
    con(V, seqs[-1].outputs.Trig, sy['g1'].inputs.In2_1, YEL)
    con(V, end, getattr(lout.inputs, LINK_OUT[role][1]), YEL)
    # playing flag: set by this slot's start, reset by its end (and, for B-D, by the clock start)
    con(V, start_me, ff.inputs.In, YEL)
    con(V, end, g3.inputs.In2_1, YEL)
    if role != 'A': con(V, st.outputs.Out, g3.inputs.In2_2, YEL)
    con(V, g3.outputs.Out2, ff.inputs.Rst, YEL)
    con(V, sy['g2'].outputs.Out1, g3.inputs.In1_1, YEL); con(V, ff.outputs.Q, g3.inputs.In1_2, YEL)
    con(V, g3.outputs.Out1, sy['amp'].inputs.Gate, YEL); con(V, g3.outputs.Out1, sy['fe'].inputs.Gate, YEL)
    P.description.variation = sound
    knobs(P, 'A1', [sy['flt'].params.Freq, sy['flt'].params.Res, sy['flt'].params.PitchMod, sy['amp'].params.Attack,
                    sy['amp'].params.Decay, sy['amp'].params.Sustain, sy['amp'].params.Release, P.settings.patchvol])
    knobs(P, 'A2', [sy['fe'].params.Attack, sy['fe'].params.Decay, sy['fe'].params.Sustain, sy['fe'].params.Release,
                    sy['mx'].params.Lev1, sy['mx'].params.Lev2, None, None])
    cc(P, 74, sy['flt'].params.Freq); cc(P, 71, sy['flt'].params.Res); cc(P, 73, sy['amp'].params.Attack); cc(P, 72, sy['amp'].params.Release)
    setp(P.settings.patchvol, 96)
    set_text(P, f'midi2g2 chain slot {role}: part {ROLES.index(role) + 1} of one long track ({len(bars)} x 16 steps). '
                'Starts when the previous slot ends (bus pulse), plays once. Variations = sounds: '
                + ', '.join(f'{i + 1} {M.SOUNDS[i][0]}' for i in range(8)) + '. A1: cutoff, res, filter env, amp A D S R, volume.')
    return save(pch2, path), sy

_CAP = None
def chain_capacity(budget=115):
    global _CAP
    if _CAP is None:
        _, P = new_patch(voices=1, mode='mono'); V = P.voice; c = Stack(V, 0)
        M.clock(c, V, 'C'); c.add('Delay', 'D'); c.add('2-In', 'I'); c.add('2-Out', 'O'); c.add('FlipFlop', 'F'); c.add('Gate', 'G'); c.add('Pulse', 'P')
        M.synth(V, 0, buses=False)
        _CAP = (budget - sum(len(m.outputs) for m in V.modules)) // 3
    return _CAP
