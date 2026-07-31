def relpath(*args):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), *args)

# http://flask.pocoo.org/docs/0.11/patterns/sqlite3/
import json
import os.path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from absl import flags
from flask import g

flags.DEFINE_string(
    "sql_log_file",
    "experiments_log.txt",
    "Path to an append-only SQL replay log file.",
)


def get_sql_log_path():
    """Return the configured SQL log path, falling back safely if flags are not parsed yet."""
    try:
        return flags.FLAGS.sql_log_file
    except Exception:
        return "experiments_log.txt"


def log_sql_call(operation, query, args=()):
    """Append a timestamped SQL call to a replay log.

    Each log entry is a JSON object containing the timestamp, operation type,
    SQL text, and parameter values. The log is append-only and intended for
    recreating database activity from this point forward.
    """
    try:
        log_path = get_sql_log_path()
        if not log_path:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "query": query,
            "args": list(args) if args else [],
        }

        # Ensure the file exists first, then make it append-only once created.
        # This uses the Linux filesystem feature requested by the user.
        if not os.path.exists(log_path):
            with open(log_path, "a", encoding="utf-8"):
                pass
            try:
                subprocess.run(["chattr", "+a", log_path], check=True, capture_output=True, text=True)
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
            f.flush()
    except Exception:
        # Never let logging break the request path.
        pass

class Database:
    # creates database if it doesn't exist; set up by schema
    def __init__(self, app, database, schema='', init=[]):
        self.database = os.path.abspath(database)
        self.init = init
        if not os.path.exists(database):
          if schema:
            with app.app_context():
                db = self.get()
                with app.open_resource(schema, mode='r') as f:
                    db.cursor().executescript(f.read())
                db.commit()
          else:
            raise ValueError('Can not create database without schema.')

        self.app = app
        if app:
          app.teardown_appcontext(lambda e: self.close())

        # Update database with any changes to metadata CSV files
        with app.app_context():
            self.db_init_hook()

    # returns a database connection
    def get(self):
        db = getattr(g, "_database", None)
        if db is None:
            db = g._database = sqlite3.connect(self.database, timeout=10.0) # timeout for multiple users
            for i in self.init:
                self.execute(i)
        return db

    def queryall(self, query, args=()):
        log_sql_call("queryall", query, args)
        cur = self.get().execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return rv

    def queryone(self, query, args=()):
        log_sql_call("queryone", query, args)
        cur = self.get().execute(query, args)
        rv = cur.fetchone()
        cur.close()
        return rv

    def execute(self, query, args=()):
        log_sql_call("execute", query, args)
        con = self.get()
        cur = con.cursor()
        cur.execute(query, args)
        con.commit()
        res = cur.lastrowid
        cur.close()
        return res or None

    def close(self):
        db = getattr(g, '_database', None)
        if db is not None:
             db.close()

    def db_init_hook(self):
        pass

from flask import Blueprint
import functools

# TODO?: redo? document?
class DatabaseBP(Blueprint):
    def __init__(self, db_path, schema_path, name, url_prefix=None):
        super().__init__(name, __name__, url_prefix=url_prefix)
        self._db_paths = (db_path, schema_path)
        self.record(lambda setup: self._bind_db(setup.app))

    def _route_db(self, *a, **kw):
        def wrapper(f):
            @functools.wraps(f)
            def wrapped(*ra, **kra):
                return f(self._blueprint_db, *ra, **kra)
            return self.route(*a, **kw)(wrapped)
        return wrapper

    def _bind_db(self, app):
        self._blueprint_db = None

