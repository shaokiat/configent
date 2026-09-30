"""Tests for A1: cross-tenant conversation hijack.

`prepare_conversation` (and the router glue around it) must refuse to load a
conversation's history for a client_id that doesn't own it.
"""
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.agent.common import ConversationNotFoundError, prepare_conversation
from app.models import Conversation
from app.routers.clients import _check_conversation_ownership


class _FakeDB:
    """Minimal AsyncSession stand-in: a conversation store plus a no-op message
    history query, enough for `prepare_conversation`'s two code paths.

    Real SQLAlchemy assigns the Conversation.id Python-side default during
    flush; this fake mimics that (real flush is a no-op here) so callers see
    the same id-after-flush behavior. `commit` is tracked rather than ignored:
    a new conversation must be committed, not just flushed, or the graph's
    independent session cannot see it as an FK parent (D3)."""

    def __init__(self):
        self.conversations: dict[str, Conversation] = {}
        self.commits = 0

    def add(self, obj):
        if isinstance(obj, Conversation):
            if obj.id is None:
                obj.id = str(uuid.uuid4())
            self.conversations[obj.id] = obj

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def get(self, model, ident):
        if model is Conversation:
            return self.conversations.get(ident)
        return None

    async def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result


@pytest.mark.asyncio
async def test_prepare_conversation_creates_new_for_client_a():
    db = _FakeDB()
    conv_id, history = await prepare_conversation(db, "client-a", None)

    assert history == []
    assert db.conversations[conv_id].client_id == "client-a"
    # Committed, not just flushed: runs.conversation_id is an FK written from a
    # separate session, which cannot see an uncommitted parent.
    assert db.commits == 1


@pytest.mark.asyncio
async def test_prepare_conversation_cross_tenant_raises_not_found():
    """A conversation created under client-a must not be loadable by client-b."""
    db = _FakeDB()
    conv_id, _ = await prepare_conversation(db, "client-a", None)

    with pytest.raises(ConversationNotFoundError):
        await prepare_conversation(db, "client-b", conv_id)


@pytest.mark.asyncio
async def test_stream_preflight_rejects_cross_tenant_conversation():
    """The SSE pre-flight check (run before StreamingResponse is constructed)
    must 404 on a conversation_id owned by a different client."""
    db = _FakeDB()
    await prepare_conversation(db, "client-a", None)
    conv_id = next(iter(db.conversations))

    with pytest.raises(HTTPException) as exc_info:
        await _check_conversation_ownership(db, "client-b", conv_id)

    assert exc_info.value.status_code == 404
