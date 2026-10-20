"""Fidelity machine modes (SP1200, SP-12, S950, MPC60, SP Raw, S950 Lo) under Unicorn.

Real firmware runs for: the stock sample-voice reader FUN_08055f0c end to end (fetch into scratch, reverse, kernel
choice, buffer helpers), entered through voice_read_entry, plus both stock kernels for the non-machine settings.
Stubbed: the sample source (FUN_08063634 fetch, FUN_080636f0 length, FUN_08063790 mono).
Reference: a Python model of the drop-sample reader; for the S950 modes a Python model of the DAC staircase's area
per frame, and the Mac build of the same C (host/libdsp.dylib) fed the same scratch buffers.
NOT checked: how it sounds, slicer / clip pads (separate path, not hooked yet), CPU on the chip (instructions counted).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
PAD, SRC, SCR, OUT, SCRD, OUTD, ARR = 0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24064000, 0x24068000, 0x24073000
APP_PADS = 0x24020088 + 0x1840
N = 64
LEN = 3000000
stream = [0.0] * LEN


def fstr(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fetch():
    dst, n, pos = e.arg(1), e.arg(2), e.arg(3)
    vals = [stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]
    e.uc.mem_write(dst, struct.pack(f"<{n}f", *vals))


e.stub(0x08063634, fetch)
e.stub(0x080636F0, value=LEN)
e.stub(0x08063790, value=0)


def set_interp(v):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))
    e.w32(PAD + 0x18, 1 << 8 | 2)
    e.w32(PAD + 0x578, 0)


def bufobj(addr, data, cap):
    e.uc.mem_write(addr, struct.pack("<IIIIBB", cap, cap, data, 0, 0, 0))


def read_block(P, rate, n=N):
    """one call into the reader for output frames [0, n) starting at absolute position P"""
    bufobj(SCR, SCRD, 4096)
    bufobj(OUT, OUTD, 4096)
    ip = math.floor(P)
    e.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
    e.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
    e.w32(STACK, n)          # param_7: frames
    e.w32(STACK + 4, 0)      # param_8: dst offset
    e.w32(STACK + 8, SCR)    # param_9: scratch
    e.w32(STACK + 12, OUT)   # param_10: out
    e.call("voice_read", PAD, SRC, ip, 0, count=5_000_000)
    return list(struct.unpack(f"<{n}f", e.uc.mem_read(OUTD, 4 * n)))


def play(P, rate, blocks):
    out = []
    for _ in range(blocks):
        out += read_block(P, rate)
        P += rate * N
    return out


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


SP45 = 26040 / 1.35                                       # SP 45: the reader's grid, 19.29 kHz
FIR = {26040: [0.00302, 0.24563, 0.5027, 0.24563, 0.00302], 40000: [-0.03947, 0.16746, 0.74402, 0.16746, -0.03947],
       SP45: [0.05302, 0.25399, 0.38598, 0.25399, 0.05302]}


def model(P, rate, n, grid):
    """drop-sample: the source read only on the machine's grid (5-tap FIR at the grid point), position from P"""
    g = 48000 / grid
    h = FIR[grid]
    out = []
    pos = P
    for i in range(n):
        k = math.floor(pos / g + 1 / 8192)
        j = round(k * g)
        out.append(sum(h[t] * stream[j - 2 + t] for t in range(5)))
        pos += rate
    return out


# a source with energy up high: 3 kHz + 9.5 kHz
for i in range(LEN):
    stream[i] = 0.4 * math.sin(2 * math.pi * 3000 * i / 48000) + 0.3 * math.sin(2 * math.pi * 9500 * i / 48000)


def mismatches(got, ref):
    """frames that differ; on an exact grid tie float and double may pick neighbouring grid points"""
    return [i for i in range(len(got)) if abs(got[i] - ref[i]) > 1e-4]

# --- stock settings: bit-identical to the unpatched firmware's reader
stock = Emu("firmware/BLACKBOX-3.1.9.bin", "out/cave.elf")
stock.uc.mem_map(0x24100000, 0x10000)
for addr, fn in ((0x08063634, None), (0x080636F0, LEN), (0x08063790, 0)):
    pass
