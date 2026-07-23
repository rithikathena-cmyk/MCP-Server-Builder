"""Read-only guard — the security-critical logic that protects every server."""

import pytest

from backend.readonly import is_read_only

ALLOWED = [
    "SELECT 1",
    "select * from parts",
    "SELECT a, b FROM t WHERE x = 1 ORDER BY a LIMIT 10",
    "   SELECT 1   ",
    "WITH c AS (SELECT 1 AS n) SELECT * FROM c",
    "SELECT COUNT(*) FROM information_schema.tables",
]

REFUSED = [
    "INSERT INTO t (a) VALUES (1)",
    "UPDATE t SET a = 1 WHERE id = 2",
    "DELETE FROM t WHERE id = 1",
    "DROP TABLE t",
    "CREATE TABLE t (a INT)",
    "ALTER TABLE t ADD COLUMN c INT",
    "TRUNCATE TABLE t",
    "GRANT ALL ON t TO u",
    "SELECT 1; DROP TABLE t",          # stacked
    "UPDATE t SET a=1; SELECT 1",       # stacked, write first
    "",                                  # empty
    "   ",                               # whitespace only
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_select_allowed(sql):
    assert is_read_only(sql) is True


@pytest.mark.parametrize("sql", REFUSED)
def test_non_select_refused(sql):
    assert is_read_only(sql) is False
