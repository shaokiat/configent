"""The confirm handshake: what happens between the offer and the filed ticket (D9).

A ticket used to be filed by the turn, where the only way to fire twice was a crash and a
resume. Now a human clicks a button, so the paths that matter are the ones a person can
provoke: a double-click, a stale tab, a run that belongs to someone else, a confirmation for
a turn that never offered anything. D4's second guard — the stored `ticket_id` — stops being
belt-and-braces and starts being the thing that holds.
"""
import pytest

from app.agent import pipeline


class _Run:
    def __init__(self, state, *, client_id="gcp-platform-support", run_id="run-1"):
        self.id = run_id
        self.conversation_id = "conv-1"
        self.client_id = client_id
        self.status = "completed"
        self.steps = [{"seq": 1, "stage": "escalate"}]
        self.state = state


class _DB:
    def __init__(self, run):
        self.run = run
        self.added = []
        self.committed = False

    async def get(self, model, key):
        if getattr(model, "__name__", "") == "Run":
            return self.run if self.run and key == self.run.id else None
        return None

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True


class _Recorder:
    def __init__(self, run_id, conversation_id, client_id):
        self.run_id = run_id
        self.steps = []
        self.state = {}

    async def step(self, stage, **extra):
        entry = {"stage": stage, **extra}
        self.steps.append(entry)
        return entry

    async def finish(self, status):
        self.status = status


_DRAFT = {
    "route": "ticket",
    "subject": "Cloud Run instance quota increase in europe-west1",
    "category": "quota_or_billing",
    "product_area": "cloud_run",
    "priority": "high",
}


@pytest.fixture
def filed(monkeypatch):
    """Records every call that reaches the ticket service."""
    calls = []

    async def _fake_ticket(draft, *, db, client_id, run_id, stage_seq):
        calls.append({"draft": draft, "run_id": run_id, "stage_seq": stage_seq})
        return {
            "ticket_id": f"PLATFORM-{1000 + len(calls)}",
            "url": "https://platform.internal.example/tickets/PLATFORM-1001",
            "queue": "platform-serverless",
            "eta_hours": 4,
        }

    monkeypatch.setattr(pipeline, "stage_ticket", _fake_ticket)
    monkeypatch.setattr(pipeline, "RunRecorder", _Recorder)
    return calls


@pytest.mark.asyncio
async def test_confirming_files_the_draft_the_turn_proposed(filed):
    db = _DB(_Run({"ticket_draft": _DRAFT}))
    out = await pipeline.confirm_ticket(
        run_id="run-1", client_id="gcp-platform-support", db=db
    )
    assert out["ticket_id"] == "PLATFORM-1001"
    assert filed[0]["draft"] == _DRAFT
    assert "PLATFORM-1001" in out["reply"]
    # The confirmation is recorded as its own assistant turn, so a reload shows it.
    assert db.committed and db.added


@pytest.mark.asyncio
async def test_a_double_click_files_exactly_one_ticket(filed):
    """The one a user can actually cause. The second confirmation returns the first
    ticket instead of opening a duplicate in someone's queue (D4)."""
    run = _Run({"ticket_draft": _DRAFT})
    db = _DB(run)
    first = await pipeline.confirm_ticket(
        run_id="run-1", client_id="gcp-platform-support", db=db
    )
    # The recorder wrote the id back to the run, as it does through checkpoint_session.
    run.state["ticket_id"] = first["ticket_id"]

    second = await pipeline.confirm_ticket(
        run_id="run-1", client_id="gcp-platform-support", db=db
    )
    assert len(filed) == 1
    assert second["ticket_id"] == first["ticket_id"]
    assert second["already_filed"] is True


@pytest.mark.asyncio
async def test_the_idempotency_key_covers_a_racing_retry(filed):
    """Belt to the state check's braces: the key is `{run_id}:{stage_seq}`, so a retry that
    slips past the state check still collapses into one ticket at the service."""
    db = _DB(_Run({"ticket_draft": _DRAFT}))
    await pipeline.confirm_ticket(run_id="run-1", client_id="gcp-platform-support", db=db)
    assert filed[0]["run_id"] == "run-1"
    assert filed[0]["stage_seq"] == 2  # one step already recorded on the run


@pytest.mark.asyncio
async def test_a_run_from_another_client_is_not_confirmable(filed):
    """Tenancy is enforced here, not by the database (P8). A 404, not a 403 — the answer
    reveals nothing about whether that run exists."""
    db = _DB(_Run({"ticket_draft": _DRAFT}, client_id="acme-fab"))
    with pytest.raises(pipeline.TicketUnavailable):
        await pipeline.confirm_ticket(
            run_id="run-1", client_id="gcp-platform-support", db=db
        )
    assert filed == []


@pytest.mark.asyncio
async def test_confirming_a_turn_that_never_offered_a_ticket_is_refused(filed):
    """A conversational turn parks no draft. The endpoint has nothing to file and does not
    invent one — which is also what stops a client authoring a ticket by posting a run id."""
    db = _DB(_Run({}))
    with pytest.raises(pipeline.TicketUnavailable):
        await pipeline.confirm_ticket(
            run_id="run-1", client_id="gcp-platform-support", db=db
        )
    assert filed == []


@pytest.mark.asyncio
async def test_an_unknown_run_is_refused(filed):
    db = _DB(None)
    with pytest.raises(pipeline.TicketUnavailable):
        await pipeline.confirm_ticket(
            run_id="nope", client_id="gcp-platform-support", db=db
        )
    assert filed == []


@pytest.mark.asyncio
async def test_a_ticket_service_failure_is_reported_without_claiming_success(monkeypatch):
    async def _boom(*_a, **_k):
        return {"error": "Ticket service unreachable: ConnectError", "retryable": True}

    monkeypatch.setattr(pipeline, "stage_ticket", _boom)
    monkeypatch.setattr(pipeline, "RunRecorder", _Recorder)
    db = _DB(_Run({"ticket_draft": _DRAFT}))
    out = await pipeline.confirm_ticket(
        run_id="run-1", client_id="gcp-platform-support", db=db
    )
    assert out["ok"] is False
    assert out["ticket_id"] is None
    assert "nothing was filed" in out["reply"].lower()


# ── the router glue ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_endpoint_turns_an_unavailable_ticket_into_a_404(monkeypatch):
    """Unknown run, another client's run, and a turn that never offered all collapse to the
    same 404. Distinguishing them would confirm which run ids exist."""
    from fastapi import HTTPException

    from app.routers import clients

    async def _refuse(**_k):
        raise pipeline.TicketUnavailable("Run 'run-1' not found")

    monkeypatch.setattr(clients, "confirm_ticket", _refuse)
    with pytest.raises(HTTPException) as exc:
        await clients.file_proposed_ticket(
            client_id="gcp-platform-support", run_id="run-1", db=_DB(None)
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_endpoint_rejects_an_unknown_client(monkeypatch):
    from fastapi import HTTPException

    from app.routers import clients

    with pytest.raises(HTTPException) as exc:
        await clients.file_proposed_ticket(
            client_id="no-such-client", run_id="run-1", db=_DB(None)
        )
    assert exc.value.status_code == 404
