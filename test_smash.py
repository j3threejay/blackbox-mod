"""Smash (compressor list value 7, src/smash.c) under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c), the output-buffer lookup and the stereo accessor, and the
engine's own call site (it calls comp_process through the patched bl).
Stubbed: the stock compressor (recorded), the downstream chain stage (recorded), the list registrar.
NOT checked: how it sounds (levels were tuned on the Mac build, host/dsp.py; the band settings are the Ableton preset's
from memory), CPU on the real chip, the Compressor page showing Depth / Time (test_master.py covers the page list).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
STORE, ARR = 0x24020088 + 0x8C90, 0x24070000
OBJ, VT, BUFS, L, R, NEXT, NVT = 0x24060000, 0x24061000, 0x24050000, 0x24064000, 0x24066000, 0x24062000, 0x24063000
N = 256
calls = []


def set_model(v):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x9C, 0, 77) + struct.pack("<HHI", 0xB4, 0, v))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 2))


e.stub(0x0804EDDC, lambda: calls.append(("stock", e.arg(0), e.arg(1))), value=1)
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 3))
e.w32(OBJ + 8, 0)
BUF = BUFS + 3 * 0x14 + 0x150E4


def block(left, right=None, chain=False):
    right = left if right is None else right
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.uc.mem_write(R, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R, 0, 1))
    calls.clear()
    e.call("comp_process", OBJ, BUFS)
    return (list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left)))),
            list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(R, 4 * len(right)))))


def sine(amp, hz=200, n=N, start=0):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def db(x):
    return 20 * math.log10(max(x, 1e-9))


def peak(x):
    return max(abs(v) for v in x)


def settle(model, amp, blocks=40, hz=200):
    set_model(model)
    e.uc.mem_write(0x38800400, b"\0" * 8)       # fresh state
    out = []
    for b in range(blocks):
        l, _ = block(sine(amp, hz, start=b * N))
        out += l
    return peak(out[-N * 8:])


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def setup(depth=1000, time=500, thresh=0, model=7):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xB4, 0, model) + struct.pack("<HHi", 0x1D0, 0, thresh) + struct.pack("<HHI", 0x1EA, 0, depth) + struct.pack("<HHI", 0x1EB, 0, time))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 4))
    e.uc.mem_write(0x38800400, b"\0" * 8)


def run(amp, hz, blocks=240, amp_r=None):
    out_l, out_r = [], []
    for b in range(blocks):
        l, r = block(sine(amp, hz, start=b * N), None if amp_r is None else sine(amp_r, hz, start=b * N))
        out_l += l
        out_r += r
    return out_l, out_r


def rms_db(x):
    return 10 * math.log10(max(sum(v * v for v in x) / len(x), 1e-18))


nums = []
e.stub(0x0808C0D8, lambda: None)
e.w32(STACK, 0)
e.w32(STACK + 4, 1000)
e.w32(STACK + 8, 0x080CC3F4)
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.arg(2), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.call("comp_register", 0x24001000, 0xB4, 4, 0x080CC3E8)
check("Depth (0x1ea) and Time (0x1eb) registered as 0..100 % knobs", nums[1:3] == [(0x1EA, 8, "Depth:", 0, 1000, "smashdepth"), (0x1EB, 8, "Time:", 0, 1000, "smashtime")], nums[:3])
check("the global settings store is allocated with 96 entries (stock 64; stock + ours had reached 50)", e.uc.mem_read(0x08094820, 2) == bytes.fromhex("6021"))

setup(depth=0)
x_rms = rms_db(sine(0.25, 1000, 48 * N)[-8 * N:])
l, _ = run(0.25, 1000, 48)
check(f"Depth 0: the level is untouched ({rms_db(l[-8 * N:]) - x_rms:+.2f} dB), stock compressor not called", abs(rms_db(l[-8 * N:]) - x_rms) < 0.3 and not calls, calls)

for hz, name in ((50, "low"), (1000, "mid"), (8000, "high")):
    setup()
    loud, _ = run(0.5, hz)
    setup()
    quiet, _ = run(0.005, hz)
    gap = rms_db(loud[-8 * N:]) - rms_db(quiet[-8 * N:])
    # (the mid tone also leaks into the high band 32 dB down, where it gets lifted: that adds ~2.5 dB to the loud one)
    check(f"{name} band at full Depth: a 40 dB difference in ({hz} Hz at -6 and -46 dBFS) comes out {gap:.1f} dB apart", 0 <= gap < 18, gap)
setup()
quiet, _ = run(0.005, 1000)
check(f"quiet material is lifted ({rms_db(quiet[-8 * N:]) - rms_db(sine(0.005, 1000, 8 * N)):+.1f} dB)", rms_db(quiet[-8 * N:]) - rms_db(sine(0.005, 1000, 8 * N)) > 12)
setup(depth=500)
half, _ = run(0.005, 1000)
check(f"Depth 50 %: about half the lift in dB ({rms_db(half[-8 * N:]) - rms_db(sine(0.005, 1000, 8 * N)):+.1f} dB)", 0.35 < (rms_db(half[-8 * N:]) - rms_db(sine(0.005, 1000, 8 * N))) / (rms_db(quiet[-8 * N:]) - rms_db(sine(0.005, 1000, 8 * N))) < 0.65)

setup()
worst = 0.0
for b in range(40):
    sig = [(0.95 if (i + b * N) % 9600 < 2400 else 0.02) * math.sin((i + b * N) * 2 * math.pi * 60 / 48000) + 0.2 * math.sin((i + b * N) * 0.9) for i in range(N)]
    l, r = block(sig)
    worst = max(worst, peak(l), peak(r))
check(f"hot kicks after quiet gaps never exceed the -0.3 dBFS ceiling (worst {db(worst):.2f} dBFS)", worst <= 0.9662, worst)

setup(thresh=0)
a, _ = run(0.02, 1000)
setup(thresh=-12000)
b_, _ = run(0.02, 1000)
check(f"Comp Thresh -12 dB = 12 dB more push into the bands; the squash absorbs part of it ({rms_db(b_[-8 * N:]) - rms_db(a[-8 * N:]):+.1f} dB out)", 0 < rms_db(b_[-8 * N:]) - rms_db(a[-8 * N:]) < 9)


def recover(time):
    setup(time=time)
    run(0.5, 1000, 60)
    g0 = struct.unpack("<f", e.uc.mem_read(0x38800400 + 4 + 144 + 12 + 4, 4))[0]
    for k in range(400):
        block([0.0] * N)
        if struct.unpack("<f", e.uc.mem_read(0x38800400 + 4 + 144 + 12 + 4, 4))[0] > g0 / 2:
            return (k + 1) * N / 48
    return 9999


fast, mid, slow = recover(0), recover(500), recover(1000)
check(f"Time: the mid band lets go in {fast:.0f} / {mid:.0f} / {slow:.0f} ms at 0 / 50 / 100 %", fast < mid / 2.5 and slow > mid * 2.5 and 120 < mid < 300, (fast, mid, slow))

setup()
l, r = run(0.5, 1000, 30, amp_r=0.0)
check("stereo-linked: a loud left channel leaves the silent right silent", peak(r[-N:]) < 1e-6 and peak(l[-N:]) > 0.05)
setup()
nan = False
for b in range(20):
    l, _ = block([0.0] * N)
    nan |= any(v != v for v in l)
check("silence in: silence out, no NaN", not nan and peak(l) == 0.0)
setup(model=2)
block(sine(0.5))
check("Smash -> Glue: the block is re-started as a model's", e.r32(0x38800400) == 0x434F4D31 and e.r32(0x38800404) == 2)
setup(model=7)
e.w32(0x38800400, 0x434F4D31)
block(sine(0.5))
check("Glue -> Smash: re-started as Smash's", e.r32(0x38800400) == 0x534D5331)
e.w32(OBJ + 8, NEXT)
e.w32(NEXT, NVT)
e.w32(NVT + 0xC, 0x24068001)
e.uc.mem_write(0x24068000, bytes.fromhex("0120 7047"))
got = []
e.stubs[0x24068000] = lambda: (got.append((e.arg(0), e.arg(1))), e.ret(1))
block(sine(0.5))
check("the next stage of the output chain still gets the buffers", got == [(NEXT, BUFS)], got)

e.w32(OBJ + 8, 0)
setup()
run(0.3, 1000, 4)
from unicorn import UC_HOOK_CODE
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: cnt.__setitem__(0, cnt[0] + 1))
block(sine(0.3, 1000))
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions per 256-frame block, {cnt[0] / N:.0f} per frame")
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
