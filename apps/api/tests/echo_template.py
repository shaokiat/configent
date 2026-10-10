"""A second template that exists only to prove the seam (D13): it echoes the question, and on
"handoff" goes to the shared escalate -> ticket nodes. It lives in tests/ and is registered
by a fixture, so nothing in app/ knows about it."""
import time
from typing import Literal

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent.handoff import _after_ticket, decline, escalate, route, ticket
from app.agent.platform import Deps, Template, TurnState, _step
from app.ingest import IngestReport


class EchoAgent(BaseModel):
    template: Literal["echo"]
    model: str
    system_prompt_file: str


async def echo(state: TurnState, runtime):
    d, t = runtime.context, time.monotonic()
    await _step(d, "echo", t)
    if state["question"] == "handoff":
        return {"route": "escalate", "why": "the user asked for a human"}
    get_stream_writer()(("text", {"delta": state["question"]}))
    text = state["question"]
    return {"route": END, "outcome": "answer", "answer": text, "segments": [{"text": text, "citations": []}]}


def build() -> StateGraph:
    g = StateGraph(TurnState, context_schema=Deps)
    g.add_node("echo", echo)
    g.add_node("escalate", escalate)
    g.add_node("ticket", ticket)
    g.add_node("decline", decline)
    g.add_edge(START, "echo")
    g.add_conditional_edges("echo", route, ["escalate", "decline", END])
    g.add_edge("decline", END)
    g.add_edge("escalate", "ticket")
    g.add_conditional_edges("ticket", _after_ticket, ["ticket", END])
    return g


async def _ingest(db, cfg, repo_root, *, force=False) -> dict:
    return {}


async def _ready(db, cfg) -> None:
    return None


TEMPLATE = Template(
    "echo", build, "echo", lambda values: {}, lambda cfg, root: IngestReport(), _ingest, _ready
)
