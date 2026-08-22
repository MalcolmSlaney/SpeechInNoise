"""Summarize rater annotations and ASR performance by subject and SNR.

Data selection
--------------
The program reads SQLite tables ``audio_results``, ``audio_trials``,
``audio_annotations``, ``review_annotations``, and ``audio_asr``. It keeps an
audio result when its trial matches ``--language`` and ``--project``, its ASR
data is non-empty, and it has non-empty ``review_annotations.data``. There is
also a subject validity filter: the username must fully match
``--subject_pattern`` (by default ``A\\d+[SP]\\d+``) and must not be in
``--excluded_subjects`` (by default ``A2P2``). ``audio_annotations`` is a left
join, so a missing audiologist annotation contributes a zero fraction rather
than excluding the result.

For each kept trial, the program extracts words from the JSON ASR ``text``
field and counts answer words recognized by the ASR, including slash-separated
alternatives and entries in ``--homonyms``. Boolean annotation lists are
converted to their fraction of ``true`` values.

Each output row and scatter-plot point represents one subject/project/SNR
group, not one rater or individual audio result. The point's coordinates are
the mean over that group's kept trial rows. If multiple reraters scored the
same audio, their review records are combined into the same group rather than
producing separate points:

* Plot 1: mean audiologist ``audio_annotations`` true fraction versus mean
    rerater ``review_annotations`` true fraction.
* Plot 2: mean ASR matched-word count divided by ``--max_words`` versus mean
    audiologist true fraction.
* Plot 3: the same normalized ASR value versus mean rerater true fraction.

The CSV also includes the group's subject, project, SNR, and trial count.
"""

import csv
import json
import logging
import math
import pandas as pd
import re
import sqlite3
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from absl import app
from absl import flags


FLAGS = flags.FLAGS
try:
    flags.DEFINE_string("dbfile", "experiments.db", "Path to the SQLite database.")
except flags.DuplicateFlagError:
    pass
flags.DEFINE_string("homonyms", "homonym_list.csv", "Path to the homonym CSV file.")
flags.DEFINE_string("language", "en", "Trial language to include.")
flags.DEFINE_string("project", "quick", "Project to include.")
flags.DEFINE_string(
    "subject_pattern",
    r"A\d+[SP]\d+",
    "Regular expression that a subject username must match completely.",
)
flags.DEFINE_list(
    "excluded_subjects",
    "A2P2",
    "Subject usernames to exclude explicitly.",
)
flags.DEFINE_string("output", "rater_summary.csv", "CSV file for the summary.")
flags.DEFINE_string("plot", "rater_summary.png", "PNG file for the optional plot.")
flags.DEFINE_bool("no_plot", False, "Do not create the summary plot.")
flags.DEFINE_integer(
    "max_words",
    5,
    "Maximum number of words used to normalize ASR matches.",
)
flags.DEFINE_bool(
    "per_trial",
    False,
    "Show results for each trial instead of aggregated by subject/project/SNR.",
)
flags.DEFINE_float(
    "alpha",
    0.7,
    "Opaqueness (alpha) of scatter plot dots. Range: 0.0 (transparent) to 1.0 (opaque).",
)
flags.DEFINE_string(
    "professional_raters",
    "metadata/professional_raters.txt",
    "Path to file with valid professional rater usernames (one per line).",
)
flags.DEFINE_string(
    "student_raters",
    "metadata/student_raters.txt",
    "Path to file with valid student rater usernames (one per line).",
)
flags.DEFINE_enum(
    "rater_type",
    "all",
    ["all", "professional", "student"],
    "Which raters to include: all, professional (from --professional_raters), or student (from --student_raters).",
)
flags.DEFINE_bool(
    "show_outliers",
    False,
    "Print trial details for rows where ASR score <= --outlier_asr_max and audiologist score >= --outlier_audio_min.",
)
flags.DEFINE_float("outlier_asr_max", 0.1, "ASR threshold for outlier detection (normalized, 0-1).")
flags.DEFINE_float("outlier_audio_min", 0.6, "Audiologist threshold for outlier detection (fraction true, 0-1).")
flags.DEFINE_string("subject_plot", "subject_rater_summary.png", "PNG file for the per-subject rater comparison plot.")
flags.DEFINE_bool("no_subject_plot", False, "Do not create the per-subject rater comparison plot.")
flags.DEFINE_string("residual_plot", "residual_summary.png", "PNG file for the per-subject residual histogram plot.")
flags.DEFINE_bool("no_residual_plot", False, "Do not create the per-subject residual histogram plot.")
flags.DEFINE_integer(
    "residual_debug_points",
    2,
    "Number of residual data points to print with raw values, baselines, and residuals (0 disables).",
)
flags.DEFINE_bool("show_regression", False, "Show OLS and slope-1 regression lines on the summary scatter plots.")
flags.DEFINE_enum(
    "residual_normalization",
    "normalization_by_snr",
    ["normalization_by_utterance", "normalization_by_snr"],
    "Residual normalization mode: 'normalization_by_utterance' uses the mean rater score for each utterance; "
    "'normalization_by_snr' uses the mean rater score across utterances with the same project and SNR.",
)
flags.DEFINE_bool(
    "dump_raw_data",
    False,
    "Dump raw per-utterance data (SNR, test name, ASR fraction correct, and each "
    "rater's fraction correct) for a single ASR configuration to --raw_output "
    "instead of writing the usual summary CSV/plots.",
)
flags.DEFINE_string(
    "asr_model",
    "large",
    "Whisper model_name to filter audio_asr rows to when --dump_raw_data is set "
    "(matches the 'model_name' key stored in audio_asr.data).",
)
flags.DEFINE_string(
    "raw_output",
    "residual_raw_data.pkl",
    "Path to write the raw per-utterance pandas DataFrame (pickle format) when "
    "--dump_raw_data is set.",
)


