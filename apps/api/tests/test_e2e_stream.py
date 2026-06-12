"""TC-3.8 (T3.5) and TC-3.9 (T3.7): live SSE contract and cache-hit assertions.

Requires RUN_INTEGRATION=1, a running pgvector DB with both corpora ingested,
and real ANTHROPIC_API_KEY / VOYAGE_API_KEY values.
"""
import json
import os

import pytest
from dotenv import load_dotenv

load_dotenv("../../.env")

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live API tests",
)


async def _stream_chat(client_id: str, message: str, conversation_id: str | None = None):
    """POST to the SSE endpoint, return the parsed [(event, data), ...] list."""
    import httpx

    from app.main import app

    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id

    events: list[tuple[str, dict]] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", f"/api/c/{client_id}/chat/stream", json=body, timeout=120.0
        ) as resp:
            assert resp.status_code == 200, await resp.aread()
            event_name = None
            data_lines: list[str] = []
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event_name = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                elif line == "" and event_name is not None:
                    events.append((event_name, json.loads("\n".join(data_lines))))
                    event_name, data_lines = None, []
    return events


@pytest.mark.asyncio
async def test_sse_event_contract() -> None:
    """TC-3.8 / UC-10: event names, ordering (tool before first text, done last),
    citation fields present."""
    events = await _stream_chat(
        "acme-fab", "How often does the chamber seal on the PX-900 need replacing?"
    )
    names = [n for n, _ in events]

    assert set(names) <= {"tool", "text", "citation", "done"}, names

    # tool before first text; done last and exactly once
    assert "tool" in names and "text" in names
    assert names.index("tool") < names.index("text")
    assert names[-1] == "done"
    assert names.count("done") == 1

    tool_starts = [d for n, d in events if n == "tool" and d["status"] == "start"]
    assert any(d["name"] == "search_docs" for d in tool_starts)

    citations = [d for n, d in events if n == "citation"]
    assert citations, "expected at least one citation event"
    for c in citations:
        assert {"index", "source", "title", "cited_text"} <= set(c)
    assert any("px900-maintenance-manual" in (c["source"] or "") for c in citations)

    done = events[-1][1]
    assert {
        "conversation_id",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cost_usd",
        "latency_ms",
    } <= set(done)
    assert done["input_tokens"] > 0 and done["output_tokens"] > 0
    assert done["cost_usd"] > 0

    # The streamed text should contain the sentinel answer
    full_text = "".join(d["delta"] for n, d in events if n == "text")
    assert "1,200" in full_text


@pytest.mark.asyncio
async def test_uc7_cache_hit_on_turn_two() -> None:
    """TC-3.9 / UC-7: turn 2 of a Meridian conversation reads from the prompt cache."""
    turn1 = await _stream_chat(
        "meridian-insurance",
        "What's the excess on accidental damage claims for HomeShield Plus?",
    )
    assert turn1[-1][0] == "done"
    done1 = turn1[-1][1]
    conversation_id = done1["conversation_id"]
    assert conversation_id

    text1 = "".join(d["delta"] for n, d in turn1 if n == "text")
    assert "500" in text1

    turn2 = await _stream_chat(
        "meridian-insurance",
        "And how long do I have to lodge a claim?",
        conversation_id=conversation_id,
    )
    assert turn2[-1][0] == "done"
    done2 = turn2[-1][1]

    assert done2["cache_read_input_tokens"] > 0, (
        f"expected a cache hit on turn 2, got usage {done2}"
    )

    text2 = "".join(d["delta"] for n, d in turn2 if n == "text")
    assert "30" in text2
