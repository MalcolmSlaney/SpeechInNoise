import os, os.path, json, random, functools, uuid, subprocess
from flask import (
    Blueprint, request, session, abort, redirect, Response, send_from_directory)
from storage import Database, relpath, DatabaseBP
from plot import scatter_results, logistic_results

upload_location = relpath("uploads")

# prefixed with audio to avoid namespace collisions with other APIs
class AudioDB(Database):
    csv_keys = (
        "active", "lang", "trial_number", "level_number", "filename", "answer")
    id_keys = {"lang", "trial_number", "level_number"}
    upserting = False

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        os.makedirs(upload_location, exist_ok=True)
        with self.app.app_context():
            self.validate()

    def conflict_clause(self, cls):
        if not self.upserting:
            return ""
        return " ON CONFLICT DO UPDATE SET " + ", ".join(
                f"{i} = excluded.{i}" for i in cls.csv_keys
                if i not in cls.id_keys)

    def parse_csv(self, cls):
        assert os.path.exists(cls.audio_files)
        with open(cls.audio_files, "r") as f:
            experiments = [
                [part.strip() for part in line.split(
                    ",", len(cls.csv_keys) - 1)] for line in f]
        con = self.get()
        cur = con.cursor()
        cur.executemany(
            f"INSERT INTO {cls.trials_table} "
            f"(project, {', '.join(cls.csv_keys)}) "
            f"VALUES ({', '.join('?' * (len(cls.csv_keys) + 1))})"
            f"{self.conflict_clause(cls)}",
            [[cls.project_key] + i for i in experiments])
        con.commit()

    def validate(self):
        pass

    @staticmethod
    def commits():
        return subprocess.check_output(
                "git log | grep ^commit | cut -d' ' -f 2",
                shell=True, cwd=relpath()).decode().strip().split()

    def db_init_hook(self):
        self.execute(
                "INSERT INTO version (id, hash) VALUES (1, ?) "
                "ON CONFLICT (id) DO UPDATE SET hash = excluded.hash",
                self.commits()[:1])

    def _username_hook(self):
        res = getattr(super(), "_username_hook", lambda: None)()
        self.execute(
                "INSERT INTO user_info (user, info_key, value) "
                "VALUES (?, 'test-type', ?)",
                (int(session["user"]), request.args.get("t", "unknown")))
        return res

def saved_png(path):
    def decorator(f):
        def load_path(*a, **kw):
            f(*a, **kw)
            with open(path, 'rb') as fp:
                return fp.read()
        return functools.wraps(f)(bytes_png(load_path))
    return decorator

def bytes_png(f):
    @functools.wraps(f)
    def flask_response(*a, **kw):
        return Response(f(*a, **kw), mimetype='image/png')
    return flask_response

