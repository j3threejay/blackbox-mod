"""Slicer knobs: bottom = Start / End of the selected slice, top-right = Zoom (see src/slice.c); Clip pads: tempo from a
selection, Waveform knobs Start / End / Beats / BPM (see src/clipsel.c). Apply together with `cave`."""
import os

from thumb import ROOT, bl, bw, symbols, word

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
    # Clip selection (src/clipsel.c), engine: setup through a trampoline (one patch for all nine callers; the stub in
    # clipsel_thunk.S replays the push.w {r4-r8, sb, lr} it replaces), setup's two file-length calls, the three
    # spawns, the Quant / Sync regrid tail call
    (0x08064A94, bytes.fromhex("2de9f043"), bw(0x08064A94, sym["sel_setup"])),
    hook(0x08064B2C, 0x080636F0, "sel_len_b"),
    hook(0x08064C5A, 0x080636F0, "sel_len_b"),
    hook(0x08065A9A, 0x08065550, "sel_spawn"),
    hook(0x08066CF2, 0x08065550, "sel_spawn"),
    hook(0x08066B9A, 0x08065550, "sel_spawn"),
    (0x080679DA, bw(0x080679DA, 0x08064E7C), bw(0x080679DA, sym["sel_regrid"])),
    # ... Waveform screen, Clip mode: the four "unbind" calls, the waveform update, the zoom re-range
    hook(0x080A5806, 0x080A7EE0, "sel_bind_start"),
    hook(0x080A5812, 0x080A7EE0, "sel_bind_end"),
    hook(0x080A581E, 0x080A7EE0, "sel_bind_beats"),
    hook(0x080A582A, 0x080A7EE0, "sel_bind_bpm"),
    hook(0x080A5B0E, 0x080C6E8C, "sel_wave"),
    hook(0x080A53B0, 0x080A52C4, "sel_zoom"),
    # ... Clip pads play while stopped (the block, and its param handler), position knobs accelerate
    hook(0x08068C6A, 0x08067FA4, "sel_block"),
    hook(0x080685D2, 0x08067648, "sel_param"),
    hook(0x080B0E88, 0x080B0CE0, "sel_accel"),
    # ... and the knob value text: the BPM knob shows tenths ("123.6")
    hook(0x080B06E4, 0x080C3B98, "sel_knob_text"),
    # ... the Waveform view's per-frame tick (vtable slot 0): a finished detection lands without waiting for a redraw
    (0x080F0004, word(0x080A6F21), word(sym["sel_view_tick"] | 1)),
    (0x080F1284, word(0x080B9591), word(sym["chop_view_tick"] | 1)),   # the pad view's tick: the Roll row's cue
    # ... a new sample clears the selection: every place stock resets its own Start / Length (FUN_0809aa94), but the
    # project loader's call for empty pads (0x0809CB78)
    hook(0x0809D618, 0x0809AA94, "sel_reset_cell"),     # recording done (x3)
    hook(0x0809D664, 0x0809AA94, "sel_reset_cell"),
    hook(0x0809D6A6, 0x0809AA94, "sel_reset_cell"),
    hook(0x0809DD30, 0x0809AA94, "sel_reset_cell"),     # a fresh WAV header (sample assigned)
    hook(0x0809F7CA, 0x0809AA94, "sel_reset_cell"),     # a pad rebuilt
    hook(0x080A004E, 0x0809AA94, "sel_reset_cell"),     # set-param handler (FUN_0809fa50): mode paths
    hook(0x080A01F6, 0x0809AA94, "sel_reset_cell"),     # the mode change
    hook(0x080A0CBA, 0x0809AA94, "sel_reset_cell"),     # an empty pad given a sample (0xdf set)
    # ... and the two new-sample paths that skip FUN_0809aa94: stock's own write there, then the selection goes
    hook(0x080A0B6C, 0x08093ECC, "sel_assign_clear"),   # a sample assigned to a pad that had one (0x90 = 0)
    hook(0x0809D622, 0x08093ECC, "sel_assign_clear"),   # recording done (0x95), after a reset
    hook(0x0809D686, 0x08093ECC, "sel_assign_clear"),   # recording done (0x95) into a pad already in Clip mode
    # ChopShop (src/chopmode.c, research/slicer/MODE_LIST_RE.md): the Mode list gets a 7th entry (Slicer + flag)
    (0x0808D0E4, word(0x080EC87C), word(sym["chop_mode_names"])),       # the names: our 7-entry table
    (0x0808CF0E, bytes.fromhex("0621"), bytes.fromhex("0721")),          # movs r1,#6 -> #7 (the count)
    hook(0x080A1BE6, 0x0809FA50, "chop_set"),           # app msg 0x6e: positions -> stored mode + flag; Chop / Roll run
    hook(0x080A5A5A, 0x080BD74E, "chop_show_wave"),     # the Waveform screen's Mode popup highlight
    hook(0x080B8AA2, 0x080BD74E, "chop_show_pad"),      # the pad view's Mode popup highlight
    hook(0x080B8956, 0x08098D40, "chop_pages"),         # the pad view's pages: Chop + Roll on ChopShop's POS page
    hook(0x0809DD28, 0x08093ECC, "chop_header_mode"),   # a fresh WAV header's mode: ChopShop stays ChopShop
    hook(0x0809DEF2, 0x080B5758, "chop_header_post"),   # ... and its refresh: chop the new sample
]
