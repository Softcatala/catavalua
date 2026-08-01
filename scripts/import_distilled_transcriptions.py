#!/usr/bin/env python3
"""
Imports transcriptions from BSC-LT/distilled-catalan-youtube-speech into catvoice.

That dataset is an automatically-verified subset of softcatala/catalan-youtube-speech
(the same corpus catvoice already imports via transcribe.py): its `audio_id` is the
same clip_id UUID used everywhere else in this project, confirmed by cross-checking
sample rows against data/clips.tsv (matching duration + yt_url). So rows match
existing clips 1:1 with no fuzzy matching needed.

Each row's `normalized_text` is a transcription that two independently-trained ASR
models agreed on (or a third model resolved a word-count tie), so it's posted as a
new transcription candidate under origin 'distilled-bsc' — text is lowercased/
punctuation-stripped ("normalized"), same as the existing candidate_1/candidate_2
ASR fields, so it fits the same slot in the UI.

Only the metadata TSVs are needed — no audio download, since we already have audio
access for these clips via the original tar files.

Like infer_dialect.py's --apply step, this never creates new clips: it fetches the
full set of clip IDs already in the target DB and skips any row whose clip isn't
in it, so a partially-imported environment doesn't get sparse clip records.

POST /transcriptions is idempotent on (clipId, origin, text), so re-running is safe.

Usage:
  python scripts/import_distilled_transcriptions.py --api-url https://api.catvoice.internal.liam.cat
  python scripts/import_distilled_transcriptions.py --max 50 --dry-run
  python scripts/import_distilled_transcriptions.py --splits test,dev
  python scripts/import_distilled_transcriptions.py --concurrency 100
"""

import argparse
import csv
import json
import logging
import sys
import urllib.error
import urllib.request
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

csv.field_size_limit(sys.maxsize)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("import-distilled")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_BASE = "https://huggingface.co/datasets/BSC-LT/distilled-catalan-youtube-speech/resolve/main"
METADATA_FILES = {
    "test": "corpus/files/metadata_test.tsv",
    "dev": "corpus/files/metadata_dev.tsv",
    "perfect_matches": "corpus/files/metadata_perfect_matches.tsv",
    "word_count_matches": "corpus/files/metadata_word_count_matches.tsv",
}
ALL_SPLITS = list(METADATA_FILES.keys())

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "distilled"

ORIGIN = "distilled-bsc"

# ---------------------------------------------------------------------------
# HTTP helpers (same pattern as transcribe.py)
# ---------------------------------------------------------------------------

