from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from ..state import GraphState
from ...models.outreach_step import OutreachStep, BUSINESS_HOURS_START, BUSINESS_HOURS_END
from ...config.constants import MIN_WAIT_SECONDS, MAX_WAIT_SECONDS
from ...observability.logging_config import logger


def _utc_to_local(dt: datetime, tz_offset_hours: int) -> datetime:
    """Convert a UTC datetime to a prospect-local datetime (naive, no tzinfo)."""
    local_tz = timezone(timedelta(hours=tz_offset_hours))
    return dt.astimezone(local_tz)


def _local_to_utc(dt: datetime, tz_offset_hours: int) -> datetime:
    """Convert a prospect-local datetime (treated as the given offset) back to UTC."""
    local_tz = timezone(timedelta(hours=tz_offset_hours))
    local_aware = dt.replace(tzinfo=local_tz)
    return local_aware.astimezone(timezone.utc)


def _roll_forward_to_next_business_slot(
    dt: datetime, tz_offset_hours: int = 0
) -> datetime:
    """
    Rolls a UTC datetime forward to the next valid business day and hour
    IN THE PROSPECT'S LOCAL TIMEZONE.

    Business hours are defined as BUSINESS_HOURS_START..BUSINESS_HOURS_END
    in local time. Weekends (Sat/Sun) are in local time.

    Args:
        dt: A UTC datetime.
        tz_offset_hours: Prospect's UTC offset in hours (e.g., 1 for CET, -5 for EST).

    Returns:
        A UTC datetime that falls within the prospect's local business hours.
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)

    # Convert to local time for business-hour checks
    local_dt = _utc_to_local(dt, tz_offset_hours)

    # Roll forward to next business day if on weekend (local time)
    while local_dt.weekday() >= 5:  # Saturday (5) or Sunday (6)
        local_dt += timedelta(days=1)
        local_dt = local_dt.replace(
            hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
        )

    # Roll forward to business hours if outside (local time)
    if local_dt.hour < BUSINESS_HOURS_START:
        local_dt = local_dt.replace(
            hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
        )
    elif local_dt.hour >= BUSINESS_HOURS_END:
        local_dt += timedelta(days=1)
        local_dt = local_dt.replace(
            hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
        )
        # Re-check for weekend after advancing a day
        while local_dt.weekday() >= 5:
            local_dt += timedelta(days=1)
            local_dt = local_dt.replace(
                hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
            )

    # Convert back to UTC
    return _local_to_utc(local_dt, tz_offset_hours)


def sandbox_sequence(state: GraphState) -> GraphState:
    """Deterministically clip timing values using prospect-local business hours."""
    if not state.validated_sequence:
        logger.warning(
            "Sandbox node received no validated_sequence. Skipping.",
            extra={"correlation_id": state.lead_id},
        )
        return state

    correlation_id = state.lead_id
    tz_offset = state.detected_timezone or 0
    tz_name = state.detected_timezone_name or "UTC"

    logger.info(
        f"Running sandbox for sequence {correlation_id} "
        f"(timezone: UTC{tz_offset:+d} / {tz_name})",
        extra={
            "correlation_id": correlation_id,
            "timezone_offset": tz_offset,
            "timezone_name": tz_name,
        },
    )

    adjusted_steps: List[OutreachStep] = []

    # If the first step has a scheduled_timestamp, use it as the baseline.
    if state.validated_sequence.steps and state.validated_sequence.steps[0].scheduled_timestamp:
        current_timestamp = state.validated_sequence.steps[0].scheduled_timestamp
    else:
        current_timestamp = datetime.now(timezone.utc)

    for i, step in enumerate(state.validated_sequence.steps):
        original_wait_delay = step.wait_delay_seconds
        adjusted_wait_delay = original_wait_delay

        # 1. Clip wait_delay_seconds
        if adjusted_wait_delay < MIN_WAIT_SECONDS:
            adjusted_wait_delay = MIN_WAIT_SECONDS
            state.sandbox_adjustments.append({
                "step_number": step.step_number,
                "field": "wait_delay_seconds",
                "original_value": original_wait_delay,
                "adjusted_value": adjusted_wait_delay,
                "reason": f"Clipped to MIN_WAIT_SECONDS ({MIN_WAIT_SECONDS}s)",
            })
            logger.info(
                f"Step {step.step_number}: Clipped wait_delay_seconds "
                f"from {original_wait_delay} to {adjusted_wait_delay}.",
                extra={
                    "correlation_id": correlation_id,
                    "step_number": step.step_number,
                },
            )
        elif adjusted_wait_delay > MAX_WAIT_SECONDS:
            adjusted_wait_delay = MAX_WAIT_SECONDS
            state.sandbox_adjustments.append({
                "step_number": step.step_number,
                "field": "wait_delay_seconds",
                "original_value": original_wait_delay,
                "adjusted_value": adjusted_wait_delay,
                "reason": f"Clipped to MAX_WAIT_SECONDS ({MAX_WAIT_SECONDS}s)",
            })
            logger.info(
                f"Step {step.step_number}: Clipped wait_delay_seconds "
                f"from {original_wait_delay} to {adjusted_wait_delay}.",
                extra={
                    "correlation_id": correlation_id,
                    "step_number": step.step_number,
                },
            )

        # 2. Recompute scheduled_timestamp with timezone-aware business hours
        if i == 0:
            new_scheduled_timestamp = _roll_forward_to_next_business_slot(
                step.scheduled_timestamp, tz_offset_hours=tz_offset
            )
            if new_scheduled_timestamp != step.scheduled_timestamp:
                local_old = _utc_to_local(step.scheduled_timestamp, tz_offset)
                local_new = _utc_to_local(new_scheduled_timestamp, tz_offset)
                state.sandbox_adjustments.append({
                    "step_number": step.step_number,
                    "field": "scheduled_timestamp",
                    "original_value": step.scheduled_timestamp.isoformat(),
                    "adjusted_value": new_scheduled_timestamp.isoformat(),
                    "original_local": local_old.isoformat(),
                    "adjusted_local": local_new.isoformat(),
                    "reason": (
                        f"Adjusted for {tz_name} business hours/weekend "
                        f"(local: {local_old.strftime('%H:%M')} → {local_new.strftime('%H:%M')})"
                    ),
                })
                logger.info(
                    f"Step {step.step_number}: Adjusted initial timestamp "
                    f"UTC {step.scheduled_timestamp.strftime('%H:%M')} → "
                    f"{new_scheduled_timestamp.strftime('%H:%M')} "
                    f"(local {local_old.strftime('%H:%M')} → {local_new.strftime('%H:%M')} {tz_name})."
                )
        else:
            previous_step_timestamp = adjusted_steps[i - 1].scheduled_timestamp
            raw_new_timestamp = previous_step_timestamp + timedelta(
                seconds=adjusted_wait_delay
            )
            new_scheduled_timestamp = _roll_forward_to_next_business_slot(
                raw_new_timestamp, tz_offset_hours=tz_offset
            )

            if new_scheduled_timestamp != step.scheduled_timestamp:
                local_new = _utc_to_local(new_scheduled_timestamp, tz_offset)
                state.sandbox_adjustments.append({
                    "step_number": step.step_number,
                    "field": "scheduled_timestamp",
                    "original_value": step.scheduled_timestamp.isoformat(),
                    "adjusted_value": new_scheduled_timestamp.isoformat(),
                    "adjusted_local": local_new.isoformat(),
                    "reason": (
                        f"Recomputed from previous step + adjusted wait ({adjusted_wait_delay}s) "
                        f"and adjusted for {tz_name} business hours/weekend."
                    ),
                })
                logger.info(
                    f"Step {step.step_number}: Recomputed timestamp "
                    f"to UTC {new_scheduled_timestamp.strftime('%Y-%m-%d %H:%M')} "
                    f"(local {local_new.strftime('%H:%M')} {tz_name})."
                )

        # Create a new OutreachStep with adjusted values
        adjusted_step = OutreachStep(
            step_number=step.step_number,
            action_type=step.action_type,
            channel=step.channel,
            scheduled_timestamp=new_scheduled_timestamp,
            wait_delay_seconds=adjusted_wait_delay,
            timing_justification=step.timing_justification,
            sequence_architecture_rationale=step.sequence_architecture_rationale,
            message_language=step.message_language,
            step_context=step.step_context,
        )
        adjusted_steps.append(adjusted_step)

    state.validated_sequence.steps = adjusted_steps
    logger.info(
        f"Sandbox processing complete for sequence {correlation_id}. "
        f"Total adjustments: {len(state.sandbox_adjustments)}",
        extra={
            "correlation_id": correlation_id,
            "total_adjustments": len(state.sandbox_adjustments),
        },
    )
    return state
