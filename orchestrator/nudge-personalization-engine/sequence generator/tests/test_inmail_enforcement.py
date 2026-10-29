"""Tests for server-side LinkedIn InMail routing enforcement."""

import sys
import os
import importlib
import importlib.util
from datetime import datetime, timedelta, timezone
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

import sequence_generator.models.outreach_step as outreach_models
import sequence_generator.graph.state as state_mod
import sequence_generator.graph.nodes.sequence_generator_node as node_mod


ActionType = outreach_models.ActionType
OutreachStep = outreach_models.OutreachStep
OutreachSequence = outreach_models.OutreachSequence
GraphState = state_mod.GraphState
_enforce_inmail_rules = node_mod._enforce_inmail_rules


def _make_step(action: ActionType, channel: str, step_number: int = 1, timestamp_offset: int = 0) -> OutreachStep:
    return OutreachStep(
        step_number=step_number,
        action_type=action,
        channel=channel,
        scheduled_timestamp=datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=timestamp_offset),
        wait_delay_seconds=0,
        wait_delay_justification="This is a test timing justification.",
        timing_justification="This is a test timing justification.",
        sequence_architecture_rationale="This is a test rationale for the step.",
        message_intent="test",
        step_context={},
        message_language="en",
    )


def _make_sequence(steps: list) -> OutreachSequence:
    return OutreachSequence(
        lead_id="test-lead",
        campaign_id="test-campaign",
        steps=steps,
    )


def _make_state(has_inmail_credits: bool, is_connected: bool) -> GraphState:
    return GraphState(
        lead_id="test-lead",
        campaign_id="test-campaign",
        entreprise="Acme",
        contact_info={"full_name": "John Doe"},
        contexte_web={},
        has_inmail_credits=has_inmail_credits,
        is_connected_on_linkedin=is_connected,
    )


def test_enforces_inmail_when_credits_available_and_not_connected():
    seq = _make_sequence([_make_step(ActionType.LINKEDIN_CONNECT, "linkedin_dm")])
    state = _make_state(has_inmail_credits=True, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    assert result.steps[0].action_type == ActionType.LINKEDIN_INMAIL
    assert result.steps[0].channel == "linkedin_inmail"


def test_noop_when_already_correct():
    seq = _make_sequence([_make_step(ActionType.LINKEDIN_INMAIL, "linkedin_inmail")])
    state = _make_state(has_inmail_credits=True, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    assert result.steps[0].action_type == ActionType.LINKEDIN_INMAIL
    assert result.steps[0].channel == "linkedin_inmail"


def test_downgrades_inmail_when_no_credits():
    seq = _make_sequence([_make_step(ActionType.LINKEDIN_INMAIL, "linkedin_inmail")])
    state = _make_state(has_inmail_credits=False, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    assert result.steps[0].action_type == ActionType.LINKEDIN_CONNECT
    assert result.steps[0].channel == "linkedin_dm"


def test_uses_message_when_connected():
    seq = _make_sequence([_make_step(ActionType.LINKEDIN_CONNECT, "linkedin_dm")])
    state = _make_state(has_inmail_credits=True, is_connected=True)

    result = _enforce_inmail_rules(seq, state)

    # When connected, InMail is not available so no enforcement occurs.
    assert result.steps[0].action_type == ActionType.LINKEDIN_CONNECT
    assert result.steps[0].channel == "linkedin_dm"


def test_only_first_linkedin_step_is_changed():
    seq = _make_sequence([
        _make_step(ActionType.EMAIL_1, "email", step_number=1),
        _make_step(ActionType.LINKEDIN_CONNECT, "linkedin_dm", step_number=2, timestamp_offset=3600),
    ])
    state = _make_state(has_inmail_credits=True, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    assert result.steps[0].action_type == ActionType.EMAIL_1
    assert result.steps[1].action_type == ActionType.LINKEDIN_INMAIL
    assert result.steps[1].channel == "linkedin_inmail"


def test_env_var_can_disable_enforcement(monkeypatch):
    monkeypatch.setattr(node_mod, "ENFORCE_INMAIL_WHEN_CREDITS_AVAILABLE", False)

    seq = _make_sequence([_make_step(ActionType.LINKEDIN_CONNECT, "linkedin_dm")])
    state = _make_state(has_inmail_credits=True, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    # Enforcement disabled, so Gemini output is left as-is.
    assert result.steps[0].action_type == ActionType.LINKEDIN_CONNECT
    assert result.steps[0].channel == "linkedin_dm"


def test_env_var_can_disable_downgrade(monkeypatch):
    monkeypatch.setattr(node_mod, "INMAIL_FALLBACK_TO_CONNECT_IF_NO_CREDITS", False)

    seq = _make_sequence([_make_step(ActionType.LINKEDIN_INMAIL, "linkedin_inmail")])
    state = _make_state(has_inmail_credits=False, is_connected=False)

    result = _enforce_inmail_rules(seq, state)

    # Downgrade disabled, so InMail is preserved even without credits.
    assert result.steps[0].action_type == ActionType.LINKEDIN_INMAIL
    assert result.steps[0].channel == "linkedin_inmail"
