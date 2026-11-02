"""CPU meter (src/cpu.c) under Unicorn.

Real firmware runs for the global cell's info function (FUN_0809ad74, with the patched name copy).
Stubbed: the FreeRTOS queue wait (advances a fake DWT cycle counter), the label setter.
NOT checked: that the DWT counter runs on the unit (the 3.1.F photo showed 16 %, so it does), that Tools refreshes
often enough for the figure to be current, how the middle label draws.
"""
import struct
import sys

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
V = e.cstr(e.sym["fw_version"])                 # our version text, in the cave (NOT stock's string: see below)
e.uc.mem_map(0x38800000, 0x1000)                        # backup SRAM: master.c's page flags (which header title, if any)
e.uc.mem_map(0x58024000, 0x1000)
CYC, STATE = 0xE0001004, 0x2405FFD0
clock = {"busy": 0, "idle": 0, "got": 1}


def cyc():
    return e.r32(CYC) & 0xFFFFFFFF


def receive():
    e.w32(CYC, cyc() + clock["idle"])
    e.calls.append(("wait", e.arg(0), e.arg(2)))
    e.ret(clock["got"])


e.stubs[0x08088756] = receive
labels = []
e.stub(0x080A3DEC, lambda: labels.append((e.arg(0), e.cstr(e.arg(1)))))


def block(busy, idle):
    """One audio period: the task works `busy` cycles, then waits `idle` cycles for the next interrupt."""
    clock["idle"] = idle
    e.w32(CYC, cyc() + busy)
    return e.call("cpu_wait", 0x24001F00, 0x24001F80, 2000, 0)


V = e.cstr(e.sym["fw_version"])
PERIOD = 2_560_000                      # cycles in 5.33 ms at 480 MHz
SPACE, MID = 0x24062174, 0x24062174 - 0xA0
SP = 0x24063000
e.uc.mem_write(SP, b"12.3 GB\0")
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def tools():
    """What a Tools refresh puts in the bar: (free-space label text, middle label text)."""
    labels.clear()
    e.call("cpu_tools", SPACE, SP)
    d = dict(labels)
    return d.get(SPACE), d.get(MID)


