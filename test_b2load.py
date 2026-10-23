"""The card loader (src/b2load.c): flash bank 2 written from a file on the SD card.

Runs the loader as built, against a model of the card (stock's f_open / f_read / f_close stubbed) and a model of
bank 2's flash controller that keeps a list of everything the code should never do: a write to bank 1's flash
registers, an erase or a program outside sectors 0-6, a program with the controller locked or PG clear, a word
programmed over cells that were not erased.

What this cannot show, and the hardware has to: that stock's file calls behave from our hook in the disk task,
that the real controller takes the sequence from firmware as it took it over USB, and the timing (an erase is
0.87 s on the test unit; here it is instant).
"""
import struct
import sys

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

from emu import BASE, DEPLOYED_BANK2, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
B2, LIMIT, SECTOR = 0x08100000, 0xE0000, 0x20000      # LIMIT: the end of sector 6, all the loader may ever look at or program
PAY_LIMIT, CLAIM_AT, CLAIM = 0xC0000, 0xC0000, 0x43324242   # sectors 0-5 hold the payload; the claim is sector 6's first word
FOREIGN = 0x40
M, MAGIC = 0x2405FFD0, 0x43505534
B2CHK = M + 35
PAIRED, UNPAIRED, LOOKED = 1, 2, 4
FILE_OK, FILE_NONE, FILE_WRONG = 1, 2, 3
CARD_FOUND = 0x240021A4 + 0x15
WDG_DISK, WDG_NOW = 0x2400A584, 0x2400A58C
F_OPEN, F_READ, F_CLOSE, FILE_STEP = 0x08086534, 0x08086866, 0x08086D76, 0x08092F5C
KEYR1, CR1, KEYR2, CR2, SR2, CCR2 = 0x52002004, 0x5200200C, 0x52002104, 0x5200210C, 0x52002110, 0x52002114
LOCK, PG, SER, START = 1, 2, 4, 0x80
ERRORS = (1 << 17) | (1 << 18) | (1 << 19) | (1 << 21) | (1 << 22) | (1 << 23) | (1 << 24)

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


img = open(IMAGE, "rb").read()
e = Emu(IMAGE, "out/cave.elf")
uc = e.uc
uc.mem_map(0x38800000, 0x1000)                      # backup SRAM: the scan mark and the loader's try count live here
uc.mem_map(0x58024000, 0x1000)                      # RCC / PWR: bkp_enable switches the backup SRAM on
MARK, TRIES_ID, TRIES_N, SCAN_MARK = 0x388003C8, 0x388003CC, 0x388003D0, 0x4E435332
NAME_MARK = 0x4D414E32
SCANNING = 8
DCCMVAC = 0xE000EF68
payload = open("out/bank2.bin", "rb").read()      # the payload THIS image was linked with (= the test unit's, unless BANK2_NEW)
on_unit = open(DEPLOYED_BANK2, "rb").read()      # what is in the test unit's bank 2 today
WRITES = uc.mem_read(e.sym["b2load_writes"], 1)[0]  # 1 = this build lets the loader program bank 2


# ---------------------------------------------------------------- the card
class Card:
    def __init__(self):
        self.data, self.pos, self.opens, self.closes, self.reads, self.names = None, 0, 0, 0, 0, []
        self.fail_read_at = None                    # byte offset at which f_read starts returning a disk error
        self.swap_after_close = None                # a different file for the second open (the card changed)


card = Card()


def f_open():
    card.opens += 1
    card.names.append(e.cstr(e.arg(1)))
    if card.opens > 1 and card.swap_after_close is not None:
        card.data = card.swap_after_close
    card.pos = 0
    e.ret(4 if card.data is None else 0)            # FR_NO_FILE


def f_read():
    card.reads += 1
    to, n, got = e.arg(1), e.arg(2), e.arg(3)
    if card.fail_read_at is not None and card.pos >= card.fail_read_at:
        uc.mem_write(got, struct.pack("<I", 0))
        return e.ret(1)                             # FR_DISK_ERR
    chunk = card.data[card.pos:card.pos + n]
    uc.mem_write(to, chunk)
    uc.mem_write(got, struct.pack("<I", len(chunk)))
    card.pos += len(chunk)
    e.ret(0)


def f_close():
    card.closes += 1
    e.ret(0)


e.stubs[F_OPEN], e.stubs[F_READ], e.stubs[F_CLOSE] = f_open, f_read, f_close


# ---------------------------------------------------------------- bank 2's flash controller
class Flash:
    def __init__(self):
        self.reset()

    def reset(self):
        self.locked, self.key1, self.cr, self.sr = True, False, 0, 0
        self.bad, self.erased, self.words, self.partial = [], [], [], []
        self.claims, self.order = [], []            # claim words programmed; and everything in the order it happened
        self.stuck_locked = False                   # the keys do nothing
        self.erase_error = None                     # sector whose erase reports OPERR
        self.word_error = None                      # offset of the flash word whose programming reports PGSERR


flash = Flash()


