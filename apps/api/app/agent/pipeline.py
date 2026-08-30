"""The support pipeline: a fixed sequence of stages with one branch, decided in Python.

Contrast with `loop.py`, which hands the model a set of tools and lets it decide what to do.
That is the right shape for exploratory work. It is the wrong shape here, because the whole
claim of this workflow is that escalation is *not* the model's decision (D2):

    retrieve  ->  score  ->  branch  ->  answer   (cited, no tools offered)
                              |
                              +------->  escalate -> ticket   (forced)

Three properties fall out of the structure rather than out of prompting:

1. Retrieval always happens. It is a function call, not a tool the model may skip, so there
   is always something to score.
2. The answering model is never sent the ticket tool. It cannot escalate, and it cannot
   decline to answer by escalating instead.
3. Every stage commits its own audit entry through `checkpoint_session()` before the next
   stage starts, so a crash leaves the completed stages durable (D3).

Two API constraints shape the stage boundaries, both verified 2026-08-30:

- `search_result` blocks are valid as top-level user content, not only inside a
  `tool_result`. That is what lets retrieval be an ordinary function call while citations
  keep working.
- Citations and `output_config.format` cannot be combined (400). So `score` and
  `escalate` take structured output; `answer` takes citations; and the final `SupportAnswer`
  is assembled in Python rather than generated.
"""
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import (
    UsageTotals,
    _attr_or_key,
    _excerpt,
    _model_trace,
    _prepare_conversation,
    _trace_payload,
)
from app.config.schema import ClientConfig
from app.database import checkpoint_session
from app.models import Message, Run, Trace
from app.retrieval.search import search
from app.tools.registry import get_tool_executor

logger = logging.getLogger("configent.pipeline")

_REPO_ROOT = Path(__file__).parents[4]
_TICKET_TOOL = "create_escalation_ticket"

# Stage names, in order. Also the vocabulary of the SSE `step` events and CRASH_AFTER.
STAGES = ("retrieve", "score", "answer", "escalate", "ticket")


class PipelineCrash(SystemExit):
    """Raised by the CRASH_AFTER fault injector (D6). SystemExit so it is not caught by
    the pipeline's own `except Exception` handlers — a swallowed crash proves nothing."""


@dataclass
class PipelineResult:
    """What the router needs to build a response. `SupportAnswer` in schema form arrives
    in W2-1; this is the same data before it has a Pydantic wrapper."""

    conversation_id: str
    run_id: str
    answer: str = ""
    segments: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    escalated: bool = False
    ticket_id: str | None = None
    usage: UsageTotals = field(default_factory=UsageTotals)


# ── prompts ──────────────────────────────────────────────────────────────────────────


def _prompt(cfg: ClientConfig, name: str) -> str:
    """Load a sibling stage prompt next to the configured answer prompt.

    `agent.system_prompt_file` points at answer.md; score.md and ticket_draft.md live
    beside it. Keeping them as separate files is the point — a single mega-prompt makes
    the scoring step unauditable, and scoring is the guardrail.
    """
    return (cfg.system_prompt_path(_REPO_ROOT).parent / f"{name}.md").read_text()


# ── audit trail ──────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunRecorder:
    """Owns the `Run` row and appends one step per stage, each on its own transaction.

    Deliberately not using the request session: that one commits at the end of the turn
    and rolls back on failure, so anything written through it disappears in exactly the
    crash this record exists to survive (D3).
    """

    def __init__(self, run_id: str, conversation_id: str, client_id: str):
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.client_id = client_id
        self.steps: list[dict] = []
        self.state: dict[str, Any] = {}

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

    async def _persist(self, *, status: str, current_stage: str | None) -> None:
        async with checkpoint_session() as db:
            run = await db.get(Run, self.run_id)
            if run is None:  # pragma: no cover — the row is created before any step
                return
            run.steps = list(self.steps)
            run.state = dict(self.state)
            run.status = status
            run.current_stage = current_stage

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
        """Record one finished stage and commit it. Returns the SSE payload."""
        entry = {
            "seq": len(self.steps) + 1,
            "stage": stage,
            "status": status,
            "reasoning": reasoning,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "ts": _now(),
            **{k: v for k, v in extra.items() if v is not None},
        }
        if usage is not None:
            entry["tokens_in"] = usage.input_tokens
            entry["tokens_out"] = usage.output_tokens
            entry["cost_usd"] = round(usage.cost_usd, 6)
        self.steps.append(entry)
        await self._persist(status="running", current_stage=stage)
        return entry

    async def finish(self, status: str) -> None:
        await self._persist(status=status, current_stage=None)


