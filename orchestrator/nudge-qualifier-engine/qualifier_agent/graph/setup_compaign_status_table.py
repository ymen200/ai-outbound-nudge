"""
setup_campaign_status_table.py
--------------------------------
One-time setup script: creates the campaigns status tracking table
in your hosted Postgres database.

This table is owned by your application — completely separate from
LangGraph's internal checkpoint tables. It gives the frontend a cheap,
simple way to check campaign lifecycle status without touching LangGraph.

Run this ONCE before using the campaign status system for the first time.
Safe to re-run — uses CREATE TABLE IF NOT EXISTS.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
    python setup_campaign_status_table.py
"""

import os
import psycopg


from dotenv import load_dotenv
load_dotenv()   


CREATE_CAMPAIGNS_TABLE = """
CREATE TABLE IF NOT EXISTS campaigns (
    -- Primary key: same value used as thread_id in LangGraph config.
    -- This is the bridge between your app's campaign record and
    -- LangGraph's internal checkpoint state.
    campaign_id         TEXT PRIMARY KEY,

    -- Who owns this campaign. Your app sets this on creation.
    user_id             TEXT NOT NULL,

    -- Lifecycle status. One of:
    --   running           — nodes 1-4 are actively executing
    --   ready_for_personas — paused after ranking; orchestrator fetches personas (auto-approve)
    --   resuming          — orchestrator resumed, node 5 is running
    --   completed         — full pipeline finished, ranked_personas available
    --   failed            — pipeline_error was set, inspect error_message
    status              TEXT NOT NULL DEFAULT 'running',

    -- The ranked company list from Node 4, stored as JSON so status polls
    -- can re-render without calling into LangGraph.
    -- Only populated when status = 'ready_for_personas'.
    -- Shape: [{apollo_id, name, domain, qualification_metrics,
    --           is_subsidiary, parent_company}, ...]
    ranked_companies    JSONB,

    -- Token usage summary (set_completed()).
    usage               JSONB,

    -- Human-readable error message if status = 'failed'.
    error_message       TEXT,

    -- ICP description text — useful for displaying campaign context in the UI.
    icp_description     TEXT,

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for the most common query pattern:
-- "show me all campaigns for this user, newest first"
CREATE INDEX IF NOT EXISTS idx_campaigns_user_id
    ON campaigns (user_id, created_at DESC);

-- Index for status-based queries:
-- "show me all campaigns currently ready for personas"
CREATE INDEX IF NOT EXISTS idx_campaigns_status
    ON campaigns (status);

-- --------------------------------------------------------------------------------
-- Additional campaign data tables (inputs, companies, personas, blacklist,
-- weights snapshot, token usage).
-- These tables make your pipeline auditable and allow downstream analytics.
-- --------------------------------------------------------------------------------

"""

CREATE_CAMPAIGN_INPUTS_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_inputs (
    id                       TEXT PRIMARY KEY,
    campaign_id              TEXT NOT NULL UNIQUE REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    raw_icp_text             TEXT NOT NULL,
    user_offering            TEXT NOT NULL,
    parsed_icp_json          JSONB NOT NULL,

    -- Hybrid: parsed fields stored separately for common filtering/reporting,
    -- while retaining the full JSON snapshot for debugging/replay.
    industries_json         JSONB NOT NULL DEFAULT '[]',
    target_countries_json   JSONB NOT NULL DEFAULT '[]',
    target_continents_json  JSONB NOT NULL DEFAULT '[]',
    target_roles_json       JSONB NOT NULL DEFAULT '[]',
    company_size_min        NUMERIC,
    company_size_max        NUMERIC,
    revenue_min             NUMERIC,
    revenue_max             NUMERIC,
    tech_stack_json         JSONB NOT NULL DEFAULT '[]',
    growth_stage            TEXT,
    funding_stage           TEXT,
    target_cities_json      JSONB NOT NULL DEFAULT '[]',

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


CREATE_CAMPAIGN_COMPANIES_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_companies (
    id                TEXT PRIMARY KEY,
    campaign_id       TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    apollo_company_id TEXT NOT NULL,
    company_name     TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, apollo_company_id)
);
"""


CREATE_CAMPAIGN_PERSONAS_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_personas (
    id               TEXT PRIMARY KEY,
    campaign_id      TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    apollo_persona_id TEXT NOT NULL,
    apollo_company_id TEXT,
    persona_name    TEXT,
    linkedin_url    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, apollo_persona_id)
);
"""


CREATE_BLACKLIST_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS blacklist_entries (
    id           TEXT PRIMARY KEY,
    campaign_id  TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    entry_type   TEXT NOT NULL, -- 'company' | 'persona'
    match_value  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, entry_type, match_value)
);
"""


CREATE_CAMPAIGN_WEIGHT_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_weight_snapshots (
    id            TEXT PRIMARY KEY,
    campaign_id   TEXT NOT NULL UNIQUE REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    weights_json  JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


CREATE_TOKEN_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS token_usage (
    id               TEXT PRIMARY KEY,
    campaign_id      TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    tool_name        TEXT NOT NULL,
    usage_json       JSONB NOT NULL,
    total_tokens     INTEGER NOT NULL,
    tokens_in        INTEGER NOT NULL,
    tokens_out       INTEGER NOT NULL,
    total_llm_calls  INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_token_usage_campaign
    ON token_usage (campaign_id, created_at ASC);
"""

# Automatically update updated_at on every row change
CREATE_UPDATED_AT_TRIGGER = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at ON campaigns;
CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set."
        )

    print("Connecting to Postgres...")
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            print("Creating campaigns table...")
            cur.execute(CREATE_CAMPAIGNS_TABLE)

            print("Creating updated_at trigger...")
            cur.execute(CREATE_UPDATED_AT_TRIGGER)

            # Lightweight migrations for already-created DBs.
            existing_columns = [
                r[0]
                for r in cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'campaigns'
                    """
                ).fetchall()
            ]
            if "usage" not in existing_columns:
                print("Migrating campaigns table: adding missing 'usage' column...")
                cur.execute("ALTER TABLE campaigns ADD COLUMN usage JSONB")

            print("Creating campaign_inputs / companies / personas tables...")
            cur.execute(CREATE_CAMPAIGN_INPUTS_TABLE)
            cur.execute(CREATE_CAMPAIGN_COMPANIES_TABLE)
            cur.execute(CREATE_CAMPAIGN_PERSONAS_TABLE)
            cur.execute(CREATE_BLACKLIST_ENTRIES_TABLE)
            cur.execute(CREATE_CAMPAIGN_WEIGHT_SNAPSHOTS_TABLE)
            cur.execute(CREATE_TOKEN_USAGE_TABLE)

        conn.commit()
        print("Done. campaigns and campaign data tables are ready.")


if __name__ == "__main__":
    main()