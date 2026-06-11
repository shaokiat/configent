import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.retrieval.embed import EMBEDDING_DIM, embed


def _mock_voyage_response(texts: list[str]) -> MagicMock:
    response = MagicMock()
    response.embeddings = [[0.1] * EMBEDDING_DIM for _ in texts]
    return response


@pytest.mark.asyncio
async def test_embed_returns_correct_shape():
    texts = ["hello world", "foo bar"]
    with patch("app.retrieval.embed._get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        client.embed.return_value = _mock_voyage_response(texts)

        result = await embed(texts)

    assert len(result) == 2
    assert len(result[0]) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_empty_returns_empty():
    result = await embed([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_batches_large_input():
    # 300 texts should produce 3 batches (batch size 128)
    texts = [f"text {i}" for i in range(300)]
    call_count = 0

    def fake_embed(batch, model, input_type):
        nonlocal call_count
        call_count += 1
        return _mock_voyage_response(batch)

    with patch("app.retrieval.embed._get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        client.embed.side_effect = fake_embed

        result = await embed(texts)

    assert call_count == 3  # ceil(300/128) = 3
    assert len(result) == 300
