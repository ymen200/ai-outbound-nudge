# Sequence Generator

Generates timezone-aware, multi-step B2B outreach sequences using Gemini, validates them with Pydantic, enforces prospect-local business hours, generates JIT messages per step, and pauses for human approval before dispatch.

---

## How It Works

```
Input (contact, company, offer)
    │
    ▼
generate_sequence  ──→  Gemini generates JSON matching OutreachSequence schema
    │                    Self-correction loop: up to MAX_RETRIES (3) attempts
    │                    Server-side step-count enforcement (DEFAULT_MAX_TOUCHES)
    │                    Falls back to SAFE_FALLBACK_SEQUENCE (2 steps) after max retries
    ▼
sandbox_sequence   ──→  Enforces prospect-local business hours (8:00–18:00 local)
    │                    Converts UTC→local, clips timing, converts back
    │                    Audit trail of every adjustment
    ▼
prepare_temporal   ──→  Converts validated sequence to Temporal workflow payload
    │
    ▼
dispatch_to_temporal ── PAUSED (interrupt_before)
    │                    Resumes via POST /api/approve/{thread_id}
    ▼
Done
```

**Note:** The retry/fallback logic is in the graph (builder.py), not in generate_sequence() itself. The node function does ONE pass and returns; the graph decides whether to retry or stop based on `validated_sequence` and `retry_count`.

Built with **LangGraph** (StateGraph + MemorySaver checkpointer), **FastAPI**, **Gemini API**, **Pydantic v2**.

---

## Project Structure

```
sequence generator/
├── graph/
│   ├── state.py                       # GraphState (Pydantic model, all pipeline state)
│   ├── builder.py                     # LangGraph graph compilation, interrupt, approval helper
│   └── nodes/
│       ├── sequence_generator_node.py # Gemini call, language/timezone detection, self-correction
│       ├── sandbox_node.py            # Timezone-aware business hours enforcement
│       └── message_generation_node.py # JIT message generation per step (calls message generator)
├── models/
│   └── outreach_step.py              # ActionType enum, OutreachStep, OutreachSequence (Pydantic)
├── config/
│   └── constants.py                   # Country→language map, country→timezone map, scheduling limits
├── tools/
│   ├── language_detector.py          # Language detection from country + Gemini fallback
│   ├── mcp_client.py                 # MCP + REST client for the message generator
│   ├── hunter_client.py              # Email finder (Hunter.io)
│   ├── scraper.py                    # Web scraping stub
│   └── tavily_client.py              # Tavily search client
├── middleware/
│   └── token_counter.py              # Token usage estimation
├── observability/
│   └── logging_config.py            # Structured logging setup
├── temporal/
│   └── payload_adapter.py           # Temporal workflow input contract adapter
├── scripts/
│   ├── api_server.py                 # FastAPI REST API (port 8001)
│   ├── app.py                        # CLI entry point
│   └── app_sequences.py             # Streamlit UI
├── tests/
│   ├── test_outreach_step.py        # Model validation tests
│   ├── test_sandbox.py              # Sandbox business hours tests
│   └── test_language_detection.py   # Language detection from country/city tests
├── .env                              # Environment variables (GOOGLE_API_KEY, etc.)
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Quickstart

### Option A — No Docker (2 terminals)

**Terminal 1** — Message Generator (port 8000):
```bash
cd "message generator and sender"
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2** — Sequence Generator (port 8001):
```bash
cd "sequence generator"
pip install -r requirements.txt
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001
```

### Option B — Docker (with Temporal)

```bash
docker-compose up --build
```

---

## API

### `POST /api/generate/sequence`

Generate a full outreach sequence for a prospect.

**Request body:**

| Field | Type | Default | Description |
|---|---|---|---|
| `lead_id` | string | auto-generated | Unique lead identifier |
| `campaign_id` | string | `"default_campaign"` | Campaign identifier |
| `company` | string | required | Prospect's company name |
| `contact` | object | required | See ContactInfo below |
| `web_context` | object | `{}` | Prospect research, offer context, ICP description |
| `sender_info` | object | `{company_name: "My Company"}` | Sender's company, offer, CTA |
| `approval_mode` | string | `"per_sequence"` | `per_sequence`, `per_step`, or `per_step_and_message` |
| `use_native_language` | bool | `false` | Generate messages in prospect's language (auto-detected from country) |
| `message_language` | string? | `null` | Explicit ISO 639-1 override (e.g. `"fr"`) — forces `use_native_language` to true |

**ContactInfo:**

| Field | Type | Default | Description |
|---|---|---|---|
| `full_name` | string | required | Prospect's full name |
| `job_title` | string | `""` | Job title / role |
| `email` | string | `""` | Email address |
| `country` | string | `""` | Country — used for timezone + language detection |
| `city` | string | `""` | City |
| `location` | string | `""` | Full location string |
| `is_connected_on_linkedin` | bool | `false` | If `false`, first LinkedIn step is `LINKEDIN_CONNECT` (connection request). If `true`, uses `LINKEDIN_MESSAGE`. |

