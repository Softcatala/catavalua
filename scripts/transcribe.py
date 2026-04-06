#!/usr/bin/env python3
"""
CatVoice transcription script.

Workflow:
  Step 1 — Build TAR index (--build-index-only):
    Reads headers from all 51 tar files via HTTP range requests.
    Saves clip_id -> {tar_file, tar_offset, tar_size} to data/tar_index.json.

  Step 2 — Transcribe (default mode):
    Iterates all dataset rows from HuggingFace API.
    For each unprocessed clip:
      - Fetches audio from the tar archive (HTTP range, no full download)
      - Runs `gemini` CLI with audio file + candidate transcriptions
      - POSTs results to the catvoice backend
      - Deletes temp audio

Idempotent: skips clips that already have both origins in the DB.
Resilient: exponential backoff, always cleans up temp files.

Usage:
  python scripts/transcribe.py --build-index-only        # Step 1 (run once)
  python scripts/transcribe.py                           # Step 2 (run repeatedly)
  python scripts/transcribe.py --max 10                  # Process only 10 clips
"""

import argparse
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("catvoice")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_BASE = "https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main"
HF_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=softcatala%2Fcatalan-youtube-speech&config=default&split=train"
)

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_FILE = DATA_DIR / "tar_index.json"
TEMP_DIR = DATA_DIR / "tmp"

TAR_HEADER_SIZE = 512
TAR_COUNT = 51  # audio-0.tar … audio-50.tar

GEMINI_MODELS = [
    "gemini-3-flash-preview",       # newest generation, full flash
    "gemini-3.1-flash-lite-preview", # newer generation, lite
    "gemini-2.5-flash",             # stable
    "gemini-2.5-flash-lite",        # most limited fallback
]

