"""Slice numbers on the piano roll's keys (src/pianoslice.c) under Unicorn.

Real firmware runs for: stock's whole roll draw FUN_080bc974 (key strip, labels, scroll bar, the theme hooks), in the
patched image AND in the stock 3.1.9 image side by side; the hook; stock's cell lookup (FUN_08098d0c), settings read
(FUN_08093e9c) on a test store, row -> note (FUN_080babf6, Fold too), snprintf, strlen.
Stubbed (recorded): the drawing primitives (fill FUN_0808ea22, outline FUN_0808e994, line FUN_0808ea7e, text
FUN_0808f23c) and the children draw FUN_080aeaf8.
Checked: on a Slicer / ChopShop Play Pad every key C2 + k with k < slices gets "k + 1" and reads white (a black key is
repainted 15 inside its row lines; keys without a slice stay stock), nothing
below C2 or past the last slice; C2 keeps stock's "C2" with the "1" at the key's right edge; a 2-digit number on a C key
(and every label under Fold that has no room) erases the label in the key's colour and takes its place; the number's
y is the label's y; every stock call is unchanged and in order, ours come after the key strip and before the
children; a Sample pad, Pads / MIDI sequences, a partial draw, thin rows, no slices and a bad pad id draw exactly as
stock.
NOT run: the glass (font placement in real pixels, the themes' look), the view's refresh path that sets the pad
(msg 0x66, FUN_080c130c: read statically), which slice the engine really plays for a sequence note.
"""
import struct
import sys

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
VIEW = 0x24040000
ROLL = VIEW + 0x38
DC, CTX, ARR = 0x24060000, 0x24060100, 0x24061000
X0, Y0 = 0, 20                                       # the roll's rect: keys at x 10..33


def setup(e):
    e.uc.mem_map(0x38800000, 0x1000)
    e.uc.mem_map(0x58024000, 0x1000)
    e.log = []
    rect = lambda a: struct.unpack("<4i", e.uc.mem_read(a, 16))
    e.stub(0x0808EA22, lambda: e.log.append(("fill", rect(e.arg(0)), e.arg(1) & 0xFF)))
    e.stub(0x0808E994, lambda: e.log.append(("box", rect(e.arg(0)), e.arg(1) & 0xFF)))
    e.stub(0x0808EA7E, lambda: e.log.append(("line", rect(e.arg(0))[:2], rect(e.arg(1))[:2], e.arg(2) & 0xFF)))
    e.stub(0x0808F23C, lambda: e.log.append(("text", e.cstr(e.arg(0)), rect(e.arg(1)), e.arg(2) & 0xFF)))
    e.stub(0x080AEAF8, lambda: e.log.append(("children", e.arg(0), e.arg(1))))


ep = Emu(IMG, "out/cave.elf")
es = Emu(STOCK_IMG, "out/cave.elf")
setup(ep)
setup(es)

img = open(IMG, "rb").read()
h1, h2 = struct.unpack_from("<HH", img, 0x080BD024 - B)
off = ((h1 & 0x7FF) << 12 | (h2 & 0x7FF) << 1)
s = (h1 >> 10) & 1
j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
off |= ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | (s << 24)
if s:
    off -= 1 << 25
check("bl @0x080bd024 (the roll draw's children draw) -> pianoslice_children",
      0x080BD024 + 4 + off == ep.sym["pianoslice_children"] & ~1, hex(0x080BD024 + 4 + off))
check("the roll's vtable slot (0x080f13e0) is still stock's draw FUN_080bc974",
      struct.unpack_from("<I", img, 0x080F13E0 - B)[0] == 0x080BC975)


def cell(row, col):
    return APP + 0x1840 + row * 0xF0 + col * 0x30


