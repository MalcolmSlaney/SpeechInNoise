"""Summarize in-booth, professional-rater, and ASR keyword recognition.

Reads ASR JSON produced by ``offline_asr.py`` and joins it with the trial
answers, in-booth annotations, and professional review annotations. Writes a
per-utterance CSV, project/SNR and subject/SNR summaries, subject SRT fits,
and a three-panel comparison plot.
"""

import json
import logging
import math
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from contextlib import closing
from functools import lru_cache
from itertools import product
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.stats import f as f_distribution
from scipy.stats import t as t_distribution
from scipy.stats import ttest_1samp

from absl import app
from absl import flags


FLAGS = flags.FLAGS


BASE_COLUMNS = [
    "subject_id",
    "subject_username",
    "project",
    "language",
    "test_utterance_id",
    "in_booth_id",
    "snr",
    "filename",
    "ground_truth",
    "in_booth_truth_values",
    "in_booth_fraction_correct",
    "professional_rater_truth_values",
    "professional_fraction_correct",
    "asr_words",
    "asr_truth_values",
    "asr_fraction_correct",
]

SCORE_COLUMNS = [
    "in_booth_fraction_correct",
    "professional_fraction_correct",
    "asr_fraction_correct",
]


def normalize_word(word: str) -> str:
    """Normalize a keyword while preserving Unicode letters and compounds."""
    word = unicodedata.normalize("NFKC", word).casefold()
    return re.sub(r"[^\w-]", "", word, flags=re.UNICODE).replace("_", "")


