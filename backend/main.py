"""FastAPI entry point for the MCP Server Builder backend.

Implements the six-step build flow behind a small REST API so the frontend is
fully decoupled from the build logic:

    1. collect params        -> (frontend form)
    2. test connection       -> POST /api/test-connection
    3. generate server code  -> POST /api/deploy  (generate + launch)
    4. deploy server         -> POST /api/deploy
    5. register with host    -> POST /api/register/{id}
    6. run read-only queries -> POST /api/query  (or the chat loop, POST /api/ask)

Route handlers live in backend/routes/:
  - backend.routes.build — steps 2, 3/4, 5, and the manual query path of step 6
  - backend.routes.ask   — the agentic "Ask your data" chat, an alternative step 6

Run with:
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import deployments
from backend.config import PROJECT_ROOT, settings
from backend.logging_config import configure_logging, get_logger
from backend.routes import ask, build

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("MCP Server Builder API starting (port range %s-%s)",
              settings.port_range_start, settings.port_range_end)
    yield
    if deployments.ACTIVE:
        log.info("Shutdown: stopping %d active deployment(s)", len(deployments.ACTIVE))
    deployments.stop_all()


app = FastAPI(
    title="MCP Server Builder API",
    description="Generate, deploy and register secure read-only MCP servers from SQL databases.",
    version="2.1.0",
    lifespan=lifespan,
)

app.include_router(build.router)
app.include_router(ask.router)


@app.get("/api/health")
def health():
    """Liveness — the process is up and serving."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness — the service can accept work."""
    return {"ready": True, "active_deployments": len(deployments.ACTIVE)}
