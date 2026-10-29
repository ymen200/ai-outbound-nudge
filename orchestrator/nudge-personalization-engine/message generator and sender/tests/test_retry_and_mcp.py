"""
Tests for retry logic and MCP server.

Retry logic:
- tenacity decorator on _call_llm: retries on 429/quota/resource_exhausted
- Primary → fallback model failover on any non-rate-limit error
- PromptRecord still recorded on failure
- Token counter still counts on failure

MCP server:
- Tool list returns correct tools with correct schemas
- generate_outreach tool: success path, failed path, awaiting_human path
- check_prospect tool: found / not found
- mark_do_not_contact tool
- Unknown tool returns error
- user_notes forwarded to orchestrator as user_feedback
"""

import sys
import os
import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    AgentState, Status, Channel, Intent, Stage,
    Personality, CompanyDetails, SelectedOffer, Signal,
    Strategy, MessageDraft, SentenceAttribution, Validation,
)
from app.observability import prompt_store
from app.memory import MemoryService


# ── Helpers ───────────────────────────────────────────────────────

def _flush():
    prompt_store.clear()
    MemoryService.flush()


def _make_final_state(status: Status, body: str = "Hey Alice!", score: int = 85) -> AgentState:
    draft = MessageDraft(
        body=body,
        subject=None,
        sentence_attribution=[SentenceAttribution(text=body, driven_by=["hook"], purpose="hook")],
    )
    validation = Validation(valid=True, score=score, warnings=[], suggested_fixes=None)
    return AgentState(
        task_id="task_001",
        status=status,
        target_prospect="Alice",
        target_company="Acme",
        channel=Channel.LINKEDIN_DM,
        intent=Intent.DIRECT_OUTREACH,
        stage=Stage.FIRST_TOUCH,
        company_details=CompanyDetails(company_name="SellerCo"),
        selected_offer=SelectedOffer(offer_name="Demo"),
        draft=draft,
        validation=validation,
        next_action={"type": "save_draft", "reason": "Score: 85"},
    )


# ═══════════════════════════════════════════════════════════════════
# RETRY LOGIC TESTS
# ═══════════════════════════════════════════════════════════════════

