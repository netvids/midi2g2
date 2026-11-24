"""NSF (NES Sound Format) reader for midi2g2.

An .nsf file is the game's own 6502 sound driver plus its data. To get notes the driver has to run: this module
emulates the CPU (py65), calls the driver's play routine once per frame, records what it writes to the NES sound
chip (APU, $4000-$4017), models the chip's envelopes / length counters / sweeps per frame, and turns the result
into notes for the two pulse channels and the triangle channel. Noise and DMC (drums / samples) are skipped.
NSF files have no tempo, so one is estimated from the note starts.
The web page has the same logic in JavaScript with its own CPU core; both are checked against each other."""
import math, struct

CPU_HZ = 1789773.0
LEN_TABLE = [10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14, 12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30]
MAX_FRAMES = 60 * 240            # emulate at most 4 minutes
SILENT_END = 180                 # stop after 3 s of silence once something has played
CALL_LIMIT = 400000              # instructions per init/play call
RET = 0x4FF0                     # sentinel return address

def header(data):
    """Parses an .nsf (NESM) or .nsfe (NSFE, chunk based) file into one description: addresses, song count, start song
    (1-based), play speed in microseconds, bank-switch values, texts, per-song labels and lengths (NSFe), and the
    driver's code + data as 'rom'."""
    txt = lambda b: b.split(b'\0')[0].decode('latin1').strip()
    if data[:5] == b'NESM\x1a':
        load, init, play = struct.unpack('<HHH', data[8:14])
        speed = struct.unpack('<H', data[0x6e:0x70])[0] or 16639
        return dict(songs=data[6], start=data[7], load=load, init=init, play=play, title=txt(data[0x0e:0x2e]), artist=txt(data[0x2e:0x4e]),
                    copyright=txt(data[0x4e:0x6e]), speed=speed, banks=list(data[0x70:0x78]), chips=data[0x7b], labels=[], times=[], rom=data[0x80:])
    if data[:4] != b'NSFE': raise ValueError('This is not an NSF or NSFe file.')
    h = dict(songs=1, start=1, load=0x8000, init=0x8000, play=0x8000, title='', artist='', copyright='', speed=16639, banks=[0] * 8, chips=0,
             labels=[], times=[], rom=b'')
    p = 4
    while p + 8 <= len(data):
        n = struct.unpack('<I', data[p:p + 4])[0]; cid = data[p + 4:p + 8]; body = data[p + 8:p + 8 + n]; p += 8 + n
        if cid == b'INFO' and n >= 8:
            h['load'], h['init'], h['play'] = struct.unpack('<HHH', body[:6]); h['chips'] = body[7]
            if n >= 9: h['songs'] = body[8]
            if n >= 10: h['start'] = body[9] + 1                     # NSFe counts the starting song from 0
        elif cid == b'DATA': h['rom'] = body
        elif cid == b'BANK': h['banks'] = (list(body[:8]) + [0] * 8)[:8]
        elif cid == b'RATE' and n >= 2: h['speed'] = struct.unpack('<H', body[:2])[0] or 16639
        elif cid == b'auth':
            parts = body.split(b'\0'); parts += [b''] * 3
            h['title'], h['artist'], h['copyright'] = (x.decode('latin1').strip() for x in parts[:3])
        elif cid == b'tlbl': h['labels'] = [x.decode('latin1').strip() for x in body.split(b'\0')][:h['songs'] if h['songs'] else None]
        elif cid == b'time': h['times'] = [struct.unpack('<i', body[k:k + 4])[0] for k in range(0, n - n % 4, 4)]
        elif cid == b'NEND': break
    if not h['rom']: raise ValueError('This NSFe file has no DATA chunk.')
    h['start'] = max(1, min(h['start'], h['songs']))            # some exporters store the start song 1-based
    return h

def expansion_reg(chips, a):
    """Is `a` a sound register of an expansion chip this file uses? VRC6 (bit 0): $9000-2, $A000-2, $B000-2.
    VRC7 (bit 1): $9010 (register select) and $9030 (data)."""
    return bool((chips & 1 and (a & 0xCFFC) == 0x8000 and 0x9000 <= a <= 0xB002) or (chips & 2 and a in (0x9010, 0x9030)))

