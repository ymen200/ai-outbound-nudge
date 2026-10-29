# How to Run — Outreach Project

Complete guide for running and manually testing the outreach system.

## Prerequisites

- **Python 3.12** (each module has its own virtual environment)
- **Google Gemini API key** — required for sequence/message generation. Get one at https://makersuite.google.com/app/apikey
- **Temporal CLI** (optional) — needed only for real dispatch testing. Install with `winget install temporalio.cli`

### Environment files

Each module reads its own `.env` file. Copy the `.env.example` files and fill in your API key:

| Module | `.env` location | Required keys |
|---|---|---|
| Message Generator | `message generator and sender/.env` | `GOOGLE_API_KEY` |
| Sequence Generator | `sequence generator/.env` | `GOOGLE_API_KEY` |
| Outreach Orchestrator | `outreach orchestrator/.env` | (no API key — proxies to the other two) |

The orchestrator's `DEBUG_MODE=true` (default) propagates to both modules at runtime, disabling memory for deterministic testing.

---

## Starting Services

### Option A: One command starts everything (recommended)

```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project"
.\venv\Scripts\activate.bat
python main.py
```

This launches all three services + Temporal Worker in separate subprocesses with live log streaming. Press Ctrl+C to stop all.

### Option B: Separate terminals (for debugging individual services)

**Terminal 1 — Message Generator (port 8000):**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\message generator and sender"
.\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — Sequence Generator (port 8001):**
```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
.\venv\Scripts\activate.bat
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001
```

**Terminal 3 — Outreach Orchestrator (port 8002):**
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

PowerShell verification commands:
```powershell
Invoke-RestMethod http://localhost:8000/
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8002/api/health
```

---

## API Endpoints

### Outreach Orchestrator (port 8002)

| Endpoint | Method | Description |
|---|---|---|
| `/api/run` | POST | Run full pipeline (sequence + messages + observability) |
| `/api/approve/{thread_id}` | POST | Approve/reject a paused sequence (passes through to Sequence Generator) |
| `/api/observability` | GET | Aggregated observability from both modules |
| `/api/observability/prompts` | GET | Merged prompt history from both modules |
| `/api/config/override` | POST | Override config in a specific module |
| `/api/config/reset` | POST | Reset config overrides in a module |
| `/api/feedback` | POST | Inject feedback into a module's next generation |
| `/api/health` | GET | Health check (includes downstream module status) |
| `/mcp` | GET | MCP SSE endpoint for global orchestrator |
| `/docs` | GET | Swagger UI |

### Sequence Generator (port 8001)

| Endpoint | Method | Description |
|---|---|---|
| `/api/generate/sequence` | POST | Generate a full outreach sequence |
| `/api/approve/{thread_id}` | POST | Approve and dispatch a paused sequence |
| `/api/paused-threads` | GET | List all sequences awaiting approval |
| `/api/feedback` | POST | Inject feedback scoped to a lead_id |
| `/api/memory/status` | GET | Check memory status (proxies to message generator) |
| `/api/memory/flush` | POST | Wipe all memory + reset graph checkpointer |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |

### Message Generator (port 8000)

| Endpoint | Method | Description |
|---|---|---|
| `/api/generate` | POST | Full pipeline (returns step-by-step history) |
| `/api/generate/simple` | POST | Single message generation (returns final message) |
| `/api/review/{task_id}` | GET | Get draft awaiting human review |
| `/api/review/{task_id}/decision` | POST | Approve or reject a draft |
| `/api/memory/status` | GET | See what's stored: debug_mode, backend type, counts, learning stats |
| `/api/memory/flush` | POST | Wipe ALL memory (prospect + learning + offer) |
| `/api/send/email` | POST | Send an email directly |
| `/mcp` | GET | MCP SSE endpoint for agent-to-agent communication |
| `/` | GET | Health check |
| `/docs` | GET | Swagger UI |

---

## Manual Walkthrough: Full Pipeline

### Step 1: Start everything

```powershell
cd "c:\Users\ASUS\Desktop\Outreach-Project"
.\venv\Scripts\activate.bat
python main.py
```

Leave this running. Open a **second PowerShell window** for the commands below.

### Step 2: Verify services

```powershell
Invoke-RestMethod http://localhost:8000/
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8002/api/health
```

