"""Report ASR and all-professional-rater coverage of recorded utterances."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


def completion_counts(
    connection: sqlite3.Connection, professional_raters: set[str]
) -> tuple[int, int, int]:
    """Count utterances with nonempty ASR data and every configured rater."""
    raters = {name.casefold() for name in professional_raters}
    if not raters:
        raise ValueError("The professional-rater list is empty.")
    placeholders = ", ".join("?" for _ in raters)
    query = f"""
        SELECT COUNT(*),
               COALESCE(SUM(EXISTS (
                   SELECT 1 FROM audio_asr a
                   WHERE a.ref = r.id AND a.data IS NOT NULL AND a.data != ''
               )), 0),
               COALESCE(SUM((
                   SELECT COUNT(DISTINCT LOWER(u.username))
                   FROM review_annotations a
                   JOIN users u ON u.id = a.labeler
                   WHERE a.ref = r.id AND a.data IS NOT NULL AND a.data != ''
                     AND LOWER(u.username) IN ({placeholders})
               ) = ?), 0)
        FROM audio_results r
    """
    total, asr, professional = connection.execute(
        query, (*sorted(raters), len(raters))
    ).fetchone()
    return total, asr, professional


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="SQLite database file")
    args = parser.parse_args()
    try:
        rater_file = Path(__file__).resolve().parent / "metadata" / "professional_raters.txt"
        raters = {
            name
            for line in rater_file.read_text(encoding="utf-8").splitlines()
            if (name := line.split("#", 1)[0].strip().casefold())
        }
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            total, asr, professional = completion_counts(connection, raters)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")

    asr_fraction = f"{asr / total:.1%}" if total else "N/A"
    professional_fraction = f"{professional / total:.1%}" if total else "N/A"
    print(
        f"ASR: {asr}/{total} ({asr_fraction}); "
        f"all professional raters: {professional}/{total} ({professional_fraction})"
    )


if __name__ == "__main__":
    main()
