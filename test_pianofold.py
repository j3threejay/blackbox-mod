"""Piano roll Fold, Scale fold, the BR pitch knob and the 1..127 range (src/pianofold.c) under Unicorn.

Real firmware runs for: the whole piano roll view built by its own constructor (FUN_080c04dc, from 0xA5 garbage: the
roll, its EDIT menu, its knobs), the view's 0x66 refresh handler FUN_080c130c (refresh FUN_080bfeec: clear, re-add
every note, auto-fit FUN_080bb40e, reselect FUN_080bc17c), the roll's touch-down / move / up handlers and its
per-frame tick from its vtable (double-tap, taps that add notes, drags, flings), the layout, row maps, hit tests,
stock's knob widget, the BR / TL knob handlers through the view's knob message 0x32, the roll draw (key strip, the
scroll bar, pianoslice's numbers), the menu's own add / layout code, the settings reads (FUN_08099504 on test stores),
and stock's scale table builder FUN_0806e9dc (to check our copy of the intervals). All of it in the patched image and,
where the feature is not new, side by side with the stock 3.1.9 image.
Stubbed (recorded): messages to the parent (FUN_080aed14: what a tap or a knob sends to the app), the sequence's event
iterator (FUN_08063814 / FUN_08097d48 / FUN_0806381c: the events come from a Python list), the cell-info call that
names the sequence type (FUN_080996b0) and its name list (FUN_0808e278), the drawing primitives.
The app's side of an edit is played by the test: a pitch change (message 0x42) is written into the event list and a
0x66 refresh is sent back, as the app does (INFERRED: the app queues that refresh; the round trip is not run).
NOT run: the glass (touch timing, the 400 ms double-tap window, how 31 px menu buttons read), the real app.
"""
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK_IMG = "firmware/BLACKBOX-3.1.9.bin"
B = 0x08040000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


APP = 0x24020088
V = 0x24040000
R = V + 0x38
MENU = V + 0xBC10
HEAP, HEAP_END = 0x24060000, 0x24078000
ARR, MSG, NAMES, PT, DC = 0x24078000, 0x24079000, 0x2407A000, 0x2407A100, 0x2407A200
CLOCK = 0x2402EEE0
SEQ_CELL = APP + 0x1840                              # the sequence: cell row 0 col 0 (view + 0xb494 = id 0)
PAD_CELL = APP + 0x1840 + 2 * 0xF0 + 1 * 0x30       # a Slicer pad: row 2 col 1 (id 0x21)
SONG = APP + 0x3038                                  # the song store (keymode 0x89, keyroot 0x8a)
MAJOR = {0, 2, 4, 5, 7, 9, 11}
MASKS = [0xfff, 0xab5, 0x295, 0x5ad, 0x4a9, 0x4e9, 0x9b3, 0x9cb, 0x9cd, 0x575, 0x4a5, 0x1a3,
         0x8b1, 0x555, 0xb6d, 0x9ad, 0xaad, 0x6ad, 0x5ab, 0xad5, 0x6b5, 0x5ad, 0x56b]


def store(at, arr, entries):
    """A settings store as FUN_08093e9c reads it: +4 the entries, +10 their count; entries {u16 id, u16 0, i32 v}."""
    w.e.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in entries))
    w.e.w32(at + 4, arr)
    w.e.uc.mem_write(at + 10, struct.pack("<H", len(entries)))


