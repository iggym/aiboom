"""Load, validate and normalise `aibom.yaml` (spec §7.1, F-IN-2).

Validation errors are reported with ``file:line:col`` where the line comes from
the annotated YAML loader and the column from jsonschema's own error path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

from aibom.errors import ManifestError
from aibom.util import (
    line_of,
    load_yaml_with_lines,
    strip_line_markers,
    walk_dicts,
)

MANIFEST_FILENAMES = ("aibom.yaml", "aibom.yml", ".aibom.yaml")

EXAMPLE_MANIFEST = """\
# aibom.yaml — declarations that cannot be inferred from source.
# Everything inferable is inferred; everything else is declared here once.
# Reference: https://github.com/modelsurface/aibom/blob/main/docs/manifest.md
schema: 1

system:
  name: support-agent
  version: git            # explicit "1.4.0", or "git" to derive from tag/commit
  description: Customer support assistant that drafts and sends replies.
  owner: platform-ai@example.com
  contacts:
    - {name: Ada Lovelace, email: ada@example.com, role: accountable}
    - {name: Grace Hopper, email: grace@example.com, role: responsible}
  purpose: Draft replies to inbound support tickets and summarise threads.
  deployment: customer-facing
  risk_classification:
    framework: EU AI Act
    label: limited
    rationale: Interacts with end users; no safety component, no biometrics.
  human_oversight: Agents approve every outbound reply before sending.
  data_classification: customer-pii
  jurisdictions: [US, EU]
  complete:
    datasets: true
    external_services: true

