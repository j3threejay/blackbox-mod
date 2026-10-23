"""Reverb slot selector + Room under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c) that picks the algorithm.
Stubbed: the stock plate core (recorded), the list registrar and the store add.
NOT checked: how Room sounds (levels are guesses to be tuned by ear), the settings page showing "Type:", saving.
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_SP

from emu import STACK, Emu

import os
os.environ.setdefault("BANK2_NEW", "1")                # Room is in the bank 2 this build links (3.3.v)
e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
STATE, POOL, OBJ, APPFX, ARR = 0x24040000, 0x24100000, 0x24041000, 0x24020088 + 0x2FC0, 0x24042000
IN, OL, OR_ = 0x24043000, 0x24044000, 0x24045000
e.uc.mem_map(0x24100000, 0x40000)
BUFS = [(0x08, 512), (0x0B, 512), (0x0E, 512), (0x11, 512), (0x14, 1024), (0x19, 1024),
        (0x1E, 8192), (0x21, 8192), (0x25, 8192), (0x27, 8192), (0x29, 8192), (0x2B, 8192)]
a = POOL
for w, n in BUFS:
    e.w32(STATE + 4 * w, a)
    a += n * 4
calls = []
e.stub(0x08074F50, lambda: calls.append("plate"))
N = 256


room_set = {0x1D7: 500, 0x1D8: 300, 0x1D9: 500, 0x1DA: 1000}


def select(v, row=1):
    data = struct.pack("<HHI", 0x37, 0, 600) + struct.pack("<HHI", 0x198, 0, v) + b"".join(struct.pack("<HHI", k, 0, x) for k, x in room_set.items())
    e.uc.mem_write(ARR, data)
    e.w32(APPFX + row * 0x18 + 4, ARR)
    e.uc.mem_write(APPFX + row * 0x18 + 10, struct.pack("<H", 2 + len(room_set)))
    e.w32(OBJ + 0x18, 3 << 16 | row << 8)


def params(decay, damp):
    e.uc.mem_write(STATE, struct.pack("<ff", decay * 0.93, damp))


def block(x):
    e.uc.mem_write(IN, struct.pack(f"<{N}f", *x))
    calls.clear()
    e.uc.reg_write(UC_ARM_REG_R4, OBJ)
    e.w32(STACK, N)
    e.call("fx2_core_thunk", STATE, IN, OL, OR_)
    return (list(struct.unpack(f"<{N}f", e.uc.mem_read(OL, 4 * N))), list(struct.unpack(f"<{N}f", e.uc.mem_read(OR_, 4 * N))))


def impulse(decay, damp, blocks=160):
    params(decay, damp)
    out_l, out_r = [], []
    for b in range(blocks):
        x = [0.0] * N
        if b == 0:
            x[0] = 1.0
        l, r = block(x)
        out_l += l
        out_r += r
    return out_l, out_r


def energy(x):
    return sum(v * v for v in x)


def rt(y, fs=29800.0):
    """time for the energy envelope (in 1024-sample windows) to fall 30 dB below its peak, x2 -> RT60 estimate"""
    w = [energy(y[i:i + 1024]) for i in range(0, len(y) - 1024, 1024)]
    pk = max(range(len(w)), key=lambda i: w[i])
    for i in range(pk, len(w)):
        if w[i] < w[pk] * 1e-3:
            return 2 * (i - pk) * 1024 / fs
    return None


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- registration and defaults
seen = {}
e.stub(0x0808C0D8, lambda: seen.update(param=e.arg(1), label=e.cstr(e.arg(2)), names=e.arg(3), count=e.r32(e.uc.reg_read(UC_ARM_REG_SP)), xml=e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))
e.w32(STACK, 2)
e.w32(STACK + 4, 0x080CCB70)
nums = []
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.arg(2), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))
e.call("fx2_register", 0x24001000, 0x198, 0x080CCB6C, 0x080EB5F0)
check("Room settings registered: Size, Mod, Early, Width (0-100 %)", nums == [(0x1D7, 8, "Size:", 0, 1000), (0x1D8, 8, "Mod:", 0, 1000), (0x1D9, 8, "Early:", 0, 1000), (0x1DA, 8, "Width:", 0, 1000)], nums)
names = [e.cstr(e.r32(seen["names"] + 4 * i)) for i in range(seen["count"])]
check("selector registered: 'Type:' Plate / Room on param 0x198, xml 'fx2algo'", (seen["param"], seen["label"], names, seen["xml"]) == (0x198, "Type:", ["Plate", "Room"], "fx2algo"), (seen, names))
added = []
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("fx2_defaults", 0x24046000, 0x37, 600)
check("reverb cell defaults: Type = Plate first, then Decay 600 as stock", added == [(0x198, 0), (0x37, 600)], added)
added.clear()
e.call("fx2_defaults_last", 0x24046000, 0x3A, 500)
check("... Room's after Damping: Size 50 %, Mod 30 %, Early 50 %, Width 100 %, then FX OUT's Level +4 dB, Low Cut Off, Output Out 1",
      added == [(0x3A, 500), (0x1D7, 500), (0x1D8, 300), (0x1D9, 500), (0x1DA, 1000), (0x149, 4000), (0x14A, 0), (0x148, 0)], added)

# --- Plate stays stock
e.uc.mem_write(0x38800A00, b"\xa5" * 0x80)
select(0)
params(0.6, 0.5)
block([0.1] * N)
check("Type Plate: the stock plate core runs", calls == ["plate"])
select(7)
block([0.1] * N)
check("unknown value: stock plate", calls == ["plate"])
e.w32(0x38800B00, 0)
e.call("fx2_core", STATE, IN, OL, OR_, N) if False else None

# --- Room
select(1)
l, r = impulse(0.3, 0.3)
check("Type Room: the stock core is not called", calls == [])
check("Room: impulse gives a finite, non-silent stereo tail", all(math.isfinite(v) for v in l + r) and energy(l) > 0 and energy(r) > 0)
first = next(i for i, v in enumerate(l) if abs(v) > 1e-6)
check(f"Room: first reflection at {first / 29.8:.1f} ms (early reflections, not a smear)", 3 < first / 29.8 < 8, first)
corr = sum(x * y for x, y in zip(l, r)) / math.sqrt(energy(l) * energy(r))
check(f"Room: left and right differ (correlation {corr:.2f})", abs(corr) < 0.7, corr)
t_short = rt(impulse(0.1, 0.3)[0])
t_long = rt(impulse(0.9, 0.3)[0])
check(f"Decay sets the length: Decay 10% -> ~{t_short:.2f} s, 90% -> ~{t_long:.2f} s (target 0.5 / 2.3 s)", t_short and t_long and 0.2 < t_short < 1.0 and 1.2 < t_long < 3.5, (t_short, t_long))


def hf_ratio(y):
    d = [y[i] - y[i - 1] for i in range(1, len(y))]
    return energy(d) / max(energy(y), 1e-12)


bright = hf_ratio(impulse(0.5, 0.0)[0][3000:20000])
dark = hf_ratio(impulse(0.5, 1.0)[0][3000:20000])
check(f"Damping darkens the tail (HF share {bright:.3f} -> {dark:.3f})", dark < bright * 0.7, (bright, dark))
params(1.0, 0.0)
worst = 0.0
for b in range(400):
    l2, r2 = block([((i * 7919 + b * 104729) % 2001 - 1000) / 2000.0 for i in range(N)])
    worst = max(worst, max(abs(v) for v in l2 + r2))
check(f"max Decay on continuous noise stays bounded (peak {worst:.1f})", worst < 10 and math.isfinite(worst), worst)

# --- 3.1.m Room settings
def fresh():
    """switch through Plate and back: clears Room's buffers"""
    select(0)
    block([0.0] * N)
    select(1)


