#!/bin/bash
set -euo pipefail

# Run tagged offline ASR jobs from run_exp3.jobs.
# Each non-empty, non-comment line has the form:
#   TAG <offline_asr.py arguments...>
#
# For each TAG, this script:
# 0) if run_exp3/TAG/run_exp3_residual_std_ratio.png already exists, skip TAG
# 1) creates run_exp3/TAG if needed
# 2) copies ../jnd.emily/experiments.db to
#    run_exp3/TAG/experiments.db if not already there
# 2a) runs clear_single_word_asr.py to clear any existing ASR results for
#     the target projects
# 3) runs offline_asr.py with the given arguments
# 4) runs score_and_report.py and writes CSV output to
#    run_exp3/TAG/quicksin_results.csv
# 5) runs summarize_raters.py for each of the target projects (quick, win) and
#     saves the output to run_exp3/TAG/summarize_raters_PROJECT.log
#
# Flags:
#   --recompute_all  Disable done-file checks and recompute all tags.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$SCRIPT_DIR/run_exp3"
JOBS_FILE="$SCRIPT_DIR/run_exp3.jobs"
SOURCE_DB="$SCRIPT_DIR/../jnd.emily/experiments.db"

# Arguments always passed to offline_asr.py for every job.
# Example: COMMON_ARGS=(--audiodir=uploads --num_workers=6)
# Num workers = 2 seems to work well for 30 cores
COMMON_ARGS=(--target_projects=quick,win --num_workers=2)

# Tags for which summarize_raters.py should also dump raw per-utterance data
# (via --dump_raw_data) for hand-checking the residual calculation.
DUMP_RAW_DATA_TAGS=(large)

RECOMPUTE_ALL=false
for arg in "$@"; do
  case "$arg" in
    --recompute_all)
      RECOMPUTE_ALL=true
      ;;
    -h|--help)
      echo "Usage: $0 [--recompute_all]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--recompute_all]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$RUN_DIR"

if [[ ! -f "$JOBS_FILE" ]]; then
  echo "Missing jobs file: $JOBS_FILE" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DB" ]]; then
  echo "Missing source database: $SOURCE_DB" >&2
  exit 1
fi

# Read all job lines into an array up front. Iterating with `while read < file`
# instead would share fd 0 with every subprocess spawned in the loop body; if
# any of them ever touches stdin, it consumes bytes from the jobs file and the
# loop silently stops after the first tag.
# Note: avoid `mapfile`/`readarray` here; macOS ships bash 3.2, which predates
# both builtins (added in bash 4.0).
job_lines=()
while IFS= read -r line || [[ -n "$line" ]]; do
  job_lines+=("$line")
done < "$JOBS_FILE"

for line in "${job_lines[@]}"; do
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
  done_file="$tag_dir/summarize_raters_win.log"

  if [[ "$RECOMPUTE_ALL" != true && -f "$done_file" ]]; then
    echo "[$tag] Found $done_file, skipping database copy/ASR/summarize steps."
    continue
  fi

  mkdir -p "$tag_dir"

  if [[ ! -f "$tag_db" ]]; then
    cp "$SOURCE_DB" "$tag_db"
    chmod 644 "$tag_db"
    clear_cmd=(
      python "$SCRIPT_DIR/clear_single_word_asr.py"
      --dbfile "$tag_db"
      --nodry_run
      --target_projects=all
    )
    "${clear_cmd[@]}" < /dev/null
  fi

  # Parse the remainder into an argv array honoring shell-style quoting.
  args=()
  if [[ -n "${rest:-}" ]]; then
    eval "args=($rest)"
  fi

  cmd=(
    python "$SCRIPT_DIR/offline_asr.py"
    --dbfile "$tag_db"
    "${COMMON_ARGS[@]}"
    "${args[@]}"
  )

  echo "[$tag] Running: ${cmd[*]}"
  "${cmd[@]}" < /dev/null

  score_csv="$tag_dir/quicksin_results.csv"
  score_cmd=(
    python "$SCRIPT_DIR/score_and_report.py"
    --dbfile "$tag_db"
    --csv_output "$score_csv"
  )
  echo "[$tag] Running: ${score_cmd[*]}"
  "${score_cmd[@]}" < /dev/null

  dump_raw_data=true # Always dump raw data for now, since we want to check the residuals for every tag.
  for dump_tag in "${DUMP_RAW_DATA_TAGS[@]}"; do
    if [[ "$tag" == "$dump_tag" ]]; then
      dump_raw_data=true
      break
    fi
  done

  # audio_asr.data's model_name is whatever --model was passed to
  # offline_asr.py (e.g. "large"), not the tag itself (e.g.
  # "large_exact_100"), so extract it from this job's args for --asr_model.
  asr_model_name="$tag"
  for ((arg_index = 0; arg_index < ${#args[@]}; arg_index++)); do
    arg="${args[$arg_index]}"
    if [[ "$arg" == --model=* ]]; then
      asr_model_name="${arg#--model=}"
      break
    elif [[ "$arg" == "--model" ]]; then
      asr_model_name="${args[$((arg_index + 1))]}"
      break
    fi
  done

  for project in quick win; do
    summary_log="$tag_dir/summarize_raters_${project}.log"
    summary_cmd=(
      python "$SCRIPT_DIR/summarize_raters.py"
      --dbfile "$tag_db"
      --project "$project"
      --residual_plot "$tag_dir/residual_std_ratio_${project}.png"
      --residual_normalization normalization_by_snr
      --output_csv "$tag_dir/summarize_raters_${project}.csv"
      --residual_debug_points=10
    )
    if [[ "$dump_raw_data" == true ]]; then
      summary_cmd+=(
        --dump_raw_data
        --asr_model="$asr_model_name"
        --raw_output="$tag_dir/residual_raw_data_${project}.pkl"
      )
    fi
    echo "[$tag] Running: ${summary_cmd[*]} > $summary_log"
    "${summary_cmd[@]}" < /dev/null > "$summary_log" 2>&1
  done
done
