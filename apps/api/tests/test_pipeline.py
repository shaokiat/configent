"""Pipeline behaviour: the guardrail, the branch, and what the answering model is sent.

These are the week-1 exit gate (G1.1-G1.4) in test form. The gate that matters most is
G1.3 — that the answering model receives no tool definitions at all — because the whole
claim of this workflow is that escalation is not something the model can choose.
"""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.agent import pipeline
from app.config.registry import get_registry
from app.config.schema import AgentConfig


@dataclass
class _Hit:
    """Stand-in for retrieval.search.Hit — the fields the pipeline actually reads."""

    similarity: float
    text: str = "By default, each instance is limited to 1 vCPU."
    document_title: str = "Cloud Run: CPU and memory limits"
    source_uri: str = "corpus://gcp-platform-support/cloud-run-cpu-and-memory"
    chunk_id: int = 1
    document_id: str = "d1"
    chunk_index: int = 0


@pytest.fixture
def cfg():
    return get_registry().get("gcp-platform-support")


def _score(confidence: float, supported: bool = True) -> dict:
    return {"supported": supported, "confidence": confidence, "reasoning": "because"}


# ── the guardrail (D2) ──────────────────────────────────────────────────────────────


def test_answers_when_both_signals_clear_threshold(cfg):
    escalate, _ = pipeline.should_escalate(
        retrieval_confidence=0.72, score=_score(0.9), cfg=cfg
    )
    assert escalate is False


def test_escalates_on_weak_retrieval_even_with_a_confident_model(cfg):
    """The deterministic signal stands alone: a model claiming 0.99 cannot override it."""
    escalate, why = pipeline.should_escalate(
        retrieval_confidence=0.31, score=_score(0.99), cfg=cfg
    )
    assert escalate is True
    assert "escalate_below" in why


def test_escalates_on_weak_groundedness_even_with_a_strong_match(cfg):
    """The 'retrieved the right document, which doesn't contain the answer' case."""
    escalate, why = pipeline.should_escalate(
        retrieval_confidence=0.88, score=_score(0.2), cfg=cfg
    )
    assert escalate is True
    assert "confidence_threshold" in why


def test_empty_retrieval_escalates_without_scoring(cfg):
    escalate, why = pipeline.should_escalate(
        retrieval_confidence=0.0, score=None, cfg=cfg
    )
    assert escalate is True
    assert "no passages" in why


def test_escalation_floor_below_drop_floor_is_rejected_at_config_load():
    """A floor that can never fire is a silently disabled guardrail, so it fails loudly."""
    with pytest.raises(ValueError, match="can never fire"):
        AgentConfig(
            model="m",
            system_prompt_file="p.md",
            mode="pipeline",
            retrieval_drop_floor=0.5,
            escalate_below=0.4,
        )


# ── G1.3: the answering model is given no tools ─────────────────────────────────────


def test_answer_request_carries_no_tool_definitions(cfg):
    kwargs = pipeline.answer_request_kwargs(
        cfg, hits=[_Hit(0.8)], question="What is the default CPU?", history=[]
    )
    assert "tools" not in kwargs
    assert pipeline._TICKET_TOOL not in str(kwargs)


def test_answer_request_puts_search_results_in_the_user_message(cfg):
    """Retrieval is deterministic, so results arrive as top-level content rather than
    through a tool_result round trip."""
    kwargs = pipeline.answer_request_kwargs(
        cfg, hits=[_Hit(0.8), _Hit(0.7)], question="What is the default CPU?", history=[]
    )
    content = kwargs["messages"][-1]["content"]
    blocks = [b for b in content if b["type"] == "search_result"]
    assert len(blocks) == 2
    assert all(b["citations"] == {"enabled": True} for b in blocks)
    assert content[-1]["type"] == "text"


def test_answer_request_preserves_conversation_history(cfg):
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    kwargs = pipeline.answer_request_kwargs(
        cfg, hits=[_Hit(0.8)], question="follow up", history=history
    )
    assert kwargs["messages"][0] == history[0]
    assert len(kwargs["messages"]) == 3


