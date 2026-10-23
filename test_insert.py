"""Per-pad insert effects (src/insert.c, insert_dsp.c, insert_thunk.S, master.c's insert page) under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c), the buffer accessors (FUN_0804d8e8, FUN_0804d944), our
thunks entered the way the patched pad process enters them (registers and stack as at the four sites).
The effects: the firmware build of insert_dsp.c is run block by block against the Mac build of the same file
(host/render_insert.py), every model, stereo and mono.
Stubbed and recorded: registration, the store's add, set-screen, the list clear / add, the selected-row lookup, the
stock page builder.
NOT run: the pad process functions around the hooks (that the buffer and flag really are where the thunks read them
is from the disassembly), the screens, the boot-time allocation taking 0x22000 more bytes, CPU on the real chip.
"""
import ctypes
import struct
import sys

import numpy as np
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R10, UC_ARM_REG_R12, UC_ARM_REG_SP)

sys.path.insert(0, "host")
import render_insert as host
from emu import RET, STACK, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
img = open(IMG, "rb").read()
BASE = 0x08040000
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
BLOCK, BANK = 0xC0000000, 0xC0000000 + 0x56800 + 0xB000
PMEM, PCHECK, UI = 0x38800F70, 0x38800F74, 0x38800B1C
APP = 0x24020088
APP_PADS = APP + 0x1840
ARR, PAD, BUF, L, R, GUI = 0x24072000, 0x24068000, 0x24069000, 0x2406A000, 0x2406B000, 0x24100000 - 0x100000
N = 128
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def memory(on=True):
    e.w32(PMEM, BLOCK if on else 0)
    e.w32(PCHECK, (BLOCK ^ 0x5052534D) if on else 0)
    e.uc.mem_write(BANK, bytes(0x22000))


def store(q, **kw):
    """the app's settings store of pad q (row q // 4, col q % 4)"""
    ids = {"ins": 0x1B6, "ph": 0x1B7, "fl": 0x1B8, "rate": 0x1B9, "depth": 0x1BA, "manual": 0x1BB, "fb": 0x1BC,
           "spread": 0x1BD, "mix": 0x1BE,
           "thresh": 0x1C2, "attack": 0x1C3, "hold": 0x1C4, "release": 0x1C5, "floor": 0x1C6, "live": 0x1C7}
    vals = {0x4: 500, 0xDB: 0}
    vals.update({ids[k]: v for k, v in kw.items()})
    rows = sorted(vals.items())
    at = ARR + q * 0x100
    e.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (q // 4) * 0xF0 + (q % 4) * 0x30
    e.w32(s + 4, at)
    e.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def scan():
    for _ in range(16):
        e.call("insert_tick")


def pad(q):
    e.uc.mem_write(PAD, bytes(0xC00))
    e.w32(PAD + 0x18, (q % 4) | (q // 4) << 8)
    return PAD


def buffer(left, right=None):
    e.uc.mem_write(L, np.asarray(left, np.float32).tobytes())
    if right is not None:
        e.uc.mem_write(R, np.asarray(right, np.float32).tobytes())
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R if right is not None else 0, 0,
                                    1 if right is not None else 0))


def audio(n=N):
    return (np.frombuffer(bytes(e.uc.mem_read(L, 4 * n)), np.float32).copy(),
            np.frombuffer(bytes(e.uc.mem_read(R, 4 * n)), np.float32).copy())


def enter(thunk, r4, sp_words=None, regs=None):
    """Run a thunk as the patched code does: bl from a site, r4 = the pad, the caller's frame on the stack."""
    sp = STACK - 0x100
    for off, v in (sp_words or {}).items():
        e.w32(sp + off, v)
    seed = {UC_ARM_REG_R0: 0x11110000, UC_ARM_REG_R1: 0x22220000, UC_ARM_REG_R2: 0x33330000, UC_ARM_REG_R3: 0x44440000,
            UC_ARM_REG_R12: 0x55550000, UC_ARM_REG_R4: r4}
    seed.update(regs or {})
    for reg, v in seed.items():
        e.uc.reg_write(reg, v)
    e.uc.reg_write(UC_ARM_REG_SP, sp)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(e.sym[thunk] | 1, RET, count=20_000_000)
    assert e.uc.reg_read(UC_ARM_REG_PC) == RET
    kept = all(e.uc.reg_read(reg) == seed[reg] for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R12,
                                                           UC_ARM_REG_R4)) and e.uc.reg_read(UC_ARM_REG_SP) == sp
    return e.uc.reg_read(UC_ARM_REG_R3), kept


