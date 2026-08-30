"""Tests for B6: GET /api/c/{client_id}/conversations/{conversation_id}.

The endpoint must return only the renderable turns — user text and
final-assistant citation segments — skipping tool_result plumbing messages
and tool_use-only assistant messages, and it must 404 on an unknown or
cross-tenant conversation_id (mirroring the ownership check already used by
the chat endpoints).
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message
from app.routers.clients import get_conversation_history


class _FakeDB:
    """Minimal AsyncSession stand-in with a conversation store and a static
    list of messages returned by any `execute(select(Message)...)` call."""

    def __init__(
        self,
        conversation: Conversation | None,
        messages: list[Message],
        runs: list | None = None,
    ):
        self._conversation = conversation
        self._messages = messages
        self._runs = runs or []
        self._calls = 0

    async def get(self, model, ident):
        if model is Conversation and self._conversation is not None:
            if self._conversation.id == ident:
                return self._conversation
            return None
        return None

    async def execute(self, stmt):
        # First select is the messages, the second (only made when a message carries a
        # run_id) is the runs those messages point at.
        self._calls += 1
        result = MagicMock()
        rows = self._messages if self._calls == 1 else self._runs
        result.scalars.return_value.all.return_value = rows
        return result


def _msg(role: str, content, citations: dict | None = None, run_id: str | None = None) -> Message:
    return Message(
        conversation_id="conv-1",
        role=role,
        content=content,
        citations=citations or {},
        run_id=run_id,
    )


@pytest.mark.asyncio
async def test_history_filters_to_user_text_and_final_assistant_segments():
    conv = Conversation(id="conv-1", client_id="acme-fab")
    messages = [
        _msg("user", "What's the PM schedule for the PX-900?"),
        _msg(
            "assistant",
            [{"type": "tool_use", "id": "t1", "name": "search_docs", "input": {}}],
        ),
        _msg("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "..."}]),
        _msg(
            "assistant",
            [{"type": "text", "text": "Every 90 days."}],
            citations={
                "segments": [{"text": "Every 90 days.", "citations": []}],
            },
        ),
    ]
    db = _FakeDB(conv, messages)

    result = await get_conversation_history("acme-fab", "conv-1", db=db)

    assert result["conversation_id"] == "conv-1"
    assert result["messages"] == [
        {"role": "user", "text": "What's the PM schedule for the PX-900?"},
        {
            "role": "assistant",
            "segments": [{"text": "Every 90 days.", "citations": []}],
        },
    ]


@pytest.mark.asyncio
async def test_history_cross_tenant_conversation_404s():
    conv = Conversation(id="conv-1", client_id="acme-fab")
    db = _FakeDB(conv, [])

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_history("meridian-insurance", "conv-1", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_history_unknown_conversation_404s():
    db = _FakeDB(None, [])

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_history("acme-fab", "nonexistent", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_history_replays_the_step_trail_for_pipeline_turns():
    """Reloading a conversation must not lose the audit trail.

    The steps live in `runs`, not on the message — a run that crashed before its message
    was written still keeps its trail — so history has to follow the join rather than
    read a copy.
    """
    from app.models import Run

    conv = Conversation(id="conv-1", client_id="gcp-platform-support")
    steps = [
        {"seq": 1, "stage": "retrieve", "status": "ok"},
        {"seq": 2, "stage": "score", "status": "ok", "confidence": 0.05},
        {"seq": 3, "stage": "escalate", "status": "ok"},
        {"seq": 4, "stage": "ticket", "status": "ok", "ticket_id": "PLATFORM-1042"},
    ]
    messages = [
        _msg("user", "Can you raise my quota?"),
        _msg(
            "assistant",
            "I've opened PLATFORM-1042.",
            {"segments": [{"text": "I've opened PLATFORM-1042.", "citations": []}]},
            run_id="run-1",
        ),
    ]
    runs = [Run(id="run-1", conversation_id="conv-1", client_id="gcp-platform-support", steps=steps)]

    out = await get_conversation_history(
        "gcp-platform-support", "conv-1", db=_FakeDB(conv, messages, runs)
    )
    assistant = [m for m in out["messages"] if m["role"] == "assistant"][0]
    assert [s["stage"] for s in assistant["steps"]] == [
        "retrieve", "score", "escalate", "ticket",
    ]
