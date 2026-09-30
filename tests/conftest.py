"""Shared fixtures for the aibom test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aibom.api import GenerateOptions, generate_full

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_root(name: str) -> Path:
    return (FIXTURES / name).resolve()


@pytest.fixture(scope="session")
def support_agent_path() -> Path:
    return fixture_root("support-agent")


@pytest.fixture(scope="session")
def rag_service_path() -> Path:
    return fixture_root("rag-service")


@pytest.fixture(scope="session")
def mcp_heavy_path() -> Path:
    return fixture_root("mcp-heavy")


@pytest.fixture(scope="session")
def support_agent_bom(support_agent_path: Path) -> dict:
    bom, _ = generate_full(GenerateOptions(root=support_agent_path, refresh=True))
    return bom


@pytest.fixture(scope="session")
def rag_service_bom(rag_service_path: Path) -> dict:
    bom, _ = generate_full(GenerateOptions(root=rag_service_path, refresh=True))
    return bom


@pytest.fixture(scope="session")
def mcp_heavy_bom(mcp_heavy_path: Path) -> dict:
    bom, _ = generate_full(GenerateOptions(root=mcp_heavy_path, refresh=True))
    return bom


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    path = FIXTURES / "golden"
    path.mkdir(exist_ok=True)
    return path


def write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
