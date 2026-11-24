"""General MIDI instrument names and the midi2g2 sound that fits each program (melody sounds / chord sounds)."""
GM_NAMES = """Grand Piano|Bright Piano|Electric Grand|Honky-tonk|Electric Piano 1|Electric Piano 2|Harpsichord|Clavinet|Celesta|Glockenspiel|Music Box|Vibraphone|Marimba|Xylophone|Tubular Bells|Dulcimer|Drawbar Organ|Percussive Organ|Rock Organ|Church Organ|Reed Organ|Accordion|Harmonica|Tango Accordion|Nylon Guitar|Steel Guitar|Jazz Guitar|Clean Guitar|Muted Guitar|Overdriven Guitar|Distortion Guitar|Guitar Harmonics|Acoustic Bass|Finger Bass|Pick Bass|Fretless Bass|Slap Bass 1|Slap Bass 2|Synth Bass 1|Synth Bass 2|Violin|Viola|Cello|Contrabass|Tremolo Strings|Pizzicato Strings|Harp|Timpani|Strings 1|Strings 2|Synth Strings 1|Synth Strings 2|Choir Aahs|Voice Oohs|Synth Voice|Orchestra Hit|Trumpet|Trombone|Tuba|Muted Trumpet|French Horn|Brass Section|Synth Brass 1|Synth Brass 2|Soprano Sax|Alto Sax|Tenor Sax|Baritone Sax|Oboe|English Horn|Bassoon|Clarinet|Piccolo|Flute|Recorder|Pan Flute|Blown Bottle|Shakuhachi|Whistle|Ocarina|Square Lead|Saw Lead|Calliope Lead|Chiff Lead|Charang Lead|Voice Lead|Fifths Lead|Bass + Lead|New Age Pad|Warm Pad|Polysynth Pad|Choir Pad|Bowed Pad|Metallic Pad|Halo Pad|Sweep Pad|Rain FX|Soundtrack FX|Crystal FX|Atmosphere FX|Brightness FX|Goblins FX|Echoes FX|Sci-fi FX|Sitar|Banjo|Shamisen|Koto|Kalimba|Bagpipe|Fiddle|Shanai|Tinkle Bell|Agogo|Steel Drums|Woodblock|Taiko|Melodic Tom|Synth Drum|Reverse Cymbal|Fret Noise|Breath Noise|Seashore|Bird Tweet|Telephone|Helicopter|Applause|Gunshot""".split('|')
assert len(GM_NAMES) == 128
# (first program, last program, melody sound index, chord sound index); melody: 0 Soft Keys 1 Organ 2 Chip Square
# 3 Chip Pulse 4 Warm Saw 5 Pluck 6 Strings 7 Bass; chords: 0 Warm Pad 1 Organ 2 Strings 3 E-Piano 4 Brass
# 5 Square Chords 6 Pluck Chords 7 Soft Sine
GM_MAP = [(0, 7, 0, 3), (8, 15, 5, 6), (16, 23, 1, 1), (24, 31, 5, 6), (32, 39, 7, 6), (40, 44, 6, 2), (45, 46, 5, 6), (47, 47, 7, 6),
          (48, 51, 6, 2), (52, 55, 6, 0), (56, 63, 4, 4), (64, 67, 4, 4), (68, 70, 3, 4), (71, 71, 2, 5), (72, 79, 1, 7), (80, 80, 2, 5),
          (81, 87, 4, 4), (88, 95, 6, 0), (96, 103, 0, 0), (104, 111, 5, 6), (112, 119, 5, 6), (120, 127, 0, 0)]
def gm_sound(program, chords=False):
    for a, b, mel, ch in GM_MAP:
        if a <= program <= b: return ch if chords else mel
    return 0
def default_sound(line, i, n):
    """Starting sound for item i of n chosen items: from the track's GM program when the file has one, else by register."""
    p = line.get('program')
    if line['kind'] == 'chords': return gm_sound(p, True) if p is not None else 0
    if line.get('sound') is not None: return line['sound']          # set by the NSF reader from the pulse duty cycle
    if p is None: return 7 if (i == n - 1 and n > 1 and line['avg'] < 55) else 0
    return 7 if line['avg'] < 50 else gm_sound(p)
