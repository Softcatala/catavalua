# Language ID: filtering non-Catalan clips (issue #5)

Softcatala/garbellaveus#5: beta feedback found ~30% of a 10-clip sample was
Spanish or English rather than Catalan. This directory documents the
investigation into running a cheap language-ID (LID) pass over the ~900h /
231,684-clip dataset to flag non-Catalan clips before human evaluation,
without deleting anything or requiring new paid infrastructure.

## Hypothesis / goal

The actual goal is **binary**: Catalan vs. not. We don't care which
non-Catalan language a clip is in, only whether it's Catalan — so scoring
should not reward or penalize models for correctly naming the *specific*
non-Catalan language.

The cost is **asymmetric**: a Catalan clip wrongly flagged non-Catalan
(false positive) silently removes good data from evaluation. A non-Catalan
clip that slips through the filter just gets caught later by a human
evaluator, same as today — no worse than the current state. So the design
target throughout is **minimize false positives**, even at the cost of
recall, and there was a working hypothesis going in that **shorter clips
are more error-prone** (less acoustic signal for the classifier to work
with).

## Methodology

### 1. Model selection

Searched Hugging Face for spoken-LID models and deliberately picked two
that are **architecturally and data-orthogonal**, so their errors shouldn't
correlate — the same reasoning as ensembling two more-different models
being sturdier than two variants of the same one:

- **`speechbrain/lang-id-voxlingua107-ecapa`** — ECAPA-TDNN (x-vector
  style, ~20M params), trained on VoxLingua107 (weakly-labeled YouTube
  scrapes — a similar domain to this dataset). Apache-2.0. Labels are ISO
  639-1 with two known-broken codes unrelated to us (`iw`/`jw` instead of
  `he`/`jv`).
- **`facebook/mms-lid-126`** — wav2vec2 transformer (~1B params), part of
  Meta's Massively Multilingual Speech project, trained on read recordings
  of religious texts across 1000+ languages, evaluated on `google/fleurs`.
  CC-BY-NC-4.0. Labels are ISO 639-3 (`cat`/`spa`/`eng`, not `ca`/`es`/`en`
  — the two models do **not** share a label scheme, `lid_models.py`
  normalizes just the Catalan label to `ca` for both).

Neither model's card nor the MMS paper (arXiv:2305.13516, Table 7 —
aggregate accuracy 93-97% depending on benchmark/language count) publishes
a Catalan-vs-Spanish confusion rate specifically, which is exactly the pair
that matters most here (closely related languages, code-switching is
common in Catalonia). That gap is why this ground-truth exercise exists
instead of trusting published numbers.

Both output a full softmax over their language set, so **per-language
confidence is available directly** — not just a top-1 guess — which is what
makes a P(catalan) threshold rule possible instead of a cruder
top-1-argmax rule.

### 2. Ground truth (`ground_truth.tsv`, `build_ground_truth.py`, `label_ui.py`)

- `build_ground_truth.py` pulls a reproducible random sample from the
  dataset (seed 42) and downloads each clip's audio via the same
  HTTP-range tar fetch as `scripts/transcribe.py`.
- 82 more clips were added from the local dev backend's already
  auto-flagged/manually-flagged-irrelevant set (`source_id=flagged_irrelevant_local`
  in the TSV) — pulled via a clean SQLite online-backup snapshot of the
  live Docker volume (`scripts/dev-db-snapshot.sh`), never touching the
  running containers. Production was **not** included: no SSH/DB access
  to that host exists, and its API has no server-side filter for
  `isRelevant`, so a full scan would mean ~2,317 slow paginated requests
  against a shared, previously-unstable box — not worth the load for this.
- `label_ui.py` is a tiny stdlib-only local web UI (audio player + one-click
  language buttons + notes, reachable over SSH port forwarding) — no
  database, writes straight back into the TSV so labeling is resumable.
