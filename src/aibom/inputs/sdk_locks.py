"""AI SDK version discovery from dependency lockfiles (spec F-IN-5).

aibom records which AI SDKs and at what version the system depends on, as
`library` components tagged `aibom:role=ai-sdk`. It reads the lockfiles that are
already in the repo rather than resolving anything over the network.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: Packages aibom recognises as AI SDKs, matched as a prefix on the package
#: name. Order matters only for reporting; the first match wins.
AI_SDK_PREFIXES: tuple[tuple[str, str], ...] = (
    ("openai", "openai"),
    ("anthropic", "anthropic"),
    ("google-genai", "google"),
    ("google-generativeai", "google"),
    ("google-cloud-aiplatform", "google"),
    ("vertexai", "google"),
    ("langchain", "langchain"),
    ("langgraph", "langchain"),
    ("llama-index", "llama-index"),
    ("llama_index", "llama-index"),
    ("mcp", "mcp"),
    ("@modelcontextprotocol/", "mcp"),
    ("litellm", "litellm"),
    ("mistralai", "mistral"),
    ("cohere", "cohere"),
    ("ai", "vercel-ai"),
    ("@ai-sdk/", "vercel-ai"),
    ("boto3", "aws"),
    ("transformers", "huggingface"),
    ("huggingface-hub", "huggingface"),
    ("sentence-transformers", "huggingface"),
    ("instructor", "instructor"),
    ("dspy-ai", "dspy"),
    ("haystack-ai", "haystack"),
    ("crewai", "crewai"),
    ("autogen-agentchat", "autogen"),
    ("semantic-kernel", "microsoft"),
    ("ollama", "ollama"),
    ("vllm", "vllm"),
    ("guidance", "guidance"),
    ("outlines", "outlines"),
    ("weave", "w&b"),
)

_SDK_LOOKALIKE = {"ai"}

REQ_LINE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.\-\[\]]+)\s*(?:\[[^\]]*\])?\s*(?P<op>===|==|>=|<=|~=|!=|>|<)?\s*(?P<ver>[^\s;#]+)?"
)
NPM_LOCK_SECTIONS = ("packages", "dependencies")


@dataclass(slots=True)
class AiSdk:
    name: str
    version: str | None
    ecosystem: str  # "pypi" | "npm"
    provider: str | None
    source: str  # lockfile the entry came from

    @property
    def purl(self) -> str:
        base = f"pkg:{self.ecosystem}/{self.name}"
        return f"{base}@{self.version}" if self.version else base

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "ecosystem": self.ecosystem,
            "provider": self.provider,
            "source": self.source,
            "purl": self.purl,
        }


def _canonical(name: str) -> str:
    return name.strip().lower()


def _match(name: str) -> tuple[bool, str | None]:
    lowered = _canonical(name)
    for prefix, provider in AI_SDK_PREFIXES:
        if prefix.endswith("/"):
            if lowered.startswith(prefix):
                return True, provider
        elif lowered == prefix or lowered.startswith(prefix + "-") or lowered.startswith(prefix + "_"):
            return True, provider
    return False, None


def _add(found: dict[tuple[str, str], AiSdk], name: str, version: str | None, eco: str, src: str) -> None:
    ok, provider = _match(name)
    if not ok:
        return
    key = (eco, _canonical(name))
    existing = found.get(key)
    if existing is None:
        found[key] = AiSdk(name=name, version=version, ecosystem=eco, provider=provider, source=src)
    elif existing.version is None and version is not None:
        existing.version = version


# --- per-format readers -------------------------------------------------------


def _read_requirements(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = REQ_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").split("[")[0]
        _add(found, name, m.group("ver"), "pypi", path.name)


def _read_uv_lock(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return
    for pkg in data.get("package") or []:
        if isinstance(pkg, dict) and pkg.get("name"):
            _add(found, str(pkg["name"]), _str_or_none(pkg.get("version")), "pypi", path.name)


def _read_poetry_lock(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return
    for pkg in data.get("package") or []:
        if isinstance(pkg, dict) and pkg.get("name"):
            _add(found, str(pkg["name"]), _str_or_none(pkg.get("version")), "pypi", path.name)


def _read_package_lock(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, meta in packages.items():
            if not key or not isinstance(meta, dict):
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            _add(found, name, _str_or_none(meta.get("version")), "npm", path.name)
        return
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        for name, meta in deps.items():
            version = meta.get("version") if isinstance(meta, dict) else None
            _add(found, str(name), _str_or_none(version), "npm", path.name)


def _read_pnpm_lock(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return
    if not isinstance(data, dict):
        return
    for section in ("packages", "importers"):
        block = data.get(section)
        if isinstance(block, dict):
            for key in block:
                if section == "importers":
                    continue
                name, version = _split_pnpm_key(str(key))
                _add(found, name, version, "npm", path.name)
        if isinstance(block, dict) and section == "importers":
            for _importer, spec in block.items():
                for group in ("dependencies", "devDependencies", "optionalDependencies"):
                    deps = (spec or {}).get(group) if isinstance(spec, dict) else None
                    if isinstance(deps, dict):
                        for name, meta in deps.items():
                            version = meta.get("version") if isinstance(meta, dict) else None
                            _add(found, str(name), _str_or_none(version), "npm", path.name)


def _split_pnpm_key(key: str) -> tuple[str, str | None]:
    key = key.lstrip("/")
    if "(" in key:
        key = key.split("(", 1)[0]
    if "@" in key[1:]:
        idx = key.rfind("@")
        return key[:idx], key[idx + 1 :]
    return key, None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --- discovery ----------------------------------------------------------------

_PY_READERS = {
    "uv.lock": _read_uv_lock,
    "poetry.lock": _read_poetry_lock,
}
_NPM_READERS = {
    "package-lock.json": _read_package_lock,
    "pnpm-lock.yaml": _read_pnpm_lock,
}


def discover_ai_sdks(root: Path) -> list[AiSdk]:
    """Find every AI SDK the repo depends on, from lockfiles only."""
    found: dict[tuple[str, str], AiSdk] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".git", "node_modules", ".venv", "venv", "dist", "build"} for part in path.parts):
            continue
        name = path.name
        if name.startswith("requirements") and name.endswith(".txt"):
            _read_requirements(path, found)
        elif name in _PY_READERS:
            _PY_READERS[name](path, found)
        elif name in _NPM_READERS:
            _NPM_READERS[name](path, found)
        elif name == "pyproject.toml" and path.parent == root:
            _read_pyproject(path, found)

    return sorted(found.values(), key=lambda s: (s.ecosystem, s.name.lower()))


def _read_pyproject(path: Path, found: dict[tuple[str, str], AiSdk]) -> None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return
    project = data.get("project") or {}
    for spec in project.get("dependencies") or []:
        m = REQ_LINE_RE.match(str(spec))
        if m:
            _add(found, m.group("name"), m.group("ver"), "pypi", "pyproject.toml")
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name, spec in (poetry.get("dependencies") or {}).items():
        version = spec if isinstance(spec, str) else (spec or {}).get("version") if isinstance(spec, dict) else None
        _add(found, name, _str_or_none(version), "pypi", "pyproject.toml")
