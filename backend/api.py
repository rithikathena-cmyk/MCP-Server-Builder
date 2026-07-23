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
Database connection strings are injected into each server via an environment
variable and never written to disk.

Run with:
    python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import socket
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastmcp import Client
from pydantic import BaseModel, Field

from backend.config import settings
from backend.connection import build_connection_string, test_connection
from backend.deploy import MCPDeployment
from backend.generator import generate_server
from backend.logging_config import configure_logging, get_logger

log = get_logger("mcp.api")


# -------------------------------
# In-memory deployment registry
# -------------------------------
# deployment_id -> {"deployment": MCPDeployment, "meta": {...}}
_deployments: dict[str, dict] = {}


def _stop_all() -> None:
    """Terminate and forget every tracked deployment."""
    for entry in _deployments.values():
        entry["deployment"].stop()
    _deployments.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("MCP Server Builder API starting (port range %s-%s)",
             settings.port_range_start, settings.port_range_end)
    yield
    if _deployments:
        log.info("Shutdown: stopping %d active deployment(s)", len(_deployments))
    _stop_all()


app = FastAPI(
    title="MCP Server Builder API",
    description="Generate, deploy and register secure read-only MCP servers from SQL databases.",
    version="2.1.0",
    lifespan=lifespan,
)


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
# Helpers
# -------------------------------
def _find_free_port() -> int:
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
    """Write registered data sources to disk for host-app discovery (no secrets)."""
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
    settings.registry_file.parent.mkdir(exist_ok=True)
    settings.registry_file.write_text(json.dumps({"mcpServers": registered}, indent=2))


# -------------------------------
# Health / readiness
# -------------------------------
@app.get("/api/health")
def health():
    """Liveness — the process is up and serving."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness — the service can accept work."""
    return {"ready": True, "active_deployments": len(_deployments)}


# -------------------------------
# Build flow
# -------------------------------
@app.post("/api/test-connection", response_model=TestResult)
def api_test_connection(config: DBConfig):
    """Step 2 — validate credentials with a single read-only `SELECT 1`."""
    cfg = config.model_dump()
    success, message = test_connection(cfg)
    log.info("test-connection db=%s host=%s user=%s ssl=%s -> %s",
             cfg["database"], cfg["host"], cfg["username"], cfg["ssl"],
             "ok" if success else "FAILED")
    return TestResult(success=success, message=message)


@app.post("/api/deploy", response_model=DeployResult)
def api_deploy(config: DBConfig):
    """Steps 3 & 4 — generate a read-only MCP server for `config` and launch it."""
    cfg = config.model_dump()

    success, message = test_connection(cfg)
    if not success:
        log.warning("deploy aborted: connection test failed for db=%s", cfg["database"])
        return DeployResult(success=False, message=message)

    server_name = cfg["database"].replace(" ", "_")
    _stop_matching(server_name)

    port = _find_free_port()
    server_path = generate_server(cfg, port)
    db_url = build_connection_string(cfg)  # injected via env — never written to disk

    deployment = MCPDeployment(host=settings.mcp_bind_host, port=port)
    deployment.deploy(server_path, db_url)

    running = deployment.wait_until_ready(timeout=settings.deploy_ready_timeout)
    if not running:
        _, err = deployment.process.communicate()
        log.error("deploy failed: server=%s did not start", server_name)
        return DeployResult(
            success=False,
            message="Server failed to start.",
            server_path=str(server_path),
            server_name=server_name,
            running=False,
            log=err or "Server did not become ready in time.",
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
    log.info("deployed server=%s id=%s url=%s", server_name, deployment_id, deployment.url)

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
    log.info("registered server=%s with host application", meta["server_name"])

    return RegisterResult(
        registered=True,
        server_name=meta["server_name"],
        config=config,
        config_text=json.dumps(config, indent=2),
    )


@app.post("/api/query", response_model=QueryResult)
async def api_query(req: QueryRequest):
    """Step 6 — run a read-only query THROUGH the deployed MCP server."""
    entry = _deployments.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    url = entry["meta"]["url"]
    try:
        async with Client(url) as client:
            result = await client.call_tool("run_query", {"sql": req.sql})
    except Exception as exc:  # noqa: BLE001 - surface any client/transport error
        log.error("query transport error dep=%s: %s", req.deployment_id, exc)
        return QueryResult(success=False, message=f"Query failed: {exc}")

    data = result.data
    if data is None:
        try:
            data = json.loads(result.content[0].text)
        except Exception:  # noqa: BLE001
            return QueryResult(success=False, message="Unparseable server response.")

    ok = bool(data.get("success"))
    rows = data.get("rows", [])
    if ok:
        log.info("query ok dep=%s rows=%d", req.deployment_id, len(rows))
    else:
        # A refused write is expected behaviour — record it for audit.
        log.warning("query refused/error dep=%s", req.deployment_id)

    return QueryResult(
        success=ok,
        rows=rows,
        row_count=data.get("row_count", len(rows)),
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
    log.info("stopped deployment id=%s", deployment_id)
    return {"stopped": True}
