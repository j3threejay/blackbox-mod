"""Parameter ids: no two of ours on one id, and none of ours on an id stock registers (except the five stock
registrations our hooks replace on purpose). Written 2026-10-18 after 3.3.n-q put Theme / Groove / two TAPESCAM lists
on 0x1ba..0x1bd, which the insert's knobs already used as P_INS_RATE + k: the registry has ONE entry per id, so the
later registration wins and the other's knob turns into the wrong control. A grep for literal ids could not see
computed ones; this runs the real registration code instead.

Real firmware runs for: every registration hook of ours, called the way stock calls it (comp_register for 0xb4,
cond_register 0x10e, interp_register 0xf1, munchi_register 0x197, fx2_register 0x198) - which covers master, lfo,
insert, preroll, groove and theme through comp_register.
Stubbed: stock's three registration functions (recorded: the id each call registers).
Reference: research/stock_param_ids.txt, every id stock 3.1.9 registers (from the decompile: all calls to
FUN_0808c0d8 / FUN_0808c12c / FUN_0808c102 with a constant id).
NOT run: stock's own registration pass, the settings stores (a separate cap: 96 entries a store).
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                      # backup SRAM
e.uc.mem_map(0x58024000, 0x1000)                      # RCC / PWR: bkp_enable switches the backup SRAM on
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


stock = {int(x, 16) for x in open("research/stock_param_ids.txt").read().splitlines() if x and not x.startswith("#")}
calls = []
for fn in (0x0808C0D8, 0x0808C12C, 0x0808C102):
    e.stub(fn, lambda fn=fn: calls.append((e.arg(1), fn)))

TABLE, NAMES, TEXT = 0x24060000, 0x24061000, 0x24062000
e.uc.mem_write(TEXT, b"x\0")
e.uc.mem_write(NAMES, struct.pack("<4I", TEXT, TEXT, TEXT, TEXT))
REPLACED = {0xB4, 0x10E, 0xF1, 0x197, 0x198}
hooks = [("comp_register", (TABLE, 0xB4, 1, TEXT), (0, 1, TEXT)),
         ("cond_register", (TABLE, 0x10E, TEXT, NAMES), (4, TEXT)),
         ("interp_register", (TABLE, 0xF1, TEXT, NAMES), (4, TEXT)),
         ("munchi_register", (TABLE, 0x197, TEXT, NAMES), (4, TEXT)),
         ("fx2_register", (TABLE, 0x198, TEXT, NAMES), (4, TEXT))]
per = {}
for name, regs, stack in hooks:
    calls.clear()
    for k, v in enumerate(stack):
        e.w32(STACK + 4 * k, v)
    e.call(name, *regs, count=5_000_000)
    per[name] = [i for i, _ in calls]

ours = [(i, n) for n, ids in per.items() for i in ids if i not in REPLACED]
seen, dup = {}, []
for i, n in ours:
    if i in seen:
        dup.append((hex(i), seen[i], n))
    seen[i] = n
check(f"{len(ours)} ids of ours, each registered once", not dup, dup)
clash = sorted({(hex(i), n) for i, n in ours if i in stock})
check("none of ours lands on an id stock registers", not clash, clash)
check("every id below the registry's 500 slots", all(i < 500 for i, _ in ours), [hex(i) for i, _ in ours if i >= 500])
check("the five replaced stock ids are each registered by their own hook",
      all(p in per[n] for n, (_, p, *_r), _s in hooks), {n: [hex(x) for x in per[n][:3]] for n in per})
for want, who in ((0x1BA, "insert Depth"), (0x1BB, "insert Manual"), (0x1BC, "insert Feedback"), (0x1BD, "insert Spread")):
    check(f"{who} is on {want:#x}, once (the id 3.3.n-q's first cut collided with)",
          sum(1 for i, _ in ours if i == want) == 1, [n for i, n in ours if i == want])
for want, who, sym in ((0x144, "Theme", "theme_register"), (0x145, "Groove", "groove_register"),
                       (0x146, "TAPESCAM Age", "tapescam_block"), (0x147, "TAPESCAM Speed", "tapescam_block")):
    if sym in e.sym:                                       # only builds that have the feature
        check(f"{who} is on {want:#x}, once", sum(1 for i, _ in ours if i == want) == 1, [n for i, n in ours if i == want])

print(f"{fails} failed")
sys.exit(1 if fails else 0)