# ---------------------------------------------------------------- the image
def is_bl(at, name):
    o = at - BASE
    h1, h2 = struct.unpack_from("<HH", img, o)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    imm -= (1 << 25) if s else 0
    return h1 >> 11 == 0b11110 and h2 >> 14 == 3 and (at + 4 + imm) == e.sym[name]


check("the seven hooks: the mix-buffer decision, after-the-voices and the no-voice early return on BOTH pad "
      "classes, plus INFO on the pad screens",
      is_bl(0x080599EC, "insert_buf_a") and is_bl(0x08059A7C, "insert_run_a") and is_bl(0x08059966, "insert_live_a")
      and is_bl(0x08068830, "insert_buf_b") and is_bl(0x0806889C, "insert_run_b") and is_bl(0x08067FD4, "insert_live_b")
      and is_bl(0x080A2FD6, "insert_info_thunk"))
pages = {"Sample": 0x080EFD38, "Multisample": 0x080EFBD0, "Slicer": 0x080EF900, "Clip": 0x080EFA68,
         "Sample (0x4c)": 0x080EF4C8, "Slicer (0x4c)": 0x080EF1F8, "Clip (0x4c)": 0x080EF360}
rows = {k: struct.unpack_from("<4H", img, a - BASE) for k, a in pages.items()}
check("every pad type's Conf list reads Saturation, Fidelity, Insert, Input",
      all(v == (0xDB, 0xF1, 0x1B6, 0x1C7) for v in rows.values()), rows)
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)

