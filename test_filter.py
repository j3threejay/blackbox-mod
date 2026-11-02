"""Pad crunch + state-variable filter under Unicorn.

Real firmware runs for: the stock cutoff and resonance curves, the audio-buffer accessors, the Interp list
registration path up to the stock registrar (stubbed), and both voice call-site thunks.
Stubbed: the modulated-parameter read (returns test values), the list registrar.
Reference: a Python model of the same SVF and crunch, so these checks pin the arithmetic, not the sound.
NOT checked: how it sounds, and CPU load with many voices (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_S0, UC_ARM_REG_S1, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")

OBJ, PARAMS, PAD, BUF, LBUF, RBUF = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24066000
N = 64
values = {}


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def param():
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", values.get(e.arg(0), 0.0)))[0])


e.stub(0x0806FB30, param)
e.w32(OBJ + 0x84, PARAMS)
e.uc.mem_map(0x38800000, 0x1000)       # backup SRAM + its clock: a SLICE_DIAG build looks for its block
e.uc.mem_map(0x58024000, 0x1000)       # (the address reads 0 here, so it records nothing)


def curve(addr, x):
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", x))[0])
    e.call(addr)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0)))[0]


APP_PADS, ARR = 0x24020088 + 0x1840, 0x24073000
PAD_ROW, PAD_COL = 1, 2


def set_interp(v, row=PAD_ROW, col=PAD_COL, sat=0):
    """The app's record of the pad (what the screen shows and presets save)."""
    store = APP_PADS + row * 0xF0 + col * 0x30
    arr = ARR + (row * 4 + col) * 0x40
    e.uc.mem_write(arr, struct.pack("<HHI", 0x8B, 0, 0) + struct.pack("<HHI", 0xF1, 0, v) + struct.pack("<HHI", 0xDB, 0, sat))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", 3))


def setup(knob, res=0.0, interp=0):
    values[PARAMS + 8] = knob
    values[PARAMS + 0x44] = res
    e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)    # engine pad id: bank << 16 | row << 8 | col
    e.w32(PAD + 0x578, 0)                         # the engine's own copy, as left by a pad reset: must not matter
    set_interp(interp)


def run(left, right=None, pad=PAD, silent=False, sample_voice=0):
    e.uc.mem_write(LBUF, struct.pack(f"<{len(left)}f", *left))
    if right is not None:
        e.uc.mem_write(RBUF, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), LBUF, RBUF if right is not None else 0, int(silent), int(right is not None)))
    e.call("filter_process", OBJ, BUF, pad, sample_voice, count=20_000_000)
    l = list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(LBUF, 4 * len(left))))
    r = list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(RBUF, 4 * len(right)))) if right is not None else None
    return l, r


def reset():
    e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)          # stale stock coefficients: the patch must initialise itself


def sine(hz, n=N, start=0, amp=0.5):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def soft(x, t):
    u = x / t
    if u > 1.5:
        return t
    if u < -1.5:
        return -t
    return t * u * (1 - 0.148148 * u * u)


def model_svf(x, g, r, s, hp, limit):
    h = 1 / (1 + r * g + g * g)
    s1, s2 = s
    out = []
    for v in x:
        hpv = (v - r * s1 - g * s1 - s2) * h
        bp = g * hpv + s1
        s1 = soft(g * hpv + bp, limit) if limit else g * hpv + bp
        lp = g * bp + s2
        s2 = g * bp + lp
        out.append(hpv if hp else lp)
    return out, [s1, s2]


def model_block(x, g, r, drive, states, hp):
    """One block of the patched filter: drive, Butterworth stage, resonant stage."""
    if drive > 0.001:
        x = [soft(v * (1 + 3 * drive), 1.0) for v in x]
    y, states[0] = model_svf(x, g, 1.84776, states[0], hp, None)
    out, states[1] = model_svf(y, g, r, states[1], hp, 4 - 3 * drive if drive > 0.001 else None)
    return out


