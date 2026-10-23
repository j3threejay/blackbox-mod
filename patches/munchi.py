"""Munchi Delay in the delay slot: Type Delay / Munchi (see src/munchi.cpp). Apply together with `cave`."""
import os

from thumb import ROOT, bl, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    hook(0x0808DE8E, 0x0808C0D8, "munchi_register"),        # param 0x197 'FX1:' -> "Type:" Delay/Munchi + 3 settings
    hook(0x0809444A, 0x08093EF6, "munchi_defaults_first"),  # delay cell defaults: Type first
    hook(0x08094494, 0x08093EF6, "munchi_defaults_last"),   # ... Wand / Random / Freeze last
    hook(0x08054F3A, 0x080548C8, "munchi_process"),         # delay vtable wrapper: the process call
    hook(0x08098E72, 0x080A50FC, "munchi_list"),            # settings-list fill: per-Type controls on the FX pages
    hook(0x0808BA8A, 0x080AB880, "fxout_open"),             # knob screen opened (GUI msg 0x9d): the knobs, not FX OUT
    # the engine's "Out 1 += effect return" (3.3.x): the FX OUT page's Output picks the bus (fxret_thunk.S, fxout.c)
    (0x08053506, bl(0x08053506, 0x0804DA6C), bl(0x08053506, sym["fxret_dly_thunk"])),
    (0x08053516, bl(0x08053516, 0x0804DA6C), bl(0x08053516, sym["fxret_rev_thunk"])),
    # FX knob screen vtable +0x10 (message handler): rebuild the page after a Type change
    (0x080F07F0, word(0x080AB901), word(sym["fx_screen_msg"] | 1)),
    # ... and its +0x30 (what its children send up): a tap on the OUT tab flips to the FX OUT page (fxout.c)
    (0x080F07EC, word(0x080AB9B5), word(sym["fx_screen_child"] | 1)),
]
