"""Fit and summarize Speech Reception Thresholds (SRTs) across projects.

Ported from the SRT analysis Colab notebook. Reads one or more
``residual_raw_data*.pkl`` DataFrames (as produced by
``summarize_raters.py --dump_raw_data``), fits a logistic psychometric
function (fraction correct vs. SNR) per user for the audiologist, the ASR,
and each professional rater, and computes a per-user "ground truth" SRT as
the median across the audiologist and professional rater SRTs.

For each user, a multi-panel figure showing the raw data and logistic fits is
saved to ``--output_dir``. A final histogram figure compares
Audiologist-vs-ground-truth and ASR-vs-ground-truth SRT differences (one row
per input project), and is saved to ``--histogram_plot``.

To run:
python3 summarize_all.py \
  --input_pickles="quick:residual_raw_data_quick.pkl,win:residual_raw_data_win.pkl" \
  --output_dir=srt_plots \
  --histogram_plot=srt_diff_histogram.png \
  --histogram_bins=10 \
  --professional_raters=metadata/professional_raters.txt \
  --ground_truth_column=SRT_Audiologist_and_Raters_Median

Or, to load every known model variation (from the notebook's VARIATIONS list)
under a run_exp3.sh output directory, where each variation's pickles are at
<summary_directory>/<variation>/residual_raw_data_<project>.pkl:
python3 summarize_all.py --summary_directory=run_exp3
"""

import os
import pickle
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

from absl import app
from absl import flags

import summarize_raters as sr

# Model variations from the original Colab notebook; empty strings are
# separators between variation groups and are skipped.
VARIATIONS = [
    "tiny.en", "tiny", "base.en", "base", "small.en", "small", "medium.en", "medium",
    "large", "", "large_prime", "large_prompt", "", "large_forced_-10", "large_forced_0",
    "large_forced_10", "large_forced_20", "large_forced_100", "", "large_exact_-10",
    "large_exact_0", "large_exact_10", "large_exact_20", "large_exact_100",
]

FLAGS = flags.FLAGS
flags.DEFINE_string(
    "input_pickles",
    "",
    "Comma separated list of label:path pairs, one per project. Each path is "
    "a pickled DataFrame produced by summarize_raters.py --dump_raw_data. "
    "Paths may also be http(s) URLs. Combined with any pairs discovered via "
    "--summary_directory.",
)
flags.DEFINE_string(
    "summary_directory",
    "",
    "Base directory holding one subdirectory per model variation (as produced "
    "by run_exp3.sh); pickles are expected at "
    "<summary_directory>/<variation>/residual_raw_data_<project>.pkl for each "
    "variation in VARIATIONS. Missing files are skipped.",
)
flags.DEFINE_string(
    "output_dir",
    "srt_plots",
    "Directory to write the per-user SRT fit figures to.",
)
flags.DEFINE_bool(
    "no_user_plots",
    False,
    "Do not save the per-user SRT fit figure for each user.",
)
flags.DEFINE_string(
    "histogram_plot",
    "srt_diff_histogram.png",
    "PNG file for the summary histogram comparing SRT differences.",
)
flags.DEFINE_integer(
    "histogram_bins",
    10,
    "Number of bins for the SRT difference histograms.",
)
flags.DEFINE_string(
    "ground_truth_column",
    "SRT_Audiologist_and_Raters_Median",
    "Column in the per-user SRT DataFrame to use as ground truth (the median "
    "of the audiologist SRT and each professional rater's SRT).",
)


def _load_dataframe(path: str) -> pd.DataFrame:
    """Load a pickled per-utterance DataFrame from a local path or URL.

    Args:
        path: Local filesystem path, or an http(s) URL, to a pickle file as
            written by ``summarize_raters.py --dump_raw_data``.

    Returns:
        The unpickled DataFrame.
    """
    if path.startswith("http://") or path.startswith("https://"):
        with urllib.request.urlopen(path) as response:
            return pickle.loads(response.read())
    with open(path, "rb") as file:
        return pickle.load(file)


