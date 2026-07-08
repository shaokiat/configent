import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.limits import (
    BudgetExceeded,
    RateLimitExceeded,
    check_daily_budget,
    check_rate_limit,
)
from app.agent.loop import ConversationNotFoundError, stream_turn
from app.agent.loop import run as agent_run
from app.config.registry import get_registry
from app.config.schema import ClientConfig
from app.database import AsyncSessionLocal, get_db
from app.models import Conversation, Message

router = APIRouter(prefix="/api")


def _enforce_rate_limit(client_id: str, cfg: ClientConfig) -> None:
    try:
        check_rate_limit(client_id, cfg.limits.rate_limit_per_minute)
    except RateLimitExceeded:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": "Too many requests. Please slow down and try again shortly.",
            },
        ) from None


async def _enforce_daily_budget(db: AsyncSession, cfg: ClientConfig) -> None:
    try:
        await check_daily_budget(db, cfg)
    except BudgetExceeded:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_budget_exceeded",
                "message": (
                    "This assistant has reached its daily usage budget. "
                    "Please try again after the daily reset (UTC midnight)."
                ),
            },
        ) from None


async def _check_conversation_ownership(
    db: AsyncSession, client_id: str, conversation_id: str | None
) -> None:
    """Pre-flight ownership check for the SSE path (A1): must run — and fail with a
    plain 404 — before the StreamingResponse starts, since once the 200 status and
    first bytes are sent there's no way to downgrade to an HTTP error status."""
    if conversation_id is None:
        return
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.client_id != client_id:
        raise HTTPException(
            status_code=404, detail=f"Conversation {conversation_id!r} not found"
        )


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    citations: list[dict]
    # Ordered answer segments: [{text, citations: [{source, title, cited_text}]}]
    segments: list[dict]


@router.get("/clients")
async def list_clients():
    registry = get_registry()
    return [
        {
            "id": cfg.client_id,
            "name": cfg.name,
            "branding": {
                "logo": cfg.branding.logo,
                "primary_color": cfg.branding.primary_color,
                "assistant_name": cfg.branding.assistant_name,
                "suggested_questions": cfg.branding.suggested_questions,
            },
        }
        for cfg in registry.all()
    ]


@router.post("/c/{client_id}/chat", response_model=ChatResponse)
async def chat(
    client_id: str,
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    registry = get_registry()
    try:
        cfg = registry.get(client_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Client {client_id!r} not found")

    _enforce_rate_limit(client_id, cfg)
    await _enforce_daily_budget(db, cfg)

    try:
        conv_id, result = await agent_run(
            req.message,
            cfg=cfg,
            client_id=client_id,
            conversation_id=req.conversation_id,
            db=db,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"System prompt not found: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        conversation_id=conv_id,
        reply=result.reply_text,
        citations=result.citations,
        segments=result.segments,
    )


@router.post("/c/{client_id}/chat/stream")
async def chat_stream(client_id: str, req: ChatRequest):
    """SSE chat endpoint. Event contract: POC_FACTORY_TEST_ANCHORS.md UC-10."""
    registry = get_registry()
    try:
        cfg = registry.get(client_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Client {client_id!r} not found")

    _enforce_rate_limit(client_id, cfg)

    # Ownership + budget checks run in their own short-lived session, before the
    # StreamingResponse is constructed, so a rejection is a normal HTTP error
    # response rather than something surfaced mid-stream.
    async with AsyncSessionLocal() as preflight_db:
        await _check_conversation_ownership(preflight_db, client_id, req.conversation_id)
        await _enforce_daily_budget(preflight_db, cfg)

    async def event_source():
        # The session is opened inside the generator: a Depends(get_db) session
        # can be torn down before a StreamingResponse body starts executing.
        async with AsyncSessionLocal() as db:
            async for name, data in stream_turn(
                req.message,
                cfg=cfg,
                client_id=client_id,
                conversation_id=req.conversation_id,
                db=db,
            ):
                yield f"event: {name}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/clients/{client_id}/branding")
async def get_client_branding(client_id: str):
    registry = get_registry()
    try:
        cfg = registry.get(client_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Client {client_id!r} not found")
    return {
        "id": cfg.client_id,
        "name": cfg.name,
        "primary_color": cfg.branding.primary_color,
        "logo": cfg.branding.logo,
        "assistant_name": cfg.branding.assistant_name,
        "suggested_questions": cfg.branding.suggested_questions,
    }


@router.get("/c/{client_id}/conversations/{conversation_id}")
async def get_conversation_history(
    client_id: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Renderable conversation history for reloading a conversation (B6).

    Returns only user turns and final-assistant turns (with their citation
    segments) — tool_use-only assistant messages and tool_result plumbing
    messages are internal to the loop and are skipped.
    """
    await _check_conversation_ownership(db, client_id, conversation_id)

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    )
    messages: list[dict] = []
    for m in result.scalars().all():
        if m.role == "user":
            if isinstance(m.content, str):
                messages.append({"role": "user", "text": m.content})
            # else: a tool_result plumbing message — not user-visible, skip.
        elif m.role == "assistant":
            segments = (m.citations or {}).get("segments")
            if segments:
                messages.append({"role": "assistant", "segments": segments})
            # else: a tool_use-only assistant message — skip.

    return {"conversation_id": conversation_id, "messages": messages}
