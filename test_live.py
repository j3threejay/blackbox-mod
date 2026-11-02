"""Live mode under Unicorn.

Real firmware runs for: nothing but the patched call site's bytes and the Tools MIDI page table (checked as bytes).
Run from the cave: live_post, live_register, live_defaults.
Stubbed: the engine bus post (recorded), the global settings read (Live Mode, MIDI Seq), the list registration.
NOT run: the MIDI parser feeding live_post and the bus distributor after it, so "the pad sounds at the key's pitch
and velocity" and "the Live Mode row shows on Tools > MIDI" are hardware checks.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import Emu
sys.path.insert(0, "patches")
from thumb import bl  # noqa: E402

OUT = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
e = Emu(OUT, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)              # backup SRAM: live.c's held-note state
e.uc.mem_map(0x58020000, 0x10000)             # RCC / PWR: bkp_enable switches the backup SRAM on
RCC_AHB4ENR = 0x580244E0

APP, ENGINE, EV, STATE = 0x24020088, 0x2400A9C0, 0x24069000, 0x38800990
settings = {0x1F0: 0, 0x79: 16}               # Live Mode Off, MIDI Seq = Ch 16 (the user's keyboard)
fails = 0


def check(cond, what):
    global fails
    if not cond:
        fails += 1
        print("FAIL", what)


def post():
    t, a, note, vel, keyed, tag = struct.unpack("<B7xIIIHH", bytes(e.uc.mem_read(e.arg(1), 24)))
    e.calls.append((t, a, note, vel, keyed))


def get_setting():
    e.uc.reg_write(UC_ARM_REG_R0, settings.get(e.arg(1), 0))


e.stub(0x080518DC, post)
e.stub(0x08093E9C, get_setting)


def select(row, col, layer=0):
    e.uc.mem_write(APP + 0x14, struct.pack("<H", layer << 8 | row << 4 | col))


def midi(kind, ch, note, vel):
    e.uc.mem_write(EV, struct.pack("<B7xIIIHH", kind, ch, note, vel, 0, 0))
    return e.call("live_post", ENGINE, EV)


ON, OFF = 5, 6
e.uc.mem_write(STATE, b"\0" * 0x70)

# Live Mode Off: everything passes through as stock had it
select(1, 2)
check(midi(ON, 15, 60, 100) == [(5, 15, 60, 100, 0)], "off: note on passes through")
check(midi(OFF, 15, 60, 0) == [(6, 15, 60, 0, 0)], "off: note off passes through")

settings[0x1F0] = 1
# On: MIDI Seq channel (Ch 16 = 15) -> pad note on the selected pad (row 1 col 2 -> a = 2 | 1 << 8)
check(midi(ON, 15, 64, 90) == [(0x42, 0x102, 64, 90, 1)], "on: note on goes to the selected pad")
# other channels untouched
check(midi(ON, 9, 36, 127) == [(5, 9, 36, 127, 0)], "on: drums channel passes through")
check(midi(0xC, 15, 64, 50) == [(0xC, 15, 64, 50, 0)], "on: poly pressure passes through")
# select another pad while 64 is held: 64's release goes to the pad that started it, new notes to the new pad
select(3, 0)
check(midi(ON, 15, 67, 80) == [(0x42, 0x300, 67, 80, 1)], "on: new selection plays the new pad")
check(midi(OFF, 15, 64, 0) == [(0x43, 0x102, 64, 0, 1)], "on: release reaches the pad the note started on")
# note on with velocity 0 is a release
check(midi(ON, 15, 67, 0) == [(0x43, 0x300, 67, 0, 1)], "on: velocity-0 note on releases")
# a release nobody started (held from before Live Mode) passes through
check(midi(OFF, 15, 50, 0) == [(6, 15, 50, 0, 0)], "on: stray release passes through")
# the same key twice: the old voice is ended first
midi(ON, 15, 70, 100)
check(midi(ON, 15, 70, 110) == [(0x43, 0x300, 70, 0, 1), (0x42, 0x300, 70, 110, 1)], "on: retrigger ends the old note")
midi(OFF, 15, 70, 0)
# switched Off with a key down: its release still reaches the pad
midi(ON, 15, 72, 100)
settings[0x1F0] = 0
check(midi(OFF, 15, 72, 0) == [(0x43, 0x300, 72, 0, 1)], "off with a key down: release still reaches the pad")
settings[0x1F0] = 1
# selection that is not a pad (a sequence cell, layer 1) or MIDI Seq None: pass through
select(0, 1, layer=1)
check(midi(ON, 15, 60, 100) == [(5, 15, 60, 100, 0)], "on: non-pad selection passes through")
midi(OFF, 15, 60, 0)
select(0, 0)
settings[0x79] = 0
check(midi(ON, 15, 60, 100) == [(5, 15, 60, 100, 0)], "MIDI Seq None passes through")
settings[0x79] = 16
# every pad corner maps row/col straight through
for r, c in ((0, 0), (0, 3), (3, 3)):
    select(r, c)
    got = midi(ON, 15, 48, 100)
    check(got == [(0x42, c | r << 8, 48, 100, 1)], f"pad r{r}c{c}")
    midi(OFF, 15, 48, 0)

# image: the parser's bus post now calls live_post; Live Mode is the 7th row of the Tools MIDI page
img = open(OUT, "rb").read()
o = lambda a: a - 0x08040000  # noqa: E731
sym = e.sym
check(img[o(0x0804CBF0):o(0x0804CBF4)] == bl(0x0804CBF0, sym["live_post"]), "call site patched")
check(struct.unpack("<7H", img[o(0x080EEDA8):o(0x080EEDB6)]) == (0x76, 0xE2, 0x79, 0xD3, 0x71, 0x7B, 0x1F0),
      "Tools MIDI page rows")

# registration: an Off / On list under its own xml name, default Off
regs = []
e.stub(0x0808C0D8, lambda: regs.append((e.arg(1), e.cstr(e.arg(2)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)),
                                        e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.call("live_register", 0x24068000)
check(regs == [(0x1F0, "Live Mode:", 2, "midilivemode")], f"registration {regs}")
adds = []
e.stub(0x08093EF6, lambda: adds.append((e.arg(1), e.arg(2))))
e.call("live_defaults", 0x24068000)
check(adds == [(0x1F0, 0)], f"default {adds}")

check(e.r32(RCC_AHB4ENR) & (1 << 28), "backup SRAM clock switched on before use")
print("live: all checks passed" if not fails else f"live: {fails} FAILED")
sys.exit(1 if fails else 0)
