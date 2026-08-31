"""create_escalation_ticket: route a question to the platform team when the docs can't answer it.

Client-specific tool for the GCP Platform Support assistant (DeployBot). The assistant's
knowledge base is public Google Cloud documentation, so anything depending on the user's own
project — quota, billing, org policy, cluster state, an in-progress incident — has to reach a
human. This tool is that path.

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

DEFINITION = {
    "name": "create_escalation_ticket",
    "description": (
        "Escalate a deployment or infrastructure question to the platform team when it cannot be "
        "answered from the public Google Cloud documentation. Use this tool when the answer "
        "depends on the user's own environment (project configuration, IAM policy, cluster "
        "state), when it concerns quota or billing, when the user reports behaviour that "
        "contradicts the documentation, when someone needs access they do not have, when the "
        "question is about a Google Cloud product outside Cloud Run, GKE, and IAM, or when a "
        "documentation search returns nothing relevant. Do not use this tool for questions the "
        "documentation already answers — answer those directly instead. Confirm a short, "
        "specific subject with the user and pick the closest category before filing. The tool "
        "returns a ticket ID the user can reference."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": (
                    "A short, specific summary of the request, detailed enough that the platform "
                    "team does not have to re-interview the user (e.g. 'Cloud Run instance quota "
                    "increase needed in europe-west1, blocking deploy')."
                ),
            },
            "category": {
                "type": "string",
                "description": (
                    "The escalation category. 'account_config' for anything requiring inspection "
                    "of the user's project, cluster, or IAM policy; 'quota_or_billing' for quota "
                    "increases, spend, and unexpected charges; 'incident' for behaviour that "
                    "contradicts documented behaviour or a suspected platform fault; "
                    "'access_request' for a needed role, binding, or service account; 'docs_gap' "
                    "for a reasonable Cloud Run/GKE/IAM question the knowledge base does not "
                    "cover; 'other' for anything else, including products outside the knowledge "
                    "base."
                ),
                "enum": [
                    "account_config",
                    "quota_or_billing",
                    "incident",
                    "access_request",
                    "docs_gap",
                    "other",
                ],
            },
            "priority": {
                "type": "string",
                "description": (
                    "How urgent the request is. Use 'high' only when the user describes "
                    "production impact — a failing deploy, a live outage, or blocked users."
                ),
                "enum": ["low", "normal", "high"],
                "default": "normal",
            },
            "product_area": {
                "type": "string",
                "description": "Which area the request concerns, for routing.",
                "enum": ["cloud_run", "gke", "iam", "other"],
            },
            "requester_email": {
                "type": "string",
                "description": "Optional email address to attach to the ticket for follow-up.",
            },
        },
        "required": ["subject", "category", "product_area"],
    },
}

# One attempt only, here. Retry with backoff is W3-1 — deliberately not inlined, because the
# retry policy belongs next to the dead-letter decision, not buried inside a tool.
_TIMEOUT_SECONDS = 10.0


def _base_url() -> str:
    return os.getenv("TICKET_API_URL", "http://localhost:9000").rstrip("/")


async def execute(
    tool_input: dict[str, Any],
    *,
    run_id: str | None = None,
    stage_seq: int = 0,
    **_,
) -> dict:
    """POST the ticket and return the service's response.

    `run_id` and `stage_seq` form the idempotency key. Both are keyword-only with defaults so
    the free-form loop — which has no run — can still call this tool; without a run_id no key
    is sent and the service will create a duplicate, which is correct, because without a run
    there is nothing to deduplicate against.
    """
    subject = str(tool_input["subject"]).strip()
    if not subject:
        return {"error": "A non-empty subject is required to open an escalation ticket."}

    payload = {
        "subject": subject,
        "category": tool_input["category"],
        "product_area": tool_input["product_area"],
        "priority": tool_input.get("priority", "normal"),
    }
    if tool_input.get("requester_email"):
        payload["requester_email"] = str(tool_input["requester_email"]).strip()
    if tool_input.get("body"):
        payload["body"] = str(tool_input["body"]).strip()

    headers = {}
    if run_id:
        headers["Idempotency-Key"] = f"{run_id}:{stage_seq}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_base_url()}/tickets", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        # Returned, not raised: the pipeline decides whether this is retryable (W3-1), and
        # the model must never be shown a raw exception.
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
