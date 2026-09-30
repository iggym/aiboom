"""Diff tests (spec §9): model swap, tool risk increase, new provider,
unchanged, plus the `--fail-on` gates and Markdown release-note output.
"""

from __future__ import annotations

import copy
import json

import pytest

from aibom.api import GenerateOptions, generate_full
from aibom.diff import check_gates, diff_boms, render_diff_markdown, render_diff_text
from aibom.errors import DiffGateError


@pytest.fixture(scope="module")
def base() -> dict:
    return generate_full(GenerateOptions(root=None, refresh=True))[0] if False else _base()


def _base() -> dict:
    from pathlib import Path

    root = (Path(__file__).parent / "fixtures" / "support-agent").resolve()
    return generate_full(GenerateOptions(root=root, refresh=True))[0]


def _component(bom: dict, name: str) -> dict:
    for component in bom["components"]:
        if component["name"] == name:
            return component
    raise AssertionError(f"no component named {name} in {[c['name'] for c in bom['components']]}")


def _prop(component: dict, key: str):
    for entry in component.get("properties", []):
        if entry["name"] == key:
            return entry["value"]
    return None


def test_identical_boms_diff_empty(base: dict) -> None:
    result = diff_boms(base, copy.deepcopy(base))
    assert result.unchanged
    assert result.counts()["added"] == 0
    assert result.counts()["removed"] == 0
    assert result.counts()["changed"] == 0


def test_model_swap_is_added_and_removed(base: dict) -> None:
    new = copy.deepcopy(base)
    component = _component(new, "gpt-4.1-2024-08-06")
    component["name"] = "gpt-5-2026-01-01"
    result = diff_boms(base, new)
    models = result.kind("model")
    assert "gpt-5-2026-01-01" in models.added
    assert "gpt-4.1-2024-08-06" in models.removed


def test_tool_risk_increase_is_a_change(base: dict) -> None:
    new = copy.deepcopy(base)
    component = _component(new, "lookup_ticket")
    for entry in component["properties"]:
        if entry["name"] == "aibom:risk":
            entry["value"] = "high"
    result = diff_boms(base, new)
    changes = [c for c in result.all_changes() if c.field == "aibom:risk"]
    assert any(c.name == "lookup_ticket" and c.after == "high" for c in changes)
    assert result.risk_increases()


def test_prompt_hash_change_is_detected(base: dict) -> None:
    new = copy.deepcopy(base)
    prompt = next(
        c for c in new["components"]
        if c["type"] == "data" and any(d.get("classification") == "prompt" for d in c.get("data", []))
    )
    prompt["hashes"] = [{"alg": "SHA-256", "content": "0" * 64}]
    result = diff_boms(base, new)
    assert result.kind("prompt").changed


def test_new_provider_is_detected(base: dict) -> None:
    new = copy.deepcopy(base)
    new.setdefault("services", []).append(
        {
            "bom-ref": "provider:mistral",
            "name": "mistral",
            "x-trust-boundary": "external",
            "properties": [{"name": "aibom:role", "value": "model-provider"}],
        }
    )
    result = diff_boms(base, new)
    assert "mistral" in result.new_providers()


# --- gates --------------------------------------------------------------------


def test_gate_any_change_trips_on_a_real_change(base: dict) -> None:
    new = copy.deepcopy(base)
    _component(new, "lookup_ticket")["name"] = "lookup_ticket_v2"
    result = diff_boms(base, new)
    with pytest.raises(DiffGateError):
        check_gates(result, ["any-change"])


def test_gate_new_high_risk_trips_for_a_new_tool(base: dict) -> None:
    new = copy.deepcopy(base)
    new["components"].append(
        {
            "type": "library",
            "bom-ref": "tool:wire_transfer",
            "name": "wire_transfer",
            "properties": [
                {"name": "aibom:kind", "value": "tool"},
                {"name": "aibom:risk", "value": "high"},
            ],
        }
    )
    result = diff_boms(base, new)
    with pytest.raises(DiffGateError):
        check_gates(result, ["new-high-risk"])


def test_gate_risk_increase_ignores_a_risk_decrease(base: dict) -> None:
    new = copy.deepcopy(base)
    component = _component(new, "issue_refund")
    for entry in component["properties"]:
        if entry["name"] == "aibom:risk":
            entry["value"] = "low"
    result = diff_boms(base, new)
    check_gates(result, ["risk-increase"])  # must not raise


def test_gate_unknown_name_is_an_error(base: dict) -> None:
    result = diff_boms(base, base)
    with pytest.raises(DiffGateError):
        check_gates(result, ["no-such-gate"])


# --- rendering ----------------------------------------------------------------


def test_markdown_renders_release_notes(base: dict) -> None:
    new = copy.deepcopy(base)
    _component(new, "lookup_ticket")["name"] = "lookup_ticket_v2"
    text = render_diff_markdown(diff_boms(base, new))
    assert "lookup_ticket" in text
    assert text.startswith("#") or text.lstrip().startswith("#")


def test_text_render_says_no_changes(base: dict) -> None:
    text = render_diff_text(diff_boms(base, base))
    assert "no changes" in text.lower()


def test_diff_dict_is_json_serialisable(base: dict) -> None:
    new = copy.deepcopy(base)
    _component(new, "lookup_ticket")["name"] = "lookup_ticket_v2"
    payload = diff_boms(base, new).as_dict()
    json.dumps(payload)
    assert payload["counts"]["added"] >= 1 and payload["counts"]["removed"] >= 1
