import json, sqlite3, unicodedata, uuid, os, time
from flask import request, session, abort
from storage import relpath, DatabaseBP, Database
from review_modules.consent_upload import (
    ensure_consent_form_column,
    process_consent_form_upload
)
from review import ReviewBP

class ReviewAPIBlueprint(DatabaseBP):
    def __init__(self,
                 db_path=relpath("experiments.db"),
                 schema_path=relpath("schema.sql"),
                 name="api_review", url_prefix=None):
        super().__init__(db_path, schema_path, name, url_prefix)
        db = lambda: self._blueprint_db
        # Register ReviewBP as a sub-blueprint
        self.review_bp = ReviewBP(db)
        self.register_blueprint(self.review_bp)
        # Register reviewer-specific set-username endpoint
        self._route_db("/review/set-username", methods=["GET", "POST"])(reviewer_set_username)

    def _bind_db(self, app):
        super()._bind_db(app)
        # Initialize database for creating users in main experiments database
        self._blueprint_db = Database(
            app, *self._db_paths, ["PRAGMA foreign_keys = ON"])
        # ReviewBP handles its own database binding separately

username_blocks = ("L", "Nd", "Nl", "Pc", "Pd", "Zs")
def username_rules(value: str):
    if not 0 < len(value) <= 512:
        return False
    for char in value:
        # Allow @ and . for email addresses
        if char in ('@', '.'):
            continue
        c = unicodedata.category(char)
        if not any(c.startswith(b) for b in username_blocks):
            return False
    return True

always_accept = lambda x: "test-".startswith(x[:5]) and len(x) >= 4

def reviewer_set_username(db):
    """Handle username setting for reviewers with consent form validation."""
    def get_param(key):
        return request.form.get(key) or request.args.get(key)
    
    name = get_param("v")
    if name is None or not username_rules(name):
        return json.dumps({"error": "Invalid username"}, indent=4), 400

    # Normalize case
    name = name.lower()

    if always_accept(name):
        name = f"{name}-{uuid.uuid4()}"

    # Preserve review session variables if same user
    review_session_vars = {}
    if session.get("username") and session.get("username").lower() == name:
        for key in ["current_test", "current_level", "cur", "played_audio", "current_test_total_files", "last_reviewed_subject"]:
            if key in session:
                review_session_vars[key] = session[key]

    # Get reviewer-specific parameters
    is_audiology_student = get_param("is-audiology-student")
    is_certified_audiologist = get_param("is-certified-audiologist")
    experience_years = get_param("experience-years")
    consent_form = request.files.get('filled-consent-form')
    
    role = None
    years_practicing = None
    if is_audiology_student == "true" or is_certified_audiologist == "true":
        role = "student" if is_audiology_student == "true" else "audiologist"
        if role == "audiologist":
            if not experience_years or experience_years.strip() == "":
                return json.dumps({"error": "Years of practice is required for certified audiologists."}, indent=4), 400
            try:
                years_practicing = int(experience_years)
                if years_practicing < 0 or years_practicing > 100:
                    return json.dumps({"error": "Please enter a valid number of years between 0 and 100."}, indent=4), 400
            except (ValueError, TypeError):
                return json.dumps({"error": "Years of practice must be a valid number."}, indent=4), 400
    
    # Handle consent form validation and reviewer database
    review_db_path = os.environ.get("SELECTED_DATABASE", relpath("experiments.db"))
    max_retries = 5
    retry_delay = 0.1
    
    for attempt in range(max_retries):
        try:
            review_conn = sqlite3.connect(review_db_path, timeout=10.0)
            review_conn.execute("PRAGMA foreign_keys = ON")
            ensure_consent_form_column(review_conn)
            
            existing_reviewer = review_conn.execute(
                "SELECT id FROM reviewers WHERE username = ?", (name,)
            ).fetchone()
            
            if existing_reviewer:
                if consent_form:
                    review_conn.close()
                    return json.dumps({"error": "We already have a consent form for you. You may log in as a returning reviewer with only your email."}, indent=4), 400
            else:
                if not consent_form:
                    review_conn.close()
                    return json.dumps({"error": "Email not found. If you are a new reviewer, please select 'I am a new reviewer' and upload a consent form. If you are a returning reviewer, please check your email."}, indent=4), 400
                if role is None:
                    review_conn.close()
                    return json.dumps({"error": "Please select whether you are an audiology student or certified audiologist."}, indent=4), 400
                
                success, error_message, file_path = process_consent_form_upload(
                    review_conn, name, role, years_practicing, consent_form
                )
                
                if not success:
                    review_conn.close()
                    return json.dumps({"error": error_message}, indent=4), 400
            
            review_conn.close()
            break
            
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                review_conn.close() if 'review_conn' in locals() else None
                time.sleep(retry_delay * (2 ** attempt))
                continue
            else:
                if 'review_conn' in locals():
                    review_conn.close()
                break
        except Exception:
            if 'review_conn' in locals():
                review_conn.close()
            break

    # Create user in main experiments database
    try:
        uid = db.execute(
            "INSERT INTO users (username, ip) VALUES (?, ?)",
            (name, request.remote_addr))
    except sqlite3.IntegrityError:
        uid = db.queryone("SELECT id FROM users WHERE username=?", (name,))[0]

    all_params = dict(request.args)
    all_params.update(request.form)
    search = json.dumps(all_params, indent=4)
    db.execute(
        "INSERT INTO user_info (user, info_key, value) "
        "VALUES (?, 'searchParams', ?)",
        (uid, search))

    session.clear()
    session["user"], session["username"] = uid, name
    session["meta"] = search
    
    # Restore review session variables
    for key, value in review_session_vars.items():
        session[key] = value
    
    return json.dumps({"success": True, "username": name}, indent=4)
