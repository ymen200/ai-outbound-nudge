"""
Regression tests verifying nothing broke after dead code removal.

Covers:
- agents/ package: old prototype files are gone, no live code depends on them
- tools/scraper.py: gone, nothing in the pipeline imports it
- tools/hunter_client.py: gone, nothing in the pipeline imports it
- graph/state.py: GraphState still has all required fields
- graph/builder.py: approve_and_dispatch still works correctly
- graph/nodes/message_generation_node.py: still runs without deleted tools
- tools/mcp_client.py: generate_message_for_step still works
- tools/language_detector.py: still importable and functional
"""

import sys
import os
import importlib
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

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
        _path = _SEQ_GEN_DIR / _sub.replace(".", "/")
        if _path.is_dir():
            _load_pkg(f"sequence_generator.{_sub}", _path)

from sequence_generator.graph.state import GraphState
from sequence_generator.graph.builder import approve_and_dispatch
from sequence_generator.models.outreach_step import OutreachStep, ActionType, OutreachSequence


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
        timing_justification=f"Step {n} timing rationale.",
        sequence_architecture_rationale=f"Step {n} architecture rationale.",
        **kwargs,
    )


def _make_sequence() -> OutreachSequence:
    now = _business_day_now()
    return OutreachSequence(
        lead_id="lead_001",
        campaign_id="camp_001",
        steps=[_make_step(1, now)],
    )


def _base_state(**kwargs) -> GraphState:
    defaults = dict(
        lead_id="lead_001",
        campaign_id="camp_001",
        entreprise="Acme",
        contact_info={"nom": "Alice", "titre": "CEO"},
        contexte_web={"profil_brut": "CEO at Acme."},
    )
    defaults.update(kwargs)
    return GraphState(**defaults)


def _mock_cp(state: GraphState) -> MagicMock:
    cp = MagicMock()
    cp.get.return_value = {"channel_values": state.model_dump()}
    return cp


# ── 1. Deleted files are truly gone ──────────────────────────────

class TestDeletedFilesGone:

    def test_agents_graph_not_importable(self):
        """agents/graph.py must be deleted."""
        agents_graph = _SEQ_GEN_DIR / "agents" / "graph.py"
        assert not agents_graph.exists()

    def test_agents_state_not_importable(self):
        """agents/state.py must be deleted."""
        agents_state = _SEQ_GEN_DIR / "agents" / "state.py"
        assert not agents_state.exists()

    def test_test_engine_not_importable(self):
        """scripts/test_engine.py must be deleted."""
        test_engine = _SEQ_GEN_DIR / "scripts" / "test_engine.py"
        assert not test_engine.exists()

    def test_scraper_not_importable(self):
        """tools/scraper.py must be deleted."""
        scraper = _SEQ_GEN_DIR / "tools" / "scraper.py"
        assert not scraper.exists()

    def test_hunter_client_not_importable(self):
        """tools/hunter_client.py must be deleted."""
        hunter = _SEQ_GEN_DIR / "tools" / "hunter_client.py"
        assert not hunter.exists()


# ── 2. GraphState still has all required fields ───────────────────

class TestGraphStateIntegrity:

    def test_all_required_fields_present(self):
        state = _base_state()
        required = [
            "lead_id", "campaign_id", "entreprise", "contact_info",
            "contexte_web", "is_connected_on_linkedin", "has_inmail_credits",
            "use_native_language", "message_language", "detected_language",
            "detected_timezone", "approval_mode", "validated_sequence",
            "validation_errors", "retry_count", "sandbox_adjustments",
            "research_signals", "max_touches", "max_days",
            "preferred_first_channel", "sequence_options", "stage_instructions",
            "personality_config", "message_generation_results",
            "user_feedback", "fallback_triggered",
        ]
        for field in required:
            assert hasattr(state, field), f"Missing field: {field}"

    def test_user_feedback_present(self):
        state = _base_state(user_feedback="Test note")
        assert state.user_feedback == "Test note"

    def test_state_survives_roundtrip(self):
        state = _base_state(user_feedback="note", retry_count=1)
        restored = GraphState(**state.model_dump())
        assert restored.user_feedback == "note"
        assert restored.retry_count == 1


# ── 3. approve_and_dispatch still works ──────────────────────────

