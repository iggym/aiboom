"""Documentation invariants (spec §10).

The risk-rules page is generated from the rulebook YAML so the docs cannot
drift from the code that runs. These tests are the enforcement.
"""

from __future__ import annotations

from pathlib import Path

from aibom.risk.docs import docs_path, render_rulebook_markdown

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_risk_rules_doc_is_current() -> None:
    """`docs/risk-rules.md` must match the rulebook it is generated from."""
    target = docs_path()
    assert target.exists(), "docs/risk-rules.md is missing; run `python -m aibom.risk.docs`"
    assert target.read_text(encoding="utf-8") == render_rulebook_markdown(), (
        "docs/risk-rules.md is stale; run `python -m aibom.risk.docs`"
    )


def test_risk_rules_doc_lists_every_rule_and_package() -> None:
    from aibom.risk import load_rulebook

    book = load_rulebook()
    rendered = render_rulebook_markdown(book)
    for rule in book.rules:
        assert f"`{rule['id']}`" in rendered
    for entry in book.packages:
        assert f"`{entry['package']}`" in rendered


def test_docs_links_resolve() -> None:
    """Every relative Markdown link in docs/ points at a file that exists."""
    import re

    missing: list[str] = []
    for page in DOCS.rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+\.md)\)", text):
            if target.startswith(("http://", "https://")):
                continue
            resolved = (page.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{page.relative_to(DOCS)} -> {target}")
    assert not missing, f"broken doc links: {missing}"


def test_readme_links_resolve() -> None:
    import re

    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    missing: list[str] = []
    for target in re.findall(r"\]\(([^)#]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (readme.parent / target).resolve().exists():
            missing.append(target)
    assert not missing, f"broken README links: {missing}"
