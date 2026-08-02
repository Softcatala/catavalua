# Running full-dataset detection on a RunPod GPU pod

Why: scoring all 231,684 clips with both models takes ~30 days of
continuous CPU compute locally (see `../REPORT.md`). A GPU pod with
batched inference and locally-downloaded audio (no per-clip HTTP request)
brings that down to an estimated few hours, for an estimated few dollars.

Batching correctness was validated locally against the already-labeled
`../ground_truth.tsv` before this ever touched a pod — see
`validate_batching.py` and its results in `../REPORT.md`. Re-run it after
any change to `batch_models.py`.

## Sequence

1. **Provision the pod** — A40, secure cloud, `CA-MTL-1` or `EU-SE-1`
   (both HIGH A40 availability), `containerDiskInGb: 120` (dataset is
   ~107GB), "Runpod Pytorch 2.8.0" image or similar (CUDA + torch
   preinstalled).

2. **Copy this repo's `scripts/language_id/` directory** to the pod (e.g.
   `rsync -av scripts/language_id/ pod:~/catvoice/scripts/language_id/`) —
   `run_full_detection.py` imports from `../paths.py` and the other
   shared modules, so the directory structure needs to come along, not
   just the `pod/` subfolder.

3. **On the pod**, set up the environment:
   ```bash
   bash scripts/language_id/pod/setup_env.sh
   source /workspace/venv/bin/activate
   ```

4. **Download the dataset** (resumable — safe to re-run/interrupt):
   ```bash
   bash scripts/language_id/pod/download_tars.sh /workspace/tars 4
   ```
   ~107GB; expect well under an hour on datacenter bandwidth. `4` is the
   parallel-download count — raise it if the pod's network allows.

5. **Run detection** (idempotent + interruptible — safe to Ctrl+C and
   re-run, it resumes from whatever's already in `--out`):
   ```bash
   python scripts/language_id/pod/run_full_detection.py \
     --tar-dir /workspace/tars \
     --out /workspace/full_detect.tsv \
     --device cuda \
     --batch-size 16
   ```
   Watch the logged `clips/sec` and `ETA` — if the real throughput is way
   off the ~20-50 clips/sec estimate in `REPORT.md`, stop and reconsider
   `--batch-size` before letting it run for hours unattended.

6. **Copy `full_detect.tsv` back** to this repo's `data/language_id/`
   (gitignored — it's ~60-70MB for the full dataset, too large/bulky to
   track like the curated `ground_truth.tsv`/`detect_sample.tsv`).

7. **Terminate the pod** once `full_detect.tsv` is safely copied back —
   nothing here needs the pod to stay running.

## Files

| file | purpose |
|---|---|
| `download_tars.sh` | resumable parallel download of all 51 HF tar files |
| `setup_env.sh` | one-time pod environment setup |
| `local_audio.py` | reads clip audio via local file seek instead of HTTP range |
| `batch_models.py` | batched, CUDA-capable inference for both models |
| `run_full_detection.py` | main driver — idempotent, interruptible, incremental writes |
| `validate_batching.py` | correctness check: batched vs. cached unbatched predictions |
