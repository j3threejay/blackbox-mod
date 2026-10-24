"""Groove (src/groove.c) under Unicorn.

Real firmware runs for: groove_s2t / groove_t2s and their grid maths, against the patched image.
Stubbed: the settings read (FUN_08093e9c: the chosen Groove), the clock's sample <-> tick converters FUN_0804d708 /
FUN_0804d798 (identity: one sample = one tick, so what is checked is the warp itself), and stock's two swing
functions (recorded, to prove Stock hands every call to them untouched).
Checked: Stock calls stock with the same arguments; where the swung note lands for MPC / Linn/909 / SP-1200 at the
classic settings (their own ticks: 96, 48, 24 PPQN); the window (16ths, or 8ths on the SP-1200); clamping; that the
two directions are inverses on every grid point and the map never runs backwards; negative ticks; the three player
calls and seqfix's call are redirected; "Groove:" registered with four names and on the Tools Clock tab (Main until beta 1).
NOT run: the player and the engine clock on the unit (the real converters, tempo changes), the swung note-on offset
inside a block (stock behaviour, unchanged), how it feels.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
fw = open(IMG, "rb").read()
CLOCK, OUT, TICKS = 0x24060000, 0x24061000, 0x24061100
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


state = {"groove": 0}
log = []
e.stub(0x08093E9C, lambda: e.uc.reg_write(UC_ARM_REG_R0, state["groove"] if e.arg(1) == 0x145 else 0), value=None)


def s2raw():                       # out = sample (identity), args: out, clk, lo, hi
    e.uc.mem_write(e.arg(0), struct.pack("<II", e.arg(2), e.arg(3)))


def raw2s():                       # out = *ticks
    e.uc.mem_write(e.arg(0), bytes(e.uc.mem_read(e.arg(2), 8)))


e.stub(0x0804D708, s2raw)
e.stub(0x0804D798, raw2s)


def stock_s2t():
    log.append(("stock_s2t", e.arg(1), e.arg(2), e.arg(3)))
    e.uc.mem_write(e.arg(0), struct.pack("<q", -7))
    e.uc.reg_write(UC_ARM_REG_R0, e.arg(0))


def stock_t2s():
    log.append(("stock_t2s", e.arg(1), struct.unpack("<q", bytes(e.uc.mem_read(e.arg(2), 8)))[0]))
    e.uc.mem_write(e.arg(0), struct.pack("<q", -9))
    e.uc.reg_write(UC_ARM_REG_R0, e.arg(0))


e.stubs[0x08069C94] = lambda: (stock_s2t(), e.ret())
e.stubs[0x08069E84] = lambda: (stock_t2s(), e.ret())


def set_swing(v):
    e.uc.mem_write(CLOCK + 0x148, struct.pack("<f", v / 100.0))


def t2s(t):
    e.uc.mem_write(TICKS, struct.pack("<q", t))
    e.call("groove_t2s", OUT, CLOCK, TICKS)
    return struct.unpack("<q", bytes(e.uc.mem_read(OUT, 8)))[0]


def s2t(s):
    e.call("groove_s2t", OUT, CLOCK, s & 0xFFFFFFFF, (s >> 32) & 0xFFFFFFFF)
    return struct.unpack("<q", bytes(e.uc.mem_read(OUT, 8)))[0]


# --- Stock: untouched
state["groove"] = 0
set_swing(62)
log.clear()
a, b = t2s(1234), s2t(5678)
check("Stock: both calls go to stock's own functions with the same arguments and return theirs",
      log == [("stock_t2s", CLOCK, 1234), ("stock_s2t", CLOCK, 5678, 0)] and (a, b) == (-9, -7), (log, a, b))

# --- where the swung note lands (straight -> real), at the classic settings
cases = [
    # groove, swing number, straight tick, expected real tick, why
    (1, 50, 240, 240, "MPC 50 %: straight"),
    (1, 54, 240, 260, "MPC 54 %: 260 of 480 (54.2 %, its 96 PPQN tick)"),
    (1, 62, 240, 300, "MPC 62 %: 300 of 480 (62.5 %)"),
    (1, 66, 240, 320, "MPC 66 %: 320 = the triplet (66.7 %)"),
    (1, 75, 240, 360, "MPC 75 %: 360 (its maximum)"),
    (1, 99, 240, 360, "MPC: Swing 99 clamps to 75 %"),
    (1, 30, 240, 240, "MPC: Swing below 50 reads as straight"),
    (1, 62, 960 + 240, 960 + 300, "MPC: every pair, not just the first"),
    (1, 62, 480, 480, "MPC: pair starts stay put"),
    (2, 58, 240, 280, "Linn/909 58 %: 280 (two 48 PPQN ticks late)"),
    (2, 62, 240, 300, "Linn/909 62 %: 300 (three ticks)"),
    (2, 71, 240, 340, "Linn/909 71 %: 340 (five ticks)"),
    (3, 54, 480, 520, "SP-1200 54: the second 8th one 24 PPQN tick late"),
    (3, 58, 480, 560, "SP-1200 58: two ticks"),
    (3, 63, 480, 600, "SP-1200 63: three ticks"),
    (3, 67, 480, 640, "SP-1200 67: four ticks"),
    (3, 71, 480, 680, "SP-1200 71: five ticks, its maximum"),
    (3, 75, 480, 680, "SP-1200: Swing 75 clamps to its 71"),
    (3, 63, 240, 300, "SP-1200 63: the 16th between moves in proportion (240 -> 300)"),
    (3, 63, 960, 960, "SP-1200: the beat stays put (window = a quarter)"),
    (1, 62, -240, -180, "MPC: a negative tick (a lead-in) swings the same way"),
]
for g, v, t, want, why in cases:
    state["groove"] = g
    set_swing(v)
    got = t2s(t)
    check(f"{why}", got == want, (got, want))

# --- inverse and order: real -> straight must be the first straight tick that sounds at or after it (that is what
# makes the player's "start < horizon" test fire exactly when the swung time comes), and time never runs backwards
for g, name in ((1, "MPC-60/3K"), (2, "Linn/909"), (3, "SP-1200")):
    state["groove"] = g
    bad, back, grid = [], [], []
    for v in (54, 62, 71):
        set_swing(v)
        fwd = {t: t2s(t) for t in range(-1000, 1961)}
        back += [(v, t) for t in range(-999, 1961) if fwd[t] < fwd[t - 1]]
        for r in range(-960, 1921, 7):
            want = min(t for t in fwd if fwd[t] >= r)
            if s2t(r) != want:
                bad.append((v, r, s2t(r), want))
        grid += [(v, t, s2t(fwd[t])) for t in range(-960, 1921) if (t % 60 == 0 or t % 80 == 0) and not t - 2 <= s2t(fwd[t]) <= t]
    check(f"{name}: real -> straight = the first straight tick sounding at or after it (every 7th tick), "
          "step points (1/64, triplets) come back at most 2 ticks short and never late (stock's own swing rounds both ways "
          "too), time never runs backwards", not bad and not back and not grid,
          (bad[:3], back[:3], grid[:3]))

# --- the hooks and the registration in the image
def bl_target(at):
    h1, h2 = struct.unpack_from("<HH", fw, at - 0x08040000)
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s:
        off -= 1 << 25
    return at + 4 + off


sites = {0x0805D238: "groove_s2t", 0x0805DC90: "groove_s2t", 0x0805DE58: "groove_t2s"}
check("the player's three swing calls go to the groove functions",
      all(bl_target(a) == e.sym[n] & ~1 for a, n in sites.items()), {hex(a): hex(bl_target(a)) for a in sites})
main = struct.unpack_from("<14H", fw, 0x080EED18 - 0x08040000)
clock = struct.unpack_from("<6H", fw, 0x080EEDF0 - 0x08040000)
check("Groove on the Clock tab after its four stock rows, not on Main (Main holds 12 rows at most: test_toolstabs.py)",
      list(clock[:6]) == [0xEF, 0xF0, 0x10F, 0x110, 0x145, 0] and 0x145 not in main, ([hex(x) for x in main], [hex(x) for x in clock]))
regs = []
e.stub(0x0808C0D8, lambda: regs.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i) & 0xFFFFFFFF)
                                                                      for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))])))
e.call("groove_register", 0x24062000)
check('registered: 0x145 "Groove:" Stock / MPC-60/3K / Linn/909 / SP-1200', regs == [(0x145, "Groove:", ["Stock", "MPC-60/3K", "Linn/909", "SP-1200"])], regs)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
