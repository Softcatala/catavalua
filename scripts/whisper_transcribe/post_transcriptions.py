#!/usr/bin/env python3
"""
Posts pod/run_full_transcription.py's output (data/whisper_transcribe/
whisper_transcriptions.tsv) to a running CatVoice backend as new
transcription candidates (origin="whisper-large-v3-turbo", see
apps/backend/src/domain/transcription.entity.ts), for issue #8.

Checks each clip already exists via GET /clips/:id before posting (same
safety pattern as scripts/infer_dialect.py's --apply — never let the
upsert silently create a new, sparse clip for a clip_id that isn't already
in that environment's DB). POST /transcriptions is idempotent by
(clipId, origin, text) on the backend side, so re-running this script after
an interruption is safe — already-posted rows just come back unchanged.

This only ADDS a new candidate transcription; it does not touch votes or
change which candidate the frontend currently shows as preferred (that's
resolveDimension()'s job, based on net votes — see apps/frontend/src/
voteUtils.ts). A fresh whisper-large-v3-turbo candidate starts at 0 votes,
same as any other, and needs evaluators to actually prefer it over time.

Usage:
  # Dry run (default): reports what would be posted, writes nothing.
  python scripts/whisper_transcribe/post_transcriptions.py --api-url http://localhost:3000

  # Actually post:
  python scripts/whisper_transcribe/post_transcriptions.py --api-url http://localhost:3000 --apply
"""
import argparse
import csv
import json
import logging
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import OUTPUT_TSV, ORIGIN, WHISPER_MODEL_ID  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("post_transcriptions")


def http_get_json(url: str, timeout: int = 15, retries: int = 3):
    delay = 5
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries:
                import time
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
        except Exception:
            if attempt < retries:
                import time
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise


def http_post_json(url: str, payload: dict, timeout: int = 15, retries: int = 3) -> dict:
    delay = 5
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt < retries:
                import time
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise e


def clip_exists(api_url: str, clip_id: str) -> bool:
    return http_get_json(f"{api_url}/clips/{clip_id}") is not None


def post_one(api_url: str, row: dict) -> str:
    # Whole body wrapped in one try/except — a bare, unhandled exception here
    # (e.g. a RemoteDisconnected from clip_exists, previously outside any
    # try block) propagates through the ThreadPoolExecutor future and kills
    # the entire batch via fut.result() in main()'s loop, rather than being
    # reported as a single row's error and letting the rest continue.
    clip_id = row["clip_id"]
    try:
        if not clip_exists(api_url, clip_id):
            return "skipped:no-such-clip"
        metadata = json.dumps({"model": WHISPER_MODEL_ID, "beam_size": row.get("beam_size")})
        http_post_json(f"{api_url}/transcriptions", {
            "clipId": clip_id,
            "origin": ORIGIN,
            "text": row["text"],
            "metadata": metadata,
        })
        return "posted"
    except Exception as e:
        return f"error:{e}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default=None, help=f"TSV to read (default {OUTPUT_TSV})")
    parser.add_argument("--api-url", default="http://localhost:3000")
    parser.add_argument("--apply", action="store_true", help="actually POST — without this, only reports what would happen")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="only process the first N rows (testing)")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else OUTPUT_TSV
    if not input_path.exists():
        log.error("%s not found — run pod/run_full_transcription.py first, or pass --input", input_path)
        return

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if args.limit:
        rows = rows[: args.limit]
    log.info("%d transcriptions in %s, target API: %s%s", len(rows), input_path, args.api_url, "" if args.apply else " (dry run — pass --apply to actually post)")

    if not args.apply:
        log.info("dry run — no requests made. Re-run with --apply when ready.")
        return

    posted = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(post_one, args.api_url, r): r["clip_id"] for r in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result == "posted":
                posted += 1
            elif result.startswith("skipped"):
                skipped += 1
            else:
                errors += 1
                log.warning("%s: %s", futures[fut][:8], result)
            if i % 200 == 0 or i == len(rows):
                log.info("%d/%d done (%d posted, %d skipped, %d errors)", i, len(rows), posted, skipped, errors)

    log.info("done: %d posted, %d skipped (clip not in this DB), %d errors", posted, skipped, errors)


if __name__ == "__main__":
    main()
