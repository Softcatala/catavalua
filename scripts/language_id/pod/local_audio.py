"""Reads clip audio straight out of the locally-downloaded tar files (via
download_tars.sh) by seeking to the clip's (tar_offset, tar_size) — same
byte range scripts/transcribe.py and hf_audio.py fetch over HTTP, but local
disk reads instead of 231k individual HTTPS requests. No per-clip temp
files: returns raw WAV bytes straight into memory."""
from pathlib import Path


def read_local_audio(tar_dir: Path, entry: dict) -> bytes:
    path = tar_dir / f"audio-{entry['tar_file']}.tar"
    with open(path, "rb") as f:
        f.seek(entry["tar_offset"])
        return f.read(entry["tar_size"])
