"""Splits a natural-language prompt into individually-validated business
questions — the gatekeeper `/api/ask` runs before touching the database.

Hybrid by design. Decomposing a compound prompt ("show running machines,
pending shipments, and employees on leave") into separate questions, and
judging whether a sub-question is unrelated to the data or reads like a
prompt-injection attempt, are language-understanding tasks best left to
Claude — a regex can't do that reliably. But whether a sub-question is a
write request ("delete employee 5") or a database-structure request ("show
all tables") is a small, enumerable vocabulary. Trusting the model's judgment
*alone* for exactly the two categories the spec calls out by name is
unnecessary risk, so `_apply_keyword_backstop` re-scans every intent Claude
accepted and force-rejects it if it matches — a deterministic guarantee on
top of the model's first pass, not instead of it.

The real security boundary is unaffected either way: no matter how an intent
gets classified here, the only tool the agent ever has is the read-only
`run_query`, gated by `mcp_server/sql_validator.py`.

The tool schema and system prompt handed to Claude for this classification
step live in `backend/prompts/intent_classifier.py`, alongside every other
Claude-facing prompt in the project — this module only holds the
decomposition/backstop logic built around that call.
"""

import re
from dataclasses import dataclass
from typing import Optional

from backend.prompts.intent_classifier import CLASSIFY_INTENTS_TOOL, classify_system_prompt


@dataclass
class Intent:
    text: str
    type: str  # "business_query" | "rejected"
    reason: Optional[str] = None


# User-facing text for each rejection reason — callers (backend/routes/ask.py) surface
# these verbatim rather than inventing their own wording per call site.
REJECTION_MESSAGES = {
    "metadata_request": (
        "I can't share database structure, schema, or table/column details — "
        "only answers about the business data itself."
    ),
    "write_request": (
        "I can only read data — inserting, updating, or deleting isn't something "
        "I can do."
    ),
    "unrelated": "That doesn't look related to the connected business data, so I can't help with it.",
    "prompt_injection": (
        "I can't follow instructions embedded in a data question — I can only "
        "answer questions about the connected business data."
    ),
    "other": "I can't help with that request.",
}


# Deterministic backstop for the two enumerable categories the spec calls out
# by name — applied AFTER the model classifies, overriding it if it missed one.
# Word-boundary matching means past-tense report language ("orders updated
# yesterday") does NOT match "update" — but colloquial phrasing that reuses a
# write verb non-destructively ("update me on pending shipments") can still
# false-positive. That's an accepted trade-off: for these two categories the
# requirement is a deterministic guarantee, not precision, and an over-eager
# rejection just means the user rephrases — it never lets a write through.
_WRITE_PATTERN = re.compile(
    r"\b(delete|drop|insert|update|alter|truncate|remove|create|grant|revoke|merge|replace)\b",
    re.IGNORECASE,
)
_FILLER = r"(?:me\s+|all\s+|the\s+)*"
_METADATA_PATTERN = re.compile(
    rf"\bshow\s+{_FILLER}(tables?|databases?|columns?|schemas?)\b"
    r"|\bshow\s+create\s+table\b"
    r"|\bdescribe\b\s+(the\s+)?(\w+\s+){0,2}table\b"
    rf"|\blist\s+{_FILLER}(tables?|databases?)\b"
    r"|\b(table|database)\s+(structure|schema)\b"
    r"|\bschema\s+of\b"
    r"|\bwhat\s+(tables?|databases?)\b"
    r"|\bwhich\s+(tables?|databases?)\b"
    r"|\bcolumns?\s+(?:of|in)\s+(?:the\s+)?\w+\s+table\b",
    re.IGNORECASE,
)


def _apply_keyword_backstop(intent: Intent) -> Intent:
    if intent.type != "business_query":
        return intent
    if _METADATA_PATTERN.search(intent.text):
        return Intent(intent.text, "rejected", "metadata_request")
    if _WRITE_PATTERN.search(intent.text):
        return Intent(intent.text, "rejected", "write_request")
    return intent


async def split_intents(
    question: str,
    history: list[dict],
    client,
    *,
    model: str,
    max_intents: int,
) -> list[Intent]:
    """Decompose+classify `question` into at most `max_intents` intents.

    `history` is the same list of prior plain-text turns `/api/ask` already
    threads through the main agent loop (`[{"role": ..., "content": ...}]`).
    `client` is an AsyncAnthropic instance. Propagates whatever the Anthropic
    call raises — callers should treat a failure here as "could not process
    this request," never fall back to running the unfiltered question.
    """
    messages = list(history) + [{"role": "user", "content": question}]
    resp = await client.messages.create(
        model=model,
        max_tokens=2000,
        system=classify_system_prompt(max_intents),
        tools=[CLASSIFY_INTENTS_TOOL],
        tool_choice={"type": "tool", "name": "classify_intents"},
        messages=messages,
    )

    raw_intents = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "classify_intents":
            raw_intents = block.input.get("intents", [])
            break

    intents = []
    for i in raw_intents:
        text = i.get("text")
        if not text:
            continue
        itype = i.get("type") if i.get("type") in ("business_query", "rejected") else "rejected"
        reason = i.get("reason") or ("other" if itype == "rejected" else None)
        intents.append(Intent(text=text, type=itype, reason=reason))

    intents = [_apply_keyword_backstop(i) for i in intents]
    return intents[:max_intents]