# ---------------------------------------------------------------- settings
lists, nums, added = [], [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.call("insert_register", 0x24001000)
check("registered: Insert (Off, Phaser, Flanger, Gate), Input (Off, In 1, In 2, In 1+2), a Model list per effect",
      [(l[0], l[1], l[2]) for l in lists] == [(0x1B6, "Insert:", ["Off", "Phaser", "Flanger", "Gate"]),
                                              (0x1C7, "Input:", ["Off", "In 1", "In 2", "In 1+2"]),
                                              (0x1B7, "Model:", ["Pebble", "Ninety", "Vibe", "Deep", "Steps"]),
                                              (0x1B8, "Model:", ["Electra", "Jet", "Tape", "Metal"])], lists)
check("...the six Phaser / Flanger knobs 0..100 %: Rate, Depth, Manual, Feedback, Spread, Mix (0x1b9 .. 0x1be)",
      [(n[0], n[1], n[2], n[3]) for n in nums[:6]] == [(0x1B9 + i, lab, 0, 1000) for i, lab in
                                                       enumerate(["Rate:", "Depth:", "Manual:", "Feedback:", "Spread:", "Mix:"])], nums[:6])
check("...and the Gate's own five (0x1c2 .. 0x1c6), so each type's page reads the way that type works",
      [(n[0], n[1], n[2], n[3]) for n in nums[6:]] == [(0x1C2 + i, lab, 0, 1000) for i, lab in
                                                       enumerate(["Thresh:", "Attack:", "Hold:", "Release:", "Floor:"])], nums[6:])
check("fifteen distinct xml names, labels short enough for the screen",
      len({l[3] for l in lists} | {n[4] for n in nums}) == 15 and all(len(x[1]) <= 9 for x in lists + nums),
      sorted({l[3] for l in lists} | {n[4] for n in nums}))
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("insert_defaults", 0x24073000)
check("a new pad: Off, the nine shared settings, the Gate's five, Input Off, then the Clip Window's Region Auto, Slip 0, "
      "Loop Len Off and Fit Off (clipwin.c)", added[0] == (0x1B6, 0) and [a[0] for a in added] == list(range(0x1B6, 0x1BF))
      + list(range(0x1C2, 0x1C8)) + [0x1C8, 0x1C9, 0x1CA, 0x1CB] and added[-5] == (0x1C7, 0)
      and added[-4:] == [(0x1C8, 0), (0x1C9, 0), (0x1CA, 0), (0x1CB, 0)], added)
check("the Gate comes up the way it was set on pad 10 of the test unit: Thresh 80 %, Attack 0, Hold 0, Release 20 %, Floor 0",
      [a[1] for a in added if 0x1C2 <= a[0] <= 0x1C6] == [800, 0, 0, 200, 0], added[-6:])

# ---------------------------------------------------------------- the engine's copy of the settings
memory()
for q in range(16):
    store(q)
store(5, ins=1, ph=3, rate=250, depth=800, manual=400, fb=600, spread=1000, mix=500)
store(10, ins=2, fl=1, rate=100, depth=1000, manual=0, fb=1000, spread=0, mix=700)
store(11, ins=7, fl=9)
scan()


SET_SIZE = 48                                     # struct ins_set: type, model, input, pad, then 11 floats


def setting(q):
    t, m = struct.unpack("<BB", e.uc.mem_read(BANK + 8 + q * SET_SIZE, 2))
    return (t, m) + tuple(round(v, 3) for v in struct.unpack("<6f", e.uc.mem_read(BANK + 8 + q * SET_SIZE + 4, 24)))


check("sixteen blocks read all sixteen pads: pad 6 a phaser, pad 11 a flanger, knobs as 0..1",
      setting(5) == (1, 3, 0.25, 0.8, 0.4, 0.6, 1.0, 0.5) and setting(10) == (2, 1, 0.1, 1.0, 0.0, 1.0, 0.0, 0.7), (setting(5), setting(10)))
check("the others are off, and a type past the list counts as off", all(setting(q)[0] == 0 for q in range(16) if q not in (5, 10)))
store(5, ins=1, ph=9)
scan()
check("a model past the list falls back to the first", setting(5)[:2] == (1, 0))
store(5, ins=1, ph=3, rate=250, depth=800, manual=400, fb=600, spread=1000, mix=500)
scan()

# ---------------------------------------------------------------- the Gate's settings and page
store(4, ins=3, thresh=350, attack=120, hold=200, release=400, floor=0, mix=900)
scan()
gs = struct.unpack("<5f", e.uc.mem_read(BANK + 8 + 4 * SET_SIZE + 28, 20))
check("a Gate pad reads its own five knobs, not the Phaser's six",
      setting(4)[0] == 3 and tuple(round(v, 3) for v in gs) == (0.35, 0.12, 0.2, 0.4, 0.0)
      and round(setting(4)[7], 3) == 1.0, (setting(4), gs))   # NOT the shared Mix (0.9 in the store): a gate is all in
check("...and the Gate has no Model of its own, so it reads 0", setting(4)[1] == 0)
# ---------------------------------------------------------------- "take a separate mix buffer?"
for thunk, stage in (("insert_buf_a", 0x560), ("insert_buf_b", 0xB8C)):
    r3, kept = enter(thunk, pad(5))
    check(f"{thunk}: a pad with an insert answers yes (stock's byte is 0); r0-r2, r12, sp untouched", r3 == 1 and kept, (r3, kept))
    r3, kept = enter(thunk, pad(6))
    check(f"{thunk}: a pad without one answers stock's 0", r3 == 0 and kept, (r3, kept))
    p = pad(6)
    e.uc.mem_write(p + stage, b"\x01")
    r3, kept = enter(thunk, p)
    check(f"{thunk}: stock's byte set comes back as it is", r3 == 1 and kept, (r3, kept))
memory(False)
r3, kept = enter("insert_buf_a", pad(5))
check("no memory block: a pad with an insert set is left on the stock path", r3 == 0 and kept)
memory()
for q in range(16):
    store(q)
store(5, ins=1, ph=3, rate=250, depth=800, manual=400, fb=600, spread=1000, mix=500)
store(10, ins=2, fl=1, rate=100, depth=1000, manual=0, fb=1000, spread=0, mix=700)
scan()

# ---------------------------------------------------------------- the effect, through the hooks
rng = np.random.default_rng(3)
noise = (0.5 * rng.uniform(-1, 1, N)).astype(np.float32)
buffer(noise, noise)
p = pad(5)
r3, kept = enter("insert_run_a", p, {0x18: BUF, 0x1C: 1})
l, r = audio()
check("insert_run_a: the pad's own buffer is processed; r3 = stock's byte, everything else as it was",
      r3 == 0 and kept and not np.allclose(l, noise) and not np.allclose(l, r), (r3, kept))
buffer(noise, noise)
r3, kept = enter("insert_run_a", p, {0x18: BUF, 0x1C: 0})
l, r = audio()
check("insert_run_a: voices rendered straight into the output bus (flag 0) are not touched", np.array_equal(l, noise) and np.array_equal(r, noise) and kept)
buffer(noise, noise)
r3, kept = enter("insert_run_a", pad(6), {0x18: BUF, 0x1C: 1})
l, r = audio()
check("insert_run_a: a pad with Insert Off is not touched", np.array_equal(l, noise) and kept)
p = pad(10)
e.uc.mem_write(p + 0xB8C, b"\x01")
buffer(noise, noise)
r3, kept = enter("insert_run_b", p, {0x14: BUF}, {UC_ARM_REG_R10: 0x24077000})
l, r = audio()
check("insert_run_b: the pad's own buffer is processed; r3 = stock's byte (1 here)", r3 == 1 and kept and not np.allclose(l, noise))
buffer(noise, noise)
r3, kept = enter("insert_run_b", pad(10), {0x14: BUF}, {UC_ARM_REG_R10: BUF})
l, r = audio()
check("insert_run_b: the mix buffer being the output bus (sl) is not touched", np.array_equal(l, noise) and kept)

# ---------------------------------------------------------------- live input on a pad (requested 2026-10-10)
# The bus hangs off the ENGINE POINTER the audio task keeps at 0x2400a9c0 + 0x9a74, not off 0x2400a9c0 itself: that
# mistake is what stopped 3.2.e, 3.2.h and 3.2.w booting. The numbers here are the test unit's, read over USB.
ENGINE_PTR, ENGINE = 0x2400A9C0 + 0x9A74, 0x24037038
INBUS, INL, INR = ENGINE + 0x128E0 + 0x1583C, 0x24078000, 0x24079000
WRONG_BUS = 0x2400A9C0 + 0x128E0 + 0x1583C
check("the input bus on the test unit is where stock's own code puts it", INBUS == 0x2405F154)
e.w32(ENGINE_PTR, ENGINE)
e.uc.mem_write(INBUS, struct.pack("<IIIIBB", N, N, INL, INR, 0, 1))
# ...and at the address the first cut read, the words that were really there: a "buffer" whose clear flag is set
# and whose channel pointer is 0xa8be291b. Anything that touches it as a buffer faults.
e.uc.mem_write(WRONG_BUS, struct.pack("<5I", 0xC3EC7401, 0x7CC64835, 0xA8BE291B, 0x5CADE91E, 0x0A682C59))
inl = (0.3 * rng.uniform(-1, 1, N)).astype(np.float32)
inr = (0.3 * rng.uniform(-1, 1, N)).astype(np.float32)
e.uc.mem_write(INL, inl.tobytes())
e.uc.mem_write(INR, inr.tobytes())
memory()
for q in range(16):
    store(q)
store(5, ins=0, live=3)                                       # Input In 1+2, no insert effect
scan()
check("a pad with Input on but Insert Off is still given its own mix buffer", enter("insert_buf_a", pad(5))[0] == 1)
for thunk, cls in (("insert_live_a", "Sample / Multisample"), ("insert_live_b", "Clip / Slicer")):
    check(f"{thunk} ({cls}): a pad carrying the input renders even with no voice sounding (stock's byte is 0)",
          enter(thunk, pad(5)) == (1, True))
    check(f"...and a pad with Input Off is left to stock's early return", enter(thunk, pad(6)) == (0, True))
    p5 = pad(5)
    e.uc.mem_write(p5 + 0x28, b"\x01")
    check("...and stock's own byte, when set, still comes back as it was", enter(thunk, p5)[0] == 1)
zeros = np.zeros(N, np.float32)
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
gl, gr = audio()
check("Input In 1+2: the live input lands in the pad's own mix, both channels",
      np.allclose(gl, inl, atol=1e-6) and np.allclose(gr, inr, atol=1e-6), (gl[:3], inl[:3]))
store(5, ins=0, live=1)
scan()
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
gl, gr = audio()
check("Input In 1: the left input goes to both sides of the pad",
      np.allclose(gl, inl, atol=1e-6) and np.allclose(gr, inl, atol=1e-6))
store(5, ins=0, live=2)
scan()
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
gl, gr = audio()
check("Input In 2: the right input goes to both sides", np.allclose(gl, inr, atol=1e-6) and np.allclose(gr, inr, atol=1e-6))
voices = (0.2 * rng.uniform(-1, 1, N)).astype(np.float32)
store(5, ins=0, live=3)
scan()
buffer(voices, voices)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("the input is ADDED to whatever the pad's voices rendered, not swapped for it",
      np.allclose(audio()[0], voices + inl, atol=1e-6))
store(5, ins=1, ph=0, rate=400, depth=900, manual=500, fb=500, spread=0, mix=500, live=3)
scan()
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
gl, _ = audio()
check("Input plus an insert: the effect runs on the input, so the pad really is a processor for it",
      np.abs(gl).max() > 1e-4 and not np.allclose(gl, inl, atol=1e-4))
store(5, ins=0, live=0)
scan()
buffer(voices, voices)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("Input Off: nothing is added", np.allclose(audio()[0], voices))
# the same thing through the class B path, which is what gets played most
store(5, ins=0, live=3)
scan()
pb = pad(5)
e.uc.mem_write(pb + 0xB8C, b"\x01")
buffer(zeros, zeros)
enter("insert_run_b", pb, {0x14: BUF}, {UC_ARM_REG_R10: 0x24077000})
check("Clip / Slicer: the live input reaches that pad's mix too",
      np.allclose(audio()[0], inl, atol=1e-6) and np.allclose(audio()[1], inr, atol=1e-6))
memory(False)
store(5, ins=0, live=3)
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("no memory block: no input, and nothing crashes", np.allclose(audio()[0], zeros))
memory()
for q in range(16):
    store(q)

# --- what killed the boot, part two: the first blocks after power-on, before insert_tick has been round the pads
for q in range(16):
    store(q)                                                  # every pad's Input is Off, as on the test unit
for what, magic in (("the SDRAM as a power-on leaves it", 0xA5A5A5A5), ("the bank an older build left (magic INS1)", 0x494E5331)):
    e.uc.mem_write(BANK, b"\xa5" * 0x22000)
    e.w32(BANK, magic)
    live = [enter(t, pad(q))[0] for q in range(16) for t in ("insert_live_a", "insert_live_b")]
    own = [enter("insert_buf_a", pad(q))[0] for q in range(16)]
    check(f"BEFORE THE FIRST TICK, on {what}: no pad carries the input and none takes a buffer",
          not any(live) and not any(own), (live, own))
    buffer(voices, voices)
    enter("insert_run_a", pad(3), {0x18: BUF, 0x1C: 1})
    check("...and a pad that renders gets its own voices back untouched", np.allclose(audio()[0], voices))
memory()
store(5, ins=0, live=3)
scan()
for what, words in (("no engine yet (null)", None), ("a pointer that is not RAM", 0x08012345), ("an odd pointer", 0x24037039)):
    e.w32(ENGINE_PTR, words or 0)
    buffer(voices, voices)
    enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
    check(f"Input on, engine pointer = {what}: nothing is added and nothing faults", np.allclose(audio()[0], voices))
e.w32(ENGINE_PTR, ENGINE)
for what, obj in (("a channel pointer that is not RAM", struct.pack("<IIIIBB", N, N, 0xA8BE291B, INR, 0, 1)),
                  ("a length that is not a block", struct.pack("<IIIIBB", 0x7CC64835, 0x7CC64835, INL, INR, 0, 1)),
                  ("a bus marked silent", struct.pack("<IIIIBB", N, N, INL, INR, 1, 1))):
    e.uc.mem_write(INBUS, obj)
    buffer(voices, voices)
    enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
    check(f"Input on, {what}: nothing is added and nothing faults", np.allclose(audio()[0], voices))
e.uc.mem_write(INBUS, struct.pack("<IIIIBB", N, N, INL, 0, 0, 0))
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("a mono input bus: its one channel goes to both sides", np.allclose(audio()[0], inl, atol=1e-6) and np.allclose(audio()[1], inl, atol=1e-6))
e.uc.mem_write(INBUS, struct.pack("<IIIIBB", N, N, INL, INR, 0, 1))
# --- a muted pad carries no input (reported on 3.2.x: "Mute does not silence the line")
MUTED5 = 0x24020088 + 0x8A88 + (5 >> 2) * 0x78 + (5 & 3) * 0x18 + 0xD
store(5, ins=0, live=3)
e.uc.mem_write(MUTED5, b"\x01")
scan()
buffer(voices, voices)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("pad 6 muted with Input on: the input is not added, and the pad is not kept rendering for it",
      np.allclose(audio()[0], voices) and enter("insert_live_a", pad(5))[0] == 0 and enter("insert_live_b", pad(5))[0] == 0)
e.uc.mem_write(MUTED5 + 0x18, b"\x01")                         # its neighbour muted instead
e.uc.mem_write(MUTED5, b"\x00")
scan()
buffer(zeros, zeros)
enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
check("...unmuted again (and the pad beside it muted): the input is back", np.allclose(audio()[0], inl, atol=1e-6)
      and enter("insert_live_a", pad(5))[0] == 1)
e.uc.mem_write(MUTED5 + 0x18, b"\x00")
check("the words at the address the first cut read were never touched",
      bytes(e.uc.mem_read(WRONG_BUS, 20)) == struct.pack("<5I", 0xC3EC7401, 0x7CC64835, 0xA8BE291B, 0x5CADE91E, 0x0A682C59))
memory()
for q in range(16):
    store(q)

# ---------------------------------------------------------------- the firmware's effects = the Mac build's, every model
dll = host.lib()
t = np.arange(N * 40)
src = (0.4 * np.sin(2 * np.pi * 180 * t / 48000) + 0.25 * np.sign(np.sin(2 * np.pi * 997 * t / 48000)) + 0.2 * rng.uniform(-1, 1, len(t))).astype(np.float32)
worst = {}
for kind, models, key in ((1, 5, "ph"), (2, 4, "fl")):
    for m in range(models):
        knobs = dict(rate=700, depth=900, manual=350 + 100 * m, fb=800, spread=400, mix=500)
        memory()
        for q in range(16):
            store(q)
        store(2, ins=kind, **{key: m}, **knobs)
        scan()
        want_l, want_r = host.run(dll, src, kind, m, *(knobs[k] / 1000 for k in ("rate", "depth", "manual", "fb", "spread", "mix")), block=N)
        got_l, got_r, p = [], [], pad(2)
        for at in range(0, len(src), N):
            buffer(src[at:at + N], src[at:at + N])
            enter("insert_run_a", p, {0x18: BUF, 0x1C: 1})
            a, b = audio()
            got_l.append(a)
            got_r.append(b)
        got_l, got_r = np.concatenate(got_l), np.concatenate(got_r)
        err = max(np.abs(got_l - want_l).max(), np.abs(got_r - want_r).max())
        worst[(key, m)] = err
        moved = np.abs(got_l - src).max() > 0.05 and np.abs(got_l - got_r).max() > 0.01
        check(f"{'Phaser' if kind == 1 else 'Flanger'} model {m}: 40 blocks match the Mac build (max difference {err:.1e}), stereo spread audible",
              err < 2e-3 and moved, err)

# mono mix buffer, and a model change clearing the state
memory()
for q in range(16):
    store(q)
store(2, ins=2, fl=0, rate=500, depth=800, manual=500, fb=500, spread=0, mix=500)
scan()
want, _ = host.run(dll, src[:N * 8], 2, 0, 0.5, 0.8, 0.5, 0.5, 0.0, 0.5, block=N, mono=True)
got, p = [], pad(2)
for at in range(0, N * 8, N):
    buffer(src[at:at + N])
    enter("insert_run_a", p, {0x18: BUF, 0x1C: 1})
    got.append(audio()[0])
check("a mono mix buffer: left processed, no right channel read or written", np.abs(np.concatenate(got) - want).max() < 2e-3)
store(2, ins=2, fl=3, rate=500, depth=800, manual=500, fb=500, spread=0, mix=500)
scan()
want, _ = host.run(dll, src[:N], 2, 3, 0.5, 0.8, 0.5, 0.5, 0.0, 0.5, block=N, mono=True)
buffer(src[:N])
enter("insert_run_a", p, {0x18: BUF, 0x1C: 1})
check("changing the Model starts from a clean state (matches a fresh run)", np.abs(audio()[0] - want).max() < 2e-3)

# ---------------------------------------------------------------- the Gate's behaviour, run in the firmware
memory()
for q in range(16):
    store(q)
store(2, ins=3, thresh=300, attack=0, hold=0, release=300, floor=0, mix=1000)
scan()
t2 = np.arange(N * 60)
tone = (0.6 * np.sin(2 * np.pi * 300 * t2 / 48000)).astype(np.float32)
burst = tone.copy()
burst[N * 10:N * 30] *= 0.0005                                  # a long quiet stretch in the middle
out, p2 = [], pad(2)
for at in range(0, len(burst), N):
    buffer(burst[at:at + N], burst[at:at + N])
    enter("insert_run_a", p2, {0x18: BUF, 0x1C: 1})
    out.append(audio()[0])
out = np.concatenate(out)
loud_in, quiet_in = np.abs(out[N * 5:N * 9]).max(), np.abs(out[N * 20:N * 29]).max()
check(f"Gate: the loud part passes ({loud_in:.2f}) and the quiet part is shut off ({quiet_in:.5f})",
      loud_in > 0.5 and quiet_in < 0.01, (loud_in, quiet_in))
check("...and it opens again when the signal comes back", np.abs(out[N * 35:N * 55]).max() > 0.5)
memory()
for q in range(16):
    store(q)
store(2, ins=3, thresh=300, attack=0, hold=0, release=300, floor=500, mix=1000)
scan()
out2 = []
for at in range(0, len(burst), N):
    buffer(burst[at:at + N], burst[at:at + N])
    enter("insert_run_a", p2, {0x18: BUF, 0x1C: 1})
    out2.append(audio()[0])
out2 = np.concatenate(out2)
ratio = np.abs(out2[N * 25:N * 29]).max() / max(np.abs(burst[N * 25:N * 29]).max(), 1e-9)
check(f"Floor 50 %: closed means ducked, not silenced (it lets {ratio:.0%} through)", 0.2 < ratio < 0.9, ratio)
def gate_run(seconds_of_blocks=20, **kv):
    """a fresh Gate pad, fed the loud tone, for a few blocks; returns the last block's peak"""
    memory()
    for q in range(16):
        store(q)
    store(2, ins=3, **kv)
    scan()
    last = None
    for b in range(seconds_of_blocks):
        buffer(tone[b * N:(b + 1) * N], tone[b * N:(b + 1) * N])
        enter("insert_run_a", pad(2), {0x18: BUF, 0x1C: 1})
        last = np.abs(audio()[0]).max()
    return last


lo = gate_run(thresh=0, attack=0, hold=0, release=300, floor=0, mix=1000)
check(f"Thresh at 0 % (about -66 dB): almost anything opens it, so the tone passes ({lo:.2f})", lo > 0.5, lo)
hi = gate_run(thresh=1000, attack=0, hold=0, release=300, floor=0, mix=1000)
check(f"Thresh at 100 % (full scale): a 0.6 tone is not loud enough, so the pad stays shut ({hi:.3f})", hi < 0.1, hi)
dll2 = host.lib()
store(2, ins=3, thresh=300, attack=200, hold=300, release=400, floor=100, mix=800)
scan()
e.uc.mem_write(BANK + 8 + 16 * SET_SIZE, bytes(0x400))          # the states follow the settings; clear ours
want = burst.copy()
state = ctypes.create_string_buffer(16384)
for at in range(0, len(burst) - N + 1, N):
    pk = struct.pack("<BBBB6f5f", 3, 0, 0, 0, 0, 0, 0, 0, 0, 0.8, 0.3, 0.2, 0.3, 0.4, 0.1)
    dll2.ins_render(state, pk, want[at:at + N].ctypes.data_as(host.F), None, N)
check("the Gate is sane end to end (bounded, finite, and it does change the signal)",
      np.isfinite(want).all() and np.abs(want).max() <= np.abs(burst).max() + 1e-6
      and not np.allclose(want, burst), np.abs(want).max())

# cost
# As the firmware has it: cpu_wait initialises the meter's state before any render, so b2_live()'s answer is
# cached. Left uninitialised, every block re-sums bank 2's 12 KB and the figure reads far too high.
e.uc.mem_write(0x2405FFD0, struct.pack("<I", 0x43505534))
e.uc.mem_write(0x2405FFD0 + 35, b"\x01")           # b2chk: bank 2 checked and matching
count = {"n": 0}
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))     # UC_HOOK_CODE
costs = {}
for kind, key, m, name in ((1, "ph", 0, "Pebble"), (1, "ph", 3, "Deep"), (2, "fl", 1, "Jet")):
    store(2, ins=kind, **{key: m}, rate=500, depth=800, manual=500, fb=500, spread=300, mix=500)
    scan()
    buffer(src[:N], src[:N])
    enter("insert_run_a", pad(2), {0x18: BUF, 0x1C: 1})
    buffer(src[:N], src[:N])
    count["n"] = 0
    enter("insert_run_a", pad(2), {0x18: BUF, 0x1C: 1})
    costs[name] = count["n"] / N
