"""The read-only SQLite connection (#18). The open mode is the real guard: the file cannot be
written through this connection whatever the SQL says. The guard's parser only exists to give
rejections a readable reason."""
import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# Everything not listed is denied. Deny-by-default also covers ATTACH, DETACH, PRAGMA and every
# write action, including ones a future SQLite adds. mode=ro does not stop ATTACH of another
# file on disk, which could then be read; this does.
_ALLOWED = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


class QueryError(Exception):
    """The database refused or failed the statement; the message is SQLite's own."""


class QueryTimeout(QueryError):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool
    elapsed_ms: int


def open_readonly(path: Path, *, timeout_ms: int | None = None) -> sqlite3.Connection:
    """Open `path` read-only. Call it in the thread that will use it (check_same_thread)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    # After query_only is set: the authorizer denies PRAGMA from here on.
    conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY)
    if timeout_ms is not None:
        # SQLite has no statement_timeout; a non-zero return aborts with "interrupted".
        deadline = time.monotonic() + timeout_ms / 1000
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    return conn


def _cell(v, cap: int):
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, str) and len(v) > cap:
        return v[:cap] + f"… [cut, {len(v)} chars]"
    return v


def _run(path: Path, sql: str, row_limit: int, timeout_ms: int, cell_chars: int) -> QueryResult:
    start = time.monotonic()
    conn = open_readonly(path, timeout_ms=timeout_ms)
    try:
        cur = conn.execute(sql)
        fetched = cur.fetchmany(row_limit + 1)  # one extra says "truncated" without reading on
        columns = [d[0] for d in cur.description or []]
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise QueryTimeout(f"query timed out after {timeout_ms} ms") from e
        raise QueryError(str(e)) from e
    except sqlite3.Error as e:
        raise QueryError(str(e)) from e
    finally:
        conn.close()
    return QueryResult(
        columns=columns,
        rows=[[_cell(v, cell_chars) for v in row] for row in fetched[:row_limit]],
        truncated=len(fetched) > row_limit,
        elapsed_ms=int((time.monotonic() - start) * 1000),
    )


async def run_query(
    path: Path, sql: str, *, row_limit: int = 200, timeout_ms: int = 5000, cell_chars: int = 500
) -> QueryResult:
    # Open, run and close all happen in the worker: a connection belongs to its creating thread.
    return await asyncio.to_thread(_run, path, sql, row_limit, timeout_ms, cell_chars)
