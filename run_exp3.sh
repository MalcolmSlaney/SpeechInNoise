#!/bin/bash
set -euo pipefail

# Run tagged offline ASR jobs from run_exp3.jobs.
# Each non-empty, non-comment line has the form:
#   TAG <offline_asr.py arguments...>
#
# For each TAG, this script:
# 0) if run_exp3/TAG/run_exp3_residual_std_ratio.png already exists, skip TAG
# 1) creates run_exp3/TAG if needed
# 2) copies ../jnd.emily/experiments.db to run_exp3/TAG/experiments.db if not already there
# 2a) runs clear_single_word_asr.py to clear any existing ASR results for the target projects
# 3) runs offline_asr.py with the given arguments
# 4) runs summarize_raters.py for each of the target projects (quick, win) and 
#     saves the output to run_exp3/TAG/summarize_raters_PROJECT.log

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$SCRIPT_DIR/run_exp3"
JOBS_FILE="$SCRIPT_DIR/run_exp3.jobs"
SOURCE_DB="$SCRIPT_DIR/../jnd.emily/experiments.db"

# Arguments always passed to offline_asr.py for every job.
# Example: COMMON_ARGS=(--audiodir=uploads --num_workers=6)
COMMON_ARGS=(--target_projects=quick,win --num_workers=10)

mkdir -p "$RUN_DIR"

if [[ ! -f "$JOBS_FILE" ]]; then
  echo "Missing jobs file: $JOBS_FILE" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DB" ]]; then
  echo "Missing source database: $SOURCE_DB" >&2
  exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip blank lines and comments.
  [[ -z "${line//[[:space:]]/}" ]] && continue
  [[ "$line" =~ ^[[:space:]]*# ]] && continue

  # First token is TAG, remainder is argument string.
  # Allow either spaces or tabs (and optional leading whitespace).
  trimmed_line="${line#"${line%%[![:space:]]*}"}"
  tag="${trimmed_line%%[[:space:]]*}"
  rest="${trimmed_line#"$tag"}"
  rest="${rest#"${rest%%[![:space:]]*}"}"
  if [[ -z "$tag" ]]; then
    continue
  fi

  echo
  echo
  echo "=== Processing ASR for tag: $tag ==="
  tag_dir="$RUN_DIR/$tag"
  tag_db="$tag_dir/experiments.db"
  done_file="$tag_dir/run_exp3_residual_std_ratio.png"

  if [[ -f "$done_file" ]]; then
    echo "[$tag] Found $done_file, skipping database copy/ASR/summarize steps."
    continue
  fi

  mkdir -p "$tag_dir"

  if [[ ! -f "$tag_db" ]]; then
    cp "$SOURCE_DB" "$tag_db"
    chmod 644 "$tag_db"
    python "$SCRIPT_DIR/clear_single_word_asr.py" --dbfile "$tag_db" --nodry_run --target_projects=all
  fi

  # Parse the remainder into an argv array honoring shell-style quoting.
  args=()
  if [[ -n "${rest:-}" ]]; then
    eval "args=($rest)"
  fi

  cmd=(python "$SCRIPT_DIR/offline_asr.py" --dbfile "$tag_db" "${COMMON_ARGS[@]}" "${args[@]}")

  echo "[$tag] Running: ${cmd[*]}"
  "${cmd[@]}"

  for project in quick win; do
    summary_log="$tag_dir/summarize_raters_${project}.log"
    summary_cmd=(python "$SCRIPT_DIR/summarize_raters.py" --dbfile "$tag_db" --project "$project")
    echo "[$tag] Running: ${summary_cmd[*]} > $summary_log"
    "${summary_cmd[@]}" > "$summary_log" 2>&1
  done
done < "$JOBS_FILE"
