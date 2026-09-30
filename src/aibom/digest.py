"""Stable content digest and `.sha256` sidecar (spec F-OUT-6).

The digest is the anchor for everything downstream: `diff` needs a cheap way to
say "nothing changed", `validate` needs to prove the BOM it read is the BOM that
was written, and a signature over a digest is far more usable than a signature
over a pretty-printed document.

The digest deliberately excludes `serialNumber`, `metadata.timestamp` and
`version`: those change on every run and carry no meaning about the AI surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aibom.errors import ValidationError
from aibom.util import bom_digest, sha256_text

DIGEST_SUFFIX = ".sha256"

#: Fields removed before hashing, and why:
VOLATILE_FIELDS = ("serialNumber", "version", "metadata.timestamp")


@dataclass(slots=True)
class DigestRecord:
    digest: str
    path: Path

    def write(self) -> Path:
        target = self.path.with_name(self.path.name + DIGEST_SUFFIX)
        target.write_text(f"{self.digest}  {self.path.name}\n", encoding="utf-8")
        return target


def digest_of(bom: dict[str, Any]) -> str:
    return bom_digest(bom)


def write_digest(bom: dict[str, Any], bom_path: Path) -> Path:
    return DigestRecord(digest=digest_of(bom), path=bom_path).write()


def read_digest(bom_path: Path) -> str | None:
    sidecar = bom_path.with_name(bom_path.name + DIGEST_SUFFIX)
    if not sidecar.exists():
        return None
    text = sidecar.read_text(encoding="utf-8").strip()
    if not text:
        return None
    # `sha256sum` format: "<digest>  <filename>"
    return text.split()[0]


def verify_digest(bom_path: Path, bom: dict[str, Any] | None = None) -> tuple[bool, str, str]:
    """Return ``(ok, expected, actual)``. ``expected`` is empty when absent."""
    expected = read_digest(bom_path)
    if bom is None:
        try:
            bom = json.loads(bom_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"cannot read {bom_path}: {exc}") from exc
    actual = digest_of(bom)
    if expected is None:
        return False, "", actual
    return expected == actual, expected, actual


def short(digest: str, length: int = 12) -> str:
    return digest[:length]


def digest_footer(bom: dict[str, Any]) -> str:
    """The provenance line that goes at the bottom of human renderings."""
    return f"sha256:{short(digest_of(bom))}"


def text_digest(text: str) -> str:
    return sha256_text(text)
