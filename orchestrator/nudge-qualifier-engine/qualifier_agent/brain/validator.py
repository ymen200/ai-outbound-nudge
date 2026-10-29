from __future__ import annotations
import re
from typing import Any  # used by _sanitize_range's type hint below
from brain.schemas import (
    ICPAttributes,
    MustHaveTraits,
    NiceToHaveTraits,
    ExcludeCriteria,
    CityContext,
    Range,
)

class ICPValidator:

    # ── Public entry points ──────────────────────────────────────────────────

    @staticmethod
    def clean(data: dict) -> dict:
        """
        Normalise raw LLM output (flat or nested) into the new nested format.
        Returns a dict ready for ICPAttributes(**data).
        """
        if ICPValidator._is_nested(data):
            cleaned = ICPValidator._clean_nested(data)
        else:
            cleaned = ICPValidator._clean_flat(data)

        # Generic fix: any city's country must also appear in must_have.target_countries.
        # Replaces one-off per-city patches (e.g. hardcoded "Tunis" recovery) with a
        # single reconciliation step that works for every city, every time.
        ICPValidator._reconcile_cities_and_countries(
            cleaned["must_have"], cleaned["nice_to_have"]
        )
        return cleaned

    @staticmethod
    def validate(data: dict) -> ICPAttributes:
        cleaned = ICPValidator.clean(data)
        return ICPAttributes(**cleaned)

    # ── Shape detection ──────────────────────────────────────────────────────

    @staticmethod
    def _is_nested(data: dict) -> bool:
        return "must_have" in data or "nice_to_have" in data or (
            "exclude" in data and isinstance(data["exclude"], dict)
            and ("industries" in data["exclude"] or "keywords" in data["exclude"])
        )

    # ── Range and Numeric Sanitization Guardrail ──────────────────────────────

    @staticmethod
    def _sanitize_range(range_data: Any) -> dict:
        """
        Coerces values to numbers, cleans strings, and fixes inverted min/max bounds.
        """
        default_range = {"min": None, "max": None}
        if not isinstance(range_data, dict):
            return default_range

        cleaned_range = {}
        for key in ["min", "max"]:
            val = range_data.get(key)
            if val is None or val == "":
                cleaned_range[key] = None
                continue

            # If the LLM returned a string like "5,000,000" or "50M", clean it up
            if isinstance(val, str):
                # Strip out punctuation/spaces
                cleaned_str = re.sub(r"[^\d.]", "", val)
                if not cleaned_str:
                    cleaned_range[key] = None
                    continue
                try:
                    val = float(cleaned_str) if "." in cleaned_str else int(cleaned_str)
                except ValueError:
                    cleaned_range[key] = None
                    continue

            if isinstance(val, (int, float)):
                cleaned_range[key] = val
            else:
                cleaned_range[key] = None

        # --- Inverted Bounds Guardrail ---
        m_min = cleaned_range["min"]
        m_max = cleaned_range["max"]
        if m_min is not None and m_max is not None and m_min > m_max:
            cleaned_range["min"], cleaned_range["max"] = m_max, m_min

        return cleaned_range

    # ── Cross-field reconciliation ──────────────────────────────────────────

    @staticmethod
    def _reconcile_cities_and_countries(must_have: dict, nice_to_have: dict) -> None:
        """
        Ensure every nice_to_have.target_cities[].country is also present in
        must_have.target_countries. LLMs sometimes drop a country from the
        must_have list when they judge it "redundant" with a more specific
        city entry — this patches that generically, for every city, instead
        of hardcoding fixes for individual city names.

        Mutates must_have["target_countries"] in place.
        """
        countries = must_have.setdefault("target_countries", [])
        existing_lower = {c.lower() for c in countries if isinstance(c, str)}

        for city in nice_to_have.get("target_cities", []):
            if not isinstance(city, dict):
                continue
            country = city.get("country")
            if isinstance(country, str) and country.strip():
                normalized = country.strip()
                if normalized.lower() not in existing_lower:
                    countries.append(normalized)
                    existing_lower.add(normalized.lower())

    # ── Flat shape (old LLM output) → nested ────────────────────────────────

    @staticmethod
    def _clean_flat(data: dict) -> dict:
        """Convert a flat ICPAttributes dict into the new nested format."""

        # ── must_have ────────────────────────────────────────────────────────
        industry = data.get("industry", [])
        if isinstance(industry, str): industry = [industry]
        if not isinstance(industry, list): industry = []

        continents = data.get("target_continents", [])
        if not isinstance(continents, list): continents = []

        countries = data.get("target_countries", [])
        if not isinstance(countries, list): countries = []

        # Sanitize company size range
        company_size = ICPValidator._sanitize_range(data.get("company_size"))

        must_have = {
            "industry":          _dedupe_list(industry),
            "company_size":      company_size,
            "target_continents": _dedupe_list(continents),
            "target_countries":  _dedupe_list(countries),
        }

        # ── nice_to_have ─────────────────────────────────────────────────────
        # Sanitize revenue range
        revenue_range = ICPValidator._sanitize_range(data.get("revenue_range"))

        cities_raw = data.get("target_cities", [])
        cities = [
            c for c in cities_raw
            if isinstance(c, dict) and c.get("city") and c.get("country")
        ]

        dyn = data.get("dynamic_attributes", {})
        if isinstance(dyn, list):
            dyn = {"tech_stack": dyn}
        if not isinstance(dyn, dict):
            dyn = {}

        tech_stack = dyn.get("tech_stack", [])
        if not isinstance(tech_stack, list): tech_stack = []

        growth_stage = dyn.get("growth_stage")
        if isinstance(growth_stage, list):
            growth_stage = growth_stage[0] if growth_stage else None

        funding_stage = dyn.get("funding_stage")
        if isinstance(funding_stage, list):
            funding_stage = funding_stage[0] if funding_stage else None

        nice_to_have = {
            "revenue_range":  revenue_range,
            "target_cities":  cities,
            "tech_stack":     _normalize_tech_stack(tech_stack),
            "growth_stage":   growth_stage,
            "funding_stage":  funding_stage,
        }

        # ── exclude ──────────────────────────────────────────────────────────
        raw_exclude = data.get("exclude", [])
        if isinstance(raw_exclude, str): raw_exclude = [raw_exclude]
        if not isinstance(raw_exclude, list): raw_exclude = []

        exclude = {
            "industries": [],
            "keywords":   _dedupe_list(raw_exclude),
            "company_size": None,
        }

        # ── target_roles ─────────────────────────────────────────────────────
        roles = data.get("target_roles", [])
        if isinstance(roles, str): roles = [roles]
        if not isinstance(roles, list): roles = []

        return {
            "must_have":    must_have,
            "nice_to_have": nice_to_have,
            "exclude":      exclude,
            "target_roles": _dedupe_list(roles),
        }

    # ── Nested shape (new LLM output) → normalise ───────────────────────────

    @staticmethod
    def _clean_nested(data: dict) -> dict:
        """Sanitise a dict that already uses the nested schema."""

        # ── must_have ────────────────────────────────────────────────────────
        mh_raw = data.get("must_have", {})
        if not isinstance(mh_raw, dict): mh_raw = {}

        industry = mh_raw.get("industry", [])
        if isinstance(industry, str): industry = [industry]
        if not isinstance(industry, list): industry = []

        continents = mh_raw.get("target_continents", [])
        if not isinstance(continents, list): continents = []

        countries = mh_raw.get("target_countries", [])
        if not isinstance(countries, list): countries = []

        # Sanitize company size range
        company_size = ICPValidator._sanitize_range(mh_raw.get("company_size"))

        must_have = {
            "industry":          _dedupe_list(industry),
            "company_size":      company_size,
            "target_continents": _dedupe_list(continents),
            "target_countries":  _dedupe_list(countries),
        }

        # ── nice_to_have ─────────────────────────────────────────────────────
        nth_raw = data.get("nice_to_have", {})
        if not isinstance(nth_raw, dict): nth_raw = {}

        # Sanitize revenue range
        revenue_range = ICPValidator._sanitize_range(nth_raw.get("revenue_range"))

        cities_raw = nth_raw.get("target_cities", [])
        cities = [
            c for c in (cities_raw if isinstance(cities_raw, list) else [])
            if isinstance(c, dict) and c.get("city") and c.get("country")
        ]

        tech_stack = nth_raw.get("tech_stack", [])
        if not isinstance(tech_stack, list): tech_stack = []

        growth_stage = nth_raw.get("growth_stage")
        if isinstance(growth_stage, list):
            growth_stage = growth_stage[0] if growth_stage else None

        funding_stage = nth_raw.get("funding_stage")
        if isinstance(funding_stage, list):
            funding_stage = funding_stage[0] if funding_stage else None

        nice_to_have = {
            "revenue_range":  revenue_range,
            "target_cities":  cities,
            "tech_stack":     _normalize_tech_stack(tech_stack),
            "growth_stage":   growth_stage,
            "funding_stage":  funding_stage,
        }

        # ── exclude ──────────────────────────────────────────────────────────
        ex_raw = data.get("exclude", {})
        if isinstance(ex_raw, list):
            ex_raw = {"industries": [], "keywords": ex_raw, "company_size": None}
        if not isinstance(ex_raw, dict): ex_raw = {}

        ex_industries = ex_raw.get("industries", [])
        if isinstance(ex_industries, str): ex_industries = [ex_industries]
        if not isinstance(ex_industries, list): ex_industries = []

        ex_keywords = ex_raw.get("keywords", [])
        if isinstance(ex_keywords, str): ex_keywords = [ex_keywords]
        if not isinstance(ex_keywords, list): ex_keywords = []

        # Sanitize excluded company size range
        ex_size = None
        if ex_raw.get("company_size") is not None:
            ex_size = ICPValidator._sanitize_range(ex_raw.get("company_size"))

        exclude = {
            "industries":   _dedupe_list(ex_industries),
            "keywords":     _dedupe_list(ex_keywords),
            "company_size": ex_size,
        }

        # ── target_roles ─────────────────────────────────────────────────────
        roles = data.get("target_roles", [])
        if isinstance(roles, str): roles = [roles]
        if not isinstance(roles, list): roles = []

        return {
            "must_have":    must_have,
            "nice_to_have": nice_to_have,
            "exclude":      exclude,
            "target_roles": _dedupe_list(roles),
        }


# ── Module-level helpers ─────────────────────────────────────────────────────

def _dedupe_list(items: list) -> list:
    """Case-insensitive dedup preserving first occurrence order."""
    seen = set()
    result = []
    for item in items:
        key = item.lower() if isinstance(item, str) else str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _normalize_tech_stack(tech: list) -> list:
    """Strip 'required:' prefix from tech items and deduplicate."""
    cleaned = []
    for t in tech:
        if not isinstance(t, str):
            continue
        item = re.sub(r"^required\s*:\s*", "", t.strip(), flags=re.IGNORECASE)
        if item:
            cleaned.append(item)
    return _dedupe_list(cleaned)