e.uc.mem_write(STATE, b"\xa5" * 36)     # RAM as left by an earlier boot
c = block(PERIOD * 3 // 10, PERIOD * 7 // 10)
check("cycle counter switched on (TRCENA, unlock, CYCCNTENA)", e.r32(0xE000EDFC) & (1 << 24) and e.r32(0xE0001FB0) & 0xFFFFFFFF == 0xC5ACCE55 and e.r32(0xE0001000) & 1)
check("the wait itself is passed through unchanged", c[0] == ("wait", 0x24001F00, 2000))


check("before a full second: the middle label is empty, the free-space label as stock sets it", tools() == ("12.3 GB", ""), tools())
for i in range(188):
    block(PERIOD * 3 // 10, PERIOD * 7 // 10)
check("after 188 blocks at 30 % busy, a Tools refresh shows '30/30%' in the middle label", tools() == ("12.3 GB", "30/30%"), tools())
check("the middle label is the one before the free-space label in the bar; the call site is hooked", labels[1][0] == SPACE - 0xA0 and e.uc.mem_read(0x080C52A4, 4) != bytes.fromhex("ddf7a2fd"), labels)
for i in range(188):
    block(PERIOD * 8 // 10 if i == 50 else PERIOD * 4 // 10 - (PERIOD * 4 // 10) // 470, PERIOD * 2 // 10 if i == 50 else PERIOD * 6 // 10)
check("one heavy block in a second: average 40 %, peak 80 %", tools()[1] == "40/80%", tools())
for i in range(188):
    block(PERIOD * 12 // 10, 1000)
check(f"overrun (work longer than a period): reads near or over 100 % ({tools()[1]})", int(tools()[1].split("/")[1].rstrip("%")) > 90, tools())
clock["got"] = 0
block(PERIOD // 10, PERIOD * 50)
clock["got"] = 1
for i in range(189):
    block(PERIOD // 10, PERIOD * 9 // 10)
check("after a wait that timed out, the next second measures cleanly again (10/10%)", tools()[1] == "10/10%", tools())

# --- the figures span the time BETWEEN DRAWS, which is the whole point of the fix
# The bar is only written when Tools is entered, so a per-second average was a stale one-second sample of
# whenever that happened. The readings were taken by leaving Tools, playing, and coming back - that has to
# summarise the whole stretch.
for i in range(188):
    block(PERIOD * 2 // 10, PERIOD * 8 // 10)       # a second at 20 %
for i in range(188):
    block(PERIOD * 6 // 10, PERIOD * 4 // 10)       # then a second at 60 %
t = tools()
check(f"two seconds at 20 % then 60 %, one look: the average spans both and the peak is the worse ({t[1]})",
      t[1] == "40/60%", t)
check("an immediate second look holds the same figures rather than going blank", tools()[1] == "40/60%", tools())
for i in range(188):
    block(PERIOD * 3 // 10, PERIOD * 7 // 10)
check("...and the look after that reports only what happened since (30/30%)", tools()[1] == "30/30%", tools())
for i in range(94):                                  # half a second: less than one report window
    block(PERIOD * 8 // 10, PERIOD * 2 // 10)
check("a look after less than a full second still reports it (80/80%)", tools()[1] == "80/80%", tools())

# --- the dropout signature: the reading must NOT fall when blocks arrive late --------------------------------
# This is the bug the 2026-10-09 dropout exposed. Load was busy / period, both wake to wake, so a stretched period
# DEFLATED the figure: Prism dropping out read 58/78 % while VHS at 85/99 % was clean. Below, the work per block is
# identical in both seconds and only the boundaries slip; under the old formula the second one would have read
# about 48 %, which is the lie. The denominator is the nominal block now, so it holds at 60 % and the late blocks
# are counted separately.
for i in range(188):
    block(PERIOD * 6 // 10, PERIOD * 4 // 10)
check("a clean second at 60 % busy reads 60/60%, nothing late", tools()[1] == "60/60%", tools())
for i in range(188):                    # same busy time; one boundary in four is missed (period 2x nominal)
    block(PERIOD * 6 // 10, PERIOD * 14 // 10 if i % 4 == 3 else PERIOD * 4 // 10)
t = tools()[1]
check(f"one block in four late: still reads 60 % (old formula said 48 %) and counts them ({t})",
      t.startswith("60/60%+") and t.split("+")[1] == "47", t)
check("the draw clears the count, so the next look at the bar is not a stale one", tools()[1] == "60/60%", tools())
for i in range(188):                    # every block late: the count saturates rather than overflowing its byte
    block(PERIOD * 6 // 10, PERIOD * 24 // 10)
check("more late blocks than the count can hold shows +99", tools()[1] == "60/60%+99", tools())
for i in range(188):
    block(PERIOD * 6 // 10, PERIOD * 4 // 10)
check("a second of stretched periods did not move the nominal: back to a clean 60/60%", tools()[1] == "60/60%", tools())
for i in range(170):                    # ends a report 18 blocks before the counter wraps
    block(PERIOD // 4, PERIOD * 3 // 4)
e.w32(CYC, 0xFFFFFFFF - PERIOD * 20)
e.w32(STATE + 4, e.r32(CYC))            # as if the task had just woken: the jump itself is not a measurement
for i in range(206):
    block(PERIOD // 4, PERIOD * 3 // 4)
check("cycle counter wrapping past 2^32 does not disturb the reading (25/25%)", tools()[1] == "25/25%", tools())

# --- the global cell's name: the header of the knob screen, and nothing but the version on its own
APP, ADDR, INFO = 0x24020088, 0x24070000, 0x24071000
e.uc.mem_write(ADDR, struct.pack("<IH", 0, 0x40))
e.uc.mem_write(INFO, b"\xee" * 0x60)
e.w32(APP + 0xE988, 12 * 1024 * 1024)
e.w32(APP + 0xE98C, 0)
e.stub(0x080C89F4, lambda: e.calls.append(("fmt", e.arg(0))))
e.uc.mem_write(0x38800B1C, bytes([0, 0]))
c = e.call(0x0809AD74, APP, ADDR, INFO)
check("global cell info (stock function, patched copy): the name is just the version, no load", e.cstr(INFO) == V, e.cstr(INFO))
check("...and the stock code still formats its size field after it (at +0x40)", ("fmt", INFO + 0x40) in c, c)
STORE, ARR = APP + 0x8C90, 0x24072000


def mfx(v):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x1DB, 0, v))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 1))


got = {}
for page, kind, want in ((0, 1, "Comp"), (1, 1, "VHS"), (1, 2, "Prism 1"), (2, 2, "Prism 2"), (1, 0, "MFX")):
    mfx(kind)
    e.uc.mem_write(0x38800B1C, bytes([page, 1]))
    e.call(0x0809AD74, APP, ADDR, INFO)
    got[want] = e.cstr(INFO)
check("while a master knob page is up the name is its title: Comp, VHS, Prism 1, Prism 2, MFX", all(k == v for k, v in got.items()), got)
check("every title fits the 8 characters the header shows before it wraps", all(len(v) <= 8 for v in got.values()) and len(V) <= 8)
e.uc.mem_write(0x38800B1C, bytes([0, 0]))

e.uc.mem_write(STATE, b"\xa5" * 36)     # fresh boot
e.w32(CYC, 777)
clock["idle"] = 0
for i in range(376):
    e.call("cpu_wait", 0x24001F00, 0x24001F80, 2000, 0)   # cycle counter never moves
check("cycle counter dead: the middle label says '--%' instead of nothing", tools()[1] == "--%", tools())
e.uc.mem_write(STATE + 35, b"\x02")     # bank 2 checked and NOT this image's payload
check("bank 2 not paired: the middle label leads with '!', where every entry to Tools redraws it", tools()[1] == "!--%", tools())
e.uc.mem_write(STATE + 35, b"\x01")
check("...and loses it once bank 2 is paired", tools()[1] == "--%", tools())

# --- stock's own "3.1.9" must stay exactly as it is -----------------------------------------------------------
# Its last character is pooled as the standalone "9", and three tables point at it. Builds up to 3.2.b patched the
# build letter over it, so the naming keyboard's 9 key typed that letter instead (a user reported "n" on the public
# 3.1.n; 3.2.b typed "b"). The version is a string of our own in the cave now, and these guard the mistake.
img = open("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "rb").read()
stock = open("firmware/BLACKBOX-3.1.9.bin", "rb").read()
BASE = 0x08040000
check("stock's \"3.1.9\" at 0x080cf290 is left exactly as it was",
      img[0x080CF290 - BASE:0x080CF296 - BASE] == stock[0x080CF290 - BASE:0x080CF296 - BASE],
      img[0x080CF290 - BASE:0x080CF296 - BASE])
check("...so the character the keyboard shares is still \"9\"", e.cstr(0x080CF294) == "9", e.cstr(0x080CF294))
kbd = [e.cstr(e.r32(0x080F0BA8 - 16 + 4 * i)) for i in range(10)]
check("the naming keyboard's top row still reads 5 6 7 8 9 0 q w e r",
      kbd == ["5", "6", "7", "8", "9", "0", "q", "w", "e", "r"], kbd)
for table in (0x080EAFC4, 0x080EB834):
    vals = [e.cstr(e.r32(table - 16 + 4 * i)) for i in range(6)]
    check(f"the numeric list at {table:#x} still reads 5 6 7 8 9", vals[:5] == ["5", "6", "7", "8", "9"], vals)
check("the four places that show the version point at our string in the cave, not stock's",
      all(e.r32(a) == e.sym["fw_version"] for a in (0x0809AF30, 0x080AEAF4, 0x080C55E8, 0x080C72C8))
      and e.cstr(e.sym["fw_version"]) == V, V)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
