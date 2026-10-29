# End-to-End Testing Guide

Complete guide for testing the full outreach pipeline — from sending a JSON request (simulating the global orchestrator) through sequence generation, message generation, human-in-the-loop approval, and Temporal workflow execution.

---

## Quick Start: One Command Does Everything

Just double-click `start_full_testing.bat` in the project root (or run it from CMD):

```cmd
start_full_testing.bat
```

This single script:
1. Starts the **Temporal dev server** (if CLI is installed)
2. Starts all **3 API services** (Message Generator, Sequence Generator, Orchestrator)
3. Starts the **Temporal worker**
4. Waits for services to boot
5. **Opens all interfaces in your browser** automatically:
   - Temporal Web UI → http://localhost:8080
   - Message Generator Swagger → http://localhost:8000/docs
   - Sequence Generator Swagger → http://localhost:8001/docs
   - Orchestrator Swagger → http://localhost:8002/docs

When you're done testing, **press any key** in the launcher window to shut everything down cleanly.

---

## Full Setup (5 Terminals) — Manual

If you prefer to start services individually:

### Terminal 1: Temporal Dev Server

```bash
temporal server start-dev
```

This gives you the **Temporal Web UI at http://localhost:8080** where you'll see workflows, activities, signals, and step execution in real time.

> If you don't have the Temporal CLI: `winget install temporalio.cli` then restart your terminal.

### Terminals 2–4: All 3 API Services

Run `start_all_services.bat` from the project root — this opens 3 CMD windows:

- **Message Generator** → port 8000
- **Sequence Generator** → port 8001
- **Outreach Orchestrator** → port 8002

Or start them manually:

```cmd
:: Terminal 2: Message Generator
cd "message generator and sender"
.\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

:: Terminal 3: Sequence Generator
cd "sequence generator"
.\venv\Scripts\activate.bat
python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001

:: Terminal 4: Outreach Orchestrator
cd "outreach orchestrator"
..\venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### Terminal 5: Temporal Worker

```cmd
cd "sequence generator"
.\venv\Scripts\activate.bat
python scripts/worker.py
```

You should see: `Worker démarré ! ... En attente de tâches...`

---

## Test Path A: Via the Orchestrator (Simulates Global Orchestrator)

This is the path that simulates what the global orchestrator would send. It exercises the full chain: Orchestrator → Sequence Generator → Message Generator.

### Step 1: Send the Full Pipeline Request

Open **http://localhost:8002/docs** (Swagger UI) and POST to `/api/run`, or use curl:

```bash
curl -X POST http://localhost:8002/api/run ^
  -H "Content-Type: application/json" ^
  -d @test_payload.json
