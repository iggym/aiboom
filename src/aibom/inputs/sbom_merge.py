"""Merge an existing SBOM into the AI BOM (spec F-IN-6).

The point of `--merge-sbom` is one artifact for security tooling: the software
inventory a team already produces plus the AI layer, under a single
`metadata.component`, so Dependency-Track/GUAC ingest both in one POST.

aibom never rewrites the merged SBOM's components — they are copied verbatim
and their refs are preserved so existing `dependencies` entries keep resolving.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aibom.errors import LockError, ValidationError


def load_sbom(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(f"cannot read SBOM {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path}: expected a JSON object at the top level")
    if data.get("bomFormat") != "CycloneDX":
        raise ValidationError(
            f"{path}: not a CycloneDX BOM",
            hint="only CycloneDX JSON SBOMs can be merged in 0.1; SPDX support is post-0.1",
        )
    return data


def merge_sbom(
    aibom_bom: dict[str, Any],
    sbom: dict[str, Any] | Path | str,
    *,
    ref_prefix: str = "sbom",
) -> dict[str, Any]:
    """Return ``aibom_bom`` with ``sbom``'s inventory merged in."""
    if isinstance(sbom, (str, Path)):
        sbom = load_sbom(Path(sbom))
    if not isinstance(sbom, dict) or "components" not in sbom and "services" not in sbom:
        raise LockError(
            "the file passed to --merge-sbom is not a CycloneDX BOM",
            hint="expected a JSON document with a `components` array (e.g. from syft or cdxgen)",
        )
    merged = json.loads(json.dumps(aibom_bom))
    existing_refs = {c.get("bom-ref") for c in merged.get("components", [])}
    existing_refs.update({s.get("bom-ref") for s in merged.get("services", [])})

    incoming_components = sbom.get("components") or []
    incoming_services = sbom.get("services") or []
    remap: dict[str, str] = {}

    for component in incoming_components:
        if not isinstance(component, dict):
            continue
        ref = component.get("bom-ref")
        if ref and ref in existing_refs:
            new_ref = f"{ref_prefix}:{ref}"
            remap[ref] = new_ref
            component = {**component, "bom-ref": new_ref}
        merged.setdefault("components", []).append(component)
        if component.get("bom-ref"):
            existing_refs.add(component["bom-ref"])
        merged.setdefault("properties", []).append(
            {"name": "aibom:merged_from", "value": f"{ref_prefix}:{sbom.get('serialNumber', 'sbom')}"}
        )

    for service in incoming_services:
        if not isinstance(service, dict):
            continue
        merged.setdefault("services", []).append(service)

    for dep in sbom.get("dependencies") or []:
        if not isinstance(dep, dict):
            continue
        entry = dict(dep)
        if entry.get("ref") in remap:
            entry["ref"] = remap[entry["ref"]]
        if entry.get("dependsOn"):
            entry["dependsOn"] = [remap.get(r, r) for r in entry["dependsOn"]]
        merged.setdefault("dependencies", []).append(entry)

    # The merged SBOM's own subject becomes a dependency of our application.
    sbom_subject = (sbom.get("metadata") or {}).get("component") or {}
    subject_ref = sbom_subject.get("bom-ref")
    if subject_ref:
        app_ref = merged["metadata"]["component"].get("bom-ref")
        for dep in merged["dependencies"]:
            if dep.get("ref") == app_ref:
                dep.setdefault("dependsOn", [])
                if subject_ref not in dep["dependsOn"]:
                    dep["dependsOn"].append(subject_ref)
                break

    merged.setdefault("properties", []).extend(
        [
            {"name": "aibom:merged_sbom", "value": str(sbom.get("serialNumber", "unknown"))},
            {"name": "aibom:merged_sbom_spec", "value": str(sbom.get("specVersion", "unknown"))},
        ]
    )
    return merged
