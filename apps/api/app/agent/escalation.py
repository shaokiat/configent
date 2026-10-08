"""The outcomes every engine shares: converse, escalate to a human, and file on confirmation.

Engine-agnostic in intent, support-graph-shaped in fact for now: `converse` reads
`state["grade"]` and the nodes log fixed levels. #17 decouples them.
"""
import time
from typing import TYPE_CHECKING

from langgraph.config import get_stream_writer
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app import tickets
from app.agent import platform
from app.agent.common import excerpt, trace_payload
from app.agent.platform import Deps, _model_step, _prompt, _step, _transcript
from app.models import Trace

if TYPE_CHECKING:  # annotation only: the engine imports this module, not the reverse
    from app.agent.engines.support_graph import TurnState

_TICKET_TOOL = "create_escalation_ticket"

_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "category": {
            "type": "string",
            "enum": [
                "account_config",
                "quota_or_billing",
                "incident",
                "access_request",
                "docs_gap",
                "other",
            ],
        },
        "product_area": {"type": "string", "enum": ["cloud_run", "gke", "iam", "other"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        "body": {"type": "string"},
    },
    "required": ["subject"],
    "additionalProperties": False,
}


_CONVERSE_FALLBACK = (
    "I answer Cloud Run, GKE and IAM questions from public Google Cloud documentation, with "
    "citations — and when something depends on your own project, I can raise it with the "
    "platform team. What are you working on?"
)


async def converse(state: "TurnState", runtime: Runtime[Deps]) -> dict:
    """The one path with no passages behind the reply; `grade.md` forbids platform facts in it."""
    d, t = runtime.context, time.monotonic()
    text = (state["grade"].get("reply") or "").strip() or _CONVERSE_FALLBACK
    await _step(d, "converse", t, level=1, reasoning=state["why"])
    get_stream_writer()(("text", {"delta": text}))
    return {"outcome": "converse", "answer": text, "segments": [{"text": text, "citations": []}]}


# ── Level 3 ──────────────────────────────────────────────────────────────────────────

_TICKET_DEFAULTS = {"category": "other", "product_area": "other", "priority": "normal"}

_CATEGORY_LABEL = {
    "account_config": "project configuration",
    "quota_or_billing": "quota or billing",
    "incident": "suspected incident",
    "access_request": "access request",
    "docs_gap": "documentation gap",
    "other": "other",
}


def _normalise_draft(draft: dict, *, question: str) -> dict:
    """Fill what the draft left out. An under-described ticket still reaches a human."""
    draft = dict(draft)
    draft["subject"] = (draft.get("subject") or "").strip() or excerpt(question)
    for key, value in _TICKET_DEFAULTS.items():
        draft[key] = draft.get(key) or value
    return draft


def _proposal_payload(draft: dict) -> dict:
    """What the confirm card renders. The draft itself stays in the checkpoint: the client
    confirms a run, it never posts back a ticket it could have edited."""
    return {k: draft.get(k, "") for k in ("subject", "category", "product_area", "priority", "body")}


def _proposal_reply(draft: dict) -> str:
    category = _CATEGORY_LABEL.get(draft.get("category", "other"), "other")
    return (
        "That one needs a human: it depends on your own project configuration, and my "
        "knowledge base is public Google Cloud documentation only.\n\n"
        f"I can open a **{category}** ticket for the platform team — "
        f'"{draft.get("subject", "")}". Say the word and I\'ll file it.'
    )


def _escalation_reply(ticket: dict, ok: bool) -> str:
    if not ok:
        return (
            "I couldn't reach the ticket system just now, so nothing was filed. Please retry "
            "shortly or raise it with the platform team directly."
        )
    eta = ticket.get("eta_hours")
    return (
        f"Done — I've opened **{ticket.get('ticket_id')}** with the "
        f"{ticket.get('queue', 'platform')} team"
        + (f", who aim to respond within {eta} hours" if eta else "")
        + f". You can follow it at {ticket.get('url')}."
    )


async def escalate(state: "TurnState", runtime: Runtime[Deps]) -> dict:
    """Draft the ticket and offer it. The model never places the call."""
    d, t = runtime.context, time.monotonic()
    raw, response = await platform._structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "ticket_draft"),
        user_content=(
            f"The assistant could not answer this from its documentation.\n"
            f"Reason: {state['why']}\n\n"
            f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
            f"User's message:\n{state['question']}"
        ),
        schema=_DRAFT_SCHEMA,
        max_tokens=768,
    )
    draft = _normalise_draft(raw, question=state["question"])
    await _model_step(
        d, state, "escalate", t, response,
        level=3,
        reasoning=state["why"],
        category=draft["category"],
        product_area=draft["product_area"],
        priority=draft["priority"],
    )
    text = _proposal_reply(draft)
    write = get_stream_writer()
    write(("ticket_proposal", {"run_id": state["run_id"], **_proposal_payload(draft)}))
    write(("text", {"delta": text}))
    return {
        "draft": draft,
        "outcome": "ticket",
        "answer": text,
        "segments": [{"text": text, "citations": []}],
    }


async def stage_ticket(draft: dict, *, run_id: str, stage_seq: int) -> dict:
    """File the ticket from Python: one call site, so one place to keep idempotent."""
    return await tickets.create_ticket(draft, run_id=run_id, stage_seq=stage_seq)


async def ticket(state: "TurnState", runtime: Runtime[Deps]) -> dict:
    """Wait for the user, then file.

    Its own node because `interrupt()` re-runs its node from the top on resume: anything
    before it in the same node would execute twice.
    """
    interrupt({"run_id": state["run_id"], **_proposal_payload(state["draft"])})
    d, t = runtime.context, time.monotonic()
    result = await stage_ticket(
        state["draft"],
        run_id=state["run_id"],
        stage_seq=d.recorder.next_seq("ticket"),
    )
    ok = "error" not in result
    d.db.add(
        Trace(
            conversation_id=state["conversation_id"],
            span_type="tool",
            tool_name=_TICKET_TOOL,
            input_=trace_payload(state["draft"]),
            output=trace_payload(result),
            latency_ms=int((time.monotonic() - t) * 1000),
        )
    )
    await _step(
        d, "ticket", t,
        status="ok" if ok else "failed",
        level=3,
        reasoning=f"filed as {result.get('ticket_id')}" if ok else str(result.get("error")),
        ticket_id=result.get("ticket_id"),
        url=result.get("url"),
        eta_hours=result.get("eta_hours"),
        queue=result.get("queue"),
    )
    return {"ticket": result}


def _after_ticket(state) -> str:  # unannotated: LangGraph resolves a branch's hints eagerly
    """A failed filing loops back to the pause, so the user can retry the same draft."""
    return "ticket" if "error" in state["ticket"] else END

