"""
LangGraph orchestration flow for the Outreach Orchestrator.

Coordinates the Sequence Generator and Message Generator via REST,
collects observability, and packages the final result.

Flow:
    collect_context → apply_config_overrides → generate_sequence →
    aggregate_observability → finalize
"""

import time
import logging
from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END

from .state import OrchestratorState
from .clients import SequenceGeneratorClient, MessageGeneratorClient
from .observability import ObservabilityAggregator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph state schema (flat dict mirror for LangGraph merging)
# ---------------------------------------------------------------------------

class OrchestratorGraphState(TypedDict, total=False):
    # Input
    lead_id: str
    campaign_id: str
    entreprise: str
    contact_info: Any
    contexte_web: Any
    research_signals: Any
    is_connected_on_linkedin: bool
    has_inmail_credits: bool
    use_native_language: bool
    message_language: Any
    approval_mode: str
    sender_company: str
    sender_elevator_pitch: str
    offer_name: str
    solution_summary: str
    cta: str

    # AI Sequence Configuration
    max_touches: Any
    max_days: Any
    preferred_first_channel: Any
    sequence_options: Any
    stage_instructions: Any
    personality_config: Any

    # Orchestration
    sequence_result: Any
    message_results: Any
    observability_snapshot: Any
    feedback: Any
    config_overrides: Any
    debug_mode: bool

    # Output
    status: str
    errors: List[str]
    generation_time_seconds: float
    _start_time: float


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def collect_context(state: OrchestratorGraphState) -> OrchestratorGraphState:
    """Validate input and prepare context for both modules."""
    state["_start_time"] = time.time()
    state["status"] = "running"

    errors = []
    if not state.get("lead_id"):
        errors.append("lead_id is required")
    if not state.get("entreprise"):
        errors.append("entreprise (company name) is required")
    if not state.get("contact_info"):
        errors.append("contact_info is required")

    if errors:
        state["errors"] = errors
        state["status"] = "failed"

    return state


async def apply_config_overrides(state: OrchestratorGraphState) -> OrchestratorGraphState:
    """Push config overrides to modules if the global orchestrator provided them.
    Also propagates DEBUG_MODE from orchestrator settings to both modules."""
    overrides = state.get("config_overrides")
    feedback = state.get("feedback")
    debug_mode = state.get("debug_mode", True)

    aggregator = ObservabilityAggregator()

    # Propagate DEBUG_MODE to both modules via config override
    debug_override = {"DEBUG_MODE": str(debug_mode).lower()}
    for module in ("sequence_generator", "message_generator"):
        try:
            result = await aggregator.override_config(module, debug_override)
            logger.info(f"DEBUG_MODE={debug_mode} propagated to {module}: {result}")
        except Exception as e:
            logger.warning(f"Failed to propagate DEBUG_MODE to {module}: {e}")

    if not overrides and not feedback:
        return state

    # Apply config overrides
    if overrides:
        for module, module_overrides in overrides.items():
            if module in ("sequence_generator", "message_generator"):
                try:
                    result = await aggregator.override_config(module, module_overrides)
                    logger.info(f"Config override applied to {module}: {result}")
                except Exception as e:
                    errors = list(state.get("errors", []))
                    errors.append(f"config_override_failed_{module}: {str(e)}")
                    state["errors"] = errors

    # Inject feedback
    if feedback:
        for module in ("sequence_generator", "message_generator"):
            try:
                result = await aggregator.inject_feedback(module, feedback)
                logger.info(f"Feedback injected to {module}: {result}")
            except Exception as e:
                errors = list(state.get("errors", []))
                errors.append(f"feedback_injection_failed_{module}: {str(e)}")
                state["errors"] = errors

    return state


