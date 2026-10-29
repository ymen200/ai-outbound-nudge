# Pipeline

The pipeline module contains the two-phase orchestration logic.

---

## Phase A — Lead Discovery (`__init__.py`)

The `PhaseAPipeline` class orchestrates lead discovery by alternating between the **Qualifier** (scoring/ranking) and **Sourcer** (data fetching) MCP servers.

### Stage machine

```
ICP_EXTRACT → ICP_PERSISTED → FETCH_COMPANIES → RANK_COMPANIES
    → FETCH_INTENT → RESCORE_INTENT → FETCH_PERSONAS → RANK_PERSONAS
    → ENRICH_CONTACTS → PACKAGE_READY
```

Each stage:
1. Calls the appropriate MCP tool (Qualifier or Sourcer)
2. Saves the raw response as an artifact in the DB
3. Updates the campaign stage
4. Logs progress with the campaign ID

### Detailed flow

| Step | Stage | MCP client | Tool | What happens |
|------|-------|------------|------|--------------|
| 1 | `ICP_EXTRACT` | Qualifier | `start_campaign` | Extract ICP features (industries, size, location, roles) from raw text |
| 2 | `ICP_PERSISTED` | — | — | Save raw ICP text + extracted features to DB |
| 3 | `FETCH_COMPANIES` | Sourcer | `orchestrator_fetch_companies` | Fetch companies matching ICP from Apollo |
| 4 | `RANK_COMPANIES` | Qualifier | `resume_with_companies` | Score companies by firmographic fit (industry, size, revenue, tech) |
| 5 | `FETCH_INTENT` | Sourcer | `orchestrator_fetch_intent` | Fetch intent signals (job offers, news) for top companies |
| 6 | `RESCORE_INTENT` | Qualifier | `rescore_with_intent` | Re-rank companies with intent signals included |
| 7 | `FETCH_PERSONAS` | Sourcer | `orchestrator_fetch_personas_with_signals` | Fetch personas + public signals for top companies |
| 8 | `RANK_PERSONAS` | Qualifier | `resume_with_approvals` | Rank personas by fit, reachability, authority |
| 9 | `ENRICH_CONTACTS` | Sourcer | `orchestrator_enrich_contacts` | Enrich email/phone for the single best lead |
| 10 | `PACKAGE_READY` | — | — | Structure `FinalLeadPackage[]` and save to DB |

### Lead selection

After persona ranking, the pipeline picks a **single best lead** using:
```
combined_score = (company_total_score × lead_company_score_weight)
               + (persona_score × lead_persona_score_weight)
```
Default weights: company=0.4, persona=0.6. Configurable via `LEAD_COMPANY_SCORE_WEIGHT` and `LEAD_PERSONA_SCORE_WEIGHT` in `.env`.

### Mock mode

When `ORCHESTRATOR_MOCK=true`, Phase A skips all live MCP calls and uses `mock_data.py` to generate a fake lead package. This is useful for testing Phase B without the qualifier/sourcer infrastructure.

### Auto-start Phase B

When `auto_start_outreach=True` (or `OUTREACH_AUTO_START=true` in `.env`), Phase A automatically calls `start_outreach_for_campaign()` as soon as the `FinalLeadPackage` is ready. Otherwise, the caller must manually POST to `/campaigns/{id}/outreach`.

### Error handling

If any stage fails, the pipeline:
1. Logs the exception with the campaign ID
2. Writes the usage report (token/cost tracking)
3. Sets the campaign stage to `FAILED` with the error message
4. Saves an error artifact
5. Re-raises the exception

---

## Phase B — Outreach Handoff (`outreach.py`)

### `build_outreach_payload(pkg, campaign, overrides)`

Maps a `FinalLeadPackage` + campaign config to the **flat MCP tool schema** expected by `run_outreach_pipeline`.

