# Outreach Message Generator - Streamlit Interface

A web-based UI for generating AI-powered outreach messages with full control over personality, company details, and offer configuration.

## Overview

This Streamlit interface allows you to:
- Manually input prospect information (name, company, role, email)
- Configure message personality (tone, traits, phrases to avoid)
- Set your company details and value propositions
- Define your offer with pain points and proof points
- Generate AI-personalized messages via the Message Generator API
- Review quality scores and send emails directly

## Prerequisites

1. **Message Generator Server must be running** on port 8000
   ```bash
   cd "message generator and sender"
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. **Required environment variables** in `message generator and sender/.env`:
   ```bash
   GOOGLE_API_KEY=your_gemini_api_key
   GMAIL_ADDRESS=your_email@gmail.com
   GMAIL_APP_PASSWORD=your_app_password
   MIN_QUALITY_SCORE=80
   ```

3. **Python dependencies installed**:
   ```bash
   pip install streamlit httpx
   ```

## How to Run

### Option 1: Run from terminal
```bash
cd "message generator and writer"
streamlit run streamlit_generator.py
```

### Option 2: Run with specific port
```bash
cd "message generator and writer"
streamlit run streamlit_generator.py --server.port 8501
```

### Option 3: Run in background (Windows PowerShell)
```powershell
cd "message generator and writer"
Start-Process -FilePath "streamlit" -ArgumentList "run", "streamlit_generator.py" -WindowStyle Hidden
```

## Accessing the Interface

After running the command, the interface will be available at:
- **Local**: http://localhost:8501
- **Network**: http://YOUR_IP:8501 (accessible from other devices on same network)

## How to Use

### 1. Fill in the Tabs

Navigate through each tab and fill in the details:

#### 👤 Prospect Info
- **Name**: Target person's full name (e.g., "Sarah Chen")
- **Company**: Target company name (e.g., "Ramp")
- **Role/Title**: Their job title (e.g., "VP of Sales")
- **Email**: Their email address for sending
- **Channel**: Communication channel (linkedin_dm, email, etc.)
- **Intent**: Type of outreach (direct_outreach, follow_up, etc.)
- **Stage**: Touch stage (first_touch, second_touch, etc.)

#### 🎭 Personality
- **Base Template**: soft_sell, hard_sell, educational, casual
- **Personality Traits**: Select multiple (curious, direct, friendly, etc.)
- **Never Use Phrases**: Words/phrases the AI should avoid (one per line)
- **Urgency Level**: 1-5 scale
- **Humor/Sarcasm**: 0-5 scale
- **Touchdowns per Message**: 1-5 (personalization points)

#### 🏢 Company Details (Your Company)
- **Company Name**: Your company name
- **Elevator Pitch**: One-sentence description
- **Value Props**: Key benefits (one per line)
- **Social Proof**: Credibility indicators (one per line)

#### 🎁 Offer
- **Offer Name**: What you're offering
- **Pain Points**: Problems you solve (one per line)
- **Solution Summary**: Detailed description
- **Proof Points**: Evidence/results (one per line)
- **Call to Action (CTA)**: What you want them to do
- **Custom Hook**: Recent activity/context for personalization

### 2. Generate Message

Click the **"🚀 Generate Message"** button. The AI will:
- Generate a personalized message based on your inputs
- Score it for quality (0-100)
- Check against guardrails

### 3. Review Result

In the **📧 Result** tab, you'll see:
- Quality Score (needs ≥80 for auto-approval)
- Status (Approved or Review Required)
- Generated Subject line
- Generated Message body

### 4. Send Email

**Option A - f human review is disabled (ENABLE_HUMAN_REVIEW=false):**
- Enter the recipient's email
- Click **"📨 Direct Send (Bypass Review)"**

**Option B - If human review is enabled (ENABLE_HUMAN_REVIEW=true):**
- Review the message
- Enter the recipient's email
- Click **"✅ Approve & Send via Review Flow"**
**Note:** The quality score (≥80) is set by MIN_QUALITY_SCORE and determines if the message passes AI quality checks, not whether human review is required.
## Example Workflow

1. **Start Message Generator server** (in separate terminal):
   ```bash
   cd "message generator and sender"
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Run Streamlit interface** (in another terminal):
   ```bash
   cd "message generator and sender"
   streamlit run streamlit_generator.py
   ```

3. **Open browser** at http://localhost:8501

4. **Fill in Sarah Chen example**:
   - Name: Sarah Chen
   - Company: Ramp
   - Role: VP of Sales
   - Channel: linkedin_dm
   - Company: SalesForce AI
   - Offer: SDR Efficiency Audit

5. **Click Generate** → Review → Send

## Troubleshooting

### "Connection refused" error
- Make sure Message Generator server is running on port 8000
- Check with: `curl http://localhost:8000/`

### "Failed to generate" error
- Check Message Generator logs for errors
- Verify GOOGLE_API_KEY is set correctly
- Check MIN_QUALITY_SCORE setting

### Email not sending
- Verify GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env
- Ensure Gmail account has "Less secure app access" enabled or uses App Password

### Port already in use
- Kill existing process: `taskkill /F /IM streamlit.exe`
- Or use different port: `streamlit run streamlit_generator.py --server.port 8502`

## File Structure

```
sequence generator/
├── streamlit_generator.py    # This interface
├── README_STREAMLIT.md       # This file
├── tools/
│   └── mcp_client.py         # API client for Message Generator
└── ...

message generator and sender/
├── app/
│   ├── main.py               # FastAPI server
│   └── send_tools.py         # Email sending logic
└── .env                      # Environment variables
```

## API Flow

```
Streamlit UI
    ↓
streamlit_generator.py
    ↓
POST /api/generate/simple (Message Generator)
    ↓
AI Generation + Quality Check
    ↓
Result (score, message)
    ↓
POST /api/review/{id}/decision (if review needed)
    OR
POST /api/send/email (direct send)
    ↓
Email Sent via Gmail
```

## Customization

To change default values, edit `streamlit_generator.py`:
- Look for `value=` parameters in `st.text_input()`, `st.text_area()`, etc.
- Modify the default strings to match your typical use case

## Support

For issues with:
- **Message generation**: Check Message Generator logs
- **UI issues**: Check browser console and Streamlit logs
- **Email sending**: Verify Gmail credentials and settings
