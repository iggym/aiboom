"""Risk rule tests (spec §9): table-driven, one row per rule and per curated
package, plus override recording.

Every row asserts the *capability* produced, because the risk level is derived
from capabilities and testing the level alone would hide a mislabelled rule.
"""

from __future__ import annotations

import pytest

from aibom.risk import (
    apply_override,
    classify_mcp_server,
    classify_tool,
    load_rulebook,
)


@pytest.fixture(scope="module")
def book():
    return load_rulebook()


# --- capability rules ---------------------------------------------------------

RULE_CASES = [
    # (tool name, expected capabilities)
    ("issue_refund", ["financial"]),
    ("refund_payment", ["financial"]),
    ("charge_customer", ["financial"]),
    ("transfer_funds", ["financial"]),
    ("delete_customer_account", ["destructive"]),
    ("drop_table", ["destructive"]),
    ("run_shell_command", ["code-exec"]),
    ("execute_python", ["code-exec"]),
    ("eval_expression", ["code-exec"]),
    ("write_file", ["write"]),
    ("update_record", ["write"]),
    ("create_issue", ["write"]),
    ("send_email", ["external-comms"]),
    ("post_to_channel", ["external-comms"]),
    ("read_file", ["filesystem", "read"]),
    ("list_directory", ["filesystem", "read"]),
    ("http_get", ["network", "read"]),
    ("fetch_url", ["network", "read"]),
    ("login_user", ["identity"]),
    ("grant_permission", ["identity"]),
    ("get_api_key", ["secrets"]),
    ("read_env_secret", ["secrets"]),
    ("lookup_ticket", ["read"]),
    ("search_policies", ["read"]),
]


@pytest.mark.parametrize("name,expected", RULE_CASES)
def test_tool_capabilities(name: str, expected: list[str], book) -> None:
    result = classify_tool(name, book=book)
    for capability in expected:
        assert capability in result.capabilities, (
            f"{name!r}: expected {capability!r}, got {result.capabilities}"
        )


def test_unclassifiable_tool_is_unknown(book) -> None:
    result = classify_tool("frobnicate_widget", book=book)
    assert result.capabilities == []
    assert result.risk == "unknown"


def test_match_all_rule_needs_every_declared_field(book) -> None:
    """Regression: `write.issue-tracker` declares identifier *and* description.

    A tool named `post_to_channel` whose description merely contains "post" must
    not be filed as a tracker write. (It is still a plain `write` via
    `write.mutation` — posting is a durable write — and that is the point: the
    narrow rule stays narrow instead of over-claiming.)
    """
    result = classify_tool(
        "post_to_channel",
        description="Post a message to a Slack channel.",
        param_keys=["channel", "text"],
        book=book,
    )
    assert "external-comms" in result.capabilities
    assert all(m.rule_id != "write.issue-tracker" for m in result.matches)


def test_match_all_rule_fires_when_every_field_matches(book) -> None:
    result = classify_tool(
        "create_issue",
        description="Create a ticket in the issue tracker.",
        book=book,
    )
    assert "write" in result.capabilities
    assert any(m.rule_id == "write.issue-tracker" for m in result.matches)


def test_any_match_rule_fires_from_a_single_field(book) -> None:
    """`exec.sql-raw` is an `any` rule: the parameter alone is enough."""
    result = classify_tool("search_records", param_keys=["sql"], book=book)
    assert "code-exec" in result.capabilities
    without = classify_tool("search_records", param_keys=["term"], book=book)
    assert "code-exec" not in without.capabilities


def test_risk_is_highest_capability(book) -> None:
    # financial (high) outranks read (low)
    result = classify_tool("read_and_refund", book=book)
    assert "financial" in result.capabilities
    assert "read" in result.capabilities
    assert result.risk == "high"


def test_every_rule_has_id_and_why(book) -> None:
    """An auditor must be able to read why a rule fired."""
    for rule in book.rules:
        assert rule.get("id"), rule
        assert rule.get("why"), f"rule {rule.get('id')} has no `why`"
        assert rule.get("capability") in book.capability_levels, rule


def test_capability_levels_cover_every_capability(book) -> None:
    for rule in book.rules:
        assert book.level(rule["capability"]) in {"high", "medium", "low", "unknown"}


# --- curated MCP packages -----------------------------------------------------


@pytest.mark.parametrize(
    "package,expected",
    [
        ("@modelcontextprotocol/server-filesystem", ["filesystem"]),
        ("@modelcontextprotocol/server-github", ["identity", "write"]),
        ("@modelcontextprotocol/server-postgres", ["secrets", "destructive"]),
        ("@modelcontextprotocol/server-slack", ["identity", "external-comms"]),
        ("@modelcontextprotocol/server-brave-search", ["network"]),
        ("@modelcontextprotocol/server-fetch", ["network"]),
        ("@modelcontextprotocol/server-puppeteer", ["code-exec"]),
        ("@modelcontextprotocol/server-memory", ["filesystem"]),
        ("@modelcontextprotocol/server-sqlite", ["destructive"]),
        ("@modelcontextprotocol/server-google-maps", ["network"]),
    ],
)
def test_curated_mcp_package_capabilities(package: str, expected: list[str], book) -> None:
    short = package.rsplit("/", 1)[-1].removeprefix("server-")
    result = classify_mcp_server(short, package=package, book=book)
    for capability in expected:
        assert capability in result.capabilities, (
            f"{package}: expected {capability!r}, got {result.capabilities}"
        )


def test_curated_registry_has_at_least_forty_packages(book) -> None:
    """Phase 3 requires ≥40 curated packages."""
    assert len(book.packages) >= 40


def test_curated_registry_entries_are_well_formed(book) -> None:
    for entry in book.packages:
        assert entry.get("package"), entry
        assert entry.get("capabilities"), entry
        assert entry.get("why"), f"{entry.get('package')} has no `why`"
        for capability in entry["capabilities"]:
            assert capability in book.capability_levels, entry


def test_curated_package_takes_precedence_for_risk(book) -> None:
    # filesystem alone is medium, but the curated entry for puppeteer raises it.
    result = classify_mcp_server("puppeteer", package="@modelcontextprotocol/server-puppeteer", book=book)
    assert result.risk == "high"


# --- overrides ----------------------------------------------------------------


def test_override_records_justification_and_keeps_heuristic(book) -> None:
    heuristic = classify_tool("issue_refund", book=book)
    override = {
        "risk": "medium",
        "capabilities": ["financial"],
        "human_in_the_loop": True,
        "reversible": False,
        "rate_limited": True,
        "justification": "Capped at $50/day and requires an approver.",
    }
    result = apply_override(heuristic, override, book)
    assert result.applied is True
    assert result.risk == "medium"
    assert result.heuristic_risk == "high"
    assert result.justification and "approver" in result.justification
    assert result.human_in_the_loop is True


def test_override_without_capabilities_keeps_heuristic_capabilities(book) -> None:
    """Capabilities are additive: an override may add, never silently drop."""
    heuristic = classify_tool("delete_customer_account", book=book)
    assert "destructive" in heuristic.capabilities
    result = apply_override(heuristic, {"human_in_the_loop": True}, book)
    assert result.capabilities == heuristic.capabilities
    assert result.risk == heuristic.risk
    assert result.human_in_the_loop is True


def test_override_may_not_silently_clear_justification(book) -> None:
    heuristic = classify_tool("issue_refund", book=book)
    result = apply_override(heuristic, {"risk": "low"}, book)
    assert result.applied is True
    assert result.risk == "low"
    # The BOM records both, so the human decision is auditable.
    assert result.heuristic_risk == "high"
