"""
Streamlit interface for manual outreach message generation.
"""
import streamlit as st
import httpx
import asyncio
from datetime import datetime

MSG_GEN_API = "http://localhost:8000"

# Example data from example_api_request.txt
EXAMPLE_DATA = {
    "target_prospect": "Sarah Chen",
    "target_company": "Ramp",
    "prospect_role": "VP of Sales",
    "channel": "linkedin_dm",
    "intent": "direct_outreach",
    "stage": "first_touch",
    "personality": {
        "base_template": "soft_sell",
        "personality_traits": ["curious", "direct"],
        "always_include_phrases": [],
        "never_use_phrases": ["synergies", "circle back"],
        "touchdowns_per_message": 2,
        "urgency_level": 2,
        "self_deprecation": 1,
        "humor_sarcasm": 3,
        "voice_samples": []
    },
    "company_details": {
        "company_name": "SalesForce AI",
        "elevator_pitch": "We help SDR teams double their reply rates using AI personalization.",
        "value_props": ["2x reply rates", "Saves 3 hours per SDR per day"],
        "social_proof": ["Used by 500+ sales teams"]
    },
    "selected_offer": {
        "offer_name": "SDR Efficiency Audit",
        "pain_points": ["Low reply rates on outbound", "SDRs spending too much time on manual research"],
        "solution_summary": "A diagnostic assessment of the SDR workflow to identify bottlenecks in targeting, data quality, and sequencing, resulting in a prioritized action plan for improving reply rates.",
        "proof_points": ["Teams saw 40% more meetings in 30 days"],
        "cta": "Ask if they are open to a brief, 15-minute chat to discuss this further."
    },
    "research_signals": [
        {
            "type": "linkedin_post",
            "content": "Just hit a major milestone at Ramp - our team doubled revenue this quarter through a new SDR pod approach.",
            "strength": "high",
            "source_url": "https://linkedin.com/posts/sarah-chen-12345",
            "timestamp": "2024-01-15T10:30:00Z",
            "why_relevant": "Recent professional activity showing current priorities and interests"
        },
        {
            "type": "company_news",
            "content": "Ramp announces new AI-powered product features to streamline customer workflows",
            "strength": "high",
            "source_url": "https://techcrunch.com/2024/01/14/ramp-news",
            "timestamp": "2024-01-14T08:00:00Z",
            "why_relevant": "Recent company developments showing growth trajectory and strategic focus"
        }
    ]
}

