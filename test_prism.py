"""Prism (Master FX type 2, src/prism.c + master.c) under Unicorn, on test_master.py's harness.

Real firmware runs for the settings lookup and the output-buffer helpers. Stubbed: the registrars, the store add, the
page list helpers, the delay's line allocator and the permanent allocator.
NOT checked: how it sounds (levels were tuned on the Mac build, host/dsp.py and host/sweep_prism.py), the page redraw
when Edit is turned, the boot-time allocation on the real allocator, CPU on the real chip.
"""
import math
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x50003000, 0x1000)                 # WWDG1, and the NVIC below: master_alloc now also runs
APP = 0x24020088
STORE, ARR = APP + 0x8C90, 0x24070000
OBJ, VT, BUFS, L, R = 0x24060000, 0x24061000, 0x24050000, 0x24064000, 0x24066000
UI, GL = 0x38800B1C, 0x38800F20
N = 256
calls = []
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def settings(**kw):
    ids = {"comp": 0xB4, "mfx": 0x1DB, "wow": 0x1DC, "flutter": 0x1DD, "sat": 0x1DE, "fail": 0x1DF, "noise": 0x1E0,
           "hicut": 0x1E1, "locut": 0x1E2, "thresh": 0x1D0, "depth": 0x1EA, "smashtime": 0x1EB,
           "edit": 0x19C, "fx0": 0x19D, "fx1": 0x19E, "fx2": 0x19F, "fx3": 0x1A0, "amt0": 0x1A1, "amt1": 0x1A2, "amt2": 0x1A3,
           "amt3": 0x1A4, "tilt": 0x1A5, "rate": 0x1A6, "time": 0x1A7, "mix": 0x1A8}
    vals = {v: 0 for v in ids.values()}
    vals.update({ids[k]: v for k, v in kw.items()})
    rows = sorted(vals.items())
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", len(rows)))


e.stub(0x0804EDDC, lambda: calls.append(("stock",)), value=1)
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 3))
e.w32(OBJ + 8, 0)
BUF = BUFS + 3 * 0x14 + 0x150E4


def block(left, right=None):
    right = left if right is None else right
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.uc.mem_write(R, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R, 0, 1))
    calls.clear()
    e.call("comp_process", OBJ, BUFS, count=20_000_000)
    return (list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left)))),
            list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(R, 4 * len(right)))))


def sine(amp, hz, start=0, n=N):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def run(blocks, hz=440, amp=0.5, right_amp=None):
    e.uc.mem_write(GL, b"\0" * 4)
    outl, outr = [], []
    for b in range(blocks):
        x = sine(amp, hz, b * N)
        l, r = block(x, None if right_amp is None else sine(right_amp, hz, b * N))
        outl += l
        outr += r
    return outl, outr


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def f32(x):
    return [struct.unpack("<f", struct.pack("<f", v))[0] for v in x]


from unicorn import UC_HOOK_CODE
PRISM, CTX = 0xC0000000, 0x24058000
PMEM, PCHECK = 0x38800F70, 0x38800F74
e.uc.mem_map(0xC0000000, 0x90000)
FX = [["Drive", "Sweet", "Fuzz", "Snarl", "Bloom"], ["Doubler", "Vibrato", "Phaser", "Tremolo", "Pitch"],
      ["PingPong", "Tape", "Hall", "Scatter", "Reverse"], ["Filter", "Clamp", "Cassette", "Glitch", "Static"]]


def peak(x):
    return max(abs(v) for v in x)


def play(blocks, src):
    outl, outr = [], []
    for b in range(blocks):
        l, r = block([src(b * N + i) for i in range(N)])
        outl += l
        outr += r
    return outl, outr


def tone(t):
    return 0.4 * math.sin(2 * math.pi * 330 * t / 48000) * (1.0 if t % 12000 < 6000 else 0.2)


