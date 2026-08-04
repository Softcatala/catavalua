#!/usr/bin/env python3
"""
First short pass (run this before provisioning any pod): transcribes a
small sample of clips_to_transcribe.tsv locally — CPU is fine for a
handful of clips — over HTTP range requests (no need to download any tar
files), and prints each result next to the dataset's original candidate_1
so you can eyeball two things before trusting the full run:

  1. Does the model actually return punctuation? (the entire point of this
     pipeline — see ../README.md and issue #8)
  2. Roughly how it compares to the original ASR candidate on the same
     audio.

Doesn't post anything anywhere — read-only, local inspection only. Once
you're happy, provision a pod and run pod/run_full_transcription.py.

Usage:
  python scripts/whisper_transcribe/select_clips.py     # if not done yet
  python scripts/whisper_transcribe/pilot_transcribe.py --n 15
  python scripts/whisper_transcribe/pilot_transcribe.py --n 15 --device cuda  # if you have a local GPU
"""
import argparse
import csv
import io
import logging
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import CLIPS_TO_TRANSCRIBE_TSV, LANGUAGE, MODEL_CACHE_DIR, WHISPER_MODEL_ID  # noqa: E402
import whisper_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pilot_transcribe")

HF_BASE = "https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main"
PUNCT_RE = re.compile(r"[.,;:!?¡¿…]")


def fetch_range(url: str, start: int, end: int, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_clip_audio(row: dict):
    import soundfile as sf

    url = f"{HF_BASE}/audio-{row['tar_file']}.tar"
    start, size = int(row["tar_offset"]), int(row["tar_size"])
    raw = fetch_range(url, start, start + size - 1, timeout=60)
    audio, sr = sf.read(io.BytesIO(raw))
    if sr != 16000:
        raise ValueError(f"unexpected sample rate {sr}")
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=15, help="number of clips to sample (default 15)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="cpu", help="cpu or cuda (default cpu — this is a local pilot, no pod)")
    parser.add_argument("--compute-type", default=None, help="default: int8 on cpu, float16 on cuda")
    parser.add_argument("--beam-size", type=int, default=5)
    args = parser.parse_args()

    if not CLIPS_TO_TRANSCRIBE_TSV.exists():
        log.error("%s not found — run select_clips.py first", CLIPS_TO_TRANSCRIBE_TSV)
        return

    with CLIPS_TO_TRANSCRIBE_TSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    random.seed(args.seed)
    sample = random.sample(rows, min(args.n, len(rows)))
    log.info("sampled %d clips (seed=%d) from %d candidates", len(sample), args.seed, len(rows))

    log.info("fetching audio over HTTP range requests...")
    audios, ok_rows = [], []
    for r in sample:
        try:
            audios.append(fetch_clip_audio(r))
            ok_rows.append(r)
        except Exception as e:
            log.warning("%s: fetch failed: %s", r["clip_id"][:8], e)

    compute_type = args.compute_type or whisper_engine.default_compute_type(args.device)
    log.info(
        "loading %s (device=%s, compute_type=%s, language=%s)... this downloads the model on first run",
        WHISPER_MODEL_ID, args.device, compute_type, LANGUAGE,
    )
    wm, tokenizer = whisper_engine.load_model(
        WHISPER_MODEL_ID, args.device, compute_type, str(MODEL_CACHE_DIR), LANGUAGE,
    )

    log.info("transcribing %d clips in one batch...", len(ok_rows))
    texts = whisper_engine.transcribe_batch(wm, tokenizer, audios, beam_size=args.beam_size)

    punctuated = 0
    print("\n" + "=" * 100)
    for r, text in zip(ok_rows, texts):
        has_punct = bool(PUNCT_RE.search(text))
        punctuated += has_punct
        print(f"\nclip {r['clip_id'][:8]}  ({r['duration']}s)  punctuation: {'YES' if has_punct else 'no'}")
        print(f"  original (candidate_1): {r['candidate_1']}")
        print(f"  whisper-large-v3-turbo: {text}")
    print("\n" + "=" * 100)
    print(f"\n{punctuated}/{len(texts)} clips came back with at least one punctuation mark.")
    if punctuated < len(texts):
        print("Some clips had none — could be genuinely short/single-word utterances, or worth listening to "
              "the audio directly before trusting the full run. Re-run with a different --seed for more signal.")


if __name__ == "__main__":
    main()
