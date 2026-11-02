"""The master clipper (src/clip.c, comp.c's clip_stage) under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c), our compressor models and Master FX stage ahead of it.
The clipper: the firmware build of clip.c is run block by block against the Mac build of the same file
(host/render_clip.py).
Stubbed and recorded: the stock compressor (and what the chain pointer was when it ran), the chain's next stage,
the buffer lookups, registration, the store's add.
NOT run: the real output chain after the compressor, the Compressor page on the screen, CPU on the real chip.
"""
import struct
import sys

import numpy as np
from unicorn.arm_const import UC_ARM_REG_SP

sys.path.insert(0, "host")
import render_clip as host
from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
APP = 0x24020088
STORE, ARR = APP + 0x8C90, 0x24070000
OBJ, VT, BUFS, L, R, NEXT, NEXTVT = 0x24060000, 0x24061000, 0x24050000, 0x24064000, 0x24066000, 0x24062000, 0x24063000
BLOCK, CLIP = 0xC0000000, 0xC0000000 + 0x56800 + 0x2D000
PMEM, PCHECK = 0x38800F70, 0x38800F74
N = 256
CEILING = 0.9661
calls, fails = [], 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def settings(comp=0, clipper=0, clip=0, shape=0, mfx=0, thresh=0):
    rows = sorted({0xB4: comp, 0x1B2: clip, 0x1B3: shape, 0x1B4: clipper, 0x1DB: mfx, 0x1D0: thresh, 0x1EA: 500, 0x1EB: 500}.items())
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", len(rows)))


def memory(on=True):
    e.w32(PMEM, BLOCK if on else 0)
    e.w32(PCHECK, (BLOCK ^ 0x5052534D) if on else 0)
    e.uc.mem_write(CLIP, bytes(0x100))


e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 3))
BUF = BUFS + 3 * 0x14 + 0x150E4
e.w32(NEXT, NEXTVT)
e.w32(NEXTVT + 0xC, 0x0807FF00 | 1)
e.uc.mem_write(0x0807FF00, b"\x70\x47")                       # bx lr: the chain's next stage


def peak():
    return float(np.abs(np.frombuffer(bytes(e.uc.mem_read(L, 4 * N)), np.float32)).max())


e.stubs[0x0807FF00] = lambda: (calls.append(("next", round(peak(), 3))), e.ret(1))
e.stubs[0x0804EDDC] = lambda: (calls.append(("stock", e.r32(OBJ + 8), round(peak(), 3))), e.ret(1))


def block(left, right=None, chain=True):
    right = left if right is None else right
    e.uc.mem_write(L, np.asarray(left, np.float32).tobytes())
    e.uc.mem_write(R, np.asarray(right, np.float32).tobytes())
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R, 0, 1))
    e.w32(OBJ + 8, NEXT if chain else 0)
    calls.clear()
    e.call("comp_process", OBJ, BUFS, count=40_000_000)
    return (np.frombuffer(bytes(e.uc.mem_read(L, 4 * len(left))), np.float32).copy(),
            np.frombuffer(bytes(e.uc.mem_read(R, 4 * len(left))), np.float32).copy())


t = np.arange(N * 12)
loud = (1.6 * np.sin(2 * np.pi * 220 * t / 48000) + 0.5 * np.sin(2 * np.pi * 3100 * t / 48000)).astype(np.float32)

