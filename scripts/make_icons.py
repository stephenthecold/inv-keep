"""Generate PWA icons for Inv-Keep. Dev/build tool only (needs Pillow).

    pip install pillow && python scripts/make_icons.py

Outputs PNGs into app/static/icons/. Re-run only when you want to change the
default app icon; the results are committed so runtime never needs Pillow.
"""

import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "icons")
os.makedirs(OUT, exist_ok=True)

ACCENT = (47, 129, 247)   # #2f81f7
DARK = (15, 20, 25)       # #0f1419
WHITE = (255, 255, 255)


def draw_glyph(d, size, cx, cy, scale):
    """A simple inventory box + barcode bars, centred at (cx, cy)."""
    w = int(size * 0.46 * scale)
    h = int(size * 0.30 * scale)
    x0, y0 = cx - w // 2, cy - h // 2
    lw = max(2, int(size * 0.022))
    # box outline
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=int(size * 0.03), outline=WHITE, width=lw)
    # lid line
    d.line([x0, y0 + h // 3, x0 + w, y0 + h // 3], fill=WHITE, width=lw)
    # barcode bars below the box
    bar_top = y0 + h + int(size * 0.05)
    bar_bot = bar_top + int(size * 0.20 * scale)
    widths = [3, 1, 2, 1, 3, 2, 1, 2]
    gap = max(2, int(size * 0.012))
    bx = cx - (sum(widths) * (lw) + (len(widths) - 1) * gap) // 2
    for wmul in widths:
        bw = lw * wmul
        d.rectangle([bx, bar_top, bx + bw, bar_bot], fill=WHITE)
        bx += bw + gap


def make(size, path, maskable=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, size, size], fill=ACCENT)  # full bleed for safe zone
        draw_glyph(d, size, size // 2, int(size * 0.46), 0.8)
    else:
        r = int(size * 0.22)
        d.rounded_rectangle([0, 0, size, size], radius=r, fill=ACCENT)
        draw_glyph(d, size, size // 2, int(size * 0.45), 1.0)
    img.save(path)
    print("wrote", path)


make(192, os.path.join(OUT, "icon-192.png"))
make(512, os.path.join(OUT, "icon-512.png"))
make(512, os.path.join(OUT, "maskable-512.png"), maskable=True)
