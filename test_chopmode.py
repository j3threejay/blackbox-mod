"""ChopShop as a pad mode (src/chopmode.c), under Unicorn.

Real firmware runs for: our wrappers, stock's settings get / set on a test store (FUN_08093e9c / FUN_08093ecc).
Stubbed: stock's set handler FUN_0809fa50 (recorded), the cell lookup, the popup value setter, the page builder and its
row add (recorded), chop_request (recorded).
NOT checked: the popup's look with 7 buttons, the pad view on a unit (research/slicer/MODE_LIST_RE.md is static).
"""
import struct
import sys

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e = Emu(IMAGE, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
img = open(IMAGE, "rb").read()
B = 0x08040000
STORE, ARR, REF = 0x24060000, 0x24060100, 0x24061000


def store(entries):
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in entries))
    e.w32(STORE + 4, ARR)
    e.uc.mem_write(STORE + 10, struct.pack("<H", len(entries)))


def get(i):
    n = e.r16(STORE + 10)
    for k in range(n):
        pid, _, v = struct.unpack("<HHi", e.uc.mem_read(ARR + 8 * k, 8))
        if pid == i:
            return v


SETS, POPUP, ROWS, REQS = [], [], [], []
e.stub(0x0809FA50, lambda: (SETS.append((e.arg(2), e.arg(3))), e.ret(7)))
e.stub(0x08098D0C, value=STORE)
e.stub(0x080BD74E, lambda: POPUP.append(e.arg(1)))
e.stub(0x08098D40, value=1)
e.stub(0x080A5038, lambda: ROWS.append((e.arg(1), e.arg(2))))
e.stub(e.sym["chop_request"] & ~1, lambda: REQS.append((e.arg(0), e.arg(1), e.arg(2), e.arg(3))))
e.uc.mem_write(REF, struct.pack("<IHH", 0x080EAF38, 2 << 4 | 1, 0))      # pad row 2 col 1 = 9

# --- the list
tbl = struct.unpack_from("<I", img, 0x0808D0E4 - B)[0]
names = []
for k in range(7):
    p = struct.unpack_from("<I", img, tbl - B + 4 * k)[0]
    o = p - B
    names.append(img[o:img.index(b"\0", o)].decode())
check(f"the Mode list: {names}", names == ["Sample", "Clip", "Slicer", "ChopShop", "Granular", "New Rec", "New Multi"], names)
check("... its count 7 (movs r1,#7 @0x0808CF0E)", img[0x0808CF0E - B:0x0808CF10 - B] == bytes.fromhex("0721"))


def pick(pos, mode_before, chop_before=0):
    store([(0x8B, mode_before), (0x14D, chop_before), (0x93, 0), (0xF4, 0)])
    SETS.clear()
    e.w32(STACK, 0x55)                            # the 5th argument, passed through
    e.call("chop_set", 0x24020088, REF, 0x8B, pos)
    return list(SETS), get(0x14D)


s, f = pick(3, 1)
check("ChopShop picked on a Clip pad: stock stores Slicer (2), the flag is on, then Launch Mode Gate (0x93 = 1), Sync on, Stretch Cyclic (0x14c = 3)",
      s == [(0x8B, 2), (0x93, 1), (0xF4, 1), (0x14C, 3)] and f == 1, (s, f))
s, f = pick(3, 2, 1)
check("ChopShop picked on a ChopShop pad: stock sees Slicer again, the defaults are not forced again", s == [(0x8B, 2)] and f == 1, (s, f))
s, f = pick(2, 2, 1)
check("Slicer picked on a ChopShop pad: Slicer, flag off", s == [(0x8B, 2)] and f == 0, (s, f))
s, f = pick(4, 2, 1)
check("position 4 (Granular) -> stored 3, flag off", s == [(0x8B, 3)] and f == 0, (s, f))
s, f = pick(6, 0)
check("position 6 (New Multi) -> stored 5", s == [(0x8B, 5)], s)
s, f = pick(1, 0)
check("position 1 (Clip) -> stored 1", s == [(0x8B, 1)], s)

