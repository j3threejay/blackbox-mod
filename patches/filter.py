"""Pad crunch (Interp list) + 24 dB state-variable filter with resonance drive in place of the stock biquad (see src/filter.c). Apply with `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # parameter registration: Interp list 2 -> 9 entries
    hook(0x0808D92A, 0x0808C0D8, "interp_register"),
    # per-voice filter process: sample pads, clip / slicer voices
    hook(0x08055C60, 0x080762D8, "filter_voice_a"),
    hook(0x080669D6, 0x080762D8, "filter_voice_b"),
    # machine modes: note the rate in the voice, park pad / position / rate on the way into the sample-voice reader,
    # then swap its two kernels
    hook(0x08057214, 0x08055F0C, "voice_read_a"),
    hook(0x080574CE, 0x08055F0C, "voice_read_a"),
    hook(0x080575D2, 0x08055F0C, "voice_read_a"),
    hook(0x08057694, 0x08055F0C, "voice_read_a"),
    # clip / slicer voices: their own reader, replaced for the machine modes (3.1.U)
    hook(0x08066622, 0x080662E4, "clip_read_b"),
    hook(0x0805619A, 0x080619D0, "read_normal"),
    hook(0x080561BE, 0x080619D0, "read_normal"),
    hook(0x080561D4, 0x080619D0, "read_normal"),
    hook(0x08056010, 0x08061A64, "read_hq"),
    hook(0x08056098, 0x08061A64, "read_hq"),
    hook(0x080560BC, 0x08061A64, "read_hq"),
    # pad-mode parameter pages (FUN_08098d40, 5 pages x 36 ids per mode), page 4 = the pad page: Interp right under
    # Saturation (0xdb) on Sample, Multisample, Slicer and Clip (stock had it only on Sample / Multisample, further down),
    # and under it Insert (0x1b6) and Input (0x1c7, src/insert.c: the pad's insert effect and the live input
    # played through it); each list grows into its next empty slot(s)
    (0x080EFD38, struct.pack("<12H", 0xDB, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0xF1, 0x6A, 0xD0, 0xF5, 0, 0),
     struct.pack("<12H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0x6A, 0xD0, 0xF5)),      # Sample
    (0x080EFBD0, struct.pack("<11H", 0xDB, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0xF1, 0x6A, 0, 0),
     struct.pack("<11H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xA0, 0xF5, 0xC4, 0x6A)),            # Multisample
    (0x080EF900, struct.pack("<11H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5, 0, 0, 0),
     struct.pack("<11H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5)),            # Slicer
    (0x080EFA68, struct.pack("<11H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5, 0, 0, 0),
     struct.pack("<11H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5)),            # Clip
    # the same three pages in the second copy of the tables (pad cells of class type 0x4c, FUN_08098d40)
    (0x080EF4C8, struct.pack("<12H", 0xDB, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0xF1, 0x6A, 0xD0, 0xF5, 0, 0),
     struct.pack("<12H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xA0, 0xC4, 0x6A, 0xD0, 0xF5)),      # Sample
    (0x080EF1F8, struct.pack("<11H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA0, 0x6A, 0xF5, 0, 0, 0),
     struct.pack("<11H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA0, 0x6A, 0xF5)),            # Slicer
    (0x080EF360, struct.pack("<11H", 0xDB, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5, 0, 0, 0),
     struct.pack("<11H", 0xDB, 0xF1, 0x1B6, 0x1C7, 0x93, 0x95, 0x62, 0xC4, 0xA1, 0x6A, 0xF5)),            # Clip
]

# Clip Window (src/clipwin.c): its hooks ride with this set, which already owns the clip read and the pad pages, so the
# image keeps the name every suite opens. patches/clipwin.py holds them.
from clipwin import PATCHES as CLIPWIN  # noqa: E402

PATCHES += CLIPWIN
