"""Flash bank 2 AS IT IS ON THE TEST UNIT, against the image just built. The test that did not exist.

Bank 2 is programmed once and survives every bank 1 install; the image is rebuilt and reflashed constantly. Every
other suite used to load the bank 2 that the SAME build had just linked, so the two always agreed - while on the
test unit they had drifted apart, and Confetti crashed on every build from 3.2.m to 3.2.r:

    confetti_block + 0xa10 (bank 2):  bl rev4_step        the reverb, which lives in the cave
        as 3.2.r linked it:   bl 0x080f8e30  -> rev4_step
        as programmed (3.2.l): bl 0x080f8b40  -> by then, relapse_block + 0x3dc

Captured off the test unit 2026-10-11: PC relapse_block + 0x40a, LR confetti_block + 0xa14, a precise bus fault at
0x24cb8d7c. The pairing check passed throughout, because the id hashes bank 2's SOURCES and the sum only checked
the payload against itself.

Nothing here needs hardware. emu.py now loads the deployed payload by default, so this is the real pair.
"""
import os
import struct
import subprocess
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE

from emu import DEPLOYED_BANK2, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
B2, CAVE_LO, CAVE_HI, OLD_PIN = 0x08100000, 0x080F1E78, 0x08100000, 0x080F8B40

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


linked = open("out/bank2.bin", "rb").read()
# BANK2_NEW=1: this build goes out with a bank 2 of its own, which the card loader writes from BBEXTRA.BIN on the
# first boot. The payload to hold the image against is then the one it ships with, not the one on the test unit today.
NEW = os.environ.get("BANK2_NEW") == "1"
deployed = linked if NEW else open(DEPLOYED_BANK2, "rb").read()
funcs, funcs_all = {}, {}
for line in subprocess.run(["arm-none-eabi-nm", "-n", "out/cave.elf"], capture_output=True, text=True, check=True).stdout.splitlines():
    p = line.split()
    if len(p) >= 3 and p[-2] in "TtWw":
        funcs[int(p[0], 16) & ~1] = p[-1]
        funcs_all[p[-1]] = int(p[0], 16) & ~1

# --- 1. the build links the payload that is physically on the unit
if NEW:
    on_unit = open(DEPLOYED_BANK2, "rb").read()
    check("BANK2_NEW: the card file is the payload this build links", open("out/BBEXTRA.BIN", "rb").read() == linked)
    print(f"     (differs from the payload on the test unit in {sum(a != b for a, b in zip(linked, on_unit)) + abs(len(linked) - len(on_unit))} bytes)")
else:
    check("the bank 2 this build links is byte-identical to the payload on the test unit", linked == deployed,
          f"{sum(a != b for a, b in zip(linked, deployed))} bytes differ")

# --- 2. THE INVARIANT, since 3.3.c: bank 2 calls NOTHING in the cave
# The cave is relinked every build and its addresses move; bank 2 is written once and lives through every bank 1
# install. A branch from one into the other is the crash that hit every build from 3.2.m to 3.2.r. The reverb that
# Confetti and Prism share used to be the one such call (through a jump pinned at 0x080f8b40); it is in bank 2 now.
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
# The scan reads a branch at every halfword, so it also reads one in the middle of an instruction: the tail of an
# `lsl.w` (f00c) followed by an `sdiv` / `udiv` (fb9x / fbbx) decodes as a bl. Integer division came to bank 2 with
# clipwin_b2.c. The linker's mapping symbols ($t code, $d data) say where the instructions are: each $t run is swept
# from its start, and a halfword that is the second half of a 32-bit instruction there is not a branch. Nothing else is
# set aside - data, and code the sweep could not decode, are still read at every halfword.
mapsyms = sorted((int(p[0], 16), p[-1]) for p in (l.split() for l in subprocess.run(
    ["arm-none-eabi-nm", "-n", "--special-syms", "out/cave.elf"], capture_output=True, text=True, check=True).stdout.splitlines())
    if len(p) >= 3 and p[-1] in ("$t", "$d") and B2 <= int(p[0], 16) < B2 + len(deployed))
