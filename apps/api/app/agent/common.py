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


@dataclass
class UsageTotals:
    """Token usage summed across one turn's model calls, priced at `model`'s rates (D8)."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_creation_input_tokens += (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def cost_usd(self) -> float:
        price = price_for(self.model)
        return (
            self.input_tokens * price.input
            + self.output_tokens * price.output
            + self.cache_creation_input_tokens * price.cache_write
            + self.cache_read_input_tokens * price.cache_read
        ) / 1_000_000


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


def attr_or_key(block: Any, name: str, default: Any = None) -> Any:
    value = getattr(block, name, None)
    if value is None and isinstance(block, dict):
        value = block.get(name, default)
    return value if value is not None else default


def _as_dict(b: Any) -> dict:
    return b.model_dump(exclude_none=True) if hasattr(b, "model_dump") and callable(b.model_dump) else b


def excerpt(text: str, max_chars: int = 400) -> str:
    """Trim a full document chunk to a readable 2-3 sentence excerpt.

    The Anthropic Citations API returns the entire chunk as cited_text. This
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


def collect_segments(response: Any) -> tuple[str, list[dict], list[dict]]:
    """Map the final response's text blocks into (reply_text, citations, segments)."""
    reply_text = ""
    citations: list[dict] = []
    segments: list[dict] = []
    for block in response.content:
        if attr_or_key(block, "type") != "text":
            continue
        block_text = attr_or_key(block, "text", "")
        reply_text += block_text
        cit_dicts = [_as_dict(cit) for cit in (attr_or_key(block, "citations") or [])]
        citations.extend(cit_dicts)
        segments.append(
            {
                "text": block_text,
                "citations": [
                    {
                        "source": c.get("source"),
                        "title": c.get("title"),
                        "cited_text": excerpt(c.get("cited_text") or ""),
                    }
                    for c in cit_dicts
                ],
            }
        )
    return reply_text, citations, segments


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
