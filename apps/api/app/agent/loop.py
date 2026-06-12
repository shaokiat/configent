"""Agent loop: the manual tool-use loop over the Anthropic API.

Two entry points share conversation loading, request assembly, tool execution,
and persistence:

- `run`: non-streaming, returns the finished turn (T3.2).
- `stream_turn`: async generator yielding SSE-shaped `(event, data)` tuples per
  the UC-10 contract in POC_FACTORY_TEST_ANCHORS.md (T3.5). Persistence is
  identical to `run` — the final message comes from `get_final_message()`.
"""
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.models import Conversation, Message
from app.tools.registry import get_tool_definitions, get_tool_executor

logger = logging.getLogger("configent.agent")

_REPO_ROOT = Path(__file__).parents[4]
_MAX_ITERATIONS = 8

# Sonnet 4.6 pricing, USD per MTok (architecture §4.4/§4.7): prompt tokens bill
# at 1x fresh / 1.25x cache write / 0.1x cache read.
_PRICE_INPUT = 3.00
_PRICE_OUTPUT = 15.00
_PRICE_CACHE_WRITE = 3.75
_PRICE_CACHE_READ = 0.30


@dataclass
class UsageTotals:
    """Token usage summed across every API call in one turn."""

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
        return (
            self.input_tokens * _PRICE_INPUT
            + self.output_tokens * _PRICE_OUTPUT
            + self.cache_creation_input_tokens * _PRICE_CACHE_WRITE
            + self.cache_read_input_tokens * _PRICE_CACHE_READ
        ) / 1_000_000


@dataclass
class LoopResult:
    messages: list[dict]
    reply_text: str = ""
    citations: list[dict] = field(default_factory=list)
    # Frontend-friendly shape: ordered [{text, citations: [{source, title, cited_text}]}]
    segments: list[dict] = field(default_factory=list)
    usage: UsageTotals = field(default_factory=UsageTotals)


def _is_content_blocks(result: Any) -> bool:
    """Executors may return Anthropic content blocks (e.g. search_result) instead of
    plain JSON data; blocks go into tool_result content verbatim, data gets dumped."""
    return (
        isinstance(result, list)
        and len(result) > 0
        and all(isinstance(item, dict) and "type" in item for item in result)
    )


def _attr_or_key(block: Any, name: str, default: Any = None) -> Any:
    value = getattr(block, name, None)
    if value is None and isinstance(block, dict):
        value = block.get(name, default)
    return value if value is not None else default


async def _execute_tool(block: Any, *, client_id: str, db: AsyncSession) -> dict:
    name = _attr_or_key(block, "name")
    tool_id = _attr_or_key(block, "id")
    inp = _attr_or_key(block, "input")
    executor = get_tool_executor(name)
    try:
        result = await executor(inp, client_id=client_id, db=db)
    except Exception as exc:
        result = {"error": str(exc)}
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": result if _is_content_blocks(result) else json.dumps(result),
    }


def _sorted_tool_defs(tool_names: list[str]) -> list[dict]:
    """Caching (§4.4) is a prefix match over tools -> system -> messages, so the
    tool list must serialize in a fixed order regardless of YAML order."""
    return sorted(get_tool_definitions(tool_names), key=lambda d: d["name"])


