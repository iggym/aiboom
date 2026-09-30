"""In-process scanning (spec F-IN-1).

When a `surface.lock` is present aibom reads it. When it is absent — or when
`--refresh` is passed — aibom scans the working tree in-process:

1. If `surfacelock` is importable, delegate to it. `surfacelock` is the
   canonical scanner; aibom must never disagree with it.
2. Otherwise run the bundled deterministic scanner below, so the tool still
   produces a useful (and reproducible) inventory with no extra dependencies.

The bundled scanner is intentionally conservative: it reports what it can
prove from source and leaves the rest to `aibom.yaml`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from aibom.digest import DIGEST_SUFFIX
from aibom.inputs.lock import LOCK_FILENAMES, SurfaceLock
from aibom.util import approx_tokens, sha256_file, sha256_text, snake_split

#: Directories never worth scanning.
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", "dist", "build",
    ".next", ".turbo", "target", "vendor", ".idea", ".vscode", "site-packages",
    ".agent_tmp", "htmlcov", ".cache",
}

TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".md", ".mdx", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".jinja", ".jinja2", ".j2", ".prompt",
    ".go", ".rb", ".java", ".kt", ".rs", ".sh", ".env.example",
}

MAX_FILE_BYTES = 512 * 1024

#: Files aibom itself owns. They are declarations or generated artifacts, not
#: source: scanning them would let the manifest's own text (e.g. the word
#: "elevenlabs" in a provider name) masquerade as a code finding. Manifest
#: declarations are consumed separately by `mapping.merge_declared`.
OWN_FILES = {
    "aibom.yaml",
    "aibom.yml",
    ".aibom.yaml",
    "aibom.cdx.json",
    "aibom.cdx.xml",
    "AIBOM.md",
    "AIBOM.html",
    "AIBOM.pdf",
    "surface.lock",
    "surface.lock.yaml",
    "surface.lock.json",
}


@dataclass(slots=True)
class ScanResult:
    lock: SurfaceLock
    source: str  # "surfacelock" | "bundled"

    def describe(self) -> str:
        return f"{self.source} scanner"


# --- provider / model detection ----------------------------------------------

#: SDK import patterns -> canonical provider name.
PROVIDER_SIGNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai", re.compile(r"\b(?:from|import)\s+openai\b|\bOpenAI\s*\(|\bAsyncOpenAI\s*\(")),
    ("anthropic", re.compile(r"\b(?:from|import)\s+anthropic\b|\bAnthropic\s*\(|\bAsyncAnthropic\s*\(")),
    ("google", re.compile(r"\bgoogle\.generativeai\b|\bgoogle\.genai\b|\bgenai\.Client\s*\(|\bGenerativeModel\s*\(")),
    ("azure-openai", re.compile(r"\bAzureOpenAI\s*\(|\bazure\.ai\.inference\b")),
    ("mistral", re.compile(r"\bfrom\s+mistralai\b|\bMistral\s*\(|\bMistralClient\s*\(")),
    ("cohere", re.compile(r"\bfrom\s+cohere\b|\bcohere\.Client\s*\(")),
    ("bedrock", re.compile(r"\bboto3\.client\(\s*[\"']bedrock|\bbedrock-runtime\b")),
    ("vertexai", re.compile(r"\bvertexai\b|\baiplatform\b")),
    ("litellm", re.compile(r"\bimport\s+litellm\b|\bfrom\s+litellm\b|\blitellm\.(?:completion|embedding)\s*\(")),
    ("langchain", re.compile(r"\bfrom\s+langchain\b|\bimport\s+langchain\b|\blangchain_openai\b|\bChatOpenAI\s*\(")),
    ("llama-index", re.compile(r"\bllama_index\b|\bfrom\s+llama_index\b")),
    ("vercel-ai", re.compile(r"\bfrom\s+[\"']ai[\"']|\bimport\s*\{[^}]*\bgenerateText\b|\bstreamText\s*\(")),
    ("elevenlabs", re.compile(r"\belevenlabs\b|\bElevenLabs\s*\(")),
    ("deepgram", re.compile(r"\bdeepgram\b")),
    ("huggingface", re.compile(r"\bhuggingface_hub\b|\btransformers\.(?:pipeline|AutoModel)\b|\bInferenceClient\s*\(")),
)

#: `model="..."`, `model: ...`, `model_name = "..."` and friends.
MODEL_CALL_RE = re.compile(
    r"""(?imx)
    \b(?:model|model_name|model_id|engine|deployment)\s*[:=]\s*
    (?:f)?["'](?P<name>[A-Za-z0-9][\w./:\-@]{1,80})["']
    """
)

#: Bare model-looking string literals, e.g. a constant table of model names.
MODEL_LITERAL_RE = re.compile(
    r"""(?x)
    ["'](?P<name>
      (?:gpt|o[1-4]|chatgpt|text-embedding|text-moderation|dall-e|whisper)[\w.\-]{0,60}
      |claude[\w.\-]{0,60}
      |gemini[\w.\-]{0,60}
      |command-r[\w.\-]{0,40}
      |mistral[\w.\-]{0,40}
      |mixtral[\w.\-]{0,40}
      |llama[\w.\-]{0,40}
      |deepseek[\w.\-]{0,40}
      |qwen[\w.\-]{0,40}
      |phi-?[0-9][\w.\-]{0,30}
      |voyage[\w.\-]{0,40}
      |cohere\.embed[\w.\-]{0,30}
      |titan-[\w.\-]{0,40}
      |stability[\w.\-]{0,40}
      |eleven_?[\w.\-]{0,40}
    )["']
    """
)

MODEL_PREFIX_PROVIDER: tuple[tuple[str, str], ...] = (
    ("gpt", "openai"),
    ("chatgpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-embedding", "openai"),
    ("text-moderation", "openai"),
    ("dall-e", "openai"),
    ("whisper", "openai"),
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("command-r", "cohere"),
    ("cohere.", "cohere"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("llama", "meta"),
    ("deepseek", "deepseek"),
    ("qwen", "alibaba"),
    ("phi", "microsoft"),
    ("voyage", "voyageai"),
    ("titan-", "bedrock"),
    ("stability", "stabilityai"),
)

PINNED_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$|@\d{8}$|:\d{4}-\d{2}-\d{2}$")
EMBEDDING_RE = re.compile(r"embed", re.I)
RERANK_RE = re.compile(r"rerank", re.I)

PROMPT_DIR_HINTS = ("prompts", "prompt", "templates", "prompt_templates")
PROMPT_FILE_RE = re.compile(r".*(?:\.prompt|\.prompt\.(?:md|txt|jinja2?)|prompt.*\.(?:md|txt|jinja2?))$", re.I)
PROMPT_ASSIGN_RE = re.compile(
    r"""(?imx)
    ^\s*(?P<name>[A-Z][A-Z0-9_]{2,60})
    \s*(?::\s*[^=]+)?=\s*
    (?:f|r|fr|rf)?(?P<quote>\"\"\"|''')
    """
)
SYSTEM_KWARG_RE = re.compile(
    r"""(?imx)\b(?P<name>system|system_prompt|instructions|developer_prompt)\s*=\s*(?:f|r|fr|rf)?(?P<quote>\"\"\"|''')"""
)

TOOL_DECORATOR_RE = re.compile(
    r"""(?imx)^\s*@(?:tool|function_tool|ai_function|mcp\.tool|server\.tool|app\.tool)\b"""
)
TOOL_DEF_RE = re.compile(r"""(?imx)^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)""")
LANGCHAIN_TOOL_RE = re.compile(r"""(?imx)\bTool\s*\(\s*name\s*=\s*["'](?P<name>[\w.\-]+)["']""")
STRUCTURED_TOOL_RE = re.compile(r"""(?imx)["']name["']\s*:\s*["'](?P<name>[\w.\-]+)["']\s*,\s*["']description["']\s*:""")

MCP_CONFIG_FILES = (".mcp.json", "mcp.json", ".cursor/mcp.json", ".vscode/mcp.json", "claude_desktop_config.json")
MCP_CODE_RE = re.compile(
    r"""(?imx)
    (?P<cls>MCPServer(?:Stdio|Sse|StreamableHttp)|\bstdio_client|\bsse_client|StreamableHTTPSessionManager)
    \s*\(
    """
)
MCP_PACKAGE_RE = re.compile(r"""["'](?P<pkg>@modelcontextprotocol/[\w.\-/]+|mcp-server-[\w.\-]+)["']""")

SKIP_MARKERS = ("aibom:ignore-file", "aibom-ignore-file")


def _is_text_file(path: Path) -> bool:
    if path.name in MCP_CONFIG_FILES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in OWN_FILES or path.name.endswith(DIGEST_SUFFIX):
            continue
        if path.name in LOCK_FILENAMES or path.suffix == ".lock":
            continue
        if not _is_text_file(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _provider_for_model(name: str) -> str | None:
    lowered = name.lower()
    for prefix, provider in MODEL_PREFIX_PROVIDER:
        if lowered.startswith(prefix):
            return provider
    return None


def _model_kind(name: str) -> str:
    if EMBEDDING_RE.search(name):
        return "embedding"
    if RERANK_RE.search(name):
        return "reranker"
    if name.lower().startswith("text-moderation"):
        return "guardrail"
    return "foundation"


def _iter_string_literals(text: str):
    """Yield (start_offset, quote, literal) for simple string literals."""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            triple = text.startswith(quote * 3, i)
            opener = quote * 3 if triple else quote
            j = i + len(opener)
            buf: list[str] = []
            while j < n:
                if text.startswith(opener, j):
                    break
                if not triple and text[j] == "\\":
                    buf.append(text[j : j + 2])
                    j += 2
                    continue
                if not triple and text[j] == "\n":
                    break
                buf.append(text[j])
                j += 1
            if text.startswith(opener, j):
                yield i, opener, "".join(buf)
                i = j + len(opener)
                continue
        i += 1


def scan_tree(root: Path) -> dict[str, Any]:
    """The bundled deterministic scanner. Returns a lockfile-shaped mapping."""
    root = root.resolve()
    files = _iter_files(root)
    file_hashes: dict[str, str] = {}
    models: dict[str, dict[str, Any]] = {}
    prompts: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    mcp_servers: dict[str, dict[str, Any]] = {}
    providers: dict[str, dict[str, Any]] = {}

    for path in files:
        rel = _rel(path, root)
        try:
            file_hashes[rel] = sha256_file(path)
        except OSError:
            continue
        text = _read(path)
        if text is None:
            continue
        if any(marker in text for marker in SKIP_MARKERS):
            continue
        lines = text.splitlines()

        # --- providers -------------------------------------------------------
        for provider, pattern in PROVIDER_SIGNS:
            m = pattern.search(text)
            if m:
                line = text[: m.start()].count("\n") + 1
                entry = providers.setdefault(
                    provider, {"name": provider, "locations": [], "sdk": provider}
                )
                loc = {"path": rel, "line": line}
                if loc not in entry["locations"]:
                    entry["locations"].append(loc)

        # --- models ----------------------------------------------------------
        seen_names: set[str] = set()
        for m in MODEL_CALL_RE.finditer(text):
            seen_names.add(m.group("name"))
        for m in MODEL_LITERAL_RE.finditer(text):
            seen_names.add(m.group("name"))
        for name in sorted(seen_names):
            if len(name) < 3 or name.lower() in {"model", "gpt", "claude"}:
                continue
            model_provider: str | None = _provider_for_model(name)
            if model_provider is None and not any(
                sign in name.lower() for sign in ("embed", "rerank")
            ):
                continue
            model_line: int | None = None
            for i, raw in enumerate(lines, start=1):
                if name in raw:
                    model_line = i
                    break
            entry = models.setdefault(
                name,
                {
                    "name": name,
                    "alias": name,
                    "resolved": name if PINNED_RE.search(name) else None,
                    "floating": not bool(PINNED_RE.search(name)),
                    "kind": _model_kind(name),
                    "provider": model_provider,
                    "locations": [],
                },
            )
            loc = {"path": rel, "line": model_line or 1}
            if loc not in entry["locations"]:
                entry["locations"].append(loc)
            if entry.get("provider") is None:
                entry["provider"] = model_provider
            if model_provider:
                pentry = providers.setdefault(
                    model_provider, {"name": model_provider, "locations": [], "sdk": model_provider}
                )
                if loc not in pentry["locations"]:
                    pentry["locations"].append(loc)

        # --- prompts: files ---------------------------------------------------
        if PROMPT_FILE_RE.match(path.name) or any(h in path.parts for h in PROMPT_DIR_HINTS):
            body = text.strip()
            if body:
                prompts.append(
                    {
                        "name": path.stem,
                        "path": rel,
                        "line": 1,
                        "source": "file",
                        "text_sha256": sha256_text(text),
                        "approx_tokens": approx_tokens(text),
                        "owners_hint": None,
                    }
                )

        # --- prompts: inline triple-quoted constants --------------------------
        for m in PROMPT_ASSIGN_RE.finditer(text):
            start = m.end()
            literal = _literal_after(text, start, m.group("quote"))
            if literal is None or len(literal) < 40:
                continue
            line = text[: m.start()].count("\n") + 1
            prompts.append(
                {
                    "name": m.group("name").lower(),
                    "path": rel,
                    "line": line,
                    "source": "inline",
                    "text_sha256": sha256_text(literal),
                    "approx_tokens": approx_tokens(literal),
                    "text": literal,
                }
            )
        for m in SYSTEM_KWARG_RE.finditer(text):
            start = m.end()
            literal = _literal_after(text, start, m.group("quote"))
            if literal is None or len(literal) < 40:
                continue
            line = text[: m.start()].count("\n") + 1
            prompts.append(
                {
                    "name": f"{path.stem}-{m.group('name')}".lower(),
                    "path": rel,
                    "line": line,
                    "source": "inline",
                    "text_sha256": sha256_text(literal),
                    "approx_tokens": approx_tokens(literal),
                    "text": literal,
                }
            )

        # --- tools -----------------------------------------------------------
        if path.suffix.lower() in {".py", ".ts", ".js", ".mjs", ".cjs", ".tsx", ".jsx"}:
            decorated = False
            for m in TOOL_DECORATOR_RE.finditer(text):
                after = text[m.end() :]
                d = TOOL_DEF_RE.search(after)
                if not d:
                    continue
                decorated = True
                line = text[: m.start()].count("\n") + 1
                params = _param_names(d.group("params"))
                _add_tool(tools, d.group("name"), rel, line, params, text, m.start())
            for m in LANGCHAIN_TOOL_RE.finditer(text):
                decorated = True
                line = text[: m.start()].count("\n") + 1
                _add_tool(tools, m.group("name"), rel, line, [], text, m.start())
            if not decorated and _is_tools_module(path):
                for d in TOOL_DEF_RE.finditer(text):
                    name = d.group("name")
                    if name.startswith("_") or name in {"main"}:
                        continue
                    line = text[: d.start()].count("\n") + 1
                    _add_tool(tools, name, rel, line, _param_names(d.group("params")), text, d.start())
        if path.suffix.lower() in {".json", ".yaml", ".yml"}:
            _structured_tools(text, rel, tools)

        # --- MCP servers ------------------------------------------------------
        if path.name in MCP_CONFIG_FILES or path.name.endswith("mcp.json"):
            _mcp_from_config(text, rel, mcp_servers)
        for m in MCP_CODE_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            window = text[max(0, m.start() - 400) : m.end() + 600]
            pkg = MCP_PACKAGE_RE.search(window)
            name = pkg.group("pkg") if pkg else f"{path.stem}-{m.group('cls').lower()}"
            entry = mcp_servers.setdefault(
                name,
                {
                    "name": name,
                    "transport": _transport_for(m.group("cls")),
                    "command": None,
                    "args": [],
                    "env_keys": _env_keys(window),
                    "config": rel,
                    "line": line,
                    "package": pkg.group("pkg") if pkg else None,
                },
            )
            entry.setdefault("locations", [])
            loc = {"path": rel, "line": line}
            if loc not in entry["locations"]:
                entry["locations"].append(loc)

    prompts = _dedupe_prompts(prompts)
    return {
        "lockfile_version": 1,
        "scanner": "aibom-bundled",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root": ".",
        "files": file_hashes,
        "models": _sorted_values(models),
        "prompts": prompts,
        "tools": _sorted_values(tools),
        "mcp_servers": _sorted_values(mcp_servers),
        "providers": _sorted_values(providers),
        "libraries": [],
        "datasets": [],
    }


def _split_package_version(spec: str) -> tuple[str, str | None]:
    """Split `@scope/name@1.2.3` into (`@scope/name`, `1.2.3`).

    The version has to come from the spec because a CLI flag is the only place
    an MCP package is versioned; npm pinning is `name@version`, not a range.
    """
    if spec.startswith("@"):
        head, _, rest = spec.partition("/")
        name, sep, version = rest.partition("@")
        if sep and version:
            return f"{head}/{name}", version
        return spec, None
    name, sep, version = spec.partition("@")
    if sep and version:
        return name, version
    return spec, None


def _is_tools_module(path: Path) -> bool:
    """Heuristic: is this file a tool-registration module?

    `tools/`, `tool_*.py`, `*_tools.py` — the conventions agent frameworks use.
    Restricting the fallback this way keeps a random `def send_email()` in a
    mailer from being reported as an agent tool.
    """
    stem = path.stem.lower()
    if "tool" in stem or stem in {"functions", "actions", "capabilities"}:
        return True
    return any(part.lower() in {"tools", "functions", "actions", "capabilities"} for part in path.parts)


def _param_names(raw: str) -> list[str]:
    names: list[str] = []
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk or chunk in {"*", "/"}:
            continue
        name = chunk.split(":")[0].split("=")[0].strip().lstrip("*")
        if name and name not in {"self", "cls"}:
            names.append(name)
    return names


def _literal_after(text: str, start: int, quote: str) -> str | None:
    end = text.find(quote, start)
    if end == -1:
        return None
    return text[start:end]


def _transport_for(cls: str) -> str:
    lowered = cls.lower()
    if "stdio" in lowered:
        return "stdio"
    if "sse" in lowered:
        return "sse"
    if "http" in lowered:
        return "http"
    return "unknown"


def _env_keys(window: str) -> list[str]:
    keys = re.findall(r"""["'](?P<k>[A-Z][A-Z0-9_]{2,40})["']\s*:""", window)
    return sorted(set(keys))


def _add_tool(
    tools: dict[str, dict[str, Any]],
    name: str,
    rel: str,
    line: int,
    params: list[str],
    text: str,
    offset: int,
) -> None:
    window = text[offset : offset + 900]
    doc = None
    doc_match = re.search(r'"""(.+?)"""', window, re.S)
    if doc_match:
        doc = doc_match.group(1).strip().splitlines()[0][:200]
    entry = tools.setdefault(
        name,
        {
            "name": name,
            "path": rel,
            "line": line,
            "source": "code",
            "description": doc,
            "param_keys": params,
            "capabilities": [],
        },
    )
    for key in params:
        if key not in entry["param_keys"]:
            entry["param_keys"].append(key)
    if doc and not entry.get("description"):
        entry["description"] = doc


def _structured_tools(text: str, rel: str, tools: dict[str, dict[str, Any]]) -> None:
    """OpenAPI-style `tools:`/`functions:` arrays in JSON/YAML manifests."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            return
    if not isinstance(data, dict):
        return
    # `mcpServers` is deliberately absent: those entries are servers, handled by
    # the MCP branch, not tools the model can call directly.
    for key in ("tools", "functions"):
        entries = data.get(key)
        if isinstance(entries, dict):
            entries = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in entries.items()]
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("operationId")
            if not name:
                continue
            params: list[str] = []
            schema = item.get("parameters") or item.get("input_schema") or item.get("inputSchema")
            if isinstance(schema, dict):
                props = schema.get("properties")
                if isinstance(props, dict):
                    params = sorted(props.keys())
            elif isinstance(schema, list):
                params = sorted(
                    str(p.get("name")) for p in schema if isinstance(p, dict) and p.get("name")
                )
            tools.setdefault(
                str(name),
                {
                    "name": str(name),
                    "path": rel,
                    "line": 1,
                    "source": "schema",
                    "description": item.get("description"),
                    "param_keys": params,
                    "capabilities": [],
                },
            )


def _mcp_from_config(text: str, rel: str, servers: dict[str, dict[str, Any]]) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    block = data.get("mcpServers") or data.get("mcp_servers") or data.get("servers")
    if not isinstance(block, dict):
        return
    for name, spec in block.items():
        if not isinstance(spec, dict):
            continue
        url = spec.get("url") or spec.get("endpoint")
        transport = spec.get("transport") or spec.get("type")
        if not transport:
            transport = "http" if url else "stdio"
        package = None
        version = None
        args = spec.get("args") or []
        if isinstance(args, list):
            for arg in args:
                if isinstance(arg, str) and ("mcp" in arg.lower() or arg.startswith("@")):
                    package, version = _split_package_version(arg)
                    break
        command = spec.get("command")
        if (
            package is None
            and command
            and isinstance(args, list)
            and args
            and isinstance(args[0], str)
            and args[0].startswith("@")
        ):
            package, version = _split_package_version(args[0])
        entry = servers.setdefault(
            str(name),
            {
                "name": str(name),
                "transport": transport,
                "command": command,
                "args": args if isinstance(args, list) else [],
                "env_keys": sorted((spec.get("env") or {}).keys()) if isinstance(spec.get("env"), dict) else [],
                "config": rel,
                "line": 1,
                "package": package,
                "version": version,
                "url": url,
            },
        )
        entry.setdefault("locations", [])
        if {"path": rel, "line": 1} not in entry["locations"]:
            entry["locations"].append({"path": rel, "line": 1})


def _dedupe_prompts(prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for prompt in prompts:
        key = (prompt["path"], str(prompt.get("line")), prompt["text_sha256"])
        if key not in seen:
            seen[key] = prompt
    return sorted(seen.values(), key=lambda p: (p["path"], p.get("line") or 0, p["name"]))


def _sorted_values(mapping: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(mapping):
        entry = mapping[key]
        if "locations" in entry:
            entry["locations"] = sorted(
                entry["locations"], key=lambda loc: (loc["path"], loc.get("line") or 0)
            )
        out.append(entry)
    return out


# --- surfacelock delegation ---------------------------------------------------


def _try_surfacelock(root: Path) -> SurfaceLock | None:
    try:
        import surfacelock  # type: ignore
    except ImportError:
        return None

    for func_name in ("scan", "scan_repo", "scan_path"):
        func = getattr(surfacelock, func_name, None)
        if callable(func):
            try:
                data = func(root)
            except TypeError:
                data = func(str(root))
            except Exception:  # noqa: BLE001 - a broken scanner must not break aibom
                continue
            if isinstance(data, dict):
                data.setdefault("lockfile_version", 1)
                data.setdefault("scanner", "surfacelock")
                data.setdefault("files", {})
                return SurfaceLock(
                    path=root / "surface.lock",
                    root=root,
                    data=data,
                    generated=True,
                )
    return None


def scan(root: Path, *, prefer: str = "auto") -> ScanResult:
    """Scan ``root`` and return a lock-shaped result.

    ``prefer`` may be ``auto`` (surfacelock when importable), ``surfacelock`` or
    ``bundled`` — the last two exist so tests and air-gapped users can pin the
    behaviour and so `doctor` can report which path was taken.
    """
    root = root.resolve()
    if prefer in ("auto", "surfacelock"):
        lock = _try_surfacelock(root)
        if lock is not None:
            return ScanResult(lock=lock, source="surfacelock")
        if prefer == "surfacelock":
            from aibom.errors import MissingDependencyError

            raise MissingDependencyError(
                "surfacelock is not installed",
                hint="pip install 'aibom[scanner]' or use --scanner bundled",
            )

    data = scan_tree(root)
    return ScanResult(
        lock=SurfaceLock(path=root / "surface.lock", root=root, data=data, generated=True),
        source="bundled",
    )


def surfacelock_available() -> bool:
    try:
        import surfacelock  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def write_lock(lock: SurfaceLock, path: Path) -> None:
    payload = dict(lock.data)
    payload["lockfile_version"] = lock.version
    payload["scanner"] = payload.get("scanner", lock.scanner)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def capability_hints(text: str) -> list[str]:
    """Cheap capability hints used when the lock is silent about a tool."""
    words = set(snake_split(text).split())
    hints = []
    for label, triggers in (
        ("write", {"write", "create", "update", "put", "post", "patch", "insert", "save", "upload"}),
        ("read", {"read", "get", "list", "fetch", "search", "query", "lookup"}),
        ("destructive", {"delete", "remove", "drop", "destroy", "purge", "truncate"}),
        ("financial", {"refund", "payment", "charge", "invoice", "transfer", "price"}),
        ("external-comms", {"email", "slack", "sms", "notify", "send", "webhook", "publish"}),
        ("filesystem", {"file", "path", "dir", "directory", "fs"}),
        ("network", {"http", "url", "request", "socket", "endpoint"}),
        ("secrets", {"token", "secret", "credential", "apikey", "api_key", "password"}),
        ("identity", {"auth", "user", "permission", "role", "login", "session"}),
        ("code-exec", {"exec", "eval", "shell", "subprocess", "command", "run"}),
    ):
        if words & triggers:
            hints.append(label)
    return hints