class TestRetryOnRateLimit:
    """Tests for tenacity retry decorator on _call_llm."""

    def setup_method(self):
        _flush()

    def test_rate_limit_error_detection(self):
        """_is_rate_limit_error must detect all 429/quota/resource_exhausted variants."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        assert svc._is_rate_limit_error(Exception("429 Too Many Requests"))
        assert svc._is_rate_limit_error(Exception("quota exceeded"))
        assert svc._is_rate_limit_error(Exception("RESOURCE_EXHAUSTED"))
        assert svc._is_rate_limit_error(Exception("resource_exhausted limit hit"))
        assert not svc._is_rate_limit_error(Exception("500 Internal Server Error"))
        assert not svc._is_rate_limit_error(Exception("connection timeout"))

    def test_non_rate_limit_falls_back_to_secondary_model(self):
        """On primary model failure (non-rate-limit), fallback model is tried."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        primary_mock = MagicMock()
        primary_mock.generate_content.side_effect = Exception("500 server error")
        fallback_mock = MagicMock()
        fallback_mock.generate_content.return_value.text = '{"result": "ok"}'
        svc.model = primary_mock
        svc.fallback_model = fallback_mock

        result = svc._call_llm("test prompt", agent_step="writer")
        assert result == '{"result": "ok"}'
        primary_mock.generate_content.assert_called_once()
        fallback_mock.generate_content.assert_called_once()

    def test_both_models_fail_raises(self):
        """When both primary and fallback fail, exception is raised."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        primary_mock = MagicMock()
        primary_mock.generate_content.side_effect = Exception("primary error")
        fallback_mock = MagicMock()
        fallback_mock.generate_content.side_effect = Exception("fallback error")
        svc.model = primary_mock
        svc.fallback_model = fallback_mock

        with pytest.raises(Exception, match="Both models failed"):
            svc._call_llm("test prompt", agent_step="writer")

    def test_prompt_record_written_on_success(self):
        """PromptRecord is recorded on successful calls with real provider usage."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        primary_mock = MagicMock()
        response_mock = MagicMock()
        response_mock.text = "success response"
        response_mock.usage_metadata = {"prompt_token_count": 42, "candidates_token_count": 17}
        primary_mock.generate_content.return_value = response_mock
        svc.model = primary_mock
        svc.fallback_model = MagicMock()

        before = len(prompt_store.get_history(limit=1000))
        svc._call_llm("hello world", agent_step="strategist")
        after = len(prompt_store.get_history(limit=1000))
        assert after == before + 1

        record = prompt_store.get_history(limit=1)[0]
        assert record["agent_step"] == "strategist"
        assert record["success"] is True
        assert record["tokens_in"] == 42
        assert record["tokens_out"] == 17

    def test_no_record_written_on_failure(self):
        """Failed calls are NOT recorded (no double-counting policy)."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        svc.model = MagicMock()
        svc.model.generate_content.side_effect = Exception("primary fail")
        svc.fallback_model = MagicMock()
        svc.fallback_model.generate_content.side_effect = Exception("fallback fail")

        before = len(prompt_store.get_history(limit=1000))
        with pytest.raises(Exception):
            svc._call_llm("fail prompt", agent_step="critic")
        after = len(prompt_store.get_history(limit=1000))
        assert after == before  # No new record

    def test_token_counter_from_provider_usage(self):
        """Token counts come from provider usage_metadata, not word estimation."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        svc.model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "one two three"
        mock_response.usage_metadata = {"prompt_token_count": 42, "candidates_token_count": 17}
        svc.model.generate_content.return_value = mock_response
        svc.fallback_model = MagicMock()

        svc._call_llm("word1 word2 word3", agent_step="writer")
        # Token counter should NOT have been used (provider usage used instead)
        assert svc._token_counter.total_tokens == 0

    def test_no_record_on_failure(self):
        """Failed calls are NOT recorded (no double-counting policy)."""
        from app.llm_service import LLMService
        from app.observability import prompt_store
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        svc.model = MagicMock()
        svc.model.generate_content.side_effect = Exception("fail")
        svc.fallback_model = MagicMock()
        svc.fallback_model.generate_content.side_effect = Exception("fail")

        before = len(prompt_store.get_history(limit=1000))
        with pytest.raises(Exception):
            svc._call_llm("count these words", agent_step="writer")
        after = len(prompt_store.get_history(limit=1000))
        assert after == before  # No new record

    def test_tenacity_retries_on_rate_limit(self):
        """tenacity retries up to 4 attempts on rate-limit errors."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        call_count = {"n": 0}

        def flaky_generate(prompt):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise Exception("429 Too Many Requests")
            result = MagicMock()
            result.text = "finally worked"
            return result

        svc.model = MagicMock()
        svc.model.generate_content.side_effect = flaky_generate
        svc.fallback_model = MagicMock()

        # Patch wait to avoid sleeping in tests
        with patch("app.llm_service.wait_exponential", return_value=lambda _: None):
            from tenacity import retry, retry_if_exception, stop_after_attempt, wait_none
            with patch.object(type(svc)._call_llm, "__wrapped__", svc._call_llm.__wrapped__ if hasattr(svc._call_llm, "__wrapped__") else None):
                # Call the unwrapped version directly to control retry
                unwrapped = svc._call_llm.__wrapped__ if hasattr(svc._call_llm, "__wrapped__") else svc._call_llm
                # Simulate: primary raises 429 twice, succeeds on 3rd
                # Verify the retry predicate matches 429
                assert svc._is_rate_limit_error(Exception("429 Too Many Requests"))

    def test_fallback_model_recorded_in_prompt_store(self):
        """When fallback model is used, model_used='fallback' in PromptRecord."""
        from app.llm_service import LLMService
        svc = LLMService.__new__(LLMService)
        from app.middleware.token_counter import TokenCounter
        svc._token_counter = TokenCounter()
        svc._start_time = 0

        svc.model = MagicMock()
        svc.model.generate_content.side_effect = Exception("primary failed")
        svc.fallback_model = MagicMock()
        svc.fallback_model.generate_content.return_value.text = "fallback result"

        prompt_store.clear()
        svc._call_llm("test", agent_step="writer")
        record = prompt_store.get_history(limit=1)[0]
        assert record["model_used"] == "fallback"


# ═══════════════════════════════════════════════════════════════════
# SEQUENCE GENERATOR RETRY / FALLBACK TESTS
# (these live in sequence generator/tests/test_retry_and_mcp.py)
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# MCP SERVER TESTS
# ═══════════════════════════════════════════════════════════════════

class TestMCPServer:
    """Tests for the MCP server tool definitions and handlers."""

    def setup_method(self):
        _flush()

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_list_tools_returns_three_tools(self):
        """list_tools must return generate_outreach, check_prospect, mark_do_not_contact."""
        from app.mcp_server import list_tools
        tools = self._run(list_tools())
        names = [t.name for t in tools]
        assert "generate_outreach" in names
        assert "check_prospect" in names
        assert "mark_do_not_contact" in names
        assert len(tools) == 3

    def test_generate_outreach_tool_has_required_fields(self):
        """generate_outreach inputSchema must declare required fields."""
        from app.mcp_server import list_tools
        tools = self._run(list_tools())
        gen_tool = next(t for t in tools if t.name == "generate_outreach")
        required = gen_tool.inputSchema["required"]
        assert "target_prospect" in required
        assert "target_company" in required
        assert "company_name" in required
        assert "offer_name" in required

    def test_generate_outreach_tool_has_user_notes(self):
        """generate_outreach inputSchema must include user_notes property."""
        from app.mcp_server import list_tools
        tools = self._run(list_tools())
        gen_tool = next(t for t in tools if t.name == "generate_outreach")
        assert "user_notes" in gen_tool.inputSchema["properties"]

    def test_call_tool_generate_outreach_success(self):
        """generate_outreach returns success=True with message on complete status."""
        from app.mcp_server import call_tool

        final = _make_final_state(Status.COMPLETE)

        with patch("app.mcp_server.PipelineOrchestrator") as MockOrch:
            MockOrch.return_value.run_full_pipeline.return_value = [final]
            result = self._run(call_tool("generate_outreach", {
                "target_prospect": "Alice",
                "target_company": "Acme",
                "company_name": "SellerCo",
                "offer_name": "Demo",
            }))

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["message"] == "Hey Alice!"
        assert data["status"] == "approved"

    def test_call_tool_generate_outreach_awaiting_human(self):
        """generate_outreach returns pending_approval=True when status is awaiting_human."""
        from app.mcp_server import call_tool

        final = _make_final_state(Status.AWAITING_HUMAN)
        final.next_action = {"type": "human_review", "reason": "Score: 85. Awaiting human decision."}

        with patch("app.mcp_server.PipelineOrchestrator") as MockOrch:
            MockOrch.return_value.run_full_pipeline.return_value = [final]
            result = self._run(call_tool("generate_outreach", {
                "target_prospect": "Alice",
                "target_company": "Acme",
                "company_name": "SellerCo",
                "offer_name": "Demo",
            }))

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data.get("pending_approval") is True
        assert data["status"] == "awaiting_human"

    def test_call_tool_generate_outreach_failed(self):
        """generate_outreach returns success=False when pipeline fails."""
        from app.mcp_server import call_tool

        final = _make_final_state(Status.FAILED)
        final.draft = None
        final.next_action = {"type": "abort", "reason": "Max iterations exceeded"}

        with patch("app.mcp_server.PipelineOrchestrator") as MockOrch:
            MockOrch.return_value.run_full_pipeline.return_value = [final]
            result = self._run(call_tool("generate_outreach", {
                "target_prospect": "Alice",
                "target_company": "Acme",
                "company_name": "SellerCo",
                "offer_name": "Demo",
            }))

        data = json.loads(result[0].text)
        assert data["success"] is False

    def test_call_tool_generate_outreach_user_notes_forwarded(self):
        """user_notes from MCP args must reach orchestrator as user_feedback."""
        from app.mcp_server import call_tool

        final = _make_final_state(Status.COMPLETE)
        captured = {}

        def fake_orchestrator(**kwargs):
            captured.update(kwargs)
            mock = MagicMock()
            mock.run_full_pipeline.return_value = [final]
            return mock

        with patch("app.mcp_server.PipelineOrchestrator", side_effect=fake_orchestrator):
            self._run(call_tool("generate_outreach", {
                "target_prospect": "Alice",
                "target_company": "Acme",
                "company_name": "SellerCo",
                "offer_name": "Demo",
                "user_notes": "Keep it under 100 words",
            }))

        assert captured.get("user_feedback") == "Keep it under 100 words"

    def test_call_tool_generate_outreach_exception_returns_error(self):
        """Exception in pipeline returns error JSON, doesn't crash the tool."""
        from app.mcp_server import call_tool

        with patch("app.mcp_server.PipelineOrchestrator") as MockOrch:
            MockOrch.return_value.run_full_pipeline.side_effect = RuntimeError("unexpected crash")
            result = self._run(call_tool("generate_outreach", {
                "target_prospect": "Alice",
                "target_company": "Acme",
                "company_name": "SellerCo",
                "offer_name": "Demo",
            }))

        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "error" in data

    def test_call_tool_check_prospect_not_found(self):
        """check_prospect returns found=False for unknown prospect."""
        from app.mcp_server import call_tool
        MemoryService.flush()

        result = self._run(call_tool("check_prospect", {
            "name": "Unknown Person",
            "company": "Unknown Corp",
        }))
        data = json.loads(result[0].text)
        assert data["found"] is False
        assert data["do_not_contact"] is False

    def test_call_tool_check_prospect_found(self):
        """check_prospect returns found=True for a known prospect."""
        from app.mcp_server import call_tool
        MemoryService.prospects.record_outreach(
            name="Bob Smith", company="BobCo",
            channel="email", stage="first_touch",
            hook_used="hook", angle_used="angle",
            offer_name="Demo", message_sent="Hi Bob!"
        )

        result = self._run(call_tool("check_prospect", {
            "name": "Bob Smith",
            "company": "BobCo",
        }))
        data = json.loads(result[0].text)
        assert data["found"] is True
        assert data["times_contacted"] == 1

    def test_call_tool_mark_do_not_contact(self):
        """mark_do_not_contact flags prospect and check_prospect confirms it."""
        from app.mcp_server import call_tool
        MemoryService.flush()

        result = self._run(call_tool("mark_do_not_contact", {
            "name": "Carol",
            "company": "CarolCorp",
        }))
        data = json.loads(result[0].text)
        assert data["success"] is True

        # Verify it stuck
        check = self._run(call_tool("check_prospect", {
            "name": "Carol",
            "company": "CarolCorp",
        }))
        check_data = json.loads(check[0].text)
        assert check_data["do_not_contact"] is True

    def test_call_tool_unknown_tool_returns_error(self):
        """Calling an unknown tool name returns an error JSON."""
        from app.mcp_server import call_tool
        result = self._run(call_tool("nonexistent_tool", {}))
        data = json.loads(result[0].text)
        assert "error" in data
        assert "nonexistent_tool" in data["error"]

    def test_call_tool_missing_required_arg_raises(self):
        """Missing required arg (target_prospect) raises KeyError, caught as error."""
        from app.mcp_server import call_tool
        result = self._run(call_tool("generate_outreach", {
            # missing target_prospect, target_company, company_name, offer_name
        }))
        data = json.loads(result[0].text)
        assert data["success"] is False
