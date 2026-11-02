"""Sequence note conditions A:B under Unicorn.

Real firmware runs for: the sequence player's "does this note play" branch (0x0805d394 onward, with the patched
compare and call in place), up to the point where it commits to play or skip.
Stubbed: rand(), the step-length helper, the list registration.
NOT run: the sequencer itself, so that the loop start time behaves as assumed (a multiple of the pattern length,
counted from when the transport started) is a hardware check.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")

SEQ, PAT = 0x24060000, 0x24062000
PLAY, SKIP, BRANCH = 0x0805D3AC, 0x0805D45A, 0x0805D394
STEP_TICKS = 960                               # one 16th
state = {"rand": 0, "rolled": 0, "hit": None}

e.w32(SEQ + 0xC20, PAT)


def rand():
    state["rolled"] += 1


def step_len():
    e.uc.mem_write(e.arg(0), struct.pack("<q", STEP_TICKS))


def reached(where):
    def f():
        state["hit"] = where
        e.uc.emu_stop()
    return f


e.stubs[0x080C89D4] = lambda: (rand(), e.ret(state["rand"]))
e.stub(0x0805CAC0, step_len)
e.stubs[PLAY] = reached("play")
e.stubs[SKIP] = reached("skip")


def plays(cond, loop=0, steps=16, base=None, rnd=0, vel=100):
    """Run the firmware's own branch for one note event."""
    e.uc.mem_write(STACK, bytes(0x50))
    e.uc.mem_write(STACK + 0x31, bytes([cond]))
    e.uc.mem_write(STACK + 0x42, struct.pack("<H", vel))
    e.w32(PAT + 4, steps)
    e.uc.mem_write(PAT + 0x38, struct.pack("<q", loop * steps * STEP_TICKS if base is None else base))
    e.uc.reg_write(UC_ARM_REG_SP, STACK)
    e.uc.reg_write(UC_ARM_REG_R5, SEQ)
    state.update(rand=rnd, rolled=0, hit=None)
    e.uc.emu_start(BRANCH | 1, 0, count=100_000)
    assert state["hit"], "branch did not reach play or skip"
    return state["hit"] == "play"


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- stock behaviour is unchanged
check("ALWAYS plays without a roll", plays(0) and state["rolled"] == 0)
check("50%: plays when the roll is 10", plays(50, rnd=10) and state["rolled"] == 1)
check("50%: skips when the roll is 80", not plays(50, rnd=80) and state["rolled"] == 1)
check("50%: the roll is taken modulo 100 (roll 30010 plays, 30080 skips)", plays(50, rnd=30010) and not plays(50, rnd=30080))
check("1%: plays on a roll of 0 or 1 only, as stock", plays(1, rnd=1) and not plays(1, rnd=2))
check("99%: always plays, as stock", all(plays(99, rnd=r) for r in (0, 50, 99)))

# --- every A:B, sixteen loops each
conds, v = {}, 100
for b in range(2, 9):
    for a in range(1, b + 1):
        conds[(a, b)] = v
        v += 1
bad = []
for (a, b), value in conds.items():
    got = [plays(value, loop) for loop in range(16)]
    if got != [loop % b == a - 1 for loop in range(16)] or state["rolled"]:
        bad.append((a, b, value, got))
check("all 35 conditions: play exactly on the Ath of every B loops, no random roll", v == 135 and not bad, bad[:2])
pat = "".join("X" if plays(conds[(1, 4)], l) else "." for l in range(8))
check("1:4 over eight loops = X...X...", pat == "X...X...", pat)
pat = "".join("X" if plays(conds[(2, 3)], l) else "." for l in range(9))
check("2:3 over nine loops = .X..X..X.", pat == ".X..X..X.", pat)
pat = "".join("X" if plays(conds[(4, 4)], l) else "." for l in range(8))
check("4:4 over eight loops = ...X...X", pat == "...X...X", pat)
pat = "".join("X" if plays(conds[(8, 8)], l) else "." for l in range(16))
check("8:8 plays on loops 8 and 16 only", pat == "." * 7 + "X" + "." * 7 + "X", pat)

# --- loop number comes from the loop start time and the pattern length
check("64-step pattern: 1:2 follows 64-step loops", [plays(conds[(1, 2)], l, steps=64) for l in range(4)] == [True, False, True, False])
one = 16 * STEP_TICKS
check("loop start a few ticks off the grid still counts as that loop", plays(conds[(2, 2)], base=one + 7) and plays(conds[(2, 2)], base=one - 7) and not plays(conds[(2, 2)], base=7))
check("values past the list (135, 200, 255) play, as on stock", all(plays(c) for c in (135, 200, 255)) and state["rolled"] == 0)
check("unusable loop time: treated as the first loop", plays(conds[(1, 3)], base=-5) and not plays(conds[(2, 3)], base=-5))
check("a note with velocity 0 still gets its condition applied", not plays(conds[(2, 2)], 0, vel=0) and plays(conds[(2, 2)], 1, vel=0))

# --- the PLAY list
e.stubs.pop(PLAY), e.stubs.pop(SKIP)
seen = {}


