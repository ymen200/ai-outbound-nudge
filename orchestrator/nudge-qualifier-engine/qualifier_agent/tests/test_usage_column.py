"""
tests/test_usage_column.py
───────────────────────────
Check if the usage column exists in the campaigns table and test writing to it.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(ROOT_DIR) / ".env")

import psycopg
from psycopg.rows import dict_row
import json


def check_usage_column():
    """Check if the usage column exists in the campaigns table."""
    print("\n--- Checking usage column in campaigns table ---")
    
    db_url = os.environ.get("DATABASE_URL")
    conn = psycopg.connect(db_url, row_factory=dict_row)
    
    try:
        with conn.cursor() as cur:
            # Check if usage column exists
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'campaigns' 
                AND column_name = 'usage';
            """)
            result = cur.fetchone()
            
            if result:
                print(f"  ✓ usage column exists: {result}")
            else:
                print(f"  ✗ usage column does NOT exist")
                print(f"  Available columns:")
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'campaigns'
                    ORDER BY ordinal_position;
                """)
                columns = cur.fetchall()
                for col in columns:
                    print(f"    - {col['column_name']}: {col['data_type']}")
                
                # Add the column if it doesn't exist
                print(f"\n  Adding usage column...")
                cur.execute("""
                    ALTER TABLE campaigns 
                    ADD COLUMN usage JSONB;
                """)
                conn.commit()
                print(f"  ✓ usage column added successfully")
                
    finally:
        conn.close()


def test_usage_write():
    """Test writing usage data to the campaigns table."""
    print("\n--- Testing usage data write ---")
    
    db_url = os.environ.get("DATABASE_URL")
    conn = psycopg.connect(db_url, row_factory=dict_row)
    
    try:
        # Create a test campaign
        test_campaign_id = "test-usage-column-123"
        
        with conn.cursor() as cur:
            # Insert test campaign
            cur.execute("""
                INSERT INTO campaigns (campaign_id, user_id, status, icp_description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (campaign_id) DO UPDATE 
                SET status = EXCLUDED.status, icp_description = EXCLUDED.icp_description
            """, (test_campaign_id, "test-user", "running", "Test for usage column"))
            conn.commit()
            
            # Test writing usage data
            test_usage = {
                "campaign_id": test_campaign_id,
                "per_node": [
                    {
                        "node_name": "test_node",
                        "llm_calls": 1,
                        "tokens_in": 100,
                        "tokens_out": 50,
                        "total_tokens": 150
                    }
                ],
                "combined": {
                    "total_tokens": 150,
                    "total_tokens_in": 100,
                    "total_tokens_out": 50,
                    "total_llm_calls": 1
                },
                "errors": []
            }
            
            cur.execute("""
                UPDATE campaigns
                SET usage = %s
                WHERE campaign_id = %s
            """, (json.dumps(test_usage), test_campaign_id))
            conn.commit()
            
            # Read back the usage data
            cur.execute("""
                SELECT usage FROM campaigns WHERE campaign_id = %s
            """, (test_campaign_id,))
            result = cur.fetchone()
            
            if result and result.get('usage'):
                print(f"  ✓ Usage data written and read back successfully")
                print(f"  Stored usage: {json.dumps(result['usage'], indent=2)}")
            else:
                print(f"  ✗ Failed to read back usage data")
                print(f"  Result: {result}")
            
            # Clean up
            cur.execute("""
                DELETE FROM campaigns WHERE campaign_id = %s
            """, (test_campaign_id,))
            conn.commit()
            print(f"  ✓ Test campaign cleaned up")
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  USAGE COLUMN DIAGNOSTIC")
    print("=" * 70)
    
    check_usage_column()
    test_usage_write()
    
    print("\n" + "=" * 70)
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 70)
