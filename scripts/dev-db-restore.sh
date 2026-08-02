#!/usr/bin/env bash
# Restores apps/backend/data/catvoice.db (the DB used by `pnpm dev:backend`)
# from the pristine snapshot at data/backups/catvoice.baseline.db. Run this
# any time local testing has left the working copy in a state you want to
# discard — it never touches the running Docker dev stack's own volume.
#
# NOTE: `pnpm dev:backend` runs `nest start` with cwd=apps/backend, so
# apps/backend/.env's DB_DATABASE=./data/catvoice.db resolves relative to
# THAT directory, not the repo root — the working copy has to live there,
# not in the top-level data/ dir.
#
# TypeORM's synchronize:true means the local backend applies any schema
# changes automatically on startup, so restoring an older snapshot and
# starting `pnpm dev:backend` is enough to bring the schema up to date too.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE="$REPO_ROOT/data/backups/catvoice.baseline.db"
TARGET="$REPO_ROOT/apps/backend/data/catvoice.db"

if [ ! -f "$BASELINE" ]; then
  echo "No baseline snapshot found at $BASELINE — run scripts/dev-db-snapshot.sh first." >&2
  exit 1
fi

cp "$BASELINE" "$TARGET"
echo "Restored $TARGET from baseline snapshot ($(date -r "$BASELINE" '+%Y-%m-%d %H:%M:%S'))."
