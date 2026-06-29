"""create_support_ticket tool: file a mock support ticket when the docs can't answer a question.

This is a client-specific tool for the Configent Support assistant. It is a deterministic mock —
it does not call a real ticketing system. Given the same subject and category it always returns
the same ticket ID, so the behaviour is reproducible in tests and demos.
"""
import zlib
from typing import Any

DEFINITION = {
    "name": "create_support_ticket",
    "description": (
        "File a support ticket for a question that cannot be answered from the Configent "
        "documentation. Use this tool when the user reports a suspected bug, requests a feature "
        "that does not exist today, asks an account or billing question not covered by the docs, "
        "or when a documentation search returns nothing relevant and the user wants follow-up. "
        "Do not use this tool for questions the documentation already answers — answer those "
        "directly instead. Confirm a short subject with the user and pick the most fitting "
        "category before filing. The tool returns a ticket ID the user can reference."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "A short, specific summary of the issue (e.g. 'Ingestion fails with missing VOYAGE_API_KEY').",
            },
            "category": {
                "type": "string",
                "description": (
                    "The ticket category. 'bug' for something broken, 'feature_request' for "
                    "missing functionality, 'account' for account/access issues, 'billing' for "
                    "billing questions, 'other' for anything else."
                ),
                "enum": ["billing", "bug", "account", "feature_request", "other"],
            },
            "priority": {
                "type": "string",
                "description": "How urgent the issue is.",
                "enum": ["low", "normal", "high"],
                "default": "normal",
            },
            "customer_email": {
                "type": "string",
                "description": "Optional email address to attach to the ticket for follow-up.",
            },
        },
        "required": ["subject", "category"],
    },
}

# How long, in hours, the team aims to first-respond by category.
_ETA_HOURS: dict[str, int] = {
    "bug": 8,
    "billing": 24,
    "account": 24,
    "feature_request": 72,
    "other": 48,
}


def _ticket_id(subject: str, category: str) -> str:
    """Deterministic ticket id derived from subject + category.

    Uses zlib.crc32 (stable across runs and processes) rather than hash(), whose seed varies.
    """
    digest = zlib.crc32(f"{category}:{subject}".strip().lower().encode())
    return f"CONFIGENT-{digest % 9000 + 1000}"


async def execute(tool_input: dict[str, Any], **_) -> dict:
    subject = str(tool_input["subject"]).strip()
    category = tool_input["category"]
    priority = tool_input.get("priority", "normal")

    if not subject:
        return {"error": "A non-empty subject is required to file a support ticket."}

    ticket_id = _ticket_id(subject, category)
    result = {
        "ticket_id": ticket_id,
        "status": "open",
        "subject": subject,
        "category": category,
        "priority": priority,
        "eta_hours": _ETA_HOURS.get(category, 48),
        "url": f"https://support.configent.dev/tickets/{ticket_id}",
    }
    if tool_input.get("customer_email"):
        result["customer_email"] = str(tool_input["customer_email"]).strip()
    return result
