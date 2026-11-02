"""Live mode: the MIDI Seq channel plays the selected pad (see src/live.c). Apply together with `cave` and `comp`
(comp.c registers the setting and its default)."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # audio task MIDI parser: note on / note off / poly pressure -> engine bus
    hook(0x0804CBF0, 0x080518DC, "live_post"),
    # Tools MIDI page (0x080eeda8): Global In, 0xe2, MIDI Seq, 0xd3, 0x71, USB Dev Out, then Live Mode in the first
    # empty slot
    (0x080EEDB4, struct.pack("<H", 0), struct.pack("<H", 0x1F0)),
]
