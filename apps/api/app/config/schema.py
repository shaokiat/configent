import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.retrieval.embed import EMBEDDING_DIM, EMBEDDING_MODELS


class BrandingConfig(BaseModel):
    logo: str
    primary_color: str
    assistant_name: str
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)
    # Empty-state copy. Left unset the UI falls back to a generic line; a client whose
    # demo has a point to make should say what it is here rather than in the frontend.
    tagline: str | None = None


class ChunkingConfig(BaseModel):
    chunk_size: int = Field(default=800, gt=0)
    overlap: int = Field(default=100, ge=0)
    # On: each chunk starts "<document title> — <heading path>", before embedding and before
    # the tsvector sees it. Off keeps today's index byte for byte.
    prefix_title: bool = False


class EmbeddingConfig(BaseModel):
    """The one hard contract between ingest and retrieval: the question is embedded with
    the same model as the chunks, or cosine similarity is noise and every threshold in
    `agent` stops meaning anything."""

    model: str = "voyage-3"

    @field_validator("model")
    @classmethod
    def model_must_fit_the_column(cls, v: str) -> str:
        if v not in EMBEDDING_MODELS:
            raise ValueError(
                f"{v!r} is not a supported embedding model. chunks.embedding is "
                f"{EMBEDDING_DIM}-dim, so the choices are {sorted(EMBEDDING_MODELS)}."
            )
        return v


class CorpusConfig(BaseModel):
    source: str
    embedding: EmbeddingConfig = EmbeddingConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    # Fallback link for a file with no `url:` in its front matter. `{stem}` and `{path}` (the
    # relative path without its extension) are filled in. Empty: such files cite as plain text.
    source_url_template: str = ""

    def fingerprint(self) -> str:
        """Hash of every setting that shapes the index. Stored on each document at ingest;
        a mismatch means the index was built under different settings and must be rebuilt.
        `source` is left out: moving the folder does not change a single vector."""
        spec = {
            "embedding_model": self.embedding.model,
            "chunk_size": self.chunking.chunk_size,
            "overlap": self.chunking.overlap,
        }
        # Added after indexes existed, so each joins the spec only when set: a config that
        # leaves them at their defaults keeps its fingerprint and nothing rebuilds on deploy.
        # The template changes no vector, but ingest stores the resulting URL per document.
        if self.chunking.prefix_title:
            spec["prefix_title"] = True
        if self.source_url_template:
            spec["source_url_template"] = self.source_url_template
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


class CorrectiveConfig(BaseModel):
    """Level 2 of the documents template: rewrite the question, then hybrid search (D10)."""

    # Off sends a turn Level 1 cannot answer straight to Level 3, a human.
    enabled: bool = True
    # Semantic variants the rewrite call produces, each embedded and searched.
    query_rewrites: int = Field(default=3, ge=1, le=5)


