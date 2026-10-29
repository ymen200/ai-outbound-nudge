from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qualifier_mcp_path: str = "../nudge-qualifier-engine/qualifier_agent/qualifier_mcp/run.py"
    sourcer_mcp_path: str = "../inject_collect_project/mcp_server.py"
    qualifier_python: Optional[str] = None
    sourcer_python: Optional[str] = None
    # Max seconds per MCP tool call (persona+signals / intent often exceed 120s).
    qualifier_timeout: float = 180.0
    sourcer_timeout: float = 300.0
    qualifier_max_retries: int = 0
    sourcer_max_retries: int = 1
    mcp_retry_backoff_base: float = 2.0

    database_path: str = "./data/orchestrator.db"
    database_backend: str = "postgres"
    database_url: Optional[str] = None

    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    # DB host as seen from the SSH jump box (usually 127.0.0.1 on the server).
    postgres_remote_host: str = ""

    ssh_tunnel_enabled: bool = False
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""

    def resolve_path(self, path_str: str) -> Path:
        """Resolve *path_str* relative to the orchestrator directory (ROOT_DIR).

        Absolute paths are returned unchanged so that users who explicitly set
        an absolute path in their ``.env`` are not affected.
        """
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (ROOT_DIR / p).resolve()

    def resolved_database_url(self) -> str:
        from app.store.connection import build_database_url

        return build_database_url()

    # How many companies the sourcer fetches before firmographic scoring.
    company_limit: int = 10
    company_limit_per_element: int = 1
    # After intent rescore, how many top companies proceed to persona discovery.
    # Defaults to company_limit when unset (see pipeline).
    companies_for_persona_fetch: Optional[int] = None
    persona_limit: int = 6
    persona_limit_per_element: int = 3
    # Weights for picking the single lead to enrich (must sum to ~1.0).
    lead_company_score_weight: float = 0.4
    lead_persona_score_weight: float = 0.6

    # Passed to qualifier as configurable_weights.max_km_radius (geo proximity).
    max_km_radius: float = 50.0

    # ── Blacklist (passed to qualifier as state['blacklist']) ─────────────
    # Companies: names or regex patterns (case-insensitive match in qualifier).
    # Personas: LinkedIn profile URLs (normalized match in qualifier).
    blacklist_companies: List[str] = Field(default_factory=list)
    blacklist_personas: List[str] = Field(default_factory=list)

    # ── Qualifier firmographic / composite weights (brain/config.py) ──────
    industry_weight: float = 0.40
    size_weight: float = 0.30
    revenue_weight: float = 0.15
    tech_stack_weight: float = 0.15
    firmographic_weight: float = 0.60
    intent_weight: float = 0.40

    # ── Qualifier persona weights (brain/config.py PersonaWeights) ────────
    primary_role_match: float = 40.0
    startup_fallback_match: float = 35.0
    partial_title_match: float = 20.0
    engagement_weight: float = 40.0
    verified_email_bonus: float = 20.0
    risky_email_bonus: float = 5.0
    fit_weight: float = 0.70
    reachability_weight: float = 0.20
    timing_weight: float = 0.10
    functional_weight: float = 0.60
    authority_weight: float = 0.40

    orchestrator_mock: bool = False

    # Default ICP brief + offering (used by smoke scripts; API falls back if omitted)
    icp_description_text: str = (
        "We sell NudgeShield cyber-risk analytics to mid-market insurance and "
        "financial services companies in the United States.\n"
        "Must have:\n"
        "- Industry: Insurance, Financial Services, Banking, Fintech\n"
        "- Company size: 200 to 5000 employees\n"
        "- Located in: United States\n"
    )
    user_offering: str = (
        "NudgeShield is a cyber-risk and underwriting intelligence platform that helps "
        "insurers and financial institutions detect emerging threats, score account risk, "
        "and prioritize high-intent commercial opportunities."
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8100
    log_level: str = "INFO"

    # ── Outreach Orchestrator integration ────────────────────────────────
    # Path to the Outreach Orchestrator stdio MCP server script
    outreach_mcp_path: str = "../../Outreach-Project/outreach orchestrator/run_mcp.py"
    outreach_python: Optional[str] = None
    # Max seconds to wait for a single Outreach MCP tool call (matches the
    # old REST OUTREACH_TIMEOUT default). Prevents a hung Gemini call from
    # blocking the global orchestrator's background task indefinitely.
    outreach_timeout: float = 120.0
    # How many times to retry a failed MCP tool call before giving up.
    outreach_max_retries: int = 2
    # Base seconds for exponential backoff between retries (2^n * base).
    outreach_retry_backoff_base: float = 2.0

    outreach_default_sender_company: str = "My Company"
    outreach_default_sender_elevator_pitch: str = ""
    outreach_default_offer_name: str = "Default Offer"
    outreach_default_solution_summary: str = ""
    outreach_default_cta: str = ""
    outreach_default_approval_mode: str = "per_sequence"
    outreach_default_use_native_language: bool = False
    outreach_default_message_language: Optional[str] = None
    outreach_default_has_inmail_credits: bool = False
    outreach_default_debug_mode: bool = True
    outreach_auto_start: bool = False

    # ── Outreach Orchestrator REST URL (for workflow signal endpoints) ───
    # Used by OutreachClient._raw_request and the custom dispatch endpoint.
    # Change this if the Outreach Orchestrator runs on a different port/host.
    outreach_orch_url: str = "http://localhost:8002"

    # ── Message Generator (for Unipile webhook registration) ───────────
    message_generator_url: str = "http://localhost:8000"

    def default_blacklist(self) -> Dict[str, List[str]]:
        return {
            "companies": list(self.blacklist_companies),
            "personas": list(self.blacklist_personas),
        }

    def default_configurable_weights(self) -> Dict[str, float]:
        """Flattened weights passed to the qualifier as configurable_weights."""
        return {
            "max_km_radius": self.max_km_radius,
            # Firmographic feature + composite
            "industry_weight": self.industry_weight,
            "size_weight": self.size_weight,
            "revenue_weight": self.revenue_weight,
            "tech_stack_weight": self.tech_stack_weight,
            "firmographic_weight": self.firmographic_weight,
            "intent_weight": self.intent_weight,
            # PersonaWeights
            "primary_role_match": self.primary_role_match,
            "startup_fallback_match": self.startup_fallback_match,
            "partial_title_match": self.partial_title_match,
            "engagement_weight": self.engagement_weight,
            "verified_email_bonus": self.verified_email_bonus,
            "risky_email_bonus": self.risky_email_bonus,
            "fit_weight": self.fit_weight,
            "reachability_weight": self.reachability_weight,
            "timing_weight": self.timing_weight,
            "functional_weight": self.functional_weight,
            "authority_weight": self.authority_weight,
        }


settings = Settings()
