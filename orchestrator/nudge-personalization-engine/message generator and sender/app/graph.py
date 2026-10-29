"""
LangGraph pipeline — replaces PipelineOrchestrator's manual while-loop.

LangGraph requires state to be a TypedDict (it merges state dicts between nodes).
We keep AgentState as the Pydantic model for the rest of the app — the graph
works on a plain dict and we convert at the boundaries.

Flow:
    planner → researcher → strategist → writer → critic
                                              ↑         |
                                              └─REVISING─┘  (soft revision)
                                              (hard retry)
    planner ←──────────────────────────── critic
"""

from typing import List, Any
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END

from .models import AgentState, Status
from .agents import AgentNodes


# ------------------------------------------------------------------
# LangGraph state schema — a flat dict mirror of AgentState fields.
# LangGraph merges returned dicts into this schema between nodes.
# We convert to/from AgentState at node boundaries.
# ------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    task_id: str
    status: str
    target_prospect: str
    target_company: str
    prospect_role: Any
    channel: Any
    intent: Any
    stage: Any
    personality: Any
    company_details: Any
    selected_offer: Any
    memory: Any
    research_signals: Any
    strategy: Any
    draft: Any
    validation: Any
    next_action: Any
    iteration_count: int
    max_iterations: int
    user_feedback: Any
    language: Any


def _to_graph_state(state: AgentState) -> GraphState:
    """Pydantic model → plain dict for LangGraph."""
    return state.model_dump()


def _from_graph_state(data: dict) -> AgentState:
    """Plain dict → Pydantic model for agent nodes."""
    return AgentState(**data)


# ------------------------------------------------------------------
# Node wrappers — convert dict→AgentState, call agent, convert back
# ------------------------------------------------------------------

def node_planner(data: GraphState) -> GraphState:
    state = _from_graph_state(data)
    result = AgentNodes.planner(state)
    return _to_graph_state(result)

def node_researcher(data: GraphState) -> GraphState:
    state = _from_graph_state(data)
    result = AgentNodes.researcher(state)
    return _to_graph_state(result)

def node_strategist(data: GraphState) -> GraphState:
    state = _from_graph_state(data)
    result = AgentNodes.strategist(state)
    return _to_graph_state(result)

def node_writer(data: GraphState) -> GraphState:
    state = _from_graph_state(data)
    result = AgentNodes.writer(state)
    return _to_graph_state(result)

def node_critic(data: GraphState) -> GraphState:
    state = _from_graph_state(data)
    result = AgentNodes.critic(state)
    return _to_graph_state(result)


# ------------------------------------------------------------------
# Routing functions
# ------------------------------------------------------------------

def route_after_planner(data: GraphState) -> str:
    status = data.get("status")
    if status == Status.FAILED.value:
        return END
    mapping = {
        Status.RESEARCHING.value:  "researcher",
        Status.STRATEGIZING.value: "strategist",
        Status.WRITING.value:      "writer",
        Status.VALIDATING.value:   "critic",
        Status.COMPLETE.value:     END,
    }
    return mapping.get(status, END)


def route_after_critic(data: GraphState) -> str:
    status = data.get("status")
    if status in (Status.COMPLETE.value, Status.FAILED.value, Status.AWAITING_HUMAN.value):
        return END
    if status == Status.REVISING.value:
        return "writer"
    if status == Status.PLANNING.value:
        return "planner"
    return END


# ------------------------------------------------------------------
# Build and compile the graph
# ------------------------------------------------------------------

def build_graph() -> Any:
    graph = StateGraph(GraphState)

    graph.add_node("planner",    node_planner)
    graph.add_node("researcher", node_researcher)
    graph.add_node("strategist", node_strategist)
    graph.add_node("writer",     node_writer)
    graph.add_node("critic",     node_critic)

    graph.set_entry_point("planner")

    graph.add_conditional_edges("planner", route_after_planner, {
        "researcher":  "researcher",
        "strategist":  "strategist",
        "writer":      "writer",
        "critic":      "critic",
        END:           END,
    })

    graph.add_edge("researcher", "strategist")
    graph.add_edge("strategist", "writer")
    graph.add_edge("writer",     "critic")

    graph.add_conditional_edges("critic", route_after_critic, {
        "writer":  "writer",
        "planner": "planner",
        END:       END,
    })

    return graph.compile()


pipeline = build_graph()


# ------------------------------------------------------------------
# Public run function — returns List[AgentState] same as before
# ------------------------------------------------------------------

def run_pipeline(initial_state: AgentState) -> List[AgentState]:
    """
    Run the full graph and return a list of AgentState snapshots per step.
    Same return shape as the old PipelineOrchestrator.run_full_pipeline().
    """
    history: List[AgentState] = [initial_state.model_copy(deep=True)]
    initial_dict = _to_graph_state(initial_state)

    for step_output in pipeline.stream(initial_dict):
        # step_output is {node_name: updated_state_dict}
        for _node_name, state_dict in step_output.items():
            history.append(_from_graph_state(state_dict))

    return history
