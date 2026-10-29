"""
Strategic Qualifier – ICP Schema
─────────────────────────────────
Three-layer architecture that mirrors the qualifier's decision logic:

  MustHaveTraits   → hard filters applied before any scoring
  NiceToHaveTraits → soft signals that lift / lower ranking scores
  ExcludeCriteria  → negative constraints that disqualify immediately

The top-level ICPAttributes model nests all three layers plus the
target_roles list, which drives persona ranking downstream.

Every field carries a Field(description=...) so that a structured-output
LLM knows exactly what to extract into which category.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


# ── Primitive helpers ────────────────────────────────────────────────────────

class Range(BaseModel):
    """Numeric range with optional min and/or max boundary."""

    min: Optional[float] = Field(
        default=None,
        description="Lower bound (inclusive). Null means no lower limit.",
    )
    max: Optional[float] = Field(
        default=None,
        description="Upper bound (inclusive). Null means no upper limit.",
    )


class CityContext(BaseModel):
    """A single target city with its country and optional continent."""

    city: str = Field(
        description="City name exactly as it would appear on a map (e.g. 'Paris')."
    )
    country: str = Field(
        description="Full country name the city belongs to (e.g. 'France')."
    )
    continent: Optional[str] = Field(
        default=None,
        description="Continent for the city (e.g. 'Europe'). Infer if not explicit.",
    )


# ── Layer 1 – Must-Have Traits (hard filters) ────────────────────────────────

class MustHaveTraits(BaseModel):
    """
    Hard constraints. A company that fails ANY of these is immediately
    disqualified — no scoring is performed.

    Fields:
      - industry        : required sectors / verticals
      - company_size    : headcount range (employees)
      - target_continents : allowed continents
      - target_countries  : allowed countries (subset of continents above)
    """

    industry: List[str] = Field(
        default_factory=list,
        description=(
            "Primary industry or vertical the target company must operate in. "
            "Examples: ['SaaS', 'Fintech', 'Logistics']. "
            "Extract every sector explicitly mentioned. Empty list = no restriction."
        ),
    )
    company_size: Range = Field(
        default_factory=Range,
        description=(
            "Headcount range (number of employees). "
            "Set min and/or max from expressions like '50–500 employees'. "
            "Leave null when not specified."
        ),
    )
    target_continents: List[str] = Field(
        default_factory=list,
        description=(
            "Continents where target companies must be located. "
            "Examples: ['Europe', 'North America']. "
            "Empty list = no continent restriction."
        ),
    )
    target_countries: List[str] = Field(
        default_factory=list,
        description=(
            "Countries where target companies must be headquartered. "
            "Use full country names: ['France', 'Germany', 'United Kingdom']. "
            "Empty list = no country restriction."
        ),
    )


# ── Layer 2 – Nice-to-Have Traits (soft ranking signals) ────────────────────

class NiceToHaveTraits(BaseModel):
    """
    Soft signals. Companies that match more of these are ranked higher,
    but failing them does NOT disqualify a company.

    Fields:
      - revenue_range  : annual revenue / ARR band
      - target_cities  : preferred cities with distance context
      - tech_stack     : technologies the company uses or should use
      - growth_stage   : stage of company maturity (e.g. 'Series B')
      - funding_stage  : latest funding round type
    """

    revenue_range: Range = Field(
        default_factory=Range,
        description=(
            "Annual revenue or ARR range in the ICP's currency. "
            "Example: min=5_000_000, max=80_000_000 for '€5M–€80M ARR'. "
            "Leave null when not mentioned."
        ),
    )
    target_cities: List[CityContext] = Field(
        default_factory=list,
        description=(
            "Preferred target cities. Only populate when the ICP specifies cities "
            "or proximity constraints (e.g. 'within 30km of Paris'). "
            "Each entry needs city + country at minimum."
        ),
    )
    tech_stack: List[str] = Field(
        default_factory=list,
        description=(
            "Technologies, platforms, or tools the target company is expected to use. "
            "Examples: ['AWS', 'Python', 'Snowflake']."
        ),
    )
    growth_stage: Optional[str] = Field(
        default=None,
        description=(
            "Company maturity or growth phase. "
            "Examples: 'Series A', 'Series B', 'growth stage', 'enterprise'. "
            "Extract the most specific term mentioned."
        ),
    )
    funding_stage: Optional[str] = Field(
        default=None,
        description=(
            "Most recent or target funding round. "
            "Examples: 'Seed', 'Series A', 'Series B', 'bootstrapped', 'post-IPO'. "
            "Use null when not specified."
        ),
    )


# ── Layer 3 – Exclude Criteria (negative constraints) ───────────────────────

class ExcludeCriteria(BaseModel):
    """
    Explicit disqualification rules. Any company matching one of these
    is immediately rejected, regardless of how well it fits the ICP.

    Fields:
      - industries   : industry verticals to reject
      - keywords     : free-form disqualifying terms (competitor names,
                       business models, descriptors)
      - company_size : headcount bands to exclude (e.g. exclude < 10 employees)
    """

    industries: List[str] = Field(
        default_factory=list,
        description=(
            "Industry verticals or sectors to exclude outright. "
            "Examples: ['Gambling', 'Tobacco', 'Government']. "
            "Only populate when explicitly mentioned."
        ),
    )
    keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Free-form terms that disqualify a company when found in its profile. "
            "Includes competitor names, disallowed business models, or descriptors "
            "like 'non-profit', 'agency', 'freelancer'. "
            "Examples: ['agency', 'non-profit', 'AcmeCorp (competitor)']."
        ),
    )
    company_size: Optional[Range] = Field(
        default=None,
        description=(
            "Headcount range to EXCLUDE. For example, exclude companies with "
            "fewer than 10 employees: Range(min=0, max=9). "
            "Leave null when no size exclusion is specified."
        ),
    )


# ── Top-level ICP model ──────────────────────────────────────────────────────

class ICPAttributes(BaseModel):
    """
    Complete ICP representation for the Strategic Qualifier.

    The three nested layers map directly to the qualifier's decision pipeline:
      1. must_have   → hard filter (disqualify or pass)
      2. nice_to_have → soft ranking (score boosters)
      3. exclude     → negative filter (immediate rejection)

    target_roles drives the persona ranker and is kept at the top level
    because it is neither a company filter nor an exclusion rule.
    """

    must_have: MustHaveTraits = Field(
        default_factory=MustHaveTraits,
        description=(
            "Hard constraints. Every field here is a binary pass/fail gate. "
            "Populate from explicit requirements in the ICP text."
        ),
    )
    nice_to_have: NiceToHaveTraits = Field(
        default_factory=NiceToHaveTraits,
        description=(
            "Soft ranking signals. Matching companies rank higher; "
            "non-matching companies are not disqualified. "
            "Populate from preferences, ranges, and technology mentions."
        ),
    )
    exclude: ExcludeCriteria = Field(
        default_factory=ExcludeCriteria,
        description=(
            "Negative constraints. Any company matching these is rejected "
            "before scoring begins. Populate from explicit 'exclude / avoid / not' "
            "language in the ICP text."
        ),
    )
    target_roles: List[str] = Field(
        default_factory=list,
        description=(
            "Job titles or roles to target for persona ranking. "
            "Extract every decision-maker title mentioned. "
            "Examples: ['VP of Sales', 'Head of Partnerships', 'CTO']. "
            "Empty list = rank all available personas by seniority."
        ),
    )

    # ── Backwards-compatibility properties ───────────────────────────────────
    # These let existing code that reads icp.industry, icp.company_size, etc.
    # continue working without modification during the migration period.

    @property
    def industry(self) -> List[str]:
        return self.must_have.industry

    @property
    def company_size(self) -> Range:
        return self.must_have.company_size

    @property
    def target_continents(self) -> List[str]:
        return self.must_have.target_continents

    @property
    def target_countries(self) -> List[str]:
        return self.must_have.target_countries

    @property
    def target_cities(self) -> List[CityContext]:
        return self.nice_to_have.target_cities

    @property
    def revenue_range(self) -> Range:
        return self.nice_to_have.revenue_range

    @property
    def tech_stack(self) -> List[str]:
        """Direct access to nice_to_have.tech_stack."""
        return self.nice_to_have.tech_stack

    @property
    def dynamic_attributes(self) -> "NiceToHaveTraits":
        """Legacy alias used by ranker.py to access tech_stack."""
        return self.nice_to_have
