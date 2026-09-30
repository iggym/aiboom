"""Python API tests (spec §6.7): `generate`, `diff`, `render_markdown`.

The API must be the *same* code path as the CLI, so a BOM produced through
`aibom.generate` and one produced by `aibom generate` must agree on their
content digest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import aibom

FIXTURES = Path(__file__).parent / "fixtures"


def test_public_surface_is_importable() -> None:
    for name in ("generate", "diff", "render_markdown", "render_html", "validate_bom"):
        assert hasattr(aibom, name), name


def test_generate_returns_a_dict(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    bom = aibom.generate(root, refresh=True)
    assert isinstance(bom, dict)
    assert bom["specVersion"] == "1.6"
    json.dumps(bom)  # must be serialisable


def test_generate_accepts_a_string_path() -> None:
    root = str((FIXTURES / "support-agent").resolve())
    bom = aibom.generate(root, refresh=True)
    assert bom["metadata"]["component"]["name"]


def test_api_and_cli_agree_on_digest(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    api_bom = aibom.generate(root, refresh=True)
    out = tmp_path / "cli.cdx.json"
    subprocess.run(
        [sys.executable, "-m", "aibom", "generate", str(root), "-o", str(out), "--refresh", "--quiet"],
        check=True, capture_output=True,
    )
    cli_bom = json.loads(out.read_text(encoding="utf-8"))
    assert aibom.bom_digest(api_bom) == aibom.bom_digest(cli_bom)


def test_render_markdown_from_dict() -> None:
    bom = aibom.generate((FIXTURES / "support-agent").resolve(), refresh=True)
    text = aibom.render_markdown(bom)
    assert "## Review notes" in text


def test_diff_from_files(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    bom = aibom.generate(root, refresh=True)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(bom), encoding="utf-8")
    b.write_text(json.dumps(bom), encoding="utf-8")
    result = aibom.diff(a, b)
    assert result.unchanged


def test_validate_bom_raises_on_garbage() -> None:
    from aibom.errors import ValidationError

    with pytest.raises(ValidationError):
        aibom.validate_bom({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"type": "x"}]})


def test_generate_with_previous_increments_version(tmp_path: Path) -> None:
    root = (FIXTURES / "support-agent").resolve()
    first = tmp_path / "v1.json"
    first.write_text(json.dumps({"version": 4}), encoding="utf-8")
    bom = aibom.generate(root, refresh=True, previous=first)
    assert bom["version"] == 5


def test_manifest_for_returns_a_manifest() -> None:
    manifest = aibom.manifest_for((FIXTURES / "support-agent").resolve())
    assert manifest.path is not None
    assert manifest.system.get("name") == "support-agent"
