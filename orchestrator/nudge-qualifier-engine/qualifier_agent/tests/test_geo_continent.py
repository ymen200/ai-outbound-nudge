"""Unit tests for continent-only geospatial filtering."""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from brain.schemas import ICPAttributes, MustHaveTraits, NiceToHaveTraits
from geo.continents import continent_for_country, resolve_company_continent
from geo.location_agent import LocationAgent


def test_continent_for_country_europe():
    assert continent_for_country("France") == "europe"
    assert continent_for_country("Poland") == "europe"
    assert continent_for_country("United States") == "north america"
    assert continent_for_country("Unknownland") is None


def test_normalize_country_aliases():
    from geo.continents import normalize_country, countries_equivalent

    assert normalize_country("Maroc") == "morocco"
    assert normalize_country("Morocco") == "morocco"
    assert countries_equivalent("Maroc", "Morocco")
    assert continent_for_country("Maroc") == "africa"
    assert continent_for_country("Tunisie") == "africa"
    assert continent_for_country("Égypte") == "africa"


def test_resolve_prefers_explicit_continent():
    assert resolve_company_continent({"continent": "Asia", "country": "France"}) == "asia"
    assert resolve_company_continent({"country": "Poland"}) == "europe"


def test_continent_only_keeps_european_companies():
    """ICP Europe + empty countries must keep France/Poland (no continent field)."""
    icp = ICPAttributes(
        must_have=MustHaveTraits(
            industry=["Finance"],
            target_continents=["Europe"],
            target_countries=[],
        ),
        nice_to_have=NiceToHaveTraits(),
        target_roles=[],
    )
    companies = [
        {"name": "Emil Frey France", "country": "France", "apollo_id": "ef1"},
        {"name": "Asseco", "country": "Poland", "apollo_id": "as1"},
        {"name": "US Corp", "country": "United States", "apollo_id": "us1"},
    ]
    agent = LocationAgent()
    # Avoid city-proximity path
    surviving = agent.filter_companies(icp, companies, max_km=0.0, debug=False)
    names = {c["name"] for c in surviving}
    assert "Emil Frey France" in names
    assert "Asseco" in names
    assert "US Corp" not in names
    # Continent should be stamped on survivors
    for c in surviving:
        assert c.get("continent", "").lower() == "europe"


def test_country_filter_still_works_when_countries_set():
    icp = ICPAttributes(
        must_have=MustHaveTraits(
            industry=[],
            target_continents=["Europe"],
            target_countries=["France"],
        ),
        nice_to_have=NiceToHaveTraits(),
        target_roles=[],
    )
    companies = [
        {"name": "Emil Frey France", "country": "France", "apollo_id": "ef1"},
        {"name": "Asseco", "country": "Poland", "apollo_id": "as1"},
    ]
    agent = LocationAgent()
    surviving = agent.filter_companies(icp, companies, max_km=0.0, debug=False)
    names = {c["name"] for c in surviving}
    assert names == {"Emil Frey France"}


def test_morocco_matches_maroc_alias():
    """Apollo often returns FR 'Maroc' while ICP extracts EN 'Morocco'."""
    icp = ICPAttributes(
        must_have=MustHaveTraits(
            industry=["Software"],
            target_continents=[],
            target_countries=["Morocco"],
        ),
        nice_to_have=NiceToHaveTraits(),
        target_roles=[],
    )
    companies = [
        {
            "name": "Intelcia",
            "country": "Maroc",
            "city": "Casablanca",
            "apollo_id": "intelcia",
        },
        {"name": "Telecom Egypt", "country": "Egypt", "apollo_id": "te"},
    ]
    agent = LocationAgent()
    surviving = agent.filter_companies(icp, companies, max_km=0.0, debug=False)
    names = {c["name"] for c in surviving}
    assert names == {"Intelcia"}
