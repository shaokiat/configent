"""Ingestion logic: parse → chunk → embed → upsert."""
import hashlib
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.models import Chunk, Client, Document
from app.retrieval.chunker import chunk_document
from app.retrieval.embed import embed
from app.retrieval.parsers import iter_corpus, parse_document


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _doc_id(client_id: str, source_uri: str) -> str:
    return hashlib.md5(f"{client_id}:{source_uri}".encode()).hexdigest()[:8]


async def ingest_client(
    db: AsyncSession,
    cfg: ClientConfig,
    repo_root: Path,
    *,
    force: bool = False,
) -> dict:
    """Ingest all documents for a client. Returns a summary dict."""
    corpus_dir = repo_root / cfg.corpus.source
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    # Ensure client row exists
    client_row = await db.get(Client, cfg.client_id)
    if client_row is None:
        db.add(Client(id=cfg.client_id, name=cfg.name))
        await db.flush()

    paths = iter_corpus(corpus_dir)
    stats = {"added": 0, "skipped": 0, "replaced": 0, "total_chunks": 0}

    for path in paths:
        rel_path = path.relative_to(repo_root)
        source_uri = f"corpus://{cfg.client_id}/{rel_path.stem}"
        doc_id = _doc_id(cfg.client_id, source_uri)

        parsed = parse_document(path)
        content_hash = _content_hash(parsed.text)

        existing: Document | None = await db.get(Document, doc_id)

        if existing is not None and existing.content_hash == content_hash and not force:
            stats["skipped"] += 1
            continue

        if existing is not None:
            # Delete existing chunks (cascade) and replace document
            await db.delete(existing)
            await db.flush()
            stats["replaced"] += 1
        else:
            stats["added"] += 1

        doc = Document(
            id=doc_id,
            client_id=cfg.client_id,
            source_uri=source_uri,
            title=parsed.title,
            content_hash=content_hash,
        )
        db.add(doc)
        await db.flush()

        # Chunk the document
        raw_chunks = chunk_document(
            parsed.text,
            document_title=parsed.title,
            source_uri=source_uri,
            chunk_size=cfg.corpus.chunking.chunk_size,
            overlap=cfg.corpus.chunking.overlap,
        )

        if not raw_chunks:
            continue

        # Embed all chunks in one batch call
        texts = [c.text for c in raw_chunks]
        embeddings = await embed(texts)

        for i, (raw, vec) in enumerate(zip(raw_chunks, embeddings)):
            db.add(
                Chunk(
                    document_id=doc_id,
                    client_id=cfg.client_id,
                    text=raw.text,
                    embedding=vec,
                    chunk_index=i,
                    metadata_={
                        "document_title": parsed.title,
                        "source_uri": source_uri,
                        "position": i,
                    },
                )
            )

        stats["total_chunks"] += len(raw_chunks)

    await db.commit()
    return stats
