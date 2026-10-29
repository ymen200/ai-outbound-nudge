from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


APOLLO_EMPLOYEE_RANGES = [
    ("1,10", 1, 10),
    ("11,50", 11, 50),
    ("51,200", 51, 200),
    ("201,500", 201, 500),
    ("501,1000", 501, 1000),
    ("1001,5000", 1001, 5000),
    ("5001,10000", 5001, 10000),
    # Open-ended top bucket — Apollo expects "10001," not "10001+".
    ("10001,", 10001, 10_000_000),
]

# Legacy hyphen labels still accepted from older callers / .env smoke helpers.
_LEGACY_RANGE_ALIASES = {
    "1-10": "1,10",
    "11-50": "11,50",
    "51-200": "51,200",
    "201-500": "201,500",
    "501-1000": "501,1000",
    "1001-5000": "1001,5000",
    "5001-10000": "5001,10000",
    "10001+": "10001,",
}


def normalize_apollo_employee_ranges(ranges: Optional[List[str]]) -> List[str]:
    """Map legacy '1-10' / '10001+' labels to Apollo's '1,10' / '10001,' format."""
    if not ranges:
        return []
    out: List[str] = []
    seen = set()
    for raw in ranges:
        if not raw:
            continue
        label = _LEGACY_RANGE_ALIASES.get(str(raw).strip(), str(raw).strip())
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def company_size_to_employee_ranges(company_size: Optional[Dict[str, Any]]) -> List[str]:
    if not company_size:
        return []
    min_size = company_size.get("min")
    max_size = company_size.get("max")
    try:
        min_v = float(min_size) if min_size is not None else None
        max_v = float(max_size) if max_size is not None else None
    except (TypeError, ValueError):
        return []

    ranges: List[str] = []
    for label, lo, hi in APOLLO_EMPLOYEE_RANGES:
        if min_v is not None and hi < min_v:
            continue
        if max_v is not None and lo > max_v:
            continue
        ranges.append(label)

    # ICP like 1–200000 covers every Apollo bucket. Sending all of them
    # (especially legacy "10001+") can make Apollo return 0 for some geos.
    # Omit the API size filter and rely on exact min/max post-filter instead.
    all_labels = [label for label, _, _ in APOLLO_EMPLOYEE_RANGES]
    if ranges == all_labels:
        return []
    return ranges


def _parse_headcount(value: Any) -> Optional[int]:
    if value in (None, "", "Non renseigné"):
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    s = str(value).strip().replace(",", "").replace(" ", "")
    if s.endswith("+"):
        s = s[:-1]
    if "-" in s and not s.startswith("-"):
        parts = s.split("-")
        s = parts[-1] if parts[-1] else parts[0]
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def company_within_icp_size(
    company: Dict[str, Any],
    company_size: Optional[Dict[str, Any]],
    *,
    near_miss_band: float = 0.10,
) -> bool:
    """True if company headcount fits ICP size (±near_miss_band). Missing headcount passes."""
    if not company_size:
        return True
    co_size = _parse_headcount(
        company.get("estimated_num_employees")
        if "estimated_num_employees" in company
        else None
    )
    if co_size is None:
        return True
    try:
        min_s = float(company_size["min"]) if company_size.get("min") is not None else 0.0
        max_s = (
            float(company_size["max"])
            if company_size.get("max") is not None
            else float("inf")
        )
    except (TypeError, ValueError):
        return True
    lower = min_s * (1.0 - near_miss_band) if min_s > 0 else 0.0
    upper = max_s * (1.0 + near_miss_band) if max_s != float("inf") else float("inf")
    return lower <= co_size <= upper


def filter_companies_by_icp_size(
    companies: List[Dict[str, Any]],
    company_size: Optional[Dict[str, Any]],
    *,
    near_miss_band: float = 0.10,
) -> List[Dict[str, Any]]:
    """Drop orgs outside ICP headcount (needed because Apollo 10001+ is open-ended)."""
    if not company_size or not companies:
        return companies
    return [
        c for c in companies
        if company_within_icp_size(c, company_size, near_miss_band=near_miss_band)
    ]


