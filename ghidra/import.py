"""Import BLACKBOX.bin into a Ghidra project as a Cortex-M7 image at 0x08040000 and auto-analyse it."""
import os
import sys

import pyghidra

GHIDRA = os.environ.get("GHIDRA_INSTALL_DIR", "/opt/homebrew/Cellar/ghidra/12.1.4/libexec")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, "firmware", sys.argv[1] if len(sys.argv) > 1 else "BLACKBOX-3.1.9.bin")
BASE = 0x08040000

# STM32H743 RAM + peripheral regions, uninitialised, so absolute refs resolve
RAM = [
    ("ITCM", 0x00000000, 0x10000),
    ("DTCM", 0x20000000, 0x20000),
    ("AXI_SRAM", 0x24000000, 0x80000),
    ("SRAM123", 0x30000000, 0x48000),
    ("SRAM4", 0x38000000, 0x10000),
    ("PERIPH", 0x40000000, 0x20000000),
    ("SDRAM", 0xC0000000, 0x4000000),
    ("CORE", 0xE0000000, 0x100000),
]

pyghidra.start(install_dir=GHIDRA)

from java.io import File
from ghidra.base.project import GhidraProject
from ghidra.program.util import DefaultLanguageService
from ghidra.util.task import TaskMonitor
from ghidra.program.flatapi import FlatProgramAPI
from ghidra.program.model.data import PointerDataType

proj_dir = os.environ.get("GHIDRA_PROJ", os.path.join(ROOT, "ghidra"))
name = os.path.splitext(os.path.basename(FW))[0]
project = GhidraProject.createProject(proj_dir, name, False)
from ghidra.program.model.lang import LanguageID, CompilerSpecID
ls = DefaultLanguageService.getLanguageService()
lang = ls.getLanguage(LanguageID("ARM:LE:32:Cortex"))
cspec = lang.getCompilerSpecByID(CompilerSpecID("default"))

program = project.importProgram(File(FW), lang, cspec)
tx = program.startTransaction("setup")
mem = program.getMemory()
blk = mem.getBlocks()[0]
if blk.getStart().getOffset() != BASE:
    mem.moveBlock(blk, program.getAddressFactory().getDefaultAddressSpace().getAddress(BASE), TaskMonitor.DUMMY)
blk.setName("FLASH")
blk.setExecute(True)
blk.setWrite(False)
space = program.getAddressFactory().getDefaultAddressSpace()
for n, start, size in RAM:
    b = mem.createUninitializedBlock(n, space.getAddress(start), size, False)
    b.setRead(True); b.setWrite(True); b.setExecute(n in ("ITCM", "AXI_SRAM", "DTCM"))
    if n in ("PERIPH", "CORE"):
        b.setVolatile(True)

# vector table: SP + 16 core vectors + 150 STM32H7 IRQs; mark handlers as functions
api = FlatProgramAPI(program)
for i in range(166):
    a = space.getAddress(BASE + 4 * i)
    api.createData(a, PointerDataType())
    v = mem.getInt(a) & 0xFFFFFFFF
    if i > 0 and v & 1 and BASE <= v < BASE + blk.getSize():
        t = space.getAddress(v & ~1)
        api.createFunction(t, "Reset_Handler" if i == 1 else f"vec_{i}")
program.endTransaction(tx, True)

project.analyze(program)
project.saveAs(program, "/", name, True)
fm = program.getFunctionManager()
print("functions:", fm.getFunctionCount())
project.close()
