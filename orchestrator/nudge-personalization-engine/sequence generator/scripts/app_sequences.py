"""
Streamlit UI for Sequence Management with Temporal backend.
This module provides the sequence workflow interface.
Can be imported into main app.py or run standalone.
"""

import streamlit as st
import json
import asyncio
import os
import re
import time
from datetime import datetime
from temporal_client import (
    start_sequence_sync,
    get_sequence_status_sync,
    send_step_sync,
    skip_step_sync,
    regenerate_step_sync,
    stop_sequence_sync,
    approve_sequence_sync,
    approve_step_sync,
)


def render_sequence_ui():
    """Render the complete sequence management UI."""
    
    st.header(" Outreach Sequence Manager")
    st.markdown("Create and manage multi-step outreach sequences with human approval")
    
    # Create tabs for different sections
    tab_create, tab_manage = st.tabs(["➕ New Sequence", "📊 Active Sequences"])
    
    with tab_create:
        render_create_sequence()
    
    with tab_manage:
        render_manage_sequences()


def load_template_data():
    """Load data from manual_input_template.txt file."""
    template_path = os.path.join(os.path.dirname(__file__), "manual_input_template.txt")
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the template
        data = {}
        
        # Extract company info
        company_match = re.search(r'Nom de l\'entreprise:\s*(.+)', content)
        data['company_name'] = company_match.group(1).strip() if company_match else ''
        
        website_match = re.search(r'Site web:\s*(.+)', content)
        data['company_website'] = website_match.group(1).strip() if website_match else ''
        
        industry_match = re.search(r'Secteur:\s*(.+)', content)
        data['company_industry'] = industry_match.group(1).strip() if industry_match else ''
        
        # Extract prospect info
        name_match = re.search(r'Nom complet:\s*(.+)', content)
        data['persona_name'] = name_match.group(1).strip() if name_match else ''
        
        role_match = re.search(r'Poste:\s*(.+)', content)
        data['persona_role'] = role_match.group(1).strip() if role_match else ''
        
        email_match = re.search(r'Email:\s*(.+)', content)
        data['persona_email'] = email_match.group(1).strip() if email_match else ''
        
        linkedin_match = re.search(r'LinkedIn URL:\s*(.+)', content)
        data['persona_linkedin'] = linkedin_match.group(1).strip() if linkedin_match else ''
        
        location_match = re.search(r'Localisation:\s*(.+)', content)
        data['persona_location'] = location_match.group(1).strip() if location_match else ''
        
        # Extract context (everything after "Contexte détaillé:")
        context_match = re.search(r'Contexte détaillé:\s*\n?([^#]+)', content, re.DOTALL)
        if context_match:
            context = context_match.group(1).strip()
            # Remove the example section if present
            if '---' in context:
                context = context.split('---')[0].strip()
            data['manual_context'] = context
        else:
            data['manual_context'] = ''
        
        # Extract ICP
        icp_match = re.search(r'Description ICP:\s*\n?([^#]+)', content, re.DOTALL)
        if icp_match:
            icp = icp_match.group(1).strip()
            if '---' in icp:
                icp = icp.split('---')[0].strip()
            data['icp_description'] = icp
        else:
            data['icp_description'] = ''
        
        # Extract offer
        offer_match = re.search(r'Offre:\s*(.+)', content)
        data['offer_context'] = offer_match.group(1).strip() if offer_match else ''
        
        return data
    except Exception as e:
        st.error(f"Error loading template: {str(e)}")
        return None


