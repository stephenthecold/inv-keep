"""Barcode value generation + printable Code128 label rendering (SVG, no Pillow)."""

from io import BytesIO

import barcode
from barcode.writer import SVGWriter

PREFIX = "PCO"


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