_RATE_LIMIT_RE = re.compile(
    r"quota|rate.?limit|resource.?exhausted|429|too many requests",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_range(url: str, start: int, end: int, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url: str, timeout: int = 30) -> dict | list:
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


# ---------------------------------------------------------------------------
# TAR indexer
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _parse_tar_header(block: bytes) -> dict | None:
    if all(b == 0 for b in block[:100]):
        return None
    name = block[:100].rstrip(b"\x00").decode("utf-8", errors="replace")
    typeflag = chr(block[156]) if block[156] else "0"
    size_field = block[124:136].rstrip(b"\x00").decode("ascii", errors="replace").strip()
    size = int(size_field, 8) if size_field else 0
    return {"name": name, "size": size, "typeflag": typeflag}


def index_tar(tar_num: int) -> list[dict]:
    """Return list of {clip_id, tar_file, tar_offset, tar_size} by reading tar headers remotely."""
    url = f"{HF_BASE}/audio-{tar_num}.tar"
    entries: list[dict] = []
    offset = 0
    pending_long_name: str | None = None
    consecutive_empty = 0

    while True:
        try:
            block = fetch_range(url, offset, offset + TAR_HEADER_SIZE - 1)
        except Exception as e:
            log.warning("tar-%d: cannot read at offset %d: %s", tar_num, offset, e)
            break

        if len(block) < TAR_HEADER_SIZE:
            break

        hdr = _parse_tar_header(block)
        if hdr is None:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            offset += TAR_HEADER_SIZE
            continue
        consecutive_empty = 0

        name = hdr["name"]
        size = hdr["size"]
        typeflag = hdr["typeflag"]

        # GNU long-name extension: next block(s) hold the real name
        if typeflag == "L":
            try:
                long_bytes = fetch_range(url, offset + TAR_HEADER_SIZE, offset + TAR_HEADER_SIZE + size - 1)
                pending_long_name = long_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")
            except Exception as e:
                log.warning("tar-%d: cannot read long name at %d: %s", tar_num, offset, e)
            padded = math.ceil(size / TAR_HEADER_SIZE) * TAR_HEADER_SIZE
            offset += TAR_HEADER_SIZE + padded
            continue

        if pending_long_name:
            name = pending_long_name
            pending_long_name = None

        data_offset = offset + TAR_HEADER_SIZE

        if typeflag in ("0", "\x00", "7") and size > 0:
            stem = Path(name).stem  # "audio/UUID.wav" → "UUID"
            if _UUID_RE.match(stem):
                entries.append({
                    "clip_id": stem,
                    "tar_file": tar_num,
                    "tar_offset": data_offset,
                    "tar_size": size,
                })

        padded = math.ceil(size / TAR_HEADER_SIZE) * TAR_HEADER_SIZE
        offset += TAR_HEADER_SIZE + padded

    log.info("tar-%d: found %d clips", tar_num, len(entries))
    return entries


def build_full_index() -> dict[str, dict]:
    """Index all tar files, saving progress after each one."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()  # resume from partial run if available
    # Determine which tar files have already been indexed
    indexed_tars = {entry["tar_file"] for entry in index.values()}
    for i in range(TAR_COUNT):
        if i in indexed_tars:
            log.info("tar-%d: already indexed, skipping", i)
            continue
        try:
            for entry in index_tar(i):
                index[entry["clip_id"]] = entry
            save_index(index)  # persist after each tar
        except Exception as e:
            log.error("tar-%d: indexing failed: %s", i, e)
    return index


def load_index() -> dict[str, dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return {}


def save_index(index: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=2))
    log.info("TAR index saved to %s (%d clips)", INDEX_FILE, len(index))


# ---------------------------------------------------------------------------
# Dataset iterator
# ---------------------------------------------------------------------------

def iter_dataset(offset: int = 0, page_size: int = 100):
    while True:
        url = f"{HF_API}&offset={offset}&length={page_size}"
        delay = 5
        while True:  # retry loop for this page
            try:
                data = http_get_json(url)
                break  # success — move on
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    log.warning("Dataset API transient error at offset %d (%s) — retrying in %ds…", offset, e, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 300)
                    continue
                log.error("Dataset API permanent error at offset %d: %s — stopping.", offset, e)
                return
            except Exception as e:
                log.warning("Dataset API error at offset %d: %s — retrying in %ds…", offset, e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 300)
        rows = data.get("rows", [])
        if not rows:
            return
        for row in rows:
            yield row["row"]
        offset += len(rows)
        if len(rows) < page_size:
            return


# ---------------------------------------------------------------------------
# Backend API
# ---------------------------------------------------------------------------

def fetch_all_clip_ids(api_url: str) -> list[str]:
    """Return all clip IDs currently stored in the backend database."""
    ids: list[str] = []
    page = 1
    limit = 100  # backend max
    while True:
        data = http_get_json(f"{api_url}/clips?search=&page={page}&limit={limit}")
        items = data.get("items", [])
        for item in items:
            ids.append(item["clip"]["clipId"])
        if len(items) < limit:
            break
        page += 1
    return ids


def backend_get(api_url: str, path: str):
    try:
        return http_get_json(f"{api_url}{path}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def ensure_clip(api_url: str, row: dict) -> None:
    http_post_json(f"{api_url}/clips", {
        "clipId": row["clip_id"],
        "sourceId": row.get("source_id") or "",
        "duration": row.get("duration"),
        "start": row.get("start"),
        "end": row.get("end"),
        "gender": row.get("gender") or "",
        "candidate1": row.get("candidate_1") or "",
        "candidate2": row.get("candidate_2") or "",
        "ytUrl": row.get("yt_url") or "",
        "license": row.get("license") or "",
    })


def has_gemini_transcription(api_url: str, clip_id: str) -> bool:
    """Return True if this clip already has a transcription from any Gemini model."""
    data = backend_get(api_url, f"/clips/{clip_id}/transcriptions")
    if not data:
        return False
    return any(t.get("origin", "").startswith("gemini") for t in data)


def post_transcription(api_url: str, clip_id: str, origin: str, text: str, metadata: dict | None) -> None:
    http_post_json(f"{api_url}/transcriptions", {
        "clipId": clip_id,
        "origin": origin,
        "text": text,
        "metadata": json.dumps(metadata) if metadata else None,
    })


def post_tar_index(api_url: str, clip_id: str, entry: dict) -> None:
    try:
        http_post_json(f"{api_url}/clips/{clip_id}/tar-index", {
            "tarFile": entry["tar_file"],
            "tarOffset": entry["tar_offset"],
            "tarSize": entry["tar_size"],
        })
    except Exception as e:
        log.warning("Failed to post tar-index for %s: %s", clip_id, e)


def patch_clip_metadata(api_url: str, clip_id: str, **fields) -> None:
    """Update mutable fields on a clip (detectedDialect, detectedLanguage, isRelevant)."""
    try:
        http_post_json(f"{api_url}/clips", {"clipId": clip_id, **fields})
    except Exception as e:
        log.warning("Failed to patch clip %s: %s", clip_id, e)


# ---------------------------------------------------------------------------
# Audio fetching
# ---------------------------------------------------------------------------

def fetch_audio(entry: dict, dest: Path) -> None:
    url = f"{HF_BASE}/audio-{entry['tar_file']}.tar"
    data = fetch_range(url, entry["tar_offset"], entry["tar_offset"] + entry["tar_size"] - 1, timeout=60)
    dest.write_bytes(data)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

GEMINI_PROMPT = """\
You are a Catalan language expert. Read and analyze the audio file at: {audio_path}

Two existing ASR transcriptions for this clip:

Candidate 1: {candidate_1}

Candidate 2: {candidate_2}

Speaker gender annotation: {gender}
Duration: {duration:.1f}s

FIRST: Listen and determine if the speech is actually in Catalan. It may sometimes be in Spanish or another language.

If NOT in Catalan, return:
{{"is_catalan": false, "detected_language": "spanish|other|unknown", "corrected_transcription": null, "confidence": "high|medium|low"}}

If in Catalan, produce a verbatim transcription of what is actually spoken:
- Keep all filler words (uh, eh, mmm, doncs, bé, home, mira, etc.)
- Keep repetitions and false starts exactly as spoken
- Do NOT correct grammar or add punctuation
- Do NOT interpret or paraphrase
- Identify the Catalan dialect variant if possible

Return:
{{"is_catalan": true, "detected_language": "catalan", "corrected_transcription": "...", "detected_gender": "male|female|unknown", "dialect_notes": "central|valencian|balearic|northwestern|alguerès|septentrional|unknown", "confidence": "high|medium|low"}}

Respond ONLY with JSON, no markdown.
"""


class RateLimitError(Exception):
    """Raised when the Gemini CLI signals a quota or rate-limit error."""


def _run_cmd(cmd: list[str], max_attempts: int = 5, label: str = "") -> str | None:
    """Run a command with retries.  Raises RateLimitError on quota exhaustion."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE", None)
    delay = 5
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, env=env
            )
            stderr = result.stderr.strip()
            if _RATE_LIMIT_RE.search(stderr) or _RATE_LIMIT_RE.search(result.stdout):
                raise RateLimitError(f"{label}: rate limit detected: {stderr[:200]}")
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            log.warning("%s attempt %d failed (rc=%d): %s", label, attempt, result.returncode, stderr[:200])
        except RateLimitError:
            raise  # propagate immediately — no retry with same model
        except subprocess.TimeoutExpired:
            log.warning("%s attempt %d timed out", label, attempt)
        except FileNotFoundError:
            log.error("%s: command not found: %s", label, cmd[0])
            return None
        if attempt < max_attempts:
            log.info("Retrying %s in %ds…", label, delay)
            time.sleep(delay)
            delay = min(delay * 2, 120)
    return None


