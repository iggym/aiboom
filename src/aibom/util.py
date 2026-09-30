"""Small shared helpers: identifiers, hashing, YAML with line numbers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml

# --- hashing ------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialisation used for digests and diffing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bom_digest(bom: dict[str, Any]) -> str:
    """SHA-256 content digest of a BOM (spec F-OUT-6).

    ``serialNumber``, ``metadata.timestamp`` and ``version`` are volatile — two
    runs over an unchanged repo must produce the same digest — so they are
    removed before hashing. Everything else, including tool versions and the
    rules version, is part of the digest on purpose: changing the rulebook
    legitimately changes the verdict.
    """
    scrubbed = json.loads(json.dumps(bom))  # deep copy, no shared references
    scrubbed.pop("serialNumber", None)
    scrubbed.pop("version", None)
    meta = scrubbed.get("metadata")
    if isinstance(meta, dict):
        meta.pop("timestamp", None)
    return sha256_text(canonical_json(scrubbed))


# --- identifiers --------------------------------------------------------------

_SPLIT_RE = re.compile(r"[^0-9A-Za-z]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake_split(identifier: str) -> str:
    """Normalise an identifier to space-separated lower-case words.

    ``writeFile`` -> ``write file``; ``delete_user_v2`` -> ``delete user v2``;
    ``gh.repos.create`` -> ``gh repos create``. Rule regexes run against this
    form so a single rule covers snake_case, camelCase and dotted names.
    """
    spaced = _CAMEL_RE.sub(" ", identifier)
    spaced = _SPLIT_RE.sub(" ", spaced)
    return re.sub(r"\s+", " ", spaced).strip().lower()


def slugify(text: str, *, max_len: int = 64) -> str:
    slug = _SPLIT_RE.sub("-", text.strip().lower()).strip("-")
    return slug[:max_len] or "unnamed"


def bom_ref(*parts: str) -> str:
    """Build a stable, human-readable bom-ref.

    Readability matters here: auditors read raw BOMs, and `bom-ref` strings
    leak into the dependency graph and the Mermaid diagram.
    """
    return ":".join(slugify(p) for p in parts if p)


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def first_sentence(text: str | None, *, limit: int = 160) -> str:
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for prompt sizing.

    Deliberately not tokeniser-specific: aibom must not depend on the model
    vendor's tokeniser, and the number is labelled ``approx_tokens``.
    """
    return max(1, round(len(text) / 4))


# --- YAML with line numbers ---------------------------------------------------


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that tags every mapping with the line it started on."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping = dict(loader.construct_pairs(node))
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_yaml_with_lines(path: Path) -> Any:
    """Load YAML, annotating each mapping with ``__line__`` (1-based)."""
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_LineLoader)


def strip_line_markers(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_line_markers(v) for k, v in obj.items() if k != "__line__"}
    if isinstance(obj, list):
        return [strip_line_markers(v) for v in obj]
    return obj


def line_of(obj: Any, *keys: str) -> int | None:
    """Best-effort line number for a nested key path inside annotated YAML."""
    node: Any = obj
    for key in keys:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    if isinstance(node, dict):
        return node.get("__line__")
    return None


def walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)


def dump_yaml(obj: Any) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, default_flow_style=False)
