"""
Decoder - integrity validation.

Two layers:
1. Cloud record check: SHA-256(driver|session|index|captured_at|signature) must equal the stored
   fingerprint_hash, so a cloud row that was edited after upload is detected.
2. Content check: the perceptual signature recomputed from the submitted video must match the
   stored one. A signature is 64 blocks x (mean luminance, edge detail), 2 hex chars each.
   Blur lowers detail; covering/replacing/editing changes luminance, so altered blocks are located.
   A frame passes if at most `max_cells` blocks differ (tolerates compression noise).
"""
import hashlib
from typing import Any

GRID = 8
PROFILES = {
    "strict":  {"lum_tol": 12, "detail_ratio": 0.70, "max_cells": 0},
    "normal":  {"lum_tol": 20, "detail_ratio": 0.55, "max_cells": 1},
    "lenient": {"lum_tol": 30, "detail_ratio": 0.40, "max_cells": 3},
}
DETAIL_FLOOR = 24   # blocks flatter than this (scaled units) cannot meaningfully be "blurred"
DETAIL_ADDED = 40   # extra detail beyond 3x original + this counts as added content


def chain_hash(driver_id, session_id, frame_index, captured_at, signature) -> str:
    raw = f"{driver_id}|{session_id}|{frame_index}|{captured_at}|{signature}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cells(sig: str) -> list[tuple[int, int]]:
    return [(int(sig[i:i + 2], 16), int(sig[i + 2:i + 4], 16)) for i in range(0, GRID * GRID * 4, 4)]


def altered_cells(expected: str, submitted: str, p: dict) -> list[int]:
    out = []
    for i, ((le, de), (ls, ds)) in enumerate(zip(_cells(expected), _cells(submitted))):
        brightness_changed = abs(le - ls) > p["lum_tol"]
        smoothed = de >= DETAIL_FLOOR and ds < de * p["detail_ratio"]
        added = ds > de * 3 + DETAIL_ADDED
        if brightness_changed or smoothed or added:
            out.append(i)
    return out


def _regions(cells: list[int]) -> str:
    names = [f"r{c // GRID + 1}c{c % GRID + 1}" for c in cells[:8]]
    return ", ".join(names) + ("..." if len(cells) > 8 else "")


def latest_session_records(rows: list[dict]) -> list[dict]:
    rows = [r for r in rows if r.get("session_id") and r.get("signature")]
    if not rows:
        return []
    sid = max(rows, key=lambda r: r["recorded_timestamp"])["session_id"]
    return sorted((r for r in rows if r["session_id"] == sid), key=lambda r: r["frame_index"])


def compare_video_signatures(records: list[dict], frames: list[dict], sensitivity: str = "normal") -> dict[str, Any]:
    p = PROFILES.get(sensitivity, PROFILES["normal"])
    submitted: dict[int, list[str]] = {}   # frame index -> candidate signatures (first frames carrying that index)
    for f in frames:
        sigs = [s.lower() for s in f["signatures"] if len(s) == GRID * GRID * 4]
        if sigs:
            submitted.setdefault(f["frame_index"], sigs)

    matching, mismatches, missing = 0, [], []
    noise_floor = 0  # most blocks changed in any frame that still passed
    expected_ids = set()
    for r in records:
        idx, sig = r["frame_index"], (r.get("signature") or "").lower()
        expected_ids.add(idx)
        if chain_hash(r["driver_id"], r["session_id"], idx, r["captured_at"], sig) != r["fingerprint_hash"].lower():
            mismatches.append({"frame_index": idx, "status": "CLOUD_RECORD_INCONSISTENT",
                               "detail": "Stored record fails its SHA-256 chain check."})
            continue
        if idx not in submitted:
            missing.append({"frame_index": idx, "status": "MISSING_FRAME",
                            "detail": "Frame not found in submitted video."})
            continue
        # Best match among the candidates: tolerates sampling a few frames late, but an edit that alters
        # every frame of that second still fails.
        alt = min((altered_cells(sig, c, p) for c in submitted[idx]), key=len)
        if len(alt) <= p["max_cells"]:
            matching += 1
            noise_floor = max(noise_floor, len(alt))
        else:
            mismatches.append({"frame_index": idx, "status": "CONTENT_ALTERED",
                               "altered_cells": alt,
                               "detail": f"{len(alt)} of {GRID * GRID} blocks changed ({_regions(alt)})"})

    unexpected = [{"frame_index": i, "status": "UNEXPECTED_FRAME",
                   "detail": "Frame index not present in cloud records."}
                  for i in sorted(submitted) if i not in expected_ids]
    total = len(records)
    return {
        "is_valid": total > 0 and matching == total and not unexpected,
        "total_expected": total,
        "total_submitted": len(submitted),
        "matching_frames": matching,
        "mismatched_frames": len(mismatches),
        "missing_frames": len(missing),
        "unexpected_frames": len(unexpected),
        "reliability_score": round(matching / total * 100, 2) if total else 0.0,
        "sensitivity": sensitivity,
        "noise_floor": noise_floor,
        "worst_altered_cells": max([len(m.get("altered_cells", [])) for m in mismatches] + [0]),
        "mismatches": mismatches,
        "missing": missing,
        "unexpected": unexpected,
    }