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
    "handoff": {"message": "I couldn't find that. Email support@example.com."},
    "agent": {
        "template": "documents",
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
    """The support-agent build's primary client (D1, D9)."""
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
    from app.config.schema import DocumentsAgent

    return DocumentsAgent(template="documents", model="m", system_prompt_file="p.md", **overrides)


@pytest.mark.parametrize(
    "stale",
    [{"mode": "loop"}, {"mode": "pipeline"}, {"tools": ["search_docs"]}, {"effort": "low"}],
    ids=["mode-loop", "mode-pipeline", "tools", "effort"],
)
def test_a_retired_engine_key_fails_loudly(stale):
    """D11: a key from a retired template must not load and read like a live capability."""
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


def _load(tmp_path, **changes):
    raw = {**VALID_CONFIG, **changes}
    write_yaml(tmp_path, "c.yaml", {k: v for k, v in raw.items() if v is not None})
    return ConfigRegistry(config_dir=tmp_path)


_SQL_AGENT = {
    "template": "database",
    "model": "claude-sonnet-4-6",
    "system_prompt_file": "p.md",
    "database": {"dialect": "sqlite", "path": "data/x.sqlite"},
    "context": {"source": "corpora/x/"},
}


def test_an_agent_with_no_template_fails_naming_the_field(tmp_path):
    agent = {k: v for k, v in VALID_CONFIG["agent"].items() if k != "template"}
    with pytest.raises(ValueError, match="c.yaml.*template"):
        _load(tmp_path, agent=agent)


def test_a_database_client_cannot_carry_a_corpus(tmp_path):
    with pytest.raises(ValueError, match="belongs to the documents template"):
        _load(tmp_path, agent=_SQL_AGENT)  # VALID_CONFIG still has corpus:
    cfg = _load(tmp_path, agent=_SQL_AGENT, corpus=None).get("test-client")
    assert cfg.corpus is None and cfg.retrieval is None


def test_a_documents_key_under_a_database_agent_fails(tmp_path):
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _load(tmp_path, agent={**_SQL_AGENT, "corrective": {"enabled": True}}, corpus=None)


def test_a_documents_client_needs_a_corpus_and_gets_default_retrieval(tmp_path):
    with pytest.raises(ValueError, match="corpus: is required"):
        _load(tmp_path, corpus=None)
    assert _load(tmp_path).get("test-client").retrieval.top_k == 5


_TICKET = {"mode": "ticket", "categories": ["other"]}


def test_handoff_is_required_and_defaults_to_a_message(tmp_path):
    with pytest.raises(ValueError, match="handoff"):
        _load(tmp_path, handoff=None)
    h = _load(tmp_path).get("test-client").handoff
    assert h.mode == "message" and "support@example.com" in h.message


def test_a_message_handoff_needs_its_text_and_takes_no_ticket_keys(tmp_path):
    with pytest.raises(ValueError, match="handoff.message.message"):
        _load(tmp_path, handoff={"mode": "message"})
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _load(tmp_path, handoff={"message": "x", "queue": "support"})


def test_the_old_escalation_block_fails_at_load(tmp_path):
    with pytest.raises(ValueError, match="escalation"):
        _load(tmp_path, escalation=_TICKET)


def test_a_ticket_handoff_must_include_other(tmp_path):
    with pytest.raises(ValueError, match="'other'"):
        _load(tmp_path, handoff={"mode": "ticket", "categories": {"incident": "incident"}})


def test_the_draft_schema_follows_the_tenants_handoff_block(tmp_path):
    esc = _load(tmp_path, handoff=_TICKET).get("test-client").handoff
    props = esc.draft_schema["properties"]
    assert props["category"]["enum"] == ["other"] and "product_area" not in props
    assert esc.draft_schema is esc.draft_schema  # built once per config
    esc = _load(
        tmp_path,
        handoff={"mode": "ticket", "categories": ["other", "data_request"], "product_areas": ["a", "other"]},
    ).get("test-client").handoff
    assert esc.categories["data_request"] == "data request"
    assert esc.draft_schema["properties"]["product_area"]["enum"] == ["a", "other"]


def test_a_template_with_no_registry_entry_fails_at_load(tmp_path, monkeypatch):
    from app.agent.templates import TEMPLATES

    monkeypatch.delitem(TEMPLATES, "database")
    with pytest.raises(ValueError, match="c.yaml.*database.*no template registered"):
        _load(tmp_path, agent=_SQL_AGENT, corpus=None)
