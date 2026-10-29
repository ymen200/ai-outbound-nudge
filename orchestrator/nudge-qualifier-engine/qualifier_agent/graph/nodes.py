"""
graph/nodes.py
──────────────
All LangGraph nodes for the Strategic Qualifier pipeline.

Node execution order (defined in workflow.py):
  1. extract_icp_node            — parse raw ICP text → ICPAttributes
  2. normalize_company_data_node — clean/normalize raw vendor company dicts
  3. filter_and_gate_node        — hard gates + firmographic scoring + bucket assignment
  4. score_and_rank_node         — funding-based intent + tier assignment
  5. rank_personas_node          — persona guard + scoring (calls persona/ranker.py)

Private helpers are prefixed with _ and are not imported by other modules.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langgraph.types import interrupt

from geo.location_agent import LocationAgent
from geo.continents import continent_for_country
from utils.usage_tracker import get_campaign_accumulator, make_callback

from brain.extractor import ICPExtractor
from brain.schemas import ICPAttributes
from brain.scoring import (
    calculate_company_score,
    calculate_funding_intent_score,
    calculate_overall_match_quality,
)
from brain.persona_ranker import calculate_persona_fit, normalise_persona_titles
from brain.config import safe_load_firmographic_weights, safe_load_persona_weights
from graph.state import CampaignState, DisqualificationLog, DisqualificationRecord
from llm.taxonomy_mapper import map_industries_batch
from datetime import datetime, timezone

load_dotenv()
logger = logging.getLogger(__name__)


def _coerce_icp(raw: Any) -> Optional[ICPAttributes]:
    """
    Rehydrate ICPAttributes after Postgres checkpoint round-trips.

    LangGraph may restore nested models as plain dicts; downstream code
    expects attribute access (icp.must_have.industry, icp.target_cities, …).
    """
    if raw is None:
        return None
    if isinstance(raw, ICPAttributes):
        return raw
    if isinstance(raw, dict):
        try:
            return ICPAttributes.model_validate(raw)
        except Exception as exc:
            logger.error("coerce_icp_failed error=%s", exc, exc_info=True)
            return None
    return None


def _company_matches_blacklist(co_name: str, patterns: List[str]) -> bool:
    """
    True if company name matches any blacklist entry as a case-insensitive regex.

    Plain names (e.g. "Microsoft") match variants like "Microsoft Corporation".
    Invalid regex entries fall back to a literal escaped search.
    """
    if not co_name or not patterns:
        return False
    for raw in patterns:
        pattern = (raw or "").strip()
        if not pattern:
            continue
        try:
            if re.search(pattern, co_name, flags=re.IGNORECASE):
                return True
        except re.error:
            if re.search(re.escape(pattern), co_name, flags=re.IGNORECASE):
                return True
    return False


def _normalize_linkedin_url(url: str) -> str:
    """Canonical form for LinkedIn URL blacklist comparison."""
    u = (url or "").strip().lower()
    if not u:
        return ""
    u = u.split("?")[0].split("#")[0].rstrip("/")
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    if u.startswith("www."):
        u = u[4:]
    return u


def _persona_matches_blacklist(persona: Dict[str, Any], linkedin_urls: List[str]) -> bool:
    """True if persona linkedin_url matches any blacklisted LinkedIn URL."""
    persona_url = _normalize_linkedin_url(str(persona.get("linkedin_url") or ""))
    if not persona_url or not linkedin_urls:
        return False
    blocked = {_normalize_linkedin_url(u) for u in linkedin_urls if u}
    return persona_url in blocked


# ── Module-level singletons (initialized once for performance) ────────────────

_extractor = ICPExtractor()
_location_agent = LocationAgent()
_groq_llm = None

def _get_groq_llm() -> ChatGroq:
    global _groq_llm
    if _groq_llm is None:
        _groq_llm = ChatGroq(
            model_name="llama-3.3-70b-versatile",
            temperature=0.0,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
    return _groq_llm


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

NULL_PLACEHOLDERS = {
    "non renseigné", "non renseigne", "n/a",
    "none", "null", "unknown", "",
}

# ormsgpack (LangGraph Postgres checkpointer) only accepts ints in this range.
# Apollo occasionally emits oversized numeric IDs (e.g. suborganizations[].id)
# that blow up checkpoint writes with: "Integer exceeds 64-bit range".
_MSGPACK_INT_MIN = -(2**63 - 1)
_MSGPACK_INT_MAX = 2**64 - 1


def _is_null_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in NULL_PLACEHOLDERS:
        return True
    return False


def _clean_value(value: Any) -> Any:
    return None if _is_null_placeholder(value) else value


def _fits_msgpack_int(value: int) -> bool:
    return _MSGPACK_INT_MIN <= value <= _MSGPACK_INT_MAX


def _deep_clean_placeholders(value: Any) -> Any:
    """Null-placeholder cleanup + stringify ints that cannot be msgpack'd."""
    if isinstance(value, dict):
        return {k: _deep_clean_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_clean_placeholders(v) for v in value]
    # bool is a subclass of int — leave True/False alone.
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not _fits_msgpack_int(value):
        return str(value)
    return _clean_value(value)

