# API Endpoints

The global orchestrator exposes a FastAPI app on port 8100.

---

## Campaign Management (Phase A)

### `POST /campaigns`

Start a new campaign. Runs Phase A (lead discovery) either synchronously or in the background.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `user_id` | string | ✓ | — | Owner of the campaign |
| `icp_description_text` | string | — | env `ICP_DESCRIPTION_TEXT` | Raw ICP brief |
| `user_offering` | string | — | env `USER_OFFERING` | Product/offering description |
| `blacklist` | object | — | env defaults | `{companies: [], personas: []}` |
| `configurable_weights` | object | — | env defaults | Scoring weight overrides |
| `company_limit` | int | — | env `COMPANY_LIMIT` | Sourcer company fetch limit |
| `run_async` | bool | — | `true` | If true, return immediately and run Phase A in background |
| `auto_start_outreach` | bool | — | `false` | Auto-start Phase B when Phase A completes |
| `sender_company` | string | — | env | Sender company name |
| `offer_name` | string | — | env | Offer name |
| `solution_summary` | string | — | env / `user_offering` | Solution description |
| `cta` | string | — | env | Call-to-action text |
| `approval_mode` | string | — | `per_sequence` | per_sequence / per_step / per_step_and_message |
| `use_native_language` | bool | — | `false` | Generate in prospect's language |
| `message_language` | string | — | `null` | ISO 639-1 override (e.g. "fr") |
| `has_inmail_credits` | bool | — | `false` | LinkedIn InMail credits available |
| `debug_mode` | bool | — | `true` | Bypass memory in outreach modules |

**Response (sync):**
```json
{
  "campaign_id": "uuid",
  "status": "completed",
  "stage": "package_ready",
  "message": "Phase A completed with 1 packages."
}
```

**Response (async):**
```json
{
  "campaign_id": "uuid",
  "status": "running",
  "stage": "created",
  "message": "Phase A started in background. Poll GET /campaigns/{id}."
}
```

---

### `GET /campaigns/{id}`

Get full campaign state including artifacts, lead packages, and outreach threads.

**Response:**
```json
{
  "campaign": {
    "id": "uuid",
    "user_id": "u1",
    "status": "completed",
    "stage": "package_ready",
    "raw_icp": "...",
    "user_offering": "...",
    "outreach_config": {...}
  },
  "artifacts": [...],
  "packages": [
    {
      "lead_id": "camp:persona-1",
      "campaign_id": "camp",
      "company": {...},
      "persona": {...},
      "icp": {...}
    }
  ],
  "outreach_threads": [...]
}
```

---

## Outreach Management (Phase B)

### `POST /campaigns/{id}/outreach`

Start Phase B outreach for a campaign's lead packages. Runs in the background.

**Query params:**
- `lead_ids` (optional) — comma-separated list of specific lead IDs to process

**Response:**
```json
{
  "campaign_id": "uuid",
  "status": "accepted",
  "message": "Outreach started in background"
}
```

---

### `GET /campaigns/{id}/outreach`

List outreach threads for a campaign.

**Response:**
```json
{
  "campaign_id": "uuid",
  "threads": [
    {
      "id": "db-uuid",
      "lead_id": "camp:persona-1",
      "thread_id": "api_thread_abc123",
      "status": "awaiting_approval",
      "payload": {"request": {...}, "response": {...}}
    }
  ]
}
```

Thread statuses: `awaiting_approval`, `dispatched`, `approved`, `rejected`, `failed`, `unknown`

---

### `POST /campaigns/{id}/outreach/{thread_id}/approve`

Approve or reject a paused outreach sequence. Forwards to the Outreach Orchestrator's `approve_pipeline` MCP tool.

**Request body:**
```json
{
  "approved": true,
  "feedback": null
}
```

When `approved=true`: dispatches the sequence to Temporal.
When `approved=false` with `feedback`: regenerates the sequence with the feedback injected.

**Response:** The raw Outreach Orchestrator response (typically `{"status": "dispatched", "thread_id": "..."}`)

---

### `GET /campaigns/{id}/outreach/observability`

Aggregated observability metrics from the Outreach Orchestrator's downstream modules (Sequence Generator + Message Generator).

**Response:**
```json
{
  "modules": {
    "sequence_generator": {"total_tokens": 1234, "total_gemini_calls": 5, ...},
    "message_generator": {"total_tokens": 5678, "total_llm_calls": 10, ...}
  }
}
```

---

## Health

### `GET /health`
```json
{"status": "ok", "mock": false}
```

### `GET /`
```json
{
  "service": "nudge-global-orchestrator",
  "version": "1.0.0",
  "phase": "A",
  "mock": false
}
```

---

## Error Handling

All endpoints return standard HTTP error codes:

| Code | When |
|------|------|
| 404 | Campaign not found, no lead packages, no outreach threads |
| 500 | MCP tool call failed, timeout, or internal error |

Error responses include a `detail` field with the error message.
