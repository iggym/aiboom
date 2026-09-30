"""Golden BOM tests (spec §9).

Three fixture repos, each a different shape of AI surface: a customer-facing
agent with a risky tool, an internal RAG service, and an MCP-heavy research
agent. Each generated BOM must:

  * validate against the vendored CycloneDX 1.6 schema,
  * be byte-stable across regenerations (digest invariance),
  * match the committed golden JSON.

Set `AIBOM_UPDATE_GOLDEN=1` to rewrite the goldens when a mapping change is
intentional; the diff should then be reviewed like any other code change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aibom.api import GenerateOptions, generate_full
from aibom.digest import digest_of
from aibom.validate import validate_bom

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"
UPDATE = os.environ.get("AIBOM_UPDATE_GOLDEN") == "1"

CASES = ["support-agent", "rag-service", "mcp-heavy"]


def _generate(name: str) -> tuple[dict, object]:
    root = (FIXTURES / name).resolve()
    return generate_full(GenerateOptions(root=root, refresh=True))


@pytest.mark.parametrize("name", CASES)
def test_bom_validates_against_cyclonedx(name: str) -> None:
    bom, _ = _generate(name)
    validate_bom(bom)


@pytest.mark.parametrize("name", CASES)
def test_digest_is_stable_across_regenerations(name: str) -> None:
    """F-OUT-6: content digest excludes serialNumber, timestamp and version."""
    first, _ = _generate(name)
    second, _ = _generate(name)
    assert digest_of(first) == digest_of(second)
    assert _without_volatile(first) == _without_volatile(second)


def _without_volatile(bom: dict) -> dict:
    stable = json.loads(json.dumps(bom))
    stable.pop("serialNumber", None)
    stable.pop("version", None)
    stable.get("metadata", {}).pop("timestamp", None)
    _strip_git(stable)
    return stable


# Git metadata reflects the checkout, not the mapping: commit hashes, branches,
# remotes and the dirty flag all differ between a developer's tree and CI. The
# golden describes the *mapping*, so these fields are stripped before comparison
# and asserted separately in `test_git_metadata_is_recorded`.
_GIT_KEYS = {"aibom:git_commit", "aibom:git_branch", "aibom:git_remote", "aibom:git_dirty"}


def _strip_git(bom: dict) -> None:
    component = bom.get("metadata", {}).get("component", {})
    if component.get("version", "").startswith("g"):
        component["version"] = "<git>"
    props = component.get("properties")
    if isinstance(props, list):
        component["properties"] = [p for p in props if p.get("name") not in _GIT_KEYS]


@pytest.mark.parametrize("name", CASES)
def test_matches_golden(name: str) -> None:
    bom, _ = _generate(name)
    target = GOLDEN / f"{name}.cdx.json"
    if UPDATE or not target.exists():
        target.parent.mkdir(exist_ok=True)
        # Timestamps and serial numbers churn; strip them so the golden is
        # about mapping, not about the clock.
        stable = json.loads(json.dumps(bom))
        stable.pop("serialNumber", None)
        stable["metadata"].pop("timestamp", None)
        _strip_git(stable)
        target.write_text(json.dumps(stable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"wrote golden {target.name}")

    expected = json.loads(target.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(bom))
    actual.pop("serialNumber", None)
    actual["metadata"].pop("timestamp", None)
    _strip_git(actual)
    assert actual == expected, f"{name} golden drifted; review then set AIBOM_UPDATE_GOLDEN=1"


@pytest.mark.parametrize("name", CASES)
def test_serial_number_is_a_urn_uuid(name: str) -> None:
    bom, _ = _generate(name)
    assert bom["serialNumber"].startswith("urn:uuid:")
    # A UUID is 36 chars after the scheme.
    assert len(bom["serialNumber"]) == len("urn:uuid:") + 36


@pytest.mark.parametrize("name", CASES)
def test_metadata_has_lifecycle_and_tool_versions(name: str) -> None:
    bom, _ = _generate(name)
    assert bom["metadata"]["lifecycles"] == [{"phase": "build"}]
    tools = bom["metadata"]["tools"]
    components = tools["components"] if isinstance(tools, dict) else tools
    names = {c["name"] for c in components}
    assert "aibom" in names
    version = next(c["version"] for c in components if c["name"] == "aibom")
    assert version


@pytest.mark.parametrize("name", CASES)
def test_git_metadata_is_recorded(name: str) -> None:
    """F-IN-4: git facts land on the application component, not in the golden.

    They are checkout-specific, so the golden comparison strips them; this test
    is what actually asserts they are present and never leak credentials.
    """
    bom, _ = _generate(name)
    component = bom["metadata"]["component"]
    props = {p["name"]: p["value"] for p in component.get("properties", [])}
    # The fixture repos are committed inside the aibom repo, so git is available.
    assert props.get("aibom:git_commit"), props
    assert props.get("aibom:git_branch") == "main"
    remote = props.get("aibom:git_remote", "")
    assert "@" not in remote, f"credentials leaked into the remote URL: {remote}"
