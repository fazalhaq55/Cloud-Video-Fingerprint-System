"""
Cloud-Based Video Fingerprint Collection System
Diagnostic script: Tests persistent cloud connection and write/read operations with Supabase.
"""

from datetime import datetime, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

# Reference/Attribution: Official supabase-py client (https://github.com/supabase/supabase-py)
def test_cloud_connection():
    print("[1/4] Connecting to Supabase Cloud...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("      Connected successfully.")

    # Generate a dummy SHA-256 hash string for testing
    dummy_hash = "a" * 64
    current_time = datetime.now(timezone.utc).isoformat()

    print("[2/4] Testing INSERT into 'fingerprints' table...")
    insert_response = supabase.table("fingerprints").insert({
        "fingerprint_hash": dummy_hash,
        "recorded_timestamp": current_time
    }).execute()

    if not insert_response.data:
        raise RuntimeError("Insert operation failed. No data returned from Supabase.")

    inserted_record = insert_response.data[0]
    record_id = inserted_record["id"]
    print(f"      Inserted successfully with ID: {record_id}")

    print("[3/4] Testing SELECT query from 'fingerprints' table...")
    select_response = supabase.table("fingerprints").select("*").eq("id", record_id).execute()

    if not select_response.data:
        raise RuntimeError(f"Could not retrieve record ID {record_id} from Supabase.")
    print(f"      Verified record exists in Supabase: {select_response.data[0]['fingerprint_hash']}")

    print("[4/4] Cleaning up test record...")
    supabase.table("fingerprints").delete().eq("id", record_id).execute()
    print("      Cleanup complete.")

    print("\nCloud database integration test PASSED! Supabase is fully configured.")

if __name__ == "__main__":
    test_cloud_connection()