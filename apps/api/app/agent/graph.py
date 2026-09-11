"""The support graph: three tiers of escalation, each route chosen in Python (D10).

    Level 1 · RAG             retrieve → grade ─┬─ answer | converse
    Level 2 · corrective RAG  rewrite → hybrid_retrieve → regrade ─┬─ answer
    Level 3 · human           escalate → ticket   (interrupt: the user confirms, then it files)

LangGraph owns two mechanisms: a checkpoint after every node, and the pause while a proposed
ticket waits for the user (`interrupt()`). It owns no decisions. `decide_level1` and
`decide_level2` are plain functions over YAML thresholds; the node stores the route and the
edge only reads it. The answering model is never sent a tool, so it cannot escalate (D2).

Citations cannot be combined with `output_config.format`, so `grade`, `rewrite` and
`escalate` take structured output and `answer` takes citations.
"""
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import anthropic
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import (
    UsageTotals,
    _attr_or_key,
    _collect_segments,
    _excerpt,
    _model_trace,
    _prepare_conversation,
    _trace_payload,
    _update_conversation_totals,
)
from app.config.schema import ClientConfig
from app.database import checkpoint_session
from app.models import Message, Run, Trace
from app.retrieval.search import Hit, hybrid_search, search
from app.tools.registry import get_tool_executor

logger = logging.getLogger("configent.graph")

_REPO_ROOT = Path(__file__).parents[4]
_TICKET_TOOL = "create_escalation_ticket"


class GraphCrash(SystemExit):
    """Raised by the CRASH_AFTER fault injector (D6). SystemExit so no `except Exception`
    swallows it."""


class RunUnavailable(Exception):
    """Unknown run, another client's run, or a run with no ticket offer to confirm. A 404
    that reveals nothing about which."""


class TurnState(TypedDict, total=False):
    """What the checkpointer saves. Plain JSON: hits are dicts, not `Hit`."""

    question: str
    history: list[dict]
    conversation_id: str
    run_id: str
    level: int  # the tier the current evidence came from
    hits: list[dict]
    top_similarity: float
    grade: dict
    queries: list[str]
    keywords: str
    route: str  # chosen by decide_level1 / decide_level2; the edges only read it
    why: str
    draft: dict
    ticket: dict
    outcome: str  # "answer" | "converse" | "ticket"
    answer: str
    segments: list[dict]
    citations: list[dict]


@dataclass
class Deps:
    """Per-request objects, passed as LangGraph `context`, which is never checkpointed."""

    cfg: ClientConfig
    client_id: str
    db: AsyncSession
    aclient: anthropic.AsyncAnthropic | None
    recorder: "RunRecorder"
    usage: UsageTotals = field(default_factory=UsageTotals)


# ── audit trail ──────────────────────────────────────────────────────────────────────


class RunRecorder:
    """Owns the `Run` row: the step trail the UI shows and a reloaded conversation replays.

    Each step commits through `checkpoint_session()`, never the request session, which
    rolls back on exactly the failure the trail has to survive (D3).
    """

    def __init__(self, run_id: str, conversation_id: str, client_id: str):
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.client_id = client_id
        self.steps: list[dict] = []

    @classmethod
    async def start(cls, conversation_id: str, client_id: str) -> "RunRecorder":
        async with checkpoint_session() as db:
            run = Run(
                conversation_id=conversation_id,
                client_id=client_id,
                status="running",
                current_stage="retrieve",
                steps=[],
                state={},
            )
            db.add(run)
            await db.flush()
            run_id = run.id
        return cls(run_id, conversation_id, client_id)

    @classmethod
    def from_run(cls, run: Run) -> "RunRecorder":
        recorder = cls(run.id, run.conversation_id, run.client_id)
        recorder.steps = list(run.steps or [])
        return recorder

    async def _persist(self, *, status: str, current_stage: str | None) -> None:
        async with checkpoint_session() as db:
            run = await db.get(Run, self.run_id)
            if run is None:  # pragma: no cover — the row is created before any step
                return
            run.steps = list(self.steps)
            run.status = status
            run.current_stage = current_stage

    def next_seq(self, stage: str) -> int:
        """The seq this stage's step will get. A stage that runs again straight after itself
        (a ticket retried after a failed filing) replaces its entry and keeps its seq, so the
        `{run_id}:{stage_seq}` idempotency key stays stable across the retry (D4)."""
        if self.steps and self.steps[-1]["stage"] == stage:
            return self.steps[-1]["seq"]
        return len(self.steps) + 1

    async def step(
        self,
        stage: str,
        *,
        status: str = "ok",
        started: float,
        reasoning: str | None = None,
        usage: UsageTotals | None = None,
        **extra: Any,
    ) -> dict:
        """Record one finished node and commit it. Returns the SSE payload."""
        seq = self.next_seq(stage)
        entry = {
            "seq": seq,
            "stage": stage,
            "status": status,
            "reasoning": reasoning,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "ts": datetime.now(UTC).isoformat(),
            **{k: v for k, v in extra.items() if v is not None},
        }
        if usage is not None:
            entry["tokens_in"] = usage.input_tokens
            entry["tokens_out"] = usage.output_tokens
            entry["cost_usd"] = round(usage.cost_usd, 6)
        if seq <= len(self.steps):
            self.steps[-1] = entry
        else:
            self.steps.append(entry)
        await self._persist(status="running", current_stage=stage)
        return entry

    async def finish(self, status: str) -> None:
        await self._persist(status=status, current_stage=None)


