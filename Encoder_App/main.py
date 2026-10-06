"""ENCODER (driver side) - FastAPI server that receives signed frame records and stores them in Supabase."""
import hashlib
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY

app = FastAPI(title="Encoder - Dashcam Simulator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SIG_RE = re.compile(r"^[0-9a-f]{256}$")


class FrameData(BaseModel):
    driver_id: str
    session_id: str
    frame_index: int
    captured_at: str        # ISO timestamp taken on the phone when the frame was captured
    signature: str          # perceptual signature of the frame (256 hex chars)
    fingerprint_hash: str   # SHA-256(driver|session|index|captured_at|signature)


def chain_hash(driver_id, session_id, frame_index, captured_at, signature) -> str:
    raw = f"{driver_id}|{session_id}|{frame_index}|{captured_at}|{signature}"
    return hashlib.sha256(raw.encode()).hexdigest()


@app.post("/api/transmit")
def transmit_hash(d: FrameData):
    signature = d.signature.lower()
    if not SIG_RE.fullmatch(signature):
        raise HTTPException(400, "Invalid signature format.")
    try:
        datetime.fromisoformat(d.captured_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid captured_at timestamp.")
    # Transport integrity: reject records whose hash does not match their content.
    if chain_hash(d.driver_id, d.session_id, d.frame_index, d.captured_at, signature) != d.fingerprint_hash.lower():
        raise HTTPException(400, "fingerprint_hash does not match the record content.")

    payload = {
        "driver_id": d.driver_id,
        "session_id": d.session_id,
        "frame_index": d.frame_index,
        "captured_at": d.captured_at,
        "recorded_timestamp": d.captured_at,
        "signature": signature,
        "fingerprint_hash": d.fingerprint_hash.lower(),
    }
    try:
        # upsert: a retry after a network drop cannot create duplicates
        response = supabase.table("fingerprints").upsert(
            payload, on_conflict="driver_id,session_id,frame_index").execute()
        if not response.data:
            raise RuntimeError("empty response")
        return {"status": "success", "id": response.data[0]["id"]}
    except Exception as e:
        print(f"Network drop: cannot store frame {d.frame_index} ({e})")
        raise HTTPException(503, "Offline: cannot reach the cloud ledger.")


app.mount("/", StaticFiles(directory="static", html=True), name="static")