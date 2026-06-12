import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.models import Conversation, Message
from app.tools.registry import get_tool_definitions, get_tool_executor

_REPO_ROOT = Path(__file__).parents[4]
_MAX_ITERATIONS = 8


@dataclass
class LoopResult:
    messages: list[dict]
    reply_text: str = ""
    citations: list[dict] = field(default_factory=list)
    # Frontend-friendly shape: ordered [{text, citations: [{source, title, cited_text}]}]
    segments: list[dict] = field(default_factory=list)


def _is_content_blocks(result: Any) -> bool:
    """Executors may return Anthropic content blocks (e.g. search_result) instead of
    plain JSON data; blocks go into tool_result content verbatim, data gets dumped."""
    return (
        isinstance(result, list)
        and len(result) > 0
        and all(isinstance(item, dict) and "type" in item for item in result)
    )


async def _execute_tool(block: Any, *, client_id: str, db: AsyncSession) -> dict:
    name = getattr(block, "name", None) or block["name"]
    tool_id = getattr(block, "id", None) or block["id"]
    inp = getattr(block, "input", None) or block["input"]
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


async def _run_loop(
    messages: list[dict],
    *,
    cfg: ClientConfig,
    client_id: str,
    system_prompt: str,
    db: AsyncSession,
    aclient: anthropic.AsyncAnthropic,
) -> LoopResult:
    """Core agent loop."""
    tool_defs = get_tool_definitions(cfg.agent.tools)
    reply_text = ""
    citations: list[dict] = []
    segments: list[dict] = []

    for _ in range(_MAX_ITERATIONS):
        response = await aclient.messages.create(
            model=cfg.agent.model,
            max_tokens=cfg.agent.max_tokens,
            thinking={"type": "disabled"},
            output_config={"effort": cfg.agent.effort},
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tool_defs,
            messages=list(messages),  # snapshot so call_args captures the state at call time
        )

        # Append full assistant content verbatim (tool_use blocks must not be lost)
        assistant_blocks = [
            b.model_dump() if hasattr(b, "model_dump") and callable(b.model_dump) else b
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_blocks})

        if response.stop_reason in ("end_turn", "max_tokens"):
            for block in response.content:
                btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                if btype == "text":
                    block_text = getattr(block, "text", None) or (block.get("text", "") if isinstance(block, dict) else "")
                    reply_text += block_text
                    block_citations = getattr(block, "citations", None) or (block.get("citations") if isinstance(block, dict) else None) or []
                    cit_dicts = [
                        cit.model_dump() if hasattr(cit, "model_dump") and callable(cit.model_dump) else cit
                        for cit in block_citations
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
            return LoopResult(
                messages=messages,
                reply_text=reply_text,
                citations=citations,
                segments=segments,
            )

        if response.stop_reason == "tool_use":
            tool_use_blocks = [
                b for b in response.content
                if (getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)) == "tool_use"
            ]
            tool_results = await asyncio.gather(
                *[_execute_tool(b, client_id=client_id, db=db) for b in tool_use_blocks]
            )
            messages.append({"role": "user", "content": list(tool_results)})
            continue

    raise RuntimeError(
        f"Agent loop exceeded {_MAX_ITERATIONS} iterations without completing"
    )


async def run(
    user_message: str,
    *,
    cfg: ClientConfig,
    client_id: str,
    conversation_id: str | None,
    db: AsyncSession,
) -> tuple[str, LoopResult]:
    """Run one chat turn. Returns (conversation_id, loop_result)."""
    if conversation_id is None:
        conv = Conversation(client_id=client_id)
        db.add(conv)
        await db.flush()
        conversation_id = conv.id
        history: list[dict] = []
    else:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
        history = [{"role": m.role, "content": m.content} for m in result.scalars().all()]

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

    # Persist the new messages added by the loop (assistant and tool results).
    # messages starts with history + user; new entries start after len(history)+1.
    # The final assistant message carries the frontend-friendly citation segments.
    new_start = len(history) + 1
    new_messages = result.messages[new_start:]
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

    await db.commit()
    return conversation_id, result
