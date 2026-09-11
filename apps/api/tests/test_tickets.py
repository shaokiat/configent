"""The ticket client, over real HTTP against the mock service running in process (D4)."""
import pytest

from app import tickets

from .conftest_mockticket import bind


@pytest.fixture(autouse=True)
def ticket_service(monkeypatch):
    bind(monkeypatch, tickets)
    monkeypatch.delenv("FAIL_RATE", raising=False)
    monkeypatch.delenv("LATENCY_MS", raising=False)


@pytest.mark.asyncio
async def test_escalation_ticket_is_idempotent_per_run_and_stage():
    """The claim the crash/resume demo rests on (D4): a replayed call files no second ticket."""
    draft = {"subject": "Binding present but access denied", "category": "account_config",
             "product_area": "iam"}
    first = await tickets.create_ticket(dict(draft), run_id="run-b", stage_seq=4)
    replay = await tickets.create_ticket(dict(draft), run_id="run-b", stage_seq=4)
    assert first["ticket_id"] == replay["ticket_id"]
    assert replay["replayed"] is True

    # A different run with identical content is a different ticket — content-derived ids
    # would have collided here, which is why the key is positional.
    other = await tickets.create_ticket(dict(draft), run_id="run-c", stage_seq=4)
    assert other["ticket_id"] != first["ticket_id"]


@pytest.mark.asyncio
async def test_escalation_ticket_reports_5xx_as_retryable(monkeypatch):
    monkeypatch.setenv("FAIL_RATE", "1.0")
    result = await tickets.create_ticket(
        {"subject": "Autoscaler ignoring max instances", "category": "incident",
         "product_area": "cloud_run"},
        run_id="run-d",
        stage_seq=4,
    )
    assert result["retryable"] is True
    assert result["status_code"] == 503
    assert "error" in result


@pytest.mark.asyncio
async def test_escalation_ticket_rejects_bad_category_without_retrying():
    """A 4xx is our bug. Retrying a validation failure is not resilience."""
    result = await tickets.create_ticket(
        {"subject": "x", "category": "not_a_category", "product_area": "gke"},
        run_id="run-e",
        stage_seq=4,
    )
    assert result["retryable"] is False
    assert result["status_code"] == 422
