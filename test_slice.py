"""Slice Start/End knobs and the Zoom knob under Unicorn.

Real firmware runs for: knob reset/type/range/value/turn, slice list get/set, the stock Slice Pos
handler, the waveform view's message handler (so the patched call sites are exercised), and the
waveform's "apply pending zoom" step.
Stubbed: message post (recorded), label/text formatting, waveform redraw.
NOT run: the waveform tick that scrolls and redraws, so what the screen does with the centre / zoom
this patch sets is only checked on hardware.
"""
import struct
import sys

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")

VIEW, MARKERS, MSG = 0x24060000, 0x24068000, 0x24069000
BL, TR, BR = VIEW + 0x950, VIEW + 0xC30, VIEW + 0xF10
KNOB_VTABLE = 0x080F0C88
PARAM_START, PARAM_END, PARAM_ZOOM = 0x3E0, 0x3E1, 0x3E2
WAVE = VIEW + 0x38
WIDTH, CENTRE_X = 476, 237


def post():
    m = e.arg(1)
    e.calls.append(("post", e.r16(m), e.r32(m + 0xC), e.r32(m + 0x10)))


e.stub(0x080AED14, post)
e.stub(0x080C3B98, lambda: e.calls.append(("text", e.cstr(e.arg(1)))))   # set string
e.stub(0x080B0528)                                                       # format knob value text
e.stub(0x080B0480)                                                       # knob redraw
e.stub(0x080C6E8C, lambda: e.calls.append(("wave_slices",)))
e.stub(0x080C6EC8, lambda: e.calls.append(("wave_select", e.arg(1))))
for k in (BL, TR, BR):                                                   # knob vtable slot used by reset
    e.w32(k, KNOB_VTABLE)
e.stub(e.r32(KNOB_VTABLE + 0x2C) & ~1)


def markers():
    n = e.r32(VIEW + 0x239C)
    return [e.r32(MARKERS + 4 * i) for i in range(n)]


def set_markers(ms, length=4000):
    for i, m in enumerate(ms):
        e.w32(MARKERS + 4 * i, m)
    e.w32(VIEW + 0x2398, MARKERS)
    e.w32(VIEW + 0x239C, len(ms))
    e.w32(VIEW + 0x2390, length)


def setf(a, v):
    e.uc.mem_write(a, struct.pack("<f", v))


def getf(a):
    return struct.unpack("<f", e.uc.mem_read(a, 4))[0]


def view_at(centre, zoom):
    """Put the waveform where the tick would: this sample in the middle, no zoom pending, view following."""
    e.w32(WAVE + 0x244, centre)
    setf(WAVE + 0x168, zoom)
    setf(WAVE + 0x24C, 0.0)
    e.uc.mem_write(WAVE + 0x1E0, b"\x01")
    e.w32(WAVE + 0x180, 0)


def scroll():
    return dict(centre=e.r32(WAVE + 0x244), state=e.r8(WAVE + 0x1E0), hold=e.r32(WAVE + 0x180))


def knob(k):
    return dict(param=e.r32(k + 0x14), type=e.r8(k + 0x31), lo=e.r32(k + 0x14C), hi=e.r32(k + 0x150), value=e.r32(k + 0x34))


def select(n):
    e.w32(VIEW + 0x47E4, n)
    e.call("slice_refresh", VIEW)


def knob_msg(param, value):
    """Deliver a knob-change (0x3d) to the real waveform view handler."""
    e.uc.mem_write(MSG, struct.pack("<HHIHHiII", 0x3D, 0, 0x080CFBA4, 0, 0, value, param, 0))
    return e.call(0x080A66DC, VIEW, MSG)


