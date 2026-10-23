"""Clip / slicer pads' reader in the Fidelity machine modes (3.1.U), under Unicorn.

Real firmware runs for: the stock clip reader FUN_080662e4 and its kernel FUN_080603ec (Normal / HighQ / crunch
settings, in the patched image and in an unpatched one side by side), the buffer helpers, the settings lookup.
Stubbed: the sample source (FUN_08063634 / FUN_08063608 fetch, FUN_080636f0 length, FUN_08063790 stereo).
Reference for the machine modes: the Python models of the drop-sample reader and of the S950's DAC staircase, both
at the position stock's kernel reads from (the segment's position + 1 + its fraction).
NOT checked: the caller (segments, slice hand-overs, the crossfades between them, tempo-synced clips), how it sounds,
CPU on the chip.
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R11, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
PAD, SRC, SCR, OUT, SCRD, SCRR, OUTD, OUTR, ARR, VARS = (0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24064000, 0x24066000,
                                                         0x24068000, 0x2406A000, 0x24073000, 0x24062200)
APP_PADS = 0x24020088 + 0x1840
VOICE = PAD + 0x260 + 0x410                      # the pad's SECOND voice object (FUN_08067fa4); filter object = + 0x14c
N = 64
LEN = 400000
left = [0.4 * math.sin(2 * math.pi * 3000 * i / 48000) + 0.3 * math.sin(2 * math.pi * 9500 * i / 48000) for i in range(LEN)]
right = [0.25 * math.sin(2 * math.pi * 5000 * i / 48000) for i in range(LEN)]
stream = left
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def fstr(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def machine(image):
    m = Emu(image, "out/cave.elf")
    m.uc.mem_map(0x38800000, 0x1000)             # backup SRAM + RCC: clipwin_read asks master.c for its SDRAM block first
    m.uc.mem_map(0x58024000, 0x1000)
    m.fetches = []

    def fetch():
        dst, n, pos = m.arg(1), m.arg(2), m.arg(3)
        m.fetches.append((pos, n))
        m.uc.mem_write(dst, struct.pack(f"<{n}f", *[left[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))

    def fetch2():
        l, r, n, pos = m.arg(1), m.arg(2), m.arg(3), m.r32(m.uc.reg_read(UC_ARM_REG_SP))
        m.fetches.append((pos, n))
        m.uc.mem_write(l, struct.pack(f"<{n}f", *[left[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))
        m.uc.mem_write(r, struct.pack(f"<{n}f", *[right[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))

    m.stub(0x08063634, fetch)
    m.stub(0x08063608, fetch2)
    m.stub(0x080636F0, value=LEN)
    m.stub(0x08063790, value=0)
    m.w32(PAD + 0x24, SRC)
    m.w32(PAD + 0x18, 1 << 8 | 2)
    return m


e, stock = machine(IMAGE), machine("firmware/BLACKBOX-3.1.9.bin")


def fidelity(v, sat=0):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xDB, 0, sat) + struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 2))


def read(m, target, pos, frac, rate, stereo=False, n=N):
    """one call: returns (ok, used, new frac, which buffer, left, right)"""
    m.stub(0x08063790, value=int(stereo))
    for buf, d, r in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        m.uc.mem_write(buf, struct.pack("<IIIIBB", 4096, 4096, d, r if stereo else 0, 0, int(stereo)))
    m.uc.mem_write(OUTD, bytes(4 * n))
    m.uc.mem_write(OUTR, bytes(4 * n))
    m.uc.mem_write(VARS, struct.pack("<ifI", -1, frac, 0))
    m.uc.reg_write(UC_ARM_REG_S0, fstr(rate))
    for k, v in enumerate((n, VARS, VARS + 4, SCR, OUT, VARS + 8)):
        m.w32(STACK + 4 * k, v)
    m.fetches.clear()
    m.uc.reg_write(UC_ARM_REG_R11, VOICE)          # fp at the call site: the voice object (clip_read_b)
    m.call(target, PAD, 0, pos, 0, count=20_000_000)
    ok = m.uc.reg_read(UC_ARM_REG_R0)
    used, nfrac, res = struct.unpack("<ifI", m.uc.mem_read(VARS, 12))
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    l = list(struct.unpack(f"<{n}f", m.uc.mem_read(dl, 4 * n)))
    r = list(struct.unpack(f"<{n}f", m.uc.mem_read(dr, 4 * n))) if stereo else None
    return ok, used, nfrac, res, l, r


def play(m, target, pos, frac, rate, blocks, stereo=False):
    """follow the position the way the caller does: position += used, the fraction carried"""
    l, r, trail = [], [], []
    for _ in range(blocks):
        ok, used, frac, res, bl, br = read(m, target, pos, frac, rate, stereo)
        trail.append((pos, used, frac))
        l += bl
        r += br or []
        pos += used
    return l, r, trail


# --- settings outside the machine modes: stock, to the bit
for v, name in ((0, "Normal"), (1, "HighQ"), (9, "12k crunch")):
    fidelity(v)
    for rate, frac, stereo in ((0.7, 0.25, False), (1.0, 0.0, False), (1.0, 0.3, False), (2.3, 0.6, False), (0.7, 0.25, True)):
        a = play(e, "clip_read_b", 5000, frac, rate, 4, stereo)
        b = play(stock, 0x080662E4, 5000, frac, rate, 4, stereo)
        check(f"Fidelity {name}, rate {rate}, fraction {frac}{', stereo' if stereo else ''}: audio, samples used and fraction identical to stock",
              a == b, (a[2][:2], b[2][:2]))

# --- machine modes: the same bookkeeping as stock, the machines' readers at the position stock reads from
FIR = {26040: [0.00302, 0.24563, 0.5027, 0.24563, 0.00302], 40000: [-0.03947, 0.16746, 0.74402, 0.16746, -0.03947],
       27500: [-0.00396, 0.24215, 0.52363, 0.24215, -0.00396]}
S950 = {4: (48000.0, [-0.07796, 0.18391, 0.7881, 0.18391, -0.07796]), 7: (31250.0, [-0.06897, 0.27256, 0.59283, 0.27256, -0.06897])}


def drop_model(P, rate, n, grid):
    g, h, out = 48000 / grid, FIR[grid], []
    for i in range(n):
        j = round(math.floor((P + i * rate) / g + 1 / 8192) * g)
        out.append(sum(h[t] * stream[j - 2 + t] for t in range(5)))
    return out


def stored(K, g, h, gain=1.0, post=1.0):
    j = math.floor(K * g + 0.5)
    v = sum(h[t] * (stream[j - 2 + t] if 0 <= j - 2 + t < LEN else 0.0) for t in range(5)) * gain
    v = min(max(v, -1.0), 2047 / 2048)
    return math.floor(v * 2048 + 0.5) / 2048 * post


def stair_model(P, rate, n, grid, h, gain=1.0, post=1.0):
    g, out = 48000 / grid, []
    for i in range(n):
        t0, t1 = (P + i * rate) / g, (P + (i + 1) * rate) / g
        m0, m1 = math.floor(t0), math.floor(t1)
        if m0 == m1:
            out.append(stored(m0, g, h, gain, post))
            continue
        acc = stored(m0, g, h, gain, post) * (m0 + 1 - t0) + sum(stored(m, g, h, gain, post) for m in range(m0 + 1, m1))
        out.append((acc + stored(m1, g, h, gain, post) * (t1 - m1)) / (t1 - t0))
    return out


def off(got, ref, tol=2e-4):
    return [i for i in range(len(got)) if abs(got[i] - ref[i]) > tol]


for v, name, grid in ((2, "SP1200", 26040), (3, "SP-12", 27500), (5, "MPC60", 40000), (6, "SP Raw", 26040)):
    fidelity(v)
    for rate, frac in ((0.5, 0.25), (0.8909, 0.0), (1.0, 0.0), (1.4983, 0.5)):
        got, _, trail = play(e, "clip_read_b", 5000, frac, rate, 6)
        fidelity(0)
        _, _, ref_trail = play(e, "clip_read_b", 5000, frac, 1.0 if rate == 1.0 and frac == 0.0 else rate, 6)
        fidelity(v)
        bad = off(got, drop_model(5000 + 1 + frac, rate, 6 * N, grid))
        check(f"{name} on a clip / slicer voice, rate {rate}: read only on its {grid} Hz grid, six blocks ({len(bad)} of {len(got)} frames off)",
              len(bad) <= 2, bad[:6])
        check(f"  and the position moves exactly as with Fidelity Normal ({trail[-1][1]} samples in the last block)",
              [(p, u) for p, u, f in trail] == [(p, u) for p, u, f in ref_trail] and all(abs(a[2] - b[2]) < 1e-6 for a, b in zip(trail, ref_trail)),
              (trail[-2:], ref_trail[-2:]))

for v, name in ((4, "S950"), (7, "S950 Lo")):
    grid, h = S950[v]
    fidelity(v)
    for rate, frac in ((0.5, 0.25), (0.8909, 0.0), (1.0, 0.0), (1.4983, 0.5), (3.7, 0.1)):
        got, _, trail = play(e, "clip_read_b", 5000, frac, rate, 6)
        bad = off(got, stair_model(5000 + 1 + frac, rate, 6 * N, grid, h))
        check(f"{name} on a clip / slicer voice, rate {rate}: the DAC staircase's area per frame, six blocks ({len(bad)} of {len(got)} frames off)",
              len(bad) <= 2, bad[:6])
    check(f"  {name}: the rate is left in the reading voice's own filter object (voice + 0x14c + 0x60)",
          abs(struct.unpack("<f", e.uc.mem_read(VOICE + 0x14C + 0x60, 4))[0] - 3.7) < 1e-6)

# stereo: both channels, the same grid, one fraction out
fidelity(2)
gl, gr, trail = play(e, "clip_read_b", 7000, 0.6, 0.75, 4, stereo=True)
bad_l = off(gl, drop_model(7000 + 1.6, 0.75, 4 * N, 26040))
stream = right
bad_r = off(gr, drop_model(7000 + 1.6, 0.75, 4 * N, 26040))
stream = left
check("SP1200, stereo clip: both channels drop-sampled on the same grid", len(bad_l) <= 2 and len(bad_r) <= 2, (bad_l[:4], bad_r[:4]))
fidelity(4)
gl, gr, _ = play(e, "clip_read_b", 7000, 0.6, 0.75, 4, stereo=True)
bad_l = off(gl, stair_model(7000 + 1.6, 0.75, 4 * N, *S950[4]))
stream = right
bad_r = off(gr, stair_model(7000 + 1.6, 0.75, 4 * N, *S950[4]))
stream = left
check("S950, stereo clip: both channels", len(bad_l) <= 2 and len(bad_r) <= 2, (bad_l[:4], bad_r[:4]))

# the very start of a sample: nothing is fetched from before it
for v, name in ((2, "SP1200"), (4, "S950")):
    fidelity(v)
    ok, used, frac, res, l, _ = read(e, "clip_read_b", 0, 0.0, 0.8)
    check(f"{name} at the sample's first frame: fetched from 0, the three samples before it are silence, finite",
          ok == 1 and all(p >= 0 for p, n in e.fetches) and e.fetches and all(math.isfinite(x) for x in l) and res == OUT, (ok, e.fetches))
ok, used, frac, res, l, _ = read(e, "clip_read_b", 1, 0.0, 0.8)
want = stair_model(1 + 1, 0.8, N, *S950[4])
check("  S950 one frame in: the staircase from the start of the sample", len(off(l, want)) <= 1, off(l, want)[:4])

# past the end, and a rate that is not forward: stock's answers
fidelity(4)
ok = read(e, "clip_read_b", LEN + 300, 0.0, 0.8)[0]
check("past the end of the sample: 0, as stock", ok == 0 and read(stock, 0x080662E4, LEN + 300, 0.0, 0.8)[0] == 0)
a = read(e, "clip_read_b", LEN - 20, 0.0, 0.8)
check("the last frames of the sample: finite, read as far as the source goes", a[0] == 1 and all(math.isfinite(x) for x in a[4]))

# Saturation = the converter's input level
fidelity(4, sat=1000)
got = play(e, "clip_read_b", 5000, 0.25, 0.5, 4)[0]
bad = off(got, stair_model(5000 + 1.25, 0.5, 4 * N, *S950[4], gain=8.0, post=1 / 2.1))
check("S950 on a clip, Saturation 100 %: +18 dB into the converter's ceiling before the 12 bits", len(bad) <= 2, bad[:6])

# cost
from unicorn import UC_HOOK_CODE
cnt = [0]
hk = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
for v, name in ((0, "Normal (stock)"), (2, "SP1200"), (4, "S950"), (7, "S950 Lo")):
    fidelity(v)
    read(e, "clip_read_b", 5000, 0.3, 0.8)
    cnt[0] = 0
    read(e, "clip_read_b", 5000, 0.3, 0.8)
    print(f"     clip reader cost, {name}: {cnt[0]} instructions per 64-frame mono block (incl. fetch stub)")
e.uc.hook_del(hk)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
