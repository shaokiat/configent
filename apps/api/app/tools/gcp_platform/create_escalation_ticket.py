"""create_escalation_ticket: route a question to the platform team when the docs can't answer it.

Client-specific tool for the GCP Platform Support assistant (DeployBot). The assistant's
knowledge base is public Google Cloud documentation, so anything depending on the user's own
project — quota, billing, org policy, cluster state, an in-progress incident — has to reach a
human. This tool is that path.

Deterministic mock: given the same subject and category it always returns the same ticket ID, so
demos and tests are reproducible. W1-8 of docs/support-agent-plan.md replaces the body with a
real HTTP call to the mock ticket service, at which point the ID is assigned by the server and
`_ticket_id` survives only as a fixture seed (see decision D4).
"""
import zlib
from typing import Any

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

# Target first-response time, in hours, by category. Incidents jump the queue.
_ETA_HOURS: dict[str, int] = {
    "incident": 2,
    "quota_or_billing": 8,
    "access_request": 8,
    "account_config": 24,
    "docs_gap": 72,
    "other": 48,
}

# Which on-call rotation the ticket lands in.
_QUEUE: dict[str, str] = {
    "cloud_run": "platform-serverless",
    "gke": "platform-kubernetes",
    "iam": "platform-security",
    "other": "platform-triage",
}


def _ticket_id(subject: str, category: str) -> str:
    """Deterministic ticket id derived from subject + category.

    Uses zlib.crc32 (stable across runs and processes) rather than hash(), whose seed varies.
    """
    digest = zlib.crc32(f"{category}:{subject}".strip().lower().encode())
    return f"PLATFORM-{digest % 9000 + 1000}"


async def execute(tool_input: dict[str, Any], **_) -> dict:
    subject = str(tool_input["subject"]).strip()
    category = tool_input["category"]
    product_area = tool_input["product_area"]
    priority = tool_input.get("priority", "normal")

    if not subject:
        return {"error": "A non-empty subject is required to open an escalation ticket."}

    ticket_id = _ticket_id(subject, category)
    result = {
        "ticket_id": ticket_id,
        "status": "open",
        "subject": subject,
        "category": category,
        "product_area": product_area,
        "priority": priority,
        "queue": _QUEUE.get(product_area, "platform-triage"),
        "eta_hours": _ETA_HOURS.get(category, 48),
        "url": f"https://platform.internal.example/tickets/{ticket_id}",
    }
    if tool_input.get("requester_email"):
        result["requester_email"] = str(tool_input["requester_email"]).strip()
    return result