def render_create_sequence():
    """Render the create new sequence section."""
    st.subheader("Create New Sequence")
    
    # Input method selection - both skip Hunter/Tavily, go straight to Gemini
    input_method = st.radio(
        "Data Source:",
        [
            "📁 Detective Module (pre-enriched)", 
            "✍️ Manual Input (my context)"
        ],
        horizontal=True,
        help="Both modes go directly to Gemini without Hunter/Tavily"
    )
    
    # Check which mode is selected
    use_detective = "Detective" in input_method
    use_manual = "Manual" in input_method or "manual" in input_method
    
    detective_data = None
    
    if use_detective:
        uploaded_file = st.file_uploader(
            "Upload Detective JSON file",
            type=["json"],
            help="File containing company + persona + ICP"
        )
        
        if uploaded_file:
            try:
                detective_data = json.load(uploaded_file)
                st.success("✅ File loaded successfully!")
                
                # Preview data
                with st.expander("📋 Data Preview"):
                    st.json(detective_data)
                    
            except Exception as e:
                st.error(f"❌ JSON read error: {str(e)}")
    
    elif use_manual:  # Manual input - direct to Gemini
        st.markdown("### 📝 Manual Input")
        st.info("💡 Your context will be analyzed directly by Gemini to create the strategy.")
        
        # Add autofill button
        col_auto, col_space = st.columns([1, 3])
        with col_auto:
            if st.button("📋 Autofill from Template", type="secondary"):
                template_data = load_template_data()
                if template_data:
                    st.session_state['template_data'] = template_data
                    st.success("✅ Template loaded! Fill the form below.")
                    st.rerun()
        
        # Get template data if available
        template_data = st.session_state.get('template_data', {})
        
        # Company info
        st.markdown("#### 🏢 Company")
        col1, col2 = st.columns(2)
        with col1:
            company_name = st.text_input("Company Name *", 
                value=template_data.get('company_name', ''), 
                placeholder="Ex: TechCorp Solutions")
            company_key = st.text_input("Company Key (optional)", 
                value=template_data.get('company_name', '').lower().replace(' ', '_') if template_data.get('company_name') else '',
                placeholder="techcorp")
        with col2:
            company_website = st.text_input("Website", 
                value=template_data.get('company_website', ''),
                placeholder="techcorp.com")
            company_industry = st.text_input("Industry", 
                value=template_data.get('company_industry', ''),
                placeholder="SaaS, Fintech...")
        
        # Prospect info
        st.markdown("#### 👤 Prospect")
        col1, col2 = st.columns(2)
        with col1:
            persona_name = st.text_input("Full Name *", 
                value=template_data.get('persona_name', ''),
                placeholder="Ex: Mohamed Benmansour")
            persona_role = st.text_input("Job Title *", 
                value=template_data.get('persona_role', ''),
                placeholder="Ex: CTO")
            persona_email = st.text_input("Email", 
                value=template_data.get('persona_email', ''),
                placeholder="mohamed@techcorp.com")
        with col2:
            persona_linkedin = st.text_input("LinkedIn URL", 
                value=template_data.get('persona_linkedin', ''),
                placeholder="linkedin.com/in/mohamed-benmansour")
            persona_location = st.text_input("Location", 
                value=template_data.get('persona_location', ''),
                placeholder="Tunis, Tunisia")
        
        # Context for Gemini
        st.markdown("#### 🧠 Context for AI")
        manual_context = st.text_area(
            "Describe what you know about this prospect *",
            value=template_data.get('manual_context', ''),
            placeholder="""Example:
- CTO at TechCorp Solutions for 3 years
- Company in strong growth (50 to 150 employees in 2 years)
- Often posts on LinkedIn about tech scaling challenges
- Recently participated in DevOpsDays Tunisia 2024
- Likely problems: technical debt management, onboarding new devs
            """,
            height=200,
            help="The more details you provide, the better Gemini's strategy will be"
        )
        
        # ICP & Offer context
        st.markdown("#### 🎯 Offer Context")
        icp_description = st.text_area(
            "Your ICP / Target Context",
            value=template_data.get('icp_description', ''),
            placeholder="We target CTOs and VP Engineering of growing SaaS startups (50-200 employees)...",
            height=80
        )
        
        offer_context = st.text_input(
            "What you're offering",
            value=template_data.get('offer_context', ''),
            placeholder="Free tech productivity audit + personalized action plan"
        )
        
        if company_name and persona_name and manual_context:
            detective_data = {
                "company_key": company_key or company_name.lower().replace(" ", "_"),
                "company_name": company_name,
                "company_website": company_website,
                "company_industry": company_industry,
                "selected_persona": {
                    "full_name": persona_name,
                    "job_title": persona_role,
                    "email": persona_email,
                    "city": persona_location,
                    "country": "",
                    "linkedin_url": persona_linkedin
                },
                "icp_description": icp_description,
                "offer_context": offer_context,
                "manual_context": manual_context  # Workflow detects this and skips research
            }
    
    # Start sequence button
    if detective_data:
        st.divider()
        
        # Approval mode selector
        st.markdown("#### Human-in-the-Loop Approval")
        approval_option = st.radio(
            "Approval Mode:",
            [
                "Once for whole sequence",
                "Per step",
                "Per step + per message"
            ],
            horizontal=True,
            help="Choose how you want to approve steps before they are sent",
            index=0
        )
        
        approval_mode_map = {
            "Once for whole sequence": "per_sequence",
            "Per step": "per_step",
            "Per step + per message": "per_step_and_message"
        }
        detective_data["approval_mode"] = approval_mode_map.get(approval_option, "per_sequence")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            workflow_id = st.text_input(
                "Sequence ID (optional)",
                value=f"seq-{detective_data.get('company_key', 'unknown')}-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                help="Unique identifier for this sequence"
            )
        
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 Launch Sequence", type="primary", use_container_width=True):
                with st.spinner("Starting Temporal workflow..."):
                    try:
                        result_id = start_sequence_sync(detective_data, workflow_id)
                        st.success(f"✅ Sequence started!\n\n**ID:** `{result_id}`")
                        
                        # Store in session state
                        if 'active_sequences' not in st.session_state:
                            st.session_state.active_sequences = []
                        
                        st.session_state.active_sequences.append({
                            'id': result_id,
                            'company': detective_data.get('company_name', ''),
                            'persona': detective_data.get('selected_persona', {}).get('full_name', ''),
                            'created_at': datetime.now().isoformat()
                        })
                        
                        # Add to recent sequences for quick access
                        if 'recent_sequences' not in st.session_state:
                            st.session_state.recent_sequences = []
                        
                        # Add to front of list, avoid duplicates
                        if result_id in st.session_state.recent_sequences:
                            st.session_state.recent_sequences.remove(result_id)
                        st.session_state.recent_sequences.insert(0, result_id)
                        # Keep only last 10
                        st.session_state.recent_sequences = st.session_state.recent_sequences[:10]
                        
                        st.info("⏳ Sequence is being generated. Go to 'Active Sequences' tab to monitor progress.")
                        
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
                        st.info("💡 Make sure:")
                        st.markdown("- Temporal server is running (localhost:7233)")
                        st.markdown("- Worker is running")
                        st.markdown("- Message generator is accessible (port 8000)")


