"""Waveform screen corner labels (src/wavelabel.c, patches/wavelabel.py) under Unicorn.

The four corner knobs of the Waveform view, in every pad mode: the knob's line white (palette 15) with a 1 px black
edge (14), stock's label draw nine times on a copy of the label, in its box inset by a pixel.
Real firmware runs for: the knob's layout (FUN_080afeb2, which makes the line its child), its draw (FUN_080b115e) and
the children walks (FUN_080aeaf8, FUN_080aeb1c), the label's text setter and its two draws (FUN_080c3d2c,
FUN_080c3fc6), the text, glyph and clipped-glyph draws and the pixel write (FUN_0808f524) into an 8-bit layer of
320 x 240, the font and the palette from the image's .data (copied in, as the reset copies it); for the pad modes, the
Waveform screen's setup (FUN_080a54a0: its bind blocks, the binder FUN_080a7ee0, JOEBOX's slice_* hooks) and the view's
refresh (FUN_080a6d28, message 0x66), with the stock pad-parameter registrar's table.
Stubbed: for the pad modes, the app's copy of the pad's store into the view, the file name, the text widgets' text,
icons, buttons, the mode list, the knob redraw, the view's post.
Reference: the stock image's own draw of the same label, in white at the inset box.
NOT checked: the view's constructor itself (the four knobs are built here as it builds them), the screen's repaint
order on the unit, how it looks on the real panel.
"""
import math
import struct
import sys

from unicorn import UC_HOOK_CODE

from emu import BASE, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
img, stock = open(IMAGE, "rb").read(), open(STOCK, "rb").read()
e = Emu(IMAGE, "out/cave.elf")
S = e.sym
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def info(text):
    print("     " + text)


def maps(m):
    """what the GUI code touches beyond emu.py's map: ITCM/DTCM/SRAM, backup SRAM + RCC, WWDG, SDRAM"""
    for a, n in ((0x00000000, 0x10000), (0x20000000, 0x80000), (0x30000000, 0x48000), (0x38000000, 0x10000),
                 (0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1800000)):
        m.uc.mem_map(a, n)


def branch(at, data=img):
    """target of the 4-byte bl at `at`"""
    h1, h2 = struct.unpack_from("<HH", data, at - BASE)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    off -= (1 << 25) if s else 0
    kind = "bl" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0xD000 else "?"
    return kind, at + 4 + off


# --- the image: the four sites and the vtable
SITES = {"TL": 0x080A660A, "BL": 0x080A6612, "TR": 0x080A661A, "BR": 0x080A6622}
check("the Waveform view's constructor colours its four corner knobs (TL, BL, TR, BR): stock 'bl 0x080b02e6' at "
      "0x080a660a / 12 / 1a / 22 is now 'bl wavelabel'",
      all(branch(a, stock) == ("bl", 0x080B02E6) and branch(a) == ("bl", S["wavelabel"]) for a in SITES.values()),
      {n: (branch(a, stock), branch(a)) for n, a in SITES.items()})
LBL_VT, KNOB_VT, LINE, LBL_BOX, LBL_COLOUR = 0x080F17A4, 0x080F0C88, 0xF4, 0x04, 0x53
vt = struct.unpack_from("<16I", img, S["wavelabel_vt"] - BASE)
st_vt = struct.unpack_from("<16I", stock, LBL_VT - BASE)
check("wavelabel_vt: a copy of stock's label vtable (0x080f17a4: fourteen entries and the two words after) with [1] and "
      "[2], the whole draw and the clipped draw, ours", vt[3:] == st_vt[3:] and vt[0] == st_vt[0] and
      (vt[1], vt[2]) == (S["wavelabel_draw"] | 1, S["wavelabel_clip"] | 1) and (st_vt[1], st_vt[2]) == (0x080C3D2D, 0x080C3FC7),
      ([hex(v) for v in vt], [hex(v) for v in st_vt]))

# --- the four corner knobs, as the view's constructor leaves them
CORNERS = {"TL": (1, (0, 0x4A, 0x9D, 0x49)), "BL": (2, (0, 0, 0x9D, 0x49)), "TR": (3, (0x9E, 0x4A, 0x9D, 0x49)),
           "BR": (4, (0x9E, 0, 0x9D, 0x49))}            # the view's (FUN_080a5b90): layout, the knob's rectangle
