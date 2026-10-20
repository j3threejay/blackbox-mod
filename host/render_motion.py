"""Audition renders for the delay's Motion types: out/render/motion/*.wav. Runs src/motion.c itself.

The Blackbox's delay is a send, so these files are built the way the unit builds them: the dry loop, plus a delay's
repeats (a plain stereo ping-pong at a dotted eighth, feedback 55 %, like the stock delay), with motion.c applied to
the repeats ONLY, in 128-frame blocks as the engine does.
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

OUT = os.path.join(HERE, "..", "out", "render", "motion")
LIB = os.path.join(HERE, "..", "out", "libmotion.dylib")
TREM, FILTER, DUCK, SWELL = 1, 2, 3, 4
F = ctypes.POINTER(ctypes.c_float)
BPM, BLOCK = 126.0, 128


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run([os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or "cc", "-O2", "-shared", "-fPIC", "-o", LIB, os.path.join(HERE, "..", "src", "motion.c")], check=True)
    d = ctypes.CDLL(LIB)
    d.motion_block.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_float, F, F, ctypes.c_int]
    return d


def repeats(x, feedback=0.55):
    """a ping-pong delay's wet output alone, dotted eighth"""
    d = int(FS * 60.0 / BPM * 0.75)
    wl, wr = np.zeros(len(x) + 4 * d, np.float32), np.zeros(len(x) + 4 * d, np.float32)
    src = np.concatenate([x, np.zeros(4 * d, np.float32)])
    g, pos, left = 1.0, d, True
    for _ in range(8):
        g *= feedback
        if g < 0.004:
            break
        tgt = wl if left else wr
        tgt[pos:] += (g * src[:len(src) - pos]).astype(np.float32)
        pos += d
        left = not left
    return wl[:len(x)].copy(), wr[:len(x)].copy()


def run(dll, wl, wr, dry, kind, rate, depth):
    """motion on the repeats, block by block, with the dry loop as the sidechain the unit would see"""
    state = ctypes.create_string_buffer(128)
    l, r = wl.copy(), wr.copy()
    for at in range(0, len(l) - BLOCK + 1, BLOCK):
        peak = float(np.abs(dry[at:at + BLOCK]).max())
        dll.motion_block(state, kind, rate, depth, peak, l[at:at + BLOCK].ctypes.data_as(F),
                         r[at:at + BLOCK].ctypes.data_as(F), BLOCK)
    return l, r


def save(name, l, r):
    y = np.clip(0.8 * np.stack([l, r], axis=1), -1, 1)
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((y * 32767).astype("<i2").tobytes())


#        name                     kind    rate  depth
SHOW = [("1_delay_no_motion",     0,      0.0,  0.0),
        ("2_Trem_slow",           TREM,   0.30, 0.80),
        ("3_Trem_fast",           TREM,   0.62, 0.95),
        ("4_Filter_slow",         FILTER, 0.26, 0.75),
        ("5_Filter_fast",         FILTER, 0.58, 0.90),
        ("6_Duck",                DUCK,   0.45, 0.85),
        ("7_Duck_deep_slow",      DUCK,   0.20, 1.00),
        ("8_Swell",               SWELL,  0.40, 0.90),
        ("9_Swell_long",          SWELL,  0.15, 1.00)]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    dll = lib()
    x = load(os.path.join(HERE, "..", "measure", "4X4DRUMS103-48k.wav"), 4 * 4 * 60 / BPM)
    wl, wr = repeats(x)
    save("0_dry_no_delay", x, x)
    for name, kind, rate, depth in SHOW:
        l, r = (wl.copy(), wr.copy()) if kind == 0 else run(dll, wl, wr, x, kind, rate, depth)
        save(name, 0.85 * x + l, 0.85 * x + r)
        print(f"{name:20} repeats rms {np.sqrt((l ** 2).mean()):.4f} (unmodulated {np.sqrt((wl ** 2).mean()):.4f})")