def icp_filters_to_sourcer_args(icp_filters: Dict[str, Any]) -> Dict[str, Any]:
    """Map ICP filters → sourcer discovery args.

    Country beats continent: if any target_countries are set, search those
    countries only. Continent expansion runs only for continent-only ICPs
    (e.g. user wrote "Africa" with no specific country).
    """
    locations = icp_filters.get("target_countries") or []
    continent = None
    if not locations:
        continents = icp_filters.get("target_continents") or []
        continent = continents[0] if continents else None
    company_size = icp_filters.get("company_size") or {}
    return {
        "industries": icp_filters.get("industries") or [],
        "locations": locations,
        "continent": continent,
        "employee_ranges": company_size_to_employee_ranges(company_size),
        "min_employees": company_size.get("min"),
        "max_employees": company_size.get("max"),
    }


# ormsgpack (qualifier LangGraph checkpointer) rejects ints outside this range.
_MSGPACK_INT_MIN = -(2**63 - 1)
_MSGPACK_INT_MAX = 2**64 - 1


def _stringify_oversized_ints(value: Any) -> Any:
    """Recursively stringify ints that cannot survive msgpack checkpointing."""
    if isinstance(value, dict):
        return {k: _stringify_oversized_ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_oversized_ints(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not (_MSGPACK_INT_MIN <= value <= _MSGPACK_INT_MAX):
        return str(value)
    return value


def _jsonify_field(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(_stringify_oversized_ints(value), default=str)
    return value


def _parse_employee_count(value: Any) -> Optional[int]:
    """Parse Apollo headcount labels like 120, '10000+', '5001-10000', '10,000+'."""
    return _parse_headcount(value)


def to_qualifier_company(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize sourcer company → qualifier resume_with_companies shape."""
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    employees = _parse_employee_count(raw.get("estimated_num_employees"))
    country = raw.get("country") or loc.get("country")

    return {
        "apollo_id": raw.get("apollo_id") or raw.get("id"),
        "name": raw.get("name") or "Unknown",
        "domain": raw.get("domain"),
        "website_url": raw.get("website_url") or raw.get("website"),
        # Keep raw vendor industry and Apollo's canonical global_industry separate
        # so the qualifier can gate/score on either (raw often diverges from ICP labels).
        "industry": raw.get("industry") or raw.get("global_industry"),
        "global_industry": raw.get("global_industry"),
        "estimated_num_employees": employees,
        "annual_revenue": raw.get("annual_revenue"),
        "founded_year": raw.get("founded_year"),
        "city": raw.get("city") or loc.get("city"),
        "country": country,
        "state": raw.get("state") or loc.get("state"),
        "latest_funding_stage": raw.get("latest_funding_stage") or raw.get("funding_stage"),
        "is_subsidiary": bool(raw.get("is_subsidiary", False)),
        "parent_company": raw.get("parent_company"),
        "full_description": raw.get("full_description") or raw.get("description"),
        "short_description": raw.get("short_description"),
        "linkedin_url": raw.get("linkedin_url"),
        "data_quality_score": raw.get("data_quality_score") or raw.get("quality_score"),
        "technologies": _jsonify_field(raw.get("technologies") or []),
        "keywords": _jsonify_field(raw.get("keywords") or []),
        "funding_events": _jsonify_field(raw.get("funding_events") or []),
        "competitors": _jsonify_field(raw.get("competitors") or []),
        "departments": _jsonify_field(raw.get("departments") or {}),
        "suborganizations": _jsonify_field(raw.get("suborganizations") or []),
        # Firmographic-first pass: empty intent; filled later via rescore_with_intent
        "intent_signals": {"job_offers": [], "news": []},
    }


def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_email_from_enrichment(enrich: Dict[str, Any]) -> str:
    if not isinstance(enrich, dict):
        return ""
    email = _first_non_empty_str(
        enrich.get("email"),
        (enrich.get("apollo_response") or {}).get("email") if isinstance(enrich.get("apollo_response"), dict) else None,
    )
    if email:
        return email

    for key in ("sanitized_emails", "emails"):
        values = enrich.get(key) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                nested = _first_non_empty_str(item.get("email"), item.get("address"))
                if nested:
                    return nested
    return ""


def _extract_phone_from_enrichment(enrich: Dict[str, Any]) -> str:
    if not isinstance(enrich, dict):
        return ""
    phone = _first_non_empty_str(
        enrich.get("phone"),
        enrich.get("phone_number"),
        (enrich.get("apollo_response") or {}).get("phone") if isinstance(enrich.get("apollo_response"), dict) else None,
        (enrich.get("apollo_response") or {}).get("phone_number") if isinstance(enrich.get("apollo_response"), dict) else None,
    )
    if phone:
        return phone

    for key in ("sanitized_numbers", "raw_numbers", "phone_numbers"):
        values = enrich.get(key) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                nested = _first_non_empty_str(
                    item.get("sanitized_number"),
                    item.get("raw_number"),
                    item.get("number"),
                    item.get("phone"),
                    item.get("phone_number"),
                )
                if nested:
                    return nested
    return ""


def limit_companies_for_persona_fetch(
    ranked_companies: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Keep top N companies by total_score after intent rescore."""
    if limit <= 0 or not ranked_companies:
        return []
    ordered = sorted(
        ranked_companies,
        key=lambda c: float(
            (c.get("qualification_metrics") or {}).get("total_score") or 0.0
        ),
        reverse=True,
    )
    return ordered[:limit]


def build_persona_company_map(
    personas_by_company: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, str]:
    """Map persona apollo_id (or name) → company apollo_id."""
    mapping: Dict[str, str] = {}
    for company_id, personas in (personas_by_company or {}).items():
        for persona in personas or []:
            pid = persona.get("apollo_id")
            if pid:
                mapping[str(pid)] = company_id
            name = persona.get("name")
            if name:
                mapping[str(name)] = company_id
    return mapping


def select_best_persona(
    ranked_personas: List[Dict[str, Any]],
    ranked_companies: List[Dict[str, Any]],
    personas_by_company: Dict[str, List[Dict[str, Any]]],
    *,
    company_weight: float = 0.4,
    persona_weight: float = 0.6,
) -> Optional[Dict[str, Any]]:
    """
    Pick one lead across all companies using company total_score + persona_score.

    Returns the winning persona dict with extra keys:
      - company_apollo_id
      - company_total_score
      - combined_lead_score
    """
    if not ranked_personas:
        return None

    companies_by_id = {
        c.get("apollo_id"): c for c in ranked_companies if c.get("apollo_id")
    }
    persona_company = build_persona_company_map(personas_by_company)

    best_persona: Optional[Dict[str, Any]] = None
    best_combined = -1.0

    for persona in ranked_personas:
        persona_id = persona.get("apollo_id") or persona.get("name")
        company_id = (
            persona_company.get(str(persona_id or ""))
            or persona_company.get(str(persona.get("name") or ""))
        )
        company = companies_by_id.get(company_id) or {}
        company_score = float(
            (company.get("qualification_metrics") or {}).get("total_score") or 0.0
        )
        persona_score = float(persona.get("persona_score") or 0.0)
        combined = (company_score * company_weight) + (persona_score * persona_weight)

        if combined > best_combined:
            best_combined = combined
            best_persona = {
                **persona,
                "company_apollo_id": company_id,
                "company_total_score": round(company_score, 2),
                "combined_lead_score": round(combined, 2),
            }

    return best_persona


def build_final_packages(
    *,
    campaign_id: str,
    qualifier_campaign_id: str,
    raw_icp: str,
    user_offering: str,
    icp_filters: Dict[str, Any],
    ranked_companies: List[Dict[str, Any]],
    intent_by_apollo_id: Dict[str, Any],
    ranked_personas: List[Dict[str, Any]],
    contacts: Dict[str, Any],
    personas_by_company: Dict[str, List[Dict[str, Any]]],
    single_lead_mode: bool = False,
) -> List[Dict[str, Any]]:
    companies_by_id = {
        c.get("apollo_id"): c for c in ranked_companies if c.get("apollo_id")
    }

    # Map persona → company via sourced personas lists
    persona_company: Dict[str, str] = {}
    for apollo_id, personas in (personas_by_company or {}).items():
        for p in personas:
            pid = p.get("apollo_id") or p.get("name")
            if pid:
                persona_company[str(pid)] = apollo_id
            if p.get("name"):
                persona_company[p["name"]] = apollo_id

    def _company_block(company: Dict[str, Any], company_id: Optional[str]) -> Dict[str, Any]:
        intent = intent_by_apollo_id.get(company_id) or {}
        return {
            "apollo_id": company.get("apollo_id") or company_id,
            "name": company.get("name"),
            "domain": company.get("domain"),
            "qualification_metrics": company.get("qualification_metrics"),
            "intent_signals": {
                "job_offers": intent.get("job_offers") or [],
                "news": intent.get("news") or [],
            },
            "intent_summary": intent.get("company_intent_summary"),
        }

    icp_block = {
        "raw": raw_icp,
        "features": icp_filters,
        "user_offering": user_offering,
    }

    packages: List[Dict[str, Any]] = []
    companies_with_persona: set = set()

    for idx, persona in enumerate(ranked_personas):
        persona_id = persona.get("apollo_id") or persona.get("name") or f"persona-{idx}"
        company_id = persona_company.get(str(persona_id)) or persona_company.get(persona.get("name") or "")
        company = companies_by_id.get(company_id) or {}
        if company_id:
            companies_with_persona.add(company_id)
        contact = contacts.get(str(persona_id)) or contacts.get(persona_id) or {}

        email = persona.get("email") or ""
        phone = persona.get("phone_number") or persona.get("phone") or ""
        if isinstance(contact, dict):
            email_enrich = contact.get("email_enrichment") or {}
            phone_enrich = contact.get("phone_enrichment") or {}
            if isinstance(email_enrich, dict):
                email = _extract_email_from_enrichment(email_enrich) or email
            if isinstance(phone_enrich, dict):
                # Phone enrich may also carry email (Apollo reveal often returns both)
                email = email or _extract_email_from_enrichment(phone_enrich)
                phone = _extract_phone_from_enrichment(phone_enrich) or phone
            # Email enrich may also carry phone numbers in some payloads
            if isinstance(email_enrich, dict) and not phone:
                phone = _extract_phone_from_enrichment(email_enrich)

        packages.append({
            "lead_id": f"{campaign_id}:{persona_id}",
            "campaign_id": campaign_id,
            "qualifier_campaign_id": qualifier_campaign_id,
            "icp": icp_block,
            "company": _company_block(company, company_id),
            "persona": {
                "apollo_id": persona.get("apollo_id") or persona_id,
                "name": persona.get("name"),
                "title": persona.get("title"),
                "seniority": persona.get("seniority"),
                "email": email,
                "phone": phone,
                "persona_score": persona.get("persona_score"),
                "company_total_score": persona.get("company_total_score"),
                "combined_lead_score": persona.get("combined_lead_score"),
                "is_linkedin_connected": persona.get("is_linkedin_connected"),
                "signals": persona.get("intent") or persona.get("public_signals"),
            },
        })

    # Companies with no Apollo personas still get a package (company + intent, persona null).
    if single_lead_mode:
        return packages

    for company in ranked_companies:
        company_id = company.get("apollo_id")
        if not company_id or company_id in companies_with_persona:
            continue
            packages.append({
                "lead_id": f"{campaign_id}:{company_id}",
                "campaign_id": campaign_id,
                "qualifier_campaign_id": qualifier_campaign_id,
                "icp": icp_block,
                "company": _company_block(company, company_id),
                "persona": None,
                "warning": "no persona selected for company",
            })

    return packages
