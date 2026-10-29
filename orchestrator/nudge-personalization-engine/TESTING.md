# Testing Guide — Outreach Project

This document is the single source of truth for how to run, test, and manually verify the Outreach Project system. It assumes zero prior familiarity with the codebase.

---

## 1. System Overview

The system is a **B2B outreach pipeline** that generates personalized multi-step engagement sequences (email, LinkedIn) for prospects. It is composed of three modules:

### Message Generator (port 8000)

Generates a single personalized outreach message (email or LinkedIn DM) for a given prospect, stage, and intent. Uses a multi-agent LLM pipeline (planner → researcher → strategist → writer → critic) powered by Google Gemini. Also handles actual message sending (Gmail SMTP, LinkedIn via UniPile).

### Sequence Generator (port 8001)

Generates a **multi-step outreach sequence** (e.g., "LinkedIn connect → wait 3 days → email → wait 5 days → follow-up email"). Calls Gemini to produce the sequence strategy, enforces business-hour scheduling via a timezone-aware sandbox, then calls the Message Generator for per-step message creation. Pauses before final dispatch for human approval (HITL — Human-In-The-Loop).

**Default sequence length:** When the caller does not specify `max_touches`, the system defaults to a maximum of `DEFAULT_MAX_TOUCHES` (default: 5, configurable via environment variable). This is enforced server-side — sequences exceeding this limit are rejected and retried. Callers can override per-request by passing an explicit `max_touches` value.

### Outreach Orchestrator (port 8002)

Coordinates the Sequence Generator and Message Generator. Exposes a single `/api/run` endpoint that runs the full pipeline end-to-end. Also exposes an **MCP server** (Model Context Protocol — a standard protocol for agent-to-agent communication, using Server-Sent Events for transport) so an external "global orchestrator" agent can control the system.

### How they talk to each other

- **REST (HTTP)**: The Orchestrator calls the Sequence Generator and Message Generator via standard HTTP REST endpoints. The Sequence Generator also calls the Message Generator via REST for per-step message generation.
- **MCP (SSE)**: Each of the Message Generator and Orchestrator mounts an MCP server as an ASGI sub-app at `/mcp`. This allows external AI agents to discover and invoke system capabilities using the Model Context Protocol. MCP uses Server-Sent Events (SSE) for transport — the agent opens a persistent SSE connection, then sends JSON-RPC messages over POST.

---

## 2. How to Start Everything

### Prerequisites

- **Python 3.12** (each module has its own virtual environment)
- **Google Gemini API key** — required for sequence/message generation. Get one at https://makersuite.google.com/app/apikey
- **Temporal CLI** (optional) — needed only if you want to test the actual Temporal dispatch step. Install with `winget install temporalio.cli`

### Environment files

Each module reads its own `.env` file from its own directory. Copy the `.env.example` files and fill in your API key:

| Module | `.env` location | Required keys |
|---|---|---|
| Message Generator | `message generator and sender/.env` | `GOOGLE_API_KEY` |
| Sequence Generator | `sequence generator/.env` | `GOOGLE_API_KEY` |
| Outreach Orchestrator | `outreach orchestrator/.env` | (no API key needed — it proxies to the other two) |

The orchestrator's `DEBUG_MODE=true` (default) propagates to both modules at runtime, disabling memory reads/writes for deterministic testing.

### Start commands

**Option A — One command starts everything (recommended):**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project"
.\venv\Scripts\activate.bat
python main.py
```
This launches all three services (Message Generator on 8000, Sequence Generator on 8001, Orchestrator on 8002) plus the Temporal Worker in separate subprocesses, with live log streaming prefixed by service name. Press Ctrl+C to stop all.

**Option B — Separate terminals (for debugging individual services):**

Open **three separate terminals** (or use `cmd /k` to keep them visible):

**Terminal 1 — Message Generator:**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\message generator and sender"
.\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — Sequence Generator:**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
.\venv\Scripts\activate.bat
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001
```

**Terminal 3 — Outreach Orchestrator:**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\outreach orchestrator"
..\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

**Optional — Temporal dev server** (needed only for real dispatch testing):
```powershell
temporal server start-dev
```

### Verify everything is running

| Service | Health check | Swagger UI |
|---|---|---|
| Message Generator | `GET http://localhost:8000/` | `http://localhost:8000/docs` |
| Sequence Generator | `GET http://localhost:8001/health` | `http://localhost:8001/docs` |
| Outreach Orchestrator | `GET http://localhost:8002/api/health` | `http://localhost:8002/docs` |

