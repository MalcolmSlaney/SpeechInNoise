"""Tests for summarize_raters.py.

These tests focus on the residual normalization modes introduced by
--residual_normalization.
"""

import os
import re
import sqlite3
import subprocess
import sys

from absl.testing import absltest


class SummarizeRatersResidualModeTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.temp_dir = self.create_tempdir().full_path
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.homonyms_path = os.path.join(self.temp_dir, "homonyms.csv")
        self.professional_raters_path = os.path.join(self.temp_dir, "professional_raters.txt")
        self.student_raters_path = os.path.join(self.temp_dir, "student_raters.txt")
        self.script_path = os.path.join(os.path.dirname(__file__), "summarize_raters.py")

        # Keep homonyms minimal; test answers are single words and do not rely on homonym expansion.
        with open(self.homonyms_path, "w", encoding="utf-8") as file:
            file.write("# none\n")

        with open(self.professional_raters_path, "w", encoding="utf-8") as file:
            file.write("rater1\n")
            file.write("rater2\n")

        with open(self.student_raters_path, "w", encoding="utf-8") as file:
            file.write("# none\n")

        self._create_db()

    def _create_db(self) -> None:
        """Create a tiny DB with two utterances in the same project/SNR bucket.

        Construction (all project=quick, snr=0):
          utterance 1: ASR score=1.0, rater scores=[1.0, 0.0], utterance mean=0.5
          utterance 2: ASR score=0.0, rater scores=[1.0, 1.0], utterance mean=1.0

        Given test data from the docstring:

          Utterance 1:
          ASR score = 1.0
          Rater scores = [1.0, 0.0]
          Utterance rater mean = 0.5

          Utterance 2:
          ASR score = 0.0
          Rater scores = [1.0, 1.0]
          Utterance rater mean = 1.0

        Normalization by utterance

          Baselines:
            u1 baseline = 0.5
            u2 baseline = 1.0
          ASR residuals:
            [1.0 - 0.5, 0.0 - 1.0] = [0.5, -1.0]
          Rater residuals:
            u1: [1.0 - 0.5, 0.0 - 0.5] = [0.5, -0.5]
            u2: [1.0 - 1.0, 1.0 - 1.0] = [0.0, 0.0]
            Combined: [0.5, -0.5, 0.0, 0.0]
          Population std:
            ASR: mean = -0.25
            variance = ((0.5 + 0.25)^2 + (-1.0 + 0.25)^2)/2 = (0.75^2 + -0.75^2)/2 = 0.5625
            std = 0.75
            Rater: mean = 0
            variance = (0.5^2 + (-0.5)^2 + 0^2 + 0^2)/4 = 0.125
            std = sqrt(0.125) = 0.353553...
          Ratio:
            0.75 / 0.353553... = 2.121320... ≈ 2.1213

        Normalization by SNR

          Baseline for both utterances:
            mean of utterance means = (0.5 + 1.0)/2 = 0.75
          ASR residuals:
            [1.0 - 0.75, 0.0 - 0.75] = [0.25, -0.75]
          Rater residuals:
            u1: [1.0 - 0.75, 0.0 - 0.75] = [0.25, -0.75]
            u2: [1.0 - 0.75, 1.0 - 0.75] = [0.25, 0.25]
            Combined: [0.25, -0.75, 0.25, 0.25]
          Population std:
            ASR: mean = -0.25
            variance = ((0.25 + 0.25)^2 + (-0.75 + 0.25)^2)/2 = (0.5^2 + -0.5^2)/2 = 0.25
            std = 0.5
            Rater: mean = 0
            variance = (0.25^2 + (-0.75)^2 + 0.25^2 + 0.25^2)/4 = 0.1875
            std = sqrt(0.1875) = 0.4330127...
          Ratio:
            0.5 / 0.4330127... = 1.154700... ≈ 1.1547

        Expected residual std-ratio (ASR/Rater):
          mode=normalization_by_utterance -> ~2.1213
          mode=normalization_by_snr       -> ~1.1547
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT
            );
            CREATE TABLE audio_trials (
                id INTEGER PRIMARY KEY,
                project TEXT,
                snr INTEGER,
                answer TEXT,
                lang TEXT
            );
            CREATE TABLE audio_results (
                id INTEGER PRIMARY KEY,
                subject INTEGER,
                trial INTEGER
            );
            CREATE TABLE audio_annotations (
                ref INTEGER,
                data TEXT
            );
            CREATE TABLE review_annotations (
                ref INTEGER,
                labeler INTEGER,
                data TEXT
            );
            CREATE TABLE audio_asr (
                ref INTEGER,
                data TEXT
            );
            """
        )

        # Subject user and two raters.
        cur.execute("INSERT INTO users (id, username) VALUES (1, 'A1S1')")
        cur.execute("INSERT INTO users (id, username) VALUES (101, 'rater1')")
        cur.execute("INSERT INTO users (id, username) VALUES (102, 'rater2')")

        # Two utterances in same project+snr.
        cur.execute(
            "INSERT INTO audio_trials (id, project, snr, answer, lang) VALUES (11, 'quick', 0, 'cat', 'en')"
        )
        cur.execute(
            "INSERT INTO audio_trials (id, project, snr, answer, lang) VALUES (12, 'quick', 0, 'dog', 'en')"
        )

        cur.execute("INSERT INTO audio_results (id, subject, trial) VALUES (201, 1, 11)")
        cur.execute("INSERT INTO audio_results (id, subject, trial) VALUES (202, 1, 12)")

        # ASR: utterance 1 matches (1.0 when max_words=1), utterance 2 does not (0.0).
        cur.execute("INSERT INTO audio_asr (ref, data) VALUES (201, '{\"text\": \"cat\"}')")
        cur.execute("INSERT INTO audio_asr (ref, data) VALUES (202, '{\"text\": \"bird\"}')")

        # Optional audiologist rows; not needed for residual computation but harmless.
        cur.execute("INSERT INTO audio_annotations (ref, data) VALUES (201, '[true]')")
        cur.execute("INSERT INTO audio_annotations (ref, data) VALUES (202, '[true]')")

        # Rater scores per utterance:
        # utterance 1 -> [1.0, 0.0]
        cur.execute("INSERT INTO review_annotations (ref, labeler, data) VALUES (201, 101, '[true]')")
        cur.execute("INSERT INTO review_annotations (ref, labeler, data) VALUES (201, 102, '[false]')")
        # utterance 2 -> [1.0, 1.0]
        cur.execute("INSERT INTO review_annotations (ref, labeler, data) VALUES (202, 101, '[true]')")
        cur.execute("INSERT INTO review_annotations (ref, labeler, data) VALUES (202, 102, '[true]')")

        conn.commit()
        conn.close()

    def _run_and_extract_ratio(self, residual_normalization: str) -> float:
        residual_plot = os.path.join(self.temp_dir, f"residual_{residual_normalization}.png")
        output_csv = os.path.join(self.temp_dir, f"summary_{residual_normalization}.csv")

        cmd = [
            sys.executable,
            self.script_path,
            "--dbfile", self.db_path,
            "--homonyms", self.homonyms_path,
            "--language", "en",
            "--project", "quick",
            "--max_words", "1",
            "--professional_raters", self.professional_raters_path,
            "--student_raters", self.student_raters_path,
            "--rater_type", "all",
            "--output", output_csv,
            "--residual_plot", residual_plot,
            "--residual_normalization", residual_normalization,
            "--no_plot",
            "--no_subject_plot",
        ]

        proc = subprocess.run(
            cmd,
            cwd=self.temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        self.assertTrue(os.path.exists(residual_plot), msg=f"Expected residual plot: {residual_plot}")

        # Parse from:
        # Residual standard deviation summary: ASR=..., Rater=..., ASR/Rater=1.2345
        match = re.search(r"Residual standard deviation summary:.*ASR/Rater=([-+]?\d*\.?\d+|nan)", proc.stdout)
        self.assertIsNotNone(
            match,
            msg=(
                "Did not find residual summary line in summarize_raters output.\n"
                f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
            ),
        )
        token = match.group(1).lower()
        self.assertNotEqual(token, "nan")
        return float(token)

    def test_residual_mean_mode_utterance(self):
        ratio = self._run_and_extract_ratio("normalization_by_utterance")
        self.assertAlmostEqual(ratio, 2.1213, places=3)

    def test_residual_mean_mode_project_snr(self):
        ratio = self._run_and_extract_ratio("normalization_by_snr")
        self.assertAlmostEqual(ratio, 1.1547, places=3)

    def test_residual_mean_modes_produce_different_ratios(self):
        ratio_utterance = self._run_and_extract_ratio("normalization_by_utterance")
        ratio_project_snr = self._run_and_extract_ratio("normalization_by_snr")
        self.assertNotAlmostEqual(ratio_utterance, ratio_project_snr, places=2)


if __name__ == "__main__":
    absltest.main()
