"""The support graph: the two decisions and the three tiers, end to end.

The gate that matters most is still that the answering model receives no tool definitions
at all (D2). The one this engine adds is that a greeting leaves at Level 1 — if it reached
Level 2, "hi" would buy a rewrite, a hybrid search and a ticket offer (D9, D10).
"""
import time

import pytest

from app.agent import graph
from app.config.registry import get_registry
from tests.graph_fakes import Harness, grade, hit, named, outcome_of, stages_of, text_of


@pytest.fixture
def cfg():
    return get_registry().get("gcp-platform-support")


@pytest.fixture
def h(monkeypatch, cfg):
    return Harness(monkeypatch, cfg)


# ── Level 1 decision (D2) ───────────────────────────────────────────────────────────


def test_answers_only_when_both_signals_clear(cfg):
    route, why = graph.decide_level1(top_similarity=0.8, score=grade(0.9), n_hits=3, cfg=cfg)
    assert route == "answer"
    assert "both above threshold" in why


def test_weak_retrieval_is_not_rescued_by_a_confident_model(cfg):
    route, why = graph.decide_level1(top_similarity=0.31, score=grade(0.99), n_hits=3, cfg=cfg)
    assert route == "rewrite"
    assert "escalate_below" in why


def test_weak_groundedness_is_not_rescued_by_a_strong_match(cfg):
    """The 'retrieved the right document, which doesn't contain the answer' case."""
    route, why = graph.decide_level1(top_similarity=0.88, score=grade(0.2), n_hits=3, cfg=cfg)
    assert route == "rewrite"
    assert "confidence_threshold" in why


def test_no_passages_goes_to_level_two(cfg):
    route, why = graph.decide_level1(top_similarity=0.0, score=grade(0.0), n_hits=0, cfg=cfg)
    assert route == "rewrite"
    assert "no passages" in why


def test_a_conversation_leaves_at_level_one(cfg):
    route, _ = graph.decide_level1(
        top_similarity=0.0, score=grade(0.0, kind="conversation"), n_hits=0, cfg=cfg
    )
    assert route == "converse"


def test_strong_evidence_answers_even_if_the_grader_called_it_conversation(cfg):
    """Phrasing is not intent: a casual question the docs answer is still answered."""
    route, _ = graph.decide_level1(
        top_similarity=0.8, score=grade(0.9, kind="conversation"), n_hits=3, cfg=cfg
    )
    assert route == "answer"


def test_a_missing_kind_is_a_question(cfg):
    """`converse` has to be asked for; a malformed grade must not become small talk."""
    score = {"confidence": 0.1, "reasoning": "?"}
    route, _ = graph.decide_level1(top_similarity=0.0, score=score, n_hits=0, cfg=cfg)
    assert route == "rewrite"


def test_corrective_off_goes_straight_to_a_human(cfg):
    off = cfg.model_copy(deep=True)
    off.agent.corrective.enabled = False
    route, _ = graph.decide_level1(top_similarity=0.2, score=grade(0.1), n_hits=1, cfg=off)
    assert route == "escalate"


# ── Level 2 decision ────────────────────────────────────────────────────────────────


def test_level_two_answers_on_groundedness_without_a_cosine_floor(cfg):
    route, _ = graph.decide_level2(score=grade(0.85), n_hits=2, cfg=cfg)
    assert route == "answer"


def test_level_two_escalates_on_weak_groundedness(cfg):
    route, why = graph.decide_level2(score=grade(0.3), n_hits=2, cfg=cfg)
    assert route == "escalate"
    assert "confidence_threshold" in why


def test_level_two_escalates_on_no_passages_whatever_the_model_says(cfg):
    route, _ = graph.decide_level2(score=grade(0.99), n_hits=0, cfg=cfg)
    assert route == "escalate"


# ── the answering call is given no tools (D2) ───────────────────────────────────────


def test_answer_request_carries_no_tool_definitions(cfg):
    kwargs = graph.answer_request_kwargs(
        cfg, hits=[graph._hit_dict(hit(0.8))], question="What is the default CPU?", history=[]
    )
    assert "tools" not in kwargs
    assert graph._TICKET_TOOL not in str(kwargs)


def test_answer_request_puts_search_results_in_the_user_message(cfg):
    hits = [graph._hit_dict(hit(0.8)), graph._hit_dict(hit(0.7, chunk_id=2))]
    kwargs = graph.answer_request_kwargs(cfg, hits=hits, question="What is the CPU?", history=[])
    content = kwargs["messages"][-1]["content"]
    blocks = [b for b in content if b["type"] == "search_result"]
    assert len(blocks) == 2
    assert all(b["citations"] == {"enabled": True} for b in blocks)
    assert content[-1]["type"] == "text"


