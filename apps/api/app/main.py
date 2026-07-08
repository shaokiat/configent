from dotenv import load_dotenv

# no-op in Docker (vars already in env); loads .env for local dev. Must run
# before app.routers imports pull in modules that read env at import time.
load_dotenv()

from fastapi import FastAPI  # noqa: E402

from app.routers import clients, health  # noqa: E402

app = FastAPI(title="Configent API", version="0.1.0")

app.include_router(health.router)
app.include_router(clients.router)