def _with_turn_breakpoint(messages: list[dict]) -> list[dict]:
    """Return a copy of `messages` with a cache breakpoint on the last content
    block of the latest message, so multi-turn history accrues incrementally.

    Applied per call (never mutating the canonical list): a breakpoint baked into
    history would accumulate one marker per loop iteration and blow the
    4-breakpoint request limit."""
    last = dict(messages[-1])
    content = last["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    blocks = list(content)
    if isinstance(blocks[-1], dict):
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    last["content"] = blocks
    return messages[:-1] + [last]


def _log_usage(client_id: str, usage: Any) -> None:
    logger.info(
        "anthropic call client=%s input=%s output=%s cache_creation=%s cache_read=%s",
        client_id,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
    )


def _request_kwargs(
    cfg: ClientConfig,
    system_prompt: str,
    tool_defs: list[dict],
    messages: list[dict],
) -> dict:
    """Assemble kwargs for one API call. `messages` is snapshotted (with the
    per-turn cache breakpoint applied) so call_args captures the state at call
    time."""
    return {
        "model": cfg.agent.model,
        "max_tokens": cfg.agent.max_tokens,
        "thinking": {"type": "disabled"},
        "output_config": {"effort": cfg.agent.effort},
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": tool_defs,
        "messages": _with_turn_breakpoint(messages),
    }


def _dump_blocks(content: list[Any]) -> list[dict]:
    return [
        b.model_dump() if hasattr(b, "model_dump") and callable(b.model_dump) else b
        for b in content
    ]


def _tool_use_blocks(content: list[Any]) -> list[Any]:
    return [b for b in content if _attr_or_key(b, "type") == "tool_use"]


def _collect_segments(response: Any) -> tuple[str, list[dict], list[dict]]:
    """Map the final response's text blocks into (reply_text, citations, segments)."""
    reply_text = ""
    citations: list[dict] = []
    segments: list[dict] = []
    for block in response.content:
        if _attr_or_key(block, "type") != "text":
            continue
        block_text = _attr_or_key(block, "text", "")
        reply_text += block_text
        cit_dicts = [
            cit.model_dump() if hasattr(cit, "model_dump") and callable(cit.model_dump) else cit
            for cit in (_attr_or_key(block, "citations") or [])
        ]
        citations.extend(cit_dicts)
        segments.append(
            {
                "text": block_text,
                "citations": [
                    {
                        "source": c.get("source"),
                        "title": c.get("title"),
                        "cited_text": c.get("cited_text"),
                    }
                    for c in cit_dicts
                ],
            }
        )
    return reply_text, citations, segments


async def _run_loop(
    messages: list[dict],
    *,
    cfg: ClientConfig,
    client_id: str,
    system_prompt: str,
    db: AsyncSession,
    aclient: anthropic.AsyncAnthropic,
) -> LoopResult:
    """Core agent loop, non-streaming."""
    tool_defs = _sorted_tool_defs(cfg.agent.tools)
    result = LoopResult(messages=messages)

    for _ in range(_MAX_ITERATIONS):
        response = await aclient.messages.create(
            **_request_kwargs(cfg, system_prompt, tool_defs, messages)
        )
        _log_usage(client_id, getattr(response, "usage", None))
        result.usage.add(getattr(response, "usage", None))

        # Append full assistant content verbatim (tool_use blocks must not be lost)
        messages.append({"role": "assistant", "content": _dump_blocks(response.content)})

        if response.stop_reason in ("end_turn", "max_tokens"):
            result.reply_text, result.citations, result.segments = _collect_segments(response)
            return result

        if response.stop_reason == "tool_use":
            tool_results = await asyncio.gather(
                *[
                    _execute_tool(b, client_id=client_id, db=db)
                    for b in _tool_use_blocks(response.content)
                ]
            )
            messages.append({"role": "user", "content": list(tool_results)})
            continue

    raise RuntimeError(
        f"Agent loop exceeded {_MAX_ITERATIONS} iterations without completing"
    )


async def _stream_loop(
    messages: list[dict],
    *,
    cfg: ClientConfig,
    client_id: str,
    system_prompt: str,
    db: AsyncSession,
    aclient: anthropic.AsyncAnthropic,
    result: LoopResult,
) -> AsyncIterator[tuple[str, dict]]:
    """Core agent loop, streaming. Yields UC-10 events; fills `result` in place
    (async generators cannot return a value)."""
    tool_defs = _sorted_tool_defs(cfg.agent.tools)
    citation_index = 0

    for _ in range(_MAX_ITERATIONS):
        async with aclient.messages.stream(
            **_request_kwargs(cfg, system_prompt, tool_defs, messages)
        ) as stream:
            async for event in stream:
                etype = getattr(event, "type", "")
                if etype == "content_block_start":
                    if _attr_or_key(event.content_block, "type") == "tool_use":
                        yield (
                            "tool",
                            {"name": event.content_block.name, "status": "start"},
                        )
                elif etype == "content_block_delta":
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
                                "cited_text": _attr_or_key(cit, "cited_text"),
                            },
                        )
            response = await stream.get_final_message()

        _log_usage(client_id, getattr(response, "usage", None))
        result.usage.add(getattr(response, "usage", None))
        messages.append({"role": "assistant", "content": _dump_blocks(response.content)})

        if response.stop_reason == "tool_use":
            tool_blocks = _tool_use_blocks(response.content)
            tool_results = await asyncio.gather(
                *[_execute_tool(b, client_id=client_id, db=db) for b in tool_blocks]
            )
            for block in tool_blocks:
                yield ("tool", {"name": _attr_or_key(block, "name"), "status": "end"})
            messages.append({"role": "user", "content": list(tool_results)})
            continue

        # end_turn / max_tokens
        result.reply_text, result.citations, result.segments = _collect_segments(response)
        return

    raise RuntimeError(
        f"Agent loop exceeded {_MAX_ITERATIONS} iterations without completing"
    )


