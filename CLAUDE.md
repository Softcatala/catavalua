# CatVoice

Human evaluation platform for the [softcatala/catalan-youtube-speech](https://huggingface.co/datasets/softcatala/catalan-youtube-speech) dataset.

## Project Layout

```
apps/backend/      NestJS + SQLite (TypeORM) — runs in Docker
apps/frontend/     React + Vite + Tailwind — runs in Docker
scripts/           Python transcription pipeline (runs on host)
data/              SQLite DB + tar_index.json + temp audio files
```

## Running Things

```bash
# Install deps
pnpm install

# Dev (backend on :3000, frontend on :5173)
pnpm dev:backend
pnpm dev:frontend

# Production (Docker)
docker compose up -d --build
```

## Transcription Pipeline (scripts/transcribe.py)

**Step 1 — Build TAR index (run once):**

```bash
python scripts/transcribe.py --build-index-only
```

This reads headers from all 51 tar files via HTTP range requests and saves
`data/tar_index.json` (clip_id → tar_file, byte offset, size).
It takes several minutes due to ~2000 range requests per tar file.

**Step 2 — Post index to backend:**

```bash
python scripts/transcribe.py --post-index
```

Updates all clip records in the DB with their audio positions.

**Step 3 — Transcribe:**

```bash
# Process all clips (run repeatedly — it's idempotent)
python scripts/transcribe.py

# Process N clips
python scripts/transcribe.py --max 100

# Different backend URL
python scripts/transcribe.py --api-url http://localhost:3000
```

The script:
- Reads clips from the HuggingFace dataset API (paginated, no full download)
- Fetches each audio clip from the tar file using HTTP range (one clip at a time)
- Runs `gemini --yolo` with the audio file path (Gemini reads it via file tool)
- Runs `claude --dangerously-skip-permissions -p` with text-only candidate transcriptions
- POSTs both results to the backend
- Deletes the temp WAV file immediately after (win or fail)
- Exponential backoff on CLI rate limit errors (5s → 10s → 20s → 40s → 120s)

## Audio Format

- TAR files: `audio-0.tar` … `audio-50.tar` (~2.1 GB each, ~107 GB total)
- Audio format inside: WAV, named `audio/{clip_id}.wav`
- HF URL: `https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main/audio-N.tar`
- The backend serves audio by proxying range requests to HuggingFace

## Dataset Schema

From HuggingFace (via Parquet/API):
- `clip_id` — UUID, primary key
- `source_id` — source YouTube video UUID
- `duration` — seconds (3–20s)
- `start`, `end` — timestamp in source video
- `gender` — `male` | `female`
- `candidate_1`, `candidate_2` — ASR transcription candidates
- `yt_url` — YouTube URL with timestamp
- `license` — CC-BY

## Voting System

- Dimensions: `transcription`, `gender` (extendable)
- One vote per user per clip per dimension (upserted on re-vote)
- Net votes ≥ 2 → "golden" / trusted
- Downvote (−1) reduces net votes
- Skip: tracked in browser localStorage, not persisted
- User identity: username set in localStorage on first visit

## After Making Changes

After completing any code change, always:
1. `docker compose up -d --build` — rebuild and restart production containers
2. `git commit` + `git push` — commit and push to remote

## Domains (production)

- Frontend: `catvoice.internal.liam.cat`
- Backend:  `api.catvoice.internal.liam.cat`