---

## 3. Automated Tests

### Sequence Generator

Each module has its own virtual environment. The Sequence Generator and Message Generator use their **own** `venv/`. The Orchestrator tests use the **root** `venv/` at the project root.

**Fast unit suite (no API calls, no cost):**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
.\venv\Scripts\python.exe -m pytest tests/ -k "not integration" -v
```
- **Baseline: 109 passed**, ~5 seconds
- Test files: `test_inmail_enforcement.py`, `test_language_detection.py`, `test_message_field_roundtrip.py`, `test_outreach_step.py`, `test_regression_cleanup.py`, `test_retry_and_gemini.py`, `test_sandbox.py`, `test_user_feedback.py`

**Integration suite (calls real Gemini API — costs money, takes ~15s):**
```powershell
.\venv\Scripts\python.exe -m pytest tests/ -k "integration" -v
```
- **Baseline: 8 passed**, ~15 seconds
- Requires valid `GOOGLE_API_KEY` in `sequence generator/.env`
- Test files: `test_paused_threads_integration.py` (4 tests — real graph resume path), `test_concurrency_integration.py` (4 tests — thread isolation + feedback scoping)

**Both together:**
```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```
- **Baseline: 117 passed** (109 unit + 8 integration)

### Message Generator

**Fast unit suite:**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\message generator and sender"
.\venv\Scripts\python.exe -m pytest tests/ -v
```
- **Baseline: 89 passed**, ~10 seconds
- Test files: `tests/test_regression_cleanup.py` (35), `test_retry_and_mcp.py` (22), `test_token_counter.py` (11), `test_user_feedback.py` (21)

**Integration suite:** None currently — all 89 tests are unit tests with mocked LLM calls.

### Outreach Orchestrator

**All tests (uses root venv):**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\outreach orchestrator"
..\venv\Scripts\python.exe -m pytest test_hitl_mcp.py -v
```
- **Baseline: 2 passed**, ~1 second
- Tests the HITL (Human-In-The-Loop) MCP workflow: approval forwarding and rejection-with-feedback
- Test file: `test_hitl_mcp.py`

**Manual end-to-end script (not pytest — requires all services running):**
```powershell
..\venv\Scripts\python.exe test_e2e_pipeline.py
```
- Runs a live pipeline request through the Orchestrator → Sequence Generator → Message Generator
- Prints sequence steps, observability stats, and prompt history
- Requires all three services to be running (ports 8000, 8001, 8002)

### Quick health check — all modules at once

```powershell
# From project root — run all unit tests across all modules
cd "c:\Users\ASUS\Desktop\Outreach-Project"

# Sequence Generator (109 unit tests)
cd "sequence generator"; .\venv\Scripts\python.exe -m pytest tests/ -k "not integration" -q; cd ..

# Message Generator (89 tests)
cd "message generator and sender"; .\venv\Scripts\python.exe -m pytest tests/ -q; cd ..

# Orchestrator (2 tests)
cd "outreach orchestrator"; ..\venv\Scripts\python.exe -m pytest test_hitl_mcp.py -q; cd ..
```

**Total healthy baseline: 200 tests passing** (109 + 89 + 2 unit, or 208 if you include integration).

---

## 4. Manual Test Scenarios

### 4.1 Full pipeline end-to-end

**What it does:** Submits a prospect through the Orchestrator, which calls the Sequence Generator to produce a multi-step outreach sequence, then calls the Message Generator for each step's message. The sequence pauses for human approval before dispatch.

**Steps:**

1. Send a POST request to the Orchestrator:
```
POST http://localhost:8002/api/run
Content-Type: application/json

