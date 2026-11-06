"""USB MIDI + audio device on the power jack (src/usbdev.c) under Unicorn, against a small model of the OTG controller.

The model is MY reading of the controller's register behaviour (receive status queue, endpoint 0 FIFO, write-one-to-
clear interrupt bits, the reset bit that clears itself), and the "host" below plays a computer's enumeration.
NOT checked: that the power jack's data lines reach PB14 / PB15 at all, that the real controller behaves as this model
does, the 48 MHz clock, timing against a real host, anything electrical. Only the unit can show those.
"""
import struct
import sys

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58020000, 0x5000)                 # GPIO, RCC, PWR
e.uc.mem_map(0x40040000, 0x4000)
CYC = 0xE0001004
SDRAM, RING_AT = 0xC0100000, 0xC0100000 + 0x56800 + 0x1000
e.uc.mem_map(SDRAM, 0x60000)
e.w32(0x38800F70, SDRAM)                         # master.c's block, as its boot hook leaves it
e.w32(0x38800F74, SDRAM ^ 0x5052534D)
USB, RCC, GPIOB, STATE = 0x40040000, 0x58024400, 0x58020400, 0x38800680
GRSTCTL, GINTSTS, GRXSTSP, DCFG, DCTL = 0x10, 0x14, 0x20, 0x800, 0x804
DIEPCTL0, DIEPTSIZ0, DOEPCTL0, DOEPINT0, DOEPTSIZ0, FIFO = 0x900, 0x910, 0xB00, 0xB08, 0xB10, 0x1000
DIEPCTL1, DIEPTSIZ1, DOEPCTL1, FIFO1 = 0x920, 0x930, 0xB20, 0x2000
GAHBCFG, GINTMSK, DSTS, DIEPCTL2, DIEPINT2, DIEPTSIZ2, FIFO2 = 0x08, 0x18, 0x808, 0x940, 0x948, 0x950, 0x3000
MGR = 0x24002E88                                 # stock's MIDI manager
IN_Q, OUT_Q = MGR + 0x4660, MGR + 0x4B68         # messages from USB, messages to USB: 256 x 5 bytes + two counters
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


class Core:
    def __init__(self):
        self.reg = {GRSTCTL: 0x80000000, DCTL: 2}
        self.rx, self.words, self.tx, self.sent = [], [], None, []
        self.midi = []                               # words written to endpoint 1's FIFO
        self.audio, self.log = [], []                # words written to endpoint 2's FIFO; (register, value) writes of note
        self.reset_reads = 0
        self.stalled = False

    def get(self, off):
        return self.reg.get(off, 0)

    def read(self, off):
        if off == GRSTCTL and self.reg[GRSTCTL] & 1:
            self.reset_reads -= 1
            if self.reset_reads <= 0:
                self.reg[GRSTCTL] &= ~1
        if off == GINTSTS:
            v = self.get(GINTSTS) & ~0x40010
            return v | (0x10 if self.rx else 0) | (0x40000 if self.get(DIEPINT2) & 1 else 0)
        if off == GRXSTSP:
            if not self.rx:
                return 0
            kind, data = self.rx.pop(0)
            ep = 0
            if isinstance(kind, tuple):
                kind, ep = kind
            if kind == 3 and ep == 1:                # the packet is in: endpoint 1 OUT is idle again
                self.reg[DOEPCTL1] = self.get(DOEPCTL1) & ~(1 << 31)
            self.words = [struct.unpack_from("<I", data.ljust((len(data) + 3) // 4 * 4, b"\0"), i)[0]
                          for i in range(0, len(data), 4)]
            if kind == 6:                         # the core drops an endpoint 0 stall when a setup arrives
                self.reg[DIEPCTL0] = self.get(DIEPCTL0) & ~(1 << 21)
                self.reg[DOEPCTL0] = self.get(DOEPCTL0) & ~(1 << 21)
            if kind == 4:
                self.reg[DOEPINT0] = self.get(DOEPINT0) | 8
            return kind << 17 | len(data) << 4 | ep
        if off == FIFO:
            return self.words.pop(0) if self.words else 0xDEADBEEF
        return self.get(off)

    def write(self, off, v):
        if off in (GINTSTS, DOEPINT0, 0x908, 0x928, 0xB28, DIEPINT2):
            self.reg[off] = self.get(off) & ~v
        elif off == GRSTCTL:
            self.log.append((GRSTCTL, v))
            if v & 1:
                self.reset_reads = 3
                self.reg[GRSTCTL] = 0x80000001
        elif off == FIFO:
            if self.tx is not None:
                self.tx[1] += struct.pack("<I", v)
                if len(self.tx[1]) >= self.tx[0]:
                    self.sent.append(bytes(self.tx[1][:self.tx[0]]))
                    self.tx = None
                    self.reg[0x908] = self.get(0x908) | 1    # transfer complete
        elif off == FIFO1:
            self.midi.append(v)
        elif off == FIFO2:
            self.audio.append(v)
        elif off in (DIEPCTL1, DOEPCTL1, DIEPCTL2):
            keep = self.get(off) & (1 << 31)             # enabled stays set until the host moves the packet
            if off == DIEPCTL2:
                self.log.append((DIEPCTL2, v))
            if v & (1 << 30):                            # disable: the core drops the transfer
                keep, v = 0, v & ~(1 << 31)
                if off == DIEPCTL2:
                    self.reg[DIEPINT2] = self.get(DIEPINT2) | 2
            self.reg[off] = (v & ~((1 << 26) | (1 << 27) | (1 << 28) | (1 << 29) | (1 << 30))) | keep
        elif off == DIEPCTL0:
            if v & (1 << 21):
                self.stalled = True
            if v & (1 << 31) and v & (1 << 26):
                n = self.get(DIEPTSIZ0) & 0x7F
                if n == 0:
                    self.sent.append(b"")
                    self.reg[0x908] = self.get(0x908) | 1
                else:
                    self.tx = [n, bytearray()]
            self.reg[off] = v & ~((1 << 31) | (1 << 26))
        else:
            self.reg[off] = v


core = Core()
e.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, _: uc.mem_write(a, struct.pack("<I", core.read(a - USB) & 0xFFFFFFFF)),
              begin=USB, end=USB + 0x3FFF)
e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, _: core.write(a - USB, v & 0xFFFFFFFF), begin=USB, end=USB + 0x3FFF)


