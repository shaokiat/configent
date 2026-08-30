"""Sentinel registry integrity.

`evals/sentinels.yaml` is the single source of truth for ground-truth facts (CONTEXT.md).
Every downstream retrieval, citation and eval assertion is built on it, so a sentinel that
has silently drifted out of its corpus turns those tests into ones that pass for the wrong
reason. These checks are cheap; run them on every push.
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[3]
SENTINELS = yaml.safe_load((REPO_ROOT / "evals" / "sentinels.yaml").read_text())


def _facts():
    for client, entries in SENTINELS.items():
        for sentinel_id, entry in entries.items():
            if sentinel_id == "tool_fixtures":
                continue
            yield client, sentinel_id, entry


@pytest.mark.parametrize(
    ("client", "sentinel_id", "entry"),
    [pytest.param(c, s, e, id=s) for c, s, e in _facts()],
)
def test_sentinel_appears_verbatim_in_its_document(client, sentinel_id, entry):
    doc = REPO_ROOT / "corpora" / client / entry["document"]
    assert doc.exists(), f"{sentinel_id}: {doc} does not exist"
    assert entry["fact"] in doc.read_text(), (
        f"{sentinel_id} is not verbatim in {entry['document']}. Either the corpus was "
        f"edited or the sentinel was paraphrased; fix whichever is wrong."
    )


@pytest.mark.parametrize(
    ("client", "sentinel_id", "entry"),
    [pytest.param(c, s, e, id=s) for c, s, e in _facts()],
)
def test_sentinel_does_not_leak_into_another_corpus(client, sentinel_id, entry):
    """Cross-client isolation depends on a sentinel being unique to one corpus."""
    for other in (REPO_ROOT / "corpora").iterdir():
        if not other.is_dir() or other.name == client:
            continue
        for doc in other.glob("*.md"):
            assert entry["fact"] not in doc.read_text(), (
                f"{sentinel_id} leaked into {other.name}/{doc.name} — the isolation tests "
                f"built on it would pass vacuously."
            )
