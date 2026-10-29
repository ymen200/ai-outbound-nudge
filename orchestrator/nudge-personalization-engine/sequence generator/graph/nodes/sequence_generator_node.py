import os
import requests
import json
import time
import threading
from typing import Dict, Any
from pydantic import ValidationError

from ..state import GraphState
from ...models.outreach_step import (
    OutreachSequence,
    ActionType,
    BUSINESS_HOURS_START,
    BUSINESS_HOURS_END,
)
from ...config.constants import (
    MAX_RETRIES,
    SAFE_FALLBACK_SEQUENCE,
    DEFAULT_LANGUAGE,
    DEFAULT_LANGUAGE_NAME,
    DEFAULT_TIMEZONE_OFFSET,
    DEFAULT_TIMEZONE_NAME,
    APPROVAL_MODE_PER_SEQUENCE,
    DEFAULT_MAX_TOUCHES,
)
from ...observability.logging_config import logger
from ...observability.observability_store import prompt_store, PromptRecord, runtime_config
from ...tools.language_detector import detect_language_with_gemini_fallback, detect_timezone_with_fallback
from ...middleware.token_counter import TokenCounter

# Gemini Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "models/gemma-3-27b-it")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "2048"))

# ── InMail enforcement flags ──
# These can be toggled via env vars so behavior can be changed without code edits.
ENFORCE_INMAIL_WHEN_CREDITS_AVAILABLE = os.getenv(
    "ENFORCE_INMAIL_WHEN_CREDITS_AVAILABLE", "true"
).lower() in ("1", "true", "yes")
INMAIL_FALLBACK_TO_CONNECT_IF_NO_CREDITS = os.getenv(
    "INMAIL_FALLBACK_TO_CONNECT_IF_NO_CREDITS", "true"
).lower() in ("1", "true", "yes")


# Module-level token counter + feedback store
_seq_token_counter = TokenCounter()
_pending_feedback: dict = {}  # lead_id -> list of feedback strings; "__shared__" for unscoped
_feedback_lock = threading.Lock()


def _collect_feedback_for_lead(lead_id: str) -> str:
    """
    Atomically collect and clear all pending feedback for a specific lead.

    Looks up lead_id-specific feedback first, then falls back to the shared
    bucket ("__shared__"). The check-then-clear is guarded by a lock so two
    concurrent threads cannot both read the same feedback.
    """
    with _feedback_lock:
        parts = []
        lead_fb = _pending_feedback.pop(lead_id, [])
        if lead_fb:
            parts.extend(lead_fb)
        shared_fb = _pending_feedback.pop("__shared__", [])
        if shared_fb:
            parts.extend(shared_fb)
    if parts:
        return "\n\n".join(f"SYSTEM DIRECTIVE (from global orchestrator):\n{fb}" for fb in parts)
    return ""


