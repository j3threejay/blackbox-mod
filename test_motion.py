"""Motion: modulation on the delay's repeats (src/motion.c, the delay slot's glue in munchi.cpp), under Unicorn.

Real firmware runs for: the settings lookup, the list helpers (fill / remove / add), the buffer pointer and length
helpers. The DSP: the firmware build of motion.c is run block by block against the Mac build of the same file
(host/render_motion.py).
Stubbed and recorded: the stock delay process (made to write known "repeats" into the bus), the line clear, the send
gate, the bus lookup, registration, the store's add.
NOT run: the real stock delay, the screen, CPU on the real chip (counted here as instructions).
"""
import ctypes
import struct
import sys

import numpy as np
from unicorn.arm_const import UC_ARM_REG_SP

sys.path.insert(0, "host")
import render_motion as host
from emu import STACK, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x50003000, 0x1000)                       # WWDG1: audio_watch re-arms the early wakeup each block
e.uc.mem_map(0xC0000000, 0x400000)
e.uc.mem_map(0x30000000, 0x10000)
OBJ, VT, BUFS, CTX, BUS, IN = 0x30000000, 0x30001000, 0x30001100, 0x30001200, 0x30001300, 0x30001400
BUSL, BUSR, INL, INR, ARR = 0x30002000, 0x30002400, 0x30002800, 0x30002C00, 0x30003000
ST = 0x38800990                                   # where munchi.cpp puts motion.c's state
APPFX = 0x24020088 + 0x2FC0
N = 128
OFF, TREM, FILTER, DUCK, SWELL = 0, 1, 2, 3, 4
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.w32(OBJ + 0x18, 3 << 16 | 0 << 8)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 2))
e.uc.mem_write(OBJ + 0x2C, struct.pack("<f", 0.5))
e.uc.mem_write(OBJ + 0x21F, b"\x01")
for off, ptr, floats in ((0x30, 0xC0000000, 192256), (0x4C, 0xC0100000, 96256), (0x68, 0xC0200000, 192256)):
    e.w32(OBJ + off, ptr)
    e.w32(OBJ + off + 0x14, floats)
e.w32(BUFS, CTX)
e.uc.mem_write(CTX + 0x18, struct.pack("<f", 126.0))


def buf(addr, l, r):
    e.w32(addr, N)
    e.w32(addr + 4, N)
    e.w32(addr + 8, l)
    e.w32(addr + 12, r)
    e.uc.mem_write(addr + 0x10, b"\x00\x01")


buf(BUS, BUSL, BUSR)
buf(IN, INL, INR)
calls = []
wet = {"l": None, "r": None}


def stock():
    """stand in for the stock delay: it leaves its repeats in the bus, which is what Motion then works on"""
    calls.append("stock")
    if wet["l"] is not None:
        e.uc.mem_write(BUSL, wet["l"].tobytes())
        e.uc.mem_write(BUSR, wet["r"].tobytes())


e.stubs[0x080548C8] = lambda: (stock(), e.ret(1))
e.stub(0x0806AAC0, lambda: calls.append("clear"))
e.stub(0x0804F0D4)
e.stub(0x0804F270, lambda: e.w32(e.arg(2), IN))
e.stub(0x0805F37C, value=BUS)
params = {}


def store(**kv):
    params.update(kv)
    ids = {"type": 0x197, "fb": 0x38, "kind": 0x1BF, "rate": 0x1C0, "depth": 0x1C1}
    data = b"".join(struct.pack("<HHI", ids[k], 0, v) for k, v in params.items())
    e.uc.mem_write(ARR, data)
    e.w32(APPFX + 4, ARR)
    e.uc.mem_write(APPFX + 10, struct.pack("<H", len(params)))


def run_block(send, repeats_l, repeats_r):
    """one engine block: `send` is what the pads put in the bus, `repeats` what stock leaves there"""
    e.uc.mem_write(BUSL, np.asarray(send, np.float32).tobytes())
    e.uc.mem_write(BUSR, np.asarray(send, np.float32).tobytes())
    wet["l"], wet["r"] = np.asarray(repeats_l, np.float32), np.asarray(repeats_r, np.float32)
    calls.clear()
    e.call("munchi_process", OBJ, BUFS, count=50_000_000)
    return (np.frombuffer(bytes(e.uc.mem_read(BUSL, 4 * N)), np.float32).copy(),
            np.frombuffer(bytes(e.uc.mem_read(BUSR, 4 * N)), np.float32).copy())


