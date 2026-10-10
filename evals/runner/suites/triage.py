"""Triage: does the first call pick question / conversation / handoff. The set is committed
before the runner (D7); see evals/<client>/triage.jsonl."""
import json
from collections import Counter

from suites.bird import ROOT

KINDS = ["question", "conversation", "handoff"]


def cases(args) -> list[dict]:
    path = ROOT / "evals" / args.client / "triage.jsonl"
    return [
        {**r, "message": r["message"], "history": r.get("history", [])}
        for r in map(json.loads, path.read_text().splitlines())
    ]


async def score(case: dict, state: dict) -> dict:
    got = state.get("kind") or "none"
    return {"correct": got == case["expected"], "got": got, "expected": case["expected"]}


def confusion(results: list[dict]) -> dict[str, Counter]:
    """Rows are the expected kind, columns what the model chose."""
    m = {k: Counter() for k in KINDS}
    for r in results:
        m[r["expected"]][r["got"]] += 1
    return m
