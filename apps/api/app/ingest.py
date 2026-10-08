"""Ingestion: reconcile a client's index with its corpus folder and `corpus` config.

The YAML is the spec, the `documents` table is the status. Each run:
  1. hashes every file's raw bytes (no parsing yet),
  2. plans: rebuild a file whose hash or ingest fingerprint differs from what is stored,
     prune an indexed document whose file is gone, skip the rest,
  3. rebuilds each planned file — embed → replace — and commits it alone,
  4. prunes, then commits.

`preflight()` runs first, in `--check` and in the real ingest alike: it parses and chunks
every file in the folder and accounts for each one, so the two cannot drift.
"""
import hashlib
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.database import AsyncSessionLocal, engine
from app.models import Chunk, Client, Document
from app.retrieval.chunker import Chunk as RawChunk
from app.retrieval.chunker import chunk_document, token_len
from app.retrieval.embed import _VOYAGE_BATCH_SIZE, embed
from app.retrieval.parsers import ParsedDocument, is_supported, iter_corpus, parse_document

logger = logging.getLogger("configent.ingest")

# Any fixed bigint: the key two API replicas contend on so only one reconciles at a time.
_RECONCILE_LOCK = 0x636F6E66


# Flags for a human to look at, not decisions: a file over or under these is still ingested.
_SCANNED_CHARS_PER_PAGE = 50
_STUB_TOKENS = 50
# USD per million embedding tokens, from Voyage's pricing page on 2026-10-08 (D8's rule: a
# dated constant, no pricing system). Voyage's free tier covers far more than a POC uses.
_EMBED_USD_PER_MTOK = {"voyage-3": 0.06, "voyage-3-large": 0.18, "voyage-3.5": 0.06}
# embed.py's first backoff on a rate limit; the free tier hits it once per batch.
_FREE_TIER_SECONDS_PER_BATCH = 21