# ---------------------------------------------------------------- settings
lists, nums, added = [], [], []
keep = (e.stubs.get(0x0808C0D8), e.stubs.get(0x0808C12C))
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.uc.mem_write(0x2407F000, struct.pack("<III", 0, 1, 0x080CC794))    # comp_register's own stack arguments: min, max, xml
e.call("comp_register", 0x24001000, 0xB4, 0, 0x080CC794)
check("registered last: Clipper (Off, Clean, Diode), Clip and Shape as 0..100 %",
      lists[-1][:3] == (0x1B4, "Clipper:", ["Off", "Clean", "Diode"]) and [n[:4] for n in nums[-2:]] == [(0x1B2, "Clip:", 0, 1000), (0x1B3, "Shape:", 0, 1000)], (lists[-1], nums[-2:]))
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("comp_defaults", 0x24072000, 0xB4, 1)
check("defaults, after everything that was there: Clipper Off, Clip 30 %, Shape 80 %", added[-3:] == [(0x1B4, 0), (0x1B2, 300), (0x1B3, 800)], added[-3:])
check("our global settings, with the three new ones: %d; stock has 41 of its own; the store holds 96" % (len(added) - 1), len(added) - 1 + 41 <= 96)
img = open("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "rb").read()
page = struct.unpack_from("<4H", img, 0x080EED18 - 0x08040000)
check("Tools: Headphone, Master FX, Compressor, Out 1: the two rows in signal order", page == (0xBA, 0x1DB, 0xB4, 0xBB), [hex(v) for v in page])

# ---------------------------------------------------------------- where it sits
memory()
settings(comp=0, clipper=0)
l, _ = block(loud[:N])
check("Clipper Off, compressor Off: Out 1 untouched", np.array_equal(l, loud[:N]) and not calls)
settings(comp=0, clipper=1, clip=0, shape=1000)
for k in range(3):
    l, r = block(loud[k * N:(k + 1) * N])
check("compressor Off, Clipper Clean: Out 1 held at the ceiling (-0.3 dBFS), both channels", abs(np.abs(l).max() - CEILING) < 1e-4 and np.array_equal(l, r), np.abs(l).max())
check("...and, as before, no chain call with the compressor Off", not calls)
settings(comp=1, clipper=1, clip=0, shape=1000)
memory()
for k in range(3):
    l, _ = block(loud[k * N:(k + 1) * N])
check("Stock compressor: it runs with its chain held back, then the clipper, then the chain gets the clipped block",
      calls == [("stock", 0, round(float(np.abs(loud[2 * N:3 * N]).max()), 3)), ("next", 0.966)] and e.r32(OBJ + 8) == NEXT, calls)
l, _ = block(loud[:N], chain=False)
check("Stock compressor with no chain: nothing called after it, clipper still runs", calls[1:] == [] and np.abs(l).max() <= CEILING + 1e-4, calls)
for model, name in ((2, "Glue"), (6, "Limit"), (7, "Smash")):
    settings(comp=model, clipper=1, clip=500, shape=600)
    memory()
    e.uc.mem_write(0x38800400, bytes(0x200))
    for k in range(4):
        l, _ = block(loud[k * N:(k + 1) * N])
    check(f"{name}: the chain's next stage is handed a block already at or under the ceiling", calls == [("next", calls[0][1])] and calls[0][1] <= 0.967, calls)
memory(False)
settings(comp=0, clipper=1, clip=500, shape=600)
l, _ = block(loud[:N])
check("no memory block: the clipper stands aside", np.array_equal(l, loud[:N]))

# ---------------------------------------------------------------- the firmware's clipper = the Mac build's
dll = host.lib()
rng = np.random.default_rng(5)
src = (loud + 0.3 * rng.uniform(-1, 1, len(loud))).astype(np.float32)
src_r = (0.7 * src[::-1]).astype(np.float32)
for kind, name in ((1, "Clean"), (2, "Diode")):
    for clip, shape in ((0, 1000), (500, 600), (1000, 0)):
        memory()
        settings(comp=0, clipper=kind, clip=clip, shape=shape)
        state = host.ctypes.create_string_buffer(256)
        wl, wr = src.copy(), src_r.copy()
        for at in range(0, len(src), N):
            dll.clip_block(state, kind, clip / 1000, shape / 1000, wl[at:at + N].ctypes.data_as(host.F), wr[at:at + N].ctypes.data_as(host.F), N)
        gl, gr = [], []
        for at in range(0, len(src), N):
            a, b = block(src[at:at + N], src_r[at:at + N])
            gl.append(a)
            gr.append(b)
        gl, gr = np.concatenate(gl), np.concatenate(gr)
        err = max(np.abs(gl - wl).max(), np.abs(gr - wr).max())
        check(f"{name}, Clip {clip // 10} %, Shape {shape // 10} %: 12 blocks match the Mac build (max difference {err:.1e}), peak {np.abs(gl).max():.4f}",
              err < 1e-4 and np.abs(gl).max() <= CEILING + 1e-5, err)

quiet = (0.2 * np.sin(2 * np.pi * 9000 * t / 48000)).astype(np.float32)
memory()
settings(comp=0, clipper=1, clip=0, shape=700)
out = np.concatenate([block(quiet[at:at + N])[0] for at in range(0, N * 4, N)])
check("under the knee the output is the input five samples late, to the last bit or two", np.abs(out[5:] - quiet[:N * 4 - 5]).max() < 1e-6, np.abs(out[5:] - quiet[:N * 4 - 5]).max())
settings(comp=0, clipper=0)
block(quiet[:N])
check("switching it Off drops its state, so it starts clean next time", e.r32(CLIP) == 0)

count = {"n": 0}
settings(comp=0, clipper=2, clip=700, shape=600)
block(loud[:N])
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
block(loud[N:2 * N])
e.uc.hook_del(hook)
print(f"     cost: {count['n'] / N:.0f} instructions per stereo frame (Diode, clipping), on the master only")
check("cost under 350 instructions per stereo frame (Prism's worst is about 760)", count["n"] / N < 350, count["n"] / N)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
