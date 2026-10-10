"""Drive the support graph end to end with no database, no model and no network.

What is faked is everything *upstream* of the claim: retrieval, the three structured calls,
the answer stream, the ticket service, and persistence of the `Run` row. What runs for real
is the claim itself — the compiled graph, both decide functions, the recorder's step logic,
a checkpointer, `interrupt()` and resume.
"""
from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import handoff, platform
from app.agent.templates import documents
from app.retrieval import search as retrieval
from app.retrieval.search import Hit

CLIENT = "gcp-platform-support"


def hit(
    similarity: float = 0.72,
    *,
    text: str = "By default, each instance is limited to 1 vCPU.",
    title: str = "Cloud Run: CPU and memory limits",
    source: str = "corpus://gcp-platform-support/cloud-run-cpu-and-memory",
    chunk_id: int = 1,
) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        document_id="d1",
        document_title=title,
        source_uri=source,
        text=text,
        similarity=similarity,
        chunk_index=0,
    )


class _Usage:
    """OpenAI-shaped usage: `prompt_tokens` includes any cached tokens."""

    prompt_tokens = 10
    completion_tokens = 5
    prompt_tokens_details = None


def _response(text: str = "ok"):
    """A non-streamed chat completion, as a structured call gets back."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=_Usage())


async def _answer_chunks(text: str, size: int = 3):
    """The answer streamed in small chunks, so a `[n]` marker splits across them, then the
    usage-only chunk `stream_options.include_usage` adds."""
    for k in range(0, len(text), size):
        delta = SimpleNamespace(content=text[k : k + size])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)
    yield SimpleNamespace(choices=[], usage=_Usage())


class FakeDB:
    """Enough session for a turn: rows are collected, commits counted, and `Run` lookups
    are served from the fake recorder's store."""

    def __init__(self, runs: dict):
        self.runs = runs
        self.added: list = []
        self.commits = 0

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def get(self, model, key):
        if model is platform.Run:
            return self.runs.get(key)
        return None  # a Conversation miss: budget accrual no-ops


def _recorder_class(runs: dict):
    class FakeRecorder(platform.RunRecorder):
        """The real step logic; only the checkpoint session is replaced by a dict."""

        @classmethod
        async def start(cls, conversation_id, client_id, template):
            recorder = cls(f"run-{len(runs) + 1}", conversation_id, client_id)
            await recorder._persist(status="running", current_stage=template.first_stage)
            runs[recorder.run_id].template = template.name  # _persist carries it forward
            return recorder

        async def _persist(self, *, status, current_stage):
            runs[self.run_id] = SimpleNamespace(
                id=self.run_id,
                conversation_id=self.conversation_id,
                client_id=self.client_id,
                template=getattr(runs.get(self.run_id), "template", None),
                steps=list(self.steps),
                status=status,
            )

    return FakeRecorder


