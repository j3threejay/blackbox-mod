"""Query the analysed Ghidra project.

  gq.py xref <string>        functions referencing strings containing <string>
  gq.py dec <addr|name> ...  decompile functions
  gq.py sref <str> ...       functions whose literal pools point at the exact string
  gq.py fn <addr> ...        function containing each address
  gq.py callers <addr|name>  functions calling it
  gq.py callees <addr|name>  functions it calls
  gq.py refs <addr>          all references to an address (data or code)
  gq.py consts <hex>         instructions using a scalar constant
  gq.py rename <addr> <name> rename a function
"""
import os
import re
import sys

os.environ.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
import pyghidra

pyghidra.start(install_dir=os.environ.get("GHIDRA_INSTALL_DIR", "/opt/homebrew/Cellar/ghidra/12.1.4/libexec"))

from ghidra.base.project import GhidraProject
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import TaskMonitor
from ghidra.program.model.scalar import Scalar

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = os.environ.get("GQ_PROG", "BLACKBOX-3.1.9")
project = GhidraProject.openProject(os.environ.get("GHIDRA_PROJ", ROOT), NAME, False)
program = project.openProgram("/", NAME, False)
fm = program.getFunctionManager()
listing = program.getListing()
refman = program.getReferenceManager()
space = program.getAddressFactory().getDefaultAddressSpace()


def addr(s):
    if s.startswith("0x") or all(c in "0123456789abcdefABCDEF" for c in s):
        return space.getAddress(int(s, 16))
    fs = [f for f in fm.getFunctions(True) if f.getName() == s]
    return fs[0].getEntryPoint()


def func(s):
    a = addr(s)
    return fm.getFunctionContaining(a) or fm.getFunctionAt(a)


def label(f):
    return f"{f.getEntryPoint()} {f.getName()}" if f else "?"


FW = open(os.path.join(os.path.dirname(ROOT), "firmware", NAME + ".bin"), "rb").read()
BASE = 0x08040000


def flash_word(a):
    o = a - BASE
    return int.from_bytes(FW[o:o + 4], "little") if 0 <= o <= len(FW) - 4 else None


def flash_str(a):
    o = a - BASE
    if not 0 <= o < len(FW):
        return None
    e = FW.find(b"\0", o)
    s = FW[o:e]
    return s.decode() if 2 <= len(s) < 80 and all(32 <= c < 127 for c in s) else None


def annotate(c):
    """Append the literal-pool value (and the string it points at) to every DAT_ reference."""
    def sub(m):
        v = flash_word(int(m.group(1), 16))
        if v is None:
            return m.group(0)
        st = flash_str(v)
        return f'{m.group(0)}/*{v:#x}{" " + repr(st) if st else ""}*/'
    return re.sub(r"DAT_([0-9a-f]{8})", sub, c)


def dec(f):
    d = DecompInterface()
    d.openProgram(program)
    r = d.decompileFunction(f, 120, TaskMonitor.DUMMY)
    return annotate(r.getDecompiledFunction().getC()) if r.decompileCompleted() else r.getErrorMessage()


cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "xref":
    needle = args[0].lower()
    for data in listing.getDefinedData(True):
        v = data.getValue()
        if isinstance(v, str) and needle in v.lower():
            fns = {label(fm.getFunctionContaining(r.getFromAddress())) for r in refman.getReferencesTo(data.getAddress())}
            print(f"{data.getAddress()} {v!r:.60} <- {sorted(fns)}")
elif cmd == "dec":
    for a in args:
        f = func(a)
        print(f"// ===== {label(f)}\n{dec(f)}")
elif cmd == "sref":
    # literal-pool pointers to exact NUL-terminated strings, with the function each pool sits in
    import struct
    for want in args:
        i = FW.find(b"\0" + want.encode() + b"\0")
        while i != -1:
            a = BASE + i + 1
            j = FW.find(struct.pack("<I", a))
            while j != -1:
                pa = space.getAddress(BASE + j)
                f = fm.getFunctionContaining(pa) or next(iter(fm.getFunctions(pa, False)), None)
                print(f"{want!r} @{a:#x} pool {BASE + j:#x} -> {label(f)}")
                j = FW.find(struct.pack("<I", a), j + 1)
            i = FW.find(b"\0" + want.encode() + b"\0", i + 1)
elif cmd == "fn":
    for a in args:
        f = func(a) or next(iter(fm.getFunctions(addr(a), False)), None)
        print(a, label(f), "" if func(a) else "(nearest before)")
elif cmd == "callers":
    f = func(args[0])
    for c in sorted({label(fm.getFunctionContaining(r.getFromAddress())) for r in refman.getReferencesTo(f.getEntryPoint())}):
        print(c)
elif cmd == "callees":
    for c in sorted(label(x) for x in func(args[0]).getCalledFunctions(TaskMonitor.DUMMY)):
        print(c)
elif cmd == "refs":
    for r in refman.getReferencesTo(addr(args[0])):
        print(r.getFromAddress(), r.getReferenceType(), label(fm.getFunctionContaining(r.getFromAddress())))
elif cmd == "consts":
    want = int(args[0], 16)
    for ins in listing.getInstructions(True):
        for i in range(ins.getNumOperands()):
            for o in ins.getOpObjects(i):
                if isinstance(o, Scalar) and o.getUnsignedValue() == want:
                    print(ins.getAddress(), ins, label(fm.getFunctionContaining(ins.getAddress())))
elif cmd == "rename":
    from ghidra.program.model.symbol import SourceType
    tx = program.startTransaction("rename")
    func(args[0]).setName(args[1], SourceType.USER_DEFINED)
    program.endTransaction(tx, True)
    project.save(program)
project.close()
