"""Tests for the one-line database completeness report."""

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from database_completeness import completion_counts


SCHEMA = """
    CREATE TABLE audio_results (id INTEGER PRIMARY KEY);
    CREATE TABLE audio_asr (ref INTEGER, data TEXT);
    CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
    CREATE TABLE review_annotations (ref INTEGER, labeler INTEGER, data TEXT);
"""


class DatabaseCompletenessTest(unittest.TestCase):
    def test_counts_nonempty_results_and_all_distinct_professionals(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(SCHEMA)
            connection.executescript("""
                INSERT INTO audio_results VALUES (1), (2), (3), (4);
                INSERT INTO audio_asr VALUES
                    (1, '{}'), (1, '{}'), (2, ''), (3, NULL), (4, '{}'), (99, '{}');
                INSERT INTO users VALUES (1, 'ALICE'), (2, 'bob'), (3, 'other');
                INSERT INTO review_annotations VALUES
                    (1, 1, '[false]'), (1, 1, '[true]'), (1, 2, '[false]'),
                    (2, 1, '[true]'), (2, 3, '[true]'),
                    (3, 1, '[true]'), (3, 2, ''),
                    (4, 1, '[true]'), (4, 2, NULL),
                    (99, 1, '[true]'), (99, 2, '[true]');
            """)
            self.assertEqual(completion_counts(connection, {"alice", "BOB"}), (4, 2, 1))

    def test_empty_database_and_empty_rater_list(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(SCHEMA)
            self.assertEqual(completion_counts(connection, {"alice"}), (0, 0, 0))
            with self.assertRaisesRegex(ValueError, "list is empty"):
                completion_counts(connection, set())

    def test_cli_one_line_and_read_only_missing_database(self):
        script = Path(__file__).with_name("database_completeness.py")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(SCHEMA)
            result = subprocess.run(
                [sys.executable, str(script), str(database)],
                capture_output=True, text=True, check=True, cwd=directory,
            )
            self.assertEqual(
                result.stdout,
                "ASR: 0/0 (N/A); all professional raters: 0/0 (N/A)\n",
            )
            self.assertEqual(result.stderr, "")
            missing = Path(directory) / "missing.db"
            result = subprocess.run(
                [sys.executable, str(script), str(missing)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.startswith("Error:"))
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
