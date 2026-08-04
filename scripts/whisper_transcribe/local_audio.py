"""Reads clip audio straight out of the locally-downloaded tar files (via
pod/download_tars.sh) by seeking to the clip's (tar_offset, tar_size) — same
byte range scripts/transcribe.py and scripts/language_id/hf_audio.py fetch
over HTTP, but local disk reads instead of one HTTPS request per clip.
No per-clip temp files: returns raw WAV bytes straight into memory.

Identical logic to scripts/language_id/pod/local_audio.py — duplicated
rather than imported so this directory stays self-contained and rsyncable
to a pod on its own (see that file's sibling README for why)."""
from pathlib import Path


def read_local_audio(tar_dir: Path, entry: dict) -> bytes:
    path = tar_dir / f"audio-{entry['tar_file']}.tar"
    with open(path, "rb") as f:
        f.seek(entry["tar_offset"])
        return f.read(entry["tar_size"])
