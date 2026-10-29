

"""
brain/persona_ranker.py
────────────────────────
Dual-axis persona fit scoring for the Strategic Qualifier pipeline.

Scoring architecture:
  - Fit score (70%):          who they are — role match + seniority
  - Reachability score (20%): how easy to reach — LinkedIn only
    (email/phone are enriched later, after persona selection)
  - Timing score (10%):       when to reach — tenure trigger + public signals

Matching strategy:
  - Titles are first normalised to English via LLM (batch, one call per
    unique title set) so French/multilingual titles match English ICP roles.
  - Role and department matching uses token overlap (not substring) so
    "Sales Operations Director" correctly matches "Sales Director".
  - Signal evaluation anchored to user_offering so the LLM judges buying
    intent relative to what is actually being sold.

Key design decisions:
  - Fit score is never overridden by contact quality signals.
    A hard-to-reach CRO always ranks above an easy-to-reach manager.
  - LinkedIn connection folds into reachability (not fit).
  - months_in_role is derived from employment_history (current role start_date).
  - Signal gate threshold lowered to functional_score >= 1 so any persona
    with a non-zero fit gets their public signals evaluated.
  - All LLM calls decorated with @retry_on_rate_limit.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from groq import Groq
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from brain.config import PersonaWeights
from utils.resilience import retry_on_rate_limit

load_dotenv()
logger = logging.getLogger(__name__)

# Stop words stripped before token matching
# Covers English and the most common French prepositions/articles
_STOP_WORDS = {
    "de", "la", "le", "du", "des", "et", "en", "au", "aux",
    "of", "the", "a", "an", "and", "for", "at", "in", "to",
}

# Cross-language / synonym tokens so ICP "sales" matches French "Commercial"
_ROLE_SYNONYM_GROUPS = [
    {"sales", "commercial", "commerciaux", "vendeur", "seller", "selling"},
    {"business", "development", "bd", "bizdev"},
]

# Filler words often present in ICP role phrases ("sales persons")
_ROLE_FILLER = {"person", "persons", "people", "role", "roles", "staff", "team", "rep", "reps"}

# Neo4j / sourcer sometimes store LLM failure text as persona.intent — treat as empty.
_MEANINGLESS_INTENT_MARKERS = {
    "none",
    "null",
    "n/a",
    "non renseigné",
    "non renseigne",
    "impossible de générer le résumé d'intention.",
    "impossible de generer le resume d'intention.",
    "aucune activité récente pour déduire une intention.",
    "aucune activite recente pour deduire une intention.",
    "activité détectée, mais aucun signal d'affaires clair n'a été extrait.",
    "activite detectee, mais aucun signal d'affaires clair n'a ete extrait.",
}


def _persona_intent_text(persona: Dict[str, Any]) -> str:
    """
    Resolve the persona buying-intent narrative for timing/signal scoring.

    Prefer Neo4j Persona.intent (sourcer field name), then public_signals / bio.
    """
    raw = persona.get("raw") if isinstance(persona.get("raw"), dict) else {}
    for candidate in (
        persona.get("intent"),
        persona.get("persona_intent"),
        raw.get("intent") if isinstance(raw, dict) else None,
        raw.get("persona_intent") if isinstance(raw, dict) else None,
        persona.get("public_signals"),
        persona.get("bio"),
    ):
        if not isinstance(candidate, str):
            continue
        text = candidate.strip()
        if not text:
            continue
        if text.lower() in _MEANINGLESS_INTENT_MARKERS:
            continue
        return text
    return ""


# Module-level Groq client for batch title normalisation
# (uses raw Groq SDK, not LangChain, for the JSON batch call)
_groq_client: Optional[Groq] = None

def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


# ── LLM response schemas ──────────────────────────────────────────────────────

class OutreachSignalAnalysis(BaseModel):
    is_relevant: bool = Field(
        description=(
            "True if the persona's public signals suggest they have a need for, "
            "are evaluating, or are actively interested in the offering described."
        )
    )
    confidence_score: float = Field(
        description="Score from 0 to 100 on how strong the signal relevance is."
    )
    reasoning: str = Field(
        description="One sentence explaining the signal relevance judgment."
    )


# ── Title normalisation ───────────────────────────────────────────────────────

def normalise_titles_to_english(titles: List[str],accumulator=None) -> Dict[str, str]:
    """
    Batch-normalise a list of job titles to standard English equivalents.

    Uses one LLM call for the entire batch — same pattern as map_industries_batch.
    Non-English titles (e.g. "Directrice Commerciale") are translated and
    standardised ("Commercial Director") so downstream token matching works
    correctly regardless of the persona's language.

    Returns a dict mapping each input title to its normalised English form.
    Falls back to the original title on any LLM/parsing failure so the
    scorer never crashes due to normalisation.
    """
    unique_titles = list({t for t in titles if t})
    if not unique_titles:
        return {}

    prompt = f"""
