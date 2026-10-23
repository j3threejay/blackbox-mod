#!/bin/sh
# Compile src/*.c into the code cave (bank 1) and, for the files listed in BANK2_SRCS, into flash bank 2.
# Outputs: out/cave.elf, out/cave.bin (bank 1, spliced into the image by patch.py) and out/bank2.bin (bank 2,
# programmed to 0x08100000 - see BANK2.md).
# Munchi Delay's engine is IN by default since 3.2.m - it lives in bank 2, where ~900 KB is free, so the ~7 KB it
# costs no longer competes with anything. MUNCHI=0 ./build.sh leaves it out (its Type slot then reads "---").
#
# Two steps now, compile then link, because the linker script has to place objects BY NAME and gcc's one-shot
# compile-and-link gives them random temporary names.
set -e
cd "$(dirname "$0")"
mkdir -p out out/obj

# The files that live in bank 2. Leaf code only (the DSP, and clipwin_b2's Clip Window maths): nothing the engine
# reaches before bank 2 has been checked (bank 1 calls in behind b2_live()), and nothing holding state that bank 1 needs
# at boot.
BANK2_SRCS="prism confetti insert_dsp rev4 clipwin_b2"
# BANK 2 IS FOR LEAF DSP ONLY. A function the firmware reaches through a patched call site must stay in bank 1,
# or a bad bank 2 faults before anything can check it - which is how 3.2.m's first cut would have boot-looped.
# munchi.o holds munchi_process, munchi_register, munchi_list and fx_screen_msg, all hooks, so it stays in bank 1.
# Splitting Munchi's engine out into its own translation unit would let the engine go up; not done yet.
BANK2_OBJS=""

# One id for both banks in a build, so bank 1 can tell a matching bank 2 from a stale one. It is a hash of the
# bank 2 sources and the flags, NOT a timestamp: identical code has to give an identical id, or reflashing an
# older image would need bank 2 reprogrammed even though the payload up there is already right.
B2_ID=$(for b in $BANK2_SRCS; do cat "src/$b.c"; done | cat - src/b2head.c | shasum -a 256 | cut -c1-8 | awk '{printf "0x%s", $1}')

CFLAGS="-mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib -fno-builtin -Wall -Wextra -Werror -DB2_ID=$B2_ID -DB2LOAD_WRITE=${B2LOAD_WRITE:-1}"

# The card loader (src/b2load.c) programs bank 2 from the card file: proven on the test unit with 3.2.z, 2026-10-12.
# B2LOAD_WRITE=0 builds the read-only loader that came first (3.2.y), which only reads the file and reports.
# RELEASE=1 builds the public image: the version is the release's name (src/release.h) and the raw USB peek / poke
# is left out. Everything else is the same code.
[ "${RELEASE:-0}" = 1 ] && CFLAGS="$CFLAGS -DPUBLIC_BUILD=1"
# FAULT_SHOW=1: a crash or a watchdog reset draws its record on the screen and holds, instead of resetting (fault.c)
[ "${FAULT_SHOW:-0}" = 1 ] && CFLAGS="$CFLAGS -DFAULT_SHOW=1"
# USB_DIAG=1: TOOLS shows the USB device's state and the HSI48 error instead of the load (usbdev.c)
[ "${USB_DIAG:-0}" = 1 ] && CFLAGS="$CFLAGS -DUSB_DIAG=1"
[ "${MUNCHI:-1}" = 1 ] || MUNCHI_FLAG=-DMUNCHI_OFF
arm-none-eabi-g++ $MUNCHI_FLAG -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib -fno-exceptions \
  -fno-rtti -fno-threadsafe-statics -fno-use-cxa-atexit -fno-math-errno -std=gnu++17 -Wall -Werror -Wno-unused-function \
  -Wno-class-memaccess -Wno-unused-but-set-variable -Wno-unused-variable -Wno-unused-parameter -isystem src/munchi/sys -c -o out/munchi.o src/munchi.cpp

