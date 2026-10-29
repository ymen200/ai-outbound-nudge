# Personalization Engine — AI-Powered B2B Outreach Platform

Multi-module AI system for cold B2B outreach: sequence generation, JIT message creation, quality validation, and human-gated dispatch. The system stops when a prospect replies — it handles cold outreach only.

---

## Architecture

```
Global Orchestrator
        ↓
Outreach Orchestrator (port 8002)   gateway
        ↓ REST
Sequence Generator (port 8001)
  ├─ generate_sequence (Gemini LLM)
  ├─ sandbox (timezone + business hours enforcement)
  └─ dispatch_to_temporal (pauses for human approval)
        ↓ MCP (SSE/stdio, JIT per step via Temporal)
Message Generator (port 8000)
  └─ LangGraph pipeline: Researcher → Strategist → Writer → Critic
```

**Inter-module communication uses MCP (Model Context Protocol)**:
- Windows: SSE (Server-Sent Events) mode by default
- Linux/Mac: stdio (subprocess) mode by default
- Configurable via `MCP_CONNECTION_MODE` and `MCP_SERVER_URL` environment variables

**Message generation is JIT** — messages are generated per-step when Temporal executes each step, not during sequence planning. The full path: Sequence Generator plans the sequence → pauses for human approval → Temporal's `generate_message_activity` calls the Message Generator via MCP per step, passing `language`, `research_signals`, and `personality_config` through to the Gemini prompt.

**Outreach scope** — the system generates and dispatches cold outreach only. Once a prospect replies, the pipeline stops. Reply recording (`/api/reply`) feeds the learning memory for future campaigns.

---

## Modules

| Module | Port | Entry point |
|--------|------|-------------|
| Message Generator | 8000 | `message generator and sender/app/main.py` |
| Sequence Generator | 8001 | `sequence generator/scripts/api_server.py` |
| Outreach Orchestrator | 8002 | `outreach orchestrator/app/main.py` |

---

## Setup

### Prerequisites
- Python 3.12+
- `.env` files configured in each module directory
- Virtual environments created in each module

### Start (development — no Temporal)

```cmd
# Option 1: Use the root launcher (recommended)
python main.py

# Option 2: Manual start in separate terminals
# Terminal 1 — Message Generator
cd "message generator and sender"
.\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Sequence Generator
cd "sequence generator"
.\venv\Scripts\activate.bat
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001

# Terminal 3 — Outreach Orchestrator (optional)
cd "outreach orchestrator"
..\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### Verify
- Message Generator: `GET http://localhost:8000/` → `{"status": "online", ...}`
- Sequence Generator: `GET http://localhost:8001/health` → `{"status": "ok", ...}`
- Orchestrator: `GET http://localhost:8002/` → `{"status": "online", ...}`

---

## Configuration

### `sequence generator/.env`
```env
GOOGLE_API_KEY=your_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
MESSAGE_GENERATOR_URL=http://localhost:8000
MCP_CONNECTION_MODE=stdio
MCP_SERVER_URL=http://localhost:8000/mcp
DEBUG_MODE=true
```

### `message generator and sender/.env`
```env
GOOGLE_API_KEY=your_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
MIN_QUALITY_SCORE=80
DEBUG_MODE=true
```

---

## API Reference

### Sequence Generator (port 8001)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generate/sequence` | POST | Generate sequence → pauses for human approval |
| `/api/approve/{thread_id}` | POST | Approve (dispatch) or reject with feedback (regenerate) |
| `/api/memory/status` | GET | Memory status (proxies to message generator) |
| `/api/memory/flush` | POST | Wipe memory + reset graph checkpointer |
| `/api/observability` | GET | Prompt history + token usage |
| `/api/observability/prompts` | GET | Filtered prompt history |
| `/api/observability/clear` | POST | Clear prompt history |
| `/api/config/override` | POST | Override runtime config (e.g. `DEBUG_MODE`) |
| `/api/config/reset` | POST | Reset config overrides to defaults |
| `/api/feedback` | POST | Inject global orchestrator feedback into next generation |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |

