#!/bin/bash

# Run the ASR experiment for single-word answers, comparing results with and 
# without the prompt.  This script copies the original database, removes
# all the single-word ASR results, and reruns the ASR with and without prompts.
#
# The result is a new database file for each condition (with and without 
# prompts) that can be analyzed with the analyze_experiments.py script.


for prompt in noprompt prompt; do
  if [ "$prompt" == "noprompt" ]; then
    echo "Running experiment without prompts..."
    project_list=""
  else
    echo "Running experiment with prompts..."
    project_list="cnc,win,nu6"
  fi
  dbfile = experiments_exp1_${prompt}.db
  cp experiments.db $dbfile
  python migrate_experiments.py --dbfile $dbfile
  python clean_experiments.py --dbfile $dbfile --nodry_run
  python offline_asr.py --dbfile $dbfile --single_word_projects="$project_list"
done