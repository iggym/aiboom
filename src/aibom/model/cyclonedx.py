"""CycloneDX 1.6 emitters (spec F-OUT-1..F-OUT-4).

Two renderings of the same model: JSON (primary, digested, signed) and XML
(`--format xml`, same data). Both are validated against the vendored official
schema in `aibom.schemas`.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from aibom import CYCLONEDX_SPEC_VERSION, __version__
from aibom.model.components import (
    AiBom,
    Dataset,
    ExternalService,
    McpServer,
    Model,
    Prompt,
    Provider,
    Tool,
    hash_sha256,
    props,
)
from aibom.util import canonical_json, sha256_text

#: Version stamp of the ML-BOM / AI component model aibom emits.
AI_SCHEMA_VERSION = "1.0"

VERSION_IN_SNAPSHOT = re.compile(r"(?:-|@|:)(\d{4}-\d{2}-\d{2}|\d{8})$")


def parse_model_version(snapshot: str) -> str | None:
    """Pull the pinned revision out of a snapshot id.

    `gpt-4.1-2025-04-14` -> `2025-04-14`; `claude-sonnet-4-5-20250929` ->
    `20250929`. An unpinned alias has no version to report.
    """
    m = VERSION_IN_SNAPSHOT.search(snapshot)
    return m.group(1) if m else None


# --- components ---------------------------------------------------------------


def _model_component(model: Model) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": "machine-learning-model",
        "bom-ref": model.bom_ref,
        "name": model.display_name,
    }
    version = model.version or parse_model_version(model.snapshot)
    if version:
        component["version"] = version
    if model.provider:
        component["supplier"] = {"name": model.provider}
        component["group"] = model.provider
    if model.purpose:
        component["description"] = model.purpose

    model_card: dict[str, Any] = {}
    params: dict[str, Any] = {}
    if model.task:
        params["task"] = model.task
    if model.architecture_family:
        params["architectureFamily"] = model.architecture_family
    if model.kind:
        params["modelArchitecture"] = model.kind
    if params:
        model_card["modelParameters"] = params

    considerations: dict[str, Any] = {}
    if model.use_cases:
        considerations["useCases"] = model.use_cases
    if model.technical_limitations:
        considerations["technicalLimitations"] = model.technical_limitations
    if model.ethical_considerations:
        considerations["ethicalConsiderations"] = [
            {k: v for k, v in item.items() if v} for item in model.ethical_considerations
        ]
    if considerations:
        model_card["considerations"] = considerations

    metrics = [
        {
            "type": ev.name,
            **({"value": str(ev.score)} if ev.score is not None else {}),
        }
        for ev in model.evals
    ]
    if metrics:
        model_card["quantitativeAnalysis"] = {"performanceMetrics": metrics}

    if model_card:
        component["modelCard"] = model_card

    refs: list[dict[str, Any]] = []
    if model.provider_docs:
        refs.append({"type": "documentation", "url": model.provider_docs})
    for ev in model.evals:
        if ev.url:
            refs.append({"type": "documentation", "url": ev.url})
    if refs:
        component["externalReferences"] = _dedupe_refs(refs)

    if model.license:
        component["licenses"] = [{"license": {"name": model.license}}]

    locations = ", ".join(loc.display() for loc in model.locations)
    component["properties"] = props(
        ("aibom:alias", model.alias),
        ("aibom:resolved", model.resolved),
        ("aibom:floating", model.floating),
        ("aibom:kind", model.kind),
        ("aibom:provider", model.provider),
        ("aibom:locations", locations),
        ("aibom:deprecation", model.deprecation),
        ("aibom:retirement", model.retirement),
        ("aibom:price_in_per_1m", model.price_in_per_1m),
        ("aibom:price_out_per_1m", model.price_out_per_1m),
        ("aibom:context_window", model.context_window),
        ("aibom:hosting_region", model.hosting_region),
        ("aibom:data_processing_agreement", model.data_processing_agreement),
        ("aibom:training_data_optout", model.training_data_optout),
        ("aibom:purpose", model.purpose),
        ("aibom:snapshot", model.snapshot if model.snapshot != model.alias else None),
        ("aibom:inferred", model.inferred or None),
    )
    return component


def _prompt_component(prompt: Prompt) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": "data",
        "bom-ref": prompt.bom_ref,
        "name": prompt.name,
        "version": prompt.version,
        "hashes": [hash_sha256(prompt.sha256)],
        "data": [
            {
                "type": "configuration",
                "name": prompt.name,
                "classification": "prompt",
                "description": f"Prompt defined at {prompt.path}:{prompt.line or 1}",
            }
        ],
        "properties": props(
            ("aibom:path", prompt.path),
            ("aibom:line", prompt.line),
            ("aibom:approx_tokens", prompt.approx_tokens),
            ("aibom:source", prompt.source),
            ("aibom:owners", prompt.owners),
            ("aibom:variables", prompt.variables),
        ),
    }
    return component


def _tool_component(tool: Tool) -> dict[str, Any]:
    digest = tool.sha256 or sha256_text(
        canonical_json(
            {
                "name": tool.name,
                "path": tool.path,
                "line": tool.line,
                "description": tool.description,
                "param_keys": tool.param_keys,
                "capabilities": tool.capabilities,
            }
        )
    )
    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": tool.bom_ref,
        "name": tool.name,
        "hashes": [hash_sha256(digest)],
    }
    if tool.description:
        component["description"] = tool.description
    component["properties"] = props(
        ("aibom:path", tool.path),
        ("aibom:line", tool.line),
        ("aibom:source", tool.source),
        ("aibom:param_keys", tool.param_keys),
        ("aibom:capabilities", tool.capabilities),
        ("aibom:risk", tool.risk),
        ("aibom:human_in_the_loop", tool.human_in_the_loop),
        ("aibom:rate_limited", tool.rate_limited),
        ("aibom:reversible", tool.reversible),
        ("aibom:risk_override", tool.risk_override),
        ("aibom:risk_justification", tool.justification),
        ("aibom:matched_rules", tool.matched_rules),
        ("aibom:heuristic_risk", tool.heuristic_risk if tool.risk_override else None),
        ("aibom:heuristic_capabilities", tool.heuristic_capabilities if tool.risk_override else None),
        ("aibom:uses_mcp_server", tool.mcp_server),
    )
    return component


def _sdk_component(sdk) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": sdk.bom_ref,
        "name": sdk.name,
        "purl": sdk.purl,
        "properties": props(
            ("aibom:role", "ai-sdk"),
            ("aibom:ecosystem", sdk.ecosystem),
            ("aibom:provider", sdk.provider),
        ),
    }
    if sdk.version:
        component["version"] = sdk.version
    return component


def _dataset_component(dataset: Dataset) -> dict[str, Any]:
    data_entry: dict[str, Any] = {
        "type": "dataset" if dataset.kind == "dataset" else "dataset",
        "name": dataset.name,
    }
    if dataset.classification:
        data_entry["classification"] = dataset.classification
    if dataset.sensitive_data:
        data_entry["sensitiveData"] = dataset.sensitive_data
    if dataset.description:
        data_entry["description"] = dataset.description
    governance: dict[str, Any] = {}
    if dataset.owners:
        governance["owners"] = [{"organization": {"name": o}} for o in dataset.owners]
    if dataset.custodians:
        governance["custodians"] = [{"organization": {"name": c}} for c in dataset.custodians]
    if governance:
        data_entry["governance"] = governance

    component: dict[str, Any] = {
        "type": "data",
        "bom-ref": dataset.bom_ref,
        "name": dataset.name,
        "data": [data_entry],
        "properties": props(
            ("aibom:role", "retrieval-source" if dataset.kind == "retrieval" else "dataset"),
            ("aibom:source", dataset.source),
            ("aibom:retention", dataset.retention),
            ("aibom:jurisdiction", dataset.jurisdiction),
            ("aibom:pii", dataset.pii),
            ("aibom:consent_basis", dataset.consent_basis),
            ("aibom:refresh", dataset.refresh),
            ("aibom:classification", dataset.classification),
            ("aibom:owners", dataset.owners),
            ("aibom:custodians", dataset.custodians),
        ),
    }
    if dataset.version:
        component["version"] = dataset.version
    return component


# --- services -----------------------------------------------------------------


def _mcp_service(server: McpServer) -> dict[str, Any]:
    service: dict[str, Any] = {
        "bom-ref": server.bom_ref,
        "name": server.name,
        "description": f"MCP server ({server.transport})",
        "x-trust-boundary": server.crosses_trust_boundary,
        "data": [
            {
                "flow": "bi-directional",
                "classification": "unknown",
                "name": "MCP protocol traffic",
            }
        ],
        "properties": props(
            ("aibom:transport", server.transport),
            ("aibom:command", server.command),
            ("aibom:args", server.args),
            ("aibom:env_keys", server.env_keys),
            ("aibom:config", server.config),
            ("aibom:package", server.package),
            ("aibom:version", server.version),
            ("aibom:version_pinned", server.version_pinned),
            ("aibom:sha256", server.sha256),
            ("aibom:capabilities", server.capabilities),
            ("aibom:risk", server.risk),
            ("aibom:human_in_the_loop", server.human_in_the_loop),
            ("aibom:rate_limited", server.rate_limited),
            ("aibom:reversible", server.reversible),
            ("aibom:risk_override", server.risk_override),
            ("aibom:risk_justification", server.justification),
            ("aibom:matched_rules", server.matched_rules),
            ("aibom:heuristic_risk", server.heuristic_risk if server.risk_override else None),
            ("aibom:heuristic_capabilities", server.heuristic_capabilities if server.risk_override else None),
        ),
    }
    if server.authenticated is not None:
        service["authenticated"] = server.authenticated
    endpoints = server.endpoints
    if endpoints:
        service["endpoints"] = endpoints
    return service


def _provider_service(provider: Provider, data_classification: str | None) -> dict[str, Any]:
    service: dict[str, Any] = {
        "bom-ref": provider.bom_ref,
        "name": provider.name,
        "description": f"Hosted model API ({provider.name})",
        "authenticated": True,
        "x-trust-boundary": True,
        "data": [
            {
                "flow": "bi-directional",
                "classification": data_classification or "unknown",
                "name": "Prompts, completions and embeddings",
            }
        ],
        "properties": props(
            ("aibom:role", "model-provider"),
            ("aibom:region", provider.region),
            ("aibom:dpa", provider.dpa),
            ("aibom:data_classification", data_classification),
            ("aibom:models", provider.models),
        ),
    }
    if provider.endpoint:
        service["endpoints"] = [provider.endpoint]
    return service


def _external_service(service: ExternalService, default_classification: str | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "bom-ref": service.bom_ref,
        "name": service.name,
        "x-trust-boundary": True,
        "data": [
            {
                "flow": "bi-directional",
                "classification": service.classification or default_classification or "unknown",
                "name": "data shared",
                "description": ", ".join(service.data_shared) if service.data_shared else None,
            }
        ],
        "properties": props(
            ("aibom:role", "external-ai-service"),
            ("aibom:provider", service.provider),
            ("aibom:purpose", service.purpose),
            ("aibom:data_shared", service.data_shared),
            ("aibom:dpa", service.dpa),
            ("aibom:region", service.region),
        ),
    }
    if entry["data"][0].get("description") is None:
        entry["data"][0].pop("description")
    if service.description:
        entry["description"] = service.description
    if service.endpoint:
        entry["endpoints"] = [service.endpoint]
    if service.provider:
        entry["provider"] = {"name": service.provider}
    if service.authenticated is not None:
        entry["authenticated"] = service.authenticated
    return entry


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("type", ""), ref.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


# --- document -----------------------------------------------------------------


def _tool_metadata() -> dict[str, Any]:
    return {
        "components": [
            {
                "type": "application",
                "bom-ref": f"tool:aibom@{__version__}",
                "name": "aibom",
                "version": __version__,
                "supplier": {"name": "modelsurface"},
                "externalReferences": [
                    {"type": "vcs", "url": "https://github.com/modelsurface/aibom"},
                    {"type": "website", "url": "https://modelsurface.github.io/aibom/"},
                ],
            }
        ]
    }


def _app_component(bom: AiBom) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": "application",
        "bom-ref": bom.app_bom_ref,
        "name": bom.app_name,
    }
    if bom.app_version:
        component["version"] = bom.app_version
    if bom.app_description:
        component["description"] = bom.app_description
    if bom.owner:
        component["authors"] = [{"name": bom.owner}]
    rc = bom.risk_classification or {}
    component["properties"] = props(
        ("aibom:purpose", bom.app_purpose),
        ("aibom:deployment", bom.deployment),
        ("aibom:data_classification", bom.data_classification),
        ("aibom:jurisdictions", bom.jurisdictions),
        ("aibom:risk_framework", rc.get("framework")),
        ("aibom:risk_label", rc.get("label")),
        ("aibom:risk_rationale", rc.get("rationale")),
        ("aibom:human_oversight", bom.human_oversight),
        ("aibom:owner", bom.owner),
        ("aibom:rules_version", bom.rules_version),
        ("aibom:ai_schema_version", AI_SCHEMA_VERSION),
        ("aibom:generator", f"{bom.tool_name} {bom.tool_version}"),
        ("aibom:scanner", bom.scanner),
        ("aibom:git_commit", bom.git.get("commit")),
        ("aibom:git_branch", bom.git.get("branch")),
        ("aibom:git_remote", bom.git.get("remote")),
        ("aibom:git_tag", bom.git.get("tag")),
        ("aibom:git_dirty", bom.git.get("dirty") if bom.git.get("available") else "unavailable"),
        ("aibom:lock", bom.lock_path),
        ("aibom:lock_generated", bom.lock_generated),
        ("aibom:lock_fresh", bom.lock_fresh),
        ("aibom:manifest", bom.manifest_path),
        ("aibom:review_errors", len(bom.notes_at("error"))),
        ("aibom:review_warnings", len(bom.notes_at("warning"))),
    )
    return component


def to_cyclonedx_json(
    bom: AiBom,
    *,
    serial_number: str | None = None,
    version: int = 1,
    include_serial: bool = True,
) -> dict[str, Any]:
    """Render the model as a CycloneDX 1.6 JSON document."""
    doc: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
    }
    if include_serial:
        doc["serialNumber"] = serial_number or f"urn:uuid:{uuid.uuid4()}"
    doc["version"] = version

    metadata: dict[str, Any] = {
        "timestamp": bom.generated_at,
        "lifecycles": [{"phase": "build"}],
        "tools": _tool_metadata(),
        "component": _app_component(bom),
    }
    authors = [{"name": c.name, **({"email": c.email} if c.email else {})} for c in bom.contacts]
    if authors:
        metadata["authors"] = authors
    doc["metadata"] = metadata

    components: list[dict[str, Any]] = []
    components += [_model_component(m) for m in bom.models]
    components += [_prompt_component(p) for p in bom.prompts]
    components += [_tool_component(t) for t in bom.tools]
    components += [_dataset_component(d) for d in bom.datasets]
    components += [_sdk_component(s) for s in bom.ai_sdks]
    components += [c for c in bom.merged_components if isinstance(c, dict)]
    if components:
        doc["components"] = components

    services: list[dict[str, Any]] = []
    services += [_mcp_service(s) for s in bom.mcp_servers]
    services += [_provider_service(p, bom.data_classification) for p in bom.providers]
    services += [_external_service(e, bom.data_classification) for e in bom.external_services]
    if services:
        doc["services"] = services

    dependencies = _dependencies(bom)
    if dependencies:
        doc["dependencies"] = dependencies

    compositions = _compositions(bom)
    if compositions:
        doc["compositions"] = compositions

    doc["properties"] = props(
        ("aibom:rules_version", bom.rules_version),
        ("aibom:tool_version", f"{bom.tool_name} {bom.tool_version}"),
        ("aibom:source_root", bom.source_root),
        ("aibom:review_notes", [f"{n.level}:{n.code}" for n in bom.review_notes]),
    )
    return doc


def _dependencies(bom: AiBom) -> list[dict[str, Any]]:
    """Application → everything; tool → its MCP server; model ← prompt (inferred)."""
    by_ref: dict[str, dict[str, Any]] = {}

    def entry(ref: str, *, inferred: bool = False) -> dict[str, Any]:
        item = by_ref.setdefault(ref, {"ref": ref, "dependsOn": []})
        if inferred:
            item["_inferred"] = True
        return item

    app = entry(bom.app_bom_ref)
    for ref in bom.all_refs:
        if ref != bom.app_bom_ref and ref not in app["dependsOn"]:
            app["dependsOn"].append(ref)

    for tool in bom.tools:
        item = entry(tool.bom_ref)
        if tool.mcp_server:
            target = f"mcp:{tool.mcp_server}"
            if target not in item["dependsOn"]:
                item["dependsOn"].append(target)

    # Best-effort: a model and a prompt referenced from the same file are
    # assumed to be used together. Recorded as inferred so an auditor knows.
    for model in bom.models:
        model_paths = {loc.path for loc in model.locations}
        if not model_paths:
            continue
        item = entry(model.bom_ref, inferred=True)
        for prompt in bom.prompts:
            if prompt.path in model_paths and prompt.bom_ref not in item["dependsOn"]:
                item["dependsOn"].append(prompt.bom_ref)
                item["_inferred"] = True

    out: list[dict[str, Any]] = []
    for ref in sorted(by_ref):
        item = by_ref[ref]
        item["dependsOn"] = sorted(item["dependsOn"])
        # `_inferred` is internal bookkeeping and is not a CycloneDX field; the
        # inference is surfaced on the component itself as `aibom:inferred=true`.
        item.pop("_inferred", None)
        out.append(item)
    return out


def _compositions(bom: AiBom) -> list[dict[str, Any]]:
    """F-OUT-4: scanned kinds are complete only when the lock is fresh."""
    scanned_aggregate = "complete" if bom.lock_fresh else "incomplete"
    out: list[dict[str, Any]] = []

    scanned = {
        "models": [m.bom_ref for m in bom.models],
        "prompts": [p.bom_ref for p in bom.prompts],
        "tools": [t.bom_ref for t in bom.tools],
        "mcp_servers": [s.bom_ref for s in bom.mcp_servers],
        "providers": [p.bom_ref for p in bom.providers],
        "ai_sdks": [s.bom_ref for s in bom.ai_sdks],
    }
    for _kind, refs in scanned.items():
        if not refs:
            continue
        out.append({"aggregate": scanned_aggregate, "assemblies": sorted(refs)})

    declared = {
        "datasets": [d.bom_ref for d in bom.datasets],
        "external_services": [e.bom_ref for e in bom.external_services],
    }
    for kind, refs in declared.items():
        if not refs:
            continue
        manifest_key = {
            "datasets": "datasets",
            "external_services": "external_services",
        }[kind]
        aggregate = "complete" if bom.manifest_complete.get(manifest_key) else "unknown"
        out.append({"aggregate": aggregate, "assemblies": sorted(refs)})

    return out


def to_cyclonedx_xml(bom: AiBom, *, serial_number: str | None = None, version: int = 1) -> str:
    """Render the same model as CycloneDX 1.6 XML (spec F-OUT-5, optional in 0.1)."""
    return json_to_xml(to_cyclonedx_json(bom, serial_number=serial_number, version=version))


def json_to_xml(doc: dict[str, Any]) -> str:
    """Render an existing CycloneDX JSON document as XML.

    Used by `aibom generate --format xml`, where the JSON document already
    exists (and may include a merged SBOM); going through the document rather
    than the model guarantees the two formats describe the same BOM.
    """
    try:
        from aibom.model.xml import to_xml

        return to_xml(doc)
    except ImportError:
        return _xml_via_elementtree(doc)


def _xml_via_elementtree(doc: dict[str, Any]) -> str:  # pragma: no cover - fallback path
    import xml.etree.ElementTree as ET

    root = ET.Element("bom", {"xmlns": "http://cyclonedx.org/schema/bom/1.6"})
    for key, value in doc.items():
        if key in {"bomFormat", "specVersion", "components", "services", "dependencies", "metadata", "compositions", "properties"}:
            continue
        ET.SubElement(root, key).text = str(value)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def to_json_text(bom: AiBom, *, serial_number: str | None = None, version: int = 1) -> str:
    return json.dumps(
        to_cyclonedx_json(bom, serial_number=serial_number, version=version),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
