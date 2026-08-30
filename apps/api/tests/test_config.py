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
        "effort": "medium",
        "tools": ["search_docs", "get_document"],
    },
    "limits": {"rate_limit_per_minute": 20, "daily_budget_usd": 2.0},
}


def test_config_valid_loads(tmp_path):
    write_yaml(tmp_path, "test-client.yaml", VALID_CONFIG)
    registry = ConfigRegistry(config_dir=tmp_path)
    cfg = registry.get("test-client")
    assert cfg.client_id == "test-client"
    assert cfg.name == "Test Client"
    assert cfg.branding.primary_color == "#FF0000"


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


def test_config_all_returns_all_clients(tmp_path):
    write_yaml(tmp_path, "test-client.yaml", VALID_CONFIG)
    second = dict(VALID_CONFIG)
    second["client_id"] = "second-client"
    second["name"] = "Second"
    write_yaml(tmp_path, "second-client.yaml", second)

    registry = ConfigRegistry(config_dir=tmp_path)
    ids = {cfg.client_id for cfg in registry.all()}
    assert ids == {"test-client", "second-client"}


def test_config_empty_dir_loads_zero_clients(tmp_path):
    registry = ConfigRegistry(config_dir=tmp_path)
    assert registry.all() == []


def test_config_suggested_questions_default_empty(tmp_path):
    write_yaml(tmp_path, "test-client.yaml", VALID_CONFIG)
    registry = ConfigRegistry(config_dir=tmp_path)
    cfg = registry.get("test-client")
    assert cfg.branding.suggested_questions == []


def test_config_suggested_questions_loaded(tmp_path):
    with_questions = dict(VALID_CONFIG)
    with_questions["branding"] = dict(VALID_CONFIG["branding"])
    with_questions["branding"]["suggested_questions"] = [
        "How do I add a client?",
        "How do citations work?",
    ]
    write_yaml(tmp_path, "test-client.yaml", with_questions)
    registry = ConfigRegistry(config_dir=tmp_path)
    cfg = registry.get("test-client")
    assert cfg.branding.suggested_questions == [
        "How do I add a client?",
        "How do citations work?",
    ]


def test_config_suggested_questions_over_max_rejected(tmp_path):
    too_many = dict(VALID_CONFIG)
    too_many["branding"] = dict(VALID_CONFIG["branding"])
    too_many["branding"]["suggested_questions"] = [f"Question {i}?" for i in range(6)]
    write_yaml(tmp_path, "test-client.yaml", too_many)

    with pytest.raises(ValueError):
        ConfigRegistry(config_dir=tmp_path)


def test_config_unknown_tool_rejected(tmp_path):
    bad = dict(VALID_CONFIG)
    bad["agent"] = dict(VALID_CONFIG["agent"])
    bad["agent"]["tools"] = ["search_docs", "nonexistent_tool"]
    write_yaml(tmp_path, "bad-tools.yaml", bad)

    with pytest.raises(ValueError, match="Unknown tool"):
        ConfigRegistry(config_dir=tmp_path)


def test_gcp_platform_support_config_loads():
    """The support-agent build's primary client (docs/support-agent-plan.md)."""
    from app.config.registry import get_registry

    cfg = get_registry().get("gcp-platform-support")
    assert cfg.branding.assistant_name == "DeployBot"
    assert "create_escalation_ticket" in cfg.agent.tools
    assert cfg.corpus.source == "corpora/gcp-platform-support/"