def render_manage_sequences():
    """Render the manage active sequences section with auto-refresh and better UX."""
    st.subheader("🎯 Active Sequences")
    
    # Initialize session state for recent sequences if not exists
    if 'recent_sequences' not in st.session_state:
        st.session_state.recent_sequences = []
    if 'current_workflow_id' not in st.session_state:
        st.session_state.current_workflow_id = ""
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = True
    
    # Recent sequences section
    if st.session_state.recent_sequences:
        with st.expander("📜 Recent Sequences (Click to Load)", expanded=True):
            for i, seq_id in enumerate(st.session_state.recent_sequences[:6]):
                col1, col2 = st.columns([4, 1])
                with col1:
                    # Truncate long IDs for display
                    display_id = seq_id[:50] + "..." if len(seq_id) > 50 else seq_id
                    if st.button(f"📋 {display_id}", key=f"recent_{i}", use_container_width=True):
                        st.session_state.current_workflow_id = seq_id
                        st.rerun()
                with col2:
                    # Copy button
                    st.code(seq_id, language=None)
    
    # Controls row
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        # Get current value from session state
        current_id = st.session_state.get('current_workflow_id', '')
        
        # Text input - only update session state if user actually typed something
        workflow_input = st.text_input(
            "🔍 Sequence ID",
            value=current_id,
            placeholder="Paste workflow ID and press Enter...",
            key="workflow_id_input"
        )
        
        # Only update if input changed and is not empty
        if workflow_input and workflow_input != current_id:
            st.session_state.current_workflow_id = workflow_input
            st.rerun()
        
        # Use the definitive value
        workflow_id = st.session_state.get('current_workflow_id', '')
    
    # Debug output - always visible
    st.caption(f"DEBUG: workflow_id = '{workflow_id}' | from_input='{workflow_input}'")
    
    if workflow_id:
        st.success("✅ Workflow ID detected - about to load sequence...")
    else:
        st.warning("⚠️ No workflow ID")
    
    with col2:
        auto_refresh = st.checkbox("⚡ Auto-refresh", value=st.session_state.auto_refresh)
        st.session_state.auto_refresh = auto_refresh
    
    with col3:
        st.write("")
        if workflow_id and st.button("❌ Stop Sequence", use_container_width=True):
            with st.spinner("Stopping..."):
                result = stop_sequence_sync(workflow_id)
                if result.get('success'):
                    st.success("✅ Stopped!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"❌ {result.get('error', 'Unknown error')}")
    
    # Auto-refresh mechanism
    if auto_refresh and workflow_id:
        st.caption("⏱️ Auto-refreshing every 3 seconds...")
        time.sleep(3)
        st.rerun()
    
    # Debug info
    if st.checkbox("🔧 Show Debug Info", value=False):
        st.json({
            "current_workflow_id": st.session_state.get('current_workflow_id', 'NOT SET'),
            "text_input_value": workflow_id,
            "recent_sequences_count": len(st.session_state.get('recent_sequences', []))
        })
    
    # Show sequence details
    if workflow_id:
        st.success(f"✅ Loading sequence: {workflow_id[:50]}...")
        try:
            render_sequence_details(workflow_id)
        except Exception as e:
            st.error(f"❌ Error rendering sequence: {str(e)}")
            import traceback
            st.code(traceback.format_exc(), language='python')
    else:
        st.info("👆 Enter a Sequence ID above, or click a recent sequence from the list")
        
        # Quick start tip
        st.markdown("---")
        st.markdown("💡 **Tip:** Create a new sequence in the 'New Sequence' tab, then come back here to manage it!")


def render_sequence_details(workflow_id: str):
    """Render details for a specific sequence."""
    
    st.write(f"🔍 Fetching sequence: `{workflow_id}`...")
    
    with st.spinner("Loading state from Temporal..."):
        status_result = get_sequence_status_sync(workflow_id)
    
    # Hide raw result in debug expander
    with st.expander("� Raw API Response (Debug)", expanded=False):
        st.json(status_result)
    
    if not status_result.get('success'):
        st.error(f"❌ Could not retrieve sequence: {status_result.get('error', 'Unknown error')}")
        return
    
    state = status_result.get('state', {})
    
    if not state:
        st.warning("⚠️ Sequence not found or initializing")
        return
    
    # Show nice status badge
    status = state.get('status', 'unknown')
    if status == 'ready':
        st.success(f"✅ Sequence Ready - {state.get('total_steps', 0)} steps available")
    elif status == 'completed':
        st.info(f"ℹ️ Sequence Completed")
    elif status == 'failed':
        st.error(f"❌ Sequence Failed")
    else:
        st.info(f"⏳ Sequence Status: {status}")
    
    # Raw state viewer for debugging
    with st.expander("🔧 View Raw State (Debug)", expanded=False):
        st.json(state)
    
    # Header info
    status = state.get('status', 'unknown')
    company_name = state.get('company_name', 'Unknown')
    persona = state.get('persona', {})
    persona_name = persona.get('full_name', 'Unknown')
    
    # Status badge
    status_colors = {
        'researching': '🔵',
        'generating_strategy': '🟡',
        'parsing_strategy': '🟡',
        'generating_messages': '🟠',
        'ready': '🟢',
        'in_progress': '🔵',
        'completed': '✅',
        'stopped': '⛔',
    }
    status_emoji = status_colors.get(status, '⚪')
    
    st.divider()
    st.markdown(f"### {status_emoji} {company_name} - {persona_name}")
    st.markdown(f"**Status:** `{status}` | **Steps:** {state.get('total_steps', 0)}")
    
    # Show detected language badge and approval mode
    detected_lang = state.get('detected_language')
    approval_mode = state.get('approval_mode', 'per_sequence')
    badge_cols = st.columns([1, 1, 3])
    with badge_cols[0]:
        if detected_lang:
            lang_labels = {"fr": "🇫🇷 French", "en": "🇬🇧 English", "ar": "🇹🇳 Arabic", "de": "🇩🇪 German", "es": "🇪🇸 Spanish"}
            st.caption(f"**Language:** {lang_labels.get(detected_lang, detected_lang)}")
    with badge_cols[1]:
        mode_labels = {"per_sequence": "🔒 Once", "per_step": "🔒 Per step", "per_step_and_message": "🔒 Step+Msg"}
        st.caption(f"**Approval:** {mode_labels.get(approval_mode, approval_mode)}")
    
    # Show approve sequence button for per_sequence mode when ready
    if status == 'ready' and approval_mode == 'per_sequence':
        if st.button("✅ Approve Entire Sequence", type="primary", use_container_width=True):
            with st.spinner("Approving..."):
                result = approve_sequence_sync(workflow_id)
                if result.get('success'):
                    st.success("✅ Sequence approved! Steps will execute on schedule.")
                    st.rerun()
                else:
                    st.error(f"❌ {result.get('error', 'Unknown error')}")
    
    # Gemini analysis (if available)
    if state.get('gemini_strategy'):
        with st.expander("🧠 Gemini Analysis", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                score = state.get('linkedin_activity_score', 0)
                st.metric("LinkedIn Score", f"{score}%")
            
            with col2:
                st.metric("Best Time", state.get('best_time_of_day', '10h'))
            
            with col3:
                st.metric("Steps Generated", len(state.get('steps', [])))
            
            if state.get('personality_analysis'):
                st.markdown(f"**Personality:** {state['personality_analysis'][:200]}...")
    
    # Steps
    steps = state.get('steps', [])
    
    if not steps:
        st.info("⏳ Steps are being generated...")
        return
    
    st.divider()
    st.markdown("### 📧 Sequence Steps")
    
    # Step status summary
    ready_count = sum(1 for s in steps if s.get('status') == 'ready')
    failed_count = sum(1 for s in steps if s.get('status') == 'failed')
    sent_count = sum(1 for s in steps if s.get('status') == 'sent')
    skipped_count = sum(1 for s in steps if s.get('status') == 'skipped')
    
    summary_cols = st.columns(5)
    with summary_cols[0]:
        st.metric("Total", len(steps))
    with summary_cols[1]:
        st.metric("Ready", ready_count, delta=f"{ready_count}/{len(steps)}")
    with summary_cols[2]:
        st.metric("Sent", sent_count, delta=f"{sent_count}/{len(steps)}")
    with summary_cols[3]:
        st.metric("Failed", failed_count, delta_color="off")
    with summary_cols[4]:
        st.metric("Skipped", skipped_count)
    
    # Warning for failed steps
    if failed_count > 0:
        st.error(f"⚠️ **{failed_count} step(s) failed!** Check error details below.")
    
    # Progress bar
    progress = sent_count / len(steps) if steps else 0
    st.progress(progress, text=f"Progress: {sent_count}/{len(steps)} steps sent")
    
    # Store approval mode for step cards
    approval_mode = state.get('approval_mode', 'per_sequence')
    st.session_state.current_approval_mode = approval_mode
    
    # Render each step
    for step in steps:
        render_step_card(step, workflow_id)


def render_step_card(step: dict, workflow_id: str):
    """Render a single step card with approval support."""
    step_num = step.get('step_num', 0)
    status = step.get('status', 'unknown')
    channel = step.get('channel', 'email')
    day_offset = step.get('day_offset', 0)
    time_of_day = step.get('time_of_day', '10h')
    approval_mode = st.session_state.get('current_approval_mode', 'per_sequence')
    
    # Status styling
    status_config = {
        'pending': {'emoji': '⏳', 'color': 'gray'},
        'ready': {'emoji': '✅', 'color': 'blue'},
        'sent': {'emoji': '📤', 'color': 'green'},
        'failed': {'emoji': '❌', 'color': 'red'},
        'skipped': {'emoji': '⏭️', 'color': 'orange'},
        'regenerating': {'emoji': '🔄', 'color': 'yellow'},
    }
    cfg = status_config.get(status, {'emoji': '⚪', 'color': 'gray'})
    
    # Channel emoji
    channel_emoji = '✉️' if channel == 'email' else '💬' if 'linkedin' in channel else '📨'
    
    with st.container():
        st.markdown(f"---")
        
        # Header row
        col1, col2, col3, col4 = st.columns([1, 2, 3, 2])
        
        with col1:
            st.markdown(f"### {cfg['emoji']} Step {step_num}")
        
        with col2:
            st.markdown(f"**{channel_emoji} {channel}**")
            st.caption(f"Day+{day_offset} at {time_of_day}")
        
        with col3:
            if step.get('quality_score'):
                score = step['quality_score']
                color = 'green' if score >= 80 else 'orange' if score >= 60 else 'red'
                st.markdown(f"**Score:** :{color}[{score}/100]")
        
        with col4:
            st.markdown(f"**Status:** `{status}`")
        
        # Error display (for failed steps)
        if status == 'failed' and step.get('error'):
            with st.expander("❌ View Error Details", expanded=True):
                st.error(f"**Error:** {step.get('error')[:500]}")
                if len(step.get('error', '')) > 500:
                    st.code(step.get('error'), language='python')
        
        # Strategy notes
        if step.get('strategy_notes'):
            with st.expander("📝 Strategy Notes"):
                st.markdown(step['strategy_notes'])
        
        # Message preview (if available)
        message_data = step.get('message', {})
        if message_data and message_data.get('message'):
            with st.expander("📧 View Message"):
                if message_data.get('subject'):
                    st.markdown(f"**Subject:** {message_data['subject']}")
                
                st.text_area(
                    "Message:",
                    value=message_data.get('message', ''),
                    height=150,
                    disabled=True,
                    key=f"msg_{workflow_id}_{step_num}"
                )
                
                if message_data.get('warnings'):
                    st.warning(f"⚠️ {len(message_data.get('warnings'))} warnings")
        
        # Action buttons
        if status in ['ready', 'pending']:
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            
            with col1:
                if st.button(f"📤 Send", key=f"send_{workflow_id}_{step_num}", use_container_width=True):
                    with st.spinner("Sending..."):
                        result = send_step_sync(workflow_id, step_num)
                        if result.get('success'):
                            st.success("✅ Sent!")
                            st.rerun()
                        else:
                            st.error(f"❌ {result.get('error')}")
            
            with col2:
                if st.button(f"⏭️ Skip", key=f"skip_{workflow_id}_{step_num}", use_container_width=True):
                    result = skip_step_sync(workflow_id, step_num)
                    if result.get('success'):
                        st.success("⏭️ Skipped!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('error')}")
            
            # Show approve button for per_step modes when step is pending
            if status == 'pending' and approval_mode in ['per_step', 'per_step_and_message']:
                with col3:
                    if st.button(f"✅ Approve", key=f"approve_{workflow_id}_{step_num}", type="primary", use_container_width=True):
                        with st.spinner("Approving..."):
                            result = approve_step_sync(workflow_id, step_num)
                            if result.get('success'):
                                st.success("✅ Step approved!")
                                st.rerun()
                            else:
                                st.error(f"❌ {result.get('error')}")
        
        elif status == 'failed':
            st.warning("⚠️ This step failed. You can regenerate the message.")
            if st.button(f"🔄 Regenerate Message", key=f"regen_{workflow_id}_{step_num}", use_container_width=True):
                with st.spinner("Regenerating..."):
                    result = regenerate_step_sync(workflow_id, step_num)
                    if result.get('success'):
                        st.success("✅ Message regenerated!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('error')}")
                        st.info("Step skipped")
                        st.rerun()
            
            with col3:
                feedback = st.text_input(
                    "Feedback for regeneration",
                    placeholder="Ex: Too formal, lacks personalization...",
                    key=f"feedback_{workflow_id}_{step_num}"
                )
                if feedback and st.button(f"🔄 Regenerate", key=f"regen_{workflow_id}_{step_num}"):
                    with st.spinner("Regenerating..."):
                        result = regenerate_step_sync(workflow_id, step_num, feedback)
                        if result.get('success'):
                            st.success("✅ Regeneration signal sent")
                            st.rerun()
                        else:
                            st.error(f"❌ {result.get('error')}")
        
        elif status == 'sent':
            sent_at = step.get('sent_at', '')
            if sent_at:
                st.caption(f"📤 Sent on: {sent_at}")
            st.success("✅ This step has been sent")
        
        elif status == 'skipped':
            st.info("⏭️ This step was skipped")

# Standalone run
if __name__ == "__main__":
    st.set_page_config(
        page_title="Sequence Manager",
        page_icon="📋",
        layout="wide"
    )
    render_sequence_ui()
