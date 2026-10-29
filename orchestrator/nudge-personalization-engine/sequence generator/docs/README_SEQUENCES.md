# 🔄 Temporal Sequence Workflow System

## Overview

This system provides **multi-step outreach sequences** powered by Temporal, Gemini AI, and the Message Generator MCP. Unlike the single-shot analysis, sequences are:

- **AI-driven**: Gemini decides the timing (J+n), channels, and strategy
- **Persistent**: State survives crashes via Temporal
- **Human-gated**: You approve each step before sending
- **Context-aware**: Each message references previous steps

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit UI (app.py)                    │
│  ┌─────────────────┐  ┌─────────────────────────────────────┐│
│  │ Tab 1: Simple   │  │ Tab 2: Sequence Management          ││
│  │ (existing)      │  │ (new)                               ││
│  └─────────────────┘  └─────────────────────────────────────┘│
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                   Temporal Client (temporal_client.py)       │
│         Helper functions to interact with workflows          │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              Temporal Server (localhost:7233)                │
│    ┌──────────────────────────────────────────────────────┐ │
│    │  SequenceWorkflow (workflows/sequence_workflow.py)   │ │
│    │                                                      │ │
│    │  1. Research (Hunter + Tavily)                       │ │
│    │  2. Gemini Strategy (custom sequence plan)         │ │
│    │  3. Parse Gemini Output → Structured Steps         │ │
│    │  4. Generate Messages (MCP for each step)           │ │
│    │  5. Wait for Human Signals → Send                   │ │
│    │                                                      │ │
│    │  Signals: send_step, skip_step, regenerate_step     │ │
│    └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## New Files

| File | Purpose |
|------|---------|
| `workflows/sequence_workflow.py` | Main Temporal workflow (multi-step orchestration) |
| `workflows/message_activities.py` | Activities: research, strategy, generate, send |
| `temporal_client.py` | Streamlit integration helpers |
| `app_sequences.py` | Sequence management UI component |
| `worker.py` (updated) | Now registers SequenceWorkflow + activities |
| `workflows/__init__.py` (updated) | Exports new components |
| `app.py` (updated) | Two-tab interface (Simple + Sequences) |

## Gemini-Driven Sequence

Unlike hardcoded J+0, J+2, J+5, Gemini analyzes the prospect and decides:

```
Input: Company + Persona + ICP (from Detective)
   ↓
Gemini analyzes:
- LinkedIn activity score (%)
- Best time of day (10h-11h, 14h-16h)
- Personality (académique, décontracté, technique)
- Optimal channels per step
   ↓
Output: Custom sequence plan
- Step 1: Email, J+0 à 10h, "ton décontracté"
- Step 2: LinkedIn DM, J+3 à 14h, "valeur ajoutée"
- Step 3: Email, J+7 à 10h, "dernier essai"
```

## Usage

### 1. Start Dependencies

```bash
# Terminal 1: Temporal Server (must be running)
temporal server start-dev

# Terminal 2: Message Generator
cd "message generator and sender"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 3: Temporal Worker
cd "sequence generator"
python worker.py

# Terminal 4: Streamlit
cd "sequence generator"
streamlit run app.py
```

### 2. Create a Sequence

1. Open http://localhost:8501
2. Go to tab "📋 Séquences Multi-Étapes"
3. Upload Detective JSON or enter manually:
   - Company name
   - Persona (name, role, email)
   - ICP description
4. Click "🚀 Lancer la Séquence"
5. Copy the workflow ID

### 3. Monitor & Send

1. Paste workflow ID in "Séquences Actives" tab
2. Wait for generation (30s-2min):
   - Status: `researching` → `generating_strategy` → `generating_messages` → `ready`
3. When `ready`, you'll see all steps with:
   - Step number + channel
   - Timing (J+n at HHh)
   - Quality score
   - Message preview
   - Send/Skip/Regenerate buttons

### 4. Per-Step Actions

| Button | Action |
|--------|--------|
| **📤 Envoyer** | Sends the message via email or marks LinkedIn for manual send |
| **⏭️ Passer** | Skips this step (marks as skipped) |
| **🔄 Régénérer** | Regenerates with your feedback (e.g., "Trop formel") |

## Input Format (Detective Output)

```json
{
  "company_key": "bosch_us",
  "company_name": "Bosch in the USA",
  "selected_persona": {
    "full_name": "Jessica Katterheinrich",
    "job_title": "Sales Manager",
    "email": "jessica@bosch.com",
    "linkedin_url": "https://linkedin.com/in/...",
    "city": "Detroit",
    "country": "United States"
  },
  "icp_description": "I want IT companies with 50-500 employees..."
}
```

## Configuration

Add to `sequence generator/.env`:

```bash
# Temporal
TEMPORAL_HOST=localhost:7233

# Gemini (already set)
GOOGLE_API_KEY=your_key

# Debug mode (uses mock data, no API calls)
DEBUG_MCP_TESTING=false

# Sender info (used in message generation)
SENDER_COMPANY_NAME=Votre Entreprise
SENDER_ELEVATOR_PITCH=Nous aidons les entreprises à grandir.
DEFAULT_OFFER_NAME=Audit Gratuit
DEFAULT_OFFER_SUMMARY=Diagnostic personnalisé.
DEFAULT_OFFER_CTA=Réserver un appel de 15 minutes.
```

## Workflow State Machine

```
researching
    ↓
generating_strategy (Gemini)
    ↓
parsing_strategy (extract steps/timing)
    ↓
generating_messages (MCP calls)
    ↓
ready ←── You are here
    ↓ (after send signals)
in_progress
    ↓
completed / stopped
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot connect to Temporal" | Start Temporal: `temporal server start-dev` |
| "Worker not found" | Run `python worker.py` in sequence generator folder |
| "MCP connection failed" | Start message generator on port 8000 |
| "Gemini API error" | Check GOOGLE_API_KEY in .env |
| Steps stuck in "generating" | Check worker logs for errors |
| Message score < 80 | Use "Régénérer" with feedback |

## Differences from Single Analysis

| Feature | Single Analysis (Tab 1) | Sequence (Tab 2) |
|---------|-------------------------|-------------------|
| Steps | 1 message | 2-4 messages (Gemini decides) |
| Timing | Immediate | J+n with time-of-day |
| Persistence | In-memory only | Temporal (survives crashes) |
| Human review | One approval | Per-step approval |
| Context | One-shot | Cumulative (step 2 knows step 1) |
| Channels | Email or LinkedIn | Mixed per step |

## Future Enhancements

- [ ] Auto-send if score > 85
- [ ] Response detection (email/LinkedIn webhooks)
 [ ] A/B testing different message variants
- [ ] Scheduled sends (calendar integration)
- [ ] Multi-persona sequences (different people at same company)
