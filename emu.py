"""Unicorn harness for running the patched image's functions against fake objects."""
import os
import struct
import subprocess
import zlib

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn import arm_const
from unicorn.arm_const import UC_CPU_ARM_MAX
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP)

BASE = 0x08040000
# The bank 2 payload the suites run against: the one programmed on the unit this tree is developed on, when there is
# a record of it here, so that an image is always tested against what it will really meet. Where there is no such
# record (the public repository has none) it is the payload this build has just linked, which is what a card
# install puts there.
DEPLOYED_BANK2 = "card-backup/BANK2-3.3.z-payload.bin"   # on the test unit since 3.3.z (10-21)
if not os.path.exists(DEPLOYED_BANK2):
    DEPLOYED_BANK2 = "out/bank2.bin"
STACK, RET = 0x2407F000, 0x0807FFF0
TRACE = open(os.environ["EMU_TRACE"], "a") if os.environ.get("EMU_TRACE") else None
TRACE_SKIP = {0xE0000000, 0x52002000, 0x58024000, 0x50003000}   # SCB / DWT, FLASH, RCC / PWR, WWDG registers
TRACE_MASK = ((STACK - 0x4000, STACK), (0x2405FFD0, 0x2405FFF4), (0x38800FE8, 0x38800FF0))
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class _Stubs(dict):
    """address -> handler; each address gets its own code hook (one hook on every instruction is ~50x slower)."""

    def __init__(self, uc):
        super().__init__()
        self.uc, self.hooked = uc, set()

    def __setitem__(self, addr, fn):
        if addr not in self.hooked:
            self.hooked.add(addr)
            self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: self[a]() if a in self else None, begin=addr, end=addr)
        super().__setitem__(addr, fn)


