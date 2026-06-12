"""Tests for T3.2: agent loop mechanics (TC-3.2, TC-3.3, TC-3.4)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.loop import _MAX_ITERATIONS, _run_loop
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
    result = await _run_loop(
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

    assert result.reply_text == "Unit price is $1840."


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
    await _run_loop(
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


@pytest.mark.asyncio
async def test_search_result_block_shape() -> None:
    """TC-3.5: search_docs executor output matches architecture §4.3."""
    from app.retrieval.search import Hit
    from app.tools.shared import search_docs

    fake_hits = [
        Hit(
            chunk_id=1,
            document_id="doc1",
            document_title="PX-900 Maintenance Manual",
            source_uri="corpora/acme-fab/px900-maintenance-manual.md",
            text="The PX-900 plasma etcher requires chamber seal replacement every 1,200 RF hours.",
            similarity=0.91,
            chunk_index=0,
        )
    ]
    with patch("app.retrieval.search.search", AsyncMock(return_value=fake_hits)):
        blocks = await search_docs.execute(
            {"query": "chamber seal interval"}, client_id="acme-fab", db=AsyncMock()
        )

    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "search_result"
    assert block["source"] == "corpora/acme-fab/px900-maintenance-manual.md"
    assert block["title"] == "PX-900 Maintenance Manual"
    assert isinstance(block["content"], list)
    assert block["content"][0] == {"type": "text", "text": fake_hits[0].text}
    assert block["citations"] == {"enabled": True}


@pytest.mark.asyncio
async def test_search_result_blocks_empty_retrieval() -> None:
    """Empty retrieval returns a plain text block, never an empty content list."""
    from app.tools.shared import search_docs

    with patch("app.retrieval.search.search", AsyncMock(return_value=[])):
        blocks = await search_docs.execute(
            {"query": "quantum computing opinions"}, client_id="acme-fab", db=AsyncMock()
        )

    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"


@pytest.mark.asyncio
async def test_loop_block_results_passed_verbatim_and_segments(minimal_cfg: ClientConfig) -> None:
    """Content-block tool results enter tool_result.content as a list (not JSON-dumped),
    and the final text blocks map to ordered citation segments."""
    search_blocks = [
        {
            "type": "search_result",
            "source": "corpora/acme-fab/px900-maintenance-manual.md",
            "title": "PX-900 Maintenance Manual",
            "content": [{"type": "text", "text": "seal text"}],
            "citations": {"enabled": True},
        }
    ]
    citation = {
        "type": "search_result_location",
        "cited_text": "every 1,200 RF hours",
        "source": "corpora/acme-fab/px900-maintenance-manual.md",
        "title": "PX-900 Maintenance Manual",
        "search_result_index": 0,
        "start_block_index": 0,
        "end_block_index": 0,
    }
    cit_mock = MagicMock()
    cit_mock.model_dump.return_value = citation

    tool_block = _make_tool_use_block("toolu_01", "search_docs", {"query": "seal interval"})
    text_block = _make_text_block("Every 1,200 RF hours.", citations=[cit_mock])

    mock_create = AsyncMock(
        side_effect=[
            _make_response([tool_block], "tool_use"),
            _make_response([text_block], "end_turn"),
        ]
    )
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch(
        "app.tools.registry.get_tool_executor",
        return_value=AsyncMock(return_value=search_blocks),
    ), patch(
        "app.agent.loop.get_tool_executor",
        return_value=AsyncMock(return_value=search_blocks),
    ):
        result = await _run_loop(
            [{"role": "user", "content": "How often does the seal need replacing?"}],
            cfg=minimal_cfg,
            client_id="acme-fab",
            system_prompt="You are helpful.",
            db=AsyncMock(),
            aclient=mock_client,
        )

    # tool_result content must be the block list verbatim, not a JSON string
    second_call_messages = mock_create.call_args_list[1].kwargs["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["content"] == search_blocks

    assert result.segments == [
        {
            "text": "Every 1,200 RF hours.",
            "citations": [
                {
                    "source": "corpora/acme-fab/px900-maintenance-manual.md",
                    "title": "PX-900 Maintenance Manual",
                    "cited_text": "every 1,200 RF hours",
                }
            ],
        }
    ]
    assert result.citations == [citation]
