"""The FX OUT page (src/fxout.c): Level + Low Cut on each send effect's wet, and the OUT tab on the knob screen.

Real firmware runs for: the settings lookup (FUN_08093e9c), the settings-list clear / add (FUN_080a4fc2 / FUN_080a5038)
and munchi_list's routing to the OUT page.
Stubbed: stock's knob screen handlers (FUN_080ab900 rebuild, FUN_080ab9b4 child messages: recorded), set_label
(FUN_080a3dec: recorded), the registrars and the store add (recorded).
NOT checked: that the bar's first tab really is the cell beside the header on the glass, that a tap reaches
FUN_080ab9b4 as message 1 with the id at +0xc (read from the disassembly: FUN_080a3808, the bar's +0x30 returns 1),
the knob for a TYPE_DB setting stepping sensibly, how the levels sound, saving with the preset.
"""
import math
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                       # backup SRAM
e.uc.mem_map(0x58024000, 0x1000)                       # RCC / PWR: bkp_enable
e.uc.mem_map(0x30000000, 0x20000)                      # fake objects
STATE = 0x38800A60
STORE, ARR, BL, BR, LIST, SCREEN, MSG, VT = 0x30000000, 0x30000100, 0x30001000, 0x30001400, 0x30002000, 0x30008000, 0x30010000, 0x30011000
N = 128
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def store(level=0, cut=0, extra=()):
    items = [(0x149, level), (0x14A, cut)] + list(extra)
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in items))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", len(items)))


def run(which, l, r=None):
    n = len(l)
    e.uc.mem_write(BL, struct.pack(f"<{n}f", *l))
    if r is not None:
        e.uc.mem_write(BR, struct.pack(f"<{n}f", *r))
    e.w32(STACK, n)                                     # the fifth argument, on the stack
    e.call("fxout_run", which, STORE, BL, BR if r is not None else 0)
    ol = list(struct.unpack(f"<{n}f", e.uc.mem_read(BL, 4 * n)))
    return (ol, list(struct.unpack(f"<{n}f", e.uc.mem_read(BR, 4 * n)))) if r is not None else ol


def tone(f, fs, blocks, which, amp=0.5):
    """steady-state gain of a sine through `blocks` blocks"""
    out, ph = [], 0.0
    for b in range(blocks):
        x = [amp * math.sin(2 * math.pi * f * (b * N + i) / fs) for i in range(N)]
        out += run(which, x, x)[0]
    per = fs / f                                        # RMS over whole periods, at least two and 1024 samples
    k = int(round(max(2, math.ceil(1024 / per)) * per))
    tail = out[-k:]
    return math.sqrt(sum(v * v for v in tail) / len(tail)) / (amp / math.sqrt(2))


def db(x):
    return 20 * math.log10(max(x, 1e-12))


