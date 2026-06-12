"""Tests for T3.5: streaming loop event production (mocked Anthropic stream).

The live SSE contract test (TC-3.8) lives in test_e2e_stream.py.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.loop import LoopResult, _stream_loop
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
            tools=["search_docs"],
        ),
    )


class FakeStream:
    """Mimics the SDK's AsyncMessageStream: async-iterable events + get_final_message."""

    def __init__(self, events: list, final_message: MagicMock):
        self._events = events
        self._final = final_message

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for e in self._events:
            yield e

    async def get_final_message(self):
        return self._final


class FakeStreamManager:
    def __init__(self, stream: FakeStream):
        self._stream = stream

    async def __aenter__(self):
        return self._stream

    async def __aexit__(self, *exc):
        return False


def _tool_use_block(tool_id: str, name: str, inp: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = inp
    block.model_dump.return_value = {
        "type": "tool_use", "id": tool_id, "name": name, "input": inp,
    }
    return block


def _text_block(text: str, citations: list | None = None) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = citations or []
    block.model_dump.return_value = {"type": "text", "text": text}
    return block


def _final_message(content: list, stop_reason: str, **usage) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.stop_reason = stop_reason
    msg.usage = SimpleNamespace(
        input_tokens=usage.get("input_tokens", 100),
        output_tokens=usage.get("output_tokens", 50),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
    )
    return msg


def _block_start(block: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_start", content_block=block, index=0)


def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text), index=0
    )


def _citations_delta(source: str, title: str, cited_text: str) -> SimpleNamespace:
    citation = SimpleNamespace(
        type="search_result_location", source=source, title=title, cited_text=cited_text
    )
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="citations_delta", citation=citation),
        index=0,
    )


@pytest.mark.asyncio
async def test_stream_loop_event_sequence(minimal_cfg: ClientConfig) -> None:
    """Tool start/end precede text; text deltas and citation events arrive in order;
    result is filled like the non-streaming loop."""
    tool_block = _tool_use_block("toolu_01", "search_docs", {"query": "seal interval"})
    cit_mock = MagicMock()
    cit_mock.model_dump.return_value = {
        "type": "search_result_location",
        "cited_text": "every 1,200 RF hours",
        "source": "corpora/acme-fab/px900-maintenance-manual.md",
        "title": "PX-900 Maintenance Manual",
    }
    answer_block = _text_block("Every 1,200 RF hours.", citations=[cit_mock])

    # Call 1: model streams a tool_use block, stops for tools.
    stream1 = FakeStream(
        [_block_start(tool_block)],
        _final_message([tool_block], "tool_use", input_tokens=200),
    )
    # Call 2: model streams the answer with one citation.
    stream2 = FakeStream(
        [
            _block_start(answer_block),
            _text_delta("Every 1,200 "),
            _citations_delta(
                "corpora/acme-fab/px900-maintenance-manual.md",
                "PX-900 Maintenance Manual",
                "every 1,200 RF hours",
            ),
            _text_delta("RF hours."),
        ],
        _final_message([answer_block], "end_turn", cache_read_input_tokens=3000),
    )

    mock_client = MagicMock()
    mock_client.messages.stream = MagicMock(
        side_effect=[FakeStreamManager(stream1), FakeStreamManager(stream2)]
    )

    messages = [{"role": "user", "content": "How often does the seal need replacing?"}]
    result = LoopResult(messages=messages)
    search_blocks = [
        {
            "type": "search_result",
            "source": "corpora/acme-fab/px900-maintenance-manual.md",
            "title": "PX-900 Maintenance Manual",
            "content": [{"type": "text", "text": "seal text"}],
            "citations": {"enabled": True},
        }
    ]

    events = []
    with patch(
        "app.agent.loop.get_tool_executor",
        return_value=AsyncMock(return_value=search_blocks),
    ):
        async for event in _stream_loop(
            messages,
            cfg=minimal_cfg,
            client_id="acme-fab",
            system_prompt="You are helpful.",
            db=AsyncMock(),
            aclient=mock_client,
            result=result,
        ):
            events.append(event)

    names = [e[0] for e in events]
    assert names == ["tool", "tool", "text", "citation", "text"]

    assert events[0] == ("tool", {"name": "search_docs", "status": "start"})
    assert events[1] == ("tool", {"name": "search_docs", "status": "end"})

    # tool events come before the first text delta (UC-10 ordering)
    assert names.index("tool") < names.index("text")

    citation = events[3][1]
    assert citation["index"] == 1
    assert citation["source"] == "corpora/acme-fab/px900-maintenance-manual.md"
    assert citation["title"] == "PX-900 Maintenance Manual"
    assert citation["cited_text"] == "every 1,200 RF hours"

    # Reconstructed text matches the deltas
    assert "".join(d["delta"] for n, d in events if n == "text") == "Every 1,200 RF hours."

    # Result filled like the non-streaming loop: full content appended, usage summed
    assert result.reply_text == "Every 1,200 RF hours."
    assert result.usage.input_tokens == 300
    assert result.usage.cache_read_input_tokens == 3000
    assistant_msgs = [m for m in result.messages if m["role"] == "assistant"]
    assert assistant_msgs[0]["content"] == [tool_block.model_dump.return_value]

    # Tool results were appended as one user message before the second call
    second_call_messages = mock_client.messages.stream.call_args_list[1].kwargs["messages"]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert tool_result_msg["content"][0]["tool_use_id"] == "toolu_01"


@pytest.mark.asyncio
async def test_stream_loop_iteration_cap(minimal_cfg: ClientConfig) -> None:
    """A stream that always stops for tools raises RuntimeError at the cap."""
    from app.agent.loop import _MAX_ITERATIONS

    tool_block = _tool_use_block("toolu_01", "search_docs", {"query": "q"})

    def make_manager(**kwargs):
        return FakeStreamManager(
            FakeStream([_block_start(tool_block)], _final_message([tool_block], "tool_use"))
        )

    mock_client = MagicMock()
    mock_client.messages.stream = MagicMock(side_effect=make_manager)

    messages = [{"role": "user", "content": "q"}]
    with patch(
        "app.agent.loop.get_tool_executor",
        return_value=AsyncMock(return_value={"ok": True}),
    ):
        with pytest.raises(RuntimeError, match=str(_MAX_ITERATIONS)):
            async for _ in _stream_loop(
                messages,
                cfg=minimal_cfg,
                client_id="acme-fab",
                system_prompt="You are helpful.",
                db=AsyncMock(),
                aclient=mock_client,
                result=LoopResult(messages=messages),
            ):
                pass

    assert mock_client.messages.stream.call_count == _MAX_ITERATIONS
