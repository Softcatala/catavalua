#!/usr/bin/env python3
"""
Builds a small, hand-labelable ground-truth sample for evaluating spoken
language-ID models (see GitHub issue #5 — filtering non-Catalan clips).

Neither speechbrain/lang-id-voxlingua107-ecapa nor facebook/mms-lid-126
publish a Catalan-vs-Spanish confusion rate, which is exactly the pair that
matters most for this dataset (closely related, code-switching is common in
Catalonia). Rather than trust either model's aggregate accuracy figure, this
script pulls a random sample of real clips, downloads their audio, and
writes a TSV for a human to label by ear. That labeled sample is later used
to score both models and pick a real confidence threshold, before any vote
gets cast automatically.

Reuses the same tar-index + HTTP-range audio fetch as scripts/transcribe.py,
and reads from the same local data/clips.tsv cache (downloaded once by
transcribe.py) rather than re-fetching it.

New rows are appended, never overwritten — safe to re-run without losing
existing labels. Output lives in scripts/reference/ (tracked in git, unlike
the gitignored data/ dir) since the labeled TSV is the valuable artifact;
audio stays under data/ (gitignored, regenerable from the clip_id alone via
the HF tar index) and is never committed.

Usage:
  python scripts/build_lid_ground_truth.py                # 100 clips, seed 42
  python scripts/build_lid_ground_truth.py --n 150 --seed 7
"""
import argparse
import csv
import json
import logging
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("build_lid_ground_truth")

HF_BASE = "https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main"
DATA_DIR = Path(__file__).parent.parent / "data"
CLIPS_TSV_FILE = DATA_DIR / "clips.tsv"
INDEX_FILE = DATA_DIR / "tar_index.json"
AUDIO_DIR = DATA_DIR / "lid_ground_truth" / "audio"
REF_DIR = Path(__file__).parent / "reference"
SAMPLE_TSV = REF_DIR / "lid_ground_truth.tsv"
FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "ground_truth_lang", "notes", "source"]


def fetch_range(url: str, start: int, end: int, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_audio(entry: dict, dest: Path) -> None:
    url = f"{HF_BASE}/audio-{entry['tar_file']}.tar"
    data = fetch_range(url, entry["tar_offset"], entry["tar_offset"] + entry["tar_size"] - 1, timeout=60)
    dest.write_bytes(data)


def load_index() -> dict[str, dict]:
    return json.loads(INDEX_FILE.read_text())


def load_rows() -> list[dict]:
    with CLIPS_TSV_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


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

    if not CLIPS_TSV_FILE.exists():
        log.error("%s not found — run `python scripts/transcribe.py --import-only --max 1` once to cache it, "
                   "or download clips.tsv from the HF dataset repo directly.", CLIPS_TSV_FILE)
        return
    if not INDEX_FILE.exists():
        log.error("%s not found — run `python scripts/transcribe.py --build-index-only` first.", INDEX_FILE)
        return

    index = load_index()
    rows = load_rows()

    existing: list[dict] = []
    existing_ids: set[str] = set()
    if SAMPLE_TSV.exists():
        with SAMPLE_TSV.open(newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f, delimiter="\t"))
        existing_ids = {r["clip_id"] for r in existing}
        log.info("%s already has %d labeled/sampled clips — won't duplicate or overwrite them", SAMPLE_TSV, len(existing))

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

    REF_DIR.mkdir(parents=True, exist_ok=True)
    with SAMPLE_TSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(all_rows)

    log.info("wrote %s (%d rows total, %d new)", SAMPLE_TSV, len(all_rows), len(new_rows))
    log.info("audio files in %s — play alongside the TSV, e.g. %s/<clip_id>.wav", AUDIO_DIR, AUDIO_DIR)
    log.info(
        "fill in ground_truth_lang for each row: ca (catalan) / es (spanish) / en (english) / other / unsure "
        "— use notes for anything odd (code-switching, music, near-silence, etc.)"
    )


if __name__ == "__main__":
    main()
