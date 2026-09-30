"""Keyless signing and verification (spec F-SIGN-1, F-SIGN-2).

Signing is strictly opt-in and strictly local: `aibom attest` shells out to
`cosign sign-blob` (or uses `sigstore-python` when installed) and the only thing
that leaves the machine is the signature entry in the public sigstore
transparency log — which the user asked for by running `attest`. Every other
command, including `verify`, is offline unless it needs the log to fetch the
signer's certificate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aibom.digest import read_digest, verify_digest, write_digest
from aibom.errors import MissingDependencyError, VerifyError

#: The CycloneDX BOM predicate type, per the CycloneDX attestation guidance.
DEFAULT_PREDICATE_TYPE = "https://cyclonedx.org/bom"

BUNDLE_SUFFIX = ".sigstore.json"
SIG_SUFFIX = ".sig"

GH_ATTESTATION_GUIDANCE = """\
GitHub-native alternative (no cosign install, uses the workflow's OIDC token):

    permissions:
      id-token: write
      attestations: write
      contents: read

    - run: aibom generate -o aibom.cdx.json
    - uses: actions/attest-build-provenance@v2
      with:
        subject-path: aibom.cdx.json

Verify it later with:

    gh attestation verify aibom.cdx.json --owner <org>
"""


@dataclass(slots=True)
class SignResult:
    path: Path
    method: str
    bundle: Path | None = None
    signature: Path | None = None
    digest: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "method": self.method,
            "bundle": str(self.bundle) if self.bundle else None,
            "signature": str(self.signature) if self.signature else None,
            "digest": self.digest,
            "detail": self.detail,
        }


@dataclass(slots=True)
class VerifyResult:
    ok: bool
    method: str
    digest_ok: bool
    signature_ok: bool | None
    identity: str | None = None
    issuer: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "method": self.method,
            "digest_ok": self.digest_ok,
            "signature_ok": self.signature_ok,
            "identity": self.identity,
            "issuer": self.issuer,
            "detail": self.detail,
        }


def cosign_path() -> str | None:
    return shutil.which("cosign")


def sigstore_available() -> bool:
    try:
        import sigstore  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


# --- attest -------------------------------------------------------------------


def attest(
    bom_path: Path,
    *,
    predicate_type: str = DEFAULT_PREDICATE_TYPE,
    identity_token: str | None = None,
    offline: bool = False,
) -> SignResult:
    """Sign ``bom_path``'s content digest, keyless, via cosign or sigstore-python."""
    if not bom_path.exists():
        raise VerifyError(f"cannot sign missing file: {bom_path}")

    digest = read_digest(bom_path)
    if digest is None:
        write_digest(json.loads(bom_path.read_text(encoding="utf-8")), bom_path)
        digest = read_digest(bom_path) or ""

    bundle = bom_path.with_name(bom_path.name + BUNDLE_SUFFIX)
    cosign = cosign_path()
    if cosign:
        cmd = [
            cosign,
            "sign-blob",
            "--yes",
            "--bundle",
            str(bundle),
            str(bom_path),
        ]
        if offline:
            cmd.append("--offline")
        if identity_token:
            cmd += ["--identity-token", identity_token]
        proc = _run(cmd)
        if proc.returncode != 0:
            raise VerifyError(
                "cosign sign-blob failed",
                hint=(proc.stderr or proc.stdout or "").strip()[:500],
            )
        return SignResult(
            path=bom_path,
            method="cosign",
            bundle=bundle,
            digest=digest,
            detail=f"predicate-type {predicate_type}",
        )

    if sigstore_available():
        from sigstore.oidc import Issuer  # type: ignore
        from sigstore.sign import SigningContext  # type: ignore

        issuer = Issuer.production()
        token = issuer.identity_token(force_oob=offline)
        ctx = SigningContext.production()
        with ctx.signer(token) as signer:
            result = signer.sign_artifact(bom_path)
        bundle_path = bom_path.with_name(bom_path.name + BUNDLE_SUFFIX)
        bundle_path.write_text(result.to_json(), encoding="utf-8")
        return SignResult(
            path=bom_path,
            method="sigstore-python",
            bundle=bundle_path,
            digest=digest,
            detail=f"predicate-type {predicate_type}",
        )

    raise MissingDependencyError(
        "no signing backend available",
        hint=(
            "Install cosign (https://docs.sigstore.dev/cosign/installation/) or "
            "`pip install 'aibom[sign]'`.\n\n" + GH_ATTESTATION_GUIDANCE
        ),
    )


# --- verify -------------------------------------------------------------------


def verify(
    bom_path: Path,
    *,
    identity: str | None = None,
    issuer: str | None = None,
    require_signature: bool = False,
) -> VerifyResult:
    """Verify a BOM: signature when present, digest always.

    The digest check is the fallback that works with no tooling at all: if the
    `.sha256` sidecar matches, the document is byte-for-byte the one that was
    generated. That is weaker than a signature and the result says so.
    """
    try:
        bom = json.loads(bom_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VerifyError(f"cannot read {bom_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VerifyError(f"{bom_path} is not valid JSON: {exc}") from exc

    digest_ok, expected, actual = verify_digest(bom_path, bom)

    bundle = bom_path.with_name(bom_path.name + BUNDLE_SUFFIX)
    signature_ok: bool | None = None
    method = "digest"

    if bundle.exists() and cosign_path():
        cmd = [cosign_path() or "cosign", "verify-blob", "--bundle", str(bundle)]
        if identity:
            cmd += ["--certificate-identity", identity]
        if issuer:
            cmd += ["--certificate-oidc-issuer", issuer]
        cmd.append(str(bom_path))
        proc = _run(cmd)
        signature_ok = proc.returncode == 0
        method = "cosign"
        if not signature_ok:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            return VerifyResult(
                ok=False,
                method=method,
                digest_ok=digest_ok,
                signature_ok=False,
                identity=identity,
                issuer=issuer,
                detail=detail,
            )
    elif require_signature:
        raise MissingDependencyError(
            "a signature was required but no verifiable bundle was found",
            hint=(
                f"expected {bundle} and a `cosign` binary.\n\n" + GH_ATTESTATION_GUIDANCE
            ),
        )

    if not digest_ok and signature_ok is not True:
        detail = (
            f"content digest mismatch: sidecar {expected[:12] or '(absent)'} != computed {actual[:12]}"
        )
        return VerifyResult(
            ok=False,
            method=method,
            digest_ok=False,
            signature_ok=signature_ok,
            identity=identity,
            issuer=issuer,
            detail=detail,
        )

    detail = "signature valid" if signature_ok else "digest matches; no signature present"
    if signature_ok is None and not digest_ok:
        detail = "no signature and no digest sidecar; nothing to verify"
    return VerifyResult(
        ok=digest_ok or signature_ok is True,
        method=method,
        digest_ok=digest_ok,
        signature_ok=signature_ok,
        identity=identity,
        issuer=issuer,
        detail=detail,
    )
