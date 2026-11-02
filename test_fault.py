"""The instrument itself: the fault recorder, the watchdog early-wakeup recorder, the breadcrumb ring and the boot
latch. None of this had a suite before, which is how a record that overran the end of backup SRAM reached hardware
and turned a crash into a "spin" theory for three sessions.

Backup SRAM is 4 KB and is mapped here at exactly that size, so Unicorn refuses a write past it the way the bus
does. Nothing in this file needs the audio engine; it is all addresses and arithmetic.
"""
import struct
import subprocess
import sys

from unicorn import UcError

from emu import Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+live+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                      # the real backup SRAM: 4 KB, nothing above it
e.uc.mem_map(0x58024000, 0x1000)                      # RCC + PWR, for bkp_enable
e.uc.mem_map(0x50003000, 0x1000)                      # WWDG1
e.uc.mem_map(0x30000000, 0x1000)                      # a fake exception frame

BKP_END = 0x38801000
FAULT, WDG, BOOT, SP_LOW = 0x38800F78, 0x38800FB8, 0x38800FD8, 0x38800FE8
AUD, GUI, AUD_SAVED, GUI_SAVED, RING_IDX = 0x38800384, 0x38800394, 0x388003A4, 0x388003B4, 0x388003C4
RING_LEN = 6 - 2                                      # four slots per ring, one ring per task
RCC_RSR = 0x580244D0
SUP = 0x2400A584                                      # the watchdog supervisor's two stamps + its own counter
WWDG_CR, WWDG_CFR, WWDG_SR = 0x50003000, 0x50003004, 0x50003008
NVIC_ISER0, NVIC_IPR0 = 0xE000E100, 0xE000E400
FRAME = 0x30000100

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def words(addr, n):
    return struct.unpack(f"<{n}I", e.uc.mem_read(addr, 4 * n))


def run(fn, *args, count=20_000):
    """Call a recorder. It ends in a deliberate spin (fault_record) or returns; a MEMORY error is the bug we hunt."""
    try:
        e.call(fn, *args, count=count)
        return None
    except UcError as exc:
        return exc                                     # wrote somewhere it must not: this is a real failure
    except AssertionError:
        return None                                    # did not return: fault_record's reset spin, as designed


# --- the layout stays inside the 4 KB, with room for every record
check(f"the fault record's 16 words end inside backup SRAM ({FAULT:#x}..{FAULT + 64 - 1:#x})", FAULT + 64 <= BKP_END)
check("the records do not overlap", FAULT + 64 <= WDG and WDG + 32 <= BOOT and BOOT + 16 <= SP_LOW)
check(f"the SP watermark ends at the top ({SP_LOW + 8:#x})", SP_LOW + 8 <= BKP_END)
check("the trails sit in the other hole, clear of od.c below and comp.c above",
      AUD >= 0x38800384 and RING_IDX + 4 <= 0x38800400)

# --- the fault recorder, with a frame it CAN read
e.uc.mem_write(FRAME, struct.pack("<8I", 0xA0, 0xA1, 0xA2, 0xA3, 0x0C, 0x0805F615, 0x08054F3A, 0x61000000))
e.uc.mem_write(0xE000ED28, struct.pack("<2I", 0x00008200, 0x40000000))                  # CFSR, HFSR
e.uc.mem_write(0xE000ED34, struct.pack("<2I", 0xDEAD0000, 0xC0DEDEAD))                  # MMFAR, BFAR (ED30 is DFSR)
e.w32(SP_LOW, 0x2403FF00)
err = run("fault_record", FRAME, 0xFFFFFFED)
check("fault_record writes only inside the 4 KB backup SRAM", err is None, str(err))
rec = words(FAULT, 16)
check("the magic is written", rec[0] == 0x31544C46, f"{rec[0]:#010x}")
check(f"the faulting PC is recorded ({rec[1]:#010x})", rec[1] == 0x08054F3A)
check("LR and xPSR are recorded", rec[2] == 0x0805F615 and rec[3] == 0x61000000, [hex(x) for x in rec[2:4]])
check("CFSR, HFSR, MMFAR and BFAR are recorded", rec[4:8] == (0x00008200, 0x40000000, 0xDEAD0000, 0xC0DEDEAD),
      [hex(x) for x in rec[4:8]])
check("EXC_RETURN, the frame pointer and r0-r3 are recorded",
      rec[8] == 0xFFFFFFED and rec[9] == FRAME and rec[11:15] == (0xA0, 0xA1, 0xA2, 0xA3),
      [hex(x) for x in (rec[8], rec[9], *rec[11:15])])
check("the frame was marked readable", rec[10] == 1)
check("the stack watermark is carried into the record", rec[15] == 0x2403FF00, hex(rec[15]))
check("it asked for the reset (AIRCR: SYSRESETREQ with the key)", words(0xE000ED0C, 1)[0] == (0x5FA << 16) | 4,
      hex(words(0xE000ED0C, 1)[0]))

