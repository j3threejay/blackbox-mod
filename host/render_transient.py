"""Audition renders for the transient shaper (src/transient.c, compiled for the Mac: the same file the firmware will
build), in 128-frame blocks like the engine. python3 host/render_transient.py [out_dir]

First a numeric check on a synthetic kick (55 Hz body + 2 ms 3 kHz click, at -12 and -42 dBFS): the gain over time
for Attack / Sustain at +-100 %, per model, so the shaping is known to be level independent before anyone listens.
Then the renders: the 4X4DRUMS103 loop (measure/, 7.6 s), mono into both channels, 32-bit float WAV, every file
12 dB down (dry included) so a boosted attack (peaks up to ~+12 dBFS) is heard as it is, not clipped by the player.
"""
import ctypes
import os
import struct
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from render_s950 import FS, load  # noqa: E402

LIB = os.path.join(HERE, "..", "out", "libts.dylib")
F = ctypes.POINTER(ctypes.c_float)
MODELS = ["Differ", "Punch", "Smooth"]


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run(["clang", "-O2", "-shared", "-fPIC", "-o", LIB, os.path.join(HERE, "..", "src", "transient.c")], check=True)
    return ctypes.CDLL(LIB)


def run(dll, x, model=0, attack=0.0, sustain=0.0, speed=0.5, length=0.5, output=0.5, mix=1.0, block=128):
    state = ctypes.create_string_buffer(64)
    p = struct.pack("<I6f", model, attack, sustain, speed, length, output, mix)
    l, r = x.astype(np.float32).copy(), x.astype(np.float32).copy()
    for at in range(0, len(x) - block + 1, block):
        dll.ts_block(state, p, l[at:at + block].ctypes.data_as(F), r[at:at + block].ctypes.data_as(F), block)
    return l, r


PAD = 0.25                                                     # -12 dB on every file, dry included: a boosted
                                                               # attack peaks up to ~+12 dBFS, which a phone would clip


def save(path, l, r):
    data = (np.stack([l, r], axis=1) * PAD).astype("<f4").tobytes()
    with open(path, "wb") as f:                                # WAVE_FORMAT_IEEE_FLOAT (3): Python's wave can't
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, 2, FS, FS * 8, 8, 32))
        f.write(b"data" + struct.pack("<I", len(data)) + data)


def load_any(path, seconds):
    """PCM or WAVE_FORMAT_EXTENSIBLE PCM (Python 3.9's wave refuses the latter), mono mix, peak 0.7 like load()"""
    raw = open(path, "rb").read()
    at, fmt, data = 12, None, None
    while at + 8 <= len(raw):
        cid, size = raw[at:at + 4], struct.unpack_from("<I", raw, at + 4)[0]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", raw, at + 8)
        elif cid == b"data":
            data = raw[at + 8:at + 8 + size]
        at += 8 + size + (size & 1)
    tag, ch, rate, _, _, bits = fmt
    assert rate == FS and tag in (1, 0xFFFE) and bits in (16, 24, 32), fmt
    w = bits // 8
    b = np.frombuffer(data[:len(data) // (w * ch) * w * ch], np.uint8).reshape(-1, ch, w)
    v = np.zeros(b.shape[:2], np.int32)
    for k in range(w):
        v |= b[:, :, k].astype(np.int32) << (8 * k)
    v = (v << (32 - bits)) >> (32 - bits)
    x = v.mean(axis=1) / float(1 << (bits - 1))
    x = x[:int(seconds * FS)]
    return (0.7 * x / np.max(np.abs(x))).astype(np.float32)


def kick(level_db, seconds=0.8):
    t = np.arange(int(seconds * FS)) / FS
    body = np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.15)
    click = np.sin(2 * np.pi * 3000 * t) * (t < 0.002)
    x = np.zeros(int(0.1 * FS) + len(t), np.float32)
    x[int(0.1 * FS):] = (body + 0.5 * click) * 10 ** (level_db / 20)
    return x


def gain_curve(dll, model, **kw):
    """output / input level in dB over 2 ms windows from the onset"""
    out = []
    for lvl in (-12, -42):
        x = kick(lvl)
        y, _ = run(dll, x, model, **kw)
        on = int(0.1 * FS)
        row = []
        for ms in (0, 2, 5, 10, 20, 50, 150, 300):
            a, b = on + int(ms * FS / 1000), on + int((ms + 2) * FS / 1000)
            row.append(20 * np.log10((np.sqrt(np.mean(y[a:b] ** 2)) + 1e-12) / (np.sqrt(np.mean(x[a:b] ** 2)) + 1e-12)))
        out.append(row)
    return out


def main(out_dir):
    dll = lib()
    print("gain (dB) at 0 / 2 / 5 / 10 / 20 / 50 / 150 / 300 ms after a kick's onset, at -12 and -42 dBFS:")
    for m, name in enumerate(MODELS):
        for label, kw in (("Attack +100", dict(attack=1.0)), ("Attack -100", dict(attack=-1.0)),
                          ("Sustain +100", dict(sustain=1.0)), ("Sustain -100", dict(sustain=-1.0))):
            a, b = gain_curve(dll, m, **kw)
            print(f"  {name:6} {label:12} " + " ".join(f"{v:+5.1f}" for v in a) + "   |  " + " ".join(f"{v:+5.1f}" for v in b))
    x = load_any(os.path.join(HERE, "..", "measure", "4X4DRUMS103-48k.wav"), 9.0)
    os.makedirs(out_dir, exist_ok=True)
    save(os.path.join(out_dir, "00 dry.wav"), x, x)
    settings = [("Attack +50", dict(attack=0.5)), ("Attack +100", dict(attack=1.0)), ("Attack -60", dict(attack=-0.6)),
                ("Sustain +60", dict(sustain=0.6)), ("Sustain -60", dict(sustain=-0.6)),
                ("Tight (Att +60 Sus -50)", dict(attack=0.6, sustain=-0.5))]
    k = 1
    for m, name in enumerate(MODELS):
        for label, kw in settings:
            l, r = run(dll, x, m, **kw)
            save(os.path.join(out_dir, f"{k:02d} {name} - {label}.wav"), l, r)
            k += 1
    print(f"{k} files in {out_dir} (32-bit float, all at the dry file's gain)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "out", "render", "transient"))
