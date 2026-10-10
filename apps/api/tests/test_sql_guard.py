"""The guard and the read-only connection (#18), against a small SQLite file built here:
CI has no BIRD."""
import sqlite3

import pytest

from app.sql import connection, guard
from app.sql.connection import QueryError, QueryTimeout, run_query


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT)")
    conn.executemany("INSERT INTO t (note) VALUES (?)", [("x" * 1000,)] + [("n",)] * 299)
    conn.commit()
    conn.close()
    return path


CASES = [
    ("INSERT INTO t VALUES (1, 'a')", "only one SELECT is allowed; found INSERT"),
    ("DROP TABLE t", "only one SELECT is allowed; found DROP"),
    ("ATTACH DATABASE 'x.db' AS x", "only one SELECT is allowed; found ATTACH"),
    ("PRAGMA table_info(t)", "only one SELECT is allowed; found PRAGMA"),
    ("VACUUM", "only one SELECT is allowed; found VACUUM"),
    ("SELECT 1; SELECT 2", "only one statement is allowed; found 2"),
    ("SELECT 1; DROP TABLE t", "only one statement is allowed; found 2"),
    ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "write inside a CTE: DELETE"),
    ("SELECT nope FROM t", "no such column: nope"),
    ("SELECT * FROM missing", "no such table: missing"),
]


@pytest.mark.parametrize(("sql", "reason"), CASES)
def test_the_guard_rejects_with_a_readable_reason(db, sql, reason):
    v = guard.check(sql, path=db)
    assert not v.ok and reason in v.reason


def test_the_guard_accepts_selects_and_ctes(db):
    for sql in ("SELECT id FROM t", "WITH x AS (SELECT id FROM t) SELECT * FROM x",
                "SELECT 1 UNION SELECT 2"):  # fmt: skip
        assert guard.check(sql, path=db).ok


@pytest.mark.parametrize("sql", ["ATTACH DATABASE ':memory:' AS x", "PRAGMA query_only=OFF",
                                 "INSERT INTO t (note) VALUES ('a')", "DELETE FROM t",
                                 "DROP TABLE t", "CREATE TABLE u (a)"])  # fmt: skip
async def test_the_connection_refuses_writes_with_the_guard_skipped(db, sql):
    with pytest.raises(QueryError):
        await run_query(db, sql)
    n = sqlite3.connect(db).execute("SELECT count(*) FROM t").fetchone()[0]
    assert n == 300


async def test_a_plain_select_returns_rows_and_caps_cells(db):
    r = await run_query(db, "SELECT id, note FROM t ORDER BY id LIMIT 3", cell_chars=50)
    assert r.columns == ["id", "note"] and len(r.rows) == 3 and not r.truncated
    assert r.rows[0][1].startswith("x" * 50 + "…") and len(r.rows[0][1]) < 100


async def test_more_than_row_limit_rows_come_back_truncated(db):
    r = await run_query(db, "SELECT id FROM t", row_limit=10)
    assert len(r.rows) == 10 and r.truncated
    assert not (await run_query(db, "SELECT id FROM t", row_limit=300)).truncated


async def test_a_runaway_query_is_stopped_by_the_timeout(db):
    with pytest.raises(QueryTimeout, match="timed out"):
        await run_query(db, "SELECT count(*) FROM t a, t b, t c, t d", timeout_ms=100)


def test_the_file_itself_is_opened_read_only(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO t (note) VALUES ('a')")
    assert connection.open_readonly(db).execute("SELECT 1").fetchone() == (1,)
