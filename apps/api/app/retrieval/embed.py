import asyncio
import os
from typing import Final

import voyageai
import voyageai.error

# voyage-3 produces 1024-dimension vectors
EMBEDDING_DIM: Final[int] = 1024
# Voyage caps at 128 per call; keyless free tier (10K TPM) needs a much smaller batch
_VOYAGE_BATCH_SIZE: Final[int] = int(os.getenv("VOYAGE_BATCH_SIZE", "128"))
_MAX_RETRIES: Final[int] = 6


def _get_client() -> voyageai.Client:
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY environment variable is not set")
    return voyageai.Client(api_key=api_key)


async def _embed_with_retry(
    client: voyageai.Client, texts: list[str], input_type: str
) -> list[list[float]]:
    delay = 21.0  # free-tier rate limits reset on a per-minute window (3 RPM)
    for attempt in range(_MAX_RETRIES):
        try:
            response = await asyncio.to_thread(
                client.embed,
                texts,
                model="voyage-3",
                input_type=input_type,
            )
            return response.embeddings
        except (voyageai.error.RateLimitError, voyageai.error.ServiceUnavailableError):
            if attempt == _MAX_RETRIES - 1:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 60.0)
    raise RuntimeError("unreachable")


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts using Voyage AI voyage-3.

    Batches automatically and retries 429/5xx with backoff sized to Voyage's
    per-minute rate-limit window.
    """
    if not texts:
        return []

    client = _get_client()
    results: list[list[float]] = []

    for i in range(0, len(texts), _VOYAGE_BATCH_SIZE):
        batch = texts[i : i + _VOYAGE_BATCH_SIZE]
        results.extend(await _embed_with_retry(client, batch, "document"))

    return results


async def embed_query(query: str) -> list[float]:
    """Embed a single query string with the query input_type for better retrieval."""
    client = _get_client()
    embeddings = await _embed_with_retry(client, [query], "query")
    return embeddings[0]
