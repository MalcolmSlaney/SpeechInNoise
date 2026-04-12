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

def migrate_database(db_file):
    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return

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

if __name__ == "__main__":
    # Change this to your actual database filename
    TARGET_DB = "experiments_malcolm.db" 
    migrate_database(TARGET_DB)
