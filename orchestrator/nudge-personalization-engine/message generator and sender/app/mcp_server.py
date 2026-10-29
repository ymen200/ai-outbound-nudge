"""
MCP Server — exposes the outreach pipeline as tools.

Any external agent (Claude, GPT, another LangGraph agent, etc.) can
connect to this server and call the pipeline via the MCP protocol.

Run standalone:
    python -m app.mcp_server

Or mount alongside FastAPI (see main.py for the /mcp SSE mount).

Tools exposed:
    generate_outreach   — run the full pipeline, returns final message + score
    check_prospect      — check if a prospect is in memory / do-not-contact
    mark_do_not_contact — flag a prospect as DNC
"""

import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .models import (
    GenerateRequest, Channel, Intent, Stage,
    Personality, CompanyDetails, SelectedOffer, Signal
)
from .orchestrator import PipelineOrchestrator
from .memory import MemoryService

app = Server("agentic-outreach")


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_outreach",
            description=(
                "Run the full multi-agent outreach pipeline for a prospect. "
                "Returns the generated message, subject line, quality score, "
                "and any warnings. Use this when you need to draft a personalized "
                "sales or outreach message."
            ),
            inputSchema={
                "type": "object",
                "required": ["target_prospect", "target_company", "company_name", "offer_name"],
                "properties": {
                    "target_prospect":  {"type": "string", "description": "Full name of the prospect"},
                    "target_company":   {"type": "string", "description": "Prospect's company"},
                    "prospect_role":    {"type": "string", "description": "Prospect's job title (optional)"},
                    "channel":          {"type": "string", "enum": ["linkedin_dm", "linkedin_inmail", "email"], "default": "linkedin_dm"},
                    "stage":            {"type": "string", "enum": ["first_touch", "second_touch", "third_touch"], "default": "first_touch"},
                    "intent":           {"type": "string", "enum": ["direct_outreach", "follow_up", "referral", "re_engagement", "event_based"], "default": "direct_outreach"},
                    "company_name":     {"type": "string", "description": "Sender's company name"},
                    "elevator_pitch":   {"type": "string", "description": "One-sentence pitch of what the sender's company does"},
                    "offer_name":       {"type": "string", "description": "Name of the offer or product being pitched"},
                    "solution_summary": {"type": "string", "description": "Brief description of the offer"},
                    "cta":              {"type": "string", "description": "Call to action text"},
                    "user_notes":       {"type": "string", "description": "Human feedback/notes to guide message generation. Injected as 'user notes: ' in the writer prompt."},
                    "language":         {"type": "string", "description": "ISO 639-1 language code for message generation (e.g., 'en', 'fr'). If not provided, defaults to English."},
                    "research_signals": {"type": "array", "description": "Pre-fetched research signals. Each item: {type, content, strength, why_relevant, source_url?, timestamp?}", "items": {"type": "object"}},
                    "personality_config": {"type": "object", "description": "Personality/style configuration. Fields: base_template, personality_traits, always_include_phrases, never_use_phrases, touchdowns_per_message, enabled_hook_types, urgency_level."},
                },
            },
        ),
        Tool(
            name="check_prospect",
            description="Check if a prospect exists in memory and whether they are marked do-not-contact.",
            inputSchema={
                "type": "object",
                "required": ["name", "company"],
                "properties": {
                    "name":    {"type": "string"},
                    "company": {"type": "string"},
                },
            },
        ),
        Tool(
            name="mark_do_not_contact",
            description="Mark a prospect as do-not-contact so the pipeline will refuse to generate messages for them.",
            inputSchema={
                "type": "object",
                "required": ["name", "company"],
                "properties": {
                    "name":    {"type": "string"},
                    "company": {"type": "string"},
                },
            },
        ),
    ]


