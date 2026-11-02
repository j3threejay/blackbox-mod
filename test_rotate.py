"""Piano roll rotate (Event editor, top-right knob) under Unicorn.

Real firmware runs for: the cell lookup (FUN_08097ce8), the layer read (FUN_08093e9c), the queue post
(FUN_080b5758), and, to prove the list is still one the firmware accepts, the stock list read (FUN_08063d08) and the
stock sorted update (FUN_08063b38) on the rotated list.
Stubbed: the parameter read (FUN_08099504: returns the chosen Step Count / Step Len / Step Mode), the engine's
event command (FUN_0804c798: recorded), the stock note-length handler (recorded).
NOT run: the piano roll view, its message handler and the encoder path (that the hooked call really is the top-right
knob with counts in r1, 400 a detent, clockwise positive), the engine taking a burst of updates while it plays, the
view's reload on message 0x66, how the piano roll draws a note that rings past the loop end.
"""
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)

APP, VIEW = 0x24020088, 0x24050000
ROLL = VIEW + 0x38
HANDLES, POOLOBJ, POOL, PARAMS, EVT = 0x24040000, 0x24041000, 0x24042000, 0x24048000, 0x24049000
ACC = 0x388006F0
SEQ_ID, ROW, COL, LAYER = 0x0112, 1, 2, 2
CELL0 = APP + ROW * 0x370 + COL * 0xB0 + 0x1C00
LIST = CELL0 + LAYER * 0x2C + 0x18
QUEUE = APP + 0x30
STEP_LEN = {"1 bar": 3, "1/4": 6, "1/8": 8, "1/8T": 9, "1/16": 10, "1/16T": 11, "1/32": 12}
TICKS = {3: 3840, 6: 960, 8: 480, 9: 320, 10: 240, 11: 160, 12: 120}
params = {0x86: 16, 0x85: 10, 0x88: 0}
engine, length_calls = [], []


def param_get():
    e.w32(e.arg(3), params.get(e.arg(2), 0))
    e.ret(1)


def engine_event():
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    ev = struct.unpack("<BBHIIIHHI", bytes(e.uc.mem_read(e.arg(2), 0x18)))
    engine.append({"engine": e.arg(0), "seq": e.arg(1), "zero": e.arg(3), "layer": e.r32(sp), "start": ev[3],
                   "length": ev[4], "id": ev[5]})
    e.ret()


e.stubs[0x08099504] = param_get
e.stubs[0x0804C798] = engine_event
e.stub(0x080BACD8, lambda: length_calls.append((e.arg(0), e.arg(1))))


def build(notes, seq_id=SEQ_ID, flags=0):
    """notes: (start, length) in list order; ids 100.., pool slots shuffled so handle != position."""
    engine.clear()
    length_calls.clear()
    e.uc.mem_write(APP, bytes(0x9000))
    e.uc.mem_write(VIEW, bytes(0xC000))
    e.uc.mem_write(POOL, bytes(0x18 * 600))
    slots = list(range(len(notes)))
    random.Random(len(notes)).shuffle(slots)
    for i, (start, length) in enumerate(notes):
        e.uc.mem_write(POOL + 0x18 * slots[i], struct.pack("<BBHIIIHHI", 1, i % 7, 0, start, length, 100 + i,
                                                           36 + i % 24, 90, 0))
        e.uc.mem_write(HANDLES + 2 * i, struct.pack("<H", slots[i] | flags))
    e.uc.mem_write(LIST, struct.pack("<IIIII", HANDLES, len(notes), 0, 0, POOLOBJ))
    e.uc.mem_write(POOLOBJ, struct.pack("<IIHH", POOL, len(notes), len(notes), 600))
    e.uc.mem_write(PARAMS, struct.pack("<HHI", 0xC0, 0, LAYER))            # the layer-0 cell's settings: Seq Layer
    e.uc.mem_write(CELL0 + 4, struct.pack("<IHH", PARAMS, 0, 1))
    e.uc.mem_write(VIEW + 0xB490, struct.pack("<IH", 0x080CFBA4, seq_id))
    e.uc.mem_write(VIEW + 0xB8B2, b"\x01")
    e.uc.mem_write(ACC, struct.pack("<h", 0))


def notes():
    """(start, length, id) in list order."""
    out = []
    for k in range(e.r32(LIST + 4)):
        h = e.r16(HANDLES + 2 * k) & 0x3FFF
        ev = struct.unpack("<BBHIIIHHI", bytes(e.uc.mem_read(POOL + 0x18 * h, 0x18)))
        out.append((ev[3], ev[4], ev[5]))
    return out