e.uc.hook_del(hook)
print("     cost per stereo frame, instructions: " + ", ".join(f"{k} {v:.0f}" for k, v in costs.items()))
check("cost per stereo frame under 400 instructions on the heaviest model", max(costs.values()) < 400, costs)

# ---------------------------------------------------------------- the knob page
calls = []
e.stub(0x0809EAEC, lambda: calls.append(("screen", e.arg(1), e.r16(APP + 0x28))))
e.stub(0x080A4FC2, lambda: calls.append(("clear",)))
e.stub(0x080A5038, lambda: calls.append(("add", e.arg(1), e.arg(2))))
e.stub(0x08098D40, lambda: calls.append(("stock page",)), value=1)
selected = {"id": 0x1B6}
e.stub(0x080B9D20, lambda: None)
e.stubs[0x080B9D20] = lambda: e.ret(selected["id"])
e.uc.mem_map(0x24100000, 0x100000)
GUIOBJ = 0x24100000
e.w32(0x24002E6C, GUIOBJ)
VIEW = GUIOBJ + 0x732D8
e.uc.mem_write(APP + 0x14, struct.pack("<H", 0x0112))            # pad row 1, col 2 = pad 7
e.uc.mem_write(APP + 0x28, struct.pack("<H", 0x0034))            # the FX screen's own cell
e.uc.mem_write(APP + 0x8CC6, b"\x01")
e.uc.mem_write(UI, bytes(4))


