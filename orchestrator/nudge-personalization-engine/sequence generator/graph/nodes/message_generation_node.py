"""
JIT Message Generation Node.

DEPRECATED: This module is NOT wired into the LangGraph graph (builder.py).
It exists only for historical reference and is called by its own tests.

The ACTUAL message generation path is:
  Temporal workflow → generate_message_activity (workflows/message_activities.py)
  → mcp_client.generate_message_for_step_sync → MCP → Message Generator

This node was intended to be a graph node between sandbox_sequence and
prepare_temporal_payload, but was never wired into builder.py. Do not use
it for production message generation.
"""

from typing import Dict, Any, List
import time
from ..state import GraphState
from ...tools.mcp_client import generate_message_for_step_sync
from ...observability.logging_config import logger


def _map_action_type_to_stage(action_type: str) -> str:
    """Map ActionType enum to message generator Stage enum.
    
    Valid Stage values: first_touch, second_touch, third_touch
    """
    action_upper = action_type.upper()
    
    if action_upper in ["LINKEDIN_CONNECT", "LINKEDIN_INMAIL", "EMAIL_1"]:
        return "first_touch"
    elif action_upper == "LINKEDIN_MESSAGE":
        return "second_touch"
    else:
        return "first_touch"


def _map_action_type_to_intent(action_type: str) -> str:
    """Map ActionType enum to message generator Intent enum.
    
    Valid Intent values: direct_outreach, follow_up, referral, re_engagement, event_based
    """
    action_upper = action_type.upper()
    
    if action_upper in ["LINKEDIN_CONNECT", "LINKEDIN_MESSAGE", "LINKEDIN_INMAIL", "EMAIL_1"]:
        return "direct_outreach"
    else:
        return "direct_outreach"