class World:
    def __init__(self, image):
        self.e = e = Emu(image, "out/cave.elf")
        for a in (0x38800000, 0x58024000):
            e.uc.mem_map(a, 0x1000)
        self.msgs, self.log, self.ev, self.seqtype = [], [], [], 1
        e.stub(0x080AED14, lambda: self.msgs.append((e.r16(e.arg(1)), [e.r32(e.arg(1) + o) for o in (4, 8, 12, 16, 20)])))
        e.stubs[0x0806381C] = self._next
        e.stub(0x08063814)
        e.stub(0x08097D48)
        e.stub(0x080996B0, self._info, value=1)
        e.uc.mem_write(NAMES, struct.pack("<3I", NAMES + 16, NAMES + 24, NAMES + 32) + bytes(4) +
                       b"Pads\0\0\0\0Keys\0\0\0\0MIDI\0\0\0\0")
        e.stub(0x0808E278, value=NAMES)
        rect = lambda a: struct.unpack("<4i", e.uc.mem_read(a, 16))
        e.stub(0x0808EA22, lambda: self.log.append(("fill", rect(e.arg(0)), e.arg(1) & 0xFF)))
        e.stub(0x0808E994, lambda: self.log.append(("box", rect(e.arg(0)), e.arg(1) & 0xFF)))
        e.stub(0x0808EA7E, lambda: self.log.append(("line", rect(e.arg(0))[:2], rect(e.arg(1))[:2], e.arg(2) & 0xFF)))
        e.stub(0x0808F23C, lambda: self.log.append(("text", e.cstr(e.arg(0)), rect(e.arg(1)), e.arg(2) & 0xFF)))
        e.stub(0x080AEAF8)                                       # children draw
        e.uc.mem_write(V, b"\xa5" * 0x13000)                     # garbage, as a long-lived GUI object can hold
        e.w32(0x2400008C, HEAP)
        e.w32(0x24000088, HEAP_END)
        e.call(0x080C04DC, V, count=50_000_000)
        self.snap = bytes(e.uc.mem_read(0x24000000, 0x80000))
        self.vt = struct.unpack_from("<16I", open(image, "rb").read(), 0x080F13DC - B)
        self.vview = struct.unpack_from("<I", open(image, "rb").read(), 0x080F1688 - B)[0]
        self.now = 10_000

    def _next(self):
        e, i = self.e, self.e.arg(1)
        if i < len(self.ev):
            s, l, p, nid = self.ev[i]
            if self.seqtype == 0:                               # a Pads event: pitch 0, the pad in byte 2
                p, kind = 0, 0x01000001 | p << 16
            else:
                kind = 0x01000001
            e.uc.mem_write(e.arg(2), struct.pack("<IIIIHH", kind, s * 960, l * 960, nid, p, 100))
            e.ret(1)
        else:
            e.ret(0)

    def _info(self):
        a = self.e.arg(2)
        self.e.uc.mem_write(a + 0x34, struct.pack("<H", 1))
        self.e.w32(a + 0x38, self.seqtype)

    # --- state
    def reset(self, events, keymode=1, keyroot=3, seqtype=1):
        e = self.e
        e.uc.mem_write(0x24000000, self.snap)
        global w
        w = self
        store(SEQ_CELL, ARR, [(0x88, 1), (0x86, 16)])            # Step Mode (note times = steps x 960), 16 steps
        store(SONG, ARR + 0x40, [(0x89, keymode), (0x8A, keyroot)])
        self.ev, self.seqtype = list(events), seqtype
        self.m66(1)                                              # as opening a sequence: refresh + auto-fit

    def song(self, keymode, keyroot):
        store(SONG, ARR + 0x40, [(0x89, keymode), (0x8A, keyroot)])

    def m66(self, flag=0):
        e = self.e
        e.uc.mem_write(MSG, struct.pack("<HHIHHiii", 0x66, 0, 0x080CFBA4, e.r16(V + 0xB494), 0, flag, 0, 0))
        self.msgs.clear()
        e.call(0x080C130C, V, MSG, count=30_000_000)

    def i32(self, o):
        return self.e.r32(R + o)

    def u8(self, o):
        return self.e.r8(R + o)

    def fold(self):
        return 0 if not self.u8(0xB2B4) else 2 if self.u8(0xB2B5) else 1

    def lst(self):
        return [self.i32(0xB2B8 + 4 * i) for i in range(self.i32(0xB43C))]

    rows = property(lambda s: s.i32(0xA040))
    base = property(lambda s: s.i32(0xA93C))
    scroll = property(lambda s: s.i32(0xB440))

    def row_notes(self):
        out = []
        for i in range(self.rows):
            self.e.call(0x080BABF6, R, i)
            out.append(self.e.arg(0))
        return out

    def row_y(self, i):
        return (self.i32(0xA944 + 4 * i) + self.i32(0xA944 + 4 * i + 4)) // 2

    def y_note(self, y):
        self.e.uc.mem_write(PT, struct.pack("<2i", 100, y))
        self.e.call(0x080BAC38, R, PT)
        return self.e.arg(0)

    # --- touch, through the roll's vtable (+0x10 down, +0x14 move, +0x18 up, +0 tick)
    def _pt(self, x, y):
        self.e.uc.mem_write(PT, struct.pack("<2i", x, y))
        return PT

    def down(self, x, y):
        self.e.w32(CLOCK, self.now)
        self.e.call(self.vt[4], R, self._pt(x, y), 0)

    def move(self, x, y):
        self.now += 16
        self.e.w32(CLOCK, self.now)
        self.e.call(self.vt[5], R, self._pt(x, y), 0)

    def up(self, x, y):
        self.e.w32(CLOCK, self.now)
        self.msgs.clear()
        self.e.call(self.vt[6], R, self._pt(x, y), 0)
        return list(self.msgs)

    def tick(self):
        self.e.uc.mem_write(DC, bytes(8))
        self.e.call(self.vt[0], R, DC)

    def tap(self, x, y):
        self.now += 300
        self.down(x, y)
        return self.up(x, y)

    def double_tap(self):
        self.now += 1000
        for _ in range(2):
            self.down(15, 90)
            self.up(15, 90)
            self.now += 120

    def drag(self, x, y0, y1, step=10):
        """A scroll drag: the view has select mode on (view ctor: roll + 0xaea4 = 1), where a quick drag draws a
        selection box; held still 800 ms first (+ 0xb2ac), the drag scrolls."""
        self.now += 1000
        self.down(x, y0)
        self.now += 900
        self.move(x, y0)
        d = step if y1 > y0 else -step
        for y in range(y0 + d, y1 + d, d):
            self.move(x, y)
            self.tick()
        self.up(x, y1)
        for _ in range(400):                                    # the fling, to its end
            if not self.u8(0xAE24):
                break
            self.tick()

    def adds(self, msgs):
        return [m[1][2] & 0xFFFF for m in msgs if m[0] == 0xDA]

    # --- knobs, through the view's knob message 0x32 (knob 3 = BR, 0 = TL)
    def knob(self, k, counts, echo=True):
        e = self.e
        e.uc.mem_write(MSG, struct.pack("<HHIHHHHhH", 0x32, 0, 0, 0, 0, k, 0, counts, 0) + bytes(8))
        self.msgs.clear()
        e.call(0x080C130C, V, MSG, count=30_000_000)
        sent = list(self.msgs)
        if echo:                                                # the app's side: write the edit, refresh
            for m in sent:
                if m[0] == 0x42:
                    nid, pitch = m[1][2], m[1][3] >> 16
                    self.ev = [(s, l, pitch if i == nid else p, i) for s, l, p, i in self.ev]
            if any(m[0] == 0x42 for m in sent):
                self.m66(0)
        return sent

    def select(self, nid):
        self.e.call(0x080BC17C, R, nid)

    def sel_pitch(self):
        idx = self.i32(0xA094 + 4 * self.i32(0xA088))
        return self.i32(idx * 0x50 + 0x78)

    def br(self, n, counts=400):
        out = []
        for _ in range(abs(n)):
            self.knob(3, counts if n > 0 else -counts)
            out.append(self.sel_pitch())
        return out

    def menu_click(self, item_id, kind=2):
        self.e.uc.mem_write(MSG, struct.pack("<HHIHHI", kind, 0, 0, 0, 0, item_id) + bytes(12))
        self.e.call(self.vview, V, MSG)
        return self.e.arg(0)

    def draw(self):
        self.log.clear()
        self.e.uc.mem_write(DC, bytes([1, 1, 0, 0]) + struct.pack("<I", 0x2407A300))
        self.e.call(0x080BC974, R, DC)
        return list(self.log)