def read_professional_raters(filename: str) -> Set[str]:
    """Read rater usernames from a text file, ignoring comments and blank lines.

    Args:
        filename: Path to a text file with one username per line. Lines starting
            with ``#`` or containing only whitespace are ignored. If the file
            does not exist, an empty set is returned so that all raters are
            allowed.

    Returns:
        Set of username strings read from the file.
    """
    raters: Set[str] = set()
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                line = line.split("#", 1)[0].strip()
                if line:
                    raters.add(line)
    except FileNotFoundError:
        pass  # If file doesn't exist, allow all raters
    return raters


def read_homonyms(filename: str) -> Dict[str, Set[str]]:
    """Read comma-separated homonym groups and build a bidirectional lookup table.

    Each non-comment line contains a comma-separated group of words that are
    considered phonetically equivalent. The returned mapping allows looking up
    any word to find all its homonyms (excluding itself).

    Args:
        filename: Path to the CSV homonym file. Lines starting with ``#`` or
            containing only whitespace are ignored.

    Returns:
        Dict mapping each word to the set of its homonyms.
    """
    homonyms: Dict[str, Set[str]] = {}
    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            if line.startswith("#"):
                continue
            line = line.split("#", 1)[0].strip()
            words = [word.strip().lower() for word in line.split(",") if word.strip()]
            for word in words:
                homonyms.setdefault(word, set()).update(words)
                homonyms[word].discard(word)
    return homonyms


def extract_asr_words(asr_data: str) -> List[str]:
    """Extract lowercase words from a JSON-encoded Whisper ASR result.

    Parses the ``text`` field of the JSON object produced by Whisper and
    tokenizes it into individual word tokens.

    Args:
        asr_data: JSON string containing at minimum a ``text`` key with the
            ASR transcript. Returns an empty list if the string is empty,
            invalid JSON, or missing the ``text`` key.

    Returns:
        List of lowercase word tokens (letters, digits, and apostrophes only).
    """
    if not asr_data:
        return []
    try:
        text = str(json.loads(asr_data).get("text", "")).lower()
    except (AttributeError, json.JSONDecodeError, TypeError):
        return []
    return re.findall(r"\b[a-z0-9']+\b", text)


def extract_asr_model_name(asr_data: str) -> Optional[str]:
    """Return the Whisper ``model_name`` stored in a JSON-encoded ASR result.

    Args:
        asr_data: JSON string as stored in ``audio_asr.data``.

    Returns:
        The ``model_name`` value, or ``None`` if missing or unparseable.
    """
    if not asr_data:
        return None
    try:
        return json.loads(asr_data).get("model_name")
    except (AttributeError, json.JSONDecodeError, TypeError):
        return None


def score_trial(answer: str, asr_words: Iterable[str], homonyms: Dict[str, Set[str]]) -> int:
    """Count the number of distinct answer items recognized by the ASR.

    Each item in ``answer`` is a space-separated token that may contain
    slash-separated alternatives (e.g. ``'can/could'``). An item is counted as
    matched if any of its alternatives, their homonyms, or their
    apostrophe-stripped forms appear in the ASR word set.

    Args:
        answer: Ground-truth answer string with space-separated keyword items.
        asr_words: Iterable of words recognized by the ASR system.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.

    Returns:
        Number of distinct answer items that were matched.
    """
    asr_word_set = set(asr_words)
    answer_items = re.findall(r"\b[a-zA-Z/0-9']+\b", (answer or "").lower())
    matched_items: Set[str] = set()

    for item in answer_items:
        if item in matched_items:
            continue
        candidates: Set[str] = set()
        for component in item.split("/"):
            candidates.add(component)
            candidates.update(homonyms.get(component, set()))
            if "'" in component:
                candidates.add(component.replace("'", ""))
        if candidates.intersection(asr_word_set):
            matched_items.add(item)
    return len(matched_items)


def fraction_true(data: str) -> float:
    """Return the fraction of ``true`` values in a JSON or comma-separated list.

    Accepts annotation data stored either as a JSON array (e.g.
    ``'[true, false, true]'``) or as a plain comma-separated string. The
    comparison is case-insensitive.

    Args:
        data: Encoded list of boolean-like values. Returns ``0.0`` for empty
            or ``'[]'`` inputs.

    Returns:
        Fraction of values that equal ``'true'``, or ``0.0`` if the list is
        empty or unparseable.
    """
    if not data or data == "[]":
        return 0.0
    try:
        values: Any = json.loads(data)
        if not isinstance(values, list):
            raise ValueError("annotation data is not a list")
    except (TypeError, ValueError, json.JSONDecodeError):
        values = [item.strip() for item in data.strip("[]").split(",") if item.strip()]
    return sum(str(value).lower() == "true" for value in values) / len(values) if values else 0.0


