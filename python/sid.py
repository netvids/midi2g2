"""SID (Commodore 64, PSID / RSID) reader for midi2g2.

Like an NSF, a .sid file is the tune's own 6502 player code plus data. This module runs it (py65 CPU), calls the
play routine once per frame (50 Hz PAL, 60 Hz NTSC, or the CIA timer rate the tune sets), and reads the three SID
voices after every call: frequency, gate, waveform and ADSR. A simple envelope model decides when a voice sounds.
Each voice becomes one line of notes. Noise-only sounds (drums) are skipped. Fast arpeggios and slides inside one
held note are reduced to a single note. Tempo and loop are estimated as for NSF files.
Limits: tunes that need a full C64 (many RSID files: raster interrupts, digis, BASIC) may read wrong or not at all;
the CPU has no decimal mode and no undocumented opcodes."""
import math, struct
from nsf import find_loop, estimate_unit, reduce_fast, CALL_LIMIT, RET

PAL_CLOCK, NTSC_CLOCK = 985248.0, 1022727.0
MAX_SECONDS = 240
ATTACK_MS = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]      # 0 -> full
DECAY_MS = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]   # full -> 0 (also release)
KERNAL_EXITS = (0xEA31, 0xEA81, 0xEA7E)        # where an interrupt handler jumps when it is done
INIT_LIMIT = 4000000

def header(data):
    if data[:4] not in (b'PSID', b'RSID'): raise ValueError('This is not a SID file (no PSID/RSID header).')
    ver, off, load, init, play, songs, start = struct.unpack('>HHHHHHH', data[4:18])
    speed = struct.unpack('>I', data[18:22])[0]
    txt = lambda a: data[a:a + 32].split(b'\0')[0].decode('latin1').strip()
    flags = struct.unpack('>H', data[0x76:0x78])[0] if ver >= 2 and off >= 0x7C else 0
    body = data[off:]
    if load == 0: load = body[0] | body[1] << 8; body = body[2:]
    return dict(kind=data[:4].decode(), songs=songs or 1, start=start or 1, load=load, init=init or load, play=play, speed=speed,
                title=txt(0x16), artist=txt(0x36), copyright=txt(0x56), ntsc=((flags >> 2) & 3) == 2, labels=[], rom=body)

