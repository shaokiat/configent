from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.retrieval.embed import embed_query


@dataclass
class Hit:
    chunk_id: int
    document_id: str
    document_title: str
    source_uri: str
    text: str
    similarity: float
    chunk_index: int


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
    query_vec = await embed_query(query)

    # Use pgvector's cosine distance comparator with the query vector bound as a
    # parameter (not interpolated into SQL text); similarity = 1 - distance.
    similarity = (1 - Chunk.embedding.cosine_distance(query_vec)).label("similarity")
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.text,
            Chunk.chunk_index,
            Document.title.label("document_title"),
            Document.source_uri,
            similarity,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.client_id == client_id)
        .order_by(similarity.desc())
        .limit(k * 2)  # fetch extra and filter by floor
    )

    rows = (await db.execute(stmt)).all()
    hits = [
        Hit(
            chunk_id=row.id,
            document_id=row.document_id,
            document_title=row.document_title,
            source_uri=row.source_uri,
            text=row.text,
            similarity=float(row.similarity),
            chunk_index=row.chunk_index,
        )
        for row in rows
        if float(row.similarity) >= floor
    ]
    return hits[:k]
