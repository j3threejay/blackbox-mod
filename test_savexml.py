"""The streamed preset writer (src/savexml.c) against stock's (FUN_08096754), on this build's image.

Real firmware runs for both, in one emulator with the SDRAM heap mapped: the cell type table and the source / jack
name tables (static initializers 0x08094c64, 0x0808e4e8), the settings registry (FUN_0808c158, with our
registrations), the data block's constructors, and the real preset LOADER FUN_08096ad8 on a preset.xml. Then stock's
writer and savexml each write that same loaded project; f_open / f_write / f_close are stubbed to capture what they
are given. Checked:
  - the files are byte-identical, and so is every f_write fragment (savexml makes stock's printer calls in order):
    a real preset (SAVEXML_PRESET, optional), a synthetic heavy project made through the same loader,
    and that heavy project with its data poked to reach every branch of the writer (repeated / unnamed / zero
    setting ids, a name two ids share, both string-valued settings, every event type, MIDI CC sources, entities)
  - heap: stock's save takes ~1 MB of the SDRAM heap for the sample preset, savexml none; with the heap capped at
    0xFC000 (where beta 2 hung) stock's writer reaches the allocator's `b .` and savexml writes the same file
  - error paths as FUN_08097148: no FIL -> 0; f_open fails -> 0, the message, nothing written or closed; f_write
    failing -> 1 and the rest still attempted, as stock does
  - watchdog: stock never stamps the disk task's word during the write; savexml stamps it at every element
  - the five call sites now call savexml, and nothing in the image calls FUN_08096754 any more
"""
import os
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import Emu, RET, STACK, ARGS, BASE

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
PRESET = os.environ.get("SAVEXML_PRESET", "")       # a real preset.xml; unset = the synthetic projects only
STOCK_WRITER = 0x08096754
SITES = (0x08091968, 0x080921F2, 0x08092290, 0x08092750, 0x08092E14)
TOP, LOW, HEAD = 0x24000088, 0x2400008C, 0x24002E7C      # the SDRAM heap: top (grows down), the permanent side
DATA, FIL, PATH, BUF = 0x24038000, 0x24053000, 0x24053100, 0x24054000
FILPTR = 0x24020084
WDG = 0x2400A584                                         # stamp A (disk task), stamp B, the supervisor's counter
F_OPEN, F_READ, F_WRITE, F_CLOSE, PRINTF, STAMP = 0x08086534, 0x08086866, 0x08086A06, 0x08086D76, 0x08043DE4, 0x080469C4
CAP_BETA2 = 0xFC000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


