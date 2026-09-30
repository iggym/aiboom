"""MCP client wiring for the support agent."""

from __future__ import annotations

import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/srv/support-kb"],
    env={"KB_ROOT": os.environ.get("KB_ROOT", "/srv/support-kb")},
)


async def open_crm_session() -> ClientSession:
    read, write = await stdio_client(server_params).__aenter__()
    return await ClientSession(read, write).__aenter__()
