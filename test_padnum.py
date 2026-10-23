"""Pad numbers on the pad picker (src/padnum.c) under Unicorn.

Real firmware runs for: the pad picker's whole constructor (FUN_080ae6f8) with the hook in it, the button class's
label setter and restyle, and the picker's own layout (FUN_080ae81e) to place the squares on screen.
Checked: each square's label is stock's number for where it sits (1 bottom left, across, then up), every square has
one, the text takes the restyled colour, the stock image leaves them blank.
NOT run: the draw (that the label shows inside a 32 x 32 square, readable on the selected fill), the nine screens
that build a picker, touching a square.
"""
import sys

from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
VIEW, RECT = 0x24050000, 0x24058000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def build(image):
    e = Emu(image, "out/cave.elf")
    e.uc.mem_write(VIEW, bytes(0x1000))
    e.call(0x080AE6F8, VIEW)
    e.uc.mem_write(RECT, (10).to_bytes(4, "little") + (200).to_bytes(4, "little"))
    e.call(0x080AE81E, VIEW, RECT)                     # layout: anchor x 10, bottom y 200
    cells = []
    for a in range(4):                                 # the constructor's own walk: a = row from the top, b = column
        for b in range(4):
            c = VIEW + 0x34 + a * 0x2B0 + b * 0xAC
            raw = bytes(e.uc.mem_read(c + 0x34 + 0x31, 32))
            cells.append(dict(pos=e.r32(c + 0xA4) & 0xFFFF, x=e.r32(c + 4), y=e.r32(c + 8),
                              text=raw.split(b"\0")[0].decode(), colour=e.uc.mem_read(c + 0x87, 1)[0]))
    return cells


cells = build(IMG)
ys = sorted({c["y"] for c in cells})
xs = sorted({c["x"] for c in cells})
check("4 rows and 4 columns on screen", len(ys) == 4 and len(xs) == 4, (xs, ys))
want = {}
for c in cells:
    row_from_bottom = ys.index(c["y"])                # the GUI's y runs up from the bottom
    want[(c["x"], c["y"])] = str(row_from_bottom * 4 + xs.index(c["x"]) + 1)
bad = [(c["pos"], c["text"], want[(c["x"], c["y"])]) for c in cells if c["text"] != want[(c["x"], c["y"])]]
check("every square reads stock's number for where it sits (1 bottom left)", not bad, bad)
check("pad id 0 (the ducker's pad 1) is labelled 1", [c["text"] for c in cells if c["pos"] == 0] == ["1"])
check("all 16 numbers once", sorted(int(c["text"] or 0) for c in cells) == list(range(1, 17)))
bl = [c for c in cells if c["y"] == ys[0] and c["x"] == xs[0]][0]
tr = [c for c in cells if c["y"] == ys[-1] and c["x"] == xs[-1]][0]
check("bottom left is 1, top right is 16", bl["text"] == "1" and tr["text"] == "16", (bl, tr))
check("label colour restyled (0x0f, stock's text-on-fill colour)", all(c["colour"] == 0x0F for c in cells),
      sorted({c["colour"] for c in cells}))

stock = build("firmware/BLACKBOX-3.1.9.bin")
check("stock leaves the squares blank", all(c["text"] == "" for c in stock), [c["text"] for c in stock])

print(f"{fails} failed")
sys.exit(1 if fails else 0)
