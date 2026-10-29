# Agent-to-Agent (A2A) Communication Architecture

## Overview

This project consists of **three** services in a hierarchical orchestrator pattern:

1. **Outreach Orchator** (port 8002) — top-level coordinator, exposes a unified API and MCP interface for external/global orchestrators.
2. **Sequence Generator** (port 8001) — LangGraph agent that designs multi-step outreach sequences ("WHEN and WHAT channel").
3. **Message Generator** (port 8000) — LangGraph agent pipeline that writes individual messages ("HOW to write the best message").

```
┌─────────────────────────────────────────────────────────────┐
│           OUTREACH ORCHESTRATOR (port 8002)                  │
│                                                              │
│  REST /api/run  →  delegates to SeqGen  →  aggregates obs.  │
│  MCP SSE endpoint for external global orchestrators         │
└────────────────────────┬────────────────────────────────────┘
                         │  REST (POST /api/generate/sequence)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│         SEQUENCE GENERATOR (port 8001)                       │
│                                                              │
│  generate_sequence → sandbox → prepare_payload → dispatch   │
│                                                              │
│  "WHEN to reach out, WHAT channel, WHAT timing"             │
│  Temporal durable execution for step dispatch + JIT msgs    │
└────────────────────────┬────────────────────────────────────┘
                         │  MCP / REST (per-step delegation)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│       MESSAGE GENERATOR (port 8000)                          │
│                                                              │
│  planner → researcher → strategist → writer → critic        │
│                                                              │
│  "HOW to write the best message for this context"           │
└─────────────────────────────────────────────────────────────┘
```

## Responsibility Breakdown

| Concern | Outreach Orchestrator | Sequence Generator | Message Generator |
|---|---|---|---|
| **Role** | Unified entry point, delegates to SeqGen, aggregates observability | Multi-step sequence design, channel selection, timing | Per-message tone, angle, hook selection |
| **Strategy** | None — delegates entirely | Multi-step sequence design, channel selection, timing | Per-message tone, angle, hook selection |
| **Timing** | None | Timezone-aware scheduling, business hours, wait delays | None — timing-agnostic |
| **Lifecycle** | Pipeline state tracking | Human approval gates, Temporal durable execution, retries | Single request → single response |
| **Language** | Passes through | Detects language, decides `use_native_language` flag | Writes the message in the requested language |
| **Quality** | None | Sandbox enforces hard constraints (timing limits) | Critic agent scores & iterates the message |
| **State** | Pipeline-level status | Full sequence state across days/weeks | Stateless per-request (or short-term memory) |

## Communication Protocols

### Transport Layers

1. **MCP Protocol** (cross-platform agent interop)
   - Message Generator server: `message generator and sender/app/mcp_server.py`
   - Tool exposed: `generate_outreach`
   - Transport: stdio or SSE (`/mcp` endpoint)
   - Client: `sequence generator/tools/mcp_client.py`
   - Outreach Orchestrator also exposes its own MCP SSE endpoint at `/mcp`

2. **REST API** (primary inter-service communication)
   - Orchestrator → Sequence Generator: `POST http://localhost:8001/api/generate/sequence`
   - Sequence Generator → Message Generator: `POST http://localhost:8000/api/generate/simple` (via MCP client or REST fallback)
   - Content-Type: `application/json`

### Direction

Communication is **strictly unidirectional** at each layer:

```
Orchestrator  ──request──▶  Sequence Generator  ──request──▶  Message Generator
Orchestrator  ◀──response──  Sequence Generator  ◀──response──  Message Generator
```

The Message Generator **never** calls back to the Sequence Generator. The Sequence Generator **never** calls back to the Orchestrator. Each is a pure function at its level: given structured context, produce a result.

## The Contract

### Sequence Generator → Message Generator (per-step request)

```json
{
  "target_prospect": "Amira Ben Salah",
  "target_company": "NovaTech Solutions",
  "prospect_role": "Marketing Director",
  "channel": "email",
  "stage": "first_touch",
  "intent": "direct_outreach",
  "message_language": "ar",
  "company_details": {
    "company_name": "OutreachAI",
    "elevator_pitch": "We help B2B teams automate personalized outreach..."
  },
  "selected_offer": {
    "offer_name": "Outreach Automation Audit",
    "solution_summary": "A free audit of your current outreach process...",
    "cta": "Would you be open to a 15-minute call?"
  },
  "personality": {
    "analysis": "Data-driven, strategic thinker",
    "strategy_notes": "Focus on European expansion ROI",
    "approach_angle": "Digital transformation expertise"
  }
}
```

