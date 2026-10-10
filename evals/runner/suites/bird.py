"""BIRD formula_1: execution accuracy (#20). Questions come from the gitignored data/bird/dev.json
and are never copied into the repo (CC BY-SA 4.0)."""
import json
from collections import Counter
from pathlib import Path

import sqlglot

from app.sql.connection import QueryError, run_query

ROOT = Path(__file__).parents[3]
DB = ROOT / "data/bird/formula_1.sqlite"
DEV = ROOT / "data/bird/dev.json"

# Scoring runs both queries with limits well above the product's 200 rows / 5 s, so a big
# gold result is compared whole instead of truncated.
_LIMITS = dict(row_limit=100_000, timeout_ms=30_000, cell_chars=10**9)


def cases(args) -> list[dict]:
    rows = [r for r in json.loads(DEV.read_text()) if r["db_id"] == "formula_1"]
    return [
        {
            "id": r["question_id"],
            "message": f"{r['question']}\n\nEvidence: {r['evidence']}" if args.evidence and r["evidence"] else r["question"],
            "question": r["question"],
            "gold": r["SQL"],
            "difficulty": r["difficulty"],
        }
        for r in rows
    ]


def has_order_by(sql: str) -> bool:
    """A top-level ORDER BY makes row order part of the answer. A subquery's does not."""
    try:
        return sqlglot.parse_one(sql, read="sqlite").args.get("order") is not None
    except sqlglot.errors.SqlglotError:
        return False


def _norm(v):
    # Floats rounded so 0.1+0.2 matches 0.3. None stays None: NULL and "" are different answers.
    return round(v, 4) if isinstance(v, float) else v


def same_result(gold: list[list], pred: list[list], ordered: bool) -> bool:
    g, p = [tuple(map(_norm, r)) for r in gold], [tuple(map(_norm, r)) for r in pred]
    # Multiset, not set: a duplicated row is a different answer.
    return g == p if ordered else Counter(g) == Counter(p)


async def _rows(sql: str) -> tuple[list[list] | None, str | None]:
    try:
        res = await run_query(DB, sql, **_LIMITS)
    except QueryError as e:  # includes QueryTimeout
        return None, f"{type(e).__name__}: {e}"
    return (None, "truncated") if res.truncated else (res.rows, None)


async def score(case: dict, state: dict) -> dict:
    """A turn that did not answer is a miss, tagged with what it did instead."""
    outcome = state.get("outcome") or "none"
    if outcome != "answer":
        return {"correct": False, "outcome": outcome}
    gold, gerr = await _rows(case["gold"])
    pred, perr = await _rows(state["sql"])
    if gerr or perr:
        return {"correct": False, "outcome": "answer", "error": f"gold: {gerr}" if gerr else f"pred: {perr}"}
    return {"correct": same_result(gold, pred, has_order_by(case["gold"])), "outcome": "answer", "sql": state["sql"]}


async def dry_run(cs: list[dict]) -> dict:
    """No model: run each gold query twice, compare the runs. Proves the harness executes,
    compares and counts; the findings are the golds that error, time out or truncate."""
    bad, ok = [], 0
    for c in cs:
        a, aerr = await _rows(c["gold"])
        b, _ = await _rows(c["gold"])
        if aerr:
            bad.append({"id": c["id"], "error": aerr})
        elif same_result(a, b, has_order_by(c["gold"])):
            ok += 1
    return {"slice": len(cs), "self_match": ok, "gold_failures": bad}
