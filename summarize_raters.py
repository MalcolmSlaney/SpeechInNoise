"""Summarize rater annotations and ASR performance by subject and SNR.

Data selection
--------------
The program reads SQLite tables ``audio_results``, ``audio_trials``,
``audio_annotations``, ``review_annotations``, and ``audio_asr``. It keeps an
audio result when its trial matches ``--language`` and ``--project``, its ASR
data is non-empty, and it has non-empty ``review_annotations.data``. There is
also a subject validity filter: the username must fully match
``--subject_pattern`` (by default ``A\d+[SP]\d+``) and must not be in
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
import math
import re
import sqlite3
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from absl import app
from absl import flags


FLAGS = flags.FLAGS
try:
    flags.DEFINE_string("dbfile", "experiments_malcolm.db", "Path to the SQLite database.")
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


def read_homonyms(filename: str) -> Dict[str, Set[str]]:
    """Read comma-separated, bidirectional homonym groups."""
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
    """Extract lowercase words from a JSON-encoded Whisper result."""
    if not asr_data:
        return []
    try:
        text = str(json.loads(asr_data).get("text", "")).lower()
    except (AttributeError, json.JSONDecodeError, TypeError):
        return []
    return re.findall(r"\b[a-z0-9']+\b", text)


def score_trial(answer: str, asr_words: Iterable[str], homonyms: Dict[str, Set[str]]) -> int:
    """Return the number of distinct answer items recognized by the ASR."""
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
    """Return the fraction of true values in a JSON or list-like value."""
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
    """Return whether a subject username is valid and not explicitly excluded."""
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
) -> List[sqlite3.Row]:
    """Fetch valid-subject trials with computed ASR and reviewer annotations."""
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
                aa.data AS audio_annotation_data,
                ra.data AS review_annotation_data,
                asr.data AS audio_asr_data
            FROM audio_results ar
            JOIN audio_trials at ON ar.trial = at.id
            JOIN users u ON ar.subject = u.id
            LEFT JOIN audio_annotations aa ON ar.id = aa.ref
            JOIN review_annotations ra ON ar.id = ra.ref
            JOIN audio_asr asr ON ar.id = asr.ref
            WHERE at.lang = ?
              AND at.project = ?
              AND asr.data IS NOT NULL AND asr.data != ''
              AND ra.data IS NOT NULL AND ra.data != ''
            """,
            (language, project),
        ).fetchall()
    return [
        row for row in rows
        if is_valid_subject(row["username"], subject_regex.pattern, excluded)
    ]


def summarize(rows: Iterable[sqlite3.Row], homonyms: Dict[str, Set[str]]) -> List[Dict[str, Any]]:
    """Aggregate trial metrics by user, project, and SNR."""
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
    """Calculate Pearson's correlation without requiring SciPy."""
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
    """Write summary rows to the configured CSV file."""
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


def print_statistics(summary: List[Dict[str, Any]]) -> None:
    """Print the three notebook comparisons and their correlations."""
    comparisons = [
        ("Audio vs. Review Annotation", "mean_fraction_audio_annotation_true", "mean_fraction_review_annotation_true"),
        ("Matched Words vs. Audio Annotation", "normalized_matched_word_count", "mean_fraction_audio_annotation_true"),
        ("Matched Words vs. Review Annotation", "normalized_matched_word_count", "mean_fraction_review_annotation_true"),
    ]
    print(f"Fetched {len(summary)} subject/project/SNR summaries.")
    for name, x_key, y_key in comparisons:
        x = [row[x_key] for row in summary]
        y = [row[y_key] for row in summary]
        correlation = pearson(x, y)
        bias = sum(b - a for a, b in zip(x, y)) / len(y) if y else float("nan")
        print(f"{name}: Pearson={correlation:.3f}, bias (Y-X)={bias:.3f}")


def fit_regression(x: List[float], y: List[float], fixed_slope: Optional[float] = None) -> Tuple[float, float]:
    """Return slope and intercept for a full or fixed-slope linear fit."""
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
    """Draw a regression line and a rotated label aligned to that line."""
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
                 alpha: float = 0.7) -> None:
    """Plot one comparison with full and slope-one regression fits."""
    x = [row[x_key] for row in summary]
    y = [row[y_key] for row in summary]
    axis.scatter(x, y, s=marker_size, alpha=alpha)
    full_slope, full_bias = fit_regression(x, y)
    fixed_slope, fixed_bias = fit_regression(x, y, fixed_slope=1.0)
    x_span = max(y) - min(y) if y else 0.0
    label_offset = max(0.01, x_span * 0.04)
    add_fit_line(axis, x, y, full_slope, full_bias, "--", label_offset)
    add_fit_line(axis, x, y, fixed_slope, fixed_bias, ":", -label_offset)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.grid(True, linestyle="--", alpha=0.6)


def create_plot(summary: List[Dict[str, Any]]) -> None:
    """Create the notebook's three-panel scatter plot."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 3, figsize=(12, 4))
    scatter_plot(
        axes[0], summary,
        "mean_fraction_audio_annotation_true",
        "mean_fraction_review_annotation_true",
        "Audiologist", "Reraters", marker_size=50, alpha=0.7,
    )
    scatter_plot(
        axes[1], summary,
        "normalized_matched_word_count",
        "mean_fraction_audio_annotation_true",
        "ASR", "Audiologist", marker_size=50, alpha=0.7,
    )
    scatter_plot(
        axes[2], summary,
        "normalized_matched_word_count",
        "mean_fraction_review_annotation_true",
        "ASR", "Reraters", marker_size=50, alpha=0.7,
    )
    figure.tight_layout()
    figure.savefig(FLAGS.plot, dpi=150)
    print(f"Wrote plot to {FLAGS.plot}")


def main(argv: List[str]) -> None:
    del argv
    homonyms = read_homonyms(FLAGS.homonyms)
    rows = fetch_trials(
        FLAGS.dbfile,
        FLAGS.language,
        FLAGS.project,
        FLAGS.subject_pattern,
        FLAGS.excluded_subjects,
    )
    summary = summarize(rows, homonyms)
    write_csv(summary)
    print_statistics(summary)
    print(f"Wrote summary to {FLAGS.output}")
    if summary and not FLAGS.no_plot:
        create_plot(summary)


if __name__ == "__main__":
    app.run(main)