OBJS=""
for f in src/*.c; do
  b=$(basename "$f" .c)
  arm-none-eabi-gcc $CFLAGS -c -o "out/obj/$b.o" "$f"
  OBJS="$OBJS out/obj/$b.o"
done
for f in src/*.S; do
  b=$(basename "$f" .S)
  arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -c -o "out/obj/$b.o" "$f"
  OBJS="$OBJS out/obj/$b.o"
done

# The linker script needs the bank 2 object list as a pattern it can match.
B2_PAT=""
for b in $BANK2_SRCS; do B2_PAT="$B2_PAT out/obj/$b.o(.text .text.* .rodata .rodata.*)"; done
for o in $BANK2_OBJS; do B2_PAT="$B2_PAT $o(.text .text.* .rodata .rodata.*)"; done
sed -e "s|@B2_OBJS@|$B2_PAT|" src/cave.ld.in > out/cave.ld

arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -nostdlib \
  -T out/cave.ld -Wl,-e,0 -Wl,-Map=out/cave.map -o out/cave.elf $OBJS out/munchi.o

arm-none-eabi-objcopy -O binary -j .cave out/cave.elf out/cave.bin
arm-none-eabi-objcopy -O binary -j .b2head -j .bank2 out/cave.elf out/bank2.raw

# Finish bank 2's header: length and a sum over everything after it, so bank 1 can tell intact from half-written.
# Padded to a whole 32-byte flash word, which is the unit the programming sequence writes.
python3 - "$B2_ID" <<'PY'
import struct, sys
raw = open("out/bank2.raw", "rb").read()
if raw:
    raw += b"\0" * (-len(raw) % 32)
    body = raw[16:]
    chk = 0
    for w in struct.unpack(f"<{len(body)//4}I", body):
        chk = (chk + w) & 0xFFFFFFFF
    hdr = struct.pack("<IIII", 0x21324242, int(sys.argv[1], 16), len(raw), chk)
    raw = hdr + raw[16:]
open("out/bank2.bin", "wb").write(raw)
print(f"bank2.bin: {len(raw)} bytes, id {sys.argv[1]}" if raw else "bank2.bin: empty")

# Bank 1 must know the sum of the bank 2 it was LINKED against (src/cpu.c: b2_expect_sum). The id cannot do this
# job - it hashes sources, and a payload linked against an older cave has the same sources.
import subprocess
sym = {l.split()[-1]: int(l.split()[0], 16) for l in subprocess.run(
    ["arm-none-eabi-nm", "out/cave.elf"], capture_output=True, text=True, check=True).stdout.splitlines() if len(l.split()) >= 3}
cave = bytearray(open("out/cave.bin", "rb").read())
at = sym["b2_expect_sum"] - 0x080F1E78
assert cave[at:at + 4] == b"\xff\xff\xff\xff", "b2_expect_sum is not where the symbol says it is"
cave[at:at + 4] = struct.pack("<I", chk if raw else 0)
open("out/cave.bin", "wb").write(cave)
PY

# THE CHECK THAT WOULD HAVE CAUGHT THE 3.2.m - 3.2.r CRASH ON DAY ONE. Bank 2 on the test unit is programmed once and
# survives every bank 1 install, so the bank 2 this build links MUST be the payload that is physically up there,
# byte for byte. If it is not, bank 2's own code changed: build with BANK2_NEW=1 and ship the new out/BBEXTRA.BIN
# beside BLACKBOX.bin - the card loader writes it. (Bank 2 calls nothing in the cave since 3.3.c; test_bank2.py
# fails the build if that ever stops being true.)
DEPLOYED_B2=card-backup/BANK2-3.3.c-payload.bin
if [ ! -f "$DEPLOYED_B2" ]; then
  :   # no record here of what is on a unit (the public tree): the build ships its own bank 2 as out/BBEXTRA.BIN
elif ! cmp -s out/bank2.bin "$DEPLOYED_B2"; then
  if [ "${BANK2_NEW:-0}" = 1 ]; then
    echo "WARNING: out/bank2.bin differs from $DEPLOYED_B2 - this image needs bank 2 REPROGRAMMED before it is flashed"
  else
    echo "ERROR: the bank 2 this build expects is NOT the payload on the test unit ($DEPLOYED_B2)."
    echo "       Flashing it would call stale addresses, which is the crash that took three sessions to find."
    echo "       $(cmp -l out/bank2.bin "$DEPLOYED_B2" | wc -l | tr -d ' ') bytes differ. Build with BANK2_NEW=1 only if bank 2 is being reprogrammed."
    exit 1
  fi
fi

# The card file the loader (src/b2load.c) looks for beside BLACKBOX.bin: the bank 2 payload under its card name.
cp out/bank2.bin out/BBEXTRA.BIN
arm-none-eabi-size -A out/cave.elf | grep -E 'cave|bank2|b2head|data|bss'
