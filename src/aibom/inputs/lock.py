"""`surface.lock` reading and drift checking (spec F-IN-1, F-OUT-4).

`surface.lock` is the canonical artifact produced by `surfacelock`. aibom
consumes it verbatim when present so that the AI BOM and the AI lockfile can
never disagree. The lock is deliberately a plain YAML/JSON document with a
``lockfile_version`` — aibom refuses to guess at unknown versions rather than
silently producing a wrong inventory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aibom.errors import LockError
from aibom.util import sha256_file, snake_split

LOCK_FILENAMES = ("surface.lock", "surface.lock.yaml", "surface.lock.json")
SUPPORTED_LOCK_VERSIONS = {1}

#: Kinds aibom can take from the lock. Order is presentation order.
LOCK_KINDS = (
    "models",
    "prompts",
    "tools",
    "mcp_servers",
    "providers",
    "libraries",
    "datasets",
)


@dataclass(slots=True)
class SurfaceLock:
    path: Path
    root: Path
    data: dict[str, Any] = field(default_factory=dict)
    #: True when the lock was produced in-process during this run rather than
    #: read from disk. Recorded in the BOM so an auditor knows the provenance.
    generated: bool = False

    @property
    def version(self) -> int:
        return int(self.data.get("lockfile_version", 1))

    @property
    def scanner(self) -> str:
        return str(self.data.get("scanner", "surfacelock"))

    @property
    def generated_at(self) -> str | None:
        return self.data.get("generated_at")

    def kind(self, name: str) -> list[dict[str, Any]]:
        value = self.data.get(name) or []
        if isinstance(value, dict):
            # Tolerate mapping form: {name: {...}} -> [{name: ...}, ...]
            return [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in value.items()]
        if not isinstance(value, list):
            raise LockError(f"{self.path}: `{name}` must be a list or mapping")
        return [v for v in value if isinstance(v, dict)]

    @property
    def files(self) -> dict[str, str]:
        files = self.data.get("files") or {}
        if isinstance(files, dict):
            return {str(k): str(v) for k, v in files.items()}
        return {}

    def counts(self) -> dict[str, int]:
        return {kind: len(self.kind(kind)) for kind in LOCK_KINDS}

    def empty(self) -> bool:
        return all(count == 0 for count in self.counts().values())


def discover_lock(root: Path, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        if not explicit.exists():
            raise LockError(f"lock file not found: {explicit}")
        return explicit
    for name in LOCK_FILENAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def read_lock(path: Path, *, root: Path | None = None) -> SurfaceLock:
    """Read and structurally validate a `surface.lock`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LockError(f"cannot read {path}: {exc}") from exc

    try:
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise LockError(f"{path} is not valid YAML/JSON: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise LockError(f"{path}: expected a mapping at the top level")

    version = data.get("lockfile_version", 1)
    try:
        version_int = int(version)
    except (TypeError, ValueError):
        raise LockError(
            f"{path}: `lockfile_version` must be an integer, got {version!r}",
            hint="regenerate the lock with a surfacelock that matches your aibom version",
        ) from None
    if version_int not in SUPPORTED_LOCK_VERSIONS:
        raise LockError(
            f"{path}: unsupported lockfile_version {version_int}",
            hint=f"aibom {__import__('aibom').__version__} understands {sorted(SUPPORTED_LOCK_VERSIONS)}",
        )

    return SurfaceLock(path=path, root=root or path.parent, data=data)


@dataclass(slots=True)
class DriftReport:
    """Result of re-checking the lock against the working tree."""

    fresh: bool
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    reason: str = ""

    def note(self) -> str:
        if self.fresh:
            return "surface.lock matches the working tree"
        bits = []
        if self.changed:
            bits.append(f"{len(self.changed)} changed")
        if self.missing:
            bits.append(f"{len(self.missing)} missing")
        if self.added:
            bits.append(f"{len(self.added)} new")
        detail = ", ".join(bits) if bits else "no comparable file hashes"
        return f"surface.lock is stale ({detail})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fresh": self.fresh,
            "changed": self.changed,
            "missing": self.missing,
            "added": self.added,
            "reason": self.reason,
        }


def check_drift(lock: SurfaceLock, root: Path | None = None) -> DriftReport:
    """Compare the lock's recorded file hashes against the working tree.

    This is the `surfacelock check` equivalent used for F-OUT-4: a BOM may only
    claim ``complete`` for scanned kinds when the lock it was built from is
    fresh. When the lock records no hashes we cannot make that claim, so we
    report not-fresh with an explicit reason rather than guessing.
    """
    base = root or lock.root
    recorded = lock.files
    if not recorded:
        return DriftReport(fresh=False, reason="lock records no file hashes")

    changed: list[str] = []
    missing: list[str] = []
    for rel, expected in sorted(recorded.items()):
        target = base / rel
        if not target.exists():
            missing.append(rel)
            continue
        if sha256_file(target) != expected:
            changed.append(rel)

    fresh = not changed and not missing
    reason = "" if fresh else DriftReport(False, changed, missing).note()
    return DriftReport(fresh=fresh, changed=changed, missing=missing, reason=reason)


def lock_summary(lock: SurfaceLock) -> dict[str, Any]:
    return {
        "path": str(lock.path),
        "generated": lock.generated,
        "scanner": lock.scanner,
        "generated_at": lock.generated_at,
        "lockfile_version": lock.version,
        "counts": lock.counts(),
    }


def normalise_capabilities(values: Any) -> list[str]:
    """Capability labels from a lock are advisory; normalise their spelling."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [snake_split(str(v)).replace(" ", "-") for v in values if str(v).strip()]