def _safe_json_parse(raw: Any, field_name: str, company_name: str) -> Any:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    if _is_null_placeholder(raw):
        return None
        
    try:
        # Pass 1: Standard clean parse
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        # Pass 2: Clean known escape sequence collisions
        try:
            sanitized = raw.replace('\\/', '/').replace('/_', '_')
            return json.loads(sanitized)
        except Exception:
            # Pass 3: Ultimate Regex Fallback for highly broken serialized object strings
            if field_name == "technologies":
                logger.info(f"Applying robust regex extraction recovery for {company_name} technologies field.")
                
                # Regex patterns to isolate objects, uid, and names even with broken surrounding quotes
                object_blocks = re.findall(r'\{([^}]+)\}', raw)
                recovered_list = []
                
                for block in object_blocks:
                    uid_match = re.search(r'"uid"\s*:\s*"([^"]+)"', block)
                    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', block)
                    category_match = re.search(r'"category"\s*:\s*"([^"]+)"', block)
                    
                    if uid_match and name_match:
                        recovered_list.append({
                            "uid": uid_match.group(1),
                            "name": name_match.group(1),
                            "category": category_match.group(1) if category_match else "Other"
                        })
                
                if recovered_list:
                    return recovered_list

            # Log warning if even the fallback couldn't extract structures
            logger.warning(
                "normalize_parse_failed company=%s field=%s error=%s",
                company_name, field_name, exc,
            )
            return None


def _safe_int(value: Any, field_name: str, company_name: str) -> Optional[int]:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    # Apollo range labels: "10000+", "1-10", "10001+", "10,000+"
    if isinstance(cleaned, str):
        s = cleaned.strip().replace(",", "").replace(" ", "")
        if s.endswith("+"):
            s = s[:-1]
        if "-" in s and not s.startswith("-"):
            # Take the upper bound of a range like "5001-10000"
            parts = s.split("-")
            s = parts[-1] if parts[-1] else parts[0]
        cleaned = s
    try:
        parsed = int(float(cleaned)) if isinstance(cleaned, str) else int(cleaned)
    except (ValueError, TypeError, OverflowError) as exc:
        logger.warning(
            "normalize_int_coercion_failed company=%s field=%s value=%r error=%s",
            company_name, field_name, value, exc,
        )
        return None
    if not _fits_msgpack_int(parsed):
        logger.warning(
            "normalize_int_exceeds_msgpack company=%s field=%s value=%r",
            company_name, field_name, value,
        )
        return None
    return parsed


def _flatten_tech_stack(tech_list: Any) -> List[str]:
    if not isinstance(tech_list, list):
        return []
    names = []
    for t in tech_list:
        if isinstance(t, dict) and t.get("name"):
            names.append(str(t["name"]))
        elif isinstance(t, str) and t.strip():
            names.append(t.strip())
    return names


