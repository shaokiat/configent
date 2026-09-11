import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import RunUnavailable, confirm_ticket, run_graph, stream_graph
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
from app.models import Conversation, Message, Run

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


def _client(client_id: str) -> ClientConfig:
    try:
        return get_registry().get(client_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Client {client_id!r} not found") from None


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
            # The engine this client runs on. The landing page groups clients by it,
            # so a graph client is never presented as a free-form assistant.
            "mode": cfg.agent.mode,
            "branding": {
                "logo": cfg.branding.logo,
                "primary_color": cfg.branding.primary_color,
                "assistant_name": cfg.branding.assistant_name,
                "suggested_questions": cfg.branding.suggested_questions,
                "tagline": cfg.branding.tagline,
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
    cfg = _client(client_id)
    _enforce_rate_limit(client_id, cfg)
    await _enforce_daily_budget(db, cfg)

    if cfg.agent.mode == "graph":
        await _check_conversation_ownership(db, client_id, req.conversation_id)
        try:
            state = await run_graph(
                req.message,
                cfg=cfg,
                client_id=client_id,
                conversation_id=req.conversation_id,
                db=db,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        return ChatResponse(
            conversation_id=state["conversation_id"],
            reply=state["answer"],
            citations=state.get("citations", []),
            segments=state["segments"],
        )

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
    """SSE chat endpoint. Event contract: docs/test-anchors.md UC-10."""
    cfg = _client(client_id)
    _enforce_rate_limit(client_id, cfg)

    # Ownership + budget checks run in their own short-lived session, before the
    # StreamingResponse is constructed, so a rejection is a normal HTTP error
    # response rather than something surfaced mid-stream.
    async with AsyncSessionLocal() as preflight_db:
        await _check_conversation_ownership(preflight_db, client_id, req.conversation_id)
        await _enforce_daily_budget(preflight_db, cfg)

    # One entry point, two engines (D5). `loop` is the free-form manual tool-use loop;
    # `graph` is the three-tier support graph whose every route is Python (D10).
    engine = stream_graph if cfg.agent.mode == "graph" else stream_turn

    async def event_source():
        # The session is opened inside the generator: a Depends(get_db) session
        # can be torn down before a StreamingResponse body starts executing.
        async with AsyncSessionLocal() as db:
            async for name, data in engine(
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


@router.post("/c/{client_id}/runs/{run_id}/ticket")
async def file_proposed_ticket(
    client_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """File the ticket a graph turn proposed, on the user's confirmation (D9).

    The turn drafts, offers and pauses; this resumes it. Nothing about the ticket comes from
    the request body — there isn't one — so a client can confirm a proposal but cannot
    author one.
    """
    cfg = _client(client_id)
    try:
        return await confirm_ticket(run_id=run_id, client_id=client_id, cfg=cfg, db=db)
    except RunUnavailable as exc:
        # Also the answer when the run belongs to another client: a 404 leaks nothing
        # about whether that run exists (P8 — tenancy is enforced here, not by the DB).
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/clients/{client_id}/branding")
async def get_client_branding(client_id: str):
    cfg = _client(client_id)
    return {
        "id": cfg.client_id,
        "name": cfg.name,
        # Drives the header badge: a graph client advertises its guardrail, not
        # the free-form loop's citation behaviour.
        "mode": cfg.agent.mode,
        "primary_color": cfg.branding.primary_color,
        "logo": cfg.branding.logo,
        "assistant_name": cfg.branding.assistant_name,
        "suggested_questions": cfg.branding.suggested_questions,
        "tagline": cfg.branding.tagline,
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
    rows = list(result.scalars().all())

    # Graph turns carry a run whose `steps` are the audit trail. Loaded in one query
    # and attached by id rather than copied onto the message at write time, so `runs`
    # stays the single source of truth for what the agent actually did.
    run_ids = {m.run_id for m in rows if m.run_id}
    steps_by_run: dict[str, list] = {}
    if run_ids:
        runs = await db.execute(select(Run).where(Run.id.in_(run_ids)))
        steps_by_run = {r.id: (r.steps or []) for r in runs.scalars().all()}

    messages: list[dict] = []
    for m in rows:
        if m.role == "user":
            if isinstance(m.content, str):
                messages.append({"role": "user", "text": m.content})
            # else: a tool_result plumbing message — not user-visible, skip.
        elif m.role == "assistant":
            segments = (m.citations or {}).get("segments")
            if segments:
                entry: dict = {"role": "assistant", "segments": segments}
                if steps := steps_by_run.get(m.run_id or ""):
                    entry["steps"] = steps
                messages.append(entry)
            # else: a tool_use-only assistant message — skip.

    return {"conversation_id": conversation_id, "messages": messages}
