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

Or, to analyze a single model variation's pickles from a run_exp3.sh output
directory (--summary_directory is joined onto each local path in
--input_pickles):
python3 summarize_all.py --summary_directory=run_exp3/medium
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

FLAGS = flags.FLAGS
flags.DEFINE_string(
    "input_pickles",
    "quick:residual_raw_data_quick.pkl,win:residual_raw_data_win.pkl",
    "Comma separated list of label:path pairs, one per project. Local paths "
    "are joined onto --summary_directory, if set; http(s) URLs are used "
    "as-is.",
)
flags.DEFINE_string(
    "summary_directory",
    "",
    "Directory holding one model variation's pickles (as produced by "
    "run_exp3.sh), joined onto each local path in --input_pickles.",
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
flags.DEFINE_float(
    "outlier_threshold",
    2.0,
    "Absolute SRT difference above which a user counts as an outlier in the "
    "SRT_DIFF_OUTLIER_COUNTS summary line.",
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


def find_summary_directory_pickles(summary_directory: str, input_pickles: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Join ``--summary_directory`` onto each local path in ``input_pickles``.

    Args:
        summary_directory: Directory holding one model variation's pickles.
        input_pickles: Generic ``(label, path)`` pairs, as returned by
            :func:`parse_input_pickles`.

    Returns:
        List of ``(label, path)`` tuples with local paths joined onto
        ``summary_directory``; http(s) URLs are left unchanged.
    """
    return [
        (label, path if path.startswith(("http://", "https://"))
         else os.path.join(summary_directory, path))
        for label, path in input_pickles
    ]


def calculate_srt_logistic(x_data, y_data):
    """
    Computes a logistic fit to x and y data and calculates the Speech Reception Threshold (SRT).

    The SRT is defined as the x-value where the logistic function crosses 0.5.

    Args:
        x_data (array-like): The independent variable data (e.g., SNR values).
        y_data (array-like): The dependent variable data (e.g., fraction correct), expected to be between 0 and 1.

    Returns:
        float: The calculated SRT (x-value where the fitted curve is 0.5),
               or np.nan if the fitting fails.
        tuple: A tuple containing the optimized parameters (k, x0) if fit is successful,
               otherwise (np.nan, np.nan).
    """
    # Ensure data is numpy arrays
    x_data = np.asarray(x_data)
    y_data = np.asarray(y_data)

    if np.all(y_data >= 0.5):
      return np.min(x_data), (np.nan, np.nan)
    if np.all(y_data < 0.5):
      return np.max(x_data), (np.nan, np.nan)

    # Define the logistic function
    def logistic(x, k, x0):
        return 1 / (1 + np.exp(-k * (x - x0)))

    try:
        # --- Robust Initial Guess (p0) for parameters ---

        # Estimate x0 (SRT) by finding where y_data crosses 0.5
        x0_guess = np.mean(x_data) # Default if interpolation isn't possible
        if len(x_data) > 1:
            idx_below_0_5 = np.where(y_data < 0.5)[0]
            idx_above_0_5 = np.where(y_data >= 0.5)[0]

            if len(idx_below_0_5) > 0 and len(idx_above_0_5) > 0:
                x_low = x_data[idx_below_0_5[-1]]
                y_low = y_data[idx_below_0_5[-1]]
                x_high = x_data[idx_above_0_5[0]]
                y_high = y_data[idx_above_0_5[0]]

                if y_high != y_low:
                    x0_guess = x_low + (0.5 - y_low) * (x_high - x_low) / (y_high - y_low)
                else: # Handle case where y_low == y_high == 0.5 or other flat segments
                    x0_guess = x_low
            elif len(idx_below_0_5) > 0: # All y_data < 0.5, guess x0 above max x_data
                x0_guess = np.max(x_data) + (np.max(x_data) - np.min(x_data)) / 2
            elif len(idx_above_0_5) > 0: # All y_data >= 0.5, guess x0 below min x_data
                x0_guess = np.min(x_data) - (np.max(x_data) - np.min(x_data)) / 2

        # Estimate k (steepness)
        k_guess = 1.0 # Default reasonable steepness
        if len(x_data) > 1:
            y_range = np.max(y_data) - np.min(y_data)
            x_range = np.max(x_data) - np.min(x_data)
            if x_range > 0 and y_range > 0:
                # A rough estimate: max slope of logistic is k/4. So k approx 4 * (avg_slope)
                k_guess = 4 * (y_range / x_range)
                k_guess = max(0.01, k_guess) # Ensure k_guess is not too small (avoid division by zero or flat curve issues)

        p0 = [k_guess, x0_guess]

        # Bounds for parameters: k > 0, x0 within a reasonable range related to x_data
        bounds = ([0.001, np.min(x_data) - (np.max(x_data)-np.min(x_data)) * 2],
                  [50, np.max(x_data) + (np.max(x_data)-np.min(x_data)) * 2]) # Increased upper bound for k from 10 to 50

        params, covariance = curve_fit(logistic, x_data, y_data, p0=p0, bounds=bounds, maxfev=5000) # Increased maxfev

        k_opt, x0_opt = params

        # As derived, when y = 0.5, x = x0. So x0_opt is the SRT.
        srt = x0_opt

        return srt, (k_opt, x0_opt)
    except RuntimeError as e:
        print(f"Error fitting logistic function: {e}") # Temporarily suppress for cleaner output
        return np.nan, (np.nan, np.nan)
    except ValueError as e:
        print(f"Error with curve_fit input values: {e}") # Temporarily suppress for cleaner output
        return np.nan, (np.nan, np.nan)

def _fit_srt_for_series(x_data, y_data_series):
    """
    Helper function to fit a logistic curve to a given y_data series
    and return the SRT and optimized parameters. Handles data validity checks.

    Args:
        x_data (np.array): The independent variable data (e.g., SNR values).
        y_data_series (pd.Series): The dependent variable data (e.g., fraction correct).

    Returns:
        tuple: (srt_value, k_parameter, x0_parameter) or (np.nan, np.nan, np.nan) if fit fails.
    """
    if y_data_series.empty:
        return np.nan, np.nan, np.nan

    y_data = y_data_series.values
    if len(x_data) > 1 and not np.all(np.isnan(y_data)) and not np.all(y_data == y_data[0]):
        srt, params = calculate_srt_logistic(x_data, y_data)
        k_opt, x0_opt = params
        return srt, k_opt, x0_opt
    return np.nan, np.nan, np.nan

def calculate_all_user_srts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates Speech Reception Thresholds (SRTs) for each user (username) in the DataFrame
    for Audiologist, ASR, and professional raters using logistic fit.

    Args:
        df (pd.DataFrame): The input DataFrame containing 'snr', 'username',
                           'audiologist_fraction_correct', 'asr_fraction_correct',
                           and 'rater_' columns for professional raters.

    Returns:
        pd.DataFrame: A DataFrame with 'username' as index and columns for the
                      SRT of Audiologist, ASR, each professional rater, and their medians.
                      Returns np.nan if SRT calculation fails for a given username/category.
    """
    all_srts = []

    # Define professional raters based on previous context
    professionals = ['anna_aupperlee@rush.edu', 'taylor.a.dalzell@vanderbilt.edu', 'cquarum@stanfordhealthcare.org']
    professional_rater_cols = [f'rater_{p}' for p in professionals]

    # Get all unique usernames
    users = df['username'].unique()

    for user in users:
        user_data = df[df['username'] == user].copy()
        user_data = user_data.dropna(subset=['snr'])

        if user_data.empty:
            print(f"Warning: No valid SNR data for user {user}. Skipping.")
            continue

        # Calculate min and max SNR for the current user's data
        min_snr = user_data['snr'].min()
        max_snr = user_data['snr'].max()

        # Identify columns for which to calculate the mean (all 'fraction_correct' and 'rater_' columns)
        columns_to_mean = [col for col in user_data.columns if 'fraction_correct' in col or col.startswith('rater_')]

        # Ensure 'snr' is present if it was dropped from columns_to_mean during filtering
        if 'snr' not in columns_to_mean:
            columns_to_mean.insert(0, 'snr')

        # Select only the relevant numeric columns for aggregation
        user_data_for_aggregation = user_data[columns_to_mean]

        # Group by SNR and calculate mean fraction correct for relevant columns
        # This ensures unique x_data points for curve_fit
        grouped_by_snr = user_data_for_aggregation.groupby('snr').mean()
        x_data = grouped_by_snr.index.values

        user_srts = {'username': user}

        # List to collect all individual SRTs (Audiologist + Raters) for combined median calculation
        all_individual_srts_for_median = []

        # --- Calculate SRT for Audiologist ---
        srt_aud, k_aud, x0_aud = _fit_srt_for_series(x_data, grouped_by_snr.get('audiologist_fraction_correct', pd.Series([])))
        if np.isnan(srt_aud):
            print(f"DEBUG: _fit_srt_for_series returned NaN for user {user}, type: Audiologist. k_opt: {k_aud}, x0_opt: {x0_aud}")
        # Apply clamping
        user_srts['SRT_Audiologist'] = np.clip(srt_aud, min_snr, max_snr) if not np.isnan(srt_aud) else np.nan
        if not np.isnan(user_srts['SRT_Audiologist']):
            all_individual_srts_for_median.append(user_srts['SRT_Audiologist'])

        # --- Calculate SRT for ASR ---
        srt_asr, k_asr, x0_asr = _fit_srt_for_series(x_data, grouped_by_snr.get('asr_fraction_correct', pd.Series([])))
        if np.isnan(srt_asr):
            print(f"DEBUG: _fit_srt_for_series returned NaN for user {user}, type: ASR. k_opt: {k_asr}, x0_opt: {x0_asr}")
        # Apply clamping
        user_srts['SRT_ASR'] = np.clip(srt_asr, min_snr, max_snr) if not np.isnan(srt_asr) else np.nan


        # --- Calculate SRT for each Professional Rater ---
        rater_srts_list = []
        for rater_col in professional_rater_cols:
            if rater_col in grouped_by_snr.columns:
                srt_rater, k_rater, x0_rater = _fit_srt_for_series(x_data, grouped_by_snr[rater_col])
                if np.isnan(srt_rater):
                    print(f"DEBUG: _fit_srt_for_series returned NaN for user {user}, type: {rater_col}. k_opt: {k_rater}, x0_opt: {x0_rater}")
                # Apply clamping
                clamped_srt_rater = np.clip(srt_rater, min_snr, max_snr) if not np.isnan(srt_rater) else np.nan
                user_srts[f'SRT_{rater_col.replace("rater_", "")}'] = clamped_srt_rater
                if not np.isnan(clamped_srt_rater):
                    rater_srts_list.append(clamped_srt_rater)
                    all_individual_srts_for_median.append(clamped_srt_rater) # Add to combined list
            else:
                user_srts[f'SRT_{rater_col.replace("rater_", "")}'] = np.nan

        # --- Calculate the mean and median of professional rater SRTs ---
        if rater_srts_list:
            user_srts['SRT_Raters_Mean'] = np.mean(rater_srts_list)
            user_srts['SRT_Professional_Raters_Median'] = np.median(rater_srts_list)
        else:
            user_srts['SRT_Raters_Mean'] = np.nan
            user_srts['SRT_Professional_Raters_Median'] = np.nan

        # --- Calculate the median of Audiologist and Professional Raters combined ---
        if all_individual_srts_for_median:
            median_srt = np.median(all_individual_srts_for_median)
            # Clip the median SRT to be within the min/max SNR of the user's data
            user_srts['SRT_Audiologist_and_Raters_Median'] = np.clip(median_srt, min_snr, max_snr)
        else:
            user_srts['SRT_Audiologist_and_Raters_Median'] = np.nan

        all_srts.append(user_srts)

    srts_df = pd.DataFrame(all_srts)
    srts_df = srts_df.set_index('username')
    return srts_df


def plot_user_srt_fits(
    df: pd.DataFrame,
    username: str,
    srts_df: pd.DataFrame,
    professional_raters: Set[str],
    label: str,
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
        label: Project/variation label (e.g. ``quick`` or ``win``), shown in
            the figure title.
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

    figure.suptitle(f"SRT Logistic Fits for User: {username} ({label})", y=1.02)
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
    max_labels_per_bin: int = 20,
) -> None:
    """Plot a histogram of ``col1 - col2`` labeling each bar with usernames.

    Args:
        srts_df: Per-user SRT DataFrame, indexed by ``username``.
        col1: First SRT column (e.g. ``SRT_ASR``).
        col2: Second SRT column, typically ``--ground_truth_column``.
        title: Panel title.
        num_bins: Number of histogram bins.
        axis: Matplotlib ``Axes`` to draw on; a new figure is created if ``None``.
        max_labels_per_bin: Maximum usernames to list per bin before
            collapsing the rest into a "+N more" suffix (avoids the label
            text overflowing the plot when many users share a bin).
    """
    difference = (srts_df[col1] - srts_df[col2]).dropna()

    if axis is None:
        _, axis = plt.subplots(figsize=(10, 8))

    if difference.empty:
        axis.set_title(title)
        axis.text(0.5, 0.5, "No valid data", ha="center", va="center", transform=axis.transAxes, fontsize=10)
        return

    counts, bins, patches = axis.hist(difference, bins=num_bins, edgecolor="black", alpha=0.7)
    # Leave headroom above the tallest bar for the stacked username labels.
    axis.set_ylim(0, max(counts) * 1.15 + 1)
    for i, patch in enumerate(patches):
        bin_start, bin_end = bins[i], bins[i + 1]
        if i == len(patches) - 1:
            users_in_bin = difference[(difference >= bin_start) & (difference <= bin_end)].index.tolist()
        else:
            users_in_bin = difference[(difference >= bin_start) & (difference < bin_end)].index.tolist()
        if users_in_bin:
            if len(users_in_bin) > max_labels_per_bin:
                shown = users_in_bin[:max_labels_per_bin]
                shown.append(f"+{len(users_in_bin) - max_labels_per_bin} more")
            else:
                shown = users_in_bin
            x_center = patch.get_x() + patch.get_width() / 2
            y_position = patch.get_y() + 0.5
            axis.text(x_center, y_position, "\n".join(shown), ha="center", va="bottom", fontsize=8, color="black")

    axis.set_xlabel("Difference in SRTs")
    axis.set_ylabel("Frequency")
    axis.set_title(f"{title} (n={len(difference)})")
    axis.grid(axis="y", alpha=0.75)


def create_summary_histogram(all_srts: Dict[str, pd.DataFrame]) -> None:
    """Save a 2x2 grid of SRT-difference histograms.

    Rows are the input labels (e.g. ``win`` and ``quick``, in the order given
    by ``--input_pickles``/``--summary_directory``); columns compare
    Audiologist-vs-ground-truth and ASR-vs-ground-truth SRTs. Each panel is a
    single histogram summarizing the differences across all of that label's
    users.

    Args:
        all_srts: Mapping from label to its per-user SRT DataFrame, as
            returned by :func:`calculate_all_user_srts`.

    Returns:
        None. Writes the figure to ``--histogram_plot``.
    """
    labels = list(all_srts.keys())
    comparisons = [("SRT_Audiologist", "Audiologist"), ("SRT_ASR", "ASR")]
    figure, axes = plt.subplots(
        len(labels), len(comparisons), figsize=(7.5 * len(comparisons), 6 * len(labels)), squeeze=False,
    )

    outlier_counts = {}
    for row, label in enumerate(labels):
        srts_df = all_srts[label]
        for col, (srt_column, comparison_name) in enumerate(comparisons):
            difference = (srts_df[srt_column] - srts_df[FLAGS.ground_truth_column]).dropna()
            outlier_counts[(label, comparison_name)] = int((difference.abs() > FLAGS.outlier_threshold).sum())
            print(
                f"Histogram panel ({label}, {comparison_name}): "
                f"{len(srts_df)} rows in srts_df, "
                f"{srts_df[srt_column].notna().sum()} non-null {srt_column}, "
                f"{srts_df[FLAGS.ground_truth_column].notna().sum()} non-null {FLAGS.ground_truth_column}, "
                f"{len(difference)} non-null differences, "
                f"{difference.nunique()} unique difference values, "
                f"min={difference.min():.3f}, max={difference.max():.3f}, "
                f"values={sorted(round(value, 2) for value in difference)}."
            )
            plot_srt_diff_histogram_with_users(
                srts_df, srt_column, FLAGS.ground_truth_column,
                f"{comparison_name} vs. Ground Truth ({label})",
                num_bins=FLAGS.histogram_bins, axis=axes[row][col],
            )

    figure.tight_layout()
    figure.savefig(FLAGS.histogram_plot, dpi=150)
    plt.close(figure)
    print(f"Wrote SRT difference histogram to {FLAGS.histogram_plot}")

    summary = ", ".join(
        f"{label}_{comparison_name}={outlier_counts[(label, comparison_name)]}"
        for label in labels
        for _, comparison_name in comparisons
    )
    print(f"SRT_DIFF_OUTLIER_COUNTS (threshold={FLAGS.outlier_threshold}): {summary}")


def main(argv: List[str]) -> None:
    """Fit SRTs for one variation's projects, save per-user plots and histogram.

    Args:
        argv: Unused command-line arguments (consumed by ABSL).
    """
    del argv
    professional_raters = sr.read_professional_raters(FLAGS.professional_raters)

    input_pickles = parse_input_pickles(FLAGS.input_pickles)
    if FLAGS.summary_directory:
        input_pickles = find_summary_directory_pickles(FLAGS.summary_directory, input_pickles)
    if not input_pickles:
        raise ValueError("--input_pickles must specify at least one label:path pair.")

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
                plot_user_srt_fits(dataframe, username, srts_df, professional_raters, label, save_path=save_path)
            print(f"Wrote {len(srts_df)} per-user SRT fit plots to {FLAGS.output_dir}")

    create_summary_histogram(all_srts)


if __name__ == "__main__":
    app.run(main)
