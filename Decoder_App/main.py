"""DECODER (insurance side) - FastAPI server: audit, video-signature verification, data retention."""
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import Client, create_client

from config import SUPABASE_URL, SUPABASE_KEY
from core.integrity_validator import compare_video_signatures, latest_session_records

app = FastAPI(title="Decoder - Insurance Verification")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_driver_records(driver_id: str) -> list[dict]:
    """Fetch every row (Supabase returns at most 1000 per request, so page through)."""
    rows, start = [], 0
    while True:
        r = (supabase.table("fingerprints").select("*").eq("driver_id", driver_id)
             .order("frame_index").range(start, start + 999).execute())
        batch = r.data or []
        rows += batch
        if len(batch) < 1000:
            return rows
        start += 1000


class VideoFrame(BaseModel):
    frame_index: int
    signatures: list[str]


class VerifyRequest(BaseModel):
    driver_id: str
    sensitivity: str = "normal"
    frames: list[VideoFrame]


@app.get("/api/audit/{driver_id}")
def audit_driver_sequence(driver_id: str):
    records = latest_session_records(get_driver_records(driver_id))
    if not records:
        raise HTTPException(404, "No fingerprint data found for this Driver ID.")
    return {"status": "success", "session_id": records[0]["session_id"], "total_frames": len(records)}


@app.post("/api/verify-video")
def verify_video(req: VerifyRequest):
    driver_id = req.driver_id.strip()
    if not driver_id:
        raise HTTPException(400, "Driver ID is required.")
    if not req.frames:
        raise HTTPException(400, "No frame indexes could be read from the video. It may not be a dashcam recording.")
    records = latest_session_records(get_driver_records(driver_id))
    if not records:
        raise HTTPException(404, "No trusted fingerprint data found for this Driver ID.")
    result = compare_video_signatures(records, [f.model_dump() for f in req.frames], req.sensitivity)
    return {"status": "success", "driver_id": driver_id, "session_id": records[0]["session_id"], **result}


@app.delete("/api/cleanup")
def cleanup_expired_data():
    """Delete records older than two hours (recorded_timestamp = capture time)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    response = supabase.table("fingerprints").delete().lt("recorded_timestamp", cutoff).execute()
    n = len(response.data or [])
    return {"status": "success", "message": f"Cleanup complete. {n} expired record(s) were purged.", "deleted_count": n}


app.mount("/", StaticFiles(directory="static", html=True), name="static")