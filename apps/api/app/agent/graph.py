"""The support graph: three tiers of escalation, each route chosen in Python (D10).

    Level 1 · RAG             retrieve → grade ─┬─ answer     (cited, no tools)
                                                ├─ converse   (no ticket)
                                                └─ ▼
    Level 2 · corrective RAG  rewrite → hybrid_retrieve → regrade ─┬─ answer
                                                                   └─ ▼
    Level 3 · human           escalate → ticket   (interrupt: the user confirms, then it files)

LangGraph owns two things that were hand-built before it: a checkpoint after every node, so
a crashed run resumes where it stopped, and the pause while a proposed ticket waits for the
user (`interrupt()`). It does not own a single decision. `decide_level1` and `decide_level2`
are plain functions comparing state against YAML thresholds; the node stores the route and
the edge only reads it. A model cannot be talked out of an `if` statement (D2).

Properties that fall out of the structure rather than out of prompting:

1. Retrieval always happens. It is a node, not a tool the model may skip.
2. The answering model is never sent a tool definition, so it cannot escalate (D2).
3. Nothing is filed until the user confirms, and a ticket is filed once (D4, D9).
4. A greeting leaves at Level 1. Triage is a field on the grade call, which sees the
   passages, so there is still no intent router in front of retrieval (D9).

Two API constraints still shape the node boundaries: `search_result` blocks are valid as
top-level user content, and citations cannot be combined with `output_config.format`. So
`grade`, `rewrite` and `escalate` take structured output, and `answer` takes citations.
"""
import json
import logging
import operator
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

