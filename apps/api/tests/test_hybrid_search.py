"""Level 2 retrieval: rank fusion in Python, and the keyword half against a real Postgres.

The merge is where a keyword-only match either reaches the grader or is lost, so it is
tested on its own. The SQL runs only with RUN_INTEGRATION=1 and an ingested corpus.
"""
import os

import pytest
from pydantic import ValidationError

from app.config.schema import RetrievalConfig
from app.retrieval import search as retrieval
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
    assert 9 in [h.chunk_id for h in rrf_merge([dense, keyword], k=3, rrf_k=60)]


def test_agreement_across_lists_ranks_first():
    merged = rrf_merge(
        [[_hit(1, 0.60), _hit(2, 0.55)], [_hit(2, 0.58), _hit(3, 0.50)], [_hit(2, 0.0)]], k=5, rrf_k=60
    )
    assert merged[0].chunk_id == 2


def test_k_caps_the_result():
    lists = [[_hit(i, 0.5) for i in range(10)]]
    assert len(rrf_merge(lists, k=5, rrf_k=60)) == 5


def test_no_lists_is_no_hits():
    assert rrf_merge([], k=5, rrf_k=60) == []


def test_fusing_one_list_is_the_identity():
    """Level 1 goes through the same path: one list in, the same hits in the same order."""
    hits = [_hit(3, 0.9), _hit(1, 0.7), _hit(2, 0.4)]
    assert rrf_merge([hits], k=5, rrf_k=60) == hits


def test_rrf_k_changes_the_fused_order_as_the_formula_says():
    # Chunk 1 is rank 1 in A only; chunk 2 is rank 3 in both A and B.
    a, b = [_hit(1, 0), _hit(4, 0), _hit(2, 0)], [_hit(5, 0), _hit(6, 0), _hit(2, 0)]
    # rrf_k=60: chunk 1 scores 1/61, chunk 2 scores 2/63, so agreement outranks a lone first.
    assert rrf_merge([a, b], k=3, rrf_k=60)[0].chunk_id == 2
    # rrf_k=0: chunk 1 scores 1/1, chunk 2 scores 2/3, so the lone first place wins.
    assert rrf_merge([a, b], k=3, rrf_k=0)[0].chunk_id == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled, expected_calls", [(True, 1), (False, 0)])
async def test_keyword_enabled_false_makes_no_keyword_query(monkeypatch, enabled, expected_calls):
    keyword_calls = []

    async def fake_embed(queries, model):
        return [[0.0]] * len(queries)

    async def fake_dense(*_a):
        return [_hit(1, 0.5)]

    async def fake_keyword(*_a):
        keyword_calls.append(1)
        return [_hit(9, 0.0)]

    monkeypatch.setattr(retrieval, "embed_queries", fake_embed)
    monkeypatch.setattr(retrieval, "_dense", fake_dense)
    monkeypatch.setattr(retrieval, "_keyword", fake_keyword)
    cfg = RetrievalConfig(keyword={"enabled": enabled})
    await retrieval.retrieve(None, "c", ["q", "q2"], "iam.actAs", cfg=cfg, model="m", floor=0.3)
    assert len(keyword_calls) == expected_calls


@pytest.mark.asyncio
async def test_default_config_level_one_returns_the_dense_hits_untouched(monkeypatch):
    """No `retrieval:` block means today's behaviour: Level 1 gets its dense hits back with
    the same order and the same similarities, and no keyword query runs."""
    dense = [_hit(3, 0.81), _hit(1, 0.64), _hit(2, 0.33)]

    async def fake_embed(queries, model):
        return [[0.0]]

    async def fake_dense(_db, _cid, _vec, k, floor):
        assert (k, floor) == (5, 0.3)
        return dense

    async def no_keyword(*_a):
        raise AssertionError("Level 1 must not run keyword search")

    monkeypatch.setattr(retrieval, "embed_queries", fake_embed)
    monkeypatch.setattr(retrieval, "_dense", fake_dense)
    monkeypatch.setattr(retrieval, "_keyword", no_keyword)
    out = await retrieval.retrieve(None, "c", ["q"], cfg=RetrievalConfig(), model="m", floor=0.3)
    assert out == dense


def test_an_unknown_retrieval_key_fails_naming_the_field():
    with pytest.raises(ValidationError, match="topk"):
        RetrievalConfig(topk=3)
    with pytest.raises(ValidationError, match="language"):
        RetrievalConfig(keyword={"language": "german"})


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
