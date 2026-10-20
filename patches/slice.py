"""Slicer knobs: bottom = Start / End of the selected slice, top-right = Zoom (see src/slice.c). Apply together with `cave`."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # Slicer-mode setup: the two "unbind bottom knob" calls
    hook(0x080A58F2, 0x080A7EE0, "slice_bind_start"),
    hook(0x080A58FE, 0x080A7EE0, "slice_bind_end"),
    # every refresh of the stock Slice Pos knob: zoom changed, setup (rebinds it as Zoom), later refresh, slice selected
    hook(0x080A52EE, 0x080A5210, "slice_refresh"),
    hook(0x080A58E6, 0x080A5210, "slice_setup"),
    hook(0x080A5B64, 0x080A5210, "slice_refresh"),
    hook(0x080A6C86, 0x080A5210, "slice_selected"),
    # stock Slice Pos message (nothing sends it now)
    hook(0x080A6C8E, 0x080A53B8, "slice_pos_moved"),
    # generic knob-change forward: intercept the private Start/End/Zoom ids
    hook(0x080A6C6C, 0x080AED14, "slice_forward"),
]

# Waveform screen corner labels (src/wavelabel.c): its four hooks ride with this set, which already owns the Waveform
# screen's knobs, so the image keeps the name every suite opens. patches/wavelabel.py holds them.
from wavelabel import PATCHES as WAVELABEL  # noqa: E402

PATCHES += WAVELABEL