def turn(k, counts):
    """Turn a knob (400 encoder counts = 1 step) through the real widget code; return the 0x3d it posts as (param, value)."""
    c = [x for x in e.call(0x080B0D54, k, counts) if x[0] == "post" and x[1] == 0x3D]
    return (c[-1][3], c[-1][2]) if c else None


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- setup as the stock Slicer branch does it: top-right first, then the two bottom binds
set_markers([0, 1000, 2000, 3000])
assert WAVE + 0x168 == VIEW + 0x1A0
e.w32(WAVE + 0xC, WIDTH)
e.w32(WAVE + 0x240, CENTRE_X)
view_at(1000, 1.0)                                      # zoom -> 1 sample per detent
e.w32(VIEW + 0x47E4, 2)
e.call(0x080B04C8, TR)
e.w32(TR + 0x14, 0x31)
e.call(0x080B0B08, TR, 0xD)
c0 = e.call("slice_setup", VIEW)
c1 = e.call("slice_bind_start", 0, 0, BL)
c2 = e.call("slice_bind_end", 0, 0, BR)
check("labels are Zoom: / Start: / End:", ("text", "Zoom:") in c0 and ("text", "Start:") in c1 and ("text", "End:") in c2, f"{c0} {c1} {c2}")
check("top-right is Zoom: level 24 (1 sample/pixel), widest offered 17 (4000 samples fit)", knob(TR) == dict(param=PARAM_ZOOM, type=1, lo=17, hi=24, value=24), knob(TR))
check("Start knob: slice 2 start 1000 in 1..1999", knob(BL) == dict(param=PARAM_START, type=0xD, lo=1, hi=1999, value=1000), knob(BL))
check("End knob: next marker 2000 in 1001..2999", knob(BR) == dict(param=PARAM_END, type=0xD, lo=1001, hi=2999, value=2000), knob(BR))

# --- turn End up through the real widget + real view handler
t = turn(BR, 450)
check("End knob turn posts a knob change with its private id", t is not None and t[0] == PARAM_END, t)
c = knob_msg(*t)
v = markers()[2]
check("End moved marker 2 forward, others untouched", v > 2000 and markers() == [0, 1000, v, 3000], markers())
check("engine told: msg 0x4a (marker 2, new pos)", ("post", 0x4A, 2, v) in c, c)
check("private id never forwarded to the app as a parameter", not any(x[0] == "post" and x[1] == 0x6E for x in c), c)
check("waveform redrawn", ("wave_slices",) in c)
check("Start upper limit follows the new end", knob(BL)["hi"] == v - 1, knob(BL))

# --- turn Start down
t = turn(BL, -1300)
c = knob_msg(*t)
s = markers()[1]
check("Start knob moved marker 1 back", t[0] == PARAM_START and s < 1000 and markers() == [0, s, v, 3000], markers())
check("engine told: msg 0x4a (marker 1)", ("post", 0x4A, 1, s) in c, c)
check("End lower limit follows the new start", knob(BR)["lo"] == s + 1, knob(BR))

# --- the stock Slice Pos message (no knob sends it now) is still handled and updates the bottom pair
c = knob_msg(0x31, 1500)
check("stock Slice Pos sets marker 1", markers()[1] == 1500 and ("post", 0x4A, 1, 1500) in c, (markers(), c))
check("Start shows 1500, End lower limit 1501", knob(BL)["value"] == 1500 and knob(BR)["lo"] == 1501, (knob(BL), knob(BR)))

# --- clamping
knob_msg(PARAM_END, 5)
check("End clamps one sample after the start", markers()[2] == 1501, markers())
knob_msg(PARAM_END, 999999)
check("End clamps one sample before the next marker", markers()[2] == 2999, markers())
knob_msg(PARAM_START, -50)
check("Start clamps one sample after the previous marker", markers()[1] == 1, markers())

