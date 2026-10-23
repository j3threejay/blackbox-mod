"""Live mixer meters (src/meter.c, meter_thunk.S) under Unicorn.

Real firmware runs for: meter_add (the thunk, into a stubbed FUN_0804da6c), meter_peak, meter_tick, meter_alive /
insert_on, meter_view_tick, meter_view_draw, against the patched image.
Stubbed: stock's Mixer tick FUN_080b6600 and draw FUN_080aeaf8 (recorded: still called first), the fill
FUN_0808ea22 (recorded: the strips), the bus add FUN_0804da6c (recorded: still reached with the original r0 / r1).
Checked: the peak of a pad's post-fader buffer lands on that pad (mono and stereo; silent / foreign / column-4 pads
ignored); the add into the bus still happens with the same arguments; nothing is measured off the Mixer, and the
Mixer's tick turns it on; insert_on forces own buffers only while the Mixer shows; peaks fall; heights in 1.5 dB
pixels and the green / yellow / red split; the hold line; the overlay redraw is asked for only on a change; nothing is
drawn on the full pass, on the Mute / Solo screen or on an empty pad; the four patches are in the image.
NOT run: the engine's pad render (that 0x0805aa12 / 0x08068c0e really carry the post-fader mix), the GUI on the
glass (strip position, frame rate, overlay redraw cost), the CPU on the unit with 16 pads.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
fw = open(IMG, "rb").read()
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
BLOCK = 0xC0000000
STATE = BLOCK + 0x56800 + 0x7000 + 0x3760
PAD, BUF, L, R, BUS, VIEW, FLAGS, DC = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24040000, 0x24065000, 0x24065100
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


e.w32(0x38800F70, BLOCK)
e.w32(0x38800F74, BLOCK ^ 0x5052534D)
e.uc.mem_write(STATE, bytes(0x90))
log = []
e.stub(0x0804DA6C, lambda: log.append(("add", e.arg(0), e.arg(1))))
e.stub(0x080B6600, lambda: log.append(("tick", e.arg(0), e.arg(1))))
e.stub(0x080AEAF8, lambda: log.append(("draw", e.arg(0), e.arg(1))))
fills = []
e.stub(0x0808EA22, lambda: fills.append((tuple(struct.unpack("<4i", bytes(e.uc.mem_read(e.arg(0), 16)))), e.arg(1))))


def peak(q):
    return struct.unpack("<f", bytes(e.uc.mem_read(STATE + 8 + 4 * q, 4)))[0]


def alive():
    return e.r32(STATE + 4)


def pad(col, row, bank=0):
    e.w32(PAD + 0x18, col | row << 8 | bank << 16)


def buffer(l, r=None, silent=0, n=128):
    e.uc.mem_write(L, struct.pack(f"<{n}f", *l))
    if r:
        e.uc.mem_write(R, struct.pack(f"<{n}f", *r))
    e.uc.mem_write(BUF, struct.pack("<iiII", n, 0, L, R) + bytes([silent, 1 if r else 0, 0, 0]))


def add():
    from unicorn.arm_const import UC_ARM_REG_R4
    e.uc.reg_write(UC_ARM_REG_R4, PAD)
    log.clear()
    e.call("meter_add", BUS, BUF)


# off the Mixer: nothing measured, the add still happens
pad(1, 0)
buffer([0.5] * 128)
add()
check("off the Mixer: no peak taken, and the pad still goes into its bus with the same arguments",
      peak(1) == 0.0 and log == [("add", BUS, BUF)], (peak(1), log))
e.call("meter_alive")
check("off the Mixer: insert_on's extra answer is no", e.uc.reg_read(UC_ARM_REG_R0) == 0)

# the Mixer's tick: stock first, then alive
log.clear()
e.uc.mem_write(VIEW, bytes(0x4000))
e.call("meter_view_tick", VIEW, FLAGS)
check("Mixer tick: stock's tick runs first with the same arguments, then the meters are alive (8 blocks)",
      log[:1] == [("tick", VIEW, FLAGS)] and alive() == 8, (log, alive()))
e.call("meter_alive")
check("on the Mixer: insert_on's extra answer is yes", e.uc.reg_read(UC_ARM_REG_R0) == 1)

# peaks
pad(2, 1)
buffer([0.25 * ((-1) ** i) for i in range(128)])
add()
check("mono pad (row 1, col 2): peak 0.25 on pad 6", abs(peak(6) - 0.25) < 1e-6, peak(6))
pad(3, 3)
buffer([0.1] * 128, [-0.7] + [0.0] * 127)
add()
check("stereo pad (row 3, col 3): the louder channel's peak, 0.7, on pad 15", abs(peak(15) - 0.7) < 1e-6, peak(15))
for what, setup in (("a silent buffer", lambda: (pad(0, 2), buffer([0.9] * 128, silent=1))),
                    ("a pad of another bank", lambda: (pad(0, 2, bank=1), buffer([0.9] * 128))),
                    ("column 4 (not a pad cell)", lambda: (pad(4, 2), buffer([0.9] * 128)))):
    setup()
    add()
    check(f"{what}: no peak", peak(8) == 0.0 and log == [("add", BUS, BUF)], (peak(8), log))

# fall
before = peak(15)
for _ in range(375):
    e.call("meter_tick")
after = peak(15)
db = 20 * __import__("math").log10(after / before)
check(f"peaks fall about 20 dB a second ({db:.1f} dB over 375 blocks) and alive counts down to 0", -24 < db < -16 and alive() == 0, (db, alive()))


# GUI: heights, colours, hold, redraw requests
def cells(empty=(), hidden=()):
    e.uc.mem_write(VIEW, bytes(0x4000))
    for row in range(4):
        for col in range(4):
            c = VIEW + 0x3AC + row * 0x680 + col * 0x1A0
            e.uc.mem_write(c + 4, struct.pack("<4i", 0x20 + col * 0x40, 1 + row * 0x37, 0x3F, 0x36))
            e.uc.mem_write(c + 0x38, struct.pack("<H", row << 4 | col))
            e.uc.mem_write(c + 0x188, bytes([0 if (row, col) in empty else 1]))
            e.uc.mem_write(c + 0x30, bytes([1 if (row, col) in hidden else 0]))


def set_peaks(d):
    for q in range(16):
        e.uc.mem_write(STATE + 8 + 4 * q, struct.pack("<f", d.get(q, 0.0)))


def frame(n=2):
    req = 0
    for _ in range(n):
        e.uc.mem_write(FLAGS, b"\0\0")
        e.call("meter_view_tick", VIEW, FLAGS)
        req |= e.r8(FLAGS + 1)
    return req


def heights():
    return list(bytes(e.uc.mem_read(STATE + 8 + 64, 16)))


cells(empty={(1, 1)})
set_peaks({0: 1.0, 1: 0.5, 2: 0.25, 3: 0.0})
req = frame()
h = heights()
check(f"heights in 1.5 dB pixels: 0 dBFS = 34, -6 dB = {h[1]}, -12 dB = {h[2]}, silence = 0",
      h[0] == 34 and h[1] == 29 and h[2] == 25 and h[3] == 0 and req == 1, (h[:4], req))
check("unchanged levels: no redraw asked", frame() == 0)
set_peaks({0: 1.0, 1: 0.5, 2: 0.25, 3: 0.001})
check("a level moving below the floor (-60 dB, the meter shows -51 .. 0): nothing visible, no redraw", frame() == 0)
set_peaks({0: 1.0, 1: 0.5, 2: 0.25, 3: 0.1})
check("a level moving into view (-20 dB): the overlay redraw is asked for", frame() == 1)


def draw(full=0, overlay=1, mute=0):
    fills.clear()
    e.uc.mem_write(VIEW + 0x1E40, bytes([mute]))
    e.uc.mem_write(DC, bytes([full, overlay, 0, 0]) + struct.pack("<I", 0x24066000))
    log.clear()
    e.call("meter_view_draw", VIEW, DC)
    return list(fills)


f = draw()
p0 = [x for x in f if x[0][0] == 0x20 + 57 and x[0][1] >= 1 + 15 and x[0][1] < 1 + 55]
check("stock's draw runs first", log[:1] == [("draw", VIEW, DC)], log)
check("pad 1 at 0 dBFS: green 26 px, yellow 6, red 2, in its cell's strip (x + 57, from y + 15, 4 px wide)",
      sorted(p0) == sorted([((0x20 + 57, 16, 4, 26), 11), ((0x20 + 57, 16 + 26, 4, 6), 20), ((0x20 + 57, 16 + 32, 4, 2), 12)]), p0)
check("an empty pad (row 1, col 1) gets no strip", not [x for x in f if x[0][0] == 0x20 + 0x40 + 57 and 56 <= x[0][1] < 111], f)
check("nothing on the full pass", draw(full=1, overlay=0) == [])
check("nothing on the Mute / Solo screen", draw(mute=1) == [])

set_peaks({2: 0.25})
frame()
set_peaks({2: 0.05})
frame()
f = draw()
hold = [x for x in f if x[0][0] == 0x20 + 2 * 0x40 + 57 and x[0][3] == 1]
check("the level dropped: a 1 px hold line stays at the old height (its top pixel, 24: green)",
      hold == [((0x20 + 2 * 0x40 + 57, 1 + 15 + 24, 4, 1), 11)], hold)
for _ in range(40):
    frame()
holds = list(bytes(e.uc.mem_read(STATE + 8 + 64 + 16, 16)))
check("after ~1 s the hold line starts to fall", holds[2] < 25, holds[:4])

# the patches in the image
def bl_target(at):
    h1, h2 = struct.unpack_from("<HH", fw, at - 0x08040000)
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + off - (1 << 25 if s else 0)


check("both pad classes' bus adds go through meter_add",
      all(bl_target(a) == e.sym["meter_add"] & ~1 for a in (0x0805AA12, 0x08068C0E)))
vt = struct.unpack_from("<2I", fw, 0x080F0F10 - 0x08040000)
check("Mixer vtable: tick and draw are ours", vt == ((e.sym["meter_view_tick"] | 1), (e.sym["meter_view_draw"] | 1)), [hex(x) for x in vt])

# cost on the audio thread: one stereo pad's buffer (128 frames), Mixer showing
from unicorn import UC_HOOK_CODE
e.call("meter_view_tick", VIEW, FLAGS)
pad(1, 1)
buffer([0.3] * 128, [0.2] * 128)
cnt = [0]
from unicorn.arm_const import UC_ARM_REG_R4
e.uc.reg_write(UC_ARM_REG_R4, PAD)
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
e.call("meter_add", BUS, BUF)
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions for one stereo pad's 128-frame block = {cnt[0] / 128:.1f} per frame per pad "
      f"= {cnt[0] / 128 / 101.25:.2f} % (16 pads: {16 * cnt[0] / 128 / 101.25:.1f} %), plus stock's own-buffer path")
print(f"{fails} failed")
sys.exit(1 if fails else 0)
