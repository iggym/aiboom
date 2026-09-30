"""Digest and validation tests (spec F-OUT-5, F-OUT-6, §9).

The digest is what `diff`, `validate` and the attestation all key off, so the
properties that matter are: it ignores the volatile fields, it changes when a
single prompt changes, and the sidecar round-trips.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aibom.api import GenerateOptions, generate_full
from aibom.digest import digest_of, read_digest, text_digest, verify_digest, write_digest
from aibom.errors import ValidationError
from aibom.validate import validate_bom

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def bom() -> dict:
    root = (FIXTURES / "support-agent").resolve()
    return generate_full(GenerateOptions(root=root, refresh=True))[0]


def test_digest_ignores_serial_number(bom: dict) -> None:
    other = copy.deepcopy(bom)
    other["serialNumber"] = "urn:uuid:00000000-0000-0000-0000-000000000000"
    assert digest_of(bom) == digest_of(other)


def test_digest_ignores_timestamp(bom: dict) -> None:
    other = copy.deepcopy(bom)
    other["metadata"]["timestamp"] = "2000-01-01T00:00:00Z"
    assert digest_of(bom) == digest_of(other)


def test_digest_ignores_version(bom: dict) -> None:
    other = copy.deepcopy(bom)
    other["version"] = 99
    assert digest_of(bom) == digest_of(other)


def test_digest_changes_when_a_prompt_changes(bom: dict) -> None:
    other = copy.deepcopy(bom)
    prompt = next(
        c for c in other["components"]
        if c["type"] == "data" and any(d.get("classification") == "prompt" for d in c.get("data", []))
    )
    prompt["hashes"] = [{"alg": "SHA-256", "content": "f" * 64}]
    assert digest_of(bom) != digest_of(other)


def test_digest_is_hex_sha256(bom: dict) -> None:
    value = digest_of(bom)
    assert len(value) == 64
    int(value, 16)


def test_sidecar_round_trips(bom: dict, tmp_path: Path) -> None:
    path = tmp_path / "aibom.cdx.json"
    path.write_text(json.dumps(bom), encoding="utf-8")
    sidecar = write_digest(bom, path)
    assert sidecar.exists()
    assert read_digest(path) == digest_of(bom)
    ok, expected, actual = verify_digest(path, bom)
    assert ok and expected == actual


def test_verify_digest_detects_tampering(bom: dict, tmp_path: Path) -> None:
    path = tmp_path / "aibom.cdx.json"
    tampered = copy.deepcopy(bom)
    tampered["components"].append({"type": "library", "name": "sneaky", "version": "1.0.0"})
    path.write_text(json.dumps(tampered), encoding="utf-8")
    write_digest(bom, path)  # sidecar for the untampered BOM
    ok, _expected, _actual = verify_digest(path)
    assert ok is False


def test_text_digest_is_stable() -> None:
    assert text_digest("hello") == text_digest("hello")
    assert text_digest("hello") != text_digest("hello ")


# --- validation ---------------------------------------------------------------


def test_valid_bom_passes_schema(bom: dict) -> None:
    validate_bom(bom)


def test_missing_metadata_component_fails(bom: dict) -> None:
    broken = copy.deepcopy(bom)
    broken["metadata"].pop("component", None)
    # `metadata.component` is optional in the schema but required by ingestors,
    # so the check lives behind `strict`.
    validate_bom(broken)
    with pytest.raises(ValidationError):
        validate_bom(broken, strict=True)


def test_wrong_spec_version_fails(bom: dict) -> None:
    broken = copy.deepcopy(bom)
    broken["specVersion"] = "1.5"
    with pytest.raises(ValidationError):
        validate_bom(broken)


def test_bad_bom_ref_fails(bom: dict) -> None:
    broken = copy.deepcopy(bom)
    broken["components"][0]["bom-ref"] = 12345  # must be a string
    with pytest.raises(ValidationError):
        validate_bom(broken)


def test_validate_digest_reports_mismatch(bom: dict, tmp_path: Path) -> None:
    path = tmp_path / "aibom.cdx.json"
    path.write_text(json.dumps(bom), encoding="utf-8")
    (tmp_path / "aibom.cdx.json.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    ok, _expected, _actual = verify_digest(path, bom)
    assert ok is False


def test_inventory_summary_is_complete(bom: dict) -> None:
    """F-OUT-2: every AI surface kind is represented in the fixture BOM."""
    kinds = {
        "model": lambda c: c["type"] == "machine-learning-model",
        "prompt": lambda c: c["type"] == "data" and any(
            d.get("classification") == "prompt" for d in c.get("data", [])
        ),
        "dataset": lambda c: c["type"] == "data" and not any(
            d.get("classification") == "prompt" for d in c.get("data", [])
        ),
        "tool": lambda c: c["type"] == "library" and not any(
            p["name"] == "aibom:role" and p["value"] == "ai-sdk" for p in c.get("properties", [])
        ),
        "ai-sdk": lambda c: any(
            p["name"] == "aibom:role" and p["value"] == "ai-sdk" for p in c.get("properties", [])
        ),
    }
    for kind, predicate in kinds.items():
        assert any(predicate(c) for c in bom["components"]), f"no {kind} component in the BOM"
    assert bom.get("services"), "expected provider/MCP services"
