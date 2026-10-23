"""The boot splash (src/splash.c) under Unicorn.

Real firmware runs for: splash_draw against the patched image with the bank 2 this build links (BANK2_NEW: the graphic
is in the new payload), the real b2_present (it sums bank 2 and compares it with what this image was linked with).
Stubbed: stock's generic view draw (FUN_080aeaf8) and the children's draws (fake labels: recorded), the DMA2D CLUT
calls (recorded, with a snapshot of the CLUT memory at the moment it is configured).
Checked: the CLUT = the live palette in 0..33 + the graphic's colours, loaded for both layers, size 34 + colours;
the surface afterwards = the graphic exactly (decoded from make_splash.py's own output); the status lines and (test
build) the version draw on top, the two title labels do not; every fallback goes to stock's draw.
NOT run: the glass (the DMA2D really reading a CLUT out of the surface, the LTDC showing ~2 s of it, the colours).
"""
import os
import re
import struct
import sys

os.environ.setdefault("BANK2_NEW", "1")               # the graphic lives in the payload this build links
from unicorn import UC_HOOK_MEM_WRITE                  # noqa: E402
from unicorn.arm_const import UC_ARM_REG_SP            # noqa: E402

from emu import Emu                                    # noqa: E402

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                       # backup SRAM (b2_present's mark)
e.uc.mem_map(0x58024000, 0x1000)                       # RCC / PWR: bkp_enable
e.uc.mem_map(0x30000000, 0x40000)                      # the view, its children, the surface
PAL, H = 0x24000000, 0x24001FAC + 0xA8
VIEW, ARG, SURF, BUF = 0x30000000, 0x30001000, 0x30001100, 0x30010000
W, HT = 320, 240
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# the expected graphic, from the generator's own output
src = open("src/splash_img.c").read()
colours = int(re.search(r"splash_colours = (\d+);", src).group(1))
clut = [int(x, 16) for x in re.findall(r"0x([0-9a-f]{8})u", src.split("splash_clut")[1].split("};")[0])]
rle = [int(x) for x in re.findall(r"\d+", src.split("splash_rle[")[1].split("{", 1)[1].split("};")[0])]
want = bytearray()
for n, v in zip(rle[0::2], rle[1::2]):
    want += bytes([v]) * n
check(f"generator output: {colours} colours, the run-lengths cover exactly 320 x 240", len(clut) == colours and len(want) == W * HT,
      (len(clut), len(want)))
check("every index in the graphic is 34 or above (never the GUI's own 0..33, never transparent 0)", min(want) >= 34 and max(want) < 34 + colours)
check("every colour opaque", all(c >> 24 == 0xFF for c in clut))

# fake view: six children at the stock offsets, each with a draw that records which one ran
draws = []
OFFS = [0x34, 0x8C, 0xE4, 0x13C, 0x194, 0x1EC]
for k, off in enumerate(OFFS):
    child, vt, code = VIEW + off, 0x30002000 + k * 0x20, 0x30003000 + k * 0x10
    e.uc.mem_write(code, b"\x70\x47")                  # bx lr
    e.w32(vt + 4, code | 1)
    e.w32(child, vt)
    e.uc.mem_write(child + 0x30, b"\0")
    e.w32(child + 0x24, VIEW + OFFS[k + 1] if k + 1 < len(OFFS) else 0)
    e.stub(code, (lambda off=off: draws.append(off)))
e.w32(VIEW + 0x1C, VIEW + OFFS[0])
stock = []
e.stub(0x080AEAF8, lambda: stock.append((e.arg(0), e.arg(1))))
dma = []
e.stub(0x0807AF64, lambda: dma.append(("cfg", e.arg(0), e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(UC_ARM_REG_SP)),
                                        list(struct.unpack(f"<{e.arg(3) + 1}I", bytes(e.uc.mem_read(e.arg(1), 4 * (e.arg(3) + 1))))))), value=0)
e.stub(0x0807AB8C, lambda: dma.append(("on", e.arg(0), e.arg(1))), value=0)
e.stub(0x0807ABC2, lambda: dma.append(("wait",)), value=0)
cleaned = []
e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, sz, v, _: cleaned.append(v & 0xFFFFFFFF), begin=0xE000EF68, end=0xE000EF6B)

