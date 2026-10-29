"""Unit tests for OutreachClient config guard, start_outreach_for_campaign,
and normalize_research_signals edge cases.

These tests use a temp SQLite DB and monkeypatch the OutreachClient's MCP
client so no real subprocess or network is required.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.mcp_clients.outreach_client import OutreachClient
from app.pipeline.outreach import (
    build_outreach_payload,
    normalize_research_signals,
    start_outreach_for_campaign,
)
from app.store import CampaignStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_package() -> Dict[str, Any]:
    return {
        "lead_id": "camp-1:persona-1",
        "campaign_id": "camp-1",
        "icp": {"raw": "ICP text", "features": {}, "user_offering": "Cyber analytics"},
        "company": {
            "apollo_id": "co-1",
            "name": "Acme Inc",
            "country": "France",
            "city": "Paris",
            "intent_signals": {
                "job_offers": [{"title": "Senior SDR"}],
                "news": [{"headline": "Raised Series B"}],
            },
            "intent_summary": "Hiring sales; just raised funding",
        },
        "persona": {
            "apollo_id": "persona-1",
            "name": "Alice Martin",
            "title": "VP Sales",
            "email": "alice@acme.com",
            "is_linkedin_connected": True,
            "signals": "Posted about scaling SDRs",
        },
    }


class _FakeMcpClient:
    """In-process fake of McpStdioClient that records calls and returns canned data."""

    def __init__(
        self,
        run_response: Optional[Dict[str, Any]] = None,
        approve_response: Optional[Dict[str, Any]] = None,
        raise_on_run: Optional[Exception] = None,
    ):
        self._run_response = run_response or {"status": "awaiting_approval", "thread_id": "fake-thread-1"}
        self._approve_response = approve_response or {"status": "dispatched", "thread_id": "fake-thread-1"}
        self._raise_on_run = raise_on_run
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.calls.append({"name": name, "arguments": arguments})
        if name == "run_outreach_pipeline":
            if self._raise_on_run:
                raise self._raise_on_run
            return self._run_response
        if name == "approve_pipeline":
            return self._approve_response
        if name == "get_outreach_status":
            return {"status": "ok"}
        if name == "get_observability":
            return {"module": "outreach", "total_tokens": 0}
        return {"error": f"unknown tool {name}"}


# ---------------------------------------------------------------------------
# OutreachClient path guard
# ---------------------------------------------------------------------------


def test_outreach_client_raises_when_mcp_path_missing(tmp_path, monkeypatch):
    """OutreachClient must raise FileNotFoundError if OUTREACH_MCP_PATH is missing."""
    from app.config import Settings

    fake_settings = Settings(
        _env_file=None,
        outreach_mcp_path=str(tmp_path / "does_not_exist.py"),
    )
    monkeypatch.setattr("app.mcp_clients.outreach_client.settings", fake_settings)

    with pytest.raises(FileNotFoundError, match="OUTREACH_MCP_PATH"):
        OutreachClient()


def test_outreach_client_warns_when_not_run_mcp(tmp_path, monkeypatch, caplog):
    """OutreachClient should log a warning if the script is not run_mcp.py."""
    from app.config import Settings

    # Create a file with a different name that exists
    fake_script = tmp_path / "mcp_server.py"
    fake_script.write_text("# stub\n", encoding="utf-8")

    fake_settings = Settings(
        _env_file=None,
        outreach_mcp_path=str(fake_script),
    )
    monkeypatch.setattr("app.mcp_clients.outreach_client.settings", fake_settings)

    with caplog.at_level(logging.WARNING, logger="app.mcp_clients.outreach_client"):
        OutreachClient()

    assert any("run_mcp.py" in rec.message for rec in caplog.records)


def test_outreach_client_constructs_when_path_valid(tmp_path, monkeypatch):
    """OutreachClient should construct cleanly when path points to existing run_mcp.py."""
    from app.config import Settings

    fake_script = tmp_path / "run_mcp.py"
    fake_script.write_text("# stub\n", encoding="utf-8")

    fake_settings = Settings(
        _env_file=None,
        outreach_mcp_path=str(fake_script),
        outreach_python=str(tmp_path / "python.exe"),
    )
    monkeypatch.setattr("app.mcp_clients.outreach_client.settings", fake_settings)

    client = OutreachClient()
    assert client._client is not None


def test_outreach_client_accepts_injected_client():
    """OutreachClient should use an injected client without touching settings."""
    fake = _FakeMcpClient()
    client = OutreachClient(client=fake)
    assert client._client is fake


# ---------------------------------------------------------------------------
# OutreachClient tool delegation (uses injected fake, no subprocess)
# ---------------------------------------------------------------------------


def test_start_outreach_delegates_to_call_tool():
    fake = _FakeMcpClient(run_response={"status": "awaiting_approval", "thread_id": "t-1"})
    client = OutreachClient(client=fake)
    result = asyncio.run(client.start_outreach({"entreprise": "Acme", "contact_full_name": "Alice"}))
    assert result["status"] == "awaiting_approval"
    assert fake.calls[0]["name"] == "run_outreach_pipeline"
    assert fake.calls[0]["arguments"]["entreprise"] == "Acme"


def test_approve_pipeline_delegates_with_feedback():
    fake = _FakeMcpClient()
    client = OutreachClient(client=fake)
    asyncio.run(client.approve_pipeline("t-1", approved=False, feedback="shorter please"))
    call = fake.calls[0]
    assert call["name"] == "approve_pipeline"
    assert call["arguments"]["thread_id"] == "t-1"
    assert call["arguments"]["approved"] is False
    assert call["arguments"]["feedback"] == "shorter please"


def test_approve_pipeline_defaults_feedback_to_empty():
    fake = _FakeMcpClient()
    client = OutreachClient(client=fake)
    asyncio.run(client.approve_pipeline("t-1"))
    assert fake.calls[0]["arguments"]["feedback"] == ""


def test_health_calls_get_outreach_status():
    fake = _FakeMcpClient()
    client = OutreachClient(client=fake)
    result = asyncio.run(client.health())
    assert result["status"] == "ok"
    assert fake.calls[0]["name"] == "get_outreach_status"


def test_observability_calls_get_observability():
    fake = _FakeMcpClient()
    client = OutreachClient(client=fake)
    result = asyncio.run(client.observability())
    assert result["module"] == "outreach"
    assert fake.calls[0]["name"] == "get_observability"


# ---------------------------------------------------------------------------
# start_outreach_for_campaign (uses temp DB + injected fake client)
# ---------------------------------------------------------------------------


def _setup_campaign_with_package(db_path: Path) -> str:
    store = CampaignStore(str(db_path))
    cid = store.create_campaign("test-user", "ICP text", "Cyber analytics")
    store.save_final_packages(cid, [_sample_package()])
    return cid


def test_start_outreach_for_campaign_success(tmp_path, monkeypatch):
    db_path = tmp_path / "test_outreach.db"
    cid = _setup_campaign_with_package(db_path)

    fresh_store = CampaignStore(str(db_path))
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    fake = _FakeMcpClient(run_response={"status": "awaiting_approval", "thread_id": "real-thread-9"})
    monkeypatch.setattr("app.pipeline.outreach.OutreachClient", lambda: OutreachClient(client=fake))

    results = asyncio.run(start_outreach_for_campaign(cid))
    assert len(results) == 1
    assert results[0]["status"] == "awaiting_approval"
    assert results[0]["thread_id"] == "real-thread-9"

    threads = fresh_store.list_outreach_threads(cid)
    assert len(threads) == 1
    assert threads[0]["thread_id"] == "real-thread-9"
    assert threads[0]["status"] == "awaiting_approval"


def test_start_outreach_for_campaign_failure_records_error(tmp_path, monkeypatch):
    db_path = tmp_path / "test_outreach.db"
    cid = _setup_campaign_with_package(db_path)

    fresh_store = CampaignStore(str(db_path))
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    fake = _FakeMcpClient(raise_on_run=RuntimeError("MCP connection closed"))
    monkeypatch.setattr("app.pipeline.outreach.OutreachClient", lambda: OutreachClient(client=fake))

    results = asyncio.run(start_outreach_for_campaign(cid))
    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert "MCP connection closed" in results[0]["error"]

    threads = fresh_store.list_outreach_threads(cid)
    assert len(threads) == 1
    assert threads[0]["status"] == "failed"
    assert threads[0]["thread_id"] is None


def test_start_outreach_for_campaign_no_packages_raises(tmp_path, monkeypatch):
    db_path = tmp_path / "test_outreach.db"
    fresh_store = CampaignStore(str(db_path))
    cid = fresh_store.create_campaign("u", "icp", "offer")
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    with pytest.raises(ValueError, match="No lead packages"):
        asyncio.run(start_outreach_for_campaign(cid))


def test_start_outreach_for_campaign_unknown_campaign_raises(tmp_path, monkeypatch):
    fresh_store = CampaignStore(str(tmp_path / "test_outreach.db"))
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    with pytest.raises(ValueError, match="Campaign not found"):
        asyncio.run(start_outreach_for_campaign("nonexistent-id"))


def test_start_outreach_for_campaign_lead_id_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "test_outreach.db"
    fresh_store = CampaignStore(str(db_path))
    cid = fresh_store.create_campaign("u", "icp", "offer")
    # Two packages with different lead_ids
    pkg_a = {**_sample_package(), "lead_id": f"{cid}:lead-a"}
    pkg_b = {**_sample_package(), "lead_id": f"{cid}:lead-b", "persona": {**_sample_package()["persona"], "name": "Bob"}}
    fresh_store.save_final_packages(cid, [pkg_a, pkg_b])
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    fake = _FakeMcpClient()
    monkeypatch.setattr("app.pipeline.outreach.OutreachClient", lambda: OutreachClient(client=fake))

    results = asyncio.run(start_outreach_for_campaign(cid, lead_ids=[f"{cid}:lead-a"]))
    assert len(results) == 1
    assert results[0]["lead_id"] == f"{cid}:lead-a"


def test_start_outreach_for_campaign_lead_id_no_match_raises(tmp_path, monkeypatch):
    db_path = tmp_path / "test_outreach.db"
    fresh_store = CampaignStore(str(db_path))
    cid = fresh_store.create_campaign("u", "icp", "offer")
    fresh_store.save_final_packages(cid, [_sample_package()])
    monkeypatch.setattr("app.pipeline.outreach.store", fresh_store)

    fake = _FakeMcpClient()
    monkeypatch.setattr("app.pipeline.outreach.OutreachClient", lambda: OutreachClient(client=fake))

    with pytest.raises(ValueError, match="No matching lead packages"):
        asyncio.run(start_outreach_for_campaign(cid, lead_ids=["nonexistent-lead"]))


# ---------------------------------------------------------------------------
# normalize_research_signals edge cases
# ---------------------------------------------------------------------------


def test_normalize_signals_empty_package():
    assert normalize_research_signals({}) == []


def test_normalize_signals_none_persona():
    pkg = _sample_package()
    pkg["persona"] = None
    # Still extracts company intent signals
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "job_offer" for s in signals)


def test_normalize_signals_dict_signals():
    pkg = _sample_package()
    pkg["persona"]["signals"] = {"intent": "hiring", "budget": "high"}
    signals = normalize_research_signals(pkg)
    types = [s["type"] for s in signals]
    assert "persona_intent" in types
    assert "persona_budget" in types


def test_normalize_signals_list_of_strings():
    pkg = _sample_package()
    pkg["persona"]["signals"] = ["posted about SDRs", "hiring"]
    signals = normalize_research_signals(pkg)
    # Two persona signals from the list, plus company intent signals from the sample
    persona_signals = [s for s in signals if s["type"] == "persona_signal"]
    assert len(persona_signals) == 2
    assert all(s["type"] == "persona_signal" for s in persona_signals)


def test_normalize_signals_list_of_dicts():
    pkg = _sample_package()
    pkg["persona"]["signals"] = [
        {"type": "post", "content": "hiring", "why_relevant": "growth"},
        {"summary": "budget news"},
    ]
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "post" for s in signals)
    assert any("budget news" in s["content"] for s in signals)


def test_normalize_signals_empty_signals_skipped():
    pkg = _sample_package()
    pkg["persona"]["signals"] = ""
    signals = normalize_research_signals(pkg)
    # No persona signal, but company intent signals remain
    assert not any(s["type"] == "persona_signal" for s in signals)
    assert any(s["type"] == "company_intent" for s in signals)


def test_normalize_signals_none_company_intent():
    pkg = _sample_package()
    pkg["company"] = None
    # Only persona signal
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "persona_signal" for s in signals)
    assert not any(s["type"] == "job_offer" for s in signals)


def test_normalize_signals_company_no_intent_fields():
    pkg = _sample_package()
    pkg["company"]["intent_signals"] = {}
    pkg["company"]["intent_summary"] = None
    signals = normalize_research_signals(pkg)
    # Only persona signal, no company signals
    assert any(s["type"] == "persona_signal" for s in signals)
    assert not any(s["type"] == "job_offer" for s in signals)
    assert not any(s["type"] == "company_intent" for s in signals)


# ---------------------------------------------------------------------------
# build_outreach_payload: persona None edge case
# ---------------------------------------------------------------------------


def test_build_outreach_payload_persona_none():
    pkg = _sample_package()
    pkg["persona"] = None
    campaign = {"raw_icp": "ICP", "user_offering": "Cyber analytics"}
    payload = build_outreach_payload(pkg, campaign)
    assert payload["contact_full_name"] == "Unknown"
    assert payload["contact_job_title"] == ""
    assert payload["web_profil_brut"] == ""
    assert payload["is_connected_on_linkedin"] is False


def test_build_outreach_payload_missing_company_country():
    pkg = _sample_package()
    pkg["company"].pop("country", None)
    campaign = {"raw_icp": "ICP", "user_offering": "Cyber analytics"}
    payload = build_outreach_payload(pkg, campaign)
    assert payload["contact_country"] == ""


# ---------------------------------------------------------------------------
# McpStdioClient timeout
# ---------------------------------------------------------------------------


class _FakeSlowMcpContext:
    """Fake async context manager that mimics fastmcp.Client but sleeps in call_tool."""

    def __init__(self, delay: float):
        self._delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        await asyncio.sleep(self._delay)
        return {"status": "should_not_reach"}


def test_mcp_stdio_client_timeout_raises_timeout_error(tmp_path, monkeypatch):
    """McpStdioClient.call_tool must raise TimeoutError with 'timed out' when the
    tool call exceeds the configured timeout."""
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    # Create a real stub script so PythonStdioTransport path validation passes
    dummy_script = tmp_path / "dummy.py"
    dummy_script.write_text("# stub\n", encoding="utf-8")

    # Monkeypatch Client to return our slow fake instead of spawning a subprocess
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: _FakeSlowMcpContext(delay=5.0))

    client = McpStdioClient(str(dummy_script), timeout=0.1)

    with pytest.raises(TimeoutError, match="timed out"):
        asyncio.run(client.call_tool("run_outreach_pipeline", {}))


def test_mcp_stdio_client_default_timeout_is_120():
    """McpStdioClient should default to a 120s timeout."""
    from app.mcp_clients import McpStdioClient

    client = McpStdioClient("/tmp/dummy.py")
    assert client.timeout == 120.0


def test_mcp_stdio_client_custom_timeout():
    """McpStdioClient should accept a custom timeout."""
    from app.mcp_clients import McpStdioClient

    client = McpStdioClient("/tmp/dummy.py", timeout=300.0)
    assert client.timeout == 300.0


def test_outreach_client_passes_timeout_from_settings(tmp_path, monkeypatch):
    """OutreachClient should pass settings.outreach_timeout to McpStdioClient."""
    from app.config import Settings

    fake_script = tmp_path / "run_mcp.py"
    fake_script.write_text("# stub\n", encoding="utf-8")

    fake_settings = Settings(
        _env_file=None,
        outreach_mcp_path=str(fake_script),
        outreach_timeout=60.0,
    )
    monkeypatch.setattr("app.mcp_clients.outreach_client.settings", fake_settings)

    client = OutreachClient()
    assert client._client.timeout == 60.0


# ---------------------------------------------------------------------------
# McpStdioClient retry + exponential backoff
# ---------------------------------------------------------------------------


class _FlakyFakeMcpContext:
    """Fake async context manager that fails N times then succeeds."""

    def __init__(self, fail_count: int, delay: float = 0.0):
        self._fail_count = fail_count
        self._delay = delay
        self._call_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        await asyncio.sleep(self._delay)
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ConnectionError(f"simulated failure #{self._call_count}")
        return {"status": "awaiting_approval", "thread_id": "recovered-thread"}


def test_mcp_stdio_client_retries_on_connection_error(tmp_path, monkeypatch):
    """McpStdioClient.call_tool should retry on ConnectionError and succeed."""
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    dummy = tmp_path / "dummy.py"
    dummy.write_text("# stub\n", encoding="utf-8")

    flaky = _FlakyFakeMcpContext(fail_count=1, delay=0.0)
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: flaky)
    # Speed up the test: replace backoff sleep with instant no-op
    _original_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _: _original_sleep(0))

    client = McpStdioClient(str(dummy), timeout=5.0, max_retries=2, retry_backoff_base=0.01)
    result = asyncio.run(client.call_tool("run_outreach_pipeline", {}))
    assert result["thread_id"] == "recovered-thread"
    assert flaky._call_count == 2  # 1 failure + 1 success


def test_mcp_stdio_client_retries_on_timeout(tmp_path, monkeypatch):
    """McpStdioClient.call_tool should retry on TimeoutError."""
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    dummy = tmp_path / "dummy.py"
    dummy.write_text("# stub\n", encoding="utf-8")

    # Use a fake that always raises TimeoutError (no real sleep needed)
    class _AlwaysTimeoutCtx:
        def __init__(self):
            self._call_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def call_tool(self, name, arguments):
            self._call_count += 1
            raise asyncio.TimeoutError()

    timeout_ctx = _AlwaysTimeoutCtx()
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: timeout_ctx)
    _original_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _: _original_sleep(0))

    client = McpStdioClient(str(dummy), timeout=0.1, max_retries=2, retry_backoff_base=0.01)
    with pytest.raises(TimeoutError):
        asyncio.run(client.call_tool("run_outreach_pipeline", {}))
    assert timeout_ctx._call_count == 3  # 1 initial + 2 retries


def test_mcp_stdio_client_no_retry_on_success(tmp_path, monkeypatch):
    """McpStdioClient should not retry when the first attempt succeeds."""
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    dummy = tmp_path / "dummy.py"
    dummy.write_text("# stub\n", encoding="utf-8")

    stable = _FlakyFakeMcpContext(fail_count=0, delay=0.0)
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: stable)

    client = McpStdioClient(str(dummy), timeout=5.0, max_retries=3)
    result = asyncio.run(client.call_tool("run_outreach_pipeline", {}))
    assert result["thread_id"] == "recovered-thread"
    assert stable._call_count == 1


def test_mcp_stdio_client_gives_up_after_max_retries(tmp_path, monkeypatch):
    """McpStdioClient should raise after exhausting all retries."""
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    dummy = tmp_path / "dummy.py"
    dummy.write_text("# stub\n", encoding="utf-8")

    always_fail = _FlakyFakeMcpContext(fail_count=99, delay=0.0)
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: always_fail)
    _original_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _: _original_sleep(0))

    client = McpStdioClient(str(dummy), timeout=5.0, max_retries=2, retry_backoff_base=0.01)
    with pytest.raises(ConnectionError, match="simulated failure"):
        asyncio.run(client.call_tool("run_outreach_pipeline", {}))
    assert always_fail._call_count == 3  # 1 initial + 2 retries


def test_mcp_stdio_client_default_no_retries():
    """McpStdioClient should default to max_retries=0 (no retry)."""
    from app.mcp_clients import McpStdioClient

    client = McpStdioClient("/tmp/dummy.py")
    assert client.max_retries == 0


def test_outreach_client_passes_retry_config_from_settings(tmp_path, monkeypatch):
    """OutreachClient should pass settings.outreach_max_retries to McpStdioClient."""
    from app.config import Settings

    fake_script = tmp_path / "run_mcp.py"
    fake_script.write_text("# stub\n", encoding="utf-8")

    fake_settings = Settings(
        _env_file=None,
        outreach_mcp_path=str(fake_script),
        outreach_max_retries=5,
        outreach_retry_backoff_base=3.0,
    )
    monkeypatch.setattr("app.mcp_clients.outreach_client.settings", fake_settings)

    client = OutreachClient()
    assert client._client.max_retries == 5
    assert client._client.retry_backoff_base == 3.0


def test_mcp_stdio_client_negative_max_retries_raises_runtime_error(tmp_path, monkeypatch):
    """When max_retries < 0, the retry loop body never runs, so last_exc stays
    None. call_tool must raise a clear RuntimeError instead of TypeError
    from `raise None`.
    """
    from app.mcp_clients import McpStdioClient
    import app.mcp_clients as mcp_mod

    dummy = tmp_path / "dummy.py"
    dummy.write_text("# stub\n", encoding="utf-8")

    # Even with a fake Client, the loop range(max_retries + 1) = range(0) is
    # empty when max_retries = -1, so _call_tool_once is never called.
    monkeypatch.setattr(mcp_mod, "Client", lambda transport: _FlakyFakeMcpContext(fail_count=0))

    client = McpStdioClient(str(dummy), timeout=5.0, max_retries=-1)
    with pytest.raises(RuntimeError, match="produced no result"):
        asyncio.run(client.call_tool("run_outreach_pipeline", {}))