models:
  gpt-4.1:
    purpose: Drafting replies and summarising ticket threads.
    kind: foundation
    task: text-generation
    architecture_family: transformer
    use_cases: [Support reply drafting, Thread summarisation]
    technical_limitations: [May hallucinate policy details; verify against docs]
    ethical_considerations:
      - {name: Bias in tone across locales, mitigation_strategy: Locale-specific review}
    provider: openai
    provider_docs: https://platform.openai.com/docs/models/gpt-4.1
    hosting_region: us
    data_processing_agreement: true
    training_data_optout: true
    license: proprietary
    context_window: 1047576
    price_in_per_1m: 2.00
    price_out_per_1m: 8.00
    evals:
      - {name: Support Reply Quality, url: https://evals.example.com/reply-q, score: 0.91}

tools:
  issue_refund:
    risk: high
    human_in_the_loop: true
    reversible: false
    rate_limited: true
    justification: Money movement; requires an approver and is capped per day.

mcp_servers:
  crm:
    risk: medium
    justification: Read-only token scoped to the support account.

datasets:
  - name: ticket-history
    version: rolling
    classification: confidential
    sensitive_data: [email, name, order_id]
    pii: true
    consent_basis: contract
    retention: 24 months
    jurisdiction: US
    owners: [support-platform]
    source: https://warehouse.example.com/tables/tickets
    refresh: daily

retrieval_sources:
  - name: help-center-index
    kind: vector-store
    classification: public
    pii: false
    refresh: on-commit
    description: Embedded help-centre articles used for retrieval augmentation.

external_services:
  - name: Eleven Labs TTS
    provider: elevenlabs
    purpose: voice
    data_shared: [transcripts]
    dpa: true
"""


@dataclass(slots=True)
class Manifest:
    """Validated, normalised view of `aibom.yaml`."""

    path: Path | None
    raw: dict[str, Any] = field(default_factory=dict)

    # --- accessors ------------------------------------------------------------
    @property
    def system(self) -> dict[str, Any]:
        return self.raw.get("system", {})

    @property
    def models(self) -> dict[str, Any]:
        return self.raw.get("models", {})

    @property
    def tools(self) -> dict[str, Any]:
        return self.raw.get("tools", {})

    @property
    def mcp_servers(self) -> dict[str, Any]:
        return self.raw.get("mcp_servers", {})

    @property
    def datasets(self) -> list[dict[str, Any]]:
        return self.raw.get("datasets", [])

    @property
    def retrieval_sources(self) -> list[dict[str, Any]]:
        return self.raw.get("retrieval_sources", [])

    @property
    def external_services(self) -> list[dict[str, Any]]:
        return self.raw.get("external_services", [])

    @property
    def complete(self) -> dict[str, bool]:
        return self.system.get("complete", {}) or {}

    def declared_kinds(self) -> set[str]:
        """Kinds whose inventory comes from the manifest rather than the scan."""
        kinds: set[str] = set()
        if self.datasets:
            kinds.add("dataset")
        if self.retrieval_sources:
            kinds.add("retrieval")
        if self.external_services:
            kinds.add("external-service")
        return kinds

    def model(self, alias: str) -> dict[str, Any]:
        """Facts for a model alias, tolerant of case and `provider/alias` forms."""
        models = self.models
        if alias in models:
            return models[alias]
        lowered = alias.lower()
        for key, value in models.items():
            if key.lower() == lowered:
                return value
            if key.lower().split("/")[-1] == lowered.split("/")[-1]:
                return value
        return {}

    def tool(self, name: str) -> dict[str, Any]:
        tools = self.tools
        if name in tools:
            return tools[name]
        for key, value in tools.items():
            if key.lower() == name.lower():
                return value
        return {}

    def mcp_server(self, name: str) -> dict[str, Any]:
        servers = self.mcp_servers
        if name in servers:
            return servers[name]
        for key, value in servers.items():
            if key.lower() == name.lower():
                return value
        return {}


def schema() -> dict[str, Any]:
    ref = resources.files("aibom.schemas").joinpath("aibom-1.schema.json")
    return json.loads(ref.read_text(encoding="utf-8"))


def discover_manifest(root: Path, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        if not explicit.exists():
            raise ManifestError(f"manifest not found: {explicit}")
        return explicit
    for name in MANIFEST_FILENAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _line_for_error(annotated: Any, error_path: list[Any]) -> int | None:
    """Map a jsonschema error path onto a line in the annotated YAML."""
    if not error_path:
        return None
    # Drop list indices: they have no line of their own, the parent mapping does.
    keys = [str(p) for p in error_path if isinstance(p, str)]
    if not keys:
        return None
    line = line_of(annotated, *keys)
    if line is not None:
        return line
    # Fall back to the nearest ancestor that is a mapping.
    for cut in range(len(keys) - 1, 0, -1):
        line = line_of(annotated, *keys[:cut])
        if line is not None:
            return line
    return None


def load_manifest(
    root: Path,
    explicit: Path | None = None,
    *,
    required: bool = False,
) -> Manifest:
    """Load and validate the manifest for ``root``.

    A missing manifest is not an error unless ``required`` is set: every fact a
    manifest can carry is optional, the tool degrades to pure inference and
    flags the gaps in review notes.
    """
    path = discover_manifest(root, explicit)
    if path is None:
        if required:
            raise ManifestError(
                f"no manifest found in {root}",
                hint="run `aibom init` to write an example aibom.yaml",
            )
        return Manifest(path=None, raw={"schema": 1, "system": {}})

    try:
        annotated = load_yaml_with_lines(path)
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", str(exc))
        mark = getattr(exc, "problem_mark", None)
        problems = []
        if mark is not None:
            problems.append((mark.line + 1, mark.column + 1, problem))
        raise ManifestError(f"{path} is not valid YAML", path=str(path), problems=problems) from exc

    if annotated is None:
        annotated = {}
    if not isinstance(annotated, dict):
        raise ManifestError(
            f"{path} must be a YAML mapping at the top level",
            path=str(path),
            problems=[(1, 1, f"got {type(annotated).__name__}")],
        )

    data = strip_line_markers(annotated)
    validator = Draft7Validator(schema())
    problems = []  # list[tuple[int | None, int | None, str]]
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path_parts = [str(p) for p in error.absolute_path]
        line = _line_for_error(annotated, list(error.absolute_path))
        where = "/".join(path_parts) if path_parts else "(root)"
        problems.append((line, None, f"{where}: {error.message}"))

    if problems:
        raise ManifestError(
            f"{path} does not match the aibom manifest schema",
            path=str(path),
            problems=problems,
            hint="run `aibom manifest validate` for the same report, or see docs/manifest.md",
        )

    _check_semantics(data, annotated, path, problems)
    if problems:
        raise ManifestError(
            f"{path} has semantically invalid entries",
            path=str(path),
            problems=problems,
        )

    return Manifest(path=path, raw=data)


def _check_semantics(
    data: dict[str, Any],
    annotated: dict[str, Any],
    path: Path,
    problems: list[tuple[int | None, int | None, str]],
) -> None:
    """Checks the JSON schema cannot express.

    The schema cannot see across sections, so cross-references and the
    "justify your override" rule live here.
    """
    for section in ("tools", "mcp_servers"):
        for name, override in (data.get(section) or {}).items():
            if not isinstance(override, dict):
                continue
            declares_something = any(
                k in override for k in ("risk", "capabilities", "human_in_the_loop", "reversible", "rate_limited")
            )
            if declares_something and not override.get("justification"):
                line = line_of(annotated, section, name)
                problems.append(
                    (
                        line,
                        None,
                        f"{section}/{name}: an override must carry a `justification` "
                        "so auditors can see the human decision next to the heuristic",
                    )
                )

    if data.get("schema") != 1:
        problems.append(
            (line_of(annotated, "schema"), None, "schema: only manifest schema 1 is supported")
        )

    for i, dataset in enumerate(data.get("datasets") or []):
        if not isinstance(dataset, dict):
            continue
        if dataset.get("pii") and not (dataset.get("consent_basis") and dataset.get("retention")):
            problems.append(
                (
                    line_of(annotated, "datasets"),
                    None,
                    f"datasets/{dataset.get('name', i)}: pii is true but "
                    "`consent_basis` and/or `retention` are missing",
                )
            )


def write_example_manifest(root: Path, *, force: bool = False) -> Path:
    target = root / "aibom.yaml"
    if target.exists() and not force:
        raise ManifestError(
            f"{target} already exists",
            hint="pass --force to overwrite",
        )
    target.write_text(EXAMPLE_MANIFEST, encoding="utf-8")
    return target


def manifest_summary(manifest: Manifest) -> dict[str, Any]:
    """Compact summary used by `doctor`, the CLI banner and the HTML header."""
    return {
        "path": str(manifest.path) if manifest.path else None,
        "system": manifest.system.get("name"),
        "version": manifest.system.get("version"),
        "models": len(manifest.models),
        "tools": len(manifest.tools),
        "mcp_servers": len(manifest.mcp_servers),
        "datasets": len(manifest.datasets),
        "retrieval_sources": len(manifest.retrieval_sources),
        "external_services": len(manifest.external_services),
    }


def all_lines(annotated: Any) -> list[int]:
    """Every recorded line number, for tests that assert coverage of the loader."""
    return [d["__line__"] for d in walk_dicts(annotated) if "__line__" in d]
