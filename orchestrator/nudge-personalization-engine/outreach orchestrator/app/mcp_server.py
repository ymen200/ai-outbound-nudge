"""
MCP Server — the global orchestrator's gateway to the Outreach system.

Exposes 7 tools:
1. run_outreach_pipeline — full end-to-end sequence + message generation
2. get_outreach_status — status of running/completed pipeline
3. get_observability — aggregated metrics from both modules
4. get_prompt_history — actual prompts sent to LLM
5. override_module_config — change runtime parameters
6. inject_feedback — inject feedback to steer future generations
7. get_module_capabilities — agent card advertising capabilities

Run standalone:
    python -m app.mcp_server

Or mounted alongside FastAPI (see main.py for /mcp SSE mount).
"""

import json
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .clients import SequenceGeneratorClient, MessageGeneratorClient
from .observability import ObservabilityAggregator
from .graph import run_orchestrator
from .state import OrchestratorState
from .config import settings

logger = logging.getLogger(__name__)

app = Server("outreach-orchestrator")

# Shared aggregator instance (lazy init)
_aggregator: ObservabilityAggregator = None


def _get_aggregator() -> ObservabilityAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = ObservabilityAggregator()
    return _aggregator


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="run_outreach_pipeline",
            description=(
                "Run the full outreach pipeline: sequence generation + JIT message generation. "
                "Calls the Sequence Generator which internally generates sequences and messages. "
                "Returns steps with messages, quality scores, and observability snapshot. "
                "If status is 'awaiting_approval', use approve_pipeline with the returned thread_id."
            ),
            inputSchema={
                "type": "object",
                "required": ["entreprise", "contact_full_name"],
                "properties": {
                    "lead_id": {"type": "string", "description": "Unique lead ID (auto-generated if empty)"},
                    "campaign_id": {"type": "string", "default": "default_campaign"},
                    "entreprise": {"type": "string", "description": "Prospect's company name"},
                    "contact_full_name": {"type": "string", "description": "Prospect's full name"},
                    "contact_job_title": {"type": "string", "default": ""},
                    "contact_email": {"type": "string", "default": ""},
                    "contact_country": {"type": "string", "default": ""},
                    "contact_city": {"type": "string", "default": ""},
                    "contact_linkedin": {"type": "string", "default": ""},
                    "is_connected_on_linkedin": {"type": "boolean", "default": False},
                    "has_inmail_credits": {"type": "boolean", "default": False, "description": "LinkedIn InMail credits available (Sales Navigator / premium). Enables LINKEDIN_INMAIL action type when not connected."},
                    "web_profil_brut": {"type": "string", "default": "", "description": "Raw web profile / research summary"},
                    "web_offer_context": {"type": "string", "default": ""},
                    "web_icp_description": {"type": "string", "default": ""},
                    "research_signals": {
                        "type": "array",
                        "description": "Pre-fetched research signals from upstream modules",
                        "items": {"type": "object"},
                    },
                    "sender_company": {"type": "string", "default": "My Company"},
                    "sender_elevator_pitch": {"type": "string", "default": ""},
                    "offer_name": {"type": "string", "default": "Default Offer"},
                    "solution_summary": {"type": "string", "default": ""},
                    "cta": {"type": "string", "default": ""},
                    "use_native_language": {"type": "boolean", "default": False},
                    "message_language": {"type": "string", "description": "ISO 639-1 override (e.g. 'fr')"},
                    "approval_mode": {"type": "string", "default": "per_sequence"},
                    "feedback": {"type": "string", "description": "Optional feedback to inject into modules"},
                    "config_overrides": {
                        "type": "object",
                        "description": "Optional config overrides per module: {module_name: {key: value}}",
                    },
                    "debug_mode": {
                        "type": "boolean",
                        "default": True,
                        "description": "When true, both modules bypass memory reads/writes for deterministic runs. Propagated via config override.",
                    },
                    "max_touches": {
                        "type": "integer",
                        "description": "Max number of touches in the sequence (optional, AI decides if omitted)",
                    },
                    "max_days": {
                        "type": "integer",
                        "description": "Max days the sequence can span (optional, AI decides if omitted)",
                    },
                    "preferred_first_channel": {
                        "type": "string",
                        "enum": ["email", "linkedin_dm", "linkedin_inmail"],
                        "description": "Preferred channel for the first touch (optional, AI decides if omitted)",
                    },
                    "sequence_options": {
                        "type": "object",
                        "description": "Boolean flags: vary_tone, include_breakup, reference_previous, escalate_urgency, cross_channel",
                    },
                    "stage_instructions": {
                        "type": "object",
                        "description": "Per-stage custom instructions: {stage_name: instruction_text}",
                    },
                    "personality_config": {
                        "type": "object",
                        "description": "Message personality config: base_template, personality_traits, always_include_phrases, never_use_phrases, urgency_level, humor_sarcasm, voice_samples, stage_instructions",
                    },
                },
            },
        ),
        Tool(
            name="get_outreach_status",
            description=(
                "Get health status of both downstream modules (Sequence Generator + Message Generator). "
                "Also reports any pipelines currently in 'awaiting_approval' state."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="approve_pipeline",
            description=(
                "Approve or reject a paused outreach sequence. "
                "Use after run_outreach_pipeline returns status='awaiting_approval'. "
                "The orchestrator owns zero approval state — this forwards directly to the Sequence Generator. "
                "When approved=true, dispatches to Temporal. "
                "When approved=false with feedback, regenerates the sequence with the feedback injected."
            ),
            inputSchema={
                "type": "object",
                "required": ["thread_id"],
                "properties": {
                    "thread_id": {
                        "type": "string",
                        "description": "The thread_id from the run_outreach_pipeline response (present when status='awaiting_approval')",
                    },
                    "approved": {
                        "type": "boolean",
                        "default": True,
                        "description": "True to approve and dispatch, False to reject with feedback",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Feedback for regeneration (used when approved=False)",
                    },
                },
            },
        ),
        Tool(
            name="get_observability",
            description=(
                "Get aggregated observability metrics from both modules: token usage, "
                "LLM call counts, quality scores, model info, latency stats."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_prompt_history",
            description=(
                "Get actual prompts sent to LLM, organized by module and agent step. "
                "Useful for auditing, debugging, and the global orchestrator's feedback loop."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": ["sequence_generator", "message_generator"],
                        "description": "Filter by module (omit for both)",
                    },
                    "agent_step": {
                        "type": "string",
                        "description": "Filter by agent step (researcher, strategist, writer, critic, sequence_generator)",
                    },
                    "limit": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="override_module_config",
            description=(
                "Change runtime parameters on a module. "
                "Sequence Generator allows: GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS, GEMINI_MODEL, MAX_RETRIES. "
                "Message Generator allows: GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS, MAX_ITERATIONS, MIN_QUALITY_SCORE."
            ),
            inputSchema={
                "type": "object",
                "required": ["module", "overrides"],
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": ["sequence_generator", "message_generator"],
                    },
                    "overrides": {
                        "type": "object",
                        "description": "Key-value pairs of config overrides",
                    },
                },
            },
        ),
        Tool(
            name="inject_feedback",
            description=(
                "Inject feedback text that influences future generations. "
                "The global orchestrator's feedback loop uses this to steer the system. "
                "Feedback is prepended to the next LLM prompt as a system directive. "
                "When lead_id is provided, feedback is scoped to that lead only — "
                "it will NOT be consumed by other concurrent sequences."
            ),
            inputSchema={
                "type": "object",
                "required": ["module", "feedback_text"],
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": ["sequence_generator", "message_generator"],
                    },
                    "feedback_text": {"type": "string"},
                    "lead_id": {
                        "type": "string",
                        "description": "Scope feedback to this lead ID. Prevents cross-contamination under concurrent sequences.",
                    },
                },
            },
        ),
        Tool(
            name="get_module_capabilities",
            description=(
                "Agent card — discover what this outreach system can do. "
                "Returns supported channels, languages, current config, and available tools."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    aggregator = _get_aggregator()

    try:
        if name == "run_outreach_pipeline":
            state = OrchestratorState(
                lead_id=arguments.get("lead_id", ""),
                campaign_id=arguments.get("campaign_id", "default_campaign"),
                entreprise=arguments["entreprise"],
                contact_info={
                    "full_name": arguments["contact_full_name"],
                    "nom": arguments["contact_full_name"],
                    "job_title": arguments.get("contact_job_title", ""),
                    "titre": arguments.get("contact_job_title", ""),
                    "email": arguments.get("contact_email", ""),
                    "country": arguments.get("contact_country", ""),
                    "city": arguments.get("contact_city", ""),
                    "linkedin": arguments.get("contact_linkedin", ""),
                    "location": f"{arguments.get('contact_city', '')}, {arguments.get('contact_country', '')}".strip(", "),
                },
                contexte_web={
                    "profil_brut": arguments.get("web_profil_brut", ""),
                    "offer_context": arguments.get("web_offer_context", ""),
                    "icp_description": arguments.get("web_icp_description", ""),
                },
                research_signals=arguments.get("research_signals"),
                is_connected_on_linkedin=arguments.get("is_connected_on_linkedin", False),
                has_inmail_credits=arguments.get("has_inmail_credits", False),
                use_native_language=arguments.get("use_native_language", False),
                message_language=arguments.get("message_language"),
                approval_mode=arguments.get("approval_mode", "per_sequence"),
                sender_company=arguments.get("sender_company", "My Company"),
                sender_elevator_pitch=arguments.get("sender_elevator_pitch", ""),
                offer_name=arguments.get("offer_name", "Default Offer"),
                solution_summary=arguments.get("solution_summary", ""),
                cta=arguments.get("cta", ""),
                max_touches=arguments.get("max_touches"),
                max_days=arguments.get("max_days"),
                preferred_first_channel=arguments.get("preferred_first_channel"),
                sequence_options=arguments.get("sequence_options"),
                stage_instructions=arguments.get("stage_instructions"),
                personality_config=arguments.get("personality_config"),
                feedback=arguments.get("feedback"),
                config_overrides=arguments.get("config_overrides"),
                debug_mode=arguments.get("debug_mode", True),
            )
            result = await run_orchestrator(state)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "get_outreach_status":
            health = await aggregator.check_health()
            # Surface real pipeline state by querying Sequence Generator for paused threads
            try:
                seq_obs = await aggregator.seq_client.get_observability()
                paused = await aggregator.seq_client.get_paused_threads()
                health["pipeline_status"] = {
                    "paused_threads": paused.get("paused_threads", []),
                    "paused_count": len(paused.get("paused_threads", [])),
                    "note": (
                        "Threads listed in paused_threads are awaiting human approval. "
                        "Use approve_pipeline with the thread_id to approve or reject."
                        if paused.get("paused_threads")
                        else "No pipelines currently paused. Run run_outreach_pipeline to start one."
                    ),
                    "sequence_generator_observability": seq_obs,
                    "sequence_generator_health": health.get("sequence_generator", {}),
                }
            except Exception as e:
                health["pipeline_status"] = {
                    "error": str(e),
                    "paused_threads": [],
                    "note": "Could not fetch Sequence Generator state. "
                           "Check run_outreach_pipeline response for status field.",
                }
            return [TextContent(type="text", text=json.dumps(health, indent=2))]

        elif name == "approve_pipeline":
            thread_id = arguments["thread_id"]
            approved = arguments.get("approved", True)
            feedback = arguments.get("feedback")
            seq_client = SequenceGeneratorClient()
            result = await seq_client.approve_sequence(
                thread_id=thread_id,
                approved=approved,
                feedback=feedback,
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "get_observability":
            snapshot = await aggregator.collect_full_snapshot()
            return [TextContent(type="text", text=json.dumps(snapshot, indent=2, default=str))]

        elif name == "get_prompt_history":
            history = await aggregator.get_prompt_history(
                module=arguments.get("module"),
                agent_step=arguments.get("agent_step"),
                limit=arguments.get("limit", 50),
            )
            return [TextContent(type="text", text=json.dumps(history, indent=2))]

        elif name == "override_module_config":
            result = await aggregator.override_config(
                module=arguments["module"],
                overrides=arguments["overrides"],
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "inject_feedback":
            result = await aggregator.inject_feedback(
                module=arguments["module"],
                feedback=arguments["feedback_text"],
                lead_id=arguments.get("lead_id"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_module_capabilities":
            capabilities = {
                "system_name": "Outreach Orchestrator",
                "version": settings.APP_VERSION,
                "description": "Hierarchical multi-agent outreach system for B2B prospecting",
                "architecture": {
                    "orchestrator": {"port": settings.PORT, "role": "domain coordinator"},
                    "sequence_generator": {"port": 8001, "role": "sequence planning + JIT message generation"},
                    "message_generator": {"port": 8000, "role": "5-agent LLM pipeline (planner, researcher, strategist, writer, critic)"},
                },
                "supported_channels": ["email", "linkedin_dm", "linkedin_inmail"],
                "supported_languages": "Auto-detect from country, or explicit ISO 639-1 override",
                "mcp_tools": [
                    "run_outreach_pipeline",
                    "approve_pipeline",
                    "get_outreach_status",
                    "get_observability",
                    "get_prompt_history",
                    "override_module_config",
                    "inject_feedback",
                    "get_module_capabilities",
                ],
                "feedback_loop": (
                    "The global orchestrator can use get_observability + get_prompt_history to analyze "
                    "system performance, then use inject_feedback + override_module_config to steer behavior. "
                    "This creates a closed feedback loop managed entirely by the global orchestrator."
                ),
            }
            return [TextContent(type="text", text=json.dumps(capabilities, indent=2))]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.error(f"MCP tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ---------------------------------------------------------------------------
# Entrypoint for standalone stdio mode
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
