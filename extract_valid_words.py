"""Extract valid words from the audio_trials table in the experiment database.

This script reads the SQLite database defined by the --dbfile flag, queries the
`audio_trials` table, and collects the valid answer words for each project.
Every answer string is split on whitespace and on homonym separators (`/`),
then normalized and grouped by project name. The result is a dictionary keyed by
project, with sorted word lists as values.

This program uses the absl.flags library for configuration:

  --dbfile: path to the SQLite database file.
  --output: optional file to write the JSON dictionary. If omitted, output is
            written to stdout.
  --lowercase: if True, all extracted words are lowercased.
  --show_counts: if True, print the number of valid words per project.
"""

import json
import os
import sqlite3
import sys
from absl import app
from absl import flags

FLAGS = flags.FLAGS
flags.DEFINE_string('dbfile', 'experiments_malcolm.db',
                    'Path to the SQLite database file.')
flags.DEFINE_string('output', '',
                    'Optional output path for a JSON file containing the project->words dictionary. If omitted, writes JSON to stdout.')
flags.DEFINE_boolean('lowercase', True,
                     'Lowercase all extracted words.')
flags.DEFINE_boolean('show_counts', False,
                     'If True, print project word counts after extraction.')


def normalize_word(word: str) -> str:
    """Normalize a single answer token.

    Args:
        word: A raw word token extracted from an answer field.

    Returns:
        The normalized word, stripped of surrounding whitespace and lowercased
        if --lowercase is enabled.
    """
    word = word.strip()
    return word.lower() if FLAGS.lowercase else word


def extract_valid_words(db_path: str) -> dict[str, list[str]]:
    """Extract valid words for each project from the database.

    Args:
        db_path: Path to the SQLite database file containing the experiments.

    Returns:
        A dictionary mapping project names to sorted lists of valid words.

    Raises:
        FileNotFoundError: If the provided database path does not exist.
        sqlite3.Error: If an SQLite error occurs while querying the database.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f'Database file not found: {db_path}')

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT project, answer FROM audio_trials "
            "WHERE answer IS NOT NULL AND TRIM(answer) != ''"
        )
        rows = cursor.fetchall()

    project_words: dict[str, set[str]] = {}
    for project, answer in rows:
        project_key = project if project is not None else 'UNKNOWN'
        answer = answer.strip()
        if not answer:
            continue
        for token in answer.split():
            for option in token.split('/'):
                normalized = normalize_word(option)
                if normalized:
                    project_words.setdefault(project_key, set()).add(normalized)

    return {project: sorted(words) for project, words in project_words.items()}


def main(argv):
    """Run the valid word extraction pipeline.

    Args:
        argv: Command-line arguments passed by absl.app. These are ignored because
            the absl flags system is used for configuration.
    """
    del argv  # unused

    try:
        valid_words = extract_valid_words(FLAGS.dbfile)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error as exc:
        print(f'Failed to read from database: {exc}', file=sys.stderr)
        sys.exit(1)

    if FLAGS.show_counts:
        print('Project valid word counts:')
        for project, words in sorted(valid_words.items()):
            print(f'  {project}: {len(words)}')
        print()

    output_data = json.dumps(valid_words, indent=2, ensure_ascii=False)

    if FLAGS.output:
        with open(FLAGS.output, 'w', encoding='utf-8') as f:
            f.write(output_data)
        print(f'Wrote valid word dictionary for {len(valid_words)} projects to {FLAGS.output}')
    else:
        print(output_data)


if __name__ == '__main__':
    app.run(main)
