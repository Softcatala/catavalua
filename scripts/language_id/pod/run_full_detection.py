#!/usr/bin/env python3
"""
Runs the two-tier language-ID detection (see ../REPORT.md) over ALL clips
in the dataset, reading audio from locally-downloaded tar files
(download_tars.sh) instead of per-clip HTTP requests, with batched GPU
inference (batch_models.py).

Idempotent + interruptible: writes results incrementally (flushed after
every batch) to --out, and on startup skips any clip_id already present
there — safe to Ctrl+C/kill at any point and re-run to resume exactly
where it left off. Clips already in ../ground_truth.tsv or
../detect_sample.tsv (already hand-labeled/reviewed) are skipped entirely
— no need to re-score clips we already have a verdict for.

Usage:
  python run_full_detection.py --tar-dir /workspace/tars --out /workspace/full_detect.tsv
  # local correctness test (no GPU, no tar files) — see validate_batching.py instead
"""
import argparse
import csv
import io
import json
import logging
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent))
from paths import (  # noqa: E402
    STRICT_THRESHOLD, LOOSE_THRESHOLD, GROUND_TRUTH_TSV, DETECT_SAMPLE_TSV,
    CLIPS_TSV_FILE, TAR_INDEX_FILE,
)

sys.path.insert(0, str(Path(__file__).parent))
from local_audio import read_local_audio  # noqa: E402
from batch_models import load_mms, run_mms_batch, load_voxlingua, run_voxlingua_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("run_full_detection")

FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "p_ca_voxlingua", "p_ca_mms", "tier"]


def tier_for(p_v: float, p_m: float) -> int:
    if p_v < STRICT_THRESHOLD and p_m < STRICT_THRESHOLD:
        return 2
    if p_v < LOOSE_THRESHOLD or p_m < LOOSE_THRESHOLD:
        return 1
    return 0


def load_index() -> dict[str, dict]:
    return json.loads(TAR_INDEX_FILE.read_text())


def load_clips_rows() -> list[dict]:
    with CLIPS_TSV_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def already_processed(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    with out_path.open(newline="", encoding="utf-8") as f:
        return {r["clip_id"] for r in csv.DictReader(f, delimiter="\t")}


def already_labeled_elsewhere() -> set[str]:
    ids: set[str] = set()
    for path in (GROUND_TRUTH_TSV, DETECT_SAMPLE_TSV):
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                ids |= {r["clip_id"] for r in csv.DictReader(f, delimiter="\t")}
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tar-dir", required=True, help="directory with locally-downloaded audio-N.tar files")
    parser.add_argument("--out", required=True, help="output TSV path (appended to incrementally, resumable)")
    parser.add_argument("--device", default="cuda", help="cuda or cpu (default cuda)")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="only process the first N remaining clips (testing)")
    parser.add_argument("--cache-dir", default="/workspace/.model_cache")
    args = parser.parse_args()

    import torch
    if args.device == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA requested but not available — falling back to CPU")
        args.device = "cpu"

    tar_dir = Path(args.tar_dir)
    out_path = Path(args.out)

    index = load_index()
    rows = load_clips_rows()
    skip_ids = already_labeled_elsewhere() | already_processed(out_path)
    log.info("%d clips already labeled/processed, skipping", len(skip_ids))

    todo = [r for r in rows if r["clip_id"] in index and r["clip_id"] not in skip_ids]
    if args.limit:
        todo = todo[: args.limit]
    log.info("%d clips to process", len(todo))

    if not todo:
        log.info("nothing to do")
        return

    log.info("loading models (device=%s)...", args.device)
    mms_processor, mms_model, mms_ca_idx = load_mms(args.device, cache_dir=f"{args.cache_dir}/mms")
    vox_clf, vox_ca_idx = load_voxlingua(args.device, savedir=f"{args.cache_dir}/voxlingua")

    write_header = not out_path.exists()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    f = out_path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
    if write_header:
        writer.writeheader()
        f.flush()

    start = time.time()
    processed = 0
    try:
        for i in range(0, len(todo), args.batch_size):
            batch = todo[i : i + args.batch_size]
            audios = []
            ok_rows = []
            for r in batch:
                try:
                    raw = read_local_audio(tar_dir, index[r["clip_id"]])
                    audio, sr = sf.read(io.BytesIO(raw))
                    if sr != 16000:
                        raise ValueError(f"unexpected sample rate {sr}")
                    audios.append(audio)
                    ok_rows.append(r)
                except Exception as e:
                    log.warning("%s: read failed: %s", r["clip_id"][:8], e)

            if not audios:
                continue

            p_ca_mms = run_mms_batch(mms_processor, mms_model, mms_ca_idx, args.device, audios)
            p_ca_vox = run_voxlingua_batch(vox_clf, vox_ca_idx, args.device, audios)

            for r, p_v, p_m in zip(ok_rows, p_ca_vox, p_ca_mms):
                writer.writerow({
                    "clip_id": r["clip_id"],
                    "duration": r.get("duration", ""),
                    "yt_url": r.get("yt_url", ""),
                    "candidate_1": (r.get("candidate_1") or "")[:120],
                    "p_ca_voxlingua": round(p_v, 4),
                    "p_ca_mms": round(p_m, 4),
                    "tier": tier_for(p_v, p_m),
                })
            f.flush()
            processed += len(ok_rows)

            if processed % (args.batch_size * 10) < args.batch_size or i + args.batch_size >= len(todo):
                elapsed = time.time() - start
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = len(todo) - processed
                eta_h = remaining / rate / 3600 if rate > 0 else float("inf")
                log.info("%d/%d done (%.1f clips/sec, ETA %.1fh)", processed, len(todo), rate, eta_h)
    except KeyboardInterrupt:
        log.info("interrupted — %d clips written to %s this run, safe to re-run to resume", processed, out_path)
    finally:
        f.close()

    log.info("done: %d clips processed, written to %s", processed, out_path)


if __name__ == "__main__":
    main()