LFB, LLAYER, LCTX, LRECT, LCLIP, LSTR, LKN = 0x24030000, 0x24058000, 0x24058100, 0x24058140, 0x24058180, 0x240581C0, 0x24050000
SW, SH, BG, CYAN, GREY, BLACK, WHITE = 320, 240, 13, 5, 9, 14, 15
DATA_LMA, DATA_LEN = 0x080F1D80, 0xF8                    # stock's .data load image: the palette at 0x24000000, the font


class Corners:
    """the four corner knobs as the view's constructor leaves them, on an emulator of `image` (stock: FUN_080b02e6 at the
    four sites, as stock calls it); bank2=False: bank 2's header wiped first"""

    def __init__(self, image=IMAGE, bank2=True):
        m = self.m = Emu(image, "out/cave.elf")
        maps(m)
        if not bank2:
            m.uc.mem_write(0x08100000, bytes(16))
        m.uc.mem_write(0x24000000, stock[DATA_LMA - BASE:DATA_LMA - BASE + DATA_LEN])
        m.uc.mem_write(LLAYER, struct.pack("<IHHBB", LFB, SW, SH, 5, 1))     # 8-bit, rows flipped
        m.uc.mem_write(LCTX, struct.pack("<BBHI", 1, 1, 0, LLAYER))
        self.at = {}
        for i, (n, (layout, rect)) in enumerate(CORNERS.items()):
            at = self.at[n] = LKN + 0x300 * i
            m.uc.mem_write(at, bytes(0x300))
            m.w32(at, KNOB_VT)
            for lo in (0x44, 0x9C, LINE):                                    # as the constructor sets them
                m.w32(at + lo, LBL_VT)
                m.uc.mem_write(at + lo + 0x51, bytes([1, 1, 3, 0x10, 0, 0]))
            m.uc.mem_write(at + 0x32, bytes([layout]))
            m.uc.mem_write(LRECT, struct.pack("<4i", *rect))
            m.call(0x080AFEB2, at, LRECT)
            m.call(S["wavelabel"] if image == IMAGE else 0x080B02E6, at, GREY)
        self.paint(BG)

    def paint(self, c, box=None):
        if box is None:
            self.m.uc.mem_write(LFB, bytes([c]) * (SW * SH))
            return
        x, y, w, h = box
        for r in range(SH - y - h, SH - y):
            self.m.uc.mem_write(LFB + r * SW + x, bytes([c]) * w)

    def text(self, n, s):
        self.m.uc.mem_write(LSTR, s.encode() + b"\0")
        self.m.call(0x080C3B98, self.at[n] + LINE, LSTR)

    def box(self, n):
        return struct.unpack("<4i", bytes(self.m.uc.mem_read(self.at[n] + LINE + LBL_BOX, 16)))

    def draw(self, n, clip=None):
        if clip is None:
            self.m.call(0x080B115E, self.at[n], LCTX, count=20_000_000)
        else:
            self.m.uc.mem_write(LCLIP, struct.pack("<4i", *clip))
            self.m.call(0x080AEB1C, self.at[n], LCTX, LCLIP, count=20_000_000)

    def fb(self):
        return bytes(self.m.uc.mem_read(LFB, SW * SH))