- Final ground truth: **182 clips**, hand-labeled by ear
  (`ca`=94, `es`=79, `other`=4, `en`=4, `unsure`=1 — the `unsure` row is
  excluded from all scoring).

### 3. Scoring (`score_models.py`)

Runs both models over every labeled clip (CPU only — `facebook/mms-lid-126`
is the slow one at ~10s/clip vs. ~1.5s/clip for the ECAPA model), caches raw
`P(catalan)`/top-guess/confidence per clip to `model_predictions.json`
(committed — it's small and it's the actual evidence behind every number
below), then reports a **P(catalan) threshold sweep** rather than plain
accuracy — accuracy would hide a model that's "94% accurate" by being
confidently wrong on exactly the Catalan clips that matter.

### 4. Vote-casting design

CatVoice already has a **2-votes-to-hide** mechanism
(`ClipService.flagIrrelevant`, `apps/backend/src/service/clip.service.ts`):
a clip only gets `isRelevant=false` (removed from the human evaluation
queue) once 2 distinct users/identities have flagged it via
`POST /clips/:id/flag-irrelevant`; a single flag is recorded but the clip
stays fully visible in normal evaluation. This maps directly onto the
two-model setup:

- **Both models agree, high confidence** (`P(catalan) < STRICT_THRESHOLD`
  for both) → cast a vote from **both** model identities (`lid-voxlingua`,
  `lid-mms`) → 2 votes → **auto-hidden immediately**, no human needed.
- **Either model flags it, lower confidence** (`P(catalan) < LOOSE_THRESHOLD`
  for at least one) → cast **exactly one** vote from a single shared
  identity (`lid-signal`), *regardless of how many models qualify* → clip
  stays visible, a human evaluator sees it completely normally and can
  independently flag it to push the count to 2, or just ignore it.

The "exactly one, shared identity" detail matters: if the loose tier
instead cast per-model votes, any clip where both models independently
(but only weakly) agreed would rack up 2 distinct-username votes and
auto-hide anyway — silently reintroducing the higher-threshold
false-positive risk. Gating the *only* path to auto-hide behind the strict,
validated-safe joint condition is what keeps the false-positive guarantee
intact regardless of how the loose threshold is tuned.

## Results

### Threshold sweep (181 scorable clips: 94 catalan / 87 non-catalan)

| rule | threshold | false positives | non-catalan caught |
|---|---|---|---|
| VoxLingua-ECAPA alone | 0.05 | 0/94 | 25/87 (29%) |
| MMS-lid-126 alone | 0.01 | 0/94 | 20/87 (23%) |
| Both models agree | 0.05 | 0/94 | 19/87 (22%) |
| Both models agree | 0.10 | 1/94 | 32/87 (37%) |

A real example shows why the two-model combo earns its keep: a 20s clip
where VoxLingua confidently (78%) guessed Spanish, but MMS correctly called
it Catalan at 96% confidence — MMS's disagreement saved that clip from
being wrongly flagged by VoxLingua alone.

Caveat: 0/94 observed false positives is not 0% true rate — with this
sample size the honest upper bound on the true rate is closer to ~3%
(rule of three). This is exactly why the vote-not-delete design matters:
even the "safe" tier stays reversible/human-confirmable rather than being
treated as a hard filter.

### Duration hypothesis: confirmed

Every false positive across both models, at every threshold tested,
occurred on a clip **≤9.2s**. Every 5-21s duration bucket had zero false
positives from either model at threshold 0.05; the two false positives in
that bucket were both <5s. The single worst miss over 10s (the 20s
VoxLingua/Spanish example above) was caught and corrected by MMS agreeing
with the ground truth instead. Misclassification risk is concentrated
almost entirely in clips under ~10s, and especially under 5s.

### Two-tier rule sweep (chosen: STRICT=0.05, LOOSE=0.1)

