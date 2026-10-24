"""TOOLS tab bar: Main / Rec / MIDI / Clock on every tab, whatever the settings (beta 1 bug, testers 10-24).

Stock's tab-bar fill (FUN_080996b0) writes each row's value at +0x14 + 4i of a 0x80-byte struct with no limit; a 13th
row on a tab lands on the tab count. Beta 1 put 13 rows on Main (Theme last), so the tabs drawn = the Theme value.
Real firmware runs for: the Tools view constructor FUN_080c5450 and its refresh FUN_080c5180 (tab info, page builder,
the tab buttons), on this build's Tools page tables, with EVERY setting read as a non-zero value (the other suites
read settings as 0, which is how this got through).
Stubbed: the settings read FUN_08093e9c (Theme = each theme, everything else 3), the card free-space probe.
Also: the insert page header cut (master_after_build) on a fake knob screen.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0

from emu import Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
TABN = ("Main", "Rec", "MIDI", "Clock")
VIEW = 0x24040000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


e = Emu(IMAGE, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
THEME = [0]


def setting():
    pid = e.arg(1)
    e.uc.reg_write(UC_ARM_REG_R0, THEME[0] if pid == 0x144 else 3)


e.stub(0x08093E9C, fn=setting, value=None)
e.stub(0x0809BBF8, value=0)


def tools(theme, tab):
    THEME[0] = theme
    e.uc.mem_write(VIEW, bytes(0xB000))
    e.call(0x080C5450, VIEW, count=5_000_000)
    e.uc.mem_write(VIEW + 0xA5E0, bytes([tab]))
    e.call(0x080C5180, VIEW, count=20_000_000)
    names = [bytes(e.uc.mem_read(VIEW + 0xA560 + 0x4D + 8 * i, 8)).split(b"\0")[0].decode("latin1") for i in range(4)]
    return e.r32(VIEW + 0xA5A4), names


for tab in range(4):
    for theme, tname in enumerate(("Stock", "Midnight", "Blue LCD", "Amber VFD")):
        count, names = tools(theme, tab)
        check(f"TOOLS {TABN[tab]}, Theme {tname}, every other setting non-zero: four tabs, Main / Rec / MIDI / Clock",
              count == 4 and names == list(TABN), (count, names))


def rows(addr):
    out = []
    while True:
        v = struct.unpack("<H", e.uc.mem_read(addr + 2 * len(out), 2))[0]
        if not v:
            return out
        out.append(v)


main, clock = rows(0x080EED18), rows(0x080EEDF0)
check(f"Tools Main has at most 12 rows ({len(main)}); Theme is its last", len(main) <= 12 and main[-1] == 0x144, [hex(r) for r in main])
check("Groove sits on the Clock tab", 0x145 in clock and 0x145 not in main, [hex(r) for r in clock])

# --- insert page header: the sample name without ".wav", 8 characters at most. The label setter is stubbed (it needs a
# real button); its string lives at button + 0x34 + 0x31 = +0x65 (READ: FUN_080a3dec -> FUN_080c3b98 strncpy @0x080c3bce).
SCREEN = 0x24050000
labels = {}
def set_label():
    labels[e.arg(0) - SCREEN] = e.cstr(e.arg(1))
    e.uc.mem_write(e.arg(0) + 0x65, e.cstr(e.arg(1)).encode() + b"\0")
e.stub(0x080A3DEC, set_label)
for name, want in (("Kick 37.wav", "Kick 37"), ("KM_DM_TOPLOOP 37.wav", "KM_DM_TO"), ("Snare.WAV", "Snare"), ("Hat", "Hat")):
    e.uc.mem_write(SCREEN, bytes(0x1000))
    e.uc.mem_write(SCREEN + 0x3AC + 0x65, name.encode() + b"\0")
    e.uc.mem_write(0x38800B1C, bytes([3, 1]))                               # master UI: page = PAGE_INS, active
    e.call("master_after_build", SCREEN)
    got = bytes(e.uc.mem_read(SCREEN + 0x3AC + 0x65, 32)).split(b"\0")[0].decode()
    check(f"insert page header {name!r} -> {want!r}", got == want, got)
e.uc.mem_write(0x38800B1C, bytes([1, 1]))                                   # a Master FX page
e.uc.mem_write(SCREEN + 0x3AC + 0x65, b"KM_DM_TOPLOOP 37.wav\0")
e.call("master_after_build", SCREEN)
labels.clear()
e.call("master_after_build", SCREEN)
check("any other knob page: header untouched", not labels and bytes(e.uc.mem_read(SCREEN + 0x3AC + 0x65, 20)) == b"KM_DM_TOPLOOP 37.wav", labels)

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
