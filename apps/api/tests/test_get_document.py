"""Tests for A2: get_document executor (scoped lookup by source URI, chunk
fallback for pre-migration rows, wrong-client rejection)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.shared import get_document


def _mock_execute_result(scalar_value=None, scalars_list=None):
    """Build a fake SQLAlchemy Result supporting .scalar_one_or_none() and
    .scalars().all(), matching the calls get_document.execute makes."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_mock
    return result


@pytest.mark.asyncio
async def test_get_document_returns_full_text_when_present():
    doc = SimpleNamespace(
        id="doc1",
        client_id="acme-fab",
        source_uri="corpus://acme-fab/px900-maintenance-manual",
        title="PX-900 Maintenance Manual",
        full_text="Full manual text.",
    )
    db = AsyncMock()
    db.execute.return_value = _mock_execute_result(scalar_value=doc)

    result = await get_document.execute(
        {"source": "corpus://acme-fab/px900-maintenance-manual"},
        client_id="acme-fab",
        db=db,
    )

    assert result["title"] == "PX-900 Maintenance Manual"
    assert result["source"] == "corpus://acme-fab/px900-maintenance-manual"
    assert result["full_text"] == "Full manual text."
    assert result["truncated"] is False
    # Full text present: no chunk fallback query needed.
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_get_document_truncates_at_8000_chars():
    long_text = "x" * 9000
    doc = SimpleNamespace(
        id="doc1",
        client_id="acme-fab",
        source_uri="corpus://acme-fab/long-doc",
        title="Long Doc",
        full_text=long_text,
    )
    db = AsyncMock()
    db.execute.return_value = _mock_execute_result(scalar_value=doc)

    result = await get_document.execute(
        {"source": "corpus://acme-fab/long-doc"}, client_id="acme-fab", db=db
    )

    assert len(result["full_text"]) == 8000
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_get_document_falls_back_to_chunks_when_full_text_null():
    doc = SimpleNamespace(
        id="doc1",
        client_id="acme-fab",
        source_uri="corpus://acme-fab/legacy-doc",
        title="Legacy Doc",
        full_text=None,
    )
    chunk_a = SimpleNamespace(chunk_index=1, text="second part")
    chunk_b = SimpleNamespace(chunk_index=0, text="first part")

    db = AsyncMock()
    db.execute.side_effect = [
        _mock_execute_result(scalar_value=doc),
        _mock_execute_result(scalars_list=[chunk_a, chunk_b]),
    ]

    result = await get_document.execute(
        {"source": "corpus://acme-fab/legacy-doc"}, client_id="acme-fab", db=db
    )

    assert result["full_text"] == "first part\n\nsecond part"
    assert db.execute.call_count == 2


@pytest.mark.asyncio
async def test_get_document_not_found_for_wrong_client():
    """The lookup is scoped by client_id in the query itself, so a document that
    exists for a different client comes back as not-found, never leaked."""
    db = AsyncMock()
    db.execute.return_value = _mock_execute_result(scalar_value=None)

    result = await get_document.execute(
        {"source": "corpus://acme-fab/px900-maintenance-manual"},
        client_id="meridian-insurance",
        db=db,
    )

    assert "error" in result
