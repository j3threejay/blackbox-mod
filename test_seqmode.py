"""Sequence mode switch: switching back across PADS restores the notes (src/seqmode.c) under Unicorn.

Real firmware runs for: the app's set-parameter handler FUN_0809fa50 from its entry with param 0xb7 (so the hooks
are reached from their real call sites), the cell lookup, the settings read / write, stock's backup into the UNDO
buffer (FUN_08098254 -> FUN_08094bb2 -> the note copy FUN_08094b72 / list read / sorted insert), the list clear,
the per-layer send FUN_080985a0 (which empties the engine's copy of each layer and sends it every note in the
app's list - that is how restored notes reach the engine) and the queue post.
Stubbed: the engine's commands FUN_0804c59c (parameter), FUN_0804c7e8 (drop a layer's notes) and FUN_0804c798 (add
one note), all recorded; the stop-all FUN_0809acec (recorded).
NOT run: the piano roll's mode button and the view refresh it gets (message 0x66), the engine itself, the preset
load paths themselves
(only that seqmode_forget forgets and still stops every cell), a pool too full to take the copy.
"""
import random
import struct
import sys

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin",
        "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)

APP = 0x24020088
UNDO, UNDO_ID = APP + 0xE868, APP + 0xE91C
STATE = 0x388006F4
POOLOBJ, POOL = 0x24040000, 0x24041000
HANDLES, SETTINGS, REFS = 0x24050000, 0x24058000, 0x2405C000
PADS, KEYS, MIDI = 0, 1, 2
IDS = (0xB7, 0xC0, 0x85, 0x86, 0xB9)                       # mode, layer, Step Len, Step Count, Play Pad

engine, stops, sent = [], [], {}


def engine_clear():
    sent[e.arg(3) & 0xFFFF] = []                           # the layer, as FUN_080985a0 passes it


def engine_note():
    from unicorn.arm_const import UC_ARM_REG_SP
    layer = e.r32(e.uc.reg_read(UC_ARM_REG_SP)) & 0xFF
    ev = struct.unpack("<BBHIIIHHI", bytes(e.uc.mem_read(e.arg(2), 0x18)))
    sent.setdefault(layer, []).append((ev[3], ev[4], ev[6], ev[7], ev[5]))


e.stub(0x0804C59C, lambda: engine.append((e.arg(1), e.arg(2), e.arg(3))))
e.stub(0x0804C7E8, engine_clear)                           # the engine: drop this layer's notes
e.stub(0x0804C798, engine_note)                            # the engine: add one note
e.stub(0x0809ACEC, lambda: stops.append(e.arg(0)))


def cell_id(row, col):
    return 0x100 | row << 4 | col


def layer_addr(row, col, layer):
    return APP + row * 0x370 + col * 0xB0 + layer * 0x2C + 0x1C00


LAYERS = [(r, c, l) for r in range(4) for c in range(5) for l in range(4)]


def reset():
    engine.clear()
    stops.clear()
    sent.clear()
    e.uc.mem_write(APP, bytes(0xF000))
    e.uc.mem_write(POOL, bytes(0x18 * 2000))
    e.uc.mem_write(POOLOBJ, struct.pack("<IIHH", POOL, 0, 0, 2000))
    e.uc.mem_write(STATE, bytes(12))
    stores = [layer_addr(*k) for k in LAYERS] + [UNDO + 0x2C * l for l in range(4)]
    for n, store in enumerate(stores):
        entries = SETTINGS + n * 0x30
        e.uc.mem_write(entries, b"".join(struct.pack("<HHI", i, 0, 0) for i in IDS))
        e.uc.mem_write(store + 4, struct.pack("<IHH", entries, len(IDS), len(IDS)))
        e.uc.mem_write(store + 0x18, struct.pack("<IIIII", HANDLES + n * 0x400, 0, 0, 0, POOLOBJ))
    for l in range(4):                                     # each layer knows its own pattern letter
        for r, c, ll in LAYERS:
            if ll == l:
                set_param(layer_addr(r, c, l), 0xC0, l)


def set_param(store, pid, v):
    entries = e.r32(store + 4)
    for k in range(e.r16(store + 10)):
        if e.r16(entries + 8 * k) == pid:
            e.w32(entries + 8 * k + 4, v)
            return
    raise KeyError(pid)


def get_param(store, pid):
    entries = e.r32(store + 4)
    for k in range(e.r16(store + 10)):
        if e.r16(entries + 8 * k) == pid:
            return e.r32(entries + 8 * k + 4)
    raise KeyError(pid)


