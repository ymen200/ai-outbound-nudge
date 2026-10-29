# Store — Campaign Persistence

The `CampaignStore` class persists all campaign state. It is the **single interface** for database access in the orchestrator.

---

## Current Implementation: SQLite

The store currently uses Python's built-in `sqlite3` module. The database file path is configurable via `DATABASE_PATH` in `.env` (default: `./data/orchestrator.db`).

### Why SQLite?

SQLite was chosen for development speed — it requires no server setup and is zero-config. It works well for single-instance development and testing.

### Limitations

- **Database-level locking** — only one writer at a time. Under concurrent campaign creation, you may see `database is locked` errors.
- **No row-level locking** — concurrent reads are fine, but concurrent writes contend.
- **Single file** — no horizontal scaling, no network access.

### Schema

```
campaigns
  id              TEXT PRIMARY KEY
  user_id         TEXT NOT NULL
  status          TEXT NOT NULL          -- running | completed | failed
  stage           TEXT NOT NULL          -- see CampaignStage enum
  qualifier_campaign_id TEXT
  raw_icp         TEXT
  user_offering   TEXT
  icp_features_json   TEXT               -- JSON of extracted ICP features
  outreach_config_json TEXT              -- JSON of Phase B config
  error           TEXT
  created_at      TEXT NOT NULL
  updated_at      TEXT NOT NULL

artifacts
  id              TEXT PRIMARY KEY
  campaign_id     TEXT NOT NULL (FK)
  stage           TEXT NOT NULL
  payload_json    TEXT NOT NULL           -- JSON of raw MCP response
  created_at      TEXT NOT NULL

final_packages
  id              TEXT PRIMARY KEY
  campaign_id     TEXT NOT NULL (FK)
  lead_id         TEXT NOT NULL
  package_json    TEXT NOT NULL           -- JSON of FinalLeadPackage
  created_at      TEXT NOT NULL

outreach_threads
  id              TEXT PRIMARY KEY
  campaign_id     TEXT NOT NULL (FK)
  lead_id         TEXT NOT NULL
  thread_id       TEXT                    -- MCP thread ID (null on failure)
  status          TEXT NOT NULL           -- awaiting_approval | dispatched | failed | ...
  payload_json    TEXT NOT NULL           -- JSON of {request, response} or {error}
  created_at      TEXT NOT NULL
  updated_at      TEXT NOT NULL
```

### CampaignStage enum

All possible campaign stages (see [app/pipeline/README.md](../pipeline/README.md) for the full flow):

```
CREATED → ICP_EXTRACT → ICP_PERSISTED → FETCH_COMPANIES → RANK_COMPANIES
→ FETCH_INTENT → RESCORE_INTENT → FETCH_PERSONAS → RANK_PERSONAS
→ ENRICH_CONTACTS → PACKAGE_READY
→ OUTREACH_STARTED → OUTREACH_AWAITING_APPROVAL → OUTREACH_APPROVED
→ OUTREACH_DISPATCHED | OUTREACH_FAILED | FAILED
```

### API

| Method | Description |
|--------|-------------|
| `create_campaign(user_id, raw_icp, user_offering, outreach_config)` | Create a new campaign, returns UUID |
| `update_stage(campaign_id, stage, **kwargs)` | Update stage + optional fields |
| `save_artifact(campaign_id, stage, payload)` | Save raw MCP response |
| `save_final_packages(campaign_id, packages)` | Store FinalLeadPackages |
| `get_campaign(campaign_id)` | Get campaign dict (with parsed JSON fields) |
| `list_artifacts(campaign_id)` | List all artifacts for a campaign |
| `list_packages(campaign_id)` | List all lead packages |
| `save_outreach_thread(campaign_id, lead_id, thread_id, status, payload)` | Save outreach thread record |
| `list_outreach_threads(campaign_id)` | List outreach threads |
| `update_outreach_thread_status(thread_db_id, status, payload)` | Update thread status |

---

## Planned Migration: PostgreSQL + DBeaver

**Status: separate ticket (not yet implemented)**

The plan is to migrate from SQLite to **PostgreSQL**, managed via **DBeaver**.

### Migration approach

The `CampaignStore` class is the single database interface. To migrate:

1. Replace `sqlite3` with `psycopg` (or `asyncpg`) in `CampaignStore`
2. Update the SQL syntax (SQLite-specific → PostgreSQL)
3. Add connection pooling (PostgreSQL supports concurrent writers)
4. Add a `DATABASE_URL` config variable (e.g. `postgresql://user:pass@localhost:5432/addvocate`)
5. Keep the same method signatures so the rest of the app doesn't change

### What won't change

- The `CampaignStore` API (method names and signatures)
- The schema structure (tables, columns)
- The `CampaignStage` enum
- The JSON serialization approach for complex fields

### What will change

- Connection management (single `sqlite3.connect` → connection pool)
- SQL dialect (`?` placeholders → `%s` or named)
- Concurrent write handling (SQLite locking → PostgreSQL MVCC)
- Database file path → connection URL