### Step 3: Run a full pipeline

Submit a prospect through the Orchestrator:

```powershell
$body = @{
    entreprise = "TechCorp Solutions"
    contact_info = @{
        full_name = "Sarah Chen"
        email = "sarah.chen@techcorp.com"
        country = "United States"
        city = "San Francisco"
        is_connected_on_linkedin = $false
    }
    contexte_web = @{
        profil_brut = "VP of Sales at TechCorp, a mid-size SaaS company. Recently posted about improving SDR efficiency."
    }
    sender_company = "OutreachAI Inc"
    sender_elevator_pitch = "We help SaaS companies automate outbound sales with AI"
    offer_name = "Free Outreach Audit"
    solution_summary = "AI-driven analysis of your outreach workflow"
    cta = "Book a 15-minute strategy call"
    debug_mode = $true
} | ConvertTo-Json -Depth 5

$result = Invoke-RestMethod -Uri "http://localhost:8002/api/run" -Method POST -Body $body -ContentType "application/json"
```

This takes 15-30 seconds. Inspect the result:

```powershell
$result.status          # "awaiting_approval"
$result.thread_id       # Save this for the next steps
$result.sequence_result.sequence | ConvertTo-Json -Depth 5
```

### Step 4: Check paused threads

The sequence pauses at `dispatch_to_temporal` waiting for approval:

```powershell
Invoke-RestMethod http://localhost:8001/api/paused-threads | ConvertTo-Json -Depth 5
```

### Step 5A: Approve the sequence

```powershell
$approveBody = @{ approved = $true } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8001/api/approve/$($result.thread_id)" -Method POST -Body $approveBody -ContentType "application/json"
```

Expected: `status: "dispatched"`. Verify it's gone from paused list:

```powershell
Invoke-RestMethod http://localhost:8001/api/paused-threads
```

### Step 5B: OR — Reject with feedback

Run the pipeline again (same command as Step 3, assign to `$result2`):

```powershell
$result2 = Invoke-RestMethod -Uri "http://localhost:8002/api/run" -Method POST -Body $body -ContentType "application/json"
```

Then reject with feedback:

```powershell
$rejectBody = @{
    approved = $false
    user_feedback = "Make it more aggressive — add a breakup email at the end"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8001/api/approve/$($result2.thread_id)" -Method POST -Body $rejectBody -ContentType "application/json"
```

Expected: `status: "regenerated"`. The regenerated sequence appears in paused threads again.

### Step 6: Test InMail routing

Hit the Sequence Generator directly (note: different field names — `company`/`contact`/`web_context` instead of `entreprise`/`contact_info`/`contexte_web`):

```powershell
# Not connected, has InMail credits → should use LINKEDIN_INMAIL
$body = @{
    company = "InMailTest Corp"
    contact = @{
        full_name = "Test User"
        email = "test@inmail.test"
        country = "United States"
        is_connected_on_linkedin = $false
        has_inmail_credits = $true
    }
    web_context = @{ profil_brut = "Test profile for InMail routing" }
    sender_info = @{ company_name = "TestCo" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:8001/api/generate/sequence" -Method POST -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 5
```

Change `has_inmail_credits` to `$false` → first LinkedIn step switches to `LINKEDIN_CONNECT`.

### Step 7: Test concurrent sequences

Fire two requests simultaneously from separate PowerShell windows:

**Window A:**
```powershell
$body = @{
    company = "AlphaCorp UNIQUE_MARKER_A"
    contact = @{ full_name = "Alice Alpha"; email = "alice@alpha.test"; country = "France" }
    web_context = @{ profil_brut = "Alpha company profile" }
    sender_info = @{ company_name = "TestCo" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost:8001/api/generate/sequence" -Method POST -Body $body -ContentType "application/json"
```

**Window B:**
```powershell
$body = @{
    company = "BetaInc UNIQUE_MARKER_B"
    contact = @{ full_name = "Bob Beta"; email = "bob@beta.test"; country = "Japan" }
    web_context = @{ profil_brut = "Beta company profile" }
    sender_info = @{ company_name = "TestCo" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost:8001/api/generate/sequence" -Method POST -Body $body -ContentType "application/json"
```

