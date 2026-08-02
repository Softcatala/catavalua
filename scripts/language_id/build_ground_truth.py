#!/usr/bin/env python3
"""
Builds a small, hand-labelable ground-truth sample for evaluating spoken
language-ID models (see GitHub issue #5 — filtering non-Catalan clips, and
REPORT.md for the full writeup).

Neither speechbrain/lang-id-voxlingua107-ecapa nor facebook/mms-lid-126
publish a Catalan-vs-Spanish confusion rate, which is exactly the pair that
matters most for this dataset (closely related, code-switching is common in
Catalonia). Rather than trust either model's aggregate accuracy figure, this
script pulls a random sample of real clips, downloads their audio, and
writes a TSV for a human to label by ear. That labeled sample is later used
to score both models and pick a real confidence threshold, before any vote
gets cast automatically.

Reuses the same tar-index + HTTP-range audio fetch as scripts/transcribe.py.

New rows are appended, never overwritten — safe to re-run without losing
existing labels. ground_truth.tsv lives here (tracked in git, unlike the
gitignored data/ dir) since the labeled TSV is the valuable artifact; audio
stays under data/language_id/ (gitignored, regenerable from the clip_id
alone via the HF tar index) and is never committed.

Usage:
  python scripts/language_id/build_ground_truth.py                # 100 clips, seed 42
  python scripts/language_id/build_ground_truth.py --n 150 --seed 7
"""
import argparse
import csv
import logging
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import AUDIO_DIR, GROUND_TRUTH_TSV, LID_DIR  # noqa: E402
from hf_audio import fetch_audio, load_tar_index, load_clips_rows  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("build_ground_truth")

FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "ground_truth_lang", "notes", "source"]


def _fetch_one(row: dict, index: dict[str, dict]) -> tuple[dict, bool, str | None]:
    clip_id = row["clip_id"]
    dest = AUDIO_DIR / f"{clip_id}.wav"
    try:
        fetch_audio(index[clip_id], dest)
        return row, True, None
    except Exception as e:
        return row, False, str(e)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=100, help="sample size (default 100)")
    parser.add_argument("--seed", type=int, default=42, help="random seed, for a reproducible sample (default 42)")
    parser.add_argument("--concurrency", type=int, default=8, help="parallel audio downloads (default 8)")
    args = parser.parse_args()

    try:
        index = load_tar_index()
        rows = load_clips_rows()
    except FileNotFoundError as e:
        log.error(str(e))
        return

    existing: list[dict] = []
    existing_ids: set[str] = set()
    if GROUND_TRUTH_TSV.exists():
        with GROUND_TRUTH_TSV.open(newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f, delimiter="\t"))
        existing_ids = {r["clip_id"] for r in existing}
        log.info("%s already has %d labeled/sampled clips — won't duplicate or overwrite them", GROUND_TRUTH_TSV, len(existing))

    indexed_rows = [r for r in rows if r["clip_id"] in index and r["clip_id"] not in existing_ids]
    log.info("%d/%d clips have a tar index entry and aren't already in the sample", len(indexed_rows), len(rows))

    random.seed(args.seed)
    sample = random.sample(indexed_rows, min(args.n, len(indexed_rows)))
    log.info("sampled %d new clips (seed=%d)", len(sample), args.seed)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(_fetch_one, r, index): r for r in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            row, ok, err = fut.result()
            if ok:
                results.append(row)
            else:
                log.warning("%s: fetch failed: %s", row["clip_id"][:8], err)
            if i % 20 == 0 or i == len(sample):
                log.info("%d/%d fetched (%d ok)", i, len(sample), len(results))

    if len(results) < len(sample):
        log.warning("%d clips failed to download — sample has %d clips, not %d", len(sample) - len(results), len(results), len(sample))

    new_rows = [
        {
            "clip_id": r["clip_id"],
            "duration": r.get("duration", ""),
            "yt_url": r.get("yt_url", ""),
            "candidate_1": (r.get("candidate_1") or "")[:120],
            "ground_truth_lang": "",
            "notes": "",
            "source": "random_sample",
        }
        for r in results
    ]
    all_rows = existing + new_rows
    all_rows.sort(key=lambda r: r["clip_id"])

    LID_DIR.mkdir(parents=True, exist_ok=True)
    with GROUND_TRUTH_TSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(all_rows)

    log.info("wrote %s (%d rows total, %d new)", GROUND_TRUTH_TSV, len(all_rows), len(new_rows))
    log.info("audio files in %s — play alongside the TSV, e.g. %s/<clip_id>.wav", AUDIO_DIR, AUDIO_DIR)
    log.info(
        "fill in ground_truth_lang for each row: ca (catalan) / es (spanish) / en (english) / other / unsure "
        "— use notes for anything odd (code-switching, music, near-silence, etc.)"
    )


if __name__ == "__main__":
    main()