def _maybe_crash(stage: str) -> None:
    """Fault injection for the week-2 resume demo (D6).

    A named injection point rather than `kill -9`: the process still dies with uncommitted
    work and an open SSE connection, so the failure mode is identical — only the timing is
    chosen, which makes it assertable in a test.
    """
    if os.getenv("CRASH_AFTER") == stage:
        logger.warning("CRASH_AFTER=%s — exiting deliberately", stage)
        raise PipelineCrash(f"CRASH_AFTER={stage}")


# ── stages ───────────────────────────────────────────────────────────────────────────


def _retrieval_query(user_message: str, history: list[dict]) -> str:
    """Build the embedding query.

    Deterministic retrieval means a pronoun-free follow-up ("and what about GKE?") embeds to
    nothing useful. Query rewriting is out of scope, so the cheap fix is to prepend the
    previous user turn: one line, no extra model call. Imperfect, but the alternative is a
    demo where the second question fails.
    """
    previous = [m for m in history if m.get("role") == "user"]
    if not previous:
        return user_message
    prior = previous[-1].get("content")
    if not isinstance(prior, str):
        return user_message
    return f"{prior}\n{user_message}"


async def stage_retrieve(
    db: AsyncSession, *, cfg: ClientConfig, client_id: str, query: str
) -> tuple[list, float]:
    """pgvector search. No model call — this is the deterministic half of the guardrail."""
    hits = await search(
        db,
        client_id=client_id,
        query=query,
        k=5,
        floor=cfg.agent.retrieval_drop_floor,
    )
    confidence = hits[0].similarity if hits else 0.0
    return hits, confidence


def _search_result_blocks(hits: list) -> list[dict]:
    """Hits as `search_result` content blocks, for direct placement in a user message.

    Citations are enabled unconditionally: the API requires them on all search results in a
    request or none, and an uncited answer is not what this assistant is for.
    """
    return [
        {
            "type": "search_result",
            "source": h.source_uri,
            "title": h.document_title,
            "content": [{"type": "text", "text": h.text}],
            "citations": {"enabled": True},
        }
        for h in hits
    ]


_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "confidence": {"type": "number"},
        "missing_info": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["supported", "confidence", "reasoning"],
    "additionalProperties": False,
}

_TICKET_SCHEMA = {
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
    "required": ["subject", "category", "product_area", "priority"],
    "additionalProperties": False,
}


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


async def stage_score(
    aclient: anthropic.AsyncAnthropic, *, cfg: ClientConfig, question: str, hits: list
) -> tuple[dict, Any]:
    """Cheap-model groundedness judgement. The second half of the guardrail (D2)."""
    passages = "\n\n".join(
        f"[{i + 1}] {h.document_title} ({h.source_uri})\n{h.text}" for i, h in enumerate(hits)
    )
    user = f"Question:\n{question}\n\nRetrieved passages:\n{passages}"
    return await _structured_call(
        aclient,
        model=cfg.agent.model,
        system=_prompt(cfg, "score"),
        user_content=user,
        schema=_SCORE_SCHEMA,
        max_tokens=512,
    )


def should_escalate(
    *, retrieval_confidence: float, score: dict | None, cfg: ClientConfig
) -> tuple[bool, str]:
    """The guardrail. Plain Python — no model is consulted, and none can override it.

    Returns (escalate, why). `score is None` means retrieval came back empty, which
    short-circuits before the scoring call: there is nothing to score, and asking a model to
    rate zero passages invents a number.
    """
    if score is None:
        return True, "retrieval returned no passages above the drop floor"
    if retrieval_confidence < cfg.agent.escalate_below:
        return True, (
            f"top similarity {retrieval_confidence:.2f} < escalate_below "
            f"{cfg.agent.escalate_below}"
        )
    if float(score.get("confidence", 0.0)) < cfg.agent.confidence_threshold:
        return True, (
            f"groundedness {float(score.get('confidence', 0.0)):.2f} < confidence_threshold "
            f"{cfg.agent.confidence_threshold}"
        )
    return False, (
        f"similarity {retrieval_confidence:.2f} and groundedness "
        f"{float(score.get('confidence', 0.0)):.2f} both above threshold"
    )


