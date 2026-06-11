from fastapi import APIRouter

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
