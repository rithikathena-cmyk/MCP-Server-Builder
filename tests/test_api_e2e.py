"""End-to-end: deploy a real generated server (SQLite) and drive the API.

Covers steps 5-6 and the write-refusal guarantee through the actual FastAPI
endpoints and a live MCP client round-trip — the same path production uses.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import api as api_mod
from backend.deploy import MCPDeployment
from backend.generator import generate_server

client = TestClient(api_mod.app)


@pytest.fixture(scope="module")
def deployed(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "quality.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE parts (id INTEGER PRIMARY KEY, name TEXT, result TEXT)")
    con.executemany(
        "INSERT INTO parts (name, result) VALUES (?, ?)",
        [("A", "PASS"), ("B", "FAIL"), ("C", "PASS")],
    )
    con.commit()
    con.close()

    port = api_mod._find_free_port()
    server_path = generate_server({"database": "quality"}, port)
    dep = MCPDeployment(host="127.0.0.1", port=port)
    dep.deploy(server_path, f"sqlite:///{db.as_posix()}")
    assert dep.wait_until_ready(timeout=20), "generated server did not start"

    dep_id = f"test-{port}"
    api_mod._deployments[dep_id] = {
        "deployment": dep,
        "meta": {
            "deployment_id": dep_id, "server_name": "quality", "database": "quality",
            "db_type": "SQLite", "url": dep.url, "server_path": str(server_path),
            "registered": False,
        },
    }
    yield dep_id, db

    dep.stop()
    api_mod._deployments.pop(dep_id, None)
    server_path.unlink(missing_ok=True)


def test_health_and_ready(deployed):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/ready").json()["ready"] is True


def test_register(deployed):
    dep_id, _ = deployed
    r = client.post(f"/api/register/{dep_id}").json()
    assert r["registered"] is True
    assert "quality" in r["config"]["mcpServers"]


def test_select_returns_rows(deployed):
    dep_id, _ = deployed
    r = client.post("/api/query", json={
        "deployment_id": dep_id,
        "sql": "SELECT name FROM parts WHERE result = 'PASS'",
    }).json()
    assert r["success"] is True
    assert r["row_count"] == 2


@pytest.mark.parametrize("sql", [
    "UPDATE parts SET result='PASS'",
    "DELETE FROM parts WHERE id=1",
    "INSERT INTO parts (name, result) VALUES ('X', 'Y')",
    "DROP TABLE parts",
    "SELECT 1; DROP TABLE parts",
])
def test_writes_are_refused(deployed, sql):
    dep_id, _ = deployed
    r = client.post("/api/query", json={"deployment_id": dep_id, "sql": sql}).json()
    assert r["success"] is False
    assert "read-only" in (r["message"] or "")


def test_data_unchanged_after_write_attempts(deployed):
    _, db = deployed
    con = sqlite3.connect(db)
    total = con.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    fails = con.execute("SELECT COUNT(*) FROM parts WHERE result='FAIL'").fetchone()[0]
    con.close()
    assert (total, fails) == (3, 1)  # nothing was inserted/updated/deleted


def test_unknown_deployment_returns_404():
    r = client.post("/api/query", json={"deployment_id": "nope", "sql": "SELECT 1"})
    assert r.status_code == 404
