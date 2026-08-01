# GarbellaVeus

Human evaluation platform for the [softcatala/catalan-youtube-speech](https://huggingface.co/datasets/softcatala/catalan-youtube-speech) dataset. Reviewers vote on ASR transcription quality, speaker gender, and dialect for short Catalan speech clips pulled from YouTube.

## Stack

- **Backend:** NestJS + TypeORM + SQLite
- **Frontend:** React + Vite + Tailwind, with i18n (English/Catalan)
- **Pipeline:** Python scripts that pre-populate transcriptions using Gemini and Claude CLIs
- **Deploy:** Docker Compose behind Traefik

## Project Layout

```
apps/backend/      NestJS + SQLite (TypeORM) — runs in Docker
apps/frontend/     React + Vite + Tailwind — runs in Docker
scripts/           Python transcription pipeline (runs on host)
data/              SQLite DB + tar_index.json + temp audio files (gitignored)
```

## Getting Started

```bash
pnpm install

# Dev servers (backend on :3000, frontend on :5173)
pnpm dev:backend
pnpm dev:frontend
```

Backend config lives in `apps/backend/.env` (dev) / `apps/backend/.env.production` (Docker) — both gitignored. At minimum:

```
PORT=3000
DB_DATABASE=./data/catvoice.db
CORS_ORIGIN=http://localhost:5173
```

### Production (Docker)

```bash
cp .env.example .env   # fill in your own domains
docker compose up -d --build
```

`docker-compose.yml` routes the frontend and backend through Traefik using domains read from `.env` — see `.env.example` for the variables it expects. The frontend's API base URL is baked in at build time from `BACKEND_DOMAIN_PUBLIC`, so that value must be reachable from wherever the app is viewed.

## How Audio Is Served

The dataset's audio ships as 51 tar files (`audio-0.tar` … `audio-50.tar`, ~107 GB total) hosted on HuggingFace. Rather than downloading them, the backend stores each clip's `(tar_file, tar_offset, tar_size)` and proxies an HTTP range request straight to HuggingFace on demand (`apps/backend/src/outbound/audio-proxy.service.ts`).

## Transcription Pipeline (`scripts/transcribe.py`)

Run on the host (not in Docker), against a running backend:

```bash
# 1. Build the TAR index once — reads headers from all 51 tar files via
#    HTTP range requests (~2000 requests per tar, takes several minutes)
python scripts/transcribe.py --build-index-only

# 2. Post the index to the backend, populating tar_file/tar_offset/tar_size
python scripts/transcribe.py --post-index

# 3. Transcribe (idempotent — safe to run repeatedly / resume)
python scripts/transcribe.py
python scripts/transcribe.py --max 100          # limit batch size
python scripts/transcribe.py --api-url <url>    # defaults to http://localhost:3000
```

Per clip, the script fetches the audio via range request, runs `gemini --yolo` on the audio file and `claude --dangerously-skip-permissions -p` on the text candidates, and posts both results to the backend. Rate-limit errors back off exponentially (5s → 10s → 20s → 40s → 120s).

`scripts/migrate_gemini_transcriptions.py` copies clip metadata, the TAR index, and Gemini-origin transcriptions from one deployed backend to another over HTTP (no direct DB/file access needed) — useful for standing up a second environment without re-running the pipeline from scratch.

## Data Model

**Clips** (from the HuggingFace dataset):
`clip_id`, `source_id`, `duration` (3–20s), `start`/`end`, `gender`, `candidate_1`/`candidate_2` (ASR candidates), `yt_url`, `license` (CC-BY).

**Voting:**
- Dimensions: `transcription`, `gender` (extendable)
- One vote per user per clip per dimension (upserted on re-vote)
- Net votes ≥ 2 → "golden" / trusted
- Skips are tracked client-side (localStorage), not persisted
- Username is set in localStorage on first visit — no auth
