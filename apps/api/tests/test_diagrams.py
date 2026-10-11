"""The docs draw each graph from code; a stale drawing fails here, not in an interview."""
import pytest

from app.agent.diagrams import OUT, mermaid
from app.agent.templates import TEMPLATES


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_committed_drawing_matches_the_graph(name):
    assert (OUT / f"{name}.mmd").read_text() == mermaid(name), (
        "Graph changed: run `cd apps/api && uv run python -m app.agent.diagrams`"
    )
