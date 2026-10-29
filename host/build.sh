#!/bin/sh
# Compile the firmware-free DSP cores for the Mac: host/libdsp.dylib, driven from Python (host/dsp.py) to render audio.
set -e
cd "$(dirname "$0")"
clang -O2 -shared -fPIC -Wno-unknown-pragmas -Wno-ignored-pragmas -o libdsp.dylib $(ls ../src/smash.c ../src/confetti.c ../src/prism.c ../src/rev4.c ../src/s950.c 2>/dev/null)
# Charles Vestal's TAPESCAM as published, the reference test_tapescam.py holds the firmware port against
clang -O2 -shared -fPIC -w -o libtsref.dylib tapescam_ref/ref.c
# ChopShop's attack scan + placement (chop_dsp.c, chop.c) for host/chop_check.py
clang -O2 -shared -fPIC -DSTR_HOST -Wno-unknown-pragmas -Wno-ignored-pragmas -Wno-incompatible-library-redeclaration -o libchop.dylib chop_host.c ../src/chop_dsp.c ../src/chop.c
