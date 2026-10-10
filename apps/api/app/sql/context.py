"""The schema context (#18): the DDL introspected from the client's database, merged with the
column descriptions, glossary and rules the notes folder holds, rendered as one prompt block.
This template's ingestion contract lives here: check, ingest, ready."""
import asyncio
import csv
import hashlib
import io
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import ClientConfig
from app.ingest import _content_hash, _delete_documents, _doc_id
from app.models import Client, Document

logger = logging.getLogger("configent.sql")

_VALUE_CHARS = 120  # a long value_description would otherwise dominate the context


@dataclass
class Column:
    name: str
    type: str
    pk: bool
    notnull: bool
    description: str = ""


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[str]
    rows: int = 0


@dataclass
class SchemaReport:
    """What `check` found. Same job as IngestReport for the support graph."""

    tables: list[Table] = field(default_factory=list)
    undescribed: list[str] = field(default_factory=list)  # "table.column"
    context: str = ""
    tokens: int | None = None  # None: the count was unavailable
    failed: list[dict] = field(default_factory=list)  # never set; the CLI reads it

    def show(self, console: Console) -> None:
        for t in self.tables:
            console.print(f"{t.name}: {len(t.columns)} columns, {t.rows:,} rows")
        console.print(f"Undescribed columns ({len(self.undescribed)}):")
        for u in self.undescribed:
            console.print(f"  [yellow]{u}[/yellow]")
        tokens = f"{self.tokens:,}" if self.tokens is not None else "unavailable (best-effort)"
        console.print(f"Schema context: {len(self.context):,} chars, {tokens} tokens")


def _open(path: Path) -> sqlite3.Connection:
    # Our own introspection, not model SQL: read-only, but without the query authorizer, which
    # denies the PRAGMA table functions.
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _paths(cfg: ClientConfig, root: Path) -> tuple[Path, Path]:
    return root / cfg.agent.database.path, root / cfg.agent.context.source


def _notes(notes: Path) -> list[Path]:
    return sorted(notes.glob("descriptions/*.csv")) + [
        p for p in (notes / "glossary.md", notes / "rules.md") if p.exists()
    ]


def _descriptions(notes: Path) -> dict[tuple[str, str], str]:
    """(table, column) -> description, from BIRD's per-table CSVs (cp1252-ish, padded cells)."""
    out: dict[tuple[str, str], str] = {}
    for path in notes.glob("descriptions/*.csv"):
        text = path.read_bytes().decode("utf-8", errors="replace")
        for row in csv.DictReader(io.StringIO(text)):
            name = (row.get("original_column_name") or "").strip()
            clean = lambda v: " ".join(v.replace("\ufffd", "-").split())  # noqa: E731
            desc = clean(row.get("column_description") or "")
            if re.sub(r"\W", "", desc).lower() == re.sub(r"\W", "", name).lower():
                desc = ""  # "year" for year says nothing: the column still counts as undescribed
            value = clean(row.get("value_description") or "")
            if len(value) > _VALUE_CHARS:
                value = value[:_VALUE_CHARS] + "…"
            parts = [p for p in (desc, value) if p]
            if name and parts:
                out[(path.stem.lower(), name.lower())] = "; ".join(parts)
    return out


def introspect(db_path: Path, notes: Path, *, count_rows: bool = False) -> list[Table]:
    described = _descriptions(notes)
    conn = _open(db_path)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = []
        for n in names:
            cols = [
                Column(r[0], r[1] or "", bool(r[2]), bool(r[3]), described.get((n.lower(), r[0].lower()), ""))
                for r in conn.execute(
                    "SELECT name, type, pk, \"notnull\" FROM pragma_table_info(?)", (n,)
                )
            ]
            fks = [
                f"FOREIGN KEY ({r[0]}) REFERENCES {r[1]}({r[2]})"
                for r in conn.execute('SELECT "from", "table", "to" FROM pragma_foreign_key_list(?)', (n,))
            ]
            rows = conn.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] if count_rows else 0
            tables.append(Table(n, cols, fks, rows))
        return tables
    finally:
        conn.close()


