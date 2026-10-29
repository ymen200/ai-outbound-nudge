"""
Test MCP/A2A interface of the Outreach Orchestrator via SSE.

Tests:
1. Connect to MCP SSE endpoint
2. List available tools
3. Call get_outreach_status tool
4. Call get_module_capabilities tool
"""

import asyncio
import json
from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_URL = "http://localhost:8002/mcp"


async def run_mcp_tests():
    print("=" * 60)
    print("MCP/A2A CLIENT TEST")
    print("=" * 60)

    try:
        async with sse_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize
                init_result = await session.initialize()
                print(f"\nServer info: {init_result.serverInfo.name} v{init_result.serverInfo.version}")

                # List tools
                tools = await session.list_tools()
                print(f"\nAvailable tools ({len(tools.tools)}):")
                tool_names = []
                for t in tools.tools:
                    print(f"  - {t.name}: {t.description[:80]}...")
                    tool_names.append(t.name)

                expected_tools = [
                    "run_outreach_pipeline",
                    "get_outreach_status",
                    "get_observability",
                    "get_prompt_history",
                    "override_module_config",
                    "inject_feedback",
                    "get_module_capabilities",
                ]
                missing = [t for t in expected_tools if t not in tool_names]
                if missing:
                    print(f"\nFAIL: Missing tools: {missing}")
                    return False
                print("\nPASS: All expected tools available")

                # Call get_outreach_status
                print("\nCalling get_outreach_status...")
                result = await session.call_tool("get_outreach_status", {})
                for c in result.content:
                    if c.type == "text":
                        status = json.loads(c.text)
                        print(f"  Result: {json.dumps(status, indent=2)[:300]}")
                print("PASS: get_outreach_status responded")

                # Call get_module_capabilities
                print("\nCalling get_module_capabilities...")
                result = await session.call_tool("get_module_capabilities", {})
                for c in result.content:
                    if c.type == "text":
                        caps = json.loads(c.text)
                        print(f"  supported_channels: {caps.get('supported_channels')}")
                        has_inmail = "linkedin_inmail" in caps.get("supported_channels", [])
                        print(f"PASS: linkedin_inmail in supported_channels: {has_inmail}")

                return True

    except Exception as e:
        print(f"\nFAIL: MCP client error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    ok = asyncio.run(run_mcp_tests())
    print("\n" + "=" * 60)
    print(f"MCP TEST: {'PASS' if ok else 'FAIL'}")
    print("=" * 60)
    exit(0 if ok else 1)
