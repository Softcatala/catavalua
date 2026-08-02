#!/usr/bin/env python3
"""
Applies the two-tier language-ID vote rule (see REPORT.md) to a fresh random
sample of clips that are NOT in ground_truth.tsv — genuinely unseen data,
used to sanity-check that the thresholds tuned against the 181-clip ground
truth (in score_models.py) generalize, rather than just fitting that sample,
and that the ground truth's observed non-Catalan rate is representative of
the wider dataset.

Two-tier rule (thresholds from paths.py, tuned against ground_truth.tsv):
  - both models' P(catalan) < STRICT_THRESHOLD  -> tier 2: cast a vote from
    BOTH model identities (2 votes -> clip.is_relevant flips to false
    immediately, per ClipService.flagIrrelevant's 2-flags-to-hide rule)
  - either model's P(catalan) < LOOSE_THRESHOLD  -> tier 1: cast ONE vote
    from a single shared identity, regardless of how many models qualify —
    this is what preserves the false-positive-safe guarantee: a clip can
    only ever get 2 votes out of *this* pipeline when both models
    independently clear the strict bar together, never from two models each
    independently clearing just the loose one.
  - otherwise -> tier 0: nothing cast.

Usage:
  # Detect-only (default): sample + score + write a TSV for review, cast no votes.
  python scripts/language_id/detect_language.py --n 300

  # After reviewing detect_sample.tsv, actually cast votes against a running backend:
  python scripts/language_id/detect_language.py --apply --api-url http://localhost:3000 [--dry-run]
"""
import argparse
import csv
import json
import logging
import random
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import (  # noqa: E402
    AUDIO_DIR, GROUND_TRUTH_TSV, DETECT_SAMPLE_TSV, LID_DIR,
    STRICT_THRESHOLD, LOOSE_THRESHOLD,
)
from hf_audio import fetch_audio, load_tar_index, load_clips_rows  # noqa: E402
from lid_models import run_voxlingua, run_mms  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("detect_language")

FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "p_ca_voxlingua", "p_ca_mms", "tier"]

VOTE_USERNAME_VOXLINGUA = "lid-voxlingua"
VOTE_USERNAME_MMS = "lid-mms"
VOTE_USERNAME_SIGNAL = "lid-signal"  # shared identity for the loose, single-vote tier
FLAG_REASON = "not_catalan"


# ---------------------------------------------------------------------------
# Sampling + scoring
# ---------------------------------------------------------------------------

def _fetch_one(row: dict, index: dict[str, dict]) -> tuple[dict, bool, str | None]:
    clip_id = row["clip_id"]
    dest = AUDIO_DIR / f"{clip_id}.wav"
    if dest.exists():
        return row, True, None
    try:
        fetch_audio(index[clip_id], dest)
        return row, True, None
    except Exception as e:
        return row, False, str(e)


def sample_fresh_clips(n: int, seed: int) -> list[dict]:
    index = load_tar_index()
    rows = load_clips_rows()

    excluded_ids: set[str] = set()
    if GROUND_TRUTH_TSV.exists():
        with GROUND_TRUTH_TSV.open(newline="", encoding="utf-8") as f:
            excluded_ids = {r["clip_id"] for r in csv.DictReader(f, delimiter="\t")}
        log.info("excluding %d clips already in %s (keeps this a genuine holdout)", len(excluded_ids), GROUND_TRUTH_TSV)

    candidates = [r for r in rows if r["clip_id"] in index and r["clip_id"] not in excluded_ids]
    random.seed(seed)
    sample = random.sample(candidates, min(n, len(candidates)))
    log.info("sampled %d fresh clips (seed=%d)", len(sample), seed)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, r, index): r for r in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            row, ok, err = fut.result()
            if ok:
                results.append(row)
            else:
                log.warning("%s: fetch failed: %s", row["clip_id"][:8], err)
            if i % 20 == 0 or i == len(sample):
                log.info("audio fetch: %d/%d (%d ok)", i, len(sample), len(results))
    return results


