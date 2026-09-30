"""Dependency-Track upload helpers (spec §6.7, §10).

Security teams already run Dependency-Track; the value of an AI BOM is that it
lands in the same project as the SBOM. This module builds the multipart request
and (optionally) performs it — the docs use `curl`, this is the same call from
Python for the GitHub Action.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

CURL_SNIPPET = """\
# Upload the AI BOM to Dependency-Track (same project as your SBOM).
curl -X POST "$DT_URL/api/v1/bom" \\
  -H "X-Api-Key: $DT_API_KEY" \\
  -H "Content-Type: multipart/form-data" \\
  -F "autoCreate=true" \\
  -F "projectName=$PROJECT_NAME" \\
  -F "projectVersion=$PROJECT_VERSION" \\
  -F "bom=@aibom.cdx.json"

# Or attach it to an existing project by UUID:
#   -F "project=$PROJECT_UUID"
"""


@dataclass(slots=True)
class UploadResult:
    ok: bool
    status: int
    token: str | None = None
    detail: str = ""


def build_multipart(
    bom: Path,
    *,
    project_name: str | None = None,
    project_version: str | None = None,
    project_uuid: str | None = None,
    auto_create: bool = True,
) -> tuple[bytes, str]:
    boundary = f"----aibom{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    if auto_create:
        field("autoCreate", "true")
    if project_uuid:
        field("project", project_uuid)
    if project_name:
        field("projectName", project_name)
    if project_version:
        field("projectVersion", project_version)

    payload = bom.read_bytes()
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="bom"; filename="{bom.name}"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload(
    bom: Path,
    *,
    base_url: str,
    api_key: str,
    project_name: str | None = None,
    project_version: str | None = None,
    project_uuid: str | None = None,
    timeout: float = 30.0,
) -> UploadResult:
    """POST the BOM to Dependency-Track. Returns a result, never raises on HTTP error."""
    body, content_type = build_multipart(
        bom,
        project_name=project_name,
        project_version=project_version,
        project_uuid=project_uuid,
    )
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/bom",
        data=body,
        method="POST",
        headers={"X-Api-Key": api_key, "Content-Type": content_type, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            token = None
            with contextlib.suppress(json.JSONDecodeError):
                token = json.loads(payload).get("token")
            return UploadResult(ok=True, status=response.status, token=token, detail=payload[:500])
    except urllib.error.HTTPError as exc:
        return UploadResult(
            ok=False,
            status=exc.code,
            detail=exc.read().decode("utf-8", errors="replace")[:500],
        )
    except urllib.error.URLError as exc:
        return UploadResult(ok=False, status=0, detail=str(exc.reason))