# ---------------------------------------------------------------- settings
lists, nums, added = [], [], []
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))],
                                         e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4), e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 8)))))
e.uc.mem_write(STACK, struct.pack("<II", 0, 0x080CC794))     # munchi_register's 5th and 6th args: count, xml
e.call("munchi_register", 0x24001000, 0x197, 0, 0)
check("the delay Type list reads Delay, Munchi, Motion, Relapse, Confetti - both engines have their own slot now",
      lists[0][:3] == (0x197, "Type:", ["Delay", "Munchi", "Motion", "Relapse", "Confetti"]), lists[0])
check("Motion registered: Off, Trem, Filter, Duck, Swell",
      [l[:3] for l in lists if l[0] == 0x1BF] == [(0x1BF, "Motion:", ["Off", "Trem", "Filter", "Duck", "Swell"])],
      [l for l in lists if l[0] == 0x1BF])
check("...with Rate and Depth as 0..100 % knobs (ids 0x1c0, 0x1c1)",
      [n[:4] for n in nums if n[0] in (0x1C0, 0x1C1)] == [(0x1C0, "Rate:", 0, 1000), (0x1C1, "Depth:", 0, 1000)],
      [n for n in nums if n[0] in (0x1C0, 0x1C1)])
check("three distinct xml names, labels short enough for the knob screen",
      len({"motionkind", "motionrate", "motiondepth"} & ({l[3] for l in lists} | {n[4] for n in nums})) == 3
      and all(len(x[1]) <= 9 for x in lists + nums))
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("munchi_defaults_last", 0x24072000, 0x35, 1)
check("defaults at the end of the delay cell: Motion Trem, Rate 40 %, Depth 60 % (then FX OUT's Level + Low Cut)",
      added[-6:] == [(0x1BF, TREM), (0x1C0, 400), (0x1C1, 600), (0x149, 4000), (0x14A, 0), (0x148, 0)], added[-6:])
check("the delay cell's store has room: %d entries of 96" % len(added), len(added) <= 96)
img = open(IMG, "rb").read()
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)

# ---------------------------------------------------------------- the page
LIST = 0x30004000
page, removed = [], []
# The real fill puts EVERY registered setting of the cell in the list, the motion's three among them, and the screen
# shows the first 8. 3.2.a added them a SECOND time on top of that, so the page ran to ten and read Motion twice
# (seen in a photo of the screen). An empty fill stub is what let that through, so this one fills the way the firmware does.
FILL = [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35, 0x1BF, 0x1C0, 0x1C1]
e.stub(0x080A50FC, lambda: page.extend(FILL))
e.stub(0x080A5038, lambda: page.append(e.arg(1)))
e.stub(0x080A4FC2, lambda: page.clear())
e.stub(0x080A506C, lambda: (removed.append(e.arg(1)), page.remove(e.arg(1)) if e.arg(1) in page else None))
CELLVT = 0x30005000
e.w32(APPFX, CELLVT)
e.w32(CELLVT, 0x0807FF10 | 1)
e.uc.mem_write(0x0807FF10, bytes.fromhex("2620704700bf"))      # movs r0,#0x26 (CELL_DELAY); bx lr


def build(type_):
    store(type=type_)
    page.clear()
    removed.clear()
    e.call("munchi_list", LIST, APPFX, count=5_000_000)
    return list(page), list(removed)


got, gone = build(2)
check("Motion's page is exactly the 8 slots the screen shows: Type, Delay, Delay(beat), Feedback, Beat, Motion, Rate, Depth",
      got == [0x197, 0x32, 0x33, 0x38, 0x34, 0x1BF, 0x1C0, 0x1C1], [hex(i) for i in got])
check("...nothing on it twice, and it does not run past 8 (3.2.a listed Motion twice)",
      len(got) == len(set(got)) and len(got) <= 8, [hex(i) for i in got])
check("...the four the screen cannot fit are among those dropped", set([0x0E, 0xCA, 0xC9, 0x35]) <= set(gone), gone)
got, gone = build(0)
check("Type Delay: the stock page as before, the motion's three taken off",
      got == [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35] and {0x1BF, 0x1C0, 0x1C1} <= set(gone),
      [hex(i) for i in got])

