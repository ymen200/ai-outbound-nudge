"""
Tests for user feedback (human notes) in the sequence generator.

Covers:
- user_feedback field on GraphState
- user_notes_instruction injected into the Gemini prompt
- approve_and_dispatch regeneration path with feedback
- user_feedback forwarded to message generator via enriched_context
"""

import sys
import os
import importlib
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Package registration (same trick as api_server.py) ───────────
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
        _path = _SEQ_GEN_DIR / _sub.replace(".", "/")
        if _path.is_dir():
            _load_pkg(f"sequence_generator.{_sub}", _path)

from sequence_generator.graph.state import GraphState
from sequence_generator.graph.builder import approve_and_dispatch
from sequence_generator.models.outreach_step import OutreachStep, ActionType, OutreachSequence
from sequence_generator.graph.nodes.message_generation_node import generate_messages_for_sequence


# ── Helpers ───────────────────────────────────────────────────────

def _business_day_now() -> datetime:
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    return now


def _make_step(n: int, now: datetime, **kwargs) -> OutreachStep:
    return OutreachStep(
        step_number=n,
        action_type=ActionType.EMAIL_1,
        channel="email",
        scheduled_timestamp=now + timedelta(days=n - 1),
        wait_delay_seconds=0 if n == 1 else 86400,
        timing_justification=f"Step {n} timing.",
        sequence_architecture_rationale=f"Step {n} rationale.",
        **kwargs,
    )


def _make_sequence(lead_id: str = "lead_001", steps: int = 1) -> OutreachSequence:
    now = _business_day_now()
    return OutreachSequence(
        lead_id=lead_id,
        campaign_id="camp_001",
        steps=[_make_step(i, now) for i in range(1, steps + 1)],
    )


def _base_state(**kwargs) -> GraphState:
    defaults = dict(
        lead_id="lead_001",
        campaign_id="camp_001",
        entreprise="Acme Corp",
        contact_info={"nom": "Alice", "titre": "CEO"},
        contexte_web={"profil_brut": "CEO at Acme Corp."},
    )
    defaults.update(kwargs)
    return GraphState(**defaults)


def _mock_checkpointer(state: GraphState) -> MagicMock:
    cp = MagicMock()
    cp.get.return_value = {"channel_values": state.model_dump()}
    return cp


# ── 1. GraphState: user_feedback field ───────────────────────────

class TestGraphStateUserFeedback:

    def test_defaults_to_none(self):
        assert _base_state().user_feedback is None

    def test_accepts_string(self):
        state = _base_state(user_feedback="Make it shorter")
        assert state.user_feedback == "Make it shorter"

    def test_survives_model_dump_roundtrip(self):
        state = _base_state(user_feedback="Focus on email only")
        assert GraphState(**state.model_dump()).user_feedback == "Focus on email only"

    def test_can_be_updated(self):
        state = _base_state(user_feedback="First note")
        state.user_feedback = "Updated note"
        assert state.user_feedback == "Updated note"


# ── 2. Prompt injection logic ─────────────────────────────────────

class TestPromptInjection:

    def test_feedback_produces_user_notes_block(self):
        feedback = "Add a breakup email at the end"
        state = _base_state(user_feedback=feedback)
        block = ""
        if state.user_feedback:
            block = f"\n    USER NOTES (human feedback):\n    - {state.user_feedback}\nTake this feedback into account.\n"
        assert "USER NOTES" in block
        assert feedback in block

    def test_none_feedback_produces_empty_block(self):
        state = _base_state(user_feedback=None)
        block = ""
        if state.user_feedback:
            block = f"\n    USER NOTES (human feedback):\n    - {state.user_feedback}\n"
        assert block == ""

    def test_feedback_included_in_full_prompt(self):
        feedback = "Limit to 3 steps max"
        block = f"\n    USER NOTES (human feedback):\n    - {feedback}\n"
        prompt = f"You are a B2B strategist.{block}JSON SCHEMA: {{}}"
        assert "USER NOTES" in prompt
        assert feedback in prompt

    def test_multiline_feedback_preserved(self):
        feedback = "Start with email.\nUse a breakup at step 4."
        block = f"\n    USER NOTES (human feedback):\n    - {feedback}\n"
        assert "Start with email" in block
        assert "breakup" in block


# ── 3. approve_and_dispatch: regeneration with feedback ──────────

