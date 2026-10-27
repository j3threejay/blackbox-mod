"""Colour themes (src/theme.c) under Unicorn.

Real firmware runs for: the hooks themselves (theme_compose, theme_clear, theme_roll_text, theme_register via
comp_register), against the patched image's tables.
Stubbed: the settings read (FUN_08093e9c: returns the chosen theme), the frame compose (FUN_0808b2d0), the layer clear
(FUN_0808f90c), the text draw (FUN_0808f23c), the list / number registration (recorded).
Checked: Stock leaves the palette and the redraw flags alone; a theme copies its 34 colours and asks for one full
redraw, then nothing more; an out-of-range setting reads as Stock; the full redraw's clear takes palette entry 2 (the
same #141414 on Stock); the piano roll's colour-2 texts become 15 only on a theme; "Theme:" is registered with 4
names and sits at the end of Tools Main; every table colour is the mock-up's colour (make_themes.py).
NOT run: the GUI on the glass (whether every screen repaints, any widget with a cached colour, stock code that might
write the palette itself), the setting's save / load in settings.tml.
"""
import contextlib
import io
import struct
import sys

sys.path.insert(0, "host/themes")
with contextlib.redirect_stdout(io.StringIO()):
    import make_themes as mk
from emu import Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                   # backup SRAM + the RCC page: theme_compose now runs chop_poll
e.uc.mem_map(0x58024000, 0x1000)
PAL, GUI = 0x24000000, 0x24050000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


fw = open(IMG, "rb").read()
STOCK = list(struct.unpack_from("<34I", fw, 0x080F1D80 - 0x08040000))
setting = {"theme": 0}
log = []
e.stub(0x08093E9C, value=None, fn=lambda: e.uc.reg_write(__import__("unicorn").arm_const.UC_ARM_REG_R0,
                                                       setting["theme"] if e.arg(1) == 0x144 else 0))
e.stub(0x0808B2D0, lambda: log.append(("compose", e.arg(0))))
e.stub(0x0808F90C, lambda: log.append(("clear", e.arg(1))))
e.stub(0x0808F23C, lambda: log.append(("text", e.arg(2))))
dma = []
e.stub(0x0807AF64, lambda: dma.append(("cfg", e.arg(0), e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(
    __import__("unicorn").arm_const.UC_ARM_REG_SP)))), value=0)
e.stub(0x0807AB8C, lambda: dma.append(("on", e.arg(0), e.arg(1))), value=0)
e.stub(0x0807ABC2, lambda: dma.append(("wait",)), value=0)
from unicorn import UC_HOOK_MEM_WRITE
cleaned = []
e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, sz, v, _: cleaned.append(v & 0xFFFFFFFF), begin=0xE000EF68, end=0xE000EF6B)
H = 0x24001FAC + 0xA8
CLUT_SEQ = [("wait",), ("cfg", H, PAL, 0, 0x21, 0), ("wait",), ("on", H, 0), ("wait",),
            ("wait",), ("cfg", H, PAL, 0, 0x21, 1), ("wait",), ("on", H, 1), ("wait",)]


def pal():
    return list(struct.unpack("<34I", bytes(e.uc.mem_read(PAL, 136))))


def flags():
    return e.r8(GUI + 0x280 + 0x38), e.r8(GUI + 0x280 + 0x39)


def frame(theme):
    setting["theme"] = theme
    log.clear()
    dma.clear()
    cleaned.clear()
    e.uc.mem_write(GUI + 0x280 + 0x38, b"\0\0")
    e.call("theme_compose", GUI)
    return flags(), list(log)


e.uc.mem_write(PAL, struct.pack("<34I", *STOCK))
f, lg = frame(0)
check("Stock: palette untouched, no redraw asked, no CLUT reload, the frame still composes", pal() == STOCK and f == (0, 0)
      and lg == [("compose", GUI)] and not dma, (f, lg, dma))

shipped = [n for n, _, p in mk.THEMES if p is not None]
want_names = ["Stock 3.1.9", "Midnight", "Blue LCD", "Amber VFD"]
for t in (1, 2, 3):
    f, lg = frame(t)
    mock = mk.THEMES[[n for n, _, _ in mk.THEMES].index(want_names[t])][2]
    want = [0] + [0xFF000000 | int(c[1:], 16) for c in mock[1:]]
    check(f"theme {t} ({want_names[t]}): palette = the mock-up's 34 colours, one full redraw asked",
          pal() == want and f == (1, 1) and lg == [("compose", GUI)], (f, [hex(x) for x in pal()[:6]]))
    check(f"theme {t}: the palette's five cache lines cleaned, then stock's CLUT load for layers 0 and 1 "
          "(the DMA2D colours from its own CLUT, not the RAM palette)",
          cleaned == [0x24000000, 0x24000020, 0x24000040, 0x24000060, 0x24000080] and dma == CLUT_SEQ, (cleaned, dma))
    f, lg = frame(t)
    check(f"theme {t}: the next frame asks for nothing and reloads nothing", f == (0, 0) and not dma, (f, dma))

f, lg = frame(9)
check("an out-of-range setting reads as Stock (palette back, one redraw)", pal() == STOCK and f == (1, 1), f)
frame(0)

e.call("theme_clear", 0x24051000, 0xFF141414)
check("Stock: the full redraw clears with #141414 as before", log[-1] == ("clear", 0xFF141414), log[-1:])
frame(1)
e.call("theme_clear", 0x24051000, 0xFF141414)
check("Midnight: the clear takes the theme's background (entry 2)", log[-1] == ("clear", pal()[2]), (log[-1:], hex(pal()[2])))

for theme, colour, want in [(0, 2, 2), (1, 2, 15), (3, 2, 15), (1, 15, 15), (2, 0xE, 0xE)]:
    setting["theme"] = theme
    log.clear()
    e.call("theme_roll_text", 0x24052000, 0x24052100, colour, 0x24052200)
    check(f"piano roll text: theme {theme}, colour {colour} -> {want}", log == [("text", want)], log)

from unicorn.arm_const import UC_ARM_REG_SP
regs = []


def reg_list():
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    names = [e.cstr(e.r32(e.arg(3) + 4 * i) & 0xFFFFFFFF) for i in range(e.r32(sp))]
    regs.append((e.arg(1), e.cstr(e.arg(2)), names, e.cstr(e.r32(sp + 4) & 0xFFFFFFFF)))


e.stub(0x0808C0D8, reg_list)
e.call("theme_register", 0x24053000)
check('registered: 0x144 "Theme:" Stock / Midnight / Blue LCD / Amber VFD, saved as "theme"',
      regs == [(0x144, "Theme:", ["Stock", "Midnight", "Blue LCD", "Amber VFD"], "theme")], regs)
main = struct.unpack_from("<13H", fw, 0x080EED18 - 0x08040000)
if False:                                            # 3.3.q .. beta 1 had Groove before Theme (13 rows: the tabs bug)
    pass
else:
    check("Tools Main ends with Theme (0x144) after the stock rows", main[11] == 0x144 and main[10] == 0x19B,
          [hex(x) for x in main])

print(f"{fails} failed")
sys.exit(1 if fails else 0)