def parse_input_pickles(spec: str) -> List[Tuple[str, str]]:
    """Parse the ``--input_pickles`` flag into ``(label, path)`` pairs.

    Args:
        spec: Comma separated ``label:path`` pairs. The path may itself
            contain colons (e.g. ``https://...``); only the first colon
            separates the label from the path.

    Returns:
        List of ``(label, path)`` tuples in the order given.
    """
    pairs = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        label, _, path = item.partition(":")
        pairs.append((label.strip(), path.strip()))
    return pairs


def find_summary_directory_pickles(summary_directory: str) -> List[Tuple[str, str]]:
    """Build label:path pairs for each known variation under ``--summary_directory``.

    For each non-empty entry in :data:`VARIATIONS`, looks for
    ``<summary_directory>/<variation>/residual_raw_data_<project>.pkl`` for
    both the ``quick`` and ``win`` projects. Variations with no matching files
    are skipped with a printed warning.

    Args:
        summary_directory: Base directory holding one subdirectory per variation.

    Returns:
        List of ``(label, path)`` tuples, labeled ``<variation>_<project>``.
    """
    pairs = []
    for variation in VARIATIONS:
        if not variation:
            continue
        for project in ("quick", "win"):
            path = os.path.join(summary_directory, variation, f"residual_raw_data_{project}.pkl")
            if not os.path.exists(path):
                print(f"Skipping missing pickle: {path}")
                continue
            pairs.append((f"{variation}_{project}", path))
    return pairs


def calculate_srt_logistic(x_data, y_data) -> Tuple[float, Tuple[float, float]]:
    """Fit a logistic curve to fraction-correct-vs-SNR data and find the SRT.

    The SRT is defined as the x-value where the fitted logistic curve crosses
    0.5.

    Args:
        x_data: Independent variable values (SNR).
        y_data: Dependent variable values (fraction correct), in ``[0, 1]``.

    Returns:
        Tuple of ``(srt, (k, x0))`` where ``k`` is the fitted steepness and
        ``x0`` is the fitted midpoint (equal to the SRT). Returns
        ``(nan, (nan, nan))`` if the fit fails.
    """
    x_data = np.asarray(x_data)
    y_data = np.asarray(y_data)

    def logistic(x, k, x0):
        return 1 / (1 + np.exp(-k * (x - x0)))

    try:
        p0 = [1, np.mean(x_data)]
        bounds = (
            [0.001, np.min(x_data) - (np.max(x_data) - np.min(x_data))],
            [np.inf, np.max(x_data) + (np.max(x_data) - np.min(x_data))],
        )
        params, _ = curve_fit(logistic, x_data, y_data, p0=p0, bounds=bounds)
        k_opt, x0_opt = params
        return x0_opt, (k_opt, x0_opt)
    except (RuntimeError, ValueError) as error:
        print(f"Error fitting logistic function: {error}")
        return np.nan, (np.nan, np.nan)


def _fit_srt_for_series(x_data, y_data_series: pd.Series) -> Tuple[float, float, float]:
    """Fit a logistic curve to one column of grouped-by-SNR data.

    Args:
        x_data: SNR values, one per group.
        y_data_series: Fraction-correct values aligned with ``x_data``.

    Returns:
        Tuple of ``(srt, k, x0)``, or ``(nan, nan, nan)`` if there is not
        enough variation in the data to fit a curve.
    """
    if y_data_series.empty:
        return np.nan, np.nan, np.nan
    y_data = y_data_series.values
    if len(x_data) > 1 and not np.all(np.isnan(y_data)) and not np.all(y_data == y_data[0]):
        srt, (k_opt, x0_opt) = calculate_srt_logistic(x_data, y_data)
        return srt, k_opt, x0_opt
    return np.nan, np.nan, np.nan


