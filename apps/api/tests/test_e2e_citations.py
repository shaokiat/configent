"""TC-3.6 (T3.3): live end-to-end citation assertions for both clients.

Requires RUN_INTEGRATION=1, a running pgvector DB with both corpora ingested,
and real ANTHROPIC_API_KEY / VOYAGE_API_KEY values. Each test costs one chat turn.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv("../../.env")

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live API tests",
)


async def _chat(client_id: str, message: str) -> dict:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            f"/api/c/{client_id}/chat", json={"message": message}, timeout=120.0
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_uc1_citation_end_to_end() -> None:
    """UC-1: Acme answer states 1,200 RF hours with a search_result_location citation
    whose source matches the ingested PX-900 maintenance manual."""
    data = await _chat(
        "acme-fab", "How often does the chamber seal on the PX-900 need replacing?"
    )

    assert "1,200" in data["reply"]

    locations = [
        c for c in data["citations"] if c.get("type") == "search_result_location"
    ]
    assert locations, "expected at least one search_result_location citation"
    assert any(
        "px900-maintenance-manual" in (c.get("source") or "") for c in locations
    ), f"no citation sourced from the maintenance manual: {locations}"

    # Segments must mirror the citations in frontend-friendly shape
    seg_citations = [c for seg in data["segments"] for c in seg["citations"]]
    assert any(
        "px900-maintenance-manual" in (c.get("source") or "") for c in seg_citations
    )


@pytest.mark.asyncio
async def test_meridian_citation_end_to_end() -> None:
    """T3.3 verify, second client: gradual seepage answer carries a citation from an
    ingested Meridian document.

    The question explicitly asks for the policy wording so the model must use
    search_docs; asking only for a coverage verdict lets it answer from the
    coverage_check tool alone, which carries no citations (observed flake).
    """
    data = await _chat(
        "meridian-insurance",
        "What exactly does the HomeShield Plus policy wording say about water "
        "damage from gradual seepage?",
    )

    locations = [
        c for c in data["citations"] if c.get("type") == "search_result_location"
    ]
    assert locations, "expected at least one search_result_location citation"
    assert any(
        "meridian-insurance" in (c.get("source") or "") for c in locations
    ), f"no citation sourced from the Meridian corpus: {locations}"
