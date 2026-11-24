"""Builds templates.json for the web version of midi2g2: for every bar count 1..64 the exact patch bytes
(as written into a .prf2) plus the bit position of every sequencer step, so the page only has to drop
the notes in. Verified by re-parsing with g2ools."""
import sys, os, json, base64, random, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import midi2g2 as M
import chords as C
from g2lib import *

TMP = tempfile.mkdtemp()

def blob(pf):
    buf = bytearray(1 << 20); mv = memoryview(buf)
    rest = pf.format_patch(pf.patch, mv)
    return bytes(buf[:len(buf) - len(rest)])

def build(n, note, trig, sound=0, div=1):
    bars = [[(note, trig)] * 16 for _ in range(n)]
    pf, _ = M.part_patch('t', bars, sound, f'{TMP}/t.pch2', loop=True, div=div)
    return pf, blob(pf)

def field_starts(a, b):
    """Start bits of the 7-bit fields that differ completely between two blobs (value 0 vs 127): one per variation."""
    x = ''.join('1' if p != q else '0' for p, q in zip(bits(a), bits(b)))
    out, i = [], 0
    while True:
        i = x.find('1111111', i)
        if i < 0: break
        out.append(i); i += 7
    assert len(out) == 9 and x.count('1') == 63, (len(out), x.count('1'))
    return out

def bits(b): return ''.join(f'{x:08b}' for x in b)

def note_runs(a, b):
    """Positions where 112 consecutive bits differ (16 notes x 7 bits: 0 vs 127) - one per sequencer per variation."""
    x = ''.join('1' if p != q else '0' for p, q in zip(bits(a), bits(b)))
    runs, i = [], 0
    while True:
        i = x.find('1' * 112, i)
        if i < 0: break
        runs.append(i); i += 112
    return runs

def setbit_field(buf, pos, nbits, val):
    for k in range(nbits):
        byte, bit = divmod(pos + k, 8); mask = 0x80 >> bit
        if (val >> (nbits - 1 - k)) & 1: buf[byte] |= mask
        else: buf[byte] &= ~mask & 0xff

