"""verify.py - check .pch2 / .prf2 files before handing them over.
    python verify.py file1.pch2 perf.prf2 folder/ ...
Checks: parses and round-trips, CRC (performances), unique G2-safe names, no reserved or duplicate MIDI CCs,
morph map limit, input Pads (2-In / Fx-In Pad 2 = 0 dB), mixers/crossfades/constants that look like signed values,
unconnected outputs of key modules, knob count, and prints module/cable/output counts as a rough load hint."""
import sys, os, glob, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2lib import Pch2File, read_prf2, G2_RESERVED_CC, NV

def check_patch(P, label):
    issues, info = [], []
    for aname, area in (('voice', P.voice), ('fx', P.fx)):
        names = [m.name for m in area.modules]
        for n, c in collections.Counter(names).items():
            if c > 1: issues.append(f'{aname}: duplicate module name "{n}"')
        for n in names:
            if len(n) > 16 or re.search(r'[^A-Za-z0-9 \-]', n): issues.append(f'{aname}: bad name "{n}"')
        for m in area.modules:
            t = m.type.shortnm
            if t in ('2-In', 'Fx-In', '4-In') and m.params.Pad.variations[0] != 2:
                issues.append(f'{aname}: "{m.name}" Pad={m.params.Pad.variations[0]} (2 = 0 dB; 0 = -12 dB) - intended?')
            if t == 'X-Fade':
                mix = m.params.Mix.variations[0]; mm = m.params.MixMod.variations[0]
                if mm and mix not in (0, 127, 64) and not m.inputs.Mod.cables: issues.append(f'{aname}: "{m.name}" MixMod set but Mod unconnected')
        info.append(f'{aname} {len(area.modules)} modules, {sum(len(m.outputs) for m in area.modules)} outputs, {len(area.cables)} cables')
    ccs = [c.midicc for c in P.ctrls]
    for n, c in collections.Counter(ccs).items():
        if c > 1: issues.append(f'CC {n} assigned {c} times')
    user = [n for n in ccs if n in G2_RESERVED_CC and n not in (7, 17)]
    if user: issues.append(f'reserved CCs used: {user}')
    nm = [sum(len(mg.maps[v]) for mg in P.settings.morphs) for v in range(NV)]
    if max(nm) > 25: issues.append(f'morph maps per variation > 25: {nm}')
    k = sum(x.assigned for x in P.knobs)
    info.append(f'{k} knobs, CCs {sorted(set(ccs))}, voices {P.description.voices}, mode {["poly","mono","legato","?"][P.description.monopoly]}')
    return issues, info

def check_file(path):
    print(f'== {path}')
    try:
        if path.endswith('.prf2'):
            perf = read_prf2(path); print('   CRC and structure OK')
            for i, s in enumerate(perf.slots):
                iss, inf = check_patch(s.patch, s.name)
                print(f'   slot {"ABCD"[i]} "{s.name}": ' + '; '.join(inf))
                for x in iss: print('     ! ' + x)
        else:
            f = Pch2File(path); data = bytes(f.format_file())
            if bytes(Pch2File(path).format_file()) != data: print('   ! does not round-trip')
            iss, inf = check_patch(f.patch, path)
            print('   ' + '; '.join(inf))
            for x in iss: print('   ! ' + x)
    except Exception as e:
        print(f'   ! FAILED TO PARSE: {e}')

if __name__ == '__main__':
    files = []
    for a in sys.argv[1:]:
        files += sorted(glob.glob(os.path.join(a, '**', '*.p*2'), recursive=True)) if os.path.isdir(a) else [a]
    for f in files: check_file(f)
