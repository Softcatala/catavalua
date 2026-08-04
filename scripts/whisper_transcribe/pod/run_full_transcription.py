#!/usr/bin/env python3
"""
Runs batched whisper-large-v3-turbo transcription (see ../whisper_engine.py)
over every clip in ../../../data/whisper_transcribe/clips_to_transcribe.tsv
(built by select_clips.py — tier-0, not-flagged-non-Catalan clips only),
reading audio from locally-downloaded tar files (download_tars.sh) instead
of one HTTP request per clip.

Idempotent + interruptible: writes results incrementally (flushed after
every batch) to --out, and on startup skips any clip_id already present
there — safe to Ctrl+C/kill at any point and re-run to resume exactly
where it left off. Mirrors scripts/language_id/pod/run_full_detection.py's
structure.

Usage:
  python pod/run_full_transcription.py --tar-dir ~/tars --out /path/to/persistent/storage/whisper_transcriptions.tsv
  # run pilot_transcribe.py first (no pod needed) to sanity-check output quality
"""
import argparse
import csv
import io
import logging
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent))
from paths import CLIPS_TO_TRANSCRIBE_TSV, LANGUAGE, WHISPER_MODEL_ID  # noqa: E402
from local_audio import read_local_audio  # noqa: E402
import whisper_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("run_full_transcription")

FIELDNAMES = ["clip_id", "duration", "text", "beam_size"]


def load_todo_rows() -> list[dict]:
    with CLIPS_TO_TRANSCRIBE_TSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def already_processed(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    with out_path.open(newline="", encoding="utf-8") as f:
        return {r["clip_id"] for r in csv.DictReader(f, delimiter="\t")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tar-dir", required=True, help="directory with locally-downloaded audio-N.tar files")
    parser.add_argument("--out", required=True, help="output TSV path (appended to incrementally, resumable)")
    parser.add_argument("--device", default="cuda:0", help="cuda:0 or cpu (default cuda:0)")
    parser.add_argument("--compute-type", default=None, help="default: float16 on cuda, int8 on cpu")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="only process the first N remaining clips (testing)")
    parser.add_argument("--cache-dir", default="/root/.model_cache")
    args = parser.parse_args()

    import ctranslate2
    if args.device.startswith("cuda") and ctranslate2.get_cuda_device_count() == 0:
        log.warning("CUDA requested but not available — falling back to CPU")
        args.device = "cpu"

    if not CLIPS_TO_TRANSCRIBE_TSV.exists():
        log.error("%s not found — run select_clips.py first", CLIPS_TO_TRANSCRIBE_TSV)
        return

    tar_dir = Path(args.tar_dir)
    out_path = Path(args.out)

    rows = load_todo_rows()
    skip_ids = already_processed(out_path)
    log.info("%d clips already processed, skipping", len(skip_ids))

    todo = [r for r in rows if r["clip_id"] not in skip_ids]
    if args.limit:
        todo = todo[: args.limit]
    log.info("%d clips to process", len(todo))

    if not todo:
        log.info("nothing to do")
        return

    compute_type = args.compute_type or whisper_engine.default_compute_type(args.device)
    log.info("loading %s (device=%s, compute_type=%s, language=%s)...", WHISPER_MODEL_ID, args.device, compute_type, LANGUAGE)
    wm, tokenizer = whisper_engine.load_model(WHISPER_MODEL_ID, args.device, compute_type, args.cache_dir, LANGUAGE)

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
            audios, ok_rows = [], []
            for r in batch:
                try:
                    entry = {"tar_file": int(r["tar_file"]), "tar_offset": int(r["tar_offset"]), "tar_size": int(r["tar_size"])}
                    raw = read_local_audio(tar_dir, entry)
                    audio, sr = sf.read(io.BytesIO(raw))
                    if sr != 16000:
                        raise ValueError(f"unexpected sample rate {sr}")
                    audios.append(audio)
                    ok_rows.append(r)
                except Exception as e:
                    log.warning("%s: read failed: %s", r["clip_id"][:8], e)

            if not audios:
                continue

            texts = whisper_engine.transcribe_batch(wm, tokenizer, audios, beam_size=args.beam_size)

            for r, text in zip(ok_rows, texts):
                writer.writerow({
                    "clip_id": r["clip_id"],
                    "duration": r.get("duration", ""),
                    "text": text,
                    "beam_size": args.beam_size,
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