def calculate_all_user_srts(df: pd.DataFrame, professional_raters: Set[str]) -> pd.DataFrame:
    """Fit per-user SRTs for the audiologist, ASR, and each professional rater.

    The per-user "ground truth" SRT (``SRT_Audiologist_and_Raters_Median``) is
    the median of the audiologist SRT and each professional rater's SRT.

    Args:
        df: Per-utterance DataFrame with ``snr``, ``username``,
            ``audiologist_fraction_correct``, ``asr_fraction_correct``, and
            ``rater_<username>`` columns, as produced by
            ``summarize_raters.build_raw_dataframe``.
        professional_raters: Usernames whose ``rater_<username>`` columns
            count toward the professional-rater SRT median.

    Returns:
        DataFrame indexed by ``username`` with columns ``SRT_Audiologist``,
        ``SRT_ASR``, one ``SRT_<rater>`` column per professional rater,
        ``SRT_Raters_Mean``, ``SRT_Professional_Raters_Median``, and
        ``SRT_Audiologist_and_Raters_Median``.
    """
    professional_rater_cols = [f"rater_{rater}" for rater in professional_raters]
    all_srts = []

    for user in df["username"].unique():
        user_data = df[df["username"] == user].dropna(subset=["snr"])
        if user_data.empty:
            print(f"Warning: No valid SNR data for user {user}. Skipping.")
            continue

        min_snr, max_snr = user_data["snr"].min(), user_data["snr"].max()
        columns_to_mean = [
            col for col in user_data.columns
            if "fraction_correct" in col or col.startswith("rater_")
        ]
        if "snr" not in columns_to_mean:
            columns_to_mean.insert(0, "snr")

        grouped_by_snr = user_data[columns_to_mean].groupby("snr").mean()
        x_data = grouped_by_snr.index.values

        user_srts = {"username": user}
        combined_srts = []

        srt_aud, _, _ = _fit_srt_for_series(x_data, grouped_by_snr.get("audiologist_fraction_correct", pd.Series([])))
        user_srts["SRT_Audiologist"] = np.clip(srt_aud, min_snr, max_snr) if not np.isnan(srt_aud) else np.nan
        if not np.isnan(user_srts["SRT_Audiologist"]):
            combined_srts.append(user_srts["SRT_Audiologist"])

        srt_asr, _, _ = _fit_srt_for_series(x_data, grouped_by_snr.get("asr_fraction_correct", pd.Series([])))
        user_srts["SRT_ASR"] = np.clip(srt_asr, min_snr, max_snr) if not np.isnan(srt_asr) else np.nan

        rater_srts = []
        for rater_col in professional_rater_cols:
            if rater_col not in grouped_by_snr.columns:
                user_srts[f"SRT_{rater_col.replace('rater_', '')}"] = np.nan
                continue
            srt_rater, _, _ = _fit_srt_for_series(x_data, grouped_by_snr[rater_col])
            clamped = np.clip(srt_rater, min_snr, max_snr) if not np.isnan(srt_rater) else np.nan
            user_srts[f"SRT_{rater_col.replace('rater_', '')}"] = clamped
            if not np.isnan(clamped):
                rater_srts.append(clamped)
                combined_srts.append(clamped)

        user_srts["SRT_Raters_Mean"] = np.mean(rater_srts) if rater_srts else np.nan
        user_srts["SRT_Professional_Raters_Median"] = np.median(rater_srts) if rater_srts else np.nan
        if combined_srts:
            median_srt = np.median(combined_srts)
            user_srts["SRT_Audiologist_and_Raters_Median"] = np.clip(median_srt, min_snr, max_snr)
        else:
            user_srts["SRT_Audiologist_and_Raters_Median"] = np.nan

        all_srts.append(user_srts)

    return pd.DataFrame(all_srts).set_index("username")


