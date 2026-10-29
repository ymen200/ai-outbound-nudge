import os
import asyncio
import threading
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .state import GraphState
from .nodes.sequence_generator_node import generate_sequence
from .nodes.sandbox_node import sandbox_sequence
from ..config.constants import MAX_RETRIES
from ..observability.logging_config import logger

def prepare_temporal_payload(state: GraphState) -> GraphState:
    """Converts the validated sequence into the Temporal workflow input contract."""
    correlation_id = state.lead_id
    logger.info(f"Preparing Temporal payload for sequence {correlation_id}", extra={"correlation_id": correlation_id})
    
    if not state.validated_sequence:
        logger.error("No validated sequence available to prepare Temporal payload.", extra={"correlation_id": correlation_id})
        state.temporal_payload = {"error": "No validated sequence"}
        return state

    state.temporal_payload = state.validated_sequence.model_dump(mode="json")
    logger.info(f"Temporal payload prepared for sequence {correlation_id}.", extra={"correlation_id": correlation_id, "payload_preview": state.temporal_payload})
    return state

def _run_async_in_sync(coro_func, *args):
    """Run an async function from a sync context, handling existing event loops."""
    try:
        asyncio.get_running_loop()
        # Already in an event loop (e.g. uvicorn) — run in a new thread
        result = [None]
        exc = [None]
        def _thread_target():
            try:
                result[0] = asyncio.run(coro_func(*args))
            except Exception as e:
                exc[0] = e
        t = threading.Thread(target=_thread_target)
        t.start()
        t.join(timeout=30)
        if exc[0]:
            raise exc[0]
        return result[0]
    except RuntimeError:
        # No running loop — safe to use asyncio.run directly
        return asyncio.run(coro_func(*args))


async def _start_temporal_workflow(state: GraphState) -> str:
    """Async helper: start a real Temporal workflow and return the workflow_id."""
    from temporalio.client import Client

    # Import the workflow class via the namespaced package (works in API server context)
    try:
        from sequence_generator.workflows.sequence_workflow import SequenceWorkflow
    except ImportError:
        # Fallback: direct path import when running from sequence generator/ directory
        from workflows.sequence_workflow import SequenceWorkflow

    client = await Client.connect("localhost:7233")

    # Build detective_data from the validated LangGraph state
    contact = state.contact_info or {}
    contexte = state.contexte_web or {}
    seq_dict = state.validated_sequence.model_dump(mode="json") if state.validated_sequence else {}

    detective_data = {
        "company_name": state.entreprise or contact.get("company", "Unknown"),
        "company_industry": contexte.get("industry", ""),
        "company_website": contexte.get("website", ""),
        "icp_description": contexte.get("icp_description", ""),
        "offer_context": contexte.get("offer_context", ""),
        "selected_persona": {
            "full_name": contact.get("full_name", "Unknown"),
            "job_title": contact.get("role", ""),
            "company": contact.get("company", ""),
            "linkedin": contact.get("linkedin", ""),
        },
        "research_signals": state.research_signals,
        "personality_config": state.personality_config,
        "manual_context": True,  # Skip external research — we already have context
        "pre_validated_sequence": seq_dict,
        "lead_id": state.lead_id,
        "campaign_id": state.campaign_id,
    }

    import time as _time
    workflow_id = f"seq-{state.lead_id}-{int(_time.time())}"

    handle = await client.start_workflow(
        SequenceWorkflow.run,
        args=[detective_data],
        id=workflow_id,
        task_queue="sequence-task-queue",
    )
    return handle.id


def dispatch_to_temporal(state: GraphState) -> GraphState:
    """Dispatches the prepared payload to a real Temporal.io workflow."""
    correlation_id = state.lead_id
    logger.info(f"Dispatching sequence {correlation_id} to Temporal.io.", extra={"correlation_id": correlation_id})
    
    if not state.temporal_payload:
        logger.critical("No Temporal payload to dispatch. This indicates a serious issue.", extra={"correlation_id": correlation_id})
        return state

    try:
        workflow_id = _run_async_in_sync(_start_temporal_workflow, state)
        state.temporal_workflow_id = workflow_id
        logger.info(
            f"Temporal workflow started: {workflow_id}",
            extra={"correlation_id": correlation_id, "workflow_id": workflow_id},
        )
    except Exception as e:
        logger.error(
            f"Temporal dispatch failed for {correlation_id}: {e}. "
            f"Falling back to simulated dispatch.",
            extra={"correlation_id": correlation_id, "error": str(e)},
        )
        state.temporal_workflow_id = f"SIMULATED-{correlation_id}"

    return state

