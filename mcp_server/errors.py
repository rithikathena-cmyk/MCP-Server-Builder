"""Generic, user-facing error classification.

Raw driver/SQLAlchemy exception text can contain hostnames, internal paths, or
other infrastructure detail that shouldn't reach the UI or an API response.
This module maps exceptions to a small, closed set of categories with a fixed,
friendly message per category — the caller decides what to log (with the raw
exception, for debugging) and what to return to the user (always the friendly
message, never `str(exc)`).

Stdlib-only so `classify_execution_error` can be embedded verbatim into every
generated server alongside `sql_validator.py` and `audit.py` (see
`backend/generator.py`).
"""

_CONNECTION_MESSAGES = {
    "auth_failed": "Authentication failed. Please check the username and password and try again.",
    "unknown_database": "The specified database could not be found. Please verify the database name and try again.",
    "host_unreachable": "Could not reach the database host. Please check the host address, port, and network/firewall settings.",
    "timeout": "The connection attempt timed out. Please verify the host is reachable and try again.",
    "ssl_error": "A TLS/SSL error occurred while connecting. Please check your SSL/TLS configuration and try again.",
    "unknown": "Could not connect to the database. Please verify your connection details and try again.",
}

_EXECUTION_MESSAGES = {
    "timeout": "The query took too long to run. Please refine your request (add filters or narrow the scope) and try again.",
    "permission": "The query could not be completed due to a permissions issue.",
    "unknown": "The query could not be completed. Please check your request and try again.",
}


def _fingerprint(exc: Exception) -> str:
    return f"{type(exc).__name__} {exc}".lower()


def classify_connection_error(exc: Exception) -> tuple[str, str]:
    """Return (category, friendly_message) for a connection/test-connection failure.

    Never return `str(exc)` to a caller-facing surface — log the original
    exception separately if you need the detail for debugging.
    """
    text = _fingerprint(exc)

    if any(k in text for k in (
        "access denied", "authentication failed", "password authentication failed",
        "login failed", "1045", "28p01", "auth",
    )):
        category = "auth_failed"
    elif any(k in text for k in (
        "unknown database", "database \"", "does not exist", "1049", "invalid catalog name",
    )):
        category = "unknown_database"
    elif any(k in text for k in ("ssl", "certificate", "tls", "cert verify")):
        category = "ssl_error"
    elif any(k in text for k in ("timed out", "timeout")):
        category = "timeout"
    elif any(k in text for k in (
        "name or service not known", "nodename nor servname", "connection refused",
        "could not connect", "can't connect", "getaddrinfo failed", "no route to host",
        "10061", "111", "unreachable",
    )):
        category = "host_unreachable"
    else:
        category = "unknown"

    return category, _CONNECTION_MESSAGES[category]


def classify_execution_error(exc: Exception) -> str:
    """Return a friendly message for a query-execution failure (post-connect)."""
    text = _fingerprint(exc)

    if any(k in text for k in (
        "timeout", "max_execution_time", "statement timeout", "query execution was interrupted",
        "1317", "3024", "lock wait timeout",
    )):
        return _EXECUTION_MESSAGES["timeout"]
    if any(k in text for k in ("denied", "permission", "privilege")):
        return _EXECUTION_MESSAGES["permission"]
    return _EXECUTION_MESSAGES["unknown"]