def plot_user_srt_fits(
    df: pd.DataFrame,
    username: str,
    srts_df: pd.DataFrame,
    professional_raters: Set[str],
    save_path: Optional[str] = None,
) -> None:
    """Plot raw SNR data and logistic fits for one user, optionally saving it.

    Draws one panel per available score column (audiologist, ASR, each
    professional rater, and the professional-rater mean), each with the raw
    per-SNR means, the fitted logistic curve, the fitted SRT, and the user's
    combined median SRT (``--ground_truth_column``) marked with an X.

    Args:
        df: Per-utterance DataFrame, as passed to :func:`calculate_all_user_srts`.
        username: The user to plot.
        srts_df: Per-user SRT DataFrame, as returned by :func:`calculate_all_user_srts`.
        professional_raters: Usernames whose ``rater_<username>`` columns are
            included as separate panels.
        save_path: If given, save the figure to this path (and close it)
            instead of leaving it open for interactive display.
    """
    user_data = df[df["username"] == username].dropna(subset=["snr"]).copy()
    if user_data.empty:
        print(f"No valid data found for user {username}. Cannot plot.")
        return

    combined_median_srt = srts_df.loc[username, FLAGS.ground_truth_column]
    if np.isnan(combined_median_srt):
        combined_median_srt = None

    professional_rater_cols = [f"rater_{rater}" for rater in professional_raters]
    existing_rater_cols = [
        col for col in professional_rater_cols
        if col in user_data.columns and pd.api.types.is_numeric_dtype(user_data[col])
    ]

    columns = ["audiologist_fraction_correct", "asr_fraction_correct"] + existing_rater_cols
    if existing_rater_cols:
        user_data["overall_rater_mean_fraction_correct"] = user_data[existing_rater_cols].mean(axis=1)
        columns.append("overall_rater_mean_fraction_correct")
    columns = [col for col in columns if col in user_data.columns and pd.api.types.is_numeric_dtype(user_data[col])]

    if not columns:
        print(f"No relevant numeric columns found for user {username}. Cannot plot.")
        return

    grouped_by_snr = user_data.groupby("snr")[columns].mean()
    x_data = grouped_by_snr.index.values
    if len(x_data) < 2:
        print(f"Not enough unique SNR points for user {username} to perform logistic fit. Cannot plot.")
        return

    ncols = min(3, len(columns))
    nrows = int(np.ceil(len(columns) / ncols))
    figure, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(5 * ncols, 4 * nrows), sharex=True, squeeze=False)
    axes = axes.flatten()

    for i, col in enumerate(columns):
        axis = axes[i]
        y_data_series = grouped_by_snr[col]
        axis.scatter(x_data, y_data_series.values, label="Raw Data", color="blue", zorder=5)

        srt_val, k_opt, x0_opt = _fit_srt_for_series(x_data, y_data_series)
        if not np.isnan(k_opt) and not np.isnan(x0_opt):
            x_fit = np.linspace(min(x_data), max(x_data), 100)
            y_fit = 1 / (1 + np.exp(-k_opt * (x_fit - x0_opt)))
            axis.plot(x_fit, y_fit, label=f"Logistic Fit (SRT={srt_val:.2f})", color="red", linestyle="--")
            axis.axvline(x=srt_val, color="green", linestyle=":", label=f"SRT = {srt_val:.2f}")
            x_min_plot, x_max_plot = axis.get_xlim()
            axis.axhline(y=0.5, color="green", linestyle=":", xmax=(srt_val - x_min_plot) / (x_max_plot - x_min_plot))
            axis.plot(srt_val, 0.5, "go", markersize=8)

        if combined_median_srt is not None:
            axis.scatter(
                combined_median_srt, 0.5, marker="x", s=200, color="magenta", linewidth=3,
                label=f"Ground Truth SRT ({combined_median_srt:.2f})", zorder=10,
            )

        clean_name = (
            col.replace("audiologist_fraction_correct", "Audiologist")
            .replace("asr_fraction_correct", "ASR")
            .replace("overall_rater_mean_fraction_correct", "Overall Raters Mean")
            .replace("rater_", "")
        )
        axis.set_title(f"{username}: {clean_name}")
        axis.set_ylabel("Fraction Correct")
        axis.grid(True)
        axis.legend()
        axis.set_xlim(min(x_data), max(x_data))

    for j in range(len(columns), len(axes)):
        figure.delaxes(axes[j])
    for k in range(ncols):
        bottom_row_index = (nrows - 1) * ncols + k
        if bottom_row_index < len(axes) and bottom_row_index >= len(columns) - ncols:
            axes[bottom_row_index].set_xlabel("SNR")

    figure.suptitle(f"SRT Logistic Fits for User: {username}", y=1.02)
    figure.tight_layout(rect=[0, 0.03, 1, 0.98])

    if save_path:
        figure.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
    else:
        plt.show()