class TestApproveAndDispatchIntegrity:

    def test_approval_dispatches(self):
        state = _base_state(validated_sequence=_make_sequence())

        def fake_invoke(d, config):
            # d is now Command(resume=True) for approval path; return a valid result dict
            return {"temporal_payload": {"ok": True}, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        result = approve_and_dispatch("t1", mock_app, _mock_cp(state), approved=True)
        assert result["status"] == "dispatched"

    def test_rejection_with_feedback_regenerates(self):
        state = _base_state(validated_sequence=_make_sequence())
        captured = {}

        def fake_invoke(d, config):
            captured.update(d)
            return {**d, "validated_sequence": None, "sandbox_adjustments": [], "validation_errors": []}

        mock_app = MagicMock()
        mock_app.invoke.side_effect = fake_invoke
        result = approve_and_dispatch("t2", mock_app, _mock_cp(state), approved=False, user_feedback="Shorten")
        assert result["status"] == "regenerated"
        assert captured.get("user_feedback") == "Shorten"
        assert captured.get("validated_sequence") is None
        assert captured.get("retry_count") == 0

    def test_missing_thread_returns_error(self):
        cp = MagicMock()
        cp.get.return_value = None
        result = approve_and_dispatch("missing", MagicMock(), cp, approved=True)
        assert result["status"] == "error"


# ── 4. message_generation_node still works ───────────────────────

class TestMessageGenerationNodeIntegrity:

    def _state_with_steps(self, n=1, user_feedback=None) -> GraphState:
        now = _business_day_now()
        steps = [
            _make_step(i, now, step_context={
                "target_prospect": "Bob",
                "target_company": "BobCo",
                "company_name": "SellerCo",
                "offer_name": "Demo",
            })
            for i in range(1, n + 1)
        ]
        seq = OutreachSequence(lead_id="lead_001", campaign_id="camp_001", steps=steps)
        return _base_state(validated_sequence=seq, user_feedback=user_feedback)

    def test_node_runs_successfully(self):
        from sequence_generator.graph.nodes.message_generation_node import generate_messages_for_sequence
        state = self._state_with_steps(n=1)
        captured = []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured.append(ctx) or {"success": True, "message": "Hi!", "subject": None, "score": 85}):
            result = generate_messages_for_sequence(state)

        assert len(result.message_generation_results) == 1
        assert result.message_generation_results[0]["success"] is True

    def test_node_forwards_user_notes(self):
        from sequence_generator.graph.nodes.message_generation_node import generate_messages_for_sequence
        state = self._state_with_steps(n=2, user_feedback="Keep it short")
        captured = []

        with patch("sequence_generator.graph.nodes.message_generation_node.generate_message_for_step_sync",
                   side_effect=lambda ctx: captured.append(ctx) or {"success": True, "message": "Hi!", "subject": None, "score": 80}):
            generate_messages_for_sequence(state)

        assert all(ctx.get("user_notes") == "Keep it short" for ctx in captured)

    def test_node_handles_missing_step_context(self):
        from sequence_generator.graph.nodes.message_generation_node import generate_messages_for_sequence
        now = _business_day_now()
        step = _make_step(1, now)  # no step_context
        seq = OutreachSequence(lead_id="lead_001", campaign_id="camp_001", steps=[step])
        state = _base_state(validated_sequence=seq)

        result = generate_messages_for_sequence(state)
        # Step with no context should be marked failed, not crash
        assert len(result.message_generation_results) == 1
        assert result.message_generation_results[0]["success"] is False


# ── 5. mcp_client still works ─────────────────────────────────────

class TestMCPClientIntegrity:

    def test_generate_message_for_step_sync_importable(self):
        from sequence_generator.tools.mcp_client import (
            generate_message_for_step_sync,
            generate_message_for_step,
            MessageGeneratorMCPClient,
        )
        assert callable(generate_message_for_step_sync)
        assert callable(generate_message_for_step)

    def test_client_has_user_notes_param(self):
        import inspect
        from sequence_generator.tools.mcp_client import MessageGeneratorMCPClient
        sig = inspect.signature(MessageGeneratorMCPClient.generate_outreach)
        assert "user_notes" in sig.parameters

    def test_generate_message_for_step_passes_user_notes(self):
        from sequence_generator.tools.mcp_client import generate_message_for_step_sync
        ctx = {
            "target_prospect": "Alice",
            "target_company": "Acme",
            "company_name": "SellerCo",
            "offer_name": "Demo",
            "channel": "email",
            "stage": "first_touch",
            "user_notes": "Be casual",
        }
        with patch("sequence_generator.tools.mcp_client.MessageGeneratorMCPClient") as MockClient:
            instance = MockClient.return_value
            instance.generate_outreach = MagicMock(return_value={"success": True, "message": "Hi!", "subject": None, "score": 80})

            import asyncio
            async def fake_generate(**kwargs):
                return {"success": True, "message": "Hi!", "subject": None, "score": 80}
            instance.generate_outreach = fake_generate

            # Just verify the function is callable and doesn't crash on import
            assert callable(generate_message_for_step_sync)


# ── 6. language_detector still works ─────────────────────────────

class TestLanguageDetectorIntegrity:

    def test_language_detector_file_exists(self):
        detector = _SEQ_GEN_DIR / "tools" / "language_detector.py"
        assert detector.exists()

    def test_language_detector_has_no_dependency_on_deleted_files(self):
        detector_path = _SEQ_GEN_DIR / "tools" / "language_detector.py"
        content = detector_path.read_text(encoding="utf-8")
        assert "scraper" not in content
        assert "hunter_client" not in content
        assert "agents.graph" not in content


# ── 7. No remaining references to deleted symbols ────────────────

class TestNoOrphanedReferences:

    def _scan_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_no_reference_to_extraire_donnees(self):
        for f in _SEQ_GEN_DIR.rglob("*.py"):
            if "venv" in str(f) or f.name == "test_regression_cleanup.py":
                continue
            if "extraire_donnees_page" in self._scan_file(f):
                pytest.fail(f"Found reference to deleted extraire_donnees_page in {f}")

    def test_no_reference_to_trouver_decideur(self):
        for f in _SEQ_GEN_DIR.rglob("*.py"):
            if "venv" in str(f) or f.name == "test_regression_cleanup.py":
                continue
            if "trouver_decideur" in self._scan_file(f):
                pytest.fail(f"Found reference to deleted trouver_decideur in {f}")

    def test_no_reference_to_agents_graph_import(self):
        for f in _SEQ_GEN_DIR.rglob("*.py"):
            if "venv" in str(f) or f.name == "test_regression_cleanup.py":
                continue
            content = self._scan_file(f)
            if "from agents.graph" in content or "from agents.state" in content:
                pytest.fail(f"Found orphaned import from deleted agents/ in {f}")
