"""Relapse, a memory echo in the delay slot (Type: Relapse), under Unicorn. Harness copied from test_munchi.py.

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
           "size": 0x1E3, "recall": 0x1E4, "reach": 0x1E9, "twist": 0x1E6, "tone": 0x1E7, "feed": 0x1E8}
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
    """Leave Relapse and come back: the slot clears its memory on a type change."""
    change(type=0)
    change(started=False, type=3, **kv)
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
ids = [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6, 0x1E3, 0x1E4, 0x1E9, 0x1E6, 0x1E7, 0x1E8]


def page(type_):
    e.uc.mem_write(ARR + 0x200, b"".join(struct.pack("<HHI", i, 0, type_ if i == 0x197 else 7) for i in ids))
    e.w32(STORE2 + 4, ARR + 0x200)
    e.uc.mem_write(STORE2 + 10, struct.pack("<H", len(ids)))
    LIST = 0x30007000
    e.w32(LIST, 0)
    e.call("munchi_list", LIST, STORE2)
    return [e.r16(LIST + 4 + 12 * i) for i in range(e.r32(LIST))]


check("Type Relapse page: Type, Feedback, Size, Recall, Reach, Twist, Tone, Feed = 8 slots", page(3) == [0x197, 0x38, 0x1E3, 0x1E4, 0x1E9, 0x1E6, 0x1E7, 0x1E8], [hex(i) for i in page(3)])
check("Type Delay page: no Relapse controls", not any(i >= 0x1E3 for i in page(0)) and len(page(0)) == 9)
ENGINE = any("granularDelay" in k for k in e.sym)      # False in a MUNCHI_OFF build (build.sh): Type 1 is "---" = stock delay
MUNCHI_PAGE = [0x197, 0x38, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6] if ENGINE else [0x197, 0x32, 0x33, 0x38, 0x34]   # Motion = the stock delay's controls, less the four the screen cannot fit;
# the motion's own three come from the fill, which this harness's store does not carry (test_motion.py has the real page)
check("the second Type's page (Munchi, or Motion): no Relapse controls", page(1) == MUNCHI_PAGE, [hex(i) for i in page(1)])

store(type=0, fb=500, size=5, recall=0, reach=500, twist=0, tone=0, feed=0)
block([(0.0, 0.0)] * N)
check("Type Delay: the stock delay runs", calls == ["stock"], calls)
n, seen = change(started=False, type=3)
check(f"switching to Relapse: stock not called, the three lines cleared ({n} blocks)", cleared(n, seen), (n, seen[:4]))
block([(0.0, 0.0)] * N)
check("...it starts, and is not cleared again", calls == [] and not clearing(), calls)

# --- a plain echo at Recall 0
l, r = impulse(2.2)
pk = peaks(l)
check(f"Recall 0, Size 1/4 at 120 BPM: repeats at {[round(p[0] / 48) for p in pk[:3]]} ms", len(pk) >= 3 and all(abs(p[0] - 24000 * (k + 1)) < 4 for k, p in enumerate(pk[:3])), pk)
check(f"Feedback 50 %: each repeat lower ({pk[0][1]:.2f}, {pk[1][1]:.2f}, {pk[2][1]:.2f}), level x wet", pk[0][1] > pk[1][1] > pk[2][1] and abs(pk[0][1] - 0.4) < 0.03 and abs(pk[1][1] / pk[0][1] - 0.475) < 0.05, pk)
check("left = right for a centred input", l == r)

fresh(size=3, recall=0, fb=500)
l, r = impulse(1.0)
pk = peaks(l)
check(f"Size 1/8: first repeat at {pk[0][0] / 48:.0f} ms", abs(pk[0][0] - 12000) < 4, pk[:2])
bpm(90.0)
fresh(size=5, recall=0)
l, r = impulse(1.5)
pk = peaks(l)
check(f"follows tempo: 1/4 at 90 BPM = {pk[0][0] / 48:.0f} ms", abs(pk[0][0] - 32000) < 4, pk[:2])
bpm(30.0)
fresh(size=8, recall=0)
l, r = impulse(5.0)
pk = peaks(l)
check(f"1 Bar at 30 BPM (8 s) is held to the 4 s the memory allows: repeat at {pk[0][0] / 48000:.2f} s", pk and 3.8 * fs < pk[0][0] < 4.0 * fs, pk[:1])
bpm(120.0)

# --- the echo time changing under sound: no click bigger than the signal
t0 = fresh(size=5, recall=0, fb=600)
swell = lambda t: (0.5 * min(1.0, (t - t0) / 9600) * math.sin(2 * math.pi * 220 * t / fs),) * 2
run(1.0, swell)
store(size=3)
l, r = run(0.5, swell)
step = max(abs(l[i] - l[i - 1]) for i in range(1, len(l)))
check(f"Size changed while sounding: cross-faded (largest sample step {step:.3f})", step < 0.03, step)

# --- Recall: snippets from earlier in the memory
def tail_periods(l, floor=0.05):
    """Which echo periods of the tail have sound in them."""
    return [max(abs(v) for v in l[m * D:(m + 1) * D]) > floor for m in range(len(l) // D)]


fresh(size=5, recall=1000, reach=1000, fb=0)
run(4.0, tone(500))
l, r = run(4.0)                              # input stops: with Feedback 0 only snippets can sound
on = tail_periods(l)
check(f"Recall 100 %, Feedback 0, input stopped: snippets of the old sound keep coming back ({sum(on[2:])} of the next {len(on) - 2} periods)", sum(on[2:]) >= 2, on)
fresh(size=5, recall=0, reach=1000, fb=0)
run(4.0, tone(500))
l, r = run(4.0)
check("Recall 0: nothing comes back after the one echo", max(map(abs, l[30000:])) < 1e-3, max(map(abs, l[30000:])))
fresh(size=5, recall=500, reach=1000, fb=0)
run(2.0, tone(500))
l, r = run(8.0, tone(500))
# the echo (period-old sine) is always there; a snippet adds a second copy, so the level of a period tells them apart
lv = [math.sqrt(energy(l[m * D + 6000:m * D + 18000]) / 12000) for m in range(len(l) // D)]
check(f"Recall 50 %: about half the periods carry a snippet ({sum(1 for v in lv if abs(v - min(lv)) > 0.02)} of {len(lv)})", 4 <= sum(1 for v in lv if abs(v - min(lv)) > 0.02) <= 12, [round(v, 2) for v in lv])

fresh(size=5, recall=1000, reach=0, fb=0)
run(5.0, tone(500))
l, r = run(3.0)
last = max((i for i, v in enumerate(l) if abs(v) > 0.05), default=0)
check(f"Reach 0: snippets only reach just behind the echo, so they stop soon after the input ({last / 48000:.2f} s)", last < 1.6 * fs, last)
fresh(size=5, recall=1000, reach=1000, fb=0)
run(5.0, tone(500))
l, r = run(3.0)
last = max((i for i, v in enumerate(l) if abs(v) > 0.05), default=0)
check(f"Reach 100 %: they reach the whole memory and keep going ({last / 48000:.2f} s)", last > 2.0 * fs, last)

# --- Twist
def chirp(t):                                # rising tone, 0.25 s of every second: direction and pitch are measurable
    u = (t % fs) / fs
    return (0.6 * math.sin(2 * math.pi * (400 * u + 2400 * u * u) * 1.0),) * 2 if u < 0.25 else (0.0, 0.0)


def zero_rate(x, i, n=1200):
    seg = x[i:i + n]
    return sum(1 for a, b in zip(seg, seg[1:]) if a < 0 <= b) * fs / n


def snippet_pitch(modify):
    fresh(size=5, recall=1000, reach=1000, fb=0, twist=modify)
    run(4.0, lambda t: (0.6 * math.sin(2 * math.pi * 500 * t / fs),) * 2)
    l, r = run(2.0)
    seg = [i for i in range(0, len(l) - 2400, 600) if min(abs(v) for v in l[i:i + 2400:7]) < 1 and max(abs(v) for v in l[i:i + 2400]) > 0.2]
    rates = sorted(zero_rate(l, i, 2400) for i in seg)
    return rates[len(rates) // 2] if rates else 0, l, r


f0, l, r = snippet_pitch(0)
check(f"Twist Off: snippets at the original pitch ({f0:.0f} Hz of 500)", abs(f0 - 500) < 30, f0)
f1, l, r = snippet_pitch(2)
check(f"Twist Oct Dn: an octave down ({f1:.0f} Hz)", abs(f1 - 250) < 30, f1)
f2, l, r = snippet_pitch(3)
check(f"Twist Oct Up: an octave up ({f2:.0f} Hz)", abs(f2 - 1000) < 60, f2)

t0 = fresh(size=5, recall=1000, reach=1000, fb=0, twist=1)


def rise(t):                                 # every echo period: a tone rising 300 -> 1500 Hz across the period
    u = ((t - t0) % D) / D
    return (0.6 * math.sin(2 * math.pi * (300 * u + 600 * u * u) * D / fs),) * 2


run(4.0, rise)
l, r = run(3.0)
segs = [l[m * D:(m + 1) * D] for m in range(2, len(l) // D) if max(abs(v) for v in l[m * D:(m + 1) * D]) > 0.1]
falling = [zero_rate(sg, 2400, 2400) > zero_rate(sg, 19200, 2400) + 300 for sg in segs]
check(f"Twist Reverse: the rising tone comes back falling ({sum(falling)} of {len(falling)} snippets)", len(falling) >= 2 and all(falling), falling)
t0 = fresh(size=5, recall=1000, reach=1000, fb=0, twist=0)
run(4.0, rise)
l, r = run(3.0)
segs = [l[m * D:(m + 1) * D] for m in range(2, len(l) // D) if max(abs(v) for v in l[m * D:(m + 1) * D]) > 0.1]
rising = [zero_rate(sg, 2400, 2400) + 300 < zero_rate(sg, 19200, 2400) for sg in segs]
check(f"Twist Off: it comes back rising ({sum(rising)} of {len(rising)})", len(rising) >= 2 and all(rising), rising)

t0 = fresh(size=5, recall=1000, reach=1000, fb=0, twist=4)
blip = lambda t: (0.6 * math.sin(2 * math.pi * 1000 * t / fs),) * 2 if 2400 <= (t - t0) % D < 3360 else (0.0, 0.0)
run(4.0, blip)
l, r = run(3.0)
seg = next(l[m * D:(m + 1) * D] for m in range(2, len(l) // D) if max(abs(v) for v in l[m * D:(m + 1) * D]) > 0.1)
ev = peaks(seg, floor=0.05, gap=3000)
gaps = [b[0] - a[0] for a, b in zip(ev, ev[1:])]
check(f"Twist Stutter: the snippet's first quarter plays four times ({len(ev)} blips, {[round(g / 48) for g in gaps]} ms apart = 1/16)", len(ev) == 4 and all(abs(g - 6000) < 200 for g in gaps), ev)

# --- Tone, Feed, stability
fresh(size=3, recall=0, fb=900, tone=0)
bright, _ = run(3.0, lambda t: ((((t * 7919) % 2001) - 1000) / 2000.0,) * 2 if t < run.t + 2400 else (0.0, 0.0))
fresh(size=3, recall=0, fb=900, tone=1000)
dark, _ = run(3.0, lambda t: ((((t * 7919) % 2001) - 1000) / 2000.0,) * 2 if t < run.t + 2400 else (0.0, 0.0))
hf = lambda x: sum((b - a) ** 2 for a, b in zip(x[96000:], x[96001:]))
check(f"Tone 100 %: late repeats much darker than at 0 (high-frequency energy x{hf(dark) / max(hf(bright), 1e-12):.4f})", hf(dark) < 0.05 * hf(bright))

noise = lambda t: ((((t * 7919) % 2001) - 1000) / 1000.0, (((t * 104729) % 2001) - 1000) / 1000.0)
fresh(size=1, recall=1000, reach=1000, fb=1000, feed=1, twist=3, tone=0)
l, r = run(6.0, noise)
check(f"everything maxed with Feed on, full-scale noise in for 6 s: finite and bounded (peak {max(map(abs, l + r)):.2f} at level 0.5)", all(math.isfinite(v) for v in l + r) and max(map(abs, l + r)) < 2.0)
l, r = run(9.0)                              # past one full wrap of the 8 s memory
check("...and it keeps running past the memory wrap", all(math.isfinite(v) for v in l + r))
fresh(size=5, recall=1000, reach=1000, fb=500, feed=0)
run(3.0, burst)
a, _ = run(8.0)
fresh(size=5, recall=1000, reach=1000, fb=500, feed=1)
run(3.0, burst)
b, _ = run(8.0)
check(f"Feed On keeps the memory alive longer than Off (energy in seconds 5-8: {energy(b[5 * fs:]):.2f} vs {energy(a[5 * fs:]):.2f})", energy(b[5 * fs:]) > 1.5 * energy(a[5 * fs:]) + 1e-6)

from unicorn import UC_HOOK_CODE
cnt = [0]
hk = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
block([noise(i) for i in range(N)])
e.uc.hook_del(hk)
print(f"     cost: {cnt[0]} instructions per 128-frame block, {cnt[0] / N:.0f} per frame")

n, seen = change(started=False, type=1)
block([(0.0, 0.0)] * N)
if ENGINE:
    check(f"Relapse -> Munchi: lines cleared ({n} blocks), Munchi starts", cleared(n, seen) and "stock" not in calls and not clearing(), (n, seen[:4], calls))
    n, seen = change(started=False, type=0)
    block([(0.0, 0.0)] * N)
    check(f"-> Delay: lines cleared ({n} blocks), stock runs", cleared(n, seen) and calls == ["stock"], (n, seen[:4], calls))
else:
    check(f"Relapse -> the second Type (engine left out): lines cleared ({n} blocks), stock runs", cleared(n, seen) and calls == ["stock"], (n, seen[:4], calls))
    store(type=0)
    block([(0.0, 0.0)] * N)
    check("-> Delay: nothing to clear, stock runs", calls == ["stock"], calls)

# --- a MODE left over from an older build's numbering must force a clear, not alias onto another type
# 3.2.m renumbered the list, and MODE lives in backup SRAM which survives a reflash. A raw 3 stored by 3.2.l
# meant Confetti; under the new numbering 3 is Relapse, so `fresh` came out false, the lines were never cleared,
# and Relapse read Confetti's state. That crashed the test unit while scrolling the delay types (2026-10-11).
MODE_RAW = 0x38800B14
e.w32(MODE_RAW, 3)                        # a bare type number, as every build before the epoch wrote it
store(type=3, fb=500, size=5, recall=0, reach=500, twist=0, tone=0, feed=0)
calls.clear()
n, seen = change(type=3)
check(f"a MODE from the old numbering is treated as unknown, so the lines are cleared instead of reused ({n - 1} blocks)",
      cleared(n - 1, seen), f"{n} blocks, calls={seen[:4]}")
check("...and the epoch is stamped in, so the next block sees it as current",
      (e.r32(MODE_RAW) >> 16) == 0x4D32, hex(e.r32(MODE_RAW)))
calls.clear()
block([(0.0, 0.0)] * N)
check("...with no further clearing once it matches", len([c for c in calls if c[0] == "clear"]) == 0 and not clearing(), calls)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
