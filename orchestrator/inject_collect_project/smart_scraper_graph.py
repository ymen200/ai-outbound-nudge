"""
LangGraph orchestration for SmartScraperAI.

Wraps existing SmartScraperAI methods 1:1. Playwright browser/page live on the
scraper instance (_browser_session), not in graph state (not serializable).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Literal, Optional, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph
from playwright.sync_api import sync_playwright

PDF_KEYWORDS = ["report", "annual", "integrated", "financial", "investors"]
REVENUE_MISSING = "annual_revenue (chiffre exact)"


class ScraperState(TypedDict, total=False):
    url: str
    target_address: Optional[str]
    max_depth: int

    locale: str
    timezone_id: str

    full_content: List[str]
    standard_links: List[Dict[str, Any]]
    potential_pdfs: List[str]
    real_social_links: Dict[str, Any]
    seen_urls: List[str]

    extracted_data: Optional[Dict[str, Any]]
    missing_fields: List[str]
    next_urls: List[str]
    depth: int

    json_filepath: Optional[str]
    raw_filepath: Optional[str]
    error: Optional[str]


def initial_scraper_state(
    url: str,
    target_address: Optional[str] = None,
    max_depth: int = 2,
) -> ScraperState:
    return {
        "url": url,
        "target_address": target_address,
        "max_depth": max_depth,
        "locale": "en-US",
        "timezone_id": "UTC",
        "full_content": [],
        "standard_links": [],
        "potential_pdfs": [],
        "real_social_links": {},
        "seen_urls": [],
        "extracted_data": None,
        "missing_fields": [],
        "next_urls": [],
        "depth": 0,
        "json_filepath": None,
        "raw_filepath": None,
        "error": None,
    }


def _page(scraper: Any):
    session = getattr(scraper, "_browser_session", None) or {}
    page = session.get("page")
    if page is None:
        raise RuntimeError("Browser session is not open (missing page).")
    return page


def _close_browser_session(scraper: Any) -> None:
    session = getattr(scraper, "_browser_session", None)
    if not session:
        return
    browser = session.get("browser")
    playwright = session.get("playwright")
    try:
        if browser is not None:
            browser.close()
    except Exception as e:
        print(f"⚠️ Erreur fermeture navigateur : {e}")
    try:
        if playwright is not None:
            playwright.stop()
    except Exception as e:
        print(f"⚠️ Erreur arrêt Playwright : {e}")
    scraper._browser_session = None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def node_plan_browser(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    target_address = state.get("target_address")
    print(f"🧠 L'IA configure le navigateur pour la cible : {target_address}")
    cfg = scraper.get_browser_config_with_ai(target_address)
    return {
        "locale": cfg.get("locale", "en-US"),
        "timezone_id": cfg.get("timezone_id", "UTC"),
    }


def node_open_browser(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    url = state["url"]
    print(f"🚀 Lancement du navigateur pour : {url}")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    random_user_agent = scraper.ua.random
    context = browser.new_context(
        locale=state.get("locale", "en-US"),
        timezone_id=state.get("timezone_id", "UTC"),
        user_agent=random_user_agent,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    scraper._browser_session = {
        "playwright": playwright,
        "browser": browser,
        "context": context,
        "page": page,
    }
    return {}


def node_observe_homepage(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    page = _page(scraper)
    url = state["url"]
    target_address = state.get("target_address")

    def go_main():
        return page.goto(url, wait_until="domcontentloaded", timeout=60000)

    response_main = scraper.execute_with_retry(
        go_main, operation_name=f"Navigation principale {url}"
    )
    page.wait_for_timeout(2000)

    try:
        page.click("text='Accept All'", timeout=3000)
    except Exception:
        pass

    scraper.smart_scroll(page)

    title = page.title()
    raw_html = page.content()

    tech_footprint_text = scraper.extract_tech_footprint(page, response_main)
    hidden_techs_regex = scraper.extract_hidden_tech(raw_html)
    real_social_links = scraper.extract_social_links_from_html(page)

    all_links_raw = page.locator("a").evaluate_all(
        "list => list.map(a => ({text: a.innerText.trim(), url: a.href}))"
    )

    potential_pdfs: List[str] = []
    standard_links: List[Dict[str, Any]] = []
    for link in all_links_raw:
        link_url = link["url"].lower()
        link_text = link["text"].lower()
        if ".pdf" in link_url and any(
            kw in link_url or kw in link_text for kw in PDF_KEYWORDS
        ):
            potential_pdfs.append(link["url"])
        else:
            standard_links.append(link)

    full_content = [f"--- PAGE D'ACCUEIL : {title} ---"]
    if target_address:
        full_content.append("\n⚠️ DIRECTIVE DE CIBLAGE (APOLLO) ⚠️")
        full_content.append(f"ADRESSE CIBLE : {target_address}")
        full_content.append(
            "Instructions : L'utilisateur recherche spécifiquement cette entité régionale. "
            "Ignore le siège mondial global et focalise-toi sur les données "
            "(revenus, adresse, filiale) de CETTE localisation.\n"
        )
    full_content.append(tech_footprint_text)
    if hidden_techs_regex:
        full_content.append(
            f"--- MATCHES REGEX CLASSIQUES ---\n{', '.join(hidden_techs_regex)}\n"
        )
    full_content.append(scraper.clean_html(raw_html))

    return {
        "full_content": full_content,
        "standard_links": standard_links,
        "potential_pdfs": potential_pdfs,
        "real_social_links": real_social_links,
        "seen_urls": [url],
    }


def node_extract_profile(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    full_content = state.get("full_content") or []
    extracted_data = scraper.extract_apollo_json("\n".join(full_content))
    return {"extracted_data": extracted_data}


def node_evaluate_gaps(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    missing_fields = scraper.check_missing_fields(state.get("extracted_data"))
    return {"missing_fields": missing_fields}


def node_plan_navigation(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    missing_fields = state.get("missing_fields") or []
    depth = int(state.get("depth") or 0)
    max_depth = int(state.get("max_depth") or 2)
    print(
        f"\n🔄 Boucle Autonome (Step {depth + 1}/{max_depth}) - "
        f"Infos manquantes : {missing_fields}"
    )
    seen = set(state.get("seen_urls") or [])
    next_urls = scraper.get_targeted_links_with_ai(
        state.get("standard_links") or [],
        state["url"],
        missing_fields,
        seen,
    )
    if not next_urls:
        print("    ⚠️ Plus d'URLs pertinentes pour ces infos.")
    return {"next_urls": next_urls or []}


def node_visit_pages(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    page = _page(scraper)
    full_content = list(state.get("full_content") or [])
    seen_urls = set(state.get("seen_urls") or [])
    potential_pdfs = list(state.get("potential_pdfs") or [])
    next_urls = state.get("next_urls") or []

    for sub_url in next_urls:
        if sub_url in seen_urls:
            continue

        print(f"🎯 Investigation ciblée : {sub_url}")
        try:

            def go_sub(u=sub_url):
                return page.goto(u, wait_until="domcontentloaded", timeout=45000)

            response_sub = scraper.execute_with_retry(
                go_sub,
                max_retries=2,
                operation_name=f"Sous-page {sub_url}",
            )
            page.wait_for_timeout(2000)
            scraper.smart_scroll(page)

            sub_raw_html = page.content()
            sub_tech_footprint = scraper.extract_tech_footprint(page, response_sub)

            full_content.append(f"\n\n--- PAGE STRATÉGIQUE : {sub_url} ---")
            full_content.append(sub_tech_footprint)
            full_content.append(scraper.clean_html(sub_raw_html))
            seen_urls.add(sub_url)

            sub_page_pdfs = page.locator('a[href$=".pdf"]').evaluate_all(
                "list => list.map(a => a.href)"
            )
            for pdf in sub_page_pdfs:
                if (
                    any(kw in pdf.lower() for kw in PDF_KEYWORDS)
                    and pdf not in potential_pdfs
                ):
                    potential_pdfs.append(pdf)
        except Exception as e:
            print(f"    ⚠️ Erreur de navigation : {e}")

    return {
        "full_content": full_content,
        "seen_urls": list(seen_urls),
        "potential_pdfs": potential_pdfs,
        "next_urls": [],
        "depth": int(state.get("depth") or 0) + 1,
    }


def node_pdf_scan(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    potential_pdfs = state.get("potential_pdfs") or []
    if not potential_pdfs:
        return {}

    target_pdf = potential_pdfs[0]
    pdf_text = scraper.extract_pdf_in_memory(target_pdf)
    if not pdf_text:
        return {}

    full_content = list(state.get("full_content") or [])
    full_content.append(f"\n\n--- EXTRAITS FINANCIERS DU PDF ({target_pdf}) ---")
    full_content.append(pdf_text)
    return {"full_content": full_content}


def node_postprocess(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    extracted_data = state.get("extracted_data")
    if not extracted_data:
        return {}

    full_text = "\n".join(state.get("full_content") or [])
    extracted_data = scraper.fix_social_links(
        extracted_data, state.get("real_social_links") or {}
    )
    extracted_data = scraper.finalize_data_with_llm(extracted_data, full_text)
    print(
        "    🧪 [XAI] Calcul des métriques d'explicabilité "
        "(Faithfulness, Calibration, Density)..."
    )
    extracted_data = scraper.inject_xai_metrics(extracted_data, full_text)
    return {"extracted_data": extracted_data}


def node_persist(scraper: Any, state: ScraperState) -> Dict[str, Any]:
    url = state["url"]
    full_content = state.get("full_content") or []
    extracted_data = state.get("extracted_data")

    domain_name = urlparse(url).netloc.replace(".", "_")
    raw_filepath = os.path.join(scraper.output_dir, f"{domain_name}_RAW.txt")

    with open(raw_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(full_content))

    if extracted_data:
        json_filepath = os.path.join(scraper.output_dir, f"{domain_name}_APOLLO.json")
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f, indent=4, ensure_ascii=False)
        print(
            f"\n✅ Succès ! Fichier JSON final généré avec XAI Metrics : {json_filepath}"
        )
        return {"raw_filepath": raw_filepath, "json_filepath": json_filepath}

    print("⚠️ Échec de la génération du JSON final.")
    return {"raw_filepath": raw_filepath, "json_filepath": None}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_evaluate(state: ScraperState) -> Literal["plan_navigation", "pdf_gate"]:
    missing = state.get("missing_fields") or []
    depth = int(state.get("depth") or 0)
    max_depth = int(state.get("max_depth") or 2)
    if missing and depth < max_depth:
        return "plan_navigation"
    return "pdf_gate"


def route_after_plan_nav(state: ScraperState) -> Literal["visit_pages", "pdf_gate"]:
    if state.get("next_urls"):
        return "visit_pages"
    return "pdf_gate"


def route_maybe_pdf(state: ScraperState) -> Literal["pdf_scan", "postprocess"]:
    missing = state.get("missing_fields") or []
    if (state.get("potential_pdfs") or []) and REVENUE_MISSING in missing:
        return "pdf_scan"
    return "postprocess"


def node_pdf_gate(_scraper: Any, _state: ScraperState) -> Dict[str, Any]:
    """No-op router node so conditional edges stay explicit."""
    return {}


# ---------------------------------------------------------------------------
# Graph builder + runner
# ---------------------------------------------------------------------------

def build_scraper_graph(scraper: Any):
    g = StateGraph(ScraperState)

    g.add_node("plan_browser", lambda s: node_plan_browser(scraper, s))
    g.add_node("open_browser", lambda s: node_open_browser(scraper, s))
    g.add_node("observe_homepage", lambda s: node_observe_homepage(scraper, s))
    g.add_node("extract_profile", lambda s: node_extract_profile(scraper, s))
    g.add_node("evaluate_gaps", lambda s: node_evaluate_gaps(scraper, s))
    g.add_node("plan_navigation", lambda s: node_plan_navigation(scraper, s))
    g.add_node("visit_pages", lambda s: node_visit_pages(scraper, s))
    g.add_node("pdf_gate", lambda s: node_pdf_gate(scraper, s))
    g.add_node("pdf_scan", lambda s: node_pdf_scan(scraper, s))
    g.add_node("extract_after_pdf", lambda s: node_extract_profile(scraper, s))
    g.add_node("postprocess", lambda s: node_postprocess(scraper, s))
    g.add_node("persist", lambda s: node_persist(scraper, s))

    g.set_entry_point("plan_browser")
    g.add_edge("plan_browser", "open_browser")
    g.add_edge("open_browser", "observe_homepage")
    g.add_edge("observe_homepage", "extract_profile")
    g.add_edge("extract_profile", "evaluate_gaps")

    g.add_conditional_edges(
        "evaluate_gaps",
        route_after_evaluate,
        {
            "plan_navigation": "plan_navigation",
            "pdf_gate": "pdf_gate",
        },
    )
    g.add_conditional_edges(
        "plan_navigation",
        route_after_plan_nav,
        {
            "visit_pages": "visit_pages",
            "pdf_gate": "pdf_gate",
        },
    )
    g.add_edge("visit_pages", "extract_profile")

    g.add_conditional_edges(
        "pdf_gate",
        route_maybe_pdf,
        {
            "pdf_scan": "pdf_scan",
            "postprocess": "postprocess",
        },
    )
    g.add_edge("pdf_scan", "extract_after_pdf")
    g.add_edge("extract_after_pdf", "postprocess")
    g.add_edge("postprocess", "persist")
    g.add_edge("persist", END)

    return g.compile()


def run_scraper_graph(
    scraper: Any,
    url: str,
    target_address: Optional[str] = None,
    max_depth: int = 2,
) -> Optional[str]:
    """
    Run the LangGraph scrape pipeline. Always closes the browser session.
    Returns json_filepath if available, else raw_filepath (same as legacy).
    """
    graph = build_scraper_graph(scraper)
    try:
        result = graph.invoke(
            initial_scraper_state(url, target_address=target_address, max_depth=max_depth)
        )
        return result.get("json_filepath") or result.get("raw_filepath")
    finally:
        _close_browser_session(scraper)
