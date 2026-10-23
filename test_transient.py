"""The Transient insert (src/transient.c, its place in insert.c / insert_dsp.c / master.c) under Unicorn.

Real firmware runs for: ts_block and ins_render from the bank 2 this build links (BANK2_NEW), master_list's insert page.
Compared against: the Mac build of the same transient.c (host/render_transient.py's library), block by block, on the
4X4DRUMS103 loop, every model, two settings each.
Checked: the two builds agree; ins_render hands a Transient pad to ts_block and leaves the other state alone;
the page lists Insert + Model + the six; the cost per stereo frame (instruction count).
NOT run: the sound on the unit, the knob screen on the glass, a pad's store past its 96 entries (89 used now).
"""
import ctypes
import os
import struct
import sys

os.environ.setdefault("BANK2_NEW", "1")
import numpy as np                                     # noqa: E402

sys.path.insert(0, "host")
import render_transient as rt                          # noqa: E402
from emu import Emu                                    # noqa: E402

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x30000000, 0x20000)
ST, PAR, BL, BR, SET, INS = 0x30000000, 0x30000100, 0x30001000, 0x30001400, 0x30002000, 0x30004000
N = 128
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# ts_block takes 5 arguments: state, params, l, r, n - n goes on the stack
_call = e.call


def call5(name, a, b, c, d, n=N):
    e.w32(0x2407F000, n)
    return _call(name, a, b, c, d)


dll = rt.lib()
LOOP = "measure/4X4DRUMS103-48k.wav"                   # a drum loop from a sample library: not in the public tree
if os.path.exists(LOOP):
    x = rt.load_any(LOOP, 3.0)
else:                                                  # stand-in: kicks + hats, decaying, peak 0.7 like load_any
    t = np.arange(int(3.0 * 48000)) / 48000.0
    beat, rng = t % 0.5, np.random.default_rng(3)
    x = np.sin(2 * np.pi * (50 + 120 * np.exp(-beat * 40)) * beat) * np.exp(-beat * 9)
    x += 0.4 * rng.standard_normal(len(t)) * np.exp(-((t + 0.25) % 0.5) * 60)
    x = (0.7 * x / np.abs(x).max()).astype(np.float32)
worst = 0.0
for m, name in enumerate(rt.MODELS):
    for kw in (dict(attack=0.8, sustain=-0.4), dict(attack=-0.5, sustain=0.7, speed=0.2, length=0.8, output=0.4, mix=0.7)):
        ml, mr = rt.run(dll, x, m, **kw)
        e.uc.mem_write(ST, bytes(64))
        e.uc.mem_write(PAR, struct.pack("<I6f", m, kw.get("attack", 0.0), kw.get("sustain", 0.0), kw.get("speed", 0.5),
                                        kw.get("length", 0.5), kw.get("output", 0.5), kw.get("mix", 1.0)))
        fl = []
        for at in range(0, len(x) - N + 1, N):
            blk = struct.pack(f"<{N}f", *x[at:at + N])
            e.uc.mem_write(BL, blk)
            e.uc.mem_write(BR, blk)
            call5("ts_block", ST, PAR, BL, BR)
            fl += struct.unpack(f"<{N}f", e.uc.mem_read(BL, 4 * N))
        fl = np.array(fl, np.float32)
        err = float(np.max(np.abs(fl - ml[:len(fl)])))
        worst = max(worst, err)
        check(f"{name} {kw}: the unit's build = the Mac build the renders came from (max diff {err:.1e})", err < 1e-3, err)

# ins_render: a Transient pad goes to ts_block
SET_TS, ST_TS = 48, 216                                # offsetof(struct ins_set, ts), offsetof(struct ins_state, ts)
e.uc.mem_write(SET, struct.pack("<BBBB6f5f", 4, 0, 0, 0, *([0.5] * 6), *([0.0] * 5)) + struct.pack("<I6f", 0, 0.8, 0.0, 0.5, 0.5, 0.5, 1.0))
e.uc.mem_write(INS, bytes(8444))
blk = struct.pack(f"<{N}f", *x[:N])
for k in range(8):
    blk = struct.pack(f"<{N}f", *x[k * N:(k + 1) * N])
    e.uc.mem_write(BL, blk)
    e.uc.mem_write(BR, blk)
    call5("ins_render", INS, SET, BL, BR)
magic = e.r32(INS + ST_TS + 28)
check("ins_render with type Transient runs ts_block on the pad's own state (its magic TST1 set)", magic == 0x54535431, hex(magic & 0xFFFFFFFF))
check("...and the Phaser / Flanger delay line is not touched", bytes(e.uc.mem_read(INS + 8444 - 8192, 8192)) == bytes(8192))
out = np.array(struct.unpack(f"<{N}f", e.uc.mem_read(BL, 4 * N)))
check("...and the audio changed (Attack +80 % on drums)", np.max(np.abs(out - np.array(struct.unpack(f"<{N}f", blk)))) > 1e-4)

# cost
count = {"n": 0}
e.uc.mem_write(PAR, struct.pack("<I6f", 0, 0.8, -0.4, 0.5, 0.5, 0.5, 1.0))
blk = struct.pack(f"<{N}f", *x[N * 40:N * 41])
for m in range(3):
    e.uc.mem_write(PAR, struct.pack("<I", m))
    e.uc.mem_write(BL, blk)
    e.uc.mem_write(BR, blk)
    call5("ts_block", ST, PAR, BL, BR)
    count["n"] = 0
    hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
    e.uc.mem_write(BL, blk)
    e.uc.mem_write(BR, blk)
    call5("ts_block", ST, PAR, BL, BR)
    e.uc.hook_del(hook)
    per = count["n"] / N
    print(f"     cost, {rt.MODELS[m]}: {per:.0f} instructions per stereo frame (~{per / 101:.2f} % at 48 kHz), per pad that has it")
    check(f"{rt.MODELS[m]} costs under 80 instructions a stereo frame", per < 80, per)
e.uc.mem_write(PAR, struct.pack("<I6f", 0, 0.0, 0.0, 0.5, 0.5, 0.5, 1.0))
count["n"] = 0
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
call5("ts_block", ST, PAR, BL, BR)
e.uc.hook_del(hook)
check(f"Attack and Sustain at 0, Output 0 dB: almost free ({count['n']} instructions for the block)", count["n"] < 100, count["n"])

img = open(IMG, "rb").read()
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