# --- THE CACHE. On hardware backup SRAM is write-back cached, so a record followed at once by a reset never
# reaches the SRAM: 3.2.o, 3.2.q and 3.2.r all lost every record that way, and this suite passed each time because
# an emulator has no cache. What CAN be checked here is the order: every line of the record must be cleaned out of
# the cache (a write of its address to DCCMVAC) BEFORE the reset is requested.
from unicorn import UC_HOOK_MEM_WRITE
DCCMVAC, AIRCR_REG = 0xE000EF68, 0xE000ED0C
order = []
hk = e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, addr, size, value, _: order.append((addr, value & 0xFFFFFFFF))
                   if addr in (DCCMVAC, AIRCR_REG) else None, begin=0xE000ED00, end=0xE000EFFF)
e.uc.mem_write(FAULT, bytes(64))
run("fault_record", FRAME, 0xFFFFFFED)
e.uc.hook_del(hk)
reset_at = next((i for i, (a, _) in enumerate(order) if a == AIRCR_REG), None)
cleaned = {v & ~31 for a, v in order[:reset_at] if a == DCCMVAC} if reset_at is not None else set()
need = {a & ~31 for a in range(FAULT, FAULT + 64, 4)} | {a & ~31 for a in range(AUD, RING_IDX + 4, 4)}
check(f"the record's cache lines are cleaned to the SRAM before the reset is asked for ({len(cleaned)} lines)",
      reset_at is not None and need <= cleaned, f"missing {[hex(a) for a in sorted(need - cleaned)]}")
check("...and nothing is cleaned after it, when it would be too late",
      reset_at is not None and not [1 for a, _ in order[reset_at + 1:] if a == DCCMVAC])
dis = subprocess.run(["arm-none-eabi-objdump", "-d", "--disassemble=bkp_flush", "out/cave.elf"], capture_output=True, text=True).stdout
check("a DSB follows the cleaning (in bkp_flush), so the writes have completed and are not just queued", "dsb" in dis)

# --- THE CASE 3.2.q COULD NOT SURVIVE: a stacking fault, where the frame pointer is garbage.
# The hardware could not push the frame, so dereferencing it faults again and locks the CPU up - no record at all,
# which is what the test unit actually produced. The record must still name the cause.
for label, bad_sp in (("unmapped", 0x10000000), ("misaligned", 0x24010004), ("just off the end of SDRAM", 0xC3FFFFF8)):
    e.uc.mem_write(FAULT, bytes(64))
    e.uc.mem_write(0xE000ED28, struct.pack("<2I", 0x00001000, 0x40000000))               # CFSR: STKERR
    err = run("fault_record", bad_sp, 0xFFFFFFED)
    rec = words(FAULT, 16)
    check(f"a frame pointer that is {label} does not take the recorder down with it", err is None, str(err))
    check(f"...and the record still lands: magic, CFSR = STKERR, SP {bad_sp:#010x}",
          rec[0] == 0x31544C46 and rec[4] == 0x00001000 and rec[9] == bad_sp, [hex(x) for x in (rec[0], rec[4], rec[9])])
    check("...marked as an unreadable frame, with PC left blank rather than invented", rec[10] == 0 and rec[1] == 0,
          [hex(rec[10]), hex(rec[1])])

# --- the watchdog early-wakeup recorder: the PC of whatever was running, and which task stopped checking in
e.uc.mem_write(SUP, struct.pack("<3I", 50_000, 61_234, 61_240))       # stamp A is 11,240 stale; B is 6
e.uc.mem_write(FRAME, struct.pack("<8I", 1, 2, 3, 4, 5, 0x080A5071, 0x08098E72, 0))   # r0-r3, r12, LR, PC, xPSR
e.uc.mem_write(WWDG_CR, struct.pack("<3I", 0x3F, 0x387F, 1))
err = run("wdg_record", FRAME, 0xFFFFFFFD)
check("wdg_record writes only inside the 4 KB backup SRAM", err is None, str(err))
rec = words(WDG, 8)
check("the magic is written", rec[0] == 0x31474457, f"{rec[0]:#010x}")
check(f"the spinning PC is recorded ({rec[1]:#010x})", rec[1] == 0x08098E72)
check("xPSR says which context it was (0 = thread mode)", rec[3] == 0)
check(f"stamp A's age is recorded ({rec[4]:,}), past the supervisor's 3,749 limit", rec[4] == 11_240 and rec[4] > 3749)
check(f"stamp B's age is recorded ({rec[5]}), inside the limit - so A is the task that stopped", rec[5] == 6)
check("the watchdog's own CR and SR are recorded", rec[7] == 0x3F | (1 << 16), f"{rec[7]:#010x}")
check("EWIF is cleared, so the handler does not re-enter for the last tick", words(WWDG_SR, 1)[0] == 0)
check("it did NOT refresh the counter, so the reset still happens on schedule", words(WWDG_CR, 1)[0] == 0x3F)

