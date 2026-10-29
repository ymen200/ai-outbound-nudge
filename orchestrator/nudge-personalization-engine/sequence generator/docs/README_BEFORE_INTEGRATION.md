# Sequence Generator - MCP Integration Complete ✅

## Overview

The Sequence Generator is an AI-powered B2B prospecting intelligence system that analyzes target companies, identifies decision-makers, and generates personalized outreach strategies. **Now integrated with the Message Generator via MCP to also generate actual outreach messages.**

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│  Recherche  │────▶│  Espionnage │────▶│   Strategy  │────▶│ Message Gen     │
│  (Hunter)   │     │  (Tavily)   │     │  (Gemini)   │     │  (MCP Tool)     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────────┘
     │                    │                    │                    │
  contact_info       contexte_web        strategie_finale      message_genere
                                                                     │
                                                               ┌─────┴─────┐
                                                               │  body     │
                                                               │  subject  │
                                                               │  score    │
                                                               │  warnings │
                                                               └───────────┘
```

## Workflow Steps

### Step 1: Contact Discovery (Hunter)
- **File**: `graph_engine.py` → `noeud_recherche()`
- **Tool**: `tools/hunter_client.py`
- **Input**: Company domain (e.g., "gomycode.com")
- **Output**: Decision-maker details
  - Full name
  - Professional email
  - Job title
  - LinkedIn URL

### Step 2: Web Intelligence (Tavily)
- **File**: `graph_engine.py` → `noeud_espionnage()`
- **Tool**: `tools/tavily_client.py`
- **Input**: Contact name + company
- **Output**: Web context
  - LinkedIn profile analysis
  - Recent posts/activity
  - Public professional information
- **Fallback**: If no name found, searches for "CEO de {company}"

### Step 3: Strategy Synthesis (Gemini)
- **File**: `graph_engine.py` → `noeud_ia()`
- **Model**: Gemini (via Google API)
- **Input**: Contact info + web context
- **Output**: Structured strategy document

### Step 4: Message Generation (MCP Tool)
- **File**: `graph_engine.py` → `noeud_generation_message()`
- **Tool**: `tools/mcp_client.py` → calls Message Generator's `generate_outreach`
- **Input**: Contact info + sender config from env
- **Output**: Generated message with quality score
  - `body`: The outreach message text
  - `subject`: Subject line (if email channel)
  - `score`: Quality score (0-100)
  - `warnings`: Any issues with the message

#### Strategy Output Format:
```markdown
### 👤 PERSONNALITÉ
- **Nom identifié:** (Confirmed full name)
- **Style & Ton:** (Profile analysis: academic, decision-maker, technical, etc.)
- **Traits dominants:** (How to approach this person)

### 📊 ANALYSE D'ACTIVITÉ & TIMING
- **Score d'activité LinkedIn:** (Activity percentage)
- **Habitudes de publication:** (Online visibility patterns)
- **Fenêtre de tir idéale:** (Best time to contact)

### 🛡️ PLAN D'ACTION STRATÉGIQUE (DÉTAILLÉ)
- **Étape 1 (Premier Contact):** Channel selection + justification
- **Étape 2 (Contenu de l'approche):** Technical points/interests to mention
- **Étape 3 (Le Suivi/Follow-up):** Timeline, secondary channel, approach variation
- **Étape 4 (Alternative de secours):** Fallback after 3 failed attempts
```

## Entry Points

### 1. Streamlit Web UI
- **File**: `app.py`
- **Usage**: `streamlit run app.py`
- **Interface**: Enter domain → Click "Lancer l'Analyse" → View results

### 2. Temporal Worker (Background Processing)
- **File**: `worker.py`
- **Workflow**: `workflows/workflow.py`
- **Activity**: `workflows/activities.py`
- **Queue**: `strategy-task-queue`
- **Usage**: `python worker.py`

### 3. Direct Graph Invocation
```python
from graph_engine import app as agent_workflow

state = {
    "entreprise": "example.com",
    "contact_info": {},
    "contexte_web": {},
    "strategie_finale": ""
}

final_state = agent_workflow.invoke(state)
```

## Components

### LangGraph State (`AgentState`)
```python
{
    "entreprise": str,           # Input domain
    "contact_info": dict,        # From Hunter
    "contexte_web": dict,        # From Tavily
    "strategie_finale": str,     # From Gemini
    "message_genere": {          # From MCP (Message Generator)
        "success": bool,
        "message": str,          # Generated outreach message
        "subject": str or None,  # Subject line (if email)
        "score": int,            # Quality score 0-100
        "warnings": list,        # Any issues
        "error": str or None     # Error message if failed
    }
}
```

### External APIs
| Service | Purpose | File |
|---------|---------|------|
| Hunter API | Contact finder | `tools/hunter_client.py` |
| Tavily API | Web search | `tools/tavily_client.py` |
| Gemini API | LLM strategy generation | `graph_engine.py` |
| Message Generator MCP | Message generation | `tools/mcp_client.py` |

### Temporal Workflow (Async)
- **Workflow**: `StrategyWorkflow`
- **Activity**: `generate_strategy_activity`
- **Timeout**: 5 minutes
- **Purpose**: Background processing, retries, observability

## Configuration

### Environment Variables (`.env`)
```bash
HUNTER_API_KEY=your_hunter_key
TAVILY_API_KEY=your_tavily_key
```

### Gemini Setup
- Requires `GOOGLE_API_KEY` environment variable
- Default model: `gemini-3.1-flash-lite-preview`
- Fallback model: `models/gemma-3-27b-it`
- Temperature: 0.7 (balanced creativity/factuality)

## Dependencies

```
langgraph
mcp
requests
streamlit
temporalio
python-dotenv
```

## Pre-Integration Status

### What Works
- ✅ Contact discovery via Hunter
- ✅ Web intelligence via Tavily
- ✅ Strategy generation via Gemini
- ✅ Message generation via MCP (Message Generator)
- ✅ Streamlit UI for manual runs
- ✅ Temporal workflow for async processing

### What Needs Integration
- ✅ Connection to main outreach pipeline via MCP
- ⬜ Unified configuration management
- ⬜ Shared memory/prospect database
- ⬜ Logging & monitoring consolidation

## File Structure

```
sequence generator/
├── app.py                  # Streamlit UI entry point
├── graph_engine.py         # Main LangGraph workflow (4 steps)
├── worker.py               # Temporal worker
├── requirements.txt
├── agents/
│   ├── graph.py           # Alternative LangGraph
│   └── state.py           # State & output schemas
├── tools/
│   ├── hunter_client.py   # Hunter API integration
│   ├── tavily_client.py   # Tavily API integration
│   ├── mcp_client.py      # MCP client for Message Generator ⭐ NEW
│   └── scraper.py         # Web scraping utilities
└── workflows/
    ├── workflow.py        # Temporal workflow definition
    └── activities.py      # Temporal activity (calls LangGraph)
```

## Next Steps for Integration

1. **Align Data Models**: Convert `strategie_finale` (markdown text) to structured JSON matching the message generator's input requirements
2. **Shared State**: Connect to the main pipeline's `AgentState` and memory system
3. **API Contract**: Define REST/MCP endpoints for the main system to call the sequence generator
4. **Remove Redundancy**: Consolidate overlapping functionality with the message generator's Researcher agent
5. **Unified Config**: Merge `.env` configurations and settings management
