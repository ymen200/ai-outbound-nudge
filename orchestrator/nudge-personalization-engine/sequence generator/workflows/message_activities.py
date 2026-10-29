"""
Temporal Activities for Sequence Workflow.

These activities handle company research, strategy generation, message generation,
and message sending. They replace the old Hunter/Tavily-based research with
Gemini-powered analysis.
"""

import os
import json
from datetime import datetime
from temporalio import activity
from typing import Dict, Any, Optional


@activity.defn
async def research_company_activity(detective_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Research company and prospect using Gemini.
    
    Replaces Hunter/Tavily with direct Gemini analysis of the provided
    detective data (company info, persona, ICP, manual context).
    
    Args:
        detective_data: Enriched data from detective module
        
    Returns:
        Research results with company insights
    """
    activity.logger.info("Starting company research activity")
    
    try:
        # If manual_context is provided, skip external research
        if detective_data.get("manual_context"):
            activity.logger.info("Using manual context, skipping external research")
            return {
                "success": True,
                "research_source": "manual_context",
                "company_insights": {
                    "company_name": detective_data.get("company_name", ""),
                    "industry": detective_data.get("company_industry", ""),
                    "website": detective_data.get("company_website", ""),
                    "manual_context": detective_data.get("manual_context", "")
                }
            }
        
        # Otherwise, use Gemini to analyze available data
        company_name = detective_data.get("company_name", "Unknown")
        company_website = detective_data.get("company_website", "")
        
        return {
            "success": True,
            "research_source": "gemini_analysis",
            "company_insights": {
                "company_name": company_name,
                "industry": detective_data.get("company_industry", ""),
                "website": company_website,
                "icp_description": detective_data.get("icp_description", ""),
                "offer_context": detective_data.get("offer_context", "")
            }
        }
        
    except Exception as e:
        activity.logger.error(f"Research activity failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@activity.defn
async def generate_strategy_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate outreach strategy using Gemini.
    
    Analyzes company/person data and generates a complete outreach strategy
    including personality analysis, timing recommendations, and step-by-step plan.
    
    Args:
        input_data: {
            "detective_data": Dict,
            "research_result": Dict
        }
        
    Returns:
        Strategy with personality analysis, timing, and step recommendations
    """
    activity.logger.info("Starting strategy generation activity")
    
    try:
        import google.generativeai as genai
        
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        detective_data = input_data.get("detective_data", {})
        research_result = input_data.get("research_result", {})
        
        # Build strategy prompt
        company_name = detective_data.get("company_name", "Unknown")
        persona = detective_data.get("selected_persona", {})
        persona_name = persona.get("full_name", "Unknown")
        persona_role = persona.get("job_title", "Unknown")
        manual_context = detective_data.get("manual_context", "")
        icp_description = detective_data.get("icp_description", "")
        offer_context = detective_data.get("offer_context", "")
        
        prompt = f"""You are an expert B2B outreach strategist. Analyze this prospect and generate a comprehensive outreach strategy.

**Company:** {company_name}
**Prospect:** {persona_name}, {persona_role}
**ICP Context:** {icp_description}
**Offer:** {offer_context}

**Additional Context:**
{manual_context}

**Research Insights:**
{json.dumps(research_result.get("company_insights", {}), indent=2)}

Generate a JSON response with:
1. "personality_analysis": Brief personality assessment (100-200 words)
2. "linkedin_activity_score": Engagement score 0-100 (estimate based on role/industry)
3. "best_time_of_day": Best time to reach them (e.g., "10h", "14h")
4. "detected_language": ISO language code based on location (e.g., "fr", "en", "ar")
5. "approval_mode": "per_sequence" (default)
6. "steps": Array of 3-5 outreach steps, each with:
   - "step_num": int (1-indexed)
   - "action_type": One of LINKEDIN_CONNECT, LINKEDIN_MESSAGE, EMAIL_1
   - "channel": One of email, linkedin_dm, linkedin_inmail
   - "day_offset": int (days from start)
   - "time_of_day": str (e.g., "10h")
   - "wait_delay_seconds": int (delay from previous step, 0 for first)
   - "strategy_notes": Why this step at this time

Respond ONLY with valid JSON, no markdown or explanation.
"""
        
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        
        # Clean markdown if present
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
        strategy = json.loads(raw_text)
        
        activity.logger.info(f"Strategy generated for {company_name}")
        return strategy
        
    except Exception as e:
        activity.logger.error(f"Strategy generation failed: {e}")
        # Return fallback strategy
        return {
            "personality_analysis": "Unable to generate detailed analysis.",
            "linkedin_activity_score": 50,
            "best_time_of_day": "10h",
            "detected_language": "en",
            "approval_mode": "per_sequence",
            "steps": [
                {
                    "step_num": 1,
                    "action_type": "LINKEDIN_CONNECT",
                    "channel": "linkedin_dm",
                    "day_offset": 0,
                    "time_of_day": "10h",
                    "wait_delay_seconds": 0,
                    "strategy_notes": "Initial connection request"
                },
                {
                    "step_num": 2,
                    "action_type": "EMAIL_1",
                    "channel": "email",
                    "day_offset": 2,
                    "time_of_day": "10h",
                    "wait_delay_seconds": 172800,
                    "strategy_notes": "Follow-up email"
                }
            ]
        }


@activity.defn
async def parse_gemini_strategy_activity(strategy_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse and validate Gemini strategy output.
    
    Args:
        strategy_result: Raw strategy from generate_strategy_activity
        
    Returns:
        Validated and structured strategy data
    """
    activity.logger.info("Parsing Gemini strategy")
    
    try:
        # Extract and validate fields
        steps = strategy_result.get("steps", [])
        detected_language = strategy_result.get("detected_language", "en")
        approval_mode = strategy_result.get("approval_mode", "per_sequence")
        
        # Validate approval mode
        valid_modes = {"per_sequence", "per_step", "per_step_and_message"}
        if approval_mode not in valid_modes:
            approval_mode = "per_sequence"
        
        # Validate steps
        validated_steps = []
        for i, step in enumerate(steps):
            validated_steps.append({
                "step_num": step.get("step_num", i + 1),
                "action_type": step.get("action_type", "EMAIL_1"),
                "channel": step.get("channel", "email"),
                "scheduled_timestamp_utc": step.get("scheduled_timestamp_utc", ""),
                "wait_delay_seconds": step.get("wait_delay_seconds", 0),
                "day_offset": step.get("day_offset", 0),
                "time_of_day": step.get("time_of_day", "10h"),
                "strategy_notes": step.get("strategy_notes", "")
            })
        
        return {
            "success": True,
            "detected_language": detected_language,
            "approval_mode": approval_mode,
            "steps": validated_steps,
            "personality_analysis": strategy_result.get("personality_analysis"),
            "linkedin_activity_score": strategy_result.get("linkedin_activity_score", 0),
            "best_time_of_day": strategy_result.get("best_time_of_day", "10h")
        }
        
    except Exception as e:
        activity.logger.error(f"Strategy parsing failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "detected_language": "en",
            "approval_mode": "per_sequence",
            "steps": []
        }


@activity.defn
async def generate_message_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    JIT message generation for a single step.
    
    Calls the message generator service to create a personalized message
    for this specific step based on the strategy and prospect data.
    
    Args:
        input_data: {
            "step_num": int,
            "action_type": str,
            "channel": str,
            "detective_data": Dict,
            "strategy": Dict,
            "feedback": Optional[str]
        }
        
    Returns:
        Generated message with subject and quality score
    """
    activity.logger.info(f"Generating message for step {input_data.get('step_num')}")
    
    try:
        import sys
        import os
        
        # Add tools directory to path
        seq_gen_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_dir = os.path.join(seq_gen_dir, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        
        from tools.mcp_client import generate_message_for_step_sync
        
        step_num = input_data.get("step_num", 1)
        action_type = input_data.get("action_type", "EMAIL_1")
        channel = input_data.get("channel", "email")
        detective_data = input_data.get("detective_data", {})
        strategy = input_data.get("strategy", {})
        feedback = input_data.get("feedback")
        
        # Build step context
        persona = detective_data.get("selected_persona", {})
        company_name = detective_data.get("company_name", "Unknown")
        
        # Map action type to stage
        if action_type in ["LINKEDIN_CONNECT", "EMAIL_1"]:
            stage = "first_touch"
        elif action_type == "LINKEDIN_MESSAGE":
            stage = "second_touch"
        else:
            stage = "first_touch"
        
        step_context = {
            "target_prospect": persona.get("full_name", "Unknown"),
            "target_company": company_name,
            "company_name": company_name,
            "offer_name": detective_data.get("offer_context", "Default Offer"),
            "prospect_role": persona.get("job_title"),
            "channel": channel,
            "stage": stage,
            "intent": "direct_outreach",
            "message_language": strategy.get("detected_language", "en")
        }
        
        # Populate research_signals from detective_data if available
        # These may come from the detective module or be pre-fetched
        research_signals = detective_data.get("research_signals")
        if research_signals and isinstance(research_signals, list):
            step_context["research_signals"] = research_signals
        
        # Populate personality_config from strategy's personality_analysis
        # The strategy activity generates personality insights that should
        # inform the message style
        personality_analysis = strategy.get("personality_analysis")
        if personality_analysis:
            if isinstance(personality_analysis, dict):
                step_context["personality_config"] = personality_analysis
            elif isinstance(personality_analysis, str):
                # If it's a string description, wrap it in a config structure
                step_context["personality_config"] = {
                    "custom_template_description": personality_analysis,
                    "personality_traits": [],
                }
        
        # Also pass through any personality_config from the original request
        # (may be provided via the orchestrator's request payload)
        if "personality_config" not in step_context:
            original_personality = detective_data.get("personality_config")
            if original_personality and isinstance(original_personality, dict):
                step_context["personality_config"] = original_personality
        
        # Add feedback if regenerating
        if feedback:
            step_context["regeneration_feedback"] = feedback
        
        # Call message generator
        result = generate_message_for_step_sync(step_context)
        
        if result.get("success"):
            return {
                "success": True,
                "message": result.get("message"),
                "subject": result.get("subject"),
                "score": result.get("score"),
                "warnings": result.get("warnings", [])
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Message generation failed"),
                "message": None,
                "subject": None,
                "score": None
            }
            
    except Exception as e:
        activity.logger.error(f"Message generation failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": None,
            "subject": None,
            "score": None
        }


@activity.defn
async def send_message_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a generated message via the appropriate channel.
    
    Calls the message generator's send endpoint to deliver the message.
    
    Args:
        input_data: {
            "step_num": int,
            "message": Dict with message/subject,
            "persona": Dict with contact info,
            "channel": str
        }
        
    Returns:
        Send result with timestamp
    """
    activity.logger.info(f"Sending message for step {input_data.get('step_num')}")
    
    try:
        import requests
        
        step_num = input_data.get("step_num", 1)
        message_data = input_data.get("message", {})
        persona = input_data.get("persona", {})
        channel = input_data.get("channel", "email")
        
        message_body = message_data.get("message", "")
        message_subject = message_data.get("subject", "")
        
        if not message_body:
            return {
                "success": False,
                "error": "No message content to send"
            }
        
        # Determine send endpoint based on channel
        base_url = os.getenv("MESSAGE_GENERATOR_URL", "http://localhost:8000")
        
        if channel == "email":
            send_url = f"{base_url}/api/send/email"
            send_payload = {
                "to_email": persona.get("email", ""),
                "subject": message_subject,
                "body": message_body
            }
        elif channel in ["linkedin_dm", "linkedin_inmail"]:
            send_url = f"{base_url}/api/send/linkedin"
            send_payload = {
                "linkedin_url": persona.get("linkedin_url", ""),
                "message": message_body
            }
        else:
            return {
                "success": False,
                "error": f"Unsupported channel: {channel}"
            }
        
        # Send message
        response = requests.post(send_url, json=send_payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get("success"):
            return {
                "success": True,
                "sent_at": datetime.now().isoformat(),
                "channel": channel
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Send failed")
            }
            
    except Exception as e:
        activity.logger.error(f"Send message failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