def drive_of(res):
    d = min(max((res - 0.5) * 2, 0.0), 1.0)
    return d * d


def coeffs(knob, res):
    hz = curve(0x08060640, knob + 1 if knob < 0 else knob)
    q = curve(0x080606C0, res)
    hz = min(max(hz, 10.0), 0.45 * 48000)
    q = min(max(q, 0.1), 40.0)
    x = math.pi * hz / 48000
    return x * (15 - x * x) / (15 - 6 * x * x), 1 / q, hz, q


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- bypass
reset()
setup(0.0)
x = sine(1000)
l, _ = run(x)
check("Filter knob at centre, Interp Normal: buffer untouched", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))
setup(-0.5)
l, _ = run(x, silent=True)
check("silent buffer: untouched, as stock", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))

# --- the filter matches the stmlib SVF model, block after block
reset()
setup(-0.4, res=0.3)
g, r, hz, q = coeffs(-0.4, 0.3)
check(f"stock curves give a usable cutoff and Q (knob -0.4 -> {hz:.0f} Hz, res 0.3 -> Q {q:.2f})", 20 < hz < 20000 and 0.1 <= q <= 40)
sig = [math.sin(i * 0.37) * 0.3 + math.sin(i * 0.05) * 0.4 for i in range(3 * N)]
states, ms, err = [[0.0, 0.0], [0.0, 0.0]], [g, r, 0.0], 0.0
for b in range(3):
    l, _ = run(sig[b * N:(b + 1) * N])
    if b:
        ms = [m + 0.33333 * (t - m) for m, t in zip(ms, (g, r, 0.0))]
    ref = model_block(sig[b * N:(b + 1) * N], ms[0], ms[1], ms[2], states, False)
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
check("low-pass output equals the model (two stmlib SVF stages, coefficient smoothing) over three blocks", err < 1e-4, err)
reset()
setup(0.5, res=0.9)
g, r, _, _ = coeffs(0.5, 0.9)
d = drive_of(0.9)
states, ms, err = [[0.0, 0.0], [0.0, 0.0]], [g, r, d], 0.0
loud = [v * 2.0 for v in sig]
for b in range(3):
    l, _ = run(loud[b * N:(b + 1) * N])
    ref = model_block(loud[b * N:(b + 1) * N], ms[0], ms[1], ms[2], states, True)
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
check(f"high-pass with drive (Res 0.9 -> drive {d:.2f}) equals the model", err < 1e-4, err)

# --- low-pass and high-pass behave
def response(knob, res, hz_test, blocks=8):
    reset()
    setup(knob, res)
    out = []
    for b in range(blocks):
        l, _ = run(sine(hz_test, start=b * N))
        out += l
    return rms(out[N * 4:]) / rms(sine(hz_test, n=N * 4))


lp_low, lp_high = response(-0.6, 0.5, 100), response(-0.6, 0.5, 12000)       # Res 0.5 = the stock default (Q 1.35)
hz = coeffs(-0.6, 0.5)[2]
check(f"LP at {hz:.0f} Hz passes 100 Hz and cuts 12 kHz", lp_low > 0.9 and lp_high < 0.1, (lp_low, lp_high))
hp_low, hp_high = response(0.6, 0.5, 100), response(0.6, 0.5, 12000)
hz = coeffs(0.6, 0.5)[2]
check(f"HP at {hz:.0f} Hz cuts 100 Hz and passes 12 kHz", hp_low < 0.1 and hp_high > 0.9, (hp_low, hp_high))
fc = coeffs(-0.6, 0.5)[2]
one, two = response(-0.6, 0.5, fc * 2), response(-0.6, 0.5, fc * 4)
check(f"24 dB/oct: one octave above cutoff {20 * math.log10(one):.0f} dB, two octaves {20 * math.log10(two):.0f} dB", two < 0.02 and two / one < 0.09, (one, two))
fc = coeffs(-0.5, 0.0)[2]
flat, peak = response(-0.5, 0.0, fc), response(-0.5, 0.5, fc)
check(f"resonance raises the level at the cutoff ({fc:.0f} Hz): x{peak / flat:.1f} at the default Res", peak > 3 * flat, (flat, peak))


