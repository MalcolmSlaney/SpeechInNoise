import json, sqlite3, unicodedata, uuid
from flask import request, session, abort
from storage import relpath, DatabaseBP
from projects import (
    QuickDB, QuickBP,
    Qs3DB, Qs3BP,
    Nu6DB, Nu6BP,
    AzBioDB, AzBioBP,
    AzBioQuietDB, AzBioQuietBP,
    CncDB, CncBP,
    WinDB, WinBP,
)
from review import ReviewBP

# use multiple inheritance to add other DB hooks
class ExperimentDB(QuickDB, Qs3DB, Nu6DB, AzBioDB, AzBioQuietDB, CncDB, WinDB):
    def _username_hook(self):
        res = set_username(self)
        super()._username_hook()
        return res

def username_hook(db):
    return db._username_hook()

class APIBlueprint(DatabaseBP):
    default_project = "quick"

    def __init__(self,
                 db_path=relpath("experiments.db"),
                 schema_path=relpath("schema.sql"),
                 name="api", url_prefix=None):
        super().__init__(db_path, schema_path, name, url_prefix)
        db = lambda: self._blueprint_db
        self.projects = {
            "quick": QuickBP,
            "qs3": Qs3BP,
            "nu6": Nu6BP,
            "azbio": AzBioBP,
            "azbio_quiet": AzBioQuietBP,
            "cnc": CncBP,
            "win": WinBP,
            "review": ReviewBP,
        }
        assert self.default_project in self.projects and "" not in self.projects
        for bp in self.projects.keys():
            self.projects[bp] = self.projects[bp](db)
            self.register_blueprint(self.projects[bp])
        self._route_db("/username-available")(username_available)
        self._route_db("/set-username")(username_hook)
        self._route_db("/authorized", methods=["POST"])(authorized)
        self._route_db("/lists", methods=["POST"])(self.audio_lists)

    def _bind_db(self, app):
        super()._bind_db(app)
        self._blueprint_db = ExperimentDB(
            app, *self._db_paths, ["PRAGMA foreign_keys = ON"])
        app.config.update(SESSION_COOKIE_NAME="audio-experiments")
        #app.config.update(SESSION_COOKIE_NAME="audio-experiments-staging")

        try:
            with open(relpath("secret_key"), "rb") as f:
                app.secret_key = f.read()
        except FileNotFoundError:
            import os
            with open(relpath("secret_key"), "wb") as f:
                secret = os.urandom(24)
                f.write(secret)
                app.secret_key = secret

    def audio_lists(self, db):
        return json.dumps({"": self.default_project, **{
            k: json.loads(v.audio_lists(db))
            for k, v in self.projects.items()}})

username_blocks = ("L", "Nd", "Nl", "Pc", "Pd", "Zs")
def username_rules(value: str):
    if not 0 < len(value) <= 512:
        return False
    for c in map(unicodedata.category, value):
        if not any(c.startswith(b) for b in username_blocks):
            return False
    return True

always_accept = lambda x: "test-".startswith(x[:5]) and len(x) >= 4

def username_available(db):
    checking = request.args.get("v")
    if checking is None or not username_rules(checking):
        return json.dumps(False)

    return json.dumps(True)

    if always_accept(checking):
        return json.dumps(True)

    return json.dumps(not db.queryone(
        "SELECT EXISTS(SELECT 1 FROM users WHERE username=? LIMIT 1)",
        (checking,))[0])

def set_username(db):
    def get_param(key):
        return request.form.get(key) or request.args.get(key)
    
    name = get_param("v")
    if name is None or not username_rules(name):
        return json.dumps("")

    if always_accept(name):
        name = f"{name}-{uuid.uuid4()}"

    review_session_vars = {}
    if session.get("username") == name:
        for key in ["current_test", "current_level", "cur", "played_audio", "current_test_total_files", "last_reviewed_subject"]:
            if key in session:
                review_session_vars[key] = session[key]

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

    is_audiology_student = get_param("is-audiology-student")
    is_certified_audiologist = get_param("is-certified-audiologist")
    experience_years = get_param("experience-years")
    
    role = None
    years_practicing = None
    if is_audiology_student == "true" or is_certified_audiologist == "true":
        role = "student" if is_audiology_student == "true" else "audiologist"
        if role == "audiologist":
            if not experience_years or experience_years.strip() == "":
                return json.dumps({"error": "Years of practice is required for certified audiologists."}, indent=4)
            try:
                years_practicing = int(experience_years)
                if years_practicing < 0 or years_practicing > 100:
                    return json.dumps({"error": "Please enter a valid number of years between 0 and 100."}, indent=4)
            except (ValueError, TypeError):
                return json.dumps({"error": "Years of practice must be a valid number."}, indent=4)
    
    review_db_path = os.environ.get("SELECTED_DATABASE", relpath("backup.db"))
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

            consent_form = request.files.get('filled-consent-form')
            
            if existing_reviewer:
                if consent_form:
                    review_conn.close()
                    return json.dumps({"error": "We already have a consent form for you. You may log in as a returning reviewer with only your username."}, indent=4)
            else:
                if not consent_form:
                    review_conn.close()
                    return json.dumps({"error": "Username not found. If you are a new reviewer, please select 'I am a new reviewer' and upload a consent form. If you are a returning reviewer, please check your username."}, indent=4)
                if role is None:
                    review_conn.close()
                    return json.dumps({"error": "Please select whether you are an audiology student or certified audiologist."}, indent=4)
                
                success, error_message, file_path = process_consent_form_upload(
                    review_conn, name, role, years_practicing, consent_form
                )
                
                if not success:
                    review_conn.close()
                    return json.dumps({"error": error_message}, indent=4)
            
            review_conn.close()
            break
            
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                review_conn.close() if 'review_conn' in locals() else None
                time.sleep(retry_delay * (2 ** attempt))
                continue
            else:
                print(f"WARNING: Failed to update reviewers table after {attempt + 1} attempts: {e}")
                if 'review_conn' in locals():
                    review_conn.close()
                break
        except Exception as e:
            print(f"WARNING: Failed to update reviewers table in review database for {name}: {e}")
            if 'review_conn' in locals():
                review_conn.close()
            break

    session.clear()
    session["user"], session["username"] = uid, name
    session["meta"] = search
    
    for key, value in review_session_vars.items():
        session[key] = value
    
    requested = get_param("list") or "null"
    if requested != "null":
        if "-" in requested:
            lang, trial_number = requested.rsplit("-", 1)
            try:
                trial_number = json.loads(trial_number)
            except json.decoder.JSONDecodeError:
                abort(400)
            if not isinstance(trial_number, int):
                abort(400)
        else:
            lang, trial_number = requested, None
        session["requested"] = json.dumps([lang, trial_number])
    else:
        session["requested"] = json.dumps(['en', None])
    return json.dumps(APIBlueprint.default_project)

def authorized(db):
    return json.dumps(True)

