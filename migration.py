"""
DATABASE MIGRATION: audio_asr cleanup and indexing
--------------------------------------------------
PURPOSE:
This script fixes a duplicate row issue in the 'audio_asr' table. 

WHY DUPLICATES OCCURRED:
The table lacked a UNIQUE constraint on the 'ref' column. Without it, 
SQLite's 'INSERT OR REPLACE' command behaves as a simple 'INSERT', 
creating a new row every time the ASR engine runs, even for the same trial.

WHAT THIS SCRIPT DOES:
1. Identifies trials with multiple ASR entries.
2. Deletes all but the oldest entry (MIN rowid) for each trial.
3. Creates a UNIQUE INDEX on 'ref'. This acts as a 'bouncer'—it forces 
   the 'REPLACE' part of 'INSERT OR REPLACE' to actually overwrite 
   existing records instead of duplicating them.
"""

import sqlite3
import os

import absl.flags as flags
import absl.app as app

def migrate_database(db_file):
    print(f"Connecting to {db_file}...")
    # Use a context manager for the connection to handle closing automatically
    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        try:
            # 1. Count the damage
            cur.execute("SELECT COUNT(*) - COUNT(DISTINCT ref) FROM audio_asr")
            dup_count = cur.fetchone()[0]
            if dup_count == 0:
                print("No duplicates found. Checking for index...")
            else:
                print(f"Found {dup_count} duplicate entries. Cleaning up...")

            # 2. Keep the first entry, kill the rest
            # We use the hidden 'rowid' since audio_asr has no Primary Key
            cur.execute("""
                DELETE FROM audio_asr 
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) 
                    FROM audio_asr 
                    GROUP BY ref
                )
            """)
            print(f"Duplicates removed.")

            # 3. Install the Unique Index
            print("Applying UNIQUE index to 'ref' column...")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_asr_ref ON audio_asr (ref)")
            
            con.commit()
            print("Migration complete. Your 'update' function will now work correctly.")

        except Exception as e:
            con.rollback()
            print(f"Migration failed with error: {e}")


def add_asr_columns_if_needed(db_file):
    # Use a context manager for the connection to handle closing automatically
    with sqlite3.connect(db_file) as con:
      cursor = con.cursor()
      # 3. Ensure the new columns exist in the audio_asr table
      new_columns = {
          'gt_word_count': 'INTEGER',
          'correct_word_count': 'INTEGER',
          'asr_clean_tokens': 'TEXT'
      }
      
      for col, col_type in new_columns.items():
          try:
              cursor.execute(f"ALTER TABLE audio_asr ADD COLUMN {col} {col_type};")
              print(f"Added new column '{col}' to audio_asr table.")
          except sqlite3.OperationalError:
              # Column likely already exists, which is fine
              pass
      con.commit()

try:
  flags.DEFINE_string('dbfile', 'experiments_malcolm.db', 
                      'Path to the SQLite database file to migrate.')
except flags.DuplicateFlagError:
    pass # Flag was already defined by another module during pytest collection
FLAGS = flags.FLAGS

def main(*argv):
    if len(argv) > 1:
        print(f"Warning: Unused command line arguments: {argv[1:]}")
    if not os.path.exists(FLAGS.dbfile):
        print(f"Error: Database file '{FLAGS.dbfile}' not found.")
        return
    migrate_database(FLAGS.dbfile)
    add_asr_columns_if_needed(FLAGS.dbfile)

if __name__ == "__main__":
  app.run(main)
