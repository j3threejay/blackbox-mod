"""Master FX slot (VHS) and the Compressor / Master FX knob pages, under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c). Stubbed and recorded: set-screen, list clear / add, the
stock page builder, label, the stock compressor, registration.
NOT checked: anything the screen draws, that the knob screen accepts the global cell on hardware, that turning a knob
there writes the global setting, saving to settings.tml, how VHS sounds, CPU on the real chip.
"""
import math
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
APP = 0x24020088
STORE, ARR = APP + 0x8C90, 0x24070000
OBJ, VT, BUFS, L, R = 0x24060000, 0x24061000, 0x24050000, 0x24064000, 0x24066000
UI, GL = 0x38800B1C, 0x38800F20
N = 256
calls = []
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def settings(**kw):
    ids = {"comp": 0xB4, "mfx": 0x1DB, "wow": 0x1DC, "flutter": 0x1DD, "sat": 0x1DE, "fail": 0x1DF, "noise": 0x1E0,
           "hicut": 0x1E1, "locut": 0x1E2, "thresh": 0x1D0, "depth": 0x1EA, "smashtime": 0x1EB,
           "edit": 0x19C, "fx0": 0x19D, "fx1": 0x19E, "fx2": 0x19F, "fx3": 0x1A0, "amt0": 0x1A1, "amt1": 0x1A2, "amt2": 0x1A3,
           "amt3": 0x1A4, "tilt": 0x1A5, "rate": 0x1A6, "time": 0x1A7, "mix": 0x1A8}
    vals = {v: 0 for v in ids.values()}
    vals.update({ids[k]: v for k, v in kw.items()})
    rows = sorted(vals.items())
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", len(rows)))


e.stub(0x0804EDDC, lambda: calls.append(("stock",)), value=1)
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 3))
e.w32(OBJ + 8, 0)
BUF = BUFS + 3 * 0x14 + 0x150E4


def block(left, right=None):
    right = left if right is None else right
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.uc.mem_write(R, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R, 0, 1))
    calls.clear()
    e.call("comp_process", OBJ, BUFS, count=20_000_000)
    return (list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left)))),
            list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(R, 4 * len(right)))))


def sine(amp, hz, start=0, n=N):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def run(blocks, hz=440, amp=0.5, right_amp=None):
    e.uc.mem_write(GL, b"\0" * 4)
    outl, outr = [], []
    for b in range(blocks):
        x = sine(amp, hz, b * N)
        l, r = block(x, None if right_amp is None else sine(right_amp, hz, b * N))
        outl += l
        outr += r
    return outl, outr


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def f32(x):
    return [struct.unpack("<f", struct.pack("<f", v))[0] for v in x]


