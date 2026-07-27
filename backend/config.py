"""Centralised, environment-driven configuration.

Every tunable lives here instead of being scattered as literals across the
codebase, so the service can be reconfigured for different environments
(local, staging, single-container cloud) without code changes. Override any
value with an ``MCP_``-prefixed environment variable, e.g. ``MCP_API_PORT=9000``.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    # FastAPI service
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Generated MCP servers bind here (loopback only — never publicly exposed)
    mcp_bind_host: str = "127.0.0.1"
    port_range_start: int = Field(default=8100, ge=1, le=65535)
    port_range_end: int = Field(default=8999, ge=1, le=65535)

    # Deployment readiness
    deploy_ready_timeout: float = 12.0

    # Observability
    log_level: str = "INFO"

    # Where registered data sources are persisted for host-app discovery
    registry_file: Path = PROJECT_ROOT / "generated_servers" / "registry.json"

    # -------------------------------------------------------------------
    # Query validation & complexity limits (mcp_server/sql_validator.py, and
    # embedded verbatim into every generated server — see backend/generator.py)
    # -------------------------------------------------------------------
    # A SELECT with no LIMIT gets this one injected automatically.
    default_query_limit: int = 500
    # Any LIMIT above this (explicit or injected) is capped down to it; this is
    # also the hard row cap enforced at fetch time regardless of what the
    # rewritten SQL says.
    max_query_limit: int = 5000
    # Queries with more JOINs than this are refused before execution.
    max_joins: int = 6
    # Queries with subqueries/CTEs nested deeper than this are refused.
    max_subquery_depth: int = 4
    # Soft per-query execution budget, applied via a dialect-appropriate session
    # variable (e.g. MySQL/TiDB MAX_EXECUTION_TIME) before running the query.
    query_timeout_ms: int = 8000

    # -------------------------------------------------------------------
    # "Ask your data" agentic assistant (backend/routes/ask.py, backend/intents.py)
    # -------------------------------------------------------------------
    # A single natural-language prompt is split into at most this many
    # independently-validated business-question intents.
    max_intents_per_prompt: int = 5

    # -------------------------------------------------------------------
    # Audit logging — one JSON line per query attempt, embedded into every
    # generated server so direct MCP-client access is audited too, not just
    # requests proxied through this API. Never contains credentials.
    # -------------------------------------------------------------------
    audit_log_dir: Path = PROJECT_ROOT / "generated_servers" / "audit"


settings = Settings()
