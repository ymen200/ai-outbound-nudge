


"""
brain/scoring.py
────────────────
Firmographic scoring engine and LLM intent analysis for the Strategic Qualifier pipeline.

Key design decisions:
  - Industry scoring: exact taxonomy label match = 100 (no LLM call).
    Only falls back to LLM semantic check when label did not match AND
    description is long enough to produce a reliable result.
  - Size / revenue scoring: three-tier system (exact / near-miss / miss).
    Near-miss band and penalty are configurable via FirmographicWeights.
  - Tech stack scoring: uses min(icp_tech, co_tech) as denominator so a
    broad ICP does not systematically under-score companies.
  - match_quality emitted per feature so the frontend can distinguish
    "perfect match" from "similar to your ICP".
  - Intent analysis anchored to user_offering so the LLM judges signals
    relative to what is actually being sold, not generically.
  - rank_companies uses calculate_funding_intent_score (funding_events +
    latest_funding_stage) as a deterministic intent proxy before sourcer intent.
  - rescore_intent uses evaluate_company_intent (LLM) once sourcer signals arrive.
  - Intent LLM requires commercial signals (job offers, news, summary; funding
    optional when include_funding_as_signal=True). Description / keywords / tech
    are supporting context only and never invent intent alone.
  - Intent signals (job offers, news, funding) filtered by recency before
    reaching the LLM.
  - LLM calls decorated with @retry_on_rate_limit; callers catch the
    final exception and apply a conservative fallback (score = 0).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from brain.config import FirmographicWeights
from utils.resilience import retry_on_rate_limit

logger = logging.getLogger(__name__)

# Feature-key aliases: FirmographicWeights uses *_weight; scoring features use *_match.
_FEATURE_WEIGHT_KEYS = {
    "industry_match":   "industry_weight",
    "size_match":       "size_weight",
    "revenue_match":    "revenue_weight",
    "tech_stack_match": "tech_stack_weight",
}


# ── Pydantic response schemas for structured LLM output ──────────────────────

class IndustryVerification(BaseModel):
    relevance_score: float = Field(
        ..., description="Decimal between 0.0 and 1.0. 1.0 = perfect match with target industries."
    )
    reasoning: str = Field(..., description="One-sentence explanation.")


class IntentAnalysis(BaseModel):
    hiring_relevance: float = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "How directly hiring signals indicate need for the offering (0-100). "
            "Use precise values; avoid defaulting to round anchors like 50 or 80."
        ),
    )
    growth_timing: float = Field(
        ...,
        ge=0,
        le=100,
        description="Strength of growth/expansion timing signals (0-100).",
    )
    offering_fit: float = Field(
        ...,
        ge=0,
        le=100,
        description="Overall fit between company context and what is being sold (0-100).",
    )
    reasoning: str = Field(..., description="Key signal explanation referencing specific evidence.")

    @property
    def intent_score(self) -> float:
        return round(
            self.hiring_relevance * 0.45
            + self.growth_timing * 0.30
            + self.offering_fit * 0.25,
            1,
        )


def intent_breakdown_from_analysis(results: IntentAnalysis) -> Dict[str, float]:
    return {
        "hiring_relevance": results.hiring_relevance,
        "growth_timing": results.growth_timing,
        "offering_fit": results.offering_fit,
    }


# ── Funding-based intent proxy (rank_companies) ─────────────────────────────

_FUNDING_STAGE_SCORES: Dict[str, float] = {
    "pre-seed": 25.0,
    "seed": 35.0,
    "angel": 32.0,
    "series a": 55.0,
    "series b": 68.0,
    "series c": 78.0,
    "series d": 82.0,
    "series e": 84.0,
    "series f": 85.0,
    "series g": 86.0,
    "debt financing": 52.0,
    "private equity": 72.0,
    "venture": 50.0,
    "growth": 62.0,
    "ipo": 88.0,
    "publicly traded": 88.0,
    "post-ipo": 80.0,
    "acquired": 38.0,
    "merger / acquisition": 38.0,
    "other": 30.0,
    "bootstrapped": 18.0,
    "nonprofit / donations": 12.0,
}


def _normalize_funding_stage(stage: Any) -> str:
    return re.sub(r"\s+", " ", str(stage or "").strip().lower())


def _score_funding_stage(stage: Any) -> float:
    """Map a funding round label to a 0-100 maturity / growth signal."""
    normalized = _normalize_funding_stage(stage)
    if not normalized:
        return 0.0

    if normalized in _FUNDING_STAGE_SCORES:
        return _FUNDING_STAGE_SCORES[normalized]

    for key, score in _FUNDING_STAGE_SCORES.items():
        if key in normalized or normalized in key:
            return score

    return 25.0


def _funding_stages_match(target: Any, actual: Any) -> bool:
    target_norm = _normalize_funding_stage(target)
    actual_norm = _normalize_funding_stage(actual)
    if not target_norm or not actual_norm:
        return False
    return (
        target_norm == actual_norm
        or target_norm in actual_norm
        or actual_norm in target_norm
    )


def _funding_recency_multiplier(raw_date: Any, max_days: int) -> float:
    """
    Linear decay from 1.0 (today) to 0.35 at max_days; 0 beyond max_days.
  Signals with no date are kept at 0.75 (unknown recency).
    """
    if not raw_date:
        return 0.75

    try:
        parsed = datetime.fromisoformat(str(raw_date))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.75

    age_days = (datetime.now(timezone.utc) - parsed).days
    if age_days < 0:
        return 1.0
    if age_days >= max_days:
        return 0.0

    return round(1.0 - (0.65 * age_days / max_days), 3)


def _sort_funding_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _event_sort_key(event: Dict[str, Any]) -> datetime:
        raw_date = event.get("date")
        if not raw_date:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(raw_date))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    return sorted(events, key=_event_sort_key, reverse=True)


def calculate_funding_intent_score(
    company: Dict[str, Any],
    icp: Any = None,
    firm_weights: Optional[FirmographicWeights] = None,
) -> Dict[str, Any]:
    """
    Deterministic intent proxy for rank_companies based on Apollo funding data.

    Uses latest_funding_stage and recent funding_events (recency-filtered).
    Replaced later by evaluate_company_intent during rescore_with_intent.
    """
    if firm_weights is None:
        firm_weights = FirmographicWeights()

    latest_stage = (
        company.get("latest_funding_stage")
        or company.get("funding_stage")
    )
    stage_score = _score_funding_stage(latest_stage)

    recent_events = _filter_recent_signals(
        company.get("funding_events") or [],
        date_key="date",
        max_days=firm_weights.intent_funding_max_days,
    )[: firm_weights.intent_max_funding_events]
    recent_events = _sort_funding_events(recent_events)

    event_score = 0.0
    best_event_type = None
    best_event_date = None
    for event in recent_events:
        type_score = _score_funding_stage(event.get("type"))
        recency = _funding_recency_multiplier(
            event.get("date"),
            firm_weights.intent_funding_max_days,
        )
        weighted = type_score * recency
        if weighted > event_score:
            event_score = weighted
            best_event_type = event.get("type")
            best_event_date = event.get("date")

    if recent_events:
        base_score = max(stage_score * 0.55, event_score)
    elif stage_score > 0:
        base_score = stage_score * 0.45
    else:
        base_score = 0.0

    icp_stage = None
    if icp is not None:
        nice = getattr(icp, "nice_to_have", None)
        icp_stage = getattr(nice, "funding_stage", None) if nice else None

    icp_bonus = 0.0
    if icp_stage and latest_stage and _funding_stages_match(icp_stage, latest_stage):
        icp_bonus = 12.0

    intent_score = min(100.0, round(base_score + icp_bonus, 1))

    if intent_score <= 0:
        reasoning = "No funding stage or recent funding events found."
    elif recent_events:
        reasoning = (
            f"Funding-based intent: stage={latest_stage or 'unknown'} "
            f"(score={stage_score:.0f}); "
            f"recent event={best_event_type or 'unknown'} "
            f"(weighted={event_score:.1f})."
        )
        if icp_bonus:
            reasoning += f" ICP funding-stage match bonus (+{icp_bonus:.0f})."
    else:
        reasoning = (
            f"Funding-based intent from stage={latest_stage} "
            f"(score={stage_score:.0f}); no recent funding events within "
            f"{firm_weights.intent_funding_max_days} days."
        )
        if icp_bonus:
            reasoning += f" ICP funding-stage match bonus (+{icp_bonus:.0f})."

    return {
        "intent_score": intent_score,
        "intent_reasoning": reasoning,
        "intent_breakdown": {
            "funding_stage_score": round(stage_score, 1),
            "recent_event_score": round(event_score, 1),
            "icp_stage_bonus": icp_bonus,
            "latest_funding_stage": latest_stage,
            "recent_event_type": best_event_type,
            "recent_event_date": best_event_date,
            "recent_events_count": len(recent_events),
        },
    }


# ── Weight helpers ────────────────────────────────────────────────────────────

def _calculate_dynamic_weights(
    state_weights: Dict[str, float] | None,
    active_keys: List[str],
    firm_weights: Optional[FirmographicWeights] = None,
) -> Dict[str, float]:
    """
    Blend user-defined weights with FirmographicWeights defaults, keep only
    active keys, and normalise so they sum to 1.0.

    Accepts both feature keys (industry_match) and config keys (industry_weight).
    """
    fw = firm_weights or FirmographicWeights()
    provided = state_weights or {}
    combined: Dict[str, float] = {}

    for feature_key, weight_attr in _FEATURE_WEIGHT_KEYS.items():
        default_val = float(getattr(fw, weight_attr))
        # Prefer explicit feature key, then FirmographicWeights-style key, then default.
        if feature_key in provided:
            combined[feature_key] = float(provided[feature_key])
        elif weight_attr in provided:
            combined[feature_key] = float(provided[weight_attr])
        else:
            combined[feature_key] = default_val

    active_sum = sum(combined.get(k, 0.0) for k in active_keys)

    if active_sum <= 0:
        logger.warning(
            "_calculate_dynamic_weights: active weight sum is zero — falling back to uniform."
        )
        return {k: 1.0 / len(active_keys) for k in active_keys}

    return {k: combined[k] / active_sum for k in active_keys}


# ── Recency filter ────────────────────────────────────────────────────────────

def _filter_recent_signals(
    signals: List[Dict[str, Any]],
    date_key: str,
    max_days: int,
) -> List[Dict[str, Any]]:
    """
    Keep only signals posted/published within max_days of today.

    Signals with a missing or unparseable date are always kept —
    absence of a date field is not treated as stale.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    recent: List[Dict[str, Any]] = []

    for signal in signals:
        raw_date = signal.get(date_key)
        if not raw_date:
            # No date available — keep it, do not penalise
            recent.append(signal)
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_date))
            # Make timezone-aware if naive
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed >= cutoff:
                recent.append(signal)
            else:
                logger.debug(
                    "intent_signal_filtered_stale date=%s max_days=%d", raw_date, max_days
                )
        except (ValueError, TypeError):
            # Unparseable date — keep the signal, do not penalise
            recent.append(signal)

    return recent


