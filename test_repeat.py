"""Note repeat (src/repeat.c, its buttons in solo.c, the hooks in patches/solo.py) under Unicorn.

Real firmware runs for: the screen-task hooks (repeat_pad_down / _up), repeat_tick against a fake engine clock, the
recorder hook, the settings lookup (pad Launch Mode), against the patched image.
Stubbed: stock's note-on / note-off (recorded), the controller inbox FUN_080518dc (recorded: cmd, offset, pad),
groove_s2t / groove_t2s / the raw map (a known grid: 120 BPM = 25 samples a tick, and a swing warp in one case).
Checked: with RPT up a tap is stock's; with RPT held a Trigger / Gate pad is the scheduler's (no stock note-on or
note-off), a Toggle pad is stock's; repeats land on the grid at the exact sample offset in the coming block (which
starts at clock + N), with a note-off half a division later; the first hit at once just after a grid point, else on
the next; the swing map is used for straight divisions, the raw map for triplets; releasing the pad or RPT stops it;
the stopped transport runs a free grid from the press; the recorder's tick is the straight tick through the Groove,
stock's raw tick on external clock. The image fits; the hooks are in place.
NOT run: the glass (two fingers: RPT + pads), the real engine clock and player, recording into a real sequence.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0

from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x100000)
e.uc.mem_map(0x30000000, 0x10000)
BLOCK = 0xC0000000
STATE = BLOCK + 0x56800 + 0xB000 + 0x21800
ENGINE, BUFS, OUT = 0x30000000, 0x30004000, 0x30005000
APP, APP_PADS = 0x24020088, 0x24020088 + 0x1840
N = 128
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


e.w32(0x38800F70, BLOCK)
e.w32(0x38800F74, BLOCK ^ 0x5052534D)
e.uc.mem_write(STATE, bytes(0x800))
e.uc.mem_write(APP + 0x8CA4, bytes([2]))               # the Pads screen
img = open(IMG, "rb").read()

# pad stores: Launch Mode per pad (0x93): pad 5 Toggle, the rest Trigger
ARR = 0x30008000
for q in range(16):
    at = ARR + q * 0x10
    e.uc.mem_write(at, struct.pack("<HHi", 0x93, 0, 2 if q == 5 else 0))
    st = APP_PADS + (q // 4) * 0xF0 + (q % 4) * 0x30
    e.w32(st + 4, at)
    e.uc.mem_write(st + 10, struct.pack("<H", 1))

stock = []
e.stub(0x0804C61C, lambda: stock.append(("on", e.arg(1))))
e.stub(0x0804C5D4, lambda: stock.append(("off", e.arg(1))))
inbox = []
e.stub(0x080518DC, lambda: inbox.append(struct.unpack("<B3xIIIIHH", bytes(e.uc.mem_read(e.arg(1), 0x18)))))
grid = {"swing": 0}                                    # extra samples on every odd 16th (240-tick step), straight map


def s2t():
    s = e.arg(2) | (e.arg(3) << 32)
    if s >= 1 << 63:
        s -= 1 << 64
    e.uc.mem_write(e.arg(0), struct.pack("<q", s // 25))
    e.uc.reg_write(UC_ARM_REG_R0, e.arg(0))


def t2s():
    t = struct.unpack("<q", bytes(e.uc.mem_read(e.arg(2), 8)))[0]
    s = t * 25 + (grid["swing"] if (t // 240) % 2 == 1 and t % 240 == 0 else 0)
    e.uc.mem_write(e.arg(0), struct.pack("<q", s))
    e.uc.reg_write(UC_ARM_REG_R0, e.arg(0))


def raw2s():
    t = struct.unpack("<q", bytes(e.uc.mem_read(e.arg(2), 8)))[0]
    e.uc.mem_write(e.arg(0), struct.pack("<q", t * 25))


e.stub(e.sym["groove_s2t"], s2t, value=None)
e.stub(e.sym["groove_t2s"], t2s, value=None)
e.stub(0x0804D798, raw2s)


def clock(sample, playing=1, sync=0, bpm=120.0):
    e.uc.mem_write(ENGINE, struct.pack("<q", sample))
    e.uc.mem_write(ENGINE + 0x18, struct.pack("<f", bpm))
    e.uc.mem_write(ENGINE + 0x38, bytes([playing]))
    e.uc.mem_write(ENGINE + 0x2C68, bytes([sync]))
    e.w32(BUFS + 0xB * 4, N)


def pad(q):
    return (4 << 16) | ((q // 4) << 8) | (q % 4)


def down(q):
    stock.clear()
    e.uc.mem_write(0x2407F000, bytes(4))                # the fifth argument (a5) on the stack
    e.call("repeat_pad_down", 0x24000000, pad(q), 0, 0)
    return list(stock)


def up(q):
    stock.clear()
    e.uc.mem_write(0x2407F000, bytes(4))
    e.call("repeat_pad_up", 0x24000000, pad(q), 0, 0)
    return list(stock)


def run(blocks, start):
    """blocks of N from clock = start; returns [(block, cmd, offset, pad)]"""
    got = []
    for b in range(blocks):
        clock(start + b * N, **run.kw)
        inbox.clear()
        e.call("repeat_tick", ENGINE, BUFS)
        got += [(b, m[0], m[1], m[2]) for m in inbox]
    return got


run.kw = {}

# --- RPT up: stock
check("RPT up: a tap is stock's note-on and note-off", down(0) == [("on", pad(0))] and up(0) == [("off", pad(0))], stock)
check("the division starts at 1/16", e.call("repeat_div_name") is not None and e.cstr(e.uc.reg_read(UC_ARM_REG_R0)) == "1/16")

# --- RPT held, playing, 1/16 = 240 ticks = 6000 samples at 120 BPM
e.call("repeat_hold", 1)
check("RPT held: a Trigger pad's own note-on is NOT sent (the scheduler owns it)", down(3) == [], stock)
check("...a Toggle pad's is (Toggle would play every other repeat)", down(5) == [("on", pad(5))], stock)
start = 240 * 25 * 10 + 3000 - N                        # the coming block starts half way between two 16ths
got = run(160, start)
ons = [(b, off) for b, c, off, p in got if c == 0x42 and p == pad(3)]
offs = [(b, off) for b, c, off, p in got if c == 0x43 and p == pad(3)]
s0 = start + N                                          # the block about to be rendered (after stock's advance)
want = []
t = (s0 // 25 // 240 + 1) * 240
while t * 25 < s0 + 160 * N:
    s = t * 25
    want.append(((s - s0) // N, (s - s0) % N))
    t += 240
check("pressed mid-16th: no hit at once; then one on every 16th, at its exact sample in the block (block starts at clock + N)",
      ons == want and len(want) >= 1, (ons, want))
check("...each with a note-off half a 16th (3000 samples) after", all(((b * N + o) - (ob * N + oo)) == 3000 for (ob, oo), (b, o) in zip(ons, offs)) and len(offs) >= 1,
      (ons, offs))
check("the Toggle pad is not repeated", all(p != pad(5) for _, _, _, p in got))

# at a grid point: the first hit at once
e.uc.mem_write(STATE + 6, struct.pack("<H", 0))         # forget the held pads
e.uc.mem_write(STATE + 0x48, struct.pack("<HH", 0, 0))  # live, off_pending (offsets in struct rpt_state)
down(7)
start = 240 * 25 * 40 + 100 - N                         # just after a 16th
got = run(1, start)
check("pressed just after a grid point: the first hit at once (offset 0)", (0, 0x42, 0, pad(7)) in got, got)
up(7)

# swing: an odd 16th lands where the warp says
grid["swing"] = 1000
down(9)
got = run(300, 240 * 25 * 80 - N)
s0 = 240 * 25 * 80                                      # the first coming block; block b's starts at s0 + b * N
ons = [s0 + b * N + o for b, c, o, p in got if c == 0x42 and p == pad(9)]
check("Swing: every second 16th lands 1000 samples late, the others on the beat (groove_t2s)",
      len(ons) >= 2 and all((x - s0) % 6000 in (0, 1000) for x in ons) and any((x - s0) % 6000 == 1000 for x in ons), [(x - s0) % 6000 for x in ons])
grid["swing"] = 0
up(9)

# triplets: the raw map
for _ in range(2):
    e.call("repeat_next_div")                           # 1/16 -> 1/16T -> 1/32
e.call("repeat_div_name")
check("the division steps 1/16 -> 1/16T -> 1/32", e.cstr(e.uc.reg_read(UC_ARM_REG_R0)) == "1/32")
for _ in range(6):
    e.call("repeat_next_div")                           # around to 1/16T
e.call("repeat_div_name")
name = e.cstr(e.uc.reg_read(UC_ARM_REG_R0))
grid["swing"] = 1000
down(10)
got = run(300, 240 * 25 * 120 - N)
s0 = 240 * 25 * 120
ons = [s0 + b * N + o for b, c, o, p in got if c == 0x42 and p == pad(10)]
check(f"{name}: 160 ticks = 4000 samples apart, never warped (the raw map: triplets are not swung)",
      name == "1/16T" and len(ons) >= 2 and all((ons[k + 1] - ons[k]) == 4000 for k in range(len(ons) - 1)), [x - s0 for x in ons])
grid["swing"] = 0
check("letting go of a pad: its scheduler stops, the stock note-off is not sent twice", up(10) == [], stock)
got = run(4, 240 * 25 * 200 - N)
check("...nothing more is sent for it but its last note-off", all(c == 0x43 for _, c, _, p in got if p == pad(10)), got)

# RPT released while a pad is held: it stops
down(11)
run(2, 240 * 25 * 300 - N)
e.call("repeat_hold", 0)
got = run(40, 240 * 25 * 301 - N)
check("RPT let go while the pad is held: no more repeats", not [g for g in got if g[1] == 0x42], got[:4])
check("...and the pad's release is still not doubled", up(11) == [], stock)

# stopped transport: a free grid from the press
e.call("repeat_hold", 1)
for _ in range(5):
    e.call("repeat_next_div")                           # 1/16T -> 1/32 -> 1/32T -> 1/4 -> 1/8 -> 1/8T ... to 1/4
e.call("repeat_div_name")
name = e.cstr(e.uc.reg_read(UC_ARM_REG_R0))
run.kw = {"playing": 0}
down(12)
got = run(200, 5_000_000 - N)
ons = [b * N + o for b, c, o, p in got if c == 0x42 and p == pad(12)]
period = {"1/4": 24000, "1/8": 12000, "1/8T": 8000}.get(name, 0)
check(f"transport stopped ({name}): the first hit at once, then every {period} samples", period and ons and ons[0] == 0 and
      all(ons[k + 1] - ons[k] == period for k in range(len(ons) - 1)), (name, ons[:4]))
run.kw = {}
up(12)
e.call("repeat_hold", 0)

# off the Pads screen: nothing
e.uc.mem_write(APP + 0x8CA4, bytes([0x30]))
e.call("repeat_hold", 1)
down(13)
got = run(60, 240 * 25 * 500 - N)
check("off the Pads screen: no repeats even with RPT and a pad held", not [g for g in got if g[1] == 0x42], got[:3])
e.uc.mem_write(APP + 0x8CA4, bytes([2]))
up(13)
e.call("repeat_hold", 0)

# recorder
clock(1_234_567)
e.uc.mem_write(ENGINE + 0x30, struct.pack("<q", 999))
e.call("repeat_rec_tick", OUT, ENGINE)
check("recording: the block start's straight tick through the Groove (1234567 / 25)", struct.unpack("<q", bytes(e.uc.mem_read(OUT, 8)))[0] == 1234567 // 25)
clock(1_234_567, sync=1)
e.call("repeat_rec_tick", OUT, ENGINE)
check("...on external clock: stock's raw tick (clock + 0x30)", struct.unpack("<q", bytes(e.uc.mem_read(OUT, 8)))[0] == 999)

# idle cost
count = {"n": 0}
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
clock(10_000_000)
e.call("repeat_tick", ENGINE, BUFS)
e.uc.hook_del(hook)
check(f"idle (nothing held): {count['n']} instructions a block (~{count['n'] / N / 101:.3f} %: the SDRAM block lookup)", count["n"] < 600, count["n"])

# patches


def bl_target(a):
    h1, h2 = struct.unpack_from("<HH", img, a - 0x08040000)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return a + 4 + (off - (1 << 25) if s else off)


check("hooks: pad-down note-on, pad-up note-off, the recorder's tick",
      bl_target(0x080A0A44) == e.sym["repeat_pad_down"] and bl_target(0x080A1A72) == e.sym["repeat_pad_up"]
      and bl_target(0x0805C936) == e.sym["repeat_rec_tick"], [hex(bl_target(a)) for a in (0x080A0A44, 0x080A1A72, 0x0805C936)])
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
