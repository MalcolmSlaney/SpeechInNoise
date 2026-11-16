"""Reproduce the Colab Model Comparison plots from summarize_asr SRT CSVs."""

import argparse
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COMPARISONS = (("in_booth_srt", "Audiologist"), ("asr_srt", "ASR"))
PROJECTS = (("quick", "Quick"), ("win", "WIN"))
SUMMARY_COLUMNS = [
    "model", "project", "comparison", "n", "outlier_count", "difference_sd_db",
]


def summarize_model(model: str, paths: Sequence[Path], threshold: float = 2.0) -> pd.DataFrame:
    """Summarize finite paired differences, without centering before counting."""
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Outlier threshold must be finite and nonnegative.")
    required = {"subject_id", "project", "professional_srt", "in_booth_srt", "asr_srt"}
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        frame = frame.loc[frame["project"].isin(dict(PROJECTS))].copy()
        if frame["subject_id"].isna().any():
            raise ValueError(f"{path}: missing subject IDs.")
        for column in ("professional_srt", "in_booth_srt", "asr_srt"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        frames.append(frame)
    if not frames:
        raise ValueError(f"{model}: provide at least one subject-SRT CSV.")
    data = pd.concat(frames, ignore_index=True)
    if data.empty:
        raise ValueError(f"{model}: no QuickSIN (quick) or WIN (win) subject rows.")
    if data.duplicated(["subject_id", "project"]).any():
        raise ValueError(f"{model}: duplicate subject/project rows across input CSVs.")

    records = []
    for project, _ in PROJECTS:
        rows = data.loc[data["project"] == project]
        for column, comparison in COMPARISONS:
            valid = np.isfinite(rows[column]) & np.isfinite(rows["professional_srt"])
            differences = rows.loc[valid, column] - rows.loc[valid, "professional_srt"]
            count = len(differences)
            if count < len(rows):
                logging.warning(
                    "%s/%s/%s: excluded %d rows with missing or nonfinite SRTs.",
                    model, project, comparison, len(rows) - count,
                )
            if count < 2:
                logging.warning(
                    "%s/%s/%s: n=%d; sample SD is not estimable%s.",
                    model, project, comparison, count,
                    "; outlier count is also unavailable" if not count else "",
                )
            records.append({
                "model": model,
                "project": project,
                "comparison": comparison,
                "n": count,
                "outlier_count": int((differences.abs() > threshold).sum()) if count else np.nan,
                "difference_sd_db": float(differences.std(ddof=1)) if count > 1 else np.nan,
            })
    return pd.DataFrame.from_records(records, columns=SUMMARY_COLUMNS)


def plot_comparisons(
    summary: pd.DataFrame, output_dir: Path, threshold: float = 2.0
) -> Tuple[Path, Path]:
    """Write the two four-series plots, retaining the supplied model order."""
    models = summary["model"].drop_duplicates().tolist()
    x = np.arange(len(models))
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = (
        output_dir / "model_comparison_outliers.png",
        output_dir / "model_comparison_stds.png",
    )
    metrics = (
        ("outlier_count", f"Number of Outliers > {threshold:g}dB"),
        ("difference_sd_db", "Standard Deviation of Differences (dB)"),
    )
    for (metric, ylabel), path in zip(metrics, paths):
        figure, axis = plt.subplots(figsize=(max(8, len(models) * 0.6), 4))
        for project, project_label in PROJECTS:
            for _, comparison in COMPARISONS:
                values = summary.loc[
                    (summary["project"] == project) & (summary["comparison"] == comparison)
                ].set_index("model")[metric].reindex(models)
                axis.plot(x, values, label=f"{project_label} {comparison}")
        axis.set_xticks(x, models, rotation=45, ha="right")
        axis.set(title="Model Comparison", xlabel="Model", ylabel=ylabel)
        axis.grid(True)
        axis.legend()
        figure.tight_layout()
        figure.savefig(path, dpi=150)
        plt.close(figure)
    return paths


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", action="append", nargs="+", required=True, metavar="NAME_OR_CSV",
        help="Model label followed by one or more subject-SRT CSVs; repeat in plot order.",
    )
    parser.add_argument("--output_dir", type=Path, default=Path("."))
    parser.add_argument("--outlier_threshold", type=float, default=2.0, help="Absolute SRT error in dB.")
    args = parser.parse_args(argv)
    if not math.isfinite(args.outlier_threshold) or args.outlier_threshold < 0:
        parser.error("--outlier_threshold must be finite and nonnegative.")

    inputs: Dict[str, List[Path]] = {}
    for entry in args.model:
        if len(entry) < 2 or not entry[0].strip():
            parser.error("Each --model needs a nonempty label and at least one CSV path.")
        name, *paths = entry
        if name in inputs:
            parser.error(f"Duplicate model label: {name}")
        inputs[name] = [Path(path) for path in paths]
    try:
        summary = pd.concat(
            [summarize_model(name, paths, args.outlier_threshold) for name, paths in inputs.items()],
            ignore_index=True,
        )
        for (project, comparison), rows in summary.groupby(["project", "comparison"]):
            if rows["n"].nunique() > 1:
                logging.warning(
                    "%s/%s: paired subject counts differ across models; inspect the summary CSV.",
                    project, comparison,
                )
        plot_paths = plot_comparisons(summary, args.output_dir, args.outlier_threshold)
        summary_path = args.output_dir / "model_comparison_summary.csv"
        summary.to_csv(summary_path, index=False)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    for path in (*plot_paths, summary_path):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