def _build_workflow():
    """
    Build the LangGraph StateGraph workflow without compiling.

    The workflow defines the sequence generation pipeline:

    Nodes:
      - generate_sequence: Calls Gemini to generate a sequence, validates it.
      - sandbox_sequence: Enforces prospect-local business hours (8am-6pm weekdays).
      - prepare_temporal_payload: Converts validated sequence to Temporal workflow input.
      - dispatch_to_temporal: Simulates dispatch to Temporal.io (HITL interrupt point).

    Conditional Edges (retry/fallback logic):
      After generate_sequence, the graph checks:
        1. If validated_sequence is set (success) -> route to sandbox_sequence
        2. Else if retry_count < MAX_RETRIES -> route back to generate_sequence (retry)
        3. Else -> route to END (fallback sequence is in state, but graph stops)

    The retry logic is HERE, not in generate_sequence() itself. The node function
    does ONE pass and returns; the graph decides whether to retry or stop.

    MAX_RETRIES (default 3): Maximum number of generation attempts before giving up.
    SAFE_FALLBACK_SEQUENCE: A validated 2-step sequence (LINKEDIN_CONNECT + EMAIL_1)
        used when all retries fail. Guaranteed to pass validation and sandbox checks.

    Returns
    -------
    StateGraph
        The uncompiled workflow. Call .compile() to create a runnable graph.
    """
    workflow = StateGraph(GraphState)
    workflow.add_node("generate_sequence", generate_sequence)
    workflow.add_node("sandbox_sequence", sandbox_sequence)
    workflow.add_node("prepare_temporal_payload", prepare_temporal_payload)
    workflow.add_node("dispatch_to_temporal", dispatch_to_temporal)
    workflow.set_entry_point("generate_sequence")
    workflow.add_conditional_edges(
        "generate_sequence",
        lambda state: "sandbox_sequence" if state.validated_sequence else ("generate_sequence" if state.retry_count < MAX_RETRIES else END),
    )
    workflow.add_edge("sandbox_sequence", "prepare_temporal_payload")
    workflow.add_edge("prepare_temporal_payload", "dispatch_to_temporal")
    workflow.add_edge("dispatch_to_temporal", END)
    return workflow


def create_graph():
    """
    Build and compile the LangGraph workflow with Human-In-The-Loop interrupt.

    The graph is compiled with interrupt_before=["dispatch_to_temporal"], which
    pauses execution before the final dispatch step. This allows a human reviewer
    to inspect the generated sequence and either approve or reject it.

    To resume after approval, use approve_and_dispatch() or invoke with Command(resume=True).

    Returns
    -------
    CompiledGraph
        The runnable LangGraph application.
    """
    app = _build_workflow().compile(interrupt_before=["dispatch_to_temporal"])
    return app

# Helper for human approval
def approve_and_dispatch(thread_id: str, app_instance, checkpointer_instance, approved: bool = True, user_feedback: str = None) -> Dict[str, Any]:
    """
    Resume the graph from the HITL interrupt and either dispatch or regenerate.

    This is the Human-In-The-Loop approval handler. When the graph pauses at
    dispatch_to_temporal, this function is called to either:
      1. Approve (approved=True): Resume the graph, which dispatches to Temporal.
      2. Reject with feedback (approved=False, user_feedback=...): Regenerate the
         sequence with the feedback injected, then pause again for re-review.

    Parameters
    ----------
    thread_id : str
        The unique identifier for the paused thread (from the initial response).
    app_instance : CompiledGraph
        The compiled LangGraph application (from create_graph()).
    checkpointer_instance : MemorySaver
        The LangGraph checkpointer holding the paused state.
    approved : bool, default True
        If True, dispatch. If False, regenerate with feedback.
    user_feedback : str, optional
        Feedback text to incorporate when regenerating. Required if approved=False.

    Returns
    -------
    dict
        Status dict with keys like "status", "thread_id", "final_state", etc.
    """
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = checkpointer_instance.get(config)
    if not initial_state:
        logger.error(f"No saved state found for thread_id {thread_id}.", extra={"correlation_id": thread_id})
        return {"status": "error", "message": "No saved state found."}

    state_obj = GraphState(**initial_state["channel_values"])

    if not state_obj.validated_sequence:
        logger.critical(f"Cannot approve/dispatch; no validated sequence in state for {thread_id}.", extra={"correlation_id": thread_id, "validation_errors": state_obj.validation_errors})
        return {"status": "error", "message": "No validated sequence to dispatch."}

    # If rejected with feedback, regenerate sequence
    if not approved and user_feedback:
        logger.info(f"Sequence rejected for thread_id {thread_id}. Regenerating with user feedback.", extra={"correlation_id": thread_id, "user_feedback": user_feedback})
        
        # Update state with user feedback and reset for regeneration
        state_obj.user_feedback = user_feedback
        state_obj.validated_sequence = None
        state_obj.retry_count = 0
        state_obj.validation_errors = []
        
        # Re-run graph from generate_sequence
        final_state = app_instance.invoke(state_obj.model_dump(), config)
        
        return {
            "status": "regenerated",
            "thread_id": thread_id,
            "user_feedback_applied": user_feedback,
            "final_state": final_state.get("validated_sequence"),
            "sandbox_adjustments": final_state.get("sandbox_adjustments", []),
            "validation_errors": final_state.get("validation_errors", [])
        }

    # If approved, resume from interrupt and dispatch to Temporal
    logger.info(f"Resuming graph for thread_id {thread_id} to dispatch to Temporal.", extra={"correlation_id": thread_id})
    final_state = app_instance.invoke(Command(resume=True), config)
    
    return {
        "status": "dispatched",
        "thread_id": thread_id,
        "temporal_workflow_id": final_state.get("temporal_workflow_id"),
        "final_state": final_state.get("temporal_payload"),
        "sandbox_adjustments": state_obj.sandbox_adjustments,
        "validation_errors": state_obj.validation_errors
    }
