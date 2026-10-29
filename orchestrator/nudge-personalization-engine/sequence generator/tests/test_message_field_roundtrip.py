"""
Round-trip test for message generation fields.

Proves that language, research_signals, and personality_config survive the full path:
  Temporal activity (message_activities.py)
  → MCP client (mcp_client.py)
  → MCP server handler (mcp_server.py) — tested via source inspection
  → PipelineOrchestrator constructor

This test avoids importing the full Message Generator app (which has env var conflicts)
and instead tests the field passthrough at each layer independently.
"""

import sys
import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

# ── Package registration ──────────────────────────────────────────
_TESTS_DIR = Path(__file__).resolve().parent
_SEQ_GEN_DIR = _TESTS_DIR.parent

if str(_SEQ_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_SEQ_GEN_DIR))

import importlib
import importlib.util


def _load_pkg(pkg_name, pkg_dir):
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
    for _sub in ["config", "models", "graph", "graph.nodes", "tools", "observability", "middleware", "workflows"]:
        _path = _SEQ_GEN_DIR / _sub
        if _path.exists():
            _load_pkg(f"sequence_generator.{_sub}", _path)


# ── Test data ──────────────────────────────────────────────────────

SAMPLE_LANGUAGE = "fr"

SAMPLE_RESEARCH_SIGNALS = [
    {
        "type": "company_news",
        "content": "Acme Corp raised Series B at $50M",
        "strength": "strong",
        "why_relevant": "Recent funding indicates expansion plans and budget for new tools",
        "source_url": "https://example.com/acme-series-b",
    },
    {
        "type": "job_change",
        "content": "Jane Doe promoted to VP of Sales",
        "strength": "medium",
        "why_relevant": "New leadership often seeks fresh approaches",
    },
]

SAMPLE_PERSONALITY_CONFIG = {
    "base_template": "consultative",
    "personality_traits": ["empathetic", "direct", "data-driven"],
    "always_include_phrases": ["ROI", "time-to-value"],
    "never_use_phrases": ["synergy", "disrupt"],
    "touchdowns_per_message": 3,
    "urgency_level": 7,
}


class TestMCPClientFieldPassthrough:
    """Test that the MCP client includes all 3 fields in tool_args."""

    def test_personality_config_included_in_tool_args(self):
        """Verify personality_config is now included in MCP tool_args
        (was previously dropped silently)."""
        from sequence_generator.tools.mcp_client import MessageGeneratorMCPClient

        captured_args = {}

        async def mock_call_tool(self_client, session, arguments):
            captured_args.update(arguments)
            return {"success": True, "message": "test", "score": 80}

        client = MessageGeneratorMCPClient()
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        with patch.object(MessageGeneratorMCPClient, '_call_tool', mock_call_tool):
            with patch("sequence_generator.tools.mcp_client.sse_client") as mock_sse:
                # Set up the async context manager chain
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                cm.__aexit__ = AsyncMock(return_value=None)
                mock_sse.return_value = cm

                with patch("sequence_generator.tools.mcp_client.ClientSession") as mock_cs:
                    session_cm = AsyncMock()
                    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                    session_cm.__aexit__ = AsyncMock(return_value=None)
                    mock_cs.return_value = session_cm

                    import asyncio
                    result = asyncio.run(client.generate_outreach(
                        target_prospect="Jane Doe",
                        target_company="Acme Corp",
                        company_name="TestCo",
                        offer_name="Demo",
                        language=SAMPLE_LANGUAGE,
                        research_signals=SAMPLE_RESEARCH_SIGNALS,
                        personality_config=SAMPLE_PERSONALITY_CONFIG,
                        user_notes="Test notes",
                    ))

        assert "language" in captured_args, "language missing from MCP tool_args"
        assert captured_args["language"] == SAMPLE_LANGUAGE

        assert "research_signals" in captured_args, "research_signals missing from MCP tool_args"
        assert captured_args["research_signals"] == SAMPLE_RESEARCH_SIGNALS

        assert "personality_config" in captured_args, "personality_config missing from MCP tool_args"
        assert captured_args["personality_config"] == SAMPLE_PERSONALITY_CONFIG


