"""
LangGraph persona contact waterfall.

Mirrors request_enrich_contacts_for_orchestrator strategy:

  local Neo4j (email+phone) → done
  → sync Apollo phone reveal
  → if email or phone missing → waterfall phone
  → if email still missing → waterfall email
  → merge + finalize

Providers stay plain Python callables (Apollo/Neo4j). No LLM orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph


class ContactWaterfallState(TypedDict, total=False):
    persona_apollo_id: str

    local_complete: bool
    local_contact: Dict[str, Any]

    sync_result: Dict[str, Any]
    waterfall_phone_result: Dict[str, Any]
    waterfall_email_result: Dict[str, Any]
    final_result: Dict[str, Any]

    has_email: bool
    has_phone: bool

    enrichment_path: str
    used_waterfall_fallback: bool
    from_local_cache: bool

    # Per-step observability: provider -> status/detail
    provider_status: Dict[str, Any]
    error: Optional[str]


@dataclass
class ContactWaterfallDeps:
    get_local_contacts: Callable[[List[str]], dict]
    enrich_sync_phone: Callable[[str], dict]
    enrich_waterfall_phone: Callable[[str], dict]
    enrich_waterfall_email: Callable[[str], dict]
    has_email: Callable[[dict], bool]
    has_phone: Callable[[dict], bool]
    merge_enrichment: Callable[[dict, dict], dict]
    try_waterfall_email: bool = True


def initial_contact_state(persona_apollo_id: str) -> ContactWaterfallState:
    return {
        "persona_apollo_id": str(persona_apollo_id).strip(),
        "local_complete": False,
        "local_contact": {},
        "sync_result": {},
        "waterfall_phone_result": {},
        "waterfall_email_result": {},
        "final_result": {},
        "has_email": False,
        "has_phone": False,
        "enrichment_path": "",
        "used_waterfall_fallback": False,
        "from_local_cache": False,
        "provider_status": {},
        "error": None,
    }


def _status_update(
    state: ContactWaterfallState,
    provider: str,
    status: str,
    **extra: Any,
) -> Dict[str, Any]:
    providers = dict(state.get("provider_status") or {})
    providers[provider] = {"status": status, **extra}
    return providers


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def node_check_local(deps: ContactWaterfallDeps, state: ContactWaterfallState) -> Dict[str, Any]:
    pid = state["persona_apollo_id"]
    local_map = deps.get_local_contacts([pid]) or {}
    local = local_map.get(pid) or {}
    providers = _status_update(state, "neo4j_local", "checked", complete=bool(local.get("complete")))

    if local.get("complete"):
        payload = local.get("contact") or {}
        print(
            f"[Waterfall] Contact cache hit for {pid} "
            f"(email+phone already in Neo4j) — Apollo enrich skip."
        )
        return {
            "local_complete": True,
            "local_contact": payload,
            "final_result": payload,
            "has_email": True,
            "has_phone": True,
            "enrichment_path": "neo4j_local",
            "used_waterfall_fallback": False,
            "from_local_cache": True,
            "provider_status": _status_update(
                {**state, "provider_status": providers},
                "neo4j_local",
                "hit",
            ),
        }

    print(f"[Waterfall] No complete local contact for {pid} — continue Apollo.")
    return {
        "local_complete": False,
        "local_contact": local.get("contact") or {},
        "from_local_cache": False,
        "provider_status": providers,
    }


def node_sync_reveal(deps: ContactWaterfallDeps, state: ContactWaterfallState) -> Dict[str, Any]:
    pid = state["persona_apollo_id"]
    print(f"[Waterfall] Sync phone reveal for {pid}")
    try:
        sync_result = deps.enrich_sync_phone(pid) or {}
    except Exception as e:
        print(f"[Waterfall] Sync reveal error for {pid}: {e}")
        sync_result = {"status": "error", "message": str(e)}

    has_email = deps.has_email(sync_result)
    has_phone = deps.has_phone(sync_result)
    providers = _status_update(
        state,
        "apollo_sync_phone",
        "success" if sync_result.get("status") == "success" else "error_or_empty",
        has_email=has_email,
        has_phone=has_phone,
    )
    return {
        "sync_result": sync_result,
        "has_email": has_email,
        "has_phone": has_phone,
        "provider_status": providers,
    }


def node_waterfall_phone(deps: ContactWaterfallDeps, state: ContactWaterfallState) -> Dict[str, Any]:
    pid = state["persona_apollo_id"]
    print(
        f"[Waterfall] Sync incomplete "
        f"(email={state.get('has_email')}, phone={state.get('has_phone')}) "
        f"— waterfall phone for {pid}"
    )
    try:
        wf_phone = deps.enrich_waterfall_phone(pid) or {}
    except Exception as e:
        print(f"[Waterfall] Waterfall phone error for {pid}: {e}")
        wf_phone = {"status": "error", "message": str(e)}

    merged = deps.merge_enrichment(state.get("sync_result") or {}, wf_phone)
    has_email = deps.has_email(merged)
    has_phone = deps.has_phone(merged)
    providers = _status_update(
        state,
        "apollo_waterfall_phone",
        "success" if wf_phone.get("status") == "success" else "error_or_empty",
        has_email=has_email,
        has_phone=has_phone,
    )
    return {
        "waterfall_phone_result": wf_phone,
        "final_result": merged,
        "has_email": has_email,
        "has_phone": has_phone,
        "used_waterfall_fallback": True,
        "enrichment_path": "enrich_persona_phone+waterfall_phone",
        "provider_status": providers,
    }


def node_waterfall_email(deps: ContactWaterfallDeps, state: ContactWaterfallState) -> Dict[str, Any]:
    pid = state["persona_apollo_id"]
    print(f"[Waterfall] Email still missing — waterfall email for {pid}")
    try:
        wf_email = deps.enrich_waterfall_email(pid) or {}
    except Exception as e:
        print(f"[Waterfall] Waterfall email error for {pid}: {e}")
        wf_email = {"status": "error", "message": str(e)}

    base = state.get("final_result") or state.get("sync_result") or {}
    merged = deps.merge_enrichment(base, wf_email)
    has_email = deps.has_email(merged)
    has_phone = deps.has_phone(merged)
    path = state.get("enrichment_path") or "enrich_persona_phone"
    if "waterfall_phone" in path:
        path = "enrich_persona_phone+waterfall_phone+waterfall_email"
    else:
        path = "enrich_persona_phone+waterfall_email"

    providers = _status_update(
        state,
        "apollo_waterfall_email",
        "success" if wf_email.get("status") == "success" else "error_or_empty",
        has_email=has_email,
        has_phone=has_phone,
    )
    return {
        "waterfall_email_result": wf_email,
        "final_result": merged,
        "has_email": has_email,
        "has_phone": has_phone,
        "used_waterfall_fallback": True,
        "enrichment_path": path,
        "provider_status": providers,
    }


def node_finalize(deps: ContactWaterfallDeps, state: ContactWaterfallState) -> Dict[str, Any]:
    if state.get("from_local_cache") and state.get("local_complete"):
        return {
            "final_result": state.get("final_result") or state.get("local_contact") or {},
            "enrichment_path": "neo4j_local",
            "used_waterfall_fallback": False,
            "has_email": True,
            "has_phone": True,
        }

    # Sync-only success path (no waterfall nodes ran)
    if not state.get("used_waterfall_fallback"):
        sync_result = state.get("sync_result") or {}
        return {
            "final_result": sync_result,
            "enrichment_path": "enrich_persona_phone",
            "used_waterfall_fallback": False,
            "has_email": deps.has_email(sync_result),
            "has_phone": deps.has_phone(sync_result),
        }

    # Waterfall path already filled final_result
    final_result = state.get("final_result") or state.get("sync_result") or {}
    return {
        "final_result": final_result,
        "has_email": deps.has_email(final_result),
        "has_phone": deps.has_phone(final_result),
        "enrichment_path": state.get("enrichment_path")
        or "enrich_persona_phone+waterfall_phone",
        "used_waterfall_fallback": True,
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_local(state: ContactWaterfallState) -> Literal["finalize", "sync_reveal"]:
    if state.get("local_complete"):
        return "finalize"
    return "sync_reveal"


def route_after_sync(state: ContactWaterfallState) -> Literal["finalize", "waterfall_phone"]:
    if state.get("has_email") and state.get("has_phone"):
        return "finalize"
    return "waterfall_phone"


def route_after_waterfall_phone(
    state: ContactWaterfallState,
    try_email: bool = True,
) -> Literal["finalize", "waterfall_email"]:
    if state.get("has_email") or not try_email:
        return "finalize"
    return "waterfall_email"


def build_contact_waterfall_graph(deps: ContactWaterfallDeps):
    g = StateGraph(ContactWaterfallState)

    g.add_node("check_local", lambda s: node_check_local(deps, s))
    g.add_node("sync_reveal", lambda s: node_sync_reveal(deps, s))
    g.add_node("waterfall_phone", lambda s: node_waterfall_phone(deps, s))
    g.add_node("waterfall_email", lambda s: node_waterfall_email(deps, s))
    g.add_node("finalize", lambda s: node_finalize(deps, s))

    g.set_entry_point("check_local")
    g.add_conditional_edges(
        "check_local",
        route_after_local,
        {"finalize": "finalize", "sync_reveal": "sync_reveal"},
    )
    g.add_conditional_edges(
        "sync_reveal",
        route_after_sync,
        {"finalize": "finalize", "waterfall_phone": "waterfall_phone"},
    )

    def _route_wf_phone(state: ContactWaterfallState) -> str:
        return route_after_waterfall_phone(state, try_email=deps.try_waterfall_email)

    g.add_conditional_edges(
        "waterfall_phone",
        _route_wf_phone,
        {"finalize": "finalize", "waterfall_email": "waterfall_email"},
    )
    g.add_edge("waterfall_email", "finalize")
    g.add_edge("finalize", END)

    return g.compile()


def enrich_one_persona_contacts(
    deps: ContactWaterfallDeps,
    persona_apollo_id: str,
) -> Dict[str, Any]:
    """Run waterfall for one persona. Returns orchestrator-shaped result dict."""
    graph = build_contact_waterfall_graph(deps)
    result = graph.invoke(initial_contact_state(persona_apollo_id))
    final = result.get("final_result") or {}
    return {
        "email_enrichment": final,
        "phone_enrichment": final,
        "enrichment_path": result.get("enrichment_path") or "",
        "used_waterfall_fallback": bool(result.get("used_waterfall_fallback")),
        "from_local_cache": bool(result.get("from_local_cache")),
        "has_email": bool(result.get("has_email")),
        "has_phone": bool(result.get("has_phone")),
        "provider_status": result.get("provider_status") or {},
        "error": result.get("error"),
    }


def enrich_persona_contacts_batch(
    deps: ContactWaterfallDeps,
    persona_apollo_ids: List[str],
) -> Dict[str, Any]:
    """Run waterfall for many personas; keyed by persona_apollo_id."""
    results: Dict[str, Any] = {}
    for raw_id in persona_apollo_ids or []:
        pid = str(raw_id).strip()
        if not pid:
            continue
        results[pid] = enrich_one_persona_contacts(deps, pid)
    return results
