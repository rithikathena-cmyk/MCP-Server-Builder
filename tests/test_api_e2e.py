"""End-to-end: deploy a real generated server (SQLite) and drive the API.

Covers steps 5-6 and the write-refusal guarantee through the actual FastAPI
endpoints and a live MCP client round-trip — the same path production uses.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import deployments
from backend.deploy import MCPDeployment
from backend.generator import generate_server
from backend.intents import REJECTION_MESSAGES
from backend.main import app
from backend.routes import ask as ask_routes

client = TestClient(app)


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

    port = deployments.find_free_port()
    server_path = generate_server({"database": "quality"}, port)
    dep = MCPDeployment(host="127.0.0.1", port=port)
    dep.deploy(server_path, f"sqlite:///{db.as_posix()}")
    assert dep.wait_until_ready(timeout=20), "generated server did not start"

    dep_id = f"test-{port}"
    deployments.ACTIVE[dep_id] = {
        "deployment": dep,
        "meta": {
            "deployment_id": dep_id, "server_name": "quality", "database": "quality",
            "db_type": "SQLite", "url": dep.url, "server_path": str(server_path),
            "registered": False,
        },
    }
    yield dep_id, db

    dep.stop()
    deployments.ACTIVE.pop(dep_id, None)
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
])
def test_writes_are_refused(deployed, sql):
    dep_id, _ = deployed
    r = client.post("/api/query", json={"deployment_id": dep_id, "sql": sql}).json()
    assert r["success"] is False
    assert "read-only" in (r["message"] or "")


def test_stacked_statement_is_refused(deployed):
    dep_id, _ = deployed
    r = client.post("/api/query", json={
        "deployment_id": dep_id,
        "sql": "SELECT 1; DROP TABLE parts",
    }).json()
    assert r["success"] is False
    assert "single query" in (r["message"] or "")


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


# -------------------------------------------------------------------------
# /api/ask — the intent gate (backend/intents.py) must run before the agent
# loop touches the database at all, and the agent loop itself must still
# answer legitimate questions through the real deployed server.
# -------------------------------------------------------------------------
class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeAskMessages:
    """Answers both the classify_intents call and the run_query agent loop,
    branching on which tool the caller offered — same shape as a real
    Anthropic client from the callers' point of view."""

    def __init__(self, intents, sql=None, final_answer=""):
        self._intents = intents
        self._sql = sql
        self._final_answer = final_answer
        self._asked_query = False

    async def create(self, **kwargs):
        tool_names = {t["name"] for t in kwargs.get("tools", [])}
        if "classify_intents" in tool_names:
            block = _Block("tool_use", name="classify_intents", input={"intents": self._intents})
            return _Resp("tool_use", [block])

        if self._sql and not self._asked_query:
            self._asked_query = True
            block = _Block("tool_use", name="run_query", input={"sql": self._sql}, id="toolu_1")
            return _Resp("tool_use", [block])

        return _Resp("end_turn", [_Block("text", text=self._final_answer)])


class _FakeAskClient:
    def __init__(self, intents, sql=None, final_answer=""):
        self.messages = _FakeAskMessages(intents, sql=sql, final_answer=final_answer)


def test_ask_rejects_write_request_before_touching_db(deployed, monkeypatch):
    dep_id, _ = deployed
    fake = _FakeAskClient([{"text": "delete part 1", "type": "rejected", "reason": "write_request"}])
    monkeypatch.setattr(ask_routes, "get_anthropic", lambda: (fake, None))

    r = client.post("/api/ask", json={"deployment_id": dep_id, "question": "delete part 1"}).json()
    assert r["success"] is False
    assert r["message"] == REJECTION_MESSAGES["write_request"]


def test_ask_answers_business_query_through_agent_loop(deployed, monkeypatch):
    dep_id, _ = deployed
    fake = _FakeAskClient(
        [{"text": "how many parts passed?", "type": "business_query"}],
        sql="SELECT COUNT(*) AS c FROM parts WHERE result = 'PASS'",
        final_answer="2 parts passed.",
    )
    monkeypatch.setattr(ask_routes, "get_anthropic", lambda: (fake, None))

    r = client.post("/api/ask", json={"deployment_id": dep_id, "question": "how many parts passed?"}).json()
    assert r["success"] is True
    assert r["answer"] == "2 parts passed."
    assert r["queries"] == ["SELECT COUNT(*) AS c FROM parts WHERE result = 'PASS'"]
