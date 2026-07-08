"""Tests for A3: cost math (TC-4.1), rate limiting, and the daily budget guard."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.agent.limits import (
    BudgetExceeded,
    RateLimitExceeded,
    _rate_windows,
    check_daily_budget,
    check_rate_limit,
)
from app.agent.loop import UsageTotals
from app.config.schema import LimitsConfig


def test_cost_math_to_the_cent():
    """TC-4.1: usage {input 5000, output 700, cache_read 3000, cache_write 3000}
    at $3 / $15 / $0.30 / $3.75 per MTok."""
    totals = UsageTotals(
        input_tokens=5000,
        output_tokens=700,
        cache_creation_input_tokens=3000,
        cache_read_input_tokens=3000,
    )
    expected = (5000 * 3.00 + 700 * 15.00 + 3000 * 0.30 + 3000 * 3.75) / 1_000_000
    assert totals.cost_usd == pytest.approx(expected)
    assert round(totals.cost_usd, 2) == round(expected, 2) == 0.04


def test_rate_limit_allows_requests_within_window():
    _rate_windows.pop("rl-test-a", None)
    for _ in range(5):
        check_rate_limit("rl-test-a", limit_per_minute=5)  # should not raise


def test_rate_limit_raises_over_window():
    """TC-4.4: requests beyond the per-minute limit are rejected."""
    _rate_windows.pop("rl-test-b", None)
    for _ in range(3):
        check_rate_limit("rl-test-b", limit_per_minute=3)
    with pytest.raises(RateLimitExceeded):
        check_rate_limit("rl-test-b", limit_per_minute=3)


def test_rate_limit_is_per_client():
    _rate_windows.pop("rl-test-c1", None)
    _rate_windows.pop("rl-test-c2", None)
    for _ in range(2):
        check_rate_limit("rl-test-c1", limit_per_minute=2)
    # A different client has its own independent window.
    check_rate_limit("rl-test-c2", limit_per_minute=2)


def test_enforce_rate_limit_returns_429_with_json_body():
    from app.routers.clients import _enforce_rate_limit

    _rate_windows.pop("rl-test-d", None)
    cfg = MagicMock()
    cfg.limits.rate_limit_per_minute = 1
    _enforce_rate_limit("rl-test-d", cfg)  # first call within limit

    with pytest.raises(HTTPException) as exc_info:
        _enforce_rate_limit("rl-test-d", cfg)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "rate_limited"


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


@pytest.mark.asyncio
async def test_check_daily_budget_under_threshold_does_not_raise():
    db = AsyncMock()
    db.execute.return_value = _mock_scalar_result(1.00)
    cfg = MagicMock(client_id="acme-fab", limits=LimitsConfig(daily_budget_usd=2.00))

    await check_daily_budget(db, cfg)  # should not raise


@pytest.mark.asyncio
async def test_check_daily_budget_at_threshold_raises():
    """TC-4.5: spend at or above the daily budget trips the guard (>= per A3 spec)."""
    db = AsyncMock()
    db.execute.return_value = _mock_scalar_result(2.00)
    cfg = MagicMock(client_id="acme-fab", limits=LimitsConfig(daily_budget_usd=2.00))

    with pytest.raises(BudgetExceeded):
        await check_daily_budget(db, cfg)


@pytest.mark.asyncio
async def test_enforce_daily_budget_returns_429_with_json_body():
    from app.routers.clients import _enforce_daily_budget

    db = AsyncMock()
    db.execute.return_value = _mock_scalar_result(5.00)
    cfg = MagicMock(client_id="acme-fab", limits=LimitsConfig(daily_budget_usd=2.00))

    with pytest.raises(HTTPException) as exc_info:
        await _enforce_daily_budget(db, cfg)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "daily_budget_exceeded"