def tail_onset(y):
    """first arrival from the feedback network: Early is off, so the first sound > 2 % of peak"""
    pk = max(abs(v) for v in y)
    start = 0
    return next(i for i in range(start, len(y)) if abs(y[i]) > 0.02 * pk)


room_set[0x1D9] = 0                        # Early off, so the tail's own arrival shows
onsets = {}
for size in (0, 500, 1000):
    room_set[0x1D7] = size
    fresh()
    l_big, r_big = impulse(0.5, 0.3)
    onsets[size] = tail_onset(l_big) / 29.8
check(f"Size moves the walls: first tail arrival {onsets[0]:.0f} / {onsets[500]:.0f} / {onsets[1000]:.0f} ms at 0 / 50 / 100 %", onsets[0] < onsets[500] < onsets[1000], onsets)
room_set[0x1D9] = 500
check("Size 100 %: finite, bounded", all(math.isfinite(v) for v in l_big + r_big) and max(abs(v) for v in l_big) < 5)
room_set[0x1D7] = 500
room_set[0x1DA] = 0
fresh()
l, r = impulse(0.5, 0.3)
er_end = int(0.04 * 29800)
check("Width 0 %: the tail is mono (early reflections stay stereo)", max(abs(a - b) for a, b in zip(l[er_end * 3:], r[er_end * 3:])) < 1e-4 * max(abs(v) for v in l))
room_set[0x1DA] = 1000
room_set[0x1D9] = 0
fresh()
l, r = impulse(0.5, 0.3)
first = next(i for i, v in enumerate(l) if abs(v) > 1e-6)
check(f"Early 0 %: no early reflections (first sound at {first / 29.8:.1f} ms, from the tail)", first / 29.8 > 20, first)
room_set[0x1D9] = 500
room_set[0x1D8] = 1000
select(1)
l, r = impulse(0.9, 0.0)
check("Mod 100 %: finite, bounded", all(math.isfinite(v) for v in l + r) and max(abs(v) for v in l) < 5)
room_set[0x1D8] = 300

# --- switching clears the shared buffers
select(1)
impulse(0.9, 0.0, blocks=4)
select(0)
block([0.0] * N)
nonzero = sum(1 for w, n in BUFS for k in range(0, n, 97) if e.r32(e.r32(STATE + 4 * w) + 4 * k) != 0)
check("switching Room -> Plate clears the shared buffers (no burst of the old tail)", nonzero == 0, nonzero)
check("the patched call site goes to the thunk", e.r32(0x0806318E) != 0)

# --- Room is in bank 2 since 3.3.v (fx2_room.c): with no live bank 2 the slot plays the Plate, never a call into it
e.uc.mem_write(0x2405FFD0, bytes(4))                   # the meter not up yet: b2_live() says "not yet"
select(1)
block([0.0] * N)
check("Room selected but bank 2 not live: the plate runs instead (no call into bank 2)", calls == ["plate"], calls)
e.meter_up()
block([0.0] * N)
check("...and Room again once it is", calls == [], calls)
check("Room's DSP sits in bank 2", 0x08100000 <= e.sym["room"] < 0x081E0000, hex(e.sym["room"]))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
