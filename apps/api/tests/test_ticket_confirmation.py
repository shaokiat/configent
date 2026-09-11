"""The confirm handshake: what happens between the offer and the filed ticket (D9).

The graph pauses on `interrupt()` when it offers a ticket, and the confirm endpoint resumes
it. The paths that matter are the ones a person can provoke: a double-click, a stale tab, a
run that belongs to someone else, a confirmation for a turn that never offered anything, and
a retry after the ticket service was down.
"""
import pytest

from app.agent import graph
from app.config.registry import get_registry
from tests.graph_fakes import Harness, grade, hit, outcome_of

_DRAFT = {
    "subject": "Cloud Run instance quota increase in europe-west1",
    "category": "quota_or_billing",
    "product_area": "cloud_run",
    "priority": "high",
}


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch, get_registry().get("gcp-platform-support"))


async def _propose(h: Harness) -> None:
    events = await h.turn(
        "Can you raise my Cloud Run instance quota for europe-west1?",
        hits=[hit(0.7)], grade=grade(0.05), l2_hits=[hit(0.6)], regrade=grade(0.05),
        draft=_DRAFT,
    )
    assert outcome_of(events) == "ticket"


@pytest.mark.asyncio
async def test_confirming_files_the_draft_the_turn_proposed(h):
    await _propose(h)
    out = await h.confirm()
    assert out["ok"] is True
    assert out["ticket_id"] == "PLATFORM-1001"
    assert h.ticket_calls[0]["draft"]["subject"] == _DRAFT["subject"]
    assert "PLATFORM-1001" in out["reply"]
    assert h.runs["run-1"].steps[-1]["stage"] == "ticket"
    # The confirmation is recorded as its own assistant turn, so a reload shows it.
    replies = [m for m in h.db.added if type(m).__name__ == "Message" and m.content == out["reply"]]
    assert replies and replies[0].run_id == "run-1"


@pytest.mark.asyncio
async def test_a_double_click_files_exactly_one_ticket(h):
    """The second confirmation returns the first ticket instead of opening a duplicate
    in someone's queue (D4)."""
    await _propose(h)
    first = await h.confirm()
    second = await h.confirm()
    assert len(h.ticket_calls) == 1
    assert second["ticket_id"] == first["ticket_id"]
    assert second["already_filed"] is True


@pytest.mark.asyncio
async def test_the_idempotency_key_is_the_ticket_steps_seq(h):
    """`{run_id}:{stage_seq}`: six steps precede the ticket on this path, so it is 7."""
    await _propose(h)
    await h.confirm()
    assert h.ticket_calls[0]["run_id"] == "run-1"
    assert h.ticket_calls[0]["stage_seq"] == 7


@pytest.mark.asyncio
async def test_a_retry_after_a_failed_filing_files_the_same_draft(h):
    """A failed filing loops the graph back to the pause, so the offer is still open —
    and the retry reuses the step's seq, so a request that did land cannot duplicate."""
    await _propose(h)
    h.ticket_failures = 1
    failed = await h.confirm()
    assert failed["ok"] is False and failed["ticket_id"] is None
    assert "nothing was filed" in failed["reply"].lower()

    filed = await h.confirm()
    assert filed["ok"] is True
    assert [c["stage_seq"] for c in h.ticket_calls] == [7, 7]
    tickets = [s for s in h.runs["run-1"].steps if s["stage"] == "ticket"]
    assert len(tickets) == 1 and tickets[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_a_run_from_another_client_is_not_confirmable(h):
    """Tenancy is enforced here, not by the database (P8)."""
    await _propose(h)
    with pytest.raises(graph.RunUnavailable):
        await h.confirm(client_id="another-client")
    assert h.ticket_calls == []


@pytest.mark.asyncio
async def test_confirming_a_turn_that_never_offered_a_ticket_is_refused(h):
    """An answered turn has no pause to resume. The endpoint does not invent a draft —
    which is also what stops a client authoring a ticket by posting a run id."""
    await h.turn("What's the default CPU?", hits=[hit(0.8)], grade=grade(0.9))
    with pytest.raises(graph.RunUnavailable):
        await h.confirm()
    assert h.ticket_calls == []


@pytest.mark.asyncio
async def test_an_unknown_run_is_refused(h):
    with pytest.raises(graph.RunUnavailable):
        await h.confirm(run_id="nope")
    assert h.ticket_calls == []


# ── the router glue ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_endpoint_turns_an_unavailable_run_into_a_404(monkeypatch):
    """Unknown run, another client's run, and a turn that never offered all collapse to the
    same 404. Distinguishing them would confirm which run ids exist."""
    from fastapi import HTTPException

    from app.routers import clients

    async def _refuse(**_k):
        raise graph.RunUnavailable("Run 'run-1' not found")

    monkeypatch.setattr(clients, "confirm_ticket", _refuse)
    with pytest.raises(HTTPException) as exc:
        await clients.file_proposed_ticket(
            client_id="gcp-platform-support", run_id="run-1", db=None
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_endpoint_rejects_an_unknown_client():
    from fastapi import HTTPException

    from app.routers import clients

    with pytest.raises(HTTPException) as exc:
        await clients.file_proposed_ticket(client_id="no-such-client", run_id="run-1", db=None)
    assert exc.value.status_code == 404