def sync(cr=True):
    """Put the model's registers where the firmware reads them. (A read hook that rewrites the word being read does
    not change what Unicorn returns, so they are kept current from the write side instead.)"""
    uc.mem_write(SR2, struct.pack("<I", flash.sr))
    if cr:
        uc.mem_write(CR2, struct.pack("<I", flash.cr | (LOCK if flash.locked else 0)))


def reg_write(_uc, _access, addr, _size, value, _user):
    value &= 0xFFFFFFFF
    if addr in (KEYR1, CR1):
        flash.bad.append(f"write to bank 1's flash register {addr:#x}")
    elif addr == KEYR2:
        if value == 0x45670123:
            flash.key1 = True
        elif value == 0xCDEF89AB and flash.key1 and not flash.stuck_locked:
            flash.locked = False
        else:
            flash.key1 = False
        sync()
    elif addr == CR2:
        # the value written lands in the model's memory as it is, which is what a real unlocked CR2 reads back
        # (bar START, which nothing reads); a write to a LOCKED controller is ignored by the chip, so it is an error here
        if flash.locked:
            if value != (flash.cr | LOCK) and value & ~0x31:
                flash.bad.append(f"CR2 = {value:#x} written while locked")
            return
        if value & LOCK:
            flash.locked, flash.key1 = True, False
        flash.cr = value & ~(START | LOCK)
        if value & SER and value & START:
            n = (value >> 8) & 7
            if n > 5:
                flash.bad.append(f"ERASE OF SECTOR {n} - " + ("the claim" if n == 6 else "THE CALIBRATION"))
                return
            flash.erased.append(n)
            flash.order.append(("erase", n))
            if flash.erase_error == n:
                flash.sr |= 1 << 22
            else:
                uc.mem_write(B2 + n * SECTOR, b"\xff" * SECTOR)
            sync(cr=False)
    elif addr == CCR2:
        flash.sr &= ~value
        sync()
    elif addr != SR2:
        flash.bad.append(f"write to flash register {addr:#x}")


def bank_write(_uc, _access, addr, size, value, _user):
    off = addr - B2
    if not 0x08100000 <= addr < B2 + LIMIT:
        flash.bad.append(f"flash write at {addr:#x}, outside bank 2 sectors 0-6")
        return
    if flash.locked or not flash.cr & PG or size != 4 or off & 3:
        flash.bad.append(f"write to bank 2 at {addr:#x} with the controller {'locked' if flash.locked else 'not in PG'}")
        return
    if bytes(uc.mem_read(addr, 4)) != b"\xff\xff\xff\xff":
        flash.bad.append(f"programmed over cells that were not erased at {addr:#x}")
    if flash.partial and flash.partial[-1] + 4 != off:
        flash.bad.append(f"flash word written out of order at {addr:#x}")
    flash.partial.append(off)
    if len(flash.partial) == 8:
        word = flash.partial[0]
        if word & 31:
            flash.bad.append(f"flash word does not start on a 32-byte boundary: {word:#x}")
        (flash.claims if word == CLAIM_AT else flash.words).append(word)
        flash.order.append(("claim" if word == CLAIM_AT else "word", word))
        if flash.word_error == word:
            flash.sr |= 1 << 18
            sync()
        flash.partial = []


uc.hook_add(UC_HOOK_MEM_WRITE, reg_write, begin=0x52002000, end=0x52002FFF)

# every read of bank 2 (with what the mark said at that moment), and every cache line written out to backup SRAM
reads, cleaned = [], []
uc.hook_add(UC_HOOK_MEM_READ, lambda _uc, _a, addr, _s, _v, _u: reads.append(struct.unpack("<I", uc.mem_read(MARK, 4))[0])
            if len(reads) < 4 else None, begin=B2, end=B2 + LIMIT - 1)
uc.hook_add(UC_HOOK_MEM_WRITE, lambda _uc, _a, _addr, _s, value, _u: cleaned.append(value & 0xFFFFFFFF), begin=DCCMVAC, end=DCCMVAC + 3)
uc.hook_add(UC_HOOK_MEM_WRITE, bank_write, begin=0x08000000, end=0x081FFFFF)


def bank2(n=None):
    return bytes(uc.mem_read(B2, len(payload) if n is None else n))


def fresh(bank=payload, file=payload, chk=0, magic=MAGIC, found=1, mark=0xA5A5A5A5, tries=(0xA5A5A5A5, 0xA5A5A5A5), claim=False):
    """A boot: this much in bank 2, this file on the card, the meter's state as given. Backup SRAM comes up as
    garbage unless told otherwise, as after a power-on."""
    global card
    uc.mem_write(MARK, struct.pack("<3I", mark, *tries))
    cleaned.clear()
    reads.clear()
    card = Card()
    card.data = file
    flash.reset()
    uc.mem_write(B2, b"\xff" * LIMIT)
    uc.mem_write(B2, bank)
    if claim:                                       # a unit the loader has written before: its claim is in sector 6
        uc.mem_write(B2 + CLAIM_AT, struct.pack("<8I", CLAIM, ~CLAIM & 0xFFFFFFFF, 1, 0, 0, 0, 0, 0))
    uc.mem_write(M, struct.pack("<I", magic))
    uc.mem_write(B2CHK, bytes([chk]))
    uc.mem_write(CARD_FOUND, bytes([found]))
    uc.mem_write(WDG_DISK, struct.pack("<I", 0))
    uc.mem_write(WDG_NOW, struct.pack("<I", 0x1234))
    sync()


