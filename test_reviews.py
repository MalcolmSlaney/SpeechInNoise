# script to submit multiple hardcoded reviews to test that we can compare multiple reviewers

import sqlite3
import json
import os

def relpath(*args):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), *args)

SELECTED_DATABASE = os.environ.get("SELECTED_DATABASE", relpath("experiments.db"))

conn = sqlite3.connect(SELECTED_DATABASE)
conn.execute("PRAGMA foreign_keys = ON")

# Find the audio_results.id for the filename
from test_config import TEST_FILENAME
filename = TEST_FILENAME
ref_id = conn.execute("SELECT id FROM audio_results WHERE reply_filename = ?", (filename,)).fetchone()[0]

# Get reviewer IDs
labeler1_id = conn.execute("SELECT id FROM users WHERE username = ?", ("testemail",)).fetchone()[0]
labeler2_id = conn.execute("SELECT id FROM users WHERE username = ?", ("testemail2",)).fetchone()[0]

# Hardcoded annotations (length 8)
annotations1 = [False, False, True, True, True, True, True, True]
annotations2 = [True, True, True, True, True, True, True, True]

# Insert reviews
conn.execute("INSERT INTO review_annotations (ref, data, labeler, unclear) VALUES (?, ?, ?, ?)",
             (ref_id, json.dumps(annotations1), labeler1_id, 0))
conn.execute("INSERT INTO review_annotations (ref, data, labeler, unclear) VALUES (?, ?, ?, ?)",
             (ref_id, json.dumps(annotations2), labeler2_id, 0))

conn.commit()
conn.close()