def tier_for(p_ca_vox: float, p_ca_mms: float) -> int:
    if p_ca_vox < STRICT_THRESHOLD and p_ca_mms < STRICT_THRESHOLD:
        return 2
    if p_ca_vox < LOOSE_THRESHOLD or p_ca_mms < LOOSE_THRESHOLD:
        return 1
    return 0


def run_detection(rows: list[dict]) -> list[dict]:
    clip_ids = [r["clip_id"] for r in rows]
    voxlingua = run_voxlingua(clip_ids)
    mms = run_mms(clip_ids)

    out = []
    for r in rows:
        cid = r["clip_id"]
        p_v, p_m = voxlingua[cid]["p_ca"], mms[cid]["p_ca"]
        out.append({
            "clip_id": cid,
            "duration": r.get("duration", ""),
            "yt_url": r.get("yt_url", ""),
            "candidate_1": (r.get("candidate_1") or "")[:120],
            "p_ca_voxlingua": round(p_v, 4),
            "p_ca_mms": round(p_m, 4),
            "tier": tier_for(p_v, p_m),
        })
    return out


# ---------------------------------------------------------------------------
# Representativeness check against ground_truth.tsv
# ---------------------------------------------------------------------------

def print_representativeness_check(detected: list[dict]) -> None:
    n = len(detected)
    tier2 = sum(1 for r in detected if r["tier"] == 2)
    tier1plus = sum(1 for r in detected if r["tier"] >= 1)
    print(f"\n=== Detected on {n} fresh (unseen) clips ===")
    print(f"tier 2 (auto-hide, 2 votes): {tier2}/{n} = {tier2/n:.1%}")
    print(f"tier 1+ (any vote):          {tier1plus}/{n} = {tier1plus/n:.1%}")

    if not (GROUND_TRUTH_TSV.exists() and (LID_DIR / "model_predictions.json").exists()):
        log.info("no ground_truth.tsv + cached predictions to compare against — skipping representativeness check")
        return

    gt_rows = list(csv.DictReader(GROUND_TRUTH_TSV.open(newline="", encoding="utf-8"), delimiter="\t"))
    random_only = [r for r in gt_rows if r["source"] == "random_sample" and r["ground_truth_lang"] in ("ca", "es", "en", "other")]
    if not random_only:
        return
    non_ca_rate = sum(1 for r in random_only if r["ground_truth_lang"] != "ca") / len(random_only)

    preds = json.loads((LID_DIR / "model_predictions.json").read_text())
    scorable = [r for r in gt_rows if r["ground_truth_lang"] in ("ca", "es", "en", "other")]
    n_ca = sum(1 for r in scorable if r["ground_truth_lang"] == "ca")
    n_non_ca = len(scorable) - n_ca
    tier2_tp = tier2_fp = tier1_tp = tier1_fp = 0
    for r in scorable:
        cid = r["clip_id"]
        if cid not in preds["voxlingua"] or cid not in preds["mms"]:
            continue
        p_v, p_m = preds["voxlingua"][cid]["p_ca"], preds["mms"][cid]["p_ca"]
        truth_ca = r["ground_truth_lang"] == "ca"
        t = tier_for(p_v, p_m)
        if t == 2:
            tier2_fp += truth_ca
            tier2_tp += not truth_ca
        elif t == 1:
            tier1_fp += truth_ca
            tier1_tp += not truth_ca

    catch_2 = tier2_tp / n_non_ca if n_non_ca else 0.0
    catch_1plus = (tier2_tp + tier1_tp) / n_non_ca if n_non_ca else 0.0
    signal_fp_rate = tier1_fp / n_ca if n_ca else 0.0  # real catalan clips that pick up a harmless single vote

    expected_tier2 = non_ca_rate * catch_2
    expected_tier1plus = non_ca_rate * catch_1plus + (1 - non_ca_rate) * signal_fp_rate

    print(f"\n=== Representativeness check ===")
    print(f"population non-catalan rate, estimated from {len(random_only)} pure-random ground-truth clips: {non_ca_rate:.1%}")
    print(f"ground-truth catch rates at these thresholds: tier2={catch_2:.1%} of non-catalan, tier1+={catch_1plus:.1%} of non-catalan")
    print(f"expected fresh-sample tier-2 rate:  {expected_tier2:.1%}   (observed: {tier2/n:.1%})")
    print(f"expected fresh-sample tier-1+ rate: {expected_tier1plus:.1%}   (observed: {tier1plus/n:.1%})")
    print(
        "\nIf observed is well outside expected, that's a signal the ground truth sample (181 clips) isn't "
        "representative of the wider dataset, or the thresholds are overfit to it — worth a bigger ground truth "
        "sample before trusting --apply at scale."
    )


