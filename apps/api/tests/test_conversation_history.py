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

    def __init__(self, conversation: Conversation | None, messages: list[Message]):
        self._conversation = conversation
        self._messages = messages

    async def get(self, model, ident):
        if model is Conversation and self._conversation is not None:
            if self._conversation.id == ident:
                return self._conversation
            return None
        return None

    async def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._messages
        return result


def _msg(role: str, content, citations: dict | None = None) -> Message:
    m = Message(conversation_id="conv-1", role=role, content=content, citations=citations or {})
    return m


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