class Rig:
    def __init__(self, heap=0x3000000):
        e = self.e = Emu(IMAGE, "out/cave.elf")
        e.uc.mem_map(0xC0000000, 0x4000000)                 # SDRAM
        e.uc.mem_map(0x38800000, 0x1000)                    # backup SRAM (our hooks keep state there)
        e.uc.mem_map(0x58024000, 0x1000)                    # RCC / PWR: bkp_enable
        img = open(IMAGE, "rb").read()
        e.uc.mem_write(0x24000000, img[0x080F1D80 - BASE:0x080F1E78 - BASE])   # stock's .data image
        e.w32(FILPTR, FIL)
        e.uc.mem_write(PATH, b"preset.xml\0")
        self.heap = heap
        self.xml, self.pos = b"", 0
        self.open_result, self.write_fail_from = 0, None
        self.crash = False
        self.low = 0xC4000000
        self.reset_log()

        def f_open():
            self.opens.append(e.cstr(e.arg(1)))
            self.pos = 0
            e.w32(e.arg(0) + 0x10, len(self.xml))           # obj.objsize, as the reader takes it
            e.ret(self.open_result)
        e.stubs[F_OPEN] = f_open

        def f_read():
            n = min(e.arg(2), len(self.xml) - self.pos)
            e.uc.mem_write(e.arg(1), self.xml[self.pos:self.pos + n])
            self.pos += n
            e.w32(e.arg(3), n)
            e.ret(0)
        e.stubs[F_READ] = f_read

        def f_write():
            n = e.arg(2)
            self.frags.append(bytes(e.uc.mem_read(e.arg(1), n)))
            if self.write_fail_from is not None and len(self.frags) > self.write_fail_from:
                e.w32(e.arg(3), 0)
                e.ret(1)                                    # FR_DISK_ERR
            else:
                e.w32(e.arg(3), n)
                e.ret(0)
        e.stubs[F_WRITE] = f_write

        def f_close():
            self.closes += 1
            e.ret(0)
        e.stubs[F_CLOSE] = f_close

        def printf():
            fmt = bytes(e.uc.mem_read(e.arg(0), 64)).split(b"\0")[0].decode("latin1")
            arg = bytes(e.uc.mem_read(e.arg(1), 64)).split(b"\0")[0].decode("latin1") if "%s" in fmt else e.arg(1)
            self.printfs.append((fmt, arg))
        e.stubs[PRINTF] = printf                            # observed; stock's own (empty) body still runs

        def stamp():
            if e.arg(0) == WDG:
                self.stamps.append(sum(len(f) for f in self.frags))
        e.stubs[STAMP] = stamp

        def crash():
            self.crash = True
            e.uc.emu_stop()
        e.stubs[0x0808A37C] = crash                         # "No more extended memory": stock's `b .`

        def track():
            self.low = min(self.low, e.r32(TOP) & 0xFFFFFFFF)
        e.stubs[0x0804444E] = track                         # malloc's success return
        self.boot()

    def reset_log(self):
        self.opens, self.frags, self.closes, self.printfs, self.stamps = [], [], 0, [], []

    def call(self, fn, *args):
        e = self.e
        for i, v in enumerate(args):
            e.uc.reg_write(ARGS[i], v & 0xFFFFFFFF)
        e.uc.reg_write(UC_ARM_REG_SP, STACK)
        e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
        self.crash = False
        e.uc.emu_start(fn | 1, RET, count=3_000_000_000)
        if self.crash:
            return "CRASH"
        assert e.uc.reg_read(UC_ARM_REG_PC) == RET, hex(e.uc.reg_read(UC_ARM_REG_PC))
        return e.uc.reg_read(UC_ARM_REG_R0)

    def boot(self):
        e = self.e
        e.w32(TOP, 0xC4000000)
        e.w32(LOW, 0xC0000000)
        e.w32(HEAD, 0)
        self.call(0x08094C64)                               # cell types (name <-> code)
        self.call(0x0808E4E8)                               # modulation source + jack names
        e.uc.mem_write(0x24030000, bytes(0x100))
        self.call(0x0808C158, 0x24030000)                   # the settings registry (and our registrations)
        e.uc.mem_write(DATA, bytes(0x7400))                 # the data block, as FUN_08070bf4 makes it
        self.call(0x08090298, DATA)
        self.call(0x0808FD30, DATA)
        e.w32(LOW, 0xC4000000 - self.heap)                  # what is left between the permanent side and the top
        e.w32(TOP, 0xC4000000)
        e.w32(HEAD, 0)

    def load(self, xml):
        self.xml = xml
        return self.call(0x08096AD8, PATH, BUF, 0x1000, DATA)

    def save(self, fn):
        """-> (result, file bytes, heap bytes taken at the deepest point, stack bytes used)"""
        e = self.e
        self.reset_log()
        top = e.r32(TOP) & 0xFFFFFFFF
        self.low = top
        e.uc.mem_write(STACK - 0x2000, b"\xA5" * 0x2000)    # paint the stack to see how deep it went
        r = self.call(fn, PATH, BUF, 0x1000, DATA)
        paint = bytes(e.uc.mem_read(STACK - 0x2000, 0x2000))
        used = 0x2000 - next(i for i, b in enumerate(paint) if b != 0xA5)
        return r, b"".join(self.frags), top - self.low, used


def calls_to(img, target):
    """Every Thumb BL in the image that lands on target."""
    out = []
    for at in range(BASE, BASE + len(img) - 4, 2):
        h1, h2 = struct.unpack_from("<HH", img, at - BASE)
        if h1 >> 11 != 0x1E or h2 >> 14 != 3 or not h2 & 0x1000:
            continue
        s = (h1 >> 10) & 1
        off = (s << 24) | ((~((h2 >> 13) & 1 ^ s) & 1) << 23) | ((~((h2 >> 11) & 1 ^ s) & 1) << 22) \
            | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
        if s:
            off -= 1 << 25
        if at + 4 + off == target:
            out.append(at)
    return out


