from pathlib import Path

import pytest
import yaml

from app.config.registry import ConfigRegistry


def write_yaml(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data))
    return p


VALID_CONFIG = {
    "client_id": "test-client",
    "name": "Test Client",
    "branding": {
        "logo": "assets/test/logo.svg",
        "primary_color": "#FF0000",
        "assistant_name": "TestBot",
    },
    "corpus": {"source": "corpora/test/", "chunking": {"chunk_size": 800, "overlap": 100}},
    "agent": {
        "model": "claude-sonnet-4-6",
        "system_prompt_file": "prompts/test.md",
        "max_tokens": 4096,
    },
    "limits": {"rate_limit_per_minute": 20, "daily_budget_usd": 2.0},
}


def test_config_missing_field_names_it(tmp_path):
    broken = dict(VALID_CONFIG)
    broken["agent"] = {k: v for k, v in VALID_CONFIG["agent"].items() if k != "model"}
    write_yaml(tmp_path, "broken.yaml", broken)

    with pytest.raises(ValueError) as exc_info:
        ConfigRegistry(config_dir=tmp_path)

    msg = str(exc_info.value)
    assert "broken.yaml" in msg
    assert "model" in msg


def test_config_duplicate_client_id_rejected(tmp_path):
    write_yaml(tmp_path, "client-a.yaml", VALID_CONFIG)
    write_yaml(tmp_path, "client-b.yaml", VALID_CONFIG)  # same client_id

    with pytest.raises(ValueError, match="Duplicate client_id"):
        ConfigRegistry(config_dir=tmp_path)


def test_a_model_with_no_price_fails_at_load(tmp_path):
    """D8: an unpriced model would report every turn as free, and the budget would never trip."""
    bad = dict(VALID_CONFIG)
    bad["agent"] = {**VALID_CONFIG["agent"], "model": "claude-unpriced"}
    write_yaml(tmp_path, "unpriced.yaml", bad)

    with pytest.raises(ValueError, match="unpriced.yaml.*No price"):
        ConfigRegistry(config_dir=tmp_path)


def test_gcp_platform_support_config_loads():
    """The support-agent build's primary client (docs/support-agent-plan.md)."""
    from app.config.registry import get_registry

    cfg = get_registry().get("gcp-platform-support")
    assert cfg.branding.assistant_name == "DeployBot"
    assert cfg.corpus.source == "corpora/gcp-platform-support/"


def test_gcp_platform_support_runs_corrective_retrieval():
    from app.config.registry import get_registry

    agent = get_registry().get("gcp-platform-support").agent
    assert agent.corrective.enabled is True
    assert agent.corrective.query_rewrites == 3


def _agent(**overrides):
    from app.config.schema import AgentConfig

    return AgentConfig(model="m", system_prompt_file="p.md", **overrides)


@pytest.mark.parametrize(
    "stale",
    [{"mode": "loop"}, {"mode": "pipeline"}, {"tools": ["search_docs"]}, {"effort": "low"}],
    ids=["mode-loop", "mode-pipeline", "tools", "effort"],
)
def test_a_retired_engine_key_fails_loudly(stale):
    """D11: a key from a retired engine must not load and read like a live capability."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _agent(**stale)


def test_corrective_defaults_on():
    assert _agent().corrective.enabled is True


def test_query_rewrites_is_bounded():
    with pytest.raises(ValueError):
        _agent(corrective={"query_rewrites": 9})


def test_escalation_floor_below_drop_floor_is_rejected():
    """A floor that can never fire is a silently disabled guardrail, so it fails loudly."""
    with pytest.raises(ValueError, match="can never fire"):
        _agent(retrieval_drop_floor=0.5, escalate_below=0.4)
