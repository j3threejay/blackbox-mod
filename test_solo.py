"""Run the patched image's solo code under Unicorn against a fake mixer view.

Real firmware runs for: cell set-unmuted (0x080a4f10), view set-mode (0x080b5e44), cell set-mode.
Stubbed and recorded: post msg, hit-test, set-screen, fill, outline, original touch handlers.
"""
import struct
import subprocess
import sys

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

BASE = 0x08040000
IMG = open("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "rb").read()
SYM = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(
    ["arm-none-eabi-nm", "out/cave.elf"], capture_output=True, text=True).stdout.splitlines()}

VIEW, APP, PT, STACK, RET = 0x24070000, 0x24060000, 0x24078000, 0x2407F000, 0x0807FFF0
STATE = 0x2405FF60

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x08000000, 0x200000)
uc.mem_write(BASE, IMG)
uc.mem_map(0x24000000, 0x80000)
uc.mem_map(0x38800000, 0x1000)                    # backup SRAM + RCC: note repeat's state lookup (repeat.c, 3.3.w)
uc.mem_map(0x58024000, 0x1000)
uc.mem_write(RET, b"\x00\xbf\x00\xbf")
uc.mem_write(STATE, b"\xa5" * 64)  # uninitialised RAM: ensure() must cope

calls = []


def cell(i):
    return VIEW + 0x3AC + i * 0x1A0


def REC(i):
    return 0x24020088 + 0x8A88 + (i // 4) * 0x78 + (i % 4) * 0x18 + 0xD


def rd8(a):
    return uc.mem_read(a, 1)[0]


def rd32(a):
    return struct.unpack("<I", uc.mem_read(a, 4))[0]


def ret(value=None):
    if value is not None:
        uc.reg_write(UC_ARM_REG_R0, value)
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


def stub(addr, fn):
    STUBS[addr] = fn


STUBS = {}


def mirror():
    """What the app's msg 0x44 handler does: muted flag into the pad record."""
    m = uc.reg_read(UC_ARM_REG_R1)
    pad = struct.unpack("<H", uc.mem_read(m + 8, 2))[0]
    uc.mem_write(REC((pad >> 4 & 0xF) * 4 + (pad & 0xF)), bytes([rd32(m + 12) == 0]))


stub(0x080AED14, lambda: (calls.append(("post", *struct.unpack("<HHIHHIII", uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 24))[0::2][:1],
                                         struct.unpack("<H", uc.mem_read(uc.reg_read(UC_ARM_REG_R1) + 8, 2))[0],
                                         rd32(uc.reg_read(UC_ARM_REG_R1) + 12))), mirror(), ret()))