def generate_messages_for_sequence(state: GraphState) -> GraphState:
    """
    Generate messages for all steps in the validated sequence.
    
    For each step, extracts the step_context and calls the message generator
    to produce a JIT message. Results are stored in state.message_generation_results.
    
    If message generation fails for a step, it's marked as failed but the process
    continues for remaining steps.
    """
    correlation_id = state.lead_id
    logger.info(f"Starting JIT message generation for sequence {correlation_id}", 
                extra={"correlation_id": correlation_id})
    
    if not state.validated_sequence:
        logger.warning("No validated sequence available for message generation.", 
                      extra={"correlation_id": correlation_id})
        return state
    
    message_results: List[Dict[str, Any]] = []
    
    for step in state.validated_sequence.steps:
        step_num = step.step_number
        logger.info(f"Generating message for step {step_num}", 
                   extra={"correlation_id": correlation_id, "step_number": step_num})
        
        # Build step context for message generation
        if not step.step_context:
            logger.warning(f"Step {step_num} has no step_context, skipping message generation", 
                          extra={"correlation_id": correlation_id, "step_number": step_num})
            message_results.append({
                "step_number": step_num,
                "success": False,
                "message": None,
                "subject": None,
                "score": None,
                "error": "No step_context available"
            })
            continue
        
        # Enrich step_context with action_type mappings
        enriched_context = {**step.step_context}
        enriched_context["stage"] = _map_action_type_to_stage(step.action_type.value)
        enriched_context["intent"] = _map_action_type_to_intent(step.action_type.value)
        enriched_context["channel"] = step.channel
        
        # Inject sender/offer info from state so the message generator has full context.
        # Gemini only populates basic prospect info in step_context; the sender details
        # (offer, pitch, CTA) come from the original request and must be forwarded here.
        web_ctx = state.contexte_web or {}
        enriched_context.setdefault("target_prospect", enriched_context.get("prospect_name", "Unknown"))
        enriched_context.setdefault("target_company", state.entreprise or enriched_context.get("company", "Unknown Company"))
        enriched_context.setdefault("company_name", web_ctx.get("sender_company", ""))
        enriched_context.setdefault("elevator_pitch", web_ctx.get("elevator_pitch", ""))
        enriched_context.setdefault("offer_name", web_ctx.get("offer_name", ""))
        enriched_context.setdefault("solution_summary", web_ctx.get("solution_summary", ""))
        enriched_context.setdefault("cta", web_ctx.get("cta", ""))
        enriched_context.setdefault("prospect_role", enriched_context.get("role", ""))
        
        # Forward research signals from state (provided by Detective module or demo data)
        if state.research_signals:
            enriched_context["research_signals"] = state.research_signals

        # Forward personality config so the message generator uses the user's style preferences
        if state.personality_config:
            enriched_context["personality_config"] = state.personality_config

        # Forward user feedback/notes so the message generator can inject them into the writer prompt
        if state.user_feedback:
            enriched_context["user_notes"] = state.user_feedback
        
        # Use step-level language only if use_native_language is enabled
        if state.use_native_language:
            if step.message_language and step.message_language != "en":
                enriched_context["message_language"] = step.message_language
            elif state.detected_language and state.detected_language != "en":
                enriched_context["message_language"] = state.detected_language
        # If use_native_language is False, don't set message_language (defaults to English)
        
        # Retry loop: up to 2 retries per step with exponential backoff
        MAX_STEP_RETRIES = 2
        step_result = None
        last_error = None
        
        for attempt in range(MAX_STEP_RETRIES + 1):
            try:
                result = generate_message_for_step_sync(enriched_context)
                
                if result.get("success"):
                    logger.info(f"Message generated successfully for step {step_num}", 
                               extra={
                                   "correlation_id": correlation_id, 
                                   "step_number": step_num,
                                   "score": result.get("score")
                               })
                    step_result = {
                        "step_number": step_num,
                        "success": True,
                        "message": result.get("message"),
                        "subject": result.get("subject"),
                        "score": result.get("score"),
                        "error": None
                    }
                    break  # Success — exit retry loop
                else:
                    last_error = result.get("error", "Unknown error")
                    if attempt < MAX_STEP_RETRIES:
                        backoff = 2 ** attempt  # 1s, 2s
                        logger.warning(f"Step {step_num} attempt {attempt + 1}/{MAX_STEP_RETRIES + 1} failed: "
                                      f"{last_error}, retrying in {backoff}s...",
                                      extra={"correlation_id": correlation_id, "step_number": step_num})
                        time.sleep(backoff)
                    else:
                        logger.error(f"Message generation failed for step {step_num} after "
                                    f"{MAX_STEP_RETRIES + 1} attempts: {last_error}",
                                    extra={"correlation_id": correlation_id, "step_number": step_num})
                        step_result = {
                            "step_number": step_num,
                            "success": False,
                            "message": None,
                            "subject": None,
                            "score": None,
                            "error": last_error
                        }
            
            except Exception as e:
                last_error = f"Exception during message generation: {str(e)}"
                if attempt < MAX_STEP_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"Step {step_num} attempt {attempt + 1}/{MAX_STEP_RETRIES + 1} exception: "
                                  f"{str(e)}, retrying in {backoff}s...",
                                  extra={"correlation_id": correlation_id, "step_number": step_num})
                    time.sleep(backoff)
                else:
                    logger.exception(f"Exception generating message for step {step_num} after "
                                    f"{MAX_STEP_RETRIES + 1} attempts",
                                    extra={"correlation_id": correlation_id, "step_number": step_num})
                    step_result = {
                        "step_number": step_num,
                        "success": False,
                        "message": None,
                        "subject": None,
                        "score": None,
                        "error": last_error
                    }
        
        message_results.append(step_result)
    
    state.message_generation_results = message_results
    
    success_count = sum(1 for r in message_results if r.get("success"))
    total_count = len(message_results)
    
    logger.info(f"JIT message generation complete for {correlation_id}: "
               f"{success_count}/{total_count} successful", 
               extra={
                   "correlation_id": correlation_id,
                   "success_count": success_count,
                   "total_count": total_count,
                   "results": message_results
               })
    
    return state
