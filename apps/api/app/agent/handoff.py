"""The outcomes every template shares: converse, and the client's handoff when a turn can't be
answered — `decline` (a fixed message) or `escalate` → `ticket` (filed on confirmation).

They read only `platform.TurnState`. A template that wants `converse` to say something sets
`reply`; one that has tiers sets `level`. Templates route to `escalate`; `route` turns that
into `decline` for a client whose `handoff.mode` is `message`.
"""
import time

from langgraph.config import get_stream_writer
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app import tickets
from app.agent import platform
from app.agent.common import excerpt, trace_payload
from app.agent.platform import Deps, TurnState, _model_step, _prompt, _step, _transcript
from app.config.schema import ClientConfig, TicketHandoff
from app.models import Trace

_TICKET_TOOL = "create_escalation_ticket"


def _converse_fallback(cfg: ClientConfig) -> str:
    b = cfg.branding
    return f"I'm {b.assistant_name}. {b.tagline or 'What are you working on?'}"


async def converse(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """The one path with no evidence behind the reply; the grading prompt forbids tenant facts in it."""
    d, t = runtime.context, time.monotonic()
    text = (state.get("reply") or "").strip() or _converse_fallback(d.cfg)
    await _step(d, "converse", t, level=state.get("level"), reasoning=state["why"])
    get_stream_writer()(("text", {"delta": text}))
    return {"outcome": "converse", "answer": text, "segments": [{"text": text, "citations": []}]}


def route(state) -> str:  # unannotated: LangGraph resolves a branch's hints eagerly
    """Every template's edge function. The template decided the turn can't be answered; the
    client's handoff decides what happens next. The graph is compiled once per template, so
    the mode comes from the state (set by `stream_turn`), not from a client's config."""
    r = state["route"]
    return "decline" if r == "escalate" and state.get("handoff") == "message" else r


async def decline(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Say so, in the client's words. No model call, no ticket."""
    d, t = runtime.context, time.monotonic()
    text = d.cfg.handoff.message
    await _step(d, "decline", t, reasoning=state["why"])
    get_stream_writer()(("text", {"delta": text}))
    return {"outcome": "decline", "answer": text, "segments": [{"text": text, "citations": []}]}


# ── Level 3 ──────────────────────────────────────────────────────────────────────────

_TICKET_DEFAULTS = {"category": "other", "product_area": "other", "priority": "normal"}


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


def _proposal_reply(draft: dict, esc: TicketHandoff) -> str:
    category = esc.categories.get(draft.get("category", "other"), "other")
    return (
        f"{esc.preamble}\n\n"
        f"I can open a **{category}** ticket for the {esc.team} — "
        f'"{draft.get("subject", "")}". Say the word and I\'ll file it.'
    )


def _ticket_reply(ticket: dict, ok: bool, esc: TicketHandoff) -> str:
    if not ok:
        return (
            "I couldn't reach the ticket system just now, so nothing was filed. Please retry "
            f"shortly or raise it with the {esc.team} directly."
        )
    eta = ticket.get("eta_hours")
    # A queue may already be named for its team ("data-team"); don't say "team" twice.
    queue = (ticket.get("queue") or esc.queue or "support").removesuffix("-team")
    return (
        f"Done — I've opened **{ticket.get('ticket_id')}** with the {queue} team"
        + (f", who aim to respond within {eta} hours" if eta else "")
        + f". You can follow it at {ticket.get('url')}."
    )


async def escalate(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Draft the ticket and offer it. The model never places the call."""
    d, t = runtime.context, time.monotonic()
    raw, response = await platform._structured_call(
        d.aclient,
        model=d.cfg.structured_model,
        system=_prompt(d.cfg, "ticket_draft"),
        user_content=(
            f"The assistant could not answer this from its evidence.\n"
            f"Reason: {state['why']}\n\n"
            f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
            f"User's message:\n{state['question']}"
        ),
        schema=d.cfg.handoff.draft_schema,
        max_tokens=768,
    )
    draft = _normalise_draft(raw, question=state["question"])
    if d.cfg.handoff.queue:
        draft["queue"] = d.cfg.handoff.queue  # sent with the ticket; the service honours it
    await _model_step(
        d, state, "escalate", t, response, model=d.cfg.structured_model,
        level=3,  # "Level 3 is a human" holds for every template
        reasoning=state["why"],
        category=draft["category"],
        product_area=draft["product_area"],
        priority=draft["priority"],
    )
    text = _proposal_reply(draft, d.cfg.handoff)
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


async def ticket(state: TurnState, runtime: Runtime[Deps]) -> dict:
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

