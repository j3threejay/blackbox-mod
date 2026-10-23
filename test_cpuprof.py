"""CPU_PROF (prof.c): the per-block section timings and the worst-block list, under Unicorn, from known timings.

Real firmware runs for: prof.c's wrappers (comp_process, munchi_process, fx2_core, filter_process, voice_read,
clip_read), prof_ctl, prof_block_start / prof_block_end. Stubbed: the wrapped bodies, which only move the cycle
counter (DWT_CYCCNT) on by a known amount, so every section has a known cost. The SDRAM block starts as garbage.
In a build without CPU_PROF there is nothing to check (passes).
"""
import struct
import sys

from emu import Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
if "prof_block_end" not in e.sym:
    print("PASS not a CPU_PROF build: nothing to check")
    sys.exit(0)

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


MEM = 0xC0000000
P = MEM + 0x56800 + 0x7000 + 0x3800
CYC = 0xE0001004
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(MEM, 0x800000)
e.w32(0x38800F70, MEM)
e.w32(0x38800F74, MEM ^ 0x5052534D)
e.uc.mem_write(P, b"\xa5" * 0x800)


def spend(n):
    return lambda: e.w32(CYC, (e.r32(CYC) + n) & 0xFFFFFFFF)


COST = {"comp_process_body": 30000, "munchi_process_body": 20000, "fx2_core_body": 25000,
        "filter_process_body": 4000, "voice_read_body": 3000, "clip_read_body": 3500}
for name, n in COST.items():
    e.stub(e.sym[name], spend(n))

NOM = 2_000_000                                     # cycles in a nominal block


def run_block(voices, sample_reads, clip_reads, ctl, ours, starts, extra):
    """one block: the sections in the order the engine runs them, then `extra` cycles of everything else"""
    e.call("prof_block_start")
    t0 = e.r32(CYC)
    e.call("prof_ctl", ours, ctl, starts)
    e.w32(CYC, (e.r32(CYC) + ours + ctl) & 0xFFFFFFFF)
    for _ in range(sample_reads):
        e.call("voice_read")
    for _ in range(clip_reads):
        e.call("clip_read")
    for _ in range(voices):
        e.call("filter_process")
    e.call("munchi_process")
    e.call("fx2_core")
    e.call("comp_process")
    e.w32(CYC, (e.r32(CYC) + extra) & 0xFFFFFFFF)
    busy = (e.r32(CYC) - t0) & 0xFFFFFFFF
    e.call("prof_block_end", busy, NOM)
    return busy


FMT = "<IHBBBBBB7I"          # busy, load, voices, reads, starts, pad x3, t[7]
SZ = struct.calcsize(FMT)
HEAD = "<3I24I"              # magic, blocks, nom, hist[24]
OFF_TOT = struct.calcsize(HEAD) + 4      # the u64 totals are 8-aligned: 4 bytes of padding after hist


cur_off_global = OFF_TOT + 80


def read():
    h = struct.unpack(HEAD, e.uc.mem_read(P, struct.calcsize(HEAD)))
    tot = struct.unpack("<10Q", e.uc.mem_read(P + OFF_TOT, 80))
    cur_off = OFF_TOT + 80
    worst = [struct.unpack(FMT, e.uc.mem_read(P + cur_off + SZ * (1 + i), SZ)) for i in range(8)]
    return h, tot, worst


e.w32(CYC, 0xFFFF0000)                              # the counter wraps during the first block
b1 = run_block(voices=6, sample_reads=4, clip_reads=2, ctl=50000, ours=8000, starts=0, extra=600000)
b2 = run_block(voices=10, sample_reads=6, clip_reads=4, ctl=90000, ours=9000, starts=3, extra=2000000)   # the heavy one
for _ in range(5):
    run_block(voices=6, sample_reads=4, clip_reads=2, ctl=50000, ours=8000, starts=0, extra=600000)
h, tot, worst = read()
magic, blocks, nom, hist = h[0], h[1], h[2], h[3:]
check("from garbage: magic PRF1, 7 blocks, nominal recorded", magic == 0x50524631 and blocks == 7 and nom == NOM, (hex(magic), blocks, nom))
w = max(worst, key=lambda r: r[1])
load2 = b2 // (NOM // 1000 + 1)
check(f"the heaviest block is in the worst list with its load ({load2 / 10:.1f} %)", w[1] == load2 and w[0] == b2, w[:2])
t = w[8:]
exp = [90000, 9000, 30000, 20000, 25000, 10 * 4000, 6 * 3000 + 4 * 3500]
check("its sections: ctl, ours, master, fx1, fx2, filters x10, reads (6 sample + 4 clip)", list(t) == exp, (list(t), exp))
check("its counts: 10 voices, 10 reads, 3 note starts", w[2:5] == (10, 10, 3), w[2:5])
check("the counter wrapping inside block 1 did not break its total", b1 < 1_500_000 and tot[0] == b1 + b2 + 5 * b1, (b1, tot[0]))
light = b1 // (NOM // 1000 + 1)
check("histogram: six light blocks and one heavy one in their 10 % bins", hist[light // 100] == 6 and hist[min(load2 // 100, 23)] == 1, (light, load2, [i for i, v in enumerate(hist) if v]))
check("section totals add up over all blocks (master = 7 x 30000)", tot[1 + 2] == 7 * 30000 and tot[1 + 0] == 90000 + 6 * 50000, tot[1:8])
check("voices and starts totals", tot[8] == 10 + 6 * 6 and tot[9] == 3, tot[8:10])
FREEZE = P + cur_off_global + SZ * 9
e.w32(FREEZE, 0x465A5221)
before = read()
run_block(voices=30, sample_reads=30, clip_reads=0, ctl=900000, ours=1, starts=9, extra=3_000_000)
check("frozen: a block changes nothing in the record", read() == before)
e.w32(FREEZE, 0)
run_block(voices=6, sample_reads=4, clip_reads=2, ctl=50000, ours=8000, starts=0, extra=600000)
check("unfrozen: it counts again", read()[0][1] == 8, read()[0][1])
sys.exit(1 if fails else 0)
