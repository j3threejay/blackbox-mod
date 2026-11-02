"""ChopShop slice points (src/chop.c), under Unicorn.

Real firmware runs for: chop_set_slices with stock's own list helpers (FUN_08093c98 clear, FUN_08093cca sorted insert),
chop_beats. Stubbed: the cell lookup (FUN_08098d0c returns a fake cell), the engine message (FUN_0804c69c, recorded),
the app post (FUN_080b5758, recorded).
NOT checked: the engine pad's copy and the screen on a unit (research/slicer/SLICE_POINTS_RE.md is static).
"""
import struct
import sys

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
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

# --- the attack scan (chop_dsp.c, bank 2) and the placement (chop.c), on a synthetic track with free-time hits
import math
import random
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_R0
FPB, NB = 24000, 64                               # 120 BPM at 48 kHz, 64 beats
SILENT = range(20, 28)                            # beats with no sound at all
LATE = range(32, 40)                              # their hit 3000 frames (62 ms) after the beat: off any grid
OFFB = range(40, 48)                              # an extra hit half a beat after the beat
ONSETS = sorted([b * FPB + (3000 if b in LATE else 0) for b in range(NB) if b not in SILENT] +
                [b * FPB + FPB // 2 for b in OFFB])
rng = random.Random(7)
TL = [0.0] * (FPB * NB)
for o in ONSETS:
    b = o // FPB
    amp = 0.9 if o % FPB == 0 and b % 4 == 0 else 0.4 if o % FPB != FPB // 2 else 0.25   # bars hit harder
    for k in range(6000):
        TL[o + k] += amp * math.exp(-k / 900.0) * (rng.random() * 2 - 1)
CLICK = 50 * FPB + 5000                           # a click 16 dB under beat 50's hit, after it (a grid from 6000 is nearer it)
for k in range(1500):
    TL[CLICK + k] += 0.06 * math.exp(-k / 300.0) * (rng.random() * 2 - 1)
J, SCR2 = 0x24070000, 0x24068000
J_N, J_LEN, J_NEXT, J_FETCH, J_AT, J_LEVEL = 20, 12, 24, 36, 1856, 10048   # offsetof(struct chop_job, ...), arm-none-eabi
e.uc.mem_write(J, bytes(0x3800))


def cfetch():
    l, r, n = e.arg(1), e.arg(2), e.arg(3)
    pos = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    seg = (TL[pos:pos + n] + [0.0] * n)[:n]
    e.uc.mem_write(l, struct.pack(f"<{n}f", *seg))
    if r:
        e.uc.mem_write(r, struct.pack(f"<{n}f", *seg))
    e.ret(1)


LEVELS = {}


def levels_of(j):
    """hit frame -> level, for the model below"""
    n = e.r32(j + J_N)
    at = struct.unpack(f"<{n}i", e.uc.mem_read(j + J_AT, 4 * n))
    lv = struct.unpack(f"<{n}f", e.uc.mem_read(j + J_LEVEL, 4 * n))
    LEVELS.clear()
    LEVELS.update(zip(at, lv))


def hits_of(j):
    n = e.r32(j + J_N)
    levels_of(j)
    return sorted(struct.unpack(f"<{n}i", e.uc.mem_read(j + J_AT, 4 * n))) if n else []




e.stub(0x080636F0, cfetch)                        # any mapped address: the job calls job->fetch through a pointer
e.w32(STACK, 1)                                   # stereo (5th argument)
e.call("chop_scan_start", J, 6, 0x1234, len(TL))
e.w32(J + J_FETCH, 0x080636F1)
check("chop_scan_start: scanning, no hits yet", e.r32(J) == 1 and e.r32(J + J_N) == 0, (e.r32(J), e.r32(J + J_N)))
blocks = 0
while e.r32(J) == 1 and blocks < 2000:
    e.call("chop_scan_step", J, SCR2, count=50_000_000)
    blocks += 1
H = hits_of(J)
check(f"the scan finishes in {blocks} blocks (2048 frames a block: 16x real time)",
      e.r32(J) == 2 and blocks == len(TL) // 2048 + 1, (e.r32(J), blocks))
ON = sorted([o for o in ONSETS if o > 0] + [CLICK])   # a hit at frame 0 is the file start (its slice is always there)
ahead = [min((o - h for h in H if -16 <= o - h <= 64), default=None) for o in ON]
check(f"every hit found, 1..48 frames ahead of its first frame ({len(H)} hits for {len(ON)} onsets: on beats, late, "
      f"off-beat)", all(a is not None for a in ahead) and len(H) == len(ON) and all(0 < a <= 48 for a in ahead),
      [(o, a) for o, a in zip(ON, ahead) if a is None or not 0 < a <= 48][:5] + [len(H)])
check("... none in the silence", not any(SILENT.start * FPB <= h < SILENT.stop * FPB - 64 for h in H),
      [h for h in H if SILENT.start * FPB <= h < SILENT.stop * FPB - 64])


def pick(fn, want, seed):
    e.call(fn, POS, want, J, seed)
    n = e.uc.reg_read(UC_ARM_REG_R0)
    return [struct.unpack("<i", e.uc.mem_read(POS + 4 * i, 4))[0] for i in range(n)]


def onto(len_, anchor, fpb, unit):
    """chop_beats, then chop_onto_hits (what chop_poll places for a grid chop)"""
    from unicorn.arm_const import UC_ARM_REG_S0
    g = beats(len_, anchor, fpb, unit)
    e.uc.mem_write(POS, struct.pack(f"<{len(g)}i", *g))
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", fpb * unit))[0])
    e.call("chop_onto_hits", POS, len(g), J)
    n = e.uc.reg_read(UC_ARM_REG_R0)
    return g, [struct.unpack("<i", e.uc.mem_read(POS + 4 * i, 4))[0] for i in range(n)]


def model(g, step, hits):
    """the rule: each point to the nearest hit within half a step, among those within 10 dB of the loudest there (and
    over -30 dB of the file's loudest), else dropped; the file start stays. Levels: LEVELS (levels_of)"""
    out = []
    floor = max(LEVELS[h] for h in hits) * 0.001
    for p in g:
        if p <= 0:
            out.append(0)
            continue
        c = [h for h in hits if abs(h - p) <= int(step * 0.5) and LEVELS[h] > floor]
        top = max([LEVELS[h] for h in c] + [floor])
        c = [h for h in c if LEVELS[h] >= top * 0.1]
        if c:
            out.append(min(c, key=lambda h: (abs(h - p), hits.index(h))))
    if not out or min(out) > 64:
        out.append(0)
    return sorted(set(out))


hs = set(H)
g, got = onto(len(TL), 0, FPB, 1.0)
check(f"Beat chops: each on the nearest hit within half a beat ({len(got)} of {len(g)} grid points; the silent beats "
      "dropped, the late hits taken)", sorted(got) == model(g, FPB, H) and all(p in hs or p == 0 for p in got)
      and not any(b * FPB - 64 <= p <= b * FPB + 64 for b in SILENT for p in got)
      and all(any(0 < b * FPB + 3000 - p <= 64 for p in got) for b in LATE), (sorted(got)[:6], model(g, FPB, H)[:6]))
g, got = onto(len(TL), 0, FPB, 0.5)
check(f"1/2 beat chops: the off-beat hits get theirs, half-beat points with no hit near are dropped ({len(got)} of {len(g)})",
      sorted(got) == model(g, FPB / 2, H) and all(any(0 < b * FPB + FPB // 2 - p <= 64 for p in got) for b in OFFB)
      and len(got) == len(H), (len(got), len(H)))
g, got = onto(len(TL), 300, FPB, 1.0)
check(f"a grid 300 frames late: a pickup at 0, every chop just ahead of its hit, not on the grid",
      0 in got and all(p in hs for p in got if p) and not any(p % FPB == 300 for p in got), sorted(got)[:4])

f1, f2 = pick("chop_find", 8, 1), pick("chop_find", 8, 777)
beat_of = lambda p: (p + 64) // FPB
check(f"Find 8: on hits, ascending, at most one per eighth of the track {[beat_of(p) for p in f1]}",
      all(p in hs for p in f1) and f1 == sorted(f1) and len(set(p * 8 // len(TL) for p in f1)) == len(f1)
      and 7 <= len(f1) <= 8, f1)
check(f"... mostly bar starts (they hit 2.25 x harder than the jitter): {sum(beat_of(p) % 4 == 0 and (p + 64) % FPB < 128 for p in f1)} of {len(f1)}",
      sum(beat_of(p) % 4 == 0 and (p + 64) % FPB < 128 for p in f1) >= len(f1) - 3, f1)
check(f"... another roll finds other chops", f2 != f1, (f1, f2))
r1, r2 = pick("chop_random", 16, 5), pick("chop_random", 16, 6)
check(f"Random 16: 16 different hits", len(r1) == 16 and len(set(r1)) == 16 and all(p in hs for p in r1), r1)
check("... another seed, another set", sorted(r1) != sorted(r2), (r1, r2))
check(f"Random 100 on {len(H)} hits: all of them", sorted(pick("chop_random", 100, 9)) == H)

# --- the driver: chop_request -> the detector -> the scan -> slices; chop_poll runs every GUI frame (theme_compose)
MASTER, AREA = 0xC0000000, 0xC0100000
e.uc.mem_map(0xC0000000, 0x200000)
e.uc.mem_write(MASTER, b"\xa5" * 0x94910)
e.uc.mem_write(AREA, b"\xa5" * 0x60000)           # the area as SDRAM garbage: magic-checked, cleared
e.w32(0x38800F70, MASTER)
e.w32(0x38800F74, MASTER ^ 0x5052534D)
e.w32(MASTER + 0x94900, AREA)
CR, CJ, TJ, CLIP = AREA + 0x57428, AREA + 0x53CE8, AREA + 297020, AREA + 28   # offsetof(struct str_bank, ...), STBA
PADE, SRC = 0x24072000, 0x24072800
e.uc.mem_write(PADE, bytes(0x300))
e.w32(PADE + 0x24, SRC)
SETS, EPARAMS = [], []
e.stub(0x08093ECC, lambda: SETS.append((e.arg(0), e.arg(1), e.arg(2))))
e.stub(0x0804C59C, lambda: EPARAMS.append((e.arg(0), e.arg(1), e.arg(2), e.arg(3))))
e.stub(0x080636F0, value=len(TL))
e.stub(0x08063790, value=1)
FETCHES = [0]


def cfetch2():
    l, r, n = e.arg(1), e.arg(2), e.arg(3)
    pos = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    seg = (TL[pos:pos + n] + [0.0] * n)[:n]
    e.uc.mem_write(l, struct.pack(f"<{n}f", *seg))
    e.uc.mem_write(r, struct.pack(f"<{n}f", *seg))
    FETCHES[0] += 1
    e.ret(1)


e.stubs[0x08063608] = cfetch2
e.call("stretch_tick")                            # the area comes up (magic, cleared)
check("the area comes up as STBA (3.5.i layout)", e.r32(AREA) == 0x53544241, hex(e.r32(AREA)))
e.w32(CLIP + 6 * 24, PADE)                        # what setup leaves: pad 6's engine object


def detected(bpm, phase, frate=48000, q=6, ok=True):
    e.w32(TJ + 160, e.r32(TJ + 156))              # served = req
    e.w32(TJ + 4, q)
    e.w32(TJ, 8 if ok else 9)
    e.uc.mem_write(TJ + 148, struct.pack("<ff", bpm, phase))
    e.w32(TJ + 24, frate)


def scan_run():
    while e.r32(CJ) == 1:                         # CHOP_SCAN: the scan's next frames (stretch_tick on the unit)
        e.call("chop_scan_step", CJ, SCR2, count=50_000_000)


def poll1():
    e.call("chop_poll")


def poll():
    """one GUI frame; a scan that it starts runs to the end (audio blocks) and the next frame places"""
    scan_run()
    e.call("chop_poll")
    if cr()["phase"] == 2:                        # CHOP_PH_SCAN
        scan_run()
        e.call("chop_poll")


def cr():
    op, ph, pad_, unit, fail = struct.unpack("<5B", e.uc.mem_read(CR, 5))
    return dict(op=op, phase=ph, pad=pad_, fail=fail)


MSGS.clear()
req0 = e.r32(TJ + 156)
e.call("chop_request", 6, 1, 2, 16)               # Beats, a beat each
check("Beats requested on pad 6: waiting on the tempo, the detector asked for pad 6",
      cr()["phase"] == 1 and e.r32(TJ + 156) == req0 + 1 and e.r32(TJ + 164) == 6, (cr(), e.r32(TJ + 156)))
poll()
check("... nothing placed before the detector answers", lst() == [50, 100, 200] and cr()["phase"] == 1, lst())
detected(120.0, 6000.0)
poll1()
check("... the answer (120 BPM, beat one 6000): the attack scan starts on pad 6's sample, nothing placed yet",
      cr()["phase"] == 2 and e.r32(CJ) == 1 and e.r32(CJ + 4) == 6 and lst() == [50, 100, 200], (cr(), e.r32(CJ)))
scan_run()
poll1()
HD = hits_of(CJ)
want = model(beats(len(TL), 6000, FPB, 1.0), FPB, HD)
check(f"... scan done: the beat grid from 6000 placed on the hits ({len(lst())} slices, every one a hit or the file start)",
      lst() == want and all(p in HD or p == 0 for p in lst()) and cr()["phase"] == 0 and cr()["fail"] == 0, lst()[:5])
check("... beat 50's grid point (6000 after it) takes its hit, not the click 16 dB under it that is nearer (5000 after)",
      any(0 < 50 * FPB - p <= 64 for p in lst()) and not any(0 < CLICK - p <= 64 for p in lst()) and any(0 < CLICK - h <= 64 for h in HD),
      [p for p in lst() if 49 * FPB < p < 52 * FPB])
check("... and the detector's job is taken (idle again)", e.r32(TJ) == 0)

e.call("chop_request", 6, 2, 0, 8)                # Find 8, tempo known, the whole file scanned: no rescan
f0 = FETCHES[0]
check("Find with the tempo known and the file scanned: straight to the picks (no detector, no rescan)",
      cr()["phase"] == 2 and e.r32(CJ) == 2, cr())
SETS.clear(); EPARAMS.clear()
poll()
f1 = lst()
check(f"... 8 Find chops placed, all on hits, none in the silence, nothing read again ({[beat_of(p) for p in f1]})",
      len(f1) == 8 and all(p in HD for p in f1) and FETCHES[0] == f0 and cr()["phase"] == 0, (f1, FETCHES[0] - f0))
check("... and PlayThru on (0xf2 = 1) in the pad's store and to the engine (Find plays on past a chop)",
      (CELL, 0xF2, 1) in SETS and (0x2400A9C0, 0x102, 0xF2, 1) in EPARAMS, (SETS, EPARAMS))
e.call("chop_request", 6, 2, 0, 8)                # roll again
poll()
check(f"a re-roll of Find: another set {[beat_of(p) for p in lst()]}", lst() != f1 and len(lst()) == 8, lst())

e.call("chop_forget", 6)                          # a new sample on pad 6 (chop_header_post)
check("a new sample: the old scan is dropped (it can never be reused for the new file)",
      e.r32(CJ) == 0 and e.r32(CJ + 8) == 0, (e.r32(CJ), e.r32(CJ + 8)))
e.call("chop_request", 6, 2, 0, 8)
check("Find after a new sample: the detector again, not a re-roll", cr()["phase"] == 1 and e.r32(TJ + 164) == 6, cr())
e.call("chop_forget", 5)
check("chop_forget on another pad leaves pad 6's run alone", cr()["phase"] == 1, cr())

e.call("chop_request", 6, 3, 0, 16)               # Random 16, the tempo fails
detected(0.0, 0.0, ok=False)
poll()
check("the detector fails: nothing placed, fail 1", cr()["phase"] == 0 and cr()["fail"] == 1, cr())
e.call("chop_request", 6, 1, 2, 16)               # nobody answers
for _ in range(1801):
    poll1()
check("no answer for ~30 s of GUI frames: gives up, fail 2", cr()["phase"] == 0 and cr()["fail"] == 2, cr())

# --- a long file: grid chops scan only as far as their 128 points; Find later goes on from there
e.call("chop_forget", 6)
e.call("chop_request", 6, 1, 0, 16)               # Beats 1/4: 128 points x 6000 = 768,000 frames of 1,536,000
detected(120.0, 0.0)
poll()
part = e.r32(CJ + J_LEN)
check(f"Beats 1/4 on a long file: the scan stops at frame {part} (past the last of 128 points + half a step), "
      f"{len(lst())} chops", cr()["phase"] == 0 and e.r32(CJ) == 2 and 127 * 6000 + 3000 < part < len(TL) // 2 + 8192
      and lst() == model(beats(len(TL), 0, FPB, 0.25), FPB / 4, hits_of(CJ)), (part, cr()))
e.call("chop_request", 6, 2, 0, 8)                # Find needs the whole file: the same scan goes on
check("... then Find: the scan goes on from there (no detector, not from the start)",
      cr()["phase"] == 2 and e.r32(CJ) == 1 and e.r32(CJ + J_NEXT) >= part - 4096 and e.r32(CJ + J_LEN) == len(TL),
      (cr(), e.r32(CJ), e.r32(CJ + J_NEXT)))
poll()
check(f"... and its hits are the one-pass scan's ({len(hits_of(CJ))})", hits_of(CJ) == H and len(lst()) == 8, len(hits_of(CJ)))

# --- a scan whose audio never arrives gives up (the job's own count), and a slow but moving scan never times out
STALL = [True]
e.stubs[0x08063608] = lambda: (e.ret(0) if STALL[0] else cfetch2())
e.call("chop_forget", 6)
e.call("chop_request", 6, 3, 0, 16)
detected(120.0, 0.0)
poll1()
for _ in range(4100):
    e.call("chop_scan_step", CJ, SCR2)
poll1()
check("the audio never arrives: the scan gives up after 4000 tries, fail 2", cr()["phase"] == 0 and cr()["fail"] == 2, cr())
STALL[0] = False
e.call("chop_forget", 6)
e.call("chop_request", 6, 3, 0, 16)
detected(120.0, 0.0)
poll1()
frames = 0
while e.r32(CJ) == 1 and frames < 3000:          # one audio block a GUI frame: a 32 s file takes 750 frames; here 2250
    if frames % 3 == 0:
        e.call("chop_scan_step", CJ, SCR2, count=50_000_000)
    poll1()
    frames += 1
poll1()
check(f"a scan slower than the ~30 s wait but moving ({frames} GUI frames): not a timeout, 16 chops",
      frames > 1800 and cr()["phase"] == 0 and cr()["fail"] == 0 and len(lst()) == 16, (frames, cr(), len(lst())))
e.stubs[0x08063608] = cfetch2

# --- the Roll row's cue (chop_roll_text; chopmode.c's view tick shows it): dice, Rolling.., the result, a resting die
from unicorn.arm_const import UC_ARM_REG_R0  # noqa: E402
TXT = SCR2 + 0x1800
import re  # noqa: E402
DIE = re.compile(r"^ {0,2}[\[(<][ .:]{3}[\])>] [\[(<][ .:]{3}[\])>]$")


def is_dice(t):
    return bool(DIE.match(t)) and len(t) <= 13


def roll(q=6):
    e.call("chop_roll_text", q, TXT)
    return e.cstr(e.uc.reg_read(UC_ARM_REG_R0))


for _ in range(200):
    poll()                           # whatever the last test left: run out
check("idle: a resting die", roll() == "[:.:]", roll())
e.call("chop_forget", 6)                          # so this run waits on the detector (Rolling..)
e.call("chop_request", 6, 1, 2, 16)               # Beats
seen = []
for _ in range(48):
    seen.append(roll())
    poll()
changes = [i for i in range(1, 48) if seen[i] != seen[i - 1]]
gaps = [b - a for a, b in zip([0] + changes, changes)]
check(f"a turn: two dice tumble ~0.8 s, every frame two dice in <= 13 characters ({seen[0]!r} .. {seen[-1]!r})",
      all(is_dice(t) for t in seen), [t for t in seen if not is_dice(t)])
check(f"... the faces change ~10 times and slow down (gaps {gaps})", len(changes) >= 8 and gaps[-1] > gaps[0], gaps)
check("... they land: square brackets, held for the last frames", seen[-1] == seen[-2] and seen[-1].strip().startswith("["),
      seen[-6:])
check("... another pad's Roll stays at rest", roll(5) == "[:.:]", roll(5))
check("... still waiting on the tempo: Rolling..", roll() == "Rolling..", roll())
check("... the knob formatter's 'any pad' = the run's pad", roll(-2) == "Rolling..", roll(-2))
detected(120.0, 6000.0)
poll()
n = len(lst())
check(f"... done: '{n} chops'", roll() == f"{n} chops", roll())
for _ in range(89):
    poll()
check("... still up just before ~1.5 s", roll() == f"{n} chops", roll())
poll()
check("... then the resting die", roll() == "[:.:]", roll())
e.call("chop_forget", 6)                          # a new sample, so the detector runs (and fails)
e.call("chop_request", 6, 3, 0, 16)               # Random, the tempo fails at once
detected(0.0, 0.0, ok=False)
poll()
check("a failure during the dice: the dice play out first", is_dice(roll()), roll())
for _ in range(48):
    poll()
check("... then 'Fail 1'", roll() == "Fail 1", roll())

# --- the Tempo row (chopmode.c; code in P_SEL_BEATS 0x15e: 0 x1, 1 half, 2 double): detection and a re-tempo
TEMPO = [0]
e.stub(0x08093E9C, lambda: e.ret(TEMPO[0] if e.arg(1) == 0x15E else 0))
for _ in range(200):
    poll()
TEMPO[0] = 2                                      # x2: the detector read the song at half its tempo
SETS.clear()
e.call("chop_forget", 6)                          # a new sample: the detection is redone, and reads the code
e.call("chop_request", 6, 1, 2, 16)               # Beats, a beat each
detected(120.0, 6000.0)                           # 120 detected -> 240 true: a beat = 12000 frames
poll()
p2 = lst()
check(f"Tempo x2: the chops on a 12000-frame grid (true beats): the off-beat hits get chops ({len(p2)})",
      p2 == model(beats(len(TL), 6000, FPB / 2, 1.0), FPB / 2, hits_of(CJ))
      and all(any(0 < b * FPB + FPB // 2 - p <= 64 for p in p2) for b in OFFB), p2[:4])
check("... and Beat Count = the file's beats at the true tempo", (CELL, 0xD2, round(len(TL) / 12000)) in SETS,
      [x for x in SETS if x[1] == 0xD2])
SETS.clear()
TEMPO[0] = 1
f0 = FETCHES[0]
ok = e.call("chop_retempo", 6, 2, 1) is not None and e.uc.reg_read(UC_ARM_REG_R0)
poll()
p3 = lst()
check(f"re-tempo x2 -> 1/2 with the detection in hand: no detector, chops on a 48000 grid ({len(p3)}); the scan (stopped "
      f"at x2's 128th point) only reads the rest ({FETCHES[0] - f0} fetches)",
      ok == 1 and p3 == model(beats(len(TL), 6000, FPB * 2, 1.0), FPB * 2, hits_of(CJ)) and cr()["phase"] == 0
      and 0 < FETCHES[0] - f0 <= 6 and e.r32(CJ + J_LEN) == len(TL), (ok, p3[:4], cr(), FETCHES[0] - f0))
check("... Beat Count follows", (CELL, 0xD2, round(len(TL) / 48000)) in SETS, [x for x in SETS if x[1] == 0xD2])
check("... with the dice cue", is_dice(roll()), roll())
e.call("chop_retempo", 5, 1, 0)
check("re-tempo on a pad with no detection: 0 (the caller detects)", e.uc.reg_read(UC_ARM_REG_R0) == 0)
TEMPO[0] = 0

# --- a Chop change with this file's tempo in hand: no detector (it choked a little mid-playback, glass 10-27)
for _ in range(60):
    poll()
req1 = e.r32(TJ + 156)
f0 = FETCHES[0]
e.call("chop_request", 6, 1, 1, 16)               # Beats 1/2 beat
check("a Chop change (tempo known, the file scanned): straight to the placement (no detector)", cr()["phase"] == 2, cr())
poll()
q3 = lst()
check(f"... placed at once, nothing read again ({len(q3)})",
      e.r32(TJ + 156) == req1 and cr()["phase"] == 0 and FETCHES[0] == f0
      and q3 == model(beats(len(TL), 6000, FPB * 2, 0.5), FPB, hits_of(CJ)), (e.r32(TJ + 156), cr(), q3[:3]))
e.call("chop_request", 6, 3, 0, 8)                # Random on the same scan: no rescan
check("Random after that: the same scan reused", cr()["phase"] == 2 and e.r32(CJ) == 2, (cr(), e.r32(CJ)))
poll()
check(f"... and placed {len(lst())} chops on hits", cr()["phase"] == 0 and len(lst()) == 8 and all(p in hits_of(CJ) for p in lst()),
      lst())

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
