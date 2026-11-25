# midi2g2

Turn a **MIDI**, **NSF / NSFe** (NES) or **SID** (Commodore 64) file into a **Nord Modular G2 performance** that plays
the whole piece from the G2's own sequencers, synced to the master clock.

Not affiliated with Clavia. "Nord Modular G2" is used only to say which instrument the files are for.

## Install and run

### What you need

- **Python 3** (tested with 3.11): [python.org/downloads](https://www.python.org/downloads/).
  On Windows, tick **"Add python.exe to PATH"** in the installer.
- **Git**: [git-scm.com](https://git-scm.com/downloads). On Windows this also gives you **Git Bash**, which the setup
  script needs.

Check both are installed by opening a terminal (PowerShell or Git Bash on Windows, Terminal on macOS/Linux):

```
python --version
git --version
```

(On macOS/Linux, use `python3` and `pip3` wherever this guide says `python` and `pip`.)

### Install (once)

**1. Download the project**

```
git clone https://github.com/netvids/g2tomidi.git
cd g2tomidi
```

**2. Install g2ools.** midi2g2 writes G2 files with [g2ools](https://github.com/msg/g2ools). This script downloads the
tested version into a `g2ools` folder in your home folder and applies the fixes midi2g2 needs. On Windows, run it in
**Git Bash**:

```
bash python/setup_g2ools.sh
```

It should end with `g2ools OK`. If you install g2ools anywhere other than your home folder, tell midi2g2 where it is
(do this in every new terminal, or add it to your profile):

```
export G2OOLS=/path/to/g2ools          # macOS / Linux / Git Bash
$env:G2OOLS = "C:\path\to\g2ools"      # Windows PowerShell
```

**3. Install the Python packages** (`mido` reads MIDI; `py65` runs NES and C64 music drivers):

```
pip install -r requirements.txt
```

**4. Check it works** by converting the example:

```
python python/midi2g2.py "examples/Ode to Joy test.mid"
```

You should see the tempo, length and slots it chose, then `wrote ...`. The result is in a new folder,
`examples/Ode to Joy test G2/`.

### Convert your own files

**1. See what is in the file.** This lists every melody line found, with a number, and stops:

```
python python/midi2g2.py "my song.mid" --list
```

**2. Convert it.** With no options the busiest lines go to slots A–C and slot D is the transpose + reverb slot:

```
python python/midi2g2.py "my song.mid"
```

The output goes in a folder named `my song G2` next to your file:

| File | What it is |
|---|---|
| `my song.prf2` | the performance: load this on the G2 |
| `my song A.pch2` … `D.pch2` / `Control.pch2` | the patch for each slot, if you want to load or edit them one by one |
| `CONVERSION.txt` | report: tempo, length, which line went to which slot, anything left out |

Long pieces are split into several numbered performances.

**3. Fine-tune if needed.** Useful options (combine as many as you like):

| Option | What it does |
|---|---|
| `--list` | show the lines found and stop |
| `--pick 3,0,5` | use these line numbers from `--list`, in slot order A, B, C… |
| `--parts 4` | 4 part slots and no control/reverb slot (1–4) |
| `--chain` | play ONE line across slots A→B→C→D, for longer pieces |
| `--grid 4` | steps per beat: 2, 3, 4 (16ths), 6, 8 or 12. Default: chosen automatically |
| `--sound 5` | starting sound 1–8 for every slot |
| `--bends follow` | pitch bend: `main` (default), `follow` in semitone steps, or `off` |
| `--start 32 --end 96` | convert only a section, in beats (quarter notes) from the start |
| `--bpm 100` | override the file's tempo |
| `--no-loop` | do not loop the piece |
| `--song 2` | NSF / NSFe / SID: which song of the file |
| `--out "My Folder"` | choose the output folder |

Examples:

```
python python/midi2g2.py song.mid --pick 3,0,5 --parts 4 --grid 4 --start 32 --end 96
python python/midi2g2.py game.nsf --song 2
python python/midi2g2.py tune.sid --chain
```

Run `python python/midi2g2.py --help` for the full list.

## Load it on the G2

1. Connect the G2 to your computer and open the Nord Modular G2 editor.
2. Open the `.prf2` file from the output folder and send it to the synth (store it in a performance location if you
   want to keep it).
3. It plays: the performance is saved with the master clock running at the piece's tempo, and every slot's
   sequencers follow it. Stopping and starting the master clock plays it again from the top.
4. In the default mode, slot D listens to the keyboard: play a key to transpose the whole piece (C3 = original
   key; it holds until the next key). Its knobs on page A1 set the room reverb: time, brightness, return and volume.

## Troubleshooting

| Message | Fix |
|---|---|
| `g2ools not found` | run step 2 of the install, or set `G2OOLS` to where g2ools is |
| `mido is missing` / `No module named py65` | run `pip install -r requirements.txt` |
| `python3: command not found` at the end of the setup script (Windows) | g2ools is already installed; only the script's last check failed. Carry on with step 3; step 4 shows whether it all works |
| `python` opens the Microsoft Store (Windows) | install Python from python.org with "Add to PATH" ticked, then open a new terminal |
| The G2 editor refuses a file | it should not happen (files stay under 64 KB); please open an issue with the source file |

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
| `python/templates.json` | pre-built, verified patch templates with their sizes (`make_templates.py` regenerates them) |
| `tests/` | public-domain test inputs, `cases.txt`, and `run_tests.py` (converts every case and checks it with `verify.py`) |
| `examples/` | public-domain example files (Ode to Joy as MIDI, NSF, NSFe and SID) |

After editing: `python python/make_templates.py` (only if patch layouts changed), then `python tests/run_tests.py`.

## License

GPL-3.0 (see `LICENSE`). It uses [g2ools](https://github.com/msg/g2ools) (GPL-2.0-or-later), which is downloaded
by `setup_g2ools.sh`, not included. Test and example files contain only public-domain music.
