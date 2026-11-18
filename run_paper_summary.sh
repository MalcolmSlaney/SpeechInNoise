# Generate the figures needed for the Ear and HEaring Paper

# Be sure to run 
# Be sure to run this script from the root of the project directory.

# Be sure to first run
#   conda activate quicksin


set -e
shopt -s nullglob

run_dir=run_exp3a
model_args=()

for db in "$run_dir"/*/experiments.db; do
    experiment_dir=$(dirname "$db")
    model=$(basename "$experiment_dir")
    output_dir="$experiment_dir/asr_summary"

    echo "Summarizing $model"

    python3 summarize_asr.py \
        --dbfile="$db" \
        --output_dir="$output_dir" \
        > "$experiment_dir/summarize_asr.log" 2>&1

    model_args+=(--model "$model" "$output_dir/recognition_all_srts.csv")
done

if (( ${#model_args[@]} == 0 )); then
    echo "No experiment databases found under $run_dir" >&2
    exit 1
fi

python3 compare_asr_models.py \
    "${model_args[@]}" \
    --output_dir="$run_dir/model_comparison"