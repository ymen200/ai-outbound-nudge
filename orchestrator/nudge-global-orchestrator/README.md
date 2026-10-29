# Nudge Global Orchestrator

The **Nudge Global Orchestrator** is the top-level brain of the outbound sales system. It runs two phases:

- **Phase A** — Lead discovery: extracts ICP, fetches companies, ranks them, fetches personas, enriches contacts, and assembles a `FinalLeadPackage`.
- **Phase B** — Outreach handoff: takes the final lead package and hands it to the [Outreach-Project](../../Outreach-Project) via **stdio MCP** to generate personalized outreach sequences + messages.

All inter-module communication uses **MCP (Model Context Protocol)** over stdio — no REST calls.

---

## Architecture

```
                         Global Orchestrator (port 8100)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
              Qualifier   Sourcer   Outreach Orchestrator
              (MCP)       (MCP)     (MCP stdio via run_mcp.py)
                                          │
                                    ┌─────┴─────┐
                                    ▼           ▼
                              Sequence Gen   Message Gen
                              (port 8001)    (port 8000)
                                    │
                                    ▼
                              Temporal (7233)
```

### Phase A — Lead Discovery (Qualifier + Sourcer via MCP)

1. **Qualifier** `start_campaign` → extracts ICP features from raw text
2. Persist raw ICP + features in orchestrator DB
3. **Sourcer** `orchestrator_fetch_companies` (industry, region, size)
4. **Qualifier** `resume_with_companies` → firmographic ranking
5. **Sourcer** `orchestrator_fetch_intent` for top companies
6. **Qualifier** `rescore_with_intent` → updated scores with intent signals
7. **Sourcer** `orchestrator_fetch_personas_with_signals`
8. **Qualifier** `resume_with_approvals` → ranked personas
9. Select single best lead (company score × weight + persona score × weight)
10. **Sourcer** `orchestrator_enrich_contacts` → email / phone enrichment
11. Structure `FinalLeadPackage[]` and store in DB

### Phase B — Outreach Handoff (Outreach Orchestrator via stdio MCP)

1. Build a flat MCP payload from the `FinalLeadPackage` + campaign config
2. Call `run_outreach_pipeline` via stdio MCP → starts the Outreach Orchestrator
3. The Outreach Orchestrator calls the Sequence Generator (port 8001) which:
   - Detects language + timezone
   - Generates a multi-step sequence with Gemini
   - Generates JIT messages per step via the Message Generator (port 8000)
   - Pauses for human approval
4. Poll for outreach threads → approve → dispatch to Temporal

**Key difference from Phase A**: Phase B uses a **`run_mcp.py` wrapper** (not the bare `app/mcp_server.py`) because the Outreach Orchestrator's MCP server uses relative imports that require package context.

---

## Quick Start

### Prerequisites

- Python 3.12+
- Virtual environments in `nudge-global-orchestrator/`, and each Outreach-Project submodule
- `.env` files configured (copy `.env.example` → `.env`)
- For Phase B: Outreach-Project services running (Temporal, Message Generator, Sequence Generator)

### Setup

```bash
cd nudge-global-orchestrator
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
copy .env.example .env         # Windows
# cp .env.example .env          # Linux/Mac
```

### Mock Mode (Phase A only, no live MCP)

Set in `.env`:
```
ORCHESTRATOR_MOCK=true
```

```bash
python scripts/run_api.py
```

Create a campaign:
```bash
curl -X POST http://localhost:8100/campaigns \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","icp_description_text":"Insurance companies in France 500-20000 employees","user_offering":"LeadPulse outbound AI","run_async":false}'
```

### Live Mode (Phase A + Phase B with real services)

1. Start Outreach-Project services:
   ```bash
   cd Outreach-Project
   python main.py    # starts Temporal, Message Gen, Sequence Gen, Outreach Orch
   ```

2. Start the global orchestrator:
   ```bash
   cd nudge-global-orchestrator
   venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8100
   ```

3. Create a campaign + trigger outreach:
   ```bash
   # Create campaign (mock Phase A, real Phase B)
   curl -X POST http://localhost:8100/campaigns \
     -H "Content-Type: application/json" \
     -d '{"user_id":"u1","run_async":false,"auto_start_outreach":false}'

   # Start outreach for the campaign
   curl -X POST http://localhost:8100/campaigns/{campaign_id}/outreach

   # Poll for threads (may take 1-3 minutes for Gemini)
   curl http://localhost:8100/campaigns/{campaign_id}/outreach

   # Approve the thread
   curl -X POST http://localhost:8100/campaigns/{campaign_id}/outreach/{thread_id}/approve \
     -H "Content-Type: application/json" \
     -d '{"approved":true}'
   ```

### Real end-to-end smoke test

```bash
cd nudge-global-orchestrator
venv\Scripts\python scripts/test_outreach_real.py
```

