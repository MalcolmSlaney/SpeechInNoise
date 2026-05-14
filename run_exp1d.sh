# Run the ASR experiment using a forced grammar and a range of OOV penalties.  
# This is for the single word projects.
prompt=forced

for oov in 1000 -10 100 0 10 ; do
  dbfile=experiments_exp1_${prompt}_${oov}.db
  rm -f $dbfile
  cp experiments.db $dbfile
  chmod 644 $dbfile
  dir=exp1/exp1_${prompt}_${oov}_results
  mkdir -p $dir

  python migration.py --dbfile $dbfile
  python clear_single_word_asr.py --dbfile $dbfile --nodry_run

  python offline_asr.py --dbfile $dbfile --single_word_projects="$project_list" \
    --num_workers 6 --use_forced --valid_words valid_words.json \
    --oov_penalty $oov  --debug > $dir/offline_asr.log

  # Now that we have the ASR results, run the analysis and save the results.
  python analyze_results.py --dbfile $dbfile --debug_count=100000 > $dir/analysis.txt
  mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/
done