def interrupt():
    """The controller's interrupt line, as the core raises it: unmasked sources only, and only when switched on."""
    pending = core.read(GINTSTS) & core.get(0x18)
    if pending and core.get(0x08) & 1 and e.r32(0xE000E108) & (1 << 13):
        e.call("usbaud_isr")
        return True
    return False


def poll(n=1):
    for _ in range(n):
        for _ in range(4):
            if not interrupt():
                break
        e.call("usbdev_poll")


def control(setup):
    """One control request as the host sends it; returns the data packet (b'' = empty status) or 'STALL'."""
    core.sent.clear()
    core.stalled = False
    core.rx += [(6, setup), (4, b"")]
    poll(2)
    if core.stalled:
        return "STALL"
    n = 0
    while len(core.sent) > n:                    # a long descriptor: a packet more per block
        n = len(core.sent)
        poll()
    core.chunks = [len(x) for x in core.sent]
    return b"".join(core.sent) if core.sent else None


def get_desc(kind, index, length):
    return control(struct.pack("<BBBBHH", 0x80, 6, index, kind, 0, length))


# --- boot: nothing until stock has its own USB running, then ~2 s, then the bring-up
e.uc.mem_write(STATE, b"\xa5" * 12)              # backup SRAM as an earlier boot left it
poll(50)
check("stock USB not started yet: the second controller's clock stays off", not e.r32(RCC + 0xD8) & (1 << 25))
e.w32(RCC + 0xD8, 1 << 27)
e.w32(RCC + 0x54, 1 << 20)
e.w32(RCC + 0x100, 0xFFFFFFFF)
e.w32(GPIOB + 0x00, 0xFFFFFFFF)                  # every pin analog, as after reset
poll(399)
check("...and for 399 more blocks after it has", not e.r32(RCC + 0xD8) & (1 << 25))
poll(1)
check("block 400: controller clock on, external-transceiver sleep clock off, host controller's clock untouched",
      e.r32(RCC + 0xD8) & 0xFFFFFFFF == (1 << 27) | (1 << 25) and not e.r32(RCC + 0x100) & (1 << 26))
check("PB14 / PB15 = alternate function 12, no other pin's mode touched",
      e.r32(GPIOB + 0x24) & 0xFFFFFFFF == 0xCC000000 and e.r32(GPIOB + 0x00) & 0xFFFFFFFF == 0xAFFFFFFF,
      f"{e.r32(GPIOB + 0x24) & 0xFFFFFFFF:#x} {e.r32(GPIOB) & 0xFFFFFFFF:#x}")
check("built-in transceiver selected, core reset asked for, D+ pull-up still off",
      core.get(0x0C) & (1 << 6) and core.get(GRSTCTL) & 1 and core.get(DCTL) & 2)
poll(12)
check("still disconnected while the mode change settles", core.get(DCTL) & 2)
poll(6)
check("connected: device mode forced, transceiver on, VBUS sensing overridden, full speed, pull-up on",
      core.get(0x0C) & (1 << 30) and core.get(0x38) & (1 << 16) and not core.get(0x38) & (1 << 21)
      and core.get(0x00) & 0xC0 == 0xC0 and core.get(DCFG) & 3 == 3 and not core.get(DCTL) & 2)
check("only the receive interrupt is unmasked, on vector 77 at stock's USB priority", core.get(0x18) == 0x10 and core.get(0x08) & 1 == 1 and e.r32(0xE000E108) & 0xFFFFFFFF == 1 << 13 and e.r8(0xE000E44D) == 0x70)

# --- a host enumerates
core.reg[GINTSTS] = (1 << 12) | (1 << 13)
poll()
check("bus reset + speed known: both acknowledged, address 0, endpoint 0 at 64 bytes",
      core.get(GINTSTS) == 0 and core.get(DCFG) & 0x7F0 == 0 and core.get(DIEPCTL0) & 3 == 0)