def word(a):
    return struct.unpack("<I", uc.mem_read(a, 4))[0]


def state():
    return uc.mem_read(B2CHK, 1)[0]


def verdict():
    return (state() >> 4) & 3


restarts = []
uc.hook_add(UC_HOOK_MEM_WRITE, lambda _uc, _a, _addr, _s, value, _u: (restarts.append(value & 0xFFFFFFFF), uc.emu_stop()),
            begin=0xE000ED0C, end=0xE000ED0F)


def poll():
    """One pass of the disk task through the loader. True if it asked for a restart (SYSRESETREQ) instead of returning."""
    restarts.clear()
    uc.reg_write(UC_ARM_REG_SP, 0x2407F000)
    uc.reg_write(UC_ARM_REG_LR, 0x0807FFF0 | 1)
    uc.emu_start(e.sym["b2_load_poll"] | 1, 0x0807FFF0, count=2_000_000_000)
    assert restarts or uc.reg_read(UC_ARM_REG_PC) == 0x0807FFF0, "the loader neither returned nor restarted"
    return restarts == [0x05FA0004]


def crafted(length):
    """A payload of another length that still passes for this image's: same id, same sum."""
    want = struct.unpack_from("<I", payload, 12)[0]
    body = bytearray((i * 37 + 11) & 0xFF for i in range(length - 16))
    struct.pack_into("<I", body, len(body) - 4, 0)
    s = sum(struct.unpack(f"<{len(body) // 4}I", bytes(body))) & 0xFFFFFFFF
    struct.pack_into("<I", body, len(body) - 4, (want - s) & 0xFFFFFFFF)
    return struct.pack("<4I", 0x21324242, struct.unpack_from("<I", payload, 4)[0], length, want) + bytes(body)


# ---------------------------------------------------------------- the hook
def is_bl(at, target):
    h1, h2 = struct.unpack_from("<HH", img, at - BASE)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    imm -= (1 << 25) if s else 0
    return (h1 >> 11) == 0b11110 and (h2 >> 12) & 0xD == 0xD and at + 4 + imm == target


check("the disk task's three calls to the file command step go through the loader's thunk",
      all(is_bl(at, e.sym["b2load_thunk"] & ~1) for at in (0x0807443E, 0x0807446E, 0x080744D8)))
check("the payload the suites load is the one this image expects",
      struct.unpack_from("<I", payload, 12)[0] == struct.unpack("<I", uc.mem_read(e.sym["b2_expect_sum"], 4))[0])

fresh()
step = []
e.stub(FILE_STEP, lambda: step.append(tuple(uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))))
e.call("b2load_thunk", 0x2401F508, 0x11, 0x22, 0x33, count=400_000_000)
check("the thunk runs the loader, then stock's step with its arguments untouched",
      step == [(0x2401F508, 0x11, 0x22, 0x33)] and card.opens == 1, (step, card.opens))

# ---------------------------------------------------------------- when it looks
fresh(magic=0)
poll()
check("before the meter is up (no audio block yet) it does nothing", card.opens == 0 and state() == 0)
fresh(found=0)
poll()
check("until stock has found a card it does nothing, and has not used up its one look",
      card.opens == 0 and not state() & LOOKED, state())
uc.mem_write(CARD_FOUND, b"\x01")
poll()
check("...and looks on the first pass after the card appears", card.opens == 1 and state() & LOOKED)
poll()
poll()
check("one look a boot: later passes do not touch the card again", card.opens == 1 and card.closes == 1)
fresh(chk=UNPAIRED | LOOKED)
poll()
check("a USB tool that has set the bypass with B2_LOOKED keeps the loader out", card.opens == 0 and not flash.bad and not flash.erased)

# ---------------------------------------------------------------- what it makes of the file
fresh()
poll()
check("bank 2 paired and its own payload on the card: verdict OK, pairing settled as paired",
      verdict() == FILE_OK and state() & 3 == PAIRED and card.names == ["BBEXTRA.BIN"], (state(), card.names))
check("...the whole file was read a flash word at a time and closed", card.reads == len(payload) // 32 and card.closes == 1,
      (card.reads, card.closes))
check("...and a paired bank 2 is NEVER written: no unlock, no erase, no word", not flash.erased and not flash.words
      and flash.locked and not flash.bad and bank2() == payload, flash.bad)

fresh(file=None)
poll()
check("no file on the card: verdict NONE, nothing written", verdict() == FILE_NONE and not flash.erased and not flash.words
      and card.closes == 0)

other = bytearray(payload)
struct.pack_into("<I", other, 4, 0x1DFC2DE2)        # the 3.2.l payload's id
fresh(file=bytes(other))
poll()
check("another build's payload (wrong id): verdict WRONG", verdict() == FILE_WRONG and card.closes == 1)

