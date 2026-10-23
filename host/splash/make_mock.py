"""Boot splash mock-ups (320 x 240, the app splash that shows ~2 s on boot): python3 make_mock.py -> mock.html.
The page draws each variant on a 320 x 240 canvas, cuts it to the screen's 15-bit colour (ARGB1555: 5 bits per
channel) and shows it 3x with hard pixels, next to the stock splash for comparison."""
import base64, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/Justin-Joe/joebox-logo-ideas"))
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    from gen import dots                                # the logo's dot-matrix letters

BLUE = "#3ad7ff"
logo = open(os.path.join(HERE, "logo.svg")).read()
GLOW = ('<defs><filter id="glow" filterUnits="userSpaceOnUse" x="0" y="0" width="320" height="240">'
        '<feGaussianBlur stdDeviation="1.1" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>'
        '</feMerge></filter></defs>')


def svg(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">{GLOW}<rect width="320" height="240" fill="#000"/>{body}</svg>'


def embed(x, y, size):
    # the logo's drawing sits at 90..510 x 80..520 of its 600 box: scale so that box is `size` tall
    s = size / 440
    inner = logo.split(">", 1)[1].rsplit("</svg>", 1)[0].replace('id="glow"', 'id="glowL"').replace("url(#glow)", "url(#glowL)")
    return f'<g transform="translate({x - 300 * s:.1f},{y - 300 * s:.1f}) scale({s:.4f})">{inner}</g>'


def small(text, x, y, size=9, fill="#d8d8d8", anchor="middle", ls=2):
    return (f'<text x="{x}" y="{y}" font-family="Menlo, monospace" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" letter-spacing="{ls}">{text}</text>')


VERSION = small("JOEBOX 1", 312, 234, 9, "#ffffff", "end", 1)       # the firmware still draws its version label here
variants = {
    "A  logo": svg(embed(160, 116, 196) + VERSION),
    "B  logo + name": svg(embed(80, 112, 150) + dots("JOEBOX 1", 237, 92, 2.5, 1.0, BLUE)
                          + small("BLACKBOX MOD", 237, 134, 8, ls=1.5) + small("BY JUSTIN JOE", 237, 148, 8, ls=1.5) + VERSION),
    "C  wordmark": svg(dots("JOEBOX 1", 160, 78, 5.2, 2.0, BLUE)
                       + '<g filter="url(#glow)"><polyline fill="none" stroke="#f2f2f2" stroke-width="1.4" points="'
                       + " ".join(f"{40 + i * 2.4:.1f},{150 + (14 * __import__('math').sin(i * 0.9) * __import__('math').exp(-i / 40) * (1 if i % 2 else -0.6)):.1f}" for i in range(101))
                       + '"/><line x1="40" y1="128" x2="40" y2="172" stroke="' + BLUE + '" stroke-width="1.6"/>'
                       + '<line x1="280" y1="128" x2="280" y2="172" stroke="' + BLUE + '" stroke-width="1.6"/></g>'
                       + small("BLACKBOX MOD  BY JUSTIN JOE", 160, 204, 8) + VERSION),
}
stock = ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240"><rect width="320" height="240" fill="#707070"/>'
         + small("blackbox", 160, 92, 13, "#ffffff", "middle", 0) + small("by 1010music", 160, 120, 13, "#ffffff", "middle", 0)
         + small("3.3.k", 312, 232, 13, "#ffffff", "end", 0) + '</svg>')
cards = "".join(
    f'<figure><figcaption>{name}</figcaption><canvas width="960" height="720" data-svg="{base64.b64encode(s.encode()).decode()}"></canvas></figure>'
    for name, s in [("Stock (now)", stock)] + list(variants.items()))
html = f"""<!doctype html><meta charset=utf-8><title>JOEBOX splash mock</title>
<style>body{{background:#1b1b1d;color:#ddd;font:14px -apple-system,sans-serif;margin:24px}}
.grid{{display:grid;grid-template-columns:repeat(2,960px);gap:28px}}figure{{margin:0}}
figcaption{{margin:0 0 8px;font-weight:600}}canvas{{image-rendering:pixelated;border:1px solid #333;width:960px;height:720px}}</style>
<h2>Boot splash, 320 x 240, shown 3x in the screen's 15-bit colour</h2><div class=grid>{cards}</div>
<script>
for (const c of document.querySelectorAll('canvas')) {{
  const img = new Image();
  img.onload = () => {{
    const s = document.createElement('canvas'); s.width = 320; s.height = 240;
    const x = s.getContext('2d'); x.drawImage(img, 0, 0, 320, 240);
    const d = x.getImageData(0, 0, 320, 240);
    for (let i = 0; i < d.data.length; i += 4) for (let k = 0; k < 3; k++) d.data[i + k] = (d.data[i + k] >> 3) * 255 / 31;   // ARGB1555
    x.putImageData(d, 0, 0);
    const o = c.getContext('2d'); o.imageSmoothingEnabled = false; o.drawImage(s, 0, 0, 960, 720);
    document.title = 'ready';
  }};
  img.src = 'data:image/svg+xml;base64,' + c.dataset.svg;
}}
</script>"""
open(os.path.join(HERE, "mock.html"), "w").write(html)
for name, s in variants.items():
    open(os.path.join(HERE, "splash-" + name.split()[0] + ".svg"), "w").write(s)
print("mock.html")
