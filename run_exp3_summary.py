"""Summarize run_exp3 correlations from summarize_raters logs.

This script reads tags from run_exp3.jobs, then for each tag looks in:
- run_exp3/<TAG>/summarize_raters_quick.log
- run_exp3/<TAG>/summarize_raters_win.log

It searches for lines containing "ASR vs. Raters" and extracts the Pearson
correlation value from text like:
    ASR vs. Raters: Pearson=0.123, bias (Y-X)=-0.045

Finally, it creates a plot with one series per project (quick and win) over
job tags.
"""

import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from absl import app
from absl import flags


FLAGS = flags.FLAGS
flags.DEFINE_string("jobs_file", "run_exp3.jobs", "Path to run_exp3 jobs file.")
flags.DEFINE_string("run_dir", "run_exp3", "Directory containing per-tag result directories.")
flags.DEFINE_string("output_plot", "run_exp3_summary.png", "Output PNG for correlation summary plot.")
flags.DEFINE_string(
    "output_ratio_plot",
    "run_exp3_residual_std_ratio.png",
    "Output PNG for residual standard deviation ratio summary plot.",
)

PROJECTS = ("quick", "win")
BAD_MODEL_TAGS = {"large_exact_-10", "large_forced_-10"}
PEARSON_RE = re.compile(r"Pearson=([-+]?\d*\.?\d+|nan)", re.IGNORECASE)
STD_RATIO_RE = re.compile(r"ASR/Rater=([-+]?\d*\.?\d+|nan)", re.IGNORECASE)


def parse_tags(jobs_file: Path) -> List[str]:
    """Parse tags from a jobs file, preserving order and uniqueness."""
    tags: List[str] = []
    seen = set()

    with jobs_file.open("r", encoding="utf-8") as file:
        for raw_line in file:
            if not raw_line.strip():
                continue
            if raw_line.lstrip().startswith("#"):
                continue
            trimmed = raw_line.lstrip()
            tag = trimmed.split(None, 1)[0]
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def extract_asr_vs_raters_correlation(log_file: Path) -> Optional[float]:
    """Extract the last ASR-vs-raters Pearson value from a summarize log."""
    if not log_file.exists():
        return None

    last_value: Optional[float] = None
    with log_file.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            if "ASR vs. Raters" not in line:
                continue
            match = PEARSON_RE.search(line)
            if not match:
                continue
            token = match.group(1).lower()
            if token == "nan":
                last_value = float("nan")
            else:
                try:
                    last_value = float(token)
                except ValueError:
                    continue
    return last_value


def extract_residual_std_ratio(log_file: Path) -> Optional[float]:
    """Extract the last ASR-to-rater residual std-dev ratio from a summarize log."""
    if not log_file.exists():
        return None

    last_value: Optional[float] = None
    with log_file.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            if "Residual standard deviation summary:" not in line:
                continue
            match = STD_RATIO_RE.search(line)
            if not match:
                continue
            token = match.group(1).lower()
            if token == "nan":
                last_value = float("nan")
            else:
                try:
                    last_value = float(token)
                except ValueError:
                    continue
    return last_value


def collect_correlations(tags: List[str], run_dir: Path) -> Dict[str, List[Optional[float]]]:
    """Collect quick/win correlations for each tag in order."""
    result: Dict[str, List[Optional[float]]] = {project: [] for project in PROJECTS}

    for tag in tags:
        tag_dir = run_dir / tag
        for project in PROJECTS:
            log_file = tag_dir / f"summarize_raters_{project}.log"
            value = extract_asr_vs_raters_correlation(log_file)
            result[project].append(value)
    return result


def collect_std_ratios(tags: List[str], run_dir: Path) -> Dict[str, List[Optional[float]]]:
    """Collect quick/win residual std-dev ratios for each tag in order."""
    result: Dict[str, List[Optional[float]]] = {project: [] for project in PROJECTS}

    for tag in tags:
        tag_dir = run_dir / tag
        for project in PROJECTS:
            log_file = tag_dir / f"summarize_raters_{project}.log"
            value = extract_residual_std_ratio(log_file)
            result[project].append(value)
    return result