# ── Level 3 copy ────────────────────────────────────────────────────────────────────


def test_a_draft_missing_fields_is_completed_rather_than_dropped():
    out = graph._normalise_draft({}, question="Can you raise my Cloud Run quota in europe-west1?")
    assert (out["category"], out["product_area"], out["priority"]) == ("other", "other", "normal")
    assert "quota" in out["subject"]


def test_the_proposal_offers_and_does_not_claim():
    reply = graph._proposal_reply(
        {"subject": "Quota increase in europe-west1", "category": "quota_or_billing"}
    )
    assert "quota or billing" in reply and "europe-west1" in reply
    assert "I can open" in reply
    assert "PLATFORM-" not in reply


def test_the_confirmation_names_the_filed_ticket():
    reply = graph._escalation_reply(
        {"ticket_id": "PLATFORM-1042", "queue": "platform-serverless", "eta_hours": 8,
         "url": "https://platform.internal.example/tickets/PLATFORM-1042"},
        ok=True,
    )
    assert "PLATFORM-1042" in reply and "platform-serverless" in reply and "8 hours" in reply


def test_a_failed_filing_does_not_claim_a_ticket_exists():
    assert "nothing was filed" in graph._escalation_reply({"error": "x"}, ok=False).lower()


# ── the audit trail ─────────────────────────────────────────────────────────────────


def test_crash_injector_only_fires_on_the_named_stage(monkeypatch):
    monkeypatch.setenv("CRASH_AFTER", "grade")
    graph._maybe_crash("retrieve")
    with pytest.raises(graph.GraphCrash):
        graph._maybe_crash("grade")


@pytest.mark.asyncio
async def test_a_crash_leaves_the_completed_steps_durable(h, monkeypatch):
    monkeypatch.setenv("CRASH_AFTER", "grade")
    with pytest.raises(graph.GraphCrash):
        await h.turn("What's the default CPU?", hits=[hit(0.8)], grade=grade(0.9))
    assert [s["stage"] for s in h.runs["run-1"].steps] == ["retrieve", "grade"]


@pytest.mark.asyncio
async def test_a_repeated_stage_replaces_its_step_and_keeps_its_seq():
    """A ticket retried after a failed filing must not duplicate its step, and must keep
    its seq — the idempotency key is built from it (D4)."""
    recorder = graph.RunRecorder("run-1", "conv-1", "gcp-platform-support")

    async def _no_commit(**_k):
        pass

    recorder._persist = _no_commit
    await recorder.step("escalate", started=time.monotonic())
    await recorder.step("ticket", started=time.monotonic(), status="failed")
    assert recorder.next_seq("ticket") == 2
    await recorder.step("ticket", started=time.monotonic())
    assert [(s["stage"], s["status"]) for s in recorder.steps] == [("escalate", "ok"), ("ticket", "ok")]


# ── end to end ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_documented_question_answers_at_level_one(h):
    events = await h.turn(
        "What's the default CPU limit for a Cloud Run instance?",
        hits=[hit(0.8)], grade=grade(0.9),
    )
    assert outcome_of(events) == "answer"
    assert stages_of(events) == ["retrieve", "grade", "answer"]
    assert h.call_names() == ["grade"]  # no rewrite, no draft
    assert events[0][0] == "run" and events[-1][0] == "done"
    assert named(events, "citation")
    assert "1 vCPU" in text_of(events)
    # D2, on the real request: the answering call carried no tools.
    assert "tools" not in h.answer_requests[0]
    assert named(events, "done")[0]["cost_usd"] > 0


@pytest.mark.asyncio
async def test_a_greeting_converses_without_reaching_level_two(h):
    events = await h.turn(
        "hey", grade=grade(0.0, kind="conversation", reply="Hey — what's broken?")
    )
    assert outcome_of(events) == "converse"
    assert stages_of(events) == ["retrieve", "grade", "converse"]
    assert h.call_names() == ["grade"]
    assert h.hybrid_requests == []
    assert text_of(events) == "Hey — what's broken?"


@pytest.mark.asyncio
async def test_the_grader_cannot_claim_confidence_over_zero_passages(h):
    events = await h.turn("what is the cpu limit", hits=[], grade=grade(0.95))
    grade_step = named(events, "step")[1]
    assert grade_step["stage"] == "grade" and grade_step["confidence"] == 0.0
    assert "rewrite" in stages_of(events)


