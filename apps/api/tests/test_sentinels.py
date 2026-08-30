"""Sentinel registry integrity.

`evals/sentinels.yaml` is the single source of truth for ground-truth facts (CONTEXT.md).
Every downstream retrieval, citation and eval assertion is built on it, so a sentinel that
has silently drifted out of its corpus turns those tests into ones that pass for the wrong
reason. These checks are cheap; run them on every push.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parents[3]
SENTINELS = yaml.safe_load((REPO_ROOT / "evals" / "sentinels.yaml").read_text())


def _facts():
    for client, entries in SENTINELS.items():
        for sentinel_id, entry in entries.items():
            if sentinel_id == "tool_fixtures":
                continue
            yield client, sentinel_id, entry


def test_sentinels_appear_verbatim_in_their_documents():
    """Ground truth for every retrieval and citation assertion. A sentinel that has
    drifted out of its corpus turns those tests into ones that pass for the wrong
    reason."""
    missing = []
    for client, sentinel_id, entry in _facts():
        doc = REPO_ROOT / "corpora" / client / entry["document"]
        if not doc.exists() or entry["fact"] not in doc.read_text():
            missing.append(f"{sentinel_id} ({entry['document']})")
    assert not missing, f"sentinels not verbatim in their document: {missing}"


def test_sentinels_do_not_leak_across_corpora():
    """Cross-client isolation depends on each sentinel being unique to one corpus."""
    leaks = []
    for client, sentinel_id, entry in _facts():
        for other in (REPO_ROOT / "corpora").iterdir():
            if not other.is_dir() or other.name == client:
                continue
            for doc in other.glob("*.md"):
                if entry["fact"] in doc.read_text():
                    leaks.append(f"{sentinel_id} -> {other.name}/{doc.name}")
    assert not leaks, f"sentinels leaked across corpora: {leaks}"
