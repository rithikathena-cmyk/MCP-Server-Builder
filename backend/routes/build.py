"""Build-flow routes — steps 2, 3/4, 5, and the manual query path of step 6:

    2. test connection       -> POST /api/test-connection
    3. generate server code  -> POST /api/deploy  (generate + launch)
    4. deploy server         -> POST /api/deploy
    5. register with host    -> POST /api/register/{id}
    6. run read-only queries -> POST /api/query

Generated servers run over HTTP; this module connects to them as an MCP client
(via `backend.mcp_client`) to execute SELECT queries. INSERT/UPDATE/DELETE are
refused by the server itself, not here. Database connection strings are
injected into each server via an environment variable and never written to
disk. The agentic chat path (step 6 alternative) lives in `backend.routes.ask`.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import deployments
from backend.config import settings
from backend.connection import build_connection_string, describe_schema, discover_schemas, test_connection
from backend.deploy import MCPDeployment
from backend.generator import generate_server, sanitize_server_name
from backend.logging_config import get_logger
from backend.mcp_client import run_query

log = get_logger("mcp.api")
router = APIRouter()


# -------------------------------
# Schemas
# -------------------------------
class DBConfig(BaseModel):
    db_type: str = Field(..., examples=["MySQL"])
    host: str = Field(..., examples=["127.0.0.1"])
    port: int = Field(..., ge=1, le=65535, examples=[3306])
    database: Optional[str] = Field(None, description="Database name (optional when discovery is used)", examples=["permit_system"])
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
# Routes
# -------------------------------
@router.post("/api/test-connection", response_model=TestResult)
def api_test_connection(config: DBConfig):
    """Step 2 — validate credentials with a single read-only `SELECT 1`."""
    cfg = config.model_dump()
    success, message = test_connection(cfg)
    log.info("test-connection db=%s host=%s user=%s ssl=%s -> %s",
              cfg.get("database"), cfg["host"], cfg["username"], cfg["ssl"],
              "ok" if success else "FAILED")
    return TestResult(success=success, message=message)


@router.post("/api/discover-schemas")
def api_discover_schemas(config: DBConfig):
    """Return a list of available schemas/databases for the given connection config."""
    cfg = config.model_dump()
    try:
        schemas = discover_schemas(cfg)
        return {"success": True, "schemas": schemas}
    except Exception as exc:
        log.error("discover_schemas failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/deploy", response_model=DeployResult)
def api_deploy(config: DBConfig):
    """Steps 3 & 4 — generate a read-only MCP server for `config` and launch it."""
    cfg = config.model_dump()

    success, message = test_connection(cfg)
    if not success:
        log.warning("deploy aborted: connection test failed for db=%s", cfg.get("database", "<none>"))
        return DeployResult(success=False, message=message)

    server_name = sanitize_server_name(cfg.get("database", "auto"))
    deployments.stop_matching(server_name)

    port = deployments.find_free_port()
    server_path = generate_server(cfg, port)
    db_url = build_connection_string(cfg)  # injected via env — never written to disk

    # Best-effort, deploy-time-only schema introspection for the "Ask your
    # data" agent (see backend/prompts/) — never exposed as a query-time
    # capability; a failure here must not block the deployment itself.
    try:
        schema = describe_schema(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("schema introspection failed for db=%s: %s", cfg.get("database"), exc)
        schema = {}

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
    deployments.ACTIVE[deployment_id] = {
        "deployment": deployment,
        "meta": {
            "deployment_id": deployment_id,
            "server_name": server_name,
            "database": cfg.get("database"),
            "db_type": cfg["db_type"],
            "url": deployment.url,
            "server_path": str(server_path),
            "registered": False,
            "schema": schema,
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


@router.post("/api/register/{deployment_id}", response_model=RegisterResult)
def api_register(deployment_id: str):
    """Step 5 — register the running server with the host application."""
    entry = deployments.ACTIVE.get(deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    meta = entry["meta"]
    config = deployments.host_config(meta["server_name"], meta["url"])

    meta["registered"] = True
    deployments.persist_registry()
    log.info("registered server=%s with host application", meta["server_name"])

    return RegisterResult(
        registered=True,
        server_name=meta["server_name"],
        config=config,
        config_text=json.dumps(config, indent=2),
    )


@router.post("/api/query", response_model=QueryResult)
async def api_query(req: QueryRequest):
    """Step 6 — run a read-only query THROUGH the deployed MCP server."""
    entry = deployments.ACTIVE.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    try:
        data = await run_query(entry["meta"]["url"], req.sql)
    except Exception as exc:  # noqa: BLE001 - surface any client/transport error
        log.error("query transport error dep=%s: %s", req.deployment_id, exc)
        return QueryResult(success=False, message=f"Query failed: {exc}")

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


@router.get("/api/status/{deployment_id}")
def api_status(deployment_id: str):
    entry = deployments.ACTIVE.get(deployment_id)
    if entry is None:
        return {"exists": False, "running": False}
    return {"exists": True, "running": entry["deployment"].is_running()}


@router.post("/api/stop/{deployment_id}")
def api_stop(deployment_id: str):
    entry = deployments.ACTIVE.get(deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")
    entry["deployment"].stop()
    del deployments.ACTIVE[deployment_id]
    deployments.persist_registry()
    log.info("stopped deployment id=%s", deployment_id)
    return {"stopped": True}
