"""FastAPI service for the MCP Server Builder.

Implements the six-step build flow behind a small REST API so the frontend is
fully decoupled from the build logic:

    1. collect params        -> (frontend form)
    2. test connection       -> POST /api/test-connection
    3. generate server code  -> POST /api/deploy  (generate + launch)
    4. deploy server         -> POST /api/deploy
    5. register with host    -> POST /api/register/{id}
    6. run read-only queries -> POST /api/query

Generated servers run over HTTP; the API connects to them as an MCP client to
execute SELECT queries. INSERT/UPDATE/DELETE are refused by the server itself.

Run with:
    python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import socket
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastmcp import Client
from pydantic import BaseModel, Field

from backend.connection import test_connection
from backend.generator import generate_server, OUTPUT_DIR
from backend.deploy import MCPDeployment

app = FastAPI(
    title="MCP Server Builder API",
    description="Generate, deploy and register secure read-only MCP servers from SQL databases.",
    version="2.0.0",
)

# Where registered data sources are persisted so a host application could
# discover them. Represents "registration with the host application".
REGISTRY_FILE = OUTPUT_DIR / "registry.json"
PORT_RANGE = (8100, 8999)


# -------------------------------
# Schemas
# -------------------------------
class DBConfig(BaseModel):
    db_type: str = Field(..., examples=["MySQL"])
    host: str = Field(..., examples=["127.0.0.1"])
    port: int = Field(..., ge=1, le=65535, examples=[3306])
    database: str = Field(..., examples=["permit_system"])
    username: str
    password: str
    ssl: bool = Field(default=False, description="Require TLS/SSL (PlanetScale, TiDB Cloud, Neon, etc.)")


class TestResult(BaseModel):
    success: bool
    message: str


class DeployResult(BaseModel):
    success: bool
    message: str
    server_path: Optional[str] = None
    deployment_id: Optional[str] = None
    server_name: Optional[str] = None
    url: Optional[str] = None
    running: bool = False
    log: Optional[str] = None


class RegisterResult(BaseModel):
    registered: bool
    server_name: str
    config: dict
    config_text: str


class QueryRequest(BaseModel):
    deployment_id: str
    sql: str


class QueryResult(BaseModel):
    success: bool
    rows: list = []
    row_count: int = 0
    message: Optional[str] = None


# -------------------------------
# In-memory deployment registry
# -------------------------------
# deployment_id -> {"deployment": MCPDeployment, "meta": {...}}
_deployments: dict[str, dict] = {}


def _find_free_port() -> int:
    """Return a TCP port on 127.0.0.1 that is currently free to bind."""
    for port in range(*PORT_RANGE):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("No free port available in range")


def _stop_matching(server_name: str) -> None:
    """Retire any existing deployment for the same data source (avoid dupes)."""
    stale = [
        dep_id
        for dep_id, entry in _deployments.items()
        if entry["meta"]["server_name"] == server_name
    ]
    for dep_id in stale:
        _deployments[dep_id]["deployment"].stop()
        del _deployments[dep_id]


def _host_config(server_name: str, url: str) -> dict:
    """Build the host-application registration entry (Claude-Desktop style)."""
    return {"mcpServers": {server_name: {"url": url, "transport": "http"}}}


def _persist_registry() -> None:
    """Write all registered data sources to disk for host-app discovery."""
    registered = {
        entry["meta"]["server_name"]: {
            "url": entry["meta"]["url"],
            "transport": "http",
            "database": entry["meta"]["database"],
            "db_type": entry["meta"]["db_type"],
        }
        for entry in _deployments.values()
        if entry["meta"].get("registered")
    }
    REGISTRY_FILE.write_text(json.dumps({"mcpServers": registered}, indent=2))


# -------------------------------
# Routes
# -------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "active_deployments": len(_deployments)}


@app.post("/api/test-connection", response_model=TestResult)
def api_test_connection(config: DBConfig):
    """Step 2 — validate credentials with a single read-only `SELECT 1`."""
    success, message = test_connection(config.model_dump())
    return TestResult(success=success, message=message)


@app.post("/api/deploy", response_model=DeployResult)
def api_deploy(config: DBConfig):
    """Steps 3 & 4 — generate a read-only MCP server for `config` and launch it."""
    cfg = config.model_dump()

    success, message = test_connection(cfg)
    if not success:
        return DeployResult(success=False, message=message)

    server_name = cfg["database"].replace(" ", "_")
    _stop_matching(server_name)

    port = _find_free_port()
    server_path = generate_server(cfg, port)

    deployment = MCPDeployment(host="127.0.0.1", port=port)
    deployment.deploy(server_path)

    running = deployment.wait_until_ready(timeout=12.0)
    log = None
    if not running:
        _, err = deployment.process.communicate()
        log = err or "Server did not become ready in time."
        return DeployResult(
            success=False,
            message="Server failed to start.",
            server_path=str(server_path),
            server_name=server_name,
            running=False,
            log=log,
        )

    deployment_id = uuid.uuid4().hex
    _deployments[deployment_id] = {
        "deployment": deployment,
        "meta": {
            "deployment_id": deployment_id,
            "server_name": server_name,
            "database": cfg["database"],
            "db_type": cfg["db_type"],
            "url": deployment.url,
            "server_path": str(server_path),
            "registered": False,
        },
    }

    return DeployResult(
        success=True,
        message="Connection successful",
        server_path=str(server_path),
        deployment_id=deployment_id,
        server_name=server_name,
        url=deployment.url,
        running=True,
    )


@app.post("/api/register/{deployment_id}", response_model=RegisterResult)
def api_register(deployment_id: str):
    """Step 5 — register the running server with the host application."""
    entry = _deployments.get(deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    meta = entry["meta"]
    config = _host_config(meta["server_name"], meta["url"])

    meta["registered"] = True
    _persist_registry()

    return RegisterResult(
        registered=True,
        server_name=meta["server_name"],
        config=config,
        config_text=json.dumps(config, indent=2),
    )


@app.post("/api/query", response_model=QueryResult)
async def api_query(req: QueryRequest):
    """Step 6 — run a read-only query THROUGH the deployed MCP server.

    The API acts as an MCP client, calls the server's `run_query` tool, and
    returns whatever the server returns — including its refusal for writes.
    """
    entry = _deployments.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    url = entry["meta"]["url"]
    try:
        async with Client(url) as client:
            result = await client.call_tool("run_query", {"sql": req.sql})
    except Exception as exc:  # noqa: BLE001 - surface any client/transport error
        return QueryResult(success=False, message=f"Query failed: {exc}")

    data = result.data
    if data is None:
        # Fall back to parsing the text content block.
        try:
            data = json.loads(result.content[0].text)
        except Exception:  # noqa: BLE001
            return QueryResult(success=False, message="Unparseable server response.")

    return QueryResult(
        success=bool(data.get("success")),
        rows=data.get("rows", []),
        row_count=data.get("row_count", len(data.get("rows", []))),
        message=data.get("message"),
    )


@app.get("/api/status/{deployment_id}")
def api_status(deployment_id: str):
    entry = _deployments.get(deployment_id)
    if entry is None:
        return {"exists": False, "running": False}
    return {"exists": True, "running": entry["deployment"].is_running()}


@app.post("/api/stop/{deployment_id}")
def api_stop(deployment_id: str):
    entry = _deployments.get(deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")
    entry["deployment"].stop()
    del _deployments[deployment_id]
    _persist_registry()
    return {"stopped": True}