# --- registration, defaults
lists, nums, added = [], [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.w32(STACK, 0)
e.w32(STACK + 4, 1000)
e.w32(STACK + 8, 0x080CC3F4)
e.call("comp_register", 0x24001000, 0xB4, 4, 0x080CC3E8)
byid = {l[0]: l for l in lists}
check("Master FX list: Off, VHS, Prism", byid[0x1DB][2] == ["Off", "VHS", "Prism"], byid[0x1DB])
check("no Edit selector any more (3.1.A's, id 0x19c)", 0x19C not in byid)
check("four effect lists (0x19d..0x1a0), five effects each", [byid[0x19D + b][1:3] for b in range(4)] == [(lab, FX[b]) for b, lab in enumerate(("Drive FX:", "Move FX:", "Space FX:", "Tex FX:"))], [byid[0x19D + b] for b in range(4)])
check("Time (0x1a7): eight note lengths", byid[0x1A7][2] == ["1/32", "1/16", "1/8T", "1/8", "1/8D", "1/4", "1/4D", "1/2"], byid[0x1A7])
pn = {n[0]: n for n in nums}
check("amounts Drive / Motion / Space / Texture (0x1a1..0x1a4) and Tilt, Rate, Mix: 0..100 % knobs",
      [pn[i][1:4] for i in (0x1A1, 0x1A2, 0x1A3, 0x1A4, 0x1A5, 0x1A6, 0x1A8)] == [(lab, 0, 1000) for lab in ("Drive:", "Motion:", "Space:", "Texture:", "Tilt:", "Rate:", "Mix:")], pn)
check("every xml name is unique", len({l[3] for l in lists} | {n[4] for n in nums}) == len(lists) + len(nums))
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("comp_defaults", 0x24072000, 0xB4, 1)
d = dict(added)
check("defaults: Sweet 30 %, Doubler 0, Tape 0, Cassette 25 %, Tilt flat, Time 1/8, Mix 100 %; 28 global entries added in all (Pre-roll, then the clipper's three)",
      [d[i] for i in range(0x19D, 0x1A9)] == [1, 0, 1, 2, 300, 0, 0, 250, 500, 300, 3, 1000] and len(added) == 28 and len(d) == 28, added)
check("stock has 41 global settings, ours add 27: 68 of the store's 96", 41 + len(added) - 1 == 68 and e.uc.mem_read(0x08094820, 2) == bytes.fromhex("6021"))

# --- the page
LIST, CELL = 0x24074000, 0x24075000
built = []
e.stub(0x080A4FC2, lambda: built.append("clear"))
e.stub(0x080A5038, lambda: built.append(e.arg(1)))
e.stub(0x08098D40, lambda: built.append("stock"), value=7)


def build():
    built.clear()
    e.uc.mem_write(CELL + 4, struct.pack("<H", 0x40))
    e.call("master_list", APP, CELL, LIST, 0)
    return list(built)


settings(mfx=2)
e.uc.mem_write(UI, bytes([1, 1]))
check("Prism page 1: each block's effect list then its amount, Drive / Motion / Space / Texture (vertical pairs on the screen)",
      build() == ["clear", 0x19D, 0x1A1, 0x19E, 0x1A2, 0x19F, 0x1A3, 0x1A0, 0x1A4], [hex(b) if b != "clear" else b for b in build()])
e.uc.mem_write(UI, bytes([2, 1]))
check("Prism page 2: Tilt, Rate, Time, Mix", build() == ["clear", 0x1A5, 0x1A6, 0x1A7, 0x1A8], build())
e.uc.mem_write(UI, bytes([1, 1]))
settings(mfx=1)
check("VHS page unchanged: Type + its seven knobs", build() == ["clear"] + list(range(0x1DB, 0x1E3)), build())

# --- memory: taken once at boot from the firmware's permanent allocator
allocs = []
e.stub(0x0806AA80, lambda: allocs.append(("line", e.arg(0), e.arg(1))))
e.stub(0x0804436C, lambda: allocs.append(("perm", e.arg(0))), value=PRISM)
e.uc.mem_write(PMEM, b"\0" * 8)
settings(mfx=2, fx0=0, amt0=1000)
x = [tone(i) for i in range(N)]
l, r = block(x)
check("no memory yet (boot hook has not run): Prism passes the signal through untouched", l == f32(x) and r == f32(x))
check("the meter is up before the boot hook runs here (the emulator starts that way)", e.r32(0x2405FFD0) == 0x43505534)
e.call("master_alloc", 0x24076000, 192000)
check("master_alloc is the once-a-boot hook: it wipes the meter's state, and the bank 2 verdict with it (cpu_boot)", e.r32(0x2405FFD0) == 0)
e.meter_up()                                      # ...and the audio task's first wake sets it up again, before any block
check("master_alloc: the delay's line is allocated as before, then 0x84900 bytes (Prism's 0x56800 + 0x1000 for the LFOs + 0x6000 for the USB audio ring + 0x4000 for the S950 filters + 0x22000 for the pad inserts + 0x100 for the clipper + 0x1000 for the Clip Window), pointer + check word stored",
      allocs == [("line", 0x24076000, 192000), ("perm", 0x84900)] and e.r32(PMEM) & 0xFFFFFFFF == PRISM and e.r32(PCHECK) & 0xFFFFFFFF == PRISM ^ 0x5052534D, (allocs, hex(e.r32(PMEM)), hex(e.r32(PCHECK))))
check("the patched call in the delay constructor goes to master_alloc", e.uc.mem_read(0x0805462A, 4) != bytes.fromhex("16f029fa") and e.sym["master_alloc"] != 0)
e.w32(PCHECK, 0x12345678)
l, r = block(x)
check("a stale pointer (check word wrong): passes through", l == f32(x))
e.w32(PCHECK, PRISM ^ 0x5052534D)

# --- audio
settings(mfx=2, mix=1000, tilt=500)
l, r = block(x)
check("all four amounts at 0, Tilt flat: bit-exact pass-through", l == f32(x) and r == f32(x), max(abs(a - b) for a, b in zip(l, f32(x))))
check("...and Prism's block is started (magic PRS1)", e.r32(PRISM) == 0x50525331)
for b in range(4):
    for f, name in enumerate(FX[b]):
        settings(mfx=2, mix=1000, tilt=500, rate=500, time=1, **{f"fx{b}": f, f"amt{b}": 600})
        blocks = 110 if name == "Scatter" else 24          # Scatter reaches up to four steps back: give it something to find
        l, r = play(blocks, tone)
        dry = [tone(i) for i in range(blocks * N)]
        diff = max(abs(a - c) for a, c in zip(l[(blocks - 16) * N:], dry[(blocks - 16) * N:]))
        ok = all(v == v for v in l + r) and peak(l + r) <= 1.0 and (diff > 0.005 or name == "Bloom")
        check(f"{['Drive', 'Motion', 'Space', 'Texture'][b]} / {name} at 60 %: finite, under full scale (peak {peak(l + r):.2f}), changes the signal ({diff:.3f})", ok, (peak(l + r), diff))

# --- tempo: Cascade at 1/4
e.w32(BUFS, CTX)
e.uc.mem_write(CTX + 0x18, struct.pack("<f", 120.0))
settings(mfx=0)
block(x)                                         # Off: Prism's block is cleared for its next start
check("Master FX Off: Prism's magic is cleared", e.r32(PRISM) == 0)
settings(mfx=2, mix=1000, tilt=500, fx2=0, amt2=1000, time=5)
l, r = play(120, lambda t: 0.5 if t == 100 else 0.0)
late = max(range(2000, len(l)), key=lambda i: abs(l[i]) + abs(r[i]))
check(f"PingPong, Time 1/4 at the preset's 120 BPM: the click comes back {(late - 100) / 48:.0f} ms later", abs(late - 100 - 24000) <= 2, late)
e.uc.mem_write(CTX + 0x18, struct.pack("<f", 60.0))
settings(mfx=0)
block(x)
settings(mfx=2, mix=1000, tilt=500, fx2=0, amt2=1000, time=3)
l, r = play(120, lambda t: 0.5 if t == 100 else 0.0)
late = max(range(2000, len(l)), key=lambda i: abs(l[i]) + abs(r[i]))
check(f"...1/8 at 60 BPM: {(late - 100) / 48:.0f} ms", abs(late - 100 - 24000) <= 2, late)
e.w32(BUFS, 0)
settings(mfx=0)
block(x)
settings(mfx=2, mix=1000, tilt=500, fx2=0, amt2=1000, time=5)
l, r = play(120, lambda t: 0.5 if t == 100 else 0.0)
late = max(range(2000, len(l)), key=lambda i: abs(l[i]) + abs(r[i]))
check(f"tempo not readable: 120 BPM assumed ({(late - 100) / 48:.0f} ms)", abs(late - 100 - 24000) <= 2, late)

# --- Mix, Tilt
settings(mfx=0)
block(x)
settings(mfx=2, mix=0, tilt=500, fx0=2, amt0=1000)
l, r = play(60, tone)                            # the Mix knob is smoothed over a few blocks
check("Mix 0: dry, whatever the blocks do", max(abs(a - c) for a, c in zip(l[56 * N:], [tone(i) for i in range(56 * N, 60 * N)])) < 1e-3)
settings(mfx=0)
block(x)
lo = lambda t: 0.3 * math.sin(2 * math.pi * 100 * t / 48000)
hi = lambda t: 0.3 * math.sin(2 * math.pi * 6000 * t / 48000)
res = {}
for tilt in (0, 1000):
    for nm, src in (("lo", lo), ("hi", hi)):
        settings(mfx=2, mix=1000, tilt=tilt)
        l, _ = play(12, src)
        res[tilt, nm] = 20 * math.log10(peak(l[8 * N:]) / 0.3)
check(f"Tilt 0: lows {res[0, 'lo']:+.1f} dB, highs {res[0, 'hi']:+.1f} dB; Tilt 100 %: lows {res[1000, 'lo']:+.1f}, highs {res[1000, 'hi']:+.1f}",
      res[0, "lo"] > 4 and res[0, "hi"] < -4 and res[1000, "lo"] < -4 and res[1000, "hi"] > 4, res)

# --- worst case and cost
settings(mfx=2, mix=1000, tilt=1000, rate=1000, time=0, fx0=0, amt0=1000, fx1=4, amt1=1000, fx2=1, amt2=1000, fx3=1, amt3=1000)
l, r = play(40, lambda t: 1.5 * math.sin(2 * math.pi * 220 * t / 48000))
check(f"all four blocks at 100 % on a +3.5 dB input: finite, never over full scale (peak {peak(l + r):.3f})", peak(l + r) <= 1.0 and all(v == v for v in l + r))
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
block([tone(i) for i in range(N)])
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions per 256-frame block, {cnt[0] / N:.0f} per frame (Drive + Pitch + Tape + Clamp)")
settings(mfx=2, mix=1000, tilt=500, rate=300, time=3, fx0=1, amt0=300, fx3=2, amt3=250)
play(4, tone)
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
block([tone(i) for i in range(N)])
e.uc.hook_del(h)
print(f"     cost at Prism's defaults (Sweet + Cassette): {cnt[0] / N:.0f} per frame")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
