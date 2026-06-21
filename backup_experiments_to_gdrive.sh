#!/usr/bin/env bash
set -euo pipefail
SRC=/var/www/jnd.emily/experiments.db
DEST_NAME="$(date +%Y-%m-%d)_experiments_emily.db"

if [[ -n "${GDRIVE_REMOTE:-}" ]]; then
  rclone copyto "$SRC" "${GDRIVE_REMOTE}/${DEST_NAME}"
else
  LOCAL="${LOCAL_DRIVE_BACKUP:-$HOME/GoogleDrive/jnd-emily-db-backup}"
  mkdir -p "$LOCAL"
  cp "$SRC" "$LOCAL/$DEST_NAME"
fi
