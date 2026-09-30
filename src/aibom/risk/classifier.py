"""Transparent capability classification (spec F-RISK-1, F-RISK-2, F-RISK-3).

The whole point of this module is explainability: every capability aibom
assigns to a tool or MCP server comes from a rule with an `id` and a `why`, and
`aibom explain-risk` prints exactly which rules matched which field. An auditor
who disagrees with a verdict can read the regex, then override it in
`aibom.yaml` — and the override is recorded next to the heuristic, never
instead of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from aibom.util import snake_split

#: Capabilities in descending severity; used for stable presentation.
CAPABILITY_ORDER = (
    "code-exec",
    "secrets",
    "financial",
    "destructive",
    "identity",
    "write",
    "external-comms",
    "filesystem",
    "network",
    "read",
    "unknown",
)

RISK_ORDER = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


@dataclass(slots=True)
class Match:
    """One rule firing against one field."""

    rule_id: str
    capability: str
    why: str
    field: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule_id,
            "capability": self.capability,
            "why": self.why,
            "field": self.field,
            "evidence": self.evidence,
        }

    def render(self) -> str:
        return f"{self.rule_id} ({self.field}: {self.evidence!r}) — {self.why}"


@dataclass(slots=True)
class Classification:
    capabilities: list[str] = field(default_factory=list)
    risk: str = "unknown"
    matches: list[Match] = field(default_factory=list)
    curated: str | None = None

    def rule_ids(self) -> list[str]:
        return [m.rule_id for m in self.matches]

    def explain(self) -> str:
        if not self.matches and not self.curated:
            return "no rule matched; risk is `unknown`"
        lines = []
        if self.curated:
            lines.append(f"curated registry: {self.curated}")
        lines += [m.render() for m in self.matches]
        lines.append(f"-> capabilities: {', '.join(self.capabilities) or 'unknown'}")
        lines.append(f"-> risk: {self.risk}")
        return "\n".join(lines)


@dataclass(slots=True)
class Rulebook:
    rules_version: str
    registry_version: str
    capability_levels: dict[str, str]
    capability_labels: dict[str, str]
    rules: list[dict[str, Any]]
    packages: list[dict[str, Any]]
    name_patterns: list[dict[str, Any]]

    # --- lookups --------------------------------------------------------------
    def level(self, capability: str) -> str:
        return self.capability_levels.get(capability, "unknown")

    def label(self, capability: str) -> str:
        return self.capability_labels.get(capability, capability)

    def risk_of(self, capabilities: list[str]) -> str:
        if not capabilities:
            return "unknown"
        return max(
            (self.level(c) for c in capabilities),
            key=lambda level: RISK_ORDER.get(level, 0),
        )

    def sort_capabilities(self, capabilities: list[str]) -> list[str]:
        seen = set(capabilities)
        ordered = [c for c in CAPABILITY_ORDER if c in seen]
        ordered += sorted(seen - set(ordered))
        return ordered


def _load(name: str) -> dict[str, Any]:
    ref = resources.files("aibom.risk.rules").joinpath(name)
    data = yaml.safe_load(ref.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} must be a YAML mapping")
    return data


@lru_cache(maxsize=1)
def load_rulebook() -> Rulebook:
    caps = _load("capabilities.yaml")
    registry = _load("mcp-packages.yaml")
    return Rulebook(
        rules_version=str(caps.get("rules_version", "unknown")),
        registry_version=str(registry.get("registry_version", "unknown")),
        capability_levels=dict(caps.get("capability_levels") or {}),
        capability_labels=dict(caps.get("capability_labels") or {}),
        rules=list(caps.get("rules") or []),
        packages=list(registry.get("packages") or []),
        name_patterns=list(registry.get("name_patterns") or []),
    )


def reload_rulebook() -> Rulebook:
    """Drop the cache. Used by tests and by `--rules` overrides."""
    load_rulebook.cache_clear()
    return load_rulebook()


# --- matching -----------------------------------------------------------------


def build_haystack(
    *,
    identifier: str | None = None,
    description: str | None = None,
    parameters: list[str] | None = None,
    command: str | None = None,
    package: str | None = None,
) -> dict[str, str]:
    """The fields a rule may match, each pre-normalised with `snake_split`."""
    fields: dict[str, str] = {}
    if identifier:
        fields["identifier"] = snake_split(identifier)
    if description:
        fields["description"] = snake_split(description)
    if parameters:
        joined = " ".join(parameters)
        fields["parameters"] = snake_split(joined)
    if command:
        fields["command"] = snake_split(command)
    if package:
        fields["package"] = snake_split(package)
    return fields


def _first_evidence(text: str, regex: re.Pattern[str]) -> str | None:
    m = regex.search(text)
    if not m:
        return None
    start, end = m.span()
    lo = max(0, start - 20)
    hi = min(len(text), end + 20)
    snippet = text[lo:hi].strip()
    return snippet


def classify_fields(fields: dict[str, str], book: Rulebook | None = None) -> Classification:
    """Run every rule against the haystack.

    A rule declares one or more field patterns (`identifier`, `description`,
    `parameters`, `command`, `package`). By default a rule fires when **any**
    declared pattern matches its field — the spec's "a regex over the identifier
    + description + parameter names", where the fields are alternative sources of
    the same evidence (a path parameter *or* a `file`-ish name both mean the tool
    touches the filesystem).

    A rule that sets `match: all` requires **every** declared field to match.
    That is for rules where one field is a qualifier on the other: `bulk_*` is
    only destructive if the description also says delete; an `issue` tool is only
    a tracker write if the description says create/update. Treating those as a
    disjunction produces an unexplainable label, which is the one thing an
    auditor cannot accept.

    Rules are additive, and the union of every matched rule's capabilities is
    the verdict.
    """
    book = book or load_rulebook()
    capabilities: list[str] = []
    matches: list[Match] = []

    field_names = ("identifier", "description", "parameters", "command", "package")
    for rule in book.rules:
        capability = rule.get("capability")
        if not capability:
            continue
        declared: list[tuple[str, str]] = [
            (name, str(rule[name])) for name in field_names if rule.get(name)
        ]
        if not declared:
            continue
        require_all = str(rule.get("match", "any")).lower() == "all"

        rule_matches: list[Match] = []
        for field_name, pattern in declared:
            hay = fields.get(field_name)
            try:
                regex = re.compile(pattern)
            except re.error:
                rule_matches = []
                break
            evidence = _first_evidence(hay, regex) if hay else None
            if evidence is None:
                if require_all:
                    rule_matches = []
                    break
                continue
            rule_matches.append(
                Match(
                    rule_id=str(rule.get("id", "unnamed")),
                    capability=str(capability),
                    why=str(rule.get("why", "")),
                    field=field_name,
                    evidence=evidence,
                )
            )
        if not rule_matches:
            continue
        if capability not in capabilities:
            capabilities.append(capability)
        # Record one match per rule so `explain-risk` stays readable; the first
        # field is the most specific when a rule declares several.
        matches.append(rule_matches[0])

    capabilities = book.sort_capabilities(capabilities)
    return Classification(
        capabilities=capabilities,
        risk=book.risk_of(capabilities),
        matches=matches,
    )


def classify_tool(
    name: str,
    *,
    description: str | None = None,
    param_keys: list[str] | None = None,
    book: Rulebook | None = None,
) -> Classification:
    book = book or load_rulebook()
    fields = build_haystack(
        identifier=name,
        description=description,
        parameters=param_keys,
    )
    return classify_fields(fields, book)


def classify_mcp_server(
    name: str,
    *,
    package: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    description: str | None = None,
    book: Rulebook | None = None,
) -> Classification:
    """Classify an MCP server: curated registry first, then regex rules.

    The curated entry sets a floor (it may only add capabilities and raise
    risk), because a package name like `server-filesystem` is far more
    informative than any regex over the word "filesystem".
    """
    book = book or load_rulebook()
    identifier = name
    package_hay = package or ""
    if not package_hay and args:
        for arg in args:
            if isinstance(arg, str) and (arg.startswith("@") or "mcp" in arg.lower()):
                package_hay = arg
                break
    command_hay = " ".join([command or "", *(a for a in (args or []) if isinstance(a, str))])

    fields = build_haystack(
        identifier=identifier,
        description=description,
        command=command_hay,
        package=package_hay,
    )
    result = classify_fields(fields, book)

    curated = match_curated_package(package_hay, book) or match_name_pattern(name, book)
    if curated is not None:
        # The curated registry is the floor, not the ceiling: its capabilities
        # are unioned in and its risk can only raise the verdict. A regex miss
        # must not be able to *downgrade* a package we already know about.
        caps = list(result.capabilities)
        for capability in curated.get("capabilities") or []:
            if capability not in caps:
                caps.append(capability)
        caps = book.sort_capabilities(caps)
        curated_risk = str(curated.get("risk") or book.risk_of(list(curated.get("capabilities") or [])))
        risk = max(
            (book.risk_of(caps), curated_risk),
            key=lambda level: RISK_ORDER.get(level, 0),
        )
        label = curated.get("package") or curated.get("pattern") or "curated"
        why = curated.get("why", "")
        matches = list(result.matches)
        if why:
            matches.append(
                Match(
                    rule_id=f"mcp.curated:{label}",
                    capability=", ".join(curated.get("capabilities") or []) or "unknown",
                    why=why,
                    field="package" if curated.get("package") else "identifier",
                    evidence=str(label),
                )
            )
        return Classification(capabilities=caps, risk=risk, matches=matches, curated=str(label))

    return result


def match_curated_package(package: str, book: Rulebook) -> dict[str, Any] | None:
    if not package:
        return None
    lowered = package.strip().lower()
    for entry in book.packages:
        names = [str(entry.get("package", ""))]
        names += [str(a) for a in entry.get("aliases") or []]
        for candidate in names:
            if not candidate:
                continue
            cand = candidate.lower()
            if lowered == cand or lowered.endswith("/" + cand) or lowered.split("@")[0] == cand:
                return entry
    return None


def match_name_pattern(name: str, book: Rulebook) -> dict[str, Any] | None:
    hay = snake_split(name)
    for entry in book.name_patterns:
        pattern = entry.get("pattern")
        if not pattern:
            continue
        try:
            if re.search(pattern, hay):
                return entry
        except re.error:
            continue
    return None


# --- overrides ----------------------------------------------------------------


@dataclass(slots=True)
class OverrideResult:
    capabilities: list[str]
    risk: str
    applied: bool
    human_in_the_loop: bool | None = None
    reversible: bool | None = None
    rate_limited: bool | None = None
    justification: str | None = None
    #: What the rules said before the human decision. Kept so the BOM can show
    #: both, and so a reviewer can see how far the override moved the verdict.
    heuristic_risk: str = "unknown"


def apply_override(
    heuristic: Classification,
    override: dict[str, Any] | None,
    book: Rulebook | None = None,
) -> OverrideResult:
    """Layer a manifest override on top of the heuristic.

    Capabilities declared in the manifest are *added* to the heuristic set
    (never silently dropped) so the BOM shows the union, and `aibom:risk_override`
    plus the justification make the human decision auditable (F-RISK-2).
    """
    book = book or load_rulebook()
    if not override:
        return OverrideResult(
            capabilities=heuristic.capabilities,
            risk=heuristic.risk,
            applied=False,
            heuristic_risk=heuristic.risk,
        )

    capabilities = list(heuristic.capabilities)
    for capability in override.get("capabilities") or []:
        if capability not in capabilities:
            capabilities.append(capability)
    capabilities = book.sort_capabilities(capabilities)

    declared_risk = override.get("risk")
    if declared_risk:
        # An explicit human risk label wins, in either direction.
        risk = str(declared_risk)
    else:
        risk = book.risk_of(capabilities)
        risk = max((risk, heuristic.risk), key=lambda level: RISK_ORDER.get(level, 0))

    return OverrideResult(
        capabilities=capabilities,
        risk=risk,
        applied=True,
        human_in_the_loop=override.get("human_in_the_loop"),
        reversible=override.get("reversible"),
        rate_limited=override.get("rate_limited"),
        justification=override.get("justification"),
        heuristic_risk=heuristic.risk,
    )


def explain(name: str, book: Rulebook | None = None, *, kind: str = "tool") -> str:
    """Human-readable explanation for `aibom explain-risk`."""
    book = book or load_rulebook()
    if kind == "mcp":
        result = classify_mcp_server(name, book=book)
    else:
        result = classify_tool(name, book=book)
    header = f"{kind} {name!r}"
    return f"{header}\n{'-' * len(header)}\n{result.explain()}"


def rulebook_as_markdown(book: Rulebook | None = None) -> str:
    """Docs generated from the rulebook, so docs/risk-rules.md cannot drift."""
    book = book or load_rulebook()
    lines = [
        "<!-- Generated by `aibom` from risk/rules/capabilities.yaml. Do not edit by hand. -->",
        "",
        f"Rulebook version: `{book.rules_version}` · registry version: `{book.registry_version}`",
        "",
        "## Capability levels",
        "",
        "| Capability | Label | Level |",
        "| --- | --- | --- |",
    ]
    for capability in CAPABILITY_ORDER:
        lines.append(
            f"| `{capability}` | {book.label(capability)} | `{book.level(capability)}` |"
        )
    lines += [
        "",
        "A tool's risk is the highest level among the capabilities it holds.",
        "",
        "## Rules",
        "",
        "| Rule | Capability | Matches on | Why |",
        "| --- | --- | --- | --- |",
    ]
    for rule in book.rules:
        fields = ", ".join(
            f"`{f}`" for f in ("identifier", "description", "parameters", "command", "package") if rule.get(f)
        )
        lines.append(
            f"| `{rule.get('id')}` | `{rule.get('capability')}` | {fields} | {rule.get('why', '')} |"
        )
    lines += [
        "",
        "## Curated MCP packages",
        "",
        f"{len(book.packages)} packages are curated. Data-only contributions welcome.",
        "",
        "| Package | Capabilities | Risk | Why |",
        "| --- | --- | --- | --- |",
    ]
    for entry in book.packages:
        caps = ", ".join(f"`{c}`" for c in entry.get("capabilities") or [])
        lines.append(
            f"| `{entry.get('package')}` | {caps} | `{entry.get('risk')}` | {entry.get('why', '')} |"
        )
    lines += [
        "",
        "## MCP name patterns",
        "",
        "| Pattern | Capabilities | Risk | Why |",
        "| --- | --- | --- | --- |",
    ]
    for entry in book.name_patterns:
        caps = ", ".join(f"`{c}`" for c in entry.get("capabilities") or [])
        lines.append(
            f"| `{entry.get('pattern')}` | {caps} | `{entry.get('risk')}` | {entry.get('why', '')} |"
        )
    return "\n".join(lines) + "\n"
