"""Check the database for missing rows, orphaned records, and duplicate ASR entries.

This script prints a summary of the main tables and runs SQLite integrity checks
so you can confirm that data was not lost during imports or migrations.
"""

import json
import os
import sqlite3

from absl import app
from absl import flags

FLAGS = flags.FLAGS
try:
    flags.DEFINE_string(
        "dbfile",
        "experiments_malcolm.db",
        "Path to the SQLite database file.",
    )
except flags.DuplicateFlagError:
    pass

TABLES_TO_CHECK = [
    "users",
    "user_info",
    "audio_trials",
    "audio_results",
    "audio_asr",
    "audio_annotations",
    "review_annotations",
]


def count_rows(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def table_exists(cur, table):
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def count_missing(cur, query):
    cur.execute(query)
    return cur.fetchone()[0]


def preview_json(value, limit=120):
    if value is None:
        return "NULL"
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[:limit] + "..."


def summarize_asr_results(cur):
    """Print the fraction of audio results with computed ASR, by project."""
    query = """
        SELECT
            at.project,
            COUNT(ar.id) AS total_results,
            SUM(
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM audio_asr aa
                    WHERE aa.ref = ar.id
                      AND aa.data IS NOT NULL
                      AND aa.data != ''
                ) THEN 1 ELSE 0 END
            ) AS computed_results
        FROM audio_results ar
        JOIN audio_trials at ON ar.trial = at.id
        GROUP BY at.project
        ORDER BY at.project
    """
    cur.execute(query)
    rows = cur.fetchall()

    print("\nASR completion by project:")
    if not rows:
        print("  No audio results found.")
        return

    print(f"  {'Project':<20} {'Computed':>10} {'Total':>10} {'Complete':>10}")
    for row in rows:
        percentage = 100 * row["computed_results"] / row["total_results"]
        print(
            f"  {row['project']:<20} {row['computed_results']:>10} "
            f"{row['total_results']:>10} {percentage:>9.1f}%"
        )


def verify(db_path="experiments_malcolm.db"):
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {os.path.abspath(db_path)}")
        return

    print(f"--- Database Report: {db_path} ---")
    print(f"File size: {os.path.getsize(db_path)} bytes")

    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys = ON")

        existing_tables = [name for name in TABLES_TO_CHECK if table_exists(cur, name)]
        missing_tables = [name for name in TABLES_TO_CHECK if name not in existing_tables]

        if all(table_exists(cur, table) for table in ["audio_trials", "audio_results", "audio_asr"]):
            summarize_asr_results(cur)
        else:
            print("\nASR completion by project: skipped (required table missing)")

        print(f"Tables found: {len(existing_tables)} / {len(TABLES_TO_CHECK)}")
        if missing_tables:
            print("Missing tables:")
            for table in missing_tables:
                print(f"  - {table}")

        # Row counts for the main tables.
        print("\nRow counts:")
        for table in TABLES_TO_CHECK:
            if table_exists(cur, table):
                print(f"  {table}: {count_rows(cur, table)}")
            else:
                print(f"  {table}: <missing>")

        # Referential integrity checks.
        print("\nConsistency checks:")
        checks = {
            "audio_results with missing trial": (
                "SELECT COUNT(*) FROM audio_results ar "
                "LEFT JOIN audio_trials at ON ar.trial = at.id "
                "WHERE at.id IS NULL"
            ),
            "audio_results with missing subject": (
                "SELECT COUNT(*) FROM audio_results ar "
                "LEFT JOIN users u ON ar.subject = u.id "
                "WHERE u.id IS NULL"
            ),
            "audio_results with null subject or trial": (
                "SELECT COUNT(*) FROM audio_results WHERE subject IS NULL OR trial IS NULL"
            ),
            "audio_asr with missing ref": (
                "SELECT COUNT(*) FROM audio_asr a "
                "LEFT JOIN audio_results r ON a.ref = r.id "
                "WHERE r.id IS NULL"
            ),
            "audio_annotations with missing ref": (
                "SELECT COUNT(*) FROM audio_annotations aa "
                "LEFT JOIN audio_results r ON aa.ref = r.id "
                "WHERE r.id IS NULL"
            ),
            "review_annotations with missing ref": (
                "SELECT COUNT(*) FROM review_annotations ra "
                "LEFT JOIN audio_results r ON ra.ref = r.id "
                "WHERE r.id IS NULL"
            ),
            "review_annotations with missing labeler": (
                "SELECT COUNT(*) FROM review_annotations ra "
                "LEFT JOIN users u ON ra.labeler = u.id "
                "WHERE u.id IS NULL"
            ),
            "duplicate audio_asr refs": (
                "SELECT COUNT(*) FROM ("
                "SELECT ref FROM audio_asr GROUP BY ref HAVING COUNT(*) > 1"
                ")"
            ),
            "duplicate audio_results (same subject/trial)": (
                "SELECT COUNT(*) FROM ("
                "SELECT subject, trial FROM audio_results "
                "GROUP BY subject, trial HAVING COUNT(*) > 1"
                ")"
            ),
            "audio_asr rows with empty data": (
                "SELECT COUNT(*) FROM audio_asr WHERE data IS NULL OR data = ''"
            ),
        }

        for label, query in checks.items():
            if all(table_exists(cur, table) for table in ["audio_results", "audio_trials", "users", "audio_asr", "audio_annotations", "review_annotations"]):
                print(f"  {label}: {count_missing(cur, query)}")
            else:
                print(f"  {label}: skipped (required table missing)")

        # SQLite-level integrity checks.
        cur.execute("PRAGMA integrity_check")
        integrity = [row[0] for row in cur.fetchall()]
        print("\nSQLite integrity_check:")
        for item in integrity:
            print(f"  {item}")

        cur.execute("PRAGMA foreign_key_check")
        fk_issues = cur.fetchall()
        print("\nforeign_key_check results:")
        if fk_issues:
            for row in fk_issues:
                print(f"  {row}")
        else:
            print("  none")

        # Sample data preview.
        if table_exists(cur, "audio_asr") and count_rows(cur, "audio_asr") > 0:
            print("\nSample audio_asr rows (first 3):")
            # Some schemas may not have the extra ASR scoring columns yet.
            try:
                cur.execute(
                    "SELECT ref, data, gt_word_count, correct_word_count FROM audio_asr "
                    "ORDER BY ref LIMIT 3"
                )
                preview_rows = cur.fetchall()
                for row in preview_rows:
                    print(
                        f"  ref={row['ref']} | data={preview_json(row['data'])} | "
                        f"gt_word_count={row['gt_word_count']} | "
                        f"correct_word_count={row['correct_word_count']}"
                    )
            except sqlite3.OperationalError:
                cur.execute(
                    "SELECT ref, data FROM audio_asr ORDER BY ref LIMIT 3"
                )
                for row in cur.fetchall():
                    print(
                        f"  ref={row['ref']} | data={preview_json(row['data'])}"
                    )
        else:
            print("\nNo audio_asr rows found.")


def main(argv):
    del argv
    verify(FLAGS.dbfile)


if __name__ == "__main__":
    app.run(main)
