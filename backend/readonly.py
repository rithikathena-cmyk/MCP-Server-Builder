"""Canonical read-only SQL guard.

This is the single source of truth for what counts as a safe, read-only query.
The generated MCP server embeds this exact module (copied verbatim at generation
time), so the logic that protects a deployed server is the same logic covered by
the test suite — no drift between what is tested and what runs.
"""

import sqlglot
from sqlglot import expressions as exp

# Statement types that are always refused. `is_read_only` additionally requires
# the statement to parse as a bare SELECT, so this list is defence-in-depth.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Grant,
)


def is_read_only(sql: str) -> bool:
    """True only if `sql` is a single SELECT (no writes, no DDL, no stacking)."""
    try:
        statements = sqlglot.parse(sql)
    except Exception:
        return False

    # Reject empty input and multi-statement payloads (e.g. "SELECT 1; DROP ...").
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return False

    parsed = statements[0]
    if isinstance(parsed, _FORBIDDEN):
        return False

    return isinstance(parsed, exp.Select)