async def _step(d: Deps, stage: str, started: float, **extra: Any) -> None:
    """Record a step and stream it: one write, so the trail watched and stored can't drift."""
    get_stream_writer()(("step", await d.recorder.step(stage, started=started, **extra)))


async def _model_step(
    d: Deps, state: TurnState, stage: str, started: float, response: Any, **extra: Any
) -> None:
    """`_step` for a node that made a model call: also accrues its cost and traces it."""
    usage = UsageTotals()
    usage.add(response.usage)
    d.usage.add(response.usage)
    d.db.add(
        _model_trace(
            state["conversation_id"], response.usage, int((time.monotonic() - started) * 1000)
        )
    )
    await _step(d, stage, started, usage=usage, **extra)


def _maybe_crash(stage: str) -> None:
    """Fault injection (D6). Called by the stream consumer, never inside a node: asyncio
    treats a SystemExit raised in a task as fatal to the event loop."""
    if os.getenv("CRASH_AFTER") == stage:
        logger.warning("CRASH_AFTER=%s — exiting deliberately", stage)
        raise GraphCrash(f"CRASH_AFTER={stage}")


# ── model calls ──────────────────────────────────────────────────────────────────────


def _prompt(cfg: ClientConfig, name: str) -> str:
    """A stage prompt from beside the configured answer prompt."""
    return (cfg.system_prompt_path(_REPO_ROOT).parent / f"{name}.md").read_text()


async def _structured_call(
    aclient: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    user_content: str,
    schema: dict,
    max_tokens: int,
) -> tuple[dict, Any]:
    """One model call constrained to a JSON schema. Never combined with citations (400)."""
    response = await aclient.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = "".join(
        _attr_or_key(b, "text", "") for b in response.content if _attr_or_key(b, "type") == "text"
    )
    return json.loads(text), response


_GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        # Triage rides on the grade call (D9): no extra call, and made with the passages in
        # view rather than by a router that sees only the question.
        "kind": {"type": "string", "enum": ["question", "conversation"]},
        "supported": {"type": "boolean"},
        "confidence": {"type": "number"},
        "missing_info": {"type": "string"},
        "reasoning": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["kind", "supported", "confidence", "reasoning"],
    "additionalProperties": False,
}

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "string"},
    },
    "required": ["queries", "keywords"],
    "additionalProperties": False,
}

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


def _transcript(history: list[dict], turns: int = 6) -> str:
    """The last few readable turns, for triage, rewriting and drafting."""
    lines = [
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-turns:]
        if isinstance(m.get("content"), str)
    ]
    return "\n".join(lines) or "(none)"


# ── the decisions ────────────────────────────────────────────────────────────────────


