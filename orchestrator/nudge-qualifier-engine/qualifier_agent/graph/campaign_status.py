"""
graph/campaign_status.py
─────────────────────────
Campaign lifecycle status manager.

This module owns all reads and writes to the campaigns table.
It is the ONLY place that should touch that table directly —
nodes.py, workflow.py, and the orchestrator all go through this.

Lifecycle:
    create()              — called when the API receives a new campaign request
        ↓ status = 'running'
    set_ready_for_personas() — called after company ranking pauses for orchestrator sync
        ↓ status = 'ready_for_personas' + ranked_companies stored
    set_resuming()        — called when orchestrator resumes with personas
        ↓ status = 'resuming'
    set_completed()       — called after Phase 2 finishes successfully
        ↓ status = 'completed'
    set_failed()          — called if pipeline_error was set or an exception escaped
        ↓ status = 'failed' + error_message stored

Read operations:
    get()                 — fetch full campaign row by campaign_id
    get_pending_for_user() — fetch campaigns ready for persona phase (orchestrator sync)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


# ── Status constants ──────────────────────────────────────────────────────────
# Import these instead of using raw strings to avoid typos.

class CampaignStatus:
    RUNNING             = "running"
    READY_FOR_PERSONAS  = "ready_for_personas"
    # Backward-compat alias (old human-approval naming)
    AWAITING_APPROVAL   = READY_FOR_PERSONAS
    RESUMING            = "resuming"
    COMPLETED           = "completed"
    FAILED              = "failed"


# ── Manager ───────────────────────────────────────────────────────────────────

class CampaignStatusManager:
    """
    Manages campaign lifecycle state in the campaigns table.

    Usage:
        manager = CampaignStatusManager(db_url=os.environ["DATABASE_URL"])

        # When campaign starts:
        manager.create(campaign_id="abc-123", user_id="user-456",
                       icp_description="...")

        # After company ranking pauses for orchestrator sync:
        manager.set_ready_for_personas("abc-123", ranked_companies=[...])

        # On app reopen — check if anything is pending:
        pending = manager.get_pending_for_user("user-456")

        # After orchestrator resumes with personas:
        manager.set_resuming("abc-123")

        # After Phase 2 completes:
        manager.set_completed("abc-123")
    """

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url or os.environ["DATABASE_URL"]

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._db_url, row_factory=dict_row)

    # ── Write operations ──────────────────────────────────────────────────

    def create(
        self,
        campaign_id: str,
        user_id: str,
        icp_description: Optional[str] = None,
    ) -> None:
        """
        Insert a new campaign row with status = 'running'.
        Called at the very start, before pipeline.invoke() is called.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO campaigns (campaign_id, user_id, status, icp_description)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (campaign_id) DO NOTHING
                    """,
                    (campaign_id, user_id, CampaignStatus.RUNNING, icp_description),
                )
            conn.commit()

    def set_ready_for_personas(
        self,
        campaign_id: str,
        ranked_companies: List[Dict[str, Any]],
    ) -> None:
        """
        Mark campaign as paused after company ranking — orchestrator will
        fetch personas and resume. No human approval wait.

        Stores ranked_companies so status polls can restore UI state.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE campaigns
                    SET status           = %s,
                        ranked_companies = %s
                    WHERE campaign_id = %s
                    """,
                    (
                        CampaignStatus.READY_FOR_PERSONAS,
                        json.dumps(ranked_companies),
                        campaign_id,
                    ),
                )
            conn.commit()

    # Backward-compat alias
    def set_awaiting_approval(
        self,
        campaign_id: str,
        ranked_companies: List[Dict[str, Any]],
    ) -> None:
        self.set_ready_for_personas(campaign_id, ranked_companies)

    def set_resuming(self, campaign_id: str) -> None:
        """
        Mark campaign as actively resuming (personas injected, Node 5 running).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE campaigns SET status = %s WHERE campaign_id = %s",
                    (CampaignStatus.RESUMING, campaign_id),
                )
            conn.commit()

    def set_completed(self, campaign_id: str, usage: Optional[Dict[str, Any]] = None) -> None:
        """
        Mark campaign as fully completed after Phase 2 finishes.
        Optionally store usage tracking data.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE campaigns
                    SET status           = %s,
                        ranked_companies = NULL,
                        usage            = %s
                    WHERE campaign_id = %s
                    """,
                    (CampaignStatus.COMPLETED, json.dumps(usage) if usage else None, campaign_id),
                )
            conn.commit()

    def set_failed(self, campaign_id: str, error_message: str) -> None:
        """
        Mark campaign as failed, storing the error for debugging.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE campaigns
                    SET status        = %s,
                        error_message = %s
                    WHERE campaign_id = %s
                    """,
                    (CampaignStatus.FAILED, error_message, campaign_id),
                )
            conn.commit()

    # ── Read operations ───────────────────────────────────────────────────

    def get(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single campaign row by campaign_id.
        Returns None if not found.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM campaigns WHERE campaign_id = %s",
                    (campaign_id,),
                )
                return cur.fetchone()

    def get_pending_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Fetch campaigns paused after company ranking (ready for persona phase).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT campaign_id,
                           user_id,
                           status,
                           ranked_companies,
                           icp_description,
                           created_at,
                           updated_at
                    FROM   campaigns
                    WHERE  user_id = %s
                    AND    status  = %s
                    ORDER  BY created_at DESC
                    """,
                    (user_id, CampaignStatus.READY_FOR_PERSONAS),
                )
                return cur.fetchall()

    def get_all_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all campaigns for a user, all statuses, newest first.
        Useful for a campaign history / dashboard view.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT campaign_id,
                           user_id,
                           status,
                           icp_description,
                           error_message,
                           created_at,
                           updated_at
                    FROM   campaigns
                    WHERE  user_id = %s
                    ORDER  BY created_at DESC
                    """,
                    (user_id,),
                )
                return cur.fetchall()