def render(tables: list[Table], notes: Path) -> str:
    """Compact CREATE TABLEs with a comment per described column, then the notes."""
    blocks = []
    for t in tables:
        lines = []
        pks = [c.name for c in t.columns if c.pk]
        for c in t.columns:
            decl = f"  {c.name} {c.type}".rstrip() + (" PRIMARY KEY" if len(pks) == 1 and c.pk else "")
            lines.append((decl, c.description))
        if len(pks) > 1:
            lines.append((f"  PRIMARY KEY ({', '.join(pks)})", ""))
        lines += [(f"  {fk}", "") for fk in t.foreign_keys]
        body = []
        for i, (decl, desc) in enumerate(lines):
            comma = "," if i < len(lines) - 1 else ""
            body.append(f"{decl}{comma}" + (f" -- {desc}" if desc else ""))
        blocks.append(f"CREATE TABLE {t.name} (\n" + "\n".join(body) + "\n);")
    out = "\n\n".join(blocks)
    for title, fname in (("Glossary", "glossary.md"), ("Rules", "rules.md")):
        f = notes / fname
        if f.exists():
            out += f"\n\n## {title}\n\n{f.read_text().strip()}"
    return out


def fingerprint(cfg: ClientConfig, root: Path) -> str:
    """SHA-256 (16 hex chars, the column's width) of the normalised DDL and every notes file."""
    db_path, notes = _paths(cfg, root)
    conn = _open(db_path)
    try:
        ddl = [
            re.sub(r"\s+", " ", r[0]).strip()
            for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
            )
        ]
    finally:
        conn.close()
    h = hashlib.sha256("\n".join(ddl).encode())
    for p in _notes(notes):
        h.update(p.relative_to(notes).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


def _count_tokens(model: str, text: str) -> int | None:
    """Claude's own tokenizer via the API. Best-effort: no key, no network, or a gateway without
    the endpoint (OpenRouter has none, D14) gives None."""
    try:
        from app import llm

        r = llm.client().messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]
        )
        return r.input_tokens
    except Exception as e:
        logger.warning("token count unavailable: %s", e)
        return None


def check(cfg: ClientConfig, root: Path) -> SchemaReport:
    db_path, notes = _paths(cfg, root)
    tables = introspect(db_path, notes, count_rows=True)
    context = render(tables, notes)
    return SchemaReport(
        tables=tables,
        undescribed=[f"{t.name}.{c.name}" for t in tables for c in t.columns if not c.description],
        context=context,
        tokens=_count_tokens(cfg.agent.model, context),
    )


def _uri(cfg: ClientConfig) -> str:
    return f"schema://{cfg.client_id}"


async def ingest(db: AsyncSession, cfg: ClientConfig, root: Path, *, force: bool = False) -> dict:
    """Store the rendered context as one documents row, no chunks. Skipped when the stored
    fingerprint already matches."""
    fp = await asyncio.to_thread(fingerprint, cfg, root)
    if await db.get(Client, cfg.client_id) is None:
        db.add(Client(id=cfg.client_id, name=cfg.name))
        await db.commit()
    stored = (
        await db.execute(select(Document.ingest_fingerprint).where(Document.source_uri == _uri(cfg)))
    ).scalar()
    if stored == fp and not force:
        return {"skipped": 1, "report": None, "failed": []}

    db_path, notes = _paths(cfg, root)
    tables = await asyncio.to_thread(introspect, db_path, notes)
    context = render(tables, notes)
    tokens = await asyncio.to_thread(_count_tokens, cfg.agent.model, context)
    await _delete_documents(db, cfg.client_id, [_uri(cfg)])
    db.add(
        Document(
            id=_doc_id(cfg.client_id, _uri(cfg)),
            client_id=cfg.client_id,
            source_uri=_uri(cfg),
            title=f"Schema context: {cfg.client_id}",
            content_hash=_content_hash(context.encode()),
            ingest_fingerprint=fp,
            full_text=context,
        )
    )
    await db.commit()
    return {
        "added": 1,
        "tables": len(tables),
        "chars": len(context),
        "tokens": tokens,
        "report": SchemaReport(tables=tables, context=context, tokens=tokens),
        "failed": [],
    }


async def ready(db: AsyncSession, cfg: ClientConfig, root: Path) -> str | None:
    """Why the stored context cannot serve the database and notes as they are now, or None."""
    stored = (
        await db.execute(
            select(Document.ingest_fingerprint).where(
                Document.client_id == cfg.client_id, Document.source_uri == _uri(cfg)
            )
        )
    ).scalar()
    if stored is None:
        return f"No schema context is ingested for {cfg.client_id!r}."
    try:
        current = await asyncio.to_thread(fingerprint, cfg, root)
    except Exception as e:  # missing or unreadable database file
        return f"The database for {cfg.client_id!r} cannot be read ({e})."
    if current != stored:
        return "The schema or notes changed since the last ingest."
    return None
