"""The agentic "Ask your data" chat endpoint — an alternative to the manual
`/api/query` path in `backend.routes.build` for step 6.

Every request is first split and screened by `backend.intents.split_intents`
— metadata/write/unrelated/prompt-injection sub-questions are refused there
and never reach the agent loop below. Each surviving business-question intent
is then answered independently: Claude is given a single `run_query` tool
backed by the deployed MCP server, and because that tool routes through the
read-only server, the agent can never write no matter what SQL it generates —
`split_intents` is a second, earlier gate on top of that hard guarantee, not
a replacement for it.
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import deployments
from backend.config import settings
from backend.intents import REJECTION_MESSAGES, split_intents
from backend.logging_config import get_logger
from backend.mcp_client import run_query
from backend.prompts import MODEL, RUN_QUERY_TOOL, build_system_prompt

log = get_logger("mcp.api")
router = APIRouter()

# -------------------------------
# Optional agentic assistant (Claude)
# -------------------------------
# The AI "ask your data" feature is optional: it works only when the anthropic
# SDK is installed and ANTHROPIC_API_KEY is configured. Everything else runs
# without it.
try:
    from anthropic import AsyncAnthropic

    _ANTHROPIC_AVAILABLE = True
except Exception:  # noqa: BLE001
    AsyncAnthropic = None  # type: ignore
    _ANTHROPIC_AVAILABLE = False

_anthropic_client = None  # cached AsyncAnthropic instance


def get_anthropic():
    """Return (client, error). Client is cached; error explains why it's absent."""
    global _anthropic_client
    if not _ANTHROPIC_AVAILABLE:
        return None, "The 'anthropic' package is not installed on the API server."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, (
            "ANTHROPIC_API_KEY is not set on the API server. Set it and restart the "
            "backend to enable the AI assistant."
        )
    if _anthropic_client is None:
        try:
            _anthropic_client = AsyncAnthropic()
        except Exception:  # noqa: BLE001
            return None, "Failed to initialise the Anthropic client."
    return _anthropic_client, None


# -------------------------------
# Schemas
# -------------------------------
class ChatTurn(BaseModel):
    role: str = Field(..., examples=["user", "assistant"])
    content: str


class AskRequest(BaseModel):
    deployment_id: str
    question: str
    # Prior plain-text turns of the conversation, oldest first, so the assistant
    # answers follow-ups with context. Tool-call turns are NOT replayed — only the
    # user questions and the assistant's final answers.
    history: list[ChatTurn] = Field(default_factory=list)


class AskResult(BaseModel):
    success: bool
    answer: Optional[str] = None
    queries: list = []  # the SELECTs the agent chose to run
    message: Optional[str] = None


# -------------------------------
# Agent loop
# -------------------------------
async def _run_agent_loop(client, system: str, url: str, messages: list[dict]) -> tuple[Optional[str], list[str], Optional[str]]:
    """Run the run_query agent loop to completion for one already-screened question.

    Returns (answer, queries, error_message) — exactly one of answer/error_message
    is set on return.
    """
    queries: list[str] = []
    for _ in range(8):  # bound the agentic loop
        resp = await client.messages.create(
            model="claude-opus-4-8",
            max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=system,
            tools=[RUN_QUERY_TOOL],
            messages=messages,
        )

        if resp.stop_reason == "refusal":
            return None, queries, "The assistant declined this request."

        if resp.stop_reason == "tool_use":
            # Preserve the full assistant turn (thinking + tool_use blocks).
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use" and block.name == "run_query":
                    sql = block.input.get("sql", "")
                    queries.append(sql)
                    try:
                        data = await run_query(url, sql)
                    except Exception as exc:  # noqa: BLE001
                        data = {"success": False, "message": f"Query failed: {exc}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(data)[:20000],  # cap oversized results
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # end_turn (or anything else) — extract the final answer text.
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        return answer, queries, None

    return None, queries, "Reached the reasoning-step limit before finishing."


@router.post("/api/ask", response_model=AskResult)
async def api_ask(req: AskRequest):
    """Agentic — Claude answers a natural-language question about the data."""
    entry = deployments.ACTIVE.get(req.deployment_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown deployment_id")

    client, err = get_anthropic()
    if client is None:
        return AskResult(success=False, message=err)

    meta = entry["meta"]
    url = meta["url"]
    history_msgs = [{"role": turn.role, "content": turn.content} for turn in req.history]

    try:
        intents = await split_intents(
            req.question, history_msgs, client,
            model=MODEL, max_intents=settings.max_intents_per_prompt,
        )
    except Exception as exc:  # noqa: BLE001 - never fall back to the unfiltered question
        log.error("intent classification error dep=%s: %s", req.deployment_id, exc)
        return AskResult(success=False, message=f"Could not process this request: {exc}")

    if not intents:
        return AskResult(success=False, message="I couldn't understand that as a question about the data.")

    accepted = [i for i in intents if i.type == "business_query"]
    rejected = [i for i in intents if i.type != "business_query"]

    if not accepted:
        message = " ".join(
            REJECTION_MESSAGES.get(i.reason, REJECTION_MESSAGES["other"]) for i in rejected
        )
        log.warning("ask fully rejected dep=%s reasons=%s", req.deployment_id, [i.reason for i in rejected])
        return AskResult(success=False, message=message)

    system = build_system_prompt(meta["db_type"], meta["database"], meta.get("schema"))
    all_queries: list[str] = []
    answers: list[str] = []

    try:
        for intent in accepted:
            messages = list(history_msgs) + [{"role": "user", "content": intent.text}]
            answer, queries, error = await _run_agent_loop(client, system, url, messages)
            all_queries.extend(queries)
            if error:
                return AskResult(success=False, queries=all_queries, message=error)
            answers.append(f"**{intent.text}**\n{answer}" if len(accepted) > 1 else answer)
    except Exception as exc:  # noqa: BLE001 - surface API/transport errors cleanly
        log.error("ask error dep=%s: %s", req.deployment_id, exc)
        return AskResult(success=False, queries=all_queries, message=f"AI assistant error: {exc}")

    final_answer = "\n\n".join(answers)
    if rejected:
        notes = " ".join(REJECTION_MESSAGES.get(i.reason, REJECTION_MESSAGES["other"]) for i in rejected)
        final_answer += f"\n\n_Note: {notes}_"

    log.info("ask ok dep=%s intents=%d/%d queries=%d",
              req.deployment_id, len(accepted), len(intents), len(all_queries))
    return AskResult(success=True, answer=final_answer, queries=all_queries)