class TestTemporalActivityFieldPopulation:
    """Test that generate_message_activity populates all 3 fields in step_context."""

    def test_activity_populates_research_signals(self):
        """Verify generate_message_activity populates research_signals in
        step_context from detective_data."""
        from sequence_generator.workflows.message_activities import generate_message_activity

        captured_step_context = {}

        def mock_generate_sync(step_context):
            captured_step_context.update(step_context)
            return {"success": True, "message": "test", "score": 80}

        input_data = {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "detective_data": {
                "company_name": "Acme Corp",
                "selected_persona": {"full_name": "Jane Doe", "job_title": "VP Sales"},
                "offer_context": "Enterprise plan",
                "research_signals": SAMPLE_RESEARCH_SIGNALS,
            },
            "strategy": {
                "detected_language": "en",
            },
            "feedback": None,
        }

        with patch("tools.mcp_client.generate_message_for_step_sync",
                    side_effect=mock_generate_sync, create=True):
            import asyncio
            result = asyncio.run(generate_message_activity(input_data))

        assert "research_signals" in captured_step_context, \
            "research_signals was not populated in step_context by the Temporal activity"
        assert captured_step_context["research_signals"] == SAMPLE_RESEARCH_SIGNALS

    def test_activity_populates_personality_config_from_strategy(self):
        """Verify generate_message_activity populates personality_config in
        step_context from strategy's personality_analysis (dict form)."""
        from sequence_generator.workflows.message_activities import generate_message_activity

        captured_step_context = {}

        def mock_generate_sync(step_context):
            captured_step_context.update(step_context)
            return {"success": True, "message": "test", "score": 80}

        input_data = {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "detective_data": {
                "company_name": "Acme Corp",
                "selected_persona": {"full_name": "Jane Doe"},
                "offer_context": "Enterprise plan",
            },
            "strategy": {
                "detected_language": "en",
                "personality_analysis": {
                    "base_template": "value_based",
                    "personality_traits": ["analytical", "concise"],
                    "urgency_level": 5,
                },
            },
            "feedback": None,
        }

        with patch("tools.mcp_client.generate_message_for_step_sync",
                    side_effect=mock_generate_sync, create=True):
            import asyncio
            result = asyncio.run(generate_message_activity(input_data))

        assert "personality_config" in captured_step_context, \
            "personality_config was not populated in step_context by the Temporal activity"
        assert captured_step_context["personality_config"]["base_template"] == "value_based"
        assert captured_step_context["personality_config"]["personality_traits"] == ["analytical", "concise"]

    def test_activity_populates_personality_config_from_string(self):
        """Verify generate_message_activity handles personality_analysis as string."""
        from sequence_generator.workflows.message_activities import generate_message_activity

        captured_step_context = {}

        def mock_generate_sync(step_context):
            captured_step_context.update(step_context)
            return {"success": True, "message": "test", "score": 80}

        input_data = {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "detective_data": {
                "company_name": "Acme Corp",
                "selected_persona": {"full_name": "Jane Doe"},
                "offer_context": "Enterprise plan",
            },
            "strategy": {
                "detected_language": "en",
                "personality_analysis": "Be very consultative and data-driven",
            },
            "feedback": None,
        }

        with patch("tools.mcp_client.generate_message_for_step_sync",
                    side_effect=mock_generate_sync, create=True):
            import asyncio
            result = asyncio.run(generate_message_activity(input_data))

        assert "personality_config" in captured_step_context
        assert captured_step_context["personality_config"]["custom_template_description"] == \
            "Be very consultative and data-driven"

    def test_activity_populates_message_language(self):
        """Verify generate_message_activity populates message_language from strategy."""
        from sequence_generator.workflows.message_activities import generate_message_activity

        captured_step_context = {}

        def mock_generate_sync(step_context):
            captured_step_context.update(step_context)
            return {"success": True, "message": "Bonjour!", "score": 90}

        input_data = {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "detective_data": {
                "company_name": "Acme Corp",
                "selected_persona": {"full_name": "Jean-Pierre"},
                "offer_context": "Enterprise plan",
            },
            "strategy": {
                "detected_language": "fr",
            },
            "feedback": None,
        }

        with patch("tools.mcp_client.generate_message_for_step_sync",
                    side_effect=mock_generate_sync, create=True):
            import asyncio
            result = asyncio.run(generate_message_activity(input_data))

        assert captured_step_context.get("message_language") == "fr"


