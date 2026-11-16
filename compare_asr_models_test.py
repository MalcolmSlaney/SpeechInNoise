"""Tests for Model Comparison statistics and plots."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

import compare_asr_models as comparison


class CompareAsrModelsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "recognition_all_srts.csv"
        self.data = pd.DataFrame({
            "subject_id": [1, 2, 3, 4, 5, 6],
            "project": ["quick", "quick", "quick", "win", "win", "win"],
            "professional_srt": [5, 5, 5, 10, 10, 10],
            "in_booth_srt": [3, 7, 8, 8, 10, 12],
            "asr_srt": [2, 5, 8, 7, 11, 12],
        })
        self.data.to_csv(self.path, index=False)

    def test_exact_threshold_and_sample_sd(self):
        summary = comparison.summarize_model("large", [self.path])
        self.assertEqual(summary["n"].tolist(), [3, 3, 3, 3])
        self.assertEqual(summary["outlier_count"].tolist(), [1, 2, 0, 1])
        np.testing.assert_allclose(
            summary["difference_sd_db"], [np.std([-2, 2, 3], ddof=1), 3, 2, np.std([-3, 1, 2], ddof=1)]
        )
        # A constant 3 dB bias must count as outlying even though its SD is zero.
        self.data["asr_srt"] = self.data["professional_srt"] + 3
        self.data.to_csv(self.path, index=False)
        summary = comparison.summarize_model("biased", [self.path])
        self.assertEqual(summary.loc[1, "outlier_count"], 3)
        self.assertEqual(summary.loc[1, "difference_sd_db"], 0)

    def test_separate_project_csvs_match_combined_input(self):
        paths = []
        for project in ("quick", "win"):
            path = self.root / f"{project}.csv"
            self.data.loc[self.data.project == project].to_csv(path, index=False)
            paths.append(path)
        pd.testing.assert_frame_equal(
            comparison.summarize_model("model", paths),
            comparison.summarize_model("model", [self.path]),
        )

    def test_missing_and_nonfinite_pairs_are_explicit_gaps(self):
        self.data["asr_srt"] = [np.nan, np.inf, -np.inf, np.nan, np.nan, 12]
        self.data.to_csv(self.path, index=False)
        with self.assertLogs(level="WARNING"):
            summary = comparison.summarize_model("model", [self.path])
        self.assertEqual(summary.loc[1, "n"], 0)
        self.assertTrue(np.isnan(summary.loc[1, "outlier_count"]))
        self.assertEqual(summary.loc[3, "n"], 1)
        self.assertEqual(summary.loc[3, "outlier_count"], 0)
        self.assertTrue(np.isnan(summary.loc[3, "difference_sd_db"]))

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            comparison.summarize_model("model", [self.path, self.path])
        for threshold in (-1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "threshold"):
                comparison.summarize_model("model", [self.path], threshold)
        self.data.drop(columns="professional_srt").to_csv(self.path, index=False)
        with self.assertRaisesRegex(ValueError, "missing columns"):
            comparison.summarize_model("model", [self.path])
        self.data.assign(project="cnc").to_csv(self.path, index=False)
        with self.assertRaisesRegex(ValueError, "no QuickSIN"):
            comparison.summarize_model("model", [self.path])

    def test_cli_writes_both_plots_and_summary_in_model_order(self):
        output = self.root / "plots"
        with redirect_stdout(io.StringIO()):
            comparison.main([
                "--model", "large_prompt", str(self.path),
                "--model", "tiny.en", str(self.path),
                "--output_dir", str(output),
            ])
        for filename in ("model_comparison_outliers.png", "model_comparison_stds.png"):
            self.assertEqual((output / filename).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        summary = pd.read_csv(output / "model_comparison_summary.csv")
        self.assertEqual(summary.model.drop_duplicates().tolist(), ["large_prompt", "tiny.en"])
        self.assertEqual(summary.shape, (8, 6))
        self.assertEqual(summary.iloc[0].outlier_count, 1)

    def test_plot_lines_and_labels_match_colab(self):
        summary = pd.concat([
            comparison.summarize_model("large_prompt", [self.path]),
            comparison.summarize_model("tiny", [self.path]),
        ])
        original_close = comparison.plt.close
        with mock.patch.object(comparison.plt, "close"):
            comparison.plot_comparisons(summary, self.root)
        figures = [comparison.plt.figure(number) for number in comparison.plt.get_fignums()]
        try:
            outlier_axis, sd_axis = [figure.axes[0] for figure in figures]
            for axis in (outlier_axis, sd_axis):
                self.assertEqual(axis.get_title(), "Model Comparison")
                self.assertEqual(
                    [line.get_label() for line in axis.lines],
                    ["Quick Audiologist", "Quick ASR", "WIN Audiologist", "WIN ASR"],
                )
                self.assertEqual([tick.get_text() for tick in axis.get_xticklabels()], ["large_prompt", "tiny"])
            np.testing.assert_array_equal(outlier_axis.lines[0].get_ydata(), [1, 1])
            np.testing.assert_array_equal(sd_axis.lines[1].get_ydata(), [3, 3])
        finally:
            for figure in figures:
                original_close(figure)

    def test_cli_rejects_duplicate_model_labels(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            comparison.main(["--model", "same", str(self.path), "--model", "same", str(self.path)])
        self.assertEqual(error.exception.code, 2)

    def test_model_order_reorders_values_and_breaks_both_plots(self):
        summary = pd.concat([
            comparison.summarize_model("first", [self.path]),
            comparison.summarize_model("second", [self.path]),
        ], ignore_index=True)
        summary.loc[summary.model == "second", "outlier_count"] += 10
        summary.loc[summary.model == "second", "difference_sd_db"] += 10
        figures = []
        original_savefig = comparison.plt.Figure.savefig

        def capture_figure(figure, *args, **kwargs):
            figures.append(figure)
            return original_savefig(figure, *args, **kwargs)

        with mock.patch.object(comparison.plt.Figure, "savefig", capture_figure):
            comparison.plot_comparisons(
                summary, self.root, model_order=["", "second", "", "", "first", ""]
            )
        self.assertEqual(len(figures), 2)
        for figure, metric in zip(figures, ("outlier_count", "difference_sd_db")):
            axis = figure.axes[0]
            self.assertEqual(
                [tick.get_text() for tick in axis.get_xticklabels()],
                ["second", "first"],
            )
            np.testing.assert_array_equal(axis.get_xticks(), [0, 1])
            for line, (project, comparison_name) in zip(
                axis.lines,
                [("quick", "Audiologist"), ("quick", "ASR"), ("win", "Audiologist"), ("win", "ASR")],
            ):
                values = summary.loc[
                    (summary.project == project) & (summary.comparison == comparison_name)
                ].set_index("model")[metric]
                np.testing.assert_allclose(
                    line.get_ydata(),
                    [np.nan, values["second"], np.nan, np.nan, values["first"], np.nan],
                )
                np.testing.assert_allclose(
                    line.get_xdata(), [np.nan, 0, np.nan, np.nan, 1, np.nan]
                )
                self.assertEqual(line.get_marker(), "o")
                # NaN slots produce distinct paths, not a connection across the gap.
                segments = list(line.get_path().iter_segments(remove_nans=True))
                self.assertEqual([code for _, code in segments], [1, 1])

    def test_model_order_rejects_unknown_missing_and_duplicate_models(self):
        summary = comparison.summarize_model("first", [self.path])
        for order in (["first", "unknown"], [""], ["first", "", "first"]):
            with self.subTest(order=order), self.assertRaisesRegex(ValueError, "--model_order"):
                comparison.plot_comparisons(summary, self.root, model_order=order)

    def test_cli_parses_model_order_and_preserves_summary_csv(self):
        output = self.root / "ordered"
        with redirect_stdout(io.StringIO()), mock.patch.object(
            comparison, "plot_comparisons", wraps=comparison.plot_comparisons
        ) as plot:
            comparison.main([
                "--model", "first", str(self.path),
                "--model", "second", str(self.path),
                "--model_order= second, ,first ",
                "--output_dir", str(output),
            ])
        self.assertEqual(plot.call_args.kwargs["model_order"], ["second", "", "first"])
        summary = pd.read_csv(output / "model_comparison_summary.csv")
        self.assertEqual(summary.model.drop_duplicates().tolist(), ["first", "second"])
        self.assertEqual(summary.shape, (8, 6))

    def test_default_model_order_skips_absent_models_and_preserves_separators(self):
        self.assertEqual(
            comparison.DEFAULT_MODEL_ORDER,
            "tiny.en,tiny,base.en,base,small.en,small,medium.en,medium,large,,"
            "large_prime,large_prompt,,large_forced_-10,large_forced_0,large_forced_10,"
            "large_forced_20,large_forced_100,,large_exact_-10,large_exact_0,"
            "large_exact_10,large_exact_20,large_exact_100",
        )
        with redirect_stdout(io.StringIO()), mock.patch.object(
            comparison, "plot_comparisons", wraps=comparison.plot_comparisons
        ) as plot:
            comparison.main([
                "--model", "large_prompt", str(self.path),
                "--model", "tiny.en", str(self.path),
                "--output_dir", str(self.root),
            ])
        self.assertEqual(
            plot.call_args.kwargs["model_order"], ["tiny.en", "", "large_prompt", "", ""]
        )

    def test_empty_model_order_uses_input_order_for_custom_models(self):
        with redirect_stdout(io.StringIO()), mock.patch.object(
            comparison, "plot_comparisons", wraps=comparison.plot_comparisons
        ) as plot:
            comparison.main([
                "--model", "custom", str(self.path),
                "--model_order=", "--output_dir", str(self.root),
            ])
        self.assertIsNone(plot.call_args.kwargs["model_order"])


if __name__ == "__main__":
    unittest.main()