def _build_gemini_url(model_name: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"


def _gemini_rate_limit_backoff(attempt: int):
    """
    API-layer rate-limit backoff — exponential backoff for Gemini API calls.
    ASSUMPTION: This is purely an API concern and must NEVER influence
    OutreachStep.wait_delay_seconds or any sequence timing value.
    """
    sleep_time = min(2 ** attempt, 60)  # Max 60 seconds
    logger.info(
        f"_gemini_rate_limit_backoff: Sleeping for {sleep_time} seconds (attempt {attempt}).",
        extra={"attempt": attempt, "sleep_time": sleep_time},
    )
    time.sleep(sleep_time)


def _call_gemini_with_json_response(
    prompt: str,
    use_fallback: bool = False,
    attempt: int = 0,
    correlation_id: str = "",
    lead_id: str = "",
) -> str:
    """
    Calls the Gemini API with a prompt and returns the raw JSON response text.

    This is a low-level helper that handles:
    - Model selection (primary vs fallback model based on use_fallback)
    - Rate-limit backoff (exponential sleep on 429/5xx responses)
    - Feedback injection (prepends any pending feedback for the lead to the prompt)
    - Logging and token counting

    Parameters
    ----------
    prompt : str
        The full prompt to send to Gemini, including schema instructions and context.
    use_fallback : bool, default False
        If True, uses GEMINI_FALLBACK_MODEL (e.g., Gemma) instead of the primary model.
        Typically set to True after the primary model fails or is rate-limited.
    attempt : int, default 0
        Zero-based attempt index. Used for logging and backoff calculation.
    correlation_id : str, default ""
        Usually the lead_id. Used for structured logging correlation.
    lead_id : str, default ""
        Used to look up and consume any pending feedback scoped to this lead.

    Returns
    -------
    str
        The raw JSON text from Gemini's response. Caller is responsible for parsing
        and validating (e.g., via OutreachSequence.model_validate_json).

    Raises
    ------
    RuntimeError
        If all retry attempts fail (network errors, rate limits, or empty responses).

    Note
    ----
    Rate-limit sleeps inside this function are purely API-layer concerns and have
    NO effect on sequence timing (wait_delay_seconds on OutreachStep).
    """
    model = GEMINI_FALLBACK_MODEL if use_fallback else GEMINI_MODEL
    url = _build_gemini_url(model)

    logger.info(
        f"Gemini API call attempt {attempt + 1} for correlation_id={correlation_id}, "
        f"model={model}, use_fallback={use_fallback}.",
        extra={
            "correlation_id": correlation_id,
            "attempt": attempt + 1,
            "model": model,
            "use_fallback": use_fallback,
        },
    )

    # Collect feedback scoped to this lead (atomic check-then-clear)
    feedback_block = _collect_feedback_for_lead(lead_id)
    actual_prompt = f"{feedback_block}\n\n{prompt}" if feedback_block else prompt

    # Log feedback injection for observability / recording
    if feedback_block:
        logger.info(
            f"FEEDBACK INJECTED for lead {lead_id}: {feedback_block[:500]}",
            extra={"correlation_id": correlation_id, "feedback_length": len(feedback_block)},
        )
    else:
        logger.info(
            f"No pending feedback for lead {lead_id} — prompt sent as-is.",
            extra={"correlation_id": correlation_id},
        )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GOOGLE_API_KEY,
    }
    payload = {
        "contents": [{"role": "user", "parts": [{"text": actual_prompt}]}],
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
        },
    }

    if not GOOGLE_API_KEY:
        return json.dumps({"error": "GOOGLE_API_KEY not configured."})

    call_start = time.time()
    model_used = "fallback" if use_fallback else "primary"
    response_text = None
    error_msg = None
    success = True

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        response_text = response_data["candidates"][0]["content"]["parts"][0]["text"]

        # Gemini often wraps JSON in markdown code blocks — strip them
        if response_text.startswith("```json") and response_text.endswith("```"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```") and response_text.endswith("```"):
            response_text = response_text[3:-3].strip()

        # ── Record actual provider token usage (not estimation) ──
        usage = response_data.get("usageMetadata", {})
        latency_ms = (time.time() - call_start) * 1000
        prompt_store.record(PromptRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            module="sequence_generator",
            agent_step="sequence_generator",
            prompt=actual_prompt[:5000],
            response=response_text[:5000],
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            model_used=model_used,
            latency_ms=round(latency_ms, 2),
            success=True,
        ))

        return response_text

    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        success = False
        logger.warning(
            f"Gemini API request failed: {e}. "
            f"{'Attempting fallback.' if not use_fallback else 'Fallback also failed.'}",
            extra={"error": str(e), "model": model, "correlation_id": correlation_id},
        )
        if not use_fallback:
            return _call_gemini_with_json_response(
                prompt, use_fallback=True, attempt=attempt,
                correlation_id=correlation_id,
                lead_id=lead_id,
            )
        else:
            return json.dumps(
                {"error": f"Gemini API request failed (fallback also failed): {str(e)}"}
            )
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        error_msg = str(e)
        success = False
        logger.warning(
            f"Gemini response parsing failed: {e}.",
            extra={
                "error": str(e),
                "model": model,
                "correlation_id": correlation_id,
                "raw_response": response.text if "response" in locals() else "N/A",
            },
        )
        return json.dumps({"error": f"Gemini response parsing failed: {str(e)}"})
    except Exception as e:
        error_msg = str(e)
        success = False
        logger.error(
            f"Unexpected error during Gemini call: {e}",
            extra={"error": str(e), "model": model, "correlation_id": correlation_id},
        )
        return json.dumps({"error": f"Unexpected error during Gemini call: {str(e)}"})