d = get_desc(1, 0, 8)
check("first 8 bytes of the device descriptor (what a host asks first)", d == bytes.fromhex("1201000200000040"), d)
d = get_desc(1, 0, 18)
check("device descriptor: 18 bytes, USB 2.0, class per interface, 1209:0003", d and len(d) == 18 and d[4] == 0 and d[8:12] == bytes.fromhex("09120300"), d)
check("...and endpoint 0 OUT armed for the host's empty status packet", core.get(DOEPCTL0) & (1 << 31))
r = control(struct.pack("<BBHHH", 0x00, 5, 9, 0, 0))
check("SET_ADDRESS 9: address latched, empty status sent", r == b"" and (core.get(DCFG) >> 4) & 0x7F == 9, r)
d = get_desc(2, 0, 9)
check("configuration descriptor header (9 bytes asked): total length 175, three interfaces", d and len(d) == 9 and d[2] == 175 and d[4] == 3, d)
d = get_desc(2, 0, 255)
check("whole configuration: 175 bytes over three packets (64 + 64 + 47), one per block", d and len(d) == 175 and core.chunks == [64, 64, 47], (d and len(d), core.chunks))
d2 = get_desc(2, 0, 100)
check("asked for 100 bytes of it: exactly the first 100", d2 == d[:100] and core.chunks == [64, 36], core.chunks)


def walk(cfg):
    out, i = [], 0
    while i < len(cfg) and cfg[i]:
        out.append(cfg[i:i + cfg[i]])
        i += cfg[i]
    return out, i


parts, used = walk(d)
ms = [x for x in parts if x[1] == 4 and x[5] == 1 and x[6] == 3]
eps = [x for x in parts if x[1] == 5]
head = [x for x in parts[parts.index(ms[0]):] if x[1] == 0x24 and x[2] == 1 and len(x) == 7] if ms else []
after = parts[parts.index(head[0]):] if head else []
check("it parses to the end: audio control, audio streaming (2 alts), MIDI streaming; endpoints 0x82 iso, 0x01 / 0x81 bulk",
      used == 175 and len(ms) == 1 and ms[0][2] == 2 and ms[0][4] == 2
      and [(x[2], x[3], x[4] | x[5] << 8) for x in eps] == [(0x82, 5, 882), (1, 2, 64), (0x81, 2, 64)], parts)
ac = [x for x in parts if x[1] == 0x24 and x[2] == 1 and len(x) == 10][0]
ac_i = parts.index(ac)
check("audio control header: its length field covers itself + both terminals (31), and it lists interfaces 1 and 2",
      ac[5] == sum(len(x) for x in parts[ac_i:ac_i + 3]) == 31 and list(ac[7:10]) == [2, 1, 2], ac)
it, ot = parts[ac_i + 1], parts[ac_i + 2]
fmt = [x for x in parts if x[1] == 0x24 and x[2] == 2 and len(x) == 11][0]
gen = parts[parts.index(fmt) - 1]
alts = [(x[2], x[3], x[4]) for x in parts if x[1] == 4 and x[6] == 2]
check("6-channel input terminal 1 -> USB streaming terminal 2; the stream is fed from terminal 2",
      it[3] == 1 and it[7] == 6 and ot[3] == 2 and ot[4:6] == bytes([1, 1]) and ot[7] == 1 and gen[3] == 2, (it, ot, gen))
check("format: PCM, 6 channels, 3-byte samples, 24 bits, 48000 Hz only",
      gen[5:7] == bytes([1, 0]) and list(fmt[4:8]) == [6, 3, 24, 1] and int.from_bytes(fmt[8:11], "little") == 48000, fmt)
check("audio streaming interface 1: alt 0 with no endpoint, alt 1 with one; 882 bytes = 49 frames x 18",
      alts == [(1, 0, 0), (1, 1, 1)] and 49 * 6 * 3 == 882, alts)
check("the MIDI streaming header's own length field matches what follows it (65)",
      head and head[0][5] == sum(len(x) for x in after) == 65, head)
check("each endpoint names an embedded jack that exists (1 = in, 3 = out)",
      [x[4] for x in parts if x[1] == 0x25 and len(x) == 5] == [1, 3] and [x[4] for x in after if x[1] == 0x24 and x[3] == 1 and x[2] in (2, 3)] == [1, 3], parts)
