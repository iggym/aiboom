"""Python API (spec §6.7).

    from aibom import generate, diff, render_markdown

    bom = generate(".")                     # dict, ready to json.dump
    changes = diff("old.cdx.json", "new.cdx.json")
    markdown = render_markdown(bom)

`generate` is the same code path the CLI uses, so the API can never produce a
different BOM than `aibom generate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aibom import __version__
from aibom.digest import digest_of, write_digest
from aibom.inputs import (
    check_drift,
    discover_lock,
    load_codeowners,
    read_git,
    read_lock,
    scan,
)
from aibom.inputs.sbom_merge import load_sbom, merge_sbom
from aibom.manifest import Manifest, load_manifest
from aibom.mapping import build_bom, merge_declared
from aibom.model.cyclonedx import json_to_xml, to_cyclonedx_json
from aibom.validate import validate_bom


@dataclass(slots=True)
class GenerateOptions:
    """Everything `generate` can be told to do. Mirrors the CLI flags."""

    root: Path = Path(".")
    manifest: Path | None = None
    lock: Path | None = None
    refresh: bool = False
    scanner: str = "auto"
    previous: Path | None = None
    merge_sbom: Path | None = None
    include_serial: bool = True
    validate: bool = True


def generate(root: str | Path = ".", **kwargs: Any) -> dict[str, Any]:
    """Generate an AI BOM for ``root`` and return it as a CycloneDX dict."""
    options = GenerateOptions(root=Path(root).resolve())
    for key, value in kwargs.items():
        if not hasattr(options, key):
            raise TypeError(f"generate() got an unexpected keyword argument {key!r}")
        setattr(options, key, value)
    bom, _ = generate_full(options)
    return bom


def generate_full(options: GenerateOptions) -> tuple[dict[str, Any], Any]:
    """Generate the BOM **and** return the internal model.

    The CLI uses this so it can render Markdown/HTML and evaluate review notes
    without re-parsing its own JSON output.
    """
    root = options.root
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    if root.is_file():
        root = root.parent

    manifest = load_manifest(root, options.manifest)
    codeowners = load_codeowners(root)
    git = read_git(root)

    lock_path = discover_lock(root, options.lock)
    if lock_path is None or options.refresh:
        result = scan(root, prefer=options.scanner)
        lock = result.lock
        lock_fresh = True  # a fresh scan is by definition current
        lock_note = "scanned in-process for this run"
        scanner = result.source
    else:
        lock = read_lock(lock_path, root=root)
        drift = check_drift(lock, root)
        lock_fresh = drift.fresh
        lock_note = drift.note()
        scanner = lock.scanner

    lock = merge_declared(lock, manifest)

    from aibom.inputs.sdk_locks import discover_ai_sdks

    ai_sdks = discover_ai_sdks(root)

    model = build_bom(
        root=root,
        lock=lock,
        manifest=manifest,
        codeowners=codeowners,
        git=git,
        ai_sdks=ai_sdks,
        lock_fresh=lock_fresh,
        lock_note=lock_note,
        scanner=scanner,
    )

    version = _next_version(options.previous)
    bom = to_cyclonedx_json(model, version=version, include_serial=options.include_serial)

    if options.merge_sbom is not None:
        sbom = load_sbom(Path(options.merge_sbom))
        bom = merge_sbom(bom, sbom)
        # Re-validate: the merge is the only place foreign JSON enters the BOM.
        if options.validate:
            validate_bom(bom, source="merged BOM")

    if options.validate:
        validate_bom(bom, source=f"{model.app_name} BOM")

    model.merged_components = list(bom.get("components", [])) if options.merge_sbom else []
    return bom, model


def _next_version(previous: Path | None) -> int:
    """F-OUT-1: increment `version` when the previous BOM is supplied."""
    if previous is None:
        return 1
    path = Path(previous)
    if not path.exists():
        return 1
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    try:
        return int(data.get("version", 0)) + 1
    except (TypeError, ValueError):
        return 1


def generate_to_file(
    target: Path,
    options: GenerateOptions | None = None,
    *,
    fmt: str = "json",
) -> tuple[Path, dict[str, Any]]:
    """Generate and write a BOM plus its `.sha256` sidecar."""
    options = options or GenerateOptions()
    bom, _ = generate_full(options)
    if fmt == "xml":
        target.write_text(json_to_xml(bom), encoding="utf-8")
    else:
        import json

        target.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if fmt == "json":
        write_digest(bom, target)
    return target, bom


def bom_digest(bom: dict[str, Any]) -> str:
    return digest_of(bom)


def manifest_for(root: str | Path = ".") -> Manifest:
    return load_manifest(Path(root).resolve())


__all__ = [
    "__version__",
    "GenerateOptions",
    "generate",
    "generate_full",
    "generate_to_file",
    "bom_digest",
    "manifest_for",
]
