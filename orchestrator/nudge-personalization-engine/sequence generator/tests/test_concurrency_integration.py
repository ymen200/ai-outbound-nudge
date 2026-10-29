"""
Integration test: prove thread isolation under concurrent graph execution.

Fires two generate_sequence requests concurrently with distinct company names,
verifies both pause at dispatch_to_temporal with their own data — no cross-contamination.
Also proves feedback injected for one lead never appears in another lead's prompt.

Requires a valid GOOGLE_API_KEY (calls real Gemini API).
Run with:  pytest tests/test_concurrency_integration.py -v
Skip with: pytest tests/ -k "not integration" -v
"""
import json
import threading
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed

from sequence_generator.graph.builder import _build_workflow
from sequence_generator.graph.state import GraphState
from langgraph.checkpoint.memory import MemorySaver


def _build_graph():
    memory = MemorySaver()
    workflow = _build_workflow()
    app = workflow.compile(
        checkpointer=memory,
        interrupt_before=["dispatch_to_temporal"],
    )
    return app, memory


def _detect_paused_threads(graph_app, memory):
    paused = []
    for tid in list(memory.storage.keys()):
        config = {"configurable": {"thread_id": tid}}
        state = graph_app.get_state(config)
        if state and "dispatch_to_temporal" in state.next:
            paused.append({
                "thread_id": tid,
                "entreprise": state.values.get("entreprise", ""),
                "lead_id": state.values.get("lead_id", ""),
                "contact_info": state.values.get("contact_info", {}),
            })
    return paused


def _invoke_graph(app, initial_state_dict, thread_id):
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(initial_state_dict, config)
    return thread_id, result


@pytest.mark.integration
def test_two_concurrent_sequences_isolated():
    """
    Fire two sequences concurrently with distinct company names.
    Both must pause at dispatch_to_temporal with their OWN data —
    no cross-contamination of state between threads.
    """
    app, memory = _build_graph()

    state_a = GraphState(
        lead_id="concurrent-lead-alpha",
        campaign_id="concurrent-camp",
        entreprise="AlphaConcurrent Corp UNIQUE_X7K9",
        contact_info={
            "full_name": "Alice Alpha",
            "email": "alice@alpha-concurrent.test",
            "country": "France",
        },
        contexte_web={"profil_brut": "Alpha company profile"},
    ).model_dump()

    state_b = GraphState(
        lead_id="concurrent-lead-beta",
        campaign_id="concurrent-camp",
        entreprise="BetaConcurrent Inc UNIQUE_Y3M2",
        contact_info={
            "full_name": "Bob Beta",
            "email": "bob@beta-concurrent.test",
            "country": "Japan",
        },
        contexte_web={"profil_brut": "Beta company profile"},
    ).model_dump()

    thread_a = "concurrent-thread-alpha"
    thread_b = "concurrent-thread-beta"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(_invoke_graph, app, state_a, thread_a)
        fut_b = pool.submit(_invoke_graph, app, state_b, thread_b)
        _, result_a = fut_a.result(timeout=120)
        _, result_b = fut_b.result(timeout=120)

    # Both produced sequences
    assert result_a.get("validated_sequence") is not None, "Thread A produced no sequence"
    assert result_b.get("validated_sequence") is not None, "Thread B produced no sequence"

    # Both are paused at the interrupt
    paused = _detect_paused_threads(app, memory)
    paused_ids = {p["thread_id"] for p in paused}
    assert thread_a in paused_ids, "Thread A not detected as paused"
    assert thread_b in paused_ids, "Thread B not detected as paused"

    # Each thread has its own distinct data
    entry_a = next(p for p in paused if p["thread_id"] == thread_a)
    entry_b = next(p for p in paused if p["thread_id"] == thread_b)

    assert "AlphaConcurrent" in entry_a["entreprise"], (
        f"Thread A has wrong entreprise: {entry_a['entreprise']}"
    )
    assert "UNIQUE_X7K9" in entry_a["entreprise"], (
        f"Thread A's unique marker missing — possible cross-contamination: {entry_a['entreprise']}"
    )
    assert "BetaConcurrent" in entry_b["entreprise"], (
        f"Thread B has wrong entreprise: {entry_b['entreprise']}"
    )
    assert "UNIQUE_Y3M2" in entry_b["entreprise"], (
        f"Thread B's unique marker missing — possible cross-contamination: {entry_b['entreprise']}"
    )

    # No cross-contamination
    assert "UNIQUE_Y3M2" not in entry_a["entreprise"], "Thread A contains Thread B's data!"
    assert "UNIQUE_X7K9" not in entry_b["entreprise"], "Thread B contains Thread A's data!"

    assert entry_a["lead_id"] == "concurrent-lead-alpha"
    assert entry_b["lead_id"] == "concurrent-lead-beta"

    # Both paused at the same node
    state_snap_a = app.get_state({"configurable": {"thread_id": thread_a}})
    state_snap_b = app.get_state({"configurable": {"thread_id": thread_b}})
    assert state_snap_a.next == ("dispatch_to_temporal",)
    assert state_snap_b.next == ("dispatch_to_temporal",)

    # JSON serializable
    raw = json.dumps({"paused_threads": paused}, default=str)
    parsed = json.loads(raw)
    assert len(parsed["paused_threads"]) >= 2


