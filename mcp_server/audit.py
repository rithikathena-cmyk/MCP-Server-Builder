"""Structured audit logging for query execution.

One JSON line per query attempt: the natural-language question (if any), the
SQL that was submitted, whether it was allowed, why (if not), how long it
took, and how many rows came back. Never receives or logs credentials — only
question/SQL/counts/timing ever flow into `record()`, and `_redact()` is
applied to every text field as a second line of defense in case an error
message happens to embed a connection string.

Stdlib-only (json/pathlib) so this module can be embedded verbatim into every
generated MCP server (see backend/generator.py), the same way
`sql_validator.py` is — audit coverage must hold for every access path to a
deployed server (including a host application connecting directly), not just
requests proxied through `backend/routes/build.py`.
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Matches the password in a DB URL (scheme://user:PASSWORD@host) or an
# MCP_DB_URL=... assignment, in case a stray message embeds one. Kept as a
# private copy (rather than importing backend.logging_config) so this module
# stays dependency-free and embeddable verbatim.
_URL_CRED = re.compile(r"(://[^:/@\s]+:)([^@/\s]+)(@)")
_ENV_URL = re.compile(r"(MCP_DB_URL=)(\S+)")


def _redact(text: str) -> str:
    text = _URL_CRED.sub(r"\1***\3", text)
    text = _ENV_URL.sub(r"\1***", text)
    return text


def record(
    log_path: Optional[str],
    *,
    question: Optional[str] = None,
    sql: str = "",
    allowed: bool = False,
    reason_code: str = "",
    duration_ms: float = 0.0,
    row_count: int = 0,
    error: Optional[str] = None,
) -> None:
    """Append one audit record.

    Writes to `log_path` (creating parent directories as needed) if set,
    otherwise to stderr. Never raises — a broken audit log must not break
    query execution.
    """
    entry = {
        "ts": time.time(),
        "question": _redact(question) if question else None,
        "sql": _redact(sql or ""),
        "allowed": allowed,
        "reason_code": reason_code,
        "duration_ms": round(duration_ms, 2),
        "row_count": row_count,
        "error": _redact(error) if error else None,
    }
    line = json.dumps(entry)
    try:
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line, file=sys.stderr)
    except Exception:
        pass