wp = World(IMG)
ws = World(STOCK_IMG)
w = wp
img = open(IMG, "rb").read()
stock = open(STOCK_IMG, "rb").read()
sym = wp.e.sym


def bl_target(at):
    h1, h2 = struct.unpack_from("<HH", img, at - B)
    off = ((h1 & 0x7FF) << 12 | (h2 & 0x7FF) << 1)
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    off |= ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | (s << 24)
    if s:
        off -= 1 << 25
    return at + 4 + off


# ---------------------------------------------------------------------------------------------------------- hooks
sites = [(0x080BB286, "pf_build"), (0x080BC718, "pf_tap"), (0x080BBCA0, "pf_follow"), (0x080BC066, "pf_follow"),
         (0x080BC2FE, "pf_follow"), (0x080BC410, "pf_follow"), (0x080C145C, "pf_refresh"), (0x080C17BA, "pf_pitch"),
         (0x080C08B8, "pf_menu_add")]
check("the 9 BLs go to ours (layout list step, double-tap, 4 x follow, refresh, BR, EDIT menu)",
      all(bl_target(a) == sym[n] & ~1 for a, n in sites), [(hex(a), n) for a, n in sites if bl_target(a) != sym[n] & ~1])
check("roll vtable slot 0 (0x080f13dc) = pf_tick, the view's notify slot (0x080f1688) = pf_view_msg; the roll draw "
      "slot is still stock's", struct.unpack_from("<I", img, 0x080F13DC - B)[0] == sym["pf_tick"] | 1
      and wp.vview == sym["pf_view_msg"] | 1 and struct.unpack_from("<I", img, 0x080F13E0 - B)[0] == 0x080BC975)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
dis = lambda data, a, n: [f"{i.mnemonic} {i.op_str}" for i in md.disasm(data[a - B:a - B + n], a)]
want = {0x080BA0C2: "movs r3, #1", 0x080BA0D2: "movs r1, #0x78", 0x080BA0E8: "movs r1, #0x7f",
        0x080BCCD6: "moveq r1, #0x7f", 0x080BD236: "rsb.w r2, r2, #0x80", 0x080BB1A0: "nop", 0x080BBD0A: "nop"}
