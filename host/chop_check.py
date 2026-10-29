"""ChopShop attack scan + placement on a real file, on the Mac (host/libchop.dylib = chop_dsp.c + chop.c's pure parts).

usage: chop_check.py file.wav bpm anchor [out.ppm]
Prints how many hits the scan keeps, how many audio blocks it takes, and per chop type how many chops sit on a hit;
with REF=onsets.npy (frames, e.g. librosa.onset.onset_detect at hop 128) how they compare to those onsets. Draws the first 8 s: waveform,
the scan's hits (green), and per row the chops of 1/2 beat, Beat, Find 64, Random 64 (red) over the beat grid (blue).
"""
import ctypes, os, sys
import numpy as np
from scipy.io import wavfile

H = os.path.dirname(os.path.abspath(__file__))
L = ctypes.CDLL(os.path.join(H, "libchop.dylib"))
F, I = ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int32)
L.chop_host_scan.argtypes = [F, F, ctypes.c_int, ctypes.c_int, ctypes.c_int]
L.chop_host_hits.argtypes = [I, F, F]
L.chop_host_grid.argtypes = [I, ctypes.c_int32, ctypes.c_int32, ctypes.c_float, ctypes.c_float]
L.chop_host_pick.argtypes = [ctypes.c_int, I, ctypes.c_int, ctypes.c_uint32]

path, bpm, anchor = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
out_ppm = sys.argv[4] if len(sys.argv) > 4 else None
fr, x = wavfile.read(path)
x = x.astype(np.float64) / {np.dtype("int16"): 32768.0, np.dtype("int32"): 2147483648.0}.get(x.dtype, 1.0)
if x.ndim == 1:
    x = x[:, None]
l = np.ascontiguousarray(x[:, 0], np.float32)
r = np.ascontiguousarray(x[:, 1], np.float32) if x.shape[1] > 1 else None
n = len(l)
fpb = fr * 60.0 / bpm


def scan(upto, miss=0):
    return L.chop_host_scan(l.ctypes.data_as(F), r.ctypes.data_as(F) if r is not None else None, n, upto, miss)


steps = scan(n)
at, sc, lv = np.zeros(1024, np.int32), np.zeros(1024, np.float32), np.zeros(1024, np.float32)
nh = L.chop_host_hits(at.ctypes.data_as(I), sc.ctypes.data_as(F), lv.ctypes.data_as(F))
hits = np.sort(at[:nh])
print(f"{os.path.basename(path)}: {n} frames ({n / fr:.1f} s), {nh} hits kept, scan = {steps} audio blocks "
      f"({steps / 375:.1f} s at 375 blocks/s)")

m = x.mean(1)
REF = os.environ.get("REF")                       # optional reference onsets (.npy of frames, e.g. librosa's)
ref = np.sort(np.load(REF)) if REF else np.zeros(0, np.int64)


def near(pts):
    k = np.searchsorted(ref, pts)
    return np.array([min(abs(int(o) - int(p)) for o in ref[max(0, kk - 1):kk + 1]) for p, kk in zip(pts, k)])


def show(name, pts):
    pts = np.sort(np.array(pts, np.int64))
    on = set(int(v) for v in hits)
    print(f"  {name:10s} {len(pts):3d} chops, {sum(int(p) in on for p in pts)} of them on a hit"
          + (f"; a reference onset within 30 ms of {np.mean(near(pts[pts > 64]) <= 1440) * 100:.0f} %" if len(ref) else ""))
    return pts


buf = np.zeros(128, np.int32)
rows = []
grid = lambda u: np.arange(anchor, n, fpb * u)[:127]
if len(ref):
    hk = np.sort(hits)
    rk = np.array([np.min(np.abs(hk - o)) for o in ref])
    print(f"  reference: {len(ref)} onsets; hits with one within 30 ms {np.mean(near(hits) <= 1440) * 100:.1f} %, "
          f"onsets with a hit within 30 ms {np.mean(rk <= 1440) * 100:.1f} %")
for name, u in (("1/2 beat", 0.5), ("Beat", 1.0), ("Bar", 4.0)):
    k = L.chop_host_grid(buf.ctypes.data_as(I), n, int(anchor), fpb, u)
    rows.append((name, show(name, buf[:k]), grid(u)))
for name, find in (("Find 64", 1), ("Random 64", 0)):
    k = L.chop_host_pick(find, buf.ctypes.data_as(I), 64, 12345)
    p = show(name, buf[:k])
    k2 = L.chop_host_pick(find, buf.ctypes.data_as(I), 64, 999)
    print(f"  {'':10s} another roll: {len(set(buf[:k2]) - set(p))} of {k2} chops differ")
    rows.append((name, p, None))

# a resumed scan (grid chops scan part-way, Find later goes on) gives the same hits as one pass, and misses don't matter
L.chop_host_scan(l.ctypes.data_as(F), None, 1, 1, 0)                       # another source: forget
s1 = scan(n // 3, 7)
s2 = scan(n, 7)
at2 = np.zeros(1024, np.int32)
nh2 = L.chop_host_hits(at2.ctypes.data_as(I), sc.ctypes.data_as(F), lv.ctypes.data_as(F))
print(f"  resumed scan (a third, then the rest, every 7th fetch missing): {nh2} hits, "
      f"{'the same' if sorted(at2[:nh2]) == sorted(at[:nh]) else 'DIFFERENT'} as one pass")

if out_ppm:
    W_, Hh, secs = 1600, 110, 8.0
    span = int(secs * fr / 4)
    img_rows = []
    mm = m / (np.abs(m[:int(secs * fr)]).max() + 1e-12)
    for s0 in range(0, int(secs * fr), span):
        s1 = s0 + span
        per = span / W_
        for name, pts, g in [("wave", None, None)] + rows:
            img = np.full((Hh, W_, 3), 18, np.uint8)
            for px in range(W_):
                lo, hi = int(s0 + px * per), int(s0 + (px + 1) * per)
                v = np.abs(mm[lo:hi]).max() if hi > lo else 0
                h = int(v * (Hh / 2 - 3))
                img[Hh // 2 - h:Hh // 2 + h + 1, px] = (150, 120, 40) if pts is not None else (232, 176, 0)
            if pts is None:
                for p in hits:
                    if s0 <= p < s1:
                        img[:, int((p - s0) / per)] = (40, 230, 90)
            else:
                if g is not None:
                    for p in g:
                        if s0 <= p < s1:
                            img[:Hh // 5, int((p - s0) / per)] = (90, 110, 255)
                for p in pts:
                    if s0 <= p < s1:
                        img[Hh // 5:, int((p - s0) / per)] = (255, 50, 50)
            img_rows += [img, np.full((2, W_, 3), 60, np.uint8)]
        img_rows.append(np.full((10, W_, 3), 255, np.uint8))
    o = np.concatenate(img_rows)
    open(out_ppm, "wb").write(b"P6 %d %d 255\n" % (o.shape[1], o.shape[0]) + o.tobytes())
    print("  picture:", out_ppm, "(per 2 s: waveform + hits; 1/2 beat; Beat; Bar; Find 64; Random 64)")
