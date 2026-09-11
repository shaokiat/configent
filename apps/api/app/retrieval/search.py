from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.retrieval.embed import embed_queries, embed_query

# Reciprocal rank fusion constant. 60 is the value from the original RRF paper and the
# common default; it damps the gap between rank 1 and rank 2 so no single list dominates.
_RRF_K = 60


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


async def search(
    db: AsyncSession,
    client_id: str,
    query: str,
    k: int = 5,
    floor: float = 0.3,
) -> list[Hit]:
    """Cosine similarity top-k search over chunks, scoped to client_id.

    Drops hits below the similarity floor so irrelevant results don't reach the model.
    """
    return await _dense(db, client_id, await embed_query(query), k, floor)


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


def rrf_merge(ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
    """Fuse several rankings by reciprocal rank: each list adds 1 / (60 + rank) per chunk.

    Rank-based on purpose. Cosine similarities and `ts_rank_cd` scores are on unrelated
    scales, so adding them would be meaningless; positions are comparable.
    """
    scores: dict[int, float] = {}
    hits_by_id: dict[int, Hit] = {}
    for hits in ranked_lists:
        for position, hit in enumerate(hits):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1 / (_RRF_K + position + 1)
            hits_by_id.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [hits_by_id[chunk_id] for chunk_id in ordered[:k]]


async def hybrid_search(
    db: AsyncSession,
    client_id: str,
    queries: list[str],
    keywords: str,
    k: int = 5,
    floor: float = 0.3,
) -> list[Hit]:
    """Level 2 retrieval: dense search for every query variant, plus full-text search on the
    exact keywords, fused by reciprocal rank. No new infrastructure — one GIN index."""
    ranked = [await _dense(db, client_id, vec, k, floor) for vec in await embed_queries(queries)]
    if keywords:
        ranked.append(await _keyword(db, client_id, keywords, k))
    return rrf_merge(ranked, k)
