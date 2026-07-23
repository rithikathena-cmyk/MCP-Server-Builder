"""Secrets must never survive into a log line."""

from backend.logging_config import redact


def test_redacts_url_password():
    assert redact("mysql+pymysql://user:secret@host/db") == "mysql+pymysql://user:***@host/db"


def test_redacts_password_with_special_chars():
    out = redact("connecting postgresql+psycopg2://u:p%40ss@h:5432/d now")
    assert "p%40ss" not in out
    assert "://u:***@h" in out


def test_redacts_env_assignment():
    out = redact("launching with MCP_DB_URL=mysql://u:hunter2@h/d")
    assert "hunter2" not in out


def test_plain_text_untouched():
    assert redact("deployed server=demo id=abc123 rows=5") == "deployed server=demo id=abc123 rows=5"
