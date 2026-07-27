"""Unit tests for mcp_server/sql_validator.py, focused on multi-database
scoping: a deployment spanning more than one database must reject any
unqualified table reference, and qualified references outside its configured
set — while a single-database deployment keeps behaving exactly as before."""

from mcp_server.sql_validator import validate_sql


def test_single_database_unqualified_table_is_allowed():
    result = validate_sql("SELECT * FROM parts", dialect="mysql", allowed_databases=["hr_db"])
    assert result.allowed is True


def test_single_database_qualified_same_database_is_allowed():
    result = validate_sql("SELECT * FROM hr_db.parts", dialect="mysql", allowed_databases=["hr_db"])
    assert result.allowed is True


def test_single_database_qualified_other_database_is_denied():
    result = validate_sql("SELECT * FROM logistics_db.parts", dialect="mysql", allowed_databases=["hr_db"])
    assert result.allowed is False
    assert result.reason_code == "cross_database_denied"


def test_multi_database_unqualified_table_is_ambiguous():
    result = validate_sql(
        "SELECT * FROM employees", dialect="mysql", allowed_databases=["hr_db", "logistics_db"]
    )
    assert result.allowed is False
    assert result.reason_code == "ambiguous_database"


def test_multi_database_qualified_allowed_table_is_allowed():
    result = validate_sql(
        "SELECT * FROM hr_db.employees", dialect="mysql", allowed_databases=["hr_db", "logistics_db"]
    )
    assert result.allowed is True


def test_multi_database_qualified_disallowed_table_is_denied():
    result = validate_sql(
        "SELECT * FROM finance_db.employees", dialect="mysql", allowed_databases=["hr_db", "logistics_db"]
    )
    assert result.allowed is False
    assert result.reason_code == "cross_database_denied"


def test_multi_database_join_across_allowed_databases_is_allowed():
    sql = (
        "SELECT e.name, s.status FROM hr_db.employees e "
        "JOIN logistics_db.shipments s ON e.id = s.employee_id"
    )
    result = validate_sql(sql, dialect="mysql", allowed_databases=["hr_db", "logistics_db"])
    assert result.allowed is True


def test_restricted_system_schema_still_blocked_regardless_of_allowlist():
    result = validate_sql(
        "SELECT * FROM information_schema.tables", dialect="mysql", allowed_databases=["hr_db", "logistics_db"]
    )
    assert result.allowed is False
    assert result.reason_code == "metadata_blocked"


def test_no_allowed_databases_configured_permits_any_qualified_table():
    # allowed_databases=None (or empty) means "no restriction" — used only by
    # the is_read_only() back-compat wrapper, never by a real deployment.
    result = validate_sql("SELECT * FROM anything.parts", dialect="mysql", allowed_databases=None)
    assert result.allowed is True