# ---------------------------------------------------------------------------
# --apply: cast votes against a running backend
# ---------------------------------------------------------------------------

def http_post(url: str, timeout: int = 15, retries: int = 3) -> dict:
    delay = 5
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt < retries:
                import time
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise e


def flag_irrelevant(api_url: str, clip_id: str, username: str) -> str:
    url = f"{api_url}/clips/{clip_id}/flag-irrelevant?username={username}&reason={FLAG_REASON}"
    try:
        http_post(url)
        return "voted"
    except Exception as e:
        return f"error:{e}"


def cmd_apply(args):
    if not DETECT_SAMPLE_TSV.exists():
        log.error("run detect_language.py without --apply first to produce %s", DETECT_SAMPLE_TSV)
        return
    rows = list(csv.DictReader(DETECT_SAMPLE_TSV.open(newline="", encoding="utf-8"), delimiter="\t"))
    tier2 = [r for r in rows if int(r["tier"]) == 2]
    tier1 = [r for r in rows if int(r["tier"]) == 1]
    log.info("%d clips at tier 2 (2 votes each), %d at tier 1 (1 vote each)", len(tier2), len(tier1))
    log.info("target API: %s%s", args.api_url, " (dry run)" if args.dry_run else "")

    if args.dry_run:
        log.info("would cast %d votes total (dry run, no requests made)", len(tier2) * 2 + len(tier1))
        return

    jobs = []
    for r in tier2:
        jobs.append((r["clip_id"], VOTE_USERNAME_VOXLINGUA))
        jobs.append((r["clip_id"], VOTE_USERNAME_MMS))
    for r in tier1:
        jobs.append((r["clip_id"], VOTE_USERNAME_SIGNAL))

    voted = errors = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(flag_irrelevant, args.api_url, cid, user): (cid, user) for cid, user in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result == "voted":
                voted += 1
            else:
                errors += 1
                log.warning("%s: %s", futures[fut], result)
            if i % 100 == 0:
                log.info("%d/%d done (%d voted, %d errors)", i, len(jobs), voted, errors)
    log.info("cast %d/%d votes (%d errors)", voted, len(jobs), errors)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=300, help="fresh sample size for detect mode (default 300)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default 1 — different from build_ground_truth.py's 42, so this is a distinct sample)")
    parser.add_argument("--apply", action="store_true", help="cast votes from detect_sample.tsv instead of detecting")
    parser.add_argument("--api-url", default="http://localhost:3000")
    parser.add_argument("--dry-run", action="store_true", help="with --apply, log what would happen without casting votes")
    parser.add_argument("--concurrency", type=int, default=10, help="parallel requests for --apply (default 10)")
    args = parser.parse_args()

    if args.apply:
        cmd_apply(args)
        return

    rows = sample_fresh_clips(args.n, args.seed)
    log.info("running both models on %d clips…", len(rows))
    detected = run_detection(rows)

    LID_DIR.mkdir(parents=True, exist_ok=True)
    with DETECT_SAMPLE_TSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(detected)
    log.info("wrote %s (%d rows)", DETECT_SAMPLE_TSV, len(detected))

    print_representativeness_check(detected)
    log.info("detect-only run — no votes cast. Review %s, then re-run with --apply when ready.", DETECT_SAMPLE_TSV)


if __name__ == "__main__":
    main()
