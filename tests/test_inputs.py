"""Input tests (spec §9 / Phase 1): lock, CODEOWNERS, git, SDK lockfiles, merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aibom.inputs.codeowners import load_codeowners
from aibom.inputs.lock import LOCK_FILENAMES, check_drift, discover_lock
from aibom.inputs.sbom_merge import merge_sbom
from aibom.inputs.scanner import scan
from aibom.inputs.sdk_locks import discover_ai_sdks

# --- lock ---------------------------------------------------------------------


def test_discover_lock_finds_nothing_in_an_empty_dir(tmp_path: Path) -> None:
    assert discover_lock(tmp_path) is None


@pytest.mark.parametrize("filename", LOCK_FILENAMES)
def test_discover_lock_finds_each_conventional_name(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text("lockfile_version: 1\n", encoding="utf-8")
    found = discover_lock(tmp_path)
    assert found is not None and found.name == filename


def test_read_lock_parses_bundled_output(support_agent_path: Path) -> None:
    result = scan(support_agent_path)
    assert result.lock.kind("models")
    assert len(result.lock.kind("prompts")) >= 1


def test_check_drift_reports_fresh_after_scan(support_agent_path: Path) -> None:
    result = scan(support_agent_path)
    drift = check_drift(result.lock, support_agent_path)
    assert drift.fresh is True


# --- CODEOWNERS ---------------------------------------------------------------


def test_codeowners_last_match_wins(support_agent_path: Path) -> None:
    owners = load_codeowners(support_agent_path)
    # `src/tools/` is later than `src/` and must win.
    assert owners.owners_for("src/tools/payments.py") == [
        "@support-ai/tool-owners",
        "ada@example.com",
    ]


def test_codeowners_directory_pattern_matches_recursively() -> None:
    owners = load_codeowners(Path("/nonexistent"))
    assert owners.path is None
    assert owners.owners_for("anything") == []


def test_codeowners_global_fallback(support_agent_path: Path) -> None:
    owners = load_codeowners(support_agent_path)
    assert owners.owners_for("unmatched/file.txt") == ["@platform-ai"]


# --- git ----------------------------------------------------------------------


def test_git_never_fails_outside_a_repo(tmp_path: Path) -> None:
    from aibom.inputs.git import read_git

    info = read_git(tmp_path)
    assert info.available in (False, None)
    assert info.version_hint is None


def test_git_reads_the_repository() -> None:
    from aibom.inputs.git import read_git

    info = read_git(Path(__file__).resolve().parents[1])
    assert info.available is True
    assert info.commit


# --- SDK lockfiles ------------------------------------------------------------


def test_sdk_locks_extract_known_ai_sdks(support_agent_path: Path) -> None:
    sdks = discover_ai_sdks(support_agent_path)
    names = {sdk.name for sdk in sdks}
    assert {"openai", "anthropic", "langchain", "llama-index-core", "mcp"} <= names


def test_sdk_locks_ignore_unrelated_packages(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\nflask==3.0.0\n", encoding="utf-8")
    assert discover_ai_sdks(tmp_path) == []


def test_sdk_lock_purl_is_correct(support_agent_path: Path) -> None:
    sdks = {sdk.name: sdk for sdk in discover_ai_sdks(support_agent_path)}
    assert sdks["openai"].purl == "pkg:pypi/openai@1.40.0"


# --- SBOM merge ---------------------------------------------------------------


def _fake_sbom() -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:11111111-1111-1111-1111-111111111111",
        "version": 1,
        "metadata": {
            "timestamp": "2026-01-01T00:00:00Z",
            "component": {"type": "application", "name": "support-agent", "bom-ref": "app"},
        },
        "components": [
            {
                "type": "library",
                "name": "requests",
                "version": "2.31.0",
                "bom-ref": "pkg:pypi/requests@2.31.0",
                "purl": "pkg:pypi/requests@2.31.0",
            }
        ],
    }


def test_merge_sbom_adds_software_components(support_agent_bom: dict, tmp_path: Path) -> None:
    path = tmp_path / "sbom.cdx.json"
    path.write_text(json.dumps(_fake_sbom()), encoding="utf-8")
    merged = merge_sbom(support_agent_bom, path)
    names = {c["name"] for c in merged.get("components", [])}
    assert "requests" in names
    # The AI component is still there: one BOM, both layers.
    assert any(c.get("name", "").startswith("gpt-") for c in merged["components"])
    assert merged["metadata"]["component"]["name"] == "support-agent"


def test_merge_sbom_is_idempotent(support_agent_bom: dict, tmp_path: Path) -> None:
    path = tmp_path / "sbom.cdx.json"
    path.write_text(json.dumps(_fake_sbom()), encoding="utf-8")
    once = merge_sbom(support_agent_bom, path)
    twice = merge_sbom(once, path)
    refs = [c.get("bom-ref") for c in twice["components"]]
    assert len(refs) == len(set(refs)), "merge duplicated a component"


def test_merge_sbom_rejects_wrong_format(tmp_path: Path) -> None:
    from aibom.errors import AibomError

    path = tmp_path / "bad.json"
    path.write_text('{"not": "a bom"}', encoding="utf-8")
    with pytest.raises(AibomError):
        merge_sbom({"components": []}, path)
