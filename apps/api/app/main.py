from contextlib import asynccontextmanager

from dotenv import load_dotenv

# no-op in Docker (vars already in env); loads .env for local dev. Must run
# before app.routers imports pull in modules that read env at import time.
load_dotenv()

from fastapi import FastAPI  # noqa: E402

from app.agent.graph import postgres_checkpointer  # noqa: E402
from app.database import DATABASE_URL  # noqa: E402
from app.routers import clients, health  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The support graph pauses on a proposed ticket and resumes after a crash, so its
    # checkpoints need a home that outlives the process: Postgres, beside everything else.
    async with postgres_checkpointer(DATABASE_URL):
        yield


app = FastAPI(title="Configent API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(clients.router)