def thd(knob, res, amp, hz):
    reset()
    setup(knob, res)
    out = []
    for b in range(16):
        l, _ = run(sine(hz, start=b * N, amp=amp))
        out += l
    y = out[8 * N:]
    t0 = 8 * N
    c = sum(v * math.cos(2 * math.pi * hz * (t0 + i) / 48000) for i, v in enumerate(y)) * 2 / len(y)
    s_ = sum(v * math.sin(2 * math.pi * hz * (t0 + i) / 48000) for i, v in enumerate(y)) * 2 / len(y)
    fund = [s_ * math.sin(2 * math.pi * hz * (t0 + i) / 48000) + c * math.cos(2 * math.pi * hz * (t0 + i) / 48000) for i in range(len(y))]
    return rms([a - b for a, b in zip(y, fund)]) / max(rms(fund), 1e-9), rms(y)


clean, lvl_clean = thd(-0.4, 0.5, 0.5, 375)
driven, lvl_driven = thd(-0.4, 0.95, 0.5, 375)
check(f"Res at default: clean (distortion {clean * 100:.2f}%)", clean < 0.01, clean)
check(f"Res near full: driven (distortion {driven * 100:.0f}%)", driven > 0.05, driven)
a1, _ = thd(-0.4, 0.5, 0.1, 375)
_, l1 = thd(-0.4, 0.5, 0.1, 375)
_, l5 = thd(-0.4, 0.5, 0.5, 375)
check("Res at default is linear: 5x the input gives 5x the output", abs(l5 / l1 - 5) < 0.05, l5 / l1)
reset()
setup(-0.3, 1.0)
worst = 0.0
for b in range(400):
    l, _ = run([((i * 7919 + b * 104729) % 2001 - 1000) / 1000.0 for i in range(N)])
    worst = max(worst, max(abs(v) for v in l))
check(f"maximum resonance on full-scale noise stays bounded (peak {worst:.1f})", worst < 4 and not math.isnan(worst), worst)
reset()
setup(-1.0, 0.0)
l, _ = run([0.5] * N)
check("knob fully left: still finite and closed", all(abs(v) < 0.6 for v in l))

# --- stereo: both channels filtered, independently
reset()
setup(-0.6, 0.2)
lo, hi = sine(100), sine(12000)
l, r = run(lo, hi)
reset()
setup(-0.6, 0.2)
l2, _ = run(lo)
check("stereo: left matches the mono run, right is filtered on its own", max(abs(a - b) for a, b in zip(l, l2)) < 1e-6 and rms(r) < rms(hi))

# --- crunch
reset()
setup(0.0, interp=9 + 1)                       # 12k
x = sine(997, n=N)
l, _ = run(x)
runs, k = [], 0
while k < N:
    j = k
    while j < N and l[j] == l[k]:
        j += 1
    runs.append(j - k)
    k = j
check("12k: output holds each value for 4 samples (48k / 12k)", all(v == 4 for v in runs[1:-1]), runs)
check("12k: held values are 12-bit (multiples of 1/2048)", all(abs(v * 2048 - round(v * 2048)) < 1e-3 for v in l))
reset()
setup(0.0, interp=9 + 2)                       # 10k: non-integer ratio
l, _ = run([0.9 * i / N for i in range(N)])    # a ramp, so every held value differs
runs, k = [], 0
while k < N:
    j = k
    while j < N and l[j] == l[k]:
        j += 1
    runs.append(j - k)
    k = j
