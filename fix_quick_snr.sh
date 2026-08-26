#!/bin/bash
set -euo pipefail

# Restores audio_trials.snr for the 'quick' project in every
# run_exp3/<tag>/experiments.db.
#
# Background: an older version of run_exp3.sh applied
# `summarize_raters.py --add_pseudo_snr` to both the 'quick' and 'win'
# projects. That flag's cleanup step (clear_pseudo_snr) unconditionally reset
# audio_trials.snr to NULL for whichever project it was passed, which wiped
# out 'quick' project's real SNR values. This script repairs each affected
# database by copying snr from a known-good source database, matched on the
# (project, lang, level_number, trial_number) natural key (see the unique
# index in schema.sql).
#
# Usage:
#   ./fix_quick_snr.sh [source_db]
# source_db defaults to experiments.db next to this script.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$SCRIPT_DIR/run_exp3"
SOURCE_DB="${1:-$SCRIPT_DIR/experiments.db}"

if [[ ! -f "$SOURCE_DB" ]]; then
  echo "Missing source database: $SOURCE_DB" >&2
  exit 1
fi

shopt -s nullglob
tag_dbs=("$RUN_DIR"/*/experiments.db)
if [[ ${#tag_dbs[@]} -eq 0 ]]; then
  echo "No run_exp3/*/experiments.db files found under $RUN_DIR" >&2
  exit 1
fi

for tag_db in "${tag_dbs[@]}"; do
  tag="$(basename "$(dirname "$tag_db")")"
  echo "=== $tag ($tag_db) ==="

  before="$(sqlite3 "$tag_db" \
    "SELECT COUNT(*) FROM audio_trials WHERE project='quick' AND snr IS NULL;")"
  if [[ "$before" -eq 0 ]]; then
    echo "[$tag] No NULL 'quick' snr rows found, skipping."
    continue
  fi

  backup="${tag_db}.bak"
  if [[ ! -f "$backup" ]]; then
    cp "$tag_db" "$backup"
    echo "[$tag] Backed up to $backup"
  fi

  sqlite3 "$tag_db" <<SQL
ATTACH DATABASE '$SOURCE_DB' AS good;
UPDATE audio_trials
SET snr = (
  SELECT good.audio_trials.snr
  FROM good.audio_trials
  WHERE good.audio_trials.project = audio_trials.project
    AND good.audio_trials.lang = audio_trials.lang
    AND good.audio_trials.level_number = audio_trials.level_number
    AND good.audio_trials.trial_number = audio_trials.trial_number
)
WHERE project = 'quick';
DETACH DATABASE good;
SQL

  after="$(sqlite3 "$tag_db" \
    "SELECT COUNT(*) FROM audio_trials WHERE project='quick' AND snr IS NULL;")"
  echo "[$tag] 'quick' NULL snr rows: $before -> $after"
done