@dataclass
class IngestReport:
    """What the corpus folder holds and what ingest will do with each file. Paths are
    relative to the folder; every file lands in exactly one of `ingest`, `unsupported`
    or `failed`."""

    files: list[str] = field(default_factory=list)  # every file in the folder
    ingest: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)  # by extension
    failed: list[dict] = field(default_factory=list)  # {path, reason}
    stubs: list[str] = field(default_factory=list)
    duplicates: list[list[str]] = field(default_factory=list)  # paths sharing one text
    chunks: int = 0
    tokens: int = 0  # what embedding will be billed for
    model: str = ""
    # What the real ingest builds from; kept so nothing is parsed or chunked twice.
    parsed: dict[str, ParsedDocument] = field(default_factory=dict, repr=False)
    raw_chunks: dict[str, list[RawChunk]] = field(default_factory=dict, repr=False)

    @property
    def extensions(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.files:
            ext = Path(f).suffix.lower() or "(none)"
            counts[ext] = counts.get(ext, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def cost_usd(self) -> float:
        return self.tokens / 1_000_000 * _EMBED_USD_PER_MTOK.get(self.model, 0.0)

    @property
    def seconds(self) -> int:
        # Worst case: every batch waits out a free-tier rate limit.
        return math.ceil(self.chunks / _VOYAGE_BATCH_SIZE) * _FREE_TIER_SECONDS_PER_BATCH


def _text_hash(text: str) -> str:
    # Whitespace-normalised, so the same words in two files compare equal.
    return _content_hash(" ".join(text.split()).encode())


def _document_url(parsed: ParsedDocument, rel: str, template: str) -> str | None:
    if parsed.url:
        return parsed.url
    if not template:
        return None
    path = Path(rel)
    return template.replace("{stem}", path.stem).replace("{path}", path.with_suffix("").as_posix())


def preflight(cfg: ClientConfig, repo_root: Path) -> IngestReport:
    """Parse and chunk every file in the corpus folder and say what ingest will do with it.
    Embeds nothing and writes nothing."""
    corpus_dir = repo_root / cfg.corpus.source
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    c = cfg.corpus
    report = IngestReport(model=c.embedding.model)
    by_text: dict[str, list[str]] = {}
    for path in iter_corpus(corpus_dir):
        rel = path.relative_to(corpus_dir).as_posix()
        report.files.append(rel)
        if not is_supported(path):
            report.unsupported.append(rel)
            continue
        try:
            parsed = parse_document(path)
            if parsed.pages and len(parsed.text.strip()) / parsed.pages < _SCANNED_CHARS_PER_PAGE:
                raise ValueError("scanned or image-only, needs OCR, not supported")
            chunks = chunk_document(
                parsed.text,
                document_title=parsed.title,
                source_uri=rel,
                chunk_size=c.chunking.chunk_size,
                overlap=c.chunking.overlap,
                prefix_title=c.chunking.prefix_title,
                markdown=parsed.markdown,
            )
        except Exception as e:  # a bad file must not stop the report
            report.failed.append({"path": rel, "reason": f"{type(e).__name__}: {e}"})
            continue
        parsed.url = _document_url(parsed, rel, c.source_url_template)
        report.ingest.append(rel)
        report.parsed[rel] = parsed
        report.raw_chunks[rel] = chunks
        tokens = sum(token_len(ch.text) for ch in chunks)
        report.chunks += len(chunks)
        report.tokens += tokens
        if token_len(parsed.text) < _STUB_TOKENS:
            report.stubs.append(rel)
        by_text.setdefault(_text_hash(parsed.text), []).append(rel)
    report.duplicates = [paths for paths in by_text.values() if len(paths) > 1]
    return report


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

    An empty corpus is refused rather than planned: a folder that mounted empty would
    otherwise prune the whole index.
    """
    if not files:
        raise ValueError("The corpus folder has no documents; refusing to prune the index.")
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
    """Reconcile one client's index with its corpus. Returns a summary dict, including the
    `preflight` report under "report"."""
    report = preflight(cfg, repo_root)
    corpus_dir = repo_root / cfg.corpus.source

    if await db.get(Client, cfg.client_id) is None:
        db.add(Client(id=cfg.client_id, name=cfg.name))
        await db.commit()

    fingerprint = cfg.corpus.fingerprint()
    # The full relative path, extension included: `iam.md` and `iam.pdf`, or
    # `a/setup.md` and `b/setup.md`, are different documents.
    # A file that failed preflight stays in `files`: leaving it out would prune the copy
    # already indexed just because the file broke.
    supported = report.ingest + [f["path"] for f in report.failed]
    files = {
        f"corpus://{cfg.client_id}/{rel}": _content_hash((corpus_dir / rel).read_bytes())
        for rel in supported
    }
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
        "failed": list(report.failed),
        "report": report,
    }

    prefix = f"corpus://{cfg.client_id}/"
    for source_uri in rebuild:
        rel = source_uri.removeprefix(prefix)
        if rel not in report.parsed:
            continue  # failed preflight; already in stats["failed"]
        parsed, raw_chunks = report.parsed[rel], report.raw_chunks[rel]
        try:
            # Embed before touching the stored row: if this call fails, the previous version
            # of the document is still indexed and every document committed so far stays.
            embeddings = await embed([c.text for c in raw_chunks], cfg.corpus.embedding.model)

            doc_id = _doc_id(cfg.client_id, source_uri)
            if source_uri in indexed:
                await _delete_documents(db, cfg.client_id, [source_uri])
            db.add(
                Document(
                    id=doc_id,
                    client_id=cfg.client_id,
                    source_uri=source_uri,
                    title=parsed.title,
                    url=parsed.url,
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
        except Exception as e:  # one file failing must not stop the rest
            await db.rollback()
            stats["failed"].append({"path": rel, "reason": f"{type(e).__name__}: {e}"})
            continue
        stats["replaced" if source_uri in indexed else "added"] += 1
        stats["total_chunks"] += len(raw_chunks)

    if prune:
        await _delete_documents(db, cfg.client_id, prune)
    await db.commit()
    return stats


async def reconcile_all(configs: list[ClientConfig], repo_root: Path) -> None:
    """Ingest every client at API startup, so a deploy with changed files or settings
    brings the index up to date without anyone running the CLI.

    Runs in the background: a full rebuild on Voyage's free tier takes minutes, and the
    chat endpoints' 409 guard covers the window. Unchanged files are skipped by hash, so
    an ordinary restart makes no embedding calls. One client failing does not stop the rest.
    """
    try:
        # The lock is held by this connection for the whole run. Sessions release their
        # connection on commit, so a session-level lock taken through one could be unlocked
        # on a different connection, or not at all.
        async with engine.connect() as lock_conn:
            if not await lock_conn.scalar(select(func.pg_try_advisory_lock(_RECONCILE_LOCK))):
                logger.info("Another replica is reconciling the index; skipping")
                return
            # A session-level lock outlives the transaction that took it, so end that one
            # instead of sitting idle in it for the whole run.
            await lock_conn.commit()
            try:
                for cfg in configs:
                    try:
                        async with AsyncSessionLocal() as db:
                            stats = await ingest_client(db, cfg, repo_root)
                        logger.info(
                            "Reconciled %s: %s",
                            cfg.client_id,
                            {k: v for k, v in stats.items() if k != "report"},
                        )
                    except Exception:
                        logger.exception("Reconcile failed for %s", cfg.client_id)
            finally:
                await lock_conn.scalar(select(func.pg_advisory_unlock(_RECONCILE_LOCK)))
    except Exception:
        # The database was unreachable, most likely. Chat's 409 guard still protects it.
        logger.exception("Startup reconcile aborted")
