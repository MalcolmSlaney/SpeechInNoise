language=spanish
dbfile=experiments_exp_${language}.db
rm -f $dbfile
cp ../jnd.emily/experiments.db $dbfile
chmod 644 $dbfile

dir=exp1/exp_${language}_results

python migration.py --dbfile $dbfile
python offline_asr.py --dbfile $dbfile --target_projects="azbio_spanish,azbio_spanish_quiet" \
  --audiodir=../jnd.emily/uploads --num_workers 6  --model=large \
  --language=es --debug > $dir/offline_asr.log

# Now that we have the ASR results, run the analysis and save the results.
  mkdir -p $dir
  python analyze_results.py --dbfile experiments_exp1_${prompt}.db  \
    --debug_count=100000 > $dir/analysis.txt
  mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/