"""Barcode value generation + printable Code128 label rendering (SVG, no Pillow)."""

from io import BytesIO

import barcode
from barcode.writer import SVGWriter

PREFIX = "PCO"

# Label size presets. width/height in millimetres; 0 = flow on a normal sheet.
LABEL_SIZES = {
    "sheet":       {"label": "Plain paper sheet (many per page)", "w": 0,   "h": 0},
    "rollo-4x6":   {"label": "Rollo 4×6 in (102×152 mm)",          "w": 102, "h": 152},
    "asset-57x32": {"label": "Asset 2.25×1.25 in (57×32 mm)",      "w": 57,  "h": 32},
    "50x25":       {"label": "50×25 mm",                            "w": 50,  "h": 25},
    "ql-62x29":    {"label": "Brother QL 62×29 mm die-cut",         "w": 62,  "h": 29},
    "ql-62-cont":  {"label": "Brother QL 62 mm continuous",         "w": 62,  "h": 40},
    "ptouch-24":   {"label": "Brother P-touch 24 mm tape",          "w": 70,  "h": 24},
    "ptouch-18":   {"label": "Brother P-touch 18 mm tape",          "w": 60,  "h": 18},
    "ptouch-12":   {"label": "Brother P-touch 12 mm tape",          "w": 50,  "h": 12},
}


def size_preset(key):
    return LABEL_SIZES.get(key) or LABEL_SIZES["sheet"]


def generate_value(part_id: int) -> str:
    """Deterministic, human-readable internal barcode for items with no barcode."""
    return f"{PREFIX}{part_id:06d}"


def render_svg(code: str, *, module_height: float = 12.0, font_size: int = 10) -> str:
    """Return an inline SVG string of a Code128 barcode for `code`."""
    writer = SVGWriter()
    options = {
        "module_height": module_height,
        "module_width": 0.3,
        "font_size": font_size,
        "text_distance": 3.0,
        "quiet_zone": 2.0,
    }
    code128 = barcode.get("code128", code, writer=writer)
    buf = BytesIO()
    code128.write(buf, options=options)
    svg = buf.getvalue().decode("utf-8")
    # Strip the XML declaration so it can be embedded inline in HTML.
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()
    return svg