The payload is flat (not nested) because the MCP tool's `inputSchema` defines all fields at the top level:
- `lead_id`, `campaign_id`, `entreprise`
- `contact_full_name`, `contact_job_title`, `contact_email`, `contact_country`, `contact_city`, `contact_linkedin`
- `web_profil_brut` (coerced to string via `str()`, truncated to 2000 chars — handles dict/list/None signals)
- `web_offer_context`, `web_icp_description`
- `research_signals` (normalized from persona + company intent signals)
- `sender_company`, `offer_name`, `solution_summary`, `cta`
- `approval_mode`, `use_native_language`, `message_language` (only included when not None)
- `debug_mode`, `has_inmail_credits`, `is_connected_on_linkedin`

#### Config resolution hierarchy

Three-tier resolution for each config value:
1. **Overrides** (passed explicitly to `build_outreach_payload`)
2. **Campaign outreach_config** (stored when the campaign was created)
3. **Environment defaults** (from `.env` / `Settings`)

Helper functions:
- `_resolve_str(key, overrides, config, default)` — string fields (empty falls through)
- `_resolve_bool(key, overrides, config, default)` — boolean fields (respects explicit `False`)
- `_resolve_optional(key, overrides, config, default)` — may return `None`

### `normalize_research_signals(pkg)`

Converts persona + company signals into the `research_signals` list format expected by the Outreach Orchestrator.

Handles multiple `signals` types:
- **String** → single `persona_signal`
- **Dict** → one signal per key (`persona_{key}`)
- **List of strings** → multiple `persona_signal` entries
- **List of dicts** → uses `type`/`content`/`why_relevant` from each dict
- **None/empty** → skipped

Also extracts company intent signals:
- `job_offers` → `job_offer` signals
- `news` → `news` signals
- `intent_summary` → `company_intent` signal

### `start_outreach_for_campaign(campaign_id, lead_ids, overrides)`

The main Phase B entry point. For each lead package in the campaign:

1. Builds the flat MCP payload
2. Calls `OutreachClient.start_outreach(payload)` via stdio MCP
3. Saves the response (thread_id, status) to the DB
4. Updates the campaign stage based on status:
   - `awaiting_approval` → `OUTREACH_AWAITING_APPROVAL`
   - `completed` → `OUTREACH_DISPATCHED`
   - other → `OUTREACH_STARTED`
5. On exception: saves a `failed` thread record with the error message, sets stage to `OUTREACH_FAILED`

### Error handling

Each lead is processed independently — if one fails, the others still proceed. Failed leads get a thread record with `status="failed"` and the error message in the payload, so operators can see what went wrong and retry.

---

## Campaign Stages

Defined in `app/store/__init__.py` as `CampaignStage` enum:

| Stage | Phase | Description |
|-------|-------|-------------|
| `CREATED` | A | Campaign created, Phase A not started |
| `ICP_EXTRACT` | A | Extracting ICP features |
| `ICP_PERSISTED` | A | ICP saved to DB |
| `FETCH_COMPANIES` | A | Fetching companies from Apollo |
| `RANK_COMPANIES` | A | Firmographic ranking |
| `FETCH_INTENT` | A | Fetching intent signals |
| `RESCORE_INTENT` | A | Re-ranking with intent |
| `FETCH_PERSONAS` | A | Fetching personas |
| `RANK_PERSONAS` | A | Ranking personas |
| `ENRICH_CONTACTS` | A | Email/phone enrichment |
| `PACKAGE_READY` | A | FinalLeadPackage assembled |
| `OUTREACH_STARTED` | B | Outreach initiated |
| `OUTREACH_AWAITING_APPROVAL` | B | Sequence paused for human review |
| `OUTREACH_APPROVED` | B | Sequence approved |
| `OUTREACH_DISPATCHED` | B | Dispatched to Temporal |
| `OUTREACH_FAILED` | B | Outreach failed |
| `FAILED` | A/B | Pipeline error |