# --- registration and defaults ride on the compressor's hooks
lists, nums, added = [], [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.w32(STACK, 0)
e.w32(STACK + 4, 1000)
e.w32(STACK + 8, 0x080CC3F4)
e.call("comp_register", 0x24001000, 0xB4, 4, 0x080CC3E8)
check("Master FX registered: list param 0x1db 'Master FX:' [Off, VHS, Prism, TapeScam], xml 'mfx'", lists[1] == (0x1DB, "Master FX:", ["Off", "VHS", "Prism", "TapeScam"], "mfx"), lists)
check("VHS's seven settings registered (0x1dc..0x1e2)", nums[3:10] == [(0x1DC, "Wow:", "mfxwow"), (0x1DD, "Flutter:", "mfxflutter"), (0x1DE, "Saturate:", "mfxsat"), (0x1DF, "Dropout:", "mfxfail"),
                                                                        (0x1E0, "Noise:", "mfxnoise"), (0x1E1, "Hi Cut:", "mfxhicut"), (0x1E2, "Lo Cut:", "mfxlocut")], nums)
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("comp_defaults", 0x24072000, 0xB4, 1)
check("defaults: Master FX Off, with usable VHS settings behind it", added[4] == (0x1DB, 0) and [a[0] for a in added[5:12]] == list(range(0x1DC, 0x1E3)), added)
page = [e.r16(0x080EED18 + 2 * k) for k in range(14)]
check("Tools Main page: Headphone, Master FX, Compressor (the order the audio runs in), then the rest, Theme last (12 rows: Groove is on Clock)", page[:4] == [0xBA, 0x1DB, 0xB4, 0xBB] and page[10:13] == [0x19B, 0x144, 0], [hex(v) for v in page])

# --- knob pages
settings(comp=3, thresh=-6000, mfx=1, wow=250)
LIST, CELL = 0x24074000, 0x24075000
built = []
e.stub(0x080A4FC2, lambda: built.append("clear"))
e.stub(0x080A5038, lambda: built.append((e.arg(1), e.arg(2) - (1 << 32) if e.arg(2) >> 31 else e.arg(2))))
e.stub(0x08098D40, lambda: built.append(("stock", e.arg(3))), value=7)


def build(cell_id):
    built.clear()
    e.uc.mem_write(CELL + 4, struct.pack("<H", cell_id))
    e.call("master_list", APP, CELL, LIST, 0)
    return e.uc.reg_read(UC_ARM_REG_R0), list(built)


e.uc.mem_write(UI, bytes([0, 1]))
check("global cell, Compressor page: Compressor + Comp Thresh with their saved values, then the clipper's three", build(0x40) == (1, ["clear", (0xB4, 3), (0x1D0, -6000), (0x1B4, 0), (0x1B2, 0), (0x1B3, 0)]), build(0x40))
settings(comp=7, thresh=-6000, mfx=1, wow=250)
check("Compressor page with Smash selected: Compressor, Depth, Time, Comp Thresh, Clipper, Clip, Shape", [b[0] for b in build(0x40)[1][1:]] == [0xB4, 0x1EA, 0x1EB, 0x1D0, 0x1B4, 0x1B2, 0x1B3], build(0x40))
settings(comp=3, thresh=-6000, mfx=1, wow=250)
e.uc.mem_write(UI, bytes([1, 1]))
r = build(0x40)
check("global cell, Master FX page (VHS): its seven knobs, no type knob (picked on the Tools row, tester report 10-25)", r[0] == 1 and [b[0] for b in r[1][1:]] == list(range(0x1DC, 0x1E3)) and r[1][1] == (0x1DC, 250), r)
check("a delay / reverb cell: the stock page builder, untouched", build(0x310) == (7, [("stock", 0)]))
check("...and the master page flag is dropped (the knob screen is on an FX cell again)", e.r8(UI + 1) == 0)

# --- buttons
screens = []
e.stub(0x0809EAEC, lambda: screens.append((e.arg(1), e.r16(APP + 0x28))))
e.uc.mem_write(APP + 0x28, struct.pack("<H", 0x310))
e.uc.mem_write(APP + 0x8CA4, bytes([0x25]))


def press(fn, *a):
    screens.clear()
    e.call(fn, APP, *a)
    return list(screens)


GUI = 0x24040000
e.w32(0x24002E6C, GUI)
ROWS = GUI + 0x1FA58 + 0x218


def select(param):
    e.w32(ROWS + 0x986C, 2)                                    # third row selected
    e.uc.mem_write(ROWS + 2 * 0x328 + 0x40C, struct.pack("<H", param))


select(0xB4)
check("INFO on the Compressor row: knob screen on the global cell", press("master_tools_info", 0x26, 0, 0) == [(0x23, 0x40)])
check("...on the Compressor page, and the FX screen's own cell selection is put back", (e.r8(UI), e.r8(UI + 1), e.r16(APP + 0x28)) == (0, 1, 0x310))
e.uc.mem_write(APP + 0x8CA4, bytes([0x23]))
r = press("master_info_thunk")
check("INFO on the Compressor page: back to Tools", r == [(0x25, 0x310)] and e.r8(UI + 1) == 0, r)
check("...and the stock INFO code is told 'global cell' (row 4: it does nothing); r0 still the app", (e.uc.reg_read(UC_ARM_REG_R3), e.uc.reg_read(UC_ARM_REG_R2), e.uc.reg_read(UC_ARM_REG_R0)) == (0x40, 4, APP))
e.uc.mem_write(APP + 0x8CA4, bytes([0x25]))
select(0x1DB)
check("INFO on the Master FX row: straight to the Master FX page", press("master_tools_info", 0x26, 0, 0) == [(0x23, 0x40)] and (e.r8(UI), e.r8(UI + 1)) == (1, 1))
e.uc.mem_write(APP + 0x8CA4, bytes([0x23]))
r = press("master_info_thunk")
check("INFO on the Master FX page (VHS): back to Tools", r == [(0x25, 0x310)] and e.r8(UI + 1) == 0, r)
settings(comp=3, mfx=2)
e.uc.mem_write(UI, bytes([1, 1]))
r = press("master_info_thunk")
check("INFO on Prism's first page: Tools, then straight on to its second page (knob screen on the global cell)", r == [(0x25, 0x310), (0x23, 0x40)] and (e.r8(UI), e.r8(UI + 1)) == (2, 1), (r, e.r8(UI), e.r8(UI + 1)))
r = press("master_info_thunk")
check("INFO on Prism's second page: back to Tools", r == [(0x25, 0x310)] and e.r8(UI + 1) == 0, r)
settings(comp=3, thresh=-6000, mfx=1, wow=250)
e.uc.mem_write(APP + 0x8CA4, bytes([0x25]))
select(0xBA)
check("INFO on any other Tools row: what stock did (re-show Tools), no knob page", press("master_tools_info", 0x26, 0, 0) == [(0x26, 0x310)] and e.r8(UI + 1) == 0)
e.w32(0x24002E6C, 0)
check("no GUI pointer: stock behaviour", press("master_tools_info", 0x26, 0, 0) == [(0x26, 0x310)])
e.w32(0x24002E6C, GUI)
e.uc.mem_write(APP + 0x8CA4, bytes([0x23]))
r = press("master_info_thunk")
check("INFO on the knob screen for a delay / reverb cell: untouched (stock judges the FX cell id)", r == [] and e.uc.reg_read(UC_ARM_REG_R3) == 0x310 and e.uc.reg_read(UC_ARM_REG_R2) == 1)
check("BACK on a delay / reverb knob screen: the FX screen as before", press("master_back", 0x30, 0, 0) == [(0x30, 0x310)])
select(0xB4)
press("master_tools_info", 0x26, 0, 0)
check("BACK on a master page: Tools", press("master_back", 0x30, 0, 0) == [(0x25, 0x310)] and e.r8(UI + 1) == 0)

# the header of a master page is the global cell's name: cpu_name asks master_title (see test_cpu.py for the name itself)
def title():
    e.call("master_title")
    p = e.uc.reg_read(UC_ARM_REG_R0)
    return e.cstr(p) if p else None


titles = {}
for pg, mfx, want in ((0, 1, "Comp"), (1, 1, "VHS"), (1, 2, "Prism 1"), (2, 2, "Prism 2"), (1, 0, "MFX")):
    settings(mfx=mfx)
    e.uc.mem_write(UI, bytes([pg, 1]))
    titles[want] = title()
e.uc.mem_write(UI, bytes([1, 0]))
check("header titles: Comp, VHS, Prism 1, Prism 2, MFX; none when no master page is up (Tools shows the version)",
      all(k == v for k, v in titles.items()) and title() is None, (titles, title()))

# --- audio
x = sine(0.5, 440)
settings(comp=0, mfx=0)
l, r = block(x)
check("Compressor Off + Master FX Off: buffer untouched, stock compressor not called (as when the stage was skipped)", l == f32(x) and calls == [], calls)
settings(comp=1, mfx=0)
l, r = block(x)
check("Compressor Stock + Master FX Off: only the stock compressor", l == f32(x) and calls == [("stock",)], calls)

settings(comp=0, mfx=1)
l, r = run(8)
ref = sine(0.5, 440, n=8 * N)
err = max(abs(l[i] - ref[i - 2]) for i in range(64, 8 * N))
check(f"VHS with every knob at 0: the signal 2 frames later, 16-bit accurate (max error {err:.6f})", err < 2e-4, err)

settings(comp=1, mfx=1)
block(x)
check("Master FX runs ahead of the stock compressor", calls == [("stock",)])

settings(comp=0, mfx=1, wow=1000, flutter=1000)
l, r = run(190)                                      # ~1 s: two full wow cycles
tail = l[48000 // 2:]
zc = [i for i in range(1, len(tail)) if tail[i - 1] < 0 <= tail[i]]
periods = [b - a for a, b in zip(zc, zc[1:])]
cents = 1200 * math.log2(max(periods) / min(periods)) / 2
check(f"Wow + Flutter at 100 %: pitch swings (about +/-{cents:.0f} cents by zero crossings), level intact", 15 < cents < 150 and 0.3 < rms(tail) < 0.4, (cents, rms(tail)))
check("left and right move together (one tape)", max(abs(a - b) for a, b in zip(l, r)) < 1e-6)

settings(comp=0, mfx=1, sat=1000)
l, r = run(8, amp=1.5)
check(f"Saturate 100 % on a +3.5 dB sine: peak held under full scale ({max(map(abs, l)):.2f})", max(map(abs, l)) < 1.0)
q, _ = run(8, amp=0.02)
check(f"...and quiet material comes up ({20 * math.log10(rms(q[1024:]) / (0.02 / math.sqrt(2))):+.1f} dB)", 3 < 20 * math.log10(rms(q[1024:]) / (0.02 / math.sqrt(2))) < 9)

settings(comp=0, mfx=1, hicut=1000)
hi, _ = run(8, hz=8000)
lo, _ = run(8, hz=200)
check(f"Hi Cut 100 %: 8 kHz down {20 * math.log10(rms(hi[1024:]) / 0.3536):.0f} dB, 200 Hz kept", rms(hi[1024:]) < 0.02 and rms(lo[1024:]) > 0.3)
settings(comp=0, mfx=1, locut=1000)
hi, _ = run(8, hz=8000)
lo, _ = run(16, hz=60)
check(f"Lo Cut 100 %: 60 Hz down {20 * math.log10(rms(lo[2048:]) / 0.3536):.0f} dB, 8 kHz kept", rms(lo[2048:]) < 0.05 and rms(hi[1024:]) > 0.3)

settings(comp=0, mfx=1, noise=1000)
l, r = run(8, amp=0.0)
check(f"Noise 100 % on silence: hiss at {20 * math.log10(rms(l)):.0f} dBFS, different on each side", 0.005 < rms(l) < 0.02 and l != r)
settings(comp=0, mfx=1, noise=0)
l, r = run(4, amp=0.0)
check("Noise 0 on silence: silence", max(map(abs, l)) == 0.0)

settings(comp=0, mfx=1, fail=1000)
l, r = run(750)                                      # 4 s
env = [rms(l[i:i + N]) for i in range(0, len(l), N)]
envr = [rms(r[i:i + N]) for i in range(0, len(r), N)]
dips = sum(1 for a, b in zip(env, env[1:]) if a > 0.3 and b <= 0.3)
check(f"Dropout 100 %: {dips} dropouts in 4 s, level returns to full in between", dips >= 4 and max(env[10:]) > 0.34, (dips, max(env)))
check("some dropouts hit one channel only", any(abs(a - b) > 0.05 for a, b in zip(env, envr)))
settings(comp=0, mfx=1, fail=0)
l, r = run(190)
check("Dropout 0: no dropouts", min(rms(l[i:i + N]) for i in range(N, len(l), N)) > 0.34)

# --- worst case stays bounded, and what it costs
settings(comp=0, mfx=1, wow=1000, flutter=1000, sat=1000, fail=1000, noise=1000, hicut=500, locut=500)
l, r = run(40, amp=2.0)
check(f"everything at max on a +6 dB input: finite and under full scale (peak {max(map(abs, l + r)):.2f})", max(map(abs, l + r)) < 1.1 and all(v == v for v in l))
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
block(sine(0.5, 440))
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions per 256-frame block, {cnt[0] / N:.0f} per frame")

settings(comp=0, mfx=0)
block(x)
check("switching Master FX Off clears its state for the next start", e.r32(GL) == 0)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