Then verify isolation:
```powershell
Invoke-RestMethod http://localhost:8001/api/paused-threads | ConvertTo-Json -Depth 5
```

Both threads appear, each with only its own data.

### Step 8: Explore observability

```powershell
# Token usage across both modules
Invoke-RestMethod http://localhost:8002/api/observability | ConvertTo-Json -Depth 5

# Prompt history (last 5 LLM calls)
Invoke-RestMethod "http://localhost:8002/api/observability/prompts?limit=5" | ConvertTo-Json -Depth 5
```

---

## API Field Naming: Orchestrator vs Sequence Generator

The two endpoints use **different field names** for the same concepts:

| Concept | Orchestrator `/api/run` | Sequence Generator `/api/generate/sequence` |
|---|---|---|
| Company | `entreprise` | `company` |
| Contact | `contact_info` (dict) | `contact` (ContactInfo model) |
| Web context | `contexte_web` (dict) | `web_context` (WebContext model) |
| Sender | `sender_company` (flat string) | `sender_info` (CompanyInfo model) |

Don't mix them — sending `entreprise` to port 8001 or `company` to port 8002 will fail.

---

## Debugging & Memory Management

### DEBUG_MODE

| File | Default | Purpose |
|------|---------|--------|
| `message generator and sender/.env` | `true` | Bypasses memory reads/writes |
| `sequence generator/.env` | `true` | Propagated to message generator |
| `outreach orchestrator/.env` | `true` | **Source of truth** — propagated to both modules at runtime |

- `DEBUG_MODE=true` — memory bypassed, deterministic results, safe for testing
- `DEBUG_MODE=false` — full memory active (prospect history, learning loop, hook dedup)

Override per-request: `"debug_mode": false` in the API payload.

Override at runtime without restarting:
```powershell
$overrideBody = @{
    module = "message_generator"
    overrides = @{ DEBUG_MODE = "false" }
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8002/api/config/override" -Method POST -Body $overrideBody -ContentType "application/json"
```

### Memory commands

```powershell
# Check memory status
Invoke-RestMethod http://localhost:8000/api/memory/status

# Flush ALL memory (both modules + graph checkpointer)
Invoke-RestMethod -Uri "http://localhost:8001/api/memory/flush" -Method POST
```

---

## Stopping Services

If using `python main.py`: press `Ctrl+C` in the terminal.

If using separate terminals: press `Ctrl+C` in each, or:
```powershell
taskkill /F /FI "WINDOWTITLE eq Message Generator" 2>$null
taskkill /F /FI "WINDOWTITLE eq Sequence Generator" 2>$null
taskkill /F /FI "WINDOWTITLE eq Outreach Orchestrator" 2>$null
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Port 8000, 8001, or 8002 already in use | `netstat -ano \| findstr :8000` to find PID, then `taskkill /F /PID <pid>` |
| "No module named uvicorn" | `pip install fastapi uvicorn` in the module's venv |
| Sequence Generator can't reach Message Generator | Make sure Message Generator (port 8000) is running first |
| API key errors | Check `.env` files have valid `GOOGLE_API_KEY` values |
| "Cannot connect to Temporal" | Only needed for dispatch — run `temporal server start-dev` |
| Orchestrator returns 500 on `/api/run` | Check that both port 8000 and 8001 are responding |
# How to Run — Outreach Project

Quick start guide for running the complete outreach system. Three setup options are available.

## Prerequisites

- Python 3.12+ installed
- `.env` files configured in `message generator and sender/`, `sequence generator/`, and `outreach orchestrator/` with your API keys
- Virtual environments created in both modules (orchestrator uses root venv)

---

## Option A: Without Docker (Recommended for Development)

This runs only the two FastAPI services. Temporal dispatch is simulated (logged but not executed).

### Terminal 1: Message Generator API (port 8000)

```cmd
cd "message generator and sender"
.\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Verify:** http://localhost:8000/  
Should return: `{"status": "online", "app": "Agentic Outreach API", ...}`

### Terminal 2: Sequence Generator API (port 8001)

```cmd
cd "sequence generator"
.\venv\Scripts\activate.bat
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001
```

**Verify:** http://localhost:8001/health  
Should return: `{"status": "ok", "service": "sequence-generator"}`

### Terminal 3: Outreach Orchestrator (port 8002)

