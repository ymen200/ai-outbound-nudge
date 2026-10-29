# AI Outbound — Nudge (Agentic B2B Prospecting)

Multi-agent platform that turns an **ICP description** into enriched B2B leads, then hands them off to outreach.

Built during an engineering internship at **Addvocate** (AI Outbound / Nudge suite).

---

## What it does

1. **Discover** companies matching an ICP (Apollo + filters)
2. **Enrich** via web scraping (Playwright) + LLM extraction (Gemini / Groq)
3. **Score & rank** companies and personas (Qualifier)
4. **Persist** knowledge in Neo4j (graph) and campaign state in PostgreSQL / SQLite
5. **Orchestrate** the full campaign lifecycle (FastAPI + MCP)
6. **Handoff** a `FinalLeadPackage` to outreach for personalized sequences

---

## Architecture

```text
ICP (text)
   │
   ▼
Global Orchestrator (FastAPI :8100)
   ├─ MCP → Qualifier   (ICP features, ranking, re-score)
   └─ MCP → Sourcer     (Inject & Collect)
              Apollo → Playwright → LLM (LangGraph + LangChain prompts)
              → multi-source merge + confidence → Neo4j
   │
   ▼
FinalLeadPackage
   │
   ▼
Phase B — Outreach handoff (MCP)
```

| Module | Path | Role |
|--------|------|------|
| **Inject & Collect (Sourcer)** | `orchestrator/inject_collect_project/` | Company/persona discovery, enrichment, Neo4j, MCP tools |
| **Global Orchestrator** | `orchestrator/nudge-global-orchestrator/` | Campaign API, Phase A/B pipeline, MCP clients, retries |
| **Qualifier** | `orchestrator/nudge-qualifier-engine/` | ICP extraction & lead scoring |
| **Personalization / Outreach** | `orchestrator/nudge-personalization-engine/` | Sequences & messages (Phase B) |
| **Frontend** | `frontend/` | Campaign Studio UI (campaign params, results) |

Inter-agent communication uses **MCP (Model Context Protocol)** over stdio.  
The frontend talks to the orchestrator over **REST**.

---

## Key technical choices

| Tech | Why |
|------|-----|
| **LangGraph** | Branching workflows inside the Sourcer (scrape loops, company enrich, contact waterfall) |
| **LangChain** | Per-task prompt templates (`ChatPromptTemplate`); code selects the template, LangChain formats it |
| **MCP** | Standard tool interface between Qualifier / Sourcer / Outreach |
| **FastAPI** | Async campaign API with Pydantic validation & OpenAPI |
| **Neo4j** | Graph of Company–Persona–Intent + provenance |
| **PostgreSQL** | Campaign state for production concurrency (SQLite for local iteration) |
| **Playwright + Apollo + Gemini/Groq** | Structured B2B data + live website enrichment + LLM extraction |

---

## Repository layout

```text
AI_Outbound/
├── README.md
├── frontend/                          # Campaign Studio (UI)
├── documentation/                     # Extra docs (if present)
└── orchestrator/
    ├── inject_collect_project/        # Sourcer (Inject & Collect)
    ├── nudge-global-orchestrator/     # Campaign brain (FastAPI)
    ├── nudge-qualifier-engine/        # Qualifier agent
    └── nudge-personalization-engine/  # Outreach / sequences / messages
```

Each submodule has its own `README.md`, `.env.example`, and (where relevant) handover / technical docs.

---

## Prerequisites

- Python **3.11+** (3.12 recommended)
- Git
- API keys as needed: Apollo, Google Gemini / Groq
- Neo4j (for Sourcer persistence)
- PostgreSQL (recommended for orchestrator in non-local mode)
- Node not required for the vanilla HTML/JS frontend

---

## Quick start (high level)

> Detailed steps live in each module README. Below is the intended order.

### 1. Clone

```bash
git clone https://github.com/<YOUR_USERNAME>/<YOUR_REPO>.git
cd <YOUR_REPO>
```

### 2. Configure environment

Copy examples and fill secrets **locally** (never commit `.env`):

```bash
cp orchestrator/inject_collect_project/.env.example orchestrator/inject_collect_project/.env
cp orchestrator/nudge-global-orchestrator/.env.example orchestrator/nudge-global-orchestrator/.env
```

Point orchestrator MCP paths to Qualifier + Sourcer (see `nudge-global-orchestrator/.env.example`).

### 3. Sourcer (Inject & Collect)

```bash
cd orchestrator/inject_collect_project
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
# Neo4j running + .env configured
python mcp_server.py   # or follow module README
```

### 4. Global Orchestrator

```bash
cd orchestrator/nudge-global-orchestrator
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
# Optional mock mode: ORCHESTRATOR_MOCK=true
python scripts/run_api.py
# API: http://localhost:8100
```

### 5. Create a campaign

```bash
curl -X POST http://localhost:8100/campaigns \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"u1\",\"icp_description_text\":\"Insurance companies in France 500-20000 employees\",\"user_offering\":\"Outbound AI\",\"run_async\":false}"
```

More endpoints: see [`orchestrator/nudge-global-orchestrator/README.md`](orchestrator/nudge-global-orchestrator/README.md).

---

## Features highlight (Sourcer)

- Apollo company & persona discovery
- Playwright site scraping + LangGraph agentic scrape loop
- Structured LLM extraction with confidence / source citations (XAI-style)
- Multi-source merge with conflict resolution
- Contact waterfall enrichment
- Neo4j persistence with provenance
- Exposed as **MCP tools** for the Global Orchestrator

---

## Security

- **Never commit** `.env`, API keys, tokens, or database dumps
- Use `.env.example` as the only template in git
- Prefer a **private** GitHub repo until you have explicit permission to publish company work publicly

---

## Status & scope

This repository reflects internship work on the Nudge / AI Outbound stack (sourcing + orchestration).  
Some modules may still be evolving; see per-folder READMEs for known limitations (auth, CORS, deployment, etc.).

---

## License / ownership

Internship work produced in the context of **Addvocate**.  

---

## Author

**Aymen Ouerghi** — AI Engineering student (ESPRIT)  
Focus areas: agentic systems, MCP, LLM pipelines, B2B automation