**Response:** Returns the full sequence with per-step messages, local timestamps, sandbox adjustments, and a `thread_id` for human approval.

### `POST /api/approve/{thread_id}`

Resume a paused sequence after human review. The graph pauses at `dispatch_to_temporal` — this endpoint resumes it and dispatches to Temporal.

### `GET /health`

Returns `{"status": "ok", "service": "sequence-generator"}`.

Swagger UI: `http://localhost:8001/docs`

---

## Language Detection

1. If `message_language` is set (e.g. `"fr"`), that code is used directly.
2. Otherwise, the prospect's `country` / `location` / `city` is matched against `COUNTRY_LANGUAGE_MAP` (60+ countries in `config/constants.py`).
3. If no match, Gemini is called to infer the language from the prospect's name and location.
4. If Gemini also fails, defaults to `"en"` (English).

**How `use_native_language` works:**
- `false` (default): Messages are generated in English. `message_language` on steps is set to `"en"`.
- `true`: Messages use the detected language. `message_language` on each step is set to the detected ISO code.
- Explanations (`timing_justification`, `sequence_architecture_rationale`) are **always in English** regardless.

**Note:** Language is passed to the message generator via the `message_language` field in the step context. The message generator currently does not have a `message_language` parameter in its API — this is a planned integration point.

---

## Timezone Detection

1. The prospect's `country` / `location` is matched against `COUNTRY_TIMEZONE_MAP` (50+ countries in `config/constants.py`).
2. If no match, defaults to UTC+0.
3. DST is **not** modeled — uses approximate standard-time offsets.

The detected timezone is used by the **sandbox** to enforce prospect-local business hours.

---

## Sandbox (Business Hours Enforcement)

The sandbox is the **authoritative enforcer** of scheduling rules. It operates in the prospect's local timezone:

1. Converts each step's UTC timestamp to the prospect's local time.
2. Checks if it falls within **08:00–18:00 local** on a **weekday**.
3. If outside business hours or on a weekend, rolls forward to the next valid slot.
4. Clips `wait_delay_seconds` to `[3600s (1h), 1209600s (14d)]`.
5. Recomputes `scheduled_timestamp` for subsequent steps based on adjusted delays.
6. Records every adjustment in `sandbox_adjustments` with original/adjusted values and reason.

**Important:** The Pydantic `OutreachStep` validator intentionally does NOT enforce business hours — it only checks that timestamps are timezone-aware UTC. The sandbox is the sole enforcer because UTC-only checks would break for non-UTC prospects (e.g., EST local 6pm = 23:00 UTC).

---

## LinkedIn Connection Awareness

The `is_connected_on_linkedin` field controls LinkedIn step behavior:

- **`false` (default):** The Gemini prompt explicitly instructs: *"you MUST use `LINKEDIN_CONNECT` for the first LinkedIn step, NOT `LINKEDIN_MESSAGE`"*. This sends a connection request first.
- **`true`:** No such restriction — Gemini can use `LINKEDIN_MESSAGE` directly.

The connection status is also passed to the message generator via `step_context.is_connected_on_linkedin`.

---

## Human-in-the-Loop

The graph is compiled with `interrupt_before=["dispatch_to_temporal"]` and uses LangGraph's `MemorySaver` checkpointer.

1. `POST /api/generate/sequence` runs the pipeline up to (but not including) `dispatch_to_temporal`.
2. Response includes `status: "awaiting_approval"` and a `thread_id`.
3. User reviews the sequence (steps, messages, sandbox adjustments).
4. `POST /api/approve/{thread_id}` resumes the graph from the checkpoint and dispatches.

---

## JIT Message Generation

After sandboxing, the `generate_messages` node iterates through each step and calls the **message generator API** (`http://localhost:8000/api/generate/simple`) for just-in-time message generation.

**Intent/Stage mapping** (action type → message generator enums):

| ActionType | → Intent | → Stage |
|---|---|---|
| `LINKEDIN_CONNECT` | `direct_outreach` | `first_touch` |
| `EMAIL_1` | `direct_outreach` | `first_touch` |
| `LINKEDIN_MESSAGE` | `direct_outreach` | `second_touch` |

**Note:** The message generator's `Intent` enum supports: `direct_outreach`, `follow_up`, `referral`, `re_engagement`, `event_based`. Its `Stage` enum supports: `first_touch`, `second_touch`, `third_touch`, `nurture`.

If the message generator is not running, message generation fails per-step but the sequence itself is still produced.

---

## Self-Correction Loop

