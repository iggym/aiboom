"""HTML and PDF rendering (spec F-HUMAN-2, F-HUMAN-3).

The HTML is one self-contained file with no external assets, because auditors
print it, mail it as an attachment, and archive it next to the audit evidence.
The PDF path uses WeasyPrint when the `[pdf]` extra is installed and otherwise
explains how to print the HTML — it never fails the command.
"""

from __future__ import annotations

import html
import json
from importlib import resources
from pathlib import Path
from typing import Any

from aibom.digest import digest_of
from aibom.errors import MissingDependencyError
from aibom.render.markdown import render_markdown
from aibom.render.md2html import convert, render_toc

DISCLAIMER = (
    "This document is evidence, not a compliance conclusion. It records what the "
    "system uses; it does not assert that the system is compliant with any framework."
)


def _template() -> str:
    return (
        resources.files("aibom.render.templates")
        .joinpath("aibom.html.j2")
        .read_text(encoding="utf-8")
    )


def _prop_map(component: dict[str, Any]) -> dict[str, str]:
    return {
        p["name"]: p.get("value", "")
        for p in component.get("properties") or []
        if isinstance(p, dict) and p.get("name")
    }


def render_html(bom: dict[str, Any]) -> str:
    """Render a self-contained, print-optimised HTML document."""
    markdown = render_markdown(bom)
    body, toc = convert(markdown, collect_toc=True)

    metadata = bom.get("metadata") or {}
    app = metadata.get("component") or {}
    app_props = _prop_map(app)
    tools = metadata.get("tools") or {}
    generator = "aibom"
    if isinstance(tools, dict):
        for component in tools.get("components") or []:
            if component.get("name") == "aibom":
                generator = f"aibom {component.get('version', '')}".strip()

    subtitle_bits = []
    if app.get("version"):
        subtitle_bits.append(f"v{app['version']}")
    if app_props.get("aibom:risk_label"):
        subtitle_bits.append(f"{app_props.get('aibom:risk_framework', 'risk')}: {app_props['aibom:risk_label']}")
    if app_props.get("aibom:owner"):
        subtitle_bits.append(f"owner {app_props['aibom:owner']}")
    if metadata.get("timestamp"):
        subtitle_bits.append(str(metadata["timestamp"]))

    replacements = {
        "{{ title }}": html.escape(f"AI BOM — {app.get('name', 'system')}"),
        "{{ spec_version }}": html.escape(str(bom.get("specVersion", "1.6"))),
        "{{ system_name }}": html.escape(str(app.get("name", "AI system"))),
        "{{ subtitle }}": html.escape(" · ".join(subtitle_bits) or "AI Bill of Materials"),
        "{{ toc }}": render_toc(toc),
        "{{ body }}": body,
        "{{ generator }}": html.escape(generator),
        "{{ digest }}": html.escape(digest_of(bom)),
        "{{ rules_version }}": html.escape(str(app_props.get("aibom:rules_version", "unknown"))),
        "{{ disclaimer }}": html.escape(DISCLAIMER),
    }
    document = _template()
    for needle, value in replacements.items():
        document = document.replace(needle, value)
    return document


def render_html_from_file(path: Path) -> str:
    return render_html(json.loads(path.read_text(encoding="utf-8")))


# --- PDF ----------------------------------------------------------------------


def weasyprint_available() -> bool:
    try:
        import weasyprint  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001 - weasyprint raises on missing system libs
        return False
    return True


PRINT_INSTRUCTIONS = (
    "PDF output needs WeasyPrint. Install it with `pip install 'aibom[pdf]'` "
    "(it also needs Pango/cairo system libraries), then re-run. "
    "Alternatively open the HTML output and print to PDF — the stylesheet already "
    "has print rules and a table of contents."
)


def render_pdf(bom: dict[str, Any], target: Path) -> Path:
    """Write ``target`` as a PDF. Raises `MissingDependencyError` without WeasyPrint."""
    if not weasyprint_available():
        raise MissingDependencyError(
            "WeasyPrint is not available, so --pdf cannot run",
            hint=PRINT_INSTRUCTIONS,
        )
    from weasyprint import HTML  # type: ignore

    document = render_html(bom)
    HTML(string=document, base_url=str(target.parent)).write_pdf(str(target))
    return target


def render_pdf_from_file(path: Path, target: Path) -> Path:
    return render_pdf(json.loads(path.read_text(encoding="utf-8")), target)