want[0x080BCCD6] = "movs r1, #0x7f"                     # inside an IT block (capstone prints no condition here)
got = {a: dis(img, a, 4)[0].strip() for a in want}
check("patched instructions: Keys min base 1, scroll widget count 120, pitch knob 127, scroll bar range 127, drag top "
      "0x80 - rows, the layout's list step on every folded layout, the refresh keeps the fold scroll",
      got == want, got)
check("... over stock's 24 / 66 / 73 / 73 / 0x61 - rows / cbz b44c / str b440",
      [dis(stock, a, 4)[0] for a in (0x080BA0C2, 0x080BA0D2, 0x080BA0E8, 0x080BD236, 0x080BB1A0, 0x080BBD0A)] ==
      ["movs r3, #0x18", "movs r1, #0x42", "movs r1, #0x49", "rsb.w r2, r2, #0x61", "cbz r3, #0x80bb1ae",
       "str.w r3, [r7, #0x440]"])

# --------------------------------------------------------------------------------------------------- scale intervals
e = wp.e
e.call(0x0806E9DC)
derived = []
for km in range(23):
    for i in range(24):
        b = bytes(e.uc.mem_read(0x24015A38 + i * 0x1C, 0x1C))
        if b[0] == km + 1:
            m = 0
            for s in b[1:1 + struct.unpack_from("<i", b, 0x10)[0]]:
                m |= 1 << s
            derived.append(m)
            break
ours = list(struct.unpack_from("<23H", img, sym["scale_mask"] - B))
check("our 23 scale masks (flash) = the table stock's FUN_0806e9dc builds in RAM at boot (Chromatic .. Locrian)",
      ours == derived == MASKS, (ours, derived))

# ---------------------------------------------------------------------------------------------- above 96 in stock
NOTES = [(0, 1, 36, 11), (2, 1, 43, 12), (4, 1, 48, 13), (6, 1, 60, 14), (8, 1, 30, 15), (10, 1, 120, 16)]
ws.reset(NOTES)
ws.e.w32(R + 0xA93C, 97 - ws.rows)
ws.e.call(0x080BB190, R)
r120 = struct.unpack("<4i", ws.e.uc.mem_read(R + 5 * 0x50 + 0x38, 16))
top = ws.i32(0xA944 + 4 * ws.rows)
check(f"STOCK, view at its top (rows {ws.base}..96): note 120 is a 3 px sliver just above the top row line "
      f"(y {r120[1]}, h {r120[3]}; top line {top}), at its own step: no row of its own",
      r120[3] == 3 and r120[1] == top + 1, r120)
ws.e.w32(R + 0xA93C, 40)
ws.e.call(0x080BB190, R)
ws.drag(200, 170, -400)
check("STOCK: a drag up from base 40 stops at base 97 - rows (top row 96)", ws.base + ws.rows - 1 == 96,
      (ws.base, ws.rows))

# ---------------------------------------------------------------------------------------------- unfolded vs stock
for name, events in [("6 notes 30..60", NOTES[:5]), ("one note at 60", [(0, 1, 60, 11)]), ("empty", [])]:
    wp.reset(events)
    ws.reset(events)
    same = (wp.rows, wp.base, wp.row_notes()) == (ws.rows, ws.base, ws.row_notes())
    tp = [wp.adds(wp.tap(200, wp.row_y(i))) for i in range(wp.rows)]
    tps = [ws.adds(ws.tap(200, ws.row_y(i))) for i in range(ws.rows)]
    thumb = lambda log: [x if not (x[0] == "fill" and x[1][0] == 1 and x[1][2] == 9 and x[2] == 1) else "thumb" for x in log]
    check(f"unfolded, {name}: same rows / base / row notes as stock after the auto-fit, taps add the same pitches, "
          "the draw is stock's but for the scroll thumb", same and tp == tps and thumb(wp.draw()) == thumb(ws.draw()),
          ((wp.rows, wp.base), (ws.rows, ws.base), tp[:3], tps[:3]))
wp.reset(NOTES[:5])
ws.reset(NOTES[:5])
for x in (wp, ws):
    x.select(14)
mid = (wp.br(3), wp.br(-5)), (ws.br(3), ws.br(-5))
check("unfolded BR from 60, mid-range: one semitone a detent, as stock (61 62 63 / 62 .. 58)",
      mid[0] == mid[1] == ([61, 62, 63], [62, 61, 60, 59, 58]), mid)
for x in (wp, ws):
    x.reset(NOTES[:5])
    x.drag(200, 100, 60, 8)
check("unfolded drag in mid-range: the same base as stock", wp.base == ws.base and wp.base != 30, (wp.base, ws.base))

# -------------------------------------------------------------------------------------------------- 1..127
wp.reset(NOTES)
wp.drag(200, 170, -400)
rn = wp.row_notes()
check(f"widened: a drag up stops at the top with the top row on 127 (base {wp.base}, rows {wp.rows})",
      rn[-1] == 127 and wp.base == 128 - wp.rows, rn)