def decide_level1(
    *, top_similarity: float, score: dict, n_hits: int, cfg: ClientConfig
) -> tuple[str, str]:
    """Route after Level 1. Plain Python; no model can override it.

    Answer only when both signals clear their thresholds (D2). Otherwise a conversation goes
    to `converse`, and anything else to Level 2 — or to Level 3 if corrective is off.
    """
    confidence = float(score.get("confidence", 0.0))
    agent = cfg.agent
    if n_hits and top_similarity >= agent.escalate_below and confidence >= agent.confidence_threshold:
        return "answer", (
            f"similarity {top_similarity:.2f} and groundedness {confidence:.2f} both above "
            f"threshold"
        )
    # `converse` has to be asked for. A missing or malformed kind is a question.
    if score.get("kind") == "conversation":
        return "converse", "not a support request — answered conversationally, no ticket"
    if not n_hits:
        why = "retrieval returned no passages above the drop floor"
    elif top_similarity < agent.escalate_below:
        why = f"top similarity {top_similarity:.2f} < escalate_below {agent.escalate_below}"
    else:
        why = f"groundedness {confidence:.2f} < confidence_threshold {agent.confidence_threshold}"
    return ("rewrite" if agent.corrective.enabled else "escalate"), why


def decide_level2(*, score: dict, n_hits: int, cfg: ClientConfig) -> tuple[str, str]:
    """Route after Level 2: answer if the new evidence grounds an answer, else a human.

    No cosine floor here: keyword matches carry no cosine similarity, and gating on one would
    reject exactly what this tier adds. Groundedness still has to clear its threshold.
    """
    confidence = float(score.get("confidence", 0.0))
    threshold = cfg.agent.confidence_threshold
    if n_hits and confidence >= threshold:
        return "answer", (
            f"groundedness {confidence:.2f} ≥ confidence_threshold {threshold} after "
            f"corrective retrieval"
        )
    if not n_hits:
        return "escalate", "corrective retrieval also returned no passages"
    return "escalate", (
        f"groundedness {confidence:.2f} < confidence_threshold {threshold} after corrective "
        f"retrieval"
    )


# ── nodes ────────────────────────────────────────────────────────────────────────────


def _hit_dict(hit: Hit) -> dict:
    return {
        "text": hit.text,
        "document_title": hit.document_title,
        "source_uri": hit.source_uri,
        "similarity": round(hit.similarity, 4),
    }


async def retrieve(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Level 1: pgvector top-k. No model call — the deterministic half of the guardrail."""
    d, t = runtime.context, time.monotonic()
    hits = await search(
        d.db,
        client_id=d.client_id,
        query=state["question"],
        k=5,
        floor=d.cfg.agent.retrieval_drop_floor,
    )
    top = hits[0].similarity if hits else 0.0
    await _step(
        d, "retrieve", t,
        level=1,
        reasoning=(
            f"Best match: {hits[0].document_title}"
            if hits
            else f"Nothing above the drop floor ({d.cfg.agent.retrieval_drop_floor})"
        ),
        n_hits=len(hits),
        top_similarity=round(top, 4),
        sources=[h.source_uri for h in hits],
    )
    return {"level": 1, "hits": [_hit_dict(h) for h in hits], "top_similarity": top}


async def grade(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Groundedness and triage in one structured call, then the Python decision.

    The same node runs as `grade` at Level 1 and `regrade` at Level 2. With zero passages
    the call still runs, so a greeting is recognised, but its confidence is overwritten
    with 0: a model rating nothing invents a number (D2).
    """
    d, t = runtime.context, time.monotonic()
    hits, level = state["hits"], state["level"]
    passages = "\n\n".join(
        f"[{i + 1}] {h['document_title']} ({h['source_uri']})\n{h['text']}"
        for i, h in enumerate(hits)
    ) or "(none — retrieval returned nothing above the drop floor)"
    score, response = await _structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "grade"),
        user_content=(
            f"Question:\n{state['question']}\n\n"
            f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
            f"Retrieved passages:\n{passages}"
        ),
        schema=_GRADE_SCHEMA,
        max_tokens=768,
    )
    if not hits:
        score = {**score, "confidence": 0.0, "supported": False}
    if level == 1:
        route, why = decide_level1(
            top_similarity=state["top_similarity"], score=score, n_hits=len(hits), cfg=d.cfg
        )
    else:
        route, why = decide_level2(score=score, n_hits=len(hits), cfg=d.cfg)
    await _model_step(
        d, state, "grade" if level == 1 else "regrade", t, response,
        level=level,
        reasoning=score.get("reasoning"),
        confidence=round(float(score.get("confidence", 0.0)), 4),
        kind=score.get("kind"),
    )
    return {"grade": score, "route": route, "why": why}