async def _prepare_conversation(
    db: AsyncSession, client_id: str, conversation_id: str | None
) -> tuple[str, list[dict]]:
    """Create the conversation row (first turn) or load prior message history."""
    if conversation_id is None:
        conv = Conversation(client_id=client_id)
        db.add(conv)
        await db.flush()
        return conv.id, []
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    )
    history = [{"role": m.role, "content": m.content} for m in result.scalars().all()]
    return conversation_id, history


async def _persist_turn(
    db: AsyncSession, conversation_id: str, history_len: int, result: LoopResult
) -> None:
    """Persist the messages added by the loop (assistant and tool results).

    `result.messages` starts with history + user; new entries start after
    history_len + 1. The final assistant message carries the frontend-friendly
    citation segments."""
    new_messages = result.messages[history_len + 1 :]
    for i, msg in enumerate(new_messages):
        is_final = i == len(new_messages) - 1 and msg["role"] == "assistant"
        db.add(
            Message(
                conversation_id=conversation_id,
                role=msg["role"],
                content=msg["content"],
                citations={"segments": result.segments} if is_final else {},
            )
        )
    await db.flush()


async def run(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> tuple[str, LoopResult]:
    """Run one chat turn, non-streaming. Returns (conversation_id, loop_result)."""
    conversation_id, history = await _prepare_conversation(db, client_id, conversation_id)
    system_prompt = cfg.system_prompt_path(_REPO_ROOT).read_text()
    messages: list[dict] = history + [{"role": "user", "content": user_message}]

    db.add(Message(conversation_id=conversation_id, role="user", content=user_message))
    await db.flush()

    aclient = anthropic.AsyncAnthropic()
    result = await _run_loop(
        messages,
        cfg=cfg,
        client_id=client_id,
        system_prompt=system_prompt,
        db=db,
        aclient=aclient,
    )

    await _persist_turn(db, conversation_id, len(history), result)
    await db.commit()
    return conversation_id, result


async def stream_turn(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one chat turn, streaming UC-10 `(event, data)` tuples.

    Event order: `tool` (start/end) and `text`/`citation` deltas as they arrive,
    then exactly one `done` carrying the usage summary and conversation_id.
    On failure an `error` event is emitted instead of `done`, and nothing is
    committed — the conversation history is left uncorrupted."""
    started = time.monotonic()
    conversation_id, history = await _prepare_conversation(db, client_id, conversation_id)
    system_prompt = cfg.system_prompt_path(_REPO_ROOT).read_text()
    messages: list[dict] = history + [{"role": "user", "content": user_message}]

    db.add(Message(conversation_id=conversation_id, role="user", content=user_message))
    await db.flush()

    aclient = anthropic.AsyncAnthropic()
    result = LoopResult(messages=messages)
    try:
        async for event in _stream_loop(
            messages,
            cfg=cfg,
            client_id=client_id,
            system_prompt=system_prompt,
            db=db,
            aclient=aclient,
            result=result,
        ):
            yield event
    except anthropic.APIError as exc:
        logger.exception("Anthropic API error during streamed turn (client=%s)", client_id)
        yield ("error", {"message": f"Upstream API error: {exc.__class__.__name__}"})
        return
    except Exception as exc:
        # The HTTP status is already sent; the SSE channel is the only way to
        # surface a failure to the client.
        logger.exception("Streamed turn failed (client=%s)", client_id)
        yield ("error", {"message": str(exc)})
        return

    await _persist_turn(db, conversation_id, len(history), result)
    await db.commit()

    yield (
        "done",
        {
            "conversation_id": conversation_id,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_creation_input_tokens": result.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": result.usage.cache_read_input_tokens,
            "cost_usd": round(result.usage.cost_usd, 6),
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )
