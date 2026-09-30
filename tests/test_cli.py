"""CLI tests (spec §6.6, §9): exit codes, `--strict`, `render`, `explain-risk`.

The CLI is the product surface, so these exercise the real command-line entry
point in a subprocess — no mocking of argument parsing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aibom", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_version_flag() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_help_lists_the_commands() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for command in (
        "generate",
        "init",
        "validate",
        "render",
        "diff",
        "explain-risk",
        "attest",
        "verify",
        "doctor",
    ):
        assert command in result.stdout


def test_generate_writes_a_bom(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    result = run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    assert result.returncode == 0, result.stderr
    bom = json.loads(out.read_text(encoding="utf-8"))
    assert bom["specVersion"] == "1.6"
    assert (tmp_path / "aibom.cdx.json.sha256").exists()


def test_generate_markdown_and_html(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    md = tmp_path / "AIBOM.md"
    html = tmp_path / "AIBOM.html"
    result = run_cli(
        "generate", str(root), "-o", str(tmp_path / "aibom.cdx.json"),
        "--markdown", str(md), "--html", str(html), "--refresh", "--quiet",
    )
    assert result.returncode == 0, result.stderr
    assert md.exists() and "## Review notes" in md.read_text(encoding="utf-8")
    assert html.exists() and "<html" in html.read_text(encoding="utf-8").lower()


def test_generate_xml(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.xml"
    result = run_cli("generate", str(root), "-o", str(out), "--format", "xml", "--refresh", "--quiet")
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert text.count("xmlns=") == 1


def test_strict_fails_when_review_notes_have_errors(tmp_path: Path) -> None:
    """mcp-heavy has an error-level note (high-risk tool, no HITL)."""
    root = (FIXTURES / "mcp-heavy").resolve()
    result = run_cli("generate", str(root), "-o", str(tmp_path / "bom.json"), "--refresh", "--strict")
    assert result.returncode == 4, result.stdout + result.stderr


def test_validate_accepts_a_generated_bom(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    result = run_cli("validate", str(out))
    assert result.returncode == 0, result.stdout + result.stderr


def test_validate_rejects_a_broken_bom(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(
        '{"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,'
        ' "components": [{"type": "not-a-real-type", "name": "x"}]}',
        encoding="utf-8",
    )
    result = run_cli("validate", str(path))
    assert result.returncode == 3, result.stdout + result.stderr


def test_render_regenerates_markdown_from_a_bom(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    md = tmp_path / "from-bom.md"
    result = run_cli("render", str(out), "--markdown", str(md))
    assert result.returncode == 0, result.stderr
    assert "## Review notes" in md.read_text(encoding="utf-8")


def test_diff_reports_no_changes(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    result = run_cli("diff", str(out), str(out))
    assert result.returncode == 0
    assert "no changes" in result.stdout.lower()


def test_diff_fail_on_change_gate(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    run_cli("generate", str(root), "-o", str(old), "--refresh", "--quiet")
    bom = json.loads(old.read_text(encoding="utf-8"))
    for component in bom["components"]:
        if component["name"] == "lookup_ticket":
            component["name"] = "lookup_ticket_v2"
    new.write_text(json.dumps(bom), encoding="utf-8")
    result = run_cli("diff", str(old), str(new), "--fail-on-change")
    assert result.returncode == 5, result.stdout + result.stderr


def test_init_writes_a_manifest(tmp_path: Path) -> None:
    result = run_cli("init", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "aibom.yaml").exists()


def test_init_creates_the_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "brand-new-project"
    assert not target.exists()
    result = run_cli("init", str(target))
    assert result.returncode == 0, result.stderr
    assert (target / "aibom.yaml").exists()


def test_manifest_validate_accepts_the_fixture() -> None:
    root = (FIXTURES / "support-agent").resolve()
    result = run_cli("manifest", "validate", str(root / "aibom.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_validate_reports_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "aibom.yaml"
    path.write_text(
        "schema: 1\nsystem:\n  name: demo\nmodels:\n  gpt-4.1:\n    hosting_region: 42\n",
        encoding="utf-8",
    )
    result = run_cli("manifest", "validate", str(path))
    assert result.returncode != 0
    assert "6" in (result.stdout + result.stderr)


def test_explain_risk_names_the_rule() -> None:
    result = run_cli("explain-risk", "issue_refund")
    assert result.returncode == 0, result.stderr
    assert "financial" in result.stdout.lower()


def test_explain_risk_for_unknown_tool_is_graceful() -> None:
    result = run_cli("explain-risk", "frobnicate_widget")
    assert result.returncode in (0, 1)
    assert result.stdout or result.stderr


def test_doctor_runs() -> None:
    result = run_cli("doctor")
    assert result.returncode in (0, 7), result.stdout + result.stderr
    assert "python" in result.stdout.lower() or "Python" in result.stdout


def test_verify_without_signature_falls_back_to_digest(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    result = run_cli("verify", str(out))
    # No signature present: the digest fallback should still report the state.
    assert result.returncode in (0, 6)
    assert result.stdout or result.stderr


@pytest.mark.skipif(shutil.which("cosign") is None, reason="cosign not installed")
def test_attest_and_verify_round_trip(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    out = tmp_path / "aibom.cdx.json"
    run_cli("generate", str(root), "-o", str(out), "--refresh", "--quiet")
    signed = run_cli("attest", str(out))
    if signed.returncode != 0:
        pytest.skip("cosign could not sign in this environment (no OIDC)")
    verified = run_cli("verify", str(out))
    assert verified.returncode == 0, verified.stdout + verified.stderr
