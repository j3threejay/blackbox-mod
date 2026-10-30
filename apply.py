"""Patch your own stock Blackbox firmware. Needs only Python 3, nothing to install.

  python3 apply.py path/to/BLACKBOX.bin [patch.json] [-o BLACKBOX.bin]

The input must be the unmodified 3.1.9 BLACKBOX.bin from 1010music's download. It is checked by SHA-256 before
anything is written, and the result is checked again afterwards.

Some builds come as TWO files: BLACKBOX.bin and BBEXTRA.BIN. Both are written to the same folder, and both go in
the root of the microSD card. The second one holds this project's own code only.
"""
import argparse
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
# The current release: the patch the browser patcher serves (docs/index.html), not the newest file (a clone gives
# every file the same time).
CURRENT = re.search(r'const PATCH = "([^"]+)"', open(os.path.join(ROOT, "docs", "index.html")).read()).group(1)
ap = argparse.ArgumentParser()
ap.add_argument("stock")
ap.add_argument("patch", nargs="?", default=os.path.join(ROOT, "docs", CURRENT))
ap.add_argument("-o", "--out", default=None)
a = ap.parse_args()

p = json.load(open(a.patch))
data = bytearray(open(a.stock, "rb").read())
if hashlib.sha256(data).hexdigest() != p["stock_sha256"]:
    raise SystemExit(f"This is not the stock {p['stock_version']} firmware (SHA-256 differs). Nothing written.\n"
                     "Download it from https://1010music.com/downloads and use the BLACKBOX.bin inside the zip.")
for w in p["writes"]:
    b = bytes.fromhex(w["bytes"])
    data[w["offset"]:w["offset"] + len(b)] = b
data += bytes.fromhex(p["append"])
if hashlib.sha256(data).hexdigest() != p["output_sha256"]:
    raise SystemExit("Patched image failed its check. Nothing written.")

extras = []
for x in p.get("extra", []):
    b = bytes.fromhex(x["bytes"])
    if os.path.basename(x["name"]) != x["name"] or len(b) != x["size"] or hashlib.sha256(b).hexdigest() != x["sha256"]:
        raise SystemExit(f"{x['name']} in the patch failed its check. Nothing written.")
    extras.append((x["name"], b))

out = a.out or os.path.join("out", f"blackbox-mod-{p.get('slug', p['version'])}", "BLACKBOX.bin")
if os.path.abspath(out) == os.path.abspath(a.stock):
    raise SystemExit("Refusing to overwrite the stock file. Pick another output path and keep the stock one as backup.")
folder = os.path.dirname(os.path.abspath(out))
os.makedirs(folder, exist_ok=True)
open(out, "wb").write(data)
print(f"wrote {out} ({len(data)} bytes) = blackbox-mod {p['version']}")
for name, b in extras:
    open(os.path.join(folder, name), "wb").write(b)
    print(f"wrote {os.path.join(os.path.dirname(out), name)} ({len(b)} bytes)")
if extras:
    print("Copy BOTH files to the root of the microSD card, then install as usual.")
