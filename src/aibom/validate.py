"""CycloneDX 1.6 schema validation (spec F-OUT-5, `aibom validate`).

The official CycloneDX schemas are vendored under `aibom/schemas/` so
validation is offline, pinned to a known revision, and reproducible. aibom
refuses to emit a BOM that fails this check: producing an invalid BOM would
break every downstream consumer (Dependency-Track, GUAC, DT's SBOM import API).
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError

from aibom.errors import ValidationError

#: Remote `$id`s the vendored schemas reference, mapped to local files.
_SCHEMA_FILES = {
    "bom-1.6.schema.json": "http://cyclonedx.org/schema/bom-1.6.schema.json",
    "spdx.schema.json": "http://cyclonedx.org/schema/spdx.schema.json",
    "jsf-0.82.schema.json": "http://cyclonedx.org/schema/jsf-0.82.schema.json",
}

#: Fields aibom relies on that downstream tools require. Checked after schema
#: validation because the schema marks them optional.
REQUIRED_FOR_INGESTION = (
    ("metadata",),
    ("metadata", "component"),
    ("metadata", "component", "bom-ref"),
)


def _load_schema(name: str) -> dict[str, Any]:
    ref = resources.files("aibom.schemas").joinpath(name)
    return json.loads(ref.read_text(encoding="utf-8"))


def _registry() -> Any:
    """Build a referencing registry with the vendored sub-schemas resolved.

    The CycloneDX schema references `spdx.schema.json` and `jsf-0.82.schema.json`
    by relative filename. Registering them locally means no network access and
    no surprise if CycloneDX publishes a new revision upstream.
    """
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    resources_map = {}
    for filename, uri in _SCHEMA_FILES.items():
        doc = _load_schema(filename)
        resource = Resource.from_contents(doc, default_specification=DRAFT7)
        resources_map[uri] = resource
        resources_map[filename] = resource
    return Registry().with_resources(list(resources_map.items()))


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = _load_schema("bom-1.6.schema.json")
    return Draft7Validator(schema, registry=_registry())


def schema_version() -> str:
    schema = _load_schema("bom-1.6.schema.json")
    return str(schema.get("$id", "unknown"))


def _path_of(error: JsonSchemaError) -> str:
    parts = [str(p) for p in error.absolute_path]
    return "/".join(parts) if parts else "(root)"


def validate_document(bom: dict[str, Any]) -> list[str]:
    """Return schema problems as ``path: message`` strings. Empty means valid."""
    problems: list[str] = []
    for error in sorted(_validator().iter_errors(bom), key=lambda e: list(e.absolute_path)):
        problems.append(f"{_path_of(error)}: {error.message}")
    return problems


def validate_bom(bom: dict[str, Any], *, source: str | None = None, strict: bool = False) -> None:
    """Raise `ValidationError` when ``bom`` is not a valid CycloneDX 1.6 document."""
    where = f"{source}: " if source else ""
    if bom.get("bomFormat") != "CycloneDX":
        raise ValidationError(
            f"{where}not a CycloneDX document (bomFormat={bom.get('bomFormat')!r})",
            hint="aibom only emits CycloneDX 1.6 JSON/XML",
        )
    if str(bom.get("specVersion")) != "1.6":
        raise ValidationError(
            f"{where}unsupported specVersion {bom.get('specVersion')!r}",
            hint="aibom 0.1 emits CycloneDX 1.6",
        )

    problems = validate_document(bom)
    if problems:
        raise ValidationError(
            f"{where}BOM does not validate against the CycloneDX 1.6 schema",
            problems=problems,
            hint="this is an aibom bug — please report it with the BOM attached",
        )

    if strict:
        extras = ingestion_problems(bom)
        if extras:
            raise ValidationError(
                f"{where}BOM is schema-valid but not usable by Dependency-Track",
                problems=extras,
            )


def ingestion_problems(bom: dict[str, Any]) -> list[str]:
    """Checks that go beyond the schema, aimed at real ingestors.

    Dependency-Track and GUAC both key on `metadata.component.bom-ref`; a BOM
    without it imports as an orphan project. The schema does not require it, so
    we check it ourselves.
    """
    problems: list[str] = []
    for path in REQUIRED_FOR_INGESTION:
        node: Any = bom
        for key in path:
            if not isinstance(node, dict) or key not in node:
                problems.append(f"{'/'.join(path)} is missing (required by Dependency-Track import)")
                break
            node = node[key]

    refs: set[str] = set()
    duplicates: list[str] = []
    for collection, key in (("components", "bom-ref"), ("services", "bom-ref")):
        for item in bom.get(collection) or []:
            if not isinstance(item, dict):
                continue
            ref = item.get(key)
            if not ref:
                problems.append(f"{collection}[{item.get('name')}]: missing {key}")
                continue
            if ref in refs:
                duplicates.append(ref)
            refs.add(ref)
    problems.extend(f"duplicate bom-ref: {ref}" for ref in sorted(set(duplicates)))

    app_ref = (bom.get("metadata") or {}).get("component", {}).get("bom-ref")
    if app_ref and not any(d.get("ref") == app_ref for d in bom.get("dependencies") or []):
        problems.append(
            "dependencies[] has no entry for the application bom-ref; "
            "some ingestors will show an empty dependency graph"
        )
    return problems


def validate_file(path: Path, *, strict: bool = False) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    try:
        bom = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    if not isinstance(bom, dict):
        raise ValidationError(f"{path}: expected a JSON object at the top level")
    validate_bom(bom, source=str(path), strict=strict)
    return bom
