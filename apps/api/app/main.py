import asyncio
import contextlib
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# no-op in Docker (vars already in env); loads .env for local dev. Must run
# before app.routers imports pull in modules that read env at import time.
load_dotenv()

from fastapi import FastAPI  # noqa: E402

from app.agent.graph import postgres_checkpointer  # noqa: E402
from app.config.registry import _REPO_ROOT, get_registry  # noqa: E402
from app.database import DATABASE_URL  # noqa: E402
from app.ingest import reconcile_all  # noqa: E402
from app.routers import clients, health  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The support graph pauses on a proposed ticket and resumes after a crash, so its
    # checkpoints need a home that outlives the process: Postgres, beside everything else.
    async with postgres_checkpointer(DATABASE_URL):
        # Bring every client's index in line with its corpus and config. Background, so
        # the API serves (and answers 409 for a stale client) while it runs.
        reconcile = asyncio.create_task(reconcile_all(get_registry().all(), _REPO_ROOT))
        yield
        # Per-document commits make stopping mid-run safe: the next start picks up the rest.
        reconcile.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reconcile


app = FastAPI(title="Configent API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(clients.router)
