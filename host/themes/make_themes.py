"""Colour theme mock-ups: python3 make_themes.py [out_dir] -> themes.html (+ one theme-N.html per theme for phone shots).

The Blackbox draws with ONE 34-entry palette (RAM 0x24000000, copied from flash 0x080f1d80 at boot); screens pass
palette INDICES. A theme = a new set of 34 colours, nothing else. Each theme is drawn on six screens at the real
320 x 240, cut to the screen's 15-bit colour (ARGB1555) and shown with hard pixels.

What is known vs. guessed about which index paints what:
  KNOWN (from the code): pad picker squares 1, selected 4, active 10, pressed 15, label text 15 (padnum.c);
  piano roll background 1, every 4th step column 16, grid lines 13, pad-number column 16 / 1 with text 2.
  The GUI's y runs UP, so the title bar is the top 20 px and the pads / lists sit under it.
  GUESSED (from the manual + photos): what the Pads, mixer, waveform and Tools screens paint with which index.
  Good enough to judge a scheme across screens, not a pixel-exact copy.
v2 (2026-10-18, his notes): no white / paper theme; more themes; a set modelled on old machines' displays; six
screens so a theme is judged everywhere.
"""
import base64
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STOCK = ["#000000", "#56565a", "#141414", "#fcfcfc", "#ff6af3", "#09d7f5", "#ff0000", "#09d7f5", "#141414",
         "#666666", "#09d7f5", "#22bb22", "#bb2222", "#141414", "#000000", "#ffffff", "#444444", "#707070",
         "#22bb22", "#bb2222", "#ffff00", "#bb2222", "#aaaaaa", "#00ffcc", "#ba00ff", "#2b2b2b", "#046b7a",
         "#09d7f5", "#777100", "#09d7f5", "#ffffff", "#09d7f5", "#ff6af3", "#ffffff"]

ROLES = {
    "accent": [5, 7, 10, 27, 29, 31],   # stock cyan: play bars, active buttons, notes
    "select": [4, 32],                  # stock pink: the selected pad / note
    "bg": [2, 8],                       # near-black: screen background
    "line": [13],                       # grid lines (stock: same as bg)
    "bar": [0, 14],                     # title / status bars
    "cell": [1],                        # the grey of pads, squares, the piano roll
    "grey9": [9], "button": [16], "grey17": [17], "label": [22], "empty": [25],
    "text": [3, 15, 30, 33],
    "green": [11, 18], "red": [12, 19, 21], "red6": [6], "yellow": [20], "teal": [23], "purple": [24],
    "accent_dim": [26], "yellow_dim": [28],
}


def theme(**over):
    p = list(STOCK)
    for role, colour in over.items():
        for i in ROLES[role]:
            p[i] = colour
    return p


def dark(bg, line, bar, cell, button, empty, label, text, accent, accent_dim, select, dim=None, **more):
    """dim = greys 9 + 17 (stock #666666 / #707070): the waveform page's Slice / Zoom / Start / End labels, and the
    XY page's labels + lines. Unset = cell / button, which on a dark theme leaves those labels invisible."""
    return theme(bg=bg, line=line, bar=bar, cell=cell, grey9=dim or cell, button=button, grey17=dim or button,
                 empty=empty, label=label, text=text, accent=accent, accent_dim=accent_dim, select=select, **more)


def lcd(bg, cell, line, ink, mid, accent, select, **more):
    """Positive LCD: a lit background, dark ink. Lit / selected things are inverted (ink fill, background text)."""
    return theme(bg=bg, bar=line, line=line, cell=cell, grey9=cell, button=mid, grey17=mid, empty=line, label=mid,
                 text=ink, accent=accent, accent_dim=mid, select=select, green=accent, red=select, red6=select,
                 yellow=ink, yellow_dim=mid, teal=accent, purple=select, **more)