# --- selection changes
set_markers([0, 1000, 2000, 3000])
select(1)
check("slice 1: Start = marker 0 in 0..999, End = marker 1 in 1..1999", (knob(BL)["lo"], knob(BL)["hi"], knob(BL)["value"]) == (0, 999, 0) and (knob(BR)["lo"], knob(BR)["hi"], knob(BR)["value"]) == (1, 1999, 1000), (knob(BL), knob(BR)))
knob_msg(PARAM_START, 300)
knob_msg(PARAM_START, -5)
check("slice 1: Start can return to sample 0", markers()[0] == 0, markers())
select(4)
check("last slice: End pinned at the end of the WAV", (knob(BR)["lo"], knob(BR)["hi"], knob(BR)["value"]) == (4000, 4000, 4000), knob(BR))
c = knob_msg(PARAM_END, 3500)
check("last slice: End knob changes nothing", markers() == [0, 1000, 2000, 3000] and not any(x[0] == "post" for x in c), (markers(), c))
c = knob_msg(PARAM_START, 3200)
check("last slice: Start still moves marker 3", markers()[3] == 3200 and ("post", 0x4A, 3, 3200) in c, markers())

# --- other parameters and the slice-select knob are unaffected
c = knob_msg(0x90, 77)
check("ordinary parameter still forwarded (msg 0x6e, param 0x90, value 77)", ("post", 0x6E, 0x90, 77) in c, c)
c = knob_msg(0x4E, 3)
check("Slice select: selects 3 and refreshes Start / End", e.r32(VIEW + 0x47E4) == 3 and knob(BL)["value"] == 2000 and knob(BR)["value"] == 3200, (knob(BL), knob(BR)))

# --- Start / End step follows the zoom
view_at(3000, 64.0)
e.call("slice_refresh", VIEW)
check("zoomed out: 64 samples per detent on Start and End", [e.r32(k + 0x28C) for k in (BL, BR)] == [64, 64], [e.r32(k + 0x28C) for k in (BL, BR)])
before = markers()[3]
c = knob_msg(*turn(BR, 900))
check("zoomed out: two steps move the end onto the 64-sample grid (3200 -> 3264)", before == 3200 and markers()[3] == 3264, (before, markers()))

# --- Zoom knob
set_markers([0, 100000, 500000, 900000], 2_000_000)     # longer than 4096 samples/pixel can show: every level offered
view_at(0, 256.0)                                       # what the stock Slicer setup leaves
e.uc.mem_write(0x2405FFA0, b"\xff")                     # patch RAM is not zeroed at boot
e.w32(VIEW + 0x47E4, 2)
e.call("slice_setup", VIEW)
check("stock zoom 256 reads as level 8 of 0..24", (knob(TR)["lo"], knob(TR)["hi"], knob(TR)["value"]) == (0, 24, 8), knob(TR))
t = turn(TR, 400)
check("one detent up posts Zoom level 9", t == (PARAM_ZOOM, 9), t)
c = knob_msg(*t)
check("Zoom is not forwarded to the app or the engine", not any(x[0] == "post" for x in c), c)
check("level 9 = 181 samples/pixel, left pending for the waveform tick", abs(getf(WAVE + 0x24C) - 181.0193) < 0.01 and getf(WAVE + 0x168) == 256.0, (getf(WAVE + 0x24C), getf(WAVE + 0x168)))
check("view centred on the slice start and held, as the stock scroll-to does", scroll() == dict(centre=100000, state=2, hold=300) and e.r8(WAVE + 0x32) == 1, scroll())
check("Start / End step already follows the pending zoom", [e.r32(k + 0x28C) for k in (BL, BR)] == [181, 181], [e.r32(k + 0x28C) for k in (BL, BR)])
e.call(0x080C6A78, WAVE)
check("stock tick step applies it", abs(getf(WAVE + 0x168) - 181.0193) < 0.01 and getf(WAVE + 0x24C) == 0.0, (getf(WAVE + 0x168), getf(WAVE + 0x24C)))
knob_msg(*turn(TR, -800))
shown = e.r32(TR + 0x27C) + e.r32(TR + 0x288)           # what an integer knob prints: stepper index + range start
check("two detents down: level 7 = 362 samples/pixel, knob shows 7", abs(getf(WAVE + 0x24C) - 362.0387) < 0.01 and shown == 7, (getf(WAVE + 0x24C), shown))
knob_msg(PARAM_ZOOM, 99)
check("level clamps at 24 = 1 sample/pixel", getf(WAVE + 0x24C) == 1.0, getf(WAVE + 0x24C))
knob_msg(PARAM_ZOOM, -3)
check("level clamps at 0 = 4096 samples/pixel", getf(WAVE + 0x24C) == 4096.0, getf(WAVE + 0x24C))

