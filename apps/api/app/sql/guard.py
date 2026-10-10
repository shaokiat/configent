"""The SQL guard (#18). It exists for explainable rejections: a reason the model can read is
what makes the repair step work. The connection mode is the real guard; if the parser and the
connection ever disagree, the connection wins."""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.sql.connection import open_readonly

_WRITES = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter,
    exp.Attach, exp.Detach, exp.Pragma, exp.Command, exp.Merge,
)  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None  # human-readable; feeds the step trail and the repair prompt


def _no(reason: str) -> Verdict:
    return Verdict(False, reason)


def check(sql: str, *, dialect: str = "sqlite", path: Path | None = None) -> Verdict:
    """Parse, then (when `path` is given) EXPLAIN on a read-only connection. Synchronous and
    cheap: callers in async code run it in a thread."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError as e:
        return _no(f"could not parse the SQL: {str(e).splitlines()[0]}")
    if not statements:
        return _no("empty statement")
    if len(statements) > 1:
        return _no(f"only one statement is allowed; found {len(statements)} separated by ';'")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        return _no(f"only one SELECT is allowed; found {_name(tree)}")
    for node in tree.walk():
        if isinstance(node, _WRITES):
            where = "a CTE" if node.find_ancestor(exp.CTE) else "the query"
            return _no(f"write inside {where}: {_name(node)}")
    if path is None:
        return Verdict(True)
    conn = open_readonly(path)
    try:
        conn.execute(f"EXPLAIN {sql}")  # unknown tables and columns fail here, before execution
    except sqlite3.Error as e:
        return _no(str(e))
    finally:
        conn.close()
    return Verdict(True)


def _name(node: exp.Expression) -> str:
    # A Command (VACUUM, EXPLAIN, ...) carries its keyword; other nodes are named by class.
    return str(node.this).upper() if isinstance(node, exp.Command) else type(node).__name__.upper()