stock.stub(0x080636F0, value=LEN)
stock.stub(0x08063790, value=0)


def stock_fetch():
    dst, n, pos = stock.arg(1), stock.arg(2), stock.arg(3)
    stock.uc.mem_write(dst, struct.pack(f"<{n}f", *[stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


stock.stub(0x08063634, stock_fetch)


def stock_play(P, rate, blocks, hq):
    out = []
    stock.w32(PAD + 0x578, hq)
    for _ in range(blocks):
        stock.uc.mem_write(SCR, struct.pack("<IIIIBB", 4096, 4096, SCRD, 0, 0, 0))
        stock.uc.mem_write(OUT, struct.pack("<IIIIBB", 4096, 4096, OUTD, 0, 0, 0))
        ip = math.floor(P)
        stock.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
        stock.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
        for k, v in enumerate((N, 0, SCR, OUT)):
            stock.w32(STACK + 4 * k, v)
        stock.call(0x08055F0C, PAD, SRC, ip, 0, count=5_000_000)
        out += struct.unpack(f"<{N}f", stock.uc.mem_read(OUTD, 4 * N))
        P += rate * N
    return out


for v, hq, name in ((0, 0, "Normal"), (1, 0, "HighQ (engine copy reads Normal, as after a pad reset)"), (9 + 1, 0, "12k crunch")):
    set_interp(v)
    for rate in (0.7, -1.3):
        a = play(1000.25 if rate > 0 else 80000.5, rate, 4)
        b = stock_play(1000.25 if rate > 0 else 80000.5, rate, 4, hq)
        check(f"Fidelity {name}, rate {rate}: identical to the stock reader", a == b, max(abs(x - y) for x, y in zip(a, b)))
set_interp(1)
e.w32(PAD + 0x578, 1)
check("engine Interp HighQ still picks the stock HighQ kernel", play(1000.25, 0.7, 2) == stock_play(1000.25, 0.7, 2, 1))
e.w32(PAD + 0x578, 0)

# --- SP1200: drop-sample on the 26.04 kHz grid, pitch down an octave and up a fifth
set_interp(2)
for rate in (0.5, 1.4983, 0.8909):
    P = 5000.3
    got = play(P, rate, 6)
    ref = model(P, rate, 6 * N, 26040)
    err = max(abs(x - y) for x, y in zip(got, ref))
    check(f"SP1200 at rate {rate}: reads the source only on its 26.04 kHz grid, continuous across blocks (max err {err:.2e})", err < 1e-4, err)

for P in (2500000.37, 2879999.5):
    got = play(P, 0.6, 6)
    bad = mismatches(got, model(P, 0.6, 6 * N, 26040))
    check(f"SP1200 deep into a 60 s sample (position {P:.0f}): grid still exact ({len(bad)} of {len(got)} frames off)", len(bad) <= 1, bad[:5])
got = play(5000.0, 1.0, 6)
ref = model(5000.0, 1.0, 6 * N, 26040)
err = max(abs(x - y) for x, y in zip(got, ref))
check(f"SP1200 at the original pitch (stock would bypass the kernel): still read on the grid (max err {err:.2e})", err < 1e-4, err)
# --- SP 45 (3.2.b: the last machine, index 8, beside S950 Lo): the same reader on a 26.04 / 1.35 kHz grid
set_interp(8)
for rate in (1.0, 0.5, 0.7071, 1.4983):
    got = play(5000.3, rate, 6)
    bad = mismatches(got, model(5000.3, rate, 6 * N, SP45))
    check(f"SP 45 at rate {rate}: reads the source only on a 19.29 kHz grid ({len(bad)} of {len(got)} frames off)", len(bad) <= 1, bad[:5])
got = play(5000.3, 1.0, 6)
runs, k = [], 0
while k < len(got):
    j = k
    while j < len(got) and got[j] == got[k]:
        j += 1
    runs.append(j - k)
    k = j
avg = sum(runs[1:-1]) / len(runs[1:-1])
check(f"SP 45 at the original pitch: each stored sample lasts 48000 / 19289 = 2.49 frames (avg {avg:.2f})", abs(avg - 48000 / SP45) < 0.1, avg)
set_interp(16)
check("a Fidelity value past SP 45: stock reader", play(1000.25, 0.7, 2) == stock_play(1000.25, 0.7, 2, 0))
set_interp(0)
check("Normal at the original pitch: stock straight copy, untouched", play(5000.0, 1.0, 2) == stock_play(5000.0, 1.0, 2, 0))
set_interp(2)
got = play(5000.3, 0.5, 6)
runs, k = [], 0
while k < len(got):
    j = k
    while j < len(got) and got[j] == got[k]:
        j += 1
    runs.append(j - k)
    k = j
avg = sum(runs[1:-1]) / len(runs[1:-1])
check(f"SP1200 an octave down: each stored sample held ~2 grid ticks (avg run {avg:.2f} frames, expect 2 x 48000/26040 = 3.69)", abs(avg - 2 * 48000 / 26040) < 0.15, avg)


set_interp(1)
clean = play(20000.0, 0.5, 8)
set_interp(2)
crunch = play(20000.0, 0.5, 8)
diff = [a - b for a, b in zip(crunch, clean)]
ratio = math.sqrt(sum(d * d for d in diff) / sum(c * c for c in clean))
check(f"SP1200 an octave down differs from clean playback by {20 * math.log10(ratio):.1f} dB (drop-sample grit)", ratio > 0.05, ratio)

# --- reverse playback keeps a consistent grid
got = play(60000.0, -0.75, 6)
check("SP1200 reverse: finite, follows the source backwards", all(math.isfinite(v) for v in got) and max(abs(v) for v in got) > 0.3)
runs_ok = len(set(got)) < len(got) * 0.9
check("SP1200 reverse: still drop-sample (repeated values)", runs_ok)

# --- MPC60 grid 40k (the S950 modes have their own section below)
set_interp(5)
got = play(5000.3, 0.8, 4)
ref = model(5000.3, 0.8, 4 * N, 40000)
err = max(abs(x - y) for x, y in zip(got, ref))
check(f"MPC60: grid 40 kHz (max err {err:.2e})", err < 1e-4, err)

set_interp(6)
got = play(5000.3, 0.6, 3)
err = max(abs(x - y) for x, y in zip(got, model(5000.3, 0.6, 3 * N, 26040)))
check(f"SP Raw: the same drop-sample reader as SP1200 (max err {err:.2e})", err < 1e-4, err)

# --- stereo samples: the other fetch path, both channels on the same grid
SCRR, OUTR = 0x24066000, 0x2406A000
stream_r = [0.25 * math.sin(2 * math.pi * 5000 * i / 48000) for i in range(200000)] + [0.0] * (LEN - 200000)


def fetch2():
    l, r, n, pos = e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    e.uc.mem_write(l, struct.pack(f"<{n}f", *[stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))
    e.uc.mem_write(r, struct.pack(f"<{n}f", *[stream_r[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


e.stub(0x08063608, fetch2)
e.stub(0x08063790, value=1)
set_interp(2)
P, rate = 7000.6, 0.75
outl, outr = [], []
for b in range(4):
    e.uc.mem_write(SCR, struct.pack("<IIIIBB", 4096, 4096, SCRD, SCRR, 0, 1))
    e.uc.mem_write(OUT, struct.pack("<IIIIBB", 4096, 4096, OUTD, OUTR, 0, 1))
    ip = math.floor(P)
    e.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
    e.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
    for k, v in enumerate((N, 0, SCR, OUT)):
        e.w32(STACK + 4 * k, v)
    e.call("voice_read", PAD, SRC, ip, 0, count=5_000_000)
    outl += struct.unpack(f"<{N}f", e.uc.mem_read(OUTD, 4 * N))
    outr += struct.unpack(f"<{N}f", e.uc.mem_read(OUTR, 4 * N))
    P += rate * N
ref_l = model(7000.6, rate, 4 * N, 26040)
saved = stream[:]
stream[:] = stream_r
ref_r = model(7000.6, rate, 4 * N, 26040)
stream[:] = saved
el = max(abs(x - y) for x, y in zip(outl, ref_l)); er = max(abs(x - y) for x, y in zip(outr, ref_r))
err = max(el, er)
check(f"SP1200 stereo sample: both channels drop-sampled on the same grid (max err {err:.2e})", err < 1e-4, err)
e.stub(0x08063790, value=0)

# --- 3.1.T: the S950 modes. The reader clocks the stored samples out with no interpolation: each output frame is the
# area of the DAC staircase under it. Stored sample K is the source at round(K x g) through the five taps, 12 bits.
import ctypes

import numpy as np

host = ctypes.CDLL("host/libdsp.dylib")
# ARM vs host: the Cortex-M7 fuses multiply-adds (vfma); a host without FMA (x86 before Haswell, or clang
# with contraction off) rounds twice in the S950 Lo recursion and drifts a few ulp from it. 1e-5 covers
# that and still catches a wrong coefficient or a missed tap (those miss by 1e-3 and more).
HOST_TOL = 1e-5
FP = ctypes.POINTER(ctypes.c_float)
host.s950_read.argtypes = [ctypes.c_float, FP, ctypes.c_int32, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
                           FP, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), FP, FP, ctypes.c_int]
S950 = {4: (48000.0, [-0.07796, 0.18391, 0.7881, 0.18391, -0.07796]), 7: (31250.0, [-0.06897, 0.27256, 0.59283, 0.27256, -0.06897])}


def stored(K, g, h, gain=1.0, post=1.0):
    j = math.floor(K * g + 0.5)
    v = sum(h[t] * stream[j - 2 + t] for t in range(5)) * gain
    v = min(max(v, -1.0), 2047 / 2048)
    return math.floor(v * 2048 + 0.5) / 2048 * post


def stair_model(P, rate, n, grid, h, gain=1.0, post=1.0):
    g = 48000 / grid
    out = []
    for i in range(n):
        t0, t1 = (P + i * rate) / g, (P + (i + 1) * rate) / g
        m0, m1 = math.floor(t0), math.floor(t1)
        if m0 == m1:
            out.append(stored(m0, g, h, gain, post))
            continue
        acc = stored(m0, g, h, gain, post) * (m0 + 1 - t0) + sum(stored(m, g, h, gain, post) for m in range(m0 + 1, m1))
        out.append((acc + stored(m1, g, h, gain, post) * (t1 - m1)) / (t1 - t0))
    return out


def host_play(P, rate, blocks, grid, h, gain=1.0, post=1.0):
    """the Mac build of s950_read, given the scratch buffer and anchoring the stock reader gives the ARM build"""
    fir = np.array(h, np.float32)
    out = []
    for _ in range(blocks):
        ip = math.floor(P)
        n_src = int(N * abs(rate)) + 8
        if rate > 0:
            scratch = np.array([stream[p] if 0 <= p < LEN else 0.0 for p in range(ip - 4, ip - 4 + n_src)], np.float32)
            base, sgn, at = ip - 4, 1.0, np.float32(np.float32(P - ip) + np.float32(4.0))
        else:                                       # FUN_08055f0c: fetched from pos - n_src + 4, then reversed
            scratch = np.array([stream[ip + 3 - j] for j in range(n_src)], np.float32)
            base, sgn, at = ip + 3, -1.0, np.float32(np.float32(4.0) - np.float32(P - ip))
        idx = int(at)
        frac = ctypes.c_float(float(at) - idx)
        dst = np.zeros(N, np.float32)
        newpos = ctypes.c_int(0)
        host.s950_read(grid, fir.ctypes.data_as(FP), base, sgn, gain, post, abs(rate), scratch.ctypes.data_as(FP), n_src, idx,
                       ctypes.byref(newpos), ctypes.byref(frac), dst.ctypes.data_as(FP), N)
        out += [float(v) for v in dst]
        P += rate * N
    return out


def close(got, ref, tol=2e-4):
    return [i for i in range(len(got)) if abs(got[i] - ref[i]) > tol]


for v, name in ((4, "S950"), (7, "S950 Lo")):
    grid, h = S950[v]
    set_interp(v)
    for rate in (0.5, 0.8909, 1.4983, 3.7):
        got = play(5000.3, rate, 6)
        bad = close(got, stair_model(5000.3, rate, 6 * N, grid, h))
        check(f"{name} at rate {rate}: every frame is the area of the staircase under it, continuous across blocks ({len(bad)} of {len(got)} frames off)",
              len(bad) <= 2, bad[:6])
        bad = close(got, host_play(5000.3, rate, 6, grid, h), HOST_TOL)
        check(f"{name} at rate {rate}: the ARM build gives what the Mac build gives", not bad, bad[:6])
    got = play(5000.0, 1.0, 4)
    bad = close(got, stair_model(5000.0, 1.0, 4 * N, grid, h))
    check(f"{name} at the original pitch (stock would bypass the kernel): still the stored samples", len(bad) <= 2, bad[:6])
    for P in (2500000.37, 2879999.5):
        got = play(P, 0.6, 6)
        bad = close(got, stair_model(P, 0.6, 6 * N, grid, h))
        check(f"{name} deep into a 60 s sample (position {P:.0f}): the grid still exact ({len(bad)} of {len(got)} frames off)", len(bad) <= 2, bad[:6])
    got = play(60000.0, -0.75, 6)
    bad = close(got, host_play(60000.0, -0.75, 6, grid, h), HOST_TOL)
    check(f"{name} reverse: the ARM build gives what the Mac build gives", not bad, bad[:6])
    fwd = stair_model(60000.0 - 6 * N * 0.75 - 1, 0.75, 6 * N + 4, grid, h)
    best = min(max(abs(a - b) for a, b in zip(got[8:-8], fwd[::-1][k + 8:])) for k in range(0, 6))
    check(f"{name} reverse: the same staircase played backwards (max diff {best:.1e} at the best alignment)", best < 0.02, best)

set_interp(4)
got = play(5000.0, 1.0, 2)
check("S950 at the original pitch: every value is a 12-bit number (nothing is interpolated)",
      all(abs(v * 2048 - round(v * 2048)) < 0.02 for v in got))
got = play(5000.3, 0.25, 6)
flat = sum(1 for a, b in zip(got, got[1:]) if a == b)
check(f"S950 two octaves down: a stored sample lasts 4 frames, three held and one shared with the next ({flat} of {len(got) - 1} frames repeat the one before)",
      abs(flat / (len(got) - 1) - 0.5) < 0.03, flat)
set_interp(4)
e.call("pad_machine_mode", PAD)
check("S950 and S950 Lo are machine modes: Saturation is the converter's input level",
      e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0) == 1)
set_interp(7)
e.call("pad_machine_mode", PAD)
check("...S950 Lo too (the list value S1000 had)", e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0) == 1)
set_interp(2)
e.call("pad_machine_mode", PAD)
check("...and SP1200 still is", e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0) == 1)
set_interp(0)
e.call("pad_machine_mode", PAD)
check("...Normal is not", e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0) == 0)


def set_drive(v, sat):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xDB, 0, sat) + struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 2))


set_drive(4, 1000)
got = play(5000.3, 0.5, 4)
bad = close(got, stair_model(5000.3, 0.5, 4 * N, 48000.0, S950[4][1], gain=8.0, post=1 / 2.1))
top = max(abs(v) for v in got)
check(f"S950 with Saturation at 100 %: +18 dB into the converter's ceiling before the 12 bits, level back (peak {top:.3f} = 1 / 2.1)",
      len(bad) <= 2 and abs(top - 1 / 2.1) < 2e-3, (bad[:6], top))
set_interp(0)

# --- cost
from unicorn import UC_HOOK_CODE
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
for v, name in ((0, "Normal (stock)"), (2, "SP1200"), (4, "S950"), (7, "S950 Lo")):
    set_interp(v)
    play(5000.3, 0.8, 1)
    cnt[0] = 0
    play(5000.3, 0.8, 1)
    print(f"     reader cost, {name}: {cnt[0]} instructions per 64-frame mono block (incl. fetch stub)")
e.uc.hook_del(h)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
