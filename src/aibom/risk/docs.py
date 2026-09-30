"""Generate `docs/risk-rules.md` from the rulebook YAML (spec §10).

The rulebook is the product's explanation surface, so its documentation is
rendered from the same files the classifier reads. If they could drift, the
docs would be the thing an auditor trusts and the code would be the thing that
runs — which is exactly backwards.

Run via `python -m aibom.risk.docs` (or `make docs`); CI asserts the committed
file matches.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aibom.risk.classifier import Rulebook, load_rulebook

PREAMBLE = """\
# Risk rules

This page is **generated** from `src/aibom/risk/rules/capabilities.yaml` and
`src/aibom/risk/rules/mcp-packages.yaml`. It cannot drift from the code that
runs: `make docs-check` fails if the committed file differs.

Every verdict `aibom` prints is reproducible. Run
`aibom explain-risk <tool>` (or `aibom explain-risk <mcp-server>`) to see the
rule ids that fired, the field they matched, and the evidence.

## How classification works

For each tool and MCP server, `aibom` builds a *haystack*:

| Field | Source |
| --- | --- |
| `identifier` | the tool/server name, split on case, `_`, `.` and `-` |
| `description` | the docstring / declared description |
| `parameters` | the parameter names of the tool function |
| `command` | an MCP server's command + args |
| `package` | an MCP server's npm/PyPI package name |

A rule declares one or more field regexes. By default the rule fires when **any**
declared field matches — the fields are alternative sources of the same evidence
(a `path` parameter *or* a `file`-ish name both mean filesystem access). A rule
that sets `match: all` requires **every** declared field to match, which is for
rules where one field qualifies the other (`bulk_*` is only destructive if the
description also says delete).

Rules are additive: a tool can hold several capabilities, and its risk is the
highest level among them. Curated MCP package entries act as a *floor* — they
add capabilities the name alone cannot reveal.

"""


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def _rules_section(book: Rulebook) -> str:
    out = ["## Capability rules", "", f"`rules_version: {book.rules_version}`", ""]
    out += [
        "| Rule | Capability | Risk | Match | Why |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rule in book.rules:
        rid = rule.get("id", "?")
        cap = rule.get("capability", "?")
        level = book.level(cap)
        match = str(rule.get("match", "any")).lower()
        why = _escape(str(rule.get("why", "")))
        out.append(f"| `{rid}` | {cap} | {level} | {match} | {why} |")
    out.append("")
    return "\n".join(out)


def _levels_section(book: Rulebook) -> str:
    out = ["## Risk levels", "", "| Capability | Level | Label |", "| --- | --- | --- |"]
    for capability, level in book.capability_levels.items():
        label = book.capability_labels.get(capability, capability)
        out.append(f"| `{capability}` | {level} | {label} |")
    out.append("")
    return "\n".join(out)


def _packages_section(book: Rulebook) -> str:
    out = [
        "## Curated MCP packages",
        "",
        f"`registry_version: {book.registry_version}` — {len(book.packages)} packages.",
        "",
        "These entries supply capabilities the server *name* cannot reveal (a",
        "`server-github` is a write + identity surface regardless of what its",
        "description says). They are a floor: the classifier still runs the rules",
        "above on top of them.",
        "",
        "| Package | Capabilities | Risk | Why |",
        "| --- | --- | --- | --- |",
    ]
    for entry in sorted(book.packages, key=lambda e: str(e.get("package", ""))):
        package = entry.get("package", "?")
        caps = ", ".join(entry.get("capabilities", []))
        risk = book.risk_of(entry.get("capabilities", []))
        why = _escape(str(entry.get("why", "")))
        out.append(f"| `{package}` | {caps} | {risk} | {why} |")
    out.append("")
    return "\n".join(out)


def render_rulebook_markdown(book: Rulebook | None = None) -> str:
    book = book or load_rulebook()
    return "\n".join(
        [
            PREAMBLE,
            _levels_section(book),
            _rules_section(book),
            _packages_section(book),
        ]
    ).rstrip() + "\n"


def docs_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "risk-rules.md"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    target = docs_path()
    rendered = render_rulebook_markdown()
    if check:
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            print(f"{target} is stale; run `python -m aibom.risk.docs`", file=sys.stderr)
            return 1
        print(f"{target} is up to date")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
