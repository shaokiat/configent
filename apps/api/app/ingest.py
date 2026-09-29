"""Ingestion: reconcile a client's index with its corpus folder and `corpus` config.

The YAML is the spec, the `documents` table is the status. Each run:
  1. hashes every file's raw bytes (no parsing yet),
  2. plans: rebuild a file whose hash or ingest fingerprint differs from what is stored,
     prune an indexed document whose file is gone, skip the rest,
  3. rebuilds each planned file — parse → chunk → embed → replace — and commits it alone,
  4. prunes, then commits.
"""
import hashlib
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.models import Chunk, Client, Document
from app.retrieval.chunker import chunk_document
from app.retrieval.embed import embed
from app.retrieval.parsers import iter_corpus, parse_document


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def _doc_id(client_id: str, source_uri: str) -> str:
    return hashlib.md5(f"{client_id}:{source_uri}".encode()).hexdigest()[:8]


async def _delete_documents(db: AsyncSession, client_id: str, source_uris: list[str]) -> None:
    # chunks.document_id is ON DELETE CASCADE, so the chunks go with the row.
    await db.execute(
        delete(Document).where(
            Document.client_id == client_id, Document.source_uri.in_(source_uris)
        )
    )


def plan(
    files: dict[str, str],
    indexed: dict[str, tuple[str, str | None]],
    fingerprint: str,
    *,
    force: bool = False,
) -> tuple[list[str], list[str]]:
    """Which source URIs to rebuild and which to prune.

    `files` maps each corpus file's source URI to its content hash; `indexed` maps each
    stored document's source URI to its (content hash, ingest fingerprint).
    """
    rebuild = [uri for uri, h in files.items() if force or indexed.get(uri) != (h, fingerprint)]
    prune = [uri for uri in indexed if uri not in files]
    return rebuild, prune


async def index_mismatch(db: AsyncSession, cfg: ClientConfig) -> str | None:
    """Why this client's index cannot serve its config, or None if it can.

    One distinct-value query per chat request. Retrieval embeds the question with the
    configured model, so an index built under any other settings answers with noise.
    """
    stored = set(
        (
            await db.execute(
                select(Document.ingest_fingerprint)
                .where(Document.client_id == cfg.client_id)
                .distinct()
            )
        ).scalars()
    )
    if not stored:
        return f"No documents are indexed for {cfg.client_id!r}."
    if stored != {cfg.corpus.fingerprint()}:
        return (
            f"The index for {cfg.client_id!r} was built under different corpus settings "
            f"(embedding model or chunking) than its config declares."
        )
    return None


async def ingest_client(
    db: AsyncSession,
    cfg: ClientConfig,
    repo_root: Path,
    *,
    force: bool = False,
) -> dict:
    """Reconcile one client's index with its corpus. Returns a summary dict."""
    corpus_dir = repo_root / cfg.corpus.source
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    if await db.get(Client, cfg.client_id) is None:
        db.add(Client(id=cfg.client_id, name=cfg.name))
        await db.commit()

    fingerprint = cfg.corpus.fingerprint()
    # The full relative path, extension included: `iam.md` and `iam.pdf`, or
    # `a/setup.md` and `b/setup.md`, are different documents.
    paths = {
        f"corpus://{cfg.client_id}/{p.relative_to(corpus_dir).as_posix()}": p
        for p in iter_corpus(corpus_dir)
    }
    files = {uri: _content_hash(p.read_bytes()) for uri, p in paths.items()}
    indexed = {
        row.source_uri: (row.content_hash, row.ingest_fingerprint)
        for row in (
            await db.execute(
                select(
                    Document.source_uri, Document.content_hash, Document.ingest_fingerprint
                ).where(Document.client_id == cfg.client_id)
            )
        ).all()
    }
    rebuild, prune = plan(files, indexed, fingerprint, force=force)

    stats = {
        "added": 0,
        "replaced": 0,
        "skipped": len(files) - len(rebuild),
        "removed": len(prune),
        "total_chunks": 0,
    }

    for source_uri in rebuild:
        parsed = parse_document(paths[source_uri])
        raw_chunks = chunk_document(
            parsed.text,
            document_title=parsed.title,
            source_uri=source_uri,
            chunk_size=cfg.corpus.chunking.chunk_size,
            overlap=cfg.corpus.chunking.overlap,
        )
        # Embed before touching the stored row: if this call fails, the previous version
        # of the document is still indexed and every document committed so far stays.
        embeddings = await embed([c.text for c in raw_chunks], cfg.corpus.embedding.model)

        doc_id = _doc_id(cfg.client_id, source_uri)
        if source_uri in indexed:
            await _delete_documents(db, cfg.client_id, [source_uri])
            stats["replaced"] += 1
        else:
            stats["added"] += 1

        db.add(
            Document(
                id=doc_id,
                client_id=cfg.client_id,
                source_uri=source_uri,
                title=parsed.title,
                content_hash=files[source_uri],
                ingest_fingerprint=fingerprint,
                full_text=parsed.text,
            )
        )
        await db.flush()
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
        await db.commit()
        stats["total_chunks"] += len(raw_chunks)

    if prune:
        await _delete_documents(db, cfg.client_id, prune)
    await db.commit()
    return stats
