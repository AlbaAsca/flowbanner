"""Parser for the frontmatter + Mermaid `flowchart LR` subset."""

import re
from dataclasses import dataclass, field

META_KEYS = {"title", "subtitle", "stack", "pulse", "theme", "width"}

_NODE = re.compile(r'([A-Za-z_]\w*)(?:\[(?:"([^"]*)"|([^\]"]*))\])?(?::::(\w+))?')
_LINK = re.compile(r"\s*(-->|-\.->)(?:\|([^|]*)\|)?\s*")
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HEADER = re.compile(r"(?:flowchart|graph)\s+(\S+)$")


class DiagramError(ValueError):
    """The source cannot be turned into a banner."""


@dataclass
class Node:
    id: str
    lines: list[str]
    color: str | None = None


@dataclass
class Edge:
    src: str
    dst: str
    label: str | None = None
    dotted: bool = False


@dataclass
class Diagram:
    meta: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


def _read_meta(lines: list[str]) -> tuple[dict[str, str], int]:
    """Return the frontmatter and the index of the first line after it."""
    start = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if start >= len(lines) or lines[start].strip() != "---":
        return {}, 0
    meta = {}
    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line == "---":
            return meta, i + 1
        if not line:
            continue
        key, colon, value = line.partition(":")
        key = key.strip()
        if not colon or key not in META_KEYS:
            raise DiagramError(
                f"line {i + 1}: unknown frontmatter entry {line!r} "
                f"(expected one of {', '.join(sorted(META_KEYS))})"
            )
        meta[key] = value.strip().strip('"')
    raise DiagramError(f"line {start + 1}: frontmatter is never closed with ---")


def _read_node(diagram: Diagram, text: str, pos: int, lineno: int) -> tuple[str, int]:
    match = _NODE.match(text, pos)
    if not match:
        raise DiagramError(f"line {lineno}: expected a node at {text[pos:]!r}")
    node_id, quoted, plain, color = match.groups()
    node = diagram.nodes.setdefault(node_id, Node(node_id, [node_id]))
    label = quoted if quoted is not None else plain
    if label is not None:
        node.lines = [part.strip() for part in _BREAK.split(label)]
    if color:
        node.color = color
    return node_id, match.end()


def _read_statement(diagram: Diagram, text: str, lineno: int) -> None:
    src, pos = _read_node(diagram, text, 0, lineno)
    while pos < len(text):
        link = _LINK.match(text, pos)
        if not link:
            raise DiagramError(f"line {lineno}: unsupported syntax at {text[pos:]!r}")
        dst, pos = _read_node(diagram, text, link.end(), lineno)
        if src == dst:
            raise DiagramError(f"line {lineno}: node {src!r} links to itself")
        diagram.edges.append(Edge(src, dst, link.group(2), link.group(1) == "-.->"))
        src = dst


def parse(source: str) -> Diagram:
    lines = source.splitlines()
    meta, first = _read_meta(lines)
    diagram = Diagram(meta=meta)
    seen_header = False
    for i in range(first, len(lines)):
        text = lines[i].split("%%", 1)[0].strip()
        if not text:
            continue
        lineno = i + 1
        if not seen_header:
            header = _HEADER.match(text)
            if not header:
                raise DiagramError(f"line {lineno}: expected 'flowchart LR', got {text!r}")
            if header.group(1) != "LR":
                raise DiagramError(f"line {lineno}: only left-to-right (LR) is supported")
            seen_header = True
            continue
        _read_statement(diagram, text, lineno)
    if not diagram.nodes:
        raise DiagramError("the diagram has no nodes")
    for node_id in _split(meta.get("pulse", "")):
        if node_id not in diagram.nodes:
            raise DiagramError(f"pulse refers to unknown node {node_id!r}")
    return diagram


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