def _normalize_single_company(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalize one raw vendor record into a clean dict.
    Returns None if the record is too malformed — never raises,
    so one bad row never kills the whole batch.
    """
    company_name = raw.get("name") or "Unknown"
 
    try:
        technologies     = _flatten_tech_stack(
            _safe_json_parse(raw.get("technologies"), "technologies", company_name) or []
        )
        competitors      = _safe_json_parse(raw.get("competitors"),       "competitors",       company_name) or []
        departments      = _safe_json_parse(raw.get("departments"),       "departments",       company_name) or {}
        keywords         = _safe_json_parse(raw.get("keywords"),          "keywords",          company_name) or []
        funding_events   = _safe_json_parse(raw.get("funding_events"),    "funding_events",    company_name) or []
        suborganizations = _safe_json_parse(raw.get("suborganizations"),  "suborganizations",  company_name) or []
 
        # Intent signals — sourcer delivers these; empty until sourcer is ready.
        # Stored as-is so scoring.py can filter by recency and build the prompt.
        raw_intent = raw.get("intent_signals") or {}
        raw_job_offers = raw_intent.get("job_offers", [])
        raw_news       = raw_intent.get("news", [])
 
        intent_signals = {
            "job_offers": _deep_clean_placeholders(
                raw_job_offers if isinstance(raw_job_offers, list) else []
            ),
            "news": _deep_clean_placeholders(
                raw_news if isinstance(raw_news, list) else []
            ),
        }

        loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        city = _clean_value(raw.get("city") or loc.get("city"))
        country = _clean_value(raw.get("country") or loc.get("country"))
        state = _clean_value(raw.get("state") or loc.get("state"))
        inferred_continent = continent_for_country(country)
        continent = _clean_value(
            raw.get("continent")
            or (inferred_continent.title() if inferred_continent else None)
        )
 
        return {
            "name":       company_name,
            "apollo_id":  _clean_value(raw.get("apollo_id")),
            "domain":     _clean_value(raw.get("domain")),
            "website_url": _clean_value(raw.get("website_url")),
 
            # Industry: raw kept for audit, mapped filled by taxonomy step.
            # global_industry is Apollo's canonical vertical (often cleaner than raw).
            "industry_raw":     _clean_value(raw.get("industry")),
            "global_industry":  _clean_value(raw.get("global_industry")),
            "mapped_industry":  None,
 
            # Numeric fields
            "estimated_num_employees": _safe_int(raw.get("estimated_num_employees"), "estimated_num_employees", company_name),
            "annual_revenue":          _safe_int(raw.get("annual_revenue"),          "annual_revenue",          company_name),
            "founded_year":            _safe_int(raw.get("founded_year"),            "founded_year",            company_name),
 
            # Location — flatten nested Apollo `location`; infer continent from country
            "city":      city,
            "country":   country,
            "state":     state,
            "continent": continent,
 
            # Funding
            "latest_funding_stage": _clean_value(raw.get("latest_funding_stage")),
            "funding_events": _deep_clean_placeholders(
                funding_events if isinstance(funding_events, list) else []
            ),
 
            # Enrichment
            "tech_stack":   technologies,
            "competitors":  _deep_clean_placeholders(
                competitors if isinstance(competitors, list) else []
            ),
            "departments":  _deep_clean_placeholders(
                departments if isinstance(departments, dict) else {}
            ),
            "keywords":     _deep_clean_placeholders(
                keywords if isinstance(keywords, list) else []
            ),

            # Subsidiary info
            "is_subsidiary":  bool(raw.get("is_subsidiary", False)),
            "parent_company": _clean_value(raw.get("parent_company")),
            "suborganizations": _deep_clean_placeholders(
                suborganizations if isinstance(suborganizations, list) else []
            ),

            # Descriptions (used by exclude keyword check + LLM intent scoring)
            "full_description":  _clean_value(raw.get("full_description")),
            "short_description": _clean_value(raw.get("short_description")),

            # Intent signals (job offers + news from sourcer agent)
            "intent_signals": intent_signals,
            # Personas — passed through as-is for node 5 to score and rank.
            # Node 2 does not touch these; node 5 owns all persona logic.
            "raw_target_personas": _deep_clean_placeholders(
                raw.get("raw_target_personas") or []
            ),
 
            # Meta
            "linkedin_url":       _clean_value(raw.get("linkedin_url")),
            "data_quality_score": _clean_value(raw.get("data_quality_score")),
        }
 
    except Exception as exc:
        logger.error(
            "normalize_company_failed company=%s error=%s",
            company_name, exc, exc_info=True,
        )
        return None




# ══════════════════════════════════════════════════════════════════════════════
# GATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _check_exclude_criteria(company: Dict[str, Any], icp: ICPAttributes) -> Optional[str]:
    """
    Check a company against the ICP exclude layer.
    Returns a reason string if excluded, None if the company is safe to proceed.

    Industry excludes match industry labels only (not free-text descriptions) —
    scanning prose for terms like "Software" false-positives fintechs.
    Keyword excludes match company name + keyword tags only (not long descriptions)
    so marketing copy containing "competitor" does not wipe valid accounts.
    """
    if not icp or not hasattr(icp, "exclude") or not icp.exclude:
        return None

    exclude = icp.exclude
    co_name = str(company.get("name", "")).lower()

    # 1. INDUSTRY EXCLUSIONS (industry attributes only)
    raw_ind = company.get("industry_raw")
    mapped_ind = company.get("mapped_industry")
    global_ind = company.get("global_industry")

    if exclude.industries:
        for ex_ind in exclude.industries:
            ex_lower = ex_ind.lower()

            if raw_ind and ex_lower in str(raw_ind).lower():
                return f"EXCLUDED_INDUSTRY: Banned sector '{ex_ind}' found in raw industry label."

            if mapped_ind and ex_lower in str(mapped_ind).lower():
                return f"EXCLUDED_INDUSTRY: Banned sector '{ex_ind}' found in mapped industry label."

            if global_ind and ex_lower in str(global_ind).lower():
                return f"EXCLUDED_INDUSTRY: Banned sector '{ex_ind}' found in global industry label."

    # 2. KEYWORD EXCLUSIONS (name + keyword tags — not full description prose)
    keyword_haystack = co_name
    co_keywords = company.get("keywords") or []
    if isinstance(co_keywords, list):
        keyword_haystack += " " + " ".join(str(k).lower() for k in co_keywords)

    if exclude.keywords:
        for kw in exclude.keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            # Whole-phrase match so "competitor" does not fire inside unrelated tokens.
            pattern = r"(?<!\w)" + re.escape(kw_lower) + r"(?!\w)"
            if re.search(pattern, keyword_haystack):
                return f"EXCLUDED_KEYWORD_FOUND: Banned keyword '{kw}' caught in data profiles."

    # 3. COMPANY SIZE RANGE EXCLUSIONS
    co_size = company.get("estimated_num_employees")
    if exclude.company_size and co_size is not None:
        ex_min = exclude.company_size.min if exclude.company_size.min is not None else 0
        ex_max = exclude.company_size.max if exclude.company_size.max is not None else float('inf')
        if ex_min <= co_size <= ex_max:
            return f"EXCLUDED_COMPANY_SIZE: Headcount {co_size} falls within banned range [{ex_min}-{ex_max}]."

    return None


# ══════════════════════════════════════════════════════════════════════════════
# DISQUALIFICATION LOG BUILDER
# ══════════════════════════════════════════════════════════════════════════════
def _build_disqualification_log(
    disqualified_records: List[DisqualificationRecord],
    total_evaluated: int,
    total_passed: int,
) -> DisqualificationLog:
    """Build a properly-typed DisqualificationLog from a batch of records."""
    summary: Dict[str, int] = {}
    for rec in disqualified_records:
        code = rec.get("reason_code", "UNKNOWN")
        summary[code] = summary.get(code, 0) + 1

    return DisqualificationLog(
        total_evaluated=total_evaluated,
        total_passed=total_passed,
        total_disqualified=len(disqualified_records),
        records=disqualified_records,
        summary=summary,
    )


def _make_record(
    entity_type: str,
    entity_name: str,
    reason_code: str,
    reason_detail: str,
    entity_id: Optional[str] = None,
    firm_score: Optional[float] = None,
    campaign_id: Optional[str] = None,
) -> DisqualificationRecord:
    """Construct a DisqualificationRecord with a UTC timestamp."""
    return DisqualificationRecord(
        entity_type=entity_type,
        entity_name=entity_name,
        entity_id=entity_id,
        reason_code=reason_code,
        reason_detail=reason_detail,
        firm_score=firm_score,
        timestamp=datetime.now(timezone.utc).isoformat(),
        campaign_id=campaign_id,
    )

def extract_icp_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 1 — Parse raw ICP text into a structured ICPAttributes object.
    Writes: extracted_icp, pipeline_error (on failure)
    """
    raw_text = state.get("icp_description_text", "").strip()

    if not raw_text:
        logger.error("extract_icp_node: empty icp_description_text — pipeline cannot proceed.")
        return {
            "extracted_icp": None,
            "pipeline_error": "ICP extraction failed: empty icp_description_text.",
        }

    try:
        accumulator = get_campaign_accumulator(state.get("campaign_id", "unknown"))
        icp = _extractor.extract(raw_text, accumulator=accumulator)
        logger.info(
            "extract_icp_node: industries=%s countries=%s roles=%s",
            icp.must_have.industry,
            icp.must_have.target_countries,
            icp.target_roles,
        )
        return {"extracted_icp": icp}

    except Exception as exc:
        logger.error("extract_icp_node: failed error=%s", exc, exc_info=True)
        return {
            "extracted_icp": None,
            "pipeline_error": f"ICP extraction failed: {exc}",
        }
# ══════════════════════════════════════════════════════════════════════════════
# NODE 1.5 — company_sourcing_node
# Sits between extract_icp_node and normalize_company_data_node.
# Pauses the pipeline after ICP extraction so the orchestrator can send
# the ICP attributes to the sourcer agent and receive raw companies back.
# ══════════════════════════════════════════════════════════════════════════════

def company_sourcing_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 1.5 — Company Sourcing Gate.

    Pauses the pipeline using LangGraph's interrupt() so the orchestrator
    can hand the extracted ICP attributes to the sourcer agent, wait for
    it to query Apollo, and feed the raw companies back in via resume.

    Interrupt payload (sent to orchestrator):
      {
        "type": "company_sourcing_required",
        "icp_filters": {
            "industries":         ["Insurance", "Fintech"],
            "target_countries":   ["France", "Germany"],
            "target_continents":  ["Europe"],
            "company_size": {
                "min": 500,
                "max": 20000,
            },
            "target_roles": ["VP of Sales", "CRO"]
        }
      }

    Resume contract:
      - List[Dict] of raw Apollo company dicts → fed into sourced_companies
      - Empty list → no companies found, pipeline logs warning and continues
        (Node 3 will produce an empty output, which is a valid result)

    Writes: sourced_companies
    """
    logger.info("Entering Node 1.5: Company Sourcing Gate — pausing for sourcer.")

    if state.get("pipeline_error"):
        logger.error("company_sourcing_node: pipeline halted — %s", state["pipeline_error"])
        return {}

    icp = _coerce_icp(state.get("extracted_icp"))
    if not icp:
        logger.error("company_sourcing_node: no extracted_icp in state — halting.")
        return {
            "pipeline_error": "company_sourcing_node: Missing extracted_icp.",
        }

    # Build the sourcing filters from the structured ICP.
    # Must-have fields drive Apollo sourcing; nice-to-have fields are included
    # so the orchestrator can persist the full parsed ICP snapshot.
    size = getattr(icp.must_have, "company_size", None)
    nice = getattr(icp, "nice_to_have", None)
    revenue = getattr(nice, "revenue_range", None) if nice else None
    cities_raw = list(getattr(nice, "target_cities", None) or []) if nice else []
    target_cities: list = []
    for city in cities_raw:
        if hasattr(city, "model_dump"):
            target_cities.append(city.model_dump())
        elif isinstance(city, dict):
            target_cities.append(city)
        else:
            target_cities.append(str(city))

    icp_filters = {
        "industries":        icp.must_have.industry or [],
        "target_countries":  icp.must_have.target_countries or [],
        "target_continents": icp.must_have.target_continents or [],
        "company_size": {
            "min": size.min if size and size.min is not None else None,
            "max": size.max if size and size.max is not None else None,
        },
        # Drives Apollo person_titles[] on persona search (orchestrator → sourcer).
        "target_roles":      list(getattr(icp, "target_roles", None) or []),
        "revenue_range": {
            "min": revenue.min if revenue and getattr(revenue, "min", None) is not None else None,
            "max": revenue.max if revenue and getattr(revenue, "max", None) is not None else None,
        },
        "tech_stack": list(getattr(nice, "tech_stack", None) or []) if nice else [],
        "growth_stage": getattr(nice, "growth_stage", None) if nice else None,
        "funding_stage": getattr(nice, "funding_stage", None) if nice else None,
        "target_cities": target_cities,
    }

    logger.info(
        "company_sourcing_node: requesting companies for industries=%s "
        "countries=%s target_roles=%s",
        icp_filters["industries"],
        icp_filters["target_countries"],
        icp_filters["target_roles"],
    )

    # Pause here. The orchestrator receives this payload, calls the sourcer,
    # and resumes with the raw company list.
    sourced_companies = interrupt({
        "type":        "company_sourcing_required",
        "icp_filters": icp_filters,
    })

    # Normalise the response — sourcer should always return a list,
    # but guard against None to avoid crashing Node 2.
    if not sourced_companies:
        logger.warning(
            "company_sourcing_node: sourcer returned empty company list. "
            "Pipeline will continue — Node 3 will produce empty output."
        )
        sourced_companies = []

    logger.info(
        "company_sourcing_node: sourcer returned %d raw companies.",
        len(sourced_companies),
    )

    return {"sourced_companies": sourced_companies}

def normalize_company_data_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 2 — Clean and normalize raw vendor company dicts.
    Writes: sourced_companies (normalized, deduplicated, taxonomy-mapped)
    """
    if state.get("pipeline_error"):
        logger.error("normalize_company_data_node: pipeline halted — %s", state["pipeline_error"])
        return {}
 
    raw_list = state.get("sourced_companies", [])
 
    normalized = [
        cleaned for raw in raw_list
        if (cleaned := _normalize_single_company(raw)) is not None
    ]

 
    icp = state.get("extracted_icp")
    if not icp:
        logger.warning(
            "normalize_company_data_node: no extracted_icp, "
            "taxonomy mapping runs without ICP context"
        )
 
    icp_industries = icp.must_have.industry if icp else []
    raw_industries = [c["industry_raw"] for c in normalized if c["industry_raw"]]
 
    if raw_industries:
        accumulator = get_campaign_accumulator(state.get("campaign_id", "unknown"))
        mapping = map_industries_batch(raw_industries, icp_industries, accumulator=accumulator)
        for c in normalized:
            if c["industry_raw"]:
                c["mapped_industry"] = mapping.get(c["industry_raw"])
 
    logger.info(
        "normalize_company_data_node: input=%d normalized=%d failed=%d",
        len(raw_list), len(normalized), len(raw_list) - len(normalized),
    )

 
    return {"sourced_companies": normalized}


def filter_and_gate_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 3: Defensive Filtering & Gating Layer

    Applies, in order:
      1. State-driven blacklist (from state['blacklist']['companies'])
      2. Must-have industry hard gate
      3. Must-have company size hard gate
      4. ICP exclude-criteria (industry/keyword/size)

    Returns only the keys this node writes (LangGraph partial-update contract).
    """
    logger.info("Entering Node 3: Batch Gating & Filtering Layer")

    # ── Circuit breaker ────────────────────────────────────────────────────
    if state.get("pipeline_error"):
        logger.error("filter_and_gate_node: pipeline halted — %s", state["pipeline_error"])
        return {}

    icp: Optional[ICPAttributes] = _coerce_icp(state.get("extracted_icp"))
    companies: List[Dict[str, Any]] = state.get("sourced_companies", [])
    campaign_id: Optional[str] = state.get("campaign_id")

    if not icp:
        logger.error("filter_and_gate_node: Missing structured ICP context — halting.")
        return {
            "pipeline_error": "filter_and_gate_node: Missing extracted_icp.",
        }

    # ── Resolve blacklist from BlacklistConfig ──────────────────────────────
    # Company entries are regex patterns (case-insensitive) so slight name
    # variants still match the same blocked account.
    blacklist_config = state.get("blacklist") or {}
    company_blacklist: List[str] = list(blacklist_config.get("companies") or [])

    valid_companies: List[Dict[str, Any]] = []
    disqualified_records: List[DisqualificationRecord] = []

    for company in companies:
        co_name = (company.get("name") or "Unknown").strip()
        co_id = company.get("apollo_id") or company.get("domain")
        is_dropped = False
        reason_code = ""
        drop_reason = ""

        # ─── CHECK 1: STATE-DRIVEN BLACKLIST (regex) ───────────────────────
        if _company_matches_blacklist(co_name, company_blacklist):
            is_dropped = True
            reason_code = "BLACKLIST_MATCH"
            drop_reason = f"'{co_name}' matched account blacklist."

        # ─── CHECK 2: MUST-HAVE INDUSTRY HARD GATE ────────────────────────
        if not is_dropped and icp.must_have.industry:
            target_industries = [ind.lower() for ind in icp.must_have.industry]
            mapped_ind = str(company.get("mapped_industry") or "").lower()
            raw_ind = str(company.get("industry_raw") or "").lower()
            # Apollo's canonical vertical — often cleaner than vendor raw labels
            # (e.g. raw="Automotive Distribution", global_industry="Finance").
            global_ind = str(company.get("global_industry") or "").lower()

            industry_hit = any(
                t_ind in mapped_ind or t_ind in raw_ind or t_ind in global_ind
                for t_ind in target_industries
            )
            if not industry_hit:
                is_dropped = True
                reason_code = "MUST_HAVE_INDUSTRY_MISS"
                display_ind = (
                    company.get("mapped_industry")
                    or company.get("global_industry")
                    or company.get("industry_raw")
                )
                drop_reason = (
                    f"Company industry '{display_ind}' "
                    f"does not match any required ICP industry {icp.must_have.industry}."
                )

        # ─── CHECK 3: MUST-HAVE COMPANY SIZE HARD GATE ────────────────────
        if not is_dropped:
            icp_size = icp.must_have.company_size
            co_size = company.get("estimated_num_employees")
            if co_size is not None and (icp_size.min is not None or icp_size.max is not None):
                # Load near_miss_band from config for tolerance
                firm_weights = safe_load_firmographic_weights(state.get("configurable_weights"))
                near_miss_band = firm_weights.near_miss_band  # Default 0.10 (±10%)
                
                min_s = icp_size.min if icp_size.min is not None else 0
                max_s = icp_size.max if icp_size.max is not None else float("inf")
                
                # Apply ±10% tolerance to the hard gate
                lower_band = min_s * (1.0 - near_miss_band) if min_s > 0 else 0
                upper_band = max_s * (1.0 + near_miss_band) if max_s != float("inf") else float("inf")
                
                if not (lower_band <= co_size <= upper_band):
                    is_dropped = True
                    reason_code = "MUST_HAVE_SIZE_MISS"
                    drop_reason = (
                        f"Headcount {co_size} falls outside required ICP range "
                        f"[{int(min_s)}-{int(max_s) if max_s != float('inf') else 'unlimited'}] "
                        f"(including ±{int(near_miss_band * 100)}% tolerance)."
                    )

        # ─── CHECK 4: ICP EXCLUDE CRITERIA ───────────────────────────────
        if not is_dropped:
            exclude_reason = _check_exclude_criteria(company, icp)
            if exclude_reason:
                is_dropped = True
                # Extract the code prefix (e.g. "EXCLUDED_INDUSTRY") from the detail string
                reason_code = exclude_reason.split(":")[0].strip()
                drop_reason = exclude_reason

        # ─── PROCESS GATING OUTCOME ───────────────────────────────────────
        if is_dropped:
            logger.warning("Disqualified '%s': %s", co_name, drop_reason)
            disqualified_records.append(
                _make_record(
                    entity_type="company",
                    entity_name=co_name,
                    entity_id=co_id,
                    reason_code=reason_code,
                    reason_detail=drop_reason,
                    campaign_id=campaign_id,
                )
            )
        else:
            logger.info("Company '%s' passed all defensive constraints.", co_name)
            valid_companies.append(company)

    total_evaluated = len(companies)
    total_passed = len(valid_companies)
    disq_log = _build_disqualification_log(
        disqualified_records=disqualified_records,
        total_evaluated=total_evaluated,
        total_passed=total_passed,
    )

    logger.info(
        "filter_and_gate_node: evaluated=%d passed=%d disqualified=%d",
        total_evaluated, total_passed, len(disqualified_records),
    )

    return {
        "filtered_companies": valid_companies,
        "sourced_companies": valid_companies,   # Forward surviving companies to next node
        "disqualification_log": disq_log,
    }


def score_and_rank_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 4 — Geospatial Filtering + Firmographic Scoring + Funding Intent + Tier Assignment
 
    Execution Order:
      1. Geospatial Gate: Hard-drop country/continent mismatches; preferred-city
         radius mismatches are kept and soft-penalized (default 3%).
      2. Firmographic Fit: Scores using configurable weights.
      3. Funding Intent: Companies >= passing_threshold get a funding-based
         intent_score (funding_events + latest_funding_stage). LLM intent runs
         later in rescore_with_intent after sourcer signals arrive.
      4. Nurture Bucket: Companies between nurture_threshold and passing_threshold → nurture list.
      5. Composite Synthesis: fit * firmographic_weight + intent * intent_weight,
         assigns Tiers (A/B/C), sorts descending.
 
    Returns only the keys this node writes (LangGraph partial-update contract).
    """
    logger.info("Entering Node 4: Geo-Filter & Scoring Engine.")
 
    if state.get("pipeline_error"):
        logger.error("score_and_rank_node: pipeline halted — %s", state["pipeline_error"])
        return {}
 
    icp          = _coerce_icp(state.get("extracted_icp"))
    companies    = state.get("sourced_companies", [])
    llm          = _get_groq_llm()
    campaign_id  = state.get("campaign_id")
    user_offering = state.get("user_offering", "")

    # Set up usage tracking
    accumulator = get_campaign_accumulator(campaign_id)
    callback = make_callback(accumulator, "score_and_rank")
    logger.info("score_and_rank_node: usage tracking initialized with callback")
 
    if not icp:
        logger.error("score_and_rank_node: Missing ICP context — halting.")
        return {"pipeline_error": "score_and_rank_node: Missing extracted_icp."}
 
    # Load all configurable thresholds and weights from config
    firm_weights      = safe_load_firmographic_weights(state.get("configurable_weights"))
    passing_threshold = firm_weights.passing_threshold
    nurture_threshold = firm_weights.nurture_threshold
    state_weights     = state.get("configurable_weights")
 
    # ── STEP 1: GEOSPATIAL FILTERING ──────────────────────────────────────
    logger.info("Evaluating geospatial constraints for %d companies.", len(companies))
    geo_filtered = _location_agent.filter_companies(
        icp, companies, max_km=firm_weights.max_km_radius
    )
 
    geo_filtered_names = {co.get("name") for co in geo_filtered if co.get("name")}
    geo_disqualified_records: List[DisqualificationRecord] = []
    for co in companies:
        co_name = (co.get("name") or "Unknown").strip()
        if co_name not in geo_filtered_names:
            # Hard drop only for country/continent (radius is soft-penalized).
            geo_disqualified_records.append(
                _make_record(
                    entity_type="company",
                    entity_name=co_name,
                    entity_id=co.get("apollo_id") or co.get("domain"),
                    reason_code="GEOSPATIAL_MISMATCH",
                    reason_detail="Target location outside matching ICP country/continent.",
                    campaign_id=campaign_id,
                )
            )
 
    # ── STEP 2 & 3: FIRMOGRAPHIC SCORING + INTENT GATE ───────────────────
    ranked_list:    List[Dict[str, Any]]        = []
    nurture_list:   List[Dict[str, Any]]        = []
    discard_records: List[DisqualificationRecord] = []
 
    for co in geo_filtered:
        co_name = (co.get("name") or "Unknown").strip()
        co_id   = co.get("apollo_id") or co.get("domain")
 
        # Firmographic fit — pass firm_weights so config thresholds are used
        firm_results = calculate_company_score(co, icp, state_weights, llm, firm_weights, callbacks=[callback])
        firm_score_raw = firm_results.get("firmographic_score", 0.0)

        # Soft preferred-city radius penalty (keep company, reduce firm score).
        geo_radius_mismatch = bool(co.get("geo_radius_mismatch"))
        geo_penalty_frac = (
            firm_weights.geo_radius_mismatch_penalty if geo_radius_mismatch else 0.0
        )
        firm_score = (
            round(firm_score_raw * (1.0 - geo_penalty_frac), 2)
            if geo_penalty_frac
            else firm_score_raw
        )
        if geo_radius_mismatch:
            logger.info(
                "geo_radius_penalty company='%s' dist=%s raw=%.2f penalty=%.0f%% scored=%.2f",
                co_name,
                co.get("dist"),
                firm_score_raw,
                geo_penalty_frac * 100,
                firm_score,
            )
        
        # Calculate overall match quality for UI display
        breakdown = firm_results.get("breakdown", {})
        overall_match = calculate_overall_match_quality(breakdown)
 
        # Funding-based intent proxy for rank_companies (LLM intent runs at rescore).
        if firm_score >= passing_threshold:
            logger.info(
                "Core fit passed (%.1f/%.1f). Scoring funding intent for '%s'.",
                firm_score, passing_threshold, co_name,
            )
            funding_intent = calculate_funding_intent_score(
                co, icp, firm_weights=firm_weights
            )
            intent_score = funding_intent["intent_score"]
            intent_reasoning = funding_intent["intent_reasoning"]
            intent_breakdown = funding_intent["intent_breakdown"]
        else:
            intent_score     = 0
            intent_reasoning = (
                f"Skipped: Firmographic fit ({firm_score:.1f}) below passing "
                f"threshold ({passing_threshold})."
            )
            intent_breakdown = None
 
        # ── Composite synthesis — weights come from config, not hardcoded ──
        total_score = (
            (firm_score   * firm_weights.firmographic_weight) +
            (intent_score * firm_weights.intent_weight)
        )
 
        if total_score >= 80.0:
            tier = "A"
        elif total_score >= 50.0:
            tier = "B"
        else:
            tier = "C"
 
        co["qualification_metrics"] = {
            "firmographic_score": firm_score,
            "firmographic_score_raw": firm_score_raw,
            "intent_score":       intent_score,
            "total_score":        round(total_score, 2),
            "tier":               tier,
            "overall_match":      overall_match,
            "intent_reasoning":   intent_reasoning,
            "intent_breakdown":   intent_breakdown,
            "breakdown":          firm_results.get("breakdown", {}),
            "applied_weights":    firm_results.get("normalized_weights", {}),
            "geo_radius_mismatch": geo_radius_mismatch,
            "geo_radius_penalty": geo_penalty_frac,
            "dist_km":            co.get("dist"),
        }
 
        # ── Bucket assignment ─────────────────────────────────────────────
        if firm_score >= passing_threshold:
            logger.info("Evaluated '%s': Score=%.2f -> Tier %s", co_name, total_score, tier)
            ranked_list.append(co)
        elif firm_score >= nurture_threshold:
            logger.info(
                "Nurture '%s': firm_score=%.1f (below %.1f, above %.1f)",
                co_name, firm_score, passing_threshold, nurture_threshold,
            )
            co["qualification_metrics"]["tier"] = "Nurture"
            nurture_list.append(co)
        else:
            logger.info(
                "Discard '%s': firm_score=%.1f below nurture threshold %.1f",
                co_name, firm_score, nurture_threshold,
            )
            discard_records.append(
                _make_record(
                    entity_type="company",
                    entity_name=co_name,
                    entity_id=co_id,
                    reason_code="BELOW_NURTURE_THRESHOLD",
                    reason_detail=(
                        f"Firmographic score {firm_score:.1f} below nurture "
                        f"threshold {nurture_threshold}."
                    ),
                    firm_score=firm_score,
                    campaign_id=campaign_id,
                )
            )
 
    ranked_list.sort(
        key=lambda x: x["qualification_metrics"]["total_score"], reverse=True
    )
 
    all_disq_records = geo_disqualified_records + discard_records
    disq_log = _build_disqualification_log(
        disqualified_records=all_disq_records,
        total_evaluated=len(companies),
        total_passed=len(ranked_list),
    )
 
    logger.info(
        "score_and_rank_node: evaluated=%d ranked=%d nurture=%d discarded=%d",
        len(companies), len(ranked_list), len(nurture_list), len(discard_records),
    )
 
    return {
        "sourced_companies":  ranked_list,
        "ranked_companies":   ranked_list,
        "nurture_companies":  nurture_list,
        "disqualification_log": disq_log,
    }
 

# ══════════════════════════════════════════════════════════════════════════════
# NEW NODE — human_review_node
# Sits between score_and_rank_node and rank_personas_node.
# Pauses the graph so the frontend can present ranked companies to the user.
# Resumes when the frontend sends back a list of approved apollo_ids.
# ══════════════════════════════════════════════════════════════════════════════
 
def human_review_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 4.5 — Orchestrator sync gate (auto-approve, no human wait).

    Always pauses via interrupt() so the orchestrator can:
      1. Fetch intent / personas for ranked (or fallback) companies
      2. Resume with approved apollo_ids + sourced_personas_by_company

    Even when ranked_companies is empty we still interrupt — skipping the
    pause would let rank_personas run with no personas and break Phase 3.

    Resume contract:
      - List[str] of apollo_ids  → only those companies proceed to persona ranking
      - None or empty list       → all ranked companies proceed (auto-approve all)
    """
    logger.info("Entering Node 4.5: Sync gate — pausing for orchestrator (auto-approve).")

    if state.get("pipeline_error"):
        logger.error("human_review_node: pipeline halted — %s", state["pipeline_error"])
        return {}

    ranked_companies = state.get("ranked_companies", []) or []

    # Always interrupt so MCP Phase 2/3 sync stays aligned (even if ranked is empty).
    review_payload = [
        {
            "apollo_id":             co.get("apollo_id"),
            "name":                  co.get("name"),
            "domain":                co.get("domain"),
            "qualification_metrics": co.get("qualification_metrics", {}),
            "is_subsidiary":         co.get("is_subsidiary", False),
            "parent_company":        co.get("parent_company"),
        }
        for co in ranked_companies
    ]

    if not ranked_companies:
        logger.warning(
            "human_review_node: no ranked companies — still interrupting for orchestrator sync."
        )

    approved_apollo_ids = interrupt(review_payload)

    if not approved_apollo_ids:
        logger.info(
            "human_review_node: auto-approved all %d companies.", len(ranked_companies)
        )
        return {"user_approved_companies": None}

    logger.info(
        "human_review_node: proceeding with %d/%d companies.",
        len(approved_apollo_ids), len(ranked_companies),
    )
    return {"user_approved_companies": list(approved_apollo_ids)}
 
 
# ══════════════════════════════════════════════════════════════════════════════
# UPDATED — rank_personas_node
# Removes the old interrupt() block that was incorrectly placed here.
# Now purely reads user_approved_companies from state (set by human_review_node).
def rank_personas_node(state: CampaignState) -> Dict[str, Any]:
    """
    Node 5 — Dual-Axis Persona Fit Optimization & CEO Fallback Guardrail
 
    Ranks contacts for each approved company using functional relevance,
    seniority, email safety, and tenure triggers.
 
    Persona data arrives separately from company data — the sourcer fetches
    personas AFTER the user approves companies at the human_review interrupt.
    Personas are delivered into state['sourced_personas_by_company'] as a
    dict keyed by apollo_id before this node runs.
 
    Returns only the keys this node writes (LangGraph partial-update contract).
    """
    logger.info("Entering Node 5: Persona Selection & Dual-Axis Matrix Engine.")
 
    if state.get("pipeline_error"):
        logger.error("rank_personas_node: pipeline halted — %s", state["pipeline_error"])
        return {}
 
    companies      = state.get("sourced_companies", [])
    icp            = _coerce_icp(state.get("extracted_icp"))
    state_weights  = state.get("configurable_weights") or {}
    llm            = _get_groq_llm()
    user_offering  = state.get("user_offering", "")
    campaign_id    = state.get("campaign_id")

    # Set up usage tracking
    accumulator = get_campaign_accumulator(campaign_id)
    callback = make_callback(accumulator, "rank_personas")
 
    # ── Human-in-the-loop filter ──────────────────────────────────────────
    # user_approved_companies is written by human_review_node.
    # None  → user kept all companies, run on full list.
    # list  → filter to approved apollo_ids only.
    approved = state.get("user_approved_companies")
    if approved is not None:
        approved_set = set(approved)
        original_len = len(companies)
        companies = [
            c for c in companies
            if c.get("apollo_id") in approved_set
        ]
        logger.info(
            "rank_personas_node: approval filter applied — %d/%d companies kept.",
            len(companies), original_len,
        )
 
    # ── Persona delivery from sourcer ─────────────────────────────────────
    # Populated by the orchestrator after human_review interrupt resolves.
    # The orchestrator receives the approved apollo_ids, calls the sourcer
    # agent to fetch personas for those companies specifically, then injects
    # the result into state before resuming the graph.
    # Structure: { apollo_id: [persona_dict, ...] }
    personas_by_company: Dict[str, List[Dict[str, Any]]] = (
        state.get("sourced_personas_by_company") or {}
    )
 
    if not personas_by_company:
        logger.warning(
            "rank_personas_node: sourced_personas_by_company is empty — "
            "no personas delivered by sourcer."
        )

    # If company scoring left sourced_companies empty but personas arrived,
    # synthesize stubs so persona scoring can still run.
    if not companies and personas_by_company:
        companies = [
            {"apollo_id": apollo_id, "name": apollo_id, "domain": None}
            for apollo_id in personas_by_company.keys()
        ]
        logger.warning(
            "rank_personas_node: sourced_companies empty — "
            "synthesized %d stubs from personas_by_company",
            len(companies),
        )
 
    # ── Persona blacklist (LinkedIn URLs) ─────────────────────────────────
    blacklist_config = state.get("blacklist") or {}
    persona_blacklist: List[str] = list(blacklist_config.get("personas") or [])

    target_roles = getattr(icp, "target_roles", []) or []
    target_departments = (
        getattr(icp, "target_departments", getattr(icp, "target_functions", [])) or []
    )
    persona_weights = safe_load_persona_weights(state_weights)
    user_role_weight = float(
        state_weights.get("target_role_match", persona_weights.primary_role_match)
    )

    if not companies:
        logger.warning("rank_personas_node: no companies to process after approval filter.")
        return {"ranked_personas": []}

    all_ranked_personas: List[Dict[str, Any]] = []

    for co in companies:
        co_name    = co.get("name", "Unknown")
        co_id      = co.get("apollo_id")
        domain     = co.get("domain")

        # ── Fetch this company's personas from the sourcer delivery ───────
        raw_personas = list(personas_by_company.get(co_id, []))

        if not raw_personas:
            logger.info(
                "rank_personas_node: no personas delivered for '%s' (apollo_id=%s) — skipping.",
                co_name, co_id,
            )
            co["ranked_target_leads"] = []
            continue

        # ── Normalise titles to English before scoring ─────────────────────
        # One batch LLM call per company — maps multilingual titles
        # (e.g. "Directrice Commerciale" → "Commercial Director") so
        # token matching works correctly regardless of persona language.
        raw_personas = normalise_persona_titles(raw_personas, accumulator=accumulator)

        scored_personas: List[Dict[str, Any]] = []

        for p in raw_personas:
            # Persona blacklist: match on linkedin_url (normalized)
            if _persona_matches_blacklist(p, persona_blacklist):
                logger.info(
                    "Persona blacklisted (linkedin_url): '%s' at '%s'.",
                    p.get("name"),
                    co_name,
                )
                continue

            try:
                fit_results = calculate_persona_fit(
                    persona=p,
                    company_domain=domain,
                    target_roles=target_roles,
                    target_departments=target_departments,
                    user_role_weight=user_role_weight,
                    llm=llm,
                    user_offering=user_offering,
                    callbacks=[callback],
                    persona_weights=persona_weights,
                )
                p.update(fit_results)
                scored_personas.append(p)
            except Exception as exc:
                logger.error(
                    "rank_personas_node: scoring failed for '%s' at '%s': %s",
                    p.get("name"), co_name, exc, exc_info=True,
                )

        # Sort by persona_score descending
        scored_personas.sort(key=lambda x: x.get("persona_score", 0.0), reverse=True)
        co["ranked_target_leads"] = scored_personas
        all_ranked_personas.extend(scored_personas)
 
        logger.info(
            "rank_personas_node: mapped %d ranked contact(s) to '%s'.",
            len(scored_personas), co_name,
        )
 
    logger.info(
        "rank_personas_node: completed — %d total personas ranked across %d companies.",
        len(all_ranked_personas), len(companies),
    )
    return {"ranked_personas": all_ranked_personas}
