"""A stand-in for a real ticketing system.

Deliberately a separate service rather than an in-process function: the point of the
support agent's escalation path is that it touches an external system over HTTP, with
everything that implies — a schema someone else owns, latency, an idempotency contract,
and failure modes that are not exceptions in your own process.

Two env knobs make those failure modes reproducible on demand, which is what the week 2
and week 3 demos need:

    FAIL_RATE    0.0-1.0  probability a POST returns 503 (default 0.0)
    LATENCY_MS   int      artificial delay before responding (default 0)

This is a mock. It is stated as a mock in the README and in the interview notes; nothing
here should be presented as an integration with a real support desk.
"""
import asyncio
import os
import random
from datetime import UTC, datetime
from itertools import count
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Ticket Service", version="1.0.0")

CATEGORIES = Literal[
    "account_config", "quota_or_billing", "incident", "access_request", "docs_gap", "other"
]

# Target first-response hours by category. Incidents jump the queue.
_ETA_HOURS: dict[str, int] = {
    "incident": 2,
    "quota_or_billing": 8,
    "access_request": 8,
    "account_config": 24,
    "docs_gap": 72,
    "other": 48,
}
_QUEUE: dict[str, str] = {
    "cloud_run": "platform-serverless",
    "gke": "platform-kubernetes",
    "iam": "platform-security",
    "other": "platform-triage",
}


class TicketRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    category: CATEGORIES
    product_area: Literal["cloud_run", "gke", "iam", "other"]
    priority: Literal["low", "normal", "high"] = "normal"
    requester_email: str | None = None
    body: str | None = None


# In-memory stores. A restart clears them, which is correct for a demo service.
_tickets: dict[str, dict[str, Any]] = {}
_by_idempotency_key: dict[str, str] = {}
_seq = count(1042)


def _fail_rate() -> float:
    return float(os.getenv("FAIL_RATE", "0"))


def _latency_ms() -> int:
    return int(os.getenv("LATENCY_MS", "0"))


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "tickets": len(_tickets), "fail_rate": _fail_rate()}


@app.post("/tickets", status_code=201)
async def create_ticket(
    req: TicketRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Create a ticket, or return the existing one for a repeated Idempotency-Key.

    The replay is what makes crash-and-resume safe: the caller may have died between our
    write and its own checkpoint, so the same key must never produce a second ticket.
    A replay answers 200, not 201, so the caller can tell the difference.
    """
    if (delay := _latency_ms()) > 0:
        await asyncio.sleep(delay / 1000)

    if idempotency_key and (existing_id := _by_idempotency_key.get(idempotency_key)):
        response.status_code = 200
        return {**_tickets[existing_id], "replayed": True}

    # Chaos switch. Checked after the idempotency replay so a retry storm cannot
    # duplicate an already-created ticket just because the service is flapping.
    if (rate := _fail_rate()) > 0 and random.random() < rate:
        raise HTTPException(
            status_code=503,
            detail={"error": "ticket_service_unavailable", "retryable": True},
        )

    ticket_id = f"PLATFORM-{next(_seq)}"
    ticket = {
        "ticket_id": ticket_id,
        "status": "open",
        "subject": req.subject,
        "category": req.category,
        "product_area": req.product_area,
        "priority": req.priority,
        "queue": _QUEUE[req.product_area],
        "eta_hours": _ETA_HOURS[req.category],
        "url": f"https://platform.internal.example/tickets/{ticket_id}",
        "created_at": datetime.now(UTC).isoformat(),
    }
    if req.requester_email:
        ticket["requester_email"] = req.requester_email
    if req.body:
        ticket["body"] = req.body

    _tickets[ticket_id] = ticket
    if idempotency_key:
        _by_idempotency_key[idempotency_key] = ticket_id
    return ticket


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> dict:
    if ticket_id not in _tickets:
        raise HTTPException(status_code=404, detail=f"No ticket {ticket_id!r}")
    return _tickets[ticket_id]


@app.get("/tickets")
async def list_tickets() -> dict:
    """Every ticket filed. The demo assertion 'exactly one ticket' reads this."""
    return {"count": len(_tickets), "tickets": list(_tickets.values())}


@app.delete("/tickets")
async def reset() -> dict:
    """Clear the store between demo runs and tests."""
    _tickets.clear()
    _by_idempotency_key.clear()
    return {"status": "reset"}