d = get_desc(3, 0, 255)
check("string 0: language 0x0409", d == bytes.fromhex("04030904"), d)
d = get_desc(3, 2, 255)
check("product string reads 'Blackbox'", d and d[0] == len(d) and d[1] == 3 and d[2:].decode("utf-16-le") == "Blackbox", d)
d = get_desc(3, 1, 255)
check("maker string reads 'blackbox-mod'", d and d[2:].decode("utf-16-le") == "blackbox-mod", d)
check("device qualifier (high-speed question): refused with a stall", get_desc(6, 0, 10) == "STALL")
check("an unknown string index: stall", get_desc(3, 7, 255) == "STALL")
r = control(struct.pack("<BBHHH", 0x00, 9, 1, 0, 0))
check("SET_CONFIGURATION 1: empty status", r == b"", r)
r = control(struct.pack("<BBHHH", 0x80, 8, 0, 0, 1))
check("GET_CONFIGURATION answers 1", r == b"\x01", r)
r = control(struct.pack("<BBHHH", 0x80, 0, 0, 0, 2))
check("GET_STATUS answers two zero bytes", r == b"\0\0", r)
core.rx += [(2, b""), (3, b"")]
poll()
check("the host's empty status packet is drained without a reply", not core.rx)
check("configured: both bulk endpoints active at 64 bytes, IN on its own FIFO, OUT armed for one packet",
      core.get(DIEPCTL1) & 0x03CC87FF == 0x00488040 and core.get(DOEPCTL1) & 0x000C87FF == 0x00088040
      and core.get(DOEPCTL1) >> 31 and core.get(0xB30) == (1 << 19) | 64, f"{core.get(DIEPCTL1):#x} {core.get(DOEPCTL1):#x}")
r = control(struct.pack("<BBHHH", 0x01, 11, 0, 2, 0))
check("SET_INTERFACE on the MIDI interface and clearing an endpoint halt are accepted; the audio stream stays closed",
      r == b"" and control(struct.pack("<BBHHH", 0x02, 1, 0, 0x81, 0)) == b"" and e.r8(STATE + 14) == 0 and core.get(GINTMSK) == 0x10, r)

# --- debug peek / poke: in test builds, and NOT in a public one
RELEASE = e.uc.mem_read(e.sym["release_build"], 1)[0]
e.w32(0x24070800, 0x11223344)
e.w32(0x24070804, 0xAABBCCDD)
r = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x0800, 0x2407, 8))
if RELEASE:
    check("PUBLIC BUILD: a peek request is refused (stalled), and no memory comes back", r == "STALL", r)
    r1 = control(struct.pack("<BBHHH", 0x40, 0x51, 0x0804, 0x2407, 0))
    r2 = control(struct.pack("<BBHHH", 0x40, 0x52, 0x5678, 0x1234, 0))
    check("PUBLIC BUILD: a poke is refused too, and the word it aimed at is untouched",
          r1 == "STALL" and r2 == "STALL" and e.r32(0x24070804) & 0xFFFFFFFF == 0xAABBCCDD, (r1, r2, hex(e.r32(0x24070804))))
    r = control(struct.pack("<BBHHH", 0x80, 6, 0x0100, 0, 18))
    check("...and the device still answers an ordinary request afterwards", r != "STALL" and len(r) == 18, r)
else:
    check("debug peek: 8 bytes at 0x24070800 come back as stored", r == bytes.fromhex("44332211ddccbbaa"), r)
    control(struct.pack("<BBHHH", 0x40, 0x51, 0x0804, 0x2407, 0))
    r = control(struct.pack("<BBHHH", 0x40, 0x52, 0x5678, 0x1234, 0))
    check("debug poke: address then word, written once", r == b"" and e.r32(0x24070804) == 0x12345678 and e.r32(0x24070800) == 0x11223344, hex(e.r32(0x24070804)))
    # bounded to whole memory regions. Backup SRAM is mapped here to exactly 0x38800fff: a read past it faults the
    # emulator itself, as it bus-faults the chip
    e.uc.mem_write(0x38800FD8, bytes(range(40)))
    r = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x0FD8, 0x3880, 64))
    check("debug peek, bounded: a 64-byte peek at 0x38800fd8 comes back as the 40 bytes up to backup SRAM's end, nothing read past it",
          r == bytes(range(40)), r)
    e.uc.mem_map(0x50001000, 0x1000)
    e.w32(0x500010AC, 0xC1234560)
    e.w32(0x5000112C, 0xC2345670)
    r1 = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x10AC, 0x5000, 4))
    r2 = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x112C, 0x5000, 4))
    r3 = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x1140, 0x5000, 16))
    r4 = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x1148, 0x5000, 4))
    check("  ...the LTDC's registers read (layer 1 and layer 2 CFBAR), a peek there stops at the block's end (8 of 16 "
          "bytes from 0x50001140), and one past it stalls", r1 == struct.pack("<I", 0xC1234560) and
          r2 == struct.pack("<I", 0xC2345670) and r3 == bytes(8) and r4 == "STALL", (r1, r2, r3, r4))
    stall = [control(struct.pack("<BBHHH", 0xC0, 0x50, lo_, hi_, 4)) for lo_, hi_ in ((0x0000, 0x4004), (0x0801, 0x2407), (0x0000, 0x6000))]
    check("  ...a peripheral not listed (the USB core), an unaligned word and an address in no memory stall",
          stall == ["STALL"] * 3, stall)
    before = (e.r32(0x08100000), e.r32(0x500010AC))
    pk = []
    for lo_, hi_ in ((0x0000, 0x0810), (0x10AC, 0x5000), (0x0802, 0x2407), (0x0010, 0xC010)):
        control(struct.pack("<BBHHH", 0x40, 0x51, lo_, hi_, 0))
        pk.append(control(struct.pack("<BBHHH", 0x40, 0x52, 0xBEEF, 0xDEAD, 0)))
    check("  ...a poke to flash, to a register or unaligned stalls and writes nothing; to SDRAM it writes",
          pk == ["STALL", "STALL", "STALL", b""] and (e.r32(0x08100000), e.r32(0x500010AC)) == before
          and e.r32(0xC0100010) & 0xFFFFFFFF == 0xDEADBEEF, (pk, before, hex(e.r32(0xC0100010))))
    # a reply the host gave up on still queued on endpoint 0 (enabled, its packet in the FIFO): the next setup
    # disables the endpoint and flushes TX FIFO 0 before it answers, so the answer is its own
    core.reg[DIEPCTL0] = core.get(DIEPCTL0) | (1 << 31)
    core.log.clear()
    r = control(struct.pack("<BBHHH", 0xC0, 0x50, 0x0800, 0x2407, 8))
    check("debug build: with a stale reply queued on endpoint 0, a new peek disables it and flushes TX FIFO 0 (GRSTCTL 0x20), "
          "then answers with its own bytes", (GRSTCTL, 0x20) in core.log and not core.get(DIEPCTL0) >> 31
          and r == bytes.fromhex("44332211") + struct.pack("<I", 0x12345678), (core.log[:4], r))