def is_valid_subject(username: str, subject_pattern: str, excluded_subjects: Iterable[str]) -> bool:
    """Return whether a subject username passes the validity filter.

    A username is valid if it is not ``None``, fully matches ``subject_pattern``
    via :func:`re.fullmatch`, and is not in ``excluded_subjects``.

    Args:
        username: Username string from the ``users`` table.
        subject_pattern: Regular expression that must match the entire username.
        excluded_subjects: Iterable of usernames to reject regardless of pattern.

    Returns:
        ``True`` if the username is valid; ``False`` otherwise.
    """
    return (
        username is not None
        and re.fullmatch(subject_pattern, username) is not None
        and username not in set(excluded_subjects)
    )


def fetch_trials(
    dbfile: str,
    language: str,
    project: str,
    subject_pattern: str,
    excluded_subjects: Iterable[str],
    allowed_raters: Set[str],
) -> List[sqlite3.Row]:
    """Fetch trials from the database, filtered by subject and rater validity.

    Queries ``audio_results`` joined with ``audio_trials``, ``users``,
    ``audio_annotations`` (left join), ``review_annotations``,
    ``audio_asr`` (left join), filtering to rows with non-empty ASR and review
    annotation data for the given language and project. Rows are then
    post-filtered to valid subjects and allowed raters.

    Args:
        dbfile: Path to the SQLite database file.
        language: Value of ``audio_trials.lang`` to include.
        project: Value of ``audio_trials.project`` to include.
        subject_pattern: Regex passed to :func:`is_valid_subject` for subject
            username validation.
        excluded_subjects: Usernames to reject regardless of pattern match.
        allowed_raters: Set of labeler usernames to accept. An empty set means
            all raters are allowed.

    Returns:
        List of :class:`sqlite3.Row` objects with columns: ``user``,
        ``username``, ``project``, ``snr``, ``answer``, ``utterance_id``,
        ``audio_annotation_data``, ``review_annotation_data``,
        ``audio_asr_data``, ``labeler_username``.
    """
    subject_regex = re.compile(subject_pattern)
    excluded = set(excluded_subjects)
    with sqlite3.connect(dbfile) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT DISTINCT
                ar.subject AS user,
                u.username AS username,
                at.project,
                at.snr,
                at.answer,
                ar.id AS utterance_id,
                aa.data AS audio_annotation_data,
                ra.data AS review_annotation_data,
                asr.data AS audio_asr_data,
                labeler_user.username AS labeler_username
            FROM audio_results ar
            JOIN audio_trials at ON ar.trial = at.id
            JOIN users u ON ar.subject = u.id
            LEFT JOIN audio_annotations aa ON ar.id = aa.ref
            JOIN review_annotations ra ON ar.id = ra.ref
            JOIN users labeler_user ON ra.labeler = labeler_user.id
            LEFT JOIN audio_asr asr ON ar.id = asr.ref
            WHERE at.lang = ?
              AND at.project = ?
              AND asr.data IS NOT NULL AND asr.data != ''
              AND ra.data IS NOT NULL AND ra.data != ''
            """,
            (language, project),
        ).fetchall()
    
    valid_rows = []
    for row in rows:
        if is_valid_subject(row["username"], subject_regex.pattern, excluded):
            if not allowed_raters or row["labeler_username"] in allowed_raters:
                valid_rows.append(row)
    return valid_rows


def build_raw_dataframe(rows: Iterable[sqlite3.Row], 
                        homonyms: Dict[str, Set[str]], 
                        asr_model: str) -> pd.DataFrame:
    """Build a wide per-utterance DataFrame for a single ASR configuration.

    Meant to let the residual math elsewhere in this module be checked by hand
    against the raw inputs: one row per utterance with the SNR, test
    (project) name, the ASR fraction correct, and the fraction correct
    reported by each individual rater (plus the audiologist annotation, if
    present) as separate columns.

    Args:
        rows: Raw trial rows as returned by :func:`fetch_trials`.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.
        asr_model: Whisper ``model_name`` to keep; other rows are dropped.

    Returns:
        DataFrame indexed by ``utterance_id`` with columns ``project``,
        ``snr``, ``subject``, ``asr_fraction_correct``,
        ``audiologist_fraction_correct``, and one ``rater_<username>`` column
        per distinct labeler.
    """
    records = []
    for row in rows:
        if extract_asr_model_name(row["audio_asr_data"]) != asr_model:
            continue
        matched = score_trial(row["answer"], extract_asr_words(row["audio_asr_data"]), homonyms)
        records.append(
            {
                "utterance_id": row["utterance_id"],
                "project": row["project"],
                "snr": row["snr"],
                "subject": row["username"],
                "asr_fraction_correct": matched / FLAGS.max_words,
                "audiologist_fraction_correct": fraction_true(row["audio_annotation_data"]),
                "rater_username": row["labeler_username"],
                "rater_fraction_correct": fraction_true(row["review_annotation_data"]),
            }
        )

    long_df = pd.DataFrame.from_records(records)
    if long_df.empty:
        return long_df

    base_columns = ["utterance_id", "project", "snr", "subject", "asr_fraction_correct",
                     "audiologist_fraction_correct"]
    base = long_df[base_columns].drop_duplicates(subset="utterance_id").set_index("utterance_id")

    rater_pivot = long_df.pivot_table(
        index="utterance_id",
        columns="rater_username",
        values="rater_fraction_correct",
        aggfunc="mean",
    )
    rater_pivot.columns = [f"rater_{name}" for name in rater_pivot.columns]

    return base.join(rater_pivot).reset_index()


def summarize(rows: Iterable[sqlite3.Row], homonyms: Dict[str, Set[str]], per_trial: bool = False) -> List[Dict[str, Any]]:
    """Compute per-group or per-trial annotation and ASR metrics.

    When ``per_trial`` is ``False`` (the default), rows are grouped by
    ``(user, project, snr)`` and the metrics are averaged within each group.
    When ``per_trial`` is ``True``, each row produces one output record
    without averaging.

    Args:
        rows: Iterable of database rows as returned by :func:`fetch_trials`.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.
        per_trial: If ``True``, return one record per row instead of aggregating
            by subject/project/SNR group.

    Returns:
        List of dicts with keys: ``user``, ``project``, ``snr``, ``records``,
        ``mean_fraction_audio_annotation_true``,
        ``mean_fraction_review_annotation_true``,
        ``average_matched_word_count``, ``normalized_matched_word_count``.
    """
    if per_trial:
        # Return one entry per trial without aggregation
        summary = []
        for row in rows:
            audio_fraction = fraction_true(row["audio_annotation_data"])
            review_fraction = fraction_true(row["review_annotation_data"])
            matched_words = score_trial(row["answer"], extract_asr_words(row["audio_asr_data"]), homonyms)
            summary.append(
                {
                    "user": row["user"],
                    "project": row["project"],
                    "snr": row["snr"],
                    "records": 1,
                    "mean_fraction_audio_annotation_true": audio_fraction,
                    "mean_fraction_review_annotation_true": review_fraction,
                    "average_matched_word_count": matched_words,
                    "normalized_matched_word_count": matched_words / FLAGS.max_words,
                }
            )
        return summary
    
    # Original aggregation by (user, project, snr)
    groups: Dict[Tuple[Any, str, Any], List[Tuple[float, float, int]]] = defaultdict(list)
    for row in rows:
        groups[(row["user"], row["project"], row["snr"])].append(
            (
                fraction_true(row["audio_annotation_data"]),
                fraction_true(row["review_annotation_data"]),
                score_trial(row["answer"], extract_asr_words(row["audio_asr_data"]), homonyms),
            )
        )

    summary = []
    for (user, project, snr), values in sorted(groups.items(), key=lambda item: item[0]):
        count = len(values)
        audio_fraction = sum(value[0] for value in values) / count
        review_fraction = sum(value[1] for value in values) / count
        matched_words = sum(value[2] for value in values) / count
        summary.append(
            {
                "user": user,
                "project": project,
                "snr": snr,
                "records": count,
                "mean_fraction_audio_annotation_true": audio_fraction,
                "mean_fraction_review_annotation_true": review_fraction,
                "average_matched_word_count": matched_words,
                "normalized_matched_word_count": matched_words / FLAGS.max_words,
            }
        )
    return summary


def pearson(x: List[float], y: List[float]) -> float:
    """Compute Pearson's correlation coefficient without requiring SciPy.

    Args:
        x: First sequence of numeric values.
        y: Second sequence of numeric values, same length as ``x``.

    Returns:
        Pearson correlation in the range ``[-1, 1]``, or ``nan`` if fewer than
        two data points are provided or if either variable has zero variance.
    """
    if len(x) < 2:
        return float("nan")
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    denominator = math.sqrt(
        sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y)
    )
    return numerator / denominator if denominator else float("nan")


def write_csv(summary: List[Dict[str, Any]]) -> None:
    """Write summary rows to the CSV file specified by ``--output``.

    Args:
        summary: List of summary dicts as returned by :func:`summarize`. The
            field names are taken from the first dict's keys. Does nothing if
            ``summary`` is empty.
    """
    fields = list(summary[0]) if summary else [
        "user", "project", "snr", "records",
        "mean_fraction_audio_annotation_true",
        "mean_fraction_review_annotation_true",
        "average_matched_word_count", "normalized_matched_word_count",
    ]
    with open(FLAGS.output, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)


def print_outlier_details(
    rows: List[sqlite3.Row],
    homonyms: Dict[str, Set[str]],
    asr_max: float,
    audio_min: float,
) -> None:
    """Print ground truth, ASR transcript, and audiologist annotations for outlier trials.

    An outlier is a trial where the normalized ASR score is at or below
    ``asr_max`` and the audiologist true fraction is at or above ``audio_min``.

    Args:
        rows: Raw trial rows as returned by :func:`fetch_trials`.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.
        asr_max: Maximum normalized ASR score to qualify as an outlier.
        audio_min: Minimum audiologist true fraction to qualify as an outlier.
    """
    found = 0
    for row in rows:
        asr_words = extract_asr_words(row["audio_asr_data"])
        matched = score_trial(row["answer"], asr_words, homonyms)
        normalized_asr = matched / FLAGS.max_words
        audio_fraction = fraction_true(row["audio_annotation_data"])
        if normalized_asr <= asr_max and audio_fraction >= audio_min:
            found += 1
            asr_text = ""
            try:
                asr_text = json.loads(row["audio_asr_data"]).get("text", "").strip()
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            print(
                f"--- Outlier {found} ---\n"
                f"  Subject:      {row['username']} (id={row['user']})\n"
                f"  Project/SNR:  {row['project']} / {row['snr']}\n"
                f"  Ground truth: {row['answer']}\n"
                f"  ASR output:   {asr_text}\n"
                f"  ASR matched:  {matched}/{FLAGS.max_words} (normalized={normalized_asr:.2f})\n"
                f"  Audiologist:  {row['audio_annotation_data']} (fraction={audio_fraction:.2f})\n"
                f"  Rerater:      {row['review_annotation_data']}\n"
            )
    if not found:
        print(f"No outliers found with ASR <= {asr_max} and audiologist >= {audio_min}.")


def print_statistics(summary: List[Dict[str, Any]]) -> None:
    """Print Pearson correlation and mean bias for the three rater comparisons.

    Prints one line per comparison showing the Pearson r and the mean signed
    difference (Y - X).

    Args:
        summary: List of summary dicts as returned by :func:`summarize`.
    """
    comparisons = [
        ("Audiologists vs. Raters", "mean_fraction_audio_annotation_true", "mean_fraction_review_annotation_true"),
        ("ASR vs. Audiologists", "normalized_matched_word_count", "mean_fraction_audio_annotation_true"),
        ("ASR vs. Raters", "normalized_matched_word_count", "mean_fraction_review_annotation_true"),
    ]
    print(f"Fetched {len(summary)} subject/project/SNR summaries.")
    for name, x_key, y_key in comparisons:
        x = [row[x_key] for row in summary]
        y = [row[y_key] for row in summary]
        correlation = pearson(x, y)
        bias = sum(b - a for a, b in zip(x, y)) / len(y) if y else float("nan")
        print(f"{name}: Pearson={correlation:.3f}, bias (Y-X)={bias:.3f}")


def fit_regression(x: List[float], y: List[float], fixed_slope: Optional[float] = None) -> Tuple[float, float]:
    """Fit a linear model to ``(x, y)`` data, optionally with a fixed slope.

    Uses two algorithms depending on whether a fixed slope is provided:

    1. **Fixed-slope fit** (``fixed_slope`` is not ``None``): intercept is the
       mean residual ``mean(y - fixed_slope * x)``. Used for the slope=1
       perfect-agreement line.
    2. **OLS fit** (``fixed_slope`` is ``None``): slope is
       ``cov(x, y) / var(x)`` and intercept is ``mean(y) - slope * mean(x)``.

    Args:
        x: Predictor values.
        y: Response values, same length as ``x``.
        fixed_slope: If provided, hold the slope at this value and solve only
            for the intercept.

    Returns:
        Tuple of ``(slope, intercept)``.
    """
    if fixed_slope is not None:
        return fixed_slope, sum(y_i - fixed_slope * x_i for x_i, y_i in zip(x, y)) / len(y)

    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    denominator = sum((x_i - x_mean) ** 2 for x_i in x)
    if not denominator:
        return 0.0, y_mean
    slope = sum((x_i - x_mean) * (y_i - y_mean) for x_i, y_i in zip(x, y)) / denominator
    return slope, y_mean - slope * x_mean


def add_fit_line(axis, x: List[float], y: List[float], slope: float, bias: float, linestyle: str, label_y_offset: float) -> None:
    """Draw a regression line with a rotated slope/intercept label on a matplotlib axis.

    The label is rendered at the midpoint of the line and rotated to match the
    line's angle in display coordinates.

    Args:
        axis: Matplotlib ``Axes`` object to draw on.
        x: X data values used to determine the line's horizontal extent.
        y: Y data values (unused for drawing; kept for API symmetry).
        slope: Slope of the line.
        bias: Y-intercept of the line.
        linestyle: Matplotlib linestyle string (e.g. ``'--'`` or ``':'``).
        label_y_offset: Vertical offset in data units applied to the label
            position to avoid overlap with the line.
    """
    x_start, x_end = min(x), max(x)
    if x_start == x_end:
        x_start -= 0.05
        x_end += 0.05
    y_start = slope * x_start + bias
    y_end = slope * x_end + bias
    axis.plot([x_start, x_end], [y_start, y_end], linestyle=linestyle, color="black", linewidth=1.2)

    label_x = (x_start + x_end) / 2
    label_y = slope * label_x + bias + label_y_offset
    display_start = axis.transData.transform((x_start, y_start))
    display_end = axis.transData.transform((x_end, y_end))
    angle = math.degrees(math.atan2(display_end[1] - display_start[1], display_end[0] - display_start[0]))
    axis.text(
        label_x,
        label_y,
        f"m={slope:.2g}, b={bias:.2g}",
        rotation=angle,
        rotation_mode="anchor",
        ha="center",
        va="bottom",
        fontsize=8,
        backgroundcolor="white",
    )


def scatter_plot(axis, summary: List[Dict[str, Any]], x_key: str, y_key: str,
                 x_label: str, y_label: str, marker_size: float = 50,
                 alpha: float = 0.7, title_suffix: str = "") -> None:
    """Render a single scatter panel with OLS and slope-1 regression overlays.

    Each dot represents one row of ``summary`` (a subject/project/SNR group or
    an individual trial, depending on ``--per_trial``). Two regression lines
    are drawn: a dashed OLS fit and a dotted slope-1 (perfect agreement) line.
    The Pearson correlation is shown in the panel title.

    Args:
        axis: Matplotlib ``Axes`` object to draw on.
        summary: List of summary dicts as returned by :func:`summarize`.
        x_key: Dict key for the X-axis values.
        y_key: Dict key for the Y-axis values.
        x_label: Axis label for the X axis.
        y_label: Axis label for the Y axis.
        marker_size: Scatter dot size in points squared.
        alpha: Dot opacity in the range ``[0, 1]``.
        title_suffix: Optional string appended to the panel title in
            parentheses alongside the Pearson r value.
    """
    x = [row[x_key] for row in summary]
    y = [row[y_key] for row in summary]
    axis.scatter(x, y, s=marker_size, alpha=alpha)
    if FLAGS.show_regression:
        full_slope, full_bias = fit_regression(x, y)
        fixed_slope, fixed_bias = fit_regression(x, y, fixed_slope=1.0)
        x_span = max(y) - min(y) if y else 0.0
        label_offset = max(0.01, x_span * 0.04)
        add_fit_line(axis, x, y, full_slope, full_bias, "--", label_offset)
        add_fit_line(axis, x, y, fixed_slope, fixed_bias, ":", -label_offset)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    
    # Calculate and display Pearson correlation
    r = pearson(x, y)
    r_text = f"r={r:.3f}" if not math.isnan(r) else "r=N/A"
    
    if title_suffix:
        axis.set_title(f"{x_label} vs {y_label}\n({title_suffix}, {r_text})")
    else:
        axis.set_title(f"{x_label} vs {y_label}\n({r_text})")
    
    axis.grid(True, linestyle="--", alpha=0.6)


def create_residual_plot(
    rows: List[sqlite3.Row],
    homonyms: Dict[str, Set[str]],
    professional_raters: Set[str],
    student_raters: Set[str],
) -> None:
    """Create and save a histogram of mean-subtracted ASR and rater scores.

        Residual baselines use professional+student rater scores and are controlled
        by ``--residual_normalization``:

        * ``normalization_by_utterance``: baseline is the mean rater score for each utterance.
        * ``normalization_by_snr``: baseline is the mean rater score across utterances
            with the same project and SNR.

    Args:
        rows: Raw trial rows as returned by :func:`fetch_trials`.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.
        professional_raters: Set of professional rater usernames.
        student_raters: Set of student rater usernames.
    """
    import matplotlib.pyplot as plt

    valid_raters = professional_raters | student_raters

    # Accumulate per-utterance ASR and review scores for valid raters.
    # Key: (project, snr, utterance_id)
    asr_scores: Dict[Tuple[str, Any, Any], float] = {}
    utterance_rater_scores: Dict[Tuple[str, Any, Any], List[float]] = defaultdict(list)

    for row in rows:
        utterance_key = (row["project"], row["snr"], row["utterance_id"])
        if utterance_key not in asr_scores:
            matched = score_trial(row["answer"], extract_asr_words(row["audio_asr_data"]), homonyms)
            asr_scores[utterance_key] = matched / FLAGS.max_words
        if row["labeler_username"] in valid_raters:
            utterance_rater_scores[utterance_key].append(
                fraction_true(row["review_annotation_data"])
            )

    utterance_means: Dict[Tuple[str, Any, Any], float] = {
        key: (sum(scores) / len(scores))
        for key, scores in utterance_rater_scores.items()
        if scores
    }

    baseline_by_utterance: Dict[Tuple[str, Any, Any], float] = {}
    if FLAGS.residual_normalization == "normalization_by_utterance":
        baseline_by_utterance = utterance_means
    else:
        # Compute project/SNR baseline as the mean across utterance means.
        project_snr_to_utterance_means: Dict[Tuple[str, Any], List[float]] = defaultdict(list)
        for (project, snr, _utterance_id), mean_value in utterance_means.items():
            project_snr_to_utterance_means[(project, snr)].append(mean_value)
        project_snr_baseline = {
            key: (sum(values) / len(values))
            for key, values in project_snr_to_utterance_means.items()
            if values
        }
        baseline_by_utterance = {
            (project, snr, utterance_id): project_snr_baseline[(project, snr)]
            for (project, snr, utterance_id) in utterance_means
            if (project, snr) in project_snr_baseline
        }

    asr_residuals = [
        asr_scores[key] - baseline_by_utterance[key]
        for key in asr_scores
        if key in baseline_by_utterance
    ]
    rater_residuals: List[float] = []
    for key, scores in utterance_rater_scores.items():
        if key not in baseline_by_utterance:
            continue
        baseline = baseline_by_utterance[key]
        rater_residuals.extend(score - baseline for score in scores)

    debug_point_count = max(0, FLAGS.residual_debug_points)
    if debug_point_count:
        print(
            f"Residual debug samples (mode={FLAGS.residual_normalization}, count={debug_point_count}):"
        )
        if FLAGS.residual_normalization == "normalization_by_utterance":
            sample_keys = sorted(baseline_by_utterance.keys())[:debug_point_count]
            for key in sample_keys:
                project, snr, utterance_id = key
                baseline = baseline_by_utterance[key]
                asr_value = asr_scores.get(key)
                rater_values = utterance_rater_scores.get(key, [])
                asr_residual = asr_value - baseline if asr_value is not None else float("nan")
                rater_res = [value - baseline for value in rater_values]
                print(
                    "  utterance "
                    f"project={project}, snr={snr}, utterance_id={utterance_id}: "
                    f"asr={asr_value:.4f}, raters={rater_values}, baseline={baseline:.4f}, "
                    f"asr_residual={asr_residual:.4f}, rater_residuals={rater_res}"
                )
        else:
            snr_buckets: Dict[Tuple[str, Any], List[Tuple[str, Any, Any]]] = defaultdict(list)
            for key in baseline_by_utterance:
                project, snr, _utterance_id = key
                snr_buckets[(project, snr)].append(key)
            sample_buckets = sorted(snr_buckets.keys())[:debug_point_count]
            for bucket in sample_buckets:
                project, snr = bucket
                bucket_keys = sorted(snr_buckets[bucket])
                baseline = baseline_by_utterance[bucket_keys[0]]
                utterance_rows = []
                for key in bucket_keys:
                    asr_value = asr_scores.get(key)
                    rater_values = utterance_rater_scores.get(key, [])
                    utterance_rows.append(
                        {
                            "utterance_id": key[2],
                            "asr": asr_value,
                            "raters": rater_values,
                            "asr_residual": (asr_value - baseline) if asr_value is not None else float("nan"),
                            "rater_residuals": [value - baseline for value in rater_values],
                        }
                    )
                print(
                    "  snr-bucket "
                    f"project={project}, snr={snr}: baseline={baseline:.4f}, "
                    f"utterances={utterance_rows}"
                )

    if not asr_residuals or not rater_residuals:
        print(
            "Residual standard deviation summary: "
            "ASR=nan (n=0), Rater=nan (n=0), ASR/Rater=nan"
        )
        print("Skipping residual plot: no valid residuals available.")
        return

    def population_std(values: List[float]) -> float:
        if not values:
            return float("nan")
        mean_value = sum(values) / len(values)
        return math.sqrt(sum((value - mean_value) ** 2 for value in values) / len(values))

    asr_std = population_std(asr_residuals)
    rater_std = population_std(rater_residuals)
    std_ratio = asr_std / rater_std if (not math.isnan(asr_std) and not math.isnan(rater_std) and rater_std != 0) else float("nan")
    print(
        "Residual standard deviation summary: "
        f"ASR={asr_std:.4f} (n={len(asr_residuals)}), "
        f"Rater={rater_std:.4f} (n={len(rater_residuals)}), "
        f"ASR/Rater={std_ratio:.4f}"
    )

    figure, axis = plt.subplots()
    all_residuals = asr_residuals + rater_residuals
    lo, hi = min(all_residuals), max(all_residuals)
    step = (hi - lo) / 40
    bins = [lo + i * step for i in range(41)]
    axis.hist(asr_residuals, bins=bins, alpha=0.6, color="steelblue", label="ASR residuals")
    axis.hist(rater_residuals, bins=bins, alpha=0.6, color="crimson", label="Rater residuals")
    axis.axvline(0, color="black", linewidth=0.8, linestyle="--")
    if FLAGS.residual_normalization == "normalization_by_utterance":
        axis.set_xlabel("Score - per-utterance mean rater score")
        axis.set_title("Residuals after removing per-utterance rater baseline")
    else:
        axis.set_xlabel("Score - mean rater score for matching project/SNR")
        axis.set_title("Residuals after removing project/SNR rater baseline")
    axis.set_ylabel("Count")
    axis.legend(fontsize=9)
    axis.grid(True, axis="y", linestyle="--", alpha=0.5)
    figure.tight_layout()
    figure.savefig(FLAGS.residual_plot, dpi=150)
    print(f"Wrote residual plot to {FLAGS.residual_plot}")


def create_subject_rater_plot(
    rows: List[sqlite3.Row],
    homonyms: Dict[str, Set[str]],
    professional_raters: Set[str],
    student_raters: Set[str],
) -> None:
    """Create and save a per-subject plot comparing ASR and rater scores.

    Each subject occupies one x-position. A single dot shows the subject's
    mean normalized ASR score. Additional dots show each rater's mean fraction
    of words marked correct, color-coded by rater type.

    Args:
        rows: Raw trial rows as returned by :func:`fetch_trials`.
        homonyms: Bidirectional homonym map as returned by :func:`read_homonyms`.
        professional_raters: Set of professional rater usernames.
        student_raters: Set of student rater usernames.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    # Accumulate per-subject ASR scores and per-(subject, rater) review fractions
    asr_scores: Dict[Any, List[float]] = defaultdict(list)
    rater_scores: Dict[Tuple[Any, str], List[float]] = defaultdict(list)

    for row in rows:
        subject = row["user"]
        matched = score_trial(row["answer"], extract_asr_words(row["audio_asr_data"]), homonyms)
        asr_scores[subject].append(matched / FLAGS.max_words)
        rater_scores[(subject, row["labeler_username"])].append(
            fraction_true(row["review_annotation_data"])
        )

    subjects = sorted(asr_scores.keys())
    x_positions = {subject: i for i, subject in enumerate(subjects)}

    figure, axis = plt.subplots(figsize=(max(6, len(subjects) * 0.25), 5))

    # Plot ASR result per subject as an 'x'
    for subject, scores in asr_scores.items():
        axis.scatter(
            x_positions[subject], sum(scores) / len(scores),
            color="steelblue", s=60, zorder=3, alpha=FLAGS.alpha, marker="x",
        )

    # Plot one dot per (subject, rater) for professional and student raters only
    for (subject, rater), scores in rater_scores.items():
        if rater in professional_raters:
            color = "crimson"
        elif rater in student_raters:
            color = "darkorange"
        else:
            continue
        axis.scatter(
            x_positions[subject], sum(scores) / len(scores),
            color=color, s=30, zorder=2, alpha=FLAGS.alpha,
        )

    axis.set_xticks(range(len(subjects)))
    axis.set_xticklabels(
        [str(s) for s in subjects], rotation=45, ha="right", fontsize=7
    )
    axis.set_xlabel("Subject #")
    axis.set_ylabel("Fraction correct")
    axis.set_title("Per-subject ASR and rater scores")
    axis.grid(True, axis="y", linestyle="--", alpha=0.5)

    legend_handles = [
        mpatches.Patch(color="steelblue", label="ASR"),
        mpatches.Patch(color="crimson", label="Professional rater"),
        mpatches.Patch(color="darkorange", label="Student rater"),
    ]
    axis.legend(handles=legend_handles, loc="upper right", fontsize=8)

    figure.tight_layout()
    figure.savefig(FLAGS.subject_plot, dpi=150)
    print(f"Wrote subject plot to {FLAGS.subject_plot}")


