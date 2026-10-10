"""The text-to-SQL template end to end with the model faked: the real guard, the real SQLite
(a small fixture database), the real graph, checkpointer and recorder."""
import sqlite3

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import platform
from app.agent.templates import database
from app.agent.templates.database import decide_sql
from app.config.registry import get_registry
from app.sql.guard import Verdict
from tests.graph_fakes import Harness, _response, named, outcome_of, stages_of, text_of

CLIENT = "f1-analyst"


@pytest.fixture
def h(monkeypatch, tmp_path):
    path = tmp_path / "f1.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE races (raceId INTEGER PRIMARY KEY, year INT, name TEXT);
        CREATE TABLE drivers (driverId INTEGER PRIMARY KEY, surname TEXT);
        CREATE TABLE results (resultId INTEGER PRIMARY KEY, raceId INT, driverId INT, position INT);
        INSERT INTO races VALUES (1, 2008, 'Monaco Grand Prix'), (2, 2008, 'Spanish Grand Prix');
        INSERT INTO drivers VALUES (1, 'Hamilton'), (2, 'Massa');
        INSERT INTO results VALUES (1, 1, 1, 1), (2, 1, 2, 2), (3, 2, 2, 1);
        """
    )
    conn.commit()
    conn.close()
    cfg = get_registry().get(CLIENT)
    cfg = cfg.model_copy(
        update={"agent": cfg.agent.model_copy(update={"database": cfg.agent.database.model_copy(update={"path": str(path)})})}
    )
    h = Harness(monkeypatch, cfg)
    platform.use_checkpointer(InMemorySaver(), [database.TEMPLATE])
    h.generate_calls: list[dict] = []
    h.executed: list[str] = []

    async def system(_d):
        return "schema"

    async def structured(_aclient, *, schema, user_content, **kw):
        h.calls.append(("generate" if "kind" in schema["properties"] else "repair" if "Your query failed" in user_content else "draft", user_content))
        h.generate_calls.append(kw)
        if "kind" in schema["properties"]:
            return dict(h.scenario["generate"]), _response()
        if "sql" in schema["properties"]:
            return dict(h.scenario["repair"]), _response()
        return dict(h.scenario.get("draft") or {"subject": "Add the 2024 season", "category": "missing_data"}), _response()

    real_run = database.run_query

    async def run(path, sql, **kw):
        h.executed.append(sql)
        return await real_run(path, sql, **kw)

    monkeypatch.setattr(database, "_system", system)
    monkeypatch.setattr(platform, "_structured_call", structured)
    monkeypatch.setattr(database, "run_query", run)
    return h


async def turn(h, message, **scenario):
    h.scenario = scenario
    return [
        e async for e in platform.stream_turn(
            message, template=database.TEMPLATE, cfg=h.cfg, client_id=CLIENT, conversation_id=None, db=h.db
        )
    ]


def q(sql):
    return {"kind": "question", "sql": sql, "reasoning": "r", "reply": ""}


async def test_a_simple_lookup_answers(h):
    events = await turn(h, "Who won Monaco 2008?", generate=q(
        "SELECT d.surname FROM results r JOIN drivers d USING (driverId) WHERE r.raceId = 1 AND r.position = 1"))
    assert outcome_of(events) == "answer"
    assert stages_of(events) == ["generate", "guard", "execute", "answer"]
    execute = [s for s in named(events, "step") if s["stage"] == "execute"][0]
    assert execute["rows"] == [["Hamilton"]] and execute["row_count"] == 1
    assert named(events, "done")[0]["row_count"] == 1
    assert h.generate_calls[0]["cache_system"] is True


async def test_an_aggregate_with_a_join_answers(h):
    events = await turn(h, "Wins per driver?", generate=q(
        "SELECT d.surname, count(*) AS wins FROM results r JOIN drivers d USING (driverId) "
        "WHERE r.position = 1 GROUP BY d.surname ORDER BY wins DESC"))
    assert outcome_of(events) == "answer"
    execute = [s for s in named(events, "step") if s["stage"] == "execute"][0]
    assert execute["columns"] == ["surname", "wins"] and execute["row_count"] == 2


async def test_a_failing_first_query_is_repaired(h):
    events = await turn(
        h, "Who won Monaco 2008?",
        generate=q("SELECT winner FROM races WHERE raceId = 1"),
        repair={"sql": "SELECT name FROM races WHERE raceId = 1", "reasoning": "no winner column"},
    )
    assert outcome_of(events) == "answer"
    assert stages_of(events) == ["generate", "guard", "repair", "guard", "execute", "answer"]
    repair = [s for s in named(events, "step") if s["stage"] == "repair"][0]
    assert "winner" in repair["error"] and repair["attempt"] == 1


async def test_a_greeting_converses_without_running_sql(h):
    events = await turn(h, "hi", generate={"kind": "conversation", "sql": "", "reasoning": "greeting", "reply": "Hello!"})
    assert outcome_of(events) == "converse" and text_of(events) == "Hello!"
    assert stages_of(events) == ["generate", "converse"]
    assert not h.executed and not h.ticket_calls


async def test_a_handoff_offers_a_ticket_and_files_once_on_confirm(h):
    events = await turn(h, "Can you add the 2024 season?", generate={"kind": "handoff", "sql": "", "reasoning": "newer data", "reply": ""})
    assert outcome_of(events) == "ticket" and stages_of(events) == ["generate", "escalate"]
    assert "data team" in text_of(events) and "platform team" not in text_of(events)
    assert not h.ticket_calls and not h.executed
    out = await h.confirm(client_id=CLIENT)
    assert out["ok"]
    await h.confirm(client_id=CLIENT)
    assert len(h.ticket_calls) == 1 and h.ticket_calls[0]["draft"]["queue"] == "data-team"


async def test_a_message_handoff_declines_with_no_model_call_after_generate(h):
    from app.config.schema import MessageHandoff

    h.cfg = h.cfg.model_copy(update={"handoff": MessageHandoff(mode="message", message="The data stops in 2017.")})
    events = await turn(h, "Can you add the 2024 season?", generate={"kind": "handoff", "sql": "", "reasoning": "newer data", "reply": ""})
    assert outcome_of(events) == "decline" and stages_of(events) == ["generate", "decline"]
    assert text_of(events) == "The data stops in 2017."
    assert [name for name, _ in h.calls] == ["generate"] and not h.ticket_calls


async def test_an_empty_sql_question_escalates_when_no_repairs_remain(h):
    h.cfg = h.cfg.model_copy(update={"agent": h.cfg.agent.model_copy(update={"repair_attempts": 0})})
    events = await turn(h, "?", generate=q(""))
    assert stages_of(events) == ["generate", "guard", "escalate"]
    assert outcome_of(events) == "ticket"


async def test_zero_rows_still_answers(h):
    events = await turn(h, "2024 winner?", generate=q("SELECT name FROM races WHERE year = 2024"))
    assert outcome_of(events) == "answer" and named(events, "done")[0]["row_count"] == 0


def test_the_answer_request_has_no_tools_and_rows_in_a_search_result(h):
    kw = database.answer_request_kwargs(
        h.cfg, client_id=CLIENT, sql="SELECT 1", reasoning="one", columns=["a"], rows=[[1]],
        truncated=False, question="q", history=[],
    )
    assert "tools" not in kw
    block = kw["messages"][-1]["content"][0]
    assert block["type"] == "search_result" and block["source"] == f"sql://{CLIENT}"
    assert block["content"][0]["text"].startswith("a\n1")


# ── decide_sql ───────────────────────────────────────────────────────────────────────

BAD = Verdict(False, "no such column: x")


def _cfg(h, n):
    return h.cfg.agent.model_copy(update={"repair_attempts": n})


def test_decide_sql(h):
    ok = Verdict(True)
    assert decide_sql(verdict=ok, error=None, attempts=0, cfg=_cfg(h, 0))[0] == "answer"
    assert decide_sql(verdict=BAD, error=None, attempts=0, cfg=_cfg(h, 1))[0] == "repair"
    assert decide_sql(verdict=ok, error="timed out", attempts=0, cfg=_cfg(h, 1))[0] == "repair"
    route, why = decide_sql(verdict=BAD, error=None, attempts=1, cfg=_cfg(h, 1))
    assert route == "escalate" and "no such column: x" in why
    assert decide_sql(verdict=BAD, error=None, attempts=0, cfg=_cfg(h, 0))[0] == "escalate"


async def test_a_missing_database_makes_ready_refuse_not_the_load_fail(h):
    cfg = get_registry().get(CLIENT)  # loaded fine although data/bird may be absent
    cfg = cfg.model_copy(update={"agent": cfg.agent.model_copy(update={"database": cfg.agent.database.model_copy(update={"path": "nope.sqlite"})})})
    assert "make data-bird" in await database.TEMPLATE.ready(None, cfg)
