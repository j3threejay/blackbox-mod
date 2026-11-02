"""Pad-1 ducking under Unicorn.

Real firmware runs for: the engine's mod-slot dispatcher (FUN_080519e0), global-source attach (FUN_0804e890),
parameter attach (FUN_0806fcd4) and parameter read (FUN_0806fb30).
Stubbed: the engine's per-block process and the two voice-start functions (recorded), a fake pad module's vtable.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import BASE, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
img = open(IMG, "rb").read()
stock = open("firmware/BLACKBOX-3.1.9.bin", "rb").read()

ENGINE, PAD, PARAM, CMD, VT = 0x24040000, 0x24030000, 0x24031000, 0x24032000, 0x24033000
STATE = 0x2405FF70
VALUE_OFF = [0xD604, 0xD668, 0xD6CC, 0xD730]
BLOCK = 64

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def f32(a):
    return struct.unpack("<f", e.uc.mem_read(a, 4))[0]


def values():
    return [f32(ENGINE + o) for o in VALUE_OFF]


# ---------------------------------------------------------------- Source list tables
names, codes = e.sym["duck_source_names"], e.sym["duck_source_codes"]


def words(buf, addr, n, fmt):
    size = struct.calcsize(fmt)
    return list(struct.unpack(f"<{n}{fmt}", buf[addr - BASE:addr - BASE + n * size]))


sn, sc = words(stock, 0x080ECD0C, 8, "I"), words(stock, 0x080ECCFC, 8, "H")
check("the stock name pointers are kept (KEY after VEL, LFO2 / LFO3 after LFO)", words(img, names, 2, "I") + [words(img, names, 4, "I")[3]] + words(img, names, 11, "I")[6:] == sn)
check("the stock codes are kept, key = 0xe after velocity, lfo2 = 5 and lfo3 = 6 after the LFO's 4", words(img, codes, 11, "H") == sc[:2] + [0xE] + sc[2:3] + [5, 6] + sc[3:])
e.uc.mem_write(0x08000000, b"")
labels = [e.cstr(p) for p in words(img, names, 16, "I")]
check("list reads none VEL KEY LFO LFO2 LFO3 PTCH MODW MVOL MPAN CC ENV EXP1 EXP2 PUMP LINR",
      labels == ["none", "VEL", "KEY", "LFO", "LFO2", "LFO3", "PTCH", "MODW", "MVOL", "MPAN", "CC", "ENV", "EXP1", "EXP2", "PUMP", "LINR"], labels)
check("duck codes are mod4, mod3, mod2, mod1", words(img, codes, 16, "H")[12:] == [0x12, 0x11, 0x10, 0xF])
check("the three list-length patches say 16", img[0x0808CB3E - BASE] == 0x10 and img[0x080B67CC - BASE] == 0x10 and img[0x080B7994 - BASE] == 0x10)

# ---------------------------------------------------------------- block hook + envelope
e.uc.mem_map(0x38800000, 0x1000)                         # backup SRAM + its clock: lfo.c looks for its memory there
e.uc.mem_map(0x58024000, 0x1000)                         # (none here: the LFOs stay idle; test_lfo.py covers them)
e.uc.mem_write(STATE, b"\xa5" * 64)                      # uninitialised RAM
e.stub(0x08053164, lambda: e.calls.append(("process", e.arg(0), e.arg(1), e.arg(2))), value=0x1234)
clock = 1_000_000


def block(n=1):
    global clock
    for _ in range(n):
        clock += BLOCK
        e.w32(ENGINE, clock)
        c = e.call("duck_block", ENGINE, 0x111, 0x222)
    return c


def ms(t):
    return int(t * 48 / BLOCK)


c = block()
check("block hook calls the engine process with its arguments and returns its result",
      c == [("process", ENGINE, 0x111, 0x222)] and e.uc.reg_read(UC_ARM_REG_R0) == 0x1234, c)
block(10)
check("idle: all four sources at 0", values() == [0, 0, 0, 0], values())


def voice_start(sym, original, pad_id):
    e.w32(PAD + 0x18, pad_id)
    seen = {}

    def rec():
        sp = e.uc.reg_read(UC_ARM_REG_SP)
        seen.update(r=[e.arg(i) for i in range(4)], sp=sp, stack=e.r32(sp), s0=struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0])
    e.stub(original, rec, value=0x77)
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 0.625))[0])
    e.w32(0x2407F000, 0xCAFE)                           # first stack argument
    e.call(sym, PAD, 0xA1, 0xA2, 0xA3)
    return seen


s = voice_start("duck_voice_start_a", 0x08058548, 0x0101)   # pad at row 1, col 1
check("thunk A passes r0-r3, stack and s0 through", s["r"] == [PAD, 0xA1, 0xA2, 0xA3] and s["sp"] == 0x2407F000 and s["stack"] == 0xCAFE and s["s0"] == 0.625, s)
block(5)
check("another pad starting a voice does not trigger", values() == [0, 0, 0, 0], values())

def trigger(thunk="duck_voice_start_a", original=0x08058548):
    voice_start(thunk, original, 0)


def run(t_ms):
    """Advance in single ticks, returning [(ms since start, [v0..v3])]."""
    out, start = [], clock
    while (clock - start) / 48 < t_ms:
        block()
        out.append(((clock - start) / 48, values()))
    return out


def at(trace, t_ms, i):
    return min(trace, key=lambda p: abs(p[0] - t_ms))[1][i]


def first(trace, i, cond):
    return next((t for t, v in trace if cond(v[i])), None)


EXP1, EXP2, PUMP, LINR = range(4)
trigger()
tr = run(900)
print("   t(ms)   EXP1   EXP2   PUMP   LINR")
for t in (1.4, 2.7, 5.4, 10, 30, 60, 106, 150, 200, 260, 330, 400, 520, 700):
    print("  %6.1f  " % t + "  ".join("%.3f" % at(tr, t, i) for i in range(4)))

check("another check that only pad 1 triggers was done above; all four start from 0 and rise", all(first(tr, i, lambda v: v > 0) is not None for i in range(4)))
check("EXP1/EXP2 at full depth on the second tick (1 ms attack)", at(tr, 2.7, EXP1) > 0.9 and at(tr, 2.7, EXP2) > 0.9, (at(tr, 2.7, EXP1), at(tr, 2.7, EXP2)))
check("PUMP at full depth after its 5 ms attack, LINR after 4 ms", first(tr, PUMP, lambda v: v == 1) <= 6.7 and first(tr, LINR, lambda v: v == 1) <= 5.4)
check("EXP1 is front-loaded: ~36% left after 54 ms, ~2% after 200 ms", abs(at(tr, 57, EXP1) - 0.36) < 0.05 and at(tr, 200, EXP1) < 0.04, (at(tr, 57, EXP1), at(tr, 200, EXP1)))
check("EXP1 fully recovered by ~250 ms", 240 <= first(tr[3:], EXP1, lambda v: v == 0) <= 262, first(tr[3:], EXP1, lambda v: v == 0))
check("EXP2 is the same shape at twice the length (~36% at 110 ms, done by ~500 ms)", abs(at(tr, 111, EXP2) - 0.36) < 0.05 and 490 <= first(tr[3:], EXP2, lambda v: v == 0) <= 512, (at(tr, 111, EXP2), first(tr[3:], EXP2, lambda v: v == 0)))
check("PUMP holds full depth for ~100 ms", at(tr, 100, PUMP) == 1 and at(tr, 112, PUMP) < 1, (at(tr, 100, PUMP), at(tr, 112, PUMP)))
check("PUMP recovers fast then eases: halfway through its 300 ms release it is ~6% of the dip", 0.03 < at(tr, 5 + 100 + 150, PUMP) < 0.09, at(tr, 255, PUMP))
check("PUMP done ~405 ms after the hit", 395 <= first(tr[8:], PUMP, lambda v: v == 0) <= 415, first(tr[8:], PUMP, lambda v: v == 0))
check("LINR unchanged: 25 ms hold, halfway back at ~180 ms, done at ~329 ms", at(tr, 26, LINR) == 1 and abs(at(tr, 179, LINR) - 0.5) < 0.03 and 320 <= first(tr[8:], LINR, lambda v: v == 0) <= 338, (at(tr, 179, LINR), first(tr[8:], LINR, lambda v: v == 0)))
check("every curve only falls during its release (no bumps)", all(all(b[1][i] <= a[1][i] + 1e-6 for a, b in zip(tr[90:], tr[91:])) for i in range(4)))

# retrigger while still recovering: rises from where it is
trigger("duck_voice_start_b", 0x08065908)
run(120)
before = values()
check("mid-recovery spread: EXP1 nearly back, EXP2 partway, PUMP in release", before[EXP1] < 0.15 and 0.2 < before[EXP2] < 0.5 and before[PUMP] < 1, before)
trigger("duck_voice_start_b", 0x08065908)
block(1)
after = values()
check("retrigger rises from the current level (no drop to 0 first)", all(a >= b for a, b in zip(after, before)), (before, after))
tr2 = run(8)
check("and each reaches full depth (EXP1/EXP2 within 3 ms, PUMP/LINR within 7 ms)",
      max(v[EXP1] for t, v in tr2 if t < 3) == 1 and max(v[EXP2] for t, v in tr2 if t < 3) == 1 and values()[PUMP] == 1 and values()[LINR] == 1, tr2)

# a clock jump (preset load, transport relocate) must not move the envelope
frozen = values()
clock += 10_000_000
block(1)
check("huge clock jump is ignored", values() == frozen, (frozen, values()))
run(900)
check("everything returns to rest", values() == [0, 0, 0, 0], values())

# ---------------------------------------------------------------- stock routing reads what we write
attached = {}
e.w32(PAD, VT)
e.w32(VT + 0x40, 0x08070001)                            # fake vtable slot: attach(amount, module, src, target, slot)
e.stub(0x08070000, lambda: attached.update(src=e.arg(1), target=e.arg(2), slot=e.arg(3),
                                           amount=struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0]))
e.w32(PAD + 0x10, 0)                                    # next module
e.w32(PAD + 0x18, 0x0102)                               # pad id of the ducked pad
e.w32(ENGINE + 0xFC08, PAD)
e.uc.mem_write(CMD, struct.pack("<BBHIIIIHh", 0x3A, 0, 0, 0, 0x0102, 4, 1, 0x12, -600))   # pad, target 4 (level), slot 1, source EXP1, -60.0%
e.call(0x080519E0, ENGINE, CMD)
check("stock dispatcher hands the pad the EXP1 source object", attached.get("src") == ENGINE + 0xD600 and attached.get("target") == 4 and attached.get("slot") == 1, attached)
check("amount arrives as -0.6", abs(attached.get("amount", 0) + 0.6) < 1e-6, attached)

# a parameter object with base value 0.75, limits 0..1, and our source attached through the real attach + read
base = PARAM + 0x100
e.uc.mem_write(base + 4, struct.pack("<f", 0.75))
e.w32(PARAM, base)
e.uc.mem_write(PARAM + 4, struct.pack("<f", 1.0))
e.uc.mem_write(PARAM + 0x28, struct.pack("<ff", 0.0, 1.0))
e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", attached["amount"]))[0])
e.call(0x0806FCD4, PARAM, attached["src"], attached["slot"])


def read_param():
    e.call(0x0806FB30, PARAM)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0]


check("at rest the parameter reads its base value (0.75)", abs(read_param() - 0.75) < 1e-6, read_param())
trigger()
e.w32(PAD + 0x18, 0x0102)
run(2)
check("at full duck it reads 0.75 - 0.6 = 0.15", abs(read_param() - 0.15) < 1e-5, read_param())
run(54)
mid = read_param()
check("54 ms into EXP1's release about two thirds of the dip is gone (0.75 - 0.6*0.36 = 0.53)", 0.50 < mid < 0.57, mid)
run(260)
check("and returns to the base value", abs(read_param() - 0.75) < 1e-6, read_param())

# ---------------------------------------------------------------- ENV: the pad's ADSR as a source (src/envmod.c)
labels = [e.cstr(p) for p in words(img, names, 16, "I")]
check("ENV sits right after CC, ahead of the duck shapes, code 1 (the preset format's 'env1')", labels[11] == "ENV" and words(img, codes, 16, "H")[11] == 1, (labels, words(img, codes, 16, "H")))
check("the three list counts are 16", img[0x0808CB3E - BASE:0x0808CB40 - BASE] == bytes.fromhex("1021") and img[0x080B67CC - BASE:0x080B67CE - BASE] == bytes.fromhex("102b")
      and img[0x080B7994 - BASE:0x080B7996 - BASE] == bytes.fromhex("1020"))

PAD2, VOICE, BASEV, CMD2 = 0x24068000, 0x2406A000, 0x2406C000, 0x2406D000
e.uc.mem_write(PAD2, bytes(0x800))
e.uc.mem_write(VOICE, bytes(0x800))


def f32(a):
    return struct.unpack("<f", e.uc.mem_read(a, 4))[0]


def slot_cmd(target, slot, source, amount):
    e.uc.mem_write(CMD2, struct.pack("<BBHIIIIHh", 0x3A, 0, 0, 0, 0, target, slot, source, amount))
    e.call("env_mod_setup", PAD2, CMD2)


def entries():
    n = e.r32(PAD2 + 0x54C)
    return [(round(f32(PAD2 + 0x4EC + 12 * i), 3), e.r16(PAD2 + 0x4F0 + 12 * i), e.r16(PAD2 + 0x4F2 + 12 * i), e.r8(PAD2 + 0x4F4 + 12 * i)) for i in range(n)]


slot_cmd(0x5C, 2, 1, 500)
check("ENV on a slot: the pad lists it as a per-voice entry with source 1 (stock code did the listing)", entries() == [(0.5, 0x5C, 1, 2)] and e.r32(PAD2 + 0x4E8) == 1 and e.r16(CMD2 + 0x14) == 1, entries())
slot_cmd(4, 1, 0xD, -250)
slot_cmd(10, 3, 1, 250)
check("velocity and a second ENV slot beside it", entries() == [(0.5, 0x5C, 1, 2), (-0.25, 4, 0xD, 1), (0.25, 10, 1, 3)], entries())
slot_cmd(0x5C, 2, 1, 800)
check("changing an ENV slot's Amount updates the same entry, still ENV", entries()[0] == (0.8, 0x5C, 1, 2) and len(entries()) == 3, entries())
slot_cmd(0x5C, 2, 0xD, 800)
check("switching that slot to VEL: the entry becomes velocity", entries()[0] == (0.8, 0x5C, 0xD, 2), entries())
slot_cmd(0x5C, 2, 1, 500)
slot_cmd(10, 3, 0, 0)
check("source none removes an ENV entry like any other", entries() == [(0.5, 0x5C, 1, 2), (-0.25, 4, 0xD, 1)], entries())

# a voice picks the list up: stock copies the pad's parameters and attaches velocity; ours attaches ENV
base = BASEV
e.uc.mem_write(base + 4, struct.pack("<f", 0.3))
e.w32(PAD2 + 0x28C, base)                                # the pad's copy of parameter 0x5c: base value 0.3, limits 0..1
e.uc.mem_write(PAD2 + 0x28C + 4, struct.pack("<f", 1.0))
e.uc.mem_write(PAD2 + 0x28C + 0x28, struct.pack("<ff", 0.0, 1.0))
e.call("env_mod_attach", PAD2, VOICE)


def voice_param():
    e.call(0x0806FB30, VOICE + 0x288)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0) & 0xFFFFFFFF))[0]


def has_source(param, src):
    return src in [e.r32(param + 4 * k) & 0xFFFFFFFF for k in range(13)]


check("the voice's parameter 0x5c has an input reading voice + 0x4c (the envelope)", has_source(VOICE + 0x288, VOICE + 0x4C))
for lvl in (0.0, 0.4, 1.0):
    e.uc.mem_write(VOICE + 0x50, struct.pack("<f", lvl))      # the amp envelope's level (envelope object +0x28)
    want = min(1.0, 0.3 + 0.5 * lvl)
    check(f"envelope level {lvl}: the parameter reads {want:.2f} (base 0.3 + 0.5 x level)", abs(voice_param() - want) < 1e-5, voice_param())
check("the velocity entry was attached by stock, to its own target (voice + 0x150, source voice + 0x84), and ENV was not added there", has_source(VOICE + 0x150, VOICE + 0x84) and not has_source(VOICE + 0x150, VOICE + 0x4C))

# ---------------------------------------------------------------- KEY: stock's own per-note source, now in the menu
check("KEY is the list's third entry with code 0xe, the preset format's 'key'", labels[2] == "KEY" and words(img, codes, 16, "H")[2] == 0xE)
e.uc.mem_write(PAD2, bytes(0x800))
e.uc.mem_write(VOICE, bytes(0x800))
slot_cmd(0x5C, 2, 0xE, 500)
check("KEY on a slot: stock lists it as a per-voice entry with source 0xe", entries() == [(0.5, 0x5C, 0xE, 2)], entries())
e.uc.mem_write(base + 4, struct.pack("<f", 0.3))
e.w32(PAD2 + 0x28C, base)
e.uc.mem_write(PAD2 + 0x28C + 4, struct.pack("<f", 1.0))
e.uc.mem_write(PAD2 + 0x28C + 0x28, struct.pack("<ff", 0.0, 1.0))
e.call("env_mod_attach", PAD2, VOICE)
check("a voice attaches it to voice + 0x8c (stock's attach; ours adds nothing)", has_source(VOICE + 0x288, VOICE + 0x8C) and not has_source(VOICE + 0x288, VOICE + 0x4C))
for note in (60, 72, 84, 36):
    e.uc.mem_write(VOICE + 0x90, struct.pack("<f", (note - 60) / 60.0))       # what voice start writes (FUN_08058548)
    want = 0.3 + 0.5 * (note - 60) / 60.0
    check(f"note {note}: the parameter reads {want:.3f} (base 0.3 + 0.5 x (note - 60) / 60)", abs(voice_param() - want) < 1e-5, voice_param())

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