def world(e, *, notes=None, base=30, rows=30, h=12, mode=2, chop=0, slices=12, pad=0x21, pads=0, midi=0, full=1,
          fold=None, hs=None):
    ram = lambda a, n: e.uc.mem_write(a, bytes(n))
    ram(VIEW, 0x10000)
    ram(APP, 0xF000)
    e.uc.mem_write(ROLL + 4, struct.pack("<4i", X0, Y0, 320, 180))
    struct_rows = rows if fold is None else len(fold)
    e.w32(ROLL + 0xA038, 0)                          # no step columns: keeps the log to the key strip
    e.w32(ROLL + 0xA040, struct_rows)
    e.w32(ROLL + 0xA93C, base)
    ys = [Y0 + 1 + h * i for i in range(struct_rows + 1)]
    if hs is not None:                               # uneven rows, as the layout's rounding makes them
        ys = [Y0 + 1 + sum(hs[:i]) for i in range(struct_rows + 1)]
    e.uc.mem_write(ROLL + 0xA944, struct.pack(f"<{struct_rows + 1}i", *ys))
    e.uc.mem_write(ROLL + 0xAE74, bytes([pads]))
    if fold is not None:
        e.uc.mem_write(ROLL + 0xB2B4, b"\1")
        e.w32(ROLL + 0xB43C, len(fold))
        e.w32(ROLL + 0xB440, 0)
        e.uc.mem_write(ROLL + 0xB2B8, struct.pack(f"<{len(fold)}i", *fold))
    e.uc.mem_write(VIEW + 0xB49C, struct.pack("<H", pad))
    e.uc.mem_write(VIEW + 0xF5E1, bytes([midi]))
    c = cell(2, 1)                                   # the Slicer under test: pad row 2 col 1 (= pad 10)
    entries = [(0x8B, mode), (0x14D, chop)]
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in entries))
    e.w32(c + 4, ARR)
    e.uc.mem_write(c + 10, struct.pack("<H", len(entries)))
    e.w32(c + 0x28, ARR + 0x100)
    e.w32(c + 0x2C, slices)
    e.uc.mem_write(DC, bytes([full, 1, 0, 0]) + struct.pack("<I", CTX))


def thumb(x):
    """The scroll bar's thumb (a 9-wide fill in colour 1 at the roll's left edge) is placed on the pitch range, which
    3.5.l widened to 1..127 (test_pianofold.py checks it): its size is not this suite's business."""
    return ("thumb",) if x[0] == "fill" and x[1][0] == X0 + 1 and x[1][2] == 9 and x[2] == 1 else x


def draw(**kw):
    out = []
    for e in (es, ep):
        world(e, **kw)
        e.log.clear()
        e.call(0x080BC974, ROLL, DC)
        out.append([thumb(x) for x in e.log])
    stock, ours = out
    ok = (stock and stock[-1] == ("children", ROLL, DC) and ours[-1] == stock[-1] and ours[:len(stock) - 1] == stock[:-1])
    return ok, ours[len(stock) - 1:-1], stock


def label_y(i, h=12):
    return Y0 + 1 + h * i + ((h - 8) >> 1)


# --- 12 slices, keys C2..B2
ok, extra, stock = draw()
check("Slicer, 12 slices: every stock call unchanged and in order, ours after the key strip, children last", ok)
texts = [(t, r[0], r[1], c) for kind, t, r, c in [x for x in extra if x[0] == "text"]]
want = []
for k in range(12):
    note = 36 + k
    i = note - 30
    black = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0][note % 12]
    x = 28 if k == 0 else 13
    want.append((str(k + 1), x, label_y(i), 2))
check("... C2 -> '1' (at the key's right edge, beside stock's C2), C#2 -> '2' .. B2 -> '12', all in colour 2",
      texts == want, (texts, want))
fills = [x for x in extra if x[0] == "fill"]
wantf = [("fill", (10, Y0 + 1 + 12 * (n - 30) + 1, 24, 11), 15) for n in (37, 39, 42, 44, 46)]
check("... the 5 black keys with a slice (C#2 D#2 F#2 G#2 A#2) repainted white (15) inside their row lines, each just "
      "before its number", fills == wantf and all(extra[extra.index(f) + 1][0] == "text" for f in fills), fills)
lines = {x[1][1] for x in stock if x[0] == "line" and x[1][0] == 10}
check("... the repaint leaves stock's row separators alone (each row's line y and the next row's are outside it)",
      all(f[1][1] - 1 in lines and f[1][1] + f[1][3] in lines and f[1][1] - 1 not in range(f[1][1], f[1][1] + f[1][3])
          for f in fills), (fills, sorted(lines)[:8]))