i120 = rn.index(120)
r120 = struct.unpack("<4i", wp.e.uc.mem_read(R + 5 * 0x50 + 0x38, 16))
check("... note 120 sits on its own row (its rect is that row's height, not a sliver)",
      r120[1] == wp.i32(0xA944 + 4 * i120) + 1 and r120[3] > 3, r120)
check("... a tap on an empty step of row 120 adds pitch 120", wp.adds(wp.tap(300, wp.row_y(i120))) == [120])
th = [x for x in wp.draw() if x[0] == "fill" and x[1][0] == 1 and x[1][2] == 9 and x[2] == 1][0][1]
h = 182 - 2
check("... the scroll bar thumb spans (base - 1) / 127 .. (base - 1 + rows) / 127 of the bar",
      abs(th[1] - (1 + (wp.base - 1) / 127 * h)) <= 1 and abs(th[1] + th[3] - (1 + (wp.base - 1 + wp.rows) / 127 * h)) <= 1,
      (th, wp.base, wp.rows))
wp.drag(200, 10, 700, 20)
check("... a drag down stops at the bottom with row 0 on 1 (not 0: a Keys event of pitch 0 is not a note)",
      wp.base == 1 and wp.row_notes()[0] == 1, wp.base)
# pinch / auto-fit push the view out of range: the tick brings it back
wp.reset([(0, 1, 120, 11), (2, 1, 126, 12), (4, 1, 100, 13)])
af = (wp.rows, wp.base)
wp.tick()
check(f"auto-fit on notes 100..126 (rows {af[0]}, base {af[1]}: top row {af[0] + af[1] - 1}) -> the next frame keeps "
      "the view inside 1..127", wp.base + wp.rows - 1 <= 127 and max(wp.row_notes()) <= 127, (wp.rows, wp.base))
wp.reset([(0, 1, 2, 11)])
wp.tick()
check("... and a lone note at 2 (stock's centring gives base -1)", wp.base >= 1 and min(wp.row_notes()) >= 1,
      (wp.rows, wp.base))

# BR at the ends
wp.reset([(0, 1, 120, 11), (2, 1, 60, 12)])
wp.select(11)
top = wp.br(9)
back = wp.br(-2)
check("BR from 120: up to 127 and no further, then one detent down = 126 (no dead detent, no skip)",
      top == [121, 122, 123, 124, 125, 126, 127, 127, 127] and back == [126, 125], (top, back))
wp.reset([(0, 1, 3, 11), (2, 1, 60, 12)])
wp.select(11)
low = wp.br(-4)
up = wp.br(1)
check("... from 3: down to 1 and no further, then one detent up = 2", low == [2, 1, 1, 1] and up == [2], (low, up))
ws.reset([(0, 1, 94, 11), (2, 1, 60, 12)])
ws.select(11)
check("STOCK at C7 for comparison: 95 96 96, then 96 (dead) 94 (skip)", ws.br(3) + ws.br(-2) == [95, 96, 96, 96, 94])
ws.reset([(0, 1, 110, 11), (2, 1, 60, 12)])
ws.select(11)
wp.reset([(0, 1, 110, 11), (2, 1, 60, 12)])
wp.select(11)
check("a note at 110 (outside stock's 24..96): stock snaps it to 95 on the first detent down; ours moves it to 109",
      ws.br(-1) == [95] and wp.br(-1) == [109])
wp.reset([(0, 1, 60, 11)])
wp.select(11)
wp.knob(3, 200)
p1 = wp.sel_pitch()
wp.knob(3, 200)
check("half detents still add up (200 + 200 counts = one semitone; nothing on the first half)",
      p1 == 60 and wp.sel_pitch() == 61, (p1, wp.sel_pitch()))

# pianoslice on the widened range: chop 85 = note 120
wp.reset(NOTES)
store(PAD_CELL, ARR + 0x80, [(0x8B, 2), (0x14D, 1)])
wp.e.w32(PAD_CELL + 0x28, ARR + 0x200)
wp.e.w32(PAD_CELL + 0x2C, 92)
wp.e.uc.mem_write(V + 0xB49C, struct.pack("<H", 0x21))
wp.e.uc.mem_write(V + 0xF5E1, b"\0")
wp.e.w32(R + 0xA040, 13)                             # 13 rows: thick enough for labels (32 rows hide them, as stock)
wp.e.w32(R + 0xA93C, 128 - 13)
wp.e.call(0x080BB190, R)
rn = wp.row_notes()
texts = {t: r for k, t, r, c in [x for x in wp.draw() if x[0] == "text"]}
i = rn.index(120)
h_ = wp.i32(0xA944 + 4 * i + 4) - wp.i32(0xA944 + 4 * i)
check("pianoslice, ChopShop with 92 chops, view at the top: note 120's key reads '85' on its row (chops up to 92 = "
      "note 127)", "85" in texts and texts["85"][1] == wp.i32(0xA944 + 4 * i) + ((h_ - 8) >> 1) and "92" in texts
      and "C9" in texts,
      sorted(texts)[:8])