# --- MIDI from the computer: through stock's own USB event parser (real firmware code) into its "from USB" queue


def queued():
    n = e.r32(MGR + 0x4B64) & 0xFFFFFFFF
    return [bytes(e.uc.mem_read(IN_Q + i * 5, 5)) for i in range(n)]


def from_host(packet):
    core.rx += [((2, 1), packet), ((3, 1), b"")]
    poll()


from_host(bytes.fromhex("09903c64" "0b b0 4a 7f".replace(" ", "") + "0ff80000" + "08803c00"))
q = queued()
check("note on, CC, clock, note off from the computer land in stock's from-USB queue, in order, with their lengths",
      [m[:m[4]].hex() for m in q] == ["903c64", "b04a7f", "f8", "803c00"], [m.hex() for m in q])
check("...and the endpoint is armed again for the next packet", core.get(DOEPCTL1) >> 31 and not core.rx)
from_host(bytes.fromhex("0ccc0500" "04f07e00" "0ee00040" "03f20102" "0dd04000"))
q = queued()[4:]
check("program change, pitch bend, channel pressure pass; SysEx and song position are dropped, not allowed to stop the rest",
      [m[:m[4]].hex() for m in q] == ["cc05", "e00040", "d040"], [m.hex() for m in q])
from_host(bytes.fromhex("0ffa0000" * 16))
check("a full 64-byte packet = 16 events, all queued", len(queued()) == 4 + 3 + 16 and queued()[-1][:1] == b"\xfa", len(queued()))
base = len(queued())
core.rx += [((2, 1), bytes.fromhex("09903001")), ((3, 1), b""), ((2, 1), bytes.fromhex("0ff80000")), ((3, 1), b""),
            ((2, 1), bytes.fromhex("08803000")), ((3, 1), b"")]
poll()
q = queued()[base:]
check("three separate packets inside one block: all three are read in that block, in order (the endpoint is re-armed from the interrupt)",
      [m[:m[4]].hex() for m in q] == ["903001", "f8", "803000"] and not core.rx and core.get(DOEPCTL1) >> 31, [m.hex() for m in q])
base = len(queued())
for k in range(5):
    core.rx += [((2, 1), bytes.fromhex("0ffa0000") * 16), ((3, 1), b"")]
for _ in range(8):
    interrupt()
check("the computer sends faster than a block can take (80 events): the queue fills at 32 and the endpoint is left un-armed, nothing is lost from the FIFO",
      (e.r8(STATE + 44) - e.r8(STATE + 45)) & 0xFF == 32 and not core.get(DOEPCTL1) >> 31, ((e.r8(STATE + 44) - e.r8(STATE + 45)) & 0xFF, hex(core.get(DOEPCTL1))))
core.rx.clear()
poll()
check("...the next block hands those 32 to stock and arms the endpoint again", len(queued()) == base + 32 and core.get(DOEPCTL1) >> 31, len(queued()) - base)

# --- MIDI to the computer: the to-USB queue is sent to endpoint 1, then stock packs it for the host jack as before
OUTBUF, LENP = 0x24070000, 0x24070400


def put(*msgs):
    for m in msgs:
        w = e.r32(OUT_Q + 0x504) & 0xFFFFFFFF
        e.uc.mem_write(OUT_Q + (w & 0xFF) * 5, bytes(m).ljust(4, b"\0") + bytes([len(m)]))
        e.w32(OUT_Q + 0x504, w + 1)


def pump():
    core.midi.clear()
    e.w32(LENP, 0)
    e.w32(STACK, LENP)
    e.call("usbdev_midi_out", MGR, OUT_Q, OUTBUF, 0x300)
    n = e.r32(LENP) & 0xFFFF
    return [struct.pack("<I", w).hex() for w in core.midi], bytes(e.uc.mem_read(OUTBUF, n)).hex()


