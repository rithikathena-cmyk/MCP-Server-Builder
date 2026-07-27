"""Canonical SQL validation guard — the single source of truth for what SQL is
safe to execute against a connected business database.

This module is embedded verbatim (via `inspect.getsource`, see
`backend/generator.py`) into every generated MCP server, so the logic that
protects a live deployment is exactly the logic covered by the test suite —
no drift between what's tested and what runs. It is also the *only*
enforcement point: `backend/routes/build.py` never re-implements or duplicates these
checks, it only surfaces whatever a generated server's `run_query` returns.

Layered checks, in order:
  1. Parse as a single statement (blocks unparseable input and stacked
     statements like "SELECT 1; DROP TABLE t").
  2. Statement type must be a bare SELECT — every write/DDL/utility statement
     type is refused, including ones sqlglot has no dedicated class for
     (CALL, EXECUTE, RENAME TABLE all fall back to `exp.Command`; LOAD DATA
     and MySQL's `INTO OUTFILE` fail to parse outright) — both are refused.
  3. No database-structure/metadata statements (SHOW, DESCRIBE, EXPLAIN) and
     no reference to a restricted system schema or any schema other than the
     one(s) this deployment is scoped to. When a deployment spans more than
     one database, every table reference must be schema-qualified — with only
     one database, an unqualified table implicitly resolves to it, same as
     before.
  4. Complexity limits: bounded join count, bounded subquery/CTE nesting, no
     recursive CTEs, no join lacking an ON/USING condition (blocks both
     comma-joins and CROSS JOIN — i.e. Cartesian products).
  5. A LIMIT is guaranteed on the way out — injected if absent, capped if
     excessive — so no query can return an unbounded result set.
"""

from dataclasses import dataclass
from typing import Iterable, Optional

import sqlglot
from sqlglot import expressions as exp

# Statement types that are always refused outright. `validate_sql` additionally
# requires the parsed statement to be exactly `exp.Select`, so this list is
# defence-in-depth / documentation of intent rather than the only gate.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Grant, exp.Command,
)

# Statement types that reveal database structure/metadata rather than data.
_METADATA_TYPES = (exp.Show, exp.Describe)

# Schemas that are never exposed, keyed by the sqlglot dialect used to parse
# this deployment's SQL. TiDB is MySQL-wire-protocol compatible and shares the
# MySQL dialect and schema set.
RESTRICTED_SCHEMAS = {
    "mysql": {"mysql", "sys", "information_schema", "performance_schema"},
    "postgres": {"pg_catalog", "information_schema"},
    "tsql": {"sys", "information_schema"},
}

# Maps this project's DBConfig.db_type values to sqlglot dialect names.
DIALECT_BY_DB_TYPE = {
    "MySQL": "mysql",
    "TiDB": "mysql",
    "PostgreSQL": "postgres",
    "SQL Server": "tsql",
}

_MESSAGES = {
    "unparseable": "This request could not be understood as a single query. Please rephrase it.",
    "multi_statement": "Only a single query is allowed per request.",
    "write_denied": "This server is read-only. Only SELECT statements are permitted.",
    "metadata_blocked": (
        "Database structure and metadata are not available. I can only help with "
        "business-data queries."
    ),
    "cross_database_denied": "Access is restricted to the connected business database(s).",
    "ambiguous_database": (
        "This deployment spans multiple databases — every table must be fully "
        "qualified as database_name.table_name."
    ),
    "too_complex": (
        "This query is too complex to run safely (too many joins, too much "
        "nesting, or an unrestricted join). Please simplify your request."
    ),
}


@dataclass
class ValidationResult:
    allowed: bool
    sql: str  # the (possibly LIMIT-rewritten) SQL to execute when allowed
    reason_code: str
    message: str


def _reject(reason_code: str) -> ValidationResult:
    return ValidationResult(False, "", reason_code, _MESSAGES[reason_code])