You are a multilingual job title normalizer for a B2B sales platform.

Given a list of job titles (which may be in any language), return each title
normalised to a standard English professional title. Keep the normalised title
concise (2-5 words). Preserve seniority level accurately.

Examples:
  "Directrice Commerciale"      → "Commercial Director"
  "VP des Ventes"               → "VP Sales"
  "Responsable des Opérations"  → "Operations Manager"
  "Chef de Projet Digital"      → "Digital Project Manager"
  "Head of Sales"               → "Head of Sales"   (already English, keep as-is)

Return ONLY a JSON object mapping each input title (exact string) to its
normalised English title. No explanation, no markdown.

TITLES TO NORMALISE:
{json.dumps(unique_titles)}

Return ONLY the JSON object.
"""

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        if accumulator is not None and response.usage:
            try:
                accumulator.record(
                    tokens_in  = response.usage.prompt_tokens,
                    tokens_out = response.usage.completion_tokens,
                    node_name  = "rank_personas",
                )
            except Exception as exc:
                logger.warning("normalise_titles_to_english: failed to record usage — %s", exc)
        mapping = json.loads(response.choices[0].message.content)
        if not isinstance(mapping, dict):
            raise ValueError("LLM did not return a dict")
        # Fallback to original for any title the LLM dropped
        return {t: mapping.get(t, t) for t in unique_titles}
    except Exception as exc:
        logger.warning(
            "normalise_titles_to_english failed: %s — falling back to originals.", exc
        )
        return {t: t for t in unique_titles}


# ── Token-based matching ──────────────────────────────────────────────────────

def _expand_tokens(tokens: set) -> set:
    """Add synonym-group partners for any token present in a synonym group."""
    expanded = set(tokens)
    # Business Development is sales-adjacent (common Apollo title)
    if {"business", "development"}.issubset(expanded) or "bizdev" in expanded:
        expanded |= {"sales", "commercial"}
    for group in _ROLE_SYNONYM_GROUPS:
        if expanded & group:
            expanded |= group
    return expanded


def _token_match(query: str, target: str) -> bool:
    """
    Token overlap match with synonym expansion.

    - "Sales Director" matches "Sales Operations Director"
    - ICP "sales" / "sales persons" matches French title "Commercial"
    - ICP "sales" matches "Business Development Manager"
    - "Sales Director" does not match "Marketing Director"
    """
    query_tokens = set(query.lower().split()) - _STOP_WORDS - _ROLE_FILLER
    target_tokens = set(target.lower().split()) - _STOP_WORDS
    if not query_tokens:
        return False
    target_expanded = _expand_tokens(target_tokens)
    # Every query token must hit the (synonym-expanded) target
    return all(_expand_tokens({tok}) & target_expanded for tok in query_tokens)


def _matches_any(queries: List[str], target_title: str) -> bool:
    """Return True if target_title token-matches any query in the list."""
    return any(_token_match(q, target_title) for q in queries)


# ── Tenure from employment history ────────────────────────────────────────────

def _parse_employment_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """Normalise one employment_history item (dict or JSON string) to a dict."""
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_job_date(raw: Any) -> Optional[date]:
    """Parse employment start/end dates (YYYY-MM-DD or YYYY-MM)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        return None


