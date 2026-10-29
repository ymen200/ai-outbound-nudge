
"""
brain/config.py
───────────────
Configurable scoring weights and thresholds. Loaded once at module import,
overridable per-run via state['configurable_weights'].
"""

from __future__ import annotations

import json
import logging
import os

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FirmographicWeights(BaseModel):
    """
    All numeric knobs for the firmographic scoring engine, geo filter,
    and intent analysis. Every value here can be overridden at runtime
    by passing a matching key inside state['configurable_weights'] —
    unknown keys are silently ignored by safe_load_firmographic_weights
    so a typo never crashes the pipeline.
    """

    # ── Feature weights (relative importance; normalised internally) ──────
    industry_weight:   float = Field(default=0.40, description="Relative weight for industry match feature.")
    size_weight:       float = Field(default=0.30, description="Relative weight for employee headcount match feature.")
    revenue_weight:    float = Field(default=0.15, description="Relative weight for annual revenue match feature.")
    tech_stack_weight: float = Field(default=0.15, description="Relative weight for tech stack intersection feature.")

    # ── Composite formula split ───────────────────────────────────────────
    firmographic_weight: float = Field(
        default=0.60,
        description="Share of total_score coming from firmographic fit (remainder goes to intent).",
    )
    intent_weight: float = Field(
        default=0.40,
        description="Share of total_score coming from LLM intent score.",
    )

    # ── Qualification thresholds ──────────────────────────────────────────
    passing_threshold: float = Field(
        default=50.0,
        description="Minimum firmographic score to qualify for LLM intent analysis and ranked output.",
    )
    nurture_threshold: float = Field(
        default=25.0,
        description="Minimum firmographic score for the nurture bucket (below this = discard).",
    )

    # ── Proximity scoring ─────────────────────────────────────────────────
    near_miss_penalty: float = Field(
        default=0.20,
        description=(
            "Score penalty applied to companies within ±near_miss_band of a numeric bound "
            "(size, revenue). 0.20 means a near-miss scores 80 instead of 100."
        ),
    )
    near_miss_band: float = Field(
        default=0.10,
        description="Fractional tolerance around size/revenue bounds that defines a near-miss (default ±10%).",
    )

    # ── Industry LLM verification ─────────────────────────────────────────
    min_description_length: int = Field(
        default=50,
        description=(
            "Minimum character count a company description must have before the "
            "LLM industry-verification call is triggered. Shorter descriptions "
            "produce unreliable semantic scores and waste quota."
        ),
    )

    # ── Intent signal recency filters ─────────────────────────────────────
    # Signals older than these thresholds are dropped before the LLM call.
    # Signals with no date are always kept (absence of date ≠ stale).
    intent_job_offer_max_days: int = Field(
        default=90,
        description=(
            "Maximum age in days for a job offer to be included in intent analysis. "
            "Postings older than this are likely filled or cancelled and add noise."
        ),
    )
    intent_news_max_days: int = Field(
        default=180,
        description=(
            "Maximum age in days for a news item to be included in intent analysis. "
            "Older news rarely reflects current buying context."
        ),
    )
    intent_funding_max_days: int = Field(
        default=365,
        description=(
            "Maximum age in days for a funding event to be considered a positive "
            "intent signal. Funding older than this decays in relevance."
        ),
    )

    # ── Intent signal volume caps (tokens / cost control) ─────────────────
    intent_max_job_offers: int = Field(
        default=10,
        description="Maximum number of job offer entries sent to the intent LLM prompt.",
    )
    intent_max_news_items: int = Field(
        default=5,
        description="Maximum number of news items sent to the intent LLM prompt.",
    )
    intent_max_funding_events: int = Field(
        default=5,
        description="Maximum number of funding events sent to the intent LLM prompt.",
    )

    # ── Geo / location-agent settings ────────────────────────────────────
    # Prefer MAX_KM_RADIUS from the orchestrator .env, injected via
    # configurable_weights["max_km_radius"] at campaign start.
    max_km_radius: float = Field(
        default=50.0,
        description=(
            "Preferred-city proximity radius (km). Companies farther than this "
            "are kept but soft-penalized (see geo_radius_mismatch_penalty); "
            "they are not dropped."
        ),
    )
    geo_radius_mismatch_penalty: float = Field(
        default=0.03,
        description=(
            "Fractional firmographic-score penalty for companies outside "
            "max_km_radius of all ICP preferred cities (0.03 = 3%)."
        ),
    )