class Machine:
    def __init__(self, data):
        from py65.devices.mpu6502 import MPU
        from py65.memory import ObservableMemory
        self.h = header(data); self.mem = ObservableMemory(subject=[0] * 0x10000); self.m = self.mem._subject
        self.ctrl_writes = []                                       # (voice, value) writes to the three control registers
        self.mem.subscribe_to_write([0xD404, 0xD40B, 0xD412], lambda a, v: self.ctrl_writes.append(((a - 0xD404) // 7, v)))
        self.cpu = MPU(memory=self.mem)

    def run(self, addr, a=0, limit=CALL_LIMIT, irq=False):
        c, m = self.cpu, self.m
        c.a, c.x, c.y, c.p = a & 0xFF, 0, 0, 0x24
        if irq: m[0x1FF] = RET >> 8; m[0x1FE] = RET & 0xFF; m[0x1FD] = 0x24; c.sp = 0xFC      # as pushed by an interrupt: PC, then P
        else: m[0x1FF] = (RET - 1) >> 8; m[0x1FE] = (RET - 1) & 0xFF; c.sp = 0xFD
        c.pc = addr
        for _ in range(limit):
            if c.pc == RET or m[c.pc] == 0x00 or (irq and c.pc in KERNAL_EXITS): return True
            c.step(); c.p &= 0xF7
        return False

    def reset(self, song):
        m, h = self.m, self.h
        for i in range(0x10000): m[i] = 0
        rom = h['rom'][:0x10000 - h['load']]
        for i, b in enumerate(rom): m[h['load'] + i] = b
        m[1] = 0x37; self.ctrl_writes = []
        self.run(h['init'], a=song, limit=INIT_LIMIT)
        play = h['play']; self.irq = False
        if play == 0:                                               # the tune installed its own interrupt handler
            play = m[0x314] | m[0x315] << 8; self.irq = True
            if play == 0: play = m[0xFFFE] | m[0xFFFF] << 8
        self.play = play
        clock = NTSC_CLOCK if h['ntsc'] else PAL_CLOCK
        if (h['speed'] >> min(song, 31)) & 1:                       # CIA timer speed
            latch = m[0xDC04] | m[0xDC05] << 8
            fps = clock / (latch + 1) if latch else 60.0
            if not 20 <= fps <= 400: fps = 60.0
        else: fps = clock / (17095 if h['ntsc'] else 19656)         # one video frame
        self.clock, self.fps = clock, fps

def frames(data, song):
    """-> (per frame list of [per voice (freq, control, AD, SR, triggered)], fps, clock)."""
    mc = Machine(data); mc.reset(song); m = mc.m
    out, gate = [], [0, 0, 0]
    if mc.play == 0: return out, mc.fps, mc.clock
    for f in range(int(MAX_SECONDS * mc.fps)):
        if f: mc.ctrl_writes = []                                   # frame 0 keeps init's writes: some tunes open the gate there, once
        if not mc.run(mc.play, irq=mc.irq): break
        trig = [False, False, False]
        for v, val in mc.ctrl_writes:
            g = val & 1
            if g and not gate[v]: trig[v] = True
            gate[v] = g
        out.append([(m[0xD400 + 7 * v] | m[0xD401 + 7 * v] << 8, m[0xD404 + 7 * v], m[0xD405 + 7 * v], m[0xD406 + 7 * v], trig[v]) for v in range(3)])
    return out, mc.fps, mc.clock

def extract(frs, fps, clock):
    """-> (notes per voice [(start frame, end frame, note)], waveform counts per voice [tri, saw, pulse])."""
    dt = 1000.0 / fps
    notes, waves = [[], [], []], [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for v in range(3):
        level, phase, cur, raw = 0.0, 'r', None, []                 # raw notes: [start, end, note, started by a trigger]
        for f, fr in enumerate(frs):
            freq, ctrl, ad, sr, trig = fr[v]
            if trig: phase = 'a'
            elif not ctrl & 1: phase = 'r'
            if phase == 'a':
                level += 255 * dt / ATTACK_MS[ad >> 4]
                if level >= 255: level = 255.0; phase = 'd'
            elif phase == 'd':
                sus = (sr >> 4) * 17
                level -= 255 * dt / DECAY_MS[ad & 15]
                if level <= sus: level = float(sus)
            else:
                level -= 255 * dt / DECAY_MS[sr & 15]
                if level < 0: level = 0.0
            hz = freq * clock / 16777216
            on = level > 6 and (ctrl & 0x70) and not (ctrl & 0x08) and hz >= 16
            if not on:
                if cur: raw.append(cur + [f]); cur = None
                continue
            for b, bit in enumerate((0x10, 0x20, 0x40)):
                if ctrl & bit: waves[v][b] += 1
            nf = 69 + 12 * math.log2(hz / 440)
            if cur is None: cur = [f, int(math.floor(nf + 0.5)), True]
            elif trig and f - cur[0] >= 1: raw.append(cur + [f]); cur = [f, int(math.floor(nf + 0.5)), True]
            elif abs(nf - cur[1]) > 0.7: raw.append(cur + [f]); cur = [f, int(math.floor(nf + 0.5)), False]
        if cur: raw.append(cur + [len(frs)])
        notes[v] = reduce_fast(raw)
    return notes, waves

def read_sid(data, song=None):
    h = header(data); song = h['start'] if song is None else song
    if not 1 <= song <= h['songs']: raise ValueError(f"This file has songs 1 to {h['songs']}.")
    frs, fps, clock = frames(data, song - 1)
    notes, waves = extract(frs, fps, clock)
    loop_end = find_loop(notes, len(frs))
    if loop_end is not None: notes = [[(s, min(e, loop_end), n) for s, e, n in ns if s < loop_end] for ns in notes]
    onsets = sorted({s for ns in notes for s, e, n in ns}); t0 = onsets[0] if onsets else 0
    uh = estimate_unit([o - t0 for o in onsets])
    beat = None
    for k in (4, 2, 8, 1, 16):
        b = 60 * fps * 100 / (uh * k)
        if 70 <= b <= 190: beat = uh * k; break
    if beat is None: beat = uh * 4
    bpm = 60 * fps * 100 / beat
    tracks = []
    for v in range(3):
        ns = [((s - t0) * 100 / beat, (e - t0) * 100 / beat, n, 100, ()) for s, e, n in notes[v] if e - s >= 1 and 5 <= n <= 127]
        if not ns: continue
        avg = sum(x[2] for x in ns) / len(ns); w = waves[v]
        sound = 7 if avg < 50 else (2 if w[2] >= w[1] and w[2] >= w[0] else 4 if w[1] >= w[0] else 0)   # pulse / saw / triangle
        tracks.append(dict(name=f'Voice {v + 1}', notes=sorted(ns), program=None, sound=sound))
    info = dict(h, song=song, frames=len(frs), loop_end=loop_end, fps=fps); del info['rom']
    return tracks, bpm, info
