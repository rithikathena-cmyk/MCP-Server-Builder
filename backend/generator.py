import inspect
from pathlib import Path

from backend import readonly
from backend.config import settings

# Anchor paths to the project root so generation works regardless of the
# current working directory (Path("templates/...") would depend on CWD).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "templates" / "mcp_template.py"
OUTPUT_DIR = PROJECT_ROOT / "generated_servers"


def _readonly_block() -> str:
    """Return the source of the read-only guard, embedded verbatim.

    Copying the canonical `backend.readonly` module into every generated server
    keeps the guard's logic identical to what the test suite covers, while
    keeping the generated file self-contained (no import back into the project).
    """
    return inspect.getsource(readonly).strip()


def generate_server(config: dict, port: int) -> Path:
    """Render the read-only MCP server for `config` on `port`.

    The generated file contains NO credentials — the connection string is
    supplied at runtime via the MCP_DB_URL environment variable. The server runs
    over HTTP at http://<bind_host>:<port>/mcp.
    """

    OUTPUT_DIR.mkdir(exist_ok=True)

    server_name = config["database"].replace(" ", "_")
    output = OUTPUT_DIR / f"{server_name}_server.py"

    template = TEMPLATE.read_text(encoding="utf-8")
    template = template.replace("{READONLY_BLOCK}", _readonly_block())
    template = template.replace("{SERVER_NAME}", server_name)
    template = template.replace("{MCP_HOST}", settings.mcp_bind_host)
    template = template.replace("{PORT}", str(port))

    # Always UTF-8 — Path.write_text defaults to the platform codepage (cp1252
    # on Windows), which would corrupt any non-ASCII byte in the generated file.
    output.write_text(template, encoding="utf-8")

    return output
