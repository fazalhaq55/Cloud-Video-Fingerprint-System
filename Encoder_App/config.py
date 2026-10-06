"""
Cloud-Based Video Fingerprint Collection System
Configuration and Cloud Credentials Loader
"""

import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "Missing Supabase credentials! Please verify SUPABASE_URL and SUPABASE_KEY in your .env file."
    )