def create_plot(tags: List[str], correlations: Dict[str, List[Optional[float]]], output_plot: Path) -> None:
    """Create and save a quick-vs-win correlation plot across tags."""
    import matplotlib.pyplot as plt

    x = list(range(len(tags)))
    figure, axis = plt.subplots(figsize=(max(8, len(tags) * 0.6), 4.8))

    colors = {"quick": "steelblue", "win": "darkorange"}

    for project in PROJECTS:
        y_values = correlations[project]
        y_plot = [
            np.nan if (value is None or tags[i] in BAD_MODEL_TAGS) else value
            for i, value in enumerate(y_values)
        ]
        axis.plot(x, y_plot, marker="o", linewidth=1.8, label=project, color=colors[project])

    axis.axhline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.7)
    axis.set_xticks(x)
    axis.set_xticklabels(tags, rotation=45, ha="right")
    axis.set_ylim(0.5, 1.0)
    axis.set_xlabel("Model Name")
    axis.set_ylabel("Pearson correlation (ASR vs. Raters)")
    axis.set_title("ASR-vs-Raters Correlation by Tag and Project")
    axis.grid(True, axis="y", linestyle="--", alpha=0.5)
    axis.legend(title="Project")

    figure.tight_layout()
    figure.savefig(output_plot, dpi=150)


def create_ratio_plot(tags: List[str], std_ratios: Dict[str, List[Optional[float]]], output_plot: Path) -> None:
    """Create and save an ASR-to-rater residual std-dev ratio plot across tags."""
    import matplotlib.pyplot as plt

    x = list(range(len(tags)))
    figure, axis = plt.subplots(figsize=(max(8, len(tags) * 0.6), 4.8))

    colors = {"quick": "steelblue", "win": "darkorange"}

    for project in PROJECTS:
        y_values = std_ratios[project]
        y_plot = [
            np.nan if (value is None or tags[i] in BAD_MODEL_TAGS) else value
            for i, value in enumerate(y_values)
        ]
        axis.plot(x, y_plot, marker="o", linewidth=1.8, label=project, color=colors[project])

    axis.axhline(1.0, color="black", linestyle="--", linewidth=0.8, alpha=0.7)
    axis.set_xticks(x)
    axis.set_xticklabels(tags, rotation=45, ha="right")
    axis.set_xlabel("Model Name")
    axis.set_ylabel("Residual std-dev ratio (ASR / Rater)")
    axis.set_title("Residual Std-Dev Ratio by Tag and Project")
    axis.grid(True, axis="y", linestyle="--", alpha=0.5)
    axis.legend(title="Project")

    figure.tight_layout()
    figure.savefig(output_plot, dpi=150)


def print_summary(tags: List[str], correlations: Dict[str, List[Optional[float]]]) -> None:
    """Print a text table of extracted correlations."""
    print("Tag\tquick\twin")
    for i, tag in enumerate(tags):
        row = [tag]
        for project in PROJECTS:
            value = correlations[project][i]
            if value is None or math.isnan(value):
                row.append("NA")
            else:
                row.append(f"{value:.3f}")
        print("\t".join(row))


def print_ratio_summary(tags: List[str], std_ratios: Dict[str, List[Optional[float]]]) -> None:
    """Print a text table of extracted residual std-dev ratios."""
    print("Tag\tquick_std_ratio\twin_std_ratio")
    for i, tag in enumerate(tags):
        row = [tag]
        for project in PROJECTS:
            value = std_ratios[project][i]
            if value is None or math.isnan(value):
                row.append("NA")
            else:
                row.append(f"{value:.3f}")
        print("\t".join(row))


def main(argv: List[str]) -> None:
    del argv

    jobs_file = Path(FLAGS.jobs_file)
    run_dir = Path(FLAGS.run_dir)
    output_plot = Path(FLAGS.output_plot)
    output_ratio_plot = Path(FLAGS.output_ratio_plot)

    if not jobs_file.exists():
        raise FileNotFoundError(f"Jobs file not found: {jobs_file}")

    tags = parse_tags(jobs_file)
    if not tags:
        raise ValueError(f"No tags found in jobs file: {jobs_file}")

    correlations = collect_correlations(tags, run_dir)
    std_ratios = collect_std_ratios(tags, run_dir)
    print_summary(tags, correlations)
    print_ratio_summary(tags, std_ratios)
    create_plot(tags, correlations, output_plot)
    create_ratio_plot(tags, std_ratios, output_ratio_plot)
    print(f"Wrote plot to {output_plot}")
    print(f"Wrote plot to {output_ratio_plot}")


if __name__ == "__main__":
    app.run(main)
