#!/usr/bin/env python3
"""
Correctness check for batch_models.py's batching/padding logic: runs a
sample of ground_truth.tsv clips through the batched code path on CPU
(no GPU available locally) and compares P(catalan) against
../model_predictions.json — the already-validated, unbatched, per-clip
predictions the whole report's numbers are based on.

This can't test CUDA speed (no local GPU), only that batching+padding
doesn't silently corrupt predictions before this code ever touches a
billed pod. Run before every pod deployment that changes batch_models.py.

Usage:
  python validate_batching.py --n 40 --batch-size 8
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent))
from paths import GROUND_TRUTH_TSV, PREDICTIONS_CACHE, AUDIO_DIR, STRICT_THRESHOLD, LOOSE_THRESHOLD  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from batch_models import load_mms, run_mms_batch, load_voxlingua, run_voxlingua_batch  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--cache-dir", default=str(Path(__file__).parent.parent.parent.parent / "data" / "language_id" / ".model_cache"))
    args = parser.parse_args()

    rows = list(csv.DictReader(GROUND_TRUTH_TSV.open(newline="", encoding="utf-8"), delimiter="\t"))
    rows = [r for r in rows if r["ground_truth_lang"] in ("ca", "es", "en", "other")][: args.n]
    cached = json.loads(PREDICTIONS_CACHE.read_text())

    print(f"loading models on CPU (batch_size={args.batch_size})...")
    mms_processor, mms_model, mms_ca_idx = load_mms("cpu", cache_dir=f"{args.cache_dir}/mms")
    vox_clf, vox_ca_idx = load_voxlingua("cpu", savedir=f"{args.cache_dir}/voxlingua")

    batched_vox: dict[str, float] = {}
    batched_mms: dict[str, float] = {}
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i : i + args.batch_size]
        audios = [sf.read(str(AUDIO_DIR / f"{r['clip_id']}.wav"))[0] for r in batch]
        p_mms = run_mms_batch(mms_processor, mms_model, mms_ca_idx, "cpu", audios)
        p_vox = run_voxlingua_batch(vox_clf, vox_ca_idx, "cpu", audios)
        for r, pv, pm in zip(batch, p_vox, p_mms):
            batched_vox[r["clip_id"]] = pv
            batched_mms[r["clip_id"]] = pm
        print(f"  {min(i+args.batch_size, len(rows))}/{len(rows)}")

    for name, batched, original in (("voxlingua", batched_vox, cached["voxlingua"]), ("mms", batched_mms, cached["mms"])):
        diffs = [abs(batched[cid] - original[cid]["p_ca"]) for cid in batched]
        print(f"\n=== {name}: batched (CPU) vs. cached unbatched (CPU) ===")
        print(f"max abs diff: {max(diffs):.5f}, mean abs diff: {statistics.mean(diffs):.5f}")
        for thresh in (STRICT_THRESHOLD, LOOSE_THRESHOLD):
            disagree = sum(1 for cid in batched if (batched[cid] < thresh) != (original[cid]["p_ca"] < thresh))
            print(f"  threshold={thresh}: {disagree}/{len(batched)} decision disagreements")


if __name__ == "__main__":
    main()
