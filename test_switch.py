"""Type switching in the delay slot: the lines cleared over several blocks (3.3.y), with lines of the real sizes.

Every other suite STUBS that call, which is the blind spot that let the Relapse hang through: a stub returns in one
instruction, so no test could ever see what clearing three multi-megabyte lines costs, or that a clear repeats. Here
the firmware's own clear runs against lines the size the test unit really has, and the cost is counted in instructions
and converted at the measured 398.8 MHz against the 2.67 ms audio block.

Real firmware runs for: the line clear, the settings lookup, the buffer pointer / length helpers, the output mix.
Stubbed: the stock delay process, the send gate, the bus lookup.
NOT checked: the GUI task (its page rebuild goes through stock's screen handler, which this harness fakes), task
priorities, and the watchdog - a stall this harness measures in ms is only a hang on hardware if something else
depends on the audio task inside that window.
"""
import struct
import sys

from unicorn import UC_HOOK_CODE

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x50003000, 0x1000)                       # WWDG1: audio_watch re-arms the early wakeup each block
e.uc.mem_map(0xC0000000, 0x800000)                     # SDRAM: the delay's three lines, at their real sizes
e.uc.mem_map(0x30000000, 0x10000)
OBJ, VT, BUFS, CTX, BUS, IN = 0x30000000, 0x30001000, 0x30001100, 0x30001200, 0x30001300, 0x30001400
BUSL, BUSR, INL, INR, ARR = 0x30002000, 0x30002400, 0x30002800, 0x30002C00, 0x30003000
LIVE, STATE, FRZ = 0xC0000000, 0xC0400000, 0xC0500000
APPFX = 0x24020088 + 0x2FC0
N = 128
MHZ, BLOCK_MS = 398.8, 128 / 48.0                      # the measured core clock; a 128-frame block is 2.67 ms

# The line sizes are the ones read off the test unit: LIVE and FREEZE are 4 s of 16-bit stereo, STATE is 2 s of floats.
LINES = ((0x30, LIVE, 192256), (0x4C, STATE, 96256), (0x68, FRZ, 192256))

e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.w32(OBJ + 0x18, 3 << 16 | 0 << 8)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 2))
e.uc.mem_write(OBJ + 0x2C, struct.pack("<f", 0.5))
e.uc.mem_write(OBJ + 0x21F, b"\x01")
for off, ptr, floats in LINES:
    e.w32(OBJ + off, ptr)
    e.w32(OBJ + off + 0x14, floats)
e.w32(BUFS, CTX)
e.uc.mem_write(CTX + 0x18, struct.pack("<f", 120.0))


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
e.stub(0x0804F0D4)
e.stub(0x0804F270, lambda: e.w32(e.arg(2), IN))
e.stub(0x0805F37C, value=BUS)
# NOT a stub: let the firmware's clear run, and only note that it was reached.
e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: calls.append(("clear", e.arg(0) - OBJ)), begin=0x0806AAC0, end=0x0806AAC0)

IDS = {"type": 0x197, "fb": 0x38, "wand": 0x1D1, "random": 0x1D2, "freeze": 0x1D3, "clock": 0x1D4, "width": 0x1D5,
       "duck": 0x1D6, "size": 0x1E3, "recall": 0x1E4, "reach": 0x1E9, "twist": 0x1E6, "tone": 0x1E7, "feed": 0x1E8,
       "mokind": 0x1BF, "morate": 0x1C0, "modepth": 0x1C1, "cfmode": 0x1EC, "cfdensity": 0x1ED, "cfcontour": 0x1EE,
       "cfspace": 0x1EF}
params = {}


def store(**kv):
    params.update(kv)
    data = b"".join(struct.pack("<HHI", IDS[k], 0, v) for k, v in params.items())
    e.uc.mem_write(ARR, data)
    e.w32(APPFX + 4, ARR)
    e.uc.mem_write(APPFX + 10, struct.pack("<H", len(params)))


counting = [False]
count = [0]
e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: count.__setitem__(0, count[0] + 1) if counting[0] else None)


def block(measure=False):
    e.uc.mem_write(INL, struct.pack(f"<{N}f", *([0.05] * N)))
    e.uc.mem_write(INR, struct.pack(f"<{N}f", *([0.05] * N)))
    calls.clear()
    counting[0], count[0] = measure, 0
    e.call("munchi_process", OBJ, BUFS, count=200_000_000)
    counting[0] = False
    return count[0]


def ms(instructions):
    """Instructions -> ms, at ~1.25 cycles per instruction (the clear loop is a 3-instruction store loop)."""
    return instructions * 1.25 / (MHZ * 1000)


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


TYPES = {0: "Delay", 1: "Munchi", 2: "Motion", 3: "Relapse", 4: "Confetti"}
store(fb=500, size=5, recall=400, reach=500, twist=0, tone=300, feed=0, wand=250, random=300, freeze=0, clock=0,
      width=0, duck=0, mokind=1, morate=400, modepth=600, cfmode=0, cfdensity=500, cfcontour=500, cfspace=300)

