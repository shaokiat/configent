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


# ── create_escalation_ticket: real HTTP against the mock service ────────────────────


@pytest.fixture
def ticket_service(monkeypatch):
    from app.tools.gcp_platform import create_escalation_ticket as tool

    from .conftest_mockticket import bind

    bind(monkeypatch, tool)
    monkeypatch.delenv("FAIL_RATE", raising=False)
    monkeypatch.delenv("LATENCY_MS", raising=False)
    yield tool


@pytest.mark.asyncio
async def test_escalation_ticket_posts_and_routes(ticket_service):
    result = await ticket_service.execute(
        {
            "subject": "Cloud Run instance quota increase needed in europe-west1",
            "category": "quota_or_billing",
            "product_area": "cloud_run",
        },
        run_id="run-a",
        stage_seq=4,
    )
    assert result["ticket_id"].startswith("PLATFORM-")
    assert result["status"] == "open"
    assert result["queue"] == "platform-serverless"
    assert result["eta_hours"] == 8
    assert result["priority"] == "normal"  # server default applied


@pytest.mark.asyncio
async def test_escalation_ticket_is_idempotent_per_run_and_stage(ticket_service):
    """The claim the crash/resume demo rests on (D4): a replayed call files no second ticket."""
    args = {"subject": "Binding present but access denied", "category": "account_config",
            "product_area": "iam"}
    first = await ticket_service.execute(dict(args), run_id="run-b", stage_seq=4)
    replay = await ticket_service.execute(dict(args), run_id="run-b", stage_seq=4)
    assert first["ticket_id"] == replay["ticket_id"]
    assert replay["replayed"] is True

    # A different run with identical content is a different ticket — content-derived ids
    # would have collided here, which is why the key is positional.
    other = await ticket_service.execute(dict(args), run_id="run-c", stage_seq=4)
    assert other["ticket_id"] != first["ticket_id"]


@pytest.mark.asyncio
async def test_escalation_ticket_reports_5xx_as_retryable(ticket_service, monkeypatch):
    monkeypatch.setenv("FAIL_RATE", "1.0")
    result = await ticket_service.execute(
        {"subject": "Autoscaler ignoring max instances", "category": "incident",
         "product_area": "cloud_run"},
        run_id="run-d",
        stage_seq=4,
    )
    assert result["retryable"] is True
    assert result["status_code"] == 503
    assert "error" in result


@pytest.mark.asyncio
async def test_escalation_ticket_rejects_bad_category_without_retrying(ticket_service):
    """A 4xx is our bug. Retrying a validation failure is not resilience."""
    result = await ticket_service.execute(
        {"subject": "x", "category": "not_a_category", "product_area": "gke"},
        run_id="run-e",
        stage_seq=4,
    )
    assert result["retryable"] is False
    assert result["status_code"] == 422


@pytest.mark.asyncio
async def test_escalation_ticket_empty_subject_errors(ticket_service):
    result = await ticket_service.execute(
        {"subject": "   ", "category": "other", "product_area": "other"}
    )
    assert "error" in result
