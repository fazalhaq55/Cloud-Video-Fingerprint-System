# Fingerprint distance and threshold evaluation

Evaluates the project's fingerprint against the metrics requested by Prof. Hammoudi.

## Run
    pip install -r requirements.txt          # ffmpeg must also be installed and on PATH
    python evaluate.py path/to/dashcam_evidence_<driver>_<session>.webm --out results

Use a **real recording from your Encoder** (at least ~20 s). Keep `decoder/` next to this folder: the script imports the
Decoder's block rule (`core/integrity_validator.py`) so the project's own method is evaluated too.

## What it does
1. Makes transformed copies with ffmpeg: **benign** (re-encode, rescale, +-5 % brightness, mild noise, must still match),
   **tamper** (small/large sticker, regional blur, full blur, must be rejected), **stress** (+-20 % brightness, strong noise,
   320x180, contrast, frame drop, 0.4 s time shift, 4 s cut; reported only).
2. Reads the frame-index barcode like the Decoder and takes the best of the first 5 frames per index.
3. Computes 18 distances per frame pair: aHash, dHash, pHash, wHash (Hamming and normalised), ssdeep, TLSH,
   project signature (L1, L2, cosine, altered-block count), 16x16 thumbnail (L1, L2, cosine).
4. Per metric: AUC, best threshold (max balanced accuracy of benign vs tamper + impostor), TPR/FPR, and the pass rate of every transformation.

## Outputs (in `--out`)
`thresholds.csv`, `robustness_pass_rates.csv`, `coverage.csv` (indexes found per transformation: frame loss / cut / shift),
`pairs.csv` (all raw distances), `distributions.png`.

## Important
`example_synthetic_run/` was produced on a **synthetic** video (`make_synthetic.py`) only to test the tool.
Do not quote those numbers in the report. Run the script on your own recording.
"Impostor" pairs compare a frame with another second of the same video; dashcam frames of one drive look alike, so this is a hard test.