**Key fields set by the Sequence Generator:**
- `channel` — derived from the sequence step's `action_type`
- `stage` — mapped: `first_touch`, `second_touch`, `third_touch`, `breakup`, `nurture`
- `intent` — mapped from ActionType: `direct_outreach`, `follow_up`, `referral`, `re_engagement`, `event_based`
- `message_language` — only set when `use_native_language=true` in the sequence request

### Message Generator response

```json
{
  "success": true,
  "message": "the written outreach message body...",
  "subject": "email subject line (for email channels)",
  "score": 85
}
```

## Language Handling

The `use_native_language` flag (on the sequence generation request) controls language behavior:

| `use_native_language` | Explanations (justifications, rationale) | Messages (actual outreach text) |
|---|---|---|
| `false` (default) | English | English |
| `true` | English | Prospect's detected language |

**Explanations are always in English.** Only the actual outreach message content (`message_language` field) changes based on the flag.

## Temporal Workflow (Sequence Generator → Message Generator JIT)

After human approval, the Sequence Generator dispatches the validated sequence to **Temporal.io** for durable execution. The Temporal workflow (`SequenceWorkflow`) orchestrates:

1. Research company activity (Gemini-powered)
2. Generate strategy activity
3. Parse strategy into steps
4. **Per-step**: JIT message generation via `generate_message_activity` → calls Message Generator
5. Wait for scheduled time (`workflow.sleep`)
6. Send message activity

The Temporal worker runs on task queue `sequence-task-queue` and requires both the Temporal server and worker to be running for step execution.

## Design Principles

1. **Single Responsibility**: Each service has exactly one job. The Orchestrator delegates; the Sequence Generator plans sequences; the Message Generator writes messages.

2. **Loose Coupling**: Services communicate through well-defined JSON contracts. Neither needs to know the other's internals.

3. **Stateless per-request**: The Message Generator doesn't need to know "this is step 2 of 5." The Sequence Generator provides all context needed in each request.

4. **Independent Evolution**: You can swap any service's LLM, change its internal pipeline, or replace it entirely — as long as the contract stays the same, the other services don't care.

5. **MCP as Inter-Agent Protocol**: Both the Message Generator and the Orchestrator expose MCP tools, making them discoverable by any external agent (Claude, GPT, other LangGraph agents) without coupling to internal implementation.

## Running All Services

```bash
# Terminal 1: Message Generator (port 8000)
cd "message generator and sender"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Sequence Generator API (port 8001)
cd "sequence generator"
.\venv\Scripts\python.exe -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001

# Terminal 3: Outreach Orchestrator (port 8002)
cd "outreach orchestrator"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# Terminal 4 (optional): Temporal Worker (for real step execution)
cd "sequence generator"
.\venv\Scripts\python.exe scripts/worker.py
```

Once all are running:
- Orchestrator API: `POST http://localhost:8002/api/run`
- Sequence API: `POST http://localhost:8001/api/generate/sequence`
- Message Generator: `POST http://localhost:8000/api/generate/simple`
- MCP endpoints: `http://localhost:8000/mcp` and `http://localhost:8002/mcp`
- Swagger UIs: `http://localhost:8001/docs` and `http://localhost:8002/docs`
# Agent-to-Agent (A2A) Communication Architecture

## Overview

This project consists of two independent LangGraph agent systems that communicate via the **MCP (Model Context Protocol)** and **REST API** in an **Orchestrator-Specialist delegation** pattern.

```
┌─────────────────────────────────────────────────────┐
│         SEQUENCE GENERATOR (Orchestrator Agent)      │
│                                                      │
│  generate_sequence → sandbox → generate_messages     │
│       → prepare_temporal → dispatch_to_temporal      │
│                                                      │
│  "WHEN to reach out, WHAT channel, WHAT timing"      │
└────────────────────────┬────────────────────────────┘
                         │  MCP / REST (per-step delegation)
                         ▼
┌─────────────────────────────────────────────────────┐
│       MESSAGE GENERATOR (Specialist Tool Agent)      │
│                                                      │
│  planner → researcher → strategist → writer → critic │
│                                                      │
│  "HOW to write the best message for this context"    │
└─────────────────────────────────────────────────────┘
```

## Responsibility Breakdown

