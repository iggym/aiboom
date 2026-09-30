"""MCP-heavy fixture: several MCP servers, several risky tools."""

from __future__ import annotations

import os

import litellm

client = litellm
MODEL = "gpt-4o"

mcp_servers = [
    "filesystem",
    "github",
    "postgres",
    "slack",
    "brave-search",
    "fetch",
    "puppeteer",
    "memory",
]


def run_shell_command(command: str) -> str:
    """Execute a shell command on the host."""
    import subprocess

    return subprocess.run(command, shell=True, capture_output=True, text=True).stdout


def rotate_api_key(service: str) -> dict[str, str]:
    """Rotate the API key for a service and return the new secret."""
    return {"service": service, "key": os.environ.get("NEW_KEY", "")}


def post_to_channel(channel: str, text: str) -> None:
    """Post a message to a Slack channel."""
    print(channel, text)
