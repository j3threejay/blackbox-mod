"""3.3.k: the converter hold anchored to the reader's grid, under Unicorn. The bug it fixes: the same slice retriggered
came out with one of three grit levels (the test unit, 2026-10-17), because the hold's phase ran free between notes.

Real firmware runs for: clip_read (the machine reader) then filter_process for the same voice, block after block, as
FUN_080667b8 does; the settings lookup. Stubbed: the sample source (a fixed noise burst), the Filter knob (centre).
Checks: the same slice retriggered with the hold's phase and held samples set at random before each hit (and once after
another note on the voice) comes out bit-identical, for every machine with a hold. The output filter is settled first
(as after a note ends): its tail is the previous note's sound, not the hold's.
NOT run here: the sample-pad (class A) reader path - it reaches the same machine_read and filter_process.
"""
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


MEM = 0xC0000000
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(MEM, 0x800000)
e.w32(0x38800F70, MEM)
e.w32(0x38800F74, MEM ^ 0x5052534D)
e.uc.mem_write(MEM + 0x56800 + 0x7000 + 0x3700, b"\xa5" * 0x100)     # the stash starts as garbage

PAD, SRC, SCR, OUT, SCRD, OUTD, VARS, PARAMS, BUF, ARR = (0x24060000, 0x24062000, 0x24063000, 0x24063100, 0x24064000,
                                                          0x24066000, 0x24063200, 0x24063300, 0x24063400, 0x24073000)
APP_PADS = 0x24020088 + 0x1840
N, LEN = 128, 200000
FILT = PAD + 0x670 + 0x14C
SEG = PAD + 0x30
PHASE = FILT + 4 + 48                                          # fstate.phase
rng = random.Random(7)
noise = [rng.uniform(-0.5, 0.5) for _ in range(LEN)]


def fetch():
    dst, n, pos = e.arg(1), e.arg(2), e.arg(3)
    e.uc.mem_write(dst, struct.pack(f"<{n}f", *[noise[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


e.stub(0x08063634, fetch)
e.stub(0x080636F0, value=LEN)
e.stub(0x08063790, value=0)
e.stub(0x0806FB30, lambda: e.uc.reg_write(UC_ARM_REG_S0, 0))
e.w32(PAD + 0x24, SRC)
e.w32(PAD + 0x18, 1 << 8 | 2)
e.w32(FILT + 0x84, PARAMS)
e.uc.mem_write(FILT + 4, b"\xa5" * 0x44)                      # filter state from garbage


def fidelity(v):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))


def block(pos, frac):
    """one block of the voice: read through clip_read, then its filter call; returns (audio, used, frac)"""
    for buf, d in ((SCR, SCRD), (OUT, OUTD)):
        e.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, 0, 0, 0))
    e.uc.mem_write(SEG + 0x1C, struct.pack("<f", frac))
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 1.0))[0])
    for k, v in enumerate((N, VARS, SEG + 0x1C, SCR, OUT, VARS + 8)):
        e.w32(STACK + 4 * k, v)
    e.call("clip_read", PAD, FILT, pos, 0, count=20_000_000)
    used = struct.unpack("<i", e.uc.mem_read(VARS, 4))[0]
    frac = struct.unpack("<f", e.uc.mem_read(SEG + 0x1C, 4))[0]
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, OUTD, 0, 0, 0))
    e.call("filter_process", FILT, BUF, PAD, count=20_000_000)
    return list(struct.unpack(f"<{N}f", e.uc.mem_read(OUTD, 4 * N))), used, frac


def note(start, blocks):
    pos, frac, out = start, 0.0, []
    for _ in range(blocks):
        a, used, frac = block(pos, frac)
        out += a
        pos += used
    return out


ZSTATE = FILT + 0x64                                           # ostate.z: the machine's output filter


for fid, name in ((3, "SP-12"), (2, "SP1200"), (5, "MPC60"), (6, "SP Raw"), (8, "SP 45")):
    fidelity(fid)
    hits = []
    for k in range(4):
        # whatever the voice did before: any hold phase, any held sample (the output filter settled, as after a note)
        e.uc.mem_write(PHASE, struct.pack("<fff", rng.random(), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        e.uc.mem_write(ZSTATE, bytes(16))
        if k == 2:
            note(90000, 3)                                     # and once, a different note on the voice just before
            e.uc.mem_write(PHASE, struct.pack("<f", rng.random()))
            e.uc.mem_write(ZSTATE, bytes(16))
        hits.append(note(20000, 6))
    check(f"{name}: the same slice retriggered 4 times from random hold phases, every hit bit-identical",
          all(h == hits[0] for h in hits[1:]), [sum(abs(a - b) for a, b in zip(h, hits[0])) for h in hits[1:]])
    check(f"{name}: not silent", max(abs(v) for v in hits[0]) > 0.05)

sys.exit(1 if fails else 0)