_ACTAS = hit(
    0.0,
    text="Grant the deployer the `iam.serviceAccounts.actAs` permission on the service account.",
    title="Cloud Run troubleshooting",
    source="corpus://gcp-platform-support/cloud-run-troubleshooting",
    chunk_id=7,
)


@pytest.mark.asyncio
async def test_level_two_recovers_what_level_one_missed(h):
    events = await h.turn(
        "deploy says I lack iam.serviceAccounts.actAs — what do I grant?",
        hits=[hit(0.38)],
        grade=grade(0.3),
        rewrite={
            "queries": ["permission needed to deploy with a runtime service account"],
            "keywords": "iam.serviceAccounts.actAs",
        },
        l2_hits=[_ACTAS],
        regrade=grade(0.9),
    )
    assert outcome_of(events) == "answer"
    assert stages_of(events) == [
        "retrieve", "grade", "rewrite", "hybrid_retrieve", "regrade", "answer",
    ]
    assert named(events, "step")[-1]["level"] == 2
    # Dense search runs the question plus each rewrite; keyword search gets the identifier.
    assert h.hybrid_requests[0]["queries"][0].startswith("deploy says")
    assert h.hybrid_requests[0]["keywords"] == "iam.serviceAccounts.actAs"
    # The answer is grounded in the Level 2 passages, not the Level 1 ones.
    blocks = h.answer_requests[0]["messages"][-1]["content"]
    assert "actAs" in blocks[0]["content"][0]["text"]


@pytest.mark.asyncio
async def test_rewrites_are_capped_by_config(h):
    await h.turn(
        "why is it slow",
        grade=grade(0.1),
        rewrite={"queries": ["a", "b", "c", "d", "e"], "keywords": ""},
    )
    assert h.hybrid_requests[0]["queries"][1:] == ["a", "b", "c"]  # query_rewrites: 3


@pytest.mark.asyncio
async def test_a_follow_up_is_rewritten_with_the_conversation_in_view(h):
    history = [
        {"role": "user", "content": "why does my container fail to start on PORT?"},
        {"role": "assistant", "content": "The container isn't listening on $PORT."},
    ]
    events = await h.turn(
        "so is that the same as the health check timing out?",
        history=history, grade=grade(0.0), l2_hits=[hit(0.5)], regrade=grade(0.8),
    )
    assert outcome_of(events) == "answer"
    assert "fail to start on PORT" in dict(h.calls)["rewrite"]


@pytest.mark.asyncio
async def test_level_two_falling_short_proposes_a_ticket_and_files_nothing(h):
    events = await h.turn(
        "Can you raise my Cloud Run instance quota for europe-west1?",
        hits=[hit(0.7)], grade=grade(0.05), l2_hits=[hit(0.6)], regrade=grade(0.05),
        draft={"subject": "Cloud Run instance quota increase in europe-west1",
               "category": "quota_or_billing", "product_area": "cloud_run", "priority": "high"},
    )
    assert outcome_of(events) == "ticket"
    assert stages_of(events)[-1] == "escalate"
    assert named(events, "step")[-1]["level"] == 3
    assert len(named(events, "ticket_proposal")) == 1
    assert h.ticket_calls == []
    assert "I can open" in text_of(events)


@pytest.mark.asyncio
async def test_corrective_off_skips_level_two(monkeypatch, cfg):
    off = cfg.model_copy(deep=True)
    off.agent.corrective.enabled = False
    h = Harness(monkeypatch, off)
    events = await h.turn("what is my quota?", hits=[hit(0.5)], grade=grade(0.1))
    assert stages_of(events) == ["retrieve", "grade", "escalate"]
    assert "rewrite" not in h.call_names()


@pytest.mark.asyncio
async def test_stream_emits_error_instead_of_done_when_a_stage_throws(h, monkeypatch):
    """A generator that simply stops looks like a finished turn from the browser's side."""

    async def _boom(*_a, **_k):
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(graph, "search", _boom)
    events = await h.turn("anything")
    names = [name for name, _ in events]
    assert names[-1] == "error" and "done" not in names
    assert "internal error" in events[-1][1]["message"].lower()
    assert h.runs["run-1"].status == "failed"


def test_the_graph_has_no_checkpointer_until_one_is_installed(monkeypatch):
    monkeypatch.setattr(graph, "_graph", None)
    with pytest.raises(RuntimeError, match="checkpointer"):
        graph._compiled()
