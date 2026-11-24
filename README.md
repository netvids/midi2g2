# midi2g2

Turn a **MIDI**, **NSF / NSFe** (NES) or **SID** (Commodore 64) file into a **Nord Modular G2 performance** that plays
the whole piece from the G2's own sequencers, synced to the master clock.

Not affiliated with Clavia. "Nord Modular G2" is used only to say which instrument the files are for.

## Use it

**In the browser:** open `docs/index.html` (or the GitHub Pages site). Drop a file, pick which lines go to slots A–D,
listen with the preview player, and save a zip with the `.prf2` performance, the slot patches and a `CONVERSION.txt`
report. Everything runs locally in the browser; nothing is uploaded.

**From the command line:**

```
bash python/setup_g2ools.sh            # once: installs g2ools and applies python/g2ools-fixes.patch
export G2OOLS=$HOME/g2ools
pip install -r requirements.txt
python python/midi2g2.py song.mid      # writes "song G2/" next to the file
python python/midi2g2.py song.mid --list
python python/midi2g2.py song.mid --pick 3,0,5 --parts 4 --grid 4 --start 32 --end 96
python python/midi2g2.py game.nsf --song 2
python python/midi2g2.py tune.sid --chain
```

Both give byte-identical files for the same settings.

## What it does

- **MIDI:** tracks are split into monophonic lines (legato overlaps kept together); chord tracks can play as one
  chord slot (up to 4 notes). Note On/Off pairing, All Notes Off and pitch bend (with RPN range) follow MIDI 1.0.
  General MIDI programs choose a fitting starting sound.
- **NSF / NSFe:** the game's sound driver runs on a built-in 6502 emulator; pulse 1, pulse 2 and triangle become lines
  (plus VRC6 and VRC7 channels). Loops are detected, the tempo is estimated.
- **SID:** the tune's player runs the same way; the three SID voices become lines.
- **On the G2:** each slot is a mono patch with chained 16-step SeqNote sequencers and its synth in the voice area.
  The step clock is the master clock's 1/96 output divided, so the G2 runs at the piece's real tempo.
  Modes: 3 parts + transpose/reverb slot, 4 parts, or one track chained through slots A→B→C→D.

## Limits

- About 31 bars of 16 steps per melody slot (29 per chained slot); longer pieces split into numbered performances.
- Performance files are kept under 64 KB (the G2 editor refuses bigger ones).
- Note pitches never travel between areas or slots; only short start pulses do.
- Drums (MIDI channel 10, NES noise/DMC) are skipped; extra NES sound chips other than VRC6/VRC7 are not read.

## Repository

| Path | What |
|---|---|
| `python/` | the converter (`midi2g2.py`), readers (`nsf.py`, `sid.py`), chord and chain slots, `g2lib.py` helpers, `verify.py` |
| `python/templates.json` | pre-built, verified patch templates used by the web app (`make_templates.py` regenerates them) |
| `web/` | web app sources; `build.py` assembles them into `docs/index.html` |
| `tests/` | public-domain test inputs, `cases.txt`, and `run_tests.py` (Python output checked with `verify.py`, then compared byte for byte with the web app via node) |
| `examples/` | public-domain example files (Ode to Joy as MIDI, NSF, NSFe and SID) |

After editing: `python python/make_templates.py` (only if patch layouts changed), `python build.py`, `python tests/run_tests.py`.

## License

GPL-3.0 (see `LICENSE`). It uses [g2ools](https://github.com/msg/g2ools) (GPL-2.0-or-later), which is downloaded
by `setup_g2ools.sh`, not included. Test and example files contain only public-domain music.
