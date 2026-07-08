"""Per-client rate limiting and daily budget enforcement (§5.2, BUILD T4.4).

Two independent guards, both checked at the start of a chat turn:

- `check_rate_limit`: in-memory sliding window of request timestamps per client.
  Single-process only — fine for the demo's scale-to-zero deployment, but would
  need a shared store (Redis) behind multiple API instances.
- `check_daily_budget`: sums today's (UTC) `traces.cost_usd` for the client,
  joined through `conversations`, against `cfg.limits.daily_budget_usd`. Reset
  is implicit at the UTC date boundary — no cron/scheduler needed.
"""
import time
from collections import deque
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.models import Conversation, Trace

_RATE_WINDOW_SECONDS = 60.0

# client_id -> deque of monotonic timestamps of recent requests within the window.
_rate_windows: dict[str, deque] = {}


class RateLimitExceeded(Exception):
    """Raised when a client exceeds its configured requests-per-minute."""


class BudgetExceeded(Exception):
    """Raised when a client has spent at or above its daily budget."""


def check_rate_limit(client_id: str, limit_per_minute: int) -> None:
    """Raise RateLimitExceeded if this request would exceed the per-minute window.

    Records the request (as if accepted) only when it's within the limit, so a
    rejected request doesn't itself count against the client.
    """
    now = time.monotonic()
    window = _rate_windows.setdefault(client_id, deque())
    cutoff = now - _RATE_WINDOW_SECONDS
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= limit_per_minute:
        raise RateLimitExceeded(
            f"Client {client_id!r} exceeded {limit_per_minute} requests/minute"
        )
    window.append(now)


async def todays_cost_usd(db: AsyncSession, client_id: str) -> float:
    """Sum cost_usd across all traces recorded today (UTC) for this client."""
    today = datetime.now(UTC).date()
    stmt = (
        select(func.coalesce(func.sum(Trace.cost_usd), 0.0))
        .join(Conversation, Trace.conversation_id == Conversation.id)
        .where(
            Conversation.client_id == client_id,
            func.date(Trace.created_at) == today,
        )
    )
    result = await db.execute(stmt)
    return float(result.scalar() or 0.0)


async def check_daily_budget(db: AsyncSession, cfg: ClientConfig) -> None:
    """Raise BudgetExceeded if the client has already spent its daily ceiling."""
    spent = await todays_cost_usd(db, cfg.client_id)
    if spent >= cfg.limits.daily_budget_usd:
        raise BudgetExceeded(
            f"Client {cfg.client_id!r} has reached its daily budget of "
            f"${cfg.limits.daily_budget_usd:.2f} (spent ${spent:.2f} today)"
        )