def by_id():
    return {n[2]: n[:2] for n in notes()}


def turn(counts):
    e.call("rotate_knob", ROLL, counts)


def model(before, steps, count, unit):
    loop, out = count * unit, {}
    for start, length, nid in before:
        out[nid] = ((start + steps * unit) % loop if start < loop else start, length)
    return out


def is_sorted():
    s = [n[0] for n in notes()]
    return s == sorted(s)


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


BEAT = [(0, 200), (240, 200), (960, 200), (1920, 200), (3600, 200)]         # 16 x 1/16 = 3840 ticks

# --- Event off: stock ---
build(BEAT)
e.uc.mem_write(VIEW + 0xB8B2, b"\x00")
turn(400)
check("Event off: the stock length handler gets the roll and the counts", length_calls == [(ROLL, 400)],
      str(length_calls))
check("Event off: nothing rotated, nothing sent", notes() == [(s, l, 100 + i) for i, (s, l) in enumerate(BEAT)]
      and not engine)

# --- one step right ---
build(BEAT)
before = notes()
turn(399)
check("399 counts: no step yet", notes() == before and not engine and not length_calls)
turn(1)
check("the 400th count: one step right, the last note wraps to the start",
      [n[0] for n in notes()] == [0, 240, 480, 1200, 2160], str(notes()))
check("order: the wrapped note leads, the rest keep their order",
      [n[2] for n in notes()] == [104, 100, 101, 102, 103], str(notes()))
check("lengths untouched", all(n[1] == 200 for n in notes()))
check("Event on: the length handler is not called", not length_calls)
check("every note sent to the engine once, with its new start",
      sorted((c["id"], c["start"]) for c in engine) == sorted((n[2], n[0]) for n in notes()), str(engine))
check("engine command: engine object, packed sequence id, zero, layer",
      all(c["engine"] == 0x2400A9C0 and c["seq"] == (COL | 1 << 16 | ROW << 8) and c["zero"] == 0
          and c["layer"] == LAYER for c in engine), str(engine[:1]))
q = struct.unpack("<HHIHHiii", bytes(e.uc.mem_read(QUEUE, 0x18)))
check("one refresh queued for this sequence", q[0] == 0x66 and q[3] == SEQ_ID and q[5:] == (0, 0, 0)
      and e.r32(QUEUE + 0xC04) == 1, f"{q} count {e.r32(QUEUE + 0xC04)}")
check("preset marked changed", e.r8(APP + 0x8CC4) == 1)
check("list count and play index untouched", e.r32(LIST + 4) == 5 and e.r32(LIST + 8) == 0)

# --- and back ---
turn(-400)
check("one step left again: the sequence is what it was", notes() == before, str(notes()))

# --- left from the start ---
build(BEAT)
turn(-400)
check("one step left: the first note wraps to the last step",
      [n[0] for n in notes()] == [0, 720, 1680, 3360, 3600] and [n[2] for n in notes()] == [101, 102, 103, 104, 100],
      str(notes()))

# --- several steps in one message, a full turn, the remainder ---
build(BEAT)
turn(400 * 5 + 150)
check("five detents in one message = five steps", by_id() == model(before, 5, 16, 240), str(notes()))
check("the 150 counts left over are kept", e.r16(ACC) == 150)
turn(250)
check("...and complete the next step", by_id() == model(before, 6, 16, 240))
build(BEAT)
turn(400 * 16)
check("a whole loop of steps: nothing changes, nothing sent", notes() == before and not engine
      and e.r32(QUEUE + 0xC04) == 0)
build(BEAT)
e.uc.mem_write(ACC, struct.pack("<h", 0x7FFF))
turn(400)
check("accumulator never written: counts start from zero", by_id() == model(before, 1, 16, 240))

# --- units ---
build(BEAT)
params.update({0x85: STEP_LEN["1/8T"], 0x86: 12})
turn(400)
check("Step Len 1/8T: one step is 320 ticks, the loop 12 of them", by_id() == model(before, 1, 12, 320),
      str(notes()))
build([(0, 100), (960, 100), (2880, 100)])
params.update({0x85: STEP_LEN["1/16"], 0x86: 4, 0x88: 1})
turn(400)
check("Step Mode on: one step is 960 whatever Step Len says",
      [n[0] for n in notes()] == [0, 960, 1920] and [n[2] for n in notes()] == [102, 100, 101], str(notes()))
