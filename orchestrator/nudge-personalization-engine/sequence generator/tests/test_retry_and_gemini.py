"""
Tests for sequence generator Gemini retry / fallback logic.

Covers:
- _gemini_rate_limit_backoff: exponential sleep
- _call_gemini_with_json_response: primary failure triggers fallback
- _call_gemini_with_json_response: both fail returns error JSON
- _call_gemini_with_json_response: PromptRecord recorded on success
- _call_gemini_with_json_response: PromptRecord recorded on failure
- _call_gemini_with_json_response: markdown stripping
- Token counter increments on Gemini calls
- Missing API key returns error JSON immediately
"""

import sys
import os
import json
import importlib
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# ── Package registration ──────────────────────────────────────────
_TESTS_DIR = Path(__file__).resolve().parent
_SEQ_GEN_DIR = _TESTS_DIR.parent

if str(_SEQ_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_SEQ_GEN_DIR))


def _load_pkg(pkg_name: str, pkg_dir: Path):
    init = pkg_dir / "__init__.py"
    if not init.exists():
        init.write_text("")
    spec = importlib.util.spec_from_file_location(
        pkg_name, str(init),
        submodule_search_locations=[str(pkg_dir)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "sequence_generator" not in sys.modules:
    _load_pkg("sequence_generator", _SEQ_GEN_DIR)
    for _sub in ["config", "models", "graph", "graph.nodes", "tools", "observability", "middleware"]:
        _p = _SEQ_GEN_DIR / _sub.replace(".", "/")
        if _p.is_dir():
            _load_pkg(f"sequence_generator.{_sub}", _p)

import sequence_generator.graph.nodes.sequence_generator_node as node_mod
import sequence_generator.observability.observability_store as obs_mod
from sequence_generator.graph.state import GraphState
from sequence_generator.config.constants import DEFAULT_MAX_TOUCHES, MAX_RETRIES, SAFE_FALLBACK_SEQUENCE
from sequence_generator.graph.builder import _build_workflow
from langgraph.checkpoint.memory import MemorySaver


def _mock_success_response(text: str, prompt_tokens: int = 100, candidate_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidate_tokens,
        }
    }
    resp.raise_for_status = MagicMock()
    return resp


# ── 1. Rate limit backoff ─────────────────────────────────────────

class TestRateLimitBackoff:

    def test_exponential_sleep_values(self):
        """Backoff sleeps 2^attempt seconds, capped at 60."""
        sleep_calls = []
        with patch("sequence_generator.graph.nodes.sequence_generator_node.time.sleep",
                   side_effect=lambda s: sleep_calls.append(s)):
            node_mod._gemini_rate_limit_backoff(0)
            node_mod._gemini_rate_limit_backoff(1)
            node_mod._gemini_rate_limit_backoff(2)
            node_mod._gemini_rate_limit_backoff(3)
            node_mod._gemini_rate_limit_backoff(10)  # should cap at 60

        assert sleep_calls[0] == 1
        assert sleep_calls[1] == 2
        assert sleep_calls[2] == 4
        assert sleep_calls[3] == 8
        assert sleep_calls[4] == 60  # 2^10=1024 capped at 60


# ── 2. _call_gemini_with_json_response: model fallback ───────────

class TestGeminiCallFallback:

    def setup_method(self):
        obs_mod.prompt_store.clear()

    def test_success_returns_text(self):
        """Successful call returns the response text."""
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response('{"steps": []}')):
            result = node_mod._call_gemini_with_json_response("test", correlation_id="test")
        assert result == '{"steps": []}'

    def test_primary_failure_triggers_fallback(self):
        """RequestException on primary triggers recursive fallback call."""
        import requests as req_lib
        call_log = []

        def fake_post(url, headers, json, timeout):
            call_log.append(url)
            if "gemma" in url or node_mod.GEMINI_FALLBACK_MODEL in url:
                return _mock_success_response('{"fallback": true}')
            raise req_lib.exceptions.RequestException("primary down")

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=fake_post):
            result = node_mod._call_gemini_with_json_response("test", use_fallback=False, correlation_id="t")

        # Two calls: primary (failed) + fallback (success)
        assert len(call_log) == 2
        assert '{"fallback": true}' == result

    def test_both_fail_returns_error_json(self):
        """When both primary and fallback fail, returns error JSON string."""
        import requests as req_lib
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=req_lib.exceptions.RequestException("down")):
            result = node_mod._call_gemini_with_json_response("test", use_fallback=False, correlation_id="t")

        parsed = json.loads(result)
        assert "error" in parsed

    def test_fallback_called_directly_returns_error_on_failure(self):
        """use_fallback=True with failure returns error JSON (no further recursion)."""
        import requests as req_lib
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=req_lib.exceptions.RequestException("fallback also down")):
            result = node_mod._call_gemini_with_json_response("test", use_fallback=True, correlation_id="t")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "fallback also failed" in parsed["error"]

    def test_missing_api_key_returns_error_immediately(self):
        """Empty GOOGLE_API_KEY returns error JSON without calling API."""
        original = node_mod.GOOGLE_API_KEY
        node_mod.GOOGLE_API_KEY = ""
        try:
            with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post") as mock_post:
                result = node_mod._call_gemini_with_json_response("test", correlation_id="t")
                mock_post.assert_not_called()
        finally:
            node_mod.GOOGLE_API_KEY = original

        parsed = json.loads(result)
        assert "error" in parsed

    def test_markdown_stripped_from_response(self):
        """Gemini markdown code fences are stripped from the response text."""
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response('```json\n{"steps": []}\n```')):
            result = node_mod._call_gemini_with_json_response("test", correlation_id="t")
        assert result == '{"steps": []}'

    def test_json_parse_error_returns_error_json(self):
        """Malformed JSON response (KeyError on parsing) returns error JSON."""
        bad_resp = MagicMock()
        bad_resp.json.return_value = {"unexpected": "structure"}  # no 'candidates' key
        bad_resp.raise_for_status = MagicMock()

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=bad_resp):
            result = node_mod._call_gemini_with_json_response("test", correlation_id="t")

        parsed = json.loads(result)
        assert "error" in parsed


