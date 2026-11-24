"""Builds a tiny public-domain test NSF: a hand-assembled 6502 driver playing Ode to Joy (Beethoven) on pulse 1
with a triangle bass. Used to test the NSF reader end to end."""
import struct
CPU=1789773.0
def hz(n): return 440*2**((n-69)/12)
def pper(n): return round(CPU/(16*hz(n)))-1
def tper(n): return round(CPU/(32*hz(n)))-1
E,F,G,D,C=76,77,79,74,72
Q=28                                   # frames per quarter note (128.6 BPM at 60 Hz)
mel=[(E,Q),(E,Q),(F,Q),(G,Q),(G,Q),(F,Q),(E,Q),(D,Q),(C,Q),(C,Q),(D,Q),(E,Q),(E,Q+Q//2),(D,Q//2),(D,Q),(None,Q),
     (E,Q),(E,Q),(F,Q),(G,Q),(G,Q),(F,Q),(E,Q),(D,Q),(C,Q),(C,Q),(D,Q),(E,Q),(D,Q+Q//2),(C,Q//2),(C,Q),(None,Q)]
bass=[(48,2*Q),(43,2*Q)]*8
assert len(mel)==32 and len(bass)==16
dur1=[d for n,d in mel]; lo1=[(pper(n)&255) if n else 0 for n,d in mel]; hi1=[((pper(n)>>8)|0x08) if n else 0x08 for n,d in mel]; vol1=[0xBF if n else 0xB0 for n,d in mel]
dur2=[d for n,d in bass]; lo2=[tper(n)&255 for n,d in bass]; hi2=[(tper(n)>>8)|0x08 for n,d in bass]; lin2=[0xFF]*16
# ---- mini assembler: items are ints (bytes), ('abs', label) -> 2 bytes little endian, ('rel', label) -> 1 byte, ('label', name)
prog=[('label','init'),0xA9,0,0x85,0,0x85,2,0xA9,1,0x85,1,0x85,3,0xA9,7,0x8D,0x15,0x40,0x60,
 ('label','play'),0xC6,1,0xD0,('rel','tri'),
   0xA6,0,0xBD,('abs','dur1'),0x85,1,0xBD,('abs','vol1'),0x8D,0x00,0x40,0xBD,('abs','lo1'),0x8D,0x02,0x40,0xBD,('abs','hi1'),0x8D,0x03,0x40,
   0xE8,0x8A,0x29,0x1F,0x85,0,
 ('label','tri'),0xC6,3,0xD0,('rel','done'),
   0xA6,2,0xBD,('abs','dur2'),0x85,3,0xBD,('abs','lin2'),0x8D,0x08,0x40,0xBD,('abs','lo2'),0x8D,0x0A,0x40,0xBD,('abs','hi2'),0x8D,0x0B,0x40,
   0xE8,0x8A,0x29,0x0F,0x85,2,
 ('label','done'),0x60]
for name,tab in (('dur1',dur1),('vol1',vol1),('lo1',lo1),('hi1',hi1),('dur2',dur2),('lin2',lin2),('lo2',lo2),('hi2',hi2)): prog+=[('label',name)]+tab
BASE=0x8000; labels={}; pc=BASE
for it in prog:
    if isinstance(it,tuple):
        if it[0]=='label': labels[it[1]]=pc
        else: pc+=2 if it[0]=='abs' else 1
    else: pc+=1
code=bytearray(); pc=BASE
for it in prog:
    if isinstance(it,tuple):
        if it[0]=='label': continue
        if it[0]=='abs': code+=struct.pack('<H',labels[it[1]]); pc+=2
        else: off=labels[it[1]]-(pc+1); assert -128<=off<=127; code.append(off&255); pc+=1
    else: code.append(it); pc+=1
def txt(s): return s.encode()+bytes(32-len(s))
hdr=b'NESM\x1a'+bytes([1,1,1])+struct.pack('<HHH',BASE,labels['init'],labels['play'])+txt('Ode to Joy (test)')+txt('L. van Beethoven')+txt('public domain')+struct.pack('<H',16666)+bytes(8)+struct.pack('<H',20000)+bytes([0,0])+bytes(4)
assert len(hdr)==0x80
open('Ode to Joy test.nsf','wb').write(hdr+bytes(code)); print('nsf bytes',len(hdr)+len(code))
