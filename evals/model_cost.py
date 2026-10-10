"""Cost and citations per model setup, on the demo questions, against a running API.

    cd apps/api && uv run python ../../evals/model_cost.py --label "haiku answers" --runs 2

Each turn records its route, citations (and invalid markers), whether the answer holds the
expected fact, and the app's cost estimate (D8). OpenRouter's own spend for the whole run is
read from the key before and after, so the estimate can be checked against the bill.
"""
import argparse
import json
import os
import time
import urllib.request

# (client, question, expected outcome, a fact the answer must contain, or None)
TURNS = [
    ("gcp-platform-support", "My Cloud Run container fails to start — what does the PORT error mean?", "answer", "PORT"),
    ("gcp-platform-support", "What's the default CPU limit for a Cloud Run instance?", "answer", "1 vCPU"),
    ("gcp-platform-support", "Why won't my GKE node pool scale down after I deleted the workload?", "answer", "PodDisruptionBudget"),
    ("gcp-platform-support", "hey", "converse", None),
    ("gcp-platform-support", "Can you raise my Cloud Run instance quota for europe-west1? It's blocking a deploy.", "ticket", None),
    ("f1-analyst", "Who won the 2008 Monaco Grand Prix?", "answer", "Hamilton"),
    ("f1-analyst", "Which constructor scored the most points in 2010?", "answer", "Red Bull"),
    ("f1-analyst", "hi", "converse", None),
    ("f1-analyst", "Can you add the 2024 season?", "ticket", None),
]


def turn(api: str, client: str, message: str) -> dict:
    req = urllib.request.Request(
        f"{api}/api/c/{client}/chat/stream",
        data=json.dumps({"message": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    out, event = {"text": "", "citations": 0, "stages": []}, None
    for raw in urllib.request.urlopen(req, timeout=180):
        line = raw.decode().rstrip("\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:])
            if event == "text":
                out["text"] += data["delta"]
            elif event == "citation":
                out["citations"] += 1
            elif event == "step":
                out["stages"].append(data["stage"])
                if data["stage"] == "answer":
                    out["bad"] = data.get("bad_citations", 0)
            elif event in ("done", "error"):
                out[event] = data
    return out


def spend() -> float:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
    )
    return json.load(urllib.request.urlopen(req))["data"]["usage"]


def settled_spend(before: float, wait: int = 90) -> float:
    """OpenRouter updates the key's usage a little after each call: wait until it stops moving."""
    last, stable = spend(), 0
    for _ in range(wait // 5):
        time.sleep(5)
        now = spend()
        stable = stable + 1 if now == last and now != before else 0
        if stable >= 2:
            return now
        last = now
    return last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    before, rows = spend(), []
    for run in range(args.runs):
        for client, message, want, fact in TURNS:
            o = turn(args.api, client, message)
            done = o.get("done") or {}
            rows.append({
                "run": run, "client": client, "message": message,
                "outcome": done.get("outcome", "error"), "expected": want,
                "fact_ok": None if fact is None else fact.lower() in o["text"].lower(),
                "citations": o["citations"], "bad_citations": o.get("bad", 0),
                "app_cost_usd": done.get("cost_usd", 0.0), "stages": o["stages"],
            })
            print(json.dumps(rows[-1]), flush=True)
    billed = settled_spend(before) - before
    estimated = sum(r["app_cost_usd"] for r in rows)
    answers = [r for r in rows if r["expected"] == "answer"]
    print(json.dumps({
        "label": args.label, "turns": len(rows),
        "routed_as_expected": sum(r["outcome"] == r["expected"] for r in rows),
        "facts_ok": f"{sum(bool(r['fact_ok']) for r in answers)}/{len(answers)}",
        "citations_per_answer": round(sum(r["citations"] for r in answers) / len(answers), 1),
        "bad_citations": sum(r["bad_citations"] for r in rows),
        "estimated_usd": round(estimated, 4), "billed_usd": round(billed, 4),
    }))


if __name__ == "__main__":
    main()
