"""Render tests (spec §7.2, F-HUMAN-1..4): Markdown sections, HTML smoke, XML.

The Markdown structure is a contract — auditors read it — so the section
headings are asserted, not just "some output was produced".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aibom.api import GenerateOptions, generate_full
from aibom.model.cyclonedx import json_to_xml, to_cyclonedx_xml
from aibom.render.html import render_html
from aibom.render.markdown import render_markdown

FIXTURES = Path(__file__).parent / "fixtures"

REQUIRED_SECTIONS = [
    "## System",
    "## Models",
    "## Tools",
    "## MCP servers",
    "## Prompts",
    "## Datasets",
    "## AI SDK versions",
    "## Dependency graph",
    "## Review notes",
    "## Provenance",
]


@pytest.fixture(scope="module")
def bom() -> dict:
    root = (FIXTURES / "support-agent").resolve()
    return generate_full(GenerateOptions(root=root, refresh=True))[0]


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_markdown_has_each_required_section(bom: dict, section: str) -> None:
    assert section in render_markdown(bom)


def test_markdown_has_a_title(bom: dict) -> None:
    first = render_markdown(bom).lstrip().splitlines()[0]
    assert first.startswith("# ")


def test_markdown_includes_a_mermaid_graph(bom: dict) -> None:
    text = render_markdown(bom)
    assert "```mermaid" in text
    assert "graph " in text or "flowchart " in text


def test_markdown_provenance_mentions_verify(bom: dict) -> None:
    text = render_markdown(bom)
    assert "aibom verify" in text


def test_markdown_does_not_break_tables_on_pipe_in_input(bom: dict) -> None:
    """A `|` in a descriptive field must be escaped, or the table is corrupt."""
    from aibom.render.markdown import _esc

    assert _esc("a | b") == "a \\| b"
    assert _esc(None) == ""


def test_html_is_a_single_document(bom: dict) -> None:
    html = render_html(bom)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "</html>" in html


def test_html_is_print_optimised(bom: dict) -> None:
    html = render_html(bom)
    assert "@media print" in html or "@page" in html


def test_html_has_a_table_of_contents(bom: dict) -> None:
    html = render_html(bom)
    assert "toc" in html.lower()


def test_html_has_no_script_tags(bom: dict) -> None:
    """A single-file, print-optimised report should not need JS."""
    html = render_html(bom)
    assert "<script" not in html.lower()


def test_html_escapes_model_names(bom: dict) -> None:
    bom = json.loads(json.dumps(bom))
    bom["components"][0]["name"] = "<script>alert(1)</script>"
    html = render_html(bom)
    assert "<script>alert(1)</script>" not in html


# --- XML ----------------------------------------------------------------------


def test_xml_parses_and_has_the_namespace(bom: dict) -> None:
    from lxml import etree

    xml = json_to_xml(bom)
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "{http://cyclonedx.org/schema/bom/1.6}bom"


def test_xml_declares_the_namespace_exactly_once(bom: dict) -> None:
    xml = json_to_xml(bom)
    # `xmlns` via nsmap plus a manual attribute yields a duplicate that
    # strict parsers reject; both forms count, so assert singleness.
    assert xml.count("xmlns=") == 1


def test_xml_carries_the_version(bom: dict) -> None:
    from lxml import etree

    doc = json.loads(json.dumps(bom))
    doc["version"] = 7
    root = etree.fromstring(json_to_xml(doc).encode("utf-8"))
    assert root.get("version") == "7"


def test_to_cyclonedx_xml_accepts_the_model(bom: dict) -> None:
    from aibom.api import GenerateOptions as GO
    from aibom.api import generate_full as gf

    root = (FIXTURES / "support-agent").resolve()
    _bom, model = gf(GO(root=root, refresh=True))
    xml = to_cyclonedx_xml(model, version=3)
    assert "<bom" in xml and xml.count("xmlns=") == 1


def test_render_markdown_from_file_round_trips(bom: dict, tmp_path: Path) -> None:
    from aibom.render.markdown import render_markdown_from_file

    path = tmp_path / "aibom.cdx.json"
    path.write_text(json.dumps(bom), encoding="utf-8")
    assert render_markdown_from_file(path) == render_markdown(bom)


def test_render_html_from_file_round_trips(bom: dict, tmp_path: Path) -> None:
    from aibom.render.html import render_html_from_file

    path = tmp_path / "aibom.cdx.json"
    path.write_text(json.dumps(bom), encoding="utf-8")
    assert render_html_from_file(path) == render_html(bom)
