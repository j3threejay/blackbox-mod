"""Sequencer edit fix under Unicorn.

Real firmware runs for: the pattern list's sorted insert / update / remove (FUN_08063b38, FUN_08063938, FUN_080638ac,
FUN_08063c08), and the stock edit method (0x0805c0d8) for comparison.
Stubbed: the clock conversion (returns a chosen "now"), the player itself (recorded).
NOT checked: the engine's real time units and loop start on hardware, and that the UI edit path reaches these methods.
"""
import struct
import sys

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
SEQ, HANDLES, POOLOBJ, POOL, EVT, CLOCK = 0x24040000, 0x24044000, 0x24045000, 0x24046000, 0x24048000, 0x24049000
PAT0 = SEQ + 0x320
LIST = PAT0 + 0xC
clock_now = {"v": 0}
played = []


def clock():
    e.uc.mem_write(e.arg(0), struct.pack("<q", clock_now["v"]))
    e.ret(e.arg(0))


e.stubs[0x08069C94] = clock
e.stub(0x0805D1D8, lambda: played.append((e.arg(0), e.arg(1))))


def build(starts, index, base=0, active=True, stretch=0):
    e.uc.mem_write(SEQ, bytes(0x1000))
    e.uc.mem_write(POOL, bytes(0x18 * 64))
    for i, st in enumerate(starts):
        e.uc.mem_write(POOL + 0x18 * i, struct.pack("<BBHIII", 1, 0, 0, st, 480, 100 + i) + bytes(8))
        e.uc.mem_write(HANDLES + 2 * i, struct.pack("<H", i))
    e.uc.mem_write(LIST, struct.pack("<IIIII", HANDLES, len(starts), index, 0, POOLOBJ))
    e.uc.mem_write(POOLOBJ, struct.pack("<IIHH", POOL, len(starts), len(starts), 64))
    e.uc.mem_write(PAT0 + 0x38, struct.pack("<q", base))
    e.w32(SEQ + 0xC20, PAT0 if active else SEQ + 0x320 + 0x48)
    e.uc.mem_write(SEQ + 0x5E, bytes([stretch]))


def starts():
    n = e.r32(LIST + 4)
    out = []
    for k in range(n):
        h = e.r16(HANDLES + 2 * k) & 0x3FFF
        out.append(e.r32(POOL + 0x18 * h + 4))
    return out


def index():
    return e.r32(LIST + 8)


def play_at(now):
    clock_now["v"] = now
    e.uc.mem_write(CLOCK, struct.pack("<q", 0))
    e.call("seq_play", SEQ, CLOCK, 0, 0)


def add(start, nid=500, fn="seq_set"):
    e.uc.mem_write(EVT, struct.pack("<BBHIII", 1, 0, 0, start, 480, nid) + bytes(8))
    if fn == "stock":
        e.call(0x0805C0D8, SEQ, EVT, 0, 0)
    else:
        e.call("seq_set", SEQ, EVT, 0, 0)


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e.uc.mem_write(0x38800700, b"\xa5" * 0x210)     # backup SRAM holds whatever it held

# notes on beats 1-4 (960 ticks apart); playhead at 1000: beat 1 and 2 played, next = beat 3 (index 2)
build([0, 960, 1920, 2880], index=2)
play_at(1000)
check("the player is still called, with the same sequence and clock", played and played[-1] == (SEQ, CLOCK), played)
add(1500, fn="stock")
check(f"STOCK, for the record: a note added at 1500 (ahead of the playhead) is skipped: index {index()} -> points past it", starts() == [0, 960, 1500, 1920, 2880] and index() == 3, (starts(), index()))

build([0, 960, 1920, 2880], index=2)
play_at(1000)
add(1500)
check("fixed: the note at 1500 is next to play (index 2)", starts() == [0, 960, 1500, 1920, 2880] and index() == 2, (starts(), index()))

build([0, 960, 1920, 2880], index=2)
play_at(1000)
add(500)
check("a note added behind the playhead (500) waits for the next pass", index() == 3 and starts()[1] == 500, (starts(), index()))
build([0, 960, 1920, 2880], index=2)
play_at(1000)
add(980)
check("a note placed just behind the playhead (980, playhead 1000: inside the 240-tick grace) still plays", index() == 2, (starts(), index()))
build([0, 960, 1920, 2880], index=2)
play_at(1300)
add(1000)
check("a note 300 ticks behind the playhead (past the grace) waits for the next pass", index() == 3, (starts(), index()))

build([0, 960, 1920, 2880], index=4)
play_at(3000)
add(3500, fn="stock")
stock_idx = index()
build([0, 960, 1920, 2880], index=4)
play_at(3000)
add(3500)
check(f"a note added after the last one (3500, playhead 3000): stock skips it (index {stock_idx}), fixed plays it (index {index()})", stock_idx == 5 and index() == 4)

build([0, 960, 1920, 2880], index=2)
play_at(1000)
e.uc.mem_write(EVT, struct.pack("<BBHIII", 1, 0, 0, 1500, 480, 100) + bytes(8))   # note id 100 (was at 0) moved to 1500
e.call("seq_set", SEQ, EVT, 0, 0)
check("moving the first note (0 -> 1500): it plays this pass, beat 2 is not replayed", starts() == [960, 1500, 1920, 2880] and index() == 1, (starts(), index()))
build([0, 960, 1920, 2880], index=2)
play_at(1000)
e.uc.mem_write(EVT, struct.pack("<BBHIII", 1, 0, 0, 2000, 480, 103) + bytes(8))   # beat 4 moved to 2000
e.call("seq_set", SEQ, EVT, 0, 0)
check("moving a note that has not played yet keeps it ahead (index stays on beat 3)", starts() == [0, 960, 1920, 2000] and index() == 2, (starts(), index()))

build([0, 960, 1920, 2880], index=2)
play_at(1000)
e.call("seq_del", SEQ, 101, 0)
check("deleting a played note (beat 2): next is still beat 3", starts() == [0, 1920, 2880] and index() == 1, (starts(), index()))
build([0, 960, 1920, 2880], index=2)
play_at(1000)
e.call("seq_del", SEQ, 102, 0)
check("deleting the next note (beat 3): next becomes beat 4", starts() == [0, 960, 2880] and index() == 2, (starts(), index()))

build([0, 960, 1920, 2880], index=2, base=3840)
play_at(3840 + 1000)
add(1500)
check("second pass of the loop (loop start 3840, playhead 4840): same result, relative to the loop start", index() == 2, (starts(), index()))

build([], index=0)
play_at(1000)
add(1500, fn="stock")
check(f"STOCK, empty pattern: the first note added (1500, playhead 1000) is skipped (index {index()})", index() == 1)
build([], index=0)
play_at(1000)
add(1500)
check("fixed, empty pattern: the first note added plays (index 0)", index() == 0 and starts() == [1500])

build([0, 960, 1920, 2880], index=2, active=False)
play_at(1000)
add(1500)
check("editing a pattern that is not playing: stock behaviour (index untouched by the fix)", index() == 3)
build([0, 960, 1920, 2880], index=2, stretch=1)
play_at(1000)
add(1500)
check("time-stretched sequence: stock behaviour", index() == 3)
build([0, 960, 1920, 2880], index=2)
e.uc.mem_write(0x38800700, b"\0" * 4)            # nothing recorded for this sequence yet
add(1500)
check("no playhead recorded yet: stock behaviour", index() == 3)
add_ok = True
build([0, 960], index=0)
play_at(0)
e.call("seq_set", SEQ, EVT, 0, 40)
check("pattern number out of range: ignored, as stock", starts() == [0, 960])

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
