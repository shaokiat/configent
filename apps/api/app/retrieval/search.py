from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import RetrievalConfig
from app.models import Chunk, Document
from app.retrieval.embed import embed_queries


@dataclass
class Hit:
    chunk_id: int
    document_id: str
    document_title: str
    source_uri: str
    text: str
    similarity: float
    chunk_index: int


def _columns():
    return (
        Chunk.id,
        Chunk.document_id,
        Chunk.text,
        Chunk.chunk_index,
        Document.title.label("document_title"),
        Document.source_uri,
    )


def _hit(row, similarity: float) -> Hit:
    return Hit(
        chunk_id=row.id,
        document_id=row.document_id,
        document_title=row.document_title,
        source_uri=row.source_uri,
        text=row.text,
        similarity=similarity,
        chunk_index=row.chunk_index,
    )


async def _dense(
    db: AsyncSession, client_id: str, query_vec: list[float], k: int, floor: float
) -> list[Hit]:
    # pgvector's cosine distance comparator with the vector bound as a parameter (not
    # interpolated into SQL text); similarity = 1 - distance.
    similarity = (1 - Chunk.embedding.cosine_distance(query_vec)).label("similarity")
    stmt = (
        select(*_columns(), similarity)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.client_id == client_id)
        .order_by(similarity.desc())
        .limit(k * 2)  # fetch extra and filter by floor
    )
    rows = (await db.execute(stmt)).all()
    return [_hit(r, float(r.similarity)) for r in rows if float(r.similarity) >= floor][:k]


async def _keyword(db: AsyncSession, client_id: str, keywords: str, k: int) -> list[Hit]:
    """Postgres full-text search over `chunks.text_search`, for the exact terms embeddings
    blur: error codes, permission names, flags. `websearch_to_tsquery` never raises on
    user-shaped input, which `to_tsquery` does."""
    tsquery = func.websearch_to_tsquery("english", keywords)
    rank = func.ts_rank_cd(Chunk.text_search, tsquery).label("rank")
    stmt = (
        select(*_columns(), rank)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.client_id == client_id, Chunk.text_search.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(k * 2)
    )
    # A keyword match carries no cosine similarity; 0.0 says so rather than inventing one.
    return [_hit(r, 0.0) for r in (await db.execute(stmt)).all()]


def rrf_merge(ranked_lists: list[list[Hit]], k: int, *, rrf_k: int) -> list[Hit]:
    """Fuse several rankings by reciprocal rank: each list adds 1 / (rrf_k + rank) per chunk.

    `rrf_k` damps the gap between rank 1 and rank 2 so no single list dominates; 60 is the
    original paper's value and the schema default.

    Rank-based on purpose. Cosine similarities and `ts_rank_cd` scores are on unrelated
    scales, so adding them would be meaningless; positions are comparable.
    """
    scores: dict[int, float] = {}
    hits_by_id: dict[int, Hit] = {}
    for hits in ranked_lists:
        for position, hit in enumerate(hits):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1 / (rrf_k + position + 1)
            hits_by_id.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [hits_by_id[chunk_id] for chunk_id in ordered[:k]]


async def retrieve(
    db: AsyncSession,
    client_id: str,
    queries: list[str],
    keywords: str = "",
    *,
    cfg: RetrievalConfig,
    model: str,
    floor: float,
) -> list[Hit]:
    """The one retriever (D12): dense search for every query, plus full-text search on the
    exact keywords when enabled, fused by reciprocal rank. No new infrastructure — one GIN index.

    Level 1 is one query and no keywords; fusing a single list is the identity, so it takes the
    same path. `model` must be the one the chunks were embedded with, the client's
    `corpus.embedding.model`, which the fingerprint check holds to the index. `floor` drops weak
    dense hits so irrelevant results don't reach the model.
    """
    vecs = await embed_queries(queries, model)
    ranked = [await _dense(db, client_id, vec, cfg.top_k, floor) for vec in vecs]
    if cfg.keyword.enabled and keywords:
        ranked.append(await _keyword(db, client_id, keywords, cfg.top_k))
    return rrf_merge(ranked, cfg.top_k, rrf_k=cfg.rrf_k)