class TestMCPServerFieldHandling:
    """Test the MCP server's field handling by reading the source code.
    
    We avoid importing the full Message Generator app (which has env var conflicts)
    and instead verify the handler logic by inspecting the source.
    """

    def test_mcp_server_reads_personality_config(self):
        """Verify mcp_server.py reads personality_config from arguments."""
        mcp_server_path = _SEQ_GEN_DIR.parent / "message generator and sender" / "app" / "mcp_server.py"
        source = mcp_server_path.read_text(encoding="utf-8")

        # Verify the handler reads personality_config
        assert 'arguments.get("personality_config")' in source, \
            "mcp_server.py does not read personality_config from arguments"

        # Verify it constructs Personality from the config
        assert "Personality(" in source, \
            "mcp_server.py does not construct a Personality object"
        assert "personality_config.get(" in source, \
            "mcp_server.py does not extract fields from personality_config"

    def test_mcp_server_reads_research_signals(self):
        """Verify mcp_server.py reads research_signals from arguments."""
        mcp_server_path = _SEQ_GEN_DIR.parent / "message generator and sender" / "app" / "mcp_server.py"
        source = mcp_server_path.read_text(encoding="utf-8")

        assert 'arguments.get("research_signals")' in source, \
            "mcp_server.py does not read research_signals from arguments"
        assert "Signal(" in source, \
            "mcp_server.py does not construct Signal objects from research_signals"
        assert "research_signals=research_signals" in source, \
            "mcp_server.py does not pass research_signals to PipelineOrchestrator"

    def test_mcp_server_schema_includes_new_fields(self):
        """Verify the MCP tool's inputSchema includes language, research_signals, personality_config."""
        mcp_server_path = _SEQ_GEN_DIR.parent / "message generator and sender" / "app" / "mcp_server.py"
        source = mcp_server_path.read_text(encoding="utf-8")

        assert '"language"' in source, "inputSchema missing 'language' field"
        assert '"research_signals"' in source, "inputSchema missing 'research_signals' field"
        assert '"personality_config"' in source, "inputSchema missing 'personality_config' field"


class TestFullRoundTrip:
    """End-to-end test: all 3 fields survive from Temporal activity through MCP client."""

    def test_all_fields_survive_activity_to_mcp_client(self):
        """
        Verify that when the Temporal activity populates step_context with
        language, research_signals, and personality_config, these fields
        are passed through to the MCP client's generate_message_for_step_sync.
        """
        from sequence_generator.workflows.message_activities import generate_message_activity

        captured_step_context = {}

        def mock_generate_sync(step_context):
            captured_step_context.update(step_context)
            return {"success": True, "message": "Bonjour!", "subject": "Test", "score": 90}

        input_data = {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "detective_data": {
                "company_name": "Acme Corp",
                "selected_persona": {"full_name": "Jean-Pierre", "job_title": "Directeur"},
                "offer_context": "Enterprise plan",
                "research_signals": SAMPLE_RESEARCH_SIGNALS,
            },
            "strategy": {
                "detected_language": "fr",
                "personality_analysis": SAMPLE_PERSONALITY_CONFIG,
            },
            "feedback": None,
        }

        with patch("tools.mcp_client.generate_message_for_step_sync",
                    side_effect=mock_generate_sync, create=True):
            import asyncio
            result = asyncio.run(generate_message_activity(input_data))

        # Verify all 3 fields survived from activity to MCP client call
        assert captured_step_context.get("message_language") == "fr", \
            f"language not passed through: got {captured_step_context.get('message_language')}"
        assert captured_step_context.get("research_signals") == SAMPLE_RESEARCH_SIGNALS, \
            "research_signals not passed through activity"
        assert captured_step_context.get("personality_config") == SAMPLE_PERSONALITY_CONFIG, \
            "personality_config not passed through activity"

        # Verify the result
        assert result["success"] is True
        assert result["message"] == "Bonjour!"