def _enforce_inmail_rules(sequence: OutreachSequence, state: GraphState) -> OutreachSequence:
    """
    Server-side enforcement of LinkedIn InMail routing rules.

    This corrects Gemini output when the prompt instructions are ignored:
    - If InMail credits are available AND not connected: the first LinkedIn step
      MUST be LINKEDIN_INMAIL on channel linkedin_inmail.
    - If no InMail credits: any LINKEDIN_INMAIL step is downgraded to
      LINKEDIN_CONNECT on channel linkedin_dm.

    Behavior is controlled by env vars:
      ENFORCE_INMAIL_WHEN_CREDITS_AVAILABLE (default true)
      INMAIL_FALLBACK_TO_CONNECT_IF_NO_CREDITS (default true)
    """
    if not sequence.steps:
        return sequence

    # Find first LinkedIn step
    first_linkedin_idx = None
    for i, step in enumerate(sequence.steps):
        if "LINKEDIN" in step.action_type.value.upper() or "linkedin" in step.channel:
            first_linkedin_idx = i
            break

    if first_linkedin_idx is None:
        return sequence

    step = sequence.steps[first_linkedin_idx]
    inmail_available = state.has_inmail_credits and not state.is_connected_on_linkedin

    if inmail_available and ENFORCE_INMAIL_WHEN_CREDITS_AVAILABLE:
        if step.action_type != ActionType.LINKEDIN_INMAIL or step.channel != "linkedin_inmail":
            old_action = step.action_type.value
            old_channel = step.channel
            step.action_type = ActionType.LINKEDIN_INMAIL
            step.channel = "linkedin_inmail"
            logger.warning(
                f"Enforced InMail routing for lead {state.lead_id}: "
                f"step {step.step_number} changed from {old_action}/{old_channel} "
                f"to LINKEDIN_INMAIL/linkedin_inmail.",
                extra={
                    "correlation_id": state.lead_id,
                    "step_number": step.step_number,
                    "old_action": old_action,
                    "old_channel": old_channel,
                },
            )

    elif not state.has_inmail_credits and INMAIL_FALLBACK_TO_CONNECT_IF_NO_CREDITS:
        if step.action_type == ActionType.LINKEDIN_INMAIL or step.channel == "linkedin_inmail":
            old_action = step.action_type.value
            old_channel = step.channel
            step.action_type = ActionType.LINKEDIN_CONNECT
            step.channel = "linkedin_dm"
            logger.warning(
                f"Downgraded InMail to LinkedIn Connect for lead {state.lead_id} "
                f"(no InMail credits): step {step.step_number} changed from "
                f"{old_action}/{old_channel} to LINKEDIN_CONNECT/linkedin_dm.",
                extra={
                    "correlation_id": state.lead_id,
                    "step_number": step.step_number,
                    "old_action": old_action,
                    "old_channel": old_channel,
                },
            )

    return sequence


