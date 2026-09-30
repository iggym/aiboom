"""Review-notes engine (spec F-RISK-4).

These are the lines a human actually reads: the flags that turn a BOM from an
inventory into a to-do list. Every note has a stable `code` so CI can gate on
specific ones, and every note names its subject so `aibom diff` can show when
one is resolved.

Levels:
  error   — the BOM is missing something an auditor will ask for; `--strict` fails.
  warning — a risk posture worth a human decision.
  info    — context that helps a reviewer.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from aibom.model.components import AiBom, ReviewNote

_CODE_ORDER = {
    "model.floating": 10,
    "model.retired": 20,
    "model.retiring": 30,
    "model.no_purpose": 40,
    "model.no_evals": 50,
    "tool.high_risk_no_hitl": 60,
    "tool.irreversible_no_hitl": 70,
    "mcp.insecure_transport": 80,
    "mcp.unpinned_package": 90,
    "mcp.risk_override": 100,
    "tool.risk_override": 110,
    "prompt.no_owner": 120,
    "prompt.no_owner_manifest": 125,
    "dataset.pii_no_consent": 130,
    "dataset.pii_no_retention": 140,
    "dataset.no_owner": 150,
    "system.no_owner": 160,
    "system.no_purpose": 170,
    "system.no_risk_classification": 180,
    "system.no_human_oversight": 190,
    "provider.no_dpa": 200,
    "external.no_dpa": 210,
    "lock.stale": 220,
    "manifest.absent": 230,
    "ai_sdk.unpinned": 240,
    "tool.unknown_risk": 250,
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PINNED_VERSION = re.compile(r"^\d+\.\d+\.\d+")


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if _ISO_DATE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
    if re.match(r"^\d{8}$", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def build_review_notes(bom: AiBom, *, today: date | None = None) -> list[ReviewNote]:
    today = today or date.today()
    notes: list[ReviewNote] = []

    # --- system ---------------------------------------------------------------
    if not bom.owner:
        notes.append(
            ReviewNote(
                "error",
                "system.no_owner",
                "The system has no accountable owner.",
                subject=bom.app_name,
                detail="Set `system.owner` in aibom.yaml — every audit asks who is accountable.",
            )
        )
    if not bom.app_purpose:
        notes.append(
            ReviewNote(
                "error",
                "system.no_purpose",
                "The system has no stated purpose.",
                subject=bom.app_name,
                detail="Set `system.purpose`; EU AI Act technical documentation expects intended purpose.",
            )
        )
    if not bom.risk_classification:
        notes.append(
            ReviewNote(
                "warning",
                "system.no_risk_classification",
                "No risk classification recorded.",
                subject=bom.app_name,
                detail="Set `system.risk_classification` (any framework; free-text is fine).",
            )
        )
    if not bom.human_oversight:
        notes.append(
            ReviewNote(
                "warning",
                "system.no_human_oversight",
                "No human-oversight description recorded.",
                subject=bom.app_name,
                detail="Set `system.human_oversight` to describe who reviews what.",
            )
        )

    # --- models ---------------------------------------------------------------
    for model in bom.models:
        if model.floating:
            notes.append(
                ReviewNote(
                    "warning",
                    "model.floating",
                    f"Model alias `{model.alias}` is not pinned to a dated snapshot.",
                    subject=model.alias,
                    detail=(
                        "A floating alias changes under you without a repo change, so the BOM "
                        "cannot be reproduced. Pin the dated snapshot."
                    ),
                )
            )
        retirement = _as_date(model.retirement)
        if retirement is not None:
            if retirement <= today:
                notes.append(
                    ReviewNote(
                        "error",
                        "model.retired",
                        f"Model `{model.alias}` retired on {retirement.isoformat()}.",
                        subject=model.alias,
                        detail="The BOM records a model that is no longer available.",
                    )
                )
            elif (retirement - today).days <= 90:
                notes.append(
                    ReviewNote(
                        "warning",
                        "model.retiring",
                        f"Model `{model.alias}` retires on {retirement.isoformat()}.",
                        subject=model.alias,
                        detail=f"{(retirement - today).days} days away; plan the migration.",
                    )
                )
        if not model.purpose:
            notes.append(
                ReviewNote(
                    "error",
                    "model.no_purpose",
                    f"Model `{model.alias}` has no declared purpose.",
                    subject=model.alias,
                    detail="Add a `models.<alias>.purpose` entry in aibom.yaml.",
                )
            )
        if not model.evals and model.kind not in {"embedding", "reranker"}:
            notes.append(
                ReviewNote(
                    "info",
                    "model.no_evals",
                    f"Model `{model.alias}` has no evaluation reference.",
                    subject=model.alias,
                    detail="Add `models.<alias>.evals` so the model card reports performance.",
                )
            )

    # --- tools ----------------------------------------------------------------
    for tool in bom.tools:
        if tool.risk == "high" and not tool.human_in_the_loop:
            notes.append(
                ReviewNote(
                    "error",
                    "tool.high_risk_no_hitl",
                    f"High-risk tool `{tool.name}` has no human in the loop.",
                    subject=tool.name,
                    detail=(
                        f"Capabilities: {', '.join(tool.capabilities) or 'unknown'}. "
                        "Either add approval or set `human_in_the_loop: true` with a justification."
                    ),
                )
            )
        if tool.reversible is False and not tool.human_in_the_loop:
            notes.append(
                ReviewNote(
                    "warning",
                    "tool.irreversible_no_hitl",
                    f"Irreversible tool `{tool.name}` has no human in the loop.",
                    subject=tool.name,
                    detail="Declare `human_in_the_loop` or mark the tool reversible.",
                )
            )
        if tool.risk == "unknown":
            notes.append(
                ReviewNote(
                    "info",
                    "tool.unknown_risk",
                    f"Tool `{tool.name}` could not be classified.",
                    subject=tool.name,
                    detail="No rule matched; declare `tools.<name>.risk` and `capabilities` in aibom.yaml.",
                )
            )
        if tool.risk_override and not tool.justification:
            notes.append(
                ReviewNote(
                    "warning",
                    "tool.risk_override",
                    f"Tool `{tool.name}` overrides the heuristic risk with no justification.",
                    subject=tool.name,
                    detail="Add `tools.<name>.justification`; auditors compare the heuristic to the decision.",
                )
            )

    # --- MCP servers ----------------------------------------------------------
    for server in bom.mcp_servers:
        if server.transport in {"http", "sse", "websocket"}:
            scheme = (server.url or "").lower()
            if scheme.startswith("http://") or (not scheme and server.transport == "http"):
                notes.append(
                    ReviewNote(
                        "error",
                        "mcp.insecure_transport",
                        f"MCP server `{server.name}` uses unencrypted http.",
                        subject=server.name,
                        detail="Switch to https; MCP traffic carries prompts and tool results.",
                    )
                )
            elif server.authenticated is False:
                notes.append(
                    ReviewNote(
                        "warning",
                        "mcp.insecure_transport",
                        f"MCP server `{server.name}` is reachable without authentication.",
                        subject=server.name,
                        detail="Set `authenticated: true` in aibom.yaml once a token is required.",
                    )
                )
        if server.package and not server.version_pinned:
            notes.append(
                ReviewNote(
                    "warning",
                    "mcp.unpinned_package",
                    f"MCP server `{server.name}` uses unpinned package `{server.package}`.",
                    subject=server.name,
                    detail="Pin an exact version so the server cannot change under the BOM.",
                )
            )
        if server.risk_override and not server.justification:
            notes.append(
                ReviewNote(
                    "warning",
                    "mcp.risk_override",
                    f"MCP server `{server.name}` overrides the heuristic risk with no justification.",
                    subject=server.name,
                    detail="Add `mcp_servers.<name>.justification`.",
                )
            )

    # --- prompts --------------------------------------------------------------
    for prompt in bom.prompts:
        if not prompt.owners:
            notes.append(
                ReviewNote(
                    "warning",
                    "prompt.no_owner",
                    f"Prompt `{prompt.name}` has no owner.",
                    subject=prompt.path,
                    detail=(
                        "No CODEOWNERS rule matched. Add the path to CODEOWNERS, or set "
                        "`system.owner` as a fallback."
                    ),
                )
            )

    # --- datasets -------------------------------------------------------------
    for dataset in bom.datasets:
        if dataset.pii and not dataset.consent_basis:
            notes.append(
                ReviewNote(
                    "error",
                    "dataset.pii_no_consent",
                    f"Dataset `{dataset.name}` holds PII with no consent basis.",
                    subject=dataset.name,
                    detail="Set `consent_basis` in aibom.yaml.",
                )
            )
        if dataset.pii and not dataset.retention:
            notes.append(
                ReviewNote(
                    "error",
                    "dataset.pii_no_retention",
                    f"Dataset `{dataset.name}` holds PII with no retention period.",
                    subject=dataset.name,
                    detail="Set `retention`; auditors ask how long PII is kept.",
                )
            )
        if not dataset.owners:
            notes.append(
                ReviewNote(
                    "info",
                    "dataset.no_owner",
                    f"Dataset `{dataset.name}` has no owner.",
                    subject=dataset.name,
                    detail="Set `owners` so governance questions have a name attached.",
                )
            )

    # --- providers & external services ---------------------------------------
    for provider in bom.providers:
        if provider.dpa is not True:
            notes.append(
                ReviewNote(
                    "warning",
                    "provider.no_dpa",
                    f"Provider `{provider.name}` has no recorded data-processing agreement.",
                    subject=provider.name,
                    detail="Set `data_processing_agreement: true` under `models` once the DPA is signed.",
                )
            )
    for service in bom.external_services:
        if service.dpa is not True:
            notes.append(
                ReviewNote(
                    "warning",
                    "external.no_dpa",
                    f"External service `{service.name}` has no recorded DPA.",
                    subject=service.name,
                    detail="Set `dpa: true` under `external_services`.",
                )
            )

    # --- provenance -----------------------------------------------------------
    if not bom.manifest_path:
        notes.append(
            ReviewNote(
                "warning",
                "manifest.absent",
                "No aibom.yaml found; the BOM is inference-only.",
                subject=None,
                detail="Run `aibom init` to declare purposes, owners, DPAs and risk classifications.",
            )
        )
    if bom.lock_path and not bom.lock_fresh:
        notes.append(
            ReviewNote(
                "warning",
                "lock.stale",
                "surface.lock is stale; scanned kinds are marked `incomplete`.",
                subject=bom.lock_path,
                detail=bom.lock_note or "Run `aibom generate --refresh` and commit the new lock.",
            )
        )

    for sdk in bom.ai_sdks:
        if not sdk.version or not _PINNED_VERSION.match(sdk.version):
            notes.append(
                ReviewNote(
                    "info",
                    "ai_sdk.unpinned",
                    f"AI SDK `{sdk.name}` is not pinned to an exact version.",
                    subject=sdk.name,
                    detail=f"Version recorded: {sdk.version or 'unknown'}.",
                )
            )

    notes.sort(key=lambda n: (_CODE_ORDER.get(n.code, 500), n.subject or ""))
    return notes


def attach_review_notes(bom: AiBom, *, today: date | None = None) -> AiBom:
    bom.review_notes = build_review_notes(bom, today=today)
    return bom


def has_errors(notes: list[ReviewNote]) -> bool:
    return any(n.level == "error" for n in notes)


def summarise(notes: list[ReviewNote]) -> str:
    errors = sum(1 for n in notes if n.level == "error")
    warnings = sum(1 for n in notes if n.level == "warning")
    infos = sum(1 for n in notes if n.level == "info")
    return f"{errors} error(s), {warnings} warning(s), {infos} info"