# ── LLM calls ─────────────────────────────────────────────────────────────────

@retry_on_rate_limit()
def _llm_verify_industry(
    description: str,
    target_industries: List[str],
    llm: ChatGroq,
    callbacks: Optional[List[Any]] = None,

) -> float:
    """
    Semantic industry verification via structured LLM output.

    Only called when the taxonomy label did not match — never on exact hits.
    Raises on failure so @retry_on_rate_limit can retry 429 errors.
    The caller must catch the final exception.
    """
    prompt = (
        f'Analyze the following company description:\n"{description}"\n\n'
        f"Target ICP Industries: {', '.join(target_industries)}\n\n"
        "Determine if this company falls into or services one of the Target ICP "
        "Industries. Look past generic labels like 'Services' and evaluate the "
        "core operational business activities."
    )
    structured_llm = llm.with_structured_output(IndustryVerification)
    result = structured_llm.invoke(prompt, config={"callbacks": callbacks or []})
    return max(0.0, min(1.0, result.relevance_score))


def _get_company_intent_summary(company: Dict[str, Any]) -> str:
    """Return synthesized company intent summary when present on company or intent_signals."""
    intent_signals = company.get("intent_signals") or {}
    for candidate in (
        company.get("company_intent_summary"),
        intent_signals.get("company_intent_summary"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


@retry_on_rate_limit()
def evaluate_company_intent(
    company: Dict[str, Any],
    icp: Any,
    llm: ChatGroq,
    user_offering: str,
    firm_weights: Optional[FirmographicWeights] = None,
    callbacks: Optional[List[Any]] = None,
    include_funding_as_signal: bool = False,
) -> IntentAnalysis:
    """
    Evaluate buying-intent signals for a company relative to what is being sold.

    Used during rescore_with_intent after the sourcer delivers commercial signals.

    Commercial intent signals (required for a non-zero score):
      - Company intent summary: synthesized narrative from sourcer/Neo4j
      - Job offers:     what roles they are actively hiring for
      - News:           recent strategic announcements or press
      - Funding events: only when include_funding_as_signal=True (rescore fallback)

    Funding events on the Apollo company record are supporting context during
    LLM evaluation once sourcer signals are present. They must not invent a
    non-zero intent_score during rank_companies — use calculate_funding_intent_score.

    Description / keywords / tech stack are supporting context only — they must
    not invent intent when no commercial signals were delivered by the sourcer.

    All signals are filtered by recency before reaching the LLM.

    Raises on LLM failure so @retry_on_rate_limit can retry 429 errors.
    The caller must catch the final exception and apply intent_score = 0 as a
    conservative fallback.
    """
    if firm_weights is None:
        firm_weights = FirmographicWeights()

    # ── Pull and filter intent signals by recency ──────────────────────────
    intent_signals = company.get("intent_signals") or {}
    company_intent_summary = _get_company_intent_summary(company)

    raw_job_offers = intent_signals.get("job_offers", [])
    raw_news       = intent_signals.get("news", [])
    # Funding on the Apollo company record is firmographic enrichment, not a
    # sourcer-delivered intent signal. Only use it as supporting context when
    # the sourcer already provided jobs/news/summary (rescore_with_intent path).
    # Using it during the empty-intent firmographic pass incorrectly gives a
    # non-zero intent_score to companies with historical funding rounds.

    job_offers = _filter_recent_signals(
        raw_job_offers,
        date_key="posted_date",
        max_days=firm_weights.intent_job_offer_max_days,
    )[: firm_weights.intent_max_job_offers]

    news = _filter_recent_signals(
        raw_news,
        date_key="published_date",
        max_days=firm_weights.intent_news_max_days,
    )[: firm_weights.intent_max_news_items]

    funding = _filter_recent_signals(
        company.get("funding_events") or [],
        date_key="date",
        max_days=firm_weights.intent_funding_max_days,
    )[: firm_weights.intent_max_funding_events]

    has_sourcer_signals = bool(job_offers or news or company_intent_summary)
    has_funding_signal = include_funding_as_signal and bool(funding)

    # No commercial signals from sourcer (and no funding when allowed) → intent is 0.
    if not has_sourcer_signals and not has_funding_signal:
        logger.info(
            "evaluate_company_intent company=%s — no commercial signals; intent_score=0",
            company.get("name"),
        )
        return IntentAnalysis(
            hiring_relevance=0.0,
            growth_timing=0.0,
            offering_fit=0.0,
            reasoning="No commercial intent signals found (no recent job offers, news, or company intent summary).",
        )

    # ── Static company signals (supporting context only) ───────────────────
    desc     = (company.get("full_description") or "")[:1200]
    keywords = company.get("keywords", [])
    tech     = company.get("tech_stack", [])[:20]

    # ── Build prompt sections only for signals that are present ───────────
    sections: List[str] = []

    if company_intent_summary:
        sections.append(
            "Synthesized company intent summary "
            "(aggregates recent hiring, news, and growth signals):\n"
            f"{company_intent_summary[:2000]}"
        )

    if job_offers:
        sections.append(
            f"Active job offers (roles they are hiring for right now):\n"
            f"{json.dumps(job_offers, default=str)}"
        )

    if news:
        sections.append(
            f"Recent news and announcements:\n"
            f"{json.dumps(news, default=str)}"
        )

    if funding:
        sections.append(
            f"Recent funding events (budget and growth signals):\n"
            f"{json.dumps(funding, default=str)}"
        )

    if keywords:
        sections.append(f"Topic keywords from vendor data: {keywords}")

    if desc:
        sections.append(f"Company description: {desc}")

    if tech:
        sections.append(f"Tech stack: {tech}")

    signal_block = "\n\n".join(sections)

    logger.info(
        "evaluate_company_intent company=%s signals=jobs:%d news:%d funding:%d summary=%s",
        company.get("name"),
        len(job_offers),
        len(news),
        len(funding),
        bool(company_intent_summary),
    )

    # ── Build the final prompt ─────────────────────────────────────────────
    prompt = (
        f"You are evaluating whether a company is likely to need and buy "
        f"the following offering:\n"
        f'OFFERING: "{user_offering}"\n\n'
        f'COMPANY: "{company.get("name")}"\n'
        f"Target sector context: {icp.must_have.industry if icp else 'B2B'}\n\n"
        f"AVAILABLE SIGNALS:\n"
        f"{signal_block}\n\n"
        f"Using ONLY the signals provided above, score three independent dimensions "
        f"(0-100 each, decimals allowed). Use the FULL range — do not cluster on "
        f"round anchors like 50 or 80 unless the evidence truly matches that level.\n\n"
        f"1. hiring_relevance — Do hiring patterns indicate they need this offering? "
        f"(e.g. sales, GTM, outbound, revenue ops roles = high for sales automation)\n"
        f"2. growth_timing — Are growth/expansion signals strong and current? "
        f"(hiring sprees, expansion news, funding)\n"
        f"3. offering_fit — How well does the company context match what is being sold?\n\n"
        f"Scoring bands (apply to EACH dimension):\n"
        f"  85-100 = strong, direct, current evidence\n"
        f"  65-84  = good evidence with minor gaps\n"
        f"  45-64  = partial or indirect evidence\n"
        f"  25-44  = weak or generic signals only\n"
        f"  0-24   = no meaningful evidence\n\n"
        f"Important rules:\n"
        f"- When a synthesized company intent summary is provided, treat it as the "
        f"primary narrative and corroborate with jobs/news/funding.\n"
        f"- Description / keywords / tech are supporting context only.\n"
        f"- Differentiate companies: stronger, more direct evidence MUST score higher "
        f"than weaker evidence on each dimension.\n"
        f"- A company hiring many sales/GTM roles for a sales-automation offering "
        f"should outscore one hiring only generic engineering roles."
    )

    structured_llm = llm.with_structured_output(IntentAnalysis)
    return structured_llm.invoke(prompt, config={"callbacks": callbacks or []})


# ── Proximity scoring helper ──────────────────────────────────────────────────

def _score_numeric_range(
    value: float,
    min_bound: float,
    max_bound: float,
    near_miss_band: float,
    near_miss_penalty: float,
) -> Tuple[float, str]:
    """
    Score a numeric value against a [min_bound, max_bound] range.

    Returns (score, match_quality):
      'exact'     — within the target range              → 100.0
      'near_miss' — within ±near_miss_band of any edge   → 100 * (1 - penalty)
      'miss'      — outside the proximity band            → 0.0
    """
    if min_bound <= value <= max_bound:
        return 100.0, "exact"

    lower_band = min_bound * (1.0 - near_miss_band)
    upper_band = (
        max_bound * (1.0 + near_miss_band)
        if max_bound != float("inf")
        else float("inf")
    )

    if lower_band <= value <= upper_band:
        return round(100.0 * (1.0 - near_miss_penalty), 2), "near_miss"

    return 0.0, "miss"


# ── Tech stack fuzzy matching ─────────────────────────────────────────────────

def _tech_fuzzy_match(icp_terms: List[str], co_terms: List[str]) -> int:
    """
    Count how many ICP tech terms fuzzy-match at least one company tech string.

    Checks both directions so vendor aliases and full product names both match:
      "salesforce" in "salesforce crm analytics"  ✓  (ICP term in vendor string)
      "ms teams"   in "microsoft teams"           ✗  (misses — use direction B)
      "microsoft teams" in "ms teams"             ✗  (misses too — token match
                                                       handles this better but
                                                       bidirectional catches most)
      "powerbi" in "power bi documenter"          ✗  (space difference — known
                                                       limitation, acceptable)

    Each ICP term counts at most once even if it matches multiple vendor strings.
    """
    matched = 0
    for icp_term in icp_terms:
        hit = any(
            icp_term in co_term or co_term in icp_term
            for co_term in co_terms
        )
        if hit:
            matched += 1
    return matched


# ── Main scoring function ─────────────────────────────────────────────────────

def calculate_company_score(
    company: Dict[str, Any],
    icp: Any,
    state_weights: Dict[str, float] | None,
    llm: ChatGroq,
    firm_weights: Optional[FirmographicWeights] = None,
    callbacks: Optional[List[Any]] = None,

) -> Dict[str, Any]:
    """
    Core firmographic scoring engine.

    Args:
        company:       Normalised company dict from normalize_company_data_node.
        icp:           Structured ICPAttributes from extract_icp_node.
        state_weights: Raw weight dict from state['configurable_weights'].
        llm:           Groq LLM instance (used only for semantic industry fallback).
        firm_weights:  Pre-loaded FirmographicWeights; defaults to FirmographicWeights()
                       if not supplied so the function is safe to call in isolation.

    Returns:
        {
          "firmographic_score": float,
          "breakdown": {
              feature: {"score": float, "match_quality": str}
          },
          "normalized_weights": {feature: float},
        }
    """
    if firm_weights is None:
        firm_weights = FirmographicWeights()

    near_miss_band    = firm_weights.near_miss_band
    near_miss_penalty = firm_weights.near_miss_penalty
    min_desc_length   = firm_weights.min_description_length

    feature_scores:  Dict[str, float] = {}
    match_qualities: Dict[str, str]   = {}
    active_features: List[str]        = []

    # ── 1. INDUSTRY FIT ───────────────────────────────────────────────────
    target_industries = [i.lower() for i in (icp.must_have.industry or [])]
    mapped_ind  = str(company.get("mapped_industry") or "").lower()
    raw_ind     = str(company.get("industry_raw") or "").lower()
    global_ind  = str(company.get("global_industry") or "").lower()
    description = company.get("full_description") or company.get("short_description") or ""

    if target_industries:
        active_features.append("industry_match")

        # Exact label match — no LLM call needed.
        # Include global_industry (Apollo canonical) so companies whose raw
        # vendor label diverges still score as exact when the ICP matches.
        label_hit = any(
            ind == mapped_ind or ind == raw_ind or ind == global_ind
            or ind in mapped_ind or ind in global_ind
            for ind in target_industries
        )

        if label_hit:
            feature_scores["industry_match"]  = 100.0
            match_qualities["industry_match"] = "exact"
        else:
            # Semantic fallback — only when description is substantive
            if description and len(description) >= min_desc_length:
                try:
                    semantic_score = _llm_verify_industry(
                        description, target_industries, llm,
                        callbacks=callbacks,
                    )
                    logger.info(
                        "industry_semantic_fallback company=%s score=%.2f",
                        company.get("name"), semantic_score,
                    )
                except Exception as exc:
                    logger.error(
                        "Industry LLM verification failed (after retries) "
                        "company=%s error=%s",
                        company.get("name"), exc,
                    )
                    semantic_score = 0.0
            else:
                logger.info(
                    "industry_semantic_skipped company=%s "
                    "reason='description too short or missing'",
                    company.get("name"),
                )
                semantic_score = 0.0

            feature_scores["industry_match"]  = round(semantic_score * 100.0, 2)
            match_qualities["industry_match"] = (
                "semantic" if semantic_score > 0 else "miss"
            )

    # ── 2. COMPANY SIZE FIT ───────────────────────────────────────────────
    # Only score when the ICP actually set min and/or max. An empty Range()
    # object is truthy in Python, so checking `if icp_size` alone would treat
    # "no size preference" as 0–∞ and give every company an exact 100.
    co_size  = company.get("estimated_num_employees")
    icp_size = getattr(icp.must_have, "company_size", None)
    size_bounds_set = bool(
        icp_size and (icp_size.min is not None or icp_size.max is not None)
    )

    if co_size is not None and size_bounds_set:
        active_features.append("size_match")
        min_s = float(icp_size.min) if icp_size.min is not None else 0.0
        max_s = float(icp_size.max) if icp_size.max is not None else float("inf")

        size_score, size_quality = _score_numeric_range(
            value=float(co_size),
            min_bound=min_s,
            max_bound=max_s,
            near_miss_band=near_miss_band,
            near_miss_penalty=near_miss_penalty,
        )
        feature_scores["size_match"]  = size_score
        match_qualities["size_match"] = size_quality

    # ── 3. REVENUE FIT ────────────────────────────────────────────────────
    # Same guard as size: extractor always emits revenue_range={min:null,max:null}
    # when the user never mentioned revenue. That empty Range must NOT activate
    # revenue_match (otherwise every company with any revenue scores exact 100).
    co_rev  = company.get("annual_revenue")
    icp_rev = getattr(icp.nice_to_have, "revenue_range", None)
    rev_bounds_set = bool(
        icp_rev and (icp_rev.min is not None or icp_rev.max is not None)
    )

    if co_rev is not None and rev_bounds_set:
        active_features.append("revenue_match")
        min_r = float(icp_rev.min) if icp_rev.min is not None else 0.0
        max_r = float(icp_rev.max) if icp_rev.max is not None else float("inf")

        rev_score, rev_quality = _score_numeric_range(
            value=float(co_rev),
            min_bound=min_r,
            max_bound=max_r,
            near_miss_band=near_miss_band,
            near_miss_penalty=near_miss_penalty,
        )
        feature_scores["revenue_match"]  = rev_score
        match_qualities["revenue_match"] = rev_quality

    # ── 4. TECH STACK FIT ─────────────────────────────────────────────────
    # Strip "required:" prefixes that can appear in ICP tech entries.
    icp_tech = [
        re.sub(r"^required\s*:\s*", "", t, flags=re.IGNORECASE).lower()
        for t in (icp.nice_to_have.tech_stack or [])
        if t
    ]

    if icp_tech:
        active_features.append("tech_stack_match")
        co_tech = [str(t).lower() for t in company.get("tech_stack", [])]
        matched = _tech_fuzzy_match(icp_tech, co_tech)

        # Use min(icp_tech, co_tech) as denominator so a broad ICP does not
        # systematically under-score companies relative to a narrow ICP.
        denominator = min(len(icp_tech), len(co_tech)) if co_tech else len(icp_tech)
        tech_score  = (matched / denominator) * 100.0 if denominator else 0.0

        if matched == 0:
            tech_quality = "miss"
        elif matched == denominator:
            tech_quality = "exact"
        else:
            tech_quality = "near_miss"

        feature_scores["tech_stack_match"]  = round(tech_score, 2)
        match_qualities["tech_stack_match"] = tech_quality

    # ── Early exit: no scoreable features ────────────────────────────────
    if not active_features:
        return {
            "firmographic_score": 0.0,
            "breakdown": {},
            "normalized_weights": {},
        }

    # ── 5. WEIGHT RECONCILIATION & FINAL SCORE ────────────────────────────
    normalized_weights = _calculate_dynamic_weights(
        state_weights, active_features, firm_weights=firm_weights
    )
    final_score = sum(
        feature_scores.get(f, 0.0) * normalized_weights.get(f, 0.0)
        for f in active_features
    )

    breakdown = {
        f: {
            "score":         round(feature_scores.get(f, 0.0), 2),
            "match_quality": match_qualities.get(f, "unknown"),
        }
        for f in active_features
    }

    return {
        "firmographic_score": round(final_score, 2),
        "breakdown":          breakdown,
        "normalized_weights": {
            f: round(normalized_weights.get(f, 0.0), 3) for f in active_features
        },
    }


def calculate_overall_match_quality(breakdown: Dict[str, Dict[str, Any]]) -> str:
    """
    Calculate overall match quality label from per-feature breakdown.
    
    Returns one of:
    - "perfect_match" - All features are exact matches
    - "similar_to_icp" - Most features are exact or near_miss
    - "partial_match" - Mixed exact/near_miss/miss
    - "poor_match" - Most features are misses
    
    Args:
        breakdown: Dict from calculate_company_score with per-feature match_quality
        
    Returns:
        Overall match quality label for UI display
    """
    if not breakdown:
        return "unknown"
    
    qualities = [item.get("match_quality", "unknown") for item in breakdown.values()]
    
    # Count quality types
    exact_count = qualities.count("exact")
    near_miss_count = qualities.count("near_miss")
    miss_count = qualities.count("miss")
    total = len(qualities)
    
    # Determine overall label
    if total == 0:
        return "unknown"
    
    if exact_count == total:
        return "perfect_match"
    elif (exact_count + near_miss_count) >= total * 0.75:
        return "similar_to_icp"
    elif miss_count >= total * 0.5:
        return "poor_match"
    else:
        return "partial_match"