"""CycloneDX 1.6 XML rendering (spec F-OUT-5, optional extra `[xml]`).

Uses lxml when installed. The XML is generated from the same dictionary the
JSON emitter produces, so the two formats cannot drift.
"""

from __future__ import annotations

from typing import Any

NS = "http://cyclonedx.org/schema/bom/1.6"

# Order matters: CycloneDX XML expects a defined element order in some
# consumers, and a stable order keeps `diff` on XML meaningful.
_COMPONENT_ORDER = (
    "type",
    "mime-type",
    "bom-ref",
    "supplier",
    "manufacturer",
    "authors",
    "author",
    "publisher",
    "group",
    "name",
    "version",
    "description",
    "scope",
    "hashes",
    "licenses",
    "copyright",
    "cpe",
    "purl",
    "externalReferences",
    "components",
    "evidence",
    "releaseNotes",
    "modelCard",
    "data",
    "properties",
    "tags",
)

_ATTRS = {
    "type",
    "bom-ref",
    "mime-type",
    "purl",
    "cpe",
    "x-trust-boundary",
    "authenticated",
}

_PLURAL = {
    "components": "component",
    "services": "service",
    "dependencies": "dependency",
    "compositions": "composition",
    "properties": "property",
    "hashes": "hash",
    "licenses": "license",
    "externalReferences": "reference",
    "endpoints": "endpoint",
    "data": "data",
    "authors": "author",
    "contacts": "contact",
    "tags": "tag",
    "assemblies": "assembly",
    "dependsOn": "dependency",
    "performanceMetrics": "performanceMetric",
    "sensitiveData": "sensitiveData",
    "owners": "owner",
    "custodians": "custodian",
    "stewards": "steward",
    "useCases": "useCase",
    "technicalLimitations": "technicalLimitation",
    "ethicalConsiderations": "ethicalConsideration",
    "modelParameters": "modelParameters",
    "considerations": "considerations",
    "quantitativeAnalysis": "quantitativeAnalysis",
    "lifecycles": "lifecycle",
    "tools": "tools",
    "component": "component",
}

# JSON key -> XML element name where they differ.
_RENAME = {
    "externalReferences": "externalReferences",
    "bom-ref": "bom-ref",
    "x-trust-boundary": "x-trust-boundary",
    "dependsOn": "dependency",
    "assemblies": "assembly",
    "performanceMetrics": "performanceMetric",
    "sensitiveData": "sensitiveData",
    "useCases": "useCase",
    "technicalLimitations": "technicalLimitation",
    "ethicalConsiderations": "ethicalConsideration",
    "mitigationStrategy": "mitigationStrategy",
    "modelParameters": "modelParameters",
    "architectureFamily": "architectureFamily",
    "modelArchitecture": "modelArchitecture",
    "quantitativeAnalysis": "quantitativeAnalysis",
}


def to_xml(doc: dict[str, Any]) -> str:
    from lxml import etree

    # The namespace arrives via nsmap; setting xmlns again produces a duplicate
    # attribute that strict XML parsers reject.
    root = etree.Element("bom", nsmap={None: NS})
    for attr in ("serialNumber", "version"):
        if attr in doc:
            root.set(attr, str(doc[attr]))
    for key in ("metadata", "components", "services",
                "externalReferences", "dependencies", "compositions", "properties"):
        if key not in doc:
            continue
        _write(root, key, doc[key])
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")


def _write_attrs(parent, value: dict[str, Any], *, skip: set[str]) -> None:
    for key in ("serialNumber", "version"):
        if key in value and key not in skip:
            parent.set(key, str(value[key]))


def _element_name(key: str) -> str:
    return _RENAME.get(key, key)


def _write(parent, key: str, value: Any) -> None:
    if value is None:
        return
    name = _element_name(key)
    if isinstance(value, list):
        singular = _PLURAL.get(key, key.rstrip("s") or key)
        for item in value:
            if isinstance(item, dict) and _is_attribute_only(item):
                child = _sub(parent, singular)
                for k, v in item.items():
                    child.set(k, str(v))
                continue
            child = _sub(parent, singular)
            if isinstance(item, dict):
                _write_mapping(child, item)
            else:
                child.text = _text(item)
        return
    if isinstance(value, dict):
        child = _sub(parent, name)
        _write_mapping(child, value)
        return
    child = _sub(parent, name)
    child.text = _text(value)


def _is_attribute_only(item: dict[str, Any]) -> bool:
    return bool(item) and all(isinstance(v, (str, int, bool)) for v in item.values()) and (
        "alg" in item or "ref" in item or "expression" in item
    )


def _write_mapping(parent, mapping: dict[str, Any]) -> None:
    ordered = sorted(
        mapping.items(),
        key=lambda kv: (_COMPONENT_ORDER.index(kv[0]) if kv[0] in _COMPONENT_ORDER else 999, kv[0]),
    )
    for key, value in ordered:
        if value is None:
            continue
        if key in _ATTRS and isinstance(value, (str, int, bool)):
            parent.set(key, "true" if value is True else "false" if value is False else str(value))
            continue
        _write(parent, key, value)


def _sub(parent, tag: str):
    from lxml import etree

    return etree.SubElement(parent, tag)


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
