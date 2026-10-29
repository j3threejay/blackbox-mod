"""Master FX slot + Compressor / Master FX knob pages (see src/master.c). Apply together with `comp`, `munchi`, `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


def bw(at, target):
    """B.W: BL's encoding with bit 14 of the second halfword clear."""
    h1, h2 = struct.unpack("<HH", bl(at, target))
    return struct.pack("<HH", h1, h2 & ~0x4000)


SET_SCREEN = 0x0809EAEC

PATCHES = [
    # master EQ screen: the graph's draw (vtable 0x080f065c +4) draws the RTA first, then stock's curve (src/rta.c)
    (0x080F0660, word(0x080AA13D), word(sym["rta_graph_draw"] | 1)),
    # engine: the compressor stage runs every block (was: only with Compressor on), so Master FX works with it Off
    (0x0805352E, bytes.fromhex("40f0b383"), bw(0x0805352E, 0x08053C98)),
    # knob screen 0x66 / 0x67 handler: page builder -> ours (master pages for the global cell)
    hook(0x080AB94A, 0x08098D40, "master_list"),
    # INFO on Tools (screens 0x25..0x29, each re-showed Tools): open the knob page of the selected row
    *[hook(at, SET_SCREEN, "master_tools_info") for at in (0x080A3094, 0x080A30A0, 0x080A30AC, 0x080A30B8, 0x080A30C4)],
    # INFO on the knob screen: a master page -> Tools
    (0x080A3064, bytes.fromhex("038dc3f30312"), bl(0x080A3064, sym["master_info_thunk"]) + bytes.fromhex("00bf")),
    # BACK on the knob screen: a master page returns to Tools
    hook(0x080A3220, SET_SCREEN, "master_back"),
    # delay constructor, its third line allocation: also take Prism's SDRAM block (once per boot)
    hook(0x0805462A, 0x0806AA80, "master_alloc"),
    # the card loader (src/b2load.c): the disk task's three calls to the file command step go through it first
    *[hook(at, 0x08092F5C, "b2load_thunk") for at in (0x0807443E, 0x0807446E, 0x080744D8)],
    # per-pad insert (src/insert.c, src/insert_thunk.S): a separate mix buffer for a pad with an insert, and the effect
    # on it after the voices; class A (Sample / Multisample) then class B (Clip / Slicer). Each replaces one
    # `ldrb.w r3, [r4, #stage]`.
    (0x080599EC, bytes.fromhex("94f86035"), bl(0x080599EC, sym["insert_buf_a"])),
    (0x08059A7C, bytes.fromhex("94f86035"), bl(0x08059A7C, sym["insert_run_a"])),
    # ... and the early return when no voice is sounding, so a pad carrying the live input still renders.
    # Same instruction, same byte, pad in r4, in both pad processes.
    (0x08059966, bytes.fromhex("94f82830"), bl(0x08059966, sym["insert_live_a"])),
    (0x08067FD4, bytes.fromhex("94f82830"), bl(0x08067FD4, sym["insert_live_b"])),
    (0x08068830, bytes.fromhex("94f88c3b"), bl(0x08068830, sym["insert_buf_b"])),
    (0x0806889C, bytes.fromhex("94f88c3b"), bl(0x0806889C, sym["insert_run_b"])),
    # INFO on a pad parameter screen: on the Insert row, open its knob page (replaces ldrb.w r3, [r3, #0xcc6])
    (0x080A2FD6, bytes.fromhex("93f8c63c"), bl(0x080A2FD6, sym["insert_info_thunk"])),
    # Tools Main page: Master FX takes Comp Thresh's row (Thresh is on the Compressor knob page now)
    # ... and sits ABOVE Compressor, the order the audio runs in: Master FX, Compressor (its page has the clipper)
    (0x080EED1A, struct.pack("<2H", 0xB4, 0x1D0), struct.pack("<2H", 0x1DB, 0xB4)),
    # Colour themes (src/theme.c): "Theme:" at the end of Tools Main, the palette applied before each GUI frame,
    # the full redraw's clear in the theme's background, three piano roll texts off the background colour
    # Tools Main holds 12 rows at most: the tab-bar fill (FUN_080996b0) writes row i's value at +0x14 + 4i of a 0x80-byte
    # struct with no limit, and row 13 lands on the tab count (+0x44). Beta 1 had 13 (Groove then Theme): the number of
    # tabs drawn = the Theme value (testers 10-24, test_toolstabs.py). Groove lives on the Clock tab since beta 2.
    (0x080EED2E, struct.pack("<2H", 0, 0), struct.pack("<2H", 0x144, 0)),          # Theme, the 12th and last row
    (0x080EEDF8, struct.pack("<2H", 0, 0), struct.pack("<2H", 0x145, 0)),          # Clock tab: Groove (groove.c, 3.3.q)
    (0x08043E4C, bl(0x08043E4C, 0x0808B2D0), bl(0x08043E4C, sym["theme_compose"])),
    # Boot splash (src/splash.c): the splash view's draw (vtable 0x080f19a4 +4, stock = the generic FUN_080aeaf8)
    (0x080F19A8, word(0x080AEAF9), word(sym["splash_draw"] | 1)),
    (0x0808B3A6, bl(0x0808B3A6, 0x0808F90C), bl(0x0808B3A6, sym["theme_clear"])),
    *[(a, bl(a, 0x0808F23C), bl(a, sym["theme_roll_text"])) for a in (0x080BCC5A, 0x080BCECE, 0x080BD010)],
    # Slice numbers on the piano roll's keys (src/pianoslice.c): the roll draw's children draw goes through it
    hook(0x080BD024, 0x080AEAF8, "pianoslice_children"),
    # Piano roll Fold (src/pianofold.c). The layout runs the list step on every layout while folded (was: only with
    # + 0xb44c set too), and the list step is ours: Fold to notes / Scale fold, 1..127, rows = the notes' count
    (0x080BB1A0, bytes.fromhex("2bb1"), bytes.fromhex("00bf")),
    hook(0x080BB286, 0x080BAAA0, "pf_build"),
    hook(0x080BC718, 0x080BBA40, "pf_tap"),                     # key strip double-tap: Off -> Notes -> Scale -> Off
    (0x080F13DC, word(0x080BD049), word(sym["pf_tick"] | 1)),   # roll tick: fold drag scroll, view kept in 1..127
    *[hook(at, 0x080BBB50, "pf_follow") for at in (0x080BBCA0, 0x080BC066, 0x080BC2FE, 0x080BC410)],
    (0x080BBD0A, bytes.fromhex("c7f84034"), bytes.fromhex("00bf00bf")),   # refresh keeps the fold scroll
    hook(0x080C145C, 0x080BFEEC, "pf_refresh"),                 # 0x66: the fold list rebuilt right after
    hook(0x080C17BA, 0x080BBBC4, "pf_pitch"),                   # BR: scale steps, re-centred detents
    hook(0x080C08B8, 0x080BD5B8, "pf_menu_add"),                # EDIT: + Fold Notes, Fold Scale (5 per column)
    (0x080F1688, word(0x080C0A41), word(sym["pf_view_msg"] | 1)),
    # Pitch range 1..127 (stock 24..96 = C1..C7): Keys min base, the vertical scroll widget's count (unread: kept
    # in step), the pitch knob's count, the scroll bar's range, the drag scroll's top (0x61 - rows -> 0x80 - rows)
    (0x080BA0C2, bytes.fromhex("1823"), bytes.fromhex("0123")),
    (0x080BA0D2, bytes.fromhex("4221"), bytes.fromhex("7821")),
    (0x080BA0E8, bytes.fromhex("4921"), bytes.fromhex("7f21")),
    (0x080BCCD6, bytes.fromhex("4921"), bytes.fromhex("7f21")),
    (0x080BD236, bytes.fromhex("c2f16102"), bytes.fromhex("c2f18002")),
]
