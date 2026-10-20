#!/bin/sh
# Build the cave, patch the image with every set, run every test suite; prints only failures and the image's sha.
cd "$(dirname "$0")"
./build.sh || exit 1
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave | tail -1
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3               # needs unicorn, capstone and numpy
[ -f host/libdsp.dylib ] || sh host/build.sh     # the host build of the DSP (clang, or CC / cc: host/build.sh), which several suites hold the firmware's against
bad=0
for t in test_*.py; do
  "$PY" "$t" > "out/$t.log" 2>&1 || { bad=$((bad + 1)); echo "FAILED $t"; grep -v '^PASS' "out/$t.log" | head -20; }
done
echo "$(ls test_*.py | wc -l | tr -d ' ') suites, $bad failed"
[ "$bad" -eq 0 ]                         # the exit status says it too, for scripts and hooks