class Harness:
    """One test's worth of graph: a fresh in-memory checkpointer and fresh fakes.

    A turn is described by its scenario — what each retrieval returns and what each model
    call says — and the harness records every call the graph makes so tests can assert on
    what did *not* happen: no rewrite for a greeting, no POST for any chat message.
    """

    def __init__(self, monkeypatch, cfg):
        self.cfg = cfg
        self.runs: dict = {}
        self.db = FakeDB(self.runs)
        self.scenario: dict = {}
        self.calls: list[tuple[str, object]] = []
        self.answer_requests: list[dict] = []
        self.hybrid_requests: list[dict] = []
        self.ticket_calls: list[dict] = []
        self.ticket_failures = 0

        monkeypatch.setattr(platform, "_graphs", {})
        platform.use_checkpointer(InMemorySaver(), [documents.TEMPLATE])
        monkeypatch.setattr(platform, "RunRecorder", _recorder_class(self.runs))
        monkeypatch.setattr(platform, "prepare_conversation", self._prepare)
        monkeypatch.setattr(retrieval, "retrieve", self._retrieve)
        monkeypatch.setattr(platform, "_structured_call", self._structured)
        monkeypatch.setattr(handoff, "stage_ticket", self._file)
        monkeypatch.setattr(
            platform.llm,
            "async_client",
            lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create))),
        )

    # ── fakes ──────────────────────────────────────────────────────────────────────

    async def _prepare(self, _db, _client_id, conversation_id):
        return conversation_id or "conv-1", list(self.scenario.get("history") or [])

    async def _retrieve(self, _db, _client_id, queries, keywords="", *, cfg, model, floor):
        # One query is Level 1; anything more is the Level 2 request.
        if len(queries) == 1:
            return list(self.scenario.get("hits") or [])
        self.hybrid_requests.append({"queries": queries, "keywords": keywords})
        return list(self.scenario.get("l2_hits") or [])

    async def _structured(self, _aclient, *, schema, user_content, **_k):
        # By shape: the draft schema is built per client, so object identity can't name it.
        props = schema["properties"]
        name = "grade" if "confidence" in props else "rewrite" if "queries" in props else "draft"
        self.calls.append((name, user_content))
        if name == "grade":
            first = sum(1 for n, _ in self.calls if n == "grade") == 1
            out = self.scenario.get("grade" if first else "regrade") or {
                "kind": "question",
                "supported": False,
                "confidence": 0.1,
                "reasoning": "The passages do not contain this.",
            }
        elif name == "rewrite":
            out = self.scenario.get("rewrite") or {"queries": ["q1", "q2", "q3"], "keywords": ""}
        else:
            out = self.scenario.get("draft") or {}
        return dict(out), _response()

    async def _create(self, *, stream=False, stream_options=None, **kwargs):
        assert stream, "only the answer streams; structured calls are faked above"
        self.answer_requests.append(kwargs)
        return _answer_chunks(self.scenario.get("answer_text", "By default each instance gets 1 vCPU. [1]"))

    async def _file(self, draft, *, run_id, stage_seq):
        self.ticket_calls.append({"draft": draft, "run_id": run_id, "stage_seq": stage_seq})
        if self.ticket_failures:
            self.ticket_failures -= 1
            return {"error": "Ticket service unreachable: ConnectError", "retryable": True}
        ticket_id = f"PLATFORM-{1000 + len(self.ticket_calls)}"
        return {
            "ticket_id": ticket_id,
            "url": f"https://platform.internal.example/tickets/{ticket_id}",
            "queue": "platform-serverless",
            "eta_hours": 4,
        }

    # ── driving ────────────────────────────────────────────────────────────────────

    async def turn(self, message: str, **scenario) -> list[tuple[str, dict]]:
        self.scenario = scenario
        self.calls = []
        return [
            event
            async for event in platform.stream_turn(
                message, template=documents.TEMPLATE, cfg=self.cfg, client_id=CLIENT, conversation_id=None, db=self.db
            )
        ]

    async def confirm(self, run_id: str = "run-1", client_id: str = CLIENT) -> dict:
        return await platform.confirm_ticket(
            run_id=run_id, client_id=client_id, cfg=self.cfg, db=self.db
        )

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


# ── reading events ────────────────────────────────────────────────────────────────────


def outcome_of(events) -> str:
    done = [d for name, d in events if name == "done"]
    assert done, f"turn produced no done event: {[n for n, _ in events]}"
    return done[0]["outcome"]


def text_of(events) -> str:
    return "".join(d["delta"] for name, d in events if name == "text")


def stages_of(events) -> list[str]:
    return [d["stage"] for name, d in events if name == "step"]


def named(events, name: str) -> list[dict]:
    return [d for n, d in events if n == name]


def grade(confidence: float, *, kind: str = "question", reply: str | None = None) -> dict:
    out = {
        "kind": kind,
        "supported": confidence >= 0.6,
        "confidence": confidence,
        "reasoning": "because",
    }
    if reply is not None:
        out["reply"] = reply
    return out