class AudioBP(DatabaseBP):
    audio_keys = (
        "id", "lang", "level_number", "trial_number", "filename", "answer")
    audio_done = [1, "--", 0, 1, "", 1]

    def audio_url(self, v):
        return v and "audio/" + v

    def audio_trial_dict(self, v):
        return dict(zip(self.audio_keys, v))

    def __init__(self, db, name, url_prefix):
        Blueprint.__init__(self, name, __name__, url_prefix=url_prefix)
        self._route_db("/lists", methods=["POST"])(self.audio_lists)
        self._route_db("/start")(self.audio_start)
        self._route_db("/result", methods=["POST"])(self.audio_result)
        self._route_db("/recognized")(self.audio_recognized)
        self._bind_db = db
        self.result_fields = tuple(zip(*sorted(self.result_fields().items())))

    @property
    def _blueprint_db(self):
        return self._bind_db()

    def audio_async(self, db, rowid, fpath, answer):
        raise NotImplementedError()

    def audio_lists(self, db):
        langs = [i[0] for i in db.queryall(
                f"SELECT DISTINCT lang FROM {self.trials_table} "
                "WHERE project=? AND level_number=1", (self.project_key,))]
        lists = [i[0] for i in db.queryall(
                f"SELECT lang || '-' || trial_number FROM {self.trials_table} "
                "WHERE project=? AND level_number=1", (self.project_key,))]
        return json.dumps(langs + lists)

    def audio_next(self, db, cur, done=None):
        level = json.loads(session["level"])
        session["level"] = json.dumps(level + 1)
        q = db.queryone(
                f"SELECT {','.join(self.audio_keys)} "
                f"FROM {self.trials_table} WHERE project=? AND "
                "level_number=? AND trial_number=? AND lang=?",
                (self.project_key, level + 1, cur['trial_number'], cur['lang']))
        if q is None:
            q = self.audio_done
            self.audio_async(*done(True))
        elif done and done():
            q = self.audio_done
        q = self.audio_trial_dict(q)
        session["q"] = json.dumps(q)
        return self.audio_url(q["filename"])

    def audio_start(self, db):
        if "user" not in session:
            abort(400)
        elif "cur" in session:
            cur, q = map(lambda x: self.audio_url(json.loads(x)["filename"]), (
                session["cur"], session["q"]))
            return json.dumps({
                "cur": cur, "next": {1: q}, "name": session["username"],
                "has_results": json.loads(session["level"]) > 1})
        lang, trial_number = json.loads(session["requested"])
        if trial_number is not None:
            cur = [db.queryone(
                    f"SELECT {','.join(self.audio_keys)} "
                    f"from {self.trials_table} WHERE project=? AND "
                    "level_number=1 AND lang=? AND trial_number=?",
                    (self.project_key, lang, trial_number))]
        else:
            cur = db.queryall(
                f"SELECT {','.join(self.audio_keys)} "
                f"FROM {self.trials_table} WHERE project=? AND "
                "lang=? AND active=1 AND level_number=1 AND "
                "trial_number NOT IN ("
                    f"SELECT trial_number FROM {self.results_table} "
                    f"LEFT JOIN {self.trials_table} "
                    f"ON {self.results_table}.trial={self.trials_table}.id "
                    "WHERE subject=? AND level_number=1)",
                (self.project_key, lang, session["user"]))
        if len(cur) == 0 or None in cur:
            abort(400)
        cur = self.audio_trial_dict(random.choice(cur))
        session["cur"] = json.dumps(cur)
        # levels 1 indexed
        session["level"] = json.dumps(1)
        return json.dumps({
            "cur": self.audio_url(cur["filename"]), "has_results": False,
            "next": {1: self.audio_next(db, cur)}, "name": session["username"]})

    def audio_parse(self, db, rowid, fpath, answer, dump=False):
        def wrapped(dump=False):
            if dump:
                return (db, rowid, fpath, answer)
            reply = self.asr.recognize(fpath, answer)
            db.execute(
                f"INSERT INTO {self.asr_table} (ref, data) VALUES (?, ?)",
                (rowid, json.dumps(reply)))
            return self.completion_condition(reply, answer)
        if dump:
            return wrapped()
        return wrapped

    def audio_result(self, db):
        if "user" not in session or "file" not in request.files:
            abort(400)
        file = request.files["file"]
        if file.filename == "":
            abort(400)
        cur = json.loads(session["cur"])
        fname = f"sin_{session['user']}_{cur['id']}_{uuid.uuid4()}"
        fpath = os.path.join(upload_location, fname)
        file.save(fpath)
        rowid = db.execute(
            f"INSERT INTO {self.results_table} "
            "(subject, trial, reply_filename) VALUES (?, ?, ?)",
            (session["user"], cur["id"], fname))
        session["cur"] = session["q"]
        return json.dumps({1: self.audio_next(
            db, json.loads(session["cur"]),
            self.audio_parse(db, rowid, fpath, cur["answer"]))})

    # delayed by one level because of preloading
    def completion_condition(self, reply, answer):
        return self.proportion_correct(reply, answer) == 0

    def proportion_correct(self, reply, answer):
        reply = set(reply.split(" "))
        correct, total = 0, 0
        for options in answer.split(" "):
            total += 1
            for option in options.split("/"):
                if option in reply:
                    correct += 1
                    break
        return correct / max(total, 1)

    @staticmethod
    def map_answer(f, answer, delimitors=" /"):
        sep = ([len(s) for s in answer.split(d)] for d in delimitors)
        sep = sorted((sum(i[:j + 1]) + j, d) for i, d in zip(
            sep, delimitors) for j in range(len(i)))
        sep = zip([(0, '')] + [(i + 1, d) for i, d in sep[:-1]], (
            i[0] for i in sep[:-1]))
        return "".join(j + f(answer[i:k]) for (i, j), k in sep)

    def audio_plotter(self, db, query="1", args=()):
        results = db.queryall(
            f"SELECT {self.trials_table}.snr, {self.asr_table}.data, "
            f"{self.trials_table}.answer FROM {self.results_table} "
            f"LEFT JOIN {self.trials_table} "
                f"ON {self.results_table}.trial={self.trials_table}.id "
            f"LEFT JOIN {self.asr_table} "
                f"ON {self.results_table}.id={self.asr_table}.ref "
            f"WHERE project=? AND {self.asr_table}.data IS NOT NULL AND "
            f"{query}", (self.project_key,) + tuple(args))
        if len(results) == 0:
            abort(400)
        results = [(snr, self.proportion_correct(
            json.loads(reply), answer)) for snr, reply, answer in results]
        return self.flask_png(*zip(*results))

    def audio_recognized(self, db):
        if "user" not in session:
            abort(400)
        return self.audio_recognize(
            db, f" WHERE project=? AND {self.results_table}.subject=?",
            (self.project_key, session["user"]))

    def result_fields(self):
        return {
            "time": "users.t",
            "subject": f"{self.results_table}.subject",
            "username": "users.username",
            "upload": f"{self.results_table}.reply_filename",
            "transcript": f"{self.asr_table}.data",
            "prompt": f"{self.trials_table}.filename",
            "answer": f"{self.trials_table}.answer",
            "trial_number": f"{self.trials_table}.trial_number",
        }

    def audio_recognize(self, db, query="", args=()):
        transcription = db.queryall(
            "SELECT "
                f"{','.join(self.result_fields[1])} "
            f"FROM {self.results_table} "
                f"LEFT JOIN {self.trials_table} "
                    f"ON {self.results_table}.trial={self.trials_table}.id "
                "LEFT JOIN users ON subject=users.id "
                f"LEFT JOIN {self.asr_table} "
                    f"ON {self.results_table}.id={self.asr_table}.ref"
            f"{query}", args)
        keys = self.result_fields[0]
        return json.dumps([dict(zip(keys, i)) for i in transcription])

    def asr(self, path):
        raise NotImplementedError()

    def flask_png(self, x, y):
        raise NotImplementedError()

