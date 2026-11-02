"""Clip pads: tempo from a selection (src/clipsel.c), under Unicorn.

Real firmware runs for: stock's clip setup FUN_08064a94 (through our trampoline in the patched image; untouched in
stock 3.1.9 side by side) with its helpers (2^x, ticks <-> frames, 64-bit divide), stock's slice spawn FUN_08065550 in
both images, our hooks, stock's settings lookup.
Stubbed: the sample object (length / rate / seek hint), the regrid (recorded), the Waveform screen's knob widgets as
test_slice.py stubs them.
Parity claim: a clip with a selection [s, e) gets EXACTLY the setup stock gives a file e - s long (every field it
writes), apart from 0x238 / 0x23c, which hold s / e; with no selection the patched setup equals stock's to the bit.
NOT checked: the engine's slice clock between spawns, the screen's drawing, how it sounds, the pad id format the
screen uses (row << 8 | col, assumed), external clock.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
PAD, SAMPLE, CLK, LAYER, ARR = 0x24060000, 0x24061000, 0x24061100, 0x24062000, 0x24063000
APP_PADS = 0x24020088 + 0x1840
STORE = APP_PADS + 1 * 0xF0 + 2 * 0x30            # pad id row 1, col 2
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def machine(image):
    m = Emu(image, "out/cave.elf")
    m.len = [0]
    m.uc.mem_map(0x38800000, 0x1000)
    m.uc.mem_map(0x58024000, 0x1000)
    m.stub(0x080636F0, lambda: m.ret(m.len[0]))
    m.stub(0x0806377C, value=44100)
    m.hints = []
    m.stub(0x0806375C, lambda: m.hints.append(m.arg(1)))
    return m


e, st = machine(IMAGE), machine("firmware/BLACKBOX-3.1.9.bin")


def f32(v):
    return struct.pack("<f", v)


def pad(m, beatcount=0, quant=3840, sync=240, sync_on=1, tempo=120.0, pitch=0):
    m.uc.mem_write(PAD, bytes(0xC00))
    m.w32(PAD + 0x18, 1 << 8 | 2)
    m.w32(PAD + 0x24, SAMPLE)
    m.uc.mem_write(PAD + 0x1F5, bytes([sync_on]))
    m.uc.mem_write(PAD + 0x218, struct.pack("<qq", quant, sync))
    m.w32(PAD + 0xA80, pitch)
    m.w32(PAD + 0xB80, beatcount)
    m.uc.mem_write(CLK, bytes(0x40))
    m.uc.mem_write(CLK + 0x18, f32(tempo))


def store(start=0, end=0, beats=0):
    e.uc.mem_write(ARR, struct.pack("<HHi", 0x15C, 0, start) + struct.pack("<HHi", 0x15D, 0, end) +
                   struct.pack("<HHi", 0x15E, 0, beats))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 3))


FIELDS = [(0x1F0, 4), (0x1FC, 4), (0x204, 4), (0x208, 8), (0x210, 4), (0x230, 8), (0x240, 4), (0x244, 4), (0x258, 4),
          (0xBA8, 8), (0xBB0, 1)]


def fields(m):
    return {hex(o): bytes(m.uc.mem_read(PAD + o, n)).hex() for o, n in FIELDS}


def setup(m, length):
    m.len[0] = length
    m.call(0x08064A94, PAD, CLK, count=5_000_000)


LEN = 441000                                      # 10 s at 44.1 kHz
CASES = [dict(), dict(tempo=97.0), dict(sync=960), dict(sync_on=0), dict(quant=0), dict(beatcount=8), dict(pitch=-3500)]

# --- no selection: the patched setup is stock's
store()
for kw in CASES:
    pad(e, **kw); setup(e, LEN)
    pad(st, **kw); setup(st, LEN)
    a, b = fields(e), fields(st)
    check(f"no selection {kw}: every field stock setup writes is identical to stock 3.1.9", a == b, {k: (a[k], b[k]) for k in a if a[k] != b[k]})
    check(f"no selection {kw}: 0x238 / 0x23c = 0 / the file length, as stock", e.r32(PAD + 0x238) == 0 and e.r32(PAD + 0x23C) == LEN)

# --- a selection MEASURES (decided 10-25): Start..End holds Beats beats; the clip plays every whole beat from Start to
# the file's end. Expected = stock setup on a file that long (whole beats from Start) with that many beats as Beat Count.
import numpy as np
F32 = np.float32


def auto_beats(n, frate, tempo):                        # clipsel.c auto_beats, in the same float32 steps
    L = F32(n) / F32(frate) * (F32(tempo) / F32(60.0))
    ticks = int(L * F32(960.0) + F32(0.5)); r = int(F32(ticks) / F32(960.0) + F32(0.5)); P = 960
    if r > 1:
        p = 1
        while p * 2 <= r:
            p *= 2
        P = 960 * p
    lo = ticks // P * P; hi = lo + P
    return (lo if ticks - lo < hi - ticks else hi) // 960


def plan(s, end, beats, tempo):
    e_ = end or LEN
    b = beats if beats else auto_beats(e_ - s, 44100, tempo)
    fpb = F32(e_ - s) / F32(b)
    total = int(F32(LEN - s) / fpb)
    play = min(LEN, s + int(F32(total) * fpb + F32(0.5)))
    return total, play


for (s, end, beats) in ((44100, 132300, 0), (10000, 400000, 0), (0, 220500, 0), (88200, 0, 0), (44100, 132300, 4), (44100, 132300, 3)):
    store(s, end, beats)
    for kw in CASES:
        total, play = plan(s, end, beats, kw.get("tempo", 120.0))
        pad(e, **kw); setup(e, LEN)
        pad(st, **dict(kw, beatcount=total)); setup(st, play - s)
        a, b = fields(e), fields(st)
        check(f"selection {s}..{end} beats {beats or 'Auto'} {kw}: plays {total} whole beats from Start = stock setup on a "
              f"file {play - s} frames long with Beat Count {total}", a == b, {k: (a[k], b[k]) for k in a if a[k] != b[k]})
        check("  ... 0x238 / 0x23c = Start / the end of the last whole beat, Beat Count back as it was",
              e.r32(PAD + 0x238) == s and e.r32(PAD + 0x23C) == play and e.r32(PAD + 0xB80) == kw.get("beatcount", 0),
              (e.r32(PAD + 0x238), e.r32(PAD + 0x23C), play))

# --- selections that are not applied
for (s, end, why) in ((0, 0, "nothing set"), (0, LEN, "the whole file"), (1000, 1200, "shorter than 512 frames"),
                      (500000, 0, "Start past the end")):
    store(s, end)
    pad(e); setup(e, LEN)
    pad(st); setup(st, LEN)
    check(f"not applied ({why}): stock", fields(e) == fields(st) and e.r32(PAD + 0x238) == 0)
store(44100, 132300)
pad(e); e.w32(PAD + 0x254, 1); setup(e, LEN)
check("a slicer pad: no selection", e.r32(PAD + 0x238) == 0)
pad(e); e.w32(PAD + 0x220, 0xF0000); e.w32(PAD + 0x224, 0); e.w32(PAD + 0x250, 3); setup(e, LEN)
check("Sync = Slice with markers: no selection", e.r32(PAD + 0x238) == 0)

# --- spawn: slice N of the selection
S, E = 44100, 132300
store(S, E)
TOTAL, PLAY = plan(S, E, 0, 120.0)


def spawn(m, index):
    for k, v in enumerate((0, index and 0, 0)):
        pass
    m.uc.mem_write(LAYER, bytes(0x400))
    m.w32(STACK, CLK); m.w32(STACK + 4, 60); m.w32(STACK + 8, 0)
    m.hints.clear()
    m.call(0x08065550 if m is st else "sel_spawn", PAD, LAYER, 0, index, count=5_000_000)
    r = m.uc.reg_read(UC_ARM_REG_R0)
    seg = PAD + 0x30 + r * 0x70
    pos, end = struct.unpack("<qq", m.uc.mem_read(seg + 8, 16))
    return r, pos, end, m.r32(seg + 0x28), list(m.hints)


pad(e); setup(e, LEN)
pad(st, beatcount=TOTAL); setup(st, PLAY - S)
q = e.r32(PAD + 0x240)
for index in (0, 1, q - 1):
    pad_e = bytes(e.uc.mem_read(PAD, 0xC00))
    a = spawn(e, index)
    b = spawn(st, index)
    last = index == q - 1
    ok = a[0] == b[0] and a[1] == b[1] + S and (a[2] == (PLAY - 1 if last else 0)) and abs(a[3] - b[3]) <= 1
    check(f"spawn slice {index} of {q}{' (the last)' if last else ''}: position + Start, "
          f"{'end = End - 1, hold as stock computes it for that end' if last else 'no end, same hold'}",
          ok, (a, b))
    check(f"  ... seek hint at the moved position", a[4] and a[4][-1] == max(a[1] - 8, 0), a[4])
    e.uc.mem_write(PAD, pad_e)
    for i in range(4):
        e.uc.mem_write(PAD + 0x30 + i * 0x70, bytes(2))
    st.uc.mem_write(PAD + 0x30, bytes(0x1C0))

# --- regrid: stock's runs on positions relative to the selection, which are then put back
seen = []
e.stub(0x08064E7C, lambda: seen.append([struct.unpack("<q", e.uc.mem_read(PAD + 0x30 + i * 0x70 + 8, 8))[0] for i in range(2)]))
pad(e); setup(e, LEN)
for i, p in enumerate((S + 5000, S + 30000)):
    e.uc.mem_write(PAD + 0x30 + i * 0x70, bytes([1, 0]))
    e.uc.mem_write(PAD + 0x30 + i * 0x70 + 8, struct.pack("<q", p))
e.call("sel_regrid", PAD, 0, 0, 0)
back = [struct.unpack("<q", e.uc.mem_read(PAD + 0x30 + i * 0x70 + 8, 8))[0] for i in range(2)]
check("regrid: stock sees positions from the selection's start; they are put back after", seen == [[5000, 30000]] and back == [S + 5000, S + 30000], (seen, back))


# --- the Waveform screen, Clip mode (widgets stubbed as test_slice.py does)
u = Emu(IMAGE, "out/cave.elf")
u.uc.mem_map(0x38800000, 0x1000)
u.uc.mem_map(0x58024000, 0x1000)
u.uc.mem_map(0xC0000000, 0x100000)
VIEW, MSG, VSTORE, GSTORE = 0x24060000, 0x24069000, 0x2406A000, 0x2406A100
TL, TR, BL, BR = VIEW + 0x670, VIEW + 0xC30, VIEW + 0x950, VIEW + 0xF10
WAVE = VIEW + 0x38
KNOB_VTABLE = 0x080F0C88
MASTER, AREA = 0xC0000000, 0xC0098000
u.w32(0x38800F70, MASTER)
u.w32(0x38800F74, MASTER ^ 0x5052534D)
u.w32(MASTER + 0x94900, AREA)


def upost():
    m = u.arg(1)
    u.calls.append(("post", u.r16(m), u.r32(m + 0xC), u.r32(m + 0x10)))


u.stub(0x080AED14, upost)
u.stub(0x080C3B98, lambda: u.calls.append(("text", u.cstr(u.arg(1)))))
u.stub(0x080B0528)
u.stub(0x080B0480)
u.stub(0x080C6E8C, lambda: u.calls.append(("wave_slices",)))
for k in (TL, TR, BL, BR):
    u.w32(k, KNOB_VTABLE)
u.stub(u.r32(KNOB_VTABLE + 0x2C) & ~1)


def ustore(at, entries):
    arr = at + 0x40
    u.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in entries))
    u.w32(at + 4, arr)
    u.uc.mem_write(at + 10, struct.pack("<H", len(entries)))


def view(start, end, beats=0, mode=1):
    ustore(VIEW + 0x2370, [(0x8B, mode), (0x15C, start), (0x15D, end), (0x15E, beats)])
    ustore(0x24020088 + 0x8C90, [(0x84, 120)])
    u.w32(VIEW + 0x2390, LEN)
    u.uc.mem_write(VIEW + 0x29C, struct.pack("<H", 1 << 4 | 2))   # the SCREEN's pad id: app cell id, row << 4 | col (the engine's is row << 8 | col)
    u.uc.mem_write(WAVE + 0x168, f32(256.0))
    u.uc.mem_write(WAVE + 0x24C, f32(0.0))
    u.call("stretch_tick")                              # brings the SDRAM area up
    u.w32(AREA + 28 + 6 * 24 + 4, 44100)              # what setup publishes: pad 6's file rate (str_clipinfo.frate)


def uknob(k):
    return dict(param=u.r32(k + 0x14), type=u.r8(k + 0x31), lo=u.r32(k + 0x14C), hi=u.r32(k + 0x150), value=u.r32(k + 0x34))


def bind_all():
    c = []
    for name, k in (("sel_bind_start", TL), ("sel_bind_end", TR), ("sel_bind_beats", BL), ("sel_bind_bpm", BR)):
        c += u.call(name, 0, 0, k)
    return c


def umsg(param, value):
    u.uc.mem_write(MSG, struct.pack("<HHIHHiII", 0x3D, 0, 0x080CFBA4, 0, 0, value, param, 0))
    return u.call(0x080A66DC, VIEW, MSG)


view(S, E)
c = bind_all()
check("Clip mode: the four knobs read Start: / End: / Beats: / BPM:",
      all(("text", t) in c for t in ("Start:", "End:", "Beats:", "BPM:")), c)
check("Start: a position knob on 0x15c, 0 .. as far as the section still fits in the file, at the section's start",
      uknob(TL) == dict(param=0x15C, type=0xD, lo=0, hi=LEN - (E - S), value=S), uknob(TL))
check("End: a position knob on 0x15d, Start + 512 .. the file end, at the selection's end",
      uknob(TR) == dict(param=0x15D, type=0xD, lo=S + 512, hi=LEN, value=E), uknob(TR))
check("Beats knob = Beats + 1: Auto = 1, Detect = 0 (no negative knob values), up to 513",
      uknob(BL)["value"] == 1 and uknob(BL)["param"] == 0x3E3 and uknob(BL)["lo"] == 0 and uknob(BL)["hi"] == 513, uknob(BL))
check("BPM: the selection's own tempo = 120.0 (the knob holds tenths)", uknob(BR)["value"] == 1200 and uknob(BR)["param"] == 0x3E4, uknob(BR))

c = umsg(0x3E4, 1201)
check("BPM one detent up: Beats x2 (8) to the app, BPM reads 240",
      ("post", 0x6E, 0x15E, 8) in c and uknob(BR)["value"] == 2400 and uknob(BL)["value"] == 9, (c, uknob(BL), uknob(BR)))
c = umsg(0x3E4, 2399)
check("BPM one detent down: Beats /2 (4), BPM 120", ("post", 0x6E, 0x15E, 4) in c and uknob(BR)["value"] == 1200, c)
c = umsg(0x3E3, 4)
check("Beats turned to 3: stored, BPM 90", ("post", 0x6E, 0x15E, 3) in c and uknob(BR)["value"] == 900, (c, uknob(BR)))
c = umsg(0x15C, 22050)
check("Start moved with Beats set (3): the value to the app as any knob, Beats NOT reset (asked for 10-24)",
      ("post", 0x6E, 0x15C, 22050) in c and not any(x[0] == "post" and x[2] == 0x15E for x in c), c)
check("... Start is where it begins and a beat: the section slides with it (End posted at E - 22050), so Beats 3 and "
      "BPM 90 stay", ("post", 0x6E, 0x15D, E - 22050) in c and uknob(BL)["value"] == 4 and uknob(BR)["value"] == 900,
      (c, uknob(BL), uknob(BR)))
check("... End's lower limit follows Start", uknob(TR)["lo"] == 22050 + 512, uknob(TR))
view(S, E, beats=0)
bind_all()
c = umsg(0x15D, E + 22050)
check("End moved with Beats on Auto: no Beats write, Beats stays Auto, the guess follows (2.5 s at 120 -> 4 beats, BPM 96)",
      not any(x[0] == "post" and x[2] == 0x15E for x in c) and uknob(BL)["value"] == 1 and uknob(BR)["value"] == 960,
      (c, uknob(BL), uknob(BR)))

u.calls.clear()
u.call("sel_wave", WAVE, 0)
check("waveform: stock's slice markers, then the selection as Start / End markers",
      ("wave_slices",) in u.calls and u.r32(WAVE + 0x228) == S and u.r32(WAVE + 0x234) == E + 22050 - S and u.r8(WAVE + 0x23A) == 1,
      (u.calls, u.r32(WAVE + 0x228), u.r32(WAVE + 0x234)))
view(0, 0)
u.call("sel_bind_start", 0, 0, TL)
u.uc.mem_write(WAVE + 0x23A, b"\0")
u.call("sel_wave", WAVE, 0)
check("no selection: no Start / End markers (as stock)", u.r8(WAVE + 0x23A) == 0)
view(S, E, mode=0)
c = umsg(0x3E2, 5)
check("not our knob ids: the slicer forward carries on as before", not any(x[0] == "post" and x[2] == 0x15E for x in c), c)

# --- audition while stopped: one block sees Quant None + Sync off, the real values come back after
CTX, CLK2, PADB = 0x24069800, 0x24069900, 0x24070000
seen = []
u.stub(0x08067FA4, lambda: seen.append((struct.unpack("<q", u.uc.mem_read(u.arg(0) + 0x218, 8))[0], u.r8(u.arg(0) + 0x1F5))))
u.uc.mem_write(PADB, bytes(0xC00))
u.uc.mem_write(PADB + 0x218, struct.pack("<q", 3840)); u.uc.mem_write(PADB + 0x1F5, b"\1")
u.w32(CTX, CLK2)
for playing, slicer, want, label in ((0, 0, (0, 0), "stopped: the block runs as Quant None, Sync off"),
                                      (1, 0, (3840, 1), "playing: untouched"),
                                      (0, 1, (3840, 1), "stopped, a Slicer pad: untouched")):
    seen.clear()
    u.uc.mem_write(CLK2 + 0x38, bytes([playing])); u.uc.mem_write(PADB + 0x254, bytes([slicer]))
    u.call("sel_block", PADB, CTX, 0, 0)
    back = (struct.unpack("<q", u.uc.mem_read(PADB + 0x218, 8))[0], u.r8(PADB + 0x1F5))
    check(f"audition, {label}; Quant / Sync back after", seen == [want] and back == (3840, 1), (seen, back))
u.uc.mem_write(PADB + 0x254, b"\0")
# a Quant change made inside a stopped block (the handler writes the real field): kept, not clobbered by the restore
AUD = AREA + 416                                           # str_bank.aud (offsetof, arm-none-eabi): pad, quant s64 +8, sync +16, on +17
u.w32(AUD, PADB); u.uc.mem_write(AUD + 8, struct.pack("<q", 3840)); u.uc.mem_write(AUD + 16, bytes([1, 1]))
u.uc.mem_write(PADB + 0x218, bytes(8)); u.uc.mem_write(PADB + 0x1F5, b"\0")
u.stub(0x08067648, lambda: (seen.append(("param", struct.unpack("<q", u.uc.mem_read(u.arg(0) + 0x218, 8))[0])),
                            u.uc.mem_write(u.arg(0) + 0x218, struct.pack("<q", 1920))))
seen.clear()
u.call("sel_param", PADB, 0x47, 0, 0)
check("a Quant change during a stopped block: the handler sees the real Quant, its new value is kept for the restore, "
      "the block keeps seeing None", seen == [("param", 3840)] and struct.unpack("<q", u.uc.mem_read(AUD + 8, 8))[0] == 1920
      and struct.unpack("<q", u.uc.mem_read(PADB + 0x218, 8))[0] == 0, (seen, struct.unpack("<q", u.uc.mem_read(AUD + 8, 8))[0]))
u.uc.mem_write(AUD + 16, bytes([1, 0]))

# --- knob acceleration on position knobs
K = 0x24071000
M = [1]
u.stub(0x080B0CE0, lambda: u.ret(M[0]))
def accel(m, lo, hi, spp):
    M[0] = m
    u.w32(K + 0x14C, lo); u.w32(K + 0x150, hi); u.w32(K + 0x28C, spp)
    u.call("sel_accel", K + 0x294)
    return u.uc.reg_read(UC_ARM_REG_R0)
check("slow turn (stock x1): x1 on any length, fine control", accel(1, 0, 28_800_000, 256) == 1)
short = [accel(m, 0, 40000, 256) for m in (2, 4, 6)]
check(f"a short sample (156 steps across): stock's own 1..6 ({short})", short == [2, 4, 6], short)
mid = [accel(m, 0, 441000, 256) for m in (2, 4, 6)]
check(f"10 s at a pixel a step (1,722 steps): a gentle turn stays stock, full speed ~3 turns across ({mid})", mid[0] == 2 and 25 <= mid[2] <= 32, mid)
fast = [accel(m, 0, 28_800_000, 256) for m in (2, 3, 4, 6)]
check(f"a 10-minute file (112,500 steps): grows with speed, full speed ~1.5 turns across ({fast})",
      fast[0] == 2 and fast[1] <= 6 and fast[1] < fast[2] < fast[3] and 1800 <= fast[3] <= 1950, fast)

# --- tempo detection, end to end: an empty Clip pad opens on the Waveform screen -> the job runs a step per audio block
# (stretch_tick) -> the result arrives as Start / End / Beats. A 2-bar loop at 123 BPM (44.1 kHz).
import os
from scipy.io import wavfile as _wf
LOOP = os.environ.get("CLIPSEL_LOOP", "")              # a 2-bar loop at 123 BPM (WAV); unset = these checks are skipped
if os.path.exists(LOOP):
    rate, x = _wf.read(LOOP)
    x = x.astype(np.float32) / (np.abs(x).max() + 1e-9)
    TL_, TR_ = x[:, 0].copy(), x[:, 1].copy()
    PADE, SRCE = 0x24072000, 0x24073800
    u.uc.mem_write(PADE, bytes(0xC00))
    u.w32(PADE + 0x18, 1 << 8 | 2); u.w32(PADE + 0x24, SRCE)
    u.stub(0x080636F0, value=len(TL_)); u.stub(0x0806377C, value=rate); u.stub(0x08063790, value=1)
    calls = [0]
    def fetch2():
        calls[0] += 1
        l, r, n, pos = u.arg(1), u.arg(2), u.arg(3), u.r32(u.uc.reg_read(UC_ARM_REG_SP))
        if calls[0] % 5 == 0:                         # every 5th read: that block is not loaded yet
            u.ret(0); return
        seg = slice(pos, pos + n)
        u.uc.mem_write(l, np.pad(TL_[seg], (0, n - len(TL_[seg]))).astype(np.float32).tobytes())
        u.uc.mem_write(r, np.pad(TR_[seg], (0, n - len(TR_[seg]))).astype(np.float32).tobytes())
        u.ret(1)
    u.stubs[0x08063608] = fetch2
    view(0, 0)
    u.w32(VIEW + 0x2390, len(TL_))
    u.w32(AREA + 28 + 6 * 24, PADE)                   # what setup leaves: pad 6's engine object
    TJ = AREA + 297020                                # offsetof(struct str_bank, tj)
    r0 = u.r32(TJ + 156)
    bind_all()
    check("opening an empty Clip pad on the Waveform screen does NOT run the detector (opt in: decided 10-25)",
          u.r32(TJ + 156) == r0, (u.r32(TJ + 156), r0))
    u.uc.mem_write(TJ + 36, b"\x5a" * (148 - 36))   # the job as SDRAM garbage (power-on): loop, n_top, best_* ...
    u.w32(TJ + 64, 1)                                 # ... and a loop flag left set (the first detection after a boot)
    umsg(0x3E3, 0)
    check("Beats turned down to Detect asks for it", u.r32(TJ + 156) == r0 + 1, u.r32(TJ + 156))
    u.call("stretch_tick", count=50_000_000)          # the audio side picks the request up: the job starts
    check("... the job starts", u.r32(TJ) == 1, u.r32(TJ))
    from unicorn import UC_HOOK_CODE as _H
    cnt, worst, blocks = [0], 0, 0
    hk = u.uc.hook_add(_H, lambda uc, a, s_, d: cnt.__setitem__(0, cnt[0] + 1))
    while u.r32(TJ) not in (8, 9) and blocks < 3000:  # TEMPO_DONE / TEMPO_FAILED
        cnt[0] = 0
        u.call("stretch_tick", count=50_000_000)
        worst = max(worst, cnt[0]); blocks += 1
    u.uc.hook_del(hk)
    u.calls.clear()
    u.call("sel_wave", WAVE, 0)
    posts = [c for c in u.calls if c[0] == "post"]
    got = {c[2]: c[3] for c in posts if c[1] == 0x6E}
    beats = got.get(0x15E, 0); s0, e0 = got.get(0x15C, -1), got.get(0x15D, -1)
    bpm_sel = beats * 60 * rate / (e0 - s0) if e0 > s0 else 0
    check(f"auto tempo on a 123 BPM loop: done in {blocks} blocks (~{blocks * 256 / 48000:.1f} s), worst block {worst} "
          f"instructions (~{worst / 256 / 100:.1f} % of that block); Start {s0}, End {e0}, Beats {beats} = {bpm_sel:.1f} BPM",
          u.r32(TJ) == 0 and abs(bpm_sel - 123) < 1.5 and 0 <= s0 < rate, (u.r32(TJ), got))
    check("... from a job left as garbage with the loop flag set (3.4.h on glass: 129.4 for 194.5 on the first run "
          "after a boot)", abs(bpm_sel - 123) < 1.5, bpm_sel)
    check("... the knobs show it: Beats and BPM", uknob(BL)["value"] == beats + 1 and abs(uknob(BR)["value"] - 1236) <= 10, (uknob(BL), uknob(BR)))
    check("... the job's work stays under ~1 % of a block", worst < 256 * 120, worst)

# --- a new clip (nothing set): Start moves on its own (glass test 10-25: it would not move until End had)
view(0, 0)
u.call("sel_bind_start", 0, 0, TL); u.call("sel_bind_end", 0, 0, TR)
check("new clip: Start can go anywhere up to the file's end less 512 frames", uknob(TL)["hi"] == LEN - 512, uknob(TL))
c = umsg(0x15C, 44100)
check("... turning it posts only Start (no End: the section runs to the file's end)",
      ("post", 0x6E, 0x15C, 44100) in c and not any(x[0] == "post" and x[2] == 0x15D for x in c), c)

# --- the knob text: BPM tenths "123.6"; "~" while Beats is Auto (stock's guess from the project tempo: 3.4.g showed it
# like a detected tempo, glass test 10-25); "Detect.." / "Fail n" for the detector; Beats 0 reads "Guess"; others untouched
TXT = []
u.stub(0x080C3B98, lambda: TXT.append(u.cstr(u.arg(1))))
TJ = AREA + 297020                                    # offsetof(struct str_bank, tj)
REQ, SERVED, MISSES = TJ + 156, TJ + 160, TJ + 168
CI6 = AREA + 28 + 6 * 24                              # str_clipinfo of pad 6: eng, frate, s, e, beats, have, fail


def ktext(knob, raw):
    TXT.clear()
    u.uc.mem_write(0x24074200, raw.encode() + b"\0")
    u.call("sel_knob_text", knob + 0x9C, 0x24074200)
    return list(TXT)


view(S, E, beats=4)
bind_all()
for raw, want in (("1236", "123.6"), ("905", "90.5"), ("7", "0.7")):
    check(f"BPM text {raw!r} with Beats set -> {want!r}", ktext(BR, raw) == [want], TXT)
view(S, E, beats=0)
bind_all()
u.w32(SERVED, u.r32(REQ)); u.w32(TJ, 0)              # no detection in flight (an earlier test left one asked)
check("BPM text with Beats on Auto: '~120.0' (a guess, not a detection)", ktext(BR, "1200") == ["~120.0"], TXT)
check("Beats knob at 1 reads 'Guess' (stock's Beat Count owns 'Auto')", ktext(BL, "1") == ["Guess"], TXT)
check("Beats knob at 0 reads 'Detect'", ktext(BL, "0") == ["Detect"], TXT)
check("Beats knob at 4 reads '3' (3 beats)", ktext(BL, "4") == ["3"], TXT)
check("Beats knob at 513 reads '512'", ktext(BL, "513") == ["512"], TXT)
check("Start knob untouched", ktext(TL, "1236") == ["1236"], TXT)

c = umsg(0x3E3, 2)
check("Beats: the first turn up from Auto keeps the guess shown (4 for 2 s at 120), BPM 120",
      ("post", 0x6E, 0x15E, 4) in c and uknob(BL)["value"] == 5 and uknob(BR)["value"] == 1200, (c, uknob(BL)))
c = umsg(0x3E3, 6)
check("... then a beat a detent (5)", ("post", 0x6E, 0x15E, 5) in c, c)
r0 = u.r32(REQ)
c = umsg(0x3E3, 1)
check("Beats turned to Auto: Beats 0, Start / End kept, no detection",
      ("post", 0x6E, 0x15E, 0) in c and not any(x[0] == "post" and x[2] in (0x15C, 0x15D) for x in c) and u.r32(REQ) == r0,
      (c, u.r32(REQ), r0))
c = umsg(0x3E3, 0)
check("Beats turned down past Auto to Detect: Start and End to 0, Beats 0, the detector asked (opt in, decided 10-25)",
      ("post", 0x6E, 0x15C, 0) in c and ("post", 0x6E, 0x15D, 0) in c and ("post", 0x6E, 0x15E, 0) in c
      and u.r32(REQ) == r0 + 1 and u.r32(TJ + 164) == 6, (c, u.r32(REQ), r0))
check("... the BPM knob says 'Detect..'", ktext(BR, "0") == ["Detect.."], TXT)

# --- the request waits for the pad's engine object (3.4.g dropped it in the first block: no tempo, no sign of it)
u.w32(CI6, 0)
view(0, 0)
bind_all()
umsg(0x3E3, 0)
for _ in range(40):
    u.call("stretch_tick", count=5_000_000)
check("no engine object yet: after 40 blocks the request still waits", u.r32(REQ) != u.r32(SERVED) and u.r32(MISSES) == 40,
      (u.r32(REQ), u.r32(SERVED), u.r32(MISSES)))
for _ in range(4000):
    u.call("stretch_tick", count=5_000_000)
check("... after ~20 s (4000 blocks) it gives up", u.r32(REQ) == u.r32(SERVED) and u.r32(TJ) == 9, (u.r32(TJ), u.r32(MISSES)))
u.calls.clear()
u.call("sel_wave", WAVE, 0)
check("... and the BPM knob says 'Fail 1' (no engine), nothing posted",
      ktext(BR, "0") == ["Fail 1"] and not any(x[0] == "post" for x in u.calls), (TXT, u.calls))
c = umsg(0x15C, 1000)
check("... the first turn clears the 'Fail'", u.r8(CI6 + 21) == 0, u.r8(CI6 + 21))

# --- a new sample clears the selection: sel_reset_cell runs stock's reset (FUN_0809aa94), then empties 0x15c..0x15e
RESET = []
CST, REF = 0x24075900, 0x24075800
ustore(CST, [(0x8B, 1), (0x8F, 7), (0x15C, 5000), (0x15D, 90000), (0x15E, 8)])
u.stub(0x0809AA94, lambda: RESET.append((u.arg(0), u.arg(1))))
u.stub(0x08098D0C, value=CST)
u.uc.mem_write(REF + 4, struct.pack("<H", 1 << 4 | 2))
u.uc.mem_write(CI6 + 20, bytes([1, 3]))
u.call("sel_reset_cell", 0x24020088, REF)
vals = {i: v for i, _, v in struct.iter_unpack("<HHi", bytes(u.uc.mem_read(CST + 0x40, 40)))}
check("sel_reset_cell: stock's reset runs first (same arguments)", RESET == [(0x24020088, REF)], RESET)
check("... then Start / End / Beats are 0 (the next Waveform visit detects again); stock's own ids untouched",
      vals[0x15C] == 0 and vals[0x15D] == 0 and vals[0x15E] == 0 and vals[0x8F] == 7 and vals[0x8B] == 1, vals)
check("... and the pad's knob copy / Fail are forgotten", u.r8(CI6 + 20) == 0 and u.r8(CI6 + 21) == 0)


# --- a new sample on a pad that already had one / a recording into a Clip pad: stock's write, then the selection goes
SETS = []
u.stub(0x08093ECC, lambda: SETS.append((u.arg(0), u.arg(1), u.arg(2))))
PST = 0x24020088 + 0x1840 + 2 * 0xF0 + 1 * 0x30          # app pad store, row 2 col 1 = pad 9
CI9 = AREA + 28 + 9 * 24
u.uc.mem_write(CI9 + 20, bytes([1, 2]))
u.call("sel_assign_clear", PST, 0x90, 0)
check("sel_assign_clear: stock's write first (0x90 = 0), then Start / End / Beats = 0 on that store",
      SETS == [(PST, 0x90, 0), (PST, 0x15C, 0), (PST, 0x15D, 0), (PST, 0x15E, 0)], SETS)
check("... and pad 9's knob copy / Fail (row 2, col 1 from the store's address) are forgotten",
      u.r8(CI9 + 20) == 0 and u.r8(CI9 + 21) == 0, (u.r8(CI9 + 20), u.r8(CI9 + 21)))
SETS.clear()
u.call("sel_assign_clear", 0x24060000, 0x95, 7)
check("... a store that is not a pad's: stock's write only", SETS == [(0x24060000, 0x95, 7)], SETS)


def bl_target(img, at):
    off = at - 0x08040000
    h1, h2 = struct.unpack_from("<HH", img, off)
    S_ = (h1 >> 10) & 1; i1 = 1 - (((h2 >> 13) & 1) ^ S_); i2 = 1 - (((h2 >> 11) & 1) ^ S_)
    imm = (S_ << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + (imm - (1 << 25) if S_ else imm)


img = open(IMAGE, "rb").read()
sites = (0x0809D618, 0x0809D664, 0x0809D6A6, 0x0809DD30, 0x0809F7CA, 0x080A004E, 0x080A01F6, 0x080A0CBA)
check("all 8 of stock's Start / Length resets (assign, recording, header, rebuild, mode) call sel_reset_cell",
      all(bl_target(img, a) == u.sym["sel_reset_cell"] & ~1 for a in sites), [hex(bl_target(img, a)) for a in sites])
check("... the project loader's (0x0809CB78, empty pads only) still calls stock's", bl_target(img, 0x0809CB78) == 0x0809AA94)
check("sample assigned to a pad that had one (0x080a0b6c) and both recording-done 0x95 writes call sel_assign_clear",
      all(bl_target(img, a) == u.sym["sel_assign_clear"] & ~1 for a in (0x080A0B6C, 0x0809D622, 0x0809D686)))
check("Waveform view vtable slot 0 (0x080f0004) = sel_view_tick",
      struct.unpack_from("<I", img, 0x080F0004 - 0x08040000)[0] == u.sym["sel_view_tick"] | 1)

# --- with the 123 BPM loop again: a knob turned while the detector runs keeps its value; a long file gets a 4-bar section
if os.path.exists(LOOP):
    L0, R0 = TL_, TR_

    def run_job():
        b = 0
        while u.r32(TJ) not in (8, 9) and b < 6000:
            u.call("stretch_tick", count=50_000_000)
            b += 1
        return b

    def fresh(n):
        view(0, 0)
        u.w32(VIEW + 0x2390, n)
        u.w32(CI6, PADE)
        bind_all()
        umsg(0x3E3, 0)

    fresh(len(TL_))
    for _ in range(20):
        u.call("stretch_tick", count=50_000_000)
    umsg(0x15C, 1000)                                 # Start turned while it runs
    run_job()
    u.calls.clear()
    u.call("sel_wave", WAVE, 0)
    check("Start turned while the detector ran: its answer is dropped, Start stays 1000 (3.4.g overwrote it)",
          not any(x[0] == "post" for x in u.calls) and uknob(TL)["value"] == 1000, (u.calls, uknob(TL)))

    TL_, TR_ = np.tile(L0, 12), np.tile(R0, 12)
    u.stub(0x080636F0, value=len(TL_))
    fresh(len(TL_))
    run_job()
    u.calls.clear()
    u.call("sel_wave", WAVE, 0)
    got = {x[2]: x[3] for x in u.calls if x[0] == "post" and x[1] == 0x6E}
    bt = got.get(0x15E, 0)
    bpm_l = bt * 60 * rate / (got[0x15D] - got[0x15C]) if bt else 0
    # the honest answer on 47 s of this loop tiled is 169.9 (host/tempo_host.c in a fresh process agrees); 3.4.h's test
    # read 123.6 only because the previous job's loop flag was left set: the bug the job reset fixes
    check(f"a {len(TL_) / rate:.0f} s file: the detected section is 4 bars (16 beats, was every beat to the end), "
          f"{bpm_l:.1f} BPM = the Mac build's 169.9 on the same audio; BPM text plain (a detection, no '~')",
          bt == 16 and abs(bpm_l - 169.9) < 0.2 and ktext(BR, str(int(bpm_l * 10))) == [f"{int(bpm_l * 10) / 10:.1f}"],
          (got, TXT))
    TL_, TR_ = L0, R0
    u.stub(0x080636F0, value=len(TL_))

    # the screen redraws only on events: the per-frame tick collects a finished detection (glass test 10-25: "Detect.."
    # until PLAY was pressed)
    TICKS = []
    u.stub(0x080A6F20, lambda: TICKS.append((u.arg(0), u.arg(1))))
    fresh(len(TL_))
    run_job()
    u.calls.clear()
    u.call("sel_view_tick", VIEW, 0x24074300)
    got = {x[2]: x[3] for x in u.calls if x[0] == "post" and x[1] == 0x6E}
    check("the Waveform view's per-frame tick takes a finished detection (no redraw needed), then runs stock's tick",
          got.get(0x15E, 0) > 0 and TICKS == [(VIEW, 0x24074300)] and ktext(BR, "1236") == ["123.6"], (got, TICKS, TXT))
    u.calls.clear()
    u.call("sel_view_tick", VIEW, 0x24074300)
    check("... and the next frame posts nothing (taken once)", not any(x[0] == "post" for x in u.calls), u.calls)
    u.uc.mem_write(VIEW + 0x2370 + 0x40 + 4, struct.pack("<i", 0))   # mode 0x8b = Sample
    u.w32(REQ, u.r32(REQ) + 1); u.w32(TJ + 164, 6); u.w32(CI6, PADE)
    run_job()
    u.calls.clear()
    u.call("sel_view_tick", VIEW, 0x24074300)
    check("... in Sample mode the tick leaves the job alone", not any(x[0] == "post" for x in u.calls) and u.r32(TJ) == 8,
          (u.calls, u.r32(TJ)))
    u.w32(TJ, 0)

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
