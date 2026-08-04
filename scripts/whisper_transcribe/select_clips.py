#!/usr/bin/env python3
"""
Builds the clip list this pipeline will transcribe (issue #8): every clip
NOT flagged non-Catalan by the language-ID pass in scripts/language_id/ —
tier 0 only, i.e. excluding both auto-hidden clips (tier 2, both models
flagged non-Catalan) AND clips a single model flagged (tier 1, one vote) —
see scripts/language_id/REPORT.md for how those tiers were derived.

Reads data/language_id/full_detect.tsv (the full-dataset LID run output,
231,202 clips) and data/tar_index.json (clip_id -> tar_file/tar_offset/
tar_size, from scripts/transcribe.py --build-index-only), joins them, and
writes data/whisper_transcribe/clips_to_transcribe.tsv.

Note: this deliberately does NOT include the ~482 clips in
scripts/language_id/ground_truth.tsv / detect_sample.tsv (hand-labeled or
held-out during that investigation, never scored into full_detect.tsv) —
same exclusion the LID vote-casting run itself used, kept consistent here
rather than inventing new inclusion logic for a ~0.2%-of-dataset gap.

Usage:
  python scripts/whisper_transcribe/select_clips.py
"""
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import CLIPS_TO_TRANSCRIBE_TSV, DATA_DIR, FULL_DETECT_TSV, TAR_INDEX_FILE  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("select_clips")

FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "tar_file", "tar_offset", "tar_size"]


def main():
    if not FULL_DETECT_TSV.exists():
        log.error("%s not found — run scripts/language_id's full-dataset pod run first (see its README.md)", FULL_DETECT_TSV)
        return
    if not TAR_INDEX_FILE.exists():
        log.error("%s not found — run `python scripts/transcribe.py --build-index-only` first", TAR_INDEX_FILE)
        return

    log.info("loading tar index...")
    tar_index: dict[str, dict] = json.loads(TAR_INDEX_FILE.read_text())

    log.info("scanning %s for tier-0 clips...", FULL_DETECT_TSV)
    tier_counts = {"0": 0, "1": 0, "2": 0}
    selected: list[dict] = []
    no_index = 0
    with FULL_DETECT_TSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            tier_counts[row["tier"]] = tier_counts.get(row["tier"], 0) + 1
            if row["tier"] != "0":
                continue
            entry = tar_index.get(row["clip_id"])
            if not entry:
                no_index += 1
                continue
            selected.append({
                "clip_id": row["clip_id"],
                "duration": row["duration"],
                "yt_url": row["yt_url"],
                "candidate_1": row["candidate_1"],
                "tar_file": entry["tar_file"],
                "tar_offset": entry["tar_offset"],
                "tar_size": entry["tar_size"],
            })

    log.info("tier counts in full_detect.tsv: %s", tier_counts)
    if no_index:
        log.warning("%d tier-0 clips had no tar-index entry — skipped", no_index)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CLIPS_TO_TRANSCRIBE_TSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(selected)

    total_hours = sum(float(r["duration"]) for r in selected) / 3600
    log.info(
        "wrote %s: %d clips selected for transcription (%.1f hours of audio)",
        CLIPS_TO_TRANSCRIBE_TSV, len(selected), total_hours,
    )


if __name__ == "__main__":
    main()