# ---------------------------------------------------------------------------------------------- a heavy project
ENT = "&<>\"'"


def heavy_xml():
    """Everything the loader takes, near its limits: 20 pads with 128 slices and 12 modulation slots each (CC sources
    among them), long file names full of entities, 80 layers + 32 sections of events of every type, all 576 assets."""
    srcs = ["velocity", "midivol", "midipan", "env1", "lfo1", "lfo2", "key", "modwheel", "pitchbend", "seq1", "macrox"]
    dests = ["gaindb", "panpos", "pitch", "dualfilcutoff", "res", "samstart", "fx1send", "fx2send", "envattack",
             "envrel", "lforate", "grainsizeperc"]
    o = ['<?xml version="1.0" encoding="UTF-8"?>', "<document>", '<session version="2">']

    def q(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
    for col in range(5):
        for row in range(4):
            n = col * 4 + row
            fname = ("\\Kits\\%s Pad %02d %s été " % (ENT, n, ENT) + "x" * 200)[:250]
            o.append(f'<cell row="{row}" column="{col}" layer="0" filename="{q(fname)}" type="{"sample" if n % 3 else "samtempl"}">')
            o.append(f'<params gaindb="{n * 37 - 300}" pitch="{-n}" samtrigtype="{n % 3}" outputbus="{n % 6}" quantsize="{n % 9}"/>')
            for k in range(12):
                if k % 4 == 3:
                    o.append(f'<modsource dest="{dests[k]}" src="midicc" mchan="{(n + k) % 16}" ccnum="{(n * 7 + k) % 128}" slot="{k % 4}" amount="{(k - 6) * 151}"/>')
                else:
                    o.append(f'<modsource dest="{dests[k]}" src="{srcs[(n + k) % len(srcs)]}" slot="{k % 4}" amount="{(k - 6) * 77}"/>')
            o.append("<slices>" + "".join(f'<slice pos="{i * 4567 + n}"/>' for i in range(128)) + "</slices>")
            o.append("</cell>")

    def events(n, seed):
        ev = []
        for i in range(n):
            step = (i * 3 + seed) % 256
            k = (i + seed) % 6
            chan = "" if i % 4 == 0 else f' chan="{(i * 37 + seed) % 300}"'
            if k == 0:
                ev.append(f'<seqevent step="{step}"{chan} type="note" strtks="{step * 960 + i % 17}" pitch="{(i * 5) % 128}" lencount="{i % 5}" lentks="{(i % 5) * 960 + i % 3}" velocity="{(i * 11) % 128}" cond="{(i * 13) % 135}"/>')
            elif k == 1:
                ev.append(f'<seqevent step="{step}"{chan} type="note" strtks="{step * 960}" pitch="{i % 128}" lentks="{240 * (i % 3 + 1)}"/>')
            elif k == 2:
                ev.append(f'<seqevent step="{step}"{chan} type="auto" value="{i * 1001 - 50000}" value2="{-i * 7}" lencount="{i % 4}"/>')
            elif k == 3:
                ev.append(f'<seqevent step="{step}"{chan} type="xyvalue" value="{i * 13 - 400}" value2="{i * 17}"/>')
            elif k == 4:
                ev.append(f'<seqevent step="{step}"{chan} type="steplen" value="{i % 9}"/>')
            else:
                ev.append(f'<seqevent step="{step}"{chan} type="sceneitem" silayer="{i % 4}" cond="{i % 3}"/>')
        return "".join(ev)
    for col in range(5):
        for row in range(4):
            for sub in range(4):
                s = (col * 4 + row) * 4 + sub
                o.append(f'<cell row="{row}" column="{col}" layer="1" seqsublayer="{sub}" name="{q(f"Seq {ENT} {s}")}" type="noteseq">')
                o.append("<params/>")
                o.append(f'<modsource dest="gaindb" src="lfo{s % 3 + 1}" slot="0" amount="{s * 10}"/>')
                o.append(f"<sequence>{events(48 + s % 40, s)}</sequence></cell>")
    for i in range(32):
        o.append(f'<cell row="{i}" column="0" layer="2" seqsublayer="0" name="{q(f"Part {ENT} {i}")}" type="section"><params/>'
                 f"<sequence>{events(40, i + 1000)}</sequence></cell>")
    for i, t in enumerate(("delay", "reverb", "eq", "null", "null")):
        o.append(f'<cell row="{i}" layer="3" type="{t}"><params/></cell>')
    for i in range(0x240):
        o.append(f'<cell row="{i}" filename="{q(f"Multi {ENT} {i:03d}.wav")}" type="asset"><params/></cell>')
    o.append('<cell type="song"><params globtempo="1234" swing="57"/></cell>')
    o += ["</session>", "</document>"]
    return "\n".join(o).encode()


def poke(r):
    """Reach the writer's branches that a loaded project rarely does, by editing the loaded data directly."""
    e = r.e
    reg = e.r32(0x2401F4FC) & 0xFFFFFFFF

    names = [e.cstr(e.r32(reg + i * 0x1C + 0x18) & 0xFFFFFFFF) if e.r16(reg + i * 0x1C) else None for i in range(500)]
    same = [(a, b) for a in range(500) for b in range(a + 1, 500) if names[a] and names[a] == names[b]]

    def store(cell, entries):
        cap = e.r16(cell + 0xC)
        assert len(entries) <= cap, (len(entries), cap)
        en = e.r32(cell + 4) & 0xFFFFFFFF
        for i, (pid, v) in enumerate(entries):
            e.uc.mem_write(en + i * 8, struct.pack("<HHi", pid, 0, v))
        e.uc.mem_write(cell + 0xA, struct.pack("<H", len(entries)))

    def entries(cell):
        en, n = e.r32(cell + 4) & 0xFFFFFFFF, e.r16(cell + 0xA)
        return [struct.unpack("<HHi", bytes(e.uc.mem_read(en + i * 8, 8)))[::2] for i in range(n)]
    pad0, pad1, pad2 = DATA, DATA + 0xF0, DATA + 0x1E0
    a, b = same[0]
    c, d = same[1]
    base = entries(pad0)[:40]
    # a repeated id (one attribute: first place, last value), two ids sharing one name, an id with no name,
    # an id past the registry, a negative and the most negative value
    store(pad0, base[:5] + [(a, 11), (base[1][0], -2147483648), (b, 22), (499, 5), (600, 6), (c, -7)]
          + base[5:20] + [(d, 99), (a, 33), (base[3][0], -1)] + base[20:])
    # the two string-valued settings: names that resolve, codes that do not, and a repeat of each
    store(pad1, [(0xF8, 0), (0xF9, 3), (0xF8, 1)] + entries(pad1)[:30] + [(0xF9, 200), (0xF8, 7), (0xF9, 9)])
    # the store ends at the first id 0, even before its count
    ent = entries(pad2)
    store(pad2, ent[:10] + [(0, 5)] + ent[10:])
    # events: every type byte the switch knows and some it does not, extremes of every field
    seq = DATA + 0x3C0
    lst = seq + 0x18
    hdl, cnt = e.r32(lst) & 0xFFFFFFFF, e.r32(lst + 4)
    pool = e.r32(e.r32(lst + 0x10) & 0xFFFFFFFF) & 0xFFFFFFFF
    kinds = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 255]
    for i in range(min(cnt, 48)):
        slot = e.r16(hdl + i * 2) & 0x3FFF
        ev = struct.pack("<BBHIIIHHHH", kinds[i % len(kinds)], (0, 1, 134, 255)[i % 4], (0, 1, 0xFFFF, 300)[i % 4],
                         (0, 959, 960, 0xFFFFFFFF, 0x80000000)[i % 5], (0, 959, 960, 0xFFFFFFFF, 0x7FFFFFFF)[i % 5],
                         0xDEADBEEF, (0, 127, 0xFFFF)[i % 3], (0, 1, 0x8000, 0xFFFF)[i % 4],
                         (0, 0xFFFF)[i % 2], (0, 3, 0xFFFF)[i % 3])
        e.uc.mem_write(pool + slot * 0x18, ev)
    # modulation: sources with the CC bit and stray high bits, codes with no name, extremes of slot and amount
    for cell in (pad0, DATA + 0x1780):
        ml, mn = e.r32(cell + 0x10) & 0xFFFFFFFF, e.r16(cell + 0x14)
        for i in range(mn):
            e.uc.mem_write(ml + i * 12, struct.pack("<iHHhH", (-2147483648, -1, 0, 2147483647)[i % 4],
                                                    (0x8000, 0xFFFF, 0x1F, 0x77, 0, 0x8ABC)[i % 6],
                                                    (0, 7, 499, 600, 0xFFFF)[i % 5], (-32768, -1, 0, 32767)[i % 4], 0))
    # a sequence without a name (stock skips the attribute)
    return len(same), same[:2]


