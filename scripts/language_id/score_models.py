#!/usr/bin/env python3
"""
Scores speechbrain/lang-id-voxlingua107-ecapa and facebook/mms-lid-126
against the hand-labeled ground truth in scripts/language_id/ground_truth.tsv
(built by build_ground_truth.py, labeled via label_ui.py). See REPORT.md for
the full writeup — this docstring covers just the how-to-run.

The actual goal (GitHub issue #5) is binary: catalan vs. not — we don't care
which non-Catalan language a clip is, only whether it's Catalan. And the
asymmetric cost matters: a Catalan clip wrongly flagged non-Catalan (false
positive) silently removes good data from evaluation, while a non-Catalan
clip that slips through just gets caught later by a human evaluator like
today. So this reports false-positive-focused numbers — a plain accuracy
score would hide a model that's "94% accurate" by being confidently wrong on
exactly the Catalan clips that matter — and sweeps the P(catalan) confidence
threshold to find where false positives on the ground-truth sample hit zero,
rather than picking a threshold blind. It also breaks results down by clip
duration, since a 3s clip carries much less acoustic signal than a 20s one
and is the more plausible source of misclassifications.

Caches raw per-clip predictions to model_predictions.json (tracked in git —
small, and it's the evidence behind REPORT.md's numbers) so re-running the
threshold/duration analysis doesn't require re-running inference
(facebook/mms-lid-126 is a ~1B-param model — slow on CPU).

Usage:
  python scripts/language_id/score_models.py              # run inference (if not cached) + report
  python scripts/language_id/score_models.py --refresh     # force re-run inference
  python scripts/language_id/score_models.py --limit 10    # smoke test on a few clips
"""
import argparse
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import GROUND_TRUTH_TSV, PREDICTIONS_CACHE, LID_DIR, STRICT_THRESHOLD, LOOSE_THRESHOLD  # noqa: E402
from lid_models import run_voxlingua, run_mms  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("score_lid")

# 'unsure' rows have no reliable ground truth — excluded from scoring entirely.
NON_CATALAN_TRUTH = {"es", "en", "other"}
SCORABLE_TRUTH = NON_CATALAN_TRUTH | {"ca"}


def load_ground_truth() -> list[dict]:
    with GROUND_TRUTH_TSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    scorable = [r for r in rows if r["ground_truth_lang"] in SCORABLE_TRUTH]
    skipped = len(rows) - len(scorable)
    if skipped:
        log.info("skipping %d row(s) with no usable ground truth (unsure/blank)", skipped)
    return scorable


def get_predictions(rows: list[dict], refresh: bool) -> dict[str, dict]:
    clip_ids = [r["clip_id"] for r in rows]

    if PREDICTIONS_CACHE.exists() and not refresh:
        cached = json.loads(PREDICTIONS_CACHE.read_text())
        have = set(cached.get("voxlingua", {})) & set(cached.get("mms", {}))
        if set(clip_ids).issubset(have):
            log.info("using cached predictions from %s (%d clips)", PREDICTIONS_CACHE, len(clip_ids))
            return cached
    else:
        cached = {"voxlingua": {}, "mms": {}}

    if refresh or not PREDICTIONS_CACHE.exists():
        cached = {"voxlingua": {}, "mms": {}}
        todo = clip_ids
    else:
        todo = [cid for cid in clip_ids if cid not in cached["voxlingua"] or cid not in cached["mms"]]

    cached["voxlingua"].update(run_voxlingua(todo))
    cached["mms"].update(run_mms(todo))

    LID_DIR.mkdir(parents=True, exist_ok=True)
    PREDICTIONS_CACHE.write_text(json.dumps(cached, indent=2))
    log.info("wrote predictions cache to %s", PREDICTIONS_CACHE)
    return cached


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def confusion_at_threshold(rows: list[dict], preds: dict[str, dict], threshold: float) -> dict:
    """A clip is flagged non-catalan when P(catalan) < threshold.
    Returns counts: false_positive (truth=ca, flagged), true_positive
    (truth=non-ca, flagged), false_negative (truth=non-ca, not flagged),
    true_negative (truth=ca, not flagged)."""
    fp = tp = fn = tn = 0
    for r in rows:
        truth_ca = r["ground_truth_lang"] == "ca"
        p_ca = preds[r["clip_id"]]["p_ca"]
        flagged = p_ca < threshold
        if truth_ca and flagged:
            fp += 1
        elif truth_ca and not flagged:
            tn += 1
        elif not truth_ca and flagged:
            tp += 1
        else:
            fn += 1
    return {"fp": fp, "tn": tn, "tp": tp, "fn": fn}