```

Create `test_payload.json` with this content (includes all sequence config fields):

```json
{
  "lead_id": "test-lead-001",
  "campaign_id": "campaign_q2_2026",
  "entreprise": "Ramp",
  "contact_info": {
    "full_name": "Sarah Chen",
    "nom": "Sarah Chen",
    "job_title": "VP of Sales",
    "titre": "VP of Sales",
    "email": "sarah.chen@ramp.com",
    "country": "United States",
    "city": "New York",
    "location": "New York, United States",
    "linkedin": "https://linkedin.com/in/sarahchen",
    "phone": ""
  },
  "contexte_web": {
    "profil_brut": "Sarah is VP of Sales at Ramp, a fintech company. Recently posted about scaling outbound sales teams and experimenting with AI-powered prospecting tools. Active on LinkedIn, engages with sales methodology content.",
    "offer_context": "AI-powered outreach automation platform that personalizes multi-channel sequences",
    "icp_description": "B2B SaaS companies with 50-500 employees, sales teams doing outbound prospecting"
  },
  "research_signals": [
    {
      "type": "recent_post",
      "content": "Posted about scaling SDR teams with AI tooling",
      "strength": "high",
      "why_relevant": "Directly related to our offer"
    },
    {
      "type": "job_change",
      "content": "Promoted to VP of Sales 3 months ago",
      "strength": "medium",
      "why_relevant": "New role likely means new budget and mandate to improve processes"
    }
  ],
  "is_connected_on_linkedin": false,
  "use_native_language": false,
  "message_language": null,
  "approval_mode": "per_sequence",
  "sender_company": "OutreachAI",
  "sender_elevator_pitch": "We help B2B sales teams automate personalized outreach across email and LinkedIn",
  "offer_name": "OutreachAI Pro",
  "solution_summary": "AI-powered multi-channel outreach sequences that write like your best SDR",
  "cta": "Book a 15-min demo to see it in action",
  "max_touches": 4,
  "max_days": 14,
  "preferred_first_channel": "linkedin_dm",
  "sequence_options": {
    "vary_tone": true,
    "include_breakup": true,
    "reference_previous": true,
    "escalate_urgency": true,
    "cross_channel": true
  },
  "stage_instructions": {
    "first_touch": "Be casual, reference their recent LinkedIn post about AI tooling, don't pitch yet",
    "second_touch": "Share a relevant insight about SDR team scaling, soft mention of our approach",
    "third_touch": "Be more direct, propose the demo, show specific value metrics"
  },
  "personality_config": {
    "base_template": "value_based",
    "personality_traits": ["Data-driven", "Direct"],
    "always_include_phrases": ["15-min demo", "AI-powered"],
    "never_use_phrases": ["game-changer", "revolutionary", "synergy"],
    "urgency_level": 4,
    "humor_sarcasm": 3,
    "touchdowns_per_message": 2
  },
  "debug_mode": true
}
```

### Step 2: Watch the Response

The orchestrator calls the sequence generator which:

1. Detects language (English) and timezone (EST, UTC-5)
2. Calls **Gemini** with your `max_touches=4`, `max_days=14`, `sequence_options`, and `stage_instructions` baked into the prompt
3. Sandboxes the result (business hours enforcement, weekend filtering)
4. Generates **JIT messages** for each step (calls message generator on port 8000 per step, forwarding `personality_config`)
5. Returns the full sequence with messages, scores, and timing

**The LangGraph graph then PAUSES at `dispatch_to_temporal`** (configured via `interrupt_before` in `builder.py`).

You'll get back a response containing:

- `status: "awaiting_approval"` (or `"completed"` depending on graph state)
- `thread_id: "api_thread_xxxxx"` ← **save this!**
- `sequence_result.steps` — the full sequence with messages, scores, timestamps
- `sequence_result.message_generation_summary` — success/failure counts

### Step 3: Human-in-the-Loop — APPROVE

If you're happy with the sequence:

```bash
curl -X POST http://localhost:8001/api/approve/{thread_id}
```

Replace `{thread_id}` with the actual `thread_id` from Step 2. This:

- Resumes the LangGraph graph from the interrupt point
- Dispatches the payload to **Temporal** (if the worker is running, you'll see it execute)
- Returns the final Temporal payload

### Step 3b: Human-in-the-Loop — REJECT & MODIFY

If you don't like the result:

**Option 1: Modify and re-submit**
Change the JSON payload (adjust `stage_instructions`, `sequence_options`, `max_touches`, etc.) and POST again to `/api/run`.

**Option 2: Inject feedback then re-submit**
```bash
curl -X POST http://localhost:8002/api/feedback ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"sequence_generator\", \"feedback\": \"Make the first touch more casual and less salesy. Reference the AI tooling post more specifically.\"}"
```
Then re-submit the same payload — the feedback gets prepended to the next Gemini prompt as a system directive.

---

## Test Path B: Directly via Sequence Generator

Skip the orchestrator and talk directly to the sequence generator. Useful for faster iteration and testing the sequence-level human-in-the-loop flow.

### Step 1: Generate Sequence

Open **http://localhost:8001/docs** (Swagger UI) and POST to `/api/generate/sequence`:

```json
{
  "lead_id": "test-lead-002",
  "campaign_id": "campaign_test",
  "company": "Notion",
  "contact": {
    "full_name": "Alex Rivera",
    "job_title": "Head of Growth",
    "email": "alex@notion.so",
    "country": "United States",
    "city": "San Francisco",
    "location": "San Francisco, United States",
    "linkedin": "",
    "is_connected_on_linkedin": true
  },
  "web_context": {
    "profil_brut": "Alex leads growth at Notion. Recently launched a new AI features suite. Active on Twitter and LinkedIn.",
    "offer_context": "AI outreach automation for B2B SaaS growth teams",
    "icp_description": "B2B SaaS growth leaders at companies with 100+ employees"
  },
  "sender_info": {
    "company_name": "OutreachAI",
    "elevator_pitch": "Automated personalized multi-channel outreach",
    "offer_name": "Growth Accelerator",
    "solution_summary": "AI sequences that write like your best SDR",
    "cta": "Grab 15 minutes to see the magic"
  },
  "approval_mode": "per_sequence",
  "max_touches": 3,
  "max_days": 10,
  "preferred_first_channel": "email",
  "sequence_options": {
    "vary_tone": true,
    "include_breakup": false,
    "reference_previous": true,
    "escalate_urgency": false,
    "cross_channel": true
  },
  "stage_instructions": {
    "first_touch": "Reference Notion's new AI features launch, be genuinely curious"
  },
  "personality_config": {
    "base_template": "consultative",
    "personality_traits": ["Storyteller", "Humble"],
    "never_use_phrases": ["disruptive", "game-changer"],
    "urgency_level": 2,
    "humor_sarcasm": 5
  },
  "research_signals": [
    {
      "type": "company_news",
      "content": "Notion launched AI-powered writing assistant",
      "strength": "high",
      "why_relevant": "Directly relevant to our AI outreach platform"
    }
  ]
}
```

### Step 2: Review & Approve/Reject

The response includes `status: "awaiting_approval"` and a `thread_id`.

- **Approve**: `POST http://localhost:8001/api/approve/{thread_id}`
- **Reject**: Re-submit with modified payload, or inject feedback first

