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

## Dialect Inference (scripts/infer_dialect.py)

Infers a clip's dialect from the town its source YouTube video was recorded
in (most source videos are municipal plenary sessions — the speaker's home
town is a much stronger signal than guessing from a few seconds of audio).
Applied as a **vote** (`dimension: 'dialect'`, `username: 'derivat-de-poblacio'`)
via the existing `POST /votes` endpoint, not a direct write to
`clips.detected_dialect` — that column holds the transcription pipeline's
Gemini audio-based per-clip guess (`scripts/transcribe.py`'s `dialect_notes`),
and overwriting it would lose that value with no history. The frontend's
`resolveDimension()` (`apps/frontend/src/voteUtils.ts`) already shows
whichever candidate has the most net votes over the clip's stored value, so
one vote is enough to surface the inferred dialect as the leading (but not
yet "golden") candidate — a real evaluator can still confirm or overturn it,
and the original model guess is never touched.

`scripts/reference/town_dialects.tsv` is a hand-built gazetteer (town →
comarca → territori → dialecte) covering the whole Catalan-speaking domain
(Catalunya, País Valencià, Illes Balears, Catalunya Nord, Franja de Ponent,
Andorra, Alguer), sourced from Catalan Wikipedia's municipi lists plus the
standard IEC/GEC dialect classification. Rebuild it (e.g. after Wikipedia's
lists change) with:

```bash
python scripts/build_town_dialects.py
```

Three-step pipeline, mirroring `transcribe.py`'s style:

```bash
python scripts/infer_dialect.py --fetch-metadata   # oEmbed title+channel per distinct source video (resumable)
python scripts/infer_dialect.py --match             # match against the gazetteer -> scripts/reference/video_town_matches.tsv
python scripts/infer_dialect.py --apply --min-confidence high [--dry-run]  # cast dialect votes on matched clips
```

Not every source video is a town-council meeting — this dataset also
includes Generalitat de Catalunya seminars, Diputació sessions, and personal
channels — so `--match` tags every row with a `confidence` (`high`/`medium`/
`low`) and a `channel_level` (`municipi` vs `provincial-or-generalitat`) and
**review the TSV before applying**; nothing is written to any backend until
`--apply` is run explicitly. `--apply` checks each clip already exists via
`GET /clips/:id` before patching — it never lets the upsert silently create a
new, sparse clip for a `clipId` that isn't already in that environment's DB.

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
| `POST` | `/clips` 🔑 | Upsert (by `clipId`) |
| `POST` | `/clips/:id/tar-index` 🔑 | Set audio location (`tarFile`/`tarOffset`/`tarSize`) |
| `POST` | `/clips/:id/flag-irrelevant` | Records a relevance-flag vote |
| `DELETE` | `/clips/:id` 🔑 | Cascades to the clip's transcriptions + votes |
| `POST` | `/transcriptions` | Create (idempotent by `clipId`+`origin`+`text`) |
| `DELETE` | `/transcriptions/:id` 🔑 | |
| `POST` | `/votes` | Cast/update a vote (upsert) |
| `DELETE` | `/votes?username=` 🔑 | Remove all of a user's votes |
| `GET` | `/votes/clip/:clipId` | Vote summary for a clip |
| `GET` | `/votes/clip/:clipId/user/:username` | One user's votes on a clip |
| `GET` | `/votes/stats` | Global stats |

🔑 = requires an `X-Api-Key` header matching the backend's `API_KEY` env var
(`ApiKeyGuard`, `apps/backend/src/inbound/api-key.guard.ts`). This only covers
routes that are never called by the frontend — every route the browser hits
directly (`POST /votes`, `POST /clips/:id/flag-irrelevant`, `POST
/transcriptions`, `POST /issue-reports`) stays open, since the SPA calls the
API straight from the browser with no secret-holding backend-for-frontend to
put a key behind. `scripts/transcribe.py`, `scripts/migrate_gemini_transcriptions.py`,
and `scripts/post_tar_index_fast.py` send this key via `--api-key`/
`--dest-api-key` (default `$CATVOICE_API_KEY`) on the 🔑 routes they call.

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
