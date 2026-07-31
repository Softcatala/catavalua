#!/usr/bin/env python3
"""
Fast, concurrent alternative to `scripts/transcribe.py --post-index`.

Posts every entry in data/tar_index.json to POST /clips/:id/tar-index against
a given backend. Use this after a bulk clip-metadata import (e.g. from
clips.tsv) that didn't also carry over tar-index data, so clips show as
"audio not indexed" in the frontend despite having candidate transcriptions.

Unlike scripts/transcribe.py --post-index, this does NOT first page through
the enriched GET /clips listing to find which clip IDs exist (slow — that
endpoint does per-clip transcription/vote lookups, and for ~230k clips it
takes a very long time). POST /clips/:id/tar-index does a plain
`.update({clipId}, {...})` in ClipService, which is a silent no-op if the
clip doesn't exist — so it's safe to just post for every entry in the local
index directly, and errors are only ever real HTTP/network failures.

Usage:
  python scripts/post_tar_index_fast.py --api-url https://api.catvoice.internal.liam.cat
  python scripts/post_tar_index_fast.py --api-url https://catavalua.softcatala.org/api

Run `--build-index-only` (scripts/transcribe.py) first if data/tar_index.json
doesn't exist or is stale.
"""
import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

INDEX_FILE = Path(__file__).parent.parent / "data" / "tar_index.json"


def post_one(api_url: str, clip_id: str, entry: dict) -> str:
    payload = json.dumps({
        "tarFile": entry["tar_file"],
        "tarOffset": entry["tar_offset"],
        "tarSize": entry["tar_size"],
    }).encode()
    req = urllib.request.Request(
        f"{api_url}/clips/{clip_id}/tar-index",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return "ok"
    except Exception as e:
        return f"error:{e}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    if not INDEX_FILE.exists():
        print(f"No index found at {INDEX_FILE}. Run scripts/transcribe.py --build-index-only first.", file=sys.stderr)
        sys.exit(1)

    index = json.loads(INDEX_FILE.read_text())
    print(f"{len(index)} entries to post to {api_url}{' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    if args.dry_run:
        return

    done = ok = errors = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(post_one, api_url, cid, entry): cid for cid, entry in index.items()}
        for fut in as_completed(futures):
            result = fut.result()
            done += 1
            if result == "ok":
                ok += 1
            else:
                errors += 1
                if errors <= 20:
                    print(f"{futures[fut]}: {result}", file=sys.stderr)
            if done % 5000 == 0:
                elapsed = time.time() - start
                print(f"{done}/{len(index)} done ({ok} ok, {errors} errors) — {elapsed:.0f}s elapsed", file=sys.stderr)

    print(f"finished: {ok} ok, {errors} errors, {time.time()-start:.0f}s total", file=sys.stderr)


if __name__ == "__main__":
    main()
