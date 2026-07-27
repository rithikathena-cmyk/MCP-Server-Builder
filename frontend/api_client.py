"""HTTP client for the FastAPI backend (backend/main.py), plus the in-process
backend bootstrap used for single-container hosting (e.g. Streamlit Community
Cloud, where only one process is available)."""

import os
import socket
import threading
import time
from urllib.parse import urlparse

import requests
import streamlit as st

API_URL = os.environ.get("MCP_API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 30  # seconds — generous enough for connect + generate + deploy

_parsed = urlparse(API_URL)
API_HOST = _parsed.hostname or "127.0.0.1"
API_PORT = _parsed.port or 8000


def _api_is_up() -> bool:
    try:
        with socket.create_connection((API_HOST, API_PORT), timeout=0.4):
            return True
    except OSError:
        return False


@st.cache_resource(show_spinner="Starting backend service...")
def ensure_backend() -> str:
    """Start the FastAPI backend in-process (daemon thread) exactly once.

    Single-container hosting (e.g. Streamlit Community Cloud) runs only one
    process, so we launch uvicorn here instead of as a separate service. If a
    backend is already listening (local dev with a separate `uvicorn`), reuse
    it. `@st.cache_resource` guarantees this runs once per Streamlit server.
    """
    if _api_is_up():
        return "external"

    import uvicorn

    from backend.main import app as api_app

    def _run():
        # uvicorn skips signal handlers off the main thread, so this is safe.
        uvicorn.Server(
            uvicorn.Config(api_app, host="127.0.0.1", port=API_PORT, log_level="warning")
        ).run()

    threading.Thread(target=_run, daemon=True, name="mcp-backend").start()

    for _ in range(60):  # wait up to ~15s for the server to accept connections
        if _api_is_up():
            return "in-process"
        time.sleep(0.25)
    return "timeout"


def bridge_secrets_to_env() -> None:
    """Copy ANTHROPIC_API_KEY from Streamlit secrets into the process environment
    so the in-process backend (and the Anthropic client it holds) can read it.
    On Streamlit Community Cloud, adding the key under Settings -> Secrets is
    the way to provide it; this is what makes that reach the backend.
    """
    try:
        if not os.environ.get("ANTHROPIC_API_KEY") and "ANTHROPIC_API_KEY" in st.secrets:
            os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:  # no secrets file present (normal in local dev)
        pass


class APIError(Exception):
    """Raised when the FastAPI backend is unreachable or returns an error."""


def _post(path: str, json: dict | None = None):
    try:
        resp = requests.post(f"{API_URL}{path}", json=json, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as exc:
        raise APIError(
            f"Cannot reach the API at {API_URL}. Start it with:\n"
            "    uvicorn backend.main:app --port 8000 --reload"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise APIError(f"API request failed: {exc}") from exc


def api_test_connection(config: dict) -> dict:
    return _post("/api/test-connection", config)


def api_discover_schemas(config: dict) -> tuple[list, str | None]:
    """Returns (schemas, error) without raising — called mid-wizard, before a
    connection is known-good, so a failure here is shown inline, not fatal."""
    try:
        resp = requests.post(f"{API_URL}/api/discover-schemas", json=config, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        return [], str(exc)
    if resp.status_code == 200:
        return resp.json().get("schemas", []), None
    return [], resp.text


def api_deploy(config: dict) -> dict:
    return _post("/api/deploy", config)


def api_register(deployment_id: str) -> dict:
    return _post(f"/api/register/{deployment_id}")


def api_query(deployment_id: str, sql: str) -> dict:
    return _post("/api/query", {"deployment_id": deployment_id, "sql": sql})


def api_ask(deployment_id: str, question: str, history: list | None = None) -> dict:
    return _post(
        "/api/ask",
        {
            "deployment_id": deployment_id,
            "question": question,
            "history": history or [],
        },
    )


def api_stop(deployment_id: str) -> None:
    try:
        _post(f"/api/stop/{deployment_id}")
    except APIError:
        pass


def fetch_tables(deployment_id: str, db_type: str, databases: list[str]) -> list[str]:
    """Returns table names — fully qualified as `database.table` when more
    than one database is in scope, plain `table` otherwise."""
    multi = len(databases) > 1
    if db_type in ("MySQL", "TiDB"):
        in_list = ", ".join(f"'{d}'" for d in databases)
        sql = (
            "SELECT table_schema, table_name FROM information_schema.tables "
            f"WHERE table_schema IN ({in_list}) AND table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name;"
        )
    elif db_type == "PostgreSQL":
        sql = "SELECT 'public' AS table_schema, table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"
    elif db_type == "SQL Server":
        sql = "SELECT 'dbo' AS table_schema, table_name FROM information_schema.tables WHERE table_schema = 'dbo' AND table_type = 'BASE TABLE' ORDER BY table_name;"
    else:
        sql = "SELECT '' AS table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' ORDER BY table_name;"

    try:
        res = api_query(deployment_id, sql)
        if res.get("success"):
            tables = []
            for row in res.get("rows", []):
                schema = row.get("table_schema") or row.get("TABLE_SCHEMA") or ""
                name = row.get("table_name") or row.get("TABLE_NAME") or row.get("Table_Name")
                if name:
                    tables.append(f"{schema}.{name}" if multi and schema else name)
            return tables
    except Exception:
        pass
    return []
