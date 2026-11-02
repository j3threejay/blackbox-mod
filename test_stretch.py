"""Clip Stretch models (src/stretch.c + stretch_dsp.c), under Unicorn.

Real firmware runs for: the hooked clip reader (clip_read_b -> clip_read -> stretch_read -> str_clip -> str_render, bank
1 and bank 2 of this build), stock's settings lookup and buffer helpers, stretch_tick reading the pad's store.
Stubbed: the sample source (fetch / length / stereo), as test_clip.py does.
Reference: the same DSP built for the Mac (host/stretch_host.c render_segment), read in the same blocks.
NOT checked: stock's segment engine around it (spawn, slot fades, the hand-over between slices), the real pad
object's field values on a unit (offsets are from the disassembly: stretch_re.md), how it sounds, card streaming.
"""
import ctypes
import math
import os
import struct
import subprocess
import sys

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R11, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
PAD, SRC, SCR, OUT, SCRD, SCRR, OUTD, OUTR, ARR, VARS = (0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24064000, 0x24066000,
                                                         0x24068000, 0x2406A000, 0x24073000, 0x24062200)
APP_PADS = 0x24020088 + 0x1840
VOICE = PAD + 0x260 + 0x410
MASTER, AREA = 0xC0000000, 0xC0100000
PMEM, PCHECK = 0x38800F70, 0x38800F74
SEG = PAD + 0x30
N = 256                                           # stock's engine block
LEN = 96000
SPS, SLOT = 6000.0, 5454.5454                     # a 1/16 slice of a 120 BPM loop played at 132 BPM (+10 %)
fails = 0
# a stereo test loop: a decaying "drum" every 6000 frames over two tones (deterministic)
left, right = [], []
for i in range(LEN):
    k = i % 6000
    hit = math.exp(-k / 600.0) * math.sin(2 * math.pi * 180 * k / 48000)
    left.append(0.4 * hit + 0.2 * math.sin(2 * math.pi * 330 * i / 48000))
    right.append(0.4 * hit + 0.2 * math.sin(2 * math.pi * 440 * i / 48000))


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def fstr(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


e = Emu(IMAGE, "out/cave.elf")
e.fetches = []


def fetch():
    dst, n, pos = e.arg(1), e.arg(2), e.arg(3)
    e.fetches.append((pos, n))
    e.uc.mem_write(dst, struct.pack(f"<{n}f", *[left[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


def fetch2():
    l, r, n, pos = e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    e.fetches.append((pos, n))
    e.uc.mem_write(l, struct.pack(f"<{n}f", *[left[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))
    e.uc.mem_write(r, struct.pack(f"<{n}f", *[right[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


e.stub(0x08063634, fetch)
e.stub(0x08063608, fetch2)
e.stub(0x080636F0, value=LEN)
e.stub(0x08063790, value=1)
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x200000)
e.w32(PAD + 0x24, SRC)
e.w32(PAD + 0x18, 1 << 8 | 2)                     # row 1, col 2 = pad 6
Q = 6
e.uc.mem_write(MASTER, b"\xa5" * 0x94910)         # whatever the SDRAM held (the stretch area is magic-checked)
e.uc.mem_write(AREA, b"\xa5" * 0x80000)
e.w32(PMEM, MASTER)
e.w32(PCHECK, MASTER ^ 0x5052534D)
e.w32(MASTER + 0x94900, AREA)
e.meter_up()


def setting(model):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x14C, 0, model))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))
    for _ in range(16):
        e.call("stretch_tick")


def pad(sync=1, divs=16, step=240, slicer=0, sps=SPS, slot=SLOT):
    e.uc.mem_write(PAD + 0x1F5, bytes([sync]))
    e.uc.mem_write(PAD + 0x1FC, struct.pack("<f", sps))
    e.uc.mem_write(PAD + 0x204, struct.pack("<f", slot))
    e.w32(PAD + 0x210, divs)
    e.w32(PAD + 0x220, step)
    e.uc.mem_write(PAD + 0x254, bytes([slicer]))


def segment(i, pos, slice_, end=0, active=1):
    s = SEG + i * 0x70
    e.uc.mem_write(s, bytes([active, 0]))
    e.uc.mem_write(s + 8, struct.pack("<qq", pos, end))
    e.w32(s + 0x34, slice_)


def read(pos, frac, rate, n=N):
    for buf, d, r in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        e.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, r, 0, 1))
    e.uc.mem_write(OUTD, bytes(4 * n))
    e.uc.mem_write(OUTR, bytes(4 * n))
    e.uc.mem_write(VARS, struct.pack("<ifI", -1, frac, 0))
    e.uc.reg_write(UC_ARM_REG_S0, fstr(rate))
    for k, v in enumerate((n, VARS, VARS + 4, SCR, OUT, VARS + 8)):
        e.w32(STACK + 4 * k, v)
    e.fetches.clear()
    e.uc.reg_write(UC_ARM_REG_R11, VOICE)
    e.call("clip_read_b", PAD, 0, pos, 0, count=50_000_000)
    ok = e.uc.reg_read(UC_ARM_REG_R0)
    used, nfrac, res = struct.unpack("<ifI", e.uc.mem_read(VARS, 12))
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    l = list(struct.unpack(f"<{n}f", e.uc.mem_read(dl, 4 * n)))
    r = list(struct.unpack(f"<{n}f", e.uc.mem_read(dr, 4 * n)))
    return ok, used, nfrac, l, r


cnt = [0]
counting = [False]
e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: cnt.__setitem__(0, cnt[0] + 1) if counting[0] else None)


def play(slice_, rate, blocks, seg=0):
    """a segment from its slice start, position += used the way stock's caller does; returns l, r, instr per block"""
    pos, frac = int(slice_ * SPS + 0.5), 0.0
    segment(seg, pos, slice_)
    l, r, cost = [], [], []
    for _ in range(blocks):
        counting[0], cnt[0] = True, 0
        ok, used, frac, bl, br = read(pos, frac, rate)
        counting[0] = False
        cost.append(cnt[0])
        l += bl
        r += br
        pos += used
        e.uc.mem_write(SEG + seg * 0x70 + 8, struct.pack("<q", pos))
    return l, r, cost


# Mac reference
lib = os.path.join("host", "libstretch.dylib")
subprocess.run(["clang", "-O2", "-DSTR_HOST", "-shared", "-fPIC", "-o", lib, "src/stretch_dsp.c", "host/stretch_host.c"], check=True)
L = ctypes.CDLL(os.path.abspath(lib))
F = ctypes.POINTER(ctypes.c_float)
L.render_segment.argtypes = [F, F, ctypes.c_int, ctypes.c_int32, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_int, F, F, ctypes.c_int, ctypes.c_int]
LA, RA = (ctypes.c_float * LEN)(*left), (ctypes.c_float * LEN)(*right)


def mac(start, rate, model, n):
    ol, orr = (ctypes.c_float * n)(), (ctypes.c_float * n)()
    L.render_segment(LA, RA, LEN, start, SPS, rate, SPS / SLOT, model, ol, orr, n, N)
    return list(ol), list(orr)


pad()
BLOCKS = 22                                       # 5632 frames: the whole slot and a little run-on
for model, name in ((1, "Smooth"), (2, "Keyframe"), (3, "Cyclic")):
    setting(model)
    for rate in (1.0, 0.9187, 1.26):
        l, r, cost = play(3, rate, BLOCKS)
        ml, mr = mac(int(3 * SPS + 0.5), rate, model, BLOCKS * N)
        err = max(max(abs(a - b) for a, b in zip(l, ml)), max(abs(a - b) for a, b in zip(r, mr)))
        check(f"{name}, rate {rate}: the firmware's output matches the Mac build of the same DSP (max diff {err:.2e})", err < 2e-4, err)
        live = max(abs(v) for v in l) > 0.05
        check(f"{name}, rate {rate}: not silent", live)
        if rate == 1.0:
            cost = cost[1:] if model == 1 else cost       # the first read of the run also pays the one-off bank 2 pairing scan
            avg, peak = sum(cost) / len(cost) / N, max(cost) / N
            print(f"     cost {name}: {avg:.0f} instructions / frame on average, peak block {peak:.0f} / frame "
                  f"(~{avg / 100:.1f} % / {peak / 100:.1f} % of the CPU per playing stereo clip at ~100 instr = 1 %)")

# --- what stays stock
setting(0)
ok, used, frac, l, _ = read(int(2 * SPS), 0.0, 1.0)
counting[0], cnt[0] = True, 0
read(int(2 * SPS), 0.0, 1.0)
counting[0] = False
stock_cost = cnt[0]
setting(1)
pad(); segment(0, int(2 * SPS), 2)
counting[0], cnt[0] = True, 0
ok2, used2, frac2, l2, _ = read(int(2 * SPS), 0.0, 1.0)
counting[0] = False
print(f"     (stock's own read of the same block: {stock_cost} instructions)")


def is_stock(label, **kw):
    """the pad / segment as given, model Smooth: the read must equal model Stock's"""
    setting(0)
    a = read(kw.get("pos", int(5 * SPS)), 0.0, 1.0)
    setting(1)
    b = read(kw.get("pos", int(5 * SPS)), 0.0, 1.0)
    check(label, a == b)


pad(sync=0); segment(0, int(5 * SPS), 5)
is_stock("Sync off: stock")
pad(divs=1); segment(0, int(5 * SPS), 5)
is_stock("one slice (no stretch): stock")
pad(step=0xF0000); segment(0, int(5 * SPS), 5)
is_stock("Sync = Slice (markers): stock")
pad(slicer=1); segment(0, int(5 * SPS), 5)
is_stock("a slicer pad: stock")
pad(); segment(0, int(15 * SPS), 15, end=LEN - 1)
is_stock("the last slice (has an end point: stock plays it at its own speed): stock", pos=int(15 * SPS))
pad(); segment(0, int(5 * SPS) + 1000, 5)
is_stock("joined mid-slice (model switched on while it played): stock until the next slice", pos=int(5 * SPS) + 1000)
pad(); segment(0, int(5 * SPS), 5, active=0)
is_stock("no live segment at that position: stock")

# --- the model changed while a slice plays: stock for the rest of it (no jump back to the slice start)
pad(); setting(1)
segment(0, int(7 * SPS), 7)
ok, used, frac, _, _ = read(int(7 * SPS), 0.0, 1.0)
setting(2)
setting(0)
a = read(int(7 * SPS) + used, frac, 1.0)
setting(2)
segment(0, int(7 * SPS) + used, 7)
b = read(int(7 * SPS) + used, frac, 1.0)
check("Smooth -> Keyframe in the middle of a slice: stock's reader for the rest of it", a == b)

# --- a new slice after a mid-slice join: the model takes over
pad(); setting(1)
l, r, _ = play(6, 1.0, 2)
ml, _ = mac(int(6 * SPS + 0.5), 1.0, 1, 2 * N)
check("the next slice after a mid-slice join plays through the model", max(abs(a - b) for a, b in zip(l, ml)) < 2e-4)


# --- a clip selection (clipsel.c leaves it in pad+0x238 / 0x23c): slice N starts at Start + N x sps, reads stay inside
pad(); setting(1)
e.w32(PAD + 0x238, 12000); e.w32(PAD + 0x23C, 60000)
segment(0, 12000 + int(2 * SPS), 2)
counting[0] = False
ok, used, frac, l, r = read(12000 + int(2 * SPS), 0.0, 1.0)
res = struct.unpack("<I", e.uc.mem_read(VARS + 8, 4))[0]
check("with a selection, slice 2 starts at Start + 2 x sps and plays through the model", res == OUT, hex(res))
check("... and never fetches before Start or past End", all(p >= 12000 - 1 and p + n <= 60000 + 1 for p, n in e.fetches) or not e.fetches, e.fetches[:4])
e.w32(PAD + 0x238, 0); e.w32(PAD + 0x23C, LEN)


# --- past the selection's End: silent, as stock past the file's end (filter.c clip_read)
setting(0); pad()
e.w32(PAD + 0x238, 12000); e.w32(PAD + 0x23C, 30000)
segment(0, 30000 - 100, 3)
ok, used, frac, l, r = read(30000 - 100, 0.0, 1.0)
check("stock reader at End - 100: the first 100 frames sound, the rest is silent",
      ok == 1 and max(abs(v) for v in l[:100]) > 0.01 and all(v == 0.0 for v in l[100:] + r[100:]), (ok, l[98:102]))
ok, used, frac, l, r = read(30000 - 100, 0.0, 1.5)
check("... at rate 1.5: silent from frame 67 (source 30000 reached at 66.7)", all(v == 0.0 for v in l[67:]) and abs(l[66]) > 0.0, l[64:69])
ok = read(30000 + 0x100, 0.0, 1.0)[0]
check("0xff past End: nothing at all (0), as stock past the file", ok == 0, ok)
e.w32(PAD + 0x238, 0); e.w32(PAD + 0x23C, LEN)

# --- slots: 32 live segments at most, the 33rd reads stock
setting(1)
pad()
seq = e.r32(AREA + 4)
OWN = AREA + 444                                  # offsetof(struct str_bank, own), arm-none-eabi
held = sum(1 for i in range(32) if e.r32(OWN + 24 * i) and (seq - e.r32(OWN + 4 + 24 * i)) & 0xFFFFFFFF < 256)
outs = []
for k in range(33):
    p = 0xC0178000 + k * 0x1000              # 33 distinct "pads" (spare SDRAM) sharing pad 6's settings: copy the pad
    e.uc.mem_write(p, bytes(e.uc.mem_read(PAD, 0xC00)))
    s = p + 0x30
    e.uc.mem_write(s, bytes([1, 0]))
    e.uc.mem_write(s + 8, struct.pack("<qq", int(4 * SPS), 0))
    e.w32(s + 0x34, 4)
    for buf, d, rr in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        e.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, rr, 0, 1))
    e.uc.mem_write(VARS, struct.pack("<ifI", -1, 0.0, 0))
    e.uc.reg_write(UC_ARM_REG_S0, fstr(1.0))
    for j, v in enumerate((N, VARS, VARS + 4, SCR, OUT, VARS + 8)):
        e.w32(STACK + 4 * j, v)
    e.uc.reg_write(UC_ARM_REG_R11, p + 0x260 + 0x410)
    e.call("clip_read_b", p, 0, int(4 * SPS), 0, count=50_000_000)
    outs.append(struct.unpack("<I", e.uc.mem_read(VARS + 8, 4))[0])
free = 32 - held
check(f"{free} free slots ({held} still held by recent segments): {free} new segments read through the model, then every "
      "slot is busy and the rest fall back to stock's reader",
      all(o == OUT for o in outs[:free]) and all(o != OUT for o in outs[free:]), [hex(o) for o in outs])

# --- marker slices: Slicer pads (Sync on) and Clip on Sync = Slice (stretch.c mk_spawn + str_clip's marker branch)
MK = AREA + 342248                                # offsetof(struct str_bank, mk), arm-none-eabi; 16 B per [pad][seg]
HOLD, TAIL = 0x28, 0x30


def mk(q, i):
    return struct.unpack("<iiiBB", e.uc.mem_read(MK + (q * 4 + i) * 16, 14))


SPAWNS = []


def fake_spawn():                                 # FUN_08065290: claims seg 1, sizes it the slow way (natural < slot)
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    SPAWNS.append(tuple(e.r32(sp + 4 * k) for k in range(6)))
    s = SEG + 1 * 0x70
    e.w32(s + HOLD, 4800)
    e.w32(s + TAIL, 900)
    e.uc.reg_write(UC_ARM_REG_R0, 1)


e.stub(0x08065290, fake_spawn)


def spawn(pos, slot, span, slicer=1, thru=0):
    pad(slicer=slicer)
    e.uc.mem_write(PAD + 0x255, bytes([thru]))
    for k, v in enumerate((pos, slot, 0, 0, span, 0)):   # call() passes r0-r3 only: the rest on the stack, as stock
        e.w32(STACK + 4 * k, v)
    e.call("mk_spawn", PAD, 0, 0, 3)
    return e.uc.reg_read(UC_ARM_REG_R0)


setting(1)
OWN1 = OWN + 0                                    # a model slot that still holds seg 1 from its last slice
e.w32(OWN1, SEG + 1 * 0x70)
r = spawn(18000, 6000, 5200)
rec = mk(Q, 1)
check("mk_spawn: stock's spawn runs with the same arguments and its result comes back",
      r == 1 and SPAWNS[-1] == (18000, 6000, 0, 0, 5200, 0), (r, SPAWNS[-1:]))
check("... a Slicer slice (PlayThru off) is recorded as stock sized it: start 18000, span 5200, slot 6000, kind CUT",
      rec[:4] == (18000, 5200, 6000, 1), rec)
check("... stock's silent tail (900) is folded into the hold (4800 -> 5700): the model fills the slot, lifetime unchanged",
      e.r32(SEG + 0x70 + HOLD) == 5700 and e.r32(SEG + 0x70 + TAIL) == 0 and rec[4] == 1,
      (e.r32(SEG + 0x70 + HOLD), e.r32(SEG + 0x70 + TAIL), rec))
check("... the model slot that held the respawned segment is free again", e.r32(OWN1) == 0, hex(e.r32(OWN1)))
spawn(18000, 6000, 5200, thru=1)
check("PlayThru on: kind THRU", mk(Q, 1)[3] == 2, mk(Q, 1))
spawn(18000, 6000, 5200, slicer=0)
check("a Clip on Sync = Slice: kind CLIP", mk(Q, 1)[3] == 3, mk(Q, 1))
spawn(18000, 900, 800)
check("a slice shorter than the model's hop (900 frames): no record, no fold: stock plays it",
      mk(Q, 1)[3] == 0 and e.r32(SEG + 0x70 + HOLD) == 4800 and e.r32(SEG + 0x70 + TAIL) == 900,
      (mk(Q, 1), e.r32(SEG + 0x70 + TAIL)))
setting(0)
spawn(18000, 6000, 5200)
check("Stretch Stock: no record, no fold", mk(Q, 1)[3] == 0 and e.r32(SEG + 0x70 + TAIL) == 900, mk(Q, 1))


def readm(pos, frac, rate, segi, n=N):
    """read() with frac in the segment (seg + 0x1c), as stock passes it at BL @0x08066622"""
    fr = SEG + segi * 0x70 + 0x1C
    for buf, d, rr in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        e.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, rr, 0, 1))
    e.uc.mem_write(OUTD, bytes(4 * n))
    e.uc.mem_write(OUTR, bytes(4 * n))
    e.uc.mem_write(VARS, struct.pack("<iI", -1, 0))
    e.uc.mem_write(fr, struct.pack("<f", frac))
    e.uc.reg_write(UC_ARM_REG_S0, fstr(rate))
    for k, v in enumerate((n, VARS, fr, SCR, OUT, VARS + 4)):
        e.w32(STACK + 4 * k, v)
    e.fetches.clear()
    e.uc.reg_write(UC_ARM_REG_R11, VOICE)
    e.call("clip_read_b", PAD, 0, pos, 0, count=50_000_000)
    ok = e.uc.reg_read(UC_ARM_REG_R0)
    used, res = struct.unpack("<iI", e.uc.mem_read(VARS, 8))
    nfrac = struct.unpack("<f", e.uc.mem_read(fr, 4))[0]
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    return (ok, used, nfrac, list(struct.unpack(f"<{n}f", e.uc.mem_read(dl, 4 * n))),
            list(struct.unpack(f"<{n}f", e.uc.mem_read(dr, 4 * n))), res)