This script automatically:
- Kills zombie processes on ports 8000/8001/8002/7233/8100
- Starts all Outreach-Project services
- Starts the global orchestrator
- Creates a campaign, starts outreach, polls for threads, approves, and verifies dispatch
- Preserves logs on failure for debugging

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/campaigns` | Start Phase A (async or sync) |
| `GET` | `/campaigns/{id}` | Campaign status, artifacts, packages, outreach threads |
| `POST` | `/campaigns/{id}/outreach` | Start Phase B outreach for a campaign |
| `GET` | `/campaigns/{id}/outreach` | List outreach threads |
| `POST` | `/campaigns/{id}/outreach/{thread_id}/approve` | Approve or reject an outreach sequence |
| `GET` | `/campaigns/{id}/outreach/observability` | Aggregated observability from outreach modules |
| `GET` | `/health` | Health check |
| `GET` | `/` | Service info |

See [app/api/README.md](app/api/README.md) for detailed request/response schemas.

---

## Configuration

All config is in `.env` (see `.env.example` for full reference). Key settings:

### Phase A — MCP paths
| Variable | Default | Description |
|----------|---------|-------------|
| `QUALIFIER_MCP_PATH` | `../nudge-qualifier-engine/.../run.py` | Path to qualifier MCP server |
| `SOURCER_MCP_PATH` | `../inject_collect_project/mcp_server.py` | Path to sourcer MCP server |
| `QUALIFIER_PYTHON` | (current python) | Python for qualifier subprocess |
| `SOURCER_PYTHON` | (current python) | Python for sourcer subprocess |
| `ORCHESTRATOR_MOCK` | `false` | Use mock data instead of live MCP |

### Phase B — Outreach MCP
| Variable | Default | Description |
|----------|---------|-------------|
| `OUTREACH_MCP_PATH` | `../../Outreach-Project/outreach orchestrator/run_mcp.py` | Path to Outreach MCP wrapper |
| `OUTREACH_PYTHON` | (current python) | Python for Outreach MCP subprocess |
| `OUTREACH_TIMEOUT` | `120.0` | Max seconds per MCP tool call |
| `OUTREACH_MAX_RETRIES` | `2` | Retry attempts on failure |
| `OUTREACH_RETRY_BACKOFF_BASE` | `2.0` | Base for exponential backoff (delay = base × 2^attempt) |
| `OUTREACH_AUTO_START` | `false` | Auto-start Phase B when Phase A completes |

### Phase B — Outreach defaults
| Variable | Default | Description |
|----------|---------|-------------|
| `OUTREACH_DEFAULT_SENDER_COMPANY` | `My Company` | Default sender company |
| `OUTREACH_DEFAULT_OFFER_NAME` | `Default Offer` | Default offer name |
| `OUTREACH_DEFAULT_APPROVAL_MODE` | `per_sequence` | per_sequence / per_step / per_step_and_message |
| `OUTREACH_DEFAULT_USE_NATIVE_LANGUAGE` | `false` | Generate in prospect's language |
| `OUTREACH_DEFAULT_DEBUG_MODE` | `true` | Bypass memory reads/writes |

---

## MCP Client Resilience

The `McpStdioClient` (shared by Qualifier, Sourcer, and Outreach clients) includes:

1. **Timeout** — every tool call has a configurable timeout (default 120s). If exceeded, a `TimeoutError` is raised with a descriptive message. Prevents hung Gemini calls from blocking the orchestrator forever.

2. **Retry + exponential backoff** — on any exception (timeout, connection closed, subprocess crash), the client retries up to `max_retries` times with exponential backoff (`delay = base × 2^attempt`). This handles transient failures like the Outreach Orchestrator being temporarily unreachable.

3. **FileNotFoundError guard** (Outreach only) — `OutreachClient` raises immediately if `OUTREACH_MCP_PATH` doesn't exist, and warns if the path isn't `run_mcp.py`.

See [app/mcp_clients/README.md](app/mcp_clients/README.md) for implementation details.

---

## Testing

### Unit tests (no subprocess, no network)
```bash
venv\Scripts\python -m pytest tests/test_outreach_client.py tests/test_outreach_mapping.py -v
```

### Mock integration test (no real services)
```bash
venv\Scripts\python scripts/test_outreach_integration.py
```

### Real end-to-end smoke test (requires GOOGLE_API_KEY + all services)
```bash
venv\Scripts\python scripts/test_outreach_real.py
```

---

## Project Layout

```
nudge-global-orchestrator/
  app/
    api/           # FastAPI routes — see app/api/README.md
    config.py      # Pydantic settings (all .env variables)
    domain/        # ICP mapping, company/persona normalization, FinalLeadPackage builder
    mcp_clients/   # MCP stdio clients — see app/mcp_clients/README.md
    pipeline/      # Phase A stage machine + Phase B outreach — see app/pipeline/README.md
    store/         # SQLite persistence — see app/store/README.md
    usage_report.py
  scripts/
    run_api.py
    smoke_live.py
    test_outreach_integration.py   # mock MCP integration test
    test_outreach_real.py          # real end-to-end smoke test
  tests/
    test_outreach_client.py        # OutreachClient + McpStdioClient tests
    test_outreach_mapping.py       # payload mapping + signal normalization tests
    test_phase_a_mock.py           # Phase A domain + mock tests
    test_usage_report.py           # usage report aggregation tests
  .env.example
  requirements.txt
  README.md (this file)
```

---

## Database

The orchestrator currently uses **SQLite** for campaign persistence (see [app/store/README.md](app/store/README.md)).

**PostgreSQL migration is planned** — the `CampaignStore` class is the single interface that will be swapped. DBeaver will be used for database management. This is a separate ticket.

---

## Known Limitations

- **No authentication** on the API — anyone who can reach port 8100 can create/approve campaigns
- **CORS `allow_origins=["*"]`** — should be locked down for production
- **SQLite** — will contend under high concurrency (Postgres migration planned)
- **No Dockerfile** — no containerized deployment path yet
- **`keep_alive=False`** — each MCP tool call spawns a new Python subprocess (~2-7s overhead)
- **No subprocess stderr capture** — MCP server crash tracebacks go to the void