# --- the popup highlight (value -> position)
VIEW = 0x24062000
for mode, chop, want in ((2, 1, 3), (2, 0, 2), (3, 0, 4), (5, 0, 6), (0, 0, 0)):
    store([(0x8B, mode), (0x14D, chop)])
    POPUP.clear()
    e.w32(0x24063000 + 4, ARR)                    # Waveform: popup - 0x23fc + 0x2370 is the view's store copy
    e.uc.mem_write(0x24063000 + 10, struct.pack("<H", 2))
    e.call("chop_show_wave", 0x24063000 - 0x2370 + 0x23FC, mode, 0, 0)
    check(f"Waveform popup: stored {mode}{' + flag' if chop else ''} highlights position {want}", POPUP == [want], POPUP)

# --- the Chop row (0x14d: 1 Off, 2..6 Beats units, 7 Find, 8 Random) and Roll: stock stores, then the chop runs


def chop_row(v, before=1, ident=0x14D):
    store([(0x8B, 2), (0x14D, before)])
    SETS.clear(); REQS.clear()
    e.uc.mem_write(STORE + 0, b"")                # the stub stores nothing: mirror stock's store write for the test
    e.stubs[0x0809FA50] = lambda: (SETS.append((e.arg(2), e.arg(3))),
                                   e.call_nested if False else None,
                                   e.ret(7))
    e.call("chop_set", 0x24020088, REF, ident, v)
    return list(SETS), list(REQS)


NAMES = ["--", "Off", "1/4", "1/2", "Beat", "2 Beats", "Bar", "Find", "Random"]
for v, want in ((4, (9, 1, 2, 0)), (2, (9, 1, 0, 0)), (7, (9, 2, 0, 64)), (8, (9, 3, 0, 64))):
    s_, r_ = chop_row(v, before=v)                # the store already holds v when chop_set reads it back
    check(f"Chop row = {NAMES[v]}: stock stores {v}, chop_request{want}", s_ == [(0x14D, v)] and r_ == [want], (s_, r_))
s_, r_ = chop_row(1, before=1)
check("Chop row = Off: stored, nothing runs", s_ == [(0x14D, 1)] and r_ == [], (s_, r_))
s_, r_ = chop_row(0, before=1)
check("Chop row turned to 0: clamped to Off (1): the row never leaves ChopShop", s_ == [(0x14D, 1)], s_)
s_, r_ = chop_row(5, before=7, ident=0x161)
check("Roll turned on a Find pad: Find again (a re-roll)", r_ == [(9, 2, 0, 64)], r_)
s_, r_ = chop_row(5, before=1, ident=0x161)
check("Roll with Chop Off: nothing", r_ == [], r_)

# --- pages
LIST = 0x24064000


def row_add_mem():                                # stock's FUN_080a5038 on the list memory: count, 12-byte entries
    lst, ident, val = e.arg(0), e.arg(1), e.arg(2)
    ROWS.append((ident, val))
    n = e.r32(lst)
    if n + 1 < 0x30:
        e.uc.mem_write(lst + 4 + 12 * n, struct.pack("<HHHHI", ident, 0, 0, 0, val))
        e.w32(lst, n + 1)


def list_ids():
    n = e.r32(LIST)
    return [struct.unpack("<H", e.uc.mem_read(LIST + 4 + 12 * i, 2))[0] for i in range(n)]


e.stub(0x080A5038, row_add_mem)
STOCK_ROWS = [0x91, 0x92, 0x93]                   # whatever stock put on the page first
for mode, chop, page, want, order in ((2, 7, 1, [(0x14D, 7), (0x161, 50), (0x162, 1)], [0x14D, 0x161, 0x162] + STOCK_ROWS),
                                      (2, 0, 1, [], STOCK_ROWS), (2, 7, 0, [], STOCK_ROWS), (1, 7, 1, [], STOCK_ROWS)):
    store([(0x8B, mode), (0x14D, chop)])
    ROWS.clear()
    e.w32(LIST, len(STOCK_ROWS))
    for i, ident in enumerate(STOCK_ROWS):
        e.uc.mem_write(LIST + 4 + 12 * i, struct.pack("<HHHHI", ident, 0, 0, 0, 0x100 + i))
    e.call("chop_pages", 0x24020088, REF, LIST, page)
    got = list_ids()
    check(f"pages: mode {mode} flag {chop} page {page}: rows added {ROWS}, page order {[hex(x) for x in got]}",
          ROWS == want and got == order, (ROWS, got))
store([(0x8B, 2), (0x14D, 7), (0x15E, 2)]); e.w32(LIST, 3)
for i, ident in enumerate(STOCK_ROWS):
    e.uc.mem_write(LIST + 4 + 12 * i, struct.pack("<HHHHI", ident, 0, 0, 0, 0x100 + i))
