"""Keys screen chords under Unicorn.

Real firmware runs for: the app's key-down / key-up handlers, the Keys view's encoder handler, the scale lookup.
Stubbed: engine note on/off (recorded), parameter reads (Scale, Root), root-name list, label text, the root stepper.
The scale table is built at boot on the real unit; here it is filled in by hand with the same layout.
NOT run: the engine, so "the sequencer records the extra notes" and how the label draws are hardware checks.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")

VIEW, MSG, NAMES, STR = 0x24060000, 0x24069000, 0x2406A000, 0x2406B000
SCALES, STATE = 0x24015A38, 0x2405FFA4
STEPPER, ROOT_LBL = VIEW + 0x2068, VIEW + 0x2CC4
ENGINE, PAD = 0x2400A9C0, 0x0102
settings = {0x89: 1, 0x8A: 3}                 # Scale list index (1 = Major), Root (3 = C: the keyboard starts at root - 3)

SCALE_DEFS = {1: list(range(12)), 2: [0, 2, 4, 5, 7, 9, 11], 3: [0, 2, 4, 7, 9], 4: [0, 2, 3, 5, 7, 8, 10]}
for i in range(24):
    offs = SCALE_DEFS.get(i + 1, [0])
    e.uc.mem_write(SCALES + i * 0x1C, bytes([i + 1] + offs).ljust(0x10, b"\0") + struct.pack("<I", len(offs)))
ROOT_NAMES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]
for i, n in enumerate(ROOT_NAMES):
    e.uc.mem_write(STR + 8 * i, n.encode() + b"\0")
    e.w32(NAMES + 4 * i, STR + 8 * i)


def note(kind):
    def f():
        a5 = e.r32(e.uc.reg_read(UC_ARM_REG_SP))
        e.calls.append((kind, e.arg(1), e.arg(2), e.arg(3), a5))
    return f


def param_get():
    e.w32(e.arg(3), settings.get(e.arg(2), 0))


e.stub(0x0804C61C, note("on"))
e.stub(0x0804C5D4, note("off"))
e.stub(0x08099504, param_get, value=1)
e.stub(0x0808E278, value=NAMES)
e.stub(0x080A3DEC, lambda: e.calls.append(("label", e.arg(0), e.cstr(e.arg(1)))))
e.stub(0x080B0B74, lambda: e.calls.append(("root_stepper", e.arg(0))))
e.stub(0x080A0924)                            # record-arm bookkeeping before a touch note-on


def key(msg_handler, n, a5=77):
    e.uc.mem_write(MSG, struct.pack("<HHIHHii", 0xFD, 0, 0, PAD, 0, n, a5))
    return e.call(msg_handler, 0x24020088, MSG)


def down(n):
    return [c[2] for c in key(0x080A0A78, n) if c[0] == "on"]


def up(n):
    return [c[2] for c in key(0x0809B764, n) if c[0] == "off"]


def knob(counts, enc=2):
    e.uc.mem_write(MSG, struct.pack("<HHIHHhHhH", 0x32, 0, 0, 0, 0, enc, 0, counts, 0))
    return e.call(0x080ADF4C, VIEW, MSG)


def shape():
    return e.r8(STATE + 4)


def set_shape(i):
    e.call("chord_knob", STEPPER, 400 * 20)   # all the way down
    if i:
        e.call("chord_knob", STEPPER, -400 * i)
    assert shape() == i, shape()


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e.uc.mem_write(VIEW + 0x4148, b"\x01")        # keys view: knobs active

# --- patch RAM starts as garbage
e.uc.mem_write(STATE, b"\xff" * 44)
c = key(0x080A0A78, 60)
check("garbage state at boot: chords off, key plays one note, velocity argument untouched", len(c) == 1 and c[0][0] == "on" and c[0][2:] == (60, 0, 77) and shape() == 0, c)
check("pad id reaches the engine as the stock handler packs it (row 0, column 2, bank 1)", c[0][1] == (1 << 16) | (0 << 8) | 2, hex(c[0][1]))
check("release sends one note-off", up(60) == [60])

# --- top-right knob, through the real Keys view handler
c = knob(400)
check("top-right knob: one step -> Triad, label 'C Tri', root stepper not turned", shape() == 1 and ("label", ROOT_LBL, "C Tri") in c and not any(x[0] == "root_stepper" for x in c), c)
c = knob(150) + knob(150)
check("300 counts: not a step yet", shape() == 1 and c == [], c)
c = knob(150)
check("...the next 150 complete it -> 7th", shape() == 2 and ("label", ROOT_LBL, "C 7th") in c, c)
for enc in (0, 1, 3):
    c = knob(400, enc)
    check(f"knob {enc} still turns the root stepper, shape untouched", ("root_stepper", STEPPER) in c and shape() == 2, c)
knob(-400 * 30)
check("knob clamps at Off; label back to plain 'C'", shape() == 0 and ("label", ROOT_LBL, "C") in e.call("chord_root_label", ROOT_LBL, STR + 8 * 3))
knob(250)
knob(400 * 30)
check("knob clamps at the last shape (Mj7)", shape() == 15, shape())
knob(-400)
check("one step back from the end takes one step (no backlog)", shape() == 14, shape())
knob(400)
c = e.call("chord_root_label", ROOT_LBL, STR + 8 * 4)
check("view refresh keeps the shape on the label; a sharp root drops the space to stay at five characters: 'C#Mj7'", c == [("label", ROOT_LBL, "C#Mj7")], c)

# --- every shape on C in C major
want = {1: [60, 64, 67], 2: [60, 64, 67, 71], 3: [60, 64, 67, 71, 74], 4: [60, 62, 67], 5: [60, 65, 67],
        6: [60, 64, 67, 69], 7: [60, 64, 67, 74], 8: [60, 67, 72], 9: [60, 72],
        10: [60, 67, 76], 11: [60, 64, 71], 12: [60, 65, 71], 13: [60, 63, 67, 70], 14: [60, 63, 67, 70, 74], 15: [60, 64, 67, 71]}
for i, notes in want.items():
    set_shape(i)
    d, u = down(60), up(60)
    check(f"C major, shape {i} on C4 -> {notes}", d == notes and sorted(u) == sorted(notes), (d, u))

# --- chords follow the scale degree
set_shape(1)
for n, notes, name in ((62, [62, 65, 69], "D minor"), (64, [64, 67, 71], "E minor"), (65, [65, 69, 72], "F major"),
                       (67, [67, 71, 74], "G major"), (69, [69, 72, 76], "A minor"), (71, [71, 74, 77], "B diminished")):
    d = down(n)
    up(n)
    check(f"C major triad on {n} = {name}", d == notes, d)
set_shape(2)
d = down(67); up(67)
check("C major 7th on G = G7 (dominant)", d == [67, 71, 74, 77], d)

set_shape(12)
d = down(65); up(65)
check("C major quartal on F stays in the scale (F B E: the tritone fourth)", d == [65, 71, 76], d)
set_shape(10)
d = down(62); up(62)
check("C major open triad on D = D A F (minor, third on top)", d == [62, 69, 77], d)

# --- parallel shapes: same intervals on every key, whatever the scale
for i, semis, name in ((13, [3, 7, 10], "m7"), (14, [3, 7, 10, 14], "m9"), (15, [4, 7, 11], "Mj7")):
    set_shape(i)
    got = []
    for n in (60, 62, 64, 65, 71):
        got.append(down(n) == [n] + [n + x for x in semis])
        up(n)
    check(f"parallel {name}: identical shape on C, D, E, F and B in C major", all(got), got)
settings.update({0x89: 3, 0x8A: 0})
set_shape(13)
d = down(57); u = up(57)
check("parallel m7 in A minor is the same shape, and releases all four notes", d == [57, 60, 64, 67] and sorted(u) == d, (d, u))
settings.update({0x89: 1, 0x8A: 3})
set_shape(14)
d = down(120); up(120)
check("parallel m9 near the top: notes above 127 dropped", d == [120, 123, 127], d)

# --- other roots and scales
set_shape(1)
settings[0x8A] = 5
d = down(62); up(62)
check("D major: triad on D = D F# A", d == [62, 66, 69], d)
settings.update({0x89: 3, 0x8A: 0})
d = down(57); up(57)
check("A minor: triad on A = A C E", d == [57, 60, 64], d)
settings.update({0x89: 2, 0x8A: 3})
d = down(60); up(60)
check("C major pentatonic: 'Triad' counts pentatonic degrees (C E A)", d == [60, 64, 69], d)
set_shape(9)
d = down(64); up(64)
check("pentatonic: Oct is still a true octave", d == [64, 76], d)
set_shape(1)
settings.update({0x89: 0})
d = down(61); up(61)
check("Chromatic: major triad on the pressed note", d == [61, 65, 68], d)
settings.update({0x89: 1})
d = down(61); up(61)
check("C major, key outside the scale: major triad on the pressed note", d == [61, 65, 68], d)

# --- held-note bookkeeping
d1, d2 = down(60), down(64)
check("two chords sharing notes both sound", d1 == [60, 64, 67] and d2 == [64, 67, 71], (d1, d2))
u1 = up(60)
check("releasing C keeps E and G that the E chord still holds", u1 == [60], u1)
u2 = up(64)
check("releasing E stops the rest", sorted(u2) == [64, 67, 71], u2)

down(60)
knob(400)
u = up(60)
check("shape changed while held: release stops exactly what was started", sorted(u) == [60, 64, 67], u)
set_shape(1)
down(60)
settings.update({0x89: 3, 0x8A: 0})
u = up(60)
check("scale changed while held: release stops exactly what was started", sorted(u) == [60, 64, 67], u)
settings.update({0x89: 1, 0x8A: 3})

d = down(125); u = up(125)
check("top of the range: notes above 127 are dropped", d == [125] and u == [125], (d, u))

keys = [36, 38, 40, 41, 43, 45]
for k in keys:
    down(k)
d = down(48)
check("seventh finger: plays its own note only", d == [48], d)
check("...and releases it only", up(48) == [48])
offs = [n for k in keys for n in up(k)]
check("six held chords all release, each pitch once", len(offs) == len(set(offs)) and set(keys) <= set(offs), offs)
d = down(60)
check("slots are free again afterwards", d == [60, 64, 67], d)
up(60)

# --- slicer pad on the Keys screen: the root label shows something else, leave it alone
e.uc.mem_write(VIEW + 0x4550, b"\x01")
before = shape()
c = e.call("chord_knob", STEPPER, -400)
check("keys showing slices: shape changes, label untouched", shape() == before + 1 and not any(x[0] == "label" for x in c), c)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
