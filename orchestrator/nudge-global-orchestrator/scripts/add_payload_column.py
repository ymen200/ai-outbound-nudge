from app.store.connection import postgres_connect_kwargs
import psycopg2
import sys

def main():
    kw = postgres_connect_kwargs()
    conn = psycopg2.connect(**kw)
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE outreach_threads ADD COLUMN IF NOT EXISTS payload_json JSONB")
        conn.commit()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='outreach_threads' AND column_name='payload'")
        if cur.fetchone():
            cur.execute("UPDATE outreach_threads SET payload_json = payload::jsonb WHERE payload IS NOT NULL AND payload_json IS NULL")
            conn.commit()
        print('OK')
    except Exception as e:
        print('ERROR', e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