def _parse_json(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    start = raw.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw, start)
        return obj
    except json.JSONDecodeError:
        return None


def run_gemini(row: dict, audio_path: Path) -> tuple[dict | None, str | None]:
    """Try each model in priority order.  Returns (result, model_name) or (None, None)."""
    prompt = GEMINI_PROMPT.format(
        audio_path=str(audio_path.resolve()),
        candidate_1=row.get("candidate_1") or "",
        candidate_2=row.get("candidate_2") or "",
        gender=row.get("gender") or "unknown",
        duration=float(row.get("duration") or 0),
    )
    for model in GEMINI_MODELS:
        label = f"gemini/{model}"
        try:
            raw = _run_cmd(["gemini", "--yolo", "--model", model, prompt], label=label)
            if raw:
                result = _parse_json(raw)
                if result:
                    return result, model
            log.warning("%s: no parseable JSON output", label)
        except RateLimitError as e:
            log.warning("%s — falling back to next model", e)
            continue
    return None, None


# ---------------------------------------------------------------------------
# Per-clip processing
# ---------------------------------------------------------------------------

def process_clip(api_url: str, row: dict, tar_index: dict[str, dict]) -> bool:
    clip_id = row["clip_id"]

    try:
        ensure_clip(api_url, row)
    except Exception as e:
        log.warning("%s: failed to upsert clip: %s", clip_id[:8], e)

    if has_gemini_transcription(api_url, clip_id):
        log.debug("%s: already done", clip_id[:8])
        return True

    entry = tar_index.get(clip_id)
    if not entry:
        log.warning("%s: not in TAR index — skipping (run --build-index-only first)", clip_id[:8])
        return False

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", dir=TEMP_DIR, delete=False, prefix=f"cv_{clip_id[:8]}_")
    audio_path = Path(tmp.name)
    tmp.close()

    try:
        log.info("%s: fetching audio from tar-%d …", clip_id[:8], entry["tar_file"])
        fetch_audio(entry, audio_path)
        post_tar_index(api_url, clip_id, entry)
    except Exception as e:
        log.warning("%s: audio fetch failed: %s", clip_id[:8], e)
        audio_path.unlink(missing_ok=True)
        return False

    success = False
    try:
        log.info("%s: running Gemini (models: %s) …", clip_id[:8], " > ".join(GEMINI_MODELS))
        result, model = run_gemini(row, audio_path)
        if result and model:
            if result.get("is_catalan") is False:
                lang = result.get("detected_language", "unknown")
                log.info("%s: NOT Catalan (detected: %s, model: %s) — flagging", clip_id[:8], lang, model)
                patch_clip_metadata(api_url, clip_id, detectedLanguage=lang, isRelevant=False)
                success = True
            elif result.get("corrected_transcription"):
                meta = {k: v for k, v in result.items() if k not in ("corrected_transcription", "is_catalan")}
                post_transcription(api_url, clip_id, model, result["corrected_transcription"], meta)
                dialect = result.get("dialect_notes")
                patch_kwargs: dict = {"detectedLanguage": "catalan", "isRelevant": True}
                if dialect:
                    patch_kwargs["detectedDialect"] = dialect
                patch_clip_metadata(api_url, clip_id, **patch_kwargs)
                log.info("%s: saved (model: %s, dialect: %s)", clip_id[:8], model, dialect or "n/a")
                success = True
            else:
                log.warning("%s: Gemini produced no usable output (model: %s)", clip_id[:8], model)
        else:
            log.warning("%s: all Gemini models exhausted or produced no output", clip_id[:8])
    except Exception as e:
        log.warning("%s: error processing Gemini result: %s", clip_id[:8], e)
    finally:
        audio_path.unlink(missing_ok=True)

    return success


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CatVoice transcription pipeline")
    parser.add_argument("--api-url", default="https://api.catvoice.internal.liam.cat")
    parser.add_argument("--max", type=int, default=0, help="Max clips to process (0=all)")
    parser.add_argument("--offset", type=int, default=0, help="Dataset row offset")
    parser.add_argument(
        "--build-index-only", action="store_true",
        help="Build TAR index and exit (run this once before transcribing)"
    )
    parser.add_argument(
        "--post-index", action="store_true",
        help="Post existing tar_index.json to backend and exit"
    )
    parser.add_argument(
        "--import-only", action="store_true",
        help="Import clip metadata only (no Claude/Gemini). Good for populating the UI quickly."
    )
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    if args.build_index_only:
        log.info("Building TAR index (%d tar files)…", TAR_COUNT)
        index = build_full_index()
        save_index(index)
        log.info("Index complete: %d clips across %d tar files.", len(index), TAR_COUNT)
        return

    if args.post_index:
        index = load_index()
        if not index:
            log.error("No index found at %s. Run with --build-index-only first.", INDEX_FILE)
            return
        log.info("Fetching clip IDs from backend…")
        clip_ids = fetch_all_clip_ids(api_url)
        log.info("Posting tar index for %d clips in DB (index has %d total)…", len(clip_ids), len(index))
        updated = 0
        for clip_id in clip_ids:
            entry = index.get(clip_id)
            if entry:
                post_tar_index(api_url, clip_id, entry)
                updated += 1
        log.info("Done. Updated %d clips.", updated)
        return

    # Load TAR index (needed for audio fetching)
    tar_index = load_index()
    if not tar_index:
        log.warning(
            "No TAR index found. Audio won't be available for Gemini. "
            "Run with --build-index-only first to enable audio-based transcription."
        )

    if args.import_only:
        log.info("Import-only mode: loading clip metadata (api=%s, offset=%d, max=%s)", api_url, args.offset, args.max or "all")
        imported = 0
        for row in iter_dataset(offset=args.offset):
            if args.max and imported >= args.max:
                break
            clip_id = row.get("clip_id", "")
            if not clip_id:
                continue
            try:
                ensure_clip(api_url, row)
                imported += 1
                if imported % 100 == 0:
                    log.info("Imported %d clips…", imported)
            except Exception as e:
                log.warning("%s: import failed: %s", clip_id[:8], e)
        log.info("Done. Imported %d clips.", imported)
        return

    log.info("Starting transcription pipeline (api=%s, offset=%d, max=%s)", api_url, args.offset, args.max or "all")
    processed = 0
    success_count = 0

    for row in iter_dataset(offset=args.offset):
        if args.max and processed >= args.max:
            break

        clip_id = row.get("clip_id", "")
        if not clip_id:
            continue

        log.info("[%d] %s", processed + 1, clip_id)
        ok = process_clip(api_url, row, tar_index)
        processed += 1
        success_count += ok

        if processed % 10 == 0:
            log.info("— Progress: %d processed, %d successful —", processed, success_count)

    log.info("Finished. %d processed, %d successful.", processed, success_count)


if __name__ == "__main__":
    main()
