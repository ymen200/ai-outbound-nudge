# TODO — LangGraph + MCP Integration

## Done
- [x] Replace manual orchestrator while-loop with LangGraph StateGraph (`app/graph.py`)
- [x] Wire all existing AgentNodes as graph nodes — zero logic changed
- [x] Conditional routing (planner fan-out, critic revision loop) via LangGraph edges
- [x] MCP server exposing 3 tools: `generate_outreach`, `check_prospect`, `mark_do_not_contact`
- [x] MCP server mounted as SSE endpoint at `/mcp` alongside FastAPI
- [x] `PipelineOrchestrator` public interface preserved — `main.py` unchanged

---

## Next Up

### LangGraph
- [ ] Add LangGraph checkpointing (swap `compile()` for `compile(checkpointer=...)`)
      so pipeline state survives server restarts and can be resumed mid-run
- [ ] Expose graph visualization endpoint (`/graph/diagram`) using `pipeline.get_graph().draw_mermaid()`
- [ ] Add async node execution — current nodes are sync, LangGraph supports async natively
- [ ] Add LangGraph Studio config (`langgraph.json`) for visual debugging

### MCP / Agent-to-Agent
- [ ] Add `get_learning_stats` tool — expose `LearningMemoryService` data so orchestrating agents
      can see which channels/templates are performing best before calling `generate_outreach`
- [ ] Add `get_offer_performance` tool — let agents pick the best offer before generating
- [ ] Add `batch_generate` tool — generate for a list of prospects in one MCP call
- [ ] Add authentication to the `/mcp` SSE endpoint (API key header check)
- [ ] Write an example LangGraph agent that uses this system as an MCP tool
      (`examples/caller_agent.py`) — demonstrates true agent-to-agent flow
- [ ] Publish MCP server config (`mcp.json`) so Kiro / Claude Desktop can connect directly

### Research Tools (Real APIs)
- [ ] Wire real LinkedIn API in `ResearchTools.fetch_linkedin_posts`
- [ ] Wire real News API in `ResearchTools.fetch_company_news`
- [ ] Wire real CRM in `ResearchTools.get_crm_history`

### Memory
- [x] Swap `_InMemoryStore` for Redis (`redis-py`) — interface already designed for this
- [x] Add reply tracking — call `MemoryService.prospects.mark_replied()` when a reply comes in via `POST /api/reply`
- [x] Feed reply data back into `LearningMemoryService` to improve hook/angle selection

### Infra
- [x] Add `Dockerfile` + `docker-compose.yml` (app + Redis)
- [x] Add Redis service to docker-compose when memory persistence is wired