mid, swept, code_bytes = set(), 0, 0
for i, (a, kind) in enumerate(mapsyms):
    if kind != "$t":
        continue
    end = mapsyms[i + 1][0] if i + 1 < len(mapsyms) else B2 + len(deployed)
    code_bytes += end - a
    for ins in md.disasm(deployed[a - B2:end - B2], a):
        swept += ins.size
        if ins.size == 4:
            mid.add(ins.address + 2)
check(f"the mapping symbols mark bank 2's code, and the sweep decodes all of it ({swept} of {code_bytes} bytes)",
      mapsyms and swept == code_bytes, (len(mapsyms), swept, code_bytes))


def scan(payload):
    """every branch in the payload that lands in the cave, and every one that leaves bank 2 for anywhere else"""
    leaving, outside, off = {}, {}, 16
    while off < len(payload) - 4:
        h1, h2 = struct.unpack_from("<HH", payload, off)
        if (h1 & 0xF800) == 0xF000 and (h2 & 0xD000) in (0xD000, 0x9000, 0xC000) and B2 + off not in mid:
            ins = list(md.disasm(payload[off:off + 4], B2 + off, 1))
            if ins and ins[0].mnemonic in ("bl", "blx", "b"):
                tgt = int(ins[0].op_str.lstrip("#"), 16)
                if CAVE_LO <= tgt < CAVE_HI:
                    leaving.setdefault(tgt, []).append(B2 + off)
                elif 0x08000000 <= tgt < 0x08200000 and not B2 <= tgt < B2 + len(payload):
                    outside.setdefault(tgt, []).append(B2 + off)     # anywhere else in the flash (a constant that
                                                                     # happens to decode as a branch points nowhere near it)
                off += 4
                continue
        off += 2
    return leaving, outside


leaving, outside = scan(deployed)
check("no branch in bank 2 lands in the cave", not leaving, {hex(t): [hex(x) for x in sites] for t, sites in leaving.items()})
check("...and none leaves bank 2 at all: it is leaf DSP, calling only itself", not outside,
      {hex(t): [hex(x) for x in sites] for t, sites in outside.items()})
# ...and the scan still sees a real one: a bl into the cave planted on an instruction of each of clipwin_b2.c's cw_*
# functions (the Clip Window's maths, all of it in bank 2; its divisions are what the mapping symbols are read for), at
# each one's first instruction and at its first sdiv / udiv if it has one
def bl_bytes(at, tgt):
    o = (tgt - (at + 4)) >> 1
    s_, j1, j2 = (o >> 23) & 1, ((o >> 22) & 1) ^ 1 ^ ((o >> 23) & 1), ((o >> 21) & 1) ^ 1 ^ ((o >> 23) & 1)
    return struct.pack("<HH", 0xF000 | (s_ << 10) | ((o >> 11) & 0x3FF), 0xD000 | (j1 << 13) | (j2 << 11) | (o & 0x7FF))


sizes = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", "out/cave.elf"], capture_output=True,
                                                                    text=True, check=True).stdout.splitlines() if len(l.split()) == 4}
cw_funcs = sorted(n for n, a in funcs_all.items() if n.startswith("cw_") and B2 <= a < B2 + len(deployed))
check(f"the Clip Window's maths is bank 2's: {len(cw_funcs)} cw_* functions there, none left in the cave",
      len(cw_funcs) >= 10 and {"cw_latch", "cw_slot", "cw_map", "cw_turn"} <= set(cw_funcs)
      and not [n for n, a in funcs_all.items() if n.startswith("cw_") and CAVE_LO <= a < CAVE_HI], cw_funcs)
