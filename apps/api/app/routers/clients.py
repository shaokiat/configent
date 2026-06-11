from fastapi import APIRouter, HTTPException

from app.config.registry import get_registry

router = APIRouter(prefix="/api")


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