# ------------------------------------------------------------------------------------------------- Fold to notes
wp.reset(NOTES)
before = (wp.rows, wp.base)
gb = wp.u8(0xB2B5)
wp.double_tap()
check(f"double-tap on the key strip (stock's gesture) turns Fold to notes ON (garbage 0x{gb:02x} in + 0xb2b5 before)",
      wp.fold() == 1, wp.fold())
check("... the ON branch: + 0xb2b4 = 1, + 0xb444 / + 0xb448 = the unfolded rows / base, + 0xb44c done",
      (wp.u8(0xB2B4), wp.i32(0xB444), wp.i32(0xB448), wp.u8(0xB44C)) == (1, before[0], before[1], 0),
      (wp.u8(0xB2B4), wp.i32(0xB444), wp.i32(0xB448), before))
check("... list = the sequence's pitches, ascending (30 36 43 48 60 120), rows = 6, scroll 0",
      wp.lst() == [30, 36, 43, 48, 60, 120] and wp.rows == 6 and wp.scroll == 0 and
      wp.row_notes() == [30, 36, 43, 48, 60, 120], (wp.lst(), wp.rows))
check("... touch y -> note: each row's centre gives its listed pitch",
      [wp.y_note(wp.row_y(i)) for i in range(wp.rows)] == wp.lst())
labels = [x[1] for x in wp.draw() if x[0] == "text"]
check("... the key strip labels every row (stock's fold draw): F#1 C2 G2 C3 C4 C9",
      labels[:6] == ["F#1", "C2", "G2", "C3", "C4", "C9"], labels)
adds = [wp.adds(wp.tap(300, wp.row_y(i))) for i in range(wp.rows)]
check("... a tap on an empty step of each row adds that row's pitch", adds == [[p] for p in wp.lst()], adds)
wp.ev.append((12, 1, 50, 17))
wp.m66(0)
check("... a note added (refresh): list rebuilt at once (+ 50), rows follow (7)",
      wp.lst() == [30, 36, 43, 48, 50, 60, 120] and wp.rows == 7, (wp.lst(), wp.rows))
wp.m66(1)
check("... the auto-fit (sequence change / layer, 0x66 with the flag) keeps the fold and rows <= count (no phantom "
      "rows reading note 0)", wp.fold() == 1 and wp.rows == 7 and 0 not in wp.row_notes(), (wp.rows, wp.row_notes()))
allr = [wp.adds(wp.tap(300, y)) for y in range(2, 182, 5)]
check("... taps anywhere from the bottom margin to the top margin add only listed pitches, never 0",
      all(a and a[0] in wp.lst() for a in allr if a), allr)
wp.e.uc.mem_write(MSG, struct.pack("<HHIHHiii", 0xDD, 0, 0, 0, 0, 1, 0, 0))
wp.e.call(0x080C130C, V, MSG, count=30_000_000)
check("... a layer change (msg 0xdd: auto-fit alone, rows 7..32) leaves rows = count",
      wp.rows == len(wp.lst()) and 0 not in wp.row_notes(), (wp.rows, wp.lst()))

# BR in Fold to notes: a semitone, the row follows
wp.reset(NOTES)
wp.double_tap()
wp.select(12)                                        # 43
p = wp.br(2)
check("BR in Fold to notes: one semitone a detent (43 -> 44 -> 45); the list follows the note (43 gone, 45 there)",
      p == [44, 45] and wp.lst() == [30, 36, 45, 48, 60, 120], (p, wp.lst()))
wp.reset([(i * 2, 1, 40 + 2 * i, 11 + i) for i in range(40)])          # 40 pitches > 32 rows
wp.double_tap()
check("Fold to notes, 40 pitches: rows = 32 (max), the scroll opens where the unfolded view was",
      wp.rows == 32 and len(wp.lst()) == 40, (wp.rows, wp.scroll))
wp.select(11 + 39)                                   # pitch 118, top
check("... selecting the top note scrolls it into view (follow, fold-aware)",
      wp.scroll <= 39 < wp.scroll + wp.rows and wp.scroll == 8, wp.scroll)
wp.select(11)
check("... and the bottom one back", wp.scroll == 0, wp.scroll)

# drag scroll in a fold, refresh keeps it
base_before, y0 = wp.base, wp.row_y(10)
rh = wp.row_y(11) - y0
wp.drag(200, y0, y0 - 3 * rh, 2)
s1 = wp.scroll
check(f"a drag down the screen by 3 rows in the fold moves the fold scroll by 3 (0 -> {s1}), the unfolded base stays",
      s1 == 3 and wp.base == base_before, (s1, wp.base, base_before))