def print_model_report(name: str, rows: list[dict], preds: dict[str, dict]) -> None:
    print(f"\n=== {name} ===")
    n_ca = sum(1 for r in rows if r["ground_truth_lang"] == "ca")
    n_non_ca = len(rows) - n_ca
    print(f"ground truth: {n_ca} catalan, {n_non_ca} non-catalan ({len(rows)} total)")

    print("\nP(catalan) threshold sweep (flag as non-catalan when P(catalan) < threshold):")
    print(f"{'threshold':>10} {'false pos':>10} {'FP rate':>9} {'caught':>8} {'recall':>8}")
    for threshold in (0.5, 0.3, 0.1, 0.05, 0.01, 0.005, 0.001):
        c = confusion_at_threshold(rows, preds, threshold)
        fp_rate = c["fp"] / n_ca if n_ca else 0.0
        recall = c["tp"] / n_non_ca if n_non_ca else 0.0
        print(f"{threshold:>10.3f} {c['fp']:>10} {fp_rate:>8.1%} {c['tp']:>8} {recall:>8.1%}")

    # False positives at top-1 prediction (the naive "argmax != catalan" rule)
    naive_fp = [r for r in rows if r["ground_truth_lang"] == "ca" and preds[r["clip_id"]]["top_lang"] != "ca"]
    if naive_fp:
        print(f"\ntop-1-argmax false positives ({len(naive_fp)}) — real Catalan clips the model's best guess got wrong:")
        for r in naive_fp:
            p = preds[r["clip_id"]]
            print(f"  {r['clip_id'][:8]}  dur={float(r['duration']):5.1f}s  "
                  f"predicted={p['top_lang']} (p={p['top_prob']:.2f}, p_ca={p['p_ca']:.3f})")


def print_duration_breakdown(rows: list[dict], preds_a: dict[str, dict], preds_b: dict[str, dict], threshold: float = 0.05) -> None:
    print(f"\n=== False positives by clip duration (both models, threshold={threshold}) ===")
    buckets = [(0, 5), (5, 10), (10, 15), (15, 21)]
    ca_rows = [r for r in rows if r["ground_truth_lang"] == "ca"]
    print(f"{'duration':>12} {'n catalan':>10} {'vox FP':>8} {'mms FP':>8} {'either FP':>10}")
    for lo, hi in buckets:
        bucket_rows = [r for r in ca_rows if lo <= float(r["duration"]) < hi]
        if not bucket_rows:
            continue
        vox_fp = sum(1 for r in bucket_rows if preds_a[r["clip_id"]]["p_ca"] < threshold)
        mms_fp = sum(1 for r in bucket_rows if preds_b[r["clip_id"]]["p_ca"] < threshold)
        either_fp = sum(
            1 for r in bucket_rows
            if preds_a[r["clip_id"]]["p_ca"] < threshold or preds_b[r["clip_id"]]["p_ca"] < threshold
        )
        print(f"{lo:>4}-{hi:<3}s{'':>4} {len(bucket_rows):>10} {vox_fp:>8} {mms_fp:>8} {either_fp:>10}")


def print_two_tier_report(rows: list[dict], preds_a: dict[str, dict], preds_b: dict[str, dict]) -> None:
    print(f"\n=== Two-tier vote rule: strict={STRICT_THRESHOLD} (2 votes, auto-hide) / loose={LOOSE_THRESHOLD} (1 vote, needs human) ===")
    n_ca = sum(1 for r in rows if r["ground_truth_lang"] == "ca")
    n_non_ca = len(rows) - n_ca
    two_vote_fp = two_vote_tp = 0
    one_vote_on_ca = one_vote_on_non = 0
    for r in rows:
        cid = r["clip_id"]
        p_v, p_m = preds_a[cid]["p_ca"], preds_b[cid]["p_ca"]
        truth_ca = r["ground_truth_lang"] == "ca"
        both_strict = p_v < STRICT_THRESHOLD and p_m < STRICT_THRESHOLD
        any_loose_not_both_strict = (p_v < LOOSE_THRESHOLD or p_m < LOOSE_THRESHOLD) and not both_strict
        if both_strict:
            two_vote_fp += truth_ca
            two_vote_tp += not truth_ca
        elif any_loose_not_both_strict:
            one_vote_on_ca += truth_ca
            one_vote_on_non += not truth_ca
    print(f"2-vote (auto-hide): {two_vote_fp} false positives / {n_ca} catalan clips, {two_vote_tp} caught / {n_non_ca} non-catalan ({two_vote_tp/n_non_ca:.1%})")
    print(f"1-vote (needs human): {one_vote_on_ca} extra catalan clips get a harmless single vote, {one_vote_on_non} extra non-catalan caught")
    total_caught = two_vote_tp + one_vote_on_non
    print(f"total non-catalan surfaced (either tier): {total_caught}/{n_non_ca} = {total_caught/n_non_ca:.1%}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-run inference even if cached")
    parser.add_argument("--limit", type=int, default=0, help="only score the first N rows (smoke test)")
    args = parser.parse_args()

    rows = load_ground_truth()
    if args.limit:
        rows = rows[: args.limit]
    log.info("scoring against %d labeled clips", len(rows))

    preds = get_predictions(rows, args.refresh)
    voxlingua, mms = preds["voxlingua"], preds["mms"]

    print_model_report("speechbrain/lang-id-voxlingua107-ecapa", rows, voxlingua)
    print_model_report("facebook/mms-lid-126", rows, mms)
    print_two_tier_report(rows, voxlingua, mms)
    print_duration_breakdown(rows, voxlingua, mms)


if __name__ == "__main__":
    main()
