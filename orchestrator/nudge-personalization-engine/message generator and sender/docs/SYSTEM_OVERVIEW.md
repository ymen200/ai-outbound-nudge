# Agentic Writer System — Overview

## What It Is

A FastAPI-based multi-agent system that generates personalized sales outreach messages. You send it a prospect, a company, a channel, and an offer — it runs a pipeline of AI agents and returns a ready-to-send message with a quality score.

The LLM backbone is **Google Gemini 2.5 Flash**.

---

## Architecture

```
HTTP Request
     │
     ▼
  main.py  (FastAPI)
     │
     ▼
PipelineOrchestrator  (orchestrator.py)
     │
     ▼  loops until COMPLETE or FAILED
  AgentNodes  (agents.py)
  ┌──────────────────────────────────────┐
  │  Planner → Researcher → Strategist  │
  │       → Writer → Critic             │
  │            ↑_______↓  (revision loop)│
  └──────────────────────────────────────┘
     │
     ▼
  LLMService  (llm_service.py)   ← Gemini API calls
  ResearchTools  (tools.py)      ← LinkedIn / news / CRM (mock or real)
  MemoryService  (memory.py)     ← Per-prospect + global learning memory
```

---

## The Pipeline — Step by Step

### 1. Planner
Looks at the current `AgentState` and decides what's missing. It sets the next `status` flag so the orchestrator knows which agent to call next. It doesn't call any LLM — it's pure routing logic.

### 2. Researcher
- Loads the prospect's memory record (or creates one if first time).
- Hard-stops if the prospect is marked `do_not_contact`.
- Fetches LinkedIn posts, company news, and CRM history (currently mock data, real API stubs are in place).
- Stores everything in `state.memory` for downstream agents.

### 3. Strategist
- Calls Gemini to analyze the research signals and pick the best **hook** (the angle of attack).
- Calls Gemini again to build a full **Strategy** object: primary hook, secondary hook, angle, tone, CTA style.
- Avoids hooks and angles already used with this prospect (pulled from memory).

### 4. Writer
- Calls Gemini to write the actual message using the strategy.
- Respects channel-specific length limits (e.g. SMS ≤ 160 chars, LinkedIn DM ≤ 300).
- Returns the message body, optional subject line, and a **sentence-level attribution** breakdown (which sentence serves which purpose and why).
- Can also be called in **revision mode** — if the Critic sends it back with feedback, the Writer revises the existing draft instead of starting fresh.

### 5. Critic
- Calls Gemini to score the message 0–100.
- Also runs rule-based checks: banned phrases, overpersonalization detection.
- **Decision logic:**
  - Score passes (`valid=True`) → mark `COMPLETE`, save to memory.
  - Score fails but has fixable suggestions + retries left → set status to `REVISING`, send feedback back to the Writer.
  - Score fails badly or retries exhausted → `FAILED` or full restart from Planner.

---

## Retry / Revision Loop

The system supports up to `MAX_ITERATIONS` (default: 3) attempts. There are two types of retries:

- **Soft revision**: Critic sends specific feedback to the Writer, which revises the existing draft. State is preserved.
- **Hard retry**: Strategy and draft are cleared, the whole pipeline restarts from Planner.

---

## Memory System (`memory.py`)

Three independent memory stores, all backed by an in-memory dict (swappable to Redis/Postgres without changing the interface):

| Store | What it tracks |
|---|---|
| `ProspectMemoryService` | Per-prospect contact history, hooks used, angles tried, do-not-contact flag |
| `LearningMemoryService` | Global stats: avg quality score, channel/stage/template reply rates |
| `OfferMemoryService` | Per-offer usage stats, best channels, best angles |

Memory is read at the **Researcher** step and written at the **Critic** step (only on success).

---

## LLM Service (`llm_service.py`)

All Gemini calls go through `LLMService`. It has four public methods:

| Method | Purpose |
|---|---|
| `analyze_research_signals` | Pick the best hooks from raw signals |
| `create_strategy` | Build the full messaging strategy |
| `write_message` | Write the actual outreach message |
| `validate_message` | Score and critique the message |

Each method builds a structured plain-English prompt from the input objects (personality block, company block, offer block, channel rules, memory context) and parses the JSON response using `json5` for tolerance against sloppy LLM output.

---

## Data Models (`models.py`)

The core state object is `AgentState` — it travels through every agent and accumulates data:

```
AgentState
├── target_prospect / target_company / prospect_role
├── channel / intent / stage
├── personality        ← tone, banned phrases, urgency, humor levels, etc.
├── company_details    ← elevator pitch, value props, social proof
├── selected_offer     ← what's being pitched, pain points, CTA
├── research_signals   ← List[Signal] from Researcher
├── strategy           ← Strategy from Strategist
├── draft              ← MessageDraft from Writer (body + sentence attribution)
├── validation         ← Validation from Critic (score, warnings, fixes)
├── memory             ← Dict for passing data between agents
├── iteration_count    ← tracks retries
└── llm_calls          ← full log of every LLM call made
```

---

## API Endpoints

| Endpoint | Returns |
|---|---|
| `GET /` | Health check + config info |
| `POST /api/generate` | Full pipeline history (every `AgentState` snapshot) |
| `POST /api/generate/simple` | Just the final message, subject, score, and warnings |

---

## Configuration (`.env`)

Key settings:

- `GOOGLE_API_KEY` — required, your Gemini key
- `USE_MOCK_DATA=true` — uses fake LinkedIn/news/CRM data (flip to false when real APIs are wired)
- `MIN_QUALITY_SCORE=80` — minimum score for a message to pass validation
- `MAX_ITERATIONS=3` — max retry attempts before giving up
- `GEMINI_MODEL=gemini-2.5-flash` — model to use

---

## Running It

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## What's Stubbed / Not Yet Wired

- Real LinkedIn API (`ResearchTools.fetch_linkedin_posts`)
- Real News API (`ResearchTools.fetch_company_news`)
- Real CRM database (`ResearchTools.get_crm_history`)
- Reply tracking (the `mark_replied` memory method exists but nothing calls it yet)
- Persistent memory (currently in-process dict, lost on restart — Redis/Postgres swap is designed in)
- Auto-send feature (`ENABLE_AUTO_SEND` flag exists but isn't implemented)
