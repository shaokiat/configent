"""Level 2 retrieval: rank fusion in Python, and the keyword half against a real Postgres.

The merge is where a keyword-only match either reaches the grader or is lost, so it is
tested on its own. The SQL runs only with RUN_INTEGRATION=1 and an ingested corpus.
"""
import os

import pytest

from app.retrieval.search import Hit, rrf_merge


def _hit(chunk_id: int, similarity: float) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        document_id="d",
        document_title="t",
        source_uri=f"corpus://x/{chunk_id}",
        text="...",
        similarity=similarity,
        chunk_index=0,
    )


def test_a_keyword_only_match_survives_the_merge():
    """The case Level 2 exists for: dense retrieval never saw chunk 9."""
    dense = [_hit(1, 0.61), _hit(2, 0.52)]
    keyword = [_hit(9, 0.0)]
    assert 9 in [h.chunk_id for h in rrf_merge([dense, keyword], k=3)]


def test_agreement_across_lists_ranks_first_and_keeps_the_best_similarity():
    merged = rrf_merge(
        [[_hit(1, 0.60), _hit(2, 0.55)], [_hit(2, 0.58), _hit(3, 0.50)], [_hit(2, 0.0)]], k=5
    )
    assert merged[0].chunk_id == 2
    assert merged[0].similarity == 0.58


def test_k_caps_the_result():
    lists = [[_hit(i, 0.5) for i in range(10)]]
    assert len(rrf_merge(lists, k=5)) == 5


def test_no_lists_is_no_hits():
    assert rrf_merge([], k=5) == []


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to query Postgres"
)
@pytest.mark.asyncio
async def test_full_text_search_finds_an_exact_permission_name():
    """`iam.serviceAccounts.actAs` is one sentence in one troubleshooting page — the kind of
    token an embedding blurs and a tsvector matches exactly."""
    from app.database import AsyncSessionLocal
    from app.retrieval.search import _keyword

    async with AsyncSessionLocal() as db:
        hits = await _keyword(db, "gcp-platform-support", "iam.serviceAccounts.actAs", k=5)
    assert any("cloud-run-troubleshooting" in h.source_uri for h in hits)