class Emu:
    def __init__(self, image, elf):
        self.sym = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(
            ["arm-none-eabi-nm", elf], capture_output=True, text=True, check=True).stdout.splitlines()}
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.ctl_set_cpu_model(UC_CPU_ARM_MAX)          # needs FPv5 (vfma, vsel) like the Cortex-M7
        uc.mem_map(0x08000000, 0x200000)
        uc.mem_write(BASE, open(image, "rb").read())
        # Flash bank 2 (0x08100000) holds the relocated leaf DSP. The hardware keeps it across bank 1 installs;
        # here it has to be loaded alongside the image or any call into it runs off into 0x00 bytes.
        # It loads the payload that is ON THE TEST UNIT, not the one this build just linked. They used to differ and
        # nothing noticed: every suite ran Confetti and Prism against a freshly linked bank 2 whose calls into the
        # cave were right, while the unit ran the 3.2.l payload whose calls were stale - which crashed it on every
        # build from 3.2.m to 3.2.r. build.sh now refuses a build where the two differ; BANK2_NEW=1 is the
        # deliberate exception, for a build that goes with a reprogrammed bank 2.
        b2 = "out/bank2.bin" if os.environ.get("BANK2_NEW") == "1" else DEPLOYED_BANK2
        try:
            uc.mem_write(0x08100000, open(b2, "rb").read())
        except FileNotFoundError:
            pass
        uc.mem_map(0x24000000, 0x80000)
        uc.mem_map(0xE0000000, 0x100000)             # the core's own registers: SCB, NVIC, DWT, cache maintenance
        uc.mem_map(0x52002000, 0x1000)               # FLASH: b2_paired reads bank 2's ECC flags (0 = clean)
        uc.mem_write(RET, b"\x00\xbf\x00\xbf")
        # The load meter's state as the firmware has it by the time anything renders: cpu_wait sets it up at the audio
        # task's first wake, before the first block. b2_live() answers "not yet" without it, since b2chk lives there
        # (3.3.a), so a suite that ran Prism or an insert from a bare emulator would see them bypassed.
        self.meter_up()
        uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)   # FPU on
        uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.stubs, self.calls = _Stubs(uc), []
        self._primask_ops(image)

    def _primask_ops(self, image):
        """The A-profile core here has no PRIMASK: `mrs rd, primask`, `cpsid i` and `msr primask, rn` (cpu.c's
        b2_step, rc4) are invalid instructions to it. Each one in the image runs here against a stand-in register.
        Keyed by address, so a match inside data or mid-instruction never fires."""
        self.primask = 0
        regs = [getattr(arm_const, f"UC_ARM_REG_R{n}") for n in range(13)]
        img = open(image, "rb").read()
        for off in range(0, len(img) - 3, 2):
            a = BASE + off
            h0, h1 = struct.unpack_from("<HH", img, off)
            if h0 == 0xF3EF and h1 & 0xF0FF == 0x8010:                 # mrs rd, primask
                def op(a=a, rd=regs[(h1 >> 8) & 0xF]):
                    self.uc.reg_write(rd, self.primask)
                    self.uc.reg_write(UC_ARM_REG_PC, (a + 4) | 1)
            elif h0 & 0xFFF0 == 0xF380 and h1 == 0x8810:               # msr primask, rn
                def op(a=a, rn=regs[h0 & 0xF]):
                    self.primask = self.uc.reg_read(rn) & 1
                    self.uc.reg_write(UC_ARM_REG_PC, (a + 4) | 1)
            elif h0 == 0xB672:                                         # cpsid i
                def op(a=a):
                    self.primask = 1
                    self.uc.reg_write(UC_ARM_REG_PC, (a + 2) | 1)
            else:
                continue
            self.stubs[a] = op

    def meter_up(self):
        """cpu_wait at the audio task's first wake after a boot: the meter's state, with b2chk in it, starts clean.
        Call it again after anything that runs master_alloc - that is a boot, and cpu_boot wipes this."""
        self.uc.mem_write(0x2405FFD0, struct.pack("<I", 0x43505534) + bytes(32))

    def arg(self, n):
        return self.uc.reg_read(ARGS[n])

    def ret(self, value=None):
        if value is not None:
            self.uc.reg_write(UC_ARM_REG_R0, value)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def stub(self, addr, fn=None, value=None):
        """Replace the firmware function at addr; fn() may record into self.calls."""
        def run():
            if fn:
                fn()
            self.ret(value)
        self.stubs[addr] = run

    def call(self, target, *args, count=2_000_000):
        addr = self.sym[target] if isinstance(target, str) else target
        for reg, v in zip(ARGS, args):
            self.uc.reg_write(reg, v & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_SP, STACK)
        self.uc.reg_write(UC_ARM_REG_LR, RET | 1)
        self.calls.clear()
        self.uc.emu_start(addr | 1, RET, count=count)
        assert self.uc.reg_read(UC_ARM_REG_PC) == RET, f"did not return from {target}"
        if TRACE:
            self._trace(target, args)
        return list(self.calls)

    def _trace(self, target, args):
        """EMU_TRACE=file: after every call, one line with what was called and CRCs of the RAM it can see, per 64 KB.
        Two builds that should behave the same (3.3.y's bank reorganisation) are run through the same suite and the
        files compared: measure/trace_diff.py. Left out, as noise between two builds that do the same work: flash, the
        core's and the chip's registers, the stack below the caller's sp, the load meter's state (it holds the bank 2
        verdict, which a build asks for at different moments) and the delay's stack watermark (fault.c's SP_LOW)."""
        crcs = []
        for begin, end, _ in sorted(self.uc.mem_regions()):
            if begin >> 24 == 0x08 or begin in TRACE_SKIP:
                continue
            data = bytearray(self.uc.mem_read(begin, end - begin + 1))
            for lo, hi in TRACE_MASK:
                if begin <= lo and hi <= end + 1:
                    data[lo - begin:hi - begin] = bytes(hi - lo)
            for off in range(0, len(data), 0x10000):
                crcs.append(f"{begin + off:08x}:{zlib.crc32(data[off:off + 0x10000]):08x}")
        name = target if isinstance(target, str) else f"{target:08x}"
        TRACE.write(f"{name} {' '.join(f'{a & 0xFFFFFFFF:x}' for a in args)} | {' '.join(crcs)}\n")

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def r16(self, a):
        return struct.unpack("<H", self.uc.mem_read(a, 2))[0]

    def r32(self, a):
        return struct.unpack("<i", self.uc.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def cstr(self, a):
        return bytes(self.uc.mem_read(a, 32)).split(b"\0")[0].decode()
