"""Intent classification gate: model decomposition plus the deterministic
keyword backstop for write/metadata requests (backend/intents.py)."""

import asyncio

from backend.intents import REJECTION_MESSAGES, split_intents


class _Block:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _Response:
    def __init__(self, intents):
        self.content = [_Block("classify_intents", {"intents": intents})]


class _FakeMessages:
    def __init__(self, intents):
        self._intents = intents

    async def create(self, **kwargs):
        return _Response(self._intents)


class _FakeClient:
    def __init__(self, intents):
        self.messages = _FakeMessages(intents)


def _split(intents, question="irrelevant", max_intents=5):
    client = _FakeClient(intents)
    return asyncio.run(
        split_intents(question, [], client, model="fake", max_intents=max_intents)
    )


def test_accepted_business_query_passes_through():
    result = _split([{"text": "how many parts failed?", "type": "business_query"}])
    assert len(result) == 1
    assert result[0].type == "business_query"
    assert result[0].reason is None


def test_model_rejected_write_request_is_kept_rejected():
    result = _split([
        {"text": "delete employee 5", "type": "rejected", "reason": "write_request"},
    ])
    assert result[0].type == "rejected"
    assert result[0].reason == "write_request"


def test_backstop_overrides_model_missing_a_write_request():
    # Model mis-classified a write request as a legitimate business query.
    result = _split([{"text": "please delete order 5", "type": "business_query"}])
    assert result[0].type == "rejected"
    assert result[0].reason == "write_request"


def test_backstop_overrides_model_missing_a_metadata_request():
    result = _split([{"text": "show all tables", "type": "business_query"}])
    assert result[0].type == "rejected"
    assert result[0].reason == "metadata_request"


def test_backstop_does_not_flag_benign_past_tense_phrasing():
    # "updated" is past-tense report language, not a write verb request.
    result = _split([{"text": "orders updated yesterday", "type": "business_query"}])
    assert result[0].type == "business_query"


def test_compound_message_splits_into_multiple_intents():
    result = _split([
        {"text": "how many parts failed?", "type": "business_query"},
        {"text": "delete employee 5", "type": "rejected", "reason": "write_request"},
    ])
    assert len(result) == 2
    assert [i.type for i in result] == ["business_query", "rejected"]


def test_max_intents_truncates_extra_results():
    intents = [{"text": f"question {i}", "type": "business_query"} for i in range(10)]
    result = _split(intents, max_intents=3)
    assert len(result) == 3


def test_rejection_messages_cover_every_reason_code():
    for reason in ("metadata_request", "write_request", "unrelated", "prompt_injection", "other"):
        assert reason in REJECTION_MESSAGES
        assert REJECTION_MESSAGES[reason]
