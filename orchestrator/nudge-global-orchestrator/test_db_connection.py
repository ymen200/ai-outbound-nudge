"""Quick test: verify PostgreSQL is reachable through the project's SSH tunnel."""

from app.store.connection import postgres_connection

try:
    with postgres_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT version()")
        print("DB Connected! PostgreSQL version:", cur.fetchone()[0])

        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"Found {len(tables)} tables:", tables if tables else "(empty database)")
except Exception as e:
    print("Connection failed:", e)
