"""Layered left-to-right layout: columns by longest path, rows by barycentre."""

from dataclasses import dataclass

from .parser import Diagram, DiagramError, Edge

MARGIN_LEFT = 50
MARGIN_RIGHT = 40
MIN_NODE_WIDTH = 150
NODE_PADDING = 24
MIN_GAP = 40
MAX_GAP = 240
ROW_GAP = 30
BASE_NODE_HEIGHT = 90
LINE_HEIGHT = 24
HEADER_TO_FLOW = 83
BOTTOM_WITH_HEADER = 65
BOTTOM_PLAIN = 50
TOP_PLAIN = 50
BACK_EDGE_DEPTH = 70
BACK_EDGE_ROOM = 40

LABEL_SIZE = 17
SUB_SIZE = 13
# (font size, baseline) of the title, subtitle and stack lines.
HEADER_LINES = {"title": (54, 92), "subtitle": (22, 132), "stack": (16, 162)}
HEADER_LEFT = {"title": 60, "subtitle": 62, "stack": 62}
HEADER_RIGHT_MARGIN = 60


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Rough width: the SVG is rendered by the viewer, so it cannot be measured here."""
    return len(text) * size * (0.56 if bold else 0.5)


@dataclass
class Box:
    id: str
    x: float
    y: float
    w: float
    h: float
    layer: int
    row: int

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class HeaderLine:
    text: str
    x: float
    y: float
    size: float


@dataclass
class Layout:
    width: int
    height: int
    boxes: dict[str, Box]
    forward: list[Edge]
    back: list[Edge]
    header: dict[str, HeaderLine]


def split_back_edges(diagram: Diagram) -> tuple[list[Edge], list[Edge]]:
    """Separate the edges that close a cycle, so the rest form a DAG."""
    outgoing: dict[str, list[Edge]] = {node_id: [] for node_id in diagram.nodes}
    for edge in diagram.edges:
        outgoing[edge.src].append(edge)
    back: set[int] = set()
    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for edge in outgoing[node_id]:
            if state.get(edge.dst) == 1:
                back.add(id(edge))
            elif edge.dst not in state:
                visit(edge.dst)
        state[node_id] = 2

    for node_id in diagram.nodes:
        if node_id not in state:
            visit(node_id)
    return (
        [edge for edge in diagram.edges if id(edge) not in back],
        [edge for edge in diagram.edges if id(edge) in back],
    )


def _assign_layers(diagram: Diagram, forward: list[Edge]) -> dict[str, int]:
    layers = {node_id: 0 for node_id in diagram.nodes}
    for _ in diagram.nodes:
        changed = False
        for edge in forward:
            if layers[edge.dst] < layers[edge.src] + 1:
                layers[edge.dst] = layers[edge.src] + 1
                changed = True
        if not changed:
            break
    return layers


def _order_rows(diagram, forward, layers) -> list[list[str]]:
    columns: list[list[str]] = [[] for _ in range(max(layers.values()) + 1)]
    for node_id in diagram.nodes:
        columns[layers[node_id]].append(node_id)
    rows: dict[str, int] = {}
    for column in columns:
        def barycentre(node_id: str) -> float:
            parents = [rows[e.src] for e in forward if e.dst == node_id]
            return sum(parents) / len(parents) if parents else 0

        column.sort(key=barycentre)
        rows.update({node_id: row for row, node_id in enumerate(column)})
    return columns


def _column_widths(diagram, columns) -> list[float]:
    widths = []
    for column in columns:
        needed = MIN_NODE_WIDTH
        for node_id in column:
            lines = diagram.nodes[node_id].lines
            needed = max(needed, text_width(lines[0], LABEL_SIZE, bold=True) + NODE_PADDING)
            for line in lines[1:]:
                needed = max(needed, text_width(line, SUB_SIZE) + NODE_PADDING)
        widths.append(needed)
    return widths


def _column_positions(widths: list[float], width: int) -> list[float]:
    available = width - MARGIN_LEFT - MARGIN_RIGHT
    used = sum(widths)
    if len(widths) == 1:
        return [MARGIN_LEFT + (available - used) / 2]
    gap = (available - used) / (len(widths) - 1)
    if gap < MIN_GAP:
        raise DiagramError(
            f"{len(widths)} columns do not fit in {width}px: "
            "shorten the labels or raise 'width' in the frontmatter"
        )
    gap = min(gap, MAX_GAP)
    x = MARGIN_LEFT + (available - used - gap * (len(widths) - 1)) / 2
    positions = []
    for column_width in widths:
        positions.append(x)
        x += column_width + gap
    return positions


def _layout_header(meta: dict[str, str], width: int) -> dict[str, HeaderLine]:
    header = {}
    for key, (size, y) in HEADER_LINES.items():
        text = meta.get(key)
        if not text:
            continue
        room = width - HEADER_LEFT[key] - HEADER_RIGHT_MARGIN
        fitted = min(size, size * room / text_width(text, size, bold=key == "title"))
        header[key] = HeaderLine(text, HEADER_LEFT[key], y, round(fitted, 1))
    return header


def compute_layout(diagram: Diagram) -> Layout:
    try:
        width = int(diagram.meta.get("width", 1200))
    except ValueError:
        raise DiagramError(f"width must be a number, got {diagram.meta['width']!r}") from None

    forward, back = split_back_edges(diagram)
    layers = _assign_layers(diagram, forward)
    columns = _order_rows(diagram, forward, layers)
    widths = _column_widths(diagram, columns)
    positions = _column_positions(widths, width)

    max_lines = max(len(node.lines) for node in diagram.nodes.values())
    node_h = BASE_NODE_HEIGHT + max(0, max_lines - 2) * LINE_HEIGHT
    tallest = max(len(column) for column in columns)
    flow_h = tallest * node_h + (tallest - 1) * ROW_GAP

    header = _layout_header(diagram.meta, width)
    if header:
        top = max(line.y for line in header.values()) + HEADER_TO_FLOW
        bottom = BOTTOM_WITH_HEADER
    else:
        top = TOP_PLAIN
        bottom = BOTTOM_PLAIN
    if back:
        bottom += BACK_EDGE_ROOM

    boxes = {}
    for layer, column in enumerate(columns):
        offset = (flow_h - (len(column) * node_h + (len(column) - 1) * ROW_GAP)) / 2
        for row, node_id in enumerate(column):
            y = top + offset + row * (node_h + ROW_GAP)
            boxes[node_id] = Box(node_id, positions[layer], y, widths[layer], node_h, layer, row)
    return Layout(width, int(top + flow_h + bottom), boxes, forward, back, header)


def walk_paths(layout: Layout) -> list[list[Edge]]:
    """Cover the forward edges with paths, so packets travel whole routes."""
    remaining = list(layout.forward)
    paths = []
    while remaining:
        current = remaining.pop(0)
        path = [current]
        while True:
            following = next((e for e in remaining if e.src == current.dst), None)
            if following is None:
                break
            remaining.remove(following)
            path.append(following)
            current = following
        paths.append(path)
    return paths