def generate_sequence(state: GraphState) -> GraphState:
    """
    Generates an outreach sequence using Gemini with a self-correction loop.

    This node function performs ONE pass of sequence generation:
      1. Detect language and timezone from contact_info location.
      2. Build a Gemini prompt with the Pydantic JSON schema + context.
      3. Call Gemini and validate the response via OutreachSequence.model_validate_json().
      4. Enforce server-side step count limit (effective_max_touches).
      5. On validation failure: record error, increment retry_count, and return.
         The GRAPH (see builder.py) decides whether to retry or fall back.
      6. On success: set validated_sequence and return.

    IMPORTANT: This function does NOT loop internally. The retry/fallback logic
    is controlled by the LangGraph workflow in builder.py:
      - If validated_sequence is None and retry_count < MAX_RETRIES, the graph
        routes back to this node for another attempt.
      - If retry_count >= MAX_RETRIES, the graph routes to END and the caller
        receives the fallback sequence.

    Parameters
    ----------
    state : GraphState
        The current graph state, including lead_id, contact_info, contexte_web,
        max_touches (optional), and any accumulated validation_errors.

    Returns
    -------
    GraphState
        Updated state with validated_sequence set (on success) or None (on failure),
        retry_count incremented, and validation_errors appended if any.
    """
    correlation_id = state.lead_id
    logger.info(
        f"Starting sequence generation for lead {state.lead_id}",
        extra={"correlation_id": correlation_id},
    )

    # ── Step 0: Apply explicit language override ──
    if state.message_language:
        state.detected_language = state.message_language
        state.detected_language_name = state.message_language  # Use ISO code as display name fallback

    # ── Step 1: Language Detection ──
    if not state.detected_language:
        location = state.contact_info.get("location") or state.contact_info.get("city") or state.contact_info.get("country")
        iso_code, lang_name = detect_language_with_gemini_fallback(
            location=location,
            contact_info=state.contact_info,
        )
        state.detected_language = iso_code
        state.detected_language_name = lang_name
        logger.info(
            f"Language detected for lead {state.lead_id}: "
            f"{iso_code} ({lang_name}).",
            extra={
                "correlation_id": correlation_id,
                "detected_language": iso_code,
                "detected_language_name": lang_name,
            },
        )

    # ── Step 1b: Timezone Detection ──
    if state.detected_timezone is None:
        location = state.contact_info.get("location") or state.contact_info.get("city") or state.contact_info.get("country")
        tz_offset, tz_name = detect_timezone_with_fallback(
            location=location,
            contact_info=state.contact_info,
        )
        state.detected_timezone = tz_offset
        state.detected_timezone_name = tz_name
        logger.info(
            f"Timezone detected for lead {state.lead_id}: "
            f"UTC{tz_offset:+d} ({tz_name}).",
            extra={
                "correlation_id": correlation_id,
                "detected_timezone": tz_offset,
                "detected_timezone_name": tz_name,
            },
        )

    # Ensure approval_mode is set
    if not state.approval_mode:
        state.approval_mode = APPROVAL_MODE_PER_SEQUENCE

    contact = state.contact_info
    contexte = state.contexte_web
    current_retry_count = state.retry_count

    # ── Step 2: Build the prompt with Pydantic schema + language context ──
    schema_json = OutreachSequence.model_json_schema()

    language_instruction = ""
    if state.use_native_language and state.detected_language and state.detected_language != "en":
        language_instruction = f"""
    LANGUAGE DETECTION:
    - The prospect's primary language is: {state.detected_language_name} (ISO: {state.detected_language}).
    - Set `detected_language` to "{state.detected_language}" at the sequence level.
    - Set `message_language` to "{state.detected_language}" on every step (this tells the message generator what language to write the outreach message in).
    - IMPORTANT: `timing_justification` and `sequence_architecture_rationale` MUST always be written in English.
"""

    timezone_instruction = ""
    if state.detected_timezone is not None and state.detected_timezone != 0:
        tz_display = f"UTC{state.detected_timezone:+d}"
        # Calculate local business hours in UTC terms for the prompt
        local_start_utc = BUSINESS_HOURS_START - state.detected_timezone
        local_end_utc = BUSINESS_HOURS_END - state.detected_timezone
        timezone_instruction = f"""
    TIMEZONE AWARENESS:
    - The prospect's timezone is: {state.detected_timezone_name} ({tz_display}).
    - Set `detected_timezone` to {state.detected_timezone} and `detected_timezone_name` to "{state.detected_timezone_name}" at the sequence level.
    - Schedule messages so they arrive during the prospect's LOCAL business hours (8:00-18:00 {state.detected_timezone_name}).
    - This means UTC timestamps should be between {local_start_utc:02d}:00 and {local_end_utc:02d}:00 UTC.
    - Wrap hours: if local_start_utc is negative (e.g., -1), it means 23:00 UTC the previous day.
"""


    approval_instruction = f"""
    APPROVAL MODE:
    - Set `approval_mode` to "{state.approval_mode}".
"""

    # ── Build AI Sequence Configuration instructions ──
    effective_max_touches = state.max_touches if state.max_touches is not None else DEFAULT_MAX_TOUCHES

    seq_config_parts = []
    seq_config_parts.append(f"- MAX TOUCHES: The sequence MUST have at most {effective_max_touches} steps. Do not exceed this limit.")
    if state.max_days is not None:
        seq_config_parts.append(f"- MAX DAYS OVERRIDE: The entire sequence MUST complete within {state.max_days} days from the first step. Do not schedule steps beyond this window.")
    if state.preferred_first_channel:
        seq_config_parts.append(f"- PREFERRED FIRST CHANNEL: Use '{state.preferred_first_channel}' as the channel for step 1 if it is a valid channel for the available action types.")
    if state.sequence_options:
        opts = state.sequence_options
        opt_lines = []
        if opts.get("vary_tone"):
            opt_lines.append("Vary tone across touches (start casual, escalate to more urgent).")
        if opts.get("include_breakup"):
            opt_lines.append("Include a 'breakup' message as the final touch — a polite last-ditch message leaving the door open.")
        if opts.get("reference_previous"):
            opt_lines.append("Reference previous messages in follow-ups to create continuity.")
        if opts.get("escalate_urgency"):
            opt_lines.append("Escalate urgency with each successive touch.")
        if opts.get("cross_channel"):
            opt_lines.append("Try cross-channel outreach if earlier touches used a single channel.")
        if opt_lines:
            seq_config_parts.append("- SEQUENCE OPTIONS (apply these):\n  " + "\n  ".join(opt_lines))
    if state.stage_instructions:
        si_lines = [f"  - {stage}: {instr}" for stage, instr in state.stage_instructions.items()]
        seq_config_parts.append("- STAGE-SPECIFIC INSTRUCTIONS (embed these in step_context as 'stage_instruction' for the corresponding stage):\n" + "\n".join(si_lines))

    seq_config_instruction = ""
    if seq_config_parts:
        seq_config_instruction = "\n    AI SEQUENCE CONFIGURATION:\n" + "\n".join(seq_config_parts) + "\n"

    # ── Human Feedback Injection ──
    user_notes_instruction = ""
    if state.user_feedback:
        user_notes_instruction = f"""
    USER NOTES (human feedback):
    - {state.user_feedback}
    Take this feedback into account when generating the sequence.
"""
        logger.info(
            f"USER FEEDBACK INJECTED for lead {state.lead_id}: {state.user_feedback[:500]}",
            extra={"correlation_id": correlation_id, "feedback_length": len(state.user_feedback)},
        )

    base_prompt = f"""
    You are an expert B2B sales strategist and sequence designer. Your task is to generate
    a personalized outreach sequence for a prospect. You MUST adhere to the provided JSON schema.

    PROSPECT: {contact.get('nom', contact.get('full_name', 'Unknown'))} ({contact.get('titre', contact.get('job_title', ''))}) chez {state.entreprise}.
    LINKEDIN CONNECTION STATUS: {'Already connected — you MUST use LINKEDIN_MESSAGE for LinkedIn steps.' if state.is_connected_on_linkedin else ('NOT connected but InMail credits are available — you MUST use action_type "LINKEDIN_INMAIL" with channel "linkedin_inmail" for the first LinkedIn step. InMail delivers a premium message directly without needing a connection request.' if (state.has_inmail_credits) else 'NOT connected and no InMail credits — you MUST use LINKEDIN_CONNECT for the first LinkedIn step, NOT LINKEDIN_MESSAGE.')}
    LINKEDIN INMAIL: {'AVAILABLE — you MUST use LINKEDIN_INMAIL (action_type) with channel "linkedin_inmail" for the first LinkedIn step. This is required when InMail credits are available and not connected.' if (state.has_inmail_credits and not state.is_connected_on_linkedin) else 'Not available (no InMail credits or already connected).'}
    INFOS WEB: {contexte.get('profil_brut', 'No web context available.')}
{language_instruction}{timezone_instruction}{approval_instruction}{seq_config_instruction}{user_notes_instruction}
    JSON SCHEMA: {json.dumps(schema_json, indent=2)}

    Instructions for sequence generation:
    1. Analyze the prospect's profile and web context to identify key interests and activity patterns.
    2. Propose a multi-step outreach sequence using ONLY the allowed ActionType values from the schema.
       Allowed ActionTypes: LINKEDIN_CONNECT, LINKEDIN_MESSAGE, LINKEDIN_INMAIL, EMAIL_1
       - LINKEDIN_CONNECT: Connection request (use ONLY when NOT connected AND no InMail credits available)
       - LINKEDIN_MESSAGE: Direct DM (use only when ALREADY connected)
       - LINKEDIN_INMAIL: Premium InMail message (PREFERRED when NOT connected AND InMail credits are available; channel MUST be "linkedin_inmail")
       - EMAIL_1: Email touch
    3. For each step, provide a `scheduled_timestamp` (ISO-8601 UTC, within business hours 08:00-18:00, not on weekends).
    4. The `wait_delay_seconds` for each step should be the delay from the *previous* step. The first step should have `wait_delay_seconds: 0`.
    5. Provide clear `timing_justification` and `sequence_architecture_rationale` (min 10 characters each) for every step.
    6. Ensure `step_number` is strictly increasing and contiguous starting from 1.
    7. Ensure `scheduled_timestamp` is strictly increasing across steps.
    8. Each step MUST include a valid `channel` field (one of: email, linkedin_dm, linkedin_inmail).
    9. Include `step_context` on each step with the prospect name, company, role, and any relevant context for message generation.
    10. The sequence should be realistic and effective for B2B outreach.

    Return ONLY the JSON object, formatted according to the OutreachSequence schema.
    """

    prompt_to_send = base_prompt
    if state.validation_errors:
        error_message = state.validation_errors[-1]
        logger.warning(
            f"Retrying generation due to validation error "
            f"(attempt {current_retry_count + 1}/{MAX_RETRIES}): {error_message[:200]}",
            extra={
                "correlation_id": correlation_id,
                "retry_count": current_retry_count + 1,
                "error": error_message,
            },
        )

        corrective_instruction = (
            f"Your previous output failed validation with the following error:\n\n"
            f"{error_message}\n\n"
            f"Your previous invalid JSON output was:\n\n"
            f"{state.raw_llm_output[:2000] if state.raw_llm_output else 'N/A'}\n\n"
            f"Correct ONLY the offending field(s) to fix this validation error and "
            f"return the full corrected JSON object. Do NOT change any other fields "
            f"unless directly impacted by the correction. Ensure the entire JSON structure "
            f"is present in your response."
        )
        prompt_to_send = f"{base_prompt}\n\n{corrective_instruction}"

    # ── Step 3: Call Gemini ──
    gemini_response_text = _call_gemini_with_json_response(
        prompt_to_send,
        attempt=current_retry_count,
        correlation_id=correlation_id,
        lead_id=state.lead_id,
    )
    state.raw_llm_output = gemini_response_text

    # ── Step 4: Validate ──
    try:
        sequence = OutreachSequence.model_validate_json(gemini_response_text)

        # Enforce max touches limit server-side (not just prompt-level)
        if len(sequence.steps) > effective_max_touches:
            raise ValueError(
                f"Sequence has {len(sequence.steps)} steps, which exceeds "
                f"the maximum of {effective_max_touches} steps."
            )

        # Ensure language fields are populated on the validated sequence
        if not sequence.detected_language and state.detected_language:
            sequence.detected_language = state.detected_language
        if sequence.detected_timezone is None and state.detected_timezone is not None:
            sequence.detected_timezone = state.detected_timezone
            sequence.detected_timezone_name = state.detected_timezone_name
        if not sequence.approval_mode:
            sequence.approval_mode = state.approval_mode

        # Populate step_context if the LLM didn't include it
        for step in sequence.steps:
            if not step.step_context:
                step.step_context = {
                    "prospect_name": contact.get("nom", contact.get("full_name", "")),
                    "prospect_company": state.entreprise,
                    "prospect_role": contact.get("titre", contact.get("job_title", "")),
                    "prospect_email": contact.get("email", ""),
                    "prospect_location": contact.get("location", contact.get("city", "")),
                    "is_connected_on_linkedin": state.is_connected_on_linkedin,
                    "offer_context": state.contexte_web.get("offer_context", ""),
                    "icp_description": state.contexte_web.get("icp_description", ""),
                }
            # Ensure message_language respects use_native_language preference
            if not step.message_language:
                if state.use_native_language and state.detected_language:
                    step.message_language = state.detected_language
                else:
                    step.message_language = DEFAULT_LANGUAGE

            # Inject stage_instructions into step_context so message generator receives them
            if state.stage_instructions and step.step_context is not None:
                # Map step number to stage key (1=first_touch, 2=second_touch, 3+=third_touch)
                stage_key = {1: "first_touch", 2: "second_touch"}.get(step.step_number, "third_touch")
                stage_instr = state.stage_instructions.get(stage_key, "")
                if stage_instr:
                    step.step_context["stage_instruction"] = stage_instr

        # Enforce InMail routing rules server-side (can be disabled via env vars)
        sequence = _enforce_inmail_rules(sequence, state)

        state.validated_sequence = sequence
        state.retry_count = 0
        state.sequence_strategy = {"source": "gemini", "retry_count": current_retry_count}

        logger.info(
            f"Successfully generated and validated sequence for lead {state.lead_id}. "
            f"Retries consumed: {current_retry_count}. "
            f"Steps: {len(sequence.steps)}. "
            f"Language: {sequence.detected_language}. "
            f"Timezone: UTC{sequence.detected_timezone:+d} ({sequence.detected_timezone_name}). "
            f"Approval mode: {sequence.approval_mode}.",
            extra={
                "correlation_id": correlation_id,
                "retries_consumed": current_retry_count,
                "step_count": len(sequence.steps),
                "detected_language": sequence.detected_language,
                "approval_mode": sequence.approval_mode,
            },
        )

        # Log each step for audit trail
        for step in sequence.steps:
            logger.info(
                f"Step {step.step_number}: {step.action_type.value} via {step.channel} "
                f"at {step.scheduled_timestamp.isoformat()} "
                f"(wait: {step.wait_delay_seconds}s, lang: {step.message_language}). "
                f"Justification: {step.timing_justification}",
                extra={
                    "correlation_id": correlation_id,
                    "step_number": step.step_number,
                    "action_type": step.action_type.value,
                    "channel": step.channel,
                    "scheduled_timestamp": step.scheduled_timestamp.isoformat(),
                    "wait_delay_seconds": step.wait_delay_seconds,
                    "message_language": step.message_language,
                    "timing_justification": step.timing_justification,
                },
            )

    except (ValidationError, ValueError) as e:
        state.validation_errors.append(str(e))
        state.retry_count += 1
        logger.warning(
            f"Sequence validation failed for lead {state.lead_id}. "
            f"Retry {state.retry_count}/{MAX_RETRIES}. Error: {str(e)[:500]}",
            extra={
                "correlation_id": correlation_id,
                "retry_count": state.retry_count,
                "error": str(e),
            },
        )

        if state.retry_count >= MAX_RETRIES:
            # ── Step 5: Fallback ──
            if SAFE_FALLBACK_SEQUENCE:
                # Deep copy to avoid mutating the shared constant
                fallback = SAFE_FALLBACK_SEQUENCE.model_copy(deep=True)
                # Override lead/campaign IDs and language
                fallback.lead_id = state.lead_id
                fallback.campaign_id = state.campaign_id
                fallback.detected_language = state.detected_language or DEFAULT_LANGUAGE
                fallback.detected_timezone = state.detected_timezone if state.detected_timezone is not None else DEFAULT_TIMEZONE_OFFSET
                fallback.detected_timezone_name = state.detected_timezone_name or DEFAULT_TIMEZONE_NAME
                fallback.approval_mode = state.approval_mode or APPROVAL_MODE_PER_SEQUENCE
                state.validated_sequence = fallback
                state.fallback_triggered = True
                state.sequence_strategy = {"source": "fallback", "retry_count": state.retry_count}

                logger.critical(
                    f"Max retries ({MAX_RETRIES}) reached for lead {state.lead_id}. "
                    f"Falling back to safe sequence. "
                    f"All validation errors: {state.validation_errors}",
                    extra={
                        "correlation_id": correlation_id,
                        "all_errors": state.validation_errors,
                        "fallback_triggered": True,
                    },
                )
            else:
                logger.critical(
                    f"Max retries reached but SAFE_FALLBACK_SEQUENCE is None. "
                    f"Cannot recover for lead {state.lead_id}. "
                    f"Errors: {state.validation_errors}",
                    extra={
                        "correlation_id": correlation_id,
                        "all_errors": state.validation_errors,
                    },
                )
                state.validated_sequence = None

    return state