def ref(row, col):
    at = REFS + (row * 5 + col) * 8
    e.uc.mem_write(at, struct.pack("<IHH", 0x080CFBA4, cell_id(row, col), 0))
    return at


def add_notes(store, notes):
    """notes: (start, length, pitch, velocity, id), added through the firmware's own sorted insert."""
    ev = 0x2405F000
    for start, length, pitch, vel, nid in notes:
        e.uc.mem_write(ev, struct.pack("<BBHIIIHHI", 1, 0, 0, start, length, nid, pitch, vel, 0))
        e.call(0x08063B38, store + 0x18, ev)


def notes(store):
    lst = store + 0x18
    out = []
    for k in range(e.r32(lst + 4)):
        h = e.r16(e.r32(lst) + 2 * k) & 0x3FFF
        ev = struct.unpack("<BBHIIIHHI", bytes(e.uc.mem_read(POOL + 0x18 * h, 0x18)))
        out.append((ev[3], ev[4], ev[6], ev[7], ev[5]))
    return out


def cell_notes(row, col):
    return [notes(layer_addr(row, col, l)) for l in range(4)]


def undo_notes():
    return [notes(UNDO + 0x2C * l) for l in range(4)]


def switch(row, col, mode, loading=0):
    e.w32(STACK, loading)                                  # fifth argument, on the stack
    e.call(0x0809FA50, APP, ref(row, col), 0xB7, mode)


def mode_of(row, col):
    return get_param(layer_addr(row, col, 0), 0xB7)


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


rng = random.Random(14)
KEYS_NOTES = [[(rng.randrange(0, 3840, 10), rng.randrange(60, 900), rng.randrange(36, 84), rng.randrange(1, 128),
                1000 * l + k + 1) for k in range(n)] for l, n in enumerate((12, 0, 5, 30))]
PADS_NOTES = [[(240 * k, 120, k % 16, 100, 5000 + k) for k in range(8)], [], [], []]
R, C = 3, 1                                                # cell "14A"-ish: any sequence cell


def fill(row, col, layers):
    for l, ns in enumerate(layers):
        add_notes(layer_addr(row, col, l), ns)


def sort(layers):
    return [sorted(ns) for ns in layers]


# --- stock behaviour kept: KEYS -> PADS clears, and backs the cell up for UNDO ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
before = cell_notes(R, C)
check("setup: notes in all patterns that have them", [len(x) for x in before] == [12, 0, 5, 30], str(before))
switch(R, C, PADS)
check("KEYS -> PADS: the cell is cleared (stock)", cell_notes(R, C) == [[], [], [], []])
check("KEYS -> PADS: the mode is PADS", mode_of(R, C) == PADS)
check("KEYS -> PADS: the engine's copy is emptied too", sorted(sent) == [0, 1, 2, 3] and not any(sent.values()))
check("KEYS -> PADS: stock backed the cell up into the UNDO buffer", undo_notes() == before
      and e.r16(UNDO_ID) == cell_id(R, C) and get_param(UNDO, 0xB7) == KEYS)
check("the tag names this cell", e.r32(STATE) & 0xFFFFFFFF == 0x534D0000 | cell_id(R, C))

# --- the feature: PADS -> KEYS on the still-empty cell brings them back ---
sent.clear()
switch(R, C, KEYS)
check("PADS -> KEYS: every note of every pattern is back", sort(cell_notes(R, C)) == sort(before),
      str([len(x) for x in cell_notes(R, C)]))
check("PADS -> KEYS: the lists are sorted the firmware's way (sorted insert)",
      all([n[0] for n in ns] == sorted(n[0] for n in ns) for ns in cell_notes(R, C)))
check("PADS -> KEYS: the mode is KEYS", mode_of(R, C) == KEYS)
check("PADS -> KEYS: the UNDO buffer is left as it was", undo_notes() == before and e.r16(UNDO_ID) == cell_id(R, C))
check("the other settings are not touched (Play Pad, Step Len)", get_param(layer_addr(R, C, 0), 0xB9) == 0)
check("no restore left pending", e.r32(STATE + 4) == 0)
check("the engine was sent exactly the restored notes, layer by layer (stock's own send after the switch)",
      [sorted(sent.get(l, [])) for l in range(4)] == sort(before), str({k: len(v) for k, v in sent.items()}))

# --- round trip again: KEYS -> PADS -> KEYS ---
switch(R, C, PADS)
switch(R, C, KEYS)
check("a second round trip restores again", sort(cell_notes(R, C)) == sort(before))

# --- recording in PADS in between: nothing the user made is replaced ---
switch(R, C, PADS)
fill(R, C, PADS_NOTES)
switch(R, C, KEYS)
check("PADS with new notes -> KEYS: the cell is cleared (stock), the Keys notes do NOT come over the Pads ones",
      cell_notes(R, C) == [[], [], [], []])