def info():
    calls.clear()
    e.uc.reg_write(UC_ARM_REG_R0, APP)
    e.uc.reg_write(UC_ARM_REG_SP, STACK - 0x100)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(e.sym["insert_info_thunk"] | 1, RET, count=1_000_000)
    return e.uc.reg_read(UC_ARM_REG_R3), e.uc.reg_read(UC_ARM_REG_R0)


e.w32(VIEW + 0xF6CC, 4)
r3, r0 = info()
check("INFO on the Insert row of the Conf list: the knob screen opens on that pad's cell, and stock is told 'nothing to do'",
      calls == [("screen", 0x23, 0x0112)] and r3 == 0 and r0 == APP, (calls, r3))
check("...the FX screen's own cell is put back, and the page is remembered for this pad",
      e.r16(APP + 0x28) == 0x0034 and bytes(e.uc.mem_read(UI, 4)) == bytes([3, 1, 0x12, 0x01]), bytes(e.uc.mem_read(UI, 4)).hex())
e.uc.mem_write(UI, bytes(4))
selected["id"] = 0xF1
r3, _ = info()
check("INFO on another row: stock's 'can be modulated' byte, nothing opened", r3 == 1 and not calls and e.r8(UI + 1) == 0)
selected["id"] = 0x1B6
e.w32(VIEW + 0xF6CC, 0)
r3, _ = info()
check("INFO on a knob page (the list widget's stale selection is not asked): stock", r3 == 1 and not calls)
e.w32(VIEW + 0xF6CC, 4)
info()

