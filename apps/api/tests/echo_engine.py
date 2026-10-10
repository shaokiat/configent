"""A second engine that exists only to prove the seam (D13): it echoes the question, and on
"handoff" goes to the shared escalate -> ticket nodes. It lives in tests/ and is registered
by a fixture, so nothing in app/ knows about it."""
import time
from typing import Literal

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent.escalation import _after_ticket, escalate, ticket
from app.agent.platform import Deps, Engine, TurnState, _step
from app.ingest import IngestReport


class EchoAgent(BaseModel):
    engine: Literal["echo"]
    model: str
    system_prompt_file: str


async def echo(state: TurnState, runtime):
    d, t = runtime.context, time.monotonic()
    await _step(d, "echo", t)
    if state["question"] == "handoff":
        return {"why": "the user asked for a human"}
    get_stream_writer()(("text", {"delta": state["question"]}))
    text = state["question"]
    return {"outcome": "answer", "answer": text, "segments": [{"text": text, "citations": []}]}


def _after_echo(state) -> str:
    return "escalate" if state.get("why") else END


def build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    g.add_node("echo", echo)
    g.add_node("escalate", escalate)
    g.add_node("ticket", ticket)
    g.add_edge(START, "echo")
    g.add_conditional_edges("echo", _after_echo, ["escalate", END])
    g.add_edge("escalate", "ticket")
    g.add_conditional_edges("ticket", _after_ticket, ["ticket", END])
    return g


async def _ingest(db, cfg, repo_root, *, force=False) -> dict:
    return {}


async def _ready(db, cfg) -> None:
    return None


ENGINE = Engine(
    "echo", build, "echo", lambda values: {}, lambda cfg, root: IngestReport(), _ingest, _ready
)