class PersonaWeights(BaseModel):
    """
    Configuration layer for Persona Selection and Fallback scoring.
    Supports late-injection from the feedback loop engine to dynamically
    adjust outreach target priorities.

    Every value can be overridden at runtime via state['configurable_weights'].
    """
    primary_role_match:     float = Field(default=40.0, description="Base score for direct match with ICP target_roles.")
    startup_fallback_match: float = Field(default=35.0, description="Base score for C-level fallback when headcount is small.")
    partial_title_match:    float = Field(default=20.0, description="Base score for partial/fuzzier title matches.")
    engagement_weight:      float = Field(default=40.0, description="Scale factor for the contact's is_likely_to_engage probability.")
    verified_email_bonus:   float = Field(default=20.0, description="Bonus for verified SMTP status.")
    risky_email_bonus:      float = Field(default=5.0,  description="Bonus for catch-all/risky emails.")

    # Composite axis weights used by brain/persona_ranker.py
    fit_weight:          float = Field(default=0.70, description="Share of persona_score from fit (role + authority).")
    reachability_weight: float = Field(default=0.20, description="Share of persona_score from LinkedIn reachability.")
    timing_weight:       float = Field(default=0.10, description="Share of persona_score from tenure + public signals.")
    functional_weight:   float = Field(default=0.60, description="Share of fit_score from functional/role match.")
    authority_weight:    float = Field(default=0.40, description="Share of fit_score from seniority/authority.")


# ── Global defaults ────────────────────────────────────────────────────────────
DEFAULT_SCORING_WEIGHTS = FirmographicWeights()
DEFAULT_PERSONA_WEIGHTS  = PersonaWeights()


def safe_load_firmographic_weights(weights_dict: dict | None) -> FirmographicWeights:
    """
    Safely instantiate FirmographicWeights from a possibly-partial or
    possibly-malformed dict (e.g. state['configurable_weights']).

    Unknown keys are filtered out so a typo'd key is silently ignored
    rather than raising a Pydantic validation error.
    """
    if not weights_dict:
        return FirmographicWeights()

    valid_fields = set(FirmographicWeights.model_fields.keys())
    filtered = {k: v for k, v in weights_dict.items() if k in valid_fields}

    unknown = set(weights_dict.keys()) - valid_fields
    # Persona weight keys share the same flat dict — ignore without warning noise.
    persona_fields = set(PersonaWeights.model_fields.keys()) | {"target_role_match"}
    unknown -= persona_fields
    if unknown:
        logger.warning(
            "safe_load_firmographic_weights: ignoring unknown keys %s", sorted(unknown)
        )

    return FirmographicWeights(**filtered)


def safe_load_persona_weights(weights_dict: dict | None) -> PersonaWeights:
    """
    Safely instantiate PersonaWeights from state['configurable_weights'].
    Unknown keys are filtered out (firmographic keys are expected and ignored).
    """
    if not weights_dict:
        return PersonaWeights()

    valid_fields = set(PersonaWeights.model_fields.keys())
    filtered = {k: v for k, v in weights_dict.items() if k in valid_fields}
    return PersonaWeights(**filtered)


def load_testing_weights(config_path: str = "brain/config.json") -> dict:
    """Loads custom runtime configurations from a local config.json file."""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                raw_json = json.load(f)

            firmographic_data = raw_json.get("firmographic_weights", {})
            persona_data      = raw_json.get("persona_weights", {})

            logger.info("Config system: loaded operational weights from %s", config_path)
            return {
                "firmographic_weights": FirmographicWeights(**firmographic_data).model_dump(),
                "persona_weights":      PersonaWeights(**persona_data).model_dump(),
            }
        except Exception as exc:
            logger.warning(
                "Config system: failed to parse %s (%s) — reverting to defaults.",
                config_path, exc,
            )

    return {
        "firmographic_weights": DEFAULT_SCORING_WEIGHTS.model_dump(),
        "persona_weights":      DEFAULT_PERSONA_WEIGHTS.model_dump(),
    }