### Message Generator (port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generate` | POST | Full pipeline (returns step-by-step agent history) |
| `/api/generate/simple` | POST | Generate a single message (returns final message only) |
| `/api/reply` | POST | Record a prospect reply — updates memory + learning loop |
| `/api/review/{task_id}` | GET | Get draft awaiting human review |
| `/api/review/{task_id}/decision` | POST | Approve (send) or reject with feedback (rewrite) |
| `/api/send/email` | POST | Send an email directly |
| `/api/memory/status` | GET | Memory state + debug_mode info |
| `/api/memory/flush` | POST | Wipe all memory (prospect + learning + offer) |
| `/api/observability` | GET | Prompt history + token usage |
| `/api/observability/prompts` | GET | Filtered prompt history |
| `/api/observability/clear` | POST | Clear prompt history |
| `/api/config/override` | POST | Override runtime config (e.g. `DEBUG_MODE`) |
| `/api/config/reset` | POST | Reset config overrides to defaults |
| `/api/feedback` | POST | Inject global orchestrator feedback into next generation |
| `/mcp` | GET | MCP SSE endpoint (agent-to-agent) |
| `/mcp/messages` | POST | MCP message posting (required by SSE transport) |
| `/` | GET | Health check |
| `/docs` | GET | Swagger UI |

### Outreach Orchestrator (port 8002)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/run` | POST | Run the full orchestrated pipeline |
| `/api/feedback` | POST | Inject global orchestrator feedback into a module |
| `/api/config/override` | POST | Override runtime config in a module |
| `/api/config/reset` | POST | Reset config overrides in a module |
| `/api/observability` | GET | Aggregated observability from both modules |
| `/api/observability/prompts` | GET | Merged prompt history from both modules |
| `/api/health` | GET | Health check + downstream module status |
| `/mcp` | GET | MCP SSE endpoint for global orchestrator |
| `/docs` | GET | Swagger UI |

---

## Key Request Fields — `/api/generate/sequence`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `contact.is_connected_on_linkedin` | bool | `false` | `true` → `LINKEDIN_MESSAGE`; `false` → `LINKEDIN_CONNECT` (or `LINKEDIN_INMAIL` if credits available) |
| `contact.has_inmail_credits` | bool | `false` | `true` + not connected → uses `LINKEDIN_INMAIL` instead of `LINKEDIN_CONNECT` |
| `use_native_language` | bool | `false` | `true` → messages written in prospect's detected language |
| `message_language` | string | `null` | ISO 639-1 override (`"fr"`, `"de"`, etc.). Forces `use_native_language=true` |
| `approval_mode` | string | `"per_sequence"` | `per_sequence` / `per_step` / `per_step_and_message` |
| `max_touches` | int | `null` | Max number of sequence steps |
| `max_days` | int | `null` | Max duration of the full sequence in days |
| `preferred_first_channel` | string | `null` | Force a specific first channel |
| `user_feedback` | string | `null` | Human notes injected as `USER NOTES:` into the sequence design prompt |
| `research_signals` | list | required | Pre-fetched signals from Detective. Pipeline aborts without them |
| `personality_config` | object | `null` | Message style overrides forwarded to the message generator |

> `timing_justification` and `sequence_architecture_rationale` are always in English regardless of language settings.

## Key Request Fields — `/api/generate/simple` (Message Generator)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_prospect` | string | ✓ | Full name |
| `target_company` | string | ✓ | Prospect's company |
| `channel` | string | ✓ | `linkedin_dm`, `linkedin_inmail`, `email` |
| `stage` | string | ✓ | `first_touch`, `second_touch`, `third_touch` |
| `company_details` | object | ✓ | `company_name`, `elevator_pitch`, `value_props`, `social_proof` |
| `selected_offer` | object | ✓ | `offer_name`, `solution_summary`, `cta`, `pain_points`, `proof_points` |
| `research_signals` | list | ✓ | Must be provided — researcher aborts without signals |
| `user_feedback` | string | — | Human notes injected as `USER NOTES:` in the writer prompt |
| `personality` | object | — | Style config: `base_template`, `personality_traits`, `urgency_level`, etc. |

---

## Human-in-the-Loop Flow