def init_session_state():
    """Initialize session state with defaults or empty values."""
    defaults = {
        'target_prospect': 'Sarah Chen',
        'target_company': 'Ramp',
        'prospect_role': 'VP of Sales',
        'target_email': '',
        'channel': 'linkedin_dm',
        'intent': 'direct_outreach',
        'stage': 'first_touch',
        'base_template': 'soft_sell',
        'personality_traits': ['curious', 'direct'],
        'never_use_phrases': 'synergies\ncircle back\nact now\nlimited time',
        'touchdowns_per_message': 2,
        'urgency_level': 2,
        'self_deprecation': 1,
        'humor_sarcasm': 3,
        'conversation_snippets': '',
        'company_name': 'SalesForce AI',
        'elevator_pitch': 'We help SDR teams double their reply rates using AI personalization.',
        'value_props': '2x reply rates\nSaves 3 hours per SDR per day',
        'social_proof': 'Used by 500+ sales teams',
        'offer_name': 'SDR Efficiency Audit',
        'pain_points': 'Low reply rates on outbound\nSDRs spending too much time on manual research',
        'proof_points': 'Teams saw 40% more meetings in 30 days',
        'solution_summary': 'A diagnostic assessment of the SDR workflow to identify bottlenecks in targeting, data quality, and sequencing, resulting in a prioritized action plan for improving reply rates.',
        'cta': 'Ask if they are open to a brief, 15-minute chat to discuss this further.',
        'research_signals': EXAMPLE_DATA['research_signals'].copy(),
        'generated_message': None,
        'task_id': None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def load_example_data():
    """Load all example data into session state."""
    st.session_state.target_prospect = EXAMPLE_DATA['target_prospect']
    st.session_state.target_company = EXAMPLE_DATA['target_company']
    st.session_state.prospect_role = EXAMPLE_DATA['prospect_role']
    st.session_state.channel = EXAMPLE_DATA['channel']
    st.session_state.intent = EXAMPLE_DATA['intent']
    st.session_state.stage = EXAMPLE_DATA['stage']
    st.session_state.base_template = EXAMPLE_DATA['personality']['base_template']
    st.session_state.personality_traits = EXAMPLE_DATA['personality']['personality_traits']
    st.session_state.never_use_phrases = '\n'.join(EXAMPLE_DATA['personality']['never_use_phrases'])
    st.session_state.touchdowns_per_message = EXAMPLE_DATA['personality']['touchdowns_per_message']
    st.session_state.urgency_level = EXAMPLE_DATA['personality']['urgency_level']
    st.session_state.self_deprecation = EXAMPLE_DATA['personality']['self_deprecation']
    st.session_state.humor_sarcasm = EXAMPLE_DATA['personality']['humor_sarcasm']
    st.session_state.company_name = EXAMPLE_DATA['company_details']['company_name']
    st.session_state.elevator_pitch = EXAMPLE_DATA['company_details']['elevator_pitch']
    st.session_state.value_props = '\n'.join(EXAMPLE_DATA['company_details']['value_props'])
    st.session_state.social_proof = '\n'.join(EXAMPLE_DATA['company_details']['social_proof'])
    st.session_state.offer_name = EXAMPLE_DATA['selected_offer']['offer_name']
    st.session_state.pain_points = '\n'.join(EXAMPLE_DATA['selected_offer']['pain_points'])
    st.session_state.proof_points = '\n'.join(EXAMPLE_DATA['selected_offer']['proof_points'])
    st.session_state.solution_summary = EXAMPLE_DATA['selected_offer']['solution_summary']
    st.session_state.cta = EXAMPLE_DATA['selected_offer']['cta']
    st.session_state.research_signals = [s.copy() for s in EXAMPLE_DATA['research_signals']]
    st.success("✅ Example data loaded!")
    st.rerun()

def add_research_signal():
    """Add a new empty research signal."""
    new_signal = {
        "type": "linkedin_post",
        "content": "",
        "strength": "medium",
        "source_url": "",
        "timestamp": datetime.now().isoformat() + "Z",
        "why_relevant": ""
    }
    st.session_state.research_signals.append(new_signal)
    st.rerun()

def remove_research_signal(index):
    """Remove research signal at given index."""
    if 0 <= index < len(st.session_state.research_signals):
        st.session_state.research_signals.pop(index)
        st.rerun()

# Initialize session state
init_session_state()

st.set_page_config(page_title="Outreach Message Generator", layout="wide")

st.title("🚀 AI Outreach Message Generator")
st.markdown("Generate personalized outreach messages via AI pipeline")

# Load example button at top
col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 3])
with col_btn1:
    if st.button("📋 Load Example Data", type="secondary", use_container_width=True):
        load_example_data()
with col_btn2:
    if st.button("🗑️ Clear All", type="secondary", use_container_width=True):
        for key in list(st.session_state.keys()):
            if key not in ['generated_message', 'task_id']:
                del st.session_state[key]
        init_session_state()
        st.rerun()

# Research signals count indicator
signal_count = len(st.session_state.research_signals)
if signal_count == 0:
    st.error("⚠️ No research signals! Click '📋 Load Example Data' or add signals in the 🔍 Research tab.")
else:
    st.success(f"✅ {signal_count} research signal(s) ready")

st.divider()

