"""Mapping from `surface.lock` + manifest to the AI BOM model (spec F-OUT-2).

This module is the single place where a scanner fact or a manifest declaration
becomes a component. Keeping it separate from the emitter means the mapping
rules can be read, tested and argued with on their own — which is what an
auditor reviewing "why is this tool listed" needs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aibom import RULES_VERSION, __version__
from aibom.errors import AibomError
from aibom.inputs.codeowners import CodeOwners, owners_for
from aibom.inputs.git import GitInfo
from aibom.inputs.lock import SurfaceLock
from aibom.inputs.scanner import capability_hints
from aibom.manifest import Manifest
from aibom.model.components import (
    AiBom,
    AiSdkLibrary,
    Contact,
    Dataset,
    EvalReference,
    ExternalService,
    Location,
    McpServer,
    Model,
    Prompt,
    Provider,
    Tool,
)
from aibom.risk import apply_override, classify_mcp_server, classify_tool, load_rulebook
from aibom.util import snake_split

#: Known provider docs, so model components carry a real `externalReference`.
PROVIDER_DOCS = {
    "openai": "https://platform.openai.com/docs/models",
    "anthropic": "https://docs.anthropic.com/en/docs/about-claude/models",
    "google": "https://ai.google.dev/gemini-api/docs/models",
    "mistral": "https://docs.mistral.ai/getting-started/models/",
    "cohere": "https://docs.cohere.com/docs/models",
    "meta": "https://www.llama.com/docs/model-cards-and-prompt-formats/",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "alibaba": "https://help.aliyun.com/zh/model-studio/getting-started/models",
    "microsoft": "https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models",
    "voyageai": "https://docs.voyageai.com/docs/embeddings",
    "bedrock": "https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html",
    "stabilityai": "https://platform.stability.ai/docs/api-reference",
    "elevenlabs": "https://elevenlabs.io/docs/api-reference",
    "azure-openai": "https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models",
    "vertexai": "https://cloud.google.com/vertex-ai/generative-ai/docs/models",
    "huggingface": "https://huggingface.co/models",
    "litellm": "https://docs.litellm.ai/docs/providers",
    "langchain": "https://python.langchain.com/docs/integrations/chat/",
    "llama-index": "https://docs.llamaindex.ai/en/stable/",
    "vercel-ai": "https://sdk.vercel.ai/providers/ai-sdk-providers",
    "ollama": "https://ollama.com/library",
}

#: Providers whose hosted API aibom will always surface as a service.
HOSTED_PROVIDERS = {
    "openai", "anthropic", "google", "mistral", "cohere", "deepseek", "alibaba",
    "voyageai", "bedrock", "azure-openai", "vertexai", "elevenlabs", "deepgram",
    "stabilityai",
}

#: Managed MCP transports that imply a remote endpoint.
REMOTE_TRANSPORTS = {"http", "sse", "websocket"}


def _entry_locations(entry: dict[str, Any]) -> list[Location]:
    locations = entry.get("locations")
    out: list[Location] = []
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, dict) and loc.get("path"):
                out.append(Location(str(loc["path"]), loc.get("line")))
            elif isinstance(loc, str):
                out.append(Location(loc))
    if not out and entry.get("path"):
        out.append(Location(str(entry["path"]), entry.get("line")))
    return out


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


# --- models -------------------------------------------------------------------


def map_models(lock: SurfaceLock, manifest: Manifest) -> list[Model]:
    models: list[Model] = []
    for entry in lock.kind("models"):
        alias = _str(entry.get("alias") or entry.get("name")) or "unknown"
        snapshot = _str(entry.get("resolved") or entry.get("snapshot") or entry.get("name")) or alias
        declared = manifest.model(alias) or manifest.model(snapshot)
        provider = _str(entry.get("provider")) or _str(declared.get("provider"))

        model = Model(
            alias=alias,
            snapshot=snapshot,
            kind=_str(entry.get("kind")) or _str(declared.get("kind")) or "foundation",
            provider=provider,
            provider_docs=_str(declared.get("provider_docs")) or PROVIDER_DOCS.get(provider or ""),
            resolved=bool(entry.get("resolved")) or snapshot != alias,
            floating=bool(entry.get("floating", snapshot == alias)),
            locations=_entry_locations(entry),
            deprecation=_str(declared.get("deprecation")),
            retirement=_str(declared.get("retirement")),
            context_window=declared.get("context_window"),
            hosting_region=_str(declared.get("hosting_region")),
            data_processing_agreement=_bool(declared.get("data_processing_agreement")),
            training_data_optout=_bool(declared.get("training_data_optout")),
            purpose=_str(declared.get("purpose")),
            license=_str(declared.get("license")),
            task=_str(declared.get("task")),
            architecture_family=_str(declared.get("architecture_family")),
            use_cases=[str(v) for v in declared.get("use_cases") or []],
            technical_limitations=[str(v) for v in declared.get("technical_limitations") or []],
            notes=_str(declared.get("notes")),
        )
        price_in = declared.get("price_in_per_1m")
        price_out = declared.get("price_out_per_1m")
        model.price_in_per_1m = None if price_in is None else str(price_in)
        model.price_out_per_1m = None if price_out is None else str(price_out)

        for item in declared.get("ethical_considerations") or []:
            if isinstance(item, str):
                model.ethical_considerations.append({"name": item})
            elif isinstance(item, dict) and item.get("name"):
                model.ethical_considerations.append(
                    {
                        "name": str(item["name"]),
                        "mitigationStrategy": _str(item.get("mitigation_strategy")) or "",
                    }
                )
        for ev in declared.get("evals") or []:
            if not isinstance(ev, dict) or not ev.get("name"):
                continue
            score = ev.get("score")
            model.evals.append(
                EvalReference(
                    name=str(ev["name"]),
                    url=_str(ev.get("url")),
                    score=None if score is None else str(score),
                    date=_str(ev.get("date")),
                    notes=_str(ev.get("notes")),
                )
            )
        models.append(model)

    models.sort(key=lambda m: (m.floating, m.alias.lower()))
    return models


# --- prompts ------------------------------------------------------------------


def map_prompts(
    lock: SurfaceLock,
    manifest: Manifest,
    codeowners: CodeOwners,
    *,
    lock_fresh: bool,
) -> list[Prompt]:
    fallback_owner = _str(manifest.system.get("owner"))
    prompts: list[Prompt] = []
    for entry in lock.kind("prompts"):
        path = _str(entry.get("path"))
        if not path:
            continue
        owners = owners_for(codeowners, path, fallback_owner)
        prompts.append(
            Prompt(
                name=_str(entry.get("name")) or Path(path).stem,
                path=path,
                line=entry.get("line"),
                sha256=_str(entry.get("text_sha256")) or "",
                approx_tokens=int(entry.get("approx_tokens") or 0),
                source=_str(entry.get("source")) or "file",
                owners=owners,
                text=_str(entry.get("text")) if not lock_fresh else None,
            )
        )
    return prompts


# --- tools --------------------------------------------------------------------


def map_tools(lock: SurfaceLock, manifest: Manifest) -> list[Tool]:
    book = load_rulebook()
    tools: list[Tool] = []
    for entry in lock.kind("tools"):
        name = _str(entry.get("name"))
        if not name:
            continue
        heuristic = classify_tool(
            name,
            description=_str(entry.get("description")),
            param_keys=[str(p) for p in entry.get("param_keys") or []],
            book=book,
        )
        # The scanner may already assert capabilities; treat them as a floor.
        declared_caps = [str(c) for c in entry.get("capabilities") or []]
        heuristic_caps = list(heuristic.capabilities)
        for capability in declared_caps:
            if capability not in heuristic_caps:
                heuristic_caps.append(capability)
        heuristic.capabilities = book.sort_capabilities(heuristic_caps)
        if declared_caps:
            heuristic.risk = book.risk_of(heuristic.capabilities)

        override = manifest.tool(name)
        result = apply_override(heuristic, override or None, book)

        mcp_server = _str(entry.get("mcp_server")) or _str(entry.get("source_mcp_server"))
        tool = Tool(
            name=name,
            path=_str(entry.get("path")),
            line=entry.get("line"),
            source=_str(entry.get("source")) or "code",
            description=_str(entry.get("description")),
            param_keys=[str(p) for p in entry.get("param_keys") or []],
            capabilities=result.capabilities,
            risk=result.risk,
            human_in_the_loop=result.human_in_the_loop
            if result.applied
            else _bool(entry.get("human_in_the_loop")),
            reversible=result.reversible if result.applied else _bool(entry.get("reversible")),
            rate_limited=result.rate_limited if result.applied else _bool(entry.get("rate_limited")),
            risk_override=result.applied,
            justification=result.justification,
            matched_rules=heuristic.rule_ids(),
            heuristic_capabilities=heuristic.capabilities,
            heuristic_risk=heuristic.risk,
            mcp_server=mcp_server,
            sha256=_str(entry.get("sha256")),
        )
        tools.append(tool)

    tools.sort(key=lambda t: (-_risk_rank(t.risk), t.name.lower()))
    return tools


def _risk_rank(risk: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(risk, 0)


# --- MCP servers --------------------------------------------------------------


def map_mcp_servers(lock: SurfaceLock, manifest: Manifest) -> list[McpServer]:
    book = load_rulebook()
    servers: list[McpServer] = []
    for entry in lock.kind("mcp_servers"):
        name = _str(entry.get("name"))
        if not name:
            continue
        package = _str(entry.get("package"))
        version = _str(entry.get("version"))
        transport = _str(entry.get("transport")) or "unknown"
        url = _str(entry.get("url"))
        args = [str(a) for a in entry.get("args") or []]

        heuristic = classify_mcp_server(
            name,
            package=package,
            command=_str(entry.get("command")),
            args=args,
            book=book,
        )
        declared_caps = [str(c) for c in entry.get("capabilities") or []]
        caps = list(heuristic.capabilities)
        for capability in declared_caps:
            if capability not in caps:
                caps.append(capability)
        heuristic.capabilities = book.sort_capabilities(caps)
        if declared_caps:
            heuristic.risk = book.risk_of(heuristic.capabilities)
        if not heuristic.capabilities:
            heuristic.capabilities = book.sort_capabilities(
                capability_hints(" ".join([name, package or "", *args]))
            )
            heuristic.risk = book.risk_of(heuristic.capabilities)

        override = manifest.mcp_server(name)
        result = apply_override(heuristic, override or None, book)

        pinned = bool(version and _looks_pinned(version))
        authenticated = entry.get("authenticated")
        if authenticated is None and transport in REMOTE_TRANSPORTS:
            authenticated = bool(entry.get("authenticated", False))
        server = McpServer(
            name=name,
            transport=transport,
            command=_str(entry.get("command")),
            args=args,
            env_keys=[str(k) for k in entry.get("env_keys") or []],
            config=_str(entry.get("config")),
            line=entry.get("line"),
            package=package,
            url=url,
            version=version,
            version_pinned=pinned,
            sha256=_str(entry.get("sha256")),
            authenticated=_bool(authenticated),
            capabilities=result.capabilities,
            risk=result.risk,
            human_in_the_loop=result.human_in_the_loop if result.applied else None,
            reversible=result.reversible if result.applied else None,
            rate_limited=result.rate_limited if result.applied else None,
            risk_override=result.applied,
            justification=result.justification,
            matched_rules=heuristic.rule_ids(),
            heuristic_capabilities=heuristic.capabilities,
            heuristic_risk=heuristic.risk,
            locations=_entry_locations(entry),
        )
        servers.append(server)

    servers.sort(key=lambda s: (-_risk_rank(s.risk), s.name.lower()))
    return servers


def _looks_pinned(version: str) -> bool:
    text = version.strip().lstrip("^~>=<v")
    return bool(text) and text[0].isdigit() and not text.endswith(".x") and "*" not in text


# --- providers ----------------------------------------------------------------


def map_providers(lock: SurfaceLock, manifest: Manifest, models: list[Model]) -> list[Provider]:
    declared_models = manifest.models
    providers: dict[str, Provider] = {}
    for entry in lock.kind("providers"):
        name = _str(entry.get("name"))
        if not name:
            continue
        providers[name] = Provider(name=name, locations=_entry_locations(entry))

    # A model's provider implies the provider is present even if the scan missed it.
    for model in models:
        if model.provider and model.provider in HOSTED_PROVIDERS:
            providers.setdefault(model.provider, Provider(name=model.provider))
        if model.provider and model.provider in providers and model.alias not in providers[model.provider].models:
            providers[model.provider].models.append(model.alias)

    out: list[Provider] = []
    # Facts declared for a third-party service apply to the provider too, so a
    # signed DPA on `external_services` is not reported as missing here.
    declared_services = {
        str(entry.get("provider") or entry.get("name", "")).lower(): entry
        for entry in manifest.external_services
    }
    for name, provider in providers.items():
        region = None
        dpa = None
        for alias, facts in declared_models.items():
            if _str(facts.get("provider")) == name or name in _provider_of_alias(alias, models):
                region = region or _str(facts.get("hosting_region"))
                if facts.get("data_processing_agreement") is not None:
                    dpa = bool(facts.get("data_processing_agreement"))
        service = declared_services.get(name.lower())
        if service:
            region = region or _str(service.get("region"))
            if service.get("dpa") is not None:
                dpa = bool(service.get("dpa"))
        provider.region = region
        provider.dpa = dpa
        provider.data_classification = _str(manifest.system.get("data_classification"))
        provider.endpoint = _provider_endpoint(name)
        provider.purpose = "Hosted model inference"
        out.append(provider)
    out.sort(key=lambda p: p.name.lower())
    return out


def _provider_of_alias(alias: str, models: list[Model]) -> list[str]:
    for model in models:
        if model.alias == alias and model.provider:
            return [model.provider]
    return []


def _provider_endpoint(name: str) -> str | None:
    return {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "mistral": "https://api.mistral.ai/v1",
        "cohere": "https://api.cohere.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "voyageai": "https://api.voyageai.com/v1",
        "elevenlabs": "https://api.elevenlabs.io/v1",
        "deepgram": "https://api.deepgram.com/v1",
    }.get(name)


# --- datasets & retrieval -----------------------------------------------------


def map_datasets(manifest: Manifest) -> list[Dataset]:
    out: list[Dataset] = []
    for entry in manifest.datasets:
        out.append(
            Dataset(
                name=str(entry["name"]),
                version=_str(entry.get("version")),
                classification=_str(entry.get("classification")),
                sensitive_data=[str(v) for v in entry.get("sensitive_data") or []],
                pii=bool(entry.get("pii")),
                consent_basis=_str(entry.get("consent_basis")),
                retention=_str(entry.get("retention")),
                jurisdiction=_str(entry.get("jurisdiction")),
                owners=[str(v) for v in entry.get("owners") or []],
                custodians=[str(v) for v in entry.get("custodians") or []],
                source=_str(entry.get("source")),
                refresh=_str(entry.get("refresh")),
                description=_str(entry.get("description")),
                kind="dataset",
            )
        )
    for entry in manifest.retrieval_sources:
        out.append(
            Dataset(
                name=str(entry["name"]),
                version=None,
                classification=_str(entry.get("classification")),
                sensitive_data=[],
                pii=bool(entry.get("pii")),
                consent_basis=None,
                retention=_str(entry.get("retention")),
                jurisdiction=_str(entry.get("jurisdiction")),
                owners=[str(v) for v in entry.get("owners") or []],
                source=_str(entry.get("source")) or _str(entry.get("endpoint")),
                refresh=_str(entry.get("refresh")),
                description=_str(entry.get("description"))
                or f"Retrieval source ({entry.get('kind', 'other')})",
                kind="retrieval",
            )
        )
    # Retrieval sources declared by the scanner (rare) are merged in too.
    out.sort(key=lambda d: (d.kind != "dataset", d.name.lower()))
    return out


# --- external services --------------------------------------------------------


def map_external_services(manifest: Manifest) -> list[ExternalService]:
    out: list[ExternalService] = []
    for entry in manifest.external_services:
        out.append(
            ExternalService(
                name=str(entry["name"]),
                provider=_str(entry.get("provider")),
                purpose=_str(entry.get("purpose")),
                endpoint=_str(entry.get("endpoint")),
                data_shared=[str(v) for v in entry.get("data_shared") or []],
                classification=_str(entry.get("classification")),
                dpa=entry.get("dpa") if isinstance(entry.get("dpa"), bool) else None,
                region=_str(entry.get("region")),
                authenticated=entry.get("authenticated")
                if isinstance(entry.get("authenticated"), bool)
                else True,
                description=_str(entry.get("description")),
            )
        )
    out.sort(key=lambda e: e.name.lower())
    return out


# --- AI SDKs ------------------------------------------------------------------


def map_ai_sdks(sdks: list[Any]) -> list[AiSdkLibrary]:
    return [
        AiSdkLibrary(
            name=sdk.name,
            version=sdk.version,
            ecosystem=sdk.ecosystem,
            provider=sdk.provider,
            purl=sdk.purl,
        )
        for sdk in sdks
    ]


# --- contacts -----------------------------------------------------------------


def map_contacts(manifest: Manifest) -> list[Contact]:
    contacts: list[Contact] = []
    for entry in manifest.system.get("contacts") or []:
        if isinstance(entry, dict) and entry.get("name"):
            contacts.append(
                Contact(
                    name=str(entry["name"]),
                    email=_str(entry.get("email")),
                    role=_str(entry.get("role")),
                )
            )
    return contacts


# --- application --------------------------------------------------------------


def app_version(manifest: Manifest, git: GitInfo) -> str | None:
    """Resolve the system version.

    `version: git` (or an absent version with a usable git checkout) yields the
    tag, else `git describe`, else the short commit. A bare commit hash is
    prefixed with `g` so the value reads as a revision and does not collide
    with a semantic version.
    """
    declared = _str(manifest.system.get("version"))
    if declared and declared != "git":
        return declared
    if declared == "git" or git.available:
        hint = git.version_hint
        if hint and hint[0] in "0123456789abcdef" and len(hint) >= 7 and "-" not in hint and "." not in hint:
            return f"g{hint}"
        return hint
    return None


def build_bom(
    *,
    root: Path,
    lock: SurfaceLock,
    manifest: Manifest,
    codeowners: CodeOwners,
    git: GitInfo,
    ai_sdks: list[Any],
    lock_fresh: bool,
    lock_note: str | None,
    scanner: str,
) -> AiBom:
    """Assemble the full BOM model from every input."""
    models = map_models(lock, manifest)
    prompts = map_prompts(lock, manifest, codeowners, lock_fresh=lock_fresh)
    tools = map_tools(lock, manifest)
    mcp_servers = map_mcp_servers(lock, manifest)
    providers = map_providers(lock, manifest, models)

    system = manifest.system
    name = _str(system.get("name")) or (root.resolve().name if root.name else "ai-system")

    bom = AiBom(
        app_name=name,
        app_version=app_version(manifest, git),
        app_description=_str(system.get("description")),
        app_purpose=_str(system.get("purpose")),
        deployment=_str(system.get("deployment")),
        data_classification=_str(system.get("data_classification")),
        jurisdictions=[str(j) for j in system.get("jurisdictions") or []],
        risk_classification=_normalise_risk(system.get("risk_classification")),
        human_oversight=_str(system.get("human_oversight")),
        owner=_str(system.get("owner")),
        contacts=map_contacts(manifest),
        app_bom_ref=f"app:{snake_split(name).replace(' ', '-')}",
        models=models,
        prompts=prompts,
        tools=tools,
        mcp_servers=mcp_servers,
        providers=providers,
        datasets=map_datasets(manifest),
        external_services=map_external_services(manifest),
        ai_sdks=map_ai_sdks(ai_sdks),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        tool_version=__version__,
        rules_version=RULES_VERSION,
        git=git.as_dict(),
        lock_path=str(lock.path) if lock.path else None,
        lock_generated=lock.generated,
        lock_fresh=lock_fresh,
        lock_note=lock_note,
        manifest_path=str(manifest.path) if manifest.path else None,
        manifest_complete=dict(manifest.complete),
        scanner=scanner,
        source_root=".",
    )

    # Tool -> MCP server link, by name, so the dependency graph is real.
    server_names = {s.name for s in bom.mcp_servers}
    for tool in bom.tools:
        if tool.mcp_server and tool.mcp_server not in server_names:
            tool.mcp_server = None
        if tool.mcp_server is None:
            for server in bom.mcp_servers:
                if snake_split(server.name) and snake_split(server.name) in snake_split(tool.name):
                    tool.mcp_server = server.name
                    break

    from aibom.risk import attach_review_notes

    attach_review_notes(bom)
    return bom


def _normalise_risk(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or not value.get("framework") or not value.get("label"):
        return None
    return {
        "framework": str(value["framework"]),
        "label": str(value["label"]),
        "rationale": _str(value.get("rationale")) or "",
    }


def merge_declared(lock: SurfaceLock, manifest: Manifest) -> SurfaceLock:
    """Overlay manifest-declared facts the scanner cannot see onto the lock.

    Only *additive* facts are merged: a declared external service, or a tool
    the manifest names that the scanner missed entirely. Existing scan facts are
    never overwritten — the scan is the evidence, the manifest is the context.
    """
    data = dict(lock.data)
    known_tools = {str(t.get("name")) for t in lock.kind("tools")}
    extra_tools = [
        {
            "name": name,
            "source": "manifest",
            "description": "Declared in aibom.yaml; not visible in source.",
            "param_keys": [],
        }
        for name in manifest.tools
        if name not in known_tools
    ]
    if extra_tools:
        data["tools"] = list(lock.kind("tools")) + extra_tools

    known_servers = {str(s.get("name")) for s in lock.kind("mcp_servers")}
    extra_servers = [
        {
            "name": name,
            "transport": "unknown",
            "config": "aibom.yaml",
            "source": "manifest",
        }
        for name in manifest.mcp_servers
        if name not in known_servers
    ]
    if extra_servers:
        data["mcp_servers"] = list(lock.kind("mcp_servers")) + extra_servers

    if manifest.datasets:
        data.setdefault("datasets", [])

    return SurfaceLock(
        path=lock.path,
        root=lock.root,
        data=data,
        generated=lock.generated,
    )


class MappingError(AibomError):
    """Raised when a lock entry cannot be mapped at all."""
