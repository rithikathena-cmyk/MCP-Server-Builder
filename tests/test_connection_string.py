"""Connection-string building: SSL, URL-encoding, per-dialect correctness."""

import pytest

from backend.connection import build_connection_string

BASE = {
    "host": "gw.example.com",
    "port": 3306,
    "database": "app",
    "username": "user.name",
    "password": "p@ss/w+d=",  # deliberately special-char heavy
}


def cfg(**over):
    return {**BASE, **over}


def test_mysql_ssl_and_encoding():
    url = build_connection_string(cfg(db_type="MySQL", ssl=True))
    assert url.startswith("mysql+pymysql://")
    assert "ssl_ca=" in url
    # password must be percent-encoded, not raw
    assert "p@ss/w+d=" not in url
    assert "p%40ss%2Fw%2Bd%3D" in url


def test_mysql_no_ssl_has_no_ssl_ca():
    url = build_connection_string(cfg(db_type="MySQL", ssl=False))
    assert "ssl_ca=" not in url


def test_tidb_uses_mysql_driver_with_ssl():
    url = build_connection_string(cfg(db_type="TiDB", port=4000, ssl=True))
    assert url.startswith("mysql+pymysql://")
    assert "ssl_ca=" in url


def test_postgres_sslmode():
    url = build_connection_string(cfg(db_type="PostgreSQL", port=5432, ssl=True))
    assert url.startswith("postgresql+psycopg2://")
    assert "sslmode=require" in url


def test_sqlserver_driver():
    url = build_connection_string(cfg(db_type="SQL Server", port=1433))
    assert url.startswith("mssql+pyodbc://")
    assert "driver=ODBC+Driver+17+for+SQL+Server" in url


def test_unsupported_type_raises():
    with pytest.raises(ValueError):
        build_connection_string(cfg(db_type="Oracle"))
