"""
MCP Client for calling the Message Generator tool.
Supports both stdio (subprocess) and SSE (HTTP) connection modes.
On Windows, uses SSE mode by default for reliability.
"""

import os
import sys
import json
import asyncio
import subprocess
import httpx
from typing import Dict, Any, Optional, List
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client


def _resolve_server_cwd():
    """Resolve absolute path to message generator directory."""
    # tools/mcp_client.py -> sequence generator -> Outreach-Project
    seq_gen_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_dir = os.path.dirname(seq_gen_dir)
    
    # Try env var first
    env_cwd = os.getenv("MCP_SERVER_CWD")
    if env_cwd:
        # Handle relative paths like "../message generator and sender"
        if env_cwd.startswith(".."):
            env_cwd = os.path.normpath(os.path.join(seq_gen_dir, env_cwd))
        return os.path.abspath(env_cwd)
    
    # Default: sibling directory in project root
    default_path = os.path.join(project_dir, "message generator and sender")
    return os.path.abspath(default_path)


class MessageGeneratorMCPClient:
    """Client to call the message generator's generate_outreach MCP tool."""
    
    def __init__(self):
        # On Windows, use SSE mode; on other platforms use stdio
        if os.name == 'nt':
            self.connection_mode = "sse"
        else:
            self.connection_mode = os.getenv("MCP_CONNECTION_MODE", "stdio")
        self.sse_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
        self.server_command = os.getenv("MCP_SERVER_COMMAND", "python -m app.mcp_server")
        self.server_cwd = _resolve_server_cwd()
    
    async def _get_session(self):
        """Get an MCP session based on connection mode."""
        if self.connection_mode == "sse":
            # HTTP SSE connection
            async with sse_client(self.sse_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        else:
            # Stdio subprocess connection
            server_params = StdioServerParameters(
                command=self.server_command.split()[0],
                args=self.server_command.split()[1:] if len(self.server_command.split()) > 1 else [],
                env={**os.environ, "PYTHONPATH": self.server_cwd}
            )
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
    
    async def generate_outreach(
        self,
        target_prospect: str,
        target_company: str,
        company_name: str,
        offer_name: str,
        prospect_role: Optional[str] = None,
        channel: str = "linkedin_dm",
        stage: str = "first_touch",
        intent: str = "direct_outreach",
        elevator_pitch: Optional[str] = None,
        solution_summary: Optional[str] = None,
        cta: Optional[str] = None,
        language: Optional[str] = None,
        research_signals: Optional[List[Dict[str, Any]]] = None,
        personality_config: Optional[Dict[str, Any]] = None,
        user_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call the generate_outreach MCP tool.
        
        Returns:
            {
                "success": bool,
                "message": str,  # generated message body
                "subject": str or None,
                "score": int,
                "warnings": list,
                "error": str (if failed)
            }
        """
        try:
            # Use async context manager properly
            if self.connection_mode == "sse":
                async with sse_client(self.sse_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tool_args = {
                            "target_prospect": target_prospect,
                            "target_company": target_company,
                            "company_name": company_name,
                            "offer_name": offer_name,
                            "prospect_role": prospect_role,
                            "channel": channel,
                            "stage": stage,
                            "intent": intent,
                            "elevator_pitch": elevator_pitch,
                            "solution_summary": solution_summary,
                            "cta": cta
                        }
                        if language:
                            tool_args["language"] = language
                        if research_signals:
                            tool_args["research_signals"] = research_signals
                        if personality_config:
                            tool_args["personality_config"] = personality_config
                        if user_notes:
                            tool_args["user_notes"] = user_notes
                        return await self._call_tool(session, tool_args)
            else:
                # Stdio mode
                server_params = StdioServerParameters(
                    command=self.server_command.split()[0],
                    args=self.server_command.split()[1:] if len(self.server_command.split()) > 1 else [],
                    env={**os.environ, "PYTHONPATH": self.server_cwd}
                )
                async with stdio_client(server_params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tool_args = {
                            "target_prospect": target_prospect,
                            "target_company": target_company,
                            "company_name": company_name,
                            "offer_name": offer_name,
                            "prospect_role": prospect_role,
                            "channel": channel,
                            "stage": stage,
                            "intent": intent,
                            "elevator_pitch": elevator_pitch,
                            "solution_summary": solution_summary,
                            "cta": cta
                        }
                        if language:
                            tool_args["language"] = language
                        if research_signals:
                            tool_args["research_signals"] = research_signals
                        if personality_config:
                            tool_args["personality_config"] = personality_config
                        if user_notes:
                            tool_args["user_notes"] = user_notes
                        return await self._call_tool(session, tool_args)
        except Exception as e:
            import traceback
            error_detail = f"MCP connection failed: {str(e)}\n"
            error_detail += f"Resolved CWD: {self.server_cwd}\n"
            error_detail += f"Command: {self.server_command}\n"
            error_detail += f"Traceback: {traceback.format_exc()}"
            return {
                "success": False,
                "error": error_detail,
                "message": None,
                "subject": None,
                "score": None,
                "warnings": []
            }
    
    async def _call_tool(self, session: ClientSession, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Actually call the tool with the session."""
        result = await session.call_tool("generate_outreach", arguments=arguments)
        
        # Parse the result
        if result and len(result) > 0:
            content = result[0]
            if hasattr(content, 'text'):
                try:
                    return json.loads(content.text)
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"Invalid JSON response: {content.text}",
                        "message": None,
                        "subject": None,
                        "score": None,
                        "warnings": []
                    }
        
        return {
            "success": False,
            "error": "Empty or invalid response from MCP tool",
            "message": None,
            "subject": None,
            "score": None,
            "warnings": []
        }


async def generate_message_for_step(step_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    JIT message generation for a single step.
    
    Takes the step's context and calls the message generator for just-in-time
    message generation. This is called by the message_generation_node or by
    Temporal activities during step execution.
    
    Args:
        step_context: Dictionary containing:
            - target_prospect: str
            - target_company: str
            - company_name: str
            - offer_name: str
            - prospect_role: Optional[str]
            - channel: str (email, linkedin_dm, etc.)
            - stage: str (first_touch, follow_up, etc.)
            - intent: str (direct_outreach, etc.)
            - elevator_pitch: Optional[str]
            - solution_summary: Optional[str]
            - cta: Optional[str]
            - message_language: Optional[str]
    
    Returns:
        {
            "success": bool,
            "message": str or None,
            "subject": str or None,
            "score": int or None,
            "error": str or None
        }
    """
    client = MessageGeneratorMCPClient()
    
    return await client.generate_outreach(
        target_prospect=step_context.get("target_prospect", "Unknown"),
        target_company=step_context.get("target_company", "Unknown Company"),
        company_name=step_context.get("company_name", "Unknown Company"),
        offer_name=step_context.get("offer_name", "Default Offer"),
        prospect_role=step_context.get("prospect_role"),
        channel=step_context.get("channel", "email"),
        stage=step_context.get("stage", "first_touch"),
        intent=step_context.get("intent", "direct_outreach"),
        elevator_pitch=step_context.get("elevator_pitch"),
        solution_summary=step_context.get("solution_summary"),
        cta=step_context.get("cta"),
        language=step_context.get("message_language"),
        research_signals=step_context.get("research_signals"),
        personality_config=step_context.get("personality_config"),
        user_notes=step_context.get("user_notes")
    )


# Synchronous wrapper for use in synchronous code
def generate_outreach_sync(
    target_prospect: str,
    target_company: str,
    company_name: str,
    offer_name: str,
    **kwargs
) -> Dict[str, Any]:
    """Synchronous wrapper for the async MCP client."""
    client = MessageGeneratorMCPClient()
    return asyncio.run(client.generate_outreach(
        target_prospect=target_prospect,
        target_company=target_company,
        company_name=company_name,
        offer_name=offer_name,
        **kwargs
    ))


def generate_message_for_step_sync(step_context: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous wrapper for generate_message_for_step that handles existing event loops."""
    try:
        # Check if there's already a running event loop
        loop = asyncio.get_running_loop()
        # Use nest_asyncio to allow nested event loops
        try:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(generate_message_for_step(step_context))
        except ImportError:
            # If nest_asyncio not available, try to run in a new thread
            import concurrent.futures
            import threading
            def run_in_new_loop():
                return asyncio.run(generate_message_for_step(step_context))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        return asyncio.run(generate_message_for_step(step_context))


async def generate_outreach_enriched_async(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Async wrapper that sends enriched JSON payload directly to message generator.

    Args:
        payload: Full enriched JSON with personality, company_details, selected_offer
    """
    import aiohttp
    import logging

    logger = logging.getLogger(__name__)

    rest_url = os.getenv("MESSAGE_GENERATOR_URL", "http://localhost:8000")
    prospect = payload.get("target_prospect", "Unknown")

    logger.debug(f"Sending to message generator: {prospect} at {rest_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{rest_url}/api/generate/simple",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                result = await response.json()
                logger.debug(f"Message generator response success: {result.get('success', 'N/A')}")
                if not result.get('success'):
                    logger.warning(f"Message generator error: {result.get('error', 'No error field')}")
                return result
    except Exception as e:
        logger.error(f"Message generator request failed: {str(e)[:200]}")
        return {
            "success": False,
            "error": str(e),
            "message": None,
            "subject": None,
            "score": None
        }


def generate_outreach_enriched_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronous wrapper that sends enriched JSON payload directly to message generator.

    Args:
        payload: Full enriched JSON with personality, company_details, selected_offer

    Example payload:
    {
        "target_prospect": "Sarah Chen",
        "target_company": "Ramp",
        "prospect_role": "VP of Sales",
        "channel": "linkedin_dm",
        "intent": "direct_outreach",
        "stage": "first_touch",
        "personality": {...},
        "company_details": {...},
        "selected_offer": {...}
    }
    """
    import requests
    import logging

    logger = logging.getLogger(__name__)

    rest_url = os.getenv("MESSAGE_GENERATOR_URL", "http://localhost:8000")

    try:
        logger.debug(f"Sending to message generator (sync) at {rest_url}")
        response = requests.post(
            f"{rest_url}/api/generate/simple",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code == 422:
            logger.warning(f"Message generator 422 error: {response.text[:300]}")
        response.raise_for_status()
        result = response.json()
        logger.debug(f"Message generator response success: {result.get('success', 'N/A')}")
        if not result.get('success'):
            logger.warning(f"Message generator error: {result.get('error', 'No error field')}")
        return result
    except Exception as e:
        logger.error(f"Message generator request failed: {str(e)[:200]}")
        return {
            "success": False,
            "error": str(e),
            "message": None,
            "subject": None,
            "score": None
        }

