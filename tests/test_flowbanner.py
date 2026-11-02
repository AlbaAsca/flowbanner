import re
from pathlib import Path

import pytest

from flowbanner import DiagramError, build, parse
from flowbanner.cli import main
from flowbanner.layout import compute_layout

ROOT = Path(__file__).resolve().parent.parent
CHAIN = "flowchart LR\n  A[One<br/>uno]:::cyan --> B[Two]:::amber --> C[Three]\n"


def test_parses_chain_labels_and_colors():
    diagram = parse(CHAIN)
    assert diagram.nodes["A"].lines == ["One", "uno"]
    assert diagram.nodes["A"].color == "cyan"
    assert [(e.src, e.dst) for e in diagram.edges] == [("A", "B"), ("B", "C")]


def test_parses_frontmatter_with_colons_in_values():
    diagram = parse("---\ntitle: a: b\n---\n" + CHAIN)
    assert diagram.meta["title"] == "a: b"


def test_parses_edge_label_dotted_and_comment():
    diagram = parse("graph LR\n  %% note\n  A -.->|sse| B %% tail\n")
    assert diagram.edges[0].dotted and diagram.edges[0].label == "sse"


@pytest.mark.parametrize(
    "source, message",
    [
        ("flowchart TD\nA --> B\n", "only left-to-right"),
        ("A --> B\n", "expected 'flowchart LR'"),
        ("flowchart LR\nA ==> B\n", "line 2: unsupported syntax"),
        ("flowchart LR\nsubgraph x\n", "line 2: unsupported syntax"),
        ("flowchart LR\nA --> A\n", "links to itself"),
        ("flowchart LR\n", "no nodes"),
        ("---\nfoo: 1\n---\nflowchart LR\nA\n", "unknown frontmatter"),
        ("---\ntitle: x\n", "never closed"),
        ("---\npulse: Z\n---\nflowchart LR\nA\n", "unknown node"),
    ],
)
def test_rejects_invalid_source(source, message):
    with pytest.raises(DiagramError, match=message):
        parse(source)


def test_rejects_unknown_color():
    with pytest.raises(DiagramError, match="unknown color"):
        build("flowchart LR\nA:::pink\n")


def test_rejects_columns_that_do_not_fit():
    source = "flowchart LR\n" + " --> ".join(f"N{i}" for i in range(12)) + "\n"
    with pytest.raises(DiagramError, match="do not fit"):
        build(source)


def test_store_sales_geometry_matches_the_hand_drawn_banner():
    source = (ROOT / "examples/store-sales-forecasting.mmd").read_text(encoding="utf-8")
    layout = compute_layout(parse(source))
    assert (layout.width, layout.height) == (1200, 400)
    assert [box.x for box in layout.boxes.values()] == [50, 290, 530, 770, 1010]
    assert {box.y for box in layout.boxes.values()} == {245}


def test_branch_uses_two_rows_in_the_same_column():
    layout = compute_layout(parse("flowchart LR\nA --> B\nA --> C\n"))
    b, c = layout.boxes["B"], layout.boxes["C"]
    assert b.x == c.x and b.y < c.y


def test_cycle_is_drawn_as_back_edge():
    layout = compute_layout(parse("flowchart LR\nA --> B\nB --> A\n"))
    assert [(e.src, e.dst) for e in layout.back] == [("B", "A")]
    assert layout.boxes["A"].layer == 0


def test_escapes_xml_in_text():
    svg = build('flowchart LR\nA["a < b & c"]\n')
    assert "a &lt; b &amp; c" in svg


def test_packets_never_wait_at_the_origin():
    svg = build(CHAIN + "C --> D --> E\n")
    begins = [float(value) for value in re.findall(r'begin="(-?[\d.]+)s"', svg)]
    assert begins and all(value <= 0 for value in begins)


def test_packets_are_always_shown():
    svg = build(CHAIN)
    assert "<animateMotion" in svg and "prefers-reduced-motion" not in svg


def test_output_is_self_contained_and_deterministic():
    assert build(CHAIN) == build(CHAIN)
    assert "<script" not in build(CHAIN) and "href" not in build(CHAIN)


def test_long_title_shrinks_to_fit():
    layout = compute_layout(parse("---\ntitle: " + "x" * 80 + "\n---\nflowchart LR\nA\n"))
    assert layout.header["title"].size < 54


def test_custom_theme_file(tmp_path):
    theme = tmp_path / "t.json"
    theme.write_text(
        '{"background":"#000001","grid":"#000002","title_from":"#000003","title_to":"#000004",'
        '"node_fill":"#000005","text":"#000006","muted":"#000007","default_color":"a",'
        '"colors":{"a":"#000008"}}',
        encoding="utf-8",
    )
    source = tmp_path / "x.mmd"
    source.write_text("flowchart LR\nA\n", encoding="utf-8")
    assert main(["build", str(source), "--theme", str(theme)]) == 0
    assert "#000008" in source.with_suffix(".svg").read_text(encoding="utf-8")


def test_cli_check_detects_stale_output(tmp_path, capsys):
    source = tmp_path / "x.mmd"
    source.write_text(CHAIN, encoding="utf-8")
    assert main(["build", str(source), "--check"]) == 1
    assert main(["build", str(source)]) == 0
    assert main(["build", str(source), "--check"]) == 0


def test_cli_reports_errors_with_the_file_name(tmp_path, capsys):
    source = tmp_path / "bad.mmd"
    source.write_text("nope\n", encoding="utf-8")
    assert main(["build", str(source)]) == 2
    assert "bad.mmd" in capsys.readouterr().err
