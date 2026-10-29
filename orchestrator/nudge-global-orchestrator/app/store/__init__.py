from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings


class CampaignStage(str, Enum):
    CREATED = "created"
    ICP_EXTRACT = "icp_extract"
    ICP_PERSISTED = "icp_persisted"
    FETCH_COMPANIES = "fetch_companies"
    RANK_COMPANIES = "rank_companies"
    FETCH_INTENT = "fetch_intent"
    RESCORE_INTENT = "rescore_intent"
    FETCH_PERSONAS = "fetch_personas"
    RANK_PERSONAS = "rank_personas"
    ENRICH_CONTACTS = "enrich_contacts"
    PACKAGE_READY = "package_ready"
    OUTREACH_STARTED = "outreach_started"
    OUTREACH_AWAITING_APPROVAL = "outreach_awaiting_approval"
    OUTREACH_APPROVED = "outreach_approved"
    OUTREACH_DISPATCHED = "outreach_dispatched"
    OUTREACH_FAILED = "outreach_failed"
    FAILED = "failed"


_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        qualifier_campaign_id TEXT,
        raw_icp TEXT,
        user_offering TEXT,
        icp_features_json TEXT,
        outreach_config_json TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS final_packages (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        lead_id TEXT NOT NULL,
        package_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outreach_threads (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        lead_id TEXT NOT NULL,
        thread_id TEXT,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS campaign_companies (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        apollo_company_id TEXT NOT NULL,
        company_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'approved',
        created_at TEXT NOT NULL,
        UNIQUE(campaign_id, apollo_company_id),
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS campaign_personas (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        apollo_persona_id TEXT NOT NULL,
        apollo_company_id TEXT,
        persona_name TEXT,
        linkedin_url TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(campaign_id, apollo_persona_id),
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blacklist_entries (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        entry_type TEXT NOT NULL,
        match_value TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, entry_type, match_value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS campaign_weights (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE,
        max_km_radius DOUBLE PRECISION,
        industry_weight DOUBLE PRECISION,
        size_weight DOUBLE PRECISION,
        revenue_weight DOUBLE PRECISION,
        tech_stack_weight DOUBLE PRECISION,
        firmographic_weight DOUBLE PRECISION,
        intent_weight DOUBLE PRECISION,
        primary_role_match DOUBLE PRECISION,
        startup_fallback_match DOUBLE PRECISION,
        partial_title_match DOUBLE PRECISION,
        engagement_weight DOUBLE PRECISION,
        verified_email_bonus DOUBLE PRECISION,
        risky_email_bonus DOUBLE PRECISION,
        fit_weight DOUBLE PRECISION,
        reachability_weight DOUBLE PRECISION,
        timing_weight DOUBLE PRECISION,
        functional_weight DOUBLE PRECISION,
        authority_weight DOUBLE PRECISION,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        usage_json TEXT NOT NULL,
        total_tokens INTEGER NOT NULL,
        tokens_in INTEGER NOT NULL,
        tokens_out INTEGER NOT NULL,
        total_llm_calls INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outreach_sequence_steps (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        thread_id TEXT,
        workflow_id TEXT,
        step_num INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        channel TEXT NOT NULL,
        message_text TEXT,
        subject TEXT,
        ai_write INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        quality_score INTEGER,
        error TEXT,
        sent_at TEXT,
        wait_delay_seconds INTEGER NOT NULL DEFAULT 0,
        day_offset INTEGER NOT NULL DEFAULT 0,
        time_of_day TEXT NOT NULL DEFAULT '10h',
        strategy_notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_campaign_inputs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE,
        icp_description_text TEXT,
        user_offering TEXT,
        parsed_icp_json TEXT,
        industries_json TEXT,
        target_countries_json TEXT,
        target_continents_json TEXT,
        target_roles_json TEXT,
        company_size_min DOUBLE PRECISION,
        company_size_max DOUBLE PRECISION,
        revenue_min DOUBLE PRECISION,
        revenue_max DOUBLE PRECISION,
        tech_stack_json TEXT,
        growth_stage TEXT,
        funding_stage TEXT,
        target_cities_json TEXT,
        company_limit INTEGER,
        run_async INTEGER NOT NULL DEFAULT 1,
        auto_start_outreach INTEGER NOT NULL DEFAULT 0,
        sender_company TEXT,
        sender_elevator_pitch TEXT,
        offer_name TEXT,
        solution_summary TEXT,
        cta TEXT,
        approval_mode TEXT,
        use_native_language INTEGER,
        message_language TEXT,
        has_inmail_credits INTEGER,
        debug_mode INTEGER,
        max_touches INTEGER,
        max_days INTEGER,
        preferred_first_channel TEXT,
        sequence_options_json TEXT,
        stage_instructions_json TEXT,
        personality_config_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # [11] msg_gen_memory — Message Generator prospect/learning/offer memory (hub-and-spoke persistence)
    """
    CREATE TABLE IF NOT EXISTS msg_gen_memory (
        key TEXT PRIMARY KEY,
        value JSONB NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]

# ICP sub-attributes formerly on campaign_inputs (raw text stays in icp_description_text)
_ICP_ATTR_COLUMNS: List[str] = [
    "parsed_icp_json",
    "industries_json",
    "target_countries_json",
    "target_continents_json",
    "target_roles_json",
    "company_size_min",
    "company_size_max",
    "revenue_min",
    "revenue_max",
    "tech_stack_json",
    "growth_stage",
    "funding_stage",
    "target_cities_json",
]

# Columnar weight attributes (no JSON blob) — mirrors settings.default_configurable_weights()
WEIGHT_COLUMNS: List[str] = [
    "max_km_radius",
    "industry_weight",
    "size_weight",
    "revenue_weight",
    "tech_stack_weight",
    "firmographic_weight",
    "intent_weight",
    "primary_role_match",
    "startup_fallback_match",
    "partial_title_match",
    "engagement_weight",
    "verified_email_bonus",
    "risky_email_bonus",
    "fit_weight",
    "reachability_weight",
    "timing_weight",
    "functional_weight",
    "authority_weight",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


class CampaignStore:
    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None):
        if db_path is not None:
            self._backend = "sqlite"
            self.db_path = db_path
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._backend = "postgres"
            self.database_url = database_url or settings.resolved_database_url()
        self._init_schema()

    @property
    def uses_postgres(self) -> bool:
        return self._backend == "postgres"

    @contextmanager
    def _conn(self):
        if self._backend == "sqlite":
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield _SqliteCursor(conn)
                conn.commit()
            finally:
                conn.close()
        else:
            from app.store.connection import postgres_session

            with postgres_session() as cursor:
                yield cursor

    def _init_schema(self) -> None:
        with self._conn() as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._migrate(conn)

    def _table_names(self, conn) -> List[str]:
        if self._backend == "sqlite":
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row[0] if not isinstance(row, dict) else row["name"] for row in rows]
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        ).fetchall()
        return [row["table_name"] for row in rows]

    def _column_names(self, conn, table: str) -> List[str]:
        if self._backend == "sqlite":
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return [row[1] if not isinstance(row, dict) else row["name"] for row in rows]
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            ORDER BY ordinal_position
            """,
            (table,),
        ).fetchall()
        return [row["column_name"] for row in rows]

    def _migrate(self, conn) -> None:
        columns = self._column_names(conn, "campaigns")
        if "outreach_config_json" not in columns:
            conn.execute("ALTER TABLE campaigns ADD COLUMN outreach_config_json TEXT")

        tables = self._table_names(conn)
        # Schema indices: 3 outreach, 4 companies, 5 personas, 6 blacklist,
        # 7 weights, 8 token_usage, 9 outreach_sequence_steps, 10 user_campaign_inputs
        if "outreach_threads" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[3])
        else:
            # Ensure payload_json column exists (Postgres migrations sometimes omit it).
            cols = self._column_names(conn, "outreach_threads")
            if "payload_json" not in cols:
                if self._backend == "sqlite":
                    # SQLite schema expects TEXT
                    conn.execute("ALTER TABLE outreach_threads ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}' ")
                else:
                    # Prefer JSONB for Postgres; add safely and backfill if needed
                    try:
                        conn.execute("ALTER TABLE outreach_threads ADD COLUMN payload_json JSONB NOT NULL DEFAULT '{}'::jsonb")
                    except Exception:
                        conn.execute("ALTER TABLE outreach_threads ADD COLUMN payload_json JSONB")
                        try:
                            conn.execute("UPDATE outreach_threads SET payload_json = '{}' WHERE payload_json IS NULL")
                        except Exception:
                            pass
                        try:
                            conn.execute("ALTER TABLE outreach_threads ALTER COLUMN payload_json SET NOT NULL")
                        except Exception:
                            pass
        if "campaign_companies" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[4])
        if "campaign_personas" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[5])
        if "token_usage" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[8])
        if "outreach_sequence_steps" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[9])

        # Add day_offset / time_of_day / strategy_notes columns (Phase B: full StepState persistence)
        if "outreach_sequence_steps" in self._table_names(conn):
            steps_cols = self._column_names(conn, "outreach_sequence_steps")
            if "day_offset" not in steps_cols:
                conn.execute("ALTER TABLE outreach_sequence_steps ADD COLUMN day_offset INTEGER NOT NULL DEFAULT 0")
            if "time_of_day" not in steps_cols:
                conn.execute("ALTER TABLE outreach_sequence_steps ADD COLUMN time_of_day TEXT NOT NULL DEFAULT '10h'")
            if "strategy_notes" not in steps_cols:
                conn.execute("ALTER TABLE outreach_sequence_steps ADD COLUMN strategy_notes TEXT NOT NULL DEFAULT ''")

        # ── Phase B indexes (CREATE IF NOT EXISTS via try/except — SQLite compat) ──
        _indexes = [
            "CREATE INDEX IF NOT EXISTS idx_outreach_threads_campaign ON outreach_threads(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_outreach_steps_campaign_wf ON outreach_sequence_steps(campaign_id, workflow_id)",
            "CREATE INDEX IF NOT EXISTS idx_artifacts_campaign ON artifacts(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_final_packages_campaign ON final_packages(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_token_usage_campaign ON token_usage(campaign_id)",
        ]
        for idx_sql in _indexes:
            try:
                conn.execute(idx_sql)
            except Exception:
                pass  # index already exists or unsupported syntax

        self._migrate_campaign_companies_status(conn)

        # Rebuild user-scoped draft tables when still on the old campaign_id shape.
        self._migrate_user_scoped_table(
            conn, "blacklist_entries", "user_id", _SCHEMA_STATEMENTS[6]
        )
        self._migrate_weight_snapshots(conn)
        self._migrate_user_campaign_inputs(conn)
        self._migrate_drop_campaign_inputs(conn)

        # Obsolete JSON-only params table — fold into user_campaign_inputs then drop.
        if "user_campaign_params" in self._table_names(conn):
            conn.execute("DROP TABLE user_campaign_params")

        # msg_gen_memory (hub-and-spoke: msg gen forwards memory writes here)
        if "msg_gen_memory" not in tables:
            conn.execute(_SCHEMA_STATEMENTS[11])

    def _migrate_campaign_companies_status(self, conn: Any) -> None:
        if "campaign_companies" not in self._table_names(conn):
            return
        cols = self._column_names(conn, "campaign_companies")
        if "status" not in cols:
            conn.execute(
                "ALTER TABLE campaign_companies "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'"
            )
            conn.execute(
                "UPDATE campaign_companies SET status = 'approved' "
                "WHERE status IS NULL OR TRIM(status) = ''"
            )

    def _migrate_user_scoped_table(
        self, conn: Any, table: str, required_col: str, create_sql: str
    ) -> None:
        tables = self._table_names(conn)
        if table not in tables:
            conn.execute(create_sql)
            return
        cols = self._column_names(conn, table)
        if required_col not in cols or "campaign_id" in cols:
            conn.execute(f"DROP TABLE {table}")
            conn.execute(create_sql)

    def _migrate_weight_snapshots(self, conn: Any) -> None:
        tables = self._table_names(conn)
        create_sql = _SCHEMA_STATEMENTS[7]
        has_old = "campaign_weight_snapshots" in tables
        has_new = "campaign_weights" in tables
        print(f"[MIGRATE] campaign_weight_snapshots exists: {has_old}, campaign_weights exists: {has_new}")
        # Migrate legacy table name if it still exists.
        if has_old:
            if has_new:
                # Both exist: copy data from old into new, then drop old.
                print("[MIGRATE] Both tables exist — copying data and dropping old table")
                self._copy_weight_snapshots_to_weights(conn)
                conn.execute("DROP TABLE campaign_weight_snapshots")
            else:
                print("[MIGRATE] Renaming campaign_weight_snapshots → campaign_weights")
                conn.execute("ALTER TABLE campaign_weight_snapshots RENAME TO campaign_weights")
            tables = self._table_names(conn)
        if "campaign_weights" not in tables:
            conn.execute(create_sql)
            return
        cols = self._column_names(conn, "campaign_weights")
        needs_rebuild = (
            "user_id" not in cols
            or "campaign_id" in cols
            or "weights_json" in cols
            or "industry_weight" not in cols
        )
        if needs_rebuild:
            conn.execute("DROP TABLE campaign_weights")
            conn.execute(create_sql)

    def _copy_weight_snapshots_to_weights(self, conn: Any) -> None:
        """Migrate legacy ``campaign_weight_snapshots`` rows into ``campaign_weights``.

        Legacy rows are campaign-scoped and store the weights as a ``weights_json``
        blob; the new table is user-scoped with one column per weight. The
        campaign -> user mapping comes from the ``campaigns`` table. Best-effort:
        rows without a matching campaign or with unparseable JSON are skipped.

        (A plain ``INSERT ... SELECT * ... ON CONFLICT DO NOTHING`` is invalid in
        SQLite — ``ON CONFLICT`` only works with VALUES inserts — and the column
        shapes differ anyway, so the copy is done row-by-row in Python.)
        """
        try:
            rows = conn.execute(
                "SELECT id, campaign_id, weights_json FROM campaign_weight_snapshots"
            ).fetchall()
        except Exception:
            print("[MIGRATE] Failed to read campaign_weight_snapshots rows — skipping copy")
            return
        for row in rows:
            data = _row_to_dict(row)
            campaign_id = data.get("campaign_id")
            if not campaign_id:
                continue
            campaign = conn.execute(
                "SELECT user_id FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if not campaign:
                continue
            user_id = _row_to_dict(campaign)["user_id"]
            try:
                blob = json.loads(data["weights_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(blob, dict):
                self._upsert_campaign_weights_conn(conn, user_id, blob)

    def _migrate_user_campaign_inputs(self, conn: Any) -> None:
        tables = self._table_names(conn)
        create_sql = _SCHEMA_STATEMENTS[10]
        if "user_campaign_inputs" not in tables:
            conn.execute(create_sql)
            return
        cols = self._column_names(conn, "user_campaign_inputs")
        _NEW_OUTREACH_COLS = [
            ("max_touches", "INTEGER"),
            ("max_days", "INTEGER"),
            ("preferred_first_channel", "TEXT"),
            ("sequence_options_json", "TEXT"),
            ("stage_instructions_json", "TEXT"),
            ("personality_config_json", "TEXT"),
        ]
        needs_rebuild = (
            "blacklist_json" in cols
            or "configurable_weights_json" in cols
        )
        if needs_rebuild:
            conn.execute("DROP TABLE user_campaign_inputs")
            conn.execute(create_sql)
            return
        # Add ICP sub-attribute columns folded in from obsolete campaign_inputs.
        for col in _ICP_ATTR_COLUMNS:
            if col not in cols:
                if col.endswith("_min") or col.endswith("_max"):
                    conn.execute(
                        f"ALTER TABLE user_campaign_inputs ADD COLUMN {col} DOUBLE PRECISION"
                    )
                else:
                    conn.execute(f"ALTER TABLE user_campaign_inputs ADD COLUMN {col} TEXT")
        # Add new AI/outreach columns.
        for col_name, col_type in _NEW_OUTREACH_COLS:
            if col_name not in cols:
                conn.execute(
                    f"ALTER TABLE user_campaign_inputs ADD COLUMN {col_name} {col_type}"
                )
        # Backfill new AI/outreach columns from params_json if it still exists.
        if "params_json" in cols:
            self._migrate_backfill_params_json_to_columns(conn)
            # Drop params_json — Postgres supports DROP COLUMN; SQLite handled below.
            if self._backend != "sqlite":
                conn.execute("ALTER TABLE user_campaign_inputs DROP COLUMN params_json")
            else:
                # SQLite: rebuild table without params_json, preserving all other columns.
                self._migrate_sqlite_drop_params_json(conn, create_sql)

    def _migrate_backfill_params_json_to_columns(self, conn: Any) -> None:
        """Extract AI/outreach fields from params_json into dedicated columns."""
        rows = conn.execute(
            "SELECT id, params_json FROM user_campaign_inputs WHERE params_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            data = _row_to_dict(row)
            row_id = data["id"]
            try:
                blob = json.loads(data["params_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(blob, dict):
                continue
            conn.execute(
                """
                UPDATE user_campaign_inputs SET
                    max_touches = ?,
                    max_days = ?,
                    preferred_first_channel = ?,
                    sequence_options_json = ?,
                    stage_instructions_json = ?,
                    personality_config_json = ?
                WHERE id = ?
                """,
                (
                    blob.get("max_touches"),
                    blob.get("max_days"),
                    blob.get("preferred_first_channel"),
                    json.dumps(blob.get("sequence_options")) if blob.get("sequence_options") is not None else None,
                    json.dumps(blob.get("stage_instructions")) if blob.get("stage_instructions") is not None else None,
                    json.dumps(blob.get("personality_config")) if blob.get("personality_config") is not None else None,
                    row_id,
                ),
            )

    def _migrate_sqlite_drop_params_json(self, conn: Any, create_sql: str) -> None:
        """Rebuild user_campaign_inputs without params_json for SQLite."""
        # Read all existing rows (params_json already backfilled into new columns).
        rows = conn.execute("SELECT * FROM user_campaign_inputs").fetchall()
        conn.execute("DROP TABLE user_campaign_inputs")
        conn.execute(create_sql)
        if not rows:
            return
        # Derive column list from the new schema (excluding params_json).
        new_cols = self._column_names(conn, "user_campaign_inputs")
        col_names = ", ".join(new_cols)
        placeholders = ", ".join(["?"] * len(new_cols))
        for row in rows:
            data = _row_to_dict(row)
            values = [data.get(col) for col in new_cols]
            conn.execute(
                f"INSERT INTO user_campaign_inputs ({col_names}) VALUES ({placeholders})",
                values,
            )

    def _migrate_drop_campaign_inputs(self, conn: Any) -> None:
        """Copy any legacy campaign_inputs rows into user_campaign_inputs, then drop."""
        if "campaign_inputs" not in self._table_names(conn):
            return
        if "user_campaign_inputs" in self._table_names(conn):
            rows = conn.execute("SELECT * FROM campaign_inputs").fetchall()
            now = _utcnow()
            for row in rows:
                data = _row_to_dict(row)
                user_id = data.get("user_id")
                if not user_id:
                    continue
                existing = conn.execute(
                    "SELECT id FROM user_campaign_inputs WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                icp_values = (
                    data.get("raw_icp_text"),
                    data.get("user_offering"),
                    data.get("parsed_icp_json"),
                    data.get("industries_json"),
                    data.get("target_countries_json"),
                    data.get("target_continents_json"),
                    data.get("target_roles_json"),
                    data.get("company_size_min"),
                    data.get("company_size_max"),
                    data.get("revenue_min"),
                    data.get("revenue_max"),
                    data.get("tech_stack_json"),
                    data.get("growth_stage"),
                    data.get("funding_stage"),
                    data.get("target_cities_json"),
                    now,
                )
                if existing:
                    conn.execute(
                        """
                        UPDATE user_campaign_inputs SET
                            icp_description_text = COALESCE(?, icp_description_text),
                            user_offering = COALESCE(?, user_offering),
                            parsed_icp_json = ?,
                            industries_json = ?,
                            target_countries_json = ?,
                            target_continents_json = ?,
                            target_roles_json = ?,
                            company_size_min = ?,
                            company_size_max = ?,
                            revenue_min = ?,
                            revenue_max = ?,
                            tech_stack_json = ?,
                            growth_stage = ?,
                            funding_stage = ?,
                            target_cities_json = ?,
                            updated_at = ?
                        WHERE user_id = ?
                        """,
                        icp_values + (user_id,),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO user_campaign_inputs (
                            id, user_id, icp_description_text, user_offering,
                            parsed_icp_json, industries_json, target_countries_json,
                            target_continents_json, target_roles_json,
                            company_size_min, company_size_max, revenue_min, revenue_max,
                            tech_stack_json, growth_stage, funding_stage, target_cities_json,
                            run_async, auto_start_outreach, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            user_id,
                            *icp_values[:-1],
                            1,
                            0,
                            now,
                            now,
                        ),
                    )
        conn.execute("DROP TABLE campaign_inputs")

    @staticmethod
    def _as_bool_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None:
            return default
        return 1 if bool(value) else 0

    @staticmethod
    def _json_load(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    @staticmethod
    def _inputs_row_to_params(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": data["user_id"],
            "icp_description_text": data.get("icp_description_text"),
            "user_offering": data.get("user_offering"),
            "company_limit": data.get("company_limit"),
            "run_async": bool(data["run_async"]) if data.get("run_async") is not None else True,
            "auto_start_outreach": bool(data["auto_start_outreach"])
            if data.get("auto_start_outreach") is not None
            else False,
            "sender_company": data.get("sender_company"),
            "sender_elevator_pitch": data.get("sender_elevator_pitch"),
            "offer_name": data.get("offer_name"),
            "solution_summary": data.get("solution_summary"),
            "cta": data.get("cta"),
            "approval_mode": data.get("approval_mode"),
            "use_native_language": (
                bool(data["use_native_language"])
                if data.get("use_native_language") is not None
                else None
            ),
            "message_language": data.get("message_language"),
            "has_inmail_credits": (
                bool(data["has_inmail_credits"])
                if data.get("has_inmail_credits") is not None
                else None
            ),
            "debug_mode": (
                bool(data["debug_mode"]) if data.get("debug_mode") is not None else None
            ),
            # AI Sequence Configuration (individual columns)
            "max_touches": data.get("max_touches"),
            "max_days": data.get("max_days"),
            "preferred_first_channel": data.get("preferred_first_channel"),
            "sequence_options": CampaignStore._json_load(data.get("sequence_options_json"), None),
            "stage_instructions": CampaignStore._json_load(data.get("stage_instructions_json"), None),
            "personality_config": CampaignStore._json_load(data.get("personality_config_json"), None),
            # ICP sub-attributes (columns; empty until pipeline or PATCH fills them)
            "industries": CampaignStore._json_load(data.get("industries_json"), []),
            "target_countries": CampaignStore._json_load(
                data.get("target_countries_json"), []
            ),
            "target_continents": CampaignStore._json_load(
                data.get("target_continents_json"), []
            ),
            "target_roles": CampaignStore._json_load(data.get("target_roles_json"), []),
            "company_size": {
                "min": data.get("company_size_min"),
                "max": data.get("company_size_max"),
            },
            "revenue_range": {
                "min": data.get("revenue_min"),
                "max": data.get("revenue_max"),
            },
            "tech_stack": CampaignStore._json_load(data.get("tech_stack_json"), []),
            "growth_stage": data.get("growth_stage"),
            "funding_stage": data.get("funding_stage"),
            "target_cities": CampaignStore._json_load(data.get("target_cities_json"), []),
        }

    # Top-level param keys that map to ICP columns (used by PATCH merge).
    ICP_PARAM_KEYS = frozenset(
        {
            "industries",
            "target_countries",
            "target_continents",
            "target_roles",
            "company_size",
            "revenue_range",
            "tech_stack",
            "growth_stage",
            "funding_stage",
            "target_cities",
        }
    )

    @staticmethod
    def _empty_parsed_icp_columns() -> Dict[str, Any]:
        empty_list = json.dumps([])
        return {
            "parsed_icp_json": json.dumps({}),
            "industries_json": empty_list,
            "target_countries_json": empty_list,
            "target_continents_json": empty_list,
            "target_roles_json": empty_list,
            "company_size_min": None,
            "company_size_max": None,
            "revenue_min": None,
            "revenue_max": None,
            "tech_stack_json": empty_list,
            "growth_stage": None,
            "funding_stage": None,
            "target_cities_json": empty_list,
        }

    @staticmethod
    def _parsed_icp_to_columns(parsed_icp: Dict[str, Any]) -> Dict[str, Any]:
        parsed = parsed_icp or {}
        size = parsed.get("company_size") or {}
        revenue = parsed.get("revenue_range") or {}
        return {
            "parsed_icp_json": json.dumps(parsed, default=str),
            "industries_json": json.dumps(parsed.get("industries") or [], default=str),
            "target_countries_json": json.dumps(
                parsed.get("target_countries") or [], default=str
            ),
            "target_continents_json": json.dumps(
                parsed.get("target_continents") or [], default=str
            ),
            "target_roles_json": json.dumps(parsed.get("target_roles") or [], default=str),
            "company_size_min": float(size["min"]) if size.get("min") is not None else None,
            "company_size_max": float(size["max"]) if size.get("max") is not None else None,
            "revenue_min": float(revenue["min"]) if revenue.get("min") is not None else None,
            "revenue_max": float(revenue["max"]) if revenue.get("max") is not None else None,
            "tech_stack_json": json.dumps(parsed.get("tech_stack") or [], default=str),
            "growth_stage": parsed.get("growth_stage"),
            "funding_stage": parsed.get("funding_stage"),
            "target_cities_json": json.dumps(
                parsed.get("target_cities") or [], default=str
            ),
        }

    def save_campaign_params(self, user_id: str, params: Dict[str, Any]) -> str:
        """Persist draft params without starting a campaign.

        Fills:
        - user_campaign_inputs (individual columns + raw ICP + empty ICP attrs)
        - blacklist_entries (row-per-entry format)
        - campaign_weights (one column per weight)
        """
        now = _utcnow()
        with self._conn() as conn:
            input_id = self._upsert_user_campaign_inputs_conn(
                conn, user_id, params, now, parsed_icp={}
            )
            self._replace_blacklist_entries_conn(
                conn, user_id, params.get("blacklist") or {}, now
            )
            weights = dict(settings.default_configurable_weights())
            weights.update(params.get("configurable_weights") or {})
            self._upsert_campaign_weights_conn(conn, user_id, weights, now)
        return input_id

    # Backwards-compatible alias
    def upsert_user_campaign_params(self, user_id: str, params: Dict[str, Any]) -> str:
        return self.save_campaign_params(user_id, params)

    def patch_user_campaign_inputs(
        self, user_id: str, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Partial update of an existing user_campaign_inputs row.

        Only keys present in ``patch`` are changed; omitted keys keep their
        current values. Nested dicts (``company_size``, ``revenue_range``,
        ``configurable_weights``, ``blacklist``, ``sequence_options``,
        ``stage_instructions``, ``personality_config``) are deep-merged at
        the first level so a partial nested payload does not wipe sibling keys.
        """
        existing = self.get_user_campaign_inputs(user_id)
        if not existing:
            return None

        current = dict(existing["params"])
        patch = {k: v for k, v in (patch or {}).items() if k != "user_id"}
        if not patch:
            return existing

        merged = dict(current)

        # Nested merges first so a partial object does not null sibling keys.
        _NESTED_MERGE_KEYS = (
            "company_size",
            "revenue_range",
            "configurable_weights",
            "sequence_options",
            "stage_instructions",
            "personality_config",
        )
        for key in _NESTED_MERGE_KEYS:
            if key in patch:
                existing_val = dict(current.get(key) or {})
                incoming = patch.get(key)
                if isinstance(incoming, dict):
                    existing_val.update(incoming)
                merged[key] = existing_val

        if "blacklist" in patch:
            bl = {
                "companies": list((current.get("blacklist") or {}).get("companies") or []),
                "personas": list((current.get("blacklist") or {}).get("personas") or []),
            }
            incoming = patch.get("blacklist") or {}
            if isinstance(incoming, dict):
                if "companies" in incoming:
                    bl["companies"] = list(incoming.get("companies") or [])
                if "personas" in incoming:
                    bl["personas"] = list(incoming.get("personas") or [])
            merged["blacklist"] = bl

        for key, value in patch.items():
            if key in _NESTED_MERGE_KEYS or key == "blacklist":
                continue
            merged[key] = value

        merged["user_id"] = user_id

        parsed_icp = {
            "industries": merged.get("industries") or [],
            "target_countries": merged.get("target_countries") or [],
            "target_continents": merged.get("target_continents") or [],
            "target_roles": merged.get("target_roles") or [],
            "company_size": merged.get("company_size") or {},
            "revenue_range": merged.get("revenue_range") or {},
            "tech_stack": merged.get("tech_stack") or [],
            "growth_stage": merged.get("growth_stage"),
            "funding_stage": merged.get("funding_stage"),
            "target_cities": merged.get("target_cities") or [],
        }

        now = _utcnow()
        with self._conn() as conn:
            self._upsert_user_campaign_inputs_conn(
                conn, user_id, merged, now, parsed_icp=parsed_icp
            )
            if "blacklist" in patch:
                self._replace_blacklist_entries_conn(
                    conn, user_id, merged.get("blacklist") or {}, now
                )
            if "configurable_weights" in patch:
                weights = dict(settings.default_configurable_weights())
                weights.update(merged.get("configurable_weights") or {})
                self._upsert_campaign_weights_conn(conn, user_id, weights, now)

        return self.get_user_campaign_inputs(user_id)

    def _upsert_user_campaign_inputs_conn(
        self,
        conn: Any,
        user_id: str,
        params: Dict[str, Any],
        now: Optional[str] = None,
        parsed_icp: Optional[Dict[str, Any]] = None,
    ) -> str:
        now = now or _utcnow()
        input_id = str(uuid.uuid4())
        icp_cols = (
            self._parsed_icp_to_columns(parsed_icp)
            if parsed_icp is not None
            else self._empty_parsed_icp_columns()
        )
        existing = conn.execute(
            "SELECT id FROM user_campaign_inputs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if existing:
            input_id = _row_to_dict(existing)["id"]
            # Re-saving draft params keeps previously parsed ICP attrs unless
            # the caller explicitly passes parsed_icp (including {}).
            if parsed_icp is not None:
                conn.execute(
                    """
                    UPDATE user_campaign_inputs SET
                        icp_description_text = ?,
                        user_offering = ?,
                        parsed_icp_json = ?,
                        industries_json = ?,
                        target_countries_json = ?,
                        target_continents_json = ?,
                        target_roles_json = ?,
                        company_size_min = ?,
                        company_size_max = ?,
                        revenue_min = ?,
                        revenue_max = ?,
                        tech_stack_json = ?,
                        growth_stage = ?,
                        funding_stage = ?,
                        target_cities_json = ?,
                        company_limit = ?,
                        run_async = ?,
                        auto_start_outreach = ?,
                        sender_company = ?,
                        sender_elevator_pitch = ?,
                        offer_name = ?,
                        solution_summary = ?,
                        cta = ?,
                        approval_mode = ?,
                        use_native_language = ?,
                        message_language = ?,
                        has_inmail_credits = ?,
                        debug_mode = ?,
                        max_touches = ?,
                        max_days = ?,
                        preferred_first_channel = ?,
                        sequence_options_json = ?,
                        stage_instructions_json = ?,
                        personality_config_json = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        params.get("icp_description_text"),
                        params.get("user_offering"),
                        icp_cols["parsed_icp_json"],
                        icp_cols["industries_json"],
                        icp_cols["target_countries_json"],
                        icp_cols["target_continents_json"],
                        icp_cols["target_roles_json"],
                        icp_cols["company_size_min"],
                        icp_cols["company_size_max"],
                        icp_cols["revenue_min"],
                        icp_cols["revenue_max"],
                        icp_cols["tech_stack_json"],
                        icp_cols["growth_stage"],
                        icp_cols["funding_stage"],
                        icp_cols["target_cities_json"],
                        params.get("company_limit"),
                        self._as_bool_int(params.get("run_async"), default=1),
                        self._as_bool_int(params.get("auto_start_outreach"), default=0),
                        params.get("sender_company"),
                        params.get("sender_elevator_pitch"),
                        params.get("offer_name"),
                        params.get("solution_summary"),
                        params.get("cta"),
                        params.get("approval_mode"),
                        self._as_bool_int(params.get("use_native_language")),
                        params.get("message_language"),
                        self._as_bool_int(params.get("has_inmail_credits")),
                        self._as_bool_int(params.get("debug_mode")),
                        params.get("max_touches"),
                        params.get("max_days"),
                        params.get("preferred_first_channel"),
                        json.dumps(params.get("sequence_options")) if params.get("sequence_options") is not None else None,
                        json.dumps(params.get("stage_instructions")) if params.get("stage_instructions") is not None else None,
                        json.dumps(params.get("personality_config")) if params.get("personality_config") is not None else None,
                        now,
                        user_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE user_campaign_inputs SET
                        icp_description_text = ?,
                        user_offering = ?,
                        company_limit = ?,
                        run_async = ?,
                        auto_start_outreach = ?,
                        sender_company = ?,
                        sender_elevator_pitch = ?,
                        offer_name = ?,
                        solution_summary = ?,
                        cta = ?,
                        approval_mode = ?,
                        use_native_language = ?,
                        message_language = ?,
                        has_inmail_credits = ?,
                        debug_mode = ?,
                        max_touches = ?,
                        max_days = ?,
                        preferred_first_channel = ?,
                        sequence_options_json = ?,
                        stage_instructions_json = ?,
                        personality_config_json = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        params.get("icp_description_text"),
                        params.get("user_offering"),
                        params.get("company_limit"),
                        self._as_bool_int(params.get("run_async"), default=1),
                        self._as_bool_int(params.get("auto_start_outreach"), default=0),
                        params.get("sender_company"),
                        params.get("sender_elevator_pitch"),
                        params.get("offer_name"),
                        params.get("solution_summary"),
                        params.get("cta"),
                        params.get("approval_mode"),
                        self._as_bool_int(params.get("use_native_language")),
                        params.get("message_language"),
                        self._as_bool_int(params.get("has_inmail_credits")),
                        self._as_bool_int(params.get("debug_mode")),
                        params.get("max_touches"),
                        params.get("max_days"),
                        params.get("preferred_first_channel"),
                        json.dumps(params.get("sequence_options")) if params.get("sequence_options") is not None else None,
                        json.dumps(params.get("stage_instructions")) if params.get("stage_instructions") is not None else None,
                        json.dumps(params.get("personality_config")) if params.get("personality_config") is not None else None,
                        now,
                        user_id,
                    ),
                )
        else:
            conn.execute(
                """
                INSERT INTO user_campaign_inputs (
                    id, user_id, icp_description_text, user_offering,
                    parsed_icp_json, industries_json, target_countries_json,
                    target_continents_json, target_roles_json,
                    company_size_min, company_size_max, revenue_min, revenue_max,
                    tech_stack_json, growth_stage, funding_stage, target_cities_json,
                    company_limit, run_async, auto_start_outreach, sender_company,
                    sender_elevator_pitch, offer_name, solution_summary, cta,
                    approval_mode, use_native_language, message_language,
                    has_inmail_credits, debug_mode,
                    max_touches, max_days, preferred_first_channel,
                    sequence_options_json, stage_instructions_json, personality_config_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    input_id,
                    user_id,
                    params.get("icp_description_text"),
                    params.get("user_offering"),
                    icp_cols["parsed_icp_json"],
                    icp_cols["industries_json"],
                    icp_cols["target_countries_json"],
                    icp_cols["target_continents_json"],
                    icp_cols["target_roles_json"],
                    icp_cols["company_size_min"],
                    icp_cols["company_size_max"],
                    icp_cols["revenue_min"],
                    icp_cols["revenue_max"],
                    icp_cols["tech_stack_json"],
                    icp_cols["growth_stage"],
                    icp_cols["funding_stage"],
                    icp_cols["target_cities_json"],
                    params.get("company_limit"),
                    self._as_bool_int(params.get("run_async"), default=1),
                    self._as_bool_int(params.get("auto_start_outreach"), default=0),
                    params.get("sender_company"),
                    params.get("sender_elevator_pitch"),
                    params.get("offer_name"),
                    params.get("solution_summary"),
                    params.get("cta"),
                    params.get("approval_mode"),
                    self._as_bool_int(params.get("use_native_language")),
                    params.get("message_language"),
                    self._as_bool_int(params.get("has_inmail_credits")),
                    self._as_bool_int(params.get("debug_mode")),
                    params.get("max_touches"),
                    params.get("max_days"),
                    params.get("preferred_first_channel"),
                    json.dumps(params.get("sequence_options")) if params.get("sequence_options") is not None else None,
                    json.dumps(params.get("stage_instructions")) if params.get("stage_instructions") is not None else None,
                    json.dumps(params.get("personality_config")) if params.get("personality_config") is not None else None,
                    now,
                    now,
                ),
            )
        return input_id

    def get_blacklist_for_user(self, user_id: str) -> Dict[str, List[str]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT entry_type, match_value FROM blacklist_entries
                WHERE user_id = ? ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        companies: List[str] = []
        personas: List[str] = []
        for row in rows:
            data = _row_to_dict(row)
            if data["entry_type"] == "company":
                companies.append(data["match_value"])
            elif data["entry_type"] == "persona":
                personas.append(data["match_value"])
        return {"companies": companies, "personas": personas}

    def get_weights_for_user(self, user_id: str) -> Optional[Dict[str, float]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM campaign_weights WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        data = _row_to_dict(row)
        out: Dict[str, float] = {}
        for key in WEIGHT_COLUMNS:
            if data.get(key) is not None:
                out[key] = float(data[key])
        return out

    def get_user_campaign_inputs(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load saved draft params; blacklist/weights come from their own tables."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_campaign_inputs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            data = _row_to_dict(row)
        params = self._inputs_row_to_params(data)
        params["user_id"] = user_id
        params["blacklist"] = self.get_blacklist_for_user(user_id)
        weights = self.get_weights_for_user(user_id)
        if weights is not None:
            params["configurable_weights"] = weights
        return {
            "id": data["id"],
            "user_id": data["user_id"],
            "params": params,
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def get_user_campaign_params(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.get_user_campaign_inputs(user_id)

    def create_campaign(
        self,
        user_id: str,
        raw_icp: str,
        user_offering: str,
        campaign_id: Optional[str] = None,
        outreach_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        cid = campaign_id or str(uuid.uuid4())
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO campaigns (
                    id, user_id, status, stage, raw_icp, user_offering,
                    outreach_config_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    user_id,
                    "running",
                    CampaignStage.CREATED.value,
                    raw_icp,
                    user_offering,
                    json.dumps(outreach_config or {}, default=str),
                    now,
                    now,
                ),
            )
        return cid

    def update_stage(
        self,
        campaign_id: str,
        stage: CampaignStage,
        *,
        status: Optional[str] = None,
        qualifier_campaign_id: Optional[str] = None,
        icp_features: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        fields = ["stage = ?", "updated_at = ?"]
        values: List[Any] = [stage.value, _utcnow()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if qualifier_campaign_id is not None:
            fields.append("qualifier_campaign_id = ?")
            values.append(qualifier_campaign_id)
        if icp_features is not None:
            fields.append("icp_features_json = ?")
            values.append(json.dumps(icp_features, default=str))
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        values.append(campaign_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE campaigns SET {', '.join(fields)} WHERE id = ?",
                values,
            )

    def save_artifact(self, campaign_id: str, stage: str, payload: Any) -> str:
        artifact_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (id, campaign_id, stage, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    campaign_id,
                    stage,
                    json.dumps(payload, default=str),
                    _utcnow(),
                ),
            )
        return artifact_id

    def save_final_packages(self, campaign_id: str, packages: List[Dict[str, Any]]) -> None:
        with self._conn() as conn:
            for pkg in packages:
                conn.execute(
                    """
                    INSERT INTO final_packages (id, campaign_id, lead_id, package_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        campaign_id,
                        pkg.get("lead_id") or str(uuid.uuid4()),
                        json.dumps(pkg, default=str),
                        _utcnow(),
                    ),
                )

    def upsert_campaign_inputs(
        self,
        user_id: str,
        raw_icp_text: str,
        user_offering: str,
        parsed_icp: Dict[str, Any],
    ) -> None:
        """Update ICP raw text + parsed sub-attributes on user_campaign_inputs."""
        with self._conn() as conn:
            self._upsert_parsed_icp_conn(
                conn, user_id, raw_icp_text, user_offering, parsed_icp
            )

    def _upsert_parsed_icp_conn(
        self,
        conn: Any,
        user_id: str,
        raw_icp_text: str,
        user_offering: str,
        parsed_icp: Dict[str, Any],
        now: Optional[str] = None,
    ) -> None:
        now = now or _utcnow()
        icp_cols = self._parsed_icp_to_columns(parsed_icp)
        existing = conn.execute(
            "SELECT id FROM user_campaign_inputs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE user_campaign_inputs SET
                    icp_description_text = ?,
                    user_offering = ?,
                    parsed_icp_json = ?,
                    industries_json = ?,
                    target_countries_json = ?,
                    target_continents_json = ?,
                    target_roles_json = ?,
                    company_size_min = ?,
                    company_size_max = ?,
                    revenue_min = ?,
                    revenue_max = ?,
                    tech_stack_json = ?,
                    growth_stage = ?,
                    funding_stage = ?,
                    target_cities_json = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    raw_icp_text,
                    user_offering,
                    icp_cols["parsed_icp_json"],
                    icp_cols["industries_json"],
                    icp_cols["target_countries_json"],
                    icp_cols["target_continents_json"],
                    icp_cols["target_roles_json"],
                    icp_cols["company_size_min"],
                    icp_cols["company_size_max"],
                    icp_cols["revenue_min"],
                    icp_cols["revenue_max"],
                    icp_cols["tech_stack_json"],
                    icp_cols["growth_stage"],
                    icp_cols["funding_stage"],
                    icp_cols["target_cities_json"],
                    now,
                    user_id,
                ),
            )
            return
        # No draft row yet — create a minimal one with the ICP columns filled.
        conn.execute(
            """
            INSERT INTO user_campaign_inputs (
                id, user_id, icp_description_text, user_offering,
                parsed_icp_json, industries_json, target_countries_json,
                target_continents_json, target_roles_json,
                company_size_min, company_size_max, revenue_min, revenue_max,
                tech_stack_json, growth_stage, funding_stage, target_cities_json,
                run_async, auto_start_outreach, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                raw_icp_text,
                user_offering,
                icp_cols["parsed_icp_json"],
                icp_cols["industries_json"],
                icp_cols["target_countries_json"],
                icp_cols["target_continents_json"],
                icp_cols["target_roles_json"],
                icp_cols["company_size_min"],
                icp_cols["company_size_max"],
                icp_cols["revenue_min"],
                icp_cols["revenue_max"],
                icp_cols["tech_stack_json"],
                icp_cols["growth_stage"],
                icp_cols["funding_stage"],
                icp_cols["target_cities_json"],
                1,
                0,
                now,
                now,
            ),
        )

    def upsert_campaign_weights(self, user_id: str, weights: Dict[str, Any]) -> None:
        with self._conn() as conn:
            self._upsert_campaign_weights_conn(conn, user_id, weights)

    def _upsert_campaign_weights_conn(
        self,
        conn: Any,
        user_id: str,
        weights: Dict[str, Any],
        now: Optional[str] = None,
    ) -> None:
        now = now or _utcnow()
        resolved = dict(weights or {})
        col_values = [resolved.get(col) for col in WEIGHT_COLUMNS]
        placeholders = ", ".join(["?"] * (2 + len(WEIGHT_COLUMNS) + 2))
        col_names = ", ".join(["id", "user_id"] + WEIGHT_COLUMNS + ["created_at", "updated_at"])
        update_set = ", ".join(
            [f"{col}=excluded.{col}" for col in WEIGHT_COLUMNS] + ["updated_at=excluded.updated_at"]
        )
        conn.execute(
            f"""
            INSERT INTO campaign_weights ({col_names})
            VALUES ({placeholders})
            ON CONFLICT(user_id) DO UPDATE SET {update_set}
            """,
            (str(uuid.uuid4()), user_id, *col_values, now, now),
        )

    def save_blacklist_entries(self, user_id: str, blacklist: Dict[str, List[str]]) -> None:
        with self._conn() as conn:
            self._replace_blacklist_entries_conn(conn, user_id, blacklist)

    def _replace_blacklist_entries_conn(
        self,
        conn: Any,
        user_id: str,
        blacklist: Dict[str, List[str]],
        now: Optional[str] = None,
    ) -> None:
        now = now or _utcnow()
        companies = list((blacklist or {}).get("companies") or [])
        personas = list((blacklist or {}).get("personas") or [])
        conn.execute("DELETE FROM blacklist_entries WHERE user_id = ?", (user_id,))
        for name in companies:
            if not str(name).strip():
                continue
            conn.execute(
                """
                INSERT INTO blacklist_entries
                (id, user_id, entry_type, match_value, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, entry_type, match_value) DO NOTHING
                """,
                (str(uuid.uuid4()), user_id, "company", str(name).strip(), now),
            )
        for url in personas:
            if not str(url).strip():
                continue
            conn.execute(
                """
                INSERT INTO blacklist_entries
                (id, user_id, entry_type, match_value, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, entry_type, match_value) DO NOTHING
                """,
                (str(uuid.uuid4()), user_id, "persona", str(url).strip(), now),
            )

    def save_campaign_companies(self, campaign_id: str, companies: List[Dict[str, Any]]) -> None:
        now = _utcnow()
        with self._conn() as conn:
            for co in companies or []:
                apollo_id = co.get("apollo_id") or co.get("id")
                if not apollo_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO campaign_companies
                    (id, campaign_id, apollo_company_id, company_name, status, created_at)
                    VALUES (?, ?, ?, ?, 'approved', ?)
                    ON CONFLICT(campaign_id, apollo_company_id) DO UPDATE SET
                        company_name=excluded.company_name
                    """,
                    (
                        str(uuid.uuid4()),
                        campaign_id,
                        str(apollo_id),
                        str(co.get("name") or "Unknown"),
                        now,
                    ),
                )

    def list_campaign_companies(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, campaign_id, apollo_company_id, company_name, status, created_at
                FROM campaign_companies
                WHERE campaign_id = ?
                ORDER BY created_at ASC, company_name ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_campaign_personas(
        self, campaign_id: str, company_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List personas sourced for a campaign, optionally filtered by company."""
        with self._conn() as conn:
            if company_id:
                rows = conn.execute(
                    """
                    SELECT id, campaign_id, apollo_persona_id, apollo_company_id,
                           persona_name, linkedin_url, created_at
                    FROM campaign_personas
                    WHERE campaign_id = ? AND apollo_company_id = ?
                    ORDER BY created_at ASC
                    """,
                    (campaign_id, company_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, campaign_id, apollo_persona_id, apollo_company_id,
                           persona_name, linkedin_url, created_at
                    FROM campaign_personas
                    WHERE campaign_id = ?
                    ORDER BY created_at ASC
                    """,
                    (campaign_id,),
                ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def decline_campaign_companies(
        self, campaign_id: str, company_ids: List[str]
    ) -> Dict[str, Any]:
        """Set status=declined for the given campaign_companies row ids."""
        ids = [str(cid).strip() for cid in (company_ids or []) if str(cid).strip()]
        if not ids:
            return {"declined": [], "not_found": [], "already_declined": []}

        declined: List[Dict[str, Any]] = []
        not_found: List[str] = []
        already_declined: List[Dict[str, Any]] = []

        with self._conn() as conn:
            for company_id in ids:
                row = conn.execute(
                    """
                    SELECT id, apollo_company_id, company_name, status
                    FROM campaign_companies
                    WHERE campaign_id = ? AND id = ?
                    """,
                    (campaign_id, company_id),
                ).fetchone()
                if not row:
                    not_found.append(company_id)
                    continue
                data = _row_to_dict(row)
                if str(data.get("status") or "").lower() == "declined":
                    already_declined.append(
                        {
                            "id": data["id"],
                            "company_name": data["company_name"],
                            "apollo_company_id": data["apollo_company_id"],
                            "status": data["status"],
                        }
                    )
                    continue
                conn.execute(
                    """
                    UPDATE campaign_companies
                    SET status = 'declined'
                    WHERE campaign_id = ? AND id = ?
                    """,
                    (campaign_id, company_id),
                )
                declined.append(
                    {
                        "id": data["id"],
                        "company_name": data["company_name"],
                        "apollo_company_id": data["apollo_company_id"],
                        "status": "declined",
                    }
                )
        return {
            "declined": declined,
            "not_found": not_found,
            "already_declined": already_declined,
        }

    def list_campaign_personas(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, campaign_id, apollo_persona_id, apollo_company_id,
                       persona_name, linkedin_url, created_at
                FROM campaign_personas
                WHERE campaign_id = ?
                ORDER BY created_at ASC, persona_name ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def save_campaign_personas(
        self,
        campaign_id: str,
        personas_by_company: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        now = _utcnow()
        with self._conn() as conn:
            for company_id, personas in (personas_by_company or {}).items():
                for p in personas or []:
                    persona_id = p.get("apollo_id") or p.get("id")
                    if not persona_id:
                        continue
                    conn.execute(
                        """
                        INSERT INTO campaign_personas
                        (id, campaign_id, apollo_persona_id, apollo_company_id, persona_name, linkedin_url, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(campaign_id, apollo_persona_id) DO UPDATE SET
                            apollo_company_id=excluded.apollo_company_id,
                            persona_name=excluded.persona_name,
                            linkedin_url=excluded.linkedin_url,
                            created_at=excluded.created_at
                        """,
                        (
                            str(uuid.uuid4()),
                            campaign_id,
                            str(persona_id),
                            str(company_id) if company_id else None,
                            p.get("name"),
                            p.get("linkedin_url"),
                            now,
                        ),
                    )

    def save_token_usage_report(self, campaign_id: str, usage_report: Dict[str, Any]) -> None:
        tools = dict((usage_report or {}).get("tools") or {})
        now = _utcnow()
        with self._conn() as conn:
            for tool_name, payload in tools.items():
                groq = dict((payload or {}).get("groq") or {})
                total_tokens = int(groq.get("total_tokens") or 0)
                tokens_in = int(groq.get("tokens_in") or 0)
                tokens_out = int(groq.get("tokens_out") or 0)
                total_llm_calls = int(groq.get("total_llm_calls") or 0)
                conn.execute(
                    """
                    INSERT INTO token_usage
                    (id, campaign_id, tool_name, usage_json, total_tokens, tokens_in, tokens_out, total_llm_calls, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        campaign_id,
                        str(tool_name),
                        json.dumps(payload or {}, default=str),
                        total_tokens,
                        tokens_in,
                        tokens_out,
                        total_llm_calls,
                        now,
                    ),
                )

    def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if not row:
                return None
            data = _row_to_dict(row)
            if data.get("icp_features_json"):
                data["icp_features"] = json.loads(data["icp_features_json"])
            else:
                data["icp_features"] = None
            if data.get("outreach_config_json"):
                data["outreach_config"] = json.loads(data["outreach_config_json"])
            else:
                data["outreach_config"] = None
            return data

    def list_artifacts(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, stage, payload_json, created_at
                FROM artifacts WHERE campaign_id = ? ORDER BY created_at ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [
            {
                "id": _row_to_dict(r)["id"],
                "stage": _row_to_dict(r)["stage"],
                "payload": json.loads(_row_to_dict(r)["payload_json"]),
                "created_at": _row_to_dict(r)["created_at"],
            }
            for r in rows
        ]

    def list_packages(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT lead_id, package_json, created_at
                FROM final_packages WHERE campaign_id = ? ORDER BY created_at ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [
            {
                "lead_id": _row_to_dict(r)["lead_id"],
                "package": json.loads(_row_to_dict(r)["package_json"]),
                "created_at": _row_to_dict(r)["created_at"],
            }
            for r in rows
        ]

    def save_outreach_thread(
        self,
        campaign_id: str,
        lead_id: str,
        thread_id: Optional[str],
        status: str,
        payload: Dict[str, Any],
    ) -> str:
        thread_db_id = str(uuid.uuid4())
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO outreach_threads (id, campaign_id, lead_id, thread_id, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_db_id,
                    campaign_id,
                    lead_id,
                    thread_id,
                    status,
                    json.dumps(payload, default=str),
                    now,
                    now,
                ),
            )
        return thread_db_id

    def list_outreach_threads(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, lead_id, thread_id, status, payload_json, created_at, updated_at
                FROM outreach_threads WHERE campaign_id = ? ORDER BY created_at ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [
            {
                "id": _row_to_dict(r)["id"],
                "lead_id": _row_to_dict(r)["lead_id"],
                "thread_id": _row_to_dict(r)["thread_id"],
                "status": _row_to_dict(r)["status"],
                "payload": json.loads(_row_to_dict(r)["payload_json"]),
                "created_at": _row_to_dict(r)["created_at"],
                "updated_at": _row_to_dict(r)["updated_at"],
            }
            for r in rows
        ]

    def save_outreach_steps(
        self,
        campaign_id: str,
        workflow_id: str,
        thread_id: Optional[str],
        steps: List[Dict[str, Any]],
    ) -> None:
        """Persist outreach sequence steps as structured rows.

        Called after dispatch (custom), after approval (AI path), or after
        any signal (approve-step, skip-step, regenerate-step, edit-step,
        update-sequence). Uses DELETE + INSERT (upsert pattern) so that
        rapid successive calls for the same workflow don't produce duplicate
        rows.
        """
        now = _utcnow()
        with self._conn() as conn:
            # ── Upsert: clear old rows for this workflow, then insert fresh ──
            conn.execute(
                "DELETE FROM outreach_sequence_steps "
                "WHERE campaign_id = ? AND workflow_id = ?",
                (campaign_id, workflow_id),
            )
            for step in steps:
                if not isinstance(step, dict):
                    continue
                message = step.get("message") or {}
                if isinstance(message, dict):
                    message_text = message.get("message") or ""
                    subject = message.get("subject")
                else:
                    message_text = str(message) if message else ""
                    subject = None
                conn.execute(
                    """
                    INSERT INTO outreach_sequence_steps (
                        id, campaign_id, thread_id, workflow_id, step_num,
                        action_type, channel, message_text, subject, ai_write,
                        status, quality_score, error, sent_at, wait_delay_seconds,
                        day_offset, time_of_day, strategy_notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        campaign_id,
                        thread_id,
                        workflow_id,
                        step.get("step_num", 0),
                        step.get("action_type", "EMAIL_1"),
                        step.get("channel", "email"),
                        message_text or None,
                        subject,
                        1 if step.get("ai_write") else 0,
                        step.get("status", "pending"),
                        step.get("quality_score"),
                        step.get("error"),
                        step.get("sent_at"),
                        step.get("wait_delay_seconds", 0),
                        step.get("day_offset", 0),
                        step.get("time_of_day", "10h"),
                        step.get("strategy_notes", ""),
                        now,
                        now,
                    ),
                )

    def list_outreach_steps(
        self, campaign_id: str, workflow_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query outreach steps for a campaign, optionally filtered by workflow."""
        with self._conn() as conn:
            if workflow_id:
                rows = conn.execute(
                    """
                    SELECT * FROM outreach_sequence_steps
                    WHERE campaign_id = ? AND workflow_id = ?
                    ORDER BY step_num ASC
                    """,
                    (campaign_id, workflow_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM outreach_sequence_steps
                    WHERE campaign_id = ?
                    ORDER BY created_at ASC, step_num ASC
                    """,
                    (campaign_id,),
                ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def update_outreach_step_status(
        self,
        campaign_id: str,
        workflow_id: str,
        step_num: int,
        *,
        status: Optional[str] = None,
        message_text: Optional[str] = None,
        quality_score: Optional[int] = None,
        error: Optional[str] = None,
        sent_at: Optional[str] = None,
    ) -> None:
        """Update a specific step's status after send or failure."""
        now = _utcnow()
        fields = ["updated_at = ?"]
        values: List[Any] = [now]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if message_text is not None:
            fields.append("message_text = ?")
            values.append(message_text)
        if quality_score is not None:
            fields.append("quality_score = ?")
            values.append(quality_score)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if sent_at is not None:
            fields.append("sent_at = ?")
            values.append(sent_at)
        values.extend([campaign_id, workflow_id, step_num])
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE outreach_sequence_steps
                SET {', '.join(fields)}
                WHERE campaign_id = ? AND workflow_id = ? AND step_num = ?
                """,
                values,
            )

    def update_outreach_thread_status(
        self,
        thread_db_id: str,
        status: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = _utcnow()
        with self._conn() as conn:
            if payload is not None:
                conn.execute(
                    """
                    UPDATE outreach_threads
                    SET status = ?, payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, json.dumps(payload, default=str), now, thread_db_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE outreach_threads
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, thread_db_id),
                )

    # ── Message Generator Memory (hub-and-spoke persistence) ──────────

    def save_memory_records(self, records: List[Dict[str, Any]]) -> int:
        """Batch upsert memory records from the message generator.

        Each record is {"key": str, "value": dict}. Uses ON CONFLICT DO UPDATE
        so re-sending the same key is idempotent.

        Returns the number of records persisted.
        """
        if not records:
            return 0
        now = _utcnow()
        with self._conn() as conn:
            for rec in records:
                conn.execute(
                    """
                    INSERT INTO msg_gen_memory (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        rec["key"],
                        json.dumps(rec["value"], default=str),
                        now,
                    ),
                )
        return len(records)

    def list_memory_records(self, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all memory records, optionally filtered by key prefix."""
        with self._conn() as conn:
            if prefix:
                rows = conn.execute(
                    "SELECT key, value, updated_at FROM msg_gen_memory WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, updated_at FROM msg_gen_memory ORDER BY key",
                ).fetchall()
        return [
            {
                "key": _row_to_dict(r)["key"],
                "value": (
                    _row_to_dict(r)["value"]
                    if isinstance(_row_to_dict(r).get("value"), dict)
                    else json.loads(_row_to_dict(r)["value"])
                ),
                "updated_at": _row_to_dict(r)["updated_at"],
            }
            for r in rows
        ]

    def delete_all_memory(self) -> int:
        """Wipe all msg_gen_memory records. Returns the count of deleted rows."""
        with self._conn() as conn:
            result = conn.execute("SELECT COUNT(*) AS cnt FROM msg_gen_memory").fetchone()
            count = _row_to_dict(result).get("cnt", 0)
            conn.execute("DELETE FROM msg_gen_memory")
        return count


class _SqliteCursor:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params=()):
        if "DOUBLE PRECISION" in sql:
            sql = sql.replace("DOUBLE PRECISION", "REAL")
        self._cursor = self._conn.execute(sql, params)
        return self

    def fetchone(self):
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self):
        if self._cursor is None:
            return []
        return self._cursor.fetchall()


class _LazyStore:
    _instance: Optional["CampaignStore"] = None

    def _get(self) -> "CampaignStore":
        if self._instance is None:
            if settings.database_backend == "postgres":
                self._instance = CampaignStore(database_url=settings.resolved_database_url())
            else:
                self._instance = CampaignStore(db_path=settings.database_path)
            import logging
            _log = logging.getLogger(__name__)
            _log.info(
                "store: backend=%s path=%s",
                self._instance._backend,
                getattr(self._instance, "db_path", None) or getattr(self._instance, "database_url", None),
            )
        return self._instance

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get(), item)


store: Any = _LazyStore()