# --- registration + defaults
reg = []
e.stub(0x0808C0D8, lambda: reg.append(("list", e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))], e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: reg.append(("num", e.arg(1), e.arg(2), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.call("fxout_register", 0x30003000)
check("registered: Level 0x149 dB (TYPE_DB 7) -12 .. +12 dB, Low Cut 0x14a Off / 30 .. 600 Hz, own xml names",
      reg == [("num", 0x149, 7, "Level:", -12000, 12000, "fxoutlevel"),
              ("list", 0x14A, "Low Cut:", ["Off", "30 Hz", "60 Hz", "100 Hz", "150 Hz", "200 Hz", "300 Hz", "400 Hz", "600 Hz"], "fxoutlowcut"),
              ("list", 0x148, "Output:", ["Out 1", "Out 2", "Out 3"], "fxoutdest")], reg)
added = []
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("fxout_defaults", STORE)
check("defaults: Level +4 dB (picked in testing), Low Cut Off, Output Out 1 (stock)", added == [(0x149, 4000), (0x14A, 0), (0x148, 0)], added)

# --- the audio
e.uc.mem_write(STATE, bytes(random.Random(7).getrandbits(8) for _ in range(0xA0)))   # backup SRAM: garbage, not zeros
x = [math.sin(i * 0.05) * 0.3 for i in range(N)]
store(0, 0)
l, r = run(0, x, x)
check("from garbage in backup SRAM: Level 0 dB + Off leaves the wet bit-exact", l == run(0, x, x)[0] and all(abs(a - b) < 1e-7 for a, b in zip(l, x)),
      max(abs(a - b) for a, b in zip(l, x)))
check("the state is ours now (magic FXO1)", e.r32(STATE) == 0x46584F31, hex(e.r32(STATE)))
store(4000, 0)
run(0, x, x)                                            # the ramp block
l, r = run(0, x, x)
g = 10 ** (4 / 20)
check("Level +4 dB: x %.4f on both channels (after one ramp block)" % g,
      all(abs(a - g * b) < 2e-4 for a, b in zip(l, x)) and all(abs(a - g * b) < 2e-4 for a, b in zip(r, x)), max(abs(a - g * b) for a, b in zip(l, x)))
store(-12000, 0)
first = run(0, x, x)[0]
check("a Level change ramps across the block (no step): first sample still near +4 dB, last near -12 dB",
      abs(first[0] / x[0] - g) < 0.02 * g if x[0] else abs(first[1] / x[1] - g) < 0.05 and abs(first[-1] / x[-1] - 10 ** (-12 / 20)) < 0.01,
      (first[1] / x[1], first[-1] / x[-1]))
l = run(0, x, x)[0]
check("Level -12 dB: x 0.2512", all(abs(a - 0.25119 * b) < 2e-4 for a, b in zip(l, x)))
for v, want in ((3000, 3), (12000, 12), (-6000, -6), (99999, 12), (-99999, -12)):
    store(v, 0)
    run(0, x, x)
    l = run(0, x, x)[0]
    k = max(range(N), key=lambda i: abs(x[i]))
    check(f"Level setting {v}: {want:+d} dB (clamped to the range)", abs(db(abs(l[k] / x[k])) - want) < 0.01, db(abs(l[k] / x[k])))

for which, fs, name in ((0, 48000.0, "delay, 48 kHz"), (1, 29800.0, "reverb, 29.8 kHz")):
    for cut, fc in ((1, 30), (3, 100), (8, 600)):
        store(0, cut)
        at = tone(fc, fs, 160, which)
        hi = tone(fc * 10, fs, 30, which)
        lo = tone(fc / 4, fs, 400, which)
        check(f"{name}: Low Cut {fc} Hz: -3 dB at {fc} Hz ({db(at):.2f}), flat a decade up ({db(hi):.2f}), "
              f"-24 dB two octaves down ({db(lo):.1f})", abs(db(at) + 3.01) < 0.3 and abs(db(hi)) < 0.1 and abs(db(lo) + 24.1) < 1.0)
store(0, 8)
run(1, [0.5] * N, [0.5] * N)
for _ in range(80):
    l = run(1, [0.5] * N, [0.5] * N)[0]
check("Low Cut removes DC from the reverb's wet", abs(l[-1]) < 1e-3, l[-1])
store(0, 5)
l = run(0, [1.0] + [0.0] * (N - 1))
check("a mono call (no right buffer) filters the left only and does not touch a null pointer", math.isfinite(l[0]) and l[0] != 1.0, l[0])
e.uc.mem_write(STATE + 8, struct.pack("<ff", float("nan"), float("inf")))
store(4000, 0)
l = run(0, x, x)[0]
check("a NaN / inf gain left in the state is not used: the block is finite", all(math.isfinite(v) for v in l))
store(0, 77)
run(0, x, x)                                            # the ramp back from +4 dB
l = run(0, x, x)[0]
check("an out-of-range Low Cut reads as Off", all(abs(a - b) < 1e-6 for a, b in zip(l, x)))

# cost
count = {"n": 0}


def counted():
    count["n"] = 0
    hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
    run(0, x, x)
    e.uc.hook_del(hook)
    return count["n"] / N


store(4000, 8)
run(0, x, x)
cost = counted()
store(0, 0)
run(0, x, x)
idle = counted()
print(f"     cost: {cost:.0f} instructions per stereo frame with Level + Low Cut on (~{cost / 101:.2f} % at 48 kHz), {idle:.1f} at 0 dB + Off")
check("cost with both on stays under 60 instructions a frame (0.6 %)", cost < 60, cost)
check("at 0 dB + Off: under 3 instructions a frame (the settings reads, once a block)", idle < 3, idle)

# --- the page
# stock's rebuild (FUN_080ab900) is stubbed and cannot run munchi_list from inside the stub (no nested emulation),
# so a page build here is the same three steps fx_screen_msg takes, with munchi_list called between them.
calls = []
labels = {}
e.stub(0x080A3DEC, lambda: labels.__setitem__(e.arg(0) - SCREEN, e.cstr(e.arg(1))))
e.stub(0x080AB9B4, lambda: calls.append(("stock_child", e.r16(e.arg(1)))))
e.stub(0x080A50FC)                                      # stock's fill: the knob page starts empty in this harness
GUI = 0x30012000
e.w32(0x24002E6C, GUI)
BUILT = STATE + 6                                       # struct fxout_state: magic, page[2], built


def cell(t):
    """make STORE a cell of type t (its vtable's first method returns t), with the delay's Type + FX OUT settings"""
    code = 0x30013000 + t * 0x10                       # fresh address per type: Unicorn caches code
    e.uc.mem_write(code, bytes([t, 0x20, 0x70, 0x47]))  # movs r0, #t ; bx lr
    e.w32(VT, code | 1)
    e.w32(STORE, VT)
    store(4000, 3, [(0x197, 0), (0x38, 500)])


def listed():
    e.w32(LIST, 0)
    e.call("munchi_list", LIST, STORE)
    return [e.r16(LIST + 4 + 12 * i) for i in range(e.r32(LIST))]


def build(effect=True):
    """a page build stock started (screen opened): before, stock + munchi_list, after"""
    labels.clear()
    e.call("fxout_before_build")
    page = listed() if effect else []
    e.call("fxout_after_build", SCREEN)
    return page


def tap(id_=0x7E01, kind=1, effect=True):
    """a tap; the rebuild it asks for runs munchi_list in stock, here the stub marks the cell as munchi_list would"""
    calls.clear()
    labels.clear()
    built = e.r8(BUILT)
    e.stub(0x080AB900, lambda: (calls.append(("stock_msg", e.r16(e.arg(1)))), e.uc.mem_write(BUILT, bytes([built if effect else 0]))))
    e.uc.mem_write(MSG + 0x40, struct.pack("<H", kind) + bytes(10) + struct.pack("<I", id_) + bytes(16))
    e.call("fx_screen_child", SCREEN, MSG + 0x40)
    return e.uc.reg_read(UC_ARM_REG_R0)


cell(0x26)
build()
check("delay page built: the first tab reads OUT and carries our id", labels.get(0x70) == "OUT" and e.r32(SCREEN + 0x70 + 0x14) == 0x7E01,
      (labels, hex(e.r32(SCREEN + 0x84))))
check("... the header is left to stock (DLY)", 0x3AC not in labels, labels)
e.uc.mem_write(GUI + 0x280 + 0x38, b"\0\0")
rc = tap()
check("tap on OUT: handled (0), stock's child handler not called, one page rebuild through stock", rc == 0 and calls == [("stock_msg", 0x66)], (rc, calls))
check("... the tab reads FX, the header DLY OUT", labels.get(0x70) == "FX" and labels.get(0x3AC) == "DLY OUT", labels)
check("... a full clear + redraw asked (the knob count changes)", bytes(e.uc.mem_read(GUI + 0x280 + 0x38, 2)) == b"\x01\x01")
page = listed()
check("... munchi_list builds the OUT page: Level, Low Cut, Output, with their values",
      page == [0x149, 0x14A, 0x148] and e.r32(LIST + 12) == 4000 and e.r32(LIST + 24) == 3, ([hex(i) for i in page], e.r32(LIST + 12), e.r32(LIST + 24)))   # entry: id at +4, value at +12, 12 bytes each
rc = tap()
check("tap again: back to the knobs (tab OUT, no header change)", rc == 0 and labels.get(0x70) == "OUT" and 0x3AC not in labels, labels)
check("... munchi_list builds the delay's own page again", 0x149 not in listed())
tap()
page = build()
check("THE 3.3.t BUG: a rebuild stock starts on its own right after the tap keeps the OUT page (it fell back to the knobs)",
      labels.get(0x70) == "FX" and labels.get(0x3AC) == "DLY OUT" and page == [0x149, 0x14A, 0x148], (labels, page))
page = build()
check("...and so does any later rebuild", labels.get(0x70) == "FX" and page == [0x149, 0x14A, 0x148], (labels, page))
opened = []
e.stub(0x080AB880, lambda: opened.append(e.arg(0)))
e.uc.mem_write(SCREEN + 0x367C, struct.pack("<H", 0x0300))      # the cell on show
e.uc.mem_write(MSG + 0x80, struct.pack("<IH", 0, 0x0300))       # stock re-opening the SAME cell
e.call("fxout_open", SCREEN, MSG + 0x80)
page = build()
check("stock re-opening the same cell (msg 0x9d, fxout_open): stock's open runs, the OUT page stays",
      opened == [SCREEN] and labels.get(0x70) == "FX" and page == [0x149, 0x14A, 0x148], (opened, labels, page))
e.uc.mem_write(MSG + 0x80, struct.pack("<IH", 0, 0x0301))       # opened on the other effect
e.call("fxout_open", SCREEN, MSG + 0x80)
page = build()
check("opened on ANOTHER cell: that one's knobs, not an OUT page", labels.get(0x70) == "OUT" and 0x149 not in page, (labels, page))
tap()
e.call("fxout_leave")
page = build()
check("BACK off the knob screen (fxout_leave from master_back): the knobs next time", labels.get(0x70) == "OUT" and 0x149 not in page, (labels, page))
calls.clear()
e.stub(0x080AB900, lambda: calls.append(("stock_msg", e.r16(e.arg(1)))))
e.uc.mem_write(MSG, struct.pack("<H", 0x66) + bytes(30))
labels.clear()
e.call("fx_screen_msg", SCREEN, MSG)
check("fx_screen_msg on a stock rebuild (0x66): stock runs once, then the tab is set", calls == [("stock_msg", 0x66)] and 0x70 in labels, (calls, labels))
rc = tap(id_=0)
check("a tap on another (empty) tab goes to stock as before", calls == [("stock_child", 1)], calls)
tap(kind=2)
check("the release (message 2) of our tab goes to stock, which ignores ids other than 3", calls == [("stock_child", 2)], calls)
cell(0x4B)
build()
tap()
check("reverb: OUT page, header RVB OUT", labels.get(0x3AC) == "RVB OUT" and listed() == [0x149, 0x14A, 0x148], labels)
tap()
build(effect=False)                                     # a master / insert page: munchi_list not reached
check("a page that is not an effect's: the tab back to empty, id 0", labels.get(0x70) == "" and e.r32(SCREEN + 0x70 + 0x14) == 0, (labels, e.r32(SCREEN + 0x84)))
tap(effect=False)
check("... and a tap there is stock's", calls == [("stock_child", 1)], calls)
cell(0x30)
build()
check("another FX cell type: the tab stays empty", labels.get(0x70) == "", labels)


img = open("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "rb").read()
# --- the return's output (3.3.x): the engine's "Out 1 += return" goes to the bus the page picks
from unicorn.arm_const import UC_ARM_REG_R8
mixes, buses = [], []
e.stub(0x0804DA6C, lambda: mixes.append((e.arg(0), e.arg(1))))
e.stub(0x0805F37C, lambda: (buses.append((e.arg(0), e.arg(1))), e.uc.reg_write(UC_ARM_REG_R0, 0x31000000 + e.arg(1) * 0x100)), value=None)
APPFX = 0x24020088 + 0x2FC0
FXA = 0x30018000
OUT1, RET, BUSTAB = 0x31000000, 0x31000A00, 0x30019000


def fx_dest(row, v):
    e.uc.mem_write(FXA + row * 0x40, struct.pack("<HHi", 0x148, 0, v))
    e.w32(APPFX + row * 0x18 + 4, FXA + row * 0x40)
    e.uc.mem_write(APPFX + row * 0x18 + 10, struct.pack("<H", 1))


def mix(thunk):
    mixes.clear()
    buses.clear()
    e.uc.reg_write(UC_ARM_REG_R8, BUSTAB)
    e.call(thunk, OUT1, RET)
    return list(mixes), list(buses)


fx_dest(0, 0)
fx_dest(1, 0)
m, b = mix("fxret_dly_thunk")
check("Output Out 1 (stock): the delay's return is mixed into Out 1's bus, no other bus fetched", m == [(OUT1, RET)] and b == [], (m, b))
fx_dest(0, 1)
m, b = mix("fxret_dly_thunk")
check("delay on Out 2: mixed into bus 1, fetched from the bus table in r8", m == [(0x31000100, RET)] and b == [(BUSTAB, 1)], (m, b))
fx_dest(1, 2)
m, b = mix("fxret_rev_thunk")
check("reverb on Out 3: mixed into bus 2 (its own setting, row 1)", m == [(0x31000200, RET)] and b == [(BUSTAB, 2)], (m, b))
fx_dest(1, 9)
m, b = mix("fxret_rev_thunk")
check("an out-of-range setting = Out 1", m == [(OUT1, RET)] and b == [], (m, b))


def bl_target(a):
    h1, h2 = struct.unpack_from("<HH", img, a - 0x08040000)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return a + 4 + (off - (1 << 25) if s else off)


check("both engine mixes go to the thunks (delay @0x08053506, reverb @0x08053516)",
      bl_target(0x08053506) == e.sym["fxret_dly_thunk"] and bl_target(0x08053516) == e.sym["fxret_rev_thunk"])
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
