"""Dataclasses for the parts of an AI BOM (spec §8, F-OUT-2).

These types sit between the scanner/manifest and the CycloneDX emitter. Keeping
them explicit (rather than building JSON directly) means the same model feeds
JSON, XML, Markdown, HTML, diff and digest — so those views can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aibom import RULES_VERSION

# --- property helpers ---------------------------------------------------------


def prop(name: str, value: Any) -> dict[str, str] | None:
    """A CycloneDX property. Empty values are dropped, not emitted as blanks."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"name": name, "value": "true" if value else "false"}
    if isinstance(value, (list, tuple, set)):
        values = [str(v) for v in value if str(v).strip()]
        if not values:
            return None
        return {"name": name, "value": ", ".join(values)}
    text = str(value).strip()
    if not text:
        return None
    return {"name": name, "value": text}


def props(*items: tuple[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name, value in items:
        p = prop(name, value)
        if p is not None:
            out.append(p)
    return out


def hash_sha256(content: str) -> dict[str, str]:
    return {"alg": "SHA-256", "content": content}


# --- shared value objects -----------------------------------------------------


@dataclass(slots=True)
class Location:
    path: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line}

    def display(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass(slots=True)
class Contact:
    name: str
    email: str | None = None
    role: str | None = None


@dataclass(slots=True)
class EvalReference:
    name: str
    url: str | None = None
    score: str | None = None
    date: str | None = None
    notes: str | None = None


# --- components ---------------------------------------------------------------


@dataclass(slots=True)
class Model:
    alias: str
    snapshot: str
    version: str | None = None
    kind: str = "foundation"
    provider: str | None = None
    provider_docs: str | None = None
    resolved: bool = False
    floating: bool = True
    locations: list[Location] = field(default_factory=list)
    deprecation: str | None = None
    retirement: str | None = None
    price_in_per_1m: str | None = None
    price_out_per_1m: str | None = None
    context_window: int | None = None
    hosting_region: str | None = None
    data_processing_agreement: bool | None = None
    training_data_optout: bool | None = None
    purpose: str | None = None
    license: str | None = None
    task: str | None = None
    architecture_family: str | None = None
    use_cases: list[str] = field(default_factory=list)
    technical_limitations: list[str] = field(default_factory=list)
    ethical_considerations: list[dict[str, str]] = field(default_factory=list)
    evals: list[EvalReference] = field(default_factory=list)
    notes: str | None = None
    #: True when aibom inferred a link (e.g. a prompt used in the same file)
    #: rather than reading it from a declaration. Surfaced as `aibom:inferred`
    #: so an auditor can see which edges are guesses.
    inferred: bool = False

    @property
    def bom_ref(self) -> str:
        return f"model:{self.alias}"

    @property
    def display_name(self) -> str:
        return self.snapshot or self.alias


@dataclass(slots=True)
class Prompt:
    name: str
    path: str
    line: int | None
    sha256: str
    approx_tokens: int
    source: str = "file"
    owners: list[str] = field(default_factory=list)
    text: str | None = None
    variables: list[str] = field(default_factory=list)

    @property
    def bom_ref(self) -> str:
        return f"prompt:{self.path}:{self.line}:{self.name}"

    @property
    def version(self) -> str:
        return self.sha256[:12]


@dataclass(slots=True)
class Tool:
    name: str
    path: str | None = None
    line: int | None = None
    source: str = "code"
    description: str | None = None
    param_keys: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    risk: str = "unknown"
    human_in_the_loop: bool | None = None
    reversible: bool | None = None
    rate_limited: bool | None = None
    risk_override: bool = False
    justification: str | None = None
    matched_rules: list[str] = field(default_factory=list)
    heuristic_capabilities: list[str] = field(default_factory=list)
    heuristic_risk: str = "unknown"
    mcp_server: str | None = None
    sha256: str | None = None

    @property
    def bom_ref(self) -> str:
        return f"tool:{self.name}"

    @property
    def location(self) -> Location | None:
        if self.path is None:
            return None
        return Location(self.path, self.line)


@dataclass(slots=True)
class McpServer:
    name: str
    transport: str = "unknown"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env_keys: list[str] = field(default_factory=list)
    config: str | None = None
    line: int | None = None
    package: str | None = None
    url: str | None = None
    version: str | None = None
    version_pinned: bool = False
    sha256: str | None = None
    authenticated: bool | None = None
    capabilities: list[str] = field(default_factory=list)
    risk: str = "unknown"
    human_in_the_loop: bool | None = None
    reversible: bool | None = None
    rate_limited: bool | None = None
    risk_override: bool = False
    justification: str | None = None
    matched_rules: list[str] = field(default_factory=list)
    heuristic_capabilities: list[str] = field(default_factory=list)
    heuristic_risk: str = "unknown"
    locations: list[Location] = field(default_factory=list)

    @property
    def bom_ref(self) -> str:
        return f"mcp:{self.name}"

    @property
    def crosses_trust_boundary(self) -> bool:
        return self.transport in {"http", "sse", "websocket"}

    @property
    def endpoints(self) -> list[str]:
        if self.url:
            return [self.url]
        if self.transport in {"http", "sse"}:
            return []
        return []


@dataclass(slots=True)
class Provider:
    name: str
    locations: list[Location] = field(default_factory=list)
    region: str | None = None
    dpa: bool | None = None
    data_classification: str | None = None
    endpoint: str | None = None
    purpose: str | None = None
    models: list[str] = field(default_factory=list)

    @property
    def bom_ref(self) -> str:
        return f"provider:{self.name}"


@dataclass(slots=True)
class Dataset:
    name: str
    version: str | None = None
    classification: str | None = None
    sensitive_data: list[str] = field(default_factory=list)
    pii: bool = False
    consent_basis: str | None = None
    retention: str | None = None
    jurisdiction: str | None = None
    owners: list[str] = field(default_factory=list)
    custodians: list[str] = field(default_factory=list)
    source: str | None = None
    refresh: str | None = None
    description: str | None = None
    kind: str = "dataset"  # "dataset" | "retrieval"

    @property
    def bom_ref(self) -> str:
        prefix = "retrieval" if self.kind == "retrieval" else "dataset"
        return f"{prefix}:{self.name}"


@dataclass(slots=True)
class ExternalService:
    name: str
    provider: str | None = None
    purpose: str | None = None
    endpoint: str | None = None
    data_shared: list[str] = field(default_factory=list)
    classification: str | None = None
    dpa: bool | None = None
    region: str | None = None
    authenticated: bool | None = None
    description: str | None = None

    @property
    def bom_ref(self) -> str:
        return f"external:{self.name}"


@dataclass(slots=True)
class AiSdkLibrary:
    name: str
    version: str | None
    ecosystem: str
    provider: str | None
    purl: str

    @property
    def bom_ref(self) -> str:
        return f"ai-sdk:{self.ecosystem}:{self.name}"


@dataclass(slots=True)
class Dependency:
    ref: str
    depends_on: list[str] = field(default_factory=list)
    inferred: bool = False


@dataclass(slots=True)
class Composition:
    aggregate: str
    assemblies: list[str] = field(default_factory=list)
    note: str | None = None
    kind: str | None = None


@dataclass(slots=True)
class ReviewNote:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    subject: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(slots=True)
class AiBom:
    """The complete in-memory model of one AI BOM."""

    # application
    app_name: str
    app_version: str | None = None
    app_description: str | None = None
    app_purpose: str | None = None
    deployment: str | None = None
    data_classification: str | None = None
    jurisdictions: list[str] = field(default_factory=list)
    risk_classification: dict[str, str] | None = None
    human_oversight: str | None = None
    owner: str | None = None
    contacts: list[Contact] = field(default_factory=list)
    app_bom_ref: str = "app:system"

    # inventory
    models: list[Model] = field(default_factory=list)
    prompts: list[Prompt] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)
    providers: list[Provider] = field(default_factory=list)
    datasets: list[Dataset] = field(default_factory=list)
    external_services: list[ExternalService] = field(default_factory=list)
    ai_sdks: list[AiSdkLibrary] = field(default_factory=list)
    merged_components: list[dict[str, Any]] = field(default_factory=list)

    # graph + provenance
    dependencies: list[Dependency] = field(default_factory=list)
    compositions: list[Composition] = field(default_factory=list)
    review_notes: list[ReviewNote] = field(default_factory=list)

    # provenance recorded in the BOM footer / properties
    generated_at: str = ""
    tool_version: str = ""
    tool_name: str = "aibom"
    rules_version: str = RULES_VERSION
    git: dict[str, Any] = field(default_factory=dict)
    lock_path: str | None = None
    lock_generated: bool = False
    lock_fresh: bool = False
    lock_note: str | None = None
    manifest_path: str | None = None
    #: `system.complete` from the manifest; only a true value lets a declared
    #: kind be reported as `complete` rather than `unknown` (F-OUT-4).
    manifest_complete: dict[str, bool] = field(default_factory=dict)
    scanner: str = "bundled"
    source_root: str = "."
    spec_version: str = "1.6"

    # --- convenience ----------------------------------------------------------

    @property
    def all_refs(self) -> list[str]:
        refs = [self.app_bom_ref]
        refs += [m.bom_ref for m in self.models]
        refs += [p.bom_ref for p in self.prompts]
        refs += [t.bom_ref for t in self.tools]
        refs += [s.bom_ref for s in self.mcp_servers]
        refs += [p.bom_ref for p in self.providers]
        refs += [d.bom_ref for d in self.datasets]
        refs += [e.bom_ref for e in self.external_services]
        refs += [sdk.bom_ref for sdk in self.ai_sdks]
        return refs

    def counts(self) -> dict[str, int]:
        return {
            "models": len(self.models),
            "prompts": len(self.prompts),
            "tools": len(self.tools),
            "mcp_servers": len(self.mcp_servers),
            "providers": len(self.providers),
            "datasets": len(self.datasets),
            "external_services": len(self.external_services),
            "ai_sdks": len(self.ai_sdks),
        }

    def summary_line(self) -> str:
        c = self.counts()
        parts = [
            f"{c['models']} model(s)",
            f"{c['prompts']} prompt(s)",
            f"{c['tools']} tool(s)",
            f"{c['mcp_servers']} MCP server(s)",
            f"{c['providers']} provider(s)",
            f"{c['datasets']} dataset(s)",
            f"{c['external_services']} external service(s)",
            f"{c['ai_sdks']} AI SDK(s)",
        ]
        return " · ".join(parts)

    def notes_at(self, level: str) -> list[ReviewNote]:
        return [n for n in self.review_notes if n.level == level]