check("10k: holds alternate 4 and 5 samples (average 4.8)", set(runs[1:-1]) <= {4, 5} and abs(N / len(runs) - 4.8) < 0.6, runs)
reset()
setup(0.0, interp=9 + 5)                       # 4k
a, _ = run(sine(997, n=N))
b, _ = run(sine(997, n=N, start=N))
joined = a + b
runs, k = [], 0
while k < 2 * N:
    j = k
    while j < 2 * N and joined[j] == joined[k]:
        j += 1
    runs.append(j - k)
    k = j
check("4k: holds 12 samples, continuing across the block boundary", all(v == 12 for v in runs[1:-1]), runs)
reset()
setup(0.0, interp=9 + 1)
l, _ = run(sine(997), pad=0)
check("no Interp location passed: no crunch", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
for v, name in ((0, "Normal"), (1, "HighQ"), (16, "a value past the list")):
    reset()
    setup(0.0, interp=v)
    l, _ = run(sine(997))
    check(f"Interp {name}: no crunch", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
reset()
setup(-0.6, 0.0, interp=9 + 3)                 # 8k into the low-pass
l, _ = run(sine(997))
check("crunch and filter together: crunched, then low-passed (no longer stair-stepped)", len(set(l)) > N // 2)
reset()
setup(-0.6, 0.3)
l, _ = run(sine(997))
check("state from an older build (magic SVF1 - SVF4) is reinitialised, not reused", e.r32(OBJ + 4) == 0x53564635)

# --- call sites
reset()
setup(0.0, interp=9 + 1)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.uc.reg_write(UC_ARM_REG_R6, PAD)
e.call("filter_voice_a", OBJ, BUF)
l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
check("sample-pad call site passes its pad (r6): crunch applies", len(set(l)) <= N // 4 + 1)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
CPAD = 0x24050000                               # class B: the pad is in r6 at the call (3.1.U; it was object - 0x3ac)
e.w32(CPAD + 0x18, 3 << 8 | 0)
set_interp(0, row=3, col=0)
e.uc.reg_write(UC_ARM_REG_R6, CPAD)
e.call("filter_voice_b", OBJ, BUF, PAD)
l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
check("clip / slicer call site, Interp Normal in the app's record: no crunch", len(set(l)) > N // 2)
reset()
set_interp(9 + 1, row=3, col=0)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.uc.reg_write(UC_ARM_REG_R6, CPAD)
e.call("filter_voice_b", OBJ, BUF, PAD)
l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
check("clip / slicer call site takes its pad from r6 and finds its Interp (12k): crunch applies", len(set(l)) <= N // 4 + 1)
OBJV = OBJ + 0x700                              # another voice of the same pad: its filter object is somewhere else
e.w32(OBJV + 0x84, PARAMS)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.uc.reg_write(UC_ARM_REG_R6, CPAD)
e.call("filter_voice_b", OBJV, BUF, PAD)
l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
check("  a second voice of the same clip / slicer pad gets the pad's Fidelity too (3.1.d - T: only the first did)", len(set(l)) <= N // 4 + 1)

# --- the engine resetting its own copy of Interp does not stop the crunch (the 3.1.f report)
reset()
setup(0.0, interp=9 + 1)
e.w32(PAD + 0x578, 0)
l, _ = run(sine(997))
check("engine copy reset to Normal, app record still 12k: crunch keeps going", len(set(l)) <= N // 4 + 1)
set_interp(1)
l, _ = run(sine(997))
check("app record set to HighQ: crunch stops", len(set(l)) > N // 2)
e.w32(PAD + 0x18, 7 << 8 | 0)
set_interp(9 + 1)
l, _ = run(sine(997))
check("a pad id outside the 4x4 grid reads as Normal (no stray lookups)", len(set(l)) > N // 2)


# --- pad pages: Interp right under Saturation
def page(addr):
    ids = []
    for k in range(36):
        v = e.r16(addr + 2 * k)
        if v == 0:
            break
        ids.append(v)
    return ids


check("Sample pad page: Saturation, Fidelity, Insert, Input, then the rest", page(0x080EFD38) == [0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0x6A, 0xD0, 0xF5], [hex(v) for v in page(0x080EFD38)])
check("Multisample pad page: same", page(0x080EFBD0) == [0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0x6A], [hex(v) for v in page(0x080EFBD0)])
check("Slicer pad page: same (Interp added)", page(0x080EF900) == [0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5], [hex(v) for v in page(0x080EF900)])
check("Clip pad page: same (Interp added)", page(0x080EFA68) == [0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5], [hex(v) for v in page(0x080EFA68)])

# --- Interp list
seen = {}
e.stub(0x0808C0D8, lambda: seen.update(names=e.arg(3), count=e.r32(e.uc.reg_read(UC_ARM_REG_SP)), param=e.arg(1), label=e.cstr(e.arg(2)), xml=e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))
e.w32(STACK, 2)
e.w32(STACK + 4, 0x080CC794)
e.call("interp_register", 0x24001000, 0xF1, 0, 0x080EB7E0)
names = [e.cstr(e.r32(seen["names"] + 4 * i)) for i in range(seen["count"])]
check("Fidelity list: the machines together (SP 45 beside S950 Lo, requested for 3.2.b), then the plain crunches 16k .. 2k", names == ["Normal", "HighQ", "SP1200", "SP-12", "S950", "MPC60", "SP Raw", "S950 Lo", "SP 45", "16k", "12k", "10k", "8k", "6k", "4k", "2k"] and seen["param"] == 0xF1, names)

check("label reads 'Fidelity:', xml name stays 'interpqual'", seen["label"] == "Fidelity:" and seen["xml"] == "interpqual", (seen["label"], seen["xml"]))


# --- machine modes, output side (the reader side is test_machine.py)
def runs_of(x):
    r, k = [], 0
    while k < len(x):
        j = k
        while j < len(x) and x[j] == x[k]:
            j += 1
        r.append(j - k)
        k = j
    return r


e.uc.mem_write(OBJ + 0x60, b"\xa5" * 0x14)        # stale stock words where the output stage keeps its state
reset()
setup(0.0, interp=2)                              # SP1200
blocks = [run(sine(997, start=b * N))[0] for b in range(4)]
first = blocks[0]
check("SP1200 output: finite after stale stock words in the state area", all(math.isfinite(v) for v in first))

# --- 3.1.T: the S950 modes' output side. The low-pass is src/s950.c, also compiled for the Mac (host/libdsp.dylib):
# the ARM build here must give what the Mac build gives.
import ctypes

import numpy as np

host = ctypes.CDLL("host/libdsp.dylib")
FP = ctypes.POINTER(ctypes.c_float)
host.s950_filter_count.argtypes = [ctypes.c_float, ctypes.c_uint]
host.s950_filter_count.restype = ctypes.c_uint
host.s950_filter.argtypes = [FP, ctypes.POINTER(FP), ctypes.c_int, ctypes.c_uint]


class HostFilter:
    def __init__(self):
        self.z = np.zeros(12, np.float32)

    def run(self, x, count):
        blk = np.array(x, np.float32)
        host.s950_filter(self.z.ctypes.data_as(FP), (FP * 2)(blk.ctypes.data_as(FP), None), len(blk), count)
        return [float(v) for v in blk]


def q12(x):
    return [round(v * 2048) / 2048 for v in x]


# backup SRAM (master.c keeps the SDRAM block's address there) and its clock: mapped at the top
e.uc.mem_map(0xC0000000, 0x100000)                  # the whole block (0x94900 since 3.3.z)
SDRAM, BANK = 0xC0000000, 0xC0000000 + 0x56800 + 0x7000


def sdram(on=True):
    e.w32(0x38800F70, SDRAM if on else 0)
    e.w32(0x38800F74, SDRAM ^ 0x5052534D)


def fresh():
    """a filter object as after boot: stale words in its own state, no slot in the bank"""
    reset()
    e.w32(BANK + 4, 0)


def tone(hz, b, amp=0.4):
    return [amp * math.sin(2 * math.pi * hz * (b * N + i) / 48000) for i in range(N)]


def err(a, b):
    return max(abs(p - q) for p, q in zip(a, b))


sdram()
check("the filter's count: 0.4 x the voice clock, never under 5 (16 kHz), from the OS's table",
      [host.s950_filter_count(c, 168) for c in (96000, 48000, 40000, 31250, 24000, 12000, 4000)] == [5, 5, 5, 6, 8, 16, 50]
      and host.s950_filter_count(48000, 132) == 36 and host.s950_filter_count(48000, 98) == 255,
      [host.s950_filter_count(c, 168) for c in (96000, 48000, 40000, 31250, 24000, 12000, 4000)])

# clip / slicer voice (no reader): 12 bits here, then the 16 kHz low-pass
setup(0.0, interp=4)
fresh()
e.uc.mem_write(OBJ + 0x60, b"\xa5" * 0x14)        # stale stock words where the output stage keeps its state
hf, worst = HostFilter(), 0.0
for b in range(6):
    x = tone(3000, b)
    worst = max(worst, err(run(x)[0], hf.run(q12(x), 5)))
check(f"S950 on a clip / slicer voice: 12 bits, then the Mac build's 16 kHz low-pass, six blocks (max diff {worst:.1e})", worst < 2e-5, worst)
check("  its state is the bank's first slot, keyed by the filter object", e.r32(BANK) == 0x53393530 and e.r32(BANK + 4) == 1
      and e.r32(BANK + 8) == OBJ and e.r32(OBJ + 0x64) == 0)
l, dry = [], []
for b in range(8):
    l += run(tone(20000, b))[0]
    dry += tone(20000, b)
att = 20 * math.log10(rms(l[2 * N:]) / rms(dry[2 * N:]))
check(f"S950: a 20 kHz tone comes out {att:.1f} dB (the chip: -11.9 dB, and the DAC's hold takes about 2 more)", -17 < att < -11, att)
l, dry = [], []
for b in range(8):
    l += run(tone(1000, b))[0]
    dry += tone(1000, b)
check(f"S950: 1 kHz passes at {20 * math.log10(rms(l[2 * N:]) / rms(dry[2 * N:])):+.2f} dB", abs(rms(l[2 * N:]) / rms(dry[2 * N:]) - 1) < 0.01)

# sample-pad voice: the reader did the 12 bits and left the rate at object + 0x60; the filter follows the clock
fresh()
e.uc.mem_write(OBJ + 0x60, struct.pack("<f", -0.5))        # an octave down, reversed
hf, worst, smooth = HostFilter(), 0.0, []
for b in range(6):
    x = tone(3000, b, amp=0.31234)
    y = run(x, sample_voice=1)[0]
    worst = max(worst, err(y, hf.run(x, 8)))
    smooth += y
check(f"S950 on a sample-pad voice an octave down: no second rounding, low-pass at 10 kHz = 0.4 x 24 kHz (max diff {worst:.1e})",
      worst < 2e-5, worst)
fresh()
e.uc.mem_write(OBJ + 0x60, struct.pack("<f", float("nan")))
hf, worst = HostFilter(), 0.0
for b in range(3):
    x = tone(3000, b)
    worst = max(worst, err(run(x, sample_voice=1)[0], hf.run(q12(x), 5)))
check("  a rate that is not a number is ignored: treated as a voice without a reader", worst < 2e-5, worst)

# S950 Lo on a clip / slicer voice: the 31.25 kHz hold stands in for the missing reader, low-pass at 13.3 kHz
setup(0.0, interp=7)
fresh()
hf, worst = HostFilter(), 0.0
ph, held, one = np.float32(0.0), 0.0, np.float32(1.0)
for b in range(6):
    x, h = tone(2000, b), []
    for v in x:
        ph = np.float32(ph + np.float32(31250.0) / np.float32(48000.0))     # single precision, as on the chip
        if ph >= one:
            ph = np.float32(ph - one)
            held = round(v * 2048) / 2048
        h.append(held)
    worst = max(worst, err(run(x)[0], hf.run(h, 6)))
check(f"S950 Lo on a clip / slicer voice: 31.25 kHz hold + 12 bits, then the low-pass at 13.3 kHz (max diff {worst:.1e})", worst < 2e-5, worst)

# a second filter object gets its own slot; the first keeps its own
setup(0.0, interp=4)
fresh()
run(tone(3000, 0))
OBJ2 = OBJ + 0x800
e.w32(OBJ2 + 0x84, PARAMS)
setup(0.0, interp=4)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *tone(3000, 0)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.call("filter_process", OBJ2, BUF, PAD, 0, count=20_000_000)
check("a second voice takes the next slot", e.r32(BANK + 4) == 2 and e.r32(BANK + 8 + 52) == OBJ2 and e.r32(OBJ2 + 0x64) == 1)

# back and forth between modes: the SP stage reads the slot number as (almost) zero, and S950 finds its slot again
setup(0.0, interp=2)
l = run(tone(997, 0))[0]
check("S950 -> SP1200 on the same voice: no jump (the slot number reads as zero state)", max(abs(v) for v in l) < 0.5)
setup(0.0, interp=4)
l = run(tone(997, 1))[0]
check("SP1200 -> S950: the voice's own slot again, started clean", e.r32(BANK + 4) == 2 and e.r32(OBJ + 0x64) == 0
      and all(math.isfinite(v) for v in l) and max(abs(v) for v in l) < 0.5)

# no SDRAM block (the boot hook did not run): 12 bits, no low-pass, no crash
sdram(False)
reset()
x = tone(3000, 0)
check("no SDRAM block: the voice goes without the low-pass", err(run(x)[0], q12(x)) < 1e-6)
sdram()

# the bank full: voice 257 goes without, nothing is overwritten
e.w32(BANK + 4, 256)
e.w32(BANK + 8 + 255 * 52, 0x24012340)
OBJ3 = OBJ + 0x1000
e.w32(OBJ3 + 0x84, PARAMS)
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *x))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.call("filter_process", OBJ3, BUF, PAD, 0, count=20_000_000)
check("bank full: no slot, no low-pass, the bank untouched", e.r32(BANK + 4) == 256 and e.r32(BANK + 8 + 255 * 52) == 0x24012340
      and err(struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N)), q12(x)) < 1e-6)
e.w32(BANK + 4, 2)

# the reader's call sites note the rate in the voice
VOICE = 0x24068000
e.stub(e.sym["voice_read"] & ~1, value=1)
e.uc.reg_write(UC_ARM_REG_R4, VOICE)
e.uc.reg_write(UC_ARM_REG_S1, struct.unpack("<I", struct.pack("<f", 0.7071))[0])
e.call("voice_read_a", 0, 0)
check("voice_read_a: the rate lands at voice + 0xa8 + 0x60 (the filter object's output-stage rate)",
      abs(struct.unpack("<f", e.uc.mem_read(VOICE + 0xA8 + 0x60, 4))[0] - 0.7071) < 1e-6)
del e.stubs[e.sym["voice_read"] & ~1]
e.uc.reg_write(UC_ARM_REG_R4, 0)

setup(0.0, interp=4)
reset()
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *tone(3000, 0)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
count = [0]
h = e.uc.hook_add(1 << 2, lambda uc, a, sz, _: count.__setitem__(0, count[0] + 1))     # UC_HOOK_CODE
e.call("filter_process", OBJ, BUF, PAD, 1, count=20_000_000)
e.uc.hook_del(h)
print(f"     S950 output stage: {count[0]} instructions per 64-frame mono block")
setup(0.0, interp=2)
reset()

# --- 3.1.n: SP Raw = SP1200 without the output filter; Saturation = input drive in machine modes
def hold_model(x, rate=26040.0):
    out, ph, held = [], 0.0, 0.0
    for v in x:
        ph += rate / 48000.0
        if ph >= 1.0:
            ph -= 1.0
            held = round(v * 2048) / 2048
        out.append(held)
    return out


setup(0.0, interp=6)                           # SP Raw
reset()
x = sine(997, amp=0.4)
l = run(x)[0]
check("SP Raw: just the 26.04 kHz hold + 12 bits, no output filter", max(abs(a - b) for a, b in zip(l, hold_model(x))) < 1e-6)
setup(0.0, interp=2)
reset()
e.uc.mem_write(OBJ + 0x60, bytes(0x14))
l9 = run(x)[0]
check("SP1200 (filtered) differs from SP Raw", max(abs(a - b) for a, b in zip(l9, hold_model(x))) > 1e-3)

setup(0.0, interp=6)
set_interp(6, sat=1000)
reset()
loud = sine(997, amp=0.8)
l = run(loud)[0]
post = 1 / (1 + 1.1)
check(f"drive 100 %: +18 dB into a hard clip at full scale, level back ({max(abs(v) for v in l):.3f} peak = {post:.3f})",
      abs(max(abs(v) for v in l) - round(post * 2048) / 2048) < 2e-3)
flat = sum(1 for v in l if abs(abs(v) - max(abs(v) for v in l)) < 1e-3)
check(f"drive 100 %: a loud loop keeps its level ({20 * math.log10(rms(l) / rms(loud)):+.1f} dB RMS)", abs(20 * math.log10(rms(l) / rms(loud))) < 2.0)
check(f"drive 100 %: clipped flat tops ({flat} of {len(l)} samples at the ceiling)", flat > len(l) // 3)
set_interp(6, sat=0)
reset()
l = run(loud)[0]
check("drive 0 %: untouched (exactly the hold + 12 bits)", max(abs(a - b) for a, b in zip(l, hold_model(loud))) < 1e-6)
set_interp(0, sat=1000)
reset()
l = run(sine(997))[0]
check("Saturation in Normal Fidelity: no drive here (the warm saturation in od.c handles it)", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))

# --- 3.3.z: THE POP AT THE CENTRE. Filter 0 = off, left = low-pass, right = high-pass; a switch is one block's S-curve
# crossfade (scratch in master.c's SDRAM block) and a low-pass starts from the input level. Click measure: the largest
# second difference, against a clean 110 Hz sine's own (1.0e-4). 3.3.y: 0.0138 turning slowly through 0, 0.70 with an
# LFO jumping from one side to the other.
sdram(True)


def sweep(knobs, hz=110, amp=0.5):
    out, t = [], 0
    for k in knobs:
        setup(k)
        out += run(sine(hz, N, t, amp))[0]
        t += N
    return out


def click(y):
    return max(abs(y[i + 1] - 2 * y[i] + y[i - 1]) for i in range(N, len(y) - 1))


reset()
slow = click(sweep([round(-0.1 + 0.005 * i, 4) for i in range(41)]))
check(f"turning the Filter slowly through 0: no click ({slow:.5f}; 3.3.y 0.0138)", slow < 0.002, slow)
reset()
lfo = click(sweep([-0.05, 0.05] * 10))
check(f"an LFO jumping across 0 every block: no pop ({lfo:.5f}; 3.3.y 0.70)", lfo < 0.002, lfo)
reset()
held = click(sweep([-0.05] * 12))
check(f"held on one side: the filter alone, no artefact ({held:.6f})", held < 0.0002, held)
reset()
setup(0.0)
run(sine(110, N, 0))
setup(-0.6)
y = run(sine(110, N, N))[0]
check("a low-pass switched on mid-wave starts from the signal, not from 0 (first sample within 0.05 of the input)",
      abs(y[0] - sine(110, N, N)[0]) < 0.05, (y[0], sine(110, N, N)[0]))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
