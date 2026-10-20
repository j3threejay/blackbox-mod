# blackbox-mod

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on a small number of units, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

**Get new builds by email:** sign up at <https://justinjoe.com/blackbox-mod> and I'll send a note when a new build is
out (new FX, fixes). That's all the list is for.

## What it adds (JOEBOX 1)

Releases have names now. JOEBOX 1 is the one after 3.1.n, and TOOLS shows it as the version.

**Updated 2026-10-17, same name.** The first JOEBOX 1 got some units stuck restarting at the logo. This build fixes
that (two of those units have confirmed it boots now). It also fixes USB audio not showing up when the compressor is
on Limit, and the insert models have their own names (Pebble, Electra, Jet). If you installed JOEBOX 1 before, patch
again and put both files on the card the same way.

New since 3.1.n:

- **Live input on a pad**: an "Input" row on a pad's Conf tab (Off, In 1, In 2, In 1+2). The audio input plays
  through that pad, so it gets the pad's insert, its reverb and delay sends, its level and pan, and the master FX.
  Muting the pad mutes it.
- **An insert effect per pad**: "Insert" on the Conf tab, INFO opens its knobs. Phaser (five models), Flanger
  (four models) or Gate. Sample, Multisample, Clip and Slicer pads.
- **LFO 2 and LFO 3 per pad**, on a new "LFO+" tab: twelve shapes (the stock nine plus two exponential ramps and
  a smooth random), tempo-synced rates from 32 bars to 1/32, Free / Retrig / Once, and a start Offset. They appear
  as LFO2 and LFO3 in the modulation Source list.
- **ENV and KEY as modulation sources**: the pad's own envelope, and key tracking.
- **Master FX slot** on TOOLS: VHS (wow, flutter, saturation, dropouts, noise) or Prism, a four-block multi-effect
  (drive, motion, space, texture; twenty effects). INFO on the row opens the knobs.
- **Delay types**: Motion (the stock delay with tremolo, filter, duck or swell on the repeats), Relapse (a memory
  echo) and Confetti (a granular micro-looper), next to Delay and Munchi.
- **Smash**, a three-band compressor, in the compressor list, and a **master clipper** after the compressor
  (Clean or Diode).
- **Fidelity**: the S950 mode rebuilt from the machine's schematic, S950 Lo and SP 45 added, and the machine modes
  now work on Clip and Slicer pads.
- **Record pre-roll**: TOOLS, Rec, Pre-roll (1, 2, 4 or 8 bars). The loop plays that long before the recording
  starts, so a resampled loop holds its own tails.
- **Rotate a sequence**: in the piano roll's Event editor the top-right knob shifts the whole layer a step at a time.
- **MUTE and SOLO on the Pads screen.**
- **USB on the power jack**: plugged into a computer the Blackbox is a class-compliant USB MIDI device and sends
  its three stereo outputs as six channels of 24-bit 48 kHz audio.
- **Load readout on TOOLS**: average / peak, for example `62/75%`. Over about 100% peak the engine is out of time
  and you will hear it.
- **Readable waveform knobs**: on the waveform screen, in every pad mode, the four corner knobs' text is white with
  a thin black edge instead of stock's grey, so it reads over the waveform's cyan as well as over the background.
  Same font, size and names.
- **Fixed**: the naming keyboard's 9 key (3.1.n typed "n").

From 3.1.n and earlier:

- **Solo** in the mixer: MIX cycles Mixer → Mute → Solo. Tap pads to solo them (yellow).
- **Slicer knobs**: on the waveform screen, bottom-left = slice Start, bottom-right = slice End, top-right = Zoom.
- **Pad-1 ducker**: four modulation Sources (EXP1, EXP2, PUMP, LINR) that fire when pad 1 plays. Put your kick
  on pad 1, set a negative Amount on another pad's Level, and you have sidechain pumping. About 0.65 dB per 1%.
- **Chords on the Keys screen**: top-right knob picks a shape (Tri, 7th, 9th, Su2, Su4, 6th, Ad9, Pwr, Oct, Opn, Shl,
  Qrt, m7, m9, Mj7). In-scale shapes follow the Keys Scale/Root. Chords record into sequences.
- **Note conditions**: the piano roll's PLAY list gains 1:2 … 8:8 ("play the Ath of every B loops").
- **Fidelity** (was Interp): sample-rate crunch plus machine modes SP1200, SP-12, S950, MPC60 and SP Raw, with
  drop-sample pitching.
- **Filter**: 24 dB/oct state-variable filter; drive comes in as Res goes past noon.
- **Saturation** (was Overdrive): soft saturation in place of the hard clip.
- **Master compressor models**: Stock, Glue, Punch, Opto, Squash, Limit, plus a Comp Thresh setting.
- **Reverb Type**: Plate (stock) or Room.
- **Munchi**, a port of the CHOMPI TEMPO granular delay, as a delay type.
- **Sequencer fix**: a note added just ahead of the playhead plays on that pass.

