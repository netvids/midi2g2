"""g2lib - helpers for building Nord Modular G2 patches (.pch2) and performances (.prf2) with g2ools.

    import sys; sys.path.insert(0, '<this folder>'); from g2lib import *
    pch2, P = new_patch(voices=1, mode='mono')          # P = the patch
    col = Stack(P.voice, 0); osc = col.add('OscB', 'VCO')
    setp(osc.params.Waveform, 2)                        # one value, or a list of 8 (variations 1-8)
    con(P.voice, osc.outputs.Out, out.inputs.InL, RED)
    knobs(P, 'A1', [osc.params.FreqCoarse, ...])        # 8 knobs per page A1..E3
    cc(P, 74, flt.params.Freq)                          # refuses reserved / duplicate CCs
    save(pch2, 'out.pch2')                              # names cleaned, audio-rate marked, re-parsed, checked
    write_prf2('perf.prf2', [slotA, slotB, slotC, slotD], bpm=128, global_knobs=[...])

Every parameter value is RAW 0..127 (64 = centre on bipolar knobs). Never write signed values (-64..63).
"""
import os, sys, re, math, struct
G2OOLS = os.environ.get('G2OOLS') or next((p for p in (os.path.expanduser('~/g2ools'),) if os.path.isdir(p)), None)
if not G2OOLS or not os.path.isdir(G2OOLS):
    raise SystemExit('g2ools not found: run python/setup_g2ools.sh and export G2OOLS=<path>')
sys.path.insert(0, G2OOLS)
from nord.g2.file import Pch2File, crc, PerformanceDescription
from nord.g2.bits import BitStream
from nord.file import MorphMap, Ctrl, Performance
from nord.g2.colors import g2cablecolors as CC, g2modulecolors as MC, g2conncolors
import nord.g2.modules as MODULES

RED, BLUE, YEL = CC.red, CC.blue, CC.yellow
NV = 9                                    # 8 variations + init (index 8 copies variation 1)
# morph groups (index): 0 Wheel, 1 Velocity, 2 Keyboard, 3 Aftertouch, 4 Sustain pedal, 5 Control pedal, 6 Pitch stick, 7 G.Wheel 2
WHEEL, VEL, KEYB, AT, SUSTAIN, CTRLPED, PSTICK, GWHEEL2 = range(8)
G2_RESERVED_CC = {0, 1, 7, 11, 17, 18, 19, 32, 64, 70, 80} | set(range(120, 128))
PAGES = {f'{p}{c}': 24 * 'ABCDE'.index(p) + 8 * (c - 1) for p in 'ABCDE' for c in (1, 2, 3)}   # 'A1' -> 0 ... 'E3' -> 112

# ------------------------------------------------------------------ values
def setp(param, values):
    """Set a parameter for variations 1-8 (init copies 1). Values are clamped to 0..127 - pass RAW values, never signed."""
    if not isinstance(values, (list, tuple)): values = [values] * 8
    vals = [max(0, min(127, int(round(x)))) for x in values]
    for v in range(8): param.variations[v] = vals[v]
    param.variations[8] = vals[0]

_G2T = None
def env_time(ms):
    """Milliseconds -> EnvTime value (0 = 0.5 ms, 127 = 45 s), from g2ools' measured table."""
    global _G2T
    if _G2T is None: _G2T = [float(l.split()[1]) for l in open(os.path.join(G2OOLS, 'build', 'g2adsrtime.txt')) if l.strip()]
    return min(range(128), key=lambda i: abs(math.log(_G2T[i]) - math.log(max(0.5, ms))))
def glide_time(ms):     return int(max(0, min(127, round(64 * (math.log(ms) - math.log(0.2)) / (math.log(511) - math.log(0.2))))))
def filter_freq(hz):    return int(max(0, min(127, round(64 + 12 * math.log2(hz / 554.37)))))   # FltFreq: 64 = 554 Hz, semitone steps
def osc_coarse(semis):  return int(max(0, min(127, 64 + semis)))                               # FreqCoarse: 64 = 0 semitones
def bip(units):         return int(max(0, min(127, 64 + units)))                                # bipolar knob: 64 = 0
def levamp_gain(x):     return int(max(0, min(127, round(64 + 63 * math.log(max(x, 1e-6)) / math.log(4)))))   # LevAmp: 64 = x1, 127 = x4

