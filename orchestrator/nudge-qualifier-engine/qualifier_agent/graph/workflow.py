"""
graph/workflow.py
─────────────────
Compiles the Strategic Qualifier LangGraph pipeline.

Node execution order:
  1. extract_icp            — parse raw ICP text → ICPAttributes
  1.5 company_sourcing      — interrupt: request companies from sourcer agent
  2. normalize_company_data — clean/normalize raw vendor company dicts
  3. filter_and_gate        — hard gates (blacklist, must-have, exclude)
  4. score_and_rank         — geo filter + firmographic scoring + intent analysis
  4.5 human_review          — interrupt: frontend presents ranked companies, user approves
  5. rank_personas          — persona scoring on approved companies only

The graph has two interrupt points:
  1. company_sourcing (Node 1.5) — pauses after ICP extraction, returns icp_filters to orchestrator
     Orchestrator resumes with: Command(resume=<list of raw company dicts>)
  2. human_review (Node 4.5) — pauses after company ranking, frontend shows ranked companies
     Orchestrator resumes with: Command(resume=<list of approved apollo_ids>)
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from langgraph.graph import StateGraph, END
import os
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


from graph.state import CampaignState
from graph.nodes import (
    extract_icp_node,
    normalize_company_data_node,
    filter_and_gate_node,
    score_and_rank_node,
    company_sourcing_node,   
    human_review_node,
    rank_personas_node,
)


# ── Graph definition ──────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    """
    Construct and wire the StateGraph.
    Separated from compilation so the same graph definition can be compiled
    with different checkpointers (e.g. SQLite for prod, MemorySaver for tests).
    """
    workflow = StateGraph(CampaignState)

    # Register nodes
    workflow.add_node("extract_icp",            extract_icp_node)
    workflow.add_node("company_sourcing", company_sourcing_node)

    workflow.add_node("normalize_company_data",  normalize_company_data_node)
    workflow.add_node("filter_and_gate",         filter_and_gate_node)
    workflow.add_node("score_and_rank",          score_and_rank_node)
    workflow.add_node("human_review",            human_review_node)
    workflow.add_node("rank_personas",           rank_personas_node)

    # Execution sequence
    workflow.set_entry_point("extract_icp")
    workflow.add_edge("extract_icp",      "company_sourcing")
    workflow.add_edge("company_sourcing", "normalize_company_data")
    workflow.add_edge("normalize_company_data", "filter_and_gate")
    workflow.add_edge("filter_and_gate",        "score_and_rank")
    workflow.add_edge("score_and_rank",         "human_review")
    workflow.add_edge("human_review",           "rank_personas")
    workflow.add_edge("rank_personas",          END)

    return workflow


# ── Pipeline factory ──────────────────────────────────────────────────────────

# @contextmanager
# def get_pipeline(db_path: str = "checkpoints.db"):
#     """
#     Context manager that yields a compiled pipeline with a SQLite checkpointer.

#     The checkpointer is required for interrupt() to work — LangGraph needs
#     somewhere to persist graph state between the pause and the resume.

#     Usage:
#         with get_pipeline() as pipeline:
#             config = {"configurable": {"thread_id": campaign_id}}
#             pipeline.invoke(initial_state, config)
#             # graph pauses at human_review interrupt()
#             pipeline.invoke(Command(resume=approved_ids), config)

#     The context manager ensures the SQLite connection is properly closed
#     when the pipeline is no longer needed, preventing connection leaks.
#     """
#     with SqliteSaver.from_conn_string(db_path) as checkpointer:
#         graph = _build_graph()
#         yield graph.compile(checkpointer=checkpointer)



@contextmanager
def get_pipeline():
    """
    Context manager that yields a compiled pipeline with a Postgres checkpointer.

    The checkpointer is required for interrupt() to work — LangGraph needs
    somewhere to persist graph state between the pause and the resume.
    Using Postgres (instead of SQLite) means the paused state survives
    server restarts/redeploys and is reachable from any worker process,
    which matters for multi-day human-review pauses.

    Usage:
        with get_pipeline() as pipeline:
            config = {"configurable": {"thread_id": campaign_id}}
            pipeline.invoke(initial_state, config)
            # graph pauses at human_review interrupt()
            pipeline.invoke(Command(resume=approved_ids), config)
    """
    db_url = os.environ["DATABASE_URL"]
    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        graph = _build_graph()
        yield graph.compile(checkpointer=checkpointer)


def get_test_pipeline():
    """
    Returns a compiled pipeline without a checkpointer for unit tests.
    interrupt() will not work in this mode — use only for node-level tests
    that don't exercise the human review gate.
    """
    from langgraph.checkpoint.memory import MemorySaver
    graph = _build_graph()
    return graph.compile(checkpointer=MemorySaver())