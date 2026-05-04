prompt=forced
dbfile=experiments_exp1_${prompt}.db
rm -f $dbfile
cp experiments.db $dbfile
chmod 644 $dbfile

python migration.py --dbfile $dbfile
python clear_single_word_asr.py --dbfile $dbfile --nodry_run
python offline_asr.py --dbfile $dbfile --single_word_projects="$project_list" \
  --num_workers 6 --use_forced --valid_words valid_words.json

# Now that we have the ASR results, run the analysis and save the results.
for prompt in forced; do
  dir=exp1/exp1_${prompt}_results
  mkdir -p $dir
  python analyze_results.py --dbfile experiments_exp1_${prompt}.db --debug_count=100000 > $dir/analysis.txt
  mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/
done