# ------------------------------------------------------------------ building
def new_patch(voices=1, mode='poly', category=12):
    """mode: 'poly' | 'mono' | 'legato'. Returns (pch2_file, patch)."""
    pch2 = Pch2File(os.path.join(G2OOLS, 'initpatch.pch2')); P = pch2.patch; d = P.description
    d.monopoly = {'poly': 0, 'mono': 1, 'legato': 2}[mode]; d.voices = voices; d.category = category; d.height = 640
    return pch2, P

class Stack:
    """Places modules top-to-bottom in one column of an area (patch.voice or patch.fx). Use one column per section."""
    def __init__(self, area, col): self.area, self.col, self.v = area, col, 0
    def add(self, kind, name, color=None):
        kw = {'color': color} if color is not None else {}
        m = self.area.add_module(kind, name=name[:16], horiz=self.col, vert=self.v, **kw)
        self.v += m.type.height
        return m
    def label(self, text): return self.add('Name', text.upper())

def con(area, a, b, color=RED): area.connect(a, b, color)
def out(module, name): return getattr(module.outputs, name)          # for names like '1/16': out(clk, '1/16')

def knob(patch, idx, param):
    k = patch.knobs[idx]; k.assigned = 1; k.isled = 0; k.param = param; param.knob = k
def knobs(patch, page, params):
    """page: 'A1'..'E3' or an index (A1=0, A2=8, A3=16, B1=24 ... E3=112). None skips a knob."""
    start = PAGES[page] if isinstance(page, str) else page
    for i, prm in enumerate(params):
        if prm is not None: knob(patch, start + i, prm)

def cc(patch, num, param):
    """Assign MIDI CC. Silently refuses G2-reserved CCs and duplicates - check the return value."""
    if param is None or num in G2_RESERVED_CC: return False
    if any(c.midicc == num for c in patch.ctrls): return False
    c = Ctrl(); c.midicc = num; c.param = param; param.ctrl = c; patch.ctrls.append(c); return True

def morph(patch, group, param, ranges):
    """Morph group (WHEEL, VEL, ...) moves param by a signed range (-127..127), per variation (list of 8) or all. Max 25 maps/variation."""
    mg = patch.settings.morphs[group]
    if not isinstance(ranges, (list, tuple)): ranges = [ranges] * 8
    for v in range(NV):
        r = int(max(-127, min(127, ranges[v if v < 8 else 0])))
        if r:
            mm = MorphMap(); mm.param, mm.morph, mm.range, mm.variation = param, mg, r, v; mg.maps[v].append(mm)

def clean_names(patch):
    """G2-safe module names: letters, digits, space, '-' only; max 16 chars; unique per area."""
    for area in (patch.voice, patch.fx):
        seen = set()
        for m in area.modules:
            n = m.name
            for a, b in (('>', '-'), ('=', ' '), ('+', ' '), ('/', '-'), ('%', 'pc'), ('.', ' '), ('~', ''), ('(', ' '), (')', ' ')): n = n.replace(a, b)
            n = re.sub(r'[^A-Za-z0-9 \-]', '', n); n = re.sub(r' +', ' ', n).strip()[:16].strip() or m.type.shortnm[:16]
            base, i = n, 2
            while n in seen: n = base[:14] + str(i); i += 1
            seen.add(n); m.name = n

def uprate(area):
    """Mark modules whose blue/red inputs carry audio as audio-rate (what the editor does). Required before saving."""
    changed = True
    while changed:
        changed = False
        for m in area.modules:
            if m.uprate: continue
            for inp in m.inputs:
                if inp.type.type != g2conncolors.blue_red: continue
                for c in inp.cables:
                    src = c.source if c.dest is inp else c.dest
                    if src.direction and (src.type.type == g2conncolors.red or src.module.uprate):
                        m.uprate = 1; changed = True

def set_text(patch, text): patch.textpad = text[:2000]