# ── 3. PromptRecord recorded on every call ────────────────────────

class TestPromptRecordOnGeminiCall:

    def setup_method(self):
        obs_mod.prompt_store.clear()

    def test_record_written_on_success(self):
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response('{"steps": []}')):
            node_mod._call_gemini_with_json_response("hello world", correlation_id="lead_001")

        records = obs_mod.prompt_store.get_history(limit=10)
        assert len(records) == 1
        r = records[0]
        assert r["module"] == "sequence_generator"
        assert r["success"] is True
        assert r["tokens_in"] > 0
        assert r["tokens_out"] > 0

    def test_no_record_written_on_primary_failure(self):
        """Failed calls are NOT recorded (no double-counting policy)."""
        import requests as req_lib
        before = len(obs_mod.prompt_store.get_history(limit=1000))
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=req_lib.exceptions.RequestException("fail")):
            node_mod._call_gemini_with_json_response("test", use_fallback=True, correlation_id="t")

        after = len(obs_mod.prompt_store.get_history(limit=1000))
        assert after == before  # No new record

    def test_model_used_primary_vs_fallback(self):
        """model_used field reflects which model was actually called."""
        # Primary success → model_used = "primary"
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response('{"ok": true}')):
            node_mod._call_gemini_with_json_response("test", use_fallback=False, correlation_id="t")

        r_primary = obs_mod.prompt_store.get_history(limit=1)[0]
        assert r_primary["model_used"] == "primary"

        obs_mod.prompt_store.clear()

        # Fallback call → model_used = "fallback"
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response('{"ok": true}')):
            node_mod._call_gemini_with_json_response("test", use_fallback=True, correlation_id="t")

        r_fallback = obs_mod.prompt_store.get_history(limit=1)[0]
        assert r_fallback["model_used"] == "fallback"


# ── 4. Token counter ──────────────────────────────────────────────

class TestTokenCounterOnGeminiCall:

    def test_tokens_in_from_provider_usage(self):
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response("one two three", prompt_tokens=42, candidate_tokens=10)):
            node_mod._call_gemini_with_json_response("word1 word2 word3 word4", correlation_id="t")

        r = obs_mod.prompt_store.get_history(limit=1)[0]
        assert r["tokens_in"] == 42

    def test_tokens_out_from_provider_usage(self):
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response("alpha beta gamma delta epsilon", prompt_tokens=100, candidate_tokens=77)):
            node_mod._call_gemini_with_json_response("prompt", correlation_id="t")

        r = obs_mod.prompt_store.get_history(limit=1)[0]
        assert r["tokens_out"] == 77

    def test_no_record_on_failure(self):
        """Failed calls are NOT recorded (no double-counting policy)."""
        import requests as req_lib
        before = len(obs_mod.prompt_store.get_history(limit=1000))
        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=req_lib.exceptions.RequestException("fail")):
            node_mod._call_gemini_with_json_response("test", use_fallback=True, correlation_id="t")

        after = len(obs_mod.prompt_store.get_history(limit=1000))
        assert after == before  # No new record


