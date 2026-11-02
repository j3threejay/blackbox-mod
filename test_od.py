"""Pad overdrive replacement under Unicorn.

Real firmware runs for: the stock overdrive setup (FUN_080707c0, which turns the knob into the stock pre-gain).
Reference: a Python model of the new curve, so these checks pin the arithmetic, not the sound.
NOT checked: the sound, and that the backup SRAM clock / write enable behave on the unit (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)               # backup SRAM
e.uc.mem_map(0x58024000, 0x1000)               # RCC + PWR
OBJ, L, R = 0x24060000, 0x24061000, 0x24063000
N = 256


def setup(od, makeup=1.0, obj=OBJ):
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", od))[0])
    e.call(0x080707C0, obj)                     # stock (float od in s0): on flag, pre-gain 2^(6 od), 0.25
    e.uc.mem_write(obj + 0xC, struct.pack("<f", makeup))


def run(left, right=None, obj=OBJ):
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    if right is not None:
        e.uc.mem_write(R, struct.pack(f"<{len(right)}f", *right))
    e.call("od_process", obj, L, R if right is not None else 0, len(left))
    l = list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left))))
    r = list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(R, 4 * len(right)))) if right is not None else None
    return l, r


def sine(hz, n=N, start=0, amp=0.5):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def play(od, hz, amp, blocks=24, makeup=1.0):
    setup(od, makeup)
    e.uc.mem_write(0x38800000, b"\0" * 4)       # fresh state
    out = []
    for b in range(blocks):
        l, _ = run(sine(hz, start=b * N, amp=amp))
        out += l
    return out[N * 8:]


def harmonics(y, hz, t0, upto=4):
    amps = []
    for k in range(1, upto + 1):
        c = sum(v * math.cos(2 * math.pi * k * hz * (t0 + i) / 48000) for i, v in enumerate(y)) * 2 / len(y)
        s = sum(v * math.sin(2 * math.pi * k * hz * (t0 + i) / 48000) for i, v in enumerate(y)) * 2 / len(y)
        amps.append(math.hypot(c, s))
    return amps


def clip(u):
    u = max(-1.5, min(1.5, u))
    return u * (1 - 0.148148 * u * u)


def model(x, od, state, makeup=1.0):
    gain = 1 + 24 * od * od
    head = 2 - od
    k = 0.3 * min(1.0, 4 * od)
    post = makeup / (1 + 0.5 * (gain - 1) / (1 + 0.12 * gain))
    tone = 1 - 0.4 * od
    hx, hy, lp = state
    out = []
    for v in x:
        c = head * clip(v * gain / head)
        y = c + k * c * c
        h = y - hx + 0.99869 * hy
        hx, hy = y, h
        lp += tone * (h - lp)
        out.append(lp * post)
    state[:] = [hx, hy, lp]
    return out


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e.uc.mem_write(0x38800000, b"\xa5" * 0x400)    # backup SRAM holds whatever it held
setup(0.0)
x = sine(440)
l, _ = run(x)
check("Overdrive 0 (stock 'off'): untouched", max(abs(a - b) for a, b in zip(l, x)) < 1e-7)
setup(0.0, makeup=0.5)
l, _ = run(x)
check("Overdrive 0 with a stock make-up gain of 0.5: only that gain, as stock", max(abs(a - b * 0.5) for a, b in zip(l, x)) < 1e-7)

setup(0.6)
run(sine(440))
check("on: backup SRAM clock and backup-domain writes enabled", e.r32(0x580244E0) & (1 << 28) and e.r32(0x58024800) & (1 << 8))
state = [0.0, 0.0, 0.0]
sig = [0.7 * math.sin(i * 0.05) + 0.2 * math.sin(i * 0.9) for i in range(3 * N)]
err = 0.0
e.uc.mem_write(0x38800000, b"\0" * 4)
for b in range(3):
    l, _ = run(sig[b * N:(b + 1) * N])
    ref = model(sig[b * N:(b + 1) * N], 0.6, state)
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
check("Overdrive 0.6: output equals the model over three blocks (state carried between blocks)", err < 2e-3, err)

y = play(0.1, 220, 0.3)
h = harmonics(y, 220, N * 8)
check(f"low drive (0.1): nearly clean (2nd {20 * math.log10(h[1] / h[0]):.0f} dB, 3rd {20 * math.log10(h[2] / h[0]):.0f} dB) and level within 2 dB", h[1] / h[0] < 0.03 and h[2] / h[0] < 0.03 and abs(20 * math.log10(rms(y) / rms(sine(220, amp=0.3)))) < 2, (h, rms(y)))
y = play(0.4, 220, 0.3)
h = harmonics(y, 220, N * 8)
check(f"moderate drive (0.4): second harmonic leads (2nd {20 * math.log10(h[1] / h[0]):.0f} dB vs 3rd {20 * math.log10(h[2] / h[0]):.0f} dB)", h[1] > h[2] and h[1] / h[0] > 0.01, h)
y = play(1.0, 220, 0.5)
h = harmonics(y, 220, N * 8)
check(f"full drive: heavily saturated (3rd {20 * math.log10(h[2] / h[0]):.0f} dB)", h[2] / h[0] > 0.1, h)
check(f"full drive: no DC shift (mean {sum(y) / len(y):+.4f})", abs(sum(y) / len(y)) < 0.01)
check(f"full drive: peak {max(abs(v) for v in y):.2f}, level compensated within 6 dB of the dry sine", 0.5 < rms(y) / rms(sine(220)) < 2)
quiet, loud = rms(play(0.7, 220, 0.05)), rms(play(0.7, 220, 0.5))
check(f"drive 0.7 compresses: 20 dB more input gives {20 * math.log10(loud / quiet):.0f} dB more output", 20 * math.log10(loud / quiet) < 14)
bright_lo = rms(play(0.2, 9000, 0.05)) / rms(play(0.2, 200, 0.05))
bright_hi = rms(play(1.0, 9000, 0.05)) / rms(play(1.0, 200, 0.05))
check(f"tape tone: at full drive 9 kHz sits {20 * math.log10(bright_lo / bright_hi):.1f} dB lower against 200 Hz than at drive 0.2", bright_hi < bright_lo * 0.8, (bright_lo, bright_hi))

# --- stock curve, for the record: positive hard clip, lopsided
stock = []
for v in (0.5, -0.5):
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", v))[0])
    e.call(0x08060B34)
    stock.append(struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0)))[0])
mine = [clip(0.5), clip(-0.5)]
check(f"for the record: stock curve at +/-0.5 = {stock[0]:.2f} / {stock[1]:.2f}; new soft clip = {mine[0]:.2f} / {mine[1]:.2f} (symmetric; warmth comes from the squared term)", abs(stock[0] + stock[1]) > 0.2 and abs(mine[0] + mine[1]) < 1e-6)

# --- stereo and many pads
setup(0.5)
e.uc.mem_write(0x38800000, b"\0" * 4)
l, r = run(sine(300), sine(300))
check("stereo: both channels processed identically for identical input", max(abs(a - b) for a, b in zip(l, r)) < 1e-6)
for k in range(40):
    setup(0.5, obj=0x24070000 + k * 0x100)
    run(sine(300), obj=0x24070000 + k * 0x100)
check("40 pads: the bank fills (OBJ + 31 more) and the rest still process, stateless, without trouble", e.r32(0x38800004 + 31 * 28) == 0x24070000 + 30 * 0x100, hex(e.r32(0x38800004 + 31 * 28)))


# --- 3.1.n: sample pads in a Fidelity machine mode: the Saturation knob belongs to the machine's input drive (filter.c)
APP_PADS, ARR2 = 0x24020088 + 0x1840, 0x24073000
PAD = 0x24050000
OBJ_A = PAD + 0x560                             # FUN_080596b0: overdrive object = pad + 0x560
e.w32(PAD + 0x18, 1 << 8 | 2)                   # row 1, col 2


def fidelity(v):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR2, struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR2)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))


def run_a(left):
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.call("od_process_a", OBJ_A, L, 0, len(left))
    return list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left))))


setup(0.8, makeup=0.9, obj=OBJ_A)
fidelity(2)                                     # SP1200
x = sine(997)
y = run_a(x)
check("machine mode: the warm saturation stands aside (make-up gain only, like Overdrive off)", all(abs(a * 0.9 - b) < 1e-6 for a, b in zip(x, y)))
fidelity(0)
y = run_a(x)
check("Normal: the saturation runs as before", max(abs(a * 0.9 - b) for a, b in zip(x, y)) > 0.01)

# --- 3.1.U: clip / slicer pads too: their overdrive object is the pad + 0xb8c (FUN_08067fa4)
OBJ_B = PAD + 0xB8C


def run_b(left):
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.call("od_process_b", OBJ_B, L, 0, len(left))
    return list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left))))


setup(0.8, makeup=0.9, obj=OBJ_B)
for v, name in ((2, "SP1200"), (4, "S950"), (7, "S950 Lo")):
    fidelity(v)
    y = run_b(x)
    check(f"clip / slicer pad on {name}: the warm saturation stands aside", all(abs(a * 0.9 - b) < 1e-6 for a, b in zip(x, y)))
for v, name in ((0, "Normal"), (9, "12k")):
    fidelity(v)
    y = run_b(x)
    check(f"clip / slicer pad on {name}: the saturation runs as before", max(abs(a * 0.9 - b) for a, b in zip(x, y)) > 0.01)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
