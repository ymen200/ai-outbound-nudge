"""
Integration test: verify /api/paused-threads endpoint against real MemorySaver state.

This is the ONLY test in the codebase that exercises the real resume path
against actual graph state instead of mocks. It catches bugs that mocked
tests cannot (e.g. the _checkpoints attribute error, the Command(resume=True)
resume path).

Requires a valid GOOGLE_API_KEY (calls real Gemini API).
Run with:  pytest tests/test_paused_threads_integration.py -v
Skip with: pytest tests/ -k "not integration" -v
"""
import json
import pytest

from sequence_generator.graph.builder import _build_workflow, approve_and_dispatch
from langgraph.checkpoint.memory import MemorySaver


# ── Helpers ────────────────────────────────────────────────────────

def _build_graph():
    """Build a real graph with MemorySaver + interrupt_before."""
    memory = MemorySaver()
    workflow = _build_workflow()
    app = workflow.compile(
        checkpointer=memory,
        interrupt_before=["dispatch_to_temporal"],
    )
    return app, memory


def _detect_paused_threads(graph_app, memory):
    """
    Replicate the /api/paused-threads endpoint logic exactly:
    use graph_app.get_state() for each thread in memory.storage,
    check if 'dispatch_to_temporal' is in state.next.
    """
    paused_threads = []
    for thread_id in list(memory.storage.keys()):
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = graph_app.get_state(config)
            if state and "dispatch_to_temporal" in state.next:
                values = state.values if isinstance(state.values, dict) else {}
                contact_info = values.get("contact_info", {})
                paused_threads.append({
                    "thread_id": thread_id,
                    "paused_at": "dispatch_to_temporal",
                    "entreprise": values.get("entreprise", ""),
                    "lead_id": values.get("lead_id", ""),
                    "contact_info": {
                        "full_name": contact_info.get("full_name", "") if isinstance(contact_info, dict) else "",
                        "email": contact_info.get("email", "") if isinstance(contact_info, dict) else "",
                        "country": contact_info.get("country", "") if isinstance(contact_info, dict) else "",
                    },
                })
        except Exception:
            continue
    return paused_threads


def _run_graph_to_interrupt(app, config):
    """Invoke the graph with a real request. It pauses at dispatch_to_temporal."""
    initial_state = {
        "lead_id": "test-lead-integ",
        "campaign_id": "test-camp-integ",
        "entreprise": "Acme Integration Corp",
        "contact_info": {
            "full_name": "Jane Integration",
            "email": "jane@integration.test",
            "country": "United States",
        },
        "contexte_web": {"company_url": "https://integration.test"},
    }
    return app.invoke(initial_state, config)


# ── Tests ──────────────────────────────────────────────────────────

@pytest.mark.integration
def test_graph_pauses_at_dispatch_to_temporal():
    """Real graph.run() produces a state where next == ('dispatch_to_temporal',)."""
    app, memory = _build_graph()
    thread_id = "integ-pause-check"
    config = {"configurable": {"thread_id": thread_id}}

    result = _run_graph_to_interrupt(app, config)

    # Graph should have produced a validated sequence
    assert result.get("validated_sequence") is not None

    # State should show dispatch_to_temporal as the next node
    state = app.get_state(config)
    assert state.next == ("dispatch_to_temporal",), (
        f"Expected ('dispatch_to_temporal',), got {state.next}"
    )


@pytest.mark.integration
def test_paused_threads_detected_before_approval():
    """
    BEFORE approval: the endpoint logic detects the paused thread with
    correct context (entreprise, lead_id, contact_info).
    """
    app, memory = _build_graph()
    thread_id = "integ-before-approval"
    config = {"configurable": {"thread_id": thread_id}}

    _run_graph_to_interrupt(app, config)

    paused = _detect_paused_threads(app, memory)
    assert len(paused) >= 1, "Expected at least one paused thread"

    found = next((p for p in paused if p["thread_id"] == thread_id), None)
    assert found is not None, f"Thread {thread_id} not found in paused list"
    assert found["paused_at"] == "dispatch_to_temporal"
    assert found["entreprise"] == "Acme Integration Corp"
    assert found["lead_id"] == "test-lead-integ"
    assert found["contact_info"]["full_name"] == "Jane Integration"
    assert found["contact_info"]["email"] == "jane@integration.test"


@pytest.mark.integration
def test_paused_thread_gone_after_approval():
    """
    AFTER approval via approve_and_dispatch(approved=True):
    the thread no longer appears in the paused list.
    This is the critical regression test — the original bug was that
    approve_and_dispatch re-invoked from the entry point instead of
    resuming, so the thread appeared paused again.
    """
    app, memory = _build_graph()
    thread_id = "integ-after-approval"
    config = {"configurable": {"thread_id": thread_id}}

    _run_graph_to_interrupt(app, config)

    # Verify paused before approval
    paused_before = _detect_paused_threads(app, memory)
    assert any(p["thread_id"] == thread_id for p in paused_before), (
        "Thread should be paused before approval"
    )

    # Approve — uses Command(resume=True) internally
    result = approve_and_dispatch(
        thread_id=thread_id,
        app_instance=app,
        checkpointer_instance=memory,
        approved=True,
    )
    assert result["status"] == "dispatched", (
        f"Expected 'dispatched', got {result['status']}"
    )

    # Verify NOT paused after approval
    paused_after = _detect_paused_threads(app, memory)
    assert not any(p["thread_id"] == thread_id for p in paused_after), (
        f"Thread {thread_id} still appears paused after approval!"
    )

    # Verify graph completed (no next nodes)
    state_after = app.get_state(config)
    assert "dispatch_to_temporal" not in state_after.next, (
        f"dispatch_to_temporal still in state.next after approval: {state_after.next}"
    )


@pytest.mark.integration
def test_endpoint_response_shape():
    """
    Verify the JSON response shape matches what the orchestrator client expects.
    """
    app, memory = _build_graph()
    thread_id = "integ-shape-check"
    config = {"configurable": {"thread_id": thread_id}}

    _run_graph_to_interrupt(app, config)

    paused = _detect_paused_threads(app, memory)
    response = {"paused_threads": paused}

    # Must be serializable to JSON
    raw = json.dumps(response, default=str)
    parsed = json.loads(raw)

    assert "paused_threads" in parsed
    assert isinstance(parsed["paused_threads"], list)
    if parsed["paused_threads"]:
        entry = parsed["paused_threads"][0]
        assert "thread_id" in entry
        assert "paused_at" in entry
        assert "entreprise" in entry
        assert "lead_id" in entry
        assert "contact_info" in entry
        assert "full_name" in entry["contact_info"]
        assert "email" in entry["contact_info"]
        assert "country" in entry["contact_info"]
