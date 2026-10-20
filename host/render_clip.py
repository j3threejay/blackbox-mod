"""Audition renders and measurements for the master clipper: out/render/clip/*.wav. Runs src/clip.c itself.

Files: the four bars of 4X4DRUMS103 dry, then pushed by the Clip knob at several Shapes, Clean and Diode. Each is
level-matched to the dry file's loudness on the way out, so what you compare is the tone, not "louder".
"""
import ctypes
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from render_s950 import FS, load

OUT = os.path.join(HERE, "..", "out", "render", "clip")
LIB = os.path.join(HERE, "..", "out", "libclip.dylib")
CLEAN, DIODE = 1, 2
F = ctypes.POINTER(ctypes.c_float)


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run([os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or "cc", "-O2", "-shared", "-fPIC", "-o", LIB, os.path.join(HERE, "..", "src", "clip.c")], check=True)
    d = ctypes.CDLL(LIB)
    d.clip_block.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_float, ctypes.c_float, F, F, ctypes.c_int]
    return d


def run(dll, x, kind, amount, shape, block=256):
    state = ctypes.create_string_buffer(256)
    l, r = x.astype(np.float32).copy(), x.astype(np.float32).copy()
    for at in range(0, len(x) - block + 1, block):                          # a tail shorter than a block is left dry
        dll.clip_block(state, kind, amount, shape, l[at:at + block].ctypes.data_as(F), r[at:at + block].ctypes.data_as(F), block)
    return l, r


def save(name, y):
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    dll = lib()
    x = load(os.path.join(HERE, "..", "measure", "4X4DRUMS103-48k.wav"), 4 * 4 * 60 / 126)
    rms = lambda v: float(np.sqrt((v ** 2).mean()))
    save("0_dry", x)
    for name, kind, amount, shape in (("1_clean_soft_push_50", CLEAN, 0.5, 0.0), ("2_clean_mid_push_50", CLEAN, 0.5, 0.6),
                                      ("3_clean_hard_push_50", CLEAN, 0.5, 1.0), ("4_clean_hard_push_100", CLEAN, 1.0, 1.0),
                                      ("5_diode_mid_push_50", DIODE, 0.5, 0.6), ("6_diode_hard_push_100", DIODE, 1.0, 1.0)):
        l, _ = run(dll, x, kind, amount, shape)
        print(f"{name:24} peak {abs(l).max():.4f}  louder by {20 * np.log10(rms(l) / rms(x)):+.1f} dB")
        save(name, l * rms(x) / rms(l))
