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
import time
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent import platform
from app.agent.common import attr_or_key, collect_segments, excerpt
from app.agent.escalation import _after_ticket, converse, escalate, ticket
from app.agent.platform import Deps, Engine, _model_step, _prompt, _step, _transcript
from app.config.schema import ClientConfig
from app.retrieval import search as retrieval
from app.retrieval.search import Hit


class TurnState(platform.TurnState, total=False):
    """The shared state plus what only this engine keeps. Hits are dicts, not `Hit`."""

    hits: list[dict]
    top_similarity: float
    grade: dict
    queries: list[str]
    keywords: str
    route: str  # chosen by decide_level1 / decide_level2; the edges only read it
    citations: list[dict]


_GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        # Triage rides on the grade call (D9): no extra call, and made with the passages in
        # view rather than by a router that sees only the question.
        "kind": {"type": "string", "enum": ["question", "conversation", "handoff"]},
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
    # Asked for a human: skip the search for an answer they didn't want. Still only a
    # proposal — nothing files until they confirm, so a misread costs one offer.
    if score.get("kind") == "handoff":
        return "escalate", "the user asked for the platform team"
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
        "url": hit.url,
        "similarity": round(hit.similarity, 4),
    }


async def retrieve(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Level 1: pgvector top-k. No model call — the deterministic half of the guardrail."""
    d, t = runtime.context, time.monotonic()
    hits = await retrieval.retrieve(
        d.db,
        d.client_id,
        [state["question"]],
        cfg=d.cfg.retrieval,
        model=d.cfg.corpus.embedding.model,
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
    score, response = await platform._structured_call(
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
    return {"grade": score, "route": route, "why": why, "reply": score.get("reply")}



async def rewrite(state: TurnState, runtime: Runtime[Deps]) -> dict:
    """Level 2: reformulate with the conversation in view — semantic variants for dense
    search, exact identifiers for keyword search."""
    d, t = runtime.context, time.monotonic()
    n = d.cfg.agent.corrective.query_rewrites
    out, response = await platform._structured_call(
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
    hits = await retrieval.retrieve(
        d.db,
        d.client_id,
        [state["question"], *state.get("queries", [])],
        state.get("keywords", ""),
        cfg=d.cfg.retrieval,
        model=d.cfg.corpus.embedding.model,
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
            # The API echoes `source` back on the citation, so a URL here is a link in the UI.
            # .get: hits checkpointed before the url field existed have none.
            "source": h.get("url") or h["source_uri"],
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
                        "source": attr_or_key(cit, "source"),
                        "title": attr_or_key(cit, "title"),
                        "cited_text": excerpt(attr_or_key(cit, "cited_text") or ""),
                    },
                ))
        response = await stream.get_final_message()
    text, citations, segments = collect_segments(response)
    await _model_step(
        d, state, "answer", t, response,
        level=state["level"],
        reasoning=state["why"],
        n_citations=len(citations),
    )
    return {"outcome": "answer", "answer": text, "citations": citations, "segments": segments}


# ── the graph ────────────────────────────────────────────────────────────────────────


def _route(state: TurnState) -> str:
    return state["route"]


def build() -> StateGraph:
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


first_stage = "retrieve"


def summary(values: dict) -> dict:
    """What this engine adds to the `done` payload."""
    return {"confidence": round(float(values["grade"].get("confidence", 0.0)), 4)}


ENGINE = Engine("support_graph", build(), first_stage, summary)
