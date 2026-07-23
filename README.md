# 🛠️ MCP Server Builder

Generate, deploy, and register a **read-only** MCP server from user-provided
database parameters — no code required. A non-engineer connects a new data
source end to end in minutes; every write (`INSERT`/`UPDATE`/`DELETE`) is refused.

## The six-step flow
1. **Collect** connection parameters (user ID, password, server/IP, port) — password masked.
2. **Test** the connection (`SELECT 1`) with a live status indicator; clear re-prompt on failure.
3. **Generate** a SELECT-only MCP server (sqlglot-validated).
4. **Deploy** it (runs over HTTP).
5. **Register** it with the host application (writes `generated_servers/registry.json`).
6. **Query** your data through the new server — writes are refused.

## Architecture
- `frontend/app.py` — Streamlit wizard UI (talks to the backend over HTTP).
- `backend/api.py` — FastAPI service (test / deploy / register / query).
- `backend/{connection,generator,deploy}.py` + `templates/mcp_template.py` — build logic.

## Run locally

Two processes (recommended for development):

```bash
python -m uvicorn backend.api:app --port 8000 --reload
streamlit run frontend/app.py
```

Or a single process — the frontend auto-starts the backend in a background
thread if nothing is already listening on port 8000:

```bash
streamlit run frontend/app.py
```

## Deploy free on Streamlit Community Cloud

The app is single-container ready: `frontend/app.py` launches the FastAPI
backend **in-process** (a daemon thread, started once via `@st.cache_resource`),
so the whole six-step flow runs inside the one process Streamlit Cloud gives you.

1. Push this repo to **public GitHub**.
2. Go to <https://share.streamlit.io> → **New app** → select the repo.
3. Set **Main file path** to `frontend/app.py`.
4. Deploy. You get a public `*.streamlit.app` URL.

`requirements.txt` (Python deps) and `packages.txt` (system `unixodbc`) are
installed automatically.

### Hosting notes / limits (free tier)
- **Only publicly-reachable databases work.** The container can't reach a DB on
  your laptop (`127.0.0.1`). Use a cloud DB — e.g. free-tier
  **Neon**/**Supabase** (Postgres) or **TiDB Cloud**/**PlanetScale** (MySQL).
- **SQL Server** needs Microsoft's ODBC driver, which Streamlit Cloud can't
  install — use MySQL/PostgreSQL/TiDB for the hosted build (or self-host for MSSQL).
- The app **sleeps when idle** and storage is **ephemeral**: generated servers
  and `registry.json` don't persist across restarts (they regenerate on next use).
- The registered MCP endpoints are **container-internal** (`localhost`) — reachable
  by this platform (which is the host application for querying), not by an
  external Claude Desktop. That matches the scenario: teams connect and query
  *through the platform*.
