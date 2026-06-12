"""Tests for T3.7: prompt-caching request assembly (architecture §4.4).

The live cache-hit assertion (TC-3.9) lives in test_e2e_stream.py.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.loop import _run_loop, _sorted_tool_defs, _with_turn_breakpoint
from app.config.schema import (
    AgentConfig,
    BrandingConfig,
    ChunkingConfig,
    ClientConfig,
    CorpusConfig,
)


@pytest.fixture
def minimal_cfg(tmp_path: Path) -> ClientConfig:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("You are a helpful assistant.")
    return ClientConfig(
        client_id="test-client",
        name="Test",
        branding=BrandingConfig(logo="l.svg", primary_color="#000", assistant_name="Bot"),
        corpus=CorpusConfig(source="corpora/test/", chunking=ChunkingConfig()),
        agent=AgentConfig(
            model="claude-sonnet-4-6",
            system_prompt_file=str(prompt),
            effort="medium",
            tools=["search_docs", "pricing_lookup", "get_document"],
        ),
    )


def _make_tool_use_block(tool_id: str, name: str, inp: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = inp
    block.model_dump.return_value = {
        "type": "tool_use", "id": tool_id, "name": name, "input": inp,
    }
    return block


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = []
    block.model_dump.return_value = {"type": "text", "text": text}
    return block


def _make_response(content: list, stop_reason: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


def test_tool_defs_sorted_by_name() -> None:
    """Tool serialization order is fixed regardless of YAML order, so the cached
    tools+system prefix is byte-stable."""
    defs_a = _sorted_tool_defs(["search_docs", "pricing_lookup", "get_document"])
    defs_b = _sorted_tool_defs(["get_document", "search_docs", "pricing_lookup"])
    names = [d["name"] for d in defs_a]
    assert names == sorted(names)
    assert defs_a == defs_b


def test_turn_breakpoint_on_string_user_message() -> None:
    messages = [{"role": "user", "content": "What is the seal interval?"}]
    out = _with_turn_breakpoint(messages)
    assert out[-1]["content"] == [
        {
            "type": "text",
            "text": "What is the seal interval?",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    # Canonical list untouched
    assert messages[-1]["content"] == "What is the seal interval?"


def test_turn_breakpoint_on_last_block_only() -> None:
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "search_docs", "input": {}}]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "a"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "b"},
            ],
        },
    ]
    out = _with_turn_breakpoint(messages)
    last_blocks = out[-1]["content"]
    assert "cache_control" not in last_blocks[0]
    assert last_blocks[1]["cache_control"] == {"type": "ephemeral"}
    # Earlier messages and the canonical list are untouched
    assert out[0] is messages[0]
    assert out[1] is messages[1]
    assert "cache_control" not in messages[-1]["content"][1]


@pytest.mark.asyncio
async def test_loop_request_carries_cache_breakpoints(minimal_cfg: ClientConfig) -> None:
    """Each API call has exactly two breakpoints: the last system block and the
    last content block of the latest message — markers never accumulate in history."""
    tool_block = _make_tool_use_block("toolu_01", "pricing_lookup", {"part_number": "X"})
    text_block = _make_text_block("Done.")

    mock_create = AsyncMock(
        side_effect=[
            _make_response([tool_block], "tool_use"),
            _make_response([text_block], "end_turn"),
        ]
    )
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    await _run_loop(
        [{"role": "user", "content": "Price part X."}],
        cfg=minimal_cfg,
        client_id="test-client",
        system_prompt="You are helpful.",
        db=AsyncMock(),
        aclient=mock_client,
    )

    for call in mock_create.call_args_list:
        kwargs = call.kwargs
        assert kwargs["system"][-1]["cache_control"] == {"type": "ephemeral"}

        sent = kwargs["messages"]
        breakpoint_count = sum(
            1
            for m in sent
            if isinstance(m["content"], list)
            for b in m["content"]
            if isinstance(b, dict) and "cache_control" in b
        )
        assert breakpoint_count == 1
        assert sent[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    # Second call: the turn-1 user message went back to plain string content
    second_messages = mock_create.call_args_list[1].kwargs["messages"]
    assert second_messages[0]["content"] == "Price part X."
