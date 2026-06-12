"""TC-3.7 (T3.4): live UC-3 — the agent resolves a part number and calls pricing_lookup.

Requires RUN_INTEGRATION=1, a running pgvector DB with the Acme corpus ingested,
and real API keys. Costs one chat turn.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv("../../.env")

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live API tests",
)


@pytest.mark.asyncio
async def test_uc3_pricing_tool() -> None:
    """UC-3: quote for 50 PX-900 seal kits uses pricing_lookup; answer carries the
    $1,840 unit price, the 8% volume discount, and the 21-day lead time."""
    import httpx
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.main import app
    from app.models import Message

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/c/acme-fab/chat",
            json={"message": "Quote me 50 chamber seal kits for the PX-900."},
            timeout=120.0,
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    reply = data["reply"]
    assert "1,840" in reply or "1840" in reply
    assert "8%" in reply or "8 %" in reply or "8 percent" in reply
    assert "21" in reply

    # The stored history must show the pricing_lookup tool_use span
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Message).where(Message.conversation_id == data["conversation_id"])
            )
        ).scalars().all()
    assistant_blocks = [
        block
        for m in rows
        if m.role == "assistant" and isinstance(m.content, list)
        for block in m.content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    tool_names = {b.get("name") for b in assistant_blocks}
    assert "pricing_lookup" in tool_names, f"tools used: {tool_names}"