class Machine:
    """NSF memory map on top of a 6502 core: RAM, $5FF8-$5FFF bank switching, APU write log."""
    def __init__(self, data):
        from py65.devices.mpu6502 import MPU
        from py65.memory import ObservableMemory
        self.h = header(data); self.rom = self.h['rom']; self.banked = any(self.h['banks'])
        self.mem = ObservableMemory(subject=[0] * 0x10000)
        self.writes = []
        self.mem.subscribe_to_write(range(0x4000, 0x4018), lambda a, v: self.writes.append((a, v)))
        if self.banked:
            pad = self.h['load'] & 0xFFF; self.padded = bytes(pad) + self.rom
            self.mem.subscribe_to_write(range(0x5FF8, 0x6000), lambda a, v: self.bank(a - 0x5FF8, v))
        chips = self.h['chips']
        def rom_write(a, v):                                        # ROM: writes change nothing, but expansion chips listen here
            if expansion_reg(chips, a): self.writes.append((a, v))
            return self.mem._subject[a]
        self.mem.subscribe_to_write(range(0x8000, 0x10000), rom_write)
        self.cpu = MPU(memory=self.mem)

    def bank(self, slot, n):
        base = 0x8000 + slot * 0x1000; page = self.padded[n * 0x1000:(n + 1) * 0x1000]
        page = page + bytes(0x1000 - len(page))
        for i, b in enumerate(page): self.mem._subject[base + i] = b

    def reset(self, song):
        m = self.mem._subject
        for i in range(0x10000): m[i] = 0
        if self.banked:
            for s, n in enumerate(self.h['banks']): self.bank(s, n)
        else:
            for i, b in enumerate(self.rom[:0x10000 - self.h['load']]): m[self.h['load'] + i] = b
        self.writes = []
        self.call(self.h['init'], a=song, x=0)

    def call(self, addr, a=0, x=0):
        c = self.cpu
        c.a, c.x, c.y, c.sp, c.p = a & 0xFF, x & 0xFF, 0, 0xFF, 0x24
        m = self.mem._subject
        m[0x1FF] = (RET - 1) >> 8; m[0x1FE] = (RET - 1) & 0xFF; c.sp = 0xFD
        c.pc = addr
        for _ in range(CALL_LIMIT):
            if c.pc == RET or m[c.pc] == 0x00: return True       # returned (or hit BRK: the driver is done for this call)
            c.step(); c.p &= 0xF7                                 # the NES CPU has no decimal mode
        return False

