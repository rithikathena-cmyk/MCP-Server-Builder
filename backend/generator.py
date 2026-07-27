import inspect
import re
from pathlib import Path

from backend.config import settings
from mcp_server import audit, errors, sql_validator
from mcp_server.sql_validator import DIALECT_BY_DB_TYPE

# Anchor paths to the project root so generation works regardless of the
# current working directory (Path("mcp_server/...") would depend on CWD).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "mcp_server" / "template.py"
OUTPUT_DIR = PROJECT_ROOT / "generated_servers"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_server_name(raw: str) -> str:
    """Collapse `raw` into a filesystem- and Python-identifier-safe name.

    `raw` ultimately comes from a user-supplied database name; without this,
    characters like `..`/`/` could steer the generated file outside
    OUTPUT_DIR, and other punctuation could break the embedded `FastMCP(...)`
    server-name literal.
    """
    name = _SAFE_NAME.sub("_", raw.strip().replace(" ", "_")).strip("_")
    return name or "server"


def _validator_block() -> str:
    """Return the source of the SQL validation guard, embedded verbatim.

    Copying the canonical `mcp_server.sql_validator` module into every generated
    server keeps the guard's logic identical to what the test suite covers,
    while keeping the generated file self-contained (no import back into the
    project).
    """
    return inspect.getsource(sql_validator).strip()


def _audit_block() -> str:
    """Return the source of the audit logger, embedded verbatim (see above)."""
    return inspect.getsource(audit).strip()


def _errors_block() -> str:
    """Return the source of the error-classification helpers, embedded verbatim."""
    return inspect.getsource(errors).strip()


def generate_server(config: dict, port: int) -> Path:
    """Render the read-only MCP server for `config` on `port`.

    The generated file contains NO credentials — the connection string is
    supplied at runtime via the MCP_DB_URL environment variable. The server runs
    over HTTP at http://<bind_host>:<port>/mcp.
    """

    OUTPUT_DIR.mkdir(exist_ok=True)

    server_name = sanitize_server_name(config.get("database", "auto"))
    output = OUTPUT_DIR / f"{server_name}_server.py"

    dialect = DIALECT_BY_DB_TYPE.get(config.get("db_type"), "mysql")
    allowed_database = config.get("database") or ""

    template = TEMPLATE.read_text(encoding="utf-8")
    # Generation-time placeholders use a __GEN_*__ token, deliberately distinct
    # from the plain identifiers (MAX_LIMIT, QUERY_TIMEOUT_MS, ...) the template
    # also uses at runtime inside f-strings — a naive .replace() on the bare
    # names would corrupt those f-strings too.
    template = template.replace("__GEN_VALIDATOR_BLOCK__", _validator_block())
    template = template.replace("__GEN_AUDIT_BLOCK__", _audit_block())
    template = template.replace("__GEN_ERRORS_BLOCK__", _errors_block())
    template = template.replace("__GEN_SERVER_NAME__", server_name)
    template = template.replace("__GEN_MCP_HOST__", settings.mcp_bind_host)
    template = template.replace("__GEN_PORT__", str(port))
    template = template.replace("__GEN_DB_DIALECT__", repr(dialect))
    template = template.replace("__GEN_ALLOWED_DATABASE__", repr(allowed_database))
    template = template.replace("__GEN_DEFAULT_LIMIT__", str(settings.default_query_limit))
    template = template.replace("__GEN_MAX_LIMIT__", str(settings.max_query_limit))
    template = template.replace("__GEN_MAX_JOINS__", str(settings.max_joins))
    template = template.replace("__GEN_MAX_SUBQUERY_DEPTH__", str(settings.max_subquery_depth))
    template = template.replace("__GEN_QUERY_TIMEOUT_MS__", str(settings.query_timeout_ms))

    # Always UTF-8 — Path.write_text defaults to the platform codepage (cp1252
    # on Windows), which would corrupt any non-ASCII byte in the generated file.
    output.write_text(template, encoding="utf-8")

    return output
