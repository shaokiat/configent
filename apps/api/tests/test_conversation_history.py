"""Tests for B6: GET /api/c/{client_id}/conversations/{conversation_id}.

The endpoint returns each user turn's text and each assistant turn's citation segments,
with the step trail for turns that ran on the graph, and it must 404 on an unknown or
cross-tenant conversation_id (mirroring the ownership check used by the chat endpoints).
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message, Run
from app.routers.clients import get_conversation_history

CLIENT = "gcp-platform-support"


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
async def test_history_returns_user_text_and_assistant_segments():
    conv = Conversation(id="conv-1", client_id=CLIENT)
    segments = [{"text": "Each instance gets 1 vCPU.", "citations": []}]
    messages = [
        _msg("user", "What's the default CPU limit for Cloud Run?"),
        _msg("assistant", "Each instance gets 1 vCPU.", {"segments": segments}),
    ]

    result = await get_conversation_history(CLIENT, "conv-1", db=_FakeDB(conv, messages))

    assert result["conversation_id"] == "conv-1"
    assert result["messages"] == [
        {"role": "user", "text": "What's the default CPU limit for Cloud Run?"},
        {"role": "assistant", "segments": segments},
    ]


@pytest.mark.asyncio
async def test_history_cross_tenant_conversation_404s():
    conv = Conversation(id="conv-1", client_id=CLIENT)
    db = _FakeDB(conv, [])

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_history("another-client", "conv-1", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_history_unknown_conversation_404s():
    db = _FakeDB(None, [])

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_history(CLIENT, "nonexistent", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_history_replays_the_step_trail_for_graph_turns():
    """Reloading a conversation must not lose the audit trail.

    The steps live in `runs`, not on the message — a run that crashed before its message
    was written still keeps its trail — so history has to follow the join rather than
    read a copy.
    """
    conv = Conversation(id="conv-1", client_id=CLIENT)
    steps = [
        {"seq": 1, "stage": "retrieve", "status": "ok"},
        {"seq": 2, "stage": "grade", "status": "ok", "confidence": 0.05},
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
    runs = [Run(id="run-1", conversation_id="conv-1", client_id=CLIENT, steps=steps)]

    out = await get_conversation_history(CLIENT, "conv-1", db=_FakeDB(conv, messages, runs))
    assistant = [m for m in out["messages"] if m["role"] == "assistant"][0]
    assert [s["stage"] for s in assistant["steps"]] == [
        "retrieve", "grade", "escalate", "ticket",
    ]