@pytest.mark.integration
def test_feedback_isolation_between_leads():
    """
    Feedback injected for lead A must ONLY appear in lead A's prompt,
    never in lead B's — even when both run concurrently.
    """
    from sequence_generator.graph.nodes.sequence_generator_node import (
        _pending_feedback,
        _collect_feedback_for_lead,
    )

    _pending_feedback.clear()

    _pending_feedback["concurrent-lead-alpha"] = ["ALPHA_SECRET_7741"]
    _pending_feedback["concurrent-lead-beta"] = ["BETA_SECRET_8825"]

    alpha_fb = _collect_feedback_for_lead("concurrent-lead-alpha")
    beta_fb = _collect_feedback_for_lead("concurrent-lead-beta")

    assert "ALPHA_SECRET_7741" in alpha_fb, "Alpha didn't get its own feedback"
    assert "BETA_SECRET_8825" not in alpha_fb, "Alpha got Beta's feedback!"
    assert "BETA_SECRET_8825" in beta_fb, "Beta didn't get its own feedback"
    assert "ALPHA_SECRET_7741" not in beta_fb, "Beta got Alpha's feedback!"

    # Consumed — second call returns empty
    alpha_fb2 = _collect_feedback_for_lead("concurrent-lead-alpha")
    assert alpha_fb2 == "", "Alpha's feedback was not consumed on first read"

    _pending_feedback.clear()


@pytest.mark.integration
def test_shared_feedback_available_to_all_leads():
    """
    Feedback injected WITHOUT a lead_id goes to a shared bucket
    and is available to any lead (backward-compatible behavior).
    """
    from sequence_generator.graph.nodes.sequence_generator_node import (
        _pending_feedback,
        _collect_feedback_for_lead,
    )

    _pending_feedback.clear()

    _pending_feedback["__shared__"] = ["SHARED_DIRECTIVE_5593"]

    fb = _collect_feedback_for_lead("any-random-lead")
    assert "SHARED_DIRECTIVE_5593" in fb, "Shared feedback not available to lead"

    # Consumed — second call returns empty
    fb2 = _collect_feedback_for_lead("any-random-lead")
    assert fb2 == "", "Shared feedback was not consumed on first read"

    _pending_feedback.clear()


@pytest.mark.integration
def test_feedback_concurrent_collection():
    """
    Two threads collecting feedback for different leads simultaneously
    must each get only their own feedback — never the other's.
    """
    from sequence_generator.graph.nodes.sequence_generator_node import (
        _pending_feedback,
        _collect_feedback_for_lead,
    )

    _pending_feedback.clear()

    # Pre-load feedback for multiple leads
    _pending_feedback["lead-X"] = ["X_ONLY_DATA"]
    _pending_feedback["lead-Y"] = ["Y_ONLY_DATA"]

    results = {}

    def collect_for_lead(lead_id):
        return _collect_feedback_for_lead(lead_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_x = pool.submit(collect_for_lead, "lead-X")
        fut_y = pool.submit(collect_for_lead, "lead-Y")
        results["lead-X"] = fut_x.result(timeout=10)
        results["lead-Y"] = fut_y.result(timeout=10)

    assert "X_ONLY_DATA" in results["lead-X"], "lead-X didn't get its own feedback"
    assert "Y_ONLY_DATA" not in results["lead-X"], "lead-X got lead-Y's feedback!"
    assert "Y_ONLY_DATA" in results["lead-Y"], "lead-Y didn't get its own feedback"
    assert "X_ONLY_DATA" not in results["lead-Y"], "lead-Y got lead-X's feedback!"

    _pending_feedback.clear()