# ── 5. Default max touches enforcement ─────────────────────────────

def _make_valid_step(step_number: int, wait: int = 86400) -> dict:
    """Helper to build a single valid step dict for JSON construction.
    Generates strictly increasing timestamps based on step_number."""
    from datetime import datetime, timedelta, timezone
    base = datetime(2025, 6, 20, 10, 0, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(days=step_number * 3)).isoformat()  # 3 days apart
    return {
        "step_number": step_number,
        "action_type": "EMAIL_1",
        "channel": "email",
        "scheduled_timestamp": ts,
        "wait_delay_seconds": wait,
        "timing_justification": "Monday morning is optimal for open rates across timezones.",
        "sequence_architecture_rationale": "Email introduction to establish initial contact with prospect.",
        "message_language": "en",
    }


def _make_state(**overrides) -> GraphState:
    """Helper to build a minimal GraphState for generate_sequence tests."""
    defaults = {
        "lead_id": "test_lead",
        "campaign_id": "test_campaign",
        "entreprise": "TestCorp",
        "contact_info": {"full_name": "John Doe", "country": "United States"},
        "contexte_web": {"profil_brut": "A test prospect for unit testing."},
    }
    defaults.update(overrides)
    return GraphState(**defaults)


class TestDefaultMaxTouchesEnforcement:

    def setup_method(self):
        obs_mod.prompt_store.clear()

    def test_default_max_touches_applied_when_not_specified(self):
        """When max_touches=None and Gemini returns more steps than DEFAULT_MAX_TOUCHES,
        the response is rejected (triggers retry/fallback), not silently accepted."""
        too_many_steps = [_make_valid_step(i + 1) for i in range(8)]
        sequence_json = json.dumps({
            "lead_id": "test_lead",
            "campaign_id": "test_campaign",
            "steps": too_many_steps,
        })

        state = _make_state(max_touches=None)

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response(sequence_json)), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_language_with_gemini_fallback",
                   return_value=("en", "English")), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_timezone_with_fallback",
                   return_value=(-5, "EST")), \
             patch.object(node_mod, "DEFAULT_MAX_TOUCHES", 5):

            result = node_mod.generate_sequence(state)

        # 8 steps > 5 (effective_max_touches), so validation should have failed.
        # generate_sequence runs once per call (retry loop is in the graph).
        # The response should be rejected with a validation error.
        assert result.validated_sequence is None
        assert result.retry_count == 1
        assert len(result.validation_errors) == 1
        assert "exceeds" in result.validation_errors[0].lower() or "maximum" in result.validation_errors[0].lower()

    def test_explicit_max_touches_overrides_default(self):
        """When max_touches=8 (higher than DEFAULT_MAX_TOUCHES=5), exactly 8 steps
        are accepted — the explicit value is NOT capped to the env default."""
        eight_steps = [_make_valid_step(i + 1) for i in range(8)]
        sequence_json = json.dumps({
            "lead_id": "test_lead",
            "campaign_id": "test_campaign",
            "steps": eight_steps,
        })

        state = _make_state(max_touches=8)

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   return_value=_mock_success_response(sequence_json)), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_language_with_gemini_fallback",
                   return_value=("en", "English")), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_timezone_with_fallback",
                   return_value=(-5, "EST")), \
             patch.object(node_mod, "DEFAULT_MAX_TOUCHES", 5):

            result = node_mod.generate_sequence(state)

        # 8 steps <= effective_max_touches (8), so accepted without fallback
        assert result.fallback_triggered is False
        assert result.validated_sequence is not None
        assert len(result.validated_sequence.steps) == 8
        assert len(result.validation_errors) == 0


# ── 6. Graph-level retry tests ─────────────────────────────────────

def _make_sequence_json(num_steps: int, lead_id: str = "test_lead", campaign_id: str = "test_campaign") -> str:
    """Build a valid sequence JSON with the given number of steps."""
    steps = [_make_valid_step(i + 1) for i in range(num_steps)]
    return json.dumps({
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "steps": steps,
    })


