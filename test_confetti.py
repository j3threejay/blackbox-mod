"""Confetti (granular micro-looper, src/confetti.c) in the delay slot (Type: Confetti), under Unicorn. Harness copied from
test_relapse.py / test_munchi.py. How it sounds was tuned on the Mac build (host/dsp.py), not here.

Original header of that harness follows.
Munchi Delay in the delay slot, under Unicorn.

Real firmware runs for: settings lookup, the list helpers (fill / remove), buffer pointer / length helpers and the
output mix (FUN_08061844). Stubbed: the stock delay process, its line clear, the send gate, the bus lookup, the
param registrars and store add.
NOT checked: how it sounds, the settings page redrawing when Type changes, CPU on the real chip (counted here as
instructions), and anything else in the firmware touching the delay's lines while Munchi owns them.
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x50003000, 0x1000)                       # WWDG1: audio_watch re-arms the early wakeup each block
e.uc.mem_map(0xC0000000, 0x400000)                     # SDRAM: the delay's lines
e.uc.mem_map(0x30000000, 0x10000)                      # fake objects
OBJ, VT, BUFS, CTX, BUS, IN = 0x30000000, 0x30001000, 0x30001100, 0x30001200, 0x30001300, 0x30001400
BUSL, BUSR, INL, INR, ARR, STORE2, VT2 = 0x30002000, 0x30002400, 0x30002800, 0x30002C00, 0x30003000, 0x30003400, 0x30003500
LIVE, STATE, FRZ = 0xC0000000, 0xC0100000, 0xC0200000
APPFX = 0x24020088 + 0x2FC0
N = 128
fs = 48000

e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.w32(OBJ + 0x18, 3 << 16 | 0 << 8)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 2))
e.uc.mem_write(OBJ + 0x2C, struct.pack("<f", 0.5))
e.uc.mem_write(OBJ + 0x21F, b"\x01")
for off, ptr, floats in ((0x30, LIVE, 192256), (0x4C, STATE, 96256), (0x68, FRZ, 192256)):
    e.w32(OBJ + off, ptr)
    e.w32(OBJ + off + 0x14, floats)
e.w32(BUFS, CTX)


def bpm(v):
    e.uc.mem_write(CTX + 0x18, struct.pack("<f", v))


bpm(120.0)


def buf(addr, l, r):
    e.w32(addr, N)
    e.w32(addr + 4, N)
    e.w32(addr + 8, l)
    e.w32(addr + 12, r)
    e.uc.mem_write(addr + 0x10, b"\x00\x01")


buf(BUS, BUSL, BUSR)
buf(IN, INL, INR)
calls = []
e.stub(0x080548C8, lambda: calls.append("stock"), value=1)
e.stub(0x0806AAC0, lambda: calls.append(("clear", e.arg(0) - OBJ)))
e.stub(0x0804F0D4)
e.stub(0x0804F270, lambda: e.w32(e.arg(2), IN))
e.stub(0x0805F37C, value=BUS)

params = {}


def store(**kv):
    params.update(kv)
    ids = {"type": 0x197, "fb": 0x38, "wand": 0x1D1, "random": 0x1D2, "freeze": 0x1D3, "clock": 0x1D4, "width": 0x1D5, "duck": 0x1D6,
           "size": 0x1E3, "scan": 0x1E4, "spread": 0x1E9, "modify": 0x1E6, "tone": 0x1E7, "feed": 0x1E8,
           "mode": 0x1EC, "density": 0x1ED, "contour": 0x1EE, "space": 0x1EF}
    data = b"".join(struct.pack("<HHI", ids[k], 0, v) for k, v in params.items())
    e.uc.mem_write(ARR, data)
    e.w32(APPFX + 4, ARR)
    e.uc.mem_write(APPFX + 10, struct.pack("<H", len(params)))


def block(x):
    e.uc.mem_write(INL, struct.pack(f"<{N}f", *[v[0] for v in x]))
    e.uc.mem_write(INR, struct.pack(f"<{N}f", *[v[1] for v in x]))
    e.uc.mem_write(BUSL, bytes(4 * N))
    e.uc.mem_write(BUSR, bytes(4 * N))
    calls.clear()
    e.call("munchi_process", OBJ, BUFS, count=50_000_000)
    return (struct.unpack(f"<{N}f", e.uc.mem_read(BUSL, 4 * N)), struct.unpack(f"<{N}f", e.uc.mem_read(BUSR, 4 * N)))


def run(seconds, src=lambda t: (0.0, 0.0)):
    out_l, out_r = [], []
    t0 = run.t
    for b in range(int(seconds * fs / N)):
        l, r = block([src(t0 + b * N + i) for i in range(N)])
        out_l += l
        out_r += r
    run.t += int(seconds * fs / N) * N
    return out_l, out_r


run.t = 0
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# 3.3.y: a Type change clears the slot's three lines over several silent blocks (MODE = "MC" | chunks << 8 | type),
# and the type starts, fresh, in the block after the last chunk. Stock's one-shot clear (stubbed above) is not called.
MODE = 0x38800B14


def clearing(done_too=True):
    m = e.r32(MODE) & 0xFFFFFFFF
    return m >> 16 == 0x4D43 and (done_too or (m >> 8) & 0xFF != 0xFF)


def change(started=True, **kv):
    """store(**kv), then the blocks of the clear (and with started=True the type's first block). (blocks, their calls)"""
    store(**kv)
    seen, n = [], 0
    while n < 64:
        block([(0.0, 0.0)] * N)
        seen += calls
        n += 1
        if not clearing() or (not started and not clearing(done_too=False)):
            break
    return n, seen


def cleared(n, seen):
    return n >= 10 and "stock" not in seen and not [c for c in seen if c[0] == "clear"]


def fresh(**kv):
    """Leave Confetti and come back: the slot clears its memory on a type change."""
    change(type=0)
    change(started=False, type=4, **kv)
    return run.t


def energy(x):
    return sum(v * v for v in x)


D = 24000                                    # a quarter note at 120 BPM: the echo period most tests use


def tone(hz, amp=0.6):
    return lambda t: (amp * math.sin(2 * math.pi * hz * t / fs),) * 2


def impulse(seconds, amp=0.8):
    return run(seconds, lambda t: (amp, amp) if t == run.t else (0.0, 0.0))


def peaks(x, floor=0.02, gap=2000):
    out, i = [], 0
    while i < len(x):
        if abs(x[i]) > floor:
            j = max(range(i, min(i + gap, len(x))), key=lambda k: abs(x[k]))
            out.append((j, abs(x[j])))
            i = j + gap
        else:
            i += 1
    return out


def burst(t):                                # 50 ms of 1 kHz at the start of every second: a recognisable event
    return (0.6 * math.sin(2 * math.pi * 1000 * t / fs),) * 2 if t % fs < 2400 else (0.0, 0.0)


# --- page list and switching
e.w32(STORE2, VT2)
e.w32(VT2, 0x30006001)
e.uc.mem_write(0x30006000, b"\x26\x20\x70\x47")          # movs r0,#0x26 ; bx lr: a delay cell
ids = [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6, 0x1E3, 0x1E4, 0x1E9, 0x1E6, 0x1E7, 0x1E8,
       0x1EC, 0x1ED, 0x1EE, 0x1EF]


def page(type_):
    e.uc.mem_write(ARR + 0x200, b"".join(struct.pack("<HHI", i, 0, type_ if i == 0x197 else 7) for i in ids))
    e.w32(STORE2 + 4, ARR + 0x200)
    e.uc.mem_write(STORE2 + 10, struct.pack("<H", len(ids)))
    LIST = 0x30007000
    e.w32(LIST, 0)
    e.call("munchi_list", LIST, STORE2)
    return [e.r16(LIST + 4 + 12 * i) for i in range(e.r32(LIST))]


CONFETTI = [0x1EC, 0x1ED, 0x1EE, 0x1EF]
check("Type Confetti page: Type, Mode, Size, Activity | Shape, Feedback, Tone, Space", page(4) == [0x197, 0x1EC, 0x1E3, 0x1ED, 0x1EE, 0x38, 0x1E7, 0x1EF], [hex(i) for i in page(4)])
ENGINE = any("granularDelay" in k for k in e.sym)      # False in a MUNCHI_OFF build (build.sh): Type 1 is "---" = stock delay
MUNCHI_PAGE = [0x197, 0x38, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6] if ENGINE else [0x197, 0x32, 0x33, 0x38, 0x34]   # Motion = the stock delay's controls, less the four the screen cannot fit;
# the motion's own three come from the fill, which this harness's store does not carry (test_motion.py has the real page)
check("Delay / Munchi / Motion / Relapse pages: no Confetti controls, same as before", not any(i in CONFETTI for t in (0, 1, 2) for i in page(t)) and len(page(0)) == 9 and
      page(1) == MUNCHI_PAGE and page(3) == [0x197, 0x38, 0x1E3, 0x1E4, 0x1E9, 0x1E6, 0x1E7, 0x1E8], [page(t) for t in (0, 1, 2, 3)])

store(type=0, fb=0, size=5, tone=0, mode=5, density=0, contour=500, space=0)
block([(0.0, 0.0)] * N)
check("Type Delay: the stock delay runs", calls == ["stock"], calls)
n, seen = change(started=False, type=4)
check(f"switching to Confetti: stock not called, the three lines cleared ({n} blocks)", cleared(n, seen), (n, seen[:4]))
l, r = block([(0.0, 0.0)] * N)
check("...it starts after that, and silence in gives silence out", calls == [] and not clearing() and max(map(abs, l + r)) == 0.0, calls)


def peak(x):
    return max(abs(v) for v in x) if x else 0.0


def rms(x):
    return math.sqrt(energy(x) / max(len(x), 1))


# --- Taps, one tap, Size 1/4 at 120 BPM: the plainest case, a repeat one step later
fresh(fb=0, size=5, tone=0, mode=5, density=0, contour=500, space=0)
t0 = run.t
l, r = run(1.5, lambda t: (0.6 * math.sin(2 * math.pi * 1000 * (t - t0) / fs),) * 2 if t - t0 < 2400 else (0.0, 0.0))
first = next(i for i, v in enumerate(r) if abs(v) > 0.01)
check(f"Taps, 1 tap, 1/4 at 120 BPM: a 50 ms burst comes back one step ({first / 48:.0f} ms) later, nothing before", abs(first - D) < 600, first)
check(f"...the first tap sits to one side (L {peak(l[D:D + 3000]):.3f}, R {peak(r[D:D + 3000]):.3f}), with the send level (0.5) applied", peak(l[D:D + 3000]) > 1.5 * peak(r[D:D + 3000]) or peak(r[D:D + 3000]) > 1.5 * peak(l[D:D + 3000]))
check(f"...Feedback 0: one repeat only (after 1.2 s: {peak(l[57600:] + r[57600:]):.4f})", peak(l[57600:] + r[57600:]) < 0.003)
fresh(density=1000)
t0 = run.t
l, r = run(4.5, lambda t: (0.6 * math.sin(2 * math.pi * 1000 * (t - t0) / fs),) * 2 if t - t0 < 2400 else (0.0, 0.0))
hits = [k for k in range(1, 9) if peak(l[k * D:k * D + 3000] + r[k * D:k * D + 3000]) > 0.02]
check(f"Taps, Activity 100 %: five taps, at steps {hits}", hits == [1, 2, 3, 5, 8], hits)

# --- every mode makes sound from a busy input, stays finite and under its ceiling
def busy(t):
    k = t % 12000
    return ((0.5 * math.sin(2 * math.pi * (110 + 55 * ((t // 12000) % 4)) * t / fs) * math.exp(-k / 3000.0)),) * 2


levels = []
for mode, name in enumerate(("Loops", "Cloud", "Slide", "Stutter", "Arp", "Taps")):
    fresh(fb=400, size=3, tone=300, mode=mode, density=700, contour=500, space=300)
    l, r = run(3.0, busy)
    ok = all(v == v for v in l + r) and 0.003 < rms(l[fs:] + r[fs:]) and peak(l + r) <= 0.5 * 1.26
    levels.append(rms(l[fs:] + r[fs:]))
    check(f"{name}: plays (rms {rms(l[fs:] + r[fs:]):.3f}, peak {peak(l + r):.3f}), finite", ok, (rms(l[fs:] + r[fs:]), peak(l + r)))
check(f"the six modes sit within 10 dB of each other at the same settings ({20 * math.log10(max(levels) / min(levels)):.1f} dB)", max(levels) / min(levels) < 3.2)

# --- everything at maximum cannot run away
fresh(fb=1000, size=0, tone=0, mode=5, density=1000, contour=1000, space=1000)
l, r = run(3.0, lambda t: (0.9 * math.sin(2 * math.pi * 220 * t / fs),) * 2)
l2, r2 = run(2.0)
check(f"Taps, every knob at 100 %, a full-scale send: bounded (peak {peak(l + r + l2 + r2):.3f} <= ceiling 1.25 x send level 0.5)", peak(l + r + l2 + r2) <= 0.5 * 1.26 and all(v == v for v in l2))
fresh(fb=1000, size=8, tone=0, mode=3, density=1000, contour=1000, space=1000)
l, r = run(2.0, lambda t: (0.9 * math.sin(2 * math.pi * 220 * t / fs),) * 2)
check(f"Stutter, the same: bounded (peak {peak(l + r):.3f})", peak(l + r) <= 0.5 * 1.26 and all(v == v for v in l))

# --- an out-of-range saved value is harmless
fresh(fb=400, size=77, tone=300, mode=99, density=5000, contour=5000, space=5000)
l, r = run(0.5, busy)
check("out-of-range settings (mode 99, size 77, 500 %): no crash, finite", all(v == v for v in l + r))

# --- 3.3.y IDLE BYPASS: once the send and the output have been under -90 dBFS for longer than the memory (+1 s), the
# block is skipped. Measured here: when it goes idle, that the whole memory is under -90 dB by then, what an idle
# block costs, and that the first block with a send runs again.
from unicorn import UC_HOOK_CODE as _HOOK
hits = [0]
_rev = e.sym["rev4_step"] & ~1                       # called every frame while Confetti runs with Space up
e.uc.hook_add(_HOOK, lambda *_: hits.__setitem__(0, hits[0] + 1), begin=_rev, end=_rev)
QUIET = 10 ** (-90 / 20)
fresh(fb=0, size=5, tone=300, mode=1, density=800, contour=500, space=600)   # Cloud, Space up
run(1.0, tone(330))
t_loud, idle_at, blocks = None, None, 0
while blocks < int(25 * fs / N):
    hits[0] = 0
    l, r = block([(0.0, 0.0)] * N)
    blocks += 1
    if max(map(abs, l + r)) >= QUIET:
        t_loud = blocks
    if hits[0] == 0:
        idle_at = blocks
        break
mem_frames = 192256 * 2
check(f"Confetti goes idle after the send stops ({idle_at and idle_at * N / fs:.1f} s of silence in)", idle_at is not None, blocks)
if idle_at:
    quiet_s = (idle_at - (t_loud or 0)) * N / fs
    check(f"...only after the output has been under -90 dB for the memory's length + 1 s ({quiet_s:.2f} s >= 9.0 s)",
          (idle_at - (t_loud or 0)) * N >= mem_frames + 48000 - N, (idle_at, t_loud))
    peak16 = 0
    for base in (LIVE, FRZ):
        raw = bytes(e.uc.mem_read(base, 192256 * 4))
        peak16 = max(peak16, max(abs(v) for v in struct.unpack(f"<{192256 * 2}h", raw)))
    check(f"...by which time every sample in the memory is under -90 dB too (peak {peak16} of 32767)", peak16 <= 2, peak16)
    l, r = block([(0.0, 0.0)] * N)
    check("an idle block gives exact silence", max(map(abs, l + r)) == 0.0)
    cnt = [0]
    hk = e.uc.hook_add(_HOOK, lambda *_: cnt.__setitem__(0, cnt[0] + 1))
    block([(0.0, 0.0)] * N)
    e.uc.hook_del(hk)
    idle_cost = cnt[0]
    cnt[0] = 0
    hk = e.uc.hook_add(_HOOK, lambda *_: cnt.__setitem__(0, cnt[0] + 1))
    hits[0] = 0
    block([(0.3 * math.sin(i / 7), 0.3 * math.sin(i / 7)) for i in range(N)])
    e.uc.hook_del(hk)
    print(f"     idle block: {idle_cost} instructions (the whole slot, incl. FX OUT); with a send: {cnt[0]}")
    check(f"an idle block costs a small fraction of a running one ({idle_cost} vs {cnt[0]} instructions)",
          idle_cost * 10 < cnt[0], (idle_cost, cnt[0]))
    check("the first block with a send runs Confetti again", hits[0] == N, hits[0])
    l, r = run(1.5, tone(330))
    check("...and the pieces come back", energy(l[fs // 2:]) > 1.0, energy(l[fs // 2:]))

# --- leaving
n, seen = change(started=False, type=0)
block([(0.0, 0.0)] * N)
check(f"Confetti -> Delay: lines cleared ({n} blocks), then the stock delay runs", cleared(n, seen) and calls == ["stock"], (n, seen[:4], calls))
change(type=3, scan=0, spread=500, modify=0, feed=0)
n, seen = change(type=4, mode=0)
check(f"Relapse -> Confetti: lines cleared ({n - 1} blocks), Confetti starts clean", cleared(n - 1, seen) and e.r32(STATE) == 0x434E4632, (n, seen[:4], hex(e.r32(STATE))))

# --- cost
from unicorn import UC_HOOK_CODE
fresh(fb=600, size=1, tone=300, mode=0, density=1000, contour=500, space=500)
run(1.0, busy)
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: cnt.__setitem__(0, cnt[0] + 1))
block([busy(run.t + i) for i in range(N)])
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions per {N}-frame block, {cnt[0] / N:.0f} per frame (Loops, Activity 100 %, Space on)")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
