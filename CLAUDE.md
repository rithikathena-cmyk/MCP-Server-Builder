# On-the-Fly MCP Server Builder — instructions

**Use the `mcp-server-reviewer` subagent** (`.claude/agents/mcp-server-reviewer.md`)
before deploying any file under `generated_servers/`, and after any change to
`mcp_server/sql_validator.py` — it checks the six read-only guarantees the
whole platform's safety depends on (single statement, SELECT-only, no
metadata leakage, database scoping, complexity limits, bounded results).

## Architecture

- `mcp_server/sql_validator.py` — the canonical SQL validation guard. Embedded
  verbatim (via `inspect.getsource`) into every generated server by
  `backend/generator.py`, so the logic that's tested is exactly the logic
  that runs. This is the *only* enforcement point — never re-implement or
  duplicate these checks elsewhere.
- `backend/prompts/ask.py` / `backend/prompts/intent_classifier.py` — the
  Claude-facing prompts for the "Ask your data" chat agent (`backend/routes/ask.py`)
  and the intent-classification gate that screens metadata/write/unrelated/
  prompt-injection sub-questions before they reach it.
- `generated_servers/` — MCP servers this platform generates and deploys per
  connected database; each embeds the validator above.

## Rules that must never be relaxed

- Never loosen a SQL Guard check to "make a query work" — fix the agent's SQL
  generation (`backend/prompts/`) instead, never the guard.
- The generated MCP servers are the only path to the database; the FastAPI
  backend never re-implements query execution or validation itself.

## Development

- Run tests with `pytest` (see `tests/test_intents.py`,
  `tests/test_connection_string.py`, `tests/test_logging_redaction.py`,
  `tests/test_api_e2e.py`).
