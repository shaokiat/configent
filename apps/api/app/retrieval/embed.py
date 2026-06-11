import asyncio
import os
from typing import Final

import voyageai

# voyage-3 produces 1024-dimension vectors
EMBEDDING_DIM: Final[int] = 1024
_VOYAGE_BATCH_SIZE: Final[int] = 128  # Voyage AI batch limit


def _get_client() -> voyageai.Client:
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY environment variable is not set")
    return voyageai.Client(api_key=api_key)


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts using Voyage AI voyage-3.

    Batches automatically (Voyage caps at 128 per call). The SDK retries 429/5xx
    with exponential backoff internally.
    """
    if not texts:
        return []

    client = _get_client()
    results: list[list[float]] = []

    for i in range(0, len(texts), _VOYAGE_BATCH_SIZE):
        batch = texts[i : i + _VOYAGE_BATCH_SIZE]
        response = await asyncio.to_thread(
            client.embed,
            batch,
            model="voyage-3",
            input_type="document",
        )
        results.extend(response.embeddings)

    return results


async def embed_query(query: str) -> list[float]:
    """Embed a single query string with the query input_type for better retrieval."""
    client = _get_client()
    response = await asyncio.to_thread(
        client.embed,
        [query],
        model="voyage-3",
        input_type="query",
    )
    return response.embeddings[0]
