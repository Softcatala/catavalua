"""Shared HTTP-range audio fetch against the HF tar files — same technique as
scripts/transcribe.py, reused here so build_ground_truth.py and
detect_language.py don't duplicate it."""
import csv
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import CLIPS_TSV_FILE, TAR_INDEX_FILE  # noqa: E402

HF_BASE = "https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main"


def fetch_range(url: str, start: int, end: int, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_audio(entry: dict, dest: Path) -> None:
    url = f"{HF_BASE}/audio-{entry['tar_file']}.tar"
    data = fetch_range(url, entry["tar_offset"], entry["tar_offset"] + entry["tar_size"] - 1, timeout=60)
    dest.write_bytes(data)


def load_tar_index() -> dict[str, dict]:
    if not TAR_INDEX_FILE.exists():
        raise FileNotFoundError(
            f"{TAR_INDEX_FILE} not found — run `python scripts/transcribe.py --build-index-only` first."
        )
    return json.loads(TAR_INDEX_FILE.read_text())


def load_clips_rows() -> list[dict]:
    if not CLIPS_TSV_FILE.exists():
        raise FileNotFoundError(
            f"{CLIPS_TSV_FILE} not found — run `python scripts/transcribe.py --import-only --max 1` once to "
            "cache it, or download clips.tsv from the HF dataset repo directly."
        )
    with CLIPS_TSV_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))