flipped = bytearray(payload)
flipped[5000] ^= 0x04
fresh(file=bytes(flipped))
poll()
check("one flipped bit in the body: verdict WRONG", verdict() == FILE_WRONG)

fresh(file=payload[:len(payload) - 32])
poll()
check("a file cut short: verdict WRONG", verdict() == FILE_WRONG)

fresh(file=payload[:10])
poll()
check("a file shorter than its own header: verdict WRONG", verdict() == FILE_WRONG and card.closes == 1)

huge = bytearray(payload)
struct.pack_into("<I", huge, 8, PAY_LIMIT + 32)
fresh(file=bytes(huge))
poll()
check("a header claiming more than sectors 0-5 hold: verdict WRONG, and the file is not read on",
      verdict() == FILE_WRONG and card.reads == 1, card.reads)

fresh()
card.fail_read_at = 4096
poll()
check("a disk error half way through: verdict WRONG, file closed", verdict() == FILE_WRONG and card.closes == 1)

# ---------------------------------------------------------------- the version label says what it found
e.stub(e.sym["master_title"], value=0)
version = e.cstr(e.sym["fw_version"])


def label():
    e.call("cpu_name", 0x24070000)
    return e.cstr(0x24070000)


# What the user actually looks at: the load readout in the middle of the Tools bar, redrawn on every entry. A leading "!"
# there = bank 2 is not this image's payload. (The version text beside it is fixed when the screen is built.)
tools_labels = []
e.stub(0x080A3DEC, lambda: tools_labels.append((e.arg(0), e.cstr(e.arg(1)))))
uc.mem_write(0x24063000, b"12.3 GB\0")


def bang():
    tools_labels.clear()
    e.call("cpu_tools", 0x24062174, 0x24063000)
    return dict(tools_labels).get(0x24062174 - 0xA0, "").startswith("!")


# cpu_name's own marks ride on the end of the version in the knob-page header, which shows eight characters: a test
# build's "3.3.e" has room for them, a release name that fills the eight ("JOEBOX 1") does not, and they drop off.
for file, bank, want, what, off in ((payload, payload, version + "+", "paired, file good", False),
                                    (None, payload, version + "-", "paired, no file", False),
                                    (bytes(flipped), payload, version + "?", "paired, file damaged", False),
                                    (None, b"", version + "!-", "bank 2 blank, no file", True)):
    fresh(bank=bank, file=file)
    poll()
    check(f"the header name reads {want[:8]!r} ({what})", label() == want[:8], label())
    check(f"...and the Tools load readout {'leads with' if off else 'has no'} '!'", bang() == off)
fresh(found=0)
poll()
check("...and carries no mark while the loader has not looked", label() == version, label())

# ---------------------------------------------------------------- the write itself (b2_program, whatever the build)
fresh(bank=b"")
r = e.call("b2_program", count=400_000_000)
ok = uc.reg_read(UC_ARM_REG_R0)
check("blank bank 2 + the payload on the card: programmed, and it reports clean", ok == 1 and bank2() == payload)
check("...sector 0 erased and no other", flash.erased == [0], flash.erased)
check("...and on this never-written unit THE CLAIM GOES ON FIRST, before anything is erased",
      flash.order[:2] == [("claim", CLAIM_AT), ("erase", 0)] and struct.unpack("<I", uc.mem_read(B2 + CLAIM_AT, 4))[0] == CLAIM, flash.order[:3])
check("...every flash word once, in order, THE HEADER LAST",
      flash.words == list(range(32, len(payload), 32)) + [0], flash.words[:4] + flash.words[-2:])
check("...the controller is locked again and the file closed", flash.locked and card.closes == 1)
check("...and the disk task's watchdog stamp was refreshed", struct.unpack("<I", uc.mem_read(WDG_DISK, 4))[0] == 0x1234)
check("...with nothing the model objects to", not flash.bad, flash.bad[:3])
check("...and nothing past the payload was touched", bytes(uc.mem_read(B2 + len(payload), 4096)) == b"\xff" * 4096)
uc.mem_write(B2CHK, bytes([UNPAIRED | LOOKED]))
e.call("b2_rescan", count=400_000_000)
check("b2_rescan then finds it paired and switches the effects on", state() & 3 == PAIRED, state())

stale = bytearray(payload)
stale[100:200] = bytes(100)
struct.pack_into("<I", stale, 12, 0)
fresh(bank=bytes(stale) + b"\x55" * 4096, claim=True)
e.call("b2_program", count=400_000_000)
check("a claimed bank with an older payload and debris after it is erased first, then replaced",
      uc.reg_read(UC_ARM_REG_R0) == 1 and bank2() == payload and flash.erased == [0] and not flash.bad
      and bytes(uc.mem_read(B2 + len(payload), 4096)) == b"\xff" * 4096, flash.bad[:3])