wp.drag(200, y0, y0 - 6 * rh, 6 * rh)
for _ in range(80):
    wp.tick()
check("... a quick one (a fling follows) stays inside 0..count - rows", 0 <= wp.scroll <= 8, wp.scroll)
wp.e.w32(R + 0xB440, 5)
wp.m66(0)
check("a refresh keeps the fold scroll (5 stays 5; stock zeroes it in FUN_080bbcac)", wp.scroll == 5, wp.scroll)
ws.reset(NOTES)
ws.e.uc.mem_write(R + 0xB2B4, b"\1")
ws.e.w32(R + 0xB440, 2)
ws.e.call(0x080BBCAC, R)
check("... STOCK's refresh-clear: 2 -> 0", ws.scroll == 0)
wp.drag(200, 10, 900, 30, )
check("a long drag up the screen in the fold stops at the bottom (scroll 0, never negative)", wp.scroll == 0, wp.scroll)
wp.drag(200, 170, -900, 30, )
check("... and a long drag down at count - rows (8)", wp.scroll == 8, wp.scroll)

# ------------------------------------------------------------------------------------------------------ Scale fold
def scale_list(notes, mask, root, lo=1):
    pcs = {k for k in range(12) if mask >> k & 1}
    s = {p for p in range(lo, 128) if (p - root) % 12 in pcs} | set(notes)
    return sorted(s)


wp.reset(NOTES)
wp.double_tap()
wp.double_tap()
L = wp.lst()
check("second double-tap: Scale fold (C major, keyroot 3 = C): every C major pitch 1..127 + the notes",
      wp.fold() == 2 and L == scale_list([30, 36, 43, 48, 60, 120], MASKS[1], 0), (len(L), L[:10]))
check("... off-scale notes unioned in: F#1 (30) has a row, F#2 (42) none", 30 in L and 42 not in L and 30 % 12 not in MAJOR)
check(f"... rows = the unfolded rows ({wp.i32(0xB444)}), the bottom row = the first scale pitch >= the old base "
      f"({wp.i32(0xB448)})", wp.rows == wp.i32(0xB444) and wp.row_notes()[0] == min(p for p in L if p >= wp.i32(0xB448)),
      (wp.rows, wp.row_notes()[:3]))
for km, kr, name in [(3, 0, "A minor (keyroot 0 = A)"), (17, 5, "D Dorian"), (2, 7, "E major pent"),
                     (13, 1, "A# whole tone"), (6, 11, "G# Raga Bhairav")]:
    wp.song(km, kr)
    wp.m66(0)
    want = scale_list([30, 36, 43, 48, 60, 120], MASKS[km], (kr + 9) % 12)
    check(f"... {name}: picked up at the next refresh, list = its pitches + the notes", wp.lst() == want,
          (wp.lst()[:12], want[:12]))
wp.song(0, 3)
wp.m66(0)
L = wp.lst()
check("... Chromatic: 127 pitches do not fit stock's 97-entry list: 97 consecutive pitches around the notes, every "
      f"note kept ({L[0]}..{L[-1]})", len(L) == 97 and L == list(range(L[0], L[0] + 97)) and
      {30, 36, 43, 48, 60, 120} <= set(L), (len(L), L[0], L[-1]))
wp.reset(NOTES, keymode=1, keyroot=3)
wp.double_tap()
wp.double_tap()
wp.double_tap()
check("third double-tap: OFF, rows / base restored", wp.fold() == 0 and (wp.rows, wp.base) == (wp.i32(0xB444),
      wp.i32(0xB448)), (wp.fold(), wp.rows, wp.base))
wp.reset([])
wp.double_tap()
check("an empty layer: the double-tap goes straight to Scale (nothing to fold to)", wp.fold() == 2, wp.fold())
wp.double_tap()
check("... and the next one OFF", wp.fold() == 0)

# BR in Scale fold
wp.reset([(0, 1, 64, 11), (2, 1, 61, 12), (4, 1, 30, 13)])
wp.double_tap()
wp.double_tap()
wp.select(11)                                        # E4 = 64 in C major
up = wp.br(3)
down = wp.br(-5)
check("BR in Scale fold (C major): one detent = the next shown pitch: 64 -> 65 67 69, back 67 65 64 62 61 (C#: "
      "another note's row, shown)", up == [65, 67, 69] and down == [67, 65, 64, 62, 61], (up, down))
check("... the rows under the finger are the scale's: every row's centre y gives its listed pitch",
      [wp.y_note(wp.row_y(i)) for i in range(wp.rows)] == wp.lst()[wp.scroll:wp.scroll + wp.rows])
wp.select(13)                                        # 30 = F#1, off the C major scale
s = wp.br(1)
check("... an off-scale note steps onto the scale (F#1 30 -> G1 31) and its old row goes (30 no longer listed)",
      s == [31] and 30 not in wp.lst(), (s, wp.lst()[:6]))
