"""Schema-context ingest (#18): fingerprint, ready and check, on a fixture database."""
import os
import sqlite3
from types import SimpleNamespace

import pytest

from app.config.schema import ClientConfig
from app.sql import context


@pytest.fixture(autouse=True)
def no_token_api(monkeypatch):
    monkeypatch.setattr(context, "_count_tokens", lambda model, text: 123)


@pytest.fixture
def cfg():
    return ClientConfig.model_validate(
        {
            "client_id": "sql-test",
            "name": "SQL test",
            "branding": {"logo": "x", "primary_color": "#000", "assistant_name": "A"},
            "handoff": {"message": "Ask the data team."},
            "agent": {
                "template": "database",
                "model": "claude-sonnet-4-6",
                "system_prompt_file": "p.md",
                "database": {"dialect": "sqlite", "path": "d.sqlite"},
                "context": {"source": "notes/"},
            },
        }
    )


@pytest.fixture
def root(tmp_path):
    conn = sqlite3.connect(tmp_path / "d.sqlite")
    conn.execute("CREATE TABLE races (raceId INTEGER PRIMARY KEY, year INTEGER, name TEXT)")
    conn.execute("INSERT INTO races (year, name) VALUES (2017, 'Monaco')")
    conn.commit()
    conn.close()
    (tmp_path / "notes" / "descriptions").mkdir(parents=True)
    (tmp_path / "notes" / "descriptions" / "races.csv").write_text(
        "original_column_name,column_name,column_description,data_format,value_description\n"
        "raceId ,,the id of the race ,integer,\n"
        "year ,,year ,integer,\n"  # echoes its name: still undescribed
    )
    (tmp_path / "notes" / "glossary.md").write_text("pole = grid 1")
    (tmp_path / "notes" / "rules.md").write_text("data ends in 2017")
    return tmp_path


def test_the_fingerprint_changes_with_notes_or_ddl_and_not_otherwise(cfg, root):
    fp = context.fingerprint(cfg, root)
    assert len(fp) == 16 and context.fingerprint(cfg, root) == fp

    sqlite3.connect(root / "d.sqlite").execute("INSERT INTO races (year) VALUES (2018)").connection.commit()
    assert context.fingerprint(cfg, root) == fp  # rows are not schema

    (root / "notes" / "rules.md").write_text("data ends in 2018")
    changed_notes = context.fingerprint(cfg, root)
    assert changed_notes != fp

    conn = sqlite3.connect(root / "d.sqlite")
    conn.execute("ALTER TABLE races ADD COLUMN round INTEGER")
    conn.commit()
    assert context.fingerprint(cfg, root) not in (fp, changed_notes)


class _Stored:
    """Just enough session for `ready`: the one stored fingerprint."""

    def __init__(self, fp):
        self.fp = fp

    async def execute(self, _stmt):
        return SimpleNamespace(scalar=lambda: self.fp)


async def test_ready_refuses_when_nothing_is_stored_or_anything_changed(cfg, root):
    assert "No schema context" in await context.ready(_Stored(None), cfg, root)
    stored = _Stored(context.fingerprint(cfg, root))
    assert await context.ready(stored, cfg, root) is None
    (root / "notes" / "glossary.md").write_text("pole = grid 1 or the fastest qualifier")
    assert "changed since the last ingest" in await context.ready(stored, cfg, root)
    stored = _Stored(context.fingerprint(cfg, root))
    conn = sqlite3.connect(root / "d.sqlite")
    conn.execute("ALTER TABLE races ADD COLUMN round INTEGER")
    conn.commit()
    assert "changed since the last ingest" in await context.ready(stored, cfg, root)


def test_check_lists_tables_undescribed_columns_and_tokens(cfg, root):
    r = context.check(cfg, root)
    assert [(t.name, t.rows) for t in r.tables] == [("races", 1)]
    assert r.undescribed == ["races.year", "races.name"]
    assert r.tokens == 123
    assert "raceId INTEGER PRIMARY KEY, -- the id of the race" in r.context
    assert "## Glossary" in r.context and "data ends in 2017" in r.context


@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1")
async def test_ingest_stores_one_row_and_ready_follows_it(cfg, root):
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import DATABASE_URL
    from app.models import Client, Document

    Session = async_sessionmaker(
        create_async_engine(DATABASE_URL, poolclass=NullPool), expire_on_commit=False
    )
    try:
        async with Session() as db:
            assert "No schema context" in await context.ready(db, cfg, root)
            stats = await context.ingest(db, cfg, root)
            assert stats["added"] == 1 and stats["tokens"] == 123
            doc = await db.get(Document, context._doc_id(cfg.client_id, "schema://sql-test"))
            assert doc.full_text.startswith("CREATE TABLE races") and doc.ingest_fingerprint
            assert await context.ready(db, cfg, root) is None
            assert (await context.ingest(db, cfg, root))["skipped"] == 1

            (root / "notes" / "rules.md").write_text("changed")
            assert "changed since" in await context.ready(db, cfg, root)
            assert (await context.ingest(db, cfg, root))["added"] == 1
            assert await context.ready(db, cfg, root) is None
    finally:
        async with Session() as db:
            await db.execute(delete(Document).where(Document.client_id == cfg.client_id))
            await db.execute(delete(Client).where(Client.id == cfg.client_id))
            await db.commit()
