"""Review-notes engine tests (spec F-RISK-4, §9: "each note has a test").

Each test drives the real pipeline (`build_bom`) with one thing changed, so a
note appears or disappears for a reason an auditor could reproduce.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from aibom.inputs.codeowners import load_codeowners
from aibom.inputs.git import read_git
from aibom.inputs.scanner import scan
from aibom.inputs.sdk_locks import discover_ai_sdks
from aibom.manifest import load_manifest
from aibom.mapping import build_bom, merge_declared
from aibom.model.components import AiBom
from aibom.risk.review import build_review_notes, has_errors, summarise

FIXTURES = Path(__file__).parent / "fixtures"


def _pipeline(
    fixture: str = "support-agent",
    *,
    lock_fresh: bool = True,
    manifest_root: Path | None = None,
) -> AiBom:
    root = (FIXTURES / fixture).resolve()
    manifest = load_manifest(manifest_root or root)
    lock = merge_declared(scan(root).lock, manifest)
    return build_bom(
        root=root,
        lock=lock,
        manifest=manifest,
        codeowners=load_codeowners(root),
        git=read_git(root),
        ai_sdks=discover_ai_sdks(root),
        lock_fresh=lock_fresh,
        lock_note=None if lock_fresh else "surface.lock is stale (files changed)",
        scanner="surfacelock",
    )


@pytest.fixture(scope="module")
def model() -> AiBom:
    return _pipeline()


def _codes(bom: AiBom, today: date | None = None) -> set[str]:
    return {n.code for n in build_review_notes(bom, today=today)}


def test_fixture_bom_flags_the_high_risk_tool_without_hitl(model: AiBom) -> None:
    assert "tool.high_risk_no_hitl" in _codes(model)


def test_floating_alias_is_flagged(model: AiBom) -> None:
    assert "model.floating" in _codes(model)


def test_retired_model_is_flagged(model: AiBom) -> None:
    model.models[0].retirement = "2020-01-01"
    assert "model.retired" in _codes(model, date(2026, 9, 30))


def test_retiring_model_is_flagged(model: AiBom) -> None:
    model.models[0].retirement = "2026-12-01"
    assert "model.retiring" in _codes(model, date(2026, 9, 30))


def test_model_without_purpose_is_flagged(model: AiBom) -> None:
    model.models[0].purpose = None
    assert "model.no_purpose" in _codes(model)


def test_mcp_plain_http_is_flagged(model: AiBom) -> None:
    server = model.mcp_servers[0]
    server.transport = "http"
    server.url = "http://internal.example.com/mcp"
    assert "mcp.insecure_transport" in _codes(model)


def test_mcp_unpinned_package_is_flagged(model: AiBom) -> None:
    server = model.mcp_servers[0]
    server.package = "@modelcontextprotocol/server-filesystem"
    server.version = None
    server.version_pinned = False
    assert "mcp.unpinned_package" in _codes(model)


def test_prompt_without_owner_is_flagged(model: AiBom) -> None:
    model.prompts[0].owners = []
    assert "prompt.no_owner" in _codes(model)


def test_dataset_pii_without_consent_is_flagged(model: AiBom) -> None:
    dataset = model.datasets[0]
    dataset.pii = True
    dataset.sensitive_data = ["email"]
    dataset.consent_basis = None
    assert "dataset.pii_no_consent" in _codes(model)


def test_dataset_pii_without_retention_is_flagged(model: AiBom) -> None:
    dataset = model.datasets[0]
    dataset.pii = True
    dataset.retention = None
    assert "dataset.pii_no_retention" in _codes(model)


def test_risk_override_with_justification_is_not_flagged(model: AiBom) -> None:
    """An override *with* a justification is recorded in the BOM, not flagged."""
    codes = _codes(model)
    assert "tool.risk_override" not in codes
    assert "mcp.risk_override" not in codes


def test_risk_override_without_justification_is_flagged(model: AiBom) -> None:
    model.tools[0].justification = None
    model.tools[0].risk_override = True
    assert "tool.risk_override" in _codes(model)


def test_stale_lock_is_flagged() -> None:
    assert "lock.stale" in _codes(_pipeline(lock_fresh=False))


def test_missing_manifest_is_flagged(tmp_path: Path) -> None:
    assert "manifest.absent" in _codes(_pipeline(manifest_root=tmp_path))


def test_system_facts_gaps_are_flagged_without_a_manifest() -> None:
    codes = _codes(_pipeline("mcp-heavy"))
    assert "system.no_risk_classification" in codes
    assert "system.no_human_oversight" in codes


def test_has_errors_matches_error_level_notes(model: AiBom) -> None:
    notes = build_review_notes(model)
    errors = [n for n in notes if n.level == "error"]
    assert has_errors(notes) == bool(errors)


def test_every_note_has_a_code_and_message(model: AiBom) -> None:
    for note in build_review_notes(model):
        assert note.code and "." in note.code, note
        assert note.message, note
        assert note.level in {"error", "warning", "info"}, note


def test_summary_line_counts_every_level(model: AiBom) -> None:
    notes = build_review_notes(model)
    line = summarise(notes)
    errors = len([n for n in notes if n.level == "error"])
    warnings = len([n for n in notes if n.level == "warning"])
    infos = len([n for n in notes if n.level == "info"])
    assert line == f"{errors} error(s), {warnings} warning(s), {infos} info"