two = crafted(SECTOR + 64)
fresh(bank=b"", file=two)
e.call("b2_program", count=400_000_000)
check("a payload that runs into sector 1 erases sectors 0 and 1 and no further",
      uc.reg_read(UC_ARM_REG_R0) == 1 and flash.erased == [0, 1] and bank2(len(two)) == two and not flash.bad,
      (flash.erased, flash.bad[:3]))

full = crafted(PAY_LIMIT)
fresh(bank=b"", file=full)
e.call("b2_program", count=2_000_000_000)
check("the largest payload there can be fills sectors 0-5 exactly; SECTOR 6 (the claim) AND SECTOR 7 (the calibration) ARE NEVER ERASED",
      uc.reg_read(UC_ARM_REG_R0) == 1 and flash.erased == list(range(6)) and bank2(PAY_LIMIT) == full and not flash.bad
      and flash.claims == [CLAIM_AT], (flash.erased, flash.bad[:3], flash.claims))

# ---------------------------------------------------------------- when the flash or the card lets it down
fresh(bank=b"")
flash.stuck_locked = True
e.call("b2_program", count=400_000_000)
check("a controller that will not unlock: gives up before erasing anything",
      uc.reg_read(UC_ARM_REG_R0) == 0 and not flash.erased and not flash.words and not flash.bad, flash.bad[:3])

fresh(bank=bytes(stale))
flash.erase_error = 0
e.call("b2_program", count=400_000_000)
check("an erase that reports an error: nothing is programmed, the controller is locked",
      uc.reg_read(UC_ARM_REG_R0) == 0 and not flash.words and flash.locked and not flash.bad, flash.bad[:3])

fresh(bank=b"")
flash.word_error = 4096
e.call("b2_program", count=400_000_000)
check("a word that fails to program: it stops there and THE HEADER IS NEVER WRITTEN",
      uc.reg_read(UC_ARM_REG_R0) == 0 and flash.words[-1] == 4096 and 0 not in flash.words
      and bank2(32) == b"\xff" * 32 and flash.locked, flash.words[-3:])
uc.mem_write(B2CHK, bytes([UNPAIRED | LOOKED]))
e.call("b2_rescan", count=400_000_000)
check("...so the half-written bank 2 is not a payload and the effects stay off", state() & 3 == UNPAIRED, state())

fresh(bank=b"")
card.fail_read_at = 8192
e.call("b2_program", count=400_000_000)
check("the card failing part way through the write: stops, no header, locked",
      uc.reg_read(UC_ARM_REG_R0) == 0 and 0 not in flash.words and bank2(32) == b"\xff" * 32 and flash.locked)

fresh(bank=bytes(stale), file=bytes(other))
e.call("b2_program", count=400_000_000)
check("a file that is not this image's payload is refused BEFORE the erase, even asked directly",
      uc.reg_read(UC_ARM_REG_R0) == 0 and not flash.erased and bank2() == bytes(stale))

fresh(bank=b"", file=None)
e.call("b2_program", count=400_000_000)
check("no file: nothing happens", uc.reg_read(UC_ARM_REG_R0) == 0 and not flash.erased and not flash.bad)

# ---------------------------------------------------------------- the whole thing, from the disk task's pass
if WRITES:
    fresh(bank=b"")
    again = poll()
    check("WRITE BUILD - blank bank 2, payload on the card: one pass programs it and it reads back paired",
          state() & 3 == PAIRED and verdict() == FILE_OK and bank2() == payload and flash.erased == [0] and not flash.bad
          and card.opens == 2, (state(), flash.erased, flash.bad[:3]))
    check("...and THE UNIT RESTARTS, so the next boot builds its lists with the payload in place", again, restarts)
    check("...with the controller locked, the mark down and the try count at zero before it goes",
          flash.locked and word(MARK) == 0 and word(TRIES_N) == 0)
    uc.mem_write(M, struct.pack("<I", MAGIC))            # the boot after the restart
    uc.mem_write(B2CHK, b"\x00")
    flash.reset()
    sync()
    card.opens = 0
    again = poll()
    check("...and that next boot finds bank 2 paired, writes nothing and does NOT restart again",
          not again and state() & 3 == PAIRED and not flash.erased and not flash.words and card.opens == 1, (again, flash.erased))
    check("...and Tools shows no '!'", not bang() and label() == (version + "+")[:8], label())
    fresh(bank=bytes(stale))
    again = poll()
    check("WRITE BUILD - a stale payload in bank 2 is replaced the same way", again and state() & 3 == PAIRED and bank2() == payload)
    if on_unit != payload:
        fresh(bank=on_unit)
        poll()
        check("WRITE BUILD - THE TEST UNIT'S FIRST BOOT: the payload in the test unit's bank 2 today is replaced by this build's, sector 0 only",
              state() & 3 == PAIRED and bank2() == payload and flash.erased == [0] and not flash.bad
              and flash.words == list(range(32, len(payload), 32)) + [0], (state(), flash.erased, flash.bad[:3]))
        if payload[16:] == on_unit[16:]:
            check("...and what changed in bank 2 is the id word alone", payload[:4] == on_unit[:4] and payload[8:] == on_unit[8:])
        else:
            print(f"     (a real change of contents: {len(on_unit)} -> {len(payload)} bytes)")
            check("...and nothing of the old payload is left past the end of the new one",
                  bytes(uc.mem_read(B2 + len(payload), 1024)) == b"\xff" * 1024)
    fresh(bank=b"", file=bytes(flipped))
    again = poll()
    check("WRITE BUILD - a damaged file never reaches the flash, and nothing restarts",
          not again and not flash.erased and not flash.words and state() & 3 == UNPAIRED)
    fresh(bank=b"")
    card.swap_after_close = bytes(other)
    poll()
    check("WRITE BUILD - the card changing between the check and the write is caught before the erase",
          not flash.erased and state() & 3 == UNPAIRED)
    fresh(bank=b"")
    flash.word_error = 2048
    again = poll()
    poll()
    check("WRITE BUILD - a failed write is not tried again this boot, and does not restart the unit",
          not again and flash.erased == [0] and state() & 3 == UNPAIRED and card.opens == 2, (flash.erased, card.opens))
