"""What the support graph shares with the rest of the API: loading a conversation, token
usage and its cost, and reading a model response.

This is what remained of `loop.py` when the free-form loop engine was retired (D11).
"""
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.pricing import price_for
from app.models import Conversation, Message, Trace


class ConversationNotFoundError(Exception):
    """Raised when a conversation_id doesn't exist or belongs to a different client.

    Routers translate this into a 404 — from the caller's point of view a
    cross-tenant conversation_id should look indistinguishable from an unknown one.
    """


def _priced(price, input_tokens, output_tokens, cache_write, cache_read) -> float:
    return (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_write * price.cache_write
        + cache_read * price.cache_read
    ) / 1_000_000


def usage_counts(usage: Any) -> tuple[int, int, int, int]:
    """(input, output, cache write, cache read) from an OpenAI-shaped usage object.

    `prompt_tokens` *includes* cached and cache-written tokens, so plain input is what is left
    after taking both out; counted whole, every cached call would be overstated (D15)."""
    details = getattr(usage, "prompt_tokens_details", None)
    read = (getattr(details, "cached_tokens", 0) or 0) if details else 0
    write = (getattr(details, "cache_write_tokens", 0) or 0) if details else 0
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    return max(prompt - read - write, 0), getattr(usage, "completion_tokens", 0) or 0, write, read


@dataclass
class UsageTotals:
    """Token usage summed across one turn's model calls, priced at `model`'s rates (D8).

    A call made on another model (`agent.structured_model`) adds its tokens to the totals
    and the price difference to `offset_usd`, so `cost_usd` stays exact."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    offset_usd: float = 0.0

    def add(self, usage: Any, model: str | None = None) -> None:
        counts = usage_counts(usage)
        self.input_tokens += counts[0]
        self.output_tokens += counts[1]
        self.cache_creation_input_tokens += counts[2]
        self.cache_read_input_tokens += counts[3]
        if model and model != self.model:
            self.offset_usd += _priced(price_for(model), *counts) - _priced(price_for(self.model), *counts)

    @property
    def cost_usd(self) -> float:
        return self.offset_usd + _priced(
            price_for(self.model),
            self.input_tokens,
            self.output_tokens,
            self.cache_creation_input_tokens,
            self.cache_read_input_tokens,
        )


_TRACE_FIELD_MAX_CHARS = 2000


def trace_payload(value: Any) -> Any:
    """JSON-safe, size-capped representation for a trace input/output column.

    Traces are for observability, not replay, so large payloads are capped rather than
    stored verbatim.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > _TRACE_FIELD_MAX_CHARS:
        text = text[:_TRACE_FIELD_MAX_CHARS] + "…(truncated)"
    return text


def model_trace(conversation_id: str, model: str, usage: Any, latency_ms: int) -> Trace:
    """Build a span_type="model" Trace row for one Anthropic API call."""
    totals = UsageTotals(model)
    totals.add(usage)
    return Trace(
        conversation_id=conversation_id,
        span_type="model",
        tokens_in=totals.input_tokens,
        tokens_out=totals.output_tokens,
        cache_read_tokens=totals.cache_read_input_tokens,
        cache_write_tokens=totals.cache_creation_input_tokens,
        cost_usd=totals.cost_usd,
        latency_ms=latency_ms,
    )


def excerpt(text: str, max_chars: int = 400) -> str:
    """Trim a full document chunk to a readable 2-3 sentence excerpt.

    A citation names a whole passage (D15), so its preview is the passage. This
    reduces it to something useful as a hover preview without losing the key fact.
    """
    if not text:
        return text
    # Strip leading markdown noise (headers, dividers) before excerpting
    cleaned = re.sub(r"^(#{1,6}\s.*|[-*]{3,})\n?", "", text, flags=re.MULTILINE).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    # Cut at the last sentence boundary within max_chars
    window = cleaned[:max_chars]
    last_stop = max(window.rfind(". "), window.rfind(".\n"), window.rfind("? "), window.rfind("! "))
    if last_stop > max_chars // 3:
        return window[: last_stop + 1]
    return window.rstrip() + "…"