# Create tabs for different sections
tab_basic, tab_personality, tab_company, tab_offer, tab_research, tab_result = st.tabs([
    "👤 Prospect Info", "🎭 Personality", "🏢 Company Details", "🎁 Offer", "🔍 Research Signals", "📧 Result"
])

with tab_basic:
    st.header("Target Prospect")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Name", value=st.session_state.target_prospect, key="target_prospect")
        st.text_input("Company", value=st.session_state.target_company, key="target_company")
    with col2:
        st.text_input("Role/Title", value=st.session_state.prospect_role, key="prospect_role")
        st.text_input("Email (for sending)", value=st.session_state.target_email, key="target_email")
    
    st.header("Message Settings")
    col3, col4, col5 = st.columns(3)
    with col3:
        channel_options = ["linkedin_dm", "email", "linkedin_inmail"]
        st.selectbox("Channel", channel_options, index=channel_options.index(st.session_state.channel), key="channel")
    with col4:
        intent_options = ["direct_outreach", "follow_up", "referral", "re_engagement", "event_based"]
        st.selectbox("Intent", intent_options, index=intent_options.index(st.session_state.intent), key="intent")
    with col5:
        stage_options = ["first_touch", "second_touch", "third_touch"]
        st.selectbox("Stage", stage_options, index=stage_options.index(st.session_state.stage), key="stage")

with tab_personality:
    st.header("Personality Configuration")
    
    template_options = ["soft_sell", "value_based", "spin_selling", "direct", "consultative", "custom"]
    st.selectbox("Base Template", template_options, index=template_options.index(st.session_state.base_template), key="base_template")
    
    col1, col2 = st.columns(2)
    with col1:
        st.multiselect(
            "Personality Traits",
            ["curious", "direct", "friendly", "professional", "humorous", "respectful", "concise", "empathetic"],
            default=st.session_state.personality_traits,
            key="personality_traits"
        )
        st.slider("Urgency Level", 1, 5, value=st.session_state.urgency_level, key="urgency_level")
        st.slider("Self-Deprecation", 0, 5, value=st.session_state.self_deprecation, key="self_deprecation")
    with col2:
        st.text_area(
            "Never Use Phrases (one per line)",
            value=st.session_state.never_use_phrases,
            key="never_use_phrases"
        )
        st.slider("Humor/Sarcasm", 0, 5, value=st.session_state.humor_sarcasm, key="humor_sarcasm")
        st.slider("Touchdowns per Message", 1, 5, value=st.session_state.touchdowns_per_message, key="touchdowns_per_message")
    
    st.subheader("💬 Voice Matching (Optional)")
    st.markdown("Paste 1-5 examples of your previous messages to mimic your writing style")
    st.text_area(
        "Your Previous Messages (separate with --- on its own line)",
        value=st.session_state.conversation_snippets,
        placeholder="Hey Sarah, loved your post on AI sales automation...\n---\nHi John, noticed you're hiring SDRs...",
        height=150,
        key="conversation_snippets"
    )

with tab_company:
    st.header("Your Company (Sender)")
    
    st.text_input("Company Name", value=st.session_state.company_name, key="company_name")
    st.text_area("Elevator Pitch", value=st.session_state.elevator_pitch, key="elevator_pitch")
    
    st.subheader("Value Propositions")
    st.text_area("Value Props (one per line)", value=st.session_state.value_props, key="value_props")
    
    st.subheader("Social Proof")
    st.text_area("Social Proof (one per line)", value=st.session_state.social_proof, key="social_proof")

with tab_offer:
    st.header("What You're Offering")
    
    st.text_input("Offer Name", value=st.session_state.offer_name, key="offer_name")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Pain Points You Solve")
        st.text_area("Pain Points (one per line)", value=st.session_state.pain_points, key="pain_points")
    with col2:
        st.subheader("Proof Points")
        st.text_area("Proof Points (one per line)", value=st.session_state.proof_points, key="proof_points")
    
    st.text_area("Solution Summary", value=st.session_state.solution_summary, key="solution_summary")
    st.text_input("Call to Action (CTA)", value=st.session_state.cta, key="cta")

