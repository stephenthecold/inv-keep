"""Built-in line-icon set for items (crisp SVG, scales + prints).

An item's `icon` field holds either an emoji (e.g. "🔌") or a reference to one of
these icons as "svg:<key>". render_html() turns either into inline HTML.
"""

import html as _html

# key -> inner SVG markup (24x24 viewBox, stroke=currentColor, no fill)
ICON_SET = {
    "network-cable": '<rect x="7" y="9" width="10" height="12" rx="1"/><path d="M9 9V7a3 3 0 0 1 6 0v2"/><path d="M9.5 12v2M12 12v2M14.5 12v2"/>',
    "power-plug": '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    "connector": '<rect x="3" y="9" width="5" height="6" rx="1"/><rect x="16" y="9" width="5" height="6" rx="1"/><path d="M8 12h8"/>',
    "adapter": '<rect x="4" y="8" width="12" height="8" rx="1"/><path d="M16 12h4"/><path d="M8 8V6M12 8V6"/>',
    "battery": '<rect x="3" y="8" width="16" height="8" rx="1"/><path d="M21 11v2"/><path d="M7 12h2M12 12h2"/>',
    "drive": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="12" r="3"/>',
    "server": '<rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><path d="M7 7h.01M7 17h.01"/>',
    "router": '<rect x="3" y="13" width="18" height="6" rx="1"/><path d="M7 16h.01M11 16h.01"/><path d="M12 13V8M12 8l-3-3M12 8l3-3"/>',
    "antenna": '<path d="M12 8v13"/><circle cx="12" cy="6" r="2"/><path d="M7 11a7 7 0 0 1 10 0"/>',
    "wifi": '<path d="M5 12a10 10 0 0 1 14 0"/><path d="M8.5 15.5a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/>',
    "bolt": '<path d="M8 4h8l4 8-4 8H8l-4-8z"/><circle cx="12" cy="12" r="3"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-2.4z"/>',
    "screwdriver": '<path d="M14 4l6 6-3 3-6-6z"/><path d="M11 7l-8 8v6h6l8-8"/>',
    "bulb": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10c1 1 1 2 1 3h6c0-1 0-2 1-3a6 6 0 0 0-4-10z"/>',
    "box": '<path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>',
    "printer": '<rect x="6" y="3" width="12" height="5"/><path d="M6 18H5a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-1"/><rect x="7" y="15" width="10" height="6"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>',
    "mouse": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v3"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "tool": '<path d="M14 7a4 4 0 0 1-5 5l-5 5 2 2 5-5a4 4 0 0 1 5-5z"/>',
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
