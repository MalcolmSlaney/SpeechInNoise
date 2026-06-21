language=spanish
dbfile=experiments_exp_${language}.db
dir=exp1/exp_${language}_results

rm -f $dbfile
cp ../jnd.emily/experiments.db $dbfile
chmod 644 $dbfile

# Check the number of audio trials and results for each language and project to make sure we have the expected data.
sqlite3 -column -header $dbfile "SELECT lang, COUNT(*) FROM audio_trials GROUP BY lang;"

# Check the number of audio results for each project to make sure we have the expected data.
sqlite3 -column -header $dbfile "SELECT t.project, COUNT(r.id) AS result_count FROM audio_results r JOIN audio_trials t ON r.trial = t.id GROUP BY t.project;"

# Get the latest audio result for each user, sorted by date.  This is useful to check if we have any new results that haven't been processed yet.
sqlite3 -column -header $dbfile "SELECT u.username, MAX(r.t) AS latest_audio_result FROM users u JOIN audio_results r ON u.id = r.subject GROUP BY u.id ORDER BY latest_audio_result ASC;"

# Check for any audio results that don't have a corresponding ASR result, which would indicate that they haven't been processed yet.
sqlite3 -column -header experiments_emily.db "SELECT t.project, COUNT(r.id) AS empty_asr_trials FROM audio_trials t JOIN audio_results r ON t.id = r.trial LEFT JOIN audio_asr a ON r.id = a.ref WHERE a.data IS NULL OR TRIM(a.data) = '' OR TRIM(a.data) = '{}' GROUP BY t.project;"

# Check the audio results for one user and one test, sorted by SNR.
sqlite3 -column -header experiments_exp_spanish.db "SELECT t.snr, SUM(a.correct_word_count) AS total_correct_words, SUM(a.gt_word_count) AS total_gt_words, ROUND(CAST(SUM(a.correct_word_count) AS REAL) / SUM(a.gt_word_count), 4) AS accuracy_fraction FROM audio_asr a JOIN audio_results r ON a.ref = r.id JOIN audio_trials t ON r.trial = t.id JOIN users u ON r.subject = u.id WHERE u.username = 'A6S30' AND t.project = 'azbio_spanish' GROUP BY t.snr ORDER BY t.snr DESC;"
mkdir -p $dir

python migration.py --dbfile $dbfile

python offline_asr.py --dbfile $dbfile --target_projects="azbio_spanish,azbio_spanish_quiet" \
  --audiodir=uploads --num_workers 6  --model=large \
  --language=es --debug > $dir/offline_asr.log

# Now that we have the ASR results, run the analysis and save the results.
  # python analyze_results.py --dbfile $dbfile  \
  #   --debug_count=100000 > $dir/analysis.txt
  python score_and_report.py --dbfile $dbfile> $dir/analysis.txt
  mv asr_audiology_discrepancies.html confusion_matrices.png quicksin_results.csv $dir/