class DocumentsAgent(BaseModel):
    # An unknown key fails at load. `mode`, `tools` and `effort` belonged to the retired
    # loop engine; left in a YAML they would read like capabilities that do nothing (D11).
    # It also rejects a key that belongs to another template's member (D13).
    model_config = ConfigDict(extra="forbid")

    template: Literal["documents"]
    model: str
    # Every structured-output call (grading, rewriting, SQL, the ticket draft) runs on this
    # when set; the cited answer runs on `model`. Any model that follows a JSON schema (D14).
    structured_model: str | None = None
    system_prompt_file: str
    max_tokens: int = Field(default=4096, gt=0)

    # --- the guardrail (D2, D10) ----------------------------------------------------
    # Two *different* floors, and the difference matters:
    #   retrieval_drop_floor  discards weak chunks inside retrieve() — they never reach
    #                         the model at all.
    #   escalate_below        escalates when the best *surviving* hit is still weak.
    # Set escalate_below at or under retrieval_drop_floor and it can never fire:
    # hits[0] is >= the drop floor by construction, or hits is empty (which is its own
    # branch). The validator below refuses that configuration at load time.
    retrieval_drop_floor: float = Field(default=0.3, ge=0.0, le=1.0)
    escalate_below: float = Field(default=0.45, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    corrective: CorrectiveConfig = CorrectiveConfig()

    @model_validator(mode="after")
    def escalation_floor_must_be_reachable(self) -> "DocumentsAgent":
        if self.escalate_below <= self.retrieval_drop_floor:
            raise ValueError(
                f"agent.escalate_below ({self.escalate_below}) must be greater than "
                f"agent.retrieval_drop_floor ({self.retrieval_drop_floor}) — otherwise the "
                f"retrieval guardrail can never fire, because retrieve() has already "
                f"discarded every hit below the drop floor."
            )
        return self


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialect: Literal["sqlite"]  # a Postgres client would be a second dialect, not another template
    path: str  # relative to the repo root


class ContextConfig(BaseModel):
    """Where the schema notes live: `descriptions/<table>.csv`, `glossary.md`, `rules.md`."""

    model_config = ConfigDict(extra="forbid")

    source: str


class GuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_limit: int = Field(default=200, gt=0)
    timeout_ms: int = Field(default=5000, gt=0)


class DatabaseAgent(BaseModel):
    """Text-to-SQL: the schema and notes go in the prompt, the model writes a SELECT, code
    guards and runs it (D13)."""

    model_config = ConfigDict(extra="forbid")

    template: Literal["database"]
    model: str
    # Every structured-output call (grading, rewriting, SQL, the ticket draft) runs on this
    # when set; the cited answer runs on `model`. Any model that follows a JSON schema (D14).
    structured_model: str | None = None
    system_prompt_file: str
    max_tokens: int = Field(default=4096, gt=0)
    database: DatabaseConfig
    context: ContextConfig
    guard: GuardConfig = GuardConfig()
    repair_attempts: int = Field(default=2, ge=0, le=3)


# The tag picks the member, so a key from another template fails at load (D13).
AgentConfig = Annotated[DocumentsAgent | DatabaseAgent, Field(discriminator="template")]


class MessageHandoff(BaseModel):
    """Can't answer: reply with this text. No ticket, no model call (D9, amended)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["message"]
    message: str


class TicketHandoff(BaseModel):
    """Can't answer: draft a ticket, offer it, file it once on the user's confirmation (D9, D13)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["ticket"]
    queue: str | None = None  # None: the ticket service routes by product area
    categories: dict[str, str]  # id -> label shown in the offer
    product_areas: list[str] = []  # empty: the draft has no product_area field
    preamble: str = "That one needs a human."  # first sentence of the ticket offer
    team: str = "platform team"  # who the offer and the failure text say will take it

    @field_validator("categories", mode="before")
    @classmethod
    def list_of_ids(cls, v):
        return {c: c.replace("_", " ") for c in v} if isinstance(v, list) else v

    @field_validator("categories")
    @classmethod
    def other_is_the_fallback(cls, v: dict[str, str]) -> dict[str, str]:
        if "other" not in v:
            raise ValueError("categories must include 'other': an incomplete draft falls back to it")
        return v

    @cached_property
    def draft_schema(self) -> dict:
        """The ticket draft's JSON schema: built once per config, so enums are the tenant's."""
        props: dict = {
            "subject": {"type": "string"},
            "category": {"type": "string", "enum": list(self.categories)},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "body": {"type": "string"},
        }
        if self.product_areas:
            props["product_area"] = {"type": "string", "enum": self.product_areas}
        return {
            "type": "object",
            "properties": props,
            "required": ["subject", "category"],  # a model may skip an optional enum (DeepSeek did)
            "additionalProperties": False,
        }


# The tag picks the member, so a ticket key under `mode: message` fails at load.
HandoffConfig = Annotated[MessageHandoff | TicketHandoff, Field(discriminator="mode")]


class EvalsConfig(BaseModel):
    golden_set: str
    judge_model: str = "anthropic/claude-sonnet-4.6"


class LimitsConfig(BaseModel):
    rate_limit_per_minute: int = Field(default=20, gt=0)
    daily_budget_usd: float = Field(default=2.00, gt=0)


class KeywordConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True  # off, Level 2 is multi-query dense search only


class RetrievalConfig(BaseModel):
    """How the index is queried (D12). Every key defaults to the pre-config behaviour. All
    query-side, so none joins CorpusConfig.fingerprint(): edits apply with no re-ingest."""

    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=5, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    keyword: KeywordConfig = KeywordConfig()


class ClientConfig(BaseModel):
    # An unknown top-level key fails at load: a leftover `escalation:` must not sit beside
    # `handoff:` looking like it does something.
    model_config = ConfigDict(extra="forbid")

    client_id: str
    name: str
    branding: BrandingConfig
    agent: AgentConfig
    handoff: HandoffConfig
    corpus: CorpusConfig | None = None
    retrieval: RetrievalConfig | None = None
    evals: EvalsConfig | None = None
    limits: LimitsConfig = LimitsConfig()

    @field_validator("client_id")
    @classmethod
    def client_id_must_be_slug(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", v):
            raise ValueError(
                f"client_id must be a lowercase slug (letters, digits, hyphens), got {v!r}"
            )
        return v

    @field_validator("handoff", mode="before")
    @classmethod
    def mode_defaults_to_message(cls, v):
        return {"mode": "message", **v} if isinstance(v, dict) else v

    @model_validator(mode="after")
    def blocks_match_the_template(self) -> "ClientConfig":
        if self.agent.template == "documents":
            if self.corpus is None:
                raise ValueError("corpus: is required by the documents template")
            self.retrieval = self.retrieval or RetrievalConfig()
        elif self.corpus is not None or self.retrieval is not None:
            block = "corpus" if self.corpus is not None else "retrieval"
            raise ValueError(
                f"`{block}:` belongs to the documents template; database clients take "
                f"`agent.database` and `agent.context` instead"
            )
        return self

    @property
    def structured_model(self) -> str:
        # A template whose agent member has no such key runs everything on `model`.
        return getattr(self.agent, "structured_model", None) or self.agent.model

    def system_prompt_path(self, root: Path) -> Path:
        return root / self.agent.system_prompt_file
