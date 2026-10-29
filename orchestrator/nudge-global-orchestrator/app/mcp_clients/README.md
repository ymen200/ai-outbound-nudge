# MCP Clients

The global orchestrator communicates with all downstream modules via **stdio MCP** (Model Context Protocol). Each module exposes an MCP server that is spawned as a subprocess; the orchestrator calls its tools over stdin/stdout.

---

## Architecture

```
McpStdioClient (base)
  ├── QualifierClient   → nudge-qualifier-engine (ICP extraction, ranking)
  ├── SourcerClient      → inject_collect_project (Apollo data fetching)
  └── OutreachClient     → Outreach-Project/outreach orchestrator (sequences + messages)
```

All three clients inherit the same resilience features from `McpStdioClient`:

1. **Timeout** — every tool call is wrapped in `asyncio.wait_for(timeout=...)`. If exceeded, a `TimeoutError` is raised.
2. **Retry + exponential backoff** — on any exception, the call is retried up to `max_retries` times with `delay = retry_backoff_base × 2^attempt`.
3. **Payload unwrapping** — FastMCP wraps tool results in nested dicts (`{"result": {...}}`, `{"content": [{"text": "..."}]}`). The `_parse_tool_result` + `_unwrap_mcp_payload` helpers normalize these into plain Python dicts.

---

## McpStdioClient

The base client. Spawns an MCP server as a subprocess and calls its tools.

### Constructor

```python
McpStdioClient(
    script_path: str,           # path to the MCP server script (REQUIRED)
    python_executable: str,     # Python to run it with (default: sys.executable)
    cwd: str,                   # working directory for the subprocess
    env: dict,                  # extra environment variables
    timeout: float = 120.0,     # max seconds per tool call
    max_retries: int = 0,       # retry attempts on failure (0 = no retry)
    retry_backoff_base: float = 2.0,  # base for exponential backoff
)
```

### How it works

1. Creates a `PythonStdioTransport` with the script path, python, cwd, and env.
2. For each `call_tool(name, arguments)`:
   - Opens an `async with Client(transport)` context (spawns the subprocess)
   - Calls `client.call_tool(name, arguments)` wrapped in `asyncio.wait_for`
   - Parses the result through `_parse_tool_result`
   - On exception: retries with exponential backoff if `max_retries > 0`
3. The subprocess is terminated when the `async with` context exits (`keep_alive=False`).

### Timeout behavior

When `asyncio.wait_for` times out:
1. The inner coroutine is cancelled
2. The `async with Client(...)` context manager cleans up the subprocess
3. `asyncio.TimeoutError` is caught and re-raised as `TimeoutError("MCP tool '{name}' on '{script}' timed out after {timeout}s")`
4. If `max_retries > 0`, the retry loop catches this and retries

### Retry behavior

The retry loop in `call_tool` catches **any `Exception`** (not just timeout/connection errors). This is intentional — fastmcp's `McpError: Connection closed` is not a subclass of `ConnectionError` or `OSError`, so a narrow catch would miss the most common real-world failure (subprocess crash). Non-transient errors (logic bugs) will simply fail again on retry and exhaust the budget quickly.

Backoff schedule: `delay = retry_backoff_base × 2^attempt`
- Attempt 0 fails → wait `base × 1` seconds → retry
- Attempt 1 fails → wait `base × 2` seconds → retry
- Attempt 2 fails → wait `base × 4` seconds → retry
- All attempts exhausted → raise the last exception

#### Edge case: negative `max_retries`

If `max_retries` is set to a negative value (e.g. `-1`), the retry loop's `range(max_retries + 1)` is empty, so no attempt is made and `last_exc` stays `None`. Rather than raising `TypeError: exceptions must derive from BaseException` (which is what `raise None` would produce), `call_tool` raises a clear **`RuntimeError`**:

```
RuntimeError: MCP tool '{name}' on '{script}' produced no result and no exception (max_retries=-1)
```

This makes misconfiguration immediately debuggable.

---

## QualifierClient

Wraps the **nudge-qualifier-engine** MCP server.