---

## Watching Temporal in Action

Once you approve and the payload dispatches to Temporal:

1. Open **http://localhost:8080** (Temporal Web UI)
2. You'll see the workflow appear in the list
3. Click into it to see:
   - Each **activity** executing (research → strategy → parse → generate message → send)
   - Step-by-step execution timeline
   - Activity inputs/outputs
   - Any failures and retries

The Temporal worker (`worker.py`) processes these activities:

| Activity | What It Does |
|----------|-------------|
| `research_company_activity` | Company research and signal gathering |
| `generate_strategy_activity` | LLM-powered strategy generation |
| `parse_gemini_strategy_activity` | Parsing and validating the strategy |
| `generate_message_activity` | Message generation per step |
| `send_message_activity` | Actual send (email/LinkedIn) |

### Temporal Signals You Can Send

The temporal client (`temporal_client.py`) supports these signals for human-in-the-loop:

| Signal | Description |
|--------|-------------|
| `approve_sequence` | Approve the entire sequence (per_sequence mode) |
| `approve_step(step_num)` | Approve a specific step (per_step modes) |
| `send_step(step_num)` | Execute a specific step |
| `skip_step(step_num)` | Skip a specific step |
| `regenerate_step(step_num, feedback)` | Regenerate with feedback |
| `stop_sequence` | Stop the entire sequence |

---

## How to Run the Launcher

**Option 1: Double-click** `start_full_testing.bat` in the project root.

**Option 2: From CMD** (recommended so you can see the startup log):
```cmd
cd c:\Users\ASUS\Desktop\Outreach-Project
start_full_testing.bat
```

> Note: Run from CMD, not PowerShell — the `.bat` syntax requires Windows CMD.
> If you run from PowerShell, use: `cmd /c start_full_testing.bat`

The script opens 5 CMD windows (one per service) + 3-4 browser tabs automatically.
When you're done, **press any key** in the launcher window to kill all services.

---

## Logs & Debugging

### Where to See Logs

All logs print to **stdout in each service's CMD window** (the ones opened by the launcher):

| Window | What You See |
|--------|-------------|
| **Message Generator** (port 8000) | Python logging — LLM calls, quality scores, errors, token counts |
| **Sequence Generator** (port 8001) | **Structured JSON logs** via `observability/logging_config.py` — every node execution, Gemini calls, validation results, sandbox adjustments |
| **Outreach Orchestrator** (port 8002) | Pipeline orchestration, inter-module calls, error handling |
| **Temporal Server** | Temporal workflow execution, activity scheduling |
| **Temporal Worker** | Activity execution (research, strategy, message gen, send) |

### Sequence Generator JSON Logs