def _months_between(start: date, end: date) -> int:
    """Whole calendar months between two dates, floored at 0."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def months_in_role_from_employment_history(
    employment_history: Any,
    today: Optional[date] = None,
) -> Optional[int]:
    """
    Derive months in current role from employment_history.

    Prefers the entry with current=true; falls back to the latest start_date.
    DB rows may store each history item as a JSON string.
    """
    if not isinstance(employment_history, list) or not employment_history:
        return None

    entries: List[Dict[str, Any]] = []
    for raw in employment_history:
        parsed = _parse_employment_entry(raw)
        if parsed:
            entries.append(parsed)
    if not entries:
        return None

    current = next((e for e in entries if e.get("current") is True), None)
    if current is None:
        dated = [(e, _parse_job_date(e.get("start_date"))) for e in entries]
        dated = [(e, d) for e, d in dated if d is not None]
        if not dated:
            return None
        current = max(dated, key=lambda item: item[1])[0]

    start = _parse_job_date(current.get("start_date"))
    if start is None:
        return None

    end = today or date.today()
    if current.get("current") is not True:
        end_date = _parse_job_date(current.get("end_date"))
        if end_date is not None:
            end = end_date

    return _months_between(start, end)


def resolve_months_in_role(persona: Dict[str, Any]) -> int:
    """
    Resolve months_in_role from employment_history, then explicit field, else 12.
    """
    history = persona.get("employment_history")
    if history is None and isinstance(persona.get("raw"), dict):
        history = persona["raw"].get("employment_history")

    derived = months_in_role_from_employment_history(history)
    if derived is not None:
        return derived

    raw_months = persona.get("months_in_role")
    try:
        if raw_months is not None:
            return int(raw_months)
    except (TypeError, ValueError):
        pass
    return 12


# ── Signal evaluation ─────────────────────────────────────────────────────────

@retry_on_rate_limit()
def _evaluate_persona_signals(
    persona: Dict[str, Any],
    target_departments: List[str],
    user_offering: str,
    llm: ChatGroq,
    callbacks: Optional[List[Any]] = None,
) -> OutreachSignalAnalysis:
    """
    Evaluate whether a persona's public signals indicate buying intent
    relative to the offering being sold.

    Anchored to user_offering so the LLM judges relevance to what is
    actually being sold — not just whether the persona published content.

    Raises on failure so @retry_on_rate_limit can retry 429 errors.
    Caller must handle the final exception.
    """
    raw_signals = _persona_intent_text(persona)

    if not raw_signals:
        return OutreachSignalAnalysis(
            is_relevant=False,
            confidence_score=0.0,
            reasoning="No public signals available to evaluate.",
        )

    prompt = (
        f"You are evaluating whether a B2B prospect's public signals suggest "
        f"they have a need for the following offering:\n"
        f'OFFERING: "{user_offering}"\n\n'
        f"PROSPECT:\n"
        f"  Name:       {persona.get('name', 'Unknown')}\n"
        f"  Title:      {persona.get('title', 'Unknown')}\n"
        f"  Department: {', '.join(target_departments) if target_departments else 'Unknown'}\n"
        f"  Signals:    {raw_signals}\n\n"
        f"Evaluate whether the signals suggest this person is:\n"
        f"  - Actively evaluating or purchasing tools in this category\n"
        f"  - Experiencing pain points the offering addresses\n"
        f"  - In a role where this offering would directly help them\n\n"
        f"Score 0-100 where 100 = very strong signal they need this offering right now."
    )

    structured_llm = llm.with_structured_output(OutreachSignalAnalysis)
    return structured_llm.invoke(prompt, config={"callbacks": callbacks or []})


# ── Batch entry point ─────────────────────────────────────────────────────────

def normalise_persona_titles(personas: List[Dict[str, Any]], accumulator=None) -> List[Dict[str, Any]]:
    """
    Normalise all persona titles to English in one batch LLM call before scoring.

    Call this once per company batch in rank_personas_node before the scoring
    loop begins. Adds a 'normalised_title' key to each persona dict.

    Returns the same list with normalised_title populated in-place.
    """
    titles  = [str(p.get("title", "")) for p in personas if p.get("title")]
    mapping = normalise_titles_to_english(titles, accumulator=accumulator)

    for p in personas:
        original = str(p.get("title", ""))
        p["normalised_title"] = mapping.get(original, original)

    return personas


# ── Main scoring function ─────────────────────────────────────────────────────

def calculate_persona_fit(
    persona: Dict[str, Any],
    company_domain: Optional[str],
    target_roles: List[str],
    target_departments: List[str],
    user_role_weight: float,
    llm: ChatGroq,
    user_offering: str = "",
    callbacks: Optional[List[Any]] = None,
    persona_weights: Optional[PersonaWeights] = None,
) -> Dict[str, Any]:
    """
    Score a persona using a three-axis model.

    Axes:
      Fit score (fit_weight)          — who they are
        functional_score: role/department match against ICP
        authority_score:  seniority proxy for decision-making power

      Reachability score (reachability_weight) — how easy to contact
        LinkedIn connection only (email/phone enriched after selection)

      Timing score (timing_weight)       — when to reach
        tenure trigger (new in role 1-3 months from employment_history)
        public signal relevance to offering (LLM-evaluated)

    Title matching uses the normalised_title field (English) if present,
    falling back to the raw title. Token overlap matching handles compound
    titles like "Sales Operations Director" matching "Sales Director".

    Args:
        persona:            Persona dict. Should have 'normalised_title' if
                            normalise_persona_titles() was called upstream.
                            Prefer employment_history for tenure timing.
        company_domain:     Reserved (email enrichment happens post-selection).
        target_roles:       ICP target role titles (English).
        target_departments: ICP target departments (English).
        user_role_weight:   Configurable weight — currently reserved for
                            future role vs department balance tuning.
        llm:                Groq LLM instance.
        user_offering:      What is being sold — anchors signal evaluation.
        persona_weights:    Optional PersonaWeights overrides for axis splits.

    Returns:
        Dict with persona_score, outreach_hook_placeholder, and full metrics.
    """
    _ = company_domain  # email/phone reachability deferred until enrichment
    _ = user_role_weight
    pw = persona_weights or PersonaWeights()

    # Use normalised English title for matching if available
    raw_title        = str(persona.get("title",            ""))
    title_for_match  = str(persona.get("normalised_title", raw_title)).lower()
    seniority        = str(persona.get("seniority",        "")).lower()

    logger.debug(
        "persona_match_check name='%s' raw='%s' normalised='%s'",
        persona.get("name"), raw_title, title_for_match,
    )

    # ── AXIS 1: FUNCTIONAL RELEVANCE ─────────────────────────────────────
    is_primary_match    = _matches_any(target_roles,       title_for_match)
    is_department_match = _matches_any(target_departments, title_for_match)

    if is_primary_match:
        functional_score  = 100.0
        functional_reason = "primary_role_match"
    elif is_department_match:
        functional_score  = 75.0
        functional_reason = "department_match"
    elif "ceo" in title_for_match or "chief executive" in title_for_match:
        functional_score  = 60.0
        functional_reason = "ceo_fallback"
    else:
        functional_score  = 0.0
        functional_reason = "no_match"

    # ── AXIS 2: AUTHORITY ────────────────────────────────────────────────
    if seniority in ["c-level", "owner", "founder"]:
        authority_score = 100.0
    elif seniority in ["vp", "vice president"]:
        authority_score = 90.0
    elif seniority in ["director", "head"]:
        authority_score = 80.0
    elif seniority in ["manager"]:
        authority_score = 50.0
    else:
        authority_score = 20.0

    # ── FIT SCORE ────────────────────────────────────────────────────────
    fit_score = (
        (functional_score * pw.functional_weight) +
        (authority_score * pw.authority_weight)
    )

    # ── REACHABILITY (LinkedIn only — email/phone come after enrichment) ─
    is_connected = bool(persona.get("is_linkedin_connected", False))
    reachability_score = 100.0 if is_connected else 0.0

    # ── TIMING ────────────────────────────────────────────────────────────
    months_in_role = resolve_months_in_role(persona)
    has_tenure_trigger = 1 <= months_in_role <= 3

    # Evaluate public signals for any persona with a non-zero functional score.
    # Previously gated at >= 50 which blocked Sales Ops personas with strong
    # intent signals from getting evaluated.
    signal_score     = 0.0
    has_signals      = False
    signal_reasoning = "Signal evaluation skipped — no functional relevance."

    if functional_score > 0:
        raw_signals = _persona_intent_text(persona)

        if raw_signals:
            try:
                signal_analysis  = _evaluate_persona_signals(
                   persona, target_departments, user_offering, llm,
                    callbacks=callbacks,
                )
                signal_score     = signal_analysis.confidence_score
                has_signals      = signal_analysis.is_relevant
                signal_reasoning = signal_analysis.reasoning
            except Exception as exc:
                logger.error(
                    "Persona signal evaluation failed for '%s': %s",
                    persona.get("name"), exc,
                )
                signal_score     = 0.0
                has_signals      = False
                signal_reasoning = "Signal evaluation failed after retries."
        else:
            signal_reasoning = "No public signals available."

    # timing: tenure=40pts, signals=60pts, normalised to 0-100
    timing_score = (
        (40.0 if has_tenure_trigger else 0.0) +
        (min(signal_score, 100.0) * 0.60)
    )

    # ── COMPOSITE SCORE ───────────────────────────────────────────────────
    persona_score = (
        (fit_score          * pw.fit_weight) +
        (reachability_score * pw.reachability_weight) +
        (timing_score       * pw.timing_weight)
    )

    logger.info(
        "persona_scored name='%s' title='%s' normalised='%s' "
        "functional=%.1f authority=%.1f fit=%.1f "
        "reach=%.1f timing=%.1f months_in_role=%d total=%.1f",
        persona.get("name"), raw_title, title_for_match,
        functional_score, authority_score, fit_score,
        reachability_score, timing_score, months_in_role,
        min(persona_score, 100.0),
    )

    return {
        "persona_score":             round(min(persona_score, 100.0), 2),
        "outreach_hook_placeholder": "",
        "months_in_role":            months_in_role,
        "metrics": {
            # Fit axis
            "functional_relevance":  round(functional_score, 2),
            "functional_reason":     functional_reason,
            "authority_score":       round(authority_score, 2),
            "fit_score":             round(fit_score, 2),
            # Reachability axis (LinkedIn only pre-enrichment)
            "linkedin_connected":    is_connected,
            "reachability_score":    round(reachability_score, 2),
            # Timing axis
            "tenure_trigger_active": has_tenure_trigger,
            "months_in_role":        months_in_role,
            "has_public_signals":    has_signals,
            "signal_score":          round(signal_score, 2),
            "signal_reasoning":      signal_reasoning,
            "timing_score":          round(timing_score, 2),
            # Title normalisation audit
            "raw_title":             raw_title,
            "normalised_title":      persona.get("normalised_title", raw_title),
        },
    }