def plot_srt_diff_histogram_with_users(
    srts_df: pd.DataFrame,
    col1: str,
    col2: str,
    title: str,
    num_bins: int = 10,
    axis=None,
) -> None:
    """Plot a histogram of ``col1 - col2`` labeling each bar with usernames.

    Args:
        srts_df: Per-user SRT DataFrame, indexed by ``username``.
        col1: First SRT column (e.g. ``SRT_ASR``).
        col2: Second SRT column, typically ``--ground_truth_column``.
        title: Panel title.
        num_bins: Number of histogram bins.
        axis: Matplotlib ``Axes`` to draw on; a new figure is created if ``None``.
    """
    difference = (srts_df[col1] - srts_df[col2]).dropna()

    if axis is None:
        _, axis = plt.subplots(figsize=(10, 8))

    if difference.empty:
        axis.set_title(title)
        axis.text(0.5, 0.5, "No valid data", ha="center", va="center", transform=axis.transAxes, fontsize=10)
        return

    counts, bins, patches = axis.hist(difference, bins=num_bins, edgecolor="black", alpha=0.7)
    for i, patch in enumerate(patches):
        bin_start, bin_end = bins[i], bins[i + 1]
        if i == len(patches) - 1:
            users_in_bin = difference[(difference >= bin_start) & (difference <= bin_end)].index.tolist()
        else:
            users_in_bin = difference[(difference >= bin_start) & (difference < bin_end)].index.tolist()
        if users_in_bin:
            x_center = patch.get_x() + patch.get_width() / 2
            y_position = patch.get_y() + 0.5
            axis.text(x_center, y_position, "\n".join(users_in_bin), ha="center", va="bottom", fontsize=8, color="black")

    axis.set_xlabel("Difference in SRTs")
    axis.set_ylabel("Frequency")
    axis.set_title(title)
    axis.grid(axis="y", alpha=0.75)


def create_summary_histogram(all_srts: Dict[str, pd.DataFrame]) -> None:
    """Save a grid of SRT-difference histograms, one row per project.

    Each row compares Audiologist-vs-ground-truth and ASR-vs-ground-truth SRT
    differences for one project's users.

    Args:
        all_srts: Mapping from project label to its per-user SRT DataFrame, as
            returned by :func:`calculate_all_user_srts`.
    """
    labels = list(all_srts.keys())
    figure, axes = plt.subplots(len(labels), 2, figsize=(15, 6 * len(labels)), squeeze=False)

    for row, label in enumerate(labels):
        srts_df = all_srts[label]
        plot_srt_diff_histogram_with_users(
            srts_df, "SRT_Audiologist", FLAGS.ground_truth_column,
            f"SRTs: Audiologist vs. Ground Truth ({label})",
            num_bins=FLAGS.histogram_bins, axis=axes[row][0],
        )
        plot_srt_diff_histogram_with_users(
            srts_df, "SRT_ASR", FLAGS.ground_truth_column,
            f"SRTs: ASR vs. Ground Truth ({label})",
            num_bins=FLAGS.histogram_bins, axis=axes[row][1],
        )

    figure.tight_layout()
    figure.savefig(FLAGS.histogram_plot, dpi=150)
    plt.close(figure)
    print(f"Wrote SRT difference histogram to {FLAGS.histogram_plot}")


def main(argv: List[str]) -> None:
    """Fit SRTs for each project, save per-user plots, and the summary histogram.

    Args:
        argv: Unused command-line arguments (consumed by ABSL).
    """
    del argv
    professional_raters = sr.read_professional_raters(FLAGS.professional_raters)

    input_pickles = parse_input_pickles(FLAGS.input_pickles)
    if FLAGS.summary_directory:
        input_pickles += find_summary_directory_pickles(FLAGS.summary_directory)
    if not input_pickles:
        raise ValueError(
            "Must specify at least one label:path pair via --input_pickles "
            "and/or a --summary_directory."
        )

    if not FLAGS.no_user_plots:
        os.makedirs(FLAGS.output_dir, exist_ok=True)

    all_srts: Dict[str, pd.DataFrame] = {}
    for label, path in input_pickles:
        print(f"Loading {label} data from {path}")
        dataframe = _load_dataframe(path)
        srts_df = calculate_all_user_srts(dataframe, professional_raters)
        all_srts[label] = srts_df
        print(f"Computed SRTs for {len(srts_df)} users in {label}.")

        if not FLAGS.no_user_plots:
            for username in srts_df.index:
                save_path = os.path.join(FLAGS.output_dir, f"{label}_{username}_srt_fit.png")
                plot_user_srt_fits(dataframe, username, srts_df, professional_raters, save_path=save_path)
            print(f"Wrote {len(srts_df)} per-user SRT fit plots to {FLAGS.output_dir}")

    create_summary_histogram(all_srts)


if __name__ == "__main__":
    app.run(main)