The sequence generator uses structured JSON logging (via `logging_config.py`). Each log line looks like:

```json
{
  "timestamp": "2026-06-16T14:23:45.123456",
  "level": "INFO",
  "message": "Sequence generated successfully",
  "name": "outreach_sequencer",
  "correlation_id": "test-lead-001",
  "funcName": "generate_sequence",
  "lineno": 142
}
```

Extra fields like `correlation_id`, `payload_preview`, `validation_errors`, and `dispatched_payload` are included automatically.

### Adjust Log Level

```bash
# Change log level at runtime (affects next calls)
curl -X POST http://localhost:8002/api/config/override ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"sequence_generator\", \"overrides\": {\"LOG_LEVEL\": \"DEBUG\"}}"
```

Or set `LOG_LEVEL=DEBUG` in the `.env` files before starting.

---

## Token Counter & Observability

### Where Token Counts Are Displayed

Token usage is tracked via the `PromptStore` observability system and exposed through REST endpoints. **The token counter counts whitespace-separated words as a proxy for tokens.**

#### Per-Module Token Summary

| Endpoint | Module | What It Returns |
|----------|--------|----------------|
| `GET http://localhost:8000/api/observability` | Message Generator | `total_tokens`, `total_tokens_in`, `total_tokens_out`, avg latency, success rate, calls by agent step |
| `GET http://localhost:8001/api/observability` | Sequence Generator | Same metrics for Gemini calls |
| `GET http://localhost:8002/api/observability` | Orchestrator (merged) | **Combined** totals from both modules |

#### Per-Call Token Detail (Prompt History)

| Endpoint | Module |
|----------|--------|
| `GET http://localhost:8000/api/observability/prompts` | Message Generator — each LLM call with prompt, response, `tokens_in`, `tokens_out`, model used, latency |
| `GET http://localhost:8001/api/observability/prompts` | Sequence Generator — each Gemini call with full prompt and token counts |
| `GET http://localhost:8002/api/observability/prompts` | Orchestrator — merged history from both modules |

Filter by agent step:
```bash
curl "http://localhost:8000/api/observability/prompts?agent_step=writer&limit=10"
```

#### Clear Observability Data

```bash
curl -X POST http://localhost:8001/api/observability/clear
curl -X POST http://localhost:8000/api/observability/clear
```

### What Gets Tracked

Every LLM/Gemini call is recorded as a `PromptRecord` with:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO-8601 UTC |
| `agent_step` | Which step: `planner`, `researcher`, `strategist`, `writer`, `critic`, `sequence_generator` |
| `prompt` | Full prompt sent to the LLM |
| `system_instruction` | System prompt / instruction |
| `response` | LLM response text |
| `tokens_in` | Estimated input tokens count |
| `tokens_out` | Estimated output token count |
| `model_used` | `primary` or `fallback` |
| `latency_ms` | Call duration in milliseconds |
| `success` | Whether the call succeeded |
| `error` | Error message if failed |

---

## Useful Debug Commands

```bash
# Check health of all services
curl http://localhost:8002/api/health

# See what prompts Gemini actually received (merged from both modules)
curl http://localhost:8002/api/observability/prompts

# See prompts from a specific module
curl http://localhost:8001/api/observability/prompts
curl http://localhost:8000/api/observability/prompts

# Flush all memory between test runs (resets both modules)
curl -X POST http://localhost:8001/api/memory/flush

# Override Gemini temperature for testing
curl -X POST http://localhost:8002/api/config/override ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"sequence_generator\", \"overrides\": {\"GEMINI_TEMPERATURE\": \"0.3\"}}"

# Check capabilities (agent card)
curl http://localhost:8002/api/capabilities
```

---

## Request Field Reference

### AI Sequence Configuration (new fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_touches` | int \| null | null | Maximum number of steps. AI decides if omitted. |
| `max_days` | int \| null | null | Maximum days the sequence can span. AI decides if omitted. |
| `preferred_first_channel` | string \| null | null | Preferred channel for step 1 (`email`, `linkedin_dm`, `linkedin_inmail`). |
| `sequence_options` | dict \| null | null | Boolean flags: `vary_tone`, `include_breakup`, `reference_previous`, `escalate_urgency`, `cross_channel` |
| `stage_instructions` | dict \| null | null | Per-stage custom instructions: `{"first_touch": "Be casual...", "second_touch": "..."}` |
| `personality_config` | dict \| null | null | Message personality forwarded to Message Generator (see below) |