check("... and the Pads notes went to the UNDO buffer", sort(undo_notes()) == sort(PADS_NOTES)
      and get_param(UNDO, 0xB7) == PADS)
switch(R, C, PADS)
check("... so switching to PADS again brings the PADS notes back", sort(cell_notes(R, C)) == sort(PADS_NOTES))

# --- KEYS <-> MIDI never crosses PADS: stock keeps the notes, the hooks are not reached ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
e.uc.mem_write(STATE, struct.pack("<II", 0x534D0000 | cell_id(R, C), 0))
switch(R, C, MIDI)
check("KEYS -> MIDI: notes kept (stock), UNDO buffer untouched", sort(cell_notes(R, C)) == sort(KEYS_NOTES)
      and undo_notes() == [[], [], [], []])
switch(R, C, PADS)
check("MIDI -> PADS: cleared, backed up", cell_notes(R, C) == [[], [], [], []]
      and sort(undo_notes()) == sort(KEYS_NOTES))
switch(R, C, MIDI)
check("PADS -> MIDI: the notes come back (MIDI is on the Keys side)", sort(cell_notes(R, C)) == sort(KEYS_NOTES))

# --- a preset load / new preset forgets it ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
switch(R, C, PADS)
e.call("seqmode_forget", APP)
check("seqmode_forget still stops every cell", stops == [APP])
switch(R, C, KEYS)
check("after a preset load, PADS -> KEYS stays empty (stock)", cell_notes(R, C) == [[], [], [], []])

# --- the UNDO buffer belongs to another cell ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
set_param(layer_addr(0, 0, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
fill(0, 0, [[(0, 100, 60, 90, 7)], [], [], []])
switch(R, C, PADS)
switch(0, 0, PADS)
switch(R, C, KEYS)
check("another cell's switch in between: the first cell stays empty (stock)", cell_notes(R, C) == [[], [], [], []])
check("... and the other cell's notes did not land in it", undo_notes()[0] == [] or e.r16(UNDO_ID) != cell_id(0, 0))

# --- REC / CLEAR on the same cell fill the buffer with its CURRENT mode: no restore ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
switch(R, C, PADS)
e.call(0x08098254, APP, ref(R, C))                         # what REC / CLEAR do first: back the PADS cell up
switch(R, C, KEYS)
check("buffer refilled from the PADS cell (REC / CLEAR): PADS -> KEYS stays empty", cell_notes(R, C) == [[], [], [], []])

# --- a load sets the mode with the fifth argument: stock, no clear, no hooks ---
reset()
set_param(layer_addr(R, C, 0), 0xB7, KEYS)
fill(R, C, KEYS_NOTES)
switch(R, C, PADS, loading=1)
check("loading (fifth argument): mode set, notes kept, nothing backed up", mode_of(R, C) == PADS
      and sort(cell_notes(R, C)) == sort(KEYS_NOTES) and undo_notes() == [[], [], [], []])

# --- garbage in backup SRAM (it survives restarts and reflashes) ---
for trial in range(200):
    reset()
    junk = rng.randrange(1 << 32)
    tag = rng.choice([junk, 0x534D0000 | cell_id(R, C)])
    e.uc.mem_write(STATE, struct.pack("<III", tag, rng.choice([0, junk, layer_addr(R, C, 0)]), junk))
    set_param(layer_addr(R, C, 0), 0xB7, PADS)
    switch(R, C, KEYS)                                     # an empty cell, the UNDO buffer empty as after a boot
    if cell_notes(R, C) != [[], [], [], []] or mode_of(R, C) != KEYS:
        check(f"garbage state {trial}: an empty cell stays empty", False, hex(tag))
        break
else:
    check("garbage in backup SRAM (200 states) never puts anything in a cell after a boot", True)
for trial in range(200):
    reset()
    junk = rng.randrange(1 << 32)
    e.uc.mem_write(STATE, struct.pack("<III", rng.choice([junk, 0x534D0000 | cell_id(R, C)]), junk, junk))
    set_param(layer_addr(R, C, 0), 0xB7, KEYS)
    fill(R, C, KEYS_NOTES)
    switch(R, C, PADS)
    if cell_notes(R, C) != [[], [], [], []] or sort(undo_notes()) != sort(KEYS_NOTES):
        check(f"garbage state {trial}: a full cell switches the stock way", False)
        break
else:
    check("garbage in backup SRAM (200 states): a full cell is still backed up and cleared the stock way", True)

print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