class TestGraphLevelRetrySuccess:
    """Test that the compiled graph retries on oversized sequences and eventually succeeds."""

    def setup_method(self):
        obs_mod.prompt_store.clear()

    def test_graph_retries_oversized_then_accepts_compliant(self):
        """Graph retries when Gemini returns oversized sequences, then accepts
        a compliant response on a subsequent call."""
        # First 2 calls return oversized (8 steps > 5 default)
        # Third call returns compliant (3 steps <= 5)
        oversized_json = _make_sequence_json(8)
        compliant_json = _make_sequence_json(3)

        call_count = [0]
        def mock_gemini_response(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return _mock_success_response(oversized_json)
            else:
                return _mock_success_response(compliant_json)

        # Build graph WITHOUT interrupt (for testing)
        workflow = _build_workflow()
        graph = workflow.compile(checkpointer=MemorySaver())

        initial_state = _make_state(max_touches=None)
        config = {"configurable": {"thread_id": "test_retry_success"}}

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=mock_gemini_response), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_language_with_gemini_fallback",
                   return_value=("en", "English")), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_timezone_with_fallback",
                   return_value=(-5, "EST")), \
             patch.object(node_mod, "DEFAULT_MAX_TOUCHES", 5):

            result = graph.invoke(initial_state.model_dump(), config)

        # Graph should have retried and eventually succeeded
        assert call_count[0] == 3, f"Expected 3 Gemini calls, got {call_count[0]}"
        assert result["validated_sequence"] is not None
        # validated_sequence is an OutreachSequence object, not a dict
        validated_seq = result["validated_sequence"]
        assert len(validated_seq.steps) == 3
        assert result["fallback_triggered"] is False
        # retry_count should be 0 because the successful call reset it
        assert result["retry_count"] == 0
        # But validation_errors should show the 2 previous failures
        assert len(result["validation_errors"]) == 2


class TestGraphLevelRetryExhaustion:
    """Test that the graph exhausts retries and falls back to SAFE_FALLBACK_SEQUENCE."""

    def setup_method(self):
        obs_mod.prompt_store.clear()

    def test_graph_falls_back_after_max_retries(self):
        """When Gemini always returns oversized sequences, graph retries MAX_RETRIES
        times then falls back to SAFE_FALLBACK_SEQUENCE."""
        # All calls return oversized (8 steps > 5 default)
        oversized_json = _make_sequence_json(8)

        call_count = [0]
        def mock_gemini_response(*args, **kwargs):
            call_count[0] += 1
            return _mock_success_response(oversized_json)

        # Build graph WITHOUT interrupt (for testing)
        workflow = _build_workflow()
        graph = workflow.compile(checkpointer=MemorySaver())

        initial_state = _make_state(max_touches=None)
        config = {"configurable": {"thread_id": "test_retry_exhaustion"}}

        with patch("sequence_generator.graph.nodes.sequence_generator_node.requests.post",
                   side_effect=mock_gemini_response), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_language_with_gemini_fallback",
                   return_value=("en", "English")), \
             patch("sequence_generator.graph.nodes.sequence_generator_node.detect_timezone_with_fallback",
                   return_value=(-5, "EST")), \
             patch.object(node_mod, "DEFAULT_MAX_TOUCHES", 5):

            result = graph.invoke(initial_state.model_dump(), config)

        # Graph should have retried MAX_RETRIES times (3)
        # Each retry makes 1 Gemini call, so total = MAX_RETRIES
        assert call_count[0] == MAX_RETRIES, f"Expected {MAX_RETRIES} Gemini calls, got {call_count[0]}"
        # Fallback should have been triggered
        assert result["fallback_triggered"] is True
        assert result["validated_sequence"] is not None
        # validated_sequence is an OutreachSequence object, not a dict
        validated_seq = result["validated_sequence"]
        # SAFE_FALLBACK_SEQUENCE has exactly 2 steps
        assert len(validated_seq.steps) == 2
        # 2 steps < 5 (DEFAULT_MAX_TOUCHES), so within limit
        assert len(validated_seq.steps) <= 5
        # All validation errors should mention exceeding the limit
        assert len(result["validation_errors"]) == MAX_RETRIES
        for err in result["validation_errors"]:
            assert "exceeds" in err.lower() or "maximum" in err.lower()
