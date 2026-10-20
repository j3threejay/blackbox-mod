"""Export the analysed project as grep-able text, once: every function's instructions (with call targets) and an index.

  ghidra/export_listing.py [outdir]     -> <outdir>/listing.txt, <outdir>/functions.tsv
Default outdir: $GHIDRA_OUT, else ghidra/. Like out_all.c, the output is 1010music's code: keep it out of git.
"""
import os
import sys

if "JAVA_HOME" not in os.environ and os.path.isdir("/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"):
    os.environ["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
import pyghidra

pyghidra.start(install_dir=os.environ.get("GHIDRA_INSTALL_DIR", "/opt/homebrew/Cellar/ghidra/12.1.4/libexec"))
from ghidra.base.project import GhidraProject

R = os.path.dirname(os.path.abspath(__file__))
PROJ = os.environ.get("GHIDRA_PROJ", R)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GHIDRA_OUT", R)
NAME = os.environ.get("GQ_PROG", "BLACKBOX-3.1.9")
os.makedirs(OUT, exist_ok=True)
p = GhidraProject.openProject(PROJ, NAME, False)
prog = p.openProgram("/", NAME, True)
fm = prog.getFunctionManager()
listing = prog.getListing()
refman = prog.getReferenceManager()
with open(os.path.join(OUT, "listing.txt"), "w") as lf, open(os.path.join(OUT, "functions.tsv"), "w") as ff:
    ff.write("entry\tname\tsize\tcallers\tcallees\n")
    for fn in fm.getFunctions(True):
        body = fn.getBody()
        callers = {c.getEntryPoint().getOffset() for c in fn.getCallingFunctions(None)}
        callees = {c.getEntryPoint().getOffset() for c in fn.getCalledFunctions(None)}
        ff.write(f"0x{fn.getEntryPoint().getOffset():08x}\t{fn.getName()}\t{body.getNumAddresses()}\t{len(callers)}\t{len(callees)}\n")
        lf.write(f"\n=== 0x{fn.getEntryPoint().getOffset():08x} {fn.getName()}\n")
        for ins in listing.getInstructions(body, True):
            a = ins.getAddress().getOffset()
            extra = []
            for r in refman.getReferencesFrom(ins.getAddress()):
                t = r.getToAddress()
                if r.getReferenceType().isCall():
                    callee = fm.getFunctionAt(t)
                    extra.append(f"call {callee.getName() if callee else ''}@0x{t.getOffset():08x}")
                elif r.getReferenceType().isData():
                    extra.append(f"data 0x{t.getOffset():08x}")
            lf.write(f"0x{a:08x}  {ins}" + (f"   ; {' '.join(extra)}" if extra else "") + "\n")
p.close()
print("exported to", OUT)
