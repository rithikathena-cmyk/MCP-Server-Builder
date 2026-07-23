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


settings = Settings()