e.call("chop_pages", 0x24020088, REF, LIST, 1)
vals = [e.r32(LIST + 4 + 12 * i + 8) for i in range(6)]
check(f"pages: the moved rows keep their values (Tempo x2 = position 2), stock's keep theirs ({vals})",
      vals == [7, 50, 2, 0x100, 0x101, 0x102], vals)

# --- a fresh WAV header
e.unstub = getattr(e, "unstub", None)
for mode, chop, wav, want_mode, want_flag in ((2, 1, 1, 2, 1), (2, 1, 0, 2, 1), (0, 1, 2, 2, 0), (2, 0, 1, 1, 0)):
    store([(0x8B, mode), (0x14D, chop)])
    e.call("chop_header_mode", STORE, 0x8B, wav)
    check(f"WAV header says {wav} on mode {mode} flag {chop}: mode {want_mode}, flag {want_flag}",
          get(0x8B) == want_mode and get(0x14D) == want_flag, (get(0x8B), get(0x14D)))

# --- the invariant
store([(0x8B, 1), (0x14D, 1)])
e.call("chop_invariant", STORE)
check("invariant: the flag goes when the mode is not Slicer", get(0x14D) == 0)
store([(0x8B, 2), (0x14D, 1)])
e.call("chop_invariant", STORE)
check("... and stays on a Slicer", get(0x14D) == 1)

# --- the Tempo row: the code into P_SEL_BEATS, then a chop (no detection here: chop_retempo says 0 -> a request)
for pos, code, chop, want_req in ((2, 2, 5, True), (0, 1, 5, True), (1, 0, 1, False)):
    store([(0x8B, 2), (0x14D, chop), (0x15E, 0 if code else 2)])
    SETS.clear(); REQS.clear()
    e.call("chop_set", 0x24020088, REF, 0x162, pos)
    check(f"Tempo position {pos}: stored code {code}, {'a chop requested' if want_req else 'Chop Off: nothing chopped'}",
          get(0x15E) == code and (len(REQS) == 1) == want_req, (get(0x15E), REQS))
store([(0x8B, 2), (0x14D, 5), (0x15E, 2)])
e.call("chop_set", 0x24020088, REF, 0x8B, 1)
check("leaving ChopShop (Clip picked): the Tempo code is cleared (it would read as the Clip selection's Beats)",
      get(0x15E) == 0, get(0x15E))

# --- the pad view's tick (vtable slot 0 at 0x080f1284 -> chop_view_tick): the Roll row's text, then stock's tick
img_now = open(IMAGE, "rb").read()
check("the pad view's tick slot points at chop_view_tick",
      struct.unpack_from("<I", img_now, 0x080F1284 - B)[0] == (e.sym["chop_view_tick"] | 1))
VIEWT, ROWT = 0x24050000, 0x24058000
TEXTS, TICKS, FINDS = [], [], []
e.stub(0x080C3B98, lambda: TEXTS.append((e.arg(0), e.cstr(e.arg(1)))))
e.stub(0x080B9590, lambda: TICKS.append((e.arg(0), e.arg(1))))


def find_row():
    FINDS.append((e.arg(0), e.arg(1)))
    e.w32(e.arg(2), ROWT)
    e.ret(1)


e.stubs[0x080B9D8A] = find_row
for page, want_text in ((1, True), (0, False)):
    TEXTS.clear(); TICKS.clear(); FINDS.clear()
    e.uc.mem_write(VIEWT + 0xF6CC, struct.pack("<i", page))
    e.uc.mem_write(VIEWT + 0xD810, struct.pack("<IHH", 0x080EAF38, 2 << 4 | 1, 0))
    e.call("chop_view_tick", VIEWT, 0x1234)
    ok = TICKS == [(VIEWT, 0x1234)] and (TEXTS == [(ROWT + 0x38 + 0x9C, "[:.:]")] if want_text else TEXTS == [])
    check(f"view tick on page {page}: {'Roll text set at row + 0x38 + 0x9c, ' if want_text else 'no text, '}stock's tick chained",
          ok and (FINDS == [(VIEWT + 0xD50, 0x161)] if want_text else True), (TEXTS, TICKS, FINDS))

print(f"\n{fails} failure(s)" if fails else "\nall passed")
sys.exit(1 if fails else 0)