async def generate_sequence(state: OrchestratorGraphState) -> OrchestratorGraphState:
    """Call Sequence Generator REST API to generate sequence + JIT messages."""
    seq_client = SequenceGeneratorClient()

    # Build the request payload matching the Sequence Generator's API contract
    request = {
        "lead_id": state.get("lead_id", ""),
        "campaign_id": state.get("campaign_id", "default_campaign"),
        "company": state.get("entreprise", ""),
        "contact": {
            "full_name": state["contact_info"].get("full_name", state["contact_info"].get("nom", "")),
            "job_title": state["contact_info"].get("job_title", state["contact_info"].get("titre", "")),
            "email": state["contact_info"].get("email", ""),
            "country": state["contact_info"].get("country", ""),
            "city": state["contact_info"].get("city", ""),
            "location": state["contact_info"].get("location", ""),
            "phone": state["contact_info"].get("phone", ""),
            "linkedin": state["contact_info"].get("linkedin", ""),
            "is_connected_on_linkedin": state.get("is_connected_on_linkedin", False),
            "has_inmail_credits": state.get("has_inmail_credits", False),
        },
        "web_context": {
            "profil_brut": state["contexte_web"].get("profil_brut", ""),
            "offer_context": state["contexte_web"].get("offer_context", ""),
            "icp_description": state["contexte_web"].get("icp_description", ""),
        },
        "sender_info": {
            "company_name": state.get("sender_company", "My Company"),
            "elevator_pitch": state.get("sender_elevator_pitch", ""),
            "offer_name": state.get("offer_name", "Default Offer"),
            "solution_summary": state.get("solution_summary", ""),
            "cta": state.get("cta", ""),
        },
        "approval_mode": state.get("approval_mode", "per_sequence"),
        "use_native_language": state.get("use_native_language", False),
        "message_language": state.get("message_language"),
        "research_signals": state.get("research_signals"),
        "max_touches": state.get("max_touches"),
        "max_days": state.get("max_days"),
        "preferred_first_channel": state.get("preferred_first_channel"),
        "sequence_options": state.get("sequence_options"),
        "stage_instructions": state.get("stage_instructions"),
        "personality_config": state.get("personality_config"),
    }

    try:
        result = await seq_client.generate_sequence(request)
        state["sequence_result"] = result
        # Pass through the status from the sequence generator (e.g. awaiting_approval, completed, failed)
        # Do NOT collapse awaiting_approval to completed — the orchestrator owns zero approval state.
        state["status"] = result.get("status", "completed")
        if result.get("errors"):
            errors = list(state.get("errors", []))
            errors.extend(result["errors"])
            state["errors"] = errors
    except Exception as e:
        errors = list(state.get("errors", []))
        errors.append(f"sequence_generation_failed: {str(e)}")
        state["errors"] = errors
        state["status"] = "failed"

    return state


async def aggregate_observability(state: OrchestratorGraphState) -> OrchestratorGraphState:
    """Collect observability from both modules and merge."""
    aggregator = ObservabilityAggregator()
    try:
        snapshot = await aggregator.collect_full_snapshot()
        state["observability_snapshot"] = snapshot
    except Exception as e:
        logger.warning(f"Observability aggregation failed: {e}")
        state["observability_snapshot"] = {"error": str(e)}
    return state


def finalize(state: OrchestratorGraphState) -> OrchestratorGraphState:
    """Package the final response with timing info."""
    start_time = state.get("_start_time", time.time())
    state["generation_time_seconds"] = round(time.time() - start_time, 2)
    return state


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_collect(state: OrchestratorGraphState) -> str:
    """If input validation failed, skip to finalize."""
    if state.get("status") == "failed":
        return "finalize"
    return "apply_config_overrides"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_orchestrator_graph():
    """Build and compile the orchestrator LangGraph workflow."""
    graph = StateGraph(OrchestratorGraphState)

    graph.add_node("collect_context", collect_context)
    graph.add_node("apply_config_overrides", apply_config_overrides)
    graph.add_node("generate_sequence", generate_sequence)
    graph.add_node("aggregate_observability", aggregate_observability)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("collect_context")

    graph.add_conditional_edges("collect_context", route_after_collect, {
        "apply_config_overrides": "apply_config_overrides",
        "finalize": "finalize",
    })

    graph.add_edge("apply_config_overrides", "generate_sequence")
    graph.add_edge("generate_sequence", "aggregate_observability")
    graph.add_edge("aggregate_observability", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


# Module-level compiled graph
orchestrator_pipeline = build_orchestrator_graph()


# ---------------------------------------------------------------------------
# Public run function
# ---------------------------------------------------------------------------

async def run_orchestrator(state: OrchestratorState) -> Dict[str, Any]:
    """Run the orchestrator pipeline and return the final result."""
    # Convert Pydantic state to dict for LangGraph
    state_dict = state.model_dump()
    state_dict["_start_time"] = time.time()
    state_dict["errors"] = []

    # Stream through the graph (async for async node functions)
    async for step_output in orchestrator_pipeline.astream(state_dict):
        for _node_name, updated_state in step_output.items():
            state_dict.update(updated_state)

    # Extract the final result
    seq_result = state_dict.get("sequence_result", {})
    obs_snapshot = state_dict.get("observability_snapshot", {})

    return {
        "status": state_dict.get("status", "unknown"),
        "lead_id": state_dict.get("lead_id", ""),
        "campaign_id": state_dict.get("campaign_id", ""),
        "debug_mode": state_dict.get("debug_mode", True),
        "thread_id": seq_result.get("thread_id"),  # Needed for approve/dispatch
        "sequence_result": seq_result,
        "observability_snapshot": obs_snapshot,
        "generation_time_seconds": state_dict.get("generation_time_seconds", 0),
        "errors": state_dict.get("errors", []),
    }