store(6, ins=1, ph=2, rate=111, depth=222, manual=333, fb=444, spread=555, mix=666)
CELL = 0x24074000
e.uc.mem_write(CELL, struct.pack("<IH", 0, 0x0112))
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("the page for a Phaser: Insert, its Model, Rate, Depth, Manual, Feedback, Spread, Mix, with the pad's values",
      calls == [("clear",), ("add", 0x1B6, 1), ("add", 0x1B7, 2), ("add", 0x1B9, 111), ("add", 0x1BA, 222), ("add", 0x1BB, 333),
                ("add", 0x1BC, 444), ("add", 0x1BD, 555), ("add", 0x1BE, 666)], calls)
store(6, ins=2, fl=3, rate=111, depth=222, manual=333, fb=444, spread=555, mix=666)
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("the page for a Flanger carries the flanger's Model", calls[1:3] == [("add", 0x1B6, 2), ("add", 0x1B8, 3)] and len(calls) == 9, calls)
store(6, ins=3, thresh=350, attack=120, hold=200, release=400, floor=0, mix=900)
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("the Gate's page: Insert, Thresh, Attack, Hold, Release, Floor - no Model, no Rate, and no Mix (Floor does that job)",
      calls == [("clear",), ("add", 0x1B6, 3), ("add", 0x1C2, 350), ("add", 0x1C3, 120), ("add", 0x1C4, 200),
                ("add", 0x1C5, 400), ("add", 0x1C6, 0)], calls)