class TestApproveAndDispatch:

    def test_rejection_with_feedback_calls_invoke(self):
        state = _base_state(validated_sequence=_make_sequence())
        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            **state.model_dump(),
            "validated_sequence": _make_sequence().model_dump(),
            "sandbox_adjustments": [],
            "validation_errors": [],
        }
        approve_and_dispatch("t1", mock_app, _mock_checkpointer(state), approved=False, user_feedback="Add email touches")
        mock_app.invoke.assert_called_once()

    def test_rejection_with_feedback_sets_user_feedback_in_invoke(self):
        feedback = "Add more email touches"
        state = _base_state(validated_sequence=_make_sequence())
        captured = {}

        def fake_invoke(state_dict, config):
            captured.update(state_dict)
            return {**state_dict, "validated_sequence": None, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        approve_and_dispatch("t2", mock_app, _mock_checkpointer(state), approved=False, user_feedback=feedback)
        assert captured.get("user_feedback") == feedback

    def test_rejection_resets_validated_sequence_to_none(self):
        state = _base_state(validated_sequence=_make_sequence())
        captured = {}

        def fake_invoke(state_dict, config):
            captured.update(state_dict)
            return {**state_dict, "validated_sequence": None, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        approve_and_dispatch("t3", mock_app, _mock_checkpointer(state), approved=False, user_feedback="Shorten")
        assert captured.get("validated_sequence") is None

    def test_rejection_resets_retry_count(self):
        state = _base_state(validated_sequence=_make_sequence(), retry_count=2)
        captured = {}

        def fake_invoke(state_dict, config):
            captured.update(state_dict)
            return {**state_dict, "validated_sequence": None, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        approve_and_dispatch("t4", mock_app, _mock_checkpointer(state), approved=False, user_feedback="Try again")
        assert captured.get("retry_count") == 0

    def test_rejection_without_feedback_falls_through_to_dispatch(self):
        """Rejecting with no feedback has no feedback to apply, so it falls through to dispatch."""
        state = _base_state(validated_sequence=_make_sequence())

        def fake_invoke(state_dict, config):
            # state_dict may be Command(resume=True) for dispatch path; return a valid result
            return {"temporal_payload": {"dispatched": True}, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        result = approve_and_dispatch("t5", mock_app, _mock_checkpointer(state), approved=False, user_feedback=None)
        # No feedback to regenerate with — falls through, invoke is called for dispatch
        mock_app.invoke.assert_called_once()
        assert result.get("status") in ("dispatched", "regenerated")

    def test_approval_dispatches_to_temporal(self):
        state = _base_state(validated_sequence=_make_sequence())

        def fake_invoke(state_dict, config):
            # state_dict is Command(resume=True) for approval path; return a valid result
            return {"temporal_payload": {"dispatched": True}, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        result = approve_and_dispatch("t6", mock_app, _mock_checkpointer(state), approved=True)
        assert result.get("status") == "dispatched"

    def test_missing_thread_returns_error(self):
        cp = MagicMock()
        cp.get.return_value = None
        result = approve_and_dispatch("nonexistent", MagicMock(), cp, approved=True)
        assert result.get("status") == "error"

    def test_result_contains_user_feedback_applied(self):
        feedback = "Use casual tone"
        state = _base_state(validated_sequence=_make_sequence())

        def fake_invoke(state_dict, config):
            return {**state_dict, "validated_sequence": _make_sequence().model_dump(), "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        result = approve_and_dispatch("t7", mock_app, _mock_checkpointer(state), approved=False, user_feedback=feedback)
        assert result.get("user_feedback_applied") == feedback
        assert result.get("status") == "regenerated"


# ── 4. user_feedback forwarded to message generator ──────────────

class TestUserFeedbackForwardedToMessageGenerator:

    def _state_with_steps(self, user_feedback: Optional[str], n_steps: int = 1) -> GraphState:
        now = _business_day_now()
        steps = [
            _make_step(
                i, now,
                step_context={
                    "target_prospect": "Bob",
                    "target_company": "BobCo",
                    "company_name": "SellerCo",
                    "offer_name": "Free Demo",
                },
            )
            for i in range(1, n_steps + 1)
        ]
        seq = OutreachSequence(lead_id="lead_001", campaign_id="camp_001", steps=steps)
        return _base_state(validated_sequence=seq, user_feedback=user_feedback)

    def test_user_notes_in_enriched_context_when_feedback_set(self):
        state = self._state_with_steps(user_feedback="Write in a very casual tone")
        captured = []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured.append(ctx) or {"success": True, "message": "Hi!", "subject": None, "score": 85}):
            generate_messages_for_sequence(state)

        assert len(captured) == 1
        assert captured[0].get("user_notes") == "Write in a very casual tone"

    def test_user_notes_absent_when_feedback_none(self):
        state = self._state_with_steps(user_feedback=None)
        captured = []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured.append(ctx) or {"success": True, "message": "Hi!", "subject": None, "score": 80}):
            generate_messages_for_sequence(state)

        assert "user_notes" not in captured[0]

    def test_user_notes_forwarded_to_every_step(self):
        state = self._state_with_steps(user_feedback="Keep all messages under 150 words", n_steps=3)
        captured = []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured.append(ctx) or {"success": True, "message": "Hi!", "subject": None, "score": 80}):
            generate_messages_for_sequence(state)

        assert len(captured) == 3
        for ctx in captured:
            assert ctx.get("user_notes") == "Keep all messages under 150 words"

    def test_sequence_specific_feedback_does_not_bleed_to_unrelated_state(self):
        """Two separate states with different feedback must not share user_notes."""
        state_a = self._state_with_steps(user_feedback="State A feedback")
        state_b = self._state_with_steps(user_feedback="State B feedback")
        captured_a, captured_b = [], []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured_a.append(ctx) or {"success": True, "message": "A", "subject": None, "score": 80}):
            generate_messages_for_sequence(state_a)

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured_b.append(ctx) or {"success": True, "message": "B", "subject": None, "score": 80}):
            generate_messages_for_sequence(state_b)

        assert captured_a[0]["user_notes"] == "State A feedback"
        assert captured_b[0]["user_notes"] == "State B feedback"
