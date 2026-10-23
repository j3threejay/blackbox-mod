"""3.3.l: filter.c's pad_setting (filter_dsp.c since 3.3.y) remembers where Fidelity (0xf1) and Saturation (0xdb) sit in each pad's store.

Real firmware runs for: pad_machine_mode (filter.c, through pad_setting) and stock's store lookup FUN_08093e9c,
against app pad stores laid out like the firmware's (u16 id at +0, u32 value at +4; entries at store+4, count at
store+10). The SDRAM block starts as garbage. Checks: the value always equals stock's lookup - after a value change,
after the store is rebuilt in another order, with a garbage table, for another pad, with no SDRAM block - and a
remembered look costs a fraction of a walk.
"""
import random
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0

from emu import Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


MEM = 0xC0000000
PS = MEM + 0x56800 + 0x7000 + 0x3720
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(MEM, 0x800000)
e.uc.mem_write(PS, bytes(random.Random(3).randrange(256) for _ in range(40)))      # garbage table
# 3.3.y: pad_setting is in bank 2 now and pad_machine_mode asks b2_live() first. The first ask scans the payload (a few
# hundred thousand instructions); on the unit the first audio block has done that long before. Do it here once.
e.call("b2_live", count=50_000_000)


def block(on):
    e.w32(0x38800F70, MEM if on else 0)
    e.w32(0x38800F74, (MEM ^ 0x5052534D) if on else 0)


APP_PADS = 0x24020088 + 0x1840
PAD = 0x24060000
ARR = 0x24070000
rng = random.Random(1)
# 82 entries like a pad store: stock's 59 then ours; Saturation at 40, Fidelity at 42 as stock's defaults builder adds them
IDS = [i for i in range(0x80, 0x80 + 40)] + [0xDB, 0x7F, 0xF1] + [0x100 + i for i in range(39)]


def store(row, col, ids, fid, sat, arr):
    vals = {i: rng.randrange(1, 1000) for i in ids}
    vals[0xF1], vals[0xDB] = fid, sat
    e.uc.mem_write(arr, b"".join(struct.pack("<HHI", i, 0, vals[i]) for i in ids))
    s = APP_PADS + row * 0xF0 + col * 0x30
    e.w32(s + 4, arr)
    e.uc.mem_write(s + 10, struct.pack("<H", len(ids)))


def is_machine(row, col):
    e.w32(PAD + 0x18, row << 8 | col)
    e.call("pad_machine_mode", PAD, count=200_000)
    return e.uc.reg_read(UC_ARM_REG_R0)


def cost(row, col):
    cnt = [0]
    h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
    is_machine(row, col)
    e.uc.hook_del(h)
    return cnt[0]


block(True)
store(1, 2, IDS, 3, 400, ARR)                       # Fidelity 3 = SP-12 (a machine)
check("a machine pad reads as one, from a garbage table", is_machine(1, 2) == 1)
e.uc.mem_write(PS, b"\xff" * 40)                     # forget: the next look walks
first, again = cost(1, 2), cost(1, 2)
print(f"     cost of pad_machine_mode: {first} instructions on a walk, {again} once remembered")
check("the remembered look is under a third of the walk", again * 3 < first, (first, again))
store(1, 2, IDS, 0, 400, ARR)                       # Normal, same layout: the value is read live
check("a value change is seen at once (Normal now)", is_machine(1, 2) == 0)
order = IDS[:]
rng.shuffle(order)
store(1, 2, order, 5, 400, ARR + 0x800)             # rebuilt in another order: MPC60
check("a store rebuilt in another order: the remembered spot no longer matches, the walk finds it", is_machine(1, 2) == 1)
store(3, 4, IDS[:20] + IDS[45:], 2, 0, ARR + 0x1000)   # another pad, no Fidelity entry at all
check("a pad without the entry reads 0 (Normal), as stock's lookup does", is_machine(3, 4) == 0)
check("and the first pad is still right", is_machine(1, 2) == 1)
block(False)
check("no SDRAM block: stock's lookup, same answer", is_machine(1, 2) == 1)
sys.exit(1 if fails else 0)