import anthropic
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import (
    UsageTotals,
    _attr_or_key,
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

# Node names, in order. Also the vocabulary of the SSE `step` events and CRASH_AFTER.
STAGES = (
    "retrieve", "grade", "converse", "rewrite", "hybrid_retrieve", "regrade",
    "answer", "escalate", "ticket",
)


class GraphCrash(SystemExit):
    """Raised by the CRASH_AFTER fault injector (D6). SystemExit so no `except Exception`
    swallows it — a swallowed crash proves nothing about resume."""


class RunUnavailable(Exception):
    """No such run for this client, or nothing to do with it — unknown id, another
    client's run, a turn that proposed no ticket, a run with nothing left to resume.
    Surfaces as a 404 that reveals nothing about which."""


@dataclass
class TurnResult:
    """What the non-streaming endpoint returns. Assembled in Python, not generated:
    citations rule out structured output on the answer call."""

    conversation_id: str
    run_id: str
    answer: str = ""
    segments: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    outcome: str = "answer"  # "answer" | "converse" | "ticket"
    ticket_id: str | None = None


# ── state and dependencies ───────────────────────────────────────────────────────────


class TurnState(TypedDict, total=False):
    """Everything the checkpointer persists. Plain JSON only — hits are dicts, not `Hit`
    — so a checkpoint written by one release still loads in the next."""

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
    outcome: str
    answer: str
    segments: list[dict]
    citations: list[dict]
    usage: Annotated[list[dict], operator.add]


@dataclass
class Deps:
    """Per-request objects the nodes need. Passed as LangGraph `context`, which is never
    checkpointed — a session or an HTTP client has no business in saved state."""

    cfg: ClientConfig
    client_id: str
    db: AsyncSession
    aclient: anthropic.AsyncAnthropic | None
    recorder: "RunRecorder"


# ── audit trail ──────────────────────────────────────────────────────────────────────


class RunRecorder:
    """Owns the `Run` row: the step trail the UI shows and a reloaded conversation replays.

    The checkpointer is what resumes a run; this is what a person reads. Each step commits
    through `checkpoint_session()`, never the request session, which rolls back on exactly
    the failure the trail has to survive (D3).
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
                current_stage=STAGES[0],
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
        """The seq this stage's step will get.

        A node that runs again straight after itself — re-run on resume because the crash
        landed before its checkpoint, or a ticket retried after a failed filing — reuses
        its seq and replaces its entry. That keeps the trail free of duplicates, and it
        keeps the ticket's `{run_id}:{stage_seq}` idempotency key stable across the re-run
        that could otherwise file twice (D4).
        """
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


async def _step(d: Deps, stage: str, started: float, **extra: Any) -> dict:
    """Record a step and stream it. The trail the user watches and the trail that is
    stored are one write, so they cannot drift."""
    entry = await d.recorder.step(stage, started=started, **extra)
    get_stream_writer()(("step", entry))
    return entry


def _maybe_crash(stage: str) -> None:
    """Fault injection for the resume demo (D6). Called by the consumer after a step is
    streamed, never inside a node: asyncio treats a SystemExit raised in a task as fatal
    to the event loop, not as a crash of this run."""
    if os.getenv("CRASH_AFTER") == stage:
        logger.warning("CRASH_AFTER=%s — exiting deliberately", stage)
        raise GraphCrash(f"CRASH_AFTER={stage}")


# ── model calls ──────────────────────────────────────────────────────────────────────


def _prompt(cfg: ClientConfig, name: str) -> str:
    """Load a stage prompt that sits next to the configured answer prompt. One file per
    stage, because the grade prompt is the guardrail and has to be readable on its own."""
    return (cfg.system_prompt_path(_REPO_ROOT).parent / f"{name}.md").read_text()


_USAGE_KEYS = (
    "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
)


def _usage_dict(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    return {k: getattr(usage, k, 0) or 0 for k in _USAGE_KEYS}


def _totals(usages: list[dict]) -> UsageTotals:
    totals = UsageTotals()
    for u in usages:
        totals.add(SimpleNamespace(**u))
    return totals


def _record_trace(d: Deps, conversation_id: str, response: Any, started: float) -> None:
    d.db.add(
        _model_trace(
            conversation_id,
            getattr(response, "usage", None),
            int((time.monotonic() - started) * 1000),
        )
    )


async def _structured_call(
    aclient: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    user_content: list[dict] | str,
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
        # Triage rides on the grade call (D9): no extra call, and it is made with the
        # passages in view rather than by a router that sees only the question.
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

# Filled in when the draft leaves a field out. An under-described ticket still reaches a
# human, which is the failure mode worth having.
_TICKET_DEFAULTS = {"category": "other", "product_area": "other", "priority": "normal"}


def _transcript(history: list[dict], turns: int = 6) -> str:
    """The last few readable turns, for the two calls that need context: triage (is this a
    follow-up?) and rewriting (what does "that" refer to?)."""
    lines = [
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-turns:]
        if isinstance(m.get("content"), str)
    ]
    return "\n".join(lines) or "(none)"


async def _grade_call(d: Deps, question: str, hits: list[dict], history: list[dict]):
    """Groundedness and triage in one structured call — the model half of the guardrail.

    With zero passages the call still runs, because a greeting still has to be recognised,
    but its confidence is overwritten with 0 in Python: a model rating nothing invents a
    number (D2).
    """
    passages = "\n\n".join(
        f"[{i + 1}] {h['document_title']} ({h['source_uri']})\n{h['text']}"
        for i, h in enumerate(hits)
    ) or "(none — retrieval returned nothing above the drop floor)"
    user = (
        f"Question:\n{question}\n\nRecent conversation:\n{_transcript(history)}"
        f"\n\nRetrieved passages:\n{passages}"
    )
    score, response = await _structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "grade"),
        user_content=user,
        schema=_GRADE_SCHEMA,
        max_tokens=768,
    )
    if not hits:
        score = {**score, "confidence": 0.0, "supported": False}
    return score, response


# ── the decisions ────────────────────────────────────────────────────────────────────


def decide_level1(
    *, top_similarity: float, score: dict, n_hits: int, cfg: ClientConfig
) -> tuple[str, str]:
    """Route after Level 1. Plain Python; no model is consulted and none can override it.

    Answer only when **both** signals clear their thresholds (D2). Otherwise a turn the
    grader called conversation goes to `converse`, and anything else goes to Level 2 — or
    straight to Level 3 when the client has turned corrective retrieval off.
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
        why = (
            f"groundedness {confidence:.2f} < confidence_threshold "
            f"{agent.confidence_threshold}"
        )
    return ("rewrite" if agent.corrective.enabled else "escalate"), why


def decide_level2(*, score: dict, n_hits: int, cfg: ClientConfig) -> tuple[str, str]:
    """Route after Level 2: answer if the corrected evidence grounds an answer, else a human.

    `escalate_below` does not apply here. It is a cosine floor, and the passages Level 2
    exists to find are the keyword matches dense retrieval ranked low — gating them on
    cosine would reject exactly what this tier adds. The groundedness check still stands,
    and the answer is still cited from the passages.
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


# ── Level 1 ──────────────────────────────────────────────────────────────────────────


def _retrieval_query(user_message: str, history: list[dict]) -> str:
    """Level 1's embedding query: the message, with the previous user turn prepended.

    Free, and enough for most follow-ups. The ones it cannot fix fail Level 1 and get a
    real rewrite at Level 2.
    """
    previous = [m for m in history if m.get("role") == "user"]
    if not previous or not isinstance(previous[-1].get("content"), str):
        return user_message
    return f"{previous[-1]['content']}\n{user_message}"


def _hit_dict(hit: Hit) -> dict:
    return {
        "text": hit.text,
        "document_title": hit.document_title,
        "source_uri": hit.source_uri,
        "similarity": round(hit.similarity, 4),
    }


async def retrieve(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """pgvector top-k. No model call — the deterministic half of the guardrail."""
    d, t = runtime.context, time.monotonic()
    hits = await search(
        d.db,
        client_id=d.client_id,
        query=_retrieval_query(state["question"], state.get("history", [])),
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
    d, t = runtime.context, time.monotonic()
    score, response = await _grade_call(
        d, state["question"], state["hits"], state.get("history", [])
    )
    _record_trace(d, state["conversation_id"], response, t)
    route, why = decide_level1(
        top_similarity=state["top_similarity"], score=score, n_hits=len(state["hits"]), cfg=d.cfg
    )
    await _step(
        d, "grade", t,
        level=1,
        reasoning=score.get("reasoning"),
        confidence=round(float(score.get("confidence", 0.0)), 4),
        supported=score.get("supported"),
        missing_info=score.get("missing_info"),
        kind=score.get("kind"),
        usage=_totals([_usage_dict(response)]),
    )
    return {"grade": score, "route": route, "why": why, "usage": [_usage_dict(response)]}


_CONVERSE_FALLBACK = (
    "I answer Cloud Run, GKE and IAM questions from public Google Cloud documentation, with "
    "citations — and when something depends on your own project, I can raise it with the "
    "platform team. What are you working on?"
)


async def converse(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """The one path with no passages in front of the reply. `grade.md` forbids stating a
    platform fact in it, which is what keeps this from being a hole in the grounding."""
    d, t = runtime.context, time.monotonic()
    text = (state["grade"].get("reply") or "").strip() or _CONVERSE_FALLBACK
    await _step(d, "converse", t, level=1, reasoning=state["why"], route="converse")
    get_stream_writer()(("text", {"delta": text}))
    return {"outcome": "converse", "answer": text, "segments": [{"text": text, "citations": []}]}


# ── Level 2 ──────────────────────────────────────────────────────────────────────────


async def rewrite(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Reformulate the question with the conversation in view: semantic variants for the
    dense side, and the exact identifiers for the keyword side."""
    d, t = runtime.context, time.monotonic()
    n = d.cfg.agent.corrective.query_rewrites
    user = (
        f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
        f"Latest message:\n{state['question']}\n\n"
        f"Why the first search failed: {state['why']}\n\nWrite {n} queries."
    )
    out, response = await _structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "rewrite"),
        user_content=user,
        schema=_REWRITE_SCHEMA,
        max_tokens=512,
    )
    _record_trace(d, state["conversation_id"], response, t)
    queries = [q.strip() for q in out.get("queries") or [] if isinstance(q, str) and q.strip()][:n]
    keywords = str(out.get("keywords") or "").strip()
    await _step(
        d, "rewrite", t,
        level=2,
        reasoning=f"Level 1 fell short ({state['why']}), so searching again",
        queries=queries,
        keywords=keywords or None,
        usage=_totals([_usage_dict(response)]),
    )
    return {"queries": queries, "keywords": keywords, "usage": [_usage_dict(response)]}


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
            f"Best match: {hits[0].document_title}" if hits else "Keyword and semantic search found nothing"
        ),
        n_hits=len(hits),
        sources=[h.source_uri for h in hits],
    )
    return {
        "level": 2,
        "hits": [_hit_dict(h) for h in hits],
        "top_similarity": max((h.similarity for h in hits), default=0.0),
    }