### Known issues

- This has run on very few units. If yours does something this list doesn't mention, I want to hear about it.
- The Blackbox only has so much CPU, and the mod lets you spend all of it. Room and Prism are the expensive ones.
  Watch the load readout on TOOLS.
- LFO 2 / 3, ENV, the insert and Input are not on Granular pads.
- A note placed very close ahead of the playhead is still sometimes silent.
- Chords need the pad out of Mono Poly Mode.
- Presets saved on an older mod build can come back with a neighbouring Fidelity or delay Type, because those
  lists gained entries. Set them again and save.
- USB on the power jack doesn't work on every unit. On some, that jack's USB data side is dead with any firmware,
  stock included (1010music never used it for data). The Blackbox boots and plays fine, you just don't get USB audio
  and MIDI. If your computer never sees the Blackbox over that jack, it's the unit, not the mod.
- The machine Fidelity modes (SP1200, SP-12, MPC60, SP Raw, SP 45) can come out grittier on one hit than the next.
  Fixed in the next build.

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. Patch it, either way:
   - **In your browser:** <https://j3threejay.github.io/blackbox-mod/>. Your file never leaves your computer.
   - **With Python 3:** `python3 apply.py path/to/BLACKBOX.bin` → `out/blackbox-mod-<version>/`
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy what the patcher gives you to the **root** of the Blackbox's microSD card. Newer builds are **two files,
   `BLACKBOX.bin` and `BBEXTRA.BIN`, and both have to be there** (the browser patcher hands you a zip with both).
5. Install it the way you install any 1010music firmware update: hold BACK + INFO while powering on, and let go as
   soon as the install screen shows.
6. On a two-file build the Blackbox **restarts itself once**, a second or two into the first boot. That is the
   second file being installed. Leave the card in and the power on until it is back up.
7. TOOLS should show `JOEBOX 1`.

### The second file

Part of the mod (Prism, Confetti and the per-pad insert effects) is too big to fit beside 1010music's firmware. The
chip has a second block of flash that 1010music's installer never touches, so the mod keeps that code there and
installs it itself from `BBEXTRA.BIN` the first time it starts. The file holds this project's own code and nothing of
1010music's. You can leave it on the card.

- **`!` in front of the load figures on TOOLS** (for example `!62/75%`) means the second part is not installed or
  does not match this build. Everything else works; those three effects are switched off.
- **`---` in the Insert, Master FX or delay Type lists** is the same thing seen from the menus: the effect that
  belongs there is not installed. A preset that uses one keeps its setting and gets the effect back once it is.
- To fix either: put the `BBEXTRA.BIN` **from the same download** as your `BLACKBOX.bin` in the root of the card and
  power the Blackbox off and on. The two files are a matched pair; one from a different build is ignored.
- If the second part cannot be written after two tries, the mod stops trying and leaves those effects off rather
  than wearing the flash. Installing any build (with its own `BBEXTRA.BIN`) starts the count again.

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way. The second part
stays in the chip, unused: stock firmware never looks at it, and it does not touch the unit's calibration.

The patcher checks your file's SHA-256 before it writes anything
(`281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d`) and checks the result afterwards. It only
works on 3.1.9.

## Build from source

Needs `arm-none-eabi-gcc` and Python 3. Put your stock image at `firmware/BLACKBOX-3.1.9.bin` (see
`firmware/README.md`).

```
RELEASE=1 ./build.sh
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave
```

That writes `out/<patchsets>/BLACKBOX.bin` and `out/BBEXTRA.BIN`, byte-identical to the release. `slice` also
applies `patches/wavelabel.py` (the Waveform screen's corner labels), so the set names stay as they were.
`python3 make_patch.py <image> "JOEBOX 1" --extra out/BBEXTRA.BIN` turns the pair into the release patch in `docs/`.
Without `RELEASE=1` you get a test build: a letter for a version, and a raw memory peek / poke over USB for
development. That one can write anywhere in the machine, so it is not in a release.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code.

`./check.sh` builds, patches and runs every suite (`test_*.py`) under Unicorn (`pip install unicorn capstone numpy`).
Several of them hold the firmware's DSP against a build of the same C for the computer (`host/build.sh`, written
for macOS). They test the new functions, not a full boot. The first power-on of any build is the real test.

`ghidra/`, `disasm.py`, `findbl.py`, `findref.py` are the helpers used to find things in your own copy of the image.

## What is and isn't in this repository

In it: original source code, patch definitions (addresses and replacement bytes), tools, and MIT-licensed third-party
DSP with its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues, pull requests or forks: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## License

MIT for the original work here ([LICENSE](LICENSE)). "1010music" and "Blackbox" are trademarks of 1010music LLC, used
only to say what this mod is for.

If you are from 1010music and have a concern about anything here, open an issue or email justin.joe.dev@gmail.com and
it will be dealt with promptly.
