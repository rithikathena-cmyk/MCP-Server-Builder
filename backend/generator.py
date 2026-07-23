from pathlib import Path

from backend.connection import build_connection_string

# Anchor paths to the project root so generation works regardless of the
# current working directory (Path("templates/...") would depend on CWD).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "templates" / "mcp_template.py"
OUTPUT_DIR = PROJECT_ROOT / "generated_servers"


def generate_server(config: dict, port: int):
    """Render the read-only MCP server template for `config` on `port`.

    The generated server runs over HTTP so a host application (or the builder)
    can connect to it at http://127.0.0.1:<port>/mcp and issue SELECT queries.
    """

    OUTPUT_DIR.mkdir(exist_ok=True)

    server_name = config["database"].replace(" ", "_")

    filename = f"{server_name}_server.py"

    output = OUTPUT_DIR / filename

    template = TEMPLATE.read_text()

    template = template.replace("{SERVER_NAME}", server_name)
    template = template.replace("{CONNECTION_STRING}", build_connection_string(config))
    template = template.replace("{PORT}", str(port))

    output.write_text(template)

    return output
