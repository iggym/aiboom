"""Manifest tests (spec §9): line-numbered errors, `init`, semantics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from aibom.errors import ManifestError
from aibom.manifest import load_manifest, write_example_manifest


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "aibom.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_absent_manifest_is_not_an_error(tmp_path: Path) -> None:
    manifest = load_manifest(tmp_path)
    assert manifest.path is None
    assert manifest.raw["schema"] == 1


def test_absent_manifest_raises_when_required(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path, required=True)


def test_valid_manifest_loads(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
          owner: team@example.com
        models:
          gpt-4.1:
            purpose: Draft replies.
        """,
    )
    manifest = load_manifest(tmp_path)
    assert manifest.system.get("name") == "demo"
    assert manifest.model("gpt-4.1")["purpose"] == "Draft replies."


def test_schema_error_reports_a_line_number(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
        models:
          gpt-4.1:
            hosting_region: 42
        """,
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tmp_path)
    problems = excinfo.value.problems
    assert problems, "expected at least one problem"
    line = problems[0][0]
    assert line is not None and line >= 6, f"expected the `hosting_region` line, got {problems}"


def test_yaml_syntax_error_reports_a_line(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
          owner: [unclosed
        """,
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tmp_path)
    assert "YAML" in excinfo.value.message


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
        nonsense: true
        """,
    )
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_invalid_schema_version_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "schema: 99\nsystem:\n  name: demo\n")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_retention_without_units_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
        datasets:
          - name: tickets
            pii: true
            retention: 24
        """,
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tmp_path)
    assert "retention" in str(excinfo.value.problems).lower()


def test_pii_without_consent_basis_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        schema: 1
        system:
          name: demo
        datasets:
          - name: tickets
            pii: true
            retention: 24 months
        """,
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tmp_path)
    assert "consent" in str(excinfo.value.problems).lower()


def test_write_example_manifest_is_valid(tmp_path: Path) -> None:
    path = write_example_manifest(tmp_path)
    assert path.exists()
    manifest = load_manifest(tmp_path)
    assert manifest.path == path
    assert manifest.system.get("name")


def test_write_example_manifest_does_not_clobber(tmp_path: Path) -> None:
    (tmp_path / "aibom.yaml").write_text("schema: 1\nsystem:\n  name: keep-me\n", encoding="utf-8")
    # Refusing is the safe default; `--force` is the explicit opt-in.
    with pytest.raises(ManifestError):
        write_example_manifest(tmp_path)
    assert load_manifest(tmp_path).system.get("name") == "keep-me"
    write_example_manifest(tmp_path, force=True)
    assert load_manifest(tmp_path).system.get("name") != "keep-me"


def test_manifest_accessors_are_none_safe(tmp_path: Path) -> None:
    manifest = load_manifest(tmp_path)
    assert manifest.model("anything") == {}
    assert manifest.tool("anything") == {}
    assert manifest.mcp_server("anything") == {}


def test_git_version_hint_is_used(tmp_path: Path) -> None:
    _write(tmp_path, "schema: 1\nsystem:\n  name: demo\n  version: git\n")
    manifest = load_manifest(tmp_path)
    assert manifest.system.get("version") == "git"