def frame_limit(h, song):
    """NSFe files can give each song's length in milliseconds: read no further than that (and never past 4 minutes)."""
    t = h['times'][song] if song < len(h['times']) else 0
    return min(MAX_FRAMES, (t * 1000 + h['speed'] - 1) // h['speed']) if t > 0 else MAX_FRAMES

def run(data, song, max_frames=MAX_FRAMES):
    """-> list (one per frame) of the APU writes [(addr, value)...] made by the play routine; frame 0 also holds init's."""
    mc = Machine(data); mc.reset(song)
    frames = [list(mc.writes)]; mc.writes = []
    for _ in range(max_frames):
        if not mc.call(mc.h['play']): break
        frames.append(mc.writes); mc.writes = []
    return frames

# ---------------------------------------------------------------- APU model (per frame, not cycle exact)
class Pulse:
    def __init__(self, first):
        self.first = first; self.en = True; self.duty = 0; self.halt = 0; self.const = 0; self.vol = 0
        self.timer = 0; self.length = 0; self.start = False; self.decay = 0; self.div = 0
        self.sw_en = 0; self.sw_p = 0; self.sw_neg = 0; self.sw_shift = 0; self.sw_reload = False; self.sw_div = 0; self.retrig = False
    def write(self, r, v):
        if r == 0: self.duty, self.halt, self.const, self.vol = v >> 6, (v >> 5) & 1, (v >> 4) & 1, v & 15
        elif r == 1: self.sw_en, self.sw_p, self.sw_neg, self.sw_shift, self.sw_reload = v >> 7, (v >> 4) & 7, (v >> 3) & 1, v & 7, True
        elif r == 2: self.timer = (self.timer & 0x700) | v
        else:
            self.timer = (self.timer & 0xFF) | ((v & 7) << 8)
            if self.en: self.length = LEN_TABLE[v >> 3]
            self.start = True; self.retrig = True
    def target(self):
        ch = self.timer >> self.sw_shift
        if self.sw_neg: ch = -ch - (1 if self.first else 0)
        return self.timer + ch
    def quarter(self):
        if self.start: self.start = False; self.decay = 15; self.div = self.vol
        elif self.div == 0:
            self.div = self.vol
            if self.decay > 0: self.decay -= 1
            elif self.halt: self.decay = 15
        else: self.div -= 1
    def half(self):
        if not self.halt and self.length > 0: self.length -= 1
        t = self.target()
        if self.sw_div == 0 and self.sw_en and self.sw_shift and self.timer >= 8 and t <= 0x7FF: self.timer = max(0, t)
        if self.sw_div == 0 or self.sw_reload: self.sw_div = self.sw_p; self.sw_reload = False
        else: self.sw_div -= 1
    def state(self):
        v = self.vol if self.const else self.decay
        on = self.en and self.length > 0 and self.timer >= 8 and self.target() <= 0x7FF and v > 0
        return on, CPU_HZ / (16 * (self.timer + 1)), v

class Triangle:
    def __init__(self):
        self.en = True; self.ctrl = 0; self.rv = 0; self.timer = 0; self.length = 0; self.linear = 0; self.reload = False; self.retrig = False
    def write(self, r, v):
        if r == 0: self.ctrl, self.rv = v >> 7, v & 127
        elif r == 2: self.timer = (self.timer & 0x700) | v
        elif r == 3:
            self.timer = (self.timer & 0xFF) | ((v & 7) << 8)
            if self.en: self.length = LEN_TABLE[v >> 3]
            self.reload = True; self.retrig = True
    def quarter(self):
        if self.reload: self.linear = self.rv
        elif self.linear > 0: self.linear -= 1
        if not self.ctrl: self.reload = False
    def half(self):
        if not self.ctrl and self.length > 0: self.length -= 1
    def state(self):
        on = self.en and self.length > 0 and self.linear > 0 and self.timer >= 2
        return on, CPU_HZ / (32 * (self.timer + 1)), 8 if on else 0

class VRC6Pulse:                              # Konami VRC6 pulse: no envelope or length counter, the driver sets the volume
    def __init__(self): self.en = 0; self.vol = 0; self.timer = 0; self.retrig = False
    def write(self, r, v):
        if r == 0: self.vol = v & 15
        elif r == 1: self.timer = (self.timer & 0xF00) | v
        else:
            if (v >> 7) and not self.en: self.retrig = True
            self.en = v >> 7; self.timer = (self.timer & 0xFF) | ((v & 15) << 8)
    def quarter(self): pass
    def half(self): pass
    def state(self):
        on = bool(self.en and self.vol > 0 and self.timer > 0)
        return on, CPU_HZ / (16 * (self.timer + 1)), self.vol

class VRC6Saw(VRC6Pulse):
    def write(self, r, v):
        if r == 0: self.vol = (v & 63) >> 2
        else: VRC6Pulse.write(self, r, v)
    def state(self):
        on = bool(self.en and self.vol > 0 and self.timer > 0)
        return on, CPU_HZ / (14 * (self.timer + 1)), self.vol

class VRC7Voice:                              # Konami VRC7 FM voice: frequency number + octave, key on/off
    def __init__(self): self.fnum = 0; self.oct = 0; self.key = 0; self.vol = 0; self.retrig = False
    def write(self, r, v):
        if r == 1: self.fnum = (self.fnum & 0x100) | v
        elif r == 2:
            if (v >> 4) & 1 and not self.key: self.retrig = True
            self.fnum = (self.fnum & 0xFF) | ((v & 1) << 8); self.oct = (v >> 1) & 7; self.key = (v >> 4) & 1
        else: self.vol = 15 - (v & 15)
    def quarter(self): pass
    def half(self): pass
    def state(self):
        on = bool(self.key and self.fnum > 0)
        return on, 49716.0 * (self.fnum or 1) / (1 << (19 - self.oct)), max(1, self.vol)

def channel_names(chips):
    names = ['Pulse 1', 'Pulse 2', 'Triangle']
    if chips & 1: names += ['VRC6 Pulse 1', 'VRC6 Pulse 2', 'VRC6 Saw']
    if chips & 2: names += [f'VRC7 FM {k}' for k in range(1, 7)]
    return names

def extract(frames, chips=0):
    """Sound-chip write log -> per channel list of notes (start frame, end frame, MIDI note) and duty histogram."""
    ch = [Pulse(True), Pulse(False), Triangle()]
    v6 = v7 = None
    if chips & 1: v6 = len(ch); ch += [VRC6Pulse(), VRC6Pulse(), VRC6Saw()]
    if chips & 2: v7 = len(ch); ch += [VRC7Voice() for _ in range(6)]
    nch = len(ch); reg7 = 0
    cur = [None] * nch; raw = [[] for _ in range(nch)]; prev_v = [0] * nch; last_retrig = [-10] * nch; duty = [[0] * 4, [0] * 4]
    last_sound = -1
    for f, writes in enumerate(frames):
        for a, v in writes:
            if 0x4000 <= a <= 0x4007: ch[(a - 0x4000) >> 2].write(a & 3, v)
            elif 0x4008 <= a <= 0x400B: ch[2].write(a & 3, v)
            elif a == 0x4015:
                for i in range(3):
                    ch[i].en = bool(v & (1 << i))
                    if not ch[i].en: ch[i].length = 0
            elif a == 0x9010 and v7 is not None: reg7 = v
            elif a == 0x9030 and v7 is not None:
                if 0x10 <= reg7 <= 0x35 and (reg7 & 15) < 6: ch[v7 + (reg7 & 15)].write(reg7 >> 4, v)
            elif a >= 0x9000 and v6 is not None and (a & 3) < 3: ch[v6 + ((a >> 12) - 9)].write(a & 3, v)
        for q in range(4):
            for c in ch: c.quarter()
            if q & 1:
                for c in ch: c.half()
        for i, c in enumerate(ch):
            on, hz, vol = c.state(); retrig = c.retrig; c.retrig = False
            if not on:
                if cur[i]: raw[i].append(cur[i] + [f]); cur[i] = None
                prev_v[i] = 0; continue
            last_sound = f
            nf = 69 + 12 * math.log2(hz / 440)
            if i < 2: duty[i][c.duty] += 1
            fresh = retrig and f - last_retrig[i] > 2
            if retrig: last_retrig[i] = f
            if cur[i] is None: cur[i] = [f, int(math.floor(nf + 0.5)), True]          # [start, note, started by an attack]
            else:
                attack = f - cur[i][0] >= 3 and (fresh or vol - prev_v[i] >= 4)
                if attack or abs(nf - cur[i][1]) > 0.7: raw[i].append(cur[i] + [f]); cur[i] = [f, int(math.floor(nf + 0.5)), bool(attack)]
            prev_v[i] = vol
        if last_sound >= 0 and f - last_sound > SILENT_END: break
    for i in range(nch):
        if cur[i]: raw[i].append(cur[i] + [len(frames)])
    return [reduce_fast(r) for r in raw], duty

def reduce_fast(raw):
    """raw: [start, note, attacked, end]. Runs of 2+ very short notes (< 3 frames) that follow each other without a
    new attack are one held note played as an arpeggio or a slide (tracker effects): an arpeggio (pitches repeat)
    becomes its lowest note, a slide becomes its last note."""
    out, i, n = [], 0, len(raw)
    while i < n:
        s, note, tr, e = raw[i]
        j = i
        if e - s < 3:
            while j + 1 < n and raw[j + 1][3] - raw[j + 1][0] < 3 and not raw[j + 1][2] and raw[j + 1][0] == raw[j][3]: j += 1
        if j > i:
            ps = [raw[k][1] for k in range(i, j + 1)]
            out.append((s, raw[j][3], min(ps) if len(set(ps)) < len(ps) else ps[-1]))
        else: out.append((s, e, note))
        i = j + 1
    return out

def find_loop(notes, total):
    """Songs loop forever, so the emulation holds the same music several times. Find the frame where the first
    repeat starts (intro + one pass of the loop), or None. Looks for the smallest lag m (in note events) with which the
    end of the piece repeats itself, and accepts it only if that repetition reaches back to the first third."""
    ev = sorted((s, i, n) for i, ns in enumerate(notes) for s, e, n in ns)
    n = len(ev)
    if n < 64: return None
    last = n - 4                                                   # the final events may be cut short by the time limit
    for m in range(16, last // 2 + 1):
        P = ev[last][0] - ev[last - m][0]
        if P <= 0: continue
        lo = last - 2 * m + 1; ok = True
        for i in range(last - m, lo - 1, -1):
            if ev[i][1:] != ev[i + m][1:] or ev[i + m][0] - ev[i][0] != P: ok = False; break
        if not ok: continue
        i0 = lo
        while i0 > 0 and ev[i0 - 1][1:] == ev[i0 - 1 + m][1:] and ev[i0 - 1 + m][0] - ev[i0 - 1][0] == P: i0 -= 1
        if ev[i0][0] * 3 <= total: return ev[i0][0] + P
    return None

def estimate_unit(onsets):
    """Frames per rhythmic unit, in hundredths (300..2400): the largest unit whose multiples fit the note starts about
    as well as the best one. Integer arithmetic only, so Python and JavaScript agree exactly."""
    if len(onsets) < 4: return 800
    best, scores = None, {}
    for uh in range(300, 2401):
        err = 0
        for o in onsets:
            r = (o * 100) % uh; err += min(r, uh - r)
        scores[uh] = (err, uh)                        # mean error fraction = err / (uh * n)
        if best is None or err * best[1] < best[0] * uh: best = (err, uh)
    n = len(onsets); pick = best[1]
    for uh in range(300, 2401):
        err = scores[uh][0]
        # within 0.02 (absolute, as a fraction of the unit) of the best fit
        if err * best[1] * 100 <= best[0] * uh * 100 + 2 * uh * best[1] * n: pick = uh
    return pick

def read_nsf(data, song=None):
    """-> (tracks, bpm, info). tracks like midi2g2.read_midi: dicts with name, notes (beats), program, sound."""
    h = header(data); song = h['start'] if song is None else song
    if not 1 <= song <= h['songs']: raise ValueError(f"This file has songs 1 to {h['songs']}.")
    frames = run(data, song - 1, frame_limit(h, song - 1)); notes, duty = extract(frames, h['chips'])
    loop_end = find_loop(notes, len(frames))
    if loop_end is not None: notes = [[(s, min(e, loop_end), n) for s, e, n in ns if s < loop_end] for ns in notes]
    fps = 1e6 / h['speed']
    onsets = sorted({s for ns in notes for s, e, n in ns})
    t0 = onsets[0] if onsets else 0
    uh = estimate_unit([o - t0 for o in onsets])
    beat = None
    for k in (4, 2, 8, 1, 16):                        # how many units make a beat: first choice giving a sensible tempo
        b = 60 * fps * 100 / (uh * k)
        if 70 <= b <= 190: beat = uh * k; break
    if beat is None: beat = uh * 4
    bpm = 60 * fps * 100 / beat
    tracks = []
    for i, name in enumerate(channel_names(h['chips'])):
        ns = [((s - t0) * 100 / beat, (e - t0) * 100 / beat, n, 100, ()) for s, e, n in notes[i] if e - s >= 1 and 5 <= n <= 127]
        if not ns: continue
        sound = None
        if i < 2: sound = 2 if duty[i][2] + duty[i][3] >= duty[i][0] + duty[i][1] else 3      # 50%/75% duty -> square, 12.5%/25% -> pulse
        elif name.startswith('VRC6'): sound = 4 if name.endswith('Saw') else 2
        tracks.append(dict(name=name, notes=sorted(ns), program=None, sound=sound))
    info = dict(h, song=song, frames=len(frames), loop_end=loop_end); del info['rom']
    return tracks, bpm, info