| loose threshold | 2-vote (auto-hide) | 1-vote (needs human) extra catalan tagged | extra non-catalan caught | **total non-catalan surfaced** |
|---|---|---|---|---|
| 0.5 | 0 FP, 19 caught | 9 | 63 | 82/87 = 94.3% |
| 0.3 | 0 FP, 19 caught | 9 | 59 | 78/87 = 89.7% |
| 0.2 | 0 FP, 19 caught | 5 | 54 | 73/87 = 83.9% |
| **0.1** | **0 FP, 19 caught** | **3** | **44** | **63/87 = 72.4%** |

The 2-vote (auto-hide) false-positive count is identical across every row —
structurally, since it's gated on STRICT=0.05 regardless of the loose
threshold. **0.1 was chosen** as the most conservative option that still
surfaces most non-Catalan clips: 0 clips wrongly auto-hidden, 22% of
non-Catalan clips auto-hidden immediately, 72% get at least one vote
(the rest still get caught by normal human evaluation, unchanged from
today), and only 3 real Catalan clips pick up a single harmless vote that a
human would simply not confirm.

### Representativeness check (`detect_language.py`, no `--apply`)

The 181-clip ground truth isn't a pure random sample — 82 of its clips were
deliberately pulled from the already-flagged-irrelevant set, which skews
its non-Catalan rate well above the true population rate. The pure
`source=random_sample` subset (100 clips) puts the population non-Catalan
rate at **23%** (77 catalan / 23 non-catalan).

`detect_language.py --n 300` draws a fresh, uniformly random sample
excluding every clip already in `ground_truth.tsv` — genuinely unseen data
— scores it with the same two models and thresholds, and compares the
observed tier-2/tier-1+ rates against what the ground-truth-derived catch
rates would predict for a sample at the true 23% non-Catalan population
rate. See `detect_sample.tsv` for the raw per-clip output.

Result, on 300 fresh clips:

| | expected (from ground truth + 23% population rate) | observed |
|---|---|---|
| tier 2 (auto-hide) | 5.0% | 6.7% (20/300) |
| tier 1+ (any vote) | 19.1% | 19.7% (59/300) |

Both observed rates land close to their predicted values — at n=300 the
standard error on a ~5-20% proportion is roughly 1-2 percentage points, so
these differences are within normal sampling noise, not a sign of drift or
overfitting. This is a good sign that the 181-clip ground truth is
representative of the wider dataset and that the thresholds tuned against
it generalize to unseen clips, at least at this sample size.

### Manual review of all 59 flagged clips (`review_ui.py`)

`ground_truth.tsv` measures false-positive *recall* (of all real Catalan
clips, how many get wrongly flagged). It can't directly measure the
auto-hide tier's real-world *precision* (of clips that actually get
flagged, how many are wrongly flagged), because the 300-clip detect run's
flagged subset wasn't part of the labeled ground truth. So every one of the
59 clips `detect_language.py --n 300` flagged (tier 1 or 2) was reviewed by
ear (`review_ui.py`) — a hand-labeled correct/false-positive verdict on
exactly the clips the two-tier rule would actually act on.

Result: **8/59 false positives** (51 correct). Broken down by tier:

| tier | correct | false positive | precision |
|---|---|---|---|
| 2 (auto-hide) | 19 | 1 | **95.0%** (19/20) |
| 1 (single vote) | 32 | 7 | 82.1% (32/39) |

