"""TAPESCAM (src/tapescam.c, bank 2) held against Charles Vestal's own code (host/tapescam_ref, compiled on the Mac).

Real firmware runs for: tapescam_block from the bank 2 payload (ARM, under Unicorn).

Reference: his tapescam.c exactly as published, with his libm, his create and his set_param (host/tapescam_ref/ref.c
only swaps his int16 I/O for float). Both run the same signal in 128-frame chunks with the same settings, so his
random wow / hiss / dropout sequences line up sample for sample.
Checked: the difference stays far below the signal (and below hearing) on his defaults, a hard Drive / Color patch,
everything worn (Wobble, Noise, Worn, Low, Heavy, Widen), a knob turned during play; level at defaults;
cost per frame.
NOT run: master.c (tapescam(), the dispatch, the knob pages and INFO paging), the Prism <-> TapeScam switch on the unit
(shared memory).
"""
import ctypes
import math
import os
import struct
import sys

import numpy as np
from unicorn import UC_HOOK_CODE

os.environ.setdefault("BANK2_NEW", "1")
from emu import STACK, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
REF = os.path.join("host", "libtsref.dylib")
if not os.path.exists(REF):
    os.system("sh host/build.sh")
ref = ctypes.CDLL(REF)
ref.ref_create.restype = ctypes.c_void_p
ref.ref_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
FP = ctypes.POINTER(ctypes.c_float)
ref.ref_process.argtypes = [ctypes.c_void_p, FP, FP, ctypes.c_int]

e = Emu(IMG, "out/cave.elf")
MEM, L, R, PAR = 0x24060000, 0x24070000, 0x24071000, 0x24072000
N = 256
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


DEFAULTS = dict(input=0.7, drive=0.0, color=0.0, wobble=0.0, tone=0.5, output=1.0, noise=0.0, comp=0, age=0, speed=0, widen=1)
ORDER = ["input", "drive", "color", "wobble", "tone", "output", "noise", "comp", "age", "speed", "widen"]
NAMES = {"comp": ["OFF", "LITE", "HEAVY"], "age": ["NEW", "USED", "WORN"], "speed": ["HIGH", "STD", "LOW"], "widen": ["OFF", "ON"]}


def signal(frames, seed=7):
    """drums-ish: decaying low thumps, noise bursts, a chord, at about -9 dBFS peaks, stereo"""
    t = np.arange(frames) / 48000.0
    rng = np.random.default_rng(seed)
    beat = np.zeros(frames)
    for k in range(0, frames, 12000):
        n = min(frames - k, 9000)
        beat[k:k + n] += 0.6 * np.sin(2 * np.pi * 55 * t[:n] * (1 + 2 * np.exp(-t[:n] * 40))) * np.exp(-t[:n] * 9)
    for k in range(6000, frames, 12000):
        n = min(frames - k, 3000)
        beat[k:k + n] += 0.25 * rng.standard_normal(n) * np.exp(-t[:n] * 60)
    chord = 0.08 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277.2 * t) + np.sin(2 * np.pi * 329.6 * t))
    return (beat + chord).astype(np.float32), (0.9 * beat + chord * 1.1).astype(np.float32)


def block(n=N):
    e.w32(STACK, n)                                  # the fifth argument (frames) is on the stack
    e.call("tapescam_block", MEM, PAR, L, R, n, count=20_000_000)


def fw_params(p):
    return struct.pack("<7f4I", p["input"], p["drive"], p["color"], p["wobble"], p["tone"], p["output"], p["noise"],
                       p["comp"], p["age"], p["speed"], p["widen"])