divs = set()
for fn in cw_funcs:
    cw = funcs_all[fn]
    div = next((i.address for i in md.disasm(deployed[cw - B2:cw - B2 + sizes.get(fn, 4)], cw) if i.mnemonic in ("sdiv", "udiv")), None)
    if div:
        divs.add(fn)
    caught = []
    for at in (cw, div) if div else (cw,):
        planted = bytearray(deployed)
        planted[at - B2:at - B2 + 4] = bl_bytes(at, CAVE_LO + 0x100)
        caught.append(scan(bytes(planted))[0] == {CAVE_LO + 0x100: [at]})
    check(f"a bl into the cave planted at {fn}'s first instruction" + (f" and at its first division ({hex(div)})" if div else "")
          + " is still found", all(caught), (hex(cw), div and hex(div), caught))
check(f"...{len(divs)} of them planted on a division, cw_latch and cw_turn among them ({', '.join(sorted(divs))})",
      {"cw_latch", "cw_turn"} <= divs, sorted(divs))
check("the reverb is in bank 2 beside its two callers", B2 <= funcs_all.get("rev4_step", 0) < B2 + len(deployed), hex(funcs_all.get("rev4_step", 0)))
check("the old pinned jump is gone from the cave", "rev4_step_impl" not in funcs_all and funcs.get(OLD_PIN) != "rev4_step", funcs.get(OLD_PIN))
lits = [struct.unpack_from("<I", deployed, o)[0] for o in range(16, len(deployed) - 3, 4)]
check("bank 2 holds no data pointers into the cave", not [v for v in lits if CAVE_LO <= (v & ~1) < CAVE_HI])

# --- 3. the crash itself: Confetti's first block, on the real pair
e = Emu(IMAGE, "out/cave.elf")
for base, size in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x800000), (0x30000000, 0x10000)):
    e.uc.mem_map(base, size)
OBJ, VT, BUFS, CTX, BUS, IN = 0x30000000, 0x30001000, 0x30001100, 0x30001200, 0x30001300, 0x30001400
BUSL, BUSR, INL, INR, ARR = 0x30002000, 0x30002400, 0x30002800, 0x30002C00, 0x30003000
APPFX, N = 0x24020088 + 0x2FC0, 128
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.w32(OBJ + 0x18, 3 << 16)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 2))
e.uc.mem_write(OBJ + 0x2C, struct.pack("<f", 0.5))
e.uc.mem_write(OBJ + 0x21F, b"\x01")
for o, ptr, floats in ((0x30, 0xC0000000, 192256), (0x4C, 0xC0400000, 96256), (0x68, 0xC0500000, 192256)):
    e.w32(OBJ + o, ptr)
    e.w32(OBJ + o + 0x14, floats)
e.w32(BUFS, CTX)
e.uc.mem_write(CTX + 0x18, struct.pack("<f", 120.0))
for addr, l, r in ((BUS, BUSL, BUSR), (IN, INL, INR)):
    e.w32(addr, N)
    e.w32(addr + 4, N)
    e.w32(addr + 8, l)
    e.w32(addr + 12, r)
    e.uc.mem_write(addr + 0x10, b"\x00\x01")
e.stub(0x080548C8, value=1)
e.stub(0x0804F0D4)
e.stub(0x0804F270, lambda: e.w32(e.arg(2), IN))
e.stub(0x0805F37C, value=BUS)
ids = {"type": 0x197, "fb": 0x38, "size": 0x1E3, "tone": 0x1E7, "cfmode": 0x1EC, "cfdensity": 0x1ED, "cfcontour": 0x1EE, "cfspace": 0x1EF}
vals = dict(type=4, fb=500, size=5, tone=300, cfmode=0, cfdensity=500, cfcontour=500, cfspace=800)
e.uc.mem_write(ARR, b"".join(struct.pack("<HHI", ids[k], 0, v) for k, v in vals.items()))
e.w32(APPFX + 4, ARR)
e.uc.mem_write(APPFX + 10, struct.pack("<H", len(vals)))
e.uc.mem_write(INL, struct.pack(f"<{N}f", *([0.3] * N)))
e.uc.mem_write(INR, struct.pack(f"<{N}f", *([0.3] * N)))