def create_plot(summary: List[Dict[str, Any]], per_trial: bool = False) -> None:
    """Create and save the three-panel scatter plot.

    The three panels compare: (1) audiologist vs. rerater fractions,
    (2) normalized ASR score vs. audiologist fraction, and (3) normalized ASR
    score vs. rerater fraction. The plot is saved to the path given by
    ``--plot``.

    Args:
        summary: List of summary dicts as returned by :func:`summarize`.
        per_trial: If ``True``, the aggregation label in each panel title reads
            "Per Trial"; otherwise "Subject/Project/SNR Aggregates".
    """
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 3, figsize=(12, 4))
    aggregation_label = "Per Trial" if per_trial else "Subject/Project/SNR Aggregates"
    rater_label = FLAGS.rater_type.capitalize() + " Reraters"

    scatter_plot(
        axes[0], summary,
        "mean_fraction_audio_annotation_true",
        "mean_fraction_review_annotation_true",
        "Audiologist", rater_label, marker_size=50, alpha=FLAGS.alpha,
        title_suffix=aggregation_label,
    )
    scatter_plot(
        axes[1], summary,
        "normalized_matched_word_count",
        "mean_fraction_audio_annotation_true",
        "ASR", "Audiologist", marker_size=50, alpha=FLAGS.alpha,
        title_suffix=aggregation_label,
    )
    scatter_plot(
        axes[2], summary,
        "normalized_matched_word_count",
        "mean_fraction_review_annotation_true",
        "ASR", rater_label, marker_size=50, alpha=FLAGS.alpha,
        title_suffix=aggregation_label,
    )
    figure.tight_layout()
    figure.savefig(FLAGS.plot, dpi=150)
    print(f"Wrote plot to {FLAGS.plot}")


