#!/usr/bin/env python3
"""
OPTIONAL side experiment, not part of the main pipeline: runs CrisperWhisper
2.0 (nyralabs/CrisperWhisper2.0_turbo) on the same pilot sample as
pilot_transcribe.py, to see empirically whether its verbatim/filler-word
mode ("um", "eh", repetitions, false starts) produces usable Catalan output.

Why this is NOT the primary model for the full run (see ../README.md for
the full reasoning):
  - CrisperWhisper 2.0's disfluency-preserving fine-tuning is benchmarked
    across ten languages (English, German + 8 more) — Catalan isn't one of
    them. Its own model card only tags `en`/`de`. The README's claim is
    "works across most languages Whisper supports", which is a hedge, not
    a guarantee — quality on Catalan is genuinely untested, not just
    theoretically fine.
  - Its weights are under the Nyra Health Non-Commercial Research License,
    not MIT — friction against ever folding these transcriptions back into
    a dataset released under CC-BY (which permits commercial reuse
    downstream; a non-commercially-licensed derivative can't cleanly sit
    inside that).
  - This dataset's clips are pre-segmented single utterances, and issue #8
    is specifically about punctuation, not filler-word fidelity — vanilla
    Whisper already does punctuation well; it's CrisperWhisper's *other*
    specialty (verbatim disfluencies) that's the only reason to consider
    it here, and that's the part with no Catalan evidence behind it.

Run this only if you want to see real Catalan output from it before ruling
it out entirely. Requires a separate install this pipeline's setup_env.sh
does NOT include by default:
  pip install "crisperwhisper[ct2]"   # or [transformers] on non-NVIDIA machines

Usage:
  python scripts/whisper_transcribe/pilot_compare_crisperwhisper.py --n 15
"""
import argparse
import csv
import io
import logging
import random
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import CLIPS_TO_TRANSCRIBE_TSV, MODEL_CACHE_DIR  # noqa: E402
from pilot_transcribe import HF_BASE, PUNCT_RE, fetch_range  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pilot_compare_crisperwhisper")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--seed", type=int, default=1, help="same default as pilot_transcribe.py, for an easy side-by-side")
    parser.add_argument("--model-size", default="turbo", help="turbo (default, fastest) / small / medium / large")
    args = parser.parse_args()

    try:
        from crisperwhisper import CrisperWhisperModel
    except ImportError:
        log.error('crisperwhisper not installed. Run: pip install "crisperwhisper[ct2]"  (or [transformers])')
        return

    if not CLIPS_TO_TRANSCRIBE_TSV.exists():
        log.error("%s not found — run select_clips.py first", CLIPS_TO_TRANSCRIBE_TSV)
        return

    with CLIPS_TO_TRANSCRIBE_TSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    random.seed(args.seed)
    sample = random.sample(rows, min(args.n, len(rows)))
    log.info("sampled %d clips (seed=%d) — same sampling as pilot_transcribe.py", len(sample), args.seed)

    log.info("loading CrisperWhisper 2.0 (%s)... downloads the model on first run", args.model_size)
    model = CrisperWhisperModel(args.model_size, cache_dir=str(MODEL_CACHE_DIR))

    print("\n" + "=" * 100)
    for r in sample:
        try:
            import soundfile as sf

            url = f"{HF_BASE}/audio-{r['tar_file']}.tar"
            start, size = int(r["tar_offset"]), int(r["tar_size"])
            raw = fetch_range(url, start, start + size - 1, timeout=60)
            audio, sr = sf.read(io.BytesIO(raw))

            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
                sf.write(tmp.name, audio, sr)
                result = model.transcribe(tmp.name, language="ca", mode="verbatim")

            has_punct = bool(PUNCT_RE.search(result.text))
            print(f"\nclip {r['clip_id'][:8]}  ({r['duration']}s)  punctuation: {'YES' if has_punct else 'no'}")
            print(f"  original (candidate_1): {r['candidate_1']}")
            print(f"  crisperwhisper (verbatim): {result.text}")
        except Exception as e:
            log.warning("%s: failed: %s", r["clip_id"][:8], e)
    print("\n" + "=" * 100)
    print(
        "\nCompare against pilot_transcribe.py's output for the same seed. Listen to a few clips directly if "
        "the Catalan output looks off — there's no published evidence either way for this language."
    )


if __name__ == "__main__":
    main()