def read_homonyms(path: str) -> Dict[str, Set[str]]:
    """Read comma-separated homonym groups into a bidirectional mapping."""
    homonyms: Dict[str, Set[str]] = {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.split("#", 1)[0].strip()
                words = {normalize_word(word.strip()) for word in line.split(",")}
                words.discard("")
                for word in words:
                    homonyms.setdefault(word, set()).update(words - {word})
    except FileNotFoundError:
        logging.warning("Homonym file %s was not found; using exact matches only.", path)
    return homonyms


def read_professional_raters(path: str) -> Set[str]:
    """Read reviewer usernames, ignoring blank lines and comments."""
    raters: Set[str] = set()
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            username = line.split("#", 1)[0].strip().casefold()
            if username:
                raters.add(username)
    return raters


def parse_truth_values(value: Any) -> Optional[List[bool]]:
    """Parse JSON or legacy comma-separated boolean annotation data."""
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = [item.strip() for item in str(value).strip("[]").split(",")]
    if not isinstance(parsed, list):
        return None
    result = []
    for item in parsed:
        if isinstance(item, bool):
            result.append(item)
        elif str(item).strip().casefold() in {"true", "1"}:
            result.append(True)
        elif str(item).strip().casefold() in {"false", "0"}:
            result.append(False)
        else:
            return None
    return result


@lru_cache(maxsize=1)
def _english_normalizer():
    try:
        from whisper.normalizers import EnglishTextNormalizer

        return EnglishTextNormalizer()
    except ImportError:
        return None


def normalize_recognition_text(text: str, language: str) -> List[str]:
    """Apply the recognizer's English normalization for English tests, then tokenize.

    Non-English test data uses Unicode-aware tokenization without applying an
    English-only normalizer. This keeps accents and non-Latin scripts intact.
    """
    text = text or ""
    if (language or "").casefold().startswith("en"):
        normalizer = _english_normalizer()
        if normalizer is not None:
            text = normalizer(text)
    return [word for word in (normalize_word(token) for token in re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", text, re.UNICODE)) if word]


def extract_asr_words(asr_data: Any, language: str) -> List[str]:
    """Extract only recognized words from offline_asr's JSON result."""
    if isinstance(asr_data, str):
        try:
            asr_data = json.loads(asr_data)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(asr_data, dict):
        return []

    segment_words = []
    for segment in asr_data.get("segments", []) or []:
        for word in segment.get("words", []) or []:
            if isinstance(word, dict) and word.get("word"):
                segment_words.append(str(word["word"]))
    text = " ".join(segment_words) if segment_words else str(asr_data.get("text", ""))
    return normalize_recognition_text(text, language)


def answer_slots(answer: str, project: str) -> List[str]:
    """Split the test answer into keyword slots using the project's answer format.

    CNC and WIN trials are single-keyword tests; other projects encode one
    keyword slot per whitespace-delimited answer item. Slash alternatives
    remain within a slot and are expanded during matching.
    """
    answer = answer or ""
    if project.casefold() in {"cnc", "win"}:
        return [answer.strip()] if answer.strip() else []
    return [slot for slot in answer.split() if slot]


def _candidate_phrases(
    slot: str, language: str, homonyms: Dict[str, Set[str]]
) -> Set[Tuple[str, ...]]:
    candidates: Set[Tuple[str, ...]] = set()
    for option in slot.split("/"):
        words = normalize_recognition_text(option, language)
        if not words:
            continue
        expansions = []
        for word in words:
            alternatives = {word, *homonyms.get(word, set())}
            alternatives.add(word.replace("'", ""))
            expansions.append(alternatives)
        candidates.update(tuple(phrase) for phrase in product(*expansions))
    return candidates


def score_asr_words(
    answer: str,
    project: str,
    language: str,
    asr_words: Sequence[str],
    homonyms: Dict[str, Set[str]],
) -> List[bool]:
    """Return one ASR hit/miss value per ground-truth keyword slot."""
    slots = answer_slots(answer, project)
    recognized = {normalize_word(word) for word in asr_words}
    matches = []
    for slot in slots:
        candidates = _candidate_phrases(slot, language, homonyms)
        found = False
        for candidate in candidates:
            if all(word in recognized or word.replace("'", "") in recognized for word in candidate):
                found = True
                break
            if any("-" in word for word in candidate):
                parts = [part for word in candidate for part in word.split("-") if part]
                if parts and all(part in recognized or f"-{part}" in recognized for part in parts):
                    found = True
                    break
        matches.append(found)
    return matches


def fraction_correct(values: Optional[Sequence[bool]]) -> float:
    if not values:
        return float("nan")
    return sum(bool(value) for value in values) / len(values)


def fetch_detail_records(
    dbfile: str,
    professional_raters: Set[str],
    homonyms: Dict[str, Set[str]],
    project: str = "",
    language: str = "",
) -> List[Dict[str, Any]]:
    """Load result rows and assemble one scored record per in-booth trial."""
    query = """
        SELECT
            ar.id AS in_booth_id,
            ar.subject AS subject_id,
            subject.username AS subject_username,
            ar.trial AS test_utterance_id,
            at.project,
            at.lang AS language,
            at.snr,
            at.filename,
            at.answer AS ground_truth,
            aa.ref AS annotation_ref,
            aa.data AS in_booth_data,
            asr.data AS asr_data,
            reviewer.username AS reviewer_username,
            ra.data AS reviewer_data
        FROM audio_results ar
        JOIN users subject ON subject.id = ar.subject
        JOIN audio_trials at ON at.id = ar.trial
        JOIN audio_asr asr ON asr.ref = ar.id
        LEFT JOIN audio_annotations aa ON aa.ref = ar.id
        LEFT JOIN review_annotations ra ON ra.ref = ar.id
        LEFT JOIN users reviewer ON reviewer.id = ra.labeler
        WHERE asr.data IS NOT NULL AND asr.data != ''
          AND (? = '' OR at.project = ?)
          AND (? = '' OR at.lang = ?)
        ORDER BY ar.id, reviewer.username
    """
    with closing(sqlite3.connect(dbfile)) as connection:
        cursor = connection.execute(query, (project, project, language, language))
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()

    grouped: Dict[int, Dict[str, Any]] = {}
    for values in rows:
        row = dict(zip(columns, values))
        in_booth_id = row["in_booth_id"]
        record = grouped.get(in_booth_id)
        if record is None:
            booth_values = parse_truth_values(row["in_booth_data"])
            asr_words = extract_asr_words(row["asr_data"], row["language"] or "")
            asr_matches = score_asr_words(
                row["ground_truth"] or "",
                row["project"] or "",
                row["language"] or "",
                asr_words,
                homonyms,
            )
            record = {
                "subject_id": row["subject_id"],
                "subject_username": row["subject_username"],
                "project": row["project"],
                "language": row["language"],
                "test_utterance_id": row["test_utterance_id"],
                "in_booth_id": row["in_booth_id"],
                "snr": row["snr"],
                "filename": row["filename"],
                "ground_truth": row["ground_truth"],
                "in_booth_truth_values": json.dumps(booth_values) if booth_values is not None else "",
                "in_booth_fraction_correct": fraction_correct(booth_values),
                "asr_words": json.dumps(asr_words, ensure_ascii=False),
                "asr_truth_values": json.dumps(asr_matches),
                "asr_fraction_correct": fraction_correct(asr_matches),
                "_rater_values": {},
            }
            grouped[in_booth_id] = record

        rater = (row["reviewer_username"] or "").casefold()
        if rater in professional_raters and rater not in record["_rater_values"]:
            record["_rater_values"][rater] = parse_truth_values(row["reviewer_data"])

    records = []
    for record in grouped.values():
        rater_values = record.pop("_rater_values")
        rater_fractions = [fraction_correct(values) for values in rater_values.values() if values is not None]
        record["professional_rater_truth_values"] = json.dumps(
            {name: values for name, values in sorted(rater_values.items())},
            ensure_ascii=False,
        )
        record["professional_fraction_correct"] = (
            sum(rater_fractions) / len(rater_fractions) if rater_fractions else float("nan")
        )
        for rater in sorted(professional_raters):
            values = rater_values.get(rater)
            record[f"rater_{rater}_truth_values"] = json.dumps(values) if values is not None else ""
            record[f"rater_{rater}_fraction_correct"] = fraction_correct(values)
        records.append(record)
    return records


def build_detail_dataframe(
    records: Sequence[Dict[str, Any]], professional_raters: Iterable[str]
) -> pd.DataFrame:
    columns = list(BASE_COLUMNS)
    for rater in sorted(set(professional_raters)):
        columns.extend([f"rater_{rater}_truth_values", f"rater_{rater}_fraction_correct"])
    return pd.DataFrame.from_records(records, columns=columns)


def summarize_by_snr(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Average the three recognition scores for each project and SNR."""
    columns = ["project", "snr", "utterance_count", *SCORE_COLUMNS]
    if detail_df.empty:
        return pd.DataFrame(columns=columns)
    summary = (
        detail_df.groupby(["project", "snr"], dropna=False)
        .agg(utterance_count=("in_booth_id", "count"), **{name: (name, "mean") for name in SCORE_COLUMNS})
        .reset_index()
        .sort_values(["project", "snr"], na_position="last")
    )
    return summary[columns]


def fit_srt(snrs: Sequence[float], scores: Sequence[float]) -> float:
    """Fit a two-parameter logistic curve and return its 50% point (x0)."""
    x = np.asarray(snrs, dtype=float)
    y = np.asarray(scores, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if not len(x):
        return float("nan")
    if np.all(y > 0.5):
        return float(np.min(x))
    if np.all(y < 0.5):
        return float(np.max(x))
    if len(np.unique(x)) < 3 or len(np.unique(y)) < 2:
        return float("nan")

    def logistic(values, steepness, midpoint):
        return 1.0 / (1.0 + np.exp(np.clip(-steepness * (values - midpoint), -700, 700)))

    x_range = float(np.max(x) - np.min(x))
    midpoint_guess = float(np.mean(x))
    below = np.flatnonzero(y < 0.5)
    above = np.flatnonzero(y >= 0.5)
    if len(below) and len(above):
        low_idx, high_idx = below[-1], above[0]
        if x[high_idx] != x[low_idx] and y[high_idx] != y[low_idx]:
            midpoint_guess = float(
                x[low_idx] + (0.5 - y[low_idx]) * (x[high_idx] - x[low_idx]) / (y[high_idx] - y[low_idx])
            )
    try:
        params, _ = curve_fit(
            logistic,
            x,
            np.clip(y, 0.0, 1.0),
            p0=(1.0, midpoint_guess),
            bounds=((0.001, np.min(x) - 2 * x_range), (50.0, np.max(x) + 2 * x_range)),
            maxfev=10000,
        )
        return float(params[1])
    except (RuntimeError, ValueError, FloatingPointError):
        return float("nan")


def summarize_subject_snr(detail_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build subject/project/SNR means and one logistic SRT row per subject/project."""
    group_columns = ["subject_id", "subject_username", "project", "snr"]
    subject_columns = [*group_columns, "utterance_count", *SCORE_COLUMNS]
    if detail_df.empty:
        empty_subject = pd.DataFrame(columns=subject_columns)
        empty_srt = pd.DataFrame(columns=["subject_id", "subject_username", "project", "snrs"])
        return empty_subject, empty_srt

    subject_snr = (
        detail_df.groupby(group_columns, dropna=False)
        .agg(utterance_count=("in_booth_id", "count"), **{name: (name, "mean") for name in SCORE_COLUMNS})
        .reset_index()
        .sort_values(["subject_id", "project", "snr"], na_position="last")
    )
    srt_records = []
    for (subject_id, username, project), group in subject_snr.groupby(
        ["subject_id", "subject_username", "project"], dropna=False, sort=False
    ):
        group = group.dropna(subset=["snr"]).sort_values("snr")
        snrs = group["snr"].astype(float).tolist()
        record: Dict[str, Any] = {
            "subject_id": subject_id,
            "subject_username": username,
            "project": project,
            "snrs": json.dumps(snrs),
        }
        for column, label in zip(SCORE_COLUMNS, ("in_booth", "professional", "asr")):
            values = group[column].astype(float).tolist()
            record[f"{label}_fractions_correct_by_snr"] = json.dumps(
                [value if math.isfinite(value) else None for value in values]
            )
            if label != "professional":
                record[f"{label}_srt"] = fit_srt(snrs, values)

        rater_fraction_columns = [
            column
            for column in detail_df.columns
            if column.startswith("rater_") and column.endswith("_fraction_correct")
        ]
        rater_srts = {}
        detail_group = detail_df.loc[
            (detail_df["subject_id"] == subject_id)
            & (detail_df["project"] == project)
        ]
        for column in rater_fraction_columns:
            rater = column[len("rater_"):-len("_fraction_correct")]
            rater_curve = detail_group.groupby("snr")[column].mean().dropna().sort_index()
            rater_srts[rater] = fit_srt(
                rater_curve.index.astype(float).tolist(),
                rater_curve.astype(float).tolist(),
            )

        valid_rater_srts = [value for value in rater_srts.values() if math.isfinite(value)]
        record["professional_rater_srts"] = json.dumps(
            {name: value if math.isfinite(value) else None for name, value in sorted(rater_srts.items())}
        )
        record["professional_srt_count"] = len(valid_rater_srts)
        record["professional_srt"] = (
            float(np.mean(valid_rater_srts)) if valid_rater_srts else float("nan")
        )
        record["professional_srt_std"] = (
            float(np.std(valid_rater_srts, ddof=1)) if len(valid_rater_srts) > 1 else float("nan")
        )
        srt_records.append(record)
    return subject_snr[subject_columns], pd.DataFrame.from_records(srt_records)


def create_comparison_plot(detail_df: pd.DataFrame, output_path: str) -> None:
    """Save a row of scatter plots comparing the three recognition sources."""
    comparisons = [
        ("in_booth_fraction_correct", "professional_fraction_correct", "In-booth vs. Professional"),
        ("in_booth_fraction_correct", "asr_fraction_correct", "In-booth vs. ASR"),
        ("professional_fraction_correct", "asr_fraction_correct", "Professional vs. ASR"),
    ]
    figure, axes = plt.subplots(1, 3, figsize=(13, 4), sharex=True, sharey=True)
    for axis, (x_column, y_column, title) in zip(axes, comparisons):
        points = detail_df[[x_column, y_column]].dropna()
        axis.scatter(points[x_column], points[y_column], alpha=0.65, s=24)
        axis.plot([0, 1], [0, 1], "k--", linewidth=0.8)
        axis.set(xlim=(-0.03, 1.03), ylim=(-0.03, 1.03), title=title, xlabel=x_column.replace("_fraction_correct", ""))
        axis.grid(True, linestyle="--", alpha=0.3)
    axes[0].set_ylabel("Fraction correct")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def create_srt_comparison_plot(srts_df: pd.DataFrame, output_path: str) -> None:
    """Plot the three paired SRT comparisons, showing professional-rater SD."""
    comparisons = [
        ("in_booth_srt", "professional_srt", "In-booth vs. Professional"),
        ("in_booth_srt", "asr_srt", "In-booth vs. ASR"),
        ("professional_srt", "asr_srt", "Professional vs. ASR"),
    ]
    figure, axes = plt.subplots(1, 3, figsize=(13, 4), sharex=True, sharey=True)
    projects = sorted(srts_df["project"].dropna().unique()) if not srts_df.empty else []
    for axis, (x_column, y_column, title) in zip(axes, comparisons):
        for project in projects:
            points = srts_df.loc[
                srts_df["project"] == project,
                [x_column, y_column, "professional_srt_std"],
            ].dropna(subset=[x_column, y_column])
            has_rater_sd = points["professional_srt_std"].notna()
            error_points = points.loc[has_rater_sd]
            plain_points = points.loc[~has_rater_sd]
            if not error_points.empty:
                axis.errorbar(
                    error_points[x_column],
                    error_points[y_column],
                    xerr=error_points["professional_srt_std"] if x_column == "professional_srt" else None,
                    yerr=error_points["professional_srt_std"] if y_column == "professional_srt" else None,
                    fmt="o",
                    markersize=4,
                    alpha=0.65,
                    capsize=2,
                    label=str(project),
                )
            if not plain_points.empty:
                axis.scatter(
                    plain_points[x_column],
                    plain_points[y_column],
                    s=20,
                    alpha=0.65,
                    label=str(project),
                )
        finite_values = srts_df[[x_column, y_column]].to_numpy(dtype=float).ravel()
        finite_values = finite_values[np.isfinite(finite_values)]
        if finite_values.size:
            lower, upper = float(finite_values.min()), float(finite_values.max())
            margin = max((upper - lower) * 0.08, 0.5)
            limits = (lower - margin, upper + margin)
            axis.plot(limits, limits, "k--", linewidth=0.8)
            axis.set_xlim(limits)
            axis.set_ylim(limits)
        axis.set_title(title)
        axis.set_xlabel(x_column.replace("_srt", "").replace("_", " ").title() + " SRT (dB)")
        axis.grid(True, linestyle="--", alpha=0.3)
    axes[0].set_ylabel("SRT (dB)")
    if len(projects) > 1:
        axes[-1].legend(title="Project", fontsize=8)
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def bland_altman_statistics(reference: Sequence[float], comparison: Sequence[float]) -> Dict[str, Any]:
    """Return bias, confidence interval, and limits of agreement.

    Differences are comparison minus reference. Bias significance is tested
    with a two-sided one-sample t-test against zero.
    """
    paired = pd.DataFrame({"reference": reference, "comparison": comparison}).dropna()
    paired = paired[np.isfinite(paired["reference"]) & np.isfinite(paired["comparison"])]
    differences = (paired["comparison"] - paired["reference"]).to_numpy(dtype=float)
    count = len(differences)
    bias = float(np.mean(differences)) if count else float("nan")
    sd = float(np.std(differences, ddof=1)) if count > 1 else float("nan")
    if count > 1:
        standard_error = sd / math.sqrt(count)
        critical_t = float(t_distribution.ppf(0.975, count - 1))
        bias_ci_lower = bias - critical_t * standard_error
        bias_ci_upper = bias + critical_t * standard_error
        bias_p_value = float(ttest_1samp(differences, 0.0).pvalue)
    else:
        bias_ci_lower = bias_ci_upper = bias_p_value = float("nan")
    return {
        "n": count,
        "mean_difference": bias,
        "sd_difference": sd,
        "bias_ci_lower": bias_ci_lower,
        "bias_ci_upper": bias_ci_upper,
        "bias_p_value": bias_p_value,
        "loa_lower": bias - 1.96 * sd if math.isfinite(sd) else float("nan"),
        "loa_upper": bias + 1.96 * sd if math.isfinite(sd) else float("nan"),
    }


def icc_3_1_statistics(reference: Sequence[float], comparison: Sequence[float]) -> Dict[str, float]:
    """Calculate ICC(3,1) and its F-test against zero reliability."""
    paired = pd.DataFrame({"reference": reference, "comparison": comparison}).dropna()
    paired = paired[np.isfinite(paired["reference"]) & np.isfinite(paired["comparison"])]
    values = paired.to_numpy(dtype=float)
    subject_count, measure_count = values.shape
    if subject_count < 2 or measure_count != 2:
        return {"icc_3_1": float("nan"), "icc_f_statistic": float("nan"), "icc_p_value": float("nan")}

    grand_mean = float(values.mean())
    subject_means = values.mean(axis=1)
    residuals = values - subject_means[:, None] - values.mean(axis=0)[None, :] + grand_mean
    ms_subjects = measure_count * float(np.sum((subject_means - grand_mean) ** 2)) / (subject_count - 1)
    ms_error = float(np.sum(residuals**2)) / ((subject_count - 1) * (measure_count - 1))
    denominator = ms_subjects + (measure_count - 1) * ms_error
    icc = (ms_subjects - ms_error) / denominator if denominator else float("nan")
    if ms_error == 0:
        f_statistic = float("inf") if ms_subjects > 0 else float("nan")
    else:
        f_statistic = ms_subjects / ms_error
    p_value = (
        float(f_distribution.sf(f_statistic, subject_count - 1, (subject_count - 1) * (measure_count - 1)))
        if math.isfinite(f_statistic)
        else (0.0 if f_statistic == float("inf") else float("nan"))
    )
    return {"icc_3_1": icc, "icc_f_statistic": f_statistic, "icc_p_value": p_value}


def icc_3_1(reference: Sequence[float], comparison: Sequence[float]) -> float:
    """Return two-way mixed, consistency, single-measure ICC(3,1)."""
    return icc_3_1_statistics(reference, comparison)["icc_3_1"]


def summarize_srt_agreement(srts_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Bland–Altman and ICC(3,1) against professional-rater consensus."""
    output = []
    comparisons = [("in_booth", "in_booth_srt"), ("asr", "asr_srt")]
    for project, project_rows in srts_df.groupby("project", dropna=False):
        for label, column in comparisons:
            valid = project_rows[["professional_srt", column]].dropna()
            ba = bland_altman_statistics(valid["professional_srt"], valid[column])
            icc = icc_3_1_statistics(valid["professional_srt"], valid[column])
            output.append(
                {
                    "project": project,
                    "comparison": label,
                    "n": ba["n"],
                    "bland_altman_bias": ba["mean_difference"],
                    "bland_altman_sd": ba["sd_difference"],
                    "bias_ci_lower": ba["bias_ci_lower"],
                    "bias_ci_upper": ba["bias_ci_upper"],
                    "bias_p_value": ba["bias_p_value"],
                    "loa_lower": ba["loa_lower"],
                    "loa_upper": ba["loa_upper"],
                    **icc,
                }
            )
    return pd.DataFrame.from_records(
        output,
        columns=[
            "project", "comparison", "n", "bland_altman_bias", "bland_altman_sd",
            "bias_ci_lower", "bias_ci_upper", "bias_p_value", "loa_lower", "loa_upper",
            "icc_3_1", "icc_f_statistic", "icc_p_value",
        ],
    )


def summarize_noninferiority(
    srts_df: pd.DataFrame,
    margin_db: float = 2.0,
) -> pd.DataFrame:
    """Test whether ASR SRT error is no more than margin_db worse than a rater.

    For each subject, ASR absolute error is measured against the professional
    SRT mean. Human absolute error is averaged across professional raters,
    where each rater is compared with the mean SRT of the other raters
    (leave-one-rater-out reference). A one-sided paired t-test tests whether
    mean(ASR error - human error) is below the noninferiority margin.

    The estimand is the mean within-subject difference in absolute errors.
    The null is that this difference is at least ``margin_db``; the alternative
    is that it is smaller. Noninferiority is declared only when the one-sided
    95% upper t-confidence bound is below the margin. This inference assumes
    independent subjects and approximately normal paired differences.
    """
    output = []
    for project, project_rows in srts_df.groupby("project", dropna=False):
        paired_errors = []
        # Each subject contributes both an ASR error and a human error. This
        # pairing controls for subject-specific SRT difficulty in the comparison.
        for row in project_rows.to_dict(orient="records"):
            professional_srt = row.get("professional_srt", float("nan"))
            asr_srt = row.get("asr_srt", float("nan"))
            try:
                rater_srts = json.loads(row.get("professional_rater_srts", "{}") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            rater_values = [
                float(value)
                for value in rater_srts.values()
                if value is not None and math.isfinite(float(value))
            ]
            if not (math.isfinite(professional_srt) and math.isfinite(asr_srt)) or len(rater_values) < 2:
                continue

            # Absolute SRT error measures distance from the reference, so an
            # equally large overestimate and underestimate count equally.
            # Leave one rater out when scoring each human so that rater is not
            # included in their own reference; this avoids artificially
            # reducing the estimated human error through self-agreement.
            human_errors = [
                abs(rater_value - float(np.mean([other for i, other in enumerate(rater_values) if i != index])))
                for index, rater_value in enumerate(rater_values)
            ]
            asr_error = abs(asr_srt - professional_srt)
            human_error = float(np.mean(human_errors))
            paired_errors.append(
                {
                    "subject_id": row.get("subject_id"),
                    "asr_absolute_error_db": asr_error,
                    "human_loo_absolute_error_db": human_error,
                    "error_difference_db": asr_error - human_error,
                }
            )

        # Pair errors within subjects before testing, so each value removes
        # subject-specific difficulty from the ASR-vs-human comparison.
        differences = np.asarray([row["error_difference_db"] for row in paired_errors], dtype=float)
        count = len(differences)
        mean_difference = float(np.mean(differences)) if count else float("nan")
        sd_difference = float(np.std(differences, ddof=1)) if count > 1 else float("nan")
        if count > 1:
            standard_error = sd_difference / math.sqrt(count)
            degrees_freedom = count - 1
            # H0: mean(ASR error - human error) >= margin; the alternative is
            # that it is smaller. A lower-tail paired t-test therefore matches
            # the noninferiority question, rather than testing for equality.
            # Equivalently, declare noninferiority only if the one-sided 95%
            # upper confidence bound is below the prespecified margin. This
            # supports a mean-error claim, not a guarantee for every subject.
            statistic = (mean_difference - margin_db) / standard_error if standard_error else (
                float("-inf") if mean_difference < margin_db else float("inf") if mean_difference > margin_db else 0.0
            )
            p_value = float(t_distribution.cdf(statistic, degrees_freedom))
            upper_bound = mean_difference + float(t_distribution.ppf(0.95, degrees_freedom)) * standard_error
        else:
            statistic = p_value = upper_bound = float("nan")
        output.append(
            {
                "project": project,
                "n_subjects": count,
                "margin_db": margin_db,
                "mean_asr_absolute_error_db": (
                    float(np.mean([row["asr_absolute_error_db"] for row in paired_errors]))
                    if count else float("nan")
                ),
                "mean_human_loo_absolute_error_db": (
                    float(np.mean([row["human_loo_absolute_error_db"] for row in paired_errors]))
                    if count else float("nan")
                ),
                "mean_error_difference_db": mean_difference,
                "difference_sd_db": sd_difference,
                "t_statistic": statistic,
                "one_sided_p_value": p_value,
                "one_sided_95ci_upper_db": upper_bound,
                "noninferior": bool(math.isfinite(upper_bound) and upper_bound < margin_db),
            }
        )
    return pd.DataFrame.from_records(
        output,
        columns=[
            "project", "n_subjects", "margin_db", "mean_asr_absolute_error_db",
            "mean_human_loo_absolute_error_db", "mean_error_difference_db", "difference_sd_db",
            "t_statistic", "one_sided_p_value", "one_sided_95ci_upper_db", "noninferior",
        ],
    )


def format_srt_agreement_report(
    agreement_df: pd.DataFrame,
    alpha: float = 0.05,
    noninferiority_df: Optional[pd.DataFrame] = None,
    margin_db: float = 2.0,
) -> str:
    """Explain agreement metrics and report their nominal statistical significance."""
    lines = [
        "SRT agreement analysis",
        "Reference: mean SRT across professional raters with successful fits.",
        "Bland-Altman bias is comparison minus reference; its p-value is from a two-sided paired-difference t-test.",
        "The 95% limits of agreement estimate the range containing about 95% of individual differences.",
        "ICC(3,1) is two-way mixed-effects, consistency, single-measure reliability; its F-test tests ICC = 0.",
        "ICC descriptors use conventional cutoffs: <0.50 poor, 0.50-0.75 moderate, 0.75-0.90 good, >0.90 excellent.",
        "P-values are nominal at alpha={:.3g}; no multiple-comparison adjustment is applied.".format(alpha),
        "Statistical significance does not establish clinically acceptable agreement; that requires predefined limits.",
    ]
    for row in agreement_df.to_dict(orient="records"):
        bias_p = row.get("bias_p_value", float("nan"))
        icc_p = row.get("icc_p_value", float("nan"))
        icc_value = row.get("icc_3_1", float("nan"))
        if math.isfinite(icc_value):
            if icc_value < 0.5:
                icc_descriptor = "poor"
            elif icc_value < 0.75:
                icc_descriptor = "moderate"
            elif icc_value < 0.9:
                icc_descriptor = "good"
            else:
                icc_descriptor = "excellent"
        else:
            icc_descriptor = "not estimable"
        bias_statement = (
            f"significant bias (p={bias_p:.4g})"
            if math.isfinite(bias_p) and bias_p < alpha
            else f"no statistically significant bias detected (p={bias_p:.4g})"
            if math.isfinite(bias_p)
            else "bias significance not estimable"
        )
        icc_statement = (
            f"statistically above zero (p={icc_p:.4g})"
            if math.isfinite(icc_p) and icc_p < alpha
            else f"not statistically distinguishable from zero (p={icc_p:.4g})"
            if math.isfinite(icc_p)
            else "ICC significance not estimable"
        )
        lines.extend(
            [
                "",
                f"{row['project']} / {row['comparison']} vs professional reference (n={row['n']}):",
                f"  Mean bias: {row['bland_altman_bias']:.3f} dB; 95% CI [{row['bias_ci_lower']:.3f}, {row['bias_ci_upper']:.3f}] dB; {bias_statement}.",
                f"  95% limits of agreement: [{row['loa_lower']:.3f}, {row['loa_upper']:.3f}] dB.",
                f"  ICC(3,1): {icc_value:.3f} ({icc_descriptor}); {icc_statement}.",
            ]
        )
    if noninferiority_df is not None:
        lines.extend(
            [
                "",
                "ASR noninferiority to professional raters",
                f"The prespecified margin is {margin_db:.3f} dB of additional absolute SRT error.",
                "Human error is each professional rater's absolute deviation from the mean of the other raters.",
                "ASR error is its absolute deviation from the all-rater professional mean; analysis is paired by subject.",
                "The one-sided paired t-test null is that mean(ASR error - human error) is at least the margin.",
                f"Noninferiority is concluded when the one-sided 95% upper confidence bound is below {margin_db:.3f} dB.",
                "This conclusion depends on the clinical justification for the chosen margin and the paired-t assumptions.",
            ]
        )
        for row in noninferiority_df.to_dict(orient="records"):
            if row["n_subjects"] < 2:
                status = "not estimable (fewer than two paired subjects)"
            elif row["noninferior"]:
                status = "ASR is noninferior under this margin"
            else:
                status = "noninferiority was not established"
            p_value = row["one_sided_p_value"]
            p_text = f"{p_value:.4g}" if math.isfinite(p_value) else "not estimable"
            upper = row["one_sided_95ci_upper_db"]
            upper_text = f"{upper:.3f} dB" if math.isfinite(upper) else "not estimable"
            lines.extend(
                [
                    "",
                    f"{row['project']} (n={row['n_subjects']} paired subjects):",
                    f"  Mean ASR absolute error: {row['mean_asr_absolute_error_db']:.3f} dB; "
                    f"mean human leave-one-out error: {row['mean_human_loo_absolute_error_db']:.3f} dB.",
                    f"  ASR minus human mean error: {row['mean_error_difference_db']:.3f} dB; "
                    f"one-sided 95% upper bound: {upper_text}; p={p_text}.",
                    f"  Result: {status}.",
                ]
            )
    return "\n".join(lines)


def write_srt_agreement_report(
    agreement_df: pd.DataFrame,
    output_path: str,
    noninferiority_df: Optional[pd.DataFrame] = None,
    margin_db: float = 2.0,
) -> str:
    """Write and return the human-readable SRT agreement report."""
    report = format_srt_agreement_report(
        agreement_df,
        noninferiority_df=noninferiority_df,
        margin_db=margin_db,
    )
    parent = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(report + "\n")
    return report


def _write_csv(dataframe: pd.DataFrame, path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    dataframe.to_csv(path, index=False)
    print(f"Wrote {len(dataframe)} rows to {path}")


def resolve_test_name(project_filter: str, detail_df: pd.DataFrame) -> str:
    """Choose a filename token from the project filter or sole project present."""
    if project_filter:
        candidate = project_filter
    else:
        projects = detail_df["project"].dropna().astype(str).unique()
        candidate = projects[0] if len(projects) == 1 else "all"
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate).strip("_")
    return safe_name or "all"


def resolve_output_path(path: str, test_name: str) -> str:
    """Substitute the test token in a default or user-provided output path."""
    return path.replace("{test_name}", test_name)


def main(argv: List[str]) -> None:
    del argv
    logging.info("Reading ASR-backed trials from %s", FLAGS.dbfile)
    homonyms = read_homonyms(FLAGS.homonyms)
    professional_raters = read_professional_raters(FLAGS.professional_raters)
    records = fetch_detail_records(
        FLAGS.dbfile,
        professional_raters,
        homonyms,
        project=FLAGS.project,
        language=FLAGS.language,
    )
    detail_df = build_detail_dataframe(records, professional_raters)
    test_name = resolve_test_name(FLAGS.project, detail_df)
    snr_df = summarize_by_snr(detail_df)
    subject_snr_df, srt_df = summarize_subject_snr(detail_df)

    output_csv = resolve_output_path(FLAGS.output_csv, test_name)
    snr_summary_csv = resolve_output_path(FLAGS.snr_summary_csv, test_name)
    subject_snr_csv = resolve_output_path(FLAGS.subject_snr_csv, test_name)
    srt_csv = resolve_output_path(FLAGS.srt_csv, test_name)
    scatter_plot = resolve_output_path(FLAGS.scatter_plot, test_name)
    srt_scatter_plot = resolve_output_path(FLAGS.srt_scatter_plot, test_name)
    agreement_csv = resolve_output_path(FLAGS.agreement_csv, test_name)
    agreement_report_path = resolve_output_path(FLAGS.agreement_report, test_name)
    noninferiority_csv = resolve_output_path(FLAGS.noninferiority_csv, test_name)

    _write_csv(detail_df, output_csv)
    _write_csv(snr_df, snr_summary_csv)
    _write_csv(subject_snr_df, subject_snr_csv)
    _write_csv(srt_df, srt_csv)
    agreement_df = summarize_srt_agreement(srt_df)
    _write_csv(agreement_df, agreement_csv)
    noninferiority_df = summarize_noninferiority(srt_df, FLAGS.noninferiority_margin_db)
    _write_csv(noninferiority_df, noninferiority_csv)
    agreement_report = write_srt_agreement_report(
        agreement_df,
        agreement_report_path,
        noninferiority_df=noninferiority_df,
        margin_db=FLAGS.noninferiority_margin_db,
    )
    print(agreement_report)
    print(f"Wrote agreement explanation to {agreement_report_path}")
    if not FLAGS.no_plot and not detail_df.empty:
        create_comparison_plot(detail_df, scatter_plot)
        print(f"Wrote comparison plot to {scatter_plot}")
    if not FLAGS.no_plot and not srt_df.empty:
        create_srt_comparison_plot(srt_df, srt_scatter_plot)
        print(f"Wrote SRT comparison plot to {srt_scatter_plot}")


if __name__ == "__main__":
    flags.DEFINE_string("dbfile", "experiments.db", "SQLite database with offline ASR results.")
    flags.DEFINE_string("homonyms", "homonym_list.csv", "Global comma-separated homonym list.")
    flags.DEFINE_string(
        "professional_raters",
        "metadata/professional_raters.txt",
        "File containing professional reviewer usernames, one per line.",
    )
    flags.DEFINE_string("project", "", "Optional project name to include; empty includes all projects.")
    flags.DEFINE_string("language", "", "Optional language code to include; empty includes all languages.")
    flags.DEFINE_string("output_csv", "recognition_{test_name}_by_utterance.csv", "Per-utterance CSV output.")
    flags.DEFINE_string("snr_summary_csv", "recognition_{test_name}_by_snr.csv", "Project/SNR summary CSV output.")
    flags.DEFINE_string("subject_snr_csv", "recognition_{test_name}_by_subject_snr.csv", "Subject/project/SNR summary CSV output.")
    flags.DEFINE_string("srt_csv", "recognition_{test_name}_srts.csv", "Per-subject/project SRT and score-list CSV output.")
    flags.DEFINE_string("scatter_plot", "recognition_{test_name}_comparison.png", "Three-panel comparison plot output.")
    flags.DEFINE_string("srt_scatter_plot", "recognition_{test_name}_srt_comparison.png", "Three-panel SRT comparison plot output.")
    flags.DEFINE_string("agreement_csv", "recognition_{test_name}_srt_agreement.csv", "Bland–Altman and ICC(3,1) summary CSV output.")
    flags.DEFINE_string("agreement_report", "recognition_{test_name}_srt_agreement.txt", "Explanation and significance report for SRT agreement statistics.")
    flags.DEFINE_string("noninferiority_csv", "recognition_{test_name}_srt_noninferiority.csv", "ASR noninferiority results CSV output.")
    flags.DEFINE_float("noninferiority_margin_db", 2.0, "Maximum excess ASR SRT error allowed for noninferiority, in dB.")
    flags.DEFINE_bool("no_plot", False, "Do not save the comparison plot.")
    app.run(main)