| Tool | Description |
|------|-------------|
| `start_campaign` | Extract ICP features from raw text |
| `resume_with_companies` | Rank companies by firmographic fit |
| `rescore_with_intent` | Re-rank with intent signals |
| `resume_with_approvals` | Rank personas for approved companies |

Config: `QUALIFIER_MCP_PATH`, `QUALIFIER_PYTHON` (see `.env.example`)

---

## SourcerClient

Wraps the **inject_collect_project** MCP server (Apollo data fetching).

| Tool | Description |
|------|-------------|
| `orchestrator_fetch_companies` | Fetch companies by industry/region/size |
| `orchestrator_fetch_intent` | Fetch intent signals for companies |
| `orchestrator_fetch_personas_with_signals` | Fetch personas + public signals |
| `orchestrator_enrich_contacts` | Enrich email/phone for personas |

Config: `SOURCER_MCP_PATH`, `SOURCER_PYTHON` (see `.env.example`)

---

## OutreachClient

Wraps the **Outreach-Project Outreach Orchestrator** MCP server.

### The `run_mcp.py` wrapper

The Outreach Orchestrator's `app/mcp_server.py` uses relative imports (`from .clients import ...`) and is designed to be run as `python -m app.mcp_server`. However, `McpStdioClient` runs scripts as bare files (`python script.py`), which breaks relative imports.

The solution is `Outreach-Project/outreach orchestrator/run_mcp.py` — a tiny wrapper:

```python
import asyncio
from app.mcp_server import main

if __name__ == "__main__":
    asyncio.run(main())
```

This imports `app.mcp_server` as a module (preserving package context) and runs its `main()`. The `OUTREACH_MCP_PATH` config must point to this wrapper, not to `app/mcp_server.py` directly.

### Tools

| Tool | Description |
|------|-------------|
| `run_outreach_pipeline` | Full sequence + message generation |
| `approve_pipeline` | Approve/reject a paused sequence |
| `get_outreach_status` | Health check + paused threads |
| `get_observability` | Aggregated metrics from both modules |

### Config

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTREACH_MCP_PATH` | `../../Outreach-Project/outreach orchestrator/run_mcp.py` | Wrapper script path |
| `OUTREACH_PYTHON` | (current python) | Python for the subprocess |
| `OUTREACH_TIMEOUT` | `120.0` | Max seconds per tool call |
| `OUTREACH_MAX_RETRIES` | `2` | Retry attempts |
| `OUTREACH_RETRY_BACKOFF_BASE` | `2.0` | Exponential backoff base |

### Guards

- **FileNotFoundError** — raised immediately if `OUTREACH_MCP_PATH` doesn't exist
- **Warning log** — emitted if the path doesn't end with `run_mcp.py` (likely misconfigured to the broken `app/mcp_server.py`)

### Payload mapping

`OutreachClient.start_outreach(payload)` expects a **flat dict** matching the `run_outreach_pipeline` MCP tool schema. The payload is built by `build_outreach_payload()` in `app/pipeline/outreach.py`, which flattens the nested `FinalLeadPackage` structure into:

- `lead_id`, `campaign_id`, `entreprise`
- `contact_full_name`, `contact_job_title`, `contact_email`, `contact_country`, `contact_city`, `contact_linkedin`
- `web_profil_brut`, `web_offer_context`, `web_icp_description`
- `research_signals`, `sender_company`, `offer_name`, `cta`, etc.

---

## Testing

Unit tests are in `tests/test_outreach_client.py`:

- **Path guard tests** — FileNotFoundError, run_mcp.py warning, valid construction
- **Tool delegation tests** — start_outreach, approve_pipeline, health, observability (uses injected `_FakeMcpClient`, no subprocess)
- **start_outreach_for_campaign tests** — success, failure, empty packages, unknown campaign, lead_id filtering
- **Timeout tests** — raises TimeoutError, default 120s, custom timeout, settings propagation
- **Retry tests** — retries on ConnectionError, retries on TimeoutError, no retry on success, gives up after max_retries, default 0 retries, settings propagation, negative max_retries raises RuntimeError
