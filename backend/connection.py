from urllib.parse import quote_plus

import certifi
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from backend.logging_config import get_logger
from mcp_server.errors import classify_connection_error
from mcp_server.sql_validator import DIALECT_BY_DB_TYPE, RESTRICTED_SCHEMAS

log = get_logger("mcp.connection")

# Bounded connection attempts so an unreachable/blackholed host fails fast with
# a clear message instead of hanging the request indefinitely.
_CONNECT_TIMEOUT_SECONDS = 10


def validate_config(config: dict) -> list[str]:
    """Structural pre-flight checks, before any network round-trip.

    Returns a list of human-readable problems; empty means the config is
    well-formed enough to attempt a connection. Never inspects or echoes the
    password back in any message.
    """
    errors: list[str] = []

    db_type = config.get("db_type")
    if db_type not in DIALECT_BY_DB_TYPE:
        errors.append(f"Unsupported database type: {db_type!r}.")

    host = config.get("host")
    if not host or not str(host).strip():
        errors.append("Host is required.")

    port = config.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        errors.append("Port must be a number between 1 and 65535.")

    if not config.get("username") or not str(config["username"]).strip():
        errors.append("Username is required.")
    if not config.get("password"):
        errors.append("Password is required.")

    database = config.get("database")
    if database and db_type in DIALECT_BY_DB_TYPE:
        dialect = DIALECT_BY_DB_TYPE[db_type]
        restricted = RESTRICTED_SCHEMAS.get(dialect, set())
        if str(database).strip().lower() in restricted:
            errors.append(
                f"'{database}' is a system schema and cannot be used as the "
                "business database for a deployment."
            )

    return errors


def build_connection_string(config: dict) -> str:
    db_type = config["db_type"]

    # URL-encode credentials — cloud DB passwords (PlanetScale, Neon, TiDB Cloud)
    # frequently contain characters that would otherwise break the URL.
    user = quote_plus(str(config["username"]))
    pwd = quote_plus(str(config["password"]))
    host = config["host"]
    port = config["port"]
    database = config.get("database")
    use_ssl = bool(config.get("ssl", False))

    if db_type in ("MySQL", "TiDB"):
        base = f"mysql+pymysql://{user}:{pwd}@{host}:{port}"
        url = f"{base}/{database}" if database else base
        params = [f"connect_timeout={_CONNECT_TIMEOUT_SECONDS}"]
        if use_ssl:
            # PlanetScale / TiDB Cloud require TLS. certifi's CA bundle validates
            # their publicly-trusted certificates on any platform.
            params.append(f"ssl_ca={quote_plus(certifi.where())}")
        return f"{url}?{'&'.join(params)}"

    elif db_type == "PostgreSQL":
        base = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}"
        url = f"{base}/{database}" if database else base
        params = [f"connect_timeout={_CONNECT_TIMEOUT_SECONDS}"]
        if use_ssl:
            params.append("sslmode=require")
        return f"{url}?{'&'.join(params)}"

    elif db_type == "SQL Server":
        base = f"mssql+pyodbc://{user}:{pwd}@{host}:{port}"
        url = f"{base}/{database}" if database else base
        return (
            f"{url}?driver=ODBC+Driver+17+for+SQL+Server"
            f"&timeout={_CONNECT_TIMEOUT_SECONDS}"
        )

    else:
        raise ValueError("Unsupported database type.")


def test_connection(config: dict):
    """Attempt a `SELECT 1` and report success/failure with a friendly message.

    Never returns raw driver/SQLAlchemy exception text — that can contain
    hostnames or internal detail. The original exception is logged (redacted)
    for debugging; only a generic, categorized message is returned.
    """
    structural_errors = validate_config(config)
    if structural_errors:
        return False, " ".join(structural_errors)

    try:
        connection_string = build_connection_string(config)

        engine = create_engine(connection_string)

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return True, "Connection Successful"

    except (SQLAlchemyError, Exception) as e:  # noqa: BLE001 - classify everything
        log.warning("connection test failed: %s", e)
        _, message = classify_connection_error(e)
        return False, message


def discover_schemas(config: dict) -> list:
    """Return the business (non-system) database/schema names from the connection.

    The config may omit the 'database' key; discovery works without it. System
    schemas (mysql/sys/information_schema/performance_schema/pg_catalog/...)
    are filtered out here — a user picking a database to deploy against should
    never be offered one that the query-time validator would refuse anyway.
    """
    connection_string = build_connection_string(config)
    engine = create_engine(connection_string)
    dialect = DIALECT_BY_DB_TYPE.get(config.get("db_type"), "")
    restricted = RESTRICTED_SCHEMAS.get(dialect, set())
    with engine.connect() as conn:
        # Generic query works for MySQL/TiDB/PostgreSQL; for SQL Server it also returns databases.
        result = conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        return [row[0] for row in result if row[0].lower() not in restricted]


def describe_schema(config: dict, max_tables: int = 50, max_columns: int = 30) -> dict:
    """Return {table_name: [column_names]} for the deployment's business database.

    This is the ONE privileged, deploy-time introspection of table/column
    names, run directly with the deploying operator's credentials — it is NOT
    exposed as a query-time capability. `run_query` (mcp_server/sql_validator.py)
    refuses any information_schema access at request time, so the "Ask your
    data" agent needs its schema knowledge handed to it up front instead of
    discovering it live; this is how. Results are capped so a very wide
    database can't blow up the system prompt built from them.
    """
    database = config.get("database")
    if not database:
        return {}

    connection_string = build_connection_string(config)
    engine = create_engine(connection_string)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = :database ORDER BY table_name, ordinal_position"
            ),
            {"database": database},
        )
        schema: dict = {}
        for table_name, column_name in result:
            columns = schema.setdefault(table_name, [])
            if len(schema) > max_tables:
                schema.pop(table_name, None)
                break
            if len(columns) < max_columns:
                columns.append(column_name)
        return schema