else:
    fresh(bank=b"")
    poll()
    check("READ-ONLY BUILD - blank bank 2, payload on the card: it reports and writes NOTHING",
          verdict() == FILE_OK and state() & 3 == UNPAIRED and not flash.erased and not flash.words and flash.locked
          and not flash.bad and card.opens == 1, (state(), flash.erased, flash.bad[:3]))
    fresh(bank=bytes(stale))
    poll()
    check("READ-ONLY BUILD - nor does it touch a stale payload", bank2() == bytes(stale) and not flash.erased and not flash.bad)

# ---------------------------------------------------------------- a flash word that cannot be read (the guard, 3.3.a)
fresh(file=None)
poll()
check("THE SCAN ANNOUNCES ITSELF: the mark is up in backup SRAM for every read of bank 2, and written out of the cache first",
      reads and all(m == SCAN_MARK for m in reads) and MARK in cleaned, ([hex(m) for m in reads], [hex(c) for c in cleaned[:3]]))
check("...and is taken down again when the scan comes back, paired", word(MARK) == 0 and state() & 3 == PAIRED and not state() & SCANNING)

fresh(file=None, mark=SCAN_MARK)
poll()
check("A BOOT THAT FINDS THE MARK STILL UP (the last scan died on a bad word): bank 2 is not read AT ALL, and is not paired",
      not reads and state() & 3 == UNPAIRED and word(MARK) == SCAN_MARK, (len(reads), state()))
check("...so Tools shows the '!' and the unit runs with those effects off instead of faulting again", bang())

# the scan dying for real: the first read of bank 2 never returns
fresh(file=None)
died = uc.hook_add(UC_HOOK_MEM_READ, lambda _uc, _a, _addr, _s, _v, _u: uc.emu_stop(), begin=B2, end=B2 + LIMIT - 1)
try:
    uc.reg_write(UC_ARM_REG_R0, 0)
    uc.emu_start(e.sym["b2_load_poll"] | 1, 0x0807FFF0, count=400_000_000)
except Exception:
    pass
uc.hook_del(died)
check("a scan that is cut off mid-read leaves the mark up for the next boot", word(MARK) == SCAN_MARK)
uc.mem_write(M, struct.pack("<I", MAGIC))
uc.mem_write(B2CHK, b"\x00")                        # the next boot: b2chk starts from zero (cpu_boot)
reads.clear()
poll()
check("...and that next boot keeps off bank 2", not reads and state() & 3 == UNPAIRED)

fresh()
uc.mem_write(B2CHK, bytes([SCANNING]))               # another task is inside the scan in THIS boot
e.call("b2_live", count=400_000_000)
check("a task that arrives while another is scanning gets 'not yet' and records NO verdict of its own",
      uc.reg_read(UC_ARM_REG_R0) == 0 and state() & 3 == 0 and not reads, state())

if WRITES:
    fresh(bank=payload, mark=SCAN_MARK, claim=True)
    again = poll()
    check("WRITE BUILD - mark up + the file on the card: the loader rewrites bank 2, takes the mark down, and restarts into a paired boot",
          again and flash.erased == [0] and bank2() == payload and word(MARK) == 0 and state() & 3 == PAIRED and not flash.bad
          and word(TRIES_N) == 0, (again, flash.erased, hex(word(MARK)), state(), word(TRIES_N)))
    # a flash that will not hold the payload: every write is followed by a bad scan
    key = None
    boots = []
    for boot in range(4):
        fresh(bank=b"", tries=(key, boot if boot < 3 else 2) if key is not None else (0xA5A5A5A5, 0xA5A5A5A5),
              mark=SCAN_MARK if boot else 0xA5A5A5A5, claim=boot > 0)
        flash.word_error = 1024
        poll()
        key = word(TRIES_ID)
        boots.append((len(flash.erased), word(TRIES_N)))
    check("WRITE BUILD - a flash that will not take the payload is written TWICE and then left alone",
          boots == [(1, 1), (1, 2), (0, 2), (0, 2)], boots)
    fresh(bank=b"", tries=(key ^ 1, 2))
    poll()
    check("WRITE BUILD - ...but a count kept for a DIFFERENT payload does not stop this one", flash.erased == [0] and state() & 3 == PAIRED
          and word(TRIES_N) == 0)
    fresh(bank=b"")
    poll()
    check("WRITE BUILD - a clean write leaves the count at zero, written out of the cache", word(TRIES_N) == 0 and word(TRIES_ID) == key
          and TRIES_N in cleaned and TRIES_ID in cleaned)

