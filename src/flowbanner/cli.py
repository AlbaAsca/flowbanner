"""Command line: flowbanner build INPUT... [-o OUTPUT] [--check]"""

import argparse
import sys
from pathlib import Path

from .parser import DiagramError, parse
from .render import load_theme, render


def _build_one(source: Path, target: Path, theme_name: str | None, check: bool) -> bool:
    """Write the banner, or with check compare it. Returns whether it was up to date."""
    diagram = parse(source.read_text(encoding="utf-8"))
    svg = render(diagram, load_theme(theme_name) if theme_name else None)
    current = target.read_text(encoding="utf-8") if target.exists() else None
    if check:
        if current != svg:
            print(f"out of date: {target}", file=sys.stderr)
        return current == svg
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as file:
        file.write(svg)
    print(f"{source} -> {target}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flowbanner", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="render .mmd files to .svg")
    build.add_argument("inputs", nargs="+", type=Path, metavar="INPUT")
    build.add_argument("-o", "--output", type=Path, help="output file (single input only)")
    build.add_argument("--theme", help="bundled theme name or path to a .json theme")
    build.add_argument("--check", action="store_true", help="fail if an output is out of date")
    args = parser.parse_args(argv)

    if args.output and len(args.inputs) > 1:
        parser.error("-o/--output needs a single input")

    all_current = True
    for source in args.inputs:
        target = args.output or source.with_suffix(".svg")
        try:
            all_current &= _build_one(source, target, args.theme, args.check)
        except (DiagramError, OSError) as error:
            print(f"{source}: {error}", file=sys.stderr)
            return 2
    return 0 if all_current else 1
