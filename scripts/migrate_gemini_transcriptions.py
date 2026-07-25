"""
Migrate clip metadata, TAR audio index, and Gemini transcriptions from one
CatVoice backend to another over HTTP — no direct file/DB access required
on either side.

Votes and non-Gemini transcriptions (human corrections, candidate text)
are intentionally NOT migrated.

Safe to re-run: POST /clips upserts, and POST /transcriptions is
deduplicated server-side by (clipId, origin, text), so repeating a run
after an interruption won't create duplicate rows.

Usage:
  python scripts/migrate_gemini_transcriptions.py \
      --source-api https://api.catvoice.internal.liam.cat \
      --dest-api https://api.catvoice-new.example.com

  # Preview without writing anything to --dest-api
  python scripts/migrate_gemini_transcriptions.py \
      --source-api https://api.catvoice.internal.liam.cat \
      --dest-api https://api.catvoice-new.example.com \
      --dry-run
"""
import argparse
import logging

import requests

log = logging.getLogger("migrate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PAGE_LIMIT = 100


def fetch_all_clips(api_url: str) -> list[dict]:
    clips: list[dict] = []
    page = 1
    while True:
        r = requests.get(f"{api_url}/clips", params={"page": page, "limit": PAGE_LIMIT}, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        clips.extend(item["clip"] for item in items)
        if len(clips) >= data.get("total", 0):
            break
        page += 1
    return clips


def fetch_gemini_transcriptions(api_url: str, clip_id: str) -> list[dict]:
    r = requests.get(f"{api_url}/clips/{clip_id}/transcriptions", timeout=30)
    r.raise_for_status()
    return [t for t in r.json() if t["origin"].startswith("gemini")]


def push_clip(api_url: str, clip: dict) -> None:
    r = requests.post(
        f"{api_url}/clips",
        json={
            "clipId": clip["clipId"],
            "sourceId": clip.get("sourceId"),
            "duration": clip.get("duration"),
            "start": clip.get("start"),
            "end": clip.get("end"),
            "gender": clip.get("gender"),
            "candidate1": clip.get("candidate1"),
            "candidate2": clip.get("candidate2"),
            "ytUrl": clip.get("ytUrl"),
            "license": clip.get("license"),
            "detectedDialect": clip.get("detectedDialect"),
            "detectedLanguage": clip.get("detectedLanguage"),
            "isRelevant": clip.get("isRelevant"),
        },
        timeout=30,
    )
    r.raise_for_status()


def push_tar_index(api_url: str, clip_id: str, tar_file: int, tar_offset: int, tar_size: int) -> None:
    r = requests.post(
        f"{api_url}/clips/{clip_id}/tar-index",
        json={"tarFile": tar_file, "tarOffset": tar_offset, "tarSize": tar_size},
        timeout=30,
    )
    r.raise_for_status()


def push_transcription(api_url: str, clip_id: str, origin: str, text: str, metadata: str | None) -> None:
    payload = {"clipId": clip_id, "origin": origin, "text": text}
    if metadata:
        payload["metadata"] = metadata
    r = requests.post(f"{api_url}/transcriptions", json=payload, timeout=30)
    r.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description="Migrate clips + Gemini transcriptions between CatVoice backends")
    parser.add_argument("--source-api", required=True)
    parser.add_argument("--dest-api", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Log what would happen without writing to --dest-api")
    args = parser.parse_args()

    source = args.source_api.rstrip("/")
    dest = args.dest_api.rstrip("/")

    log.info("Fetching clip list from %s…", source)
    clips = fetch_all_clips(source)
    log.info("%d clips found on source.", len(clips))

    clips_migrated = 0
    transcriptions_migrated = 0
    clips_without_gemini = 0

    for i, clip in enumerate(clips, 1):
        clip_id = clip["clipId"]
        gemini_rows = fetch_gemini_transcriptions(source, clip_id)
        if not gemini_rows:
            clips_without_gemini += 1

        if args.dry_run:
            log.info(
                "[dry-run] %s: would push clip%s + %d gemini transcription(s)",
                clip_id[:8],
                " + tar-index" if clip.get("tarFile") is not None else "",
                len(gemini_rows),
            )
        else:
            push_clip(dest, clip)
            if clip.get("tarFile") is not None:
                push_tar_index(dest, clip_id, clip["tarFile"], clip["tarOffset"], clip["tarSize"])
            for t in gemini_rows:
                push_transcription(dest, clip_id, t["origin"], t["text"], t.get("metadata"))

        clips_migrated += 1
        transcriptions_migrated += len(gemini_rows)

        if i % 200 == 0:
            log.info("Progress: %d/%d clips processed…", i, len(clips))

    log.info(
        "Done. %d clips migrated, %d gemini transcriptions migrated, %d clips had no gemini transcription.",
        clips_migrated,
        transcriptions_migrated,
        clips_without_gemini,
    )


if __name__ == "__main__":
    main()