{
  "entreprise": "Acme Corp",
  "contact_info": {
    "full_name": "Jane Doe",
    "email": "jane@acme.com",
    "country": "United States"
  },
  "contexte_web": {
    "profil_brut": "VP of Sales at Acme Corp, active on LinkedIn"
  },
  "debug_mode": true
}
```

2. **Expected response:** HTTP 200 with `"status": "awaiting_approval"` and a `"thread_id"` field. The response also contains the generated sequence steps, detected language, detected timezone, and per-step messages.

3. **Pass criteria:** Response contains `status: "awaiting_approval"`, a non-empty `thread_id`, and at least one step in the `steps` array.

4. **Fail criteria:** HTTP 500, or `status: "failed"`, or missing `thread_id`.

### 4.2 HITL approval — pause, visibility, approve, complete

**What it does:** Verifies that a sequence pauses at the approval gate, appears in the paused-threads list, can be approved, and actually completes (graph resumes and dispatches).

**Steps:**

1. **Submit a sequence** (same as 4.1). Note the `thread_id` from the response.

2. **Check paused threads:**
```
GET http://localhost:8001/api/paused-threads
```
**Expected:** The response contains a `paused_threads` array with an entry matching your `thread_id`. The entry includes `paused_at: "dispatch_to_temporal"`, the `entreprise` name, and `contact_info`.

3. **Approve the sequence:**
```
POST http://localhost:8001/api/approve/{thread_id}
Content-Type: application/json

{"approved": true}
```
**Expected:** HTTP 200 with `"status": "dispatched"`.

4. **Verify it's no longer paused:**
```
GET http://localhost:8001/api/paused-threads
```
**Expected:** The `paused_threads` array no longer contains your `thread_id`.

**Pass criteria:** Thread appears in paused list → approval returns `"dispatched"` → thread disappears from paused list.

**Fail criteria:** Thread remains in paused list after approval (this was a real bug — the graph was re-invoked from the start instead of resuming from the interrupt).

### 4.3 Reject with feedback

**What it does:** Rejects a paused sequence and provides feedback. The Sequence Generator regenerates the sequence incorporating the feedback.

**Steps:**

1. **Submit a sequence** (same as 4.1). Note the `thread_id`.

2. **Reject with feedback:**
```
POST http://localhost:8001/api/approve/{thread_id}
Content-Type: application/json

{
  "approved": false,
  "user_feedback": "Add more LinkedIn touches before the email"
}
```
**Expected:** HTTP 200 with `"status": "regenerated"` and `"user_feedback_applied"` matching your feedback string. The response includes the new `final_state` (the regenerated sequence).

3. **Check paused threads again:**
```
GET http://localhost:8001/api/paused-threads
```
**Expected:** The thread appears again (the regenerated sequence also pauses for approval — it goes through the full graph again).

**Pass criteria:** Rejection returns `"regenerated"`, feedback string is echoed back, thread re-appears in paused list with the new sequence.

**Fail criteria:** HTTP 500, or thread does not re-appear after regeneration.

### 4.4 Concurrent sequences — no cross-contamination

**What it does:** Runs two sequences simultaneously for different leads and verifies that neither sequence's data leaks into the other.

**Steps:**

1. **Submit two sequences concurrently** (use two terminal windows or a tool like `curl` in parallel):

**Request A:**
```
POST http://localhost:8001/api/generate/sequence
Content-Type: application/json

{
  "company": "AlphaCorp UNIQUE_MARKER_A",
  "contact": {"full_name": "Alice Alpha", "email": "alice@alpha.test", "country": "France"},
  "web_context": {"profil_brut": "Alpha company profile"},
  "sender_info": {"company_name": "TestCo"}
}
```

**Request B** (fire at the same time):
```
POST http://localhost:8001/api/generate/sequence
Content-Type: application/json

{
  "company": "BetaInc UNIQUE_MARKER_B",
  "contact": {"full_name": "Bob Beta", "email": "bob@beta.test", "country": "Japan"},
  "web_context": {"profil_brut": "Beta company profile"},
  "sender_info": {"company_name": "TestCo"}
}
```

2. **Check paused threads:**
```
GET http://localhost:8001/api/paused-threads
```

3. **Verify isolation:** Both `thread_id`s appear in `paused_threads`. The entry for AlphaCorp contains `"UNIQUE_MARKER_A"` in its `entreprise` field and does NOT contain `"UNIQUE_MARKER_B"`. Vice versa for BetaInc.

**Pass criteria:** Both threads present, each with only its own data, no cross-contamination.

**Fail criteria:** One thread's `entreprise` contains the other's unique marker, or one thread is missing from the paused list.

### 4.5 Downstream service failure — retry behavior

**What it does:** Verifies that when the Message Generator is unreachable, the Sequence Generator handles it gracefully without creating duplicate work.

**Steps:**

1. **Stop the Message Generator** (kill the terminal running it).

2. **Submit a sequence directly to the Sequence Generator:**
```
POST http://localhost:8001/api/generate/sequence
Content-Type: application/json

