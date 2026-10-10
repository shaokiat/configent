"""Eval runner (#20). Drives real turns through `run_turn` and scores them with a suite.

    cd apps/api && uv run python ../../evals/runner/run.py --client f1-analyst --suite bird --model claude-haiku-4-5-20251001
    ... --suite bird --dry-run     no model, no Postgres: gold SQL against itself

Real runs call the Anthropic API and cost money; they are run by hand and the results committed.
"""
import argparse
import asyncio
import importlib
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # suites/ and report.py sit beside this file

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

ROOT = Path(__file__).parents[2]


def parse(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--client", default="f1-analyst")
    p.add_argument("--suite", choices=["bird", "triage"], required=True)
    p.add_argument("--model", help="overrides the YAML for this run only")
    p.add_argument("--variant", choices=["schema", "naive"], default="schema")
    p.add_argument("--evidence", action="store_true", help="bird: append BIRD's evidence hint")
    p.add_argument("--limit", type=int, help="first N cases, for a cheap smoke run")
    p.add_argument("--dry-run", action="store_true", help="bird: gold vs gold, no model")
    return p.parse_args(argv)


async def one_turn(cfg, case, db):
    """One case through the real entry point; returns the final state and the turn's trace sums."""
    from sqlalchemy import func, select

    from app.agent import platform
    from app.agent.templates import TEMPLATES
    from app.models import Conversation, Message, Trace

    conv_id = None
    if case.get("history"):  # seed a conversation so the turn sees prior messages
        conv = Conversation(client_id=cfg.client_id)
        db.add(conv)
        await db.flush()
        db.add_all(Message(conversation_id=conv.id, role=m["role"], content=m["content"]) for m in case["history"])
        await db.commit()
        conv_id = conv.id
    state = await platform.run_turn(
        case["message"], template=TEMPLATES[cfg.agent.template], cfg=cfg,
        client_id=cfg.client_id, conversation_id=conv_id, db=db,
    )
    t = (
        await db.execute(
            select(
                func.coalesce(func.sum(Trace.cost_usd), 0), func.coalesce(func.sum(Trace.latency_ms), 0),
                func.coalesce(func.sum(Trace.cache_read_tokens), 0), func.coalesce(func.sum(Trace.cache_write_tokens), 0),
            ).where(Trace.conversation_id == state["conversation_id"])
        )
    ).one()
    return state, {"cost_usd": float(t[0]), "latency_ms": int(t[1]), "cache_read_tokens": int(t[2]), "cache_write_tokens": int(t[3])}


async def main(args) -> int:
    suite = importlib.import_module(f"suites.{args.suite}")
    cases = suite.cases(args)[: args.limit]
    if args.dry_run:
        out = await suite.dry_run(cases)  # bird only
        print(out)
        return 1 if out["gold_failures"] else 0

    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent import platform
    from app.agent.templates import TEMPLATES, database
    from app.config.registry import ConfigRegistry
    from app.database import AsyncSessionLocal
    from app.models import EvalRun

    cfg = ConfigRegistry(config_dir=ROOT / "config").get(args.client)
    if args.model:
        cfg = cfg.model_copy(update={"agent": cfg.agent.model_copy(update={"model": args.model})})
    if args.variant == "naive":
        async def no_schema(d):  # the same prompt with the schema section left out
            return f"{platform._prompt(d.cfg, 'generate')}\n\n## Database schema and notes\n\n(none)"
        database._system = no_schema
    platform.use_checkpointer(InMemorySaver(), TEMPLATES.values())  # evals need no durable pause

    results = []
    async with AsyncSessionLocal() as db:
        if args.variant == "schema" and (why := await TEMPLATES[cfg.agent.template].ready(db, cfg)):
            sys.exit(f"not ready: {why}")
        for i, case in enumerate(cases, 1):
            t0 = time.monotonic()
            state, usage = await one_turn(cfg, case, db)
            r = {"id": case["id"], **{k: case[k] for k in ("question", "difficulty") if k in case},
                 **await suite.score(case, state), **usage}
            results.append(r)
            print(f"{i}/{len(cases)} {case['id']} {'ok' if r['correct'] else 'miss'} {time.monotonic() - t0:.1f}s", flush=True)

        import report

        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        meta = {"client": args.client, "suite": args.suite, "model": cfg.agent.model, "variant": args.variant,
                "evidence": args.evidence, "git_sha": sha, "date": date.today().isoformat(), "slice": len(cases)}
        extra = ""
        if args.suite == "triage":
            m = suite.confusion(results)
            extra = "\n| expected \\ got | " + " | ".join(suite.KINDS) + " | none |\n|---|---|---|---|---|\n" + "\n".join(
                f"| {k} | " + " | ".join(str(m[k][c]) for c in [*suite.KINDS, "none"]) + " |" for k in suite.KINDS)
        print("wrote", report.write(meta, results, extra))
        db.add(EvalRun(client_id=args.client, git_sha=sha, scores={**meta, **report.summarize(results)}))
        await db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
