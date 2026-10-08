"""The shared platform: what runs a turn, whichever engine finds the evidence.

The audit trail (`RunRecorder`), the per-request `Deps`, the structured-call helper, the
checkpointer, and the three entry points. An engine is passed in as an `Engine`; this module
imports none.
"""
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import anthropic
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.common import (
    UsageTotals,
    attr_or_key,
    model_trace,
    prepare_conversation,
    update_conversation_totals,
)
from app.config.schema import ClientConfig
from app.database import checkpoint_session
from app.models import Message, Run

logger = logging.getLogger("configent.graph")

_REPO_ROOT = Path(__file__).parents[4]


class GraphCrash(SystemExit):
    """Raised by the CRASH_AFTER fault injector (D6). SystemExit so no `except Exception`
    swallows it."""


class RunUnavailable(Exception):
    """Unknown run, another client's run, or a run with no ticket offer to confirm. A 404
    that reveals nothing about which."""

class TurnState(TypedDict, total=False):
    """What every engine's state has, and all the shared nodes and the platform read. Plain
    JSON: it is what the checkpointer saves. An engine's own state extends it."""

    question: str
    history: list[dict]
    conversation_id: str
    run_id: str
    level: int  # optional: the tier the evidence came from, for an engine that has tiers
    why: str  # what sent the turn to converse or escalate
    reply: str  # optional: what converse says
    draft: dict
    ticket: dict
    outcome: str  # "answer" | "converse" | "ticket"
    answer: str
    segments: list[dict]


@dataclass(frozen=True)
class Engine:
    """What an engine hands the platform: its graph, where a turn starts, and its
    contribution to the `done` payload."""

    name: str
    build: Callable[[], StateGraph]
    first_stage: str
    summary: Callable[[dict], dict]


@dataclass
class Deps:
    """Per-request objects, passed as LangGraph `context`, which is never checkpointed."""

    cfg: ClientConfig
    client_id: str
    db: AsyncSession
    aclient: anthropic.AsyncAnthropic | None
    recorder: "RunRecorder"
    usage: UsageTotals = field(init=False)

    def __post_init__(self) -> None:
        self.usage = UsageTotals(self.cfg.agent.model)


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
    async def start(cls, conversation_id: str, client_id: str, engine: Engine) -> "RunRecorder":
        async with checkpoint_session() as db:
            run = Run(
                conversation_id=conversation_id,
                client_id=client_id,
                engine=engine.name,  # confirm_ticket resumes the graph the run was proposed on
                status="running",
                current_stage=engine.first_stage,
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
    d: Deps, state: dict, stage: str, started: float, response: Any, **extra: Any
) -> None:
    """`_step` for a node that made a model call: also accrues its cost and traces it."""
    model = d.cfg.agent.model
    usage = UsageTotals(model)
    usage.add(response.usage)
    d.usage.add(response.usage)
    latency_ms = int((time.monotonic() - started) * 1000)
    d.db.add(model_trace(state["conversation_id"], model, response.usage, latency_ms))
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
        attr_or_key(b, "text", "") for b in response.content if attr_or_key(b, "type") == "text"
    )
    return json.loads(text), response


def _transcript(history: list[dict], turns: int = 6) -> str:
    """The last few readable turns, for triage, rewriting and drafting."""
    lines = [
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-turns:]
        if isinstance(m.get("content"), str)
    ]
    return "\n".join(lines) or "(none)"




_graphs: dict = {}  # engine name -> graph compiled against the checkpointer


def use_checkpointer(saver, engines: Iterable[Engine]) -> None:
    """Compile every engine's graph against a checkpointer: Postgres in the app, in-memory
    in tests. Thread ids are run ids, so the graphs never share a checkpoint."""
    _graphs.clear()
    _graphs.update({e.name: e.build().compile(checkpointer=saver) for e in engines})


def _compiled(name: str):
    if not _graphs:
        raise RuntimeError(
            "No engine has a checkpointer: the app lifespan did not run "
            "postgres_checkpointer(), and the ticket pause cannot work without one."
        )
    return _graphs[name]


@asynccontextmanager
async def postgres_checkpointer(database_url: str, engines: Iterable[Engine]):
    """Install the Postgres saver for the app's lifetime. psycopg 3, beside asyncpg, because
    langgraph-checkpoint-postgres is written against it; `setup()` is idempotent."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conninfo = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    # ponytail: one shared connection with a lock. Swap to an AsyncConnectionPool if
    # concurrent turns contend on it, or if a dropped connection needs to heal itself.
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()
        use_checkpointer(saver, engines)
        yield


def _thread(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


# ── entry points ─────────────────────────────────────────────────────────────────────


async def stream_turn(
    user_message: str,
    *,
    engine: Engine,
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
        conversation_id, history = await prepare_conversation(db, client_id, conversation_id)
        recorder = await RunRecorder.start(conversation_id, client_id, engine)
        run_id = recorder.run_id
        yield ("run", {"run_id": run_id, "conversation_id": conversation_id})

        deps = Deps(cfg, client_id, db, anthropic.AsyncAnthropic(), recorder)
        initial = {
            "question": user_message,
            "history": history,
            "conversation_id": conversation_id,
            "run_id": run_id,
        }
        async for event, data in _compiled(engine.name).astream(
            initial, _thread(run_id), context=deps, stream_mode="custom", durability="sync"
        ):
            yield event, data
            if event == "step":
                _maybe_crash(data["stage"])

        values = (await _compiled(engine.name).aget_state(_thread(run_id))).values
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
        await update_conversation_totals(db, conversation_id, deps.usage)
        await db.commit()
        await recorder.finish("completed")
        yield (
            "done",
            {
                "conversation_id": conversation_id,
                "run_id": run_id,
                "outcome": values["outcome"],
                **engine.summary(values),
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


async def run_turn(
    user_message: str,
    *,
    engine: Engine,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> dict:
    """Non-streaming entry point: drain the stream, so the two paths cannot drift. Returns
    the final state."""
    run_id = None
    async for event, data in stream_turn(
        user_message, engine=engine, cfg=cfg, client_id=client_id, conversation_id=conversation_id, db=db
    ):
        if event == "run":
            run_id = data["run_id"]
        elif event == "error":
            raise RuntimeError(data["message"])
    return (await _compiled(engine.name).aget_state(_thread(run_id))).values


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
    # The run's engine, not the client's current one: a config edit between the offer and
    # the click must not resume a paused thread on a graph that never created it.
    if run.engine not in _graphs:
        raise RunUnavailable(f"Run {run_id!r} not found")
    graph, thread = _compiled(run.engine), _thread(run_id)
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

    # Imported here: escalation imports this module for the helpers its nodes share.
    from app.agent.escalation import _escalation_reply

    reply = _escalation_reply(result, ok, cfg.escalation)
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
