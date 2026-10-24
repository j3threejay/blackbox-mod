"""Master compressor models under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c), the output-buffer lookup and the stereo accessor, and the
engine's own call site (it calls comp_process through the patched bl).
Stubbed: the stock compressor (recorded), the downstream chain stage (recorded), the list registrar.
NOT checked: how the models sound (all settings are textbook starting points, to be tuned by ear), the Tools screen
showing a list, settings.tml round-trip (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
STORE, ARR = 0x24020088 + 0x8C90, 0x24070000
OBJ, VT, BUFS, L, R, NEXT, NVT = 0x24060000, 0x24061000, 0x24050000, 0x24064000, 0x24066000, 0x24062000, 0x24063000
N = 256
calls = []


def set_model(v):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x9C, 0, 77) + struct.pack("<HHI", 0xB4, 0, v))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 2))


e.stub(0x0804EDDC, lambda: calls.append(("stock", e.arg(0), e.arg(1))), value=1)
e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 3))
e.w32(OBJ + 8, 0)
BUF = BUFS + 3 * 0x14 + 0x150E4


def block(left, right=None, chain=False):
    right = left if right is None else right
    e.uc.mem_write(L, struct.pack(f"<{len(left)}f", *left))
    e.uc.mem_write(R, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R, 0, 1))
    calls.clear()
    e.call("comp_process", OBJ, BUFS)
    return (list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(L, 4 * len(left)))),
            list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(R, 4 * len(right)))))


def sine(amp, hz=200, n=N, start=0):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def db(x):
    return 20 * math.log10(max(x, 1e-9))


def peak(x):
    return max(abs(v) for v in x)


def settle(model, amp, blocks=40, hz=200):
    set_model(model)
    e.uc.mem_write(0x38800400, b"\0" * 8)       # fresh state
    out = []
    for b in range(blocks):
        l, _ = block(sine(amp, hz, start=b * N))
        out += l
    return peak(out[-N * 8:])


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- registration
seen = {}
first_list = {}
e.stub(0x0808C0D8, lambda: first_list or first_list.update(param=e.arg(1), label=e.arg(2), names=e.arg(3), count=e.r32(e.uc.reg_read(UC_ARM_REG_SP)), xml=e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))
e.w32(STACK, 0)
e.w32(STACK + 4, 1000)
e.w32(STACK + 8, 0x080CC3F4)
nums = []
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.arg(2), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.call("comp_register", 0x24001000, 0xB4, 4, 0x080CC3E8)
seen = first_list
check("Comp Thresh registered too: param 0x1d0, dB type, -24..+12 dB, xml 'compthresh'", nums[0] == (0x1D0, 7, "Comp Thresh:", -24000, 12000, "compthresh"), nums)
names = [e.cstr(e.r32(seen["names"] + 4 * i)) for i in range(seen["count"])]
check("Compressor registered as a list: Off, Stock, Glue, Punch, Opto, Squash, Limit, Smash (same param, label, xml name)", names == ["Off", "Stock", "Glue", "Punch", "Opto", "Squash", "Limit", "Smash"] and (seen["param"], seen["label"], seen["xml"]) == (0xB4, 0x080CC3E8, 0x080CC3F4), (names, seen))

# --- Stock stays stock
set_model(1)
x = sine(0.5)
l, _ = block(x)
check("Stock (saved value 1, what existing settings hold): runs the stock compressor, buffer untouched by the patch", calls == [("stock", OBJ, BUFS)] and l == [struct.unpack("<f", struct.pack("<f", v))[0] for v in x], calls)
set_model(9)
block(x)
check("a value past the list: stock compressor", calls[0][0] == "stock")

# --- the engine's own call site reaches comp_process
set_model(1)
calls.clear()
e.uc.reg_write(UC_ARM_REG_SP, STACK)
check("the patched engine call goes to comp_process", e.r32(0x08053CA0) != 0 and e.sym["comp_process"] != 0)

# --- static curves
for model, name, ratio, thr in ((2, "Glue", 2, -18), (3, "Punch", 4, -20), (4, "Opto", 3, -22)):
    lo, hi = settle(model, 10 ** ((thr + 6) / 20) * 1.4142), settle(model, 10 ** ((thr + 15) / 20) * 1.4142)
    slope = (db(hi) - db(lo)) / 9
    check(f"{name}: above threshold and knee, 9 dB more in gives {db(hi) - db(lo):.1f} dB more out (about 1/{ratio})", abs(slope - 1 / ratio) < 0.12, slope)
quiet_in = 10 ** (-40 / 20)
for model, name, mk in ((2, "Glue", 3), (3, "Punch", 4), (4, "Opto", 4)):
    out = settle(model, quiet_in)
    check(f"{name}: far below threshold, only the make-up gain ({db(out) - db(quiet_in):+.1f} dB, set {mk:+d})", abs(db(out) - db(quiet_in) - mk) < 0.6, db(out) - db(quiet_in))

# --- Squash: parallel
loud = settle(5, 0.5)
check(f"Squash: heavy (0.5 in -> {loud:.2f} out) but the dry half keeps the shape", 0.2 < loud < 0.97)
quiet = settle(5, 0.01)
check(f"Squash: quiet material comes up a lot ({db(quiet) - db(0.01):+.1f} dB)", db(quiet) - db(0.01) > 5)

# --- Limit
set_model(6)
e.uc.mem_write(0x38800400, b"\0" * 8)
worst = 0.0
for b in range(40):
    sig = [(0.9 if (i + b * N) % 4800 < 30 else 0.3) * math.sin(i * 0.07) for i in range(N)]
    l, r = block(sig)
    worst = max(worst, peak(l), peak(r))
check(f"Limit: hot material with sudden peaks never exceeds the -0.3 dBFS ceiling (worst {db(worst):.2f} dBFS)", worst <= 0.9662)
q = settle(6, 0.1)
check(f"Limit: quiet material gets the +6 dB push ({db(q) - db(0.1):+.1f} dB)", abs(db(q) - db(0.1) - 6) < 0.6)
set_model(6)
e.uc.mem_write(0x38800400, b"\0" * 8)
imp = [0.0] * N
imp[10] = 0.3
l, _ = block(imp)
check("Limit: 1.5 ms look-ahead (72 frames) delays the signal", abs(l[10 + 72] - 0.3 * 1.9953) < 0.01 and abs(l[10]) < 1e-6, (l[10], l[82]))

# --- Punch lets the attack through
set_model(3)
e.uc.mem_write(0x38800400, b"\0" * 8)
for b in range(10):
    block([0.0] * N)
hit = []
for b in range(4):
    l, _ = block(sine(0.7, start=b * N))
    hit += l
check(f"Punch: first 2 ms of a hit {db(peak(hit[:96])):.1f} dB vs {db(peak(hit[-240:])):.1f} dB once clamped (transient kept)", peak(hit[:96]) > peak(hit[-240:]) * 1.3)

# --- Opto two-stage release
set_model(4)
e.uc.mem_write(0x38800400, b"\0" * 8)
for b in range(60):
    block(sine(0.8, start=b * N))
deep = e.uc.mem_read(0x38800408, 4)
gr0 = struct.unpack("<f", deep)[0]
trace = []
for b in range(200):
    block([0.0] * N)
    trace.append(struct.unpack("<f", e.uc.mem_read(0x38800408, 4))[0])
t_half = next((i for i, v in enumerate(trace) if v > gr0 / 2), len(trace)) * 256 / 48
t_90 = next((i for i, v in enumerate(trace) if v > gr0 * 0.1), len(trace)) * 256 / 48
check(f"Opto: from {gr0:.1f} dB, half recovered in {t_half:.0f} ms, 90% in {t_90:.0f} ms (fast, then slow)", t_half < 120 and t_90 > 3 * t_half, (t_half, t_90))

# --- housekeeping
set_model(2)
e.uc.mem_write(0x38800400, b"\0" * 8)
l, r = block(sine(0.5), [0.0] * N)
check("stereo-linked: a loud left channel turns the right down too (no image shift)", peak(r) < 1e-6 and peak(l) > 0)
e.w32(OBJ + 8, NEXT)
e.w32(NEXT, NVT)
e.w32(NVT + 0xC, 0x24068001)
e.uc.mem_write(0x24068000, bytes.fromhex("0120 7047"))   # movs r0,#1; bx lr
got = []
e.stubs[0x24068000] = lambda: (got.append((e.arg(0), e.arg(1))), e.ret(1))
block(sine(0.5))
check("the next stage of the output chain still gets the buffers", got == [(NEXT, BUFS)], got)
e.w32(OBJ + 8, 0)
set_model(3)
e.uc.mem_write(0x38800400 + 8, struct.pack("<f", -30.0))
block(sine(0.01))
check("switching model resets the state (no leftover gain reduction)", struct.unpack("<f", e.uc.mem_read(0x38800408, 4))[0] > -1.0)
nan = False
set_model(6)
for b in range(5):
    l, _ = block([0.0] * N)
    nan |= any(v != v for v in l)
check("silence in: silence out, no NaN", not nan and peak(l) == 0.0)

# --- Comp Thresh
def set_model_thresh(v, mdb):
    e.uc.mem_write(ARR, struct.pack("<HHI", 0x9C, 0, 77) + struct.pack("<HHI", 0xB4, 0, v) + struct.pack("<HHi", 0x1D0, 0, mdb))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", 3))


def settle_t(model, amp, mdb, blocks=40):
    set_model_thresh(model, mdb)
    e.uc.mem_write(0x38800400, b"\0" * 8)
    out = []
    for b in range(blocks):
        l, _ = block(sine(amp, start=b * N))
        out += l
    return peak(out[-N * 8:])


amp = 10 ** (-12 / 20) * 1.4142                 # -12 dB RMS: 6 dB over Glue's default threshold
g0, gm, gp = settle_t(2, amp, 0), settle_t(2, amp, -6000), settle_t(2, amp, 6000)
check(f"Glue, Comp Thresh -6 dB squeezes harder ({db(gm) - db(g0):+.1f} dB), +6 dB leaves it alone ({db(gp) - db(g0):+.1f} dB)", db(gm) < db(g0) - 1 and db(gp) > db(g0) + 1, (g0, gm, gp))
l0, lm = settle_t(6, 0.05, 0), settle_t(6, 0.05, -6000)
check(f"Limit, Comp Thresh -6 dB pushes quiet material 6 dB harder ({db(lm) - db(l0):+.1f} dB)", abs(db(lm) - db(l0) - 6) < 0.6, (l0, lm))
w = settle_t(6, 0.9, -24000)
check(f"Limit, Comp Thresh at -24 dB on a hot signal: still never over the ceiling ({db(w):.2f} dBFS)", w <= 0.9662)

# --- defaults, Tools page, label
added = []
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("comp_defaults", 0x24072000, 0xB4, 1)
check("settings defaults: Compressor 1 (Stock) as before, then Comp Thresh 0, Smash Depth 50 %, Time 50 %", added[:4] == [(0xB4, 1), (0x1D0, 0), (0x1EA, 500), (0x1EB, 500)], added)
page = [e.r16(0x080EED18 + 2 * k) for k in range(14)]
check("Tools Main page: Headphone, Master FX, Compressor (signal order; Comp Thresh is on the knob page), Out 1-3, Brightness, Metronome, Metro Out, Metro Gain, SD Mode, Theme (Groove is on Clock)", page[:13] == [0xBA, 0x1DB, 0xB4, 0xBB, 0xBC, 0xBD, 0x7F, 0xCD, 0xF6, 0xF7, 0x19B, 0x144, 0], [hex(v) for v in page])
check("pad Overdrive label reads 'Saturation:' (xml name unchanged)", e.cstr(e.r32(0x0808D878)) == "Saturation:" and e.cstr(0x080CC620) == "overdrive", e.cstr(e.r32(0x0808D878)))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