ok, extra_b, _ = draw(slices=1)
check("... with 1 slice the black keys above C2 stay stock (no repaint without a number)",
      [x[0] for x in extra_b] == ["text"], extra_b)
c2 = [x for x in stock if x[0] == "text" and x[1] == "C2"]
check("... stock still draws 'C2' and the number's y is that label's y",
      len(c2) == 1 and c2[0][2][1] == texts[0][2] and c2[0][2][0] == 13, c2)

# --- 40 slices: C3 / C4 take 2 digits, the label goes
ok, extra, stock = draw(slices=40)
check("40 slices: stock calls unchanged", ok)
texts = [x[1] for x in extra if x[0] == "text"]
check("... numbers 1..24 on notes 36..59 (the rows shown), none on 30..35", texts == [str(k) for k in range(1, 25)], texts)
fills = [x for x in extra if x[0] == "fill" and x[1][2] == 12]       # label erases (key repaints are 24 wide)
c3 = [x for x in stock if x[0] == "text" and x[1] == "C3"][0]
check("... C3: its 'C3' label erased in the white key's colour 15 over exactly the label (x 13, its y, 12 x 8), "
      "then '13' at x 13", fills == [("fill", (13, c3[2][1], 12, 8), 15)]
      and ("text", "13", (13, c3[2][1], 0x28, 0x14), 2) in extra
      and extra.index(fills[0]) + 1 == extra.index(("text", "13", (13, c3[2][1], 0x28, 0x14), 2)), (fills, c3))

# --- slices running out mid-screen, and a higher window
ok, extra, _ = draw(slices=5, base=40, rows=20)
texts = [x[1] for x in extra if x[0] == "text"]
check("5 slices seen from E2 up: '5' on E2 (note 40) only; nothing past the 5th slice", ok and texts == ["5"], texts)
ok, extra, _ = draw(slices=12, base=0, rows=36)
check("a window that ends below C2 (notes 0..35): nothing", ok and extra == [], extra)

# --- ChopShop
ok, extra_c, _ = draw(chop=1)
ok2, extra_s, _ = draw()
check("ChopShop (Slicer + 0x14d) gets the same numbers as a plain Slicer", ok and extra_c == extra_s and extra_c, extra_c)
ok, extra_c, _ = draw(chop=7)
check("... with a chop type set (0x14d = 7: Find)", ok and extra_c == extra_s, extra_c)

# --- exactly stock
for name, kw in [("a Sample / multisample pad (0x8b 0) with a slice list", dict(mode=0)),
                 ("a Clip pad (0x8b 1)", dict(mode=1)),
                 ("a Clip pad with a stray ChopShop flag (0x8b 1, 0x14d 1): keyed on 0x8b, not the flag",
                  dict(mode=1, chop=1)),
                 ("a Granular pad (0x8b 3)", dict(mode=3)),
                 ("a Slicer with no slices", dict(slices=0)),
                 ("a Pads sequence (roll + 0xae74) on a Slicer", dict(pads=1)),
                 ("a MIDI sequence (view + 0xf5e1) with the Slicer's id still in view + 0xb49c", dict(midi=1, pad=0x21)),
                 ("the Play Pad elsewhere (pad 1, a Sample pad)", dict(pad=0x00)),
                 ("a bad pad id (row 4)", dict(pad=0x41)),
                 ("a bad pad id (col 4)", dict(pad=0x24)),
                 ("a partial draw (dc[0] = 0)", dict(full=0))]:
    ok, extra, stock = draw(**kw)
    check(f"{name}: draws exactly as stock", ok and extra == [], extra[:4])

# --- zoom: one decision per zoom (3.5.k skipped single 9 px rows), white at every zoom
def rows_of(hs, base=30):
    ys = [Y0 + 1 + sum(hs[:i]) for i in range(len(hs) + 1)]
    return ys