stub(0x080B5E78, lambda: (uc.mem_write(uc.reg_read(UC_ARM_REG_R2), struct.pack("<I", cell(rd32(uc.reg_read(UC_ARM_REG_R1))))), ret(1)))
stub(0x0809EAEC, lambda: (calls.append(("screen", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x0808EA22, lambda: (calls.append(("fill", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x0808E994, lambda: (calls.append(("outline", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x080B5F44, lambda: (calls.append(("orig_down",)), ret()))
stub(0x080B5EBC, lambda: (calls.append(("orig_move",)), ret()))


def on_code(uc, addr, size, _):
    if addr in STUBS:
        STUBS[addr]()


uc.hook_add(UC_HOOK_CODE, on_code)


def call(name_or_addr, *args):
    addr = SYM[name_or_addr] if isinstance(name_or_addr, str) else name_or_addr
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v)
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    calls.clear()
    uc.emu_start(addr | 1, RET, count=200000)
    return list(calls)


def set_screen(s):
    uc.mem_write(APP + 0x8CA4, bytes([s]))


def unmuted():
    return [rd8(cell(i) + 0x189) for i in range(16)]


def touch(i):
    uc.mem_write(PT, struct.pack("<I", i))
    return call("solo_touch_down", VIEW, PT, 0)


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# fake view: 16 cells, pad id = row<<4|col, all unmuted, no parent for post()
for i in range(16):
    uc.mem_write(cell(i) + 0x38, struct.pack("<H", (i // 4) << 4 | (i % 4)))
    uc.mem_write(cell(i) + 0x189, b"\x01")
uc.mem_write(VIEW + 0x2C, b"\0\0\0\0")

# Mixer -> Mute
set_screen(0x2E)
check("MIX on Mixer goes to Mute (0x2f)", call("solo_mix_pressed", APP, 0x2F, 0, 0) == [("screen", 0x2F)])
call("solo_set_mode", VIEW, 1)
check("Mute mode is not Solo", rd8(STATE + 4) == 0)
check("view mute flag set by real set-mode", rd8(VIEW + 0x1E40) == 1)
check("touch in Mute mode reaches the original handler", touch(3) == [("orig_down",)])

# Mute -> Solo
set_screen(0x2F)
check("MIX on Mute re-enters 0x2f", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2F)])
call("solo_set_mode", VIEW, 1)
check("Solo mode active", rd8(STATE + 4) == 1)

# pad 5 muted beforehand
uc.mem_write(cell(5) + 0x189, b"\x00")
c = touch(2)
posts = [x for x in c if x[0] == "post"]
check("solo pad 2: 14 mute posts (pad 5 already muted, pad 2 stays)", len(posts) == 14 and all(p[3] == 0 for p in posts))
check("solo pad 2: posts carry msg 0x44", all(p[1] == 0x44 for p in posts))
check("solo pad 2: only pad 2 audible", unmuted() == [1 if i == 2 else 0 for i in range(16)])
check("touch in Solo never reaches the original handler", not any(x[0].startswith("orig") for x in c))

c = touch(7)
check("add pad 7: one unmute post for pad id 0x13", [x for x in c if x[0] == "post"] == [("post", 0x44, 0x13, 1)])
check("pads 2 and 7 audible", unmuted() == [1 if i in (2, 7) else 0 for i in range(16)])

# drawing in Solo mode
c = call("solo_mute_fill", cell(7) + 4, 0xB, 0)
check("soloed pad fill is dark yellow + 2 yellow outlines", c == [("fill", 0x1C), ("outline", 0x14), ("outline", 0x14)])
c = call("solo_mute_fill", cell(0) + 4, 0xC, 0)
check("muted pad stays red with yellow outline", c == [("fill", 0xC), ("outline", 0x14), ("outline", 0x14)])
c = call("solo_mute_fill", 0x24050000 + 4, 0xB, 0)
check("cells of other views untouched", c == [("fill", 0xB)])

touch(2)
check("unsolo pad 2: only pad 7 audible", unmuted() == [1 if i == 7 else 0 for i in range(16)])
touch(7)
check("clear last solo restores previous mutes (only pad 5 muted)", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# a non-soloed pad that will not stay muted (an empty pad, or a hand edit) must NOT break the set: the 3.1.d report,
# "un-solo left nothing playing"
touch(9)
uc.mem_write(cell(0) + 0x189, b"\x01")  # pad 0 reads unmuted although the solo muted it
c = call("solo_mute_fill", cell(9) + 4, 0xB, 0)
check("a stray unmuted pad: pad 9 still drawn as soloed", c[0] == ("fill", 0x1C))
touch(9)
check("un-solo pad 9 restores the state from before the solo (only pad 5 muted), not 'everything muted'", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# the 3.1.l report: a soloed pad that merely READS muted at the next tap (screen refresh, engine / screen disagreeing)
# must not drop the set and re-capture the solo's own mutes
touch(9)
uc.mem_write(cell(9) + 0x189, b"\x00")  # pad 9 reads muted, no hand edit
touch(9)
check("un-solo after a soloed pad read muted: still restores the state from before the solo (only pad 5 muted)", unmuted() == [0 if i == 5 else 1 for i in range(16)])
touch(9)
touch(9)
check("solo and un-solo again afterwards: back to only pad 5 muted", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# with a solo set alive the Mute screen is always Solo, however it is reached (the 3.1.n report: un-solo left
# everything muted; a tap on the look-alike plain Mute screen muted the soloed pad and dropped the set)
touch(9)                                 # solo pad 9: everything else muted
call("solo_set_mode", VIEW, 0)           # MIX: Solo -> Mixer
call("solo_set_mode", VIEW, 1)           # MIX / INFO / BACK into the Mute screen, nothing pending
check("Mute screen with a solo set alive comes up as Solo", rd8(STATE + 4) == 1)
c = touch(9)
check("the tap there un-solos (never reaches the original handler)", not any(x[0].startswith("orig") for x in c))
check("and restores the state from before the solo (only pad 5 muted)", unmuted() == [0 if i == 5 else 1 for i in range(16)])
check("restore posts to all 16 pads, whatever the cells read", len([x for x in c if x[0] == "post"]) == 16)

# stale cells at un-solo: every cell reads unmuted while the engine still has the solo's mutes
touch(9)
for i in range(16):
    uc.mem_write(cell(i) + 0x189, b"\x01")
c = touch(9)
posts = [x for x in c if x[0] == "post"]
check("un-solo with stale cells still posts unmute for every pad but 5", sorted((x[2], x[3]) for x in posts) == sorted(((i // 4) << 4 | (i % 4), 0 if i == 5 else 1) for i in range(16)))
check("cells end at only pad 5 muted", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# no set alive: the Mute screen is plain Mute again and taps are hand edits
call("solo_set_mode", VIEW, 0)
call("solo_set_mode", VIEW, 1)
check("no solo set: Mute screen is plain Mute", rd8(STATE + 4) == 0)
check("hand tap in Mute mode reaches the original handler", touch(9) == [("orig_down",)])
uc.mem_write(STATE + 5, b"\x01")        # MIX again: pending
call("solo_set_mode", VIEW, 1)

# a set left over from before a preset load / warm restart: RAM keeps the mask, the app's pad records are all unmuted
touch(4)                                 # solo pad 4 (the app records below stand in for the engine side)
for i in range(16):
    uc.mem_write(cell(i) + 0x189, b"\x01")   # preset load: everything unmuted again
    uc.mem_write(REC(i), b"\0")
call("solo_set_mode", VIEW, 0)
call("solo_set_mode", VIEW, 1)
check("stale set (nothing muted outside it) is forgotten: plain Mute", rd8(STATE + 4) == 0 and struct.unpack("<H", uc.mem_read(STATE + 12, 2))[0] == 0)
uc.mem_write(STATE + 5, b"\x01")
call("solo_set_mode", VIEW, 1)
touch(7)
touch(7)
check("solo / un-solo after a stale set: everything unmuted, no leftover pad", unmuted() == [1] * 16)
# a live set (app records show the others muted) is kept
touch(7)
for i in range(16):
    uc.mem_write(REC(i), bytes([0 if i == 7 else 1]))
call("solo_set_mode", VIEW, 0)
call("solo_set_mode", VIEW, 1)
check("live set is kept and the screen is Solo", rd8(STATE + 4) == 1 and struct.unpack("<H", uc.mem_read(STATE + 12, 2))[0] == 1 << 7)
touch(7)
for i in range(16):
    uc.mem_write(REC(i), b"\0")
call("solo_set_mode", VIEW, 0)
call("solo_set_mode", VIEW, 1)
check("hand tap in Mute mode reaches the original handler (again)", touch(9) == [("orig_down",)])
uc.mem_write(STATE + 5, b"\x01")
call("solo_set_mode", VIEW, 1)

# Solo -> Mixer, and the move handler
check("move in Solo is swallowed", call("solo_touch_move", VIEW, PT, 0) == [])
set_screen(0x2F)
check("MIX in Solo goes to Mixer (0x2e)", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2E)])
call("solo_set_mode", VIEW, 0)
check("Solo disarmed on Mixer", rd8(STATE + 4) == 0)
check("move on Mixer reaches the original handler", call("solo_touch_move", VIEW, PT, 0) == [("orig_move",)])
c = call("solo_mute_fill", cell(0) + 4, 0xB, 0)
check("no outline outside Solo", c == [("fill", 0xB)])

# INFO from Solo (set-mode 0 without MIX), then INFO back into Mute: must be Mute, not Solo
set_screen(0x2F)
call("solo_mix_pressed", APP, 0x2E, 0, 0)  # Mute -> Solo
call("solo_set_mode", VIEW, 1)
call("solo_set_mode", VIEW, 0)             # INFO: back to Mixer
call("solo_set_mode", VIEW, 1)             # INFO: into Mute
check("INFO path lands in Mute, not Solo", rd8(STATE + 4) == 0)

# from another screen MIX goes to Mixer
set_screen(0x02)
check("MIX from Pads goes to Mixer", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2E)])

# ---------------- Pads screen: MUTE / SOLO on a third knob position ----------------
PADS, SLIDER, BUTTONS, PVT, MSG = 0x24040000, 0x24048000, 0x24049000, 0x2404A000, 0x2404B000
HIDE = 0x0807FF00                                       # a fake set-hidden method for both panels
uc.mem_write(HIDE, b"\x70\x47")                         # bx lr
stub(HIDE, lambda: (calls.append(("hide", uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x080A3DEC, lambda: (calls.append(("label", uc.reg_read(UC_ARM_REG_R0) - BUTTONS, bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 8)).split(b"\0")[0].decode())), ret()))
stub(0x080B3E84, lambda: (calls.append(("stock_child",)), ret(1)))
stub(0x080B4134, lambda: (calls.append(("stock_msg",)), ret()))
lit = {}
stub(0x080A3E00, lambda: (lit.__setitem__(uc.reg_read(UC_ARM_REG_R0) - BUTTONS, uc.reg_read(UC_ARM_REG_R1)), ret()))
uc.mem_write(PVT + 0x2C, struct.pack("<I", HIDE | 1))
uc.mem_write(SLIDER, struct.pack("<I", PVT))
uc.mem_write(BUTTONS, struct.pack("<I", PVT))
uc.mem_write(PADS + 0x2B58, struct.pack("<II", SLIDER, BUTTONS))
ROWS = (0x214, 0x174, 0xD4, 0x34)                       # the panel's buttons, top to bottom


def knob(pos):
    uc.mem_write(PADS + 0x2B6C, struct.pack("<I", pos))
    c = call("pads_panels_thunk")
    return c


def r6_call(pos):
    from unicorn.arm_const import UC_ARM_REG_R6
    uc.reg_write(UC_ARM_REG_R6, PADS)
    return knob(pos)


def ids():
    return [rd32(BUTTONS + o + 0x14) for o in ROWS]


check("the column stepper has three positions", IMG[0x080B4704 - BASE:0x080B4706 - BASE] == bytes.fromhex("0321"))
c = r6_call(2)
check("knob position 2: buttons read MUTE, SOLO, RPT and the repeat division (1/16), top to bottom", [x[2] for x in c if x[0] == "label"] == ["MUTE", "SOLO", "RPT", "1/16"] and [x[1] for x in c if x[0] == "label"] == list(ROWS), c)
check("...with our ids (RPT 0x1f3, division 0x1f4), the slider hidden and the button panel shown", ids() == [0x1F1, 0x1F2, 0x1F3, 0x1F4] and [x for x in c if x[0] == "hide"] == [("hide", SLIDER, 1), ("hide", BUTTONS, 0)], (ids(), c))
check("...and the position recorded as shown", rd32(PADS + 0x2B78) == 2)
c = r6_call(1)
check("position 1: the clipboard buttons are back (CLR, PSTE, COPY, CUT with the stock ids)", [x[2] for x in c if x[0] == "label"] == ["CLR", "PSTE", "COPY", "CUT"] and ids() == [0x25, 0x2A, 0x29, 0x28], (c, ids()))
c = r6_call(0)
check("position 0: Velocity slider shown, buttons hidden, nothing relabelled", c == [("hide", SLIDER, 0), ("hide", BUTTONS, 1)], c)
check("...and no button left lit (MUTE, SOLO, and RPT since 3.3.w)", lit == {0x214: 0, 0x174: 0, 0xD4: 0}, lit)

# start clean: nothing muted, no solo set, mixer view known
for i in range(16):
    uc.mem_write(REC(i), b"\0")
    uc.mem_write(cell(i) + 0x189, b"\x01")
uc.mem_write(STATE + 12, b"\0\0\0\0")


def select(i):
    uc.mem_write(PADS + 0x20B8, struct.pack("<H", (i // 4) << 4 | (i % 4)))


def button(bid, kind=2):
    uc.mem_write(MSG, struct.pack("<H", kind) + bytes(10) + struct.pack("<H", bid) + bytes(18))
    c = call("pads_child_msg", PADS, MSG)
    return uc.reg_read(UC_ARM_REG_R0), c


def recs():
    return [rd8(REC(i)) for i in range(16)]


def pad_cell(i):
    return rd8(PADS + 0x34 + (i // 4) * 0x820 + (i % 4) * 0x1A0 + 0x189)


def lights():
    return lit.get(0x214), lit.get(0x174)


uc.mem_write(PADS + 0x2B6C, struct.pack("<I", 2))       # the column is on MUTE / SOLO for the rest
select(6)
r, c = button(0x1F1)
check("MUTE with pad 7 selected: one mute message for pad id 0x12, handled here", r == 0 and c == [("post", 0x44, 0x12, 0)], (r, c))
check("...the Pads cell and the Mixer cell both read muted, and the MUTE button lights", pad_cell(6) == 0 and unmuted()[6] == 0 and lights() == (1, 0), lights())
r, c = button(0x1F1)
check("MUTE again: unmuted, light off", c == [("post", 0x44, 0x12, 1)] and recs() == [0] * 16 and pad_cell(6) == 1 and unmuted()[6] == 1 and lights() == (0, 0), c)
r, c = button(0x1F1)
r, c = button(0x1F1)
check("two more presses in a row (before the app has caught up is the same code path): mute then unmute", c == [("post", 0x44, 0x12, 1)] and recs() == [0] * 16)
r, c = button(0x1F1, kind=1)
check("the press itself (before the click) is swallowed without acting", r == 0 and c == [])
r, c = button(0x1F3)
check("RPT (was a blank button) is handled here and posts nothing to the app", r == 0 and c == [])
r, c = button(0x1F4)
check("the division button (0x1f4): handled here, its label rewritten (no SDRAM block in this harness: still 1/16)", r == 0 and c == [("label", 0x34, "1/16")], (r, c))
r, c = button(0x28)
check("clipboard buttons go to the stock handler untouched", c == [("stock_child",)] and r == 1, (r, c))

select(9)
button(0x1F1)                                           # pad 10 muted by hand before any solo
select(2)
r, c = button(0x1F2)
check("SOLO with pad 3 selected: every other pad muted (14 messages, pad 10 already was)", len(c) == 14 and all(x[3] == 0 for x in c) and recs() == [0 if i == 2 else 1 for i in range(16)], c)
check("...the solo set is the Mixer's own (same mask), its cells follow, the SOLO button lights", struct.unpack("<H", uc.mem_read(STATE + 12, 2))[0] == 1 << 2 and unmuted() == [1 if i == 2 else 0 for i in range(16)] and lights() == (0, 1), lights())
select(5)
uc.mem_write(MSG, struct.pack("<H", 0x63) + bytes(30))
c = call("pads_msg", PADS, MSG)
check("selecting another pad (msg 0x63): stock handler runs, then the lights follow the new pad (muted by the solo, not soloed)", c == [("stock_msg",)] and lights() == (1, 0), (c, lights()))
r, c = button(0x1F2)
check("SOLO on a second pad adds it", c == [("post", 0x44, 0x11, 1)] and recs() == [0 if i in (2, 5) else 1 for i in range(16)] and lights() == (0, 1), c)
call("solo_set_mode", VIEW, 1)
check("the Mixer's Mute screen now comes up as Solo with those two pads", rd8(STATE + 4) == 1)
c = call("solo_mute_fill", cell(5) + 4, 0xB, 0)
check("...drawn as soloed", c[0] == ("fill", 0x1C))
touch(5)                                                # un-solo one on the Mixer
call("solo_set_mode", VIEW, 0)
for i in range(16):                                     # the Pads cells have not heard about that
    uc.mem_write(PADS + 0x34 + (i // 4) * 0x820 + (i % 4) * 0x1A0 + 0x189, b"\x01")
uc.mem_write(MSG, struct.pack("<H", 0x67) + bytes(30))
call("pads_msg", PADS, MSG)
check("coming back to the Pads screen (msg 0x67): its cells' mute flags are brought in line with the app", [pad_cell(i) for i in range(16)] == [1 if i == 2 else 0 for i in range(16)])
select(2)
r, c = button(0x1F2)                                    # and the other on the Pads screen
check("un-solo the last pad from the Pads screen: back to only pad 10 muted, on both screens", recs() == [1 if i == 9 else 0 for i in range(16)] and unmuted() == [0 if i == 9 else 1 for i in range(16)] and pad_cell(9) == 0 and pad_cell(2) == 1 and lights() == (0, 0), recs())

# MUTE while a solo is on: the solo ends, then the selected pad toggles (3.1.u ignored the press)
select(2)
button(0x1F2)                                           # solo pad 3 again
select(7)
r, c = button(0x1F1)
check("MUTE with a solo on: the solo ends (pads back to only pad 10 muted) and the selected pad is muted", recs() == [1 if i in (7, 9) else 0 for i in range(16)] and struct.unpack("<H", uc.mem_read(STATE + 12, 2))[0] == 0 and lights() == (1, 0), (recs(), lights()))
r, c = button(0x1F1)
check("MUTE again: only pad 10 muted", recs() == [1 if i == 9 else 0 for i in range(16)])
select(9)
button(0x1F1)
check("...and pad 10 unmuted by hand: nothing muted", recs() == [0] * 16)
uc.mem_write(PADS + 0x2B6C, struct.pack("<I", 1))
uc.mem_write(MSG, struct.pack("<H", 0x63) + bytes(30))
lit.clear()
c = call("pads_msg", PADS, MSG)
check("on the clipboard position a pad selection touches no lights", c == [("stock_msg",)] and lit == {})
uc.mem_write(PADS + 0x2B6C, struct.pack("<I", 2))
select(0x44 // 1)                                       # garbage selection (row 4): nothing happens
uc.mem_write(PADS + 0x20B8, struct.pack("<H", 0x40))
r, c = button(0x1F1)
check("no pad selected (the id of a non-pad cell): nothing happens", r == 0 and c == [])
uc.mem_write(PADS + 0x20B8, struct.pack("<H", 0x04))    # column 4: the FX column
r, c = button(0x1F2)
check("a selection in the fifth column: nothing happens", r == 0 and c == [])

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
