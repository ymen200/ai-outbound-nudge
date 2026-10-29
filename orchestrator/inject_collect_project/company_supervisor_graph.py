"""
LangGraph company supervisor.

1) Per-company enrichment graph (used inside request_discover_companies):
   normalize → apollo_enrich → scrape? → merge → (low DQS re-scrape?) → describe

2) Optional mission graph (discover → intent → personas → contacts):
   wraps existing request_* tools; Neo4j writes stay in those tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

# Re-scrape once when merged DQS is below this threshold.
LOW_DQS_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Per-company enrichment state
# ---------------------------------------------------------------------------

class CompanyEnrichState(TypedDict, total=False):
    company: Dict[str, Any]
    target_loc: Optional[str]
    target_industry: str

    valid_domain: bool
    domain: str
    website_url: Optional[str]
    target_addr: str

    full_data: Dict[str, Any]
    ai_json_path: Optional[str]
    merged_data: Optional[Dict[str, Any]]

    rescrape_done: bool
    scrape_attempted: bool
    scrape_succeeded: bool

    profile_out: Optional[Dict[str, Any]]
    profile_kind: str  # "merged" | "apollo"
    error: Optional[str]


@dataclass
class CompanyEnrichDeps:
    apollo_scraper: Any
    ai_scraper: Any
    generate_merged_report: Callable[..., Optional[dict]]
    generate_source_comparison_report: Callable[..., Any]
    generate_company_full_description: Callable[[dict], dict]
    gemini_tracker: Any = None
    low_dqs_threshold: float = LOW_DQS_THRESHOLD


def initial_company_enrich_state(
    company: dict,
    target_loc: Optional[str],
    target_industry: str,
) -> CompanyEnrichState:
    return {
        "company": company,
        "target_loc": target_loc,
        "target_industry": target_industry,
        "valid_domain": False,
        "domain": "",
        "website_url": None,
        "target_addr": "",
        "full_data": dict(company),
        "ai_json_path": None,
        "merged_data": None,
        "rescrape_done": False,
        "scrape_attempted": False,
        "scrape_succeeded": False,
        "profile_out": None,
        "profile_kind": "apollo",
        "error": None,
    }


def _build_target_addr(full_data: dict, target_loc: Optional[str]) -> str:
    loc_data = full_data.get("location", {}) if isinstance(full_data.get("location"), dict) else {}
    street = loc_data.get("street_address") or full_data.get("street_address") or ""
    city = loc_data.get("city") or full_data.get("city") or ""
    country = loc_data.get("country") or full_data.get("country") or target_loc or ""
    parts = [p for p in [street, city, country] if p and p != "Non renseigné"]
    return ", ".join(parts)


# --- nodes ---

def node_normalize(_deps: CompanyEnrichDeps, state: CompanyEnrichState) -> Dict[str, Any]:
    company = dict(state.get("company") or {})
    domain = company.get("domain")
    valid_domain = bool(domain and domain != "Non renseigné")
    website_url = company.get("website_url") or company.get("website")
    target_addr = _build_target_addr(company, state.get("target_loc"))
    return {
        "full_data": company,
        "domain": domain or "",
        "valid_domain": valid_domain,
        "website_url": website_url,
        "target_addr": target_addr,
    }


def node_apollo_enrich(deps: CompanyEnrichDeps, state: CompanyEnrichState) -> Dict[str, Any]:
    if not state.get("valid_domain"):
        print("⚠️ Domaine invalide — Apollo enrich ignoré.")
        return {}

    domain = state.get("domain")
    company = state.get("company") or {}
    full_data = dict(state.get("full_data") or company)
    target_loc = state.get("target_loc")

    try:
        enriched = deps.apollo_scraper.enrich_organization(
            domain=domain,
            target_location=target_loc,
            trace_identifier=domain,
        )
        if enriched:
            full_data = {**company, **enriched}
    except Exception as e:
        print(f"⚠️ Erreur enrichissement Apollo pour {domain}: {e}")
        return {"full_data": full_data, "error": str(e)}

    target_addr = _build_target_addr(full_data, target_loc)
    website_url = full_data.get("website_url") or full_data.get("website")
    return {
        "full_data": full_data,
        "website_url": website_url,
        "target_addr": target_addr,
    }


def node_scrape(deps: CompanyEnrichDeps, state: CompanyEnrichState) -> Dict[str, Any]:
    website_url = state.get("website_url")
    target_addr = state.get("target_addr") or ""
    full_data = state.get("full_data") or {}

    if not (
        state.get("valid_domain")
        and website_url
        and website_url != "Non renseigné"
        and str(website_url).startswith("http")
    ):
        name = full_data.get("name", "cette entreprise")
        print(f"⚠️ Pas d'URL valide pour {name}, SmartScraperAI ignoré.")
        return {"scrape_attempted": False, "scrape_succeeded": False, "ai_json_path": None}

    try:
        print(f"🤖 Lancement de SmartScraperAI pour le site : {website_url}")
        if target_addr:
            print(f"📍 Cible géographique transmise à l'IA : {target_addr}")

        path_to_json = deps.ai_scraper.scrape_and_save(
            website_url,
            target_address=target_addr,
            token_tracker=deps.gemini_tracker,
        )
        if path_to_json and str(path_to_json).endswith(".json"):
            return {
                "scrape_attempted": True,
                "scrape_succeeded": True,
                "ai_json_path": path_to_json,
            }
        print("⚠️ Le scraping IA n'a pas retourné de chemin JSON valide.")
        return {
            "scrape_attempted": True,
            "scrape_succeeded": False,
            "ai_json_path": None,
        }
    except Exception as e:
        print(f"❌ Erreur SmartScraperAI sur {website_url}: {e}")
        return {
            "scrape_attempted": True,
            "scrape_succeeded": False,
            "ai_json_path": None,
            "error": str(e),
        }


def node_merge(deps: CompanyEnrichDeps, state: CompanyEnrichState) -> Dict[str, Any]:
    full_data = dict(state.get("full_data") or {})
    ai_json_path = state.get("ai_json_path")
    if not ai_json_path:
        return {"merged_data": None}

    comparison_paths = deps.generate_source_comparison_report(full_data, ai_json_path)
    merged_data = deps.generate_merged_report(full_data, ai_json_path)
    if merged_data and comparison_paths:
        merged_data["comparison_report_path"] = comparison_paths.get("comparison")
        merged_data["full_comparison_report_path"] = comparison_paths.get("full_report")
    return {"merged_data": merged_data}


def node_describe(deps: CompanyEnrichDeps, state: CompanyEnrichState) -> Dict[str, Any]:
    target_industry = state.get("target_industry") or "Unknown"
    merged_data = state.get("merged_data")
    full_data = dict(state.get("full_data") or {})

    # Secure anti-collision domain (same as legacy discover loop)
    if not full_data.get("domain") or full_data.get("domain") == "Non renseigné":
        safe_name = str(full_data.get("name", "unknown")).replace(" ", "_").lower()
        full_data["domain"] = f"unknown_{safe_name}"

    if merged_data:
        merged_data = dict(merged_data)
        merged_data["global_industry"] = target_industry
        merged_data = deps.generate_company_full_description(merged_data)
        return {
            "full_data": full_data,
            "merged_data": merged_data,
            "profile_out": merged_data,
            "profile_kind": "merged",
        }

    full_data["global_industry"] = target_industry
    full_data = deps.generate_company_full_description(full_data)
    return {
        "full_data": full_data,
        "profile_out": full_data,
        "profile_kind": "apollo",
    }


# --- routing ---

def route_after_apollo(state: CompanyEnrichState) -> Literal["scrape", "describe"]:
    website_url = state.get("website_url")
    if (
        state.get("valid_domain")
        and website_url
        and website_url != "Non renseigné"
        and str(website_url).startswith("http")
    ):
        return "scrape"
    return "describe"  # Apollo-only path


def route_after_scrape(state: CompanyEnrichState) -> Literal["merge", "describe"]:
    if state.get("scrape_succeeded") and state.get("ai_json_path"):
        return "merge"
    return "describe"


def route_after_merge(
    state: CompanyEnrichState,
    threshold: float = LOW_DQS_THRESHOLD,
) -> Literal["scrape", "describe"]:
    """Low DQS → one optional re-scrape; otherwise continue to describe."""
    if state.get("rescrape_done"):
        return "describe"
    merged = state.get("merged_data") or {}
    try:
        dqs = float(merged.get("data_quality_score") or 0.0)
    except (TypeError, ValueError):
        dqs = 0.0
    if dqs < threshold and state.get("website_url"):
        print(
            f"[RETRY] DQS bas ({dqs} < {threshold}) — nouvelle passe SmartScraperAI..."
        )
        return "scrape"
    return "describe"


def build_company_enrichment_graph(deps: CompanyEnrichDeps):
    g = StateGraph(CompanyEnrichState)

    g.add_node("normalize", lambda s: node_normalize(deps, s))
    g.add_node("apollo_enrich", lambda s: node_apollo_enrich(deps, s))
    g.add_node("scrape", lambda s: node_scrape(deps, s))
    g.add_node("merge", lambda s: node_merge(deps, s))
    g.add_node("describe", lambda s: node_describe(deps, s))

    g.set_entry_point("normalize")
    g.add_edge("normalize", "apollo_enrich")
    g.add_conditional_edges(
        "apollo_enrich",
        route_after_apollo,
        {"scrape": "scrape", "describe": "describe"},
    )
    g.add_conditional_edges(
        "scrape",
        route_after_scrape,
        {"merge": "merge", "describe": "describe"},
    )

    def _route_merge(state: CompanyEnrichState) -> str:
        nxt = route_after_merge(state, threshold=deps.low_dqs_threshold)
        if nxt == "scrape":
            # mark rescrape so the next merge won't loop forever
            return "rescrape"
        return "describe"

    g.add_node(
        "mark_rescrape",
        lambda s: {"rescrape_done": True},
    )
    g.add_conditional_edges(
        "merge",
        _route_merge,
        {"rescrape": "mark_rescrape", "describe": "describe"},
    )
    g.add_edge("mark_rescrape", "scrape")
    g.add_edge("describe", END)

    return g.compile()


def enrich_one_company(
    deps: CompanyEnrichDeps,
    company: dict,
    target_loc: Optional[str],
    target_industry: str,
) -> Dict[str, Any]:
    """
    Run per-company LangGraph enrichment.
    Returns dict with profile_out, profile_kind, scrape_attempted, scrape_succeeded.
    """
    graph = build_company_enrichment_graph(deps)
    result = graph.invoke(
        initial_company_enrich_state(company, target_loc, target_industry)
    )
    return {
        "profile_out": result.get("profile_out"),
        "profile_kind": result.get("profile_kind") or "apollo",
        "scrape_attempted": bool(result.get("scrape_attempted")),
        "scrape_succeeded": bool(result.get("scrape_succeeded")),
        "merged_data": result.get("merged_data"),
        "full_data": result.get("full_data"),
        "error": result.get("error"),
    }


# ---------------------------------------------------------------------------
# Mission supervisor (discover → intent → personas → contacts)
# ---------------------------------------------------------------------------

class CompanyMissionState(TypedDict, total=False):
    industries: List[Any]
    locations: Optional[List[Any]]
    continent: Optional[str]
    employee_ranges: Optional[List[Any]]
    limit: int
    limit_per_element: int
    min_employees: Optional[float]
    max_employees: Optional[float]
    target_country: Optional[str]
    role: Optional[List[Any]]

    include_intent: bool
    include_personas: bool
    include_contacts: bool

    companies: List[Dict[str, Any]]
    company_apollo_ids: List[str]
    intent_results: Dict[str, Any]
    persona_results: Dict[str, Any]
    contact_results: Dict[str, Any]
    error: Optional[str]


@dataclass
class CompanyMissionDeps:
    discover_companies: Callable[..., list]
    enrich_intents: Callable[..., Any]
    enrich_personas: Callable[..., Any]
    enrich_contacts: Callable[..., Any]


def initial_mission_state(
    *,
    industries: list,
    locations: Optional[list] = None,
    continent: Optional[str] = None,
    employee_ranges: Optional[list] = None,
    limit: int = 2,
    limit_per_element: int = 1,
    min_employees: Optional[float] = None,
    max_employees: Optional[float] = None,
    target_country: Optional[str] = None,
    role: Optional[list] = None,
    include_intent: bool = False,
    include_personas: bool = False,
    include_contacts: bool = False,
) -> CompanyMissionState:
    return {
        "industries": industries,
        "locations": locations,
        "continent": continent,
        "employee_ranges": employee_ranges,
        "limit": limit,
        "limit_per_element": limit_per_element,
        "min_employees": min_employees,
        "max_employees": max_employees,
        "target_country": target_country,
        "role": role,
        "include_intent": include_intent,
        "include_personas": include_personas,
        "include_contacts": include_contacts,
        "companies": [],
        "company_apollo_ids": [],
        "intent_results": {},
        "persona_results": {},
        "contact_results": {},
        "error": None,
    }


def _apollo_ids_from_companies(companies: list) -> List[str]:
    ids: List[str] = []
    seen = set()
    for c in companies or []:
        aid = c.get("apollo_id") or c.get("id")
        if not aid:
            continue
        aid = str(aid)
        if aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
    return ids


def node_mission_discover(deps: CompanyMissionDeps, state: CompanyMissionState) -> Dict[str, Any]:
    print("🕸️ [Mission] Étape discover…")
    companies = deps.discover_companies(
        industries=state.get("industries") or [],
        locations=state.get("locations"),
        continent=state.get("continent"),
        employee_ranges=state.get("employee_ranges"),
        limit=int(state.get("limit") or 2),
        limit_per_element=int(state.get("limit_per_element") or 1),
        min_employees=state.get("min_employees"),
        max_employees=state.get("max_employees"),
    ) or []
    apollo_ids = _apollo_ids_from_companies(companies)
    print(f"🕸️ [Mission] Discover terminé — {len(companies)} company(ies), {len(apollo_ids)} apollo_id(s)")
    return {"companies": companies, "company_apollo_ids": apollo_ids}


def node_mission_intent(deps: CompanyMissionDeps, state: CompanyMissionState) -> Dict[str, Any]:
    apollo_ids = state.get("company_apollo_ids") or []
    if not apollo_ids:
        print("⚠️ [Mission] Intent ignoré — aucun apollo_id.")
        return {"intent_results": {}}
    print(f"🕸️ [Mission] Étape intent ({len(apollo_ids)})…")
    results = deps.enrich_intents(
        apollo_ids,
        target_country=state.get("target_country"),
    ) or {}
    return {"intent_results": results}


def node_mission_personas(deps: CompanyMissionDeps, state: CompanyMissionState) -> Dict[str, Any]:
    apollo_ids = state.get("company_apollo_ids") or []
    if not apollo_ids:
        print("⚠️ [Mission] Personas ignorés — aucun apollo_id.")
        return {"persona_results": {}}
    # Skip personas when no company has a usable domain signal in discover results
    has_domain = any(
        (c.get("domain") and c.get("domain") != "Non renseigné")
        for c in (state.get("companies") or [])
    )
    if not has_domain:
        print("⚠️ [Mission] Personas ignorés — aucun domaine utilisable.")
        return {"persona_results": {"status": "skipped_no_domain"}}

    print(f"🕸️ [Mission] Étape personas ({len(apollo_ids)})…")
    results = deps.enrich_personas(
        apollo_ids,
        target_country=state.get("target_country"),
        role=state.get("role"),
        limit=max(10, len(apollo_ids) * 3),
        limit_per_element=3,
    ) or {}
    return {"persona_results": results}


def node_mission_contacts(deps: CompanyMissionDeps, state: CompanyMissionState) -> Dict[str, Any]:
    persona_results = state.get("persona_results") or {}
    persona_ids: List[str] = []
    for _key, payload in persona_results.items():
        if not isinstance(payload, dict):
            continue
        for p in payload.get("personas") or payload.get("enriched_personas") or []:
            pid = p.get("apollo_id") or p.get("id")
            if pid:
                persona_ids.append(str(pid))
    persona_ids = list(dict.fromkeys(persona_ids))
    if not persona_ids:
        print("⚠️ [Mission] Contacts ignorés — aucun persona_id.")
        return {"contact_results": {}}
    print(f"🕸️ [Mission] Étape contacts ({len(persona_ids)})…")
    results = deps.enrich_contacts(persona_ids) or {}
    return {"contact_results": results}


def route_after_discover(state: CompanyMissionState) -> Literal["intent", "personas", "contacts", "end"]:
    if state.get("include_intent"):
        return "intent"
    if state.get("include_personas"):
        return "personas"
    if state.get("include_contacts"):
        return "contacts"
    return "end"


def route_after_intent(state: CompanyMissionState) -> Literal["personas", "contacts", "end"]:
    if state.get("include_personas"):
        return "personas"
    if state.get("include_contacts"):
        return "contacts"
    return "end"


def route_after_personas(state: CompanyMissionState) -> Literal["contacts", "end"]:
    if state.get("include_contacts"):
        return "contacts"
    return "end"


def build_company_mission_graph(deps: CompanyMissionDeps):
    g = StateGraph(CompanyMissionState)
    g.add_node("discover", lambda s: node_mission_discover(deps, s))
    g.add_node("intent", lambda s: node_mission_intent(deps, s))
    g.add_node("personas", lambda s: node_mission_personas(deps, s))
    g.add_node("contacts", lambda s: node_mission_contacts(deps, s))
    g.add_node("end_noop", lambda s: {})

    g.set_entry_point("discover")
    g.add_conditional_edges(
        "discover",
        route_after_discover,
        {
            "intent": "intent",
            "personas": "personas",
            "contacts": "contacts",
            "end": "end_noop",
        },
    )
    g.add_conditional_edges(
        "intent",
        route_after_intent,
        {
            "personas": "personas",
            "contacts": "contacts",
            "end": "end_noop",
        },
    )
    g.add_conditional_edges(
        "personas",
        route_after_personas,
        {
            "contacts": "contacts",
            "end": "end_noop",
        },
    )
    g.add_edge("contacts", "end_noop")
    g.add_edge("end_noop", END)
    return g.compile()


def run_company_mission(
    deps: CompanyMissionDeps,
    **kwargs: Any,
) -> CompanyMissionState:
    """Run discover (+ optional intent/personas/contacts) via LangGraph."""
    graph = build_company_mission_graph(deps)
    return graph.invoke(initial_mission_state(**kwargs))
