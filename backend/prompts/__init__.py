"""Every Claude-facing prompt and tool schema, one concern per file.

- `ask.py` — the "Ask your data" chat assistant (backend.routes.ask).
- `intent_classifier.py` — the upstream intent-splitting gate (backend.intents).

Kept separate from route/handler code so prompt wording changes never require
touching request-handling logic, and vice versa.
"""

MODEL = "claude-opus-4-8"

from backend.prompts.ask import RUN_QUERY_TOOL, build_system_prompt
from backend.prompts.intent_classifier import CLASSIFY_INTENTS_TOOL, classify_system_prompt

__all__ = [
    "MODEL",
    "RUN_QUERY_TOOL",
    "build_system_prompt",
    "CLASSIFY_INTENTS_TOOL",
    "classify_system_prompt",
]
