# LangGraph + MCP Integration

This document covers the architecture added on top of the existing agentic pipeline.
The original agent logic (`agents.py`, `llm_service.py`, `tools.py`, `memory.py`) is untouched.

---

## What Changed

### Before
```
main.py → PipelineOrchestrator (manual while-loop) → AgentNodes
```

### After
```
main.py → PipelineOrchestrator → LangGraph StateGraph → AgentNodes
                                                              ↑
External agents ──── MCP (SSE at /mcp) ───────────────────────┘
```

---

## LangGraph (`app/graph.py`)

The `PipelineOrchestrator`'s manual `while` loop is replaced by a `StateGraph`.

The graph has 5 nodes, each a thin wrapper around the existing `AgentNodes` static methods:

```
planner ──→ researcher ──→ strategist ──→ writer ──→ critic
   ↑                                         ↑          │
   │                                         └─REVISING─┘
   └──────────────────── PLANNING (hard retry) ──────────┘
```

Routing is handled by two conditional edge functions:
- `route_after_planner` — fans out based on what's missing in state
- `route_after_critic` — loops back to writer (soft revision), planner (hard retry), or ends

The `AgentState` Pydantic model is used directly as the LangGraph state — no wrapper needed.

### Running the graph directly
```python
from app.graph import run_pipeline
from app.models import AgentState, Status

state = AgentState(task_id="...", target_prospect="Sarah Chen", ...)
history = run_pipeline(state)  # returns List[AgentState]
```

---

## MCP Server (`app/mcp_server.py`)

Exposes the pipeline as an MCP-compatible tool server. Any agent that speaks MCP
(Claude Desktop, another LangGraph agent, Kiro, etc.) can call this system as a tool.

### Tools

| Tool | Description |
|---|---|
| `generate_outreach` | Run the full pipeline for a prospect, returns message + score |
| `check_prospect` | Look up a prospect in memory, check do-not-contact status |
| `mark_do_not_contact` | Flag a prospect so the pipeline refuses to generate for them |

### Connecting via SSE (HTTP)

The MCP server is mounted at `/mcp` on the same FastAPI process.

Add to your `mcp.json` (Kiro / Claude Desktop):
```json
{
  "mcpServers": {
    "agentic-outreach": {
      "url": "http://localhost:8000/mcp",
      "transport": "sse"
    }
  }
}
```

### Running as standalone stdio server

For agents that connect via stdio (e.g. spawned as a subprocess):
```bash
python -m app.mcp_server
```

---

## Agent-to-Agent Example

An external LangGraph agent can use this system as a tool:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({
    "outreach": {"url": "http://localhost:8000/mcp", "transport": "sse"}
}) as client:
    tools = await client.get_tools()
    # tools now includes generate_outreach, check_prospect, mark_do_not_contact
    result = await tools["generate_outreach"].ainvoke({
        "target_prospect": "Sarah Chen",
        "target_company": "Ramp",
        "company_name": "SalesForce AI",
        "offer_name": "SDR Efficiency Audit",
    })
```

---

## Running

```bash
# Install new deps
pip install -r requirements.txt

# Start the server (FastAPI + MCP SSE both on port 8000)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The existing `/api/generate` and `/api/generate/simple` endpoints work exactly as before.
