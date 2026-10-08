"""The seam holds: a second engine runs a full turn and a propose-and-confirm ticket round
trip through the platform's own entry points, with no platform or escalation edits (D13)."""
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import platform
from app.agent.engines import ENGINES
from app.config.registry import get_registry
from tests import echo_engine
from tests.graph_fakes import CLIENT, Harness, named, outcome_of, stages_of, text_of


@pytest.fixture
def h(monkeypatch):
    gcp = get_registry().get(CLIENT)
    h = Harness(monkeypatch, gcp)
    monkeypatch.setitem(ENGINES, "echo", echo_engine.ENGINE)
    platform.use_checkpointer(InMemorySaver(), ENGINES.values())
    # model_copy does not validate: the config union is closed, and the echo agent is not in it.
    h.cfg = gcp.model_copy(
        update={
            "agent": echo_engine.EchoAgent(
                engine="echo", model=gcp.agent.model, system_prompt_file=gcp.agent.system_prompt_file
            ),
            "corpus": None,
        }
    )
    return h


async def _turn(h: Harness, message: str) -> list:
    h.scenario = {"draft": {"subject": "Hand off", "category": "other"}}
    return [
        e
        async for e in platform.stream_turn(
            message, engine=ENGINES["echo"], cfg=h.cfg, client_id=CLIENT, conversation_id=None, db=h.db
        )
    ]


@pytest.mark.asyncio
async def test_a_full_turn_on_another_engine(h):
    events = await _turn(h, "hello")
    assert stages_of(events) == ["echo"]
    assert text_of(events) == "hello" and outcome_of(events) == "answer"
    assert h.runs["run-1"].engine == "echo" and h.runs["run-1"].status == "completed"


@pytest.mark.asyncio
async def test_propose_and_confirm_on_another_engine(h):
    events = await _turn(h, "handoff")
    assert outcome_of(events) == "ticket" and stages_of(events) == ["echo", "escalate"]
    assert named(events, "ticket_proposal")[0]["subject"] == "Hand off"
    assert not h.ticket_calls  # an offer files nothing

    out = await platform.confirm_ticket(run_id="run-1", client_id=CLIENT, cfg=h.cfg, db=h.db)
    assert out["ok"] and out["ticket_id"] == "PLATFORM-1001"
    assert [c["draft"]["subject"] for c in h.ticket_calls] == ["Hand off"]
