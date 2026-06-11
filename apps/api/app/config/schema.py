from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class BrandingConfig(BaseModel):
    logo: str
    primary_color: str
    assistant_name: str


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

    @field_validator("effort")
    @classmethod
    def effort_must_be_valid(cls, v: str) -> str:
        valid = {"low", "medium", "high", "max"}
        if v not in valid:
            raise ValueError(f"effort must be one of {valid}, got {v!r}")
        return v


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