check("with the pair as it is on the test unit, bank 2 is accepted as live", e.call("b2_live") == [] and e.uc.reg_read(66) == 1,
      e.uc.reg_read(66))                                   # 66 = UC_ARM_REG_R0

hits = {"impl": 0, "relapse": 0, "cave": 0}
impl, relapse = e.sym["rev4_step"] & ~1, e.sym["relapse_block"] & ~1
confetti = e.sym["confetti_block"] & ~1
e.uc.hook_add(UC_HOOK_CODE, lambda *_: hits.__setitem__("impl", hits["impl"] + 1), begin=impl, end=impl)
e.uc.hook_add(UC_HOOK_CODE, lambda *_: hits.__setitem__("relapse", hits["relapse"] + 1), begin=relapse, end=relapse + 1700)
err = None
try:
    for _ in range(4):                                     # the first block is the one that died
        e.call("munchi_process", OBJ, BUFS, count=200_000_000)
except Exception as exc:
    err = exc
check("CONFETTI'S FIRST BLOCKS RUN: the crash on the test unit does not happen", err is None, str(err))
check(f"Confetti's Space reaches the reverb, which is now in bank 2 with it ({hits['impl']} entries at {impl:#010x})",
      hits["impl"] > 0 and B2 <= impl < B2 + len(deployed), hits)
check("...and never in relapse_block, which is where the stale call used to land", hits["relapse"] == 0, hits)
out = struct.unpack(f"<{N}f", e.uc.mem_read(BUSL, 4 * N))
check("the output is finite", all(v == v and abs(v) < 100 for v in out))

# --- 4. the failure mode, reconstructed: a payload that is internally consistent but was linked for another cave
# This is exactly what was on the test unit. b2_ok() passes it (right id, sum matches its own contents); only the sum
# bank 1 carries for the payload it was LINKED against can tell.
stale = bytearray(deployed)
site = (e.sym["confetti_block"] & ~1) - B2 + 0x40            # one instruction's worth of difference, anywhere in the code
stale[site] ^= 0x40
body = bytes(stale[16:])
struct.pack_into("<I", stale, 12, sum(struct.unpack(f"<{len(body) // 4}I", body)) & 0xFFFFFFFF)
e2 = Emu(IMAGE, "out/cave.elf")
for base, size in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x800000), (0x30000000, 0x10000)):
    e2.uc.mem_map(base, size)                     # backup SRAM first: the pairing scan leaves its mark there (3.3.a)
e2.uc.mem_write(B2, bytes(stale))
e2.call("b2_ok")
ok_alone = e2.uc.reg_read(66)
e2.call("b2_live")
check("a payload linked for a different cave still passes the old check (right id, self-consistent sum)", ok_alone == 1, ok_alone)
check("...but is REJECTED now: bank 1 knows the sum of the payload it was linked against", e2.uc.reg_read(66) == 0, e2.uc.reg_read(66))

# --- 4b. WITH BANK 2 OFF, CONFETTI MUST BECOME THE PLAIN DELAY - ONCE. Until 3.2.u it cleared the delay's three
# lines on every block in that state (4.5 ms of work in a 2.67 ms block): the test unit ran at 103 blocks a second with
# the button lights stuttering while bank 2 was being rewritten on 2026-10-11. e2 above holds a rejected payload.
e2.uc.mem_write(OBJ, bytes(e.uc.mem_read(OBJ, 0x4000)))                # the same delay object, buffers and store
e2.uc.mem_write(APPFX, bytes(e.uc.mem_read(APPFX, 0x18)))
events = []
e2.stub(0x080548C8, lambda: events.append("stock"), value=1)
e2.stub(0x0806AAC0, lambda: events.append("clear"))
e2.stub(0x0804F0D4)
e2.stub(0x0804F270, lambda: e2.w32(e2.arg(2), IN))
e2.stub(0x0805F37C, value=BUS)
e2.w32(0x38800B14, (0x4D32 << 16) | 1)                                 # Munchi ran last
per_block = []
for _ in range(5):
    events.clear()
    e2.call("munchi_process", OBJ, BUFS, count=200_000_000)
    per_block.append((events.count("clear"), events.count("stock")))
