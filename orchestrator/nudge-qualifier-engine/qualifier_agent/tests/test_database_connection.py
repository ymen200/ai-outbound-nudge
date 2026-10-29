"""
tests/test_database_connection.py
─────────────────────────────────
Database connectivity diagnostic script.

Tests:
  1. Environment variable loading
  2. Connection string parsing
  3. Direct database connection
  4. Simple query execution
  5. Connection pooler vs direct port comparison

Usage:
    python qualifier_agent/tests/test_database_connection.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv

# Load .env file - it's in the qualifier_agent directory
env_path = Path(ROOT_DIR) / ".env"
load_dotenv(dotenv_path=env_path)


def test_environment_variables():
    """Test that required environment variables are set."""
    print("\n--- Test 1: Environment Variables ---")
    
    db_url = os.environ.get("DATABASE_URL")
    groq_key = os.environ.get("GROQ_API_KEY")
    
    print(f"  DATABASE_URL set: {bool(db_url)}")
    print(f"  GROQ_API_KEY set: {bool(groq_key)}")
    
    if db_url:
        # Mask the password for security
        masked_url = db_url.replace(db_url.split(':')[2].split('@')[0], '***')
        print(f"  DB URL (masked): {masked_url}")
    
    assert db_url, "DATABASE_URL is not set"
    assert groq_key, "GROQ_API_KEY is not set"
    
    print("  ✓ Environment variables are set correctly")
    return db_url


def test_connection_string_parsing(db_url: str):
    """Test that the connection string can be parsed correctly."""
    print("\n--- Test 2: Connection String Parsing ---")
    
    try:
        # Parse the connection string
        if db_url.startswith("postgresql://"):
            parts = db_url.replace("postgresql://", "").split("@")
            if len(parts) == 2:
                user_pass, host_port_db = parts
                user = user_pass.split(":")[0]
                host = host_port_db.split(":")[0]
                port = host_port_db.split(":")[1].split("/")[0]
                db = host_port_db.split("/")[-1]
                
                print(f"  User: {user}")
                print(f"  Host: {host}")
                print(f"  Port: {port}")
                print(f"  Database: {db}")
                
                # Check if using pooler port (6543) vs direct port (5432)
                if port == "6543":
                    print("  ⚠ WARNING: Using pooler port (6543)")
                    print("    Pooler may have connection limits or timeouts")
                    print("    Consider using direct port (5432) for testing")
                elif port == "5432":
                    print("  ✓ Using direct port (5432)")
                
                return True
    except Exception as e:
        print(f"  ✗ Failed to parse connection string: {e}")
        return False
    
    print("  ✓ Connection string parsed successfully")
    return True


def test_database_connection(db_url: str, timeout: int = 10):
    """Test direct database connection with timeout."""
    print(f"\n--- Test 3: Database Connection (timeout={timeout}s) ---")
    
    try:
        import psycopg
        
        print(f"  Attempting to connect to database...")
        start_time = time.time()
        
        conn = psycopg.connect(db_url, connect_timeout=timeout)
        
        elapsed = time.time() - start_time
        print(f"  ✓ Connected successfully in {elapsed:.2f}s")
        
        # Get connection info
        print(f"  Server version: {conn.info.server_version}")
        print(f"  Database: {conn.info.dbname}")
        print(f"  User: {conn.info.user}")
        print(f"  Host: {conn.info.host}")
        print(f"  Port: {conn.info.port}")
        
        conn.close()
        print(f"  ✓ Connection closed successfully")
        
        return True
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ✗ Connection failed after {elapsed:.2f}s: {e}")
        
        # Provide troubleshooting tips
        if "timeout" in str(e).lower():
            print("\n  Troubleshooting tips for timeout:")
            print("    1. Check your internet connection")
            print("    2. Verify Supabase project is active (not paused)")
            print("    3. Check if firewall is blocking port 5432")
            print("    4. Try using direct port (5432) instead of pooler (6543)")
            print("    5. Verify Supabase region is accessible from your location")
        elif "authentication" in str(e).lower() or "password" in str(e).lower():
            print("\n  Troubleshooting tips for authentication:")
            print("    1. Verify database password is correct")
            print("    2. Check if database user has proper permissions")
            print("    3. Ensure connection string format is correct")
        
        return False


def test_simple_query(db_url: str):
    """Test a simple query execution."""
    print("\n--- Test 4: Simple Query Execution ---")
    
    try:
        import psycopg
        from psycopg.rows import dict_row
        
        conn = psycopg.connect(db_url, row_factory=dict_row)
        
        # Test a simple query
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            result = cur.fetchone()
            print(f"  PostgreSQL version: {result.get('version', 'N/A')}")
            
            # Check if campaigns table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'campaigns'
                );
            """)
            table_exists = cur.fetchone()
            print(f"  campaigns table exists: {table_exists}")
            
            if table_exists:
                # Count campaigns
                cur.execute("SELECT COUNT(*) as count FROM campaigns;")
                count = cur.fetchone()
                print(f"  Total campaigns in database: {count.get('count', 0)}")
        
        conn.close()
        print("  ✓ Query executed successfully")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Query failed: {e}")
        return False


def test_connection_pooler_vs_direct(db_url: str):
    """Test connection using pooler vs direct port."""
    print("\n--- Test 5: Pooler vs Direct Port Comparison ---")
    
    # Extract base connection string
    if "postgresql://" in db_url:
        base = db_url.replace("postgresql://", "")
        user_pass = base.split("@")[0]
        host_db = base.split("@")[1]
        host = host_db.split(":")[0]
        db = host_db.split("/")[-1]
        
        # Test direct port (5432)
        direct_url = f"postgresql://{user_pass}@{host}:5432/{db}"
        print(f"  Testing direct port (5432)...")
        direct_ok = test_database_connection(direct_url, timeout=5)
        
        # Test pooler port (6543) 
        pooler_url = f"postgresql://{user_pass}@{host}:6543/{db}"
        print(f"  Testing pooler port (6543)...")
        pooler_ok = test_database_connection(pooler_url, timeout=5)
        
        print(f"\n  Results:")
        print(f"    Direct port (5432): {'✓' if direct_ok else '✗'}")
        print(f"    Pooler port (6543): {'✓' if pooler_ok else '✗'}")
        
        if direct_ok and not pooler_ok:
            print(f"\n  Recommendation: Use direct port (5432) in DATABASE_URL")
            print(f"  Change your .env file to use port 5432 instead of 6543")
        elif pooler_ok and not direct_ok:
            print(f"\n  Recommendation: Use pooler port (6543) in DATABASE_URL")
            print(f"  Change your .env file to use port 6543 instead of 5432")
        elif direct_ok and pooler_ok:
            print(f"\n  Both ports work - either can be used")
        
        return direct_ok or pooler_ok
    
    return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  DATABASE CONNECTIVITY DIAGNOSTIC")
    print("=" * 70)
    
    try:
        # Test 1: Environment variables
        db_url = test_environment_variables()
        
        # Test 2: Connection string parsing
        test_connection_string_parsing(db_url)
        
        # Test 3: Database connection
        if test_database_connection(db_url, timeout=10):
            # Test 4: Simple query
            test_simple_query(db_url)
        else:
            print("\n  ⚠ Skipping query test due to connection failure")
            print("  Trying pooler vs direct port comparison...")
            test_connection_pooler_vs_direct(db_url)
        
        print("\n" + "=" * 70)
        print("  DIAGNOSTIC COMPLETE")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n  ✗ Diagnostic failed with error: {e}")
        import traceback
        traceback.print_exc()