# --------------------------------------------------------------------------------------------------- the suites
img = open(IMAGE, "rb").read()
r = Rig()
SAVEXML = r.e.sym["savexml"]
to_us = calls_to(img, SAVEXML)
check("the five call sites of stock's preset writer now call savexml, and nothing else does",
      sorted(to_us) == sorted(SITES), [hex(a) for a in to_us])
check("nothing in the image calls FUN_08096754 any more", calls_to(img, STOCK_WRITER) == [],
      [hex(a) for a in calls_to(img, STOCK_WRITER)])

if PRESET:
    xml = open(PRESET, "rb").read()
else:                                                   # no real preset given: the synthetic heavy project stands in
    print("(SAVEXML_PRESET unset: the 'sample preset' checks run on the synthetic heavy project; the 0xFC000 cap check is skipped)")
    xml = heavy_xml()
    r = Rig(heap=0x2000000)
check("the sample preset loads", r.load(xml) == 1)
new = r.save(SAVEXML)
nfr, nst = list(r.frags), list(r.stamps)
old = r.save(STOCK_WRITER)
ofr, ost = list(r.frags), list(r.stamps)
check(f"sample preset: savexml's preset.xml is stock's, byte for byte ({len(new[1])} bytes, "
      f"{new[1].count(b'<modsource')} modsources, {new[1].count(b'<seqevent')} events)",
      new[0] == old[0] == 1 and new[1] == old[1] and len(new[1]) > 150000, (new[0], old[0], len(new[1]), len(old[1])))