1. Gemini generates JSON matching the `OutreachSequence` Pydantic schema.
2. `OutreachSequence.model_validate_json()` validates the response.
3. Server-side step-count enforcement: if the sequence has more steps than `effective_max_touches` (either `max_touches` from the request or `DEFAULT_MAX_TOUCHES` from env), it's rejected with a `ValueError`.
4. On failure (validation error or step-count exceeded): error is appended to `validation_errors`, `retry_count` is incremented, and the graph routes back to `generate_sequence` for another attempt.
5. After `MAX_RETRIES` (default: 3) failed attempts: the graph stops retrying and the caller receives `SAFE_FALLBACK_SEQUENCE` (2 steps: LINKEDIN_CONNECT + EMAIL_1).

**Important:** The retry loop is in the graph (builder.py), not in `generate_sequence()` itself. The node function does ONE pass and returns; the graph decides whether to retry based on `validated_sequence` and `retry_count`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | yes | Gemini API key |
| `GEMINI_MODEL` | no | Default: `gemini-3.1-flash-lite-preview` |
| `GEMINI_FALLBACK_MODEL` | no | Default: `models/gemma-3-27b-it` |
| `GEMINI_TEMPERATURE` | no | Default: `0.7` |
| `GEMINI_MAX_TOKENS` | no | Default: `2048` |
| `DEFAULT_MAX_TOUCHES` | no | Default: `5`. Maximum sequence length when caller doesn't specify `max_touches`. Server-side enforced. |
| `MESSAGE_GENERATOR_URL` | no | Message generator base URL. Default: `http://localhost:8000` |
| `DEBUG_MODE` | no | Default: `true` — bypasses memory reads/writes in the message generator for deterministic testing. The orchestrator pushes this value to both modules at runtime (so `outreach orchestrator/.env` takes precedence). Set to `false` for production |

---

## ActionType Enum

| Value | Description |
|---|---|
| `LINKEDIN_CONNECT` | LinkedIn connection request (used when not connected) |
| `LINKEDIN_MESSAGE` | LinkedIn DM (used when already connected) |
| `EMAIL_1` | Email touch |

## Valid Channels

`email`, `linkedin_dm`, `linkedin_inmail`

---

## Testing

```bash
cd "sequence generator"
.\venv\Scripts\python.exe -m pytest tests/ -v
```

---

## Key Design Decisions

- **Pydantic does NOT enforce business hours** — the sandbox is the authoritative enforcer (timezone-aware).
- **Language explanations always English** — `timing_justification` and `sequence_architecture_rationale` are never translated.
- **`is_connected_on_linkedin` defaults to `false`** — safer default: always send connection request first.
- **Graph pauses before dispatch** — human reviews the full sequence + generated messages before anything is sent.
- **`step_context` on every step** — carries prospect info, offer info, and connection status for JIT message generation.
- **Fallback sequence is validated on module load** — guaranteed to always pass validation.

---

## Memory & Debug Mode

### DEBUG_MODE — `.env` files where it's defined

| File | Default | Role |
|------|---------|------|
| `sequence generator/.env` | `true` | Fallback — used when calling sequence generator directly |
| `message generator and sender/.env` | `true` | Directly controls memory reads/writes |
| `outreach orchestrator/.env` | `true` | **Source of truth** — pushed to both modules at runtime |

### Debug Mode (`DEBUG_MODE=true`, default)

During development/testing, memory can pollute results — accumulated hooks/angles from previous test runs make the strategist avoid hooks that were "used" in debug sessions, not real outreach.

When `DEBUG_MODE=true`:
- The message generator **bypasses all memory reads** — every generation starts fresh
- The message generator **skips all memory writes** — no data accumulates across test runs
- **`do_not_contact` is still enforced** — hard stop regardless of debug mode
- This ensures **deterministic, repeatable results**

When `DEBUG_MODE=false` (production):
- Full memory active — the system avoids repeating hooks/angles, learns from performance over time
- Prospect memory, learning memory, and offer memory are all read and written

### How propagation works

When the orchestrator receives a request with `"debug_mode": true`, its `apply_config_overrides` node pushes `DEBUG_MODE` to both the sequence generator and message generator via REST config override. The orchestrator's `.env` value takes precedence over the individual module `.env` values.

You can also override per-request in the API payload:
```json
{"debug_mode": false, "lead_id": "..."}
```

### Memory Management Endpoints

Both APIs expose memory management endpoints (the sequence generator proxies to the message generator):

| Endpoint | Method | Description |
|---|---|---|
| `/api/memory/status` | GET | See what's stored: debug_mode, backend type, prospect/offer counts, learning stats |
| `/api/memory/flush` | POST | Wipe ALL memory + reset LangGraph checkpointer. Returns what was deleted |

### Where Sequences Are Stored

- **LangGraph MemorySaver** (in-memory): Stores graph state between nodes and for the human-in-the-loop interrupt. Each request gets a unique `thread_id`. The `/api/memory/flush` endpoint resets the MemorySaver.
- **Message Generator Redis/In-Memory**: Stores prospect memory, learning memory, and offer memory. The `/api/memory/flush` endpoint wipes all keys.

### Switching to Production

Set in **all three** `.env` files (`sequence generator/.env`, `message generator and sender/.env`, `outreach orchestrator/.env`):
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