# --- two rings, one per task: a burst from the GUI must not flush the audio task's trail
e.uc.mem_write(AUD, bytes(RING_LEN * 4))
e.uc.mem_write(GUI, bytes(RING_LEN * 4))
e.w32(RING_IDX, 0)
for v in (0x0101, 0x0C03, 0x0603, 0x0603, 0x0603):       # the audio task, with a repeat as a running block gives
    e.call("crumb_drop", v, 0)
audio = words(AUD, RING_LEN)
check(f"audio repeats are dropped, so its ring holds distinct steps {[hex(x) for x in audio]}",
      sorted(x for x in audio if x) == [0x0101, 0x0603, 0x0C03], [hex(x) for x in audio])
for v in (0x1200, 0x1300, 0x1404, 0x1300, 0x1404, 0x1F97):   # the GUI burst that flushed everything in 3.2.q
    e.call("crumb_drop", v, 1)
check("the GUI burst did NOT disturb the audio ring", words(AUD, RING_LEN) == audio,
      [hex(x) for x in words(AUD, RING_LEN)])
check("the GUI ring took the burst and wrapped", (e.r32(RING_IDX) >> 8) & 0xFF < RING_LEN, hex(e.r32(RING_IDX)))
check("each ring keeps its own index", (e.r32(RING_IDX) & 0xFF) < RING_LEN, hex(e.r32(RING_IDX)))

# --- the audio task's stack watermark, and the re-arm stock's HAL undoes
e.w32(SP_LOW, 0)
e.w32(SP_LOW + 4, 0)
e.w32(WWDG_CFR, 0x387F)                                 # as HAL_WWDG_Init leaves it: EWI clear
e.call("audio_watch", 0x2403FF00)
e.call("audio_watch", 0x2403FE80)
e.call("audio_watch", 0x2403FFF0)
check(f"the watermark keeps the LOWEST stack the delay ever ran at ({e.r32(SP_LOW):#010x})", e.r32(SP_LOW) == 0x2403FE80)
check("and the most recent one beside it", e.r32(SP_LOW + 4) == 0x2403FFF0, hex(e.r32(SP_LOW + 4)))
check("it re-arms the early wakeup that HAL_WWDG_Init clears after master_alloc runs",
      words(WWDG_CFR, 1)[0] == 0x387F | (1 << 9), hex(words(WWDG_CFR, 1)[0]))

# --- the boot latch: the trails, and the reset cause stock is about to throw away
e.uc.mem_write(AUD, struct.pack("<4I", 0x101, 0xC03, 0x603, 0))
e.uc.mem_write(GUI, struct.pack("<4I", 0x1404, 0x1F97, 0, 0))
e.uc.mem_write(AUD_SAVED, bytes(RING_LEN * 4))
e.uc.mem_write(GUI_SAVED, bytes(RING_LEN * 4))
e.w32(RING_IDX, 0x0102)
e.w32(BOOT, 0)
e.w32(BOOT + 8, 7)
e.w32(RCC_RSR, 0x14000000)                              # WWDG1RSTF | D1RSTF, as a watchdog reset leaves it
e.w32(WWDG_CFR, 0x387F)
e.w32(NVIC_ISER0, 0)
e.uc.mem_write(NVIC_IPR0, b"\xFF")
live_a, live_g = words(AUD, RING_LEN), words(GUI, RING_LEN)
e.call("instrument_boot")
check("the audio trail from before the reset is saved", words(AUD_SAVED, RING_LEN) == live_a,
      [hex(x) for x in words(AUD_SAVED, RING_LEN)])
check("the GUI trail from before the reset is saved", words(GUI_SAVED, RING_LEN) == live_g,
      [hex(x) for x in words(GUI_SAVED, RING_LEN)])
check("both live rings are cleared, so the reboot's own crumbs cannot be mistaken for them",
      words(AUD, RING_LEN) == (0,) * RING_LEN and words(GUI, RING_LEN) == (0,) * RING_LEN)
boot = words(BOOT, 4)
check("the boot record is stamped", boot[0] == 0x31544F42, hex(boot[0]))
check(f"THE RESET CAUSE IS CAPTURED before stock clears it ({boot[1]:#010x} = WWDG1RSTF set)",
      boot[1] == 0x14000000 and boot[1] & (1 << 26), hex(boot[1]))
check("the boot count goes up", boot[2] == 8, boot[2])
check("the ring indexes as they stood are kept, so the saved trails can be put in order",
      boot[3] >> 16 == 0x0102, hex(boot[3]))
check("the stack watermark restarts for the new boot", e.r32(SP_LOW) == 0)
check("the early wakeup is armed (CFR bit 9)", words(WWDG_CFR, 1)[0] == 0x387F | (1 << 9),
      hex(words(WWDG_CFR, 1)[0]))
check("IRQ 0 is enabled at the highest priority, so it preempts whatever is spinning",
      words(NVIC_ISER0, 1)[0] & 1 and e.r8(NVIC_IPR0) == 0, (hex(words(NVIC_ISER0, 1)[0]), e.r8(NVIC_IPR0)))
check("it did not touch the watchdog counter", words(WWDG_CR, 1)[0] == 0x3F)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
