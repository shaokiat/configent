"""Pipeline behaviour: the guardrail, the branch, and what the answering model is sent.

These are the week-1 exit gate (G1.1-G1.4) in test form. The gate that matters most is
G1.3 — that the answering model receives no tool definitions at all — because the whole
claim of this workflow is that escalation is not something the model can choose.
"""
from dataclasses import dataclass

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


# ── multi-turn retrieval ────────────────────────────────────────────────────────────


def test_followup_query_includes_the_previous_user_turn():
    """'And what about GKE?' embeds to nothing on its own."""
    history = [{"role": "user", "content": "Why won't my node pool scale down?"},
               {"role": "assistant", "content": "..."}]
    query = pipeline._retrieval_query("And what about GKE Autopilot?", history)
    assert "node pool" in query and "Autopilot" in query


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


def test_crash_injector_only_fires_on_the_named_stage(monkeypatch):
    monkeypatch.setenv("CRASH_AFTER", "ticket")
    pipeline._maybe_crash("retrieve")  # different stage: no-op
    with pytest.raises(pipeline.PipelineCrash):
        pipeline._maybe_crash("ticket")


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