class AudioAnnotatedBP(AudioBP):
    def __init__(self, *a, **kw):
        fields = self.result_fields()
        fields["annotations"] = f"{self.annotations_table}.data"
        self.result_fields = lambda: fields
        super().__init__(*a, **kw)
        self._route_db("/reset", methods=["POST"])(self.audio_reset)
        self._route_db("/effort", methods=["POST"])(self.audio_effort)

    def audio_plotter(self, db, query="1", args=()):
        results = db.queryall(
            f"SELECT {self.trials_table}.snr, {self.annotations_table}.data "
            f"FROM {self.results_table} "
            f"LEFT JOIN {self.trials_table} ON "
                f"{self.results_table}.trial={self.trials_table}.id "
            f"LEFT JOIN {self.annotations_table} ON "
                f"{self.results_table}.id={self.annotations_table}.ref "
            f"WHERE {self.annotations_table}.data IS NOT NULL "
            f"AND {self.annotations_table}.data != '' AND "
            f"{self.trials_table}.project=? AND {query}",
            (self.project_key,) + tuple(args))
        if len(results) == 0:
            abort(400)
        results = [(snr, json.loads(data)) for snr, data in results]
        results = [(snr, sum(data) / len(data)) for snr, data in results]
        return self.flask_png(*zip(*results))

    def audio_parse(self, db, rowid, fpath, answer, dump=False, data=None):
        def wrapped(dump=False):
            nonlocal data
            data = data or request.args["annotations"]
            if dump:
                return (db, rowid, fpath, answer, True, data)
            db.execute(
                f"INSERT INTO {self.annotations_table} (ref, data) VALUES "
                "(?, ?)", (rowid, data))
            return False # audiologist can end test when they want to
        if dump:
            return wrapped()
        return wrapped

    def audio_start(self, db):
        res = json.loads(super().audio_start(db))
        res["answer"] = [
                json.loads(session[i])["answer"] for i in ("cur", "q")]
        return json.dumps(res)

    def audio_result(self, db):
        if "annotations" not in request.args:
            abort(400)
        res = json.loads(super().audio_result(db))
        res["answer"] = json.loads(session["q"])["answer"]
        return json.dumps(res)

    def audio_recognize(self, db, query="", args=()):
        res = super().audio_recognize(db, (
            f" LEFT JOIN {self.annotations_table} ON "
                f"{self.results_table}.id = {self.annotations_table}.ref"
            f"{query}"), args)
        res = json.loads(res)
        res = [{**i, "annotations": [] if i["annotations"] is None else
                json.loads(i["annotations"])} for i in res]
        return json.dumps(res)

    def audio_async(self, *args):
        return self.audio_parse(*args)

    def audio_reset(self, db):
        session.pop("cur", None)
        session["requested"] = json.dumps([
            json.loads(session.pop("requested", None))[0], None])
        return ""

    def audio_effort(self, db):
        if "user" not in session or "v" not in request.args:
            abort(400)
        try:
            effort = int(effort).get("v")
        except ValueError:
            abort(400)
        db.execute(
            "INSERT INTO user_info (user, info_key, value) "
            "VALUES (?, 'effort', ?)",
            (int(session["user"]), effort))
        return ""

