"""Clip Window: per-pad Slip, Region, Loop Len and Fit on Clip pads (see src/clipwin.c, notes/re/README.md sections 2
and 3).

Rides with the `filter` set (patches/filter.py imports it), which already owns the clip reader's call and the pad
pages, so the patched image keeps its name. The clip read itself needs no patch here: filter.py's hook at 0x08066622
goes to clip_read_b (src/filter_thunk.S), which now continues into clipwin_read. Apply together with `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # segment starts: the source prefetch in FUN_08065550 (every non-slice segment: launch, steps, wraps) and in
    # FUN_08065290 (slice-marker segments)
    hook(0x0806578C, 0x0806375C, "clipwin_seg_start_b"),
    hook(0x0806541A, 0x0806375C, "clipwin_slice_start_b"),
    # Region: the clip's length where it shapes the clip (H3: the recompute's two - the second also times a clip of one
    # step by the clip, and stores a fitted pad's step fields again (Fit) -, FUN_08065550's > 0 check and the last
    # step's end; never the reader's bound at 0x080662F6), and the recompute at the two wraps (H3')
    hook(0x08064B2C, 0x080636F0, "clipwin_len_recompute_b"),
    hook(0x08064C5A, 0x080636F0, "clipwin_len_steps_b"),
    hook(0x0806561E, 0x080636F0, "clipwin_len_b"),
    hook(0x08065690, 0x080636F0, "clipwin_len_end_b"),
    hook(0x08066FAC, 0x08064A94, "clipwin_wrap_b"),
    hook(0x08066E9E, 0x08064A94, "clipwin_wrap_free_b"),
    # H5: the render's playhead message (0x4a), the frame heard instead of the segment's own position
    hook(0x080668FC, 0x0804F504, "clipwin_playhead_b"),
    # the knob's value text: set value (every type) and the type-1 turn
    hook(0x080B0746, 0x080B0528, "clipwin_format"),
    hook(0x080B0E18, 0x080B0528, "clipwin_format"),
    # the type-1 turn's stepper call: Slip's acceleration
    hook(0x080B0DDE, 0x080B0B74, "clipwin_turn"),
    # the Waveform screen in Clip mode (FUN_080a54a0): the bind block's last unbind (BR) binds all four knobs, Loop Start /
    # Loop End / Slip / Loop Len; the position knobs' step, range and value after every bind and zoom change
    # (FUN_080a53a2's call); their range and value, the other two's value and the loop bracket at every Clip refresh
    hook(0x080A582A, 0x080A7EE0, "clipwin_bind"),
    hook(0x080A53B0, 0x080A52C4, "clipwin_zoom"),
    hook(0x080A5B0E, 0x080C6E8C, "clipwin_wave"),
    # the waveform's tick, after it placed the playhead line: no line while a Clip view holds on an edge
    hook(0x080C6DCA, 0x080C6ACC, "clipwin_line"),
    # the Clip Pos page (FUN_08098d40 page 1: Loop Mode 0x8d, Beat Count 0xd2, Quant Size 0x47, Sync 0x94, then 32 empty
    # slots), both copies of the tables: Region in slot 5, Slip in slot 6, Loop Len in slot 7, Fit in slot 8, and
    # stock's own Loop Fade row (0xFA, Sample mode's; the class-B pad drops it, the class-H object stores it) in slot 9
    (0x080EF998, struct.pack("<5H", 0, 0, 0, 0, 0), struct.pack("<5H", 0x1C8, 0x1C9, 0x1CA, 0x1CB, 0xFA)),
    (0x080EF290, struct.pack("<5H", 0, 0, 0, 0, 0), struct.pack("<5H", 0x1C8, 0x1C9, 0x1CA, 0x1CB, 0xFA)),
]
