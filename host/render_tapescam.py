"""Render a WAV through Charles Vestal's TAPESCAM (his code, host/libtsref.dylib) at a few settings, for listening.
python3 host/render_tapescam.py in.wav out_dir   (the firmware port matches this to -53..-72 dB: test_tapescam.py)"""
import ctypes
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ref = ctypes.CDLL(os.path.join(HERE, "libtsref.dylib"))
ref.ref_create.restype = ctypes.c_void_p
ref.ref_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
FP = ctypes.POINTER(ctypes.c_float)
ref.ref_process.argtypes = [ctypes.c_void_p, FP, FP, ctypes.c_int]

PATCHES = {
    "1-defaults": {},
    "2-drive-color": {"drive": "0.5", "color": "0.5"},
    "3-worn-wobble": {"wobble": "0.6", "age": "WORN", "speed": "STD", "color": "0.3"},
    "4-lofi-heavy": {"speed": "LOW", "compression": "HEAVY", "noise": "0.4", "drive": "0.35", "tone": "0.35"},
    "5-cranked": {"drive": "0.9", "color": "0.8", "wobble": "0.4", "compression": "LITE"},
}


def read(path):
    """16 / 24 / 32-bit PCM or 32-bit float WAV, plain or WAVE_FORMAT_EXTENSIBLE (Python's wave refuses the latter)"""
    import struct
    d = open(path, "rb").read()
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(d):
        cid, size = d[pos:pos + 4], struct.unpack("<I", d[pos + 4:pos + 8])[0]
        body = d[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, bits)
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    tag, ch, bits = fmt
    if tag == 3:
        x = np.frombuffer(data, np.float32 if bits == 32 else np.float64).astype(np.float32)
    elif bits == 24:
        b = np.frombuffer(data, np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608.0
    else:
        x = np.frombuffer(data, np.int16 if bits == 16 else np.int32).astype(np.float32) / (32768.0 if bits == 16 else 2147483648.0)
    x = x.reshape(-1, ch)
    return (x[:, 0].copy(), (x[:, 1] if ch > 1 else x[:, 0]).copy())


def write(path, l, r):
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(48000)
    w.writeframes((np.clip(np.stack([l, r], 1), -1, 1) * 32767).astype(np.int16).tobytes())


def main(src, out):
    l0, r0 = read(src)
    write(os.path.join(out, "0-dry.wav"), l0, r0)
    for name, sets in PATCHES.items():
        inst = ref.ref_create()
        for k, v in sets.items():
            ref.ref_set(inst, k.encode(), v.encode())
        l, r = l0.copy(), r0.copy()
        for i in range(0, len(l) - 127, 128):
            a, b = l[i:i + 128].copy(), r[i:i + 128].copy()
            ref.ref_process(inst, a.ctypes.data_as(FP), b.ctypes.data_as(FP), 128)
            l[i:i + 128], r[i:i + 128] = a, b
        write(os.path.join(out, f"{name}.wav"), l, r)
        print(name, sets)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
