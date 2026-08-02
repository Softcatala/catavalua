#!/usr/bin/env bash
# Safely snapshots the running dev Docker stack's SQLite DB (docker volume
# catvoice_catvoice-data) into data/backups/catvoice.baseline.db, using
# SQLite's online backup API via a throwaway container (read-only mount of
# the live volume, so the running backend/frontend containers are never
# touched or restarted).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/data/backups"
mkdir -p "$BACKUP_DIR"

docker run --rm \
  -v catvoice_catvoice-data:/src:ro \
  -v "$BACKUP_DIR":/backup \
  alpine:3.24 sh -c '
    apk add --no-cache sqlite >/dev/null
    sqlite3 /src/catvoice.db ".backup /backup/catvoice.baseline.db"
    sqlite3 /backup/catvoice.baseline.db "PRAGMA integrity_check;"
  '

echo "Snapshot written to $BACKUP_DIR/catvoice.baseline.db"
