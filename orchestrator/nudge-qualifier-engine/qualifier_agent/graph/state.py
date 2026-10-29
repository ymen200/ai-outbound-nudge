# # graph/state.py

# from __future__ import annotations
# from typing import Any, Dict, List, Optional
# from typing_extensions import TypedDict
# from brain.schemas import ICPAttributes

# # ── Reducer Functions ─────────────────────────────────────────────────────────

# def reduce_disqualification_log(old_log: DisqualificationLog, new_log: DisqualificationLog) -> DisqualificationLog:
#     """Merges new disqualification records and updates counts automatically."""
#     if not old_log:
#         return new_log
#     if not new_log:
#         return old_log
        
#     # Combine lists of records
#     combined_records = old_log.get("records", []) + new_log.get("records", [])
    
#     # Update running counters
#     total_eval = old_log.get("total_evaluated", 0) + new_log.get("total_evaluated", 0)
#     total_pass = old_log.get("total_passed", 0) + new_log.get("total_passed", 0)
#     total_disq = old_log.get("total_disqualified", 0) + new_log.get("total_disqualified", 0)
    
#     # Merge summary dictionary (reason_code -> count)
#     combined_summary = dict(old_log.get("summary", {}))
#     for code, count in new_log.get("summary", {}).items():
#         combined_summary[code] = combined_summary.get(code, 0) + count
        
#     return {
#         "total_evaluated": total_eval,
#         "total_passed": total_pass,
#         "total_disqualified": total_disq,
#         "records": combined_records,
#         "summary": combined_summary
#     }

# # ── Audit trail ───────────────────────────────────────────────────────────────

# class DisqualificationRecord(TypedDict):
#     entity_type: str        # 'company' or 'persona'
#     entity_name: str
#     entity_id:   Optional[str]
#     reason_code: str        # 'BLACKLIST' | 'EXCLUDE_INDUSTRY' | 'EXCLUDE_KEYWORD' ...
#     reason_detail: str
#     firm_score:  Optional[float]
#     timestamp:   str
#     campaign_id: Optional[str]

# class DisqualificationLog(TypedDict):
#     total_evaluated:   int
#     total_passed:      int
#     total_disqualified: int
#     records:   List[DisqualificationRecord]
#     summary:   Dict[str, int]   

# # ── Blacklist ─────────────────────────────────────────────────────────────────

# class BlacklistConfig(TypedDict):
#     companies: List[str]   
#     personas:  List[str]   

# # ── Main pipeline state ───────────────────────────────────────────────────────

# from langgraph.graph.message import add_messages # standard if you use messages, but we use Annotated for lists

# from typing import Annotated

# class CampaignState(TypedDict):
#     # ── Inputs ────────────────────────────────────────────────────────────────
#     icp_description_text: str
#     user_offering:        str
#     blacklist:            BlacklistConfig
#     configurable_weights: Dict[str, float]
#     campaign_id:          Optional[str]

#     # ── Sourcer outputs ───────────────────────────────────────────────────────
#     sourced_companies: List[Dict[str, Any]]
#     sourced_personas:  List[Dict[str, Any]]

#     # ── Node outputs ──────────────────────────────────────────────────────────
#     extracted_icp:      Optional[ICPAttributes]
#     filtered_companies: List[Dict[str, Any]]
#     nurture_companies:  List[Dict[str, Any]]
#     ranked_companies:   List[Dict[str, Any]]
#     ranked_personas:    List[Dict[str, Any]]

#     # ── Pipeline health ────────────────────────────────────────────────────────
#     # Set by any node to signal a fatal upstream failure that should halt
#     # downstream processing (e.g. ICP extraction failure).
#     pipeline_error:     Optional[str]
    
#     # Direct LangGraph to use our custom reducer to append data instead of replacing it
#     disqualification_log: Annotated[DisqualificationLog, reduce_disqualification_log]




























# graph/state.py

from __future__ import annotations
from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from brain.schemas import ICPAttributes


# ── Reducer Functions ─────────────────────────────────────────────────────────