# ---------------------------------------------------------------- whose is it? (3.3.d) - an erase cannot be taken back
CLAIM_MARK = 0x4D4C4332


def claim_word():
    return struct.unpack("<3I", uc.mem_read(B2 + CLAIM_AT, 12))


if WRITES:
    junk = bytes((i * 29 + 3) & 0xFF for i in range(4096))
    for what, bank in (("SOMETHING THAT IS NOT OURS at the start of bank 2", junk),
                       ("a blank start and something that is not ours in sector 4", b"\xff" * (4 * SECTOR + 512) + junk),
                       ("something that is not ours in sector 6, away from the claim word", b"\xff" * (6 * SECTOR + 4096) + junk[:64]),
                       ("an older payload of ours with something else after it", bytes(stale) + b"\xff" * 64 + junk[:64])):
        fresh(bank=bank)
        before = bytes(uc.mem_read(B2, LIMIT))
        again = poll()
        check(f"{what}: NOTHING is erased or programmed, no claim is made, and bank 2 is byte for byte as it was",
              not again and not flash.erased and not flash.words and not flash.claims and not flash.bad and flash.locked
              and bytes(uc.mem_read(B2, LIMIT)) == before, (flash.erased, flash.claims, flash.bad[:2]))
        check("...the unit runs with the effects off, B2_FOREIGN set and '!' on Tools; the try count is not spent on it",
              state() & FOREIGN and state() & 3 == UNPAIRED and bang() and word(MARK) == 0
              and word(TRIES_N) != 1, (hex(state()), word(TRIES_N)))
    fresh(bank=bytes(stale))
    again = poll()
    check("one of the mod's payloads from BEFORE the claim existed, blank after it: claimed, then replaced",
          again and flash.order[0] == ("claim", CLAIM_AT) and flash.erased == [0] and bank2() == payload and not flash.bad
          and not state() & FOREIGN, (flash.order[:2], flash.bad[:2]))
    fresh(bank=junk * 8, claim=True)
    reads.clear()
    count = {"n": 0}
    spy = uc.hook_add(UC_HOOK_MEM_READ, lambda _uc, _a, addr, _s, _v, _u: count.__setitem__("n", count["n"] + 1),
                      begin=B2 + SECTOR, end=B2 + CLAIM_AT - 1)
    again = poll()
    uc.hook_del(spy)
    check("A CLAIMED bank holding debris (an erase the power cut short): erased and written, no questions asked",
          again and flash.erased == [0] and bank2() == payload and not flash.claims and not flash.bad, (flash.erased, flash.bad[:2]))
    check("...and with a claim to go on, the rest of the bank is not read through first", count["n"] == 0, count["n"])
    fresh(bank=payload)                               # the test unit today: paired, written before the claim existed
    again = poll()
    check("PAIRED and unclaimed (the test unit): the claim is written - and nothing else, no erase, no restart",
          not again and flash.claims == [CLAIM_AT] and not flash.erased and not flash.words and not flash.bad and flash.locked
          and claim_word()[:2] == (CLAIM, ~CLAIM & 0xFFFFFFFF) and bank2() == payload and state() & 3 == PAIRED,
          (flash.claims, flash.erased, flash.bad[:2]))
    fresh(bank=payload, claim=True)
    again = poll()
    check("paired and claimed: bank 2 is not written at all", not again and not flash.claims and not flash.erased and not flash.words
          and flash.locked and not flash.bad)
    fresh(bank=payload + b"\xff" * (CLAIM_AT - len(payload)) + b"\x00" * 32)
    again = poll()
    check("paired, and sector 6's first word already holds something else: left alone, nothing programmed over it",
          not again and not flash.claims and not flash.bad and state() & 3 == PAIRED, (flash.claims, flash.bad[:2]))
    fresh(bank=b"", mark=CLAIM_MARK)
    again = poll()
    check("the loader's own look died in an earlier boot (its mark is up): it keeps away - no read, no claim, no erase",
          not again and not reads and not flash.claims and not flash.erased and state() & FOREIGN and word(MARK) == CLAIM_MARK,
          (len(reads), flash.claims, hex(state())))
    fresh(bank=payload, mark=SCAN_MARK)               # a dead scan on a bank with NO claim
    again = poll()
    check("a dead scan and no claim: the bank cannot be proved blank without reading the bad word again, so it is left alone",
          not again and not flash.erased and not flash.claims and word(MARK) == SCAN_MARK and state() & FOREIGN,
          (flash.erased, hex(word(MARK))))
    fresh(bank=b"")
    flash.word_error = CLAIM_AT
    again = poll()
    check("the claim itself failing to program: nothing is erased", not again and not flash.erased and not flash.words and flash.locked,
          (flash.erased, flash.words[:2]))

