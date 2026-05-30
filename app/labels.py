"""Barcode value generation + printable Code128 label rendering (SVG, no Pillow)."""

from io import BytesIO

import barcode
from barcode.writer import SVGWriter

PREFIX = "PCO"

# Label size presets, grouped by the four most popular label-printer brands
# (Brother, DYMO, Zebra, Rollo). width/height in millimetres; 0 = flow on a sheet.
LABEL_SIZES = {
    "sheet":        {"brand": "Generic", "label": "Plain paper sheet (many per page)", "w": 0,   "h": 0},
    "50x25":        {"brand": "Generic", "label": "Generic 50×25 mm",                  "w": 50,  "h": 25},

    # Brother
    "ql-62x29":     {"brand": "Brother", "label": "Brother QL 62×29 mm die-cut",   "w": 62,  "h": 29},
    "ql-62-cont":   {"brand": "Brother", "label": "Brother QL 62 mm continuous",   "w": 62,  "h": 40},
    "ql-29x90":     {"brand": "Brother", "label": "Brother QL 29×90 mm address",   "w": 90,  "h": 29},
    "ptouch-24":    {"brand": "Brother", "label": "Brother P-touch 24 mm tape",    "w": 70,  "h": 24},
    "ptouch-18":    {"brand": "Brother", "label": "Brother P-touch 18 mm tape",    "w": 60,  "h": 18},
    "ptouch-12":    {"brand": "Brother", "label": "Brother P-touch 12 mm tape",    "w": 50,  "h": 12},

    # DYMO (LabelWriter / LabelManager)
    "dymo-30252":   {"brand": "DYMO", "label": "DYMO 30252 Address (89×28 mm)",      "w": 89,  "h": 28},
    "dymo-30336":   {"brand": "DYMO", "label": "DYMO 30336 Multipurpose (54×25 mm)", "w": 54,  "h": 25},
    "dymo-30334":   {"brand": "DYMO", "label": "DYMO 30334 Medium (57×32 mm)",       "w": 57,  "h": 32},
    "dymo-30330":   {"brand": "DYMO", "label": "DYMO 30330 Return (51×19 mm)",       "w": 51,  "h": 19},
    "dymo-lm-12":   {"brand": "DYMO", "label": "DYMO LabelManager 12 mm tape",       "w": 50,  "h": 12},

    # Zebra
    "zebra-2x1":    {"brand": "Zebra", "label": "Zebra 2×1 in (51×25 mm)",          "w": 51,  "h": 25},
    "zebra-225x125":{"brand": "Zebra", "label": "Zebra 2.25×1.25 in (57×32 mm)",    "w": 57,  "h": 32},
    "zebra-3x2":    {"brand": "Zebra", "label": "Zebra 3×2 in (76×51 mm)",          "w": 76,  "h": 51},
    "zebra-4x6":    {"brand": "Zebra", "label": "Zebra 4×6 in (102×152 mm)",        "w": 102, "h": 152},

    # Rollo
    "rollo-4x6":    {"brand": "Rollo", "label": "Rollo 4×6 in (102×152 mm)",        "w": 102, "h": 152},
    "asset-57x32":  {"brand": "Rollo", "label": "Rollo 2.25×1.25 in (57×32 mm)",    "w": 57,  "h": 32},

    # Epson (ColorWorks label + LabelWorks tape)
    "epson-cw-4x6":  {"brand": "Epson", "label": "Epson ColorWorks 4×6 in (102×152 mm)", "w": 102, "h": 152},
    "epson-cw-225":  {"brand": "Epson", "label": "Epson ColorWorks 2.25×1.25 in (57×32 mm)", "w": 57, "h": 32},
    "epson-cw-2x1":  {"brand": "Epson", "label": "Epson ColorWorks 2×1 in (51×25 mm)", "w": 51, "h": 25},
    "epson-lw-24":   {"brand": "Epson", "label": "Epson LabelWorks 24 mm tape", "w": 70, "h": 24},
    "epson-lw-18":   {"brand": "Epson", "label": "Epson LabelWorks 18 mm tape", "w": 60, "h": 18},
    "epson-lw-12":   {"brand": "Epson", "label": "Epson LabelWorks 12 mm tape", "w": 50, "h": 12},

    # Brady (M-series tape + self-laminating wire/cable labels)
    "brady-m21-19":  {"brand": "Brady", "label": "Brady M21 19 mm (3/4 in) tape", "w": 60, "h": 19},
    "brady-m21-12":  {"brand": "Brady", "label": "Brady M21 12.7 mm (1/2 in) tape", "w": 50, "h": 13},
    "brady-25x13":   {"brand": "Brady", "label": "Brady 1×0.5 in label (25×13 mm)", "w": 25, "h": 13},
    "brady-selflam": {"brand": "Brady", "label": "Brady self-laminating wire 25×38 mm", "w": 25, "h": 38},
    "brady-51x25":   {"brand": "Brady", "label": "Brady 2×1 in label (51×25 mm)", "w": 51, "h": 25},
}


def size_preset(key):
    return LABEL_SIZES.get(key) or LABEL_SIZES["sheet"]


def grouped_sizes():
    """Ordered list of (brand, [(key, preset), ...]) for optgrouped dropdowns."""
    groups = []
    for key, p in LABEL_SIZES.items():
        brand = p.get("brand", "Other")
        if not groups or groups[-1][0] != brand:
            groups.append((brand, []))
        groups[-1][1].append((key, p))
    return groups


def generate_value(part_id: int) -> str:
    """Deterministic, human-readable internal barcode for items with no barcode."""
    return f"{PREFIX}{part_id:06d}"


def render_svg(code: str, *, module_height: float = 12.0, font_size: int = 10, show_text: bool = True) -> str:
    """Return an inline SVG string of a Code128 barcode for `code`."""
    writer = SVGWriter()
    options = {
        "module_height": module_height,
        "module_width": 0.3,
        "font_size": font_size,
        "text_distance": 3.0,
        "quiet_zone": 2.0,
        "write_text": show_text,
    }
    code128 = barcode.get("code128", code, writer=writer)
    buf = BytesIO()
    code128.write(buf, options=options)
    svg = buf.getvalue().decode("utf-8")
    # Strip the XML declaration so it can be embedded inline in HTML.
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()
    return svg