# ------------------------------------------------------------------
# Tool handlers
# ------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "generate_outreach":
        try:
            # Build personality from personality_config if provided, else default
            personality_config = arguments.get("personality_config")
            if personality_config and isinstance(personality_config, dict):
                personality = Personality(
                    base_template=personality_config.get("base_template", "soft_sell"),
                    custom_template_description=personality_config.get("custom_template_description"),
                    personality_traits=personality_config.get("personality_traits", []),
                    always_include_phrases=personality_config.get("always_include_phrases", []),
                    never_use_phrases=personality_config.get("never_use_phrases", []),
                    touchdowns_per_message=personality_config.get("touchdowns_per_message", 2),
                    enabled_hook_types=personality_config.get("enabled_hook_types", []),
                    urgency_level=personality_config.get("urgency_level", 3),
                )
            else:
                personality = Personality()

            # Build research signals from list of dicts if provided
            raw_signals = arguments.get("research_signals")
            research_signals = None
            if raw_signals and isinstance(raw_signals, list):
                research_signals = [
                    Signal(
                        type=s.get("type", "general"),
                        content=s.get("content", ""),
                        strength=s.get("strength", "medium"),
                        source_url=s.get("source_url"),
                        timestamp=s.get("timestamp"),
                        why_relevant=s.get("why_relevant", ""),
                    )
                    for s in raw_signals
                    if isinstance(s, dict)
                ]

            # Extract language for output control
            language = arguments.get("language")

            orchestrator = PipelineOrchestrator(
                target_prospect=arguments["target_prospect"],
                target_company=arguments["target_company"],
                prospect_role=arguments.get("prospect_role"),
                channel=Channel(arguments.get("channel", "linkedin_dm")),
                intent=Intent(arguments.get("intent", "direct_outreach")),
                stage=Stage(arguments.get("stage", "first_touch")),
                personality=personality,
                company_details=CompanyDetails(
                    company_name=arguments["company_name"],
                    elevator_pitch=arguments.get("elevator_pitch"),
                ),
                selected_offer=SelectedOffer(
                    offer_name=arguments["offer_name"],
                    solution_summary=arguments.get("solution_summary"),
                    cta=arguments.get("cta"),
                ),
                research_signals=research_signals,
                user_feedback=arguments.get("user_notes"),
                language=language,
            )
            history = orchestrator.run_full_pipeline()
            final = history[-1]

            if final.status.value == "complete" and final.draft:
                result = {
                    "success": True,
                    "message": final.draft.body,
                    "subject": final.draft.subject,
                    "score": final.validation.score if final.validation else None,
                    "warnings": final.validation.warnings if final.validation else [],
                    "status": "approved"
                }
            elif final.status.value == "awaiting_human" and final.draft:
                # Human review required - return draft for approval
                result = {
                    "success": True,
                    "pending_approval": True,
                    "message": final.draft.body,
                    "subject": final.draft.subject,
                    "score": final.validation.score if final.validation else None,
                    "warnings": final.validation.warnings if final.validation else [],
                    "status": "awaiting_human",
                    "reason": final.next_action.get("reason") if final.next_action else "Awaiting human review"
                }
            else:
                result = {
                    "success": False,
                    "reason": final.next_action.get("reason") if final.next_action else "Pipeline failed",
                    "score": final.validation.score if final.validation else None,
                    "status": final.status.value
                }

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

    elif name == "check_prospect":
        record = MemoryService.prospects.get(
            name=arguments["name"],
            company=arguments["company"]
        )
        if record is None:
            result = {"found": False, "do_not_contact": False}
        else:
            result = {
                "found": True,
                "do_not_contact": record.do_not_contact,
                "times_contacted": record.times_contacted,
                "ever_replied": record.ever_replied,
                "last_contacted_at": record.last_contacted_at,
            }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "mark_do_not_contact":
        MemoryService.prospects.mark_do_not_contact(
            name=arguments["name"],
            company=arguments["company"]
        )
        return [TextContent(type="text", text=json.dumps({"success": True}))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ------------------------------------------------------------------
# Entrypoint for standalone stdio mode
# ------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