check(f"sample preset: and so is every f_write ({len(nfr)} fragments)", nfr == ofr, (len(nfr), len(ofr)))
check(f"sample preset: heap taken by the save: stock {old[2]:,} B, savexml {new[2]} B",
      new[2] == 0 and old[2] > 900_000, (new[2], old[2]))
check(f"sample preset: stack used by the write: stock {old[3]} B, savexml {new[3]} B (no deeper than stock)",
      new[3] <= old[3], (new[3], old[3]))
elements = new[1].count(b"<") - new[1].count(b"</") - 1    # opening tags, less the declaration
check(f"watchdog: stock's write never stamps the disk task's word; savexml stamps it at each of the {elements} "
      f"elements (at most {max(b - a for a, b in zip(nst, nst[1:] + [len(new[1])])):,} bytes between stamps)",
      ost == [] and len(nst) == elements, (len(ost), len(nst), elements))
ref_out = new[1]

r.e.w32(WDG, 0)
r.e.w32(WDG + 8, 0x1234)
r.save(SAVEXML)
check("watchdog: the stamp savexml writes is the supervisor's counter, as FUN_080469c4 is meant to",
      r.e.r32(WDG) == 0x1234 and r.e.r32(WDG + 4) == 0, (hex(r.e.r32(WDG)), hex(r.e.r32(WDG + 4))))

