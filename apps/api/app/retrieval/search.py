from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.retrieval.embed import EMBEDDING_DIM, embed_query


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
    vec_literal = f"[{','.join(str(v) for v in query_vec)}]"

    # Use pgvector's cosine distance operator (<=>); similarity = 1 - distance
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.text,
            Chunk.chunk_index,
            Document.title.label("document_title"),
            Document.source_uri,
            (1 - Chunk.embedding.cosine_distance(text(f"'{vec_literal}'::vector"))).label(
                "similarity"
            ),
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.client_id == client_id)
        .order_by(text("similarity DESC"))
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