def main():
    nv, nf = M.capacity(); out = dict(capacity=[nv, nf], sounds=[s[0] for s in M.SOUNDS], templates={})
    for n in range(1, nv + nf + 1):
        pa, A = build(n, 0, 0); pb, B = build(n, 127, 1); _, S = build(n, 0, 0, sound=7)
        assert len(A) == len(B) == len(S)
        runs = note_runs(A, B); assert len(runs) == 9 * n, (n, len(runs))
        dv = [i for i, (p, q) in enumerate(zip(bits(A), bits(S))) if p != q]; varpos = dv[-1] - 7
        # runs are in module-index order; map them back to bars via the module order in each area
        P = pa.patch
        order = []
        for area in (P.voice, P.fx):     # Parameters sections: voice area first, then FX area (checked below)
            seqs = sorted([m for m in area.modules if m.type.shortnm == 'SeqNote'], key=lambda m: m.index)
            order += [int(m.name.split()[1]) - 1 for m in seqs]
        bar_runs = [None] * n
        for k, bar in enumerate(order): bar_runs[bar] = runs[9 * k: 9 * k + 9]
        # verify: random notes/trigs + a default variation through the offsets, re-parse with g2ools
        buf = bytearray(A); want = [[(random.randint(5, 127), random.randint(0, 1)) for _ in range(16)] for _ in range(n)]
        for bar in range(n):
            for base in bar_runs[bar]:
                for i, (nt, tr) in enumerate(want[bar]):
                    setbit_field(buf, base + 7 * i, 7, nt); setbit_field(buf, base + 112 + 7 * i, 7, tr)
        setbit_field(buf, varpos, 8, 5)
        chk = Pch2File(); chk.parse_patch(chk.patch, memoryview(bytes(buf)))
        assert chk.patch.description.variation == 5
        for m in chk.patch.voice.modules + chk.patch.fx.modules:
            if m.type.shortnm != 'SeqNote': continue
            bar = int(m.name.split()[1]) - 1
            for i, (nt, tr) in enumerate(want[bar]):
                for v in range(9):
                    assert getattr(m.params, f'Seq1Step{i + 1}').variations[v] == nt
                    assert getattr(m.params, f'Seq2Step{i + 1}').variations[v] == tr
        _, Dv = build(n, 0, 0, div=128); div_pos = field_starts(A, Dv)
        out['templates'][n] = dict(blob=base64.b64encode(A).decode(), runs=bar_runs, var=varpos, div=div_pos)
        print('template', n, len(A), 'bytes ok')
    # ---------------- chord slots
    out['chord'] = {}; out['chord_sounds'] = [x[0] for x in C.CHORD_SOUNDS]; out['chord_capacity'] = {}
    cref = {}
    for K in (2, 3, 4):
        cap = C.chord_capacity(K); out['chord_capacity'][K] = cap; out['chord'][K] = {}
        for n in range(1, cap + 1):
            def cb(note, r2, sound=0, div=1, hl=None):
                rows = [[[(note, r2)] * 16 for _ in range(n)] for _ in range(K)]
                pf, _ = C.chord_patch(rows, 1, sound, f'{TMP}/c.pch2', last_len=16, div=div, _hl=hl)
                return pf, blob(pf)
            pc, A = cb(0, 0); _, B = cb(127, 1); _, S = cb(0, 0, sound=7)
            runs = note_runs(A, B); assert len(runs) == 9 * n * K, (K, n, len(runs))
            dv = [i for i, (p, q) in enumerate(zip(bits(A), bits(S))) if p != q]; varpos = dv[-1] - 7
            div_pos = field_starts(A, cb(0, 0, div=128)[1]); hl_pos = field_starts(A, cb(0, 0, hl=127)[1])
            seqs = sorted([m_ for m_ in pc.patch.voice.modules if m_.type.shortnm == 'SeqNote' and m_.name != 'Chord Step'], key=lambda m_: m_.index)
            vr = [[None] * n for _ in range(K)]
            for j, m_ in enumerate(seqs):
                v, _, b = m_.name.split(); vr[int(v[1:]) - 1][int(b) - 1] = runs[9 * j: 9 * j + 9]
            buf = bytearray(A); want = [[[(random.randint(5, 127), random.randint(0, 1)) for _ in range(16)] for _ in range(n)] for _ in range(K)]
            for v in range(K):
                for b in range(n):
                    for base in vr[v][b]:
                        for i, (nt, r2) in enumerate(want[v][b]): setbit_field(buf, base + 7 * i, 7, nt); setbit_field(buf, base + 112 + 7 * i, 7, r2)
                for base in vr[v][n - 1]: setbit_field(buf, base + 231, 7, 6)
            setbit_field(buf, varpos, 8, 3)
            for p in div_pos: setbit_field(buf, p, 7, 3)
            for p in hl_pos: setbit_field(buf, p, 7, 5)
            chk = Pch2File(); chk.parse_patch(chk.patch, memoryview(bytes(buf)))
            assert chk.patch.description.variation == 3
            assert find(chk, 'Step Clock').params.Divider.variations[:9] == [3] * 9
            assert find(chk, 'Chord Step').params.Length.variations[:9] == [5] * 9
            assert find(chk, 'Chord Step').params.Seq2Step1.variations[0] == 1
            for m_ in chk.patch.voice.modules:
                if m_.type.shortnm != 'SeqNote' or m_.name == 'Chord Step': continue
                v, _, b = m_.name.split(); v = int(v[1:]) - 1; b = int(b) - 1
                assert m_.params.Length.variations[0] == (6 if b == n - 1 else 15)
                for i, (nt, r2) in enumerate(want[v][b]):
                    assert getattr(m_.params, f'Seq1Step{i + 1}').variations[0] == nt
                    assert getattr(m_.params, f'Seq2Step{i + 1}').variations[8] == r2
            fl, am = find(pc, 'Filter'), find(pc, 'Amp Env')
            refs = dict(cutoff=[fl.area.index, fl.index, fl.params.Freq.index], release=[am.area.index, am.index, am.params.Release.index],
                        attack=[am.area.index, am.index, am.params.Attack.index])
            if K not in cref: cref[K] = refs
            assert cref[K] == refs
            out['chord'][K][n] = dict(blob=base64.b64encode(A).decode(), runs=vr, var=varpos, div=div_pos, hl=hl_pos)
        print('chord', K, cap, 'ok')
    out['chord_knobs'] = cref
    # ---------------- chain slots (one track across A -> B -> C -> D)
    import chainslots as CS
    cap = CS.chain_capacity(); out['chain_capacity'] = cap; out['chain'] = {}
    for role in CS.ROLES:
        mk = lambda note, trig, sound=0, div=1: CS.chain_slot(role, [[(note, trig)] * 16 for _ in range(cap)], sound, f'{TMP}/ch.pch2', div)[0]
        pc = mk(0, 0); A = blob(pc); B = blob(mk(127, 1)); S = blob(mk(0, 0, 7))
        runs = note_runs(A, B); assert len(runs) == 9 * cap
        dv = [i for i, (p, q) in enumerate(zip(bits(A), bits(S))) if p != q]; varpos = dv[-1] - 7
        seqs = sorted([m for m in pc.patch.voice.modules if m.type.shortnm == 'SeqNote'], key=lambda m: m.index)
        br = [None] * cap
        for j, m in enumerate(seqs): br[int(m.name.split()[1]) - 1] = runs[9 * j: 9 * j + 9]
        buf = bytearray(A); want = [[(random.randint(0, 127), random.randint(0, 1)) for _ in range(16)] for _ in range(cap)]
        for b in range(cap):
            for base in br[b]:
                for i, (nt, tr) in enumerate(want[b]): setbit_field(buf, base + 7 * i, 7, nt); setbit_field(buf, base + 112 + 7 * i, 7, tr)
        setbit_field(buf, varpos, 8, 4)
        chk = Pch2File(); chk.parse_patch(chk.patch, memoryview(bytes(buf))); assert chk.patch.description.variation == 4
        for m in chk.patch.voice.modules:
            if m.type.shortnm == 'SeqNote':
                b = int(m.name.split()[1]) - 1
                for i, (nt, tr) in enumerate(want[b]):
                    assert getattr(m.params, f'Seq1Step{i + 1}').variations[0] == nt and getattr(m.params, f'Seq2Step{i + 1}').variations[8] == tr
        fl, am = find(pc, 'Filter'), find(pc, 'Amp Env')
        out['chain'][role] = dict(blob=base64.b64encode(A).decode(), runs=br, var=varpos, div=field_starts(A, blob(mk(0, 0, 0, 128))),
                                  knobs=dict(cutoff=[fl.area.index, fl.index, fl.params.Freq.index], release=[am.area.index, am.index, am.params.Release.index],
                                             attack=[am.area.index, am.index, am.params.Attack.index]))
        print('chain', role, len(A), 'bytes ok')
    fl, am = find(pa, 'Filter'), find(pa, 'Amp Env')
    ref = lambda p: [p.module.area.index, p.module.index, p.index]
    D = M.control_patch(f'{TMP}/c.pch2'); F = free_patch(f'{TMP}/f.pch2')
    out['control'] = base64.b64encode(blob(D)).decode(); out['free'] = base64.b64encode(blob(F)).decode()
    out['knobs'] = dict(cutoff=ref(fl.params.Freq), release=ref(am.params.Release), attack=ref(am.params.Attack),
                        room=ref(find(D, 'Room').params.Time), retL=ref(find(D, 'Return L').params.Lev1), retR=ref(find(D, 'Return R').params.Lev1))
    json.dump(out, open(os.path.join(HERE, 'templates.json'), 'w'), separators=(',', ':'))
    print('written', os.path.getsize(os.path.join(HERE, 'templates.json')), 'bytes')

if __name__ == '__main__':
    main()
