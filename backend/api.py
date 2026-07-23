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
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastmcp import Client
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT, settings
from backend.connection import build_connection_string, test_connection
from backend.deploy import MCPDeployment
from backend.generator import generate_server
from backend.logging_config import configure_logging, get_logger

# Load secrets from a local .env into the process environment so ANTHROPIC_API_KEY
# (and any other keys) are picked up without exporting them by hand. The .env file
# is git-ignored — keys never reach the repo. On Streamlit Community Cloud, use the
# Secrets UI instead (it exposes values as environment variables too).
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # noqa: BLE001 - dotenv is optional
    pass

log = get_logger("mcp.api")

# -------------------------------
# Optional agentic assistant (Claude)
# -------------------------------
# The AI "ask your data" feature is optional: it works only when the anthropic
# SDK is installed and ANTHROPIC_API_KEY is configured. Everything else runs
# without it.
try:
    from anthropic import AsyncAnthropic

    _ANTHROPIC_AVAILABLE = True
except Exception:  # noqa: BLE001
    AsyncAnthropic = None  # type: ignore
    _ANTHROPIC_AVAILABLE = False

_anthropic_client = None  # cached AsyncAnthropic instance


def _get_anthropic():
    """Return (client, error). Client is cached; error explains why it's absent."""
    global _anthropic_client
    if not _ANTHROPIC_AVAILABLE:
        return None, "The 'anthropic' package is not installed on the API server."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, (
            "ANTHROPIC_API_KEY is not set on the API server. Set it and restart the "
            "backend to enable the AI assistant."
        )
    if _anthropic_client is None:
        try:
            _anthropic_client = AsyncAnthropic()
        except Exception:  # noqa: BLE001
            return None, "Failed to initialise the Anthropic client."
    return _anthropic_client, None


# Tool Claude is given: the ONLY way it can touch the database. It routes through
# the deployed MCP server, so the read-only guard gates every query the agent runs.
_RUN_QUERY_TOOL = {
    "name": "run_query",
    "description": (
        "Execute a single read-only SQL SELECT against the connected database and "
        "return the rows as JSON. Only SELECT is allowed — INSERT/UPDATE/DELETE/DDL "
        "are refused. Use information_schema to discover tables and columns when unsure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single SELECT statement."}
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
}


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


class AskRequest(BaseModel):
    deployment_id: str
    question: str


class AskResult(BaseModel):
    success: bool
    answer: Optional[str] = None
    queries: list = []  # the SELECTs the agent chose to run
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


async def _mcp_run_query(url: str, sql: str) -> dict:
    """Call the deployed MCP server's run_query tool and return its dict result."""
    async with Client(url) as client:
        result = await client.call_tool("run_query", {"sql": sql})
    data = result.data
    if data is None:
        data = json.loads(result.content[0].text)
    return data


@app.post("/api/query", response_model=QueryResult)
async def api_query(req: QueryRequest):
    """Step 6 — run a read-only query THROUGH the deployed MCP server."""
    entry = _deployments.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    try:
        data = await _mcp_run_query(entry["meta"]["url"], req.sql)
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


@app.post("/api/ask", response_model=AskResult)
async def api_ask(req: AskRequest):
    """Agentic — Claude answers a natural-language question about the data.

    Claude is given a single `run_query` tool backed by the deployed MCP server.
    It explores the schema and runs SELECTs to build an answer. Because the tool
    routes through the read-only server, the agent can never write, no matter
    what SQL it generates.
    """
    entry = _deployments.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    client, err = _get_anthropic()
    if client is None:
        return AskResult(success=False, message=err)

    meta = entry["meta"]
    url = meta["url"]
    system = (
        f"You are a data analyst assistant connected to a READ-ONLY {meta['db_type']} "
        f"database named '{meta['database']}'. Answer the user's question by exploring "
        "the schema and running SELECT queries with the run_query tool. When unsure of "
        "table or column names, query information_schema first. Only SELECT is possible; "
        "never attempt writes. Base every statement on actual query results — do not "
        "fabricate data. When you have enough information, answer concisely in plain language."
    )
    messages = [{"role": "user", "content": req.question}]
    queries: list[str] = []

    try:
        for _ in range(8):  # bound the agentic loop
            resp = await client.messages.create(
                model="claude-opus-4-8",
                max_tokens=8000,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                system=system,
                tools=[_RUN_QUERY_TOOL],
                messages=messages,
            )

            if resp.stop_reason == "refusal":
                return AskResult(success=False, message="The assistant declined this request.")

            if resp.stop_reason == "tool_use":
                # Preserve the full assistant turn (thinking + tool_use blocks).
                messages.append({"role": "assistant", "content": resp.content})
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use" and block.name == "run_query":
                        sql = block.input.get("sql", "")
                        queries.append(sql)
                        try:
                            data = await _mcp_run_query(url, sql)
                        except Exception as exc:  # noqa: BLE001
                            data = {"success": False, "message": f"Query failed: {exc}"}
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(data)[:20000],  # cap oversized results
                        })
                messages.append({"role": "user", "content": tool_results})
                continue

            # end_turn (or anything else) — extract the final answer text.
            answer = "".join(b.text for b in resp.content if b.type == "text").strip()
            log.info("ask ok dep=%s queries=%d", req.deployment_id, len(queries))
            return AskResult(success=True, answer=answer, queries=queries)

        return AskResult(
            success=False,
            answer=None,
            queries=queries,
            message="Reached the reasoning-step limit before finishing.",
        )
    except Exception as exc:  # noqa: BLE001 - surface API/transport errors cleanly
        log.error("ask error dep=%s: %s", req.deployment_id, exc)
        return AskResult(success=False, queries=queries, message=f"AI assistant error: {exc}")


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