wp.reset([(0, 1, 125, 11)])
wp.double_tap()
wp.double_tap()
wp.select(11)
top = wp.br(3)
back = wp.br(-1)
check("... at the top (F9 125 -> G9 127, the highest C major pitch) it stops; one detent back = F9 again (F#9 126 "
      "has no row)", top == [127, 127, 127] and back == [125], (top, back))

# ------------------------------------------------------------------------------------------------------ EDIT menu
wp.reset(NOTES)
n_items = wp.e.r32(MENU + 0x12F4)
items = [struct.unpack("<4i", wp.e.uc.mem_read(MENU + 0x34 + i * 0xA0 + 4, 16)) for i in range(n_items)]
ids = [wp.e.r32(MENU + 0x34 + i * 0xA0 + 0x14) for i in range(n_items)]
check("EDIT: 9 entries, stock's 7 then Fold Notes / Fold Scale (ids 0x7e0 / 0x7e1)",
      ids == [0x28, 0x29, 0x2A, 0x25, 0x186, 0x12, 0x199, 0x7E0, 0x7E1], [hex(i) for i in ids])
check("... 2 columns of 5 + 4 at x 80 / 200 (stock's 4 per column would make 3, the first at x -40), all inside "
      "the 320 x 182 roll area", wp.e.r32(MENU + 0x1308) == 5 and {r[0] for r in items} == {80, 200} and
      all(r[0] >= 0 and r[0] + r[2] <= 320 and r[1] >= 0 and r[1] + r[3] <= 182 for r in items), items)
item_mem = [bytes(wp.e.uc.mem_read(MENU + 0x34 + i * 0xA0, 0xA0)) for i in (7, 8)]
def label_of(m):
    for o in range(0, 0xA0 - 3, 4):
        p = struct.unpack_from("<I", m, o)[0]
        if p in (sym["fold_notes"], sym["fold_scale"]):
            return wp.e.cstr(p)
    for s_ in (b"Fold Notes", b"Fold Scale"):
        if s_ in m:
            return s_.decode()
check("... their labels are ours ('Fold Notes', 'Fold Scale': no pooled stock string)",
      [label_of(m) for m in item_mem] == ["Fold Notes", "Fold Scale"], [label_of(m) for m in item_mem])
wp.e.uc.mem_write(MENU + 0x30, b"\0")               # the menu open
r = wp.menu_click(0x7E0)
check("Fold Notes from OFF: Fold to notes, the menu closes (as Clear Sel), handled (0)",
      wp.fold() == 1 and wp.e.r8(MENU + 0x30) == 1 and r == 0, (wp.fold(), wp.e.r8(MENU + 0x30), r))
wp.menu_click(0x7E1)
check("Fold Scale from Notes: Scale fold", wp.fold() == 2)
wp.menu_click(0x7E1)
check("Fold Scale while in Scale fold: OFF, rows / base restored",
      wp.fold() == 0 and (wp.rows, wp.base) == (wp.i32(0xB444), wp.i32(0xB448)))
wp.menu_click(0x7E1)
wp.menu_click(0x7E0)
check("Fold Notes from Scale: Fold to notes; again: OFF", wp.fold() == 1 and (wp.menu_click(0x7E0), wp.fold())[1] == 0)
r = wp.menu_click(0x7E0, kind=1)
check("a press (type 1) of our entry is swallowed (0) and changes nothing", r == 0 and wp.fold() == 0)
wp.msgs.clear()
r = wp.menu_click(0x28, kind=1)
check("stock's entries still reach stock (Cut Seq press -> forwarded up as msg 0x28)",
      any(m[0] == 0x28 for m in wp.msgs), wp.msgs)
wp.e.uc.mem_write(MSG, struct.pack("<HHIHHI", 0x16E, 0, 0, 0, 0, 0x7E0) + bytes(12))
wp.e.call(wp.vview, V, MSG)
check("a 0x16e (selection) message carrying note id 0x7e0 is not taken for our entry", wp.fold() == 0)

# --------------------------------------------------------------------------------------------------- Pads roll
wp.reset([(0, 1, 3, 11), (2, 1, 9, 12), (4, 1, 0, 13)], seqtype=0)
check("a Pads sequence: stock's Pads roll (min base 0, 16 rows)", wp.u8(0xAE74) == 1 and wp.i32(0xAE78) == 0)
wp.double_tap()
pads_l = wp.lst()
wp.double_tap()
check("... the double-tap folds to the pads used (0 3 9), then OFF (no Scale fold on pads)",
      pads_l == [0, 3, 9] and wp.fold() == 0, (pads_l, wp.fold()))

print(f"{fails} failed")
sys.exit(1 if fails else 0)