async def regrade(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    score, response = await _grade_call(
        d, state["question"], state["hits"], state.get("history", [])
    )
    _record_trace(d, state["conversation_id"], response, t)
    route, why = decide_level2(score=score, n_hits=len(state["hits"]), cfg=d.cfg)
    await _step(
        d, "regrade", t,
        level=2,
        reasoning=score.get("reasoning"),
        confidence=round(float(score.get("confidence", 0.0)), 4),
        supported=score.get("supported"),
        missing_info=score.get("missing_info"),
        usage=_totals([_usage_dict(response)]),
    )
    return {"grade": score, "route": route, "why": why, "usage": [_usage_dict(response)]}


# ── the answer ───────────────────────────────────────────────────────────────────────


def _search_result_blocks(hits: list[dict]) -> list[dict]:
    """Hits as `search_result` blocks. Citations on all or none, per the API."""
    return [
        {
            "type": "search_result",
            "source": h["source_uri"],
            "title": h["document_title"],
            "content": [{"type": "text", "text": h["text"]}],
            "citations": {"enabled": True},
        }
        for h in hits
    ]


def answer_request_kwargs(
    cfg: ClientConfig, *, hits: list[dict], question: str, history: list[dict]
) -> dict:
    """Assemble the answering call. Note what is absent: `tools`. The answering model cannot
    file a ticket (D2), and the tests assert it."""
    content = _search_result_blocks(hits) + [{"type": "text", "text": question}]
    return {
        "model": cfg.agent.model,
        "max_tokens": cfg.agent.max_tokens,
        "system": [
            {"type": "text", "text": _prompt(cfg, "answer"), "cache_control": {"type": "ephemeral"}}
        ],
        "messages": history + [{"role": "user", "content": content}],
    }


def _collect_segments(response: Any) -> tuple[str, list[dict], list[dict]]:
    """Map the answer's text blocks into (text, citations, segments) — the shape the
    frontend renders and history stores."""
    text, citations, segments = "", [], []
    for block in response.content:
        if _attr_or_key(block, "type") != "text":
            continue
        block_text = _attr_or_key(block, "text", "")
        text += block_text
        cits = [
            b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else b
            for b in (_attr_or_key(block, "citations") or [])
        ]
        citations.extend(cits)
        segments.append(
            {
                "text": block_text,
                "citations": [
                    {
                        "source": c.get("source"),
                        "title": c.get("title"),
                        "cited_text": _excerpt(c.get("cited_text") or ""),
                    }
                    for c in cits
                ],
            }
        )
    return text, citations, segments


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
            dtype = getattr(event.delta, "type", "")
            if dtype == "text_delta":
                write(("text", {"delta": event.delta.text}))
            elif dtype == "citations_delta":
                citation_index += 1
                cit = event.delta.citation
                write(
                    (
                        "citation",
                        {
                            "index": citation_index,
                            "source": _attr_or_key(cit, "source"),
                            "title": _attr_or_key(cit, "title"),
                            "cited_text": _excerpt(_attr_or_key(cit, "cited_text") or ""),
                        },
                    )
                )
        response = await stream.get_final_message()
    _record_trace(d, state["conversation_id"], response, t)
    text, citations, segments = _collect_segments(response)
    await _step(
        d, "answer", t,
        level=state.get("level", 1),
        reasoning=state["why"],
        n_citations=len(citations),
        usage=_totals([_usage_dict(response)]),
    )
    return {
        "outcome": "answer",
        "answer": text,
        "citations": citations,
        "segments": segments,
        "usage": [_usage_dict(response)],
    }


# ── Level 3 ──────────────────────────────────────────────────────────────────────────


def _normalise_draft(draft: dict, *, question: str) -> dict:
    draft = dict(draft)
    draft["subject"] = (draft.get("subject") or "").strip() or _excerpt(question)
    for key, value in _TICKET_DEFAULTS.items():
        draft[key] = draft.get(key) or value
    return draft


_CATEGORY_LABEL = {
    "account_config": "project configuration",
    "quota_or_billing": "quota or billing",
    "incident": "suspected incident",
    "access_request": "access request",
    "docs_gap": "documentation gap",
    "other": "other",
}


def _proposal_payload(draft: dict) -> dict:
    """The fields the confirm card renders. The draft stays server-side, in the checkpoint:
    the client confirms a run, it never posts back a ticket it could have edited."""
    return {
        "subject": draft.get("subject", ""),
        "category": draft.get("category", "other"),
        "product_area": draft.get("product_area", "other"),
        "priority": draft.get("priority", "normal"),
        "body": draft.get("body", ""),
    }


def _proposal_reply(draft: dict) -> str:
    """What the user sees instead of a filed ticket: why a human is needed, and an offer."""
    category = _CATEGORY_LABEL.get(draft.get("category", "other"), "other")
    return (
        "That one needs a human: it depends on your own project configuration, and my "
        "knowledge base is public Google Cloud documentation only.\n\n"
        f"I can open a **{category}** ticket for the platform team — "
        f'"{draft.get("subject", "")}". Say the word and I\'ll file it.'
    )


def _escalation_reply(ticket: dict, ok: bool) -> str:
    """What the user sees once they have confirmed."""
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
    """Draft the ticket and offer it. Structured output; the model never places the call,
    and never decides whether the turn was answerable — the decide functions did."""
    d, t = runtime.context, time.monotonic()
    user = (
        f"The assistant could not answer this from its documentation.\n"
        f"Reason: {state['why']}\n\nRecent conversation:\n{_transcript(state.get('history', []))}"
        f"\n\nUser's message:\n{state['question']}"
    )
    raw, response = await _structured_call(
        d.aclient,
        model=d.cfg.agent.model,
        system=_prompt(d.cfg, "ticket_draft"),
        user_content=user,
        schema=_DRAFT_SCHEMA,
        max_tokens=768,
    )
    _record_trace(d, state["conversation_id"], response, t)
    draft = _normalise_draft(raw, question=state["question"])
    await _step(
        d, "escalate", t,
        level=3,
        reasoning=state["why"],
        route="ticket",
        category=draft["category"],
        product_area=draft["product_area"],
        priority=draft["priority"],
        usage=_totals([_usage_dict(response)]),
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
        "usage": [_usage_dict(response)],
    }


async def stage_ticket(
    draft: dict, *, db: AsyncSession, client_id: str, run_id: str, stage_seq: int
) -> dict:
    """File the ticket. Python calls the executor directly: one call site to keep
    idempotent (D4)."""
    executor = get_tool_executor(_TICKET_TOOL)
    return await executor(draft, client_id=client_id, db=db, run_id=run_id, stage_seq=stage_seq)


async def ticket(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Wait for the user, then file.

    Its own node, because `interrupt()` re-runs its node from the top on resume: anything
    placed before it in the same node would execute twice. The graph pauses here at the
    end of the turn and `confirm_ticket()` resumes it.
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
    """A failed filing loops back and pauses again, so the user can retry the same draft."""
    return "ticket" if "error" in (state.get("ticket") or {}) else END


def _build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    for node in (retrieve, grade, converse, rewrite, hybrid_retrieve, regrade, answer, escalate, ticket):
        g.add_node(node.__name__, node)
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
    """Compile the graph against a checkpointer. The app lifespan passes Postgres; tests
    pass an in-memory saver."""
    global _graph
    _graph = _builder.compile(checkpointer=saver)


def _compiled():
    if _graph is None:
        raise RuntimeError(
            "The support graph has no checkpointer: the app lifespan did not run "
            "postgres_checkpointer(), and interrupt/resume cannot work without one."
        )
    return _graph


@asynccontextmanager
async def postgres_checkpointer(database_url: str):
    """Open a psycopg3 pool beside the asyncpg engine and install the Postgres saver.

    A second driver, because langgraph-checkpoint-postgres is written against psycopg.
    `setup()` creates or migrates its own tables and is safe on every start.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    conninfo = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    async with AsyncConnectionPool(
        conninfo,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        use_checkpointer(saver)
        yield saver


def _thread(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


# ── driving it ───────────────────────────────────────────────────────────────────────


async def _drive(graph_input: Any, deps: Deps) -> AsyncIterator[tuple[str, dict]]:
    """Run the graph until it ends or pauses, forwarding what the nodes stream.

    `durability="sync"` writes each checkpoint before the next node starts, so a crash
    loses at most the node that was running.
    """
    async for event, data in _compiled().astream(
        graph_input,
        _thread(deps.recorder.run_id),
        context=deps,
        stream_mode="custom",
        durability="sync",
    ):
        yield event, data
        if event == "step":
            _maybe_crash(data["stage"])


async def _finish(deps: Deps, started: float) -> AsyncIterator[tuple[str, dict]]:
    """Persist the turn from the checkpointed state and emit `done`."""
    db, run_id = deps.db, deps.recorder.run_id
    values = (await _compiled().aget_state(_thread(run_id))).values
    conversation_id = values["conversation_id"]
    usage = _totals(values.get("usage", []))
    db.add(Message(conversation_id=conversation_id, role="user", content=values["question"]))
    db.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=values.get("answer", ""),
            citations={"segments": values.get("segments", [])},
            # The join back to this turn's step trail, for reloading a conversation.
            run_id=run_id,
        )
    )
    await _update_conversation_totals(db, conversation_id, usage)
    await db.commit()
    await deps.recorder.finish("completed")
    yield (
        "done",
        {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "outcome": values.get("outcome", "answer"),
            "confidence": round(float((values.get("grade") or {}).get("confidence", 0.0)), 4),
            "ticket_id": None,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "cost_usd": round(usage.cost_usd, 6),
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )


async def _guarded(events: AsyncIterator, *, client_id: str, db: AsyncSession, recorders: list):
    """Turn failures into an `error` event. The HTTP status went out long ago, and a stream
    that simply stops looks like a finished turn from the browser's side."""
    try:
        async for event in events:
            yield event
    except GraphCrash:
        raise
    except anthropic.APIError as exc:
        logger.exception("Anthropic API error during graph turn (client=%s)", client_id)
        await db.rollback()
        if recorders:
            await recorders[-1].finish("failed")
        yield ("error", {"message": f"Upstream API error: {exc.__class__.__name__}"})
    except Exception:
        logger.exception("Graph turn failed (client=%s)", client_id)
        await db.rollback()
        if recorders:
            await recorders[-1].finish("failed")
        yield ("error", {"message": "An internal error occurred. Please try again."})


async def stream_graph(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one turn, yielding SSE `(event, data)` tuples: `run`, a `step` per node, `text` /
    `citation` deltas, `ticket_proposal` when a human is needed, then one `done`."""
    recorders: list[RunRecorder] = []

    async def turn():
        started = time.monotonic()
        conv_id, history = await _prepare_conversation(db, client_id, conversation_id)
        recorder = await RunRecorder.start(conv_id, client_id)
        recorders.append(recorder)
        yield ("run", {"run_id": recorder.run_id, "conversation_id": conv_id})
        deps = Deps(cfg, client_id, db, anthropic.AsyncAnthropic(), recorder)
        initial = {
            "question": user_message,
            "history": history,
            "conversation_id": conv_id,
            "run_id": recorder.run_id,
            "usage": [],
        }
        async for event in _drive(initial, deps):
            yield event
        async for event in _finish(deps, started):
            yield event

    async for event in _guarded(turn(), client_id=client_id, db=db, recorders=recorders):
        yield event


async def _load_run(db: AsyncSession, run_id: str, client_id: str) -> Run:
    run = await db.get(Run, run_id)
    if run is None or run.client_id != client_id:
        raise RunUnavailable(f"Run {run_id!r} not found")
    return run


async def resumable_run(db: AsyncSession, run_id: str, client_id: str) -> Run:
    """The pre-flight for resume, run before any stream starts so a refusal is a plain 404.
    Resumable means the checkpoint has a next node and is not waiting on the user."""
    run = await _load_run(db, run_id, client_id)
    snapshot = await _compiled().aget_state(_thread(run_id))
    if not snapshot.next or snapshot.interrupts:
        raise RunUnavailable(f"Run {run_id!r} has nothing to resume")
    return run


async def stream_resume(
    run: Run, *, cfg: ClientConfig, client_id: str, db: AsyncSession
) -> AsyncIterator[tuple[str, dict]]:
    """Continue a crashed run from its last checkpoint (D3). Completed nodes do not run
    again; the node that was running when the process died does."""
    recorders: list[RunRecorder] = []

    async def resumed():
        started = time.monotonic()
        recorder = RunRecorder.from_run(run)
        recorders.append(recorder)
        yield ("run", {"run_id": run.id, "conversation_id": run.conversation_id})
        deps = Deps(cfg, client_id, db, anthropic.AsyncAnthropic(), recorder)
        async for event in _drive(None, deps):
            yield event
        async for event in _finish(deps, started):
            yield event

    async for event in _guarded(resumed(), client_id=client_id, db=db, recorders=recorders):
        yield event


async def confirm_ticket(
    *, run_id: str, client_id: str, cfg: ClientConfig, db: AsyncSession
) -> dict:
    """File the ticket this run proposed, once the user has said yes (D9).

    The draft comes from the checkpoint, not the request. Both D4 guards hold: a filed
    `ticket_id` in state short-circuits a second confirmation, and the `{run_id}:{stage_seq}`
    idempotency key covers a retry that races it.
    """
    run = await _load_run(db, run_id, client_id)
    snapshot = await _compiled().aget_state(_thread(run_id))
    filed = snapshot.values.get("ticket") or {}
    if filed.get("ticket_id"):
        return {"ticket_id": filed["ticket_id"], "reply": None, "already_filed": True}
    if "ticket" not in snapshot.next or not snapshot.interrupts:
        raise RunUnavailable(f"Run {run_id!r} did not propose a ticket")

    recorder = RunRecorder.from_run(run)
    deps = Deps(cfg, client_id, db, None, recorder)
    async for _ in _drive(Command(resume=True), deps):
        pass
    result = (await _compiled().aget_state(_thread(run_id))).values.get("ticket") or {}
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
        "step": recorder.steps[-1] if recorder.steps else None,
        "already_filed": False,
    }


async def run_graph(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> TurnResult:
    """Non-streaming entry point: drain the stream, so the two paths cannot drift."""
    result = TurnResult(conversation_id="", run_id="")
    async for event, data in stream_graph(
        user_message, cfg=cfg, client_id=client_id, conversation_id=conversation_id, db=db
    ):
        if event == "text":
            result.answer += data["delta"]
        elif event == "done":
            result.conversation_id = data["conversation_id"]
            result.run_id = data["run_id"]
            result.outcome = data["outcome"]
            result.confidence = data["confidence"]
            values = (await _compiled().aget_state(_thread(result.run_id))).values
            result.citations = values.get("citations", [])
            result.segments = values.get("segments", [])
    return result
