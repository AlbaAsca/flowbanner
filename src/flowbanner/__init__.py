"""Mermaid-style text to animated, self-contained SVG banners."""

from .parser import DiagramError, parse
from .render import load_theme, render

__all__ = ["DiagramError", "build", "load_theme", "parse", "render"]


def build(source: str) -> str:
    """Turn banner source text into an SVG document."""
    return render(parse(source))