def answer_request_kwargs(
    cfg: ClientConfig, *, hits: list, question: str, history: list[dict]
) -> dict:
    """Assemble the answering call.

    Note what is absent: `tools`. The answering model is given no tool definitions at all,
    so it cannot file a ticket (D2) — that is asserted in the tests, not left to inspection.
    """
    content = _search_result_blocks(hits) + [{"type": "text", "text": question}]
    return {
        "model": cfg.agent.model,
        "max_tokens": cfg.agent.max_tokens,
        "system": [
            {
                "type": "text",
                "text": _prompt(cfg, "answer"),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": history + [{"role": "user", "content": content}],
    }


async def stage_escalate(
    aclient: anthropic.AsyncAnthropic, *, cfg: ClientConfig, question: str, why: str
) -> tuple[dict, Any]:
    """Draft the ticket fields. Structured output; the model never places the call."""
    user = (
        f"The assistant could not answer this question from its documentation.\n"
        f"Reason: {why}\n\nUser's question:\n{question}"
    )
    return await _structured_call(
        aclient,
        model=cfg.agent.model,
        system=_prompt(cfg, "ticket_draft"),
        user_content=user,
        schema=_TICKET_SCHEMA,
        max_tokens=768,
    )


async def stage_ticket(
    draft: dict, *, db: AsyncSession, client_id: str, run_id: str, stage_seq: int
) -> dict:
    """File the ticket. Python calls the executor directly — there is no tool-use round trip,
    so there is exactly one call site to make idempotent (D4)."""
    executor = get_tool_executor(_TICKET_TOOL)
    return await executor(
        draft, client_id=client_id, db=db, run_id=run_id, stage_seq=stage_seq
    )


# ── orchestration ────────────────────────────────────────────────────────────────────


def _collect_segments(response: Any) -> tuple[str, list[dict], list[dict]]:
    """Map the answer response's text blocks into (text, citations, segments).

    Same shape the loop produces, so the frontend renderer and stored citation format are
    unchanged — the pipeline is a different engine, not a different contract.
    """
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


async def stream_pipeline(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one turn through the pipeline, yielding SSE `(event, data)` tuples.

    Event order: one `step` per completed stage, interleaved with `text`/`citation` deltas
    while the answer streams, then exactly one `done`. The `step` events are the audit
    trail and the thing the user watches — the same surface, which is why SSE was worth
    reusing rather than adding a polling endpoint.

    On failure the stream emits `error` instead of `done`. The HTTP status was sent long
    ago, so the SSE channel is the only way to tell the client anything went wrong — a
    generator that simply stops looks identical to a completed turn from the browser's
    side, which is the worst possible failure mode for a workflow whose whole claim is
    that it is auditable.

    `PipelineCrash` is deliberately not caught: the CRASH_AFTER injector exists to kill
    the process, and a swallowed crash proves nothing about resume.
    """
    recorders: list[RunRecorder] = []
    try:
        async for event in _stream_pipeline_inner(
            user_message,
            cfg=cfg,
            client_id=client_id,
            conversation_id=conversation_id,
            db=db,
            on_recorder=lambda r: recorders.append(r),
        ):
            yield event
    except PipelineCrash:
        raise
    except anthropic.APIError as exc:
        logger.exception("Anthropic API error during pipeline turn (client=%s)", client_id)
        await db.rollback()
        if recorders:
            await recorders[-1].finish("failed")
        yield ("error", {"message": f"Upstream API error: {exc.__class__.__name__}"})
    except Exception:
        # Detail stays in the logs; the client only ever sees a generic message.
        logger.exception("Pipeline turn failed (client=%s)", client_id)
        await db.rollback()
        if recorders:
            await recorders[-1].finish("failed")
        yield ("error", {"message": "An internal error occurred. Please try again."})


async def _stream_pipeline_inner(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
    on_recorder,
) -> AsyncIterator[tuple[str, dict]]:
    """The stage sequence itself. Wrapped by `stream_pipeline`, which owns error handling."""
    started = time.monotonic()
    conversation_id, history = await _prepare_conversation(db, client_id, conversation_id)
    db.add(Message(conversation_id=conversation_id, role="user", content=user_message))
    await db.flush()

    recorder = await RunRecorder.start(conversation_id, client_id)
    # Handed to the wrapper so a failure can mark the run failed rather than leaving it
    # stuck in "running" forever.
    on_recorder(recorder)
    result = PipelineResult(conversation_id=conversation_id, run_id=recorder.run_id)
    aclient = anthropic.AsyncAnthropic()
    yield ("run", {"run_id": recorder.run_id, "conversation_id": conversation_id})

    # ── 1. retrieve ────────────────────────────────────────────────────────────
    t = time.monotonic()
    query = _retrieval_query(user_message, history)
    hits, retrieval_confidence = await stage_retrieve(
        db, cfg=cfg, client_id=client_id, query=query
    )
    yield (
        "step",
        await recorder.step(
            "retrieve",
            started=t,
            reasoning=(
                f"{len(hits)} passage(s) above the drop floor "
                f"({cfg.agent.retrieval_drop_floor}); best similarity "
                f"{retrieval_confidence:.2f}"
            ),
            n_hits=len(hits),
            top_similarity=round(retrieval_confidence, 4),
            sources=[h.source_uri for h in hits],
        ),
    )
    _maybe_crash("retrieve")

    # ── 2. score ───────────────────────────────────────────────────────────────
    # Empty retrieval short-circuits: nothing to score, and scoring nothing invents a number.
    score: dict | None = None
    if hits:
        t = time.monotonic()
        score, score_response = await _run_scored(aclient, cfg, user_message, hits, result)
        yield (
            "step",
            await recorder.step(
                "score",
                started=t,
                reasoning=score.get("reasoning"),
                confidence=round(float(score.get("confidence", 0.0)), 4),
                supported=score.get("supported"),
                missing_info=score.get("missing_info"),
                usage=_usage_of(score_response),
            ),
        )
        _maybe_crash("score")

    # ── 3. branch ──────────────────────────────────────────────────────────────
    escalate, why = should_escalate(
        retrieval_confidence=retrieval_confidence, score=score, cfg=cfg
    )
    result.confidence = float(score.get("confidence", 0.0)) if score else 0.0
    result.escalated = escalate

    if not escalate:
        # ── 4a. answer ─────────────────────────────────────────────────────────
        t = time.monotonic()
        citation_index = 0
        kwargs = answer_request_kwargs(cfg, hits=hits, question=user_message, history=history)
        async with aclient.messages.stream(**kwargs) as stream:
            async for event in stream:
                etype = getattr(event, "type", "")
                if etype != "content_block_delta":
                    continue
                dtype = getattr(event.delta, "type", "")
                if dtype == "text_delta":
                    yield ("text", {"delta": event.delta.text})
                elif dtype == "citations_delta":
                    citation_index += 1
                    cit = event.delta.citation
                    yield (
                        "citation",
                        {
                            "index": citation_index,
                            "source": _attr_or_key(cit, "source"),
                            "title": _attr_or_key(cit, "title"),
                            "cited_text": _excerpt(_attr_or_key(cit, "cited_text") or ""),
                        },
                    )
            response = await stream.get_final_message()
        usage = _usage_of(response)
        result.usage.add(getattr(response, "usage", None))
        result.answer, result.citations, result.segments = _collect_segments(response)
        _record_trace(db, conversation_id, response, t)
        yield (
            "step",
            await recorder.step(
                "answer",
                started=t,
                reasoning=why,
                n_citations=len(result.citations),
                usage=usage,
            ),
        )
        _maybe_crash("answer")
    else:
        # ── 4b. escalate ───────────────────────────────────────────────────────
        t = time.monotonic()
        draft, draft_response = await stage_escalate(
            aclient, cfg=cfg, question=user_message, why=why
        )
        result.usage.add(getattr(draft_response, "usage", None))
        _record_trace(db, conversation_id, draft_response, t)
        yield (
            "step",
            await recorder.step(
                "escalate",
                started=t,
                reasoning=why,
                category=draft.get("category"),
                product_area=draft.get("product_area"),
                priority=draft.get("priority"),
                usage=_usage_of(draft_response),
            ),
        )
        _maybe_crash("escalate")

        # ── 5. ticket ──────────────────────────────────────────────────────────
        t = time.monotonic()
        stage_seq = len(recorder.steps) + 1
        ticket = await stage_ticket(
            draft,
            db=db,
            client_id=client_id,
            run_id=recorder.run_id,
            stage_seq=stage_seq,
        )
        ok = "error" not in ticket
        if ok:
            result.ticket_id = ticket.get("ticket_id")
            recorder.state["ticket_id"] = result.ticket_id
        db.add(
            Trace(
                conversation_id=conversation_id,
                span_type="tool",
                tool_name=_TICKET_TOOL,
                input_=_trace_payload(draft),
                output=_trace_payload(ticket),
                latency_ms=int((time.monotonic() - t) * 1000),
            )
        )
        yield (
            "step",
            await recorder.step(
                "ticket",
                status="ok" if ok else "failed",
                started=t,
                reasoning=(
                    f"filed as {result.ticket_id}" if ok else str(ticket.get("error"))
                ),
                ticket_id=result.ticket_id,
                url=ticket.get("url"),
                eta_hours=ticket.get("eta_hours"),
                queue=ticket.get("queue"),
            ),
        )
        _maybe_crash("ticket")
        result.answer = _escalation_reply(ticket, ok)
        result.segments = [{"text": result.answer, "citations": []}]
        # Emitted as a text event so a streaming client renders an escalation the same way
        # it renders an answer. Without this the UI shows the step trail above an empty
        # message bubble, which reads as a crash rather than a decision.
        yield ("text", {"delta": result.answer})

    # ── persist + done ─────────────────────────────────────────────────────────
    db.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=result.answer,
            citations={"segments": result.segments},
        )
    )
    await _accrue_totals(db, conversation_id, result.usage)
    await db.commit()
    await recorder.finish("completed")

    yield (
        "done",
        {
            "conversation_id": conversation_id,
            "run_id": recorder.run_id,
            "escalated": result.escalated,
            "confidence": round(result.confidence, 4),
            "ticket_id": result.ticket_id,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_creation_input_tokens": result.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": result.usage.cache_read_input_tokens,
            "cost_usd": round(result.usage.cost_usd, 6),
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )


async def _run_scored(aclient, cfg, user_message, hits, result) -> tuple[dict, Any]:
    score, response = await stage_score(aclient, cfg=cfg, question=user_message, hits=hits)
    result.usage.add(getattr(response, "usage", None))
    return score, response


def _usage_of(response: Any) -> UsageTotals:
    totals = UsageTotals()
    totals.add(getattr(response, "usage", None))
    return totals


def _record_trace(db: AsyncSession, conversation_id: str, response: Any, started: float) -> None:
    db.add(
        _model_trace(
            conversation_id,
            getattr(response, "usage", None),
            int((time.monotonic() - started) * 1000),
        )
    )


def _escalation_reply(ticket: dict, ok: bool) -> str:
    """What the user sees when the agent escalates.

    An escalation is not a refusal. The user asked a reasonable question; the honest answer
    is that it needs someone who can see their project, and that this has been arranged.
    """
    if not ok:
        return (
            "I can't answer this from the Google Cloud documentation I have — it needs "
            "someone with access to your project. I also couldn't reach the ticket system "
            "just now, so please retry shortly or raise it with the platform team directly."
        )
    eta = ticket.get("eta_hours")
    return (
        f"That one needs a human: it depends on your own project configuration, and my "
        f"knowledge base is public Google Cloud documentation only.\n\n"
        f"I've opened **{ticket.get('ticket_id')}** with the "
        f"{ticket.get('queue', 'platform')} team"
        + (f", who aim to respond within {eta} hours" if eta else "")
        + f". You can follow it at {ticket.get('url')}."
    )


async def _accrue_totals(db: AsyncSession, conversation_id: str, usage: UsageTotals) -> None:
    from app.models import Conversation

    conv = await db.get(Conversation, conversation_id)
    if conv is None:  # pragma: no cover
        return
    conv.total_cost += usage.cost_usd
    conv.total_tokens += usage.input_tokens + usage.output_tokens


async def run_pipeline(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> PipelineResult:
    """Non-streaming entry point: drain the stream and keep the final state.

    Sharing one implementation means the streamed and non-streamed paths cannot drift —
    the bug where the demo works and the JSON endpoint quietly doesn't.
    """
    result = PipelineResult(conversation_id="", run_id="")
    async for event, data in stream_pipeline(
        user_message, cfg=cfg, client_id=client_id, conversation_id=conversation_id, db=db
    ):
        if event == "text":
            result.answer += data["delta"]
        elif event == "done":
            result.conversation_id = data["conversation_id"]
            result.run_id = data["run_id"]
            result.escalated = data["escalated"]
            result.confidence = data["confidence"]
            result.ticket_id = data.get("ticket_id")
    return result
