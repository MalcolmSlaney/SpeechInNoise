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
        from storage import relpath
        from flask import send_from_directory
        def review_html_handler(db):
            from flask import session, redirect
            if not session.get("username") and not session.get("user"):
                return redirect("/jnd/api/review/")
            return send_from_directory(relpath("static"), "review.html")
        self._route_db("/review.html")(review_html_handler)

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
    name = request.args.get("v")
    if name is None or not username_rules(name):
        return json.dumps("")

    if always_accept(name):
        name = f"{name}-{uuid.uuid4()}"

    try:
        uid = db.execute(
            "INSERT INTO users (username, ip) VALUES (?, ?)",
            (name, request.remote_addr))
    except sqlite3.IntegrityError:
        #return json.dumps("")
        uid = db.queryone("SELECT id FROM users WHERE username=?", (name,))[0]

    search = json.dumps(dict(request.args))
    db.execute(
        "INSERT INTO user_info (user, info_key, value) "
        "VALUES (?, 'searchParams', ?)",
        (uid, search))

    session.clear()
    session["user"], session["username"] = uid, name
    session["meta"] = search
    requested = request.args.get("list", "null")
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