def register():
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    seen.update(table=e.arg(0), param=e.arg(1), label=e.arg(2), names=e.arg(3), count=e.r32(sp), xml=e.r32(sp + 4))


e.stub(0x0808C0D8, register)
e.w32(STACK, 100)
e.w32(STACK + 4, 0x080CCA88)
e.call("cond_register", 0x24001000, 0x10E, 0x080CCA80, 0x080EB634)
names = [e.cstr(e.r32(seen["names"] + 4 * i)) for i in range(seen["count"])]
check("PLAY list registered with 135 entries, same parameter, label and xml name", (seen["count"], seen["param"], seen["label"], seen["xml"], seen["table"]) == (135, 0x10E, 0x080CCA80, 0x080CCA88, 0x24001000), seen)
check("list order: 1% .. 99%, then ALWAYS in the middle", names[:99] == [f"{i}%" for i in range(1, 100)] and names[99] == "ALWAYS", names[:3] + names[97:100])
check("then 1:2, 2:2, 1:3 ... 8:8, in the order the engine decodes them", names[100:] == [f"{a}:{b}" for (a, b) in conds], names[100:])

# --- piano roll: stored value <-> list position
shown = {}
e.stub(0x080B1084, lambda: shown.update(param=e.arg(0), pos=e.arg(1), knob=e.arg(2)))


def show(cond):
    e.call("cond_show", 0x10E, cond, 0x24063000)
    return shown["pos"]


MSG = 0x24064000
posted = {}
e.stub(0x080AED14, lambda: posted.update(view=e.arg(0), id=e.r16(e.arg(1)), event=e.r32(e.arg(1) + 0xC), field=e.r32(e.arg(1) + 0x10), value=e.r32(e.arg(1) + 0x14)))


def turn_to(pos, field=7, mid=0x16F):
    e.uc.mem_write(MSG, struct.pack("<HHIHHiii", mid, 0, 0, 5, 0, 1234, field, pos))
    e.call("cond_post", 0x24060000, MSG)
    return posted["value"]


check("an ALWAYS note shows at the middle position, named ALWAYS", names[show(0)] == "ALWAYS" and shown["param"] == 0x10E and shown["knob"] == 0x24063000, shown)
check("percent notes show under their own name (1%, 50%, 99%)", [names[show(c)] for c in (1, 50, 99)] == ["1%", "50%", "99%"])
check("A:B notes show under their own name", [names[show(c)] for c in (100, 105, 134)] == ["1:2", "1:4", "8:8"])
check("one step right of ALWAYS stores 1:2; one step left stores 99%", turn_to(100) == 100 and turn_to(98) == 99, (turn_to(100), turn_to(98)))
check("the middle position stores 0 (ALWAYS); far left stores 1%; far right stores 8:8", (turn_to(99), turn_to(0), turn_to(134)) == (0, 1, 134))
check("every position round-trips: knob -> stored value -> knob", all(show(turn_to(p)) == p for p in range(135)))
check("every stored value 0..134 round-trips and keeps its name", all(turn_to(show(c)) == c for c in range(135)))
check("the event id and field pass through untouched", posted["event"] == 1234 and posted["field"] == 7 and posted["id"] == 0x16F, posted)
check("a velocity edit (field 6) is not remapped", turn_to(99, field=6) == 99 and turn_to(5, field=6) == 5)

# --- the real piano roll handlers go through both hooks
VIEW, EVT = 0x24066000, 0x24067000
e.uc.mem_write(EVT, struct.pack("<BBhiiihh", 1, 105, 0, 0, 960, 77, 60, 90))        # a note with cond 1:4
shown.clear()
bound = []
e.stub(0x080B1084, lambda: bound.append((e.arg(0), e.arg(1), e.arg(2))))
e.call(0x080AB004, VIEW, EVT)
check("selecting a 1:4 note: VEL knob gets 90, PLAY knob gets the position named 1:4", bound[0] == (0x10D, 90, VIEW + 0x318) and bound[1][0] == 0x10E and names[bound[1][1]] == "1:4" and bound[1][2] == VIEW + 0x8D8, bound)
e.w32(VIEW + 0xBF8, 77)
e.uc.mem_write(MSG, struct.pack("<HHIHHiHH", 0x3C, 0, 0, 0, 0, POS := 99, 0x10E, 0))
e.call(0x080AABB0, VIEW, MSG)
check("turning the PLAY knob to the middle posts cond 0 for the selected event", (posted["id"], posted["event"], posted["field"], posted["value"]) == (0x16F, 77, 7, 0), posted)
e.uc.mem_write(MSG, struct.pack("<HHIHHiHH", 0x3C, 0, 0, 0, 0, 108, 0x10E, 0))
e.call(0x080AABB0, VIEW, MSG)
check("...and to 4:4 posts 108", posted["value"] == 108, posted)
e.uc.mem_write(MSG, struct.pack("<HHIHHiHH", 0x3C, 0, 0, 0, 0, 64, 0x10D, 0))
e.call(0x080AABB0, VIEW, MSG)
check("the VEL knob still posts its value unchanged", (posted["field"], posted["value"]) == (6, 64), posted)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