The single tier-2 false positive (`3c8261fd`, 4.8s — *"si la senyora
martínez de senyor fernàndez"*) is a genuinely hard case rather than random
noise: the clip is dominated by Spanish-origin surnames inside a Catalan
sentence, and it's short — consistent with the duration finding above. This
95% tier-2 precision is a *complementary* measurement to the ground truth's
0/94 (0%, ≤~3% upper bound) false-positive *rate* — different statistic,
same conclusion: the auto-hide tier is strong but not literally perfect,
which is exactly why votes (reversible, human-confirmable) were chosen over
a hard delete.

Breaking the tier-1 false positives down by which model triggered them
(the other model stayed above the loose threshold) surfaces a real but
thin signal:

| trigger | correct | false positive | precision | n |
|---|---|---|---|---|
| both cross loose (incl. all tier-2) | 26 | 1 | 96.3% | 27 |
| VoxLingua alone | 5 | 2 | 71.4% | 7 |
| MMS alone | 20 | 5 | 80.0% | 25 |

MMS's solo flags look more trustworthy than VoxLingua's (80% vs. 71%), and
VoxLingua's two solo misses — like its one miss in the original ground
truth — skewed toward a longer clip (16s) that MMS correctly leaned Catalan
on. But `vox_only` is only 7 clips; one flipped verdict swings that
precision figure by ~14 points, so this doesn't clear the bar for adding
per-model thresholds or weighting one model over the other yet. What the
data supports clearly is something the two-tier rule already captures
structurally: **agreement between the two models is a far stronger signal
than either model's solo opinion** (96% vs. 71-80%) — that gap is bigger
and better-evidenced than any asymmetry between the models themselves.
Revisiting per-model weighting would need materially more `vox_only`/
`mms_only` examples (20-30+ each) before it's a data-backed decision rather
than a guess dressed up as one.

### Full-dataset run (RunPod GPU pod)

Scoring the remaining 231,202 clips (everything not already in
`ground_truth.tsv`/`detect_sample.tsv`) locally on CPU would have taken
~30 days — see `pod/README.md`. Instead, ran on a rented RunPod A40 GPU pod
(secure cloud, EU-SE-1, $0.44/hr):

- Downloaded all 51 HF tar files locally to the pod (~100GB, resumable —
  `pod/download_tars.sh`) so audio reads are a local file seek instead of
  231k individual HTTP requests.
- Batched CUDA inference (`pod/batch_models.py`), correctness-validated
  against the cached unbatched CPU predictions before ever touching the
  pod (`pod/validate_batching.py`): mms-lid-126 matched exactly (0.0
  diff), VoxLingua-ECAPA had negligible float noise (max diff 0.0165)
  with zero decision disagreements at either threshold, on 40
  ground-truth clips.
- `pod/run_full_detection.py` is idempotent and interruptible by design —
  incremental writes flushed per batch, skips already-processed clips on
  restart — and wrote its output to the pod's persistent `/workspace`
  volume specifically (not the ephemeral container disk the tar files
  lived on), so an unplanned pod restart mid-run would have lost at most
  the downloaded tars (cheap to redo) and never the accumulating results.

**Result**: sustained **9.9 clips/sec**, all 231,202 clips scored in
**~6.5 hours** (**~$3.11** total pod cost, including setup/download time).
Output integrity fully verified before trusting it: exact row count, no
malformed rows, all `tier` values in {0,1,2}, all `p_ca_*` values in
[0,1], no duplicate `clip_id`s, and an MD5 checksum match between the
pod's copy and the one pulled back locally. 231,202 + 482
(ground-truth/reviewed clips) = 231,684 — the complete dataset, every
clip accounted for exactly once.

| tier | count | % |
|---|---|---|
| 2 (auto-hide) | 20,070 | 8.68% |
| 1 (single vote) | 30,689 | 13.27% |
| 0 (nothing) | 180,443 | 78.05% |

Consistent with the 300-clip representativeness check throughout the run
(~8-9% / ~13% split held steady from the first progress checkpoint to the
last). Output lives at `data/language_id/full_detect.tsv` (gitignored,
~51MB — too large to track like the curated `ground_truth.tsv`).

### Votes cast against the local dev container

`detect_language.py --apply` gained an `--input` flag so it can act on
`full_detect.tsv` instead of just `detect_sample.tsv`. Dry-run confirmed
the expected job size: 20,070×2 + 30,689×1 = **70,829 vote requests**
(`POST /clips/:id/flag-irrelevant`, reason `not_catalan`).

Cast against the local dev container only (`http://localhost:3000`) —
production was deliberately excluded, consistent with every other
production-touching decision in this investigation (no verified access,
no rush to act on it without separately deciding how). Ran at
concurrency=100 while watching `docker stats catvoice-backend`: CPU
stayed under 1% throughout, negligible load on the container.

**Result**: all 70,829/70,829 votes cast successfully, **zero errors**, in
~8m47s (~134 votes/sec). Spot-checked against the live API afterward: a
sampled tier-2 clip shows `isRelevant: 0` with netVotes -2 from both model
identities (auto-hidden, as designed); a sampled tier-1 clip shows
`isRelevant: 1` (still fully visible to evaluators) with netVotes -1 from
the single shared identity — needs one more flag, model or human, to
disappear. `GET /votes/stats` reports `flaggedIrrelevant: 50,776`, which
reconciles exactly: 20,070 + 30,689 = 50,759 newly-flagged clips from this
run, plus the 17 pre-existing relevance-flagged clips from before this
investigation (folded into `ground_truth.tsv` and correctly excluded from
the full run as a separate, non-overlapping set) = 50,776.

Production was not touched — this apply run targeted `http://localhost:3000`
(the local dev container) only.

## Open items / next steps

- **Production was not covered by the ground truth** — no SSH/DB access
  exists to `catavalua.softcatala.org`, and its API can't filter by
  `isRelevant` server-side. If English/other-language clips specifically
  from production ever need adding to `ground_truth.tsv`, that requires
  either DB access being granted or accepting a slow full-pagination scan.
- **`--apply` has not been run.** `detect_language.py --apply` casts real
  votes against a running backend using the identities above — reviewed
  and intentionally not invoked yet.
- Consider expanding `ground_truth.tsv` (more labeled clips) to tighten the
  ~3% false-positive upper-bound confidence interval before trusting this
  at full dataset scale.
- Consider special-casing clips under ~5-10s given the duration finding —
  e.g. requiring an even stricter threshold, or skipping automated flagging
  entirely, for the shortest clips.
- **Per-model weighting/thresholds deliberately not adopted yet** — the
  `vox_only`/`mms_only` precision gap (71% vs. 80%) is suggestive but only
  7 and 25 samples respectively. Keep running `detect_language.py` +
  `review_ui.py` on fresh batches to build up enough `vox_only`/`mms_only`
  examples (20-30+ each) before deciding whether that gap is real.

## Files in this directory

| file | tracked? | purpose |
|---|---|---|
| `REPORT.md` | yes | this document |
| `ground_truth.tsv` | yes | 182 hand-labeled clips |
| `model_predictions.json` | yes | cached raw model outputs for `ground_truth.tsv` (small, reproducible evidence) |
| `detect_sample.tsv` | yes | fresh 300-clip holdout run + manual review verdicts on all 59 flagged clips |
| `paths.py` | yes | shared path/threshold constants |
| `hf_audio.py` | yes | shared HTTP-range audio fetch |
| `lid_models.py` | yes | shared model-inference code for both candidate models |
| `build_ground_truth.py` | yes | builds/extends `ground_truth.tsv` |
| `label_ui.py` | yes | local web UI for hand-labeling |
| `score_models.py` | yes | scores both models against `ground_truth.tsv`, prints the tables above |
| `detect_language.py` | yes | detect (TSV, no votes) / `--apply` (casts votes) against a live backend |
| `review_ui.py` | yes | local web UI for hand-reviewing flagged (tier ≥1) clips in `detect_sample.tsv` for false positives |
| `pod/` | yes | RunPod GPU deployment scripts for the full-dataset run — see `pod/README.md` |
| `../../data/language_id/audio/` | **no** (gitignored) | downloaded clip audio — regenerable from `clip_id` via the HF tar index |
| `../../data/language_id/.model_cache/` | **no** (gitignored) | downloaded model weights — regenerable from HuggingFace |
| `../../data/language_id/full_detect.tsv` | **no** (gitignored, ~51MB) | all 231,202 non-ground-truth clips scored — output of the full pod run |