ours, stock = pump()
check("nothing queued: nothing sent, endpoint left idle", ours == [] and stock == "" and not core.get(DIEPCTL1) >> 31, (ours, stock))
put([0x90, 60, 100], [0xB0, 74, 127], [0xF8], [0x80, 60, 0], [0xE1, 0, 64], [0xC2, 9], [0xFB])
ours, stock = pump()
check("to the computer: note on, CC, clock, note off, pitch bend, program change, continue, each with its event code",
      ours == ["09903c64", "0bb04a7f", "0ff80000", "08803c00", "0ee10040", "0cc20900", "0ffb0000"], ours)
check("...as one transfer of 28 bytes in one packet", core.get(DIEPTSIZ1) == (1 << 19) | 28 and core.get(DIEPCTL1) >> 31, hex(core.get(DIEPTSIZ1)))
check("stock still packs the same queue for the host jack (its own choice: notes and clock only) and consumes it",
      stock == "09903c64" "0ff80000" "08803c00" and e.r32(OUT_Q + 0x500) == e.r32(OUT_Q + 0x504), stock)
core.reg[DIEPCTL1] &= ~(1 << 31)
put([0xFA], [0xFA], [0xF8], [0xFC], [0xFC], [0xFA])
ours, stock = pump()
check("slaved, stock queues Start and Stop twice each: the computer gets Start, tick, Stop, Start; the host jack still gets what stock packs",
      ours == ["0ffa0000", "0ff80000", "0ffc0000", "0ffa0000"] and stock == "0ffa0000" * 2 + "0ff80000" + "0ffc0000" * 2 + "0ffa0000", (ours, stock))
core.reg[DIEPCTL1] &= ~(1 << 31)
put([0xFA], [0xFC])
ours, stock = pump()
check("...and the memory of the last one carries over blocks (a Start after a Start is dropped, the Stop goes)", ours == ["0ffc0000"], ours)
put([0x90, 62, 90])
ours, stock = pump()
check("computer has not taken the last packet yet: this block's note is not written to the FIFO; the host jack still gets it",
      ours == [] and stock == "09903e5a", (ours, stock))
core.reg[DIEPCTL1] &= ~(1 << 31)
put(*[[0x90, 36 + i, 100] for i in range(20)])
ours, stock = pump()
check("20 notes in one block: one transfer of 80 bytes in two packets",
      len(ours) == 20 and core.get(DIEPTSIZ1) == (2 << 19) | 80 and ours[19] == "09903764", (len(ours), hex(core.get(DIEPTSIZ1))))
core.reg[DIEPCTL1] &= ~(1 << 31)
put(*[[0x90, i, 1] for i in range(100)])
ours, stock = pump()
check("100 notes in one block: the first 64 go to the computer (the FIFO's size), the host jack's buffer gets all 100",
      len(ours) == 64 and len(stock) == 800 and core.get(DIEPTSIZ1) == (4 << 19) | 256, (len(ours), len(stock)))
e.w32(OUT_Q + 0x500, 0xFFFFFFFE)
e.w32(OUT_Q + 0x504, 0xFFFFFFFE)
core.reg[DIEPCTL1] &= ~(1 << 31)
put([0x91, 1, 2], [0x91, 3, 4], [0x91, 5, 6])
ours, stock = pump()
check("queue counters wrapping past 2^32: three notes still go out in order", ours == ["09910102", "09910304", "09910506"], ours)


# --- audio: the three outputs' floats -> ring -> one packet per USB frame from the interrupt
W, R, DRY = STATE + 16, STATE + 20, STATE + 24
FA, FB, FC, FD, DAC, DAC2 = 0x24071000, 0x24071400, 0x24071800, 0x24071C00, 0x24072000, 0x24072800
ORDER = (2, 3, 1)                                # ring pairs: bus c (Out 1), bus d (Out 2), bus b (Out 3); a (headphones) is not sent


def u32(a):
    return e.r32(a) & 0xFFFFFFFF


def tap(block, n=128):
    """One audio block as stock ends it: buses a b c left, then right, then bus d left, right. Value = f(...) / 2^23."""
    for side in (0, 1):
        for out, at in enumerate((FA, FB, FC)):
            e.uc.mem_write(at, struct.pack(f"<{n}f", *[val(block, out, side, i) / 8388608.0 for i in range(n)]))
        e.uc.mem_write(STACK, struct.pack("<II", DAC + 8 * side, 4))
        e.call("usbaud_tap", FA, FB, FC, n)
    for side in (0, 1):
        e.uc.mem_write(FD, struct.pack(f"<{n}f", *[val(block, 3, side, i) / 8388608.0 for i in range(n)]))
        e.uc.mem_write(STACK, struct.pack("<I", 4))
        e.call("usbaud_tap1", FD, n, DAC2 + 8 * side, 0)


def frame(block, i):
    return [val(block, o, sd, i) for o in ORDER for sd in range(2)]


def val(block, out, side, i):
    return (block * 4096 + i * 16 + out * 2 + side) - 2_000_000