THEMES = [
    ("Displays of old machines", None, None),
    ("Green LCD", "Yellow-green backlit LCD with dark ink, like the 80s samplers and drum machines. Lit = inverted.",
     lcd(bg="#a8b86a", cell="#97a85c", line="#869751", ink="#18240c", mid="#4f5e2a", accent="#2c3b14", select="#6f8238")),
    ("Grey-green LCD", "The cooler, greyer backlit LCD of the big-screen MPC-era boxes. Lit = inverted.",
     lcd(bg="#9fac9a", cell="#8e9b89", line="#7f8c7a", ink="#14201a", mid="#4b5a50", accent="#25362c", select="#687a6c")),
    ("Blue LCD", "Negative blue LCD: deep blue glass, pale blue-white pixels.",
     dark(bg="#0b1a7a", line="#08135c", bar="#06104a", cell="#1d2f9e", button="#16278a", empty="#0e1d6a",
          label="#8fa3e8", text="#dfe8ff", accent="#2a9ad8", accent_dim="#2b5fae", select="#ec6a14",
          dim="#6f7fb5", green="#7fd8ff", yellow="#ffe36a", red="#ff7a8a")),
    ("Orange LCD", "Orange backlight, black ink. Loud but very readable.",
     lcd(bg="#e8862a", cell="#d47722", line="#bf6a1d", ink="#1a0c02", mid="#6e3a0c", accent="#3a1c04", select="#f6b46a")),
    ("Amber VFD", "Gas-plasma / VFD amber: black glass, glowing amber, a hotter orange for selection.",
     dark(bg="#0a0705", line="#1a120a", bar="#000000", cell="#2a2118", button="#1e1811", empty="#140f0a",
          label="#a08868", text="#ffd9a0", accent="#c08300", accent_dim="#6a4a00", select="#ff5a1f",
          dim="#7a674e", green="#ffb000", yellow="#ffd060", red="#ff5a1f")),
    ("Cyan VFD", "Vacuum-fluorescent blue-green: black glass, teal glow.",
     dark(bg="#030b0b", line="#0b1c1c", bar="#000000", cell="#10302e", button="#0b2422", empty="#071514",
          label="#5fae9e", text="#bffff0", accent="#3fffe0", accent_dim="#127466", select="#d0ff5a",
          green="#3fffe0", yellow="#d0ff5a", red="#ff6a5a")),
    ("Red LED", "Seven-segment red: black, red glow, orange for selection.",
     dark(bg="#080202", line="#1c0606", bar="#000000", cell="#2e0c0c", button="#220808", empty="#140404",
          label="#a85050", text="#ffc0b0", accent="#ff2a1a", accent_dim="#701008", select="#ffa020",
          green="#ff2a1a", yellow="#ffa020", red="#ff2a1a")),
    ("Phosphor", "Green-screen terminal: green-black, green glow, lime selection.",
     dark(bg="#050a06", line="#0e1a10", bar="#000000", cell="#16261a", button="#102016", empty="#0b150e",
          label="#7fb08a", text="#c8ffd2", accent="#39ff6a", accent_dim="#14662a", select="#d6ff3a",
          green="#39ff6a", yellow="#d6ff3a")),
    ("Colours", None, None),
    ("Stock 3.1.9", "1010music's own: cyan + pink on mid grey.", STOCK),
    ("JOEBOX", "Cyan moved to the logo blue, pink becomes a warm amber. Greys as stock.",
     theme(accent="#3ad7ff", select="#ffb13a", accent_dim="#0f5f73")),
    ("Club Dark", "Darker greys, orange instead of pink, a deeper teal. Easier on the eyes in a dark room.",
     dark(bg="#0a0a0a", line="#0a0a0a", bar="#000000", cell="#2f2f33", button="#262626", empty="#1a1a1a",
          label="#8a8a8a", text="#ececec", accent="#079cb3", accent_dim="#04505c", select="#ff7a00")),
    ("Midnight", "Navy-tinted greys, violet for lit, mint for selection.",
     dark(bg="#0b0d18", line="#0b0d18", bar="#05060c", cell="#2a2f4a", button="#20243a", empty="#151829",
          label="#8a90b8", text="#e6e8ff", accent="#8f7bff", accent_dim="#3d3380", select="#3ba97f",
          dim="#666b89")),
    ("Ember", "Charcoal, red for lit, gold for selection.",
     dark(bg="#0e0b0a", line="#0e0b0a", bar="#000000", cell="#35302d", button="#2a2522", empty="#1c1816",
          label="#9a8f88", text="#f2e8e0", accent="#ff4a3d", accent_dim="#7a1f18", select="#ffc93c")),
    ("Forest", "Green-grey, lime for lit, coral for selection.",
     dark(bg="#0a0f0b", line="#0a0f0b", bar="#000000", cell="#2c3a30", button="#223027", empty="#16201a",
          label="#8aa092", text="#e6f2ea", accent="#a8ff3c", accent_dim="#4a7a14", select="#ff7a6a")),
    ("Ocean", "Slate blue, aqua for lit, coral for selection.",
     dark(bg="#081018", line="#081018", bar="#03080c", cell="#273a4c", button="#1e2f3e", empty="#132230",
          label="#86a0b8", text="#e4f0fa", accent="#2ee6d6", accent_dim="#11706a", select="#ff8a65")),
    ("Rose", "Plum greys, pink for lit, sky blue for selection.",
     dark(bg="#120a10", line="#120a10", bar="#060305", cell="#3e2c3a", button="#30222d", empty="#1e141c",
          label="#b08aa8", text="#fbe8f6", accent="#ff5fbf", accent_dim="#7a245a", select="#6ad0ff")),
    ("High Contrast", "For daylight: black, near-black squares, yellow lit, red selection.",
     dark(bg="#000000", line="#000000", bar="#000000", cell="#303030", button="#202020", empty="#181818",
          label="#b0b0b0", text="#f4f4f4", accent="#ffd400", accent_dim="#6a5800", select="#ff3b30")),
]

