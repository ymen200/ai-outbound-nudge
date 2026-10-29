"""Copy all orchestrator tables from SQLite into PostgreSQL."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.store import CampaignStore
from app.store.connection import postgres_connection

TABLES_IN_ORDER = [
    "campaigns",
    "artifacts",
    "final_packages",
    "outreach_threads",
    "campaign_companies",
    "campaign_personas",
    "blacklist_entries",
    "campaign_weights",
    "token_usage",
    "user_campaign_inputs",
]


def _sqlite_tables(sqlite_path: Path) -> list[str]:
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [name for (name,) in rows if not name.startswith("sqlite_")]
    finally:
        conn.close()


def _sqlite_columns(sqlite_path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [row[1] for row in rows]
    finally:
        conn.close()


def migrate(sqlite_path: Path, truncate: bool = False) -> None:
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    pg_store = CampaignStore()
    if not pg_store.uses_postgres:
        raise SystemExit("PostgreSQL is not configured as the active backend.")

    sqlite_tables = set(_sqlite_tables(sqlite_path))
    print(f"Source SQLite: {sqlite_path}")
    print(f"Target PostgreSQL: {settings.postgres_db} @ {settings.postgres_host}:{settings.postgres_port}")
    print(f"SSH tunnel: {'enabled' if settings.ssh_tunnel_enabled else 'disabled'}")

    with postgres_connection() as pg_conn:
        pg_cur = pg_conn.cursor()
        if truncate:
            print("Truncating existing PostgreSQL tables...")
            for table in reversed(TABLES_IN_ORDER):
                pg_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')

        pg_cur.execute("SET session_replication_role = replica")

        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        try:
            for table in TABLES_IN_ORDER:
                if table not in sqlite_tables:
                    print(f"  skip {table} (not in SQLite)")
                    continue

                columns = _sqlite_columns(sqlite_path, table)
                rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
                if not rows:
                    print(f"  {table}: 0 rows")
                    continue

                placeholders = ", ".join(["%s"] * len(columns))
                col_list = ", ".join(f'"{c}"' for c in columns)
                insert_sql = (
                    f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
                    f"ON CONFLICT DO NOTHING"
                )

                copied = 0
                for row in rows:
                    values = [row[c] for c in columns]
                    pg_cur.execute(insert_sql, values)
                    copied += pg_cur.rowcount
                print(f"  {table}: copied {copied}/{len(rows)} rows")
        finally:
            sqlite_conn.close()

        pg_cur.execute("SET session_replication_role = DEFAULT")

    print("Migration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        default=str(settings.database_path),
        help="Path to the source orchestrator.db file",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing PostgreSQL rows before copying",
    )
    args = parser.parse_args()
    migrate(Path(args.sqlite_path), truncate=args.truncate)


if __name__ == "__main__":
    main()