def citation(passage: dict) -> dict:
    """The chip for passage [n]: what the UI shows and the step trail counts."""
    return {"source": passage["source"], "title": passage["title"], "cited_text": excerpt(passage["text"])}


class Markers:
    """Numbered citations in streamed text (D15). `feed` turns chunks into `("text", str)` and
    `("cite", n)` pieces. A possible marker at the end of a chunk is held back until it
    completes, so `[1` + `2]` still parses. A number with no passage (`arr[0]`, an invented
    `[9]`) stays as text and is counted in `bad`."""

    _MARKER = re.compile(r"\[(\d{1,2})\]")
    # Trailing spaces wait too: "1 vCPU [1]." should read "1 vCPU." once the marker is gone.
    _PARTIAL = re.compile(r"\s*(\[\d{0,2})?$")

    def __init__(self, n_passages: int):
        self.n, self.buf, self.bad = n_passages, "", 0

    def feed(self, chunk: str) -> list[tuple[str, Any]]:
        self.buf += chunk
        out: list[tuple[str, Any]] = []
        while m := self._MARKER.search(self.buf):
            n = int(m.group(1))
            if 1 <= n <= self.n:
                if before := self.buf[: m.start()].rstrip():
                    out.append(("text", before))
                out.append(("cite", n))
            else:
                self.bad += 1
                out.append(("text", self.buf[: m.end()]))
            self.buf = self.buf[m.end():]
        partial = self._PARTIAL.search(self.buf)
        cut = partial.start() if partial else len(self.buf)
        if cut:
            out.append(("text", self.buf[:cut]))
            self.buf = self.buf[cut:]
        return out

    def flush(self) -> list[tuple[str, Any]]:
        rest, self.buf = self.buf, ""
        return [("text", rest)] if rest else []


def segments_from(pieces: list[tuple[str, Any]], passages: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """(reply text, citations, segments) from parsed pieces: each run of text, then the
    citations that follow it. The same shape the UI and stored messages have always used."""
    text, citations, segments = "", [], []
    for kind, value in pieces:
        if kind == "text":
            text += value
            if not segments or segments[-1]["citations"]:
                segments.append({"text": "", "citations": []})
            segments[-1]["text"] += value
        else:
            c = citation(passages[value - 1])
            citations.append(c)
            if not segments:
                segments.append({"text": "", "citations": []})
            segments[-1]["citations"].append(c)
    return text, citations, segments




async def prepare_conversation(
    db: AsyncSession, client_id: str, conversation_id: str | None
) -> tuple[str, list[dict]]:
    """Create the conversation row (first turn) or load prior message history.

    Raises `ConversationNotFoundError` if `conversation_id` doesn't exist or
    belongs to a different client (A1) — history (including retrieved chunks)
    must never leak across the client_id boundary.

    A newly created conversation is **committed immediately**, not just flushed. The graph
    writes run state through an independent session (D3), and `runs.conversation_id` is a
    foreign key — an uncommitted parent is invisible to that session and the insert fails.
    The cost of committing early is that a turn which then fails leaves an empty
    conversation row behind; that is a row with no messages, not corrupted history.
    """
    if conversation_id is None:
        conv = Conversation(client_id=client_id)
        db.add(conv)
        await db.commit()
        return conv.id, []

    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.client_id != client_id:
        raise ConversationNotFoundError(
            f"Conversation {conversation_id!r} not found for client {client_id!r}"
        )

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    )
    history = [{"role": m.role, "content": m.content} for m in result.scalars().all()]
    return conversation_id, history


async def update_conversation_totals(
    db: AsyncSession, conversation_id: str, usage: UsageTotals
) -> None:
    """Accrue this turn's cost/tokens onto Conversation.total_cost/total_tokens."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        return
    conv.total_cost += usage.cost_usd
    conv.total_tokens += usage.input_tokens + usage.output_tokens
