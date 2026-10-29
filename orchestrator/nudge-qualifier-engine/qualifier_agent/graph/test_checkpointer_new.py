"""
test_checkpointer.py
────────────────────
Minimal, standalone script to verify Step 1: checkpointer setup works.

This does NOT touch your real pipeline files. It builds a tiny fake
3-node graph with the same compile() pattern you'll use in workflow.py,
so you can confirm the checkpointer works in your environment before
we wire it into the real CampaignState pipeline.

Run with:
    pip install langgraph langgraph-checkpoint-sqlite
    python test_checkpointer.py

Expected output: the graph runs node_a -> node_b -> node_c and prints
the final state. After running, a file called "checkpoints.db" should
appear in the same folder.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver


# A tiny stand-in for CampaignState — just enough to prove the wiring works.
class TestState(TypedDict):
    log: list[str]


def node_a(state: TestState) -> dict:
    print("Running node_a")
    return {"log": state.get("log", []) + ["node_a ran"]}


def node_b(state: TestState) -> dict:
    print("Running node_b")
    return {"log": state.get("log", []) + ["node_b ran"]}


def node_c(state: TestState) -> dict:
    print("Running node_c")
    return {"log": state.get("log", []) + ["node_c ran"]}


# ── Build the graph, same shape as your real workflow.py ──────────────────
workflow = StateGraph(TestState)

workflow.add_node("node_a", node_a)
workflow.add_node("node_b", node_b)
workflow.add_node("node_c", node_c)

workflow.set_entry_point("node_a")
workflow.add_edge("node_a", "node_b")
workflow.add_edge("node_b", "node_c")
workflow.add_edge("node_c", END)

# ── Run it ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    config = {"configurable": {"thread_id": "test-thread-1"}}
    
    # Use from_conn_string and enter the context manager to get the instance
    checkpointer_cm = SqliteSaver.from_conn_string("checkpoints.db")
    with checkpointer_cm as checkpointer:
        test_pipeline = workflow.compile(checkpointer=checkpointer)
        result = test_pipeline.invoke({"log": []}, config=config)

    print("\nFinal state:")
    print(result)

    print(
        "\nIf you see node_a/node_b/node_c all ran above, and a "
        "'checkpoints.db' file now exists in this folder, Step 1 works."
    )