FONT = 'font-family="Menlo, monospace"'


def t(x, y, s, c, size=8, anchor="start", weight="bold"):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" font-weight="{weight}" fill="{c}" text-anchor="{anchor}">{s}</text>'


def r(x, y, w, h, c, stroke=None, sw=1):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"{s}/>'


def svg(body, bg):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">{r(0, 0, 320, 240, bg)}{body}</svg>'


def title(p, left, mid, right=""):
    return (r(0, 0, 320, 19, p[14]) + t(4, 13, left, p[15], 9) + t(160, 13, mid, p[15], 9, "middle")
            + t(316, 13, right, p[15], 9, "end"))


NAMES = ["VOX", "", "LOOP 1", "FX RISE", "BASS", "", "STAB", "CHORD",
         "CLAP", "RIM", "TOM LO", "PERC", "KICK 01", "SNARE", "HAT C", "HAT O"]   # top row first; KICK = pad 1


def pads_screen(p):
    b = [title(p, "1:1", "Scene 1", "120.0")]
    for row in range(4):
        for col in range(4):
            x, y = col * 64 + 1, 20 + row * 55
            name = NAMES[row * 4 + col]
            b.append(r(x, y, 62, 53, p[1] if name else p[25]))
            if name:
                b.append(t(x + 4, y + 12, name, p[15], 8))
                b.append(r(x + 4, y + 40, 54, 3, p[16]))
            if (row, col) == (3, 2):                            # playing: the progress bar
                b.append(r(x + 4, y + 40, 34, 3, p[5]))
                b.append(r(x + 1, y + 46, 60, 5, p[5]))
            if (row, col) == (3, 0):                            # selected: the pink box
                b.append(r(x + 1, y + 1, 60, 51, "none", p[4], 2))
    for i, (lab, lit) in enumerate([("VEL", True), ("COPY", False), ("MUTE", False), ("SOLO", False)]):
        y = 20 + i * 55
        b.append(r(258, y, 61, 53, p[5] if lit else p[16]))
        b.append(t(288, y + 30, lab, p[15], 9, "middle"))
    return svg("".join(b), p[2])


