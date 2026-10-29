from typing import Dict, Any, List
from ..models.outreach_step import OutreachSequence, OutreachStep
from ..observability.logging_config import logger

def adapt_to_temporal(sequence: OutreachSequence, correlation_id: str) -> Dict[str, Any]:
    """Converts a validated OutreachSequence into the format expected by Temporal workflows."""
    logger.info(f"Adapting OutreachSequence to Temporal payload for {correlation_id}.", extra={"correlation_id": correlation_id})

    temporal_steps: List[Dict[str, Any]] = []
    for step in sequence.steps:
        temporal_step = {
            "step_number": step.step_number,
            "action_type": step.action_type.value,  # Send enum value as string
            "channel": step.channel,
            "scheduled_timestamp_utc": step.scheduled_timestamp.isoformat(),  # ISO-8601 string
            "wait_delay_seconds": step.wait_delay_seconds,
            "timing_justification": step.timing_justification,
            "sequence_architecture_rationale": step.sequence_architecture_rationale,
            "message_language": step.message_language,
            "step_context": step.step_context,
        }

        # Include JIT message generation config if step_context is present
        if step.step_context:
            temporal_step["message_generation_config"] = {
                "target_prospect": step.step_context.get("target_prospect"),
                "target_company": step.step_context.get("target_company"),
                "company_name": step.step_context.get("company_name"),
                "offer_name": step.step_context.get("offer_name"),
                "prospect_role": step.step_context.get("prospect_role"),
                "channel": step.channel,
                "message_language": step.message_language or sequence.detected_language,
            }

        temporal_steps.append(temporal_step)

    temporal_payload = {
        "lead_id": sequence.lead_id,
        "campaign_id": sequence.campaign_id,
        "generated_at_utc": sequence.generated_at.isoformat(),
        "detected_language": sequence.detected_language,
        "detected_timezone": sequence.detected_timezone,
        "detected_timezone_name": sequence.detected_timezone_name,
        "approval_mode": sequence.approval_mode,
        "steps": temporal_steps
    }
    logger.info(f"Temporal payload adapted for {correlation_id}.", extra={"correlation_id": correlation_id, "temporal_payload_preview": temporal_payload})
    return temporal_payload
