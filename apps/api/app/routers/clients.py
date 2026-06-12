import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run as agent_run
from app.agent.loop import stream_turn
from app.config.registry import get_registry
from app.database import AsyncSessionLocal, get_db

router = APIRouter(prefix="/api")


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

    try:
        conv_id, result = await agent_run(
            req.message,
            cfg=cfg,
            client_id=client_id,
            conversation_id=req.conversation_id,
            db=db,
        )
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
    }