def main(argv: List[str]) -> None:
    """Entry point: load data, compute summaries, write CSV and optional plot.

    Args:
        argv: Unused command-line arguments (consumed by ABSL).
    """
    del argv
    logging.info(
        f"Starting summarize_raters: dbfile={FLAGS.dbfile}, language={FLAGS.language}, "
        f"project={FLAGS.project}, per_trial={FLAGS.per_trial}"
    )
    homonyms = read_homonyms(FLAGS.homonyms)
    professional_raters = read_professional_raters(FLAGS.professional_raters)
    student_raters = read_professional_raters(FLAGS.student_raters)
    logging.info(
        f"Loaded {len(professional_raters)} professional raters, {len(student_raters)} student raters, "
        f"rater_type={FLAGS.rater_type}"
    )
    if FLAGS.rater_type == "professional":
        allowed_raters = professional_raters
    elif FLAGS.rater_type == "student":
        allowed_raters = student_raters
    else:
        allowed_raters = set()  # empty means allow all
    rows = fetch_trials(
        FLAGS.dbfile,
        FLAGS.language,
        FLAGS.project,
        FLAGS.subject_pattern,
        FLAGS.excluded_subjects,
        allowed_raters,
    )
    if FLAGS.dump_raw_data:
        logging.info(f"Fetched {len(rows)} rows before filtering by asr_model={FLAGS.asr_model}")
        dataframe = build_raw_dataframe(rows, homonyms, FLAGS.asr_model)
        if dataframe.empty:
            print(f"No rows found for asr_model={FLAGS.asr_model!r}; nothing written.")
            return
        dataframe.to_pickle(FLAGS.raw_output)
        print(f"Wrote {len(dataframe)} utterance rows to {FLAGS.raw_output}")
        print(dataframe.head())
        return
    summary = summarize(rows, homonyms, per_trial=FLAGS.per_trial)
    if FLAGS.show_outliers:
        print_outlier_details(rows, homonyms, FLAGS.outlier_asr_max, FLAGS.outlier_audio_min)
    write_csv(summary)
    print_statistics(summary)
    print(f"Wrote summary to {FLAGS.output}")
    if summary and not FLAGS.no_plot:
        create_plot(summary, per_trial=FLAGS.per_trial)
    if rows and not FLAGS.no_subject_plot:
        create_subject_rater_plot(rows, homonyms, professional_raters, student_raters)
    if rows and not FLAGS.no_residual_plot:
        create_residual_plot(rows, homonyms, professional_raters, student_raters)


if __name__ == "__main__":
    app.run(main)