def save(pch2, path):
    """Clean names, mark audio rate, write, re-parse and compare bytes, check morph limits. Returns the re-read Pch2File."""
    P = pch2.patch; clean_names(P); uprate(P.voice); uprate(P.fx)
    data = pch2.format_file(); open(path, 'wb').write(data)
    chk = Pch2File(path)
    assert bytes(chk.format_file()) == bytes(data), 'round-trip mismatch'
    n = [sum(len(mg.maps[v]) for mg in chk.patch.settings.morphs) for v in range(NV)]
    assert max(n) <= 25, f'more than 25 morph maps in a variation: {n}'
    return chk

def load(path): return Pch2File(path)

def free_patch(path, label='Free Slot'):
    pch2, P = new_patch(); Stack(P.voice, 0).label(label); set_text(P, 'Empty slot - load any patch here.'); return save(pch2, path)

# ------------------------------------------------------------------ performances
def write_prf2(path, slots, bpm=120, global_knobs=(), range_enabled=0, clock_run=1):
    """slots: EXACTLY 4 dicts (name, patch=<Pch2File from save()>, enabled, keyboard, lo=0, hi=127).
    global_knobs: list of (index 0-119, slot 0-3, param) - the 120 performance knobs (8 per page, pages A1..E3)."""
    assert len(slots) == 4, 'a performance needs 4 slots (use free_patch() for empty ones)'
    data = bytearray(1 << 20); mv = memoryview(data)
    hdr = 'Version=Nord Modular G2 File Format 1\r\nType=Performance\r\nVersion=23\r\nInfo=BUILD 320\r\n\0'.encode('latin1')
    mv[:len(hdr)] = hdr; body = mv[len(hdr):]; body[0] = 23; body[1] = 1; cur = body[2:]
    bs = BitStream(cur[3:])
    for nbits, val in [(8, 0), (4, 0), (2, 0), (2, 0), (8, range_enabled), (8, bpm), (8, 0), (8, clock_run), (8, 0), (8, 0)]: bs.write_bits(nbits, val)
    for s in slots:
        name = s['name'][:16]; bs.write_str(name + ('\0' if len(name) < 16 else ''))
        for val in [s['enabled'], s['keyboard'], 0, 0, 0, s.get('lo', 0), s.get('hi', 127), 0, 0, 0]: bs.write_bits(8, val)
    nbytes = (bs.tell_bit() + 7) >> 3; cur[:3] = struct.pack('>BH', 0x11, nbytes); cur = cur[3 + nbytes:]
    for s in slots: cur = s['patch'].format_patch(s['patch'].patch, cur)
    gk = {i: (slot, prm) for i, slot, prm in global_knobs}
    bs = BitStream(cur[3:]); bs.write_bits(16, 120)
    for i in range(120):
        if i in gk:
            slot, prm = gk[i]; bs.write_bits(1, 1); bs.write_bitsa([2, 8, 2, 7, 2], [prm.module.area.index, prm.module.index, 0, prm.index, slot])
        else: bs.write_bits(1, 0)
    nbytes = (bs.tell_bit() + 7) >> 3; cur[:3] = struct.pack('>BH', 0x5f, nbytes); cur = cur[3 + nbytes:]
    used = len(body) - len(cur); body[used:used + 2] = struct.pack('>H', crc(body[:used]))
    open(path, 'wb').write(bytes(data[:len(hdr) + used + 2]))
    return read_prf2(path)

def read_prf2(path):
    """Parse a .prf2, verify CRC and that the global-knob section is consumed exactly. Returns the Performance."""
    raw = open(path, 'rb').read(); body = memoryview(raw)[raw.find(0) + 1:]
    assert struct.unpack('>H', bytes(body[-2:]))[0] == crc(body[:-2]), f'{path}: bad CRC'
    mv = body[2:-2]; perf = Performance(MODULES.fromname); p = Pch2File()
    mv = p.parse_section(PerformanceDescription(), perf, mv)
    for s in perf.slots: mv = p.parse_patch(s.patch, mv)
    t, l = struct.unpack('>BH', bytes(mv[:3])); assert t == 0x5f and len(mv) - 3 - l == 0, f'{path}: trailing data'
    return perf

def find(patch_or_file, name):
    P = getattr(patch_or_file, 'patch', patch_or_file)
    return next(m for m in P.voice.modules + P.fx.modules if m.name == name)