def run(settings_at, frames):
    """settings_at(block index) -> settings dict. Returns (firmware L, R, reference L, R)."""
    xl, xr = signal(frames)
    e.uc.mem_write(MEM, b"\0" * 0x5000)
    inst = ref.ref_create()
    last = dict(DEFAULTS)
    fl, fr, rl, rr = [], [], [], []
    for b in range(frames // N):
        p = settings_at(b)
        for k in ORDER:                                  # his set_param for what changed, in the firmware's order
            if p[k] != last[k]:
                v = NAMES[k][p[k]] if k in NAMES else f"{p[k]:.9g}"
                ref.ref_set(inst, ("compression" if k == "comp" else k).encode(), v.encode())   # his key names
        last = dict(p)
        a, c = xl[b * N:(b + 1) * N].copy(), xr[b * N:(b + 1) * N].copy()
        e.uc.mem_write(L, a.tobytes())
        e.uc.mem_write(R, c.tobytes())
        e.uc.mem_write(PAR, fw_params(p))
        block()
        fl.append(np.frombuffer(bytes(e.uc.mem_read(L, 4 * N)), np.float32))
        fr.append(np.frombuffer(bytes(e.uc.mem_read(R, 4 * N)), np.float32))
        for h in (0, 128):
            pa, pc = a[h:h + 128], c[h:h + 128]
            ref.ref_process(inst, pa.ctypes.data_as(FP), pc.ctypes.data_as(FP), 128)
        rl.append(a)
        rr.append(c)
    return np.concatenate(fl), np.concatenate(fr), np.concatenate(rl), np.concatenate(rr)


def compare(name, settings_at, frames=12288, limit_db=-60.0):
    fl, fr, rl, rr = run(settings_at, frames)
    sig = np.sqrt(np.mean(np.concatenate([rl, rr]) ** 2))
    err = np.sqrt(np.mean(np.concatenate([fl - rl, fr - rr]) ** 2))
    worst = float(np.max(np.abs(np.concatenate([fl - rl, fr - rr]))))
    rel = 20 * math.log10(max(err, 1e-12) / sig)
    finite = bool(np.all(np.isfinite(fl)) and np.all(np.isfinite(fr)))
    check(f"{name}: port vs his code {rel:.0f} dB below the signal (worst sample {worst:.1e})", finite and rel < limit_db,
          (rel, worst))
    return fl, fr


compare("his defaults (Input 70 %, Output 100 %, Widen On)", lambda b: DEFAULTS)
compare("Drive 80 %, Color 60 %, Tone 30 %", lambda b: dict(DEFAULTS, drive=0.8, color=0.6, tone=0.3), limit_db=-50.0)   # hard clipping magnifies 1e-7 differences
worn = dict(DEFAULTS, wobble=0.7, noise=0.5, comp=2, age=2, speed=2, color=0.4)
compare("Wobble 70 %, Noise 50 %, Heavy, Worn, Low", lambda b: worn, frames=24576, limit_db=-50.0)
compare("Std speed, Used, Lite, Widen Off, Tone 80 %", lambda b: dict(DEFAULTS, speed=1, age=1, comp=1, widen=0, tone=0.8))
compare("Drive turned up during play (0 -> 100 % over 40 blocks), Wobble on",
        lambda b: dict(DEFAULTS, drive=min(1.0, b / 40.0), wobble=0.4), frames=12288, limit_db=-50.0)

# the Blackbox default (his: Output 100 %): about unity on a mid-band tone (his gain stage band-limits lows and highs on
# purpose, so a full-range signal does come out quieter)
def tone_signal(frames):
    t = np.arange(frames) / 48000.0
    x = (0.25 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    return x, x.copy()


keep = signal
signal = lambda frames, seed=7: tone_signal(frames)
fl, fr, rl, rr = run(lambda b: DEFAULTS, 12288)
signal = keep
gain = 20 * math.log10(np.sqrt(np.mean(fl[4096:] ** 2)) / 0.25 * math.sqrt(2))
check(f"defaults (his, Output 100 %): a 1 kHz tone comes out at {gain:+.1f} dB (within 1.5 dB of unity)", abs(gain) < 1.5, gain)

cnt = [0]
e.uc.mem_write(MEM, b"\0" * 0x5000)
heavy = dict(worn, drive=0.6)
xl, xr = signal(N * 2)
for b in range(3):                                   # the first block builds the instance: not the steady cost
    e.uc.mem_write(L, xl[(b % 2) * N:(b % 2 + 1) * N].tobytes())
    e.uc.mem_write(R, xr[(b % 2) * N:(b % 2 + 1) * N].tobytes())
    e.uc.mem_write(PAR, fw_params(heavy))
    if b == 2:
        h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
    block()
e.uc.hook_del(h)
pf = cnt[0] / N
check(f"cost with everything on: {pf:.0f} instructions per frame = {pf / 101.25:.1f} % of the CPU (budget 10,125 = 100 %); "
      "guard against regressions at 1600", pf < 1600, pf)
cnt = [0]
e.uc.mem_write(MEM, b"\0" * 0x5000)                  # a fresh instance on the defaults
e.uc.mem_write(PAR, fw_params(DEFAULTS))
block()
block()
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
block()
e.uc.hook_del(h)
print(f"     cost at the defaults: {cnt[0] / N:.0f} instructions per frame = {cnt[0] / N / 101.25:.1f} %")

print(f"{fails} failed")
sys.exit(1 if fails else 0)
