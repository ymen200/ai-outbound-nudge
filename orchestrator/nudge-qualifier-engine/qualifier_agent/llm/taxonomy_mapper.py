"""
llm/taxonomy_mapper.py
───────────────────────
Maps messy/multilingual vendor industry strings (e.g. French Apollo labels
like "Assurance et Services Financiers") onto the user's ICP industry
taxonomy (e.g. "Insurance"), using an LLM instead of a hardcoded dictionary.

Why LLM instead of a static dict:
  - Vendor industry taxonomies are long-tail and inconsistent across sources
    (Apollo, Clearbit, ZoomInfo all use different label sets).
  - They appear in multiple languages.
  - The user's ICP industries are themselves free text, not a fixed enum,
    so a static lookup table would need constant manual maintenance.

This does ONE batched call for the whole company list per normalization run,
not one call per company, to keep cost/latency reasonable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

from dotenv import load_dotenv
from groq import Groq

from utils.resilience import retry_on_rate_limit

load_dotenv()
logger = logging.getLogger(__name__)

# Lazy initialization - create client only when first needed
_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        _client = Groq(api_key=api_key)
    return _client


@retry_on_rate_limit()
def _call_llm(prompt: str) -> dict:
    client = _get_client()
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



def map_industries_batch(
    raw_industries: List[str],
    icp_industries: List[str],
    accumulator=None,
) -> Dict[str, str]:
    """
    Given a list of raw vendor industry strings and the user's ICP industry
    list, return a dict mapping each raw string to either:
      - the matching ICP industry (if it's a reasonable semantic match), or
      - a normalized English industry label (if it doesn't match the ICP
        but still needs a clean label for display/logging).

    If icp_industries is empty (no must_have.industry constraint), this
    just normalizes raw labels to clean English without trying to match
    them to anything specific.

    Never raises — falls back to passing raw strings through unchanged
    on any LLM/parsing failure, so a taxonomy-mapping outage never blocks
    the pipeline.
    """
    unique_raw = sorted(set(r for r in raw_industries if r))
    if not unique_raw:
        return {}

    icp_list_str = json.dumps(icp_industries) if icp_industries else "[] (no restriction)"

    prompt = f"""
You are an industry taxonomy normalizer for a B2B outbound platform.

You are given:
1. A list of raw industry labels pulled from a data vendor. These may be in
   any language and may be vendor-specific phrasing.
2. The user's ICP target industries (in English, normalized).

For EACH raw label, return the SINGLE closest matching ICP industry from
the list, if and only if it is a genuine semantic match (translate first,
then judge meaning — not string similarity). If no ICP industry matches
well, return your best normalized English industry label instead (a short,
clean, standard industry name, NOT the literal translation).

Return ONLY a JSON object mapping each raw label (exact string, used as the
key) to its resolved label (string value). No explanation, no markdown.

ICP TARGET INDUSTRIES:
{icp_list_str}

RAW VENDOR LABELS TO MAP:
{json.dumps(unique_raw)}

EXAMPLE:
ICP TARGET INDUSTRIES: ["Insurance", "Fintech"]
RAW VENDOR LABELS: ["Assurance et Services Financiers", "Vente au détail"]
CORRECT RESPONSE:
{{
  "Assurance et Services Financiers": "Insurance",
  "Vente au détail": "Retail"
}}

Return ONLY the JSON object.
"""

    try:
        mapping, usage = _call_llm(prompt)

        if accumulator is not None:
            try:
                accumulator.record(
                    tokens_in  = usage["tokens_in"],
                    tokens_out = usage["tokens_out"],
                    node_name  = "normalize_company_data",
                )
            except Exception as exc:
                logger.warning("taxonomy_mapper: failed to record usage — %s", exc)

        if not isinstance(mapping, dict):
            raise ValueError("LLM did not return a dict")
        # Guard against the LLM dropping or renaming keys unexpectedly —
        # fall back to identity mapping for anything missing.
        return {raw: mapping.get(raw, raw) for raw in unique_raw}
    except Exception as exc:
        logger.warning("taxonomy_mapping_failed error=%s", exc)
        return {raw: raw for raw in unique_raw}