### Personality Config Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_template` | string | `soft_sell` | Foundation style: `soft_sell`, `value_based`, `spin_selling`, `direct`, `consultative`, `custom` |
| `personality_traits` | list[str] | [] | Trait adjectives: e.g. `["Data-driven", "Witty/Sarcastic"]` |
| `always_include_phrases` | list[str] | [] | Phrases AI must weave in naturally |
| `never_use_phrases` | list[str] | [] | Banned words/phrases |
| `urgency_level` | int (1-10) | 3 | How urgent the message feels |
| `humor_sarcasm` | int (1-10) | 3 | How much humor/light sarcasm |
| `touchdowns_per_message` | int (1-5) | 2 | Distinct value/hook touchpoints per message |
| `voice_samples` | list[str] | [] | Real messages by the sender for voice matching |
| `stage_instructions` | dict | {} | Per-stage instruction overrides within personality |

### Existing Key Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `contact.is_connected_on_linkedin` | bool | false | If false, first LinkedIn step = `LINKEDIN_CONNECT` |
| `use_native_language` | bool | false | If true, messages in prospect's detected language |
| `message_language` | string \| null | null | Explicit ISO 639-1 override (e.g. `"fr"`) |
| `approval_mode` | string | `per_sequence` | `per_sequence`, `per_step`, or `per_step_and_message` |
| `debug_mode` | bool | true | Bypasses memory for deterministic runs (see below) |

---

## DEBUG_MODE — What It Does and Where It Lives

`DEBUG_MODE` controls whether the message generator's memory system is active. It's defined in **all three** `.env` files:

| File | Default | Role |
|------|---------|------|
| `message generator and sender/.env` | `true` | Directly controls memory reads/writes |
| `sequence generator/.env` | `true` | Propagated downstream to message generator |
| `outreach orchestrator/.env` | `true` | **Source of truth** — pushed to both modules at runtime |

### `DEBUG_MODE=true` (default — you want this for testing)

- Every message generation starts from a **clean slate** — no accumulated hooks, angles, or prospect history
- Test runs are **deterministic and repeatable**
- `do_not_contact` lists are still enforced (hard stop)

### `DEBUG_MODE=false` (production)

- Full memory active — the system reads prospect history, avoids repeating hooks/angles
- Learning loop tracks quality scores over time (requires `ENABLE_LEARNING_LOOP=true`)
- Results change based on accumulated history

### How it propagates

The orchestrator's `apply_config_overrides` node pushes `DEBUG_MODE` to both modules via REST before each pipeline run. You can also override per-request:

```json
{
  "debug_mode": false,
  "lead_id": "..."
}
```

This overrides the `.env` default for that single call only.

### Switch to production mode

Set in **all three** `.env` files, then restart:
```env
DEBUG_MODE=false
ENABLE_LEARNING_LOOP=true
```

Or override at runtime (no restart needed):
```bash
curl -X POST http://localhost:8002/api/config/override ^
  -H "Content-Type: application/json" ^
  -d "{\"module\": \"message_generator\", \"overrides\": {\"DEBUG_MODE\": \"false\"}}"
```

---

## Quick Start Checklist

| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Start Temporal: `temporal server start-dev` | Temporal UI at http://localhost:8080 |
| 2 | Run `start_all_services.bat` | 3 CMD windows open (ports 8000, 8001, 8002) |
| 3 | Verify health: `curl http://localhost:8002/api/health` | Both modules show online |
| 4 | Start worker: `python scripts/worker.py` | "Worker démarré !" message |
| 5 | POST test payload to `http://localhost:8002/api/run` | Get response with `thread_id` |
| 6 | Review the sequence steps and messages | Check quality scores, timing, channels |
| 7 | Approve: `POST /api/approve/{thread_id}` | Dispatch to Temporal |
| 8 | Watch Temporal UI at http://localhost:8080 | See workflow activities executing |
| 9 | Flush memory: `POST /api/memory/flush` | Clean state for next test |
| 10 | Modify payload and repeat | Iterate on sequence quality |
