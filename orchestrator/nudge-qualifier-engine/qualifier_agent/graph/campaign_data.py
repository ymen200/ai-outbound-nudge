"""
campaign_data.py
──────────────────
Writes structured campaign data (inputs, companies, personas, blacklist,
weights snapshot, token usage) into your hosted Postgres database.

The existing `campaign_status.py` module owns the `campaigns` lifecycle table.
This module owns the additional "campaign_*" data tables.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class CampaignDataManager:
    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url or os.environ["DATABASE_URL"]

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._db_url, row_factory=dict_row)

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _coerce_model_dump(obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                return {}
        if isinstance(obj, dict):
            return obj
        return {}

    @staticmethod
    def _safe_list(v: Any) -> List[Any]:
        if isinstance(v, list):
            return v
        return []

    def upsert_campaign_inputs(
        self,
        *,
        campaign_id: str,
        raw_icp_text: str,
        user_offering: str,
        extracted_icp: Any,
    ) -> None:
        """
        Store:
          - raw ICP text (full string)
          - user offering
          - parsed ICP JSONB snapshot
          - hybrid: also stores key parsed fields in separate columns
        """
        parsed = self._coerce_model_dump(extracted_icp)

        must_have = parsed.get("must_have") or {}
        nice_to_have = parsed.get("nice_to_have") or {}

        company_size = must_have.get("company_size") or {}
        revenue_range = nice_to_have.get("revenue_range") or {}

        industries = self._safe_list(must_have.get("industry"))
        target_countries = self._safe_list(must_have.get("target_countries"))
        target_continents = self._safe_list(must_have.get("target_continents"))
        target_roles = self._safe_list(parsed.get("target_roles"))

        tech_stack = self._safe_list(nice_to_have.get("tech_stack"))
        target_cities = self._safe_list(nice_to_have.get("target_cities"))

        def _to_float_or_none(v: Any) -> Optional[float]:
            if v is None:
                return None
            try:
                return float(v)
            except Exception:
                return None

        parsed_icp_json = parsed or {}
        now = self._utcnow()
        row_id = str(uuid.uuid4())

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO campaign_inputs (
                        id,
                        campaign_id,
                        raw_icp_text,
                        user_offering,
                        parsed_icp_json,
                        industries_json,
                        target_countries_json,
                        target_continents_json,
                        target_roles_json,
                        company_size_min,
                        company_size_max,
                        revenue_min,
                        revenue_max,
                        tech_stack_json,
                        growth_stage,
                        funding_stage,
                        target_cities_json,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s, %s,
                        %s,
                        %s, %s
                    )
                    ON CONFLICT (campaign_id) DO UPDATE SET
                        raw_icp_text = EXCLUDED.raw_icp_text,
                        user_offering = EXCLUDED.user_offering,
                        parsed_icp_json = EXCLUDED.parsed_icp_json,
                        industries_json = EXCLUDED.industries_json,
                        target_countries_json = EXCLUDED.target_countries_json,
                        target_continents_json = EXCLUDED.target_continents_json,
                        target_roles_json = EXCLUDED.target_roles_json,
                        company_size_min = EXCLUDED.company_size_min,
                        company_size_max = EXCLUDED.company_size_max,
                        revenue_min = EXCLUDED.revenue_min,
                        revenue_max = EXCLUDED.revenue_max,
                        tech_stack_json = EXCLUDED.tech_stack_json,
                        growth_stage = EXCLUDED.growth_stage,
                        funding_stage = EXCLUDED.funding_stage,
                        target_cities_json = EXCLUDED.target_cities_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        row_id,
                        campaign_id,
                        raw_icp_text,
                        user_offering,
                        json.dumps(parsed_icp_json, default=str),
                        json.dumps(industries, default=str),
                        json.dumps(target_countries, default=str),
                        json.dumps(target_continents, default=str),
                        json.dumps(target_roles, default=str),
                        _to_float_or_none(company_size.get("min")),
                        _to_float_or_none(company_size.get("max")),
                        _to_float_or_none(revenue_range.get("min")),
                        _to_float_or_none(revenue_range.get("max")),
                        json.dumps(tech_stack, default=str),
                        nice_to_have.get("growth_stage"),
                        nice_to_have.get("funding_stage"),
                        json.dumps(target_cities, default=str),
                        now,
                        now,
                    ),
                )
            conn.commit()

    def upsert_campaign_weights(self, *, campaign_id: str, weights: Dict[str, Any]) -> None:
        now = self._utcnow()
        row_id = str(uuid.uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO campaign_weight_snapshots (
                        id,
                        campaign_id,
                        weights_json,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (campaign_id) DO UPDATE SET
                        weights_json = EXCLUDED.weights_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        row_id,
                        campaign_id,
                        json.dumps(weights or {}, default=str),
                        now,
                        now,
                    ),
                )
            conn.commit()

    def upsert_blacklist_entries(
        self, *, campaign_id: str, blacklist: Optional[Dict[str, List[str]]]
    ) -> None:
        if not blacklist:
            blacklist = {"companies": [], "personas": []}

        companies = list(blacklist.get("companies") or [])
        personas = list(blacklist.get("personas") or [])

        now = self._utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                for match_value in companies:
                    match_value = str(match_value).strip()
                    if not match_value:
                        continue
                    cur.execute(
                        """
                        INSERT INTO blacklist_entries (
                            id, campaign_id, entry_type, match_value, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (campaign_id, entry_type, match_value) DO NOTHING
                        """,
                        (str(uuid.uuid4()), campaign_id, "company", match_value, now),
                    )

                for match_value in personas:
                    match_value = str(match_value).strip()
                    if not match_value:
                        continue
                    cur.execute(
                        """
                        INSERT INTO blacklist_entries (
                            id, campaign_id, entry_type, match_value, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (campaign_id, entry_type, match_value) DO NOTHING
                        """,
                        (str(uuid.uuid4()), campaign_id, "persona", match_value, now),
                    )
            conn.commit()

    def insert_campaign_companies(
        self, *, campaign_id: str, companies: List[Dict[str, Any]]
    ) -> None:
        now = self._utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                for co in companies or []:
                    apollo_id = co.get("apollo_id") or co.get("id") or co.get("domain")
                    if not apollo_id:
                        continue
                    name = str(co.get("name") or "Unknown")
                    cur.execute(
                        """
                        INSERT INTO campaign_companies (
                            id, campaign_id, apollo_company_id, company_name, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (campaign_id, apollo_company_id) DO UPDATE SET
                            company_name = EXCLUDED.company_name
                        """,
                        (
                            str(uuid.uuid4()),
                            campaign_id,
                            str(apollo_id),
                            name,
                            now,
                        ),
                    )
            conn.commit()

    def insert_campaign_personas(
        self,
        *,
        campaign_id: str,
        sourced_personas_by_company: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        now = self._utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                for apollo_company_id, personas in (sourced_personas_by_company or {}).items():
                    for p in personas or []:
                        apollo_persona_id = p.get("apollo_id") or p.get("id") or p.get("persona_id")
                        if not apollo_persona_id:
                            continue
                        persona_name = str(p.get("name") or "Unknown")
                        linkedin_url = p.get("linkedin_url") or p.get("linkedin") or ""
                        linkedin_url = str(linkedin_url) if linkedin_url else ""
                        cur.execute(
                            """
                            INSERT INTO campaign_personas (
                                id,
                                campaign_id,
                                apollo_persona_id,
                                apollo_company_id,
                                persona_name,
                                linkedin_url,
                                created_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (campaign_id, apollo_persona_id) DO UPDATE SET
                                persona_name = EXCLUDED.persona_name,
                                apollo_company_id = EXCLUDED.apollo_company_id,
                                linkedin_url = EXCLUDED.linkedin_url
                            """,
                            (
                                str(uuid.uuid4()),
                                campaign_id,
                                str(apollo_persona_id),
                                str(apollo_company_id) if apollo_company_id else None,
                                persona_name,
                                linkedin_url,
                                now,
                            ),
                        )
            conn.commit()

    @staticmethod
    def _extract_total_tokens(usage: Dict[str, Any]) -> Tuple[int, int, int, int]:
        """
        Returns (total_tokens, tokens_in, tokens_out, total_llm_calls).
        """
        combined = usage.get("combined") or {}
        total_tokens = int(combined.get("total_tokens") or 0)
        tokens_in = int(combined.get("total_tokens_in") or 0)
        tokens_out = int(combined.get("total_tokens_out") or 0)
        total_llm_calls = int(combined.get("total_llm_calls") or 0)

        if total_tokens == 0 and usage.get("per_node"):
            per_node = usage.get("per_node") or []
            total_tokens = sum(int(n.get("total_tokens") or 0) for n in per_node if isinstance(n, dict))
            tokens_in = sum(int(n.get("tokens_in") or 0) for n in per_node if isinstance(n, dict))
            tokens_out = sum(int(n.get("tokens_out") or 0) for n in per_node if isinstance(n, dict))
            total_llm_calls = sum(int(n.get("llm_calls") or 0) for n in per_node if isinstance(n, dict))

        return total_tokens, tokens_in, tokens_out, total_llm_calls

    def insert_token_usage(
        self, *, campaign_id: str, tool_name: str, usage: Dict[str, Any]
    ) -> None:
        now = self._utcnow()
        usage = usage or {}
        total_tokens, tokens_in, tokens_out, total_llm_calls = self._extract_total_tokens(usage)
        row_id = str(uuid.uuid4())

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO token_usage (
                        id,
                        campaign_id,
                        tool_name,
                        usage_json,
                        total_tokens,
                        tokens_in,
                        tokens_out,
                        total_llm_calls,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row_id,
                        campaign_id,
                        tool_name,
                        json.dumps(usage, default=str),
                        total_tokens,
                        tokens_in,
                        tokens_out,
                        total_llm_calls,
                        now,
                    ),
                )
            conn.commit()