{
  "company": "TestCorp",
  "contact": {"full_name": "Test User", "email": "test@test.com", "country": "Germany"},
  "web_context": {"profil_brut": "Test profile"},
  "sender_info": {"company_name": "TestCo"}
}
```

3. **Expected behavior:** The Sequence Generator will attempt to call the Message Generator for per-step messages. If the Message Generator is down, the sequence generation itself (Gemini + sandbox) still succeeds — the steps will have `message: null` or an error indicator, but the sequence structure is returned. The response status will be `"awaiting_approval"` (the sequence pauses regardless of message generation success).

4. **Restart the Message Generator** and verify it responds:
```
GET http://localhost:8000/
```

**Pass criteria:** Sequence generation completes (with null messages) even when Message Generator is down. No crash, no duplicate sequences created.

**Fail criteria:** HTTP 500 from the Sequence Generator, or the request hangs indefinitely.

### 4.6 InMail vs. connection-request routing

**What it does:** Verifies that the system correctly routes the first LinkedIn step based on InMail credit availability and connection status.

**Steps:**

1. **Scenario A — Not connected, InMail credits available:**
```
POST http://localhost:8001/api/generate/sequence
Content-Type: application/json

{
  "company": "InMailTest Corp",
  "contact": {
    "full_name": "Test User",
    "email": "test@inmail.test",
    "country": "United States",
    "is_connected_on_linkedin": false,
    "has_inmail_credits": true
  },
  "web_context": {"profil_brut": "Test profile"},
  "sender_info": {"company_name": "TestCo"}
}
```
**Expected:** The first LinkedIn step in the response has `action_type: "LINKEDIN_INMAIL"` and `channel: "linkedin_inmail"`.

2. **Scenario B — Not connected, no InMail credits:**
Same request but with `"has_inmail_credits": false`.
**Expected:** The first LinkedIn step has `action_type: "LINKEDIN_CONNECT"` and `channel: "linkedin_dm"`.

3. **Scenario C — Already connected:**
Same request but with `"is_connected_on_linkedin": true`.
**Expected:** LinkedIn steps use `action_type: "LINKEDIN_MESSAGE"` and `channel: "linkedin_dm"`.

**Pass criteria:** The first LinkedIn step's action type and channel match the routing rules above in each scenario.

**Fail criteria:** InMail credits available but first LinkedIn step is `LINKEDIN_CONNECT`, or no credits but first step is `LINKEDIN_INMAIL`.

### 4.7 Step-count enforcement (DEFAULT_MAX_TOUCHES)

**What it does:** Verifies that the system enforces a maximum sequence length when the caller does not specify `max_touches`, and that explicit overrides are respected.

**How it works:**
- `DEFAULT_MAX_TOUCHES` (default: 5, configurable via environment variable) sets the maximum number of steps allowed in a sequence when the caller does not specify `max_touches`.
- The Gemini prompt is instructed to generate sequences within this limit.
- Server-side enforcement validates the response: if Gemini returns more steps than `effective_max_touches`, the sequence is rejected.
- Rejection triggers the retry mechanism: the graph retries up to `MAX_RETRIES` (default: 3) times.
- If all retries fail, the system falls back to `SAFE_FALLBACK_SEQUENCE` (2 steps: LINKEDIN_CONNECT + EMAIL_1).
- Callers can override per-request by passing an explicit `max_touches` value (e.g., `"max_touches": 8` allows up to 8 steps).

**Testing the feature:**
1. **Default behavior (no max_touches specified):** Submit a request without `max_touches`. The response should have at most 5 steps (or the value of `DEFAULT_MAX_TOUCHES` if overridden in `.env`).
2. **Explicit override:** Submit a request with `"max_touches": 8`. The response can have up to 8 steps.
3. **Enforcement:** If Gemini returns a sequence exceeding the limit, the system retries. If all retries fail, the fallback sequence (2 steps) is returned.

**Automated tests:** `test_retry_and_gemini.py` includes tests for:
- `TestDefaultMaxTouchesEnforcement`: Verifies server-side rejection of oversized sequences.
- `TestGraphLevelRetrySuccess`: Verifies the graph retries on oversized sequences and eventually accepts a compliant one.
- `TestGraphLevelRetryExhaustion`: Verifies the graph falls back to `SAFE_FALLBACK_SEQUENCE` after exhausting retries.

---

## 5. Known Limitations / By-Design Behavior

These are **not bugs**. Do not file them as such.

### Idempotency cache is in-memory and per-process

The Sequence Generator and Message Generator both implement idempotency caches (keyed by the `Idempotency-Key` request header). These caches are **in-memory dicts** — they deduplicate within a single process but will NOT deduplicate across multiple service instances if the system is scaled horizontally. This is documented in the code comments and is acceptable for the current single-instance deployment.

### Shared/unscoped feedback is not concurrency-safe

The `/api/feedback` endpoint accepts an optional `lead_id` parameter. When `lead_id` is provided, feedback is scoped to that lead and consumed only by that lead's next Gemini call — this is protected by a `threading.Lock` and is concurrency-safe.

When `lead_id` is **omitted**, feedback goes to a shared `"__shared__"` bucket that any lead can consume. If two sequences run concurrently, either one might consume the shared feedback. This is **by design** — the shared bucket exists for backward compatibility with callers that don't know the `lead_id`. Always pass `lead_id` in production to get isolation.

### MemorySaver resets on `/api/memory/flush`

Calling `POST /api/memory/flush` on the Sequence Generator resets the LangGraph `MemorySaver` (the in-memory checkpointer that holds paused thread state). All paused threads are lost. This is intentional for development/testing — do not call this in production.

### Sequence Generator directory has a space in its name

The folder is `sequence generator/` (with a space). This is handled at runtime by registering it as the importable package `sequence_generator` via `importlib`. Do not rename the folder — it would break the package registration logic in `scripts/api_server.py` and `tests/conftest.py`.

### message_generation_node.py is deprecated dead code

The file `sequence generator/graph/nodes/message_generation_node.py` is NOT wired into the LangGraph graph (`builder.py`). It was intended as a graph node but was never connected. The ACTUAL message generation path is: Temporal workflow → `generate_message_activity` (in `workflows/message_activities.py`) → `mcp_client.generate_message_for_step_sync` → MCP → Message Generator. The MCP path now correctly passes `language`, `research_signals`, and `personality_config` through to the Gemini prompt. Do not use `message_generation_node.py` for production message generation.

### Integration tests cost money

The 8 integration tests call the real Gemini API. Each run costs a small amount (fractions of a cent) and takes ~15 seconds. They are excluded from the default unit test command (`-k "not integration"`). Run them deliberately, not as part of every save-and-test cycle.

### No CI pipeline exists

There is no GitHub Actions, GitLab CI, or any automated test runner. Tests only run when someone manually executes them. The integration tests especially are only exercised when someone remembers to run the special command. This is a known gap.

---

## 6. Where Things Live

```
Outreach-Project/
├── message generator and sender/     ← Message Generator module
│   ├── app/
│   │   ├── main.py                   ← FastAPI app (port 8000), REST + MCP endpoints
│   │   ├── mcp_server.py             ← MCP tool definitions for message generation
│   │   ├── agents.py                 ← 5-agent LLM pipeline (planner, researcher, etc.)
│   │   ├── orchestrator.py           ← Pipeline orchestration logic
│   │   ├── send_tools.py             ← Email (Gmail SMTP) + LinkedIn (UniPile) senders
│   │   ├── memory.py                 ← 3-tier memory (prospect, learning, offer)
│   │   ├── observability.py          ← Prompt store, runtime config, token tracking
│   │   ├── config.py                 ← Settings / env vars
│   │   └── models.py                 ← Pydantic models (AgentState, GenerateRequest, etc.)
│   ├── tests/                        ← 89 unit tests
│   ├── .env                          ← Runtime config (GOOGLE_API_KEY, etc.)
│   ├── .env.example                  ← Template for .env
│   ├── requirements.txt
│   └── venv/                         ← Python 3.12 virtual environment
│
├── sequence generator/               ← Sequence Generator module
│   ├── scripts/
│   │   ├── api_server.py             ← FastAPI app (port 8001), REST endpoints
│   │   └── worker.py                 ← Temporal worker (processes workflow tasks)
│   ├── graph/
│   │   ├── builder.py                ← LangGraph workflow definition + approve_and_dispatch()
│   │   ├── state.py                  ← GraphState Pydantic model
│   │   └── nodes/
│   │       ├── sequence_generator_node.py  ← Gemini sequence generation + retry loop
│   │       ├── sandbox_node.py             ← Timezone-aware business-hour enforcement
│   │       └── message_generation_node.py  ← DEPRECATED dead code (NOT wired into builder.py)
│   ├── models/
│   │   └── outreach_step.py          ← OutreachSequence, OutreachStep, ActionType enum
│   ├── tools/
│   │   ├── language_detector.py      ← Country → language/timezone detection
│   │   └── mcp_client.py             ← MCP client (calls Message Generator)
│   ├── workflows/
│   │   ├── message_activities.py     ← Temporal activities (research, strategy, message gen, send)
│   │   └── sequence_workflow.py      ← Temporal workflow definition
│   ├── middleware/
│   │   └── token_counter.py          ← LLM token counting
│   ├── observability/
│   │   ├── logging_config.py         ← Structured logging setup
│   │   └── observability_store.py    ← Prompt history, runtime config, metrics
│   ├── temporal/
│   │   └── payload_adapter.py        ← Temporal workflow payload serialization
│   ├── tests/                        ← 117 tests (109 unit + 8 integration)
│   │   ├── conftest.py               ← Pytest config: .env loading, package registration
│   │   ├── test_paused_threads_integration.py   ← Real graph resume path (4 tests)
│   │   ├── test_concurrency_integration.py      ← Thread isolation + feedback scoping (4 tests)
│   │   ├── test_inmail_enforcement.py           ← InMail routing rules (7 tests)
│   │   ├── test_language_detection.py           ← Language/timezone detection (15 tests)
│   │   ├── test_message_field_roundtrip.py      ← Field passthrough: language, signals, personality (14 tests)
│   │   ├── test_outreach_step.py                ← Pydantic model validation (10 tests)
│   │   ├── test_regression_cleanup.py           ← Deleted files, state integrity (22 tests)
│   │   ├── test_retry_and_gemini.py             ← Gemini retry/fallback, token recording (14 tests)
│   │   ├── test_sandbox.py                      ← Sandbox clipping, business hours (8 tests)
│   │   └── test_user_feedback.py                ← Feedback injection, approval paths (20 tests)
│   ├── .env                          ← Runtime config (GOOGLE_API_KEY, etc.)
│   ├── .env.example
│   ├── requirements.txt
│   └── venv/                         ← Python 3.12 virtual environment
│
├── outreach orchestrator/            ← Outreach Orchestrator module
│   ├── app/
│   │   ├── main.py                   ← FastAPI app (port 8002), REST + MCP endpoints
│   │   ├── mcp_server.py             ← MCP tool definitions (run pipeline, approve, etc.)
│   │   ├── graph.py                  ← Orchestrator graph (calls seq gen + msg gen)
│   │   ├── clients.py                ← HTTP clients for Sequence Generator + Message Generator
│   │   ├── observability.py          ← Aggregates observability from both modules
│   │   ├── state.py                  ← OrchestratorState Pydantic model
│   │   └── config.py                 ← Settings / env vars
│   ├── test_hitl_mcp.py              ← 2 HITL MCP workflow tests
│   ├── test_e2e_pipeline.py          ← Manual live pipeline script (not pytest, requires running services)
│   ├── .env                          ← Runtime config (DEBUG_MODE, downstream URLs)
│   ├── .env.example
│   ├── requirements.txt
│   └── venv/                         ← Python 3.12 virtual environment
│
├── venv/                             ← Root virtual environment (used by orchestrator tests)
├── frontend/                         ← React frontend (Vite + Tailwind)
├── main.py                           ← Root launcher — starts all services with one command
├── TESTING.md                        ← This file
└── HOW_TO_RUN.md                     ← Original setup instructions
```

### Quick reference — test commands

| Module | Command | Count |
|---|---|---|
| Sequence Generator (unit) | `cd "sequence generator"; .\venv\Scripts\python.exe -m pytest tests/ -k "not integration" -v` | 109 |
| Sequence Generator (integration) | `cd "sequence generator"; .\venv\Scripts\python.exe -m pytest tests/ -k "integration" -v` | 8 |
| Sequence Generator (all) | `cd "sequence generator"; .\venv\Scripts\python.exe -m pytest tests/ -v` | 117 |
| Message Generator | `cd "message generator and sender"; .\venv\Scripts\python.exe -m pytest tests/ -v` | 89 |
| Orchestrator | `cd "outreach orchestrator"; ..\venv\Scripts\python.exe -m pytest test_hitl_mcp.py -v` | 2 |
