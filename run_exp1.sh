#!/bin/bash

# Run the ASR experiment for single-word answers, comparing results with and 
# without the prompt.  This script copies the original database, removes
# all the single-word ASR results, and reruns the ASR with and without prompts.
#
# The result is a new database file for each condition (with and without 
# prompts) that can be analyzed with the analyze_experiments.py script.


# This is really testing (acoustic) priming, not prompting.  Wrong name
# being used here.

for prompt in noprompt prompt; do
  if [[ "$prompt" == noprompt ]]; then
    echo "Running experiment without prompts..."
    project_list=""
  else
    echo "Running experiment with prompts..."
    project_list="cnc,win,nu6"
  fi
  dbfile=experiments_exp1_${prompt}.db
  rm -f $dbfile
  cp experiments.db $dbfile
  chmod 644 $dbfile

  python migration.py --dbfile $dbfile
  python clear_single_word_asr.py --dbfile $dbfile --nodry_run
  python offline_asr.py --dbfile $dbfile --single_word_projects="$project_list" \
    --num_workers 6 
done

# Now that we have the ASR results, run the analysis and save the results.
for prompt in noprompt prompt; do
  dir=exp1/exp1_${prompt}_results
  mkdir -p $dir
  python analyze_results.py --dbfile experiments_exp1_${prompt}.db > $dir/analysis.txt
  mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/
done
