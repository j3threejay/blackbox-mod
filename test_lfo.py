"""LFO 2 / LFO 3 per pad (src/lfo.c, routing in src/envmod.c, triggers in src/duck_thunk.S) under Unicorn.

Real firmware runs for the settings lookup, the pad's slot list (FUN_08056810), the voice attach (FUN_0805623c) and
the parameter read. Stubbed: the registrars, the store add, the tab-bar switch, the label setter, the voice start.
NOT checked: that the pad screen shows the LFO+ tab and its eight knobs, that a pad store of 96 entries boots, preset
save / load of the eight settings and of the lfo2 / lfo3 routings, how the modulation sounds.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import BASE, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
img = open(IMG, "rb").read()
stock = open("firmware/BLACKBOX-3.1.9.bin", "rb").read()

ENGINE, PAD, PARAM, CMD, VT = 0x24040000, 0x24030000, 0x24031000, 0x24032000, 0x24033000
STATE = 0x2405FF70
VALUE_OFF = [0xD604, 0xD668, 0xD6CC, 0xD730]
BLOCK = 64

import math
from unicorn.arm_const import UC_ARM_REG_S0

fails = 0


def words(buf, addr, n, fmt):
    size = struct.calcsize(fmt)
    return list(struct.unpack(f"<{n}{fmt}", buf[addr - BASE:addr - BASE + n * size]))


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def f32(a):
    return struct.unpack("<f", e.uc.mem_read(a, 4))[0]


e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
BLOCKMEM, LFOS = 0xC0000000, 0xC0000000 + 0x56800
APP_PADS = 0x24020088 + 0x1840
ARR = 0x24072000

# ---- settings
lists, nums, added = [], [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.call("lfo_register", 0x24001000)
WAVES = ["Saw", "RevSaw", "Tri", "Tri+", "Sine", "Sine+", "Square", "Sqr+", "Random", "ExpDn", "ExpUp", "Drift"]
RATES = ["32 bar", "16 bar", "8 bar", "4 bar", "2 bar", "1 bar", "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T", "1/16", "1/16T", "1/32"]
check("registered per LFO: Wave (12), Rate (15 synced lengths), Trig (Free, Retrig, Once); ids 0x1a9.. and 0x1ad..",
      [(l[0], l[1], l[2]) for l in lists] == [(0x1A9, "2 Wave:", WAVES), (0x1AA, "2 Rate:", RATES), (0x1AB, "2 Trig:", ["Free", "Retrig", "Once"]),
                                              (0x1AD, "3 Wave:", WAVES), (0x1AE, "3 Rate:", RATES), (0x1AF, "3 Trig:", ["Free", "Retrig", "Once"])], lists)
check("...and Offset 0..100 %", [(n[0], n[1], n[2], n[3]) for n in nums] == [(0x1AC, "2 Offset:", 0, 1000), (0x1B0, "3 Offset:", 0, 1000)], nums)
check(f"the whole image fits flash bank 1: {len(img)} bytes of at most {0x08100000 - BASE} (the installer refuses a longer one)", len(img) <= 0x08100000 - BASE, len(img))
check("eight distinct xml names", len({l[3] for l in lists} | {n[4] for n in nums}) == 8)
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("lfo_defaults", 0x24073000, 0xDC, 0)
check("pad defaults: stock's last entry, then LFO 2 = Sine, 1 bar, Free; LFO 3 = Random, 1/4, Retrig",
      added[:9] == [(0xDC, 0), (0x1A9, 4), (0x1AA, 5), (0x1AB, 0), (0x1AC, 0), (0x1AD, 8), (0x1AE, 8), (0x1AF, 1), (0x1B0, 0)], added)
check("...then the pad's insert: Off, Pebble, Electra, the six shared knobs, the Gate's five, Input Off, then the Clip "
      "Window's Region Auto, Slip 0, Loop Len Off and Fit Off (clipwin.c)",
      added[9:] == [(0x1B6, 0), (0x1B7, 0), (0x1B8, 0), (0x1B9, 330), (0x1BA, 750), (0x1BB, 500), (0x1BC, 350), (0x1BD, 250), (0x1BE, 500),
                    (0x1C2, 800), (0x1C3, 0), (0x1C4, 0), (0x1C5, 200), (0x1C6, 0), (0x1C7, 0), (0x1C8, 0), (0x1C9, 0), (0x1CA, 0), (0x1CB, 0)], added[9:])
check("a pad's settings store holds 96 entries (stock 64, of which 59 used; ours make 86): both places that size one",
      img[0x08093F26 - BASE:0x08093F28 - BASE] == bytes.fromhex("6021") and img[0x080949F0 - BASE:0x080949F2 - BASE] == bytes.fromhex("6021"))
check("page 3 of the Sample and Multisample pad pages lists the eight knobs",
      words(img, 0x080EFCF0, 9, "H") == list(range(0x1A9, 0x1B1)) + [0] and words(img, 0x080EFB88, 9, "H") == list(range(0x1A9, 0x1B1)) + [0])
check("...and so does page 3 of the Clip and Slicer pad pages", words(img, 0x080EF948 + 3 * 0x48, 9, "H") == list(range(0x1A9, 0x1B1)) + [0] and words(img, 0x080EF7E0 + 3 * 0x48, 9, "H") == list(range(0x1A9, 0x1B1)) + [0])
check("the second copy of the pad pages (cells of class type 0x4c) has them too, and its defaults are hooked",
      all(words(img, b + 3 * 0x48, 9, "H") == list(range(0x1A9, 0x1B1)) + [0] for b in (0x080EF3A8, 0x080EF240, 0x080EF0D8))
      and img[0x080943B4 - BASE:0x080943B8 - BASE] != stock[0x080943B4 - BASE:0x080943B8 - BASE] and img[0x0809423C - BASE:0x08094240 - BASE] != stock[0x0809423C - BASE:0x08094240 - BASE])
check("Granular pads' page 3 is still their own six grain knobs", words(img, 0x080EF510 + 3 * 0x48, 7, "H") == words(stock, 0x080EF510 + 3 * 0x48, 7, "H") and words(stock, 0x080EF510 + 3 * 0x48, 7, "H")[5] != 0)

# ---- the tab
VIEW = 0x24048000
tabs = []
e.stub(0x080B8724, lambda: tabs.append(("bar", e.arg(1))))
e.stub(0x080A3DEC, lambda: tabs.append(("label", e.arg(0) - VIEW, e.cstr(e.arg(1)))))


def pick(bar):
    tabs.clear()
    e.call("lfo_tabs", VIEW, bar)
    return list(tabs)


check("Sample, Clip and Slicer pads (bar 0): get the five-tab bar, fourth tab labelled LFO+", pick(0) == [("label", 0x106D8, "LFO+"), ("bar", 1)], pick(0))
check("Multisample pad (bar 2): the same", pick(2) == [("label", 0x106D8, "LFO+"), ("bar", 1)], pick(2))
check("Granular pad (bar 1): its five-tab bar, the fourth tab says Gran again", pick(1) == [("label", 0x106D8, "Gran"), ("bar", 1)], pick(1))
check("both stock calls that pick the bar go through lfo_tabs", img[0x080B8844 - BASE:0x080B8848 - BASE] != stock[0x080B8844 - BASE:0x080B8848 - BASE] and img[0x080B8BCC - BASE:0x080B8BD0 - BASE] != stock[0x080B8BCC - BASE:0x080B8BD0 - BASE])

# ---- triggers: the voice-start thunk sets the pad's bit
def voice_start(sym, original, pad_id):
    e.w32(PAD + 0x18, pad_id)
    seen = {}

    def rec():
        sp = e.uc.reg_read(UC_ARM_REG_SP)
        seen.update(r=[e.arg(i) for i in range(4)], sp=sp, stack=e.r32(sp), s0=struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0])
    e.stub(original, rec, value=0x77)
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 0.625))[0])
    e.w32(0x2407F000, 0xCAFE)
    e.call(sym, PAD, 0xA1, 0xA2, 0xA3)
    return seen


e.uc.mem_write(STATE, bytes(64))
s = voice_start("duck_voice_start_a", 0x08058548, 0x0201)          # row 2, col 1 = pad 10
check("voice start on pad 10 (row 2, col 1): bit 9 of the trigger mask, arguments and stack passed on untouched, no duck trigger",
      e.r16(STATE + 14) == 1 << 9 and e.r8(STATE + 8) == 0 and s["r"] == [PAD, 0xA1, 0xA2, 0xA3] and s["sp"] == 0x2407F000 and s["stack"] == 0xCAFE and s["s0"] == 0.625, (hex(e.r16(STATE + 14)), s))
voice_start("duck_voice_start_b", 0x08065908, 0)
check("voice start on pad 1 (class B thunk): bit 0 added, and the duck trigger as before", e.r16(STATE + 14) == (1 << 9) | 1 and e.r8(STATE + 8) == 1, hex(e.r16(STATE + 14)))
voice_start("duck_voice_start_a", 0x08058548, 0x10303)
check("bank bits are ignored: row 3, col 3 = pad 16", e.r16(STATE + 14) == (1 << 9) | 1 | (1 << 15), hex(e.r16(STATE + 14)))

# ---- no memory: everything stays out of the way
e.uc.mem_write(0x38800F70, bytes(8))
e.call("lfo_tick", 1000)
check("no memory block (boot hook has not run): the tick does nothing but clear the triggers", e.r16(STATE + 14) == 0)
PAD2, VOICE, CMD2 = 0x24068000, 0x2406A000, 0x2406D000
e.uc.mem_write(PAD2, bytes(0x800))
e.uc.mem_write(VOICE, bytes(0x800))
e.w32(PAD2 + 0x18, 0x0201)


def slot_cmd(target, slot, source, amount):
    e.uc.mem_write(CMD2, struct.pack("<BBHIIIIHh", 0x3A, 0, 0, 0, 0, target, slot, source, amount))
    e.call("env_mod_setup", PAD2, CMD2)


def entries():
    n = e.r32(PAD2 + 0x54C)
    return [(round(f32(PAD2 + 0x4EC + 12 * i), 3), e.r16(PAD2 + 0x4F0 + 12 * i), e.r16(PAD2 + 0x4F2 + 12 * i), e.r8(PAD2 + 0x4F4 + 12 * i)) for i in range(n)]


slot_cmd(0x5C, 2, 5, 500)
slot_cmd(4, 1, 6, -250)
slot_cmd(10, 3, 1, 250)
check("LFO2 / LFO3 on slots: listed by the pad with sources 5 / 6, beside an ENV slot", entries() == [(0.5, 0x5C, 5, 2), (-0.25, 4, 6, 1), (0.25, 10, 1, 3)], entries())
e.uc.mem_write(BASEV := 0x2406C000, bytes(0x100))
e.uc.mem_write(BASEV + 4, struct.pack("<f", 0.5))
e.w32(PAD2 + 0x28C, BASEV)
e.uc.mem_write(PAD2 + 0x28C + 4, struct.pack("<f", 1.0))
e.uc.mem_write(PAD2 + 0x28C + 0x28, struct.pack("<ff", 0.0, 1.0))


def has_source(param, src):
    return src in [e.r32(param + 4 * k) & 0xFFFFFFFF for k in range(13)]


e.call("env_mod_attach", PAD2, VOICE)
check("without memory a voice gets no LFO2 input (and nothing crashes)", not any(has_source(VOICE + 0x288, LFOS + 0x18 + 9 * 2 * 28 + k) for k in range(0, 56, 4)))

# ---- with memory
e.w32(0x38800F70, BLOCKMEM)
e.w32(0x38800F74, BLOCKMEM ^ 0x5052534D)
L = lambda pad, k: LFOS + 0x18 + (pad * 2 + k) * 28          # struct lfo is 28 bytes; state header 24
e.call("env_mod_attach", PAD2, VOICE)
check("with memory: the voice's parameter 0x5c reads pad 10's LFO 2 (state + header + 9 * 2 lfos)", has_source(VOICE + 0x288, L(9, 0)), [hex(e.r32(VOICE + 0x288 + 4 * k) & 0xFFFFFFFF) for k in range(13)])
check("...the state is started (magic LFO2) and pad 10's LFO 2 and LFO 3 are marked in use", e.r32(LFOS) == 0x4C464F32 and e.r32(LFOS + 8) == 3 << 18, hex(e.r32(LFOS + 8)))


def pad_settings(pad, **kw):
    ids = {"wave2": 0x1A9, "rate2": 0x1AA, "trig2": 0x1AB, "off2": 0x1AC, "wave3": 0x1AD, "rate3": 0x1AE, "trig3": 0x1AF, "off3": 0x1B0}
    vals = dict(wave2=4, rate2=8, trig2=0, off2=0, wave3=8, rate3=8, trig3=1, off3=0)
    vals.update(kw)
    arr = ARR + 0x100 + pad * 0x80
    e.uc.mem_write(arr, b"".join(struct.pack("<HHI", ids[k], 0, v) for k, v in vals.items()))
    store = APP_PADS + (pad >> 2) * 0xF0 + (pad & 3) * 0x30
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", 8))


now = [10_000_000]


def tick(frames=256, n=1):
    for _ in range(n):
        now[0] += frames
        e.call("lfo_tick", now[0])


def val(pad, k):
    return f32(L(pad, k) + 4)


def restart(**kw):
    """New settings for pad 10, picked up within 16 ticks, then a note to restart retriggered LFOs."""
    pad_settings(9, **kw)
    tick(1, 16)




def tempo(bpm):
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", bpm))[0])
    e.call("lfo_tempo")


tempo(120.0)
pad_settings(9)
tick(1, 16)                                   # all 16 pads' settings read once
e.w32(L(9, 0) + 8, 0)                         # LFO 2's phase back to the start
tick(1)
q = 6000                                      # frames in a quarter of a 1/4-note cycle at 120 BPM
seen = [val(9, 0)]
for _ in range(4):
    tick(250, 24)
    seen.append(val(9, 0))
check(f"Sine, Rate 1/4 at 120 BPM: 0, +1, 0, -1, 0 at the quarter points ({', '.join(f'{v:+.2f}' for v in seen)})",
      all(abs(a - b) < 0.02 for a, b in zip(seen, (0, 1, 0, -1, 0))), seen)
tempo(60.0)
e.w32(L(9, 0) + 8, 0)
tick(1)
tick(250, 48)
check(f"at 60 BPM the same cycle takes twice as long (quarter point after 12000 frames: {val(9, 0):+.2f})", abs(val(9, 0) - 1) < 0.02, val(9, 0))
tempo(120.0)

voice = e.sym["duck_voice_start_a"]
restart(wave2=0, rate2=8, trig2=1)            # Saw, Retrig
tick(250, 40)
before = val(9, 0)
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)
check(f"Retrig: a note on the pad restarts the cycle ({before:+.2f} -> {val(9, 0):+.2f})", val(9, 0) < -0.98 and before > -0.9, (before, val(9, 0)))
voice_start("duck_voice_start_a", 0x08058548, 0x0000)
tick(250, 10)
moved = val(9, 0)
check("...a note on another pad does not", moved > -0.8, moved)
restart(wave2=0, rate2=8, trig2=0)            # Free
tick(250, 8)
before = val(9, 0)
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)
check("Free: notes do not restart it", abs(val(9, 0) - before) < 0.01, (before, val(9, 0)))

restart(wave2=0, rate2=8, trig2=2)            # Once
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)
start = val(9, 0)
tick(250, 48)
half = val(9, 0)
tick(250, 100)
end1 = val(9, 0)
tick(250, 100)
check(f"Once: runs one cycle from the note ({start:+.2f} .. {half:+.2f} ..) and holds its end ({end1:+.2f}, later {val(9, 0):+.2f})",
      start < -0.98 and abs(half) < 0.05 and end1 > 0.98 and val(9, 0) == end1, (start, half, end1, val(9, 0)))

restart(wave2=0, rate2=8, trig2=1, off2=250)  # Offset 25 %
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)
check(f"Offset 25 %: a retriggered Saw starts a quarter of the way up ({val(9, 0):+.2f})", abs(val(9, 0) + 0.5) < 0.02, val(9, 0))

ranges = {}
for w, name in enumerate(WAVES):
    restart(wave2=w, rate2=10, trig2=0, off2=0)
    got = []
    for _ in range(400):
        tick(250)
        got.append(val(9, 0))
    ranges[name] = (min(got), max(got), len({round(g, 3) for g in got}))
uni = ("Tri+", "Sine+", "Sqr+", "ExpDn", "ExpUp")
check("every wave stays inside its range: -1..1, and 0..1 for Tri+ / Sine+ / Sqr+ / ExpDn / ExpUp",
      all((lo >= (-0.001 if n in uni else -1.001)) and hi <= 1.001 and hi - lo > (0.5 if n in ("Random", "Drift") else 0.9) for n, (lo, hi, _) in ranges.items()),
      {n: (round(lo, 2), round(hi, 2)) for n, (lo, hi, _) in ranges.items()})
check(f"Random steps (few values: {ranges['Random'][2]}), Drift glides (many: {ranges['Drift'][2]})", ranges["Random"][2] < 60 and ranges["Drift"][2] > 200, ranges)
restart(wave2=9, rate2=8, trig2=1)
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)
a = val(9, 0)
tick(250, 12)
b = val(9, 0)
tick(250, 60)
check(f"ExpDn: starts at 1, most of the fall in the first eighth of the cycle ({a:.2f}, {b:.2f}, {val(9, 0):.2f})", a > 0.98 and b < 0.6 and val(9, 0) < 0.05, (a, b, val(9, 0)))

restart(wave2=4, rate2=0, trig2=0)
e.w32(L(9, 0) + 8, 0)
tick(1)
tick(256, 3000)                               # 16 s
check(f"Rate 32 bar: after 16 s (a quarter of the 64 s cycle at 120 BPM) the sine is at its top ({val(9, 0):+.3f})", abs(val(9, 0) - 1.0) < 0.01, val(9, 0))
check("pads with nothing routed are not worked on", f32(L(3, 0) + 4) == 0.0 and e.r32(L(3, 0) + 8) == 0)

# ---- the routing, end to end
restart(wave2=7, rate2=8, trig2=1)            # Sqr+: 1 for the first half, 0 for the second
voice_start("duck_voice_start_a", 0x08058548, 0x0201)
tick(1)


def voice_param():
    e.call(0x0806FB30, VOICE + 0x288)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0]


hi = voice_param()
tick(250, 60)
lo = voice_param()
check(f"parameter with base 0.5 and LFO2 at +50 %: {hi:.2f} while the square is high, {lo:.2f} when it is low", abs(hi - 1.0) < 1e-4 and abs(lo - 0.5) < 1e-4, (hi, lo))

# ---- Clip / Slicer pads (engine class B): two layers, each with its own copy of a parameter
PADB, CMDB = 0x24064000, 0x2406E000
e.uc.mem_write(PADB, bytes(0x1000))
e.w32(PADB + 0x18, 0x0302)                    # row 3, col 2 = pad 15
stock_b = []
e.stub(0x08067018, lambda: stock_b.append(e.r16(e.arg(1) + 0x14)))


def slot_b(target, slot, source, amount):
    stock_b.clear()
    e.uc.mem_write(CMDB, struct.pack("<BBHIIIIHh", 0x3A, 0, 0, 0, 0, target, slot, source, amount))
    e.call("env_mod_setup_b", PADB, CMDB)


def layer_param(off, layer, base=0.5):
    """Give the layer's parameter object a base value and limits 0..1, as stock's copy would."""
    p = PADB + off + layer * 0x410
    b = 0x2406F000 + layer * 0x40 + off // 4
    e.uc.mem_write(b + 4, struct.pack("<f", base))
    e.w32(p, b)
    e.uc.mem_write(p + 4, struct.pack("<f", 1.0))
    e.uc.mem_write(p + 0x28, struct.pack("<ff", 0.0, 1.0))
    return p


def read_param(p):
    e.call(0x0806FB30, p)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0]


e.uc.mem_write(0x2406F000, bytes(0x1000))
flt = [layer_param(0x2F4, 0), layer_param(0x2F4, 1)]
slot_b(0x5C, 1, 0xD, 300)
check("class B: a stock source (velocity) still goes to stock", stock_b == [0xD], stock_b)
slot_b(0x5C, 1, 1, 400)
check("class B, ENV on Filter: both layers' parameters read their own layer's envelope (pad + 0x4dc, pad + 0x8ec); stock not called",
      has_source(flt[0], PADB + 0x4DC) and has_source(flt[1], PADB + 0x8EC) and not stock_b, stock_b)
e.uc.mem_write(PADB + 0x4E0, struct.pack("<f", 1.0))      # layer 1's envelope fully open, layer 2's closed
e.uc.mem_write(PADB + 0x8F0, struct.pack("<f", 0.0))
check(f"...layer 1 reads 0.5 + 0.4 x 1 = {read_param(flt[0]):.2f}, layer 2 (envelope at 0) stays {read_param(flt[1]):.2f}", abs(read_param(flt[0]) - 0.9) < 1e-5 and abs(read_param(flt[1]) - 0.5) < 1e-5)
slot_b(0x5C, 2, 5, -200)
check("class B, LFO2 on a second slot of the same parameter: both layers read pad 15's LFO 2, which is marked in use",
      has_source(flt[0], L(14, 0)) and has_source(flt[1], L(14, 0)) and e.r32(LFOS + 8) >> 28 & 1 == 1, hex(e.r32(LFOS + 8)))
e.uc.mem_write(L(14, 0) + 4, struct.pack("<f", 1.0))
check(f"...ENV +40 % and LFO2 -20 % add up: {read_param(flt[0]):.2f}", abs(read_param(flt[0]) - 0.7) < 1e-5, read_param(flt[0]))
pit = [layer_param(0x26C, 0), layer_param(0x26C, 1)]
slot_b(0x62, 1, 6, 100)
e.uc.mem_write(L(14, 1) + 4, struct.pack("<f", 1.0))
check(f"class B, LFO3 on Pitch counts double, as stock's LFO does there ({read_param(pit[0]):.2f})", abs(read_param(pit[0]) - 0.7) < 1e-5, read_param(pit[0]))
slot_b(0xA2, 1, 5, 500)
check("class B: a target these pads cannot modulate is left alone", not stock_b)
check("the class B setup call is hooked", img[0x080685C4 - BASE:0x080685C8 - BASE] != stock[0x080685C4 - BASE:0x080685C8 - BASE])

cnt = [0]
from unicorn import UC_HOOK_CODE
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a_, s_, u: cnt.__setitem__(0, cnt[0] + 1))
tick(256)
e.uc.hook_del(h)
print(f"     cost: {cnt[0]} instructions per engine tick with one pad's two LFOs in use")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