for name, hs in [("9, 9, 9, 10 px rows (an Event-view roll at 12 rows; glass: only every 4th key numbered)",
                  [9, 9, 9, 10] * 7),
                 ("9 / 10 px rows as 18 full-height rows make them", [9, 10, 9, 10, 10, 9, 10, 9, 10, 10, 9, 10, 9, 10, 10,
                                                                      9, 10, 10, 9, 10, 9, 10, 10, 9, 9, 10, 10, 9]),
                 ("every row 9 px", [9] * 28)]:
    ok, extra, stock = draw(hs=hs, rows=len(hs), slices=20)
    ys = rows_of(hs)
    texts = [x for x in extra if x[0] == "text"]
    nums = [int(t[1]) for t in texts]
    inside = all(ys[n - 1 + 6] < t[2][1] and t[2][1] + 8 <= ys[n + 6] for t, n in zip(texts, nums))
    whites = {x[1][1] for x in extra if x[0] == "fill" and x[1][2] == 24}
    want_w = {ys[36 + k - 30] + 1 for k in range(20) if [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0][(36 + k) % 12]}
    check(f"{name}: stock calls unchanged; every one of the 20 chop keys numbered (no holes), each number inside its "
          "row's lines, every black chop key white", ok and nums == list(range(1, 21)) and inside and whites == want_w,
          (nums, inside, sorted(whites - want_w), sorted(want_w - whites)))
ok, extra, stock = draw(hs=[9] * 28, rows=28, slices=20)
c2 = [x for x in extra if x[0] == "text" and x[1] == "1"]
check("... at 9 px stock draws no 'C2' (its labels need 10): '1' takes the label's place (x 13), no label erase",
      c2 and c2[0][2][0] == 13 and not [x for x in stock if x[0] == "text" and x[1] == "C2"]
      and not [x for x in extra if x[0] == "fill" and x[1][2] == 12], c2)
for name, hs, fill_h in [("8 / 9 px rows (average under 9)", [8, 9] * 12, None), ("5 px rows", [5] * 24, 4),
                         ("2 px rows", [2] * 24, 1), ("1 px rows", [1] * 24, 0)]:
    ok, extra, stock = draw(hs=hs, rows=len(hs), slices=20)
    fills = [x for x in extra if x[0] == "fill"]
    ys = rows_of(hs)
    good = all(f[1][1] == ys[i] + 1 and f[1][1] + f[1][3] == ys[i + 1] for f in fills
               for i in [ys.index(f[1][1] - 1)])
    nblack = sum(1 for k in range(20) if [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0][(36 + k) % 12] and 36 + k - 30 < len(hs))
    check(f"{name}: no numbers; " + ("every black chop key repainted white between its row lines (the separators stay)"
          if fill_h else "nothing to repaint (a 1 px row is only its line)" if fill_h == 0 else
          "black chop keys still white"), ok and not [x for x in extra if x[0] == "text"] and good and
          len(fills) == (0 if fill_h == 0 else nblack), (len(fills), nblack, extra[:3]))

# --- Fold: every row labelled by stock
fold = [30, 36, 37, 41, 49, 60, 70]
ok, extra, stock = draw(fold=fold, slices=30)
check("Fold (rows 30 36 37 41 49 60 70), 30 slices: stock calls unchanged", ok)
lab = {x[1]: x[2] for x in stock if x[0] == "text"}
ky = lambda i: (10, Y0 + 1 + 12 * i + 1, 24, 11)
want = [("text", "1", (28, lab["C2"][1], 0x28, 0x14), 2),
        ("fill", ky(2), 15), ("text", "2", (13, lab["C#2"][1], 0x28, 0x14), 2),
        ("text", "6", (28, lab["F2"][1], 0x28, 0x14), 2),
        ("fill", ky(4), 15), ("text", "14", (13, lab["C#3"][1], 0x28, 0x14), 2),
        ("fill", (13, lab["C4"][1], 12, 8), 15), ("text", "25", (13, lab["C4"][1], 0x28, 0x14), 2)]
check("... C2 keeps its label + '1' right, F2 keeps 'F2' + '6' right, C#2 / C#3 repainted white (label gone) with 2 / 14, "
      "C4's label erased for 25, "
      "A#4 (slice 35 > 30) and A#1 nothing", extra == want, (extra, want))

print(f"{fails} failed")
sys.exit(1 if fails else 0)
