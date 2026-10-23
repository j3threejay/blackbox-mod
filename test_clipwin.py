"""Clip Window: Slip, Region, Loop Len, Fit and Loop Fade (src/clipwin.c, clipwin_b2.c, clipwin_thunk.S,
patches/clipwin.py; notes/re/README.md sections 2, 3) under Unicorn.

Real firmware runs for: the whole class-B pad block method (0x08068c64) block after block - process, voice start, the
recompute (FUN_08064a94 with H3 in it, called at the wraps through H3'), segment start (FUN_08065550 with H1 and H3 in
it, FUN_08065290 with H1'), render, fades, the segment reader with JOEBOX's
clip_read_b and clipwin_read in it, filter.c's clip_read and clip_read_ring, the stock clip reader and its kernel - then
the engine's own clock advance (0x080696d8), in the control tick's order; the pad constructor and the real param-set
for every setting (Pad Mode, Launch, Loop, Beat Count, Quant, Sync, Pitch, slice markers, a live Sync change, Launch
Trigger relaunches, Toggle stops, the transport stopped and its start message 0x57) and where Loop Len forces Sync from
clipwin_tick, which duck_block hands the engine; the cell's class-H object (its constructor,
linked at pad + 8, its block method after the pad's, its param-set storing Loop Start / End / Mode from the same
queue); clipwin_tick reading the app's pad stores
through the stock settings lookup, once a block where duck_block calls it; filter.c's machine readers (every machine
mode, SP 45 included) at and near the seam; the stock pad-parameter registrar (FUN_0808c158) with master_register /
clipwin_register in it, the stock pad-store builder (FUN_08093f20) with the defaults chain in it, master_alloc; the
stock knob binder (FUN_080a7ee0), set-value, the turn (FUN_080b0d54) and list-widget (FUN_080b9a3c) paths with
clipwin_format / clipwin_turn in them, the stock ring push and speed, stepper and snprintf; both thunks entered as their
sites enter them; the Waveform screen's setup (FUN_080a54a0: its bind block, FUN_080a53a2 and the refresh, with
clipwin_bind / clipwin_zoom / clipwin_wave in them), the view's two handlers (the knob event, the param-changed refresh,
the forward to the app with JOEBOX's slice_forward in it, the zoom message), the waveform's slice-marker and zoom setters,
and the app's SetCellParam (FUN_0809fa50) for what the forward sends; the Clip Window's maths in bank 2 (clipwin_b2.c,
every hook's), and a bank 2 whose header is gone from the start (every hook then stock's). Every scenario
also runs on this image with the clipwin hooks taken out at run time (or only Region's), and the Slip 0 ones on the
stock 3.1.9 image, for the comparisons; a Region scenario also runs on the stock image with a file as long as its
region.
Stubbed: the allocator, the log print, for the Waveform screen the app's copy of the pad's store into the view, the file
name, icons, buttons and the mode list, SetCellParam's posts to the engine and the UI (recorded), the sample source (length, rate, ready, the prefetch hint - recorded, with the
read it was made in - and the mono / stereo fetch, which serve a ramp: frame q holds (q + 1) * 2^-20, the right channel
its negative, or 1.0 for the gain runs; in the reader unit two sines, the file or the file turned circular), the knob's
text widget, redraw and post to the app (recorded).
Reference: the research harness's stock measurements (notes/re/a2: launch on the bar at 288 000 with +0x140 = 11 520
and msg 0x1d, a launch 300 samples late at once with +0x140 = 11 532, steps at (int)(j x fps), Sync None restarting
every len - 257 samples) and its model's assertions (a2/r2/k_slip.py, k_live.py, droplaunch.py, armed.py): every
sounding sample plays (stock frame + slip_f) mod len, the summed gain is stock's - a launch waiting for its bar when
Slip changes included; for a region (a2/r2/k_region.py, k_seam.py), stock playing a file as long as the region
(every sample at rs + (its frame + slip_f) mod vlen, the same gain away from the wraps; every recompute field), a
change heard from the next wrap on (the one after when made in the last Sync step; the next on its own grid when it
moves the wrap grid, against stock's live Beat Count change, which doubles) with no silence added, and no zero-gain
sample nor doubling at a seamless wrap, a clip of one step included; for Loop Len (a2/r2/k_looplen.py), the model's
numbers (the in-point from the sounding segment's phase, a forced Sync re-gridding the playing segment, the launch held
until it has sounded), the review's cases with absolute frames (a 44.1 kHz file whose re-indexed step runs ahead of its
position, Off and on within a step, a stop and relaunch, Sync None) and every segment starting on (int)((float)w x
fps) for the window's step w, then playing on, the gain of the run without it where Sync is not forced, no zero-gain
sample added where it is; for Fit, the rule's own numbers (the nearest whole beat, the wrap grid gcd(Quant, clip), its
steps gcd(Sync, clip), FUN_08070420's samples) at H3 site 3, and a model of what a fitted clip must sound like: every
pass one clip after the one before, the audio carrying on at every joint (within half a frame, a frame where stock
starts a step on a whole frame), no zero-gain sample and no doubling, where stock (Fit Off, the same files at their Beat
Count) does not - 3, 5, 6, 7 and 14 beats on Quant 1 bar, Sync 1/16 to 1 bar, Quant None (CW_FULL=1: at every Sync),
a file and a region, a tempo change, Slip, Loop Len, Pitch, 44.1 kHz stereo, a one-shot, live changes and the wrap's
hold - and a launch off the Sync grid pulled onto the beat at its first step as Fit Off and the stock image pull it; for
Loop Fade, stock's Sample-mode formula (FUN_08056fd0: an equal-gain linear crossfade of the loop's last F frames into
the F before Loop Start) frame by frame, and a mismatched sine's splice; for
the reader, the stock reader on the file turned circular; for a machine-mode pad, filter.c's
own clip_read on the file turned circular (at the seam, on the last blocks before it, near the start: bit for bit) and
test_clip.py's drop-sample model off the seam; for the seam hint, notes/re/a2's provider (a hint covers the block of
its position and the next two: 16 384 frames sure); for the Waveform knobs, stock's own Loop Start / End knobs in Sample
mode at the same zoom (the same posts, steps, ranges and positions, turn after turn), the bare Slip knob (the same values
with every turn sent to the app and refreshed), and the screen with the three hooks taken out in every other mode.
NOT checked: duck_block and the control tick around clipwin_tick (only its place in duck_block, from the image); a
negative value through preset save / load; how the waveform draws the bracket (only the widget's fields and dirty flag
are checked: its draw gates the bracket on +0x239 alone, notes/re/a3), the zoom a pinch leaves pending until the
waveform's tick applies it and posts 0xe5 (the message is sent here), the dead travel at the top of a type-0xd knob on
the hardware (stock's, open question 16); SD streaming at
the seam (the source is in RAM: the hints are checked - H1's, and H2's at rs (and where a fade's copy starts) per
crossing segment - not whether the
unit's cache still holds the hinted blocks when the read gets there: the miss counter 0x24013930, on the unit); Fidelity
machine modes inside the whole process (the reader alone is); relaunches at
the other recompute sites beyond the retriggers (a pad relaunched while it plays keeps its region: not run); Loop Len
with Pitch (rate != 1 is run once, a 44.1 kHz file), with a region change or a Beat Count change while it is engaged,
and a Trigger / Gate relaunch while it is engaged; whether a preset load stops a pad (Loop Len's in-point resets on a
stopped pad); the app's
loader and Pad Mode change feeding the class-H object (posted here as the app posts them, x3); the knob's counts per
revolution on the hardware (the acceleration's K); Fit on a pad the app's Beat Count display then miscounts (the app is
told stock's clip, msg 0x8d); whether the app's preset load closes a pad's file before its recompute (Fit Auto's
count is forgotten only then); how it sounds; CPU on the chip.
"""
import math
import os
import re
import struct
import subprocess
import sys

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_R11, UC_ARM_REG_S0,
                               UC_ARM_REG_SP, UC_ARM_REG_LR)

from emu import BASE, RET, STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
e = Emu(IMAGE, "out/cave.elf")
img, stock = open(IMAGE, "rb").read(), open(STOCK, "rb").read()
S = e.sym

P_SLIP, P_REGION, P_LOOPLEN, P_SYNC = 0x1C9, 0x1C8, 0x1CA, 0x94
P_FIT, P_FADE = 0x1CB, 0xFA                          # Fit; stock's Sample-mode Loop Fade (0 .. 1000)
AUTO, FILE, LOOP = 0, 1, 2                           # Region's list
FIT_NAMES = ["Off", "Auto (Bars)", "Auto (Beats)", "1/4", "1/2", "3 beats", "1 bar", "6 beats", "2 bars", "4 bars", "8 bars"]
FIT_BEATS = [None, None, None, 1, 2, 3, 4, 6, 8, 16, 32]   # Fit's list: its beats (each Auto counts its own)
AUTO_BARS, AUTO_BEATS = 1, 2                         # Fit's two Autos
APP = 0x24020088
APP_PADS = APP + 0x1840
GUI_MS = 0x2402EEE0
PMEM, PCHECK, KEY = 0x38800F70, 0x38800F74, 0x5052534D
BLOCK = 0xC0000000                                   # master.c's boot-time SDRAM block, here
BANK = BLOCK + 0x56800 + 0x2D100                     # clipwin.c's cw_bank in it
B_SLIP, B_PAD, B_VALID, B_LATCH, B_H1, B_HINTED = 8, 0x48, 0x88, 0x98, 0x498, 0x4A8
B_WRAP, B_REGION, B_GOOD, B_ORIGIN, B_LL, B_FORCED, B_SF = 0x4BE, 0x4C0, 0x540, 0x5C0, 0x600, 0x610, 0x620
B_ZERO_AT, B_ZERO_DIR, B_KNOB_COUNTS, B_KNOB_SPEED = 0x4B8, 0x4BC, 0x720, 0x722   # the Slip knob's (clipwin_turn)
B_ZERO_SLOW = 0x4BD                                  # ...the arrival on 0 was slow (the long hold)
B_LLV, B_LLC = 0x723, 0x733                          # Loop Len as last polled, and polls since it changed
B_FLEN = 0x744                                       # fw_src_len at each pad's last recompute (the Waveform's length)
B_FIT, B_PFIT, B_FON, B_ABEATS, B_ALEN, B_BPM, B_ENGINE = 0x784, 0x794, 0x7A4, 0x7B4, 0x7D4, 0x814, 0x854   # Fit's
B_FADE = 0x858                                       # Loop Fade as taken with the region
B_FIN, B_WRAPPED = 0x878, 0x888                      # the slots that get their fade-in back, the wraps just made
B_ABARS = 0x898                                      # 1: Auto's count is Auto (Bars)', 0: Auto (Beats)'
B_SIZE = 0x8A8                                       # sizeof(struct cw_bank)
B_BYTES = 0x1000                                     # what master.c's block gives it (0x800 before Fit)
CW_MAGIC = 0x43574E42
HEAP = 0xC1000000
ARR = 0x24072000                                     # the stores' entry arrays, 0x100 a pad
N = 128
RAMP = 2.0 ** -20
CTOR, PSET, BLOCKM, ADVANCE = 0x080640D0, 0x08067648, 0x08068C64, 0x080696D8
H_CTOR, RECOMPUTE = 0x08055450, 0x08064A94
PREFETCH, SRC_LEN, FETCH, FETCH2 = 0x0806375C, 0x080636F0, 0x08063634, 0x08063608
SITE_H1, SITE_H1P, SITE_READ, SITE_MIX_L, SITE_MIX_R = 0x0806578C, 0x0806541A, 0x08066622, 0x080666E2, 0x080666FA
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def info(text):
    print("     " + text)


def maps(m):
    """what the class-B code and the cave touch beyond emu.py's map: ITCM/DTCM/SRAM, backup SRAM + RCC, WWDG, SDRAM"""
    for a, n in ((0x00000000, 0x10000), (0x20000000, 0x80000), (0x30000000, 0x48000), (0x38000000, 0x10000),
                 (0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1800000)):
        m.uc.mem_map(a, n)


def sdram(m, on=True):
    m.w32(PMEM, BLOCK if on else 0)
    m.w32(PCHECK, (BLOCK ^ KEY) if on else 0)


def store(m, q, vals):
    """the app's settings store of pad q (row q // 4, col q % 4): {id: value}. The Slip row's value is the content's
    shift, + = ahead (clockwise on the knob, like a CDJ jog), the number every check below reasons in."""
    return store_raw(m, q, vals)


def store_raw(m, q, vals):
    """the app's settings store of pad q, values as the app keeps them"""
    rows = sorted(vals.items())
    at = ARR + q * 0x100
    m.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (q // 4) * 0xF0 + (q % 4) * 0x30
    m.w32(s + 4, at)
    m.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def slips(m, d):
    for q in range(16):
        store(m, q, {0x4: 500, P_SLIP: d.get(q, 0)})


def u32(m, a):
    return m.r32(a) & 0xFFFFFFFF


def bank_slip(m, q):
    return m.r32(BANK + B_SLIP + 4 * q)


def bank_valid(m, q):
    return m.r8(BANK + B_VALID + q)


L_SIZE = 16                                          # struct cw_latch: rs, vlen, delta, len


def latch(m, q, k):
    """(rs, vlen, delta)"""
    return struct.unpack("<3i", m.uc.mem_read(BANK + B_LATCH + (q * 4 + k) * L_SIZE, 12))


def made_for(m, q, k):
    """the file length a latch was made for"""
    return m.r32(BANK + B_LATCH + (q * 4 + k) * L_SIZE + 12)


def slip_f(slip, length, clip):
    return (slip * length // clip) % length


# ====================================================================================================== 1. the image
def branch(at, data=img):
    """target of the 4-byte bl / b.w at `at`, and which one it is"""
    h1, h2 = struct.unpack_from("<HH", data, at - BASE)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    off -= (1 << 25) if s else 0
    kind = "bl" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0xD000 else "b.w" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0x9000 else "?"
    return kind, at + 4 + off


cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def code(name, n):
    a = S[name]
    return [(i.address, i.mnemonic, i.op_str) for i in cs.disasm(img[a - BASE:a - BASE + n], a)]


sites = {"H1 (segment start, FUN_08065550)": (0x0806578C, PREFETCH, "clipwin_seg_start_b"),
         "H1' (slice segment start, FUN_08065290)": (0x0806541A, PREFETCH, "clipwin_slice_start_b"),
         "H3 (the recompute's first length: Beat Count Auto, frames per step)": (0x08064B2C, SRC_LEN, "clipwin_len_recompute_b"),
         "H3 (the recompute's second length: the file tempo; a clip of one step timed by the clip)": (0x08064C5A, SRC_LEN, "clipwin_len_steps_b"),
         "H3 (FUN_08065550's length > 0 check)": (0x0806561E, SRC_LEN, "clipwin_len_b"),
         "H3 (the last step's end)": (0x08065690, SRC_LEN, "clipwin_len_end_b"),
         "H3' (the synced wrap's recompute)": (0x08066FAC, RECOMPUTE, "clipwin_wrap_b"),
         "H3' (the unsynced wrap's recompute)": (0x08066E9E, RECOMPUTE, "clipwin_wrap_free_b"),
         "F (set-value text, FUN_080b0728)": (0x080B0746, 0x080B0528, "clipwin_format"),
         "F (type-1 turn text)": (0x080B0E18, 0x080B0528, "clipwin_format"),
         "K (type-1 turn stepper)": (0x080B0DDE, 0x080B0B74, "clipwin_turn"),
         "H5 (the render's playhead message, 0x4a)": (0x080668FC, 0x0804F504, "clipwin_playhead_b"),
         "W (the Waveform's Clip bind block, its last unbind: BR)": (0x080A582A, 0x080A7EE0, "clipwin_bind"),
         "W (FUN_080a53a2: the position knobs at every bind and zoom change)": (0x080A53B0, 0x080A52C4, "clipwin_zoom"),
         "W (the Waveform refresh's Clip case: the slice markers)": (0x080A5B0E, 0x080C6E8C, "clipwin_wave"),
         "W (the waveform's tick, after it placed the playhead line)": (0x080C6DCA, 0x080C6ACC, "clipwin_line")}
for what, (at, was, now) in sites.items():
    check(f"{what} at {at:#010x}: stock 'bl {was:#010x}' is now 'bl {now}'",
          branch(at, stock) == ("bl", was) and branch(at) == ("bl", S[now]), (branch(at, stock), branch(at)))
check("H2: the segment reader's call at 0x08066622 is still JOEBOX's 'bl clip_read_b' (stock: bl 0x080662e4)",
      branch(0x08066622, stock) == ("bl", 0x080662E4) and branch(0x08066622) == ("bl", S["clip_read_b"]))
c = code("clip_read_b", 8)
check("clip_read_b: 'add.w r1, fp, #0x14c' then 'b.w clipwin_read' (was b.w clip_read)",
      [x[1] for x in c] == ["add.w", "b.w"] and c[0][2] == "r1, fp, #0x14c" and branch(c[1][0]) == ("b.w", S["clipwin_read"]), c)
for thunk, slot, target in (("clipwin_seg_start_b", "#0x20", "clipwin_seg_start"), ("clipwin_slice_start_b", "#4", "clipwin_slice_start")):
    c = code(thunk, 8)
    check(f"{thunk}: r2 = the slot at [sp, {slot}], r3 = r4 (the pad), then b.w {target}",
          [(x[1], x[2]) for x in c[:2]] == [("ldr", f"r2, [sp, {slot}]"), ("mov", "r3, r4")] and branch(c[2][0]) == ("b.w", S[target]), c)
for thunk, site in (("clipwin_len_recompute_b", 1), ("clipwin_len_b", 0), ("clipwin_len_end_b", 2)):
    c = code(thunk, 8)
    check(f"{thunk}: r1 = r4 (the pad), r2 = site {site}, then b.w clipwin_len (r0, the source, as the caller set it)",
          [(x[1], x[2]) for x in c[:2]] == [("mov", "r1, r4"), ("movs", f"r2, #{site}")] and branch(c[2][0]) == ("b.w", S["clipwin_len"]), c)
c = code("clipwin_len_steps_b", 10)
check("clipwin_len_steps_b: r1 = r4 (the pad), r2 = site 3, r3 = r9 (the clip in output samples at 0x08064c5a), then b.w "
      "clipwin_len", [(x[1], x[2]) for x in c[:3]] == [("mov", "r1, r4"), ("movs", "r2, #3"), ("mov", "r3, sb")]
      and branch(c[3][0]) == ("b.w", S["clipwin_len"]), c)
c = code("clipwin_playhead_b", 8)
check("clipwin_playhead_b: r2 = r6 (the pad), r3 = fp (the slot of the segment just read), then b.w clipwin_playhead "
      "(r0 the UI's queue, r1 the message, as the render set them)",
      [(x[1], x[2]) for x in c[:2]] == [("mov", "r2, r6"), ("mov", "r3, fp")] and branch(c[2][0]) == ("b.w", S["clipwin_playhead"]), c)
c = code("clipwin_wrap_b", 6)
c2 = code("clipwin_wrap_free_b", 6)
check("clipwin_wrap_b: r2 = sp + 0x58 (the render's tick of the next pass), clipwin_wrap_free_b: r2 = 0; then b.w clipwin_wrap "
      "(r0, r1 as the caller set them)", [(x[1], x[2]) for x in c[:1]] == [("add", "r2, sp, #0x58")] and branch(c[1][0]) == ("b.w", S["clipwin_wrap"])
      and [(x[1], x[2]) for x in c2[:1]] == [("movs", "r2, #0")] and branch(c2[1][0]) == ("b.w", S["clipwin_wrap"]), (c, c2))
# the stock facts the two thunks rely on: r9 at 0x08064c5a is the clip in output samples ([sp + 0x20], FUN_08070420's
# output, loaded at 0x08064bac on every path, the Beat Count one through 0x08064e58), and the render's tick of the next
# pass is at [sp + 0x58] when it calls the recompute at the synced wrap (stored at 0x08064f2e/32, snapped at 0x08066f92/6)
words = lambda a, n: struct.unpack_from(f"<{n}H", stock, a - BASE)
check("stock: 'ldr.w r9, [sp, #0x20]' at 0x08064bac (after FUN_08070420 at 0x08064b9e and 0x08064e54, whose output is "
      "[sp + 0x20]); nothing between it and 0x08064c5a writes r9 or [sp + 0x20]; the synced wrap stores the tick at "
      "[sp + 0x58] (0x08066f2e, 0x08066f92, 0x08066f96) and calls the recompute with sp unchanged",
      [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08064BAC - BASE:0x08064BB0 - BASE], 0x08064BAC)] == [("ldr.w", "sb, [sp, #0x20]")]
      and not any((not i.mnemonic.startswith(("str", "vstr", "cmp")) and i.op_str.split(",")[0].strip("{ ") == "sb") or "sb" in i.op_str and
                  i.mnemonic.startswith("pop") or i.mnemonic.startswith(("str", "vstr")) and "[sp, #0x20]" in i.op_str
                  for i in cs.disasm(stock[0x08064BB0 - BASE:0x08064C5A - BASE], 0x08064BB0))
      and sum(1 for _ in cs.disasm(stock[0x08064BB0 - BASE:0x08064C5A - BASE], 0x08064BB0)) > 50
      and [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08066F2E - BASE:0x08066F36 - BASE], 0x08066F2E)] == [("str.w", "r8, [sp, #0x58]"), ("str.w", "sb, [sp, #0x5c]")]
      and [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08066F92 - BASE:0x08066F9A - BASE], 0x08066F92)] == [("strd", "r0, r3, [sp, #0x58]"), ("strd", "r4, r2, [sp, #0x58]")]
      and not any(i.mnemonic in ("push", "pop", "sub", "add") and "sp" in i.op_str.split(",")[0] for i in cs.disasm(stock[0x08066F9A - BASE:0x08066FAC - BASE], 0x08066F9A)))
sizes = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", "out/cave.elf"], capture_output=True,
                                                                    text=True, check=True).stdout.splitlines() if len(l.split()) == 4}
duck = code("duck_block", sizes["duck_block"])
order = [int(x[2].lstrip("#"), 16) for x in duck if x[1] == "bl"]
tail = img[S["duck_block"] - BASE:S["duck_block"] - BASE + sizes["duck_block"]]
at_tick = [i for i, x in enumerate(duck) if x[1] == "bl" and int(x[2].lstrip("#"), 16) == S["clipwin_tick"]] or [1]
r4_writes = [x for x in duck[:at_tick[0]] if x[2].split(",")[0].strip() == "r4" and not x[1].startswith(("str", "cmp", "tst"))]
check("duck_block: lfo_tick, insert_tick, then clipwin_tick (once a block, before the pads) with r0 = the engine (duck_block's "
      "own r0, kept in r4: 'mov r4, r0' is the only write to r4 before it), then the tail call into the engine's control tick (0x08053164)",
      order[-3:] == [S["lfo_tick"], S["insert_tick"], S["clipwin_tick"]] and order.count(S["clipwin_tick"]) == 1
      and struct.pack("<I", 0x08053165) in tail and duck[at_tick[0] - 1][1:] == ("mov", "r0, r4")
      and [x[1:] for x in r4_writes] == [("mov", "r4, r0")], ([hex(t) for t in order], duck[at_tick[0] - 1], r4_writes))
POS_ROWS = (P_REGION, P_SLIP, P_LOOPLEN, P_FIT, P_FADE)   # the Clip Pos page's slots 5 .. 9
for page in (0x080EF990, 0x080EF288):
    got = struct.unpack_from("<36H", img, page - BASE)
    check(f"Clip Pos page at {page:#010x}: Loop Mode, Beat Count, Quant Size, Sync, Region (0x1c8), Slip (0x1c9), Loop Len "
          f"(0x1ca), Fit (0x1cb), stock's Loop Fade (0xfa), then {32 - len(POS_ROWS)} empty slots",
          got == (0x8D, 0xD2, 0x47, 0x94) + POS_ROWS + (0,) * (32 - len(POS_ROWS))
          and struct.unpack_from("<36H", stock, page - BASE) == (0x8D, 0xD2, 0x47, 0x94) + (0,) * 32, [hex(x) for x in got[:10]])
touched = {"FUN_08065550": (0x08065550, 936, [0x0806561E, 0x08065690, 0x0806578C]), "FUN_08065290": (0x08065290, 688, [0x0806541A]),
           "FUN_08064a94 (recompute)": (0x08064A94, 0x3C8, [0x08064B2C, 0x08064C5A]),
           "FUN_080667b8 (render; filter.py's filter_voice_b at 0x080669d6)": (0x080667B8, 0x860, [0x080668FC, 0x080669D6, 0x08066E9E, 0x08066FAC]),
           "FUN_08066454": (0x08066454, 856, [0x08066622]), "FUN_080662e4 (stock clip reader)": (0x080662E4, 368, []),
           "FUN_080b0728": (0x080B0728, 36, [0x080B0746]), "FUN_080b0d54": (0x080B0D54, 772, [0x080B0DDE, 0x080B0E18]),
           "FUN_080a54a0 (the Waveform setup; slice.py's four Slicer hooks in it too)":
               (0x080A54A0, 0x6F0, [0x080A582A, 0x080A5B0E, 0x080A58E6, 0x080A58F2, 0x080A58FE, 0x080A5B64]),
           "FUN_080a53a2": (0x080A53A2, 0x16, [0x080A53B0]),
           "the Clip Pos page": (0x080EF990, 72, [0x080EF998 + 2 * i for i in range(len(POS_ROWS))]),
           "its class-0x4c copy": (0x080EF288, 72, [0x080EF290 + 2 * i for i in range(len(POS_ROWS))])}
for name, (start, size, at) in touched.items():
    allowed = {a + i for a in at for i in range(4 if a < 0x080EF000 else 2)}
    diff = {start + i for i in range(size) if img[start - BASE + i] != stock[start - BASE + i]}
    check(f"{name}: no stock byte changes outside the hook sites ({', '.join(hex(a) for a in at) or 'none'})",
          diff <= allowed and (not at or diff), sorted(hex(a) for a in diff - allowed))

# ---- master_alloc: the bank is cleared at every boot and fits the block
maps(e)
allocs = []
e.stub(0x0806AA80, lambda: allocs.append(("line", e.arg(0), e.arg(1))))
e.stub(0x0804436C, lambda: allocs.append(("perm", e.arg(0))), value=BLOCK)
e.w32(BANK, CW_MAGIC)
e.call("master_alloc", 0x24076000, 192000)
e.meter_up()
check(f"master_alloc: one 0x84900-byte block, cw_bank's {B_BYTES:#x} bytes at its end (+0x83900; it uses {B_SIZE:#x}), its "
      "magic cleared each boot",
      allocs[-1] == ("perm", 0x84900) and BANK + B_BYTES == BLOCK + 0x84900 and u32(e, BANK) == 0, (allocs, hex(u32(e, BANK))))
del e.stubs[0x0806AA80], e.stubs[0x0804436C]

# ====================================================================================================== 2. registration
regs = []


lists = {}


def registrar(m, table):
    """the stock pad-parameter registrar run whole; every registration recorded at the one writer (FUN_0808c0a8), and
    each list's entry names at the list registrar (FUN_0808c0d8: r3 names, [sp] count) into `lists`"""
    out = []

    def names():
        sp = m.uc.reg_read(UC_ARM_REG_SP)
        lists[m.arg(1)] = [m.cstr(u32(m, m.arg(3) + 4 * i)) for i in range(m.r32(sp))]
    m.uc.hook_add(UC_HOOK_CODE, lambda *a: names(), begin=0x0808C0D8, end=0x0808C0D8)

    def write():
        a = m.arg(1)
        pid, typ = m.r16(a), m.r8(a + 2)
        lab, lo, hi, xml = u32(m, a + 4), m.r32(a + 0x10), m.r32(a + 0x14), u32(m, a + 0x18)
        out.append((pid, typ, m.cstr(lab) if lab else None, lo, hi, m.cstr(xml) if xml else None))
    m.uc.hook_add(UC_HOOK_CODE, lambda *a: write(), begin=0x0808C0A8, end=0x0808C0A8)
    m.stub(0x0804436C, value=table)
    m.call(0x0808C158, 0, count=20_000_000)
    del m.stubs[0x0804436C]
    return out


TABLE = 0x24040000
regs = registrar(e, TABLE)
st_m = Emu(STOCK, "out/cave.elf")
maps(st_m)
stock_regs = registrar(st_m, TABLE)
ours = [r for r in regs if r[0] == P_SLIP]
check("the patched registrar registers 0x1c9 once: 'Slip:', type 1 (int), -3840 .. 3840, saved as 'clipslip'",
      ours == [(P_SLIP, 1, "Slip:", -3840, 3840, "clipslip")], ours)
region_reg = [r for r in regs if r[0] == P_REGION]
list_type = {r[1] for r in regs if r[0] == 0xF1}                # Fidelity, a stock-registrar list (filter.c)
check(f"... and 0x1c8 once, before it: 'Region:', a list (type {region_reg[0][1] if region_reg else None}, as Fidelity's) of "
      f"{lists.get(P_REGION)}, saved as 'clipregion'", len(region_reg) == 1 and region_reg[0][2] == "Region:"
      and region_reg[0][5] == "clipregion" and {region_reg[0][1]} == list_type and lists.get(P_REGION) == ["Auto", "File", "Loop"]
      and regs.index(region_reg[0]) < regs.index(ours[0]), (region_reg, list_type, lists.get(P_REGION)))
ll_reg = [r for r in regs if r[0] == P_LOOPLEN]
LL_NAMES = ["Off", "1/16", "1/8", "1/4", "1/2", "1 bar", "2 bars", "4 bars"]
check(f"... and 0x1ca once, after Slip: 'Loop Len:', a list of {lists.get(P_LOOPLEN)} (stock's own strings), saved as "
      "'cliplooplen'", len(ll_reg) == 1 and ll_reg[0][2] == "Loop Len:" and ll_reg[0][5] == "cliplooplen"
      and {ll_reg[0][1]} == list_type and lists.get(P_LOOPLEN) == LL_NAMES and regs.index(ll_reg[0]) > regs.index(ours[0]),
      (ll_reg, lists.get(P_LOOPLEN)))
fit_reg = [r for r in regs if r[0] == P_FIT]
check(f"... and 0x1cb once, after Loop Len: 'Fit:', a list of {lists.get(P_FIT)} (stock's own strings but the two Autos, "
      "'3 beats' and '6 beats'), saved as 'clipfit'", len(fit_reg) == 1 and fit_reg[0][2] == "Fit:" and fit_reg[0][5] == "clipfit"
      and {fit_reg[0][1]} == list_type and lists.get(P_FIT) == FIT_NAMES and regs.index(fit_reg[0]) > regs.index(ll_reg[0]),
      (fit_reg, lists.get(P_FIT)))
check("the labels fit the screen (<= 9 characters)", ours and len(ours[0][2]) <= 9 and region_reg and len(region_reg[0][2]) <= 9
      and ll_reg and len(ll_reg[0][2]) <= 9 and fit_reg and len(fit_reg[0][2]) <= 9)
check("stock registers nothing in 0x1c8 .. 0x1cf; the patched image only 0x1c8, 0x1c9, 0x1ca and 0x1cb there",
      not [r for r in stock_regs if 0x1C8 <= r[0] <= 0x1CF]
      and sorted(r[0] for r in regs if 0x1C8 <= r[0] <= 0x1CF) == [P_REGION, P_SLIP, P_LOOPLEN, P_FIT],
      [hex(r[0]) for r in regs if 0x1C8 <= r[0] <= 0x1CF])
xmls = [r[5] for r in regs if r[5]]
dups = sorted({x for x in xmls if xmls.count(x) > 1})
stock_xmls = [r[5] for r in stock_regs if r[5]]
check("'clipslip', 'clipregion', 'cliplooplen' and 'clipfit' are unique among every registered xml name (and new to the "
      "image)", all(xmls.count(x) == 1 and x not in stock_xmls and x.encode() not in stock
                    for x in ("clipslip", "clipregion", "cliplooplen", "clipfit")))
if dups:
    info(f"xml names registered more than once (stock's own: {sorted({x for x in stock_xmls if stock_xmls.count(x) > 1})}): {dups}")
check(f"the patched registrar still registers stock's {len(stock_regs)} ids under their stock xml names (JOEBOX relabels a few)",
      {(r[0], r[5]) for r in stock_regs} <= {(r[0], r[5]) for r in regs}, sorted({(r[0], r[5]) for r in stock_regs} - {(r[0], r[5]) for r in regs}))

# ---- the type-3 (pad) store built by the stock builder, with lfo_defaults -> insert_defaults -> clipwin_defaults in it
PSTORE, TYPE, PARR = 0x24073000, 0x24073100, 0x24074000
e.uc.mem_write(PSTORE, bytes(0x20))
e.uc.mem_write(TYPE, b"\x03")
e.stub(0x0804436C, lambda: e.uc.mem_write(PARR, bytes(e.arg(0))), value=PARR)
e.call(0x08093F20, PSTORE, TYPE)
del e.stubs[0x0804436C]
count, cap = e.r16(PSTORE + 10), e.r16(PSTORE + 12)
entries = [struct.unpack_from("<HHi", bytes(e.uc.mem_read(PARR + 8 * i, 8))) for i in range(count)]
ids = [x[0] for x in entries]
check(f"a new pad's store (FUN_08093f20, type 3) holds Region 0 (Auto), Slip 0, Loop Len 0 (Off) and Fit 0 (Off) once each "
      f"({count} of {cap} entries used)",
      all(ids.count(p_) == 1 and entries[ids.index(p_)][2] == 0 for p_ in (P_REGION, P_SLIP, P_LOOPLEN, P_FIT))
      and cap == 96 and count < cap,
      (count, cap, ids[-4:]))

fade_reg = [r for r in regs if r[0] == P_FADE]
check(f"stock's Loop Fade row (0xfa), on the Clip Pos page's slot 9: registered as stock registers it ({fade_reg}), and in a new "
      f"pad's store once (value {entries[ids.index(P_FADE)][2] if P_FADE in ids else None}), so a Clip pad's saves",
      len(fade_reg) == 1 and fade_reg == [r for r in stock_regs if r[0] == P_FADE] and fade_reg[0][3:5] == (0, 1000)
      and ids.count(P_FADE) == 1, (fade_reg, ids.count(P_FADE)))

# ====================================================================================================== the poll (unit)
sdram(e)
e.uc.mem_write(BANK, bytes(B_BYTES))
values = {0: 960, 1: -30, 2: 7, 3: 3839, 4: -3840, 5: 5000, 6: -9999, 9: 1}
for q in range(16):
    store(e, q, {0x4: 500} if q == 7 else {0x4: 500, P_SLIP: values.get(q, 0)})
e.call("clipwin_tick", 0)
check(f"clipwin_tick with a fresh block: the bank is set up (magic '{CW_MAGIC.to_bytes(4, 'big').decode()}') and one pad "
      "polled per call",
      u32(e, BANK) == CW_MAGIC and e.r32(BANK + 4) == 1 and bank_slip(e, 0) == 960 and bank_slip(e, 1) == 0,
      (hex(u32(e, BANK)), e.r32(BANK + 4), bank_slip(e, 0), bank_slip(e, 1)))
# a bank left by another layout (SDRAM keeps its contents through a reset; master_alloc clears only the magic): the
# first call clears all of cw_bank, and nothing past it
e.uc.mem_write(BANK, b"\xa5" * B_BYTES)
e.w32(BANK, CW_MAGIC - 1)
e.call("clipwin_tick", 0)
got = bytes(e.uc.mem_read(BANK, B_BYTES))
check(f"a stale bank (the magic of another layout, every other byte 0xa5): the first call zeroes all {B_SIZE:#x} bytes of "
      f"cw_bank but what that poll wrote (magic, scan 1, pad 1's Slip 960), and leaves the rest of its {B_BYTES:#x} alone",
      u32(e, BANK) == CW_MAGIC and e.r32(BANK + 4) == 1 and bank_slip(e, 0) == 960
      and got[8 + 4:B_SIZE] == bytes(B_SIZE - 12) and got[B_SIZE:] == b"\xa5" * (B_BYTES - B_SIZE),
      (hex(u32(e, BANK)), e.r32(BANK + 4), bank_slip(e, 0), [hex(i) for i in range(12, B_SIZE) if got[i]][:4]))
for _ in range(15):
    e.call("clipwin_tick", 0)
want = [max(-3840, min(3840, values.get(q, 0))) for q in range(16)]
check("sixteen calls read all sixteen pads' stores (row * 0xf0 + col * 0x30), clamped to +-3840; a store without the id reads 0",
      [bank_slip(e, q) for q in range(16)] == want, [bank_slip(e, q) for q in range(16)])

# the guarded drop on a cached pad
UPAD = 0x24060000


def upad(q, cls=0x4C):
    e.uc.mem_write(UPAD, bytes(0xC00))
    e.uc.mem_write(UPAD + 4, bytes([cls]))
    e.w32(UPAD + 0x18, (q // 4) << 8 | q % 4)
    for k, (act, done, delay, first) in enumerate(((1, 0, 500, 0), (1, 0, 500, 1), (1, 0, 0, 0), (0, 0, 500, 0))):
        b = UPAD + 0x30 + k * 0x70
        e.uc.mem_write(b, bytes([act, done]))
        e.w32(b + 0x20, delay)
        e.uc.mem_write(b + 0x3C, bytes([first]))
    e.w32(BANK + B_PAD + 4 * q, UPAD)


def done():
    return [e.r8(UPAD + 0x31 + k * 0x70) for k in range(4)]


def tick_until(q):
    for _ in range(16):
        e.call("clipwin_tick", 0)
        if (e.r32(BANK + 4) - 1) & 15 == q:
            return


upad(9)
store(e, 9, {0x4: 500, P_SLIP: 480})
tick_until(9)
check("a Slip change drops the pad's pending segment (active, not done, delay > 0) and nothing else: not a pending "
      "launch (+0x3c set), not the sounding one (delay 0), not an inactive slot", done() == [1, 0, 0, 0] and bank_slip(e, 9) == 480, done())
upad(9)
tick_until(9)
check("the same value polled again: no drop", done() == [0, 0, 0, 0], done())
for what, cls, cell_q in (("a cached object that is not a class-B pad", 0x48, 9), ("a cached pad whose cell moved", 0x4C, 10)):
    upad(9, cls)
    e.w32(UPAD + 0x18, (cell_q // 4) << 8 | cell_q % 4)
    store(e, 9, {0x4: 500, P_SLIP: -480 if cell_q == 9 else 300})
    tick_until(9)
    check(f"{what}: the new value is taken, nothing is dropped", done() == [0, 0, 0, 0] and bank_slip(e, 9) in (-480, 300), done())
sdram(e, False)
e.uc.mem_write(BANK, bytes(16))
e.call("clipwin_tick", 0)
check("no SDRAM block (master_alloc did not run): clipwin_tick writes nothing", bytes(e.uc.mem_read(BANK, 16)) == bytes(16))


# ====================================================================================================== the rig
POS, SID, AT, FET = 2, 6, 7, 12          # a read row: block, slot, POSition (virtual), n, rate, frac, Segment ID, the
#                                         sample it sounds AT; then return, used, frac, buffer, its FETches, clip_read ran


def no_bank2(m, entered):
    """bank 2's header wiped on emulator m before its first b2_live() (which caches the verdict for the boot), and every
    entry into a bank-2 cw_* function appended to `entered`"""
    m.uc.mem_write(0x08100000, bytes(16))
    for fn in CW_FUNCS:
        m.uc.hook_add(UC_HOOK_CODE, lambda *a, fn=fn: entered.append(fn), begin=S[fn] & ~1, end=S[fn] & ~1)


CW_FUNCS = sorted(n for n in S if n.startswith("cw_") and 0x08100000 <= S[n] < 0x08200000)


class Rig:
    """The class-B pad process block by block (notes/re/a2's Rig, with a1's Rig2 input-bank buffers), on an Emu.

    One pad, one engine; pre_block runs where duck_block would (clipwin_tick), then the block method, then the clock
    advance. Logs: reads at the segment reader's call (block, slot, virtual position, n, rate, frac, then the result:
    return, used, frac, buffer, the fetches made inside it, whether filter.c's clip_read ran), fetches, prefetches,
    every segment start (H1 and H1'), each segment's mixed samples, the summed output, the messages to the app.
    h: the cell's class-H object too (real ctor, linked at pad + 8 as the graph builder links it; its block method runs
    after the pad's and reads the same queue, so loop points posted there land in it, notes/re/x3). bypass: every
    clipwin hook taken out at run time; region_off: only Region's (H3, H3'), which leaves Slip. bank2=False: bank
    2's header wiped before anything runs, so the first b2_live() (the first poll, or the first recompute) says no and
    keeps saying it, as on a unit without this build's BBEXTRA.BIN; every entry into a cw_* function is counted in
    b2_entered."""

    def __init__(self, frames=96000, src_rate=48000, bpm=120.0, stereo=False, cell=0, image=IMAGE, block=True,
                 bypass=False, dc=False, h=False, region_off=False, bank2=True):
        self.m = m = Emu(image, "out/cave.elf")
        uc = self.uc = m.uc
        maps(m)
        self.b2_entered = []
        if not bank2:
            no_bank2(m, self.b2_entered)
        self.patched = image == IMAGE
        self.heap = HEAP
        self.len, self.src_rate, self.stereo, self.dc = frames, src_rate, stereo, dc
        self.q = (cell >> 8 & 3) * 4 + (cell & 3)
        sdram(m, block)
        m.stubs[0x0804436C] = lambda: m.ret(self.alloc(m.arg(0)))
        m.stub(0x08043DE4, value=0)
        self.src = self.alloc(0x40)
        m.w32(self.src + 0x24, 0x1234)
        uc.mem_write(self.src + 0x1C, bytes([int(stereo)]))
        m.stubs[SRC_LEN] = lambda: m.ret(self.len)
        m.stubs[0x0806377C] = lambda: m.ret(self.src_rate)
        m.stub(0x0806371C, value=1)
        self.prefetches, self.fetches, self.hints, self.reading = [], [], [], None
        m.stub(PREFETCH, self._prefetch, value=0)
        m.stub(FETCH, self._fetch_mono, value=0)
        m.stub(FETCH2, self._fetch_stereo, value=0)
        self.engine = eng = self.alloc(0x30000, 0x100)
        self.ctx = ctx = eng + 0x128E0
        m.w32(ctx, eng)
        uc.mem_write(eng + 0x18, struct.pack("<f", bpm))
        uc.mem_write(eng + 0x38, b"\x01")
        self._buffers()
        self.pad = pad = self.alloc(3000)
        m.call(CTOR, pad)
        m.w32(pad + 0x24, self.src)
        m.w32(pad + 0x18, cell)
        uc.mem_write(pad + 0xB79, b"\x01")
        self.h = None
        if h:
            self.h = H = self.alloc(0x5C4)
            m.call(H_CTOR, H)
            m.w32(H + 0x18, cell)
            shared = self.alloc(0x10)                         # engine + 0x2c74: {key map, source entries}
            m.w32(shared + 4, self.alloc(0x7500))
            m.w32(H + 0x20, shared)
            m.w32(pad + 8, H)
        self.queue = ctx + {0x400: 4, 0x401: 0x608}.get(cell, ((cell >> 8 & 0xFF) + ((cell & 0xFF) + (cell >> 16) * 4) * 4 + 2) * 0x604 + 4)
        self.block, self._S0 = 0, 0
        self.posted, self.reads, self.mix, self.out, self.made = [], [], [], [], []
        self.pre_block = None
        self.sid, self.nsid, self.cur, self.in_clip_read = {}, 0, None, False
        for a, fn in ((SITE_H1, self._on_h1), (SITE_H1P, self._on_h1p), (SITE_READ, self._on_read),
                      (SITE_READ + 4, self._on_read_ret), (SITE_MIX_L, lambda: self._on_mix(0)),
                      (SITE_MIX_R, lambda: self._on_mix(1))):
            uc.hook_add(UC_HOOK_CODE, lambda u, a_, s_, d_, fn=fn: fn(), begin=a, end=a)
        if self.patched:
            uc.hook_add(UC_HOOK_CODE, lambda *a: setattr(self, "in_clip_read", True), begin=S["clip_read"], end=S["clip_read"])
        go = lambda target: (lambda: uc.reg_write(UC_ARM_REG_PC, target | 1))
        if bypass and self.patched:
            m.stubs[S["clipwin_seg_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_slice_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_read"]] = go(S["clip_read"])
            m.stub(S["clipwin_tick"])
            m.stubs[S["clipwin_playhead_b"]] = go(0x0804F504)
        if (bypass or region_off) and self.patched:
            for t in ("clipwin_len_recompute_b", "clipwin_len_steps_b", "clipwin_len_b", "clipwin_len_end_b"):
                m.stubs[S[t]] = go(SRC_LEN)
            for t in ("clipwin_wrap_b", "clipwin_wrap_free_b"):
                m.stubs[S[t]] = go(RECOMPUTE)

    def alloc(self, n, align=8):
        a = (self.heap + align - 1) & ~(align - 1)
        self.heap = a + n
        self.uc.mem_write(a, bytes(n))
        return a

    def _prefetch(self):
        pos = struct.unpack("<i", struct.pack("<I", self.m.arg(1)))[0]
        self.prefetches.append((self.block, pos))
        if self.reading is not None:                          # a hint made inside a segment read (H2): whose read
            self.hints.append((self.block, pos, self.reading))

    def _data(self, pos, n, right=False):
        q = np.arange(pos, pos + n, dtype=np.int64)
        v = np.ones(n) if self.dc else (q + 1) * RAMP * (-1.0 if right else 1.0)
        return np.where((q >= 0) & (q < self.len), v, 0.0).astype(np.float32).tobytes()

    def _fetch_mono(self):
        m = self.m
        dst, n, pos = m.arg(1), m.arg(2), struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(dst, self._data(pos, n))

    def _fetch_stereo(self):
        m = self.m
        n, pos = m.arg(3), m.r32(self.uc.reg_read(UC_ARM_REG_SP))
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(m.arg(1), self._data(pos, n))
        self.uc.mem_write(m.arg(2), self._data(pos, n, True))

    def _buffers(self):
        def mk(addr, cap=N):
            l, r = self.alloc(cap * 4), self.alloc(cap * 4)
            self.uc.mem_write(addr, struct.pack("<IIIIBBxx", cap, 0, l, r, 1, 0))
            return l
        for k in range(3):
            mk(self.ctx + 0x151FC + k * 0x14)
        self.buses = [(self.ctx + 0x150E4 + k * 0x14, mk(self.ctx + 0x150E4 + k * 0x14)) for k in range(16)]
        for k, cap in enumerate((N, 0x400, N, N)):         # Rig2: the input bank (the reader's scratch is #1)
            mk(self.ctx + 0x1583C + k * 0x14, cap)

    def i64(self, a):
        return struct.unpack("<q", self.uc.mem_read(a, 8))[0]

    @property
    def S(self):
        return self.i64(self.engine)

    def goto(self, at):
        e_ = self.engine
        self.uc.mem_write(e_ + 8, bytes(16))
        self.uc.mem_write(e_, struct.pack("<q", at - N))
        self.m.call(ADVANCE, e_, N)

    def set_bpm(self, bpm):
        """a tempo change as a re-anchored tempo state looks: origin = (ticks now, samples now)"""
        self.uc.mem_write(self.engine + 8, struct.pack("<qq", self.i64(self.engine + 0x30), self.S))
        self.uc.mem_write(self.engine + 0x18, struct.pack("<f", bpm))

    def post(self, mtype, offset=0, w8=0, wc=0, w10=0, w14=0):
        n = self.m.r32(self.queue + 0x600)
        self.uc.mem_write(self.queue + 0x18 * n, struct.pack("<BxxxIIIII", mtype, offset, w8, wc, w10 & 0xFFFFFFFF, w14))
        self.m.w32(self.queue + 0x600, n + 1)

    def cell(self):
        return u32(self.m, self.pad + 0x18)

    def note_on(self, note=60, vel=100):
        self.post(2, 0, 0, note, vel)

    def param(self, pid, value):
        self.post(0x39, 0, self.cell(), pid, value)

    def params(self, beats=4, quant=3, sync=3, loop=1, launch=2, mode=1):
        for pid, v in ((0x8B, mode), (0x93, launch), (0x8D, loop), (0xD2, beats), (0x47, quant), (0x94, sync)):
            msg = self.alloc(0x18)
            self.uc.mem_write(msg, struct.pack("<BxxxIIII", 0x39, 0, self.cell(), pid, v & 0xFFFFFFFF))
            self.m.call(PSET, self.pad, self.engine, msg, self.ctx)

    def markers(self, frames):
        self.post(0x3C, 0, self.cell(), 0, 1000)
        for f in frames:
            self.post(0x3C, 0, self.cell(), f, 1)

    def _new(self, k, how, step, start, stock_pos, launch=0):
        self.nsid += 1
        self.sid[k] = self.nsid
        ours = self.patched and self.q < 16
        p = self.pad
        self.made.append(dict(sid=self.nsid, k=k, how=how, step=step, start=start, block=self.block, stock_pos=stock_pos, launch=launch,
                              valid_before=(bank_valid(self.m, self.q) >> k) & 1 if self.patched else 0,
                              h1_before=(self.m.r8(BANK + B_H1 + self.q) >> k) & 1 if ours else 0,
                              prefetch_at=len(self.prefetches),
                              # what H1 has to go on: the pad's steps (final here) and the bank's Loop Len
                              tps=self.i64(p + 0x208), n=u32(self.m, p + 0x210),
                              fps=struct.unpack("<f", bytes(self.uc.mem_read(p + 0x1FC, 4)))[0],
                              ll=self.m.r8(BANK + B_LL + self.q) if ours else 0,
                              origin=self.m.r32(BANK + B_ORIGIN + 4 * self.q) if ours else 0))

    def _on_h1(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 0x20)
        self._new(k, "H1", uc.reg_read(UC_ARM_REG_R5), self.i64(self.pad + 0x38 + k * 0x70), uc.reg_read(UC_ARM_REG_R1),
                  uc.reg_read(UC_ARM_REG_R8))

    def _on_h1p(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 4)
        self._new(k, "H1'", None, None, uc.reg_read(UC_ARM_REG_R1))

    def _on_read(self):
        uc, m = self.uc, self.m
        k = (uc.reg_read(UC_ARM_REG_R4) - self.pad - 0x30) // 0x70
        sp = uc.reg_read(UC_ARM_REG_SP)
        n = m.r32(sp)
        pos = uc.reg_read(UC_ARM_REG_R2) | uc.reg_read(UC_ARM_REG_R3) << 32
        self.cur = (k, n)
        self._ptrs = [u32(m, sp + o) for o in (4, 8, 0x14)]
        self._f0 = len(self.fetches)
        self.in_clip_read = False
        self.reads.append([self.block, k, pos, n, uc.reg_read(UC_ARM_REG_S0), u32(m, self._ptrs[1]), self.sid.get(k),
                           self._S0 + N - n])
        self.reading = self.sid.get(k)

    def _on_read_ret(self):
        m = self.m
        self.reading = None
        self.reads[-1] += [self.uc.reg_read(UC_ARM_REG_R0)] + [u32(m, p) for p in self._ptrs] + \
            [tuple(self.fetches[self._f0:]), self.in_clip_read]

    def _on_mix(self, ch):
        if self.cur is None:
            return
        uc = self.uc
        k, n = self.cur
        if ch == 1 or not self.stereo:
            self.cur = None
        cnt = uc.reg_read(UC_ARM_REG_R1)
        v = np.frombuffer(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 4 * cnt)), np.float32).copy()
        self.mix.append((self._S0 + (N - n), self.sid.get(k), ch, v))

    def step_block(self):
        m, uc = self.m, self.uc
        self._S0 = self.S
        if self.pre_block:
            self.pre_block(self)
        z = bytes(N * 4)
        for a, buf in self.buses:
            m.w32(a + 4, 0)
            uc.mem_write(a + 0x10, b"\x01")
            uc.mem_write(buf, z)
        m.call(BLOCKM, self.pad, self.ctx, count=20_000_000)
        acc = np.zeros(N, np.float32)
        for a, buf in self.buses:
            acc += np.frombuffer(bytes(uc.mem_read(buf, N * 4)), np.float32)
        self.out.append(acc)
        q = self.ctx + 0x15238                                # the app queue: log, then drained
        for i in range(m.r32(q + 0x600)):
            b = bytes(uc.mem_read(q + 0x18 * i, 0x18))
            self.posted.append((self.block, b[0], struct.unpack("<5I", b[4:])))
        m.w32(q + 0x600, 0)
        m.w32(self.queue + 0x600, 0)                          # the engine drains the pad queues (FUN_0805f3b8)
        m.call(ADVANCE, self.engine, N)                       # then the clock advance, as at 0x080531e0
        self.block += 1

    def run(self, blocks):
        for _ in range(blocks):
            self.step_block()
        return self

    def seg(self, k):
        b = self.pad + 0x30 + k * 0x70
        return dict(active=self.m.r8(b), done=self.m.r8(b + 1), delay=self.m.r32(b + 0x20), first=self.m.r8(b + 0x3C),
                    step=u32(self.m, b + 0x34))

    def layer(self, L=0):
        b = self.pad + 0x260 + L * 0x410
        return dict(active=self.m.r8(b), launch_tick=self.i64(b + 0x140), armed=self.m.r8(b + 0x148))

    def seam_reads(self):
        return [r for r in self.reads if not r[-1]]


def poll(r):
    r.m.call("clipwin_tick", r.engine, count=20_000_000)


def starts(r):
    """each segment that sounded: (its first sample, step, stock start frame), in order"""
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    return sorted((first[m_["sid"]], m_["step"], m_["start"]) for m_ in r.made if m_["sid"] in first)


def scenario(frames=96000, beats=4, quant=3, sync=3, at=287000, blocks=900, slip=0, others=None, pre=None, setup=None,
             note=60, launch=2, loop=1, region=None, points=None, vals=None, **kw):
    """A Clip pad (Launch Toggle, Loop On) with Slip `slip` (and Region `region`, if given) in its store, the app's other
    pads per `others`; the poll has seen the stores before the note (as on the unit, where the app writes its store
    before it posts). points = (Loop Start, Loop End, Loop Mode): posted to the cell's queue a block before the rest,
    so its class-H object (h, implied) holds them, as the app's posts leave it. vals: more of the pad's store ({id: value},
    e.g. Sync and Loop Len), from the start."""
    if points is not None:
        kw["h"] = True
    r = Rig(frames=frames, **kw)
    d = dict(others or {})
    d[r.q] = slip
    slips(r.m, d)
    if region is not None or vals:
        store(r.m, r.q, {0x4: 500, P_SLIP: slip, **({} if region is None else {P_REGION: region}), **(vals or {})})
    if r.patched:
        for _ in range(16):
            poll(r)

    def pb(rr):
        if rr.patched:
            poll(rr)
        if pre:
            pre(rr)
    r.pre_block = pb
    r.params(beats=beats, quant=quant, sync=sync, launch=launch, loop=loop)
    if r.h:
        r.goto(at - N)
        if points is not None:
            for pid, v in zip((0x91, 0x92, 0x8E), points):
                r.param(pid, v)
        r.step_block()
    if setup:
        setup(r)
    r.goto(at)
    r.note_on(note)
    return r.run(blocks)


def same(a, b, silent=False):
    """everything the two runs did, bit for bit: reads (and their results and fetches), prefetches, mixed output, posts"""
    strip = lambda rs: [x[:SID] + x[AT:-1] for x in rs]            # the segment numbering and clip_read flag aside
    d = dict(reads=strip(a.reads) == strip(b.reads), fetches=a.fetches == b.fetches, prefetches=a.prefetches == b.prefetches,
             out=len(a.out) == len(b.out) and all(np.array_equal(x.view(np.uint32), y.view(np.uint32)) for x, y in zip(a.out, b.out)),
             posted=a.posted == b.posted)
    return all(d.values()) and (silent or len(a.reads) > 0), d


def decode(rd, rr, ch=0):
    """a gain run (source 1.0) and a ramp run of the same scenario -> per sample: summed gain, sounding segments, and
    when one segment sounds, which one and the source frame it plays"""
    a = [x for x in rd.mix if x[2] == ch]
    b = [x for x in rr.mix if x[2] == ch]
    assert len(a) == len(b) and all(x[0] == y[0] and x[1] == y[1] and len(x[3]) == len(y[3]) for x, y in zip(a, b))
    s = np.concatenate([x[0] + np.arange(len(x[3])) for x in a])
    sid = np.concatenate([np.full(len(x[3]), x[1] or 0) for x in a])
    g = np.concatenate([x[3] for x in a]).astype(np.float64)
    v = np.concatenate([y[3] for y in b]).astype(np.float64)
    base = int(s.min())
    idx = s - base
    live = np.abs(g) > 1e-7
    cnt = np.bincount(idx, weights=live.astype(float))
    single = live & (cnt[idx] == 1)
    frame, who = np.full(len(cnt), np.nan), np.zeros(len(cnt), np.int64)
    frame[idx[single]] = (-1.0 if ch else 1.0) * v[single] / g[single] / RAMP - 1
    who[idx[single]] = sid[single]
    return dict(base=base, gain=np.bincount(idx, weights=g), cnt=cnt, frame=frame, sid=who, rig=rr)


def audio(**kw):
    return decode(scenario(dc=True, **kw), scenario(**kw))


def window(ref, cw):
    lo, hi = max(ref["base"], cw["base"]), min(ref["base"] + len(ref["gain"]), cw["base"] + len(cw["gain"]))
    cut = lambda d, key: d[key][lo - d["base"]:hi - d["base"]]
    return lo, {k: (cut(ref, k), cut(cw, k)) for k in ("frame", "gain", "sid")}


def shifted(ref, cw, sf, length, edge=0, since=None):
    """samples where one segment sounds in both runs: max |cw frame - (stock frame + slip_f) mod len| (circular), the
    count of samples off by more than 0.05 frame, and of samples whose summed gain differs. `edge` > 0 leaves out the
    samples within that many frames of the file's ends in either run (the kernel's support: there stock interpolates
    into the silence after the file, the Clip Window into the file's start). `since`: only the samples from there on."""
    lo, w = window(ref, cw)
    fs, fc = w["frame"]
    gs, gc = w["gain"]
    span = lo + np.arange(len(gs)) >= (since if since is not None else lo)
    ok = ~np.isnan(fs) & ~np.isnan(fc) & span
    want = np.mod(fs + sf, length)
    near = lambda f: (f < edge) | (f > length - 1 - edge)
    if edge:
        ok &= ~near(fs) & ~near(want)
    err = np.abs(fc - want)
    err = np.minimum(err, length - err)[ok]
    gdiff = (np.abs(gs - gc) > 1e-6) & span
    if edge:
        gdiff &= ~(near(np.nan_to_num(fs, nan=length / 2)) | near(np.nan_to_num(fc, nan=length / 2)))
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > 0.05).sum()), int(gdiff.sum())


def wraps(d, length):
    """how often the frame played by one segment jumps from the file's end back to its start"""
    f, sid = d["frame"], d["sid"]
    i = np.where(~np.isnan(f[:-1]) & ~np.isnan(f[1:]) & (sid[:-1] == sid[1:]) & (sid[:-1] > 0))[0]
    return int((f[i + 1] - f[i] < -length / 2).sum())


# ====================================================================================================== 3. off = stock
off_cases = [("the matched file (96 000 frames, 4 beats), Quant 1 bar, Sync 1/4", dict(frames=96000, at=287000, cell=0x102)),
             ("a fast file (88 615 frames, fps 22 153.75)", dict(frames=88615, at=287000, cell=0x0)),
             ("88 615 frames, the note 300 samples after the bar", dict(frames=88615, at=288300, cell=0x303)),
             ("Sync None", dict(frames=96000, at=287000, sync=6, cell=0x201))]
for name, sc in off_cases:
    q = (sc["cell"] >> 8) * 4 + (sc["cell"] & 3)
    others = {p: 960 for p in range(16) if p != q}
    cw = scenario(slip=0, others=others, **sc)
    by = scenario(slip=0, others=others, bypass=True, **sc)
    st = scenario(slip=0, image=STOCK, **sc)
    ok1, d1 = same(cw, by)
    ok2, d2 = same(cw, st)
    check(f"Slip 0, {name} (pad {q + 1}; every other pad's Slip 960): each read (position, n, rate, frac, used, buffer, "
          "fetches), prefetch, mixed sample and message identical to the hooks taken out", ok1, d1)
    check("  ...and to the stock 3.1.9 image", ok2, d2)
    check("  ...no latch made, the poll did run", bank_valid(cw.m, q) == 0 and u32(cw.m, BANK) == CW_MAGIC and bank_slip(cw.m, (q + 1) % 16) == 960)
    st_ = starts(cw)
    if "matched" in name:
        check("  stock as measured (notes/re/a2): launch on the bar at 288 000 (+0x140 = 11 520, msg 0x1d), steps at "
              "312 000 / 336 000 / 360 000 on frames 24 000 j, the wrap at 384 000 back to frame 0",
              cw.layer()["launch_tick"] == 11520 and [b for b, t, _ in cw.posted if t == 0x1D] and
              st_[:5] == [(288000, 0, 0), (312000, 1, 24000), (336000, 2, 48000), (360000, 3, 72000), (384000, 0, 0)],
              (cw.layer(), st_[:5]))
    if "fast" in name:
        check("  stock as measured: steps start on (int)(j x 22153.75) = 0, 22 153, 44 307, 66 461, on the same grid",
              st_[:4] == [(288000, 0, 0), (312000, 1, 22153), (336000, 2, 44307), (360000, 3, 66461)], st_[:4])
    if "300" in name:
        check("  stock as measured: a launch 300 samples late starts at once on frame 0 (+0x140 = 11 532), step 1 still "
              "on the grid (312 000)", cw.layer()["launch_tick"] == 11532 and st_[:2] == [(288300, 0, 0), (312000, 1, 22153)],
              (cw.layer(), st_[:2]))
    if "None" in name:
        check("  stock as measured: Sync None, one segment for the whole file, restarted every len - 257 samples",
              st_[:2] == [(288000, 0, 0), (288000 + 96000 - 257, 0, 0)], st_[:3])

# ====================================================================================================== 4. Slip
slip_cases = [("matched 96 000, launch on the bar", dict(frames=96000, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch on the bar", dict(frames=88615, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch 300 samples late", dict(frames=88615, at=288300, blocks=900), (960, -30, 3839)),
              ("16 beats (384 000), Quant 1 beat < Sync 1 bar, note at tick 8 000", dict(frames=384000, beats=16, quant=5, sync=1, at=200000, blocks=1000), (960, -30, 3839)),
              ("fast 88 615, default Sync 1/16", dict(frames=88615, sync=5, at=287000, blocks=900), (960, 7, 3839))]
for name, sc, values in slip_cases:
    sc = dict(sc, cell=0x102)
    ref = audio(**sc)
    clip = sc.get("beats", 4) * 960
    for slip in values:
        cw = audio(slip=slip, **sc)
        sf = slip_f(slip, sc["frames"], clip)
        n, err, bad, gd = shifted(ref, cw, sf, sc["frames"])
        r = cw["rig"]
        h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
        pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
        lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
        check(f"{name}, Slip {slip} (slip_f {sf}): every sounding sample plays (stock frame + slip_f) mod len "
              f"({n} samples, max error {err:.4f} frame), summed gain = stock's at every sample",
              n > 80000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
        if slip:
            wr = wraps(cw, sc["frames"])
            check(f"  H1 latched every segment start ({len(h1)}): slot k from the caller's frame, (0, len, slip_f), and "
                  f"prefetched where it will read; the content wraps inside a segment {wr} time(s), {len(r.seam_reads())} "
                  "block(s) read by clipwin_read's own fetch (across the file end, or within 3 frames of its start)",
                  h1 and pf == [max(0, (m_["start"] + sf) % sc["frames"] - 8) for m_ in h1] and lat and
                  all(x == (0, sc["frames"], sf) for x in lat) and len(r.seam_reads()) >= min(wr, 1),
                  (pf[:4], [m_["start"] for m_ in h1][:4], lat, len(r.seam_reads())))

# more of what stock does around a slipped pad: it keeps doing it, every sample still stock + slip_f
for name, sc, slip in (("a retrigger (Launch Trigger, Quant 1 beat, a second note in step 1): two voices' segments",
                        dict(launch=0, quant=5, pre=lambda rr: rr.note_on() if rr.block == 200 else None), 960),
                       ("a live Sync change (1/4 -> 1/2 in step 1): stock re-grids the playing segment, re-makes the pending one",
                        dict(pre=lambda rr: rr.param(0x94, 2) if rr.block == 265 else None), -30),
                       ("a tempo change (120 -> 126 BPM in step 1)", dict(pre=lambda rr: rr.set_bpm(126.0) if rr.block == 265 else None), 7)):
    sc = dict(sc, cell=0x102, frames=88615)
    ref, cw = audio(**sc), audio(slip=slip, **sc)
    sf = slip_f(slip, 88615, 3840)
    n, err, bad, gd = shifted(ref, cw, sf, 88615)
    launches = sum(1 for m_ in cw["rig"].made if m_["launch"])
    check(f"{name}, Slip {slip}: every sounding sample plays stock + slip_f ({n} samples, max {err:.4f} frame), summed "
          f"gain = stock's ({launches} launch(es))", n > 50000 and err <= 0.02 and bad == 0 and gd == 0
          and launches == (2 if "retrigger" in name else 1), (n, err, bad, gd, launches))
# clip = ticks per step x steps, not Beat Count x 960, where the steps do not divide the clip
r = scenario(frames=1392000, beats=29, sync=1, slip=3840, cell=0x102, blocks=40)
tps, n_ = r.i64(r.pad + 0x208), u32(r.m, r.pad + 0x210)
got = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
check(f"Beat Count 29, Sync 1 bar: {n_} steps of {tps} ticks ({tps * n_}, not 27 840); slip_f = floor(3840 x len / {tps * n_})"
      f" = {slip_f(3840, 1392000, tps * n_)} (README 2.4: the product, as the model)",
      (tps, n_) == (3977, 7) and got and all(x == (0, 1392000, slip_f(3840, 1392000, 27839)) for x in got)
      and slip_f(3840, 1392000, 27839) != slip_f(3840, 1392000, 27840), (tps, n_, got))

# the cave writes nothing in the block but its own bank: every write from clipwin.o's code (its static helpers and
# bank included: the link map gives the object's .text) and clipwin_b2.o's (the latch and the rest of the maths, in
# bank 2), a launch on the seam (Slip 3839) and a live change
w = []
r = Rig(cell=0x102)
cw_code = [(int(l.split()[1], 16), int(l.split()[1], 16) + int(l.split()[2], 16)) for l in open("out/cave.map")
           if l.split()[:1] and l.split()[0].startswith(".text") and l.rstrip().endswith(("out/obj/clipwin.o", "out/obj/clipwin_b2.o"))
           and len(l.split()) == 4]
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size_, v, d: w.append((addr, size_)) if any(
    a <= u.reg_read(UC_ARM_REG_PC) < b for a, b in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
slips(r.m, {6: 3839})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), store(rr.m, 6, {0x4: 500, P_SLIP: -30}) if rr.block == 150 else None)
r.params()
r.goto(287000)
r.note_on()
r.run(300)
hit = {name: any(lo <= a - BANK < hi for a, s in w) for name, lo, hi in (("valid", B_VALID, B_LATCH), ("latch", B_LATCH, B_H1),
                                                                         ("h1", B_H1, B_HINTED), ("hinted", B_HINTED, B_SIZE))}
check(f"in a Slip run, every write clipwin.c makes into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (of the {B_BYTES:#x} "
      f"reserved; valid, latch, h1 and hinted written: {hit})", cw_code and w and all(hit.values())
      and all(BANK <= a and a + s <= BANK + B_SIZE for a, s in w), (cw_code, sorted({hex(a) for a, s in w if not BANK <= a < BANK + B_SIZE})[:4]))

# H2's seam hint (README 2.6): once a segment reads within 16 384 frames of the region end (the hint's sure reach,
# notes/re/a2), clipwin_read hints rs once for that slot; H1 clears the bit at the next latch
for name, sc, exact in (("96 000 frames, Slip 7, Sync 1/4 (the seam mid-step)", dict(frames=96000, slip=7, blocks=1600), True),
                        ("88 615 frames, Slip 960, Sync 1/4 (a step crosses mid-step, the next starts on the seam)",
                         dict(frames=88615, slip=960, blocks=1400), True),
                        ("88 615 frames, Slip 960, Sync 1/16 (steps shorter than the reach)", dict(frames=88615, slip=960, sync=5, blocks=1400), False)):
    r = scenario(cell=0x102, **sc)
    ln, sf = sc["frames"], slip_f(sc["slip"], sc["frames"], 3840)
    near = {x[SID] for x in r.reads if ln - (x[POS] + sf) % ln <= 16384}          # the rule, from each read's real position
    cross = {}
    for x in r.seam_reads():
        cross.setdefault(x[SID], x[0])
    sids = [s for _, _, s in r.hints]
    lead = sorted(max((b - hb for hb, _, _ in r.hints if 0 <= b - hb <= 300), default=-1) for b in cross.values())
    check(f"seam hint, {name}: {len(r.hints)} hint(s) from clipwin_read, all at rs = 0, one per segment, from exactly the "
          f"segments that read within 16 384 frames of the end ({len(near)}){', which are the crossing ones' if exact else ''} "
          f"({len(cross)} crossing in {len(r.made)} segments); every seam read hinted {lead} blocks ahead (>= 100); no other "
          "prefetch than H1's", r.hints and all(p == 0 for _, p, _ in r.hints) and len(set(sids)) == len(sids)
          and set(sids) == near and set(cross) <= near and (not exact or set(cross) == near) and len(cross) >= 2
          and min(lead) >= 100 and len(r.prefetches) == len(r.made) + len(r.hints),
          (r.hints[:6], sorted(near), cross, lead, len(r.prefetches), len(r.made)))
r = scenario(frames=96000, slip=-30, cell=0x102, blocks=40)
seam = [x[0] for x in r.seam_reads()][:1]
info(f"observed: a launch whose slipped content starts near the end (Slip -30: frame 95 250) is hinted at rs only at its "
     f"first read (block {r.hints[0][0] if r.hints else None}; H1's own prefetch at {r.prefetches[0][1]}), "
     f"{seam[0] - r.hints[0][0] if seam and r.hints else None} block(s) before its seam read (block {seam[:1]})")

# ====================================================================================================== 5. live change
for frames in (96000, 88615):
    ref = audio(frames=frames, cell=0x102)
    for slip in (480, -7):
        seen = {}

        def change(rr, slip=slip):
            if rr.block == 265:                               # sample 320 920, inside step 1 (312 000 .. 336 000)
                store(rr.m, 6, {0x4: 500, P_SLIP: slip})
            if "at" not in seen and bank_slip(rr.m, 6) == slip:
                seen["at"] = rr.block
        cw = audio(frames=frames, cell=0x102, pre=change)
        r = cw["rig"]
        sf = slip_f(slip, frames, 3840)
        at = seen.get("at", -1)
        lo, w = window(ref, cw)
        fs, fc = w["frame"]
        gs, gc = w["gain"]
        sid = w["sid"][1]
        newer = np.array([r.made[s - 1]["block"] >= at if s else False for s in sid])
        both = ~np.isnan(fs) & ~np.isnan(fc)
        old, new = both & ~newer, both & newer
        e_old = float(np.abs(fc[old] - fs[old]).max()) if old.any() else 9e9
        e_new = np.abs(fc[new] - np.mod(fs[new] + sf, frames))
        e_new = float(np.minimum(e_new, frames - e_new).max()) if new.any() else 9e9
        first_new = min((x[AT] for x in r.reads if x[SID] and r.made[x[SID] - 1]["block"] >= at), default=-1)
        alone = int(np.argmax(new)) + lo
        remade = [(m_["k"], m_["step"], m_["block"]) for m_ in r.made if m_["step"] == 2][:2]
        bdy = (336000 - 287000) // N
        check(f"live {frames} frames, Slip 0 -> {slip} in step 1 (polled at block {at}, {at - 265} block(s) after the store "
              f"changed): the pending step 2 is dropped and re-made in that block, same slot",
              0 <= at - 265 < 16 and len(remade) == 2 and remade[1][2] == at and remade[0][0] == remade[1][0], remade)
        check(f"  everything up to the step boundary (336 000) identical to stock; the sounding segment keeps playing stock "
              f"frames (max {e_old:.4f}); the re-made step starts on the boundary ({first_new}, through stock's crossfade: "
              f"alone from {alone}) and every sample of it plays stock + slip_f (max {e_new:.4f}); summed gain = stock's at "
              "every sample (no added silence)",
              all(np.array_equal(x, y) for x, y in zip(ref["rig"].out[:bdy], r.out[:bdy])) and e_old == 0 and e_new <= 0.02
              and first_new == 336000 and not (np.abs(gs - gc) > 1e-6).any(),
              (e_old, e_new, first_new, int((np.abs(gs - gc) > 1e-6).sum())))

# The row's sign: + = AHEAD, - = behind (a CDJ jog). -480 (-0.480 on screen, half a beat behind) must
# play every sample 12 000 samples (half a beat at 120 BPM) after stock plays it: content = stock - 12 000.
ref = audio(frames=96000, cell=0x102)


def user_late(rr):
    if rr.block == 0:
        store_raw(rr.m, 6, {0x4: 500, P_SLIP: -480})


cw = audio(frames=96000, cell=0x102, pre=user_late)
n, err, bad, gd = shifted(ref, cw, slip_f(-480, 96000, 3840), 96000)
check(f"the row's sign: Slip -0.480 (counter-clockwise, behind) plays every sample half a beat LATER than stock - content "
      f"= stock frame - 12 000 ({n} samples, max {err:.4f} frame), and the bank holds -480",
      n > 25000 and err <= 0.02 and bad == 0 and gd == 0 and bank_slip(cw["rig"].m, 6) == -480, (n, err, bad, gd))

# Sync None: no pending segment to drop - the new Slip waits for the restart (README section 4, open question 8)
seen = {}


def change_none(rr):
    if rr.block == 300:
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:
        seen["at"] = rr.block


r = scenario(frames=96000, sync=6, cell=0x102, pre=change_none, blocks=900)
first = {}
for x in r.reads:
    first.setdefault(x[SID], x)
remade = [m_ for m_ in r.made if m_["block"] == seen.get("at")]
restart = first.get(remade[0]["sid"]) if len(remade) == 1 else None
check("Sync None, Slip 0 -> 960 while playing (README section 4, question 8): the playing segment plays on stock; the "
      "pending restart is re-made when the poll sees it, and that restart (len - 257 samples on) plays slipped",
      restart and first[1][FET][0][1] == 0 and restart[AT] == 288000 + 96000 - 257 and restart[FET][0][1] == 24000,
      ([(m_["block"], m_["start"]) for m_ in r.made], seen, [(x[AT], x[FET][:1]) for x in first.values()]))

# the pending launch (droplaunch, armed): never dropped (that would sound it at once, off its bar); the poll latches it
# again in place, so it plays the new Slip from its first read, on its bar
seen = {}


def change_pending(rr):
    if rr.block == 20:                                        # between the note (193 000) and its bar (288 000)
        seen["segs"] = [rr.seg(k) for k in range(4)]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:       # the poll ran just before, in this block
        seen["at"] = rr.block
        seen["pending"] = [rr.seg(k) for k in range(4)]
        seen["latch"] = [latch(rr.m, 6, k) if bank_valid(rr.m, 6) >> k & 1 else None for k in range(4)]


r = scenario(frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending)
launch = [m_ for m_ in r.made if m_["step"] == 0][:2]
k0 = launch[0]["k"] if launch else 0
p0 = seen["pending"][k0] if "pending" in seen and launch else dict(active=0, done=0, delay=0, first=0)
check("pending launch: when the poll sees the change, the launch segment is waiting (delay > 0, +0x3c set) and is "
      "not dropped (no step-0 segment made again); only the step after it is re-made",
      p0["active"] and not p0["done"] and p0["delay"] > 0 and p0["first"] and len(launch) == 1
      and [m_["block"] for m_ in r.made if m_["step"] == 1][:2] == [0, seen.get("at")], (p0, [(m_["step"], m_["block"]) for m_ in r.made]))
check("  ...so it still launches on its bar: first read at 288 000, layer +0x140 = 11 520, msg 0x1d posted",
      r.reads[0][AT] == 288000 and r.layer()["launch_tick"] == 11520 and [b for b, t, _ in r.posted if t == 0x1D][:1] == [742],
      (r.reads[0][AT], r.layer(), [b for b, t, _ in r.posted if t == 0x1D][:2]))
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
check(f"  the poll latches the waiting launch again in place (slot {k0}: (0, 96 000, 24 000), prefetched at 23 992 in that "
      "block): it plays slipped from its first read (first fetch 24 000 = slip_f), the next step too (24 000 + 24 000)",
      seen.get("latch", [None] * 4)[k0] == (0, 96000, 24000) and (seen.get("at"), 23992) in r.prefetches
      and r.reads[0][FET][0][1] == 24000 and step1 and step1[0][FET][0][1] == 48000,
      (seen.get("latch"), [p for p in r.prefetches if p[0] == seen.get("at")], r.reads[0][FET][:1], step1[0][FET][:1] if step1 else None))
ref = audio(frames=96000, at=193000, blocks=960, cell=0x102)
cw = decode(scenario(dc=True, frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending), r)
n, err, bad, gd = shifted(ref, cw, 24000, 96000)
check(f"  every sounding sample, the launch step's first included, plays (stock frame + slip_f) mod len ({n} samples, max "
      f"{err:.4f} frame), summed gain = stock's", n > 25000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))


def armed(bypass):
    """a note while the transport is stopped, Slip 0 -> 960 while it is armed, then PLAY on the bar at 384 000"""
    r = Rig(cell=0x102, bypass=bypass)
    slips(r.m, {})
    for _ in range(16):
        poll(r)
    r.pre_block = poll
    r.params()
    r.goto(193000)
    r.uc.mem_write(r.engine + 0x38, b"\x00")                  # transport stopped
    r.note_on()
    r.run(10)
    before = [r.seg(k) for k in range(4)]
    store(r.m, 6, {0x4: 500, P_SLIP: 960})
    r.run(20)
    held = dict(segs=[r.seg(k) for k in range(4)], armed=r.layer()["armed"], slip=bank_slip(r.m, 6), reads=len(r.reads),
                latch=latch(r.m, 6, 0) if bank_valid(r.m, 6) & 1 else None, pf=[p for b, p in r.prefetches if b >= 10])
    r.goto(384000)                                             # PLAY: the transport runs, and its start message (0x57)
    r.uc.mem_write(r.engine + 0x38, b"\x01")
    r.post(0x57)
    r.run(300)
    return r, before, held


r, before, held = armed(False)
by = armed(True)[0]
check("armed while the transport is stopped (delay 1, +0x3c set, layer +0x148 = 1): a Slip change leaves the launch armed "
      "and untouched, and latches it again in place (slot 0: (0, 96 000, 24 000), prefetched at 23 992)",
      before[0]["first"] and before[0]["delay"] == 1 and held["segs"] == before and held["armed"] == 1 and held["slip"] == 960
      and not held["reads"] and held["latch"] == (0, 96000, 24000) and held["pf"] == [23992], (before[0], held))
timing = lambda rr: [x[:SID] + x[AT:FET] for x in rr.reads]          # every read but its fetches
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
no_ph = lambda rr: [p for p in rr.posted if p[1] != 0x4A]          # the playhead's: H5 posts the slipped frame
check("  PLAY (msg 0x57) on the bar at 384 000: it sounds from 384 001 (stock's delay 1; +0x140 = 15 360, msg 0x1d), every "
      "read's timing and bookkeeping and every message but the playhead's (H5, §11d) as with the hooks out, and it plays "
      "slipped from its first read: first fetch 24 000 (slip_f; hooks out: 0), the next step 48 000",
      r.reads and by.reads and r.reads[0][AT] == by.reads[0][AT] == 384001 and r.layer()["launch_tick"] == by.layer()["launch_tick"] == 15360
      and [b for b, t, _ in r.posted if t == 0x1D][:1] == [30] and timing(r) == timing(by) and no_ph(r) == no_ph(by)
      and r.reads[0][FET][0][1] == 24000 and by.reads[0][FET][0][1] == 0 and step1 and step1[0][FET][0][1] == 48000,
      (r.reads[0][AT] if r.reads else None, r.layer(), by.layer(), timing(r) == timing(by), no_ph(r) == no_ph(by),
       r.reads[0][FET][:1] if r.reads else None, step1[0][FET][:1] if step1 else None))

# ====================================================================================================== 5b. a new file
# A new file under a playing pad: a load from the pad's Load screen, the browser's pre-listen (FUN_080a1560 loads each
# highlighted file into the pad the browser was opened on too), a take landing in the pad. The chain, as notes/re/x3
# sections 3 and 4 trace it: the pad's asset closes (fw_src_len answers 0), the pad load's full re-post makes the pad
# recompute while the new slot is not open yet (0x90), the loader opens the new file (fw_src_len answers its length,
# the source serves its frames), the app's 0xE handler posts 0x90 and the pad recomputes against it.
SWAP, CLOSED = 265, 4                                         # sample 320 920, inside step 1 (312 000 .. 336 000)
T_SWAP, T_OPEN = 287000 + SWAP * N, 287000 + (SWAP + CLOSED) * N


def new_file(length):
    def pre(rr):
        if rr.block == SWAP:
            rr.len = 0
            rr.param(0x90, 0)
        if rr.block == SWAP + CLOSED:
            rr.len = length
        if rr.block == SWAP + CLOSED + 1:
            rr.param(0x90, length)
    return pre


strip = lambda x: x[:SID] + x[AT:-1]                         # a read row, segment numbering and clip_read flag aside
for name, length, values in (("a shorter file (50 000 frames)", 50000, (960, -480)),
                             ("a longer file (192 000 frames)", 192000, (960,)),
                             ("a file of the same length (96 000 frames)", 96000, (960,))):
    sc = dict(frames=96000, cell=0x102, blocks=900, pre=new_file(length))
    st_r = scenario(image=STOCK, **sc)
    st = decode(scenario(dc=True, image=STOCK, **sc), st_r)
    t = st["base"] + np.arange(len(st["gain"]))
    quiet = int(((t >= T_OPEN) & (np.abs(st["gain"]) < 1e-7)).sum())
    on = [x for x in st_r.reads if x[0] == SWAP + CLOSED and st_r.made[x[SID] - 1]["step"] == 1]
    at = T_SWAP - 312000 + 24000                              # step 1's position when the slot closes
    check(f"stock 3.1.9, Slip 0, {name} under the playing pad from {T_SWAP}: no restart - the sounding step 1 stands "
          f"still while the slot is closed (nothing read) and reads on from its position, {at}, in the new file; the "
          f"pending step 2 keeps its start on the old grid (48 000), step 3 starts on the new one ({3 * length // 4}); "
          f"{quiet} samples silent after the file opens (the reader reads nothing past len + 0xff)",
          starts(st_r)[:5] == [(288000, 0, 0), (312000, 1, 24000), (336000, 2, 48000), (360000, 3, 3 * length // 4), (384000, 0, 0)]
          and not [m_ for m_ in st_r.made if SWAP <= m_["block"] <= SWAP + CLOSED + 1]
          and len(on) == 1 and on[0][POS] == at and on[0][FET][:1] == ((SWAP + CLOSED, at, N),),
          (starts(st_r)[:6], [(m_["block"], m_["step"]) for m_ in st_r.made], on[:1]))
    ok, d = same(scenario(**sc), st_r)
    check("  Slip 0 on this image: every read, fetch, prefetch, mixed sample and message identical to stock through the "
          "file change", ok, d)
    for slip in values:
        rr = scenario(slip=slip, **sc)
        cw = decode(scenario(dc=True, slip=slip, **sc), rr)
        sf_old, sf_new = slip_f(slip, 96000, 3840), slip_f(slip, length, 3840)
        lo, w = window(st, cw)
        gs, gc = w["gain"]
        s = lo + np.arange(len(gs))
        extra = int(((s >= T_SWAP) & (np.abs(gc) < 1e-7) & (np.abs(gs) > 1e-7)).sum())
        past = lambda r_: {f for f in r_.fetches if f[0] >= SWAP + CLOSED and f[1] + f[2] > length}
        old = {m_["sid"] for m_ in rr.made if m_["block"] < SWAP}
        mine = [strip(x) for x in rr.reads if x[0] >= SWAP and x[SID] in old]
        theirs = [strip(x) for x in st_r.reads if x[0] >= SWAP and x[SID] in old]
        if length != 96000:
            check(f"  Slip {slip}: the segments latched for the old file (the sounding step 1 and the pending step 2) read "
                  f"as stock does from the file change on: {len(mine)} reads (position, n, rate, frac, used, buffer, "
                  f"fetches) identical to stock's (the old mapping, + {sf_old} folded at 96 000, belongs to the old file)",
                  len(mine) > 200 and mine == theirs, (len(mine), len(theirs), [(a, b) for a, b in zip(mine, theirs) if a != b][:2]))
            check(f"  ...so no silence stock does not have ({extra} samples silent where stock sounds), and no read past "
                  f"the new file's end that stock does not make ({len(past(rr))} fetches reaching past {length}, all stock's own)",
                  extra == 0 and past(rr) <= past(st_r), (extra, sorted(past(rr) - past(st_r))[:3]))
        else:
            n, err, bad, gd = shifted(st, cw, sf_old, 96000)
            check(f"  Slip {slip}: the file closes and one of the same length opens: the latches hold again (the same "
                  f"length, the same shift), every sounding sample before and after plays stock + slip_f ({n} samples, max "
                  f"{err:.4f} frame), summed gain = stock's, the closed blocks silent as stock's",
                  n > 80000 and err <= 0.02 and bad == 0 and gd == 0 and extra == 0, (n, err, bad, gd, extra))
        fresh = [m_ for m_ in rr.made if m_["block"] > SWAP + CLOSED + 1]
        t_new = min((x[AT] for x in rr.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
        held = [(latch(rr.m, 6, k), made_for(rr.m, 6, k)) for k in range(4) if bank_valid(rr.m, 6) >> k & 1]
        n, err, bad, gd = shifted(st, cw, sf_new, length, since=t_new + 256)
        check(f"  the first segment made after the recompute (step {fresh[0]['step'] if fresh else None}, sounding from "
              f"{t_new}) and the ones after it latch the new file: (0, {length}, {sf_new}), made for {length}; from the end "
              f"of its crossfade with step 2 ({t_new + 256}) every sounding sample plays (stock frame + {sf_new}) mod "
              f"{length} ({n} samples, max {err:.4f} frame), summed gain = stock's",
              t_new == 360000 and held and all(x == ((0, length, sf_new), length) for x in held)
              and n > 20000 and err <= 0.02 and bad == 0 and gd == 0, (t_new, held, n, err, bad, gd))

# The browser's own chain. The browser loads each highlighted file into the pad it was opened from, and
# gives the pad its own file back when it is left: here a longer file (168 000 frames: 7 beats, Beat Count Auto 8) is
# swapped in inside step 1 of the 4-beat clip, played on into its last step (step 7, from frame 147 000, ending on
# 167 999), and the pad's own 96 000 frames come back inside it. That step's position is past the file's end and its
# end beyond it: the reader reads nothing there, so it never moves and never ends, and holds the layer, which only
# plays its step 0, once each time it comes round (on a unit: a slot at 315 848 of a 192 000-frame file, the
# pad repeating its first beat every 2 beats; at Slip 0 too). Stock 3.1.9 does exactly that; so does this image with
# cw_retire taken out. With it, the poll retires that segment (marks it done) and the pad plays its own file
# again from the next pass, in time.
LONG9, T9A, T9B = 168000, 265, 1355                 # the browsed file; swapped in inside step 1, back inside step 7


def browse(rr):
    """the browsed file in through 5b's whole chain (its slot closes, opens 4 blocks on); the pad's own back as a file
    whose slot is still open (the key map keeps the pad's asset: no closed blocks). With 4 closed blocks there too the
    recompute that sees no file ends the voice (stock's msg 0x1e): no stuck state, and the pad simply stops; the unit's
    pad kept playing, so its own file came back open"""
    for at, length, closed in ((T9A, LONG9, CLOSED), (T9B, 96000, 0)):
        if rr.block == at and closed:
            rr.len = 0
            rr.param(0x90, 0)
        if rr.block == at + closed:
            rr.len = length
        if rr.block == at + closed + 1:
            rr.param(0x90, length)


def stuck_log(rr):
    rr.segs9 = getattr(rr, "segs9", [])
    rr.segs9.append([(rr.m.r8(rr.pad + 0x30 + k * 0x70), rr.m.r8(rr.pad + 0x31 + k * 0x70),
                      rr.i64(rr.pad + 0x38 + k * 0x70), u32(rr.m, rr.pad + 0x64 + k * 0x70)) for k in range(4)])


def run9(old=False, **kw):
    sc_ = dict(frames=96000, cell=0x102, blocks=2300, pre=lambda rr: (browse(rr), stuck_log(rr)), **kw)
    if old and kw.get("image", IMAGE) == IMAGE:
        sc_["setup"] = lambda r_: r_.m.stub(S["cw_retire"])
    return audio(**sc_)


T9_BACK = 287000 + T9B * N                         # the pad's own file back
runs9 = {"stock 3.1.9": run9(image=STOCK), "no cw_retire": run9(old=True), "this build": run9(),
         "this build, Slip 960": run9(slip=960)}
for name, d in runs9.items():
    r = d["rig"]
    after = [x for x in starts(r) if x[0] > T9_BACK]
    held = [b for b, segs in enumerate(r.segs9) if b > T9B + 20 and any(a and not dn and p >= 96000 for a, dn, p, _ in segs)]
    if "this build" not in name:
        pos9 = {segs[k][2] for segs in r.segs9[T9B + 20:] for k in range(4) if segs[k][0] and segs[k][2] >= 96000}
        check(f"{name}: the pad's own file back inside the browsed file's last step: a segment past its end ({sorted(pos9)}) "
              f"stays active and never moves, to the end of the run ({len(held)} blocks), and the pad only plays its step 0 "
              f"from then on ({[x[:2] for x in after][:6]})",
              len(held) > 800 and len(pos9) == 1 and after and all(x[1] == 0 for x in after) and len(after) >= 2,
              (len(held), sorted(pos9), after[:6]))
    else:
        gone = next((b for b, segs in enumerate(r.segs9) if b > T9B and not any(a and not dn and p >= 96000
                                                                              for a, dn, p, _ in segs)), None)
        t0 = next((x[0] for x in after if x[1] == 0 and x[0] % 96000 == 0), None)
        seq = [x for x in after if t0 is not None and x[0] >= t0][:12]
        seq = seq[:len(seq) // 4 * 4 + 1] if len(seq) > 4 else seq
        slip9 = 960 if "Slip" in name else 0
        sf9 = slip_f(slip9, 96000, 3840) if slip9 else 0
        lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
        check(f"{name}: the segment past the end retired by the poll at block {gone} (the file back at block "
              f"{T9B}); from the next bar on ({t0}) the pad plays its own file in time again: steps "
              f"{[x[1] for x in seq]} at {[x[0] - (t0 or 0) for x in seq][:8]} from frames {[x[2] for x in seq][:8]}"
              + (f", latched {lat[:2]} (slip_f {sf9})" if sf9 else ""),
              gone is not None and gone <= T9B + 1 + 16 and len(seq) >= 5
              and [x[1] for x in seq] == [i % 4 for i in range(len(seq))]
              and [x[0] - t0 for x in seq] == [24000 * i for i in range(len(seq))]
              and [x[2] for x in seq] == [24000 * (i % 4) for i in range(len(seq))]
              and (not sf9 or (lat and all(x == (0, 96000, sf9) for x in lat))), (gone, t0, seq, lat))
# the load (TOOLS read 99 % once on a unit, in this state): the instructions the pad's block costs, the stuck pad
# against the recovered one, over the same blocks
from unicorn import UC_HOOK_CODE as _HC


def per_block(old):
    r = scenario(frames=96000, cell=0x102, blocks=T9B + 200, pre=browse,
                 setup=(lambda r_: r_.m.stub(S["cw_retire"])) if old else None)
    n = [0]
    r.uc.hook_add(_HC, lambda *a: n.__setitem__(0, n[0] + 1), begin=0x08040000, end=0x081FFFFF)
    out, pf, ft = [], len(r.prefetches), len(r.fetches)
    for _ in range(300):
        before = n[0]
        r.step_block()
        out.append(n[0] - before)
    return sum(out) / len(out), max(out), (len(r.prefetches) - pf) / 300, (len(r.fetches) - ft) / 300


c_old, c_new = per_block(True), per_block(False)
check(f"the load (TOOLS read 99 % once, in this state): the pad's block, the 300 blocks from 200 after the file came "
      f"back, stuck (cw_retire out): {c_old[0]:.0f} instructions on average (max {c_old[1]}), {c_old[2]:.2f} "
      f"prefetches and {c_old[3]:.2f} fetches a block (the stuck step's position is past the file's end); recovered: "
      f"{c_new[0]:.0f} (max {c_new[1]}), {c_new[2]:.2f}, {c_new[3]:.2f}: the extra work ends with the stuck state "
      "(its SD side, the prefetches past the end, is the unit's to measure)",
      c_new[0] < c_old[0] and c_new[2] < c_old[2], (c_old, c_new))

# ====================================================================================================== 6. gating


def gate(name, slip_map, silent=False, **kw):
    a = scenario(others=slip_map, **kw)
    b = scenario(others=slip_map, bypass=True, **kw)
    ok, d = same(a, b, silent)
    return a, ok, d


def slicer_setup(ms):
    def setup(r):
        r.goto(287000 - N)
        r.markers(ms)
        r.step_block()
    return setup


all960 = {q: 960 for q in range(16)}
MK = (0, 20000, 50000, 70000)                                 # slice markers
for name, kw in (("a Slicer pad (no markers: its segments pass H1)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers, note 37 (segments through H1')", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers (H1')", dict(sync=0, setup=slicer_setup(MK)))):
    a, ok, d = gate(name, all960, slip=960, cell=0x102, blocks=500, **kw)
    hits = {h: sum(1 for m_ in a.made if m_["how"] == h) for h in ("H1", "H1'")}
    check(f"{name}, Slip 960: plays exactly as with the hooks out, no latch ({hits})",
          ok and bank_valid(a.m, 6) == 0 and bank_slip(a.m, 6) == 960 and sum(hits.values()) > 0, d)

# Slip changed live on those pads: the poll still drops their pending segments (it does not know Slip is ignored there)


def changes(rr):
    if rr.block in (150, 260, 330, 420):
        store(rr.m, 6, {0x4: 500, P_SLIP: {150: 960, 260: -30, 330: 480, 420: 7}[rr.block]})


for name, kw in (("a Slicer pad (no markers)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers", dict(sync=0, setup=slicer_setup(MK)))):
    a = scenario(slip=0, cell=0x102, blocks=600, pre=changes, **kw)
    b = scenario(slip=0, cell=0x102, blocks=600, pre=changes, bypass=True, **kw)
    ok, d = same(a, b)
    remade = len(a.made) - len(b.made)
    check(f"{name}, Slip changed four times while it plays: every read, fetch, output sample and message as with the "
          f"hooks out ({remade} pending segment(s) dropped and re-made by stock, {len(a.prefetches) - len(b.prefetches)} "
          "extra prefetch hint(s))", d["reads"] and d["fetches"] and d["out"] and d["posted"] and bank_valid(a.m, 6) == 0, d)

# a slot H1 latched, reused by a slice segment (H1' clears it): live Sync -> Slice on a slipped pad


def to_slice(r):
    if r.block == 300:
        r.param(0x94, 0)


runs = [scenario(slip=960, cell=0x102, blocks=900, pre=to_slice, setup=slicer_setup(MK), bypass=b)
        for b in (False, True)]
sl = [[x[FET] for x in r_.reads if r_.made[x[SID] - 1]["how"] == "H1'"] for r_ in runs]
stale = [m_ for m_ in runs[0].made if m_["how"] == "H1'" and m_["valid_before"]]
check("Sync -> Slice while slipped: slice segments reuse slots H1 had latched (H1' clears them) and read the stock "
      "frames, exactly as with the hooks out", stale and sl[0] and sl[0] == sl[1], (len(stale), len(sl[0]), sl[0][:2], sl[1][:2]))
sounding = {x[SID] for x in runs[0].reads if x[0] == 300}
past = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[0].reads if x[SID] in sounding and x[POS] >= 96000][:1]
past_by = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[1].reads if x[POS] >= 96000][:1]
info("observed: the segment sounding at the switch keeps its latch and stock re-times it to run on past the file's end; "
     f"stock reads silence there {past_by}, the Clip Window the folded, slipped frames {past} (virtual, real)")

# a launch waiting for its bar on Sync = Slice (a slice segment, H1') is never latched again by the poll, even in a slot
# an earlier H1 segment used: Launch Trigger, Sync 1/4 (H1 caches the pad, every slot passes H1), a relaunch on the
# next bar, Sync -> Slice with markers live, another relaunch (now through H1'), then Slip 0 -> 960 before its bar
seen = {}


def slice_relaunch(rr):
    s = seen.setdefault(rr.hooks_out, {})
    if rr.block == 100:
        rr.note_on()                                          # relaunch on the bar at 384 000, through H1
    if rr.block == 800:
        rr.param(0x94, 0)                                     # Sync -> Slice
    if rr.block == 830:
        rr.note_on()                                          # relaunch on the bar at 480 000, through H1'
    if rr.block == 840:
        s["cached"] = u32(rr.m, BANK + B_PAD + 4 * 6) == rr.pad
        s["pending"] = [k for k in range(4) if rr.seg(k)["active"] and rr.seg(k)["delay"] > 0 and rr.seg(k)["first"]]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if rr.block == 870:
        s["slip"], s["valid"] = bank_slip(rr.m, 6), bank_valid(rr.m, 6)


runs = []
for b_ in (False, True):
    def tag(r, b_=b_):
        r.hooks_out = b_
        slicer_setup(MK)(r)
    runs.append(scenario(slip=0, sync=3, launch=0, cell=0x102, at=287000, blocks=1600, pre=slice_relaunch, setup=tag, bypass=b_))
ok, d = same(*runs)
a, s = runs[0], seen.get(False, {})
rel = [m_ for m_ in a.made if m_["how"] == "H1'" and m_["block"] == 830 and m_["k"] in s.get("pending", [])]
check(f"Sync = Slice, a relaunch pending for its bar (slot {[m_['k'] for m_ in rel]}, made through H1' in a slot H1 had used: "
      f"h1 bit {[m_['h1_before'] for m_ in rel]} before), pad cached by H1 ({s.get('cached')}), Slip 0 -> 960 before the bar: "
      f"every read, fetch, output sample and message as with the hooks out (msg 0x1d at {[b for b, t, _ in a.posted if t == 0x1D]}), "
      f"no latch; only prefetch hints differ ({len(a.prefetches) - len(runs[1].prefetches)} extra: pending slice steps re-made)",
      d["reads"] and d["fetches"] and d["out"] and d["posted"] and len(rel) == 1 and rel[0]["h1_before"] == 1 and s.get("cached")
      and s.get("slip") == 960 and s.get("valid") == 0 and bank_valid(a.m, 6) == 0
      and [b for b, t, _ in a.posted if t == 0x1D][-1:] == [1508], (d, s, [(m_["how"], m_["block"], m_["k"], m_["h1_before"]) for m_ in a.made]))

a, ok, d = gate("0x401", all960, slip=960, blocks=400, cell=0x401)
check(f"cell 0x401 (the 17th class-B object, queue ctx + 0x608; pad 2's store under & 3), Slip 960 on every pad: "
      f"inactive - plays ({len(a.reads)} reads) as with the hooks out, no latch, not cached as any pad",
      ok and not any(bank_valid(a.m, q) for q in range(16)) and not any(u32(a.m, BANK + B_PAD + 4 * q) for q in range(16)),
      (d, len(a.reads)))
a, ok, d = gate("len 0", all960, silent=True, slip=960, blocks=400, frames=0)
check(f"fw_src_len 0 (not open), Slip 960: nothing plays, as with the hooks out ({len(a.reads)} reads), no latch",
      ok and not any(bank_valid(a.m, q) for q in range(16)), d)
a, ok, d = gate("len bad", all960, slip=960, blocks=400, frames=0x10000000)
check(f"fw_src_len 0x10000000 (the provider reported 0 frames), Slip 960: inactive - plays ({len(a.reads)} reads) as with "
      "the hooks out, no latch", ok and not any(bank_valid(a.m, q) for q in range(16)), d)
fill = bytes([0xA5]) * (0x800 + B_BYTES)
a = Rig(block=False, cell=0x102)
a.uc.mem_write(BANK - 0x800, fill)
slips(a.m, all960)
a.pre_block = poll
a.params()
a.goto(287000)
a.note_on()
a.run(400)
b = scenario(slip=960, others=all960, cell=0x102, blocks=400, bypass=True)
ok, d = same(a, b)
check("no SDRAM block, Slip 960: the poll and both hooks pass through - same as the hooks out, the memory where the "
      "bank would be untouched", ok and bytes(a.uc.mem_read(BANK - 0x800, 0x800 + B_BYTES)) == fill, d)

# ====================================================================================================== 7. the reader (unit)
LENU = 50000
t = np.arange(LENU)
L_SIG = (0.4 * np.sin(2 * np.pi * 3000 * t / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t / 48000)).astype(np.float32)
R_SIG = (0.25 * np.sin(2 * np.pi * 5000 * t / 48000)).astype(np.float32)
RPAD, RSRC, SCR, OUT, VARS = 0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24062200
SCRD, SCRR, OUTD, OUTR = 0x24064000, 0x24065000, 0x24066000, 0x24067000   # 1024 floats each
VOICE = RPAD + 0x260 + 0x410
QU = 6


def sigs(length):
    """the test file's two channels, `length` frames (the first LENU are L_SIG / R_SIG)"""
    t_ = np.arange(length)
    return ((0.4 * np.sin(2 * np.pi * 3000 * t_ / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t_ / 48000)).astype(np.float32),
            (0.25 * np.sin(2 * np.pi * 5000 * t_ / 48000)).astype(np.float32))


def reader(image, rotate=None, length=LENU):
    """a machine with a RAM-served source: frame p of the file, or of the file turned by `rotate` (circular)"""
    m = Emu(image, "out/cave.elf")
    maps(m)
    m.fetches = []
    sig_l, sig_r = (L_SIG, R_SIG) if length == LENU else sigs(length)

    def frames_of(pos, n, sig):
        p = np.arange(pos, pos + n)
        if rotate is not None:
            return sig[np.mod(p + rotate, length)].tobytes()
        return np.where((p >= 0) & (p < length), sig[np.clip(p, 0, length - 1)], 0).astype(np.float32).tobytes()

    def fetch():
        pos = struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        m.fetches.append((pos, m.arg(2)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(2), sig_l))

    def fetch2():
        pos = m.r32(m.uc.reg_read(UC_ARM_REG_SP))
        m.fetches.append((pos, m.arg(3)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(3), sig_l))
        m.uc.mem_write(m.arg(2), frames_of(pos, m.arg(3), sig_r))
    m.stub(FETCH, fetch)
    m.stub(FETCH2, fetch2)
    m.stub(SRC_LEN, value=length)
    m.uc.mem_write(RPAD, bytes(0xC00))
    m.uc.mem_write(RPAD + 4, b"\x4c")
    m.w32(RPAD + 0x24, RSRC)
    m.w32(RPAD + 0x18, (QU // 4) << 8 | QU % 4)
    sdram(m)
    m.uc.mem_write(BANK, bytes(B_BYTES))
    m.w32(BANK, CW_MAGIC)
    return m


def set_latch(m, k, delta, valid=True, q=QU, length=LENU):
    """slot k latched as H1 latches it for a file of `length` frames: (0, length, delta), made for that length"""
    m.uc.mem_write(BANK + B_LATCH + (q * 4 + k) * L_SIZE, struct.pack("<4i", 0, length, delta, length))
    m.uc.mem_write(BANK + B_VALID + q, bytes([(1 << k) if valid else 0]))


def read(m, target, pos, frac, rate, stereo=False, n=64, k=1, frac_at=None):
    m.stub(0x08063790, value=int(stereo))
    for buf, dl, dr in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        m.uc.mem_write(buf, struct.pack("<IIIIBB", 1024, 1024, dl, dr if stereo else 0, 0, int(stereo)))
    for a in (OUTD, OUTR, SCRD, SCRR):
        m.uc.mem_write(a, bytes(4096))
    fp = frac_at if frac_at is not None else RPAD + 0x30 + k * 0x70 + 0x1C
    m.uc.mem_write(fp, struct.pack("<f", frac))
    m.uc.mem_write(VARS, struct.pack("<iI", -1, 0))
    m.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", rate))[0])
    for i, v in enumerate((n, VARS, fp, SCR, OUT, VARS + 4)):
        m.w32(STACK + 4 * i, v)
    m.fetches.clear()
    m.uc.reg_write(UC_ARM_REG_R11, VOICE)
    if target == 0x080662E4 or target == "clip_read":
        m.call(target, RPAD, VOICE + 0x14C, pos, 0, count=20_000_000)
    else:
        m.call(target, RPAD, 0, pos, 0, count=20_000_000)
    ok = m.uc.reg_read(UC_ARM_REG_R0)
    used, res = struct.unpack("<iI", m.uc.mem_read(VARS, 8))
    nfrac = struct.unpack("<f", m.uc.mem_read(fp, 4))[0]
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    left = np.frombuffer(bytes(m.uc.mem_read(dl, 4 * n)), np.float32).copy()
    right = np.frombuffer(bytes(m.uc.mem_read(dr, 4 * n)), np.float32).copy() if stereo else None
    return ok, used, nfrac, res, left, right, list(m.fetches)


def fidelity(m, v):
    store(m, QU, {0x4: 500, 0xDB: 0, 0xF1: v})


cw_m = reader(IMAGE)
for name, delta, pos, rate, frac, stereo, n, length in (
        ("rate 1, frac 0 (the straight copy)", 30000, 19970, 1.0, 0.0, False, 64, LENU),
        ("rate 0.7, frac 0.25 (the kernel)", 30000, 19980, 0.7, 0.25, False, 64, LENU),
        ("rate 2.3, frac 0.6", 12345, LENU - 12345 - 70, 2.3, 0.6, False, 64, LENU),
        ("rate 8, 128 frames (the fetch capped at the scratch's 1024)", 30000, 19990, 8.0, 0.3, False, 128, LENU),
        ("stereo, rate 1, frac 0", 30000, 19970, 1.0, 0.0, True, 64, LENU),
        ("stereo, rate 0.91875 (44.1 kHz), frac 0.4", 30000, 19985, 0.91875, 0.4, True, 64, LENU),
        ("rate 1, frac 0, real position 1 (no seam in stock's window: its reader at the real position)", 30001, 20000, 1.0, 0.0, False, 64, LENU),
        ("rate 0.8, real position 2 (the same)", 2, 0, 0.8, 0.1, False, 64, LENU),
        ("a 40-frame file, 64 frames read (round the file twice)", 13, 20, 1.0, 0.0, False, 64, 40),
        ("a 40-frame file, stereo, rate 1.7", 13, 30, 1.7, 0.2, True, 64, 40)):
    m = cw_m if length == LENU else reader(IMAGE, length=length)
    ref_m = reader(STOCK, rotate=delta, length=length)
    set_latch(m, 1, delta, length=length)
    fidelity(m, 0)
    got = read(m, "clip_read_b", pos, frac, rate, stereo, n=n)
    want = read(ref_m, 0x080662E4, pos, frac, rate, stereo, n=n)
    real = (pos + delta) % length
    count = n if rate == 1.0 and frac == 0.0 else min(int(np.float32(n) * np.float32(rate)) + 8, 1024)
    ring = got[6][0][0] == real and all(f[0] == 0 for f in got[6][1:]) and sum(f[1] for f in got[6]) == count
    check(f"{'seam' if real + count > length else 'mapped'} read, {name}: what the stock reader makes of the file turned circular (output, used, frac, buffer, "
          f"bit for bit); fetched {got[6]}", ring and got[0] == want[0] == 1 and got[1:4] == want[1:4]
          and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32))
          and (not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32))), (got[:4], want[:4], got[6], want[6]))

# off the seam: filter.c's machine modes read the mapped position (test_clip.py's model)
FIR26 = [0.00302, 0.24563, 0.5027, 0.24563, 0.00302]


def drop_model(P, rate, n, grid=26040):
    g, out = 48000 / grid, []
    for i in range(n):
        j = round(np.floor((P + i * rate) / g + 1 / 8192) * g)
        out.append(sum(FIR26[t] * float(L_SIG[(j - 2 + t) % LENU]) for t in range(5)))
    return np.array(out)


set_latch(cw_m, 1, 30000)
fidelity(cw_m, 2)
got = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
bad = np.where(np.abs(got[4] - drop_model(35000 + 1.25, 0.5, 64)) > 2e-4)[0]
fidelity(cw_m, 0)
norm = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
check("off the seam, Fidelity SP1200, rate 0.5: the drop-sample reader at the mapped position (35 000; test_clip.py's "
      f"model, {len(bad)} of 64 off), position bookkeeping as Fidelity Normal, one fetch from real - 3 {got[6]}",
      len(bad) <= 2 and got[1:3] == norm[1:3] and got[6] == [(34997, 40)], (bad[:4], got[1:3], norm[1:3], got[6]))

# a machine mode at or near the seam: filter.c's machine reader over the circular region (clip_read_ring), seam or not.
# The reference: filter.c's own clip_read at the real position on the file truly circular, bit for bit.
MODES = ((2, "SP1200"), (3, "SP-12"), (4, "S950"), (5, "MPC60"), (6, "SP Raw"), (7, "S950 Lo"), (8, "SP 45"))
circ_m = reader(IMAGE, rotate=0)


def same_read(got, want, stereo):
    return got[:4] == want[:4] and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32)) and (
        not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32)))


fidelity(cw_m, 2)
fidelity(circ_m, 2)
set_latch(cw_m, 1, 30000)
got = read(cw_m, "clip_read_b", 19980, 0.25, 0.5)
want = read(circ_m, "clip_read", 49980, 0.25, 0.5)
check(f"on the seam, Fidelity SP1200, rate 0.5 (real 49 980): filter.c's machine reader over the circular file, bit for "
      f"bit its clip_read on the file turned circular (output, used, frac, buffer); fetched {got[6]}, all inside the file",
      same_read(got, want, False) and got[6] == [(49977, 23), (0, 17)], (got[:4], want[:4], got[6], want[6]))
set_latch(cw_m, 1, 30001)
got = read(cw_m, "clip_read_b", 20000, 0.25, 0.5)
want = read(circ_m, "clip_read", 50001, 0.25, 0.5)
check("Fidelity SP1200 one frame into the file (real 1): the machine reader's back-step wraps to the file's end, bit for "
      "bit clip_read on the circular file one pass later (50 001: the 26 040 Hz grid repeats every 50 000 frames, 27 125 "
      f"steps); fetched {got[6]}", same_read(got, want, False) and got[6] == [(49998, 2), (0, 38)],
      (got[:4], want[:4], got[6], want[6]))

# F1: rate 1, frac 0 on the last blocks before the seam. Stock's straight copy needs n frames and has no seam there; a
# machine reads [real - 3, real + n + 5), across the end (gap 0..4) or onto it (5)
for v, name in MODES:
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    bad, outside = [], []
    for stereo in (False, True):
        for gap in range(6):
            real = LENU - N - gap
            set_latch(cw_m, 1, 30000)
            got = read(cw_m, "clip_read_b", real - 30000, 0.0, 1.0, stereo, n=N)
            want = read(circ_m, "clip_read", real, 0.0, 1.0, stereo, n=N)
            outside += [f for f in got[6] if not 0 <= f[0] <= f[0] + f[1] <= LENU]
            if not (same_read(got, want, stereo) and got[6][0][0] == real - 3 and sum(c for _, c in got[6]) == N + 8):
                bad.append((stereo, gap, got[:4], want[:4], got[6]))
    check(f"F1, Fidelity {name}, rate 1, frac 0, real = len - 128 - 0..5, mono and stereo: the machine's 136 frames from "
          "real - 3 fetched inside [0, len) only (in two parts where they wrap), and bit for bit clip_read on the circular file",
          not bad and not outside, (bad[:2], outside[:4]))

# near the start (real 0..2): the back-step wraps to the end. The reference reads one pass later, on a 240 000-frame file
# (5 x 48 000: the grid of every machine but SP 45, 19 288.9 Hz, repeats over it)
LONG = 240000
long_m, long_ref = reader(IMAGE, length=LONG), reader(IMAGE, rotate=0, length=LONG)
for v, name in MODES[:6]:
    fidelity(long_m, v)
    fidelity(long_ref, v)
    bad = []
    for stereo in (False, True):
        for real, rate, frac in ((0, 1.0, 0.0), (1, 1.0, 0.0), (2, 1.0, 0.0), (1, 0.91875, 0.4), (2, 0.8, 0.1)):
            set_latch(long_m, 1, 1234, length=LONG)
            got = read(long_m, "clip_read_b", (real - 1234) % LONG, frac, rate, stereo, n=N)
            want = read(long_ref, "clip_read", real + LONG, frac, rate, stereo, n=N)
            if not (same_read(got, want, stereo) and got[6][0] == (LONG - 3 + real, 3 - real)
                    and all(0 <= p_ <= p_ + c_ <= LONG for p_, c_ in got[6])):
                bad.append((real, rate, stereo, got[:4], want[:4], got[6]))
    check(f"near the start, Fidelity {name}, real 0 / 1 / 2 at rates 1, 0.91875, 0.8, mono and stereo: the back-step's "
          "frames fetched from the file's end, nothing outside it, and bit for bit clip_read on the circular file one pass "
          "later", not bad, bad[:2])

# ABI-1: the filter object's rate (+0x60) is the reader's to write; a clocked machine (S950, S950 Lo) takes its DAC clock
# and its low-pass from it, and a rate that makes no sense as "no reader ran". A seam block must write it too.
for v, name in ((4, "S950"), (7, "S950 Lo")):
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    rows = []
    for stereo in (False, True):
        for rate, frac, real in ((0.91875, 0.4, LENU - 20), (1.0, 0.0, LENU - 60), (1.498, 0.3, LENU - 60)):
            set_latch(cw_m, 1, 30000)
            cw_m.uc.mem_write(VOICE + 0x14C + 0x60, struct.pack("<f", 0.5))       # left by another rate
            got = read(cw_m, "clip_read_b", real - 30000, frac, rate, stereo, n=N)
            after = struct.unpack("<f", cw_m.uc.mem_read(VOICE + 0x14C + 0x60, 4))[0]
            want = read(circ_m, "clip_read", real, frac, rate, stereo, n=N)
            rows.append((rate, stereo, after, len(got[6]) == 2 and same_read(got, want, stereo)))
    check(f"ABI-1, Fidelity {name}: a stale rate at the filter object + 0x60 (0.5) is rewritten by a seam block (rates "
          "0.91875, 1, 1.498, mono and stereo, the fetch in two parts), and the block is clip_read's on the circular file",
          all(after == np.float32(rate) and ok_ for rate, _, after, ok_ in rows), rows)
fidelity(cw_m, 0)

# when the read is not ours to map
base_m = reader(IMAGE)
for name, prep, kw in (("the latch is not valid", lambda m: set_latch(m, 1, 30000, valid=False), {}),
                       ("the latch is for another slot", lambda m: set_latch(m, 2, 30000), {}),
                       ("&frac is not a segment's fraction", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 0x70 + 0x20)),
                       ("&frac is past the fourth segment", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 4 * 0x70 + 0x1C)),
                       ("the pad is cell 0x401", lambda m: (set_latch(m, 1, 30000), m.w32(RPAD + 0x18, 0x401)), {}),
                       ("the latch was made for a 96 000-frame file and the pad's file is now 50 000 frames (a load since "
                        "H1; the old mapping would read at 49 970)", lambda m: set_latch(m, 1, 30000, length=96000), {}),
                       ("no SDRAM block", lambda m: (set_latch(m, 1, 30000), sdram(m, False)), {})):
    m = reader(IMAGE)
    prep(m)
    got = read(m, "clip_read_b", 19970, 0.25, 0.7, **kw)
    want = read(base_m, "clip_read", 19970, 0.25, 0.7, **kw)
    check(f"{name}: filter.c's clip_read, unchanged", got[:4] == want[:4] and np.array_equal(got[4], want[4]) and got[6] == want[6],
          (got[:4], want[:4], got[6], want[6]))

# thunks entered as the patched sites enter them


def enter(m, thunk, r4, words):
    sp = STACK - 0x100
    for off, v in words.items():
        m.w32(sp + off, v)
    for reg, v in ((UC_ARM_REG_R0, RSRC), (UC_ARM_REG_R1, 1234), (UC_ARM_REG_R2, 0x33330000), (UC_ARM_REG_R3, 0x44440000),
                   (UC_ARM_REG_R4, r4)):
        m.uc.reg_write(reg, v)
    m.uc.reg_write(UC_ARM_REG_SP, sp)
    m.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    m.uc.emu_start(S[thunk] | 1, RET, count=1_000_000)
    return m.uc.reg_read(UC_ARM_REG_PC) == RET and m.uc.reg_read(UC_ARM_REG_SP) == sp and m.uc.reg_read(UC_ARM_REG_R4) == r4


m = reader(IMAGE)
pf = []
m.stub(PREFETCH, lambda: pf.append((m.arg(0), m.arg(1))))
set_latch(m, 2, 777)
for at in (B_VALID, B_H1, B_HINTED):
    m.uc.mem_write(BANK + at + QU, b"\x0f")
bits = lambda: [m.r8(BANK + at + QU) for at in (B_VALID, B_H1, B_HINTED)]
ok = enter(m, "clipwin_slice_start_b", RPAD, {4: 2, 0x20: 1})
check("H1' thunk: the slot from [sp + 4], the pad from r4: that slot's latch and its 'made through H1' bit cleared, the "
      "others kept, the prefetch called with the caller's source and position", ok and bits() == [0x0B, 0x0B, 0x0F]
      and pf == [(RSRC, 1234)], ([hex(x) for x in bits()], pf))
m.uc.mem_write(RPAD + 0x29, b"\x01")
m.uc.mem_write(RPAD + 0x208, struct.pack("<qI", 960, 4))
m.uc.mem_write(RPAD + 0x30 + 3 * 0x70 + 8, struct.pack("<q", 37000))
m.w32(BANK + B_SLIP + 4 * QU, 960)
m.uc.mem_write(BANK + B_H1 + QU, b"\x03")                     # slot 3 last held a slice segment
pf.clear()
ok = enter(m, "clipwin_seg_start_b", RPAD, {4: 1, 0x20: 3})
check("H1 thunk: the slot from [sp + 0x20]: slot 3 latched (0, 50 000, 12 500) for the 50 000-frame file, marked made "
      "through H1, its seam hint re-armed (hinted bit cleared), prefetched at 37 000 + 12 500 - 8",
      ok and bits() == [0x0B, 0x0B, 0x07] and latch(m, QU, 3) == (0, LENU, 12500) and made_for(m, QU, 3) == LENU
      and pf == [(RSRC, 49492)] and u32(m, BANK + B_PAD + 4 * QU) == RPAD, ([hex(x) for x in bits()], latch(m, QU, 3), pf))

# ====================================================================================================== 8. rate, stereo


def rate_case(name, frames, src_rate, stereo, slip, pitch=None):
    pre = (lambda rr: rr.param(0x5C, pitch) if rr.block == 0 else None) if pitch else None
    sc = dict(frames=frames, src_rate=src_rate, stereo=stereo, cell=0x102, pre=pre)
    rd0, rr0 = scenario(dc=True, **sc), scenario(**sc)
    rd1, rr1 = scenario(dc=True, slip=slip, **sc), scenario(slip=slip, **sc)
    sf = slip_f(slip, frames, 3840)
    rate = struct.unpack("<f", struct.pack("<I", rr1.reads[3][4]))[0]
    for ch in ((0, 1) if stereo else (0,)):
        n, err, bad, gd = shifted(decode(rd0, rr0, ch), decode(rd1, rr1, ch), sf, frames, edge=3)
        check(f"{name}{', right' if ch else (', left' if stereo else '')} (rate {rate:.5f}), Slip {slip}: every sounding "
              f"sample plays stock + slip_f ({n} samples, max {err:.4f} frame; the 3 frames at each end of the file "
              "aside), summed gain = stock's", n > 90000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
    seam = rr1.seam_reads()
    check(f"  {len(seam)} seam block(s) read through clipwin_read's own fetch{' pair' if stereo else ''} and "
          f"{'the kernel' if rate != 1.0 else 'the straight copy'}", len(seam) >= 1 and all(len(x[FET]) == 2 for x in seam if x[FET][0][1] > 3))


rate_case("44.1 kHz file (88 200 frames)", 88200, 44100, False, 960)
rate_case("stereo 48 kHz", 96000, 48000, True, -30)
rate_case("stereo 44.1 kHz", 88200, 44100, True, 3839)
rate_case("Pitch +7 semitones", 96000, 48000, False, 960, pitch=7000)

# ====================================================================================================== 9. the knob
texts, posts = [], []
e.stub(0x080C3B98, lambda: texts.append((e.arg(0), e.cstr(e.arg(1)))))
e.stub(0x080B0480)
e.stub(0x080AED14, lambda: posts.append((e.r16(e.arg(1)), e.r32(e.arg(1) + 0xC), e.r32(e.arg(1) + 0x10))))
LIST = 0x24050000
KN = LIST + 0x120


def fresh():
    e.uc.mem_write(LIST, bytes(0xA000))
    e.w32(KN, 0x080F0C88)
    e.uc.mem_write(LIST + 0x404, b"\x01")


def vtext():
    return [x for a, x in texts if a == KN + 0x9C]


regs = registrar(e, TABLE)                             # a real table for the binder
for v, want in ((1240, "+1.280"), (-30, "-0.030"), (0, "+0.000"), (959, "+0.959"), (3840, "+4.000"), (-3840, "-4.000")):
    fresh()
    texts.clear()
    e.call(0x080A7EE0, P_SLIP, v, KN)
    check(f"Slip {v} on a knob bound by the stock binder: type {e.r8(KN + 0x31)}, range {e.r32(KN + 0x14C)}..{e.r32(KN + 0x150)}, "
          f"text {want!r} (beats.ticks)", vtext()[-1:] == [want] and e.r8(KN + 0x31) == 1
          and (e.r32(KN + 0x14C), e.r32(KN + 0x150)) == (-3840, 3840), (vtext(), e.r8(KN + 0x31)))
fresh()
e.w32(KN + 0x14, P_SLIP)
e.call(0x080B04C8, KN)
texts.clear()
e.call(0x080B0790, KN, 1240)
check("a reset knob that kept the stale id 0x1c9 (type 0) prints what stock prints there: ''", vtext() == [""], vtext())
fresh()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
e.uc.mem_write(KN + 0x2D8, b"\x01")
texts.clear()
e.call("clipwin_format", KN)
ours_ = vtext()
texts.clear()
e.call(0x080B0528, KN)
check(f"a frozen knob (+0x2d8 set): clipwin_format leaves it to the stock formatter (text {ours_}, stock {vtext()})",
      ours_ == vtext() and "+1.280" not in ours_, (ours_, vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x09")         # registered as a type-9 row instead (P3 may)
fresh()
texts.clear()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
check("the same row registered as type 9 (a list position): the value it stands for, '+1.280'",
      e.r8(KN + 0x31) == 9 and vtext()[-1:] == ["+1.280"], (e.r8(KN + 0x31), vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x01")


def turn(path, per_ms, events=40, sign=1, start=0, fresh_knob=True, t0=10_000, period=16, seq=None, counts=None):
    """`events` turn events `period` ms apart at `per_ms` counts per ms (or `counts` an event, signed); returns (value,
    counts sent, last time), and appends (time, value) after each event to `seq` if given. A fresh knob comes with its acceleration ring (8 x
    {counts, ms} at +0x294, write index at +0x2d4) as if it had been turning at that speed for 8 events already:
    fresh() zeroes the widget, and a ring of zeros would read as a slow turn. The bank's detent state (the last arrival
    on 0) is left as it is: a fresh knob is a new turn, not a new unit."""
    c, t = (counts if counts is not None else sign * int(per_ms * period)), t0
    if fresh_knob:
        fresh()
        e.call(0x080A7EE0, P_SLIP, start, KN)
        posts.clear()
        texts.clear()
        for k in range(8):
            e.uc.mem_write(KN + 0x294 + 8 * k, struct.pack("<iI", c, t - period * (7 - k)))
        e.w32(KN + 0x2D4, 0)
    for _ in range(events):
        t += period
        e.w32(GUI_MS, t)
        if path == "list":
            e.call(0x080B9A3C, LIST, c)
        else:
            e.call(0x080B0D54, KN, c)
        if seq is not None:
            seq.append((t, e.r32(KN + 0x27C) + e.r32(KN + 0x288)))
    return e.r32(KN + 0x27C) + e.r32(KN + 0x288), c * events, t


# The knob: easy to set back to 0, and smooth from single ticks to large moves. Every turn event
# moves the stepper counts x gain(m) (400 stepper counts a tick), the gain geometric in the stock accelerator's speed m
# (1 .. 6): KNOB_GAIN at speed 1, x KNOB_GAIN_STEP / 256 a speed up, fitted to the bench's knob log (median counts an
# event by speed: 21, 35, 45, 63, 80, 116) so that speed 1 is single ticks and speed 6 a 1/64 an event; only the top
# speed (KNOB_TOP) snaps to the 1/64 grid. 0 is a detent: a turn that reaches or crosses it stops there, and passes
# ZERO_DETENT_SLOW_MS after it ARRIVED if it arrived at speed KNOB_DETENT_SLOW or under, ZERO_DETENT_MS if faster. The
# numbers are read from src/clipwin_b2.c's #defines (the rule is bank 2's, cw_turn), so that tuning one on the unit leaves
# these checks about the shape. The detent's state lives in cw_bank (SDRAM), as on the unit, so the block is there.
_knob_src = open("src/clipwin_b2.c").read()
KNOB_DEF = {n: int(re.search(rf"^#define {n}\s+(\d+)", _knob_src, re.M).group(1))
            for n in ("KNOB_GAIN", "KNOB_GAIN_STEP", "KNOB_TOP", "SLIP_GRID", "ZERO_DETENT_MS", "ZERO_DETENT_SLOW_MS",
                      "KNOB_DETENT_SLOW")}
GAIN1, GSTEP, TOP, GRID, DETENT, DETENT_SLOW, SLOW_AT = KNOB_DEF.values()
LOG_MEDIAN = {1: 21, 2: 35, 3: 45, 4: 63, 5: 80, 6: 116}   # notes/bench/2026-10-16-gate3-part1.md, the knob log
info(f"the knob's numbers (src/clipwin_b2.c): gain {GAIN1} at speed 1, x {GSTEP}/256 a speed, the 1/64 grid ({GRID}) at "
     f"speed {TOP}, the detent {DETENT_SLOW} ms after an arrival at speed {SLOW_AT} or under, {DETENT} ms after a faster one")


def gain(m):
    """stepper counts a knob count, x 256, as cw_turn makes it"""
    g = GAIN1 << 8
    for _ in range(1, min(max(m, 1), TOP)):
        g = g * GSTEP >> 8
    return g


def cdiv(a, b):
    """C's truncating division"""
    return -(-a // b) if (a < 0) != (b < 0) else a // b


def stepper_run(adds, start=0):
    """what the stock stepper (FUN_080b0b74, its step/3 hysteresis and all) makes of these adds, from `start` on a fresh
    knob (its accumulator parked mid-step there, as the binder leaves it)"""
    fresh()
    e.call(0x080A7EE0, P_SLIP, start, KN)
    for a in adds:
        e.call(0x080B0B74, KN + 0x270, a)
    return e.r32(KN + 0x27C) + e.r32(KN + 0x288)


def top_run(c, events, start):
    """the top speed's rule: the move rounded to the nearest 1/64 (half away from 0), at least one in the turn's way"""
    v = start
    for _ in range(events):
        to = v + cdiv(cdiv(c * gain(TOP), 256), 400)
        t_ = cdiv(to + (GRID // 2 if to >= 0 else -(GRID // 2)), GRID) * GRID
        if (c > 0 and t_ <= v) or (c < 0 and t_ >= v):
            t_ = (v // GRID + 1) * GRID if c > 0 else -((-v) // GRID + 1) * GRID
        v = max(-3840, min(3840, t_))
    return v


def at_speed(m):
    """counts per ms that the stock accelerator reads as speed m: trunc(|sum of the last 8 counts| / their 7 periods)"""
    return (m + 0.5) * 7 / 8


def turn_c(path, c, m, events, start=0, t0=10_000, seq=None):
    """`events` events of c counts each, as far apart as makes the ring read speed m"""
    period = max(1, int(8 * abs(c) / (7 * (m + 0.5))))
    while period > 1 and min(6, 8 * abs(c) // (7 * period)) < m:
        period -= 1
    return turn(path, 0, events=events, start=start, t0=t0, period=period, seq=seq, counts=c)


try:
    e.uc.mem_map(0xC0000000, 0x1800000)
except Exception:
    pass                                                    # already mapped
e.uc.mem_map(0x38800000, 0x1000) if not any(r[0] == 0x38800000 for r in e.uc.mem_regions()) else None
e.uc.mem_map(0x58024000, 0x1000) if not any(r[0] == 0x58024000 for r in e.uc.mem_regions()) else None
sdram(e)
e.w32(BANK, 0)                                              # bank() sets itself up on first use
for path in ("list", "turn"):
    name = "pad page list (FUN_080b9a3c)" if path == "list" else "waveform turn (FUN_080b0d54)"
    slow, counts, _ = turn(path, 0.7)
    check(f"{name}: slow (speed 1), 1 tick per 40 counts ({counts} counts -> {slow})", slow == counts // 40,
          (slow, counts))
    # at the knob log's median counts of each speed, 20 events from +120 up: the stepper fed counts x gain(m) / 256, or
    # at the top speed the 1/64 rule; and what each event leaves in cw_bank for the bench
    got, want, seen, rate = [], [], [], {}
    for m_ in range(1, 7):
        c = LOG_MEDIAN[m_]
        v, cnt, _ = turn_c(path, c, m_, 20, start=120)
        got.append(v)
        seen.append((struct.unpack("<h", bytes(e.uc.mem_read(BANK + B_KNOB_COUNTS, 2)))[0], e.r8(BANK + B_KNOB_SPEED), c))
        want.append(stepper_run([cdiv(c * gain(m_), 256)] * 20, 120) if m_ < TOP else top_run(c, 20, 120))
        rate[m_] = (v - 120) / 20
    steps = [rate[m_ + 1] / rate[m_] for m_ in range(1, 6)]
    check(f"  the log's median counts at speeds 1 .. 6, 20 events from +120: {got} - ticks an event "
          f"{[round(rate[m_], 2) for m_ in rate]}: single ticks at speed 1, a 1/64 at speed {TOP}, and between them a "
          f"geometric climb, x {[round(x, 2) for x in steps]} a speed; each the stepper fed "
          f"counts x gain / 256 (the top speed onto the 1/64 grid)",
          got == want and rate[1] <= 1 and rate[TOP] == GRID and all(1.5 <= x <= 3.5 for x in steps), (got, want, rate))
    check(f"  each event leaves its counts (i16) and the speed (u8) at cw_bank + {B_KNOB_COUNTS:#x} for a bench read "
          f"({[x[:2] for x in seen]})", all(x[0] == x[2] and x[1] == m_ for m_, x in enumerate(seen, 1)), seen)
    snaps = [turn_c(path, LOG_MEDIAN[TOP], TOP, 3, start=25)[0], turn_c(path, -LOG_MEDIAN[TOP], TOP, 3, start=-25)[0],
             turn_c(path, LOG_MEDIAN[TOP - 1], TOP - 1, 3, start=25)[0]]
    check(f"  the top speed snaps to the 1/64 grid (+25 up, three events: {snaps[0]}; -25 down: {snaps[1]}); the speed under "
          f"it does not ({snaps[2]} from +25)", snaps[:2] == [top_run(LOG_MEDIAN[TOP], 3, 25), top_run(-LOG_MEDIAN[TOP], 3, -25)]
          and all(x % GRID == 0 for x in snaps[:2]) and snaps[2] % GRID and snaps[2] > 25, snaps)
    v, _, _ = turn(path, 12, events=80)
    check("  fast up stops at +3840; the text follows, and the app is sent 0x1c9 = the value",
          v == 3840 and vtext()[-1:] == ["+4.000"] and posts and posts[-1] == (0x3D, 3840, P_SLIP), (v, vtext()[-1:], posts[-1:]))
    v, _, _ = turn(path, 12, events=80, sign=-1)
    check("  fast down stops at -3840 too", v == -3840 and vtext()[-1:] == ["-4.000"], (v, vtext()[-1:]))

    # the detent, a fast arrival: down from +300 at the top speed, an event every 16 ms
    sq = []
    turn(path, at_speed(TOP), events=20, sign=-1, start=300, t0=20_000, seq=sq)
    vals = [x for _, x in sq]
    i_arr = vals.index(0) if 0 in vals else 0
    t_arr = sq[i_arr][0]
    held = [x for tt, x in sq[i_arr + 1:] if tt - t_arr < DETENT]
    after = [x for tt, x in sq[i_arr + 1:] if tt - t_arr >= DETENT]
    check(f"  fast down from +300 (16 ms events): {vals[:i_arr + 1]} - it stops on 0, holds there for {len(held)} events "
          f"(those under {DETENT} ms after the arrival: a fast arrival), then goes past it at its speed ({after[:3]} ...); "
          f"slow-arrival flag {e.r8(BANK + B_ZERO_SLOW)}",
          0 in vals and held == [0] * len(held) and len(held) == (DETENT - 1) // 16 and len(after) > 0
          and after[0] < 0 and all(x % GRID == 0 for x in after) and e.r8(BANK + B_ZERO_SLOW) == 0, (vals, after))
    # ...a slow one (else it ends up slightly on the other side): held ZERO_DETENT_SLOW_MS
    for m_, c in ((1, 11), (SLOW_AT, LOG_MEDIAN[SLOW_AT])):
        sq = []
        turn_c(path, -c, m_, 120, start=3, t0=90_000 + 2000 * m_, seq=sq)
        vals = [x for _, x in sq]
        i_arr = vals.index(0) if 0 in vals else 0
        t_arr = sq[i_arr][0]
        held = [x for tt, x in sq[i_arr + 1:] if tt - t_arr < DETENT_SLOW]
        after = [x for tt, x in sq[i_arr + 1:] if tt - t_arr >= DETENT_SLOW]
        check(f"  slow down from +3 at speed {m_} ({c} counts an event): {vals[:i_arr + 1]} - held on 0 for the {len(held)} "
              f"events under {DETENT_SLOW} ms after the arrival (a fast one: {DETENT}), then on ({after[:4]} ...); slow-arrival "
              f"flag {e.r8(BANK + B_ZERO_SLOW)}",
              0 in vals and len(held) > 0 and held == [0] * len(held) and sq[i_arr + len(held)][0] - t_arr < DETENT_SLOW
              and sq[i_arr + len(held)][0] - t_arr >= DETENT_SLOW - 30 and after and after[-1] < 0
              and e.r8(BANK + B_ZERO_SLOW) == 1, (vals, held, after))
    # the pause counts from the arrival, not from the last event: a steady fast stream every 20 ms passes
    sq = []
    turn(path, at_speed(TOP), events=30, sign=-1, start=300, t0=30_000, period=20, seq=sq)
    t_arr = next(tt for tt, x in sq if x == 0)
    first = next((tt for tt, x in sq if x < 0), None)
    want_first = t_arr + -(-DETENT // 20) * 20
    check(f"  a steady stream, an event every 20 ms: it passes 0 {None if first is None else first - t_arr} ms after it "
          f"arrived (the first event {DETENT} ms or more on), then on ({[x for _, x in sq][-3:]})",
          first == want_first and sq[-1][1] < sq[-2][1] < 0, (first, want_first, sq))
    # a new turn the same way inside the pause is still in it; one after it, from rest, moves at once
    v, _, t = turn(path, at_speed(TOP), events=5, sign=-1, start=300, t0=40_000)
    v_in, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, start=0, t0=t + DETENT - 30)
    v_rest, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, start=0, t0=t + DETENT)
    check(f"  a fast turn that arrived on 0 ({v}), then a new one the same way {DETENT - 14} ms after the arrival: still on 0 "
          f"({v_in}); {DETENT + 16} ms after: off at once ({v_rest})", v == 0 and v_in == 0 and v_rest == -GRID,
          (v, v_in, v_rest))
    v_set = [turn(path, at_speed(m_), events=1, sign=s_, start=0, t0=50_000 + m_)[0] for m_, s_ in ((3, 1), (TOP, -1))]
    check(f"  a turn starting at 0 from rest: its first event moves (speed 3 {v_set[0]:+d}, the top speed {v_set[1]:+d})",
          v_set[0] > 0 and v_set[1] == -GRID, v_set)
    # the other way leaves 0 at once
    v, _, t = turn(path, at_speed(TOP), events=5, sign=1, start=-200, t0=60_000)
    v_back, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, fresh_knob=False, t0=t)
    check(f"  fast up from -200 holds 0 ({v}); turning the other way 16 ms later moves at once ({v_back})",
          v == 0 and v_back < 0, (v, v_back))
    # an arrival at speed 3 (over KNOB_DETENT_SLOW) is a fast one
    sq = []
    turn_c(path, -LOG_MEDIAN[3], 3, 30, start=40, t0=80_000, seq=sq)
    vals = [x for _, x in sq]
    i_arr = vals.index(0) if 0 in vals else 0
    t_arr = sq[i_arr][0]
    after = [(tt - t_arr, x) for tt, x in sq[i_arr + 1:] if x != 0]
    check(f"  an arrival at speed 3 holds {DETENT} ms, not {DETENT_SLOW}: {vals[:i_arr + 1]}, then on at "
          f"{after[0][0] if after else None} ms ({[x for _, x in after[:3]]})",
          0 in vals and after and DETENT <= after[0][0] < DETENT + 20 and e.r8(BANK + B_ZERO_SLOW) == 0, (vals, after))

# other knobs: the same text, steps and posts as on the stock image
for m_ in (st_m,):
    m_.stub(0x080B0480)
st_texts, st_posts = [], []
st_m.stub(0x080C3B98, lambda: st_texts.append((st_m.arg(0), st_m.cstr(st_m.arg(1)))))
st_m.stub(0x080AED14, lambda: st_posts.append((st_m.r16(st_m.arg(1)), st_m.r32(st_m.arg(1) + 0xC), st_m.r32(st_m.arg(1) + 0x10))))
others = [r for r in stock_regs if r[1] in (1, 0xD, 9)][:6]


def knob_run(m, tx, ps, pid, v, counts):
    m.uc.mem_write(LIST, bytes(0xA000))
    m.w32(KN, 0x080F0C88)
    tx.clear()
    ps.clear()
    m.call(0x080A7EE0, pid, v, KN)
    t_ = 50_000
    for c in counts:
        t_ += 16
        m.w32(GUI_MS, t_)
        m.call(0x080B0D54, KN, c)
    return [x for a, x in tx if a == KN + 0x9C], list(ps), m.r32(KN + 0x34), m.r32(KN + 0x27C)


for pid, typ, lab, lo, hi, xml in others:
    v = lo + (hi - lo) // 3
    counts = [11] * 10 + [192] * 10 + [-40] * 5
    a_, b_ = knob_run(e, texts, posts, pid, v, counts), knob_run(st_m, st_texts, st_posts, pid, v, counts)
    check(f"another knob ({lab!r}, id {pid:#x}, type {typ}): bound and turned slow and fast, the same text, posts and "
          "position as on the stock image", a_ == b_, (a_[0][-2:], b_[0][-2:], a_[1][-1:], b_[1][-1:], a_[2:], b_[2:]))

# ====================================================================================================== 10. Region
# Region (README section 3): the clip plays the Sample-mode loop [Loop Start, Loop End) - the cell's class-H object keeps
# it in Clip mode too - as if it were the file: the clip's length (H3) is the region's, so Beat Count Auto, the steps and
# the last step's end follow it, every segment latches the region in H1 and reads it circularly in H2. A change while it
# plays waits for the next wrap (H3'). Seamless wrap: Loop On and not Trigger, the last step crossfades into step 0.


def region_bank(m, q):
    return struct.unpack("<2i", m.uc.mem_read(BANK + B_REGION + 8 * q, 8))


# ---- unit: the rule, the source and the gating, clipwin_len called as the thunks call it
u = Emu(IMAGE, "out/cave.elf")
maps(u)
sdram(u)
u.uc.mem_write(BANK, bytes(B_BYTES))
UQ, UL, UH, USRC = 6, 0x24060000, 0x24061000, 0x24062000
ulen = [96000]
u.stub(SRC_LEN, lambda: u.ret(ulen[0]))
u.uc.mem_write(UL, bytes(0xC00))
u.uc.mem_write(UL + 4, b"\x4c")
u.w32(UL + 0x18, 0x102)
u.uc.mem_write(UL + 0x29, b"\x01")
u.uc.mem_write(UL + 0x1F4, bytes([1, 0, 0, 0, 3]))           # Loop On; Launch Toggle (+0x1f8 = 3)
u.uc.mem_write(UL + 0x220, struct.pack("<q", 960))           # Sync 1/4
u.uc.mem_write(UH, bytes(0x5C4))
u.uc.mem_write(UH + 4, b"\x48")
u.w32(UH + 0x18, 0x102)
u.w32(UL + 8, UH)


def h_loop(ls, le, mode):
    u.uc.mem_write(UH + 0xFC, struct.pack("<iii", ls, le, 0))
    u.w32(UH + 0x108, mode)


def len_at(site):
    u.call("clipwin_len", USRC, UL, site)
    return u.uc.reg_read(UC_ARM_REG_R0)


def ulen_call(site, layer=0):
    u.uc.mem_write(UL + 0x260, bytes([layer]))
    return len_at(site)


rule = [  # Region, Loop Mode, Loop Start, Loop End -> the region (rs, vlen), or None = the whole file
    (AUTO, 1, 24000, 72000, (24000, 48000), "a loop inside the file"),
    (AUTO, 2, 10000, 30000, (10000, 20000), "Bidirect counts as a loop"),
    (AUTO, 0, 24000, 72000, (24000, 48000), "Loop Mode None: the loop all the same (a row a Clip pad never shows)"),
    (AUTO, 1, 0, 96000, None, "[0, len) with Loop Forward: what a load leaves (x3 t13)"),
    (AUTO, 1, 0, 95999, None, "[0, len - 1]: a whole-file smpl loop"),
    (AUTO, 1, 0, 95998, (0, 95998), "[0, len - 2]"),
    (AUTO, 1, 0, 72000, (0, 72000), "from the start"),
    (AUTO, 1, 24000, 96000, (24000, 72000), "to the end"),
    (AUTO, 1, 50000, 40000, None, "start after end"),
    (AUTO, 1, 24000, 24000, None, "start = end"),
    (AUTO, 1, 24000, 100000, None, "end past the file"),
    (AUTO, 1, -5, 72000, None, "negative start"),
    (AUTO, 1, 0, 0, None, "Loop End 0 (no file yet, or a store being rebuilt)"),
    (FILE, 1, 24000, 72000, None, "File, whatever the loop"),
    (LOOP, 0, 24000, 72000, (24000, 48000), "Loop, whatever Loop Mode says"),
    (LOOP, 0, 0, 95999, None, "Loop on [0, len - 1] (a whole-file smpl loop, dwEnd inclusive) is the file too"),
    (LOOP, 0, 0, 95998, (0, 95998), "Loop on [0, len - 2]"),
    (LOOP, 1, 0, 96000, None, "Loop on the whole file is the file"),
    (LOOP, 1, 50000, 40000, None, "Loop, start after end"),
    (7, 1, 24000, 72000, (24000, 48000), "a value past the list reads as Auto"),
]
bad = []
for reg, mode, ls, le, want, what in rule:
    store(u, UQ, {0x4: 500, P_REGION: reg})
    h_loop(ls, le, mode)
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", 777, 777))
    got = ulen_call(1)
    r_ = region_bank(u, UQ)
    ok = (r_ == want and got == want[1]) if want else (r_[1] == 0 and got == 96000)
    if not ok:
        bad.append((what, got, r_, want))
check(f"the Auto rule and File / Loop over {len(rule)} loop-point cases (len 96 000; the class-H object's Loop Start +0xfc, "
      "Loop End +0x100, Loop Mode +0x108): Auto = Loop = any 0 <= start < end <= len but the whole file ([0, >= len - 1]), "
      "Loop Mode not asked; the recompute's length is the region's", not bad, bad)
store(u, UQ, {0x4: 500, P_REGION: AUTO})
h_loop(24000, 72000, 1)
rows = []
for n_, what in ((0, "not open"), (0x10000000, "the provider reported 0 frames")):
    ulen[0] = n_
    rows.append((ulen_call(1), region_bank(u, UQ)[1], ulen_call(0), ulen_call(2)))
ulen[0] = 96000
check(f"fw_src_len 0 / 0x10000000: no region, the length passed on as it is at every site ({rows})",
      rows == [(0, 0, 0, 0), (0x10000000, 0, 0x10000000, 0x10000000)], rows)
flens = []
for n_ in (336359, 0):
    ulen[0] = n_
    ulen_call(1)
    flens.append(u.r32(BANK + B_FLEN + 4 * UQ))
    ulen[0] = 7
    ulen_call(0)
    ulen_call(2)
    flens.append(u.r32(BANK + B_FLEN + 4 * UQ))
ulen[0] = 96000
ulen_call(1)
check(f"site 1 (the recompute) keeps fw_src_len's answer for the Waveform screen (cw_bank flen), the other sites do not "
      f"touch it ({flens}, then {u.r32(BANK + B_FLEN + 4 * UQ)})",
      flens == [336359, 336359, 0, 0] and u.r32(BANK + B_FLEN + 4 * UQ) == 96000, flens)
ulen_call(1)
rows = {}
for what, at, val, want in (("Clip", None, None, (48000, 48000, 1)),
                            ("Launch Trigger", 0x1F8, 1, (48000, 48000, 48000)),
                            ("Loop Off", 0x1F4, 0, (48000, 48000, 48000)),
                            ("a Slicer pad", 0x254, 1, (96000, 96000, 96000)),
                            ("Clip / Slicer mode off", 0x29, 0, (96000, 96000, 96000)),
                            ("Sync Slice with slice markers", 0x220, None, (96000, 96000, 96000)),
                            ("Sync Slice, no markers", 0x221, None, (48000, 48000, 1))):
    keep = bytes(u.uc.mem_read(UL, 0xC00))
    if at == 0x220:
        u.uc.mem_write(UL + 0x220, struct.pack("<q", 0xF0000))
        u.w32(UL + 0x250, 4)
    elif at == 0x221:
        u.uc.mem_write(UL + 0x220, struct.pack("<q", 0xF0000))
    elif at is not None:
        u.uc.mem_write(UL + at, bytes([val]))
    rows[what] = (ulen_call(0, 1), ulen_call(1, 1), ulen_call(2, 1))
    u.uc.mem_write(UL, keep)
check("the sites while it plays: the region's length at the recompute and the > 0 check, and at the last step's end 1 "
      "(seamless: end = 0) - but the region's end on a one-shot (Launch Trigger, or Loop Off); the whole file on a Slicer "
      f"pad, a pad not in Clip / Slicer mode, and Sync Slice with markers: {rows}",
      all(rows[w] == x for w, x in (("Clip", (48000, 48000, 1)), ("Launch Trigger", (48000, 48000, 48000)),
                                     ("Loop Off", (48000, 48000, 48000)), ("a Slicer pad", (96000,) * 3),
                                     ("Clip / Slicer mode off", (96000,) * 3), ("Sync Slice with slice markers", (96000,) * 3),
                                     ("Sync Slice, no markers", (48000, 48000, 1)))), rows)
# site 3 (0x08064c5a, the recompute's second length, r3 = the clip in output samples): a synced clip of one step has
# that step timed by the clip (+0x204), where stock times it by the length; nothing else changes it
def site3(n=1, synced=1, clip=24000, region=True):
    keep, kb = bytes(u.uc.mem_read(UL, 0xC00)), bytes(u.uc.mem_read(BANK + B_REGION + 8 * UQ, 8))
    u.uc.mem_write(UL + 0x1F5, bytes([synced]))
    u.w32(UL + 0x210, n)
    u.uc.mem_write(UL + 0x204, struct.pack("<f", 32000.0))
    u.uc.mem_write(UL + 0x260, b"\x01")
    if not region:
        u.w32(BANK + B_REGION + 8 * UQ + 4, 0)
    u.call("clipwin_len", USRC, UL, 3, clip)
    got = (u.uc.reg_read(UC_ARM_REG_R0), struct.unpack("<f", bytes(u.uc.mem_read(UL + 0x204, 4)))[0])
    u.uc.mem_write(UL, keep)
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, kb)
    return got


rows = {what: site3(**kw) for what, kw in (("one step, synced", {}), ("two steps", dict(n=2)), ("Sync None", dict(synced=0)),
                                           ("a clip of 0 ticks", dict(clip=0)), ("no region", dict(region=False)))}
check(f"site 3: the region's length; a synced clip of one step gets +0x204 = the clip in output samples (24 000), not the "
      f"region's 32 000 - not with two steps, Sync None, a clip of 0 ticks or no region ({rows})",
      rows == {"one step, synced": (48000, 24000.0), "two steps": (48000, 32000.0), "Sync None": (48000, 32000.0),
               "a clip of 0 ticks": (48000, 32000.0), "no region": (96000, 32000.0)}, rows)
# when it is taken: a stopped pad at any recompute; a playing one only at its wrap's
h_loop(0, 32000, 1)
playing = (ulen_call(1, 1), region_bank(u, UQ))
for L in (1, 2):
    u.uc.mem_write(UL + 0x260, bytes(0x420))
    u.uc.mem_write(UL + 0x260 + (L - 1) * 0x410, b"\x01")
    playing += (len_at(1), region_bank(u, UQ))
u.uc.mem_write(UL + 0x260, bytes(0x420))
u.uc.mem_write(BANK + B_WRAP, bytes([UQ + 2]))               # another pad's wrap
u.uc.mem_write(UL + 0x260, b"\x01")
other = (len_at(1), region_bank(u, UQ))
u.uc.mem_write(BANK + B_WRAP, bytes([UQ + 1]))               # this pad's
wrapped = (len_at(1), region_bank(u, UQ))
u.uc.mem_write(BANK + B_WRAP, b"\x00")
stopped = (ulen_call(1, 0), region_bank(u, UQ))
h_loop(24000, 72000, 1)
ulen_call(1)
h_loop(0, 32000, 1)
others = (ulen_call(0, 1), ulen_call(2, 1), ulen_call(0, 0), region_bank(u, UQ))
check("taken at the recompute (site 1) only: while either layer plays, the region it plays is kept (new loop points wait), "
      f"another pad's wrap changes nothing, its own wrap takes them, and so does a stopped pad: {playing}, {other}, "
      f"{wrapped}, {stopped}; the other sites never take one: {others}",
      playing == (48000, (24000, 48000), 48000, (24000, 48000), 48000, (24000, 48000)) and other == (48000, (24000, 48000))
      and wrapped == (32000, (0, 32000)) and stopped == (32000, (0, 32000)) and others == (48000, 1, 48000, (24000, 48000)),
      (playing, other, wrapped, stopped, others))
rec = []
u.stub(RECOMPUTE, lambda: rec.append((u.arg(0), u.arg(1), u.r8(BANK + B_WRAP))))
u.call("clipwin_wrap", UL, 0x12345678, 0)
after = u.r8(BANK + B_WRAP)
u.w32(UL + 0x18, 0x401)
u.call("clipwin_wrap", UL, 0x12345678, 0)
u.w32(UL + 0x18, 0x102)
check(f"H3' (clipwin_wrap): the recompute with the caller's pad and clock, this pad marked as wrapping during it and only "
      f"then; cell 0x401 is no pad ({rec}, after {after})", rec == [(UL, 0x12345678, UQ + 1), (UL, 0x12345678, 0)] and after == 0, rec)
# ...and the wrap grid: the recompute stubbed as one that adopts (0, 32 000) when this pad wraps and leaves +0x230 =
# `grid`; t = the synced wrap's tick of the new pass (an i64 at the thunk's sp + 0x58), 0 for the unsynced wrap
TICK = 0x24063000


def wrap_grid(t, grid, new=(0, 32000), old=(24000, 48000), was_grid=1920, was_tps=960, was_n=2):
    """...the pad's wrap grid and its steps (tps x n = its clip) before the recompute: by default the old region's 2 beats
    on Quant 1 bar (grid min(3840, 1920) = 1920)"""
    rec.clear()
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", *old))
    u.uc.mem_write(UL + 0x230, struct.pack("<q", was_grid))
    u.uc.mem_write(UL + 0x208, struct.pack("<qI", was_tps, was_n))

    def fake():
        w_ = u.r8(BANK + B_WRAP)
        rec.append(w_)
        if w_ == UQ + 1 and new:
            u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", *new))
        u.uc.mem_write(UL + 0x230, struct.pack("<q", grid))
    u.stub(RECOMPUTE, fake)
    if t is not None:
        u.uc.mem_write(TICK, struct.pack("<q", t))
    u.call("clipwin_wrap", UL, 0x12345678, TICK if t is not None else 0)
    return region_bank(u, UQ), tuple(rec)


rows = {what: wrap_grid(*a, **kw) for what, a, kw in (
    ("on the new grid", (3840 * 100, 3840), {}), ("off it", (3840 * 100 + 1920, 3840), {}),
    ("off it, region unchanged", (3840 * 100 + 1920, 3840), dict(new=None)),
    ("off it, only Loop Start moved", (3840 * 100 + 1920, 3840), dict(new=(0, 48000))),
    ("the unsynced wrap (no tick)", (None, 3840), {}), ("no grid (+0x230 = 0)", (3840 * 100 + 1920, 0), {}),
    ("a tick past 2^32", ((1 << 32) + 1920, 3840), {}))}
check("H3' and the wrap grid: a new region whose pass would not start on its own wrap grid (+0x230 after the recompute) "
      "is put back and the recompute run again, as no wrap (the pass keeps the region it had); on the grid, without a tick "
      f"(unsynced), without a grid, with the region unchanged or a tick past 2^32, it is taken: {rows}",
      rows == {"on the new grid": ((0, 32000), (UQ + 1,)), "off it": ((24000, 48000), (UQ + 1, 0)),
               "off it, region unchanged": ((24000, 48000), (UQ + 1,)), "off it, only Loop Start moved": ((24000, 48000), (UQ + 1, 0)),
               "the unsynced wrap (no tick)": ((0, 32000), (UQ + 1,)), "no grid (+0x230 = 0)": ((0, 32000), (UQ + 1,)),
               "a tick past 2^32": ((0, 32000), (UQ + 1,))}, rows)
# It waits only for a wrap that can come. The render snaps each pass start to the old grid, so the
# passes start one old pass (the old clip snapped to it) apart; they meet the new grid iff gcd(old pass, new grid) divides
# the tick. A region under half a beat (Beat Count Auto: a clip of 0 ticks, grid 0) has passes that start anywhere; a
# 3-bar loop on Quant 1 bar launched on bar 1 (mod 3) cut to 3 beats starts every pass 960 ticks off the 2 880 grid
rows = {what: wrap_grid(*a, **kw) for what, a, kw in (
    ("from a 0-tick clip (no grid), off the new grid", (3840 * 100 + 777, 1920), dict(was_grid=0, was_tps=0, was_n=1)),
    ("from 3 bars on the 1-bar grid, a pass on bar 1 mod 3, to a 3-beat grid", (3840 * 100, 2880),
     dict(was_grid=3840, was_tps=960, was_n=12)),
    ("from 2 bars to a 3-beat grid (the wrap comes: 7 680 x k + 384 000 meets 2 880)", (3840 * 100, 2880),
     dict(was_grid=3840, was_tps=960, was_n=8)),
    ("from 10 beats on the 1-bar grid, a tie its passes take down (7 680 apart), to a 3-beat grid (the wrap comes)",
     (3840 * 100, 2880), dict(was_grid=3840, was_tps=960, was_n=10)),
    ("from 2 beats to 1 bar, the pass on the off-bar beat (the bar comes next pass)", (3840 * 100 + 1920, 3840), {}))}
del u.stubs[RECOMPUTE]
check("...but only for a wrap on the new grid that can come: from a 0-tick clip, or passes that never meet "
      "the new grid, the region is taken at once; where one comes (gcd of the old pass and the new grid divides the "
      f"tick) it waits for it: {rows}",
      rows == {"from a 0-tick clip (no grid), off the new grid": ((0, 32000), (UQ + 1,)),
               "from 3 bars on the 1-bar grid, a pass on bar 1 mod 3, to a 3-beat grid": ((0, 32000), (UQ + 1,)),
               "from 2 bars to a 3-beat grid (the wrap comes: 7 680 x k + 384 000 meets 2 880)": ((24000, 48000), (UQ + 1, 0)),
               "from 10 beats on the 1-bar grid, a tie its passes take down (7 680 apart), to a 3-beat grid (the wrap comes)":
                   ((24000, 48000), (UQ + 1, 0)),
               "from 2 beats to 1 bar, the pass on the off-bar beat (the bar comes next pass)": ((24000, 48000), (UQ + 1, 0))},
      rows)
u.uc.mem_write(UL + 0x230, bytes(8))
# the source: the class-H object when the link holds, else the app's store (0x91, 0x92) with the last good pair; Loop
# Mode (0x8e) is not read: the fourth pair, with Loop Mode None, is a region all the same
rows = []
for what, link in (("no class-H object (pad + 8 = 0)", 0), ("an object of another class", "class"), ("another cell's", "cell")):
    u.w32(UL + 8, UH if link else 0)
    if link == "class":
        u.uc.mem_write(UH + 4, b"\x43")
    if link == "cell":
        u.w32(UH + 0x18, 0x103)
    u.uc.mem_write(BANK + B_GOOD + 8 * UQ, bytes(8))
    seq = []
    for vals in ({0x8E: 1, 0x91: 10000, 0x92: 30000}, {0x8E: 1, 0x91: 40000, 0x92: 30000}, {0x8E: 1, 0x92: 30000},
                 {0x8E: 0, 0x91: 10000, 0x92: 30000}, {0x8E: 1, 0x91: 0, 0x92: 64000}):
        store(u, UQ, {**vals, 0x4: 500, P_REGION: AUTO})
        ulen_call(1)
        seq.append(region_bank(u, UQ))
    rows.append((what, seq))
    u.uc.mem_write(UH + 4, b"\x48")
    u.w32(UH + 0x18, 0x102)
u.w32(UL + 8, UH)
want = [(10000, 20000), (10000, 20000), (0, 30000), (10000, 20000), (0, 64000)]
check("no usable class-H link (none, another class, another cell): the loop from the app's store, through the settings "
      "lookup; a pair that makes no sense there (start after end; a start not stored yet, read 0) gives the last pair that "
      "did; Loop Mode None as on", all(seq == want for _, seq in rows),
      rows)
info("observed: a Loop Start the store does not hold yet reads 0 and makes a pair with Loop End: [0, 30 000) until it "
     "arrives (the fallback only; the class-H object has both from the same queue)")

# ---- the whole process
REG = (24000, 72000, 1)                                      # 2 beats of a 96 000-frame file, Loop Forward


def first_steps(r, k=6):
    return [(a, st_, fr) for a, st_, fr in starts(r)][:k]


def wraps_at(r, after=0):
    return [a for a, st_, _ in starts(r) if st_ == 0 and a > after]


def region_shift(ref, cw, rs, vlen, sf, wraps, guard=300, edge=0):
    """samples where one segment sounds in both runs, away from the wraps: max |cw frame - (rs + (ref frame + sf) mod
    vlen)| (circular), the count off by more than 0.05, and of samples whose summed gain differs. `edge` leaves out the
    samples within that many frames of either end, of the reference file or of the region (the kernel's support: stock
    interpolates into the silence after its file, the region into its own start, and a frame decoded from a ramp
    interpolated across the seam is a blend of both ends)"""
    lo, w = window(ref, cw)
    fs, fc = w["frame"]
    gs, gc = w["gain"]
    at = lo + np.arange(len(fs))
    away = np.ones(len(fs), bool)
    for x in wraps:
        away &= np.abs(at - x) > guard
    want = np.mod(fs + sf, vlen)
    if edge:
        for x in (np.nan_to_num(fs, nan=vlen / 2), np.nan_to_num(want, nan=vlen / 2)):
            away &= (x >= edge) & (x <= vlen - 1 - edge)
    ok = ~np.isnan(fs) & ~np.isnan(fc) & away
    want = rs + want
    err = np.abs(fc - want)
    err = np.minimum(err, vlen - err)[ok]
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > 0.05).sum()), int(((np.abs(gs - gc) > 1e-6) & away).sum())


def inside(d, rs, vlen, start, stop=None):
    """from sample `start` on: frames played by one segment outside [rs, rs + vlen), zero-gain samples, the peak gain"""
    a, b_ = start - d["base"], (stop - d["base"]) if stop else len(d["gain"]) - N
    f, g = d["frame"][a:b_], d["gain"][a:b_]
    out = ~np.isnan(f) & ((f < rs - 0.02) | (f > rs + vlen - 1 + 0.02))
    return int(out.sum()), int((np.abs(g) < 1e-7).sum()), float(g.max())


FIELDS = ((0x1FC, "<f"), (0x204, "<f"), (0x208, "<q"), (0x210, "<I"), (0x230, "<q"), (0x23C, "<I"), (0x258, "<f"), (0xBA8, "<q"))


def fields(r):
    return [struct.unpack(f_, bytes(r.uc.mem_read(r.pad + o, struct.calcsize(f_))))[0] for o, f_ in FIELDS]


# Region Loop plays only [ls, le), Slip on top; Beat Count Auto from the region's length. Reference: the stock image
# playing a 48 000-frame file - the region alone - with the same settings.
ref = audio(frames=48000, beats=0, image=STOCK, cell=0x102)
ref_r = ref["rig"]
for slip in (0, 480, -30, 7):
    cw = audio(frames=96000, beats=0, slip=slip, points=REG, cell=0x102)
    r = cw["rig"]
    sf = slip_f(slip, 48000, 1920)
    w_ = wraps_at(r, 288000)
    n, err, bad_, gd = region_shift(ref, cw, 24000, 48000, sf, w_)
    out, zeros, peak = inside(cw, 24000, 48000, 288000 + 300)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
    pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
    check(f"Region Auto, Loop Forward [24 000, 72 000) of 96 000, Slip {slip} (slip_f {sf} over the region): away from the "
          f"wraps ({w_[:3]}...) every sounding sample plays 24 000 + (stock's frame of the region alone + slip_f) mod 48 000 "
          f"({n} samples, max error {err:.4f} frame), summed gain = stock's",
          n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0 and len(w_) >= 2, (n, err, bad_, gd, w_))
    check(f"  nothing outside the region from the launch on ({out} samples), no zero-gain sample ({zeros}; stock's wraps "
          f"have a notch), peak gain {peak:.3f}; latched {lat[:1]} every segment, prefetched at 24 000 + the mapped start - 8"
          + (f"; {len(r.hints)} seam hint(s) at rs" if slip else ""),
          out == 0 and zeros == 0 and peak <= 1.0 + 1e-6 and lat and all(x == (24000, 48000, sf) for x in lat)
          and pf == [max(0, 24000 + (m_["start"] + sf) % 48000 - 8) for m_ in h1]
          and all(p == 24000 for _, p, _ in r.hints) and (not slip or r.hints), (out, zeros, peak, lat, pf[:4], r.hints[:3]))
    if slip == 0:
        check("  Beat Count Auto counts the region: frames per step, output samples per step, ticks per step, steps, wrap "
              f"grid, length, file tempo and the clip ticks told the app equal stock's for the 48 000-frame file ({fields(r)})",
              fields(r) == fields(ref_r) and fields(r)[2] * fields(r)[3] == 1920
              and [p[1:] for p in r.posted if p[1] == 0x8D][-1:] == [p[1:] for p in ref_r.posted if p[1] == 0x8D][-1:],
              (fields(r), fields(ref_r), [p for p in r.posted if p[1] == 0x8D], [p for p in ref_r.posted if p[1] == 0x8D]))

# Beat Count Auto over other region lengths: the recompute's fields are stock's for a file of the region's length
rows = []
for ls, le in ((0, 36000), (10000, 50000), (5000, 61000), (12345, 90000), (0, 95998)):
    a = scenario(frames=96000, beats=0, points=(ls, le, 1), cell=0x102, blocks=8)
    b = scenario(frames=le - ls, beats=0, image=STOCK, cell=0x102, blocks=8)
    rows.append((le - ls, fields(a)[2] * fields(a)[3], fields(a) == fields(b)))
check(f"Beat Count Auto with regions of 36 000, 40 000, 56 000, 77 655 and 95 998 frames: every recompute field as stock's for "
      f"that file ({[(v, c) for v, c, _ in rows]} (frames, clip ticks))", all(x for _, _, x in rows), rows)

# Auto keeps a freshly loaded pad on File (its loop points the whole file, whatever Loop Mode), and File is Slip alone, bit for bit
for name, kw in (("Auto, [0, len) Loop Forward (what a load leaves)", dict(points=(0, 88615, 1))),
                 ("Auto, [0, len) Loop Mode None", dict(points=(0, 88615, 0))),
                 ("File, a Loop Forward loop [24 000, 72 000)", dict(points=REG, region=FILE))):
    for slip in (0, 960):
        a = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, **kw)
        b = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, points=(0, 0, 0))
        c = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, region_off=True, **kw)
        ok1, d1 = same(a, b)
        ok2, d2 = same(a, c)
        check(f"{name}, Slip {slip}, 88 615 frames: every read, fetch, prefetch, output sample and message as with no loop "
              "(Loop Start, Loop End, Loop Mode all 0), and as with Region's hooks taken out (Slip alone)", ok1 and ok2 and region_bank(a.m, 6)[1] == 0, (d1, d2))
a = scenario(frames=96000, cell=0x102, blocks=900, points=REG, region=FILE)
b = scenario(frames=96000, cell=0x102, blocks=900, points=REG, image=STOCK)
ok, d = same(a, b)
check("File with a loop, Slip 0: as the stock 3.1.9 image, bit for bit", ok, d)
a = audio(frames=96000, beats=0, points=(24000, 72000, 0), region=LOOP, cell=0x102)
n, err, bad_, gd = region_shift(ref, a, 24000, 48000, 0, wraps_at(a["rig"], 288000))
check(f"Loop with Loop Mode None: the region all the same ({n} samples as the region alone, max error {err:.4f})",
      n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0, (n, err, bad_, gd))
# A take whose loop points were moved on the Clip-mode Waveform has Sample mode's Loop Mode None (a row a
# Clip pad never shows): Auto plays them, as Loop does
a = audio(frames=96000, beats=0, points=(24000, 72000, 0), region=AUTO, cell=0x102)
n, err, bad_, gd = region_shift(ref, a, 24000, 48000, 0, wraps_at(a["rig"], 288000))
check(f"Auto with Loop Mode None: the region, as Loop plays it ({n} samples as the region alone, max error "
      f"{err:.4f}; region {region_bank(a['rig'].m, 6)})", n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0
      and region_bank(a["rig"].m, 6) == (24000, 48000), (n, err, bad_, gd, region_bank(a["rig"].m, 6)))

# the seamless wrap, proven: regions shorter and longer than their (Auto) beats, against stock playing them as files
for ls, le, what in ((10000, 50000, "40 000 frames (1.67 beats, Auto 2: short, stock leaves a gap before each wrap)"),
                     (0, 56000, "56 000 frames (2.33 beats, Auto 2: long, stock's last step overlaps the next pass)"),
                     (24000, 72000, "48 000 frames (2 beats: stock's V-notch at the wrap)")):
    vlen = le - ls
    st_ = audio(frames=vlen, beats=0, image=STOCK, cell=0x102)
    cw = audio(frames=96000, beats=0, points=(ls, le, 1), cell=0x102)
    _, z0, p0 = inside(st_, 0, vlen, 288000 + 300)
    out, z1, p1 = inside(cw, ls, vlen, 288000 + 300)
    n, err, bad_, gd = region_shift(st_, cw, ls, vlen, 0, wraps_at(cw["rig"], 288000), guard=4400)
    wr = wraps(dict(frame=cw["frame"] - ls, sid=cw["sid"]), vlen)
    check(f"seamless, {what}: stock {z0} zero-gain samples and peak {p0:.3f}; the region {z1} and peak {p1:.3f}, nothing "
          f"outside it, the last step running on round the region's end ({wr} time(s) in one segment) into the next pass; "
          f"the steps away from the wraps as stock's ({n} samples)",
          z1 == 0 and p1 <= 1.0 + 1e-6 and out == 0 and (z0 > 0 or p0 > 1.0 + 1e-6) and n > 20000 and err <= 0.02
          and bad_ == 0, (z0, p0, z1, p1, out, wr, n, err, bad_))
for name, kw in (("Launch Trigger (a one-shot)", dict(launch=0)), ("Loop Off", dict(loop=0))):
    st_ = audio(frames=48000, beats=0, image=STOCK, cell=0x102, **kw)
    cw = audio(frames=96000, beats=0, points=REG, cell=0x102, **kw)
    n, err, bad_, gd = region_shift(st_, cw, 24000, 48000, 0, [])
    out, _, _ = inside(cw, 24000, 48000, 288000)
    last, last_st = np.nanmax(cw["frame"]), np.nanmax(st_["frame"])
    check(f"{name}: no seamless end - the pass plays the region once and stops on its end (last frame sounding {last:.0f}, "
          f"stock {last_st:.0f} of its 48 000), every sample and gain as stock's playing the region alone ({n} samples)",
          n > 40000 and err <= 0.02 and bad_ == 0 and gd == 0 and out == 0 and abs(last - last_st - 24000) < 0.02
          and last_st > 47990, (n, err, bad_, gd, out, last, last_st))

# a clip of one Sync step (Sync >= the clip, n = 1): stock times that step by the length (+0x204), so a file longer than
# its beats doubles at every wrap and a shorter one leaves a gap; the region's step is timed by the clip (H3 site 3)
for ls, le, what in ((24000, 56000, "32 000 frames (1.33 beats, Auto 1: long)"), (24000, 44000, "20 000 frames (0.83 beat, Auto 1: short)")):
    vlen = le - ls
    st_ = audio(frames=vlen, beats=0, image=STOCK, cell=0x102)
    cw = audio(frames=96000, beats=0, points=(ls, le, 1), cell=0x102)
    r = cw["rig"]
    _, z0, p0 = inside(st_, 0, vlen, 288000 + 300)
    out, z1, p1 = inside(cw, ls, vlen, 288000 + 300)
    w_ = wraps_at(r, 0)
    f_, fs_ = fields(r), fields(st_["rig"])
    n, err, bad_, gd = region_shift(st_, cw, ls, vlen, 0, w_)
    check(f"one step, {what}, Sync 1/4: ticks per step {f_[2]}, {f_[3]} step, +0x204 {f_[1]:.0f} (the clip; stock "
          f"{fs_[1]:.0f}, the length); stock {z0} zero-gain samples and peak {p0:.3f}, the region {z1} and peak {p1:.3f}, "
          f"nothing outside it, a pass every beat ({w_[:4]}), what both play alone as stock's ({n} samples)",
          f_[2:4] == [960, 1] and f_[1] == 24000.0 and fs_[1] == vlen and z1 == 0 and p1 <= 1.0 + 1e-6 and out == 0
          and (z0 > 0 or p0 > 1.0 + 1e-6) and w_[:4] == [288000, 312000, 336000, 360000] and n > 10000 and err <= 0.02 and bad_ == 0,
          (f_, fs_, z0, p0, z1, p1, out, w_[:4], n, err, bad_))

# a region under half a beat on Beat Count Auto is a clip of 0 ticks (stock rounds a file that short to 0 beats too):
# no clip to turn Slip into frames (slip_f 0), but every segment still reads the region, not the file's first frames
for launch, name in ((2, "Toggle"), (0, "Trigger")):
    st_ = audio(frames=9000, beats=0, sync=5, launch=launch, image=STOCK, cell=0x102, blocks=400)
    cw = audio(frames=96000, beats=0, sync=5, launch=launch, points=(30000, 39000, 1), slip=480, cell=0x102, blocks=400)
    r = cw["rig"]
    out, z, pk = inside(cw, 30000, 9000, 288000 + 300)
    _, zs, pks = inside(st_, 0, 9000, 288000 + 300)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
    pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
    s_ = starts(r)
    fr = cw["frame"]
    lo_, hi_ = float(np.nanmin(fr)), float(np.nanmax(fr))
    ok = (fields(r)[2] == 0 and out == 0 and lo_ >= 30000 - 0.02 and hi_ <= 38999 + 0.02 and lat and all(x == (30000, 9000, 0) for x in lat)
          and pf == [max(0, 30000 + m_["start"] % 9000 - 8) for m_ in h1] and all(st == 0 and fr_ == 0 for _, st, fr_ in s_))
    if launch == 0:
        n, err, bad_, gd = region_shift(st_, cw, 30000, 9000, 0, [])
        check(f"a region of 9 000 frames (3/8 beat), Beat Count Auto, Sync 1/16, Slip 480, {name}: 0 ticks per step, every "
              f"segment latched (30 000, 9 000, slip_f 0), frames {lo_:.0f} .. {hi_:.0f}, nothing outside the region; one pass, "
              f"every sample and gain as stock's playing the 9 000 frames alone ({n} samples)",
              ok and len(s_) == 1 and n > 8000 and err <= 0.02 and bad_ == 0 and gd == 0, (lat, out, lo_, hi_, s_, n, err, bad_, gd))
    else:
        per = sorted({b_[0] - a_[0] for a_, b_ in zip(s_, s_[1:])})
        check(f"  ...{name}: the same, a pass every {per} samples (no grid: on its own length, as stock's 9 000-frame file "
              f"every {sorted({b_[0] - a_[0] for a_, b_ in zip(starts(st_['rig']), starts(st_['rig'])[1:])})}), "
              f"{z} zero-gain samples, peak {pk:.3f} (stock {pks:.3f}: a 0-beat clip restarts early, README Known issues)",
              ok and len(s_) >= 4 and per == [8875] and z == 0 and pk < 2.0, (lat, out, lo_, hi_, s_[:5], per, z, pk))

# A region grown from under half a beat while it plays. The 9 000-frame region of 3/8 beat (Beat Count
# Auto: 0 ticks, no grid; Sync 1/16, Toggle) gets Loop End 78 000 at block 300: 2 beats, grid 1 920. Its passes started
# where its length ended them, so no wrap is ever on the new grid, and waiting for one would hold the old region until a
# stop and a relaunch. The next wrap's recompute takes it (the pass it starts was made with the old one: the one after plays
# it). That pass starts off the grid (where the old one ended), and stock's own snaps put it back on: its step 1 on the
# 1/16 grid (a gap of up to half a step) and its end on the grid point nearest the end, which lies before it (the last
# step overlaps the next pass at gain 2, as on stock's own live Beat Count change); from the pass after that, every
# pass starts on the 1 920 grid and plays [30 000, 78 000)
def grow(rr):
    if rr.block == 300:
        rr.param(0x92, 78000)


cw = audio(frames=96000, beats=0, sync=5, points=(30000, 39000, 1), cell=0x102, blocks=1700, pre=grow)
r = cw["rig"]
T_GROW = 287000 + 300 * N
s_ = starts(r)
took = [a for a, st, fr in s_ if a > T_GROW and st == 0 and fr == 0]
reg_now = region_bank(r.m, 6)
fr = cw["frame"]
t_ = cw["base"] + np.arange(len(fr))
new_from = took[1] if len(took) > 1 else 1 << 30                # the first pass made after the recompute that took it
after = ~np.isnan(fr) & (t_ >= new_from)
out = int(((fr[after] < 30000 - 0.02) | (fr[after] > 77999 + 0.02)).sum())
tw = (t_ >= new_from) & (t_ < (took[3] if len(took) > 3 else 0))   # the off-grid pass and the one its end snaps back
gl = cw["gain"][tw]
gr = cw["gain"][t_ >= (took[3] if len(took) > 3 else 1 << 30)]
zw = int((np.abs(gl) < 1e-7).sum())
check(f"a region grown from 3/8 beat to 2 beats while it plays: taken at the next wrap (the change at {T_GROW}; "
      f"pass starts {took[:6]}), the region now {reg_now}; two passes after it every pass starts on the 1 920-tick grid "
      f"(48 000 samples) and from the first one made with it all play inside [30 000, 78 000) ({out} samples outside, "
      f"frames up to {np.nanmax(fr[after]) if after.any() else None:.0f}); the two passes stock's snaps bring back to "
      f"the grid: a gap of {zw} samples, {int((gl > 1 + 1e-6).sum())} samples above gain 1 (peak {gl.max() if len(gl) else 0:.2f}: "
      f"each under a 1/16 step, 6 000 samples, and its crossfades); then gain 1 ({gr.max() if len(gr) else 0:.2f} max), no zero-gain sample "
      f"({int((np.abs(gr) < 1e-7).sum())})",
      reg_now == (30000, 48000) and len(took) >= 5 and took[0] - T_GROW < 9000 + 2 * N and took[1] - took[0] < 9000 + N
      and all(a % 48000 == 0 for a in took[3:]) and out == 0 and np.nanmax(fr[after]) > 70000
      and zw < 6000 and (gl > 1 + 1e-6).sum() < 6000 + 4 * 256 and abs(gr.max() - 1) < 1e-5 and not (np.abs(gr) < 1e-7).any(),
      (reg_now, took[:6], out, zw, (gl > 1 + 1e-6).sum(), gr.max()))

# a region change while the pad plays: heard at the next wrap, no added silence
for name, change in (("new loop points (Loop End 96 000 -> 48 000, Region Auto)", lambda rr: rr.param(0x92, 48000)),
                     ("Region File -> Auto over a loop it already had", lambda rr: store(rr.m, 6, {0x4: 500, P_REGION: AUTO}))):
    first = (0, 96000, 1) if "points" in name else (0, 48000, 1)
    reg0 = None if "points" in name else FILE
    kw = dict(frames=96000, beats=0, cell=0x102, points=first, region=reg0, blocks=1500)
    ref_ = audio(**kw)
    cw = audio(pre=lambda rr: change(rr) if rr.block == 265 else None, **kw)
    r, rr_ = cw["rig"], ref_["rig"]
    W = 288000 + 96000                                        # the first wrap after the change
    up_to = (W - 287000) // N - 1
    same_before = all(np.array_equal(x, y) for x, y in zip(rr_.out[:up_to], r.out[:up_to]))
    s_ = [(a, st_, fr) for a, st_, fr in starts(r) if a >= W][:5]
    out, _, peak = inside(cw, 0, 48000, W + 300)
    zr = set(np.where(np.abs(ref_["gain"]) < 1e-7)[0] + ref_["base"])
    zc = set(np.where(np.abs(cw["gain"]) < 1e-7)[0] + cw["base"])
    lim = cw["base"] + len(cw["gain"]) - N
    added = sorted(x for x in zc - zr if 321000 <= x < lim)
    check(f"live, {name}, inside step 1 of the first pass: every output sample identical to no change up to the wrap at "
          f"{W}; from it the new region (steps {s_}), nothing outside [0, 48 000), no zero-gain sample that the run without "
          f"the change does not have ({len(added)} added; it keeps stock's notch at {W} - that pass's last step was made "
          "before the change was taken)", same_before and s_[:3] == [(W, 0, 0), (W + 24000, 1, 24000), (W + 48000, 0, 0)]
          and out == 0 and not added and peak <= 1.0 + 1e-6, (same_before, s_, out, added[:5], peak))

# region -> region while it plays, Slip 480 (slip_f 12 000 over either): [24 000, 72 000) -> [6 000, 54 000), both 2 beats.
# Changed inside step 0 it is heard at the next wrap; inside the pass's last Sync step, at the one after: the next
# pass's step 0 is made, and the wrap's recompute run, when the last step starts sounding (README)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, blocks=1300, slip=480)
ref_ = audio(**kw)
zr = set(np.where(np.abs(ref_["gain"]) < 1e-7)[0] + ref_["base"])
for blk, W, when in ((100, 336000, "inside step 0"), (265, 384000, "inside step 1, the last Sync step")):
    cw = audio(pre=lambda rr, blk=blk: (rr.param(0x91, 6000), rr.param(0x92, 54000)) if rr.block == blk else None, **kw)
    r = cw["rig"]
    up_to = (W - 287000) // N - 1
    same_before = all(np.array_equal(x, y) for x, y in zip(ref_["rig"].out[:up_to], r.out[:up_to]))
    out, z, pk = inside(cw, 6000, 48000, W + 300)
    zc = set(np.where(np.abs(cw["gain"]) < 1e-7)[0] + cw["base"])
    added = sorted(x for x in zc - zr if 290000 <= x < cw["base"] + len(cw["gain"]) - N)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    s_ = [x for x in starts(r) if x[0] >= W][:3]
    check(f"live, region -> region, Slip 480, {when} (sample {287000 + blk * N}): every output sample as without the "
          f"change up to the wrap at {W}, from it the new region (steps {s_}; latched {lat[:1]}), nothing outside "
          f"[6 000, 54 000), no zero-gain sample added ({len(added)}), peak {pk:.3f}",
          same_before and s_ == [(W, 0, 0), (W + 24000, 1, 24000), (W + 48000, 0, 0)] and out == 0 and not added
          and pk <= 1.0 + 1e-6 and lat and all(x == (6000, 48000, 12000) for x in lat), (same_before, s_, out, added[:5], pk, lat))

# a change that makes the clip longer moves stock's wrap grid (+0x230 = min(Quant, clip)): a pass that does not start on
# it has its end snapped back into the past. Stock does that on a live Beat Count change (2 -> 4 beats, Quant 1 bar):
# two passes start at once over the last step (gain 2), then the bar. The region waits for a wrap on its grid (H3').
st_ = audio(frames=96000, beats=2, image=STOCK, cell=0x102, blocks=2400, pre=lambda rr: rr.param(0xD2, 4) if rr.block == 100 else None)
cw = audio(frames=192000, beats=0, points=REG, cell=0x102, blocks=2400, pre=lambda rr: rr.param(0x92, 120000) if rr.block == 100 else None)
ws, wc = wraps_at(st_["rig"], 0), wraps_at(cw["rig"], 0)
gs, gc = st_["gain"][:len(st_["gain"]) - N], cw["gain"][:len(cw["gain"]) - N]
out, z, pk = inside(cw, 24000, 96000, 384000 + 300)
check(f"live, 2 beats -> 4 inside step 0 (Loop End 72 000 -> 120 000, mid-bar wrap at 336 000): stock's Beat Count change "
      f"starts passes at {ws[:5]} ({int((gs > 1 + 1e-6).sum())} samples above gain 1, peak {gs.max():.2f}); the region keeps "
      f"its 2 beats to the bar and plays the 4 from it: {wc[:5]}, {int((gc > 1 + 1e-6).sum())} samples above 1, "
      f"{z} zero-gain, nothing outside [24 000, 120 000)",
      ws[2] < 480000 - 48000 and gs.max() > 1.9 and wc[:5] == [288000, 336000, 384000, 480000, 576000] and not (gc > 1 + 1e-6).any()
      and z == 0 and out == 0, (ws[:6], wc[:6], gs.max(), gc.max(), z, out))

# region -> File while it plays (Region Auto -> File), inside step 0: the file's 4 beats wait for the bar, from which it
# plays as the stock image plays the file (the region's last step, seamless, crossfades into it: no notch there)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, blocks=1700, region=AUTO)
ref_ = audio(**kw)
st_ = audio(frames=96000, beats=0, image=STOCK, cell=0x102, blocks=1700)
cw = audio(pre=lambda rr: store(rr.m, 6, {0x4: 500, P_REGION: FILE}) if rr.block == 100 else None, **kw)
r = cw["rig"]
up_to = (384000 - 287000) // N - 1
same_before = all(np.array_equal(x, y) for x, y in zip(ref_["rig"].out[:up_to], r.out[:up_to]))
s_ = [x for x in starts(r) if x[0] >= 336000][:7]
lo, w = window(st_, cw)
at = lo + np.arange(len(w["frame"][0]))
keep = at >= 384000 + 300
fs, fc = w["frame"][0][keep], w["frame"][1][keep]
both = ~np.isnan(fs) & ~np.isnan(fc)
gdiff = int((np.abs(w["gain"][0][keep] - w["gain"][1][keep]) > 1e-6).sum())
zc = sorted(x for x in np.where(np.abs(cw["gain"][:len(cw["gain"]) - N]) < 1e-7)[0] + cw["base"] if x > 290000)
zs = sorted(x for x in np.where(np.abs(st_["gain"][:len(st_["gain"]) - N]) < 1e-7)[0] + st_["base"] if x > 290000)
check(f"live, region -> File inside step 0: as without the change up to the bar at 384 000 (the region at 336 000 too), "
      f"then the file's 4 beats ({s_}); from there every sample and gain as the stock image's ({int(both.sum())} samples, "
      f"{gdiff} gains differ); zero-gain samples {zc} (stock {zs}: its notch at 384 000 is the region's crossfade here), "
      f"no latch, peak {cw['gain'].max():.3f}",
      same_before and s_ == [(336000, 0, 0), (360000, 1, 24000), (384000, 0, 0), (408000, 1, 24000), (432000, 2, 48000),
                             (456000, 3, 72000), (480000, 0, 0)] and both.sum() > 90000 and np.abs(fs[both] - fc[both]).max() <= 0.02
      and gdiff == 0 and zc == [x for x in zs if x > 384000 + 300] and zs and bank_valid(r.m, 6) == 0 and cw["gain"].max() <= 1.0 + 1e-6,
      (same_before, s_, int(both.sum()), gdiff, zc, zs))

# unsynced: Sync None, the restart takes it
cw = audio(frames=96000, beats=0, sync=6, cell=0x102, points=(0, 96000, 1), blocks=2000,
           pre=lambda rr: rr.param(0x92, 48000) if rr.block == 300 else None)
r = cw["rig"]
s_ = starts(r)
after = [(a, fr) for a, st_, fr in s_ if a > 288000 + 38400]
out, zeros, peak = inside(cw, 0, 48000, after[1][0] + 300 if len(after) > 1 else 0)
check(f"live, Sync None (the unsynced wrap, 0x08066e9e): the restart made after the change plays [0, 48 000) and the "
      f"next comes 48 000 samples on (seamless: no end, so not stock's len - 257) ({[a for a, _ in after[:4]]}); nothing "
      f"outside it from there, {zeros} zero-gain samples, peak {peak:.3f}",
      len(after) >= 3 and after[0][0] == 288000 + 96000 - 257 and after[1][0] - after[0][0] == 96000 - 257
      and after[2][0] - after[1][0] == 48000 and out == 0 and zeros == 0 and peak <= 1.0 + 1e-6, (s_[:5], out, zeros, peak))

# rate != 1 and stereo: a 44.1 kHz stereo file, the region one second of it (2 beats)
st_ = [scenario(dc=dc, frames=44100, src_rate=44100, stereo=True, beats=0, image=STOCK, cell=0x102) for dc in (True, False)]
cw_ = [scenario(dc=dc, frames=88200, src_rate=44100, stereo=True, beats=0, points=(22050, 66150, 1), slip=480, cell=0x102)
       for dc in (True, False)]
for ch in (0, 1):
    a, b = decode(*st_, ch), decode(*cw_, ch)
    sf = slip_f(480, 44100, 1920)
    w_ = wraps_at(cw_[1], 288000)
    n, err, bad_, gd = region_shift(a, b, 22050, 44100, sf, w_, edge=3)
    check(f"44.1 kHz stereo ({'right' if ch else 'left'}), region [22 050, 66 150) of 88 200, Slip 480: every sample away "
          f"from the wraps plays 22 050 + (stock's frame + slip_f) mod 44 100 ({n} samples, max {err:.4f}; the 3 frames at "
          "each end of stock's file aside), gain as stock's",
          n > 40000 and err <= 0.02 and bad_ == 0 and gd == 0, (n, err, bad_, gd))

# a new file under a pad playing a region (5b's chain, Beat Count Auto): the latch keeps the FILE's length, not the
# region's. The segments latched for the region read as stock reads, at their own positions in the new file; the next
# ones latch the new file: the region again when it fits there (a playing pad takes new loop points at its wrap), else
# the file. Slip on top, against the same run at Slip 0.
for length, slip in ((50000, 0), (50000, 960), (192000, 960)):
    sc = dict(frames=96000, beats=0, cell=0x102, blocks=900, points=REG, pre=new_file(length))
    rr = scenario(slip=slip, **sc)
    cw = decode(scenario(dc=True, slip=slip, **sc), rr)
    old = {m_["sid"] for m_ in rr.made if m_["block"] < SWAP}
    rows = [x for x in rr.reads if x[0] >= SWAP + CLOSED and x[SID] in old]
    moved = [x for x in rows if not x[FET] or x[FET][0][1] != x[POS]]
    past = [f for f in rr.fetches if f[0] >= SWAP + CLOSED and f[1] + f[2] > length + 0xFF]
    t = cw["base"] + np.arange(len(cw["gain"]))
    quiet = int(((t >= T_OPEN) & (np.abs(cw["gain"]) < 1e-7)).sum())
    rs, vlen = (24000, 48000) if length >= 72000 else (0, length)
    sf = slip_f(slip, vlen, 1920)
    held = [(latch(rr.m, 6, k), made_for(rr.m, 6, k)) for k in range(4) if bank_valid(rr.m, 6) >> k & 1]
    fresh = [m_ for m_ in rr.made if m_["block"] > SWAP + CLOSED + 1]
    t_new = min((x[AT] for x in rr.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
    want_held = [((rs, vlen, sf), length)] * len(held) if (slip or rs) else []
    check(f"Region Loop [24 000, 72 000) of 96 000, Slip {slip}, a {length}-frame file under the playing pad from {T_SWAP}: "
          f"the segments latched for the region (made for 96 000) read as stock reads from the file opening on, at their "
          f"own positions in the new file ({len(rows)} reads, {len(moved)} mapped), nothing fetched past the new end + 0xff, "
          f"no silent sample ({quiet}); the segments made since latch {want_held[:1] or 'nothing (File, Slip 0: stock)'}"
          + (" (the region fits the new file)" if rs else " (the region does not fit: the file)"),
          len(rows) > 200 and not moved and not past and quiet == 0 and held == want_held and t_new == 360000,
          (len(rows), moved[:2], past[:2], quiet, held, t_new))
    if slip:
        ref0 = decode(scenario(dc=True, **sc), scenario(**sc))
        lo, w = window(ref0, cw)
        f0, fc = w["frame"]
        g0, gc = w["gain"]
        span = lo + np.arange(len(f0)) >= t_new + 256
        ok_ = ~np.isnan(f0) & ~np.isnan(fc) & span
        want = rs + np.mod(f0 - rs + sf, vlen)
        err = np.abs(fc - want)
        err = np.minimum(err, vlen - err)[ok_]
        gd = int(((np.abs(g0 - gc) > 1e-6) & span).sum())
        check(f"  from the end of the first new segment's crossfade ({t_new + 256}) every sounding sample plays "
              f"{rs} + (the Slip 0 run's frame - {rs} + {sf}) mod {vlen} ({int(ok_.sum())} samples, max "
              f"{float(err.max()) if len(err) else 9e9:.4f} frame), summed gain = the Slip 0 run's",
              ok_.sum() > 20000 and len(err) and err.max() <= 0.02 and gd == 0, (int(ok_.sum()), gd))

# gating: where a region does not apply, every hook passes through (as the hooks out), the loop points set
for name, kw in (("a Slicer pad (no markers)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Clip pad, Sync = Slice, with markers (H1')", dict(sync=0, setup=slicer_setup(MK))),
                 ("no SDRAM block", dict(block=False)),
                 ("fw_src_len 0x10000000", dict(frames=0x10000000))):
    a = scenario(points=REG, region=LOOP, cell=0x102, blocks=500, **kw)
    b = scenario(points=REG, region=LOOP, cell=0x102, blocks=500, bypass=True, **kw)
    ok, d = same(a, b)
    check(f"Region Loop over [24 000, 72 000), {name}: plays as with the hooks out, no latch", ok and bank_valid(a.m, 6) == 0, d)
a = scenario(points=REG, region=LOOP, cell=0x102, blocks=400, frames=0)
b = scenario(points=REG, region=LOOP, cell=0x102, blocks=400, frames=0, bypass=True)
ok, d = same(a, b, True)
check(f"Region Loop, fw_src_len 0 (not open): nothing plays, as with the hooks out ({len(a.reads)} reads)", ok, d)
a = scenario(points=REG, region=LOOP, cell=0x401, blocks=400)
b = scenario(points=REG, region=LOOP, cell=0x401, blocks=400, bypass=True)
ok, d = same(a, b)
check("Region Loop on cell 0x401 (no pad): as with the hooks out, nothing in the bank",
      ok and not any(region_bank(a.m, q)[1] for q in range(16)), d)

# every write clipwin.c makes in a Region run lands in the bank
w = []
r = Rig(cell=0x102, h=True)
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u_, acc, addr, size_, v, d_: w.append((addr, size_)) if any(
    a_ <= u_.reg_read(UC_ARM_REG_PC) < b_ for a_, b_ in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
store(r.m, 6, {0x4: 500, P_SLIP: 7, P_REGION: AUTO})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), rr.param(0x92, 48000) if rr.block == 200 else None)
r.params(beats=0)
r.goto(287000 - N)
for pid, v in zip((0x91, 0x92, 0x8E), (24000, 72000, 1)):
    r.param(pid, v)
r.step_block()
r.goto(287000)
r.note_on()
r.run(700)
hit = {name: any(lo <= a_ - BANK < hi for a_, s_ in w) for name, lo, hi in (("wrap", B_WRAP, B_WRAP + 1), ("region", B_REGION, B_GOOD))}
check(f"in a Region run, every write clipwin.c makes into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (wrap and "
      f"region written: {hit})", w and all(hit.values()) and all(BANK <= a_ and a_ + s_ <= BANK + B_SIZE for a_, s_ in w)
      and region_bank(r.m, 6) == (24000, 24000), (sorted({hex(a_) for a_, s_ in w if not BANK <= a_ < BANK + B_SIZE})[:4], region_bank(r.m, 6)))

# ====================================================================================================== 11. Loop Len
# Loop Len (README section 3, notes/re/a2 k_looplen): only a window of W ticks loops, on the clock, where the music
# was when it was engaged. Each segment H1 makes plays the window's step that lines up with its own, w = (origin + ((j x
# tps - origin) mod W)) / tps, from (int)((float)w x fps) (+ slip_f): stock's own product. origin = the phase of the
# sounding segment that started last, rounded down to W. A W the steps do not divide forces the pad's Sync through the
# class-B param-set (0x94), given back on Off as the app's store has it; never while a launch waits for its bar.
# Reference: the research model's numbers (a2/r2/k_looplen.out: L1 origin 7 680, steps 3 and 0 replaying 192 000; L2
# origin 1 200, Sync 1/16 forced, the next segment at 324 000 and every one after playing 30 000, Sync 1/4 back and step
# 2 at 432 000 playing 48 000; L3 every later step replaying 48 000; L4 the engage held until the launch sounded, the
# launch on its bar with +0x140 = 11 520), the same run with Loop Len never on (same gains, sample for sample, where the
# Sync is not forced), and the formula above, evaluated per segment from what H1 saw.
def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def fl(w, fps):
    """stock's first frame of step w: vcvt.f32.u32, vmul.f32 by +0x1fc, vcvt.s32.f32 (truncation)"""
    return int(f32(float(w) * fps))


def want_first(m_, sf=0, vlen=None):
    """the frame segment m_ starts on, from what H1 saw: its step, the pad's steps, the bank's Loop Len and origin"""
    j, tps, n, o = m_["step"], m_["tps"], m_["n"], m_["origin"]
    W = 240 << (m_["ll"] - 1) if m_["ll"] else 0
    w = (o + (j * tps - o) % W) // tps if W and W < tps * n and not W % tps and not o % tps else j
    f = fl(w, m_["fps"]) + sf
    return f % vlen if vlen else f


LL_SETTLE = int(re.search(r"#define LL_SETTLE\s+(\d+)", open("src/clipwin_b2.c").read()).group(1))
SETTLE_BLOCKS = 16 * LL_SETTLE                       # a pad is polled every 16 blocks


def ll_pre(events, slip=0, sync=3, region=None, then=None, settled=True):
    """pre_block: the pad's store as the app keeps it (Sync, Slip, Loop Len) with Loop Len set at the blocks in
    `events` {block: value}; the bank's Loop Len state after each block's poll in rr.llog. A value other than Off is taken
    once it has settled, LL_SETTLE polls after the one that saw it. settled: such a value is
    written SETTLE_BLOCKS earlier (but a poll after the event before it), as a hand that stopped on it that long before,
    so that the poll takes it at the block, as if it took a value at once; Off is taken at once, at its block"""
    if settled:
        moved, last = {}, -17
        for b_ in sorted(events):
            nb = max(b_ - SETTLE_BLOCKS, last + 17, 0) if events[b_] else b_   # each value polled once at least
            moved[nb], last = events[b_], nb
        events = moved

    def pre(rr):
        if not hasattr(rr, "llog"):
            rr.llog = []
        q = rr.q
        rr.llog.append((rr.block, rr.m.r8(BANK + B_LL + q), rr.m.r32(BANK + B_ORIGIN + 4 * q), rr.m.r8(BANK + B_FORCED + q),
                        rr.i64(rr.pad + 0x220)))
        if rr.block in events:
            store(rr.m, q, {0x4: 500, P_SLIP: slip, P_SYNC: sync, P_LOOPLEN: events[rr.block],
                            **({} if region is None else {P_REGION: region})})
        if then:
            then(rr)
    return pre


def taken(r, ll):
    """the first block whose poll took Loop Len `ll`, and the state then (block, ll, origin, forced, Sync ticks)"""
    for i, x in enumerate(r.llog):
        if x[1] == ll and (i == 0 or r.llog[i - 1][1] != ll):
            return x
    return None


def seg_firsts(d, after=0, rate=1.0):
    """each segment that sounded alone somewhere, from sample `after`: (its first sample, step, the frame it started on,
    read back from the first sample it sounds alone, at `rate` source frames a sample)"""
    r = d["rig"]
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    out = []
    for m_ in r.made:
        s0 = first.get(m_["sid"])
        idx = np.where(d["sid"] == m_["sid"])[0]
        if s0 is None or not len(idx) or s0 < after:
            continue
        out.append((s0, m_["step"], int(round(d["frame"][idx[0]] - (d["base"] + idx[0] - s0) * rate))))
    return sorted(out)


def follows(d, sf=0, rs=0, vlen=None, after=0, rate=1.0, off=0.0, tol=0.02):
    """every sample where one segment sounds (from `after`): plays rs + (want_first(its segment) + the samples since it
    started x rate) mod vlen, read back `off` frames on (the reader's own at rate != 1). Returns (samples, max error,
    samples off by more than `tol` frame)"""
    r = d["rig"]
    vlen = vlen or r.len
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    by = {m_["sid"]: m_ for m_ in r.made}
    f, sid, base = d["frame"], d["sid"], d["base"]
    at = base + np.arange(len(f))
    ok = ~np.isnan(f) & (sid > 0) & (at >= after)
    want = np.full(len(f), np.nan)
    for s_ in set(sid[ok].tolist()):
        m_ = by.get(s_)
        if m_ is None or m_["how"] != "H1" or s_ not in first:
            ok &= sid != s_
            continue
        sel = ok & (sid == s_)
        want[sel] = rs + np.mod(want_first(m_, sf, vlen) + (at[sel] - first[s_]) * rate + off, vlen)
    err = np.abs(f - want)[ok]
    err = np.minimum(err, vlen - err)
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > tol).sum())


def zeros_after(d, start):
    g = d["gain"][:len(d["gain"]) - N]
    return {int(x) + d["base"] for x in np.where(np.abs(g) < 1e-7)[0] if x + d["base"] >= start}


def same_gain(a, b, start):
    lo, w = window(a, b)
    at = lo + np.arange(len(w["gain"][0]))
    keep = at >= start
    return int((np.abs(w["gain"][0][keep] - w["gain"][1][keep]) > 1e-6).sum())


# L1: Quant 1 beat < Sync 1 bar, a 16-beat 384 000-frame clip launched on beat 2 (tick 8 640): stock's phase is its step
# index, not ticks - launch. Engaged 1 bar inside step 2 (sounding frame ~195 520, phase ~7 821), Off two bars on.
eng = (387520 - 200000) // N
kw = dict(frames=384000, beats=16, quant=5, sync=1, at=200000, blocks=3900, vals={P_SYNC: 1})
ref_ = audio(pre=ll_pre({}, sync=1), **kw)
cw = audio(pre=ll_pre({eng: 5, eng + 1500: 0}, sync=1), **kw)
r = cw["rig"]
on, off = taken(r, 5), taken(r, 0) if taken(r, 5) else None
off = next((x for x in r.llog if on and x[0] > on[0] and x[1] == 0), None)
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
zc, zr = zeros_after(cw, 200000), zeros_after(ref_, 200000)
check(f"Loop Len 1 bar engaged inside step 2 of a 16-beat clip launched on beat 2 (Quant 1 beat < Sync 1 bar; taken at "
      f"block {on and on[0]}, sample {on and 200000 + on[0] * N}): origin {on and on[2]} (a2/r2 k_looplen L1: 7 680; ticks - "
      f"launch would give 3 840), Sync left alone; steps 3 and 0 replay the bar that was playing, from 192 000 ({sg[:4]})",
      on and on[2] == 7680 and on[3] == 0 and on[4] == 3840 and sg[:3] == [(384000, 2, 192000), (480000, 3, 192000), (576000, 0, 192000)],
      (on, sg[:4]))
check(f"  Off two bars on (block {off and off[0]}): step 1 at 672 000 plays its own 96 000 again, in phase, as without Loop "
      f"Len ({sg[3:4]}); every sample plays its segment's step of the window from its first frame ({n_} samples, max error "
      f"{err:.4f}); summed gain = the run without Loop Len at every sample ({same_gain(ref_, cw, 200000)} differ), no zero-gain "
      f"sample added ({len(zc - zr)})", off and sg[3:4] == [(672000, 1, 96000)] and n_ > 300000
      and err <= 0.02 and bad_ == 0 and same_gain(ref_, cw, 200000) == 0 and not zc - zr, (off, sg[3:6], n_, err, bad_))

# L2: the matched 4-beat clip, Sync 1/4, Loop Len 1/16 engaged inside step 1 (frame ~33 000): W < a Sync step, so the
# pad's Sync is forced to 1/16 and stock re-grids the playing segment; Off one bar on gives Sync 1/4 back.
kw = dict(frames=96000, at=193000, blocks=2600, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}), **kw)
cw = audio(pre=ll_pre({1000: 1, 1750: 0}), **kw)
r = cw["rig"]
on = taken(r, 1)
off = next((x for x in r.llog if on and x[0] > on[0] and x[1] == 0), None)
sg = seg_firsts(cw, 318000)
during = [x for x in sg if x[0] < 418000]
n_, err, bad_ = follows(cw)
zc, zr = zeros_after(cw, 288300), zeros_after(ref_, 288300)
check(f"Loop Len 1/16 engaged inside step 1 with Sync 1/4 (taken at sample {on and 193000 + on[0] * N}): origin {on and on[2]} "
      f"(L2: 1 200), Sync forced to 1/16 (+0x220 {on and on[4]}, forced {on and on[3]}); the playing segment re-gridded, the "
      f"next at 324 000 and every one after it, a 1/16 apart, replaying frame 30 000 ({during[:3]} ... {len(during)} segments)",
      on and on[2] == 1200 and on[3] == 1 and on[4] == 240 and during and during[0][0] == 324000
      and all(x[2] == 30000 for x in during) and [x[0] for x in during] == list(range(324000, 324000 + 6000 * len(during), 6000))
      and len(during) >= 15, (on, during[:4], len(during)))
after = [x for x in sg if x[0] >= 418000][:4]
st_ = audio(frames=96000, at=193000, blocks=2600, image=STOCK, pre=lambda rr: rr.param(P_SYNC, 5) if on and rr.block == on[0]
            else rr.param(P_SYNC, 3) if off and rr.block == off[0] else None)
same_starts = [x[:2] for x in starts(r)] == [x[:2] for x in starts(st_["rig"])]
check(f"  the timing is stock's own Sync change: every segment start and the summed gain at every sample as the stock image "
      f"sent Sync 1/16 and 1/4 in those two blocks ({same_starts}, {same_gain(st_, cw, 288300)} samples differ)",
      on and off and same_starts and same_gain(st_, cw, 288300) == 0, (starts(r)[:12], starts(st_["rig"])[:12]))
check(f"  Off one bar on (block {off and off[0]}): Sync 1/4 given back (+0x220 {off and off[4]}, forced {off and off[3]}), the "
      f"next segment step 2 on the beat at 432 000 playing 48 000, in phase ({after}); every sample plays its segment's "
      f"step of the window ({n_} samples, max error {err:.4f}); no zero-gain sample added ({sorted(zc - zr)[:4]}), peak "
      f"{cw['gain'].max():.3f}", off and off[3] == 0 and off[4] == 960 and after[:3] == [(432000, 2, 48000), (456000, 3, 72000),
                                                                                 (480000, 0, 0)]
      and n_ > 150000 and err <= 0.02 and bad_ == 0 and not zc - zr and cw["gain"].max() <= 1.0 + 1e-6, (off, after, n_, err, bad_, sorted(zc - zr)[:5]))

# L3: a launch 300 samples late (+0x140 = 11 532), Loop Len 1/4 inside step 2: a one-beat stutter of the beat that was
# playing - every later step replays 48 000, the summed gain stock's sample for sample
kw = dict(frames=96000, at=288300, blocks=1800, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}), **kw)
cw = audio(pre=ll_pre({400: 3}), **kw)
r = cw["rig"]
on = taken(r, 3)
sg = seg_firsts(cw, 336000)
n_, err, bad_ = follows(cw)
check(f"Loop Len 1/4 inside step 2 of a launch 300 samples late (+0x140 {r.layer()['launch_tick']}): origin {on and on[2]} "
      f"(L3: 1 920), Sync 1/4 left alone; every step from 360 000 replays the beat at 48 000 ({sg[:6]}), every sample its "
      f"segment's ({n_} samples, max error {err:.4f}); summed gain = the run without Loop Len ({same_gain(ref_, cw, 288300)} differ)",
      r.layer()["launch_tick"] == 11532 and on and on[2] == 1920 and on[3] == 0 and sg[0] == (336000, 2, 48000)
      and [x[2] for x in sg[1:7]] == [48000] * 6 and [x[0] for x in sg[:7]] == list(range(336000, 336000 + 7 * 24000, 24000))
      and n_ > 100000 and err <= 0.02 and bad_ == 0 and same_gain(ref_, cw, 288300) == 0, (on, sg[:8], n_, err, bad_))

# L4: Loop Len set while the launch waits for its bar (the note at 193 000, the bar at 288 000): nothing until the launch
# has sounded - it keeps its bar, +0x140 and msg 0x1d - then taken from where it plays (origin 0), Sync forced to 1/16
kw = dict(frames=96000, at=193000, blocks=1300, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({20: 1}), **kw)
r = cw["rig"]
on = taken(r, 1)
sg = seg_firsts(cw, 0)
n_, err, bad_ = follows(cw)
check(f"Loop Len 1/16 set while the launch waits for its bar: not taken while it waits (taken at sample "
      f"{on and 193000 + on[0] * N}, after the launch at {sg[0][0] if sg else None}); the launch on its bar with +0x140 "
      f"{r.layer()['launch_tick']} and msg 0x1d; then origin {on and on[2]}, Sync 1/16 forced, every later segment replaying "
      f"frame 0 ({sg[1:5]}; {n_} samples follow their segment, max error {err:.4f})",
      on and 193000 + on[0] * N > 288000 and sg[0] == (288000, 0, 0) and r.layer()["launch_tick"] == 11520
      and [b_ for b_, t_, _ in r.posted if t_ == 0x1D] and on[2] == 0 and on[3] == 1 and on[4] == 240
      and all(x[2] == 0 for x in sg[2:]) and len(sg) >= 10 and n_ > 60000 and err <= 0.02 and bad_ == 0, (on, sg[:5], n_, err, bad_))

# changing it live keeps the in-point: 1/4 engaged inside step 2 (in-point 1 920 = frame 48 000), then 1/8 (Sync forced to
# 1/8), then 1/2 (the user's 1/4 divides the window again: given back): the window starts at 48 000 throughout, its
# out-point moves
kw = dict(frames=96000, at=287000, blocks=2200, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({400: 3, 900: 2, 1400: 4}), **kw)
r = cw["rig"]
t1, t2, t3 = taken(r, 3), taken(r, 2), taken(r, 4)
sg = seg_firsts(cw, 340000)
n_, err, bad_ = follows(cw)
s8 = [x for x in sg if t2 and t3 and 287000 + t2[0] * N + 12000 <= x[0] < 287000 + t3[0] * N]
s2 = [x for x in sg if t3 and x[0] >= 287000 + t3[0] * N + 12000]
check(f"Loop Len changed live 1/4 -> 1/8 -> 1/2: the in-point stays (origin {t1 and t1[2]}, {t2 and t2[2]}, {t3 and t3[2]}); at "
      f"1/8 Sync is forced to 1/8 (+0x220 {t2 and t2[4]}) and every step replays 48 000 ({s8[:3]}...); at 1/2 the user's "
      f"Sync 1/4 is given back (+0x220 {t3 and t3[4]}, forced {t3 and t3[3]}) and the window [48 000, 96 000) plays in 1/4 "
      f"steps, on the clock ({[x[2] for x in s2[:8]]}); every sample its segment's ({n_}, max {err:.4f})",
      t1 and t2 and t3 and t1[2] == t2[2] == t3[2] == 1920 and t2[4] == 480 and t2[3] == 1 and t3[4] == 960 and t3[3] == 0
      and s8 and all(x[2] == 48000 for x in s8) and len(s2) >= 4 and [x[0] % 24000 for x in s2] == [0] * len(s2)
      and all(x[2] == 48000 + 24000 * ((x[0] // 24000) % 2) for x in s2) and n_ > 150000 and err <= 0.02 and bad_ == 0,
      (t1, t2, t3, s8[:4], s2[:8], n_, err, bad_))

# a fast file (88 615 frames, fps 22 153.75 at Sync 1/4): each step of the window starts on stock's own float product
kw = dict(frames=88615, at=287000, blocks=1900, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({600: 4}), **kw)
r = cw["rig"]
on = taken(r, 4)
sg = seg_firsts(cw, 287000 + 600 * N + 2048 + 24000)
n_, err, bad_ = follows(cw)
w_ = [44307 if (x[0] // 24000) % 2 == 0 else 66461 for x in sg]
check(f"Loop Len 1/2 on 88 615 frames (taken in step 3, origin {on and on[2]}): the steps alternate (int)(2 x 22 153.75) = "
      f"44 307 and (int)(3 x 22 153.75) = 66 461 ({[x[2] for x in sg[:6]]}); every sample its segment's ({n_}, max {err:.4f})",
      on and on[2] == 1920 and len(sg) >= 5 and [x[2] for x in sg] == w_ and n_ > 100000 and err <= 0.02 and bad_ == 0,
      (on, sg[:8], n_, err, bad_))

# stacked: Region [24 000, 72 000) (Beat Count Auto: 2 beats), Slip 480 (slip_f 12 000), Loop Len 1/4 inside step 1 -
# the window is the region's beat 2, shifted by Slip within the region: every step plays 24 000 + (24 000 + 12 000) mod
# 48 000 on; gains as the same run without Loop Len (the seamless wrap included)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, slip=480, blocks=1500, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}, slip=480), **kw)
cw = audio(pre=ll_pre({300: 3}, slip=480), **kw)
r = cw["rig"]
on = taken(r, 3)
sg = seg_firsts(cw, 287000 + 300 * N + 2048 + 24000)
n_, err, bad_ = follows(cw, sf=12000, rs=24000, vlen=48000)
out, z, pk = inside(cw, 24000, 48000, 288300)
check(f"Loop Len 1/4 on Region [24 000, 72 000) with Slip 480 (taken at origin {on and on[2]}): every later step starts on "
      f"60 000 ({[x[2] for x in sg[:5]]}), every sample 24 000 + (its step's frame + 12 000) mod 48 000 ({n_}, max {err:.4f}); "
      f"nothing outside the region, summed gain = without Loop Len ({same_gain(ref_, cw, 288300)} differ), {z} zero-gain samples",
      on and on[2] == 960 and len(sg) >= 5 and all(x[2] == 60000 for x in sg) and n_ > 80000 and err <= 0.02 and bad_ == 0
      and out == 0 and z == 0 and same_gain(ref_, cw, 288300) == 0, (on, sg[:6], n_, err, bad_, out, z))

# where Loop Len does nothing: Quant None (no grid); Sync None (no clock phase: a1; forcing a Sync there would make
# stock's None-to-synced re-grid double a whole step at gain 2); a window of the whole clip or more (2 bars on 4 beats);
# a Slicer pad; Sync = Slice with markers - every read, fetch, sample and message as the same run without it, the pad's Sync
# untouched (the poll still drops the pending step when it takes the value, and stock makes it again: one more prefetch;
# on Sync = Slice with markers every segment starts in H1', so the poll never has the pad and never takes it)
for name, kw in (("Quant None", dict(quant=8)), ("Sync None", dict(sync=6)), ("2 bars on a 4-beat clip", dict(ll=6)),
                 ("a Slicer pad", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("Sync = Slice with markers", dict(sync=0, setup=slicer_setup(MK)))):
    ll = kw.pop("ll", 1)
    sync = kw.get("sync", 3)
    a = scenario(frames=96000, at=287000, blocks=700, vals={P_SYNC: sync}, pre=ll_pre({100: ll}, sync=sync), **kw)
    b = scenario(frames=96000, at=287000, blocks=700, vals={P_SYNC: sync}, pre=ll_pre({}, sync=sync), **kw)
    ok, d = same(a, b)
    check(f"Loop Len {'1/16' if ll == 1 else '2 bars'}, {name}: every read, fetch, sample and message as without it "
          f"({len(a.prefetches) - len(b.prefetches)} prefetch(es) more: the pending step made again), the pad's Sync "
          f"untouched (forced {a.m.r8(BANK + B_FORCED + a.q)}), no latch", d["reads"] and d["fetches"] and d["out"]
          and d["posted"] and a.m.r8(BANK + B_FORCED + a.q) == 0 and a.i64(a.pad + 0x220) == b.i64(b.pad + 0x220)
          and (taken(a, ll) or "markers" in name) and bank_valid(a.m, a.q) == 0, d)

# the app re-sends Sync (a turn of the Sync knob) while Loop Len holds it forced: the next poll forces it again
kw = dict(frames=96000, at=287000, blocks=1000, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({200: 1}, then=lambda rr: rr.param(P_SYNC, 3) if rr.block == 600 else None), **kw)
r = cw["rig"]
back = [x for x in r.llog if x[0] > 600 and x[4] == 960]
again = next((x for x in r.llog if x[0] > 600 and x[4] == 240), None)
n_, err, bad_ = follows(cw)
check(f"Sync re-sent as 1/4 while Loop Len 1/16 holds it at 1/16: forced again by the next poll ({len(back)} blocks on 1/4, "
      f"then {again}), every sample its segment's ({n_}, max {err:.4f})",
      again and 0 < len(back) <= 16 and again[3] == 1 and n_ > 80000 and err <= 0.02 and bad_ == 0, (back[:2], again, n_, err))

# a stopped pad: Loop Len set after a Toggle stop is taken at once (no music: the in-point is the clip's start) and its
# Sync forced while it is quiet; the next launch, on its bar, plays the first 1/16 over and over
kw = dict(frames=96000, at=287000, blocks=1960, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({900: 1}, then=lambda rr: rr.note_on() if rr.block in (300, 1000) else None), **kw)
r = cw["rig"]
on = taken(r, 1)
sg = seg_firsts(cw, 400000)
n_, err, bad_ = follows(cw)
quiet = cw["gain"][(on[0] * N + 287000 - cw["base"]) if on else 0:(480000 - cw["base"])] if on else np.ones(1)
check(f"Loop Len 1/16 set on a pad stopped by Toggle (taken at sample {on and 287000 + on[0] * N}, the pad silent from "
      f"there to the relaunch: {not np.abs(quiet).max() > 1e-7}): origin {on and on[2]}, Sync forced at once (+0x220 "
      f"{on and on[4]}); the relaunch on the bar at 480 000 and every 1/16 after it replay frame 0 ({sg[:4]}), every sample "
      f"its segment's ({n_}, max {err:.4f})", on and on[2] == 0 and on[3] == 1 and on[4] == 240 and not np.abs(quiet).max() > 1e-7
      and sg and sg[0] == (480000, 0, 0) and len(sg) >= 8 and all(x[2] == 0 for x in sg)
      and [x[0] for x in sg[:8]] == list(range(480000, 528000, 6000)) and n_ > 40000 and err <= 0.02 and bad_ == 0,
      (on, sg[:6], n_, err, bad_))

# the engage at rate != 1 (a 44.1 kHz file, rate 0.91875; notes/re/a1): the app sends Sync 1/2 late in step 1 of 1/4 and
# stock's re-index puts the playing segment on step 1 of 1/2 while it still plays frame 43 063 < (int)(1 x 44 100): its
# elapsed frames are negative. Loop Len 1/2 taken there (block 374, the clock at 1 875 ticks, in the first half) takes
# the first half (origin 0, signed; an unsigned difference gave 186 992 640, a frame 78 247 window); the re-indexed
# segment plays on to 384 000, then every step replays frame 0. Frames read back as the reader gives them at this rate:
# 1 frame on, +-0.1 (the run without Loop Len reads the same way)
def late_sync(rr, ll=None):
    """the app sends Sync 1/2 and stores it (its store keeps the pad's Loop Len, `ll`, if set)"""
    if rr.block == 370:
        rr.param(P_SYNC, 2)
        store(rr.m, rr.q, {0x4: 500, P_SLIP: 0, P_SYNC: 2, **({} if ll is None else {P_LOOPLEN: ll})})


kw = dict(frames=88200, src_rate=44100, at=287000, blocks=1300, vals={P_SYNC: 3}, cell=0x102)   # pad 6: polled at 374
RT = 44100 / 48000
ref_ = audio(pre=ll_pre({}, sync=2, then=late_sync), **kw)
cw = audio(pre=ll_pre({371: 4}, sync=2, then=lambda rr: late_sync(rr, 4)), **kw)
r = cw["rig"]
on = taken(r, 4)
sg, sr = seg_firsts(cw, 300000, RT), seg_firsts(ref_, 300000, RT)
n_, err, bad_ = follows(cw, rate=RT, off=1.0, tol=0.12)
nr, er, br = follows(ref_, rate=RT, off=1.0, tol=0.12)
check(f"Loop Len 1/2 on a 44.1 kHz file, taken where stock's re-index has put the playing segment a step ahead of its "
      f"position (block {on and on[0]}): origin {on and on[2]} (the clock's half, 1 875 ticks: 0), Sync 1/2 left alone; the "
      f"re-indexed segment plays on, then every step replays frame 0 ({sg[:4]}; without Loop Len {sr[:4]}); every sample "
      f"its segment's ({n_}, max {err:.3f} with the reader's 1-frame offset, as without it: {er:.3f}); summed gain = the run "
      f"without Loop Len ({same_gain(ref_, cw, 288300)} differ)",
      on and on[0] == 374 and on[2] == 0 and on[3] == 0 and on[4] == 1920 and len(sg) >= 3 and sg[0] == sr[0]
      and [x[:2] for x in sg[1:3]] == [(384000, 0), (432000, 1)] and [x[2] for x in sg[1:]] == [1] * (len(sg) - 1)
      and sr[2][2] == 44101 and n_ > 150000 and bad_ == 0 and br == 0 and nr > 150000
      and same_gain(ref_, cw, 288300) == 0, (on, sg[:5], sr[:5], n_, err, bad_, er, br))

# Off, then on again within the same Sync step (the stutter gesture): after Off the sounding segment still plays the
# window (frames 26 000 .. 34 000 at 362 000 .. 370 000), so the new engage takes its in-point from that frame, not from
# stock's unlooped position (72 000 + ..., which would give 2 880): the same beat, 24 000, from 384 000 on. (The value
# turned on again 18 blocks after Off settles LL_SETTLE polls after the poll that sees it, block 630: still inside that
# step.) Then Off at
# 415 000 (step 1: the steps after it play their own, 48 000 at 432 000) and on again at 453 400, inside step 2, where
# the sounding segment plays its own step: the in-point is where stock plays (1 920), 48 000 from 456 000 on
kw = dict(frames=96000, at=287000, blocks=1700, vals={P_SYNC: 3}, cell=0x102)   # pad 6: polled at 214 + 16k
cw = audio(pre=ll_pre({200: 3, 600: 0, 618: 3, 1000: 0, 1300: 3}), **kw)
r = cw["rig"]
tr = [x[:4] for i, x in enumerate(r.llog) if i and x[1] != r.llog[i - 1][1]]
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
fr = [cw["frame"][x - cw["base"]] for x in (362000, 366000, 370000)]
check(f"Loop Len 1/4 on, Off and on again inside one Sync step (taken at blocks {[x[0] for x in tr[:3]]}): the window "
      f"still sounding after Off ({fr}) gives the in-point again (origins {[x[2] for x in tr[:3]]}), and the steps from "
      f"384 000 replay 24 000; Off (block {tr[3][0] if len(tr) > 3 else None}) and on again inside step 2 (block "
      f"{tr[4][0] if len(tr) > 4 else None}): the in-point where stock plays (origin {tr[4][2] if len(tr) > 4 else None}) "
      f"({[x[::2] for x in sg if 384000 <= x[0] <= 480000]}); every sample its segment's ({n_}, max {err:.4f})",
      len(tr) == 5 and [x[1:3] for x in tr] == [(3, 960), (0, 960), (3, 960), (0, 960), (3, 1920)]
      and tr[1][0] < 627 < tr[2][0] < 640 + SETTLE_BLOCKS and 1300 < tr[4][0] < 1320 and fr == [26000.0, 30000.0, 34000.0]
      and [x[::2] for x in sg if 384000 <= x[0] <= 480000] == [(384000, 24000), (408000, 24000), (432000, 48000),
                                                                (456000, 48000), (480000, 48000)]
      and n_ > 150000 and err <= 0.02 and bad_ == 0, (tr, sg[:16], fr, n_, err, bad_))

# a pad stopped while Loop Len is on (taken inside step 1: in-point 960), then the store written again with the same
# Loop Len (as a preset reload leaves it), then relaunched: a stopped pad starts the window over at the clip's start, as
# a launch after power-on does (origin 0 from the first poll that sees it stopped), so the relaunch on the bar at 480 000
# and every step after it replay frame 0
kw = dict(frames=96000, at=287000, blocks=1960, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({200: 3, 850: 3}, then=lambda rr: rr.note_on() if rr.block in (700, 1000) else None), **kw)
r = cw["rig"]
on = taken(r, 3)
reset = next((x for x in r.llog if on and x[0] > on[0] and x[2] != on[2]), None)
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
quiet = cw["gain"][384300 - cw["base"]:480000 - cw["base"]]
check(f"Loop Len 1/4 taken inside step 1 (origin {on and on[2]}), the pad stopped by Toggle (silent from 384 300: "
      f"{not np.abs(quiet).max() > 1e-7}), its store written again with the same value, then relaunched: the in-point "
      f"is the clip's start again once the pad is stopped ({reset}); the relaunch on the bar at 480 000 and every step "
      f"after it replay frame 0 ({[x for x in sg if x[0] >= 480000][:4]}; before the stop {[x[2] for x in sg if x[0] < 400000]}); "
      f"every sample its segment's ({n_}, max {err:.4f})",
      on and on[2] == 960 and reset and reset[2] == 0 and 287000 + reset[0] * N < 384000 + 16 * N + 2048
      and not np.abs(quiet).max() > 1e-7 and [x[2] for x in sg if x[0] < 400000] == [24000] * 4
      and [x[:3] for x in sg if x[0] >= 480000][:3] == [(480000, 0, 0), (504000, 1, 0), (528000, 2, 0)]
      and n_ > 100000 and err <= 0.02 and bad_ == 0, (on, reset, sg[:10], n_, err, bad_))

# a new file under a pad playing a window (5b's chain; Loop Len latches at Slip 0 too): the segments latched for the old
# file read as stock reads, at their own positions in the new file, and the next ones latch the new file, the window's
# step played from the new file's frames per step (the in-point is in ticks: it stays)
for length in (50000, 192000):
    cw = audio(pre=ll_pre({100: 3}, then=new_file(length)), frames=96000, at=287000, blocks=900, vals={P_SYNC: 3})
    r = cw["rig"]
    on = taken(r, 3)
    old = {m_["sid"] for m_ in r.made if m_["block"] < SWAP}
    rows = [x for x in r.reads if x[0] >= SWAP + CLOSED and x[SID] in old]
    moved = [x for x in rows if (x[FET][0][1] != x[POS] if x[FET] else x[POS] < length)]
    held = [made_for(r.m, r.q, k) for k in range(4) if bank_valid(r.m, r.q) >> k & 1]
    fresh = [m_ for m_ in r.made if m_["block"] > SWAP + CLOSED + 1]
    t_new = min((x[AT] for x in r.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
    sg = seg_firsts(cw, t_new)
    n_, err, bad_ = follows(cw, after=t_new + 256, vlen=length)
    check(f"Loop Len 1/4 taken in step 0 (origin {on and on[2]}), a {length}-frame file under the playing pad from {T_SWAP}: the "
          f"segments latched for the old file read from the file opening on as stock reads, at their own positions in the new "
          f"file ({len(rows)} reads, {len(moved)} mapped; past its end nothing, as stock); the next ones latch the new "
          f"file (made for {sorted(set(held))}) and replay its frame 0 ({sg[:3]}), every sample its segment's step of the "
          f"window ({n_} samples, max {err:.4f})",
          on and on[2] == 0 and len(rows) > 200 and not moved and held and set(held) == {length}
          and t_new == 360000 and sg[:3] and all(x[2] == 0 for x in sg[:3]) and n_ > 20000 and err <= 0.02 and bad_ == 0,
          (on, len(rows), moved[:2], held, t_new, sg[:4], n_, err, bad_))

# The value is taken once it has settled. A turn from Off to 1/4 at speed 3 (one list value every 43 blocks, 115 ms:
# its fast end) passes 1/16 and 1/8: taken at once, 1/16 would set the in-point inside beat 2 (2 160, a 1/16 boundary),
# kept for 1/4, with Sync 1/16 forced, the window not starting on a beat (as seen on a unit). Only 1/4 is taken, LL_SETTLE polls after the one that saw it, on the beat playing then (an in-point of whole beats), the
# user's Sync left alone, and every step from the next one replays that beat. A slow step-through (each value held 375
# blocks, a second) still takes each value in turn, the in-point from the first; Off is taken at once
def ll_turn(events):
    kw = dict(frames=96000, at=287000, blocks=1500, vals={P_SYNC: 3}, cell=0x102)   # pad 6: polled at 214 + 16k
    d = audio(pre=ll_pre(events, settled=False), **kw)
    r_ = d["rig"]
    return d, [x for i, x in enumerate(r_.llog) if i and x[1] != r_.llog[i - 1][1]]


cw, tr = ll_turn({450: 1, 493: 2, 536: 3})
tb = tr[0][0] if tr else None
beat = (287000 + tb * N - 288000) % 96000 // 24000 if tr else None
sg = [x for x in seg_firsts(cw, 287000 + (tb or 0) * N + 24000)][:6]
syncs = {x[4] for x in cw["rig"].llog}
check(f"Loop Len turned Off -> 1/16 -> 1/8 -> 1/4 at blocks 450, 493, 536 (speed 3): only 1/4 is taken ({[x[:4] for x in tr]}), "
      f"at block {tb} (the poll {LL_SETTLE} polls after the one that saw it), in-point {tr[0][2] if tr else None} = beat "
      f"{beat} of the clip, the one playing then (a multiple of 960), the Sync never forced (pad +0x220 {sorted(syncs)}); "
      f"the steps after it replay frame {beat * 24000 if tr else None}: {[x[::2] for x in sg]}",
      [x[1] for x in tr] == [3] and tr[0][2] == beat * 960 and tr[0][3] == 0 and syncs == {960}
      and 536 + SETTLE_BLOCKS <= tb <= 536 + SETTLE_BLOCKS + 16 and len(sg) >= 3 and all(x[2] == beat * 24000 for x in sg),
      (tr, sg, syncs))
# ...a value every 56 blocks (149 ms: the slow end of speed 3), 64 (171 ms: speed 2's fast half), 81 (216 ms: the
# rest on 1/8 that 4 polls took on a unit) or 112 (299 ms), at four phases of the pad's
# poll: still only 1/4, on a whole beat. LL_SETTLE 3 took 1/16 or 1/8 on the way at 56 and 64, 4 at 81; at 112 blocks
# every value is seen by exactly LL_SETTLE polls, one short of being taken
sl = {}
for gap in (56, 64, 81, 16 * LL_SETTLE):
    for ph in (0, 4, 8, 12):
        cw, tr = ll_turn({450 + ph: 1, 450 + gap + ph: 2, 450 + 2 * gap + ph: 3})
        sl[gap, ph] = [x[:4] for x in tr]
check(f"...a value every 56, 64, 81 or {16 * LL_SETTLE} blocks (149, 171, 216, {16 * LL_SETTLE * N / 48:.0f} ms) at four poll "
      f"phases: only 1/4 is taken, on a whole beat, Sync not forced ({sl})",
      all([x[1] for x in t_] == [3] and t_[0][2] % 960 == 0 and t_[0][3] == 0 for t_ in sl.values()), sl)
cw, tr = ll_turn({450: 1, 825: 2, 1200: 3})
check(f"...a slow step-through (each value held 375 blocks, a second): each is taken in turn ({[x[:4] for x in tr]}), the in-point "
      "from the first (a 1/16 boundary inside beat 2) kept, as a value that stays is taken (changing it keeps the in-point)",
      [x[1] for x in tr] == [1, 2, 3] and len({x[2] for x in tr}) == 1 and tr[0][2] % 240 == 0 and tr[0][2] % 960
      and 1920 < tr[0][2] < 2880
      and all(e + 1 <= x[0] <= e + SETTLE_BLOCKS + 16 for e, x in zip((450, 825, 1200), tr)), tr)
cw, tr = ll_turn({450: 3, 800: 0})
check(f"...and Off is taken at once, at the first poll after it ({[x[:4] for x in tr]})",
      [x[1] for x in tr] == [3, 0] and 800 < tr[1][0] <= 816, tr)

# every write clipwin.c (and its bank 2 part, clipwin_b2.c, where Loop Len's take is) makes in a Loop Len run (engaged
# with Sync forced, changed, Off with Sync given back) lands in the bank; the param-set it calls writes the pad, as a 0x39
# message would
w = []
r = Rig(cell=0x102)
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u_, acc, addr, size_, v, d_: w.append((addr, size_)) if any(
    a_ <= u_.reg_read(UC_ARM_REG_PC) < b_ for a_, b_ in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
store(r.m, 6, {0x4: 500, P_SYNC: 3})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), ll_pre({300: 1, 500: 3, 700: 0})(rr))
r.params()
r.goto(287000)
r.note_on()
r.run(900)
hit = {name: any(lo <= a_ - BANK < hi for a_, s_ in w) for name, lo, hi in (("origin", B_ORIGIN, B_LL), ("ll", B_LL, B_FORCED),
                                                                           ("forced", B_FORCED, B_SF), ("sf", B_SF, B_SIZE))}
check(f"in a Loop Len run, every write clipwin.c and clipwin_b2.c make into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (origin, "
      f"Loop Len, forced and the latches' Slip part written: {hit}); Sync forced to 1/16, eased to 1/8 at 1/4 (the largest "
      f"that divides the in-point), given back on Off ({[x[4] for i, x in enumerate(r.llog) if i and x[4] != r.llog[i - 1][4]]})",
      w and all(hit.values()) and all(BANK <= a_ and a_ + s_ <= BANK + B_SIZE for a_, s_ in w)
      and [x[4] for i, x in enumerate(r.llog) if i and x[4] != r.llog[i - 1][4]] == [240, 480, 960] and r.i64(r.pad + 0x220) == 960,
      (sorted({hex(a_) for a_, s_ in w if not BANK <= a_ < BANK + B_SIZE})[:4], hit))

# a window that is not a whole number of the pad's steps although longer: Loop Len 1/2 on a 5-beat clip with Sync 1/2
# (n = 2, steps of 2 400 ticks), engaged inside step 1: forced to 1/4, the largest Sync that divides the window, its
# in-point and the clip. Stock plays this clip with a gap (its step 1 snaps to the 2 400 grid) and its re-grid to 1/4
# skips steps: the stock image sent Sync 1/4 in the same block does exactly the same, sample for sample
kw = dict(frames=120000, beats=5, at=287000, sync=2, blocks=1700, vals={P_SYNC: 2})
cw = audio(pre=ll_pre({600: 4}, sync=2), **kw)
r = cw["rig"]
on = taken(r, 4)
st_ = audio(frames=120000, beats=5, at=287000, sync=2, blocks=1700, image=STOCK,
            pre=lambda rr: rr.param(P_SYNC, 3) if on and rr.block == on[0] else None)
sg = seg_firsts(cw, 287000 + on[0] * N + 2048 if on else 0)
n_, err, bad_ = follows(cw)
same_starts = [x[:2] for x in starts(r)] == [x[:2] for x in starts(st_["rig"])]
check(f"Loop Len 1/2 on a 5-beat clip with Sync 1/2 (steps of {r.made[0]['tps']} ticks), taken inside step 1: Sync forced "
      f"to 1/4 (+0x220 {on and on[4]}), origin {on and on[2]}; the steps play the window's two beats, 48 000 and 72 000 "
      f"({sg[:5]}), every sample its segment's ({n_}, max {err:.4f}); starts and summed gain as the stock image sent Sync "
      f"1/4 in that block ({same_starts}, {same_gain(st_, cw, 288300)} samples differ)",
      r.made[0]["tps"] == 2400 and on and on[4] == 960 and on[3] == 1 and on[2] == 1920 and len(sg) >= 4
      and all(x[2] == 48000 + 24000 * (((x[1] * 960 - 1920) % 1920) // 960) for x in sg) and {x[2] for x in sg} == {48000, 72000}
      and n_ > 80000 and err <= 0.02 and bad_ == 0 and same_starts and same_gain(st_, cw, 288300) == 0, (on, sg[:8], n_, err, bad_))

# Every Clip Window hook's maths is in bank 2 (clipwin_b2.c): without this build's payload there (its header wiped
# before the first poll, so the first b2_live() says no for the whole run) every hook passes through to stock. L2's run,
# Loop Len 1/16 set and then Off: bit for bit the run where it is never set, the Sync never forced, and no bank-2
# function entered
kw = dict(frames=96000, at=193000, blocks=1900, vals={P_SYNC: 3})
nb = scenario(pre=ll_pre({1000: 1, 1750: 0}), bank2=False, **kw)
rf = scenario(pre=ll_pre({}), **kw)
ok_, d_ = same(rf, nb)
check(f"no bank 2 (its header wiped before the first poll): Loop Len 1/16 set and then Off plays as if it had never been "
      f"set, bit for bit ({d_}), never taken ({sorted({x[1] for x in nb.llog})}), Sync never forced "
      f"({sorted({x[4] for x in nb.llog})}), and no bank-2 function entered ({len(nb.b2_entered)} entries of "
      f"{len(CW_FUNCS)} functions)",
      ok_ and {x[1] for x in nb.llog} == {0} and {x[4] for x in nb.llog} == {960} and not nb.b2_entered and len(CW_FUNCS) >= 14,
      (d_, sorted(set(nb.b2_entered)), CW_FUNCS))
# ...and with all three set from the start (Slip +480, Region Loop over [24 000, 72 000) in the class-H object, Loop Len
# 1/4) and a live Slip change: every read, fetch, prefetch, mixed sample and message as with every clipwin hook taken out
kw = dict(frames=96000, cell=0x102, blocks=900, slip=480, points=(24000, 72000, 1), region=LOOP,
          vals={P_SYNC: 3, P_LOOPLEN: 3, P_FIT: 1, P_FADE: 50},
          pre=lambda rr: store(rr.m, rr.q, {0x4: 500, P_SLIP: -30, P_REGION: LOOP, P_SYNC: 3, P_LOOPLEN: 3, P_FIT: 1,
                                            P_FADE: 50})
          if rr.block == 300 else None)
nb = scenario(bank2=False, **kw)
by = scenario(bypass=True, **kw)
wb = scenario(**kw)
ok_, d_ = same(nb, by)
differs = not same(wb, by)[0]
check(f"no bank 2, with Slip +480 (then -30), Region Loop [24 000, 72 000), Loop Len 1/4, Fit Auto and Loop Fade 5 % set: every Clip pad plays "
      f"stock, bit for bit the run with every clipwin hook taken out ({d_}), no bank-2 function entered "
      f"({len(nb.b2_entered)}), nothing latched (valid {bank_valid(nb.m, 6):#x}), no Sync forced ({nb.i64(nb.pad + 0x220)}); "
      f"with bank 2 the same run is not stock's ({differs}: latched {bank_valid(wb.m, 6):#x})",
      ok_ and not nb.b2_entered and bank_valid(nb.m, 6) == 0 and nb.i64(nb.pad + 0x220) == 960 and differs
      and bank_valid(wb.m, 6), (d_, sorted(set(nb.b2_entered)), differs))
# ...and Slip 0, Region File, Loop Len Off over a loop in the class-H object: the stock 3.1.9 image's run, bit for bit
a = scenario(frames=96000, cell=0x102, blocks=900, points=REG, region=FILE, bank2=False)
b = scenario(frames=96000, cell=0x102, blocks=900, points=REG, image=STOCK)
ok_, d_ = same(a, b)
check(f"no bank 2: Slip 0, Region File and Loop Len Off over a loop play as the stock 3.1.9 image, bit for bit ({d_})", ok_, d_)

# ====================================================================================================== 11b. Fit
# Fit (README section 3; clipwin_b2.c's fit, at H3 site 3): a Clip pad's clip made a whole number of beats - Auto the
# nearest, or a count from the list - and what the pad plays (its region, or the file) made to last exactly that long at
# the tempo, through stock's own step fields stored again: +0x230 the wrap grid, +0x208 ticks per step, +0x210 steps,
# +0x1fc frames per step, +0x204 output samples per step and +0x1f0 the rate every segment takes. A clip that is no
# whole number of Quants cycles against them (polymetric): its wrap grid is gcd(Quant, clip), and its steps are
# gcd(Sync, clip), on the clock's grid of their length as stock's are.


def f32s(*xs):
    return [float(np.float32(x)) for x in xs]


def joints(d, vlen, rate=None, since=None):
    """at each place where the sounding segment changes (a crossfade, a gap), how far the frame after it is from where
    the frame before it would have got at the playing rate (0: the audio carries on), mod vlen; rate = the median slope
    of the long single-segment runs unless given. Each side is read where its frames run smoothly (a frame decoded from
    the ramp next to the region's seam is a blend of both ends: the kernel's support). (rate, [(first sample, jump,
    zero-gain samples there)])"""
    f, g, sid = d["frame"], d["gain"], d["sid"]
    t = d["base"] + np.arange(len(f))
    ok = ~np.isnan(f)
    if rate is None:
        runs, i = [], 0
        while i < len(f):
            j = i
            while j + 1 < len(f) and ok[j + 1] and ok[i] and sid[j + 1] == sid[i] and abs(f[j + 1] - f[j]) < 50:
                j += 1
            if j - i > 2000:
                runs.append((f[j] - f[i]) / (j - i))
            i = j + 1
        rate = float(np.median(runs)) if runs else 1.0
    smooth = lambda k: 0 < k < len(f) and ok[k] and ok[k - 1] and abs(f[k] - f[k - 1] - rate) < 0.05
    out, i, n = [], 0, len(f) - N
    while i < n - 1:
        if ok[i] and not ok[i + 1]:
            j = i + 1
            while j < n and not ok[j]:
                j += 1
            if j >= n:
                break
            a, b_ = i, j
            while a > i - 16 and not smooth(a):
                a -= 1
            while b_ < j + 16 and not smooth(b_ + 1):
                b_ += 1
            jump = (f[b_] - (f[a] + (b_ - a) * rate) + vlen / 2) % vlen - vlen / 2
            if since is None or t[i + 1] >= since:
                out.append((int(t[i + 1]), float(jump), int((np.abs(g[i + 1:j]) < 1e-7).sum())))
            i = j
        else:
            i += 1
    return rate, out


def pass_starts(r, after=0):
    """the samples where a pass (step 0) starts sounding"""
    return [a for a, st_, _ in starts(r) if st_ == 0 and a >= after]


def fit_audio(fit, **kw):
    """audio() with Fit `fit` in the pad's store (and kw's vals)"""
    return audio(vals={P_FIT: fit, **kw.pop("vals", {})}, **kw)


def seamless(d, vlen, since=288000 + 300, rate=None):
    """(rate, joints, jumps over half a frame, zero-gain samples from `since` on, peak summed gain)"""
    rate_, js = joints(d, vlen, rate=rate, since=since)
    g = d["gain"][since - d["base"]:len(d["gain"]) - N]
    return rate_, len(js), [(a, round(j, 2)) for a, j, _ in js if abs(j) > 0.5], int((np.abs(g) < 1e-7).sum()), float(g.max())


# ---- unit: what site 3 stores (clipwin_len as the thunks call it: site 1 takes Fit from the store, the pad stopped)
fu = Emu(IMAGE, "out/cave.elf")
maps(fu)
sdram(fu)
fu.uc.mem_write(BANK, bytes(B_BYTES))
fu.w32(BANK, CW_MAGIC)
FQ, FL, FENG, FSRC = 6, 0x24060000, 0x24064000, 0x24062000
flen_ = [96000]
fu.stub(SRC_LEN, lambda: fu.ret(flen_[0]))
fu.uc.mem_write(FL, bytes(0xC00))
fu.uc.mem_write(FL + 4, b"\x4c")
fu.w32(FL + 0x18, 0x102)
fu.uc.mem_write(FL + 0x29, b"\x01")
fu.uc.mem_write(FL + 0x1F4, bytes([1, 1, 0, 0, 3]))           # Loop On, synced; Launch Toggle
fu.uc.mem_write(FENG, bytes(0x40))
fu.w32(BANK + B_ENGINE, FENG)                                # the engine as the poll leaves it
STOCKF = (1234.5, 5678.5, 77, 3, 99)                         # stock's +0x1fc, +0x204, +0x208, +0x210, +0x230 (any)


def fit_at(length, fit, bpm=120.0, quant=3840, sync=960, synced=1, base=1.0, region=None, slicer=0, on=1):
    """pad FQ, stopped, with Fit `fit` (and Region Loop over `region` = (ls, le), else File) in its store: its
    recompute's two lengths at sites 1 and 3, stock's fields stored before site 3 (STOCKF). (site 3's answer, +0x230,
    +0x208, +0x210, +0x1fc, +0x204, +0x1f0, fon, Auto's beats, Auto's length)"""
    fu.uc.mem_write(FENG + 0x18, struct.pack("<f", bpm))
    store(fu, FQ, {0x4: 500, P_FIT: fit, **({P_REGION: FILE} if region is None else
                                            {P_REGION: LOOP, 0x91: region[0], 0x92: region[1]})})
    fu.uc.mem_write(FL + 0x29, bytes([on]))
    fu.uc.mem_write(FL + 0x254, bytes([slicer]))
    fu.uc.mem_write(FL + 0x1F0, struct.pack("<f", base))
    fu.uc.mem_write(FL + 0x1F5, bytes([synced]))
    fu.uc.mem_write(FL + 0x218, struct.pack("<qq", quant, sync))
    flen_[0] = length
    fu.call("clipwin_len", FSRC, FL, 1)
    fu.uc.mem_write(FL + 0x1FC, struct.pack("<f", STOCKF[0]))
    fu.uc.mem_write(FL + 0x204, struct.pack("<fqI", STOCKF[1], STOCKF[2], STOCKF[3]))
    fu.uc.mem_write(FL + 0x230, struct.pack("<q", STOCKF[4]))
    fu.call("clipwin_len", FSRC, FL, 3, 0)
    ret = fu.uc.reg_read(UC_ARM_REG_R0)
    rd = lambda o, f_: struct.unpack(f_, bytes(fu.uc.mem_read(FL + o, struct.calcsize(f_))))[0]
    return (ret, rd(0x230, "<q"), rd(0x208, "<q"), rd(0x210, "<I"), rd(0x1FC, "<f"), rd(0x204, "<f"), rd(0x1F0, "<f"),
            fu.r8(BANK + B_FON + FQ), fu.r16(BANK + B_ABEATS + 2 * FQ), fu.r32(BANK + B_ALEN + 4 * FQ))


def fit_want(length, beats, bpm=120.0, quant=3840, sync=960, synced=1):
    """what Fit stores for a clip of `beats`, from the rule (clipwin_b2.c fit), in the M7's single precision"""
    clip = beats * 960
    grid = math.gcd(quant, clip) if quant > 0 else 0
    step = math.gcd(sync, clip) if synced == 1 and sync > 0 and grid > 0 and clip // sync > 1 else clip
    n = clip // step
    samples = int(48000.0 * (clip / 960.0 / float(np.float32(bpm))) * 60.0 + 0.5)
    fps, out, rate = (float(np.float32(length) / np.float32(n)), float(np.float32(samples) / np.float32(n)),
                      float(np.float32(length) / np.float32(samples)))
    return (length, grid, step, n, fps, out, rate, 1)


def auto_beats(length, bpm=120.0, base=1.0):
    x = np.float32(length) / (np.float32(base) * np.float32(48000.0)) * np.float32(bpm) / np.float32(60.0) + np.float32(0.5)
    return max(1, min(1024, int(x)))


rows = []
for length, base, want_b, what in ((336359, 1.0, 14, "14.015 beats (a take cut by ear)"), (89760, 1.0, 4, "3.74 beats"),
                                   (374400, 1.0, 16, "15.6 beats"), (348000, 1.0, 15, "14.5 beats (a tie: up)"),
                                   (7200, 1.0, 1, "0.3 beat (at least one)"), (96000, 1.0, 4, "one bar"),
                                   (82465, 0.91875, 4, "3.74 beats of a 44.1 kHz file (+0x1f0 0.91875)"),
                                   (24000 * 2000, 1.0, 1024, "2 000 beats (at most 1 024)")):
    got = fit_at(length, AUTO_BEATS, base=base)
    want = fit_want(length, want_b)
    rows.append((what, got[8], want_b, got[:8] == want and got[8] == want_b == auto_beats(length, base=base) and got[9] == length))
check(f"Fit Auto (Beats) counts the nearest whole number of beats at the tempo, at least 1, at most 1 024 (len / (+0x1f0 "
      f"x 48 000) x BPM / 60 + 0.5, truncated), and site 3 stores the step fields for that clip "
      f"({[(w, g_) for w, g_, _, _ in rows]})", all(ok for *_, ok in rows), [r_ for r_ in rows if not r_[3]])
# Auto (Bars) (the loop stays with the metronome's bar): under a bar the nearest of 1/4,
# 1/2 and 1 bar, from a bar up the nearest whole number of bars - of the length itself, not of Auto (Beats)' count (5.9
# beats is 6 to the beat but 1 bar to the bar) - ties up, as Auto (Beats)'
rows = []
for length, want_b, what in ((7200, 1, "0.3 beat"), (35999, 1, "1.49996 beats"), (36000, 2, "1.5 beats (a tie: up)"),
                             (71999, 2, "2.99996 beats"), (72000, 4, "3 beats (a tie: up)"), (89760, 4, "3.74 beats"),
                             (141600, 4, "5.9 beats"), (144000, 8, "6 beats (a tie: up)"),
                             (336359, 16, "14.015 beats (pad 1's take)"), (374400, 16, "15.6 beats"),
                             (24000 * 2000, 1024, "2 000 beats (at most 1 024: 256 bars)")):
    got = fit_at(length, AUTO_BARS)
    rows.append((what, got[8], got[:8] == fit_want(length, want_b) and got[8] == want_b and got[9] == length))
check(f"Fit Auto (Bars) counts 1, 2 or 4 beats under a bar, a whole number of bars from a bar up, and site 3 stores the "
      f"step fields for that clip ({[(w, g_) for w, g_, _ in rows]})", all(ok for *_, ok in rows),
      [r_ for r_ in rows if not r_[2]])
seq = [fit_at(336359, AUTO_BEATS)[8], fit_at(336359, AUTO_BARS)[8], fit_at(336359, AUTO_BEATS)[8],
       fit_at(336359, AUTO_BARS, bpm=60.0)[8], fit_at(336359, AUTO_BARS)[8]]
check(f"the other Auto chosen counts again, of the same length: 14.015 beats is {seq[0]} (Beats), {seq[1]} (Bars), "
      f"{seq[2]} (Beats); Bars counted at 60 BPM is {seq[3]} beats, and still {seq[4]} at 120 (counted once per length)",
      seq == [14, 16, 14, 8, 8], seq)
rows = []
for v in range(3, 11):
    got = fit_at(96000, v)
    rows.append((FIT_NAMES[v], got[1:4], got[:8] == fit_want(96000, FIT_BEATS[v]) and got[9] == 0))
check(f"Fit's list from 1/4 to 8 bars forces 1, 2, 3, 4, 6, 8, 16 and 32 beats on a one-bar file (grid, ticks per step, "
      f"steps at Quant 1 bar, Sync 1/4: {[(w, g_) for w, g_, _ in rows]}); Auto's count is cleared",
      all(ok for *_, ok in rows), rows)
cases = (("14 beats, Quant 1 bar, Sync 1/16", dict(sync=240), (1920, 240, 56)),
         ("14 beats, Quant 1 bar, Sync 1/4", dict(), (1920, 960, 14)),
         ("14 beats, Quant 1 bar, Sync 1 bar (stock: 3 steps of 4 480)", dict(sync=3840), (1920, 1920, 7)),
         ("14 beats, Quant 4 bars, Sync 1 bar", dict(quant=15360, sync=3840), (1920, 1920, 7)),
         ("14 beats, Quant 1/16, Sync 1/4 (steps on the beat, as Sync's)", dict(quant=240), (240, 960, 14)),
         ("2 bars, Quant 1/4, Sync 1 bar (as stock: 2 steps of a bar)", dict(quant=960, sync=3840), (960, 3840, 2)),
         ("14 beats, Quant None (synced 0)", dict(quant=0, synced=0), (0, 13440, 1)),
         ("14 beats, Sync None (synced 0)", dict(sync=0, synced=0), (1920, 13440, 1)),
         ("14 beats, Sync Slice without markers", dict(sync=0xF0000), (1920, 13440, 1)))
rows = [(w, fit_at(336359 if w.startswith("14") else 192000, AUTO_BEATS if w.startswith("14") else 8, **kw)[1:4], want)
        for w, kw, want in cases]
check(f"the polymetric grid and steps: wrap grid gcd(Quant, clip), steps one when Sync is the clip or longer, else "
      f"gcd(Sync, clip): {[(w, g_) for w, g_, _ in rows]}", all(g_ == w_ for _, g_, w_ in rows),
      [r_ for r_ in rows if r_[1] != r_[2]])
for what, kw, beats in (("3 beats, Sync 1 bar (one step)", dict(sync=3840), 3), ("6 beats, Sync 1 bar", dict(sync=3840), 6),
                        ("5 beats, Quant 1 bar, Sync 1/4", dict(), 5)):
    got = fit_at(beats * 24000 + 77, AUTO_BEATS, **kw)
    check(f"  {what}: {got[1:4]}, as the rule gives", got[:8] == fit_want(beats * 24000 + 77, beats, **kw), (got, fit_want(beats * 24000 + 77, beats, **kw)))
# counted once per length: a tempo change keeps Auto's count (the speed moves), a new length or Auto chosen again counts
seq = [fit_at(336359, AUTO_BEATS)[8], fit_at(336359, AUTO_BEATS, bpm=60.0)[8], fit_at(336359, AUTO_BEATS, bpm=60.0)[6]]
seq += [fit_at(336359, 0, bpm=60.0)[7], fit_at(336359, AUTO_BEATS, bpm=60.0)[8], fit_at(300000, AUTO_BEATS, bpm=60.0)[8]]
check(f"Auto is counted once per length: 14 at 120 BPM, still 14 at 60 (rate {seq[2]:.6f}: the clip lasts twice as long); "
      f"Off (fon {seq[3]}), then Auto again counts at 60 BPM ({seq[4]}), and so does another length ({seq[5]})",
      seq[0] == 14 and seq[1] == 14 and abs(seq[2] - 336359 / 672000) < 1e-6 and seq[3] == 0 and seq[4] == 7 and seq[5] == 6, seq)
# ...and forgotten when a recompute finds the file closed (0 frames, or the provider's 0x10000000): a file opened again
# (a preset loaded with it) counts at the tempo then, as after a boot - not at the tempo of whatever played it before
seq = [fit_at(336359, AUTO_BEATS, bpm=90.0)[8], fit_at(336359, AUTO_BEATS, bpm=120.0)[8]]
for closed in (0, 0x10000000):
    fit_at(336359, 0, bpm=90.0)                                  # Off, then Auto again: counted at 90 BPM
    before = fit_at(336359, AUTO_BEATS, bpm=90.0)[8]
    shut = fit_at(closed, AUTO_BEATS, bpm=120.0)
    seq += [before, (shut[7], shut[9]), fit_at(336359, AUTO_BEATS, bpm=120.0)[8]]
check(f"Auto's count made at 90 BPM ({seq[0]} beats) stays at 120 ({seq[1]}); counted at 90 again ({seq[2]}, {seq[5]}), "
      f"a recompute with the file closed (0 frames: fon, the length counted {seq[3]}; the provider's 0 frames: "
      f"{seq[6]}) forgets it, and the file opened again at 120 BPM counts {seq[4]} and {seq[7]}, as a fresh boot does",
      seq == [11, 11, 11, (0, 0), 14, 11, (0, 0), 14], seq)
rows = {what: fit_at(96000, 1, **kw) for what, kw in (("Fit Off", dict()), ("a Slicer pad", dict(slicer=1)),
                                                       ("Clip / Slicer mode off", dict(on=0)), ("a tempo of 0", dict(bpm=0.0)))}
rows["Fit Off"] = fit_at(96000, 0)
fu.w32(BANK + B_ENGINE, 0)
rows["no engine polled yet"] = fit_at(96000, 1)
fu.w32(BANK + B_ENGINE, FENG)
stock_f = (96000, STOCKF[4], STOCKF[2], STOCKF[3]) + tuple(f32s(STOCKF[0], STOCKF[1])) + (1.0, 0)
check(f"not fitted - Fit Off, a Slicer pad, a pad out of Clip / Slicer mode, a tempo of 0, no engine polled yet: site 3 "
      f"leaves stock's step fields and its rate as they are ({ {w: g_[:8] == stock_f for w, g_ in rows.items()} })",
      all(g_[:8] == stock_f for g_ in rows.values()), {w: g_ for w, g_ in rows.items() if g_[:8] != stock_f})
got = fit_at(192000, 1, region=(6144, 95904))
check(f"a region: Fit counts the region (3.74 beats -> 4; site 3 answers its length, {got[0]}), rate {got[6]:.6f}",
      got[:8] == fit_want(89760, 4) and got[8] == 4, got)

# ---- the whole process: a 3.74-beat loop (89 760 frames at 120 BPM), as a region [6 144, 95 904) of a 192 000-frame
# file and as a file of its own, Quant 1 bar, Sync 1/4. Stock (Fit Off) re-places it every step, a step being 22 440
# frames of a 24 000-sample beat: -1 560 frames at each, and the file's last step leaves a gap before the bar.
RS4, VL4 = 6144, 89760
REG4 = dict(frames=192000, region=LOOP, points=(RS4, RS4 + VL4, 1))
for what, kw in (("as a region", REG4), ("as a whole file", dict(frames=VL4))):
    res = {}
    for fit in (0, 1):
        d = fit_audio(fit, beats=0, blocks=2300, cell=0x102, **kw)
        res[fit] = seamless(d, VL4) + (pass_starts(d["rig"]), d["rig"].m.r16(BANK + B_ABEATS + 2 * 6))
    off, on = res[0], res[1]
    check(f"3.74 beats {what}, Beat Count Auto, Sync 1/4: Fit Off jumps at {len(off[2])} of {off[1]} joints "
          f"({off[2][:2]}...), {off[3]} zero-gain samples; Fit Auto ({on[6]} beats) plays at {on[0]:.6f} (89 760 / 96 000) "
          f"with no jump over half a frame at its {on[1]} joints ({on[2][:3]}), no zero-gain sample ({on[3]}), peak "
          f"{on[4]:.3f}, a pass every bar ({on[5][:4]})",
          len(off[2]) >= 8 and abs(on[0] - 0.935) < 1e-4 and on[1] >= 8 and not on[2] and on[3] == 0 and on[4] <= 1 + 1e-6
          and on[5][:4] == [288000, 384000, 480000, 576000] and on[6] == 4, (off[:5], on))
# a WAV's Beat Count over a one-bar region: Beat Count 8 cuts it into 8 steps of an eighth of the bar,
# each played for a beat - every step re-placed back half a beat. Fit Auto and Fit 1 bar make it the bar it is.
res = {}
for fit in (0, 1, 6):
    d = fit_audio(fit, beats=8, blocks=2300, cell=0x102, frames=96000)
    res[fit] = seamless(d, 96000) + (u32(d["rig"].m, d["rig"].pad + 0x210), d["rig"].i64(d["rig"].pad + 0x208))
check(f"a one-bar file at Beat Count 8: Fit Off {res[0][5]} steps of {res[0][6]} ticks, jumps at {len(res[0][2])} "
      f"joints, {res[0][3]} zero-gain samples; Fit Auto and Fit 1 bar: {res[1][5]} and {res[6][5]} steps of "
      f"{res[1][6]} ticks, rate {res[1][0]:.6f}, no jump ({res[1][2]}, {res[6][2]}), no zero-gain sample ({res[1][3]}, "
      f"{res[6][3]})", len(res[0][2]) >= 8 and res[1][5:] == res[6][5:] == (4, 960) and not res[1][2] and not res[6][2]
      and res[1][3] == res[6][3] == 0 and abs(res[1][0] - 1) < 1e-5, res)


# tempo: 120 -> 126 BPM inside a pass (sample 414 000). The poll recomputes the fitted pad within 16 blocks (its clip
# stays 4 beats, its rate becomes 89 760 / 91 429); the steps made before the change play out as stock's do at a tempo
# change (one overlaps the next, gain 2, as Fit Off); from the next pass on the audio carries on round every joint
def to126(r):
    if r.S >= 414000 and not getattr(r, "t126", None):
        r.t126 = r.block
        r.set_bpm(126.0)
    if getattr(r, "t126", None) and not getattr(r, "r126", None) and r.m.r32(r.pad + 0x1F0) != struct.unpack("<I", struct.pack("<f", 0.935))[0]:
        r.r126 = r.block


res = {}
for fit in (0, 6):
    d = fit_audio(fit, beats=0, blocks=3000, cell=0x102, pre=to126, **REG4)
    r = d["rig"]
    ps = pass_starts(r)
    rate = struct.unpack("<f", bytes(r.uc.mem_read(r.pad + 0x1F0, 4)))[0]
    res[fit] = (r.t126, getattr(r, "r126", None), rate, ps, seamless(d, VL4, since=ps[2], rate=rate if fit else 1.0))
off, on = res[0], res[6]
s126 = int(48000.0 * (3840 / 960.0 / 126.0) * 60.0 + 0.5)
check(f"tempo 120 -> 126 BPM in a pass (block {on[0]}), Fit 1 bar on the 3.74-beat region: recomputed at block {on[1]} (the "
      f"poll, within 16), rate {on[2]:.6f} (89 760 / {s126}), passes {on[3][:5]}; from the next pass on no jump over a "
      f"frame ({on[4][2]}: steps of {s126 / 4} samples land on whole samples), no zero-gain sample, peak {on[4][4]:.2f} "
      f"(Fit Off: jumps {off[4][2][:2]}...)", on[1] is not None and 0 <= on[1] - on[0] <= 16
      and on[2] == float(np.float32(np.float32(VL4) / np.float32(s126))) and on[3][2:5] == off[3][2:5]
      and all(abs(j) <= 1 for _, j in on[4][2]) and on[4][3] == 0 and on[4][4] <= 1 + 1e-6 and len(off[4][2]) >= 8, res)

# Slip 480 on the fitted region: the same audio shifted by slip_f = floor(480 x 89 760 / 3 840) = 11 220 frames, every joint
# carrying on; Loop Len 1/4 (taken at the launch): every beat plays the fitted first beat
ds = {s_: fit_audio(1, beats=0, blocks=2300, cell=0x102, slip=s_, **REG4) for s_ in (0, 480)}
lo, w = window(ds[0], ds[480])
f0, f1 = w["frame"]
run_ = lambda f: np.concatenate([[False], np.abs(np.diff(f) - 0.935) < 0.05])   # a frame one rate step after the last
far = (lo + np.arange(len(f0)) > 289000) & run_(f0) & run_(f1) & np.roll(run_(f0), -1) & np.roll(run_(f1), -1)
dif = np.mod(f1[far] - f0[far], VL4)
sm = seamless(ds[480], VL4)
check(f"Fit Auto and Slip 480 on the 3.74-beat region: every sample plays Slip 0's frame + {480 * VL4 // 3840} (mod the region; "
      f"{int(far.sum())} samples, {dif.min():.3f} .. {dif.max():.3f}), no jump at its {sm[1]} joints ({sm[2]}), no zero-gain sample",
      far.sum() > 100000 and np.abs(dif - 480 * VL4 // 3840).max() < 0.02 and not sm[2] and sm[3] == 0, (dif.min(), dif.max(), sm))
d = fit_audio(1, beats=0, blocks=2300, cell=0x102, vals={P_LOOPLEN: 3}, **REG4)
f_, b0 = d["frame"], d["base"]
beat = [f_[t - b0] for t in range(289000, 289000 + 24000 * 9, 24000)]
check(f"Fit Auto and Loop Len 1/4 on the 3.74-beat region: every beat plays the first fitted beat (the frame 1 000 samples "
      f"into each: {[round(x, 2) for x in beat]})", all(abs(x - beat[0]) < 0.02 for x in beat) and abs(beat[0] - RS4 - 935) < 1.5,
      beat)

# a 44.1 kHz stereo loop of 3.74 beats (82 465 frames) at Sync 1/16, and Pitch +12 on the 48 kHz region
d = fit_audio(1, beats=0, blocks=2300, cell=0x102, frames=82465, sync=5, src_rate=44100, stereo=True)
sm, r = seamless(d, 82465), d["rig"]
check(f"44.1 kHz stereo, 3.74 beats, Sync 1/16, Fit Auto: {u32(r.m, r.pad + 0x210)} steps of 5 154.06 frames, rate "
      f"{sm[0]:.6f} (82 465 / 96 000), at its {sm[1]} joints nothing over a frame ({sm[2][:3]}: stock starts each step on a "
      f"whole frame, (int)(j x fps)), no zero-gain sample ({sm[3]})",
      u32(r.m, r.pad + 0x210) == 16 and abs(sm[0] - 82465 / 96000) < 1e-4 and sm[1] >= 40 and all(abs(j) < 1 for _, j in sm[2])
      and sm[3] == 0, sm)
d = fit_audio(1, beats=0, blocks=2300, cell=0x102, setup=lambda r: r.param(0x5C, 12000), **REG4)
sm, r = seamless(d, VL4), d["rig"]
st4 = [(m_["step"], m_["start"]) for m_ in r.made if m_["how"] == "H1"]
check(f"Pitch +12 on the fitted region: read at {sm[0]:.4f} (2 x 0.935), each step still started where stock starts it "
      f"((int)(j x 22 440): {st4[:5]}), as stock re-places a pitched clip at every step; no zero-gain sample ({sm[3]})",
      abs(sm[0] - 2 * 0.935) < 2e-3 and len(st4) >= 12 and all(fr == int(j * 22440.0) for j, fr in st4) and sm[3] == 0, (sm, st4[:8]))

# a one-shot (Launch Trigger, Loop Off): the fitted pass lasts the clip, the bar
for fit, want in ((0, 94438), (1, 95999)):
    d = fit_audio(fit, beats=0, blocks=1400, cell=0x102, launch=0, loop=0, **REG4)
    nz = np.where(np.abs(d["gain"]) > 1e-6)[0]
    res[fit] = (int(nz[-1] - nz[0] + 1), seamless(d, VL4)[2])
check(f"a one-shot of the 3.74-beat region (Launch Trigger, Loop Off): Fit Off sounds {res[0][0]} samples, Fit Auto "
      f"{res[1][0]} (the bar: 96 000) with no jump ({res[1][1]})", res[0][0] == 94438 and res[1][0] == 95999 and not res[1][1], res)

# ---- polymetric: a clip that is no whole number of bars (Quant 1 bar), a File of B beats and a Region of B beats in a
# longer file, Fit Auto (= B). Every pass starts B beats after the one before, the audio carries on at every joint, no
# zero-gain sample, no doubling - at Sync 1/16, 1/4 and 1 bar (a Sync that does not divide the clip: stock cuts it into
# clip / Sync steps of an off-grid length, or one step), and at Quant None (no grid: the pass is the clip exactly).
# Stock, the same file at Beat Count B (Fit Off), for comparison: 14 beats at Sync 1/16 has every other pass's end
# snapped half a bar back, into the past (step 0 at once over the last step, then a 1/16 of silence at the next wrap),
# 7 beats at Sync 1/4 waits for the bar after (a beat of silence a pass), 5 at Sync 1/2 is cut into 2 steps of 2 400 ticks.
SYNCS = {"1 bar": 1, "1/2": 2, "1/4": 3, "1/16": 5}


def poly(beats, quant=3, sync="1/4", kind="File", image=IMAGE, fit=AUTO_BEATS, bc=0):
    vlen = beats * 24000
    kw = dict(frames=vlen) if kind == "File" else dict(frames=vlen + 2 * 6144 + 1000, region=LOOP, points=(6144, 6144 + vlen, 1))
    d = fit_audio(fit, beats=bc, quant=quant, sync=SYNCS[sync], blocks=int((2.05 * vlen + 4000) / N), cell=0x102,
                  image=image, **kw)
    ps = pass_starts(d["rig"])
    rate, nj, big, zeros, peak = seamless(d, vlen)
    return ps, [b_ - a for a, b_ in zip(ps, ps[1:])], nj, big, zeros, peak


# CW_FULL=1 runs the whole matrix (60 cases: Quant None at every Sync too, which changes nothing there - no grid, one
# step - about three minutes more); by default Quant None is run at Sync 1/4 for 3 and 14 beats
FULL = os.environ.get("CW_FULL") == "1"
bad, seen = [], []
for kind, b_, quant, sync in ([(k, b, 3, s_) for k in ("File", "Region") for b in (3, 5, 6, 7, 14) for s_ in ("1/16", "1/4", "1 bar")]
                              + ([(k, b, 8, s_) for k in ("File", "Region") for b in (3, 5, 6, 7, 14) for s_ in ("1/16", "1/4", "1 bar")]
                                 if FULL else [("File", 3, 8, "1/4"), ("File", 14, 8, "1/4"), ("Region", 14, 8, "1/4")])
                              + [("File", 5, 3, "1/2")]):
    ps, apart, nj, big, zeros, peak = poly(b_, quant=quant, sync=sync, kind=kind)
    seen.append((kind, b_, f"{sync}{' Quant None' if quant == 8 else ''}", len(apart)))
    if not (len(apart) >= 2 and set(apart) == {b_ * 24000} and not big and zeros == 0 and peak <= 1 + 1e-6
            and (quant == 8 or ps[0] == 288000)):
        bad.append((kind, b_, sync, quant, ps, big[:3], zeros, peak))
check(f"polymetric, Fit Auto (Beats): {len(seen)} cases - a File and a Region of 3, 5, 6, 7 and 14 beats, Quant 1 bar, Sync 1/16, "
      f"1/4 and 1 bar; {'every one at Quant None too' if FULL else '3 and 14 beats at Quant None'}; 5 at Sync 1/2 -: "
      f"every pass B beats after the one before, no jump over half a frame at any joint, no zero-gain sample, gain at "
      f"most 1", not bad, bad)
st14 = poly(14, sync="1/16", image=STOCK, fit=0, bc=14)
st7 = poly(7, sync="1/4", image=STOCK, fit=0, bc=7)
st5 = poly(5, sync="1/2", image=STOCK, fit=0, bc=5)
info(f"stock, a 14-beat file at Beat Count 14, Quant 1 bar, Sync 1/16: passes {st14[1]} samples apart (336 000 is 14 beats), "
     f"{st14[4]} zero-gain samples, peak gain {st14[5]:.2f}; 7 beats at Sync 1/4: {st7[1]}, {st7[4]} zero-gain; 5 beats at "
     f"Sync 1/2: {st5[1]}, jumps {st5[3][:3]}")
check("  ...where stock, the same files at their Beat Count, does not keep them (passes off the clip, silence or doubling)",
      set(st14[1]) != {336000} and st14[4] > 0 and st14[5] > 1.5 and set(st7[1]) != {168000} and st7[4] > 0
      and (set(st5[1]) != {120000} or st5[3]), (st14, st7, st5))

# ---- launched off the Sync grid (Quant 1/16 under Sync 1/4, Quant 1/4 under Sync 1 bar, 1/16 after the bar): the steps
# lie on the clock's grid of their length, as stock's do, so the pad is pulled onto the beat (the bar) at its first step
# - one jump, the one Fit Off and the stock image make there - and every pass after starts on that grid. (Steps of
# gcd(Sync, gcd(Quant, clip)) left such a pad a 1/16 late for good, a whole-bar clip too.)
def off_grid(beats, quant, sync, fit, kind="File", bc=0, image=IMAGE):
    vlen = VL4 if kind == "Region" else beats * 24000
    kw = dict(frames=vlen) if kind == "File" else REG4
    d = fit_audio(fit, beats=bc, quant=quant, sync=SYNCS[sync], at=290000, blocks=int((3 * beats * 24000 + 15000) / N),
                  cell=0x102, image=image, **kw)
    rate, nj, big, zeros, peak = seamless(d, vlen)
    return pass_starts(d["rig"])[:4], [(a, round(j)) for a, j in big], zeros


rows, bad = {}, []
for what, a, want_ps, want_big in (
        ("a 1-bar file, Quant 1/16, Sync 1/4, Fit 1 bar", (4, 7, "1/4", 6), [294000, 384000, 480000, 576000], [(312001, 6000)]),
        ("  ...Fit Off", (4, 7, "1/4", 0), [294000, 384000, 480000, 576000], [(312001, 6000)]),
        ("  ...the stock image", (4, 7, "1/4", 0, "File", 0, STOCK), [294000, 384000, 480000, 576000], [(312001, 6000)]),
        ("a 14-beat file, Quant 1/16, Sync 1/4, Fit Auto (Beats)", (14, 7, "1/4", AUTO_BEATS), [294000, 624000, 960000, 1296000],
         [(312001, 6000)]),
        ("the 3.74-beat region, Quant 1/16, Sync 1/4, Fit Auto", (4, 7, "1/4", 1, "Region"), [294000, 384000, 480000, 576000],
         [(312001, 5610)]),
        ("a 2-bar file, Quant 1/4, Sync 1 bar, Fit 2 bars", (8, 5, "1 bar", 8), [312000, 480000, 672000, 864000],
         [(384001, 24000)]),
        ("  ...Fit Off, Beat Count 8", (8, 5, "1 bar", 0, "File", 8), [312000, 480000, 672000, 864000], [(384001, 24000)])):
    got = off_grid(*a)
    rows[what] = got
    if got[0] != want_ps or len(got[1]) != 1 or got[1][0][0] != want_big[0][0] or abs(got[1][0][1] - want_big[0][1]) > 1 \
            or (a[3] and got[2]):
        bad.append((what, got))
check(f"launched 1/16 after the bar, off the Sync grid: Fit pulls the pad onto the beat at its first step, one jump, as "
      f"Fit Off and stock do, and every pass after starts on the grid (passes, jumps over half a frame, zero-gain "
      f"samples: {rows})", not bad, bad)

# ---- live: Fit is taken with the region, at the pad's wrap: a change inside a pass is heard from the next one. One
# that moves the wrap grid (Fit 1 bar -> 2 bars at Quant 4 bars: passes a bar apart, the new grid 2 bars) waits, with
# the region, for a wrap on its grid (H3', cw_hold), where a launch would start it: no doubled pass.
def fit_to(at, fit, quant_rows=None):
    def pre(r):
        if r.S >= at and not getattr(r, "fit_done", False):
            r.fit_done = True
            store(r.m, r.q, {0x4: 500, P_SLIP: 0, P_REGION: LOOP, P_FIT: fit, P_SYNC: 3})
    return pre


d = fit_audio(0, beats=0, blocks=2300, cell=0x102, vals={P_SYNC: 3}, pre=fit_to(418000, 1), **REG4)
r = d["rig"]
ps = pass_starts(r)
rate = struct.unpack("<f", bytes(r.uc.mem_read(r.pad + 0x1F0, 4)))[0]
sm_before, sm_after = seamless(d, VL4, since=ps[1] - 1000, rate=1.0), seamless(d, VL4, since=ps[2] + 300, rate=rate)
check(f"live, Fit Off -> Auto inside the second pass (sample 418 000): that pass plays on unfitted (jumps {sm_before[2][:3]}...), "
      f"the next ({ps[2]}) fitted: rate {rate:.6f}, no jump at its {sm_after[1]} joints ({sm_after[2]}), no zero-gain "
      f"sample, passes {ps[:4]}",
      ps[:4] == [288000, 384000, 480000, 576000] and len(sm_before[2]) >= 3 and abs(rate - 0.935) < 1e-6
      and sm_after[1] >= 4 and not sm_after[2] and sm_after[3] == 0, (ps, sm_before[:3], sm_after))
res = {}
for quant, what in ((1, "Quant 4 bars"), (3, "Quant 1 bar")):
    d = fit_audio(6, beats=0, quant=quant, blocks=6200, cell=0x102, vals={P_SYNC: 3}, pre=fit_to(418000, 8), **REG4)
    r = d["rig"]
    g = d["gain"][:len(d["gain"]) - N]
    res[what] = (pass_starts(r), float(g.max()), int((np.abs(g[384300 - d["base"]:]) < 1e-7).sum()),
                 seamless(d, VL4, since=pass_starts(r)[3] + 300)[2] if len(pass_starts(r)) > 3 else None)
q4, q1 = res["Quant 4 bars"], res["Quant 1 bar"]
check(f"live, Fit 1 bar -> 2 bars at sample 418 000: at Quant 4 bars (launched on bar 4, a pass a bar) the next wrap (bar 5) "
      f"is off the 2-bar grid and the bar plays once more; the one after (bar 6) takes it: passes {q4[0][:5]}, peak gain "
      f"{q4[1]:.2f}, {q4[2]} zero-gain samples; at Quant 1 bar (launched on bar 3; grid gcd(1 bar, 2 bars) = 1 bar) the "
      f"next wrap takes it: {q1[0][:4]}; no jump in the 2-bar passes ({q4[3]}, {q1[3]})",
      q4[0][:5] == [384000, 480000, 576000, 768000, 960000] and q4[1] <= 1 + 1e-6 and q4[2] == 0 and not q4[3]
      and q1[0][:4] == [288000, 384000, 480000, 672000] and q1[1] <= 1 + 1e-6 and not q1[3], res)

# the wrap-grid hold and a polymetric clip: a 14-beat region at Fit Auto (Beats) (grid gcd(1 bar, 14 beats) = half a
# bar: its passes start on the bar and on the half bar in turn) made 16 beats (grid 1 bar) while it plays waits for a
# pass that starts on the bar, one pass at most; made 13 beats (grid a beat) it is taken at the next wrap, wherever it
# falls. (Auto (Bars) makes the same region 4 bars, every pass on the bar: nothing to wait for.)
def loop_end(at, le):
    def pre(r):
        if r.S >= at and not getattr(r, "le_done", False):
            r.le_done = True
            r.param(0x92, le)
    return pre


res = {}
for beats_, at in ((16, 300000), (16, 700000), (13, 300000)):
    d = fit_audio(AUTO_BEATS, beats=0, blocks=int((1360000 - 287000) / N), cell=0x102, vals={P_SYNC: 3}, frames=400000,
                  region=LOOP, points=(6144, 6144 + 336000, 1), pre=loop_end(at, 6144 + beats_ * 24000))
    g = d["gain"][:len(d["gain"]) - N]
    res[(beats_, at)] = (pass_starts(d["rig"]), float(g.max()), int((np.abs(g[288300 - d["base"]:]) < 1e-7).sum()),
                         seamless(d, beats_ * 24000, since=pass_starts(d["rig"])[-2] + 300)[2])
a, b_, c_ = res[(16, 300000)], res[(16, 700000)], res[(13, 300000)]
check(f"a fitted 14-beat region made 16 beats inside its first pass: the next wrap is on the half bar, so the second pass "
      f"plays 14 more and the third (on the bar) takes it - {a[0][:4]}; made 16 inside the second pass, the next wrap is on "
      f"the bar and takes it - {b_[0][:4]}; made 13 beats: the next wrap, on the half bar - {c_[0][:4]}; peak gain "
      f"{max(a[1], b_[1], c_[1]):.2f}, zero-gain samples {a[2]}, {b_[2]}, {c_[2]}, no jump in the last pass "
      f"({a[3]}, {b_[3]}, {c_[3]})",
      a[0][:4] == [288000, 624000, 960000, 1344000] and b_[0][:3] == [288000, 624000, 960000] and b_[0][3] == 1344000
      and c_[0][:4] == [288000, 624000, 936000, 1248000] and max(a[1], b_[1], c_[1]) <= 1 + 1e-6
      and a[2] == b_[2] == c_[2] == 0 and not a[3] and not b_[3] and not c_[3], res)

# Fit Off is stock's step fields, bit for bit: an explicit Off in the store against no Fit row at all, over a region with
# Slip, and over a file with Slip (the whole file then is no region)
for what, kw in (("a region, Slip 480", dict(points=REG, slip=480)), ("a file, Slip -30", dict(slip=-30, frames=88615))):
    a = scenario(cell=0x102, blocks=900, vals={P_FIT: 0}, **kw)
    b = scenario(cell=0x102, blocks=900, **kw)
    ok_, d_ = same(a, b)
    check(f"Fit Off in the store, {what}: every read, fetch, prefetch, output sample and message as with no Fit row ({d_}), "
          f"nothing fitted (fon {a.m.r8(BANK + B_FON + 6)})", ok_ and a.m.r8(BANK + B_FON + 6) == 0, d_)

# ---- unit: the wrap's hold with Fit (clipwin_wrap, the recompute stubbed as one that adopts at this pad's wrap: Fit
# from `old` to `new`, the region kept, and leaves +0x230 = grid). A Fit taken with the region waits with it when it moves
# the wrap grid off this pass and a wrap on the new grid can come; a polymetric fitted clip is on its own grid
HT = 0x24063800


def hold_fit(t, grid, old, new, was_grid=3840, was_tps=960, was_n=4):
    rec = []
    fu.uc.mem_write(BANK + B_REGION + 8 * FQ, struct.pack("<2i", 24000, 48000))
    fu.uc.mem_write(BANK + B_FIT + FQ, bytes([old]))
    fu.uc.mem_write(FL + 0x230, struct.pack("<q", was_grid))
    fu.uc.mem_write(FL + 0x208, struct.pack("<qI", was_tps, was_n))
    fu.uc.mem_write(FL + 0x260, b"\x01")

    def fake():
        w_ = fu.r8(BANK + B_WRAP)
        rec.append(w_)
        if w_ == FQ + 1:                                     # adopt at this pad's wrap: pfit = fit, fit = the store's
            fu.uc.mem_write(BANK + B_PFIT + FQ, bytes([fu.r8(BANK + B_FIT + FQ)]))
            fu.uc.mem_write(BANK + B_FIT + FQ, bytes([new]))
        fu.uc.mem_write(FL + 0x230, struct.pack("<q", grid))
    fu.stub(RECOMPUTE, fake)
    fu.uc.mem_write(HT, struct.pack("<q", t))
    fu.call("clipwin_wrap", FL, 0x12345678, HT)
    del fu.stubs[RECOMPUTE]
    fu.uc.mem_write(FL + 0x260, b"\x00")
    return fu.r8(BANK + B_FIT + FQ), fu.r8(BANK + B_PFIT + FQ), tuple(rec)


rows = {what: hold_fit(*a) for what, a in (
    ("1 bar -> 2 bars, the pass on bar 5 (off the 2-bar grid)", (19200, 7680, 6, 8)),
    ("1 bar -> 2 bars, the pass on bar 6 (on it)", (23040, 7680, 6, 8)),
    ("Fit unchanged, region unchanged, the grid moved by stock", (19200, 7680, 6, 6)),
    ("14 beats Auto unchanged, the pass on a half bar (its grid: half a bar)", (24960, 1920, 1, 1)),
    ("Auto -> 2 bars from 14 beats (grid half a bar), a pass on a half bar that the 2-bar grid can meet", (24960, 7680, 1, 8, 1920, 960, 14)))}
check(f"H3' and Fit: a Fit change that moves the wrap grid off this pass waits (Fit put back, the recompute run again) when "
      f"a wrap on the new grid can come, else it is taken; a pass on a polymetric clip's own grid takes it: {rows}",
      rows == {"1 bar -> 2 bars, the pass on bar 5 (off the 2-bar grid)": (6, 6, (FQ + 1, 0)),
               "1 bar -> 2 bars, the pass on bar 6 (on it)": (8, 8, (FQ + 1,)),
               "Fit unchanged, region unchanged, the grid moved by stock": (6, 6, (FQ + 1,)),
               "14 beats Auto unchanged, the pass on a half bar (its grid: half a bar)": (1, 1, (FQ + 1,)),
               "Auto -> 2 bars from 14 beats (grid half a bar), a pass on a half bar that the 2-bar grid can meet":
                   (1, 1, (FQ + 1, 0))}, rows)

# every write into the SDRAM block in a fitted run (a tempo change in it) lands in the bank, Fit's fields among them
w = []
r = Rig(cell=0x102, h=True, frames=192000)
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u_, acc, addr, size_, v, d_: w.append((addr, size_)) if any(
    a_ <= u_.reg_read(UC_ARM_REG_PC) < b_ for a_, b_ in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
store(r.m, 6, {0x4: 500, P_SLIP: 0, P_REGION: LOOP, P_FIT: 1, P_FADE: 50})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), rr.set_bpm(126.0) if rr.block == 400 else None)
r.params(beats=0)
r.goto(287000 - N)
for pid, v in zip((0x91, 0x92, 0x8E), (RS4, RS4 + VL4, 1)):
    r.param(pid, v)
r.step_block()
r.goto(287000)
r.note_on()
r.run(700)
hit = {name: any(lo <= a_ - BANK < hi for a_, s_ in w) for name, lo, hi in (
    ("fit", B_FIT, B_PFIT), ("pfit", B_PFIT, B_FON), ("fon", B_FON, B_ABEATS), ("abeats", B_ABEATS, B_ALEN),
    ("alen", B_ALEN, B_BPM), ("bpm", B_BPM, B_ENGINE), ("engine", B_ENGINE, B_FADE), ("fade", B_FADE, B_FIN),
    ("abars", B_ABARS, B_SIZE))}
check(f"in a fitted run with Loop Fade, every write clipwin.c and clipwin_b2.c make into the SDRAM block lands in "
      f"cw_bank's {B_SIZE:#x} bytes (Fit's and Loop Fade's fields written: {hit})", w and all(hit.values()) and all(BANK <= a_ and a_ + s_ <= BANK + B_SIZE for a_, s_ in w),
      (sorted({hex(a_) for a_, s_ in w if not BANK <= a_ < BANK + B_SIZE})[:4], hit))

# ====================================================================================================== 11c. Loop Fade
# Loop Fade on a Region (without it the region's seam is a hard splice, a single-sample step at every wrap):
# stock's own Sample-mode row (0xfa, 0 .. 1000) on the Clip Pos page, taken with the region; the region's last F =
# (int)(vlen x row / 1000) frames (at most Loop Start) crossfade, equal-gain and linear as stock's Sample mode does, into
# the F frames before Loop Start: y = x + g (x(j - vlen) - x(j)), g = (j - (le - F)) / F. The ramp source makes that
# exact: a faded frame j decodes as j - g x vlen.
FREG = dict(frames=192000, region=LOOP, points=(RS4, RS4 + VL4, 1), beats=0, cell=0x102)


def fade_model(d0, d1, fade, rs=RS4, vlen=VL4):
    """the faded run d1 against the Loop Fade 0 run d0 of the same scenario, sample by sample where one segment sounds
    in both: (samples compared, of them inside the fade, max |d1 frame - (d0 frame - g x vlen)|), leaving out the
    kernel's support (3 frames) round the fade's two kinks and the seam, and d0's frames that are not one rate step
    from both neighbours"""
    lo, w = window(d0, d1)
    f0, f1 = w["frame"]
    le = rs + vlen
    F = min(int(np.float32(vlen) * (np.float32(fade) / np.float32(1000.0))), rs)
    z = le - F
    ok = ~np.isnan(f0) & ~np.isnan(f1) & (lo + np.arange(len(f0)) > 288300)
    ok &= ~((np.abs(f0 - z) < 3) | (np.abs(f0 - le) < 3) | (np.abs(f0 - rs) < 3))
    d_ = np.diff(f0)
    rate = float(np.median(d_[np.abs(d_) < 50]))
    smooth = np.abs(d_ - rate) < 0.05                       # (a frame decoded across the seam is a blend of both ends)
    ok &= np.concatenate([[False], smooth]) & np.concatenate([smooth, [False]])
    g = np.clip((f0 - z) / F, 0, 1) * (f0 < le)
    e = np.abs(f1 - (f0 - g * vlen))[ok]
    return int(ok.sum()), int((ok & (f0 >= z) & (f0 < le)).sum()), float(e.max()) if len(e) else 9e9


rows = []
for what, kw in (("48 kHz mono, rate 1", dict()), ("Fit Auto (rate 0.935)", dict(vals={P_FIT: 1})),
                 ("44.1 kHz stereo (rate 0.91875)", dict(stereo=True, src_rate=44100)), ("Slip +480", dict(slip=480))):
    vals = kw.pop("vals", {})
    d0 = audio(blocks=2300, vals={P_FADE: 0, **vals}, **FREG, **kw)
    d5 = audio(blocks=2300, vals={P_FADE: 50, **vals}, **FREG, **kw)
    n_, nz, err = fade_model(d0, d5, 50)
    rows.append((what, n_, nz, round(err, 4), d5["rig"].hints[:2]))
F5 = int(VL4 * 0.05)
check(f"Loop Fade 5 % on the 3.74-beat region [6 144, 95 904) ({F5} frames): every sample of the faded run plays the Loop "
      f"Fade 0 run's frame j, crossfaded into j - 89 760 with gain (j - (95 904 - {F5})) / {F5} (stock's equal-gain linear "
      f"formula): {[(w_, n_, nz, e_) for w_, n_, nz, e_, _ in rows]} (samples, inside the fade, max error in frames); the "
      f"seam hinted where the copy starts ({6144 - F5}) and at rs ({RS4})",
      all(n_ > 100000 and nz > 2 * F5 and e_ <= (0.01 if "rate 1" in w_ or "Slip" in w_ else 0.1) for w_, n_, nz, e_, _ in rows)
      and all(h and {p for _, p, _ in h} == {RS4 - F5, RS4} for *_, h in rows), rows)
d0 = audio(blocks=2300, vals={P_FADE: 0}, **{**FREG, "points": (1000, 1000 + VL4, 1)})
d5 = audio(blocks=2300, vals={P_FADE: 50}, **{**FREG, "points": (1000, 1000 + VL4, 1)})
n_, nz, err = fade_model(d0, d5, 50, rs=1000)
check(f"  ...a region starting at 1 000 (5 % would be {F5} frames): the fade is Loop Start long, 1 000 frames, as stock's "
      f"({n_} samples, {nz} in the fade, max error {err:.4f})", n_ > 100000 and nz > 2700 and err <= 0.01, (n_, nz, err))
# the bench's measure: a zero-mean source whose seam does not match (a 441 Hz sine), the largest sample-to-sample step of
# the output after the launch: the splice at Loop Fade 0, the sine's own (and the steps' crossfades) with it
keep = Rig._data


def sine(self, pos, n, right=False):
    q_ = np.arange(pos, pos + n, dtype=np.int64)
    v = 0.5 * np.sin(2 * np.pi * 441.0 * q_ / self.src_rate) * (-1.0 if right else 1.0)
    return np.where((q_ >= 0) & (q_ < self.len), v, 0.0).astype(np.float32).tobytes()


Rig._data = sine
try:
    steps = {}
    for fade in (0, 10, 50):
        for what, kw in (("rate 1", dict()), ("Fit Auto", dict(vals={P_FIT: 1}))):
            vals = kw.pop("vals", {})
            r = scenario(blocks=2300, vals={P_FADE: fade, **vals}, **FREG, **kw)
            out = np.concatenate(r.out).astype(np.float64)[(288300 - 287000):]
            steps[(fade, what)] = float(np.abs(np.diff(out)).max())
finally:
    Rig._data = keep
check(f"a 441 Hz sine region, its seam mismatched: the largest sample step after the launch {steps} - a splice at Loop Fade 0 "
      f"(0.3), none at 1 % and 5 % (the sine's own 0.029 a sample, and its steps' crossfades)",
      steps[(0, "rate 1")] > 0.25 and steps[(0, "Fit Auto")] > 0.25
      and all(steps[(f_, w_)] < 0.07 for f_ in (10, 50) for w_ in ("rate 1", "Fit Auto")), steps)
# where it does nothing, bit for bit as Loop Fade 0: a one-shot (Launch Trigger: it never wraps), Loop Off, a region
# under 2 048 frames, a rate above 3.9 (Pitch +24: the window and its copy no longer fit the scratch), a machine mode
# (Fidelity SP1200: filter.c's reader), and Loop Fade 0 in the store against no Loop Fade row
for what, kw in (("Launch Trigger", dict(launch=0)), ("Loop Off", dict(loop=0)),
                 ("a region of 2 000 frames", dict(points=(RS4, RS4 + 2000, 1), beats=0)),
                 ("Pitch +24 (rate 4)", dict(setup=lambda r: r.param(0x5C, 24000))),
                 ("Fidelity SP1200", dict(vals={0xF1: 2})), ("Loop Fade 0 against no row", None)):
    if kw is None:
        a, b = scenario(blocks=1500, vals={P_FADE: 0}, **FREG), scenario(blocks=1500, **FREG)
    else:
        vals = kw.pop("vals", {})
        base_ = {**FREG, **kw}
        a = scenario(blocks=1500, vals={P_FADE: 50, **vals}, **base_)
        b = scenario(blocks=1500, vals={P_FADE: 0, **vals}, **base_)
    ok_, d_ = same(a, b)
    check(f"Loop Fade 5 %, {what}: every read, fetch, prefetch, output sample and message as at Loop Fade 0 ({d_})", ok_, d_)


# ...and while Loop Len is taken: a window goes back to its own start, never on into Loop Start, so it is not faded (on
# the region's last beat each repetition would end on the audio before Loop Start). Loop Len 1/4 taken in the last beat
# of a one-bar region [40 000, 136 000), Loop Fade 1 % (960 frames, inside that beat): as at Loop Fade 0. Loop Len is
# written SETTLE_BLOCKS before block 574, so that it is taken at block 582 whatever the settle, before either run's seam
# hint (Loop Fade's, at rs - F, comes about 8 blocks earlier than Loop Fade 0's at rs)
def ll_fade(fade, block, ll=3):
    """pre_block: the pad's store with Loop Fade `fade` throughout and Loop Len `ll` written at `block`; the block whose
    poll took it in rr.took"""
    def pre(rr):
        if rr.block == block:
            store(rr.m, rr.q, {0x4: 500, P_SLIP: 0, P_SYNC: 3, P_REGION: LOOP, P_FADE: fade, P_LOOPLEN: ll})
        if getattr(rr, "took", None) is None and rr.m.r8(BANK + B_LL + rr.q) == ll:
            rr.took = rr.block
    return pre


RL = dict(frames=192000, region=LOOP, points=(40000, 136000, 1), beats=0, cell=0x102)
a, b = (scenario(blocks=1500, vals={P_FADE: f_, P_SYNC: 3}, pre=ll_fade(f_, 574 - SETTLE_BLOCKS), **RL) for f_ in (10, 0))
ok_, d_ = same(a, b)
took = (getattr(a, "took", None), getattr(b, "took", None))
check(f"Loop Fade 1 % and Loop Len 1/4 taken in the region's last beat (block {took[0]}: sample "
      f"{took[0] and 287000 + took[0] * N}, the beat from 360 000): every read, fetch, prefetch, output sample and "
      f"message as at Loop Fade 0 ({d_})", ok_ and took[0] == took[1] and took[0] and 360000 <= 287000 + took[0] * N < 384000,
      (took, d_))

# the seam hint with a long fade on a slipped pad (Slip 480: the seam inside a segment, where H1's prefetch for the next
# pass does not reach rs): Loop Fade 25 % of a 192 000-frame region at 40 000, clamped to Loop Start (40 000 frames).
# The hint where the copy starts (0) reaches 3 blocks of 8 192 frames, not rs: rs is hinted as well, before the crossing
RSH, VLH = 40000, 192000
cov = lambda p: p // 8192 * 8192 <= RSH < (p // 8192 + 3) * 8192
rows = {}
for fade in (0, 250):
    r = scenario(frames=RSH + VLH + 4000, cell=0x102, blocks=2000, beats=0, points=(RSH, RSH + VLH, 1), region=LOOP,
                 slip=480, vals={P_FADE: fade, P_SYNC: 3})
    seams = sorted({b_ for b_, pos, n in r.fetches if pos == RSH and b_ > 50})
    prev, got = 50, []
    for s_ in seams:
        got.append((s_, [(b_, p) for b_, p in r.prefetches if prev < b_ <= s_ and cov(p)][:3]))
        prev = s_
    rows[fade] = (got, r.hints[:4])
check(f"Loop Fade 25 %, Slip 480: before each seam crossing a prefetch covers rs = {RSH} (crossing block, those "
      f"prefetches; the hints: {rows}), as at Loop Fade 0", all(g_ and all(c for _, c in g_) for g_, _ in rows.values())
      and {p for _, p, _ in rows[250][1]} == {0, RSH}, rows)

# ====================================================================================================== 11d. the playhead
# H5 (clipwin_playhead at the render's post of msg 0x4a, 0x080668fc): stock posts each segment's own position, which
# the reader never shows: counted from the region's start, unslipped, never in Loop Len's window. Now the frame heard:
# cw_map's mapping of the slot's latch (the reader's own), per mille as stock reckons it ((float)pos x 1000 / file).
# Checked against the audio: in every block that one segment plays from start to end (no crossfade, which posts the
# fading segment's tail as stock does), the position posted is the frame after the block's last sample (to the frame
# at rate 1, the decoded frame's float error aside; at Fit's 0.935 the posted whole frame is 1 to 2.1 behind the
# decoded one plus the rate: the kernel reads about a frame behind the position, and the fraction is cut). Without bank 2 the
# messages are the stock image's.
def heads(d, frames, rs=0, vlen=None, rate=1.0, at=287000):
    """per block with one 0x4a post and one segment sounding throughout: (block, posted, per mille, frame heard + rate)"""
    r_, vlen = d["rig"], vlen or frames
    pre = 1 if r_.h else 0                                   # a rig with the class-H object runs a block before `at`
    per = {}
    for b_, t_, w_ in r_.posted:
        if t_ == 0x4A:
            per.setdefault(b_, []).append((w_[3], w_[4] & 0xFFFF))
    rows = []
    for b_, ps in sorted(per.items()):
        i0 = at + (b_ - pre) * N - d["base"]
        if len(ps) != 1 or i0 < 0 or i0 + N > len(d["cnt"]) or not np.all(d["cnt"][i0:i0 + N] == 1):
            continue
        f = d["frame"][i0 + N - 1]
        if np.isnan(f):
            continue
        rows.append((b_, ps[0][0], ps[0][1], float(f) + rate))
    dv = lambda x: ((x[1] - x[3]) + vlen / 2) % vlen - vlen / 2
    ok = [x for x in rows if (abs(dv(x)) <= 0.01 if rate == 1.0 else -2.5 <= dv(x) <= 0.5)
          and rs <= x[1] < rs + vlen and x[2] == int(np.float32(np.float32(x[1]) * np.float32(1000.0) / np.float32(frames)))]
    return rows, ok, len(per)


PH = {"a region from 6 072 (B's [6 072, 102 072) of 192 000 frames)": dict(frames=192000, beats=0, region=LOOP, points=(6072, 102072, 1)),
      "...with Slip +0.060 (1 500 frames ahead)": dict(frames=192000, beats=0, region=LOOP, points=(6072, 102072, 1), slip=60),
      "...with Slip -0.120 (3 000 behind: the line wraps at Loop End)": dict(frames=192000, beats=0, region=LOOP, points=(6072, 102072, 1), slip=-120),
      "a whole file with Slip +0.480": dict(frames=96000, beats=4, slip=480),
      "Loop Len 1/4 on a whole file (each step replays the window's beat)": dict(frames=96000, beats=4, vals={P_SYNC: 3, P_LOOPLEN: 3}),
      "Fit Auto on a 3.74-beat file (rate 0.935)": dict(frames=89760, beats=0, vals={P_FIT: 1})}
for what, kw in PH.items():
    d = audio(blocks=900, **kw)
    rate = struct.unpack("<f", bytes(d["rig"].m.uc.mem_read(d["rig"].pad + 0x1F0, 4)))[0]
    rs, vlen = (6072, 96000) if kw.get("region") == LOOP else (0, kw["frames"])
    rows, ok, n_ = heads(d, kw["frames"], rs, vlen, rate)
    ex = rows[len(rows) // 2] if rows else None
    check(f"H5, {what}: in each of the {len(rows)} blocks (of {n_} with a post) that one segment plays throughout, the "
          f"line is the frame heard next, its per mille stock's reckoning (block {ex and ex[0]}: {ex and ex[1:3]} after "
          f"frame {ex and ex[3] - rate:.1f})", len(rows) > 0.7 * n_ and len(ok) == len(rows),
          ([x for x in rows if x not in ok][:4], len(rows), n_))


# stock's own message on that region (H5 alone taken out): 6 072 frames behind the audio, which is the same
def h5_out(rr):
    rr.m.stubs[S["clipwin_playhead_b"]] = lambda: rr.uc.reg_write(UC_ARM_REG_PC, 0x0804F504 | 1)


kw = dict(PH["a region from 6 072 (B's [6 072, 102 072) of 192 000 frames)"], blocks=900)
d, nd = audio(**kw), audio(setup=h5_out, **kw)
nrows = heads(nd, 192000, 6072, 96000)[0]
lag = sorted({x[3] - x[1] for x in nrows})
check(f"  ...H5 taken out, the same region's line is stock's: {lag} frames behind the audio (the region's start), which "
      "is the same with it in", lag == [6072.0] and np.array_equal(d["frame"], nd["frame"], equal_nan=True)
      and np.array_equal(d["gain"], nd["gain"]), (lag[:4], len(nrows)))
# without bank 2: the messages are the stock image's, bit for bit (a region and Slip set, which then do nothing)
kw = dict(frames=192000, beats=0, region=LOOP, points=(6072, 102072, 1), slip=60, blocks=600)
nb = scenario(bank2=False, **kw)
sti = scenario(image=STOCK, **kw)
p_nb, p_st = [x for x in nb.posted if x[1] == 0x4A], [x for x in sti.posted if x[1] == 0x4A]
check(f"H5 without bank 2: the {len(p_nb)} playhead messages of a region with Slip are the stock image's, bit for bit "
      f"(and every other message), no bank-2 function entered", p_nb == p_st and nb.posted == sti.posted and p_nb
      and not nb.b2_entered, (len(p_nb), len(p_st), nb.b2_entered[:3]))

# ====================================================================================================== 12. the Waveform knobs
# Clip mode on the Waveform screen (README section 3, notes/re/a3): stock unbinds all four knobs and never draws the loop
# bracket. Patched: TL = Loop Start (0x91), TR = Loop End (0x92), sample positions (type 0xd) one zoom pixel a step, ranged
# as stock ranges them in Sample mode; BL = Slip, BR = Loop Len; the white bracket when Region plays the loop. Real: the
# screen's setup FUN_080a54a0 (its bind block, FUN_080a53a2, the refresh), the binder FUN_080a7ee0, the knob widget (reset,
# label, type, range, value, list, the turn FUN_080b0d54, stepper, accelerator, formatter, clipwin_format / clipwin_turn
# in them), the view's two handlers (FUN_080a6d28: the knob event 0x32, the param-changed refresh 0x66; FUN_080a66dc: the
# forward of 0x3d / 0x3c with JOEBOX's slice_forward in it, the zoom message 0xe5), the waveform's slice-marker setter
# FUN_080c6e8c and its zoom set FUN_080c6f44, and the app's SetCellParam FUN_0809fa50 for what the forward sends. Stubbed:
# the app's copy of the pad's store into the view (FUN_0809a830: the store kept here), the file name, text widgets
# (recorded), icons, buttons and the mode list, the knob redraw, the view's post (recorded); SetCellParam's posts to the
# engine and the UI (recorded). The app posting 0x66 after it stored a value is done here, as the app does it.
SITES12 = {"clipwin_bind": (0x080A582A, 0x080A7EE0), "clipwin_zoom": (0x080A53B0, 0x080A52C4),
           "clipwin_wave": (0x080A5B0E, 0x080C6E8C)}
VIEW, VENT, VMSG = 0x24060000, 0x24070000, 0x24078000
KN12 = {"TL": 0x670, "BL": 0x950, "TR": 0xC30, "BR": 0xF10}
WV = VIEW + 0x38
CLIP12 = {0x8B: 1, 0xEA: 0, 0x8E: 1, 0x8F: 0, 0x90: 0, 0x91: 24000, 0x92: 72000, 0x8D: 1, 0x94: 3, 0x47: 3, 0xD2: 0,
          P_REGION: AUTO, P_SLIP: 480, P_LOOPLEN: 3}


class Screen:
    """the Waveform view of pad (1, 2) on an emulator of `image`; bypass = the three Waveform hooks put back to stock;
    bank2=False: bank 2's header wiped before anything runs (entries into cw_* counted in b2_entered); stock_knob = the
    knob's text and turn hooks (clipwin_format, clipwin_turn) put back to stock; compose: the knob's real redraw
    (FUN_080b0480, its "%s %s" line of name and value, recorded at the knob's + 0xf4 text), else stubbed"""

    def __init__(self, image=IMAGE, bypass=False, bank2=True, stock_knob=False, compose=False):
        m = self.m = Emu(image, "out/cave.elf")
        maps(m)
        self.b2_entered = []
        if not bank2:
            no_bank2(m, self.b2_entered)
        if stock_knob:
            for at in (0x080B0746, 0x080B0E18, 0x080B0DDE):
                m.uc.mem_write(at, stock[at - BASE:at - BASE + 4])
        registrar(m, TABLE)
        if bypass:
            for at, _ in SITES12.values():
                m.uc.mem_write(at, stock[at - BASE:at - BASE + 4])
        m.uc.mem_write(VIEW, bytes(0x5000))
        for o in KN12.values():
            m.w32(VIEW + o, 0x080F0C88)
        self.vals, self.texts, self.posts, self.binds = {}, [], [], []
        m.stub(0x0809A830, lambda: self.copy(self.vals))
        m.stub(0x0809AD74, lambda: m.uc.mem_write(m.arg(2), b"loop.wav\0"))
        if compose:                                          # the text set for real (the line reads the widgets back)
            m.uc.hook_add(UC_HOOK_CODE, lambda *a: self.texts.append((m.arg(0) - VIEW, m.cstr(m.arg(1)))),
                          begin=0x080C3B98, end=0x080C3B98)
        else:
            m.stub(0x080C3B98, lambda: self.texts.append((m.arg(0) - VIEW, m.cstr(m.arg(1)))))
        for a in (0x080A5480, 0x080A3DEC, 0x080C6078, 0x080C4DD6, 0x080A401C, 0x080BD398, 0x080BD74E,
                  0x080C6004, 0x080A5210) + (() if compose else (0x080B0480,)):
            m.stub(a)
        self.ov = []                                         # the overview strip's length set (FUN_080c4df0), recorded
        m.stub(0x080C4DF0, lambda: self.ov.append((m.arg(0) - VIEW, m.arg(1))))
        m.stub(0x080A331A, lambda: m.uc.mem_write(m.arg(0) + 0x30, bytes([m.arg(1) & 0xFF])))   # a knob's grey flag
        m.stub(0x080AED14, lambda: self.posts.append((m.r16(m.arg(1)), m.r32(m.arg(1) + 0xC), m.r32(m.arg(1) + 0x10))))
        m.uc.hook_add(UC_HOOK_CODE, lambda *a: self.binds.append((m.arg(0), m.arg(1), m.arg(2) - VIEW)),
                      begin=0x080A7EE0, end=0x080A7EE0)
        m.w32(VIEW + 0x2390, 192000)                         # the file's length
        m.w32(VIEW + 0x47C8 + 8, 400)                        # the marker stepper's counts per step
        m.uc.mem_write(VIEW + 0x29C, struct.pack("<H", 0x12))
        m.uc.mem_write(VIEW + 0x3740, b"\x01")               # turns go to the knobs (not the popup list)
        m.w32(GUI_MS, 10_000)
        sdram(m)                                             # the Slip knob's hold on 0 lives in cw_bank
        m.w32(BANK, 0)

    def copy(self, vals):
        rows = sorted(vals.items())
        self.m.uc.mem_write(VENT, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
        self.m.w32(VIEW + 0x2370 + 4, VENT)
        self.m.uc.mem_write(VIEW + 0x2370 + 10, struct.pack("<HH", len(rows), 96))

    def msg(self, handler, mid, a=0, b=0, pad=0x12):
        self.m.uc.mem_write(VMSG, struct.pack("<HHIHHiiI", mid, 0, 0x080CFBA4, pad, 0, a, b, 0))
        self.m.call(handler, VIEW, VMSG, count=50_000_000)

    def open(self, vals, was=0):
        """the screen set up for the pad, which was in mode `was` the last time the view looked"""
        self.vals = dict(vals)
        self.copy({**vals, 0x8B: was})
        self.binds.clear()
        self.texts.clear()
        self.m.call(0x080A54A0, VIEW, 0, count=50_000_000)

    def stored(self, **upd):
        """the app stored the pad's value(s) and posts 0x66: the view's refresh"""
        self.vals.update({int(k[1:], 16): v for k, v in upd.items()})
        self.msg(0x080A6D28, 0x66)

    def turn(self, k, counts, t=None):
        """one knob event (0x32: TL 0, BL 1, TR 2, BR 3) -> the knob's own post -> the view's forward; then the app
        stores what was forwarded and posts 0x66. Returns (the knob's posts, the forwards)"""
        if t is not None:
            self.m.w32(GUI_MS, t)
        self.posts.clear()
        self.msg(0x080A6D28, 0x32, k, counts)
        own, fwd = list(self.posts), []
        for p_ in own:
            self.posts.clear()
            self.m.uc.mem_write(VMSG, struct.pack("<HHIHHiiI", p_[0], 0, 0x080CFBA4, 0, 0, p_[1], p_[2], 0))
            self.m.call(0x080A66DC, VIEW, VMSG, count=50_000_000)
            fwd += self.posts
        for p_ in fwd:
            if p_[0] == 0x6E:
                self.vals[p_[1]] = p_[2]
        if fwd:
            self.msg(0x080A6D28, 0x66)
        return own, fwd

    def knob(self, name):
        k = VIEW + KN12[name]
        m = self.m
        return dict(id=m.r32(k + 0x14), type=m.r8(k + 0x31), lo=m.r32(k + 0x14C), hi=m.r32(k + 0x150), step=m.r32(k + 0x28C),
                    pending=m.r32(k + 0x290), idx=m.r32(k + 0x27C), start=m.r32(k + 0x288), n=m.r32(k + 0x280),
                    acc=m.r32(k + 0x270), grey=m.r8(k + 0x30))

    def shown(self, name):
        """the knob's value as the turn would post it: type 0xd the pending position, else idx x step + start; others
        idx + start"""
        k = self.knob(name)
        if k["type"] == 0xD:
            return k["pending"] if k["pending"] != 0x7FFFFFFE else min(max(k["idx"] * k["step"] + k["start"], k["lo"]), k["hi"])
        return k["idx"] + k["start"]

    def text(self, name, off=0x9C):
        t = [x for a, x in self.texts if a == KN12[name] + off]
        return t[-1] if t else None

    def wave(self):
        m = self.m
        return dict(on=m.r8(WV + 0x239), ls=m.r32(WV + 0x22C), le=m.r32(WV + 0x230), dirty=m.r8(WV + 0x32),
                    slices=m.r8(WV + 0x238), startlen=m.r8(WV + 0x23A))

    def state(self):
        return {n: self.knob(n) for n in KN12} | {"wave": self.wave()}


# ---- Clip: the setup binds the four knobs, the position pair stepped, ranged and valued in that order
sc = Screen()
sc.open(CLIP12)
b_ = sc.binds
st = sc.state()
check(f"Clip setup: stock's three unbinds (TL, TR, BL), then the hook at BR binds TL 0x91 = 24 000, TR 0x92 = 72 000, BL "
      f"Slip = 480, BR Loop Len = 3 through the stock binder with the store's values ({[(hex(i), v, hex(o)) for i, v, o in b_]})",
      b_ == [(0, 0, 0x670), (0, 0, 0xC30), (0, 0, 0x950), (0x91, 24000, 0x670), (0x92, 72000, 0xC30), (P_SLIP, 480, 0x950),
             (P_LOOPLEN, 3, 0xF10)], b_)
check(f"  names {[sc.text(n, 0x44) for n in ('TL', 'TR', 'BL', 'BR')]} (the binder's, from the table, then this screen's: "
      f"{[x for a, x in sc.texts if a in (0x670 + 0x44, 0xC30 + 0x44, 0x950 + 0x44, 0xF10 + 0x44)]}), texts "
      f"{[sc.text(n) for n in ('TL', 'TR', 'BL', 'BR')]} (Slip as beats.ticks, Loop Len its name)",
      [sc.text(n, 0x44) for n in ("TL", "TR", "BL", "BR")] == ["LpS", "LpE", "Slip", "LpLen"]
      and [sc.text(n) for n in ("TL", "TR", "BL", "BR")] == ["24000", "72000", "+0.480", "1/4"], sc.texts[-12:])

# ---- the knobs' lines fit ("Loop Start", "Loop End", "Slip", "Loop Len" are too long: the values would be hidden
# by the neighbour's name). A knob draws "name value" (FUN_080b0480, real here) in its + 0xf4 text: the box and the
# alignment from the knob's own set-rect FUN_080afeb2 (real) on the rects and styles the view's constructor FUN_080a5b90
# gives them (TL (0, 74, 157, 73) style 1, BL (0, 0, ...) 2, TR (158, 74, ...) 3, BR (158, 0, ...) 4, its text size
# 0x10), the width of a line from the text draw's own measure (FUN_0808ed28: length x the font's width x 2 at size 0x10,
# the font's width a u16 at 0x240000d4, its .data image at 0x080f1d80 + 0xd4)
CHAR_W = struct.unpack_from("<H", img, 0x080F1D80 + 0xD4 - BASE)[0] * 2
geom = {}
for name, (x, y, style) in {"TL": (0, 0x4A, 1), "BL": (0, 0, 2), "TR": (0x9E, 0x4A, 3), "BR": (0x9E, 0, 4)}.items():
    kn = 0x24068000
    e.uc.mem_write(kn, bytes(0x300))
    e.uc.mem_write(kn + 0x32, bytes([style]))
    e.uc.mem_write(kn + 0x98, b"\x10")
    e.uc.mem_write(0x24068400, struct.pack("<4i", x, y, 0x9D, 0x49))
    e.stub(0x080AEC44)
    e.call(0x080AFEB2, kn, 0x24068400)
    del e.stubs[0x080AEC44]
    geom[name] = (e.r32(kn + 0xF4 + 4), e.r32(kn + 0xF4 + 0xC), e.r8(kn + 0xF4 + 0x51))   # x, w, alignment (1 left, 3 right)


def extent(name, line):
    x, w, al = geom[name]
    n = len(line) * CHAR_W
    return (x, x + n) if al == 1 else (x + w - n, x + w)


def lines(scr):
    return {n: [x for a, x in scr.texts if a == KN12[n] + 0xF4][-1] for n in KN12}


def fits(ln):
    """each line inside its box, and the two of a row clear of each other"""
    ex = {n: extent(n, ln[n]) for n in ln}
    inside = all(geom[n][0] <= ex[n][0] and ex[n][1] <= geom[n][0] + geom[n][1] for n in ln)
    return inside and ex["TL"][1] <= ex["TR"][0] and ex["BL"][1] <= ex["BR"][0], ex


big = {**CLIP12, 0x91: 99999998, 0x92: 99999999, P_SLIP: -3840, P_LOOPLEN: 7}
mid = {**CLIP12, 0x91: 1000000, 0x92: 1234567}
for what, vals_, length in (("the setup's values", CLIP12, 192000),
                            ("positions of seven digits (a loop past 21 s of a 30 s file)", mid, 1440000),
                            ("the widest ones (positions of eight digits, Slip -4.000, Loop Len 4 bars)", big, 100000000)):
    scl = Screen(compose=True)
    scl.m.w32(VIEW + 0x2390, length)
    scl.open(vals_)
    ln = lines(scl)
    ok_, ex = fits(ln)
    check(f"  the four lines with {what}: {ln}; {CHAR_W} px a character, each inside its {geom['TL'][1]}-px box "
          f"(left from x {geom['TL'][0]}, right ending at {geom['TR'][0] + geom['TR'][1]}) and clear of its neighbour: {ex}",
          ok_ and geom["TL"][2] == 1 and geom["TR"][2] == 3 and geom["BL"][2] == 1 and geom["BR"][2] == 3
          and ln["TL"].startswith("LpS ") and ln["BR"].startswith("LpLen "), (ln, ex, geom))
old_names = {"TL": "Loop Start:", "TR": "Loop End:", "BL": "Slip:", "BR": "Loop Len:"}
old_ok, old_ex = fits({n: f"{old_names[n]} {v}" for n, v in (("TL", 24000), ("TR", 72000), ("BL", "+0.480"), ("BR", "1/4"))})
check(f"  ...where the table's names (the binder's) do not fit even the setup's values: {old_ex}", not old_ok, old_ex)
tl, tr = st["TL"], st["TR"]
check(f"  TL Loop Start: type 0xd, a step of the setup's zoom (256 frames a pixel), 0 .. Loop End, at 24 000 (stock's binder "
      f"alone leaves 0 .. 1000 with 1 000 shown: {tl}); TR Loop End: 24 000 .. the length 192 000, at 72 000 ({tr})",
      (tl["type"], tl["step"], tl["lo"], tl["hi"], sc.shown("TL")) == (0xD, 256, 0, 72000, 24000)
      and (tr["type"], tr["step"], tr["lo"], tr["hi"], sc.shown("TR")) == (0xD, 256, 24000, 192000, 72000), (tl, tr))
check(f"  BL Slip type 1 at +480, BR Loop Len a list (type 5) at 1/4, none greyed ({st['BL']}, {st['BR']})",
      st["BL"]["type"] == 1 and sc.shown("BL") == 480 and st["BR"]["type"] == 5 and sc.shown("BR") == 3
      and not any(st[n]["grey"] for n in KN12), (st["BL"], st["BR"]))
w_ = st["wave"]
check(f"  the loop bracket drawn (Region Auto, Loop Mode on): [24 000, 72 000), shown, dirty; slice markers and the pink "
      f"start bracket off as stock leaves them ({w_})", w_ == dict(on=1, ls=24000, le=72000, dirty=1, slices=0, startlen=0), w_)

# stock (and the hooks bypassed): nothing bound, no bracket
for nm, scr in (("stock", Screen(STOCK)), ("hooks bypassed", Screen(bypass=True))):
    scr.open(CLIP12)
    s2 = scr.state()
    check(f"  on the {nm} image the same setup binds nothing (ids {[hex(s2[n]['id']) for n in KN12]}, types "
          f"{[s2[n]['type'] for n in KN12]}) and draws no bracket ({s2['wave']['on']})",
          all(s2[n]["id"] == 0 and s2[n]["type"] == 0 for n in KN12) and s2["wave"]["on"] == 0, s2)

# ---- turns through the view: the knob posts, the view forwards to the app, the app stores and posts 0x66, the view
# refreshes. TL and TR turn as stock's own Loop Start and Loop End knobs turn in Sample mode, where they are BL and BR:
# the same screen in Sample mode at the same zoom, the same turns - the same posts and knob states, turn after turn
sm = Screen()
sm.open({**CLIP12, 0x8B: 0}, was=1)
sm.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 256.0))
sm.msg(0x080A66DC, 0xE5)                                   # Sample mode fits the whole file: zoomed in to the Clip's 256
pos = lambda s_, n: {k: s_.knob(n)[k] for k in ("type", "lo", "hi", "step", "idx", "start", "pending")}
seq = [(0, -400), (0, 1200), (2, -400), (2, 2800), (0, -8000), (2, -400 * 3)]
clip_f, samp_f, alike, drawn = [], [], [], []
for i, (k, c) in enumerate(seq):
    sc.m.uc.mem_write(WV + 0x32, b"\x00")              # drawn: each turn moves the pair under a bracket that stays shown
    clip_f += sc.turn(k, c, t=20_000 + 100 * i)[1]
    samp_f += sm.turn({0: 1, 2: 3}[k], c, t=20_000 + 100 * i)[1]
    alike.append(pos(sc, "TL") == pos(sm, "BL") and pos(sc, "TR") == pos(sm, "BR"))
    w = sc.wave()
    drawn.append((w["on"], w["dirty"], (w["ls"], w["le"]) == (sc.vals[0x91], sc.vals[0x92])))
st = sc.state()
ls, le = sc.vals[0x91], sc.vals[0x92]
check(f"TL / TR turned slow and fast, down and up ({len(seq)} turns): the same posts as Sample mode's Loop Start / End knobs "
      f"({clip_f}), the same steps, ranges and positions after each turn ({alike}); one step down from 24 000 posts 23 552, "
      "the stepper cell below 24 000's, as stock's (the binder alone would post 999)",
      clip_f == samp_f and len(clip_f) == len(seq) and all(alike) and clip_f[0] == (0x6E, 0x91, 23552), (clip_f, samp_f, alike))
check(f"  each forwarded as 0x6e and stored; the refresh ranges each by the other (TL 0 .. {st['TL']['hi']}, TR "
      f"{st['TR']['lo']} .. {st['TR']['hi']}) and the bracket follows: [{st['wave']['ls']}, {st['wave']['le']}), shown "
      f"through every turn, each turn's new pair drawn and marked dirty (on, dirty, the stored pair: {drawn})",
      all(x[0] == 0x6E and x[1] in (0x91, 0x92) for x in clip_f) and (st["TL"]["lo"], st["TL"]["hi"]) == (0, le)
      and (st["TR"]["lo"], st["TR"]["hi"]) == (ls, 192000) and (st["wave"]["on"], st["wave"]["ls"], st["wave"]["le"]) == (1, ls, le)
      and drawn == [(1, 1, True)] * len(seq), (st["TL"], st["TR"], st["wave"], ls, le, drawn))
sc.m.uc.mem_write(WV + 0x32, b"\x00")
sc.stored()
check(f"a refresh that changes nothing leaves the waveform clean (dirty {sc.wave()['dirty']})", sc.wave()["dirty"] == 0)
own, fwd = sc.turn(3, -800, t=20_300)
check(f"BR Loop Len two list steps down: 1/16 (index 1), sent as a list change (0x3c) and forwarded as 0x6e 0x1ca "
      f"({own}, {fwd}); text {sc.text('BR')}", own == [(0x3C, 1, P_LOOPLEN)] and fwd == [(0x6E, P_LOOPLEN, 1)]
      and sc.text("BR") == "1/16" and sc.shown("BR") == 1, (own, fwd, sc.text("BR")))

# Slip on BL: the same knob as on the Pos page, every turn coming back as a refresh. A refresh re-values only a value the
# store holds differently: a set value parks the stepper mid-step, which on every turn would double the slow speed.
def slip_run(round_trip, per_ms, events, sign=1, start=0):
    s_ = Screen()
    s_.open({**CLIP12, P_SLIP: start})
    c, t = sign * int(per_ms * 16), 30_000
    k = VIEW + 0x950
    for i in range(8):
        s_.m.uc.mem_write(k + 0x294 + 8 * i, struct.pack("<iI", c, t - 16 * (7 - i)))
    s_.m.w32(k + 0x2D4, 0)
    vals_ = []
    for _ in range(events):
        t += 16
        if round_trip:
            s_.turn(1, c, t=t)
        else:
            s_.m.w32(GUI_MS, t)
            s_.m.call(0x080B0D54, k, c)
        vals_.append(s_.shown("BL"))
    return vals_, s_


rt, s_ = slip_run(True, 0.7, 40)
bare, _ = slip_run(False, 0.7, 40)
check(f"BL Slip, slow (0.7 counts/ms, 40 events): every turn forwarded and refreshed gives the bare knob's values, 1 tick "
      f"per 40 counts ({rt[-1]} vs {bare[-1]}; store {s_.vals[P_SLIP]}, text {s_.text('BL')})",
      rt == bare and rt[-1] == 40 * 11 // 40 and s_.vals[P_SLIP] == rt[-1] and s_.text("BL") == "+0.011", (rt[-5:], bare[-5:]))
rt, s_ = slip_run(True, 6, 20, sign=-1, start=300)
bare, _ = slip_run(False, 6, 20, sign=-1, start=300)
n_held = (DETENT - 1) // 16                                # the events under ZERO_DETENT_MS after the arrival
check(f"  fast down from +300 through the view: the 1/64 grid, the detent on 0 for {n_held} events, then past it "
      f"({rt[:6]} ... {rt[-3:]}), as the bare knob ({bare[:6]} ... {bare[-3:]})",
      rt == bare and rt[:5] == [240, 180, 120, 60, 0] and rt[5:5 + n_held] == [0] * n_held
      and rt[5 + n_held:] == [-GRID * (i + 1) for i in range(15 - n_held)] and s_.vals[P_SLIP] == rt[-1], (rt, bare))
s_.stored(_1c9=-1200)
check(f"  a Slip the store gets from elsewhere is shown at the next refresh ({s_.shown('BL')}, {s_.text('BL')})",
      s_.shown("BL") == -1200 and s_.text("BL") == "-1.240", (s_.shown("BL"), s_.text("BL")))

# what the forward sends, the app stores (SetCellParam FUN_0809fa50, real): a Clip pad's store takes all four
sp_posts = []
sc.m.stub(0x0804C59C, lambda: sp_posts.append(("engine", sc.m.arg(1), sc.m.arg(2), sc.m.arg(3))))
sc.m.stub(0x080B5758, lambda: sp_posts.append(("ui", sc.m.r16(sc.m.arg(1)), sc.m.r16(sc.m.arg(1) + 8))))
CLS = 0x24079000
sc.m.uc.mem_write(CLS, struct.pack("<HH", 0x2003, 0x4770))                 # movs r0, #3; bx lr: a pad store's class
sc.m.w32(CLS + 0x10, CLS | 1)
ST12, ENT12 = APP_PADS + 1 * 0xF0 + 2 * 0x30, 0x2407A000
rows = sorted(CLIP12.items())
sc.m.uc.mem_write(ENT12, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
sc.m.w32(ST12, CLS + 0x10)
sc.m.w32(ST12 + 4, ENT12)
sc.m.uc.mem_write(ST12 + 10, struct.pack("<HH", len(rows), 96))
CELL12 = 0x2407B000
sc.m.uc.mem_write(CELL12, struct.pack("<IHH", 0, 0x0012, 0))
got, sets12 = {}, ((0x91, 24576), (0x92, 71936), (P_SLIP, -60), (P_LOOPLEN, 1))
for pid, v in sets12:
    sp_posts.clear()
    sc.m.call(0x0809FA50, APP, CELL12, pid, v, 0, count=20_000_000)
    sc.m.call(0x08093E9C, ST12, pid)
    got[pid] = (sc.m.uc.reg_read(66), [x for x in sp_posts])
check(f"SetCellParam on the Clip pad's store (mode {CLIP12[0x8B]}) stores what the forward sends: Loop Start, Loop End, "
      f"Slip, Loop Len, and posts each to the engine and the UI ({ {hex(k): v[0] for k, v in got.items()} })",
      {k: v[0] & 0xFFFFFFFF for k, v in got.items()} == {0x91: 24576, 0x92: 71936, P_SLIP: (-60) & 0xFFFFFFFF, P_LOOPLEN: 1}
      and all(any(x[0] == "engine" for x in v[1]) and any(x[0] == "ui" for x in v[1]) for v in got.values()), got)
# ...and the engine's post is the {cell, id, value} the engine takes (the 0x39 message the Rig's Region and Loop Len runs
# start from): what ties a turn on this screen to what the pad plays
eng12 = {pid: [x[1:] for x in got[pid][1] if x[0] == "engine"] for pid, _ in sets12}
check(f"  each posted to the engine as cell 0x102 (row 1, col 2), the id and the value ({ {hex(k): v for k, v in eng12.items()} })",
      all(eng12[pid] == [(0x102, pid, v & 0xFFFFFFFF)] for pid, v in sets12), eng12)

# ---- the length is the pad's file's. The view's own (+0x2390, FUN_0809a830's copy of the app's
# store + 0x20) is what the app's 0xE handler FUN_080a121c wrote into the first cell whose record names the asset just
# opened (row 0 col 0 first): on the unit both pad stores read 192 000, while pad 1 plays a 336 359-frame file - TR stopped
# at 192 000, and Loop End 192 000 (Loop Start 0) read as the whole file, so no bracket. Here the view holds another
# pad's 192 000 and the engine's last recompute of this pad (cw_bank flen, H3 site 1) 336 359
lv = Screen()
lv.m.w32(BANK, CW_MAGIC)
lv.m.w32(BANK + B_FLEN + 4 * 6, 336359)                     # pad (1, 2), as the recompute leaves it
lv.open({**CLIP12, P_REGION: LOOP, 0x91: 0, 0x92: 192000})
tr_, wv = lv.knob("TR"), lv.wave()
check(f"a view whose own length is another pad's (192 000) and a pad file of 336 359 frames: TR Loop End ranges "
      f"{tr_['lo']} .. {tr_['hi']}, the bracket at [0, 192 000) shows ({wv['on']}: not the whole file), the waveform's "
      f"length (+0x254, its playhead's clamp) {lv.m.r32(WV + 0x254)} and the overview strip's {lv.ov[-1:]}",
      (tr_["lo"], tr_["hi"]) == (0, 336359) and wv["on"] == 1 and (wv["ls"], wv["le"]) == (0, 192000)
      and lv.m.r32(WV + 0x254) == 336359 and lv.ov[-1:] == [(0x2168, 336359)], (tr_, wv, lv.m.r32(WV + 0x254), lv.ov))
lv.stored(_92=300000)
check(f"  ...and Loop End turned up past 192 000 is kept and drawn there ({lv.knob('TR')['hi']}, {lv.wave()['le']})",
      lv.shown("TR") == 300000 and lv.wave()["le"] == 300000 and lv.wave()["on"] == 1, (lv.knob("TR"), lv.wave()))
l0 = Screen()
l0.open({**CLIP12, P_REGION: LOOP, 0x91: 0, 0x92: 192000})
check(f"  with no recompute measured yet (flen 0), the view's own length as before: TR up to {l0.knob('TR')['hi']}, the "
      f"bracket {l0.wave()['on']} ([0, 192 000) is that whole file)", l0.knob("TR")["hi"] == 192000 and l0.wave()["on"] == 0,
      (l0.knob("TR"), l0.wave()))


# (h) on a unit, the Waveform view of pad 1 froze before the end of the audio loop (the overview's rectangle stops, the
# detail view stops in the middle; the pad's +0x248 tracks the whole file). The waveform's tick FUN_080c6c34 (real)
# clamps the playhead the app reports (FUN_0809a810) to its + 0x254, which the bind block's FUN_080c6f44 sets from the
# view's own length: at 192 000 of 336 359 frames it stops at 57 %. Following the playhead (+0x1e0 = 1), at 300 000
def follows_to(scr, at):
    m = scr.m
    m.stub(0x0809A96C)
    m.stub(0x0809A810, lambda: (m.uc.reg_write(UC_ARM_REG_R1, 0), m.ret(at)))
    m.stub(0x080C6A78)
    m.stub(0x080C6ACC)
    m.uc.mem_write(WV + 0x1E0, b"\x01")
    m.call(0x080C6C34, WV, 0x2407D000)
    return m.r32(WV + 0x244)


check(f"  (h) the waveform's tick following the playhead at 300 000: the view goes there ({follows_to(lv, 300000)}); with "
      f"the view's own 192 000 it stops at {follows_to(l0, 300000)} (stock: the freeze at 57 %)",
      follows_to(lv, 300000) == 300000 and follows_to(l0, 300000) == 192000)

# ---- a TL or TR turn takes the view to the edge it moves (it was following the playhead, which
# ran the edge being set off the screen), and the view follows the playhead again after a pause. That is stock's own
# tap on the overview strip (the view handler's FUN_080c6e68 at 0x080a6cc0): the frame at the view's anchor (+ 0x244,
# drawn at the pixel + 0x240), the waveform's follow mode + 0x1e0 = 2 and its count + 0x180 = 300. Its tick FUN_080c6c34
# (real) counts down and holds the view, then (mode 1) follows the playhead again; each turn sets the count again.
def tick(scr, at, n=1):
    """n of the waveform's ticks with the pad playing at frame `at` (its per mille <= 1000): the view's anchor frame"""
    m = scr.m
    m.stub(0x0809A96C, lambda: m.w32(m.arg(0) + 8, 500))
    m.stub(0x0809A810, lambda: (m.uc.reg_write(UC_ARM_REG_R1, 0), m.ret(at)))
    m.stub(0x080C6A78)
    for _ in range(n):
        m.call(0x080C6C34, WV, 0x2407D000)
    return m.r32(WV + 0x244)


def follow(scr):
    """(the view's anchor frame, its follow mode, its count)"""
    return scr.m.r32(WV + 0x244), scr.m.r8(WV + 0x1E0), scr.m.r32(WV + 0x180)


jv = Screen()
jv.open({**CLIP12, P_REGION: LOOP})
opened = follow(jv)
jv.m.uc.mem_write(WV + 0x1E0, b"\x01")
at0 = tick(jv, 150000)
_, f_tl = jv.turn(0, -400, t=50_000)
ls_ = jv.vals[0x91]
got_tl = follow(jv)
check(f"a TL turn (Loop Start to {ls_}) while the view follows the playhead at {at0}: the view goes to Loop Start and "
      f"holds, stock's overview tap ({got_tl}: anchor, mode 2, 300 ticks); not on the setup ({opened})",
      at0 == 150000 and f_tl and f_tl[0][1] == 0x91 and ls_ < 24000 and got_tl == (ls_, 2, 300) and opened[1] != 2,
      (at0, f_tl, got_tl, opened))
held = tick(jv, 151000, 299)
back = tick(jv, 152000)
check(f"  the view stays on Loop Start for 299 ticks of the playing pad ({held}), then follows the playhead again "
      f"({back}, mode {jv.m.r8(WV + 0x1E0)})", held == ls_ and back == 152000 and jv.m.r8(WV + 0x1E0) == 1,
      (held, back, follow(jv)))
_, f_tr = jv.turn(2, 400, t=60_000)
le_ = jv.vals[0x92]
got_tr = follow(jv)
tick(jv, 153000, 150)
_, f_tr2 = jv.turn(2, 400, t=60_500)
le2 = jv.vals[0x92]
mid = tick(jv, 154000, 299)
check(f"  a TR turn: the view to Loop End ({got_tr}, Loop End {le_}); a second turn 150 ticks later starts the count "
      f"again: still on its Loop End {le2} 299 ticks after it ({mid}), then the playhead ({tick(jv, 155000)})",
      f_tr and f_tr[0][1] == 0x92 and le_ > 72000 and got_tr == (le_, 2, 300) and f_tr2 and le2 > le_ and mid == le2
      and jv.m.r32(WV + 0x244) == 155000, (got_tr, le_, le2, mid, follow(jv)))
# what does not move the view: Slip and Loop Len, both ends at once (not a knob: a preset, a load), a bracket that
# appears or goes (a Region change), a zoom, a bracket Region does not play (no bracket: Region File), no bank 2
nm, ok_ = [], True
jv.m.uc.mem_write(WV + 0x1E0, b"\x01")
for name, act in [("Slip turned (BL)", lambda: jv.turn(1, 400, t=70_000)), ("Loop Len turned (BR)", lambda: jv.turn(3, 400, t=80_000)),
                  ("both ends stored at once", lambda: jv.stored(_91=12000, _92=96000)),
                  ("Region File (the bracket goes)", lambda: jv.stored(_1c8=FILE)),
                  ("Loop Start stored under Region File", lambda: jv.stored(_91=6000)),
                  ("Region Loop again (the bracket comes back)", lambda: jv.stored(_1c8=LOOP)),
                  ("a zoom (msg 0xe5)", lambda: jv.msg(0x080A66DC, 0xE5))]:
    jv.m.w32(WV + 0x244, 160000)
    act()
    nm.append((name, follow(jv)))
    ok_ &= follow(jv)[:2] == (160000, 1)
fv = Screen()
fv.open({**CLIP12, P_REGION: FILE})
fv.m.uc.mem_write(WV + 0x1E0, b"\x01")
fv.m.w32(WV + 0x244, 160000)
fv.turn(0, -400, t=50_000)
nb2 = Screen(bank2=False)
nb2.open({**CLIP12, P_REGION: LOOP})
nb2.m.uc.mem_write(WV + 0x1E0, b"\x01")
nb2.m.w32(WV + 0x244, 160000)
nb2.turn(0, -400, t=50_000)
check(f"  the view stays with the playhead on {[n for n, _ in nm]} ({set(f for _, f in nm)}); on a TL turn under "
      f"Region File, no bracket ({follow(fv)}); and without bank 2, as stock ({follow(nb2)}, entered {nb2.b2_entered[:2]})",
      ok_ and follow(fv)[:2] == (160000, 1) and follow(nb2)[:2] == (160000, 1) and fv.vals[0x91] < 24000
      and nb2.vals[0x91] < 24000, (nm, follow(fv), follow(nb2)))

# ---- while the view holds on that edge, the white playhead line would mark the edge, not the playhead. In Clip mode
# the bind block pins the line to the anchor pixel (+ 0x248 = 1: + 0x23c = + 0x240 at each tick) and scrolls the
# waveform under it. clipwin_line (at the tick's FUN_080c6acc) puts it left of the waveform's box for the hold (the
# draw, FUN_080c6338 @0x080c68f2, draws + 0x23c only from the box's x + 0x4), and the tick puts it back after. Sample
# mode (+ 0x248 = 0: the line moves over the view) keeps stock's line, held or not.
def line(scr):
    """the playhead line's pixel from the waveform box's left edge: < 0 is not drawn"""
    return scr.m.r32(WV + 0x23C) - scr.m.r32(WV + 0x4)


lh = Screen()
lh.open({**CLIP12, P_REGION: LOOP})
lh.m.uc.mem_write(WV + 0x1E0, b"\x01")
tick(lh, 150000)
following = line(lh), lh.m.r32(WV + 0x240) - lh.m.r32(WV + 0x4)
lh.turn(0, -400, t=50_000)
tick(lh, 151000)
holding = line(lh), follow(lh)
tick(lh, 151000, 298)
still = line(lh), follow(lh)[1:]
tick(lh, 152000)
after = line(lh), follow(lh)[:2]
check(f"the line on a Clip view (+0x248 {lh.m.r8(WV + 0x248)}): on the anchor pixel while it follows the playhead "
      f"({following}); after a TL turn, out of the box while the view holds on Loop Start ({holding}), still for the "
      f"hold's 299th tick ({still}); back on the anchor when the view follows the playhead again ({after})",
      lh.m.r8(WV + 0x248) == 1 and following[0] == following[1] >= 0 and holding[0] < 0 and holding[1][1] == 2
      and still == (holding[0], (2, 1)) and after == (following[0], (152000, 1)), (following, holding, still, after))
sp = Screen()
sp.open({**CLIP12, 0x8B: 0})
sp.m.w32(WV + 0x244, 151000)
sp.m.uc.mem_write(WV + 0x1E0, b"\x02")
sp.m.w32(WV + 0x180, 300)
tick(sp, 151000)
check(f"  a Sample view (+0x248 {sp.m.r8(WV + 0x248)}) held the same way (an overview tap) keeps stock's line, on the "
      f"playhead: {line(sp)} (the anchor's {sp.m.r32(WV + 0x240) - sp.m.r32(WV + 0x4)}, mode {sp.m.r8(WV + 0x1E0)})",
      sp.m.r8(WV + 0x248) == 0 and sp.m.r8(WV + 0x1E0) == 2 and line(sp) == sp.m.r32(WV + 0x240) - sp.m.r32(WV + 0x4) >= 0,
      (line(sp), follow(sp)))

# ---- the zoom: msg 0xe5 (no refresh follows it) re-steps the pair, keeping range and value, as Sample mode's
for s_ in (sc, sm):
    s_.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 16.0))
    s_.msg(0x080A66DC, 0xE5)
st = sc.state()
check(f"zoom to 16 frames a pixel (msg 0xe5): TL and TR step 16, same ranges and values ({st['TL']['step']}, "
      f"{st['TR']['step']}; {sc.shown('TL')}, {sc.shown('TR')}), as Sample mode's pair",
      (st["TL"]["step"], st["TR"]["step"], st["TL"]["hi"], st["TR"]["lo"], sc.shown("TL"), sc.shown("TR")) == (16, 16, le, ls, ls, le)
      and pos(sc, "TL") == pos(sm, "BL") and pos(sc, "TR") == pos(sm, "BR"), (st["TL"], st["TR"]))
f1, f2 = sc.turn(2, 400, t=40_000)[1], sm.turn(3, 400, t=40_000)[1]
check(f"  TR one step up then: {f1}, a pixel at that zoom, as Sample mode's ({f2})", f1 == f2 == [(0x6E, 0x92, le + 16)], (f1, f2))
sc.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 0.5))
sc.msg(0x080A66DC, 0xE5)
check(f"  a zoom under one frame a pixel (0.5) steps 1 frame ({sc.knob('TL')['step']}, {sc.knob('TR')['step']})",
      sc.knob("TL")["step"] == 1 and sc.knob("TR")["step"] == 1)

# ---- the bracket shows what Region plays (the engine's rule, is_loop), marked dirty only when it changes
br = Screen()
br.open(CLIP12)
cases = [("Region File", dict(_1c8=FILE), 0), ("Auto, Loop Mode None", dict(_1c8=AUTO, _8e=0), 1),
         ("Loop, Loop Mode None", dict(_1c8=LOOP), 1), ("Loop, the whole file [0, 192 000)", dict(_91=0, _92=192000), 0),
         ("Loop, [0, 191 999] (a whole-file smpl loop)", dict(_92=191999), 0), ("Loop, [1, 191 999)", dict(_91=1), 1),
         ("Loop, Loop End past the file", dict(_92=192001), 0), ("Loop, Loop Start = Loop End", dict(_91=50000, _92=50000), 0),
         ("Auto, Loop Mode on, [24 000, 72 000)", dict(_1c8=AUTO, _8e=1, _91=24000, _92=72000), 1),
         ("Loop End moved while Region plays the loop: [24 000, 96 000)", dict(_92=96000), 1),
         ("Slip changed: nothing moves", dict(_1c9=-30), 1)]
got_, ok_ = [], True
for name, upd, want in cases:
    before = br.wave()
    br.m.uc.mem_write(WV + 0x32, b"\x00")
    br.stored(**upd)
    w = br.wave()
    moved = w["on"] != before["on"] or (w["on"] and (w["ls"], w["le"]) != (before["ls"], before["le"]))
    got_.append((name, w["on"], w["dirty"]))
    ok_ &= w["on"] == want and w["dirty"] == moved and (not want or (w["ls"], w["le"]) == (br.vals[0x91], br.vals[0x92]))
check(f"the bracket at each refresh: shown exactly when Region plays the loop, at [Loop Start, Loop End), dirty only when "
      f"it changed, shown or moved ({[(n, o, d) for n, o, d in got_]})",
      ok_ and [o for _, o, _ in got_] == [w_ for _, _, w_ in cases] and got_[-2][1:] == (1, 1), got_)
MK = 0x2407C000
sl = Screen()
sl.m.uc.mem_write(MK, struct.pack("<3I", 0, 64000, 128000))
sl.m.w32(VIEW + 0x2398, MK)
sl.m.w32(VIEW + 0x2398 + 4, 3)
sl.m.w32(WV + 0x184, MK + 0x100)
sl.open(CLIP12)
w = sl.wave()
check(f"a Clip pad with slice markers: the bracket beside them, the markers still shown (FUN_080c6edc would hide them) ({w})",
      w["on"] == 1 and w["slices"] == 1 and (w["ls"], w["le"]) == (24000, 72000), w)

# ---- without bank 2: the four rows are bound all the same (Loop Start and End are stock's own; Slip and Loop
# Len are kept, as stored, and do nothing), but no bracket shows where Region plays the loop, and the Slip knob is
# stock's: its text and every turn as with the knob's two hooks taken out (the turn's counts straight to the stepper)
nb2, kref = Screen(bank2=False), Screen(stock_knob=True)
runs = []
for scr in (nb2, kref):
    scr.open(CLIP12)
    seq = [scr.turn(1, c, t=40_000 + 16 * i) for i, c in enumerate((400, 400, 1200, -400, 2000, -4000, -40, 9000))]
    scr.stored(_1c9=-30)
    runs.append(({n: scr.knob(n) for n in KN12}, list(scr.texts), seq, list(scr.binds), scr.shown("BL")))
w_nb, w_ref = nb2.wave(), kref.wave()
check(f"no bank 2: the Waveform's Slip knob (BL) is stock's - its text ({nb2.text('BL')!r}, not beats.ticks), eight turns "
      f"(their posts and forwards, the value {runs[0][4]}) and every other knob, text and bind as with the knob's two hooks "
      f"taken out; the four rows bound ({[hex(runs[0][0][n]['id']) for n in KN12]})",
      runs[0] == runs[1] and nb2.text("BL") is not None and "." not in nb2.text("BL")
      and [runs[0][0][n]["id"] for n in KN12] == [0x91, 0x1C9, 0x92, 0x1CA],
      {i: (runs[0][i], runs[1][i]) for i in range(5) if runs[0][i] != runs[1][i]})
check(f"  ...no bracket where Region Auto plays [24 000, 72 000) with bank 2 (shown without it {w_nb['on']}, with it "
      f"{w_ref['on']}), and no bank-2 function entered ({len(nb2.b2_entered)})",
      w_nb["on"] == 0 and w_ref["on"] == 1 and not nb2.b2_entered, (w_nb, w_ref, sorted(set(nb2.b2_entered))))

# ---- the other modes: the screen exactly as with the three hooks taken out - Sample, Granular, Slicer, set up, zoomed,
# refreshed, and Sample after Clip (the Clip binding leaves nothing behind)
for name, steps in (("Sample", [0]), ("Granular", [3]), ("Slicer", [2]), ("Sample after Clip", [1, 0])):
    runs = []
    for scr in (Screen(), Screen(bypass=True)):
        scr.m.w32(WV + 0xC, 476)
        was = 0 if steps[0] else 1
        for mode in steps:
            scr.open({**CLIP12, 0x8B: mode}, was=was)
            was = mode
        scr.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 64.0))
        scr.msg(0x080A66DC, 0xE5)
        scr.stored(_91=30000)
        runs.append((scr.state(), list(scr.texts), list(scr.binds)))
    # after Clip, the knobs' steppers start where the Clip binding left them (stock's reset keeps a stepper), so Sample's
    # own values park them mid-step at the same index: the accumulator differs by half a step, nothing else
    strip = lambda st_: {k: ({kk: vv for kk, vv in v.items() if kk != "acc"} if k in KN12 and len(steps) > 1 else v) for k, v in st_.items()}
    acc = [(runs[0][0][n]["acc"], runs[1][0][n]["acc"], runs[0][0][n]["idx"]) for n in KN12]
    check(f"{name}: knobs, texts, binds and waveform flags as with the Waveform hooks taken out (TL {hex(runs[0][0]['TL']['id'])}, "
          f"bracket {runs[0][0]['wave']['on']})" + (f"; the steppers' accumulators parked mid-step at the same index ({acc})"
                                                     if len(steps) > 1 else ""),
          (strip(runs[0][0]), runs[0][1:]) == (strip(runs[1][0]), runs[1][1:])
          and (len(steps) == 1 or all(a // 400 == b // 400 == i for a, b, i in acc)),
          {k: (runs[0][0][k], runs[1][0][k]) for k in runs[0][0] if runs[0][0][k] != runs[1][0][k]})

# New Rec and New Multi bind nothing (stock's bind block has no branch for modes 4 and 5): after Clip the knobs keep
# these rows there, as on stock they keep Sample's after Sample. A zoom change there leaves them and the bracket alone.
for mode in (4, 5):
    nr = Screen()
    nr.open(CLIP12)
    nr.open({**CLIP12, 0x8B: mode}, was=1)
    nr.m.uc.mem_write(WV + 0x239, b"\x00")
    before = nr.state()
    nr.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 16.0))
    nr.msg(0x080A66DC, 0xE5)
    after = nr.state()
    check(f"{('New Rec', 'New Multi')[mode - 4]} after Clip: nothing rebound ({[hex(after[n]['id']) for n in KN12]}); a zoom change "
          f"there re-steps nothing (TL step {after['TL']['step']}) and draws no bracket ({after['wave']['on']})",
          before == after and after["TL"]["step"] == 256 and after["wave"]["on"] == 0, (before["TL"], after["TL"], after["wave"]))

# ====================================================================================================== 12d. a step 0 inside the audio
# Traced on a unit: pad 1, a whole file, Fit Auto, Slip -645, Sync 1/16. Every ordinary step's segment starts with a
# fade-in of 256 and a countdown of 5 744; the step 0 of each pass with 0 and 6 000: at Attack 0 (param 0x3c -> pad +
# 0xBA1 = 1, stock's default; both pads on the unit) stock starts every step 0 hard (0x08065790: after H1 it moves the
# fade-in into the countdown), right where the file starts, after the last step's fade-out. Moved into the audio (Slip,
# a region from past frame 0, Loop Len's window) or on a seamless wrap (a region or Fit, Loop On, not Trigger: the last
# step crossfades into it), that step 0 clicks out of the notch, or sounds the audio twice under the crossfade (the
# bench's doubled 180 samples). Every run until here had 0xBA1 = 0, the step-0 fade-in on, which is why none of them saw
# it. cw_latch marks such a segment and its first read (cw_slot) gives it back stock's fade-in, (0, c + 256) -> (256,
# c). Measured here on DC sources (each segment's gain, sample by sample), against the same runs with the marks cleared
# before every read (no marks) and with 0xBA1 = 0.


def attack0(r):
    """Attack 0 through stock's own class-B param-set (0x39 {cell, 0x3c, 0}): pad + 0xBA1 = 1"""
    msg = r.alloc(0x18)
    r.uc.mem_write(msg, struct.pack("<BxxxIIII", 0x39, 0, r.cell(), 0x3C, 0))
    r.m.call(PSET, r.pad, r.engine, msg, r.ctx)


def fa_run(attack=0, off=False, **kw):
    """a DC run of scenario(**kw) at Attack 0 (attack=None: the rig's 0xBA1 = 0); off: bank 2's marks cleared
    before each segment read, as if it made none"""
    def setup(r):
        if attack == 0:
            attack0(r)
        if off and r.patched:
            r.uc.hook_add(UC_HOOK_CODE, lambda *a: r.uc.mem_write(BANK + B_FIN + r.q, b"\0"), begin=SITE_READ, end=SITE_READ)
    r = scenario(dc=True, setup=setup, **kw)
    r.hard0 = r.m.r8(r.pad + 0xBA1)
    return r


def fa_segs(r):
    """per segment that sounded: its first sample (where it is first read), the gain of its first sound, its last
    sounding sample, step, launch; and the summed gain (base, gains)"""
    a = [x for x in r.mix if x[2] == 0 and x[1] is not None]
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    made = {m_["sid"]: m_ for m_ in r.made}
    out = {}
    for t0, sid, _, v in a:
        nz = np.nonzero(np.abs(v) > 1e-7)[0]
        if not len(nz):
            continue
        d = out.setdefault(sid, dict(at=first.get(sid), g0=None, end=0, step=made[sid]["step"], launch=made[sid]["launch"],
                                     fade=[]))
        if d["g0"] is None:
            d["g0"] = float(v[nz[0]])
        d["end"] = max(d["end"], t0 + int(nz[-1]))
        if len(d["fade"]) < FADE:
            d["fade"] += [float(x) for x in v[:FADE - len(d["fade"])]] if t0 >= d["at"] else []
    s = np.concatenate([x[0] + np.arange(len(x[3])) for x in a])
    g = np.concatenate([x[3] for x in a]).astype(np.float64)
    base = int(s.min())
    return out, base, np.bincount(s - base, weights=g)


FADE = 256
fa_cases = [("Fit Auto, a 3.74-beat file (89 760), Slip -645, Sync 1/16", dict(frames=89760, beats=0, slip=-645, sync=5,
                                                                             vals={P_FIT: 1}), True),
            ("Fit Auto, Slip +60, Sync 1/4", dict(frames=89760, beats=0, slip=60, sync=3, vals={P_FIT: 1}), True),
            ("Fit Off, the matched file (96 000), Slip -645, Sync 1/16", dict(frames=96000, slip=-645, sync=5), False),
            ("Fit Off, Slip +60, Sync 1/4", dict(frames=96000, slip=60, sync=3), False),
            ("a Region from 6 072 (Loop, [6 072, 102 072) of 192 000), Slip 0, Sync 1/4",
             dict(frames=192000, beats=4, points=(6072, 102072, 1), region=LOOP, cell=0x102, sync=3), True)]
for name, kw, seamless_ in fa_cases:
    kw = dict(blocks=1700, **kw)
    off, on, ref = fa_run(off=True, **kw), fa_run(**kw), fa_run(attack=None, **kw)
    so, bo, go = fa_segs(off)
    sn, bn, gn = fa_segs(on)
    sr, br, gr = fa_segs(ref)
    wo = [d for d in so.values() if d["step"] == 0 and not d["launch"]]
    wn = [d for d in sn.values() if d["step"] == 0 and not d["launch"]]
    since = min(d["at"] for d in wn) - 1 if wn else 0
    ordinary = [d for d in sn.values() if d["step"] and not d["launch"] and d["at"] > since and len(d["fade"]) == FADE]
    peak = lambda b, g: float(g[since - b:].max()) if wn else 9.0
    info(f"step 0, {name}: Attack 0 = pad + 0xBA1 {on.hard0} (0xBA1 = 0 run: {ref.hard0}); passes at {[d['at'] for d in wn]}")
    check(f"step 0, {name}: without the marks (cleared), every pass's step 0 starts at full gain "
          f"({sorted({round(d['g0'], 3) for d in wo})})" + (", and the summed gain at the wrap reaches "
                                                            f"{peak(bo, go):.2f}: the audio twice under the crossfade" if seamless_ else ""),
          on.hard0 == 1 and ref.hard0 == 0 and len(wo) >= 2 and all(d["g0"] > 0.999 for d in wo)
          and (not seamless_ or peak(bo, go) > 1.5), [(d["at"], d["g0"]) for d in wo])
    check(f"  ...with them: each one fades in as an ordinary step does (first sound {max(d['g0'] for d in wn):.4f}; its "
          f"first 256 gains an ordinary step's, within 1e-6), and the summed gain stays at most 1 ({peak(bn, gn):.4f})",
          len(wn) >= 2 and ordinary and all(d["g0"] < 0.02 and np.allclose(d["fade"], ordinary[0]["fade"], rtol=0, atol=1e-6) for d in wn)
          and peak(bn, gn) <= 1.0 + 1e-6, [(d["at"], d["g0"]) for d in wn])
    sched = lambda r: [(m_["block"], m_["k"], m_["step"], m_["start"], m_["launch"]) for m_ in r.made]
    span = lambda s_: sorted((d["at"], d["end"], d["step"]) for d in s_.values())
    check(f"  ...the timing as before, sample for sample: every segment made in the same block, slot, step and start, "
          f"first read on the same sample and silent from the same sample on ({len(sn)} segments)",
          sched(on) == sched(off) and span(sn) == span(so), (span(sn)[:6], span(so)[:6]))
    lo = max(since, bn, br)
    n_ = min(len(gn) - (lo - bn), len(gr) - (lo - br))
    check(f"  ...and from the first wrap on ({n_} samples), the summed gain is the 0xBA1 = 0 run's bit for bit (stock's "
          "step-0 fade-in)", wn and n_ > 96000 and np.array_equal(gn[lo - bn:lo - bn + n_], gr[lo - br:lo - br + n_]),
          float(np.abs(gn[lo - bn:lo - bn + n_] - gr[lo - br:lo - br + n_]).max()) if wn and n_ > 0 else None)

# the launch: inside the audio (Slip) it fades in too; at the file's own start it stays hard, as stock has it, even
# where the wraps after it are seamless (Fit Auto at Slip 0) and get their fade-in
kw = dict(frames=96000, slip=-645, sync=5, blocks=900)
lon, loff = fa_segs(fa_run(**kw))[0], fa_segs(fa_run(off=True, **kw))[0]
la_on = [d for d in lon.values() if d["launch"]]
la_off = [d for d in loff.values() if d["launch"]]
check(f"step 0, the launch at Slip -645 (Attack 0): stock's hard start ({[d['g0'] for d in la_off]}) fades in from the "
      f"first sample with the marks ({[round(d['g0'], 4) for d in la_on]}), on the same sample",
      la_on and la_off and la_off[0]["g0"] > 0.999 and la_on[0]["g0"] < 0.02 and la_on[0]["at"] == la_off[0]["at"] == 288000
      and la_on[0]["end"] == la_off[0]["end"], (la_on, la_off))
kw = dict(frames=89760, beats=0, slip=0, sync=3, vals={P_FIT: 1}, blocks=1700)
fs = fa_segs(fa_run(**kw))[0]
fl_ = [d for d in fs.values() if d["launch"]]
fw = [d for d in fs.values() if d["step"] == 0 and not d["launch"]]
check(f"  ...Fit Auto at Slip 0 (a seamless wrap, step 0 on the file's frame 0): the launch still starts at full gain "
      f"({[d['g0'] for d in fl_]}), each wrap's step 0 fades in ({[round(d['g0'], 4) for d in fw]})",
      fl_ and fl_[0]["g0"] > 0.999 and len(fw) >= 2 and all(d["g0"] < 0.02 for d in fw), (fl_, fw))

# unchanged: an Attack (0xBA1 = 0), a pad the hooks leave alone, no bank 2
kw = dict(frames=89760, beats=0, slip=-645, sync=5, vals={P_FIT: 1}, blocks=1700)
ok, d = same(fa_run(attack=None, **kw), fa_run(attack=None, off=True, **kw))
check("step 0: with an Attack (0xBA1 = 0: stock fades every step 0 in itself) nothing is marked: Fit Auto, Slip -645, each "
      "read, prefetch, mixed sample and message identical with the marks cleared", ok, d)
for name, kw in (("Slip 0, the whole file, Fit Off (no latch)", dict(frames=96000, slip=0, sync=5, blocks=1700)),
                 ("Slip -645 without this build's bank 2", dict(frames=96000, slip=-645, sync=5, blocks=1700, bank2=False))):
    a = scenario(setup=attack0, **kw)
    b = scenario(setup=attack0, bypass=True, **{k: v for k, v in kw.items() if k != "bank2"})
    ok, d = same(a, b)
    hard = [m_ for m_ in a.made if m_["step"] == 0]
    check(f"step 0, Attack 0, {name}: identical to the hooks taken out (stock: each step 0 hard), every read, prefetch, mixed "
          f"sample and message ({len(hard)} step-0 segments)" + (f"; no cw_* entered ({len(a.b2_entered)})" if "bank 2" in name
                                                                    else ""),
          ok and len(hard) >= 2 and ("bank 2" not in name or not a.b2_entered), d)

# ---- a take loaded into a playing pad, with a Sync or Quant set while its slot is closed. The
# browser closes the slot (fw_src_len = SRC_BAD) and opens the new take a few blocks later; a Sync set in between
# re-grids the playing segments onto a step of the closed slot's 2^28-frame clip, and stock's recompute at the open
# re-grids nothing: no segment for millions of samples (the unit: valid 0010, the old region's latches). The poll sends
# the pad's own Sync again once the file is open: one re-grid from the open file, then the take's own lattice (a fresh
# launch of 96 003 frames under Beat Count Auto passes every 750 blocks: 758, 1508, 2258).
FP_SW, FP_CL, FP_LEN = 265, 4, 96003


def fp_load(inside, sends):
    hooked = []

    def pre(rr):
        if not hooked:
            hooked.append(1)
            rr.uc.hook_add(UC_HOOK_CODE, lambda uc, a, sz, ud: sends.append(rr.block), begin=0x08067ABA, end=0x08067ABA)
        if rr.block == FP_SW:
            rr.len = 0x10000000          # SRC_BAD: the slot closed
            rr.param(0x90, 0)
        if rr.block == FP_SW + 1:
            for pid, v in inside:
                rr.param(pid, v)
        if rr.block == FP_SW + FP_CL:
            rr.len = FP_LEN
        if rr.block == FP_SW + FP_CL + 1:
            for pid, v in ((0x8F, 0), (0x90, FP_LEN), (0x91, 0), (0x92, FP_LEN)):
                rr.param(pid, v)
    return pre


def fp_run(inside, load=True):
    sends = []
    r = scenario(frames=96000, beats=0, sync=5, cell=0x102, blocks=2600, slip=112, region=AUTO, points=(24000, 96000, 1),
                 pre=fp_load(inside, sends) if load else None)
    return [m_["block"] for m_ in r.made if m_["block"] > FP_SW + FP_CL + 1], [s for s in sends if s > FP_SW + 1]


fp_after, fp_sent = fp_run(((0x94, 0), (0x47, 3)))
check("a take under a closed slot: Sync Slice and Quant 1 bar set while the slot is closed: the pad's own Sync is sent once after the open "
      f"(blocks {fp_sent}) and the pad sounds again at once, then passes on the take's own lattice (fresh launch: 758, "
      "1508, 2258)", len(fp_sent) == 1 and FP_SW + FP_CL + 1 < fp_sent[0] <= FP_SW + FP_CL + 1 + 32 and
      len(fp_after) >= 4 and fp_after[0] == fp_sent[0] and fp_after[2:4] == [1508, 2258], f"made {fp_after[:8]}")
fp_plain, fp_plain_sent = fp_run(())
fp_none, _ = fp_run((), load=False)
fp_gap = max(b_ - a_ for a_, b_ in zip(fp_plain, fp_plain[1:]))
check("  ...a load with no Sync set inside it sends nothing: the pad plays on through it, a step every 1/16 as with no "
      f"load (longest gap {fp_gap} blocks)", not fp_plain_sent and fp_plain[:8] == fp_none[:8] and fp_gap <= 50 and
      fp_plain[-1] > 2500, f"sent {fp_plain_sent}, made {fp_plain[:8]} / {fp_none[:8]}")


print(f"{fails} failed")
sys.exit(1 if fails else 0)