# error paths, as FUN_08097148
for label, setup in (("no FIL", lambda: r.e.w32(FILPTR, 0)),
                     ("f_open fails (FR_DISK_ERR)", lambda: setattr(r, "open_result", 1)),
                     ("f_open fails (FR_NO_PATH)", lambda: setattr(r, "open_result", 5))):
    got = []
    for fn in (STOCK_WRITER, SAVEXML):
        setup()
        res = r.save(fn)
        got.append((res[0], res[1], r.opens, r.closes, r.printfs))
        r.e.w32(FILPTR, FIL)
        r.open_result = 0
    check(f"error: {label}: both return 0 having written and closed nothing, with the same message "
          f"({got[1][4]})", got[0] == got[1] and got[0][0] == 0 and got[0][1] == b"" and got[0][3] == 0, got)
for at in (0, 150):
    got = []
    for fn in (STOCK_WRITER, SAVEXML):
        r.write_fail_from = at
        res = r.save(fn)
        got.append((res[0], list(r.frags), r.closes))
        r.write_fail_from = None
    check(f"error: f_write failing from fragment {at}: both return 1, attempt the same {len(got[0][1])} writes and "
          f"close once", got[0] == got[1] and got[0][0] == 1 and got[0][2] == 1, (got[0][0], got[1][0], len(got[0][1]),
                                                                                  len(got[1][1]), got[0][2], got[1][2]))

# the heap beta 2 hung at (needs a real preset small enough to load under it)
if PRESET:
    r = Rig(heap=CAP_BETA2)
    check(f"heap capped at {CAP_BETA2:#x} (beta 2's hang): the sample preset still loads", r.load(xml) == 1)
    new = r.save(SAVEXML)
    old = r.save(STOCK_WRITER)
    check("heap capped at 0xFC000: savexml writes the same preset.xml, stock's writer runs into `b .` (0x0808A37C)",
          new[0] == 1 and new[1] == ref_out and old[0] == "CRASH" and old[1] == b"", (new[0], len(new[1]), old[0]))

# a heavy project, through the real loader
hx = heavy_xml()
r = Rig(heap=0x2000000)
check(f"heavy project ({len(hx):,} B of xml) loads", r.load(hx) == 1)
new = r.save(SAVEXML)
nfr = list(r.frags)
old = r.save(STOCK_WRITER)
c = [new[1].count(k) for k in (b"<slice ", b"<modsource", b"<seqevent", b'type="asset"', b"&amp;", b"midicc")]
check(f"heavy project: byte-identical ({len(new[1]):,} B; {c[0]} slices, {c[1]} modsources, {c[2]} events, "
      f"{c[3]} assets, {c[4]} escaped &, {c[5]} CC sources)",
      new[0] == old[0] == 1 and new[1] == old[1] and nfr == list(r.frags) and c[0] == 20 * 128 and c[3] == 0x240
      and c[5] > 0, (len(new[1]), len(old[1]), c))
check(f"heavy project: heap taken by the save: stock {old[2]:,} B, savexml {new[2]} B", new[2] == 0, new[2])
check(f"heavy project: stack used: stock {old[3]} B, savexml {new[3]} B", new[3] <= old[3], (new[3], old[3]))
for k in (b'type="note"', b'type="auto"', b'type="xyvalue"', b'type="steplen"', b'type="sceneitem"', b"cond=",
          b"velocity=", b"lencount=", b"chan=", b"mchan=", b"name="):
    check(f"heavy project carries {k.decode()}", k in new[1])

nsame, pairs = poke(r)
new = r.save(SAVEXML)
nfr = list(r.frags)
old = r.save(STOCK_WRITER)
check(f"poked project (repeated ids, {nsame} names two ids share e.g. {pairs}, unnamed ids, id 0 mid-store, both "
      f"string settings, every event type, CC sources, extremes): byte-identical ({len(new[1]):,} B)",
      new[0] == old[0] == 1 and new[1] == old[1] and nfr == list(r.frags) and nsame > 0, (len(new[1]), len(old[1])))
first = new[1].split(b"<params ", 1)[1].split(b"/>", 1)[0]
check(f"poked project: a name set three times on one <params> is ONE attribute with the last value, as tinyxml2 "
      f"keeps it (feedback=\"33\")", first.count(b" feedback=") == 1 and b' feedback="33"' in first, first[:200])
for k in (b"inputiocon=", b"outputiocon=", b"-2147483648", b"4294967295", b'step="4473924"'):
    check(f"poked project reaches {k.decode()}", k in new[1])

print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