```
POST /api/generate/sequence
    → status: "awaiting_approval", thread_id: "..."
    → review steps, messages, quality scores

POST /api/approve/{thread_id}  { "approved": true }
    → dispatches sequence to Temporal

POST /api/approve/{thread_id}  { "approved": false, "user_feedback": "..." }
    → resets state, injects feedback as USER NOTES, regenerates sequence

POST /api/review/{task_id}/decision  { "approved": false, "feedback": "..." }
    → sets writer to REVISING, reruns pipeline with feedback
```

---

## Human Feedback (`user_feedback`)

Both generators accept `user_feedback` as a runtime parameter. Injected directly into the LLM prompt at generation time — does not modify the base prompt template.

- **Sequence Generator**: injected as `USER NOTES:` into the Gemini sequence design prompt
- **Message Generator**: injected as `USER NOTES:` into the writer agent prompt on every write and revision pass
- **End-to-end**: sequence generator `user_feedback` is forwarded to the message generator for every step via `enriched_context["user_notes"]`

---

## Memory System

Three memory stores, all active in production mode (`DEBUG_MODE=false`):

| Store | What it tracks | Fed by |
|-------|---------------|--------|
| Prospect memory | hooks used, angles tried, contact count per prospect | `critic` (on success), `record_outreach` |
| Learning memory | best/worst hooks + angles system-wide, reply rates | `critic` (generation stats), `POST /api/reply` (reply events) |
| Offer memory | best angles per offer, avg quality score | `critic` (on success via `record_usage`) |

**How learning memory feeds the strategist:**
- `best_performing_hooks` → strategist prefers similar hook approaches
- `worst_performing_hooks` → strategist avoids these hook patterns
- `best_performing_angles` → strategist considers similar angles
- `offer_memory.best_angles` → strategist biases toward angles that historically worked for this specific offer

**Reply recording closes the loop:**
```cmd
POST http://localhost:8000/api/reply?prospect_name=Alice&prospect_company=Acme&sentiment=positive
```
This updates prospect memory (`ever_replied`) and promotes the last hook/angle used into `best_performing_hooks/angles` in learning memory.

---

## ActionTypes

| ActionType | Condition | Channel |
|------------|-----------|---------|
| `LINKEDIN_CONNECT` | Not connected, no InMail credits | `linkedin_dm` |
| `LINKEDIN_MESSAGE` | Already connected | `linkedin_dm` |
| `LINKEDIN_INMAIL` | Not connected + has InMail credits | `linkedin_inmail` |
| `EMAIL_1` | Any | `email` |

---

## DEBUG_MODE

Controls memory read/write in the message generator.

| Mode | Memory reads | Memory writes | Deterministic |
|------|-------------|----------------|---------------|
| `true` (default) | Bypassed | Skipped | Yes |
| `false` (production) | Full — all 3 stores | Full — updates after each generation | No |

`do_not_contact` is enforced in both modes regardless.

Override at runtime without restarting:
```cmd
curl -X POST http://localhost:8002/api/config/override ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"message_generator\", \"overrides\": {\"DEBUG_MODE\": \"false\"}}"
```

---

## Memory Management

```cmd
# Check status (prospect count, learning stats, debug_mode)
curl http://localhost:8000/api/memory/status

# Flush everything (message generator memory + graph checkpointer)
curl -X POST http://localhost:8001/api/memory/flush
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port in use | `netstat -ano \| findstr :8000` → `taskkill /F /PID <pid>` |
| API key errors | Check `GOOGLE_API_KEY` in `.env` files |
| Sequence gen can't reach message gen | Start message generator (port 8000) first |
| Generic messages | Ensure `sender_info` has real `company_name`, `elevator_pitch`, and `offer_name` |
| Pipeline aborts immediately | `research_signals` is required — must be provided in the request |
| Memory not updating | Check `DEBUG_MODE=false` in `.env` and restart the service |

---

## Port Map

| Service | Port |
|---------|------|
| Message Generator | 8000 |
| Sequence Generator | 8001 |
| Outreach Orchestrator | 8002 |
| Temporal | 7233 |
| Temporal Web UI | 8080 |
