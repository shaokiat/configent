import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/configent")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def checkpoint_session() -> AsyncIterator[AsyncSession]:
    """A short-lived session whose writes commit immediately and independently (D3).

    The request-scoped session from `get_db` commits once at the end of a turn and is
    rolled back on any failure — so run state written through it is erased by exactly the
    crash it exists to survive. Durability writes (the `Run` row, its steps) go here
    instead: each call opens its own connection, commits, and closes.

    Cost is one connection per checkpoint. At the rate a pipeline checkpoints (once per
    stage) that is cheaper than the alternative, which is losing the audit trail.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
