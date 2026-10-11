"""Results files: one Markdown table and one JSON per run, plus the misses CSV for hand tagging."""
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

RESULTS = Path(__file__).parents[1] / "results"
TAGS = ["wrong_join", "wrong_filter", "wrong_aggregate", "ambiguous_question", "gold_label_error", "other"]


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[max(0, math.ceil(p * len(xs)) - 1)] if xs else 0.0


def summarize(results: list[dict]) -> dict:
    n = len(results)
    mean = lambda k: sum(r[k] for r in results) / n if n else 0.0  # noqa: E731
    return {
        "n": n,
        "correct": sum(r["correct"] for r in results),
        "accuracy": sum(r["correct"] for r in results) / n if n else 0.0,
        "outcomes": dict(Counter(r.get("outcome", "-") for r in results)),
        "cost_usd": {"mean": mean("cost_usd"), "p95": pct([r["cost_usd"] for r in results], 0.95)},
        "latency_ms": {"mean": mean("latency_ms"), "p95": pct([r["latency_ms"] for r in results], 0.95)},
        "cache_read_tokens": sum(r["cache_read_tokens"] for r in results),
        "cache_write_tokens": sum(r["cache_write_tokens"] for r in results),
    }


def write(meta: dict, results: list[dict], extra_md: str = "") -> Path:
    RESULTS.mkdir(exist_ok=True)
    s = summarize(results)
    stem = "-".join(
        [meta["client"], meta["suite"], meta["model"].replace("/", "_"), meta["variant"]]  # OpenRouter ids have a slash
        + (["evidence"] if meta["evidence"] else []) + [meta["date"]]
    )
    (RESULTS / f"{stem}.json").write_text(json.dumps({"meta": meta, "summary": s, "cases": results}, indent=1))
    md = [
        f"# {meta['client']} {meta['suite']}, {meta['model']}, variant={meta['variant']}, evidence={meta['evidence']}",
        f"\ngit {meta['git_sha']}, {meta['date']}, {s['n']} cases\n",
        "| metric | value |", "|---|---|",
        f"| accuracy | {s['accuracy']:.1%} ({s['correct']}/{s['n']}) |",
        f"| outcomes | {s['outcomes']} |",
        f"| cost per question (mean / p95) | ${s['cost_usd']['mean']:.4f} / ${s['cost_usd']['p95']:.4f} |",
        f"| model latency per question, ms (mean / p95) | {s['latency_ms']['mean']:.0f} / {s['latency_ms']['p95']:.0f} |",
        f"| cache read / write tokens | {s['cache_read_tokens']} / {s['cache_write_tokens']} |",
        extra_md,
    ]
    (RESULTS / f"{stem}.md").write_text("\n".join(md) + "\n")
    misses = [r for r in results if not r["correct"]]
    if misses and meta["suite"] == "bird":  # hand-tag the tag column, then run `report.py`
        with open(RESULTS / f"{stem}-misses.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "difficulty", "outcome", "tag", "question"])
            w.writerows([r["id"], r["difficulty"], r["outcome"], "", r["question"]] for r in misses)
    return RESULTS / f"{stem}.md"


def tagged(json_path: str, csv_path: str) -> str:
    """Tag counts, and accuracy raw and excluding gold_label_error rows."""
    d = json.loads(Path(json_path).read_text())["summary"]
    tags = Counter(r["tag"] for r in csv.DictReader(open(csv_path)))
    bad = tags["gold_label_error"]
    adj = d["correct"] / (d["n"] - bad)
    return f"tags {dict(tags)}\nraw {d['correct']}/{d['n']} = {d['accuracy']:.1%}; excluding gold_label_error ({bad}): {adj:.1%}"


if __name__ == "__main__":  # python report.py <results.json> <misses.csv>
    print(tagged(*sys.argv[1:3]))