class AudioScatterBP:
    @staticmethod
    @bytes_png
    def flask_png(x, y):
        return scatter_results(x, y)

class AudioLogisticBP:
    @staticmethod
    @bytes_png
    def flask_png(x, y):
        return logistic_results(x, y) if len(x) > 1 else scatter_results(x, y)

class AudioNormalizedBP(AudioBP):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from asr import whisper_normalizer
        self.normalizer = whisper_normalizer

    def proportion_correct(self, reply, answer):
        return super().proportion_correct(
            self.normalizer(reply["text"]),
            self.map_answer(self.normalizer, answer))

class AudioWhisperBP(AudioNormalizedBP):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from asr import WhisperASR
        self.whisper_asr = WhisperASR()

    def asr(self, path, answer):
        return self.whisper_asr.recognize(path)

class AudioPromptedWhisperBP(AudioNormalizedBP):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from asr import PromptedWhisperASR
        self.prompted_whisper_asr = PromptedWhisperASR()

    def asr(self, path, answer):
        return self.prompted_whisper_asr.recognize(
            path, answer.replace("/", " "))

# class AudioResultsBP(AudioWhisperBP):
# class AudioResultsBP(AudioPromptedWhisperBP):
class AudioResultsBP(AudioAnnotatedBP):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._route_db("/plot")(self.audio_plot)
        self._route_db("/upload/<fname>")(self.upload)

    def audio_recognized(self, db):
        if request.args.get("user", None) == "all":
            return self.audio_recognize(
                    db, f" WHERE project=?", (self.project_key,))
        if "user" not in session:
            abort(400)
        user = request.args.get("user", session["user"])
        return self.audio_recognize(
            db, f" WHERE project=? AND {self.results_table}.subject=?",
            (self.project_key, user))

    def audio_plot(self, db):
        user = request.args.get("user", session["user"])
        if user == "all":
            return self.audio_plotter(db)
        return self.audio_plotter(
                db, f"{self.results_table}.subject=?", (user,))

    def upload(self, db, fname):
        return send_from_directory(upload_location, fname)

class AudioConferenceBP(AudioWhisperBP, AudioResultsBP):
    def audio_parse(self, db, rowid, fpath, answer, dump=False):
        def wrapped(dump=False):
            if dump:
                return (db, rowid, fpath, answer)
            reply = self.asr.recognize(fpath, answer)
            db.execute(
                f"INSERT INTO {self.asr_table} (ref, data) VALUES (?, ?)",
                (rowid, json.dumps(reply)))
            return False
        if dump:
            return wrapped()
        return wrapped

class AudioNopBP(AudioLogisticBP, AudioConferenceBP):
    def audio_parse(self, db, rowid, fpath, answer, dump=False, data=None):
        def wrapped(dump=False):
            if dump:
                return (db, rowid, fpath, answer, True, data)
            return False
        if dump:
            return wrapped()
        return wrapped

    def audio_async(self, *args):
        return self.audio_parse(*args)

class AudioWhisperDebugBP(AudioResultsBP):
    def audio_next(self, db, cur, done=False):
        print(f'answer is "{cur["answer"]}"')
        return super().audio_next(db, cur, done)

    def proportion_correct(self, reply, answer):
        res = super().proportion_correct(reply, answer)
        print(f'heard "{reply}": {res}')
        return res

    def audio_async(self, db, rowid, fpath, answer):
        return self.audio_parse(db, rowid, fpath, answer, True)

# class AudioLogisticWhisperBP(AudioLogisticBP, AudioWhisperDebugBP):
# class AudioLogisticWhisperBP(AudioLogisticBP, AudioWhisperBP):
class AudioOutputBP(AudioLogisticBP, AudioResultsBP):
    pass
