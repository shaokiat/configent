"""The database template (D13): the model writes a SELECT, code guards and runs it, the rows
are the evidence.

    generate ─┬─ converse / handoff       (the same call classifies the message, as in D9)
              └─ guard → execute ─┬─ answer
                                  └─ repair → guard → execute ─┬─ answer
                                                               └─ handoff

The handoff is `decline` or `escalate → ticket`, per the client's `handoff.mode`.

Python decides every route (`decide_sql`, D2); the nodes store it and the edges only read it.
`guard` and `execute` are separate nodes so the trail tells a rejected query from a failed one.
`generate` takes structured output and `answer` writes cited prose, so they stay apart.
"""
import asyncio
import time
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import select

from app.agent import platform
from app.agent.common import excerpt
from app.agent.handoff import _after_ticket, converse, decline, escalate, route, ticket
from app.agent.platform import _REPO_ROOT, Deps, Template, _model_step, _prompt, _step, _transcript
from app.config.schema import ClientConfig, DatabaseAgent
from app.models import Document
from app.sql import context, guard
from app.sql.connection import QueryError, run_query
from app.sql.guard import Verdict

_PREVIEW_ROWS = 5  # in the step trail; the full rows go only to the answering call


class TurnState(platform.TurnState, total=False):
    kind: str
    sql: str
    reasoning: str
    verdict: dict  # {"ok": bool, "reason": str | None}
    error: str  # the latest guard or execution failure
    attempts: int  # repairs so far
    route: str  # chosen by decide_sql (or generate); the edges only read it
    columns: list[str]
    rows: list[list]
    truncated: bool
    row_count: int  # set only when a query ran: summary() reads it


_SQL_FIELDS = {
    # Reasoning first: fields are written in order, and a model that committed to `kind`
    # first was seen marking "2008 Monaco" a handoff, then noting 2008 is in range (D15).
    "reasoning": {"type": "string"},
    "sql": {"type": "string"},
}
_GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": _SQL_FIELDS["reasoning"],
        "kind": {"type": "string", "enum": ["question", "conversation", "handoff"]},
        "sql": _SQL_FIELDS["sql"],
        "reply": {"type": "string"},  # what converse says; "" otherwise
    },
    "required": ["kind", "sql", "reasoning", "reply"],
    "additionalProperties": False,
}
_REPAIR_SCHEMA = {
    "type": "object",
    "properties": _SQL_FIELDS,
    "required": ["sql", "reasoning"],
    "additionalProperties": False,
}


def decide_sql(
    *, verdict: Verdict | None, error: str | None, attempts: int, cfg: DatabaseAgent
) -> tuple[str, str]:
    """Route after the guard or the execution. Zero rows is an answer, not a failure: the
    query ran, and "nothing matches" is true evidence, not something for the data team."""
    failure = error or (verdict.reason if verdict is not None and not verdict.ok else None)
    if failure is None:
        return "answer", "the query ran"
    if attempts < cfg.repair_attempts:
        return "repair", failure
    return "escalate", f"the query failed after {attempts} repair attempt(s): {failure}"


async def _system(d: Deps) -> str:
    """The same text for `generate` and `repair`, so the cached prefix is reused (P5)."""
    uri = f"schema://{d.client_id}"
    text = (
        await d.db.execute(
            select(Document.full_text).where(Document.client_id == d.client_id, Document.source_uri == uri)
        )
    ).scalar()
    return f"{_prompt(d.cfg, 'generate')}\n\n## Database schema and notes\n\n{text}"


def _db_path(cfg: ClientConfig) -> Path:
    return _REPO_ROOT / cfg.agent.database.path


