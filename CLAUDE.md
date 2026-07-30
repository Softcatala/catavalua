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

# Different backend URL (defaults to http://localhost:3000)
python scripts/transcribe.py --api-url https://api.your-domain.example
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

## Backend Data Model

Three tables (SQLite via TypeORM, `synchronize: true` — schema follows the
entities in `apps/backend/src/domain/`):

- **clips** — one row per dataset clip (`clip_id` primary key). `POST /clips`
  is an upsert keyed on `clipId`.
- **transcriptions** — candidate/model/human transcriptions for a clip.
  `POST /transcriptions` is idempotent: re-posting the same
  `(clipId, origin, text)` returns the existing row instead of duplicating.
- **votes** — one row per `(clipId, dimension, username)`, upserted on
  re-vote (`POST /votes`).

Both `transcriptions` and `votes` have a foreign key to `clips` with
`ON DELETE NO ACTION` — **deleting a clip requires deleting its
transcriptions and votes first**, or the delete fails while children still
reference it (`ClipService.remove` does this in the right order — follow
that pattern if you add other cascading deletes).

## API Reference

| Method | Path | Notes |
|---|---|---|
| `GET` | `/clips?search=&page=&limit=` | Paginated list, enriched with best transcription + vote summary |
| `GET` | `/clips/:id` | Single clip |
| `GET` | `/clips/:id/transcriptions` | All transcriptions for a clip |
| `POST` | `/clips` | Upsert (by `clipId`) |
| `POST` | `/clips/:id/tar-index` | Set audio location (`tarFile`/`tarOffset`/`tarSize`) |
| `POST` | `/clips/:id/flag-irrelevant` | Records a relevance-flag vote |
| `DELETE` | `/clips/:id` | Cascades to the clip's transcriptions + votes |
| `POST` | `/transcriptions` | Create (idempotent by `clipId`+`origin`+`text`) |
| `DELETE` | `/transcriptions/:id` | |
| `POST` | `/votes` | Cast/update a vote (upsert) |
| `DELETE` | `/votes?username=` | Remove all of a user's votes |
| `GET` | `/votes/clip/:clipId` | Vote summary for a clip |
| `GET` | `/votes/clip/:clipId/user/:username` | One user's votes on a clip |
| `GET` | `/votes/stats` | Global stats |

All `DELETE` routes are unauthenticated in the app itself — in production
they're gated by infra-level auth in front of the API, not app code.

## Deployment

The live site is **not** deployed by running `docker compose up -d --build`
locally — that only stands up your own instance (useful for self-hosting or
local testing against real Traefik/domain config). Pushing to `main` on
GitHub is what deploys the live site, via a CI/CD pipeline that lives
outside this repo. There's nothing else to do after `git push`.

The live site also runs behind a single domain with the API served under
`/api` (see `apps/frontend/src/api.ts` — `VITE_API_BASE_URL` defaults to
the relative path `/api`, baked into the frontend bundle at build time).
The two-domain setup in this repo's own `docker-compose.yml`/`.env.example`
is for standalone self-hosting, and doesn't reflect how the live site is
actually configured.
