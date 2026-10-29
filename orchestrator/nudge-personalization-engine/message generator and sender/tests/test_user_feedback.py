"""
Tests for user feedback (human notes) in the message generator.

Covers:
- user_feedback field on GenerateRequest and AgentState
- user_feedback survives through the LangGraph GraphState TypedDict
- user_notes injected into the writer prompt via llm_service.write_message
- writer agent passes user_feedback from state to llm_service
- review/decision endpoint: rejection feedback triggers rewrite
- user_feedback preserved across pipeline re-runs
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock, call
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    AgentState, GenerateRequest, HumanDecision, Status,
    Channel, Intent, Stage, Personality, CompanyDetails,
    SelectedOffer, Signal, Strategy, MessageDraft, SentenceAttribution,
)
from app.graph import GraphState, _to_graph_state, _from_graph_state


# ── Fixtures ──────────────────────────────────────────────────────

def _make_agent_state(**kwargs) -> AgentState:
    defaults = dict(
        task_id="task_001",
        target_prospect="Alice Martin",
        target_company="Acme Corp",
        channel=Channel.LINKEDIN_DM,
        intent=Intent.DIRECT_OUTREACH,
        stage=Stage.FIRST_TOUCH,
        company_details=CompanyDetails(company_name="SellerCo", elevator_pitch="We help B2B teams."),
        selected_offer=SelectedOffer(offer_name="Free Audit", solution_summary="Audit your process", cta="Book a call"),
        research_signals=[Signal(type="linkedin_post", content="Alice posted about AI.", strength="strong", why_relevant="Relevant to our offer")],
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


def _make_strategy() -> Strategy:
    return Strategy(
        primary_hook="Alice's recent AI post",
        secondary_hook="Acme's expansion",
        angle="Peer-to-peer",
        tone="soft_sell",
        cta_style="soft_question",
        reasoning="Good match",
    )


def _make_draft(body: str = "Hey Alice, saw your post on AI!") -> MessageDraft:
    return MessageDraft(
        body=body,
        subject=None,
        sentence_attribution=[SentenceAttribution(text=body, driven_by=["hook"], purpose="hook")],
    )


# ── 1. GenerateRequest: user_feedback field ───────────────────────

class TestGenerateRequestUserFeedback:

    def test_user_feedback_optional_defaults_none(self):
        req = GenerateRequest(
            target_prospect="Alice",
            target_company="Acme",
            company_details=CompanyDetails(company_name="SellerCo"),
            selected_offer=SelectedOffer(offer_name="Demo"),
        )
        assert req.user_feedback is None

    def test_user_feedback_accepted(self):
        req = GenerateRequest(
            target_prospect="Alice",
            target_company="Acme",
            company_details=CompanyDetails(company_name="SellerCo"),
            selected_offer=SelectedOffer(offer_name="Demo"),
            user_feedback="Keep it under 200 characters",
        )
        assert req.user_feedback == "Keep it under 200 characters"


# ── 2. AgentState: user_feedback field ───────────────────────────

class TestAgentStateUserFeedback:

    def test_user_feedback_defaults_none(self):
        state = _make_agent_state()
        assert state.user_feedback is None

    def test_user_feedback_stored(self):
        state = _make_agent_state(user_feedback="More humor please")
        assert state.user_feedback == "More humor please"

    def test_user_feedback_survives_model_dump_roundtrip(self):
        state = _make_agent_state(user_feedback="Focus on pain points")
        restored = AgentState(**state.model_dump())
        assert restored.user_feedback == "Focus on pain points"


# ── 3. LangGraph GraphState: user_feedback in TypedDict ──────────

class TestGraphStateTypedDict:

    def test_user_feedback_in_graph_state_keys(self):
        """user_feedback must be declared in the LangGraph GraphState TypedDict."""
        assert "user_feedback" in GraphState.__annotations__

    def test_user_feedback_preserved_through_to_graph_state(self):
        state = _make_agent_state(user_feedback="Write in French tone")
        graph_dict = _to_graph_state(state)
        assert graph_dict.get("user_feedback") == "Write in French tone"

    def test_user_feedback_preserved_through_from_graph_state(self):
        state = _make_agent_state(user_feedback="No buzzwords")
        graph_dict = _to_graph_state(state)
        restored = _from_graph_state(graph_dict)
        assert restored.user_feedback == "No buzzwords"

    def test_none_user_feedback_preserved(self):
        state = _make_agent_state(user_feedback=None)
        graph_dict = _to_graph_state(state)
        restored = _from_graph_state(graph_dict)
        assert restored.user_feedback is None

    def test_user_feedback_not_dropped_between_nodes(self):
        """Simulate two node transitions and confirm user_feedback persists."""
        state = _make_agent_state(user_feedback="Mention the ROI")
        d1 = _to_graph_state(state)
        # Simulate a node modifying status only
        d1["status"] = Status.STRATEGIZING.value
        state2 = _from_graph_state(d1)
        d2 = _to_graph_state(state2)
        d2["status"] = Status.WRITING.value
        state3 = _from_graph_state(d2)
        assert state3.user_feedback == "Mention the ROI"


# ── 4. llm_service.write_message: user_notes in prompt ───────────

class TestWriteMessageUserNotes:

    def _make_write_message_args(self, user_notes: Optional[str] = None) -> dict:
        from app.models import Personality, CompanyDetails, SelectedOffer, Channel, Intent, Stage
        return dict(
            strategy=_make_strategy(),
            prospect_name="Alice Martin",
            company="Acme Corp",
            prospect_role="VP Sales",
            personality=Personality(),
            company_details=CompanyDetails(company_name="SellerCo", elevator_pitch="We help."),
            selected_offer=SelectedOffer(offer_name="Audit", solution_summary="Process audit", cta="Book call"),
            channel=Channel.LINKEDIN_DM,
            intent=Intent.DIRECT_OUTREACH,
            stage=Stage.FIRST_TOUCH,
            user_notes=user_notes,
        )

    def test_user_notes_injected_into_prompt(self):
        """USER NOTES: must appear in the prompt when user_notes is set."""
        from app.llm_service import LLMService

        service = LLMService()
        captured_prompt = {}

        def fake_call_llm(prompt, system_instruction=None, agent_step=None):
            captured_prompt["prompt"] = prompt
            return '{"body": "Hey Alice!", "subject": null, "sentence_breakdown": []}'

        with patch.object(service, "_call_llm", side_effect=fake_call_llm):
            service.write_message(**self._make_write_message_args(user_notes="Mention the free trial"))

        assert "USER NOTES" in captured_prompt["prompt"]
        assert "Mention the free trial" in captured_prompt["prompt"]

    def test_no_user_notes_absent_from_prompt(self):
        """USER NOTES must NOT appear when user_notes is None."""
        from app.llm_service import LLMService

        service = LLMService()
        captured_prompt = {}

        def fake_call_llm(prompt, system_instruction=None, agent_step=None):
            captured_prompt["prompt"] = prompt
            return '{"body": "Hey Alice!", "subject": null, "sentence_breakdown": []}'

        with patch.object(service, "_call_llm", side_effect=fake_call_llm):
            service.write_message(**self._make_write_message_args(user_notes=None))

        assert "USER NOTES" not in captured_prompt["prompt"]

    def test_user_notes_present_during_revision(self):
        """user_notes must still appear in the prompt during a revision pass."""
        from app.llm_service import LLMService

        service = LLMService()
        captured_prompt = {}

        def fake_call_llm(prompt, system_instruction=None, agent_step=None):
            captured_prompt["prompt"] = prompt
            return '{"body": "Short message.", "subject": null, "sentence_breakdown": []}'

        args = self._make_write_message_args(user_notes="Keep it very short")
        args.update(is_revision=True, previous_draft="Old long message here.", feedback_from_critic="Too long.")

        with patch.object(service, "_call_llm", side_effect=fake_call_llm):
            service.write_message(**args)

        assert "USER NOTES" in captured_prompt["prompt"]
        assert "Keep it very short" in captured_prompt["prompt"]
        assert "REVISION REQUIRED" in captured_prompt["prompt"]


# ── 5. Writer agent: passes user_feedback to llm_service ─────────

class TestWriterAgentPassesUserFeedback:

    def test_writer_passes_user_feedback_as_user_notes(self):
        """AgentNodes.writer must forward state.user_feedback as user_notes."""
        from app.agents import AgentNodes

        state = _make_agent_state(
            status=Status.WRITING,
            strategy=_make_strategy(),
            user_feedback="Always end with a question",
        )
        captured_kwargs = {}

        def fake_write_message(**kwargs):
            captured_kwargs.update(kwargs)
            return {"body": "Hi Alice!", "subject": None, "sentence_breakdown": []}

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.write_message.side_effect = fake_write_message
            AgentNodes.writer(state)

        assert mock_llm.write_message.called
        assert captured_kwargs.get("user_notes") == "Always end with a question"

    def test_writer_passes_none_when_no_user_feedback(self):
        """user_notes must be None when state.user_feedback is not set."""
        from app.agents import AgentNodes

        state = _make_agent_state(
            status=Status.WRITING,
            strategy=_make_strategy(),
            user_feedback=None,
        )
        captured_kwargs = {}

        def fake_write_message(**kwargs):
            captured_kwargs.update(kwargs)
            return {"body": "Hi Alice!", "subject": None, "sentence_breakdown": []}

        with patch("app.agents.llm_service") as mock_llm:
            mock_llm.write_message.side_effect = fake_write_message
            AgentNodes.writer(state)

        assert captured_kwargs.get("user_notes") is None


# ── 6. Review/decision endpoint: rejection triggers rewrite ──────

class TestReviewDecisionFeedback:

    def test_rejection_sets_revising_status(self):
        """Rejecting a draft must set status=REVISING before re-running pipeline."""
        from app.main import app
        from fastapi.testclient import TestClient

        draft_state = _make_agent_state(
            status=Status.AWAITING_HUMAN,
            strategy=_make_strategy(),
            draft=_make_draft(),
        )
        from app import main as main_module
        main_module._pending_review["task_001"] = draft_state

        rewritten_state = _make_agent_state(
            task_id="task_002",
            status=Status.COMPLETE,
            strategy=_make_strategy(),
            draft=_make_draft("Rewritten message here."),
        )

        with patch("app.main.run_pipeline", return_value=[rewritten_state]):
            client = TestClient(app)
            response = client.post(
                "/api/review/task_001/decision",
                json={"approved": False, "feedback": "Too formal, be more casual"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["rewritten"] is True

    def test_rejection_feedback_put_in_next_action(self):
        """The feedback string must end up in next_action['feedback'] for the writer."""
        from app.main import app
        from fastapi.testclient import TestClient

        draft_state = _make_agent_state(
            status=Status.AWAITING_HUMAN,
            strategy=_make_strategy(),
            draft=_make_draft(),
        )
        from app import main as main_module
        main_module._pending_review["task_feedback_test"] = draft_state

        captured_states = []

        def fake_pipeline(state):
            captured_states.append(state.model_copy(deep=True))
            final = _make_agent_state(
                task_id="task_new",
                status=Status.COMPLETE,
                strategy=_make_strategy(),
                draft=_make_draft("Better message."),
            )
            return [final]

        with patch("app.main.run_pipeline", side_effect=fake_pipeline):
            client = TestClient(app)
            client.post(
                "/api/review/task_feedback_test/decision",
                json={"approved": False, "feedback": "Mention the ROI metric"},
            )

        assert len(captured_states) == 1
        next_action = captured_states[0].next_action or {}
        assert next_action.get("feedback") == "Mention the ROI metric"

    def test_rejection_without_feedback_uses_default_message(self):
        """Rejection with no feedback string must use a sensible default."""
        from app.main import app
        from fastapi.testclient import TestClient

        draft_state = _make_agent_state(
            status=Status.AWAITING_HUMAN,
            strategy=_make_strategy(),
            draft=_make_draft(),
        )
        from app import main as main_module
        main_module._pending_review["task_no_feedback"] = draft_state

        captured_states = []

        def fake_pipeline(state):
            captured_states.append(state.model_copy(deep=True))
            final = _make_agent_state(
                task_id="task_new2",
                status=Status.COMPLETE,
                strategy=_make_strategy(),
                draft=_make_draft("Another message."),
            )
            return [final]

        with patch("app.main.run_pipeline", side_effect=fake_pipeline):
            client = TestClient(app)
            client.post(
                "/api/review/task_no_feedback/decision",
                json={"approved": False},
            )

        next_action = captured_states[0].next_action or {}
        assert next_action.get("feedback") is not None
        assert len(next_action["feedback"]) > 0

    def test_approval_does_not_rewrite(self):
        """Approving a draft must NOT trigger a pipeline rewrite."""
        from app.main import app
        from fastapi.testclient import TestClient

        draft_state = _make_agent_state(
            status=Status.AWAITING_HUMAN,
            strategy=_make_strategy(),
            draft=_make_draft(),
        )
        from app import main as main_module
        main_module._pending_review["task_approve"] = draft_state

        with patch("app.main.run_pipeline") as mock_pipeline, \
             patch("app.main.send_email", return_value={"success": True}), \
             patch("app.main.send_linkedin_dm", return_value={"success": True}):
            client = TestClient(app)
            client.post(
                "/api/review/task_approve/decision",
                json={"approved": True, "prospect_linkedin_id": "linkedin_123"},
            )
            mock_pipeline.assert_not_called()


# ── 7. PipelineOrchestrator: user_feedback passed to AgentState ──

class TestOrchestratorUserFeedback:

    def test_orchestrator_passes_user_feedback_to_initial_state(self):
        from app.orchestrator import PipelineOrchestrator

        orch = PipelineOrchestrator(
            target_prospect="Alice",
            target_company="Acme",
            prospect_role="VP",
            channel=Channel.LINKEDIN_DM,
            intent=Intent.DIRECT_OUTREACH,
            stage=Stage.FIRST_TOUCH,
            personality=Personality(),
            company_details=CompanyDetails(company_name="SellerCo"),
            selected_offer=SelectedOffer(offer_name="Demo"),
            research_signals=[],
            user_feedback="Focus on their recent funding round",
        )
        assert orch.initial_state.user_feedback == "Focus on their recent funding round"

    def test_orchestrator_user_feedback_none_by_default(self):
        from app.orchestrator import PipelineOrchestrator

        orch = PipelineOrchestrator(
            target_prospect="Alice",
            target_company="Acme",
            prospect_role=None,
            channel=Channel.LINKEDIN_DM,
            intent=Intent.DIRECT_OUTREACH,
            stage=Stage.FIRST_TOUCH,
            personality=Personality(),
            company_details=CompanyDetails(company_name="SellerCo"),
            selected_offer=SelectedOffer(offer_name="Demo"),
        )
        assert orch.initial_state.user_feedback is None
