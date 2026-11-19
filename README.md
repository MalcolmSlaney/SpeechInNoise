## Useful commands

### Database completeness

```bash
python3 database_completeness.py experiments_emily.db
```

Prints one line with counts and percentages of all recorded utterances
(`audio_results`) having at least one nonempty ASR result and having a nonempty
annotation from every rater in `metadata/professional_raters.txt`. These are
independent fractions; duplicate ASR or annotation rows do not inflate counts.
This checks stored-data presence, not JSON validity or recognition accuracy.
The database is opened read-only; an empty database reports `N/A` percentages.

### Summarize rater scores

`summarize_raters.py` reads `audio_results`, `audio_trials`, `audio_asr`,
`audio_annotations`, and `review_annotations` from SQLite. It keeps every
subject whose username fully matches `--subject_pattern` (by default
`A\d+[SP]\d+`) and is not in `--excluded_subjects` (which defaults to `A2P2`),
provided it has a trial matching `--language` and `--project`, non-empty ASR
data, and non-empty reviewer data in `review_annotations.data`. Audiologist
data is optional because it is a left join; when `audio_annotations.data` is
missing, that trial contributes a zero audiologist true fraction.

For each kept trial, ASR words are compared with the trial answer using
`homonym_list.csv` and slash-separated answer alternatives. The program then
groups trials by subject, project, and SNR. Each CSV row and each scatter-plot
point is one such group, not one rater. Values are averaged across its trial
rows; if multiple reraters scored the same audio, their review records are
combined into the same group rather than producing separate dots:

* audiologist true fraction from `audio_annotations.data`;
* rerater true fraction from `review_annotations.data`; and
* ASR matched-word count normalized by the number of words in each answer.

The three plot panels compare audiologist versus rerater fractions, normalized
ASR versus audiologist fraction, and normalized ASR versus rerater fraction.

Example:
```bash
python3 summarize_raters.py --dbfile experiments_emily.db --project quick
```

### Summarize offline ASR and human recognition

After `offline_asr.py` has populated `audio_asr`, run:

```bash
python3 summarize_asr.py --dbfile experiments_emily.db
```

By default, every summary, plot, and report (including pre-scoring coverage
counts) is restricted using the subject tracking CSV:

```bash
python3 summarize_asr.py --dbfile experiments_large_prompt.db \
  --valid_users_file=Clean_ASR_SubjectTracking_2025.csv
```

The CSV's `Subject ID` column contains exact, case-sensitive usernames.
For each subject, QuickSIN (`quick`) trials are limited to the list numbers in
`QS_5dB_Lists`, and WIN (`win`) trials to those in `WIN_List`. The numbers
match `audio_trials.trial_number`; all SNRs within selected lists are included.
Comma-separated list numbers are accepted; a blank list field excludes that
subject's trials for that project. Other projects are included for listed
subjects without list filtering. Missing files, missing required columns,
duplicate subject IDs, and invalid list numbers are errors. Set
`--valid_users_file=` to disable both subject and list filtering.