def playm(start, span, slot, rate, blocks, model, thru):
    setting(model)
    spawn(start, slot, span, thru=thru)
    segment(1, start, 3)
    pos, frac, l, r, fetched = start, 0.0, [], [], []
    for _ in range(blocks):
        ok, used, frac, bl, br, res = readm(pos, frac, rate, 1)
        fetched += e.fetches
        l += bl
        r += br
        pos += used
        e.uc.mem_write(SEG + 0x70 + 8, struct.pack("<q", pos))
    return l, r, fetched


def macm(start, span, slot, rate, model, n):
    ol, orr = (ctypes.c_float * n)(), (ctypes.c_float * n)()
    L.render_segment(LA, RA, LEN, start, span, rate, span / slot, model, ol, orr, n, N)
    return list(ol), list(orr)


for model, name in ((1, "Smooth"), (2, "Keyframe"), (3, "Cyclic")):
    l, r, _ = playm(18000, 5200, 6000, 1.0, 22, model, thru=1)
    ml, mr = macm(18000, 5200, 6000, 1.0, model, 22 * N)
    err = max(max(abs(a - b) for a, b in zip(l, ml)), max(abs(a - b) for a, b in zip(r, mr)))
    check(f"Slicer slice (PlayThru on), {name}: reads through the model = the Mac build on start 18000 / span 5200 / "
          f"slot 6000 (max diff {err:.2e}), not silent", err < 2e-4 and max(abs(v) for v in l) > 0.05, err)
    l, r, fetched = playm(18000, 5200, 6000, 1.0, 22, model, thru=0)
    inside = all(p >= 18000 - 1 and p + n <= 23200 + 1 for p, n in fetched)
    check(f"Slicer slice (PlayThru off), {name}: never fetches outside the slice [18000, 23200)", inside and bool(fetched),
          [f for f in fetched if not (f[0] >= 17999 and f[0] + f[1] <= 23201)][:3])

# a folded slice that falls back to stock (Stretch changed mid-slice) past its source end: silence, not slice 4
setting(1)
spawn(18000, 6000, 5200)
segment(1, 18000, 3)
pos, frac = 18000, 0.0
for _ in range(4):
    ok, used, frac, _, _, _ = readm(pos, frac, 1.0, 1)
    pos += used
    e.uc.mem_write(SEG + 0x70 + 8, struct.pack("<q", pos))
setting(2)                                         # Keyframe now: this slice goes to stock for the rest
e.uc.mem_write(SEG + 0x70 + 8, struct.pack("<q", 23300))
ok, used, frac, l, r, res = readm(23300, 0.0, 1.0, 1)
check("folded slice, Stretch changed mid-slice, read past the slice's source end (23300 > 23200): silence (not slice 4)",
      ok == 1 and max(abs(v) for v in l + r) == 0.0 and used == 256, (ok, used, max(abs(v) for v in l + r)))

img = open(IMAGE, "rb").read()
check("Slicer POS page: 'Stretch:' (0x14c) in the last slot of both table copies",
      all(struct.unpack_from("<H", img, a - 0x08040000)[0] == 0x14C for a in (0x080EF836, 0x080EF12E)))

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
