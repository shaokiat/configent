"""File an escalation ticket with the platform team.

The graph's `ticket` node calls this from Python once the user confirms a proposal. No model
ever sees it as a tool.

The ticket service is a separate process reached over HTTP (`TICKET_API_URL`). It is a mock we
wrote — `apps/mockticket/` — and is described as one wherever this project is presented. What is
not mocked is the integration shape: a schema owned elsewhere, a network hop that can fail, and
an idempotency contract.

The server assigns the ticket id. The client never derives one from content: two people phrasing
the same request identically must not collide into one ticket, and no real ticketing system
behaves that way (D4). Instead the caller passes a positional `Idempotency-Key` of
`{run_id}:{stage_seq}`, which is stable across a crash and retry of the *same* run and distinct
across every other.
"""
import os
from typing import Any

import httpx

# One attempt only, here. Retry with backoff is W3-1 — deliberately not inlined, because the
# retry policy belongs next to the dead-letter decision, not buried inside the client.
_TIMEOUT_SECONDS = 10.0


def _base_url() -> str:
    return os.getenv("TICKET_API_URL", "http://localhost:9000").rstrip("/")


async def create_ticket(draft: dict[str, Any], *, run_id: str, stage_seq: int) -> dict:
    """POST the ticket and return the service's response, or a dict with an `error` key."""
    subject = str(draft["subject"]).strip()
    if not subject:
        return {"error": "A non-empty subject is required to open an escalation ticket."}

    payload = {
        "subject": subject,
        "category": draft["category"],
        "product_area": draft["product_area"],
        "priority": draft.get("priority", "normal"),
    }
    if draft.get("body"):
        payload["body"] = str(draft["body"]).strip()

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_base_url()}/tickets",
                json=payload,
                headers={"Idempotency-Key": f"{run_id}:{stage_seq}"},
            )
    except httpx.HTTPError as exc:
        # Returned, not raised: the graph routes a failed filing back to the pause (W3-1),
        # and the user must never be shown a raw exception.
        return {
            "error": f"Ticket service unreachable: {exc.__class__.__name__}",
            "retryable": True,
        }

    if response.status_code >= 500:
        return {
            "error": f"Ticket service returned {response.status_code}",
            "retryable": True,
            "status_code": response.status_code,
        }
    if response.status_code >= 400:
        # A 4xx is our bug, not theirs. Retrying a 422 is not resilience.
        return {
            "error": f"Ticket service rejected the request ({response.status_code})",
            "retryable": False,
            "status_code": response.status_code,
            "detail": response.text[:500],
        }

    return response.json()