The program keeps only the recognized word list from ASR JSON, scores it
against each trial's answer and `homonym_list.csv`, and includes in-booth
annotations plus only raters listed in `metadata/professional_raters.txt`.
Before scoring, it prints selected result counts and annotation coverage,
including ASR-backed utterances missing any valid, nonempty professional-rater
annotation from that configured list.
It writes per-utterance, project/SNR, subject/project/SNR, and subject SRT CSVs,
plus a three-panel recognition comparison PNG and a disagreement page named
`recognition_{test_name}_discrepancies.html`. The page lists utterances where
in-booth, ASR, or a professional rater's fraction-correct score differs, and
includes the recognized ASR words and links to subject recordings at
`https://quicksin.stanford.edu/uploads/`, using `audio_results.reply_filename`.
Clicking a recording opens a small player dialog with playback controls and a
direct link; the original link also works when JavaScript is unavailable.
Missing or unsupported recording filenames are marked unavailable; server
availability and access permissions are not checked. Default output filenames use
`recognition_{test_name}_...`; `test_name` comes from `--project`, a sole project
found in the data, or `all` when multiple projects are included. Explicit output
relative paths are placed under `--output_dir` (default `.`), while absolute
paths starting with `/` remain unchanged. Output directories are created as
needed. For example, `--output_dir=results/large` keeps that model's CSVs,
plots, text report, and HTML together. Input paths are unaffected.
The subject SRT CSV includes
each professional rater's fitted SRT, their mean SRT (the reference), and
their standard deviation. It also writes an SRT comparison PNG with rater-SRT
standard-deviation error bars (±1 SD; subjects whose full error bar is longer
than 15 dB are labeled with their username in the project's color). Set
`--srt_error_bar_label_db` to change this threshold, measured as the full
length of the error bar (2 × SD). Blank usernames fall back to subject IDs.
It also writes
`recognition_{test_name}_srt_histogram.png`,
with in-booth and ASR SRT differences from the professional-rater mean in
separate panels and one row per project. Each bar lists subject usernames
(falling back to numeric subject IDs). The shaded range is centered on each
panel's mean paired difference and extends one pooled within-subject
professional-rater SD in either direction. For each test, the SD pools
professional-rater deviations from each subject's professional mean, using
`sqrt(sum((n_i - 1) * s_i**2) / sum(n_i - 1))`, where `n_i` and `s_i`
are the number of valid professional SRTs and their sample SD for subject `i`.
Subjects with fewer than two valid professional fits do not contribute to
this SD; all eligible subjects in the test contribute, even if they lack an
ASR or in-booth SRT. The same pooled SD is used in both panels. It measures
professional-rater variability, not the spread of ASR or in-booth differences
or the uncertainty of an individual fit.

The plot and console output call subjects strictly outside the shaded range
outliers and report their count and a Gaussian benchmark of approximately
31.7% of paired subjects. This benchmark assumes the comparison differences
are normally distributed with SD equal to the pooled professional-rater SD;
it is not necessarily the expected outlier count for the actual comparison
distribution. The range is omitted when the pooled SD cannot be estimated,
and the Gaussian benchmark is not applicable when the SD is zero.
The console counts are also printed with `--no_plot`. Set `--histogram_bins` to
change the default of 10.
It also writes a CSV of Bland-Altman bias/limits of agreement
and ICC(3,1) for in-booth and ASR SRTs versus the professional-rater mean, plus
`recognition_srt_agreement.txt` explaining the statistics and nominal p-value
significance. Bias uses a paired t-test; ICC(3,1) uses its F-test against zero.
The report notes that statistical significance is not the same as clinically
acceptable agreement, which requires predefined limits.
It also tests ASR noninferiority against professional-rater leave-one-out
absolute SRT errors using a one-sided paired t-test; the default 2 dB margin is
configurable with `--noninferiority_margin_db`. Results are saved to
`recognition_srt_noninferiority.csv`.
Use `--project=quick` or `--language=en` to filter the source rows; output paths
can be changed with `--output_csv`, `--snr_summary_csv`, `--subject_snr_csv`,
`--srt_csv`, `--scatter_plot`, `--srt_scatter_plot`, `--srt_histogram_plot`, `--agreement_csv`, and
`--noninferiority_csv`.

### Compare ASR model variations

Run `summarize_asr.py` separately for each model, saving its subject-SRT CSVs
in separate directories. Then reproduce the two "Model Comparison" plots from
[the Colab notebook](https://colab.research.google.com/drive/1fsi7D-HB9xuC5BBegQQ6kVHhwdgM9xh2):

```bash
python3 compare_asr_models.py \
  --model tiny.en results/tiny.en/recognition_quick_srts.csv results/tiny.en/recognition_win_srts.csv \
  --model large results/large/recognition_all_srts.csv \
  --model large_prompt results/large_prompt/recognition_all_srts.csv \
  --output_dir model_comparison
```

Each `--model` takes a label and one or more subject-SRT CSVs.
A combined `recognition_all_srts.csv` or separate QuickSIN/WIN CSVs
work equally well. Do not supply overlapping subject/project rows for a
model. Only projects `quick` and `win` are plotted.

Use `--model_order="tiny.en,large,,large_prompt"` to override the plot order.
List every input model exactly once. Empty comma-delimited slots break the
lines between model groups in both plots without consuming x-axis positions;
consecutive models always remain one position apart. Whitespace
around names is ignored; unknown, omitted, or repeated model names are errors.
Markers keep isolated model results visible. The default order is:

```text
tiny.en,tiny,base.en,base,small.en,small,medium.en,medium,large,,large_prime,large_prompt,,large_forced_-10,large_forced_0,large_forced_10,large_forced_20,large_forced_100,,large_exact_-10,large_exact_0,large_exact_10,large_exact_20,large_exact_100
```

The default skips model names without input CSVs, preserving the group
separators. Input models not in the default require an explicit order.
Set `--model_order=` to use the `--model` input order instead.
The summary CSV remains in input order, without separator rows.

The outputs are `model_comparison_outliers.png`,
`model_comparison_stds.png`, and `model_comparison_summary.csv`. Both plots
have Quick/WIN Audiologist (in-booth) and ASR lines. Differences are each
subject's in-booth or ASR SRT minus `professional_srt` (the professional-rater
**mean** supplied by `summarize_asr.py`, not a recomputed median).

Outliers have absolute difference **strictly greater than 2 dB**, configurable
with `--outlier_threshold`. This is measured from zero, not from the mean
difference. The second plot uses the sample SD (`ddof=1`) of those differences,
not the pooled within-subject rater SD used in `summarize_asr.py`'s histogram.
Missing/nonfinite pairs are excluded independently for each model, project,
and comparison, with warnings; fewer than two pairs leave an SD gap, and zero
pairs also leave an outlier-count gap. The summary CSV records the paired
sample counts (`n`). Models are not restricted to a shared subject cohort:
use matching upstream inputs for fair comparisons and inspect the sample counts.

Deploy server and detach process from the appropriate folder path.
```bash
conda activate quicksin # Or whatever environment you use
nohup sh server.sh & tail -f nohup.out
```
kill server and uwsgi processes
```bash
ps x | grep [s]erver | sed 's/^ \+\([0-9]\+\).*/\1/g' | xargs kill && \
killall uwsgi && watch 'ps x'
```
Run the staging server that skips audio in favor of logged answers
```bash
FLASK_APP="debug:app" flask run -p 8088 --debug
```

To verify that the server is running, issue the following command from a terminal
```bash
curl -X POST https://quicksin.stanford.edu/jnd/api/lists
```

To run offline ASR on the collected utterances (From Kent's account):
```bash
source ~kent/env/bin/activate
python3 offline_asr.py --model tiny.en
```

To run offline ASR on the collected utterances (From Malcolm's account):
```bash
conda activate quicksin
python3 offline_asr.py --model tiny.en
```

[Colab that synthesizes the needed CSV transcript files](
https://colab.research.google.com/drive/1EOPHV74jawtxrZSQh94Dp5AFAGFt0Pkn?usp=sharing)

[Google drive folder with all the segmented data](
https://drive.google.com/drive/folders/1XfQn3eAjBY6h9Q7wruck7zqJVS7cCEQG)
And within that the Web_Audio folder has the renamed data we play to subjects.

## Adding tests
To add a new type of audio test do the following:
1. Add a section to the [colab](https://colab.research.google.com/drive/1EOPHV74jawtxrZSQh94Dp5AFAGFt0Pkn?usp=sharing) to create the transcript (csv) for the new test data. Watch for Google Drive permissions.
1. Add new transcript to the `metadata` folder matching the path in the spec class below
2. In `projects.py`, add a new spec, blueprint and database classes for the project
3. In `api.py`,
    1. Add the database and blueprint class to the import at the top,
    2. Add the new database class to the `ExperimentDB` parents,
    3. Add the blueprint class name to the dictionary of `APIBlueprint.projects`
4. To install a new test
    1. Run `python migrate.py projects.[ProjectDBClass]` (subclass of AudioDB)
5. To update an existing database (online test) do the following:
    1. Run `python migrate.py  # No extra arguments`
    2. Run `python migrate.py projects.[ProjectDBClass] --rewrite`
6. Add the audio files to `static/audio/[project]/*.wav`
7. Add `static/[project].html`, replace the project name in the inline script tag (let audio =..), and add `static/[project]_done.html`

## OAuth
1) [login client](https://github.com/kentslaney/login/) (as a sibling to jnd):
```bash
git clone https://github.com/kentslaney/login.git
```

2) [Google OAuth credentials page](
https://console.cloud.google.com/apis/credentials) Web application replacing
`sub.domain.tld` with the real subdomain

Authorized JavaScript origins: `https://sub.domain.tld`

Authorized redirect URIs: `https://sub.domain.tld/login/google/authorized`

3) put the resulting credentials in `login/run/credentials.json`:
```json
{
    "google": {"id": "username", "secret": "API key"}
}
```

4) in `login`
```bash
sh server.sh start
```

5) update owner id in `protected.py`:
```
malcolmslaney@gmail.com 110909794990702804159
mslaney@stanford.edu    100987618575971262389
Varsha Mysore Athreya   114354889327043931514
Matthew Fitzgerald      101607400393342786056
```

6) update `protected.py`'s value for `login_required.prefix` to the real
subdomain

7) with the environment running the QuickSIN server:
```bash
pip install -e path/to/login # ../login probably
```

8) change `server.sh` from `uwsgi.ini` to `login.ini` and start the QuickSIN
server

9) go to `/login/access/view/invite`, check the audio group, remove the
`invitees` value if you want the invite to work for more than one person,
and change the redirect URL to `/jnd`, then you can distribute the invite
