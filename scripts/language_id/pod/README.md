# Running full-dataset detection on a rented GPU machine

Why: scoring all 231,684 clips with both models takes ~30 days of
continuous CPU compute locally (see `../REPORT.md`). A rented GPU machine
with batched inference and locally-downloaded audio (no per-clip HTTP
request) brings that down to a few hours, for a few dollars.

Batching correctness was validated locally against the already-labeled
`../ground_truth.tsv` before this ever touched a rented machine — see
`validate_batching.py` and its results in `../REPORT.md`. Re-run it after
any change to `batch_models.py`.

## Sequence

1. **Provision a GPU machine** — a single mid-range datacenter GPU (48GB
   VRAM is comfortably more than either model needs) is enough; a
   PyTorch + CUDA base image saves installing those from scratch. Size the
   machine's own local disk to at least ~120GB (dataset is ~107GB) —
   that's where the tar files go, not any smaller persistent/network
   volume the provider might separately offer.

2. **Copy this repo's `scripts/language_id/` directory** to the machine
   (e.g. `rsync -av scripts/language_id/ gpu-machine:~/catvoice/scripts/language_id/`)
   preserving the same relative path depth (`.../scripts/language_id/`) —
   `run_full_detection.py` imports from `../paths.py` and the other shared
   modules, so the directory structure needs to come along, not just the
   `pod/` subfolder.

3. **On the machine**, set up the environment:
   ```bash
   bash scripts/language_id/pod/setup_env.sh
   source ~/venv/bin/activate
   ```

4. **Download the dataset** to local disk, not any smaller persistent
   volume (resumable — safe to re-run/interrupt):
   ```bash
   bash scripts/language_id/pod/download_tars.sh ~/tars 6
   ```
   ~107GB; expect well under an hour on datacenter bandwidth. The second
   argument is the parallel-download count — raise it if the network
   allows.

5. **Run detection** (idempotent + interruptible — safe to Ctrl+C and
   re-run, it resumes from whatever's already in `--out`). Point `--out`
   at whichever storage on the machine actually survives a restart (a
   persistent/network volume if the provider separates that from the
   machine's local disk) — the downloaded tars are cheap to redo if lost,
   but hours of accumulated results are not:
   ```bash
   nohup python scripts/language_id/pod/run_full_detection.py \
     --tar-dir ~/tars \
     --out /path/to/persistent/storage/full_detect.tsv \
     --device cuda:0 \
     --batch-size 16 \
     --cache-dir ~/.model_cache \
     < /dev/null > ~/full_run.log 2>&1 &
   disown
   ```
   Watch the logged `clips/sec` and `ETA`. This repo's own run sustained
   ~9.9 clips/sec — see `REPORT.md` for the full result and cost.

6. **Copy the output back** to this repo's `data/language_id/`
   (gitignored — it's ~50MB for the full dataset, too large/bulky to
   track like the curated `ground_truth.tsv`/`detect_sample.tsv`). Verify
   its integrity (row count, field count, tier/probability ranges,
   checksum against the remote copy) before trusting it.

7. **Terminate the machine** once the output is safely copied back and
   verified, and confirm no separate storage volume is still
   provisioned/billing — nothing here needs the machine to stay running.

## Files

| file | purpose |
|---|---|
| `download_tars.sh` | resumable parallel download of all 51 HF tar files |
| `setup_env.sh` | one-time environment setup |
| `local_audio.py` | reads clip audio via local file seek instead of HTTP range |
| `batch_models.py` | batched, CUDA-capable inference for both models |
| `run_full_detection.py` | main driver — idempotent, interruptible, incremental writes |
| `validate_batching.py` | correctness check: batched vs. cached unbatched predictions |
