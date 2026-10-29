from typing import List, Dict, Any
import uuid
import logging
from .models import (
    AgentState, Status, Strategy, MessageDraft,
    SentenceAttribution, Validation, Signal, ActionType
)
from .tools import ResearchTools, ReasoningTools
from .llm_service import llm_service
from .config import settings
from .memory import MemoryService
from .observability import pending_feedback as _pending_feedback, get_runtime_config

logger = logging.getLogger(__name__)

class AgentNodes:

    @staticmethod
    def planner(state: AgentState) -> AgentState:
        """Decides what step to run next based on what's missing"""

        needs_research = not state.research_signals
        needs_strategy = state.research_signals and not state.strategy
        needs_draft = state.strategy and not state.draft
        needs_validation = state.draft and not state.validation

        if needs_research:
            state.status = Status.RESEARCHING
            state.next_action = {
                "step": "research",
                "reason": "No research signals yet"
            }
        elif needs_strategy:
            state.status = Status.STRATEGIZING
            state.next_action = {
                "step": "strategize",
                "reason": "Research done, building strategy"
            }
        elif needs_draft:
            state.status = Status.WRITING
            state.next_action = {
                "step": "write",
                "reason": "Strategy ready, writing message"
            }
        elif needs_validation:
            state.status = Status.VALIDATING
            state.next_action = {
                "step": "validate",
                "reason": "Draft ready, validating quality"
            }
        else:
            state.status = Status.COMPLETE

        return state

    @staticmethod
    def researcher(state: AgentState) -> AgentState:
        """Gathers research signals and loads prospect memory"""

        # --- Load prospect memory (skipped in debug mode) ---
        rc = get_runtime_config()
        debug_mode = rc.get("DEBUG_MODE", settings.DEBUG_MODE)
        # Handle string "true"/"false" from orchestrator override
        if isinstance(debug_mode, str):
            debug_mode = debug_mode.lower() in ("true", "1", "yes")
        if debug_mode:
            # Debug mode: every request starts fresh, no accumulated history
            prospect_memory = MemoryService.prospects.get_or_create(
                name=state.target_prospect,
                company=state.target_company,
                role=state.prospect_role
            )
            # Still honor do_not_contact even in debug mode — it's a hard stop
            if prospect_memory.do_not_contact:
                state.status = Status.FAILED
                state.next_action = {
                    "type": ActionType.ABORT,
                    "reason": f"{state.target_prospect} is marked as do not contact"
                }
                return state
            # Fresh state — no history
            state.memory["prospect_record"] = prospect_memory.model_dump()
            state.memory["hooks_already_used"] = []
            state.memory["angles_already_tried"] = []
            state.memory["times_contacted_before"] = 0
            state.memory["ever_replied"] = False
            state.memory["last_message_sent"] = None
            state.memory["best_performing_hooks"] = []
            state.memory["best_performing_angles"] = []
            state.memory["worst_performing_hooks"] = []
            state.memory["channel_reply_rates"] = {}
            state.memory["total_messages_generated"] = 0
        else:
            # Production mode: full memory reads
            prospect_memory = MemoryService.prospects.get_or_create(
                name=state.target_prospect,
                company=state.target_company,
                role=state.prospect_role
            )

            # Hard stop if do not contact
            if prospect_memory.do_not_contact:
                state.status = Status.FAILED
                state.next_action = {
                    "type": ActionType.ABORT,
                    "reason": f"{state.target_prospect} is marked as do not contact"
                }
                return state

            # Store memory context so strategist and writer can use it
            state.memory["prospect_record"] = prospect_memory.model_dump()
            state.memory["hooks_already_used"] = prospect_memory.hooks_used
            state.memory["angles_already_tried"] = prospect_memory.angles_tried
            state.memory["times_contacted_before"] = prospect_memory.times_contacted
            state.memory["ever_replied"] = prospect_memory.ever_replied
            state.memory["last_message_sent"] = prospect_memory.last_message_sent

            # Load learning memory (system-wide performance data)
            learning = MemoryService.learning.get()
            state.memory["best_performing_hooks"] = learning.best_performing_hooks
            state.memory["best_performing_angles"] = learning.best_performing_angles
            state.memory["worst_performing_hooks"] = learning.worst_performing_hooks
            state.memory["channel_reply_rates"] = learning.channel_reply_rates
            state.memory["total_messages_generated"] = learning.total_messages_generated

            # Load offer memory if we have an offer
            if state.selected_offer:
                offer_memory = MemoryService.offers.get(state.selected_offer.offer_name)
                if offer_memory:
                    state.memory["offer_memory"] = {
                        "times_used": offer_memory.times_used,
                        "avg_quality_score": offer_memory.avg_quality_score,
                        "best_channels": offer_memory.best_channels,
                        "best_angles": offer_memory.best_angles,
                    }

        # --- HARD REQUIREMENT: research_signals must be provided by external module ---
        if not state.research_signals:
            state.status = Status.FAILED
            state.next_action = {
                "type": ActionType.ABORT,
                "reason": "research_signals is required. Must be provided by external research module (e.g., Detective)."
            }
            return state

        state.memory["total_signals_found"] = len(state.research_signals)
        state.memory["signals_source"] = "external"
        state.status = Status.STRATEGIZING
        return state

    @staticmethod
    def strategist(state: AgentState) -> AgentState:
        """Uses LLM to pick hooks and build strategy"""

        if not state.research_signals:
            state.strategy = Strategy(
                primary_hook=f"Your work at {state.target_company}",
                secondary_hook="Industry developments",
                angle="General professional connection",
                tone=state.personality.base_template.value,
                cta_style=state.selected_offer.cta if state.selected_offer else "soft_question",
                reasoning="No research signals available"
            )
            state.status = Status.WRITING
            return state

        try:
            # Step 1: Analyze signals
            analysis = llm_service.analyze_research_signals(
                signals=state.research_signals,
                prospect_name=state.target_prospect,
                company=state.target_company,
                personality=state.personality,
                hooks_already_used=state.memory.get("hooks_already_used", []),
                best_performing_hooks=state.memory.get("best_performing_hooks", []),
                best_performing_angles=state.memory.get("best_performing_angles", []),
                worst_performing_hooks=state.memory.get("worst_performing_hooks", []),
            )

            # Step 2: Build full strategy
            strategy = llm_service.create_strategy(
                primary_hook=analysis.get("primary_hook"),
                secondary_hook=analysis.get("secondary_hook"),
                prospect_name=state.target_prospect,
                company=state.target_company,
                prospect_role=state.prospect_role,
                personality=state.personality,
                company_details=state.company_details,
                selected_offer=state.selected_offer,
                channel=state.channel,
                intent=state.intent,
                stage=state.stage,
                angles_already_tried=state.memory.get("angles_already_tried", []),
                offer_best_angles=state.memory.get("offer_memory", {}).get("best_angles", []),
                language=state.language,
            )

            state.strategy = strategy

        except Exception as e:
            state.strategy = Strategy(
                primary_hook=state.research_signals[0].content,
                secondary_hook=state.research_signals[1].content if len(state.research_signals) > 1 else "",
                angle="Professional connection",
                tone=state.personality.base_template.value,
                cta_style=state.selected_offer.cta if state.selected_offer else "soft_question",
                reasoning=f"Fallback due to error: {str(e)}"
            )
            state.memory["strategist_error"] = str(e)

        state.status = Status.WRITING
        return state

    @staticmethod
    def writer(state: AgentState) -> AgentState:
        """Uses LLM to write the message, or revise it based on feedback."""

        if not state.strategy:
            state.status = Status.PLANNING
            return state

        # --- NEW: Check if this is a revision call and get the feedback ---
        is_revision = state.status == Status.REVISING
        previous_draft = state.draft.body if is_revision and state.draft else None
        feedback = state.next_action.get("feedback") if is_revision and state.next_action else None

        # Inject global orchestrator feedback if pending
        if _pending_feedback:
            orchestrator_directives = "\n".join(_pending_feedback)
            _pending_feedback.clear()
            if feedback:
                feedback = f"{feedback}\n\nGLOBAL ORCHESTRATOR DIRECTIVE:\n{orchestrator_directives}"
            else:
                feedback = f"GLOBAL ORCHESTRATOR DIRECTIVE:\n{orchestrator_directives}"

        try:
            message_data = llm_service.write_message(
                strategy=state.strategy,
                prospect_name=state.target_prospect,
                company=state.target_company,
                prospect_role=state.prospect_role,
                personality=state.personality,
                company_details=state.company_details,
                selected_offer=state.selected_offer,
                channel=state.channel,
                intent=state.intent,
                stage=state.stage,
                times_contacted_before=state.memory.get("times_contacted_before", 0),
                last_message_sent=state.memory.get("prospect_record", {}).get("last_message_sent"),
                
                # --- NEW: Pass the revision context to the LLM service ---
                is_revision=is_revision,
                previous_draft=previous_draft,
                feedback_from_critic=feedback,
                user_notes=state.user_feedback,
                language=state.language
            )

            attributions = [
                SentenceAttribution(
                    text=item.get("text", ""),
                    driven_by=item.get("driven_by", []),
                    purpose=item.get("purpose", "unknown")
                )
                for item in message_data.get("sentence_breakdown", [])
            ]

            state.draft = MessageDraft(
                body=message_data.get("body", ""),
                subject=message_data.get("subject"),
                sentence_attribution=attributions
            )

        except Exception as e:
            # Do NOT produce a fallback garbage message.
            # Instead, trigger a proper retry from scratch.
            logger.error(f"Writer LLM call failed: {e}")
            state.memory["writer_error"] = str(e)
            if state.iteration_count < state.max_iterations:
                state.status = Status.PLANNING  # Full retry from scratch
                state.iteration_count += 1
                state.draft = None
                state.strategy = None
                state.next_action = {
                    "type": ActionType.RETRY,
                    "reason": f"Writer LLM failed: {str(e)[:100]}. Retrying from scratch."
                }
            else:
                state.status = Status.FAILED
                state.next_action = {
                    "type": ActionType.ABORT,
                    "reason": f"Writer LLM failed after {state.max_iterations} attempts: {str(e)[:100]}"
                }
            return state  # Return immediately — do NOT overwrite with VALIDATING

        state.status = Status.VALIDATING
        return state

    # --- UPDATED critic FUNCTION ---
    @staticmethod
    def critic(state: AgentState) -> AgentState:
        """Uses LLM to validate the message and decides on refinement."""

        if not state.draft:
            state.status = Status.PLANNING
            return state

        try:
            validation_result = llm_service.validate_message(
                message=state.draft.body,
                prospect_name=state.target_prospect,
                channel=state.channel,
                personality=state.personality
            )

            # Post-LLM rule checks — these are deterministic and override the LLM
            # Penalties are CAPPED at -40 total to prevent death spirals where overlapping
            # checks tank a decent message. Applied in priority order (most severe first).
            MAX_DETERMINISTIC_PENALTY = 40
            total_penalty_applied = 0
            extra_issues: List[str] = []
            body_lower = state.draft.body.lower()

            # Check each issue (detection only, no penalty yet)
            placeholder_detected = ReasoningTools.detect_placeholder_text(state.draft.body)
            template_defaults = ["sender name", "sender title", "your company here", "[your name]", "[company name]", "your name here"]
            template_defaults_detected = any(td in body_lower for td in template_defaults)
            attachment_phrases = ["i've attached", "i have attached", "see attached", "i'm sending", "i'll send", "check out the link", "i sent you"]
            attachment_refs_detected = any(p in body_lower for p in attachment_phrases)
            overpersonalization_detected = ReasoningTools.detect_overpersonalization(state.draft.body)
            generic_company_detected = False
            if state.target_company and state.target_company not in ("Unknown", "Unknown Company", ""):
                generic_company_phrases = ["your company", "your organization", "your team", "your firm"]
                generic_company_detected = any(gcp in body_lower for gcp in generic_company_phrases)
            # Banned phrases: only check in Tier 3 if Tier 1 didn't already short-circuit
            banned_phrase_detected = False
            for phrase in state.personality.never_use_phrases:
                if phrase.lower() in body_lower:
                    banned_phrase_detected = True
                    break

            # Apply penalties in priority order (most severe first), capped at -40
            penalty_checks = [
                (placeholder_detected, 40, "Remove all placeholder text like [Company], [Name], [Result] — use only real data or omit entirely."),
                (template_defaults_detected, 35, "Replace literal template defaults ('Sender Name', 'Sender Title', etc.) with real data or omit them."),
                (attachment_refs_detected, 30, "Remove attachment/link references — this is a plain text message, you cannot attach or send files."),
                (overpersonalization_detected, 20, "Remove overly personal references that may feel intrusive."),
                (generic_company_detected, 15, f"Use the prospect's actual company name '{state.target_company}' instead of generic references like 'your company'."),
                (banned_phrase_detected, 10, "Remove banned phrases from the message."),
            ]

            for detected, penalty, message in penalty_checks:
                if detected:
                    extra_issues.append(message)
                    if total_penalty_applied < MAX_DETERMINISTIC_PENALTY:
                        actual_penalty = min(penalty, MAX_DETERMINISTIC_PENALTY - total_penalty_applied)
                        validation_result["score"] = max(0, validation_result["score"] - actual_penalty)
                        total_penalty_applied += actual_penalty

            if extra_issues:
                validation_result["warnings"].extend(extra_issues)
                validation_result["valid"] = False
                # Build structured, prioritized feedback for the writer
                structured_feedback = ["CRITICAL FIXES (must fix):"]
                for i, issue in enumerate(extra_issues, 1):
                    structured_feedback.append(f"{i}. {issue}")
                existing_fixes = validation_result.get("suggested_fixes") or ""
                if existing_fixes:
                    structured_feedback.append(f"\nQUALITY IMPROVEMENTS:\n{existing_fixes}")
                validation_result["suggested_fixes"] = "\n".join(structured_feedback)

            # Final safety: if score is below threshold, force valid=False
            if validation_result.get("score", 0) < settings.MIN_QUALITY_SCORE:
                validation_result["valid"] = False

            state.validation = Validation(**validation_result)
        except Exception as e:
            state.validation = Validation(valid=False, score=0, warnings=[f"Validation failed: {str(e)}"], suggested_fixes="Rewrite the message from scratch.")
            state.memory["critic_error"] = str(e)

        # --- UPDATED: Refinement Logic ---

        # Case 1: Validation passed
        if state.validation.valid:
            # If human review is enabled, pause here instead of completing
            if settings.ENABLE_HUMAN_REVIEW:
                state.status = Status.AWAITING_HUMAN
                state.next_action = {
                    "type": ActionType.HUMAN_REVIEW,
                    "reason": f"Message approved by critic (score: {state.validation.score}). Awaiting human decision."
                }
            else:
                state.status = Status.COMPLETE
                state.next_action = {"type": ActionType.SAVE_DRAFT, "reason": f"Score: {state.validation.score}"}

            # Record to memory — skipped in debug mode to keep tests deterministic
            rc = get_runtime_config()
            debug_mode = rc.get("DEBUG_MODE", settings.DEBUG_MODE)
            if isinstance(debug_mode, str):
                debug_mode = debug_mode.lower() in ("true", "1", "yes")
            if not debug_mode:
                MemoryService.prospects.record_outreach(
                    name=state.target_prospect,
                    company=state.target_company,
                    channel=state.channel.value,
                    stage=state.stage.value,
                    hook_used=state.strategy.primary_hook if state.strategy else "",
                    angle_used=state.strategy.angle if state.strategy else "",
                    offer_name=state.selected_offer.offer_name if state.selected_offer else "",
                    message_sent=state.draft.body if state.draft else ""
                )

                if settings.ENABLE_LEARNING_LOOP:
                    MemoryService.learning.record_generation(
                        quality_score=state.validation.score,
                        channel=state.channel.value,
                        stage=state.stage.value,
                        template=state.personality.base_template.value
                    )
                    if state.selected_offer:
                        MemoryService.offers.record_usage(
                            offer_name=state.selected_offer.offer_name,
                            channel=state.channel.value,
                            angle=state.strategy.angle if state.strategy else "",
                            prospect_role=state.prospect_role,
                            quality_score=state.validation.score
                        )

        # Case 2: Validation failed, but we have specific fixes to try (and haven't exhausted retries)
        elif state.validation.suggested_fixes and state.iteration_count < state.max_iterations:
            state.status = Status.REVISING  # Tell the orchestrator to go back to the writer
            state.iteration_count += 1
            state.next_action = {
                "type": ActionType.RETRY,
                "reason": f"Validation failed (score: {state.validation.score}). Attempting revision.",
                "feedback": state.validation.suggested_fixes # This is the crucial part
            }
            # We do NOT clear state.draft, the writer needs it to revise

        # Case 3: Validation failed badly, or we're out of retries. Start over from scratch.
        else:
            if state.iteration_count >= state.max_iterations:
                state.status = Status.FAILED
                state.next_action = {"type": ActionType.ABORT, "reason": f"Max iterations hit, final score: {state.validation.score}"}
            else: # Major failure with no suggested fixes
                state.status = Status.PLANNING
                state.iteration_count += 1
                state.draft = None # Clear draft for a full rewrite
                state.strategy = None # Clear strategy, it might have been the problem
                state.next_action = {"type": ActionType.RETRY, "reason": f"Major failure (score {state.validation.score}), planning full retry."}

        return state