class TestLanguageFieldRoundTrip:
    """Test that message_language survives the full chain to the Gemini prompt."""

    @staticmethod
    def _import_msg_gen():
        """Import Message Generator modules with env isolation.
        Mocks redis (not in seq gen venv) and sets GOOGLE_API_KEY."""
        import os
        # Mock redis — not installed in the Sequence Generator venv
        if 'redis' not in sys.modules:
            sys.modules['redis'] = MagicMock()
        # Mock json5 — not installed in the Sequence Generator venv
        if 'json5' not in sys.modules:
            import json
            mock_json5 = MagicMock()
            mock_json5.loads = json.loads
            sys.modules['json5'] = mock_json5
        # Add message generator to path
        msg_gen_dir = _SEQ_GEN_DIR.parent / "message generator and sender"
        if str(msg_gen_dir) not in sys.path:
            sys.path.insert(0, str(msg_gen_dir))
        # Set required env vars
        os.environ["GOOGLE_API_KEY"] = "test-key"
        import app.models as models_mod
        import app.orchestrator as orch_mod
        import app.llm_service as llm_mod
        return models_mod, orch_mod, llm_mod

    def test_language_reaches_mcp_client_tool_args(self):
        """Verify language is included in MCP tool_args."""
        from sequence_generator.tools.mcp_client import MessageGeneratorMCPClient

        captured_args = {}

        async def mock_call_tool(self_client, session, arguments):
            captured_args.update(arguments)
            return {"success": True, "message": "Bonjour!", "score": 90}

        client = MessageGeneratorMCPClient()
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        with patch.object(MessageGeneratorMCPClient, '_call_tool', mock_call_tool):
            with patch("sequence_generator.tools.mcp_client.sse_client") as mock_sse:
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                cm.__aexit__ = AsyncMock(return_value=None)
                mock_sse.return_value = cm

                with patch("sequence_generator.tools.mcp_client.ClientSession") as mock_cs:
                    session_cm = AsyncMock()
                    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                    session_cm.__aexit__ = AsyncMock(return_value=None)
                    mock_cs.return_value = session_cm

                    import asyncio
                    result = asyncio.run(client.generate_outreach(
                        target_prospect="Jean-Pierre",
                        target_company="Acme Corp",
                        company_name="TestCo",
                        offer_name="Demo",
                        language="fr",
                    ))

        assert captured_args.get("language") == "fr", \
            "language was not included in MCP tool_args"

    def test_orchestrator_stores_language_on_agent_state(self):
        """Actually construct a PipelineOrchestrator with language='fr' and
        verify initial_state.language is set correctly."""
        models_mod, orch_mod, _ = self._import_msg_gen()

        orch = orch_mod.PipelineOrchestrator(
            target_prospect="Jean-Pierre",
            target_company="Acme Corp",
            prospect_role="Directeur",
            channel=models_mod.Channel.EMAIL,
            intent=models_mod.Intent.DIRECT_OUTREACH,
            stage=models_mod.Stage.FIRST_TOUCH,
            personality=models_mod.Personality(),
            company_details=models_mod.CompanyDetails(
                company_name="TestCo",
                elevator_pitch="We do things",
            ),
            selected_offer=models_mod.SelectedOffer(
                offer_name="Demo",
                solution_summary="A demo",
                cta="Book a call",
            ),
            language="fr",
        )

        assert orch.initial_state.language == "fr", \
            f"PipelineOrchestrator did not store language on AgentState: got {orch.initial_state.language!r}"

    def test_agent_state_language_field_roundtrip(self):
        """Actually construct an AgentState with language='de' and verify
        the field is stored and serialised correctly."""
        models_mod, _, _ = self._import_msg_gen()

        state = models_mod.AgentState(
            task_id="test-123",
            target_prospect="Hans",
            target_company="Acme GmbH",
            language="de",
        )

        assert state.language == "de", \
            f"AgentState.language not stored: got {state.language!r}"

        # Verify it survives model_dump (used by LangGraph graph state conversion)
        dumped = state.model_dump()
        assert dumped.get("language") == "de", \
            f"language lost during model_dump: got {dumped.get('language')!r}"

    def test_write_message_prompt_contains_language_instruction(self):
        """Actually call write_message() with language='fr' and verify the
        prompt sent to Gemini contains the OUTPUT LANGUAGE instruction."""
        models_mod, _, llm_mod = self._import_msg_gen()

        captured_prompt = {}

        def fake_call_llm(prompt, system_instruction=None, agent_step="unknown"):
            captured_prompt["prompt"] = prompt
            captured_prompt["system_instruction"] = system_instruction
            return '{"body": "Bonjour", "subject": "Test", "sentence_breakdown": []}'

        with patch.object(llm_mod.LLMService, '_call_llm', side_effect=fake_call_llm):
            strategy = models_mod.Strategy(
                primary_hook="Test hook",
                secondary_hook="Secondary",
                angle="Test angle",
                tone="soft_sell",
                cta_style="soft_question",
                reasoning="Test",
            )
            llm_mod.llm_service.write_message(
                strategy=strategy,
                prospect_name="Jean-Pierre",
                company="Acme Corp",
                prospect_role="Directeur",
                personality=models_mod.Personality(),
                company_details=models_mod.CompanyDetails(
                    company_name="TestCo",
                    elevator_pitch="We do things",
                ),
                selected_offer=models_mod.SelectedOffer(
                    offer_name="Demo",
                    solution_summary="A demo",
                    cta="Book a call",
                ),
                channel=models_mod.Channel.EMAIL,
                intent=models_mod.Intent.DIRECT_OUTREACH,
                stage=models_mod.Stage.FIRST_TOUCH,
                language="fr",
            )

        prompt = captured_prompt.get("prompt", "")
        assert "OUTPUT LANGUAGE" in prompt, \
            f"write_message prompt does not contain OUTPUT LANGUAGE instruction. Prompt: {prompt[:200]}..."
        assert "fr" in prompt, \
            f"write_message prompt does not mention 'fr'. Prompt: {prompt[:200]}..."

    def test_create_strategy_prompt_contains_language_instruction(self):
        """Actually call create_strategy() with language='fr' and verify the
        prompt sent to Gemini contains the OUTPUT LANGUAGE instruction."""
        models_mod, _, llm_mod = self._import_msg_gen()

        captured_prompt = {}

        def fake_call_llm(prompt, system_instruction=None, agent_step="unknown"):
            captured_prompt["prompt"] = prompt
            return '{"angle": "Test angle", "reasoning": "Test"}'

        with patch.object(llm_mod.LLMService, '_call_llm', side_effect=fake_call_llm):
            llm_mod.llm_service.create_strategy(
                primary_hook="Test hook",
                secondary_hook="Secondary",
                prospect_name="Jean-Pierre",
                company="Acme Corp",
                prospect_role="Directeur",
                personality=models_mod.Personality(),
                company_details=models_mod.CompanyDetails(
                    company_name="TestCo",
                    elevator_pitch="We do things",
                ),
                selected_offer=models_mod.SelectedOffer(
                    offer_name="Demo",
                    solution_summary="A demo",
                    cta="Book a call",
                ),
                channel=models_mod.Channel.EMAIL,
                intent=models_mod.Intent.DIRECT_OUTREACH,
                stage=models_mod.Stage.FIRST_TOUCH,
                language="fr",
            )

        prompt = captured_prompt.get("prompt", "")
        assert "OUTPUT LANGUAGE" in prompt, \
            f"create_strategy prompt does not contain OUTPUT LANGUAGE instruction. Prompt: {prompt[:200]}..."
        assert "fr" in prompt, \
            f"create_strategy prompt does not mention 'fr'. Prompt: {prompt[:200]}..."
