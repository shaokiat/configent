from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run as agent_run
from app.config.registry import get_registry
from app.database import get_db

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    citations: list[dict]


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
        conv_id, reply, citations = await agent_run(
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

    return ChatResponse(conversation_id=conv_id, reply=reply, citations=citations)


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
