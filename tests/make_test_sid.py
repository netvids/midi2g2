"""Builds a tiny public-domain test SID (PSID v2): a hand-assembled C64 player playing Ode to Joy (Beethoven) on
voice 1 (pulse) with a sawtooth bass on voice 3. Used to test the SID reader end to end."""
import struct
CLOCK=985248.0
def hz(n): return 440*2**((n-69)/12)
def sf(n): return round(hz(n)*16777216/CLOCK)
E,F,G,D,C=76,77,79,74,72
Q=24                                   # frames per quarter note (125.3 BPM at 50.12 Hz)
mel=[(E,Q),(E,Q),(F,Q),(G,Q),(G,Q),(F,Q),(E,Q),(D,Q),(C,Q),(C,Q),(D,Q),(E,Q),(E,Q+Q//2),(D,Q//2),(D,Q),(None,Q),
     (E,Q),(E,Q),(F,Q),(G,Q),(G,Q),(F,Q),(E,Q),(D,Q),(C,Q),(C,Q),(D,Q),(E,Q),(D,Q+Q//2),(C,Q//2),(C,Q),(None,Q)]
bass=[(48,2*Q),(43,2*Q)]*8
dur1=[d for n,d in mel]; lo1=[sf(n)&255 if n else 0 for n,d in mel]; hi1=[sf(n)>>8 if n else 0 for n,d in mel]; ctl1=[0x41 if n else 0x40 for n,d in mel]
dur2=[d for n,d in bass]; lo2=[sf(n)&255 for n,d in bass]; hi2=[sf(n)>>8 for n,d in bass]
I1,C1,I2,C2=0xFB,0xFC,0xFD,0xFE
def sta(a): return [0x8D,a&255,a>>8]
prog=[('label','init'),0xA9,0x0F]+sta(0xD418)+[0xA9,0,0x85,I1,0x85,I2,0xA9,1,0x85,C1,0x85,C2,
      0xA9,0x08]+sta(0xD403)+[0xA9,0x09]+sta(0xD405)+sta(0xD413)+[0xA9,0xA0]+sta(0xD406)+sta(0xD414)+[0x60,
 ('label','play'),0xC6,C1,0xD0,('rel','v3'),
   0xA6,I1,0xBD,('abs','dur1'),0x85,C1,0xA9,0x40]+sta(0xD404)+[0xBD,('abs','lo1')]+sta(0xD400)+[0xBD,('abs','hi1')]+sta(0xD401)+[0xBD,('abs','ctl1')]+sta(0xD404)+[
   0xE8,0x8A,0x29,0x1F,0x85,I1,
 ('label','v3'),0xC6,C2,0xD0,('rel','done'),
   0xA6,I2,0xBD,('abs','dur2'),0x85,C2,0xA9,0x20]+sta(0xD412)+[0xBD,('abs','lo2')]+sta(0xD40E)+[0xBD,('abs','hi2')]+sta(0xD40F)+[0xA9,0x21]+sta(0xD412)+[
   0xE8,0x8A,0x29,0x0F,0x85,I2,
 ('label','done'),0x60]
for name,tab in (('dur1',dur1),('lo1',lo1),('hi1',hi1),('ctl1',ctl1),('dur2',dur2),('lo2',lo2),('hi2',hi2)): prog+=[('label',name)]+tab
BASE=0x1000; labels={}; pc=BASE
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
hdr=b'PSID'+struct.pack('>HHHHHHH',2,0x7C,0,labels['init'],labels['play'],1,1)+struct.pack('>I',0)+txt('Ode to Joy (test)')+txt('L. van Beethoven')+txt('public domain')+struct.pack('>H',0x0004)+bytes(4)
assert len(hdr)==0x7C
open('Ode to Joy test.sid','wb').write(hdr+struct.pack('<H',BASE)+bytes(code)); print('sid bytes',len(hdr)+2+len(code))