def piano_roll(p, picker=False):
    b = [title(p, "1:1", "Seq 1: A")]
    x = 1
    for lab, w in [("#", 22), ("A", 22), ("PADS", 40), ("Edit", 38), ("Event", 44)]:
        b.append(r(x, 20, w, 17, p[16]))
        b.append(t(x + w / 2, 32, lab, p[5] if lab == "A" else p[15], 9, "middle"))
        x += w + 1
    top, h = 38, 202
    b.append(r(0, top, 320, h, p[1]))
    for s in range(16):
        cx = 34 + s * 18
        if s % 4 == 0:
            b.append(r(cx, top, 18, h, p[16]))
        b.append(r(cx, top, 1, h, p[13]))
    for i in range(12):
        y = top + i * 18
        b.append(r(10, y, 24, 18, p[16] if i % 4 == 0 else p[1]))
        b.append(t(14, y + 12, str(16 - i), p[2], 8))
        b.append(r(10, y + 17, 310, 1, p[13]))
    b.append(r(0, top, 9, h, p[2]))
    b.append(r(1, top + 40, 7, 60, p[1]))
    for st, row, ln in [(0, 11, 2), (4, 11, 2), (8, 11, 2), (12, 11, 2), (2, 9, 1), (6, 9, 1), (10, 9, 1), (14, 9, 1),
                        (4, 10, 1), (12, 10, 1), (0, 3, 4), (8, 3, 3)]:
        b.append(r(35 + st * 18, top + row * 18 + 3, ln * 18 - 2, 12, p[4] if (st, row) == (8, 3) else p[7]))
    if picker:
        b.append(r(0, 38, 150, 202, p[2]))
        for row in range(4):
            for col in range(4):
                x, y = 8 + col * 34, 46 + row * 34
                n = (3 - row) * 4 + col + 1
                b.append(r(x, y, 32, 32, p[4] if n == 1 else p[1]))
                b.append(t(x + 16, y + 20, str(n), p[15], 9, "middle"))   # KNOWN: colour 15 on every square
        b.append(r(8, 186, 134, 30, p[16]))
        b.append(t(75, 205, "SEQ", p[15], 10, "middle"))
    return svg("".join(b), p[2])


def mixer(p):
    b = [title(p, "MIX", "Scene 1", "-3.2 dB")]
    levels = [0.0, 0.0, 0.55, 0.3, 0.7, 0.0, 0.45, 0.6, 0.8, 0.35, 0.5, 0.4, 0.95, 0.75, 0.6, 0.5]
    for row in range(4):
        for col in range(4):
            i = row * 4 + col
            x, y = col * 80 + 1, 20 + row * 55
            name = NAMES[i]
            b.append(r(x, y, 78, 53, p[1] if name else p[25]))
            if not name:
                continue
            muted = name == "PERC"
            b.append(t(x + 4, y + 12, name, p[22] if muted else p[15], 8))
            b.append(r(x + 4, y + 30, 70, 6, p[16]))
            lv = levels[i] * 70
            b.append(r(x + 4, y + 30, min(lv, 50), 6, p[11]))
            if lv > 50:
                b.append(r(x + 54, y + 30, min(lv, 62) - 50, 6, p[20]))
            if lv > 62:
                b.append(r(x + 66, y + 30, lv - 62, 6, p[12]))
            b.append(t(x + 74, y + 48, "M" if muted else "0 dB", p[12] if muted else p[22], 7, "end"))
            if muted:
                b.append(r(x, y + 49, 78, 4, p[12]))
    return svg("".join(b), p[2])


def waveform(p):
    b = [title(p, "KICK 01.wav", "", "Pad 1")]
    top, h = 20, 160
    b.append(r(0, top, 320, h, p[2]))
    b.append(r(48, top, 200, h, p[26]))                         # the selected region
    b.append(r(0, top + h / 2, 320, 1, p[16]))
    pts = []
    for i in range(320):
        env = math.exp(-i / 70.0)
        v = math.sin(i * 0.35 + 0.02 * i * i / 30) * env * 70 + math.sin(i * 1.7) * env * 6
        pts.append(f"{i},{top + h / 2 - v:.1f}")
    b.append(f'<polyline fill="none" stroke="{p[5]}" stroke-width="1" points="{" ".join(pts)}"/>')
    b.append(r(48, top, 2, h, p[4]))
    b.append(r(246, top, 2, h, p[4]))
    b.append(r(120, top, 1, h, p[15]))                          # playhead
    for i, (lab, val) in enumerate([("START", "15%"), ("END", "77%"), ("PITCH", "-3"), ("LEVEL", "0dB")]):
        x = i * 80 + 1
        b.append(r(x, 182, 78, 57, p[25]))
        b.append(t(x + 39, 200, lab, p[17], 8, "middle"))              # KNOWN from the glass: 9 or 17
        b.append(t(x + 39, 222, val, p[17], 11, "middle"))
    return svg("".join(b), p[2])


