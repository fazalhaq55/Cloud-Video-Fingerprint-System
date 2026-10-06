"""
Cloud-Based Video Fingerprint Collection System
Diagnostic script: Tests the real-time streaming engine.
"""

import asyncio
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from core.stream_engine import stream_fingerprints_to_cloud

async def main():
    print("Initializing Supabase Client...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    test_filepath = "test_fingerprints.txt"
    # Using a 0.5 second delay for testing purposes
    await stream_fingerprints_to_cloud(test_filepath, supabase, delay_seconds=0.5)

if __name__ == "__main__":
    asyncio.run(main())