# Agentic Outreach API

A multi-agent AI system that generates personalized sales outreach messages, validates them, waits for human approval, and sends them automatically via email or LinkedIn.

Built with FastAPI, LangGraph, Google Gemini, and MCP.

> **Note:** This module generates messages in **English only**. The sequence generator passes `message_language` in the step context, but this module's API does not currently have a `message_language` parameter — multilingual support is a planned integration.

---

## How It Works

A request comes in with a prospect, channel, offer, and sender personality. Five agents run in sequence inside a LangGraph pipeline:

```
Planner → Researcher → Strategist → Writer → Critic
                                         ↑         |
                                         └─REVISING─┘
```

1. **Planner** — looks at the current state and decides what to do next
2. **Researcher** — fetches LinkedIn posts, company news, CRM history, and loads prospect memory
3. **Strategist** — calls Gemini to pick the best hook and build a messaging strategy
4. **Writer** — calls Gemini to write the message, respects channel format rules and length limits, can emulate the sender's voice from past message samples
5. **Critic** — scores the message 0-100, runs hard rule checks (length, banned phrases, placeholders), loops back to the Writer with specific feedback if it fails

If `ENABLE_HUMAN_REVIEW=true`, the pipeline pauses after the Critic approves and waits for a human decision before sending.

---

## Channel Format Specifications

The Writer follows strict format rules for each channel to ensure platform-appropriate messages:

| Channel | Max Chars | Subject Line | Greeting | Structure | Formatting | Tone | CTA Style |
|---------|-----------|--------------|----------|-----------|------------|------|----------|
| **LinkedIn DM** | 300 | No | Informal ("Hi [Name],") | 1. Hook 2. Value 3. Question | Max 2 short paragraphs. No signature. | Peer-to-peer, conversational | Open-ended ("Worth a look?") |
| **LinkedIn InMail** | 600 | Required | Semi-formal ("Hi [Name],") | 1. Subject 2. Why now 3. Value 4. CTA | Bullet points OK. Max 150 words. | Professional, authoritative | Specific request ("Open to a chat Tuesday?") |
| **Email** | 800 | Required | Professional ("Hi/Hello [Name],") | 1. Problem hook 2. Social proof 3. CTA | Standard email format. Signature required. | Warm, professional | Interest-based ("Mind if I send a video?") |

The Writer receives these format requirements **before** writing, ensuring correctly-formatted messages on the first attempt and reducing wasteful critic iterations.

---

## Project Structure

```
agentic-outreach/
├── app/
│   ├── main.py          # FastAPI endpoints + human review routes
│   ├── models.py        # All Pydantic models and enums
│   ├── config.py        # Settings loaded from .env
│   ├── agents.py        # Agent logic (Planner, Researcher, Strategist, Writer, Critic)
│   ├── orchestrator.py  # Builds initial state, delegates to LangGraph
│   ├── graph.py         # LangGraph StateGraph — wires agents and routing
│   ├── llm_service.py   # All Gemini API calls with exponential backoff
│   ├── tools.py         # Research tools (mock + real API stubs)
│   ├── memory.py        # Per-prospect + global learning memory
│   ├── send_tools.py    # Email (Gmail SMTP) and LinkedIn (Unipile) sending
│   └── mcp_server.py    # MCP server — exposes pipeline as tools for external agents
├── Dockerfile
├── docker-compose.yml
├── .env
├── .env.example
└── requirements.txt
```

---

## Quickstart

### Option 1 — Docker (recommended)

```bash
cp .env.example .env
# Fill in GOOGLE_API_KEY in .env
docker-compose up --build
```

