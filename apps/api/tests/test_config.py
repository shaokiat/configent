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
    assert cfg.corpus.source == "corpora/gcp-platform-support/"


def test_pipeline_clients_declare_no_tools():
    """A pipeline client must not list tools.

    `agent.tools` is read only by loop.py, so anything listed on a pipeline client is
    dead config that reads like a capability. Retrieval is a function call and the
    ticket executor is invoked from Python.
    """
    from app.config.registry import get_registry

    for cfg in get_registry().all():
        if cfg.agent.mode == "pipeline":
            assert cfg.agent.tools == [], (
                f"{cfg.client_id} runs the pipeline engine but lists "
                f"{cfg.agent.tools} — those definitions are never sent to a model"
            )
