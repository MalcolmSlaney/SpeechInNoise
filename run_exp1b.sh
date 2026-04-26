#!/bin/bash

# Run a (text) priming experiment, not the prompting of exp1.sh
#
# The result is a new database file for each condition (with and without 
# prompts) that can be analyzed with the analyze_experiments.py script.


dbfile=experiments_exp1_textprompt.db
rm -f $dbfile
cp experiments.db $dbfile
chmod 644 $dbfile

python migration.py --dbfile $dbfile
python clear_single_word_asr.py --dbfile $dbfile --nodry_run
python offline_asr.py --dbfile $dbfile --use_prompt --num_workers 6

dir=exp1/exp1_textprompt_results
mkdir -p $dir
python analyze_results.py --dbfile experiments_exp1_textprompt.db > $dir/analysis.txt
mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/
