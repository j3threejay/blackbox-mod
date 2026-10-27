"""ChopShop slice points (src/chop.c), under Unicorn.

Real firmware runs for: chop_set_slices with stock's own list helpers (FUN_08093c98 clear, FUN_08093cca sorted insert),
chop_beats. Stubbed: the cell lookup (FUN_08098d0c returns a fake cell), the engine message (FUN_0804c69c, recorded),
the app post (FUN_080b5758, recorded).
NOT checked: the engine pad's copy and the screen on a unit (research/slicer/SLICE_POINTS_RE.md is static).
"""
import struct
import sys

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e = Emu(IMAGE, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
CELL, BUF, POS, MSGS = 0x24060000, 0x24061000, 0x24062000, []
REFS, POSTS = [], []
e.w32(CELL + 0x28, BUF)
e.w32(CELL + 0x2C, 0)
for i in range(128):
    e.w32(BUF + 4 * i, 0xDEAD)


def cell():
    r = e.arg(1)
    REFS.append((e.r32(r), e.r16(r + 4)))
    e.ret(CELL)


e.stub(0x08098D0C, cell)
e.stub(0x0804C69C, lambda: MSGS.append((e.arg(0), e.arg(1), e.arg(2) - (1 << 32 if e.arg(2) >= 1 << 31 else 0), e.arg(3))))
e.stub(0x080B5758, lambda: POSTS.append((e.arg(0), e.r16(e.arg(1)), e.r32(e.arg(1) + 4), e.r16(e.arg(1) + 8))))


def lst():
    n = e.r32(CELL + 0x2C)
    return [e.r32(BUF + 4 * i) for i in range(n)]


def beats(len_, anchor, fpb, unit, mx=128):
    e.uc.mem_write(STACK, struct.pack("<ff", fpb, unit))
    from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", fpb))[0])
    e.uc.reg_write(UC_ARM_REG_S1, struct.unpack("<I", struct.pack("<f", unit))[0])
    e.call("chop_beats", POS, mx, len_, anchor)
    n = e.uc.reg_read(__import__("unicorn.arm_const", fromlist=["x"]).UC_ARM_REG_R0)
    return [struct.unpack("<i", e.uc.mem_read(POS + 4 * i, 4))[0] for i in range(n)]


# RC000008: 194.48 BPM detected, beat one at 5553, 48 kHz, 5,845,367 frames; one click down = 97.24 BPM
fpb = 48000 * 60 / 97.24
p = beats(5845367, 5553, fpb, 1.0)
check(f"beats at 97.24 BPM from beat one 5553: a pickup slice at 0, then every beat ({len(p)} points, capped at 128)",
      p[0] == 0 and p[1] == 5553 and len(p) == 128 and abs(p[2] - p[1] - fpb) < 1, p[:4])
check("... computed per point, not accumulated: point 127 = 5553 + 126 x fpb to the frame",
      p[127] == int(5553 + 126 * fpb + 0.5), (p[127], 5553 + 126 * fpb))
p = beats(5845367, 30, fpb, 4.0)
check("a bar (4 beats), beat one at frame 30: no pickup (under 64 frames), starts at 30", p[0] == 30 and abs(p[1] - 30 - 4 * fpb) < 1, p[:3])
p = beats(240000, 0, 24000.0, 0.5)
check("half beats on a 5 s loop at 120 BPM: 20 points, the last below the length", len(p) == 20 and p[-1] == 228000, (len(p), p[-1]))
check("a step under 16 frames: nothing", beats(240000, 0, 20.0, 0.25) == [])

e.uc.mem_write(POS, struct.pack("<5i", 0, 5553, 35168, 64784, 94400))
e.call("chop_set_slices", 2 << 4 | 1, POS, 5)
check("chop_set_slices: the app cell's list holds exactly the new points, sorted", lst() == [0, 5553, 35168, 64784, 94400], lst())
check("... the cell looked up for pad row 2 col 1 with stock's ref tag", REFS[-1] == (0x080EAF38, 0x21), REFS)
check("... the engine is told: clear (1000), then insert (1) each point, for pad col 1 | row 2 << 8",
      MSGS == [(0x2400A9C0, 0x201, 0, 1000)] + [(0x2400A9C0, 0x201, v, 1) for v in (0, 5553, 35168, 64784, 94400)], MSGS)
check("... ONE screen refresh (0x66) for that cell, and the project marked changed",
      POSTS == [(0x24020088 + 0x30, 0x66, 0x080CFBA4, 0x21)] and e.r8(0x24020088 + 0x8CC4) == 1, POSTS)
MSGS.clear()
e.uc.mem_write(POS, struct.pack("<4i", 100, 100, 50, 200))
e.call("chop_set_slices", 0x21, POS, 4)
check("duplicates and order: the list keeps 50, 100, 200; the engine is only sent what the list took",
      lst() == [50, 100, 200] and [m[2] for m in MSGS if m[3] == 1] == [100, 50, 200], (lst(), MSGS))

# --- the whole-file beat scan (chop_dsp.c, bank 2) and Find / Random (chop.c), on a synthetic track
import math
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_R0
FPB, NB = 24000, 64                               # 120 BPM at 48 kHz, 64 beats
TL = []
for i in range(FPB * NB):
    b, k = divmod(i, FPB)
    amp = 0.0 if 20 <= b < 28 else (0.9 if b % 4 == 0 else 0.4)      # bars hit harder; beats 20..27 silent
    TL.append(amp * math.exp(-k / 2000.0) * math.sin(2 * math.pi * 90 * k / 48000) + (0.0 if 20 <= b < 28 else 0.05))
J, SCR2 = 0x24070000, 0x24068000
e.uc.mem_write(J, bytes(48 + 8 * 1024))


def cfetch():
    l, r, n = e.arg(1), e.arg(2), e.arg(3)
    pos = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    seg = TL[pos:pos + n] + [0.0] * max(0, pos + n - len(TL))
    e.uc.mem_write(l, struct.pack(f"<{n}f", *seg[:n]))
    if r:
        e.uc.mem_write(r, struct.pack(f"<{n}f", *seg[:n]))
    e.ret(1)


e.stub(0x080636F0, cfetch)                        # any mapped address: the job calls job->fetch through a pointer
from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1
e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 0.0))[0])
e.uc.reg_write(UC_ARM_REG_S1, struct.unpack("<I", struct.pack("<f", float(FPB)))[0])
e.w32(STACK, 1)                                   # stereo (5th argument)
e.call("chop_scan_start", J, 6, 0x1234, len(TL))
e.w32(J + 40, 0x080636F1)
check("chop_scan_start: 64 beats on the grid, scanning", e.r32(J) == 1 and e.r32(J + 28) == NB, (e.r32(J), e.r32(J + 28)))
blocks = 0
while e.r32(J) == 1 and blocks < 100:
    e.call("chop_scan_step", J, SCR2, count=50_000_000)
    blocks += 1
