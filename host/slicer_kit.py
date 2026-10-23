"""Slicer test kit from any sample: out/kit/<NAME>/.

    python3 host/slicer_kit.py SAMPLE [--name NAME] [--start S] [--seconds S] [--slices N] [--bpm BPM]

Drum beats hide the crunch (his finding, 2026-10-17), so the kit is built from a sample he picks. Writes:
  card/Presets/<NAME>/preset.xml + <NAME>.wav   copy the <NAME> folder into the card's Presets folder
  renders/*.wav                                  the pattern through each Fidelity mode (numpy copies of filter.c)
  kit.json                                       slice points, pattern, pads: what measure/slice_hits.py checks against

The preset (one slicer per pad, all on the same file and slices):
  pad 1 Normal  mono      sequence (4 bars): plays the pattern in bar 1
  pad 2 SP-12   mono      sequence: plays the same pattern in bar 3 -> clean / crunched A/B. Bars 2 and 4 rest, so
                          a slice still ringing from one pad never overlaps the other pad's hits
  pad 3 SP-12   poly      no sequence: tap it
  pad 4 SP1200  mono      no sequence
  pads 5-8: MPC60, S950, SP Raw, SP 45, all mono, no sequence
Pads without a sequence play the kit's brightest slice on every tap (the crunch is easiest to hear there), so every
tap of one pad should sound the same: one that sounds cleaner than the rest is the bug.

The preset is the backed-up preset.xml (card-backup/sample-preset) with the pads and sequences replaced. Read from
that file, NOT checked on the unit: pad index = row * 4 + col; a sequence's note goes to pad `chan - 256`; with
dispmode 1 (keys) a slicer's note 36 is its first slice (seq 2,1 -> pad 14, notes 36 / 38; seq 3,0 -> pad 12, note
42 with actslice 7); interpqual = the Fidelity list index (filter.c interp_names: Normal 0, HighQ 1, SP1200 2 ...).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s950  # noqa: E402

FS = 48000
TEMPLATE = os.path.join(HERE, "..", "card-backup", "sample-preset", "preset.xml")
TICKS = 960                      # per 1/16 step (template: strtks = step * 960)
SLICE_NOTE = 36

# filter.c machines[]: grid, fir, output filter (None = SP Raw), DAC rate when not the grid
FIDELITY = {
    "Normal": (0, None),
    "SP1200": (2, (26040.0, (0.00302, 0.24563, 0.5027, 0.24563, 0.00302), (0.357143, 0.714286, 0.0, 0.428571), 0)),
    "SP-12": (3, (27500.0, (-0.00396, 0.24215, 0.52363, 0.24215, -0.00396), (0.376262, 0.752523, 0.092392, 0.412654), 0)),
    "S950": (4, "S950"),
    "MPC60": (5, (40000.0, (-0.03947, 0.16746, 0.74402, 0.16746, -0.03947), (0.506372, 1.012744, 0.675162, 0.350325), 0)),
    "SP Raw": (6, (26040.0, (0.00302, 0.24563, 0.5027, 0.24563, 0.00302), None, 0)),
    "S950 Lo": (7, "S950 Lo"),
    "SP 45": (8, (26040.0 / 1.35, (0.05302, 0.25399, 0.38598, 0.25399, 0.05302), (0.357143, 0.714286, 0.0, 0.428571),
                  26040.0)),
}
PADS = [  # (pad index, fidelity, poly, sequence bar or None)
    (0, "Normal", False, 0),
    (1, "SP-12", False, 2),
    (2, "SP-12", True, None),
    (3, "SP1200", False, None),
    (4, "MPC60", False, None),
    (5, "S950", False, None),
    (6, "SP Raw", False, None),
    (7, "SP 45", False, None),
]
HIT_STEPS = (0, 2, 3, 6, 8, 10, 11, 14)      # 8 hits in a bar of 16ths: two back-to-back pairs (voice steals)


# ---- audio ----------------------------------------------------------------------------------------------------

def load(path, start, seconds):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", path, "-ac", "2",
                          "-ar", str(FS), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
    if not len(x):
        sys.exit(f"{path}: no audio between {start} s and {start + seconds} s")
    return x * (0.89 / max(np.max(np.abs(x)), 1e-9))           # -1 dBFS peak


def write_wav(path, x):
    x = np.atleast_2d(x.T).T
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def onsets(mono, count):
    """`count` slice points on the strongest attacks, at least 1/8 s apart; equal divisions fill any shortfall."""
    hop = 256
    n = len(mono) // hop
    d = np.diff(np.concatenate([[0.0], mono]))                  # first difference: weights the attack's top end
    env = np.sqrt(np.mean(d[:n * hop].reshape(n, hop) ** 2, axis=1))
    flux = np.maximum(np.diff(np.concatenate([[0.0], env])), 0.0)
    gap = int(0.125 * FS / hop)
    picks = [0]
    for i in np.argsort(flux)[::-1]:
        if len(picks) == count or flux[i] <= 0:
            break
        if all(abs(i - p) >= gap for p in picks) and i * hop < len(mono) - FS // 8:
            picks.append(int(i))
    pts = sorted(p * hop for p in picks)
    while len(pts) < count:                                     # split the longest slice
        ends = pts[1:] + [len(mono)]
        k = int(np.argmax(np.subtract(ends, pts)))
        pts.insert(k + 1, (pts[k] + ends[k]) // 2)
    out = []
    for p in pts:                                               # back up 2 ms to keep the attack, then a zero crossing
        p = max(0, p - FS // 500)
        w = mono[p:p + 64]
        z = np.nonzero(np.signbit(w[:-1]) != np.signbit(w[1:]))[0]
        out.append(int(p + z[0]) if len(z) and p else int(p))
    return out


def brightness(x):
    """Share of a slice's energy above 10 kHz: where 26 - 40 kHz machines differ most from clean."""
    s = np.abs(np.fft.rfft(x.mean(axis=1) * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / FS)
    return float(s[f > 10000].sum() / max(s.sum(), 1e-20))


def machine(x, spec):
    """One voice at the original pitch through filter.c's path: machine_read, crunch (hold + 12 bits), out_stage."""
    if spec is None:
        return x.copy()
    if isinstance(spec, str):
        mode = s950.HI if spec == "S950" else s950.LO
        return np.stack([s950.s950(x[:, c].astype(np.float32), 0.0, mode) for c in range(2)], axis=1)[:len(x)]
    grid, fir, out, dac = spec
    pad = np.concatenate([np.zeros((4, 2)), x, np.zeros((8, 2))])
    g = FS / grid
    j = np.rint(np.floor(np.arange(len(x)) / g + 1 / 8192) * g).astype(int) + 4
    y = sum(h * pad[j - 2 + t] for t, h in enumerate(fir))
    held, phase, step = np.zeros(2), 0.0, (dac or grid) / FS
    for i in range(len(y)):
        phase += step
        if phase >= 1.0:
            phase -= 1.0
            held = np.rint(y[i] * 2048) / 2048
        y[i] = held
    if out is not None:
        b0, b1, a1, a2 = out
        z1 = np.zeros(2)
        z2 = np.zeros(2)
        for i in range(len(y)):
            v = y[i].copy()
            o = b0 * v + z1
            z1 = b1 * v - a1 * o + z2
            z2 = b0 * v - a2 * o
            y[i] = o
    return y


def render_pattern(x, cuts, pattern, step_frames, spec, mono=True):
    """One bar: each hit plays its slice to the slice's end; a mono pad cuts the previous hit (3 ms fade)."""
    bar = 16 * step_frames
    y = np.zeros((bar + FS, 2))
    fade = FS * 3 // 1000
    ends = cuts[1:] + [len(x)]
    for h, (step, s) in enumerate(pattern):
        t = step * step_frames
        seg = machine(x[cuts[s]:ends[s]], spec)
        if mono and h + 1 < len(pattern):
            room = pattern[h + 1][0] * step_frames - t
            if len(seg) > room:
                seg = seg[:room].copy()
                seg[-fade:] *= np.linspace(1, 0, fade)[:, None]
        y[t:t + len(seg)] += seg[:len(y) - t]
    return y


# ---- preset ---------------------------------------------------------------------------------------------------

def set_attrs(params, **kv):
    for k, v in kv.items():
        params, n = re.subn(rf'\b{k}="[^"]*"', f'{k}="{v}"', params)
        assert n == 1, k
    return params


def make_preset(name, frames, cuts, pattern, bright, bpm):
    s = open(TEMPLATE, encoding="utf-8-sig").read()
    cell = re.compile(r'( *)<cell row="(\d)" column="(\d)" layer="0"[^>]*>.*?</cell>\n', re.S)
    slicer = re.search(r'<cell row="3" column="2" layer="0".*?(<params [^>]*/>)', s, re.S).group(1)
    empty = re.search(r'<cell row="1" column="2" layer="0".*?</cell>', s, re.S).group(0)
    mods = ('            <modsource dest="gaindb" src="velocity" slot="0" amount="400"/>\n'
            '            <modsource dest="gaindb" src="midivol" slot="2" amount="1000"/>\n'
            '            <modsource dest="panpos" src="midipan" slot="2" amount="1000"/>\n')
    pads = {p[0]: p for p in PADS}

    def pad_cell(m):
        ind, row, col = m.group(1), int(m.group(2)), int(m.group(3))
        k = row * 4 + col
        if col > 3 or k not in pads:
            return ind + re.sub(r'row="1" column="2"', f'row="{row}" column="{col}"', empty) + "\n"
        _, fid, poly, _ = pads[k]
        p = set_attrs(slicer, gaindb=0, samtrigtype=0, loopmode=0, cellmode=2, samstart=0, samlen=frames,
                      loopstart=0, loopend=frames, actslice=bright + 1, polymode=int(poly), polymodeslice=int(poly),
                      slicestepmode=0, overdrive=0, interpqual=FIDELITY[fid][0], playthru=0, slicersync=0)
        sl = "".join(f'                <slice pos="{c}"/>\n' for c in cuts)
        return (f'{ind}<cell row="{row}" column="{col}" layer="0" filename=".\\{name}.wav" type="sample">\n'
                f'            {p}\n{mods}            <slices>\n{sl}            </slices>\n        </cell>\n')

    s = cell.sub(pad_cell, s)
    seqs = {p[3]: p[0] for p in PADS if p[3] is not None}      # bar -> pad; sequence slot = (0, bar)

    def seq_cell(m):
        head, params = m.group(1), m.group(2)
        slot = re.search(r'row="(\d)" column="(\d)" layer="1" seqsublayer="(\d)"', head).groups()
        row, col, sub = map(int, slot)
        if row == 0 and sub == 0 and col in seqs:
            k = seqs[col]
            params = set_attrs(params, notesteplen=10, notestepcount=64, dispmode=1, seqpadmapdest=k,
                               seqplayenable=1)
            ev = "".join(
                f'                <seqevent step="{st}" chan="{256 + k}" type="note" strtks="{st * TICKS}" '
                f'pitch="{SLICE_NOTE + sl}" lencount="1" lentks="{TICKS}" velocity="100"/>\n'
                for st, sl in ((16 * col + a, b) for a, b in pattern))
            body = f"            <sequence>\n{ev}            </sequence>\n"
        else:
            body = "            <sequence/>\n"
        return f"{head}\n            {params}\n{body}        </cell>"

    s = re.sub(r'(<cell row="\d" column="\d" layer="1" seqsublayer="\d" type="noteseq">)\s*(<params [^>]*/>).*?</cell>',
               seq_cell, s, flags=re.S)
    song = re.search(r'<cell type="song">\s*(<params [^>]*/>)', s).group(1)
    s = s.replace(song, set_attrs(song, globtempo=int(round(bpm)), swing=50))
    return "﻿" + s


# ---- main -----------------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    ap.add_argument("--name", help="preset / file name (default: from the sample)")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the sample")
    ap.add_argument("--seconds", type=float, default=8.0, help="how much of it to slice")
    ap.add_argument("--slices", type=int, default=8)
    ap.add_argument("--bpm", type=float, default=96.0)
    a = ap.parse_args()
    name = a.name or re.sub(r"[^A-Za-z0-9]+", "-", os.path.splitext(os.path.basename(a.sample))[0]).strip("-")[:24]
    name = name.upper()
    out = os.path.join(HERE, "..", "out", "kit", name)
    card = os.path.join(out, "card", "Presets", name)
    rend = os.path.join(out, "renders")
    os.makedirs(card, exist_ok=True)
    os.makedirs(rend, exist_ok=True)

    x = load(a.sample, a.start, a.seconds)
    cuts = onsets(x.mean(axis=1), a.slices)
    ends = cuts[1:] + [len(x)]
    bright = int(np.argmax([brightness(x[c:e]) for c, e in zip(cuts, ends)]))
    n = len(cuts)
    order = [0, 3, 3, 5, 1, 6, 2, 7]                            # a repeat (3, 3) and both back-to-back pairs
    order = [o % n for o in order]
    pattern = list(zip(HIT_STEPS, order))
    step_frames = int(round(FS * 60 / a.bpm / 4))

    write_wav(os.path.join(card, name + ".wav"), x)
    with open(os.path.join(card, "preset.xml"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(make_preset(name, len(x), cuts, pattern, bright, a.bpm))

    # renders: the sequence's A/B, then every mode on the same bar, then the tap test on the brightest slice
    clean = render_pattern(x, cuts, pattern, step_frames, None)
    files = []

    def save(fname, y):
        write_wav(os.path.join(rend, fname), y)
        files.append(fname)

    bar = 16 * step_frames
    ab = np.zeros((4 * bar, 2))
    ab[:len(clean)] += clean[:len(ab)]
    sp12 = render_pattern(x, cuts, pattern, step_frames, FIDELITY["SP-12"][1])
    ab[2 * bar:2 * bar + len(sp12)] += sp12[:2 * bar]
    save("00_sequence_as_on_the_card_clean_rest_SP-12_rest.wav", ab)
    for i, fid in enumerate(["Normal", "SP1200", "SP-12", "MPC60", "S950", "S950 Lo", "SP Raw", "SP 45"], 1):
        y = clean if fid == "Normal" else render_pattern(x, cuts, pattern, step_frames, FIDELITY[fid][1])
        save(f"{i:02d}_{fid.replace(' ', '_')}.wav", y)
    seg = x[cuts[bright]:ends[bright]][:FS]
    taps = [seg, machine(seg, FIDELITY["SP-12"][1])] * 2
    gap = np.zeros((FS // 4, 2))
    save("09_brightest_slice_clean_SP-12_clean_SP-12.wav", np.concatenate(sum(([t, gap] for t in taps), [])))

    kit = dict(name=name, sample=os.path.abspath(a.sample), start=a.start, seconds=a.seconds, frames=len(x),
               bpm=a.bpm, slices=cuts, brightest=bright, slice_note=SLICE_NOTE, pattern=pattern,
               step_frames=step_frames, pads=[dict(pad=k + 1, fidelity=f, poly=p, sequence_bar=b)
                                              for k, f, p, b in PADS], renders=files)
    with open(os.path.join(out, "kit.json"), "w") as f:
        json.dump(kit, f, indent=1)
    print(f"{out}\n  {n} slices at {[round(c / FS, 3) for c in cuts]} s; brightest = slice {bright + 1}")
    print(f"  pattern (step, slice): {[(s, o + 1) for s, o in pattern]} at {a.bpm:g} BPM")
    print(f"  card: {card}\n  renders: {', '.join(files)}")


if __name__ == "__main__":
    main()
