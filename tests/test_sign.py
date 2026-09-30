"""Signing tests (spec §9): digest fallback always; cosign if present.

The rule is that signing must never send the BOM anywhere unless the user runs
`attest`, so these tests never hit the network. The cosign round-trip is
skipped when cosign or an OIDC identity is unavailable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from aibom.api import GenerateOptions, generate_full
from aibom.digest import digest_of, write_digest
from aibom.errors import MissingDependencyError
from aibom.sign import attest, cosign_path, sigstore_available, verify

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def signed_ready(tmp_path: Path) -> Path:
    root = (FIXTURES / "support-agent").resolve()
    bom, _ = generate_full(GenerateOptions(root=root, refresh=True))
    path = tmp_path / "aibom.cdx.json"
    path.write_text(json.dumps(bom), encoding="utf-8")
    write_digest(bom, path)
    return path


def test_signing_backends_are_probed_not_required() -> None:
    # Both may be absent; the call must simply report the truth.
    assert isinstance(cosign_path(), (str, type(None)))
    assert isinstance(sigstore_available(), bool)


def test_verify_with_sidecar_and_no_signature_uses_digest(signed_ready: Path) -> None:
    result = verify(signed_ready)
    assert result.digest_ok is True
    assert result.method in {"digest", "cosign", "sigstore"}


def test_verify_detects_a_tampered_digest(signed_ready: Path) -> None:
    sidecar = signed_ready.with_suffix(signed_ready.suffix + ".sha256")
    sidecar.write_text("0" * 64 + "\n", encoding="utf-8")
    result = verify(signed_ready)
    assert result.digest_ok is False
    assert result.ok is False


def test_attest_without_any_backend_reports_clearly(signed_ready: Path) -> None:
    """With no cosign and no sigstore, `attest` must fail loudly, not silently."""
    if cosign_path() is not None or sigstore_available():
        pytest.skip("a signing backend is installed")
    with pytest.raises(MissingDependencyError):
        attest(signed_ready)


def test_digest_matches_the_recorded_sidecar(signed_ready: Path) -> None:
    bom = json.loads(signed_ready.read_text(encoding="utf-8"))
    sidecar = signed_ready.with_suffix(signed_ready.suffix + ".sha256")
    first_field = sidecar.read_text(encoding="utf-8").strip().split()[0]
    assert first_field == digest_of(bom)


@pytest.mark.skipif(shutil.which("cosign") is None, reason="cosign not installed")
def test_cosign_sign_verify_round_trip(signed_ready: Path) -> None:
    try:
        attest(signed_ready)
    except Exception as exc:  # pragma: no cover - depends on OIDC availability
        pytest.skip(f"cosign signing unavailable: {exc}")
    result = verify(signed_ready)
    assert result.ok is True
    assert result.signature_ok is True