with tab_research:
    st.header("🔍 Research Signals (Required)")
    st.markdown("**⚠️ These are required!** The message generator needs research signals from external modules (e.g., Detective).")
    
    # Show count and add button
    col_count, col_add = st.columns([3, 1])
    with col_count:
        st.info(f"Current signals: {len(st.session_state.research_signals)}")
    with col_add:
        if st.button("➕ Add Signal", use_container_width=True):
            add_research_signal()
    
    st.divider()
    
    # Display each signal with edit fields
    for idx, signal in enumerate(st.session_state.research_signals):
        with st.container():
            col_title, col_delete = st.columns([4, 1])
            with col_title:
                st.subheader(f"Signal #{idx + 1}: {signal.get('type', 'Unknown')}")
            with col_delete:
                if st.button("🗑️ Delete", key=f"del_signal_{idx}"):
                    remove_research_signal(idx)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                signal['type'] = st.selectbox(
                    "Type",
                    ["linkedin_post", "company_news", "job_change", "shared_connection", "event_attendance", "content_engagement", "funding_news", "product_launch"],
                    index=["linkedin_post", "company_news", "job_change", "shared_connection", "event_attendance", "content_engagement", "funding_news", "product_launch"].index(signal.get('type', 'linkedin_post')),
                    key=f"sig_type_{idx}"
                )
                signal['strength'] = st.selectbox(
                    "Strength",
                    ["high", "medium", "low"],
                    index=["high", "medium", "low"].index(signal.get('strength', 'medium')),
                    key=f"sig_strength_{idx}"
                )
            with col2:
                signal['source_url'] = st.text_input(
                    "Source URL",
                    value=signal.get('source_url', ''),
                    key=f"sig_url_{idx}"
                )
                signal['timestamp'] = st.text_input(
                    "Timestamp (ISO)",
                    value=signal.get('timestamp', datetime.now().isoformat() + "Z"),
                    key=f"sig_time_{idx}"
                )
            with col3:
                signal['content'] = st.text_area(
                    "Content (Hook Text)",
                    value=signal.get('content', ''),
                    height=100,
                    key=f"sig_content_{idx}"
                )
                signal['why_relevant'] = st.text_area(
                    "Why Relevant?",
                    value=signal.get('why_relevant', ''),
                    height=50,
                    key=f"sig_relevant_{idx}"
                )
        st.divider()