view_at(0, 16.0)
knob_msg(PARAM_END, 500100)
knob_msg(PARAM_ZOOM, 20)
check("after turning End, zoom centres on the slice end", scroll()["centre"] == 500100, scroll())
knob_msg(PARAM_START, 100050)
knob_msg(PARAM_ZOOM, 21)
check("after turning Start, zoom centres on the slice start", scroll()["centre"] == 100050, scroll())
e.w32(VIEW + 0x47E4, 4)
knob_msg(PARAM_END, 1)
knob_msg(PARAM_ZOOM, 20)
check("last slice, End turned last: zoom centres on the end of the WAV", scroll()["centre"] == 2_000_000, scroll())
knob_msg(PARAM_START, 900000)

view_at(900000, 4.0)                                    # screen shows 900000 +- 948 samples
knob_msg(PARAM_START, 900400)
check("Start moved but still on screen: view not touched", scroll() == dict(centre=900000, state=1, hold=0), scroll())
knob_msg(PARAM_START, 902000)
check("Start moved off screen: view follows it", scroll() == dict(centre=902000, state=2, hold=300), scroll())
view_at(902000, 4.0)
knob_msg(0x4E, 2)
check("Slice select, new slice off screen: view jumps to its start", scroll() == dict(centre=100050, state=2, hold=300), scroll())
view_at(100050, 4096.0)
knob_msg(0x4E, 3)
check("Slice select, new slice already on screen: view not touched", scroll() == dict(centre=100050, state=1, hold=0), scroll())

view_at(0, 4.0)
e.w32(WAVE + 0x178, 1)
knob_msg(PARAM_ZOOM, 12)
check("finger on the waveform: zoom still set, view left to the touch gesture", getf(WAVE + 0x24C) == 64.0 and scroll() == dict(centre=0, state=1, hold=0), (getf(WAVE + 0x24C), scroll()))
e.w32(WAVE + 0x178, 0)

view_at(0, 300.0)                                       # e.g. left by a pinch
e.call("slice_refresh", VIEW)
check("pinch zoom 300 reads as the nearest level (8 = 256)", knob(TR)["value"] == 8, knob(TR))
set_markers([0, 100000], 150000)
e.call("slice_refresh", VIEW)
check("150000-sample WAV: widest level offered is 7 (362/pixel shows it all)", knob(TR)["lo"] == 7, knob(TR))

# --- no slices
set_markers([])
e.call("slice_refresh", VIEW)
c = knob_msg(PARAM_START, 100)
check("no slices: knobs do nothing", not any(x[0] == "post" for x in c) and knob(BL)["value"] == 0 and knob(BR)["value"] == 0, (c, knob(BL), knob(BR)))

# --- knobs bound to something else (Sample mode) are left alone by the refresh
set_markers([0, 1000, 2000, 3000])
e.w32(BL + 0x14, 0x91)
e.w32(BR + 0x14, 0x92)
e.w32(BL + 0x34, 111)
e.w32(BR + 0x34, 222)
select(2)
check("refresh ignores knobs not bound to Start/End", e.r32(BL + 0x34) == 111 and e.r32(BR + 0x34) == 222)
e.w32(TR + 0x14, 0x90)
e.w32(TR + 0x34, 333)
e.w32(TR + 0x14C, 5)
e.call("slice_refresh", VIEW)
check("refresh ignores a top-right knob not bound to Zoom", e.r32(TR + 0x34) == 333 and e.r32(TR + 0x14C) == 5)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
