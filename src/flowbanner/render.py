"""SVG output. Everything is inline: GitHub only shows SVGs loaded through <img>."""

import json
from importlib import resources
from pathlib import Path
from xml.sax.saxutils import escape

from .layout import BACK_EDGE_DEPTH, Box, Layout, compute_layout, walk_paths
from .parser import Diagram, DiagramError

FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
SECONDS_PER_EDGE = 1.0
MIN_DURATION = 2.0
MAX_PACKETS = 3


def load_theme(name: str = "tokyo-night") -> dict:
    """Load a bundled theme by name, or a JSON file by path."""
    try:
        if name.endswith(".json"):
            return json.loads(Path(name).read_text(encoding="utf-8"))
        bundled = resources.files("flowbanner") / "themes" / f"{name}.json"
        return json.loads(bundled.read_text(encoding="utf-8"))
    except OSError as error:
        raise DiagramError(f"cannot load theme {name!r}: {error}") from None


def _num(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _node_color(diagram: Diagram, theme: dict, node_id: str) -> str:
    name = diagram.nodes[node_id].color or theme["default_color"]
    if name not in theme["colors"]:
        raise DiagramError(
            f"node {node_id!r} uses unknown color {name!r} "
            f"(available: {', '.join(sorted(theme['colors']))})"
        )
    return theme["colors"][name]


def _style(theme: dict) -> str:
    return f"""    <style>
      .node {{ fill: {theme['node_fill']}; stroke-width: 2; }}
      .label {{ fill: {theme['text']}; font-size: 17px; font-weight: 600; text-anchor: middle; }}
      .sub {{ fill: {theme['muted']}; font-size: 13px; text-anchor: middle; }}
      .edge {{ fill: {theme['muted']}; font-size: 12px; text-anchor: middle; }}
      .flow {{ fill: none; stroke-width: 2.5; stroke-dasharray: 6 8; animation: dash 1.2s linear infinite; }}
      .dotted {{ stroke-dasharray: 2 7; opacity: .75; }}
      @keyframes dash {{ to {{ stroke-dashoffset: -28; }} }}
      .ping {{ animation: ping 3s ease-out infinite; transform-box: fill-box; transform-origin: center; }}
      @keyframes ping {{ 0% {{ opacity: .9; transform: scale(1); }} 70%, 100% {{ opacity: 0; transform: scale(1.35); }} }}
      @media (prefers-reduced-motion: reduce) {{
        .flow, .ping {{ animation: none; }}
        .ping, .packet {{ display: none; }}
      }}
    </style>"""


def _segment(src: Box, dst: Box) -> str:
    """Path from the right side of src to the left side of dst, without the M."""
    if src.cy == dst.cy:
        return f"H{_num(dst.x)}"
    mid = _num((src.right + dst.x) / 2)
    return f"C{mid} {_num(src.cy)}, {mid} {_num(dst.cy)}, {_num(dst.x)} {_num(dst.cy)}"


def _back_path(src: Box, dst: Box) -> str:
    return (
        f"M{_num(src.cx)} {_num(src.bottom)} "
        f"C{_num(src.cx)} {_num(src.bottom + BACK_EDGE_DEPTH)}, "
        f"{_num(dst.cx)} {_num(dst.bottom + BACK_EDGE_DEPTH)}, "
        f"{_num(dst.cx)} {_num(dst.bottom)}"
    )


def _edges(layout: Layout, colors: dict[str, str]) -> list[str]:
    out = []
    for edge, back in [(e, False) for e in layout.forward] + [(e, True) for e in layout.back]:
        src, dst = layout.boxes[edge.src], layout.boxes[edge.dst]
        path = (
            _back_path(src, dst)
            if back
            else f"M{_num(src.right)} {_num(src.cy)} {_segment(src, dst)}"
        )
        css = "flow dotted" if edge.dotted else "flow"
        out.append(f'  <path class="{css}" stroke="{colors[edge.src]}" d="{path}"/>')
    return out


def _edge_labels(layout: Layout) -> list[str]:
    out = []
    for edge, back in [(e, False) for e in layout.forward] + [(e, True) for e in layout.back]:
        if not edge.label:
            continue
        src, dst = layout.boxes[edge.src], layout.boxes[edge.dst]
        if back:
            x = (src.cx + dst.cx) / 2
            y = max(src.bottom, dst.bottom) + BACK_EDGE_DEPTH * 0.75 + 16
        else:
            x = (src.right + dst.x) / 2
            y = (src.cy + dst.cy) / 2 - 10
        out.append(f'  <text class="edge" x="{_num(x)}" y="{_num(y)}">{escape(edge.label)}</text>')
    return out


def _packet_group(path_d: str, colors: list[str], edge_count: int) -> list[str]:
    duration = max(MIN_DURATION, edge_count * SECONDS_PER_EDGE)
    count = MAX_PACKETS if edge_count >= 3 else 1
    out = []
    for i in range(count):
        radius = 6 if i == 0 else 5
        color = colors[i % len(colors)]
        # A negative begin keeps the packet on its route from the first frame;
        # a positive one would leave it at (0, 0) until the animation starts.
        begin = _num(-i * duration / count)
        out.append(
            f'  <circle class="packet" r="{radius}" fill="{color}">'
            f'<animateMotion dur="{_num(duration)}s" begin="{begin}s" '
            f'repeatCount="indefinite" path="{path_d}"/></circle>'
        )
    return out


def _packets(layout: Layout, colors: dict[str, str]) -> list[str]:
    out = []
    for path in walk_paths(layout):
        first = layout.boxes[path[0].src]
        d = [f"M{_num(first.cx)} {_num(first.cy)} H{_num(first.right)}"]
        for edge in path:
            src, dst = layout.boxes[edge.src], layout.boxes[edge.dst]
            d.append(_segment(src, dst))
            d.append(f"H{_num(dst.right if edge is not path[-1] else dst.cx)}")
        # Distinct colours along the route, skipping the repeats.
        route = [path[0].src] + [edge.dst for edge in path]
        palette = list(dict.fromkeys(colors[node_id] for node_id in route))
        out.extend(_packet_group(" ".join(d), palette, len(path)))
    for edge in layout.back:
        src, dst = layout.boxes[edge.src], layout.boxes[edge.dst]
        out.extend(_packet_group(_back_path(src, dst), [colors[edge.src]], 1))
    return out


def _node(box: Box, lines: list[str], color: str, pulse: bool) -> list[str]:
    geometry = (
        f'x="{_num(box.x)}" y="{_num(box.y)}" width="{_num(box.w)}" '
        f'height="{_num(box.h)}" rx="14" stroke="{color}"'
    )
    out = []
    if pulse:
        out.append(f'  <rect class="node ping" {geometry}/>')
    out.append(f'  <rect class="node" {geometry}/>')
    baseline = box.y + (box.h / 2 + 6 if len(lines) == 1 else 39)
    for i, line in enumerate(lines):
        css = "label" if i == 0 else "sub"
        out.append(
            f'  <text class="{css}" x="{_num(box.cx)}" y="{_num(baseline + i * 24)}">'
            f"{escape(line)}</text>"
        )
    return out


def render(diagram: Diagram, theme: dict | None = None) -> str:
    if theme is None:
        theme = load_theme(diagram.meta.get("theme", "tokyo-night"))
    layout = compute_layout(diagram)
    colors = {node_id: _node_color(diagram, theme, node_id) for node_id in diagram.nodes}
    pulse = {part.strip() for part in diagram.meta.get("pulse", "").split(",")}
    w, h = layout.width, layout.height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" font-family="{FONT}">',
        "  <defs>",
        f'    <linearGradient id="title" x1="0" x2="1"><stop offset="0" stop-color="{theme["title_from"]}"/>'
        f'<stop offset="1" stop-color="{theme["title_to"]}"/></linearGradient>',
        '    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">',
        f'      <path d="M40 0H0V40" fill="none" stroke="{theme["grid"]}" stroke-width="1"/>',
        "    </pattern>",
        _style(theme),
        "  </defs>",
        f'  <rect width="{w}" height="{h}" rx="18" fill="{theme["background"]}"/>',
        f'  <rect width="{w}" height="{h}" rx="18" fill="url(#grid)" opacity="0.6"/>',
    ]
    fills = {
        "title": 'font-weight="800" fill="url(#title)"',
        "subtitle": f'fill="{theme["text"]}"',
        "stack": f'fill="{theme["muted"]}"',
    }
    for key, line in layout.header.items():
        parts.append(
            f'  <text x="{_num(line.x)}" y="{_num(line.y)}" font-size="{_num(line.size)}" '
            f"{fills[key]}>{escape(line.text)}</text>"
        )
    parts += _edges(layout, colors)
    parts += _packets(layout, colors)
    for node_id, box in layout.boxes.items():
        parts += _node(box, diagram.nodes[node_id].lines, colors[node_id], node_id in pulse)
    parts += _edge_labels(layout)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
