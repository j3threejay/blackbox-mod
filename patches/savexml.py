"""Save / Save As / Pack write preset.xml by streaming (src/savexml.c) instead of through stock's document build.

Stock's five calls to the preset writer FUN_08096754 (all in the disk task, under the file-command dispatcher
FUN_08092f5c) go to savexml, which takes the same arguments and returns what stock would. Applied with `cave`
(patches/cave.py pulls these in), so the build command does not change."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))

WRITER = 0x08096754
SITES = (
    0x08091968,   # FUN_080918c8: a preset that loaded from its fallback file is written back as preset.xml
    0x080921F2,   # FUN_08091e80: Save / Save As (one branch)
    0x08092290,   # FUN_08091e80: Save / Save As (the other)
    0x08092750,   # FUN_080922e4: Pack
    0x08092E14,   # FUN_08092c58: file command 0x15
)

PATCHES = [(at, bl(at, WRITER), bl(at, sym["savexml"])) for at in SITES]