lev = struct.unpack("<64f", e.uc.mem_read(J + 44, 256))
hit = struct.unpack("<64f", e.uc.mem_read(J + 44 + 4096, 256))
check(f"the scan finishes in {blocks} blocks (4 beats a block)", e.r32(J) == 2 and blocks == 16, (e.r32(J), blocks))
check("... silent beats read silent; a bar hits harder than a beat", max(lev[20:28]) == 0.0 and hit[4] > hit[5] > 0.0,
      (max(lev[20:28]), hit[4], hit[5]))


def pick(fn, want, seed):
    e.call(fn, POS, want, J, seed)
    n = e.uc.reg_read(UC_ARM_REG_R0)
    return [struct.unpack("<i", e.uc.mem_read(POS + 4 * i, 4))[0] for i in range(n)]


f1, f2 = pick("chop_find", 8, 1), pick("chop_find", 8, 777)
beats_of = lambda ps: [p // FPB for p in ps]
check(f"Find 8: on beats, ascending, none in the silence, at most one per eighth of the track {beats_of(f1)}",
      all(p % FPB == 0 for p in f1) and f1 == sorted(f1) and not any(20 <= b < 28 for b in beats_of(f1))
      and len(set(b // 8 for b in beats_of(f1))) == len(f1) and 6 <= len(f1) <= 8, f1)
check(f"... mostly bar starts (they hit 1.5 x harder than they jitter): {sum(b % 4 == 0 for b in beats_of(f1))} of {len(f1)}",
      sum(b % 4 == 0 for b in beats_of(f1)) >= len(f1) - 2, beats_of(f1))
check(f"... another roll finds other chops {beats_of(f2)}", f2 != f1, (f1, f2))
r1, r2 = pick("chop_random", 16, 5), pick("chop_random", 16, 6)
check(f"Random 16: 16 different usable beats, ascending, none silent {beats_of(r1)}",
      len(r1) == 16 and len(set(r1)) == 16 and r1 == sorted(r1) and not any(20 <= b < 28 for b in beats_of(r1)), r1)
check("... another seed, another set", r1 != r2, (r1, r2))
check("Random 100 on 56 usable beats: all 56", len(pick("chop_random", 100, 9)) == 56)

# --- the driver: chop_request -> the detector -> (scan) -> slices; chop_poll runs every GUI frame (theme_compose)
MASTER, AREA = 0xC0000000, 0xC0100000
e.uc.mem_map(0xC0000000, 0x200000)
e.uc.mem_write(MASTER, b"\xa5" * 0x94910)
e.uc.mem_write(AREA, b"\xa5" * 0x60000)           # the area as SDRAM garbage: magic-checked, cleared
e.w32(0x38800F70, MASTER)
e.w32(0x38800F74, MASTER ^ 0x5052534D)
e.w32(MASTER + 0x94900, AREA)
CR, CJ, TJ, CLIP = AREA + 351508, AREA + 343272, AREA + 297020, AREA + 28
PADE, SRC = 0x24072000, 0x24072800
e.uc.mem_write(PADE, bytes(0x300))
e.w32(PADE + 0x24, SRC)
SETS, EPARAMS = [], []
e.stub(0x08093ECC, lambda: SETS.append((e.arg(0), e.arg(1), e.arg(2))))
e.stub(0x0804C59C, lambda: EPARAMS.append((e.arg(0), e.arg(1), e.arg(2), e.arg(3))))
e.stub(0x080636F0, value=len(TL))
e.stub(0x08063790, value=1)


def cfetch2():
    l, r, n = e.arg(1), e.arg(2), e.arg(3)
    pos = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    seg = (TL[pos:pos + n] + [0.0] * n)[:n]
    e.uc.mem_write(l, struct.pack(f"<{n}f", *seg))
    e.uc.mem_write(r, struct.pack(f"<{n}f", *seg))
    e.ret(1)


e.stubs[0x08063608] = cfetch2
e.call("stretch_tick")                            # the area comes up (magic, cleared)
e.w32(CLIP + 6 * 24, PADE)                        # what setup leaves: pad 6's engine object


def detected(bpm, phase, frate=48000, q=6, ok=True):
    e.w32(TJ + 160, e.r32(TJ + 156))              # served = req
    e.w32(TJ + 4, q)
    e.w32(TJ, 8 if ok else 9)
    e.uc.mem_write(TJ + 148, struct.pack("<ff", bpm, phase))
    e.w32(TJ + 24, frate)


def cr():
    op, ph, pad_, unit, fail = struct.unpack("<5B", e.uc.mem_read(CR, 5))
    return dict(op=op, phase=ph, pad=pad_, fail=fail)


MSGS.clear()
req0 = e.r32(TJ + 156)
e.call("chop_request", 6, 1, 2, 16)               # Beats, a beat each
check("Beats requested on pad 6: waiting on the tempo, the detector asked for pad 6",
      cr()["phase"] == 1 and e.r32(TJ + 156) == req0 + 1 and e.r32(TJ + 164) == 6, (cr(), e.r32(TJ + 156)))
e.call("chop_poll")
check("... nothing placed before the detector answers", lst() == [50, 100, 200] and cr()["phase"] == 1, lst())
detected(120.0, 6000.0)
e.call("chop_poll")
want = [0] + [6000 + 24000 * k for k in range(64) if 6000 + 24000 * k < len(TL)]
check(f"... the answer (120 BPM, beat one 6000): a pickup at 0 then every beat ({len(lst())} slices), done",
      lst() == want and cr()["phase"] == 0 and cr()["fail"] == 0, lst()[:5])
check("... and the detector's job is taken (idle again)", e.r32(TJ) == 0)

e.call("chop_request", 6, 2, 0, 8)                # Find 8
detected(120.0, 0.0)
e.call("chop_poll")
check("Find: tempo in, the beat scan starts on pad 6's sample", e.r32(CJ) == 1 and e.r32(CJ + 4) == 6 and cr()["phase"] == 2,
      (e.r32(CJ), cr()))
e.call("chop_poll")
check("... no slices while it scans", cr()["phase"] == 2)
while e.r32(CJ) == 1:
    e.call("chop_scan_step", CJ, SCR2, count=50_000_000)
SETS.clear(); EPARAMS.clear()
e.call("chop_poll")
f1 = lst()
check(f"... scan done: 8 Find chops placed {[p // FPB for p in f1]}, on beats, none in the silence",
      len(f1) == 8 and all(p % FPB == 0 for p in f1) and not any(20 <= p // FPB < 28 for p in f1) and cr()["phase"] == 0, f1)
check("... and PlayThru on (0xf2 = 1) in the pad's store and to the engine (Find plays on past a chop)",
      (CELL, 0xF2, 1) in SETS and (0x2400A9C0, 0x102, 0xF2, 1) in EPARAMS, (SETS, EPARAMS))
e.call("chop_request", 6, 2, 0, 8)                # roll again
check("a re-roll of Find: straight to the scan it already has (no detector, no rescan)", cr()["phase"] == 2 and e.r32(CJ) == 2, cr())
e.call("chop_poll")
check(f"... another set {[p // FPB for p in lst()]}", lst() != f1 and len(lst()) == 8, lst())

e.call("chop_forget", 6)                          # a new sample on pad 6 (chop_header_post)
e.call("chop_request", 6, 2, 0, 8)
check("Find after a new sample: the detector again (the old scan is the old file's), not a re-roll",
      cr()["phase"] == 1 and e.r32(TJ + 164) == 6, cr())
e.call("chop_forget", 5)
check("chop_forget on another pad leaves pad 6's run alone", cr()["phase"] == 1, cr())

e.call("chop_request", 6, 3, 0, 16)               # Random 16, the tempo fails
detected(0.0, 0.0, ok=False)
e.call("chop_poll")
check("the detector fails: nothing placed, fail 1", cr()["phase"] == 0 and cr()["fail"] == 1, cr())
e.call("chop_request", 6, 1, 2, 16)               # nobody answers
for _ in range(1801):
    e.call("chop_poll")
check("no answer for ~30 s of GUI frames: gives up, fail 2", cr()["phase"] == 0 and cr()["fail"] == 2, cr())

# --- the Roll row's cue (chop_roll_text; chopmode.c's view tick shows it): dice, Rolling.., the result, a resting die
from unicorn.arm_const import UC_ARM_REG_R0  # noqa: E402
TXT = SCR2 + 0x1800
DICE = ["[.]", "[:]", "[:.]", "[::]", "[:.:]", "[:::]"]


def roll(q=6):
    e.call("chop_roll_text", q, TXT)
    return e.cstr(e.uc.reg_read(UC_ARM_REG_R0))


for _ in range(200):
    e.call("chop_poll")                           # whatever the last test left: run out
check("idle: a resting die", roll() == "[:.:]", roll())
e.call("chop_request", 6, 1, 2, 16)               # Beats
seen = []
for _ in range(36):
    seen.append(roll())
    e.call("chop_poll")
check(f"a turn: dice tumble for ~0.6 s ({sorted(set(seen))})", all(t in DICE for t in seen) and len(set(seen)) == 6, seen)
check("... another pad's Roll stays at rest", roll(5) == "[:.:]", roll(5))
check("... still waiting on the tempo: Rolling..", roll() == "Rolling..", roll())
check("... the knob formatter's 'any pad' = the run's pad", roll(-2) == "Rolling..", roll(-2))
detected(120.0, 6000.0)
e.call("chop_poll")
n = len(lst())
check(f"... done: '{n} chops'", roll() == f"{n} chops", roll())
for _ in range(89):
    e.call("chop_poll")
check("... still up just before ~1.5 s", roll() == f"{n} chops", roll())
e.call("chop_poll")
check("... then the resting die", roll() == "[:.:]", roll())
e.call("chop_request", 6, 3, 0, 16)               # Random, the tempo fails at once
detected(0.0, 0.0, ok=False)
e.call("chop_poll")
check("a failure during the dice: the dice play out first", roll() in DICE, roll())
for _ in range(36):
    e.call("chop_poll")
check("... then 'Fail 1'", roll() == "Fail 1", roll())

# --- the Tempo row (chopmode.c; code in P_SEL_BEATS 0x15e: 0 x1, 1 half, 2 double): detection and a re-tempo
TEMPO = [0]
e.stub(0x08093E9C, lambda: e.ret(TEMPO[0] if e.arg(1) == 0x15E else 0))
for _ in range(200):
    e.call("chop_poll")
TEMPO[0] = 2                                      # x2: the detector read the song at half its tempo
SETS.clear()
e.call("chop_request", 6, 1, 2, 16)               # Beats, a beat each
detected(120.0, 6000.0)                           # 120 detected -> 240 true: a beat = 12000 frames
e.call("chop_poll")
p2 = lst()
check(f"Tempo x2: the chops land every 12000 frames (true beats), not 24000 ({p2[:4]})",
      len(p2) > 2 and p2[1] == 6000 and p2[2] - p2[1] == 12000, p2[:4])
check("... and Beat Count = the file's beats at the true tempo", (CELL, 0xD2, round(len(TL) / 12000)) in SETS,
      [x for x in SETS if x[1] == 0xD2])
SETS.clear()
TEMPO[0] = 1
ok = e.call("chop_retempo", 6, 2, 1) is not None and e.uc.reg_read(UC_ARM_REG_R0)
p3 = lst()
check(f"re-tempo x2 -> 1/2 with the detection in hand: at once, no detector, a chop every 48000 ({p3[:4]})",
      ok == 1 and len(p3) > 2 and p3[2] - p3[1] == 48000 and cr()["phase"] == 0, (ok, p3[:4], cr()))
check("... Beat Count follows", (CELL, 0xD2, round(len(TL) / 48000)) in SETS, [x for x in SETS if x[1] == 0xD2])
check("... with the dice cue", roll() in DICE, roll())
e.call("chop_retempo", 5, 1, 0)
check("re-tempo on a pad with no detection: 0 (the caller detects)", e.uc.reg_read(UC_ARM_REG_R0) == 0)
TEMPO[0] = 0

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
