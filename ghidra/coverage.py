import os
os.environ.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
import pyghidra
pyghidra.start(install_dir=os.environ.get("GHIDRA_INSTALL_DIR", "/opt/homebrew/Cellar/ghidra/12.1.4/libexec"))
from ghidra.base.project import GhidraProject
R=os.path.dirname(os.path.abspath(__file__))
p=GhidraProject.openProject(os.environ.get("GHIDRA_PROJ", R),"BLACKBOX-3.1.9",False); prog=p.openProgram("/","BLACKBOX-3.1.9",False)
fm=prog.getFunctionManager(); L=prog.getListing()
buckets={}
for f in fm.getFunctions(True):
    o=f.getEntryPoint().getOffset()
    buckets[(o>>16)]=buckets.get(o>>16,0)+1
for k in sorted(buckets): print(hex(k<<16),buckets[k])
n=sum(1 for _ in L.getInstructions(True)); print("instructions",n)
p.close()
