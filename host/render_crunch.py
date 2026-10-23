"""Audition renders after his Instagram find (vubeatz's MPC2000 "Sampling Mode", 2026-10-14): out/render/crunch/*.wav.

Each file: two bars of 4X4DRUMS103 at the original pitch, then 5 semitones down, half a second apart. Mono.
 0_clean              the loop, re-pitched cleanly (reference)
 1_their_recipe       vubeatz's SP1200 preset as they describe it: sample-and-hold at 26040 Hz, 12 bits, "without a
                      smoothing filter", applied to the RECORDING. Pitched down, the converted file is re-pitched
                      with linear interpolation (how the MPC2000 itself re-pitches is not documented: an assumption)
 2_our_SP1200         Fidelity SP1200 as built: drop-sample reader on the 26.04 kHz grid with the SP's anti-alias
                      taps, hold, 12 bits, the SP's output filter
 3_our_SP_Raw         Fidelity SP Raw as built: the same, without the output filter
 4_new_SP_Dirty       not built: SP Raw without the anti-alias taps either - nothing smooths anything
Numpy copies of filter.c's path (as render_sp45.py), not the compiled code.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s950
from render_s950 import FS, HERE, load
from render_sp45 import SP_OUT, SP_RATE, save as _save

OUT = os.path.join(HERE, "..", "out", "render", "crunch")
SP_FIR = (0.00302, 0.24563, 0.5027, 0.24563, 0.00302)
NO_FIR = (0.0, 0.0, 1.0, 0.0, 0.0)


def hold12(y):
    held, phase, out = 0.0, 0.0, np.empty(len(y))
    step = SP_RATE / FS
    for i, v in enumerate(y):
        phase += step
        if phase >= 1.0:
            phase -= 1.0
            held = np.rint(v * 2048) / 2048
        out[i] = held
    return out


def out_filter(out):
    b0, b1, a1, a2 = SP_OUT
    z1 = z2 = 0.0
    out = out.copy()
    for i, v in enumerate(out):
        o = b0 * v + z1
        z1 = b1 * v - a1 * o + z2
        z2 = b0 * v - a2 * o
        out[i] = o
    return out


def machine(x, semis, fir, filtered):
    rate = 2 ** (semis / 12)
    g = FS / SP_RATE
    pos = np.arange(int((len(x) - 8) / rate)) * rate + 4
    j = np.rint(np.floor(pos / g + 1 / 8192) * g).astype(int)          # drop-sample on the SP's grid
    y = hold12(sum(h * x[j - 2 + t] for t, h in enumerate(fir)))
    return (out_filter(y) if filtered else y).astype(np.float32)


def their_recipe(x, semis):
    conv = hold12(x)                                                    # converted at sampling, stored at 48 kHz
    rate = 2 ** (semis / 12)
    pos = np.arange(int((len(conv) - 2) / rate)) * rate
    i = pos.astype(int)
    f = pos - i
    return (conv[i] * (1 - f) + conv[i + 1] * f).astype(np.float32)    # re-pitched with linear interpolation


def save(name, parts):
    import render_sp45
    render_sp45.OUT = OUT
    _save(name, parts)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    src = os.path.join(OUT, "_src.wav")        # the measure/ file is WAVE_FORMAT_EXTENSIBLE, which wave cannot read:
    if not os.path.exists(src):                # ffmpeg -i measure/4X4DRUMS103-48k.wav -c:a pcm_s16le out/render/crunch/_src.wav
        os.system(f'ffmpeg -v error -y -i "{os.path.join(HERE, "..", "measure", "4X4DRUMS103-48k.wav")}" -c:a pcm_s16le "{src}"')
    x = load(src, 2 * 4 * 60 / 126)
    P = (0, -5)
    save("0_clean", [s950.clean(x, p) for p in P])
    save("1_their_recipe", [their_recipe(x, p) for p in P])
    save("2_our_SP1200", [machine(x, p, SP_FIR, True) for p in P])
    save("3_our_SP_Raw", [machine(x, p, SP_FIR, False) for p in P])
    save("4_new_SP_Dirty", [machine(x, p, NO_FIR, False) for p in P])
    print(sorted(f for f in os.listdir(OUT) if not f.startswith("_")))
