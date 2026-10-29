"""
Regression tests verifying nothing broke after dead code removal.

Covers:
- tools.py: ResearchTools and ReasoningTools still work after get_crm_history
  and score_hook_relevance were removed
- memory.py: LearningMemoryService still works after record_successful_hook
  and record_failed_hook were removed; record_reply still updates hooks correctly
- models.py: AgentState no longer has llm_calls field
- graph.py: GraphState TypedDict no longer has llm_calls key
- llm_service.py: LLMService is importable and has the correct active methods
- agents.py: writer, strategist, critic run without referencing llm_calls
- memory feedback loop: worst_performing_hooks and offer_best_angles wired correctly
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    AgentState, GenerateRequest, Status, Channel, Intent, Stage,
    Personality, CompanyDetails, SelectedOffer, Signal,
    Strategy, MessageDraft, SentenceAttribution, Validation,
)
from app.graph import GraphState, _to_graph_state, _from_graph_state
from app.tools import ResearchTools, ReasoningTools
from app.memory import (
    LearningMemoryService, LearningMemoryRecord,
    ProspectMemoryService, OfferMemoryService, MemoryService,
)


# ── Helpers ───────────────────────────────────────────────────────

def _make_state(**kwargs) -> AgentState:
    defaults = dict(
        task_id="task_001",
        target_prospect="Alice",
        target_company="Acme",
        channel=Channel.LINKEDIN_DM,
        intent=Intent.DIRECT_OUTREACH,
        stage=Stage.FIRST_TOUCH,
        company_details=CompanyDetails(company_name="SellerCo"),
        selected_offer=SelectedOffer(offer_name="Demo", solution_summary="Audit", cta="Book call"),
        research_signals=[Signal(type="linkedin_post", content="Alice posted about AI.", strength="strong", why_relevant="Relevant")],
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


def _make_strategy() -> Strategy:
    return Strategy(
        primary_hook="Alice's AI post",
        secondary_hook="Acme expansion",
        angle="Peer-to-peer",
        tone="soft_sell",
        cta_style="soft_question",
        reasoning="Good match",
    )


def _make_draft(body="Hey Alice!") -> MessageDraft:
    return MessageDraft(
        body=body,
        subject=None,
        sentence_attribution=[SentenceAttribution(text=body, driven_by=["hook"], purpose="hook")],
    )


# ── 1. tools.py: surviving methods still work ─────────────────────

class TestToolsAfterCleanup:

    def test_reasoning_tools_detect_placeholder_still_works(self):
        assert ReasoningTools.detect_placeholder_text("Hi [Company], I'd love to connect") is True
        assert ReasoningTools.detect_placeholder_text("Hi Acme, I'd love to connect") is False

    def test_reasoning_tools_detect_overpersonalization_still_works(self):
        assert ReasoningTools.detect_overpersonalization("I've been watching your profile") is True
        assert ReasoningTools.detect_overpersonalization("I saw your recent LinkedIn post") is False

    def test_get_crm_history_does_not_exist(self):
        assert not hasattr(ResearchTools, "get_crm_history")

    def test_score_hook_relevance_does_not_exist(self):
        assert not hasattr(ReasoningTools, "score_hook_relevance")

    def test_research_tools_fetch_linkedin_posts_still_works(self):
        signals = ResearchTools.fetch_linkedin_posts("Alice", "Acme")
        assert isinstance(signals, list)
        assert len(signals) >= 1
        assert all(hasattr(s, "type") for s in signals)

    def test_research_tools_fetch_company_news_still_works(self):
        signals = ResearchTools.fetch_company_news("Acme")
        assert isinstance(signals, list)
        assert len(signals) >= 1


# ── 2. memory.py: LearningMemoryService after method removal ──────

class TestMemoryAfterCleanup:

    def setup_method(self):
        """Flush memory before each test to avoid cross-test pollution."""
        MemoryService.flush()

    def test_record_successful_hook_does_not_exist(self):
        assert not hasattr(LearningMemoryService, "record_successful_hook")

    def test_record_failed_hook_does_not_exist(self):
        assert not hasattr(LearningMemoryService, "record_failed_hook")

    def test_record_reply_still_promotes_hooks(self):
        LearningMemoryService.record_reply(
            hook="AI post hook",
            angle="peer angle",
            channel="linkedin_dm",
            stage="first_touch",
            sentiment="positive",
        )
        record = LearningMemoryService.get()
        assert "AI post hook" in record.best_performing_hooks
        assert "AI post hook" not in record.worst_performing_hooks

    def test_record_reply_still_demotes_hooks_on_negative(self):
        LearningMemoryService.record_reply(
            hook="bad hook",
            angle="bad angle",
            channel="email",
            stage="first_touch",
            sentiment="negative",
        )
        record = LearningMemoryService.get()
        assert "bad hook" in record.worst_performing_hooks

    def test_record_reply_promotes_angles(self):
        LearningMemoryService.record_reply(
            hook="hook",
            angle="ROI angle",
            channel="linkedin_dm",
            stage="first_touch",
            sentiment="positive",
        )
        record = LearningMemoryService.get()
        assert "ROI angle" in record.best_performing_angles

    def test_record_generation_still_works(self):
        LearningMemoryService.record_generation(
            quality_score=88,
            channel="linkedin_dm",
            stage="first_touch",
            template="soft_sell",
        )
        record = LearningMemoryService.get()
        assert record.total_messages_generated == 1
        assert record.avg_quality_score == 88.0

    def test_offer_record_usage_still_works(self):
        OfferMemoryService.record_usage(
            offer_name="Free Audit",
            channel="email",
            angle="ROI angle",
            prospect_role="VP Sales",
            quality_score=90,
        )
        record = OfferMemoryService.get("Free Audit")
        assert record is not None
        assert record.times_used == 1
        assert "ROI angle" in record.best_angles

    def test_prospect_mark_replied_feeds_learning(self):
        # Set up prospect with history
        ProspectMemoryService.record_outreach(
            name="Alice",
            company="Acme",
            channel="linkedin_dm",
            stage="first_touch",
            hook_used="funding round hook",
            angle_used="growth angle",
            offer_name="Demo",
            message_sent="Hey Alice!",
        )
        ProspectMemoryService.mark_replied(name="Alice", company="Acme", sentiment="positive")
        learning = LearningMemoryService.get()
        assert "funding round hook" in learning.best_performing_hooks


# ── 3. AgentState: llm_calls field removed ────────────────────────

class TestAgentStateAfterCleanup:

    def test_llm_calls_field_gone_from_agent_state(self):
        state = _make_state()
        assert not hasattr(state, "llm_calls")

    def test_agent_state_still_creates_correctly(self):
        state = _make_state()
        assert state.task_id == "task_001"
        assert state.target_prospect == "Alice"
        assert state.status == Status.PLANNING

    def test_agent_state_model_dump_has_no_llm_calls(self):
        state = _make_state()
        dumped = state.model_dump()
        assert "llm_calls" not in dumped


# ── 4. GraphState TypedDict: llm_calls removed ────────────────────

class TestGraphStateAfterCleanup:

    def test_llm_calls_not_in_graph_state_annotations(self):
        assert "llm_calls" not in GraphState.__annotations__

    def test_to_graph_state_has_no_llm_calls(self):
        state = _make_state()
        graph_dict = _to_graph_state(state)
        assert "llm_calls" not in graph_dict

    def test_roundtrip_without_llm_calls(self):
        state = _make_state(user_feedback="test note")
        graph_dict = _to_graph_state(state)
        restored = _from_graph_state(graph_dict)
        assert restored.target_prospect == "Alice"
        assert restored.user_feedback == "test note"


# ── 5. llm_service.py: active class importable, old class gone ────

class TestLLMServiceAfterCleanup:

    def test_llm_service_importable(self):
        from app.llm_service import LLMService, llm_service
        assert LLMService is not None
        assert llm_service is not None

    def test_llm_service_has_write_message(self):
        from app.llm_service import LLMService
        assert hasattr(LLMService, "write_message")

    def test_llm_service_has_analyze_research_signals(self):
        from app.llm_service import LLMService
        assert hasattr(LLMService, "analyze_research_signals")

    def test_llm_service_has_create_strategy(self):
        from app.llm_service import LLMService
        assert hasattr(LLMService, "create_strategy")

    def test_llm_service_has_validate_message(self):
        from app.llm_service import LLMService
        assert hasattr(LLMService, "validate_message")

    def test_write_message_accepts_user_notes(self):
        """write_message signature must include user_notes param."""
        import inspect
        from app.llm_service import LLMService
        sig = inspect.signature(LLMService.write_message)
        assert "user_notes" in sig.parameters

    def test_analyze_research_signals_accepts_worst_performing_hooks(self):
        """analyze_research_signals must accept worst_performing_hooks."""
        import inspect
        from app.llm_service import LLMService
        sig = inspect.signature(LLMService.analyze_research_signals)
        assert "worst_performing_hooks" in sig.parameters

    def test_create_strategy_accepts_offer_best_angles(self):
        """create_strategy must accept offer_best_angles."""
        import inspect
        from app.llm_service import LLMService
        sig = inspect.signature(LLMService.create_strategy)
        assert "offer_best_angles" in sig.parameters


# ── 6. Agents: writer/strategist/critic run without llm_calls ─────

class TestAgentsAfterCleanup:

    def test_strategist_runs_without_llm_calls(self):
        from app.agents import AgentNodes
        state = _make_state(status=Status.STRATEGIZING, memory={
            "hooks_already_used": [],
            "best_performing_hooks": ["AI hook"],
            "worst_performing_hooks": ["bad hook"],
            "best_performing_angles": [],
            "angles_already_tried": [],
            "offer_memory": {"best_angles": ["ROI angle"]},
        })

        def fake_analyze(**kwargs):
            return {"primary_hook": "AI hook", "secondary_hook": "funding", "reasoning": "good", "confidence": "high"}

        def fake_strategy(**kwargs):
            return _make_strategy()

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.analyze_research_signals.side_effect = fake_analyze
            mock_llm.create_strategy.side_effect = fake_strategy
            result = AgentNodes.strategist(state)

        assert result.strategy is not None
        assert result.status == Status.WRITING

    def test_strategist_passes_worst_hooks_to_analyze(self):
        from app.agents import AgentNodes
        state = _make_state(status=Status.STRATEGIZING, memory={
            "hooks_already_used": [],
            "best_performing_hooks": [],
            "worst_performing_hooks": ["spammy hook"],
            "best_performing_angles": [],
            "angles_already_tried": [],
        })
        captured = {}

        def fake_analyze(**kwargs):
            captured.update(kwargs)
            return {"primary_hook": "hook", "secondary_hook": "", "reasoning": "ok", "confidence": "high"}

        def fake_strategy(**kwargs):
            return _make_strategy()

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.analyze_research_signals.side_effect = fake_analyze
            mock_llm.create_strategy.side_effect = fake_strategy
            AgentNodes.strategist(state)

        assert captured.get("worst_performing_hooks") == ["spammy hook"]

    def test_strategist_passes_offer_best_angles_to_create_strategy(self):
        from app.agents import AgentNodes
        state = _make_state(status=Status.STRATEGIZING, memory={
            "hooks_already_used": [],
            "best_performing_hooks": [],
            "worst_performing_hooks": [],
            "best_performing_angles": [],
            "angles_already_tried": [],
            "offer_memory": {"best_angles": ["ROI angle", "pain point angle"]},
        })
        captured = {}

        def fake_analyze(**kwargs):
            return {"primary_hook": "hook", "secondary_hook": "", "reasoning": "ok", "confidence": "high"}

        def fake_strategy(**kwargs):
            captured.update(kwargs)
            return _make_strategy()

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.analyze_research_signals.side_effect = fake_analyze
            mock_llm.create_strategy.side_effect = fake_strategy
            AgentNodes.strategist(state)

        assert captured.get("offer_best_angles") == ["ROI angle", "pain point angle"]

    def test_writer_runs_without_llm_calls(self):
        from app.agents import AgentNodes
        state = _make_state(
            status=Status.WRITING,
            strategy=_make_strategy(),
            memory={"times_contacted_before": 0, "prospect_record": {}},
        )

        def fake_write(**kwargs):
            return {"body": "Hey Alice!", "subject": None, "sentence_breakdown": []}

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.write_message.side_effect = fake_write
            result = AgentNodes.writer(state)

        assert result.draft is not None
        assert result.draft.body == "Hey Alice!"
        assert result.status == Status.VALIDATING

    def test_critic_runs_without_llm_calls(self):
        from app.agents import AgentNodes
        state = _make_state(
            status=Status.VALIDATING,
            strategy=_make_strategy(),
            draft=_make_draft("Hey Alice, saw your post on AI automation!"),
        )

        def fake_validate(**kwargs):
            return {"score": 85, "warnings": [], "suggested_fixes": None, "valid": True}

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.validate_message.side_effect = fake_validate
            result = AgentNodes.critic(state)

        assert result.validation is not None
        assert result.validation.score == 85


# ── 7. Pipeline: full graph still runs end-to-end ─────────────────

class TestPipelineAfterCleanup:

    def test_run_pipeline_returns_history(self):
        from app.graph import run_pipeline
        state = _make_state()

        def fake_analyze(**kwargs):
            return {"primary_hook": "AI hook", "secondary_hook": "", "reasoning": "ok", "confidence": "high"}

        def fake_strategy(**kwargs):
            return _make_strategy()

        def fake_write(**kwargs):
            return {"body": "Hey Alice!", "subject": None, "sentence_breakdown": []}

        def fake_validate(**kwargs):
            return {"score": 88, "warnings": [], "suggested_fixes": None, "valid": True}

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.analyze_research_signals.side_effect = fake_analyze
            mock_llm.create_strategy.side_effect = fake_strategy
            mock_llm.write_message.side_effect = fake_write
            mock_llm.validate_message.side_effect = fake_validate
            history = run_pipeline(state)

        assert len(history) >= 2
        final = history[-1]
        assert final.status in (Status.COMPLETE, Status.AWAITING_HUMAN)
        assert final.draft is not None
        assert final.draft.body == "Hey Alice!"

    def test_no_llm_calls_attribute_on_final_state(self):
        from app.graph import run_pipeline
        state = _make_state()

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.analyze_research_signals.return_value = {"primary_hook": "hook", "secondary_hook": "", "reasoning": "ok", "confidence": "high"}
            mock_llm.create_strategy.return_value = _make_strategy()
            mock_llm.write_message.return_value = {"body": "Hi!", "subject": None, "sentence_breakdown": []}
            mock_llm.validate_message.return_value = {"score": 85, "warnings": [], "suggested_fixes": None, "valid": True}
            history = run_pipeline(state)

        final = history[-1]
        assert not hasattr(final, "llm_calls")
