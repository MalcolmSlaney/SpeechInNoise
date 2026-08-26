#!/bin/bash
set -euo pipefail

# Restores audio_trials.snr for the 'quick' project in every
# run_exp3/<tag>/experiments.db.
#
# Background: an older version of run_exp3.sh applied
# `summarize_raters.py --add_pseudo_snr` to both the 'quick' and 'win'
# projects. That flag's cleanup step (clear_pseudo_snr) unconditionally reset
# audio_trials.snr to NULL for whichever project it was passed, which wiped
# out 'quick' project's real SNR values.
#
# This script repairs each affected database by re-running QuickDB's CSV
# import (projects.QuickDB, via migrate.py), which upserts every audio_trials
# column, including snr, from metadata/quicksin_transcript.csv keyed on the
# same (lang, trial_number, level_number) natural key used originally. This
# is the same code path the app uses to populate the table in the first
# place, so it repairs the data more reliably than copying between two
# separately-typed SQLite files.
#
# Usage:
#   ./fix_quick_snr.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$SCRIPT_DIR/run_exp3"

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

  python "$SCRIPT_DIR/migrate.py" projects.QuickDB --database "$tag_db"

  after="$(sqlite3 "$tag_db" \
    "SELECT COUNT(*) FROM audio_trials WHERE project='quick' AND snr IS NULL;")"
  echo "[$tag] 'quick' NULL snr rows: $before -> $after"
done
