"""Summarize rater annotations and ASR performance by subject and SNR.

This is the standalone version of the rater analysis originally developed in
the Colab notebook. It reads trial data from SQLite, scores ASR transcripts
against the trial answers, and writes one summary row per subject/project/SNR.
"""

import csv
import json
import math
import re
import sqlite3
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Set, Tuple

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


def fetch_trials(dbfile: str, language: str, project: str) -> List[sqlite3.Row]:
    """Fetch trials that have both computed ASR and reviewer annotations."""
    with sqlite3.connect(dbfile) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT DISTINCT
                ar.subject AS user,
                at.project,
                at.snr,
                at.answer,
                aa.data AS audio_annotation_data,
                ra.data AS review_annotation_data,
                asr.data AS audio_asr_data
            FROM audio_results ar
            JOIN audio_trials at ON ar.trial = at.id
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


def create_plot(summary: List[Dict[str, Any]]) -> None:
    """Create the notebook's three-panel scatter plot."""
    import matplotlib.pyplot as plt

    comparisons = [
        ("mean_fraction_audio_annotation_true", "mean_fraction_review_annotation_true", "Audiologist", "Reraters"),
        ("normalized_matched_word_count", "mean_fraction_audio_annotation_true", "ASR", "Audiologist"),
        ("normalized_matched_word_count", "mean_fraction_review_annotation_true", "ASR", "Reraters"),
    ]
    figure, axes = plt.subplots(1, 3, figsize=(12, 4))
    for axis, (x_key, y_key, x_label, y_label) in zip(axes, comparisons):
        axis.scatter([row[x_key] for row in summary], [row[y_key] for row in summary], alpha=0.7)
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        axis.grid(True, linestyle="--", alpha=0.6)
    figure.tight_layout()
    figure.savefig(FLAGS.plot, dpi=150)
    print(f"Wrote plot to {FLAGS.plot}")


def main(argv: List[str]) -> None:
    del argv
    homonyms = read_homonyms(FLAGS.homonyms)
    rows = fetch_trials(FLAGS.dbfile, FLAGS.language, FLAGS.project)
    summary = summarize(rows, homonyms)
    write_csv(summary)
    print_statistics(summary)
    print(f"Wrote summary to {FLAGS.output}")
    if summary and not FLAGS.no_plot:
        create_plot(summary)


if __name__ == "__main__":
    app.run(main)