```cmd
cd "outreach orchestrator"
..\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

**Verify:** http://localhost:8002/  
Should return: `{"status": "online", "app": "Outreach Orchestrator", ...}`

---

## Option B: With Docker + Temporal (Full Production Setup)

Requires Docker and the Temporal CLI installed.

### Terminal 1: Temporal Server

```bash
temporal server start-dev
```

Or via Docker:
```bash
docker run -d --name temporal -p 7233:7233 -p 8080:8080 temporalio/auto-setup:latest
```

**Temporal Web UI:** http://localhost:8080

### Terminal 2: Message Generator API (port 8000)

Same as Option A, Terminal 1.

### Terminal 3: Sequence Generator API (port 8001)

Same as Option A, Terminal 2.

### Terminal 4: Outreach Orchestrator (port 8002)

Same as Option A, Terminal 3.

### Terminal 5: Temporal Worker (optional — for actual message sending)

```cmd
cd "sequence generator"
.\venv\Scripts\activate.bat
python scripts/worker.py
```

---

## API Endpoints

### Outreach Orchestrator (port 8002)

| Endpoint | Method | Description |
|---|---|---|
| `/api/orchestrate` | POST | Run full orchestrated pipeline (sequence + observability) |
| `/api/observability` | GET | Aggregated observability from both modules |
| `/api/observability/prompts` | GET | Merged prompt history from both modules |
| `/api/config/override` | POST | Override config in a specific module |
| `/api/config/reset` | POST | Reset config overrides in a module |
| `/api/feedback` | POST | Inject feedback into a module's next generation |
| `/api/health` | GET | Health check (includes downstream module status) |
| `/mcp` | GET | MCP SSE endpoint for global orchestrator |
| `/docs` | GET | Swagger UI |

### Sequence Generator (port 8001)

| Endpoint | Method | Description |
|---|---|---|
| `/api/generate/sequence` | POST | Generate a full outreach sequence |
| `/api/approve/{thread_id}` | POST | Approve and dispatch a paused sequence |
| `/api/memory/status` | GET | Check memory status (proxies to message generator) |
| `/api/memory/flush` | POST | Wipe all memory + reset graph checkpointer |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |

### Message Generator (port 8000)

| Endpoint | Method | Description |
|---|---|---|
| `/api/generate` | POST | Full pipeline (returns step-by-step history) |
| `/api/generate/simple` | POST | Single message generation (returns final message) |
| `/api/review/{task_id}` | GET | Get draft awaiting human review |
| `/api/review/{task_id}/decision` | POST | Approve or reject a draft |
| `/api/memory/status` | GET | See what's stored: debug_mode, backend type, counts, learning stats |
| `/api/memory/flush` | POST | Wipe ALL memory (prospect + learning + offer) |
| `/api/send/email` | POST | Send an email directly |
| `/mcp` | GET | MCP SSE endpoint for agent-to-agent communication |
| `/` | GET | Health check |
| `/docs` | GET | Swagger UI |

---

## Example: Generate a Sequence

```cmd
curl -X POST http://localhost:8001/api/generate/sequence ^
  -H "Content-Type: application/json" ^
  -d @"sequence generator/example_api_request.json"
