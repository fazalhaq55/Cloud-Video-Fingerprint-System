"""
Cloud-Based Video Fingerprint Collection System
Diagnostic script: Tests the insurance-side integrity validation.
"""
import os
from supabase import create_client, Client
from Decoder_App.config import SUPABASE_URL, SUPABASE_KEY
from core.integrity_validator import validate_fingerprint_integrity
from core.file_handler import load_and_validate_fingerprints

def run_integrity_tests():
    print("Initializing Supabase Client for Insurance Validation...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. Test with a VALID fingerprint (grabbing the first one from our test file)
    test_filepath = "test_fingerprints.txt"
    if not os.path.exists(test_filepath):
        print(f"Error: {test_filepath} not found.")
        return
        
    valid_hashes = load_and_validate_fingerprints(test_filepath)
    authentic_hash = valid_hashes[0]
    
    print("\n--- Test 1: Authentic Video Submission ---")
    print(f"Checking Hash: {authentic_hash[:15]}...")
    result1 = validate_fingerprint_integrity(supabase, authentic_hash)
    print(f"Status: {result1['message']}")
    if result1['is_valid']:
        print(f"Timestamp verified: {result1['recorded_timestamp']}")
        
    # 2. Test with an INVALID/TAMPERED fingerprint
    # A fake 64-character hash simulating a manipulated video frame
    tampered_hash = "f" * 64
    
    print("\n--- Test 2: Tampered Video Submission ---")
    print(f"Checking Hash: {tampered_hash[:15]}...")
    result2 = validate_fingerprint_integrity(supabase, tampered_hash)
    print(f"Status: {result2['message']}")

if __name__ == "__main__":
    run_integrity_tests()