def host_takes():
    """The computer's IN token took the packet: transfer complete, interrupt."""
    core.reg[DIEPCTL2] &= ~(1 << 31)
    core.reg[DIEPINT2] = core.get(DIEPINT2) | 1
    core.reg[DSTS] = ((core.get(DSTS) >> 8) + 1) << 8
    core.audio.clear()
    core.log.clear()
    e.call("usbaud_isr")
    size = core.get(DIEPTSIZ2) & 0x7FFFF
    raw = b"".join(struct.pack("<I", w) for w in core.audio)
    frames = [[int.from_bytes(raw[f * 18 + c * 3:f * 18 + c * 3 + 3], "little", signed=True) for c in range(6)]
              for f in range(size // 18)]
    return size, len(core.audio), frames


def parity():
    """Which frame the last load of endpoint 2 was aimed at: 1 = odd."""
    v = [x for r, x in core.log if r == DIEPCTL2 and x >> 31][-1]
    return 1 if v & (1 << 29) else 0 if v & (1 << 28) else None


e.w32(W, 5000)
tap(0)
check("stream closed: the tap passes the buffers to stock and writes nothing to the ring",
      u32(W) == 5000 and e.r32(DAC) != 0 and e.r32(DAC + 8) != 0 and e.r32(DAC2) != 0 and e.r32(DAC2 + 8) != 0, u32(W))
core.reg[DSTS] = 10 << 8
core.audio.clear()
core.log.clear()
r = control(struct.pack("<BBHHH", 0x01, 11, 1, 1, 0))
check("SET_INTERFACE 1 alt 1 opens it: endpoint 2 = isochronous, 882 bytes, FIFO 2; its two interrupts unmasked beside receive",
      r == b"" and core.get(DIEPCTL2) & 0x03CC87FF == 0x00848372 and core.get(GINTMSK) == (1 << 18) | (1 << 20) | 0x10
      and core.get(GAHBCFG) & 1 and core.get(0x810) == 1 and core.get(0x81C) == 4 and e.r8(STATE + 14) == 1,
      f"{core.get(DIEPCTL2):#x} {core.get(GINTMSK):#x}")
check("...the first packet is 48 frames of silence aimed at the next (odd) frame",
      core.get(DIEPTSIZ2) == (1 << 29) | (1 << 19) | 864
      and len(core.audio) == 216 and not any(core.audio) and parity() == 1, (hex(core.get(DIEPTSIZ2)), len(core.audio)))
check("GET_INTERFACE 1 answers alt 1", control(struct.pack("<BBHHH", 0x81, 10, 0, 1, 1)) == b"\x01")
tap(1)
ring0 = [struct.unpack_from("<6i", bytes(e.uc.mem_read(RING_AT + ((5000 + i) % 1024) * 24, 24))) for i in range(128)]
check("a block lands in the ring as 24-bit, frame by frame: bus c left, right, bus d left, right, bus b left, right (a is left out)",
      u32(W) == 5128 and all(list(ring0[i]) == frame(1, i) for i in range(128)), ring0[:2])
size, words, frames = host_takes()
check("128 frames in the ring is not enough yet (wants 224): still silence, 48 frames, now aimed at an even frame",
      size == 864 and not any(any(f) for f in frames) and parity() == 0 and u32(R) == 5000, (size, parity(), u32(R)))
tap(2)
size, words, frames = host_takes()
want = [frame(1, i) for i in range(48)]
check("256 frames: live. The packet is the first 48 frames tapped, sample for sample, 216 words",
      size == 864 and words == 216 and frames == want and u32(R) == 5048, (size, words, frames[:1], want[:1]))
size, words, frames = host_takes()
want = [frame(1 + (48 + i) // 128, (48 + i) % 128) for i in range(48)]
check("the next packet continues exactly where that one ended", frames == want and u32(R) == 5096, frames[:1])
tap(3)
tap(4)
size, words, frames = host_takes()
check("ring running high (over 352 frames): 49 frames = 882 bytes in 221 words", size == 882 and words == 221 and len(frames) == 49 and u32(R) == 5145, (size, words))
check("...and the last frame of an odd-length packet is still intact", frames[48] == frame(1 + 144 // 128, 144 % 128), frames[48])
e.w32(R, u32(W) - 90)
size, words, frames = host_takes()
check("ring running low (under 96): 47 frames = 846 bytes in 212 words", size == 846 and words == 212 and len(frames) == 47, (size, words, u32(W) - u32(R)))
e.w32(R, u32(W) - 30)
size, words, frames = host_takes()
check("ring nearly empty (under a packet): silence, counted as running dry, and it waits to refill before going live again",
      size == 864 and not any(any(f) for f in frames) and u32(DRY) == 1 and e.r8(STATE + 15) == 0, (size, u32(DRY)))
tap(5)
size, words, frames = host_takes()
check("...one block later still silent; two blocks later live again", not any(any(f) for f in frames))
tap(6)
size, words, frames = host_takes()
check("live again after the refill", any(any(f) for f in frames) and e.r8(STATE + 15) == 1)
# clipping and the ring's wrap
e.w32(W, 0xFFFFFFC0)
e.w32(R, 0xFFFFFFC0)
for side in (0, 1):
    e.uc.mem_write(FC, struct.pack("<128f", *([1.5, -1.5, 1.0, -1.0, 0.5, 0.0] + [0.25] * 122)))
    e.uc.mem_write(FB, struct.pack("<128f", *([0.0] * 128)))
    e.uc.mem_write(FA, struct.pack("<128f", *([0.125] * 128)))
    e.uc.mem_write(STACK, struct.pack("<II", DAC + 8 * side, 4))
    e.call("usbaud_tap", FA, FB, FC, 128)
for side in (0, 1):
    e.uc.mem_write(FD, struct.pack("<128f", *([-0.25] * 128)))
    e.uc.mem_write(STACK, struct.pack("<I", 4))
    e.call("usbaud_tap1", FD, 128, DAC2 + 8 * side, 0)
tap(7)
size, words, frames = host_takes()
check("over full scale clips to the 24-bit limits; counters wrapping past 2^32 and the ring's end do not disturb the order",
      [f[0] for f in frames[:6]] == [8388607, -8388608, 8388607, -8388608, 4194304, 0] and frames[47][2] == -2097152 and frames[47][4] == 0
      and u32(W) == 0xC0 and u32(R) == (0xFFFFFFC0 + 48) & 0xFFFFFFFF, [f[0] for f in frames[:6]])
# a frame went by without our packet
core.reg[GINTSTS] = 1 << 20
core.audio.clear()
core.log.clear()
before = u32(R)
e.call("usbaud_isr")
check("missed frame: the stale packet is disabled and its FIFO flushed, a fresh one loaded, the flag acknowledged",
      any(r == DIEPCTL2 and v & (1 << 30) for r, v in core.log) and (GRSTCTL, (1 << 5) | (2 << 6)) in core.log
      and len(core.audio) in (212, 216, 221) and core.get(GINTSTS) & (1 << 20) == 0 and core.get(DIEPCTL2) >> 31
      and u32(R) == (before + (core.get(DIEPTSIZ2) & 0x7FFFF) // 18) & 0xFFFFFFFF, (core.log, len(core.audio), u32(R) - before))
core.audio.clear()
core.log.clear()
core.reg[DIEPINT2] = 0
e.call("usbaud_isr")
check("interrupt with nothing of ours pending: touches nothing", not core.audio and not core.log)
r = control(struct.pack("<BBHHH", 0x01, 11, 0, 1, 0))
w = u32(W)
tap(8)
check("SET_INTERFACE 1 alt 0 closes it: only receive left unmasked, endpoint off, the tap stops writing",
      r == b"" and core.get(GINTMSK) == 0x10 and core.get(GAHBCFG) & 1 and not core.get(DIEPCTL2) & (1 << 15)
      and not core.get(DIEPCTL2) >> 31 and e.r8(STATE + 14) == 0 and u32(W) == w, hex(core.get(DIEPCTL2)))
r = control(struct.pack("<BBHHH", 0x01, 11, 1, 1, 0))
check("reopened for the reset test", e.r8(STATE + 14) == 1 and core.get(GINTMSK) != 0)
e.w32(0x38800F74, 0)
r = control(struct.pack("<BBHHH", 0x01, 11, 0, 1, 0))
r = control(struct.pack("<BBHHH", 0x01, 11, 1, 1, 0))
check("no SDRAM block (Prism's check word wrong): the stream cannot open, only receive stays unmasked", e.r8(STATE + 14) == 0 and core.get(GINTMSK) == 0x10)
e.w32(0x38800F74, SDRAM ^ 0x5052534D)
r = control(struct.pack("<BBHHH", 0x01, 11, 1, 1, 0))

core.reg[GINTSTS] = 1 << 12
poll()
check("a second bus reset: address back to 0, unconfigured, the unsent packet dropped (endpoint disabled)",
      core.get(DCFG) & 0x7F0 == 0 and not core.get(DIEPCTL1) >> 31 and e.r8(STATE + 11) == 0, hex(core.get(DIEPCTL1)))
check("...and the audio stream closed with it", e.r8(STATE + 14) == 0 and core.get(GINTMSK) == 0x10 and not core.get(DIEPCTL2) >> 31)
put([0x90, 1, 1])
ours, stock = pump()
check("not configured: nothing is written to the endpoint; stock's side unaffected", ours == [] and stock == "09900101", (ours, stock))

# --- a core that never leaves reset: give up, never connect
core2 = Core()
core = core2
e.w32(RCC + 0xD8, 1 << 27)
poll(400)
core.reset_reads = 10 ** 9
poll(400)
check("core stuck in reset (no 48 MHz clock): gives up after ~1 s, D+ pull-up never turned on", core.get(DCTL) & 2 and e.r8(STATE + 10) == 4, e.r8(STATE + 10))
put([0x90, 1, 1])
ours, stock = pump()
check("...and MIDI out never touches the dead controller", ours == [] and stock == "09900101", (ours, stock))
before = dict(core.reg)
poll(50)
check("...and then leaves the controller alone", core.reg == before)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
