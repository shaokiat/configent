"""Tests for A3: cost math (TC-4.1), rate limiting, and the daily budget guard."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.agent.limits import (
    BudgetExceeded,
    _rate_windows,
    check_daily_budget,
)
from app.config.schema import LimitsConfig


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