# ── multi-turn retrieval ────────────────────────────────────────────────────────────


def test_followup_query_includes_the_previous_user_turn():
    """'And what about GKE?' embeds to nothing on its own."""
    history = [{"role": "user", "content": "Why won't my node pool scale down?"},
               {"role": "assistant", "content": "..."}]
    query = pipeline._retrieval_query("And what about GKE Autopilot?", history)
    assert "node pool" in query and "Autopilot" in query


def test_first_turn_query_is_the_message_itself():
    assert pipeline._retrieval_query("What is the default CPU?", []) == "What is the default CPU?"


# ── audit trail ─────────────────────────────────────────────────────────────────────


def test_escalation_reply_names_the_ticket_and_the_queue():
    reply = pipeline._escalation_reply(
        {"ticket_id": "PLATFORM-1042", "queue": "platform-serverless", "eta_hours": 8,
         "url": "https://platform.internal.example/tickets/PLATFORM-1042"},
        ok=True,
    )
    assert "PLATFORM-1042" in reply
    assert "platform-serverless" in reply
    assert "8 hours" in reply


def test_escalation_reply_is_honest_when_the_ticket_service_is_down():
    reply = pipeline._escalation_reply({"error": "unreachable"}, ok=False)
    assert "couldn't reach" in reply
    assert "PLATFORM-" not in reply


def test_crash_injector_only_fires_on_the_named_stage(monkeypatch):
    monkeypatch.setenv("CRASH_AFTER", "ticket")
    pipeline._maybe_crash("retrieve")  # different stage: no-op
    with pytest.raises(pipeline.PipelineCrash):
        pipeline._maybe_crash("ticket")


def test_crash_injector_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CRASH_AFTER", raising=False)
    for stage in pipeline.STAGES:
        pipeline._maybe_crash(stage)


def test_step_entries_carry_cost_and_latency():
    recorder = pipeline.RunRecorder("run-1", "conv-1", "gcp-platform-support")
    usage = pipeline.UsageTotals()
    usage.add(SimpleNamespace(input_tokens=1000, output_tokens=200,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0))
    entry = {
        "seq": 1, "stage": "score", "status": "ok", "reasoning": "r",
        "tokens_in": usage.input_tokens, "cost_usd": round(usage.cost_usd, 6),
    }
    assert entry["tokens_in"] == 1000
    assert entry["cost_usd"] > 0
    assert recorder.steps == []


# ── streaming contract ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_emits_error_instead_of_done_when_a_stage_throws(cfg, monkeypatch):
    """A generator that simply stops looks identical to a finished turn from the browser's
    side. For a workflow whose claim is auditability, that is the worst failure mode."""

    class _DB:
        async def rollback(self):
            self.rolled_back = True

    async def _boom(*a, **k):
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(pipeline, "_prepare_conversation", _boom)

    events = [
        e
        async for e in pipeline.stream_pipeline(
            "anything", cfg=cfg, client_id="gcp-platform-support",
            conversation_id=None, db=_DB(),
        )
    ]
    names = [name for name, _ in events]
    assert names == ["error"]
    assert "internal error" in events[0][1]["message"].lower()


@pytest.mark.asyncio
async def test_deliberate_crash_is_not_swallowed_by_the_error_handler(cfg, monkeypatch):
    """CRASH_AFTER exists to kill the process. A caught crash proves nothing about resume."""

    class _DB:
        async def rollback(self):
            pass

    async def _crash(*a, **k):
        raise pipeline.PipelineCrash("CRASH_AFTER=retrieve")

    monkeypatch.setattr(pipeline, "_prepare_conversation", _crash)

    with pytest.raises(pipeline.PipelineCrash):
        async for _ in pipeline.stream_pipeline(
            "anything", cfg=cfg, client_id="gcp-platform-support",
            conversation_id=None, db=_DB(),
        ):
            pass
