from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


class BrandingConfig(BaseModel):
    logo: str
    primary_color: str
    assistant_name: str
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)


class ChunkingConfig(BaseModel):
    chunk_size: int = Field(default=800, gt=0)
    overlap: int = Field(default=100, ge=0)


class CorpusConfig(BaseModel):
    source: str
    chunking: ChunkingConfig = ChunkingConfig()


class AgentConfig(BaseModel):
    model: str
    system_prompt_file: str
    max_tokens: int = Field(default=4096, gt=0)
    effort: str = Field(default="medium")
    tools: list[str] = Field(default_factory=list)

    # "loop" is the free-form manual tool-use loop; "pipeline" is the fixed-stage
    # support workflow whose escalation branch is Python control flow (D5).
    mode: str = Field(default="loop")

    # --- pipeline-only knobs (D2) -------------------------------------------------
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

    @field_validator("effort")
    @classmethod
    def effort_must_be_valid(cls, v: str) -> str:
        valid = {"low", "medium", "high", "max"}
        if v not in valid:
            raise ValueError(f"effort must be one of {valid}, got {v!r}")
        return v

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        valid = {"loop", "pipeline"}
        if v not in valid:
            raise ValueError(f"agent.mode must be one of {valid}, got {v!r}")
        return v

    @model_validator(mode="after")
    def escalation_floor_must_be_reachable(self) -> "AgentConfig":
        if self.mode == "pipeline" and self.escalate_below <= self.retrieval_drop_floor:
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
