"""Thin MCP client used to call a deployed generated server's `run_query` tool.

Shared by `backend.routes.build` (the manual `/api/query` endpoint) and
`backend.routes.ask` (the agentic loop) — both talk to the deployed server
the same way, so there is exactly one place that knows the FastMCP client API.
"""

import json

from fastmcp import Client


async def run_query(url: str, sql: str) -> dict:
    """Call the deployed MCP server's run_query tool and return its dict result."""
    async with Client(url) as client:
        result = await client.call_tool("run_query", {"sql": sql})
    data = result.data
    if data is None:
        data = json.loads(result.content[0].text)
    return data