def tools(p):
    b = [title(p, "TOOLS", "Main")]
    rows = [("Tempo", "120.0"), ("Swing", "54%"), ("Master FX", "VHS"), ("Compressor", "Smash"),
            ("Clipper", "Diode"), ("Metronome", "Off"), ("MIDI Clock", "In"), ("Theme", "Club Dark")]
    for i, (k, v) in enumerate(rows):
        y = 20 + i * 24
        sel = i == 1
        b.append(r(0, y, 320, 23, p[4] if sel else p[1]))               # KNOWN from the glass: select fill
        b.append(t(8, y + 16, k, p[15], 10))
        b.append(t(312, y + 16, v, p[15] if sel else p[5], 10, "end"))
    b.append(r(0, 214, 320, 26, p[14]))
    b.append(t(6, 231, "12.3 GB", p[22], 9))
    b.append(t(160, 231, "38/52%", p[20], 9, "middle"))
    b.append(t(314, 231, "3.3.m", p[15], 9, "end"))
    return svg("".join(b), p[2])


SCREENS = [("Pads", pads_screen), ("Piano roll", piano_roll), ("Pad picker", lambda p: piano_roll(p, True)),
           ("Mixer", mixer), ("Waveform", waveform), ("Tools", tools)]


def swatches(p):
    seen, out = [], []
    for c in p:
        if c not in seen:
            seen.append(c)
            out.append(f'<span style="background:{c}" title="{c}"></span>')
    return "".join(out)


def card(s):
    return f'<canvas width="640" height="480" data-svg="{base64.b64encode(s.encode()).decode()}"></canvas>'


SCRIPT = """<script>
for (const c of document.querySelectorAll('canvas[data-svg]')) {
  const img = new Image();
  img.onload = () => {
    const s = document.createElement('canvas'); s.width = 320; s.height = 240;
    const x = s.getContext('2d'); x.drawImage(img, 0, 0);
    const d = x.getImageData(0, 0, 320, 240);
    for (let i = 0; i < d.data.length; i += 4) for (let k = 0; k < 3; k++) { const v = d.data[i + k] >> 3; d.data[i + k] = (v << 3) | (v >> 2); }
    x.putImageData(d, 0, 0);
    const o = c.getContext('2d'); o.imageSmoothingEnabled = false; o.drawImage(s, 0, 0, 640, 480);
  };
  img.src = 'data:image/svg+xml;base64,' + c.dataset.svg;
}
</script>"""
STYLE = """<style>
body{background:#111;color:#eee;font:14px/1.4 -apple-system,system-ui,sans-serif;margin:20px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:24px 0 2px} h3{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:2px;margin:36px 0 0}
p{color:#999;margin:0 0 8px;max-width:900px}
.screens{display:grid;grid-template-columns:repeat(3,320px);gap:10px} .phone .screens{grid-template-columns:repeat(2,320px)}
figure{margin:0} figcaption{color:#888;font-size:11px;margin-top:2px}
canvas{image-rendering:pixelated;width:320px;height:240px;display:block}
.sw span{display:inline-block;width:18px;height:12px;margin-right:2px;border:1px solid #333}
</style>"""


def section(i, name, note, p):
    figs = "".join(f"<figure>{card(fn(p))}<figcaption>{c}</figcaption></figure>" for c, fn in SCREENS)
    return f'<section><h2>{i}. {name}</h2><p>{note}</p><div class="sw">{swatches(p)}</div><div class="screens">{figs}</div></section>'


def main(out):
    parts, n = [], 0
    for name, note, p in THEMES:
        if p is None:
            parts.append(f"<h3>{name}</h3>")
            continue
        n += 1
        sec = section(n, name, note, p)
        parts.append(sec)
        open(os.path.join(out, f"theme-{n}.html"), "w").write(
            f'<!doctype html><meta charset="utf-8"><title>{name}</title>{STYLE}<body class="phone" style="width:650px">{sec}{SCRIPT}')
    page = (f'<!doctype html><meta charset="utf-8"><title>Blackbox Themes</title>{STYLE}'
            '<h1>Blackbox colour themes v2 (mock-ups)</h1><p>Each theme only swaps the 34 palette colours. Screens are '
            'approximations at the real 320 x 240, cut to the screen\'s 15-bit colour. Known issue: stock writes the piano '
            'roll\'s pad numbers in the background colour, so on most themes they vanish; a real theme needs one small code '
            'change to give that text its own colour (the mock-ups show stock behaviour).</p>' + "".join(parts) + SCRIPT)
    open(os.path.join(HERE, "themes.html"), "w").write(page)
    print(f"themes.html: {n} themes x {len(SCREENS)} screens")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