palette = [0xFF000000 | (i * 0x070503) for i in range(34)]    # a stand-in theme in RAM
e.uc.mem_write(PAL, struct.pack("<34I", *palette))


def surface(fmt=5, orient=1, w=W, h=HT, buf=BUF):
    e.uc.mem_write(SURF, struct.pack("<IHHBB", buf, w, h, fmt, orient))
    e.w32(ARG + 4, SURF)


def draw():
    draws.clear()
    stock.clear()
    dma.clear()
    cleaned.clear()
    e.uc.mem_write(BUF, bytes(W * HT))
    e.call("splash_draw", VIEW, ARG)


surface()
draw()
cfgs = [d for d in dma if d[0] == "cfg"]
check("the matching bank 2 is there (b2_present): the graphic draws, stock's draw does not", not stock and cfgs, (stock, len(cfgs)))
check(f"CLUT loaded for layers 0 and 1, {34 + colours} entries, from the surface's own buffer, ARGB8888 (mode 0)",
      [(c[1], c[2], c[3], c[4], c[5]) for c in cfgs] == [(H, BUF, 0, 33 + colours, 0), (H, BUF, 0, 33 + colours, 1)], [c[:6] for c in cfgs])
check("... and each one enabled after it", [d for d in dma if d[0] == "on"] == [("on", H, 0), ("on", H, 1)])
check("... a DMA2D wait comes first (the frame's clear of the surface may be a DMA2D fill)", dma and dma[0] == ("wait",), dma[:2])
check("the CLUT the DMA2D reads: the live palette in 0..33, then the graphic's colours", cfgs and cfgs[0][6] == palette + clut,
      cfgs and [hex(v) for v in cfgs[0][6][30:38]])
check("its cache lines cleaned first (the DMA2D reads memory, not the M7's cache)",
      set(range(BUF, BUF + (34 + colours) * 4, 32)) <= set(cleaned), (len(cleaned), [hex(a) for a in cleaned[:3]]))
got = bytes(e.uc.mem_read(BUF, W * HT))
check("the surface afterwards = the graphic, every pixel (the CLUT it was built in is overwritten)", got == bytes(want),
      next((i for i in range(W * HT) if got[i] != want[i]), None))
RELEASE = e.uc.mem_read(e.sym["release_build"], 1)[0]  # a release build leaves the version off (splash.c)
VER = [] if RELEASE else [0x1EC]
check("on top: the three status lines and (test build) the version; not 'blackbox' / 'by 1010music'",
      draws == [0xE4, 0x13C, 0x194] + VER, [hex(d) for d in draws])
e.uc.mem_write(VIEW + 0x13C + 0x30, b"\1")
draw()
check("a hidden child is skipped, as the generic draw does", draws == [0xE4, 0x194] + VER, [hex(d) for d in draws])
e.uc.mem_write(VIEW + 0x13C + 0x30, b"\0")
count = {"n": 0}
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
draw()
e.uc.hook_del(hook)
print(f"     cost: {count['n']} instructions per frame (b2_present's sum over bank 2 included), boot only")

for name, args in (("format 3 (not L8)", dict(fmt=3)), ("orientation 2", dict(orient=2)), ("a 160 px wide surface", dict(w=160)),
                   ("no buffer", dict(buf=0)), ("an unaligned buffer", dict(buf=BUF + 1))):
    surface(**args)
    draw()
    check(f"{name}: stock's draw, nothing else", stock == [(VIEW, ARG)] and not dma and not draws, (stock, len(dma), draws))
surface()
e.w32(ARG + 4, 0)
draw()
check("no surface at all: stock's draw", stock == [(VIEW, ARG)] and not dma)
surface()
b2sum = e.r32(0x0810000C)
e.uc.mem_write(0x0810000C, struct.pack("<I", (b2sum + 1) & 0xFFFFFFFF))
e.uc.mem_write(0x38800000, bytes(0x1000))
draw()
check("bank 2 not the payload this image was linked with (b2_present false): stock's text splash", stock == [(VIEW, ARG)] and not dma, (stock, len(dma)))
e.uc.mem_write(0x0810000C, struct.pack("<i", b2sum))
img = open(IMG, "rb").read()
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