store(6, ins=0)
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("Insert Off: the page is the one knob", calls == [("clear",), ("add", 0x1B6, 0)], calls)
e.uc.mem_write(CELL, struct.pack("<IH", 0, 0x0034))
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("the knob screen back on a delay / reverb cell: stock's page, and the insert page is forgotten", calls == [("stock page",)] and e.r8(UI + 1) == 0)
info()
e.uc.mem_write(APP + 0x8CA4, bytes([0x23]))
calls.clear()
e.call("master_info_knob", APP)
check("INFO on the insert page: back to the pad's Conf list", calls == [("screen", 0x1C, 0x0034)] and e.r8(UI + 1) == 0 and e.arg(0) == 0x40, calls)
info()
calls.clear()
e.call("master_back", APP, 0x30, 0, 0)
check("BACK on the insert page: back to the pad's Conf list", calls == [("screen", 0x1C, 0x0034)] and e.r8(UI + 1) == 0, calls)
info()
check("the Tools version label is not given a master page title while an insert page is up", e.call("master_title") == [] and e.arg(0) == 0)

# --- a bad bank 2 must BYPASS, not fault. This is 2026-10-10's boot loop as a test.
# Erasing bank 2 under a running 3.2.l pulled ins_render out from under the engine; a saved preset then called
# into 0xff on every boot and the watchdog reset the unit forever. An advisory marker on the version label was no
# use, because the fault happens long before anything reads it. b2_live() has to make it survivable.
import struct as _struct
_saved = bytes(e.uc.mem_read(0x08100000, 0x4000))
e.uc.mem_write(0x08100000, b"\xff" * 0x4000)              # bank 2 as the crash left it
e.uc.mem_write(0x2405FFD0, _struct.pack("<I", 0x43505534))
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")                  # not yet checked, as at a fresh boot
before = bytes(e.uc.mem_read(L, 4 * N))
ok = True
try:
    e.call("insert_process", PAD, BUF, count=20_000_000)
except Exception as exc:
    ok = False
    print(f"     FAULTED: {type(exc).__name__} {exc}")
after = bytes(e.uc.mem_read(L, 4 * N))
check("bank 2 erased: the pad insert bypasses itself instead of calling into 0xff (the boot loop of 2026-10-10)",
      ok and after == before, "faulted" if not ok else "the buffer was touched")
e.uc.mem_write(0x08100000, _saved)
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
