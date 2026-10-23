"""SLICE_DIAG (filter.c): the per-trigger rows, under Unicorn, from a known sequence of reads and filter calls.

Real firmware runs for: clip_read (machine reader and the stock fallback), filter_process, sdiag_block, the settings
lookup. Stubbed: the sample source. The block starts as garbage (0xa5), as SDRAM is after a boot.
In a build without SLICE_DIAG there is nothing to check (passes).
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
if "sdiag_block" not in e.sym:
    print("PASS not a SLICE_DIAG build: nothing to check")
    sys.exit(0)

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


MEM = 0xC0000000
SD = MEM + 0x56800 + 0x7000 + 0x3800
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(MEM, 0x800000)
e.w32(0x38800F70, MEM)
e.w32(0x38800F74, MEM ^ 0x5052534D)
e.uc.mem_write(SD, b"\xa5" * 0x800)

PAD, SRC, SCR, OUT, SCRD, OUTD, VARS, PARAMS, BUF, ARR = (0x24060000, 0x24062000, 0x24063000, 0x24063100, 0x24064000,
                                                          0x24066000, 0x24063200, 0x24063300, 0x24063400, 0x24073000)
APP_PADS = 0x24020088 + 0x1840
N, LEN = 64, 100000
FILT = (PAD + 0x260 + 0x14C, PAD + 0x670 + 0x14C)            # the two voices' filter objects
SEG = (PAD + 0x30, PAD + 0x30 + 0x70)                         # two segments in the pad's pool

e.stub(0x08063634, lambda: e.uc.mem_write(e.arg(1), bytes(4 * e.arg(2))))
e.stub(0x080636F0, value=LEN)
e.stub(0x08063790, value=0)
e.stub(0x0806FB30, lambda: e.uc.reg_write(UC_ARM_REG_S0, 0))   # the filter knob: centre
e.w32(PAD + 0x24, SRC)
e.w32(PAD + 0x18, 1 << 8 | 2)
for f in FILT:
    e.w32(f + 0x84, PARAMS)


def fidelity(v):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))


def read(voice, seg, pos):
    for buf, d in ((SCR, SCRD), (OUT, OUTD)):
        e.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, 0, 0, 0))
    e.uc.mem_write(seg + 0x1C, struct.pack("<f", 0.0))
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 1.0))[0])
    for k, v in enumerate((N, VARS, seg + 0x1C, SCR, OUT, VARS + 8)):
        e.w32(STACK + 4 * k, v)
    e.call("clip_read", PAD, FILT[voice], pos, 0, count=20_000_000)


def filt(voice, silent=False):
    e.uc.mem_write(OUTD, struct.pack(f"<{N}f", *([0.1] * N)))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, OUTD, 0, int(silent), 0))
    e.call("filter_process", FILT[voice], BUF, PAD, count=20_000_000)


def block():
    e.call("sdiag_block")


ROW = "<IIBBBB8Hf"
ROWN = struct.calcsize(ROW)


def rows():
    magic, seq, n, _ = struct.unpack("<4I", e.uc.mem_read(SD, 16))
    tot = struct.unpack("<8I", e.uc.mem_read(SD + 16, 32))
    base = SD + 48 + 8 * 12 + 8
    cur = [struct.unpack(ROW, e.uc.mem_read(base + i * ROWN, ROWN)) for i in range(2)]
    ring = [struct.unpack(ROW, e.uc.mem_read(base + (2 + i) * ROWN, ROWN)) for i in range(min(n, 48))]
    return magic, seq, n, tot, cur, ring


fidelity(3)                                                  # SP-12
for b in range(5):                                           # trigger 1: voice 1, segment A, 5 blocks
    block()
    read(1, SEG[0], 1000 + 64 * b)
    filt(1)
for b in range(3):                                           # trigger 2: segment A restarts (a retrigger)
    block()
    read(1, SEG[0], 1000 + 64 * b)
    filt(1)
for b in range(2):                                           # trigger 3: voice 0, segment B
    block()
    read(0, SEG[1], 5000 + 64 * b)
    filt(0)
fidelity(0)                                                  # one block where the pad reads as Normal
block()
read(0, SEG[1], 5128)
filt(0)
fidelity(3)
block()
filt(0, silent=True)                                         # and one silent buffer

magic, seq, n, tot, cur, ring = rows()
check("the block from garbage: magic set, 12 blocks counted", magic == 0x53444731 and seq == 12, (hex(magic), seq))
check("one finished row (trigger 1), two current", n == 1, n)
# row: seq0, pad_id, voice, seg, interp, flags, reads_m, reads_stock, reads_rate, filt_m, filt_other, filt_silent, reads_old, last, rate
r1 = ring[0]
check("trigger 1: voice 1, segment 0, SP-12, 5 machine reads, 5 machine filter calls, started at block 1",
      r1[:6] == (1, 1 << 8 | 2, 1, 0, 3, 1) and r1[6:12] == (5, 0, 0, 5, 0, 0) and r1[13] == 4, r1)
r2 = cur[1]
check("trigger 2 (the retrigger): its own row, 3 + 3, started at block 6",
      r2[0] == 6 and r2[2:4] == (1, 0) and r2[6:12] == (3, 0, 0, 3, 0, 0), r2)
r3 = cur[0]
check("trigger 3: voice 0, segment 1, 2 machine reads + 1 stock, filter 2 machine + 1 other + 1 silent",
      r3[0] == 9 and r3[2:4] == (0, 1) and r3[6:12] == (2, 1, 0, 2, 1, 1), r3)
check("totals: reads 10 machine / 1 stock, filter 10 / 1 / 1, 2 segments", tot[:7] == (10, 1, 0, 10, 1, 1, 0) and tot[7] == 2, tot)
check("rate recorded", abs(r1[14] - 1.0) < 1e-6, r1[14])
sys.exit(1 if fails else 0)
