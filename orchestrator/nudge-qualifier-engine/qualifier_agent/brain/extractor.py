    
import json
import logging
import os
import re

from dotenv import load_dotenv
from groq import Groq

from brain.schemas import ICPAttributes
from brain.validator import ICPValidator
from utils.cache import RedisCache
from utils.resilience import retry_on_rate_limit

load_dotenv()
logger = logging.getLogger(__name__)


class ICPExtractor:
    def __init__(self):
        # Lazy initialization - create client only when first needed
        self._client = None
        self.cache  = RedisCache()

    def _get_client(self):
        if self._client is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("GROQ_API_KEY environment variable not set")
            self._client = Groq(api_key=api_key)
        return self._client

    @retry_on_rate_limit()
    def _call_llm(self, prompt: str) -> dict:
        client = self._get_client()
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        usage = {
            "tokens_in":  res.usage.prompt_tokens     if res.usage else 0,
            "tokens_out": res.usage.completion_tokens  if res.usage else 0,
        }
        return json.loads(res.choices[0].message.content), usage

    def extract(self, text: str,accumulator=None) -> ICPAttributes:
        if not text or not text.strip():
            raise ValueError("ICP extraction received empty input text.")

        # ── Cache check (v4 cache key — prompt schema changed) ───────────────
        cache_key = self.cache.key("icp_v4_clean", text) 
        cached    = self.cache.get(cache_key)
        if cached:
            logger.info("icp_extraction_cache=hit")
            return ICPAttributes(**cached)

        # ── LLM extraction prompt setup ──────────────────────────────────────
        prompt = f"""
You are the Strategic Qualifier extraction engine for an AI outbound platform.
Parse the ICP description and return a JSON object with four keys:
must_have, nice_to_have, exclude, target_roles.

Return ONLY valid JSON. No explanation, no markdown tags.

OUTPUT SCHEMA:
{{
  "must_have": {{
    "industry":          ["string"],
    "company_size":      {{"min": number_or_null, "max": number_or_null}},
    "target_continents": ["string"],
    "target_countries":  ["string"]
  }},
  "nice_to_have": {{
    "revenue_range":  {{"min": number_or_null, "max": number_or_null}},
    "target_cities":  [{{"city": "string", "country": "string", "continent": "string_or_null"}}],
    "tech_stack":     ["string"],
    "growth_stage":   "string_or_null",
    "funding_stage":  "string_or_null"
  }},
  "exclude": {{
    "industries":   ["string"],
    "keywords":     ["string"],
    "company_size": {{"min": number_or_null, "max": number_or_null}} or null
  }},
  "target_roles": ["string"]
}}

LAYER RULES:

MUST_HAVE — hard filters, disqualify if unmet:
  industry          → sectors the company MUST be in. E.g. ["SaaS", "Fintech"].
  company_size      → headcount range. "50–500 employees" → {{"min": 50, "max": 500}}.
  target_continents → ONLY when the user explicitly names a continent
                      (e.g. "Africa", "Europe", "Asia"). Do NOT infer a
                      continent from a country. If they said "Morocco" only,
                      leave target_continents as []. E.g. ["Europe"].
  target_countries  → countries to include. E.g. ["France", "Germany", "United Kingdom"].

NICE_TO_HAVE — soft signals, higher match = higher rank:
  revenue_range  → ARR/revenue as plain numbers. "€5M–€80M" → {{"min": 5000000, "max": 80000000}}.
  target_cities  → only when specific cities or proximity are mentioned.
                   Each entry: city + country required, continent inferred.
                   CRITICAL RULE: You MUST extract every explicitly named city 
                   (e.g., "Tunis", "Paris") into this array, even if its parent 
                   country is already captured in the must_have.target_countries 
                   list. Do not deduplicate cities out of this field.
  growth_stage   → maturity. E.g. "Series B", "growth stage".
  funding_stage  → latest round. E.g. "Seed", "Series A".
  tech_stack    → Always extract mentioned technologies into this list, even if
                   the user frames them as mandatory requirements.
                   E.g. ["AWS", "Python", "Kubernetes"].

EXCLUDE — negative constraints, immediate rejection if matched:
  industries   → sectors to reject outright. E.g. ["Gambling", "Government"].
  keywords     → free-form disqualifiers. E.g. ["non-profit", "agency", "competitor:Acme"].
  company_size → headcount band to exclude. E.g., if excluding micro-businesses under 10 people → {{"min": 0, "max": 9}}.

TARGET_ROLES — drives persona ranker, not a company filter:
  Every decision-maker title mentioned. E.g. ["VP of Sales", "Head of Partnerships"].
  Return [] if no roles are specified.

CRITICAL RELATIONSHIP MAPPING RULES:
  - If target cities are named in the text (e.g., "Paris", "Berlin"), you MUST identify their parent countries and append them directly to the `must_have.target_countries` array.
  - The downstream data sourcer relies completely on `must_have.target_countries` to query databases. If a city or country is implied or mentioned, that country MUST be listed in `must_have.target_countries`.
  - Do NOT put full country strings inside the `target_cities` array list and do not put city names in the `target_countries` list.
  - GEO PRIORITY: country beats continent. Never fill target_continents just because you know which continent a country belongs to. Only set target_continents when the user literally named a continent.
  - If the user names BOTH a continent and a country (e.g. "Morocco in Africa"), keep the country in target_countries and you MAY keep the continent — but country is the search driver.
  - Numbers must be plain numbers (no symbols like €, $, or commas).
  - Return ONLY the JSON object.
================================================================================
🎯 EXAMPLES OF CORRECT EXTRACTION (FEW-SHOT REGIME)
================================================================================

EXAMPLE 1 INPUT TEXT:
"Looking for software companies in London and Milan or local teams across Italy. Size 20-200. Target roles: VP of Engineering."

EXAMPLE 1 CORRECT JSON RESPONSE:
{{
  "must_have": {{
    "industry": ["Software"],
    "company_size": {{"min": 20, "max": 200}},
    "target_continents": [],
    "target_countries": ["United Kingdom", "Italy"]
  }},
  "nice_to_have": {{
    "revenue_range": {{"min": null, "max": null}},
    "target_cities": [
      {{"city": "London", "country": "United Kingdom", "continent": "Europe"}},
      {{"city": "Milan", "country": "Italy", "continent": "Europe"}}
    ],
    "tech_stack": [],
    "growth_stage": null,
    "funding_stage": null
  }},
  "exclude": {{
    "industries": [],
    "keywords": [],
    "company_size": null
  }},
  "target_roles": ["VP of Engineering"]
}}

EXAMPLE 2 INPUT TEXT:
"We are targeting Software companies in Morocco. Size 1-200000. Contact sales persons."

EXAMPLE 2 CORRECT JSON RESPONSE:
{{
  "must_have": {{
    "industry": ["Software"],
    "company_size": {{"min": 1, "max": 200000}},
    "target_continents": [],
    "target_countries": ["Morocco"]
  }},
  "nice_to_have": {{
    "revenue_range": {{"min": null, "max": null}},
    "target_cities": [],
    "tech_stack": [],
    "growth_stage": null,
    "funding_stage": null
  }},
  "exclude": {{
    "industries": [],
    "keywords": [],
    "company_size": null
  }},
  "target_roles": ["sales persons"]
}}

EXAMPLE 3 INPUT TEXT:
"Software companies across Africa, any country. Size 50-500."

EXAMPLE 3 CORRECT JSON RESPONSE:
{{
  "must_have": {{
    "industry": ["Software"],
    "company_size": {{"min": 50, "max": 500}},
    "target_continents": ["Africa"],
    "target_countries": []
  }},
  "nice_to_have": {{
    "revenue_range": {{"min": null, "max": null}},
    "target_cities": [],
    "tech_stack": [],
    "growth_stage": null,
    "funding_stage": null
  }},
  "exclude": {{
    "industries": [],
    "keywords": [],
    "company_size": null
  }},
  "target_roles": []
}}

================================================================================
🚨 STRICT RUNTIME EXTRACTION RULES
================================================================================
1. CRITICAL CITIES DEDUPLICATION GUARD: If a specific city name is mentioned in the text (e.g. "Tunis", "Paris", "London"), you MUST explicitly write it into the `nice_to_have.target_cities` array. Never drop or omit a city item because its parent country is already inside `must_have.target_countries`.
2. Every city entry must have both its absolute 'city' name and its parent 'country' name clearly assigned.
3. Clean all currency symbols (€, $) and commas out of any parsed numerical metrics.
4. NEVER infer target_continents from a country name. "Morocco" → countries=["Morocco"], continents=[]. "Africa" → continents=["Africa"], countries=[].

TEXT TO EVALUATE:
{text}
"""

        raw_data, usage = self._call_llm(prompt)

        # Record token usage if an accumulator was provided
        if accumulator is not None:
            try:
                accumulator.record(
                    tokens_in  = usage["tokens_in"],
                    tokens_out = usage["tokens_out"],
                    node_name  = "extract_icp",
                )
            except Exception as exc:
                logger.warning("ICPExtractor: failed to record usage — %s", exc)

        # ── Validate, normalize and cache data ───────────────────────────────
        cleaned   = ICPValidator.clean(raw_data)
        validated = ICPAttributes(**cleaned)
        self.cache.set(cache_key, validated.model_dump(), ttl=30 * 24 * 3600)
        return validated