def reduce_disqualification_log(
    old_log: DisqualificationLog,
    new_log: DisqualificationLog,
) -> DisqualificationLog:
    """
    Merges new disqualification records into the running log.
    Called automatically by LangGraph whenever a node returns a
    'disqualification_log' key — nodes must return a properly shaped
    DisqualificationLog dict (not a plain list).
    """
    if not old_log:
        return new_log
    if not new_log:
        return old_log

    combined_records = old_log.get("records", []) + new_log.get("records", [])

    total_eval = old_log.get("total_evaluated", 0) + new_log.get("total_evaluated", 0)
    total_pass = old_log.get("total_passed", 0)    + new_log.get("total_passed", 0)
    total_disq = old_log.get("total_disqualified", 0) + new_log.get("total_disqualified", 0)

    combined_summary = dict(old_log.get("summary", {}))
    for code, count in new_log.get("summary", {}).items():
        combined_summary[code] = combined_summary.get(code, 0) + count

    return {
        "total_evaluated":    total_eval,
        "total_passed":       total_pass,
        "total_disqualified": total_disq,
        "records":            combined_records,
        "summary":            combined_summary,
    }


# ── Audit trail ───────────────────────────────────────────────────────────────

class DisqualificationRecord(TypedDict):
    entity_type:   str            # 'company' | 'persona'
    entity_name:   str
    entity_id:     Optional[str]
    reason_code:   str            # 'BLACKLIST' | 'EXCLUDE_INDUSTRY' | 'EXCLUDE_KEYWORD' | ...
    reason_detail: str
    firm_score:    Optional[float]
    timestamp:     str            # ISO-8601 UTC
    campaign_id:   Optional[str]


class DisqualificationLog(TypedDict):
    total_evaluated:    int
    total_passed:       int
    total_disqualified: int
    records:            List[DisqualificationRecord]
    summary:            Dict[str, int]   # reason_code -> count


# ── Blacklist ─────────────────────────────────────────────────────────────────

class BlacklistConfig(TypedDict):
    # Company names or regex patterns (case-insensitive match in filter_and_gate_node)
    companies: List[str]
    # Persona LinkedIn profile URLs (normalized match in rank_personas_node)
    personas:  List[str]


# ── Main pipeline state ───────────────────────────────────────────────────────

class CampaignState(TypedDict):
    # ── Inputs ────────────────────────────────────────────────────────────────
    icp_description_text: str
    user_offering:        str
    blacklist:            BlacklistConfig
    configurable_weights: Dict[str, float]
    campaign_id:          Optional[str]

    # ── Sourcer outputs ───────────────────────────────────────────────────────
    sourced_companies: List[Dict[str, Any]]
    # sourced_personas:  List[Dict[str, Any]]

    # ── Node outputs ──────────────────────────────────────────────────────────
    extracted_icp:      Optional[ICPAttributes]
    filtered_companies: List[Dict[str, Any]]
    nurture_companies:  List[Dict[str, Any]]
    ranked_companies:   List[Dict[str, Any]]
    ranked_personas:    List[Dict[str, Any]]
    # Written by human_review_node after the interrupt() resumes.
    # Contains the apollo_ids of companies the user chose to keep.
    # If None, rank_personas_node runs on the full ranked_companies list.
    user_approved_companies: Optional[List[str]]
    # Populated by sourcer AFTER user approval, keyed by apollo_id
    sourced_personas_by_company: Optional[Dict[str, List[Dict[str, Any]]]]


    # ── Pipeline health ───────────────────────────────────────────────────────
    # Set by any node to signal a fatal upstream failure.
    # Every downstream node must check this and return {} immediately if set.
    pipeline_error: Optional[str]

    # ── Audit log (reducer-managed) ───────────────────────────────────────────
    # LangGraph calls reduce_disqualification_log on every node return that
    # includes this key. Nodes must return a full DisqualificationLog dict,
    # never a plain list.
    disqualification_log: Annotated[DisqualificationLog, reduce_disqualification_log]