# ---------------------------------------------------------------- the slot
e.uc.mem_write(ST, bytes(0x40))
rng = np.random.default_rng(4)
reps = (0.4 * rng.uniform(-1, 1, N)).astype(np.float32)
send = (0.5 * rng.uniform(-1, 1, N)).astype(np.float32)
store(type=0, kind=TREM, rate=400, depth=900)
l, r = run_block(send, reps, reps)
check("Type Delay: stock runs and its repeats reach the bus untouched", calls == ["stock"] and np.array_equal(l, reps))
store(type=2, kind=OFF)
l, r = run_block(send, reps, reps)
check("Type Motion with Motion Off: stock runs, repeats untouched", calls == ["stock"] and np.array_equal(l, reps))
store(type=2, kind=TREM, rate=400, depth=900)
e.uc.mem_write(ST, bytes(0x40))
l, r = run_block(send, reps, reps)
check("Type Motion with Trem: stock still runs, and its repeats come back modulated",
      calls == ["stock"] and not np.array_equal(l, reps) and np.abs(l).max() <= np.abs(reps).max() + 1e-6, calls)
check("the delay's lines are never cleared by switching to Motion (stock keeps them)", "clear" not in calls)

# ---------------------------------------------------------------- firmware DSP = the Mac build's, every type
dll = host.lib()
t = np.arange(N * 60)
src = (0.5 * np.sin(2 * np.pi * 180 * t / 48000) * (0.4 + 0.6 * (np.sin(2 * np.pi * 2.1 * t / 48000) > 0))
       + 0.2 * rng.uniform(-1, 1, len(t))).astype(np.float32)
dry = np.abs(src)
for kind, name, rate, depth in ((TREM, "Trem", 0.35, 0.8), (FILTER, "Filter", 0.3, 0.75),
                                (DUCK, "Duck", 0.45, 0.85), (SWELL, "Swell", 0.4, 0.9)):
    state = ctypes.create_string_buffer(128)
    wl, wr = src.copy(), (0.7 * src).copy()
    for at in range(0, len(src) - N + 1, N):
        peak = float(np.abs(dry[at:at + N]).max())
        dll.motion_block(state, kind, rate, depth, peak, wl[at:at + N].ctypes.data_as(host.F),
                         wr[at:at + N].ctypes.data_as(host.F), N)
    store(type=2, kind=kind, rate=int(rate * 1000), depth=int(depth * 1000))
    e.uc.mem_write(ST, bytes(0x40))
    gl, gr = [], []
    for at in range(0, len(src) - N + 1, N):
        a, b = run_block(dry[at:at + N], src[at:at + N], 0.7 * src[at:at + N])
        gl.append(a)
        gr.append(b)
    gl, gr = np.concatenate(gl), np.concatenate(gr)
    err = max(np.abs(gl - wl[:len(gl)]).max(), np.abs(gr - wr[:len(gr)]).max())
    moved = np.abs(gl - src[:len(gl)]).max() > 0.02
    check(f"{name}: 60 blocks match the Mac build (max difference {err:.1e}) and really change the repeats", err < 2e-4 and moved, err)

# Depth 0 is a no-op, silence stays silent
store(type=2, kind=TREM, rate=500, depth=0)
e.uc.mem_write(ST, bytes(0x40))
l, _ = run_block(send, reps, reps)
l, _ = run_block(send, reps, reps)
check("Depth 0 leaves the repeats exactly as they were", np.array_equal(l, reps))
store(type=2, kind=DUCK, rate=500, depth=1000)
z = np.zeros(N, np.float32)
l, _ = run_block(z, z, z)
check("silence in, silence out", not np.abs(l).max())
store(type=2, kind=SWELL, rate=900, depth=1000)
e.uc.mem_write(ST, bytes(0x40))
for _ in range(4):
    l, _ = run_block(send, reps, reps)
check("a type past the list and a fresh state never produce anything out of range", np.isfinite(l).all() and np.abs(l).max() <= 0.41)

count = {"n": 0}
store(type=2, kind=FILTER, rate=400, depth=800)
run_block(send, reps, reps)
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
run_block(send, reps, reps)
e.uc.hook_del(hook)
print(f"     cost: {count['n'] / N:.0f} instructions per stereo frame (Filter, the heaviest), on the send only")
check("cost under 120 instructions per stereo frame", count["n"] / N < 120, count["n"] / N)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
