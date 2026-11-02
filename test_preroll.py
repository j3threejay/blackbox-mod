"""Record pre-roll under Unicorn.

Real firmware runs for: the WAV recorder's whole block method (0x0806201c) with its start routine (0x08061c94), the
clock position read (0x08069c38), the 64-bit divide, the settings lookup (FUN_08093e9c), and both patched call sites.
Stubbed: the message queue (feeds the "start recording" message 0x25), the buffer lookups, the input gain and
meters, the outgoing messages (recorded), the file writer (recorded: which block, from which frame, how many), and
the tick -> sample conversion (a fixed tempo: 16 samples a tick, so one 128-frame block is 8 ticks).
NOT checked: that Rec + Play on the unit reaches message 0x25 with the clock already at 0 (read from the code, not
run), the Tools > Rec page showing the new row, the setting surviving a power cycle, and how a take sounds.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_SP

from emu import Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
STORE, ARR = 0x24020088 + 0x8C90, 0x24070000
REC, WRITER, WVT, BUFS, CLOCK, INBUF, OUTBUF, L, R = (0x24060000, 0x24061000, 0x24061100, 0x24050000, 0x24052000,
                                                      0x24053000, 0x24053100, 0x24064000, 0x24066000)
WRITE = 0x08180000               # an empty, mapped address: the file writer's method
N, SPT, BAR = 128, 16, 3840      # frames a block, samples a tick (stub), ticks a bar
PARAM_PREROLL = 0x1B1


def setting(v):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x9C, 0, 77) + struct.pack("<HHI", PARAM_PREROLL, 0, v))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 2))


def pos():
    return struct.unpack("<q", e.uc.mem_read(CLOCK + 0x30, 8))[0]


def q(off):
    return struct.unpack("<q", e.uc.mem_read(REC + off, 8))[0]


inbox, sent, writes, block_no = [], [], [], {"k": 0}


def queue_get():
    i = e.arg(1)
    if i < len(inbox):
        e.uc.mem_write(e.arg(2), inbox[i])
        e.ret(1)
    else:
        e.ret(0)


def sample_of_tick():
    tick = struct.unpack("<q", e.uc.mem_read(e.arg(1), 8))[0]
    e.ret(max(-2**31, min(2**31 - 1, (tick - pos()) * SPT)) & 0xFFFFFFFF)


def write():
    frames = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    writes.append((block_no["k"], (e.uc.reg_read(UC_ARM_REG_R2) - L) // 4, frames))
    e.ret(0)


e.stubs[0x0804F4D4] = queue_get
e.stubs[0x08069C64] = sample_of_tick
e.stubs[WRITE] = write
e.stub(0x0805F390, value=INBUF)
e.stub(0x0805F37C, value=OUTBUF)
e.stub(0x0805F2C8, value=0x24054000)
e.stub(0x0804D880)
e.stub(0x0805FD14)
e.stub(0x0805F9F0)
e.stub(0x08076758)
e.stub(0x08076770, value=0)
e.stub(0x0805F788, value=0)
e.stub(0x0804F504, lambda: sent.append(e.r8(e.arg(1))))
for buf in (INBUF, OUTBUF):
    e.uc.mem_write(buf, struct.pack("<IIIIBB", N, N, L, R, 0, 1))
e.w32(BUFS, CLOCK)
e.w32(WRITER, WVT)
e.w32(WVT, WRITE | 1)


def run(preroll, start_tick, blocks, quant=BAR, length=BAR, playing=True, thresh=False, arm_block=0):
    """Arm at `arm_block`, run `blocks` blocks from `start_tick`. Returns (writes, messages sent, start, stop)."""
    setting(preroll)
    e.uc.mem_write(REC, bytes(0x400))
    e.w32(REC + 0x18, 5)
    e.w32(REC + 0x20, WRITER)
    e.uc.mem_write(REC + 0x38, struct.pack("<qq", quant, length))
    e.uc.mem_write(REC + 0x58, bytes([3, 0, 1]))            # input Resam, monitor off, record screen active
    e.uc.mem_write(REC + 0x60, bytes([thresh]))
    e.uc.mem_write(REC + 0x64, struct.pack("<f", 1.0))
    e.uc.mem_write(CLOCK, bytes(0x200))
    e.uc.mem_write(CLOCK + 0x38, bytes([playing]))
    writes.clear()
    sent.clear()
    armed = None
    for k in range(blocks):
        block_no["k"] = k
        e.uc.mem_write(CLOCK + 0x30, struct.pack("<q", start_tick + (k * N // SPT if playing else 0)))
        inbox[:] = [bytes([0x25]) + bytes(23)] if k == arm_block else []
        e.call(0x0806201C, REC, BUFS)
        if k == arm_block:
            armed = (q(0x28), q(0x30))
    return list(writes), list(sent), armed[0], armed[1]


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def total(w):
    return sum(n for _, _, n in w)


PER_BAR = BAR * SPT // N         # 480 blocks

# --- the call sites and the setting
img = open(IMAGE, "rb").read()


def bl_target(at):
    h1, h2 = struct.unpack_from("<HH", img, at - 0x08040000)
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + (off - (1 << 25) if s else off)


check("the recorder's start call goes to preroll_start", bl_target(0x08062108) == e.sym["preroll_start"])
check("the waiting position read goes to preroll_position", bl_target(0x0806283A) == e.sym["preroll_position"])
check("Tools Rec page: RecToPlay, RecConfig, Lead In, Pre-roll", struct.unpack_from("<5H", img, 0x080EED60 - 0x08040000) == (0x9D, 0xE1, 0xD5, 0x1B1, 0))
lists, added = [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i) & 0xFFFFFFFF) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))], e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4) & 0xFFFFFFFF))))
e.call("preroll_register", 0x24001000)
check("registered: 0x1b1 'Pre-roll:' Off / 1 / 2 / 4 / 8 bars, saved as 'recpreroll'", lists == [(0x1B1, "Pre-roll:", ["Off", "1 bar", "2 bars", "4 bars", "8 bars"], "recpreroll")], lists)
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("preroll_defaults", 0x24001000)
check("default: Off", added == [(0x1B1, 0)], added)
del e.stubs[0x08093EF6], e.stubs[0x0808C0D8]

# --- stock behaviour, for the record (Pre-roll Off): Rec + Play from a stopped clock, Rec Quant 1 bar, Length 1 bar
w0, s0, a0, b0 = run(0, 0, PER_BAR + 4)
check("Off: start 0, stop one bar later", (a0, b0) == (0, BAR), (a0, b0))
check("Off: writing begins in block 1 (the resample bus runs one block behind), from its first frame", w0[0] == (1, 0, N), w0[:2])
check("Off: exactly one bar is written, then the 'done' message (0x29)", total(w0) == BAR * SPT and s0.count(0x29) == 1, (total(w0), s0))

# --- 1, 2, 4, 8 bars
for v, bars in ((1, 1), (2, 2), (3, 4), (4, 8)):
    w, s, a, b = run(v, 0, (bars + 1) * PER_BAR + 4)
    check(f"{bars} bar(s): start {bars} bar(s) in, stop one bar after that", (a, b) == (bars * BAR, (bars + 1) * BAR), (a, b))
    check(f"{bars} bar(s): nothing is written during the pre-roll; writing begins {bars * PER_BAR} blocks later than stock, same frame",
          w and w[0] == (1 + bars * PER_BAR, 0, N), w[:2])
    check(f"{bars} bar(s): still exactly one bar written, one 'started' (0x26), one 'done' (0x29)",
          total(w) == BAR * SPT and s.count(0x26) == 1 and s.count(0x29) == 1, (total(w), s.count(0x26), s.count(0x29)))

# --- armed while the loop is already running, mid-bar (tick 1000 = block 125)
w, s, a, b = run(1, 1000, 3 * PER_BAR, length=2 * BAR)
check("armed mid-bar with 1 bar: start = the next bar line + 1 bar, stop two bars on", (a, b) == (2 * BAR, 4 * BAR), (a, b))
check("armed mid-bar: first write is the block after the one holding tick 7680", w and w[0][0] == (2 * BAR - 1000) * SPT // N + 1, w[:1])

# --- Lead In on: the clock starts four beats before 0
w, s, a, b = run(1, -BAR, 3 * PER_BAR + 4)
check("with Lead In (clock from -1 bar) and 1 bar: start 1 bar in, after the count", (a, b) == (BAR, 2 * BAR), (a, b))
check("with Lead In: writing begins one block after tick 3840, one bar written", w and w[0] == (2 * PER_BAR + 1, 0, N) and total(w) == BAR * SPT, (w[:1], total(w)))

# --- Rec Quant None while playing
w, s, a, b = run(2, 504, 3 * PER_BAR + 80, quant=0)
check("Rec Quant None, playing, 2 bars: start = now + 2 bars", (a, b) == (504 + 2 * BAR, 504 + 3 * BAR), (a, b))
check("Rec Quant None: one bar written after the pre-roll", w and w[0][0] == 2 * PER_BAR + 1 and total(w) == BAR * SPT, (w[:1], total(w)))

# --- Length Custom: no stop time to move
w, s, a, b = run(1, 0, PER_BAR + 40, length=0)
check("Length Custom: start moved, no stop set, still recording at the end", a == BAR and e.r8(REC + 0x4A) == 0 and e.r8(REC + 0x48) == 1 and w[0][0] == PER_BAR + 1, (a, w[:1]))

# --- left alone
wt, st, at, bt = run(4, 1000, 8, thresh=True)
check("RecThresh on: start is the position at arming, no pre-roll", (at, bt) == (1000, 1000 + BAR), (at, bt))
ws, ss, as_, bs = run(4, 0, 8, quant=0, playing=False)
wn, sn, an, bn = run(0, 0, 8, quant=0, playing=False)
check("clock stopped + Rec Quant None: records at once exactly as with Off", ws == wn and ws[0] == (0, 0, N) and (as_, bs) == (an, bn), (ws[:1], wn[:1]))
wq, sq, aq, bq = run(2, 0, 8, playing=False)
check("clock stopped + Rec Quant 1 bar: waits (as stock does) with start 2 bars in", wq == [] and (aq, bq) == (2 * BAR, 3 * BAR), (wq, aq, bq))

# --- the position read
OUT = 0x24058000
e.uc.mem_write(CLOCK + 0x30, struct.pack("<q", 123456))
setting(0)
e.call("preroll_position", OUT, CLOCK)
check("Off: the waiting position read is stock's", struct.unpack("<q", e.uc.mem_read(OUT, 8))[0] == 123456)
setting(3)
e.call("preroll_position", OUT, CLOCK)
check("a pre-roll selected: that read reports a negative position (low word kept)", struct.unpack("<Ii", e.uc.mem_read(OUT, 8)) == (123456, -1))
setting(9)
e.call("preroll_position", OUT, CLOCK)
check("a value outside the list counts as Off", struct.unpack("<q", e.uc.mem_read(OUT, 8))[0] == 123456)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
