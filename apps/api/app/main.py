from fastapi import FastAPI

from app.routers import clients, health

app = FastAPI(title="Configent API", version="0.1.0")

app.include_router(health.router)
app.include_router(clients.router)
