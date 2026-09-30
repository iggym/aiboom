"""Input adapters: everything aibom reads from the repository."""

from __future__ import annotations

from aibom.inputs.codeowners import CodeOwners, load_codeowners, owners_for
from aibom.inputs.git import GitInfo, read_git
from aibom.inputs.lock import DriftReport, SurfaceLock, check_drift, discover_lock, read_lock
from aibom.inputs.sbom_merge import merge_sbom
from aibom.inputs.scanner import ScanResult, scan
from aibom.inputs.sdk_locks import AiSdk, discover_ai_sdks

__all__ = [
    "CodeOwners",
    "load_codeowners",
    "owners_for",
    "GitInfo",
    "read_git",
    "SurfaceLock",
    "DriftReport",
    "discover_lock",
    "read_lock",
    "check_drift",
    "merge_sbom",
    "ScanResult",
    "scan",
    "AiSdk",
    "discover_ai_sdks",
]
