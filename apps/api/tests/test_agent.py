"""Tests for T3.2: agent loop mechanics (TC-3.2, TC-3.3, TC-3.4)."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.loop import _run_loop, _MAX_ITERATIONS
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
            tools=["pricing_lookup"],
        ),
    )


def _make_tool_use_block(tool_id: str, name: str, inp: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = inp
    block.model_dump.return_value = {
        "type": "tool_use",
        "id": tool_id,
        "name": name,
        "input": inp,
    }
    return block


def _make_text_block(text: str, citations: list | None = None) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = citations or []
    block.model_dump.return_value = {"type": "text", "text": text}
    return block


def _make_response(content: list, stop_reason: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


@pytest.mark.asyncio
async def test_loop_appends_full_content(minimal_cfg: ClientConfig) -> None:
    """TC-3.2: assistant content blocks are appended verbatim; second call sees them."""
    tool_block = _make_tool_use_block("toolu_01", "pricing_lookup", {"part_number": "PX900-SEAL-A2"})
    text_block = _make_text_block("Unit price is $1840.")

    mock_create = AsyncMock(
        side_effect=[
            _make_response([tool_block], "tool_use"),
            _make_response([text_block], "end_turn"),
        ]
    )
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    messages = [{"role": "user", "content": "How much for PX900-SEAL-A2?"}]
    final_messages, reply, _ = await _run_loop(
        messages,
        cfg=minimal_cfg,
        client_id="test-client",
        system_prompt="You are helpful.",
        db=AsyncMock(),
        aclient=mock_client,
    )

    assert mock_create.call_count == 2
    second_call_messages = mock_create.call_args_list[1].kwargs["messages"]

    # The assistant message must be present and contain the tool_use block verbatim
    assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == [tool_block.model_dump.return_value]

    assert reply == "Unit price is $1840."


@pytest.mark.asyncio
async def test_loop_parallel_tool_calls_one_message(minimal_cfg: ClientConfig) -> None:
    """TC-3.3: 2 parallel tool_use blocks produce exactly one user message with 2 tool_results."""
    block_a = _make_tool_use_block("toolu_A", "pricing_lookup", {"part_number": "PX900-SEAL-A2"})
    block_b = _make_tool_use_block("toolu_B", "pricing_lookup", {"part_number": "LT200-VALVE-B1"})
    text_block = _make_text_block("Here are both prices.")

    mock_create = AsyncMock(
        side_effect=[
            _make_response([block_a, block_b], "tool_use"),
            _make_response([text_block], "end_turn"),
        ]
    )
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    messages = [{"role": "user", "content": "Price both parts."}]
    final_messages, reply, _ = await _run_loop(
        messages,
        cfg=minimal_cfg,
        client_id="test-client",
        system_prompt="You are helpful.",
        db=AsyncMock(),
        aclient=mock_client,
    )

    assert mock_create.call_count == 2
    second_call_messages = mock_create.call_args_list[1].kwargs["messages"]

    # The tool results must be in a single user message
    user_msgs_after_start = [m for m in second_call_messages if m["role"] == "user"]
    # Last user message should be the tool results message
    tool_result_msg = user_msgs_after_start[-1]
    results = tool_result_msg["content"]

    assert len(results) == 2
    result_ids = {r["tool_use_id"] for r in results}
    assert result_ids == {"toolu_A", "toolu_B"}
    assert all(r["type"] == "tool_result" for r in results)


@pytest.mark.asyncio
async def test_loop_iteration_cap(minimal_cfg: ClientConfig) -> None:
    """TC-3.4: loop always returning tool_use raises RuntimeError at the cap."""
    tool_block = _make_tool_use_block("toolu_01", "pricing_lookup", {"part_number": "PX900-SEAL-A2"})
    # Every response is tool_use — loop should hit the cap and raise
    mock_create = AsyncMock(
        return_value=_make_response([tool_block], "tool_use")
    )
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    messages = [{"role": "user", "content": "Price?"}]
    with pytest.raises(RuntimeError, match=str(_MAX_ITERATIONS)):
        await _run_loop(
            messages,
            cfg=minimal_cfg,
            client_id="test-client",
            system_prompt="You are helpful.",
            db=AsyncMock(),
            aclient=mock_client,
        )

    assert mock_create.call_count == _MAX_ITERATIONS