```

Or open http://localhost:8001/docs in your browser and use the interactive Swagger UI.

### Key Request Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `contact.is_connected_on_linkedin` | bool | `false` | If `false`, first LinkedIn step will be `LINKEDIN_CONNECT` (connection request). If `true`, uses `LINKEDIN_MESSAGE` directly. |
| `use_native_language` | bool | `false` | If `true`, messages are written in the prospect's detected language. If `false`, messages are in English. |
| `message_language` | string | `null` | Explicit language override (ISO 639-1 code like `"fr"`, `"es"`, `"de"`). When set, forces `use_native_language` to `true`. |
| `approval_mode` | string | `"per_sequence"` | `per_sequence` = approve once before dispatch. `per_step` = approve each step. `per_step_and_message` = approve step + message. |

> **Note:** Explanations (`timing_justification`, `sequence_architecture_rationale`) are **always in English** regardless of language settings.

---

## Debugging & Memory Management

### DEBUG_MODE — Development vs Production

`DEBUG_MODE` is defined in **all three** `.env` files:

| File | Default | Purpose |
|------|---------|--------|
| `message generator and sender/.env` | `true` | Controls whether the message generator reads/writes prospect & learning memory |
| `sequence generator/.env` | `true` | Propagated to the message generator via the sequence generator's own debug flag |
| `outreach orchestrator/.env` | `true` | **Source of truth** — propagated to both modules at runtime via config override |

#### `DEBUG_MODE=true` (default — development/testing)

- **Memory reads bypassed** — every generation starts fresh, no accumulated hooks/angles
- **Memory writes skipped** — test runs don't pollute stored data
- **`do_not_contact` still enforced** — hard stop regardless of debug mode
- **Results are deterministic and repeatable**

#### `DEBUG_MODE=false` (production)

- **Full memory active** — prospect memory, learning memory, and offer memory are read and written
- **Strategist avoids repeating hooks/angles** from previous outreach
- **Learning loop kicks in** (if `ENABLE_LEARNING_LOOP=true`) — tracks quality scores over time
- **Results are NOT deterministic** — output changes based on accumulated history

#### How propagation works

When you send a request to the orchestrator with `"debug_mode": true`:
1. The orchestrator stores it in `OrchestratorState`
2. The `apply_config_overrides` node **pushes `DEBUG_MODE` to both modules** via REST config override
3. Both modules' `RuntimeConfig` picks it up — researcher and critic agents check it before reading/writing memory

> You can also set `debug_mode` per-request in the API payload (e.g. `"debug_mode": false`), which overrides the `.env` default for that call only.

### Check memory status:
```cmd
curl http://localhost:8000/api/memory/status
```
Returns: `debug_mode`, backend type, prospect/offer counts, learning stats.

### Flush all memory (wipe everything):
```cmd
curl -X POST http://localhost:8001/api/memory/flush
```
This flushes BOTH the message generator's Redis/in-memory store AND resets the sequence generator's LangGraph checkpointer.

### Switch to production mode:
Set in **all three** `.env` files, then restart services:
```env
DEBUG_MODE=false
ENABLE_LEARNING_LOOP=true
```

Or override at runtime without restarting:
```cmd
curl -X POST http://localhost:8002/api/config/override ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"message_generator\", \"overrides\": {\"DEBUG_MODE\": \"false\"}}"
```

---

## Human-in-the-Loop Flow

1. `POST /api/generate/sequence` → returns sequence with `status: "awaiting_approval"` and a `thread_id`
2. Review the returned sequence (steps, messages, timing)
3. If satisfied: `POST /api/approve/{thread_id}` → dispatches to Temporal
4. If not: modify your request and re-submit, or provide feedback

---

## Orchestration: `start_all_services.bat`

For quick startup of Option A, run:

```cmd
start_all_services.bat
```

This opens three CMD windows:
- **Message Generator** on port 8000
- **Sequence Generator** on port 8001
- **Outreach Orchestrator** on port 8002

---

## Verification Checklist

| Service | Status Check | Expected Result |
|---------|--------------|-----------------|
| Message Generator | `GET http://localhost:8000/` | `{"status": "online", ...}` |
| Sequence Generator | `GET http://localhost:8001/health` | `{"status": "ok", ...}` |
| Outreach Orchestrator | `GET http://localhost:8002/` | `{"status": "online", ...}` |
| Temporal (optional) | `http://localhost:8080` | Temporal Web UI loads |

---

## Stopping Services

```cmd
taskkill /F /FI "WINDOWTITLE eq Message Generator" 2>nul
taskkill /F /FI "WINDOWTITLE eq Sequence Generator" 2>nul
taskkill /F /FI "WINDOWTITLE eq Outreach Orchestrator" 2>nul
```

Or press `Ctrl+C` in each terminal.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Port 8000, 8001, or 8002 already in use | `netstat -ano \| findstr :8000` to find PID, then `taskkill /F /PID <pid>` |
| "No module named uvicorn" | `pip install fastapi uvicorn` in the venv |
| Sequence Generator can't reach Message Generator | Make sure Message Generator (port 8000) is running first |
| API key errors | Check `.env` files have valid `GOOGLE_API_KEY` values |
| "Cannot connect to Temporal" | Only needed for Option B — run `temporal server start-dev` or Docker equivalent |