params.update({0x85: 10, 0x86: 16, 0x88: 0})

# --- notes outside the loop, ties, long notes ---
build([(0, 100), (3600, 100), (3840, 100), (5000, 100)])
turn(400)
check("notes at or past the loop end are left where they are, after the others",
      notes() == [(0, 100, 101), (240, 100, 100), (3840, 100, 102), (5000, 100, 103)], str(notes()))
check("...and are not sent to the engine", sorted(c["id"] for c in engine) == [100, 101])
build([(3600, 100), (3600, 200), (3600, 300)])
turn(400)
check("a chord on the last step wraps together, in order", notes() == [(0, 100, 100), (0, 200, 101), (0, 300, 102)],
      str(notes()))
build([(0, 3840), (3360, 960)])
turn(400)
check("a note longer than what is left of the loop keeps its length", notes() == [(240, 3840, 100), (3600, 960, 101)],
      str(notes()))
build([(1000, 100)])
turn(-400 * 3)
check("a single off-grid note moves by whole steps", notes() == [(280, 100, 100)], str(notes()))

# --- nothing to do ---
build([])
turn(400)
check("empty sequence: nothing sent, no refresh", not engine and e.r32(QUEUE + 0xC04) == 0)
build(BEAT, seq_id=0x0145)
turn(400)
check("an id outside the sequence grid is ignored", notes() == before and not engine)
build(BEAT)
params[0x85] = 15
turn(400)
check("a Step Len past the table is ignored", notes() == before and not engine)
params[0x85] = 10

# --- the handles' upper bits, and the stock list code on the result ---
build(BEAT, flags=0x4000)
turn(800)
check("the handles' two upper bits ride along", all(e.r16(HANDLES + 2 * k) & 0xC000 == 0x4000 for k in range(5))
      and by_id() == model(before, 2, 16, 240))
build(BEAT)
turn(400)
got = []
for k in range(6):
    e.call(0x08063D08, LIST, k, EVT)
    if not e.arg(0):
        break
    got.append(struct.unpack("<BBHIIIHHI", bytes(e.uc.mem_read(EVT, 0x18)))[3])
check("the stock list read walks the rotated list in start order", got == [0, 240, 480, 1200, 2160], str(got))
e.uc.mem_write(EVT, struct.pack("<BBHIIIHHI", 1, 0, 0, 3000, 200, 100, 36, 90, 0))
e.call(0x08063B38, LIST, EVT)
check("the stock sorted update still works on it", [(n[0], n[2]) for n in notes()] ==
      [(0, 104), (480, 101), (1200, 102), (2160, 103), (3000, 100)], str(notes()))

# --- random sequences against the model ---
rng, bad = random.Random(7), None
for trial in range(300):
    count = rng.choice([1, 3, 4, 8, 16, 32, 64, 256])
    key = rng.choice(list(STEP_LEN))
    mode = rng.random() < 0.3
    unit = 960 if mode else TICKS[STEP_LEN[key]]
    loop = count * unit
    n = rng.choice([1, 2, 5, 17, 64, 200, 512])
    starts = sorted(rng.choice([rng.randrange(loop), rng.randrange(count) * unit, rng.randrange(loop * 2)])
                    for _ in range(n))
    build([(s, rng.randrange(1, 4000)) for s in starts])
    params.update({0x85: STEP_LEN[key], 0x86: count, 0x88: int(mode)})
    was, total = notes(), 0
    for _ in range(3):
        steps = rng.randrange(-70, 70)
        total += steps
        turn(400 * steps)
        if by_id() != model(was, total, count, unit) or not is_sorted() or e.r32(LIST + 4) != n:
            bad = bad or f"trial {trial}: {n} notes, {count} x {key}, mode {mode}, steps {total}"
    turn(-400 * total)
    if notes() != was and sorted(notes()) != sorted(was):
        bad = bad or f"trial {trial}: not restored"
    if sorted(e.r16(HANDLES + 2 * k) for k in range(n)) != list(range(n)):
        bad = bad or f"trial {trial}: handles are not a permutation"
params.update({0x85: 10, 0x86: 16, 0x88: 0})
check("300 random sequences (1 to 512 notes, every unit, three turns each): model, sorted, restored on the way back",
      bad is None, bad or "")

print(f"\n{fails} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