def pix(fb, c):
    """the (x, y) of every pixel of colour c, y up as the widgets count it"""
    return {(i % SW, SH - 1 - i // SW) for i, v in enumerate(fb) if v == c}


def changed(a, b):
    return {(i % SW, SH - 1 - i // SW) for i in range(len(a)) if a[i] != b[i]}


def inside(ps, box):
    x, y, w, h = box
    return all(x <= px < x + w and y <= py < y + h for px, py in ps)


def ring(ps):
    return {(px + dx, py + dy) for px, py in ps for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - ps


lc = Corners()
st_lc = Corners(STOCK)
kn = lc.at["TL"]
check("each corner knob's line (+ 0xf4) has our vtable, its name and value labels stock's; all three keep the "
      "constructor's grey (9); the line is the knob's only child (layouts 1..4)",
      all(lc.m.r32(a + LINE) == S["wavelabel_vt"] and lc.m.r32(a + 0x44) == lc.m.r32(a + 0x9C) == LBL_VT
          and [lc.m.r8(a + lo + LBL_COLOUR) for lo in (0x44, 0x9C, LINE)] == [GREY] * 3
          and lc.m.r32(a + 0x1C) == lc.m.r32(a + 0x18) == a + LINE for a in lc.at.values()),
      {n: (hex(lc.m.r32(a + LINE)), hex(lc.m.r32(a + 0x1C)), [lc.m.r8(a + lo + LBL_COLOUR) for lo in (0x44, 0x9C, LINE)])
       for n, a in lc.at.items()})
lc.m.w32(kn + LINE, 0x080F0144)
lc.m.call(S["wavelabel"], kn, GREY)
check("  ...and leaves a line whose vtable is not stock's label's alone", lc.m.r32(kn + LINE) == 0x080F0144)
lc.m.w32(kn + LINE, S["wavelabel_vt"])

# --- every corner, short and long lines (Sample, Slicer and Granular names), on the background and on the cyan: white
# exactly where stock draws the glyphs in the box inset by a pixel, black exactly on the pixels around them, nothing
# else changed, all in the box
LINES = {"TL": ["Start 6000", "Start 12345678", "Slice: 16"], "BL": ["Len: 96000", "Start 0", "Spray: 100"],
         "TR": ["End 336359", "Zoom 1/64", "Pos: 99999"], "BR": ["Loop 102000", "End 4", "Size: 0"]}


def lines_ok(scr, ref_scr):
    rows, ok_all = {}, True
    for n, texts in LINES.items():
        for t in texts:
            for bgc in (BG, CYAN):
                scr.paint(bgc)
                scr.text(n, t)
                before = scr.fb()
                scr.draw(n)
                after = scr.fb()
                box = scr.box(n)
                ref_scr.paint(0)                  # stock's glyphs at the inset box, in white: the reference
                ref_scr.text(n, t)
                sa = ref_scr.at[n] + LINE
                ref_scr.m.uc.mem_write(sa + LBL_BOX, struct.pack("<4i", box[0] + 1, box[1] + 1, box[2] - 2, box[3] - 2))
                ref_scr.m.uc.mem_write(sa + LBL_COLOUR, bytes([WHITE]))
                ref_scr.draw(n)
                ref = pix(ref_scr.fb(), WHITE)
                ref_scr.m.uc.mem_write(sa + LBL_BOX, struct.pack("<4i", *box))
                ref_scr.m.uc.mem_write(sa + LBL_COLOUR, bytes([GREY]))
                w, k, ch = pix(after, WHITE), pix(after, BLACK), changed(before, after)
                ok = ref and w == ref and k == ring(ref) and ch == w | k and inside(ch, box)
                ok_all &= bool(ok)
                rows[(n, t, bgc)] = (len(w), len(k), ok)
    return ok_all, rows


ok_all, rows = lines_ok(lc, st_lc)
check(f"{len(rows)} lines (four corners, 7 to 14 characters, on the background and on the cyan): the glyphs white "
      "exactly where stock draws them in the box inset by a pixel, the pixels around them black, nothing else changed, "
      "all inside the label's box", ok_all, {k: v for k, v in rows.items() if not v[2]})
info("white / black pixels: " + ", ".join(f"{n} {t!r} {w}/{k}" for (n, t, b), (w, k, _) in rows.items() if b == BG))

# --- the clipped draw (the screen's repaint of a dirty rectangle): the same pixels when the rectangle holds the box,
# and only those inside it when it cuts the box
lc.paint(CYAN)
lc.text("TR", "End 102000")
base = lc.fb()
lc.draw("TR")
full = lc.fb()
box = lc.box("TR")
lc.paint(CYAN)
lc.draw("TR", clip=box)
same = lc.fb()
lc.paint(CYAN)
half = (box[0] + box[2] // 2, box[1], box[2] - box[2] // 2, box[3] - 7)
lc.draw("TR", clip=half)
cut = lc.fb()
ch_cut = changed(base, cut)
check(f"the clipped draw (FUN_080aeb1c through the line's [2]): with the box as the dirty rectangle, the frame of the "
      f"whole draw ({len(changed(base, same))} pixels); with {half} only pixels inside it ({len(ch_cut)}), each as the "
      "whole draw has it", same == full and ch_cut and inside(ch_cut, half)
      and all(cut[(SH - 1 - y) * SW + x] == full[(SH - 1 - y) * SW + x] for x, y in ch_cut)
      and ch_cut == {p for p in changed(base, full) if inside([p], half)}, (len(ch_cut), half))

# --- a value that changes: the screen repaints the label's box and draws it again; nothing is left outside the box
for n, (t1, t2) in (("TR", ("End 102000", "End 96000")), ("TL", ("Start 12345678", "Start 0")), ("BL", ("Len: 96000", "Len: 0"))):
    lc.paint(CYAN)
    lc.text(n, t1)
    lc.draw(n)
    lc.text(n, t2)
    lc.paint(CYAN, lc.box(n))
    lc.draw(n)
    after = lc.fb()
    lc.paint(CYAN)
    lc.draw(n)
    check(f"{n} {t1!r} then {t2!r}, the box repainted between: the frame of a fresh draw of {t2!r}", after == lc.fb())

# --- no tie to bank 2: with bank 2's header wiped (no BBEXTRA.BIN installed), the same white and black
nb_lc = Corners(bank2=False)
ok_nb, rows_nb = lines_ok(nb_lc, st_lc)
check(f"bank 2 missing: the same {len(rows_nb)} lines, white and black as above (it needs nothing up there)", ok_nb,
      {k: v for k, v in rows_nb.items() if not v[2]})

# --- the stock image draws them grey, and the patched image's labels are as stock left them (box, grey, flags)
frames = []
for scr in (lc, st_lc):
    scr.paint(CYAN)
    for n, texts in LINES.items():
        scr.text(n, texts[0])
        scr.draw(n)
    frames.append(scr.fb())
check(f"stock: the four lines grey ({len(pix(frames[1], GREY))} pixels, none white or black); here none grey",
      pix(frames[1], GREY) and not pix(frames[1], WHITE) | pix(frames[1], BLACK) and not pix(frames[0], GREY))
check("  ...and after every draw above, the labels themselves are untouched: past the vtable, the same bytes (box, grey, "
      "text, flags) as stock's after the same draws", all(bytes(lc.m.uc.mem_read(lc.at[n] + LINE + 4, 0x54))
                                                        == bytes(st_lc.m.uc.mem_read(st_lc.at[n] + LINE + 4, 0x54)) for n in CORNERS),
      {n: (bytes(lc.m.uc.mem_read(lc.at[n] + LINE + 4, 0x54)).hex(), bytes(st_lc.m.uc.mem_read(st_lc.at[n] + LINE + 4, 0x54)).hex())
       for n in CORNERS})

# --- every pad mode: the Waveform screen set up and refreshed in Sample, Clip, Slicer, Granular and New Rec (and back)
# never sets a label's vtable again, nor a colour. Real: the setup FUN_080a54a0 and its binds (JOEBOX's slice_* hooks
# in Slicer mode), the view's refresh 0x66.
VIEW, VENT, VMSG = 0x24060000, 0x24070000, 0x24078000
KN = {"TL": 0x670, "BL": 0x950, "TR": 0xC30, "BR": 0xF10}
PAD = {0x8B: 0, 0xEA: 0, 0x8E: 1, 0x8F: 0, 0x90: 0, 0x91: 24000, 0x92: 72000, 0x8D: 1, 0x94: 3, 0x47: 3, 0xD2: 0}


def registrar(m, table):
    """the stock pad-parameter registrar run whole (JOEBOX's rows in it), so the binder finds every id"""
    m.stub(0x0804436C, value=table)
    m.call(0x0808C158, 0, count=20_000_000)
    del m.stubs[0x0804436C]


class Screen:
    """the Waveform view of pad (1, 2) on an emulator of the image"""

    def __init__(self):
        m = self.m = Emu(IMAGE, "out/cave.elf")
        maps(m)
        registrar(m, 0x24040000)
        m.uc.mem_write(VIEW, bytes(0x5000))
        for o in KN.values():
            m.w32(VIEW + o, KNOB_VT)
        self.vals = {}
        m.stub(0x0809A830, lambda: self.copy(self.vals))
        m.stub(0x0809AD74, lambda: m.uc.mem_write(m.arg(2), b"loop.wav\0"))
        for a in (0x080C3B98, 0x080A5480, 0x080A3DEC, 0x080C6078, 0x080C4DD6, 0x080A401C, 0x080BD398, 0x080BD74E,
                  0x080C6004, 0x080A5210, 0x080B0480, 0x080C4DF0, 0x080AED14):
            m.stub(a)
        m.stub(0x080A331A, lambda: m.uc.mem_write(m.arg(0) + 0x30, bytes([m.arg(1) & 0xFF])))   # a knob's grey flag
        m.w32(VIEW + 0x2390, 192000)                         # the file's length
        m.w32(VIEW + 0x47C8 + 8, 400)                        # the marker stepper's counts per step
        m.uc.mem_write(VIEW + 0x29C, struct.pack("<H", 0x12))
        m.uc.mem_write(VIEW + 0x3740, b"\x01")               # turns go to the knobs (not the popup list)

    def copy(self, vals):
        rows = sorted(vals.items())
        self.m.uc.mem_write(VENT, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
        self.m.w32(VIEW + 0x2370 + 4, VENT)
        self.m.uc.mem_write(VIEW + 0x2370 + 10, struct.pack("<HH", len(rows), 96))

    def open(self, mode, was):
        self.vals = {**PAD, 0x8B: mode}
        self.copy({**PAD, 0x8B: was})
        self.m.call(0x080A54A0, VIEW, 0, count=50_000_000)

    def refresh(self):
        self.m.uc.mem_write(VMSG, struct.pack("<HHIHHiiI", 0x66, 0, 0x080CFBA4, 0x12, 0, 0, 0, 0))
        self.m.call(0x080A6D28, VIEW, VMSG, count=50_000_000)


ms = Screen()
for o in KN.values():
    for lo in (0x44, 0x9C, LINE):
        ms.m.w32(VIEW + o + lo, LBL_VT)
    ms.m.call(S["wavelabel"], VIEW + o, GREY)
seen = []
for mode, was in ((0, 0), (1, 0), (3, 1), (2, 3), (1, 2), (0, 1), (4, 0)):   # Sample, Clip, Granular, Slicer, New Rec
    ms.open(mode, was)
    ms.refresh()
    seen.append(all(ms.m.r32(VIEW + o + LINE) == S["wavelabel_vt"] and ms.m.r32(VIEW + o + 0x44) == ms.m.r32(VIEW + o + 0x9C) == LBL_VT
                    and ms.m.r8(VIEW + o + LINE + LBL_COLOUR) == GREY for o in KN.values()))
check(f"every pad mode: Sample, Clip, Granular, Slicer and New Rec set up and refreshed on the screen, the four lines keep "
      f"our vtable and their grey, the other labels stock's ({seen})", all(seen), seen)


# --- what it costs: the instructions of one corner's draw (the GUI task, not the audio's)
def cost(scr, n, t):
    scr.paint(CYAN)
    scr.text(n, t)
    count = [0]
    h = scr.m.uc.hook_add(UC_HOOK_CODE, lambda *a: count.__setitem__(0, count[0] + 1))
    scr.m.uc.ctl_flush_tb()                  # the draw's code is translated already: without this the hook never runs
    scr.draw(n)
    scr.m.uc.hook_del(h)
    scr.m.uc.ctl_flush_tb()
    return count[0]


c_ours, c_stock = cost(lc, "TL", "Start 12345678"), cost(st_lc, "TL", "Start 12345678")
check(f"one corner's draw, 14 characters: {c_ours} instructions against stock's {c_stock} (x{c_ours / c_stock:.1f}: nine "
      "passes)", 8 * c_stock < c_ours < 10 * c_stock, (c_ours, c_stock))


# --- a preview: stock's four corners and these, over a waveform of the screen's cyan on its background
def frame(scr):
    scr.paint(BG)
    buf = bytearray(scr.fb())
    for x in range(SW):
        a = int(118 * abs(math.sin(x / 9.0) * math.sin(x / 41.0)) + 4)
        for y in range(max(0, 120 - a), min(SH, 120 + a)):
            buf[(SH - 1 - y) * SW + x] = CYAN
    scr.m.uc.mem_write(LFB, bytes(buf))
    for n, t in (("TL", "Start 6000"), ("BL", "Len: 96000"), ("TR", "End 102000"), ("BR", "Loop 102000")):
        scr.text(n, t)
        scr.draw(n)
    return scr.fb()


def png(path, frames, scale=2):
    import zlib
    pal = struct.unpack_from("<34I", stock, DATA_LMA - BASE)
    width = SW * len(frames) + 8 * (len(frames) - 1)
    raw = bytearray()
    for r in range(SH):
        line = bytearray()
        for i, f in enumerate(frames):
            if i:
                line += bytes([40, 40, 40]) * 8
            for x in range(SW):
                v = pal[f[r * SW + x]] if f[r * SW + x] < 34 else 0xFFFF00FF
                line += bytes([(v >> 16) & 255, (v >> 8) & 255, v & 255])
        line = b"".join(line[i:i + 3] * scale for i in range(0, len(line), 3))
        raw += (b"\0" + line) * scale

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width * scale, SH * scale, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


png("out/wavelabel-preview.png", [frame(st_lc), frame(lc)])
info("out/wavelabel-preview.png: stock's corner labels (left) and these (right), over the screen's cyan on its background")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
