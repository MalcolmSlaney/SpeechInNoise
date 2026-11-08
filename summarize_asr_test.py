"""Tests for the ASR and human-recognition summary pipeline."""

from ast import For
import json
import math
import os
import sqlite3

from absl.testing import absltest
import pandas as pd

import summarize_asr as sa


class SummarizeAsrTest(absltest.TestCase):

    def test_output_names_include_resolved_test_name(self):
        one_project = pd.DataFrame({"project": ["quick", "quick"]})
        multiple_projects = pd.DataFrame({"project": ["quick", "win"]})

        self.assertEqual(sa.resolve_test_name("quick", multiple_projects), "quick")
        self.assertEqual(sa.resolve_test_name("", one_project), "quick")
        self.assertEqual(sa.resolve_test_name("", multiple_projects), "all")
        self.assertEqual(
            sa.resolve_output_path("recognition_{test_name}_srts.csv", "quick"),
            "recognition_quick_srts.csv",
        )
        self.assertEqual(sa.resolve_output_path("custom/results.csv", "quick"), "custom/results.csv")

    def test_score_uses_inline_alternatives_and_global_homonyms(self):
        homonyms = {"cat": {"kat"}, "kat": {"cat"}, "dog": {"puppy"}, "puppy": {"dog"}}
        matches = sa.score_asr_words(
            "cat/kitty dog",
            "quick",
            "en",
            ["kitty", "puppy"],
            homonyms,
        )
        self.assertEqual(matches, [True, True])

    def test_fetch_records_keeps_professional_raters_and_scores_each_source(self):
        db_path = os.path.join(self.create_tempdir().full_path, "summary.db")
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE audio_trials (
                id INTEGER PRIMARY KEY, project TEXT, lang TEXT, snr REAL,
                filename TEXT, answer TEXT
            );
            CREATE TABLE audio_results (
                id INTEGER PRIMARY KEY, subject INTEGER, trial INTEGER
            );
            CREATE TABLE audio_asr (ref INTEGER, data TEXT);
            CREATE TABLE audio_annotations (ref INTEGER, data TEXT);
            CREATE TABLE review_annotations (ref INTEGER, labeler INTEGER, data TEXT);
            INSERT INTO users VALUES (1, 'A1S1');
            INSERT INTO users VALUES (10, 'pro1@example.org');
            INSERT INTO users VALUES (11, 'pro2@example.org');
            INSERT INTO users VALUES (12, 'student@example.org');
            INSERT INTO audio_trials VALUES (20, 'quick', 'en', 5, 'test.wav', 'cat dog');
            INSERT INTO audio_results VALUES (30, 1, 20);
            INSERT INTO audio_asr VALUES (30, '{"text":"cat puppy","model_name":"tiny.en"}');
            INSERT INTO audio_annotations VALUES (30, '[true, true]');
            INSERT INTO review_annotations VALUES (30, 10, '[true, false]');
            INSERT INTO review_annotations VALUES (30, 11, '[false, true]');
            INSERT INTO review_annotations VALUES (30, 12, '[true, true]');
            """
        )
        connection.commit()
        connection.close()

        records = sa.fetch_detail_records(
            db_path,
            {"pro1@example.org", "pro2@example.org"},
            {"dog": {"puppy"}, "puppy": {"dog"}},
        )
        detail = sa.build_detail_dataframe(records, {"pro1@example.org", "pro2@example.org"})

        self.assertEqual(len(detail), 1)
        row = detail.iloc[0]
        self.assertEqual(row["subject_id"], 1)
        self.assertEqual(row["test_utterance_id"], 20)
        self.assertEqual(row["in_booth_id"], 30)
        self.assertEqual(json.loads(row["asr_words"]), ["cat", "puppy"])
        self.assertEqual(json.loads(row["in_booth_truth_values"]), [True, True])
        self.assertEqual(json.loads(row["asr_truth_values"]), [True, True])
        self.assertAlmostEqual(row["professional_fraction_correct"], 0.5)
        self.assertNotIn("student@example.org", row["professional_rater_truth_values"])

        snr_summary = sa.summarize_by_snr(detail)
        self.assertEqual(snr_summary.loc[0, "utterance_count"], 1)
        self.assertAlmostEqual(snr_summary.loc[0, "professional_fraction_correct"], 0.5)
        plot_path = os.path.join(self.create_tempdir().full_path, "comparison.png")
        sa.create_comparison_plot(detail, plot_path)
        self.assertTrue(os.path.getsize(plot_path) > 0)

    def test_subject_snr_summary_keeps_snr_lists_and_fits_srt(self):
        detail = pd.DataFrame(
            [
                {
                    "subject_id": 1,
                    "subject_username": "A1S1",
                    "project": "quick",
                    "snr": snr,
                    "in_booth_id": index,
                    "in_booth_fraction_correct": score,
                    "professional_fraction_correct": score,
                    "asr_fraction_correct": score,
                    "rater_pro1_fraction_correct": score,
                    "rater_pro2_fraction_correct": min(score + 0.1, 1.0),
                }
                for index, (snr, score) in enumerate([(-5, 0.1), (0, 0.5), (5, 0.9)], 1)
            ]
        )
        subject_snr, srts = sa.summarize_subject_snr(detail)

        self.assertEqual(subject_snr["snr"].tolist(), [-5, 0, 5])
        self.assertEqual(len(srts), 1)
        row = srts.iloc[0]
        self.assertEqual(json.loads(row["snrs"]), [-5.0, 0.0, 5.0])
        self.assertEqual(json.loads(row["asr_fractions_correct_by_snr"]), [0.1, 0.5, 0.9])
        self.assertTrue(math.isfinite(row["asr_srt"]))
        rater_srts = json.loads(row["professional_rater_srts"])
        valid_rater_srts = list(rater_srts.values())
        self.assertEqual(row["professional_srt"], sum(valid_rater_srts) / len(valid_rater_srts))
        self.assertAlmostEqual(
            row["professional_srt_std"],
            float(pd.Series(valid_rater_srts).std(ddof=1)),
        )
        self.assertTrue(math.isfinite(row["in_booth_srt"]))

        plot_path = os.path.join(self.create_tempdir().full_path, "srt_comparison.png")
        sa.create_srt_comparison_plot(srts, plot_path)
        self.assertTrue(os.path.getsize(plot_path) > 0)

    def test_fit_srt_recovers_logistic_midpoint(self):
        snrs = [-10, -5, 0, 5, 10, 15]
        expected_midpoint = 2.0
        scores = [1 / (1 + math.exp(-0.4 * (snr - expected_midpoint))) for snr in snrs]

        self.assertAlmostEqual(sa.fit_srt(snrs, scores), expected_midpoint, places=2)
        self.assertTrue(math.isnan(sa.fit_srt([0, 5], [0.2, 0.8]))) # Not enough points to fit reliably
        self.assertTrue(math.isnan(sa.fit_srt([0, 5, 10], [0.5, 0.5, 0.5])))
        self.assertEqual(sa.fit_srt([10, 0, 5], [0.6, 0.8, 1.0]), 0.0)
        self.assertEqual(sa.fit_srt([10, 0, 5], [0.1, 0.2, 0.4]), 10.0)

    def test_bland_altman_statistics(self):
        reference = [1.0, 2.0, 3.0, 4.0]
        comparison = [1.2, 2.3, 3.4, 4.5]
        stats = sa.bland_altman_statistics(reference, comparison)
        differences = [0.2, 0.3, 0.4, 0.5]
        # Bias is the mean of comparison-reference; the SD is the sample SD
        # of those four differences, and the limits are bias +/- 1.96 SD.
        mean_difference = sum(differences) / len(differences)
        sd_difference = float(pd.Series(differences).std(ddof=1))
        self.assertEqual(stats["n"], 4)
        self.assertAlmostEqual(stats["mean_difference"], mean_difference)
        self.assertAlmostEqual(stats["sd_difference"], sd_difference)
        self.assertLess(stats["bias_ci_lower"], mean_difference)
        self.assertGreater(stats["bias_ci_upper"], mean_difference)
        self.assertLess(stats["bias_p_value"], 0.05)
        self.assertAlmostEqual(stats["loa_lower"], mean_difference - 1.96 * sd_difference)
        self.assertAlmostEqual(stats["loa_upper"], mean_difference + 1.96 * sd_difference)

    def test_icc_3_1_statistics(self):
        # Identical measures have no residual error, so ICC(3,1) is exactly 1.
        self.assertAlmostEqual(sa.icc_3_1([1.0, 2.0, 3.0, 4.0],
                                          [1.0, 2.0, 3.0, 4.0]),
                                          1.0)

        # The paired matrix is [[1, 1], [2, 3], [3, 2], [4, 4]]. Its subject
        # means are [1, 2.5, 2.5, 4] and its grand mean is 2.5. Thus
        # MS_subject = 2 * sum((subject_mean - 2.5)^2) / 3 = 3.
        # 
        # The factor of 2 is the number of measurements per subject (k=2): 
        # reference and comparison. In a two-way ANOVA, the between-subject 
        # sum of squares is
        #   SS_subject = k * sum((subject_mean - grand_mean)^2)
        # and MS_subject = SS_subject / (n−1). Here, k=2 because each subject
        # contributes two values. It is not the number of professional raters.
        #
        # MS_error is the residual mean square: how much each paired measurement
        # differs after accounting for subject averages and overall measure
        # averages. Here, the residual sum of squares is 1, divided by 3 
        # residual degrees of freedom, so MS_error = 1/3.
        #
        # The residuals are the two-way ANOVA residuals: what remains after 
        # accounting for each subject’s overall level and each measure’s 
        # overall level. For each cell:
        #   e_ij = x_ij - x̄_i⋅ - x̄_⋅j + x̄
        #
        # ICC(3,1) uses these to estimate consistency:
        #   ICC(3,1) = (MS_subject - MS_error) / (MS_subject + MS_error) 
        #            = (3 - 1/3) / (3 + 1/3) = 0.8.
        # Therefore F = 3 / (1/3) = 9.
        nontrivial_icc = sa.icc_3_1_statistics(
            [1.0, 2.0, 3.0, 4.0],
            [1.0, 3.0, 2.0, 4.0],
        )
        self.assertAlmostEqual(nontrivial_icc["icc_3_1"], 0.8)
        self.assertAlmostEqual(nontrivial_icc["icc_f_statistic"], 9.0)
        self.assertGreater(nontrivial_icc["icc_p_value"], 0.0)

    def test_summarize_srt_agreement_and_report(self):
        reference = [1.0, 2.0, 3.0, 4.0]
        comparison = [1.2, 2.3, 3.4, 4.5]
        agreement = sa.summarize_srt_agreement(
            pd.DataFrame(
                {
                    "project": ["quick"] * 4,
                    "professional_srt": reference,
                    "in_booth_srt": comparison,
                    "asr_srt": [1.2, 2.1, 2.9, 4.4],
                }
            )
        )
        self.assertEqual(agreement["comparison"].tolist(), ["in_booth", "asr"])
        self.assertEqual(agreement["n"].tolist(), [4, 4])
        self.assertTrue(agreement["icc_3_1"].map(math.isfinite).all())
        self.assertTrue(agreement["bias_p_value"].map(math.isfinite).all())
        self.assertTrue(agreement["icc_p_value"].map(math.isfinite).all())
        report = sa.format_srt_agreement_report(agreement)
        self.assertIn("Bland-Altman bias", report)
        self.assertIn("significant bias", report)
        self.assertIn("ICC(3,1)", report)
        self.assertIn("clinically acceptable agreement", report)

        report_path = os.path.join(self.create_tempdir().full_path, "agreement.txt")
        self.assertEqual(sa.write_srt_agreement_report(agreement, report_path), report)
        with open(report_path, encoding="utf-8") as report_file:
            self.assertEqual(report_file.read().strip(), report)

    def test_noninferiority_uses_leave_one_rater_out_human_error(self):
        # The paired endpoint is ASR absolute error minus mean human
        # leave-one-out error. Values near 1 dB are below the 2 dB margin;
        # values of 4 dB are above it and must not pass noninferiority.
        rows = []
        for index, (professional_srt, asr_offset) in enumerate(
            [(0.0, 1.0), (1.0, 1.1), (2.0, 0.9), (3.0, 1.2)],
            start=1,
        ):
            rows.append(
                {
                    "subject_id": index,
                    "project": "noninferior",
                    "professional_srt": professional_srt,
                    "professional_rater_srts": json.dumps(
                        {"rater_a": professional_srt - 1.0, "rater_b": professional_srt + 1.0}
                    ),
                    "asr_srt": professional_srt + asr_offset,
                }
            )
            rows.append(
                {
                    "subject_id": index,
                    "project": "not_noninferior",
                    "professional_srt": professional_srt,
                    "professional_rater_srts": json.dumps(
                        {"rater_a": professional_srt - 1.0, "rater_b": professional_srt + 1.0}
                    ),
                    "asr_srt": professional_srt + 5.0,
                }
            )

        results = sa.summarize_noninferiority(pd.DataFrame(rows), margin_db=2.0).set_index("project")
        self.assertTrue(bool(results.loc["noninferior", "noninferior"]))
        # The test passes only when the one-sided 95% upper confidence bound,
        # not merely the observed mean difference, is below the margin.
        self.assertLess(results.loc["noninferior", "one_sided_95ci_upper_db"], 2.0)
        self.assertLess(results.loc["noninferior", "one_sided_p_value"], 0.05)
        self.assertFalse(bool(results.loc["not_noninferior", "noninferior"]))
        self.assertGreaterEqual(results.loc["not_noninferior", "one_sided_95ci_upper_db"], 2.0)

        report = sa.format_srt_agreement_report(
            pd.DataFrame(),
            noninferiority_df=results.reset_index(),
            margin_db=2.0,
        )
        self.assertIn("prespecified margin is 2.000 dB", report)
        self.assertIn("ASR is noninferior under this margin", report)
        self.assertIn("noninferiority was not established", report)

if __name__ == "__main__":
    absltest.main()