check(f"bank 2 off + Confetti selected: the lines are cleared ONCE, then left alone {[c for c, _ in per_block]}",
      [c for c, _ in per_block] == [3, 0, 0, 0, 0], per_block)
check("...and the stock delay runs every block in its place", all(st == 1 for _, st in per_block), per_block)
# --- 5. THE FLASH HAS TO READ CLEANLY TOO (3.2.t). The payload on the test unit was byte-perfect and still misread one
# word read in 700: the chip corrects a single flipped bit silently and bus-faults on two. b2_paired now clears the
# ECC flags, reads every flash word of the payload sixteen times past the data cache, and refuses bank 2 if a flag
# is set. Here the flash controller is modelled just far enough: a write to CCR2 clears flags in SR2, and a read
# hook can raise SNECCERR the way a marginal word would.
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

SR2_REG, CCR2_REG, DCIMVAC_REG, SNECC = 0x52002110, 0x52002114, 0xE000EF5C, 1 << 25


def boot_check(stale_flag=False, misread_on=None):
    """One fresh boot's verdict. misread_on: raise SNECCERR on that payload read (counted from 0), or never."""
    em = Emu(IMAGE, "out/cave.elf")
    em.uc.mem_map(0x38800000, 0x1000)                    # backup SRAM + its clock: the scan's mark (3.3.a)
    em.uc.mem_map(0x58024000, 0x1000)
    seen = {"reads": 0, "inval": 0, "words": set()}
    em.w32(SR2_REG, SNECC if stale_flag else 0)

    def on_write(uc, access, addr, size, value, _):
        if addr == CCR2_REG:
            em.w32(SR2_REG, em.r32(SR2_REG) & ~value & 0xFFFFFFFF)
        elif addr == DCIMVAC_REG:
            seen["inval"] += 1
            seen["last_inval"] = value

    def on_read(uc, access, addr, size, value, _):
        if seen.get("last_inval") == addr:               # a read of a line just dropped from the cache: a real one
            if seen["reads"] == misread_on:
                em.w32(SR2_REG, em.r32(SR2_REG) | SNECC)
            seen["reads"] += 1
            seen["words"].add(addr)
            seen["last_inval"] = None

    em.uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=0x52002000, end=0x52002FFF)
    em.uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=0xE000EF00, end=0xE000EFFF)
    em.uc.hook_add(UC_HOOK_MEM_READ, on_read, begin=B2, end=B2 + len(deployed) - 1)
    em.call("b2_live", count=5_000_000)
    return em.uc.reg_read(66), seen


words = len(deployed) // 32
live, seen = boot_check()
check("a payload that reads cleanly is accepted", live == 1, live)
check(f"every one of the {words} flash words is read, sixteen times over ({seen['reads']:,} real reads)",
      len(seen["words"]) == words and seen["reads"] == 16 * words, (len(seen["words"]), seen["reads"]))
check("each of those reads is forced past the data cache first", seen["inval"] >= seen["reads"], seen["inval"])
live, _ = boot_check(stale_flag=True)
check("a flag left over from before the scan does not condemn a good payload (it is cleared first)", live == 1, live)
for label, n in (("the very first read", 0), ("a read in the middle", 8 * words + 123), ("the very last read", 16 * words - 1)):
    live, _ = boot_check(misread_on=n)
    check(f"ONE corrected bit error on {label} -> bank 2 is refused, and the effects bypass", live == 0, live)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
