"""The text-to-SQL engine (D13). The graph is #19; until then `build` is a placeholder that
answers "not built". What exists is the ingestion contract: the schema context (#18)."""
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.agent.platform import Deps, Engine, TurnState
from app.config.schema import ClientConfig
from app.sql import context

_REPO_ROOT = Path(__file__).parents[4]


async def _generate(state: TurnState, runtime):
    # ponytail: placeholder until #19 builds the real graph.
    text = "The text-to-SQL graph is not built yet."
    return {"outcome": "answer", "answer": text, "segments": [{"text": text, "citations": []}]}


def build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    g.add_node("generate", _generate)
    g.add_edge(START, "generate")
    g.add_edge("generate", END)
    return g


async def _ready(db, cfg: ClientConfig) -> str | None:
    return await context.ready(db, cfg, _REPO_ROOT)


ENGINE = Engine(
    "text_to_sql", build, "generate", lambda values: {}, context.check, context.ingest, _ready
)
