"""Audition renders for the per-pad insert effects: out/render/insert/*.wav, stereo.

This runs src/insert_dsp.c itself, compiled for the Mac (the same file the firmware builds), in 128-frame blocks like
the engine. Source: the four bars of 4X4DRUMS103 (measure/), mono into both channels.
"""
import ctypes
import os
import struct
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from render_s950 import FS, load

OUT = os.path.join(HERE, "..", "out", "render", "insert")
LIB = os.path.join(HERE, "..", "out", "libins.dylib")
PHASER, FLANGER = 1, 2
F = ctypes.POINTER(ctypes.c_float)


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run([os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or "cc", "-O2", "-shared", "-fPIC", "-o", LIB, os.path.join(HERE, "..", "src", "insert_dsp.c")], check=True)
    return ctypes.CDLL(LIB)


def run(dll, x, kind, model, rate, depth, manual, fb, spread, mix, block=128, mono=False, gate=(0, 0, 0, 0, 0)):
    state = ctypes.create_string_buffer(16384)
    l, r = x.astype(np.float32).copy(), x.astype(np.float32).copy()
    for at in range(0, len(x) - block + 1, block):
        p = struct.pack("<BBBB6f5f", kind, model, 0, 0, rate, depth, manual, fb, spread, mix, *gate)
        dll.ins_render(state, p, l[at:at + block].ctypes.data_as(F), None if mono else r[at:at + block].ctypes.data_as(F), block)
    return l, r


def save(name, l, r):
    y = np.clip(0.7 * np.stack([l, r], axis=1), -1, 1)       # 3 dB down: the wet peaks run past the dry ones
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((y * 32767).astype("<i2").tobytes())


#        name                kind     model rate  depth manual fb    spread mix
SHOW = [("01_phaser_Pebble", PHASER, 0, 0.36, 0.85, 0.50, 0.50, 0.25, 0.5),
        ("02_phaser_Ninety", PHASER, 1, 0.48, 0.75, 0.45, 0.35, 0.00, 0.5),
        ("03_phaser_Vibe", PHASER, 2, 0.58, 0.95, 0.50, 0.20, 0.30, 0.5),
        ("04_phaser_Deep", PHASER, 3, 0.26, 0.80, 0.50, 0.75, 0.25, 0.5),
        ("05_phaser_Steps", PHASER, 4, 0.52, 0.85, 0.55, 0.65, 0.50, 0.5),
        ("06_flanger_Electra", FLANGER, 0, 0.28, 0.80, 0.45, 0.60, 0.25, 0.5),
        ("07_flanger_Jet", FLANGER, 1, 0.22, 1.00, 0.50, 0.85, 0.25, 0.5),
        ("08_flanger_Tape", FLANGER, 2, 0.24, 1.00, 0.50, 0.30, 0.00, 0.5),
        ("09_flanger_Metal", FLANGER, 3, 0.30, 0.70, 0.50, 0.85, 0.25, 0.5)]

GATE = 3
# Thresh is exp2(-11 x (1 - knob)) of full scale, so 0.70 is about -20 dB and 0.80 about -13 dB. A drum loop
# rarely falls below -40 dB between hits, so anything under about 0.55 never closes on this material.
#            name                  thresh atk   hold  rel   floor
GATES = [("10_gate_tight",        0.78,  0.05, 0.08, 0.25, 0.00),
         ("11_gate_long_tail",    0.78,  0.05, 0.04, 0.72, 0.00),
         ("12_gate_slow_attack",  0.74,  0.45, 0.20, 0.35, 0.00),
         ("13_gate_duck_not_mute", 0.78, 0.05, 0.08, 0.30, 0.45)]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    dll = lib()
    x = load(os.path.join(HERE, "..", "measure", "4X4DRUMS103-48k.wav"), 4 * 4 * 60 / 126)
    save("00_dry", x, x)
    for name, *a in SHOW:
        l, r = run(dll, x, *a)
        save(name, l, r)
        print(f"{name:22} peak {max(abs(l).max(), abs(r).max()):.2f}  rms {np.sqrt((l ** 2).mean()):.3f} (dry {np.sqrt((x ** 2).mean()):.3f})")
    for name, th, at, ho, re, fl in GATES:
        l, r = run(dll, x, GATE, 0, 0, 0, 0, 0, 0, 1.0, gate=(th, at, ho, re, fl))
        save(name, l, r)
        # rms is useless for a gate: it takes away the quiet material, which hardly shows there. Report how much of
        # the loop it actually holds down instead.
        held = 100 * (np.abs(l) < np.abs(x) * 0.99).mean()
        print(f"{name:22} peak {abs(l).max():.2f}  holds down {held:.0f}% of the loop")