async def generate_message():
    """Call message generator API."""
    
    # Build payload from session state
    snippets = st.session_state.conversation_snippets
    voice_samples = [s.strip() for s in snippets.split('---') if s.strip()] if snippets else []
    
    payload = {
        "target_prospect": st.session_state.target_prospect,
        "target_company": st.session_state.target_company,
        "prospect_role": st.session_state.prospect_role,
        "channel": st.session_state.channel,
        "intent": st.session_state.intent,
        "stage": st.session_state.stage,
        "personality": {
            "base_template": st.session_state.base_template,
            "personality_traits": st.session_state.personality_traits,
            "always_include_phrases": [],
            "never_use_phrases": [p.strip() for p in st.session_state.never_use_phrases.split('\n') if p.strip()],
            "touchdowns_per_message": st.session_state.touchdowns_per_message,
            "urgency_level": st.session_state.urgency_level,
            "self_deprecation": st.session_state.self_deprecation,
            "humor_sarcasm": st.session_state.humor_sarcasm,
            "voice_samples": voice_samples
        },
        "company_details": {
            "company_name": st.session_state.company_name,
            "elevator_pitch": st.session_state.elevator_pitch,
            "value_props": [p.strip() for p in st.session_state.value_props.split('\n') if p.strip()],
            "social_proof": [p.strip() for p in st.session_state.social_proof.split('\n') if p.strip()]
        },
        "selected_offer": {
            "offer_name": st.session_state.offer_name,
            "pain_points": [p.strip() for p in st.session_state.pain_points.split('\n') if p.strip()],
            "solution_summary": st.session_state.solution_summary,
            "proof_points": [p.strip() for p in st.session_state.proof_points.split('\n') if p.strip()],
            "cta": st.session_state.cta
        },
        "research_signals": st.session_state.research_signals
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(f"{MSG_GEN_API}/api/generate/simple", json=payload)
        return response.json()

async def approve_and_send(task_id, email):
    """Approve via review endpoint and send."""
    approval = {
        "approved": True,
        "prospect_email": email
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{MSG_GEN_API}/api/review/{task_id}/decision",
            json=approval
        )
        return response.json()

async def send_direct(email, subject, body):
    """Send email directly via API."""
    params = {
        "to_address": email,
        "subject": subject,
        "body": body
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{MSG_GEN_API}/api/send/email", params=params)
        return response.json()

# Generate button
st.divider()
gen_disabled = len(st.session_state.research_signals) == 0

if gen_disabled:
    st.warning("⚠️ Cannot generate: Add research signals in the 🔍 Research Signals tab or click '📋 Load Example Data' above.")

if st.button("🚀 Generate Message", type="primary", use_container_width=True, disabled=gen_disabled):
    with st.spinner("AI is generating your message..."):
        try:
            result = asyncio.run(generate_message())
            st.session_state.generated_message = result
            st.session_state.task_id = result.get('task_id')
            if result.get('success'):
                st.success("Message generated!")
            else:
                st.error(f"Generation failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            st.error(f"Error: {str(e)}")

# Result tab
with tab_result:
    if st.session_state.generated_message:
        result = st.session_state.generated_message
        
        st.header("📊 Generation Result")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Quality Score", f"{result.get('score', 'N/A')}/100")
        with col2:
            status = "✅ Approved" if result.get('success') and not result.get('awaiting_human') else "⏳ Review Required"
            st.metric("Status", status)
        with col3:
            if result.get('awaiting_human'):
                st.metric("Task ID", result.get('task_id', 'N/A')[:8] + "...")
        
        st.subheader("Subject")
        st.code(result.get('subject', 'N/A'), language=None)
        
        st.subheader("Message Body")
        st.text_area("", value=result.get('message', ''), height=400, disabled=True)
        
        # Send options
        st.divider()
        st.header("📧 Send Options")
        
        send_email = st.text_input("Send to Email", value=st.session_state.target_email, key="send_email")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if result.get('awaiting_human') and st.session_state.task_id:
                if st.button("✅ Approve & Send via Review Flow", use_container_width=True):
                    if not send_email:
                        st.error("Please enter an email address")
                    else:
                        with st.spinner("Approving and sending..."):
                            try:
                                send_result = asyncio.run(approve_and_send(st.session_state.task_id, send_email))
                                if send_result.get('success'):
                                    st.success(f"✅ Email sent to {send_email}!")
                                else:
                                    st.error(f"Failed: {send_result}")
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
            elif result.get('success'):
                st.info("Message was auto-approved. Use direct send below.")
        
        with col2:
            if st.button("📨 Direct Send (Bypass Review)", use_container_width=True):
                if not send_email:
                    st.error("Please enter an email address")
                else:
                    with st.spinner("Sending..."):
                        try:
                            send_result = asyncio.run(send_direct(
                                send_email, 
                                result.get('subject', ''), 
                                result.get('message', '')
                            ))
                            if send_result.get('success'):
                                st.success(f"✅ Email sent to {send_email}!")
                            else:
                                st.error(f"Failed: {send_result}")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
    else:
        st.info("Click 'Generate Message' to see results here")

# Debug: Show JSON payload
with st.expander("📋 View API Payload (Debug)"):
    if st.session_state.generated_message:
        st.json(st.session_state.generated_message)