# Since 3.3.y the slot clears the lines itself, CLR_WORDS a block, and stock's one-shot clear is never called: the
# 4.5 ms of clearing in one 2.67 ms block was the delay Type spike in the profiler reading (10-20).
MODE = 0x38800B14
CLR_EPOCH, CLR_DONE = 0x4D43, 0xFF


def clearing():
    v = e.r32(MODE) & 0xFFFFFFFF
    return v >> 16 == CLR_EPOCH


def settle(limit=40):
    """Blocks until the clear is over and the type has started: (blocks, worst block's instructions, stock clears)."""
    n, worst, stock = 0, 0, 0
    while n < limit:
        c = block(measure=True)
        stock += len([x for x in calls if x[0] == "clear"])
        n += 1
        worst = max(worst, c)
        if not clearing():
            break
    return n, worst, stock


# --- 1. the clear is spread over blocks, each one well inside the block
e.w32(MODE, 0)                                         # MODE: unknown epoch
store(type=1)
settle()                                               # settle on Munchi
store(type=3)
n, worst, stock = settle()
check(f"Munchi -> Relapse: the lines are cleared over {n - 1} blocks, then Relapse starts", 10 <= n - 1 <= 20 and not clearing(),
      (n, hex(e.r32(MODE) & 0xFFFFFFFF)))
print(f"     worst clearing block: {worst:,} instructions = {ms(worst):.2f} ms of work in a {BLOCK_MS:.2f} ms block")
check("no clearing block is more than a fifth of a block's work", ms(worst) < BLOCK_MS / 5, f"{ms(worst):.2f} ms")
check("stock's one-shot clear is never called", stock == 0, stock)
steady = block(measure=True)
check(f"the next block does not clear again ({ms(steady):.2f} ms, {steady:,} instructions)",
      not clearing() and not [c for c in calls if c[0] == "clear"], calls[:5])

# --- 2. every transition: does any pair clear more than once, or clear on every block?
print("\n     from -> to          blocks   worst block      next block")
worst_all = (0, "")
for frm in TYPES:
    for to in TYPES:
        if frm == to:
            continue
        e.w32(MODE, 0)
        store(type=frm)
        settle()
        block()
        store(type=to)
        n, a, stock = settle()
        b = block(measure=True)
        again = clearing() or [c for c in calls if c[0] == "clear"]
        print(f"     {TYPES[frm]:9}-> {TYPES[to]:9} {n:4}      {ms(a):6.2f} ms       {ms(b):6.2f} ms"
              + ("   <-- CLEARS AGAIN" if again else ""))
        check(f"{TYPES[frm]} -> {TYPES[to]}: clears once, then settles", not again and stock == 0 and ms(a) < BLOCK_MS / 5
              and ms(b) < BLOCK_MS, f"{n} blocks, {ms(a):.2f} / {ms(b):.2f} ms, {stock} stock clears")
        if ms(a) > worst_all[0]:
            worst_all = (ms(a), f"{TYPES[frm]} -> {TYPES[to]}")

print(f"\n     worst block of any switch: {worst_all[1]} at {worst_all[0]:.2f} ms")

# --- 3. the clear really does hand the lines over empty, all of every line, and resets their positions
e.w32(MODE, 0)
store(type=1)
settle()
block()
for off, ptr, floats in LINES:
    e.uc.mem_write(ptr, b"\xAA" * (floats * 4))        # Munchi's leftovers, the whole line
    e.uc.mem_write(OBJ + off + 4, struct.pack("<III", 0x1111, 0x2222, 0x3333))
    e.w32(OBJ + off + 0x10, 0x4444)
store(type=3)
settle()
left = sum(bytes(e.uc.mem_read(ptr, floats * 4)).count(0xAA) for off, ptr, floats in LINES)
check("the lines are handed over zeroed, every word of all three, so Relapse never reads Munchi's state", left == 0,
      f"{left} bytes left")
pos = [struct.unpack("<III", e.uc.mem_read(OBJ + off + 4, 12)) for off, ptr, floats in LINES]
check("...and their positions reset as stock's clear does (+4 = +0x10, +8 = +0xc = 0)", all(p == (0x4444, 0, 0) for p in pos), pos)
outside = bytes(e.uc.mem_read(STATE + 96256 * 4, 64)).count(0) + bytes(e.uc.mem_read(FRZ + 192256 * 4, 64)).count(0)

# --- 4. a change in the middle of a clear carries on with it; a clear cut off by a reset finishes on the next boot
e.w32(MODE, 0)
store(type=1)
settle()
store(type=3)
for _ in range(5):
    block()
store(type=4)
n, worst, stock = settle()
check(f"Munchi -> Relapse -> Confetti mid-clear: the clear goes on ({n} more blocks) and Confetti starts",
      not clearing() and e.r32(MODE) & 0xFF == 4 and n < 15, (n, hex(e.r32(MODE) & 0xFFFFFFFF)))
e.w32(MODE, CLR_EPOCH << 16 | 7 << 8 | 3)              # what a reset half way through a clear to Relapse leaves
store(type=3)
n, worst, stock = settle()
check(f"a clear left half done by a reset finishes ({n} blocks), then the type starts", not clearing() and 7 <= n <= 10,
      (n, hex(e.r32(MODE) & 0xFFFFFFFF)))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
