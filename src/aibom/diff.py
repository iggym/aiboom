"""BOM diffing (spec F-DIFF-1).

`aibom diff` exists so the AI surface shows up in release notes next to the
software one. It compares two BOMs by component kind and reports added, removed
and changed entries. "Changed" is deliberately narrow — version, hash, risk,
capabilities, floating and retirement — because a diff that fires on cosmetic
changes gets ignored, and an ignored diff is worse than none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aibom.digest import digest_of
from aibom.errors import DiffGateError, ValidationError

#: Kinds compared, with the collection they live in and the property used as
#: identity. Services are compared separately because CycloneDX splits them.
KINDS: tuple[tuple[str, str, str], ...] = (
    ("model", "components", "aibom:alias"),
    ("prompt", "components", "aibom:path"),
    ("tool", "components", "aibom:name"),
    ("ai-sdk", "components", "aibom:role"),
    ("dataset", "components", "aibom:role"),
    ("mcp-server", "services", "aibom:transport"),
    ("provider", "services", "aibom:role"),
    ("external-service", "services", "aibom:role"),
)

#: Properties whose change makes an entry "changed".
WATCHED_PROPERTIES = (
    "aibom:risk",
    "aibom:capabilities",
    "aibom:floating",
    "aibom:retirement",
    "aibom:deprecation",
    "aibom:version",
    "aibom:version_pinned",
    "aibom:data_processing_agreement",
    "aibom:human_in_the_loop",
    "aibom:transport",
    "aibom:hosting_region",
    "aibom:consent_basis",
    "aibom:retention",
)

RISK_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


@dataclass(slots=True)
class Change:
    kind: str
    name: str
    field: str
    before: Any
    after: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "field": self.field,
            "before": self.before,
            "after": self.after,
        }

    def describe(self) -> str:
        return f"{self.field}: {self.before!r} -> {self.after!r}"


@dataclass(slots=True)
class KindDiff:
    kind: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "added": self.added,
            "removed": self.removed,
            "changed": [c.as_dict() for c in self.changed],
        }


@dataclass(slots=True)
class BomDiff:
    old_digest: str
    new_digest: str
    kinds: list[KindDiff] = field(default_factory=list)
    review_notes_added: list[dict[str, Any]] = field(default_factory=list)
    review_notes_resolved: list[dict[str, Any]] = field(default_factory=list)
    old_version: Any = None
    new_version: Any = None

    @property
    def unchanged(self) -> bool:
        return all(k.empty for k in self.kinds) and not self.review_notes_added and not self.review_notes_resolved

    @property
    def any_changes(self) -> bool:
        return not self.unchanged

    def kind(self, name: str) -> KindDiff:
        for k in self.kinds:
            if k.kind == name:
                return k
        new = KindDiff(kind=name)
        self.kinds.append(new)
        return new

    def counts(self) -> dict[str, int]:
        return {
            "added": sum(len(k.added) for k in self.kinds),
            "removed": sum(len(k.removed) for k in self.kinds),
            "changed": sum(len(k.changed) for k in self.kinds),
            "notes_added": len(self.review_notes_added),
            "notes_resolved": len(self.review_notes_resolved),
        }

    def risk_increases(self) -> list[Change]:
        return [c for c in self.all_changes() if c.field == "aibom:risk" and _risk_up(c.before, c.after)]

    def all_changes(self) -> list[Change]:
        return [c for k in self.kinds for c in k.changed]

    def new_high_risk(self) -> list[str]:
        """Names of components that are new and already high risk."""
        out: list[str] = []
        for k in self.kinds:
            for name in k.added:
                if k.kind in {"tool", "mcp-server"}:
                    out.append(f"{k.kind}:{name}")
        return out

    def new_providers(self) -> list[str]:
        out: list[str] = []
        for k in self.kinds:
            if k.kind in {"provider", "external-service"}:
                out.extend(k.added)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "old_digest": self.old_digest,
            "new_digest": self.new_digest,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "unchanged": self.unchanged,
            "counts": self.counts(),
            "kinds": [k.as_dict() for k in self.kinds],
            "review_notes_added": self.review_notes_added,
            "review_notes_resolved": self.review_notes_resolved,
        }


def _risk_up(before: Any, after: Any) -> bool:
    return RISK_RANK.get(str(after), 0) > RISK_RANK.get(str(before), 0)


def _prop_map(component: dict[str, Any]) -> dict[str, str]:
    return {
        p["name"]: p.get("value", "")
        for p in component.get("properties") or []
        if isinstance(p, dict) and p.get("name")
    }


def _identity(kind: str, item: dict[str, Any], props: dict[str, str]) -> str:
    """Stable identity for a component across two BOMs.

    Names are the identity for models/tools/MCP servers; prompts are identified
    by their path (a prompt moving file is a change, not a new prompt); datasets
    and SDKs by name. Falling back to the bom-ref keeps odd BOMs comparable.
    """
    name = item.get("name")
    if kind == "prompt":
        return props.get("aibom:path") or str(name)
    if kind == "ai-sdk":
        return f"{item.get('purl') or name}"
    if kind == "dataset":
        return f"{props.get('aibom:role', 'dataset')}:{name}"
    if kind in {"provider", "external-service"}:
        return str(name)
    return str(name or item.get("bom-ref") or "unknown")


def _index(bom: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """kind -> identity -> {component, props, hashes}."""
    index: dict[str, dict[str, dict[str, Any]]] = {k[0]: {} for k in KINDS}
    for item in bom.get("components") or []:
        if not isinstance(item, dict):
            continue
        kind = _classify_component(item)
        if kind is None:
            continue
        props = _prop_map(item)
        entry = {
            "component": item,
            "props": props,
            "hashes": {h.get("alg"): h.get("content") for h in item.get("hashes") or [] if isinstance(h, dict)},
        }
        index[kind][_identity(kind, item, props)] = entry
    for item in bom.get("services") or []:
        if not isinstance(item, dict):
            continue
        kind = _classify_service(item)
        if kind is None:
            continue
        props = _prop_map(item)
        index[kind][_identity(kind, item, props)] = {
            "component": item,
            "props": props,
            "hashes": {},
        }
    return index


def _classify_component(item: dict[str, Any]) -> str | None:
    ctype = item.get("type")
    props = _prop_map(item)
    if ctype == "machine-learning-model":
        return "model"
    if ctype == "data":
        role = props.get("aibom:role", "dataset")
        if role == "retrieval-source":
            return "dataset"
        # Prompts are `data` components with a prompt classification.
        for d in item.get("data") or []:
            if isinstance(d, dict) and d.get("classification") == "prompt":
                return "prompt"
        return "dataset"
    if ctype == "library":
        if props.get("aibom:role") == "ai-sdk":
            return "ai-sdk"
        return "tool"
    return None


def _classify_service(item: dict[str, Any]) -> str | None:
    props = _prop_map(item)
    role = props.get("aibom:role")
    if role == "model-provider":
        return "provider"
    if role == "external-ai-service":
        return "external-service"
    if props.get("aibom:transport") is not None or item.get("x-trust-boundary") is not None:
        return "mcp-server"
    return None


def diff_boms(old: dict[str, Any], new: dict[str, Any]) -> BomDiff:
    result = BomDiff(
        old_digest=digest_of(old),
        new_digest=digest_of(new),
        old_version=old.get("version"),
        new_version=new.get("version"),
    )
    old_index = _index(old)
    new_index = _index(new)

    for kind, _collection, _prop in KINDS:
        kd = KindDiff(kind=kind)
        old_items = old_index.get(kind, {})
        new_items = new_index.get(kind, {})
        for name in sorted(set(new_items) - set(old_items)):
            kd.added.append(name)
        for name in sorted(set(old_items) - set(new_items)):
            kd.removed.append(name)
        for name in sorted(set(old_items) & set(new_items)):
            kd.changed.extend(_changes_for(kind, name, old_items[name], new_items[name]))
        if not kd.empty:
            result.kinds.append(kd)

    _diff_review_notes(old, new, result)
    return result


def _changes_for(kind: str, name: str, before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    b_comp, a_comp = before["component"], after["component"]

    if b_comp.get("version") != a_comp.get("version"):
        changes.append(Change(kind, name, "version", b_comp.get("version"), a_comp.get("version")))

    for alg in sorted(set(before["hashes"]) | set(after["hashes"])):
        b_hash, a_hash = before["hashes"].get(alg), after["hashes"].get(alg)
        if b_hash != a_hash:
            changes.append(
                Change(kind, name, f"hash:{alg}", _short_hash(b_hash), _short_hash(a_hash))
            )

    b_props, a_props = before["props"], after["props"]
    for prop_name in WATCHED_PROPERTIES:
        if b_props.get(prop_name) != a_props.get(prop_name):
            changes.append(
                Change(kind, name, prop_name, b_props.get(prop_name), a_props.get(prop_name))
            )

    # A new capability is a real change even if the risk label is unchanged.
    b_caps = set((b_props.get("aibom:capabilities") or "").split(", ")) - {""}
    a_caps = set((a_props.get("aibom:capabilities") or "").split(", ")) - {""}
    for cap in sorted(a_caps - b_caps):
        changes.append(Change(kind, name, "capability+", None, cap))
    for cap in sorted(b_caps - a_caps):
        changes.append(Change(kind, name, "capability-", cap, None))
    return changes


def _short_hash(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 12:
        return value[:12] + "…"
    return value


def _diff_review_notes(old: dict[str, Any], new: dict[str, Any], result: BomDiff) -> None:
    def codes(bom: dict[str, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for prop in bom.get("properties") or []:
            if isinstance(prop, dict) and prop.get("name") == "aibom:review_notes":
                for entry in (prop.get("value") or "").split(", "):
                    if ":" in entry:
                        level, code = entry.split(":", 1)
                        out[code] = level
        return out

    old_codes, new_codes = codes(old), codes(new)
    result.review_notes_added = [
        {"code": code, "level": new_codes[code]}
        for code in sorted(set(new_codes) - set(old_codes))
    ]
    result.review_notes_resolved = [
        {"code": code, "level": old_codes[code]}
        for code in sorted(set(old_codes) - set(new_codes))
    ]


# --- gates --------------------------------------------------------------------


def check_gates(result: BomDiff, gates: list[str]) -> None:
    """Raise `DiffGateError` when any `--fail-on` gate trips (spec F-DIFF-1)."""
    failures: list[str] = []
    for gate in gates:
        if gate == "risk-increase":
            increases = result.risk_increases()
            if increases:
                failures.append(
                    "risk increase: "
                    + "; ".join(f"{c.kind} {c.name} {c.before}->{c.after}" for c in increases)
                )
        elif gate == "new-high-risk":
            new_high = result.new_high_risk()
            if new_high:
                failures.append("new high-risk component(s): " + ", ".join(new_high))
        elif gate == "new-provider":
            providers = result.new_providers()
            if providers:
                failures.append("new provider/external service(s): " + ", ".join(providers))
        elif gate == "any-change":
            if result.any_changes:
                failures.append("the AI surface changed")
        else:
            raise DiffGateError(
                f"unknown gate {gate!r}",
                hint="valid gates: risk-increase, new-high-risk, new-provider, any-change",
            )
    if failures:
        raise DiffGateError("diff gate failed: " + "; ".join(failures))


# --- rendering ----------------------------------------------------------------


def render_diff_text(result: BomDiff) -> str:
    if result.unchanged:
        return f"No changes to the AI surface.\n  digest: {result.new_digest[:12]}\n"
    lines: list[str] = []
    counts = result.counts()
    lines.append(
        f"AI surface changed: {counts['added']} added, {counts['removed']} removed, "
        f"{counts['changed']} changed."
    )
    lines.append(f"  digest: {result.old_digest[:12]} -> {result.new_digest[:12]}")
    if result.old_version != result.new_version:
        lines.append(f"  bom version: {result.old_version} -> {result.new_version}")
    lines.append("")
    for kd in result.kinds:
        if kd.empty:
            continue
        lines.append(f"{kd.kind}:")
        for name in kd.added:
            lines.append(f"  + {name}")
        for name in kd.removed:
            lines.append(f"  - {name}")
        for change in kd.changed:
            lines.append(f"  ~ {change.name}: {change.describe()}")
        lines.append("")
    if result.review_notes_added:
        lines.append("new review notes:")
        lines += [f"  ! {n['level']}: {n['code']}" for n in result.review_notes_added]
    if result.review_notes_resolved:
        lines.append("resolved review notes:")
        lines += [f"  ✓ {n['code']}" for n in result.review_notes_resolved]
    return "\n".join(lines).rstrip() + "\n"


def render_diff_markdown(result: BomDiff, *, title: str = "AI BOM changes") -> str:
    """Release-note-ready Markdown (F-DIFF-1)."""
    lines = [f"## {title}", ""]
    if result.unchanged:
        lines.append(f"No changes to the AI surface. `{result.new_digest[:12]}`")
        return "\n".join(lines) + "\n"

    counts = result.counts()
    lines.append(
        f"**{counts['added']} added · {counts['removed']} removed · "
        f"{counts['changed']} changed** "
        f"(`{result.old_digest[:8]}` → `{result.new_digest[:8]}`)"
    )
    lines.append("")
    if result.old_version != result.new_version:
        lines.append(f"BOM version: `{result.old_version}` → `{result.new_version}`")
        lines.append("")

    for kd in result.kinds:
        if kd.empty:
            continue
        lines.append(f"### {kd.kind.replace('-', ' ').title()}")
        lines.append("")
        if kd.added:
            lines.append("| Added | |")
            lines.append("| --- | --- |")
            for name in kd.added:
                lines.append(f"| `{name}` | new |")
            lines.append("")
        if kd.removed:
            lines.append("| Removed | |")
            lines.append("| --- | --- |")
            for name in kd.removed:
                lines.append(f"| `{name}` | removed |")
            lines.append("")
        if kd.changed:
            lines.append("| Component | Change |")
            lines.append("| --- | --- |")
            for change in kd.changed:
                arrow = "→"
                before = "—" if change.before in (None, "") else f"`{change.before}`"
                after = "—" if change.after in (None, "") else f"`{change.after}`"
                lines.append(f"| `{change.name}` | {change.field}: {before} {arrow} {after} |")
            lines.append("")

    if result.review_notes_added or result.review_notes_resolved:
        lines.append("### Review notes")
        lines.append("")
        for note in result.review_notes_added:
            lines.append(f"- :warning: new **{note['level']}** note `{note['code']}`")
        for note in result.review_notes_resolved:
            lines.append(f"- :white_check_mark: resolved `{note['code']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_bom(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path}: expected a JSON object")
    return data


def diff(old_path: Path, new_path: Path) -> BomDiff:
    """Python API entry point (spec §6.7)."""
    return diff_boms(load_bom(old_path), load_bom(new_path))
