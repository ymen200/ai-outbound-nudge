# 🎯 Streamlit Message Generator - Standalone Interface

A simple, standalone web interface for generating and sending personalized outreach messages in one shot.

## Overview

This is the **single-shot** message generator - no sequences, no workflows, just:
1. Fill in prospect details
2. Generate message via AI
3. Send immediately (or approve then send)

Perfect for: Quick one-off messages when you already know who you want to reach.

## Features

| Feature | Description |
|---------|-------------|
| 👤 Prospect Info | Name, company, role, email |
| 🎭 Personality | Traits, tone, templates, urgency |
| 🏢 Company Details | Your company name, elevator pitch |
| 🎁 Offer | Pain points, solution, CTA, proof points |
| 📧 Send Options | Direct send or review-then-send |

## How to Run

### Prerequisites

- Message Generator API running on port 8000
- Virtual environment activated

### Start

```bash
cd "message generator and sender"
.\venv\Scripts\activate
streamlit run streamlit_generator.py
```

Access: http://localhost:8501

## Usage

### 1. Fill the Tabs

#### 👤 Prospect Info
- **Name**: Target person's full name
- **Company**: Target company
- **Role/Title**: Their job position
- **Email**: Where to send the message
- **Channel**: linkedin_dm, email, etc.
- **Intent**: direct_outreach, follow_up, etc.
- **Stage**: first_touch, second_touch, etc.

#### 🎭 Personality
- **Base Template**: soft_sell, hard_sell, educational, casual
- **Traits**: curious, direct, friendly, etc.
- **Never Use Phrases**: Words to avoid
- **Urgency/Humor**: Sliders (1-5)

#### 🏢 Company Details
- **Your Company Name**
- **Elevator Pitch**: One-liner about your company
- **Value Props**: Key benefits
- **Social Proof**: Credibility indicators

#### 🎁 Offer
- **Offer Name**: What you're offering
- **Pain Points**: Problems you solve
- **Solution Summary**: Detailed description
- **CTA**: Call to action (e.g., "Book a 15-min call")
- **Proof Points**: Evidence/results

### 2. Generate

Click **"🚀 Generate Message"**

- AI generates personalized message
- Quality score (0-100)
- Warnings if any

### 3. Send

#### Option A: Direct Send (if score ≥ 80)
- Enter email
- Click **"📨 Direct Send (Bypass Review)"**
- Email sent immediately

#### Option B: Approve & Send (if score < 80)
- Review the message
- Click **"✅ Approve & Send via Review Flow"**
- Email sent after human approval

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `POST /api/generate/simple` | Generate message |
| `POST /api/send/email` | Send email directly |
| `POST /api/review/{id}/decision` | Approve and send |

## Data Flow

```
Streamlit UI
    ↓
streamlit_generator.py
    ↓
POST /api/generate/simple
    ↓
Message Generator (port 8000)
    ↓
AI Generation + Quality Check
    ↓
Result (message + score)
    ↓
POST /api/send/email (or /review)
    ↓
Email Sent via Gmail
```

## Differences from Sequence Workflow

| Aspect | This Interface | Sequence Workflow (app.py) |
|--------|----------------|---------------------------|
| **Steps** | 1 message | 2-4 step sequence |
| **Persistence** | In-memory only | Temporal workflow (survives crashes) |
| **Timing** | Immediate | J+0, J+3, J+7 scheduling |
| **Human Review** | Optional | Required per-step |
| **Use Case** | Quick one-off | Campaign/nurture sequence |

## Troubleshooting

### "Connection refused"
Message Generator not running. Start it:
```bash
cd "message generator and sender"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### "Failed to generate"
- Check GOOGLE_API_KEY in message generator .env
- Check Message Generator logs

### "Email not sending"
- Verify GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env
- Check Gmail security settings (App Passwords)

## Related Files

| File | Purpose |
|------|---------|
| `streamlit_generator.py` | This interface |
| `app.py` | Main interface (simple + sequence tabs) |
| `app_sequences.py` | Sequence management UI |
| `temporal_client.py` | Temporal workflow client |

## Quick Start Summary

```bash
# Terminal 1: Message Generator API
cd "message generator and sender"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: This interface
cd "sequence generator"
streamlit run streamlit_generator.py

# Open browser: http://localhost:8501
```