async def generate(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    out, response = await platform._structured_call(
        d.aclient,
        model=d.cfg.structured_model,
        system=await _system(d),
        user_content=(
            f"Recent conversation:\n{_transcript(state.get('history', []))}\n\n"
            f"Latest message:\n{state['question']}"
        ),
        schema=_GENERATE_SCHEMA,
        max_tokens=d.cfg.agent.max_tokens,
        cache_system=True,
    )
    kind, sql = out.get("kind"), (out.get("sql") or "").strip()
    route = {"conversation": "converse", "handoff": "escalate"}.get(kind, "guard")
    reasoning = out.get("reasoning") or ""
    await _model_step(d, state, "generate", t, response, model=d.cfg.structured_model, reasoning=reasoning, kind=kind, sql=sql or None)
    return {
        "kind": kind, "sql": sql, "reasoning": reasoning, "reply": out.get("reply"),
        "route": route, "why": reasoning or f"the model marked this a {kind}",
        "attempts": 0,
    }


async def guard_node(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    cfg = d.cfg.agent
    if state["sql"]:
        verdict = await asyncio.to_thread(
            guard.check, state["sql"], dialect=cfg.database.dialect, path=_db_path(d.cfg)
        )
    else:
        verdict = Verdict(False, "no query produced")  # a question with no SQL repairs or escalates
    if verdict.ok:
        route, why = "execute", "read-only SELECT"
    else:
        route, why = decide_sql(verdict=verdict, error=None, attempts=state["attempts"], cfg=cfg)
    await _step(d, "guard", t, reasoning=why, ok=verdict.ok, reason=verdict.reason)
    return {"verdict": {"ok": verdict.ok, "reason": verdict.reason}, "error": verdict.reason or "",
            "route": route, "why": why}


async def execute(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    cfg = d.cfg.agent
    try:
        result = await run_query(
            _db_path(d.cfg), state["sql"], row_limit=cfg.guard.row_limit, timeout_ms=cfg.guard.timeout_ms
        )
    except QueryError as e:  # includes QueryTimeout
        route, why = decide_sql(verdict=None, error=str(e), attempts=state["attempts"], cfg=cfg)
        await _step(d, "execute", t, status="failed", reasoning=str(e), error=str(e))
        return {"error": str(e), "route": route, "why": why}
    await _step(
        d, "execute", t,
        reasoning=f"{len(result.rows)} rows",
        row_count=len(result.rows), truncated=result.truncated, elapsed_ms=result.elapsed_ms,
        columns=result.columns, rows=result.rows[:_PREVIEW_ROWS],
    )
    return {
        "columns": result.columns, "rows": result.rows, "truncated": result.truncated,
        "row_count": len(result.rows), "error": "", "route": "answer", "why": "the query ran",
    }


async def repair(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    out, response = await platform._structured_call(
        d.aclient,
        model=d.cfg.structured_model,
        system=await _system(d),
        user_content=(
            f"Latest message:\n{state['question']}\n\n"
            f"Your query failed.\nQuery:\n{state['sql']}\nError: {state['error']}\n\n"
            "Write a corrected query."
        ),
        schema=_REPAIR_SCHEMA,
        max_tokens=d.cfg.agent.max_tokens,
        cache_system=True,
    )
    sql, attempt = (out.get("sql") or "").strip(), state["attempts"] + 1
    await _model_step(
        d, state, "repair", t, response, model=d.cfg.structured_model,
        reasoning=out.get("reasoning"), error=state["error"], sql=sql or None, attempt=attempt,
    )
    return {"sql": sql, "attempts": attempt, "route": "guard"}


def _rows_text(columns: list[str], rows: list[list], truncated: bool, limit: int) -> str:
    """A compact table, header first. Truncation is flagged so the answer can say it is partial."""
    lines = [" | ".join(columns)] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    lines.append(f"({len(rows)} rows" + (f", truncated at the {limit}-row limit)" if truncated else ")"))
    return "\n".join(lines)


def answer_request_kwargs(
    cfg: ClientConfig, *, client_id: str, sql: str, reasoning: str,
    columns: list[str], rows: list[list], truncated: bool, question: str, history: list[dict],
) -> tuple[dict, list[dict]]:
    """Assemble the answering call and its passages: the rows are passage [1] (D15), and
    `tools` is absent (D2)."""
    passages = [{
        "source": f"sql://{client_id}",
        "title": excerpt(reasoning or sql, 120),
        "text": _rows_text(columns, rows, truncated, cfg.agent.guard.row_limit),
    }]
    kwargs = {
        "model": cfg.agent.model,
        "max_tokens": cfg.agent.max_tokens,
        "messages": [platform._system(_prompt(cfg, "answer"), cache=True), *history,
                     {"role": "user", "content": f"{platform.numbered(passages)}\n\nQuestion: {question}"}],
    }
    return kwargs, passages


async def answer(state: TurnState, runtime: Runtime[Deps]) -> dict:
    d, t = runtime.context, time.monotonic()
    kwargs, passages = answer_request_kwargs(
        d.cfg, client_id=d.client_id, sql=state["sql"], reasoning=state.get("reasoning", ""),
        columns=state["columns"], rows=state["rows"], truncated=state["truncated"],
        question=state["question"], history=state.get("history", []),
    )
    a = await platform._stream_answer(d, kwargs, passages)
    await _model_step(
        d, state, "answer", t, a, reasoning=state["why"],
        n_citations=len(a.citations), bad_citations=a.bad_citations or None,
    )
    return {"outcome": "answer", "answer": a.text, "citations": a.citations, "segments": a.segments}


def build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    for name, node in (
        ("generate", generate), ("guard", guard_node), ("execute", execute), ("repair", repair),
        ("answer", answer), ("converse", converse), ("escalate", escalate), ("ticket", ticket),
        ("decline", decline),
    ):
        g.add_node(name, node)
    g.add_edge(START, "generate")
    g.add_conditional_edges("generate", route, ["guard", "converse", "escalate", "decline"])
    g.add_conditional_edges("guard", route, ["execute", "repair", "escalate", "decline"])
    g.add_conditional_edges("execute", route, ["answer", "repair", "escalate", "decline"])
    g.add_edge("repair", "guard")
    g.add_edge("answer", END)
    g.add_edge("converse", END)
    g.add_edge("decline", END)
    g.add_edge("escalate", "ticket")
    g.add_conditional_edges("ticket", _after_ticket, ["ticket", END])
    return g


def summary(values: dict) -> dict:
    """No `confidence`: this template grades nothing."""
    return {"row_count": values["row_count"]} if "row_count" in values else {}


async def _ready(db, cfg: ClientConfig) -> str | None:
    path = _db_path(cfg)
    if not path.exists():  # data state, not a config error: CI and fresh clones lack it
        return f"The database was not found at {cfg.agent.database.path}; run `make data-bird`."
    return await context.ready(db, cfg, _REPO_ROOT)


TEMPLATE = Template("database", build, "generate", summary, context.check, context.ingest, _ready)
