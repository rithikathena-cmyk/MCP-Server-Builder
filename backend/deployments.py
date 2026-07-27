"""In-memory registry of active MCP server deployments.

Single process-lifetime store: deployment_id -> {"deployment": MCPDeployment,
"meta": {...}}. Shared by `backend.routes.build` (writes it on deploy/register/
stop) and `backend.routes.ask` (reads it to find the URL for a deployment_id).
"""

import json
import socket

from fastapi import HTTPException

from backend.config import settings

# deployment_id -> {"deployment": MCPDeployment, "meta": {...}}
ACTIVE: dict[str, dict] = {}


def find_free_port() -> int:
    """Return a TCP port on the bind host that is currently free to bind."""
    for port in range(settings.port_range_start, settings.port_range_end):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((settings.mcp_bind_host, port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise HTTPException(status_code=503, detail="No free port available for a new server")


def stop_matching(server_name: str) -> None:
    """Retire any existing deployment for the same data source (avoid dupes)."""
    stale = [
        dep_id
        for dep_id, entry in ACTIVE.items()
        if entry["meta"]["server_name"] == server_name
    ]
    for dep_id in stale:
        ACTIVE[dep_id]["deployment"].stop()
        del ACTIVE[dep_id]


def stop_all() -> None:
    """Terminate and forget every tracked deployment."""
    for entry in ACTIVE.values():
        entry["deployment"].stop()
    ACTIVE.clear()


def host_config(server_name: str, url: str) -> dict:
    """Build the host-application registration entry (Claude-Desktop style)."""
    return {"mcpServers": {server_name: {"url": url, "transport": "http"}}}


def persist_registry() -> None:
    """Write registered data sources to disk for host-app discovery (no secrets)."""
    registered = {
        entry["meta"]["server_name"]: {
            "url": entry["meta"]["url"],
            "transport": "http",
            "database": entry["meta"]["database"],
            "db_type": entry["meta"]["db_type"],
        }
        for entry in ACTIVE.values()
        if entry["meta"].get("registered")
    }
    settings.registry_file.parent.mkdir(exist_ok=True)
    settings.registry_file.write_text(json.dumps({"mcpServers": registered}, indent=2))
