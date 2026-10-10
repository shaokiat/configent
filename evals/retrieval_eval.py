"""Retrieval eval (#15): recall@k and MRR of retrieve() against the golden set.

    cd apps/api && uv run python ../../evals/retrieval_eval.py --client gcp-platform-support

No judge model and no generation: the only network call is one Voyage query embedding per
question. Needs an ingested index. Variants override RetrievalConfig in code, not the YAML.
"""
import argparse
import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def recall_at_k(expected: list[str], ranked: list[str], k: int) -> float:
    """Fraction of expected documents among the first k *distinct* documents of `ranked`
    (chunks of one document count once)."""
    top = list(dict.fromkeys(ranked))[:k]
    return sum(e in top for e in expected) / len(expected)


def reciprocal_rank(expected: list[str], ranked: list[str]) -> float:
    """1 / rank of the first expected document, ranks counted over distinct documents; 0 if absent."""
    for rank, doc in enumerate(dict.fromkeys(ranked), start=1):
        if doc in expected:
            return 1 / rank
    return 0.0


def _stem(source_uri: str) -> str:
    return source_uri.rsplit("/", 1)[-1].removesuffix(".md")


def _keywords(question: str) -> str:
    # No model call: the longer words, OR-ed. websearch_to_tsquery ANDs bare words, and a whole
    # question never matches that way.
    return " or ".join(w for w in question.lower().replace("?", " ").split() if len(w) > 4)


async def main(client_id: str) -> None:
    load_dotenv(ROOT / ".env")
    from app.config.registry import get_registry
    from app.database import AsyncSessionLocal
    from app.retrieval import search
    from app.retrieval.embed import embed_queries

    cfg = get_registry().get(client_id)
    model, floor = cfg.corpus.embedding.model, cfg.agent.retrieval_drop_floor
    rows = [
        r
        for r in map(json.loads, (ROOT / cfg.evals.golden_set).read_text().splitlines())
        if r["expected_citations"]
    ]

    # One batched embedding call; every variant then reuses the vectors (free-tier Voyage is 3 RPM).
    vecs = dict(zip((r["question"] for r in rows), await embed_queries([r["question"] for r in rows], model)))

    async def cached(queries: list[str], _model: str) -> list[list[float]]:
        return [vecs[q] for q in queries]

    search.embed_queries = cached

    variants = [  # (label, keyword.enabled, top_k)
        ("Level 1, dense only", False, 5),
        ("Level 1, dense only", False, 10),
        ("Level 2, dense + keyword", True, 5),
        ("Level 2, dense + keyword", True, 10),
    ]
    out = []
    async with AsyncSessionLocal() as db:
        for label, kw, k in variants:
            rcfg = cfg.retrieval.model_copy(deep=True, update={"top_k": k})
            rcfg.keyword.enabled = kw
            recalls, rrs, misses = [], [], []
            for r in rows:
                hits = await search.retrieve(
                    db, client_id, [r["question"]], _keywords(r["question"]) if kw else "",
                    cfg=rcfg, model=model, floor=floor,
                )
                ranked = [_stem(h.source_uri) for h in hits]
                recalls.append(recall_at_k(r["expected_citations"], ranked, k))
                rrs.append(reciprocal_rank(r["expected_citations"], ranked))
                if recalls[-1] < 1:
                    misses.append(r["id"])
            out.append((label, rcfg, sum(recalls) / len(rows), sum(rrs) / len(rows), misses))

    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    lines = [
        f"# Retrieval eval, {client_id}, {date.today()}",
        "",
        f"Git SHA `{sha}`. n = {len(rows)} questions with expected citations "
        f"(golden set rows with none are skipped). One question moves a metric by {100 / len(rows):.1f} points.",
        "",
        "| Variant | top_k | keyword | rrf_k | floor | recall@k | MRR | Missed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, c, rec, mrr, misses in out:
        lines.append(
            f"| {label} | {c.top_k} | {'on' if c.keyword.enabled else 'off'} | {c.rrf_k} | {floor} "
            f"| {rec:.3f} | {mrr:.3f} | {', '.join(misses) or '-'} |"
        )
    text = "\n".join(lines) + "\n"
    print(text)
    path = ROOT / "evals/results" / f"retrieval-{date.today()}.md"
    path.write_text(text)
    print(f"wrote {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    asyncio.run(main(ap.parse_args().client))
