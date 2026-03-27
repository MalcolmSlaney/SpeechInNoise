"""Small program to check the status of the database and the number of
trials that have been populated with ASR results.
"""


import sqlite3
import json
import os

db_path = "experiments_malcolm.db" # Ensure this matches your filename

def verify():
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {os.path.abspath(db_path)}")
        return

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        
        # 1. Check if the table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audio_asr'")
        if not cur.fetchone():
            print("Table 'audio_asr' does NOT exist.")
            return

        # 2. Get total row count
        cur.execute("SELECT COUNT(*) FROM audio_asr")
        total_rows = cur.fetchone()[0]
        
        # 3. Get count of rows where data is actually present
        cur.execute("SELECT COUNT(*) FROM audio_asr WHERE data IS NOT NULL AND data != ''")
        populated_rows = cur.fetchone()[0]

        print(f"--- Database Report: {db_path} ---")
        print(f"Total rows in 'audio_asr': {total_rows}")
        print(f"Populated ASR results:     {populated_rows}")
        print(f"Empty/Null results:        {total_rows - populated_rows}")

        # 4. Show a sample of the data if it exists
        if populated_rows > 0:
            print("\nSample Data (First 2 rows):")
            cur.execute("SELECT ref, data FROM audio_asr WHERE data IS NOT NULL LIMIT 2")
            for ref, data in cur.fetchall():
                # Preview just the start of the JSON string
                preview = data[:100] + "..." if len(data) > 100 else data
                print(f"Ref {ref}: {preview}")
        else:
            print("\nNo data found. This suggests the INSERTs didn't commit or the path was wrong.")

if __name__ == "__main__":
    verify()