### Option 2 — Local

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in GOOGLE_API_KEY in .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API is at `http://localhost:8000`
Swagger UI is at `http://localhost:8000/docs`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | yes | Gemini API key from [makersuite.google.com](https://makersuite.google.com/app/apikey) |
| `GEMINI_MODEL` | no | Default: `gemini-2.5-flash-lite-preview-06-17` (overridable via `.env`) |
| `GEMINI_FALLBACK_MODEL` | no | Default: `models/gemma-3-27b-it` — used if primary fails |
| `REDIS_URL` | no | Redis connection string (e.g., `redis://localhost:6379/0`). Falls back to in-memory if not set |
| `MIN_QUALITY_SCORE` | no | Default: `80` — minimum score for a message to pass |
| `MAX_ITERATIONS` | no | Default: `3` — max Writer→Critic revision cycles |
| `USE_MOCK_DATA` | no | Default: `true` — uses fake LinkedIn/news/CRM data |
| `ENABLE_HUMAN_REVIEW` | no | Default: `false` — pause pipeline for human approval before sending |
| `ENABLE_LEARNING_LOOP` | no | Default: `false` — when `true`, learning + offer memory are written on each generation |
| `DEBUG_MODE` | no | Default: `true` — bypasses all memory reads/writes so each request starts fresh. The orchestrator pushes this value at runtime (so `outreach orchestrator/.env` takes precedence). Set to `false` for production |
| `GMAIL_ADDRESS` | for email send | Your Gmail address |
| `GMAIL_APP_PASSWORD` | for email send | Gmail App Password (not your account password) |
| `UNIPILE_API_KEY` | for LinkedIn send | From your Unipile dashboard |
| `UNIPILE_DSN` | for LinkedIn send | e.g. `api4.unipile.com:13465` |
| `UNIPILE_DEFAULT_ACCOUNT_ID` | for LinkedIn send | Your connected LinkedIn account ID in Unipile |

---

## API Endpoints

### Generate a message

```
POST /api/generate/simple
```

Returns the final message, score, and warnings. If `ENABLE_HUMAN_REVIEW=true`, returns a `review_url` instead of sending immediately.

```json
{
  "target_prospect": "Sarah Chen",
  "target_company": "Ramp",
  "prospect_role": "VP of Sales",
  "channel": "linkedin_dm",
  "stage": "first_touch",
  "intent": "direct_outreach",
  "personality": {
    "base_template": "soft_sell",
    "personality_traits": ["curious", "direct"],
    "never_use_phrases": ["synergies", "circle back"],
    "touchdowns_per_message": 2,
    "urgency_level": 2,
    "humor_sarcasm": 3,
    "voice_samples": [
      "Hey John, saw your post about the Q3 push — respect. Curious if a quick chat makes sense?",
      "Not gonna pitch you hard — just thought our audit might save you some pain before the ramp-up."
    ]
  },
  "company_details": {
    "company_name": "SalesForce AI",
    "elevator_pitch": "We help SDR teams double their reply rates using AI personalization.",
    "social_proof": ["Used by 500+ sales teams"]
  },
  "selected_offer": {
    "offer_name": "SDR Efficiency Audit",
    "solution_summary": "A diagnostic of your SDR workflow with a prioritized action plan.",
    "proof_points": ["Teams saw 40% more meetings in 30 days"],
    "cta": "Open to a quick 15-min chat?"
  }
}
```

```
POST /api/generate        — same pipeline, returns full step-by-step history
```

### Human review (when ENABLE_HUMAN_REVIEW=true)

```
GET  /api/review/{task_id}            — see the draft waiting for approval
POST /api/review/{task_id}/decision   — approve or reject
```

Approve and send via email:
```json
{ "approved": true, "prospect_email": "sarah@ramp.com" }
```

Approve and send via LinkedIn:
```json
{ "approved": true, "prospect_linkedin_id": "ACoAAA..." }
```

Reject with feedback (triggers a rewrite):
```json
{ "approved": false, "feedback": "Too formal, make it more casual and shorter" }
```

---

## Agent Pipeline

The message generator runs a 5-agent pipeline. Each agent has a specific role:

### 1. Planner Agent
Decides which step to run next based on what's missing from the state.

### 2. Researcher Agent
**⚠️ HARD REQUIREMENT**: The Researcher agent does **NOT** fetch data itself. It **requires** `research_signals` to be provided via the API request from an external research module (e.g., Detective).

**What the Researcher does:**
- Loads prospect memory (hooks/angles already used, contact history)
- Checks `do_not_contact` flag — aborts if set
- **Validates that `research_signals` is provided** — fails if missing

**Research Signals Format:**
```json
{
  "research_signals": [
    {
      "type": "linkedin_post",
      "content": "Just hit a major milestone at Ramp...",
      "strength": "high",
      "source_url": "https://linkedin.com/posts/...",
      "timestamp": "2024-01-15T10:30:00Z",
      "why_relevant": "Recent professional activity showing current priorities"
    },
    {
      "type": "company_news",
      "content": "Ramp announces new AI-powered product features...",
      "strength": "high",
      "source_url": "https://techcrunch.com/...",
      "timestamp": "2024-01-14T08:00:00Z",
      "why_relevant": "Recent company developments"
    }
  ]
}
```

**Hook Types:**
- `linkedin_post` — Prospect's LinkedIn activity
- `company_news` — Company announcements/funding news
- `job_change` — Recent role changes
- `shared_connection` — Mutual LinkedIn connections
- `event_attendance` — Conference/webinar participation
- `content_engagement` — Blog posts, articles, GitHub activity

### 3. Strategist Agent
Analyzes the provided research signals and picks the best hooks and angles for the message. Uses memory to avoid repeating hooks/angles that were already used with this prospect.

### 4. Writer Agent
Generates the message using the strategy, personality config, and channel format rules. Uses memory to adjust tone for repeat contacts.

### 5. Critic Agent
Validates the message against quality criteria and hard rules. Post-LLM deterministic checks include:
- **Bracket placeholders** — `[Company]`, `[Name]`, `[Result]` (-40 points)
- **Template defaults** — `Sender Name`, `Sender Title`, etc. (-35 points)
- **Generic references** — "your company" when the actual name is known (-15 points)
- **Banned phrases** — from `never_use_phrases` in personality (-10 points each)
- **Hallucinated attachments** — "I've attached", "see attached" (-30 points)
- **Overpersonalization** — overly personal references that feel intrusive (-20 points)

Records results to memory after validation passes.

---

## Sender Voice Emulation

Pass `voice_samples` in the `personality` block — 3 to 5 real messages you've written before. The Writer will analyze your sentence rhythm, vocabulary, punctuation habits, and opening/closing patterns, then write in your voice instead of a generic AI tone.

---

## Memory System

The system maintains persistent memory using **Redis** (or in-memory fallback) to track prospect interactions and learn from performance over time.

### Debug Mode (`DEBUG_MODE=true`, default)

**Defined in these `.env` files:**

| File | Default | Role |
|------|---------|------|
| `message generator and sender/.env` | `true` | Directly controls memory reads/writes |
| `outreach orchestrator/.env` | `true` | **Source of truth** — pushed to both modules at runtime |

When `DEBUG_MODE=true`:
- **Memory reads are bypassed** — every request starts with a blank slate (no hooks used, no angles tried, no contact history)
- **Memory writes are skipped** — generating a message does NOT record it to prospect/learning/offer memory
- This ensures **deterministic, repeatable test results** during development
- `do_not_contact` flag is still honored (hard stop)

When `DEBUG_MODE=false` (production):
- Full memory reads — the system avoids repeating hooks/angles used in previous runs
- Full memory writes — each generation is recorded for future reference
- Learning memory feeds best-performing hooks/angles back into the strategist

### Memory Management Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/memory/status` | GET | See what's stored: debug_mode, backend type, prospect/offer counts, learning stats |
| `/api/memory/flush` | POST | Wipe ALL memory (prospect + learning + offer). Returns what was deleted |

### Configuration

Set `REDIS_URL` in `.env` to enable Redis persistence:
```env
REDIS_URL=redis://localhost:6379/0
```

If not set or Redis is unreachable, the system falls back to in-memory storage (data lost on restart).

### What Gets Stored (when `DEBUG_MODE=false`)

| Data Type | Purpose |
|-----------|--------|
| **Prospect Memory** | Per-prospect: hooks/angles used, contact count, last message, reply status, do-not-contact flag |
| **Learning Memory** | System-wide: best/worst performing hooks and angles, reply rates per channel/stage/template. Only written when `ENABLE_LEARNING_LOOP=true` |
| **Offer Memory** | Per-offer: usage count, avg quality score, best channels/angles/prospect roles. Only written when `ENABLE_LEARNING_LOOP=true` |

### How Each Agent Uses Memory

**Researcher Agent** (loads from memory — skipped in debug mode):
- Fetches prospect's `hooks_already_used` and `angles_already_tried`
- Checks `do_not_contact` flag — aborts if set
- Retrieves `times_contacted_before` and `last_message_sent`
- Loads `best_performing_hooks` and `best_performing_angles` from learning memory
- Loads offer performance data if available

**Strategist Agent** (reads from memory):
- Receives `hooks_already_used` → avoids picking the same hooks
- Receives `angles_already_tried` → avoids repeating the same angles
- Receives `best_performing_hooks` → prefers similar approaches
- Receives `best_performing_angles` → considers similar approaches

**Writer Agent** (reads from memory):
- Uses `times_contacted_before` to adjust tone for repeat contacts
- Uses `last_message_sent` to ensure the new message is clearly different

**Critic Agent** (writes to memory — skipped in debug mode):
- After validation passes, records:
  - `record_outreach()` — saves hook, angle, channel, stage, message
  - `record_generation()` — updates quality score stats (only if `ENABLE_LEARNING_LOOP=true`)
  - `record_usage()` — logs offer performance data (only if `ENABLE_LEARNING_LOOP=true`)

This prevents repetitive outreach and helps the system learn what messaging strategies work best.

---

## MCP — Agent-to-Agent

The pipeline is exposed as an MCP server at `/mcp` (SSE transport). Any external agent that speaks MCP (Claude Desktop, another LangGraph agent) can connect and call:

- `generate_outreach` — run the full pipeline
- `check_prospect` — look up prospect memory
- `mark_do_not_contact` — flag a prospect

The sequence generator calls this module via REST (`POST /api/generate/simple`) for JIT message generation of each step in a sequence.

Add to your `mcp.json`:
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

---

## Email Setup (Gmail SMTP — free)

1. Enable 2FA on your Google account
2. Go to `myaccount.google.com` → Security → App Passwords
3. Generate a password for "Mail"
4. Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env`

## Intent and Stage Enums

These are the valid values that the sequence generator maps to when calling this module:

**Intent:** `direct_outreach`, `follow_up`, `referral`, `re_engagement`, `event_based`

**Stage:** `first_touch`, `second_touch`, `third_touch`, `breakup`, `nurture`

> **Important:** Other values (e.g. `connection_request`, `meeting_request`) are NOT valid and will cause a 422 validation error.

---

## LinkedIn Setup (Unipile)

1. Sign up at [unipile.com](https://unipile.com)
2. Connect your LinkedIn account
3. Copy your DSN, API key, and account ID into `.env`