def _max_select_depth(node: exp.Expression) -> int:
    """Deepest nesting of one SELECT inside another (subqueries, CTEs, IN/EXISTS)."""
    max_depth = 0
    for sel in node.find_all(exp.Select):
        depth = 0
        parent = sel.parent
        while parent is not None:
            if isinstance(parent, exp.Select):
                depth += 1
            parent = parent.parent
        max_depth = max(max_depth, depth)
    return max_depth


def _has_unrestricted_join(node: exp.Expression) -> bool:
    """True if any JOIN lacks an ON/USING condition (comma-join or CROSS JOIN)."""
    for join in node.find_all(exp.Join):
        if join.args.get("on") is None and not join.args.get("using"):
            return True
    return False


def validate_sql(
    sql: str,
    *,
    dialect: str = "mysql",
    allowed_databases: Optional[Iterable[str]] = None,
    default_limit: int = 500,
    max_limit: int = 5000,
    max_joins: int = 6,
    max_subquery_depth: int = 4,
) -> ValidationResult:
    """Validate `sql` and return the (possibly LIMIT-rewritten) SQL to execute.

    Only a single, bare SELECT against `allowed_databases` is permitted.
    `dialect` should be one of the sqlglot dialect names in
    `DIALECT_BY_DB_TYPE`'s values.

    With exactly one allowed database, an unqualified table implicitly
    resolves to it (same as always). With more than one, every table
    reference must be schema-qualified — there is no default to fall back
    to, so an unqualified table is rejected rather than guessed at.
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception:
        return _reject("unparseable")

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return _reject("multi_statement" if statements else "unparseable")

    parsed = statements[0]

    if isinstance(parsed, _METADATA_TYPES):
        return _reject("metadata_blocked")
    if isinstance(parsed, _FORBIDDEN) or not isinstance(parsed, exp.Select):
        return _reject("write_denied")
    if parsed.args.get("into") is not None:
        # e.g. SQL Server `SELECT ... INTO new_table FROM ...` creates a table.
        return _reject("write_denied")

    restricted = RESTRICTED_SCHEMAS.get(dialect, set())
    allowed_lower = {d.lower() for d in allowed_databases} if allowed_databases else set()
    multi_db = len(allowed_lower) > 1
    for table in parsed.find_all(exp.Table):
        schema = (table.db or "").lower()
        if not schema:
            if multi_db:
                return _reject("ambiguous_database")
            continue
        if schema in restricted:
            return _reject("metadata_blocked")
        if allowed_lower and schema not in allowed_lower:
            return _reject("cross_database_denied")

    if any(w.args.get("recursive") for w in parsed.find_all(exp.With)):
        return _reject("too_complex")
    if len(list(parsed.find_all(exp.Join))) > max_joins:
        return _reject("too_complex")
    if _max_select_depth(parsed) > max_subquery_depth:
        return _reject("too_complex")
    if _has_unrestricted_join(parsed):
        return _reject("too_complex")

    limit_node = parsed.args.get("limit")
    target_limit = default_limit
    if limit_node is not None:
        expr = limit_node.expression
        if isinstance(expr, exp.Literal) and expr.is_number:
            try:
                target_limit = min(int(expr.this), max_limit)
            except (TypeError, ValueError):
                target_limit = max_limit
        else:
            target_limit = max_limit
    parsed.set("limit", exp.Limit(expression=exp.Literal.number(target_limit)))

    return ValidationResult(True, parsed.sql(dialect=dialect), "ok", "")


def is_read_only(sql: str, dialect: str = "mysql") -> bool:
    """Back-compat convenience wrapper: True only for a single safe SELECT.

    Does not apply schema/database allowlisting beyond the fixed restricted-
    schema policy, complexity limits, or LIMIT rewriting — those need
    per-deployment configuration, so use `validate_sql` directly for full
    enforcement (as the generated server template does).
    """
    result = validate_sql(
        sql, dialect=dialect, allowed_databases=None,
        default_limit=10**9, max_limit=10**9,
        max_joins=10**9, max_subquery_depth=10**9,
    )
    return result.allowed
