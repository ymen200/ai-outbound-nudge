"""
setup_postgres_checkpointer.py
────────────────────────────────
One-time setup script: creates the tables PostgresSaver needs
(checkpoints, checkpoint_writes, etc.) in your hosted Postgres database.

Run this ONCE before using PostgresSaver for the first time, and again
any time you upgrade langgraph-checkpoint-postgres to a version with
schema changes.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
    python setup_postgres_checkpointer.py

Safe to re-run — .setup() is idempotent (uses CREATE TABLE IF NOT EXISTS
internally), so running this twice will not error or duplicate anything.
"""

import os
from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import load_dotenv

load_dotenv()


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it to your Postgres connection string (use the direct, "
            "non-pooled port if using Supabase) before running this script."
        )

    print(f"Connecting to Postgres...")
    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        print("Running checkpointer.setup() — creating required tables...")
        checkpointer.setup()
        print("Done. PostgresSaver tables are ready.")


if __name__ == "__main__":
    main()