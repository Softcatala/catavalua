#!/usr/bin/env bash
# Downloads all 51 HF tar files (audio-0.tar .. audio-50.tar, ~107GB total)
# to a local directory on the pod, so the detection run reads audio via a
# local file seek instead of 231k individual HTTP range requests.
#
# Resumable + idempotent: wget -c continues partial downloads, and any tar
# already fully downloaded is skipped by comparing against its expected
# size (HEAD request) before re-downloading — safe to re-run after an
# interruption at any point.
set -euo pipefail

DEST_DIR="${1:-$HOME/tars}"
PARALLEL="${2:-4}"
HF_BASE="https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main"

mkdir -p "$DEST_DIR"

fetch_one() {
    local n="$1"
    local url="$HF_BASE/audio-$n.tar"
    local dest="$DEST_DIR/audio-$n.tar"

    local remote_size
    remote_size=$(curl -sIL "$url" | grep -i '^content-length:' | tail -1 | tr -d '\r' | awk '{print $2}')

    if [[ -f "$dest" && -n "$remote_size" ]]; then
        local local_size
        local_size=$(stat -c%s "$dest" 2>/dev/null || stat -f%z "$dest" 2>/dev/null || echo 0)
        if [[ "$local_size" == "$remote_size" ]]; then
            echo "audio-$n.tar: already complete ($local_size bytes), skipping"
            return 0
        fi
    fi

    echo "audio-$n.tar: downloading..."
    wget -c -q --show-progress -O "$dest" "$url"
    echo "audio-$n.tar: done"
}
export -f fetch_one
export DEST_DIR HF_BASE

seq 0 50 | xargs -P "$PARALLEL" -I{} bash -c 'fetch_one "$@"' _ {}

echo "All 51 tar files present in $DEST_DIR"
du -sh "$DEST_DIR"