# ---------------------------------------------------------------- what the lists call the effects (3.3.b)
lists = {}


def reg_list():
    names_at, count = e.arg(3), struct.unpack("<I", uc.mem_read(uc.reg_read(UC_ARM_REG_SP), 4))[0]
    lists[e.arg(1)] = [e.cstr(struct.unpack("<I", uc.mem_read(names_at + 4 * i, 4))[0]) for i in range(count)]


e.stub(0x0808C0D8, reg_list)
e.stub(0x0808C12C)


def registered():
    lists.clear()
    reads.clear()
    e.call("insert_register", 0x24070100)
    e.call("master_register", 0x24070100)
    uc.mem_write(0x2407EF00, struct.pack("<2I", 0, 0))
    e.call("munchi_register", 0x24070100, 0x197, 0, 0, count=2_000_000)
    return lists.get(0x1B6), lists.get(0x1DB), lists.get(0x197)


fresh()
uc.mem_write(M, bytes(36))                           # as it really is at that moment: the meter is NOT up yet
ins, mfx, dly = registered()
check("payload in bank 2: the lists carry the names - Phaser / Flanger / Gate, Prism / TapeScam, Motion / Relapse / Confetti",
      ins == ["Off", "Phaser", "Flanger", "Gate", "Transnt"] and mfx == ["Off", "VHS", "Prism", "TapeScam"]
      and dly == ["Delay", "Munchi", "Motion", "Relapse", "Confetti"], (ins, mfx, dly))
check("...and asking leaves the mark down", word(MARK) == 0)
for what, kw in (("NO PAYLOAD (BLACKBOX.bin copied to the card and nothing else)", dict(bank=b"")),
                 ("another build's payload", dict(bank=bytes(other))),
                 ("a payload whose sum is not this image's", dict(bank=bytes(stale)))):
    fresh(**kw)
    uc.mem_write(M, bytes(36))
    ins, mfx, dly = registered()
    check(f"{what}: the bank 2 effects are listed as '---' (inserts, Prism, since 3.3.o Motion / Relapse / Confetti, since "
          "3.3.y VHS and Munchi), every other entry as before, and the lists keep their length",
          ins == ["Off", "---", "---", "---", "---"] and mfx == ["Off", "---", "---", "---"]
          and dly == ["Delay", "---", "---", "---", "---"], (ins, mfx, dly))
for what, m in (("the mark up from a dead scan", SCAN_MARK), ("the mark up from a naming read that died", NAME_MARK)):
    fresh(mark=m)
    uc.mem_write(M, bytes(36))
    ins, mfx, dly = registered()
    check(f"{what}: '---' as well, bank 2 is not read to find out, and the mark is left for the loader",
          ins == ["Off", "---", "---", "---", "---"] and mfx[-1] == "---" and dly[-1] == "---" and not reads and word(MARK) == m,
          (ins, len(reads), hex(word(MARK))))
fresh()
uc.mem_write(M, bytes(36))
seen_marks = []
spy = uc.hook_add(UC_HOOK_MEM_READ, lambda _uc, _a, _addr, _s, _v, _u: seen_marks.append(word(MARK)) if len(seen_marks) < 3 else None,
                  begin=B2, end=B2 + LIMIT - 1)
e.call("b2_present", count=2_000_000)
uc.hook_del(spy)
check("the naming read announces itself with its OWN mark, and takes it down", seen_marks and all(m == NAME_MARK for m in seen_marks)
      and word(MARK) == 0 and uc.reg_read(UC_ARM_REG_R0) == 1, [hex(m) for m in seen_marks])
# the audio task arriving at the pairing scan while the screen task is in the middle of that read
fresh(mark=NAME_MARK)
e.call("b2_live", count=400_000_000)
check("a pairing scan that finds the NAMING mark says 'not yet': no verdict, no read of bank 2, and it will ask again",
      uc.reg_read(UC_ARM_REG_R0) == 0 and state() & 3 == 0 and not state() & SCANNING and not reads and word(MARK) == NAME_MARK, state())
uc.mem_write(MARK, struct.pack("<I", 0))             # ...the screen task finishes
e.call("b2_live", count=400_000_000)
check("...and the next block's scan goes ahead and pairs", uc.reg_read(UC_ARM_REG_R0) == 1 and state() & 3 == PAIRED)
if WRITES:
    fresh(mark=NAME_MARK, claim=True)
    again = poll()
    check("WRITE BUILD - a NAMING mark stuck from an earlier boot + the file on the card: the loader rewrites bank 2, clears it, restarts",
          again and flash.erased == [0] and word(MARK) == 0 and state() & 3 == PAIRED and bank2() == payload, (again, flash.erased, state()))

print(f"\n{'writes enabled' if WRITES else 'read-only build'}: {fails} failed")
sys.exit(1 if fails else 0)
