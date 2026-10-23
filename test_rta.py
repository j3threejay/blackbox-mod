"""RTA on the master EQ screen (rta.c hooks, rta_dsp.c FFT + drawing) under Unicorn.

Real firmware runs for: rta_graph_draw / rta_tap / rta_frame / rta_feed and the FFT, the bank 2 pairing check, the
stock buffer accessors. Stubbed: stock's line primitive (records the segments), stock's EQ graph draw (records the
call), the bus lookup.
Checks: a 1 kHz sine peaks in the column the EQ grid puts 1 kHz at, at its level; silence falls off the graph; stock's
curve is drawn after (on top of) the spectrum; nothing without bank 2; the audio side stops when the screen does.
NOT checked: how it looks on the glass (palette index 17 on each theme), the GUI task's real frame rate.
"""
import math
import os
import struct
import sys

from unicorn import UC_HOOK_CODE

os.environ.setdefault("BANK2_NEW", "1")
from emu import Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
for base, size in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0xC0000000, 0x800000), (0x30000000, 0x10000)):
    e.uc.mem_map(base, size)
MEM = 0xC0000000
e.w32(0x38800F70, MEM)                                  # master_block(): Prism's SDRAM block and its check word
e.w32(0x38800F74, MEM ^ 0x5052534D)
RTA = MEM + 0x56800 + 0x2D100
e.call("b2_live", count=50_000_000)
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


GRAPH, DC, OBJ, VT, BUFS, BUF, L, R = 0x30000000, 0x30000100, 0x30000200, 0x30000300, 0x30000400, 0x30000500, 0x30001000, 0x30002000
N = 256
e.uc.mem_write(GRAPH + 4, struct.pack("<4i", 0, 0, 320, 220))
e.uc.mem_write(DC, bytes([0, 1, 0, 0]) + struct.pack("<I", 0xCAFE0000))
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 0))
segs, order = [], []


def line():
    p0 = struct.unpack("<2i", e.uc.mem_read(e.arg(0), 8))
    p1 = struct.unpack("<2i", e.uc.mem_read(e.arg(1), 8))
    segs.append((p0, p1, e.arg(2)))
    order.append("line")


e.stub(0x0808EA7E, line)
e.stub(0x080AA13C, lambda: order.append("stock"))
e.stub(0x0805F37C, value=BUF)


def draw(overlay=1):
    segs.clear()
    order.clear()
    e.uc.mem_write(DC + 1, bytes([overlay]))
    e.call("rta_graph_draw", GRAPH, DC, count=20_000_000)


def feed(src, blocks, silent=False):
    for b in range(blocks):
        x = [src(b * N + i) for i in range(N)]
        e.uc.mem_write(L, struct.pack(f"<{N}f", *x))
        e.uc.mem_write(R, struct.pack(f"<{N}f", *x))
        e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, L, R, int(silent), 1))
        e.call("rta_tap", OBJ, BUFS, count=5_000_000)


def heights():
    """y per column from the drawn segments (y runs up from the graph's bottom edge, as the GUI's does)"""
    col = {}
    for (x0, y0), (x1, y1), _ in segs:
        col[x0], col[x1] = y0, y1
    return col


def db_at(y):
    return -90.0 + y / 219.0 * 84.0


# --- first frame builds the tables and wakes the audio side
draw()
check("the first overlay frame draws stock's curve (after anything of ours)", order and order[-1] == "stock", order[:3])
check("...and the audio side is now fed (alive)", e.r32(RTA + 4) == 48, e.r32(RTA + 4))

# --- a 1 kHz sine at -20 dBFS
amp = 0.1
feed(lambda t: amp * math.sin(2 * math.pi * 1000 * t / 48000), 12)
for _ in range(3):
    draw()
col = heights()
peak_x = max(col, key=lambda x: col[x]) if col else None
want_x = 32 * math.log2(1000 / 20)
check(f"1 kHz peaks at column {peak_x} (the EQ grid puts 1 kHz at {want_x:.1f})", peak_x is not None and abs(peak_x - want_x) <= 1.5,
      peak_x)
if col:
    lvl = db_at(col[peak_x])
    check(f"...at {lvl:.1f} dB for a -20 dBFS sine (tilt is 0 dB at 1 kHz)", abs(lvl + 20) < 1.5, lvl)
    far = max([db_at(y) for x, y in col.items() if abs(x - want_x) > 40], default=-90.0)   # none drawn = on the floor
    check(f"...and the window keeps the rest of the graph low (highest {far:.0f} dB 40 columns away)", far < -60, far)
check("stock's curve and nodes are drawn last, on top of the spectrum", order[-1] == "stock" and "line" in order, order[-3:])
check("the spectrum is drawn in palette index 17", segs and all(c == 17 for _, _, c in segs), {c for _, _, c in segs})

# --- cost
cnt = [0]


def counting(fn):
    cnt[0] = 0
    h = e.uc.hook_add(UC_HOOK_CODE, lambda *_: cnt.__setitem__(0, cnt[0] + 1))
    fn()
    e.uc.hook_del(h)
    return cnt[0]


costs = [counting(draw) for _ in range(3)]
blk = counting(lambda: feed(lambda t: 0.1, 1))
print(f"     GUI: {max(costs):,} instructions on an update frame, {min(costs):,} on the others (incl. 320 line stubs); "
      f"audio: {blk:,} a {N}-frame block = {blk / N:.1f} per frame")
check("the audio side costs under 12 instructions a frame (0.12 %), and only while the EQ screen shows", blk / N < 12, blk / N)

# --- silence: the line falls away and nothing is drawn along the floor
for _ in range(200):
    feed(lambda t: 0.0, 1, silent=True)
    draw()
check(f"after silence the spectrum has fallen off the graph ({len(segs)} segments drawn)", len(segs) == 0, len(segs))

# --- the screen closes: no draws, so the audio side stops within ALIVE blocks
w0 = e.r32(RTA + 8)
feed(lambda t: 0.0, 60)
w1 = e.r32(RTA + 8)
feed(lambda t: 0.0, 10)
check("with the EQ screen not drawing, the audio side stops writing after ~0.25 s", e.r32(RTA + 8) == w1 and w1 != w0,
      (w0, w1, e.r32(RTA + 8)))

# --- the full (non-overlay) pass: only stock
draw(overlay=0)
check("the full pass is stock's alone", order == ["stock"], order)

# --- no bank 2 payload: stock's screen, untouched
e.uc.mem_write(0x2405FFD0 + 35, bytes([2]))            # b2chk = B2_UNPAIRED
draw()
check("without bank 2: no spectrum, stock's curve as before", order == ["stock"], order)
e.uc.mem_write(0x2405FFD0 + 35, bytes([1]))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
