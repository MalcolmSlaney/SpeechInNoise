import os, sqlite3
from storage import relpath

def ensure_consent_form_column(review_conn):
    table_exists = review_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reviewers'"
    ).fetchone()
    
    if not table_exists:
        review_conn.execute("""
            CREATE TABLE IF NOT EXISTS reviewers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              t TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              role TEXT NOT NULL CHECK(role IN('student', 'audiologist')),
              years_practicing INTEGER CHECK((role = 'audiologist' AND years_practicing IS NOT NULL) OR (role = 'student' AND years_practicing IS NULL)),
              completed_tests TEXT,
              test_in_progress TEXT,
              remaining_tests TEXT,
              most_recent_subject INTEGER,
              total_reviews INTEGER DEFAULT 0,
              played_audio TEXT,
              notes TEXT,
              consent_form BLOB NOT NULL
            )
        """)
        review_conn.commit()
    else:
        columns = [row[1] for row in review_conn.execute("PRAGMA table_info(reviewers)").fetchall()]
        if 'consent_form' not in columns:
            review_conn.execute("ALTER TABLE reviewers ADD COLUMN consent_form BLOB")
            review_conn.commit()

def validate_consent_form_file(consent_form_file):
    if not consent_form_file:
        return None, "No consent form file provided."
    
    if not consent_form_file.filename or not consent_form_file.filename.lower().endswith('.pdf'):
        return None, "Please upload a PDF file."
    
    consent_form_data = consent_form_file.read()
    if len(consent_form_data) > 10 * 1024 * 1024:
        return None, "File is too large."
    
    if not consent_form_data.startswith(b'%PDF'):
        return None, "Invalid PDF file."
    
    return consent_form_data, None

def save_consent_form_to_database(review_conn, username, role, years_practicing, consent_form_data):
    review_conn.execute(
        "INSERT INTO reviewers (username, role, years_practicing, consent_form) VALUES (?, ?, ?, ?)",
        (username, role, years_practicing, consent_form_data))
    review_conn.commit()

def save_consent_form_to_filesystem(username, consent_form_data):
    try:
        consent_form_uploads_dir = relpath("consent_form_uploads")
        os.makedirs(consent_form_uploads_dir, exist_ok=True)
        safe_username = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in username)
        consent_form_path = os.path.join(consent_form_uploads_dir, f"{safe_username}_consent_form.pdf")
        with open(consent_form_path, "wb") as f:
            f.write(consent_form_data)
        return consent_form_path, None
    except Exception as e:
        return None, str(e)

def process_consent_form_upload(review_conn, username, role, years_practicing, consent_form_file):
    consent_form_data, validation_error = validate_consent_form_file(consent_form_file)
    if validation_error:
        return False, validation_error, None
    
    try:
        save_consent_form_to_database(review_conn, username, role, years_practicing, consent_form_data)
    except Exception as e:
        return False, f"Failed to save consent form: {e}", None
    
    file_path, file_error = save_consent_form_to_filesystem(username, consent_form_data)
    if file_error:
        return True, None, None
    
    return True, None, file_path