_CONVERSE_FALLBACK = (
    "I answer Cloud Run, GKE and IAM questions from public Google Cloud documentation, with "
    "citations — and when something depends on your own project, I can raise it with the "
    "platform team. What are you working on?"
)


async def converse(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """The one path with no passages behind the reply; `grade.md` forbids platform facts in it."""
    d, t = runtime.context, time.monotonic()
    text = (state["grade"].get("reply") or "").strip() or _CONVERSE_FALLBACK
    await _step(d, "converse", t, level=1, reasoning=state["why"])
    get_stream_writer()(("text", {"delta": text}))
    return {"outcome": "converse", "answer": text, "segments": [{"text": text, "citations": []}]}


async def rewrite(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Level 2: reformulate with the conversation in view — semantic variants for dense
    search, exact identifiers for keyword search."""
    d, t = runtime.context, time.monotonic()
    n = d.cfg.agent.corrective.query_rewrites
    out, response = await _structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "rewrite"),
        user_content=(
            f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
            f"Latest message:\n{state['question']}\n\n"
            f"Why the first search failed: {state['why']}\n\nWrite {n} queries."
        ),
        schema=_REWRITE_SCHEMA,
        max_tokens=512,
    )
    queries = [q.strip() for q in out.get("queries") or [] if isinstance(q, str) and q.strip()][:n]
    keywords = str(out.get("keywords") or "").strip()
    await _model_step(
        d, state, "rewrite", t, response,
        level=2,
        reasoning=f"Level 1 fell short ({state['why']}), so searching again",
        queries=queries,
        keywords=keywords or None,
    )
    return {"queries": queries, "keywords": keywords}


async def hybrid_retrieve(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    hits = await hybrid_search(
        d.db,
        client_id=d.client_id,
        queries=[state["question"], *state.get("queries", [])],
        keywords=state.get("keywords", ""),
        k=5,
        floor=d.cfg.agent.retrieval_drop_floor,
    )
    await _step(
        d, "hybrid_retrieve", t,
        level=2,
        reasoning=(
            f"Best match: {hits[0].document_title}"
            if hits
            else "Keyword and semantic search found nothing"
        ),
        n_hits=len(hits),
        sources=[h.source_uri for h in hits],
    )
    return {"level": 2, "hits": [_hit_dict(h) for h in hits]}


def answer_request_kwargs(
    cfg: ClientConfig, *, hits: list[dict], question: str, history: list[dict]
) -> dict:
    """Assemble the answering call. Note what is absent: `tools` (D2)."""
    search_results = [
        {
            "type": "search_result",
            "source": h["source_uri"],
            "title": h["document_title"],
            "content": [{"type": "text", "text": h["text"]}],
            # The API requires citations on all search results or none.
            "citations": {"enabled": True},
        }
        for h in hits
    ]
    return {
        "model": cfg.agent.model,
        "max_tokens": cfg.agent.max_tokens,
        "system": [
            {"type": "text", "text": _prompt(cfg, "answer"), "cache_control": {"type": "ephemeral"}}
        ],
        "messages": history
        + [{"role": "user", "content": search_results + [{"type": "text", "text": question}]}],
    }


async def answer(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Stream a cited answer from whichever tier's passages cleared the guardrail."""
    d, t = runtime.context, time.monotonic()
    write = get_stream_writer()
    citation_index = 0
    kwargs = answer_request_kwargs(
        d.cfg, hits=state["hits"], question=state["question"], history=state.get("history", [])
    )
    async with d.aclient.messages.stream(**kwargs) as stream:
        async for event in stream:
            if getattr(event, "type", "") != "content_block_delta":
                continue
            if event.delta.type == "text_delta":
                write(("text", {"delta": event.delta.text}))
            elif event.delta.type == "citations_delta":
                citation_index += 1
                cit = event.delta.citation
                write((
                    "citation",
                    {
                        "index": citation_index,
                        "source": _attr_or_key(cit, "source"),
                        "title": _attr_or_key(cit, "title"),
                        "cited_text": _excerpt(_attr_or_key(cit, "cited_text") or ""),
                    },
                ))
        response = await stream.get_final_message()
    text, citations, segments = _collect_segments(response)
    await _model_step(
        d, state, "answer", t, response,
        level=state["level"],
        reasoning=state["why"],
        n_citations=len(citations),
    )
    return {"outcome": "answer", "answer": text, "citations": citations, "segments": segments}


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
    draft["subject"] = (draft.get("subject") or "").strip() or _excerpt(question)
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


async def escalate(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Draft the ticket and offer it. The model never places the call."""
    d, t = runtime.context, time.monotonic()
    raw, response = await _structured_call(
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


async def stage_ticket(
    draft: dict, *, db: AsyncSession, client_id: str, run_id: str, stage_seq: int
) -> dict:
    """File the ticket: Python calls the executor directly, one call site to keep idempotent."""
    executor = get_tool_executor(_TICKET_TOOL)
    return await executor(draft, client_id=client_id, db=db, run_id=run_id, stage_seq=stage_seq)


async def ticket(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Wait for the user, then file.

    Its own node because `interrupt()` re-runs its node from the top on resume: anything
    before it in the same node would execute twice.
    """
    interrupt({"run_id": state["run_id"], **_proposal_payload(state["draft"])})
    d, t = runtime.context, time.monotonic()
    result = await stage_ticket(
        state["draft"],
        db=d.db,
        client_id=d.client_id,
        run_id=state["run_id"],
        stage_seq=d.recorder.next_seq("ticket"),
    )
    ok = "error" not in result
    d.db.add(
        Trace(
            conversation_id=state["conversation_id"],
            span_type="tool",
            tool_name=_TICKET_TOOL,
            input_=_trace_payload(state["draft"]),
            output=_trace_payload(result),
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


# ── the graph ────────────────────────────────────────────────────────────────────────


def _route(state: TurnState) -> str:
    return state["route"]


def _after_ticket(state: TurnState) -> str:
    """A failed filing loops back to the pause, so the user can retry the same draft."""
    return "ticket" if "error" in state["ticket"] else END


def _build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("converse", converse)
    g.add_node("rewrite", rewrite)
    g.add_node("hybrid_retrieve", hybrid_retrieve)
    g.add_node("regrade", grade)
    g.add_node("answer", answer)
    g.add_node("escalate", escalate)
    g.add_node("ticket", ticket)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", _route, ["answer", "converse", "rewrite", "escalate"])
    g.add_edge("rewrite", "hybrid_retrieve")
    g.add_edge("hybrid_retrieve", "regrade")
    g.add_conditional_edges("regrade", _route, ["answer", "escalate"])
    g.add_edge("answer", END)
    g.add_edge("converse", END)
    g.add_edge("escalate", "ticket")
    g.add_conditional_edges("ticket", _after_ticket, ["ticket", END])
    return g


_builder = _build()
_graph = None


def use_checkpointer(saver) -> None:
    """Compile the graph against a checkpointer: Postgres in the app, in-memory in tests."""
    global _graph
    _graph = _builder.compile(checkpointer=saver)


def _compiled():
    if _graph is None:
        raise RuntimeError(
            "The support graph has no checkpointer: the app lifespan did not run "
            "postgres_checkpointer(), and the ticket pause cannot work without one."
        )
    return _graph


@asynccontextmanager
async def postgres_checkpointer(database_url: str):
    """Install the Postgres saver for the app's lifetime. psycopg 3, beside asyncpg, because
    langgraph-checkpoint-postgres is written against it; `setup()` is idempotent."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conninfo = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    # ponytail: one shared connection with a lock. Swap to an AsyncConnectionPool if
    # concurrent turns contend on it, or if a dropped connection needs to heal itself.
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()
        use_checkpointer(saver)
        yield


def _thread(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


# ── entry points ─────────────────────────────────────────────────────────────────────


async def stream_graph(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one turn, yielding SSE `(event, data)` tuples: `run`, a `step` per node, `text` /
    `citation` deltas, `ticket_proposal` when a human is needed, then one `done`.

    On failure the stream emits `error` instead of `done`: the HTTP status went out long
    ago, and a stream that simply stops looks like a finished turn to the browser.
    """
    started = time.monotonic()
    recorder = None
    try:
        conversation_id, history = await _prepare_conversation(db, client_id, conversation_id)
        recorder = await RunRecorder.start(conversation_id, client_id)
        run_id = recorder.run_id
        yield ("run", {"run_id": run_id, "conversation_id": conversation_id})

        deps = Deps(cfg, client_id, db, anthropic.AsyncAnthropic(), recorder)
        initial = {
            "question": user_message,
            "history": history,
            "conversation_id": conversation_id,
            "run_id": run_id,
        }
        async for event, data in _compiled().astream(
            initial, _thread(run_id), context=deps, stream_mode="custom", durability="sync"
        ):
            yield event, data
            if event == "step":
                _maybe_crash(data["stage"])

        values = (await _compiled().aget_state(_thread(run_id))).values
        db.add(Message(conversation_id=conversation_id, role="user", content=user_message))
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=values["answer"],
                citations={"segments": values["segments"]},
                run_id=run_id,  # the join back to this turn's step trail, for reload
            )
        )
        await _update_conversation_totals(db, conversation_id, deps.usage)
        await db.commit()
        await recorder.finish("completed")
        yield (
            "done",
            {
                "conversation_id": conversation_id,
                "run_id": run_id,
                "outcome": values["outcome"],
                "confidence": round(float(values["grade"].get("confidence", 0.0)), 4),
                "ticket_id": None,
                "input_tokens": deps.usage.input_tokens,
                "output_tokens": deps.usage.output_tokens,
                "cache_creation_input_tokens": deps.usage.cache_creation_input_tokens,
                "cache_read_input_tokens": deps.usage.cache_read_input_tokens,
                "cost_usd": round(deps.usage.cost_usd, 6),
                "latency_ms": int((time.monotonic() - started) * 1000),
            },
        )
    except GraphCrash:
        raise
    except Exception as exc:
        logger.exception("Graph turn failed (client=%s)", client_id)
        await db.rollback()
        if recorder:
            await recorder.finish("failed")
        # Detail stays in the logs; the client only ever sees a generic message.
        message = (
            f"Upstream API error: {exc.__class__.__name__}"
            if isinstance(exc, anthropic.APIError)
            else "An internal error occurred. Please try again."
        )
        yield ("error", {"message": message})


async def run_graph(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> dict:
    """Non-streaming entry point: drain the stream, so the two paths cannot drift. Returns
    the final state."""
    run_id = None
    async for event, data in stream_graph(
        user_message, cfg=cfg, client_id=client_id, conversation_id=conversation_id, db=db
    ):
        if event == "run":
            run_id = data["run_id"]
        elif event == "error":
            raise RuntimeError(data["message"])
    return (await _compiled().aget_state(_thread(run_id))).values


async def confirm_ticket(
    *, run_id: str, client_id: str, cfg: ClientConfig, db: AsyncSession
) -> dict:
    """File the ticket this run proposed, once the user has said yes (D9).

    Resumes the graph paused on `interrupt()`. The draft comes from the checkpoint, not the
    request. Both D4 guards hold: a filed `ticket_id` short-circuits a second confirmation,
    and the `{run_id}:{stage_seq}` idempotency key covers a retry that races it.
    """
    run = await db.get(Run, run_id)
    if run is None or run.client_id != client_id:
        raise RunUnavailable(f"Run {run_id!r} not found")
    graph, thread = _compiled(), _thread(run_id)
    snapshot = await graph.aget_state(thread)
    filed = snapshot.values.get("ticket") or {}
    if filed.get("ticket_id"):
        return {"ticket_id": filed["ticket_id"], "reply": None, "already_filed": True}
    if not snapshot.interrupts:
        raise RunUnavailable(f"Run {run_id!r} did not propose a ticket")

    recorder = RunRecorder.from_run(run)
    values = await graph.ainvoke(
        Command(resume=True), thread, context=Deps(cfg, client_id, db, None, recorder),
        durability="sync",
    )
    result = values["ticket"]
    ok = "error" not in result
    await recorder.finish("completed")

    reply = _escalation_reply(result, ok)
    # Its own assistant turn, so reloading the conversation shows the confirmation.
    db.add(
        Message(
            conversation_id=run.conversation_id,
            role="assistant",
            content=reply,
            citations={"segments": [{"text": reply, "citations": []}]},
            run_id=run.id,
        )
    )
    await db.commit()
    return {
        "ok": ok,
        "ticket_id": result.get("ticket_id"),
        "url": result.get("url"),
        "queue": result.get("queue"),
        "eta_hours": result.get("eta_hours"),
        "reply": reply,
        "step": recorder.steps[-1],
        "already_filed": False,
    }
