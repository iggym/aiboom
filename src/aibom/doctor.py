"""`aibom doctor` — environment and repository diagnostics.

Written to answer "why did my BOM come out like that?" in one command. Every
line is actionable: what was found, and what to do about it.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from aibom import RULES_VERSION, __version__
from aibom.errors import DoctorFinding
from aibom.inputs.codeowners import CODEOWNERS_LOCATIONS, load_codeowners
from aibom.inputs.git import read_git
from aibom.inputs.lock import LOCK_FILENAMES, check_drift, discover_lock, read_lock
from aibom.inputs.scanner import surfacelock_available
from aibom.manifest import discover_manifest, load_manifest
from aibom.render.html import weasyprint_available
from aibom.risk import load_rulebook
from aibom.sign import cosign_path, sigstore_available
from aibom.validate import schema_version


def run_doctor(root: Path) -> list[DoctorFinding]:
    root = root.resolve()
    findings: list[DoctorFinding] = []

    findings.append(
        DoctorFinding("ok", "python", f"{platform.python_version()} on {platform.system()}")
    )
    findings.append(DoctorFinding("ok", "aibom", f"{__version__} (rules {RULES_VERSION})"))
    findings.append(
        DoctorFinding("ok", "cyclonedx-schema", schema_version())
    )

    # --- scanner --------------------------------------------------------------
    if surfacelock_available():
        findings.append(DoctorFinding("ok", "surfacelock", "importable; scanning delegates to it"))
    else:
        findings.append(
            DoctorFinding(
                "info",
                "surfacelock",
                "not installed; aibom will use its bundled deterministic scanner",
                fix="pip install 'aibom[scanner]' to use the canonical scanner",
            )
        )

    # --- lock -----------------------------------------------------------------
    lock_path = discover_lock(root)
    if lock_path is None:
        findings.append(
            DoctorFinding(
                "info",
                "surface.lock",
                f"not found (looked for {', '.join(LOCK_FILENAMES)})",
                fix="aibom generate --refresh will scan in-process and mark compositions incomplete-safe",
            )
        )
    else:
        try:
            lock = read_lock(lock_path, root=root)
        except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
            findings.append(DoctorFinding("error", "surface.lock", f"unreadable: {exc}"))
        else:
            drift = check_drift(lock, root)
            level = "ok" if drift.fresh else "warning"
            findings.append(
                DoctorFinding(
                    level,
                    "surface.lock",
                    f"{lock_path.name} (v{lock.version}, scanner {lock.scanner}) — {drift.note()}",
                    fix=None if drift.fresh else "aibom generate --refresh",
                )
            )
            counts = lock.counts()
            findings.append(
                DoctorFinding(
                    "info",
                    "lock inventory",
                    ", ".join(f"{k}={v}" for k, v in counts.items()),
                )
            )

    # --- manifest -------------------------------------------------------------
    manifest_path = discover_manifest(root)
    if manifest_path is None:
        findings.append(
            DoctorFinding(
                "info",
                "aibom.yaml",
                "not found; the BOM will be inference-only",
                fix="aibom init",
            )
        )
    else:
        try:
            manifest = load_manifest(root)
        except Exception as exc:  # noqa: BLE001
            findings.append(
                DoctorFinding("error", "aibom.yaml", f"invalid: {exc}", fix="aibom manifest validate")
            )
        else:
            findings.append(
                DoctorFinding(
                    "ok",
                    "aibom.yaml",
                    f"{manifest_path.name}: {len(manifest.models)} model(s), "
                    f"{len(manifest.tools)} tool override(s), {len(manifest.datasets)} dataset(s)",
                )
            )

    # --- CODEOWNERS -----------------------------------------------------------
    codeowners = load_codeowners(root)
    if codeowners.path is None:
        findings.append(
            DoctorFinding(
                "info",
                "CODEOWNERS",
                f"not found (looked in {', '.join(CODEOWNERS_LOCATIONS)})",
                fix="add CODEOWNERS so prompts get owners, or set system.owner as a fallback",
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "ok",
                "CODEOWNERS",
                f"{codeowners.path.relative_to(root)} with {len(codeowners.rules)} rule(s)",
            )
        )

    # --- git ------------------------------------------------------------------
    git = read_git(root)
    if not git.available:
        findings.append(
            DoctorFinding(
                "warning",
                "git",
                "not a git repository; commit/branch/tag will be empty in the BOM",
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "ok",
                "git",
                f"{git.short_commit or '?'} on {git.branch or 'detached'}"
                + (f", tag {git.tag}" if git.tag else "")
                + (" (dirty)" if git.dirty else ""),
            )
        )

    # --- optional extras ------------------------------------------------------
    findings.append(
        DoctorFinding(
            "ok" if weasyprint_available() else "info",
            "pdf extra",
            "WeasyPrint available" if weasyprint_available() else "WeasyPrint not installed",
            fix=None if weasyprint_available() else "pip install 'aibom[pdf]' for --pdf",
        )
    )
    findings.append(
        DoctorFinding(
            "ok" if cosign_path() else ("ok" if sigstore_available() else "info"),
            "sign extra",
            f"cosign at {cosign_path()}"
            if cosign_path()
            else ("sigstore-python available" if sigstore_available() else "no signing backend"),
            fix=None if (cosign_path() or sigstore_available()) else "pip install 'aibom[sign]'",
        )
    )

    # --- rulebook -------------------------------------------------------------
    try:
        book = load_rulebook()
        findings.append(
            DoctorFinding(
                "ok",
                "rulebook",
                f"{len(book.rules)} rules, {len(book.packages)} curated MCP packages "
                f"(version {book.rules_version})",
            )
        )
    except Exception as exc:  # noqa: BLE001
        findings.append(DoctorFinding("error", "rulebook", f"failed to load: {exc}"))

    return findings


def render_doctor(findings: list[DoctorFinding], *, colour: bool = False) -> str:
    marks = {"ok": "✓", "info": "·", "warning": "!", "error": "✗"}
    colours = {"ok": "\033[32m", "info": "\033[36m", "warning": "\033[33m", "error": "\033[31m"}
    reset = "\033[0m"
    lines: list[str] = []
    for finding in findings:
        level = str(finding["level"])
        mark = marks.get(level, "?")
        prefix = f"{colours.get(level, '')}{mark}{reset}" if colour else mark
        lines.append(f"{prefix} {finding['name']}: {finding['detail']}")
        if finding.get("fix"):
            lines.append(f"    → {finding['fix']}")
    return "\n".join(lines)


def as_dict(findings: list[DoctorFinding]) -> dict[str, Any]:
    errors = sum(1 for f in findings if f["level"] == "error")
    warnings = sum(1 for f in findings if f["level"] == "warning")
    return {
        "aibom_version": __version__,
        "rules_version": RULES_VERSION,
        "errors": errors,
        "warnings": warnings,
        "findings": [dict(f) for f in findings],
    }


def exit_code(findings: list[DoctorFinding]) -> int:
    from aibom.errors import EXIT_OK

    return EXIT_OK if not any(f["level"] == "error" for f in findings) else 1


def python_info() -> str:
    return f"{sys.implementation.name} {sys.version.split()[0]}"
