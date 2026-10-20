"""Decompile every function into ghidra/out_all.c (one-time, for grep)."""
import os
os.environ.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
import pyghidra
pyghidra.start(install_dir=os.environ.get("GHIDRA_INSTALL_DIR", "/opt/homebrew/Cellar/ghidra/12.1.4/libexec"))
from ghidra.base.project import GhidraProject
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import TaskMonitor
R = os.path.dirname(os.path.abspath(__file__))
p = GhidraProject.openProject(os.environ.get("GHIDRA_PROJ", R), "BLACKBOX-3.1.9", False)
prog = p.openProgram("/", "BLACKBOX-3.1.9", False)
d = DecompInterface(); d.openProgram(prog)
with open(os.path.join(R, "out_all.c"), "w") as f:
    for fn in prog.getFunctionManager().getFunctions(True):
        r = d.decompileFunction(fn, 60, TaskMonitor.DUMMY)
        if r.decompileCompleted():
            f.write(f"// ===== {fn.getEntryPoint()} {fn.getName()}\n{r.getDecompiledFunction().getC()}\n")
p.close()
