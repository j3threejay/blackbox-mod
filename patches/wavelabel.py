"""Waveform screen: the four corner knobs' text white with a 1 px black edge, in every pad mode (see src/wavelabel.c).

Rides with the `slice` set (patches/slice.py imports it), which already owns the Waveform screen's knobs, so the patched
image keeps its name. Apply together with `cave`."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # the end of the Waveform view's constructor (FUN_080a5b90), which greys each corner knob's three labels once:
    # TL, BL, TR, BR
    hook(0x080A660A, 0x080B02E6, "wavelabel"),
    hook(0x080A6612, 0x080B02E6, "wavelabel"),
    hook(0x080A661A, 0x080B02E6, "wavelabel"),
    hook(0x080A6622, 0x080B02E6, "wavelabel"),
]
