from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CorpusConfig(BaseModel):
    source: str
    chunking: ChunkingConfig = ChunkingConfig()


class CorrectiveConfig(BaseModel):
    """Level 2 of the graph engine: rewrite the question, then hybrid search (D10)."""

    # Off sends a turn Level 1 cannot answer straight to Level 3, a human.
    enabled: bool = True
    # Semantic variants the rewrite call produces, each embedded and searched.
    query_rewrites: int = Field(default=3, ge=1, le=5)


class AgentConfig(BaseModel):
    # An unknown key fails at load. `mode`, `tools` and `effort` belonged to the retired
    # loop engine; left in a YAML they would read like capabilities that do nothing (D11).
    model_config = ConfigDict(extra="forbid")

    model: str
    system_prompt_file: str
    max_tokens: int = Field(default=4096, gt=0)

    # --- the guardrail (D2, D10) ----------------------------------------------------
    # Two *different* floors, and the difference matters:
    #   retrieval_drop_floor  discards weak chunks inside search() — they never reach
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
    def escalation_floor_must_be_reachable(self) -> "AgentConfig":
        if self.escalate_below <= self.retrieval_drop_floor:
            raise ValueError(
                f"agent.escalate_below ({self.escalate_below}) must be greater than "
                f"agent.retrieval_drop_floor ({self.retrieval_drop_floor}) — otherwise the "
                f"retrieval guardrail can never fire, because search() has already "
                f"discarded every hit below the drop floor."
            )
        return self


class EvalsConfig(BaseModel):
    golden_set: str
    judge_model: str = "claude-sonnet-4-6"


class LimitsConfig(BaseModel):
    rate_limit_per_minute: int = Field(default=20, gt=0)
    daily_budget_usd: float = Field(default=2.00, gt=0)


class ClientConfig(BaseModel):
    client_id: str
    name: str
    branding: BrandingConfig
    corpus: CorpusConfig
    agent: AgentConfig
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

    def system_prompt_path(self, root: Path) -> Path:
        return root / self.agent.system_prompt_file
