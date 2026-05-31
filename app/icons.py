"""Built-in line-icon set for items (crisp SVG, scales + prints).

An item's `icon` field holds either an emoji (e.g. "🔌") or a reference to one of
these icons as "svg:<key>". render_html() turns either into inline HTML.
"""

import html as _html

# key -> inner SVG markup. All drawn for a 24x24 viewBox with stroke=currentColor,
# fill=none, stroke-width=2 (set by _SVG_OPEN below). Targeting recognition at the
# ~18px display size used in the items list — favour silhouettes over detail.
ICON_SET = {
    # RJ45 patch cable plug: trapezoid body, two pin slots, cable trailing down.
    "network-cable": '<path d="M10 4h4l1 2v8h-6V6z"/><path d="M11 6v3M13 6v3"/><path d="M12 14v7"/>',
    # 2-prong wall plug: prongs up, body, cable down.
    "power-plug": '<path d="M10 4v4M14 4v4"/><rect x="7" y="8" width="10" height="6" rx="1"/><path d="M12 14v7"/>',
    # Two barrel-style connectors meeting in the middle.
    "connector": '<rect x="2" y="9" width="9" height="6" rx="1"/><rect x="13" y="9" width="9" height="6" rx="1"/><path d="M11 12h2"/>',
    # AC power brick: cable in one side, barrel jack out the other.
    "adapter": '<rect x="6" y="9" width="10" height="6" rx="1.5"/><path d="M6 12H3M16 12h2"/><circle cx="20" cy="12" r="1.5"/>',
    # Single-cell battery: body, terminal nub, three charge bars.
    "battery": '<rect x="3" y="7" width="16" height="10" rx="1"/><path d="M19 10v4h2v-4z"/><path d="M6 10v4M10 10v4M14 10v4"/>',
    # External drive: enclosure with status LED + label line.
    "drive": '<rect x="3" y="9" width="18" height="9" rx="1.5"/><circle cx="7" cy="13.5" r="1"/><path d="M11 13.5h7"/>',
    # Two-unit server rack: each unit has an LED + ventilation slots.
    "server": '<rect x="3" y="4" width="18" height="7" rx="1"/><rect x="3" y="13" width="18" height="7" rx="1"/><circle cx="7" cy="7.5" r="1"/><circle cx="7" cy="16.5" r="1"/><path d="M11 7.5h8M11 16.5h8"/>',
    # Network switch/router: ports across the front + small antenna up top.
    "router": '<rect x="3" y="12" width="18" height="7" rx="1"/><path d="M7 15.5v1M11 15.5v1M15 15.5v1M19 15.5v1"/><path d="M12 12V7M9 5l3-2 3 2"/>',
    # Broadcast antenna: mast with two signal arcs and base dot.
    "antenna": '<path d="M12 12v9"/><circle cx="12" cy="12" r="1.5"/><path d="M9 8a4 4 0 0 1 6 0M6 5a8 8 0 0 1 12 0"/>',
    # Wi-Fi: classic concentric arcs above a dot.
    "wifi": '<path d="M5 12a10 10 0 0 1 14 0"/><path d="M8 15.5a5 5 0 0 1 8 0"/><circle cx="12" cy="19" r="1"/>',
    # Hex-head bolt with threaded shaft (thread cross-hatches).
    "bolt": '<path d="M8 4l4-2 4 2v3l-4 2-4-2z"/><path d="M10 9v12M14 9v12"/><path d="M10 12h4M10 15h4M10 18h4"/>',
    # Open-end wrench at 45°.
    "wrench": '<path d="M15 3a5 5 0 0 0-4.6 6.9L3 17.5 5.5 20l7.6-7.6A5 5 0 0 0 20 8l-2.8 2.8-2-2L17 6z"/>',
    # Flathead screwdriver: handle + shaft + tip.
    "screwdriver": '<rect x="14" y="3" width="7" height="4" rx="1" transform="rotate(45 17.5 5)"/><path d="M13 8l-9 9v4h4l9-9"/>',
    # Lightbulb: bulb, base lines, filament dot.
    "bulb": '<path d="M9 21h6M10 18h4"/><path d="M12 3a6 6 0 0 1 4 10.4l-1 1.6v2.5h-6V15l-1-1.6A6 6 0 0 1 12 3z"/>',
    # Cube / shipping box.
    "box": '<path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>',
    # Printer: paper top, body with output slot, output tray.
    "printer": '<rect x="6" y="3" width="12" height="6"/><path d="M4 9h16v7a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/>',
    # Keyboard: rectangle with three rows of key dots and a spacebar.
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="6" cy="10" r=".8"/><circle cx="10" cy="10" r=".8"/><circle cx="14" cy="10" r=".8"/><circle cx="18" cy="10" r=".8"/><path d="M7 14h10"/>',
    # Computer mouse: tall pill shape + scroll-wheel hint.
    "mouse": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v3"/>',
    # Smartphone: body, speaker slit, home button.
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M9 5h6"/><circle cx="12" cy="19" r="1"/>',
    # Toolbox: body, handle on top, separator line.
    "tool": '<rect x="3" y="9" width="18" height="11" rx="1"/><path d="M9 9V6h6v3"/><path d="M3 13h18"/>',
}

# Ordered list shown in the icon dropdown
ICON_CHOICES = [
    ("network-cable", "Network / Ethernet cable"),
    ("power-plug", "Power cord / plug"),
    ("connector", "Connector / coupler"),
    ("adapter", "Adapter / power brick"),
    ("battery", "Battery"),
    ("drive", "Drive / disk"),
    ("server", "Server"),
    ("router", "Router / switch"),
    ("antenna", "Antenna"),
    ("wifi", "Wi-Fi / wireless"),
    ("bolt", "Fastener / bolt"),
    ("wrench", "Wrench"),
    ("screwdriver", "Screwdriver"),
    ("tool", "Tool / part"),
    ("bulb", "Bulb / lighting"),
    ("box", "Box / misc"),
    ("printer", "Printer"),
    ("keyboard", "Keyboard"),
    ("mouse", "Mouse"),
    ("phone", "Phone"),
]

_SVG_OPEN = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">')


def render_html(value: str) -> str:
    if not value:
        return ""
    if value.startswith("svg:"):
        inner = ICON_SET.get(value[4:])
        return f"{_SVG_OPEN}{inner}</svg>" if inner else ""
    return f'<span class="emoji-ico">{_html.escape(value)}</span>'
