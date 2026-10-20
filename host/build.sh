#!/bin/sh
# Compile the firmware-free DSP cores for the host: host/libdsp.dylib, driven from Python (host/dsp.py) to render audio.
# clang on the Mac; any C compiler elsewhere (CC=gcc ./build.sh). The file keeps its .dylib name: dlopen does not care.
set -e
cd "$(dirname "$0")"
${CC:-$(command -v clang || command -v cc)} -O2 -shared -fPIC -Wno-unknown-pragmas -Wno-ignored-pragmas -o libdsp.dylib $(ls ../src/smash.c ../src/confetti.c ../src/prism.c ../src/rev4.c ../src/s950.c 2>/dev/null)