def http_get_json(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def http_post_json(url: str, payload: dict, timeout: int = 15, retries: int = 3) -> dict:
    delay = 5
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                log.warning("POST %s transient error (%s) — retrying in %ds…", url, e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
                last_exc = e
                continue
            raise
        except Exception as e:
            if attempt < retries:
                log.warning("POST %s error (%s) — retrying in %ds…", url, e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
                last_exc = e
                continue
            raise
    raise last_exc


CLIP_IDS_CACHE = CACHE_DIR / "clip_ids.json"


def fetch_all_clip_ids(api_url: str, use_cache: bool = True) -> set[str]:
    """Return the set of every clip ID already in the backend database.

    Paginating the full /clips list (100/page) takes ~10min against a DB with
    230k+ clips. Cached globally (not per api_url): every catvoice environment
    is imported from the same original clips.tsv, so their clip ID sets are
    expected to be identical — pass --refresh-cache (or use_cache=False) if
    that assumption ever needs re-checking against a specific environment.
    """
    cache_path = CLIP_IDS_CACHE
    if use_cache and cache_path.exists():
        ids = set(json.loads(cache_path.read_text()))
        log.info("Loaded %d clip IDs from cache (%s). Use --refresh-cache to re-fetch.", len(ids), cache_path)
        return ids

    ids: set[str] = set()
    page = 1
    limit = 100  # backend max
    while True:
        data = http_get_json(f"{api_url}/clips?search=&page={page}&limit={limit}")
        items = data.get("items", [])
        for item in items:
            ids.add(item["clip"]["clipId"])
        if len(items) < limit:
            break
        page += 1
        if page % 100 == 0:
            log.info("…fetched %d clip IDs so far", len(ids))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(sorted(ids)))
    log.info("Cached %d clip IDs to %s", len(ids), cache_path)
    return ids


def post_transcription(api_url: str, clip_id: str, text: str, metadata: dict) -> None:
    http_post_json(f"{api_url}/transcriptions", {
        "clipId": clip_id,
        "origin": ORIGIN,
        "text": text,
        "metadata": json.dumps(metadata),
    })


# ---------------------------------------------------------------------------
# Dataset fetching
# ---------------------------------------------------------------------------

def ensure_metadata_tsv(split: str) -> Path:
    dest = CACHE_DIR / f"{split}.tsv"
    if dest.exists():
        return dest
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{HF_BASE}/{METADATA_FILES[split]}"
    log.info("Downloading %s metadata (%s)…", split, url)
    tmp = dest.with_suffix(".tsv.part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    log.info("Saved %s", dest)
    return dest


def iter_split_rows(split: str):
    path = ensure_metadata_tsv(split)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield row


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _collect_tasks(splits: list[str], known_clip_ids: set[str], max_tasks: int) -> tuple[list[tuple[str, str, dict]], dict]:
    """Filter dataset rows down to (clip_id, text, metadata) tuples worth posting.

    Sequential and in-memory only (no network) — cheap enough to do up front so the
    concurrent posting phase below just has a flat list of work to fan out.
    """
    seen: set[str] = set()  # clip_ids already queued this run (dev overlaps perfect_matches)
    tasks: list[tuple[str, str, dict]] = []
    counters = {"total_rows": 0, "matched": 0, "skipped_no_clip": 0, "skipped_empty_text": 0, "skipped_dup": 0}

    for split in splits:
        log.info("=== split: %s ===", split)
        for row in iter_split_rows(split):
            if max_tasks and len(tasks) >= max_tasks:
                return tasks, counters
            counters["total_rows"] += 1

            clip_id = row.get("audio_id", "")
            text = (row.get("normalized_text") or "").strip()

            if not clip_id or clip_id not in known_clip_ids:
                counters["skipped_no_clip"] += 1
                continue
            counters["matched"] += 1

            if not text:
                counters["skipped_empty_text"] += 1
                continue

            if clip_id in seen:
                counters["skipped_dup"] += 1
                continue
            seen.add(clip_id)

            metadata = {
                "split": row.get("split"),
                "consensus": row.get("consensus"),
                "selected_trans": row.get("selected_trans"),
            }
            tasks.append((clip_id, text, metadata))

    return tasks, counters


def _post_one(api_url: str, clip_id: str, text: str, metadata: dict) -> tuple[str, bool, str | None]:
    try:
        post_transcription(api_url, clip_id, text, metadata)
        return clip_id, True, None
    except Exception as e:
        return clip_id, False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Import BSC-LT distilled transcriptions into catvoice")
    parser.add_argument("--api-url", default="http://localhost:3000")
    parser.add_argument("--splits", default=",".join(ALL_SPLITS),
                         help=f"Comma-separated subset of {ALL_SPLITS}")
    parser.add_argument("--max", type=int, default=0, help="Max transcriptions to attempt (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't POST, just log what would happen")
    parser.add_argument("--refresh-cache", action="store_true",
                         help="Re-fetch the clip ID list instead of using the cached one from a previous run")
    parser.add_argument("--concurrency", type=int, default=1,
                         help="Number of POST /transcriptions requests to run in parallel (default 1 = sequential)")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    for s in splits:
        if s not in METADATA_FILES:
            parser.error(f"unknown split {s!r}, choose from {ALL_SPLITS}")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")

    log.info("Fetching existing clip IDs from %s…", api_url)
    known_clip_ids = fetch_all_clip_ids(api_url, use_cache=not args.refresh_cache)
    log.info("Backend has %d clips.", len(known_clip_ids))

    tasks, counters = _collect_tasks(splits, known_clip_ids, args.max)
    log.info("%d transcriptions queued to post (concurrency=%d).", len(tasks), args.concurrency)

    posted = 0
    failed = 0

    if args.dry_run:
        for clip_id, text, _ in tasks:
            log.info("[dry-run] %s: would post %r", clip_id[:8], text[:80])
        posted = len(tasks)
    elif args.concurrency == 1:
        for clip_id, text, metadata in tasks:
            _, ok, err = _post_one(api_url, clip_id, text, metadata)
            if ok:
                posted += 1
            else:
                failed += 1
                log.warning("%s: failed to post: %s", clip_id[:8], err)
            if (posted + failed) % 500 == 0:
                log.info("…posted %d transcriptions (%d attempted)", posted, posted + failed)
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(_post_one, api_url, clip_id, text, metadata) for clip_id, text, metadata in tasks]
            for future in as_completed(futures):
                clip_id, ok, err = future.result()
                if ok:
                    posted += 1
                else:
                    failed += 1
                    log.warning("%s: failed to post: %s", clip_id[:8], err)
                if (posted + failed) % 500 == 0:
                    log.info("…posted %d transcriptions (%d attempted)", posted, posted + failed)

    log.info(
        "Done. %d rows scanned, %d matched an existing clip, %d posted, %d failed, "
        "%d skipped (no matching clip), %d skipped (empty text), %d skipped (dup within run).",
        counters["total_rows"], counters["matched"], posted, failed,
        counters["skipped_no_clip"], counters["skipped_empty_text"], counters["skipped_dup"],
    )


if __name__ == "__main__":
    main()
