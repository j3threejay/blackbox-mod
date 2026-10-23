"""Mixer Solo hooks (see src/solo.c). Apply together with `cave`, which appends the code."""
import os

from thumb import ROOT, bl, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))

PATCHES = [
    # MIX button: set_screen(app, 0x2e/0x2f) -> three-way cycle
    (0x080A32DE, bl(0x080A32DE, 0x0809EAEC), bl(0x080A32DE, sym["solo_mix_pressed"])),
    # GUI mixer (re)show: view set-mode -> arm/disarm Solo
    (0x0808BC40, bl(0x0808BC40, 0x080B5E44), bl(0x0808BC40, sym["solo_set_mode"])),
    # mixer cell mute-mode fills (green, red) -> solo colours + outline
    (0x080A43E0, bl(0x080A43E0, 0x0808EA22), bl(0x080A43E0, sym["solo_mute_fill"])),
    (0x080A43F8, bl(0x080A43F8, 0x0808EA22), bl(0x080A43F8, sym["solo_mute_fill"])),
    # mixer view vtable: touch down / touch move
    (0x080F0F20, word(0x080B5F45), word(sym["solo_touch_down"] | 1)),
    (0x080F0F24, word(0x080B5EBD), word(sym["solo_touch_move"] | 1)),
    # Pads screen: a third position on the lower-right knob (Velocity slider / clipboard / MUTE + SOLO)
    (0x080B4704, bytes.fromhex("0221"), bytes.fromhex("0321")),                       # column stepper: 2 -> 3 positions
    (0x080B43A4, bytes.fromhex("42f65435" "3544"), bl(0x080B43A4, sym["pads_panels_thunk"]) + bytes.fromhex("1de7")),
    (0x080F0E80, word(0x080B3E85), word(sym["pads_child_msg"] | 1)),                  # Pads view vtable +0x30
    (0x080F0E84, word(0x080B4135), word(sym["pads_msg"] | 1)),                        # Pads view vtable +0x34
    # Note repeat (src/repeat.c, 3.3.w): the app's pad-down note-on / pad-up note-off, and the recorder's block tick
    (0x080A0A44, bl(0x080A0A44, 0x0804C61C), bl(0x080A0A44, sym["repeat_pad_down"])),
    (0x080A1A72, bl(0x080A1A72, 0x0804C5D4), bl(0x080A1A72, sym["repeat_pad_up"])),
    (0x0805C936, bl(0x0805C936, 0x08069C38), bl(0x0805C936, sym["repeat_rec_tick"])),
    # pad picker constructor: add each square to the view -> add it and give it its pad number (src/padnum.c)
    (0x080AE776, bl(0x080AE776, 0x080AEC44), bl(0x080AE776, sym["padsel_add_cell"])),
    # Mixer live meters (src/meter.c, meter_thunk.S, 3.3.r): each pad's post-fader mix on its way into the bus, both
    # pad classes, and the Mixer view's tick / draw (vtable slots 0 and 1)
    (0x0805AA12, bl(0x0805AA12, 0x0804DA6C), bl(0x0805AA12, sym["meter_add"])),
    (0x08068C0E, bl(0x08068C0E, 0x0804DA6C), bl(0x08068C0E, sym["meter_add"])),
    (0x080F0F10, word(0x080B6601), word(sym["meter_view_tick"] | 1)),
    (0x080F0F14, word(0x080AEAF9), word(sym["meter_view_draw"] | 1)),
]
