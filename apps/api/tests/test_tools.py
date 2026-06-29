import pytest

from app.tools.registry import get_tool_definitions, validate_tool_names


def test_registry_resolves_acme_tools():
    acme_tools = ["search_docs", "get_document", "pricing_lookup"]
    defs = get_tool_definitions(acme_tools)
    names = {d["name"] for d in defs}
    assert names == set(acme_tools)
    assert "pricing_lookup" in names
    assert "coverage_check" not in names


def test_registry_resolves_meridian_tools():
    meridian_tools = ["search_docs", "get_document", "coverage_check"]
    defs = get_tool_definitions(meridian_tools)
    names = {d["name"] for d in defs}
    assert names == set(meridian_tools)
    assert "coverage_check" in names
    assert "pricing_lookup" not in names


def test_registry_resolves_configent_support_tools():
    support_tools = ["search_docs", "get_document", "create_support_ticket"]
    defs = get_tool_definitions(support_tools)
    names = {d["name"] for d in defs}
    assert names == set(support_tools)
    assert "create_support_ticket" in names
    assert "coverage_check" not in names
    assert "pricing_lookup" not in names


def test_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        validate_tool_names(["nonexistent_tool"])


def test_tool_definitions_have_descriptions():
    defs = get_tool_definitions(["search_docs", "get_document"])
    for defn in defs:
        assert "description" in defn
        assert len(defn["description"]) > 50, "Tool descriptions must be substantive"


@pytest.mark.asyncio
async def test_pricing_lookup_applies_volume_discount():
    from app.tools.acme_fab.pricing_lookup import execute

    result = await execute({"part_number": "PX900-SEAL-A2", "quantity": 50})
    assert result["unit_price_usd"] == 1840.00
    assert result["discount_pct"] == 8  # 50 >= min_qty of 10
    assert result["total_usd"] == round(1840.00 * 0.92 * 50, 2)
    assert result["lead_time_days"] == 21


@pytest.mark.asyncio
async def test_pricing_lookup_unknown_part():
    from app.tools.acme_fab.pricing_lookup import execute

    result = await execute({"part_number": "UNKNOWN-PART"})
    assert "error" in result


@pytest.mark.asyncio
async def test_coverage_check_gradual_seepage():
    from app.tools.meridian.coverage_check import execute

    result = await execute({"scenario": "gradual_seepage"})
    assert result["covered"] is False
    assert result["clause"] == "4.2.1"


@pytest.mark.asyncio
async def test_coverage_check_burst_pipe():
    from app.tools.meridian.coverage_check import execute

    result = await execute({"scenario": "burst_pipe_sudden"})
    assert result["covered"] is True
    assert result["excess_usd"] == 500


@pytest.mark.asyncio
async def test_create_support_ticket_is_deterministic():
    from app.tools.configent_support.create_support_ticket import execute

    args = {"subject": "Ingestion fails with missing VOYAGE_API_KEY", "category": "bug"}
    first = await execute(args)
    second = await execute(dict(args))

    assert first["ticket_id"] == second["ticket_id"]
    assert first["ticket_id"].startswith("CONFIGENT-")
    assert first["status"] == "open"
    assert first["category"] == "bug"
    assert first["priority"] == "normal"  # default applied
    assert first["eta_hours"] == 8  # bug ETA


@pytest.mark.asyncio
async def test_create_support_ticket_category_changes_id():
    from app.tools.configent_support.create_support_ticket import execute

    subject = "Add support for per-source ingestion"
    bug = await execute({"subject": subject, "category": "bug"})
    feature = await execute({"subject": subject, "category": "feature_request"})
    assert bug["ticket_id"] != feature["ticket_id"]
    assert feature["eta_hours"] == 72


@pytest.mark.asyncio
async def test_create_support_ticket_empty_subject_errors():
    from app.tools.configent_support.create_support_ticket import execute

    result = await execute({"subject": "   ", "category": "other"})
    assert "error" in result