| Concern | Sequence Generator | Message Generator |
|---|---|---|
| **Strategy** | Multi-step sequence design, channel selection, timing | Per-message tone, angle, hook selection |
| **Timing** | Timezone-aware scheduling, business hours, wait delays | None — timing-agnostic |
| **Lifecycle** | Human approval gates, Temporal durable execution, retries | Single request → single response |
| **Language** | Detects language, decides `use_native_language` flag | Writes the message in the requested language |
| **Quality** | Sandbox enforces hard constraints (timing limits) | Critic agent scores & iterates the message |
| **State** | Full sequence state across days/weeks | Stateless per-request (or short-term memory) |

## Communication Protocol

### Transport Layers

1. **MCP Protocol** (Primary — cross-platform agent interop)
   - Server: `message generator and sender/app/mcp_server.py`
   - Tool exposed: `generate_outreach`
   - Transport: stdio or SSE (`/mcp` endpoint)
   - Client: `sequence generator/tools/mcp_client.py`

2. **REST API** (Fallback — used on Windows for reliability)
   - Endpoint: `POST /api/generate/simple` on port 8000
   - Content-Type: `application/json`

### Direction

Communication is **strictly unidirectional**:

```
Sequence Generator  ──request──▶  Message Generator
Sequence Generator  ◀──response──  Message Generator
```

The message generator **never** calls back to the sequence generator. It is a pure function: given structured context, produce a quality message.

## The Contract

### Request (what the Sequence Generator sends per step)

```json
{
  "target_prospect": "Amira Ben Salah",
  "target_company": "NovaTech Solutions",
  "prospect_role": "Marketing Director",
  "channel": "email",
  "stage": "first_touch",
  "intent": "direct_outreach",
  "message_language": "ar",
  "company_details": {
    "company_name": "OutreachAI",
    "elevator_pitch": "We help B2B teams automate personalized outreach..."
  },
  "selected_offer": {
    "offer_name": "Outreach Automation Audit",
    "solution_summary": "A free audit of your current outreach process...",
    "cta": "Would you be open to a 15-minute call?"
  },
  "personality": {
    "analysis": "Data-driven, strategic thinker",
    "strategy_notes": "Focus on European expansion ROI",
    "approach_angle": "Digital transformation expertise"
  }
}
```

**Key fields set by the Sequence Generator:**
- `channel` — derived from the sequence step's `action_type`
- `stage` — mapped: `first_touch`, `second_touch`, `third_touch`, `breakup`, `nurture`
- `intent` — mapped from ActionType: `direct_outreach`, `follow_up`, `referral`, `re_engagement`, `event_based`
- `message_language` — only set when `use_native_language=true` in the sequence request

### Response (what the Message Generator returns)

```json
{
  "success": true,
  "message": "the written outreach message body...",
  "subject": "email subject line (for email channels)",
  "score": 85
}
```

## Language Handling

The `use_native_language` flag (on the sequence generation request) controls language behavior:

| `use_native_language` | Explanations (justifications, rationale) | Messages (actual outreach text) |
|---|---|---|
| `false` (default) | English | English |
| `true` | English | Prospect's detected language |

**Explanations are always in English.** Only the actual outreach message content (`message_language` field) changes based on the flag.

## Design Principles

1. **Single Responsibility**: Each agent system has exactly one job. The sequence generator never writes messages; the message generator never plans sequences.

2. **Loose Coupling**: They communicate through a well-defined JSON contract. Neither needs to know the other's internals. The message generator is a black box tool.

3. **Stateless per-request**: The message generator doesn't need to know "this is step 2 of 5" or "the previous email was sent Tuesday." The sequence generator provides all context needed in each request.

4. **Independent Evolution**: You can swap the message generator's LLM, change its internal pipeline, or replace it entirely — as long as the contract stays the same, the sequence generator doesn't care.

5. **MCP as Inter-Agent Protocol**: The message generator exposes its pipeline as MCP tools, making it discoverable by any external agent (Claude, GPT, other LangGraph agents) without coupling to internal implementation.

## Running Both Services

```bash
# Terminal 1: Message Generator (port 8000)
cd "message generator and sender"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Sequence Generator API (port 8001)
cd "sequence generator"
.\venv\Scripts\python.exe -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001
```

Once both are running:
- Sequence API: `POST http://localhost:8001/api/generate/sequence`
- Swagger UI: `http://localhost:8001/docs`
- Message Generator: `POST http://localhost:8000/api/generate/simple`
- MCP endpoint: `http://localhost:8000/mcp`

The Sequence Generator automatically calls the Message Generator for JIT (just-in-time) message generation on each sequence step.
